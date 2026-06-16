import unittest
from project_brain.assembly import derive_id, build_glossary_terms, build_code_evidence, resolve_refs
from project_brain.assembly import build_mappings
from project_brain.assembly import build_manifests, build_context
from project_brain.assembly import apply_updates
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


class BuildMappingsTest(unittest.TestCase):
    def test_mapping_links_new_and_ref_terms(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc", "now": NOW, "repo": "bb2_client"},
            "mappings": [{"key": "hit-trigger", "canonical_summary": "요약",
                          "meaning": "의미", "boundary": "경계",
                          "glossary_keys": ["hit"], "glossary_term_refs": ["near_pop_hook"],
                          "code_evref_keys": ["hit-hook"]}],
        }
        refs_map = {"near_pop_hook": "g.ctx.do-disturb-on-near-bubble-pop"}
        objs = build_mappings(notes, refs_map, NOW)
        m = objs[0]
        self.assertEqual(m["id"], "mapping.ctx.hit-trigger")
        self.assertEqual(m["kind"], "DomainMapping")
        self.assertEqual(m["status"], "reviewed")
        self.assertEqual(sorted(m["glossary_term_ids"]),
                         ["g.ctx.do-disturb-on-near-bubble-pop", "g.ctx.hit"])
        self.assertEqual(m["code_locator_ids"], ["code.ctx.hit-hook"])
        self.assertEqual(m["evidence_refs"], ["evref.ctx.hit-hook"])
        self.assertEqual(m["caveats"], ["history_coverage=unsearched"])


class BuildManifestsContextTest(unittest.TestCase):
    def test_source_becomes_manifest(self):
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "bb2_client"},
                 "sources": [{"id": "manifest.ctx.s", "source_type": "session",
                              "title": "T", "locator": "...", "captured_by": "user-statement"}]}
        objs = build_manifests(notes, NOW)
        self.assertEqual(len(objs), 1)
        m = objs[0]
        self.assertEqual(m["id"], "manifest.ctx.s")
        self.assertEqual(m["kind"], "EvidenceManifest")
        self.assertEqual(m["truth_role"], "source")
        self.assertEqual(m["redaction_status"], "none")  # default
        self.assertEqual(m["acl"], ["bb2-team"])          # default

    def test_context_built_only_with_display_fields(self):
        base_cx = {"key": "ctx", "commit": "a", "now": NOW, "repo": "bb2_client"}
        self.assertEqual(build_context({"context": base_cx}, NOW), [])  # display_name 없으면 빈 리스트
        rich = dict(base_cx, display_name="방해버블", boundary_summary="...")
        objs = build_context({"context": rich}, NOW)
        self.assertEqual(objs[0]["id"], "context.ctx")
        self.assertEqual(objs[0]["kind"], "DomainContext")
        self.assertEqual(objs[0]["truth_role"], "domain")


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


T0 = "2026-06-01T00:00:00Z"


def _mapping(**over):
    o = {"id": "mapping.ctx.hook", "kind": "DomainMapping", "status": "reviewed",
         "truth_role": "domain", "title": "t", "context_id": "context.ctx",
         "mapping_key": "hook", "canonical_summary": "s", "meaning": "옛 의미",
         "boundary": "b", "caveats": [], "glossary_term_ids": ["g.ctx.a"],
         "decision_record_ids": [], "code_locator_ids": [], "evidence_refs": ["evref.ctx.x"],
         "schema_version": "0.1", "poc_priority": "P2", "created_at": T0, "updated_at": T0,
         "tags": ["ctx"]}
    o.update(over)
    return o


class ApplyUpdatesTest(unittest.TestCase):
    def test_set_scalar_and_union_list(self):
        # title(비-claim scalar) set + glossary_term_ids union — 둘 다 근거 동반 불필요.
        # claim 필드(meaning·boundary 등)는 별도 테스트(test_claim_*)에서 근거 강제 검증.
        store = _store(_mapping())
        notes = {"updates": [{"id": "mapping.ctx.hook", "expected_updated_at": T0,
                              "union": {"glossary_term_ids": ["g.ctx.b"]},
                              "set": {"title": "새 제목"}}]}
        objs, diffs, errors = apply_updates(notes, store, NOW)
        self.assertEqual(errors, [])
        m = objs[0]
        self.assertEqual(sorted(m["glossary_term_ids"]), ["g.ctx.a", "g.ctx.b"])
        self.assertEqual(m["title"], "새 제목")
        self.assertEqual(m["updated_at"], NOW)
        self.assertEqual(m["status"], "reviewed")  # 강등 없음

    def test_claim_field_requires_evidence(self):
        # meaning(claim) 수정인데 evidence 변경도 evidence_unchanged도 없으면 실패
        store = _store(_mapping())
        notes = {"updates": [{"id": "mapping.ctx.hook", "expected_updated_at": T0,
                              "set": {"meaning": "새 의미"}}]}
        _, _, errors = apply_updates(notes, store, NOW)
        self.assertTrue(any("evidence" in e.lower() for e in errors))

    def test_claim_with_evidence_unchanged_ok(self):
        store = _store(_mapping())
        notes = {"updates": [{"id": "mapping.ctx.hook", "expected_updated_at": T0,
                              "set": {"meaning": "새 의미"}, "evidence_unchanged": True}]}
        _, _, errors = apply_updates(notes, store, NOW)
        self.assertEqual(errors, [])

    def test_expected_updated_at_mismatch_fails(self):
        store = _store(_mapping())
        notes = {"updates": [{"id": "mapping.ctx.hook", "expected_updated_at": "2099-01-01T00:00:00Z",
                              "set": {"boundary": "x"}}]}
        _, _, errors = apply_updates(notes, store, NOW)
        self.assertTrue(any("expected_updated_at" in e for e in errors))

    def test_field_not_in_allowlist_fails(self):
        store = _store(_mapping())
        notes = {"updates": [{"id": "mapping.ctx.hook", "expected_updated_at": T0,
                              "set": {"status": "candidate"}}]}
        _, _, errors = apply_updates(notes, store, NOW)
        self.assertTrue(any("allowlist" in e.lower() or "status" in e for e in errors))

    def test_per_kind_allowlist_rejects_foreign_field(self):
        # GlossaryTerm에 DomainMapping 전용 scalar(meaning)를 set → GlossaryTerm allowlist 밖
        term = {"id": "g.ctx.t", "kind": "GlossaryTerm", "status": "reviewed",
                "truth_role": "domain", "title": "t", "context_id": "context.ctx",
                "term": "용어", "definition": "정의", "evidence_refs": ["evref.ctx.x"],
                "schema_version": "0.1", "poc_priority": "P2",
                "created_at": T0, "updated_at": T0, "tags": ["ctx"]}
        store = _store(term)
        notes = {"updates": [{"id": "g.ctx.t", "expected_updated_at": T0,
                              "set": {"meaning": "엉뚱"}}]}
        _, _, errors = apply_updates(notes, store, NOW)
        self.assertTrue(any("allowlist" in e.lower() for e in errors))
