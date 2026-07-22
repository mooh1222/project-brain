"""install — 프로젝트에 config + 스킬을 멱등 설치하고 manifest로 추적한다.

산출물:
  1. .project-brain.json — 없으면 생성, 있으면 보존(누락 키만 옵션값으로 보충).
  2. .agents/skills/<project>-brain-{query,ingest,session-ingest,audit}/...
     — templates/<skill>/ 디렉토리를 통째 walk·렌더 주입(SKILL.md + references/ + scripts/).
  3. .project-brain-manifest.json — 심은 파일 경로+sha256.

파일 단위 보존(hwi_PKM 멱등): 디스크 해시가 manifest 기록과 일치할 때만 갱신(도구 소유),
불일치(사용자 수정)·manifest 밖(사용자 소유)은 보존. (--force·채택은 Task 3에서 추가.)
스킬 런타임에 안 쓰이는 개발 자산(test_*.py)·죽은 산출물(fixtures/)·생성물(__pycache__/.pyc)은
주입하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

from project_brain.config import CONFIG_FILENAME

MANIFEST_FILENAME = ".project-brain-manifest.json"
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# 스킬 키 → 디렉토리 접미. templates/<key>/ 가 소스.
_SKILLS = {
    "query": "brain-query",
    "ingest": "brain-ingest",
    "session-ingest": "brain-session-ingest",
    "audit": "brain-audit",
}

_TEXT_SUFFIXES = {".md", ".py", ".js", ".sh", ".json"}


class InstallConflictError(RuntimeError):
    """안전한 재설치를 보장할 수 없어 어떤 쓰기도 시작하지 않은 상태."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_text(text: str, *, project: str, brain_root: str,
                default_branch: str = "", repo: str = "") -> str:
    """텍스트의 치환 변수를 채운다. {{VAR}} 토큰이라 순서 무관."""
    return (text.replace("{{REPO}}", repo)
                .replace("{{DEFAULT_BRANCH}}", default_branch)
                .replace("{{BRAIN_ROOT}}", brain_root)
                .replace("{{PROJECT}}", project))


def _excluded(rel: Path) -> bool:
    """install 미주입: 개발 자산·죽은 산출물·생성물."""
    parts = set(rel.parts)
    if "__pycache__" in parts or "fixtures" in parts:
        return True
    if rel.suffix == ".pyc":
        return True
    if rel.name.startswith("test_") and rel.suffix == ".py":
        return True
    return False


def _rendered_bytes(src: Path, *, project: str, brain_root: str,
                    default_branch: str, repo: str) -> bytes:
    """텍스트면 렌더 후 utf-8 바이트, 아니면 원본 바이트(바이너리 복사)."""
    if src.suffix in _TEXT_SUFFIXES:
        text = render_text(src.read_text(encoding="utf-8"), project=project,
                           brain_root=brain_root, default_branch=default_branch, repo=repo)
        return text.encode("utf-8")
    return src.read_bytes()


def _preserve_executable_mode(src: Path, dst: Path) -> bool:
    """템플릿의 실행 비트만 도구가 쓴 설치 파일에 맞춘다."""
    executable_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    source_mode = stat.S_IMODE(src.stat().st_mode)
    destination_mode = stat.S_IMODE(dst.stat().st_mode)
    desired_mode = (destination_mode & ~executable_bits) | (source_mode & executable_bits)
    if desired_mode == destination_mode:
        return False
    dst.chmod(desired_mode)
    return True


