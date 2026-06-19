"""router.answer 회귀 베이스라인 (B+C 작업 선행). 읽기 전용 불변(answer 전후 store
불변) + 검수된 glossary 노출이라는 안정 동작을 고정한다. Task 1이 C(후보 노출)를
이 파일에 확장한다 — 후보 미노출 동작은 Task 1이 뒤집으므로 베이스라인에 넣지 않는다."""

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


class TestCandidateExposure(unittest.TestCase):
    def test_only_candidate_exposed_with_clarification(self):
        # 후보만 매칭(매칭된 검수 매핑 없음) → 후보 노출 + needs_clarification=True.
        # ★context()(reviewed DomainContext)를 일부러 둔다 — 실코퍼스에도 reviewed DomainContext가
        #   상존해 source_ids가 안 비므로, (not source_ids)가 아니라 명시 clarification_needed로
        #   §4.3이 작동함을 이 픽스처가 증명한다(리뷰 critical 반영).
        store = store_of(context(glossary_term_ids=[]),
                         candidate_term_inline("g.c", "갈고리"))
        answer = QueryRouter(store).answer("갈고리 용어 무슨 뜻?")
        gloss = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
        cand_ids = [c["id"] for c in gloss["candidate_terms"]]
        self.assertIn("g.c", cand_ids)
        self.assertEqual(gloss["candidate_terms"][0]["trust_label"], "확인 필요")
        # 후보 정의가 실제로 노출됨(silent 제거)
        self.assertEqual(gloss["candidate_terms"][0]["definition"], "후보 정의")
        # 후보 전용 필드에 승격 후보 번호
        self.assertIn("g.c", answer["promotable_candidate_ids"])
        # 후보만 노출 → 검수된 source 없음 → needs_clarification
        self.assertNotIn("g.c", answer["source_object_ids"])
        self.assertTrue(answer["needs_clarification"])
        # 답 전체 라벨은 candidate(severity 2) 이상
        self.assertEqual(answer["status"], "candidate")
        # 담담한 단서 한 줄
        self.assertTrue(any("확인 필요한 후보 항목 포함" in w for w in answer["warnings"]))

    def test_alias_matches_candidate(self):
        store = store_of(context(glossary_term_ids=[]),
                         candidate_term_inline("g.a", "카약 레이스", aliases=["미나의 카약"]))
        answer = QueryRouter(store).answer("미나의 카약 용어 무슨 뜻?")
        gloss = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
        self.assertIn("g.a", [c["id"] for c in gloss["candidate_terms"]])

    def test_irrelevant_candidate_not_exposed(self):
        # 질의에 안 나오는 term은 노출 안 함(노이즈 배제)
        store = store_of(context(glossary_term_ids=[]),
                         candidate_term_inline("g.c", "갈고리"),
                         candidate_term_inline("g.z", "전혀다른용어"))
        answer = QueryRouter(store).answer("갈고리 용어 무슨 뜻?")
        gloss = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
        ids = [c["id"] for c in gloss["candidate_terms"]]
        self.assertIn("g.c", ids)
        self.assertNotIn("g.z", ids)

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


class TestRouterReadOnly(unittest.TestCase):
    def test_answer_does_not_mutate_store(self):
        store = store_of(context(glossary_term_ids=["g.r"]),
                         reviewed_term_with_evidence("g.r", "갈고리", evidence_refs=[]))
        before = copy.deepcopy(store._objects)
        QueryRouter(store).answer("갈고리 용어 무슨 뜻?")
        self.assertEqual(store._objects, before)


class TestGlossaryReviewedExposure(unittest.TestCase):
    def test_reviewed_glossary_term_surfaces(self):
        store = store_of(context(glossary_term_ids=["g.r"]),
                         reviewed_term_with_evidence("g.r", "갈고리", evidence_refs=[]))
        answer = QueryRouter(store).answer("갈고리 용어 무슨 뜻?")
        self.assertIn("glossary_meaning", answer["intents"])
        self.assertIn("g.r", answer["source_object_ids"])


# ── 슬라이스 5: 라우터 의미 회상 통합(§7) ──────────────────────────────────────
import tempfile
from pathlib import Path
from unittest import mock

from project_brain.embedder import StubEmbedder
from project_brain.search_index import rebuild as index_rebuild
from tests.test_search import (
    code_locator,
    domain_mapping,
    glossary_term as st_glossary_term,
)


