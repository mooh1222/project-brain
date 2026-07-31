"""Corpus-wide lock, durable journal, and rollback-only recovery."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import re
import stat
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

from project_brain.transaction_receipt import (
    BatchBinding,
    batch_binding_dict,
    batch_intent_id,
    normalize_batch_binding,
)


class JournalState(StrEnum):
    PREPARING = "preparing"
    PREPARED = "prepared"
    COMMITTING = "committing"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    RECOVERY_REQUIRED = "recovery_required"


class ReceiptVerificationMode(StrEnum):
    STRICT_COMMIT = "strict_commit"
    POST_GATE_OBJECT_TAIL = "post_gate_object_tail"


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


@dataclass(frozen=True)
class DirectoryBinding:
    path: Path
    parent_device: int
    parent_inode: int
    device: int
    inode: int


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
    "canonical_repair",
}


@dataclass(frozen=True)
class _PinnedDirectory:
    relative_path: str
    fd: int
    device: int
    inode: int


@dataclass(frozen=True)
class _CaseOnlyRenameBinding:
    """Pinned before-image binding for one case-insensitive rename."""

    old_path: str
    new_path: str
    parent: _PinnedDirectory
    old_name: str
    new_name: str
    device: int
    inode: int
    before_sha256: str


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
    blocking: bool = True,
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
        if not blocking:
            lock_mode |= fcntl.LOCK_NB
        try:
            fcntl.flock(lock_fd, lock_mode)
        except OSError as exc:
            if not blocking and exc.errno in (errno.EACCES, errno.EAGAIN):
                raise CorpusIOError(
                    "corpus_lock_busy",
                    "stable corpus lock is already held",
                    paths=(parent / _stable_lock_name(root),),
                ) from exc
            raise
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


def _validated_direct_child_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or name in ("", ".", "..")
        or "/" in name
        or "\0" in name
    ):
        raise ValueError("directory name must identify one direct child")
    return name


def _validated_directory_prefix(prefix: str) -> str:
    if not isinstance(prefix, str) or "/" in prefix or "\0" in prefix:
        raise ValueError("directory prefix must stay within one direct child")
    return prefix


def _validated_directory_mode(mode: int) -> int:
    if (
        not isinstance(mode, int)
        or isinstance(mode, bool)
        or mode < 0
        or mode & ~0o777
    ):
        raise ValueError("directory mode must contain permission bits only")
    return mode


def _open_directory_path(path: Path) -> tuple[int, os.stat_result]:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
    except OSError as exc:
        raise _anchored_path_error(path, exc) from exc
    try:
        directory_stat = os.fstat(descriptor)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor, directory_stat


def _path_binding_changed(binding: DirectoryBinding, detail: str) -> CorpusIOError:
    return CorpusIOError(
        "path_binding_changed",
        detail,
        paths=(binding.path,),
    )


def _open_bound_directory(binding: DirectoryBinding) -> int:
    parent_fd = -1
    child_fd = -1
    try:
        try:
            parent_fd = os.open(
                binding.path.parent,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
        except OSError as exc:
            raise _path_binding_changed(
                binding,
                "bound directory parent is no longer directly reachable",
            ) from exc
        parent_stat = os.fstat(parent_fd)
        if (parent_stat.st_dev, parent_stat.st_ino) != (
            binding.parent_device,
            binding.parent_inode,
        ):
            raise _path_binding_changed(
                binding,
                "bound directory parent was replaced",
            )
        try:
            child_fd = os.open(
                _validated_direct_child_name(binding.path.name),
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except (OSError, ValueError) as exc:
            raise _path_binding_changed(
                binding,
                "bound directory is no longer a direct directory child",
            ) from exc
        child_stat = os.fstat(child_fd)
        if (child_stat.st_dev, child_stat.st_ino) != (
            binding.device,
            binding.inode,
        ):
            raise _path_binding_changed(
                binding,
                "bound directory was replaced",
            )
        result = child_fd
        child_fd = -1
        return result
    finally:
        if child_fd >= 0:
            os.close(child_fd)
        if parent_fd >= 0:
            os.close(parent_fd)


def _existing_child_error(
    parent_fd: int,
    *,
    name: str,
    path: Path,
) -> CorpusIOError:
    try:
        child_stat = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        return CorpusIOError(
            "anchored_io_failed",
            f"existing directory entry disappeared during creation: {path}",
            paths=(path,),
        )
    if stat.S_ISLNK(child_stat.st_mode):
        return CorpusIOError(
            "symlink_forbidden",
            f"directory child is a symlink: {path}",
            paths=(path,),
        )
    if not stat.S_ISDIR(child_stat.st_mode):
        return CorpusIOError(
            "file_type_invalid",
            f"directory child is not a directory: {path}",
            paths=(path,),
        )
    return CorpusIOError(
        "path_already_exists",
        f"directory child already exists: {path}",
        paths=(path,),
    )


def _create_directory_at(
    parent_path: Path,
    parent_fd: int,
    parent_stat: os.stat_result,
    *,
    name: str,
    mode: int,
) -> DirectoryBinding:
    name = _validated_direct_child_name(name)
    mode = _validated_directory_mode(mode)
    path = parent_path / name
    try:
        os.mkdir(name, mode, dir_fd=parent_fd)
    except FileExistsError as exc:
        raise _existing_child_error(
            parent_fd,
            name=name,
            path=path,
        ) from exc
    except OSError as exc:
        raise _anchored_path_error(path, exc) from exc

    child_fd = -1
    try:
        try:
            child_fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise _anchored_path_error(path, exc) from exc
        child_stat = os.fstat(child_fd)
        child_device = _observed_device(os.fspath(path), child_stat.st_dev)
        if child_device != parent_stat.st_dev:
            raise CorpusIOError(
                "filesystem_mismatch",
                f"directory child is on another filesystem: {path}",
                paths=(path,),
            )
        os.fchmod(child_fd, mode)
        child_stat = os.fstat(child_fd)
        if (
            not stat.S_ISDIR(child_stat.st_mode)
            or stat.S_IMODE(child_stat.st_mode) != mode
        ):
            raise CorpusIOError(
                "file_type_invalid",
                f"directory child mode or type is invalid: {path}",
                paths=(path,),
            )
        os.fsync(child_fd)
        os.fsync(parent_fd)
        binding = DirectoryBinding(
            path=path,
            parent_device=parent_stat.st_dev,
            parent_inode=parent_stat.st_ino,
            device=child_stat.st_dev,
            inode=child_stat.st_ino,
        )
    finally:
        if child_fd >= 0:
            os.close(child_fd)
    verify_directory_binding(binding)
    return binding


def create_anchored_temp_directory(
    parent: Path,
    *,
    prefix: str,
    mode: int = 0o700,
) -> DirectoryBinding:
    """Create a unique direct child from one pinned parent directory."""
    parent = Path(parent)
    prefix = _validated_directory_prefix(prefix)
    mode = _validated_directory_mode(mode)
    parent_fd, parent_stat = _open_directory_path(parent)
    try:
        for _attempt in range(100):
            name = f"{prefix}{os.urandom(8).hex()}"
            try:
                return _create_directory_at(
                    parent,
                    parent_fd,
                    parent_stat,
                    name=name,
                    mode=mode,
                )
            except CorpusIOError as exc:
                if exc.code != "path_already_exists":
                    raise
        raise CorpusIOError(
            "temporary_directory_unavailable",
            f"could not allocate a unique directory below {parent}",
            paths=(parent,),
        )
    finally:
        os.close(parent_fd)


def create_anchored_directory(
    parent: DirectoryBinding,
    *,
    name: str,
    mode: int = 0o700,
) -> DirectoryBinding:
    """Create a named direct child from a verified, pinned parent."""
    name = _validated_direct_child_name(name)
    mode = _validated_directory_mode(mode)
    parent_fd = _open_bound_directory(parent)
    try:
        parent_stat = os.fstat(parent_fd)
        return _create_directory_at(
            parent.path,
            parent_fd,
            parent_stat,
            name=name,
            mode=mode,
        )
    finally:
        os.close(parent_fd)


def verify_directory_binding(binding: DirectoryBinding) -> None:
    """Reject a directory whose direct parent or own inode was replaced."""
    descriptor = _open_bound_directory(binding)
    os.close(descriptor)


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


def read_tracked_file_bytes(
    brain_root: Path,
    relative_path: str,
) -> bytes:
    """Read one existing tracked file through the pinned corpus root."""
    active = _CORPUS_LOCK_SCOPE.get()
    if active is None:
        with corpus_lock(brain_root, exclusive=False):
            return read_tracked_file_bytes(brain_root, relative_path)
    scope = _current_lock_scope(brain_root)
    normalized = _validated_relative_path(relative_path)
    inspected = scope.anchored.inspect_file(normalized)
    if not inspected["had_before"]:
        raise CorpusIOError(
            "tracked_file_missing",
            f"tracked file does not exist: {normalized}",
            paths=(Path(scope.brain_root_identity) / normalized,),
        )
    parent, name = scope.anchored.pin_existing_parent(
        normalized,
        create=False,
    )
    payload = _read_bytes_at(parent.fd, name)
    after_read = scope.anchored.inspect_file(normalized)
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if (
        after_read != inspected
        or actual_sha256 != inspected["before_sha256"]
    ):
        raise CorpusIOError(
            "before_hash_mismatch",
            f"tracked file changed while reading: {normalized}",
            paths=(Path(scope.brain_root_identity) / normalized,),
        )
    return payload


def inspect_tracked_file(
    brain_root: Path,
    relative_path: str,
) -> Mapping[str, object]:
    """Inspect one tracked path without following links or reading its bytes."""
    active = _CORPUS_LOCK_SCOPE.get()
    if active is None:
        with corpus_lock(brain_root, exclusive=False):
            return inspect_tracked_file(brain_root, relative_path)
    scope = _current_lock_scope(brain_root)
    return scope.anchored.inspect_file(
        _validated_relative_path(relative_path)
    )


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
    manifest = payload.get("manifest")
    if (
        isinstance(manifest, dict)
        and "batch_binding" not in payload
        and "batch_binding" not in manifest
    ):
        # Read-only compatibility for pre-batch non-batch artifacts. New
        # manifests/journals always write the field explicitly as null.
        payload = dict(payload)
        payload["manifest"] = dict(manifest)
        payload["batch_binding"] = None
        payload["manifest"]["batch_binding"] = None
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
        try:
            os.lstat(restore_state_root(brain_root))
        except FileNotFoundError:
            pass
        else:
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


def batch_intent_relative_path(
    binding: BatchBinding | Mapping[str, object],
) -> Path:
    """Return the stable root-relative intent path for one batch item."""
    return Path(".brain-local") / "batch-intents" / (
        f"{batch_intent_id(binding)}.json"
    )


def _canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _canonical_manifest_bytes(manifest: Mapping[str, object]) -> bytes:
    return _canonical_json_bytes(manifest)


def _batch_intent_payload(
    manifest: Mapping[str, object],
    binding: BatchBinding,
) -> dict[str, object]:
    transaction_id = manifest.get("transaction_id")
    operation = manifest.get("operation")
    engine_sha = manifest.get("engine_sha")
    return {
        "version": 1,
        "intent_id": batch_intent_id(binding),
        "batch_binding": batch_binding_dict(binding),
        "transaction_id": transaction_id,
        "manifest_sha256": hashlib.sha256(
            _canonical_manifest_bytes(manifest)
        ).hexdigest(),
        "operation": operation,
        "engine_sha": engine_sha,
    }


def _publish_batch_intent_anchored(
    anchored: _AnchoredRoot,
    manifest: Mapping[str, object],
    binding: BatchBinding,
) -> None:
    intent = _batch_intent_payload(manifest, binding)
    payload = _canonical_json_bytes(intent)
    intents = anchored.pin_directory(
        ".brain-local/batch-intents",
        create=True,
    )
    name = f"{intent['intent_id']}.json"
    try:
        _write_bytes_at(
            intents.fd,
            name,
            payload,
            replace_existing=False,
        )
    except FileExistsError:
        try:
            existing = _read_bytes_at(intents.fd, name)
        except OSError as exc:
            raise _anchored_path_error(
                anchored.path / batch_intent_relative_path(binding),
                exc,
            ) from exc
        if existing != payload:
            raise CorpusIOError(
                "batch_intent_mismatch",
                "existing batch intent does not match the planned transaction",
                paths=(
                    anchored.path / batch_intent_relative_path(binding),
                ),
            )


def _read_batch_intent_anchored(
    anchored: _AnchoredRoot,
    binding: BatchBinding,
) -> dict[str, object]:
    relative = batch_intent_relative_path(binding)
    try:
        intents = anchored.pin_directory(
            relative.parent.as_posix(),
            create=False,
        )
        raw = _read_bytes_at(intents.fd, relative.name)
    except (FileNotFoundError, OSError, CorpusIOError) as exc:
        raise CorpusIOError(
            "batch_intent_missing",
            f"batch intent is unavailable: {relative}",
            paths=(anchored.path / relative,),
        ) from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CorpusIOError(
            "batch_intent_invalid",
            f"batch intent is not canonical JSON: {exc}",
            paths=(anchored.path / relative,),
        ) from exc
    if not isinstance(value, dict) or _canonical_json_bytes(value) != raw:
        raise CorpusIOError(
            "batch_intent_invalid",
            "batch intent bytes are not canonical",
            paths=(anchored.path / relative,),
        )
    expected_fields = {
        "version",
        "intent_id",
        "batch_binding",
        "transaction_id",
        "manifest_sha256",
        "operation",
        "engine_sha",
    }
    if set(value) != expected_fields or value.get("version") != 1:
        raise CorpusIOError(
            "batch_intent_invalid",
            "batch intent fields do not match the contract",
            paths=(anchored.path / relative,),
        )
    if value.get("intent_id") != batch_intent_id(binding):
        raise CorpusIOError(
            "batch_intent_mismatch",
            "batch intent identity does not match the requested item",
            paths=(anchored.path / relative,),
        )
    try:
        stored_binding = normalize_batch_binding(value.get("batch_binding"))
    except ValueError as exc:
        raise CorpusIOError(
            "batch_intent_invalid",
            str(exc),
            paths=(anchored.path / relative,),
        ) from exc
    if stored_binding != binding:
        raise CorpusIOError(
            "batch_intent_mismatch",
            "batch intent binding does not match the requested item",
            paths=(anchored.path / relative,),
        )
    if (
        not _is_sha256(value.get("transaction_id"))
        or not _is_sha256(value.get("manifest_sha256"))
        or value.get("operation") != "ingest"
        or value.get("engine_sha") != binding.engine_sha
    ):
        raise CorpusIOError(
            "batch_intent_invalid",
            "batch intent transaction fields are invalid",
            paths=(anchored.path / relative,),
        )
    return value


def _manifest_action_object_ids(
    manifest: Mapping[str, object],
) -> list[str]:
    object_ids: set[str] = set()
    for field_name in ("creates", "updates", "deletes"):
        actions = manifest.get(field_name)
        if not isinstance(actions, list):
            raise CorpusIOError(
                "committed_receipt_invalid",
                f"manifest.{field_name} is invalid",
            )
        for action in actions:
            if not isinstance(action, Mapping):
                raise CorpusIOError(
                    "committed_receipt_invalid",
                    f"manifest.{field_name} action is invalid",
                )
            object_id = action.get("object_id")
            if not isinstance(object_id, str) or not object_id:
                raise CorpusIOError(
                    "committed_receipt_invalid",
                    f"manifest.{field_name} object id is invalid",
                )
            object_ids.add(object_id)
    renames = manifest.get("renames")
    if not isinstance(renames, list):
        raise CorpusIOError(
            "committed_receipt_invalid",
            "manifest.renames is invalid",
        )
    for action in renames:
        if not isinstance(action, Mapping):
            raise CorpusIOError(
                "committed_receipt_invalid",
                "manifest rename action is invalid",
            )
        for field_name in ("old_id", "new_id"):
            object_id = action.get(field_name)
            if not isinstance(object_id, str) or not object_id:
                raise CorpusIOError(
                    "committed_receipt_invalid",
                    f"manifest rename {field_name} is invalid",
                )
            object_ids.add(object_id)
    return sorted(object_ids)


def _recover_committed_receipt_anchored(
    anchored: _AnchoredRoot,
    normalized: BatchBinding,
    *,
    expected_receipt: Mapping[str, object] | None,
    verification_mode: ReceiptVerificationMode | None,
) -> dict[str, object]:
    intent = _read_batch_intent_anchored(anchored, normalized)
    transaction_id = str(intent["transaction_id"])
    try:
        transactions = anchored.pin_directory(
            ".brain-local/transactions",
            create=False,
        )
        transaction_fd = _open_directory_at(
            transactions.fd,
            transaction_id,
            create=False,
            expected_device=anchored.device,
        )
    except (FileNotFoundError, OSError, CorpusIOError) as exc:
        raise CorpusIOError(
            "committed_receipt_missing",
            f"{transaction_id}: committed journal is unavailable",
        ) from exc
    try:
        journal = _read_journal_at(transaction_fd, transaction_id)
    finally:
        os.close(transaction_fd)
    if journal.get("state") != JournalState.COMMITTED.value:
        raise CorpusIOError(
            "receipt_not_committed",
            f"{transaction_id}: journal is not COMMITTED",
        )
    if journal.get("batch_binding") != batch_binding_dict(normalized):
        raise CorpusIOError(
            "committed_receipt_invalid",
            f"{transaction_id}: journal batch binding mismatch",
        )
    manifest = journal.get("manifest")
    if not isinstance(manifest, Mapping):
        raise CorpusIOError(
            "committed_receipt_invalid",
            f"{transaction_id}: journal manifest is invalid",
        )
    manifest_sha256 = hashlib.sha256(
        _canonical_manifest_bytes(manifest)
    ).hexdigest()
    if manifest_sha256 != intent.get("manifest_sha256"):
        raise CorpusIOError(
            "committed_receipt_invalid",
            f"{transaction_id}: canonical manifest SHA mismatch",
        )
    if (
        manifest.get("transaction_id") != transaction_id
        or manifest.get("operation") != "ingest"
        or manifest.get("engine_sha") != normalized.engine_sha
        or manifest.get("batch_binding") != batch_binding_dict(normalized)
    ):
        raise CorpusIOError(
            "committed_receipt_invalid",
            f"{transaction_id}: manifest binding mismatch",
        )
    if verification_mode is not None:
        try:
            if verification_mode is ReceiptVerificationMode.STRICT_COMMIT:
                _verify_committed_state(anchored, journal)
            else:
                _verify_post_gate_object_tail(anchored, journal)
        except (CorpusIOError, ValueError) as exc:
            raise CorpusIOError(
                "committed_receipt_state_mismatch",
                f"{transaction_id}: {exc}",
            ) from exc
    object_ids = _manifest_action_object_ids(manifest)
    if not object_ids:
        raise CorpusIOError(
            "committed_receipt_invalid",
            f"{transaction_id}: committed transaction has no object actions",
        )
    receipt: dict[str, object] = {
        "ok": True,
        "transaction_id": transaction_id,
        "operation": "ingest",
        "committed": True,
        "manifest_sha256": manifest_sha256,
        "before_fingerprint": manifest["before_fingerprint"],
        "after_fingerprint": manifest["expected_after_fingerprint"],
        "ingested_ids": object_ids,
        "ingested_count": len(object_ids),
    }
    if expected_receipt is not None and dict(expected_receipt) != receipt:
        raise CorpusIOError(
            "receipt_mismatch",
            f"{transaction_id}: supplied receipt does not match durable state",
        )
    return receipt


def recover_committed_receipts(
    brain_root: Path,
    bindings: Iterable[BatchBinding | Mapping[str, object]],
    *,
    expected_receipts: Iterable[Mapping[str, object] | None],
    verification_mode: ReceiptVerificationMode | str = (
        ReceiptVerificationMode.STRICT_COMMIT
    ),
) -> tuple[dict[str, object] | None, ...]:
    """Verify an ordered batch receipt chain and its current committed tail."""
    try:
        normalized_mode = ReceiptVerificationMode(verification_mode)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "receipt verification_mode must be strict_commit or "
            "post_gate_object_tail"
        ) from exc
    normalized_bindings = tuple(
        normalize_batch_binding(binding)
        for binding in bindings
    )
    if any(binding is None for binding in normalized_bindings):
        raise ValueError("committed receipt bindings cannot contain None")
    expected = tuple(expected_receipts)
    if len(normalized_bindings) != len(expected):
        raise ValueError("receipt bindings and expected receipts length mismatch")
    active = _CORPUS_LOCK_SCOPE.get()
    if active is None:
        with corpus_lock(brain_root, exclusive=False):
            return recover_committed_receipts(
                brain_root,
                tuple(
                    binding
                    for binding in normalized_bindings
                    if binding is not None
                ),
                expected_receipts=expected,
                verification_mode=normalized_mode,
            )
    scope = _current_lock_scope(brain_root)
    scope.verify_lexical_bindings()
    anchored = scope.anchored
    receipts: list[dict[str, object] | None] = []
    missing_seen = False
    for binding, expected_receipt in zip(
        normalized_bindings,
        expected,
    ):
        assert binding is not None
        try:
            receipt = _recover_committed_receipt_anchored(
                anchored,
                binding,
                expected_receipt=expected_receipt,
                verification_mode=None,
            )
        except CorpusIOError as exc:
            if (
                expected_receipt is None
                and exc.code in {
                    "batch_intent_missing",
                    "committed_receipt_missing",
                    "receipt_not_committed",
                }
            ):
                receipt = None
            else:
                raise
        if receipt is None:
            missing_seen = True
        elif missing_seen:
            raise CorpusIOError(
                "committed_receipt_gap",
                "a committed batch receipt appears after a missing item",
            )
        receipts.append(receipt)
    committed = [
        receipt
        for receipt in receipts
        if receipt is not None
    ]
    for previous, current in zip(committed, committed[1:]):
        if previous["after_fingerprint"] != current["before_fingerprint"]:
            raise CorpusIOError(
                "committed_receipt_chain_mismatch",
                "batch receipt before/after fingerprints do not form a chain",
            )
    if committed:
        tail_index = max(
            index
            for index, receipt in enumerate(receipts)
            if receipt is not None
        )
        tail_binding = normalized_bindings[tail_index]
        assert tail_binding is not None
        _recover_committed_receipt_anchored(
            anchored,
            tail_binding,
            expected_receipt=committed[-1],
            verification_mode=normalized_mode,
        )
    return tuple(receipts)


def recover_committed_receipt(
    brain_root: Path,
    binding: BatchBinding | Mapping[str, object],
    *,
    expected_receipt: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Recover and verify the exact receipt for one durably committed item."""
    normalized = normalize_batch_binding(binding)
    assert normalized is not None
    active = _CORPUS_LOCK_SCOPE.get()
    if active is None:
        with corpus_lock(brain_root, exclusive=False):
            return recover_committed_receipt(
                brain_root,
                normalized,
                expected_receipt=expected_receipt,
            )
    scope = _current_lock_scope(brain_root)
    scope.verify_lexical_bindings()
    return _recover_committed_receipt_anchored(
        scope.anchored,
        normalized,
        expected_receipt=expected_receipt,
        verification_mode=ReceiptVerificationMode.STRICT_COMMIT,
    )


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
            batch_binding = normalize_batch_binding(
                manifest.get("batch_binding")
            )
            entries, case_only_bindings = _build_entries_anchored(
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
                "batch_binding": batch_binding_dict(batch_binding),
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
            if batch_binding is not None:
                _publish_batch_intent_anchored(
                    anchored,
                    manifest,
                    batch_binding,
                )
                _inject(
                    failure_injector,
                    "after_batch_intent_fsync",
                )
                scope.verify_lexical_bindings()

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
            _revalidate_case_only_renames(anchored, case_only_bindings)

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
            _revalidate_case_only_renames(anchored, case_only_bindings)
            case_only_by_old_path = {
                binding.old_path: binding
                for binding in case_only_bindings
            }
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
                binding = case_only_by_old_path.get(str(entry["path"]))
                if binding is not None:
                    _revalidate_case_only_renames(anchored, (binding,))
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
            if batch_binding is not None:
                _inject(
                    failure_injector,
                    "after_journal_committed",
                )
    except CorpusIOError as exc:
        if (
            exc.code not in {
                "path_binding_changed",
                "batch_intent_mismatch",
            }
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
                    f"pre-commit validation failure failed: {rollback_exc}"
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


def _exact_names_at(parent_fd: int) -> tuple[str, ...]:
    """Return literal directory entries without resolving lookup aliases."""
    return tuple(sorted(os.listdir(parent_fd)))


def _exact_name_exists_at(parent_fd: int, name: str) -> bool:
    """Check the literal directory entry, never the filesystem lookup alias."""
    return name in _exact_names_at(parent_fd)


def _casefolded_entry_name(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def _case_only_rename_paths(
    manifest: Mapping[str, object],
) -> tuple[tuple[str, str], ...]:
    """Return manifest rename pairs whose leaves differ only by APFS folding."""
    renames = manifest.get("renames")
    if not isinstance(renames, (list, tuple)):
        return ()
    pairs: list[tuple[str, str]] = []
    for action in renames:
        if not isinstance(action, Mapping):
            continue
        old_path = action.get("old_path")
        new_path = action.get("new_path")
        if not isinstance(old_path, str) or not isinstance(new_path, str):
            continue
        old = PurePosixPath(old_path)
        new = PurePosixPath(new_path)
        if (
            old.parent == new.parent
            and old.name != new.name
            and _casefolded_entry_name(old.name)
            == _casefolded_entry_name(new.name)
        ):
            pairs.append((old_path, new_path))
    return tuple(pairs)


def _inspect_case_only_renames(
    anchored: _AnchoredRoot,
    manifest: Mapping[str, object],
) -> tuple[_CaseOnlyRenameBinding, ...]:
    """Bind only valid APFS lookup aliases as one before-image.

    The manifest stays a pair of ordinary paths.  This private binding merely
    records that the volume currently resolves those two spellings to one
    literal old directory entry.
    """
    actions = manifest.get("renames")
    if not isinstance(actions, (list, tuple)):
        return ()
    bindings: list[_CaseOnlyRenameBinding] = []
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        old_path = action.get("old_path")
        new_path = action.get("new_path")
        before_sha = action.get("before_sha256")
        if not (
            isinstance(old_path, str)
            and isinstance(new_path, str)
            and isinstance(before_sha, str)
        ):
            continue
        old = PurePosixPath(old_path)
        new = PurePosixPath(new_path)
        if (
            old.parent != new.parent
            or old.name == new.name
            or _casefolded_entry_name(old.name)
            != _casefolded_entry_name(new.name)
        ):
            continue
        parent, old_name = anchored.pin_existing_parent(old_path, create=False)
        new_name = new.name
        old_stat = _file_stat_at(parent.fd, old_name)
        new_stat = _file_stat_at(parent.fd, new_name)
        # This is an ordinary case-sensitive rename when the new spelling is
        # genuinely absent; preserve its existing path unchanged.
        if new_stat is None:
            continue
        if old_stat is None:
            raise CorpusIOError(
                "case_only_rename_invalid",
                f"{old_path}: old entry is absent",
            )
        if (old_stat.st_dev, old_stat.st_ino) != (
            new_stat.st_dev,
            new_stat.st_ino,
        ):
            raise CorpusIOError(
                "case_only_rename_collision",
                f"{old_path}: old and new spellings resolve differently",
            )
        if not _exact_name_exists_at(parent.fd, old_name):
            raise CorpusIOError(
                "case_only_rename_invalid",
                f"{old_path}: old exact directory entry is absent",
            )
        if _exact_name_exists_at(parent.fd, new_name):
            raise CorpusIOError(
                "case_only_rename_collision",
                f"{new_path}: new exact directory entry already exists",
            )
        equivalent = [
            name
            for name in _exact_names_at(parent.fd)
            if _casefolded_entry_name(name) == _casefolded_entry_name(old_name)
        ]
        if equivalent != [old_name]:
            raise CorpusIOError(
                "case_only_rename_ambiguous",
                f"{old_path}: normalization-equivalent entries are ambiguous",
            )
        if old_stat.st_nlink != 1:
            raise CorpusIOError(
                "case_only_rename_ambiguous",
                f"{old_path}: hard-linked before image is ambiguous",
            )
        if _observed_device(old_path, old_stat.st_dev) != anchored.device:
            raise CorpusIOError(
                "filesystem_mismatch",
                f"{old_path}: live file is on another filesystem",
            )
        actual_sha = _sha256_at(parent.fd, old_name)
        if actual_sha != before_sha:
            raise CorpusIOError(
                "before_hash_mismatch",
                f"{old_path}: before hash changed between plan and apply",
            )
        bindings.append(
            _CaseOnlyRenameBinding(
                old_path=old_path,
                new_path=new_path,
                parent=parent,
                old_name=old_name,
                new_name=new_name,
                device=old_stat.st_dev,
                inode=old_stat.st_ino,
                before_sha256=before_sha,
            )
        )
    return tuple(bindings)


def _revalidate_case_only_renames(
    anchored: _AnchoredRoot,
    bindings: Iterable[_CaseOnlyRenameBinding],
) -> None:
    for binding in bindings:
        anchored.verify_binding(binding.parent)
        if not _exact_name_exists_at(binding.parent.fd, binding.old_name):
            raise CorpusIOError(
                "path_binding_changed",
                f"{binding.old_path}: old exact directory entry changed",
            )
        if _exact_name_exists_at(binding.parent.fd, binding.new_name):
            raise CorpusIOError(
                "case_only_rename_collision",
                f"{binding.new_path}: new exact directory entry appeared",
            )
        old_stat = _file_stat_at(binding.parent.fd, binding.old_name)
        new_stat = _file_stat_at(binding.parent.fd, binding.new_name)
        if old_stat is None or new_stat is None or (
            old_stat.st_dev,
            old_stat.st_ino,
            old_stat.st_nlink,
        ) != (binding.device, binding.inode, 1) or (
            new_stat.st_dev,
            new_stat.st_ino,
        ) != (binding.device, binding.inode):
            raise CorpusIOError(
                "path_binding_changed",
                f"{binding.old_path}: case-only binding changed",
            )
        if _sha256_at(binding.parent.fd, binding.old_name) != binding.before_sha256:
            raise CorpusIOError(
                "before_hash_mismatch",
                f"{binding.old_path}: before image changed while preparing",
            )


def _build_entries_anchored(
    anchored: _AnchoredRoot,
    manifest: Mapping[str, object],
    after_files: Mapping[str, bytes],
) -> tuple[list[dict[str, object]], tuple[_CaseOnlyRenameBinding, ...]]:
    expected = _validate_manifest_model(
        manifest,
        str(manifest["transaction_id"]),
    )
    case_only_bindings = _inspect_case_only_renames(anchored, manifest)
    case_only_new_paths = {binding.new_path for binding in case_only_bindings}
    entries: list[dict[str, object]] = []
    for expected_entry in expected:
        if str(expected_entry["path"]) in case_only_new_paths:
            entry = {
                "path": str(expected_entry["path"]),
                "had_before": False,
                "before_sha256": None,
            }
        else:
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
    return entries, case_only_bindings


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

    # On a case-insensitive volume the old spelling becomes a lookup alias
    # for the restored new file.  Remove the literal new entry before any
    # old before-image is put back, otherwise the generic absent-entry pass
    # can unlink the restored old file through that alias.
    case_only_new_paths = {
        new_path
        for _old_path, new_path in _case_only_rename_paths(
            journal["manifest"]
        )
    }
    for relative_path in sorted(case_only_new_paths):
        live_parent, live_name = live_parents[relative_path]
        anchored.verify_binding(live_parent)
        if _exact_name_exists_at(live_parent.fd, live_name):
            os.unlink(live_name, dir_fd=live_parent.fd)
            os.fsync(live_parent.fd)

    for entry in (*entries, *derived):
        relative_path = str(entry["path"])
        live_parent, live_name = live_parents[relative_path]
        anchored.verify_binding(live_parent)
        live_stat = _file_stat_at(live_parent.fd, live_name)
        if not entry["had_before"]:
            if relative_path in case_only_new_paths:
                continue
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
    required_fields = {
        "version",
        "transaction_id",
        "state",
        "manifest",
        "entries",
        "derived",
        "before_derived_fingerprint",
        "expected_after_derived_fingerprint",
        "applied",
        "batch_binding",
    }
    if (
        not required_fields.issubset(journal)
        or set(journal) - required_fields - {"recovery_error"}
    ):
        raise ValueError("journal keys do not match the contract")
    if journal.get("version") != 1:
        raise ValueError("version must be 1")
    if _SHA256.fullmatch(transaction_id) is None:
        raise ValueError("transaction_id must be a lowercase SHA-256")
    state = JournalState(journal.get("state"))
    manifest = journal.get("manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("manifest must be an object")
    if "batch_binding" not in journal:
        raise ValueError("journal batch_binding field is missing")
    expected_entries = _validate_manifest_model(manifest, transaction_id)
    try:
        manifest_binding = normalize_batch_binding(
            manifest.get("batch_binding")
        )
        journal_binding = normalize_batch_binding(
            journal.get("batch_binding")
        )
    except ValueError as exc:
        raise ValueError(f"batch binding is invalid: {exc}") from exc
    if journal_binding != manifest_binding:
        raise ValueError("journal batch binding does not match manifest")

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
        "auxiliary_updates",
        "before_fingerprint",
        "expected_after_fingerprint",
        "grandfathered_problems_before",
        "grandfathered_problems_after",
        "batch_binding",
        "canonical_repair_binding",
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
    try:
        batch_binding = normalize_batch_binding(
            manifest.get("batch_binding")
        )
    except ValueError as exc:
        raise ValueError(f"manifest batch_binding is invalid: {exc}") from exc
    if batch_binding is not None:
        if manifest.get("operation") != "ingest":
            raise ValueError("manifest batch_binding requires ingest operation")
        if batch_binding.engine_sha != manifest.get("engine_sha"):
            raise ValueError("manifest batch_binding engine_sha mismatch")
    canonical_repair_binding = manifest.get("canonical_repair_binding")
    if manifest.get("operation") == "canonical_repair":
        if (
            not isinstance(canonical_repair_binding, Mapping)
            or set(canonical_repair_binding) != {
                "decision_ledger_sha256",
                "phase_a_classification_sha256",
            }
            or not all(
                _is_sha256(value)
                for value in canonical_repair_binding.values()
            )
        ):
            raise ValueError(
                "manifest canonical_repair_binding is invalid"
            )
    elif canonical_repair_binding is not None:
        raise ValueError(
            "manifest canonical_repair_binding requires canonical_repair operation"
        )
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

    auxiliary_updates = manifest.get("auxiliary_updates")
    if not isinstance(auxiliary_updates, (list, tuple)):
        raise ValueError("manifest auxiliary_updates must be a sequence")
    if auxiliary_updates and manifest.get("operation") != "id_only_migration":
        raise ValueError(
            "auxiliary updates are allowed only for id_only_migration"
        )
    for action in auxiliary_updates:
        if not isinstance(action, Mapping) or set(action) != {
            "path",
            "before_sha256",
            "after_sha256",
        }:
            raise ValueError("manifest auxiliary update is invalid")
        path = _validated_relative_path(action.get("path"))
        if path != "eval_scenarios.json":
            raise ValueError("manifest auxiliary update path is invalid")
        before_sha = action.get("before_sha256")
        after_sha = action.get("after_sha256")
        _require_hashes(
            before_sha,
            after_sha,
            before=True,
            after=True,
        )
        if before_sha == after_sha:
            raise ValueError(
                "manifest auxiliary update must change content"
            )
        _add_expected_entry(entries, path, before_sha, after_sha)
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
    _verify_entry_state(
        anchored,
        journal.get("entries"),
        after=False,
        exact_paths=_case_only_paths_from_journal(journal),
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


def _verify_post_gate_object_tail(
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
            f"post-gate corpus fingerprint mismatch: {actual} != {expected}"
        )
    _verify_entry_state(
        anchored,
        journal.get("entries"),
        after=True,
        exact_paths=_case_only_paths_from_journal(journal),
    )


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
    _verify_entry_state(
        anchored,
        journal.get("entries"),
        after=True,
        exact_paths=_case_only_paths_from_journal(journal),
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


def _verify_entry_state(
    anchored: _AnchoredRoot,
    raw_entries: object,
    *,
    after: bool,
    exact_paths: set[str] | None = None,
) -> None:
    if not isinstance(raw_entries, list):
        raise ValueError("transaction entry inventory is invalid")
    for entry in raw_entries:
        if not isinstance(entry, Mapping):
            raise ValueError("transaction entry is invalid")
        relative_path = _validated_relative_path(entry.get("path"))
        expected_sha = entry.get(
            "after_sha256" if after else "before_sha256"
        )
        if exact_paths is not None and relative_path in exact_paths:
            parent, name = anchored.pin_existing_parent(
                relative_path,
                create=False,
            )
            exact_exists = _exact_name_exists_at(parent.fd, name)
            expected_sha = entry.get(
                "after_sha256" if after else "before_sha256"
            )
            if expected_sha is None:
                if exact_exists:
                    raise ValueError(
                        f"{relative_path}: unexpected transaction file exists"
                    )
                continue
            if (
                not exact_exists
                or _sha256_at(parent.fd, name) != expected_sha
            ):
                state = "after" if after else "before"
                raise ValueError(
                    f"{relative_path}: transaction {state} hash mismatch"
                )
            continue
        actual = anchored.inspect_file(relative_path)
        if expected_sha is None:
            if actual["had_before"]:
                raise ValueError(
                    f"{relative_path}: unexpected transaction file exists"
                )
            continue
        if (
            not actual["had_before"]
            or actual["before_sha256"] != expected_sha
        ):
            state = "after" if after else "before"
            raise ValueError(
                f"{relative_path}: transaction {state} hash mismatch"
            )


def _case_only_paths_from_journal(journal: Mapping[str, object]) -> set[str]:
    manifest = journal.get("manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError("journal manifest is invalid")
    return {
        path
        for pair in _case_only_rename_paths(manifest)
        for path in pair
    }


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
