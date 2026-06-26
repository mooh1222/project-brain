import unittest
from project_brain.assembly import derive_id, build_glossary_terms, build_code_evidence, resolve_refs
from project_brain.assembly import build_mappings
from project_brain.assembly import build_manifests, build_context
from project_brain.assembly import apply_updates
from project_brain.assembly import build_decisions
from project_brain.store import BrainStore

NOW = "2026-06-16T00:00:00Z"


class DeriveIdTest(unittest.TestCase):
    def test_glossary_id(self):
        self.assertEqual(derive_id("GlossaryTerm", "trap-bubble-system", "hit"),
                         "g.trap-bubble-system.hit")

    def test_mapping_id(self):
        self.assertEqual(derive_id("DomainMapping", "ctx", "k"), "mapping.ctx.k")

    def test_code_and_evref_id(self):
        self.assertEqual(derive_id("CodeLocator", "ctx", "a"), "code.ctx.a")
        self.assertEqual(derive_id("EvidenceRef", "ctx", "a"), "evref.ctx.a")


class BuildCodeEvidenceTest(unittest.TestCase):
    def test_anchor_expands_to_locator_and_evref(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc123", "now": NOW, "repo": "demoapp"},
            "code_anchors": [{"key": "hit-hook", "path": "TrapObject.h",
                              "symbol": "TrapObject::_doTrapOnPop", "line_start": 206,
                              "line_end": 206, "quote": "virtual void _doTrapOnPop(...){};",
                              "manifest": "manifest.ctx.code-v2"}],
        }
        objs = build_code_evidence(notes, NOW)
        kinds = {o["kind"]: o for o in objs}
        self.assertEqual(set(kinds), {"CodeLocator", "EvidenceRef"})
        loc, ev = kinds["CodeLocator"], kinds["EvidenceRef"]
        self.assertEqual(loc["id"], "code.ctx.hit-hook")
        self.assertEqual(loc["path"], "TrapObject.h")
        self.assertEqual(loc["commit_sha"], "abc123")
        self.assertEqual(loc["repo"], "demoapp")
        self.assertNotIn("line_start", loc)
        self.assertNotIn("line_end", loc)
        self.assertEqual(ev["id"], "evref.ctx.hit-hook")
        self.assertEqual(ev["evidence_manifest_id"], "manifest.ctx.code-v2")
        self.assertEqual(ev["ref_type"], "code_locator")
        self.assertEqual(ev["locator"], {"code_locator_id": "code.ctx.hit-hook"})

    def test_anchor_without_line_numbers(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc123", "now": NOW, "repo": "demoapp"},
            "code_anchors": [{"key": "no-line", "path": "Foo.cpp", "symbol": "Foo::bar",
                              "quote": "void bar();", "manifest": "manifest.ctx.code-v2"}],
        }
        objs = build_code_evidence(notes, NOW)
        kinds = {o["kind"]: o for o in objs}
        loc, ev = kinds["CodeLocator"], kinds["EvidenceRef"]
        self.assertNotIn("line_start", loc)
        self.assertNotIn("line_end", loc)
        self.assertEqual(ev["locator"], {"code_locator_id": "code.ctx.no-line"})


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
            "context": {"key": "ctx", "commit": "abc", "now": NOW, "repo": "demoapp"},
            "mappings": [{"key": "hit-trigger", "canonical_summary": "요약",
                          "meaning": "의미", "boundary": "경계",
                          "glossary_keys": ["hit"], "glossary_term_refs": ["near_pop_hook"],
                          "code_evref_keys": ["hit-hook"]}],
        }
        refs_map = {"near_pop_hook": "g.ctx.do-trap-on-near-bubble-pop"}
        objs = build_mappings(notes, refs_map, NOW)
        m = objs[0]
        self.assertEqual(m["id"], "mapping.ctx.hit-trigger")
        self.assertEqual(m["kind"], "DomainMapping")
        self.assertEqual(m["status"], "reviewed")
        self.assertEqual(sorted(m["glossary_term_ids"]),
                         ["g.ctx.do-trap-on-near-bubble-pop", "g.ctx.hit"])
        self.assertEqual(m["code_locator_ids"], ["code.ctx.hit-hook"])
        self.assertEqual(m["evidence_refs"], ["evref.ctx.hit-hook"])
        self.assertEqual(m["caveats"], ["history_coverage=unsearched"])


