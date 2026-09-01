"""QueryRouter의 변경 이유·현재·과거·근거 facet과 읽기 전용 계약 회귀."""

import copy
import unittest

from project_brain.router import QueryRouter
from project_brain.store import BrainStore
from tests.test_ingest import context


def store_of(*objs):
    return BrainStore({o["id"]: o for o in objs})


def reviewed_term_with_evidence(tid, term, *, evidence_refs):
    """근거 가진 reviewed GlossaryTerm (Task 4 §6.4 이후에도 유효하도록 evidence 보유)."""
    from project_brain.objbase import base
    return base(
        {
            "id": tid,
            "kind": "GlossaryTerm",
            "status": "reviewed",
            "truth_role": "domain",
            "title": f"Term: {term}",
            "context_id": "context.neutral",
            "term": term,
            "definition": f"{term} 검수 정의",
            "evidence_refs": evidence_refs,
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


def candidate_term_inline(tid, term, *, definition="후보 정의", aliases=None):
    """노출 대상 candidate GlossaryTerm (매칭용 term/aliases 보유)."""
    from project_brain.objbase import base
    obj = {
        "id": tid,
        "kind": "GlossaryTerm",
        "status": "candidate",
        "truth_role": "domain",
        "title": f"Candidate term: {term}",
        "context_id": "context.neutral",
        "term": term,
        "definition": definition,
        "candidate": {"candidate_state": "ready_for_review", "candidate_source": "spec"},
    }
    if aliases is not None:
        obj["aliases"] = aliases
    return base(obj, tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z")


class TestRestrictedForFailClosed(unittest.TestCase):
    """_restricted_for 신뢰 게이트는 fail-closed: 'approved'만 통과, None·키 누락·비승인은 restricted."""

    def _store_and_obj(self, manifest):
        evref = {"id": "evref.x", "kind": "EvidenceRef", "evidence_manifest_id": manifest["id"]}
        obj = {"id": "mapping.x", "kind": "DomainMapping", "evidence_refs": ["evref.x"]}
        return store_of(obj, evref, manifest), obj

    def test_approved_not_restricted(self):
        store, obj = self._store_and_obj(
            {"id": "manifest.x", "kind": "EvidenceManifest", "redaction_status": "approved"})
        self.assertFalse(QueryRouter(store)._restricted_for(obj))

    def test_missing_redaction_status_is_restricted(self):
        # 키 누락(수기편집 등 lint 전 비정상 상태) → fail-closed로 restricted(신뢰 오표시 방지)
        store, obj = self._store_and_obj({"id": "manifest.x", "kind": "EvidenceManifest"})
        self.assertTrue(QueryRouter(store)._restricted_for(obj))

    def test_nonapproved_status_is_restricted(self):
        store, obj = self._store_and_obj(
            {"id": "manifest.x", "kind": "EvidenceManifest", "redaction_status": "staged"})
        self.assertTrue(QueryRouter(store)._restricted_for(obj))


class TestQueryFacetCandidateIsolation(unittest.TestCase):
    def test_candidate_not_fed_into_conflict_resolution(self):
        # glossary_meaning + current_status를 함께 유발하는 질의.
        # current_status 분기의 kept/conflicts에 candidate가 절대 안 섞여야 함(spec §4.2).
        store = store_of(context(glossary_term_ids=[]),
                         candidate_term_inline("g.c", "갈고리"))
        answer = QueryRouter(store).answer("갈고리 용어 현재 규칙 무슨 뜻?")
        current = next(s for s in answer["sections"] if s["intent"] == "current_status")
        self.assertNotIn("g.c", current["object_ids"])
        for entry in current.get("conflicts", []):
            self.assertNotIn("g.c", entry["fact_ids"])


def decision_record_inline(did, *, affected_term_ids, summary="결정"):
    """매칭된 용어를 affected_glossary_term_ids로 가리키는 reviewed DecisionRecord."""
    from project_brain.objbase import base
    return base(
        {
            "id": did,
            "kind": "DecisionRecord",
            "status": "reviewed",
            "truth_role": "event",
            "title": f"Decision: {summary}",
            "decision_type": "improvement",
            "summary": summary,
            "decision": f"{summary} 상세",
            "source_object_ids": [],
            "affected_context_ids": [],
            "affected_glossary_term_ids": affected_term_ids,
            "spec_reflected": "unknown",
        },
        tags=["neutral"], created_at="2026-06-09T00:00:00Z", updated_at="2026-06-09T00:00:00Z",
    )


def temporal_fact_inline(fid, *, value, feature):
    from project_brain.objbase import base

    return base(
        {
            "id": fid,
            "kind": "TemporalFact",
            "status": "reviewed",
            "truth_role": "fact",
            "title": f"{feature} 현재 규칙",
            "subject": "race.level",
            "predicate": "enabled",
            "value": value,
            "scope": {"feature": feature},
            "valid_from": "2026-06-09T00:00:00Z",
            "derived_from_event_id": "ledger.neutral.change",
            "confidence": "high",
        },
        tags=["neutral"],
        created_at="2026-06-09T00:00:00Z",
        updated_at="2026-06-09T00:00:00Z",
    )


class TestWhyChangedDecisions(unittest.TestCase):
    def test_decision_surfaces_for_matched_term(self):
        # "왜 X 추가됐어?" → why_changed. DecisionRecord가 매칭된 용어를
        # affected_glossary_term_ids로 가리키면 surface한다(EventLedger 0개여도).
        store = store_of(
            context(glossary_term_ids=[]),
            candidate_term_inline("g.npcno", "NpcNo"),
            decision_record_inline("d.npcno", affected_term_ids=["g.npcno"], summary="NpcNo 추가"),
        )
        answer = QueryRouter(store).answer("왜 NpcNo 추가됐어?")
        self.assertIn("why_changed", answer["intents"])
        self.assertIn("d.npcno", answer["source_object_ids"])
        why = next(s for s in answer["sections"] if s["intent"] == "why_changed")
        self.assertIn("d.npcno", why["object_ids"])
        # 결정의 실제 내용(왜)이 답에 펼쳐져야 한다 — id만으론 "왜"에 답 못 함.
        self.assertEqual(why["decisions"][0]["summary"], "NpcNo 추가")

    def test_unrelated_decision_not_surfaced(self):
        # 질의에 안 나오는 용어를 가리키는 결정은 surface 안 함(scoped — 전량 반환 방지).
        store = store_of(
            context(glossary_term_ids=[]),
            candidate_term_inline("g.npcno", "NpcNo"),
            candidate_term_inline("g.other", "전혀다른것"),
            decision_record_inline("d.other", affected_term_ids=["g.other"], summary="딴 결정"),
        )
        answer = QueryRouter(store).answer("왜 NpcNo 추가됐어?")
        self.assertNotIn("d.other", answer["source_object_ids"])

    def test_reviewed_synonym_and_alias_surface_the_same_decision(self):
        from tests.test_search import glossary_term

        term = glossary_term(
            "g.canoe",
            term="카누 레이스",
            synonyms=["카누 경기"],
            aliases=["샐리 카누"],
        )
        decision = decision_record_inline(
            "d.canoe",
            affected_term_ids=[term["id"]],
            summary="카누 규칙 변경",
        )
        store = store_of(term, decision)

        for name in ("카누 경기", "샐리 카누"):
            with self.subTest(name=name):
                answer = QueryRouter(store).answer(f"왜 {name} 규칙이 바뀌었어?")
                self.assertIn(decision["id"], answer["source_object_ids"])
                section = next(
                    item for item in answer["sections"]
                    if item["intent"] == "why_changed"
                )
                self.assertIn(decision["id"], section["object_ids"])


class TestReviewedNameScope(unittest.TestCase):
    def _term(self):
        from tests.test_search import glossary_term

        term = glossary_term(
            "g.canoe",
            term="카누 레이스",
            synonyms=["카누 경기"],
            aliases=["샐리 카누"],
        )
        term["scope_hint"] = {"feature": "canoe-race"}
        return term

    def _facts(self):
        return (
            temporal_fact_inline(
                "fact.canoe",
                value=True,
                feature="canoe-race",
            ),
            temporal_fact_inline(
                "fact.other",
                value=False,
                feature="other-race",
            ),
        )

    def test_synonym_and_alias_apply_the_same_scope_hint(self):
        term = self._term()
        canoe, other = self._facts()
        store = store_of(term, canoe, other)

        for name in ("카누 경기", "샐리 카누"):
            with self.subTest(name=name):
                answer = QueryRouter(store).answer(f"{name} 현재 규칙 알려줘")
                section = next(
                    item for item in answer["sections"]
                    if item["intent"] == "current_status"
                )
                self.assertEqual(section["object_ids"], [canoe["id"]])
                self.assertEqual(section["conflicts"], [])
                self.assertNotIn(other["id"], answer["source_object_ids"])
                self.assertTrue(any(
                    "scope 추론" in warning
                    for warning in answer["warnings"]
                ))

    def test_synonym_and_alias_apply_the_same_as_of_scope_hint(self):
        term = self._term()
        canoe, other = self._facts()
        store = store_of(term, canoe, other)

        for name in ("카누 경기", "샐리 카누"):
            with self.subTest(name=name):
                answer = QueryRouter(store).answer(f"{name} 당시 규칙 알려줘")
                section = next(
                    item for item in answer["sections"]
                    if item["intent"] == "as_of_history"
                )
                self.assertEqual(section["object_ids"], [canoe["id"]])
                self.assertNotIn(other["id"], answer["source_object_ids"])
                self.assertTrue(any(
                    "scope 추론" in warning
                    for warning in answer["warnings"]
                ))

    def test_long_alias_does_not_apply_nested_short_term_scope(self):
        from tests.test_search import glossary_term

        long_term = self._term()
        short_term = glossary_term("g.short", term="카누")
        short_term["scope_hint"] = {"feature": "other-race"}
        canoe, other = self._facts()

        answer = QueryRouter(
            store_of(long_term, short_term, canoe, other)
        ).answer("샐리 카누 현재 규칙 알려줘")
        section = next(
            item for item in answer["sections"]
            if item["intent"] == "current_status"
        )

        self.assertEqual(section["object_ids"], [canoe["id"]])
        self.assertNotIn(other["id"], answer["source_object_ids"])
        self.assertFalse(any(
            "feature=other-race" in warning
            for warning in answer["warnings"]
        ))


class TestDeterministicFacetPreservation(unittest.TestCase):
    def test_current_status_uses_supersedes_winner_for_conflicting_facts(self):
        old = temporal_fact_inline("fact.old", value=False, feature="canoe-race")
        new = temporal_fact_inline("fact.new", value=True, feature="canoe-race")
        new["supersedes"] = old["id"]

        answer = QueryRouter(store_of(old, new)).answer("현재 규칙은?")
        current = next(
            section for section in answer["sections"]
            if section["intent"] == "current_status"
        )

        self.assertEqual(current["object_ids"], [new["id"]])
        self.assertEqual(current["conflicts"][0]["fact_ids"], [new["id"], old["id"]])
        self.assertFalse(answer["needs_clarification"])

    def test_current_status_warns_for_invalid_current_view_sources(self):
        candidate = temporal_fact_inline(
            "fact.candidate",
            value=True,
            feature="canoe-race",
        )
        candidate["status"] = "candidate"
        closed = temporal_fact_inline(
            "fact.closed",
            value=False,
            feature="canoe-race",
        )
        closed["valid_until"] = "2026-06-10T00:00:00Z"
        view = {
            "id": "view.current.canoe",
            "kind": "CurrentView",
            "status": "reviewed",
            "source_fact_ids": ["fact.missing", candidate["id"], closed["id"]],
        }

        answer = QueryRouter(store_of(candidate, closed, view)).answer("현재 상태는?")
        rendered = "\n".join(answer["warnings"])

        self.assertIn("source fact fact.missing 부재", rendered)
        self.assertIn("source fact fact.candidate 미검수", rendered)
        self.assertIn("source fact fact.closed 닫힘(superseded)", rendered)

    def test_evidence_facet_preserves_chain_and_raw_or_restricted_status(self):
        fact = temporal_fact_inline("fact.evidence", value=True, feature="canoe-race")
        fact["review_record_id"] = "review.fact.evidence"
        fact["evidence_refs"] = ["evref.fact.evidence"]
        review = {"id": "review.fact.evidence", "kind": "ReviewRecord"}
        reference = {
            "id": "evref.fact.evidence",
            "kind": "EvidenceRef",
            "evidence_manifest_id": "manifest.fact.evidence",
        }

        for redaction_status, missing_raw, expected_status in (
            ("approved", True, "raw-unavailable"),
            ("restricted", False, "restricted"),
        ):
            with self.subTest(expected_status=expected_status):
                manifest = {
                    "id": "manifest.fact.evidence",
                    "kind": "EvidenceManifest",
                    "redaction_status": redaction_status,
                }
                router = QueryRouter(
                    store_of(fact, review, reference, manifest),
                    missing_raw_manifest_ids=(
                        {manifest["id"]} if missing_raw else set()
                    ),
                )
                answer = router.answer("근거와 출처를 알려줘")
                evidence = next(
                    section for section in answer["sections"]
                    if section["intent"] == "evidence_provenance"
                )

                self.assertEqual(
                    evidence["object_ids"],
                    [fact["id"], review["id"], reference["id"]],
                )
                self.assertEqual(answer["status"], expected_status)

    def test_why_changed_keeps_inferred_causal_basis_without_derived_facts(self):
        events = [
            {
                "id": f"ledger.event.{index}",
                "kind": "EventLedgerRecord",
                "status": "reviewed",
                "happened_at": f"2026-06-0{index}T00:00:00Z",
                "event_type": "qa_result" if index == 2 else "spec_revised",
                "summary": f"변경 사건 {index}",
            }
            for index in (1, 2)
        ]

        answer = QueryRouter(store_of(*events)).answer("왜 바뀌었어?")
        why = next(
            section for section in answer["sections"]
            if section["intent"] == "why_changed"
        )

        self.assertEqual(why["causal_basis"], "inferred")
        self.assertEqual(why["events"][1]["role"], "supporting_context")


class TestRouterReadOnly(unittest.TestCase):
    def test_answer_does_not_mutate_store(self):
        store = store_of(context(glossary_term_ids=["g.r"]),
                         reviewed_term_with_evidence("g.r", "갈고리", evidence_refs=[]))
        before = copy.deepcopy(store._objects)
        QueryRouter(store).answer("갈고리 용어 무슨 뜻?")
        self.assertEqual(store._objects, before)


if __name__ == "__main__":
    unittest.main()
