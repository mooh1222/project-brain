from copy import deepcopy
from pathlib import Path

import pytest

from project_brain.context_projection import build_context_projection
from project_brain.dedicated_proof import (
    builtin_dedicated_proof_profiles,
    dedicated_proof_profile,
)
from project_brain.dedicated_proof_derived import (
    CONTEXT_MD_PROFILE_ID,
    CURRENT_VIEW_PROFILE_ID,
    INSIGHT_PROFILE_ID,
    KNOWLEDGE_PAGE_PROFILE_ID,
    prepare_derived_dedicated_proof,
)
from project_brain.hash_utils import source_content_hash
from project_brain.mutation import MutationOperation, MutationRequest, MutationService
from project_brain.objbase import base
from project_brain.store import BrainStore
from project_brain.write_semantics import ObjectActionKind
from tests.coverage_helpers import direct_coverage


T = "2026-08-21T00:00:00+09:00"
BUILDER = {"kind": "builder", "id": "derived-builder", "version": "1"}
SYNTHESIZER = {"kind": "synthesizer", "id": "insight-builder", "version": "1"}
VERIFIER = {
    "kind": "synthesis-verifier",
    "id": "independent-verifier",
    "version": "1",
}


def _context(object_id: str, *, display_name: str = "Neutral") -> dict:
    key = object_id.removeprefix("context.")
    return base(
        {
            "id": object_id,
            "kind": "DomainContext",
            "status": "reviewed",
            "truth_role": "domain",
            "title": display_name,
            "context_key": key,
            "project_id": "demo",
            "display_name": display_name,
            "boundary_summary": "A bounded context",
            "in_scope": [],
            "out_of_scope": [],
            "injection_profile": {"default_audience": "coding-agent"},
            "glossary_term_ids": [],
        },
        tags=[],
        created_at=T,
        updated_at=T,
    )


def _event() -> dict:
    return base(
        {
            "id": "event.feature.release",
            "kind": "EventLedgerRecord",
            "status": "reviewed",
            "truth_role": "event",
            "title": "Release event",
            "event_type": "release",
            "happened_at": T,
            "summary": "Released",
            "related_objects": [],
        },
        tags=[],
        created_at=T,
        updated_at=T,
    )


def _fact() -> dict:
    return base(
        {
            "id": "fact.feature.release-status",
            "kind": "TemporalFact",
            "status": "reviewed",
            "truth_role": "fact",
            "title": "Release status",
            "subject": "feature",
            "predicate": "release-status",
            "value": "ready",
            "scope": {"project": "demo"},
            "valid_from": T,
            "derived_from_event_id": "event.feature.release",
            "confidence": "high",
        },
        tags=[],
        created_at=T,
        updated_at=T,
    )


def _view() -> dict:
    return base(
        {
            "id": "view.feature-status.main",
            "kind": "CurrentView",
            "status": "reviewed",
            "truth_role": "synthesis",
            "title": "Current release status",
            "view_type": "feature_status",
            "as_of": T,
            "source_fact_ids": ["fact.feature.release-status"],
            "source_event_ids": ["event.feature.release"],
            "summary": "Ready",
        },
        tags=[],
        created_at=T,
        updated_at=T,
    )


def _page() -> dict:
    return base(
        {
            "id": "page.guide.main",
            "kind": "KnowledgePage",
            "status": "reviewed",
            "truth_role": "synthesis",
            "title": "Guide",
            "category": "guide",
            "path": "docs/guide.md",
            "summary": "Guide summary",
            "source_object_ids": ["context.neutral"],
            "stale_policy": "manual",
        },
        tags=[],
        created_at=T,
        updated_at=T,
    )


def _insight(*, body: str = "Cross-context risk") -> dict:
    return base(
        {
            "id": "insight.neutral.risk",
            "kind": "Insight",
            "status": "reviewed",
            "truth_role": "synthesis",
            "title": "Risk",
            "body": body,
            "insight_type": "cross-cutting-risk",
            "source_object_ids": ["context.neutral", "context.secondary"],
            "scope": "demo",
        },
        tags=[],
        created_at=T,
        updated_at=T,
    )


