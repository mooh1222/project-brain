import unittest

import pytest
from project_brain.coverage import CoverageError, normalize_coverage
from project_brain.assembly import derive_id, build_glossary_terms, build_code_evidence, resolve_refs
from project_brain.assembly import build_mappings
from project_brain.assembly import build_manifests, build_context
from project_brain.assembly import apply_updates
from project_brain.assembly import build_decisions, validate_assembled_inputs
from project_brain.store import BrainStore

NOW = "2026-06-16T00:00:00Z"


def _assembled_coverage_fixture():
    return {
        "version": 1,
        "mode": "assembled",
        "verify_groups": {"names": ["g1"]},
        "context": {"key": "ctx", "mode": "create"},
        "sections": {
            "sources": {"ids": ["manifest.ctx.code"]},
            "glossary": {"keys": ["term-one"]},
            "code_anchors": {"keys": ["anchor-one"]},
            "mappings": {"keys": ["mapping-one"]},
            "decisions": {"items": [{
                "key": "decision-one",
                "evidence": [{"type": "commit", "ref": "abc"}],
            }]},
            "refs": {"items": [{
                "category": "glossary",
                "alias": "shared",
                "id": "g.ctx.existing",
                "expect": {"kind": "GlossaryTerm", "meta": {"rank": 1}},
            }]},
            "updates": {"ids": ["mapping.ctx.old"]},
            "extra_objects": {"objects": [{
                "id": "ledger.ctx.extra", "kind": "EventLedgerRecord",
            }]},
        },
        "expected_objects": [
            {"id": "code.ctx.anchor-one", "kind": "CodeLocator"},
            {"id": "context.ctx", "kind": "DomainContext"},
            {"id": "decision.ctx.decision-one", "kind": "DecisionRecord"},
            {"id": "evref.ctx.anchor-one", "kind": "EvidenceRef"},
            {"id": "evref.ctx.commit-abc", "kind": "EvidenceRef"},
            {"id": "g.ctx.term-one", "kind": "GlossaryTerm"},
            {"id": "ledger.ctx.extra", "kind": "EventLedgerRecord"},
            {"id": "manifest.ctx.code", "kind": "EvidenceManifest"},
            {"id": "mapping.ctx.mapping-one", "kind": "DomainMapping"},
            {"id": "mapping.ctx.old", "kind": "DomainMapping"},
        ],
    }


def _complete_verify_fixture():
    return {"groups": [{"group": "g1"}]}


def _complete_notes_fixture():
    return {
        "context": {
            "key": "ctx", "commit": "abc", "repo": "demoapp",
            "display_name": "컨텍스트", "boundary_summary": "경계",
            "in_scope": [], "out_of_scope": [], "glossary_term_ids": [],
            "claim_status": "reviewed",
        },
        "sources": [{"id": "manifest.ctx.code"}],
        "glossary": [{"key": "term-one"}],
        "code_anchors": [{"key": "anchor-one"}],
        "mappings": [{"key": "mapping-one"}],
        "decisions": [{
            "key": "decision-one",
            "evidence": [{
                "type": "commit", "ref": "abc", "summary": "커밋 근거",
            }],
        }],
        "refs": {"glossary": {"shared": {
            "id": "g.ctx.existing",
            "expect": {"kind": "GlossaryTerm", "meta": {"rank": 1}},
        }}},
        "updates": [{"id": "mapping.ctx.old"}],
        "extra_objects": [{"id": "ledger.ctx.extra", "kind": "EventLedgerRecord"}],
    }


def _remove_identity(notes, section, identity):
    field = "id" if section in {"sources", "updates"} else "key"
    notes[section] = [item for item in notes[section] if item[field] != identity]


@pytest.mark.parametrize(
    ("section", "identity"),
    [
        ("sources", "manifest.ctx.code"),
        ("glossary", "term-one"),
        ("code_anchors", "anchor-one"),
        ("mappings", "mapping-one"),
        ("updates", "mapping.ctx.old"),
    ],
)
def test_assemble_rejects_one_missing_declared_item(section, identity):
    notes = _complete_notes_fixture()
    _remove_identity(notes, section, identity)

    with pytest.raises(CoverageError) as exc:
        validate_assembled_inputs(
            binding=normalize_coverage(_assembled_coverage_fixture()),
            verify_data=_complete_verify_fixture(),
            notes=notes,
            store=BrainStore({}),
        )

    assert exc.value.code == "coverage_notes_mismatch"


@pytest.mark.parametrize("field", ["category", "alias", "id", "expect"])
def test_assemble_compares_every_ref_identity_field(field):
    notes = _complete_notes_fixture()
    ref = notes["refs"]["glossary"]["shared"]
    if field == "category":
        notes["refs"] = {"mapping": notes["refs"].pop("glossary")}
    elif field == "alias":
        notes["refs"]["glossary"]["renamed"] = notes["refs"]["glossary"].pop("shared")
    elif field == "id":
        ref["id"] = "g.ctx.other"
    else:
        ref["expect"] = {"kind": "GlossaryTerm", "meta": {"rank": 2}}

    with pytest.raises(CoverageError) as exc:
        validate_assembled_inputs(
            binding=normalize_coverage(_assembled_coverage_fixture()),
            verify_data=_complete_verify_fixture(),
            notes=notes,
            store=BrainStore({}),
        )
    assert exc.value.code == "coverage_notes_mismatch"


