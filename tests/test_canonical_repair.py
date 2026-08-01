from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from dataclasses import dataclass, fields, replace
from pathlib import Path

import pytest

from project_brain import canonical_repair
from project_brain.canonical_repair import (
    CanonicalAction,
    CanonicalRepairError,
    CanonicalizationLedger,
    apply_canonical_repair_artifact,
    canonical_repair_renames_from_ledger,
    create_canonical_repair_artifact,
    decode_canonicalization_ledger,
    id_renames_from_ledger,
    id_renames_from_trusted_repair_receipt,
    parse_canonicalization_ledger,
    plan_canonical_repair,
    validate_canonicalization_ledger,
)
from project_brain.mutation import (
    CanonicalFieldChange,
    CanonicalRepairIntent,
    MutationManifest,
    MutationOperation,
    MutationService,
    corpus_fingerprint,
)
from project_brain.snapshot import (
    SnapshotRequest,
    SnapshotVerification,
    create_snapshot,
    verify_snapshot,
)
from project_brain.store import BrainStore
from tests.test_canonical_merge import _real_collision_pairs
from tests.test_ingest import candidate_mapping, candidate_term, context, review_record_for
from tests.test_mutation import _write_raw


ENGINE_SHA = "e" * 40
REPO_HEAD = "b" * 40
DRONE_MERGE_SOURCE = "mapping.disturb-drone.cloud-reskin-identity"
DRONE_MERGE_TARGET = "mapping.disturb-drone.drone-cloud-reskin-identity"
HEDGEHOG_MERGE_SOURCE = "mapping.disturb-hedgehog.angry-shoot-block"
HEDGEHOG_MERGE_TARGET = (
    "mapping.disturb-hedgehog.angry-shoot-bubble-removal"
)


def _json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


@dataclass(frozen=True)
class LedgerFixture:
    store: BrainStore
    ledger_payload: dict
    ledger_bytes: bytes
    classification_payload: dict
    classification_bytes: bytes
    classification_sha256: str

    @property
    def validation_args(self) -> dict:
        return {
            "classification_bytes": self.classification_bytes,
            "expected_classification_sha256": self.classification_sha256,
            "existing": self.store,
            "engine_sha": ENGINE_SHA,
            "repo_head": REPO_HEAD,
        }


def _ledger_fixture(
    *,
    first_action: str = "id_only_rename",
    first_target: str = "g.neutral.canonical-000",
    existing_target: bool = False,
    merge_count: int = 2,
) -> LedgerFixture:
    objects: dict[str, dict] = {}
    source_receipts: dict[str, str] = {}
    rows: list[dict] = []
    decisions: list[dict] = []
    for index in range(156):
        source_id = f"g.neutral.legacy-{index:03d}"
        source_kind = "GlossaryTerm"
        source_sha256 = hashlib.sha256(
            f"source:{source_id}".encode("utf-8")
        ).hexdigest()
        objects[source_id] = {
            "id": source_id,
            "kind": source_kind,
            "title": source_id,
        }
        source_receipts[source_id] = source_sha256
        rows.append({
            "old_id": source_id,
            "kind": source_kind,
            "source_sha256": source_sha256,
        })
        action = first_action if index == 0 else "id_only_rename"
        new_id = (
            first_target
            if index == 0
            else f"g.neutral.canonical-{index:03d}"
        )
        decisions.append({
            "source_id": source_id,
            "source_kind": source_kind,
            "source_sha256": source_sha256,
            "action": action,
            "new_id": new_id,
            "field_changes": [],
            "decision_reason": f"approved canonical identity {index}",
            "decision_evidence": [f"classification#/rows/{index}"],
        })
    collision_pairs = list(_real_collision_pairs())
    if merge_count == 3:
        synthetic_source = deepcopy(collision_pairs[0][0])
        synthetic_target = deepcopy(collision_pairs[0][1])
        for obj, object_id in (
            (synthetic_source, "mapping.synthetic.collision-source"),
            (synthetic_target, "mapping.synthetic.canonical-target"),
        ):
            obj.update({
                "id": object_id,
                "context_id": "context.synthetic",
                "mapping_key": "canonical-target",
                "review_record_id": "review.bundle.synthetic.domain-mapping",
                "tags": ["synthetic"],
            })
        collision_pairs.append((synthetic_source, synthetic_target))
    for offset, (source, target) in enumerate(collision_pairs[:merge_count]):
        index = 156 - merge_count + offset
        replaced_source_id = decisions[index]["source_id"]
        objects.pop(replaced_source_id)
        source_receipts.pop(replaced_source_id)
        source_sha256 = hashlib.sha256(
            f"source:{source['id']}".encode("utf-8")
        ).hexdigest()
        objects[source["id"]] = deepcopy(source)
        objects[target["id"]] = deepcopy(target)
        source_receipts[source["id"]] = source_sha256
        rows[index] = {
            "old_id": source["id"],
            "kind": source["kind"],
            "source_sha256": source_sha256,
        }
        decisions[index] = {
            "source_id": source["id"],
            "source_kind": source["kind"],
            "source_sha256": source_sha256,
            "action": "collision_merge_into_existing",
            "new_id": target["id"],
            "field_changes": [],
            "decision_reason": "approved collision merge into canonical target",
            "decision_evidence": [f"classification#/rows/{index}"],
        }
    if existing_target:
        objects[first_target] = {
            "id": first_target,
            "kind": "GlossaryTerm",
            "title": "occupied target",
        }
        source_receipts[first_target] = hashlib.sha256(
            b"occupied target"
        ).hexdigest()
    store = BrainStore(objects, source_sha256_by_id=source_receipts)
    fingerprint = corpus_fingerprint(store)
    classification = {
        "binding": {
            "schema_version": 1,
            "engine_sha": ENGINE_SHA,
            "repo_head": REPO_HEAD,
            "corpus_fingerprint": fingerprint,
            "eval_sha256": "a" * 64,
            "stale_sha256": None,
        },
        "rows": rows,
        "summary": {
            "classification_row_count_including_induced_review": 156,
        },
    }
    classification_bytes = _json_bytes(classification)
    classification_sha256 = hashlib.sha256(classification_bytes).hexdigest()
    ledger = {
        "version": 1,
        "phase_a_classification_sha256": classification_sha256,
        "engine_sha": ENGINE_SHA,
        "repo_head": REPO_HEAD,
        "corpus_fingerprint": fingerprint,
        "decisions": decisions,
    }
    ledger_bytes = _json_bytes(ledger)
    return LedgerFixture(
        store=store,
        ledger_payload=ledger,
        ledger_bytes=ledger_bytes,
        classification_payload=classification,
        classification_bytes=classification_bytes,
        classification_sha256=classification_sha256,
    )


