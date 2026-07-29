"""검증 가능한 full snapshot 생성·검증·brain-only 복원."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from project_brain.installer import MANIFEST_FILENAME
from project_brain.objbase import now_kst
from project_brain.store import BrainStore


_SNAPSHOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
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
_INDEX_FILES = ("index.db", "index.db-wal", "index.db-shm")


class SnapshotError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        paths: tuple[Path, ...] = (),
    ):
        self.code = code
        self.detail = detail
        self.paths = paths
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


def _fail(
    code: str,
    detail: str,
    *,
    paths: tuple[Path, ...] = (),
) -> None:
    raise SnapshotError(code, detail, paths=paths)


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value:
        _fail("snapshot_manifest_invalid", "file path must be non-empty")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        _fail("snapshot_manifest_invalid", f"unsafe relative path: {value!r}")
    return path.as_posix()


def _open_absolute_directory(path: Path, *, create: bool) -> int:
    path = Path(path)
    if not path.is_absolute():
        _fail("request_invalid", f"path must be absolute: {path}")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                if not create:
                    _fail(
                        "source_unavailable",
                        f"directory does not exist: {path}",
                        paths=(path,),
                    )
                os.mkdir(part, 0o755, dir_fd=descriptor)
                os.fsync(descriptor)
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                os.fsync(child)
            except OSError as exc:
                code = (
                    "symlink_forbidden"
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}
                    else "source_unavailable"
                )
                _fail(code, f"cannot pin directory {path}: {exc}", paths=(path,))
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_relative_regular(root: Path, relative: str) -> int:
    relative = _safe_relative(relative)
    descriptor = _open_absolute_directory(root, create=False)
    try:
        root_device = os.fstat(descriptor).st_dev
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            except OSError as exc:
                code = (
                    "symlink_forbidden"
                    if exc.errno in {errno.ELOOP, errno.ENOTDIR}
                    else "source_unavailable"
                )
                _fail(
                    code,
                    f"cannot traverse {root / relative}: {exc}",
                    paths=(root / relative,),
                )
            if os.fstat(child).st_dev != root_device:
                os.close(child)
                _fail(
                    "filesystem_mismatch",
                    f"path crosses a filesystem boundary: {root / relative}",
                    paths=(root / relative,),
                )
            os.close(descriptor)
            descriptor = child
        try:
            file_fd = os.open(
                parts[-1],
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
        except OSError as exc:
            code = (
                "symlink_forbidden"
                if exc.errno in {errno.ELOOP, errno.ENOTDIR}
                else "source_unavailable"
            )
            _fail(code, f"cannot open {root / relative}: {exc}", paths=(root / relative,))
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode):
            os.close(file_fd)
            _fail(
                "source_type_invalid",
                f"source is not a regular file: {root / relative}",
                paths=(root / relative,),
            )
        if opened.st_dev != root_device:
            os.close(file_fd)
            _fail(
                "filesystem_mismatch",
                f"file is on another filesystem: {root / relative}",
                paths=(root / relative,),
            )
        return file_fd
    finally:
        os.close(descriptor)


def _read_regular(root: Path, relative: str) -> bytes:
    descriptor = _open_relative_regular(root, relative)
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _hash_regular(root: Path, relative: str) -> tuple[str, int]:
    descriptor = _open_relative_regular(root, relative)
    try:
        before = os.fstat(descriptor)
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
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            _fail(
                "source_fingerprint_changed",
                f"source changed while hashing: {root / relative}",
            )
        return digest.hexdigest(), size
    finally:
        os.close(descriptor)


def _hash_file(path: Path) -> tuple[str, int]:
    path = Path(path)
    return _hash_regular(path.parent, path.name)


def _scan_tree(
    root: Path,
    *,
    unsafe_code: str = "source_type_invalid",
) -> tuple[set[str], set[str]]:
    root = Path(root)
    root_fd = _open_absolute_directory(root, create=False)
    directories: set[str] = set()
    files: set[str] = set()
    root_device = os.fstat(root_fd).st_dev

    def visit(descriptor: int, prefix: str) -> None:
        for name in sorted(os.listdir(descriptor)):
            relative = f"{prefix}/{name}" if prefix else name
            child_stat = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if child_stat.st_dev != root_device or stat.S_ISLNK(child_stat.st_mode):
                _fail(unsafe_code, f"unsafe tree entry: {root / relative}")
            if stat.S_ISDIR(child_stat.st_mode):
                directories.add(relative)
                child_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                try:
                    visit(child_fd, relative)
                finally:
                    os.close(child_fd)
            elif stat.S_ISREG(child_stat.st_mode):
                files.add(relative)
            else:
                _fail(unsafe_code, f"unsupported tree entry: {root / relative}")

    try:
        visit(root_fd, "")
        return directories, files
    finally:
        os.close(root_fd)


def _walk_regular_files(root: Path, relative_directory: str) -> list[str]:
    directory = root / relative_directory
    try:
        _, files = _scan_tree(directory)
    except SnapshotError as exc:
        if exc.code == "source_unavailable":
            return []
        raise
    return sorted(f"{relative_directory}/{path}" for path in files)


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
    try:
        raw = json.loads(_read_regular(repo_root, MANIFEST_FILENAME))
    except SnapshotError as exc:
        if exc.code == "source_unavailable":
            return [], []
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail("install_manifest_invalid", str(exc))
    files = raw.get("files")
    if not isinstance(files, dict):
        _fail("install_manifest_invalid", "install manifest files must be an object")
    inventory: list[dict] = []
    paths: list[str] = []
    for raw_path, recorded_sha in sorted(files.items()):
        relative = _safe_relative(raw_path)
        if not isinstance(recorded_sha, str) or _SHA256.fullmatch(recorded_sha) is None:
            _fail("install_manifest_invalid", f"invalid managed hash: {relative}")
        try:
            actual_sha, _ = _hash_regular(repo_root, relative)
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
        try:
            _hash_regular(request.brain_root, relative)
        except SnapshotError as exc:
            if exc.code != "source_unavailable":
                raise
        else:
            brain_paths.add(relative)
    for relative in sorted(brain_paths):
        digest, size = _hash_regular(request.brain_root, relative)
        files.append({
            "scope": "brain",
            "path": relative,
            "sha256": digest,
            "size": size,
            "copied": True,
            "snapshot_path": f"payload/brain/{relative}",
        })

    managed, managed_paths = _managed_inventory(request.repo_root)
    repo_paths: set[str] = set()
    for relative in (".project-brain.json", MANIFEST_FILENAME, *managed_paths):
        try:
            _hash_regular(request.repo_root, relative)
        except SnapshotError as exc:
            if exc.code != "source_unavailable":
                raise
        else:
            repo_paths.add(relative)
    for relative in sorted(repo_paths):
        digest, size = _hash_regular(request.repo_root, relative)
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


def _corpus_fingerprint(objects: dict[str, dict]) -> str:
    digest = hashlib.sha256()
    for object_id in sorted(objects):
        digest.update(object_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(BrainStore.object_bytes(objects[object_id]))
        digest.update(b"\0")
    return digest.hexdigest()


def _derive_snapshot_metadata(files: list[dict], payload_root: Path) -> tuple[dict, dict]:
    object_directories = tuple(sorted(set(BrainStore._KIND_DIR.values())))
    counts = {kind: 0 for kind in BrainStore._KIND_DIR}
    objects: dict[str, dict] = {}
    by_path = {
        entry["path"]: entry
        for entry in files
        if entry["scope"] == "brain"
    }
    for relative, entry in sorted(by_path.items()):
        object_directory = next(
            (
                directory
                for directory in object_directories
                if relative.startswith(directory + "/")
            ),
            None,
        )
        if object_directory is None:
            continue
        if not relative.endswith(".json"):
            _fail("snapshot_metadata_mismatch", f"object file is not JSON: {relative}")
        try:
            value = json.loads(_read_regular(payload_root, entry["snapshot_path"]))
        except (UnicodeError, json.JSONDecodeError, SnapshotError) as exc:
            _fail("snapshot_metadata_mismatch", f"invalid object payload {relative}: {exc}")
        actual_kind = value.get("kind") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or actual_kind not in BrainStore._KIND_DIR
            or BrainStore._KIND_DIR[actual_kind] != object_directory
            or not isinstance(value.get("id"), str)
            or not value["id"]
            or value["id"] in objects
        ):
            _fail("snapshot_metadata_mismatch", f"invalid object identity: {relative}")
        objects[value["id"]] = value
        counts[actual_kind] += 1

    def fingerprint(relative: str) -> dict | None:
        entry = by_path.get(relative)
        if entry is None:
            return None
        return {"sha256": entry["sha256"], "size": entry["size"]}

    corpus = {
        "kind_counts": dict(sorted(counts.items())),
        "object_ids": sorted(objects),
        "fingerprint": _corpus_fingerprint(objects),
    }
    derived = {
        "index": {
            name: fingerprint(f".brain-local/{name}")
            for name in _INDEX_FILES
        },
        "stale_set": fingerprint(".brain-local/stale-set.json"),
    }
    return corpus, derived


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = _read_regular(source.parent, source.name)
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
        _fail("snapshot_lock_failed", str(exc), paths=getattr(exc, "paths", ()))


def _create_snapshot_locked(request: SnapshotRequest) -> SnapshotResult:
    _validate_request(request)
    for source_root in (request.brain_root, request.repo_root, request.engine_root):
        descriptor = _open_absolute_directory(source_root, create=False)
        os.close(descriptor)
    output_fd = _open_absolute_directory(request.output_root, create=True)
    os.close(output_fd)
    final_root = request.output_root / request.snapshot_id
    try:
        final_root.lstat()
    except FileNotFoundError:
        pass
    else:
        _fail("snapshot_exists", f"snapshot already exists: {final_root}")
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
        roots = {"brain": request.brain_root, "repo": request.repo_root}
        for entry in files_before:
            _copy_file(
                roots[entry["scope"]] / entry["path"],
                temporary_root / entry["snapshot_path"],
            )
            copied_sha, copied_size = _hash_regular(
                temporary_root,
                entry["snapshot_path"],
            )
            if (copied_sha, copied_size) != (entry["sha256"], entry["size"]):
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
        corpus, derived = _derive_snapshot_metadata(files_before, temporary_root)
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
                if entry["scope"] == "brain"
                and entry["path"].startswith("raw/sources/")
            ],
            "managed_files": managed_before,
            "corpus": corpus,
            "derived": derived,
        }
        manifest_bytes = _manifest_bytes(manifest)
        manifest_path = temporary_root / "manifest.json"
        manifest_path.write_bytes(manifest_bytes)
        with manifest_path.open("rb") as stream:
            os.fsync(stream.fileno())
        _rename_path(temporary_root, final_root)
        parent_fd = _open_absolute_directory(request.output_root, create=False)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
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


def _load_manifest(
    snapshot_root: Path,
    *,
    expected_manifest_sha256: str,
) -> tuple[dict, bytes]:
    if (
        not isinstance(expected_manifest_sha256, str)
        or _SHA256.fullmatch(expected_manifest_sha256) is None
    ):
        _fail(
            "expected_manifest_sha256_invalid",
            "trusted manifest receipt must be an exact lowercase SHA-256",
        )
    try:
        manifest_bytes = _read_regular(Path(snapshot_root), "manifest.json")
    except SnapshotError as exc:
        if exc.code == "symlink_forbidden":
            raise
        _fail("snapshot_manifest_invalid", exc.detail, paths=exc.paths)
    actual_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_sha256 != expected_manifest_sha256:
        _fail(
            "manifest_sha256_mismatch",
            "snapshot manifest does not match the trusted external receipt",
        )
    try:
        manifest = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
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
        "corpus",
        "derived",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        _fail("snapshot_manifest_invalid", "manifest keys do not match contract")
    if manifest["version"] != 1 or _SNAPSHOT_ID.fullmatch(
        manifest.get("snapshot_id", "")
    ) is None:
        _fail("snapshot_manifest_invalid", "snapshot version or ID is invalid")
    if (
        not isinstance(manifest["created_at"], str)
        or not isinstance(manifest["source_fingerprint"], str)
        or _SHA256.fullmatch(manifest["source_fingerprint"]) is None
        or (
            manifest["repo_head"] is not None
            and (
                not isinstance(manifest["repo_head"], str)
                or _GIT_SHA.fullmatch(manifest["repo_head"]) is None
            )
        )
        or (
            manifest["engine_head"] is not None
            and (
                not isinstance(manifest["engine_head"], str)
                or _GIT_SHA.fullmatch(manifest["engine_head"]) is None
            )
        )
        or not isinstance(manifest["managed_files"], list)
        or not isinstance(manifest["raw_sources"], list)
    ):
        _fail("snapshot_manifest_invalid", "manifest metadata types are invalid")
    targets = manifest["brain_targets"]
    if (
        not isinstance(targets, dict)
        or set(targets) != {"object_kinds", "directories", "files"}
        or targets["object_kinds"] != dict(sorted(BrainStore._KIND_DIR.items()))
        or targets["directories"] != list(_BRAIN_DIRECTORIES)
        or targets["files"] != list(_BRAIN_FILES)
    ):
        _fail("snapshot_manifest_invalid", "brain target coverage is invalid")
    roots = manifest["roots"]
    if (
        not isinstance(roots, dict)
        or set(roots) != {"brain_root", "repo_root", "engine_root"}
        or any(
            not isinstance(value, str) or not Path(value).is_absolute()
            for value in roots.values()
        )
    ):
        _fail("snapshot_manifest_invalid", "snapshot roots are invalid")
    if not isinstance(manifest["files"], list):
        _fail("snapshot_manifest_invalid", "manifest files must be a list")
    return manifest, manifest_bytes


def _validate_file_entries(snapshot_root: Path, manifest: dict) -> set[str]:
    expected_payload_paths: set[str] = set()
    seen_keys: set[tuple[str, str]] = set()
    previous_key: tuple[str, str] | None = None
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
            _fail("snapshot_manifest_invalid", "payload path does not match source")
        if (
            not isinstance(entry["sha256"], str)
            or _SHA256.fullmatch(entry["sha256"]) is None
            or type(entry["size"]) is not int
            or entry["size"] < 0
            or entry["copied"] is not True
        ):
            _fail("snapshot_manifest_invalid", "file hash/size/copy flag is invalid")
        key = (entry["scope"], relative)
        if key in seen_keys or snapshot_path in expected_payload_paths:
            _fail("snapshot_manifest_invalid", "duplicate file entry")
        if previous_key is not None and key < previous_key:
            _fail("snapshot_manifest_invalid", "file entries must be sorted")
        previous_key = key
        seen_keys.add(key)
        expected_payload_paths.add(snapshot_path)
        try:
            actual = _hash_regular(snapshot_root, snapshot_path)
        except SnapshotError as exc:
            _fail(
                "snapshot_payload_hash_mismatch",
                f"snapshot payload unavailable: {snapshot_path}: {exc.detail}",
            )
        if actual != (entry["sha256"], entry["size"]):
            _fail(
                "snapshot_payload_hash_mismatch",
                f"snapshot payload changed: {snapshot_path}",
            )
    return expected_payload_paths


def _validate_completeness_types(manifest: dict) -> None:
    corpus = manifest["corpus"]
    if (
        not isinstance(corpus, dict)
        or set(corpus) != {"kind_counts", "object_ids", "fingerprint"}
        or not isinstance(corpus["kind_counts"], dict)
        or set(corpus["kind_counts"]) != set(BrainStore._KIND_DIR)
        or any(
            type(value) is not int or value < 0
            for value in corpus["kind_counts"].values()
        )
        or not isinstance(corpus["object_ids"], list)
        or any(
            not isinstance(object_id, str) or not object_id
            for object_id in corpus["object_ids"]
        )
        or corpus["object_ids"] != sorted(set(corpus["object_ids"]))
        or not isinstance(corpus["fingerprint"], str)
        or _SHA256.fullmatch(corpus["fingerprint"]) is None
    ):
        _fail("snapshot_manifest_invalid", "corpus completeness metadata is invalid")

    def valid_fingerprint(value: object) -> bool:
        return value is None or (
            isinstance(value, dict)
            and set(value) == {"sha256", "size"}
            and isinstance(value["sha256"], str)
            and _SHA256.fullmatch(value["sha256"]) is not None
            and type(value["size"]) is int
            and value["size"] >= 0
        )

    derived = manifest["derived"]
    if (
        not isinstance(derived, dict)
        or set(derived) != {"index", "stale_set"}
        or not isinstance(derived["index"], dict)
        or set(derived["index"]) != set(_INDEX_FILES)
        or any(
            not valid_fingerprint(value)
            for value in derived["index"].values()
        )
        or not valid_fingerprint(derived["stale_set"])
    ):
        _fail("snapshot_manifest_invalid", "derived fingerprints are invalid")

    for entry in manifest["managed_files"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != {
                "path",
                "recorded_sha256",
                "actual_sha256",
                "matches_recorded",
            }
            or not isinstance(entry["recorded_sha256"], str)
            or _SHA256.fullmatch(entry["recorded_sha256"]) is None
            or (
                entry["actual_sha256"] is not None
                and (
                    not isinstance(entry["actual_sha256"], str)
                    or _SHA256.fullmatch(entry["actual_sha256"]) is None
                )
            )
            or type(entry["matches_recorded"]) is not bool
        ):
            _fail("snapshot_manifest_invalid", "managed file metadata is invalid")


def _expected_tree(expected_files: set[str]) -> tuple[set[str], set[str]]:
    directories: set[str] = set()
    for relative in expected_files:
        parent = PurePosixPath(relative).parent
        while parent.as_posix() != ".":
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories, {"manifest.json", *expected_files}


def _validate_manifest_derivations(snapshot_root: Path, manifest: dict) -> None:
    _validate_completeness_types(manifest)
    expected_raw = [
        {
            "path": entry["path"],
            "sha256": entry["sha256"],
            "size": entry["size"],
        }
        for entry in manifest["files"]
        if entry["scope"] == "brain"
        and entry["path"].startswith("raw/sources/")
    ]
    if manifest["raw_sources"] != expected_raw:
        _fail("snapshot_metadata_mismatch", "raw source inventory is inconsistent")
    expected_fingerprint = _inventory_fingerprint(
        manifest["files"],
        manifest["managed_files"],
        repo_head=manifest["repo_head"],
        engine_head=manifest["engine_head"],
    )
    if manifest["source_fingerprint"] != expected_fingerprint:
        _fail("snapshot_metadata_mismatch", "source fingerprint is inconsistent")
    corpus, derived = _derive_snapshot_metadata(manifest["files"], snapshot_root)
    if manifest["corpus"] != corpus or manifest["derived"] != derived:
        _fail("snapshot_metadata_mismatch", "corpus or derived metadata is inconsistent")

    repo_entries = {
        entry["path"]: entry
        for entry in manifest["files"]
        if entry["scope"] == "repo"
    }
    install_entry = repo_entries.get(MANIFEST_FILENAME)
    expected_managed: list[dict] = []
    if install_entry is not None:
        try:
            install = json.loads(
                _read_regular(snapshot_root, install_entry["snapshot_path"])
            )
            recorded = install["files"]
        except (KeyError, TypeError, UnicodeError, json.JSONDecodeError, SnapshotError):
            _fail("snapshot_metadata_mismatch", "captured install manifest is invalid")
        if not isinstance(recorded, dict):
            _fail("snapshot_metadata_mismatch", "captured managed files are invalid")
        for raw_path, recorded_sha in sorted(recorded.items()):
            relative = _safe_relative(raw_path)
            if (
                not isinstance(recorded_sha, str)
                or _SHA256.fullmatch(recorded_sha) is None
            ):
                _fail(
                    "snapshot_metadata_mismatch",
                    f"captured managed hash is invalid: {relative}",
                )
            actual = repo_entries.get(relative)
            actual_sha = actual["sha256"] if actual is not None else None
            expected_managed.append({
                "path": relative,
                "recorded_sha256": recorded_sha,
                "actual_sha256": actual_sha,
                "matches_recorded": actual_sha == recorded_sha,
            })
    if manifest["managed_files"] != expected_managed:
        _fail("snapshot_metadata_mismatch", "managed file metadata is inconsistent")


def verify_snapshot(
    snapshot_root: Path,
    *,
    expected_manifest_sha256: str,
) -> SnapshotVerification:
    snapshot_root = Path(snapshot_root)
    manifest, manifest_bytes = _load_manifest(
        snapshot_root,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    expected_payload_paths = _validate_file_entries(snapshot_root, manifest)
    expected_directories, expected_files = _expected_tree(expected_payload_paths)
    actual_directories, actual_files = _scan_tree(
        snapshot_root,
        unsafe_code="snapshot_payload_inventory_mismatch",
    )
    if actual_directories != expected_directories or actual_files != expected_files:
        _fail(
            "snapshot_payload_inventory_mismatch",
            "snapshot tree inventory differs from manifest",
        )
    _validate_manifest_derivations(snapshot_root, manifest)
    return SnapshotVerification(
        ok=True,
        snapshot_id=manifest["snapshot_id"],
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        file_count=len(manifest["files"]),
    )


def _copy_tree_no_symlinks(source: Path, destination: Path) -> None:
    directories, files = _scan_tree(source, unsafe_code="restore_live_tree_unsafe")
    destination.mkdir()
    for relative in sorted(directories, key=lambda value: (value.count("/"), value)):
        (destination / relative).mkdir()
    for relative in sorted(files):
        _copy_file(source / relative, destination / relative)


def _remove_stage_target(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
        shutil.rmtree(path)
    elif stat.S_ISREG(mode):
        path.unlink()
    else:
        _fail("restore_staging_unsafe", f"unsafe staging target: {path}")


def _rename_path(source: Path, destination: Path) -> None:
    os.rename(source, destination)


def _restore_state_root(brain_root: Path) -> Path:
    from project_brain.corpus_io import restore_state_root

    return restore_state_root(brain_root)


def _fsync_directory(path: Path) -> None:
    descriptor = _open_absolute_directory(path, create=False)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_journal(state_root: Path, payload: dict) -> None:
    state_root.mkdir(mode=0o700, parents=False, exist_ok=True)
    temporary = state_root / ".journal.json.tmp"
    data = _manifest_bytes(payload)
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, state_root / "journal.json")
    _fsync_directory(state_root)
    _fsync_directory(state_root.parent)


def _read_journal(state_root: Path) -> dict:
    try:
        raw = json.loads(_read_regular(state_root, "journal.json"))
    except (UnicodeError, json.JSONDecodeError, SnapshotError) as exc:
        _fail(
            "recovery_required",
            f"restore journal is unreadable: {exc}",
            paths=(state_root,),
        )
    if not isinstance(raw, dict):
        _fail("recovery_required", "restore journal is invalid", paths=(state_root,))
    return raw


def _remove_restore_state(state_root: Path) -> None:
    try:
        mode = state_root.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        _fail(
            "recovery_required",
            "restore state root is not a safe directory",
            paths=(state_root,),
        )
    tombstone = state_root.with_name(
        f"{state_root.name}.cleanup-{uuid.uuid4().hex}"
    )
    os.rename(state_root, tombstone)
    _fsync_directory(state_root.parent)
    shutil.rmtree(tombstone)


def _brain_snapshot_inventory(brain_root: Path, manifest: dict) -> dict[str, tuple[str, int]]:
    targets = manifest["brain_targets"]
    paths = {
        path
        for directory in targets["directories"]
        for path in _walk_regular_files(brain_root, directory)
    }
    for relative in targets["files"]:
        try:
            _hash_regular(brain_root, relative)
        except SnapshotError as exc:
            if exc.code != "source_unavailable":
                raise
        else:
            paths.add(relative)
    return {relative: _hash_regular(brain_root, relative) for relative in sorted(paths)}


def _expected_brain_inventory(manifest: dict) -> dict[str, tuple[str, int]]:
    return {
        entry["path"]: (entry["sha256"], entry["size"])
        for entry in manifest["files"]
        if entry["scope"] == "brain"
    }


def _validate_recovery_journal(
    journal: dict,
    *,
    state_root: Path,
    snapshot_root: Path,
    brain_root: Path,
    expected_manifest_sha256: str,
) -> tuple[Path, Path, Path, str]:
    required = {
        "version",
        "phase",
        "snapshot_root",
        "brain_root",
        "expected_manifest_sha256",
        "workspace",
    }
    if set(journal) != required or journal.get("version") != 1:
        _fail("recovery_required", "restore journal contract is invalid", paths=(state_root,))
    workspace = state_root / "workspace"
    if (
        journal["snapshot_root"] != str(snapshot_root)
        or journal["brain_root"] != str(brain_root)
        or journal["expected_manifest_sha256"] != expected_manifest_sha256
        or journal["workspace"] != str(workspace)
        or journal["phase"] not in {
            "preparing",
            "prepared",
            "moving_live",
            "activating",
            "activated",
        }
    ):
        _fail(
            "recovery_required",
            "restore journal does not match this trusted restore request",
            paths=(state_root, workspace),
        )
    return workspace, workspace / "staged", workspace / "backup", journal["phase"]


def _recover_restore(
    *,
    state_root: Path,
    snapshot_root: Path,
    brain_root: Path,
    expected_manifest_sha256: str,
    manifest: dict,
) -> None:
    journal_path = state_root / "journal.json"
    try:
        journal_path.lstat()
    except FileNotFoundError:
        if state_root.exists():
            _remove_restore_state(state_root)
        return
    journal = _read_journal(state_root)
    workspace, staged, backup, phase = _validate_recovery_journal(
        journal,
        state_root=state_root,
        snapshot_root=snapshot_root,
        brain_root=brain_root,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    live_exists = brain_root.exists()
    staged_exists = staged.exists()
    backup_exists = backup.exists()
    expected = _expected_brain_inventory(manifest)

    if not live_exists and backup_exists:
        try:
            _rename_path(backup, brain_root)
            _fsync_directory(brain_root.parent)
        except Exception as exc:
            _fail(
                "recovery_required",
                f"could not roll back interrupted restore: {exc}",
                paths=(state_root, workspace, backup, staged),
            )
        _remove_restore_state(state_root)
        return
    if live_exists and backup_exists and not staged_exists and phase in {
        "activating",
        "activated",
    }:
        if _brain_snapshot_inventory(brain_root, manifest) != expected:
            _fail(
                "recovery_required",
                "activated corpus cannot be proven to match the snapshot",
                paths=(state_root, workspace, backup, brain_root),
            )
        _remove_restore_state(state_root)
        return
    if live_exists and not backup_exists:
        _remove_restore_state(state_root)
        return
    _fail(
        "recovery_required",
        "restore state cannot be recovered without operator review",
        paths=(state_root, workspace, backup, staged),
    )


def restore_snapshot(
    snapshot_root: Path,
    brain_root: Path,
    *,
    expected_manifest_sha256: str,
) -> RestoreResult:
    from project_brain.corpus_io import (
        CorpusIOError,
        corpus_lock,
        recover_unfinished_transaction_unlocked,
        stable_corpus_lock,
    )

    snapshot_root = Path(snapshot_root)
    brain_root = Path(brain_root)
    if not brain_root.is_absolute():
        _fail("request_invalid", "brain_root must be absolute")
    verification = verify_snapshot(
        snapshot_root,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    manifest, _ = _load_manifest(
        snapshot_root,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    state_root = _restore_state_root(brain_root)
    try:
        with stable_corpus_lock(brain_root, exclusive=True):
            _recover_restore(
                state_root=state_root,
                snapshot_root=snapshot_root,
                brain_root=brain_root,
                expected_manifest_sha256=expected_manifest_sha256,
                manifest=manifest,
            )
            with corpus_lock(brain_root, exclusive=True):
                recover_unfinished_transaction_unlocked(brain_root)
            return _restore_snapshot_locked(
                snapshot_root,
                brain_root,
                expected_manifest_sha256=expected_manifest_sha256,
                verification=verification,
                manifest=manifest,
            )
    except SnapshotError:
        raise
    except CorpusIOError as exc:
        _fail("restore_lock_failed", str(exc), paths=getattr(exc, "paths", ()))


def _restore_snapshot_locked(
    snapshot_root: Path,
    brain_root: Path,
    *,
    expected_manifest_sha256: str,
    verification: SnapshotVerification,
    manifest: dict,
) -> RestoreResult:
    try:
        root_mode = brain_root.lstat().st_mode
    except OSError as exc:
        _fail("restore_live_root_invalid", str(exc))
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        _fail("restore_live_root_invalid", f"unsafe brain_root: {brain_root}")

    state_root = _restore_state_root(brain_root)
    state_root.mkdir(mode=0o700, parents=False, exist_ok=False)
    _fsync_directory(state_root.parent)
    workspace = state_root / "workspace"
    workspace.mkdir()
    staged = workspace / "staged"
    backup = workspace / "backup"
    journal = {
        "version": 1,
        "phase": "preparing",
        "snapshot_root": str(snapshot_root),
        "brain_root": str(brain_root),
        "expected_manifest_sha256": expected_manifest_sha256,
        "workspace": str(workspace),
    }
    try:
        _write_journal(state_root, journal)
        _copy_tree_no_symlinks(brain_root, staged)
        targets = manifest["brain_targets"]
        for relative in targets["directories"]:
            _remove_stage_target(staged / _safe_relative(relative))
        for relative in targets["files"]:
            _remove_stage_target(staged / _safe_relative(relative))
        brain_entries = [
            entry for entry in manifest["files"] if entry["scope"] == "brain"
        ]
        for entry in brain_entries:
            _copy_file(
                snapshot_root / entry["snapshot_path"],
                staged / entry["path"],
            )
        expected_inventory = _expected_brain_inventory(manifest)
        if _brain_snapshot_inventory(staged, manifest) != expected_inventory:
            _fail(
                "restore_staging_mismatch",
                "restored staging inventory does not match snapshot",
            )
        journal["phase"] = "prepared"
        _write_journal(state_root, journal)
        journal["phase"] = "moving_live"
        _write_journal(state_root, journal)
        _rename_path(brain_root, backup)
        _fsync_directory(brain_root.parent)
        journal["phase"] = "activating"
        _write_journal(state_root, journal)
        try:
            _rename_path(staged, brain_root)
            _fsync_directory(brain_root.parent)
        except Exception as activation_exc:
            try:
                _rename_path(backup, brain_root)
                _fsync_directory(brain_root.parent)
            except Exception as rollback_exc:
                _fail(
                    "recovery_required",
                    (
                        f"activation failed: {activation_exc}; "
                        f"rollback failed: {rollback_exc}"
                    ),
                    paths=(state_root, workspace, backup, staged),
                )
            _remove_restore_state(state_root)
            _fail("restore_activation_failed", str(activation_exc))
        journal["phase"] = "activated"
        _write_journal(state_root, journal)
        if _brain_snapshot_inventory(brain_root, manifest) != expected_inventory:
            _fail(
                "recovery_required",
                "activated corpus does not match snapshot",
                paths=(state_root, workspace, backup, brain_root),
            )
        _remove_restore_state(state_root)
        return RestoreResult(
            snapshot_id=verification.snapshot_id,
            brain_root=brain_root,
            restored_files=tuple(sorted(expected_inventory)),
        )
    except SnapshotError:
        raise
    except Exception as exc:
        if (state_root / "journal.json").exists():
            _fail(
                "recovery_required",
                str(exc),
                paths=(state_root, workspace, backup, staged),
            )
        shutil.rmtree(state_root, ignore_errors=True)
        _fail("restore_failed", str(exc))