def _write(brain_root: Path, obj: dict) -> None:
    path = BrainStore.object_path(brain_root, obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(BrainStore.object_bytes(obj))


def _request(
    brain_root: Path,
    objects: tuple[dict, ...],
    proofs,
    *,
    operation: MutationOperation = MutationOperation.INGEST,
) -> MutationRequest:
    return MutationRequest(
        operation=operation,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=objects,
        dedicated_proofs=tuple(sorted(proofs, key=lambda proof: proof.target_id)),
        coverage=direct_coverage(*objects) if operation is MutationOperation.INGEST else None,
    )


def _proof(
    obj: dict,
    store: BrainStore,
    brain_root: Path,
    *,
    before=None,
    action=ObjectActionKind.CREATE,
    receipt="a",
):
    is_insight = obj["kind"] == "Insight"
    return prepare_derived_dedicated_proof(
        obj,
        store,
        brain_root=brain_root,
        before=before,
        action=action,
        producer=SYNTHESIZER if is_insight else BUILDER,
        verifiers=(VERIFIER,) if is_insight else (),
        receipt_id=receipt * 64,
    )


def test_builtin_profiles_cover_only_four_derived_variants():
    profiles = builtin_dedicated_proof_profiles()
    assert {profile.id for profile in profiles} == {
        CURRENT_VIEW_PROFILE_ID,
        KNOWLEDGE_PAGE_PROFILE_ID,
        INSIGHT_PROFILE_ID,
        CONTEXT_MD_PROFILE_ID,
    }
    prompt_payload = {
        "kind": "ContextProjection",
        "format": "prompt_payload",
    }
    assert dedicated_proof_profile(prompt_payload, profiles=profiles) is None


def test_current_view_page_and_insight_write_with_kind_receipts_no_review_record(
    tmp_path,
):
    brain_root = (tmp_path / "brain").resolve()
    sources = (_event(), _fact(), _context("context.neutral"), _context("context.secondary"))
    for source in sources:
        _write(brain_root, source)
    store = BrainStore.load(brain_root)
    objects = (_view(), _page(), _insight())
    proofs = tuple(
        _proof(obj, store, brain_root, receipt=letter)
        for obj, letter in zip(objects, ("a", "b", "c"), strict=True)
    )

    result = MutationService().apply(
        objects,
        request=_request(brain_root, objects, proofs),
    )

    assert result.ok is True
    assert not BrainStore.load(brain_root).by_kind("ReviewRecord")
    assert result.manifest is not None
    assert {
        proof["execution"]["receipt"]["kind"]
        for proof in result.manifest.dedicated_proofs
    } == {
        "current-view-builder",
        "knowledge-page-builder",
        "source-aware-replace",
    }


def test_knowledge_page_builder_and_stale_policy_are_bound(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    _write(brain_root, _context("context.neutral"))
    store = BrainStore.load(brain_root)
    page = _page()
    proof = _proof(page, store, brain_root)
    changed = deepcopy(page)
    changed["stale_policy"] = "source-change"

    result = MutationService().apply(
        (changed,),
        request=_request(brain_root, (changed,), (proof,)),
    )

    assert (result.ok, result.error_code) == (False, "dedicated_proof_not_ready")
    assert not BrainStore.object_path(brain_root, changed).exists()


def test_insight_replace_requires_live_sources_and_synthesis_verifier(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    for source in (_context("context.neutral"), _context("context.secondary")):
        _write(brain_root, source)
    old = _insight()
    _write(brain_root, old)
    store = BrainStore.load(brain_root)
    changed = _insight(body="Updated risk")

    with pytest.raises(ValueError, match="execution_invalid"):
        prepare_derived_dedicated_proof(
            changed,
            store,
            brain_root=brain_root,
            before=old,
            action=ObjectActionKind.UPDATE,
            producer=SYNTHESIZER,
            receipt_id="d" * 64,
        )

    success_root = (tmp_path / "success-brain").resolve()
    for source in (_context("context.neutral"), _context("context.secondary")):
        _write(success_root, source)
    _write(success_root, old)
    success_store = BrainStore.load(success_root)
    success_proof = _proof(
        changed,
        success_store,
        success_root,
        before=old,
        action=ObjectActionKind.UPDATE,
        receipt="e",
    )
    success = MutationService().apply(
        (changed,),
        request=_request(success_root, (changed,), (success_proof,)),
    )
    assert success.ok is True
    assert success.manifest is not None
    replace_receipt = success.manifest.dedicated_proofs[0]["execution"]["receipt"]
    assert replace_receipt["before_sha256"]

    proof = _proof(
        changed,
        store,
        brain_root,
        before=old,
        action=ObjectActionKind.UPDATE,
        receipt="d",
    )
    changed_source = _context("context.secondary", display_name="Changed")
    _write(brain_root, changed_source)

    result = MutationService().apply(
        (changed,),
        request=_request(brain_root, (changed,), (proof,)),
    )
    assert (result.ok, result.error_code) == (False, "dedicated_proof_not_ready")
    assert BrainStore.load(brain_root).get(old["id"])["body"] == old["body"]


def test_context_md_uses_official_freshness_and_builder_identity(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    source = _context("context.neutral")
    _write(brain_root, source)
    store = BrainStore.load(brain_root)
    projection, _content = build_context_projection(
        store,
        source["id"],
        output_locator="docs/contexts/generated/neutral/CONTEXT.md",
        generated_by=BUILDER["id"],
    )
    proof = _proof(projection, store, brain_root, receipt="e")

    result = MutationService().apply(
        (projection,),
        request=_request(
            brain_root,
            (projection,),
            (proof,),
            operation=MutationOperation.PROJECTION,
        ),
    )
    assert result.ok is True
    assert not BrainStore.load(brain_root).by_kind("ReviewRecord")

    drift_root = (tmp_path / "builder-drift-brain").resolve()
    _write(drift_root, source)
    drift_store = BrainStore.load(drift_root)
    drift_projection, _ = build_context_projection(
        drift_store,
        source["id"],
        output_locator="docs/contexts/generated/neutral/CONTEXT.md",
        generated_by=BUILDER["id"],
    )
    drift_proof = _proof(drift_projection, drift_store, drift_root, receipt="a")
    drift_projection["generated_by"] = "different-builder"
    builder_drift = MutationService().apply(
        (drift_projection,),
        request=_request(
            drift_root,
            (drift_projection,),
            (drift_proof,),
            operation=MutationOperation.PROJECTION,
        ),
    )
    assert (builder_drift.ok, builder_drift.error_code) == (
        False,
        "dedicated_proof_not_ready",
    )

    second_root = (tmp_path / "stale-brain").resolve()
    _write(second_root, source)
    old_store = BrainStore.load(second_root)
    stale_projection, _ = build_context_projection(
        old_store,
        source["id"],
        output_locator="docs/contexts/generated/neutral/CONTEXT.md",
        generated_by=BUILDER["id"],
    )
    stale_proof = _proof(stale_projection, old_store, second_root, receipt="f")
    changed_source = deepcopy(source)
    changed_source["boundary_summary"] = "Changed meaning"
    _write(second_root, changed_source)

    stale = MutationService().apply(
        (stale_projection,),
        request=_request(
            second_root,
            (stale_projection,),
            (stale_proof,),
            operation=MutationOperation.PROJECTION,
        ),
    )
    assert (stale.ok, stale.error_code) == (
        False,
        "dedicated_proof_not_ready",
    )


def test_existing_context_md_updates_with_current_dedicated_proof(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    source = _context("context.neutral")
    _write(brain_root, source)
    initial_store = BrainStore.load(brain_root)
    existing, _ = build_context_projection(
        initial_store,
        source["id"],
        output_locator="docs/contexts/generated/neutral/CONTEXT.md",
        generated_by=BUILDER["id"],
    )
    initial_proof = _proof(existing, initial_store, brain_root, receipt="a")
    created = MutationService().apply(
        (existing,),
        request=_request(
            brain_root,
            (existing,),
            (initial_proof,),
            operation=MutationOperation.PROJECTION,
        ),
    )
    assert created.ok is True
    existing = BrainStore.load(brain_root).get(existing["id"])

    current_store = BrainStore.load(brain_root)
    replacement, _ = build_context_projection(
        current_store,
        source["id"],
        output_locator="docs/contexts/generated/neutral/CURRENT_CONTEXT.md",
        generated_by=BUILDER["id"],
    )
    proof = _proof(
        replacement,
        current_store,
        brain_root,
        before=existing,
        action=ObjectActionKind.UPDATE,
        receipt="b",
    )

    result = MutationService().apply(
        (replacement,),
        request=_request(
            brain_root,
            (replacement,),
            (proof,),
            operation=MutationOperation.PROJECTION,
        ),
    )

    assert result.ok is True
    assert result.manifest is not None
    assert result.manifest.dedicated_proofs[0]["action"] == "update"
    assert (
        BrainStore.load(brain_root).get(existing["id"])["output_locator"]
        == replacement["output_locator"]
    )


def test_source_timestamp_only_does_not_stale_builtin_profile(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    source = _context("context.neutral")
    _write(brain_root, source)
    store = BrainStore.load(brain_root)
    page = _page()
    proof = _proof(page, store, brain_root)
    timestamp_only = deepcopy(source)
    timestamp_only["updated_at"] = "2099-01-01T00:00:00+09:00"
    assert source_content_hash([timestamp_only]) == source_content_hash([source])
    _write(brain_root, timestamp_only)

    result = MutationService().apply(
        (page,),
        request=_request(brain_root, (page,), (proof,)),
    )
    assert result.ok is True
