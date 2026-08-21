from copy import deepcopy
from pathlib import Path

from project_brain.dedicated_proof import (
    DedicatedProofContext,
    DedicatedProofMaterial,
    DedicatedProofProfile,
    dedicated_proof_dict,
    evaluate_dedicated_proof,
    prepare_dedicated_proof,
    semantic_source_bindings,
)
from project_brain.hash_utils import source_content_hash
from project_brain.mutation import (
    MutationOperation,
    MutationRequest,
    MutationService,
    canonical_unstamped_intent,
)
from project_brain.objbase import base
from project_brain.store import BrainStore
from project_brain.transaction_receipt import receipt_from_result
from project_brain.write_semantics import ObjectActionKind
from tests.coverage_helpers import direct_coverage


T = "2026-08-21T00:00:00+09:00"


def _fact(*, updated_at: str = T, value: str = "ready") -> dict:
    return base(
        {
            "id": "fact.feature.release-status",
            "kind": "TemporalFact",
            "status": "reviewed",
            "truth_role": "fact",
            "title": "Release status",
            "subject": "feature",
            "predicate": "release-status",
            "value": value,
            "scope": {"project": "neutral"},
            "valid_from": T,
            "derived_from_event_id": "event.feature.release",
            "confidence": "high",
        },
        tags=[],
        created_at=T,
        updated_at=updated_at,
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


def _view(*, summary: str = "Ready", status: str = "reviewed") -> dict:
    return base(
        {
            "id": "view.feature-status.main",
            "kind": "CurrentView",
            "status": status,
            "truth_role": "synthesis",
            "title": "Current release status",
            "view_type": "feature_status",
            "as_of": T,
            "source_fact_ids": ["fact.feature.release-status"],
            "source_event_ids": ["event.feature.release"],
            "summary": summary,
        },
        tags=[],
        created_at=T,
        updated_at=T,
    )


def _material(context: DedicatedProofContext) -> DedicatedProofMaterial:
    assert context.brain_root is None or context.brain_root.is_absolute()
    assert context.receipt["kind"] == "builder"
    return DedicatedProofMaterial(
        sources=semantic_source_bindings(
            context.after,
            context.store,
            fields=("source_fact_ids", "source_event_ids"),
        ),
        inputs={"as_of": context.after["as_of"]},
    )


PROFILE = DedicatedProofProfile(
    id="dedicated.test-current-view",
    version=1,
    subject_kind="CurrentView",
    selector=lambda subject: True,
    materialize=_material,
    receipt_kinds=frozenset({"builder"}),
)


def _proof(
    store: BrainStore,
    *,
    brain_root: Path | None = None,
    before: dict | None = None,
    after: dict | None = None,
    action: ObjectActionKind = ObjectActionKind.CREATE,
):
    return prepare_dedicated_proof(
        after or _view(),
        store,
        brain_root=brain_root,
        before=before,
        action=action,
        profile=PROFILE,
        producer={"kind": "builder", "id": "current-view-builder", "version": "1"},
        verifiers=(),
        receipt={"kind": "builder", "id": "a" * 64},
    )


def _write(brain_root: Path, obj: dict) -> None:
    path = BrainStore.object_path(brain_root, obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(BrainStore.object_bytes(obj))


def _request(
    brain_root: Path,
    objects: tuple[dict, ...],
    *,
    proofs=(),
    operation: MutationOperation = MutationOperation.INGEST,
) -> MutationRequest:
    return MutationRequest(
        operation=operation,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=objects,
        dedicated_proofs=tuple(proofs),
        coverage=direct_coverage(*objects) if operation is MutationOperation.INGEST else None,
    )


def test_dedicated_proof_recomputes_source_meaning_without_timestamp_noise():
    fact = _fact()
    event = _event()
    store = BrainStore({fact["id"]: fact, event["id"]: event})
    proof = _proof(store)

    ready = evaluate_dedicated_proof(
        proof,
        store=store,
        before=None,
        after=_view(),
        action=ObjectActionKind.CREATE,
        profile=PROFILE,
    )
    assert (ready.proof_status, ready.reason_codes) == ("ready", ())

    timestamp_only = deepcopy(fact)
    timestamp_only["updated_at"] = "2099-01-01T00:00:00+09:00"
    timestamp_store = BrainStore({
        timestamp_only["id"]: timestamp_only,
        event["id"]: event,
    })
    assert source_content_hash([timestamp_only]) == source_content_hash([fact])
    assert evaluate_dedicated_proof(
        proof,
        store=timestamp_store,
        before=None,
        after=_view(),
        action=ObjectActionKind.CREATE,
        profile=PROFILE,
    ).proof_status == "ready"

    changed = _fact(value="blocked")
    changed_store = BrainStore({changed["id"]: changed, event["id"]: event})
    stale = evaluate_dedicated_proof(
        proof,
        store=changed_store,
        before=None,
        after=_view(),
        action=ObjectActionKind.CREATE,
        profile=PROFILE,
    )
    assert (stale.proof_status, stale.reason_codes) == (
        "stale",
        ("sources_changed",),
    )


def test_mutation_keeps_proof_ephemeral_and_binds_exact_manifest_intent(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    fact = _fact()
    event = _event()
    _write(brain_root, fact)
    _write(brain_root, event)
    store = BrainStore.load(brain_root)
    view = _view()
    proof = _proof(store, brain_root=brain_root)
    request = _request(brain_root, (view,), proofs=(proof,))
    service = MutationService(dedicated_proof_profiles=(PROFILE,))

    preview = service.preview((view,), request=request)
    assert preview.ok is True
    intent, _, _ = canonical_unstamped_intent(request, preview)
    assert intent["request"]["dedicated_proofs"] == [dedicated_proof_dict(proof)]

    result = service.apply((view,), request=request)

    assert result.ok is True
    stored = BrainStore.load(brain_root).get(view["id"])
    assert "dedicated_proof" not in stored
    assert result.manifest is not None
    assert list(result.manifest.dedicated_proofs) == [dedicated_proof_dict(proof)]
    assert not BrainStore.load(brain_root).by_kind("ReviewRecord")
    receipt = receipt_from_result(result, committed=True)
    assert receipt.operation == "ingest"
    assert [dict(row) for row in receipt.changed_objects] == [
        {"action": "create", "id": view["id"], "kind": "CurrentView"}
    ]


def test_stale_source_revalidation_is_zero_write(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    fact = _fact()
    event = _event()
    for obj in (fact, event):
        _write(brain_root, obj)
    old_store = BrainStore.load(brain_root)
    proof = _proof(old_store, brain_root=brain_root)
    _write(brain_root, _fact(value="blocked"))
    view = _view()

    result = MutationService(dedicated_proof_profiles=(PROFILE,)).apply(
        (view,),
        request=_request(brain_root, (view,), proofs=(proof,)),
    )

    assert (result.ok, result.error_code) == (False, "dedicated_proof_not_ready")
    assert not BrainStore.object_path(brain_root, view).exists()


def test_legacy_reviewed_first_meaning_update_requires_request_proof(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    fact = _fact()
    event = _event()
    legacy = _view()
    for obj in (fact, event, legacy):
        _write(brain_root, obj)
    changed = _view(summary="Blocked")
    service = MutationService(dedicated_proof_profiles=(PROFILE,))

    missing = service.apply(
        (changed,),
        request=_request(brain_root, (changed,)),
    )
    assert (missing.ok, missing.error_code) == (
        False,
        "dedicated_proof_missing",
    )

    store = BrainStore.load(brain_root)
    proof = _proof(
        store,
        brain_root=brain_root,
        before=legacy,
        after=changed,
        action=ObjectActionKind.UPDATE,
    )
    result = service.apply(
        (changed,),
        request=_request(brain_root, (changed,), proofs=(proof,)),
    )
    assert result.ok is True
    assert BrainStore.load(brain_root).get(legacy["id"])["summary"] == "Blocked"


def test_capability_gate_rejects_dedicated_candidate_and_forbidden_promotion(
    tmp_path,
):
    brain_root = (tmp_path / "brain").resolve()
    candidate = _view(status="candidate")
    service = MutationService(dedicated_proof_profiles=(PROFILE,))

    create = service.apply(
        (candidate,),
        request=_request(brain_root, (candidate,)),
    )
    assert (create.ok, create.error_code) == (
        False,
        "dedicated_candidate_forbidden",
    )

    _write(brain_root, candidate)
    reviewed = _view()
    promote = service.apply(
        (reviewed,),
        request=_request(
            brain_root,
            (reviewed,),
            operation=MutationOperation.PROMOTE,
        ),
    )
    assert (promote.ok, promote.error_code) == (
        False,
        "dedicated_promotion_forbidden",
    )