class BuildManifestsContextTest(unittest.TestCase):
    def test_source_becomes_manifest(self):
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"},
                 "sources": [{"id": "manifest.ctx.s", "source_type": "session",
                              "title": "T", "locator": "...", "captured_by": "user-statement"}]}
        objs = build_manifests(notes, NOW)
        self.assertEqual(len(objs), 1)
        m = objs[0]
        self.assertEqual(m["id"], "manifest.ctx.s")
        self.assertEqual(m["kind"], "EvidenceManifest")
        self.assertEqual(m["truth_role"], "source")
        self.assertEqual(m["redaction_status"], "none")  # default
        self.assertEqual(m["acl"], ["demo-team"])          # default

    def test_context_built_only_with_display_fields(self):
        base_cx = {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"}
        self.assertEqual(build_context({"context": base_cx}, NOW), [])  # display_name 없으면 빈 리스트
        rich = dict(base_cx, display_name="함정", boundary_summary="...")
        objs = build_context({"context": rich}, NOW)
        self.assertEqual(objs[0]["id"], "context.ctx")
        self.assertEqual(objs[0]["kind"], "DomainContext")
        self.assertEqual(objs[0]["truth_role"], "domain")


class BuildGlossaryTest(unittest.TestCase):
    def test_builds_reviewed_term_with_evidence(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc", "now": NOW, "repo": "demoapp"},
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

    def test_glossary_carries_synonyms_and_aliases(self):
        notes = {
            "context": {"key": "ctx", "commit": "a"},
            "glossary": [{"key": "tok", "term": "CLEAR_PASS_TICKET_RECOVER",
                          "definition": "토큰 환불 복구 요청 타입",
                          "evidence_refs": ["evref.ctx.x"],
                          "synonyms": ["클리어 패스 티켓 복구", "토큰 환불 복구"],
                          "aliases": ["CPTR"]}],
        }
        objs = build_glossary_terms(notes, NOW)
        self.assertEqual(objs[0]["synonyms"], ["클리어 패스 티켓 복구", "토큰 환불 복구"])
        self.assertEqual(objs[0]["aliases"], ["CPTR"])

    def test_glossary_synonyms_default_empty(self):
        notes = {
            "context": {"key": "ctx", "commit": "a"},
            "glossary": [{"key": "t", "term": "T", "definition": "d",
                          "evidence_refs": ["evref.ctx.x"]}],
        }
        objs = build_glossary_terms(notes, NOW)
        self.assertEqual(objs[0]["synonyms"], [])
        self.assertEqual(objs[0]["aliases"], [])


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

    def test_glossary_synonyms_union_allowed(self):
        store = _store({"id": "g.ctx.x", "kind": "GlossaryTerm", "updated_at": T0,
                        "synonyms": ["기존"], "aliases": [], "status": "reviewed",
                        "truth_role": "domain", "title": "t", "context_id": "context.ctx",
                        "term": "용어", "definition": "정의", "evidence_refs": ["evref.ctx.x"],
                        "schema_version": "0.1", "poc_priority": "P2",
                        "created_at": T0, "tags": ["ctx"]})
        notes = {"updates": [{"id": "g.ctx.x", "expected_updated_at": T0,
                              "union": {"synonyms": ["추가"], "aliases": ["AKA"]}}]}
        objs, diffs, errors = apply_updates(notes, store, NOW)
        self.assertEqual(errors, [])
        self.assertEqual(objs[0]["synonyms"], ["기존", "추가"])
        self.assertEqual(objs[0]["aliases"], ["AKA"])


from project_brain.assembly import validate_notes, build


def _ref_objs(ctx="ctx"):
    """_mapping()이 가리키는 참조 대상을 닫는 최소 객체들 — build의 lint를 통과시키려면
    evidence_refs(evref)·context_id(context)가 store에 실존해야 한다."""
    manifest = {"id": f"manifest.{ctx}.src", "kind": "EvidenceManifest", "status": "reviewed",
                "truth_role": "source", "title": "src", "source_type": "session",
                "locator": "...", "captured_at": T0, "captured_by": "user-statement",
                "sensitivity": "internal", "acl": ["demo-team"], "redaction_status": "approved",
                "schema_version": "0.1", "poc_priority": "P2",
                "created_at": T0, "updated_at": T0, "tags": [ctx], "evidence_refs": []}
    evref = {"id": f"evref.{ctx}.x", "kind": "EvidenceRef", "status": "reviewed",
             "truth_role": "reference", "title": "e", "evidence_manifest_id": f"manifest.{ctx}.src",
             "ref_type": "session_turn", "locator": "...", "summary": "s",
             "schema_version": "0.1", "poc_priority": "P2",
             "created_at": T0, "updated_at": T0, "tags": [ctx], "evidence_refs": []}
    context = {"id": f"context.{ctx}", "kind": "DomainContext", "status": "reviewed",
               "truth_role": "domain", "title": "C", "context_key": ctx,
               "project_id": "demoapp", "display_name": "C", "boundary_summary": "b",
               "in_scope": [], "out_of_scope": [],
               "injection_profile": {"default_audience": "coding-agent"},
               "glossary_term_ids": [], "schema_version": "0.1", "poc_priority": "P2",
               "created_at": T0, "updated_at": T0, "tags": [ctx], "evidence_refs": []}
    return [manifest, evref, context]


class ValidateNotesTest(unittest.TestCase):
    def test_unknown_section_fails(self):
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "bogus_section": []})
        self.assertTrue(any("bogus_section" in e for e in errors))

    def test_missing_context_fails(self):
        errors = validate_notes({"glossary": []})
        self.assertTrue(any("context" in e for e in errors))

    def test_remove_operation_rejected(self):
        # set/union 외 연산 키(remove 등)는 미지원 — 거부
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "updates": [{"id": "x", "expected_updated_at": NOW,
                                              "remove": {"caveats": ["old"]}}]})
        self.assertTrue(any("remove" in e for e in errors))

    def test_section_wrong_type_rejected(self):
        # glossary는 list여야 — dict면 실패
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "glossary": {"not": "a list"}})
        self.assertTrue(any("glossary" in e for e in errors))

    def test_item_missing_required_field_rejected(self):
        # glossary 항목에 definition 누락 → 1층에서 잡음
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "glossary": [{"key": "hit", "term": "hit"}]})
        self.assertTrue(any("definition" in e for e in errors))

    def test_glossary_empty_evidence_rejected(self):
        # reviewed로 만들어질 glossary가 빈 evidence_refs면 1층에서 잡힌다(2층 schema 전에)
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "glossary": [{"key": "h", "term": "h", "definition": "d",
                                               "evidence_refs": []}]})
        self.assertTrue(any("evidence_refs" in e for e in errors))

    def test_code_anchor_without_line_numbers_accepted(self):
        # B안: code_anchor의 line_start/line_end는 선택값 — 없어도 1층 검증 통과
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "code_anchors": [{"key": "k", "path": "Foo.cpp",
                                                   "symbol": "Foo::bar",
                                                   "manifest": "manifest.c.code"}]})
        self.assertEqual(errors, [])


