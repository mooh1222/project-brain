"""CodeLocator의 Git blob quote와 symbol 관계를 확인한다.

신규 쓰기는 :func:`verify_locator_for_write`로 repository identity, commit reachability,
full blob quote byte range, C/C++ AST symbol 관계를 한 번에 검증한다. 기존 audit의
opt-in quote 검사 API는 :func:`verify_code_quotes`로 유지한다.
"""
from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from pathlib import PurePosixPath
from typing import Callable, Iterable

from project_brain.objbase import now_kst
from project_brain.repo_context import RepoContext, VerificationFailure
from project_brain.stale_check import GitError
from project_brain.symbol_verify import SymbolStatus, verify_symbol_relation


BlobReader = Callable[[str, str], bytes]
_COMMIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_MANUAL_SYMBOL_FIELDS = frozenset({
    "reviewer",
    "repo",
    "commit",
    "path",
    "symbol",
    "quote_sha256",
    "rationale",
})


@dataclass(frozen=True)
class VerifiedLocator:
    locator: dict
    quote_sha256: str
    verified_at: str
    symbol_status: str


class CodeVerificationError(RuntimeError):
    def __init__(self, failure: VerificationFailure):
        self.failure = failure
        super().__init__(f"{failure.code}: {failure.detail}")


def _verification_error(locator_id: str, code: str, detail: str) -> CodeVerificationError:
    return CodeVerificationError(VerificationFailure(locator_id, code, detail))


