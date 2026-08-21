"""공통 candidate verification envelope와 현재 상태 계산.

저장된 ready 플래그를 신뢰하지 않고 candidate, 현재 store, versioned profile을
함께 대조한다. 첫 profile은 EvidenceRef이며 이후 kind profile도 이 모듈에 붙인다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from project_brain.capabilities import (
    CAPABILITY_REGISTRY,
    ManualPromotionPolicy,
)
from project_brain.hash_utils import (
    sha256_text,
    source_content_hash,
    stable_json,
    verification_content_hash,
)
from project_brain.repo_context import RepoContext
from project_brain.store import BrainStore
from project_brain.verification_event_time_code import (
    code_checkout_evidence_row,
    dedicated_engine_checks,
)


VerificationStatus = Literal["ready", "unverified", "stale", "blocked"]


@dataclass(frozen=True)
class VerificationEvaluation:
    verification_status: VerificationStatus
    reason_codes: tuple[str, ...]


_PROFILE_VERSION = 1
_COMMON_CHECK_AUTHORITIES = {
    "common.content-supported": frozenset({"agent", "human"}),
    "common.evidence-resolved": frozenset({"engine"}),
    "common.current": frozenset({"engine", "agent"}),
    "common.kind-fit": frozenset({"agent"}),
    "common.questions-resolved": frozenset({"agent", "human"}),
}
_COMMON_ENGINE_CHECK_IDS = frozenset({
    "common.evidence-resolved",
    "common.current",
})


@dataclass(frozen=True)
class VerificationProfile:
    id: str
    version: int
    subject_kind: str
    check_authorities: Mapping[str, frozenset[str]]
    engine_check_ids: frozenset[str]
    direct_evidence_fields: frozenset[str]
    required_format: str | None = None


def _profile(
    profile_id: str,
    subject_kind: str,
    *,
    dedicated_checks: Mapping[str, frozenset[str]],
    engine_check_ids: frozenset[str],
    direct_evidence_fields: frozenset[str],
    required_format: str | None = None,
) -> VerificationProfile:
    return VerificationProfile(
        id=profile_id,
        version=_PROFILE_VERSION,
        subject_kind=subject_kind,
        check_authorities={**_COMMON_CHECK_AUTHORITIES, **dedicated_checks},
        engine_check_ids=_COMMON_ENGINE_CHECK_IDS | engine_check_ids,
        direct_evidence_fields=direct_evidence_fields,
        required_format=required_format,
    )


_EVIDENCE_REF_PROFILE = _profile(
    "verification.evidence-ref",
    "EvidenceRef",
    dedicated_checks={
        "evidence.locator-resolves": frozenset({"engine"}),
        "evidence.manifest-compatible": frozenset({"engine"}),
        "evidence.quote-bound": frozenset({"engine"}),
    },
    engine_check_ids=frozenset({
        "evidence.locator-resolves",
        "evidence.manifest-compatible",
        "evidence.quote-bound",
    }),
    direct_evidence_fields=frozenset({
        "evidence_manifest_id", "locator", "evidence_refs",
    }),
)
_PROFILES_BY_KIND = {
    profile.subject_kind: profile
    for profile in (
        _EVIDENCE_REF_PROFILE,
    )
}
_PROFILES_BY_ID = {
    profile.id: profile
    for profile in _PROFILES_BY_KIND.values()
}

# 기존 EvidenceRef 내부 이름은 같은 모듈의 이전 테스트·호출을 깨지 않게 유지한다.
_PROFILE_ID = _EVIDENCE_REF_PROFILE.id
_DIRECT_EVIDENCE_FIELDS = _EVIDENCE_REF_PROFILE.direct_evidence_fields
_CHECK_AUTHORITIES = _EVIDENCE_REF_PROFILE.check_authorities
_ENGINE_CHECK_IDS = _EVIDENCE_REF_PROFILE.engine_check_ids
_TOP_LEVEL_KEYS = frozenset({
    "version", "profile", "bindings", "checks", "execution",
})
_BINDING_KEYS = frozenset({
    "content_sha256", "evidence_sha256", "rules_sha256", "execution_sha256",
})
_EXECUTION_KEYS = frozenset({
    "workflow", "engine_sha", "executed_at", "producer", "verifiers",
    "subject_metadata",
})
_SUBJECT_METADATA_KEYS = frozenset({
    "candidate_state", "candidate_source", "proposed_by", "proposed_at",
    "open_questions",
})
_IDENTITY_KEYS = frozenset({"kind", "id", "version"})
_CHECK_KEYS = frozenset({"id", "outcome", "authority", "summary"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ENGINE_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_REASON_ORDER = (
    "kind_not_promotable",
    "candidate_conflict",
    "check_failed",
    "human_required",
    "open_questions",
    "execution_invalid",
    "review_shape_invalid",
    "unsupported_version",
    "profile_mismatch",
    "content_changed",
    "evidence_changed",
    "rules_changed",
    "verification_missing",
)
_BLOCKED_REASONS = frozenset(_REASON_ORDER[:7])
_STALE_REASONS = frozenset({
    "unsupported_version",
    "profile_mismatch",
    "content_changed",
    "evidence_changed",
    "rules_changed",
})
_REF_TYPES_BY_SOURCE_TYPE = {
    "session": frozenset({"session_turn"}),
    "slack": frozenset({"slack_message", "slack_thread"}),
    "jira": frozenset({"jira_comment", "jira_issue"}),
    "pr": frozenset({"pr"}),
    "commit": frozenset({"commit", "code_locator"}),
    "spec": frozenset({"spec_slide", "spec_section"}),
    "build_log": frozenset({"build_log_range"}),
    "code_search": frozenset({"code_locator"}),
    "wiki": frozenset({"wiki_section"}),
    "context": frozenset({"context_term"}),
}


def _is_timezone_aware(value: object) -> bool:
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _identity_problems(identity: object, *, label: str) -> list[str]:
    if not isinstance(identity, Mapping):
        return [f"{label} must be an object"]
    problems = []
    if frozenset(identity) != _IDENTITY_KEYS:
        problems.append(f"{label} keys must be exact")
    for key in _IDENTITY_KEYS:
        value = identity.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{label}.{key} must be a non-empty string")
    return problems


def _candidate_metadata(subject: Mapping[str, object]) -> object:
    candidate = subject.get("candidate")
    if not isinstance(candidate, Mapping):
        return None
    return {
        key: deepcopy(candidate.get(key))
        for key in _SUBJECT_METADATA_KEYS
    }


def _candidate_metadata_problems(subject: Mapping[str, object]) -> list[str]:
    from project_brain.schema import (
        CANDIDATE_SOURCE_VALUES,
        CANDIDATE_STATE_VALUES,
    )

    candidate = subject.get("candidate")
    if not isinstance(candidate, Mapping):
        return ["candidate metadata is required"]
    problems = []
    missing = sorted(_SUBJECT_METADATA_KEYS - frozenset(candidate))
    if missing:
        problems.append("candidate metadata missing: " + ", ".join(missing))
    for key in ("candidate_state", "candidate_source", "proposed_by"):
        value = candidate.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"candidate.{key} must be a non-empty string")
    if candidate.get("candidate_state") not in CANDIDATE_STATE_VALUES:
        problems.append("candidate.candidate_state is invalid")
    if candidate.get("candidate_source") not in CANDIDATE_SOURCE_VALUES:
        problems.append("candidate.candidate_source is invalid")
    if not _is_timezone_aware(candidate.get("proposed_at")):
        problems.append("candidate.proposed_at must be timezone-aware ISO 8601")
    questions = candidate.get("open_questions")
    if not isinstance(questions, list):
        problems.append("candidate.open_questions must be a list")
    else:
        valid_questions = all(
            isinstance(item, str) and bool(item.strip())
            for item in questions
        )
        if (
            not valid_questions
            or questions != sorted(set(questions))
        ):
            problems.append(
                "candidate.open_questions must be sorted unique non-empty strings"
            )
    return problems


def candidate_verification_profile(
    subject: Mapping[str, object],
) -> VerificationProfile | None:
    """현재 구현이 지원하는 candidate verification profile을 반환한다."""
    profile = _PROFILES_BY_KIND.get(str(subject.get("kind")))
    if profile is None:
        return None
    if (
        profile.required_format is not None
        and subject.get("format") != profile.required_format
    ):
        return None
    return profile


def registered_candidate_verification_kind(
    subject: Mapping[str, object],
) -> bool:
    """kind가 registry에 있으나 variant가 profile 대상 밖인지 구분한다."""
    return str(subject.get("kind")) in _PROFILES_BY_KIND


def _profile_from_envelope(
    verification: Mapping[str, object],
) -> VerificationProfile | None:
    profile = verification.get("profile")
    if not isinstance(profile, Mapping):
        return None
    return _PROFILES_BY_ID.get(str(profile.get("id")))


def _direct_evidence_rows(
    subject: Mapping[str, object],
    store: BrainStore,
    profile: VerificationProfile | None = None,
) -> list[dict[str, object]]:
    selected = profile or candidate_verification_profile(subject)
    if selected is None:
        return []
    pointers: list[tuple[str, object]] = []
    for field in sorted(
        selected.direct_evidence_fields - frozenset({"source_content_hash"})
    ):
        value = subject.get(field)
        if isinstance(value, list):
            pointers.extend(
                (f"/{field}/{index}", object_id)
                for index, object_id in enumerate(value)
            )
        elif field == "locator":
            if isinstance(value, Mapping) and "code_locator_id" in value:
                pointers.append(
                    ("/locator/code_locator_id", value.get("code_locator_id"))
                )
        else:
            pointers.append((f"/{field}", value))
    rows = []
    for pointer, object_id in pointers:
        target = (
            store.get(object_id)
            if isinstance(object_id, str) and store.has(object_id)
            else None
        )
        rows.append({
            "pointer": pointer,
            "object_id": object_id,
            "content_sha256": (
                source_content_hash([target]) if target is not None else None
            ),
        })
    if "source_content_hash" in selected.direct_evidence_fields:
        source_ids = subject.get("source_object_ids")
        current_source_hash = None
        if (
            isinstance(source_ids, list)
            and all(isinstance(item, str) and store.has(item) for item in source_ids)
        ):
            current_source_hash = source_content_hash(
                store.get(object_id) for object_id in source_ids
            )
        rows.append({
            "pointer": "/source_content_hash",
            "object_id": None,
            "content_sha256": current_source_hash,
        })
    return sorted(rows, key=lambda row: (str(row["pointer"]), str(row["object_id"])))


def _content_sha256(
    subject: Mapping[str, object],
    profile: VerificationProfile | None = None,
) -> str:
    selected = profile or candidate_verification_profile(subject)
    if selected is None:
        raise ValueError("subject has no supported verification profile")
    return verification_content_hash(
        subject,
        direct_evidence_fields=selected.direct_evidence_fields,
    )


def _evidence_sha256(
    subject: Mapping[str, object],
    store: BrainStore,
    profile: VerificationProfile | None = None,
) -> str:
    selected = profile or candidate_verification_profile(subject)
    if selected is None:
        raise ValueError("subject has no supported verification profile")
    return sha256_text(stable_json({
        "projection": "verification-evidence-v1",
        "rows": _direct_evidence_rows(subject, store, selected),
    }))


def _rules_sha256(profile: VerificationProfile | None = None) -> str:
    selected = profile or _EVIDENCE_REF_PROFILE
    return sha256_text(stable_json({
        "profile": {"id": selected.id, "version": selected.version},
        "checks": [
            {"id": check_id, "authorities": sorted(authorities)}
            for check_id, authorities in sorted(selected.check_authorities.items())
        ],
        "content_projection": "verification-content-v1",
        "direct_evidence_fields": sorted(selected.direct_evidence_fields),
        "evidence_projection": "verification-evidence-v1",
        "profile_rules": (
            {
                "ref_types_by_source_type": {
                    source_type: sorted(ref_types)
                    for source_type, ref_types
                    in sorted(_REF_TYPES_BY_SOURCE_TYPE.items())
                },
            }
            if selected is _EVIDENCE_REF_PROFILE
            else {"required_format": selected.required_format}
        ),
    }))


def _rules_binding(profile: VerificationProfile) -> str:
    # EvidenceRef의 기존 monkeypatch seam을 유지한다.
    return _rules_sha256() if profile is _EVIDENCE_REF_PROFILE else _rules_sha256(profile)


def _execution_sha256(
    *,
    checks: Sequence[Mapping[str, object]],
    execution: Mapping[str, object],
    bindings: Mapping[str, object],
) -> str:
    return sha256_text(stable_json({
        "workflow": execution.get("workflow"),
        "engine_sha": execution.get("engine_sha"),
        "executed_at": execution.get("executed_at"),
        "producer": execution.get("producer"),
        "verifiers": execution.get("verifiers"),
        "subject_metadata": execution.get("subject_metadata"),
        "content_sha256": bindings.get("content_sha256"),
        "evidence_sha256": bindings.get("evidence_sha256"),
        "rules_sha256": bindings.get("rules_sha256"),
        "checks": list(checks),
    }))


def _engine_checks(
    subject: Mapping[str, object],
    store: BrainStore,
    profile: VerificationProfile | None = None,
) -> list[dict[str, str]]:
    selected = profile or candidate_verification_profile(subject)
    if selected is None:
        return []
    rows = _direct_evidence_rows(subject, store, selected)
    references_resolve = all(row["content_sha256"] is not None for row in rows)
    checks = {
        "common.evidence-resolved": (
            references_resolve,
            "직접 근거 참조가 현재 store에서 모두 해석된다.",
        ),
        "common.current": (
            references_resolve,
            "현재 store의 직접 근거 결속을 사용했다.",
        ),
    }
    if selected is _EVIDENCE_REF_PROFILE:
        locator = subject.get("locator")
        code_locator = None
        code_locator_id = (
            locator.get("code_locator_id")
            if isinstance(locator, Mapping)
            else None
        )
        if isinstance(code_locator_id, str) and store.has(code_locator_id):
            candidate_locator = store.get(code_locator_id)
            if candidate_locator.get("kind") == "CodeLocator":
                code_locator = candidate_locator
        if subject.get("ref_type") == "code_locator":
            locator_resolves = code_locator is not None
        else:
            locator_resolves = isinstance(locator, Mapping) and bool(locator)
        manifest = None
        manifest_id = subject.get("evidence_manifest_id")
        if isinstance(manifest_id, str) and store.has(manifest_id):
            candidate_manifest = store.get(manifest_id)
            if candidate_manifest.get("kind") == "EvidenceManifest":
                manifest = candidate_manifest
        compatible = bool(
            manifest is not None
            and subject.get("ref_type")
            in _REF_TYPES_BY_SOURCE_TYPE.get(str(manifest.get("source_type")), ())
        )
        quote_bound = bool(
            isinstance(subject.get("summary"), str)
            and str(subject.get("summary")).strip()
            and locator_resolves
            and (
                subject.get("ref_type") != "code_locator"
                or (
                    isinstance(code_locator, Mapping)
                    and isinstance(code_locator.get("verified_quote"), str)
                    and bool(str(code_locator.get("verified_quote")).strip())
                )
            )
        )
        checks.update({
            "evidence.locator-resolves": (
                locator_resolves,
                "locator가 현재 store에서 해석된다.",
            ),
            "evidence.manifest-compatible": (
                compatible,
                "manifest source_type과 ref_type이 호환된다.",
            ),
            "evidence.quote-bound": (
                quote_bound,
                "비어 있지 않은 인용 요약이 locator에 결속된다.",
            ),
        })
    return [
        {
            "id": check_id,
            "outcome": "pass" if passed else "fail",
            "authority": "engine",
            "summary": summary,
        }
        for check_id, (passed, summary) in sorted(checks.items())
    ]


def verification_envelope_problems(subject: Mapping[str, object]) -> tuple[str, ...]:
    """존재하는 v1 envelope의 exact 모양 위반을 반환한다."""
    candidate = subject.get("candidate")
    verification = (
        candidate.get("verification")
        if isinstance(candidate, Mapping)
        else None
    )
    if verification is None:
        return ()
    if not isinstance(verification, Mapping):
        return ("candidate.verification must be an object",)
    problems = []
    if "kind" in subject:
        selected = candidate_verification_profile(subject)
        if selected is None:
            problems.append("subject has no supported candidate verification profile")
            selected = _profile_from_envelope(verification)
    else:
        selected = _profile_from_envelope(verification)
    if selected is None:
        problems.append("verification profile is unsupported")
    if frozenset(verification) != _TOP_LEVEL_KEYS:
        problems.append("verification top-level keys must be exact")
    profile = verification.get("profile")
    if not isinstance(profile, Mapping) or frozenset(profile) != {"id", "version"}:
        problems.append("verification.profile keys must be exact")
    elif (
        not isinstance(profile.get("id"), str)
        or type(profile.get("version")) is not int
    ):
        problems.append("verification.profile values are invalid")
    if type(verification.get("version")) is not int:
        problems.append("verification.version must be an integer")
    bindings = verification.get("bindings")
    if not isinstance(bindings, Mapping) or frozenset(bindings) != _BINDING_KEYS:
        problems.append("verification.bindings keys must be exact")
    elif any(
        not isinstance(value, str) or _SHA256.fullmatch(value) is None
        for value in bindings.values()
    ):
        problems.append("verification bindings must be lowercase SHA-256")
    checks = verification.get("checks")
    if not isinstance(checks, list):
        problems.append("verification.checks must be a list")
        checks = []
    else:
        check_ids: list[str] = []
        for index, check in enumerate(checks):
            if not isinstance(check, Mapping) or frozenset(check) != _CHECK_KEYS:
                problems.append(f"verification.checks[{index}] keys must be exact")
                continue
            check_id = check.get("id")
            if not isinstance(check_id, str):
                problems.append(f"verification.checks[{index}] id must be a string")
                continue
            check_ids.append(check_id)
            authorities = (
                selected.check_authorities
                if selected is not None
                else {}
            )
            if check_id not in authorities:
                problems.append(f"verification.checks[{index}] id is not in the profile")
            elif check.get("authority") not in authorities[str(check_id)]:
                problems.append(f"verification.checks[{index}] authority is not allowed")
            if check.get("outcome") not in {"pass", "fail", "needs_human"}:
                problems.append(f"verification.checks[{index}] invalid outcome")
            if not isinstance(check.get("summary"), str) or not str(check.get("summary")).strip():
                problems.append(f"verification.checks[{index}] summary must be non-empty")
        if check_ids != sorted(check_ids) or len(check_ids) != len(set(check_ids)):
            problems.append("verification checks must be sorted and unique")
        if selected is not None and set(check_ids) != set(
            selected.check_authorities
        ):
            problems.append("verification checks must exactly match the profile")
    execution = verification.get("execution")
    if not isinstance(execution, Mapping) or frozenset(execution) != _EXECUTION_KEYS:
        problems.append("verification.execution keys must be exact")
    else:
        if execution.get("workflow") not in {
            "candidate", "direct_reviewed_create", "reviewed_update",
        }:
            problems.append("verification.execution.workflow is invalid")
        if (
            subject.get("status") == "candidate"
            and execution.get("workflow") != "candidate"
        ):
            problems.append("candidate verification workflow must be candidate")
        engine_sha = execution.get("engine_sha")
        if not isinstance(engine_sha, str) or _ENGINE_SHA.fullmatch(engine_sha) is None:
            problems.append("verification.execution.engine_sha is invalid")
        if not _is_timezone_aware(execution.get("executed_at")):
            problems.append("verification.execution.executed_at is invalid")
        problems.extend(_identity_problems(execution.get("producer"), label="producer"))
        verifiers = execution.get("verifiers")
        if not isinstance(verifiers, list):
            problems.append("verification.execution.verifiers must be a list")
        else:
            identities = []
            for index, verifier in enumerate(verifiers):
                problems.extend(_identity_problems(verifier, label=f"verifiers[{index}]"))
                if (
                    isinstance(verifier, Mapping)
                    and all(
                        isinstance(verifier.get(key), str)
                        for key in ("kind", "id", "version")
                    )
                ):
                    identities.append(tuple(verifier.get(key) for key in ("kind", "id", "version")))
            if identities != sorted(identities) or len(identities) != len(set(identities)):
                problems.append("verification verifiers must be sorted and unique")
        if execution.get("workflow") == "candidate":
            problems.extend(_candidate_metadata_problems(subject))
            metadata = execution.get("subject_metadata")
            if not isinstance(metadata, Mapping) or frozenset(metadata) != _SUBJECT_METADATA_KEYS:
                problems.append("candidate subject_metadata keys must be exact")
            elif metadata != _candidate_metadata(subject):
                problems.append("candidate subject_metadata must match candidate")
            producer = execution.get("producer")
            candidate = subject.get("candidate")
            if (
                isinstance(producer, Mapping)
                and isinstance(candidate, Mapping)
                and producer.get("id") != candidate.get("proposed_by")
            ):
                problems.append("candidate producer.id must equal proposed_by")
        elif execution.get("subject_metadata") is not None:
            problems.append("reviewed workflow subject_metadata must be null")
    return tuple(problems)


def prepare_candidate_verification(
    subject: Mapping[str, object],
    store: BrainStore,
    *,
    checks: Sequence[Mapping[str, object]],
    engine_sha: str,
    executed_at: str,
    producer: Mapping[str, object],
    verifiers: Sequence[Mapping[str, object]],
    repo_context: RepoContext | None = None,
) -> dict:
    """지원 candidate의 현재 store 결속 v1 envelope를 결정론적으로 만든다."""
    selected = candidate_verification_profile(subject)
    if selected is None or subject.get("status") != "candidate":
        raise ValueError("subject requires a supported candidate verification profile")
    metadata_problems = _candidate_metadata_problems(subject)
    if metadata_problems:
        raise ValueError("; ".join(metadata_problems))
    if any(not isinstance(check, Mapping) for check in checks):
        raise ValueError("checks must contain objects")
    supplied_checks = [dict(check) for check in checks]
    supplied_ids = [check.get("id") for check in supplied_checks]
    expected_supplied = sorted(
        set(selected.check_authorities) - selected.engine_check_ids
    )
    if (
        any(not isinstance(check_id, str) for check_id in supplied_ids)
        or sorted(supplied_ids) != expected_supplied
        or len(supplied_ids) != len(set(supplied_ids))
    ):
        raise ValueError("caller checks must exactly match non-engine profile checks")
    if any(not isinstance(verifier, Mapping) for verifier in verifiers):
        raise ValueError("verifiers must contain objects")
    normalized_checks = sorted(
        supplied_checks + _engine_checks(subject, store, selected),
        key=lambda check: str(check.get("id")),
    )
    normalized_verifiers = sorted(
        (dict(verifier) for verifier in verifiers),
        key=lambda identity: (
            str(identity.get("kind")),
            str(identity.get("id")),
            str(identity.get("version")),
        ),
    )
    bindings = {
        "content_sha256": _content_sha256(subject, selected),
        "evidence_sha256": _evidence_sha256(subject, store, selected),
        "rules_sha256": _rules_binding(selected),
    }
    execution = {
        "workflow": "candidate",
        "engine_sha": engine_sha,
        "executed_at": executed_at,
        "producer": dict(producer),
        "verifiers": normalized_verifiers,
        "subject_metadata": _candidate_metadata(subject),
    }
    bindings["execution_sha256"] = _execution_sha256(
        checks=normalized_checks,
        execution=execution,
        bindings=bindings,
    )
    envelope = {
        "version": 1,
        "profile": {"id": selected.id, "version": selected.version},
        "bindings": bindings,
        "checks": normalized_checks,
        "execution": execution,
    }
    prepared = deepcopy(dict(subject))
    prepared_candidate = dict(prepared["candidate"])
    prepared_candidate["verification"] = envelope
    prepared["candidate"] = prepared_candidate
    problems = verification_envelope_problems(prepared)
    if problems:
        raise ValueError("; ".join(problems))
    return prepared


def promotion_review_fields(
    subject: Mapping[str, object],
    store: BrainStore,
    *,
    repo_context: RepoContext | None = None,
) -> dict[str, object]:
    """fresh candidate가 ReviewRecord로 옮길 초기 verification 필드를 반환한다."""
    if not isinstance(store, BrainStore):
        raise ValueError("verified candidate promotion requires the current BrainStore")
    evaluation = evaluate_candidate_verification(dict(subject), store)
    if evaluation.verification_status != "ready":
        reasons = ", ".join(evaluation.reason_codes) or "unknown"
        raise ValueError(f"verification_not_ready: {reasons}")
    candidate = subject.get("candidate")
    assert isinstance(candidate, Mapping)
    return {
        "verification": deepcopy(candidate["verification"]),
        "verification_origin": "candidate_promotion",
        "verification_history": [],
    }


def review_record_verification_problems(
    record: Mapping[str, object],
) -> tuple[str, ...]:
    """legacy ReviewRecord는 허용하고, 존재하는 단일-target verification만 exact 검사한다."""
    fields = {
        "verification",
        "verification_origin",
        "verification_history",
    }
    present = fields & set(record)
    if not present:
        return ()
    problems = []
    if present != fields:
        problems.append("ReviewRecord verification fields must appear together")
        return tuple(problems)
    if record.get("verification_origin") not in {
        "candidate_promotion", "direct_reviewed_create", "reviewed_update",
    }:
        problems.append("ReviewRecord verification_origin is invalid")
    history = record.get("verification_history")
    if not isinstance(history, list):
        problems.append("ReviewRecord verification_history must be a list")
    verification = record.get("verification")
    if not isinstance(verification, Mapping):
        problems.append("ReviewRecord verification must be an object")
    else:
        execution = verification.get("execution")
        metadata = (
            execution.get("subject_metadata")
            if isinstance(execution, Mapping)
            else None
        )
        synthetic = {
            "candidate": {
                **(dict(metadata) if isinstance(metadata, Mapping) else {}),
                "verification": verification,
            }
        }
        problems.extend(verification_envelope_problems(synthetic))
    if "target_verifications" in record:
        problems.append("single-target ReviewRecord cannot contain target_verifications")
    return tuple(problems)


def candidate_promotion_problems(
    candidate: Mapping[str, object],
    promoted: Mapping[str, object],
    record: Mapping[str, object],
    store: BrainStore,
    *,
    repo_context: RepoContext | None = None,
) -> tuple[str, ...]:
    """lock 안 live store에서 지원 candidate의 target·record 결속을 검증한다."""
    selected = candidate_verification_profile(candidate)
    if selected is None:
        return ()
    evaluation = evaluate_candidate_verification(
        dict(candidate),
        store,
        repo_context=repo_context,
    )
    if evaluation.verification_status != "ready":
        return ("verification_not_ready: " + ", ".join(evaluation.reason_codes),)
    candidate_metadata = candidate.get("candidate")
    assert isinstance(candidate_metadata, Mapping)
    envelope = candidate_metadata.get("verification")
    bindings = envelope.get("bindings") if isinstance(envelope, Mapping) else None
    problems = []
    if promoted.get("status") != "reviewed" or "candidate" in promoted:
        problems.append("promotion target must be reviewed without candidate metadata")
    if isinstance(bindings, Mapping):
        if bindings.get("content_sha256") != _content_sha256(promoted, selected):
            problems.append("promotion target content binding differs from candidate")
        if bindings.get("evidence_sha256") != _evidence_sha256(
            promoted,
            store,
            selected,
        ):
            problems.append("promotion target evidence binding differs from candidate")
    if record.get("verification") != envelope:
        problems.append("ReviewRecord verification must equal candidate verification")
    if record.get("verification_origin") != "candidate_promotion":
        problems.append("ReviewRecord verification_origin must be candidate_promotion")
    if record.get("verification_history") != []:
        problems.append("initial ReviewRecord verification_history must be empty")
    problems.extend(review_record_verification_problems(record))
    return tuple(problems)


def _review_shape_problems(subject: Mapping[str, object]) -> tuple[str, ...]:
    from project_brain.id_grammar import format_id
    from project_brain.objbase import review_record
    from project_brain.schema import (
        validate_mutation_input_schema,
        validate_object_id,
    )

    candidate = subject.get("candidate")
    if not isinstance(candidate, Mapping) or not isinstance(
        candidate.get("verification"), Mapping
    ):
        return ()
    try:
        review_id = format_id(
            "ReviewRecord",
            target_object_id=str(subject.get("id", "")),
        )
    except ValueError as exc:
        return (str(exc),)
    reviewed = deepcopy(dict(subject))
    reviewed["status"] = "reviewed"
    reviewed["review_record_id"] = review_id
    reviewed.pop("candidate", None)
    reviewed.pop("updated_at", None)
    fields = {
        "verification": deepcopy(candidate["verification"]),
        "verification_origin": "candidate_promotion",
        "verification_history": [],
    }
    execution = candidate["verification"].get("execution")
    reviewed_at = (
        execution.get("executed_at")
        if isinstance(execution, Mapping)
        else None
    )
    record = review_record(
        review_id,
        target_object_id=str(subject.get("id", "")),
        reviewer="verification-shape-check",
        reviewed_at=reviewed_at,
        verdict="approved",
        tags=list(subject.get("tags") or []),
        created_at=None,
        updated_at=None,
        evidence_refs=list(subject.get("evidence_refs") or []),
        **fields,
    )
    return tuple(
        validate_mutation_input_schema(
            reviewed,
            omitted_required_fields=frozenset({"updated_at"}),
        )
        + validate_object_id(reviewed)
        + validate_mutation_input_schema(
            record,
            omitted_required_fields=frozenset({"created_at", "updated_at"}),
        )
        + validate_object_id(record)
    )


def evaluate_candidate_verification(
    subject: dict,
    store: BrainStore,
    *,
    repo_context: RepoContext | None = None,
) -> VerificationEvaluation:
    """현재 store에서 candidate의 verification 상태와 고정 순서 사유를 계산한다."""
    reasons: set[str] = set()
    capability = CAPABILITY_REGISTRY.get(str(subject.get("kind")))
    selected = candidate_verification_profile(subject)
    if (
        capability is None
        or capability.manual_promotion not in {
            ManualPromotionPolicy.ALLOWED,
            ManualPromotionPolicy.DEDICATED_VERIFICATION,
        }
        or subject.get("status") != "candidate"
        or selected is None
    ):
        reasons.add("kind_not_promotable")
    candidate = subject.get("candidate")
    if isinstance(candidate, Mapping):
        if candidate.get("candidate_state") == "conflict":
            reasons.add("candidate_conflict")
        if candidate.get("open_questions"):
            reasons.add("open_questions")
    verification = (
        candidate.get("verification")
        if isinstance(candidate, Mapping)
        else None
    )
    if verification is None:
        reasons.add("verification_missing")
    elif not isinstance(verification, Mapping):
        reasons.add("execution_invalid")
    else:
        if (
            type(verification.get("version")) is not int
            or selected is None
            or verification.get("version") != selected.version
        ):
            reasons.add("unsupported_version")
        profile = verification.get("profile")
        if (
            selected is None
            or
            not isinstance(profile, Mapping)
            or type(profile.get("version")) is not int
            or profile != {"id": selected.id, "version": selected.version}
        ):
            reasons.add("profile_mismatch")
        problems = verification_envelope_problems(subject)
        if problems:
            reasons.add("execution_invalid")
        checks = verification.get("checks")
        if isinstance(checks, list):
            seen_ids: set[str] = set()
            authorities = selected.check_authorities if selected is not None else {}
            for check in checks:
                if not isinstance(check, Mapping):
                    continue
                check_id = check.get("id")
                authority = check.get("authority")
                if (
                    not isinstance(check_id, str)
                    or
                    check_id not in authorities
                    or authority not in authorities.get(str(check_id), ())
                ):
                    reasons.add("execution_invalid")
                    continue
                if check_id in seen_ids:
                    reasons.add("execution_invalid")
                seen_ids.add(check_id)
                if check.get("outcome") == "fail":
                    reasons.add("check_failed")
                elif check.get("outcome") == "needs_human":
                    reasons.add("human_required")
            if seen_ids != set(authorities):
                reasons.add("execution_invalid")
        bindings = verification.get("bindings")
        execution = verification.get("execution")
        if isinstance(bindings, Mapping) and selected is not None:
            content_matches = (
                bindings.get("content_sha256")
                == _content_sha256(subject, selected)
            )
            evidence_matches = (
                bindings.get("evidence_sha256")
                == _evidence_sha256(subject, store, selected)
            )
            rules_match = bindings.get("rules_sha256") == _rules_binding(selected)
            if not content_matches:
                reasons.add("content_changed")
            if not evidence_matches:
                reasons.add("evidence_changed")
            if not rules_match:
                reasons.add("rules_changed")
            if isinstance(checks, list) and isinstance(execution, Mapping):
                if bindings.get("execution_sha256") != _execution_sha256(
                    checks=checks,
                    execution=execution,
                    bindings=bindings,
                ):
                    reasons.add("execution_invalid")
                if content_matches and evidence_matches and rules_match:
                    check_by_id = {
                        str(check["id"]): check
                        for check in checks
                        if isinstance(check, Mapping) and "id" in check
                    }
                    for engine_check in _engine_checks(subject, store, selected):
                        if check_by_id.get(engine_check["id"]) != engine_check:
                            reasons.add("execution_invalid")
        if (
            not problems
            and selected is not None
            and profile == {"id": selected.id, "version": selected.version}
            and _review_shape_problems(subject)
        ):
            reasons.add("review_shape_invalid")
    ordered = tuple(reason for reason in _REASON_ORDER if reason in reasons)
    if not ordered:
        status: VerificationStatus = "ready"
    elif reasons & _BLOCKED_REASONS:
        status = "blocked"
    elif reasons & _STALE_REASONS:
        status = "stale"
    else:
        status = "unverified"
    return VerificationEvaluation(status, ordered)
