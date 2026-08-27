from collections.abc import Callable
import json
import time
from types import MappingProxyType
from unittest import mock

import pytest

from project_brain import corpus_io
from project_brain.evidence_preparation import (
    EvidencePreparationError,
    ProjectedStore,
    plan_base,
)
from project_brain.evidence_plan import EvidencePlanRequirement
from project_brain.mutation import MutationService
from project_brain.store import BrainStore


_STAMP = "2026-08-27T09:00:00+09:00"


def _candidate(object_id: str, meaning: str, *, stamp: str = _STAMP) -> dict:
    return {
        "id": object_id,
        "kind": "DomainMapping",
        "status": "candidate",
        "title": f"Candidate {object_id.rsplit('.', 1)[-1]}",
        "meaning": meaning,
        "created_at": stamp,
        "updated_at": stamp,
    }


def _decoded(value: bytes) -> dict:
    return json.loads(value.decode("utf-8"))


def _object(
    object_id: str,
    *,
    kind: str,
    status: str,
    stamp: str = _STAMP,
    **fields: object,
) -> dict:
    return {
        "id": object_id,
        "kind": kind,
        "status": status,
        "title": object_id,
        "value": object_id,
        "created_at": stamp,
        "updated_at": stamp,
        **fields,
    }


@pytest.mark.parametrize(
    "after_images,delete_ids",
    (
        (
            [
                _candidate("candidate.duplicate", "first"),
                _candidate("candidate.duplicate", "second"),
            ],
            (),
        ),
        ([], ("candidate.delete", "candidate.delete")),
        ([_candidate("candidate.live", "planned")], ("candidate.live",)),
        ([], ("candidate.missing",)),
    ),
    ids=(
        "duplicate-after",
        "duplicate-delete",
        "after-delete-overlap",
        "missing-delete",
    ),
)
@pytest.mark.parametrize("seam", (plan_base, ProjectedStore))
def test_e2_public_seams_reject_invalid_base_ids_before_planning(
    after_images: list[dict],
    delete_ids: tuple[str, ...],
    seam: Callable[..., object],
) -> None:
    live = _candidate("candidate.live", "live")
    delete = _candidate("candidate.delete", "live")
    store = BrainStore({live["id"]: live, delete["id"]: delete})

    with pytest.raises(EvidencePreparationError) as raised:
        seam(store, after_images, delete_ids=delete_ids)

    assert raised.value.code == "evidence_base_plan_invalid"


def test_base_plan_four_actions():
    before_update = _candidate("candidate.update", "old")
    before_same = _candidate("candidate.same", "same")
    before_delete = _candidate("candidate.delete", "gone")
    store = BrainStore({
        before_update["id"]: before_update,
        before_same["id"]: before_same,
        before_delete["id"]: before_delete,
    })

    plan = plan_base(
        store,
        [
            _candidate("candidate.create", "new"),
            _candidate("candidate.update", "new", stamp="2099-01-01T00:00:00Z"),
            _candidate("candidate.same", "same", stamp="2099-01-01T00:00:00Z"),
        ],
        delete_ids=("candidate.delete",),
    )

    assert [(target.target_id, target.action) for target in plan.targets] == [
        ("candidate.create", "create"),
        ("candidate.delete", "delete"),
        ("candidate.same", "no_change"),
        ("candidate.update", "update"),
    ]

    targets = {target.target_id: target for target in plan.targets}
    assert targets["candidate.create"].before_unstamped_bytes is None
    assert _decoded(targets["candidate.create"].base_unstamped_bytes) == {
        "id": "candidate.create",
        "kind": "DomainMapping",
        "status": "candidate",
        "title": "Candidate create",
        "meaning": "new",
    }
    assert targets["candidate.create"].base_semantic_sha256 == (
        "dfc395cf2fd856d8e01a791e66cd2435f8ac329acb71c7faa029a5c7a721c7c9"
    )

    assert _decoded(targets["candidate.update"].before_unstamped_bytes) == {
        "id": "candidate.update",
        "kind": "DomainMapping",
        "status": "candidate",
        "title": "Candidate update",
        "meaning": "old",
    }
    assert _decoded(targets["candidate.update"].base_unstamped_bytes) == {
        "id": "candidate.update",
        "kind": "DomainMapping",
        "status": "candidate",
        "title": "Candidate update",
        "meaning": "new",
    }
    assert targets["candidate.update"].before_semantic_sha256 == (
        "a38f52220abe4b1246fb635a6ffabde6deee393bc4c23b340d382bffd90622b1"
    )
    assert targets["candidate.update"].base_semantic_sha256 == (
        "1555b1fdf81067680370c9c13cd2644b67e8c57cfb16a807eac787c5e7f07570"
    )

    assert targets["candidate.same"].before_unstamped_bytes == (
        b'{\n'
        b'  "id": "candidate.same",\n'
        b'  "kind": "DomainMapping",\n'
        b'  "status": "candidate",\n'
        b'  "title": "Candidate same",\n'
        b'  "meaning": "same"\n'
        b'}\n'
    )
    assert targets["candidate.same"].base_unstamped_bytes == (
        b'{\n'
        b'  "id": "candidate.same",\n'
        b'  "kind": "DomainMapping",\n'
        b'  "status": "candidate",\n'
        b'  "title": "Candidate same",\n'
        b'  "meaning": "same"\n'
        b'}\n'
    )
    assert targets["candidate.same"].before_semantic_sha256 == (
        "75b3d37f454e1717e21f154976ddc11104f2b1573d53ec651b588954034d55dd"
    )
    assert targets["candidate.same"].base_semantic_sha256 == (
        "75b3d37f454e1717e21f154976ddc11104f2b1573d53ec651b588954034d55dd"
    )

    assert targets["candidate.delete"].before_unstamped_bytes == (
        b'{\n'
        b'  "id": "candidate.delete",\n'
        b'  "kind": "DomainMapping",\n'
        b'  "status": "candidate",\n'
        b'  "title": "Candidate delete",\n'
        b'  "meaning": "gone"\n'
        b'}\n'
    )
    assert targets["candidate.delete"].before_semantic_sha256 == (
        "afd53ffe5f374dbff73feddc8a10bdf00fe8671fb40ae5c7b429d27628f54d59"
    )
    assert targets["candidate.delete"].base_unstamped_bytes is None
    assert targets["candidate.delete"].base_semantic_sha256 is None


