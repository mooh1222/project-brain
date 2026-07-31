from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Sequence
from dataclasses import fields, replace
from pathlib import Path

import pytest

import project_brain.mutation as mutation
from project_brain.mutation import (
    AuxiliaryFileUpdate,
    MutationManifest,
    MutationOperation,
    MutationRequest,
    MutationService,
    corpus_fingerprint,
)
from project_brain.objbase import base
from project_brain.hash_utils import stable_json
from project_brain.hash_utils import source_content_hash
from project_brain.repo_context import resolve_repo_context
from project_brain.schema import validate_object_id
from project_brain.store import BrainStore
from project_brain.transaction_receipt import BatchBinding
from tests.test_ingest import (
    candidate_mapping,
    candidate_term,
    context,
    evidence_ref,
    manifest,
    review_record_for,
)


T = "2026-07-28T00:00:00+09:00"


class _ExplodingSequence(Sequence):
    def __len__(self):
        raise RuntimeError("exploding sequence")

    def __getitem__(self, index):
        raise RuntimeError("exploding sequence")


def _request(
    brain_root: Path,
    objects: tuple[dict, ...],
    *,
    operation: MutationOperation = MutationOperation.INGEST,
    repo_context=None,
    delete_ids: tuple[str, ...] = (),
    renames: dict[str, str] | None = None,
    preconditions: dict[str, str] | None = None,
    expected_corpus_fingerprint: str | None = None,
    auxiliary_updates: tuple[AuxiliaryFileUpdate, ...] = (),
    batch_binding: BatchBinding | None = None,
    canonical_repair_intents: tuple[object, ...] = (),
    canonical_repair_binding: dict[str, str] | None = None,
) -> MutationRequest:
    return MutationRequest(
        operation=operation,
        brain_root=brain_root,
        repo_context=repo_context,
        engine_sha="e" * 40,
        objects=objects,
        delete_ids=delete_ids,
        renames=renames or {},
        preconditions=preconditions or {},
        expected_corpus_fingerprint=expected_corpus_fingerprint,
        auxiliary_updates=auxiliary_updates,
        batch_binding=batch_binding,
        canonical_repair_intents=canonical_repair_intents,
        canonical_repair_binding=canonical_repair_binding,
    )


def _plan(
    brain_root: Path,
    objects: list[dict],
    **request_kwargs,
):
    inputs = tuple(objects)
    request = _request(brain_root, inputs, **request_kwargs)
    return MutationService().plan(inputs, request=request)