def _rebind_ledger_fixture(
    fixture: LedgerFixture,
    *,
    change_objects=None,
    change_decisions=None,
    receipt_overrides: dict[str, str] | None = None,
) -> LedgerFixture:
    objects = {
        str(obj["id"]): deepcopy(obj)
        for obj in fixture.store.all()
    }
    decisions = deepcopy(fixture.ledger_payload["decisions"])
    if change_objects is not None:
        change_objects(objects)
    if change_decisions is not None:
        change_decisions(decisions)
    receipts = {
        row["source_id"]: row["source_sha256"]
        for row in decisions
    }
    receipts.update(receipt_overrides or {})
    store = BrainStore(objects, source_sha256_by_id=receipts)
    fingerprint = corpus_fingerprint(store)
    classification = deepcopy(fixture.classification_payload)
    classification["binding"]["corpus_fingerprint"] = fingerprint
    classification["rows"] = [
        {
            "old_id": row["source_id"],
            "kind": row["source_kind"],
            "source_sha256": row["source_sha256"],
        }
        for row in decisions
    ]
    classification_bytes = _json_bytes(classification)
    classification_sha256 = hashlib.sha256(classification_bytes).hexdigest()
    ledger_payload = deepcopy(fixture.ledger_payload)
    ledger_payload.update({
        "phase_a_classification_sha256": classification_sha256,
        "corpus_fingerprint": fingerprint,
        "decisions": decisions,
    })
    ledger_bytes = _json_bytes(ledger_payload)
    return LedgerFixture(
        store=store,
        ledger_payload=ledger_payload,
        ledger_bytes=ledger_bytes,
        classification_payload=classification,
        classification_bytes=classification_bytes,
        classification_sha256=classification_sha256,
    )


def _decode_changed(fixture: LedgerFixture, change) -> CanonicalizationLedger:
    payload = json.loads(fixture.ledger_bytes)
    change(payload)
    return decode_canonicalization_ledger(_json_bytes(payload))


def test_decode_ledger_accepts_exact_156_row_payload():
    fixture = _ledger_fixture()

    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)

    assert ledger.version == 1
    assert len(ledger.decisions) == 156
    assert ledger.decisions[0].action is CanonicalAction.ID_ONLY_RENAME
    assert ledger.sha256 == hashlib.sha256(fixture.ledger_bytes).hexdigest()


def test_merge_ledger_decodes_exact_collision_map_and_excludes_id_renames():
    fixture = _ledger_fixture()

    ledger = parse_canonicalization_ledger(
        fixture.ledger_bytes,
        **fixture.validation_args,
    )

    assert canonical_repair.collision_merges_from_ledger(ledger) == {
        DRONE_MERGE_SOURCE: DRONE_MERGE_TARGET,
        HEDGEHOG_MERGE_SOURCE: HEDGEHOG_MERGE_TARGET,
    }
    assert not (
        set(canonical_repair.collision_merges_from_ledger(ledger))
        & set(id_renames_from_ledger(ledger))
    )
    assert not (
        set(canonical_repair.collision_merges_from_ledger(ledger))
        & set(canonical_repair_renames_from_ledger(ledger))
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("new_id", None),
        (
            "field_changes",
            [{"pointer": "/mapping_key", "before": "old", "after": "new"}],
        ),
    ],
)
def test_merge_ledger_decoder_rejects_missing_target_or_field_changes(
    field,
    value,
):
    fixture = _ledger_fixture()

    def change(payload):
        row = next(
            item
            for item in payload["decisions"]
            if item["source_id"] == DRONE_MERGE_SOURCE
        )
        row[field] = value

    with pytest.raises(CanonicalRepairError) as exc:
        _decode_changed(fixture, change)

    assert exc.value.code == "decision_ledger_invalid"


@pytest.mark.parametrize("merge_count", [1, 3])
def test_merge_ledger_rejects_action_count_other_than_two(merge_count):
    fixture = _ledger_fixture(merge_count=merge_count)
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(ledger, **fixture.validation_args)

    assert exc.value.code == "canonical_repair_action_count_invalid"


def test_merge_ledger_rejects_non_mapping_source_kind():
    fixture = _ledger_fixture()

    def change_objects(objects):
        objects[DRONE_MERGE_SOURCE]["kind"] = "GlossaryTerm"

    def change_decisions(decisions):
        row = next(
            item for item in decisions
            if item["source_id"] == DRONE_MERGE_SOURCE
        )
        row["source_kind"] = "GlossaryTerm"

    fixture = _rebind_ledger_fixture(
        fixture,
        change_objects=change_objects,
        change_decisions=change_decisions,
    )
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(ledger, **fixture.validation_args)

    assert exc.value.code == "decision_merge_target_invalid"


def test_decode_ledger_rejects_duplicate_json_key():
    payload = b'{"version":1,"version":1}'

    with pytest.raises(CanonicalRepairError) as exc:
        decode_canonicalization_ledger(payload)

    assert exc.value.code == "decision_ledger_invalid"


@pytest.mark.parametrize("location", ["top", "row"])
def test_decode_ledger_rejects_unknown_key(location):
    fixture = _ledger_fixture()

    def change(payload):
        target = payload if location == "top" else payload["decisions"][0]
        target["unknown"] = True

    with pytest.raises(CanonicalRepairError) as exc:
        _decode_changed(fixture, change)

    assert exc.value.code == "decision_ledger_invalid"


def test_decode_ledger_rejects_unknown_action():
    fixture = _ledger_fixture()

    with pytest.raises(CanonicalRepairError) as exc:
        _decode_changed(
            fixture,
            lambda payload: payload["decisions"][0].__setitem__(
                "action",
                "merge",
            ),
        )

    assert exc.value.code == "decision_ledger_invalid"


@pytest.mark.parametrize("field", ["decision_reason", "decision_evidence"])
def test_decode_ledger_rejects_empty_reason_or_evidence(field):
    fixture = _ledger_fixture()

    with pytest.raises(CanonicalRepairError) as exc:
        _decode_changed(
            fixture,
            lambda payload: payload["decisions"][0].__setitem__(
                field,
                "" if field == "decision_reason" else [],
            ),
        )

    assert exc.value.code == "decision_ledger_invalid"


