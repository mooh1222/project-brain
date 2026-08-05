import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_brain.coverage import CoverageError

try:
    from . import assemble_notes as _assemble_notes_module
except ImportError:  # unittest discover는 scripts/를 top-level import path로 쓴다.
    import assemble_notes as _assemble_notes_module

_load_spec = _assemble_notes_module._load_spec
_load_spec_bytes = _assemble_notes_module._load_spec_bytes
assemble_notes = _assemble_notes_module.assemble_notes
build_notes = _assemble_notes_module.build_notes
finalization_contract = _assemble_notes_module.finalization_contract
normalize = _assemble_notes_module.normalize


def _coverage(*, verify_groups=None):
    return {
        "version": 1,
        "mode": "assembled",
        "verify_groups": {"names": verify_groups or ["g1", "g2"]},
        "context": {"key": "ctx", "mode": "create"},
        "sections": {
            "sources": {"ids": ["manifest.ctx.code"]},
            "glossary": {"keys": [], "empty_reason": "fixture에서 용어 없음"},
            "code_anchors": {"keys": [], "empty_reason": "fixture에서 앵커 없음"},
            "mappings": {"keys": [], "empty_reason": "fixture에서 매핑 없음"},
            "decisions": {"items": [], "empty_reason": "fixture에서 결정 없음"},
            "refs": {"items": [], "empty_reason": "fixture에서 참조 없음"},
            "updates": {"ids": [], "empty_reason": "fixture에서 갱신 없음"},
            "extra_objects": {"objects": [], "empty_reason": "fixture에서 추가 객체 없음"},
        },
        "expected_objects": [{"id": "context.ctx", "kind": "DomainContext"}],
    }

SPEC = {
    "CTX": "ctx", "COMMIT": "abc123", "REPO": "{{REPO}}",
    "MANIFESTS": {"code": "manifest.ctx.code"},
    "DISPLAY_NAME": "테스트", "BOUNDARY_SUMMARY": "경계 문장",
    "IN_SCOPE": ["x"], "OUT_OF_SCOPE": ["y"],
    "COVERAGE": _coverage(), "EXCLUDE_TERMS": {"drop-me"},
    "HISTORY_COVERAGE": "partial", "NOW": "2026-06-26T00:00:00+09:00",
    "CLAIM_STATUS": "reviewed", "SOURCE_ACL": ["team"],
    "CAPTURED_AT": "2026-06-26T00:00:00+09:00",
    "EXPECT_UNMERGED_ANCHORS": False,
    "CORRECTIONS": {}, "DECISIONS": [],
}

def _atom(mk, anchors=1, terms=()):
    return {
        "mapping_key": mk, "canonical_summary": f"{mk} 요약",
        "meaning": f"{mk} 의미", "boundary": f"{mk} 경계",
        "code_anchors": [
            {
                "key": f"{mk}-anchor-{i}",
                "path": f"{mk}.cpp",
                "symbol": f"sym{i}",
                "quote": "q",
            }
            for i in range(anchors)
        ],
        "glossary_terms": [{"term_key": t, "term": t, "definition": f"{t} 정의"} for t in terms],
    }


