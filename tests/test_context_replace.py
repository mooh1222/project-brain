from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import project_brain.transaction_receipt as transaction_receipt

from project_brain.context_replace import (
    ContextReplaceError,
    apply_context_replace_artifact,
    create_context_replace_artifact,
    plan_context_replace,
)
from project_brain.mutation import (
    MutationOperation,
    MutationService,
)
from project_brain.reference_fields import iter_object_refs
from project_brain.store import BrainStore
from tests.test_ingest import (
    candidate_term,
    context,
    evidence_ref,
    manifest,
    review_record_for,
)
from tests.test_mutation import _write_raw


ENGINE_SHA = "e" * 40
FIXED_TIME = "2026-08-05T12:34:56+09:00"


def _hash(obj: dict) -> str:
    return hashlib.sha256(BrainStore.object_bytes(obj)).hexdigest()


def _plan(
    brain_root: Path,
    *,
    desired_objects: list[dict],
    expected_drop_ids=(),
    expected_moves=None,
    external_reference_rewrites=None,
):
    existing = BrainStore.load(brain_root)
    return plan_context_replace(
        context_id="context.neutral",
        existing=existing,
        brain_root=brain_root.resolve(),
        repo_context=None,
        engine_sha=ENGINE_SHA,
        desired_objects=desired_objects,
        expected_drop_ids=expected_drop_ids,
        expected_moves=expected_moves or {},
        external_reference_rewrites=external_reference_rewrites or {},
    )


def _write_legacy_without_trailing_lf(brain_root: Path, obj: dict) -> Path:
    path = BrainStore.object_path(brain_root, obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
    )
    return path


def _apply_artifact(brain_root: Path, request):
    artifact = create_context_replace_artifact(request)
    result = apply_context_replace_artifact(
        manifest_bytes=artifact.manifest_bytes,
        expected_manifest_sha256=artifact.manifest_sha256,
        brain_root=brain_root,
        repo_context=None,
        engine_sha=ENGINE_SHA,
    )
    return artifact, result


