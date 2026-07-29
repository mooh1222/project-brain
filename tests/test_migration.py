from __future__ import annotations

import hashlib
import json
from dataclasses import fields, replace
from pathlib import Path
from unittest import mock

import pytest

from project_brain.migration import (
    MigrationError,
    MigrationRow,
    apply_migration_artifact,
    canonical_payload_hash_pair,
    create_migration_artifact,
    plan_display_migration,
    plan_id_migration,
)
from project_brain.store import BrainStore
from project_brain.snapshot import SnapshotVerification
from tests.test_ingest import evidence_ref, manifest, review_record_for
from tests.test_mutation import _code_locator, _write_raw


SNAPSHOT_ID = "trusted-before-id-migration"
SNAPSHOT_SHA = "a" * 64
ENGINE_SHA = "e" * 40


def _snapshot_verification(
    *,
    snapshot_id: str = SNAPSHOT_ID,
    manifest_sha256: str = SNAPSHOT_SHA,
) -> SnapshotVerification:
    return SnapshotVerification(
        ok=True,
        snapshot_id=snapshot_id,
        manifest_sha256=manifest_sha256,
        file_count=1,
    )


def _apply(artifact, brain_root: Path, **overrides):
    kwargs = {
        "manifest_bytes": artifact.manifest_bytes,
        "expected_manifest_sha256": artifact.manifest_sha256,
        "brain_root": brain_root,
        "engine_sha": ENGINE_SHA,
        "snapshot_root": brain_root.parent / "snapshot",
        "expected_snapshot_manifest_sha256": SNAPSHOT_SHA,
        **overrides,
    }
    with mock.patch(
        "project_brain.migration.verify_snapshot",
        return_value=_snapshot_verification(),
    ):
        return apply_migration_artifact(**kwargs)


def _write_eval(brain_root: Path, payload: dict) -> bytes:
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    (brain_root / "eval_scenarios.json").write_bytes(encoded)
    return encoded


def _id_plan(brain_root: Path, renames: dict[str, str]):
    return plan_id_migration(
        existing=BrainStore.load(brain_root),
        brain_root=brain_root,
        engine_sha=ENGINE_SHA,
        renames=renames,
        snapshot_id=SNAPSHOT_ID,
        snapshot_manifest_sha256=SNAPSHOT_SHA,
    )


def test_migration_row_has_exact_contract_fields():
    assert [field.name for field in fields(MigrationRow)] == [
        "old_id",
        "new_id",
        "kind",
        "canonical_payload_hash",
        "reference_rewrites",
        "dependent_artifacts",
        "snapshot_id",
    ]


def test_id_plan_tokenizes_self_and_registered_refs_and_lists_every_pointer(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    old_locator = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy display",
    )
    old_review = review_record_for("review.code.Legacy", old_locator["id"])
    _write_raw(brain_root, old_locator)
    _write_raw(brain_root, old_review)
    eval_before = {
        "scenarios": [{
            "id": "migration",
            "query": "query keeps code.Legacy literally",
            "expect": {
                "top5_any": ["code.Legacy"],
                "linked_any_groups": [["review.code.Legacy"]],
                "raw_top5_prefix_any": ["code.Legacy"],
            },
        }],
        "note": "code.Legacy outside registry stays unchanged",
    }
    _write_eval(brain_root, eval_before)
    local = brain_root / ".brain-local"
    local.mkdir()
    (local / "stale-set.json").write_text(
        json.dumps({
            "stale_mapping_ids": ["code.Legacy"],
            "note": "code.Legacy",
        }),
        encoding="utf-8",
    )
    (local / "index.db").write_bytes(b"synthetic index")

    plan = _id_plan(brain_root, {
        "code.Legacy": "code.neutral.legacy",
        "review.code.Legacy": "review.code.neutral.legacy",
    })

    assert plan.mutation_plan.ok is True
    assert [row.old_id for row in plan.rows] == [
        "code.Legacy",
        "review.code.Legacy",
    ]
    assert all(
        set(row.__dict__) == {
            "old_id",
            "new_id",
            "kind",
            "canonical_payload_hash",
            "reference_rewrites",
            "dependent_artifacts",
            "snapshot_id",
        }
        for row in plan.rows
    )
    locator_row, review_row = plan.rows
    assert locator_row.canonical_payload_hash
    assert locator_row.reference_rewrites == ({
        "object_id": "review.code.neutral.legacy",
        "pointer": "/target_object_id",
        "before_id": "code.Legacy",
        "after_id": "code.neutral.legacy",
    },)
    assert {
        (item["artifact"], item["action"])
        for item in locator_row.dependent_artifacts
    } >= {
        ("eval_scenarios.json", "rewrite"),
        (".brain-local/stale-set.json", "invalidate"),
        (".brain-local/index.db*", "invalidate"),
    }
    rewritten_eval = json.loads(
        plan.request.auxiliary_updates[0].after_bytes
    )
    scenario = rewritten_eval["scenarios"][0]
    assert scenario["expect"]["top5_any"] == ["code.neutral.legacy"]
    assert scenario["expect"]["linked_any_groups"] == [
        ["review.code.neutral.legacy"],
    ]
    assert scenario["expect"]["raw_top5_prefix_any"] == ["code.Legacy"]
    assert scenario["query"] == "query keeps code.Legacy literally"
    assert rewritten_eval["note"] == eval_before["note"]


