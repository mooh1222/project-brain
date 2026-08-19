"""현재 19종 Brain 객체의 쓰기·검색·검수 capability 정본.

이 registry는 정책을 설명하고 분산된 kind 집합의 드리프트를 검사하는 용도다.
schema, query, search, promote, mutation, graph의 런타임 분기를 아직 이 표로
바꾸지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType


class CandidatePolicy(StrEnum):
    FORBIDDEN = "forbidden"
    ALLOWED = "allowed"
    PROMPT_PAYLOAD_ONLY = "prompt_payload_only"


class ManualPromotionPolicy(StrEnum):
    FORBIDDEN = "forbidden"
    ALLOWED = "allowed"
    DEDICATED_VERIFICATION = "dedicated_verification"


class SearchLane(StrEnum):
    NONE = "none"
    OBJECTS = "objects"
    PROJECTION_REUSE = "projection_reuse"
    ADVISORIES = "advisories"


class GraphExposure(StrEnum):
    DEFAULT = "default"


class VerificationMode(StrEnum):
    COMMON = "common_verification"
    DEDICATED = "dedicated_proof"
    NOT_APPLICABLE = "not_applicable"


class ReviewRecordPolicy(StrEnum):
    REQUIRED_FOR_COMMON_VERIFICATION = "required_for_common_verification"
    NOT_IMPLICIT = "not_implicit"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class KindCapabilities:
    candidate_policy: CandidatePolicy
    query_confirmation: bool
    direct_reviewed: bool
    direct_reviewed_requirement: str
    manual_promotion: ManualPromotionPolicy
    automatic_promotion: bool
    search_lane: SearchLane
    update_owner: str
    graph_exposure: GraphExposure
    verification_modes: frozenset[VerificationMode]
    review_record_policy: ReviewRecordPolicy


def _capability(
    *,
    candidate: CandidatePolicy,
    query_confirmation: bool,
    direct_reviewed: bool,
    direct_reviewed_requirement: str,
    manual_promotion: ManualPromotionPolicy,
    automatic_promotion: bool = False,
    search_lane: SearchLane = SearchLane.NONE,
    update_owner: str,
    verification_modes: tuple[VerificationMode, ...],
    review_record_policy: ReviewRecordPolicy,
) -> KindCapabilities:
    return KindCapabilities(
        candidate_policy=candidate,
        query_confirmation=query_confirmation,
        direct_reviewed=direct_reviewed,
        direct_reviewed_requirement=direct_reviewed_requirement,
        manual_promotion=manual_promotion,
        automatic_promotion=automatic_promotion,
        search_lane=search_lane,
        update_owner=update_owner,
        graph_exposure=GraphExposure.DEFAULT,
        verification_modes=frozenset(verification_modes),
        review_record_policy=review_record_policy,
    )


_COMMON_REVIEW = ReviewRecordPolicy.REQUIRED_FOR_COMMON_VERIFICATION
_DEDICATED_REVIEW = ReviewRecordPolicy.NOT_IMPLICIT
_NO_REVIEW = ReviewRecordPolicy.NOT_APPLICABLE


CAPABILITY_REGISTRY: Mapping[str, KindCapabilities] = MappingProxyType({
    "EvidenceManifest": _capability(
        candidate=CandidatePolicy.FORBIDDEN,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="source_acl_redaction_verified",
        manual_promotion=ManualPromotionPolicy.FORBIDDEN,
        update_owner="source_recapture_and_redaction_update",
        verification_modes=(VerificationMode.DEDICATED,),
        review_record_policy=_DEDICATED_REVIEW,
    ),
    "EvidenceRef": _capability(
        candidate=CandidatePolicy.ALLOWED,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="locator_and_manifest_verified",
        manual_promotion=ManualPromotionPolicy.ALLOWED,
        update_owner="evidence_recapture_and_locator_repair",
        verification_modes=(VerificationMode.COMMON,),
        review_record_policy=_COMMON_REVIEW,
    ),
    "ReviewRecord": _capability(
        candidate=CandidatePolicy.FORBIDDEN,
        query_confirmation=False,
        direct_reviewed=False,
        direct_reviewed_requirement="engine_generated_with_target_write",
        manual_promotion=ManualPromotionPolicy.FORBIDDEN,
        update_owner="reviewed_change_and_id_migration",
        verification_modes=(VerificationMode.NOT_APPLICABLE,),
        review_record_policy=_NO_REVIEW,
    ),
    "EventLedgerRecord": _capability(
        candidate=CandidatePolicy.ALLOWED,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="event_and_source_verified",
        manual_promotion=ManualPromotionPolicy.ALLOWED,
        search_lane=SearchLane.OBJECTS,
        update_owner="correction_or_follow_up_event",
        verification_modes=(VerificationMode.COMMON,),
        review_record_policy=_COMMON_REVIEW,
    ),
    "TemporalFact": _capability(
        candidate=CandidatePolicy.ALLOWED,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="event_scope_and_time_verified",
        manual_promotion=ManualPromotionPolicy.ALLOWED,
        search_lane=SearchLane.OBJECTS,
        update_owner="validity_and_supersession_update",
        verification_modes=(VerificationMode.COMMON,),
        review_record_policy=_COMMON_REVIEW,
    ),
    "CodeLocator": _capability(
        candidate=CandidatePolicy.ALLOWED,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="checkout_verified",
        manual_promotion=ManualPromotionPolicy.ALLOWED,
        search_lane=SearchLane.OBJECTS,
        update_owner="code_verifier_and_mark_checked",
        verification_modes=(VerificationMode.COMMON,),
        review_record_policy=_COMMON_REVIEW,
    ),
    "DomainContext": _capability(
        candidate=CandidatePolicy.ALLOWED,
        query_confirmation=True,
        direct_reviewed=True,
        direct_reviewed_requirement="independent_boundary_verified",
        manual_promotion=ManualPromotionPolicy.ALLOWED,
        search_lane=SearchLane.OBJECTS,
        update_owner="context_update_and_replace",
        verification_modes=(VerificationMode.COMMON,),
        review_record_policy=_COMMON_REVIEW,
    ),
    "GlossaryTerm": _capability(
        candidate=CandidatePolicy.ALLOWED,
        query_confirmation=True,
        direct_reviewed=True,
        direct_reviewed_requirement="glossary_qualification_verified",
        manual_promotion=ManualPromotionPolicy.ALLOWED,
        automatic_promotion=True,
        search_lane=SearchLane.OBJECTS,
        update_owner="common_glossary_gate_and_approved_migration",
        verification_modes=(VerificationMode.COMMON,),
        review_record_policy=_COMMON_REVIEW,
    ),
    "ContextProjection": _capability(
        candidate=CandidatePolicy.PROMPT_PAYLOAD_ONLY,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="context_md_builder_path",
        manual_promotion=ManualPromotionPolicy.DEDICATED_VERIFICATION,
        search_lane=SearchLane.PROJECTION_REUSE,
        update_owner="projection_build_and_refresh",
        verification_modes=(VerificationMode.COMMON, VerificationMode.DEDICATED),
        review_record_policy=_COMMON_REVIEW,
    ),
    "CurrentView": _capability(
        candidate=CandidatePolicy.FORBIDDEN,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="source_aggregate_verified",
        manual_promotion=ManualPromotionPolicy.FORBIDDEN,
        search_lane=SearchLane.OBJECTS,
        update_owner="source_based_rebuild_and_replace",
        verification_modes=(VerificationMode.DEDICATED,),
        review_record_policy=_DEDICATED_REVIEW,
    ),
    "KnowledgePage": _capability(
        candidate=CandidatePolicy.FORBIDDEN,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="source_binding_verified",
        manual_promotion=ManualPromotionPolicy.FORBIDDEN,
        update_owner="source_based_rebuild_and_replace",
        verification_modes=(VerificationMode.DEDICATED,),
        review_record_policy=_DEDICATED_REVIEW,
    ),
    "IndexRecord": _capability(
        candidate=CandidatePolicy.FORBIDDEN,
        query_confirmation=False,
        direct_reviewed=False,
        direct_reviewed_requirement="engine_generated",
        manual_promotion=ManualPromotionPolicy.FORBIDDEN,
        update_owner="index_rebuild",
        verification_modes=(VerificationMode.NOT_APPLICABLE,),
        review_record_policy=_NO_REVIEW,
    ),
    "SpecDocument": _capability(
        candidate=CandidatePolicy.FORBIDDEN,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="canonical_locator_verified",
        manual_promotion=ManualPromotionPolicy.FORBIDDEN,
        update_owner="source_recapture",
        verification_modes=(VerificationMode.DEDICATED,),
        review_record_policy=_DEDICATED_REVIEW,
    ),
    "SpecRevision": _capability(
        candidate=CandidatePolicy.FORBIDDEN,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="document_and_revision_bound",
        manual_promotion=ManualPromotionPolicy.FORBIDDEN,
        update_owner="append_new_revision",
        verification_modes=(VerificationMode.DEDICATED,),
        review_record_policy=_DEDICATED_REVIEW,
    ),
    "SlideRef": _capability(
        candidate=CandidatePolicy.FORBIDDEN,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="revision_and_slide_bound",
        manual_promotion=ManualPromotionPolicy.FORBIDDEN,
        update_owner="source_recapture",
        verification_modes=(VerificationMode.DEDICATED,),
        review_record_policy=_DEDICATED_REVIEW,
    ),
    "SlackThread": _capability(
        candidate=CandidatePolicy.FORBIDDEN,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="thread_capture_verified",
        manual_promotion=ManualPromotionPolicy.FORBIDDEN,
        update_owner="thread_recapture",
        verification_modes=(VerificationMode.DEDICATED,),
        review_record_policy=_DEDICATED_REVIEW,
    ),
    "DecisionRecord": _capability(
        candidate=CandidatePolicy.ALLOWED,
        query_confirmation=True,
        direct_reviewed=True,
        direct_reviewed_requirement="decision_source_and_impact_verified",
        manual_promotion=ManualPromotionPolicy.ALLOWED,
        search_lane=SearchLane.OBJECTS,
        update_owner="decision_and_back_reference_update",
        verification_modes=(VerificationMode.COMMON,),
        review_record_policy=_COMMON_REVIEW,
    ),
    "DomainMapping": _capability(
        candidate=CandidatePolicy.ALLOWED,
        query_confirmation=True,
        direct_reviewed=True,
        direct_reviewed_requirement="meaning_boundary_and_evidence_verified",
        manual_promotion=ManualPromotionPolicy.ALLOWED,
        search_lane=SearchLane.OBJECTS,
        update_owner="guarded_bundle_update",
        verification_modes=(VerificationMode.COMMON,),
        review_record_policy=_COMMON_REVIEW,
    ),
    "Insight": _capability(
        candidate=CandidatePolicy.FORBIDDEN,
        query_confirmation=False,
        direct_reviewed=True,
        direct_reviewed_requirement="source_synthesis_verified",
        manual_promotion=ManualPromotionPolicy.FORBIDDEN,
        search_lane=SearchLane.ADVISORIES,
        update_owner="source_aware_replace_and_supersede",
        verification_modes=(VerificationMode.DEDICATED,),
        review_record_policy=_DEDICATED_REVIEW,
    ),
})


def capability_registry_problems(
    registry: Mapping[str, KindCapabilities] = CAPABILITY_REGISTRY,
) -> tuple[str, ...]:
    """현재 kind 집합과 각 row 구조가 어긋난 지점을 정렬해 반환한다."""
    from project_brain.schema import VALID_KINDS

    problems: list[str] = []
    actual_kinds = frozenset(registry)
    missing = sorted(VALID_KINDS - actual_kinds)
    extra = sorted(actual_kinds - VALID_KINDS)
    if missing:
        problems.append(f"capability registry missing kinds: {', '.join(missing)}")
    if extra:
        problems.append(f"capability registry unknown kinds: {', '.join(extra)}")

    for kind in sorted(VALID_KINDS & actual_kinds):
        capability = registry[kind]
        if not isinstance(capability, KindCapabilities):
            problems.append(f"{kind}: capability row must be KindCapabilities")
            continue
        if (
            capability.automatic_promotion
            and capability.manual_promotion is ManualPromotionPolicy.FORBIDDEN
        ):
            problems.append(
                f"{kind}: automatic promotion requires manual promotion support"
            )
        if not capability.direct_reviewed_requirement:
            problems.append(f"{kind}: direct reviewed requirement is empty")
        if not capability.update_owner:
            problems.append(f"{kind}: update owner is empty")
        if VerificationMode.NOT_APPLICABLE in capability.verification_modes:
            if capability.verification_modes != frozenset({VerificationMode.NOT_APPLICABLE}):
                problems.append(
                    f"{kind}: not_applicable verification cannot be combined"
                )
            if capability.review_record_policy is not ReviewRecordPolicy.NOT_APPLICABLE:
                problems.append(
                    f"{kind}: not_applicable verification requires "
                    "not_applicable ReviewRecord policy"
                )
        if (
            VerificationMode.COMMON in capability.verification_modes
            and capability.review_record_policy
            is not ReviewRecordPolicy.REQUIRED_FOR_COMMON_VERIFICATION
        ):
            problems.append(
                f"{kind}: common verification requires target ReviewRecord policy"
            )
    return tuple(problems)