class TestRouterRecallTopK(unittest.TestCase):
    """§7 전량 적재 → top-K 전이: 색인이 있으면 라우터가 recall 점수 top-K로 좁힌다
    (06-05 "110개 무더기" 제거). 전부 stub embedder + tmp 색인."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()

    def tearDown(self):
        self._td.cleanup()

    def _rebuild(self, objs):
        for obj in objs:
            BrainStore.save_object(self.brain, obj)
        index_rebuild(self.brain, self.db, embedder=self.embedder)

    def _router(self):
        return QueryRouter(BrainStore.load(self.brain), db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)

    def test_implementation_location_uses_topk_not_all(self):
        # CodeLocator 12개를 적재하고 어디 구현 질의 → recall top-K(≤5)로 좁혀져
        # 전량(12개)이 아니라 일부만 source로 적재된다(전량 적재 사라짐).
        objs = [code_locator(f"code.{i:02d}", path=f"a/Lane{i}.cpp", symbol=f"makeLanes{i}")
                for i in range(12)]
        self._rebuild(objs)
        answer = self._router().answer("makeLanes0 어디 구현?")
        loc_section = next(s for s in answer["sections"]
                           if s["intent"] == "implementation_location")
        # 회상 0건 회귀(게이트 전부 차단)가 공허하게 통과하지 않게 ≥1 단언(리뷰 반영).
        self.assertGreaterEqual(len(loc_section["object_ids"]), 1)
        self.assertLessEqual(len(loc_section["object_ids"]), 5)
        # 무더기(12 전량)가 아니다.
        self.assertLess(len(loc_section["object_ids"]), 12)

    def test_implementation_location_pinpoints_via_mapping_graph(self):
        # §3.5·§8 주 경로: 매핑이 점수 상위로 적중하고, 그 매핑이 linked.code_locators로
        # 동반한 CodeLocator가 implementation_location source로 핀포인트된다(심볼 직접
        # 적중이 아니라 그래프 1-hop 경로). 매핑 텍스트가 질의와 닿게 구성.
        self._rebuild([
            domain_mapping("m.stage", meaning="스테이지 클리어 개수 최대값 모델",
                           glossary_term_ids=["g.stage"],
                           code_locator_ids=["code.stage"]),
            st_glossary_term("g.stage", term="StageClearMax", definition="스테이지 클리어 개수"),
            code_locator("code.stage", path="a/Model.hpp", symbol="m_nStageClearMax"),
        ])
        answer = self._router().answer("스테이지 클리어 개수 최대값 모델 어디 구현?")
        loc_section = next(s for s in answer["sections"]
                           if s["intent"] == "implementation_location")
        # 매핑이 동반한 code.stage가 핀포인트로 들어온다(전량 적재 아님).
        self.assertIn("code.stage", loc_section["object_ids"])
        self.assertLessEqual(len(loc_section["object_ids"]), 5 + 1)

    def test_candidate_linked_locator_not_in_source(self):
        # 리뷰 반영(§7 채널 규약): reviewed 매핑이 candidate CodeLocator를 참조해도
        # 확신 채널(source)에는 안 들어간다 — 폴백 경로(_reviewed_by_kind)와 동일.
        cand_locator = code_locator("code.cand", path="a/Model.hpp",
                                    symbol="m_nStageClearMax")
        cand_locator["status"] = "candidate"
        self._rebuild([
            domain_mapping("m.stage", meaning="스테이지 클리어 개수 최대값 모델",
                           glossary_term_ids=["g.stage"],
                           code_locator_ids=["code.cand", "code.ok"]),
            st_glossary_term("g.stage", term="StageClearMax",
                             definition="스테이지 클리어 개수"),
            cand_locator,
            code_locator("code.ok", path="a/Model.cpp", symbol="setStageClearMax"),
        ])
        answer = self._router().answer("스테이지 클리어 개수 최대값 모델 어디 구현?")
        loc_section = next(s for s in answer["sections"]
                           if s["intent"] == "implementation_location")
        self.assertIn("code.ok", loc_section["object_ids"])
        self.assertNotIn("code.cand", loc_section["object_ids"])

    def test_candidate_linked_locator_exposed_with_label(self):
        # 후보 채널 노출(2026-06-11 사용자 결정): reviewed 매핑이 동반한 candidate
        # CodeLocator는 침묵 드롭이 아니라 "확인 필요" 라벨로 노출한다 — C 정책
        # (glossary candidate_terms)을 구현위치 섹션에도 적용. 확신 채널(object_ids)
        # 불변은 위 테스트가 보장.
        cand_locator = code_locator("code.cand", path="a/Model.hpp",
                                    symbol="m_nStageClearMax")
        cand_locator["status"] = "candidate"
        self._rebuild([
            domain_mapping("m.stage", meaning="스테이지 클리어 개수 최대값 모델",
                           glossary_term_ids=["g.stage"],
                           code_locator_ids=["code.cand", "code.ok"]),
            st_glossary_term("g.stage", term="StageClearMax",
                             definition="스테이지 클리어 개수"),
            cand_locator,
            code_locator("code.ok", path="a/Model.cpp", symbol="setStageClearMax"),
        ])
        answer = self._router().answer("스테이지 클리어 개수 최대값 모델 어디 구현?")
        loc_section = next(s for s in answer["sections"]
                           if s["intent"] == "implementation_location")
        self.assertNotIn("code.cand", loc_section["object_ids"])
        cand = next(c for c in loc_section["candidate_locators"]
                    if c["id"] == "code.cand")
        self.assertEqual(cand["trust_label"], "확인 필요")
        self.assertEqual(cand["path"], "a/Model.hpp")
        self.assertIn("code.cand", answer["promotable_candidate_ids"])

    def test_candidate_direct_locator_hit_exposed(self):
        # 후보 채널 직접 적중(candidate CodeLocator가 recall candidates에 뜸)도
        # 같은 라벨로 노출 — reviewed가 하나도 없으면 확신 채널은 빈 채 유지.
        objs = []
        for i in range(3):
            loc = code_locator(f"code.{i}", path=f"a/Lane{i}.cpp", symbol=f"makeLanes{i}")
            loc["status"] = "candidate"
            objs.append(loc)
        self._rebuild(objs)
        answer = self._router().answer("makeLanes0 어디 구현?")
        loc_section = next(s for s in answer["sections"]
                           if s["intent"] == "implementation_location")
        self.assertEqual(loc_section["object_ids"], [])
        ids = [c["id"] for c in loc_section["candidate_locators"]]
        self.assertIn("code.0", ids)

    def test_glossary_meaning_uses_topk_not_all_reviewed(self):
        # reviewed GlossaryTerm 12개 적재. 정확 매칭 매핑이 없는 질의에서도 glossary
        # source가 전량(12)이 아니라 recall top-K(≤5)로 좁혀진다.
        objs = [st_glossary_term(f"g.{i:02d}", term=f"용어{i}", definition=f"레인 정의 {i}")
                for i in range(12)]
        self._rebuild(objs)
        answer = self._router().answer("용어0 무슨 뜻?")
        gloss = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
        # 회상 0건 회귀가 공허하게 통과하지 않게 ≥1 단언(리뷰 반영).
        self.assertGreaterEqual(len(gloss["object_ids"]), 1)
        self.assertLessEqual(len(gloss["object_ids"]), 5)
        self.assertLess(len(gloss["object_ids"]), 12)

    def test_evidence_provenance_combined_impl_uses_topk(self):
        # 후속 a(P2 4번): evidence_provenance가 implementation_location과 결합되면
        # CodeLocator 전량(_reviewed_by_kind)이 아니라 recall top-K 핀포인트의 출처
        # 사슬만 defend한다(§6.6 정밀 규칙 + §7 top-K의 결합 경로 적용).
        objs = [code_locator(f"code.{i:02d}", path=f"a/Lane{i}.cpp", symbol=f"makeLanes{i}")
                for i in range(12)]
        self._rebuild(objs)
        answer = self._router().answer("makeLanes0 어디 구현? 근거는?")
        ev = next(s for s in answer["sections"]
                  if s["intent"] == "evidence_provenance")
        loc_ids = [oid for oid in ev["object_ids"] if oid.startswith("code.")]
        self.assertGreaterEqual(len(loc_ids), 1)
        self.assertLessEqual(len(loc_ids), 6)  # top-K(5)+그래프 동반 ≤6, 전량 12 아님

    def test_evidence_provenance_combined_glossary_uses_topk(self):
        # 후속 a: glossary_meaning 결합도 DomainContext·GlossaryTerm 전량이 아니라
        # recall top-K로 좁힌다.
        objs = [st_glossary_term(f"g.{i:02d}", term=f"용어{i}", definition=f"레인 정의 {i}")
                for i in range(12)]
        self._rebuild(objs)
        answer = self._router().answer("용어0 무슨 뜻? 근거는?")
        ev = next(s for s in answer["sections"]
                  if s["intent"] == "evidence_provenance")
        term_ids = [oid for oid in ev["object_ids"] if oid.startswith("g.")]
        self.assertGreaterEqual(len(term_ids), 1)
        self.assertLess(len(term_ids), 12)

    def test_router_recall_reuses_router_store(self):
        # 후속 b(2026-06-11): 라우터는 생성 시 받은 self.store를 recall에 주입한다 —
        # 질의마다 BrainStore.load로 코퍼스 재로드 없음(장수 인스턴스 성능,
        # 06-10 슬라이스 5 리뷰 후속 관찰 (b) 해소).
        objs = [code_locator(f"code.{i:02d}", path=f"a/Lane{i}.cpp", symbol=f"makeLanes{i}")
                for i in range(3)]
        self._rebuild(objs)
        router = self._router()
        with mock.patch.object(BrainStore, "load",
                               side_effect=AssertionError("라우터 회상은 자기 store 재사용")):
            answer = router.answer("makeLanes0 어디 구현?")
        loc = next(s for s in answer["sections"]
                   if s["intent"] == "implementation_location")
        # 회상이 실제로 돌았는지(공허 통과 방지) 적중 ≥1 단언.
        self.assertGreaterEqual(len(loc["object_ids"]), 1)

    def test_exact_matched_mapping_not_duplicated(self):
        # 요구사항 1: 정확 매칭이 잡은 매핑은 의미 확장에서 중복 적재 안 됨.
        # 매핑이 용어 "레인"을 표면으로 가져 정확 매칭되면서, recall에도 잡힐 수 있다.
        self._rebuild([
            st_glossary_term("g.lane", term="레인", definition="레인 영역 배치"),
            domain_mapping("m.lane", meaning="레인 영역 배치",
                           glossary_term_ids=["g.lane"]),
        ])
        answer = self._router().answer("레인 무슨 뜻?")
        gloss = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
        # m.lane은 정확 매칭(mappings)으로 한 번만 — object_ids에 중복 없음.
        self.assertEqual(gloss["object_ids"].count("m.lane"), 1)


class TestRouterRecallFallback(unittest.TestCase):
    """§7 안전 폴백: db_path가 없거나 색인이 없으면 recall을 끄고 정확 매칭 경로만으로
    동작한다 — 색인 없는 store로 도는 기존 동작 보존."""

    def test_no_db_path_falls_back_to_full_load(self):
        # db_path 미지정 → recall 비활성. reviewed GlossaryTerm 전량 적재(폴백) 유지.
        store = store_of(context(glossary_term_ids=["g.r"]),
                         reviewed_term_with_evidence("g.r", "갈고리", evidence_refs=[]))
        answer = QueryRouter(store).answer("갈고리 용어 무슨 뜻?")
        self.assertIn("g.r", answer["source_object_ids"])

    def test_missing_db_file_falls_back(self):
        # db_path는 줬지만 파일이 없으면(색인 미생성) recall 비활성 → 폴백.
        store = store_of(context(glossary_term_ids=["g.r"]),
                         reviewed_term_with_evidence("g.r", "갈고리", evidence_refs=[]))
        router = QueryRouter(store, db_path=Path("/nonexistent/index.db"))
        answer = router.answer("갈고리 용어 무슨 뜻?")
        self.assertIn("g.r", answer["source_object_ids"])


class TestRouterUnknownRecall(unittest.TestCase):
    """§7 unknown 일반 회상: 맥락만 던진 질의를 의미 회상으로 답한다.
    게이트 통과 reviewed=확신(source), candidate=후보(promotable + 확인필요)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()

    def tearDown(self):
        self._td.cleanup()

    def _rebuild(self, objs):
        for obj in objs:
            BrainStore.save_object(self.brain, obj)
        index_rebuild(self.brain, self.db, embedder=self.embedder)

    def _router(self):
        return QueryRouter(BrainStore.load(self.brain), db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)

    def test_unknown_query_recalls_reviewed_as_source(self):
        # intent 분류가 unknown(키워드 신호 없는 맥락 질의)인데, 색인이 있으면 의미
        # 회상으로 reviewed 적중을 source로 답한다.
        self._rebuild([
            st_glossary_term("g.lane", term="레인 영역", definition="레인 영역 배치 좌표"),
        ])
        answer = self._router().answer("레인 영역 배치 좌표")
        self.assertIn("unknown", answer["intents"])
        self.assertIn("g.lane", answer["source_object_ids"])
        self.assertFalse(answer["needs_clarification"])

    def test_unknown_candidate_only_needs_clarification(self):
        # candidate만 게이트 통과하면 후보 채널 노출(promotable) + needs_clarification.
        self._rebuild([
            st_glossary_term("g.cand", term="레인 영역", definition="레인 영역 배치 좌표",
                             status="candidate"),
        ])
        answer = self._router().answer("레인 영역 배치 좌표")
        self.assertIn("g.cand", answer["promotable_candidate_ids"])
        self.assertNotIn("g.cand", answer["source_object_ids"])
        self.assertTrue(answer["needs_clarification"])

    def test_unknown_no_index_falls_back_to_no_match(self):
        # 색인이 없으면 unknown은 기존 "No matching intent"로 폴백(빈 회상).
        store = store_of(context(glossary_term_ids=[]))
        answer = QueryRouter(store).answer("아무 맥락 텍스트")
        unk = next(s for s in answer["sections"] if s["intent"] == "unknown")
        self.assertEqual(unk["object_ids"], [])
        self.assertEqual(unk["summary"], "No matching intent")

    def test_unknown_anchorless_query_gated_to_clarification(self):
        # ★게이트 needs_clarification★(§7): 흔한 토큰만 다수 문서에 심어 앵커 df를 상한
        # 위로 올리고, 질의 핵심 엔티티는 코퍼스에 없다 → 게이트 차단 → needs_clarification.
        from project_brain.search import _ANCHOR_DF_MAX
        objs = [st_glossary_term(f"g.common{i}", term="보상", definition="흔한 보상 토큰")
                for i in range(_ANCHOR_DF_MAX + 5)]
        self._rebuild(objs)
        answer = self._router().answer("없는엔티티 보상")
        self.assertTrue(answer["needs_clarification"])
        # 게이트 차단이라 reviewed source로 적재되지 않는다.
        unk = next(s for s in answer["sections"] if s["intent"] == "unknown")
        self.assertEqual(unk["object_ids"], [])