def _write_raw(brain_root: Path, obj: dict) -> None:
    path = (
        brain_root
        / BrainStore._KIND_DIR[obj["kind"]]
        / f"{obj['id']}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(obj, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    )


def _object_hash(obj: dict) -> str:
    return hashlib.sha256(BrainStore.object_bytes(obj)).hexdigest()


def _file_update(path: str, before: bytes, after: bytes) -> AuxiliaryFileUpdate:
    return AuxiliaryFileUpdate(
        path=path,
        before_sha256=hashlib.sha256(before).hexdigest(),
        after_sha256=hashlib.sha256(after).hexdigest(),
        after_bytes=after,
    )


def _problem_object_hash(obj: dict) -> str:
    return hashlib.sha256(stable_json(obj).encode("utf-8")).hexdigest()


def _canonical_repair_binding() -> dict[str, str]:
    return {
        "decision_ledger_sha256": "a" * 64,
        "phase_a_classification_sha256": "b" * 64,
    }


def _mapping_repair_request(
    tmp_path: Path,
    *,
    operation=None,
    tamper_field: str | None = None,
) -> MutationRequest:
    brain_root = tmp_path / "brain"
    old = candidate_mapping(
        "mapping.neutral.Legacy",
        glossary_term_ids=["g.neutral.term"],
        mapping_key="Legacy",
    )
    new = dict(old)
    new["id"] = "mapping.neutral.legacy"
    new["mapping_key"] = "legacy"
    if tamper_field is not None:
        new[tamper_field] = f"changed-{tamper_field}"
    for obj in (context(), candidate_term("g.neutral.term"), old):
        _write_raw(brain_root, obj)
    change = mutation.CanonicalFieldChange(
        pointer="/mapping_key",
        before="Legacy",
        after="legacy",
    )
    intent = mutation.CanonicalRepairIntent(
        source_id=old["id"],
        new_id=new["id"],
        reason_code="projected_field_repair",
        field_changes=(change,),
    )
    return _request(
        brain_root,
        (new,),
        operation=operation or MutationOperation.CANONICAL_REPAIR,
        delete_ids=(old["id"],),
        renames={old["id"]: new["id"]},
        canonical_repair_intents=(intent,),
        canonical_repair_binding=_canonical_repair_binding(),
    )


def _mixed_review_repair_request(
    tmp_path: Path,
    *,
    tamper: str | None = None,
    source_review_id: str = "review.bundle.Neutral.domain-mapping",
    cleanup_target_id: str = "g.neutral.term",
) -> MutationRequest:
    request = _mapping_repair_request(tmp_path)
    old_mapping = BrainStore.load(request.brain_root).get(
        request.delete_ids[0]
    )
    new_mapping = request.objects[0]
    stable_mapping = candidate_mapping(
        "mapping.neutral.stable",
        glossary_term_ids=["g.neutral.term"],
        mapping_key="stable",
    )
    _write_raw(request.brain_root, stable_mapping)

    old_review = review_record_for(
        source_review_id,
        old_mapping["id"],
    )
    old_review.pop("target_object_id")
    old_review.update({
        "review_scope": "mapping_bundle",
        "review_type": "meaning_review",
        "bundle_key": "bundle.neutral.domain-mapping",
        "confirmation_key": "bundle.neutral.domain-mapping",
        "target_object_ids": [
            old_mapping["id"],
            stable_mapping["id"],
            cleanup_target_id,
        ],
    })
    _write_raw(request.brain_root, old_review)
    new_review = dict(old_review)
    new_review["id"] = "review.bundle.neutral.domain-mapping"
    new_review["target_object_ids"] = [
        new_mapping["id"],
        stable_mapping["id"],
    ]
    if tamper == "add_target":
        new_review["target_object_ids"].append(stable_mapping["id"])
    elif tamper == "drop_mapping":
        new_review["target_object_ids"].pop()
    elif tamper == "change_scope":
        new_review["review_scope"] = "single_object"
    elif tamper == "change_bundle_key":
        new_review["bundle_key"] = "bundle.neutral.other"
    elif tamper == "replace_target":
        replacement = candidate_mapping(
            "mapping.neutral.replacement",
            glossary_term_ids=["g.neutral.term"],
            mapping_key="replacement",
        )
        _write_raw(request.brain_root, replacement)
        new_review["target_object_ids"][1] = replacement["id"]
    elif tamper == "reorder":
        new_review["target_object_ids"].reverse()

    mapping_intent = request.canonical_repair_intents[0]
    review_change = mutation.CanonicalFieldChange(
        pointer="/target_object_ids",
        before=[
            new_mapping["id"],
            stable_mapping["id"],
            cleanup_target_id,
        ],
        after=[new_mapping["id"], stable_mapping["id"]],
    )
    review_intent = mutation.CanonicalRepairIntent(
        source_id=old_review["id"],
        new_id=new_review["id"],
        reason_code="review_shape_repair",
        field_changes=(review_change,),
    )
    return replace(
        request,
        objects=(new_mapping, new_review),
        delete_ids=(old_mapping["id"], old_review["id"]),
        renames={
            old_mapping["id"]: new_mapping["id"],
            old_review["id"]: new_review["id"],
        },
        canonical_repair_intents=(mapping_intent, review_intent),
    )


def _legacy_invalid_context(*, title: str = "legacy") -> dict:
    obj = context("context.Legacy")
    obj["context_key"] = "Legacy"
    obj["title"] = title
    return obj


def _legacy_unknown_review(*, title: str = "legacy") -> dict:
    record = review_record_for(
        "review.disturb-boostedbomb.depth-config",
        "context.neutral",
    )
    record["title"] = title
    return record


def _projection(
    *,
    object_id: str = "projection.neutral.req.reuse",
    source_ids: list[str] | None = None,
    source_hash: str = "stale",
) -> dict:
    return base(
        {
            "id": object_id,
            "kind": "ContextProjection",
            "status": "candidate",
            "truth_role": "index",
            "title": "reuse",
            "context_id": "context.neutral",
            "format": "prompt_payload",
            "reuse_payload": "payload",
            "output_locator": "indexes/context_projections/neutral.req.reuse.txt",
            "source_object_ids": source_ids or ["context.neutral"],
            "source_content_hash": source_hash,
            "projection_hash": "projection-hash",
            "generated_at": T,
            "generated_by": "test",
            "stale_policy": "fail_on_manual_edit",
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _promotion_bundle(term: dict, *, reviewer: str = "second") -> list[dict]:
    reviewed = dict(term)
    reviewed["status"] = "reviewed"
    reviewed["updated_at"] = T
    reviewed.pop("candidate", None)
    review_id = f"review.{term['id']}"
    reviewed["review_record_id"] = review_id
    record = review_record_for(review_id, term["id"])
    record["reviewer"] = reviewer
    return [reviewed, record]


def _code_locator(
    *,
    object_id: str = "code.neutral.foo",
    title: str = "untrusted title",
    repo: str = "demo",
    path: str = "Foo.cpp",
    symbol: str = "Foo::bar",
    commit_sha: str = "0" * 40,
    quote: str | None = "void Foo::bar() {}",
    verified_at: str | None = "1900-01-01T00:00:00Z",
) -> dict:
    payload = {
        "id": object_id,
        "kind": "CodeLocator",
        "status": "reviewed",
        "truth_role": "reference",
        "title": title,
        "repo": repo,
        "path": path,
        "symbol": symbol,
        "commit_sha": commit_sha,
        "locator_source": "rg",
    }
    if verified_at is not None:
        payload["verified_at"] = verified_at
    if quote is not None:
        payload["verified_quote"] = quote
    return base(payload, tags=["neutral"], created_at=T, updated_at=T)


def _git_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
    )
    (repo / "Foo.cpp").write_text("void Foo::bar() {}\n", encoding="utf-8")
    subprocess.run(["git", "add", "Foo.cpp"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    context_ = resolve_repo_context(
        repo.resolve(),
        expected_repo_id="demo",
        configured_repo_id="demo",
        expected_revision_ref=sha,
    )
    return context_, sha


def test_request_and_manifest_models_match_the_plan_contract():
    assert [field.name for field in fields(MutationRequest)] == [
        "operation",
        "brain_root",
        "repo_context",
        "engine_sha",
        "objects",
        "delete_ids",
        "renames",
        "preconditions",
        "expected_corpus_fingerprint",
        "auxiliary_updates",
        "batch_binding",
        "canonical_repair_intents",
        "canonical_repair_binding",
    ]
    assert [field.name for field in fields(MutationManifest)] == [
        "transaction_id",
        "operation",
        "engine_sha",
        "creates",
        "updates",
        "deletes",
        "renames",
        "reference_rewrites",
        "auxiliary_updates",
        "before_fingerprint",
        "expected_after_fingerprint",
        "grandfathered_problems_before",
        "grandfathered_problems_after",
        "batch_binding",
        "canonical_repair_binding",
    ]
    assert {operation.value for operation in MutationOperation} == {
        "ingest",
        "promote",
        "promote_auto",
        "mark_checked",
        "projection",
        "projection_repair",
        "context_replace",
        "id_only_migration",
        "display_migration",
        "canonical_repair",
    }


def test_canonical_repair_operation_and_manifest_binding_are_registered():
    assert MutationOperation.CANONICAL_REPAIR.value == "canonical_repair"
    assert "canonical_repair_binding" in {
        field.name for field in fields(MutationManifest)
    }


def test_canonical_intent_is_rejected_for_ingest(tmp_path):
    request = _mapping_repair_request(
        tmp_path,
        operation=MutationOperation.INGEST,
    )

    result = MutationService().plan(request.objects, request=request)

    assert result.error_code == "canonical_repair_intent_operation_invalid"


def test_canonical_repair_requires_intent_and_binding_before_store_load(tmp_path):
    brain_root = tmp_path / "brain"
    broken = brain_root / "objects" / "domain" / "broken.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{", encoding="utf-8")
    no_intent = _request(
        brain_root,
        (),
        operation=MutationOperation.CANONICAL_REPAIR,
        canonical_repair_binding=_canonical_repair_binding(),
    )

    result = MutationService().plan((), request=no_intent)

    assert result.error_code == "canonical_repair_intent_required"


def test_canonical_repair_binding_is_rejected_for_ingest_before_store_load(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    broken = brain_root / "objects" / "domain" / "broken.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{", encoding="utf-8")
    request = _request(
        brain_root,
        (),
        canonical_repair_binding=_canonical_repair_binding(),
    )

    result = MutationService().plan((), request=request)

    assert result.error_code == "canonical_repair_binding_operation_invalid"


def _projection_repair_plan(
    brain_root: Path,
    replacements: list[dict],
    *,
    preconditions: dict[str, str] | None = None,
    delete_ids: tuple[str, ...] = (),
):
    return _plan(
        brain_root,
        replacements,
        operation=MutationOperation.PROJECTION_REPAIR,
        preconditions=preconditions,
        delete_ids=delete_ids,
    )


def test_projection_repair_removes_existing_hash_mismatch(tmp_path):
    brain_root = tmp_path / "brain"
    source = context()
    stale = _projection()
    _write_raw(brain_root, source)
    _write_raw(brain_root, stale)
    repaired = dict(stale)
    repaired["source_content_hash"] = source_content_hash([source])

    result = _projection_repair_plan(
        brain_root,
        [repaired],
        preconditions={stale["id"]: _object_hash(stale)},
    )

    assert result.ok is True
    assert result.manifest.updates[0]["object_id"] == stale["id"]


@pytest.mark.parametrize(
    "operation",
    [MutationOperation.PROJECTION, MutationOperation.INGEST],
)
def test_general_mutation_still_rejects_existing_projection_mismatch(
    tmp_path,
    operation,
):
    brain_root = tmp_path / operation.value
    source = context()
    stale = _projection()
    _write_raw(brain_root, source)
    _write_raw(brain_root, stale)
    repaired = dict(stale)
    repaired["source_content_hash"] = source_content_hash([source])

    result = _plan(
        brain_root,
        [repaired],
        operation=operation,
        preconditions={stale["id"]: _object_hash(stale)},
    )

    assert result.error_code == "existing_lint_problem"


@pytest.mark.parametrize("case", ["missing", "extra", "mismatch"])
def test_projection_repair_requires_exact_before_hash_preconditions(tmp_path, case):
    brain_root = tmp_path / "brain"
    source = context()
    stale = _projection()
    _write_raw(brain_root, source)
    _write_raw(brain_root, stale)
    repaired = dict(stale)
    repaired["source_content_hash"] = source_content_hash([source])
    preconditions = {stale["id"]: _object_hash(stale)}
    if case == "missing":
        preconditions = {}
    elif case == "extra":
        preconditions["context.neutral"] = _object_hash(source)
    else:
        preconditions[stale["id"]] = "0" * 64

    result = _projection_repair_plan(
        brain_root,
        [repaired],
        preconditions=preconditions,
    )

    expected = (
        "precondition_hash_mismatch"
        if case == "mismatch"
        else "projection_repair_precondition_set_mismatch"
    )
    assert result.error_code == expected


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("create", "projection_repair_create_forbidden"),
        ("delete", "projection_repair_delete_forbidden"),
        ("rename", "projection_repair_delete_forbidden"),
        ("non_projection", "projection_repair_kind_invalid"),
        ("other_field", "projection_repair_field_invalid"),
    ],
)
def test_projection_repair_rejects_non_repair_shapes(
    tmp_path,
    case,
    expected_code,
):
    brain_root = tmp_path / "brain"
    source = context()
    stale = _projection()
    _write_raw(brain_root, source)
    _write_raw(brain_root, stale)
    repaired = dict(stale)
    repaired["source_content_hash"] = source_content_hash([source])
    delete_ids = ()
    if case == "create":
        repaired["id"] = "projection.neutral.new.reuse"
    elif case == "delete":
        delete_ids = (stale["id"],)
    elif case == "rename":
        repaired["id"] = "projection.neutral.renamed.reuse"
        delete_ids = (stale["id"],)
    elif case == "non_projection":
        repaired = dict(source)
        repaired["title"] = "changed"
    else:
        repaired["title"] = "changed"
    preconditions = {
        repaired["id"]: _object_hash(
            source if case == "non_projection" else stale
        )
    }

    result = _projection_repair_plan(
        brain_root,
        [repaired],
        preconditions=preconditions,
        delete_ids=delete_ids,
    )

    assert result.error_code == expected_code


@pytest.mark.parametrize("case", ["wrong_hash", "partial", "dangling"])
def test_projection_repair_rejects_incomplete_or_other_lint(tmp_path, case):
    brain_root = tmp_path / "brain"
    source = context()
    stale = _projection()
    _write_raw(brain_root, source)
    _write_raw(brain_root, stale)
    repaired = dict(stale)
    repaired["source_content_hash"] = (
        "still-wrong"
        if case == "wrong_hash"
        else source_content_hash([source])
    )
    if case == "partial":
        second = _projection(
            object_id="projection.neutral.other.reuse",
            source_hash="also-stale",
        )
        _write_raw(brain_root, second)
    elif case == "dangling":
        broken = context("context.broken", glossary_term_ids=["g.neutral.missing"])
        broken["context_key"] = "broken"
        _write_raw(brain_root, broken)

    result = _projection_repair_plan(
        brain_root,
        [repaired],
        preconditions={stale["id"]: _object_hash(stale)},
    )

    assert result.ok is False
    assert result.error_code in {
        "projection_repair_incomplete",
        "dangling_reference",
    }


@pytest.mark.parametrize(
    "operation",
    [MutationOperation.PROMOTE, MutationOperation.PROMOTE_AUTO],
)
def test_promotion_requires_exact_preconditions_for_target_ids(tmp_path, operation):
    brain_root = tmp_path / operation.value
    term = candidate_term()
    term["evidence_refs"] = ["evref.neutral.ref"]
    for obj in (manifest(), evidence_ref(), context(), term):
        _write_raw(brain_root, obj)
    promotion = _promotion_bundle(term)

    result = _plan(
        brain_root,
        promotion,
        operation=operation,
    )

    assert result.error_code == "promotion_precondition_set_mismatch"


@pytest.mark.parametrize(
    "operation",
    [MutationOperation.PROMOTE, MutationOperation.PROMOTE_AUTO],
)
def test_promotion_requires_exact_selection_snapshot(tmp_path, operation):
    brain_root = tmp_path / operation.value
    term = candidate_term()
    term["evidence_refs"] = ["evref.neutral.ref"]
    for obj in (manifest(), evidence_ref(), context(), term):
        _write_raw(brain_root, obj)
    promotion = _promotion_bundle(term)

    result = _plan(
        brain_root,
        promotion,
        operation=operation,
        preconditions={term["id"]: _object_hash(term)},
    )

    assert result.error_code == "promotion_corpus_fingerprint_required"


def test_second_promotion_apply_cannot_overwrite_reviewed_target_or_record(tmp_path):
    brain_root = tmp_path / "brain"
    stale_term = candidate_term()
    stale_term["evidence_refs"] = ["evref.neutral.ref"]
    first_promotion = _promotion_bundle(stale_term, reviewer="first")
    for obj in (manifest(), evidence_ref(), context(), *first_promotion):
        _write_raw(brain_root, obj)
    stale_second_promotion = _promotion_bundle(stale_term, reviewer="second")

    inputs = tuple(stale_second_promotion)
    request = _request(
        brain_root,
        inputs,
        operation=MutationOperation.PROMOTE,
        preconditions={
            stale_term["id"]: _object_hash(first_promotion[0]),
        },
        expected_corpus_fingerprint=corpus_fingerprint(
            BrainStore.load(brain_root)
        ),
    )
    result = MutationService().apply(inputs, request=request)

    assert result.error_code == "promotion_target_not_candidate"
    stored = BrainStore.load(brain_root)
    assert stored.get(stale_term["id"]) == first_promotion[0]
    assert stored.get(f"review.{stale_term['id']}")["reviewer"] == "first"


@pytest.mark.parametrize(
    "case",
    [
        "request_type",
        "operation",
        "brain_root_type",
        "brain_root_relative",
        "repo_context",
        "engine_sha",
        "request_objects_type",
        "request_object_item",
        "objects_string",
        "objects_exploding",
        "objects_item",
        "objects_mismatch",
        "delete_ids_type",
        "delete_id_item",
        "renames_type",
        "rename_item",
        "preconditions_type",
        "precondition_item",
        "expected_fingerprint",
        "canonical_intents_type",
        "canonical_intent_source",
        "canonical_field_changes_type",
        "canonical_change_pointer",
        "canonical_binding_shape",
    ],
)
def test_malformed_request_is_rejected_before_store_load(tmp_path, case):
    brain_root = tmp_path / "brain"
    broken = brain_root / "objects" / "domain" / "broken.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{", encoding="utf-8")
    request = _request(brain_root, ())
    objects = ()

    if case == "request_type":
        request = None
    elif case == "operation":
        request = replace(request, operation="ingest")
    elif case == "brain_root_type":
        request = replace(request, brain_root=str(brain_root))
    elif case == "brain_root_relative":
        request = replace(request, brain_root=Path("brain"))
    elif case == "repo_context":
        request = replace(request, repo_context={"repo_root": tmp_path})
    elif case == "engine_sha":
        request = replace(request, engine_sha="engine-sha")
    elif case == "request_objects_type":
        request = replace(request, objects=[])
    elif case == "request_object_item":
        request = replace(request, objects=("not-an-object",))
    elif case == "objects_string":
        objects = "not-an-object-sequence"
    elif case == "objects_exploding":
        objects = _ExplodingSequence()
    elif case == "objects_item":
        objects = ("not-an-object",)
    elif case == "objects_mismatch":
        request = replace(request, objects=(context(),))
    elif case == "delete_ids_type":
        request = replace(request, delete_ids=[])
    elif case == "delete_id_item":
        request = replace(request, delete_ids=(7,))
    elif case == "renames_type":
        request = replace(request, renames=[])
    elif case == "rename_item":
        request = replace(request, renames={"context.neutral": 7})
    elif case == "preconditions_type":
        request = replace(request, preconditions=[])
    elif case == "precondition_item":
        request = replace(request, preconditions={"context.neutral": 7})
    elif case == "expected_fingerprint":
        request = replace(request, expected_corpus_fingerprint="")
    elif case == "canonical_intents_type":
        request = replace(request, canonical_repair_intents=[])
    elif case == "canonical_intent_source":
        intent = mutation.CanonicalRepairIntent(7, "new", "reason", ())
        request = replace(request, canonical_repair_intents=(intent,))
    elif case == "canonical_field_changes_type":
        intent = mutation.CanonicalRepairIntent("old", "new", "reason", [])
        request = replace(request, canonical_repair_intents=(intent,))
    elif case == "canonical_change_pointer":
        change = mutation.CanonicalFieldChange(7, "before", "after")
        intent = mutation.CanonicalRepairIntent(
            "old", "new", "reason", (change,)
        )
        request = replace(request, canonical_repair_intents=(intent,))
    elif case == "canonical_binding_shape":
        request = replace(
            request,
            canonical_repair_binding={"decision_ledger_sha256": "a" * 64},
        )

    result = MutationService().plan(objects, request=request)

    assert result.error_code == "request_invalid"
    assert result.manifest is None