def test_context_replace_rejects_expanded_artifact_keys(tmp_path):
    brain_root = tmp_path / "brain"
    before = context()
    _write_raw(brain_root, before)
    after = dict(before)
    after["title"] = "확장 manifest 적용"
    request = _plan(brain_root, desired_objects=[after])
    artifact = create_context_replace_artifact(request)
    expanded = {
        **artifact.manifest,
        "coverage_sha256": None,
        "expected_objects": [],
        "verified_objects": [],
        "changed_objects": [],
    }
    manifest_bytes = (
        json.dumps(expanded, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    with pytest.raises(ContextReplaceError) as caught:
        apply_context_replace_artifact(
            manifest_bytes=manifest_bytes,
            expected_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            brain_root=brain_root,
            repo_context=None,
            engine_sha=ENGINE_SHA,
        )

    assert caught.value.code == "manifest_invalid"
    assert BrainStore.load(brain_root).get(after["id"]) == before


def test_context_replace_does_not_force_old_and_new_counts_to_match(tmp_path):
    brain_root = tmp_path / "brain"
    ctx = context(glossary_term_ids=["g.neutral.keep", "g.neutral.drop"])
    keep = candidate_term("g.neutral.keep", term="유지")
    drop = candidate_term("g.neutral.drop", term="삭제")
    for obj in (ctx, keep, drop):
        _write_raw(brain_root, obj)
    desired_context = dict(ctx)
    desired_context["glossary_term_ids"] = [
        keep["id"],
        "g.neutral.created-a",
        "g.neutral.created-b",
    ]
    created_a = candidate_term("g.neutral.created-a", term="신규 A")
    created_b = candidate_term("g.neutral.created-b", term="신규 B")

    request = _plan(
        brain_root,
        desired_objects=[desired_context, keep, created_a, created_b],
        expected_drop_ids=(drop["id"],),
    )
    result = MutationService().plan(request.objects, request=request)

    assert request.operation is MutationOperation.CONTEXT_REPLACE
    assert result.ok is True
    assert {item["object_id"] for item in result.manifest.creates} == {
        created_a["id"],
        created_b["id"],
    }
    assert {item["object_id"] for item in result.manifest.deletes} == {
        drop["id"],
    }


def test_context_replace_keeps_unchanged_external_unknown_grammar_bound(tmp_path):
    brain_root = tmp_path / "brain"
    keep = candidate_term("g.neutral.keep", term="유지")
    drop = candidate_term("g.neutral.drop", term="삭제")
    ctx = context(glossary_term_ids=[keep["id"], drop["id"]])
    legacy = review_record_for(
        "review.disturb-boostedbomb.depth-config",
        ctx["id"],
    )
    for obj in (ctx, keep, drop, legacy):
        _write_raw(brain_root, obj)
    desired_context = dict(ctx)
    desired_context["glossary_term_ids"] = [keep["id"]]

    request = _plan(
        brain_root,
        desired_objects=[desired_context, keep],
        expected_drop_ids=(drop["id"],),
    )
    result = MutationService().plan(request.objects, request=request)

    assert result.ok is True
    assert result.manifest.grandfathered_problems_before == (
        result.manifest.grandfathered_problems_after
    )
    assert result.manifest.grandfathered_problems_after[0]["object_id"] == (
        legacy["id"]
    )


def test_context_membership_follows_registered_forward_references(tmp_path):
    brain_root = tmp_path / "brain"
    source_manifest = manifest()
    reference = evidence_ref()
    term = candidate_term()
    term["evidence_refs"] = [reference["id"]]
    ctx = context(glossary_term_ids=[term["id"]])
    desired = [ctx, term, reference, source_manifest]
    for obj in desired:
        _write_raw(brain_root, obj)

    request = _plan(brain_root, desired_objects=desired)

    assert {obj["id"] for obj in request.objects} == {
        obj["id"] for obj in desired
    }
    assert request.delete_ids == ()


def test_context_replace_expected_moves_are_exact_real_renames(tmp_path):
    brain_root = tmp_path / "brain"
    old = candidate_term("g.neutral.old", term="이전")
    ctx = context(glossary_term_ids=[old["id"]])
    for obj in (ctx, old):
        _write_raw(brain_root, obj)
    new = candidate_term("g.neutral.new", term="새 의미")
    desired_context = dict(ctx)
    desired_context["glossary_term_ids"] = [new["id"]]

    request = _plan(
        brain_root,
        desired_objects=[desired_context, new],
        expected_moves={old["id"]: new["id"]},
    )
    result = MutationService().plan(request.objects, request=request)

    assert request.renames == {old["id"]: new["id"]}
    assert result.ok is True
    assert len(result.manifest.renames) == 1
    assert result.manifest.creates == ()
    assert result.manifest.deletes == ()
    rename = result.manifest.renames[0]
    stamped_new = next(
        obj for obj in result.after_objects if obj["id"] == new["id"]
    )
    assert rename["before_sha256"] == _hash(old)
    assert rename["after_sha256"] == _hash(stamped_new)


def test_context_replace_preserve_actions_share_one_transaction_clock(tmp_path):
    brain_root = tmp_path / "brain"
    old = candidate_term("g.neutral.old", term="같은 값")
    ctx = context(glossary_term_ids=[old["id"]])
    for obj in (ctx, old):
        _write_raw(brain_root, obj)
    new = {**old, "id": "g.neutral.new"}
    desired_context = {**ctx, "glossary_term_ids": [new["id"]]}
    request = _plan(
        brain_root,
        desired_objects=[desired_context, new],
        expected_moves={old["id"]: new["id"]},
    )
    calls: list[str] = []

    result = MutationService(
        clock=lambda: calls.append(FIXED_TIME) or FIXED_TIME
    ).apply(request.objects, request=request)

    stored = BrainStore.load(brain_root)
    assert result.outcome is transaction_receipt.MutationOutcome.COMMITTED
    assert calls == [FIXED_TIME]
    assert stored.get(new["id"])["created_at"] == old["created_at"]
    assert stored.get(new["id"])["updated_at"] == old["updated_at"]
    assert {(row["action"], row.get("id", row.get("new_id"))) for row in (
        result.manifest.changed_objects
    )} == {("update", ctx["id"]), ("rename", new["id"])}


@pytest.mark.parametrize(
    "action",
    ["exact_move", "semantic_move", "reference_only", "standalone_create"],
)
def test_context_replace_action_timestamp_matrix(tmp_path, action):
    brain_root = tmp_path / action
    old = candidate_term("g.neutral.old", term="같은 값")
    ctx = context(glossary_term_ids=[old["id"]])
    external = context("context.other", glossary_term_ids=[old["id"]])
    external["context_key"] = "other"
    for obj in (ctx, old):
        _write_raw(brain_root, obj)
    calls: list[str] = []

    if action == "standalone_create":
        created = candidate_term("g.neutral.created", term="신규")
        desired_context = {**ctx, "glossary_term_ids": [old["id"], created["id"]]}
        request = _plan(
            brain_root,
            desired_objects=[desired_context, old, created],
        )
        target_id = created["id"]
    else:
        new = {**old, "id": "g.neutral.new"}
        if action == "semantic_move":
            new["term"] = "바뀐 의미"
        desired_context = {**ctx, "glossary_term_ids": [new["id"]]}
        rewrites = {}
        if action == "reference_only":
            _write_raw(brain_root, external)
            rewrites = {old["id"]: new["id"]}
        request = _plan(
            brain_root,
            desired_objects=[desired_context, new],
            expected_moves={old["id"]: new["id"]},
            external_reference_rewrites=rewrites,
        )
        target_id = external["id"] if action == "reference_only" else new["id"]

    result = MutationService(
        clock=lambda: calls.append(FIXED_TIME) or FIXED_TIME
    ).apply(request.objects, request=request)

    assert result.ok
    assert calls == [FIXED_TIME]
    stored = BrainStore.load(brain_root).get(target_id)
    if action in {"exact_move", "reference_only"}:
        source = old if action == "exact_move" else external
        assert (stored["created_at"], stored["updated_at"]) == (
            source["created_at"], source["updated_at"]
        )
    elif action == "semantic_move":
        assert (stored["created_at"], stored["updated_at"]) == (
            old["created_at"], FIXED_TIME
        )
    else:
        assert stored["created_at"] == stored["updated_at"] == FIXED_TIME


@pytest.mark.parametrize(
    ("drops", "moves", "expected_code"),
    [
        ((), {}, "drop_set_mismatch"),
        (("g.neutral.old",), {"g.neutral.old": "g.neutral.new"},
         "move_drop_overlap"),
        ((), {"g.neutral.old": "g.neutral.missing"}, "move_target_mismatch"),
    ],
)
def test_context_replace_rejects_inexact_drop_or_move_contract(
    tmp_path,
    drops,
    moves,
    expected_code,
):
    brain_root = tmp_path / "brain"
    old = candidate_term("g.neutral.old", term="이전")
    ctx = context(glossary_term_ids=[old["id"]])
    for obj in (ctx, old):
        _write_raw(brain_root, obj)
    new = candidate_term("g.neutral.new", term="새 의미")
    desired_context = dict(ctx)
    desired_context["glossary_term_ids"] = [new["id"]]

    with pytest.raises(ContextReplaceError) as caught:
        _plan(
            brain_root,
            desired_objects=[desired_context, new],
            expected_drop_ids=drops,
            expected_moves=moves,
        )

    assert caught.value.code == expected_code


def test_context_replace_rejects_delete_with_external_backreference(tmp_path):
    brain_root = tmp_path / "brain"
    old = candidate_term("g.neutral.old", term="이전")
    ctx = context(glossary_term_ids=[old["id"]])
    external = context("context.other", glossary_term_ids=[old["id"]])
    external["context_key"] = "other"
    for obj in (ctx, old, external):
        _write_raw(brain_root, obj)
    desired_context = dict(ctx)
    desired_context["glossary_term_ids"] = []

    with pytest.raises(ContextReplaceError) as caught:
        _plan(
            brain_root,
            desired_objects=[desired_context],
            expected_drop_ids=(old["id"],),
        )

    assert caught.value.code == "external_reference_rewrite_required"


def test_context_replace_rewrites_declared_external_backreference(tmp_path):
    brain_root = tmp_path / "brain"
    old = candidate_term("g.neutral.old", term="이전")
    new = candidate_term("g.neutral.new", term="새 값")
    ctx = context(glossary_term_ids=[old["id"]])
    external = context("context.other", glossary_term_ids=[old["id"]])
    external["context_key"] = "other"
    for obj in (ctx, old, external):
        _write_raw(brain_root, obj)
    desired_context = dict(ctx)
    desired_context["glossary_term_ids"] = [new["id"]]

    request = _plan(
        brain_root,
        desired_objects=[desired_context, new],
        expected_moves={old["id"]: new["id"]},
        external_reference_rewrites={old["id"]: new["id"]},
    )
    rewritten_external = next(
        obj for obj in request.objects if obj["id"] == external["id"]
    )
    result = MutationService().plan(request.objects, request=request)

    assert [ref.object_id for ref in iter_object_refs(rewritten_external)] == [
        new["id"],
    ]
    assert request.preconditions[external["id"]] == _hash(external)
    assert getattr(request, "external_reference_rewrites", {}) == {
        old["id"]: new["id"],
    }
    assert result.ok is True
    assert {
        (row["object_id"], row["before_id"], row["after_id"])
        for row in result.manifest.reference_rewrites
    } == {
        (ctx["id"], old["id"], new["id"]),
        (external["id"], old["id"], new["id"]),
    }


def test_context_replace_artifact_is_unstamped_intent(tmp_path):
    brain_root = tmp_path / "brain"
    before = context()
    _write_raw(brain_root, before)
    request = _plan(
        brain_root,
        desired_objects=[{**before, "title": "새 제목"}],
    )

    artifact = create_context_replace_artifact(request)

    assert "intent" in artifact.manifest
    assert "transaction_id" not in artifact.manifest
    assert "creates" not in artifact.manifest
    assert "updates" not in artifact.manifest


def test_production_artifact_paths_use_preview_and_central_bound_apply():
    project = Path(__file__).resolve().parents[1]
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in (
            project / "src/project_brain/context_replace.py",
            project / "src/project_brain/migration.py",
            project / "src/project_brain/canonical_repair.py",
        )
    }

    assert all(".plan(" not in text for text in sources.values())
    assert "apply_transaction(" not in sources["context_replace.py"]
    assert all("apply_bound_intent(" in text for text in sources.values())


def test_context_replace_update_uses_legacy_raw_before_receipt_and_applies(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    old = context()
    old_path = _write_legacy_without_trailing_lf(brain_root, old)
    replacement = dict(old)
    replacement["title"] = "legacy update"

    request = _plan(brain_root, desired_objects=[replacement])
    artifact, _ = _apply_artifact(brain_root, request)
    source_sha256_by_id = artifact.manifest["intent"]["preview"][
        "source_sha256_by_id"
    ]
    stored = BrainStore.load(brain_root).get(replacement["id"])

    assert source_sha256_by_id[old["id"]] == hashlib.sha256(
        json.dumps(old, ensure_ascii=False, indent=2).encode("utf-8")
    ).hexdigest()
    assert stored["title"] == "legacy update"
    assert old_path.read_bytes() == BrainStore.object_bytes(stored)


def test_context_replace_delete_uses_legacy_raw_before_receipt_and_applies(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    old = candidate_term("g.neutral.old", term="이전")
    ctx = context(glossary_term_ids=[old["id"]])
    _write_raw(brain_root, ctx)
    old_path = _write_legacy_without_trailing_lf(brain_root, old)
    desired_context = dict(ctx)
    desired_context["glossary_term_ids"] = []

    request = _plan(
        brain_root,
        desired_objects=[desired_context],
        expected_drop_ids=(old["id"],),
    )
    artifact, _ = _apply_artifact(brain_root, request)
    source_sha256_by_id = artifact.manifest["intent"]["preview"][
        "source_sha256_by_id"
    ]

    assert source_sha256_by_id[old["id"]] == hashlib.sha256(
        json.dumps(old, ensure_ascii=False, indent=2).encode("utf-8")
    ).hexdigest()
    assert not old_path.exists()


def test_context_replace_rename_uses_legacy_raw_before_receipt_and_applies(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    old = candidate_term("g.neutral.old", term="이전")
    ctx = context(glossary_term_ids=[old["id"]])
    _write_raw(brain_root, ctx)
    old_path = _write_legacy_without_trailing_lf(brain_root, old)
    new = candidate_term("g.neutral.new", term="새 값")
    desired_context = dict(ctx)
    desired_context["glossary_term_ids"] = [new["id"]]

    request = _plan(
        brain_root,
        desired_objects=[desired_context, new],
        expected_moves={old["id"]: new["id"]},
    )
    artifact, _ = _apply_artifact(brain_root, request)
    new_path = BrainStore.object_path(brain_root, new)
    source_sha256_by_id = artifact.manifest["intent"]["preview"][
        "source_sha256_by_id"
    ]
    stored = BrainStore.load(brain_root).get(new["id"])

    assert source_sha256_by_id[old["id"]] == hashlib.sha256(
        json.dumps(old, ensure_ascii=False, indent=2).encode("utf-8")
    ).hexdigest()
    assert not old_path.exists()
    assert new_path.read_bytes() == BrainStore.object_bytes(stored)


def test_context_replace_case_only_rename_keeps_legacy_raw_receipt(tmp_path):
    """A newline-normalizing case rename would fail this literal receipt."""
    brain_root = tmp_path / "brain"
    old = candidate_term("g.neutral.Legacy", term="이전")
    ctx = context(glossary_term_ids=[old["id"]])
    _write_raw(brain_root, ctx)
    old_path = _write_legacy_without_trailing_lf(brain_root, old)
    new = candidate_term("g.neutral.legacy", term="새 값")
    desired_context = dict(ctx)
    desired_context["glossary_term_ids"] = [new["id"]]

    request = _plan(
        brain_root,
        desired_objects=[desired_context, new],
        expected_moves={old["id"]: new["id"]},
    )
    artifact, result = _apply_artifact(brain_root, request)
    new_path = BrainStore.object_path(brain_root, new)
    source_sha256_by_id = artifact.manifest["intent"]["preview"][
        "source_sha256_by_id"
    ]
    stored = BrainStore.load(brain_root).get(new["id"])

    assert result.action_count == 2
    assert source_sha256_by_id[old["id"]] == hashlib.sha256(
        json.dumps(old, ensure_ascii=False, indent=2).encode("utf-8")
    ).hexdigest()
    assert new_path.name in {path.name for path in new_path.parent.iterdir()}
    assert old_path.name not in {path.name for path in old_path.parent.iterdir()}
    assert new_path.read_bytes() == BrainStore.object_bytes(stored)


def test_context_replace_rejects_post_plan_legacy_whitespace_change_before_write(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    old = context()
    old_path = _write_legacy_without_trailing_lf(brain_root, old)
    replacement = dict(old)
    replacement["title"] = "planned replacement"
    request = _plan(brain_root, desired_objects=[replacement])
    artifact = create_context_replace_artifact(request)
    index_path = brain_root / ".brain-local" / "index.sqlite3"
    stale_path = brain_root / ".brain-local" / "stale-set.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(b"index before\n")
    stale_path.write_bytes(b'{"stale":["before"]}\n')
    changed_raw = json.dumps(old, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    old_path.write_bytes(changed_raw)

    with pytest.raises(ContextReplaceError) as caught:
        apply_context_replace_artifact(
            manifest_bytes=artifact.manifest_bytes,
            expected_manifest_sha256=artifact.manifest_sha256,
            brain_root=brain_root,
            repo_context=None,
            engine_sha=ENGINE_SHA,
        )

    assert caught.value.code == "intent_revalidation_failed"
    assert old_path.read_bytes() == changed_raw
    assert index_path.read_bytes() == b"index before\n"
    assert stale_path.read_bytes() == b'{"stale":["before"]}\n'


@pytest.mark.parametrize("operation", ["update", "delete", "rename"])
def test_context_replace_canonical_before_receipts_still_apply(tmp_path, operation):
    brain_root = tmp_path / "brain"
    old = candidate_term("g.neutral.old", term="이전")
    ctx = context(glossary_term_ids=[old["id"]])
    for obj in (ctx, old):
        _write_raw(brain_root, obj)

    if operation == "update":
        replacement = dict(ctx)
        replacement["title"] = "canonical update"
        request = _plan(brain_root, desired_objects=[replacement, old])
    elif operation == "delete":
        replacement = dict(ctx)
        replacement["glossary_term_ids"] = []
        request = _plan(
            brain_root,
            desired_objects=[replacement],
            expected_drop_ids=(old["id"],),
        )
    else:
        new = candidate_term("g.neutral.new", term="새 값")
        replacement = dict(ctx)
        replacement["glossary_term_ids"] = [new["id"]]
        request = _plan(
            brain_root,
            desired_objects=[replacement, new],
            expected_moves={old["id"]: new["id"]},
        )

    before_path = BrainStore.object_path(
        brain_root,
        old if operation != "update" else ctx,
    )
    raw_before = before_path.read_bytes()
    artifact, _ = _apply_artifact(brain_root, request)
    before_obj = old if operation != "update" else ctx

    source_sha256_by_id = artifact.manifest["intent"]["preview"][
        "source_sha256_by_id"
    ]
    assert source_sha256_by_id[before_obj["id"]] == _hash(before_obj)
    assert source_sha256_by_id[before_obj["id"]] == hashlib.sha256(
        raw_before
    ).hexdigest()
