"""파생·종합 객체의 종류별 전용 증거 profile."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path

from project_brain.dedicated_proof import (
    DedicatedProof,
    DedicatedProofContext,
    DedicatedProofMaterial,
    DedicatedProofProfile,
    prepare_dedicated_proof,
    semantic_source_bindings,
)
from project_brain.hash_utils import stable_json, verification_content_hash
from project_brain.lint import projection_is_fresh
from project_brain.store import BrainStore
from project_brain.write_semantics import ObjectActionKind


CURRENT_VIEW_PROFILE_ID = "dedicated.current-view"
KNOWLEDGE_PAGE_PROFILE_ID = "dedicated.knowledge-page"
INSIGHT_PROFILE_ID = "dedicated.insight"
CONTEXT_MD_PROFILE_ID = "dedicated.context-projection-context-md"


def _sources_sha256(sources: Sequence[Mapping[str, str]]) -> str:
    return hashlib.sha256(
        stable_json({"sources": [dict(row) for row in sources]}).encode("utf-8")
    ).hexdigest()


def _require_source_kinds(
    context: DedicatedProofContext,
    *,
    field: str,
    kind: str,
) -> None:
    for source_id in context.after.get(field) or []:
        if context.store.get(source_id).get("kind") != kind:
            raise ValueError(f"{field} requires {kind} sources")


def _current_view_material(
    context: DedicatedProofContext,
) -> DedicatedProofMaterial:
    _require_source_kinds(
        context,
        field="source_fact_ids",
        kind="TemporalFact",
    )
    _require_source_kinds(
        context,
        field="source_event_ids",
        kind="EventLedgerRecord",
    )
    return DedicatedProofMaterial(
        sources=semantic_source_bindings(
            context.after,
            context.store,
            fields=("source_fact_ids", "source_event_ids"),
        ),
        inputs={"as_of": context.after.get("as_of")},
    )


def _knowledge_page_material(
    context: DedicatedProofContext,
) -> DedicatedProofMaterial:
    return DedicatedProofMaterial(
        sources=semantic_source_bindings(
            context.after,
            context.store,
            fields=("source_object_ids",),
        ),
        inputs={"stale_policy": context.after.get("stale_policy")},
    )


def _insight_material(context: DedicatedProofContext) -> DedicatedProofMaterial:
    return DedicatedProofMaterial(
        sources=semantic_source_bindings(
            context.after,
            context.store,
            fields=("source_object_ids",),
        ),
        inputs={},
    )


def _context_md_material(
    context: DedicatedProofContext,
) -> DedicatedProofMaterial:
    sources = semantic_source_bindings(
        context.after,
        context.store,
        fields=("source_object_ids",),
    )
    return DedicatedProofMaterial(
        sources=sources,
        inputs={
            "source_content_hash": context.after.get("source_content_hash"),
            "projection_hash": context.after.get("projection_hash"),
            "generated_by": context.after.get("generated_by"),
            "fresh": projection_is_fresh(
                context.store,
                dict(context.after),
            ),
        },
    )


def _current_view_execution_problems(
    context: DedicatedProofContext,
    proof: DedicatedProof,
) -> tuple[str, ...]:
    receipt = proof.receipt
    expected_keys = {
        "kind", "id", "builder_id", "source_sha256", "as_of",
    }
    problems = []
    if set(receipt) != expected_keys:
        problems.append("current view builder receipt keys are invalid")
    if proof.producer.get("kind") != "builder":
        problems.append("current view producer must be a builder")
    if receipt.get("builder_id") != proof.producer.get("id"):
        problems.append("current view builder identity changed")
    if receipt.get("source_sha256") != _sources_sha256(proof.sources):
        problems.append("current view builder source binding changed")
    if receipt.get("as_of") != context.after.get("as_of"):
        problems.append("current view as-of binding changed")
    return tuple(problems)


def _knowledge_page_execution_problems(
    context: DedicatedProofContext,
    proof: DedicatedProof,
) -> tuple[str, ...]:
    receipt = proof.receipt
    expected_keys = {
        "kind", "id", "builder_id", "source_sha256", "stale_policy",
    }
    problems = []
    if set(receipt) != expected_keys:
        problems.append("knowledge page builder receipt keys are invalid")
    if proof.producer.get("kind") != "builder":
        problems.append("knowledge page producer must be a builder")
    if receipt.get("builder_id") != proof.producer.get("id"):
        problems.append("knowledge page builder identity changed")
    if receipt.get("source_sha256") != _sources_sha256(proof.sources):
        problems.append("knowledge page source binding changed")
    if receipt.get("stale_policy") != context.after.get("stale_policy"):
        problems.append("knowledge page stale policy changed")
    return tuple(problems)


def _insight_execution_problems(
    context: DedicatedProofContext,
    proof: DedicatedProof,
) -> tuple[str, ...]:
    receipt = proof.receipt
    expected_keys = {
        "kind",
        "id",
        "producer_id",
        "source_sha256",
        "before_sha256",
        "synthesis_verifier_id",
    }
    problems = []
    if set(receipt) != expected_keys:
        problems.append("insight replace receipt keys are invalid")
    if receipt.get("producer_id") != proof.producer.get("id"):
        problems.append("insight producer identity changed")
    if receipt.get("source_sha256") != _sources_sha256(proof.sources):
        problems.append("insight source binding changed")
    before_sha256 = (
        verification_content_hash(
            context.before,
            direct_evidence_fields=(),
        )
        if context.before is not None
        else None
    )
    if receipt.get("before_sha256") != before_sha256:
        problems.append("insight replace source changed")
    verifier_id = receipt.get("synthesis_verifier_id")
    if not any(
        verifier.get("kind") == "synthesis-verifier"
        and verifier.get("id") == verifier_id
        for verifier in proof.verifiers
    ):
        problems.append("insight synthesis verifier changed")
    return tuple(problems)


def _context_md_execution_problems(
    context: DedicatedProofContext,
    proof: DedicatedProof,
) -> tuple[str, ...]:
    receipt = proof.receipt
    expected_keys = {
        "kind",
        "id",
        "builder_id",
        "source_content_hash",
        "projection_hash",
    }
    problems = []
    if set(receipt) != expected_keys:
        problems.append("context projection builder receipt keys are invalid")
    if proof.producer.get("kind") != "builder":
        problems.append("context projection producer must be a builder")
    if (
        receipt.get("builder_id") != proof.producer.get("id")
        or proof.producer.get("id") != context.after.get("generated_by")
    ):
        problems.append("context projection builder identity changed")
    if (
        receipt.get("source_content_hash")
        != context.after.get("source_content_hash")
        or not projection_is_fresh(context.store, dict(context.after))
    ):
        problems.append("context projection sources are stale")
    if receipt.get("projection_hash") != context.after.get("projection_hash"):
        problems.append("context projection output binding changed")
    return tuple(problems)


CURRENT_VIEW_PROFILE = DedicatedProofProfile(
    id=CURRENT_VIEW_PROFILE_ID,
    version=1,
    subject_kind="CurrentView",
    selector=lambda _subject: True,
    materialize=_current_view_material,
    receipt_kinds=frozenset({"current-view-builder"}),
    execution_problems=_current_view_execution_problems,
)

KNOWLEDGE_PAGE_PROFILE = DedicatedProofProfile(
    id=KNOWLEDGE_PAGE_PROFILE_ID,
    version=1,
    subject_kind="KnowledgePage",
    selector=lambda _subject: True,
    materialize=_knowledge_page_material,
    receipt_kinds=frozenset({"knowledge-page-builder"}),
    execution_problems=_knowledge_page_execution_problems,
)

INSIGHT_PROFILE = DedicatedProofProfile(
    id=INSIGHT_PROFILE_ID,
    version=1,
    subject_kind="Insight",
    selector=lambda _subject: True,
    materialize=_insight_material,
    receipt_kinds=frozenset({"source-aware-replace"}),
    minimum_verifiers=1,
    execution_problems=_insight_execution_problems,
)

CONTEXT_MD_PROFILE = DedicatedProofProfile(
    id=CONTEXT_MD_PROFILE_ID,
    version=1,
    subject_kind="ContextProjection",
    selector=lambda subject: subject.get("format") == "context_md",
    materialize=_context_md_material,
    receipt_kinds=frozenset({"context-projection-builder"}),
    execution_problems=_context_md_execution_problems,
)

DERIVED_PROFILES = (
    CONTEXT_MD_PROFILE,
    CURRENT_VIEW_PROFILE,
    INSIGHT_PROFILE,
    KNOWLEDGE_PAGE_PROFILE,
)


def prepare_derived_dedicated_proof(
    after: Mapping[str, object],
    store: BrainStore,
    *,
    brain_root: Path | None,
    before: Mapping[str, object] | None,
    action: ObjectActionKind,
    producer: Mapping[str, str],
    verifiers: Sequence[Mapping[str, str]] = (),
    receipt_id: str,
) -> DedicatedProof:
    """네 파생 profile의 종류별 receipt를 만들고 공통 envelope를 준비한다."""
    profile = next(
        (
            candidate
            for candidate in DERIVED_PROFILES
            if after.get("kind") == candidate.subject_kind
            and candidate.selector(after)
        ),
        None,
    )
    if profile is None:
        raise ValueError("subject has no derived dedicated proof profile")
    context = DedicatedProofContext(
        brain_root=brain_root,
        store=store,
        before=before,
        after=after,
        action=action,
        receipt={},
    )
    sources = profile.materialize(context).sources
    if profile is CURRENT_VIEW_PROFILE:
        receipt = {
            "kind": "current-view-builder",
            "id": receipt_id,
            "builder_id": producer.get("id"),
            "source_sha256": _sources_sha256(sources),
            "as_of": after.get("as_of"),
        }
    elif profile is KNOWLEDGE_PAGE_PROFILE:
        receipt = {
            "kind": "knowledge-page-builder",
            "id": receipt_id,
            "builder_id": producer.get("id"),
            "source_sha256": _sources_sha256(sources),
            "stale_policy": after.get("stale_policy"),
        }
    elif profile is INSIGHT_PROFILE:
        synthesis_verifiers = [
            verifier
            for verifier in verifiers
            if verifier.get("kind") == "synthesis-verifier"
        ]
        verifier_id = (
            synthesis_verifiers[0].get("id")
            if synthesis_verifiers
            else None
        )
        receipt = {
            "kind": "source-aware-replace",
            "id": receipt_id,
            "producer_id": producer.get("id"),
            "source_sha256": _sources_sha256(sources),
            "before_sha256": (
                verification_content_hash(before, direct_evidence_fields=())
                if before is not None
                else None
            ),
            "synthesis_verifier_id": verifier_id,
        }
    else:
        receipt = {
            "kind": "context-projection-builder",
            "id": receipt_id,
            "builder_id": producer.get("id"),
            "source_content_hash": after.get("source_content_hash"),
            "projection_hash": after.get("projection_hash"),
        }
    return prepare_dedicated_proof(
        after,
        store,
        brain_root=brain_root,
        before=before,
        action=action,
        producer=producer,
        verifiers=verifiers,
        receipt=receipt,
        profile=profile,
    )
