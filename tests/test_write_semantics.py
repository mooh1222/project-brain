from __future__ import annotations

import pytest

from project_brain.objbase import base
from project_brain.write_semantics import (
    ObjectActionKind,
    TimestampPolicy,
    VerifiedReferenceRewrite,
    apply_timestamp_policy,
    classify_object_actions,
    engine_owned_input_fields,
    engine_owned_temporal_fields,
    reference_only_rewrite,
    validate_write_semantics,
)
from tests.test_ingest import candidate_mapping, manifest as manifest_fixture


T = "2026-06-04T00:00:00Z"
EVENT_TIME = "2026-08-05T12:34:56+09:00"


def event(*, happened_at: object = T, object_id: str = "ledger.neutral.change") -> dict:
    return base(
        {
            "id": object_id,
            "kind": "EventLedgerRecord",
            "status": "reviewed",
            "truth_role": "event",
            "title": "변경 사건",
            "event_type": "rule_change",
            "happened_at": happened_at,
            "summary": "합성 변경 사건",
            "related_objects": [],
            "evidence_refs": [],
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def mapping(
    *,
    object_id: str = "mapping.neutral.key",
    meaning: object = "중립 의미",
    evidence_refs: list[str] | None = None,
) -> dict:
    obj = candidate_mapping(
        object_id,
        glossary_term_ids=[],
        mapping_key=object_id.rsplit(".", 1)[-1],
    )
    obj["meaning"] = meaning
    if evidence_refs is not None:
        obj["evidence_refs"] = evidence_refs
    return obj


def manifest(*, captured_at: object = T, object_id: str = "manifest.neutral.source") -> dict:
    obj = manifest_fixture(object_id)
    obj["captured_at"] = captured_at
    return obj


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("2026-08-05T00:00:00+09:00", True),
        ("2026-08-05T00:00:00Z", True),
        ("2026-08-05T00:00:00", False),
        ("2026-08-05", False),
        ("not-a-time", False),
    ],
)
def test_timestamp_parser_requires_iso_and_timezone_but_accepts_midnight(value, valid):
    obj = event(happened_at=value)
    report = validate_write_semantics(
        before_by_id={}, after_by_id={obj["id"]: obj}, source_id_by_after_id={}
    )
    actual = [(problem.code, problem.field) for problem in report.errors]
    assert actual == ([] if valid else [("timestamp_invalid", "happened_at")])


def test_required_claim_string_rejects_whitespace_only():
    obj = mapping(meaning=" \n ")
    report = validate_write_semantics(
        before_by_id={}, after_by_id={obj["id"]: obj}, source_id_by_after_id={}
    )
    assert [(p.code, p.field) for p in report.errors] == [
        ("write_semantics_invalid", "meaning")
    ]


def test_nonblank_rule_does_not_generalize_to_required_lists_or_optional_strings():
    obj = mapping(evidence_refs=[])
    obj["optional_note"] = " \n "
    report = validate_write_semantics(
        before_by_id={}, after_by_id={obj["id"]: obj}, source_id_by_after_id={}
    )
    assert not report.errors


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        ("EvidenceManifest", "captured_at"),
        ("SpecRevision", "captured_at"),
        ("ReviewRecord", "reviewed_at"),
        ("EventLedgerRecord", "happened_at"),
        ("TemporalFact", "valid_from"),
        ("TemporalFact", "valid_until"),
        ("CurrentView", "as_of"),
        ("IndexRecord", "indexed_at"),
    ],
)
def test_caller_temporal_field_map_rejects_each_changed_naive_value(kind, field):
    obj = {
        "id": f"synthetic.{kind}.{field}",
        "kind": kind,
        field: "2026-08-05T12:00:00",
    }
    report = validate_write_semantics(
        before_by_id={}, after_by_id={obj["id"]: obj}, source_id_by_after_id={}
    )
    assert [(problem.code, problem.field) for problem in report.errors] == [
        ("timestamp_invalid", field)
    ]


def test_thread_ts_is_not_treated_as_an_iso_timestamp():
    obj = {
        "id": "slack.neutral.thread",
        "kind": "SlackThread",
        "thread_ts": "1712345678.123456",
    }
    report = validate_write_semantics(
        before_by_id={}, after_by_id={obj["id"]: obj}, source_id_by_after_id={}
    )
    assert not report.errors


def test_write_semantics_grandfathers_same_object_field_value_only():
    old = manifest(captured_at="legacy-without-zone")
    same_legacy = {**old, "title": "관련 없는 제목 수정"}
    report = validate_write_semantics(
        before_by_id={old["id"]: old},
        after_by_id={old["id"]: same_legacy},
        source_id_by_after_id={old["id"]: old["id"]},
    )
    assert not report.errors
    assert [(p.object_id, p.field) for p in report.grandfathered] == [
        (old["id"], "captured_at")
    ]


def test_changed_invalid_captured_at_is_blocking():
    old = manifest(captured_at="legacy-without-zone")
    changed = {**old, "captured_at": "another-invalid-value"}
    report = validate_write_semantics(
        before_by_id={old["id"]: old},
        after_by_id={old["id"]: changed},
        source_id_by_after_id={old["id"]: old["id"]},
    )
    assert [(p.code, p.field) for p in report.errors] == [
        ("timestamp_invalid", "captured_at")
    ]


