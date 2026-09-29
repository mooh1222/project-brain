#!/usr/bin/env python3
"""Project Brain release artifact 빌드·검증 (#107).

    python tools/release.py build --tag v0.1.0
    python tools/release.py smoke --tag v0.1.0                 # 로컬 dist/release/<tag>
    python tools/release.py smoke --tag v0.1.0 --from-release  # GitHub Release URL

build는 커밋된 HEAD만 `git archive`로 떠서 빌드한다 — 작업 트리의 미추적·미커밋 파일이
wheel에 섞이지 않는다. 산출물은 wheel, uv.lock에서 뽑은 runtime constraints, 둘의
SHA256SUMS 세 개다. smoke는 격리된 임시 uv tool 환경에 artifact만으로 설치해 버전·
도움말·import 위치·프로젝트 installer 2회 멱등을 확인한다. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from email.parser import Parser
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RELEASE_BASE_URL = "https://github.com/mooh1222/project-brain/releases/download"
DIST_NAME = "project-brain"
CONSOLE_SCRIPT = ("project-brain", "project_brain.cli:main")
TEMPLATES_PREFIX = "project_brain/templates/"
_SOURCE_TEMPLATES = "src/project_brain/templates"
_EXECUTABLE = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
_INSTALL_REPORT_KEYS = ("created", "updated", "removed", "adopted", "skipped")
_PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?==[^\s;]+(\s*;.*)?$"
)
_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")


class ReleaseError(RuntimeError):
    pass


# ── 이름 규약 ─────────────────────────────────────────────────────────────


def version_from_tag(tag: str) -> str:
    match = _TAG.fullmatch(tag)
    if match is None:
        raise ValueError(f"release tag must look like v0.1.0: {tag!r}")
    return match.group(1)


def wheel_name(version: str) -> str:
    return f"project_brain-{version}-py3-none-any.whl"


def constraints_name(version: str) -> str:
    return f"{DIST_NAME}-{version}-constraints.txt"


CHECKSUMS_NAME = "SHA256SUMS"


# ── 결정론 검사 ───────────────────────────────────────────────────────────


def tracked_template_modes(repo_root: Path, rev: str) -> dict[str, bool]:
    """커밋 rev의 설치 템플릿 → wheel 안 경로와 실행 비트 여부."""
    result = subprocess.run(
        ["git", "-C", str(repo_root), "ls-tree", "-r", "-z", rev, "--", _SOURCE_TEMPLATES],
        check=True,
        capture_output=True,
    )
    modes: dict[str, bool] = {}
    for entry in result.stdout.decode("utf-8").split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t", 1)
        mode = meta.split(" ", 1)[0]
        modes[path.removeprefix("src/")] = mode == "100755"
    return modes


def inspect_wheel(wheel: Path, expected_templates: dict[str, bool], version: str) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(wheel) as archive:
        infos = {info.filename: info for info in archive.infolist() if not info.is_dir()}
        dist_info = f"project_brain-{version}.dist-info"
        metadata_name = next(
            (name for name in infos if name.endswith(".dist-info/METADATA")), None
        )
        if metadata_name is None:
            problems.append("missing dist-info METADATA")
        else:
            metadata = Parser().parsestr(archive.read(metadata_name).decode("utf-8"))
            if metadata["Version"] != version:
                problems.append(
                    f"metadata version {metadata['Version']} != release version {version}"
                )
            if metadata["Name"] != DIST_NAME:
                problems.append(f"metadata name {metadata['Name']} != {DIST_NAME}")
        entry_points_name = f"{dist_info}/entry_points.txt"
        scripts = configparser.ConfigParser()
        if entry_points_name in infos:
            scripts.read_string(archive.read(entry_points_name).decode("utf-8"))
        name, target = CONSOLE_SCRIPT
        if not scripts.has_section("console_scripts") or \
                scripts.get("console_scripts", name, fallback=None) != target:
            problems.append(f"missing console script: {name} = {target}")
    if "project_brain/cli.py" not in infos:
        problems.append("missing module: project_brain/cli.py")

    shipped = {
        name: bool((info.external_attr >> 16) & _EXECUTABLE)
        for name, info in infos.items()
        if name.startswith(TEMPLATES_PREFIX)
    }
    for path in sorted(set(expected_templates) - set(shipped)):
        problems.append(f"missing template: {path}")
    for path in sorted(set(shipped) - set(expected_templates)):
        problems.append(f"untracked template: {path}")
    for path in sorted(set(shipped) & set(expected_templates)):
        if shipped[path] != expected_templates[path]:
            expected = "executable" if expected_templates[path] else "non-executable"
            problems.append(f"executable bit mismatch: {path} (expected {expected})")
    return problems


def constraint_problems(text: str) -> list[str]:
    problems: list[str] = []
    pins = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _PIN.fullmatch(line)
        if match is None:
            problems.append(f"unpinned constraint: {line}")
            continue
        if _normalize(match.group("name")) == DIST_NAME:
            problems.append(f"constraints must not pin {DIST_NAME} itself")
            continue
        pins += 1
    if pins == 0 and not problems:
        problems.append("constraints file has no pins")
    return problems


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def installed_version_problems(
    constraints: str,
    installed: dict[str, str],
    marker_applies: Callable[[str], bool],
) -> list[str]:
    """이 환경에 적용되는 모든 pin이 tool env에 그 버전으로 깔렸는지.

    constraints는 여러 Python·플랫폼 분기를 함께 담으므로 marker는 설치 대상
    인터프리터 기준으로 평가해야 한다(marker_applies 주입).
    """
    versions = {_normalize(name): version for name, version in installed.items()}
    problems: list[str] = []
    for raw in constraints.splitlines():
        line = raw.strip()
        if _PIN.fullmatch(line) is None:
            continue
        requirement, _, marker = (part.strip() for part in line.partition(";"))
        if marker and not marker_applies(marker):
            continue
        name, pinned = requirement.split("==", 1)
        name = _normalize(name.split("[", 1)[0])
        if name not in versions:
            problems.append(f"constrained {name} {pinned} is not installed")
        elif versions[name] != pinned:
            problems.append(f"installed {name} {versions[name]} != constrained {pinned}")
    return problems


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_checksums(paths: list[Path], output: Path) -> Path:
    """`shasum -a 256 -c`와 호환되는 형식. 파일명은 output 디렉토리 기준."""
    lines = [f"{_sha256(path)}  {path.name}\n" for path in paths]
    output.write_text("".join(lines), encoding="utf-8")
    return output


def checksum_problems(checksums: Path) -> list[str]:
    problems: list[str] = []
    entries = [line.split("  ", 1) for line in checksums.read_text().splitlines() if line]
    if not entries:
        return ["checksum file lists no artifacts"]
    for digest, name in entries:
        path = checksums.parent / name
        if not path.is_file():
            problems.append(f"missing file: {name}")
        elif _sha256(path) != digest:
            problems.append(f"checksum mismatch: {name}")
    return problems


def idempotent_install_problems(report: dict) -> list[str]:
    problems: list[str] = []
    if report.get("ok") is not True:
        problems.append("second install did not report ok")
    for key in _INSTALL_REPORT_KEYS:
        if key not in report:
            problems.append(f"second install report lacks {key}")
        elif report[key]:
            problems.append(f"second install {key}: {report[key]!r}")
    return problems


def _record_entries(record: str) -> dict[str, str]:
    entries = {}
    for line in record.splitlines():
        path, _, rest = line.partition(",")
        if path.startswith("project_brain/"):
            entries[path] = rest
    return entries


def record_problems(wheel_record: str, installed_record: str) -> list[str]:
    """tool env에 깔린 엔진 파일이 checksum으로 검증한 wheel과 같은 바이트인지(RECORD 해시)."""
    installed = _record_entries(installed_record)
    return [
        f"installed file differs from verified wheel: {path}"
        for path, digest in sorted(_record_entries(wheel_record).items())
        if installed.get(path) != digest
    ]


def installed_mode_problems(desired: dict[str, bool], project: Path) -> list[str]:
    """installer가 주입한 파일의 실행 비트가 원본 템플릿과 같은지. desired: 목적지 → 원본 실행 여부."""
    problems = []
    for relative, executable in sorted(desired.items()):
        path = project / relative
        if not path.is_file():
            problems.append(f"installed file missing: {relative}")
        elif bool(path.stat().st_mode & stat.S_IXUSR) != executable:
            problems.append(f"installed executable bit differs from template: {relative}")
    return problems


# ── build ────────────────────────────────────────────────────────────────


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, text=True, capture_output=True, **kwargs)


def _pyproject_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def _produce_artifacts(repo_root: Path, staging: Path, version: str) -> None:
    """커밋된 HEAD만 떠서 wheel과 runtime constraints를 staging에 만든다."""
    with tempfile.TemporaryDirectory(prefix="project-brain-source-") as tmp:
        source = Path(tmp)
        archive = subprocess.run(
            ["git", "-C", str(repo_root), "archive", "--format=tar", "HEAD"],
            check=True, capture_output=True,
        ).stdout
        subprocess.run(["tar", "-x", "-C", str(source)], input=archive, check=True)
        _run(["uv", "build", "--wheel", "--out-dir", str(staging), str(source)])
        # --locked: pyproject와 어긋난 lock이면 조용히 옛 pin을 내보내지 않고 실패한다.
        _run([
            "uv", "export", "--project", str(source), "--locked", "--no-dev",
            "--no-emit-project", "--no-hashes", "--no-header", "--format", "requirements-txt",
            "--output-file", str(staging / constraints_name(version)),
        ])


def build(tag: str, out_root: Path, repo_root: Path = REPO_ROOT) -> dict:
    version = version_from_tag(tag)
    if _pyproject_version(repo_root) != version:
        raise ReleaseError(f"pyproject version {_pyproject_version(repo_root)} != {version}")
    dirty = _run(["git", "-C", str(repo_root), "status", "--porcelain",
                  "--untracked-files=no"]).stdout
    if dirty.strip():
        raise ReleaseError("tracked files have uncommitted changes:\n" + dirty)
    out_dir = out_root / tag
    if out_dir.exists():
        raise ReleaseError(f"output directory already exists: {out_dir}")
    commit = _run(["git", "-C", str(repo_root), "rev-parse", "HEAD"]).stdout.strip()

    # 검사를 모두 통과한 산출물만 out_dir로 옮긴다 — 실패해도 반쪽 artifact가 남지 않는다.
    with tempfile.TemporaryDirectory(prefix="project-brain-release-") as tmp:
        staging = Path(tmp)
        _produce_artifacts(repo_root, staging, version)
        wheel = staging / wheel_name(version)
        constraints = staging / constraints_name(version)
        if not wheel.is_file():
            raise ReleaseError(f"expected wheel was not built: {wheel.name}")
        problems = inspect_wheel(wheel, tracked_template_modes(repo_root, "HEAD"), version)
        problems += constraint_problems(constraints.read_text(encoding="utf-8"))
        if problems:
            raise ReleaseError("release artifact check failed:\n" + "\n".join(problems))
        write_checksums([wheel, constraints], staging / CHECKSUMS_NAME)
        artifacts = {path.name: _sha256(path) for path in (wheel, constraints)}
        out_dir.mkdir(parents=True)
        for path in (wheel, constraints, staging / CHECKSUMS_NAME):
            shutil.copyfile(path, out_dir / path.name)
    return {
        "ok": True,
        "tag": tag,
        "commit": commit,
        "out_dir": str(out_dir),
        "artifacts": artifacts,
        "checksums": CHECKSUMS_NAME,
    }


# ── smoke ────────────────────────────────────────────────────────────────


def _download(url: str, destination: Path) -> Path:
    with urllib.request.urlopen(url, timeout=120) as response, \
            destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return destination


def _isolated_env(tmp: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if key not in {"PYTHONPATH", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}}
    env["UV_TOOL_DIR"] = str(tmp / "tools")
    env["UV_TOOL_BIN_DIR"] = str(tmp / "bin")
    return env


# tool env 안에서 돈다: import 위치, 설치된 배포·RECORD, 그 인터프리터 기준 marker 평가,
# 설치본 installer가 주입할 목적지와 원본 템플릿의 실행 비트.
_TOOL_ENV_PROBE = """
import importlib.metadata, json, stat, sys
try:
    from packaging.markers import Marker