class BuildIntegrationTest(unittest.TestCase):
    def test_build_new_objects_bundle(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc", "now": NOW, "repo": "demoapp"},
            "sources": [{"id": "manifest.ctx.code-v2", "source_type": "code_search",
                         "title": "코드", "locator": "...", "captured_by": "agent"}],
            "code_anchors": [{"key": "hit-hook", "path": "D.h", "symbol": "S",
                              "line_start": 1, "line_end": 1, "quote": "q",
                              "manifest": "manifest.ctx.code-v2"}],
            "glossary": [{"key": "hit", "term": "hit", "definition": "정의",
                          "evidence_refs": ["evref.ctx.hit-hook"]}],
        }
        result = build(notes, _store(), NOW)
        self.assertEqual(result["errors"], [])
        ids = {o["id"] for o in result["objects"]}
        self.assertIn("g.ctx.hit", ids)
        self.assertIn("code.ctx.hit-hook", ids)
        self.assertIn("evref.ctx.hit-hook", ids)

    def test_build_warns_isolated_new_leaf_non_blocking(self):
        # C8: 이번 묶음 신규 잎 중 인바운드 0(아무도 안 가리킴)을 비차단 warnings로 보고한다.
        # 매핑 없이 적재된 GlossaryTerm·CodeLocator는 고립 잎 → 경고. evref는 term의
        # evidence_refs가 가리키므로 경고 아님(묶음 내 참조). 차단 아님(errors 비어야 함 —
        # candidate 일시 고립은 정상). 점검 잎 kind·역인덱스는 C1(graph.py)과 공유.
        notes = {
            "context": {"key": "ctx", "commit": "abc", "now": NOW, "repo": "demoapp"},
            "sources": [{"id": "manifest.ctx.code-v2", "source_type": "code_search",
                         "title": "코드", "locator": "...", "captured_by": "agent"}],
            "code_anchors": [{"key": "hit-hook", "path": "D.h", "symbol": "S",
                              "line_start": 1, "line_end": 1, "quote": "q",
                              "manifest": "manifest.ctx.code-v2"}],
            "glossary": [{"key": "hit", "term": "hit", "definition": "정의",
                          "evidence_refs": ["evref.ctx.hit-hook"]}],
        }
        result = build(notes, _store(), NOW)
        self.assertEqual(result["errors"], [])  # 비차단
        warned = " ".join(result["warnings"])
        self.assertIn("g.ctx.hit", warned)             # 고립 GlossaryTerm → 경고
        self.assertIn("code.ctx.hit-hook", warned)     # 고립 CodeLocator → 경고
        self.assertNotIn("evref.ctx.hit-hook", warned)  # term이 가리킴 → 고립 아님

    def test_build_dangling_ref_caught(self):
        # glossary가 없는 evref를 가리키면 2층(dangling)이 잡는다
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"},
                 "glossary": [{"key": "x", "term": "x", "definition": "d",
                               "evidence_refs": ["evref.ctx.nonexistent"]}]}
        result = build(notes, _store(), NOW)
        self.assertTrue(result["errors"])

    def test_build_evref_dangling_manifest_caught(self):
        # extra_objects로 들어온 EvidenceRef가 없는 manifest를 가리키면 build 2층이 잡는다
        # (lint는 EvidenceRef→manifest를 안 보므로 build가 직접 검사)
        evref = {"id": "evref.ctx.x", "kind": "EvidenceRef", "status": "reviewed",
                 "truth_role": "reference", "title": "e",
                 "evidence_manifest_id": "manifest.ctx.missing", "ref_type": "session_turn",
                 "locator": "...", "summary": "s", "schema_version": "0.1", "poc_priority": "P2",
                 "created_at": T0, "updated_at": T0, "tags": ["ctx"], "evidence_refs": []}
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"},
                 "extra_objects": [evref]}
        result = build(notes, _store(), NOW)
        self.assertTrue(any("evidence_manifest_id" in e for e in result["errors"]))

    def test_build_union_target_missing_caught(self):
        # DomainContext.glossary_term_ids union 대상이 store·묶음 어디에도 없으면 build가 잡는다
        # (lint는 DomainMapping 링크만 봐서 DomainContext union은 사각지대)
        store = _store(*_ref_objs())  # context.ctx 포함
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"},
                 "updates": [{"id": "context.ctx", "expected_updated_at": T0,
                              "union": {"glossary_term_ids": ["g.ctx.nonexistent"]}}]}
        result = build(notes, store, NOW)
        self.assertTrue(any("g.ctx.nonexistent" in e for e in result["errors"]))

    def test_build_emits_preconditions_for_updates(self):
        # title(비-claim) set + 참조 닫힌 픽스처 → errors 없이 preconditions 방출
        store = _store(_mapping(glossary_term_ids=[]), *_ref_objs())
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"},
                 "updates": [{"id": "mapping.ctx.hook", "expected_updated_at": T0,
                              "set": {"title": "새 제목"}}]}
        result = build(notes, store, NOW)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["preconditions"], {"mapping.ctx.hook": T0})


