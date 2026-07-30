from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from project_brain.context_replace import (
    ContextReplaceError,
    plan_context_replace,
)
from project_brain.mutation import MutationOperation, MutationService
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
    assert rename["before_sha256"] == _hash(old)
    assert rename["after_sha256"] == _hash(new)


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
    assert result.ok is True
    assert {
        (row["object_id"], row["before_id"], row["after_id"])
        for row in result.manifest.reference_rewrites
    } == {
        (ctx["id"], old["id"], new["id"]),
        (external["id"], old["id"], new["id"]),
    }