@pytest.mark.parametrize(
    ("location", "field"),
    [
        ("top", "phase_a_classification_sha256"),
        ("top", "engine_sha"),
        ("top", "repo_head"),
        ("top", "corpus_fingerprint"),
        ("row", "source_sha256"),
    ],
)
def test_decode_ledger_rejects_malformed_sha(location, field):
    fixture = _ledger_fixture()

    def change(payload):
        target = payload if location == "top" else payload["decisions"][0]
        target[field] = "A" * 64

    with pytest.raises(CanonicalRepairError) as exc:
        _decode_changed(fixture, change)

    assert exc.value.code == "decision_ledger_invalid"


def test_decode_ledger_rejects_duplicate_source():
    fixture = _ledger_fixture()

    def change(payload):
        payload["decisions"][1]["source_id"] = payload["decisions"][0][
            "source_id"
        ]

    with pytest.raises(CanonicalRepairError) as exc:
        _decode_changed(fixture, change)

    assert exc.value.code == "decision_ledger_invalid"


def test_decode_ledger_rejects_missing_new_id_for_rename_action():
    fixture = _ledger_fixture()

    with pytest.raises(CanonicalRepairError) as exc:
        _decode_changed(
            fixture,
            lambda payload: payload["decisions"][0].__setitem__(
                "new_id",
                None,
            ),
        )

    assert exc.value.code == "decision_ledger_invalid"


def test_parse_ledger_validates_exact_classification_and_source_binding():
    fixture = _ledger_fixture()

    ledger = parse_canonicalization_ledger(
        fixture.ledger_bytes,
        **fixture.validation_args,
    )

    assert ledger.sha256 == hashlib.sha256(fixture.ledger_bytes).hexdigest()


def test_classification_rejects_incomplete_156_row_coverage():
    fixture = _ledger_fixture()
    classification = json.loads(fixture.classification_bytes)
    classification["rows"].pop()
    classification_bytes = _json_bytes(classification)
    classification_sha256 = hashlib.sha256(classification_bytes).hexdigest()
    ledger = replace(
        decode_canonicalization_ledger(fixture.ledger_bytes),
        phase_a_classification_sha256=classification_sha256,
    )

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(
            ledger,
            classification_bytes=classification_bytes,
            expected_classification_sha256=classification_sha256,
            existing=fixture.store,
            engine_sha=ENGINE_SHA,
            repo_head=REPO_HEAD,
        )

    assert exc.value.code == "classification_coverage_invalid"


def test_classification_rejects_wrong_trusted_sha():
    fixture = _ledger_fixture()
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(
            ledger,
            **{
                **fixture.validation_args,
                "expected_classification_sha256": "0" * 64,
            },
        )

    assert exc.value.code == "classification_sha256_mismatch"


@pytest.mark.parametrize(
    ("axis", "error_code"),
    [
        ("source_id", "classification_source_mismatch"),
        ("source_kind", "classification_source_mismatch"),
        ("source_sha256", "classification_source_mismatch"),
    ],
)
def test_classification_rejects_row_binding_drift(axis, error_code):
    fixture = _ledger_fixture()
    classification = json.loads(fixture.classification_bytes)
    classification_key = {
        "source_id": "old_id",
        "source_kind": "kind",
        "source_sha256": "source_sha256",
    }[axis]
    classification["rows"][0][classification_key] = (
        "other" if axis != "source_sha256" else "0" * 64
    )
    classification_bytes = _json_bytes(classification)
    classification_sha256 = hashlib.sha256(classification_bytes).hexdigest()
    ledger = replace(
        decode_canonicalization_ledger(fixture.ledger_bytes),
        phase_a_classification_sha256=classification_sha256,
    )

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(
            ledger,
            classification_bytes=classification_bytes,
            expected_classification_sha256=classification_sha256,
            existing=fixture.store,
            engine_sha=ENGINE_SHA,
            repo_head=REPO_HEAD,
        )

    assert exc.value.code == error_code


@pytest.mark.parametrize(
    ("axis", "error_code"),
    [
        ("engine", "decision_engine_sha_mismatch"),
        ("repo", "decision_repo_head_mismatch"),
        ("corpus", "decision_corpus_fingerprint_mismatch"),
    ],
)
def test_ledger_rejects_runtime_binding_drift(axis, error_code):
    fixture = _ledger_fixture()
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)
    kwargs = fixture.validation_args
    if axis == "engine":
        kwargs["engine_sha"] = "d" * 40
    elif axis == "repo":
        kwargs["repo_head"] = "c" * 40
    else:
        changed = dict(fixture.store.get("g.neutral.legacy-000"))
        changed["title"] = "changed"
        objects = {
            obj["id"]: dict(obj)
            for obj in fixture.store.all()
        }
        objects[changed["id"]] = changed
        kwargs["existing"] = BrainStore(
            objects,
            source_sha256_by_id={
                decision.source_id: decision.source_sha256
                for decision in ledger.decisions
            },
        )

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(ledger, **kwargs)

    assert exc.value.code == error_code


def test_source_binding_rejects_current_store_source_sha_drift():
    fixture = _ledger_fixture()
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)
    receipts = {
        decision.source_id: decision.source_sha256
        for decision in ledger.decisions
    }
    receipts[ledger.decisions[0].source_id] = "0" * 64
    drifted_store = BrainStore(
        {obj["id"]: dict(obj) for obj in fixture.store.all()},
        source_sha256_by_id=receipts,
    )

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(
            ledger,
            **{**fixture.validation_args, "existing": drifted_store},
        )

    assert exc.value.code == "decision_source_sha256_mismatch"


def test_ledger_rejects_duplicate_rename_target():
    fixture = _ledger_fixture()

    def change(payload):
        payload["decisions"][1]["new_id"] = payload["decisions"][0]["new_id"]

    ledger = _decode_changed(fixture, change)

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(ledger, **fixture.validation_args)

    assert exc.value.code == "decision_target_duplicate"


def test_ledger_rejects_current_store_target_collision():
    fixture = _ledger_fixture(existing_target=True)
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(ledger, **fixture.validation_args)

    assert exc.value.code == "decision_target_exists"


@pytest.mark.parametrize("drift", ["missing", "noncanonical"])
def test_merge_ledger_rejects_missing_or_noncanonical_existing_target(drift):
    fixture = _ledger_fixture()
    invalid_target = "mapping.disturb-drone.not_canonical"

    def change_objects(objects):
        target = objects.pop(DRONE_MERGE_TARGET)
        if drift == "noncanonical":
            target["id"] = invalid_target
            target["mapping_key"] = "not_canonical"
            objects[invalid_target] = target

    def change_decisions(decisions):
        if drift == "noncanonical":
            row = next(
                item for item in decisions
                if item["source_id"] == DRONE_MERGE_SOURCE
            )
            row["new_id"] = invalid_target

    fixture = _rebind_ledger_fixture(
        fixture,
        change_objects=change_objects,
        change_decisions=change_decisions,
    )
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(ledger, **fixture.validation_args)

    assert exc.value.code == "decision_merge_target_invalid"


