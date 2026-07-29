"""Corpus-wide lock, durable journal, and rollback-only recovery."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any


class JournalState(StrEnum):
    PREPARING = "preparing"
    PREPARED = "prepared"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True)
class RecoveryResult:
    recovered_transaction_ids: tuple[str, ...] = ()


class RecoveryRequiredError(RuntimeError):
    def __init__(
        self,
        detail: str,
        *,
        transaction_ids: tuple[str, ...] = (),
    ):
        self.detail = detail
        self.transaction_ids = transaction_ids
        super().__init__(detail)


class CorpusIOError(RuntimeError):
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


_TERMINAL_STATES = {
    JournalState.COMMITTED.value,
    JournalState.ROLLED_BACK.value,
}
_DERIVED_PATHS = (
    ".brain-local/index.db",
    ".brain-local/index.db-wal",
    ".brain-local/index.db-shm",
    ".brain-local/index.db-journal",
    ".brain-local/stale-set.json",
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_MUTATION_OPERATIONS = {
    "ingest",
    "promote",
    "promote_auto",
    "mark_checked",
    "projection",
    "projection_repair",
    "context_replace",
    "id_only_migration",
    "display_migration",
}


@dataclass(frozen=True)
class _PinnedDirectory:
    relative_path: str
    fd: int
    device: int
    inode: int


def _observed_device(relative_path: str, actual_device: int) -> int:
    """Return an fstat-derived device through a deterministic test seam."""
    return actual_device


class _AnchoredRoot:
    """One no-follow root FD plus transaction-lifetime directory pins."""

    def __init__(self, brain_root: Path):
        self.path = Path(brain_root)
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            self.root_fd = os.open(self.path, flags)
        except OSError as exc:
            raise CorpusIOError(
                "brain_root_unavailable",
                f"cannot pin brain_root without following symlinks: {exc}",
                paths=(self.path,),
            ) from exc
        root_stat = os.fstat(self.root_fd)
        self.device = root_stat.st_dev
        self.inode = root_stat.st_ino
        self._fds: list[int] = []
        self._bound_prefixes: dict[str, _PinnedDirectory] = {}

    def close(self) -> None:
        for descriptor in reversed(self._fds):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self._fds.clear()
        os.close(self.root_fd)

    def __enter__(self) -> "_AnchoredRoot":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def pin_directory(
        self,
        relative_path: str,
        *,
        create: bool,
    ) -> _PinnedDirectory:
        normalized = _validated_directory_path(relative_path)
        prefix = self._bound_prefix(normalized)
        if prefix is None:
            descriptor = os.dup(self.root_fd)
            traversed: list[str] = []
            remaining_parts = PurePosixPath(normalized).parts
        else:
            descriptor = os.dup(prefix.fd)
            traversed = list(PurePosixPath(prefix.relative_path).parts)
            all_parts = PurePosixPath(normalized).parts
            remaining_parts = all_parts[len(traversed):]
        for part in remaining_parts:
            try:
                next_descriptor = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                if not create:
                    os.close(descriptor)
                    raise
                try:
                    os.mkdir(part, 0o755, dir_fd=descriptor)
                except FileExistsError:
                    pass
                os.fsync(descriptor)
                next_descriptor = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
                os.fsync(next_descriptor)
            except OSError as exc:
                os.close(descriptor)
                raise _anchored_path_error(
                    self.path / normalized,
                    exc,
                ) from exc
            os.close(descriptor)
            descriptor = next_descriptor
            traversed.append(part)
            current_relative = PurePosixPath(*traversed).as_posix()
            directory_device = _observed_device(
                current_relative,
                os.fstat(descriptor).st_dev,
            )
            if directory_device != self.device:
                os.close(descriptor)
                raise CorpusIOError(
                    "filesystem_mismatch",
                    f"{relative_path}: directory crosses filesystem boundary",
                    paths=(self.path / normalized,),
                )
        file_stat = os.fstat(descriptor)
        self._fds.append(descriptor)
        return _PinnedDirectory(
            normalized,
            descriptor,
            file_stat.st_dev,
            file_stat.st_ino,
        )

    def bind_prefix(
        self,
        relative_path: str,
        pinned: _PinnedDirectory,
    ) -> None:
        normalized = _validated_directory_path(relative_path)
        if pinned.relative_path != normalized:
            raise ValueError("pinned prefix path mismatch")
        self._bound_prefixes[normalized] = pinned

    def _bound_prefix(
        self,
        relative_path: str,
    ) -> _PinnedDirectory | None:
        candidates = [
            pinned
            for prefix, pinned in self._bound_prefixes.items()
            if relative_path == prefix
            or relative_path.startswith(prefix + "/")
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: len(item.relative_path))

    def pin_existing_parent(
        self,
        relative_file: str,
        *,
        create: bool,
    ) -> tuple[_PinnedDirectory, str]:
        relative_file = _validated_relative_path(relative_file)
        path = PurePosixPath(relative_file)
        parent = path.parent.as_posix()
        if parent == ".":
            parent = ""
        return self.pin_directory(parent, create=create), path.name

    def verify_binding(self, pinned: _PinnedDirectory) -> None:
        try:
            current = self.pin_directory(
                pinned.relative_path,
                create=False,
            )
        except (FileNotFoundError, CorpusIOError, OSError) as exc:
            raise CorpusIOError(
                "path_binding_changed",
                (
                    f"{pinned.relative_path}: pinned directory can no longer "
                    "be reached without following symlinks"
                ),
                paths=(self.path / pinned.relative_path,),
            ) from exc
        if (current.device, current.inode) != (
            pinned.device,
            pinned.inode,
        ):
            raise CorpusIOError(
                "path_binding_changed",
                f"{pinned.relative_path}: directory binding changed",
                paths=(self.path / pinned.relative_path,),
            )

    def inspect_file(self, relative_file: str) -> dict[str, object]:
        relative_file = _validated_relative_path(relative_file)
        path = PurePosixPath(relative_file)
        parent_parts = path.parent.parts
        descriptor = os.dup(self.root_fd)
        traversed: list[str] = []
        try:
            for part in parent_parts:
                if part == ".":
                    continue
                try:
                    next_descriptor = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                except FileNotFoundError:
                    return {
                        "path": relative_file,
                        "had_before": False,
                        "before_sha256": None,
                    }
                except OSError as exc:
                    raise _anchored_path_error(
                        self.path / relative_file,
                        exc,
                    ) from exc
                os.close(descriptor)
                descriptor = next_descriptor
                traversed.append(part)
                current_relative = PurePosixPath(*traversed).as_posix()
                directory_device = _observed_device(
                    current_relative,
                    os.fstat(descriptor).st_dev,
                )
                if directory_device != self.device:
                    raise CorpusIOError(
                        "filesystem_mismatch",
                        f"{relative_file}: parent is on another filesystem",
                        paths=(self.path / relative_file,),
                    )
            try:
                file_stat = os.stat(
                    path.name,
                    dir_fd=descriptor,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return {
                    "path": relative_file,
                    "had_before": False,
                    "before_sha256": None,
                }
            if stat.S_ISLNK(file_stat.st_mode):
                raise CorpusIOError(
                    "symlink_forbidden",
                    f"{relative_file}: live file is a symlink",
                    paths=(self.path / relative_file,),
                )
            if not stat.S_ISREG(file_stat.st_mode):
                raise CorpusIOError(
                    "file_type_invalid",
                    f"{relative_file}: live entry is not a regular file",
                    paths=(self.path / relative_file,),
                )
            file_device = _observed_device(
                relative_file,
                file_stat.st_dev,
            )
            if file_device != self.device:
                raise CorpusIOError(
                    "filesystem_mismatch",
                    f"{relative_file}: live file is on another filesystem",
                    paths=(self.path / relative_file,),
                )
            return {
                "path": relative_file,
                "had_before": True,
                "before_sha256": _sha256_at(descriptor, path.name),
            }
        finally:
            os.close(descriptor)


@dataclass(frozen=True)
class _CorpusLockScope:
    brain_root_identity: str
    anchored: _AnchoredRoot
    local_root: _PinnedDirectory
    exclusive: bool

    def verify_lexical_bindings(self) -> None:
        try:
            descriptor = os.open(
                self.brain_root_identity,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
        except OSError as exc:
            raise CorpusIOError(
                "path_binding_changed",
                "brain_root lexical binding changed while locked",
                paths=(Path(self.brain_root_identity),),
            ) from exc
        try:
            current = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        if (current.st_dev, current.st_ino) != (
            self.anchored.device,
            self.anchored.inode,
        ):
            raise CorpusIOError(
                "path_binding_changed",
                "brain_root lexical binding changed while locked",
                paths=(Path(self.brain_root_identity),),
            )
        try:
            local_descriptor = os.open(
                ".brain-local",
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=self.anchored.root_fd,
            )
        except OSError as exc:
            raise CorpusIOError(
                "path_binding_changed",
                ".brain-local lexical binding changed while locked",
                paths=(
                    Path(self.brain_root_identity) / ".brain-local",
                ),
            ) from exc
        try:
            current_local = os.fstat(local_descriptor)
        finally:
            os.close(local_descriptor)
        if (current_local.st_dev, current_local.st_ino) != (
            self.local_root.device,
            self.local_root.inode,
        ):
            raise CorpusIOError(
                "path_binding_changed",
                ".brain-local lexical binding changed while locked",
                paths=(
                    Path(self.brain_root_identity) / ".brain-local",
                ),
            )


_CORPUS_LOCK_SCOPE: ContextVar[_CorpusLockScope | None] = ContextVar(
    "project_brain_corpus_lock_scope",
    default=None,
)


@dataclass(frozen=True)
class _StableCorpusLockScope:
    brain_root_identity: str
    exclusive: bool


_STABLE_CORPUS_LOCK_SCOPE: ContextVar[_StableCorpusLockScope | None] = ContextVar(
    "project_brain_stable_corpus_lock_scope",
    default=None,
)


def _brain_root_identity(brain_root: Path) -> str:
    return os.path.abspath(os.fspath(Path(brain_root)))


def restore_state_root(brain_root: Path) -> Path:
    """Return the stable sibling state directory used by snapshot restore."""
    identity = Path(_brain_root_identity(brain_root))
    return identity.parent / f".{identity.name}.project-brain-restore"


def _stable_lock_name(brain_root: Path) -> str:
    identity = Path(_brain_root_identity(brain_root))
    return f".{identity.name}.project-brain-corpus.lock"


@contextmanager
def stable_corpus_lock(
    brain_root: Path,
    *,
    exclusive: bool,
) -> Iterator[None]:
    """Lock a path outside the swappable corpus-root inode."""
    identity = _brain_root_identity(brain_root)
    active = _STABLE_CORPUS_LOCK_SCOPE.get()
    if active is not None:
        if active.brain_root_identity != identity:
            raise CorpusIOError(
                "corpus_lock_scope_mismatch",
                "cannot nest stable locks for different brain roots",
                paths=(Path(active.brain_root_identity), Path(identity)),
            )
        if exclusive and not active.exclusive:
            raise CorpusIOError(
                "exclusive_corpus_lock_required",
                "cannot upgrade a shared stable corpus lock in place",
                paths=(Path(identity),),
            )
        yield
        return

    root = Path(identity)
    parent = root.parent
    try:
        parent_fd = os.open(
            parent,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
    except OSError as exc:
        raise _anchored_path_error(parent, exc) from exc
    lock_fd = -1
    try:
        try:
            lock_fd = os.open(
                _stable_lock_name(root),
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise _anchored_path_error(
                parent / _stable_lock_name(root),
                exc,
            ) from exc
        lock_stat = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_stat.st_mode):
            raise CorpusIOError(
                "file_type_invalid",
                "stable corpus lock is not a regular file",
                paths=(parent / _stable_lock_name(root),),
            )
        parent_stat = os.fstat(parent_fd)
        if lock_stat.st_dev != parent_stat.st_dev:
            raise CorpusIOError(
                "filesystem_mismatch",
                "stable corpus lock is on another filesystem",
                paths=(parent / _stable_lock_name(root),),
            )
        lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lock_fd, lock_mode)
        token = _STABLE_CORPUS_LOCK_SCOPE.set(
            _StableCorpusLockScope(identity, exclusive)
        )
        try:
            yield
        finally:
            _STABLE_CORPUS_LOCK_SCOPE.reset(token)
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        if lock_fd >= 0:
            os.close(lock_fd)
        os.close(parent_fd)


def _current_lock_scope(
    brain_root: Path,
    *,
    require_exclusive: bool = False,
) -> _CorpusLockScope:
    scope = _CORPUS_LOCK_SCOPE.get()
    requested = _brain_root_identity(brain_root)
    if scope is None:
        raise CorpusIOError(
            "corpus_lock_required",
            "operation requires an active corpus lock",
            paths=(Path(requested),),
        )
    if scope.brain_root_identity != requested:
        raise CorpusIOError(
            "corpus_lock_scope_mismatch",
            (
                "active corpus lock belongs to "
                f"{scope.brain_root_identity}, not {requested}"
            ),
            paths=(
                Path(scope.brain_root_identity),
                Path(requested),
            ),
        )
    if require_exclusive and not scope.exclusive:
        raise CorpusIOError(
            "exclusive_corpus_lock_required",
            "operation requires an exclusive corpus lock",
            paths=(Path(requested),),
        )
    return scope


def _validated_directory_path(value: object) -> str:
    if value == "":
        return ""
    return _validated_relative_path(value)


def _anchored_path_error(path: Path, exc: OSError) -> CorpusIOError:
    if exc.errno in (errno.ELOOP, errno.ENOTDIR):
        return CorpusIOError(
            "symlink_forbidden",
            f"cannot traverse path without following symlinks: {path}",
            paths=(path,),
        )
    if exc.errno == errno.EXDEV:
        return CorpusIOError(
            "filesystem_mismatch",
            f"path crosses a filesystem boundary: {path}",
            paths=(path,),
        )
    return CorpusIOError(
        "anchored_io_failed",
        f"anchored path operation failed for {path}: {exc}",
        paths=(path,),
    )


def _open_directory_at(
    parent_fd: int,
    name: str,
    *,
    create: bool,
    expected_device: int,
) -> int:
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(name, 0o755, dir_fd=parent_fd)
        os.fsync(parent_fd)
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        os.fsync(descriptor)
    except OSError as exc:
        raise _anchored_path_error(Path(name), exc) from exc
    if os.fstat(descriptor).st_dev != expected_device:
        os.close(descriptor)
        raise CorpusIOError(
            "filesystem_mismatch",
            f"{name}: directory is on another filesystem",
        )
    return descriptor


def _open_nested_directory_at(
    base_fd: int,
    relative_path: str,
    *,
    create: bool,
    expected_device: int,
    owned_fds: list[int],
) -> int:
    descriptor = os.dup(base_fd)
    owned_fds.append(descriptor)
    if relative_path in ("", "."):
        return descriptor
    for part in PurePosixPath(relative_path).parts:
        next_descriptor = _open_directory_at(
            descriptor,
            part,
            create=create,
            expected_device=expected_device,
        )
        owned_fds.append(next_descriptor)
        descriptor = next_descriptor
    return descriptor


def _file_stat_at(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        file_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(file_stat.st_mode):
        raise CorpusIOError(
            "symlink_forbidden",
            f"{name}: file entry is a symlink",
        )
    if not stat.S_ISREG(file_stat.st_mode):
        raise CorpusIOError(
            "file_type_invalid",
            f"{name}: file entry is not regular",
        )
    return file_stat


def _sha256_at(parent_fd: int, name: str) -> str:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW,
        dir_fd=parent_fd,
    )
    try:
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)
    finally:
        os.close(descriptor)


def _read_bytes_at(parent_fd: int, name: str) -> bytes:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW,
        dir_fd=parent_fd,
    )
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def read_tracked_json_files(
    brain_root: Path,
    relative_directories: Iterable[str],
) -> tuple[tuple[Path, bytes], ...]:
    """Read tracked JSON trees through the active pinned corpus root."""
    active = _CORPUS_LOCK_SCOPE.get()
    if active is None:
        with corpus_lock(brain_root, exclusive=False):
            return read_tracked_json_files(
                brain_root,
                relative_directories,
            )
    scope = _current_lock_scope(brain_root)
    results: list[tuple[Path, bytes]] = []
    for relative_directory in sorted(set(relative_directories)):
        normalized = _validated_directory_path(relative_directory)
        try:
            directory = scope.anchored.pin_directory(
                normalized,
                create=False,
            )
        except FileNotFoundError:
            continue
        _collect_json_files_at(
            scope,
            directory.fd,
            normalized,
            results,
        )
    return tuple(sorted(results, key=lambda item: item[0].as_posix()))


def _collect_json_files_at(
    scope: _CorpusLockScope,
    directory_fd: int,
    relative_directory: str,
    results: list[tuple[Path, bytes]],
) -> None:
    try:
        children = sorted(os.listdir(directory_fd))
    except OSError as exc:
        raise CorpusIOError(
            "object_scan_failed",
            f"cannot list tracked object directory: {relative_directory}",
            paths=(
                Path(scope.brain_root_identity) / relative_directory,
            ),
        ) from exc
    for name in children:
        relative_path = (
            PurePosixPath(relative_directory, name).as_posix()
        )
        try:
            child_stat = os.stat(
                name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise CorpusIOError(
                "object_scan_failed",
                f"cannot inspect tracked object entry: {relative_path}",
                paths=(Path(scope.brain_root_identity) / relative_path,),
            ) from exc
        if stat.S_ISLNK(child_stat.st_mode):
            raise CorpusIOError(
                "symlink_forbidden",
                f"tracked object entry is a symlink: {relative_path}",
                paths=(Path(scope.brain_root_identity) / relative_path,),
            )
        if child_stat.st_dev != scope.anchored.device:
            raise CorpusIOError(
                "filesystem_mismatch",
                f"tracked object entry crosses filesystem: {relative_path}",
                paths=(Path(scope.brain_root_identity) / relative_path,),
            )
        if stat.S_ISDIR(child_stat.st_mode):
            child_fd = _open_directory_at(
                directory_fd,
                name,
                create=False,
                expected_device=scope.anchored.device,
            )
            try:
                _collect_json_files_at(
                    scope,
                    child_fd,
                    relative_path,
                    results,
                )
            finally:
                os.close(child_fd)
            continue
        if not stat.S_ISREG(child_stat.st_mode):
            raise CorpusIOError(
                "file_type_invalid",
                f"tracked object entry is not regular: {relative_path}",
                paths=(Path(scope.brain_root_identity) / relative_path,),
            )
        if name.endswith(".json"):
            results.append((
                Path(scope.brain_root_identity) / relative_path,
                _read_bytes_at(directory_fd, name),
            ))


def _write_bytes_at(
    parent_fd: int,
    name: str,
    payload: bytes,
    *,
    replace_existing: bool,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
    if replace_existing:
        flags |= os.O_TRUNC
    else:
        flags |= os.O_EXCL
    descriptor = os.open(name, flags, 0o600, dir_fd=parent_fd)
    try:
        view = memoryview(payload)
        written = 0
        while written < len(view):
            written += os.write(descriptor, view[written:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(parent_fd)


def _unlink_at_if_exists(parent_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=parent_fd)
    except FileNotFoundError:
        return
    os.fsync(parent_fd)


def _write_journal_at(
    transaction_fd: int,
    journal: Mapping[str, object],
) -> None:
    payload = (
        json.dumps(
            journal,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    temporary_name = ".journal.json.tmp"
    _unlink_at_if_exists(transaction_fd, temporary_name)
    _write_bytes_at(
        transaction_fd,
        temporary_name,
        payload,
        replace_existing=False,
    )
    os.replace(
        temporary_name,
        "journal.json",
        src_dir_fd=transaction_fd,
        dst_dir_fd=transaction_fd,
    )
    os.fsync(transaction_fd)


def _read_journal_at(
    transaction_fd: int,
    transaction_id: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(
            _read_bytes_at(transaction_fd, "journal.json").decode("utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryRequiredError(
            f"{transaction_id}: journal is missing or invalid: {exc}",
            transaction_ids=(transaction_id,),
        ) from exc
    if not isinstance(payload, dict):
        raise RecoveryRequiredError(
            f"{transaction_id}: journal must contain a JSON object",
            transaction_ids=(transaction_id,),
        )
    try:
        _validate_journal_model(payload, transaction_id)
    except (TypeError, ValueError) as exc:
        raise RecoveryRequiredError(
            f"{transaction_id}: journal structure is invalid: {exc}",
            transaction_ids=(transaction_id,),
        ) from exc
    return payload


def _remove_tree_at(parent_fd: int, name: str, *, expected_device: int) -> None:
    file_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISDIR(file_stat.st_mode):
        os.unlink(name, dir_fd=parent_fd)
        os.fsync(parent_fd)
        return
    descriptor = _open_directory_at(
        parent_fd,
        name,
        create=False,
        expected_device=expected_device,
    )
    try:
        for child in os.listdir(descriptor):
            child_stat = os.stat(
                child,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            if stat.S_ISDIR(child_stat.st_mode) and not stat.S_ISLNK(
                child_stat.st_mode
            ):
                _remove_tree_at(
                    descriptor,
                    child,
                    expected_device=expected_device,
                )
            else:
                os.unlink(child, dir_fd=descriptor)
                os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.rmdir(name, dir_fd=parent_fd)
    os.fsync(parent_fd)


def _cleanup_private_attempts(anchored: _AnchoredRoot) -> None:
    relative_root = ".brain-local/preparing-transactions"
    try:
        preparing = anchored.pin_directory(
            relative_root,
            create=False,
        )
    except FileNotFoundError:
        return
    for name in sorted(os.listdir(preparing.fd)):
        relative_path = f"{relative_root}/{name}"
        try:
            entry_stat = os.stat(
                name,
                dir_fd=preparing.fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise CorpusIOError(
                "private_transaction_invalid",
                f"cannot inspect private transaction: {relative_path}",
                paths=(anchored.path / relative_path,),
            ) from exc
        if (
            _SHA256.fullmatch(name) is None
            or stat.S_ISLNK(entry_stat.st_mode)
            or not stat.S_ISDIR(entry_stat.st_mode)
        ):
            raise CorpusIOError(
                "private_transaction_invalid",
                f"unexpected private transaction entry: {relative_path}",
                paths=(anchored.path / relative_path,),
            )
        _validate_private_tree_at(
            preparing.fd,
            name,
            relative_path=relative_path,
            expected_device=anchored.device,
            brain_root=anchored.path,
        )
        _remove_tree_at(
            preparing.fd,
            name,
            expected_device=anchored.device,
        )


def _validate_private_tree_at(
    parent_fd: int,
    name: str,
    *,
    relative_path: str,
    expected_device: int,
    brain_root: Path,
) -> None:
    entry_stat = os.stat(
        name,
        dir_fd=parent_fd,
        follow_symlinks=False,
    )
    if (
        entry_stat.st_dev != expected_device
        or stat.S_ISLNK(entry_stat.st_mode)
        or not stat.S_ISDIR(entry_stat.st_mode)
    ):
        raise CorpusIOError(
            "private_transaction_invalid",
            f"unsafe private transaction entry: {relative_path}",
            paths=(brain_root / relative_path,),
        )
    descriptor = _open_directory_at(
        parent_fd,
        name,
        create=False,
        expected_device=expected_device,
    )
    try:
        for child in sorted(os.listdir(descriptor)):
            child_relative = f"{relative_path}/{child}"
            child_stat = os.stat(
                child,
                dir_fd=descriptor,
                follow_symlinks=False,
            )
            if (
                child_stat.st_dev != expected_device
                or stat.S_ISLNK(child_stat.st_mode)
            ):
                raise CorpusIOError(
                    "private_transaction_invalid",
                    f"unsafe private transaction entry: {child_relative}",
                    paths=(brain_root / child_relative,),
                )
            if stat.S_ISDIR(child_stat.st_mode):
                _validate_private_tree_at(
                    descriptor,
                    child,
                    relative_path=child_relative,
                    expected_device=expected_device,
                    brain_root=brain_root,
                )
            elif not stat.S_ISREG(child_stat.st_mode):
                raise CorpusIOError(
                    "private_transaction_invalid",
                    f"unsafe private transaction entry: {child_relative}",
                    paths=(brain_root / child_relative,),
                )
    finally:
        os.close(descriptor)


@contextmanager
def corpus_lock(brain_root: Path, *, exclusive: bool) -> Iterator[None]:
    """Hold the corpus advisory lock for a complete read or mutation."""
    identity = _brain_root_identity(brain_root)
    active = _CORPUS_LOCK_SCOPE.get()
    if active is not None:
        if active.brain_root_identity != identity:
            raise CorpusIOError(
                "corpus_lock_scope_mismatch",
                "cannot nest locks for different brain roots",
                paths=(
                    Path(active.brain_root_identity),
                    Path(identity),
                ),
            )
        if exclusive and not active.exclusive:
            raise CorpusIOError(
                "exclusive_corpus_lock_required",
                "cannot upgrade a shared corpus lock in place",
                paths=(Path(identity),),
            )
        yield
        return

    brain_root = Path(identity)
    with stable_corpus_lock(brain_root, exclusive=exclusive):
        if (restore_state_root(brain_root) / "journal.json").exists():
            raise RecoveryRequiredError(
                "snapshot restore recovery is required before corpus access"
            )
        brain_root.mkdir(parents=True, exist_ok=True)
        with _corpus_inode_lock(brain_root, identity, exclusive=exclusive):
            yield


@contextmanager
def _corpus_inode_lock(
    brain_root: Path,
    identity: str,
    *,
    exclusive: bool,
) -> Iterator[None]:
    with _AnchoredRoot(brain_root) as anchored:
        lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(anchored.root_fd, lock_mode)
        try:
            local_root = anchored.pin_directory(".brain-local", create=True)
            anchored.bind_prefix(".brain-local", local_root)
            try:
                lock_fd = os.open(
                    "corpus.lock",
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=local_root.fd,
                )
            except OSError as exc:
                raise _anchored_path_error(
                    brain_root / ".brain-local" / "corpus.lock",
                    exc,
                ) from exc
            fcntl.flock(
                lock_fd, lock_mode
            )
            try:
                lock_stat = os.fstat(lock_fd)
                if not stat.S_ISREG(lock_stat.st_mode):
                    raise CorpusIOError(
                        "file_type_invalid",
                        "corpus.lock is not a regular file",
                        paths=(
                            brain_root / ".brain-local" / "corpus.lock",
                        ),
                    )
                if (
                    _observed_device(
                        ".brain-local/corpus.lock",
                        lock_stat.st_dev,
                    )
                    != anchored.device
                ):
                    raise CorpusIOError(
                        "filesystem_mismatch",
                        "corpus.lock is on another filesystem",
                        paths=(
                            brain_root / ".brain-local" / "corpus.lock",
                        ),
                    )
                scope = _CorpusLockScope(
                    identity,
                    anchored,
                    local_root,
                    exclusive,
                )
                token = _CORPUS_LOCK_SCOPE.set(scope)
                try:
                    if exclusive:
                        _cleanup_private_attempts(anchored)
                    yield
                finally:
                    _CORPUS_LOCK_SCOPE.reset(token)
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
        finally:
            fcntl.flock(anchored.root_fd, fcntl.LOCK_UN)


def fsync_file(path: Path) -> None:
    with Path(path).open("rb") as file_obj:
        os.fsync(file_obj.fileno())


def fsync_directory(path: Path) -> None:
    descriptor = os.open(Path(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def assert_corpus_readable(brain_root: Path) -> None:
    unfinished = _unfinished_transaction_ids(brain_root)
    if unfinished:
        raise RecoveryRequiredError(
            "unfinished corpus transaction requires rollback before reading: "
            + ", ".join(unfinished),
            transaction_ids=unfinished,
        )


def recover_unfinished_transaction(brain_root: Path) -> RecoveryResult:
    with corpus_lock(brain_root, exclusive=True):
        return recover_unfinished_transaction_unlocked(brain_root)


def recover_unfinished_transaction_unlocked(
    brain_root: Path,
) -> RecoveryResult:
    scope = _current_lock_scope(
        brain_root,
        require_exclusive=True,
    )
    recovered: list[str] = []
    owned_fds: list[int] = []
    anchored = scope.anchored
    scope.verify_lexical_bindings()
    try:
        for transaction_id, journal in _active_journals(anchored):
            if journal["state"] in _TERMINAL_STATES:
                continue
            transaction = anchored.pin_directory(
                f".brain-local/transactions/{transaction_id}",
                create=False,
            )
            if journal["state"] == JournalState.RECOVERY_REQUIRED.value:
                raise RecoveryRequiredError(
                    (
                        f"{transaction_id}: transaction requires "
                        "manual recovery"
                    ),
                    transaction_ids=(transaction_id,),
            )
            try:
                scope.verify_lexical_bindings()
                _rollback_transaction_anchored(
                    anchored,
                    transaction.fd,
                    journal,
                    owned_fds=owned_fds,
                )
                scope.verify_lexical_bindings()
                journal["state"] = JournalState.ROLLED_BACK.value
                _write_journal_at(transaction.fd, journal)
            except BaseException as exc:
                journal["state"] = JournalState.RECOVERY_REQUIRED.value
                journal["recovery_error"] = str(exc)
                try:
                    _write_journal_at(transaction.fd, journal)
                except BaseException:
                    pass
                raise RecoveryRequiredError(
                    (
                        f"{transaction_id}: automatic rollback "
                        f"failed: {exc}"
                    ),
                    transaction_ids=(transaction_id,),
                ) from exc
            recovered.append(transaction_id)
    finally:
        for descriptor in reversed(owned_fds):
            try:
                os.close(descriptor)
            except OSError:
                pass
    return RecoveryResult(tuple(recovered))


def apply_transaction(
    brain_root: Path,
    *,
    manifest: Mapping[str, object],
    after_files: Mapping[str, bytes],
    failure_injector: Callable[[str], None] | None = None,
    preparation_injector: Callable[[str], None] | None = None,
) -> None:
    """Apply one validated mutation using only root-anchored writes."""
    active = _CORPUS_LOCK_SCOPE.get()
    if active is None:
        with corpus_lock(brain_root, exclusive=True):
            apply_transaction(
                brain_root,
                manifest=manifest,
                after_files=after_files,
                failure_injector=failure_injector,
                preparation_injector=preparation_injector,
            )
        return
    scope = _current_lock_scope(
        brain_root,
        require_exclusive=True,
    )
    transaction_id = manifest.get("transaction_id")
    if not isinstance(transaction_id, str) or not transaction_id:
        raise ValueError("manifest transaction_id must be a non-empty string")
    scope.verify_lexical_bindings()
    owned_fds: list[int] = []
    anchored = scope.anchored
    private_fd: int | None = None
    journal: dict[str, Any] | None = None
    try:
            _validate_manifest_model(manifest, transaction_id)
            entries = _build_entries_anchored(
                anchored,
                manifest,
                after_files,
            )
            derived = [
                anchored.inspect_file(relative_path)
                for relative_path in _DERIVED_PATHS
            ]
            journal = {
                "version": 1,
                "transaction_id": transaction_id,
                "state": JournalState.PREPARING.value,
                "manifest": dict(manifest),
                "entries": entries,
                "derived": derived,
                "before_derived_fingerprint": _inventory_fingerprint(
                    derived
                ),
                "expected_after_derived_fingerprint": (
                    _empty_derived_fingerprint()
                ),
                "applied": [],
            }
            _validate_journal_model(journal, transaction_id)

            _archive_active_transaction_anchored(
                anchored,
                transaction_id,
            )
            preparing = anchored.pin_directory(
                ".brain-local/preparing-transactions",
                create=True,
            )
            _remove_child_if_present(
                preparing.fd,
                transaction_id,
                expected_device=anchored.device,
            )
            os.mkdir(transaction_id, 0o700, dir_fd=preparing.fd)
            os.fsync(preparing.fd)
            private_fd = _open_directory_at(
                preparing.fd,
                transaction_id,
                create=False,
                expected_device=anchored.device,
            )
            owned_fds.append(private_fd)
            _inject(preparation_injector, "after_private_root_mkdir")
            scope.verify_lexical_bindings()
            temp_fd = _mkdir_and_open_transaction_child(
                private_fd,
                "temp",
                anchored.device,
                owned_fds,
            )
            _inject(preparation_injector, "after_temp_dir_mkdir")
            scope.verify_lexical_bindings()
            before_fd = _mkdir_and_open_transaction_child(
                private_fd,
                "before",
                anchored.device,
                owned_fds,
            )
            _inject(preparation_injector, "after_before_dir_mkdir")
            scope.verify_lexical_bindings()
            snapshots_fd = _mkdir_and_open_transaction_child(
                private_fd,
                "snapshots",
                anchored.device,
                owned_fds,
            )
            _inject(preparation_injector, "after_snapshot_dir_mkdir")
            scope.verify_lexical_bindings()
            _write_journal_at(private_fd, journal)
            os.fsync(private_fd)
            _inject(preparation_injector, "before_active_publish")
            scope.verify_lexical_bindings()

            transactions = anchored.pin_directory(
                ".brain-local/transactions",
                create=True,
            )
            os.rename(
                transaction_id,
                transaction_id,
                src_dir_fd=preparing.fd,
                dst_dir_fd=transactions.fd,
            )
            os.fsync(preparing.fd)
            os.fsync(transactions.fd)

            live_parents = _pin_live_parents(
                anchored,
                (*entries, *derived),
            )
            temp_parents = _transaction_parent_fds(
                temp_fd,
                entries,
                expected_device=anchored.device,
                owned_fds=owned_fds,
            )
            before_parents = _transaction_parent_fds(
                before_fd,
                (*entries, *derived),
                expected_device=anchored.device,
                owned_fds=owned_fds,
            )
            snapshot_parents = _transaction_parent_fds(
                snapshots_fd,
                (*entries, *derived),
                expected_device=anchored.device,
                owned_fds=owned_fds,
            )

            for entry in entries:
                if entry["after_sha256"] is None:
                    continue
                parent_fd, name = temp_parents[entry["path"]]
                _write_bytes_at(
                    parent_fd,
                    name,
                    after_files[entry["path"]],
                    replace_existing=False,
                )
            _inject(failure_injector, "after_temp_fsync")
            scope.verify_lexical_bindings()
            _verify_live_bindings(anchored, live_parents)

            for entry in (*entries, *derived):
                if not entry["had_before"]:
                    continue
                live_parent, live_name = live_parents[entry["path"]]
                data = _read_bytes_at(live_parent.fd, live_name)
                if hashlib.sha256(data).hexdigest() != entry["before_sha256"]:
                    raise CorpusIOError(
                        "before_hash_mismatch",
                        (
                            f"{entry['path']}: before image changed "
                            "while preparing"
                        ),
                    )
                snapshot_parent_fd, snapshot_name = snapshot_parents[
                    entry["path"]
                ]
                _write_bytes_at(
                    snapshot_parent_fd,
                    snapshot_name,
                    data,
                    replace_existing=False,
                )
            journal["state"] = JournalState.PREPARED.value
            _write_journal_at(private_fd, journal)
            _inject(failure_injector, "after_journal_prepared")
            scope.verify_lexical_bindings()

            journal["state"] = JournalState.COMMITTING.value
            _write_journal_at(private_fd, journal)
            _inject(failure_injector, "after_state_committing")
            scope.verify_lexical_bindings()

            first_before_rename = True
            for entry in entries:
                if not entry["had_before"]:
                    continue
                live_parent, live_name = live_parents[entry["path"]]
                anchored.verify_binding(live_parent)
                if (
                    _sha256_at(live_parent.fd, live_name)
                    != entry["before_sha256"]
                ):
                    raise CorpusIOError(
                        "before_hash_mismatch",
                        f"{entry['path']}: live file changed before rename",
                    )
                before_parent_fd, before_name = before_parents[entry["path"]]
                scope.verify_lexical_bindings()
                os.replace(
                    live_name,
                    before_name,
                    src_dir_fd=live_parent.fd,
                    dst_dir_fd=before_parent_fd,
                )
                os.fsync(live_parent.fd)
                os.fsync(before_parent_fd)
                _record_applied_at(
                    private_fd,
                    journal,
                    f"before:{entry['path']}",
                )
                scope.verify_lexical_bindings()
                if first_before_rename:
                    first_before_rename = False
                    _inject(
                        failure_injector,
                        "after_first_before_rename",
                    )
                    scope.verify_lexical_bindings()

            first_live_replace = True
            for entry in entries:
                if entry["after_sha256"] is None:
                    continue
                live_parent, live_name = live_parents[entry["path"]]
                anchored.verify_binding(live_parent)
                temp_parent_fd, temp_name = temp_parents[entry["path"]]
                scope.verify_lexical_bindings()
                os.replace(
                    temp_name,
                    live_name,
                    src_dir_fd=temp_parent_fd,
                    dst_dir_fd=live_parent.fd,
                )
                os.fsync(temp_parent_fd)
                os.fsync(live_parent.fd)
                _record_applied_at(
                    private_fd,
                    journal,
                    f"live:{entry['path']}",
                )
                scope.verify_lexical_bindings()
                if first_live_replace:
                    first_live_replace = False
                    _inject(
                        failure_injector,
                        "after_first_live_replace",
                    )
                    scope.verify_lexical_bindings()

            for entry in derived:
                live_parent, live_name = live_parents[entry["path"]]
                anchored.verify_binding(live_parent)
                current = _file_stat_at(live_parent.fd, live_name)
                if current is None:
                    if entry["had_before"]:
                        raise CorpusIOError(
                            "before_hash_mismatch",
                            f"{entry['path']}: derived file disappeared",
                        )
                    continue
                before_parent_fd, before_name = before_parents[entry["path"]]
                scope.verify_lexical_bindings()
                os.replace(
                    live_name,
                    before_name,
                    src_dir_fd=live_parent.fd,
                    dst_dir_fd=before_parent_fd,
                )
                os.fsync(live_parent.fd)
                os.fsync(before_parent_fd)
                _record_applied_at(
                    private_fd,
                    journal,
                    f"derived:{entry['path']}",
                )
                scope.verify_lexical_bindings()
            _inject(failure_injector, "after_derived_invalidation")
            scope.verify_lexical_bindings()
            _inject(failure_injector, "before_post_commit_gate")
            scope.verify_lexical_bindings()

            _verify_live_bindings(anchored, live_parents)
            _verify_committed_state(anchored, journal)
            _verify_live_bindings(anchored, live_parents)
            journal["state"] = JournalState.COMMITTED.value
            _write_journal_at(private_fd, journal)
    except CorpusIOError as exc:
        if (
            exc.code != "path_binding_changed"
            or journal is None
            or private_fd is None
        ):
            raise
        try:
            _rollback_transaction_anchored(
                anchored,
                private_fd,
                journal,
                owned_fds=owned_fds,
            )
            journal["state"] = JournalState.ROLLED_BACK.value
            _write_journal_at(private_fd, journal)
        except BaseException as rollback_exc:
            journal["state"] = JournalState.RECOVERY_REQUIRED.value
            journal["recovery_error"] = str(rollback_exc)
            try:
                _write_journal_at(private_fd, journal)
            except BaseException:
                pass
            raise RecoveryRequiredError(
                (
                    f"{transaction_id}: automatic rollback after "
                    f"binding change failed: {rollback_exc}"
                ),
                transaction_ids=(transaction_id,),
            ) from rollback_exc
        raise
    finally:
        for descriptor in reversed(owned_fds):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _build_entries_anchored(
    anchored: _AnchoredRoot,
    manifest: Mapping[str, object],
    after_files: Mapping[str, bytes],
) -> list[dict[str, object]]:
    expected = _validate_manifest_model(
        manifest,
        str(manifest["transaction_id"]),
    )
    entries: list[dict[str, object]] = []
    for expected_entry in expected:
        entry = anchored.inspect_file(str(expected_entry["path"]))
        if entry["before_sha256"] != expected_entry["before_sha256"]:
            raise CorpusIOError(
                "before_hash_mismatch",
                (
                    f"{entry['path']}: before hash changed between "
                    "plan and apply"
                ),
                paths=(anchored.path / str(entry["path"]),),
            )
        after_sha = expected_entry["after_sha256"]
        if after_sha is not None:
            payload = after_files.get(str(entry["path"]))
            if (
                not isinstance(payload, bytes)
                or hashlib.sha256(payload).hexdigest() != after_sha
            ):
                raise CorpusIOError(
                    "after_payload_invalid",
                    f"{entry['path']}: after bytes do not match manifest",
                )
        elif entry["path"] in after_files:
            raise CorpusIOError(
                "after_payload_invalid",
                f"{entry['path']}: delete action has after bytes",
            )
        entry["after_sha256"] = after_sha
        entries.append(entry)
    expected_after_paths = {
        str(entry["path"])
        for entry in entries
        if entry["after_sha256"] is not None
    }
    unexpected = set(after_files) - expected_after_paths
    if unexpected:
        raise CorpusIOError(
            "after_payload_invalid",
            "after bytes contain paths absent from manifest: "
            + ", ".join(sorted(unexpected)),
        )
    return entries


def _empty_derived_fingerprint() -> str:
    return _inventory_fingerprint([
        {
            "path": relative_path,
            "had_before": False,
            "before_sha256": None,
        }
        for relative_path in _DERIVED_PATHS
    ])


def _archive_active_transaction_anchored(
    anchored: _AnchoredRoot,
    transaction_id: str,
) -> None:
    transactions = anchored.pin_directory(
        ".brain-local/transactions",
        create=True,
    )
    active_stat = _file_stat_or_directory_at(
        transactions.fd,
        transaction_id,
    )
    if active_stat is None:
        return
    if not stat.S_ISDIR(active_stat.st_mode) or stat.S_ISLNK(
        active_stat.st_mode
    ):
        raise RecoveryRequiredError(
            f"{transaction_id}: active transaction entry is invalid",
            transaction_ids=(transaction_id,),
        )
    active_fd = _open_directory_at(
        transactions.fd,
        transaction_id,
        create=False,
        expected_device=anchored.device,
    )
    try:
        previous = _read_journal_at(active_fd, transaction_id)
    finally:
        os.close(active_fd)
    if previous["state"] not in _TERMINAL_STATES:
        raise RecoveryRequiredError(
            f"{transaction_id}: active transaction is unfinished",
            transaction_ids=(transaction_id,),
        )

    history = anchored.pin_directory(
        f".brain-local/transaction-history/{transaction_id}",
        create=True,
    )
    attempts: list[int] = []
    for child in os.listdir(history.fd):
        child_stat = os.stat(
            child,
            dir_fd=history.fd,
            follow_symlinks=False,
        )
        if (
            stat.S_ISDIR(child_stat.st_mode)
            and not stat.S_ISLNK(child_stat.st_mode)
            and child.startswith("attempt-")
            and child[8:].isdigit()
        ):
            attempts.append(int(child[8:]))
            continue
        raise CorpusIOError(
            "transaction_history_invalid",
            f"unexpected transaction history entry: {child}",
        )
    archive_name = f"attempt-{max(attempts, default=0) + 1:06d}"
    os.rename(
        transaction_id,
        archive_name,
        src_dir_fd=transactions.fd,
        dst_dir_fd=history.fd,
    )
    os.fsync(transactions.fd)
    os.fsync(history.fd)


def _file_stat_or_directory_at(
    parent_fd: int,
    name: str,
) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _remove_child_if_present(
    parent_fd: int,
    name: str,
    *,
    expected_device: int,
) -> None:
    if _file_stat_or_directory_at(parent_fd, name) is None:
        return
    _remove_tree_at(parent_fd, name, expected_device=expected_device)


def _mkdir_and_open_transaction_child(
    transaction_fd: int,
    name: str,
    expected_device: int,
    owned_fds: list[int],
) -> int:
    os.mkdir(name, 0o700, dir_fd=transaction_fd)
    os.fsync(transaction_fd)
    descriptor = _open_directory_at(
        transaction_fd,
        name,
        create=False,
        expected_device=expected_device,
    )
    owned_fds.append(descriptor)
    os.fsync(descriptor)
    return descriptor


def _pin_live_parents(
    anchored: _AnchoredRoot,
    entries: tuple[dict[str, object], ...],
) -> dict[str, tuple[_PinnedDirectory, str]]:
    pinned_by_parent: dict[str, _PinnedDirectory] = {}
    result: dict[str, tuple[_PinnedDirectory, str]] = {}
    for entry in entries:
        relative_path = str(entry["path"])
        path = PurePosixPath(relative_path)
        parent = path.parent.as_posix()
        if parent == ".":
            parent = ""
        pinned = pinned_by_parent.get(parent)
        if pinned is None:
            pinned = anchored.pin_directory(parent, create=True)
            pinned_by_parent[parent] = pinned
        result[relative_path] = (pinned, path.name)
    return result


def _transaction_parent_fds(
    base_fd: int,
    entries: tuple[dict[str, object], ...] | list[dict[str, object]],
    *,
    expected_device: int,
    owned_fds: list[int],
) -> dict[str, tuple[int, str]]:
    parents: dict[str, int] = {}
    result: dict[str, tuple[int, str]] = {}
    for entry in entries:
        relative_path = str(entry["path"])
        path = PurePosixPath(relative_path)
        parent = path.parent.as_posix()
        if parent == ".":
            parent = ""
        descriptor = parents.get(parent)
        if descriptor is None:
            descriptor = _open_nested_directory_at(
                base_fd,
                parent,
                create=True,
                expected_device=expected_device,
                owned_fds=owned_fds,
            )
            parents[parent] = descriptor
        result[relative_path] = (descriptor, path.name)
    return result


def _verify_live_bindings(
    anchored: _AnchoredRoot,
    live_parents: Mapping[str, tuple[_PinnedDirectory, str]],
) -> None:
    seen: set[tuple[int, int]] = set()
    for pinned, _ in live_parents.values():
        identity = (pinned.device, pinned.inode)
        if identity in seen:
            continue
        anchored.verify_binding(pinned)
        seen.add(identity)


def _record_applied_at(
    transaction_fd: int,
    journal: dict[str, Any],
    marker: str,
) -> None:
    journal["applied"].append(marker)
    _write_journal_at(transaction_fd, journal)


def _active_journals(
    anchored: _AnchoredRoot,
) -> list[tuple[str, dict[str, Any]]]:
    try:
        transactions = anchored.pin_directory(
            ".brain-local/transactions",
            create=False,
        )
    except FileNotFoundError:
        return []
    active: list[tuple[str, dict[str, Any]]] = []
    for transaction_id in sorted(os.listdir(transactions.fd)):
        entry_stat = os.stat(
            transaction_id,
            dir_fd=transactions.fd,
            follow_symlinks=False,
        )
        if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISDIR(
            entry_stat.st_mode
        ):
            raise RecoveryRequiredError(
                f"unexpected active transaction entry: {transaction_id}",
                transaction_ids=(transaction_id,),
            )
        transaction_fd = _open_directory_at(
            transactions.fd,
            transaction_id,
            create=False,
            expected_device=anchored.device,
        )
        try:
            active.append((
                transaction_id,
                _read_journal_at(transaction_fd, transaction_id),
            ))
        finally:
            os.close(transaction_fd)
    return active


def _rollback_transaction_anchored(
    anchored: _AnchoredRoot,
    transaction_fd: int,
    journal: Mapping[str, object],
    *,
    owned_fds: list[int],
) -> None:
    raw_entries = journal["entries"]
    raw_derived = journal["derived"]
    assert isinstance(raw_entries, list)
    assert isinstance(raw_derived, list)
    entries = tuple(dict(entry) for entry in raw_entries)
    derived = tuple(dict(entry) for entry in raw_derived)
    live_parents = _pin_live_parents(
        anchored,
        (*entries, *derived),
    )
    before_fd = _open_directory_at(
        transaction_fd,
        "before",
        create=False,
        expected_device=anchored.device,
    )
    snapshots_fd = _open_directory_at(
        transaction_fd,
        "snapshots",
        create=False,
        expected_device=anchored.device,
    )
    restore_fd = _open_directory_at(
        transaction_fd,
        "restore",
        create=True,
        expected_device=anchored.device,
    )
    owned_fds.extend((before_fd, snapshots_fd, restore_fd))

    for entry in (*entries, *derived):
        relative_path = str(entry["path"])
        live_parent, live_name = live_parents[relative_path]
        anchored.verify_binding(live_parent)
        live_stat = _file_stat_at(live_parent.fd, live_name)
        if not entry["had_before"]:
            if live_stat is not None:
                os.unlink(live_name, dir_fd=live_parent.fd)
                os.fsync(live_parent.fd)
            continue

        before_sha = str(entry["before_sha256"])
        if (
            live_stat is not None
            and _sha256_at(live_parent.fd, live_name) == before_sha
        ):
            continue
        before_source = _backup_source(
            before_fd,
            relative_path,
            before_sha,
            expected_device=anchored.device,
            owned_fds=owned_fds,
        )
        snapshot_source = _backup_source(
            snapshots_fd,
            relative_path,
            before_sha,
            expected_device=anchored.device,
            owned_fds=owned_fds,
        )
        if before_source is not None:
            source_parent_fd, source_name = before_source
            os.replace(
                source_name,
                live_name,
                src_dir_fd=source_parent_fd,
                dst_dir_fd=live_parent.fd,
            )
            os.fsync(source_parent_fd)
            os.fsync(live_parent.fd)
        elif snapshot_source is not None:
            source_parent_fd, source_name = snapshot_source
            payload = _read_bytes_at(source_parent_fd, source_name)
            restore_parent_fd, restore_name = _nested_file_parent(
                restore_fd,
                relative_path,
                create=True,
                expected_device=anchored.device,
                owned_fds=owned_fds,
            )
            temporary_name = f".{restore_name}.restore"
            _unlink_at_if_exists(restore_parent_fd, temporary_name)
            _write_bytes_at(
                restore_parent_fd,
                temporary_name,
                payload,
                replace_existing=False,
            )
            os.replace(
                temporary_name,
                live_name,
                src_dir_fd=restore_parent_fd,
                dst_dir_fd=live_parent.fd,
            )
            os.fsync(restore_parent_fd)
            os.fsync(live_parent.fd)
        else:
            raise CorpusIOError(
                "before_image_missing",
                f"{relative_path}: valid before image is unavailable",
            )
        if _sha256_at(live_parent.fd, live_name) != before_sha:
            raise CorpusIOError(
                "rollback_hash_mismatch",
                f"{relative_path}: restored hash mismatch",
            )

    _verify_live_bindings(anchored, live_parents)
    _verify_rolled_back_state(anchored, journal)
    _verify_live_bindings(anchored, live_parents)


def _backup_source(
    base_fd: int,
    relative_path: str,
    expected_sha: str,
    *,
    expected_device: int,
    owned_fds: list[int],
) -> tuple[int, str] | None:
    try:
        parent_fd, name = _nested_file_parent(
            base_fd,
            relative_path,
            create=False,
            expected_device=expected_device,
            owned_fds=owned_fds,
        )
    except FileNotFoundError:
        return None
    file_stat = _file_stat_at(parent_fd, name)
    if file_stat is None or _sha256_at(parent_fd, name) != expected_sha:
        return None
    return parent_fd, name


def _nested_file_parent(
    base_fd: int,
    relative_path: str,
    *,
    create: bool,
    expected_device: int,
    owned_fds: list[int],
) -> tuple[int, str]:
    path = PurePosixPath(_validated_relative_path(relative_path))
    parent = path.parent.as_posix()
    if parent == ".":
        parent = ""
    return (
        _open_nested_directory_at(
            base_fd,
            parent,
            create=create,
            expected_device=expected_device,
            owned_fds=owned_fds,
        ),
        path.name,
    )


def _unfinished_transaction_ids(brain_root: Path) -> tuple[str, ...]:
    active = _CORPUS_LOCK_SCOPE.get()
    if active is None:
        with corpus_lock(brain_root, exclusive=False):
            return _unfinished_transaction_ids(brain_root)
    anchored = _current_lock_scope(brain_root).anchored
    return tuple(
        transaction_id
        for transaction_id, journal in _active_journals(anchored)
        if journal["state"] not in _TERMINAL_STATES
    )
def _validate_journal_model(
    journal: Mapping[str, object],
    transaction_id: str,
) -> None:
    if journal.get("version") != 1:
        raise ValueError("version must be 1")
    if _SHA256.fullmatch(transaction_id) is None:
        raise ValueError("transaction_id must be a lowercase SHA-256")
    state = JournalState(journal.get("state"))
    manifest = journal.get("manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("manifest must be an object")
    expected_entries = _validate_manifest_model(manifest, transaction_id)

    raw_entries = journal.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("entries must be a list")
    entries = [
        _validated_inventory_entry(entry, allow_after=True)
        for entry in raw_entries
    ]
    if entries != expected_entries:
        raise ValueError("entries do not match the manifest actions")

    raw_derived = journal.get("derived")
    if not isinstance(raw_derived, list):
        raise ValueError("derived must be a list")
    derived = [
        _validated_inventory_entry(entry, allow_after=False)
        for entry in raw_derived
    ]
    if [entry["path"] for entry in derived] != list(_DERIVED_PATHS):
        raise ValueError("derived inventory paths are incomplete or reordered")

    before_derived = journal.get("before_derived_fingerprint")
    expected_after_derived = journal.get(
        "expected_after_derived_fingerprint"
    )
    if not _is_sha256(before_derived) or not _is_sha256(
        expected_after_derived
    ):
        raise ValueError("derived fingerprints must be lowercase SHA-256")
    if before_derived != _inventory_fingerprint(derived):
        raise ValueError("before derived fingerprint does not match inventory")
    absent_derived = [
        {
            "path": relative_path,
            "had_before": False,
            "before_sha256": None,
        }
        for relative_path in _DERIVED_PATHS
    ]
    if expected_after_derived != _inventory_fingerprint(absent_derived):
        raise ValueError("expected after derived fingerprint is invalid")

    applied = journal.get("applied")
    if (
        not isinstance(applied, list)
        or not all(isinstance(marker, str) for marker in applied)
        or len(set(applied)) != len(applied)
    ):
        raise ValueError("applied must be a unique list of strings")
    allowed = {
        *(f"before:{entry['path']}" for entry in entries),
        *(f"live:{entry['path']}" for entry in entries),
        *(f"derived:{entry['path']}" for entry in derived),
    }
    if not set(applied).issubset(allowed):
        raise ValueError("applied contains an unknown marker")
    if state is JournalState.COMMITTED:
        required = {
            *(
                f"before:{entry['path']}"
                for entry in entries
                if entry["had_before"]
            ),
            *(
                f"live:{entry['path']}"
                for entry in entries
                if entry["after_sha256"] is not None
            ),
            *(
                f"derived:{entry['path']}"
                for entry in derived
                if entry["had_before"]
            ),
        }
        if not required.issubset(applied):
            raise ValueError("committed journal is missing applied markers")
    if state is JournalState.RECOVERY_REQUIRED:
        recovery_error = journal.get("recovery_error")
        if not isinstance(recovery_error, str) or not recovery_error:
            raise ValueError(
                "recovery_required journal needs a recovery_error"
            )


def _validate_manifest_model(
    manifest: Mapping[str, object],
    transaction_id: str,
) -> list[dict[str, object]]:
    required = {
        "transaction_id",
        "operation",
        "engine_sha",
        "creates",
        "updates",
        "deletes",
        "renames",
        "reference_rewrites",
        "before_fingerprint",
        "expected_after_fingerprint",
        "grandfathered_problems_before",
        "grandfathered_problems_after",
    }
    if set(manifest) != required:
        raise ValueError("manifest keys do not match the contract")
    if manifest.get("transaction_id") != transaction_id:
        raise ValueError("manifest transaction_id mismatch")
    if manifest.get("operation") not in _MUTATION_OPERATIONS:
        raise ValueError("manifest operation is invalid")
    if (
        not isinstance(manifest.get("engine_sha"), str)
        or _GIT_SHA.fullmatch(manifest["engine_sha"]) is None
    ):
        raise ValueError("manifest engine_sha is invalid")
    if not _is_sha256(manifest.get("before_fingerprint")):
        raise ValueError("manifest before_fingerprint is invalid")
    if not _is_sha256(manifest.get("expected_after_fingerprint")):
        raise ValueError("manifest expected_after_fingerprint is invalid")
    for field_name in (
        "grandfathered_problems_before",
        "grandfathered_problems_after",
    ):
        if not isinstance(manifest.get(field_name), (list, tuple)):
            raise ValueError(f"manifest {field_name} must be a sequence")

    entries: dict[str, dict[str, object]] = {}
    for field_name in ("creates", "updates", "deletes"):
        actions = manifest.get(field_name)
        if not isinstance(actions, (list, tuple)):
            raise ValueError(f"manifest {field_name} must be a sequence")
        for action in actions:
            if not isinstance(action, Mapping):
                raise ValueError(
                    f"manifest {field_name} entry must be an object"
                )
            if set(action) != {
                "object_id",
                "path",
                "before_sha256",
                "after_sha256",
            }:
                raise ValueError(
                    f"manifest {field_name} action keys are invalid"
                )
            _validated_object_id(action.get("object_id"))
            path = _validated_relative_path(action.get("path"))
            before_sha = action.get("before_sha256")
            after_sha = action.get("after_sha256")
            if field_name == "creates":
                _require_hashes(before_sha, after_sha, before=False, after=True)
            elif field_name == "updates":
                _require_hashes(before_sha, after_sha, before=True, after=True)
            else:
                _require_hashes(before_sha, after_sha, before=True, after=False)
            _add_expected_entry(entries, path, before_sha, after_sha)

    renames = manifest.get("renames")
    if not isinstance(renames, (list, tuple)):
        raise ValueError("manifest renames must be a sequence")
    for action in renames:
        if not isinstance(action, Mapping):
            raise ValueError("manifest rename entry must be an object")
        if set(action) != {
            "old_id",
            "new_id",
            "old_path",
            "new_path",
            "before_sha256",
            "after_sha256",
        }:
            raise ValueError("manifest rename action keys are invalid")
        _validated_object_id(action.get("old_id"))
        _validated_object_id(action.get("new_id"))
        before_sha = action.get("before_sha256")
        after_sha = action.get("after_sha256")
        _require_hashes(before_sha, after_sha, before=True, after=True)
        _add_expected_entry(
            entries,
            _validated_relative_path(action.get("old_path")),
            before_sha,
            None,
        )
        _add_expected_entry(
            entries,
            _validated_relative_path(action.get("new_path")),
            None,
            after_sha,
        )

    rewrites = manifest.get("reference_rewrites")
    if not isinstance(rewrites, (list, tuple)):
        raise ValueError("manifest reference_rewrites must be a sequence")
    for rewrite in rewrites:
        if not isinstance(rewrite, Mapping) or set(rewrite) != {
            "object_id",
            "pointer",
            "before_id",
            "after_id",
        }:
            raise ValueError("manifest reference rewrite is invalid")
        if not all(
            isinstance(rewrite.get(field_name), str)
            for field_name in (
                "object_id",
                "pointer",
                "before_id",
                "after_id",
            )
        ):
            raise ValueError("manifest reference rewrite values are invalid")
    return [entries[path] for path in sorted(entries)]


def _validated_inventory_entry(
    raw_entry: object,
    *,
    allow_after: bool,
) -> dict[str, object]:
    if not isinstance(raw_entry, Mapping):
        raise ValueError("inventory entry must be an object")
    expected_keys = {"path", "had_before", "before_sha256"}
    if allow_after:
        expected_keys.add("after_sha256")
    if set(raw_entry) != expected_keys:
        raise ValueError("inventory entry keys are invalid")
    path = _validated_relative_path(raw_entry.get("path"))
    had_before = raw_entry.get("had_before")
    before_sha = raw_entry.get("before_sha256")
    if not isinstance(had_before, bool):
        raise ValueError("inventory had_before must be bool")
    _require_hashes(
        before_sha,
        raw_entry.get("after_sha256") if allow_after else None,
        before=had_before,
        after=None,
    )
    entry = {
        "path": path,
        "had_before": had_before,
        "before_sha256": before_sha,
    }
    if allow_after:
        after_sha = raw_entry.get("after_sha256")
        if after_sha is not None and not _is_sha256(after_sha):
            raise ValueError("inventory after_sha256 is invalid")
        entry["after_sha256"] = after_sha
    return entry


def _add_expected_entry(
    entries: dict[str, dict[str, object]],
    path: str,
    before_sha: object,
    after_sha: object,
) -> None:
    if path in entries:
        raise ValueError(f"manifest repeats transaction path: {path}")
    entries[path] = {
        "path": path,
        "had_before": before_sha is not None,
        "before_sha256": before_sha,
        "after_sha256": after_sha,
    }


def _validated_object_id(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("manifest object id must be a non-empty string")
    return value


def _require_hashes(
    before_sha: object,
    after_sha: object,
    *,
    before: bool | None,
    after: bool | None,
) -> None:
    if before is True and not _is_sha256(before_sha):
        raise ValueError("before_sha256 is invalid")
    if before is False and before_sha is not None:
        raise ValueError("before_sha256 must be null")
    if before is None and before_sha is not None and not _is_sha256(before_sha):
        raise ValueError("before_sha256 is invalid")
    if after is True and not _is_sha256(after_sha):
        raise ValueError("after_sha256 is invalid")
    if after is False and after_sha is not None:
        raise ValueError("after_sha256 must be null")
    if after is None and after_sha is not None and not _is_sha256(after_sha):
        raise ValueError("after_sha256 is invalid")


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _validated_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("transaction path must be a non-empty string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(f"transaction path must stay below brain_root: {value}")
    if path.as_posix() != value:
        raise ValueError(f"transaction path is not canonical: {value}")
    return value


def _inject(
    failure_injector: Callable[[str], None] | None,
    point: str,
) -> None:
    if failure_injector is not None:
        failure_injector(point)


def _verify_rolled_back_state(
    anchored: _AnchoredRoot,
    journal: Mapping[str, object],
) -> None:
    manifest = journal.get("manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("journal manifest is invalid")
    actual = _corpus_fingerprint(anchored.path)
    expected = manifest.get("before_fingerprint")
    if actual != expected:
        raise ValueError(
            f"corpus rollback fingerprint mismatch: {actual} != {expected}"
        )
    _verify_inventory(anchored, journal.get("derived"))
    current_derived = [
        anchored.inspect_file(relative_path)
        for relative_path in _DERIVED_PATHS
    ]
    if (
        _inventory_fingerprint(current_derived)
        != journal.get("before_derived_fingerprint")
    ):
        raise ValueError("derived rollback fingerprint mismatch")


def _verify_committed_state(
    anchored: _AnchoredRoot,
    journal: Mapping[str, object],
) -> None:
    manifest = journal.get("manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("journal manifest is invalid")
    actual = _corpus_fingerprint(anchored.path)
    expected = manifest.get("expected_after_fingerprint")
    if actual != expected:
        raise ValueError(
            f"post-commit corpus fingerprint mismatch: {actual} != {expected}"
        )
    for relative_path in _DERIVED_PATHS:
        if anchored.inspect_file(relative_path)["had_before"]:
            raise ValueError(
                f"derived file was not invalidated: {relative_path}"
            )
    current_derived = [
        anchored.inspect_file(relative_path)
        for relative_path in _DERIVED_PATHS
    ]
    if (
        _inventory_fingerprint(current_derived)
        != journal.get("expected_after_derived_fingerprint")
    ):
        raise ValueError("post-commit derived fingerprint mismatch")


def _verify_inventory(
    anchored: _AnchoredRoot,
    raw_entries: object,
) -> None:
    if not isinstance(raw_entries, list):
        raise ValueError("derived recovery inventory is invalid")
    for entry in raw_entries:
        if not isinstance(entry, Mapping):
            raise ValueError("derived recovery entry is invalid")
        relative_path = _validated_relative_path(entry.get("path"))
        actual = anchored.inspect_file(relative_path)
        if entry.get("had_before"):
            before_sha256 = entry.get("before_sha256")
            if (
                not actual["had_before"]
                or not isinstance(before_sha256, str)
                or actual["before_sha256"] != before_sha256
            ):
                raise ValueError(
                    f"{relative_path}: derived rollback fingerprint mismatch"
                )
        elif actual["had_before"]:
            raise ValueError(
                f"{relative_path}: derived file appeared during rollback"
            )


def _corpus_fingerprint(brain_root: Path) -> str:
    from project_brain.store import BrainStore

    store = BrainStore.load_unlocked(brain_root)
    digest = hashlib.sha256()
    objects = {obj["id"]: obj for obj in store.all()}
    for object_id in sorted(objects):
        digest.update(object_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(BrainStore.object_bytes(objects[object_id]))
        digest.update(b"\0")
    return digest.hexdigest()


def _inventory_fingerprint(
    entries: list[dict[str, object]],
) -> str:
    canonical = [
        {
            "path": entry["path"],
            "had_before": entry["had_before"],
            "before_sha256": entry["before_sha256"],
        }
        for entry in sorted(entries, key=lambda item: str(item["path"]))
    ]
    return hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
