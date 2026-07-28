from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Sequence
from dataclasses import fields, replace
from pathlib import Path

import pytest

from project_brain.mutation import (
    MutationManifest,
    MutationOperation,
    MutationRequest,
    MutationService,
)
from project_brain.objbase import base
from project_brain.hash_utils import stable_json
from project_brain.hash_utils import source_content_hash
from project_brain.repo_context import resolve_repo_context
from project_brain.store import BrainStore
from tests.test_ingest import (
    candidate_mapping,
    candidate_term,
    context,
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
    preconditions: dict[str, str] | None = None,
    expected_corpus_fingerprint: str | None = None,
) -> MutationRequest:
    return MutationRequest(
        operation=operation,
        brain_root=brain_root,
        repo_context=repo_context,
        engine_sha="e" * 40,
        objects=objects,
        delete_ids=delete_ids,
        preconditions=preconditions or {},
        expected_corpus_fingerprint=expected_corpus_fingerprint,
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


def _problem_object_hash(obj: dict) -> str:
    return hashlib.sha256(stable_json(obj).encode("utf-8")).hexdigest()


def _legacy_invalid_context(*, title: str = "legacy") -> dict:
    obj = context("context.Legacy")
    obj["context_key"] = "Legacy"
    obj["title"] = title
    return obj


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
        "preconditions",
        "expected_corpus_fingerprint",
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
        "before_fingerprint",
        "expected_after_fingerprint",
        "grandfathered_problems_before",
        "grandfathered_problems_after",
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
    }


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
        "preconditions_type",
        "precondition_item",
        "expected_fingerprint",
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
    elif case == "preconditions_type":
        request = replace(request, preconditions=[])
    elif case == "precondition_item":
        request = replace(request, preconditions={"context.neutral": 7})
    elif case == "expected_fingerprint":
        request = replace(request, expected_corpus_fingerprint="")

    result = MutationService().plan(objects, request=request)

    assert result.error_code == "request_invalid"
    assert result.manifest is None


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


def test_unchanged_locator_ignores_external_verified_at(tmp_path):
    brain_root = tmp_path / "brain"
    existing = _code_locator(
        quote=None,
        title="legacy display",
        verified_at=T,
    )
    _write_raw(brain_root, existing)
    replacement = dict(existing)
    replacement["verified_at"] = "2099-01-01T00:00:00Z"

    result = _plan(brain_root, [replacement])

    assert result.ok is True
    assert result.after["verified_at"] == T


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