def _run_locator_git(
    locator_id: str,
    repo_root: Path,
    *args: str,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            timeout=60,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise _verification_error(
            locator_id,
            "blob_read_failed",
            f"git command failed: {exc}",
        ) from exc


def _git_stderr(result: subprocess.CompletedProcess[bytes]) -> str:
    return result.stderr.decode("utf-8", errors="replace").strip()


def _repo_is_shallow(locator_id: str, repo_root: Path) -> bool:
    result = _run_locator_git(
        locator_id,
        repo_root,
        "rev-parse",
        "--is-shallow-repository",
    )
    return result.returncode == 0 and result.stdout.strip() == b"true"


def verify_locator_for_write(
    locator: Mapping[str, object],
    *,
    repo: RepoContext,
    manual_symbol_verification: Mapping[str, object] | None = None,
) -> VerifiedLocator:
    locator_id = str(locator.get("id", ""))
    locator_repo = locator.get("repo")
    if locator_repo != repo.expected_repo_id:
        raise _verification_error(
            locator_id,
            "repo_identity_mismatch",
            f"locator repo {locator_repo!r} does not match {repo.expected_repo_id!r}",
        )

    commit = locator.get("commit_sha")
    if not isinstance(commit, str) or _COMMIT_SHA.fullmatch(commit) is None:
        raise _verification_error(
            locator_id,
            "commit_missing",
            f"locator commit_sha is not an exact hexadecimal SHA: {commit!r}",
        )
    commit_result = _run_locator_git(
        locator_id,
        repo.repo_root,
        "rev-parse",
        "--verify",
        "--quiet",
        f"{commit}^{{commit}}",
    )
    if commit_result.returncode != 0:
        code = (
            "shallow_or_unfetched"
            if _repo_is_shallow(locator_id, repo.repo_root)
            else "commit_missing"
        )
        raise _verification_error(
            locator_id,
            code,
            f"commit {commit} is unavailable: {_git_stderr(commit_result)}",
        )
    resolved_commit = commit_result.stdout.decode("ascii", errors="replace").strip()
    if resolved_commit != commit:
        raise _verification_error(
            locator_id,
            "commit_missing",
            f"commit_sha must be the full object id {resolved_commit}, got {commit}",
        )

    reachable_result = _run_locator_git(
        locator_id,
        repo.repo_root,
        "merge-base",
        "--is-ancestor",
        commit,
        repo.target_revision_sha,
    )
    if reachable_result.returncode == 1:
        code = (
            "shallow_or_unfetched"
            if _repo_is_shallow(locator_id, repo.repo_root)
            else "commit_not_reachable"
        )
        raise _verification_error(
            locator_id,
            code,
            f"commit {commit} is not reachable from {repo.target_revision_sha}",
        )
    if reachable_result.returncode != 0:
        raise _verification_error(
            locator_id,
            "commit_missing",
            "merge-base failed before reachability could be established "
            f"(exit={reachable_result.returncode}): {_git_stderr(reachable_result)}",
        )

    path = locator.get("path")
    if (
        not isinstance(path, str)
        or not path
        or "\x00" in path
        or PurePosixPath(path).is_absolute()
        or ".." in PurePosixPath(path).parts
    ):
        raise _verification_error(
            locator_id,
            "path_missing_at_commit",
            f"locator path is not a repository-relative path: {path!r}",
        )
    revision = f"{commit}:{path}"
    path_result = _run_locator_git(
        locator_id,
        repo.repo_root,
        "cat-file",
        "-e",
        revision,
    )
    if path_result.returncode != 0:
        raise _verification_error(
            locator_id,
            "path_missing_at_commit",
            f"path {path!r} is missing at commit {commit}: {_git_stderr(path_result)}",
        )
    type_result = _run_locator_git(
        locator_id,
        repo.repo_root,
        "cat-file",
        "-t",
        revision,
    )
    object_type = type_result.stdout.decode("ascii", errors="replace").strip()
    if type_result.returncode != 0 or object_type != "blob":
        raise _verification_error(
            locator_id,
            "blob_read_failed",
            f"{revision} is not a blob (type={object_type!r}): {_git_stderr(type_result)}",
        )
    blob_result = _run_locator_git(
        locator_id,
        repo.repo_root,
        "cat-file",
        "blob",
        revision,
    )
    if blob_result.returncode != 0:
        raise _verification_error(
            locator_id,
            "blob_read_failed",
            f"could not read blob {revision}: {_git_stderr(blob_result)}",
        )
    blob = blob_result.stdout

    quote = locator.get("verified_quote")
    if not isinstance(quote, str) or not quote:
        raise _verification_error(
            locator_id,
            "quote_not_found",
            "verified_quote must be a non-empty string",
        )
    try:
        quote_bytes = quote.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _verification_error(
            locator_id,
            "quote_not_found",
            f"verified_quote is not valid UTF-8 text: {exc}",
        ) from exc
    quote_offsets = _find_all(blob, quote_bytes)
    if not quote_offsets:
        raise _verification_error(
            locator_id,
            "quote_not_found",
            f"verified_quote is absent from {revision}",
        )

    symbol = locator.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        raise _verification_error(
            locator_id,
            "symbol_mismatch",
            "symbol must be a non-empty string",
        )
    symbol_results = [
        verify_symbol_relation(
            path=path,
            blob=blob,
            quote_start=start,
            quote_end=start + len(quote_bytes),
            symbol=symbol,
        )
        for start in quote_offsets
    ]
    verified = next(
        (result for result in symbol_results if result.status is SymbolStatus.VERIFIED),
        None,
    )
    quote_hash = sha256(quote_bytes).hexdigest()
    symbol_status: SymbolStatus
    if verified is not None:
        symbol_status = SymbolStatus.VERIFIED
    elif any(result.status is SymbolStatus.MISMATCH for result in symbol_results):
        evidence = "; ".join(result.evidence for result in symbol_results)
        raise _verification_error(locator_id, "symbol_mismatch", evidence)
    elif manual_symbol_evidence_matches(
        manual_symbol_verification,
        repo_id=repo.expected_repo_id,
        commit=commit,
        path=path,
        symbol=symbol,
        quote_hash=quote_hash,
    ):
        symbol_status = SymbolStatus.MANUAL_VERIFIED
    else:
        evidence = "; ".join(result.evidence for result in symbol_results)
        raise _verification_error(
            locator_id,
            "symbol_verification_missing",
            evidence or "structured manual symbol verification is required",
        )

    verified_at = now_kst()
    verified_locator = dict(locator)
    verified_locator["verified_at"] = verified_at
    return VerifiedLocator(
        locator=verified_locator,
        quote_sha256=quote_hash,
        verified_at=verified_at,
        symbol_status=symbol_status.value,
    )


def _find_all(blob: bytes, quote: bytes) -> tuple[int, ...]:
    offsets: list[int] = []
    start = 0
    while True:
        found = blob.find(quote, start)
        if found < 0:
            return tuple(offsets)
        offsets.append(found)
        start = found + 1


def manual_symbol_evidence_matches(
    evidence: Mapping[str, object] | None,
    *,
    repo_id: str,
    commit: str,
    path: str,
    symbol: str,
    quote_hash: str,
) -> bool:
    if not isinstance(evidence, Mapping):
        return False
    if any(field not in evidence for field in _MANUAL_SYMBOL_FIELDS):
        return False
    if any(
        not isinstance(evidence[field], str) or not evidence[field].strip()
        for field in _MANUAL_SYMBOL_FIELDS
    ):
        return False
    expected = {
        "repo": repo_id,
        "commit": commit,
        "path": path,
        "symbol": symbol,
        "quote_sha256": quote_hash,
    }
    return all(evidence[field] == value for field, value in expected.items())


def make_git_blob_reader(repo_root: Path, *, timeout: int = 60) -> BlobReader:
    """``git cat-file blob <commit>:<path>``의 원시 stdout 바이트를 읽는다."""
    def read_blob(commit: str, path: str) -> bytes:
        revision = f"{commit}:{path}"
        try:
            result = subprocess.run(
                ["git", "cat-file", "blob", revision], capture_output=True,
                cwd=str(repo_root), timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git cat-file blob {revision} timed out after {timeout}s") from exc
        except OSError as exc:
            raise GitError(f"git cat-file blob {revision} could not start: {exc}") from exc
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise GitError(f"git cat-file blob {revision} failed: {stderr}")
        return result.stdout
    return read_blob


def _locator_id(locator: Mapping) -> str:
    return str(locator.get("id", ""))


def _failure(locator: Mapping, reason: str, *, error: str | None = None) -> dict:
    failure = {"locator_id": locator.get("id"), "reason": reason}
    if error is not None:
        failure["error"] = error
    return failure


def verify_code_quotes(
    locators: Iterable[Mapping], *, blob_reader: BlobReader,
) -> dict:
    """``verified_quote``가 있는 locator만 원시 Git blob에서 정확히 확인한다.

    필드가 없으면 기존 locator라서 건너뛴다. 필드는 있지만 빈 문자열 또는 문자열이
    아니면 검증 실패다. 실패와 입력 순서는 ID 기준으로 고정한다.
    """
    checked = 0
    skipped = 0
    failures = []
    for locator in sorted(locators, key=_locator_id):
        if "verified_quote" not in locator:
            skipped += 1
            continue

        checked += 1
        quote = locator["verified_quote"]
        if not isinstance(quote, str) or not quote:
            failures.append(_failure(locator, "invalid_verified_quote"))
            continue

        commit = locator.get("commit_sha")
        if commit is None or commit == "":
            failures.append(_failure(locator, "missing_commit"))
            continue
        if not isinstance(commit, str):
            failures.append(_failure(locator, "invalid_commit"))
            continue

        path = locator.get("path")
        if path is None or path == "":
            failures.append(_failure(locator, "missing_path"))
            continue
        if not isinstance(path, str):
            failures.append(_failure(locator, "invalid_path"))
            continue

        try:
            blob = blob_reader(commit, path)
            if not isinstance(blob, bytes):
                raise TypeError("blob reader must return bytes")
        except Exception as exc:
            failures.append(_failure(locator, "blob_read_failed", error=str(exc)))
            continue
        if quote.encode("utf-8") not in blob:
            failures.append(_failure(locator, "quote_not_found"))

    return {"ok": not failures, "checked": checked, "skipped": skipped,
            "failures": failures}