def test_canonical_repair_allows_id_and_matching_mapping_key(tmp_path):
    request = _mapping_repair_request(tmp_path)

    result = MutationService().plan(request.objects, request=request)

    assert result.ok is True
    assert result.manifest.renames[0]["old_id"] == request.delete_ids[0]
    assert (
        result.manifest.canonical_repair_binding
        == _canonical_repair_binding()
    )


@pytest.mark.parametrize("field", ["title", "meaning", "status"])
def test_canonical_repair_rejects_unlisted_mapping_change(tmp_path, field):
    request = _mapping_repair_request(tmp_path, tamper_field=field)

    result = MutationService().plan(request.objects, request=request)

    assert result.error_code == "canonical_repair_payload_changed"


@pytest.mark.parametrize("mismatch", ["after", "before"])
def test_canonical_repair_rejects_mapping_change_mismatch(tmp_path, mismatch):
    request = _mapping_repair_request(tmp_path)
    intent = request.canonical_repair_intents[0]
    change = intent.field_changes[0]
    if mismatch == "after":
        changed = mutation.CanonicalFieldChange(
            change.pointer,
            change.before,
            "other",
        )
    else:
        changed = mutation.CanonicalFieldChange(
            change.pointer,
            "other",
            change.after,
        )
    request = replace(
        request,
        canonical_repair_intents=(
            replace(intent, field_changes=(changed,)),
        ),
    )

    result = MutationService().plan(request.objects, request=request)

    assert result.error_code == "canonical_repair_payload_changed"