def test_same_invalid_value_on_a_different_object_is_not_grandfathered():
    old = manifest(captured_at="legacy-without-zone")
    other = manifest(
        captured_at="legacy-without-zone",
        object_id="manifest.neutral.other",
    )
    report = validate_write_semantics(
        before_by_id={old["id"]: old},
        after_by_id={other["id"]: other},
        source_id_by_after_id={},
    )
    assert [(p.code, p.object_id, p.field) for p in report.errors] == [
        ("timestamp_invalid", other["id"], "captured_at")
    ]
    assert not report.grandfathered


def test_context_replace_action_matrix_distinguishes_exact_move_from_live_rename():
    old = mapping(object_id="mapping.neutral.old", meaning="same")
    exact_move = {**old, "id": "mapping.neutral.new"}
    changed_move = {**exact_move, "meaning": "changed"}
    exact = classify_object_actions(
        operation="context_replace",
        existing_by_id={old["id"]: old},
        transformed_by_id={exact_move["id"]: exact_move},
        delete_ids=(old["id"],),
        rename_pairs=((old["id"], exact_move["id"]),),
        verified_reference_rewrites=(),
    )
    live = classify_object_actions(
        operation="context_replace",
        existing_by_id={old["id"]: old},
        transformed_by_id={changed_move["id"]: changed_move},
        delete_ids=(old["id"],),
        rename_pairs=((old["id"], changed_move["id"]),),
        verified_reference_rewrites=(),
    )
    assert (exact[0].action, exact[0].source_id) == (
        ObjectActionKind.RENAME,
        old["id"],
    )
    assert exact[0].timestamp_policy is TimestampPolicy.PRESERVE
    assert live[0].timestamp_policy is TimestampPolicy.LIVE


def test_reference_only_rewrite_requires_same_pointer_shape():
    before = mapping(evidence_refs=["evref.neutral.old"])
    after = {**before, "evidence_refs": ["evref.neutral.new"]}
    assert reference_only_rewrite(
        before, after, {"evref.neutral.old": "evref.neutral.new"}
    )
    assert not reference_only_rewrite(
        before,
        {**after, "evidence_refs": ["evref.neutral.new", "evref.neutral.extra"]},
        {"evref.neutral.old": "evref.neutral.new"},
    )


def test_verified_same_pointer_reference_rewrite_is_a_preserve_action():
    before = mapping(evidence_refs=["evref.neutral.old"])
    after = {**before, "evidence_refs": ["evref.neutral.new"]}
    actions = classify_object_actions(
        operation="context_replace",
        existing_by_id={before["id"]: before},
        transformed_by_id={after["id"]: after},
        delete_ids=(),
        rename_pairs=(),
        verified_reference_rewrites=(
            VerifiedReferenceRewrite(
                object_id=before["id"],
                pointer="/evidence_refs/0",
                before_id="evref.neutral.old",
                after_id="evref.neutral.new",
            ),
        ),
    )
    assert [(action.action, action.timestamp_policy) for action in actions] == [
        (ObjectActionKind.REFERENCE_REWRITE, TimestampPolicy.PRESERVE)
    ]


def test_unregistered_operation_action_pair_has_no_timestamp_policy_fallback():
    obj = mapping()
    with pytest.raises(ValueError, match="timestamp_policy_missing"):
        classify_object_actions(
            operation="projection_repair",
            existing_by_id={},
            transformed_by_id={obj["id"]: obj},
            delete_ids=(),
            rename_pairs=(),
            verified_reference_rewrites=(),
        )


def test_engine_owned_temporal_and_operation_omission_maps_are_behaviorally_distinct():
    assert engine_owned_temporal_fields("EventLedgerRecord") == frozenset(
        {"created_at", "updated_at"}
    )
    assert engine_owned_temporal_fields("CodeLocator") == frozenset(
        {"created_at", "updated_at", "verified_at"}
    )
    assert engine_owned_temporal_fields("ContextProjection") == frozenset(
        {"created_at", "updated_at", "generated_at"}
    )
    assert "reviewed_at" not in engine_owned_input_fields("ingest", "ReviewRecord")
    assert "reviewed_at" in engine_owned_input_fields("promote", "ReviewRecord")


def test_live_timestamp_policy_stamps_lifecycle_but_preserves_caller_event_time():
    obj = event(happened_at="2026-08-01T09:00:00+09:00")
    action = classify_object_actions(
        operation="ingest",
        existing_by_id={},
        transformed_by_id={obj["id"]: obj},
        delete_ids=(),
        rename_pairs=(),
        verified_reference_rewrites=(),
    )
    stamped = apply_timestamp_policy(
        [obj],
        actions=action,
        existing_by_id={},
        operation="ingest",
        verified_object_ids=(),
        event_time=EVENT_TIME,
    )[0]
    assert (stamped["created_at"], stamped["updated_at"]) == (
        EVENT_TIME,
        EVENT_TIME,
    )
    assert stamped["happened_at"] == "2026-08-01T09:00:00+09:00"