@pytest.mark.parametrize(
    "overlap",
    ["decision_source", "merge_target", "rename_target"],
)
def test_merge_ledger_rejects_endpoint_overlap(overlap):
    fixture = _ledger_fixture()

    def change_decisions(decisions):
        drone = next(
            item for item in decisions
            if item["source_id"] == DRONE_MERGE_SOURCE
        )
        hedgehog = next(
            item for item in decisions
            if item["source_id"] == HEDGEHOG_MERGE_SOURCE
        )
        if overlap == "decision_source":
            drone["new_id"] = decisions[0]["source_id"]
        elif overlap == "merge_target":
            hedgehog["new_id"] = drone["new_id"]
        else:
            decisions[0]["new_id"] = drone["new_id"]

    fixture = _rebind_ledger_fixture(
        fixture,
        change_decisions=change_decisions,
    )
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(ledger, **fixture.validation_args)

    assert exc.value.code == "decision_merge_endpoint_overlap"


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("kind", "DecisionRecord", "merge_target_kind_invalid"),
        ("context_id", "context.other", "merge_target_id_invalid"),
        ("mapping_key", "other", "merge_target_id_invalid"),
        (
            "review_record_id",
            "review.bundle.other.domain-mapping",
            "merge_exact_field_mismatch",
        ),
    ],
)
def test_merge_ledger_rejects_endpoint_payload_drift(
    field,
    value,
    error_code,
):
    fixture = _ledger_fixture()

    def change_objects(objects):
        objects[DRONE_MERGE_TARGET][field] = value

    fixture = _rebind_ledger_fixture(
        fixture,
        change_objects=change_objects,
    )
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(ledger, **fixture.validation_args)

    assert exc.value.code == error_code


def test_merge_ledger_rejects_source_sha_drift():
    fixture = _ledger_fixture()
    fixture = _rebind_ledger_fixture(
        fixture,
        receipt_overrides={DRONE_MERGE_SOURCE: "0" * 64},
    )
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(ledger, **fixture.validation_args)

    assert exc.value.code == "decision_source_sha256_mismatch"


def test_merge_ledger_rejects_provenance_reference():
    fixture = _ledger_fixture()

    def change_objects(objects):
        objects["insight.neutral.merge-provenance"] = {
            "id": "insight.neutral.merge-provenance",
            "kind": "Insight",
            "source_object_id": DRONE_MERGE_SOURCE,
        }

    fixture = _rebind_ledger_fixture(
        fixture,
        change_objects=change_objects,
    )
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(ledger, **fixture.validation_args)

    assert exc.value.code == "merge_provenance_reference"


@pytest.mark.parametrize("dependency", ["source", "survivor", "referrer"])
def test_merge_ledger_rejects_context_projection_dependency(dependency):
    fixture = _ledger_fixture()

    def change_objects(objects):
        referrer_id = "decision.neutral.merge-referrer"
        if dependency == "referrer":
            objects[referrer_id] = {
                "id": referrer_id,
                "kind": "DecisionRecord",
                "target_object_id": DRONE_MERGE_SOURCE,
            }
        dependency_id = {
            "source": DRONE_MERGE_SOURCE,
            "survivor": DRONE_MERGE_TARGET,
            "referrer": referrer_id,
        }[dependency]
        objects["projection.neutral.requirement.reuse"] = {
            "id": "projection.neutral.requirement.reuse",
            "kind": "ContextProjection",
            "source_object_ids": [dependency_id],
        }

    fixture = _rebind_ledger_fixture(
        fixture,
        change_objects=change_objects,
    )
    ledger = decode_canonicalization_ledger(fixture.ledger_bytes)

    with pytest.raises(CanonicalRepairError) as exc:
        validate_canonicalization_ledger(ledger, **fixture.validation_args)

    assert exc.value.code == "merge_context_projection_reference"


def test_collision_distinct_rename_allows_an_empty_selected_target():
    fixture = _ledger_fixture(first_action="collision_distinct_rename")

    ledger = parse_canonicalization_ledger(
        fixture.ledger_bytes,
        **fixture.validation_args,
    )

    assert ledger.decisions[0].action is CanonicalAction.COLLISION_DISTINCT_RENAME