except ImportError as exc:
    sys.exit(f"tool env has no 'packaging' to evaluate constraint markers: {exc}")
import project_brain
from project_brain import installer
markers = json.load(sys.stdin)
desired = installer._desired_files(project="smoke", brain_root="brain",
                                   default_branch="", repo="")
print(json.dumps({
    "import_file": project_brain.__file__,
    "installed": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
    "record": importlib.metadata.distribution("project-brain").read_text("RECORD"),
    "markers": {m: Marker(m).evaluate() for m in markers},
    "desired_modes": {
        dest: bool(src.stat().st_mode & stat.S_IXUSR) for dest, (src, _, _) in desired.items()
    },
}))
"""


def _constraint_markers(constraints: str) -> list[str]:
    markers = set()
    for raw in constraints.splitlines():
        line = raw.strip()
        if _PIN.fullmatch(line) is not None and ";" in line:
            markers.add(line.partition(";")[2].strip())
    return sorted(markers)


def _check(condition: bool, message: str, problems: list[str]) -> None:
    if not condition:
        problems.append(message)


def smoke(tag: str, out_root: Path, from_release: bool, repo_root: Path = REPO_ROOT) -> dict:
    version = version_from_tag(tag)
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="project-brain-smoke-") as tmp_name:
        tmp = Path(tmp_name)
        if from_release:
            base = f"{RELEASE_BASE_URL}/{tag}"
            artifacts = tmp / "artifacts"
            artifacts.mkdir()
            for name in (CHECKSUMS_NAME, wheel_name(version), constraints_name(version)):
                _download(f"{base}/{name}", artifacts / name)
            # 소비자 안내와 같은 명령: wheel·constraints 둘 다 release URL로 설치한다.
            # URL로 다시 받은 wheel이 검증본과 같은지는 아래 RECORD 대조가 확인한다.
            wheel_source = f"{base}/{wheel_name(version)}"
            constraints_source = f"{base}/{constraints_name(version)}"
        else:
            artifacts = out_root / tag
            wheel_source = str(artifacts / wheel_name(version))
            constraints_source = str(artifacts / constraints_name(version))
        problems += checksum_problems(artifacts / CHECKSUMS_NAME)
        if problems:
            raise ReleaseError("checksum verification failed:\n" + "\n".join(problems))
        verified_wheel = artifacts / wheel_name(version)
        if from_release:
            # 게시된 wheel을 main이 아니라 tag 커밋의 템플릿과 대조한다.
            problems += inspect_wheel(
                verified_wheel, tracked_template_modes(repo_root, tag), version
            )

        env = _isolated_env(tmp)
        workdir = tmp / "work"
        workdir.mkdir()
        _run(["uv", "tool", "install", wheel_source, "--constraints", constraints_source],
             env=env, cwd=workdir)
        executable = tmp / "bin" / "project-brain"

        version_out = _run([str(executable), "--version"], env=env, cwd=workdir).stdout
        _check(version_out.strip() == f"project-brain {version}",
               f"--version printed {version_out.strip()!r}", problems)
        help_out = _run([str(executable), "--help"], env=env, cwd=workdir).stdout
        _check("install" in help_out and "--version" in help_out,
               "--help does not list install and --version", problems)

        constraints_text = (artifacts / constraints_name(version)).read_text(encoding="utf-8")
        tool_python = tmp / "tools" / DIST_NAME / "bin" / "python"
        tool_env = json.loads(_run(
            [str(tool_python), "-c", _TOOL_ENV_PROBE],
            input=json.dumps(_constraint_markers(constraints_text)),
            env=env, cwd=workdir,
        ).stdout)
        imported = Path(tool_env["import_file"]).resolve()
        _check(imported.is_relative_to((tmp / "tools").resolve()),
               f"project_brain imported from outside the tool env: {imported}", problems)
        _check(not imported.is_relative_to(repo_root.resolve()),
               f"project_brain imported from the source checkout: {imported}", problems)
        with zipfile.ZipFile(verified_wheel) as archive:
            wheel_record = archive.read(
                f"project_brain-{version}.dist-info/RECORD").decode("utf-8")
        problems += record_problems(wheel_record, tool_env["record"])
        problems += installed_version_problems(
            constraints_text, tool_env["installed"], tool_env["markers"].__getitem__
        )

        project = tmp / "project"
        project.mkdir()
        install = [str(executable), "install", "--target", str(project), "--project", "smoke"]
        first = json.loads(_run(install, env=env, cwd=workdir).stdout)
        _check(first.get("ok") is True and bool(first.get("created")),
               "first install did not create managed files", problems)
        second = json.loads(_run(install, env=env, cwd=workdir).stdout)
        problems += idempotent_install_problems(second)
        problems += installed_mode_problems(tool_env["desired_modes"], project)

    if problems:
        raise ReleaseError("smoke failed:\n" + "\n".join(problems))
    return {
        "ok": True,
        "tag": tag,
        "source": wheel_source if from_release else str(artifacts),
        "version": version_out.strip(),
        "import_path_in_tool_env": True,
        "installed_matches_verified_wheel": True,
        "constrained_packages_match": True,
        "installed_files": len(tool_env["desired_modes"]),
        "second_install_changes": {key: second[key] for key in _INSTALL_REPORT_KEYS},
    }


def _error_detail(exc: Exception) -> str:
    detail = str(exc)
    stderr = getattr(exc, "stderr", None)
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    if stderr:
        detail += "\n" + stderr
    return detail


def main(argv: list[str] | None = None) -> int:
    default_out = REPO_ROOT / "dist" / "release"
    parser = argparse.ArgumentParser(prog="tools/release.py")
    commands = parser.add_subparsers(dest="command", required=True)
    build_parser = commands.add_parser("build", help="HEAD에서 release artifact를 만든다")
    build_parser.add_argument("--tag", required=True)
    build_parser.add_argument("--out", type=Path, default=default_out,
                              help="artifact 상위 디렉토리. 산출물은 <out>/<tag>/")
    smoke_parser = commands.add_parser("smoke", help="격리된 tool 환경에 설치해 확인한다")
    smoke_parser.add_argument("--tag", required=True)
    source = smoke_parser.add_mutually_exclusive_group()
    source.add_argument("--out", type=Path, default=default_out,
                        help="build --out과 같은 상위 디렉토리. <out>/<tag>/를 설치한다")
    source.add_argument("--from-release", action="store_true",
                        help="GitHub Release URL에서 내려받아 설치")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            report = build(args.tag, args.out)
        else:
            report = smoke(args.tag, args.out, args.from_release)
    except (ReleaseError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "error": _error_detail(exc)},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
