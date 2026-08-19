from dataclasses import asdict, replace
from pathlib import Path

from project_brain.capabilities import (
    CAPABILITY_REGISTRY,
    CandidatePolicy,
    GraphExposure,
    KindCapabilities,
    ManualPromotionPolicy,
    ReviewRecordPolicy,
    SearchLane,
    VerificationMode,
    capability_registry_problems,
)
from project_brain.id_grammar import ID_GRAMMARS
from project_brain.schema import KIND_REQUIRED, KIND_TRUTH_ROLE, VALID_KINDS
from project_brain.surface import _EXTRACTORS


EXPECTED_POLICIES = {
    "EvidenceManifest": (
        "forbidden", False, True, "forbidden", False, "none",
        "dedicated_proof", "not_implicit",
    ),
    "EvidenceRef": (
        "allowed", False, True, "allowed", False, "none",
        "common_verification", "required_for_common_verification",
    ),
    "ReviewRecord": (
        "forbidden", False, False, "forbidden", False, "none",
        "not_applicable", "not_applicable",
    ),
    "EventLedgerRecord": (
        "allowed", False, True, "allowed", False, "objects",
        "common_verification", "required_for_common_verification",
    ),
    "TemporalFact": (
        "allowed", False, True, "allowed", False, "objects",
        "common_verification", "required_for_common_verification",
    ),
    "CodeLocator": (
        "allowed", False, True, "allowed", False, "objects",
        "common_verification", "required_for_common_verification",
    ),
    "DomainContext": (
        "allowed", True, True, "allowed", False, "objects",
        "common_verification", "required_for_common_verification",
    ),
    "GlossaryTerm": (
        "allowed", True, True, "allowed", True, "objects",
        "common_verification", "required_for_common_verification",
    ),
    "ContextProjection": (
        "prompt_payload_only", False, True, "dedicated_verification", False,
        "projection_reuse", "common_verification,dedicated_proof",
        "required_for_common_verification",
    ),
    "CurrentView": (
        "forbidden", False, True, "forbidden", False, "objects",
        "dedicated_proof", "not_implicit",
    ),
    "KnowledgePage": (
        "forbidden", False, True, "forbidden", False, "none",
        "dedicated_proof", "not_implicit",
    ),
    "IndexRecord": (
        "forbidden", False, False, "forbidden", False, "none",
        "not_applicable", "not_applicable",
    ),
    "SpecDocument": (
        "forbidden", False, True, "forbidden", False, "none",
        "dedicated_proof", "not_implicit",
    ),
    "SpecRevision": (
        "forbidden", False, True, "forbidden", False, "none",
        "dedicated_proof", "not_implicit",
    ),
    "SlideRef": (
        "forbidden", False, True, "forbidden", False, "none",
        "dedicated_proof", "not_implicit",
    ),
    "SlackThread": (
        "forbidden", False, True, "forbidden", False, "none",
        "dedicated_proof", "not_implicit",
    ),
    "DecisionRecord": (
        "allowed", True, True, "allowed", False, "objects",
        "common_verification", "required_for_common_verification",
    ),
    "DomainMapping": (
        "allowed", True, True, "allowed", False, "objects",
        "common_verification", "required_for_common_verification",
    ),
    "Insight": (
        "forbidden", False, True, "forbidden", False, "advisories",
        "dedicated_proof", "not_implicit",
    ),
}

EXPECTED_REQUIREMENTS = {
    "EvidenceManifest": ("source_acl_redaction_verified", "source_recapture_and_redaction_update"),
    "EvidenceRef": ("locator_and_manifest_verified", "evidence_recapture_and_locator_repair"),
    "ReviewRecord": ("engine_generated_with_target_write", "reviewed_change_and_id_migration"),
    "EventLedgerRecord": ("event_and_source_verified", "correction_or_follow_up_event"),
    "TemporalFact": ("event_scope_and_time_verified", "validity_and_supersession_update"),
    "CodeLocator": ("checkout_verified", "code_verifier_and_mark_checked"),
    "DomainContext": ("independent_boundary_verified", "context_update_and_replace"),
    "GlossaryTerm": (
        "glossary_qualification_verified",
        "common_glossary_gate_and_approved_migration",
    ),
    "ContextProjection": ("context_md_builder_path", "projection_build_and_refresh"),
    "CurrentView": ("source_aggregate_verified", "source_based_rebuild_and_replace"),
    "KnowledgePage": ("source_binding_verified", "source_based_rebuild_and_replace"),
    "IndexRecord": ("engine_generated", "index_rebuild"),
    "SpecDocument": ("canonical_locator_verified", "source_recapture"),
    "SpecRevision": ("document_and_revision_bound", "append_new_revision"),
    "SlideRef": ("revision_and_slide_bound", "source_recapture"),
    "SlackThread": ("thread_capture_verified", "thread_recapture"),
    "DecisionRecord": ("decision_source_and_impact_verified", "decision_and_back_reference_update"),
    "DomainMapping": ("meaning_boundary_and_evidence_verified", "guarded_bundle_update"),
    "Insight": ("source_synthesis_verified", "source_aware_replace_and_supersede"),
}


