"""검증 가능한 full snapshot 생성·검증·안전한 directory-swap 복원."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from project_brain.installer import MANIFEST_FILENAME
from project_brain.objbase import now_kst
from project_brain.store import BrainStore


_SNAPSHOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_BRAIN_DIRECTORIES = tuple(sorted({
    *BrainStore._KIND_DIR.values(),
    "raw/sources",
}))
_BRAIN_FILES = (
    ".brain-local/index.db",
    ".brain-local/index.db-wal",
    ".brain-local/index.db-shm",
    ".brain-local/stale-set.json",
    "eval_scenarios.json",
)


class SnapshotError(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class SnapshotRequest:
    brain_root: Path
    repo_root: Path
    engine_root: Path
    output_root: Path
    snapshot_id: str


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_id: str
    snapshot_root: Path
    manifest_path: Path
    manifest_sha256: str
    file_count: int


@dataclass(frozen=True)
class SnapshotVerification:
    ok: bool
    snapshot_id: str
    manifest_sha256: str
    file_count: int


@dataclass(frozen=True)
class RestoreResult:
    snapshot_id: str
    brain_root: Path
    restored_files: tuple[str, ...]


def _fail(code: str, detail: str) -> None:
    raise SnapshotError(code, detail)


def _safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value:
        _fail("snapshot_manifest_invalid", "file path must be non-empty")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        _fail("snapshot_manifest_invalid", f"unsafe relative path: {value!r}")
    return path.as_posix()


def _hash_file(path: Path) -> tuple[str, int]:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        _fail("source_unavailable", f"cannot inspect {path}: {exc}")
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        _fail("source_type_invalid", f"source is not a regular file: {path}")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        _fail("source_unavailable", f"cannot open {path}: {exc}")
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            _fail("source_type_invalid", f"source is not regular: {path}")
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        if (
            opened.st_dev,
            opened.st_ino,
            opened.st_size,
            opened.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            _fail("source_fingerprint_changed", f"source changed while hashing: {path}")
        return digest.hexdigest(), size
    finally:
        os.close(descriptor)


def _walk_regular_files(root: Path, relative_directory: str) -> list[str]:
    directory = root / relative_directory
    try:
        mode = directory.lstat().st_mode
    except FileNotFoundError:
        return []
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        _fail("source_type_invalid", f"source directory is unsafe: {directory}")
    results: list[str] = []
    for current, directory_names, file_names in os.walk(directory, followlinks=False):
        current_path = Path(current)
        for name in sorted(directory_names):
            child = current_path / name
            child_mode = child.lstat().st_mode
            if stat.S_ISLNK(child_mode) or not stat.S_ISDIR(child_mode):
                _fail("source_type_invalid", f"source tree is unsafe: {child}")
        for name in sorted(file_names):
            child = current_path / name
            relative = child.relative_to(root).as_posix()
            _hash_file(child)
            results.append(relative)
    return sorted(results)


def _git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _managed_inventory(repo_root: Path) -> tuple[list[dict], list[str]]:
    manifest_path = repo_root / MANIFEST_FILENAME
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], []
    except (OSError, json.JSONDecodeError) as exc:
        _fail("install_manifest_invalid", f"cannot read {manifest_path}: {exc}")
    files = raw.get("files")
    if not isinstance(files, dict):
        _fail("install_manifest_invalid", "install manifest files must be an object")
    inventory: list[dict] = []
    paths: list[str] = []
    for raw_path, recorded_sha in sorted(files.items()):
        relative = _safe_relative(raw_path)
        if not isinstance(recorded_sha, str) or _SHA256.fullmatch(recorded_sha) is None:
            _fail(
                "install_manifest_invalid",
                f"managed file hash is invalid: {relative}",
            )
        path = repo_root / relative
        try:
            actual_sha, _ = _hash_file(path)
        except SnapshotError as exc:
            if exc.code != "source_unavailable":
                raise
            actual_sha = None
        inventory.append({
            "path": relative,
            "recorded_sha256": recorded_sha,
            "actual_sha256": actual_sha,
            "matches_recorded": actual_sha == recorded_sha,
        })
        if actual_sha is not None:
            paths.append(relative)
    return inventory, paths


def _inventory(request: SnapshotRequest) -> tuple[list[dict], list[dict]]:
    files: list[dict] = []
    brain_paths = {
        path
        for directory in _BRAIN_DIRECTORIES
        for path in _walk_regular_files(request.brain_root, directory)
    }
    for relative in _BRAIN_FILES:
        path = request.brain_root / relative
        if path.exists():
            brain_paths.add(relative)
    for relative in sorted(brain_paths):
        digest, size = _hash_file(request.brain_root / relative)
        files.append({
            "scope": "brain",
            "path": relative,
            "sha256": digest,
            "size": size,
            "copied": True,
            "snapshot_path": f"payload/brain/{relative}",
        })

    managed, managed_paths = _managed_inventory(request.repo_root)
    repo_paths = [
        relative
        for relative in (
            ".project-brain.json",
            MANIFEST_FILENAME,
            *managed_paths,
        )
        if (request.repo_root / relative).exists()
    ]
    for relative in sorted(set(repo_paths)):
        digest, size = _hash_file(request.repo_root / relative)
        files.append({
            "scope": "repo",
            "path": relative,
            "sha256": digest,
            "size": size,
            "copied": True,
            "snapshot_path": f"payload/repo/{relative}",
        })
    return files, managed


def _inventory_fingerprint(
    files: list[dict],
    managed_files: list[dict],
    *,
    repo_head: str | None,
    engine_head: str | None,
) -> str:
    payload = {
        "files": files,
        "managed_files": managed_files,
        "repo_head": repo_head,
        "engine_head": engine_head,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination, follow_symlinks=False)


def _manifest_bytes(manifest: dict) -> bytes:
    return (
        json.dumps(
            manifest,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _validate_request(request: SnapshotRequest) -> None:
    if not isinstance(request, SnapshotRequest):
        _fail("request_invalid", "request must be SnapshotRequest")
    for name in ("brain_root", "repo_root", "engine_root", "output_root"):
        path = getattr(request, name)
        if not isinstance(path, Path) or not path.is_absolute():
            _fail("request_invalid", f"{name} must be an absolute Path")
    if _SNAPSHOT_ID.fullmatch(request.snapshot_id) is None:
        _fail("snapshot_id_invalid", "snapshot_id contains unsafe characters")
    try:
        request.output_root.relative_to(request.brain_root)
    except ValueError:
        pass
    else:
        _fail("output_inside_brain", "snapshot output_root cannot be inside brain_root")


def create_snapshot(request: SnapshotRequest) -> SnapshotResult:
    from project_brain.corpus_io import (
        CorpusIOError,
        assert_corpus_readable,
        corpus_lock,
    )

    _validate_request(request)
    try:
        with corpus_lock(request.brain_root, exclusive=False):
            assert_corpus_readable(request.brain_root)
            return _create_snapshot_locked(request)
    except CorpusIOError as exc:
        _fail("snapshot_lock_failed", str(exc))


def _create_snapshot_locked(request: SnapshotRequest) -> SnapshotResult:
    _validate_request(request)
    final_root = request.output_root / request.snapshot_id
    if final_root.exists():
        _fail("snapshot_exists", f"snapshot already exists: {final_root}")
    request.output_root.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(
        dir=request.output_root,
        prefix=f".{request.snapshot_id}.building-",
    ))
    try:
        repo_head_before = _git_head(request.repo_root)
        engine_head_before = _git_head(request.engine_root)
        files_before, managed_before = _inventory(request)
        fingerprint_before = _inventory_fingerprint(
            files_before,
            managed_before,
            repo_head=repo_head_before,
            engine_head=engine_head_before,
        )
        roots = {
            "brain": request.brain_root,
            "repo": request.repo_root,
        }
        for entry in files_before:
            _copy_file(
                roots[entry["scope"]] / entry["path"],
                temporary_root / entry["snapshot_path"],
            )
            copied_sha, copied_size = _hash_file(
                temporary_root / entry["snapshot_path"]
            )
            if (
                copied_sha != entry["sha256"]
                or copied_size != entry["size"]
            ):
                _fail(
                    "source_fingerprint_changed",
                    f"source changed while copying: {entry['scope']}:{entry['path']}",
                )

        files_after, managed_after = _inventory(request)
        repo_head_after = _git_head(request.repo_root)
        engine_head_after = _git_head(request.engine_root)
        fingerprint_after = _inventory_fingerprint(
            files_after,
            managed_after,
            repo_head=repo_head_after,
            engine_head=engine_head_after,
        )
        if fingerprint_after != fingerprint_before:
            _fail(
                "source_fingerprint_changed",
                "snapshot inputs changed between initial and final inventory",
            )
        manifest = {
            "version": 1,
            "snapshot_id": request.snapshot_id,
            "created_at": now_kst(),
            "source_fingerprint": fingerprint_before,
            "roots": {
                "brain_root": str(request.brain_root),
                "repo_root": str(request.repo_root),
                "engine_root": str(request.engine_root),
            },
            "repo_head": repo_head_before,
            "engine_head": engine_head_before,
            "brain_targets": {
                "object_kinds": dict(sorted(BrainStore._KIND_DIR.items())),
                "directories": list(_BRAIN_DIRECTORIES),
                "files": list(_BRAIN_FILES),
            },
            "files": files_before,
            "raw_sources": [
                {
                    "path": entry["path"],
                    "sha256": entry["sha256"],
                    "size": entry["size"],
                }
                for entry in files_before
                if (
                    entry["scope"] == "brain"
                    and entry["path"].startswith("raw/sources/")
                )
            ],
            "managed_files": managed_before,
        }
        manifest_bytes = _manifest_bytes(manifest)
        manifest_path = temporary_root / "manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        os.rename(temporary_root, final_root)
        return SnapshotResult(
            snapshot_id=request.snapshot_id,
            snapshot_root=final_root,
            manifest_path=final_root / "manifest.json",
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            file_count=len(files_before),
        )
    except SnapshotError:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(temporary_root, ignore_errors=True)
        _fail("snapshot_create_failed", str(exc))


def _load_manifest(snapshot_root: Path) -> tuple[dict, bytes]:
    try:
        manifest_bytes = (snapshot_root / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        _fail("snapshot_manifest_invalid", str(exc))
    required = {
        "version",
        "snapshot_id",
        "created_at",
        "source_fingerprint",
        "roots",
        "repo_head",
        "engine_head",
        "brain_targets",
        "files",
        "raw_sources",
        "managed_files",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        _fail("snapshot_manifest_invalid", "manifest keys do not match contract")
    if manifest["version"] != 1 or _SNAPSHOT_ID.fullmatch(
        manifest.get("snapshot_id", "")
    ) is None:
        _fail("snapshot_manifest_invalid", "snapshot version or ID is invalid")
    targets = manifest["brain_targets"]
    if (
        not isinstance(targets, dict)
        or set(targets) != {"object_kinds", "directories", "files"}
        or targets["object_kinds"]
        != dict(sorted(BrainStore._KIND_DIR.items()))
        or targets["directories"] != list(_BRAIN_DIRECTORIES)
        or targets["files"] != list(_BRAIN_FILES)
    ):
        _fail("snapshot_manifest_invalid", "brain target coverage is invalid")
    if not isinstance(manifest["files"], list):
        _fail("snapshot_manifest_invalid", "manifest files must be a list")
    return manifest, manifest_bytes


def verify_snapshot(snapshot_root: Path) -> SnapshotVerification:
    snapshot_root = Path(snapshot_root)
    manifest, manifest_bytes = _load_manifest(snapshot_root)
    expected_payload_paths: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != {
            "scope", "path", "sha256", "size", "copied", "snapshot_path",
        }:
            _fail("snapshot_manifest_invalid", "file entry keys are invalid")
        if entry["scope"] not in {"brain", "repo"}:
            _fail("snapshot_manifest_invalid", "file scope is invalid")
        relative = _safe_relative(entry["path"])
        snapshot_path = _safe_relative(entry["snapshot_path"])
        if snapshot_path != f"payload/{entry['scope']}/{relative}":
            _fail(
                "snapshot_manifest_invalid",
                f"snapshot payload path does not match its source: {snapshot_path}",
            )
        if (
            not isinstance(entry["sha256"], str)
            or _SHA256.fullmatch(entry["sha256"]) is None
            or not isinstance(entry["size"], int)
            or entry["size"] < 0
            or entry["copied"] is not True
        ):
            _fail("snapshot_manifest_invalid", "file hash/size/copy flag is invalid")
        key = (entry["scope"], relative)
        if key in seen_keys or snapshot_path in expected_payload_paths:
            _fail("snapshot_manifest_invalid", "duplicate file entry")
        seen_keys.add(key)
        expected_payload_paths.add(snapshot_path)
        try:
            actual_sha, actual_size = _hash_file(snapshot_root / snapshot_path)
        except SnapshotError as exc:
            _fail(
                "snapshot_payload_hash_mismatch",
                f"snapshot payload is unavailable: {snapshot_path}: {exc.detail}",
            )
        if actual_sha != entry["sha256"] or actual_size != entry["size"]:
            _fail(
                "snapshot_payload_hash_mismatch",
                f"snapshot payload changed: {snapshot_path}",
            )
    actual_payload_paths = {
        path.relative_to(snapshot_root).as_posix()
        for path in (snapshot_root / "payload").rglob("*")
        if path.is_file()
    } if (snapshot_root / "payload").exists() else set()
    if actual_payload_paths != expected_payload_paths:
        _fail(
            "snapshot_payload_inventory_mismatch",
            "snapshot payload inventory differs from manifest",
        )
    expected_raw_sources = [
        {
            "path": entry["path"],
            "sha256": entry["sha256"],
            "size": entry["size"],
        }
        for entry in manifest["files"]
        if (
            entry["scope"] == "brain"
            and entry["path"].startswith("raw/sources/")
        )
    ]
    if manifest["raw_sources"] != expected_raw_sources:
        _fail(
            "snapshot_manifest_invalid",
            "raw source inventory differs from captured files",
        )
    return SnapshotVerification(
        ok=True,
        snapshot_id=manifest["snapshot_id"],
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        file_count=len(manifest["files"]),
    )


def _copy_tree_no_symlinks(source: Path, destination: Path) -> None:
    destination.mkdir()
    for current, directory_names, file_names in os.walk(source, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(source)
        target_directory = destination / relative
        for name in sorted(directory_names):
            child = current_path / name
            mode = child.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                _fail("restore_live_tree_unsafe", f"unsafe live directory: {child}")
            (target_directory / name).mkdir()
        for name in sorted(file_names):
            child = current_path / name
            _hash_file(child)
            _copy_file(child, target_directory / name)


def _remove_stage_target(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _rename_path(source: Path, destination: Path) -> None:
    os.rename(source, destination)


def restore_snapshot(snapshot_root: Path, brain_root: Path) -> RestoreResult:
    from project_brain.corpus_io import (
        CorpusIOError,
        corpus_lock,
        recover_unfinished_transaction_unlocked,
    )

    brain_root = Path(brain_root)
    try:
        with corpus_lock(brain_root, exclusive=True):
            recover_unfinished_transaction_unlocked(brain_root)
            return _restore_snapshot_locked(snapshot_root, brain_root)
    except CorpusIOError as exc:
        _fail("restore_lock_failed", str(exc))


def _restore_snapshot_locked(
    snapshot_root: Path,
    brain_root: Path,
) -> RestoreResult:
    snapshot_root = Path(snapshot_root)
    brain_root = Path(brain_root)
    verification = verify_snapshot(snapshot_root)
    manifest, _ = _load_manifest(snapshot_root)
    if not brain_root.is_absolute():
        _fail("request_invalid", "brain_root must be absolute")
    try:
        root_mode = brain_root.lstat().st_mode
    except OSError as exc:
        _fail("restore_live_root_invalid", str(exc))
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        _fail("restore_live_root_invalid", f"unsafe brain_root: {brain_root}")

    workspace = Path(tempfile.mkdtemp(
        dir=brain_root.parent,
        prefix=f".{brain_root.name}.restore-",
    ))
    staged = workspace / "staged"
    backup = workspace / "backup"
    activated = False
    try:
        _copy_tree_no_symlinks(brain_root, staged)
        targets = manifest["brain_targets"]
        if not isinstance(targets, dict) or set(targets) != {
            "object_kinds", "directories", "files",
        }:
            _fail("snapshot_manifest_invalid", "brain_targets is invalid")
        if targets["object_kinds"] != dict(sorted(BrainStore._KIND_DIR.items())):
            _fail("snapshot_manifest_invalid", "object kind coverage is invalid")
        for relative in targets["directories"]:
            _remove_stage_target(staged / _safe_relative(relative))
        for relative in targets["files"]:
            _remove_stage_target(staged / _safe_relative(relative))
        brain_entries = [
            entry for entry in manifest["files"]
            if entry["scope"] == "brain"
        ]
        for entry in brain_entries:
            _copy_file(
                snapshot_root / entry["snapshot_path"],
                staged / entry["path"],
            )
        staged_inventory = {
            relative: _hash_file(staged / relative)
            for relative in sorted({
                *(
                    path
                    for directory in targets["directories"]
                    for path in _walk_regular_files(staged, directory)
                ),
                *(
                    relative
                    for relative in targets["files"]
                    if (staged / relative).exists()
                ),
            })
        }
        expected_inventory = {
            entry["path"]: (entry["sha256"], entry["size"])
            for entry in brain_entries
        }
        if staged_inventory != expected_inventory:
            _fail(
                "restore_staging_mismatch",
                "restored staging inventory does not match snapshot",
            )
        _rename_path(brain_root, backup)
        try:
            _rename_path(staged, brain_root)
            activated = True
        except Exception as exc:
            try:
                _rename_path(backup, brain_root)
            except Exception as rollback_exc:
                _fail(
                    "restore_rollback_failed",
                    f"activation failed: {exc}; rollback failed: {rollback_exc}",
                )
            _fail("restore_activation_failed", str(exc))
        return RestoreResult(
            snapshot_id=verification.snapshot_id,
            brain_root=brain_root,
            restored_files=tuple(sorted(expected_inventory)),
        )
    except SnapshotError:
        raise
    except Exception as exc:
        _fail("restore_failed", str(exc))
    finally:
        if not activated and not brain_root.exists() and backup.exists():
            try:
                _rename_path(backup, brain_root)
            except Exception:
                pass
        shutil.rmtree(workspace, ignore_errors=True)