def test_projected_store_after_images_and_deletes():
    live_update = _candidate("candidate.update", "live")
    live_delete = _candidate("candidate.delete", "live")
    live_keep = _candidate("candidate.keep", "live")
    store = BrainStore({
        live_update["id"]: live_update,
        live_delete["id"]: live_delete,
        live_keep["id"]: live_keep,
    })
    after_update = _candidate("candidate.update", "planned")
    after_create = _candidate("candidate.create", "planned")

    projected = ProjectedStore(
        store,
        [after_update, after_create],
        delete_ids=("candidate.delete",),
    )

    assert projected.get("candidate.update")["meaning"] == "planned"
    assert projected.get("candidate.create")["meaning"] == "planned"
    assert not projected.has("candidate.delete")
    assert {obj["id"] for obj in projected.all()} == {
        "candidate.create",
        "candidate.keep",
        "candidate.update",
    }
    assert store.get("candidate.update")["meaning"] == "live"
    assert store.has("candidate.delete")

    after_update["meaning"] = "caller-mutated"
    returned = projected.get("candidate.update")
    returned["meaning"] = "return-mutated"

    assert projected.get("candidate.update")["meaning"] == "planned"
    assert store.get("candidate.update")["meaning"] == "live"


def test_projected_store_keeps_deep_snapshot_and_returns_fresh_copies():
    live = _candidate("candidate.update", "live")
    live["nested"] = {"values": ["live"]}
    store = BrainStore({live["id"]: live})
    after = _candidate("candidate.update", "planned")
    after["nested"] = MappingProxyType({"values": ["planned"]})

    projected = ProjectedStore(store, [after])

    after["nested"]["values"].append("caller-mutated")
    store.get("candidate.update")["nested"]["values"].append("live-mutated")
    returned = projected.get("candidate.update")
    returned["nested"]["values"].append("get-mutated")
    returned_all = projected.all()[0]
    returned_all["nested"]["values"].append("all-mutated")
    returned_by_kind = projected.by_kind("DomainMapping")[0]
    returned_by_kind["nested"]["values"].append("by-kind-mutated")

    expected = {"values": ["planned"]}
    assert projected.get("candidate.update")["nested"] == expected
    assert projected.all()[0]["nested"] == expected
    assert projected.by_kind("DomainMapping")[0]["nested"] == expected
    assert store.get("candidate.update")["nested"] == {
        "values": ["live", "live-mutated"]
    }