def test_canonical_payload_rejects_every_non_registry_semantic_change():
    before = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy display",
    )
    after = dict(before)
    after["id"] = "code.neutral.legacy"
    expected = canonical_payload_hash_pair(
        before,
        after,
        renames={"code.Legacy": "code.neutral.legacy"},
        old_id="code.Legacy",
        new_id="code.neutral.legacy",
    )
    assert len(expected) == 64

    for field_name, value in (
        ("title", "changed"),
        ("status", "candidate"),
        ("path", "Changed.cpp"),
        ("symbol", "Changed"),
        ("commit_sha", "1" * 40),
        ("verified_at", "2099-01-01T00:00:00Z"),
        ("verified_quote", "changed quote"),
        ("meaning", "changed meaning"),
    ):
        changed = dict(after)
        changed[field_name] = value
        with pytest.raises(MigrationError, match="canonical payload"):
            canonical_payload_hash_pair(
                before,
                changed,
                renames={"code.Legacy": "code.neutral.legacy"},
                old_id="code.Legacy",
                new_id="code.neutral.legacy",
            )


@pytest.mark.parametrize(
    ("snapshot_id", "snapshot_sha", "error_code"),
    [
        ("", SNAPSHOT_SHA, "snapshot_id_invalid"),
        ("../unsafe", SNAPSHOT_SHA, "snapshot_id_invalid"),
        (SNAPSHOT_ID, "", "snapshot_receipt_invalid"),
        (SNAPSHOT_ID, "A" * 64, "snapshot_receipt_invalid"),
    ],
)
def test_plan_rejects_empty_or_unsafe_snapshot_binding(
    tmp_path,
    snapshot_id,
    snapshot_sha,
    error_code,
):
    brain_root = (tmp_path / "brain").resolve()
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)

    with pytest.raises(MigrationError) as caught:
        plan_id_migration(
            existing=BrainStore.load(brain_root),
            brain_root=brain_root,
            engine_sha=ENGINE_SHA,
            renames={old["id"]: "code.neutral.legacy"},
            snapshot_id=snapshot_id,
            snapshot_manifest_sha256=snapshot_sha,
        )

    assert caught.value.code == error_code


@pytest.mark.parametrize(
    ("renames", "error_code"),
    [
        (
            {
                "code.Legacy": "code.neutral.same",
                "code.Other": "code.neutral.same",
            },
            "duplicate_new_id",
        ),
        (
            {"code.Legacy": "code.Other"},
            "migration_target_exists",
        ),
        (
            {"code.Missing": "code.neutral.missing"},
            "migration_source_missing",
        ),
    ],
)
def test_id_plan_rejects_merge_or_non_one_to_one_mapping(
    tmp_path,
    renames,
    error_code,
):
    brain_root = tmp_path / "brain"
    for object_id in ("code.Legacy", "code.Other"):
        _write_raw(
            brain_root,
            _code_locator(
                object_id=object_id,
                quote=None,
                title="legacy",
            ),
        )

    with pytest.raises(MigrationError) as caught:
        _id_plan(brain_root, renames)

    assert caught.value.code == error_code


