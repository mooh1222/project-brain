"""P0 foundation baseline, immutable-state checks, and bound receipts."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import subprocess
import tempfile
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

import project_brain
from project_brain import cli, mutation, search_index, snapshot
from project_brain.installer import (
    CONFIG_FILENAME,
    MANIFEST_FILENAME,
    InstallConflictError,
    normalize_installer_report_path,
)
from project_brain.snapshot import SnapshotError
from project_brain.store import BrainStore


_SHA256 = frozenset("0123456789abcdef")
_CORE_PATHS = ("src/project_brain", "pyproject.toml", "uv.lock")
_BASELINE_KEYS = {
    "version",
    "purpose",
    "roots",
    "artifact_root",
    "artifact_inventory",
    "ignored_snapshots_inventory",
    "engine",
    "bb2",
    "corpus",
    "search_index",
    "runtime",
    "stale_set",
}
BB2_MANAGED_SKILL_ROOTS = (
    ".agents/skills/bb2-brain-query/",
    ".agents/skills/bb2-brain-ingest/",
    ".agents/skills/bb2-brain-session-ingest/",
    ".agents/skills/bb2-brain-audit/",
)
_INSTALL_CHANGE_FIELDS = ("created", "updated", "removed", "adopted", "skipped")


class FoundationError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        paths: tuple[Path, ...] = (),
        cause_code: str | None = None,
    ):
        self.code = code
        self.detail = detail
        self.paths = paths
        self.cause_code = cause_code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class TreeEntryReceipt:
    path: str
    entry_type: str
    mode: int
    size: int
    sha256: str


@dataclass(frozen=True)
class TreeReceipt:
    root: str
    entries: tuple[TreeEntryReceipt, ...]
    sha256: str


@dataclass(frozen=True)
class FoundationCommandSpec:
    id: str
    argv: tuple[str, ...]
    cwd: str
    env: tuple[tuple[str, str], ...]


def _fail(
    code: str,
    detail: str,
    *,
    paths: tuple[Path, ...] = (),
    cause_code: str | None = None,
) -> None:
    raise FoundationError(
        code,
        detail,
        paths=paths,
        cause_code=cause_code,
    )


def _from_snapshot(exc: SnapshotError, *, code: str | None = None) -> FoundationError:
    return FoundationError(
        code or exc.code,
        exc.detail,
        paths=exc.paths,
        cause_code=exc.code,
    )


def canonical_receipt_bytes(value: Mapping[str, object]) -> bytes:
    if not isinstance(value, Mapping):
        _fail("receipt_json_invalid", "receipt must be a JSON object")
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        _fail("receipt_json_invalid", f"receipt is not strict JSON: {exc}")
    return text.encode("utf-8") + b"\n"


def _normalized_report_arrays(
    report: Mapping[str, object],
) -> tuple[Path, dict[str, list[str]], list[str]]:
    target_raw = report.get("target_root")
    if not isinstance(target_raw, str):
        _fail("installer_report_invalid", "installer report target_root is missing")
    target = Path(target_raw)
    normalized: dict[str, list[str]] = {}
    try:
        for field in _INSTALL_CHANGE_FIELDS:
            values = report.get(field)
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                _fail("installer_report_invalid", f"installer report {field} must be a string array")
            normalized[field] = [
                normalize_installer_report_path(target, value)
                for value in values
            ]
        controls = report.get("installer_control_paths")
        if not isinstance(controls, list) or not all(isinstance(value, str) for value in controls):
            _fail(
                "installer_report_invalid",
                "installer report installer_control_paths must be a string array",
            )
        normalized_controls = [
            normalize_installer_report_path(target, value)
            for value in controls
        ]
    except InstallConflictError as exc:
        _fail("installer_report_path_invalid", f"installer report path: {exc}")
    return target, normalized, normalized_controls


def task15_stage_paths(report: Mapping[str, object]) -> list[str]:
    """Task 15가 stage할 수 있는 BB2 runtime/control 경로만 돌려준다."""
    if not isinstance(report, Mapping) or report.get("ok") is not True:
        _fail("installer_report_invalid", "installer report must have ok=true")
    _, arrays, controls = _normalized_report_arrays(report)
    if arrays["skipped"]:
        _fail("installer_skipped_paths", "installer skipped paths must be empty")
    if arrays["adopted"]:
        _fail("installer_adopted_paths", "installer adopted paths must be empty")
    if controls != [MANIFEST_FILENAME]:
        _fail(
            "installer_control_paths_invalid",
            "installer_control_paths must be exactly ['.project-brain-manifest.json']",
        )
    changes = arrays["created"] + arrays["updated"] + arrays["removed"]
    if len(changes) != len(set(changes)):
        _fail("installer_report_invalid", "installer change arrays contain duplicate paths")
    invalid = sorted(
        path
        for path in changes
        if not any(path.startswith(root) for root in BB2_MANAGED_SKILL_ROOTS)
    )
    if invalid:
        _fail(
            "managed_runtime_path_invalid",
            f"managed runtime path is outside the four BB2 skill roots: {invalid!r}",
        )
    return sorted(set(changes) | {MANIFEST_FILENAME})


def _safe_cached_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        _fail("cached_path_invalid", f"cached path is unsafe: {value!r}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or pure.as_posix() in {"", "."} or ".." in pure.parts:
        _fail("cached_path_invalid", f"cached path is unsafe: {value!r}")
    return pure.as_posix()


def validate_task15_cached_paths(
    *,
    preexisting_cached_paths: Sequence[str],
    cached_paths: Sequence[str],
    allowed_paths: Sequence[str],
) -> None:
    preexisting = [_safe_cached_path(path) for path in preexisting_cached_paths]
    if preexisting:
        _fail(
            "preexisting_cached_paths",
            f"refusing preexisting cached paths: {sorted(preexisting)!r}",
        )
    cached = [_safe_cached_path(path) for path in cached_paths]
    allowed = {_safe_cached_path(path) for path in allowed_paths}
    if not cached:
        _fail("empty_cached_paths", "empty cached path set after Task 15 staging")
    unexpected = sorted(set(cached) - allowed)
    if unexpected:
        _fail("cached_path_invalid", f"cached path is outside allowed paths: {unexpected!r}")
    if len(cached) != len(set(cached)):
        _fail("cached_path_invalid", "cached paths contain duplicates")


def _exact_absolute(path: Path, *, label: str) -> Path:
    path = Path(path)
    if not path.is_absolute() or path != Path(os.path.abspath(path)):
        _fail("foundation_path_invalid", f"{label} must be exact absolute: {path}")
    return path


def foundation_command_specs(
    *,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    installed_runtime: Path,
    smoke_root: Path,
    python_executable: Path,
) -> tuple[FoundationCommandSpec, ...]:
    engine_root = _exact_absolute(engine_root, label="engine_root")
    repo_root = _exact_absolute(repo_root, label="repo_root")
    brain_root = _exact_absolute(brain_root, label="brain_root")
    installed_runtime = _exact_absolute(installed_runtime, label="installed_runtime")
    smoke_root = _exact_absolute(smoke_root, label="smoke_root")
    python_executable = _exact_absolute(python_executable, label="python_executable")
    python = str(python_executable)
    pythonpath = str(engine_root / "src")
    common_env = (("PYTHONPATH", pythonpath),)
    cli = (python, "-m", "project_brain.cli")
    return (
        FoundationCommandSpec(
            id="installed-runtime-unittest",
            argv=(
                python,
                "-m",
                "unittest",
                "src.project_brain.templates.ingest.scripts.test_validate_foundation",
            ),
            cwd=str(engine_root),
            env=common_env + (("PROJECT_BRAIN_FOUNDATION_RUNTIME", str(installed_runtime)),),
        ),
        FoundationCommandSpec(
            id="bb2-checks",
            argv=(python, "-m", "unittest", "discover", "-s", "brain/checks", "-p", "test_*.py"),
            cwd=str(repo_root),
            env=common_env,
        ),
        FoundationCommandSpec(
            id="lint",
            argv=cli + ("lint", "--brain-root", str(brain_root)),
            cwd=str(repo_root),
            env=common_env,
        ),
        FoundationCommandSpec(
            id="audit-no-fetch",
            argv=cli + (
                "audit",
                "--brain-root",
                str(brain_root),
                "--repo-root",
                str(repo_root),
                "--no-fetch",
            ),
            cwd=str(repo_root),
            env=common_env,
        ),
        FoundationCommandSpec(
            id="eval",
            argv=cli + ("eval", "--brain-root", str(brain_root)),
            cwd=str(repo_root),
            env=common_env,
        ),
        FoundationCommandSpec(
            id="coverage-build-dry-smoke",
            argv=cli + (
                "build",
                "--notes",
                str(smoke_root / "notes.json"),
                "--coverage-file",
                str(smoke_root / "coverage.json"),
                "--objects-file",
                str(smoke_root / "objects.json"),
                "--brain-root",
                str(smoke_root / "brain"),
            ),
            cwd=str(repo_root),
            env=common_env,
        ),
    )


def _tree_receipt(root: Path, entries: tuple[snapshot.SafeTreeEntry, ...]) -> TreeReceipt:
    converted = tuple(TreeEntryReceipt(**asdict(entry)) for entry in entries)
    payload = {"entries": [asdict(entry) for entry in converted]}
    return TreeReceipt(
        root=str(root),
        entries=converted,
        sha256=hashlib.sha256(canonical_receipt_bytes(payload)).hexdigest(),
    )


def _tree_dict(receipt: TreeReceipt) -> dict[str, object]:
    return {
        "root": receipt.root,
        "entries": [asdict(entry) for entry in receipt.entries],
        "sha256": receipt.sha256,
    }


def capture_tree_receipt(
    root: Path,
    relative_paths: Collection[str],
    *,
    excluded_paths: Collection[Path] = (),
) -> TreeReceipt:
    root = Path(root)
    try:
        entries = snapshot.capture_tree_entries(
            root,
            relative_paths,
            excluded_paths=excluded_paths,
        )
    except SnapshotError as exc:
        raise _from_snapshot(exc, code="tree_path_invalid" if exc.code == "tree_path_invalid" else None) from exc
    return _tree_receipt(root, entries)


def _scan_tree_receipt(
    root: Path,
    *,
    excluded_paths: Collection[Path] = (),
) -> TreeReceipt:
    root = Path(root)
    try:
        entries = snapshot.scan_tree_entries(root, excluded_paths=excluded_paths)
    except SnapshotError as exc:
        raise _from_snapshot(exc) from exc
    return _tree_receipt(root, entries)


def _ignored_snapshots_receipt(
    ignored_snapshots_root: Path,
    artifact_root: Path,
) -> TreeReceipt:
    receipt = _scan_tree_receipt(
        ignored_snapshots_root,
        excluded_paths=(artifact_root,),
    )
    relative = artifact_root.relative_to(ignored_snapshots_root).as_posix()
    parts = PurePosixPath(relative).parts
    ancestors = {
        "/".join(parts[:index])
        for index in range(1, len(parts))
    }
    surviving_paths = {
        entry.path for entry in receipt.entries if entry.path not in ancestors
    }
    removable = {
        ancestor
        for ancestor in ancestors
        if not any(path.startswith(ancestor + "/") for path in surviving_paths)
    }
    if not removable:
        return receipt
    entries = tuple(
        entry for entry in receipt.entries if entry.path not in removable
    )
    payload = {"entries": [asdict(entry) for entry in entries]}
    return TreeReceipt(
        root=receipt.root,
        entries=entries,
        sha256=hashlib.sha256(canonical_receipt_bytes(payload)).hexdigest(),
    )


def _absolute_relative(root: Path, path: Path, *, label: str) -> str:
    path = Path(path)
    if not path.is_absolute() or path != Path(os.path.abspath(path)):
        _fail("artifact_inventory_invalid", f"{label} must be exact absolute: {path}")
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        _fail("artifact_inventory_invalid", f"{label} escapes artifact root: {path}")
    pure = PurePosixPath(relative)
    if relative in {"", "."} or pure.is_absolute() or ".." in pure.parts:
        _fail("artifact_inventory_invalid", f"unsafe {label}: {path}")
    return relative


def verify_artifact_inventory(
    artifact_root: Path,
    *,
    allowed_files: Collection[Path],
    verified_snapshot_root: Path | None = None,
) -> TreeReceipt:
    artifact_root = Path(artifact_root)
    verified_entries: dict[str, TreeEntryReceipt] = {}
    allowed_regular = {
        _absolute_relative(artifact_root, Path(path), label="allowed artifact")
        for path in allowed_files
    }
    if verified_snapshot_root is not None:
        verified_snapshot_root = Path(verified_snapshot_root)
        snapshot_relative = _absolute_relative(
            artifact_root,
            verified_snapshot_root,
            label="verified snapshot root",
        )
        try:
            verified_before = capture_tree_receipt(
                artifact_root,
                [snapshot_relative],
            )
            manifest_entry = next(
                entry
                for entry in verified_before.entries
                if entry.path == f"{snapshot_relative}/manifest.json"
            )
            snapshot.verify_snapshot(
                verified_snapshot_root,
                expected_manifest_sha256=manifest_entry.sha256,
            )
            verified_after = capture_tree_receipt(
                artifact_root,
                [snapshot_relative],
            )
            if verified_after != verified_before:
                _fail(
                    "artifact_inventory_invalid",
                    "verified snapshot changed during verification",
                    paths=(verified_snapshot_root,),
                )
            verified_entries = {
                entry.path: entry for entry in verified_after.entries
            }
        except (FoundationError, SnapshotError, StopIteration) as exc:
            cause = exc.code if isinstance(exc, (FoundationError, SnapshotError)) else None
            paths = getattr(exc, "paths", ())
            _fail(
                "artifact_inventory_invalid",
                f"verified snapshot inventory failed: {getattr(exc, 'detail', exc)}",
                paths=paths,
                cause_code=cause,
            )
        allowed_regular.update(
            entry.path
            for entry in verified_entries.values()
            if entry.entry_type == "regular"
        )
    _after_verified_snapshot_receipt_hook()
    try:
        receipt = _scan_tree_receipt(artifact_root)
    except FoundationError as exc:
        raise FoundationError(
            "artifact_inventory_invalid",
            f"artifact inventory is unsafe: {exc.detail}",
            paths=exc.paths,
            cause_code=exc.cause_code or exc.code,
        ) from exc
    actual_regular = {
        entry.path for entry in receipt.entries if entry.entry_type == "regular"
    }
    expected_directories = {
        parent.as_posix()
        for relative in allowed_regular
        for parent in PurePosixPath(relative).parents
        if parent.as_posix() not in {"", "."}
    }
    actual_directories = {
        entry.path for entry in receipt.entries if entry.entry_type == "directory"
    }
    actual_entries = {entry.path: entry for entry in receipt.entries}
    if any(
        actual_entries.get(path) != expected
        for path, expected in verified_entries.items()
    ):
        _fail(
            "artifact_inventory_invalid",
            "verified snapshot metadata changed before final artifact scan",
            paths=(verified_snapshot_root,) if verified_snapshot_root else (),
        )
    expected_snapshot_directories = {
        entry.path
        for entry in verified_entries.values()
        if entry.entry_type == "directory"
    }
    expected_directories.update(expected_snapshot_directories)
    if actual_regular != allowed_regular or actual_directories != expected_directories:
        unexpected = sorted(
            (actual_regular - allowed_regular)
            | (actual_directories - expected_directories)
        )
        missing = sorted(
            (allowed_regular - actual_regular)
            | (expected_directories - actual_directories)
        )
        _fail(
            "artifact_inventory_invalid",
            f"artifact inventory mismatch; unexpected={unexpected!r}, missing={missing!r}",
            paths=tuple(artifact_root / path for path in unexpected),
        )
    return receipt


def _after_verified_snapshot_receipt_hook() -> None:
    """Deterministic test seam before the final task artifact scan."""


def resolved_project_brain_file() -> Path:
    return Path(project_brain.__file__).resolve()


def resolved_cli_source_file() -> Path:
    return Path(cli.__file__).resolve()


def _root_identity(path: Path, *, label: str) -> dict[str, object]:
    path = Path(path)
    if not path.is_absolute() or path != Path(os.path.abspath(path)):
        _fail(
            "root_invalid",
            f"{label} root must be an exact normalized absolute path: {path}",
            paths=(path,),
        )
    try:
        descriptor = snapshot._open_absolute_directory(path, create=False)
    except SnapshotError as exc:
        raise _from_snapshot(exc, code="root_invalid") from exc
    try:
        current = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    return {
        "path": str(path),
        "device": current.st_dev,
        "inode": current.st_ino,
        "label": label,
    }


def _git_dict(receipt: snapshot.GitDirtReceipt) -> dict[str, object]:
    return {
        "root": receipt.root,
        "head": receipt.head,
        "status_sha256": receipt.status_sha256,
        "status_porcelain_v1_z_base64": base64.b64encode(receipt.status_bytes).decode("ascii"),
        "dirt_content_manifest": json.loads(receipt.content_manifest_bytes),
        "dirt_content_sha256": receipt.content_manifest_sha256,
    }


def _capture_git(root: Path, *, label: str) -> snapshot.GitDirtReceipt:
    try:
        return snapshot.capture_git_dirt_receipt(root, label=label)
    except SnapshotError as exc:
        raise _from_snapshot(exc) from exc


def _is_core_path(path: str) -> bool:
    return any(path == core or path.startswith(core + "/") for core in _CORE_PATHS)


def _reject_engine_core_dirt(receipt: snapshot.GitDirtReceipt) -> None:
    rows = json.loads(receipt.content_manifest_bytes)
    dirty = sorted({row["path"] for row in rows if _is_core_path(row["path"])})
    if dirty:
        _fail(
            "engine_core_dirty",
            f"engine core contains tracked or untracked dirt: {dirty!r}",
            paths=tuple(Path(receipt.root) / path for path in dirty),
        )


def _git_core_tree_sha(engine_root: Path, head: str) -> str:
    before = _root_identity(engine_root, label="engine")
    try:
        result = subprocess.run(
            ["git", "-C", str(engine_root), "ls-tree", "-r", "-z", head, "--", *_CORE_PATHS],
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        _fail("engine_core_invalid", f"cannot list engine tracked core: {exc}")
    if result.returncode != 0:
        _fail("engine_core_invalid", "cannot list engine tracked core")
    rows: list[dict[str, object]] = []
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            raw_mode, entry_type, raw_oid = metadata.split(b" ", 2)
            path = os.fsdecode(raw_path)
            mode = int(raw_mode, 8)
            oid = raw_oid.decode("ascii")
        except (ValueError, UnicodeError) as exc:
            _fail("engine_core_invalid", f"malformed tracked core entry: {exc}")
        if entry_type != b"blob" or not _is_core_path(path):
            _fail("engine_core_invalid", f"unexpected tracked core entry: {path!r}")
        blob = subprocess.run(
            ["git", "-C", str(engine_root), "cat-file", "blob", oid],
            capture_output=True,
            check=False,
        )
        if blob.returncode != 0:
            _fail("engine_core_invalid", f"cannot read tracked core blob: {path}")
        rows.append({"path": path, "mode": mode, "sha256": hashlib.sha256(blob.stdout).hexdigest()})
    if not rows:
        _fail("engine_core_invalid", "engine tracked core is empty")
    after = _root_identity(engine_root, label="engine")
    try:
        current_head = snapshot.verify_git_root_head(engine_root, label="engine_root")
    except SnapshotError as exc:
        raise _from_snapshot(exc, code="engine_core_invalid") from exc
    if before != after or current_head != head:
        _fail(
            "engine_core_invalid",
            "engine checkout changed during tracked core capture",
            paths=(engine_root,),
        )
    return hashlib.sha256(canonical_receipt_bytes({"entries": sorted(rows, key=lambda row: row["path"])})).hexdigest()


def _ensure_engine_checkout(engine_root: Path) -> tuple[str, str]:
    package_root = engine_root / "src/project_brain"
    import_file = Path(resolved_project_brain_file())
    cli_file = Path(resolved_cli_source_file())
    for label, path in (("import_file", import_file), ("cli_source_file", cli_file)):
        try:
            path.relative_to(package_root)
        except ValueError:
            _fail(
                "engine_checkout_mismatch",
                f"{label} does not belong to the designated engine checkout: {path}",
                paths=(path, engine_root),
            )
    return str(import_file), str(cli_file)


def _file_receipt(root: Path, relative: str, *, optional: bool = False) -> dict[str, object]:
    try:
        receipt = capture_tree_receipt(root, [relative])
    except FoundationError as exc:
        if optional and (exc.cause_code or exc.code) == "source_unavailable":
            return {"path": relative, "sha256": "", "size": 0, "mode": None}
        raise
    if len(receipt.entries) != 1 or receipt.entries[0].entry_type != "regular":
        _fail("file_receipt_invalid", f"expected one regular file: {root / relative}")
    entry = receipt.entries[0]
    return {"path": relative, "sha256": entry.sha256, "size": entry.size, "mode": entry.mode}


def _runtime_inventory(repo_root: Path) -> dict[str, object]:
    manifest_receipt = _file_receipt(repo_root, MANIFEST_FILENAME)
    try:
        raw = snapshot._read_regular(repo_root, MANIFEST_FILENAME)
        value = json.loads(raw)
        files = value["files"]
    except (SnapshotError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        _fail("runtime_manifest_invalid", f"invalid installer manifest: {exc}")
    if not isinstance(files, dict):
        _fail("runtime_manifest_invalid", "installer manifest files must be an object")
    managed: list[dict[str, object]] = []
    for path, recorded_sha in sorted(files.items()):
        if not isinstance(path, str) or not isinstance(recorded_sha, str):
            _fail("runtime_manifest_invalid", "managed path/hash must be strings")
        file_receipt = _file_receipt(repo_root, path)
        if recorded_sha != file_receipt["sha256"]:
            _fail(
                "runtime_manifest_mismatch",
                f"managed runtime hash differs from manifest: {path}",
                paths=(repo_root / path,),
            )
        managed.append({
            "path": path,
            "recorded_sha256": recorded_sha,
            "actual_sha256": file_receipt["sha256"],
            "mode": file_receipt["mode"],
            "size": file_receipt["size"],
        })
    return {"manifest_sha256": manifest_receipt["sha256"], "managed_files": managed}


def _capture_corpus(brain_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    objects = _scan_tree_receipt(brain_root / "objects")
    raw = _scan_tree_receipt(brain_root / "raw")
    store = BrainStore.load(brain_root)
    mutation_fingerprint = mutation.corpus_fingerprint(store)
    live_fingerprint = search_index.compute_corpus_fingerprint(store, brain_root)
    objects_after = _scan_tree_receipt(brain_root / "objects")
    raw_after = _scan_tree_receipt(brain_root / "raw")
    if objects.sha256 != objects_after.sha256 or raw.sha256 != raw_after.sha256:
        _fail("corpus_changed_during_capture", "corpus changed during foundation capture")
    db_before = _file_receipt(brain_root, ".brain-local/index.db")
    meta_fingerprint = search_index.read_meta_fingerprint(brain_root / ".brain-local/index.db")
    db_after = _file_receipt(brain_root, ".brain-local/index.db")
    if db_before != db_after:
        _fail("index_changed_during_capture", "index DB changed during foundation capture")
    return (
        {
            "mutation_fingerprint": mutation_fingerprint,
            "objects_tree_sha256": objects.sha256,
            "raw_tree_sha256": raw.sha256,
        },
        {
            "live_corpus_fingerprint": live_fingerprint,
            "meta_corpus_fingerprint": meta_fingerprint,
            "db_file_sha256": db_before["sha256"],
        },
    )


def _stale_receipt(brain_root: Path) -> dict[str, object]:
    receipt = _file_receipt(brain_root, ".brain-local/stale-set.json", optional=True)
    return {"sha256": receipt["sha256"]}


def capture_foundation_baseline(
    *,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    artifact_root: Path,
    ignored_snapshots_root: Path,
) -> dict[str, object]:
    engine_root = Path(engine_root)
    repo_root = Path(repo_root)
    brain_root = Path(brain_root)
    artifact_root = Path(artifact_root)
    ignored_snapshots_root = Path(ignored_snapshots_root)
    roots = {
        "engine": _root_identity(engine_root, label="engine"),
        "bb2": _root_identity(repo_root, label="bb2"),
        "brain": _root_identity(brain_root, label="brain"),
    }
    engine_git = _capture_git(engine_root, label="engine_root")
    _reject_engine_core_dirt(engine_git)
    import_file, cli_source_file = _ensure_engine_checkout(engine_root)
    engine = _git_dict(engine_git)
    engine.update({
        "core_paths": list(_CORE_PATHS),
        "core_tracked_tree_sha256": _git_core_tree_sha(engine_root, engine_git.head),
        "import_file": import_file,
        "cli_source_file": cli_source_file,
        "entrypoint": "project_brain.cli:main",
    })
    corpus, index = _capture_corpus(brain_root)
    runtime = _runtime_inventory(repo_root)
    try:
        artifact = _scan_tree_receipt(artifact_root)
    except FoundationError as exc:
        if (exc.cause_code or exc.code) != "source_unavailable":
            raise
        try:
            snapshot.verify_tree_path_absent(artifact_root)
        except SnapshotError as absent_exc:
            raise _from_snapshot(absent_exc) from absent_exc
        artifact = _tree_receipt(artifact_root, ())
    ignored = _ignored_snapshots_receipt(ignored_snapshots_root, artifact_root)
    ignored_dict = _tree_dict(ignored)
    ignored_dict["excluded_subtree"] = artifact_root.relative_to(ignored_snapshots_root).as_posix()
    # Corpus readers may materialize their persistent lock file. Capture user
    # dirt only after all read-only baseline collectors have run so verification
    # compares the state actually left by this capture.
    bb2 = _git_dict(_capture_git(repo_root, label="bb2_root"))
    return {
        "version": 1,
        "purpose": "p0-foundation-baseline",
        "roots": roots,
        "artifact_root": str(artifact_root),
        "artifact_inventory": _tree_dict(artifact),
        "ignored_snapshots_inventory": ignored_dict,
        "engine": engine,
        "bb2": bb2,
        "corpus": corpus,
        "search_index": index,
        "runtime": runtime,
        "stale_set": _stale_receipt(brain_root),
    }


def _decode_status(value: Mapping[str, object]) -> tuple[bytes, bytes]:
    try:
        status = base64.b64decode(value["status_porcelain_v1_z_base64"], validate=True)
    except (KeyError, TypeError, ValueError) as exc:
        _fail("baseline_invalid", f"invalid Git receipt: {exc}")
    # snapshot stores the canonical rows directly, not wrapped in an object.
    manifest = (
        json.dumps(
            value["dirt_content_manifest"],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    if (
        value.get("status_sha256") != hashlib.sha256(status).hexdigest()
        or value.get("dirt_content_sha256")
        != hashlib.sha256(manifest).hexdigest()
    ):
        _fail("baseline_invalid", "Git receipt hashes do not match their payloads")
    return status, manifest


def _git_changed_paths(root: Path, before: str, after: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "-z", before, after],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        _fail("bb2_head_invalid", "cannot derive BB2 commit path delta")
    return sorted(os.fsdecode(path) for path in result.stdout.split(b"\0") if path)


def _runtime_delta(before: Mapping[str, object], after: Mapping[str, object]) -> list[str]:
    before_rows = {row["path"]: row for row in before["managed_files"]}
    after_rows = {row["path"]: row for row in after["managed_files"]}
    return sorted(
        path
        for path in set(before_rows) | set(after_rows)
        if before_rows.get(path) != after_rows.get(path)
    )


def verify_foundation_invariants(
    baseline: Mapping[str, object],
    *,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    allowed_managed_paths: Collection[str],
    allowed_installer_control_paths: Collection[str],
    artifact_root: Path,
    ignored_snapshots_root: Path,
    allowed_artifact_files: Collection[Path],
    verified_snapshot_root: Path | None,
) -> dict[str, object]:
    if (
        not isinstance(baseline, Mapping)
        or set(baseline) != _BASELINE_KEYS
        or type(baseline.get("version")) is not int
        or baseline.get("version") != 1
        or baseline.get("purpose") != "p0-foundation-baseline"
    ):
        _fail("baseline_invalid", "foundation baseline top-level shape or purpose is invalid")
    errors: list[str] = []
    observed = {"expected_local_mutation": [], "bb2_commit_paths": []}
    caller_managed = sorted(set(allowed_managed_paths))
    caller_control = sorted(set(allowed_installer_control_paths))
    allowed = {
        "managed_runtime_paths": [],
        "installer_control_paths": caller_control,
    }

    def add(code: str) -> None:
        if code not in errors:
            errors.append(code)

    engine_root = Path(engine_root)
    repo_root = Path(repo_root)
    brain_root = Path(brain_root)
    artifact_root = Path(artifact_root)
    ignored_snapshots_root = Path(ignored_snapshots_root)
    if str(artifact_root) != baseline["artifact_root"]:
        add("artifact_root_mismatch")
    if str(ignored_snapshots_root) != baseline["ignored_snapshots_inventory"]["root"]:
        add("ignored_snapshots_root_mismatch")

    try:
        current_roots = {
            "engine": _root_identity(engine_root, label="engine"),
            "bb2": _root_identity(repo_root, label="bb2"),
            "brain": _root_identity(brain_root, label="brain"),
        }
        if current_roots != baseline["roots"]:
            add("root_identity_changed")
    except FoundationError:
        add("root_identity_changed")

    try:
        import_file, cli_file = _ensure_engine_checkout(engine_root)
        if import_file != baseline["engine"]["import_file"] or cli_file != baseline["engine"]["cli_source_file"]:
            add("engine_checkout_mismatch")
    except FoundationError:
        add("engine_checkout_mismatch")

    try:
        baseline_status, baseline_manifest = _decode_status(baseline["engine"])
        engine_git = snapshot.verify_git_dirt_preserved(
            engine_root,
            baseline_status_bytes=baseline_status,
            baseline_content_manifest_bytes=baseline_manifest,
            label="engine_root",
        )
        _reject_engine_core_dirt(engine_git)
        if engine_git.head != baseline["engine"]["head"]:
            add("engine_head_changed")
        if _git_core_tree_sha(engine_root, engine_git.head) != baseline["engine"]["core_tracked_tree_sha256"]:
            add("engine_core_changed")
    except FoundationError as exc:
        add("engine_core_dirty" if exc.code == "engine_core_dirty" else "engine_state_changed")
    except SnapshotError:
        add("engine_state_changed")

    runtime_current: dict[str, object] | None = None
    try:
        runtime_current = _runtime_inventory(repo_root)
        derived_managed = _runtime_delta(baseline["runtime"], runtime_current)
        allowed["managed_runtime_paths"] = derived_managed
        if derived_managed != caller_managed:
            add("managed_runtime_allowlist_mismatch")
    except (FoundationError, KeyError, TypeError):
        add("runtime_changed")
        derived_managed = []

    try:
        baseline_status, baseline_manifest = _decode_status(baseline["bb2"])
        bb2_git = snapshot.verify_git_dirt_preserved(
            repo_root,
            baseline_status_bytes=baseline_status,
            baseline_content_manifest_bytes=baseline_manifest,
            label="bb2_root",
        )
        if bb2_git.head != baseline["bb2"]["head"]:
            changed = _git_changed_paths(repo_root, baseline["bb2"]["head"], bb2_git.head)
            observed["bb2_commit_paths"] = changed
            if changed != sorted(set(derived_managed) | set(caller_control)):
                add("bb2_commit_paths_invalid")
        elif derived_managed or runtime_current != baseline["runtime"]:
            add("runtime_changed")
    except (FoundationError, SnapshotError, KeyError, TypeError):
        add("user_dirt_changed")

    try:
        current_objects = _scan_tree_receipt(brain_root / "objects")
        if current_objects.sha256 != baseline["corpus"]["objects_tree_sha256"]:
            add("objects_changed")
    except (FoundationError, KeyError, TypeError):
        add("objects_changed")

    try:
        current_raw = _scan_tree_receipt(brain_root / "raw")
        if current_raw.sha256 != baseline["corpus"]["raw_tree_sha256"]:
            add("raw_changed")
    except (FoundationError, KeyError, TypeError):
        add("raw_changed")

    try:
        current_db = _file_receipt(brain_root, ".brain-local/index.db")
        if current_db["sha256"] != baseline["search_index"]["db_file_sha256"]:
            add("index_db_changed")
    except (FoundationError, KeyError, TypeError):
        add("index_db_changed")

    try:
        corpus, index = _capture_corpus(brain_root)
        if corpus["objects_tree_sha256"] != baseline["corpus"]["objects_tree_sha256"]:
            add("objects_changed")
        if corpus["raw_tree_sha256"] != baseline["corpus"]["raw_tree_sha256"]:
            add("raw_changed")
        if corpus["mutation_fingerprint"] != baseline["corpus"]["mutation_fingerprint"]:
            add("corpus_fingerprint_changed")
        if index["db_file_sha256"] != baseline["search_index"]["db_file_sha256"]:
            add("index_db_changed")
        if index["live_corpus_fingerprint"] != baseline["search_index"]["live_corpus_fingerprint"]:
            add("index_input_changed")
        if index["meta_corpus_fingerprint"] != baseline["search_index"]["meta_corpus_fingerprint"]:
            add("index_meta_changed")
    except Exception:
        add("corpus_state_invalid")

    try:
        stale = _stale_receipt(brain_root)
        if stale != baseline["stale_set"]:
            observed["expected_local_mutation"] = ["brain/.brain-local/stale-set.json"]
    except FoundationError:
        add("stale_set_invalid")

    try:
        verify_artifact_inventory(
            artifact_root,
            allowed_files=allowed_artifact_files,
            verified_snapshot_root=verified_snapshot_root,
        )
    except FoundationError:
        add("unexpected_dirt_path")

    try:
        ignored = _ignored_snapshots_receipt(ignored_snapshots_root, artifact_root)
        if ignored.sha256 != baseline["ignored_snapshots_inventory"]["sha256"]:
            add("ignored_snapshots_changed")
    except (FoundationError, KeyError, TypeError):
        add("ignored_snapshots_changed")

    return {
        "ok": not errors,
        "errors": errors,
        "allowed_changes": allowed,
        "observed_changes": observed,
    }


def _validate_output_path(path: Path, *, label: str) -> tuple[int, str]:
    path = Path(path)
    if not path.is_absolute() or path != Path(os.path.abspath(path)) or path.name in {"", ".", ".."}:
        _fail(f"{label}_path_invalid", f"{label} path must be exact absolute: {path}")
    try:
        parent_fd = snapshot._open_absolute_directory(path.parent, create=True)
    except SnapshotError as exc:
        raise _from_snapshot(exc, code=f"{label}_parent_invalid") from exc
    return parent_fd, path.name


def _preflight_absent(parent_fd: int, name: str, *, label: str) -> None:
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if stat.S_ISLNK(current.st_mode):
        _fail(f"{label}_symlink", f"{label} output symlink exists")
    _fail(f"{label}_exists", f"{label} output already exists")


def _create_at(parent_fd: int, name: str, data: bytes, *, label: str) -> os.stat_result:
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        _fail(f"{label}_create_failed", f"{label} create failed: {exc}")
    created = os.fstat(descriptor)
    failure: BaseException | None = None
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                _fail(f"{label}_create_failed", f"{label} write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        created = os.fstat(descriptor)
    except (OSError, FoundationError) as exc:
        failure = exc
    finally:
        os.close(descriptor)
    if failure is not None:
        removed = _unlink_if_owned(parent_fd, name, created)
        detail = f"{label} create failed: {failure}"
        if not removed:
            detail += "; partial output could not be safely removed"
        raise FoundationError(
            f"{label}_create_failed",
            detail,
            cause_code=getattr(failure, "code", type(failure).__name__),
        ) from failure
    try:
        os.fsync(parent_fd)
    except OSError as exc:
        removed = _unlink_if_owned(parent_fd, name, created)
        detail = f"{label} parent fsync failed: {exc}"
        if not removed:
            detail += "; output could not be safely removed"
        raise FoundationError(
            f"{label}_create_failed",
            detail,
            cause_code=type(exc).__name__,
        ) from exc
    return created


def _unlink_if_owned(parent_fd: int, name: str, owned: os.stat_result) -> bool:
    try:
        cli._remove_linked_target_if_unchanged(
            parent_fd,
            target_name=name,
            linked_stat=owned,
        )
    except OSError:
        return False
    return True


def atomic_create_receipt(path: Path, value: Mapping[str, object]) -> str:
    data = canonical_receipt_bytes(value)
    digest = hashlib.sha256(data).hexdigest()
    parent_fd, name = _validate_output_path(path, label="receipt")
    try:
        _preflight_absent(parent_fd, name, label="receipt")
        _create_at(parent_fd, name, data, label="receipt")
    finally:
        os.close(parent_fd)
    return digest


def _binding_value(
    receipt_path: Path,
    receipt_sha: str,
    value: Mapping[str, object],
) -> dict[str, object]:
    if type(value.get("version")) is not int or value.get("version") != 1:
        _fail("binding_version_invalid", "receipt version must be integer 1")
    purpose = value.get("purpose")
    try:
        if purpose == "p0-foundation-baseline":
            binding_purpose = "p0-foundation-baseline-binding"
            engine_head = value["engine"]["head"]
            bb2_head = value["bb2"]["head"]
        elif purpose == "p0-foundation-gate":
            binding_purpose = "p0-foundation-gate-binding"
            engine_head = value["heads"]["engine"]
            bb2_head = value["heads"]["bb2_after"]
        else:
            _fail("binding_purpose_invalid", f"unsupported receipt purpose: {purpose!r}")
    except (KeyError, TypeError) as exc:
        _fail("binding_head_invalid", f"receipt head source is missing: {exc}")
    for label, head in (("engine_head", engine_head), ("bb2_head", bb2_head)):
        if not isinstance(head, str) or len(head) != 40 or any(ch not in _SHA256 for ch in head):
            _fail("binding_head_invalid", f"{label} must be lowercase 40-hex")
    return {
        "version": 1,
        "purpose": binding_purpose,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha,
        "engine_head": engine_head,
        "bb2_head": bb2_head,
    }


def _before_binding_create_hook() -> None:
    """Deterministic test seam immediately before the second exclusive create."""


def atomic_create_bound_receipt(
    *,
    receipt_path: Path,
    binding_path: Path,
    value: Mapping[str, object],
) -> tuple[str, str]:
    receipt_path = Path(receipt_path)
    binding_path = Path(binding_path)
    receipt_data = canonical_receipt_bytes(value)
    receipt_sha = hashlib.sha256(receipt_data).hexdigest()
    binding = _binding_value(receipt_path, receipt_sha, value)
    binding_data = canonical_receipt_bytes(binding)
    binding_sha = hashlib.sha256(binding_data).hexdigest()
    receipt_parent, receipt_name = _validate_output_path(
        receipt_path,
        label="receipt",
    )
    try:
        binding_parent, binding_name = _validate_output_path(
            binding_path,
            label="binding",
        )
        try:
            _preflight_absent(receipt_parent, receipt_name, label="receipt")
            _preflight_absent(binding_parent, binding_name, label="binding")
            created = _create_at(
                receipt_parent,
                receipt_name,
                receipt_data,
                label="receipt",
            )
            try:
                _before_binding_create_hook()
                _create_at(
                    binding_parent,
                    binding_name,
                    binding_data,
                    label="binding",
                )
            except (FoundationError, OSError) as exc:
                removed = _unlink_if_owned(
                    receipt_parent,
                    receipt_name,
                    created,
                )
                detail = f"binding_create_failed: {getattr(exc, 'detail', exc)}"
                if not removed:
                    detail += "; owned receipt could not be safely rolled back"
                raise FoundationError(
                    "binding_create_failed",
                    detail,
                    paths=(receipt_path, binding_path),
                    cause_code=getattr(exc, "code", type(exc).__name__),
                ) from exc
        finally:
            os.close(binding_parent)
    finally:
        os.close(receipt_parent)
    return receipt_sha, binding_sha


def _read_canonical_json(path: Path, *, label: str) -> tuple[dict[str, object], bytes]:
    try:
        data = snapshot._read_regular(path.parent, path.name)
        value = json.loads(data)
    except (SnapshotError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label}_invalid", f"cannot read {label}: {exc}", paths=(path,))
    if not isinstance(value, dict) or canonical_receipt_bytes(value) != data:
        _fail(f"{label}_invalid", f"{label} is not a canonical JSON object", paths=(path,))
    return value, data


def _parse_canonical_json_bytes(
    data: bytes,
    *,
    path: Path,
    label: str,
) -> dict[str, object]:
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label}_invalid", f"cannot parse {label}: {exc}", paths=(path,))
    if not isinstance(value, dict) or canonical_receipt_bytes(value) != data:
        _fail(f"{label}_invalid", f"{label} is not a canonical JSON object", paths=(path,))
    return value


def verify_bound_receipt(
    *,
    receipt_path: Path,
    binding_path: Path,
    expected_purpose: str,
) -> dict[str, object]:
    receipt_path = Path(receipt_path)
    binding_path = Path(binding_path)
    if any(
        not path.is_absolute() or path != Path(os.path.abspath(path))
        for path in (receipt_path, binding_path)
    ):
        _fail(
            "binding_path_invalid",
            "receipt and binding paths must be exact normalized absolute paths",
        )
    binding, _ = _read_canonical_json(binding_path, label="binding")
    expected_keys = {
        "version",
        "purpose",
        "receipt_path",
        "receipt_sha256",
        "engine_head",
        "bb2_head",
    }
    if (
        set(binding) != expected_keys
        or type(binding.get("version")) is not int
        or binding.get("version") != 1
    ):
        _fail("binding_invalid", "binding exact shape is invalid")
    if binding["purpose"] != expected_purpose:
        _fail("binding_invalid", "purpose mismatch")
    if binding["receipt_path"] != str(receipt_path):
        _fail("binding_invalid", "receipt_path mismatch")
    try:
        receipt_data = snapshot._read_regular(receipt_path.parent, receipt_path.name)
    except SnapshotError as exc:
        raise _from_snapshot(exc, code="receipt_invalid") from exc
    if binding["receipt_sha256"] != hashlib.sha256(receipt_data).hexdigest():
        _fail("binding_invalid", "receipt_sha256 mismatch")
    receipt = _parse_canonical_json_bytes(
        receipt_data,
        path=receipt_path,
        label="receipt",
    )
    expected = _binding_value(receipt_path, binding["receipt_sha256"], receipt)
    if expected["purpose"] != expected_purpose:
        _fail("binding_invalid", "purpose does not match receipt purpose")
    if binding["engine_head"] != expected["engine_head"]:
        _fail("binding_invalid", "engine_head mismatch")
    if binding["bb2_head"] != expected["bb2_head"]:
        _fail("binding_invalid", "bb2_head mismatch")
    return receipt


def _read_json_document(path: Path, *, label: str) -> tuple[dict[str, object], bytes]:
    path = _exact_absolute(path, label=label)
    try:
        data = snapshot._read_regular(path.parent, path.name)
        value = json.loads(data)
    except (SnapshotError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"{label}_invalid", f"cannot read {label}: {exc}", paths=(path,))
    if not isinstance(value, dict):
        _fail(f"{label}_invalid", f"{label} must be a JSON object", paths=(path,))
    return value, data


def _verify_named_bound_receipt(
    *,
    receipt_path: Path,
    binding_path: Path,
    purpose: str,
    label: str,
) -> tuple[dict[str, object], str]:
    try:
        value = verify_bound_receipt(
            receipt_path=receipt_path,
            binding_path=binding_path,
            expected_purpose=purpose,
        )
    except FoundationError as exc:
        if "receipt_sha256 mismatch" in exc.detail:
            _fail(
                f"{label}_sha256_mismatch",
                f"{label} bytes do not match immutable binding",
                paths=(Path(receipt_path), Path(binding_path)),
                cause_code=exc.code,
            )
        raise
    binding, _ = _read_canonical_json(Path(binding_path), label=f"{label}_binding")
    return value, str(binding["receipt_sha256"])


def validate_p0_project_config(repo_root: Path) -> None:
    config, _ = _read_json_document(repo_root / CONFIG_FILENAME, label="project_config")
    expected = {
        "project": "bb2",
        "brain_root": "brain",
        "default_branch": "develop",
        "repo": "bb2_client",
    }
    if config != expected:
        _fail(
            "project_config_mismatch",
            f"P0 config must be exact: expected={expected!r}, actual={config!r}",
            paths=(repo_root / CONFIG_FILENAME,),
        )


def _protected_artifact_receipt(
    artifact_root: Path,
    protected_files: Collection[Path],
) -> dict[str, object]:
    relative = sorted(
        _absolute_relative(artifact_root, Path(path), label="protected artifact")
        for path in protected_files
    )
    return _tree_dict(capture_tree_receipt(artifact_root, relative))


def capture_foundation_state(
    *,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    artifact_root: Path,
    ignored_snapshots_root: Path,
    protected_artifact_files: Collection[Path],
) -> dict[str, object]:
    """gate/handoff가 서로 exact 비교할 현재 상태를 새로 측정한다."""
    engine_root = _exact_absolute(engine_root, label="engine_root")
    repo_root = _exact_absolute(repo_root, label="repo_root")
    brain_root = _exact_absolute(brain_root, label="brain_root")
    artifact_root = _exact_absolute(artifact_root, label="artifact_root")
    ignored_snapshots_root = _exact_absolute(
        ignored_snapshots_root,
        label="ignored_snapshots_root",
    )
    roots = {
        "engine": _root_identity(engine_root, label="engine"),
        "bb2": _root_identity(repo_root, label="bb2"),
        "brain": _root_identity(brain_root, label="brain"),
    }
    engine_git = _capture_git(engine_root, label="engine_root")
    _reject_engine_core_dirt(engine_git)
    import_file, cli_source_file = _ensure_engine_checkout(engine_root)
    engine = _git_dict(engine_git)
    engine.update({
        "core_paths": list(_CORE_PATHS),
        "core_tracked_tree_sha256": _git_core_tree_sha(engine_root, engine_git.head),
        "import_file": import_file,
        "cli_source_file": cli_source_file,
        "entrypoint": "project_brain.cli:main",
    })
    corpus, index = _capture_corpus(brain_root)
    runtime = _runtime_inventory(repo_root)
    stale_set = _stale_receipt(brain_root)
    ignored = _ignored_snapshots_receipt(ignored_snapshots_root, artifact_root)
    ignored_value = _tree_dict(ignored)
    ignored_value["excluded_subtree"] = artifact_root.relative_to(
        ignored_snapshots_root
    ).as_posix()
    artifact_inventory = _protected_artifact_receipt(
        artifact_root,
        protected_artifact_files,
    )
    # Read-only collectors may create their persistent lock. Capture dirt last.
    bb2 = _git_dict(_capture_git(repo_root, label="bb2_root"))
    return {
        "roots": roots,
        "engine": engine,
        "bb2": bb2,
        "corpus": corpus,
        "search_index": index,
        "runtime": runtime,
        "stale_set": stale_set,
        "ignored_snapshots_inventory": ignored_value,
        "artifact_inventory": artifact_inventory,
    }


def _state_drift_codes(
    expected: Mapping[str, object],
    actual: Mapping[str, object],
) -> list[str]:
    errors: list[str] = []

    def add(code: str) -> None:
        if code not in errors:
            errors.append(code)

    try:
        if expected["roots"] != actual["roots"]:
            add("root_identity_changed")
        expected_engine = expected["engine"]
        actual_engine = actual["engine"]
        if expected_engine["head"] != actual_engine["head"]:
            add("engine_head_changed")
        for field in (
            "status_sha256",
            "status_porcelain_v1_z_base64",
            "dirt_content_manifest",
            "dirt_content_sha256",
        ):
            if expected_engine[field] != actual_engine[field]:
                add("engine_dirt_changed")
        if expected_engine["core_tracked_tree_sha256"] != actual_engine["core_tracked_tree_sha256"]:
            add("engine_core_changed")
        for field in ("import_file", "cli_source_file", "entrypoint"):
            if expected_engine[field] != actual_engine[field]:
                add("engine_checkout_mismatch")
        expected_bb2 = expected["bb2"]
        actual_bb2 = actual["bb2"]
        if expected_bb2["head"] != actual_bb2["head"]:
            add("bb2_head_changed")
        if expected["corpus"]["objects_tree_sha256"] != actual["corpus"]["objects_tree_sha256"]:
            add("objects_changed")
        if expected["corpus"]["mutation_fingerprint"] != actual["corpus"]["mutation_fingerprint"]:
            add("objects_changed")
        if expected["corpus"]["raw_tree_sha256"] != actual["corpus"]["raw_tree_sha256"]:
            add("raw_changed")
        if expected["search_index"] != actual["search_index"]:
            add("index_db_changed")
        if expected["runtime"] != actual["runtime"]:
            add("runtime_changed")
        if expected["stale_set"] != actual["stale_set"]:
            add("stale_set_changed")
        if expected["ignored_snapshots_inventory"] != actual["ignored_snapshots_inventory"]:
            add("ignored_snapshots_changed")
        if expected["artifact_inventory"] != actual["artifact_inventory"]:
            add("artifact_inventory_changed")
        for field in (
            "status_sha256",
            "status_porcelain_v1_z_base64",
            "dirt_content_manifest",
            "dirt_content_sha256",
        ):
            if expected_bb2[field] != actual_bb2[field]:
                add("user_dirt_changed")
    except (KeyError, TypeError):
        add("foundation_state_invalid")
    return errors


def _assert_state_transition(
    expected: Mapping[str, object],
    actual: Mapping[str, object],
    *,
    allow_stale_set: bool,
) -> None:
    errors = _state_drift_codes(expected, actual)
    if allow_stale_set:
        errors = [code for code in errors if code != "stale_set_changed"]
    if errors:
        _fail(errors[0], f"foundation state drift: {errors!r}")


def _normalized_install_report(
    report: Mapping[str, object],
    *,
    repo_root: Path,
) -> dict[str, object]:
    if report.get("ok") is not True:
        _fail("installer_report_invalid", "installer report must have ok=true")
    target, arrays, controls = _normalized_report_arrays(report)
    if target != repo_root:
        _fail("installer_target_mismatch", "installer target_root differs from BB2 root")
    config = report.get("config")
    if config not in {"created", "updated", "kept"}:
        _fail("installer_report_invalid", "installer config status is invalid")
    return {
        "ok": True,
        "target_root": str(target),
        "config": config,
        **arrays,
        "installer_control_paths": controls,
    }


def validate_foundation_install_reports(
    first: Mapping[str, object],
    second: Mapping[str, object],
    *,
    repo_root: Path,
) -> tuple[dict[str, object], dict[str, object], list[str]]:
    repo_root = _exact_absolute(repo_root, label="repo_root")
    first_value = _normalized_install_report(first, repo_root=repo_root)
    second_value = _normalized_install_report(second, repo_root=repo_root)
    if first_value["config"] != "kept":
        _fail("installer_config_changed", "first P0 install must keep exact existing config")
    if first_value["skipped"]:
        _fail("installer_skipped_paths", "first P0 install skipped managed paths")
    if first_value["adopted"]:
        _fail("installer_adopted_paths", "first P0 install adopted pre-existing paths")
    for report in (first_value, second_value):
        if report["installer_control_paths"] != [MANIFEST_FILENAME]:
            _fail(
                "installer_control_paths_invalid",
                "P0 installer_control_paths must be exactly the manifest",
            )
    for field in _INSTALL_CHANGE_FIELDS:
        if second_value[field]:
            _fail(
                "installer_not_idempotent",
                f"second install {field} must be empty: {second_value[field]!r}",
            )
    stage = task15_stage_paths(first_value)
    return first_value, second_value, [path for path in stage if path != MANIFEST_FILENAME]


def prepare_coverage_smoke(
    *,
    installed_runtime: Path,
    smoke_root: Path,
) -> None:
    installed_runtime = _exact_absolute(installed_runtime, label="installed_runtime")
    smoke_root = _exact_absolute(smoke_root, label="smoke_root")
    templates = installed_runtime.parent.parent / "references/object-templates"
    required = {
        "notes.json": templates / "build-notes.complete.template.json",
        "coverage.json": templates / "build-coverage.complete.template.json",
        "graph.json": templates / "object-graph.complete.template.json",
    }
    smoke_root.mkdir(parents=True, exist_ok=False)
    for destination, source in required.items():
        try:
            data = snapshot._read_regular(source.parent, source.name)
        except SnapshotError as exc:
            raise _from_snapshot(exc, code="coverage_smoke_fixture_invalid") from exc
        (smoke_root / destination).write_bytes(data)
    try:
        graph = json.loads((smoke_root / "graph.json").read_bytes())
        objects = graph["objects"]
    except (UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        _fail("coverage_smoke_fixture_invalid", f"invalid installed object graph: {exc}")
    brain_root = smoke_root / "brain"
    (brain_root / "objects").mkdir(parents=True)
    (brain_root / "raw").mkdir()
    for obj in objects:
        if not isinstance(obj, dict):
            _fail("coverage_smoke_fixture_invalid", "object graph entry must be an object")
        path = BrainStore.object_path(brain_root, obj)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(BrainStore.object_bytes(obj))


def _command_row(spec: FoundationCommandSpec) -> dict[str, object]:
    environment = os.environ.copy()
    environment.update(dict(spec.env))
    try:
        result = subprocess.run(
            spec.argv,
            cwd=spec.cwd,
            env=environment,
            capture_output=True,
            check=False,
        )
        stdout = result.stdout
        stderr = result.stderr
        exit_code = result.returncode
    except OSError as exc:
        stdout = b""
        stderr = str(exc).encode("utf-8", errors="replace")
        exit_code = 127
    return {
        "id": spec.id,
        "argv": list(spec.argv),
        "cwd": spec.cwd,
        "exit_code": exit_code,
        "stdout": stdout.decode("utf-8", errors="replace"),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stderr": stderr.decode("utf-8", errors="replace"),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "ok": exit_code == 0,
    }


def _invariant_or_fail(
    baseline: Mapping[str, object],
    *,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    artifact_root: Path,
    ignored_snapshots_root: Path,
    allowed_managed_paths: Collection[str],
    protected_artifact_files: Collection[Path],
    verified_snapshot_root: Path | None = None,
    all_artifact_files: Collection[Path] | None = None,
) -> dict[str, object]:
    report = verify_foundation_invariants(
        baseline,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        allowed_managed_paths=allowed_managed_paths,
        allowed_installer_control_paths=(MANIFEST_FILENAME,),
        artifact_root=artifact_root,
        ignored_snapshots_root=ignored_snapshots_root,
        allowed_artifact_files=(
            all_artifact_files
            if all_artifact_files is not None
            else protected_artifact_files
        ),
        verified_snapshot_root=verified_snapshot_root,
    )
    if not report["ok"]:
        errors = list(report["errors"])
        code = errors[0] if errors else "foundation_invariant_failed"
        if code == "unexpected_dirt_path":
            code = "artifact_inventory_changed"
        _fail(code, f"foundation invariant failed: {errors!r}")
    return report


def run_foundation_gate(
    *,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    artifact_root: Path,
    baseline_path: Path,
    baseline_binding_path: Path,
    install_report_1_path: Path,
    install_report_2_path: Path,
    installed_runtime: Path | None = None,
    python_executable: Path | None = None,
) -> dict[str, object]:
    engine_root = _exact_absolute(engine_root, label="engine_root")
    repo_root = _exact_absolute(repo_root, label="repo_root")
    brain_root = _exact_absolute(brain_root, label="brain_root")
    artifact_root = _exact_absolute(artifact_root, label="artifact_root")
    ignored_snapshots_root = _exact_absolute(
        repo_root / ".snapshots",
        label="ignored_snapshots_root",
    )
    baseline_path = _exact_absolute(baseline_path, label="baseline_path")
    baseline_binding_path = _exact_absolute(
        baseline_binding_path,
        label="baseline_binding_path",
    )
    install_report_1_path = _exact_absolute(
        install_report_1_path,
        label="install_report_1_path",
    )
    install_report_2_path = _exact_absolute(
        install_report_2_path,
        label="install_report_2_path",
    )
    installed_runtime = _exact_absolute(
        installed_runtime
        or repo_root / ".agents/skills/bb2-brain-ingest/scripts/validate_foundation.py",
        label="installed_runtime",
    )
    python_executable = _exact_absolute(
        python_executable or Path(os.sys.executable),
        label="python_executable",
    )
    validate_p0_project_config(repo_root)
    baseline, baseline_sha = _verify_named_bound_receipt(
        receipt_path=baseline_path,
        binding_path=baseline_binding_path,
        purpose="p0-foundation-baseline-binding",
        label="baseline",
    )
    first_raw, _ = _read_json_document(install_report_1_path, label="install_report_1")
    second_raw, _ = _read_json_document(install_report_2_path, label="install_report_2")
    first, second, allowed_managed = validate_foundation_install_reports(
        first_raw,
        second_raw,
        repo_root=repo_root,
    )
    protected_files = (
        baseline_path,
        baseline_binding_path,
        install_report_1_path,
        install_report_2_path,
    )
    verify_artifact_inventory(artifact_root, allowed_files=protected_files)
    initial_invariant = _invariant_or_fail(
        baseline,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        artifact_root=artifact_root,
        ignored_snapshots_root=ignored_snapshots_root,
        allowed_managed_paths=allowed_managed,
        protected_artifact_files=protected_files,
    )
    before = capture_foundation_state(
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        artifact_root=artifact_root,
        ignored_snapshots_root=ignored_snapshots_root,
        protected_artifact_files=protected_files,
    )
    command_rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="project-brain-foundation-smoke-") as temporary:
        smoke_root = (Path(temporary) / "smoke").resolve()
        prepare_coverage_smoke(
            installed_runtime=installed_runtime,
            smoke_root=smoke_root,
        )
        specs = foundation_command_specs(
            engine_root=engine_root,
            repo_root=repo_root,
            brain_root=brain_root,
            installed_runtime=installed_runtime,
            smoke_root=smoke_root,
            python_executable=python_executable,
        )
        previous = before
        for spec in specs:
            pre = capture_foundation_state(
                engine_root=engine_root,
                repo_root=repo_root,
                brain_root=brain_root,
                artifact_root=artifact_root,
                ignored_snapshots_root=ignored_snapshots_root,
                protected_artifact_files=protected_files,
            )
            _assert_state_transition(previous, pre, allow_stale_set=False)
            _invariant_or_fail(
                baseline,
                engine_root=engine_root,
                repo_root=repo_root,
                brain_root=brain_root,
                artifact_root=artifact_root,
                ignored_snapshots_root=ignored_snapshots_root,
                allowed_managed_paths=allowed_managed,
                protected_artifact_files=protected_files,
            )
            row = _command_row(spec)
            command_rows.append(row)
            post = capture_foundation_state(
                engine_root=engine_root,
                repo_root=repo_root,
                brain_root=brain_root,
                artifact_root=artifact_root,
                ignored_snapshots_root=ignored_snapshots_root,
                protected_artifact_files=protected_files,
            )
            _assert_state_transition(
                pre,
                post,
                allow_stale_set=spec.id == "audit-no-fetch",
            )
            _invariant_or_fail(
                baseline,
                engine_root=engine_root,
                repo_root=repo_root,
                brain_root=brain_root,
                artifact_root=artifact_root,
                ignored_snapshots_root=ignored_snapshots_root,
                allowed_managed_paths=allowed_managed,
                protected_artifact_files=protected_files,
            )
            previous = post
    after = capture_foundation_state(
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        artifact_root=artifact_root,
        ignored_snapshots_root=ignored_snapshots_root,
        protected_artifact_files=protected_files,
    )
    _assert_state_transition(previous, after, allow_stale_set=False)
    final_invariant = _invariant_or_fail(
        baseline,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        artifact_root=artifact_root,
        ignored_snapshots_root=ignored_snapshots_root,
        allowed_managed_paths=allowed_managed,
        protected_artifact_files=protected_files,
    )
    _assert_state_transition(
        before,
        after,
        allow_stale_set=True,
    )
    observed = final_invariant["observed_changes"]
    return {
        "version": 1,
        "purpose": "p0-foundation-gate",
        "baseline": {"path": str(baseline_path), "sha256": baseline_sha},
        "heads": {
            "engine": after["engine"]["head"],
            "bb2_before": baseline["bb2"]["head"],
            "bb2_after": after["bb2"]["head"],
        },
        "install": {"first": first, "second": second},
        "commands": command_rows,
        "before": before,
        "after": after,
        "allowed_changes": {
            "managed_runtime_paths": sorted(allowed_managed),
            "installer_control_paths": [MANIFEST_FILENAME],
            "expected_local_mutation_paths": [
                "brain/.brain-local/stale-set.json"
            ],
        },
        "observed_changes": {
            "bb2_commit_paths": observed["bb2_commit_paths"],
            "expected_local_mutation_paths": observed["expected_local_mutation"],
        },
        "ok": bool(initial_invariant["ok"] and final_invariant["ok"])
        and all(row["ok"] for row in command_rows),
    }


def _validate_gate_receipt(
    gate: Mapping[str, object],
    *,
    baseline: Mapping[str, object],
    baseline_path: Path,
    baseline_sha: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    installed_runtime: Path,
    python_executable: Path,
    install_first: Mapping[str, object],
    install_second: Mapping[str, object],
    allowed_managed: Sequence[str],
) -> None:
    expected_keys = {
        "version",
        "purpose",
        "baseline",
        "heads",
        "install",
        "commands",
        "before",
        "after",
        "allowed_changes",
        "observed_changes",
        "ok",
    }
    if (
        set(gate) != expected_keys
        or type(gate.get("version")) is not int
        or gate.get("version") != 1
        or gate.get("purpose") != "p0-foundation-gate"
        or gate.get("ok") is not True
    ):
        _fail("gate_invalid", "foundation gate exact shape, purpose, or ok is invalid")
    if gate.get("baseline") != {"path": str(baseline_path), "sha256": baseline_sha}:
        _fail("gate_baseline_mismatch", "gate does not bind the immutable baseline")
    commands = gate.get("commands")
    command_keys = {
        "id",
        "argv",
        "cwd",
        "exit_code",
        "stdout",
        "stdout_sha256",
        "stderr",
        "stderr_sha256",
        "ok",
    }
    if (
        not isinstance(commands, list)
        or len(commands) != 6
        or any(not isinstance(row, dict) or set(row) != command_keys for row in commands)
    ):
        _fail("gate_commands_invalid", "gate command rows are not the exact successful fixed set")
    coverage_argv = commands[-1].get("argv")
    if not isinstance(coverage_argv, list) or not all(
        isinstance(value, str) for value in coverage_argv
    ):
        _fail("gate_commands_invalid", "coverage command argv must be a string array")
    try:
        notes_index = coverage_argv.index("--notes")
        if coverage_argv.count("--notes") != 1:
            raise ValueError("duplicate --notes")
        smoke_root = Path(coverage_argv[notes_index + 1]).parent
    except (ValueError, IndexError) as exc:
        _fail("gate_commands_invalid", f"cannot derive coverage smoke root: {exc}")
    expected_temp_root = Path(tempfile.gettempdir()).resolve()
    if (
        not smoke_root.is_absolute()
        or smoke_root != Path(os.path.abspath(smoke_root))
        or smoke_root.name != "smoke"
        or not smoke_root.parent.name.startswith("project-brain-foundation-smoke-")
        or smoke_root.parent.parent != expected_temp_root
    ):
        _fail("gate_commands_invalid", f"unsafe coverage smoke root: {smoke_root}")
    expected_specs = foundation_command_specs(
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        installed_runtime=installed_runtime,
        smoke_root=smoke_root,
        python_executable=python_executable,
    )
    for row, spec in zip(commands, expected_specs, strict=True):
        if (
            row.get("id") != spec.id
            or row.get("argv") != list(spec.argv)
            or row.get("cwd") != spec.cwd
            or type(row.get("exit_code")) is not int
            or row.get("exit_code") != 0
            or row.get("ok") is not True
        ):
            _fail("gate_commands_invalid", f"gate command differs from fixed spec: {spec.id}")
        for stream in ("stdout", "stderr"):
            value = row.get(stream)
            digest = row.get(f"{stream}_sha256")
            if (
                not isinstance(value, str)
                or not isinstance(digest, str)
                or digest != hashlib.sha256(value.encode("utf-8")).hexdigest()
            ):
                _fail(
                    "gate_commands_invalid",
                    f"gate command {spec.id} {stream} SHA mismatch",
                )
    rendered = "\n".join(" ".join(row["argv"]) for row in commands)
    if "finalize_ingest" in rendered or "index rebuild" in rendered:
        _fail("gate_commands_invalid", "gate includes a forbidden mutating command")
    expected_install = {
        "first": dict(install_first),
        "second": dict(install_second),
    }
    if gate.get("install") != expected_install:
        _fail("gate_install_invalid", "embedded install reports differ from artifact reports")
    allowed = gate.get("allowed_changes")
    expected_allowed = {
        "managed_runtime_paths": sorted(allowed_managed),
        "installer_control_paths": [MANIFEST_FILENAME],
        "expected_local_mutation_paths": ["brain/.brain-local/stale-set.json"],
    }
    if allowed != expected_allowed:
        _fail("gate_allowed_changes_invalid", "gate allowed_changes contract is invalid")
    before = gate.get("before")
    after = gate.get("after")
    state_keys = {
        "roots",
        "engine",
        "bb2",
        "corpus",
        "search_index",
        "runtime",
        "stale_set",
        "ignored_snapshots_inventory",
        "artifact_inventory",
    }
    if (
        not isinstance(before, dict)
        or not isinstance(after, dict)
        or set(before) != state_keys
        or set(after) != state_keys
    ):
        _fail("gate_state_invalid", "gate before/after exact state shape is invalid")
    drift = [
        code for code in _state_drift_codes(before, after)
        if code != "stale_set_changed"
    ]
    try:
        state_contract_ok = (
            before["roots"] == after["roots"] == baseline["roots"]
            and before["engine"] == after["engine"] == baseline["engine"]
            and before["bb2"] == after["bb2"]
            and before["corpus"] == after["corpus"] == baseline["corpus"]
            and before["search_index"] == after["search_index"] == baseline["search_index"]
            and before["runtime"] == after["runtime"]
            and before["stale_set"] == baseline["stale_set"]
            and before["ignored_snapshots_inventory"]
            == after["ignored_snapshots_inventory"]
            == baseline["ignored_snapshots_inventory"]
            and before["artifact_inventory"] == after["artifact_inventory"]
        )
    except (KeyError, TypeError):
        state_contract_ok = False
    if drift or not state_contract_ok:
        _fail("gate_state_invalid", f"gate state contract differs: {drift!r}")
    heads = gate.get("heads")
    expected_heads = {
        "engine": after["engine"]["head"],
        "bb2_before": baseline["bb2"]["head"],
        "bb2_after": after["bb2"]["head"],
    }
    if heads != expected_heads:
        _fail("gate_heads_invalid", "gate heads do not match baseline/after states")
    expected_observed = {
        "bb2_commit_paths": sorted(set(allowed_managed) | {MANIFEST_FILENAME}),
        "expected_local_mutation_paths": (
            ["brain/.brain-local/stale-set.json"]
            if after["stale_set"] != baseline["stale_set"]
            else []
        ),
    }
    if gate.get("observed_changes") != expected_observed:
        _fail("gate_observed_changes_invalid", "gate observed_changes contract is invalid")


def _snapshot_handoff_evidence(
    *,
    snapshot_root: Path,
    create_receipt_path: Path,
    verify_receipt_path: Path,
) -> tuple[dict[str, object], TreeReceipt]:
    snapshot_root = _exact_absolute(snapshot_root, label="snapshot_root")
    create_receipt_path = _exact_absolute(
        create_receipt_path,
        label="snapshot_create_receipt",
    )
    verify_receipt_path = _exact_absolute(
        verify_receipt_path,
        label="snapshot_verify_receipt",
    )
    create_value, create_data = _read_json_document(
        create_receipt_path,
        label="snapshot_create_receipt",
    )
    verify_value, verify_data = _read_json_document(
        verify_receipt_path,
        label="snapshot_verify_receipt",
    )
    if set(create_value) != {
        "ok",
        "snapshot_id",
        "snapshot_root",
        "manifest_path",
        "manifest_sha256",
        "file_count",
        "restore_scope",
    } or create_value.get("ok") is not True or create_value.get("restore_scope") != "brain_only":
        _fail("snapshot_create_receipt_invalid", "snapshot create receipt exact shape is invalid")
    if set(verify_value) != {
        "ok",
        "snapshot_id",
        "manifest_sha256",
        "file_count",
    } or verify_value.get("ok") is not True:
        _fail("snapshot_verify_receipt_invalid", "snapshot verify receipt exact shape is invalid")
    manifest_path = snapshot_root / "manifest.json"
    if create_value.get("snapshot_root") != str(snapshot_root):
        _fail("snapshot_root_mismatch", "snapshot create receipt root differs from handoff root")
    if create_value.get("manifest_path") != str(manifest_path):
        _fail("snapshot_manifest_path_mismatch", "snapshot manifest path is not root/manifest.json")
    expected_sha = create_value.get("manifest_sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64 or any(ch not in _SHA256 for ch in expected_sha):
        _fail("snapshot_manifest_sha_invalid", "snapshot manifest SHA is invalid")
    try:
        manifest_data = snapshot._read_regular(snapshot_root, "manifest.json")
    except SnapshotError as exc:
        raise _from_snapshot(exc, code="snapshot_manifest_invalid") from exc
    actual_sha = hashlib.sha256(manifest_data).hexdigest()
    if actual_sha != expected_sha:
        _fail("snapshot_manifest_sha_mismatch", "actual snapshot manifest SHA differs from create receipt")
    before_verify = _scan_tree_receipt(snapshot_root)
    try:
        verification = snapshot.verify_snapshot(
            snapshot_root,
            expected_manifest_sha256=expected_sha,
        )
    except SnapshotError as exc:
        raise _from_snapshot(exc, code="snapshot_verify_failed") from exc
    after_verify = _scan_tree_receipt(snapshot_root)
    if after_verify != before_verify:
        _fail("snapshot_changed", "snapshot changed during independent verification")
    actual = {
        "ok": verification.ok,
        "snapshot_id": verification.snapshot_id,
        "manifest_sha256": verification.manifest_sha256,
        "file_count": verification.file_count,
    }
    if (
        actual["ok"] is not True
        or create_value.get("snapshot_id") != actual["snapshot_id"]
        or create_value.get("manifest_sha256") != actual["manifest_sha256"]
        or create_value.get("file_count") != actual["file_count"]
        or verify_value != actual
    ):
        _fail(
            "snapshot_verify_result_mismatch",
            "snapshot create/verify receipts differ from independent verification",
        )
    return (
        {
            "ok": actual["ok"],
            "root": str(snapshot_root),
            "manifest_path": str(manifest_path),
            "manifest_sha256": actual["manifest_sha256"],
            "snapshot_id": actual["snapshot_id"],
            "file_count": actual["file_count"],
            "create_receipt": {
                "path": str(create_receipt_path),
                "sha256": hashlib.sha256(create_data).hexdigest(),
            },
            "verify_receipt": {
                "path": str(verify_receipt_path),
                "sha256": hashlib.sha256(verify_data).hexdigest(),
            },
        },
        after_verify,
    )


def _before_handoff_publish_hook() -> None:
    """Deterministic test seam immediately before the final state recheck."""


def _after_handoff_write_hook() -> None:
    """Deterministic test seam after handoff create and before final inventory."""


def _snapshot_regular_paths(
    artifact_root: Path,
    tree: TreeReceipt,
) -> list[Path]:
    snapshot_root = Path(tree.root)
    return [
        artifact_root / snapshot_root.relative_to(artifact_root) / entry.path
        for entry in tree.entries
        if entry.entry_type == "regular"
    ]


def _assert_snapshot_entries_in_artifact_receipt(
    *,
    artifact_root: Path,
    snapshot_root: Path,
    artifact_receipt: TreeReceipt,
    expected_snapshot: TreeReceipt,
) -> None:
    prefix = snapshot_root.relative_to(artifact_root).as_posix()
    observed: list[TreeEntryReceipt] = []
    for entry in artifact_receipt.entries:
        marker = prefix + "/"
        if not entry.path.startswith(marker):
            continue
        observed.append(TreeEntryReceipt(
            path=entry.path.removeprefix(marker),
            entry_type=entry.entry_type,
            mode=entry.mode,
            size=entry.size,
            sha256=entry.sha256,
        ))
    if tuple(observed) != expected_snapshot.entries:
        _fail(
            "snapshot_changed",
            "snapshot metadata differs inside the final artifact inventory receipt",
            paths=(snapshot_root,),
        )


def _tree_receipt_from_entry_receipts(
    root: Path,
    entries: Collection[TreeEntryReceipt],
) -> TreeReceipt:
    ordered = tuple(sorted(entries, key=lambda entry: entry.path))
    payload = {"entries": [asdict(entry) for entry in ordered]}
    return TreeReceipt(
        root=str(root),
        entries=ordered,
        sha256=hashlib.sha256(canonical_receipt_bytes(payload)).hexdigest(),
    )


def _capture_handoff_state(**kwargs: object) -> dict[str, object]:
    """Capture-time validation failures도 handoff의 공개 drift 코드로 정규화한다."""
    try:
        return capture_foundation_state(**kwargs)
    except FoundationError as exc:
        mapped = {
            "engine_core_dirty": "engine_core_changed",
            "engine_core_invalid": "engine_core_changed",
            "runtime_manifest_invalid": "runtime_changed",
            "runtime_manifest_mismatch": "runtime_changed",
            "corpus_changed_during_capture": "objects_changed",
            "index_changed_during_capture": "index_db_changed",
        }.get(exc.code)
        if mapped is None:
            raise
        _fail(
            mapped,
            f"handoff state capture failed: {exc.detail}",
            paths=exc.paths,
            cause_code=exc.code,
        )


def build_foundation_handoff(
    *,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    artifact_root: Path,
    baseline_path: Path,
    baseline_binding_path: Path,
    gate_path: Path,
    gate_binding_path: Path,
    snapshot_root: Path,
    snapshot_create_receipt_path: Path,
    snapshot_verify_receipt_path: Path,
    output_path: Path,
) -> dict[str, object]:
    engine_root = _exact_absolute(engine_root, label="engine_root")
    repo_root = _exact_absolute(repo_root, label="repo_root")
    brain_root = _exact_absolute(brain_root, label="brain_root")
    artifact_root = _exact_absolute(artifact_root, label="artifact_root")
    ignored_snapshots_root = _exact_absolute(
        repo_root / ".snapshots",
        label="ignored_snapshots_root",
    )
    baseline_path = _exact_absolute(baseline_path, label="baseline_path")
    baseline_binding_path = _exact_absolute(
        baseline_binding_path,
        label="baseline_binding_path",
    )
    gate_path = _exact_absolute(gate_path, label="gate_path")
    gate_binding_path = _exact_absolute(gate_binding_path, label="gate_binding_path")
    snapshot_root = _exact_absolute(snapshot_root, label="snapshot_root")
    snapshot_create_receipt_path = _exact_absolute(
        snapshot_create_receipt_path,
        label="snapshot_create_receipt_path",
    )
    snapshot_verify_receipt_path = _exact_absolute(
        snapshot_verify_receipt_path,
        label="snapshot_verify_receipt_path",
    )
    output_path = _exact_absolute(output_path, label="output_path")
    if output_path.parent != artifact_root:
        _fail("handoff_path_invalid", "handoff output must be a direct artifact-root child")

    baseline, baseline_sha = _verify_named_bound_receipt(
        receipt_path=baseline_path,
        binding_path=baseline_binding_path,
        purpose="p0-foundation-baseline-binding",
        label="baseline",
    )
    gate, gate_sha = _verify_named_bound_receipt(
        receipt_path=gate_path,
        binding_path=gate_binding_path,
        purpose="p0-foundation-gate-binding",
        label="gate",
    )
    install_report_1_path = artifact_root / "install-1.json"
    install_report_2_path = artifact_root / "install-2.json"
    first_raw, _ = _read_json_document(
        install_report_1_path,
        label="install_report_1",
    )
    second_raw, _ = _read_json_document(
        install_report_2_path,
        label="install_report_2",
    )
    install_first, install_second, allowed_managed = validate_foundation_install_reports(
        first_raw,
        second_raw,
        repo_root=repo_root,
    )
    installed_runtime = _exact_absolute(
        repo_root / ".agents/skills/bb2-brain-ingest/scripts/validate_foundation.py",
        label="installed_runtime",
    )
    _validate_gate_receipt(
        gate,
        baseline=baseline,
        baseline_path=baseline_path,
        baseline_sha=baseline_sha,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        installed_runtime=installed_runtime,
        python_executable=_exact_absolute(
            Path(os.sys.executable),
            label="python_executable",
        ),
        install_first=install_first,
        install_second=install_second,
        allowed_managed=allowed_managed,
    )
    protected_files = (
        baseline_path,
        baseline_binding_path,
        install_report_1_path,
        install_report_2_path,
    )
    snapshot_evidence, initial_snapshot_tree = _snapshot_handoff_evidence(
        snapshot_root=snapshot_root,
        create_receipt_path=snapshot_create_receipt_path,
        verify_receipt_path=snapshot_verify_receipt_path,
    )
    full_artifact_files = (
        *protected_files,
        gate_path,
        gate_binding_path,
        snapshot_create_receipt_path,
        snapshot_verify_receipt_path,
    )
    snapshot_regular = _snapshot_regular_paths(artifact_root, initial_snapshot_tree)
    initial_full_inventory = verify_artifact_inventory(
        artifact_root,
        allowed_files=(*full_artifact_files, *snapshot_regular),
    )
    _assert_snapshot_entries_in_artifact_receipt(
        artifact_root=artifact_root,
        snapshot_root=snapshot_root,
        artifact_receipt=initial_full_inventory,
        expected_snapshot=initial_snapshot_tree,
    )
    first = _capture_handoff_state(
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        artifact_root=artifact_root,
        ignored_snapshots_root=ignored_snapshots_root,
        protected_artifact_files=protected_files,
    )
    _assert_state_transition(gate["after"], first, allow_stale_set=False)
    _invariant_or_fail(
        baseline,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        artifact_root=artifact_root,
        ignored_snapshots_root=ignored_snapshots_root,
        allowed_managed_paths=allowed_managed,
        protected_artifact_files=protected_files,
        verified_snapshot_root=None,
        all_artifact_files=(*full_artifact_files, *snapshot_regular),
    )

    _before_handoff_publish_hook()
    second_snapshot_tree = _scan_tree_receipt(snapshot_root)
    if second_snapshot_tree != initial_snapshot_tree:
        _fail("snapshot_changed", "snapshot tree changed before handoff publish")
    second_inventory = verify_artifact_inventory(
        artifact_root,
        allowed_files=(*full_artifact_files, *snapshot_regular),
    )
    _assert_snapshot_entries_in_artifact_receipt(
        artifact_root=artifact_root,
        snapshot_root=snapshot_root,
        artifact_receipt=second_inventory,
        expected_snapshot=initial_snapshot_tree,
    )
    if second_inventory != initial_full_inventory:
        _fail(
            "artifact_inventory_changed",
            "full artifact inventory changed before handoff publish",
        )
    second = _capture_handoff_state(
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        artifact_root=artifact_root,
        ignored_snapshots_root=ignored_snapshots_root,
        protected_artifact_files=protected_files,
    )
    _assert_state_transition(gate["after"], second, allow_stale_set=False)
    _assert_state_transition(first, second, allow_stale_set=False)
    receipt = {
        "version": 1,
        "purpose": "p0-foundation-handoff",
        "baseline": {"path": str(baseline_path), "sha256": baseline_sha},
        "gate": {"path": str(gate_path), "sha256": gate_sha},
        "snapshot": snapshot_evidence,
        "final_recheck": {"first": first, "second": second},
        "task18_status": "blocked_pending_new_measurement_design_binding",
        "ok": True,
    }
    data = canonical_receipt_bytes(receipt)
    parent_fd, name = _validate_output_path(output_path, label="handoff")
    created: os.stat_result | None = None
    try:
        _preflight_absent(parent_fd, name, label="handoff")
        created = _create_at(parent_fd, name, data, label="handoff")
        output_relative = output_path.relative_to(artifact_root).as_posix()
        expected_post_inventory = _tree_receipt_from_entry_receipts(
            artifact_root,
            (
                *initial_full_inventory.entries,
                TreeEntryReceipt(
                    path=output_relative,
                    entry_type="regular",
                    mode=stat.S_IMODE(created.st_mode),
                    size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                ),
            ),
        )
        try:
            _after_handoff_write_hook()
            post_snapshot_tree = _scan_tree_receipt(snapshot_root)
            if post_snapshot_tree != initial_snapshot_tree:
                _fail("snapshot_changed", "snapshot tree changed after handoff write")
            post_inventory = verify_artifact_inventory(
                artifact_root,
                allowed_files=(
                    *full_artifact_files,
                    *snapshot_regular,
                    output_path,
                ),
            )
            _assert_snapshot_entries_in_artifact_receipt(
                artifact_root=artifact_root,
                snapshot_root=snapshot_root,
                artifact_receipt=post_inventory,
                expected_snapshot=initial_snapshot_tree,
            )
            if post_inventory != expected_post_inventory:
                _fail(
                    "artifact_inventory_changed",
                    "post-write artifact inventory is not initial receipt plus owned output",
                )
            try:
                linked = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except OSError as exc:
                _fail("handoff_output_changed", f"cannot re-stat handoff output: {exc}")
            if linked.st_dev != created.st_dev or linked.st_ino != created.st_ino:
                _fail("handoff_output_changed", "handoff output name no longer binds the owned inode")
            output_entry = next(
                (entry for entry in post_inventory.entries if entry.path == output_relative),
                None,
            )
            if (
                output_entry is None
                or output_entry.entry_type != "regular"
                or output_entry.sha256 != hashlib.sha256(data).hexdigest()
                or output_entry.size != len(data)
                or output_entry.mode != stat.S_IMODE(created.st_mode)
            ):
                _fail(
                    "handoff_output_changed",
                    "handoff output metadata or canonical bytes changed after publish",
                )
        except (FoundationError, OSError) as exc:
            removed = _unlink_if_owned(parent_fd, name, created)
            try:
                os.fsync(parent_fd)
            except OSError:
                removed = False
            detail = f"handoff post-write artifact inventory failed: {getattr(exc, 'detail', exc)}"
            if not removed:
                detail += "; owned handoff could not be safely removed"
            raise FoundationError(
                "artifact_inventory_changed",
                detail,
                paths=(output_path,),
                cause_code=getattr(exc, "code", type(exc).__name__),
            ) from exc
    finally:
        os.close(parent_fd)
    return receipt