class BuildDecisionsTest(unittest.TestCase):
    def _notes(self):
        return {
            "context": {"key": "ctx", "commit": "abc123", "now": NOW, "repo": "bb2_client"},
            "decisions": [
                {
                    "key": "v55-special-color",
                    "decision_type": "improvement",
                    "title": "스페셜버블 색상도 셀렉 체크",
                    "summary": "스페셜버블 색상 포함 요약",
                    "decision": "설정이 켜지면 스페셜버블 내부 색상을 체크 타입으로 삼는다.",
                    "spec_reflected": "not_applicable",
                    "evidence": [
                        {"type": "commit", "ref": "763086bc41", "summary": "셀렉로직 개선 commit"},
                        {"type": "jira", "ref": "3869",
                         "locator": "https://jira.example/browse/X-3869", "summary": "버닝볼 이슈"},
                    ],
                    "affects": ["special-color-select", "enable-filter"],
                },
            ],
        }

    def test_decision_object_required_fields(self):
        objs = build_decisions(self._notes(), NOW)
        dec = next(o for o in objs if o["kind"] == "DecisionRecord")
        self.assertEqual(dec["id"], "decision.ctx.v55-special-color")
        self.assertEqual(dec["status"], "reviewed")
        self.assertEqual(dec["truth_role"], "event")
        self.assertEqual(dec["decision_type"], "improvement")
        self.assertEqual(dec["spec_reflected"], "not_applicable")
        self.assertEqual(dec["affected_context_ids"], ["context.ctx"])
        self.assertEqual(dec["affected_mapping_ids"],
                         ["mapping.ctx.special-color-select", "mapping.ctx.enable-filter"])
        self.assertEqual(dec["source_object_ids"],
                         ["evref.ctx.commit-763086bc41", "evref.ctx.jira-3869"])
        self.assertEqual(dec["evidence_refs"], dec["source_object_ids"])
        self.assertEqual(dec["created_at"], NOW)
        self.assertEqual(dec["updated_at"], NOW)

    def test_evref_types_and_locators(self):
        objs = build_decisions(self._notes(), NOW)
        evs = {o["id"]: o for o in objs if o["kind"] == "EvidenceRef"}
        commit_ev = evs["evref.ctx.commit-763086bc41"]
        self.assertEqual(commit_ev["ref_type"], "commit")
        self.assertEqual(commit_ev["locator"], {"repo": "bb2_client", "sha": "763086bc41"})
        self.assertEqual(commit_ev["evidence_manifest_id"], "manifest.ctx.commit")
        self.assertEqual(commit_ev["summary"], "셀렉로직 개선 commit")
        jira_ev = evs["evref.ctx.jira-3869"]
        self.assertEqual(jira_ev["ref_type"], "jira_issue")
        self.assertEqual(jira_ev["locator"], "https://jira.example/browse/X-3869")
        self.assertEqual(jira_ev["evidence_manifest_id"], "manifest.ctx.jira")

    def test_shared_evref_deduped(self):
        notes = self._notes()
        notes["decisions"].append({
            "key": "v56-followup", "decision_type": "improvement",
            "title": "후속", "summary": "같은 커밋 공유", "decision": "...",
            "evidence": [{"type": "commit", "ref": "763086bc41", "summary": "셀렉로직 개선 commit"}],
            "affects": ["enable-filter"],
        })
        objs = build_decisions(notes, NOW)
        commit_evs = [o for o in objs if o.get("id") == "evref.ctx.commit-763086bc41"]
        self.assertEqual(len(commit_evs), 1)  # 두 결정이 공유해도 evref는 1개

    def test_validate_notes_jira_evidence_requires_locator(self):
        from project_brain.assembly import validate_notes
        notes = self._notes()
        del notes["decisions"][0]["evidence"][1]["locator"]  # jira evidence의 locator 제거
        errors = validate_notes(notes)
        self.assertTrue(any("locator" in e for e in errors),
                        f"locator 누락을 1층에서 막아야 함: {errors}")