def test_canonical_repair_rejects_mapping_key_that_differs_from_new_id(tmp_path):
    request = _mapping_repair_request(tmp_path)
    new = dict(request.objects[0])
    new["mapping_key"] = "other"
    intent = request.canonical_repair_intents[0]
    change = replace(intent.field_changes[0], after="other")
    request = replace(
        request,
        objects=(new,),
        canonical_repair_intents=(
            replace(intent, field_changes=(change,)),
        ),
    )

    result = MutationService().plan(request.objects, request=request)

    assert result.error_code == "canonical_repair_payload_changed"


@pytest.mark.parametrize("duplicate", ["source", "target"])
def test_canonical_repair_rejects_duplicate_intent_endpoint(tmp_path, duplicate):
    request = _mapping_repair_request(tmp_path)
    first = request.canonical_repair_intents[0]
    second = first
    if duplicate == "target":
        second_old = candidate_mapping(
            "mapping.neutral.Second",
            glossary_term_ids=["g.neutral.term"],
            mapping_key="Second",
        )
        _write_raw(request.brain_root, second_old)
        second = replace(first, source_id=second_old["id"])
        request = replace(
            request,
            delete_ids=request.delete_ids + (second_old["id"],),
            renames={
                **request.renames,
                second_old["id"]: first.new_id,
            },
        )
    request = replace(
        request,
        canonical_repair_intents=(first, second),
    )

    result = MutationService().plan(request.objects, request=request)

    assert result.error_code == "canonical_repair_intent_duplicate"


@pytest.mark.parametrize("case", ["existing_target", "delete_only"])
def test_canonical_repair_rejects_merge_or_delete_only(tmp_path, case):
    request = _mapping_repair_request(tmp_path)
    if case == "existing_target":
        _write_raw(request.brain_root, request.objects[0])
    else:
        extra = candidate_term("g.neutral.extra")
        _write_raw(request.brain_root, extra)
        request = replace(
            request,
            delete_ids=request.delete_ids + (extra["id"],),
        )

    result = MutationService().plan(request.objects, request=request)

    assert result.ok is False
    assert result.manifest is None


def test_canonical_repair_allows_review_target_cleanup_only(tmp_path):
    request = _mixed_review_repair_request(tmp_path)

    result = MutationService().plan(request.objects, request=request)

    assert result.ok is True


@pytest.mark.parametrize(
    "absent_target_id",
    [
        "mapping.neutral.absent",
        "g.neutral.absent",
    ],
)
def test_canonical_repair_rejects_absent_mixed_review_target(
    tmp_path,
    absent_target_id,
):
    request = _mixed_review_repair_request(
        tmp_path,
        cleanup_target_id=absent_target_id,
    )

    result = MutationService().plan(request.objects, request=request)

    assert result.error_code == "canonical_repair_payload_changed"


def test_canonical_repair_rejects_mapping_shaped_non_mapping_cleanup(tmp_path):
    target_id = "mapping.neutral.not-a-domain-mapping"
    request = _mixed_review_repair_request(
        tmp_path,
        cleanup_target_id=target_id,
    )
    _write_raw(request.brain_root, candidate_term(target_id))

    result = MutationService().plan(request.objects, request=request)

    assert result.error_code == "canonical_repair_payload_changed"


def test_canonical_repair_rejects_mismatched_source_bundle_identity(tmp_path):
    request = _mixed_review_repair_request(
        tmp_path,
        source_review_id="review.bundle.other.wrong",
    )

    result = MutationService().plan(request.objects, request=request)

    assert result.error_code == "canonical_repair_payload_changed"


def test_canonical_repair_rejects_single_record_new_review_id(tmp_path):
    request = _mixed_review_repair_request(tmp_path)
    mapping, review = request.objects
    single_review_id = f"review.{mapping['id']}"
    single_review = dict(review)
    single_review["id"] = single_review_id
    mapping_intent, review_intent = request.canonical_repair_intents
    request = replace(
        request,
        objects=(mapping, single_review),
        renames={
            mapping_intent.source_id: mapping_intent.new_id,
            review_intent.source_id: single_review_id,
        },
        canonical_repair_intents=(
            mapping_intent,
            replace(review_intent, new_id=single_review_id),
        ),
    )

    result = MutationService().plan(request.objects, request=request)

    assert result.error_code == "canonical_repair_payload_changed"


@pytest.mark.parametrize(
    "tamper",
    [
        "add_target",
        "drop_mapping",
        "change_scope",
        "change_bundle_key",
        "replace_target",
        "reorder",
    ],
)
def test_canonical_repair_rejects_unapproved_review_shape(tmp_path, tamper):
    request = _mixed_review_repair_request(tmp_path, tamper=tamper)

    result = MutationService().plan(request.objects, request=request)

    assert result.error_code == "canonical_repair_payload_changed"


def test_canonical_repair_rejects_unknown_reason_code(tmp_path):
    request = _mapping_repair_request(tmp_path)
    intent = replace(
        request.canonical_repair_intents[0],
        reason_code="semantic_repair",
    )
    request = replace(request, canonical_repair_intents=(intent,))

    result = MutationService().plan(request.objects, request=request)

    assert result.error_code == "canonical_repair_reason_invalid"


def test_canonical_repair_grandfathers_reference_only_invalid_object(tmp_path):
    request = _mapping_repair_request(tmp_path)
    old_mapping_id = request.delete_ids[0]
    new_mapping_id = request.objects[0]["id"]
    legacy_review = review_record_for(
        "review.disturb-boostedbomb.depth-config",
        old_mapping_id,
    )
    _write_raw(request.brain_root, legacy_review)
    rewritten_review = dict(legacy_review)
    rewritten_review["target_object_id"] = new_mapping_id
    request = replace(
        request,
        objects=request.objects + (rewritten_review,),
    )

    result = MutationService().plan(request.objects, request=request)

    assert result.ok is True
    assert result.manifest.grandfathered_problems_after
    before_keys = {
        (item["object_id"], item["problem"], item["object_hash"])
        for item in result.manifest.grandfathered_problems_before
    }
    after_keys = {
        (item["object_id"], item["problem"], item["object_hash"])
        for item in result.manifest.grandfathered_problems_after
    }
    assert after_keys <= before_keys