@pytest.mark.parametrize("field", ["key", "evidence"])
def test_assemble_compares_decision_key_and_evidence(field):
    notes = _complete_notes_fixture()
    if field == "key":
        notes["decisions"][0]["key"] = "decision-other"
    else:
        notes["decisions"][0]["evidence"][0]["ref"] = "def"

    with pytest.raises(CoverageError) as exc:
        validate_assembled_inputs(
            binding=normalize_coverage(_assembled_coverage_fixture()),
            verify_data=_complete_verify_fixture(),
            notes=notes,
            store=BrainStore({}),
        )
    assert exc.value.code == "coverage_notes_mismatch"


@pytest.mark.parametrize("field", ["id", "kind"])
def test_assemble_compares_extra_object_id_and_kind(field):
    notes = _complete_notes_fixture()
    notes["extra_objects"][0][field] = (
        "ledger.ctx.other" if field == "id" else "TemporalFact"
    )
    with pytest.raises(CoverageError) as exc:
        validate_assembled_inputs(
            binding=normalize_coverage(_assembled_coverage_fixture()),
            verify_data=_complete_verify_fixture(),
            notes=notes,
            store=BrainStore({}),
        )
    assert exc.value.code == "coverage_notes_mismatch"


def test_assemble_rejects_unexpected_notes_item():
    notes = _complete_notes_fixture()
    notes["sources"].append({"id": "manifest.ctx.extra"})
    with pytest.raises(CoverageError) as exc:
        validate_assembled_inputs(
            binding=normalize_coverage(_assembled_coverage_fixture()),
            verify_data=_complete_verify_fixture(),
            notes=notes,
            store=BrainStore({}),
        )
    assert exc.value.code == "coverage_notes_mismatch"


def test_assemble_does_not_filter_malformed_unexpected_item():
    coverage = _assembled_coverage_fixture()
    coverage["sections"]["glossary"] = {
        "keys": [], "empty_reason": "용어 없음",
    }
    notes = _complete_notes_fixture()
    notes["glossary"] = [42]

    with pytest.raises(CoverageError) as exc:
        validate_assembled_inputs(
            binding=normalize_coverage(coverage),
            verify_data=_complete_verify_fixture(),
            notes=notes,
            store=BrainStore({}),
        )

    assert exc.value.code == "coverage_notes_mismatch"


@pytest.mark.parametrize(
    ("section", "malformed"),
    [
        ("decisions", {"not": "a list"}),
        ("refs", ["not", "an", "object"]),
    ],
)
def test_assemble_rejects_malformed_empty_section(section, malformed):
    coverage = _assembled_coverage_fixture()
    list_field = "items"
    coverage["sections"][section] = {
        list_field: [], "empty_reason": f"{section} 없음",
    }
    notes = _complete_notes_fixture()
    notes[section] = malformed

    with pytest.raises(CoverageError) as exc:
        validate_assembled_inputs(
            binding=normalize_coverage(coverage),
            verify_data=_complete_verify_fixture(),
            notes=notes,
            store=BrainStore({}),
        )

    assert exc.value.code == "coverage_notes_mismatch"


def test_assemble_rejects_malformed_verify_group_when_none_declared():
    coverage = _assembled_coverage_fixture()
    coverage["verify_groups"] = {
        "names": [], "empty_reason": "verify group 없음",
    }

    with pytest.raises(CoverageError) as exc:
        validate_assembled_inputs(
            binding=normalize_coverage(coverage),
            verify_data={"groups": [None]},
            notes=_complete_notes_fixture(),
            store=BrainStore({}),
        )

    assert exc.value.code == "coverage_notes_mismatch"