class BuildWithDecisionsTest(unittest.TestCase):
    def _notes(self):
        return {
            "context": {"key": "ctx", "commit": "abc123", "now": NOW, "repo": "bb2_client",
                        "display_name": "테스트 컨텍스트", "boundary_summary": "경계",
                        "in_scope": ["x"], "out_of_scope": ["y"], "glossary_term_ids": []},
            "sources": [
                {"id": "manifest.ctx.code", "source_type": "code_search",
                 "title": "코드", "locator": "repo@dev"},
                {"id": "manifest.ctx.commit", "source_type": "commit",
                 "title": "커밋 이력", "locator": "bb2_client@develop"},
            ],
            # 매핑이 reviewed로 만들어지므로 evidence_refs가 비면 안 됨(schema.py:217).
            # code_anchor로 CodeLocator+EvidenceRef를 만들어 매핑이 그 evref를 갖게 한다.
            "code_anchors": [
                {"key": "filter-fn", "path": "BallGenerator.cpp",
                 "symbol": "_getEnableGenerateType", "manifest": "manifest.ctx.code",
                 "quote": "// 셀렉 후보 자격 판정"},
            ],
            "mappings": [
                {"key": "enable-filter", "canonical_summary": "셀렉 후보 필터",
                 "meaning": "후보 자격 판정", "boundary": "노말타입만",
                 "caveats": ["history_coverage=partial"],
                 "glossary_keys": [], "code_evref_keys": ["filter-fn"]},
            ],
            "decisions": [
                {"key": "skull-exclude", "decision_type": "qa_issue",
                 "title": "해골투구 셀렉 제외", "summary": "해골 상태 색상 숨김",
                 "decision": "투구 착용 시 후보 제외.",
                 "evidence": [{"type": "commit", "ref": "900b6ce82d", "summary": "해골 이슈 fix"}],
                 "affects": ["enable-filter"]},
            ],
        }

    def test_build_includes_decision_and_backfills_mapping(self):
        from project_brain.store import BrainStore
        result = build(self._notes(), BrainStore({}), NOW)
        self.assertEqual(result["errors"], [])  # lint 8c 통과 = 양방향 성립
        by_id = {o["id"]: o for o in result["objects"]}
        self.assertIn("decision.ctx.skull-exclude", by_id)
        mapping = by_id["mapping.ctx.enable-filter"]
        self.assertIn("decision.ctx.skull-exclude", mapping["decision_record_ids"])

    def test_rebuild_is_idempotent(self):
        from project_brain.store import BrainStore
        a = build(self._notes(), BrainStore({}), NOW)["objects"]
        b = build(self._notes(), BrainStore({}), NOW)["objects"]
        self.assertEqual(a, b)  # 같은 now → 완전 동일(churn 0)