def test_display_plan_changes_only_code_locator_title(tmp_path):
    brain_root = tmp_path / "brain"
    with_symbol = _code_locator(
        object_id="code.neutral.with-symbol",
        symbol="Namespace::Run",
        title="semantic label",
        quote=None,
    )
    without_symbol = _code_locator(
        object_id="code.neutral.legacy",
        title="semantic legacy label",
        quote=None,
        path="Source/Legacy.cpp",
    )
    without_symbol.pop("symbol")
    source_manifest = manifest()
    ref = evidence_ref("evref.neutral.display")
    ref["title"] = "EvidenceRef title is not a target"
    for obj in (with_symbol, without_symbol, source_manifest, ref):
        _write_raw(brain_root, obj)

    plan = plan_display_migration(
        existing=BrainStore.load(brain_root),
        brain_root=brain_root,
        engine_sha=ENGINE_SHA,
        snapshot_id=SNAPSHOT_ID,
        snapshot_manifest_sha256=SNAPSHOT_SHA,
    )

    after = {obj["id"]: obj for obj in plan.mutation_plan.after_objects}
    assert after[with_symbol["id"]]["title"] == "Namespace::Run"
    assert after[without_symbol["id"]]["title"] == "Legacy.cpp:legacy"
    assert ref["id"] not in after
    before = {with_symbol["id"]: with_symbol, without_symbol["id"]: without_symbol}
    for object_id, migrated in after.items():
        assert {
            key: value
            for key, value in migrated.items()
            if key != "title"
        } == {
            key: value
            for key, value in before[object_id].items()
            if key != "title"
        }


def test_apply_recomputes_manifest_and_rejects_canonical_hash_tampering(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    _write_eval(brain_root, {
        "scenarios": [{
            "id": "s",
            "query": "q",
            "expect": {"top5_any": [old["id"]]},
        }],
    })
    plan = _id_plan(
        brain_root,
        {old["id"]: "code.neutral.legacy"},
    )
    artifact = create_migration_artifact(plan)
    tampered = json.loads(artifact.manifest_bytes)
    tampered["rows"][0]["canonical_payload_hash"] = "0" * 64
    tampered_bytes = (
        json.dumps(
            tampered,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")

    with pytest.raises(MigrationError) as caught:
        _apply(
            replace(
                artifact,
                manifest_bytes=tampered_bytes,
                manifest_sha256=hashlib.sha256(
                    tampered_bytes,
                ).hexdigest(),
            ),
            brain_root,
        )

    assert caught.value.code == "manifest_revalidation_failed"
    assert BrainStore.load(brain_root).has(old["id"])


def test_apply_requires_exact_trusted_snapshot_and_manifest_receipts(tmp_path):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    plan = _id_plan(
        brain_root,
        {old["id"]: "code.neutral.legacy"},
    )
    artifact = create_migration_artifact(plan)

    for changes, verification, error_code in (
        (
            {"expected_manifest_sha256": "0" * 64},
            _snapshot_verification(),
            "manifest_sha256_mismatch",
        ),
        (
            {},
            _snapshot_verification(snapshot_id="other"),
            "snapshot_binding_mismatch",
        ),
        (
            {},
            _snapshot_verification(manifest_sha256="0" * 64),
            "snapshot_binding_mismatch",
        ),
    ):
        kwargs = {
            "manifest_bytes": artifact.manifest_bytes,
            "expected_manifest_sha256": artifact.manifest_sha256,
            "brain_root": brain_root,
            "engine_sha": ENGINE_SHA,
            "snapshot_root": brain_root.parent / "snapshot",
            "expected_snapshot_manifest_sha256": SNAPSHOT_SHA,
            **changes,
        }
        with mock.patch(
            "project_brain.migration.verify_snapshot",
            return_value=verification,
        ), pytest.raises(MigrationError) as caught:
            apply_migration_artifact(**kwargs)
        assert caught.value.code == error_code


def test_id_apply_commits_exact_object_eval_and_invalidates_derived(tmp_path):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    _write_eval(brain_root, {
        "scenarios": [{
            "id": "s",
            "query": "q",
            "expect": {"top5_any": [old["id"]]},
        }],
    })
    local = brain_root / ".brain-local"
    local.mkdir()
    (local / "index.db").write_bytes(b"index")
    (local / "stale-set.json").write_text(
        '{"stale_mapping_ids":["code.Legacy"]}\n',
        encoding="utf-8",
    )
    plan = _id_plan(
        brain_root,
        {old["id"]: "code.neutral.legacy"},
    )
    artifact = create_migration_artifact(plan)

    result = _apply(artifact, brain_root)

    assert result.transaction_id == plan.mutation_plan.manifest.transaction_id
    store = BrainStore.load(brain_root)
    assert not store.has(old["id"])
    assert store.has("code.neutral.legacy")
    eval_payload = json.loads((brain_root / "eval_scenarios.json").read_bytes())
    assert eval_payload["scenarios"][0]["expect"]["top5_any"] == [
        "code.neutral.legacy",
    ]
    assert not (local / "index.db").exists()
    assert not (local / "stale-set.json").exists()
