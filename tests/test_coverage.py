import hashlib
import inspect
import json

import pytest

from project_brain.coverage import (
    BuildArtifactBinding,
    CoverageError,
    ObjectIdentity,
    build_artifact_binding,
    normalize_build_artifact_binding,
    normalize_coverage,
    object_identities,
    plan_expected_objects,
    read_coverage,
)
from project_brain.store import BrainStore
from tests.coverage_helpers import direct_coverage


def domain_context(*, kind="DomainContext"):
    return {"id": "context.ctx", "kind": kind}


def assembled_coverage_fixture(*, verify_groups=None, context_mode="create"):
    expected_objects = [
        {"id": "code.ctx.anchor-one", "kind": "CodeLocator"},
        {"id": "code.ctx.anchor-two", "kind": "CodeLocator"},
        {"id": "decision.ctx.decision-one", "kind": "DecisionRecord"},
        {"id": "decision.ctx.decision-two", "kind": "DecisionRecord"},
        {"id": "evref.ctx.anchor-one", "kind": "EvidenceRef"},
        {"id": "evref.ctx.anchor-two", "kind": "EvidenceRef"},
        {"id": "evref.ctx.commit-abc", "kind": "EvidenceRef"},
        {"id": "g.ctx.term-one", "kind": "GlossaryTerm"},
        {"id": "g.ctx.term-two", "kind": "GlossaryTerm"},
        {"id": "ledger.ctx.extra", "kind": "EventLedgerRecord"},
        {"id": "manifest.ctx.code", "kind": "EvidenceManifest"},
        {"id": "mapping.ctx.mapping-one", "kind": "DomainMapping"},
        {"id": "mapping.ctx.mapping-two", "kind": "DomainMapping"},
    ]
    if context_mode == "create":
        expected_objects.insert(
            2,
            {"id": "context.ctx", "kind": "DomainContext"},
        )
    return {
        "version": 1,
        "mode": "assembled",
        "verify_groups": {"names": verify_groups or ["g1"]},
        "context": {"key": "ctx", "mode": context_mode},
        "sections": {
            "sources": {"ids": ["manifest.ctx.code"]},
            "glossary": {"keys": ["term-two", "term-one"]},
            "code_anchors": {"keys": ["anchor-two", "anchor-one"]},
            "mappings": {"keys": ["mapping-two", "mapping-one"]},
            "decisions": {
                "items": [
                    {
                        "key": "decision-two",
                        "evidence": [{"type": "commit", "ref": "abc"}],
                    },
                    {
                        "key": "decision-one",
                        "evidence": [{"type": "commit", "ref": "abc"}],
                    },
                ]
            },
            "refs": {
                "items": [
                    {
                        "category": "glossary",
                        "alias": "shared",
                        "id": "g.ctx.existing",
                        "expect": {"kind": "GlossaryTerm"},
                    },
                    {
                        "category": "mapping",
                        "alias": "mapping-existing",
                        "id": "mapping.ctx.existing",
                        "expect": {"kind": "DomainMapping"},
                    },
                ]
            },
            "updates": {"ids": [], "empty_reason": "기존 객체 갱신 없음"},
            "extra_objects": {
                "objects": [
                    {"id": "ledger.ctx.extra", "kind": "EventLedgerRecord"}
                ]
            },
        },
        "expected_objects": expected_objects,
    }