def test_context_replace_explicit_rename_is_a_real_manifest_action(tmp_path):
    brain_root = tmp_path / "brain"
    old = candidate_term("g.neutral.old", term="이전")
    ctx = context(glossary_term_ids=[old["id"]])
    _write_raw(brain_root, ctx)
    _write_raw(brain_root, old)

    new = candidate_term("g.neutral.new", term="새 값")
    rewritten_context = dict(ctx)
    rewritten_context["glossary_term_ids"] = [new["id"]]
    result = _plan(
        brain_root,
        [new, rewritten_context],
        operation=MutationOperation.CONTEXT_REPLACE,
        delete_ids=(old["id"],),
        renames={old["id"]: new["id"]},
    )

    assert result.ok is True
    assert result.manifest.creates == ()
    assert result.manifest.deletes == ()
    assert result.manifest.renames == ({
        "old_id": old["id"],
        "new_id": new["id"],
        "old_path": (
            "objects/domain/g.neutral.old.json"
        ),
        "new_path": (
            "objects/domain/g.neutral.new.json"
        ),
        "before_sha256": _object_hash(old),
        "after_sha256": _object_hash(new),
    },)
    assert {
        (
            rewrite["object_id"],
            rewrite["pointer"],
            rewrite["before_id"],
            rewrite["after_id"],
        )
        for rewrite in result.manifest.reference_rewrites
    } == {
        (
            ctx["id"],
            "/glossary_term_ids/0",
            old["id"],
            new["id"],
        ),
    }


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("wrong_operation", "explicit_rename_operation_invalid"),
        ("old_not_deleted", "explicit_rename_old_not_deleted"),
        ("old_missing", "explicit_rename_old_missing"),
        ("new_missing", "explicit_rename_new_missing"),
        ("new_existing", "explicit_rename_new_not_create"),
        ("duplicate_target", "explicit_rename_target_duplicate"),
    ],
)
def test_explicit_rename_contract_fails_closed(tmp_path, case, expected_code):
    brain_root = tmp_path / "brain"
    old = candidate_term("g.neutral.old", term="이전")
    second_old = candidate_term("g.neutral.second-old", term="두 번째")
    existing_new = candidate_term("g.neutral.existing", term="기존")
    for obj in (context(), old, second_old, existing_new):
        _write_raw(brain_root, obj)

    new = candidate_term("g.neutral.new", term="새 값")
    operation = MutationOperation.CONTEXT_REPLACE
    delete_ids = (old["id"],)
    objects = [new]
    renames = {old["id"]: new["id"]}
    if case == "wrong_operation":
        operation = MutationOperation.INGEST
    elif case == "old_not_deleted":
        delete_ids = ()
    elif case == "old_missing":
        missing = "g.neutral.missing"
        delete_ids = (missing,)
        renames = {missing: new["id"]}
    elif case == "new_missing":
        objects = []
    elif case == "new_existing":
        objects = [existing_new]
        renames = {old["id"]: existing_new["id"]}
    elif case == "duplicate_target":
        delete_ids = (old["id"], second_old["id"])
        renames = {
            old["id"]: new["id"],
            second_old["id"]: new["id"],
        }

    result = _plan(
        brain_root,
        objects,
        operation=operation,
        delete_ids=delete_ids,
        renames=renames,
    )

    assert result.error_code == expected_code


def test_duplicate_full_id_is_rejected_before_dict_fold_and_schema(tmp_path):
    first = context()
    second = dict(first)
    second.pop("status")

    result = _plan(tmp_path / "brain", [first, second])

    assert result.error_code == "duplicate_object_id"


def test_malformed_non_string_ids_reach_validation_instead_of_duplicate_fold(tmp_path):
    first = context()
    first["id"] = []
    second = context("context.other")
    second["context_key"] = "other"
    second["id"] = []

    result = _plan(tmp_path / "brain", [first, second])

    assert result.error_code == "new_or_modified_lint_problem"


def test_missing_id_is_a_schema_failure_instead_of_an_exception(tmp_path):
    obj = context()
    obj.pop("id")

    result = _plan(tmp_path / "brain", [obj])

    assert result.error_code == "schema_invalid"


def test_unhashable_kind_is_a_schema_failure_instead_of_an_exception(tmp_path):
    obj = context()
    obj["kind"] = []

    result = _plan(tmp_path / "brain", [obj])

    assert result.error_code == "schema_invalid"


def test_duplicate_logical_key_is_rejected_before_schema_and_id(tmp_path):
    first = candidate_mapping(
        "mapping.neutral.one",
        glossary_term_ids=[],
        mapping_key="same",
    )
    second = candidate_mapping(
        "mapping.neutral.two",
        glossary_term_ids=[],
        mapping_key="same",
    )
    second.pop("status")

    result = _plan(tmp_path / "brain", [first, second])

    assert result.error_code == "duplicate_logical_key"


def test_duplicate_source_id_is_rejected_before_schema(tmp_path):
    first = context()
    first["source_id"] = "source-1"
    second = context("context.other")
    second["context_key"] = "other"
    second["source_id"] = "source-1"
    second.pop("status")

    result = _plan(tmp_path / "brain", [first, second])

    assert result.error_code == "duplicate_source_id"


def test_schema_is_rejected_before_invalid_id(tmp_path):
    obj = _legacy_invalid_context()
    obj.pop("status")

    result = _plan(tmp_path / "brain", [obj])

    assert result.error_code == "schema_invalid"


def test_invalid_id_is_rejected_before_missing_quote(tmp_path):
    locator = _code_locator(object_id="code.Legacy", quote=None)

    result = _plan(tmp_path / "brain", [locator])

    assert result.error_code == "new_or_modified_lint_problem"


def test_status_transition_is_rejected_before_repo_verification(tmp_path):
    brain_root = tmp_path / "brain"
    locator = _code_locator(quote=None)
    _write_raw(brain_root, locator)
    replacement = dict(locator)
    replacement["status"] = "candidate"
    replacement["path"] = "Missing.cpp"

    result = _plan(brain_root, [replacement])

    assert result.error_code == "status_transition_invalid"


def test_missing_precondition_target_is_rejected_before_merged_lint(tmp_path):
    brain_root = tmp_path / "brain"
    broken = context(glossary_term_ids=["g.neutral.missing"])
    _write_raw(brain_root, broken)

    result = _plan(
        brain_root,
        [candidate_term()],
        preconditions={"g.neutral.gone": "0" * 64},
    )

    assert result.error_code == "precondition_target_missing"


def test_precondition_hash_mismatch_is_rejected(tmp_path):
    brain_root = tmp_path / "brain"
    existing = context()
    _write_raw(brain_root, existing)
    replacement = dict(existing)
    replacement["title"] = "changed"

    result = _plan(
        brain_root,
        [replacement],
        preconditions={existing["id"]: "0" * 64},
    )

    assert result.error_code == "precondition_hash_mismatch"


def test_new_locator_is_verified_and_external_time_and_title_are_ignored(tmp_path):
    repo_context, sha = _git_repo(tmp_path)
    locator = _code_locator(commit_sha=sha)

    result = _plan(
        tmp_path / "brain",
        [locator],
        repo_context=repo_context,
    )

    assert result.ok is True
    assert result.after["verified_at"] != locator["verified_at"]
    assert result.after["title"] == "Foo::bar"
    assert result.after["verified_quote"] == "void Foo::bar() {}"


def test_new_locator_without_verified_at_reaches_verifier_and_gets_engine_time(
    tmp_path,
):
    repo_context, sha = _git_repo(tmp_path)
    locator = _code_locator(commit_sha=sha, verified_at=None)

    result = _plan(
        tmp_path / "brain",
        [locator],
        repo_context=repo_context,
    )

    assert result.ok is True
    assert "verified_at" not in locator
    assert isinstance(result.after["verified_at"], str)
    assert result.after["verified_at"]


def test_unverified_locator_missing_quote_fails_at_quote_gate_not_schema(tmp_path):
    locator = _code_locator(quote=None, verified_at=None)

    result = _plan(tmp_path / "brain", [locator])

    assert result.error_code == "quote_required"


def test_coordinate_changed_locator_is_reverified(tmp_path):
    repo_context, sha = _git_repo(tmp_path)
    brain_root = tmp_path / "brain"
    existing = _code_locator(
        commit_sha=sha,
        title="Foo::bar",
        verified_at=T,
    )
    _write_raw(brain_root, existing)
    replacement = dict(existing)
    replacement["verified_quote"] = "not in blob"

    result = _plan(
        brain_root,
        [replacement],
        repo_context=repo_context,
    )

    assert result.error_code == "quote_not_found"