class DeriveIdTest(unittest.TestCase):
    def test_glossary_id(self):
        self.assertEqual(derive_id("GlossaryTerm", "trap-bubble-system", "hit"),
                         "g.trap-bubble-system.hit")

    def test_mapping_id(self):
        self.assertEqual(derive_id("DomainMapping", "ctx", "k"), "mapping.ctx.k")

    def test_code_and_evref_id(self):
        self.assertEqual(derive_id("CodeLocator", "ctx", "a"), "code.ctx.a")
        self.assertEqual(derive_id("EvidenceRef", "ctx", "a"), "evref.ctx.a")

    def test_noncanonical_key_is_rejected(self):
        with self.assertRaises(ValueError):
            derive_id("DomainMapping", "ctx", "bad_key")


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
        self.assertEqual(loc["verified_quote"], "virtual void _doTrapOnPop(...){};")
        self.assertNotIn("verified_at", loc)
        self.assertEqual(loc["title"], "TrapObject::_doTrapOnPop")
        self.assertEqual(ev["title"], "TrapObject::_doTrapOnPop")
        self.assertNotIn("line_start", loc)
        self.assertNotIn("line_end", loc)
        self.assertEqual(ev["id"], "evref.ctx.hit-hook")
        self.assertEqual(ev["evidence_manifest_id"], "manifest.ctx.code-v2")
        self.assertEqual(ev["ref_type"], "code_locator")
        self.assertEqual(ev["locator"], {"code_locator_id": "code.ctx.hit-hook"})

    def test_anchor_title_is_symbol_not_truncated_quote(self):
        """title은 symbol이다 — 잘린 인용은 설명처럼 읽히지만 설명이 아니다.

        symbol은 코드에서 파생돼 항상 참이고, 답변 라벨(search.py의 linked.code_locators)에
        실리는 유일한 사람 읽을 값이다. 사람이 새로 쓴 문장은 넣지 않는다 — 읽는 쪽이
        진위를 대조할 방법이 없다."""
        long_quote = "if (pBubble->getBubbleType() == BUBBLE_TYPE::kSpecial_Kamehameha) { " + "x" * 200
        notes = {
            "context": {"key": "ctx", "commit": "abc123", "now": NOW, "repo": "demoapp"},
            "code_anchors": [{"key": "beam-check", "path": "Foo.cpp",
                              "symbol": "Foo::isKamehameha", "quote": long_quote,
                              "verified_at": NOW, "manifest": "manifest.ctx.code-v2"}],
        }
        kinds = {o["kind"]: o for o in build_code_evidence(notes, NOW)}
        self.assertEqual(kinds["CodeLocator"]["title"], "Foo::isKamehameha")
        self.assertEqual(kinds["EvidenceRef"]["title"], "Foo::isKamehameha")
        # 인용 원문은 verified_quote와 evref.summary에 그대로 남는다
        self.assertEqual(kinds["CodeLocator"]["verified_quote"], long_quote)
        self.assertEqual(kinds["EvidenceRef"]["summary"], long_quote[:500])

    def test_notes_cannot_inject_anchor_title(self):
        """노트가 준 title은 무시한다 — 사람이 쓴 라벨을 넣는 입구를 만들지 않는다."""
        notes = {
            "context": {"key": "ctx", "commit": "abc123", "now": NOW, "repo": "demoapp"},
            "code_anchors": [{"key": "k", "path": "Foo.cpp", "symbol": "Foo::bar",
                              "title": "사람이 쓴 그럴듯한 설명", "quote": "void bar();",
                              "verified_at": NOW, "manifest": "manifest.ctx.code-v2"}],
        }
        kinds = {o["kind"]: o for o in build_code_evidence(notes, NOW)}
        self.assertEqual(kinds["CodeLocator"]["title"], "Foo::bar")

    def test_anchor_without_line_numbers(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc123", "now": NOW, "repo": "demoapp"},
            "code_anchors": [{"key": "no-line", "path": "Foo.cpp", "symbol": "Foo::bar",
                              "quote": "void bar();",
                              "manifest": "manifest.ctx.code-v2"}],
        }
        objs = build_code_evidence(notes, NOW)
        kinds = {o["kind"]: o for o in objs}
        loc, ev = kinds["CodeLocator"], kinds["EvidenceRef"]
        self.assertNotIn("line_start", loc)
        self.assertNotIn("line_end", loc)
        self.assertEqual(ev["locator"], {"code_locator_id": "code.ctx.no-line"})


def _store(*objs):
    return BrainStore({o["id"]: o for o in objs})


def _context(ctx="ctx"):
    return build_context(
        {
            "context": {
                "key": ctx,
                "repo": "demoapp",
                "display_name": "합성 컨텍스트",
                "boundary_summary": "합성 테스트 경계",
            },
        },
        NOW,
    )[0]


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
        self.assertEqual(m["context_id"], "context.ctx")
        self.assertEqual(sorted(m["glossary_term_ids"]),
                         ["g.ctx.do-trap-on-near-bubble-pop", "g.ctx.hit"])
        self.assertEqual(m["code_locator_ids"], ["code.ctx.hit-hook"])
        self.assertEqual(m["evidence_refs"], ["evref.ctx.hit-hook"])
        self.assertEqual(m["caveats"], ["history_coverage=unsearched"])


class BuildManifestsContextTest(unittest.TestCase):
    def test_source_becomes_manifest(self):
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"},
                 "sources": [{"id": "manifest.ctx.s", "source_type": "session",
                              "title": "T", "locator": "...", "captured_by": "user-statement",
                              "captured_at": NOW, "acl": ["team"]}]}
        objs = build_manifests(notes, NOW)
        self.assertEqual(len(objs), 1)
        m = objs[0]
        self.assertEqual(m["id"], "manifest.ctx.s")
        self.assertEqual(m["kind"], "EvidenceManifest")
        self.assertEqual(m["truth_role"], "source")
        self.assertNotIn("redaction_status", m)  # 미지정은 키 생략 → ingest에서 schema가 거부
        self.assertEqual(m["acl"], ["team"])
        self.assertEqual(m["captured_at"], NOW)

    def test_source_redaction_status_passes_through(self):
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"},
                 "sources": [{"id": "manifest.ctx.s", "source_type": "session",
                              "title": "T", "locator": "...", "captured_by": "user-statement",
                              "captured_at": NOW, "acl": ["team"],
                              "redaction_status": "approved"}]}
        m = build_manifests(notes, NOW)[0]
        self.assertEqual(m["redaction_status"], "approved")

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


