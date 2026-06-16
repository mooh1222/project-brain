import unittest
from project_brain.assembly import derive_id, build_glossary_terms, build_code_evidence, resolve_refs
from project_brain.store import BrainStore

NOW = "2026-06-16T00:00:00Z"


class DeriveIdTest(unittest.TestCase):
    def test_glossary_id(self):
        self.assertEqual(derive_id("GlossaryTerm", "disturb-bubble-system", "hit"),
                         "g.disturb-bubble-system.hit")

    def test_mapping_id(self):
        self.assertEqual(derive_id("DomainMapping", "ctx", "k"), "mapping.ctx.k")

    def test_code_and_evref_id(self):
        self.assertEqual(derive_id("CodeLocator", "ctx", "a"), "code.ctx.a")
        self.assertEqual(derive_id("EvidenceRef", "ctx", "a"), "evref.ctx.a")


class BuildCodeEvidenceTest(unittest.TestCase):
    def test_anchor_expands_to_locator_and_evref(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc123", "now": NOW, "repo": "bb2_client"},
            "code_anchors": [{"key": "hit-hook", "path": "DisturbObject.h",
                              "symbol": "DisturbObject::_doDisturbOnPop", "line_start": 206,
                              "line_end": 206, "quote": "virtual void _doDisturbOnPop(...){};",
                              "manifest": "manifest.ctx.code-v2"}],
        }
        objs = build_code_evidence(notes, NOW)
        kinds = {o["kind"]: o for o in objs}
        self.assertEqual(set(kinds), {"CodeLocator", "EvidenceRef"})
        loc, ev = kinds["CodeLocator"], kinds["EvidenceRef"]
        self.assertEqual(loc["id"], "code.ctx.hit-hook")
        self.assertEqual(loc["path"], "DisturbObject.h")
        self.assertEqual(loc["commit_sha"], "abc123")
        self.assertEqual(loc["repo"], "bb2_client")
        self.assertEqual(ev["id"], "evref.ctx.hit-hook")
        self.assertEqual(ev["evidence_manifest_id"], "manifest.ctx.code-v2")
        self.assertEqual(ev["ref_type"], "code_locator")
        self.assertEqual(ev["locator"], "DisturbObject.h:206")


def _store(*objs):
    return BrainStore({o["id"]: o for o in objs})


class ResolveRefsTest(unittest.TestCase):
    def test_id_direct_passthrough(self):
        store = _store({"id": "g.ctx.x", "kind": "GlossaryTerm"})
        notes = {"refs": {"terms": {"loc": {"id": "g.ctx.x",
                                            "expect": {"kind": "GlossaryTerm"}}}}}
        refs_map, report, errors = resolve_refs(notes, store)
        self.assertEqual(errors, [])
        self.assertEqual(refs_map["loc"], "g.ctx.x")
        self.assertIn("g.ctx.x", report.values())

    def test_missing_id_is_error(self):
        store = _store()
        notes = {"refs": {"terms": {"loc": {"id": "g.ctx.missing",
                                            "expect": {"kind": "GlossaryTerm"}}}}}
        _, _, errors = resolve_refs(notes, store)
        self.assertTrue(any("g.ctx.missing" in e for e in errors))

    def test_expect_kind_mismatch_is_error(self):
        store = _store({"id": "g.ctx.x", "kind": "GlossaryTerm", "status": "reviewed"})
        notes = {"refs": {"terms": {"loc": {"id": "g.ctx.x",
                                            "expect": {"kind": "DomainMapping"}}}}}
        _, _, errors = resolve_refs(notes, store)
        self.assertTrue(any("expect" in e.lower() or "kind" in e.lower() for e in errors))


class BuildGlossaryTest(unittest.TestCase):
    def test_builds_reviewed_term_with_evidence(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc", "now": NOW, "repo": "bb2_client"},
            "glossary": [{"key": "hit", "term": "hit (직접 타격)", "definition": "슈팅버블이…",
                          "evidence_refs": ["evref.ctx.hit-session"]}],
        }
        objs = build_glossary_terms(notes, NOW)
        self.assertEqual(len(objs), 1)
        t = objs[0]
        self.assertEqual(t["id"], "g.ctx.hit")
        self.assertEqual(t["kind"], "GlossaryTerm")
        self.assertEqual(t["status"], "reviewed")
        self.assertEqual(t["truth_role"], "domain")
        self.assertEqual(t["context_id"], "context.ctx")
        self.assertEqual(t["term"], "hit (직접 타격)")
        self.assertEqual(t["evidence_refs"], ["evref.ctx.hit-session"])
        self.assertIn("created_at", t)  # base() 적용 확인
