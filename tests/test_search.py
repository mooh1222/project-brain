"""RRF 융합 + recall() + eval_recall 어댑터 (스펙 §3.4·§3 결과 계약, 슬라이스 3 마무리).

spec: docs/superpowers/specs/2026-06-10-project-brain-search-layer-design.md

전부 stub embedder + tmp 색인으로 결정론 검증한다(과업 명세 — 실모델 테스트 없음.
실코퍼스·실모델 측정은 cli eval/슬라이스 3.5 몫). RRF 수식은 손계산 기대값으로
검증하고, 양채널/단채널 융합·top30 절단·matched_via 표기·결정론·scope 필터·
검수 상태와 객체 종류만으로 갈리는 채널 배치를 본다(ADR 0008 — 답변 게이트 폐지).
"""

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from project_brain import tokenize_ko
from project_brain.embedder import StubEmbedder
from project_brain.id_grammar import format_id, parse_id
from project_brain.objbase import base
from project_brain.search import (
    _GRAPH_SUPPORT_CAP,
    _document_frequency,
    _graph_signals_by_id,
    _rerank_by_support,
    EVAL_CHANNEL_TOP_K,
    eval_recall,
    infer_scope,
    recall,
    rrf_fuse,
    UnknownScopeError,
)
from project_brain.search_index import StaleIndexError, rebuild, search_bm25_scoped
from project_brain.store import BrainStore
from project_brain.tokenize_ko import active_backend

T = "2026-06-04T00:00:00Z"


def _b(obj):
    return base(obj, tags=["neutral"], created_at=T, updated_at=T)


def _contextual_id(kind, object_id, context_id):
    """옛 short fixture 표기를 context/key가 닫힌 canonical 합성 ID로 만든다."""
    ctx = parse_id(context_id, "DomainContext").ctx
    key = object_id.rsplit(".", 1)[-1]
    if kind == "GlossaryTerm":
        return format_id(kind, ctx=ctx, key=key)
    if kind == "CodeLocator":
        return format_id(kind, ctx=ctx, anchor_key=key)
    if kind == "DomainMapping":
        return format_id(kind, ctx=ctx, key=key)
    if kind == "DecisionRecord":
        return format_id(kind, ctx=ctx, key=key)
    if kind == "Insight":
        return format_id(kind, ctx=ctx, key=key)
    raise AssertionError(f"unsupported fixture kind {kind}")


def _evidence_ref_id(context_id, anchor_key):
    ctx = parse_id(context_id, "DomainContext").ctx
    return format_id("EvidenceRef", ctx=ctx, anchor_key=anchor_key)


def glossary_term(tid, *, term, definition="정의", status="reviewed",
                  context_id="context.neutral", synonyms=None, aliases=None):
    tid = _contextual_id("GlossaryTerm", tid, context_id)
    obj = {
        "id": tid, "kind": "GlossaryTerm", "status": status, "truth_role": "domain",
        "title": f"Term: {term}", "context_id": context_id,
        "term": term, "definition": definition,
        "evidence_refs": (
            [_evidence_ref_id(context_id, "term")]
            if status == "reviewed"
            else []
        ),
    }
    if synonyms is not None:
        obj["synonyms"] = synonyms
    if aliases is not None:
        obj["aliases"] = aliases
    if status == "candidate":
        obj["candidate"] = {"candidate_state": "ready_for_review", "candidate_source": "spec"}
    return _b(obj)


def code_locator(cid, *, path, symbol, context_id="context.neutral"):
    cid = _contextual_id("CodeLocator", cid, context_id)
    return _b({
        "id": cid, "kind": "CodeLocator", "status": "reviewed", "truth_role": "reference",
        "title": f"Code: {symbol}", "context_id": context_id,
        "repo": "demoapp", "path": path, "symbol": symbol,
        "locator_source": "rg", "verified_at": T,
        "evidence_refs": [_evidence_ref_id(context_id, "code")],
    })


def domain_mapping(mid, *, meaning, glossary_term_ids=None, code_locator_ids=None,
                   decision_record_ids=None, status="reviewed",
                   context_id="context.neutral"):
    mid = _contextual_id("DomainMapping", mid, context_id)
    glossary_term_ids = [
        _contextual_id("GlossaryTerm", tid, context_id)
        for tid in (glossary_term_ids or [])
    ]
    code_locator_ids = [
        _contextual_id("CodeLocator", cid, context_id)
        for cid in (code_locator_ids or [])
    ]
    decision_record_ids = [
        _contextual_id("DecisionRecord", did, context_id)
        for did in (decision_record_ids or [])
    ]
    obj = {
        "id": mid, "kind": "DomainMapping", "status": status, "truth_role": "domain",
        "title": f"Mapping: {meaning}", "context_id": context_id,
        "mapping_key": parse_id(mid, "DomainMapping").key,
        "canonical_summary": meaning, "meaning": meaning,
        "boundary": "범위", "glossary_term_ids": glossary_term_ids,
        "decision_record_ids": decision_record_ids,
        "code_locator_ids": code_locator_ids,
        "evidence_refs": (
            [_evidence_ref_id(context_id, "mapping")]
            if status == "reviewed"
            else []
        ),
    }
    if status == "candidate":
        obj["candidate"] = {"candidate_state": "ready_for_review", "candidate_source": "spec"}
    return _b(obj)


def decision_record(did, *, summary, affected_glossary_term_ids=None,
                    affected_mapping_ids=None, context_id="context.neutral"):
    did = _contextual_id("DecisionRecord", did, context_id)
    obj = {
        "id": did, "kind": "DecisionRecord", "status": "reviewed", "truth_role": "event",
        "title": f"Decision: {summary}", "context_id": context_id,
        "decision_type": "naming_decision", "summary": summary, "decision": summary,
        "source_object_ids": [], "affected_context_ids": [], "spec_reflected": "yes",
        "evidence_refs": [_evidence_ref_id(context_id, "decision")],
    }
    if affected_glossary_term_ids is not None:
        obj["affected_glossary_term_ids"] = [
            _contextual_id("GlossaryTerm", tid, context_id)
            for tid in affected_glossary_term_ids
        ]
    if affected_mapping_ids is not None:
        obj["affected_mapping_ids"] = [
            _contextual_id("DomainMapping", mid, context_id)
            for mid in affected_mapping_ids
        ]
    return _b(obj)


def build_store_dir(tmp: Path, objs) -> Path:
    for obj in objs:
        BrainStore.save_object(tmp, obj)
    return tmp


class RrfFuseTest(unittest.TestCase):
    """RRF 순수 함수 — 손계산 기대값으로 수식 검증(§3.4 score = Σ 1/(60+rank))."""

    def test_single_ranking_uses_one_based_rank(self):
        # ★표준 RRF는 1-기반★: 1등 → 1/(60+1), 2등 → 1/(60+2). 0-기반이면 유효 k=59가
        # 되어 "k=60 업계 표준" 주장과 어긋난다(2026-06-10 리뷰 반영). 6자리 반올림.
        fused = dict(rrf_fuse([["a", "b"]]))
        self.assertEqual(fused["a"], round(1.0 / 61, 6))
        self.assertEqual(fused["b"], round(1.0 / 62, 6))

    def test_object_in_two_rankings_sums(self):
        # "a"가 BM25 1등 + 벡터 2등 → 1/61 + 1/62 (반올림)
        fused = dict(rrf_fuse([["a", "b"], ["b", "a"]]))
        self.assertEqual(fused["a"], round(1.0 / 61 + 1.0 / 62, 6))
        self.assertEqual(fused["b"], round(1.0 / 62 + 1.0 / 61, 6))

    def test_k_parameter_changes_denominator(self):
        fused = dict(rrf_fuse([["a"]], k=10))
        self.assertEqual(fused["a"], round(1.0 / 11, 6))

    def test_returns_sorted_desc_with_object_id_tiebreak(self):
        # 동점이면 object_id 정렬(결정론, §3.4). 두 채널에서 a·b 모두 rank0이라 동점.
        fused = rrf_fuse([["b", "a"], ["a", "b"]])
        ids = [oid for oid, _ in fused]
        # 점수 동일 → object_id 오름차순
        self.assertEqual(ids, ["a", "b"])

    def test_empty_rankings(self):
        self.assertEqual(rrf_fuse([]), [])
        self.assertEqual(rrf_fuse([[], []]), [])


