"""Content-bound release identity, separate from consumer Git revision and P0 foundation.

The release builder supplies provenance from its committed archive. This is an
integrity contract for a trusted wheel, not an artifact signature or sandbox.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import shutil
import stat
import subprocess
import sys
from types import CodeType
from pathlib import Path

IDENTITY_FILE = "_release_identity.json"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_FIELDS = {"scheme", "version", "source_commit", "content_sha256"}
_PROCESS_IDENTITY: dict | None = None
_EXECUTED_CODE: dict[str, set[CodeType]] | None = None
_EXECUTION_SCRIPTS = {"run_ingest_batch.py", "run_ingest.sh", "engine_python.py",
                      "assemble_notes.py", "finalize_ingest.py", "finalize_ingest.sh"}


def _file_state(value: object) -> tuple:
    # Reads can update atime; only replacement/content/mode changes invalidate identity.
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def _bootstrap_release(executed: dict[str, set[CodeType]]) -> None:
    global _EXECUTED_CODE
    _EXECUTED_CODE = executed
    capture_release_engine()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def normalize_release_identity(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("release engine_identity fields invalid")
    if value["scheme"] != "release-v1":
        raise ValueError("release engine_identity scheme invalid")
    if not isinstance(value["version"], str) or not value["version"]:
        raise ValueError("release engine_identity version invalid")
    if not isinstance(value["source_commit"], str) or not _COMMIT.fullmatch(value["source_commit"]):
        raise ValueError("release engine_identity source_commit invalid")
    if not isinstance(value["content_sha256"], str) or not _SHA.fullmatch(value["content_sha256"]):
        raise ValueError("release engine_identity content_sha256 invalid")
    return dict(value)


def _inventory(package: Path) -> dict:
    rows = {}
    for path in sorted(package.rglob("*")):
        relative = path.relative_to(package)
        if "__pycache__" in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError(f"release package symlink: {relative}")
        if path.is_dir() or relative.as_posix() == IDENTITY_FILE:
            continue
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"release package nonregular file: {relative}")
        content = path.read_bytes()
        if _file_state(before) != _file_state(path.stat()):
            raise ValueError(f"release package changed while reading: {relative}")
        rows[relative.as_posix()] = {
            "sha256": hashlib.sha256(content).hexdigest(),
            "executable": bool(before.st_mode & 0o111),
        }
    return rows


def write_release_identity(package: Path, source_commit: str, version: str) -> dict:
    """Build only: call on the archive before wheel creation, never an installation."""
    payload = {"scheme": "release-v1", "version": version,
               "source_commit": source_commit, "files": _inventory(package)}
    payload["content_sha256"] = hashlib.sha256(_canonical(payload)).hexdigest()
    identity = normalize_release_identity({key: payload[key] for key in _FIELDS})
    (package / IDENTITY_FILE).write_bytes(_canonical(payload) + b"\n")
    return identity


def read_release_identity(package: Path) -> dict:
    """Verify all package bytes/modes, including templates, against build provenance."""
    path = package / IDENTITY_FILE
    if path.is_symlink():
        raise ValueError("release identity symlink")
    try:
        original = path.read_bytes()
        payload = json.loads(original)
    except (OSError, ValueError) as exc:
        raise ValueError("release identity unavailable; use a content-bound release, "
                         "or the original checkout for legacy runs") from exc
    if not isinstance(payload, dict) or set(payload) != _FIELDS | {"files"}:
        raise ValueError("release identity manifest fields invalid")
    identity = normalize_release_identity({key: payload[key] for key in _FIELDS})
    digest = hashlib.sha256(_canonical({key: value for key, value in payload.items()
                                       if key != "content_sha256"})).hexdigest()
    if digest != identity["content_sha256"]:
        raise ValueError("release identity digest mismatch")
    observed = _inventory(package)
    files = payload["files"]
    if not isinstance(files, dict) or set(files) != set(observed):
        raise ValueError("release package file set mismatch")
    for name, actual in observed.items():
        if not isinstance(files[name], dict) or set(files[name]) != {"sha256", "executable"}:
            raise ValueError(f"release package inventory invalid: {name}")
        if actual["sha256"] != files[name]["sha256"]:
            raise ValueError(f"release package content mismatch: {name}")
        if actual["executable"] != files[name]["executable"]:
            raise ValueError(f"release package mode mismatch: {name}")
    if path.read_bytes() != original:
        raise ValueError("release identity changed while reading")
    return identity


def capture_release_engine(expected: dict | None = None) -> dict:
    """Capture actual imported installation; repeat at execution/write boundaries."""
    global _PROCESS_IDENTITY
    import project_brain

    package = Path(project_brain.__file__).resolve().parent
    before = package.stat()
    identity = read_release_identity(package)
    distribution = importlib.metadata.distribution("project-brain")
    if distribution.version != identity["version"] or Path(
        distribution.locate_file("project_brain")
    ).resolve() != package:
        raise ValueError("release distribution/import mismatch")
    direct = distribution.read_text("direct_url.json")
    if direct and json.loads(direct).get("dir_info", {}).get("editable"):
        raise ValueError("release identity requires a non-editable installation")
    for name, module in tuple(sys.modules.items()):
        if name == "project_brain" or name.startswith("project_brain."):
            origin = getattr(module, "__file__", None)
            if origin is not None and not Path(origin).resolve().is_relative_to(package):
                raise ValueError(f"release loaded module origin mismatch: {name}")
            if origin and Path(origin).suffix == ".py" and (
                _EXECUTED_CODE is None or str(Path(origin).resolve()) not in _EXECUTED_CODE
            ):
                raise ValueError(f"release executed code unavailable: {name}")
    # Keep every executed module code, including a module later removed/reloaded.
    # Cache deletion or replacement cannot change this in-memory observation.
    for filename, executed in tuple((_EXECUTED_CODE or {}).items()):
        source_code = compile(Path(filename).read_bytes(), filename, "exec",
                              dont_inherit=True, optimize=sys.flags.optimize)
        if any(code != source_code for code in executed):
            raise ValueError(f"release executed code/source mismatch: {filename}")
    if _file_state(before) != _file_state(package.stat()):
        raise ValueError("release engine root changed while reading")
    state = {"engine_root": str(package), "engine_sha": identity["source_commit"],
             "engine_root_device": before.st_dev, "engine_root_inode": before.st_ino,
             "engine_identity": identity}
    if expected is not None and normalize_release_identity(expected) != identity:
        raise ValueError("declared engine_identity does not match loaded release")
    if _PROCESS_IDENTITY is not None and state != _PROCESS_IDENTITY:
        raise ValueError("loaded release engine changed during execution")
    _PROCESS_IDENTITY = state
    return state


def verify_release_runtime(scripts: Path, repo_root: Path) -> None:
    """Reject stale or modified installed execution scripts; preserve user files."""
    from project_brain.config import load_config
    from project_brain.installer import _desired_files

    config = load_config(start=repo_root)
    if config is None:
        raise ValueError("release runtime project config missing")
    raw = json.loads(config["path"].read_text())
    desired = _desired_files(project=raw.get("project", ""),
                             brain_root=raw.get("brain_root", "brain"),
                             default_branch=raw.get("default_branch", ""),
                             repo=raw.get("repo", ""))
    expected_root = repo_root / ".agents/skills" / f"{raw.get('project', '')}-brain-ingest/scripts"
    if scripts.resolve() != expected_root.resolve():
        raise ValueError("release runtime location mismatch; run project-brain install")
    for relative, (source, content, _) in desired.items():
        path = repo_root / relative
        if path.parent != expected_root or path.name not in _EXECUTION_SCRIPTS:
            continue
        if (path.is_symlink() or not path.is_file() or path.read_bytes() != content
                or bool(path.stat().st_mode & 0o111) != bool(source.stat().st_mode & 0o111)):
            raise ValueError(f"release runtime mismatch: {path.name}; run project-brain install "
                             "and review skipped user changes without --force")


def verify_release_binding(binding: object) -> None:
    """Shared CLI/MutationService boundary; legacy bindings retain their contract."""
    from project_brain.transaction_receipt import ReleaseBatchBinding, normalize_batch_binding
    from project_brain.config import load_config

    normalized = normalize_batch_binding(binding)
    if not isinstance(normalized, ReleaseBatchBinding):
        return
    state = capture_release_engine(normalized.engine_identity)
    for field in ("engine_root", "engine_sha", "engine_root_device", "engine_root_inode"):
        if state[field] != getattr(normalized, field):
            raise ValueError(f"batch binding {field} mismatch")
    repo = Path(normalized.repo_root)
    config = load_config(start=repo)
    if config is None:
        raise ValueError("release runtime project config missing")
    scripts = repo / ".agents/skills" / f"{config['project']}-brain-ingest/scripts"
    verify_release_runtime(scripts, repo)


def verify_release_cli(expected: dict, repo_root: Path) -> None:
    """Bind the actual PATH CLI before baseline/audit can write derived files."""
    executable = shutil.which("project-brain")
    if executable is None:
        raise ValueError("release PATH CLI unavailable")
    try:
        result = subprocess.run([executable, "--engine-identity"], cwd=repo_root,
                                text=True, capture_output=True, timeout=30)
        observed = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError("release PATH CLI identity unavailable") from exc
    if result.returncode != 0 or observed != {"ok": True, **expected}:
        raise ValueError("release PATH CLI/runner engine mismatch; align PATH and PROJECT_BRAIN_PYTHON")