def coverage_with_same_id_and_different_kinds(mode):
    duplicate_objects = [
        {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"},
        {"id": "ledger.ctx.one", "kind": "TemporalFact"},
    ]
    if mode == "direct":
        return {
            "version": 1,
            "mode": "direct",
            "objects": duplicate_objects,
        }
    raw = assembled_coverage_fixture()
    raw["expected_objects"] = duplicate_objects
    return raw


def test_direct_contract_rejects_mixed_mode_fields():
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(
            {
                "version": 1,
                "mode": "direct",
                "objects": [
                    {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"}
                ],
                "expected_objects": [],
            }
        )
    assert exc.value.code == "coverage_invalid"
    assert exc.value.unexpected == ("expected_objects",)


@pytest.mark.parametrize("version", [True, 0, 2, "1"])
def test_version_accepts_only_integer_one(version):
    raw = direct_coverage(
        {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"}
    )
    raw["version"] = version
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(raw)
    assert exc.value.field == "version"


def test_assembled_contract_requires_exact_top_level_and_section_shapes():
    raw = assembled_coverage_fixture()
    del raw["sections"]["refs"]
    raw["sections"]["other"] = {"ids": []}
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(raw)
    assert exc.value.section == "sections"
    assert exc.value.missing == ("refs",)
    assert exc.value.unexpected == ("other",)


def test_assembled_empty_list_requires_reason_and_nonempty_forbids_it():
    raw = assembled_coverage_fixture()
    raw["sections"]["updates"] = {"ids": []}
    with pytest.raises(CoverageError, match="empty_reason"):
        normalize_coverage(raw)
    raw["sections"]["updates"] = {
        "ids": ["mapping.ctx.one"],
        "empty_reason": "없음",
    }
    with pytest.raises(CoverageError, match="empty_reason"):
        normalize_coverage(raw)


def test_empty_verify_groups_require_nonblank_reason():
    raw = assembled_coverage_fixture(verify_groups=[])
    raw["verify_groups"] = {"names": [], "empty_reason": "  "}
    with pytest.raises(CoverageError, match="empty_reason"):
        normalize_coverage(raw)


@pytest.mark.parametrize(
    ("mutator", "field"),
    [
        (
            lambda c: c["verify_groups"]["names"].extend(["g1"]),
            "verify_groups.names",
        ),
        (
            lambda c: c["sections"]["glossary"]["keys"].extend(
                ["term-one"]
            ),
            "sections.glossary.keys",
        ),
        (
            lambda c: c["sections"]["refs"]["items"].append(
                {
                    "category": "mapping",
                    "alias": "shared",
                    "id": "mapping.ctx.one",
                    "expect": {},
                }
            ),
            "sections.refs.items.alias",
        ),
    ],
)
def test_raw_duplicates_fail_before_set_folding(mutator, field):
    raw = assembled_coverage_fixture()
    mutator(raw)
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(raw)
    assert exc.value.field == field


def test_ref_alias_is_unique_across_categories():
    raw = assembled_coverage_fixture()
    raw["sections"]["refs"]["items"] = [
        {
            "category": "glossary",
            "alias": "same",
            "id": "g.ctx.existing",
            "expect": {},
        },
        {
            "category": "mapping",
            "alias": "same",
            "id": "mapping.ctx.existing",
            "expect": {},
        },
    ]
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(raw)
    assert exc.value.field == "sections.refs.items.alias"


def test_ref_expect_rejects_non_string_key_before_canonical_sha_collision():
    valid = assembled_coverage_fixture()
    valid["sections"]["refs"]["items"][0]["expect"] = {"1": "x"}
    valid_binding = normalize_coverage(valid)
    assert json.loads(valid_binding.canonical_bytes) == valid_binding.contract

    invalid = assembled_coverage_fixture()
    invalid["sections"]["refs"]["items"][0]["expect"] = {1: "x"}
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(invalid)
    assert exc.value.field == "refs.items.expect"


def test_ref_expect_accepts_json_array_but_rejects_tuple():
    valid = assembled_coverage_fixture()
    valid["sections"]["refs"]["items"][0]["expect"] = {
        "status": ["reviewed", "candidate"]
    }
    binding = normalize_coverage(valid)
    assert json.loads(binding.canonical_bytes) == binding.contract

    invalid = assembled_coverage_fixture()
    invalid["sections"]["refs"]["items"][0]["expect"] = {
        "status": ("reviewed", "candidate")
    }
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(invalid)
    assert exc.value.field == "refs.items.expect"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_ref_expect_rejects_non_finite_float(value):
    raw = assembled_coverage_fixture()
    raw["sections"]["refs"]["items"][0]["expect"] = {"score": value}
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(raw)
    assert exc.value.field == "refs.items.expect"


def test_duplicate_evidence_in_one_decision_is_rejected():
    raw = assembled_coverage_fixture()
    raw["sections"]["decisions"]["items"][0]["evidence"].append(
        {"type": "commit", "ref": "abc"}
    )
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(raw)
    assert exc.value.field == "sections.decisions.items.evidence"


@pytest.mark.parametrize("mode", ["direct", "assembled"])
def test_final_object_lists_reject_duplicate_id_even_when_kind_differs(mode):
    raw = coverage_with_same_id_and_different_kinds(mode)
    with pytest.raises(CoverageError) as exc:
        normalize_coverage(raw)
    assert exc.value.field in {"objects.id", "expected_objects.id"}


def test_live_coverage_rejects_empty_final_object_list():
    with pytest.raises(CoverageError, match="must not be empty"):
        normalize_coverage({"version": 1, "mode": "direct", "objects": []})


def test_normalization_sorts_identity_arrays_but_preserves_verify_group_order():
    raw = assembled_coverage_fixture(verify_groups=["second", "first"])
    binding = normalize_coverage(raw)
    assert binding.contract["verify_groups"]["names"] == ["second", "first"]
    assert binding.contract["sections"]["glossary"]["keys"] == [
        "term-one",
        "term-two",
    ]
    assert binding.contract["sections"]["code_anchors"]["keys"] == [
        "anchor-one",
        "anchor-two",
    ]
    assert binding.canonical_bytes.endswith(b"\n")
    assert binding.sha256 == hashlib.sha256(binding.canonical_bytes).hexdigest()
    assert json.loads(binding.canonical_bytes) == binding.contract


def test_planner_expands_code_anchor_and_deduplicates_decision_evidence():
    store = BrainStore({})
    binding = normalize_coverage(assembled_coverage_fixture())
    planned = plan_expected_objects(binding, store)
    assert ObjectIdentity("code.ctx.anchor-one", "CodeLocator") in planned
    assert ObjectIdentity("evref.ctx.anchor-one", "EvidenceRef") in planned
    assert planned.count(ObjectIdentity("evref.ctx.commit-abc", "EvidenceRef")) == 1
    assert planned == binding.expected_objects


def test_planner_rejects_authored_expected_objects_that_disagree():
    raw = assembled_coverage_fixture()
    raw["expected_objects"] = [
        item
        for item in raw["expected_objects"]
        if item["id"] != "evref.ctx.anchor-one"
    ]
    binding = normalize_coverage(raw)

    with pytest.raises(CoverageError) as exc:
        plan_expected_objects(binding, BrainStore({}))

    assert exc.value.code == "coverage_build_mismatch"
    assert exc.value.field == "expected_objects"
    assert exc.value.missing == ("evref.ctx.anchor-one:EvidenceRef",)


def test_context_create_and_reuse_are_checked_against_store():
    create = normalize_coverage(assembled_coverage_fixture(context_mode="create"))
    with pytest.raises(CoverageError, match="already exists"):
        plan_expected_objects(
            create,
            BrainStore({"context.ctx": domain_context()}),
        )
    reuse = normalize_coverage(assembled_coverage_fixture(context_mode="reuse"))
    with pytest.raises(CoverageError, match="DomainContext"):
        plan_expected_objects(reuse, BrainStore({}))
    with pytest.raises(CoverageError, match="DomainContext"):
        plan_expected_objects(
            reuse,
            BrainStore({"context.ctx": domain_context(kind="GlossaryTerm")}),
        )
    assert plan_expected_objects(
        reuse,
        BrainStore({"context.ctx": domain_context()}),
    ) == reuse.expected_objects


def test_planner_resolves_update_kind_from_store():
    raw = assembled_coverage_fixture()
    raw["sections"]["updates"] = {"ids": ["mapping.ctx.old"]}
    raw["expected_objects"].append(
        {"id": "mapping.ctx.old", "kind": "DomainMapping"}
    )
    binding = normalize_coverage(raw)
    with pytest.raises(CoverageError, match="store"):
        plan_expected_objects(binding, BrainStore({}))
    store = BrainStore(
        {
            "mapping.ctx.old": {
                "id": "mapping.ctx.old",
                "kind": "DomainMapping",
            }
        }
    )
    assert plan_expected_objects(binding, store) == binding.expected_objects


def test_planner_does_not_import_or_call_assembly_build():
    source = inspect.getsource(plan_expected_objects)
    module_source = inspect.getsource(inspect.getmodule(plan_expected_objects))
    assert "assembly" not in source
    assert "project_brain.assembly" not in module_source


def test_direct_planner_uses_normalized_object_identities():
    raw = direct_coverage(
        {"id": "ledger.ctx.two", "kind": "EventLedgerRecord"},
        {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"},
    )
    binding = normalize_coverage(raw)
    assert plan_expected_objects(binding, BrainStore({})) == (
        ObjectIdentity("ledger.ctx.one", "EventLedgerRecord"),
        ObjectIdentity("ledger.ctx.two", "EventLedgerRecord"),
    )


def test_read_coverage_normalizes_json_and_reports_invalid_json(tmp_path):
    path = tmp_path / "coverage.json"
    path.write_text(
        json.dumps(
            direct_coverage(
                {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"}
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert read_coverage(path) == normalize_coverage(
        direct_coverage(
            {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"}
        )
    )
    path.write_text("{", encoding="utf-8")
    with pytest.raises(CoverageError) as exc:
        read_coverage(path)
    assert exc.value.code == "coverage_invalid"


def test_object_identities_validate_shape_and_sort():
    assert object_identities(
        [
            {"id": "ledger.ctx.two", "kind": "EventLedgerRecord"},
            {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"},
        ]
    ) == (
        ObjectIdentity("ledger.ctx.one", "EventLedgerRecord"),
        ObjectIdentity("ledger.ctx.two", "EventLedgerRecord"),
    )
    with pytest.raises(CoverageError) as exc:
        object_identities(
            [
                {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"},
                {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"},
            ]
        )
    assert exc.value.field == "objects.id"


def test_build_artifact_binding_hashes_canonical_object_bundle():
    binding = normalize_coverage(
        direct_coverage(
            {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"}
        )
    )
    objects = [
        {
            "kind": "EventLedgerRecord",
            "summary": "하나",
            "id": "ledger.ctx.one",
        }
    ]
    artifact = build_artifact_binding(binding, objects)
    canonical = (
        '[{"id":"ledger.ctx.one","kind":"EventLedgerRecord",'
        '"summary":"하나"}]\n'
    ).encode("utf-8")
    assert artifact == BuildArtifactBinding(
        version=1,
        coverage_sha256=binding.sha256,
        expected_objects=binding.expected_objects,
        actual_objects=binding.expected_objects,
        objects_sha256=hashlib.sha256(canonical).hexdigest(),
    )
    assert artifact.as_dict() == {
        "version": 1,
        "coverage_sha256": binding.sha256,
        "expected_objects": [
            {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"}
        ],
        "actual_objects": [
            {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"}
        ],
        "objects_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def test_build_artifact_binding_rejects_actual_object_mismatch():
    binding = normalize_coverage(
        direct_coverage(
            {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"}
        )
    )
    with pytest.raises(CoverageError) as exc:
        build_artifact_binding(
            binding,
            [{"id": "ledger.ctx.two", "kind": "EventLedgerRecord"}],
        )
    assert exc.value.code == "coverage_build_mismatch"


def test_build_artifact_binding_parser_requires_exact_shape():
    raw = {
        "version": 1,
        "coverage_sha256": "a" * 64,
        "expected_objects": [
            {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"}
        ],
        "actual_objects": [
            {"id": "ledger.ctx.one", "kind": "EventLedgerRecord"}
        ],
        "objects_sha256": "b" * 64,
    }
    assert normalize_build_artifact_binding(raw) == BuildArtifactBinding(
        version=1,
        coverage_sha256="a" * 64,
        expected_objects=(
            ObjectIdentity("ledger.ctx.one", "EventLedgerRecord"),
        ),
        actual_objects=(
            ObjectIdentity("ledger.ctx.one", "EventLedgerRecord"),
        ),
        objects_sha256="b" * 64,
    )
    raw["extra"] = True
    with pytest.raises(CoverageError) as exc:
        normalize_build_artifact_binding(raw)
    assert exc.value.unexpected == ("extra",)


def test_coverage_error_exposes_structured_details():
    error = CoverageError(
        "coverage_notes_mismatch",
        "declared notes differ",
        section="glossary",
        field="keys",
        missing=("term-one",),
        unexpected=("term-two",),
        coverage_sha256="a" * 64,
    )
    assert error.as_dict() == {
        "code": "coverage_notes_mismatch",
        "detail": "declared notes differ",
        "section": "glossary",
        "field": "keys",
        "missing": ["term-one"],
        "unexpected": ["term-two"],
        "coverage_sha256": "a" * 64,
    }