def _desired_files(*, project: str, brain_root: str,
                   default_branch: str, repo: str) -> dict[str, tuple[Path, bytes, str]]:
    desired = {}
    for skill, suffix in _SKILLS.items():
        src_root = _TEMPLATES_DIR / skill
        if not src_root.is_dir():
            continue
        skill_dir_name = f"{project}-{suffix}"
        for src in sorted(src_root.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(src_root)
            if _excluded(rel):
                continue
            rel_key = str(Path(".agents") / "skills" / skill_dir_name / rel)
            rendered = _rendered_bytes(
                src, project=project, brain_root=brain_root,
                default_branch=default_branch, repo=repo,
            )
            desired[rel_key] = (src, rendered, _sha256_bytes(rendered))
    return desired


def _managed_roots(project: str) -> tuple[Path, ...]:
    return tuple(
        Path(".agents") / "skills" / f"{project}-{suffix}"
        for suffix in _SKILLS.values()
    )


def _preflight_control_file(path: Path) -> bool:
    """제어 파일을 따라가지 않고 검사하고, 존재 여부를 돌려준다."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(mode):
        raise InstallConflictError(f"{path.name}: 제어 경로가 심링크임")
    if not stat.S_ISREG(mode):
        raise InstallConflictError(f"{path.name}: 제어 경로가 일반 파일이 아님")
    return True


def _safe_managed_path(target_root: Path, rel_key: str,
                       allowed_roots: tuple[Path, ...],
                       *, require_regular_leaf: bool = False) -> Path:
    if not isinstance(rel_key, str) or not rel_key:
        raise InstallConflictError(f"{rel_key!r}: 안전하지 않은 관리 경로")
    rel = Path(rel_key)
    if rel.is_absolute() or ".." in rel.parts:
        raise InstallConflictError(f"{rel_key}: 안전하지 않은 관리 경로")
    if not any(rel != root and rel.parts[:len(root.parts)] == root.parts
               for root in allowed_roots):
        raise InstallConflictError(f"{rel_key}: 안전하지 않은 관리 경로")

    cursor = target_root
    for part in rel.parts[:-1]:
        cursor = cursor / part
        try:
            mode = cursor.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise InstallConflictError(
                f"{rel_key}: 부모 심링크가 대상 루트 밖 또는 다른 위치를 가리킴"
            )
        if not stat.S_ISDIR(mode):
            raise InstallConflictError(
                f"{rel_key}: 부모 경로 {cursor}가 디렉터리가 아님"
            )
    dst = target_root / rel
    try:
        mode = dst.lstat().st_mode
    except FileNotFoundError:
        return dst
    if stat.S_ISLNK(mode):
        raise InstallConflictError(f"{rel_key}: 관리 파일이 심링크임")
    if require_regular_leaf and not stat.S_ISREG(mode):
        raise InstallConflictError(f"{rel_key}: 관리 경로가 일반 파일이 아님")
    return dst


def _preflight_retired(target_root: Path, manifest_files: dict,
                       desired_keys: set[str], allowed_roots: tuple[Path, ...]):
    retired = []
    for rel_key in sorted(set(manifest_files) - desired_keys):
        recorded = manifest_files[rel_key]
        if (not isinstance(recorded, str) or len(recorded) != 64
                or any(ch not in "0123456789abcdef" for ch in recorded)):
            raise InstallConflictError(f"{rel_key}: manifest SHA-256 기록이 올바르지 않음")
        dst = _safe_managed_path(target_root, rel_key, allowed_roots)
        if not dst.exists():
            retired.append((rel_key, dst, False))
            continue
        if not dst.is_file():
            raise InstallConflictError(f"{rel_key}: retired 관리 경로가 일반 파일이 아님")
        on_disk = _sha256_bytes(dst.read_bytes())
        if on_disk != recorded:
            raise InstallConflictError(
                f"{rel_key}: 사용자 수정된 retired 관리 파일은 삭제할 수 없음"
            )
        retired.append((rel_key, dst, True))
    return retired


def _preflight_migration_destinations(
        retired: list[tuple[str, Path, bool]], manifest_files: dict,
        desired: dict[str, tuple[Path, bytes, str]], desired_paths: dict[str, Path],
        *, force: bool) -> None:
    """retired 정본을 지우기 전에 desired 목적지가 전부 적용 가능한지 확인한다.

    retired가 없는 일반 재설치는 사용자 파일을 ``skipped``하는 기존 정책을 유지한다.
    migration 중에는 그 skip이 정본 유실을 만들 수 있으므로 같은 상태를 충돌로 승격한다.
    """
    if not retired:
        return
    for rel_key, (_, _, rendered_hash) in desired.items():
        dst = desired_paths[rel_key]
        if not dst.exists():
            continue
        if not dst.is_file():
            raise InstallConflictError(
                f"{rel_key}: migration 목적지 충돌 — 일반 파일이 아님; retired 파일을 보존하고 중단"
            )
        on_disk = _sha256_bytes(dst.read_bytes())
        if on_disk == rendered_hash:
            continue  # manifest 밖이라도 렌더 결과와 같으면 이후 adopt 가능
        recorded = manifest_files.get(rel_key)
        if recorded == on_disk or (recorded is not None and force):
            continue
        if recorded is None:
            reason = "manifest 밖 사용자 파일이며 렌더 결과와 다름"
        else:
            reason = "manifest 추적 파일이 사용자 수정됐고 force=false"
        raise InstallConflictError(
            f"{rel_key}: migration 목적지 충돌 — {reason}; retired 파일을 보존하고 중단"
        )


def install(target, *, project: str, brain_root: str = "brain",
            default_branch: str = "", repo: str = "", force: bool = False) -> dict:
    """target에 설치한다.

    ``removed``는 실제로 unlink한 retired 관리 파일만 담는다. 이미 없던 retired 파일은
    manifest key만 정리하므로 ``removed``에 넣지 않는다.
    """
    target = Path(target).resolve()
    report = {"config": "kept", "created": [], "updated": [],
              "removed": [], "adopted": [], "skipped": []}

    cfg_path = target / CONFIG_FILENAME
    manifest_path = target / MANIFEST_FILENAME
    config_exists = _preflight_control_file(cfg_path)
    manifest_exists = _preflight_control_file(manifest_path)

    # 1. config를 읽고 유효값만 계산한다. retired preflight 전에는 쓰지 않는다.
    config_bytes = None
    if config_exists:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        project = cfg.get("project") or project
        brain_root = cfg.get("brain_root", brain_root)
        default_branch = cfg.get("default_branch", default_branch)
        repo = cfg.get("repo", repo)
        # 누락 키 보충: 옵션/기본으로 들어온 값이 있는데 config에 칸이 없으면 채운다.
        # 기존 키는 안 건드리고(보존 원칙 유지), 빈 값은 안 적어 무의미한 갱신을 막는다.
        # 미보충 시 다음 install이 빈 값으로 렌더해 스킬이 깨지는 footgun 차단.
        backfill = {k: v for k, v in (("project", project), ("brain_root", brain_root),
                    ("default_branch", default_branch), ("repo", repo))
                    if v and k not in cfg}
        if backfill:
            cfg.update(backfill)
            config_bytes = (json.dumps(cfg, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            report["config"] = "updated"
    else:
        config_bytes = (json.dumps(
            {"project": project, "brain_root": brain_root,
             "default_branch": default_branch, "repo": repo},
            ensure_ascii=False, indent=2,
        ) + "\n").encode("utf-8")
        report["config"] = "created"

    # 2. manifest와 현재 템플릿의 원하는 파일 집합을 계산한다.
    manifest = {"files": {}}
    if manifest_exists:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("files", {})  # 구버전·손상 manifest 방어(KeyError 차단)
    if not isinstance(manifest.get("files"), dict):
        raise InstallConflictError("manifest files는 객체여야 함")
    desired = _desired_files(
        project=project, brain_root=brain_root,
        default_branch=default_branch, repo=repo,
    )
    allowed_roots = _managed_roots(project)

    # 3. 삭제·생성·갱신 후보를 모두 검사한 뒤에만 쓰기를 시작한다.
    retired = _preflight_retired(
        target, manifest["files"], set(desired), allowed_roots,
    )
    desired_paths = {
        rel_key: _safe_managed_path(
            target, rel_key, allowed_roots, require_regular_leaf=True,
        )
        for rel_key in desired
    }
    _preflight_migration_destinations(
        retired, manifest["files"], desired, desired_paths, force=force,
    )

    if config_bytes is not None:
        cfg_path.write_bytes(config_bytes)

    for rel_key, dst, exists in retired:
        if exists:
            dst.unlink()
            report["removed"].append(str(dst))
        manifest["files"].pop(rel_key, None)

    # 4. 원하는 파일을 주입한다(기존 파일 보존 의미는 유지).
    for rel_key, (src, rendered, rendered_hash) in desired.items():
        dst = desired_paths[rel_key]
        recorded = manifest["files"].get(rel_key)
        if dst.exists():
            on_disk = _sha256_bytes(dst.read_bytes())
            if on_disk == rendered_hash:
                if recorded != rendered_hash:
                    report["adopted"].append(str(dst))
                elif _preserve_executable_mode(src, dst):
                    report["updated"].append(str(dst))
                manifest["files"][rel_key] = rendered_hash
                continue
            if recorded == on_disk or (recorded is not None and force):
                dst.write_bytes(rendered)
                _preserve_executable_mode(src, dst)
                report["updated"].append(str(dst))
            else:
                report["skipped"].append(str(dst))
                continue
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(rendered)
            _preserve_executable_mode(src, dst)
            report["created"].append(str(dst))
        manifest["files"][rel_key] = rendered_hash

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report