def test_unchanged_ingest_locator_preserves_engine_fields(tmp_path):
    brain_root = tmp_path / "brain"
    existing = _code_locator(
        quote=None,
        title="legacy display",
        verified_at=T,
    )
    _write_raw(brain_root, existing)
    replacement = dict(existing)
    replacement["verified_at"] = "2099-01-01T00:00:00Z"
    replacement["title"] = "external rewrite"

    result = _plan(
        brain_root,
        [replacement],
        operation=MutationOperation.INGEST,
    )

    assert result.ok is True
    assert result.after["verified_at"] == T
    assert result.after["title"] == "legacy display"


def test_legacy_id_only_is_the_only_no_quote_exception(tmp_path):
    repo_context, sha = _git_repo(tmp_path)
    normal = _code_locator(commit_sha=sha, quote=None)
    normal_result = _plan(
        tmp_path / "normal-brain",
        [normal],
        repo_context=repo_context,
    )
    assert normal_result.error_code == "quote_required"

    brain_root = tmp_path / "migration-brain"
    old = _code_locator(
        object_id="code.Legacy",
        commit_sha=sha,
        quote=None,
        title="legacy display",
    )
    _write_raw(brain_root, old)
    new = dict(old)
    new["id"] = "code.neutral.legacy"
    id_only_result = _plan(
        brain_root,
        [new],
        operation=MutationOperation.ID_ONLY_MIGRATION,
        delete_ids=(old["id"],),
        preconditions={old["id"]: _object_hash(old)},
    )

    assert id_only_result.ok is True
    assert id_only_result.after["verified_at"] == old["verified_at"]
    assert id_only_result.after["title"] == old["title"]
    assert len(id_only_result.manifest.renames) == 1


def test_id_only_migration_allows_only_id_and_registered_reference_changes(tmp_path):
    brain_root = tmp_path / "brain"
    old_locator = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy display",
    )
    old_review = review_record_for("review.code.Legacy", "code.Legacy")
    _write_raw(brain_root, old_locator)
    _write_raw(brain_root, old_review)

    new_locator = dict(old_locator)
    new_locator["id"] = "code.neutral.legacy"
    new_review = dict(old_review)
    new_review["id"] = "review.code.neutral.legacy"
    new_review["target_object_id"] = new_locator["id"]

    result = _plan(
        brain_root,
        [new_locator, new_review],
        operation=MutationOperation.ID_ONLY_MIGRATION,
        delete_ids=(old_locator["id"], old_review["id"]),
    )

    assert result.ok is True
    assert {
        (rewrite["pointer"], rewrite["before_id"], rewrite["after_id"])
        for rewrite in result.manifest.reference_rewrites
    } == {
        (
            "/target_object_id",
            old_locator["id"],
            new_locator["id"],
        ),
    }


@pytest.mark.parametrize("review_scope", ["absent", "single_object"])
def test_target_derived_single_review_rename_accepts_current_valid_single_scope(
    review_scope,
):
    before = review_record_for("review.g.neutral.x", "g.neutral.x")
    after = review_record_for("review.g.other.x", "g.other.x")
    if review_scope == "single_object":
        before["review_scope"] = review_scope
        after["review_scope"] = review_scope

    assert mutation.is_target_derived_single_review_rename(
        before,
        after,
        {
            "g.neutral.x": "g.other.x",
            "review.g.neutral.x": "review.g.other.x",
        },
    ) is True


@pytest.mark.parametrize(
    "tamper",
    [
        "scope",
        "identity",
        "independent_self_id",
        "target_not_renamed",
        "payload",
        "bundle",
    ],
)
def test_target_derived_single_review_rename_rejects_non_exact_closure(tamper):
    before = review_record_for("review.g.neutral.x", "g.neutral.x")
    after = review_record_for("review.g.other.x", "g.other.x")
    replacements = {
        "g.neutral.x": "g.other.x",
        "review.g.neutral.x": "review.g.other.x",
    }
    if tamper == "scope":
        before["review_scope"] = None
    elif tamper == "identity":
        after = dict(before)
        replacements = {
            "g.neutral.x": "g.neutral.x",
            "review.g.neutral.x": "review.g.neutral.x",
        }
    elif tamper == "independent_self_id":
        after["id"] = "review.g.neutral.other"
    elif tamper == "target_not_renamed":
        del replacements["g.neutral.x"]
    elif tamper == "payload":
        after["title"] = "changed"
    elif tamper == "bundle":
        after["id"] = "review.bundle.other.review"
        after.pop("target_object_id")
        after.update({
            "review_scope": "mapping_bundle",
            "bundle_key": "bundle.other.review",
            "confirmation_key": "bundle.other.review",
            "target_object_ids": ["mapping.other.review"],
        })

    assert mutation.is_target_derived_single_review_rename(
        before,
        after,
        replacements,
    ) is False


def test_id_only_migration_rejects_non_identity_payload_change(tmp_path):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy display",
    )
    _write_raw(brain_root, old)
    changed = dict(old)
    changed["id"] = "code.neutral.legacy"
    changed["title"] = "semantic change"

    result = _plan(
        brain_root,
        [changed],
        operation=MutationOperation.ID_ONLY_MIGRATION,
        delete_ids=(old["id"],),
    )

    assert result.error_code == "id_only_payload_changed"


def test_id_only_plan_binds_existing_eval_update_to_exact_bytes(tmp_path):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy display",
    )
    _write_raw(brain_root, old)
    new = dict(old)
    new["id"] = "code.neutral.legacy"
    before = (
        b'{"scenarios":[{"id":"s","query":"q","expect":'
        b'{"top5_any":["code.Legacy"]}}]}\n'
    )
    after = (
        b'{"scenarios":[{"expect":{"top5_any":["code.neutral.legacy"]},'
        b'"id":"s","query":"q"}]}\n'
    )
    (brain_root / "eval_scenarios.json").write_bytes(before)
    update = _file_update("eval_scenarios.json", before, after)

    result = _plan(
        brain_root,
        [new],
        operation=MutationOperation.ID_ONLY_MIGRATION,
        delete_ids=(old["id"],),
        auxiliary_updates=(update,),
    )

    assert result.ok is True
    assert result.manifest.auxiliary_updates == ({
        "path": "eval_scenarios.json",
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": hashlib.sha256(after).hexdigest(),
    },)
    assert result.auxiliary_after_files == {
        "eval_scenarios.json": after,
    }


@pytest.mark.parametrize(
    ("operation", "path", "expected_error"),
    [
        (
            MutationOperation.INGEST,
            "eval_scenarios.json",
            "auxiliary_update_operation_invalid",
        ),
        (
            MutationOperation.ID_ONLY_MIGRATION,
            "other.json",
            "auxiliary_update_path_invalid",
        ),
        (
            MutationOperation.ID_ONLY_MIGRATION,
            "../eval_scenarios.json",
            "auxiliary_update_path_invalid",
        ),
        (
            MutationOperation.ID_ONLY_MIGRATION,
            "/eval_scenarios.json",
            "auxiliary_update_path_invalid",
        ),
    ],
)
def test_auxiliary_update_allowlist_fails_closed(
    tmp_path,
    operation,
    path,
    expected_error,
):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    before = b"{}\n"
    after = b'{"scenarios":[]}\n'
    (brain_root / "eval_scenarios.json").write_bytes(before)
    update = _file_update(path, before, after)

    result = _plan(
        brain_root,
        [],
        operation=operation,
        auxiliary_updates=(update,),
    )

    assert result.error_code == expected_error


def test_auxiliary_update_rejects_missing_before_file(tmp_path):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    update = _file_update(
        "eval_scenarios.json",
        b"{}\n",
        b'{"scenarios":[]}\n',
    )

    result = _plan(
        brain_root,
        [],
        operation=MutationOperation.ID_ONLY_MIGRATION,
        auxiliary_updates=(update,),
    )

    assert result.error_code == "auxiliary_update_missing"