class AssemblyClaimContractTest(unittest.TestCase):
    def _notes(self, *, claim_status="reviewed"):
        return {
            "context": {"key": "ctx", "commit": "abc", "claim_status": claim_status,
                        "display_name": "Context", "boundary_summary": "boundary"},
            "sources": [{"id": "manifest.ctx.code", "source_type": "code_search",
                         "title": "code", "locator": "repo@abc", "captured_at": NOW,
                         "acl": ["team"], "redaction_status": "approved"}],
            "code_anchors": [{"key": "anchor", "path": "a.cpp", "symbol": "run",
                              "manifest": "manifest.ctx.code", "quote": "\tfirst();\n\tsecond();",
                              }],
            "glossary": [{"key": "term", "term": "Term", "definition": "definition",
                          "evidence_refs": ["evref.ctx.anchor"]}],
            "mappings": [{"key": "mapping", "canonical_summary": "summary",
                          "meaning": "meaning", "boundary": "boundary",
                          "glossary_keys": ["term"], "code_evref_keys": ["anchor"]}],
            "decisions": [{"key": "decision", "decision_type": "qa_issue", "title": "title",
                           "summary": "summary", "decision": "decision", "evidence": [],
                           "affects": ["mapping"]}],
        }

    def test_context_claim_status_defaults_to_reviewed(self):
        notes = self._notes()
        del notes["context"]["claim_status"]
        result = build(notes, BrainStore({}), NOW)
        self.assertEqual(result["errors"], [])
        claims = [o for o in result["objects"]
                  if o["kind"] in {"GlossaryTerm", "DomainMapping", "DecisionRecord"}]
        self.assertEqual({o["status"] for o in claims}, {"reviewed"})

    def test_context_candidate_marks_claims_but_not_supporting_evidence(self):
        notes = self._notes(claim_status="candidate")
        notes["glossary"][0]["candidate"] = {
            "candidate_state": "ready_for_review", "candidate_source": "code",
        }
        result = build(notes, BrainStore({}), NOW)
        self.assertEqual(result["errors"], [])
        by_id = {o["id"]: o for o in result["objects"]}
        self.assertEqual(by_id["g.ctx.term"]["status"], "candidate")
        self.assertEqual(by_id["mapping.ctx.mapping"]["status"], "candidate")
        self.assertEqual(by_id["decision.ctx.decision"]["status"], "candidate")
        for oid in ("manifest.ctx.code", "code.ctx.anchor", "evref.ctx.anchor"):
            self.assertEqual(by_id[oid]["status"], "reviewed")

    def test_item_status_overrides_context_for_each_claim_kind(self):
        notes = self._notes(claim_status="candidate")
        notes["glossary"][0].update(status="reviewed")
        notes["mappings"][0].update(status="reviewed")
        notes["decisions"][0].update(status="reviewed")
        result = build(notes, BrainStore({}), NOW)
        self.assertEqual(result["errors"], [])
        self.assertEqual(
            {o["id"]: o["status"] for o in result["objects"]
             if o["kind"] in {"GlossaryTerm", "DomainMapping", "DecisionRecord"}},
            {"g.ctx.term": "reviewed", "mapping.ctx.mapping": "reviewed",
             "decision.ctx.decision": "reviewed"},
        )

    def test_candidate_glossary_requires_complete_established_metadata(self):
        notes = self._notes(claim_status="candidate")
        notes["glossary"][0]["candidate"] = {"candidate_state": "ready_for_review"}
        result = build(notes, BrainStore({}), NOW)
        self.assertTrue(any("candidate_source" in error for error in result["errors"]))

    def test_candidate_glossary_accepts_complete_established_metadata(self):
        notes = self._notes(claim_status="candidate")
        notes["glossary"][0]["candidate"] = {
            "candidate_state": "ready_for_review", "candidate_source": "code",
        }
        result = build(notes, BrainStore({}), NOW)
        self.assertEqual(result["errors"], [])

    def test_source_acl_and_capture_time_are_required_before_build(self):
        notes = self._notes()
        notes["sources"][0]["acl"] = []
        notes["sources"][0]["captured_at"] = ""
        errors = validate_notes(notes)
        self.assertTrue(any("acl" in error and "비어" in error for error in errors))
        self.assertTrue(any("captured_at" in error and "비어" in error for error in errors))

    def test_code_anchor_quote_is_required_before_build(self):
        notes = self._notes()
        notes["code_anchors"][0]["quote"] = ""
        errors = validate_notes(notes)
        self.assertTrue(any("quote" in error and "비어" in error for error in errors))

    def test_code_anchor_symbol_is_required_before_build(self):
        """symbol이 비면 title도 비고 색인 표면이 path 하나로 쪼그라든다 — 입구에서 막는다."""
        notes = self._notes()
        notes["code_anchors"][0]["symbol"] = "  "
        errors = validate_notes(notes)
        self.assertTrue(any("symbol" in error and "비어" in error for error in errors))

    def test_locator_preserves_exact_multiline_tab_verified_quote(self):
        result = build(self._notes(), BrainStore({}), NOW)
        self.assertEqual(result["errors"], [])
        locator = next(o for o in result["objects"] if o["kind"] == "CodeLocator")
        self.assertEqual(locator["verified_quote"], "\tfirst();\n\tsecond();")


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

    def test_anchor_title_set_update(self):
        """앵커 title 백필의 유일한 안전 통로 — extra_objects는 낙관적 잠금이 없다.

        title은 _CLAIM_FIELDS 밖이라 근거 동반이 강제되지 않는다(표시 라벨이고 의미 주장이 아니다)."""
        locator = {"id": "code.ctx.hook", "kind": "CodeLocator", "status": "reviewed",
                   "truth_role": "reference", "title": "\tif (x) { return NULL;",
                   "repo": "demoapp", "path": "Foo.cpp", "symbol": "Foo::bar",
                   "locator_source": "rg", "commit_sha": "abc123",
                   "verified_quote": "\tif (x) { return NULL;", "verified_at": T0,
                   "schema_version": "0.1", "poc_priority": "P2",
                   "created_at": T0, "updated_at": T0, "tags": ["ctx"]}
        evref = {"id": "evref.ctx.hook", "kind": "EvidenceRef", "status": "reviewed",
                 "truth_role": "reference", "title": "\tif (x) { return NULL;",
                 "evidence_manifest_id": "manifest.ctx.code", "ref_type": "code_locator",
                 "locator": {"code_locator_id": "code.ctx.hook"},
                 "summary": "\tif (x) { return NULL;",
                 "schema_version": "0.1", "poc_priority": "P2",
                 "created_at": T0, "updated_at": T0, "tags": ["ctx"]}
        for obj in (locator, evref):
            with self.subTest(kind=obj["kind"]):
                store = _store(obj)
                notes = {"updates": [{"id": obj["id"], "expected_updated_at": T0,
                                      "set": {"title": "Foo::bar"}}]}
                objs, _, errors = apply_updates(notes, store, NOW)
                self.assertEqual(errors, [])
                self.assertEqual(objs[0]["title"], "Foo::bar")
                self.assertEqual(objs[0]["verified_quote" if obj["kind"] == "CodeLocator"
                                          else "summary"], "\tif (x) { return NULL;")

    def test_anchor_path_symbol_still_not_updatable(self):
        """title만 열었다 — path·symbol·quote는 여전히 updates 밖(amend를 쓴다)."""
        locator = {"id": "code.ctx.hook", "kind": "CodeLocator", "status": "reviewed",
                   "truth_role": "reference", "title": "Foo::bar", "repo": "demoapp",
                   "path": "Foo.cpp", "symbol": "Foo::bar", "locator_source": "rg",
                   "commit_sha": "abc123", "verified_quote": "q", "verified_at": T0,
                   "schema_version": "0.1", "poc_priority": "P2",
                   "created_at": T0, "updated_at": T0, "tags": ["ctx"]}
        for field in ("path", "symbol", "verified_quote", "commit_sha"):
            with self.subTest(field=field):
                notes = {"updates": [{"id": "code.ctx.hook", "expected_updated_at": T0,
                                      "set": {field: "바뀐값"}}]}
                _, _, errors = apply_updates(notes, _store(locator), NOW)
                self.assertTrue(any("allowlist" in e.lower() for e in errors), errors)

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
    def test_duplicate_item_key_is_error(self):
        """같은 key 2개는 같은 id 객체 2개를 만들고 뒤의 것만 저장된다 — 무신호 유실이다."""
        base_items = {
            "glossary": {"key": "dup", "term": "용어", "definition": "정의",
                         "evidence_refs": ["evref.ctx.x"]},
            "code_anchors": {"key": "dup", "path": "Foo.cpp", "symbol": "Foo::bar",
                             "manifest": "manifest.ctx.code", "quote": "void bar();",
                             "verified_at": NOW},
            "mappings": {"key": "dup", "canonical_summary": "요약", "meaning": "의미",
                         "boundary": "경계"},
            "decisions": {"key": "dup", "decision_type": "spec_clarification",
                          "title": "결정", "summary": "요약", "decision": "내용"},
            "sources": {"id": "manifest.ctx.dup", "source_type": "session", "title": "제목",
                        "locator": "session://x", "captured_at": NOW, "acl": ["team"]},
        }
        for section, item in base_items.items():
            field = "id" if section == "sources" else "key"
            with self.subTest(section=section):
                notes = {"context": {"key": "ctx", "commit": "abc"},
                         section: [dict(item), dict(item)]}
                errors = validate_notes(notes)
                self.assertTrue(
                    any(f"{section}[1].{field}" in e and "중복" in e for e in errors),
                    f"{section} 중복이 안 잡힘: {errors}")

    def test_distinct_item_keys_pass(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc"},
            "code_anchors": [
                {"key": "a", "path": "Foo.cpp", "symbol": "Foo::a", "manifest": "manifest.ctx.code",
                 "quote": "void a();", "verified_at": NOW},
                {"key": "b", "path": "Foo.cpp", "symbol": "Foo::b", "manifest": "manifest.ctx.code",
                 "quote": "void b();", "verified_at": NOW},
            ],
        }
        self.assertEqual([e for e in validate_notes(notes) if "중복" in e], [])

    def test_logical_key_reference_fields_require_lists(self):
        mapping = {
            "key": "bubble-attribution",
            "canonical_summary": "요약",
            "meaning": "의미",
            "boundary": "경계",
        }
        decision = {
            "key": "bubble-attribution",
            "decision_type": "spec_clarification",
            "title": "결정",
            "summary": "요약",
            "decision": "내용",
        }
        cases = [
            ("mappings[0].glossary_keys", mapping, "glossary_keys", "term"),
            ("mappings[0].code_evref_keys", mapping, "code_evref_keys", "anchor"),
            ("mappings[0].decision_keys", mapping, "decision_keys", None),
            ("decisions[0].affects", decision, "affects", 1),
        ]

        for location, item, field, value in cases:
            with self.subTest(location=location, value=value):
                item = {**item, field: value}
                notes = {"context": {"key": "disturb-bubble-system", "commit": "abc"}}
                notes["mappings" if location.startswith("mappings") else "decisions"] = [item]

                errors = validate_notes(notes)

                self.assertTrue(any(location in e and "list여야 함" in e for e in errors))

    def test_source_key_is_not_validated_as_logical_key(self):
        notes = {
            "context": {"key": "disturb-bubble-system", "commit": "abc"},
            "sources": [{
                "id": "manifest.disturb-bubble-system.source",
                "key": "source.disturb-bubble-system.source",
                "source_type": "session",
                "title": "근거",
                "locator": "session-1",
            }],
        }

        errors = validate_notes(notes)

        self.assertFalse(any("sources[0].key" in e and "논리 key" in e for e in errors))

    def test_validate_notes_rejects_full_object_id_as_mapping_key(self):
        notes = {
            "context": {"key": "disturb-bubble-system", "commit": "abc"},
            "mappings": [{
                "key": "mapping.disturb-bubble-system.bubble-attribution",
                "canonical_summary": "요약",
                "meaning": "의미",
                "boundary": "경계",
            }],
        }
        errors = validate_notes(notes)
        self.assertTrue(any("mappings[0].key" in e and "논리 key" in e for e in errors))

    def test_validate_notes_rejects_full_object_ids_in_logical_key_fields(self):
        def context_notes():
            return {"context": {"key": "disturb-bubble-system", "commit": "abc"}}

        cases = [
            (
                "context.key",
                "context.disturb-bubble-system",
                {"context": {"key": "context.disturb-bubble-system", "commit": "abc"}},
                True,
            ),
            (
                "glossary[0].key",
                "g.disturb-bubble-system.bubble-attribution",
                {
                    **context_notes(),
                    "glossary": [{
                        "key": "g.disturb-bubble-system.bubble-attribution",
                        "term": "용어",
                        "definition": "정의",
                        "evidence_refs": ["evref.disturb-bubble-system.source"],
                    }],
                },
                True,
            ),
            (
                "decisions[0].key",
                "decision.disturb-bubble-system.bubble-attribution",
                {
                    **context_notes(),
                    "decisions": [{
                        "key": "decision.disturb-bubble-system.bubble-attribution",
                        "decision_type": "spec_clarification",
                        "title": "결정",
                        "summary": "요약",
                        "decision": "내용",
                    }],
                },
                True,
            ),
            (
                "code_anchors[0].key",
                "code.disturb-bubble-system.core-behavior--0",
                {
                    **context_notes(),
                    "code_anchors": [{
                        "key": "code.disturb-bubble-system.core-behavior--0",
                        "path": "Core.cpp",
                        "symbol": "Core::run",
                        "manifest": "manifest.disturb-bubble-system.code",
                    }],
                },
                True,
            ),
            (
                "mappings[0].glossary_keys[0]",
                "g.disturb-bubble-system.bubble-attribution",
                {
                    **context_notes(),
                    "mappings": [{
                        "key": "bubble-attribution",
                        "canonical_summary": "요약",
                        "meaning": "의미",
                        "boundary": "경계",
                        "glossary_keys": ["g.disturb-bubble-system.bubble-attribution"],
                    }],
                },
                True,
            ),
            (
                "mappings[0].code_evref_keys[0]",
                "evref.disturb-bubble-system.core-behavior--0",
                {
                    **context_notes(),
                    "mappings": [{
                        "key": "bubble-attribution",
                        "canonical_summary": "요약",
                        "meaning": "의미",
                        "boundary": "경계",
                        "code_evref_keys": ["evref.disturb-bubble-system.core-behavior--0"],
                    }],
                },
                True,
            ),
            (
                "mappings[0].decision_keys[0]",
                "decision.disturb-bubble-system.bubble-attribution",
                {
                    **context_notes(),
                    "mappings": [{
                        "key": "bubble-attribution",
                        "canonical_summary": "요약",
                        "meaning": "의미",
                        "boundary": "경계",
                        "decision_keys": ["decision.disturb-bubble-system.bubble-attribution"],
                    }],
                },
                True,
            ),
            (
                "decisions[0].affects[0]",
                "mapping.disturb-bubble-system.bubble-attribution",
                {
                    **context_notes(),
                    "decisions": [{
                        "key": "bubble-attribution",
                        "decision_type": "spec_clarification",
                        "title": "결정",
                        "summary": "요약",
                        "decision": "내용",
                        "affects": ["mapping.disturb-bubble-system.bubble-attribution"],
                    }],
                },
                True,
            ),
            (
                "code_anchors[0].key",
                "core-behavior--0",
                {
                    **context_notes(),
                    "code_anchors": [{
                        "key": "core-behavior--0",
                        "path": "Core.cpp",
                        "symbol": "Core::run",
                        "manifest": "manifest.disturb-bubble-system.code",
                    }],
                },
                False,
            ),
        ]

        for field, value, notes, should_reject in cases:
            with self.subTest(field=field, value=value):
                errors = validate_notes(notes)
                rejected = any(field in error and "논리 key" in error for error in errors)
                self.assertEqual(rejected, should_reject)

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
                                                   "manifest": "manifest.c.code",
                                                   "quote": "void bar();"}]})
        self.assertEqual(errors, [])