class RecallTest(unittest.TestCase):
    """recall() — BM25+벡터 RRF 융합 → §3 결과 계약(stub embedder, tmp 색인)."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()
        build_store_dir(self.brain, [
            glossary_term("g.race", term="레이스", definition="카약 경주 진행"),
            glossary_term("g.reward", term="보상", definition="레이스 종료 보상 지급"),
            glossary_term("g.cand", term="에러코드", definition="보상 미지급 에러",
                          status="candidate"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)

    def tearDown(self):
        self._td.cleanup()

    def test_returns_contract_shape(self):
        hits = recall("레이스 보상", db_path=self.db, embedder=self.embedder,
                      brain_root=self.brain)
        self.assertTrue(hits)
        for h in hits:
            self.assertEqual(
                set(h.keys()),
                {"object_id", "kind", "status", "context_id", "score",
                 "matched_via", "surface", "linked", "graph_reached", "graph_hits",
                 "graph_support"},
            )
            self.assertIn(h["matched_via"], {"bm25", "vector", "both"})
            self.assertEqual(
                set(h["linked"].keys()),
                {"code_locators", "evidence_ref_ids", "related_object_ids"},
            )
            # 이 fixture는 GlossaryTerm만이라 참조 엣지가 없어 linked는 비고
            # graph_reached=False (§3.5 — 참조 없는 객체는 빈 linked).
            self.assertEqual(h["linked"]["code_locators"], [])
            self.assertEqual(h["linked"]["related_object_ids"], [])
            self.assertFalse(h["graph_reached"])
            self.assertEqual(h["graph_hits"], 0)
            # 아웃바운드 엣지가 없으니 상호지지도 0 → 재정렬이 RRF 순위를 유지.
            self.assertEqual(h["graph_support"], 0)

    def test_matched_via_both_when_in_both_channels(self):
        # "레이스"는 BM25(표면 토큰)와 벡터(stub은 자기 표면 임베딩) 양쪽에서 g.race 적중.
        hits = recall("카약 경주 진행", db_path=self.db, embedder=self.embedder,
                      brain_root=self.brain)
        by_id = {h["object_id"]: h for h in hits}
        self.assertIn("g.neutral.race", by_id)
        self.assertEqual(by_id["g.neutral.race"]["matched_via"], "both")

    def test_descending_score_order_when_support_uniform(self):
        # 이 fixture는 아웃바운드 엣지가 없어 graph_support가 전부 0 → 재정렬 1순위 키가
        # 균일해 RRF 순위(=점수 내림차순)가 그대로 유지된다. 상호지지가 갈리면 점수
        # 내림차순이 깨질 수 있다(그 케이스는 GraphRerankTest가 검증).
        hits = recall("레이스 보상", db_path=self.db, embedder=self.embedder,
                      brain_root=self.brain)
        scores = [h["score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_deterministic(self):
        a = recall("레이스 보상 카약", db_path=self.db, embedder=self.embedder,
                   brain_root=self.brain)
        b = recall("레이스 보상 카약", db_path=self.db, embedder=self.embedder,
                   brain_root=self.brain)
        self.assertEqual(a, b)

    def test_surface_present(self):
        hits = recall("레이스", db_path=self.db, embedder=self.embedder,
                      brain_root=self.brain)
        for h in hits:
            self.assertTrue(h["surface"])

    def test_top30_truncation(self):
        # 31개 객체를 같은 토큰으로 적재 → 양채널이 다 매칭해도 top30만.
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name) / "brain"
        db = Path(td.name) / "index.db"
        build_store_dir(brain, [
            glossary_term(f"g.{i:02d}", term="레이스", definition="카약 경주")
            for i in range(31)
        ])
        rebuild(brain, db, embedder=self.embedder)
        hits = recall("레이스 카약 경주", db_path=db, embedder=self.embedder,
                      brain_root=brain)
        self.assertLessEqual(len(hits), 30)

    def test_empty_query_returns_empty(self):
        # 빈 문자열은 BM25(토큰 0)·벡터(search_vector가 falsy query 0건) 둘 다 비어 융합 0.
        self.assertEqual(
            recall("", db_path=self.db, embedder=self.embedder, brain_root=self.brain), [])

    def test_recall_reuses_given_store_without_reloading(self):
        # 후속 b(2026-06-11): 장수 라우터가 질의마다 코퍼스 전체를 다시 읽지 않게
        # 이미 로드한 store를 주입받는다 — 주면 BrainStore.load를 안 부르고,
        # 결과는 자체 로드 경로와 동일해야 한다.
        baseline = recall("레이스 보상", db_path=self.db, embedder=self.embedder,
                          brain_root=self.brain)
        store = BrainStore.load(self.brain)
        with mock.patch.object(BrainStore, "load",
                               side_effect=AssertionError("store 주입 시 재로드 금지")):
            injected = recall("레이스 보상", store=store, db_path=self.db,
                              embedder=self.embedder, brain_root=self.brain)
        self.assertEqual(injected, baseline)

    def test_scope_filters_bm25_channel_too(self):
        # scope는 벡터 채널(search_vector 후처리)뿐 아니라 BM25 채널 적중도 걸러야
        # 한다 — 융합 후 context_id 필터(2026-06-10 리뷰 반영: docstring만 있고
        # 코드가 없던 모순을 실구현으로).
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name) / "brain"
        db = Path(td.name) / "index.db"
        build_store_dir(brain, [
            glossary_term("g.in", term="레이스", context_id="context.a"),
            glossary_term("g.out", term="레이스", context_id="context.b"),
        ])
        rebuild(brain, db, embedder=self.embedder)
        hits = recall("레이스", scope="context.a", db_path=db, embedder=self.embedder,
                      brain_root=brain)
        ids = {h["object_id"] for h in hits}
        self.assertIn("g.a.in", ids)
        self.assertNotIn("g.b.out", ids)

    def test_single_channel_vector_only_when_bm25_has_no_tokens(self):
        # 토큰이 안 잡히는 질의("!!!")라 BM25는 0건이어도, 벡터는 KNN으로 행을 돌려준다 —
        # 단채널(벡터 단독) 동작 확인. stub은 의미를 못 담지만 항상 행을 돌려준다.
        hits = recall("!!!", db_path=self.db, embedder=self.embedder, brain_root=self.brain)
        self.assertTrue(hits)  # 벡터 단독으로라도 반환
        self.assertTrue(all(h["matched_via"] == "vector" for h in hits))


def scoped_context(cid, *, display_name, title, context_key):
    return _b({
        "id": format_id("DomainContext", ctx=context_key),
        "kind": "DomainContext", "status": "reviewed", "truth_role": "domain",
        "title": title, "context_key": context_key, "project_id": "p",
        "display_name": display_name, "boundary_summary": "경계",
        "in_scope": ["a"], "out_of_scope": ["b"],
        "injection_profile": {"default_audience": "coding-agent"},
        "glossary_term_ids": [], "evidence_refs": [],
    })


class InferScopeTest(unittest.TestCase):
    """infer_scope — 질의 표면에서 DomainContext 단일 특정(P2 3번 scope 자동 라우팅).

    표면 = display_name / title('도메인' 접미 제거) / context_key. 표면의 내용 토큰
    (2자 이상)이 전부 질의 토큰에 들어 있으면 그 컨텍스트가 언급된 것으로 본다.
    정확히 1개 매칭일 때만 scope를 돌려준다 — 0개·다중은 None(하드 필터는 보수적으로).
    표면은 토크나이저 백엔드 무관하게 공백 분리 명사로 구성(조사 분해는 실코퍼스 eval 몫).
    """

    def _store(self, contexts):
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name)
        build_store_dir(brain, contexts)
        return BrainStore.load(brain)

    def test_single_match_by_title_prefix(self):
        store = self._store([
            scoped_context("context.a", display_name="카약 레이스 이벤트",
                           title="카약 레이스 도메인", context_key="kayak-race"),
            scoped_context("context.b", display_name="클리어 토큰",
                           title="클리어 토큰 도메인", context_key="clear-token"),
        ])
        self.assertEqual(
            infer_scope("카약 레이스 보상이 안 들어왔대", store),
            "context.kayak-race",
        )

    def test_no_surface_match_returns_none(self):
        store = self._store([
            scoped_context("context.a", display_name="카약 레이스 이벤트",
                           title="카약 레이스 도메인", context_key="kayak-race"),
        ])
        self.assertIsNone(infer_scope("보상 지급 기준이 뭐야", store))

    def test_partial_surface_tokens_do_not_match(self):
        # 표면 토큰 일부만 있으면 비매칭 — "클리어"만으로 "클리어 토큰"을 특정하지 않는다
        # (s1 회귀의 골자: 미나 질의의 '스테이지 클리어'가 토큰 컨텍스트를 끌면 안 됨).
        store = self._store([
            scoped_context("context.b", display_name="클리어 토큰",
                           title="클리어 토큰 도메인", context_key="clear-token"),
        ])
        self.assertIsNone(infer_scope("스테이지 클리어 개수가 달라요", store))

    def test_multi_context_match_returns_none(self):
        store = self._store([
            scoped_context("context.a", display_name="카약 레이스 이벤트",
                           title="카약 레이스 도메인", context_key="kayak-race"),
            scoped_context("context.b", display_name="클리어 토큰",
                           title="클리어 토큰 도메인", context_key="clear-token"),
        ])
        self.assertIsNone(
            infer_scope("카약 레이스 중에 클리어 토큰 쓰면 어떻게 돼", store))

    def test_specific_surface_wins_over_subset_surface(self):
        # 구체 표면 우선(§3 결정 2): 시스템 컨텍스트 표면 {함정}이 기능 컨텍스트
        # 표면 {가시,함정}의 진부분집합이면, 더 구체적인 기능 컨텍스트가 단일
        # 특정된다. 기존 규칙은 둘 다 매칭→다중→None이라 핀포인트 질의가 scope 보호를
        # 잃었다(s1 회귀 재노출). maximal(다른 매칭의 진부분집합이 아닌 것)만 남긴다.
        store = self._store([
            scoped_context("context.spike", display_name="가시 함정",
                           title="가시 함정 도메인", context_key="trap-spike"),
            scoped_context("context.system", display_name="함정",
                           title="함정 도메인", context_key="trap-bubble-system"),
        ])
        self.assertEqual(
            infer_scope("가시 함정 상태", store), "context.trap-spike")

    def test_only_subset_surface_matched_is_single_scope(self):
        # 일반 질의(고유명 토큰 없음)는 시스템 컨텍스트 표면 {함정}만 매칭 → 시스템으로.
        store = self._store([
            scoped_context("context.spike", display_name="가시 함정",
                           title="가시 함정 도메인", context_key="trap-spike"),
            scoped_context("context.system", display_name="함정",
                           title="함정 도메인", context_key="trap-bubble-system"),
        ])
        self.assertEqual(
            infer_scope("함정 점수 처리", store),
            "context.trap-bubble-system",
        )

    def test_two_maximal_surfaces_returns_none(self):
        # maximal 표면이 2개(비포함 관계)면 여전히 None — 두 기능을 동시에 언급한 질의.
        store = self._store([
            scoped_context("context.spike", display_name="가시 함정",
                           title="가시 함정 도메인", context_key="trap-spike"),
            scoped_context("context.bomb", display_name="폭탄 함정",
                           title="폭탄 함정 도메인", context_key="trap-bomb"),
            scoped_context("context.system", display_name="함정",
                           title="함정 도메인", context_key="trap-bubble-system"),
        ])
        self.assertIsNone(infer_scope("가시 폭탄 함정 비교", store))

    def test_recall_auto_scope_filters_other_context(self):
        # recall(scope=None)이 질의 표면에서 컨텍스트를 단일 특정하면 하드 필터 적용.
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name) / "brain"
        db = Path(td.name) / "index.db"
        build_store_dir(brain, [
            scoped_context("context.a", display_name="카약 레이스 이벤트",
                           title="카약 레이스 도메인", context_key="kayak-race"),
            scoped_context("context.b", display_name="클리어 토큰",
                           title="클리어 토큰 도메인", context_key="clear-token"),
            glossary_term(
                "g.in",
                term="보상",
                context_id="context.kayak-race",
            ),
            glossary_term(
                "g.out",
                term="보상",
                context_id="context.clear-token",
            ),
        ])
        embedder = StubEmbedder()
        rebuild(brain, db, embedder=embedder)
        hits = recall("카약 레이스 보상 기준", db_path=db, embedder=embedder,
                      brain_root=brain)
        ids = {h["object_id"] for h in hits}
        self.assertIn("g.kayak-race.in", ids)
        self.assertNotIn("g.clear-token.out", ids)

    def test_recall_explicit_scope_wins_over_inference(self):
        # scope를 명시하면 추론하지 않는다 — 질의가 context.a 표면이어도 명시 b를 따른다.
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name) / "brain"
        db = Path(td.name) / "index.db"
        build_store_dir(brain, [
            scoped_context("context.a", display_name="카약 레이스 이벤트",
                           title="카약 레이스 도메인", context_key="kayak-race"),
            scoped_context("context.b", display_name="클리어 토큰",
                           title="클리어 토큰 도메인", context_key="clear-token"),
            glossary_term(
                "g.in",
                term="보상",
                context_id="context.kayak-race",
            ),
            glossary_term(
                "g.out",
                term="보상",
                context_id="context.clear-token",
            ),
        ])
        embedder = StubEmbedder()
        rebuild(brain, db, embedder=embedder)
        hits = recall(
            "카약 레이스 보상 기준",
            scope="context.clear-token",
            db_path=db,
                      embedder=embedder, brain_root=brain)
        ids = {h["object_id"] for h in hits}
        self.assertIn("g.clear-token.out", ids)
        self.assertNotIn("g.kayak-race.in", ids)


class RecallScopeOptionTest(unittest.TestCase):
    """회수 진입점의 scope 지정·해제 인자(#74).

    기본(scope=None, auto_scope=True)은 기존 자동 추론 그대로다. auto_scope=False는
    추론을 건너뛰고 전체 코퍼스를 회수하며, scope를 명시하면 추론과 무관하게 그
    컨텍스트만 회수한다. 명시한 scope가 코퍼스의 DomainContext id가 아니면 조용한
    0건 대신 UnknownScopeError로 거부한다(오타와 미적재를 구분 못 하는 침묵 방지).
    """

    def setUp(self):
        self._td = TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()
        build_store_dir(self.brain, [
            scoped_context("context.a", display_name="카약 레이스 이벤트",
                           title="카약 레이스 도메인", context_key="kayak-race"),
            scoped_context("context.b", display_name="클리어 토큰",
                           title="클리어 토큰 도메인", context_key="clear-token"),
            glossary_term("g.in", term="보상", context_id="context.kayak-race"),
            glossary_term("g.out", term="보상", context_id="context.clear-token"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)

    def _recall_ids(self, **kwargs):
        hits = recall("카약 레이스 보상 기준", db_path=self.db,
                      embedder=self.embedder, brain_root=self.brain, **kwargs)
        return {h["object_id"] for h in hits}

    def test_auto_scope_disabled_recalls_every_context(self):
        # 기본은 질의 표면이 context.kayak-race를 단일 특정해 하드 필터가 걸린다.
        self.assertNotIn("g.clear-token.out", self._recall_ids())
        loosened = self._recall_ids(auto_scope=False)
        self.assertIn("g.kayak-race.in", loosened)
        self.assertIn("g.clear-token.out", loosened)

    def test_explicit_scope_applies_even_when_auto_scope_is_off(self):
        # 해제는 "추론하지 마라"이지 "필터하지 마라"가 아니다 — 명시 scope는 그대로 걸린다.
        pinned = self._recall_ids(scope="context.clear-token", auto_scope=False)
        self.assertIn("g.clear-token.out", pinned)
        self.assertNotIn("g.kayak-race.in", pinned)

    def test_unknown_scope_id_is_rejected_and_names_known_contexts(self):
        with self.assertRaises(UnknownScopeError) as ctx:
            self._recall_ids(scope="context.nope")
        message = str(ctx.exception)
        self.assertIn("context.nope", message)
        self.assertIn("context.kayak-race", message)

    def test_non_context_object_id_is_not_a_valid_scope(self):
        # DomainContext가 아닌 객체 id는 어떤 적중의 context_id와도 같지 않아 조용히
        # 0건이 된다 — 그 침묵을 오류로 바꾼다.
        with self.assertRaises(UnknownScopeError):
            self._recall_ids(scope="g.kayak-race.in")

    def test_eval_recall_passes_scope_options_to_recall(self):
        loosened = eval_recall("카약 레이스 보상 기준", db_path=self.db,
                               embedder=self.embedder, brain_root=self.brain,
                               auto_scope=False)
        loosened_ids = {h["object_id"] for h in loosened["results"]}
        self.assertIn("g.kayak-race.in", loosened_ids)
        self.assertIn("g.clear-token.out", loosened_ids)

        pinned = eval_recall("카약 레이스 보상 기준", db_path=self.db,
                             embedder=self.embedder, brain_root=self.brain,
                             scope="context.clear-token")
        pinned_ids = {h["object_id"] for h in pinned["results"]}
        self.assertIn("g.clear-token.out", pinned_ids)
        self.assertNotIn("g.kayak-race.in", pinned_ids)

    def test_eval_recall_reports_how_the_applied_scope_was_decided(self):
        # #73의 scope 사실은 "실제로 걸린 하드 필터"를 신고한다 — #74의 지정·해제도
        # 같은 자리(_resolve_scope)를 지나므로 신고값과 적용값이 갈라지지 않는다.
        kwargs = dict(db_path=self.db, embedder=self.embedder, brain_root=self.brain)

        inferred = eval_recall("카약 레이스 보상 기준", **kwargs)
        self.assertEqual(inferred["scope"],
                         {"context_id": "context.kayak-race", "origin": "inferred"})

        pinned = eval_recall("카약 레이스 보상 기준",
                             scope="context.clear-token", **kwargs)
        self.assertEqual(pinned["scope"],
                         {"context_id": "context.clear-token", "origin": "explicit"})

    def test_disabled_inference_is_reported_apart_from_failed_inference(self):
        # ★필터 없음의 두 이유를 가른다★ — 호출자가 껐으면 "disabled", 추론이 돌았는데
        # 컨텍스트를 단일 특정 못 했으면 "none". context_id는 둘 다 None이라 이 값이
        # 아니면 에이전트가 다음 수(좁힐지, 질의를 바꿀지)를 고를 수 없다.
        kwargs = dict(db_path=self.db, embedder=self.embedder, brain_root=self.brain)

        # 같은 질의(추론하면 kayak-race로 좁혀지는)를 껐을 때 → disabled.
        released = eval_recall("카약 레이스 보상 기준", auto_scope=False, **kwargs)
        self.assertEqual(released["scope"], {"context_id": None, "origin": "disabled"})

        # 기능명이 없어 추론이 특정 못 하는 질의 → none.
        unmatched = eval_recall("보상 기준이 뭐야", **kwargs)
        self.assertEqual(unmatched["scope"], {"context_id": None, "origin": "none"})

        # 두 갈래를 같은 값으로 뭉개지 않는다(회귀 가드).
        self.assertNotEqual(released["scope"]["origin"], unmatched["scope"]["origin"])

        # 추론이 못 좁힌 질의를 명시로 껐을 때도 disabled다 — 이유는 호출자 쪽이다.
        both = eval_recall("보상 기준이 뭐야", auto_scope=False, **kwargs)
        self.assertEqual(both["scope"], {"context_id": None, "origin": "disabled"})

    def test_explicit_scope_is_the_scope_actually_applied(self):
        # 신고값과 적용값의 배관 가드: 신고된 context_id 밖 적중이 결과에 없어야 한다.
        pinned = eval_recall("카약 레이스 보상 기준", scope="context.clear-token",
                             db_path=self.db, embedder=self.embedder,
                             brain_root=self.brain)
        reported = pinned["scope"]["context_id"]
        for channel in ("results", "candidates"):
            for hit in pinned[channel]:
                if hit.get("context_id") is not None:
                    self.assertEqual(hit["context_id"], reported)

    def test_scope_guard_rejects_stale_schema_before_querying_documents(self):
        # ★색인 쿼리 전 스키마 버전 가드★(§4 규약, 2026-06-11 실사고) — 구버전 DDL은
        # 컬럼이 없어 SELECT가 원시 OperationalError로 터진다. scope 실존 가드도 다른
        # 색인 쿼리와 같은 순서를 지켜 rebuild 안내로 거부해야 한다.
        with sqlite3.connect(str(self.db)) as conn:
            conn.execute("UPDATE meta SET schema_version = 3")
            # v3에는 scope 후처리용 context_id 열이 없다 — 없는 열을 재현한다.
            conn.execute(
                "ALTER TABLE documents RENAME COLUMN context_id TO context_id_v3")
        with self.assertRaises(StaleIndexError) as ctx:
            self._recall_ids(scope="context.kayak-race")
        self.assertIn("rebuild", str(ctx.exception))

    def test_eval_recall_rejects_unknown_scope(self):
        with self.assertRaises(UnknownScopeError):
            eval_recall("카약 레이스 보상 기준", db_path=self.db,
                        embedder=self.embedder, brain_root=self.brain,
                        scope="context.nope")


class EvalRecallChannelTest(unittest.TestCase):
    """eval_recall() — reviewed→results / candidate→candidates 채널 분리(§7)."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()
        build_store_dir(self.brain, [
            glossary_term("g.race", term="레이스", definition="카약 경주 진행"),
            glossary_term("g.cand", term="보상에러", definition="레이스 보상 미지급",
                          status="candidate"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)

    def tearDown(self):
        self._td.cleanup()

    def test_channel_separation(self):
        resp = eval_recall("레이스 보상", db_path=self.db, embedder=self.embedder,
                           brain_root=self.brain)
        self.assertEqual(set(resp.keys()),
                         {"results", "candidates", "raw_excerpts",
                          "advisories", "projection_reuse",
                          # 회수 사실(#73) — 채널과 나란히 응답 최상위에 실린다.
                          "query_tokens", "scope"})
        result_ids = {h["object_id"] for h in resp["results"]}
        cand_ids = {h["object_id"] for h in resp["candidates"]}
        self.assertIn("g.neutral.race", result_ids)
        self.assertIn("g.neutral.cand", cand_ids)
        # reviewed는 candidates에, candidate는 results에 들어가지 않는다.
        self.assertNotIn("g.neutral.cand", result_ids)
        self.assertNotIn("g.neutral.race", cand_ids)
        for h in resp["results"]:
            self.assertEqual(h["status"], "reviewed")
        for h in resp["candidates"]:
            self.assertEqual(h["status"], "candidate")

    def test_channels_capped_at_five(self):
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name) / "brain"
        db = Path(td.name) / "index.db"
        objs = [glossary_term(f"g.r{i}", term="레이스", definition="카약 경주") for i in range(7)]
        objs += [glossary_term(f"g.c{i}", term="레이스보상", definition="카약 경주 보상",
                               status="candidate") for i in range(7)]
        build_store_dir(brain, objs)
        rebuild(brain, db, embedder=self.embedder)
        resp = eval_recall("레이스 카약 경주 보상", db_path=db, embedder=self.embedder,
                           brain_root=brain)
        self.assertLessEqual(len(resp["results"]), 5)
        self.assertLessEqual(len(resp["candidates"]), 5)

    def test_channel_top_k_argument_overrides_the_eval_measuring_unit(self):
        # 표시 상한은 호출 인자다(#74). ★기본값은 EVAL_CHANNEL_TOP_K(=5)로 둔다★ —
        # 평가 하네스(eval_harness.evaluate)는 recall_fn(query) 한 인자로만 부르므로
        # 이 기본값이 곧 하네스의 측정 단위이고, CLI만 자기 기본값을 넘긴다.
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name) / "brain"
        db = Path(td.name) / "index.db"
        build_store_dir(brain, [
            glossary_term(f"g.r{i}", term="레이스", definition="카약 경주")
            for i in range(7)
        ])
        rebuild(brain, db, embedder=self.embedder)
        kwargs = dict(db_path=db, embedder=self.embedder, brain_root=brain)

        self.assertEqual(
            len(eval_recall("레이스 카약 경주", **kwargs)["results"]),
            EVAL_CHANNEL_TOP_K,
        )
        self.assertEqual(
            len(eval_recall("레이스 카약 경주", channel_top_k=7, **kwargs)["results"]),
            7,
        )
        self.assertEqual(
            len(eval_recall("레이스 카약 경주", channel_top_k=2, **kwargs)["results"]),
            2,
        )

    def test_candidate_only_corpus_leaves_results_empty(self):
        # reviewed 적중이 없으면 results는 비고 candidates만 찬다 — 판정 플래그 없음.
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name) / "brain"
        db = Path(td.name) / "index.db"
        build_store_dir(brain, [
            glossary_term("g.only", term="레이스", definition="카약 경주", status="candidate"),
        ])
        rebuild(brain, db, embedder=self.embedder)
        resp = eval_recall("레이스 카약", db_path=db, embedder=self.embedder, brain_root=brain)
        self.assertEqual(resp["results"], [])
        self.assertIn("g.neutral.only", {h["object_id"] for h in resp["candidates"]})
        self.assertNotIn("needs_clarification", resp)

    def test_reviewed_hit_fills_results(self):
        resp = eval_recall("레이스", db_path=self.db, embedder=self.embedder,
                           brain_root=self.brain)
        # g.race(reviewed) 적중 → results 채워짐. 응답에 판정 플래그는 없다.
        self.assertTrue(resp["results"])
        self.assertNotIn("needs_clarification", resp)

    def test_missing_db_raises_clear_error(self):
        missing = Path(self._td.name) / "nonexistent.db"
        with self.assertRaises(Exception) as ctx:
            eval_recall("레이스", db_path=missing, embedder=self.embedder, brain_root=self.brain)
        self.assertIn("index rebuild", str(ctx.exception))