class BuildNotesTest(unittest.TestCase):
    def test_anchor_key_and_mapping_links(self):
        notes = build_notes([_atom("m1", anchors=2, terms=["t1"])], SPEC)
        self.assertEqual(
            [c["key"] for c in notes["code_anchors"]],
            ["m1-anchor-0", "m1-anchor-1"],
        )
        m = notes["mappings"][0]
        self.assertEqual(m["code_evref_keys"], ["m1-anchor-0", "m1-anchor-1"])
        self.assertEqual(m["glossary_keys"], ["t1"])
        self.assertEqual(m["caveats"], ["history_coverage=partial"])

    def test_glossary_first_anchor_evidence(self):
        notes = build_notes([_atom("m1", anchors=2, terms=["t1"])], SPEC)
        g = next(g for g in notes["glossary"] if g["key"] == "t1")
        self.assertEqual(g["evidence_refs"], ["evref.ctx.m1-anchor-0"])

    def test_exclude_terms_dropped(self):
        notes = build_notes([_atom("m1", terms=["keep", "drop-me"])], SPEC)
        self.assertEqual(notes["mappings"][0]["glossary_keys"], ["keep"])
        self.assertNotIn("drop-me", [g["key"] for g in notes["glossary"]])

    def test_decisions_passthrough_and_now(self):
        spec = dict(SPEC, DECISIONS=[{"key": "d1", "decision_type": "improvement",
                                      "title": "t", "summary": "s", "decision": "d",
                                      "evidence": [], "affects": ["m1"]}])
        notes = build_notes([_atom("m1")], spec)
        self.assertEqual(notes["decisions"], spec["DECISIONS"])  # 해석 없이 그대로
        self.assertEqual(notes["context"]["now"], "2026-06-26T00:00:00+09:00")

    def test_context_shape(self):
        notes = build_notes([_atom("m1", terms=["t1"])], SPEC)
        c = notes["context"]
        self.assertEqual(c["key"], "ctx")
        self.assertEqual(c["commit"], "abc123")
        self.assertEqual(c["glossary_term_ids"], ["g.ctx.t1"])
        self.assertEqual(notes["sources"][0]["id"], "manifest.ctx.code")
        # B3(2026-07-02): 엔진이 redaction_status 기본값을 안 채우므로 노트가 명시해야
        # ingest schema(필수 필드 + enum)를 통과한다. 누락 시 "missing field"로 적재 거부.
        self.assertEqual(notes["sources"][0]["redaction_status"], "approved")

    def test_reuse_context_emits_only_existing_context_material(self):
        coverage = _coverage()
        coverage["context"] = {"key": "ctx", "mode": "reuse"}
        coverage["expected_objects"] = [
            {"id": "manifest.ctx.code", "kind": "EvidenceManifest"},
        ]
        notes = build_notes([], dict(SPEC, COVERAGE=coverage))

        self.assertEqual(
            notes["context"],
            {
                "key": "ctx",
                "commit": "abc123",
                "repo": "{{REPO}}",
                "claim_status": "reviewed",
            },
        )

    def test_explicit_source_provenance_and_claim_status_pass_through(self):
        spec = dict(SPEC, CLAIM_STATUS="candidate", SOURCE_ACL=["brain-team"],
                    CAPTURED_AT="2026-07-23T00:00:00+09:00")
        notes = build_notes([_atom("m1")], spec)
        self.assertEqual(notes["context"]["claim_status"], "candidate")
        self.assertEqual(notes["sources"][0]["acl"], ["brain-team"])
        self.assertEqual(notes["sources"][0]["captured_at"], "2026-07-23T00:00:00+09:00")

    def test_code_anchor_omits_external_verification_fields(self):
        notes = build_notes(
            [_atom("m1")],
            dict(SPEC, VERIFIED_AT="2026-07-23T00:01:00+09:00"),
        )
        self.assertEqual(
            set(notes["code_anchors"][0]),
            {"key", "path", "symbol", "manifest", "quote"},
        )

    def test_glossary_candidate_metadata_passes_through_from_first_definition(self):
        candidate = {
            "candidate_state": "ready_for_review",
            "candidate_source": "code",
            "promotion_criteria": ["verified source"],
        }
        first = _atom("m1", terms=[])
        first["glossary_terms"] = [
            {"term_key": "candidate-term", "term": "후보", "definition": "첫 정의",
             "status": "candidate", "candidate": candidate},
            {"term_key": "ordinary-term", "term": "일반", "definition": "일반 정의"},
        ]
        duplicate = _atom("m2", terms=[])
        duplicate["glossary_terms"] = [
            {"term_key": "candidate-term", "term": "후보", "definition": "뒤 정의",
             "status": "reviewed"},
        ]

        notes = build_notes([first, duplicate], SPEC)
        terms = {term["key"]: term for term in notes["glossary"]}

        self.assertEqual(terms["candidate-term"]["definition"], "첫 정의")
        self.assertEqual(terms["candidate-term"]["status"], "candidate")
        self.assertEqual(terms["candidate-term"]["candidate"], candidate)
        self.assertNotIn("status", terms["ordinary-term"])
        self.assertNotIn("candidate", terms["ordinary-term"])

    def test_anchor_quote_is_preserved_exactly(self):
        quote = "\tfirst();\r\n\tsecond();"
        atom = _atom("m1", anchors=0)
        atom["code_anchors"] = [{
            "key": "anchor-key",
            "path": "m1.cpp",
            "symbol": "sym",
            "quote": quote,
        }]
        notes = build_notes([atom], SPEC)
        self.assertEqual(notes["mappings"][0]["code_evref_keys"], ["anchor-key"])
        self.assertEqual(notes["code_anchors"][0]["quote"], quote)

    def test_empty_provenance_reaches_actionable_assembly_rejection(self):
        from project_brain.assembly import validate_notes
        spec = dict(SPEC, SOURCE_ACL=[], CAPTURED_AT="")
        notes = build_notes([_atom("m1")], spec)
        errors = validate_notes(notes)
        self.assertTrue(any("acl" in error and "비어" in error for error in errors))
        self.assertTrue(any("captured_at" in error and "비어" in error for error in errors))