def _git_repo(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "repair@test.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Repair Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@dataclass(frozen=True)
class CanonicalPlanFixture:
    brain_root: Path
    repo_root: Path
    engine_root: Path
    engine_sha: str
    existing: BrainStore
    ledger: CanonicalizationLedger
    ledger_bytes: bytes
    classification_bytes: bytes
    classification_sha256: str
    snapshot: SnapshotVerification
    expected_id_only_sources: tuple[str, ...]
    reference_only_id: str

    @property
    def plan_args(self) -> dict:
        return {
            "existing": self.existing,
            "brain_root": self.brain_root,
            "repo_root": self.repo_root,
            "engine_root": self.engine_root,
            "engine_sha": self.engine_sha,
            "ledger": self.ledger,
            "snapshot": self.snapshot,
        }


def _canonical_plan_fixture(tmp_path: Path) -> CanonicalPlanFixture:
    repo_root = (tmp_path / "repo").resolve()
    repo_head = _git_repo(repo_root)
    brain_root = repo_root / "brain"
    engine_root = (tmp_path / "engine").resolve()
    engine_sha = _git_repo(engine_root)
    bad_terms = []
    for index in range(150):
        term = candidate_term(
            f"g.neutral.Legacy{index:03d}",
            term=f"합성 용어 {index}",
        )
        bad_terms.append(term)
        _write_raw(brain_root, term)
    _write_raw(brain_root, context())
    stable_mapping = candidate_mapping(
        "mapping.neutral.stable",
        glossary_term_ids=[bad_terms[0]["id"]],
        mapping_key="stable",
    )
    _write_raw(brain_root, stable_mapping)
    old_mappings: list[dict] = []
    new_mapping_ids: list[str] = []
    for index in range(4):
        old = candidate_mapping(
            f"mapping.neutral.Legacy{index}",
            glossary_term_ids=[bad_terms[0]["id"]],
            mapping_key=f"Legacy{index}",
        )
        old_mappings.append(old)
        new_mapping_ids.append(f"mapping.neutral.repair-{index}")
        _write_raw(brain_root, old)
    mixed_review = review_record_for(
        "review.bundle.Neutral.domain-mapping",
        old_mappings[0]["id"],
    )
    mixed_review.pop("target_object_id")
    mixed_review.update({
        "review_scope": "mapping_bundle",
        "review_type": "meaning_review",
        "bundle_key": "bundle.neutral.domain-mapping",
        "confirmation_key": "bundle.neutral.domain-mapping",
        "target_object_ids": [
            *(item["id"] for item in old_mappings),
            stable_mapping["id"],
            bad_terms[0]["id"],
        ],
    })
    _write_raw(brain_root, mixed_review)
    reference_only = review_record_for(
        "review.bundle.neutral.reference-only",
        old_mappings[0]["id"],
    )
    reference_only.pop("target_object_id")
    reference_only.update({
        "review_scope": "mapping_bundle",
        "review_type": "meaning_review",
        "bundle_key": "bundle.neutral.reference-only",
        "confirmation_key": "bundle.neutral.reference-only",
        "target_object_ids": [old_mappings[0]["id"]],
    })
    _write_raw(brain_root, reference_only)
    existing = BrainStore.load(brain_root)
    fingerprint = corpus_fingerprint(existing)
    decisions: list[dict] = []
    for old, new_id in zip(old_mappings, new_mapping_ids, strict=True):
        decisions.append({
            "source_id": old["id"],
            "source_kind": old["kind"],
            "source_sha256": existing.source_sha256(old["id"]),
            "action": "projected_field_repair",
            "new_id": new_id,
            "field_changes": [{
                "pointer": "/mapping_key",
                "before": old["mapping_key"],
                "after": new_id.rsplit(".", 1)[-1],
            }],
            "decision_reason": "approved mapping projection repair",
            "decision_evidence": [f"fixture#{old['id']}"],
        })
    mixed_after_targets = [*new_mapping_ids, stable_mapping["id"]]
    decisions.append({
        "source_id": mixed_review["id"],
        "source_kind": mixed_review["kind"],
        "source_sha256": existing.source_sha256(mixed_review["id"]),
        "action": "review_shape_repair",
        "new_id": "review.bundle.neutral.domain-mapping",
        "field_changes": [{
            "pointer": "/target_object_ids",
            "before": [*mixed_after_targets, bad_terms[0]["id"]],
            "after": mixed_after_targets,
        }],
        "decision_reason": "approved mixed review target cleanup",
        "decision_evidence": ["fixture#mixed-review"],
    })
    decisions.append({
        "source_id": reference_only["id"],
        "source_kind": reference_only["kind"],
        "source_sha256": existing.source_sha256(reference_only["id"]),
        "action": "reference_only",
        "new_id": None,
        "field_changes": [],
        "decision_reason": "registered reference follows mapping repair",
        "decision_evidence": ["fixture#reference-only"],
    })
    for index, term in enumerate(bad_terms):
        decisions.append({
            "source_id": term["id"],
            "source_kind": term["kind"],
            "source_sha256": existing.source_sha256(term["id"]),
            "action": "id_only_rename",
            "new_id": f"g.neutral.canonical-{index:03d}",
            "field_changes": [],
            "decision_reason": "approved pure identity repair",
            "decision_evidence": [f"fixture#term-{index}"],
        })
    decisions.sort(key=lambda row: row["source_id"])
    classification = {
        "binding": {
            "schema_version": 1,
            "engine_sha": engine_sha,
            "repo_head": repo_head,
            "corpus_fingerprint": fingerprint,
            "eval_sha256": "a" * 64,
            "stale_sha256": None,
        },
        "rows": [
            {
                "old_id": row["source_id"],
                "kind": row["source_kind"],
                "source_sha256": row["source_sha256"],
            }
            for row in decisions
        ],
        "summary": {
            "classification_row_count_including_induced_review": 156,
        },
    }
    classification_bytes = _json_bytes(classification)
    classification_sha256 = hashlib.sha256(classification_bytes).hexdigest()
    ledger_bytes = _json_bytes({
        "version": 1,
        "phase_a_classification_sha256": classification_sha256,
        "engine_sha": engine_sha,
        "repo_head": repo_head,
        "corpus_fingerprint": fingerprint,
        "decisions": decisions,
    })
    ledger = parse_canonicalization_ledger(
        ledger_bytes,
        classification_bytes=classification_bytes,
        expected_classification_sha256=classification_sha256,
        existing=existing,
        engine_sha=engine_sha,
        repo_head=repo_head,
    )
    snapshot = SnapshotVerification(
        ok=True,
        snapshot_id="canonical-repair-before",
        manifest_sha256="f" * 64,
        file_count=len(existing.all()),
        repo_head=repo_head,
        engine_head=engine_sha,
        corpus_fingerprint=fingerprint,
    )
    return CanonicalPlanFixture(
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        engine_sha=engine_sha,
        existing=existing,
        ledger=ledger,
        ledger_bytes=ledger_bytes,
        classification_bytes=classification_bytes,
        classification_sha256=classification_sha256,
        snapshot=snapshot,
        expected_id_only_sources=tuple(term["id"] for term in bad_terms),
        reference_only_id=reference_only["id"],
    )


@pytest.fixture
def canonical_fixture(tmp_path) -> CanonicalPlanFixture:
    return _canonical_plan_fixture(tmp_path)


def test_plan_repairs_only_five_non_id_only_sources(canonical_fixture):
    plan = plan_canonical_repair(**canonical_fixture.plan_args)

    assert len(plan.rows) == 5
    assert {old_id for old_id, _ in plan.id_renames} == set(
        canonical_fixture.expected_id_only_sources
    )
    assert len(plan.request.canonical_repair_intents) == 5
    assert all(
        isinstance(intent, CanonicalRepairIntent)
        for intent in plan.request.canonical_repair_intents
    )
    assert plan.request.operation is MutationOperation.CANONICAL_REPAIR


def _ledger_with_repair_count_drift(
    ledger: CanonicalizationLedger,
    drift: str,
) -> CanonicalizationLedger:
    decisions = list(ledger.decisions)
    projected_index = next(
        index
        for index, decision in enumerate(decisions)
        if decision.action is CanonicalAction.PROJECTED_FIELD_REPAIR
    )
    id_only_index = next(
        index
        for index, decision in enumerate(decisions)
        if decision.action is CanonicalAction.ID_ONLY_RENAME
    )
    if drift == "extra":
        decisions[id_only_index] = replace(
            decisions[id_only_index],
            action=CanonicalAction.PROJECTED_FIELD_REPAIR,
            field_changes=(CanonicalFieldChange(
                pointer="/mapping_key",
                before="Legacy-extra",
                after="canonical-extra",
            ),),
        )
    elif drift == "missing":
        decisions[projected_index] = replace(
            decisions[projected_index],
            action=CanonicalAction.ID_ONLY_RENAME,
            field_changes=(),
        )
    else:
        decisions[projected_index] = replace(
            decisions[projected_index],
            action=CanonicalAction.REVIEW_SHAPE_REPAIR,
            field_changes=(CanonicalFieldChange(
                pointer="/target_object_ids",
                before=["mapping.neutral.before"],
                after=["mapping.neutral.after"],
            ),),
        )
    return replace(ledger, decisions=tuple(decisions))


@pytest.mark.parametrize("drift", ["extra", "missing", "altered_distribution"])
def test_plan_rejects_repair_action_count_drift_before_mutation_planning(
    canonical_fixture,
    monkeypatch,
    drift,
):
    def forbidden_plan(*args, **kwargs):
        raise AssertionError("MutationService.plan must not run for repair count drift")

    monkeypatch.setattr(MutationService, "plan", forbidden_plan)

    with pytest.raises(CanonicalRepairError) as exc:
        plan_canonical_repair(
            **{
                **canonical_fixture.plan_args,
                "ledger": _ledger_with_repair_count_drift(
                    canonical_fixture.ledger,
                    drift,
                ),
            }
        )

    assert exc.value.code == "canonical_repair_action_count_invalid"


def test_plan_includes_reference_only_affected_object(canonical_fixture):
    plan = plan_canonical_repair(**canonical_fixture.plan_args)
    request_by_id = {obj["id"]: obj for obj in plan.request.objects}

    assert canonical_fixture.reference_only_id in request_by_id
    assert request_by_id[canonical_fixture.reference_only_id][
        "target_object_ids"
    ] == ["mapping.neutral.repair-0"]


def test_plan_captures_exact_clean_engine_receipt(canonical_fixture):
    plan = plan_canonical_repair(**canonical_fixture.plan_args)

    assert plan.engine_receipt.root == str(canonical_fixture.engine_root)
    assert plan.engine_receipt.head == canonical_fixture.engine_sha
    assert plan.engine_receipt.status_bytes == b""
    assert plan.engine_receipt.status_sha256 == hashlib.sha256(b"").hexdigest()


def test_artifact_has_exact_outer_keys_and_receipt_bindings(canonical_fixture):
    plan = plan_canonical_repair(**canonical_fixture.plan_args)

    artifact = create_canonical_repair_artifact(plan)

    assert set(artifact.manifest) == {
        *(field.name for field in fields(MutationManifest)),
        "canonical_repair_version",
        "migration_kind",
        "rows",
        "objects",
        "decision_ledger_sha256",
        "phase_a_classification_sha256",
        "id_renames",
        "snapshot_id",
        "snapshot_manifest_sha256",
        "engine_receipt",
    }
    assert artifact.manifest["decision_ledger_sha256"] == canonical_fixture.ledger.sha256
    assert artifact.manifest["phase_a_classification_sha256"] == (
        canonical_fixture.classification_sha256
    )
    assert artifact.manifest["id_renames"] == dict(plan.id_renames)
    assert artifact.manifest["snapshot_id"] == canonical_fixture.snapshot.snapshot_id
    assert artifact.manifest["snapshot_manifest_sha256"] == (
        canonical_fixture.snapshot.manifest_sha256
    )
    assert artifact.manifest["before_fingerprint"] == corpus_fingerprint(
        canonical_fixture.existing
    )
    assert artifact.manifest["expected_after_fingerprint"] == (
        plan.mutation_plan.manifest.expected_after_fingerprint
    )
    assert artifact.manifest["engine_receipt"] == {
        "root": str(canonical_fixture.engine_root),
        "head": canonical_fixture.engine_sha,
        "status_sha256": hashlib.sha256(b"").hexdigest(),
    }
    assert "status_bytes" not in artifact.manifest["engine_receipt"]
    assert artifact.manifest_bytes == _json_bytes(artifact.manifest)
    assert artifact.manifest_sha256 == hashlib.sha256(
        artifact.manifest_bytes
    ).hexdigest()


def test_pure_id_rename_map_excludes_repairs_and_reference_only(canonical_fixture):
    assert id_renames_from_ledger(canonical_fixture.ledger) == {
        source_id: f"g.neutral.canonical-{index:03d}"
        for index, source_id in enumerate(canonical_fixture.expected_id_only_sources)
    }


def _artifact_for(fixture: CanonicalPlanFixture):
    plan = plan_canonical_repair(**fixture.plan_args)
    return plan, create_canonical_repair_artifact(plan)


def _apply_args(
    fixture: CanonicalPlanFixture,
    *,
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
    **overrides,
) -> dict:
    args = {
        "manifest_bytes": manifest_bytes,
        "expected_manifest_sha256": expected_manifest_sha256,
        "decisions_bytes": fixture.ledger_bytes,
        "expected_decisions_sha256": fixture.ledger.sha256,
        "classification_bytes": fixture.classification_bytes,
        "expected_classification_sha256": fixture.classification_sha256,
        "brain_root": fixture.brain_root,
        "repo_root": fixture.repo_root,
        "engine_root": fixture.engine_root,
        "engine_sha": fixture.engine_sha,
        "snapshot_root": fixture.repo_root.parent / "snapshot",
        "expected_snapshot_manifest_sha256": fixture.snapshot.manifest_sha256,
    }
    args.update(overrides)
    return args


def _forbid_apply(*args, **kwargs):
    raise AssertionError("MutationService.apply must not run before drift rejection")


def test_apply_rejects_ledger_drift_before_mutation(
    canonical_fixture,
    monkeypatch,
):
    _, artifact = _artifact_for(canonical_fixture)
    monkeypatch.setattr(MutationService, "apply", _forbid_apply)

    with pytest.raises(CanonicalRepairError) as exc:
        apply_canonical_repair_artifact(
            **_apply_args(
                canonical_fixture,
                manifest_bytes=artifact.manifest_bytes,
                expected_manifest_sha256=artifact.manifest_sha256,
                decisions_bytes=canonical_fixture.ledger_bytes + b"\n",
            ),
        )

    assert exc.value.code == "decision_ledger_sha256_mismatch"


def test_apply_rejects_classification_drift_before_mutation(
    canonical_fixture,
    monkeypatch,
):
    _, artifact = _artifact_for(canonical_fixture)
    monkeypatch.setattr(MutationService, "apply", _forbid_apply)

    with pytest.raises(CanonicalRepairError) as exc:
        apply_canonical_repair_artifact(
            **_apply_args(
                canonical_fixture,
                manifest_bytes=artifact.manifest_bytes,
                expected_manifest_sha256=artifact.manifest_sha256,
                classification_bytes=(
                    canonical_fixture.classification_bytes + b"\n"
                ),
            ),
        )

    assert exc.value.code == "classification_sha256_mismatch"


def test_apply_rejects_manifest_drift_before_mutation(
    canonical_fixture,
    monkeypatch,
):
    _, artifact = _artifact_for(canonical_fixture)
    monkeypatch.setattr(MutationService, "apply", _forbid_apply)

    with pytest.raises(CanonicalRepairError) as exc:
        apply_canonical_repair_artifact(
            **_apply_args(
                canonical_fixture,
                manifest_bytes=artifact.manifest_bytes + b"\n",
                expected_manifest_sha256=artifact.manifest_sha256,
            ),
        )

    assert exc.value.code == "manifest_sha256_mismatch"


def test_apply_rejects_snapshot_drift_before_mutation(
    canonical_fixture,
    monkeypatch,
):
    _, artifact = _artifact_for(canonical_fixture)
    monkeypatch.setattr(MutationService, "apply", _forbid_apply)
    monkeypatch.setattr(
        "project_brain.canonical_repair.verify_snapshot",
        lambda *args, **kwargs: replace(
            canonical_fixture.snapshot,
            snapshot_id="other-snapshot",
        ),
    )

    with pytest.raises(CanonicalRepairError) as exc:
        apply_canonical_repair_artifact(
            **_apply_args(
                canonical_fixture,
                manifest_bytes=artifact.manifest_bytes,
                expected_manifest_sha256=artifact.manifest_sha256,
            ),
        )

    assert exc.value.code == "snapshot_binding_mismatch"


def test_apply_rejects_snapshot_manifest_bytes_drift_before_mutation(
    canonical_fixture,
    monkeypatch,
):
    output_root = canonical_fixture.repo_root.parent / "snapshots"
    snapshot_result = create_snapshot(SnapshotRequest(
        brain_root=canonical_fixture.brain_root,
        repo_root=canonical_fixture.repo_root,
        engine_root=canonical_fixture.engine_root,
        output_root=output_root,
        snapshot_id="real-canonical-repair-before",
    ))
    snapshot = verify_snapshot(
        snapshot_result.snapshot_root,
        expected_manifest_sha256=snapshot_result.manifest_sha256,
    )
    real_fixture = replace(canonical_fixture, snapshot=snapshot)
    _, artifact = _artifact_for(real_fixture)
    snapshot_result.manifest_path.write_bytes(
        snapshot_result.manifest_path.read_bytes() + b"\n"
    )
    monkeypatch.setattr(MutationService, "apply", _forbid_apply)

    with pytest.raises(CanonicalRepairError) as exc:
        apply_canonical_repair_artifact(
            **_apply_args(
                real_fixture,
                manifest_bytes=artifact.manifest_bytes,
                expected_manifest_sha256=artifact.manifest_sha256,
                snapshot_root=snapshot_result.snapshot_root,
            ),
        )

    assert exc.value.code == "manifest_sha256_mismatch"


def test_apply_rejects_engine_status_drift_before_mutation(
    canonical_fixture,
    monkeypatch,
):
    _, artifact = _artifact_for(canonical_fixture)
    (canonical_fixture.engine_root / "untracked.txt").write_text(
        "dirt",
        encoding="utf-8",
    )
    monkeypatch.setattr(MutationService, "apply", _forbid_apply)
    monkeypatch.setattr(
        "project_brain.canonical_repair.verify_snapshot",
        lambda *args, **kwargs: canonical_fixture.snapshot,
    )

    with pytest.raises(CanonicalRepairError) as exc:
        apply_canonical_repair_artifact(
            **_apply_args(
                canonical_fixture,
                manifest_bytes=artifact.manifest_bytes,
                expected_manifest_sha256=artifact.manifest_sha256,
            ),
        )

    assert exc.value.code == "engine_worktree_dirty"


def test_apply_rejects_engine_head_drift_before_mutation(
    canonical_fixture,
    monkeypatch,
):
    _, artifact = _artifact_for(canonical_fixture)
    (canonical_fixture.engine_root / "head.txt").write_text(
        "new head",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(canonical_fixture.engine_root), "add", "head.txt"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(canonical_fixture.engine_root),
            "commit",
            "-q",
            "-m",
            "drift",
        ],
        check=True,
    )
    monkeypatch.setattr(MutationService, "apply", _forbid_apply)
    monkeypatch.setattr(
        "project_brain.canonical_repair.verify_snapshot",
        lambda *args, **kwargs: canonical_fixture.snapshot,
    )

    with pytest.raises(CanonicalRepairError) as exc:
        apply_canonical_repair_artifact(
            **_apply_args(
                canonical_fixture,
                manifest_bytes=artifact.manifest_bytes,
                expected_manifest_sha256=artifact.manifest_sha256,
            ),
        )

    assert exc.value.code == "snapshot_engine_head_mismatch"