class BuildIntegrationTest(unittest.TestCase):
    def test_build_new_objects_bundle(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc", "now": NOW, "repo": "demoapp"},
            "sources": [{"id": "manifest.ctx.code-v2", "source_type": "code_search",
                         "title": "코드", "locator": "...", "captured_by": "agent",
                         "captured_at": NOW, "acl": ["team"], "redaction_status": "approved"}],
            "code_anchors": [{"key": "hit-hook", "path": "D.h", "symbol": "S",
                              "line_start": 1, "line_end": 1, "quote": "q",
                              "manifest": "manifest.ctx.code-v2"}],
            "glossary": [{"key": "hit", "term": "hit", "definition": "정의",
                          "evidence_refs": ["evref.ctx.hit-hook"]}],
        }
        result = build(notes, _store(_context()), NOW)
        self.assertEqual(result["errors"], [])
        ids = {o["id"] for o in result["objects"]}
        self.assertIn("g.ctx.hit", ids)
        self.assertIn("code.ctx.hit-hook", ids)
        self.assertIn("evref.ctx.hit-hook", ids)

    def test_build_warns_isolated_new_leaf_non_blocking(self):
        # C8: 이번 묶음 신규 잎 중 인바운드 0(아무도 안 가리킴)을 비차단 warnings로 보고한다.
        # 매핑 없이 적재된 GlossaryTerm은 고립 잎 → 경고. evref는 term의 evidence_refs가,
        # locator는 evref.locator.code_locator_id가 가리키므로 둘 다 경고 아님(묶음 내 참조).
        # 차단 아님(errors 비어야 함 — candidate 일시 고립은 정상). 점검 잎 kind·역인덱스는
        # C1(graph.py)과 공유.
        notes = {
            "context": {"key": "ctx", "commit": "abc", "now": NOW, "repo": "demoapp"},
            "sources": [{"id": "manifest.ctx.code-v2", "source_type": "code_search",
                         "title": "코드", "locator": "...", "captured_by": "agent",
                         "captured_at": NOW, "acl": ["team"], "redaction_status": "approved"}],
            "code_anchors": [{"key": "hit-hook", "path": "D.h", "symbol": "S",
                              "line_start": 1, "line_end": 1, "quote": "q",
                              "manifest": "manifest.ctx.code-v2"}],
            "glossary": [{"key": "hit", "term": "hit", "definition": "정의",
                          "evidence_refs": ["evref.ctx.hit-hook"]}],
        }
        result = build(notes, _store(_context()), NOW)
        self.assertEqual(result["errors"], [])  # 비차단
        warned = " ".join(result["warnings"])
        self.assertIn("g.ctx.hit", warned)             # 고립 GlossaryTerm → 경고
        self.assertNotIn("evref.ctx.hit-hook", warned)  # term이 가리킴 → 고립 아님
        self.assertNotIn("code.ctx.hit-hook", warned)   # evref locator가 가리킴 → 고립 아님

    def test_build_dangling_ref_caught(self):
        # glossary가 없는 evref를 가리키면 2층(dangling)이 잡는다
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"},
                 "glossary": [{"key": "x", "term": "x", "definition": "d",
                               "evidence_refs": ["evref.ctx.nonexistent"]}]}
        result = build(notes, _store(_context()), NOW)
        self.assertTrue(
            any("dangling evidence_ref evref.ctx.nonexistent" in error
                for error in result["errors"]),
            result["errors"],
        )

    def test_build_evref_dangling_manifest_caught(self):
        # extra_objects로 들어온 EvidenceRef가 없는 manifest를 가리키면 build 2층이 잡는다.
        evref = {"id": "evref.ctx.x", "kind": "EvidenceRef", "status": "reviewed",
                 "truth_role": "reference", "title": "e",
                 "evidence_manifest_id": "manifest.ctx.missing", "ref_type": "session_turn",
                 "locator": "...", "summary": "s", "schema_version": "0.1", "poc_priority": "P2",
                 "created_at": T0, "updated_at": T0, "tags": ["ctx"], "evidence_refs": []}
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"},
                 "extra_objects": [evref]}
        result = build(notes, _store(), NOW)
        self.assertEqual(
            [error for error in result["errors"]
             if "dangling evidence_manifest_id manifest.ctx.missing" in error],
            ["evref.ctx.x: dangling evidence_manifest_id manifest.ctx.missing"],
        )

    def test_build_union_target_missing_caught(self):
        # DomainContext.glossary_term_ids union 대상이 store·묶음 어디에도 없으면
        # generic lint와 별도로 update 위치를 밝힌 진단을 보존한다.
        store = _store(*_ref_objs())  # context.ctx 포함
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"},
                 "updates": [{"id": "context.ctx", "expected_updated_at": T0,
                              "union": {"glossary_term_ids": ["g.ctx.nonexistent"]}}]}
        result = build(notes, store, NOW)
        self.assertIn(
            "updates context.ctx: union glossary_term_ids 대상 g.ctx.nonexistent 없음 "
            "(store·이번 묶음 어디에도)",
            result["errors"],
        )

    def test_build_emits_preconditions_for_updates(self):
        # title(비-claim) set + 참조 닫힌 픽스처 → errors 없이 preconditions 방출
        store = _store(_mapping(glossary_term_ids=[]), *_ref_objs())
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "demoapp"},
                 "updates": [{"id": "mapping.ctx.hook", "expected_updated_at": T0,
                              "set": {"title": "새 제목"}}]}
        result = build(notes, store, NOW)
        self.assertEqual(result["errors"], [])
        import hashlib

        expected = hashlib.sha256(
            BrainStore.object_bytes(store.get("mapping.ctx.hook"))
        ).hexdigest()
        self.assertEqual(
            result["preconditions"],
            {"mapping.ctx.hook": expected},
        )