def _policy_tuple(capability: KindCapabilities) -> tuple[object, ...]:
    verification = ",".join(sorted(mode.value for mode in capability.verification_modes))
    return (
        capability.candidate_policy.value,
        capability.query_confirmation,
        capability.direct_reviewed,
        capability.manual_promotion.value,
        capability.automatic_promotion,
        capability.search_lane.value,
        verification,
        capability.review_record_policy.value,
    )


def test_registry_contains_the_current_19_kinds_exactly_once():
    assert len(CAPABILITY_REGISTRY) == 19
    assert set(CAPABILITY_REGISTRY) == set(EXPECTED_POLICIES)
    assert "GlossaryClassificationRecord" not in CAPABILITY_REGISTRY
    assert {
        kind: _policy_tuple(capability)
        for kind, capability in CAPABILITY_REGISTRY.items()
    } == EXPECTED_POLICIES
    assert {
        kind: (capability.direct_reviewed_requirement, capability.update_owner)
        for kind, capability in CAPABILITY_REGISTRY.items()
    } == EXPECTED_REQUIREMENTS


def test_every_capability_declares_all_required_dimensions():
    expected_fields = {
        "candidate_policy",
        "query_confirmation",
        "direct_reviewed",
        "direct_reviewed_requirement",
        "manual_promotion",
        "automatic_promotion",
        "search_lane",
        "update_owner",
        "graph_exposure",
        "verification_modes",
        "review_record_policy",
    }
    for capability in CAPABILITY_REGISTRY.values():
        assert set(asdict(capability)) == expected_fields
        assert capability.direct_reviewed_requirement
        assert capability.update_owner
        assert capability.graph_exposure is GraphExposure.DEFAULT


def test_registry_matches_existing_kind_and_search_registries():
    kinds = frozenset(CAPABILITY_REGISTRY)
    assert kinds == VALID_KINDS
    assert kinds == frozenset(KIND_REQUIRED)
    assert kinds == frozenset(KIND_TRUTH_ROLE)
    assert kinds == frozenset(ID_GRAMMARS)

    searchable = {
        kind
        for kind, capability in CAPABILITY_REGISTRY.items()
        if capability.search_lane is not SearchLane.NONE
    }
    assert searchable == frozenset(_EXTRACTORS)
    assert CAPABILITY_REGISTRY["ContextProjection"].search_lane is SearchLane.PROJECTION_REUSE
    assert CAPABILITY_REGISTRY["Insight"].search_lane is SearchLane.ADVISORIES


def test_registry_matches_the_19_installed_kind_templates():
    template_dir = (
        Path(__file__).parents[1]
        / "src/project_brain/templates/ingest/references/object-templates/kinds"
    )
    template_kinds = {
        path.name.removesuffix(".template.json")
        for path in template_dir.glob("*.template.json")
    }
    assert template_kinds == set(CAPABILITY_REGISTRY)


def test_structure_check_rejects_missing_kind_and_inconsistent_rows():
    assert capability_registry_problems() == ()

    missing = dict(CAPABILITY_REGISTRY)
    missing.pop("EvidenceRef")
    assert capability_registry_problems(missing) == (
        "capability registry missing kinds: EvidenceRef",
    )

    malformed = dict(CAPABILITY_REGISTRY)
    malformed["EvidenceRef"] = {}
    assert capability_registry_problems(malformed) == (
        "EvidenceRef: capability row must be KindCapabilities",
    )

    inconsistent = dict(CAPABILITY_REGISTRY)
    inconsistent["GlossaryTerm"] = replace(
        inconsistent["GlossaryTerm"],
        automatic_promotion=True,
        manual_promotion=ManualPromotionPolicy.FORBIDDEN,
    )
    assert capability_registry_problems(inconsistent) == (
        "GlossaryTerm: automatic promotion requires manual promotion support",
    )


def test_policy_enums_are_closed():
    assert set(CandidatePolicy) == {
        CandidatePolicy.FORBIDDEN,
        CandidatePolicy.ALLOWED,
        CandidatePolicy.PROMPT_PAYLOAD_ONLY,
    }
    assert set(ManualPromotionPolicy) == {
        ManualPromotionPolicy.FORBIDDEN,
        ManualPromotionPolicy.ALLOWED,
        ManualPromotionPolicy.DEDICATED_VERIFICATION,
    }
    assert set(VerificationMode) == {
        VerificationMode.COMMON,
        VerificationMode.DEDICATED,
        VerificationMode.NOT_APPLICABLE,
    }
    assert set(ReviewRecordPolicy) == {
        ReviewRecordPolicy.REQUIRED_FOR_COMMON_VERIFICATION,
        ReviewRecordPolicy.NOT_IMPLICIT,
        ReviewRecordPolicy.NOT_APPLICABLE,
    }