def test_apply_rejects_corpus_drift_before_mutation(
    canonical_fixture,
    monkeypatch,
):
    _, artifact = _artifact_for(canonical_fixture)
    changed = dict(
        canonical_fixture.existing.get(
            canonical_fixture.expected_id_only_sources[0]
        )
    )
    changed["title"] = "drifted title"
    BrainStore.object_path(canonical_fixture.brain_root, changed).write_bytes(
        BrainStore.object_bytes(changed)
    )
    monkeypatch.setattr(MutationService, "apply", _forbid_apply)
    monkeypatch.setattr(
        "project_brain.canonical_repair.verify_snapshot",
        lambda *args, **kwargs: canonical_fixture.snapshot,
    )

    with pytest.raises(CanonicalRepairError) as exc:
        apply_canonical_repair_artifact(
            **_apply_args(
                canonical_fixture,
                manifest_bytes=artifact.manifest_bytes,
                expected_manifest_sha256=artifact.manifest_sha256,
            ),
        )

    assert exc.value.code == "decision_corpus_fingerprint_mismatch"


def test_apply_rejects_fresh_replan_byte_mismatch_before_mutation(
    canonical_fixture,
    monkeypatch,
):
    _, artifact = _artifact_for(canonical_fixture)
    tampered = json.loads(artifact.manifest_bytes)
    tampered["rows"][0]["canonical_payload_hash"] = "0" * 64
    tampered_bytes = _json_bytes(tampered)
    monkeypatch.setattr(MutationService, "apply", _forbid_apply)
    monkeypatch.setattr(
        "project_brain.canonical_repair.verify_snapshot",
        lambda *args, **kwargs: canonical_fixture.snapshot,
    )

    with pytest.raises(CanonicalRepairError) as exc:
        apply_canonical_repair_artifact(
            **_apply_args(
                canonical_fixture,
                manifest_bytes=tampered_bytes,
                expected_manifest_sha256=hashlib.sha256(
                    tampered_bytes
                ).hexdigest(),
            ),
        )

    assert exc.value.code == "manifest_revalidation_failed"