def test_auxiliary_update_rejects_wrong_hashes_and_duplicate_path(tmp_path):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    before = b"{}\n"
    after = b'{"scenarios":[]}\n'
    (brain_root / "eval_scenarios.json").write_bytes(before)
    valid = _file_update("eval_scenarios.json", before, after)
    wrong_before = replace(valid, before_sha256="0" * 64)
    wrong_after = replace(valid, after_sha256="0" * 64)

    assert _plan(
        brain_root,
        [],
        operation=MutationOperation.ID_ONLY_MIGRATION,
        auxiliary_updates=(wrong_before,),
    ).error_code == "auxiliary_before_hash_mismatch"
    assert _plan(
        brain_root,
        [],
        operation=MutationOperation.ID_ONLY_MIGRATION,
        auxiliary_updates=(wrong_after,),
    ).error_code == "auxiliary_after_hash_mismatch"
    assert _plan(
        brain_root,
        [],
        operation=MutationOperation.ID_ONLY_MIGRATION,
        auxiliary_updates=(valid, valid),
    ).error_code == "duplicate_auxiliary_update"


def test_auxiliary_update_rejects_noop_before_transaction_or_invalidation(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    unchanged = b'{"scenarios":[]}\n'
    (brain_root / "eval_scenarios.json").write_bytes(unchanged)
    local = brain_root / ".brain-local"
    local.mkdir()
    (local / "index.db").write_bytes(b"index")
    (local / "stale-set.json").write_bytes(b'{"stale":[]}\n')
    update = _file_update("eval_scenarios.json", unchanged, unchanged)
    request = _request(
        brain_root,
        (),
        operation=MutationOperation.ID_ONLY_MIGRATION,
        auxiliary_updates=(update,),
    )

    result = MutationService().apply((), request=request)

    assert result.error_code == "auxiliary_update_noop"
    assert (local / "index.db").read_bytes() == b"index"
    assert (local / "stale-set.json").read_bytes() == b'{"stale":[]}\n'
    assert not (local / "transactions").exists()
    assert not (local / "preparing-transactions").exists()


@pytest.mark.parametrize(
    ("entry_kind", "expected_error"),
    [
        ("symlink", "symlink_forbidden"),
        ("directory", "file_type_invalid"),
    ],
)
def test_auxiliary_update_rejects_unsafe_existing_eval_entry(
    tmp_path,
    entry_kind,
    expected_error,
):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    eval_path = brain_root / "eval_scenarios.json"
    if entry_kind == "symlink":
        target = tmp_path / "outside.json"
        target.write_bytes(b"{}\n")
        eval_path.symlink_to(target)
    else:
        eval_path.mkdir()
    update = _file_update(
        "eval_scenarios.json",
        b"{}\n",
        b'{"scenarios":[]}\n',
    )

    result = _plan(
        brain_root,
        [],
        operation=MutationOperation.ID_ONLY_MIGRATION,
        auxiliary_updates=(update,),
    )

    assert result.error_code == expected_error


def test_auxiliary_update_rejects_cross_device_entry(tmp_path, monkeypatch):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    before = b"{}\n"
    after = b'{"scenarios":[]}\n'
    (brain_root / "eval_scenarios.json").write_bytes(before)
    update = _file_update("eval_scenarios.json", before, after)
    original = __import__(
        "project_brain.corpus_io",
        fromlist=["_observed_device"],
    )._observed_device

    def cross_device(relative_path, actual_device):
        if relative_path == "eval_scenarios.json":
            return actual_device + 1
        return original(relative_path, actual_device)

    monkeypatch.setattr(
        "project_brain.corpus_io._observed_device",
        cross_device,
    )

    result = _plan(
        brain_root,
        [],
        operation=MutationOperation.ID_ONLY_MIGRATION,
        auxiliary_updates=(update,),
    )

    assert result.error_code == "filesystem_mismatch"


def test_id_only_no_quote_rename_requires_old_invalid_id(tmp_path):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.neutral.old",
        quote=None,
        title="legacy display",
    )
    _write_raw(brain_root, old)
    new = dict(old)
    new["id"] = "code.neutral.new"

    result = _plan(
        brain_root,
        [new],
        operation=MutationOperation.ID_ONLY_MIGRATION,
        delete_ids=(old["id"],),
    )

    assert result.error_code == "id_only_legacy_source_not_invalid"


def test_legacy_locator_without_symbol_uses_deterministic_display_fallback(tmp_path):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.neutral.legacy",
        quote=None,
        title="untrusted",
    )
    old.pop("symbol")
    _write_raw(brain_root, old)

    result = _plan(
        brain_root,
        [old],
        operation=MutationOperation.DISPLAY_MIGRATION,
    )

    assert result.ok is True
    assert result.after["title"] == "Foo.cpp:legacy"


def test_unchanged_preexisting_id_problem_is_temporarily_grandfathered(tmp_path):
    brain_root = tmp_path / "brain"
    legacy = _legacy_invalid_context()
    _write_raw(brain_root, legacy)

    result = _plan(brain_root, [context()])

    assert result.ok is True
    assert (
        result.manifest.grandfathered_problems_after
        <= result.manifest.grandfathered_problems_before
    )
    assert len(result.manifest.grandfathered_problems_after) == 1
    problem = result.manifest.grandfathered_problems_after[0]
    assert problem["object_id"] == legacy["id"]
    assert isinstance(problem["problem"], str) and problem["problem"]
    assert problem["object_hash"] == _problem_object_hash(legacy)


@pytest.mark.parametrize("mode", ["changed", "new"])
def test_changed_or_new_invalid_id_is_rejected(tmp_path, mode):
    brain_root = tmp_path / "brain"
    invalid = _legacy_invalid_context()
    if mode == "changed":
        _write_raw(brain_root, invalid)
        invalid = _legacy_invalid_context(title="changed")

    result = _plan(brain_root, [invalid])

    assert result.error_code == "new_or_modified_lint_problem"


def test_unchanged_invalid_id_uses_stable_json_not_key_insertion_order(tmp_path):
    brain_root = tmp_path / "brain"
    invalid = _legacy_invalid_context()
    _write_raw(brain_root, invalid)
    reordered = dict(reversed(tuple(invalid.items())))

    result = _plan(brain_root, [reordered])

    assert result.ok is True
    assert result.manifest.grandfathered_problems_after


