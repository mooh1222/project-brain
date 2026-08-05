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
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from project_brain.installer import MANIFEST_FILENAME
from project_brain.objbase import now_kst
from project_brain.store import BrainStore


_SNAPSHOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
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
_PHASE_RECORDS = (b"preparing", b"prepared", b"moved_live", b"activated")
_PHASE_LOG_MAX_BYTES = sum(len(record) + 1 for record in _PHASE_RECORDS)
_PHASE_READ_EINTR_RETRY_LIMIT = 8


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
    repo_head: str
    engine_head: str
    corpus_fingerprint: str


@dataclass(frozen=True)
class RestoreResult:
    snapshot_id: str
    brain_root: Path
    restored_files: tuple[str, ...]


@dataclass(frozen=True)
class GitWorktreeReceipt:
    root: str
    head: str
    status_bytes: bytes
    status_sha256: str


@dataclass(frozen=True)
class GitDirtReceipt:
    root: str
    head: str
    status_bytes: bytes
    status_sha256: str
    entry_count: int
    content_manifest_bytes: bytes
    content_manifest_sha256: str


@dataclass(frozen=True)
class SafeTreeEntry:
    """One no-follow entry captured through a pinned absolute tree root."""

    path: str
    entry_type: str
    mode: int
    size: int
    sha256: str


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


def _after_tree_read_hook(path: Path) -> None:
    """Deterministic test seam for a replacement after an opened-file read."""


def _tree_relative(value: object) -> str:
    if not isinstance(value, str) or not value:
        _fail("tree_path_invalid", "tree path must be a non-empty relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(
        part in {"", ".", ".."} for part in value.split("/")
    ):
        _fail("tree_path_invalid", f"unsafe relative tree path: {value!r}")
    return path.as_posix()


def _tree_exclusions(root: Path, excluded_paths: Collection[Path]) -> set[str]:
    excluded: set[str] = set()
    for raw_path in excluded_paths:
        path = Path(raw_path)
        if not path.is_absolute() or path != Path(os.path.abspath(path)):
            _fail(
                "tree_path_invalid",
                f"excluded tree path must be exact absolute: {path}",
                paths=(path,),
            )
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            _fail(
                "tree_path_invalid",
                f"excluded tree path escapes root: {path}",
                paths=(path,),
            )
        if relative in {"", "."}:
            _fail("tree_path_invalid", "cannot exclude the tree root", paths=(path,))
        excluded.add(_tree_relative(relative))
    return excluded


def _excluded_tree_path(relative: str, excluded: set[str]) -> bool:
    return any(
        relative == candidate or relative.startswith(candidate + "/")
        for candidate in excluded
    )


def _capture_tree_entry(
    *,
    root: Path,
    root_device: int,
    parent_fd: int,
    name: str,
    relative: str,
    recursive: bool,
    excluded: set[str],
    entries: dict[str, SafeTreeEntry],
) -> None:
    if _excluded_tree_path(relative, excluded):
        return
    try:
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as exc:
        _fail(
            "source_unavailable",
            f"cannot inspect tree entry {root / relative}: {exc}",
            paths=(root / relative,),
        )
    if stat.S_ISLNK(before.st_mode):
        _fail(
            "symlink_forbidden",
            f"symlink tree entry is forbidden: {root / relative}",
            paths=(root / relative,),
        )
    if before.st_dev != root_device:
        _fail(
            "filesystem_mismatch",
            f"tree entry crosses a filesystem boundary: {root / relative}",
            paths=(root / relative,),
        )
    mode = stat.S_IMODE(before.st_mode)
    if stat.S_ISDIR(before.st_mode):
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            _fail(
                "symlink_forbidden" if exc.errno in {errno.ELOOP, errno.ENOTDIR} else "source_unavailable",
                f"cannot pin tree directory {root / relative}: {exc}",
                paths=(root / relative,),
            )
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISDIR(opened.st_mode) or not _same_stat(before, opened):
                _fail(
                    "source_fingerprint_changed",
                    f"tree directory changed while opening: {root / relative}",
                    paths=(root / relative,),
                )
            entries.setdefault(
                relative,
                SafeTreeEntry(
                    path=relative,
                    entry_type="directory",
                    mode=mode,
                    size=0,
                    sha256=hashlib.sha256(b"").hexdigest(),
                ),
            )
            if recursive:
                try:
                    names = sorted(os.listdir(descriptor))
                except OSError as exc:
                    _fail(
                        "source_unavailable",
                        f"cannot list tree directory {root / relative}: {exc}",
                        paths=(root / relative,),
                    )
                for child_name in names:
                    child_relative = f"{relative}/{child_name}"
                    _capture_tree_entry(
                        root=root,
                        root_device=root_device,
                        parent_fd=descriptor,
                        name=child_name,
                        relative=child_relative,
                        recursive=True,
                        excluded=excluded,
                        entries=entries,
                    )
            after = os.fstat(descriptor)
            try:
                rebound = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except OSError as exc:
                _fail(
                    "source_fingerprint_changed",
                    f"tree directory changed while reading: {root / relative}: {exc}",
                    paths=(root / relative,),
                )
            if not _same_stat(opened, after) or not _same_stat(opened, rebound):
                _fail(
                    "source_fingerprint_changed",
                    f"tree directory changed while reading: {root / relative}",
                    paths=(root / relative,),
                )
        finally:
            os.close(descriptor)
        return
    if not stat.S_ISREG(before.st_mode):
        _fail(
            "source_type_invalid",
            f"unsupported tree entry: {root / relative}",
            paths=(root / relative,),
        )
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        _fail(
            "symlink_forbidden" if exc.errno in {errno.ELOOP, errno.ENOTDIR} else "source_unavailable",
            f"cannot open tree file {root / relative}: {exc}",
            paths=(root / relative,),
        )
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not _same_stat(before, opened):
            _fail(
                "source_fingerprint_changed",
                f"tree file changed while opening: {root / relative}",
                paths=(root / relative,),
            )
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        _after_tree_read_hook(root / relative)
        after = os.fstat(descriptor)
        try:
            rebound = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            _fail(
                "source_fingerprint_changed",
                f"tree file changed while reading: {root / relative}: {exc}",
                paths=(root / relative,),
            )
        if (
            not _same_stat(opened, after)
            or not _same_stat(opened, rebound)
            or size != after.st_size
        ):
            _fail(
                "source_fingerprint_changed",
                f"tree file changed while reading: {root / relative}",
                paths=(root / relative,),
            )
        entries.setdefault(
            relative,
            SafeTreeEntry(
                path=relative,
                entry_type="regular",
                mode=mode,
                size=size,
                sha256=digest.hexdigest(),
            ),
        )
    finally:
        os.close(descriptor)


