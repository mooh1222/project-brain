"""사건·시간 사실·코드 위치 candidate의 전용 verification 검사."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from project_brain.hash_utils import sha256_text, stable_json
from project_brain.repo_context import RepoContext, resolve_git_checkout
from project_brain.store import BrainStore


def _timezone_aware(value: object) -> bool:
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def code_checkout_evidence_row(
    subject: Mapping[str, object],
    repo_context: RepoContext | None,
) -> dict[str, object]:
    """현재 checkout의 실제 identity와 HEAD를 직접 근거 한 행으로 만든다."""
    binding = None
    if repo_context is not None:
        try:
            checkout = resolve_git_checkout(repo_context.repo_root)
        except (OSError, RuntimeError, ValueError):
            checkout = None
        if checkout is not None:
            binding = {
                "repo": repo_context.expected_repo_id,
                "expected_revision_ref": repo_context.expected_revision_ref,
                "target_revision_sha": repo_context.target_revision_sha,
                "checkout_head_sha": checkout.head_sha,
                "checkout_device": checkout.device,
                "checkout_inode": checkout.inode,
                "locator_commit_sha": subject.get("commit_sha"),
            }
    return {
        "pointer": "/current_checkout",
        "object_id": None,
        "content_sha256": (
            sha256_text(stable_json(binding)) if binding is not None else None
        ),
    }


def dedicated_engine_checks(
    subject: Mapping[str, object],
    store: BrainStore,
    *,
    repo_context: RepoContext | None = None,
) -> dict[str, tuple[bool, str]]:
    """지원 kind의 engine 전용 검사 결과를 check ID별로 반환한다."""
    kind = subject.get("kind")
    if kind == "EventLedgerRecord":
        return {
            "event.occurred-at-valid": (
                _timezone_aware(subject.get("happened_at")),
                "사건 발생 시각이 timezone-aware ISO 8601이다.",
            ),
        }
    if kind == "TemporalFact":
        event_id = subject.get("derived_from_event_id")
        event_linked = bool(
            isinstance(event_id, str)
            and store.has(event_id)
            and store.get(event_id).get("kind") == "EventLedgerRecord"
            and store.get(event_id).get("status") in {"reviewed", "superseded"}
        )
        supersedes = subject.get("supersedes")
        supersession_valid = supersedes is None
        if isinstance(supersedes, str) and supersedes != subject.get("id"):
            previous = store.get(supersedes) if store.has(supersedes) else None
            supersession_valid = bool(
                previous is not None
                and previous.get("kind") == "TemporalFact"
                and all(
                    previous.get(field) == subject.get(field)
                    for field in ("subject", "predicate", "scope")
                )
            )
        return {
            "fact.event-linked": (
                event_linked,
                "원인 사건이 현재 store의 검수된 EventLedgerRecord로 연결된다.",
            ),
            "fact.supersession-valid": (
                supersession_valid,
                "대체 대상이 없거나 같은 사실 축의 기존 TemporalFact다.",
            ),
        }
    if kind == "CodeLocator":
        return _code_checks(subject, repo_context)
    return {}


def _code_checks(
    subject: Mapping[str, object],
    repo_context: RepoContext | None,
) -> dict[str, tuple[bool, str]]:
    from project_brain.code_verify import (
        CodeVerificationError,
        verify_locator_for_write,
    )

    checks = {
        "code.locator-resolves": False,
        "code.quote-matches": False,
        "code.revision-bound": False,
    }
    summaries = {
        "code.locator-resolves": "repo·path·symbol locator가 현재 checkout에서 해석된다.",
        "code.quote-matches": "verified_quote가 결속된 Git blob과 정확히 일치한다.",
        "code.revision-bound": "locator commit과 현재 checkout revision이 정확히 결속된다.",
    }
    if repo_context is None:
        return {check_id: (False, summary) for check_id, summary in summaries.items()}

    try:
        checkout = resolve_git_checkout(repo_context.repo_root)
    except (OSError, RuntimeError, ValueError):
        checkout = None
    revision_bound = bool(
        checkout is not None
        and checkout.root == repo_context.repo_root
        and checkout.head_sha == repo_context.target_revision_sha
        and subject.get("commit_sha") == repo_context.target_revision_sha
    )
    checks["code.revision-bound"] = revision_bound
    try:
        verify_locator_for_write(
            subject,
            repo=repo_context,
            manual_symbol_verification=(
                subject.get("manual_symbol_verification")
                if isinstance(subject.get("manual_symbol_verification"), Mapping)
                else None
            ),
        )
    except CodeVerificationError as exc:
        code = exc.failure.code
        if code in {"quote_not_found", "quote_invalid"}:
            checks["code.locator-resolves"] = True
        elif code in {"symbol_mismatch", "symbol_verification_missing"}:
            checks["code.quote-matches"] = True
    else:
        checks["code.locator-resolves"] = True
        checks["code.quote-matches"] = True
    return {
        check_id: (checks[check_id], summaries[check_id])
        for check_id in sorted(checks)
    }