def test_unchanged_unknown_grammar_is_grandfathered_with_exact_problem_binding(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    legacy = _legacy_unknown_review()
    _write_raw(brain_root, context())
    _write_raw(brain_root, legacy)

    result = _plan(brain_root, [])

    assert result.ok is True
    assert result.manifest.grandfathered_problems_before == (
        {
            "object_id": legacy["id"],
            "problem": (
                "review.disturb-boostedbomb.depth-config: invalid id for "
                "ReviewRecord: unknown ID prefix 'disturb-boostedbomb'"
            ),
            "object_hash": _problem_object_hash(legacy),
        },
    )
    assert (
        result.manifest.grandfathered_problems_after
        == result.manifest.grandfathered_problems_before
    )


def test_unchanged_unknown_grammar_uses_stable_json_not_key_insertion_order(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    legacy = _legacy_unknown_review()
    _write_raw(brain_root, context())
    _write_raw(brain_root, legacy)
    reordered = dict(reversed(tuple(legacy.items())))

    result = _plan(brain_root, [reordered])

    assert result.ok is True
    assert result.manifest.grandfathered_problems_after


@pytest.mark.parametrize("change", ["payload", "new"])
def test_changed_or_new_unknown_grammar_is_rejected(tmp_path, change):
    brain_root = tmp_path / "brain"
    legacy = _legacy_unknown_review()
    _write_raw(brain_root, context())
    _write_raw(brain_root, legacy)
    candidate = dict(legacy)
    if change == "payload":
        candidate["title"] = "changed"
    else:
        candidate["id"] = "review.disturb-hedgehog.cloud-fix"

    result = _plan(brain_root, [candidate])

    assert result.error_code == "new_or_modified_lint_problem"


def test_unknown_grammar_with_changed_problem_list_is_rejected(tmp_path):
    brain_root = tmp_path / "brain"
    before = review_record_for(
        "review.context.neutral",
        "mystery.neutral",
    )
    after = dict(before)
    after["target_object_id"] = "mystery.other"
    before_errors = [
        "review.context.neutral: invalid id fields: target_object_id "
        "'mystery.neutral' does not match ID target 'context.neutral'",
    ]
    after_errors = [
        "review.context.neutral: invalid id fields: target_object_id "
        "'mystery.other' does not match ID target 'context.neutral'",
    ]

    assert validate_object_id(before) == before_errors
    assert validate_object_id(after) == after_errors
    assert before_errors != after_errors
    _write_raw(brain_root, before)

    result = _plan(brain_root, [after])

    assert result.error_code == "new_or_modified_lint_problem"


def test_unknown_grammar_does_not_grandfather_an_existing_non_id_problem(tmp_path):
    brain_root = tmp_path / "brain"
    _write_raw(brain_root, context())
    _write_raw(brain_root, _legacy_unknown_review())
    _write_raw(
        brain_root,
        context("context.broken", glossary_term_ids=["g.neutral.missing"]),
    )

    result = _plan(brain_root, [])

    assert result.error_code == "dangling_reference"


def test_id_migration_completion_gate_rejects_remaining_unknown_grammar(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    _write_raw(brain_root, context())
    _write_raw(brain_root, _legacy_unknown_review())

    result = _plan(
        brain_root,
        [],
        operation=MutationOperation.ID_ONLY_MIGRATION,
    )

    assert result.error_code == "grandfathered_problems_remaining"


def test_existing_non_id_lint_problem_is_never_grandfathered(tmp_path):
    brain_root = tmp_path / "brain"
    broken = context(glossary_term_ids=["g.neutral.missing"])
    _write_raw(brain_root, broken)

    result = _plan(brain_root, [])

    assert result.error_code == "dangling_reference"


def test_id_migration_completion_gate_requires_zero_grandfathered_problems(tmp_path):
    brain_root = tmp_path / "brain"
    _write_raw(brain_root, _legacy_invalid_context())

    result = _plan(
        brain_root,
        [],
        operation=MutationOperation.ID_ONLY_MIGRATION,
    )

    assert result.error_code == "grandfathered_problems_remaining"


def test_merged_references_are_checked_before_merged_lint(tmp_path):
    brain_root = tmp_path / "brain"
    ctx = context(glossary_term_ids=["g.neutral.x"])
    term = candidate_term()
    _write_raw(brain_root, ctx)
    _write_raw(brain_root, term)

    result = _plan(brain_root, [], delete_ids=(term["id"],))

    assert result.error_code == "dangling_reference"


def test_lifecycle_failure_precedes_missing_delete_target(tmp_path):
    brain_root = tmp_path / "brain"
    existing = context()
    _write_raw(brain_root, existing)
    replacement = dict(existing)
    replacement["status"] = "candidate"

    result = _plan(
        brain_root,
        [replacement],
        delete_ids=("g.neutral.missing",),
    )

    assert result.error_code == "status_transition_invalid"


def test_manifest_is_deterministic_relative_and_hash_bound(tmp_path):
    brain_root = tmp_path / "brain"
    existing = context()
    _write_raw(brain_root, existing)
    replacement = dict(existing)
    replacement["title"] = "changed"
    new = candidate_term()

    first = _plan(
        brain_root,
        [replacement, new],
        preconditions={existing["id"]: _object_hash(existing)},
    )
    second = _plan(
        brain_root,
        [replacement, new],
        preconditions={existing["id"]: _object_hash(existing)},
    )

    assert first.ok is True
    assert first.manifest_bytes == second.manifest_bytes
    assert first.manifest_sha256 == hashlib.sha256(first.manifest_bytes).hexdigest()
    assert first.manifest_bytes.endswith(b"\n")
    assert not first.manifest_bytes.endswith(b"\n\n")
    decoded = json.loads(first.manifest_bytes)
    assert first.manifest_bytes == (
        json.dumps(
            decoded,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    assert first.manifest.updates[0] == {
        "object_id": existing["id"],
        "path": "objects/domain/context.neutral.json",
        "before_sha256": _object_hash(existing),
        "after_sha256": _object_hash(replacement),
    }
    assert first.manifest.creates[0]["path"] == "objects/domain/g.neutral.x.json"
    assert Path(first.manifest.creates[0]["path"]).is_absolute() is False
    assert BrainStore.load(brain_root).get(existing["id"])["title"] != "changed"


def test_reference_rewrites_are_recorded_with_exact_pointer(tmp_path):
    brain_root = tmp_path / "brain"
    old = context(glossary_term_ids=["g.neutral.old"])
    old_term = candidate_term("g.neutral.old")
    new_term = candidate_term("g.neutral.new")
    _write_raw(brain_root, old)
    _write_raw(brain_root, old_term)
    replacement = dict(old)
    replacement["glossary_term_ids"] = ["g.neutral.new"]

    result = _plan(
        brain_root,
        [replacement, new_term],
        delete_ids=(old_term["id"],),
    )

    assert result.ok is True
    assert result.manifest.reference_rewrites == (
        {
            "object_id": old["id"],
            "pointer": "/glossary_term_ids/0",
            "before_id": "g.neutral.old",
            "after_id": "g.neutral.new",
        },
    )


@pytest.mark.parametrize("same_payload", [True, False])
def test_existing_duplicate_payload_id_blocks_plan_without_manifest(
    tmp_path,
    same_payload,
):
    brain_root = tmp_path / "brain"
    first = context()
    second = dict(first)
    if not same_payload:
        second["title"] = "different"
    first_path = brain_root / "objects" / "domain" / "first.json"
    second_path = brain_root / "objects" / "domain" / "second.json"
    first_path.parent.mkdir(parents=True)
    first_path.write_bytes(BrainStore.object_bytes(first))
    second_path.write_bytes(BrainStore.object_bytes(second))

    result = _plan(brain_root, [])

    assert result.error_code == "duplicate_existing_object_id"
    assert result.manifest is None
    assert "first.json" in result.detail
    assert "second.json" in result.detail


def test_corrupt_tracked_object_json_returns_corpus_invalid(tmp_path):
    brain_root = tmp_path / "brain"
    path = brain_root / "objects" / "domain" / "broken.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")

    result = _plan(brain_root, [])

    assert result.error_code == "corpus_invalid"
    assert result.manifest is None
    assert "broken.json" in result.detail


def test_apply_corrupt_tracked_object_json_returns_corpus_invalid(tmp_path):
    brain_root = tmp_path / "brain"
    broken = brain_root / "objects" / "domain" / "broken.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("{", encoding="utf-8")
    request = _request(brain_root, ())

    result = MutationService().apply((), request=request)

    assert result.error_code == "corpus_invalid"
    assert not (brain_root / ".brain-local" / "transactions").exists()
    assert result.manifest is None
    assert "broken.json" in result.detail


def test_plan_fails_closed_when_changed_existing_object_has_no_source_receipt(
    tmp_path,
):
    existing = context()
    replacement = dict(existing)
    replacement["title"] = "requires source receipt"
    request = _request(tmp_path / "brain", (replacement,))

    result = MutationService().plan(
        request.objects,
        request=request,
        _existing_store=BrainStore({existing["id"]: existing}),
    )

    assert result.error_code == "source_receipt_missing"
    assert result.manifest is None


@pytest.mark.parametrize("source_sha256", ["not-a-sha", 7])
def test_plan_rejects_malformed_injected_source_receipt_before_manifest(
    tmp_path,
    source_sha256,
):
    existing = context()
    replacement = dict(existing)
    replacement["title"] = "requires valid source receipt"
    request = _request(tmp_path / "brain", (replacement,))

    result = MutationService().plan(
        request.objects,
        request=request,
        _existing_store=BrainStore(
            {existing["id"]: existing},
            source_sha256_by_id={existing["id"]: source_sha256},
        ),
    )

    assert result.error_code == "source_receipt_invalid"
    assert result.manifest is None
