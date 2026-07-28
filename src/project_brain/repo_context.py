"""제품 쓰기에서 사용할 Git repository context."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

_GIT_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class RepoContext:
    repo_root: Path
    expected_repo_id: str
    expected_revision_ref: str
    target_revision_sha: str


@dataclass(frozen=True)
class VerificationFailure:
    locator_id: str
    code: str
    detail: str


class RepoVerificationError(RuntimeError):
    def __init__(self, failure: VerificationFailure):
        self.failure = failure
        super().__init__(f"{failure.code}: {failure.detail}")


def _failure(code: str, detail: str) -> RepoVerificationError:
    return RepoVerificationError(VerificationFailure("", code, detail))


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise _failure("not_git_repo", f"git command failed to start: {exc}") from exc


def _stderr(result: subprocess.CompletedProcess[bytes]) -> str:
    return result.stderr.decode("utf-8", errors="replace").strip()


def _is_shallow(repo_root: Path) -> bool:
    result = _run_git(repo_root, "rev-parse", "--is-shallow-repository")
    return result.returncode == 0 and result.stdout.strip() == b"true"


def resolve_repo_context(
    repo_root: Path,
    *,
    expected_repo_id: str,
    configured_repo_id: str,
    expected_revision_ref: str,
) -> RepoContext:
    root = Path(repo_root)
    if not root.is_absolute():
        raise ValueError("repo_root must be an absolute path")
    if "\x00" in str(root):
        raise _failure("not_git_repo", "repo_root contains a NUL byte")
    try:
        root = root.resolve()
    except (OSError, ValueError) as exc:
        raise _failure("not_git_repo", f"repo_root could not be resolved: {exc}") from exc

    if (
        not isinstance(expected_repo_id, str)
        or not expected_repo_id.strip()
        or not isinstance(configured_repo_id, str)
        or configured_repo_id != expected_repo_id
    ):
        raise _failure(
            "repo_identity_mismatch",
            f"expected repo {expected_repo_id!r}, configured repo {configured_repo_id!r}",
        )

    if not root.is_dir():
        raise _failure("not_git_repo", f"repository root is not a directory: {root}")
    top_result = _run_git(root, "rev-parse", "--show-toplevel")
    if top_result.returncode != 0:
        raise _failure(
            "not_git_repo",
            f"git rev-parse --show-toplevel failed: {_stderr(top_result)}",
        )
    try:
        top_text = top_result.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as exc:
        raise _failure("not_git_repo", f"Git toplevel is not UTF-8: {exc}") from exc
    if not top_text:
        raise _failure("not_git_repo", "git returned an empty repository root")
    actual_root = Path(top_text).resolve()
    if actual_root != root:
        raise _failure(
            "repo_identity_mismatch",
            f"repo_root {root} is not exact Git toplevel {actual_root}",
        )

    if (
        not isinstance(expected_revision_ref, str)
        or not expected_revision_ref.strip()
        or "\x00" in expected_revision_ref
    ):
        raise _failure(
            "commit_missing",
            "expected revision ref must be non-empty and contain no NUL byte",
        )
    revision_result = _run_git(
        root,
        "rev-parse",
        "--verify",
        "--quiet",
        f"{expected_revision_ref}^{{commit}}",
    )
    if revision_result.returncode != 0:
        code = "shallow_or_unfetched" if _is_shallow(root) else "commit_missing"
        raise _failure(
            code,
            f"revision {expected_revision_ref!r} is unavailable: {_stderr(revision_result)}",
        )
    try:
        target_revision_sha = revision_result.stdout.decode(
            "ascii",
            errors="strict",
        ).strip()
    except UnicodeDecodeError as exc:
        raise _failure(
            "commit_missing",
            f"revision {expected_revision_ref!r} did not resolve to an ASCII object id",
        ) from exc
    if not target_revision_sha:
        raise _failure("commit_missing", f"revision {expected_revision_ref!r} resolved empty")

    return RepoContext(
        repo_root=root,
        expected_repo_id=expected_repo_id,
        expected_revision_ref=expected_revision_ref,
        target_revision_sha=target_revision_sha,
    )