class EvalRecallQueryFactsTest(unittest.TestCase):
    """eval_recall 회수 사실(#73) — 질의 토큰 분해·토큰별 df·적중별 겹친 질의 토큰.

    ADR 0008: 엔진은 회수만 하고 답변 판정은 에이전트가 한다. 여기 사실은 전부
    결정론 계산이고 판정이 아니다 — 어떤 값도 boolean 판정이 아니다.
    토큰 분해가 형태소 백엔드 설치 여부에 흔들리지 않게 ★정규식 폴백을 강제★한다
    (색인·질의가 같은 tokenize를 쓰므로 rebuild 전에 고정해야 한다).
    """

    def setUp(self):
        self._saved_name = tokenize_ko._BACKEND_NAME
        self._saved_split = tokenize_ko._KOREAN_SPLITTER
        tokenize_ko._BACKEND_NAME = "regex"
        tokenize_ko._KOREAN_SPLITTER = tokenize_ko._regex_splitter
        self.addCleanup(self._restore_backend)
        self._td = TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()
        src = self.brain / "raw" / "sources" / "foo-ctx"
        src.mkdir(parents=True)
        # 헤더 2개 = 청크 2개. 첫 청크에만 "레이스", 둘째 청크에만 "보상"이 있다.
        (src / "spec.md").write_text(
            "# 레이스 안내\n레이스 진행 안내 문구.\n\n# 지급 안내\n보상 지급 안내 문구.\n",
            encoding="utf-8")
        build_store_dir(self.brain, [
            # "레이스"는 객체 2개(term + 다른 객체 definition)에, "보상"은 1개에만 있다.
            glossary_term("g.race", term="레이스", definition="카약 경주 진행"),
            glossary_term("g.reward", term="보상", definition="레이스 보상 지급 기준"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)

    def _restore_backend(self):
        tokenize_ko._BACKEND_NAME = self._saved_name
        tokenize_ko._KOREAN_SPLITTER = self._saved_split

    def test_query_tokens_report_object_df_and_raw_df(self):
        resp = eval_recall("레이스 보상 크리스마스", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        # 분해 결과는 tokenize 순서·중복 제거를 그대로 노출한다(길이 필터 없음).
        self.assertEqual([f["token"] for f in resp["query_tokens"]],
                         ["레이스", "보상", "크리스마스"])
        facts = {f["token"]: f for f in resp["query_tokens"]}
        self.assertEqual(facts["레이스"]["object_df"], 2)
        self.assertEqual(facts["레이스"]["raw_df"], 1)
        self.assertEqual(facts["보상"]["object_df"], 1)
        self.assertEqual(facts["보상"]["raw_df"], 1)
        # 부재 토큰: 객체에도 raw에도 없다 → 0/0(판정이 아니라 사실).
        self.assertEqual(facts["크리스마스"]["object_df"], 0)
        self.assertEqual(facts["크리스마스"]["raw_df"], 0)

    def test_query_tokens_separate_object_absence_from_raw_presence(self):
        # 객체 표면엔 없고 raw 청크에만 있는 토큰은 object_df 0 · raw_df>0으로 갈린다
        # ("객체로는 없지만 기획서에는 있다" ≠ "어디에도 없다").
        resp = eval_recall("문구", db_path=self.db, embedder=self.embedder,
                           brain_root=self.brain)
        facts = {f["token"]: f for f in resp["query_tokens"]}
        self.assertEqual(facts["문구"]["object_df"], 0)
        self.assertEqual(facts["문구"]["raw_df"], 2)

    def test_empty_query_reports_no_tokens(self):
        resp = eval_recall("!!!", db_path=self.db, embedder=self.embedder,
                           brain_root=self.brain)
        self.assertEqual(resp["query_tokens"], [])

    def test_hits_report_query_tokens_present_in_indexed_text(self):
        resp = eval_recall("레이스 보상 크리스마스", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        by_id = {h["object_id"]: h for h in resp["results"]}
        # g.race 색인 본문 = "레이스 카약 경주 진행" → 질의 토큰 중 "레이스"만 겹친다.
        self.assertEqual(by_id["g.neutral.race"]["matched_query_tokens"], ["레이스"])
        # g.reward 색인 본문 = "보상 레이스 보상 지급 기준" → 질의 순서대로 둘 다.
        self.assertEqual(by_id["g.neutral.reward"]["matched_query_tokens"],
                         ["레이스", "보상"])
        # 코퍼스에 없는 토큰은 어느 적중에도 나타나지 않는다.
        for hit in resp["results"]:
            self.assertNotIn("크리스마스", hit["matched_query_tokens"])

    def test_raw_excerpt_hits_report_matched_query_tokens(self):
        resp = eval_recall("레이스 보상 크리스마스", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        matched = {h["object_id"]: h["matched_query_tokens"]
                   for h in resp["raw_excerpts"]}
        self.assertEqual(matched["raw.foo-ctx.spec#000"], ["레이스"])
        self.assertEqual(matched["raw.foo-ctx.spec#001"], ["보상"])


class EvalRecallScopeFactTest(unittest.TestCase):
    """eval_recall이 적용된 scope를 신고한다(#73) — context_id와 적용 출처.

    출처는 boolean이 아니라 문자열이다(어떤 사실 필드도 boolean 판정이 아니다).
    """

    def setUp(self):
        self._td = TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()
        build_store_dir(self.brain, [
            scoped_context("context.a", display_name="카약 레이스 이벤트",
                           title="카약 레이스 도메인", context_key="kayak-race"),
            scoped_context("context.b", display_name="클리어 토큰",
                           title="클리어 토큰 도메인", context_key="clear-token"),
            glossary_term("g.in", term="보상", context_id="context.kayak-race"),
            glossary_term("g.out", term="보상", context_id="context.clear-token"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)

    def test_reports_inferred_context_id(self):
        resp = eval_recall("카약 레이스 보상 기준", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        self.assertEqual(resp["scope"],
                         {"context_id": "context.kayak-race", "origin": "inferred"})
        # 신고한 scope가 실제로 적용된 하드 필터와 같다.
        self.assertNotIn("g.clear-token.out",
                         {h["object_id"] for h in resp["results"]})

    def test_reports_absent_scope_without_boolean(self):
        resp = eval_recall("보상 기준", db_path=self.db, embedder=self.embedder,
                           brain_root=self.brain)
        self.assertEqual(resp["scope"], {"context_id": None, "origin": "none"})


class GraphOneHopTest(unittest.TestCase):
    """그래프 1-hop 동반(§3.5) — linked 채움 + graph_reached/graph_hits 분리 신호.

    매핑→용어/CodeLocator/결정 참조 픽스처를 tmp store에 적재하고, recall이 적중
    객체의 참조 필드를 1-hop 따라 linked를 채우는지, 도달 횟수를 세는지, dangling id를
    건너뛰는지, surface가 원문인지, 결정론인지를 본다(전부 stub embedder).
    """

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()
        build_store_dir(self.brain, [
            # 매핑 → 용어 2개 + CodeLocator 2개 참조(둘 다 실존).
            domain_mapping(
                "m.popup",
                meaning="시작 팝업 스테이지 개수 안내",
                glossary_term_ids=["g.target", "g.popup", "g.dangling"],  # g.dangling은 store에 없음
                code_locator_ids=["code.init", "code.contents", "code.dangling"],
            ),
            glossary_term("g.target", term="targetStages", definition="시작 팝업 스테이지 개수"),
            glossary_term("g.popup", term="시작 팝업", definition="시작 팝업 안내"),
            code_locator("code.init", path="a/Popup.cpp", symbol="StartAlert::init"),
            code_locator("code.contents", path="a/Popup.cpp", symbol="StartAlert::makeContents"),
            # 참조 엣지가 전혀 없는 외톨이 매핑(빈 linked·graph_reached=False 확인).
            domain_mapping("m.alone", meaning="외톨이 매핑 시작 팝업"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)

    def tearDown(self):
        self._td.cleanup()

    def _by_id(self, query):
        hits = recall(query, db_path=self.db, embedder=self.embedder, brain_root=self.brain)
        return {h["object_id"]: h for h in hits}

    def test_linked_code_locators_are_objects_with_path_symbol(self):
        # linked CodeLocator는 정본 4필드만 노출한다. title은 표시용이고,
        # principal/ACL evaluator가 없는 제품 기본 경로에서는 quote를 절대 내보내지 않는다.
        by_id = self._by_id("시작 팝업 스테이지 개수 안내")
        self.assertIn("mapping.neutral.popup", by_id)
        locators = by_id["mapping.neutral.popup"]["linked"]["code_locators"]
        by_loc = {c["object_id"]: c for c in locators}
        # dangling(code.dangling)은 빠지고 실존 2개만.
        self.assertEqual(
            set(by_loc),
            {"code.neutral.init", "code.neutral.contents"},
        )
        self.assertEqual(by_loc["code.neutral.init"]["path"], "a/Popup.cpp")
        self.assertEqual(
            by_loc["code.neutral.init"]["symbol"],
            "StartAlert::init",
        )
        self.assertEqual(
            by_loc["code.neutral.init"],
            {
                "object_id": "code.neutral.init",
                "path": "a/Popup.cpp",
                "symbol": "StartAlert::init",
                "quote_access": "indeterminate",
            },
        )

    def test_linked_locator_never_leaks_title_or_verified_quote_without_principal(self):
        locator = self.brain / "objects" / "code" / "code.neutral.init.json"
        payload = BrainStore.load(self.brain).get("code.neutral.init")
        payload["verified_quote"] = "void StartAlert::init()"
        locator.write_bytes(BrainStore.object_bytes(payload))
        rebuild(self.brain, self.db, embedder=self.embedder)

        linked = self._by_id("시작 팝업 스테이지 개수 안내")[
            "mapping.neutral.popup"
        ]["linked"]["code_locators"]
        entry = next(c for c in linked if c["object_id"] == "code.neutral.init")
        self.assertNotIn("title", entry)
        self.assertNotIn("verified_quote", entry)
        self.assertNotIn("quote", entry)
        self.assertEqual(entry["quote_access"], "indeterminate")

    def test_linked_related_object_ids_from_glossary_edges(self):
        # glossary_term_ids → related_object_ids. dangling(g.dangling) 건너뜀.
        by_id = self._by_id("시작 팝업 스테이지 개수 안내")
        related = by_id["mapping.neutral.popup"]["linked"]["related_object_ids"]
        by_rel = {r["object_id"]: r for r in related}
        self.assertIn("g.neutral.target", by_rel)
        self.assertIn("g.neutral.popup", by_rel)
        self.assertNotIn("g.neutral.dangling", by_rel)
        # 이웃 dict에 제목 동반(C-2) — id만으론 무엇인지 가늠 어려움.
        self.assertEqual(by_rel["g.neutral.popup"]["title"], "Term: 시작 팝업")

    def test_linked_evidence_ref_ids_display_only(self):
        # evidence_refs는 표시 전용으로 동반(랭킹 입력 아님 — 여기선 동반 여부만 확인).
        by_id = self._by_id("시작 팝업 스테이지 개수 안내")
        self.assertEqual(
            by_id["mapping.neutral.popup"]["linked"]["evidence_ref_ids"],
            ["evref.neutral.mapping"],
        )

    def test_object_without_references_has_empty_linked(self):
        # 참조 엣지가 없는 m.alone은 빈 linked·graph_reached=False.
        by_id = self._by_id("외톨이 매핑 시작 팝업")
        self.assertIn("mapping.neutral.alone", by_id)
        linked = by_id["mapping.neutral.alone"]["linked"]
        self.assertEqual(linked["code_locators"], [])
        self.assertEqual(linked["related_object_ids"], [])
        self.assertFalse(by_id["mapping.neutral.alone"]["graph_reached"])
        self.assertEqual(by_id["mapping.neutral.alone"]["graph_hits"], 0)

    def test_graph_hits_counts_mutual_reach_in_top30(self):
        # m.popup이 top30에 함께 든 g.target/g.popup/code.init/code.contents 4개를
        # 가리키면 m.popup의 graph_hits=4(양방향 — 각 피참조 객체도 +1).
        by_id = self._by_id("시작 팝업 스테이지 개수 안내 targetStages StartAlert init makeContents")
        self.assertIn("mapping.neutral.popup", by_id)
        # 적중집합에 4개 피참조가 다 들어왔는지 먼저 확인(안 들어오면 도달이 안 세짐).
        reached_in_set = [
            oid
            for oid in (
                "g.neutral.target",
                "g.neutral.popup",
                "code.neutral.init",
                "code.neutral.contents",
            )
                          if oid in by_id]
        # ★리터럴 고정(리뷰 반영)★: stub 벡터 채널이 전 행을 반환하므로 4개 전부
        # 적중집합에 있어야 한다 — 채널 회귀로 빠지면 expected가 조용히 줄어
        # 공허 통과하는 것을 막는다.
        self.assertEqual(len(reached_in_set), 4)
        expected = len(reached_in_set)
        self.assertEqual(
            by_id["mapping.neutral.popup"]["graph_hits"],
            expected,
        )
        self.assertEqual(
            by_id["mapping.neutral.popup"]["graph_reached"],
            expected > 0,
        )
        # 양방향: 피참조 객체도 m.popup으로부터 도달 1회씩.
        for oid in reached_in_set:
            self.assertGreaterEqual(by_id[oid]["graph_hits"], 1)
            self.assertTrue(by_id[oid]["graph_reached"])

    def test_evidence_refs_not_in_graph_reach(self):
        # evidence_refs(evref.neutral.mapping 등)는 그래프 도달에서 제외 —
        # m.alone은 evidence_refs가
        # 있어도 graph_reached=False(다른 적중을 엣지로 안 가리킴).
        by_id = self._by_id("외톨이 매핑 시작 팝업")
        self.assertEqual(
            by_id["mapping.neutral.alone"]["linked"]["evidence_ref_ids"],
            ["evref.neutral.mapping"],
        )
        self.assertFalse(by_id["mapping.neutral.alone"]["graph_reached"])

    def test_surface_is_original_not_tokenized(self):
        # surface 승급(과업 3번): tokenized_text(공백 분리 토큰)가 아니라 extract_surface
        # 원문. 용어 g.target의 표면은 정의 원문 "시작 팝업 스테이지 개수"를 포함한다.
        by_id = self._by_id("targetStages 시작 팝업 스테이지 개수")
        self.assertIn("g.neutral.target", by_id)
        self.assertIn(
            "시작 팝업 스테이지 개수",
            by_id["g.neutral.target"]["surface"],
        )

    def test_decision_record_affected_edges_as_related(self):
        # affected_glossary_term_ids / affected_mapping_ids도 related_object_ids로.
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name) / "brain"
        db = Path(td.name) / "index.db"
        build_store_dir(brain, [
            decision_record("dec.switch", summary="다음 레벨 전환 결정",
                            affected_glossary_term_ids=["g.next"],
                            affected_mapping_ids=["m.join"]),
            glossary_term("g.next", term="다음 레벨", definition="다음 레벨 전환"),
            domain_mapping("m.join", meaning="레이스 참가 다음 레벨"),
        ])
        rebuild(brain, db, embedder=self.embedder)
        hits = recall("다음 레벨 전환 결정", db_path=db, embedder=self.embedder, brain_root=brain)
        by_id = {h["object_id"]: h for h in hits}
        self.assertIn("decision.neutral.switch", by_id)
        related = by_id["decision.neutral.switch"]["linked"]["related_object_ids"]
        related_ids = {r["object_id"] for r in related}
        self.assertIn("g.neutral.next", related_ids)
        self.assertIn("mapping.neutral.join", related_ids)

    def test_deterministic_with_graph(self):
        a = recall("시작 팝업 스테이지 개수 안내", db_path=self.db,
                   embedder=self.embedder, brain_root=self.brain)
        b = recall("시작 팝업 스테이지 개수 안내", db_path=self.db,
                   embedder=self.embedder, brain_root=self.brain)
        self.assertEqual(a, b)


class GraphRerankTest(unittest.TestCase):
    """그래프 상호지지 재정렬(§3.5 후반·§8) — capped graph_support 1순위 사전식 정렬.

    캡 값 자체를 고정하는 테스트 포함(§8 "계수는 코드 상수+테스트로 고정" — 값 단언이
    없으면 캘리브레이션 결과가 단위 스위트에서 침묵 드리프트, 2026-06-10 리뷰 반영).

    재정렬 규칙(_rerank_by_support)과 방향 신호 분리(_graph_signals_by_id)를 합성
    입력으로 결정론 검증한다(임베더 불필요 — 순수 함수). 실모델 순위 변화는 cli eval
    측정 보고 몫(과업 명세). 캡이 허브를 누르는지가 핵심 검증 포인트(과업 3번).
    """

    def test_cap_value_pinned_to_calibration(self):
        # §8 "계수는 코드 상수+테스트로 고정" — 값 단언이 없으면 캡이 바뀌어도 단위
        # 스위트가 전부 green이라(다른 테스트는 심볼릭 사용) 침묵 드리프트한다.
        # 2는 2026-06-10 실모델 캘리브레이션 값(s1 10등→4등·s2 9등→3등, 1~3 폭 안정).
        # 바꾸려면 실모델 cli eval 재측정 후 이 단언을 같이 갱신할 것.
        self.assertEqual(_GRAPH_SUPPORT_CAP, 2)

    def test_support_object_overtakes_higher_rrf_zero_support(self):
        # RRF 순위: a(0)·b(1)·c(2). c만 상호지지 2 → c가 a·b를 추월해 1등.
        order = _rerank_by_support(["a", "b", "c"], {"a": 0, "b": 0, "c": 2})
        self.assertEqual(order[0], "c")
        # a·b는 상호지지 0 동점 → 원래 RRF 순위(a<b) 유지.
        self.assertEqual(order[1:], ["a", "b"])

    def test_cap_neutralizes_hub_fanout(self):
        # ★허브 가드(과업 3번)★: hub는 상호지지 10(엣지 폭발)이지만 캡(_GRAPH_SUPPORT_CAP)
        # 으로 잘려 초점 매핑 focus(상호지지 = 캡)와 같은 1순위 키가 된다. 따라서 둘 사이
        # 순서는 원래 RRF 순위가 가른다 — focus가 RRF로 hub보다 위면 hub가 그래프 신호로
        # focus를 추월하지 못한다(허브가 더 굳어지지 않음).
        order = _rerank_by_support(
            ["focus", "hub"],
            {"focus": _GRAPH_SUPPORT_CAP, "hub": 10},
        )
        self.assertEqual(order, ["focus", "hub"])

    def test_cap_does_not_let_hub_jump_lower_rrf_focus(self):
        # hub가 RRF 2등이고 focus(상호지지=캡)가 RRF 3등이어도, 캡 동점이라 RRF 순위가
        # 갈라 hub(2등)가 focus(3등) 위 — 캡이 허브를 ★올려주지 않는다★(부풀림 차단).
        # 단 상호지지 0인 RRF 1등 lead는 둘 다에게 밀린다(상호지지 신호 우선).
        order = _rerank_by_support(
            ["lead", "hub", "focus"],
            {"lead": 0, "hub": 10, "focus": _GRAPH_SUPPORT_CAP},
        )
        self.assertEqual(order, ["hub", "focus", "lead"])

    def test_tiebreak_by_object_id_when_support_and_rank_equal(self):
        # 같은 상호지지 + 같은 원래 순위는 불가능하지만(순위는 유일), 상호지지가 같으면
        # 원래 RRF 순위로, 그게 없으면 object_id로 깬다(§5 결정론). 여기선 순위로 갈림.
        order = _rerank_by_support(["b", "a"], {"a": 1, "b": 1})
        # 둘 다 상호지지 1 동점 → 원래 순위(b=0, a=1) 유지.
        self.assertEqual(order, ["b", "a"])

    def test_rerank_is_deterministic(self):
        ids = ["m", "n", "o", "p"]
        sup = {"m": 0, "n": 2, "o": 1, "p": 2}
        self.assertEqual(_rerank_by_support(ids, sup), _rerank_by_support(ids, sup))

    def test_signals_split_outbound_vs_bidirectional(self):
        # _graph_signals_by_id: m.popup이 g.t·code.i 둘을 가리킴(둘 다 적중집합).
        # graph_hits(양방향): m.popup +2, g.t +1, code.i +1.
        # graph_support(아웃바운드): m.popup만 2, g.t·code.i는 0(피참조만).
        with TemporaryDirectory() as name:
            brain = Path(name) / "brain"
            build_store_dir(brain, [
                domain_mapping("m.popup", meaning="시작 팝업",
                               glossary_term_ids=["g.t"], code_locator_ids=["code.i"]),
                glossary_term("g.t", term="targetStages", definition="개수"),
                code_locator("code.i", path="a/P.cpp", symbol="init"),
            ])
            store = BrainStore.load(brain)
            hit_ids = [
                "mapping.neutral.popup",
                "g.neutral.t",
                "code.neutral.i",
            ]
            hits, support = _graph_signals_by_id(hit_ids, store)
            self.assertEqual(
                hits,
                {
                    "mapping.neutral.popup": 2,
                    "g.neutral.t": 1,
                    "code.neutral.i": 1,
                },
            )
            self.assertEqual(
                support,
                {
                    "mapping.neutral.popup": 2,
                    "g.neutral.t": 0,
                    "code.neutral.i": 0,
                },
            )

    def test_recall_focused_mapping_overtakes_leaf_term(self):
        # 통합: 적중집합 안에서 매핑이 자기 코드/용어를 되찾으면(graph_support>0),
        # 아웃바운드 0인 잎 용어보다 위로 재정렬돼 반환된다. graph_support 키도 동반.
        with TemporaryDirectory() as name:
            brain = Path(name) / "brain"
            db = Path(name) / "index.db"
            embedder = StubEmbedder()
            build_store_dir(brain, [
                domain_mapping("m.lanes", meaning="레인 영역 배치",
                               glossary_term_ids=["g.lane"],
                               code_locator_ids=["code.lane"]),
                glossary_term("g.lane", term="레인", definition="레인 영역 배치"),
                code_locator("code.lane", path="a/Lane.cpp", symbol="makeLanes"),
            ])
            rebuild(brain, db, embedder=embedder)
            hits = recall("레인 영역 배치", db_path=db, embedder=embedder, brain_root=brain)
            by_id = {h["object_id"]: h for h in hits}
            self.assertIn("mapping.neutral.lanes", by_id)
            # 매핑은 적중집합 안의 g.lane·code.lane을 가리켜 상호지지 2(>0).
            self.assertGreater(
                by_id["mapping.neutral.lanes"]["graph_support"],
                0,
            )
            # 잎 용어 g.lane은 아웃바운드 0 → graph_support 0.
            self.assertEqual(by_id["g.neutral.lane"]["graph_support"], 0)
            order = [h["object_id"] for h in hits]
            # 매핑이 잎 용어보다 앞(상호지지 재정렬 결과).
            self.assertLess(
                order.index("mapping.neutral.lanes"),
                order.index("g.neutral.lane"),
            )


class EvalRecallStatusKindChannelTest(unittest.TestCase):
    """eval_recall 채널 배치는 ★검수 상태와 객체 종류★만으로 갈린다(ADR 0008, #77).

    답변 게이트를 폐지했으므로 질의 어휘가 흔하든 명부에 없든 회수된 검수 객체는
    results로 나온다 — 그것이 답인지는 에이전트가 회수 결과와 사실을 보고 판정한다.
    토큰 분해가 형태소 백엔드 설치 여부에 흔들리지 않게 ★정규식 폴백을 강제★한다
    (색인·질의가 같은 tokenize를 쓰므로 rebuild 전에 고정해야 한다).
    """

    def setUp(self):
        self._saved_name = tokenize_ko._BACKEND_NAME
        self._saved_split = tokenize_ko._KOREAN_SPLITTER
        tokenize_ko._BACKEND_NAME = "regex"
        tokenize_ko._KOREAN_SPLITTER = tokenize_ko._regex_splitter
        self.addCleanup(self._restore_backend)
        self._td = TemporaryDirectory()
        self.embedder = StubEmbedder()

    def _restore_backend(self):
        tokenize_ko._BACKEND_NAME = self._saved_name
        tokenize_ko._KOREAN_SPLITTER = self._saved_split

    def tearDown(self):
        self._td.cleanup()

    def _build(self, objs):
        brain = Path(self._td.name) / "brain"
        db = Path(self._td.name) / "index.db"
        build_store_dir(brain, objs)
        rebuild(brain, db, embedder=self.embedder)
        return brain, db

    def test_common_token_query_still_returns_reviewed_results(self):
        # 옛 게이트가 막던 형태의 재현: 질의의 유일한 희소 엔티티가 코퍼스에 없고
        # ('없는엔티티') 남는 토큰('보상')은 35개 문서에 흔하다. 명부 표면형도 질의에
        # 없다. 게이트 시절엔 전 채널 0건이었지만, 이제 reviewed·candidate 적중이
        # 그대로 채널에 오른다.
        objs = [glossary_term(f"g.common{i}", term="보상", definition="흔한 보상 토큰")
                for i in range(35)]
        objs += [glossary_term(f"g.cand{i}", term="보상", definition="흔한 보상 토큰",
                               status="candidate") for i in range(3)]
        brain, db = self._build(objs)
        resp = eval_recall("없는엔티티 보상", db_path=db, embedder=self.embedder,
                           brain_root=brain)
        self.assertTrue(resp["results"])
        self.assertTrue(all(h["status"] == "reviewed" for h in resp["results"]))
        self.assertTrue(resp["candidates"])
        self.assertTrue(all(h["status"] == "candidate" for h in resp["candidates"]))
        # 부재 엔티티는 숨기는 대신 사실로 신고한다 — 판정은 에이전트 몫(#73).
        facts = {f["token"]: f for f in resp["query_tokens"]}
        self.assertEqual(facts["없는엔티티"]["object_df"], 0)

    def test_no_glossary_registry_in_corpus_still_fills_results(self):
        # 코퍼스에 GlossaryTerm이 하나도 없어도 회수된 reviewed 객체는 results에
        # 오른다 — 채널 배치가 어휘 명부를 전혀 참조하지 않는다는 가드.
        brain, db = self._build([
            domain_mapping("mapping.flow", meaning="아이템 사용 처리 흐름"),
        ])
        resp = eval_recall("아이템 사용하면 어떤 흐름으로 처리돼", db_path=db,
                           embedder=self.embedder, brain_root=brain)
        self.assertIn("mapping.neutral.flow",
                      {h["object_id"] for h in resp["results"]})

    def test_candidate_channel_survives_when_reviewed_empty(self):
        # candidate만 적중 → results 빈, candidates 채워짐(§7 채널 분리 유지).
        brain, db = self._build([
            glossary_term("g.only", term="레인", definition="레인 영역 배치",
                          status="candidate"),
        ])
        resp = eval_recall("레인 영역 배치", db_path=db, embedder=self.embedder,
                           brain_root=brain)
        self.assertEqual(resp["results"], [])
        self.assertIn(
            "g.neutral.only",
            {h["object_id"] for h in resp["candidates"]},
        )


class RawLaneTest(unittest.TestCase):
    """raw 본문 색인의 검색 통합(스펙 §2.2, 2026-06-11) — raw는 객체 레인과 분리된
    별도 레인: 객체 융합·그래프·재정렬 파이프라인을 일절 흔들지 않고, eval_recall이
    raw_excerpts 채널("원문 발췌(미검수)")로 따로 가른다. 전부 stub embedder."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()

    def tearDown(self):
        self._td.cleanup()

    def _write_raw(self, ctx: str, name: str, text: str):
        src = self.brain / "raw" / "sources" / ctx
        src.mkdir(parents=True, exist_ok=True)
        (src / f"{name}.md").write_text(text, encoding="utf-8")

    def _build(self, objs):
        build_store_dir(self.brain, objs)
        rebuild(self.brain, self.db, embedder=self.embedder)

    def test_recall_appends_raw_hits_after_objects_with_original_text(self):
        self._write_raw("foo-ctx", "spec",
                        "# 광고 버튼\n광고 시청 버튼은 빈 보유량 상태에서 노출 비율을 줄인다.\n")
        self._build([glossary_term("g.ad", term="광고 버튼", definition="광고 시청 버튼")])
        hits = recall("광고 시청 버튼 노출", db_path=self.db, embedder=self.embedder,
                      brain_root=self.brain)
        kinds = [h["kind"] for h in hits]
        self.assertIn("raw_chunk", kinds)
        # raw는 객체 뒤 별도 레인 — 첫 raw 이후에 객체가 나오지 않는다.
        first_raw = kinds.index("raw_chunk")
        self.assertTrue(all(k == "raw_chunk" for k in kinds[first_raw:]))
        raw_hit = hits[first_raw]
        self.assertEqual(raw_hit["status"], "raw")
        self.assertIn("광고 시청 버튼", raw_hit["surface"])  # 원문 발췌
        self.assertEqual(raw_hit["linked"]["code_locators"], [])
        self.assertEqual(raw_hit["graph_support"], 0)

    def test_raw_flood_does_not_crowd_object_lane(self):
        # raw 청크가 융합 top-30을 잠식해 객체(그래프 재정렬 입력)를 밀어내면 안 된다 —
        # 같은 토큰의 raw 문서 60개가 있어도 객체 적중은 그대로 살아남는다(레인 분리).
        big = "\n\n".join(f"# 섹션 {i}\n레이스 보상 지급 서술 {i}." for i in range(60))
        self._write_raw("foo-ctx", "spec", big)
        self._build([glossary_term("g.race", term="레이스", definition="레이스 보상 지급")])
        hits = recall("레이스 보상 지급", db_path=self.db, embedder=self.embedder,
                      brain_root=self.brain)
        object_ids = [h["object_id"] for h in hits if h["kind"] != "raw_chunk"]
        self.assertIn("g.neutral.race", object_ids)

    def test_object_df_excludes_raw_rows(self):
        # 회수 사실의 객체 df(#73)는 raw 청크를 세지 않는다 — "객체로는 없지만
        # 기획서에는 있다"를 raw df와 갈라 보고하려면 두 수가 분리돼야 한다.
        # 같은 토큰의 raw 문서 40개가 있어도 객체 df는 1이다.
        big = "\n\n".join(f"# 섹션 {i}\n레이스 서술 {i}." for i in range(40))
        self._write_raw("foo-ctx", "spec", big)
        self._build([glossary_term("g.race", term="레이스", definition="카약 경주")])
        conn = sqlite3.connect(str(self.db))
        try:
            self.assertEqual(_document_frequency(conn, "레이스"), 1)
        finally:
            conn.close()

    def test_eval_recall_raw_excerpts_channel(self):
        self._write_raw("foo-ctx", "spec",
                        "# 광고 버튼\n광고 시청 버튼은 빈 보유량 상태에서 노출 비율을 줄인다.\n")
        self._build([glossary_term("g.ad", term="광고 버튼", definition="광고 시청 버튼 정의")])
        resp = eval_recall("광고 시청 버튼 노출 비율", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        raw_ids = [h["object_id"] for h in resp["raw_excerpts"]]
        self.assertTrue(raw_ids)
        self.assertTrue(all(i.startswith("raw.foo-ctx.") for i in raw_ids))
        self.assertLessEqual(len(resp["raw_excerpts"]), 5)
        # raw는 results/candidates에 섞이지 않는다.
        self.assertFalse([h for h in resp["results"] if h["kind"] == "raw_chunk"])
        self.assertFalse([h for h in resp["candidates"] if h["kind"] == "raw_chunk"])

    def test_raw_lane_returns_excerpts_for_vocabulary_absent_from_objects(self):
        # ★설계 고정(2026-06-11)★: raw 레인의 존재 이유는 "객체화 안 된 기획서 서술
        # 회수"다. 객체 표면에 없는 어휘로 물어도 raw 발췌는 그대로 나온다.
        self._write_raw("foo-ctx", "spec",
                        "# 연출 기획\n버블 발사 연출은 무지개색 궤적으로 표현한다.\n")
        self._build([glossary_term("g.x", term="레이스", definition="카약 경주")])
        resp = eval_recall("버블 발사 연출 무지개색 궤적", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        raw_ids = [h["object_id"] for h in resp["raw_excerpts"]]
        self.assertTrue(raw_ids)
        self.assertTrue(all(i.startswith("raw.foo-ctx.") for i in raw_ids))

    def test_no_raw_dir_keeps_empty_channel(self):
        self._build([glossary_term("g.race", term="레이스", definition="카약 경주")])
        resp = eval_recall("레이스", db_path=self.db, embedder=self.embedder,
                           brain_root=self.brain)
        self.assertEqual(resp["raw_excerpts"], [])

    def test_scope_filter_applies_to_raw_lane(self):
        # raw 행도 context_id 행 메타를 가지므로 scope 하드 필터를 그대로 받는다.
        self._write_raw("foo-ctx", "spec", "# 보상\n레이스 보상 서술.\n")
        self._write_raw("bar-ctx", "spec", "# 보상\n레이스 보상 다른 기능 서술.\n")
        self._build([glossary_term("g.race", term="레이스", definition="카약 경주")])
        hits = recall("레이스 보상 서술", scope="context.foo-ctx", db_path=self.db,
                      embedder=self.embedder, brain_root=self.brain)
        raw_ctx = {h["context_id"] for h in hits if h["kind"] == "raw_chunk"}
        self.assertEqual(raw_ctx, {"context.foo-ctx"})


def insight(iid, *, body, scope="범위", status="reviewed",
            source_object_ids=None, code_locator_ids=None,
            insight_type="cross-cutting-risk"):
    iid = _contextual_id("Insight", iid, "context.neutral")
    obj = {
        "id": iid, "kind": "Insight", "status": status, "truth_role": "synthesis",
        "title": f"인사이트: {iid}", "body": body, "scope": scope,
        "source_object_ids": source_object_ids or [
            "mapping.neutral.a",
            "mapping.neutral.b",
        ],
        "insight_type": insight_type, "evidence_refs": [],
    }
    if code_locator_ids is not None:
        obj["code_locator_ids"] = [
            _contextual_id("CodeLocator", cid, "context.neutral")
            for cid in code_locator_ids
        ]
    return _b(obj)


class InsightLaneTest(unittest.TestCase):
    """Insight 별도 레인(spec 2026-06-15 §4.6) — raw와 동형으로 객체 융합·그래프
    재정렬을 흔들지 않고, hits 뒤에 별도로 붙는다. surface 승급·linked는 유지(advisory가
    어느 코드와 관련인지 보여줘야 하므로). 전부 stub embedder."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()

    def tearDown(self):
        self._td.cleanup()

    def test_insight_appended_as_separate_lane_after_objects(self):
        build_store_dir(self.brain, [
            glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰"),
            insight("insight.gate", body="클리어 토큰 노출 게이트가 두 팝업에 이중구현"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)
        hits = recall("클리어 토큰 노출 게이트", db_path=self.db, embedder=self.embedder,
                      brain_root=self.brain)
        kinds = [h["kind"] for h in hits]
        self.assertIn("Insight", kinds)
        # Insight는 객체 뒤 별도 레인 — 첫 Insight 이후에 일반 객체가 나오지 않는다.
        first_ins = kinds.index("Insight")
        self.assertTrue(all(k in ("Insight", "raw_chunk") for k in kinds[first_ins:]))
        ins_hit = next(h for h in hits if h["kind"] == "Insight")
        self.assertEqual(ins_hit["status"], "reviewed")
        self.assertIn("이중구현", ins_hit["surface"])  # 표면 승급(body)
        self.assertEqual(ins_hit["graph_support"], 0)  # 재정렬 입력 아님

    def test_insight_flood_does_not_crowd_object_lane(self):
        # Insight 60개가 있어도 객체 적중(그래프 재정렬 입력)은 그대로 살아남는다(레인 분리).
        objs = [glossary_term("g.race", term="레이스", definition="레이스 보상 지급")]
        objs += [insight(f"insight.{i}", body="레이스 보상 지급 위험 서술") for i in range(60)]
        build_store_dir(self.brain, objs)
        rebuild(self.brain, self.db, embedder=self.embedder)
        hits = recall("레이스 보상 지급", db_path=self.db, embedder=self.embedder,
                      brain_root=self.brain)
        object_ids = [h["object_id"] for h in hits
                      if h["kind"] not in ("Insight", "raw_chunk")]
        self.assertIn("g.neutral.race", object_ids)

    def test_insight_linked_carries_code_locators(self):
        build_store_dir(self.brain, [
            code_locator("code.enter", path="a/Enter.cpp", symbol="Enter::gate"),
            insight("insight.gate", body="클리어 토큰 노출 게이트 이중구현",
                    code_locator_ids=["code.enter"]),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)
        hits = recall("클리어 토큰 노출 게이트 이중구현", db_path=self.db,
                      embedder=self.embedder, brain_root=self.brain)
        ins_hit = next(h for h in hits if h["kind"] == "Insight")
        locs = {c["object_id"] for c in ins_hit["linked"]["code_locators"]}
        self.assertIn("code.neutral.enter", locs)

    def test_object_df_excludes_insight_rows(self):
        # 회수 사실의 객체 df(#73)는 Insight 행을 세지 않는다 — Insight는 자유 텍스트
        # 곁들임 채널이라 객체 코퍼스 분포에 섞이면 안 된다. 같은 토큰의 Insight
        # 40개가 있어도 객체 df는 1로 유지된다.
        objs = [glossary_term("g.race", term="레이스", definition="카약 경주")]
        objs += [insight(f"insight.{i}", body=f"레이스 위험 서술 {i}") for i in range(40)]
        build_store_dir(self.brain, objs)
        rebuild(self.brain, self.db, embedder=self.embedder)
        conn = sqlite3.connect(str(self.db))
        try:
            self.assertEqual(_document_frequency(conn, "레이스"), 1)
        finally:
            conn.close()


def projection(pid, *, context_id, title, reuse_payload, source_object_ids=None,
               status="candidate", fmt="prompt_payload", source_objects=None):
    ctx = parse_id(context_id, "DomainContext").ctx
    pid_parts = pid.split(".")
    requirement_key = pid_parts[-2] if pid_parts[-1] == "reuse" else pid_parts[-1]
    pid = format_id(
        "ContextProjection",
        ctx=ctx,
        requirement_key=requirement_key,
        format=fmt,
    )
    sids = source_object_ids or ["mapping.mina-kayak.race-end-result-achieve"]
    # source_objects(구성 객체 dict들)를 주면 fresh source_content_hash를 lint와
    # 같은 공식으로 계산한다 — Task A6 신선도 가드가 색인에서 빼지 않도록. 안 주면
    # 옛 placeholder("x")라 stale 취급된다(낡음 검사 자체를 보는 테스트용).
    if source_objects is not None:
        from project_brain.hash_utils import source_content_hash as _sch
        content_hash = _sch(source_objects)
    else:
        content_hash = "x"
    return _b({
        "id": pid, "kind": "ContextProjection", "status": status, "truth_role": "index",
        "title": title, "context_id": context_id,
        "format": fmt, "reuse_payload": reuse_payload,
        "output_locator": f"indexes/context_projections/{pid}.txt",
        "source_object_ids": sids,
        "source_content_hash": content_hash, "projection_hash": "y",
        "generated_at": T, "generated_by": "test",
        "stale_policy": "fail_on_manual_edit",
        "evidence_refs": [],
    })


class ProjectionLaneTest(unittest.TestCase):
    """ContextProjection 재사용 레인(spec 2026-06-17 projection_reuse) — raw·Insight와
    동형으로 객체 융합·그래프 재정렬을 흔들지 않고 hits 뒤에 별도로 붙는다. 전부 stub
    embedder."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()

    def tearDown(self):
        self._td.cleanup()

    def test_projection_in_recall_after_objects(self):
        src = domain_mapping("mapping.mina-kayak.race-end-result-achieve",
                             meaning="미나 결과 팝업 순위 표시", context_id="context.mina-kayak")
        build_store_dir(self.brain, [
            src,
            projection("projection.mina-kayak.result-popup-rank.reuse",
                       context_id="context.mina-kayak",
                       title="미나 결과 팝업 순위 표시 착수 브리핑",
                       reuse_payload="데이터 출처: RaceInfo recordMap. 확장 지점: PopupMinaKayakResult.",
                       source_object_ids=["mapping.mina-kayak.race-end-result-achieve"],
                       source_objects=[src]),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)
        hits = recall("미나 결과 팝업 순위 표시", db_path=self.db, embedder=self.embedder,
                      brain_root=self.brain)
        kinds = [h["kind"] for h in hits]
        self.assertIn("ContextProjection", kinds)
        # projection은 객체·raw·Insight 적중 뒤 별도 레인 — 첫 projection 이후엔
        # 일반 객체가 나오지 않는다.
        proj_idx = kinds.index("ContextProjection")
        obj_idx = next(i for i, k in enumerate(kinds)
                       if k not in ("ContextProjection", "raw_chunk", "Insight"))
        self.assertLess(obj_idx, proj_idx)
        proj_hit = next(h for h in hits if h["kind"] == "ContextProjection")
        self.assertEqual(proj_hit["status"], "candidate")
        self.assertIn("PopupMinaKayakResult", proj_hit["surface"])
        self.assertEqual(proj_hit["linked"]["code_locators"], [])
        self.assertEqual(proj_hit["graph_support"], 0)

    def test_projection_excluded_from_object_df(self):
        # projection 본문에만 있는 희귀 토큰의 객체 df가 0(존재 안 함)으로 잡힌다 —
        # projection 행 미집계. raw/Insight df 제외와 동형(projection은 정본 객체를
        # 재서술한 본문이라 객체 df에 섞이면 정본 회수를 잠식한다).
        # "reuseprobexyz"는 토크나이저가 쪼개지 않는 단일 보존 토큰이고 projection
        # reuse_payload에만 있다 — 제외 안 되면 df=1로 새므로 제외를 직접 검증한다.
        src = domain_mapping("mapping.mina-kayak.race-end-result-achieve",
                             meaning="미나 결과 팝업 순위 표시", context_id="context.mina-kayak")
        build_store_dir(self.brain, [
            src,
            projection("projection.mina-kayak.result-popup-rank.reuse",
                       context_id="context.mina-kayak",
                       title="미나 결과 팝업 순위 표시 착수 브리핑",
                       reuse_payload="데이터 출처: reuseprobexyz recordMap.",
                       source_object_ids=["mapping.mina-kayak.race-end-result-achieve"],
                       source_objects=[src]),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)
        conn = sqlite3.connect(str(self.db))
        try:
            df = _document_frequency(conn, "reuseprobexyz")
        finally:
            conn.close()
        self.assertEqual(df, 0)


class EvalRecallProjectionReuseTest(unittest.TestCase):
    """eval_recall projection_reuse 채널(spec 2026-06-17 Task A5) — ContextProjection은
    status 무관 results/candidates에 안 섞이고 projection_reuse로만 나온다. 전부 stub
    embedder."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()

    def tearDown(self):
        self._td.cleanup()

    def _build(self, objs):
        build_store_dir(self.brain, objs)
        rebuild(self.brain, self.db, embedder=self.embedder)

    def test_eval_recall_projection_in_own_channel_not_results(self):
        # candidate projection도 results/candidates가 아니라 projection_reuse로만 나온다.
        src = domain_mapping("mapping.mina-kayak.race-end-result-achieve",
                             meaning="미나 결과 팝업 순위 표시", context_id="context.mina-kayak")
        self._build([
            src,
            projection("projection.mina-kayak.result-popup-rank.reuse",
                       context_id="context.mina-kayak",
                       title="미나 결과 팝업 순위 표시 착수 브리핑",
                       reuse_payload="데이터 출처: RaceInfo recordMap. 확장 지점: PopupMinaKayakResult.",
                       source_object_ids=["mapping.mina-kayak.race-end-result-achieve"],
                       source_objects=[src]),
        ])
        resp = eval_recall("미나 결과 팝업 순위 표시", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        self.assertIn("projection_reuse", resp)
        self.assertTrue(all(h["kind"] != "ContextProjection" for h in resp["results"]))
        self.assertTrue(all(h["kind"] != "ContextProjection" for h in resp["candidates"]))
        self.assertTrue(any(h["kind"] == "ContextProjection"
                            for h in resp["projection_reuse"]))

    def test_eval_recall_reviewed_projection_stays_in_reuse_channel(self):
        # 핵심 가드(codex 블로커): promote된(reviewed) projection도 results가 아니라
        # projection_reuse에 남는다 — 채널 이동 없음.
        src = domain_mapping("mapping.mina-kayak.race-end-result-achieve",
                             meaning="미나 결과 팝업 순위 표시", context_id="context.mina-kayak")
        self._build([
            src,
            projection("projection.mina-kayak.result-popup-rank.reuse",
                       context_id="context.mina-kayak",
                       title="미나 결과 팝업 순위 표시 착수 브리핑",
                       reuse_payload="데이터 출처: RaceInfo recordMap. 확장 지점: PopupMinaKayakResult.",
                       source_object_ids=["mapping.mina-kayak.race-end-result-achieve"],
                       source_objects=[src],
                       status="reviewed"),
        ])
        resp = eval_recall("미나 결과 팝업 순위 표시", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        self.assertTrue(all(h["kind"] != "ContextProjection" for h in resp["results"]))
        self.assertTrue(any(h["kind"] == "ContextProjection"
                            and h.get("status") == "reviewed"
                            for h in resp["projection_reuse"]))


class EvalRecallAdvisoriesTest(unittest.TestCase):
    """eval_recall advisories 채널(spec 2026-06-15 §4.6 C1) — reviewed Insight는
    results에 안 섞이고 advisories로 가른다. candidate Insight는 1차 미노출."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()

    def tearDown(self):
        self._td.cleanup()

    def test_reviewed_insight_goes_to_advisories_not_results(self):
        # reviewed Insight는 advisories로, results/candidates엔 안 섞인다.
        build_store_dir(self.brain, [
            glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰 노출"),
            insight("insight.gate", body="클리어 토큰 노출 게이트가 두 팝업에 이중구현"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)
        resp = eval_recall("클리어 토큰 노출 게이트 이중구현", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        self.assertIn("advisories", resp)
        self.assertIn(
            "insight.neutral.gate",
            {h["object_id"] for h in resp["advisories"]},
        )
        self.assertFalse([h for h in resp["results"] if h["kind"] == "Insight"])
        self.assertFalse([h for h in resp["candidates"] if h["kind"] == "Insight"])

    def test_candidate_insight_not_exposed_first_cut(self):
        # candidate Insight는 validate가 적재를 막으므로(Task 1) save_object를 우회해
        # 직접 파일로 써 store에 넣고, 검색층이 방어적으로 안 띄움을 확인(이중 안전망).
        import json
        build_store_dir(self.brain, [
            glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰 노출"),
        ])
        cand = insight("insight.cand", body="클리어 토큰 노출 위험 후보", status="candidate")
        ins_dir = self.brain / "objects" / "insights"
        ins_dir.mkdir(parents=True, exist_ok=True)
        (ins_dir / "insight.cand.json").write_text(
            json.dumps(cand, ensure_ascii=False), encoding="utf-8")
        rebuild(self.brain, self.db, embedder=self.embedder)
        resp = eval_recall("클리어 토큰 노출 위험", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        self.assertEqual(resp["advisories"], [])
        self.assertFalse([h for h in resp["candidates"] if h["kind"] == "Insight"])

    def test_advisories_capped_at_five(self):
        # reviewed Insight 7개 → advisories top-5.
        objs = [glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰")]
        objs += [insight(f"insight.{i}", body="클리어 토큰 노출 게이트 이중구현 위험")
                 for i in range(7)]
        build_store_dir(self.brain, objs)
        rebuild(self.brain, self.db, embedder=self.embedder)
        resp = eval_recall("클리어 토큰 노출 게이트 이중구현", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        self.assertTrue(resp["advisories"])
        self.assertLessEqual(len(resp["advisories"]), 5)

    def test_candidate_object_does_not_pull_insight_into_results(self):
        # advisories는 곁들임 채널 — reviewed 객체 답(results)이 0이어도 Insight가
        # results/candidates로 새지 않는다(채널은 status·kind로만 갈린다).
        build_store_dir(self.brain, [
            glossary_term("g.cand", term="클리어 토큰", definition="스테이지 클리어 토큰",
                          status="candidate"),
            insight("insight.gate", body="클리어 토큰 노출 게이트 이중구현"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)
        resp = eval_recall("클리어 토큰 노출 게이트 이중구현", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        self.assertIn("insight.neutral.gate",
                      {h["object_id"] for h in resp["advisories"]})
        self.assertEqual(resp["results"], [])
        self.assertFalse([h for h in resp["candidates"] if h["kind"] == "Insight"])


class IndexFreshnessGuardTest(unittest.TestCase):
    def _seed_and_build(self, brain_root, db):
        obj = glossary_term("g.t.a", term="용어", status="candidate",
                            context_id="context.t")
        BrainStore.save_object(brain_root, obj)
        rebuild(brain_root=brain_root, db_path=db, embedder=StubEmbedder())

    def test_recall_raises_on_stale_index(self):
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            db = brain_root / "idx.db"
            self._seed_and_build(brain_root, db)

            # 색인 빌드 후 객체 변경(status 플립) → 색인이 stale
            obj2 = glossary_term("g.t.a", term="용어", status="reviewed",
                                 context_id="context.t")
            BrainStore.save_object(brain_root, obj2)

            with self.assertRaises(RuntimeError) as ctx:
                recall("용어", db_path=db, brain_root=brain_root,
                       embedder=StubEmbedder())
            self.assertIn("rebuild", str(ctx.exception))  # 해결책이 담긴 메시지

    def test_recall_passes_on_fresh_index(self):
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            db = brain_root / "idx.db"
            self._seed_and_build(brain_root, db)
            results = recall("용어", db_path=db, brain_root=brain_root,
                             embedder=StubEmbedder())
            self.assertIsInstance(results, list)  # 신선하면 기존 동작 그대로

    def _set_meta_tokenizer(self, db, value):
        conn = sqlite3.connect(str(db))
        try:
            conn.execute("UPDATE meta SET tokenizer = ?", (value,))
            conn.commit()
        finally:
            conn.close()

    def test_recall_raises_on_tokenizer_mismatch(self):
        # #75: 코퍼스는 그대로여도 색인 토크나이저가 다르면 검색 진입에서 거부한다 —
        # 지문 stale과 같은 오류·같은 안내(rebuild)로 처리한다.
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            db = brain_root / "idx.db"
            self._seed_and_build(brain_root, db)
            self._set_meta_tokenizer(db, "다른토크나이저@1")

            with self.assertRaises(RuntimeError) as ctx:
                recall("용어", db_path=db, brain_root=brain_root,
                       embedder=StubEmbedder())
            self.assertIn("rebuild", str(ctx.exception))

    def test_recall_raises_on_meta_without_rules_version(self):
        # #75가 규칙 버전 없는 색인을 버전 1로 읽고, #79가 현재 규칙을 2로 올렸다 —
        # 백엔드 이름이 같아도 규칙이 달라 rebuild 안내로 거부돼야 한다.
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            db = brain_root / "idx.db"
            self._seed_and_build(brain_root, db)
            self._set_meta_tokenizer(db, active_backend())

            with self.assertRaises(RuntimeError) as ctx:
                recall("용어", db_path=db, brain_root=brain_root,
                       embedder=StubEmbedder())
            self.assertIn("rebuild", str(ctx.exception))


class ScopedBm25WiringTest(unittest.TestCase):
    """recall — scope가 정해지면 객체 레인 BM25가 scoped 재계산으로 바뀐다(§3.2).

    s1 회귀(2026-06-12)의 recall 차원 가드: 벡터 채널은 문서별 독립이라 원래
    면역 — BM25 채널이 scoped로 바뀌면 객체 레인 전체가 scope 밖 적재에 면역.
    """

    def _base_objs(self):
        return [
            scoped_context("context.a", display_name="카약 레이스",
                           title="카약 레이스 도메인", context_key="kayak-race"),
            glossary_term("g.d1", term="알림 팝업", context_id="context.a"),
            glossary_term("g.d2", term="클리어 팝업", context_id="context.a"),
            glossary_term("g.d3", term="알림 안내", context_id="context.a"),
        ]

    def _setup_corpus(self, objs):
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name) / "brain"
        db = Path(td.name) / "index.db"
        embedder = StubEmbedder()
        build_store_dir(brain, objs)
        rebuild(brain, db, embedder=embedder)
        return brain, db, embedder

    def test_recall_uses_scoped_bm25_when_scope_resolved(self):
        # 배선 가드: 질의가 컨텍스트를 단일 특정하면 search_bm25_scoped가 불린다.
        brain, db, embedder = self._setup_corpus(self._base_objs())
        with mock.patch("project_brain.search.search_bm25_scoped",
                        wraps=search_bm25_scoped) as spy:
            recall("카약 레이스 알림 클리어", db_path=db, embedder=embedder,
                   brain_root=brain)
        spy.assert_called_once()

    def test_recall_no_scope_does_not_use_scoped_bm25(self):
        # scope 미특정(컨텍스트 언급 없음) 질의는 기존 전역 경로 그대로.
        brain, db, embedder = self._setup_corpus(self._base_objs())
        with mock.patch("project_brain.search.search_bm25_scoped",
                        wraps=search_bm25_scoped) as spy:
            recall("알림 클리어", db_path=db, embedder=embedder, brain_root=brain)
        spy.assert_not_called()

    def test_recall_object_lane_immune_to_out_of_scope_ingest(self):
        # 행동 불변식: context.b 어휘 중첩 적재 전후, scope 추론 질의의 recall
        # 결과 순서(객체 레인)가 동일해야 한다 — s1 회귀의 합성 재현.
        td = TemporaryDirectory()
        self.addCleanup(td.cleanup)
        brain = Path(td.name) / "brain"
        db = Path(td.name) / "index.db"
        embedder = StubEmbedder()
        build_store_dir(brain, self._base_objs())
        rebuild(brain, db, embedder=embedder)
        query = "카약 레이스 알림 클리어"
        before = [h["object_id"] for h in
                  recall(query, db_path=db, embedder=embedder, brain_root=brain)]
        build_store_dir(brain, [
            glossary_term(f"g.n{i}", term="클리어 보상", context_id="context.b")
            for i in range(4)
        ])
        rebuild(brain, db, embedder=embedder)
        after = [h["object_id"] for h in
                 recall(query, db_path=db, embedder=embedder, brain_root=brain)]
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