def test_apply_fresh_replans_then_calls_mutation_apply_exactly_once(
    canonical_fixture,
    monkeypatch,
):
    plan, artifact = _artifact_for(canonical_fixture)
    original_apply = MutationService.apply
    calls: list[str] = []

    def tracked_apply(self, objects, *, request, failure_injector=None):
        calls.append(request.operation.value)
        return original_apply(
            self,
            objects,
            request=request,
            failure_injector=failure_injector,
        )

    monkeypatch.setattr(MutationService, "apply", tracked_apply)
    monkeypatch.setattr(
        "project_brain.canonical_repair.verify_snapshot",
        lambda *args, **kwargs: canonical_fixture.snapshot,
    )

    result = apply_canonical_repair_artifact(
        **_apply_args(
            canonical_fixture,
            manifest_bytes=artifact.manifest_bytes,
            expected_manifest_sha256=artifact.manifest_sha256,
        ),
    )

    assert calls == ["canonical_repair"]
    assert result.transaction_id == plan.mutation_plan.manifest.transaction_id
    assert result.snapshot_id == canonical_fixture.snapshot.snapshot_id
    assert result.decision_ledger_sha256 == canonical_fixture.ledger.sha256
    after = BrainStore.load(canonical_fixture.brain_root)
    assert not after.has("mapping.neutral.Legacy0")
    assert after.has("mapping.neutral.repair-0")