def _capture_safe_tree(
    root: Path,
    relative_paths: Collection[str] | None,
    *,
    excluded_paths: Collection[Path] = (),
) -> tuple[SafeTreeEntry, ...]:
    root = Path(root)
    if not root.is_absolute() or root != Path(os.path.abspath(root)):
        _fail("tree_path_invalid", f"tree root must be exact absolute: {root}")
    excluded = _tree_exclusions(root, excluded_paths)
    scan_all = relative_paths is None
    root_fd = _open_absolute_directory(root, create=False)
    entries: dict[str, SafeTreeEntry] = {}
    try:
        root_stat = os.fstat(root_fd)
        requested = (
            sorted(os.listdir(root_fd))
            if relative_paths is None
            else sorted({_tree_relative(value) for value in relative_paths})
        )
        for relative in requested:
            parts = PurePosixPath(relative).parts
            descriptor = os.dup(root_fd)
            directory_bindings: list[tuple[int, str, os.stat_result, str]] = []
            try:
                prefix = ""
                for part in parts[:-1]:
                    prefix = f"{prefix}/{part}" if prefix else part
                    if _excluded_tree_path(prefix, excluded):
                        break
                    try:
                        before = os.stat(
                            part,
                            dir_fd=descriptor,
                            follow_symlinks=False,
                        )
                    except OSError as exc:
                        _fail(
                            "source_unavailable",
                            f"cannot inspect tree path {root / relative}: {exc}",
                            paths=(root / relative,),
                        )
                    if stat.S_ISLNK(before.st_mode):
                        _fail(
                            "symlink_forbidden",
                            f"cannot traverse symlink tree path: {root / relative}",
                            paths=(root / relative,),
                        )
                    try:
                        child = os.open(
                            part,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=descriptor,
                        )
                    except OSError as exc:
                        _fail(
                            "symlink_forbidden" if exc.errno in {errno.ELOOP, errno.ENOTDIR} else "source_unavailable",
                            f"cannot traverse tree path {root / relative}: {exc}",
                            paths=(root / relative,),
                        )
                    child_stat = os.fstat(child)
                    if (
                        not stat.S_ISDIR(child_stat.st_mode)
                        or not _same_stat(before, child_stat)
                    ):
                        os.close(child)
                        _fail(
                            "source_fingerprint_changed",
                            f"tree directory changed while opening: {root / prefix}",
                            paths=(root / prefix,),
                        )
                    if child_stat.st_dev != root_stat.st_dev:
                        os.close(child)
                        _fail(
                            "filesystem_mismatch",
                            f"tree path crosses a filesystem boundary: {root / relative}",
                            paths=(root / relative,),
                        )
                    directory_bindings.append(
                        (os.dup(descriptor), part, child_stat, prefix)
                    )
                    os.close(descriptor)
                    descriptor = child
                else:
                    _capture_tree_entry(
                        root=root,
                        root_device=root_stat.st_dev,
                        parent_fd=descriptor,
                        name=parts[-1],
                        relative=relative,
                        recursive=True,
                        excluded=excluded,
                        entries=entries,
                    )
                    for parent_guard, part, opened, bound_relative in reversed(
                        directory_bindings
                    ):
                        try:
                            rebound = os.stat(
                                part,
                                dir_fd=parent_guard,
                                follow_symlinks=False,
                            )
                        except OSError as exc:
                            _fail(
                                "source_fingerprint_changed",
                                (
                                    "tree directory changed while reading: "
                                    f"{root / bound_relative}: {exc}"
                                ),
                                paths=(root / bound_relative,),
                            )
                        if not _same_stat(opened, rebound):
                            _fail(
                                "source_fingerprint_changed",
                                (
                                    "tree directory changed while reading: "
                                    f"{root / bound_relative}"
                                ),
                                paths=(root / bound_relative,),
                            )
            finally:
                os.close(descriptor)
                for parent_guard, _, _, _ in directory_bindings:
                    os.close(parent_guard)
        current_fd = _open_absolute_directory(root, create=False)
        try:
            current = os.fstat(current_fd)
        finally:
            os.close(current_fd)
        if (
            (root_stat.st_dev, root_stat.st_ino)
            != (current.st_dev, current.st_ino)
            or (scan_all and not _same_stat(root_stat, current))
        ):
            _fail(
                "source_fingerprint_changed",
                f"tree root changed while reading: {root}",
                paths=(root,),
            )
    finally:
        os.close(root_fd)
    return tuple(entries[path] for path in sorted(entries))


def capture_tree_entries(
    root: Path,
    relative_paths: Collection[str],
    *,
    excluded_paths: Collection[Path] = (),
) -> tuple[SafeTreeEntry, ...]:
    """Capture named regular files/directories below one pinned tree root."""

    return _capture_safe_tree(root, relative_paths, excluded_paths=excluded_paths)


def scan_tree_entries(
    root: Path,
    *,
    excluded_paths: Collection[Path] = (),
) -> tuple[SafeTreeEntry, ...]:
    """Capture every entry below one pinned tree root without following links."""

    return _capture_safe_tree(root, None, excluded_paths=excluded_paths)


def verify_tree_path_absent(path: Path) -> None:
    """Verify one exact absolute path is absent without creating ancestors."""

    path = Path(path)
    if not path.is_absolute() or path != Path(os.path.abspath(path)):
        _fail("tree_path_invalid", f"tree path must be exact absolute: {path}")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    existing_parts: list[str] = []
    try:
        for index, part in enumerate(path.parts[1:]):
            try:
                inspected = os.stat(
                    part,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                existing_path = Path("/").joinpath(*existing_parts)
                pinned = os.fstat(descriptor)
                verified_fd = _open_absolute_directory(
                    existing_path,
                    create=False,
                )
                try:
                    verified = os.fstat(verified_fd)
                finally:
                    os.close(verified_fd)
                if not _same_stat(pinned, verified):
                    _fail(
                        "source_fingerprint_changed",
                        f"tree path changed while checking absence: {path}",
                        paths=(path,),
                    )
                return
            except OSError as exc:
                _fail(
                    "source_unavailable",
                    f"cannot inspect absent tree path {path}: {exc}",
                    paths=(path,),
                )
            if stat.S_ISLNK(inspected.st_mode):
                _fail(
                    "symlink_forbidden",
                    f"symlink in absent tree path: {path}",
                    paths=(path,),
                )
            if index == len(path.parts[1:]) - 1:
                _fail(
                    "source_exists",
                    f"tree path already exists: {path}",
                    paths=(path,),
                )
            if not stat.S_ISDIR(inspected.st_mode):
                _fail(
                    "source_type_invalid",
                    f"non-directory in absent tree path: {path}",
                    paths=(path,),
                )
            child = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            opened = os.fstat(child)
            if not _same_stat(inspected, opened):
                os.close(child)
                _fail(
                    "source_fingerprint_changed",
                    f"tree path changed while checking absence: {path}",
                    paths=(path,),
                )
            os.close(descriptor)
            descriptor = child
            existing_parts.append(part)
    finally:
        os.close(descriptor)


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


def _required_git_head(root: Path, *, label: str) -> str:
    root = Path(root)
    if not root.is_absolute() or root != Path(os.path.abspath(root)):
        _fail(
            "git_root_invalid",
            f"{label} must be an exact absolute path",
            paths=(root,),
        )
    descriptor = _open_absolute_directory(root, create=False)
    try:
        pinned = os.fstat(descriptor)
        try:
            top = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, ValueError) as exc:
            _fail(
                "git_head_invalid",
                f"{label} Git root check failed: {exc}",
                paths=(root,),
            )
        try:
            top_path = Path(top.stdout.strip())
        except (TypeError, ValueError):
            top_path = Path()
        value = _git_head(root)
        try:
            current = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            _fail(
                "git_root_changed",
                f"{label} changed during Git verification: {exc}",
                paths=(root,),
            )
        if (
            not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino)
            != (pinned.st_dev, pinned.st_ino)
        ):
            _fail(
                "git_root_changed",
                f"{label} changed during Git verification",
                paths=(root,),
            )
        if (
            top.returncode != 0
            or not top.stdout.strip()
            or top_path != root
            or value is None
            or _GIT_SHA.fullmatch(value) is None
        ):
            _fail(
                "git_head_invalid",
                (
                    f"{label} must be an exact Git toplevel at a lowercase "
                    "40-hex commit SHA"
                ),
                paths=(root,),
            )
        return value
    finally:
        os.close(descriptor)