class TestRouterAdvisories(unittest.TestCase):
    """answer() 반환에 advisories 키(spec 2026-06-15 §4.6) — recall이 켜지면 reviewed
    Insight를 가공해 노출(id/insight_type/surface/code_locators). 색인 없으면 빈 리스트."""

    def setUp(self):
        from tempfile import TemporaryDirectory
        from project_brain.embedder import StubEmbedder
        from project_brain.search_index import rebuild
        from project_brain.objbase import base
        self._td = TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        from pathlib import Path
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()
        T = "2026-06-04T00:00:00Z"
        objs = [
            base({"id": "g.token", "kind": "GlossaryTerm", "status": "reviewed",
                  "truth_role": "domain", "title": "Term", "context_id": "context.neutral",
                  "term": "클리어 토큰", "definition": "스테이지 클리어 토큰 노출",
                  "evidence_refs": ["ev.x"]},
                 tags=["n"], created_at=T, updated_at=T),
            base({"id": "code.gate", "kind": "CodeLocator", "status": "reviewed",
                  "truth_role": "reference", "title": "Code", "context_id": "context.neutral",
                  "repo": "demoapp", "path": "a/Enter.cpp", "symbol": "Enter::gate",
                  "locator_source": "rg", "verified_at": T, "evidence_refs": []},
                 tags=["n"], created_at=T, updated_at=T),
            base({"id": "insight.gate", "kind": "Insight", "status": "reviewed",
                  "truth_role": "synthesis", "title": "인사이트",
                  "body": "클리어 토큰 노출 게이트가 두 팝업에 이중구현",
                  "scope": "클리어 토큰", "insight_type": "cross-cutting-risk",
                  "source_object_ids": ["g.token", "code.gate"],
                  "code_locator_ids": ["code.gate"], "evidence_refs": []},
                 tags=["n"], created_at=T, updated_at=T),
        ]
        for o in objs:
            BrainStore.save_object(self.brain, o)
        rebuild(self.brain, self.db, embedder=self.embedder)
        self.store = BrainStore.load(self.brain)

    def _router(self):
        return QueryRouter(self.store, db_path=self.db, embedder=self.embedder,
                           brain_root=self.brain)

    def test_advisories_key_present_and_populated(self):
        resp = self._router().answer("클리어 토큰 노출 게이트 이중구현")
        self.assertIn("advisories", resp)
        ids = {a["id"] for a in resp["advisories"]}
        self.assertIn("insight.gate", ids)
        adv = next(a for a in resp["advisories"] if a["id"] == "insight.gate")
        self.assertEqual(adv["insight_type"], "cross-cutting-risk")
        self.assertIn("이중구현", adv["surface"])
        self.assertIn("code.gate", {c["object_id"] for c in adv["code_locators"]})
        # 가로지름(critic 검토 4): source_object_ids가 advisory에 직접 담긴다.
        self.assertEqual(set(adv["source_object_ids"]), {"g.token", "code.gate"})

    def test_advisories_empty_without_index(self):
        # 색인 없는 라우터(db_path 미전달)는 recall 비활성 → advisories 빈 리스트.
        resp = QueryRouter(self.store).answer("클리어 토큰 노출 게이트")
        self.assertEqual(resp["advisories"], [])


if __name__ == "__main__":
    unittest.main()