def _trusted_intermediate_args(
    canonical_fixture,
    monkeypatch,
) -> dict:
    _, artifact = _artifact_for(canonical_fixture)
    monkeypatch.setattr(
        "project_brain.canonical_repair.verify_snapshot",
        lambda *args, **kwargs: canonical_fixture.snapshot,
    )
    apply_canonical_repair_artifact(
        **_apply_args(
            canonical_fixture,
            manifest_bytes=artifact.manifest_bytes,
            expected_manifest_sha256=artifact.manifest_sha256,
        ),
    )
    intermediate = BrainStore.load(canonical_fixture.brain_root)
    intermediate_snapshot = SnapshotVerification(
        ok=True,
        snapshot_id="canonical-repair-intermediate",
        manifest_sha256="9" * 64,
        file_count=len(intermediate.all()),
        repo_head=canonical_fixture.snapshot.repo_head,
        engine_head=canonical_fixture.snapshot.engine_head,
        corpus_fingerprint=corpus_fingerprint(intermediate),
    )
    return {
        "decisions_bytes": canonical_fixture.ledger_bytes,
        "expected_decisions_sha256": canonical_fixture.ledger.sha256,
        "classification_bytes": canonical_fixture.classification_bytes,
        "expected_classification_sha256": canonical_fixture.classification_sha256,
        "canonical_manifest_bytes": artifact.manifest_bytes,
        "expected_canonical_manifest_sha256": artifact.manifest_sha256,
        "existing": intermediate,
        "intermediate_snapshot": intermediate_snapshot,
    }


def test_trusted_intermediate_receipt_returns_only_pure_id_renames(
    canonical_fixture,
    monkeypatch,
):
    args = _trusted_intermediate_args(canonical_fixture, monkeypatch)

    renames = id_renames_from_trusted_repair_receipt(
        **args,
    )

    assert renames == id_renames_from_ledger(canonical_fixture.ledger)


def _tamper_trusted_manifest(args: dict, axis: str) -> None:
    manifest = json.loads(args["canonical_manifest_bytes"])
    if axis == "expected_after_fingerprint":
        manifest["expected_after_fingerprint"] = "0" * 64
    elif axis == "source_before_receipt":
        manifest["renames"][0]["before_sha256"] = "0" * 64
    else:
        manifest["renames"][0]["after_sha256"] = "0" * 64
    manifest_bytes = _json_bytes(manifest)
    args["canonical_manifest_bytes"] = manifest_bytes
    args["expected_canonical_manifest_sha256"] = hashlib.sha256(
        manifest_bytes
    ).hexdigest()


@pytest.mark.parametrize(
    ("axis", "error_code"),
    [
        ("decisions_bytes", "decision_ledger_sha256_mismatch"),
        ("decisions_sha", "decision_ledger_sha256_mismatch"),
        ("classification_bytes", "classification_sha256_mismatch"),
        ("classification_sha", "classification_sha256_mismatch"),
        ("canonical_manifest_bytes", "manifest_sha256_mismatch"),
        ("canonical_manifest_sha", "manifest_sha256_mismatch"),
        ("expected_after_fingerprint", "intermediate_receipt_mismatch"),
        ("intermediate_fingerprint", "snapshot_corpus_fingerprint_mismatch"),
        ("intermediate_binding", "intermediate_receipt_mismatch"),
        ("source_before_receipt", "intermediate_source_receipt_mismatch"),
        ("source_after_receipt", "intermediate_source_receipt_mismatch"),
    ],
)
def test_trusted_intermediate_receipt_rejects_each_drifted_trust_axis(
    canonical_fixture,
    monkeypatch,
    axis,
    error_code,
):
    args = _trusted_intermediate_args(canonical_fixture, monkeypatch)
    if axis == "decisions_bytes":
        args["decisions_bytes"] += b"\n"
    elif axis == "decisions_sha":
        args["expected_decisions_sha256"] = "0" * 64
    elif axis == "classification_bytes":
        args["classification_bytes"] += b"\n"
    elif axis == "classification_sha":
        args["expected_classification_sha256"] = "0" * 64
    elif axis == "canonical_manifest_bytes":
        args["canonical_manifest_bytes"] += b"\n"
    elif axis == "canonical_manifest_sha":
        args["expected_canonical_manifest_sha256"] = "0" * 64
    elif axis in {
        "expected_after_fingerprint",
        "source_before_receipt",
        "source_after_receipt",
    }:
        _tamper_trusted_manifest(args, axis)
    elif axis == "intermediate_fingerprint":
        args["intermediate_snapshot"] = replace(
            args["intermediate_snapshot"],
            corpus_fingerprint="0" * 64,
        )
    else:
        args["intermediate_snapshot"] = replace(
            args["intermediate_snapshot"],
            engine_head="d" * 40,
        )

    with pytest.raises(CanonicalRepairError) as exc:
        id_renames_from_trusted_repair_receipt(**args)

    assert exc.value.code == error_code