def verify_git_root_head(root: Path, *, label: str) -> str:
    """Resolve one exact no-follow Git root to its trusted current HEAD."""
    return _required_git_head(root, label=label)


def _git_status_bytes(root: Path, *, label: str) -> bytes:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            capture_output=True,
            check=False,
        )
    except (OSError, ValueError) as exc:
        _fail(
            "git_status_invalid",
            f"{label} Git status failed: {exc}",
            paths=(root,),
        )
    if result.returncode != 0:
        _fail(
            "git_status_invalid",
            f"{label} Git status failed with exit {result.returncode}",
            paths=(root,),
        )
    return result.stdout


def _git_dirt_path(raw_path: bytes) -> tuple[bytes, ...]:
    if not raw_path or raw_path.startswith(b"/"):
        _fail("git_dirt_path_unsafe", f"unsafe Git dirt path: {raw_path!r}")
    parts = tuple(raw_path.split(b"/"))
    if any(part in {b"", b".", b".."} for part in parts):
        _fail("git_dirt_path_unsafe", f"unsafe Git dirt path: {raw_path!r}")
    return parts


def _parse_git_status(status_bytes: bytes) -> list[tuple[bytes, str]]:
    if not isinstance(status_bytes, bytes):
        _fail("git_dirt_status_invalid", "Git status receipt must be bytes")
    if not status_bytes:
        return []
    fields = status_bytes.split(b"\0")
    if fields[-1] != b"":
        _fail("git_dirt_status_invalid", "NUL Git status is unterminated")
    fields.pop()
    parsed: list[tuple[bytes, str]] = []
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if len(record) < 4 or record[2:3] != b" ":
            _fail("git_dirt_status_invalid", "malformed porcelain v1 status")
        raw_status = record[:2]
        try:
            status_code = raw_status.decode("ascii")
        except UnicodeDecodeError:
            _fail("git_dirt_status_invalid", "non-ASCII Git status code")
        if any(value not in b" MADRCUT?!" for value in raw_status):
            _fail("git_dirt_status_invalid", f"invalid Git status: {raw_status!r}")
        raw_paths = [record[3:]]
        if b"R" in raw_status or b"C" in raw_status:
            if index >= len(fields):
                _fail("git_dirt_status_invalid", "rename/copy source path is missing")
            raw_paths.append(fields[index])
            index += 1
        for raw_path in raw_paths:
            _git_dirt_path(raw_path)
            parsed.append((raw_path, status_code))
    return parsed


def _missing_git_dirt_row(path: str, status_code: str) -> dict:
    return {
        "path": path,
        "status": status_code,
        "type": "missing",
        "mode": None,
        "size": None,
        "content_sha256": None,
    }


