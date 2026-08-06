"""Low-level state receipts used by Task 18 binding producers and verifiers."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from project_brain.foundation import (
    FoundationError,
    capture_corpus_receipt,
    capture_search_index_receipt,
    capture_stale_set_receipt,
)
from project_brain.snapshot import (
    SnapshotError,
    decode_nul_paths,
    git_show_blob,
    ls_remote_exact_commit,
    read_regular_no_follow,
    require_commit_is_ancestor,
    resolve_exact_commit,
    run_git_bytes,
)


class Task18StateError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class RemoteRefReceipt:
    local_ref: str
    local_sha: str
    remote: str
    remote_ref: str
    remote_sha: str


def _from_dependency(exc: SnapshotError | FoundationError) -> Task18StateError:
    return Task18StateError(exc.code, exc.detail)


def capture_cached_paths(root: Path) -> tuple[str, ...]:
    try:
        payload = run_git_bytes(root, "diff", "--cached", "--name-only", "-z")
        return tuple(sorted(decode_nul_paths(payload)))
    except SnapshotError as exc:
        raise _from_dependency(exc) from exc


def capture_remote_ref(
    root: Path,
    *,
    local_ref: str,
    remote: str,
    remote_ref: str,
) -> RemoteRefReceipt:
    try:
        local_sha = resolve_exact_commit(root, local_ref)
        remote_sha = ls_remote_exact_commit(root, remote, remote_ref)
    except SnapshotError as exc:
        raise _from_dependency(exc) from exc
    if local_sha != remote_sha:
        raise Task18StateError(
            "remote_ref_mismatch",
            "local and remote refs do not resolve to the same commit",
        )
    return RemoteRefReceipt(local_ref, local_sha, remote, remote_ref, remote_sha)


def capture_bound_file(path: Path) -> Mapping[str, object]:
    path = Path(path)
    try:
        data, mode = read_regular_no_follow(path)
    except SnapshotError as exc:
        raise _from_dependency(exc) from exc
    return {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "mode": mode,
    }


def capture_task18_corpus_state(brain_root: Path) -> Mapping[str, object]:
    try:
        corpus = capture_corpus_receipt(brain_root)
        search_index = capture_search_index_receipt(brain_root)
        stale_set = capture_stale_set_receipt(brain_root)
    except FoundationError as exc:
        raise _from_dependency(exc) from exc
    return {
        "corpus": corpus,
        "search_index": search_index,
        "stale_set": stale_set,
    }


def capture_committed_input(
    root: Path,
    relative_path: Path,
    commit_sha: str,
) -> Mapping[str, object]:
    root = Path(root)
    relative_path = Path(relative_path)
    pure = PurePosixPath(relative_path.as_posix())
    if (
        relative_path.is_absolute()
        or pure.as_posix() in {"", "."}
        or ".." in pure.parts
    ):
        raise Task18StateError(
            "committed_input_path_invalid",
            "relative_path must be a safe relative path",
        )
    try:
        require_commit_is_ancestor(root, commit_sha, "HEAD")
        committed_bytes = git_show_blob(root, commit_sha, relative_path)
        working_path = root / relative_path
        working_bytes, mode = read_regular_no_follow(working_path)
    except SnapshotError as exc:
        raise _from_dependency(exc) from exc
    if committed_bytes != working_bytes:
        raise Task18StateError(
            "committed_input_bytes_mismatch",
            "working file bytes differ from the committed input",
        )
    return {
        "path": str(working_path),
        "commit_sha": commit_sha,
        "file_sha256": hashlib.sha256(working_bytes).hexdigest(),
        "mode": mode,
    }