def test_target_requirement_from_action_and_capability():
    before_delete = _candidate("candidate.delete", "live")
    before_reviewed_same = _object(
        "mapping.reviewed-same",
        kind="DomainMapping",
        status="reviewed",
    )
    store = BrainStore({
        before_delete["id"]: before_delete,
        before_reviewed_same["id"]: before_reviewed_same,
    })

    plan = plan_base(
        store,
        [
            _candidate("candidate.optional", "candidate"),
            _object(
                "manifest.required",
                kind="EvidenceManifest",
                status="reviewed",
            ),
            _object(
                "mapping.direct-reviewed",
                kind="DomainMapping",
                status="reviewed",
            ),
            _object(
                "mapping.reviewed-same",
                kind="DomainMapping",
                status="reviewed",
                stamp="2099-01-01T00:00:00Z",
            ),
            _object(
                "projection.context",
                kind="ContextProjection",
                status="reviewed",
                format="context_md",
            ),
        ],
        delete_ids=("candidate.delete",),
    )

    assert plan.requirements == (
        EvidencePlanRequirement(
            "candidate.delete",
            "forbidden",
            "evidence_plan_delete_target",
        ),
        EvidencePlanRequirement("candidate.optional", "optional_unverified"),
        EvidencePlanRequirement(
            "manifest.required",
            "required",
        ),
        EvidencePlanRequirement(
            "mapping.direct-reviewed",
            "forbidden",
            "direct_reviewed_evidence_unavailable",
        ),
        EvidencePlanRequirement(
            "mapping.reviewed-same",
            "optional_unverified",
        ),
        EvidencePlanRequirement(
            "projection.context",
            "forbidden",
            "evidence_profile_unavailable",
        ),
    )


def test_base_plan_has_no_external_effects():
    before = _candidate("candidate.before", "before")
    after = _candidate("candidate.after", "after")
    store = BrainStore({before["id"]: before})
    forbidden_context = mock.Mock(name="adapter-and-repo-context")

    filesystem = mock.Mock(side_effect=AssertionError("filesystem called"))
    journal = mock.Mock(side_effect=AssertionError("journal called"))
    receipt = mock.Mock(side_effect=AssertionError("receipt called"))
    clock = mock.Mock(side_effect=AssertionError("clock called"))
    apply = mock.Mock(side_effect=AssertionError("mutation apply called"))

    with (
        mock.patch.object(BrainStore, "load", filesystem),
        mock.patch.object(BrainStore, "save_object", filesystem),
        mock.patch.object(corpus_io, "apply_transaction", journal),
        mock.patch.object(corpus_io, "record_no_change_receipt", receipt),
        mock.patch.object(MutationService, "apply", apply),
        mock.patch.object(time, "time", clock),
    ):
        plan = plan_base(
            store,
            [after],
            delete_ids=(before["id"],),
            repo_context=forbidden_context,
        )

    assert [target.action for target in plan.targets] == ["create", "delete"]
    assert not forbidden_context.mock_calls
    assert not filesystem.called
    assert not journal.called
    assert not receipt.called
    assert not apply.called
    assert not clock.called


def test_invalid_base_plan_has_no_external_effects():
    before = _candidate("candidate.before", "before")
    store = BrainStore({before["id"]: before})
    adapter = mock.Mock(name="adapter-and-repo-context")

    filesystem = mock.Mock(side_effect=AssertionError("filesystem called"))
    journal = mock.Mock(side_effect=AssertionError("journal called"))
    receipt = mock.Mock(side_effect=AssertionError("receipt called"))
    clock = mock.Mock(side_effect=AssertionError("clock called"))
    apply = mock.Mock(side_effect=AssertionError("mutation apply called"))

    with (
        mock.patch.object(BrainStore, "load", filesystem),
        mock.patch.object(BrainStore, "save_object", filesystem),
        mock.patch.object(corpus_io, "apply_transaction", journal),
        mock.patch.object(corpus_io, "record_no_change_receipt", receipt),
        mock.patch.object(MutationService, "apply", apply),
        mock.patch.object(time, "time", clock),
    ):
        with pytest.raises(EvidencePreparationError) as raised:
            plan_base(
                store,
                [_candidate(before["id"], "planned")],
                delete_ids=(before["id"],),
                repo_context=adapter,
            )

    assert raised.value.code == "evidence_base_plan_invalid"
    assert not adapter.mock_calls
    assert not filesystem.called
    assert not journal.called
    assert not receipt.called
    assert not apply.called
    assert not clock.called