def _same_stat(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_mode,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_mode,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


def _git_dirt_row(
    root_fd: int,
    root: Path,
    raw_path: bytes,
    status_code: str,
) -> dict:
    parts = _git_dirt_path(raw_path)
    relative = os.fsdecode(raw_path)
    descriptor = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                return _missing_git_dirt_row(relative, status_code)
            except OSError as exc:
                _fail(
                    "git_dirt_path_unsafe",
                    f"cannot traverse Git dirt path {root / relative}: {exc}",
                    paths=(root / relative,),
                )
            os.close(descriptor)
            descriptor = child

        leaf = parts[-1]
        try:
            before = os.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return _missing_git_dirt_row(relative, status_code)
        except OSError as exc:
            _fail(
                "git_dirt_path_unsafe",
                f"cannot inspect Git dirt path {root / relative}: {exc}",
                paths=(root / relative,),
            )

        mode = stat.S_IMODE(before.st_mode)
        if stat.S_ISREG(before.st_mode):
            try:
                file_fd = os.open(
                    leaf,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            except OSError as exc:
                _fail(
                    "git_dirt_path_unsafe",
                    f"cannot open Git dirt path {root / relative}: {exc}",
                    paths=(root / relative,),
                )
            try:
                opened = os.fstat(file_fd)
                if not stat.S_ISREG(opened.st_mode) or not _same_stat(before, opened):
                    _fail(
                        "git_dirt_content_changed",
                        f"Git dirt path changed while opening: {root / relative}",
                        paths=(root / relative,),
                    )
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = os.read(file_fd, 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                after = os.fstat(file_fd)
                if not _same_stat(opened, after) or size != after.st_size:
                    _fail(
                        "git_dirt_content_changed",
                        f"Git dirt path changed while hashing: {root / relative}",
                        paths=(root / relative,),
                    )
            finally:
                os.close(file_fd)
            return {
                "path": relative,
                "status": status_code,
                "type": "regular",
                "mode": mode,
                "size": size,
                "content_sha256": digest.hexdigest(),
            }

        if stat.S_ISLNK(before.st_mode):
            try:
                target = os.readlink(leaf, dir_fd=descriptor)
                after = os.stat(leaf, dir_fd=descriptor, follow_symlinks=False)
            except OSError as exc:
                _fail(
                    "git_dirt_content_changed",
                    f"Git dirt symlink changed while reading: {root / relative}: {exc}",
                    paths=(root / relative,),
                )
            if not isinstance(target, bytes):
                target = os.fsencode(target)
            if not _same_stat(before, after):
                _fail(
                    "git_dirt_content_changed",
                    f"Git dirt symlink changed while reading: {root / relative}",
                    paths=(root / relative,),
                )
            return {
                "path": relative,
                "status": status_code,
                "type": "symlink",
                "mode": mode,
                "size": before.st_size,
                "content_sha256": hashlib.sha256(target).hexdigest(),
            }

        _fail(
            "git_dirt_path_unsafe",
            f"unsupported Git dirt path type: {root / relative}",
            paths=(root / relative,),
        )
    finally:
        os.close(descriptor)


def _git_dirt_manifest(
    root_fd: int,
    root: Path,
    status_bytes: bytes,
) -> tuple[bytes, int]:
    entries = _parse_git_status(status_bytes)
    rows = [
        _git_dirt_row(root_fd, root, raw_path, status_code)
        for raw_path, status_code in entries
    ]
    rows.sort(key=lambda row: (row["path"], row["status"]))
    manifest = (
        json.dumps(
            rows,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return manifest, len(rows)


def _git_root_still_bound(
    root_fd: int,
    root: Path,
    *,
    label: str,
) -> None:
    current_fd = _open_absolute_directory(root, create=False)
    try:
        pinned = os.fstat(root_fd)
        current = os.fstat(current_fd)
    except OSError as exc:
        _fail(
            "git_root_changed",
            f"{label} changed during Git verification: {exc}",
            paths=(root,),
        )
    finally:
        os.close(current_fd)
    if (pinned.st_dev, pinned.st_ino) != (current.st_dev, current.st_ino):
        _fail(
            "git_root_changed",
            f"{label} changed during Git receipt capture",
            paths=(root,),
        )


def _verify_git_state_stable(
    root_fd: int,
    root: Path,
    *,
    label: str,
    head: str,
    status_bytes: bytes,
) -> None:
    status_after = _git_status_bytes(root, label=label)
    head_after = _required_git_head(root, label=label)
    _git_root_still_bound(root_fd, root, label=label)
    if head_after != head:
        _fail(
            "git_head_changed",
            f"{label} HEAD changed during Git receipt capture",
            paths=(root,),
        )
    if status_after != status_bytes:
        _fail(
            "git_dirt_status_changed",
            f"{label} status changed during Git receipt capture",
            paths=(root,),
        )


def _capture_git_dirt(root: Path, *, label: str) -> GitDirtReceipt:
    root = Path(root)
    root_fd = _open_absolute_directory(root, create=False)
    try:
        head = _required_git_head(root, label=label)
        status_bytes = _git_status_bytes(root, label=label)
        content_manifest_bytes, entry_count = _git_dirt_manifest(
            root_fd,
            root,
            status_bytes,
        )
        verified_manifest_bytes, verified_entry_count = _git_dirt_manifest(
            root_fd,
            root,
            status_bytes,
        )
        _verify_git_state_stable(
            root_fd,
            root,
            label=label,
            head=head,
            status_bytes=status_bytes,
        )
        if (
            verified_entry_count != entry_count
            or verified_manifest_bytes != content_manifest_bytes
        ):
            _fail(
                "git_dirt_content_changed",
                f"{label} content changed during Git receipt capture",
                paths=(root,),
            )
    finally:
        os.close(root_fd)
    return GitDirtReceipt(
        root=str(root),
        head=head,
        status_bytes=status_bytes,
        status_sha256=hashlib.sha256(status_bytes).hexdigest(),
        entry_count=entry_count,
        content_manifest_bytes=content_manifest_bytes,
        content_manifest_sha256=hashlib.sha256(content_manifest_bytes).hexdigest(),
    )


def verify_git_root_clean(root: Path, *, label: str) -> GitWorktreeReceipt:
    """Return a receipt for one exact Git root, rejecting all visible dirt."""
    root = Path(root)
    root_fd = _open_absolute_directory(root, create=False)
    try:
        head = _required_git_head(root, label=label)
        status_bytes = _git_status_bytes(root, label=label)
        _verify_git_state_stable(
            root_fd,
            root,
            label=label,
            head=head,
            status_bytes=status_bytes,
        )
    finally:
        os.close(root_fd)
    if status_bytes:
        prefix = label.removesuffix("_root")
        _fail(
            f"{prefix}_worktree_dirty",
            f"{label} has tracked, staged, or untracked changes",
            paths=(root,),
        )
    return GitWorktreeReceipt(
        root=str(root),
        head=head,
        status_bytes=status_bytes,
        status_sha256=hashlib.sha256(status_bytes).hexdigest(),
    )


def capture_git_dirt_receipt(root: Path, *, label: str) -> GitDirtReceipt:
    """Capture raw Git status and no-follow content evidence for every path."""
    return _capture_git_dirt(root, label=label)


_GIT_DIRT_MANIFEST_KEYS = {
    "path",
    "status",
    "type",
    "mode",
    "size",
    "content_sha256",
}


def _validated_git_dirt_manifest(
    manifest_bytes: bytes,
    status_entries: list[tuple[bytes, str]],
) -> list[dict]:
    try:
        rows = json.loads(manifest_bytes)
    except (TypeError, UnicodeError, json.JSONDecodeError) as exc:
        _fail("git_dirt_receipt_invalid", f"invalid content manifest: {exc}")
    if not isinstance(rows, list):
        _fail("git_dirt_receipt_invalid", "content manifest must be an array")
    validated: list[dict] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != _GIT_DIRT_MANIFEST_KEYS:
            _fail("git_dirt_receipt_invalid", "content manifest row shape is invalid")
        path = row["path"]
        status_code = row["status"]
        entry_type = row["type"]
        if not isinstance(path, str):
            _fail("git_dirt_receipt_invalid", "content manifest path is invalid")
        _git_dirt_path(os.fsencode(path))
        if not isinstance(status_code, str) or len(status_code) != 2:
            _fail("git_dirt_receipt_invalid", f"invalid status for {path!r}")
        if entry_type not in {"regular", "symlink", "missing"}:
            _fail("git_dirt_receipt_invalid", f"invalid type for {path!r}")
        digest = row["content_sha256"]
        if entry_type == "missing":
            valid_metadata = (
                row["mode"] is None
                and row["size"] is None
                and digest is None
            )
        else:
            valid_metadata = (
                isinstance(row["mode"], int)
                and not isinstance(row["mode"], bool)
                and isinstance(row["size"], int)
                and not isinstance(row["size"], bool)
                and row["size"] >= 0
                and isinstance(digest, str)
                and _SHA256.fullmatch(digest) is not None
            )
        if not valid_metadata:
            _fail("git_dirt_receipt_invalid", f"invalid metadata for {path!r}")
        validated.append(row)
    expected_status = Counter(
        (os.fsdecode(raw_path), status_code)
        for raw_path, status_code in status_entries
    )
    actual_status = Counter(
        (row["path"], row["status"])
        for row in validated
    )
    if actual_status != expected_status:
        _fail("git_dirt_receipt_invalid", "status and content manifest disagree")
    canonical = (
        json.dumps(
            sorted(rows, key=lambda row: (row["path"], row["status"])),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    if canonical != manifest_bytes:
        _fail("git_dirt_receipt_invalid", "content manifest is not canonical")
    return validated


def _git_dirt_row_key(row: dict) -> tuple:
    return (
        row["path"],
        row["status"],
        row["type"],
        row["mode"],
        row["size"],
        row["content_sha256"],
    )


def verify_git_dirt_preserved(
    root: Path,
    *,
    baseline_status_bytes: bytes,
    baseline_content_manifest_bytes: bytes,
    label: str,
    allowed_extra_paths: Collection[str] = (),
) -> GitDirtReceipt:
    """Verify baseline dirt bytes while permitting only named new status paths."""
    baseline_entries = _parse_git_status(baseline_status_bytes)
    baseline_rows = _validated_git_dirt_manifest(
        baseline_content_manifest_bytes,
        baseline_entries,
    )
    allowed: set[str] = set()
    for value in allowed_extra_paths:
        if not isinstance(value, str):
            _fail("git_dirt_path_unsafe", "allowlisted path must be text")
        _git_dirt_path(os.fsencode(value))
        allowed.add(value)

    current = _capture_git_dirt(Path(root), label=label)
    current_entries = _parse_git_status(current.status_bytes)
    current_status = Counter(
        (os.fsdecode(raw_path), status_code)
        for raw_path, status_code in current_entries
    )
    baseline_status = Counter(
        (os.fsdecode(raw_path), status_code)
        for raw_path, status_code in baseline_entries
    )
    baseline_paths = {path for path, _ in baseline_status}
    for occurrence, count in baseline_status.items():
        if current_status[occurrence] < count:
            path, _ = occurrence
            _fail(
                "git_dirt_status_changed",
                f"{label} baseline status changed for {path!r}",
                paths=(Path(root) / path,),
            )
    added_status = current_status - baseline_status
    changed_baseline_paths = {
        path for path, _ in added_status if path in baseline_paths
    }
    if changed_baseline_paths:
        path = sorted(changed_baseline_paths)[0]
        _fail(
            "git_dirt_status_changed",
            f"{label} baseline status changed for {path!r}",
            paths=(Path(root) / path,),
        )
    unexpected = {
        path for path, _ in added_status
        if path not in allowed
    }
    if unexpected:
        _fail(
            "git_dirt_unexpected_path",
            f"{label} has unexpected dirt paths: {sorted(unexpected)!r}",
            paths=tuple(Path(root) / value for value in sorted(unexpected)),
        )
    current_rows = json.loads(current.content_manifest_bytes)
    baseline_content = Counter(_git_dirt_row_key(row) for row in baseline_rows)
    current_content = Counter(_git_dirt_row_key(row) for row in current_rows)
    for row_key, count in baseline_content.items():
        if current_content[row_key] < count:
            path = row_key[0]
            _fail(
                "git_dirt_content_changed",
                f"{label} baseline content changed for {path!r}",
                paths=(Path(root) / path,),
            )
    return current


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
        repo_head_before = _required_git_head(request.repo_root, label="repo_root")
        engine_head_before = _required_git_head(
            request.engine_root,
            label="engine_root",
        )
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
        repo_head_after = _required_git_head(request.repo_root, label="repo_root")
        engine_head_after = _required_git_head(
            request.engine_root,
            label="engine_root",
        )
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
            not isinstance(manifest["repo_head"], str)
            or _GIT_SHA.fullmatch(manifest["repo_head"]) is None
        )
        or (
            not isinstance(manifest["engine_head"], str)
            or _GIT_SHA.fullmatch(manifest["engine_head"]) is None
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
        repo_head=manifest["repo_head"],
        engine_head=manifest["engine_head"],
        corpus_fingerprint=manifest["corpus"]["fingerprint"],
    )


def _copy_tree_no_symlinks(
    source: Path,
    destination: Path,
    *,
    destination_exists: bool = False,
) -> None:
    directories, files = _scan_tree(source, unsafe_code="restore_live_tree_unsafe")
    if not destination_exists:
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
    """Rename non-recovery snapshot build paths."""
    os.rename(source, destination)


def _rename_entry(
    source_parent_fd: int,
    source_name: str,
    destination_parent_fd: int,
    destination_name: str,
) -> None:
    """Test seam for one verified directory-FD-relative rename."""
    os.rename(
        source_name,
        destination_name,
        src_dir_fd=source_parent_fd,
        dst_dir_fd=destination_parent_fd,
    )


def _restore_state_root(brain_root: Path) -> Path:
    from project_brain.corpus_io import restore_state_root

    return restore_state_root(brain_root)


def _fsync_directory(path: Path) -> None:
    descriptor = _open_absolute_directory(path, create=False)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _entry_kind(mode: int) -> str:
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "regular"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    return "other"


def _binding(file_stat: os.stat_result) -> dict:
    return {
        "type": _entry_kind(file_stat.st_mode),
        "device": file_stat.st_dev,
        "inode": file_stat.st_ino,
    }


def _binding_valid(value: object, *, expected_type: str) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"type", "device", "inode"}
        and value["type"] == expected_type
        and type(value["device"]) is int
        and value["device"] >= 0
        and type(value["inode"]) is int
        and value["inode"] > 0
    )


def _stat_entry(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _open_bound_entry(
    parent_fd: int,
    name: str,
    expected: dict,
    *,
    expected_type: str,
    paths: tuple[Path, ...],
) -> int:
    observed = _stat_entry(parent_fd, name)
    if observed is None or _binding(observed) != expected:
        _fail(
            "recovery_required",
            f"restore artifact binding changed: {name}",
            paths=paths,
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if expected_type == "directory":
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        _fail(
            "recovery_required",
            f"cannot open bound restore artifact {name}: {exc}",
            paths=paths,
        )
    if _binding(os.fstat(descriptor)) != expected:
        os.close(descriptor)
        _fail(
            "recovery_required",
            f"restore artifact changed while opening: {name}",
            paths=paths,
        )
    return descriptor


def _read_descriptor(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        view = view[written:]


def _append_phase(phase_fd: int, phase: str) -> None:
    record = phase.encode("ascii")
    if record not in _PHASE_RECORDS:
        raise ValueError(f"unsupported restore phase: {phase}")
    os.lseek(phase_fd, 0, os.SEEK_END)
    _write_all(phase_fd, record + b"\n")
    os.fsync(phase_fd)


def _read_phases(
    phase_fd: int,
    *,
    expected_binding: dict,
    paths: tuple[Path, ...],
) -> tuple[bytes, ...]:
    before = os.fstat(phase_fd)
    if (
        not stat.S_ISREG(before.st_mode)
        or _binding(before) != expected_binding
        or not 1 <= before.st_size <= _PHASE_LOG_MAX_BYTES
    ):
        _fail(
            "recovery_required",
            "restore phase log size or binding is invalid",
            paths=paths,
        )
    os.lseek(phase_fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    bytes_read = 0
    interrupted_retries = 0
    read_limit = _PHASE_LOG_MAX_BYTES + 1
    while bytes_read < read_limit:
        try:
            chunk = os.read(phase_fd, read_limit - bytes_read)
        except InterruptedError:
            interrupted_retries += 1
            if interrupted_retries > _PHASE_READ_EINTR_RETRY_LIMIT:
                _fail(
                    "recovery_required",
                    "restore phase log read exceeded the EINTR retry limit",
                    paths=paths,
                )
            continue
        except OSError as exc:
            if exc.errno == errno.EINTR:
                interrupted_retries += 1
                if interrupted_retries <= _PHASE_READ_EINTR_RETRY_LIMIT:
                    continue
                _fail(
                    "recovery_required",
                    "restore phase log read exceeded the EINTR retry limit",
                    paths=paths,
                )
            _fail(
                "recovery_required",
                f"restore phase log read failed: {exc}",
                paths=paths,
            )
        if not chunk:
            break
        chunks.append(chunk)
        bytes_read += len(chunk)
    payload = b"".join(chunks)
    after = os.fstat(phase_fd)
    if (
        bytes_read > _PHASE_LOG_MAX_BYTES
        or bytes_read != before.st_size
        or _binding(after) != expected_binding
        or (
            _entry_kind(after.st_mode),
            after.st_dev,
            after.st_ino,
            after.st_size,
        )
        != (
            _entry_kind(before.st_mode),
            before.st_dev,
            before.st_ino,
            before.st_size,
        )
    ):
        _fail(
            "recovery_required",
            "restore phase log changed while reading",
            paths=paths,
        )
    if not payload.endswith(b"\n"):
        _fail(
            "recovery_required",
            "restore phase log has a torn final record",
            paths=paths,
        )
    records = payload.split(b"\n")
    if records[-1] != b"":
        raise AssertionError("LF-terminated split must have one trailing empty record")
    records = records[:-1]
    if not records or tuple(records) != _PHASE_RECORDS[:len(records)]:
        _fail("recovery_required", "restore phase sequence is invalid", paths=paths)
    return tuple(records)


def _create_restore_journal(
    *,
    parent_fd: int,
    state_fd: int,
    workspace_fd: int,
    staged_fd: int,
    brain_fd: int,
    state_root: Path,
    snapshot_root: Path,
    brain_root: Path,
    expected_manifest_sha256: str,
) -> tuple[int, dict]:
    journal_fd = os.open(
        "journal.json",
        os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=state_fd,
    )
    try:
        phase_fd = os.open(
            "phases.log",
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=state_fd,
        )
    except Exception:
        os.close(journal_fd)
        raise
    bindings = {
        "parent": _binding(os.fstat(parent_fd)),
        "state_root": _binding(os.fstat(state_fd)),
        "workspace": _binding(os.fstat(workspace_fd)),
        "staged": _binding(os.fstat(staged_fd)),
        "backup": _binding(os.fstat(brain_fd)),
        "journal": _binding(os.fstat(journal_fd)),
        "phases": _binding(os.fstat(phase_fd)),
    }
    journal = {
        "version": 2,
        "snapshot_root": str(snapshot_root),
        "brain_root": str(brain_root),
        "expected_manifest_sha256": expected_manifest_sha256,
        "workspace": str(state_root / "workspace"),
        "bindings": bindings,
    }
    try:
        _write_all(journal_fd, _manifest_bytes(journal))
        os.fsync(journal_fd)
        _append_phase(phase_fd, "preparing")
        os.fsync(workspace_fd)
        os.fsync(state_fd)
        os.fsync(parent_fd)
    finally:
        os.close(journal_fd)
    return phase_fd, journal


def _remove_tree_at(parent_fd: int, name: str) -> None:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        dir_fd=parent_fd,
    )
    try:
        for child in sorted(os.listdir(descriptor)):
            child_stat = os.stat(child, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISDIR(child_stat.st_mode) and not stat.S_ISLNK(
                child_stat.st_mode
            ):
                _remove_tree_at(descriptor, child)
            else:
                os.unlink(child, dir_fd=descriptor)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.rmdir(name, dir_fd=parent_fd)


def _remove_restore_state_at(
    parent_fd: int,
    *,
    state_name: str,
    expected_state_binding: dict,
    paths: tuple[Path, ...],
) -> None:
    observed = _stat_entry(parent_fd, state_name)
    if observed is None or _binding(observed) != expected_state_binding:
        _fail(
            "recovery_required",
            "restore state root changed before cleanup",
            paths=paths,
        )
    tombstone = f"{state_name}.cleanup-{uuid.uuid4().hex}"
    _rename_entry(parent_fd, state_name, parent_fd, tombstone)
    moved = _stat_entry(parent_fd, tombstone)
    if moved is None or _binding(moved) != expected_state_binding:
        _fail(
            "recovery_required",
            "restore state root binding changed during cleanup",
            paths=paths,
        )
    os.fsync(parent_fd)
    _remove_tree_at(parent_fd, tombstone)
    os.fsync(parent_fd)


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


def _recover_restore(
    *,
    parent_fd: int,
    snapshot_root: Path,
    brain_root: Path,
    expected_manifest_sha256: str,
    manifest: dict,
) -> None:
    state_root = _restore_state_root(brain_root)
    state_name = state_root.name
    workspace = state_root / "workspace"
    staged = workspace / "staged"
    backup = workspace / "backup"
    journal_path = state_root / "journal.json"
    evidence_paths = (state_root, workspace, backup, staged, journal_path)
    state_stat = _stat_entry(parent_fd, state_name)
    if state_stat is None:
        return
    if not stat.S_ISDIR(state_stat.st_mode) or stat.S_ISLNK(state_stat.st_mode):
        _fail(
            "recovery_required",
            "restore state root type changed",
            paths=evidence_paths,
        )
    try:
        state_fd = os.open(
            state_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        _fail(
            "recovery_required",
            f"cannot open restore state root: {exc}",
            paths=evidence_paths,
        )
    descriptors = [state_fd]
    cleanup = False
    try:
        journal_stat = _stat_entry(state_fd, "journal.json")
        if (
            journal_stat is None
            or not stat.S_ISREG(journal_stat.st_mode)
            or stat.S_ISLNK(journal_stat.st_mode)
        ):
            _fail(
                "recovery_required",
                "restore journal is missing or has the wrong type",
                paths=evidence_paths,
            )
        journal_fd = os.open(
            "journal.json",
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=state_fd,
        )
        descriptors.append(journal_fd)
        try:
            journal = json.loads(_read_descriptor(journal_fd))
        except (UnicodeError, json.JSONDecodeError) as exc:
            _fail(
                "recovery_required",
                f"restore journal is invalid: {exc}",
                paths=evidence_paths,
            )
        required = {
            "version",
            "snapshot_root",
            "brain_root",
            "expected_manifest_sha256",
            "workspace",
            "bindings",
        }
        if (
            not isinstance(journal, dict)
            or set(journal) != required
            or journal["version"] != 2
            or journal["snapshot_root"] != str(snapshot_root)
            or journal["brain_root"] != str(brain_root)
            or journal["expected_manifest_sha256"] != expected_manifest_sha256
            or journal["workspace"] != str(workspace)
            or not isinstance(journal["bindings"], dict)
        ):
            _fail(
                "recovery_required",
                "restore journal does not match this trusted request",
                paths=evidence_paths,
            )
        bindings = journal["bindings"]
        binding_types = {
            "parent": "directory",
            "state_root": "directory",
            "workspace": "directory",
            "staged": "directory",
            "backup": "directory",
            "journal": "regular",
            "phases": "regular",
        }
        if (
            set(bindings) != set(binding_types)
            or any(
                not _binding_valid(bindings[name], expected_type=expected_type)
                for name, expected_type in binding_types.items()
            )
            or _binding(os.fstat(parent_fd)) != bindings["parent"]
            or _binding(os.fstat(state_fd)) != bindings["state_root"]
            or _binding(os.fstat(journal_fd)) != bindings["journal"]
            or any(
                value["device"] != bindings["parent"]["device"]
                for value in bindings.values()
            )
        ):
            _fail(
                "recovery_required",
                "restore journal artifact bindings are invalid",
                paths=evidence_paths,
            )
        workspace_fd = _open_bound_entry(
            state_fd,
            "workspace",
            bindings["workspace"],
            expected_type="directory",
            paths=evidence_paths,
        )
        descriptors.append(workspace_fd)
        phase_fd = _open_bound_entry(
            state_fd,
            "phases.log",
            bindings["phases"],
            expected_type="regular",
            paths=evidence_paths,
        )
        descriptors.append(phase_fd)
        phases = _read_phases(
            phase_fd,
            expected_binding=bindings["phases"],
            paths=evidence_paths,
        )
        reopened_phase_fd = _open_bound_entry(
            state_fd,
            "phases.log",
            bindings["phases"],
            expected_type="regular",
            paths=evidence_paths,
        )
        descriptors.append(reopened_phase_fd)

        if set(os.listdir(state_fd)) != {
            "workspace",
            "journal.json",
            "phases.log",
        }:
            _fail(
                "recovery_required",
                "restore state root has unexpected entries",
                paths=evidence_paths,
            )
        workspace_entries = set(os.listdir(workspace_fd))
        if not workspace_entries <= {"backup", "staged"}:
            _fail(
                "recovery_required",
                "restore workspace has unexpected entries",
                paths=evidence_paths,
            )

        root_stat = _stat_entry(parent_fd, brain_root.name)
        backup_stat = _stat_entry(workspace_fd, "backup")
        staged_stat = _stat_entry(workspace_fd, "staged")
        root_binding = _binding(root_stat) if root_stat is not None else None
        backup_binding = _binding(backup_stat) if backup_stat is not None else None
        staged_binding = _binding(staged_stat) if staged_stat is not None else None
        if root_binding not in (
            None,
            bindings["backup"],
            bindings["staged"],
        ):
            _fail(
                "recovery_required",
                "live brain root binding changed",
                paths=evidence_paths,
            )
        if backup_binding not in (None, bindings["backup"]):
            _fail(
                "recovery_required",
                "backup binding changed",
                paths=evidence_paths,
            )
        if staged_binding not in (None, bindings["staged"]):
            _fail(
                "recovery_required",
                "staged binding changed",
                paths=evidence_paths,
            )
        backup_locations = sum((
            root_binding == bindings["backup"],
            backup_binding == bindings["backup"],
        ))
        staged_locations = sum((
            root_binding == bindings["staged"],
            staged_binding == bindings["staged"],
        ))
        if backup_locations != 1 or staged_locations != 1:
            _fail(
                "recovery_required",
                "restore artifact is missing or duplicated",
                paths=evidence_paths,
            )

        if root_binding == bindings["backup"]:
            if backup_binding is not None or staged_binding != bindings["staged"]:
                _fail(
                    "recovery_required",
                    "restore artifact locations are inconsistent",
                    paths=evidence_paths,
                )
            cleanup = True
        elif root_binding is None:
            if (
                backup_binding != bindings["backup"]
                or staged_binding != bindings["staged"]
            ):
                _fail(
                    "recovery_required",
                    "interrupted restore artifacts are incomplete",
                    paths=evidence_paths,
                )
            backup_fd = _open_bound_entry(
                workspace_fd,
                "backup",
                bindings["backup"],
                expected_type="directory",
                paths=evidence_paths,
            )
            staged_fd = _open_bound_entry(
                workspace_fd,
                "staged",
                bindings["staged"],
                expected_type="directory",
                paths=evidence_paths,
            )
            descriptors.extend((backup_fd, staged_fd))
            try:
                _rename_entry(
                    workspace_fd,
                    "backup",
                    parent_fd,
                    brain_root.name,
                )
                os.fsync(workspace_fd)
                os.fsync(parent_fd)
            except Exception as exc:
                _fail(
                    "recovery_required",
                    f"could not roll back interrupted restore: {exc}",
                    paths=evidence_paths,
                )
            restored_fd = _open_bound_entry(
                parent_fd,
                brain_root.name,
                bindings["backup"],
                expected_type="directory",
                paths=evidence_paths,
            )
            descriptors.append(restored_fd)
            cleanup = True
        else:
            if (
                root_binding != bindings["staged"]
                or backup_binding != bindings["backup"]
                or staged_binding is not None
                or phases[-1] not in {b"moved_live", b"activated"}
            ):
                _fail(
                    "recovery_required",
                    "activated restore artifacts are inconsistent",
                    paths=evidence_paths,
                )
            live_fd = _open_bound_entry(
                parent_fd,
                brain_root.name,
                bindings["staged"],
                expected_type="directory",
                paths=evidence_paths,
            )
            descriptors.append(live_fd)
            expected = _expected_brain_inventory(manifest)
            if _brain_snapshot_inventory(brain_root, manifest) != expected:
                _fail(
                    "recovery_required",
                    "activated corpus does not match the trusted snapshot",
                    paths=evidence_paths,
                )
            reopened_fd = _open_bound_entry(
                parent_fd,
                brain_root.name,
                bindings["staged"],
                expected_type="directory",
                paths=evidence_paths,
            )
            descriptors.append(reopened_fd)
            cleanup = True
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    if cleanup:
        _remove_restore_state_at(
            parent_fd,
            state_name=state_name,
            expected_state_binding=journal["bindings"]["state_root"],
            paths=evidence_paths,
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
            parent_fd = _open_absolute_directory(brain_root.parent, create=False)
            try:
                _recover_restore(
                    parent_fd=parent_fd,
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
                    parent_fd=parent_fd,
                    expected_manifest_sha256=expected_manifest_sha256,
                    verification=verification,
                    manifest=manifest,
                )
            finally:
                os.close(parent_fd)
    except SnapshotError:
        raise
    except CorpusIOError as exc:
        _fail("restore_lock_failed", str(exc), paths=getattr(exc, "paths", ()))


def _restore_snapshot_locked(
    snapshot_root: Path,
    brain_root: Path,
    *,
    parent_fd: int,
    expected_manifest_sha256: str,
    verification: SnapshotVerification,
    manifest: dict,
) -> RestoreResult:
    state_root = _restore_state_root(brain_root)
    state_name = state_root.name
    workspace = state_root / "workspace"
    staged = workspace / "staged"
    backup = workspace / "backup"
    evidence_paths = (
        state_root,
        workspace,
        backup,
        staged,
        state_root / "journal.json",
    )
    descriptors: list[int] = []
    journal_created = False

    root_stat = _stat_entry(parent_fd, brain_root.name)
    if (
        root_stat is None
        or not stat.S_ISDIR(root_stat.st_mode)
        or stat.S_ISLNK(root_stat.st_mode)
        or root_stat.st_dev != os.fstat(parent_fd).st_dev
    ):
        _fail("restore_live_root_invalid", f"unsafe brain_root: {brain_root}")
    if _stat_entry(parent_fd, state_name) is not None:
        _fail(
            "recovery_required",
            "restore state root was not cleared before a new restore",
            paths=evidence_paths,
        )
    try:
        brain_fd = os.open(
            brain_root.name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        descriptors.append(brain_fd)
        backup_binding = _binding(os.fstat(brain_fd))
        if backup_binding != _binding(root_stat):
            _fail("restore_live_root_invalid", "brain_root changed while opening")

        os.mkdir(state_name, 0o700, dir_fd=parent_fd)
        os.fsync(parent_fd)
        state_fd = os.open(
            state_name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        descriptors.append(state_fd)
        os.mkdir("workspace", 0o700, dir_fd=state_fd)
        os.fsync(state_fd)
        workspace_fd = os.open(
            "workspace",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=state_fd,
        )
        descriptors.append(workspace_fd)
        os.mkdir("staged", 0o700, dir_fd=workspace_fd)
        os.fsync(workspace_fd)
        staged_fd = os.open(
            "staged",
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=workspace_fd,
        )
        descriptors.append(staged_fd)
        phase_fd, journal = _create_restore_journal(
            parent_fd=parent_fd,
            state_fd=state_fd,
            workspace_fd=workspace_fd,
            staged_fd=staged_fd,
            brain_fd=brain_fd,
            state_root=state_root,
            snapshot_root=snapshot_root,
            brain_root=brain_root,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        descriptors.append(phase_fd)
        journal_created = True
        bindings = journal["bindings"]

        _copy_tree_no_symlinks(
            brain_root,
            staged,
            destination_exists=True,
        )
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
        rebound_staged_fd = _open_bound_entry(
            workspace_fd,
            "staged",
            bindings["staged"],
            expected_type="directory",
            paths=evidence_paths,
        )
        descriptors.append(rebound_staged_fd)
        _append_phase(phase_fd, "prepared")
        os.fsync(state_fd)

        _rename_entry(
            parent_fd,
            brain_root.name,
            workspace_fd,
            "backup",
        )
        os.fsync(parent_fd)
        os.fsync(workspace_fd)
        rebound_backup_fd = _open_bound_entry(
            workspace_fd,
            "backup",
            bindings["backup"],
            expected_type="directory",
            paths=evidence_paths,
        )
        descriptors.append(rebound_backup_fd)
        _append_phase(phase_fd, "moved_live")
        os.fsync(state_fd)
        try:
            _rename_entry(
                workspace_fd,
                "staged",
                parent_fd,
                brain_root.name,
            )
            os.fsync(workspace_fd)
            os.fsync(parent_fd)
        except Exception as activation_exc:
            try:
                verified_backup_fd = _open_bound_entry(
                    workspace_fd,
                    "backup",
                    bindings["backup"],
                    expected_type="directory",
                    paths=evidence_paths,
                )
                descriptors.append(verified_backup_fd)
                _rename_entry(
                    workspace_fd,
                    "backup",
                    parent_fd,
                    brain_root.name,
                )
                os.fsync(workspace_fd)
                os.fsync(parent_fd)
                restored_fd = _open_bound_entry(
                    parent_fd,
                    brain_root.name,
                    bindings["backup"],
                    expected_type="directory",
                    paths=evidence_paths,
                )
                descriptors.append(restored_fd)
            except Exception as rollback_exc:
                _fail(
                    "recovery_required",
                    (
                        f"activation failed: {activation_exc}; "
                        f"rollback failed: {rollback_exc}"
                    ),
                    paths=(state_root, workspace, backup, staged),
                )
            for descriptor in reversed(descriptors):
                os.close(descriptor)
            descriptors.clear()
            _remove_restore_state_at(
                parent_fd,
                state_name=state_name,
                expected_state_binding=bindings["state_root"],
                paths=evidence_paths,
            )
            _fail("restore_activation_failed", str(activation_exc))

        activated_fd = _open_bound_entry(
            parent_fd,
            brain_root.name,
            bindings["staged"],
            expected_type="directory",
            paths=evidence_paths,
        )
        descriptors.append(activated_fd)
        _append_phase(phase_fd, "activated")
        os.fsync(state_fd)
        if _brain_snapshot_inventory(brain_root, manifest) != expected_inventory:
            _fail(
                "recovery_required",
                "activated corpus does not match snapshot",
                paths=(state_root, workspace, backup, brain_root),
            )
        reopened_activated_fd = _open_bound_entry(
            parent_fd,
            brain_root.name,
            bindings["staged"],
            expected_type="directory",
            paths=evidence_paths,
        )
        descriptors.append(reopened_activated_fd)
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        descriptors.clear()
        _remove_restore_state_at(
            parent_fd,
            state_name=state_name,
            expected_state_binding=bindings["state_root"],
            paths=evidence_paths,
        )
        return RestoreResult(
            snapshot_id=verification.snapshot_id,
            brain_root=brain_root,
            restored_files=tuple(sorted(expected_inventory)),
        )
    except SnapshotError:
        raise
    except Exception as exc:
        if journal_created:
            _fail(
                "recovery_required",
                str(exc),
                paths=(state_root, workspace, backup, staged),
            )
        _fail("restore_failed", str(exc))
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