class CodeAnchorMutationInputTest(unittest.TestCase):
    def _notes(self):
        return {
            "context": {
                "key": "ctx",
                "commit": "a" * 40,
                "repo": "demoapp",
            },
            "code_anchors": [
                {
                    "key": "foo",
                    "path": "Foo.cpp",
                    "symbol": "Foo::bar",
                    "manifest": "manifest.ctx.code",
                    "quote": "void Foo::bar() {}",
                }
            ],
        }

    def test_code_anchor_build_uses_symbol_titles_and_omits_verified_at(self):
        loc, evref = build_code_evidence(self._notes(), NOW)

        self.assertEqual(loc["title"], "Foo::bar")
        self.assertNotIn("verified_at", loc)
        self.assertEqual(evref["title"], "Foo::bar")

    def test_code_anchor_rejects_external_title_and_verified_at(self):
        for field, value in (
            ("title", "외부 제목"),
            ("verified_at", "1900-01-01T00:00:00Z"),
        ):
            notes = self._notes()
            notes["code_anchors"][0][field] = value
            with self.subTest(field=field):
                errors = validate_notes(notes)
                self.assertTrue(
                    any(field in error and "허용" in error for error in errors),
                    errors,
                )


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

    def test_decision_evidence_slack_spec_wiki_types(self):
        # 발견3: 기획서→구현 이후 최초와 달라지는 변경(개선/기획요청)이 '결정'이 되고,
        # 그 근거가 Slack/기획서/위키인 경우가 실재한다(spec_reflected=no는 commit 근거 자체가 없음).
        # 자동조립이 이 근거들을 받아야 한다 — 스키마 REF_TYPE_VALUES는 이미 지원.
        from project_brain.assembly import validate_notes
        notes = self._notes()
        notes["decisions"][0]["evidence"] = [
            {"type": "slack", "ref": "C123-p456",
             "locator": "https://slack/archives/C123/p456", "summary": "기획요청 스레드"},
            {"type": "spec", "ref": "luckybox-v2",
             "locator": "기획서 럭키박스 v2 §3", "summary": "완주 기준 개정"},
            {"type": "wiki", "ref": "luckybox-page",
             "locator": "wiki/luckybox", "summary": "서버 규칙 위키"},
        ]
        self.assertEqual(validate_notes(notes), [])  # 1층 통과(하드코딩 튜플 아닌 dict 참조)
        objs = build_decisions(notes, NOW)
        evs = {o["id"]: o for o in objs if o["kind"] == "EvidenceRef"}
        self.assertEqual(evs["evref.ctx.slack-c123-p456"]["ref_type"], "slack_thread")
        self.assertEqual(evs["evref.ctx.spec-luckybox-v2"]["ref_type"], "spec_section")
        self.assertEqual(evs["evref.ctx.wiki-luckybox-page"]["ref_type"], "wiki_section")
        # 커밋 외 타입은 노트가 준 locator를 그대로 쓴다(인스턴스 URL은 엔진이 안 만듦)
        self.assertEqual(evs["evref.ctx.slack-c123-p456"]["locator"],
                         "https://slack/archives/C123/p456")

    def test_decision_evidence_unsupported_type_still_rejected(self):
        # 무한 확장 아님 — 지원 목록(_DECISION_REF_TYPE) 밖 타입은 1층에서 여전히 거부
        from project_brain.assembly import validate_notes
        notes = self._notes()
        notes["decisions"][0]["evidence"] = [{"type": "email", "ref": "x", "locator": "y"}]
        self.assertTrue(any("미지원" in e for e in validate_notes(notes)))


class BuildWithDecisionsTest(unittest.TestCase):
    def _notes(self):
        return {
            "context": {"key": "ctx", "commit": "abc123", "now": NOW, "repo": "bb2_client",
                        "display_name": "테스트 컨텍스트", "boundary_summary": "경계",
                        "in_scope": ["x"], "out_of_scope": ["y"], "glossary_term_ids": []},
            "sources": [
                {"id": "manifest.ctx.code", "source_type": "code_search",
                 "title": "코드", "locator": "repo@dev", "captured_at": NOW, "acl": ["team"],
                 "redaction_status": "approved"},
                {"id": "manifest.ctx.commit", "source_type": "commit",
                 "title": "커밋 이력", "locator": "bb2_client@develop", "captured_at": NOW,
                 "acl": ["team"],
                 "redaction_status": "approved"},
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
