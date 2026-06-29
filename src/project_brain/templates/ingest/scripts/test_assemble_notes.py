import unittest
from assemble_notes import normalize, build_notes, assemble_notes

SPEC = {
    "CTX": "ctx", "COMMIT": "abc123", "REPO": "{{REPO}}",
    "MANIFESTS": {"code": "manifest.ctx.code"},
    "DISPLAY_NAME": "테스트", "BOUNDARY_SUMMARY": "경계 문장",
    "IN_SCOPE": ["x"], "OUT_OF_SCOPE": ["y"],
    "GROUP_ORDER": ["g1", "g2"], "EXCLUDE_TERMS": {"drop-me"},
    "HISTORY_COVERAGE": "partial", "NOW": "2026-06-26T00:00:00+09:00",
    "CORRECTIONS": {}, "DECISIONS": [],
}

def _atom(mk, anchors=1, terms=()):
    return {
        "mapping_key": mk, "canonical_summary": f"{mk} 요약",
        "meaning": f"{mk} 의미", "boundary": f"{mk} 경계",
        "code_anchors": [{"path": f"{mk}.cpp", "symbol": f"sym{i}", "quote": "q"} for i in range(anchors)],
        "glossary_terms": [{"term_key": t, "term": t, "definition": f"{t} 정의"} for t in terms],
    }


class BuildNotesTest(unittest.TestCase):
    def test_anchor_key_and_mapping_links(self):
        notes = build_notes([_atom("m1", anchors=2, terms=["t1"])], SPEC)
        self.assertEqual([c["key"] for c in notes["code_anchors"]], ["m1--0", "m1--1"])
        m = notes["mappings"][0]
        self.assertEqual(m["code_evref_keys"], ["m1--0", "m1--1"])
        self.assertEqual(m["glossary_keys"], ["t1"])
        self.assertEqual(m["caveats"], ["history_coverage=partial"])

    def test_glossary_first_anchor_evidence(self):
        notes = build_notes([_atom("m1", anchors=2, terms=["t1"])], SPEC)
        g = next(g for g in notes["glossary"] if g["key"] == "t1")
        self.assertEqual(g["evidence_refs"], ["evref.ctx.m1--0"])

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
        spec = dict(SPEC, GROUP_ORDER=["g2", "g1"])
        atoms = normalize(self._groups(), spec)
        self.assertEqual([a["mapping_key"] for a in atoms], ["m2", "m1"])

    def test_corrections_applied(self):
        spec = dict(SPEC, CORRECTIONS={"m1": {"meaning": "고친 의미", "drop_terms": ["t1"]}})
        groups = [{"group": "g1", "verify": {"corrected_atoms": [_atom("m1", terms=["t1", "keep"])]},
                   "extract": {"atoms": []}}]
        spec = dict(spec, GROUP_ORDER=["g1"])
        atoms = normalize(groups, spec)
        self.assertEqual(atoms[0]["meaning"], "고친 의미")
        self.assertEqual([t["term_key"] for t in atoms[0]["glossary_terms"]], ["keep"])

    def test_hook_invoked(self):
        calls = []
        def hook(atoms):
            calls.append(len(atoms)); return atoms[:1]
        spec = dict(SPEC, HOOK=hook, GROUP_ORDER=["g1"])
        groups = [{"group": "g1", "verify": {"corrected_atoms": [_atom("m1"), _atom("m2")]}, "extract": {"atoms": []}}]
        atoms = normalize(groups, spec)
        self.assertEqual(calls, [2])
        self.assertEqual(len(atoms), 1)


class EndToEndTest(unittest.TestCase):
    def test_assemble_notes(self):
        groups = {"groups": [{"group": "g1", "verify": {"corrected_atoms": [_atom("m1", terms=["t1"])]},
                              "extract": {"atoms": []}}]}
        spec = dict(SPEC, GROUP_ORDER=["g1"])
        notes = assemble_notes(groups, spec)
        self.assertEqual(notes["mappings"][0]["key"], "m1")
        self.assertEqual(notes["context"]["now"], spec["NOW"])


if __name__ == "__main__":
    unittest.main()