class NormalizeTest(unittest.TestCase):
    def _groups(self):
        return [
            {"group": "g1", "verify": {"corrected_atoms": [_atom("m1")]}, "extract": {"atoms": []}},
            {"group": "g2", "verify": {"corrected_atoms": []},
             "extract": {"atoms": [_atom("m2")]}},  # CASE: 빈 corrected_atoms → extract.atoms 폴백
        ]

    def test_list_form(self):  # main-map 형태
        atoms = normalize(self._groups(), SPEC)
        self.assertEqual([a["mapping_key"] for a in atoms], ["m1", "m2"])

    def test_groups_wrapped_form(self):  # ball-select 형태
        atoms = normalize({"groups": self._groups()}, SPEC)
        self.assertEqual([a["mapping_key"] for a in atoms], ["m1", "m2"])

    def test_group_order_respected(self):
        spec = dict(SPEC, COVERAGE=_coverage(verify_groups=["g2", "g1"]))
        atoms = normalize(self._groups(), spec)
        self.assertEqual([a["mapping_key"] for a in atoms], ["m2", "m1"])

    def test_exact_verify_group_set_is_required(self):
        spec = dict(SPEC, COVERAGE=_coverage(verify_groups=["g2", "g1"]))
        verify = {"groups": [
            {"group": "g1"},
            {"group": "extra"},
            {"group": "g2"},
        ]}

        with self.assertRaises(CoverageError) as raised:
            assemble_notes(verify, spec)

        self.assertEqual(raised.exception.code, "coverage_notes_mismatch")

    def test_corrections_applied(self):
        spec = dict(SPEC, CORRECTIONS={"m1": {"meaning": "고친 의미", "drop_terms": ["t1"]}})
        groups = [{"group": "g1", "verify": {"corrected_atoms": [_atom("m1", terms=["t1", "keep"])]},
                   "extract": {"atoms": []}}]
        spec = dict(spec, COVERAGE=_coverage(verify_groups=["g1"]))
        atoms = normalize(groups, spec)
        self.assertEqual(atoms[0]["meaning"], "고친 의미")
        self.assertEqual([t["term_key"] for t in atoms[0]["glossary_terms"]], ["keep"])

    def test_hook_invoked(self):
        calls = []
        def hook(atoms):
            calls.append(len(atoms)); return atoms[:1]
        spec = dict(SPEC, HOOK=hook, COVERAGE=_coverage(verify_groups=["g1"]))
        groups = [{"group": "g1", "verify": {"corrected_atoms": [_atom("m1"), _atom("m2")]}, "extract": {"atoms": []}}]
        atoms = normalize(groups, spec)
        self.assertEqual(calls, [2])
        self.assertEqual(len(atoms), 1)


class EndToEndTest(unittest.TestCase):
    def test_assemble_notes(self):
        groups = {"groups": [{"group": "g1", "verify": {"corrected_atoms": [_atom("m1", terms=["t1"])]},
                              "extract": {"atoms": []}}]}
        spec = dict(SPEC, COVERAGE=_coverage(verify_groups=["g1"]))
        notes = assemble_notes(groups, spec)
        self.assertEqual(notes["mappings"][0]["key"], "m1")
        self.assertEqual(notes["context"]["now"], spec["NOW"])


class FinalizationContractTest(unittest.TestCase):
    def test_true_derives_unmerged_locator_ids_from_generated_anchor_keys(self):
        notes = build_notes([_atom("m1", anchors=2), _atom("m2", anchors=1)], SPEC)
        contract = finalization_contract(
            notes,
            dict(SPEC, EXPECT_UNMERGED_ANCHORS=True,
                 FINALIZATION={"recall_checks": [], "intentional_terminal_ids": []}),
        )

        self.assertEqual(contract["expected_unmerged_locator_ids"],
                         ["code.ctx.m1-anchor-0", "code.ctx.m1-anchor-1",
                          "code.ctx.m2-anchor-0"])

    def test_false_or_missing_unmerged_expectation_is_empty(self):
        notes = build_notes([_atom("m1")], SPEC)
        for spec in (
            dict(SPEC, FINALIZATION={"recall_checks": [], "intentional_terminal_ids": []}),
            dict(SPEC, EXPECT_UNMERGED_ANCHORS=False,
                 FINALIZATION={"recall_checks": [], "intentional_terminal_ids": []}),
        ):
            with self.subTest(spec=spec):
                self.assertEqual(finalization_contract(notes, spec)["expected_unmerged_locator_ids"], [])


class SpecLoaderTest(unittest.TestCase):
    def test_bytes_loader_uses_pinned_payload_not_live_path(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "domain_spec.py"
            pinned = b'COVERAGE = {"version": 1, "mode": "direct", "objects": []}\n'
            path.write_bytes(b'raise AssertionError("live path was reopened")\n')

            loaded = _load_spec_bytes(pinned, filename=str(path))

            self.assertEqual(loaded["COVERAGE"]["version"], 1)

    def test_path_adapter_matches_bytes_loader(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "domain_spec.py"
            payload = b'COVERAGE = {"version": 1, "mode": "direct", "objects": []}\n'
            path.write_bytes(payload)

            self.assertEqual(
                _load_spec(path),
                _load_spec_bytes(payload, filename=str(path)),
            )


if __name__ == "__main__":
    unittest.main()
