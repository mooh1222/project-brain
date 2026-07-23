"""CodeLocator의 opt-in 원문 인용구를 Git blob 바이트에서 확인한다.

심볼 경계나 줄 범위는 확인하지 않는다. ``verified_quote``가 정확히 같은 UTF-8
바이트열로 blob 안에 있는지만 검사한다.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Iterable, Mapping

from project_brain.stale_check import GitError


BlobReader = Callable[[str, str], bytes]


def make_git_blob_reader(repo_root: Path, *, timeout: int = 60) -> BlobReader:
    """``git show <commit>:<path>``의 원시 stdout 바이트를 읽는 리더를 만든다."""
    def read_blob(commit: str, path: str) -> bytes:
        revision = f"{commit}:{path}"
        try:
            result = subprocess.run(
                ["git", "show", revision], capture_output=True,
                cwd=str(repo_root), timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git show {revision} timed out after {timeout}s") from exc
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise GitError(f"git show {revision} failed: {stderr}")
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
