"""설치되는 객체 계약 JSON이 현재 엔진 관문과 함께 동작하는지 검증한다.

문서 예시를 별도 테스트 fixture로 복제하지 않는다. 이 파일은 사용자가 실제로 받는
``templates/ingest/references/object-templates`` 원본을 직접 실행한다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

from project_brain.assembly import build, validate_assembled_inputs, validate_notes
from project_brain.coverage import normalize_coverage, plan_expected_objects
from project_brain.context_projection import build_context_projection
from project_brain.lint import lint_store_report
from project_brain.mutation import (
    MutationOperation,
    MutationRequest,
    MutationService,
    corpus_fingerprint,
)
from project_brain.promote import promote
from project_brain.reference_fields import iter_object_refs
from project_brain.repo_context import resolve_repo_context
from project_brain.schema import (
    BASE_REQUIRED,
    KIND_REQUIRED,
    VALID_KINDS,
    validate_mutation_input_schema,
    validate_object,
    validate_object_id,
)
from project_brain.store import BrainStore
from project_brain.write_semantics import validate_write_semantics
from tests.coverage_helpers import direct_coverage


ROOT = Path(__file__).parents[1]
TEMPLATES = ROOT / "src/project_brain/templates/ingest/references/object-templates"
KINDS = TEMPLATES / "kinds"
INVALID = TEMPLATES / "invalid"
FIXED_TIME = "2026-06-04T00:00:00Z"


def _load_json(path: Path):
    assert path.is_file(), f"missing object-contract fixture: {path.relative_to(ROOT)}"
    return json.loads(path.read_text(encoding="utf-8"))


def _kind_name(path: Path) -> str:
    return path.name.removesuffix(".template.json")


def _fixture_objects(payload) -> list[dict]:
    if isinstance(payload, list):
        assert all(isinstance(item, dict) for item in payload)
        return deepcopy(payload)
    assert isinstance(payload, dict)
    if isinstance(payload.get("objects"), list):
        assert all(isinstance(item, dict) for item in payload["objects"])
        return deepcopy(payload["objects"])
    return [deepcopy(payload)]


def _base_objects(relative_files: list[str]) -> list[dict]:
    objects: list[dict] = []
    for relative in relative_files:
        objects.extend(_fixture_objects(_load_json(TEMPLATES / relative)))
    return objects


def _write_raw(brain_root: Path, obj: dict) -> None:
    path = BrainStore.object_path(brain_root, obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(BrainStore.object_bytes(obj))


def _mutation_plan(
    brain_root: Path,
    objects: list[dict],
    *,
    repo_context=None,
    operation: MutationOperation = MutationOperation.INGEST,
    preconditions: dict[str, str] | None = None,
    expected_corpus_fingerprint: str | None = None,
):
    brain_root.parent.mkdir(parents=True, exist_ok=True)
    inputs = tuple(objects)
    request = MutationRequest(
        operation=operation,
        brain_root=brain_root,
        repo_context=repo_context,
        engine_sha="e" * 40,
        objects=inputs,
        preconditions=preconditions or {},
        expected_corpus_fingerprint=expected_corpus_fingerprint,
        coverage=(
            direct_coverage(*inputs)
            if operation is MutationOperation.INGEST
            else None
        ),
    )
    return MutationService().plan(inputs, request=request)


def _object_hash(obj: dict) -> str:
    return hashlib.sha256(BrainStore.object_bytes(obj)).hexdigest()


def _git_repo(parent: Path):
    repo = parent / "repo"
    repo.mkdir(parents=True)
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
    context = resolve_repo_context(
        repo.resolve(),
        expected_repo_id="demoapp",
        configured_repo_id="demoapp",
        expected_revision_ref=sha,
    )
    return context, sha


def _core_graph_objects() -> list[dict]:
    payload = _load_json(TEMPLATES / "object-graph.complete.template.json")
    assert set(payload) == {"schema_version", "name", "objects"}
    assert payload["schema_version"] == 1
    assert payload["name"] == "core-ingest-graph"
    assert isinstance(payload["objects"], list) and payload["objects"]
    return deepcopy(payload["objects"])


def test_kind_template_file_set_exactly_matches_schema():
    actual = {_kind_name(path) for path in KINDS.glob("*.template.json")}
    assert actual == VALID_KINDS


def test_each_kind_template_has_required_keys_valid_shape_id_and_no_placeholder():
    paths = sorted(KINDS.glob("*.template.json"))
    assert paths
    for path in paths:
        text = path.read_text(encoding="utf-8")
        obj = json.loads(text)
        kind = _kind_name(path)
        assert obj["kind"] == kind
        assert set(obj) >= (set(BASE_REQUIRED) | set(KIND_REQUIRED[kind]))
        assert "{{" not in text and "}}" not in text
        assert validate_object(obj) == [], path.name
        assert validate_object_id(obj) == [], path.name
        assert validate_write_semantics(
            before_by_id={},
            after_by_id={obj["id"]: obj},
            source_id_by_after_id={},
        ).errors == (), path.name


def test_coverage_templates_bind_both_modes_to_canonical_object_identities():
    assembled_raw = _load_json(
        TEMPLATES / "build-coverage.complete.template.json"
    )
    direct_raw = _load_json(TEMPLATES / "direct-coverage.template.json")
    assembled = normalize_coverage(assembled_raw)
    direct = normalize_coverage(direct_raw)

    assert assembled.mode == "assembled"
    assert direct.mode == "direct"
    assert assembled.contract == assembled_raw
    assert direct.contract == direct_raw

    notes = _load_json(TEMPLATES / "build-notes.complete.template.json")
    verify_data = {"groups": [{"group": "build-contract"}]}
    seed = BrainStore({obj["id"]: obj for obj in _core_graph_objects()})
    validate_assembled_inputs(
        binding=assembled,
        verify_data=verify_data,
        notes=notes,
        store=seed,
    )
    assert plan_expected_objects(assembled, seed) == assembled.expected_objects
    assert [(item.id, item.kind) for item in direct.expected_objects] == [
        ("mapping.ctx.behavior", "DomainMapping")
    ]


def test_code_locator_template_passes_official_write_gate_and_links_code_edges(
    tmp_path,
):
    repo_context, sha = _git_repo(tmp_path)
    locator = _load_json(KINDS / "CodeLocator.template.json")
    locator.update(
        {
            "repo": "demoapp",
            "path": "Foo.cpp",
            "symbol": "Foo::bar",
            "commit_sha": sha,
            "verified_quote": "void Foo::bar() {}",
            "title": "외부에서 믿으면 안 되는 제목",
            "verified_at": "1900-01-01T00:00:00Z",
        }
    )

    graph = _core_graph_objects()
    evidence_ref = next(obj for obj in graph if obj["kind"] == "EvidenceRef")
    evidence_ref["ref_type"] = "code_locator"
    evidence_ref["locator"] = {"code_locator_id": locator["id"]}
    mapping = next(obj for obj in graph if obj["kind"] == "DomainMapping")
    mapping["code_locator_ids"] = [locator["id"]]

    result = _mutation_plan(
        tmp_path / "brain",
        [*graph, locator],
        repo_context=repo_context,
    )

    assert result.ok is True, (result.error_code, result.detail)
    planned_by_id = {obj["id"]: obj for obj in result.after_objects}
    stored = planned_by_id[locator["id"]]
    assert stored["title"] == "Foo::bar"
    assert stored["verified_at"] != "1900-01-01T00:00:00Z"
    assert stored["verified_quote"] == "void Foo::bar() {}"
    assert any(
        ref.pointer == "/locator/code_locator_id"
        and ref.object_id == locator["id"]
        for ref in iter_object_refs(planned_by_id[evidence_ref["id"]])
    )
    assert planned_by_id[mapping["id"]]["code_locator_ids"] == [locator["id"]]


def test_glossary_template_promotes_through_official_mutation_gate(tmp_path):
    seed_objects = _core_graph_objects()
    candidate = _load_json(KINDS / "GlossaryTerm.template.json")
    graph_term_index = next(
        index
        for index, obj in enumerate(seed_objects)
        if obj["kind"] == "GlossaryTerm"
    )
    assert seed_objects[graph_term_index] == candidate
    candidate["status"] = "candidate"
    candidate["candidate"] = {
        "candidate_state": "ready_for_review",
        "candidate_source": "spec",
    }
    candidate.pop("review_record_id", None)
    seed_objects[graph_term_index] = candidate
    assert validate_object(candidate) == []
    seed = BrainStore({obj["id"]: obj for obj in seed_objects})
    assert lint_store_report(seed) == ()

    brain_root = tmp_path / "promotion" / "brain"
    for obj in seed_objects:
        _write_raw(brain_root, obj)

    promoted, records = promote(
        [candidate],
        [candidate["id"]],
        "single_object",
        reviewer="user-confirmed",
        reviewed_at=FIXED_TIME,
    )

    assert len(promoted) == len(records) == 1
    reviewed, record = promoted[0], records[0]
    expected_record = _load_json(KINDS / "ReviewRecord.template.json")
    expected_record["evidence_refs"] = candidate["evidence_refs"]
    expected_record.pop("created_at")
    expected_record.pop("updated_at")
    assert record == expected_record
    result = _mutation_plan(
        brain_root,
        [reviewed, record],
        operation=MutationOperation.PROMOTE,
        preconditions={candidate["id"]: _object_hash(candidate)},
        expected_corpus_fingerprint=corpus_fingerprint(seed),
    )

    assert result.ok is True, (result.error_code, result.detail)
    planned_by_id = {obj["id"]: obj for obj in result.after_objects}
    planned_reviewed = planned_by_id[reviewed["id"]]
    planned_record = planned_by_id[record["id"]]
    assert planned_reviewed["review_record_id"] == planned_record["id"]
    assert planned_record["target_object_id"] == planned_reviewed["id"]
    merged = {obj["id"]: obj for obj in seed_objects}
    merged.update(planned_by_id)
    assert lint_store_report(BrainStore(merged)) == ()


def test_context_projection_template_is_rederived_by_current_builder():
    context = _load_json(KINDS / "DomainContext.template.json")
    expected = _load_json(KINDS / "ContextProjection.template.json")

    actual, content = build_context_projection(
        BrainStore({context["id"]: context}),
        context["id"],
        output_locator=expected["output_locator"],
        generated_by=expected["generated_by"],
    )
    for field in ("created_at", "updated_at", "generated_at"):
        expected.pop(field)

    assert actual == expected
    assert content.startswith("GENERATED FROM PROJECT BRAIN - DO NOT EDIT\n")


EXPECTED_CORE_REFERENCES = {
    ("evref.ctx.ref", "/evidence_manifest_id", "manifest.ctx.source", "EvidenceManifest"),
    ("context.ctx", "/glossary_term_ids/0", "g.ctx.term", "GlossaryTerm"),
    ("g.ctx.term", "/context_id", "context.ctx", "DomainContext"),
    ("g.ctx.term", "/evidence_refs/0", "evref.ctx.ref", "EvidenceRef"),
    ("mapping.ctx.behavior", "/context_id", "context.ctx", "DomainContext"),
    ("mapping.ctx.behavior", "/glossary_term_ids/0", "g.ctx.term", "GlossaryTerm"),
    ("mapping.ctx.behavior", "/evidence_refs/0", "evref.ctx.ref", "EvidenceRef"),
    (
        "mapping.ctx.behavior",
        "/decision_record_ids/0",
        "decision.ctx.change",
        "DecisionRecord",
    ),
    (
        "decision.ctx.change",
        "/affected_context_ids/0",
        "context.ctx",
        "DomainContext",
    ),
    (
        "decision.ctx.change",
        "/affected_mapping_ids/0",
        "mapping.ctx.behavior",
        "DomainMapping",
    ),
    (
        "decision.ctx.change",
        "/source_object_ids/0",
        "evref.ctx.ref",
        "EvidenceRef",
    ),
    (
        "decision.ctx.change",
        "/evidence_refs/0",
        "evref.ctx.ref",
        "EvidenceRef",
    ),
}


def test_complete_object_graph_is_connected_typed_and_lint_clean():
    objects = _core_graph_objects()
    by_id = {obj["id"]: obj for obj in objects}
    assert len(by_id) == len(objects)
    assert {obj["kind"] for obj in objects} == {
        "EvidenceManifest",
        "EvidenceRef",
        "DomainContext",
        "GlossaryTerm",
        "DomainMapping",
        "DecisionRecord",
    }
    for obj in objects:
        assert validate_object(obj) == [], obj["id"]
        assert validate_object_id(obj) == [], obj["id"]

    adjacency = {object_id: set() for object_id in by_id}
    actual_references = set()
    for obj in objects:
        for ref in iter_object_refs(obj):
            if ref.object_id in by_id:
                adjacency[obj["id"]].add(ref.object_id)
                adjacency[ref.object_id].add(obj["id"])
            actual_references.add(
                (
                    obj["id"],
                    ref.pointer,
                    ref.object_id,
                    by_id[ref.object_id]["kind"] if ref.object_id in by_id else None,
                )
            )

    seen = set()
    pending = [next(iter(by_id))]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(adjacency[current] - seen)
    assert seen == set(by_id)

    assert actual_references == EXPECTED_CORE_REFERENCES

    assert lint_store_report(BrainStore(by_id)) == ()


def test_complete_build_notes_exercises_all_sections_and_builds_clean_bundle():
    notes = _load_json(TEMPLATES / "build-notes.complete.template.json")
    assert set(notes) == {
        "context",
        "sources",
        "code_anchors",
        "glossary",
        "mappings",
        "decisions",
        "refs",
        "updates",
        "extra_objects",
    }
    assert validate_notes(notes) == []
    assert all("decision_keys" not in mapping for mapping in notes["mappings"])
    assert notes["decisions"][0]["affects"] == ["behavior"]

    seed = BrainStore({obj["id"]: obj for obj in _core_graph_objects()})
    result = build(notes, seed, FIXED_TIME)

    assert result["errors"] == []
    assert "mapping.ctx.behavior" in result["preconditions"]
    assert result["resolved_refs"] == {"existing-term": "g.ctx.term"}
    by_id = {obj["id"]: obj for obj in result["objects"]}
    assert by_id["mapping.ctx-build.behavior"]["decision_record_ids"] == [
        "decision.ctx-build.change"
    ]
    assert by_id["decision.ctx-build.change"]["affected_mapping_ids"] == [
        "mapping.ctx-build.behavior"
    ]
    assert by_id["mapping.ctx.behavior"]["title"] != seed.get(
        "mapping.ctx.behavior"
    )["title"]
    assert "ledger.ctx-build.note" in by_id


EXPECTED_INVALID_CASES = {
    "notes-missing-context-commit": (
        "notes",
        "validate_notes",
        "standalone",
        None,
        "context.key·context.commit 필수",
    ),
    "missing-base-required": (
        "schema",
        "validate_object",
        "standalone",
        None,
        "missing base field 'title'",
    ),
    "missing-kind-required": (
        "schema",
        "validate_object",
        "standalone",
        None,
        "EvidenceManifest missing field 'redaction_status'",
    ),
    "candidate-without-metadata": (
        "schema",
        "validate_object",
        "standalone",
        None,
        "candidate GlossaryTerm requires candidate metadata",
    ),
    "reviewed-without-evidence": (
        "schema",
        "validate_object",
        "standalone",
        None,
        "reviewed GlossaryTerm requires non-empty evidence_refs",
    ),
    "invalid-redaction-status": (
        "schema",
        "validate_object",
        "standalone",
        None,
        "EvidenceManifest invalid redaction_status",
    ),
    "dangling-reference": (
        "lint",
        "lint_store_report",
        "merged_store",
        "dangling_reference",
        None,
    ),
    "code-locator-without-quote": (
        "mutation",
        "mutation_plan",
        "repo_fixture",
        "quote_required",
        None,
    ),
    "code-locator-coordinate-change-without-quote": (
        "mutation",
        "mutation_plan",
        "repo_fixture",
        "quote_required",
        None,
    ),
    "reviewed-to-candidate": (
        "mutation",
        "mutation_plan",
        "existing_object",
        "status_transition_invalid",
        None,
    ),
}


def _run_invalid_case(case: dict, payload, tmp_path: Path) -> None:
    expected = case["expected"]
    setup = case["setup"]
    bases = _base_objects(setup["base_fixture_files"])

    if case["validator"] == "validate_notes":
        errors = validate_notes(payload)
        assert len(errors) == 1
        assert expected["message_fragment"] in errors[0]
        return

    if case["validator"] == "validate_object":
        errors = validate_object(payload)
        assert len(errors) == 1
        assert expected["message_fragment"] in errors[0]
        return

    if case["validator"] == "lint_store_report":
        payload_objects = _fixture_objects(payload)
        for obj in [*bases, *payload_objects]:
            assert validate_object(obj) == [], obj.get("id")
            assert validate_object_id(obj) == [], obj.get("id")
        merged = {obj["id"]: obj for obj in [*bases, *payload_objects]}
        problems = lint_store_report(BrainStore(merged))
        assert {problem.code for problem in problems} == {expected["code"]}
        if expected["message_fragment"] is not None:
            assert any(
                expected["message_fragment"] in problem.message
                for problem in problems
            )
        return

    assert case["validator"] == "mutation_plan"
    brain_root = tmp_path / case["name"] / "brain"
    inputs = _fixture_objects(payload)
    repo_context = None
    if setup["mode"] == "repo_fixture":
        repo_context, sha = _git_repo(tmp_path / case["name"])
        for obj in [*bases, *inputs]:
            if obj.get("kind") == "CodeLocator":
                obj["repo"] = "demoapp"
                obj["commit_sha"] = sha
    for obj in [*bases, *inputs]:
        assert validate_mutation_input_schema(
            obj,
            omitted_required_fields=(
                frozenset({"verified_at"})
                if obj.get("kind") == "CodeLocator"
                else frozenset()
            ),
        ) == [], obj.get("id")
        assert validate_object_id(obj) == [], obj.get("id")
    if bases:
        assert lint_store_report(BrainStore({obj["id"]: obj for obj in bases})) == ()
    for obj in bases:
        _write_raw(brain_root, obj)
    result = _mutation_plan(brain_root, inputs, repo_context=repo_context)
    assert result.error_code == expected["code"], result.detail
    if expected["message_fragment"] is not None:
        assert expected["message_fragment"] in (result.detail or "")


def test_invalid_manifest_describes_and_replays_all_four_validation_layers(tmp_path):
    manifest = _load_json(INVALID / "manifest.json")
    assert set(manifest) == {"schema_version", "cases"}
    assert manifest["schema_version"] == 1
    assert isinstance(manifest["cases"], list)
    assert {case["name"] for case in manifest["cases"]} == set(
        EXPECTED_INVALID_CASES
    )
    assert {case["layer"] for case in manifest["cases"]} == {
        "notes",
        "schema",
        "lint",
        "mutation",
    }

    for case in manifest["cases"]:
        assert set(case) == {
            "name",
            "file",
            "layer",
            "validator",
            "setup",
            "expected",
            "purpose",
        }
        layer, validator, mode, code, fragment = EXPECTED_INVALID_CASES[
            case["name"]
        ]
        assert case["file"] == f"{case['name']}.json"
        assert (case["layer"], case["validator"]) == (layer, validator)
        assert set(case["setup"]) == {"mode", "base_fixture_files"}
        assert case["setup"]["mode"] == mode
        assert isinstance(case["setup"]["base_fixture_files"], list)
        assert case["expected"] == {
            "code": code,
            "message_fragment": fragment,
        }
        assert isinstance(case["purpose"], str) and case["purpose"].strip()
        for relative in case["setup"]["base_fixture_files"]:
            _load_json(TEMPLATES / relative)

        payload = _load_json(INVALID / case["file"])
        _run_invalid_case(case, payload, tmp_path)


def test_legacy_quote_omission_loads_and_unchanged_ingest_preserves_it_but_new_write_fails(
    tmp_path,
):
    legacy = _load_json(KINDS / "CodeLocator.template.json")
    legacy.pop("verified_quote", None)
    brain_root = tmp_path / "legacy-quote" / "brain"
    _write_raw(brain_root, legacy)

    loaded = BrainStore.load(brain_root).get(legacy["id"])
    assert "verified_quote" not in loaded
    replacement = dict(loaded)
    replacement["title"] = "외부 제목 변경"
    replacement["verified_at"] = "2099-01-01T00:00:00Z"
    unchanged = _mutation_plan(brain_root, [replacement])
    assert unchanged.ok is True, (unchanged.error_code, unchanged.detail)
    assert unchanged.after["title"] == loaded["title"]
    assert unchanged.after["verified_at"] == loaded["verified_at"]
    assert "verified_quote" not in unchanged.after

    new_locator = dict(legacy)
    new_locator["id"] = "code.ctx.new-without-quote"
    rejected = _mutation_plan(tmp_path / "new-quote" / "brain", [new_locator])
    assert rejected.error_code == "quote_required"


def test_legacy_short_sha_loads_and_unchanged_ingest_preserves_it_but_write_gate_is_exact(
    tmp_path,
):
    repo_context, sha = _git_repo(tmp_path / "short-sha-repo")
    legacy = _load_json(KINDS / "CodeLocator.template.json")
    legacy.update(
        {
            "repo": "demoapp",
            "path": "Foo.cpp",
            "symbol": "Foo::bar",
            "commit_sha": sha[:12],
            "verified_quote": "void Foo::bar() {}",
        }
    )
    brain_root = tmp_path / "legacy-short" / "brain"
    _write_raw(brain_root, legacy)
    loaded = BrainStore.load(brain_root).get(legacy["id"])
    assert loaded["commit_sha"] == sha[:12]

    unchanged = _mutation_plan(brain_root, [dict(loaded)])
    assert unchanged.ok is True, (unchanged.error_code, unchanged.detail)

    new_locator = dict(legacy)
    new_locator["id"] = "code.ctx.new-short-sha"
    new_result = _mutation_plan(
        tmp_path / "new-short" / "brain",
        [new_locator],
        repo_context=repo_context,
    )
    assert new_result.error_code == "commit_missing"

    changed = dict(legacy)
    changed["path"] = "Changed.cpp"
    changed_result = _mutation_plan(
        brain_root,
        [changed],
        repo_context=repo_context,
    )
    assert changed_result.error_code == "commit_missing"
