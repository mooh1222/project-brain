"""RRF 융합 + recall() + 그래프 1-hop + eval_recall 어댑터 (스펙 §3.4·§3.5·§3 결과 계약).

spec: docs/superpowers/specs/2026-06-10-project-brain-search-layer-design.md

BM25 채널(search_bm25)과 벡터 채널(search_vector)을 각각 top 50 받아 RRF로 융합한다
(§3.4: score = Σ 1/(60+rank), k=60). 두 채널은 이미 "좋은 순"으로 정렬돼 있으므로
(BM25 점수는 작을수록·벡터 거리도 작을수록 좋음) rank만 쓰면 된다. 융합 결과 top 30을
§3 결과 계약 dict로 만든다.

슬라이스 4(§3.5 그래프 1-hop): 융합 top-30 적중에서 참조 필드를 1-hop 따라 linked를
채우고(code_locators는 {object_id, path, symbol, quote_access} 객체형), top-30 적중집합 안의 상호
연결 도달 횟수를 graph_reached(bool)·graph_hits(횟수)로 분리 기록한다. evidence_refs는
표시 전용(linked.evidence_ref_ids)이라 랭킹·그래프 도달 계산에서 제외한다.

캘리브레이션(§3.5 후반·§8 그래프 재정렬): 융합 top-30을 그래프 ★상호지지★로 결정론
재정렬한다 — graph_support(자기 엣지가 적중집합 안의 다른 적중을 가리킨 아웃바운드 도달
수)를 캡(_GRAPH_SUPPORT_CAP)으로 자른 뒤 사전식(lexicographic) 1순위 키로, 동점은 원래
RRF 순위·object_id로 깬다. ★RRF 점수에 임의 상수를 더하지 않는다(§3.5)★. 캡이 허브
객체(엣지 100+개)의 도달을 초점 매핑과 같은 상한으로 눌러 허브가 그래프 신호로 더
굳어지는 것을 막는다(과업 3번). 실측: s1 목표 매핑 10등→top5, s2 9등→top5(§8).

채널 배치(#77, ADR 0008): `eval_recall(query)`는 recall 융합 결과를 ★검수 상태와
객체 종류만으로★ 다섯 채널로 가른다 — reviewed 객체는 results, candidate 객체는
candidates, raw 청크는 raw_excerpts, reviewed Insight는 advisories, ContextProjection은
projection_reuse. 회수한 검수 객체를 엔진이 숨기는 답변 게이트(어휘 명부 매칭 OR
앵커 df 상한), 채널별 점수 바닥, needs_clarification 플래그는 폐지했다 — 엔진은
LLM이 아니라 "이 객체가 이 질문의 답인가"를 판단할 수 없고, 어휘 일치는 답 존재의
근거가 아니다. 그 판정은 아래 회수 사실을 보고 에이전트가 한다.

회수 사실(#73, ADR 0008 "엔진은 회수만 하고 답변 판정은 에이전트가 한다"): `eval_recall`은
채널과 함께 결정론 사실을 신고한다 — 질의 토큰 분해와 토큰별 객체 df·raw df
(compute_query_token_facts), 적중별로 그 적중의 색인 본문에 실제로 있는 질의 토큰
(matched_query_tokens), 적용된 scope(context_id + 적용 출처). 이 사실들은 판정이 아니라
에이전트의 답변 판정 재료다 — 어떤 값도 boolean 판정이 아니고, 명부 매칭 사실은 싣지
않는다(등재 어휘가 걸리면 GlossaryTerm 객체 자체가 results에 오른다).
"""

import re
import sqlite3
from pathlib import Path

from project_brain.config import resolve_brain_root, resolve_db_path
from project_brain.quote_access import AccessState, evaluate_quote_access
from project_brain.raw_chunks import RAW_KIND, RAW_STATUS
from project_brain.search_index import (
    search_bm25,
    search_bm25_scoped,
    search_vector,
)
from project_brain.store import BrainStore
from project_brain.surface import extract_surface
from project_brain.tokenize_ko import tokenize


class UnknownScopeError(ValueError):
    """명시한 scope를 코퍼스가 모른다(#74).

    scope 필터는 적중의 context_id 일치이므로, 없는 id를 주면 전 채널이 조용히 0건이
    된다 — 오타와 "정말 없다"가 구분되지 않는다. 색인 누락·stale과 같은 철학으로
    시끄럽게 거부하고 실제 id를 안내한다.
    """


# 기본 brain root·색인 DB는 프로젝트 config(.project-brain.json)에서 해석한다(§4) —
# recall이 그래프 1-hop을 따라가려면 store가 필요하다.

# 그래프 1-hop 엣지 필드(§3.5 — 전부 optional, 없으면 건너뜀). 실코퍼스 대조 완료
# (2026-06-10): code_locator_ids는 CodeLocator를 가리켜 linked.code_locators(객체형)로,
# 나머지 4종은 용어/결정/매핑을 가리켜 linked.related_object_ids로 동반된다.
# ★evidence_refs는 여기 없다 — 표시 전용이라 linked.evidence_ref_ids에만, 랭킹·그래프
# 도달 계산 입력에서 제외(전 객체 보편 필드라 랭킹/그래프 오염, §3.5).
_CODE_EDGE_FIELD = "code_locator_ids"
_RELATED_EDGE_FIELDS = (
    "glossary_term_ids",
    "decision_record_ids",
    "affected_glossary_term_ids",
    "affected_mapping_ids",
)
# graph_reached/graph_hits 계산이 따라가는 전체 엣지(양방향 도달, evidence_refs 제외).
_GRAPH_EDGE_FIELDS = (_CODE_EDGE_FIELD,) + _RELATED_EDGE_FIELDS

# RRF 표준 상수(§3.4 — hwi_PKM·HwiCortex·hindsight 동일).
RRF_K = 60

# 각 채널에서 받는 후보 수(§3.2·§3.3 top 50) / 융합 결과 절단(§3.4 top 30).
CHANNEL_TOP_N = 50
FUSED_TOP_N = 30

# eval_recall이 채널별로 노출하는 기본 상한(§8 평가 — top-5 적중 측정 단위).
# ★기본값을 바꾸지 않는다★: 평가 하네스(eval_harness.evaluate)는 recall_fn(query)를
# 인자 하나로만 부르므로 이 기본값이 곧 하네스의 측정 단위다.
EVAL_CHANNEL_TOP_K = 5
# CLI `search`가 채널별로 표시하는 기본 상한(#74) — 사람·에이전트가 읽는 회수 출력은
# 평가 측정 단위보다 넓게 본다. CLI만 이 값을 channel_top_k로 넘기고, 하네스는 위 기본값
# 그대로다. 회수 자체의 절단(객체 레인 FUSED_TOP_N, raw·Insight·projection 레인
# RAW_FUSED_TOP_N)을 넘겨 보여줄 수는 없다 — 표시 상한은 자르기만 한다.
SEARCH_CHANNEL_TOP_K = 10

# ── raw 별도 레인(§2.2 raw 본문 색인, 2026-06-11) ──────────────────────────
# raw 청크는 같은 색인 테이블에 있지만 recall에서는 ★객체 레인과 분리★한다 —
# 한 레인에 섞으면 기획서 청크가 융합 top-30의 객체 자리를 잠식해 그래프 상호지지
# 재정렬(§3.5 — s1·s2 핀포인트의 열쇠)이 약해지는 회귀가 실재한다. 채널 검색을
# 이 배수로 과대 적재한 뒤 kind로 갈라 레인별로 따로 자르고 따로 융합한다.
_RAW_LANE_FETCH_FACTOR = 3
# raw 레인 융합 절단 — eval 채널이 top-5만 노출하므로 여유분 포함 10이면 충분.
RAW_FUSED_TOP_N = 10

# ── Insight 별도 레인(spec 2026-06-15 §4.6) ──────────────────────────────────
# Insight는 store 객체(RAW_KIND 아님)라 객체 레인에 남는다 — 자유 텍스트 다토큰이라
# 융합 top-30의 객체 자리를 잠식해 그래프 재정렬을 약화시킨다(raw 청크 회귀와 동형).
# raw처럼 별도 레인으로 빼되, store 객체라 surface 승급·linked는 유지한다. scope
# 필터는 미적용 — "가로지르는" 객체라 단일 context_id가 없다.
INSIGHT_KIND = "Insight"
# ContextProjection 별도 레인(2026-06-17 projection reuse layer).
PROJECTION_KIND = "ContextProjection"
# 객체 레인에서 제외할 kind(별도 레인으로 빠지는 것들).
_OBJECT_LANE_EXCLUDED = (RAW_KIND, INSIGHT_KIND, PROJECTION_KIND)

# RRF 융합 점수 반올림 자릿수(§3.4 결정론 비교 — 부동소수점 동점 흔들림 완화).
_SCORE_ROUND = 6

# 그래프 상호지지 재정렬 캡(§3.5 후반·§8 캘리브레이션). 적중 객체가 ★자기 엣지로★
# top-30 적중집합 안의 다른 적중을 가리킨 수(아웃바운드 도달, graph_support)를 이 값으로
# 자른 뒤 1순위 정렬 키로 쓴다. ★캡이 핵심★: context.mina-kayak 같은 허브는 엣지가
# 100개 넘어 아웃바운드 도달이 매우 높지만, 캡이 허브의 도달을 초점 매핑(엣지 3~7개)과
# 같은 상한으로 눌러 허브가 그래프 신호로 더 굳어지지 않게 한다(과업 3번 — 허브 가드).
# 양방향 graph_hits를 캡해도 안 되는 이유: 허브가 가리키는 잎 용어들도 graph_hits가
# 높아져(피참조 +1) 매핑과 안 갈라진다 — 실측 확인. 아웃바운드만 세야 "초점 매핑이
# 자기 참조 코드/용어를 적중집합에서 되찾았다"는 신호가 잎 용어(아웃바운드 0)와 분리된다.
# 계수 2는 캘리브레이션 실측값(s1 10등→top5, s2 9등→top5; 1~3 폭에서 안정 — §8).
_GRAPH_SUPPORT_CAP = 2


def rrf_fuse(rankings, k: int = RRF_K):
    """여러 순위 리스트를 RRF로 융합한다(§3.4 score = Σ 1/(k+rank)).

    rankings: object_id 리스트의 리스트. 각 리스트는 이미 "좋은 순"으로 정렬된 한 채널의
              결과. ★rank는 1부터★(표준 RRF — 1등이 1/(k+1)). 0-기반으로 세면 유효
              k가 59가 되어 "k=60 업계 표준(hwi_PKM·HwiCortex 동일)" 주장과 어긋난다
              (2026-06-10 슬라이스 3 리뷰 반영).
    반환: (object_id, score) 튜플 리스트, score 내림차순 + 동점은 object_id 오름차순
          정렬(결정론 tie-break, §3.4). score는 6자리 반올림.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, object_id in enumerate(ranking, start=1):
            scores[object_id] = scores.get(object_id, 0.0) + 1.0 / (k + rank)
    fused = [(oid, round(s, _SCORE_ROUND)) for oid, s in scores.items()]
    # 점수 내림차순, 동점은 object_id 오름차순(§3.4 결정론).
    fused.sort(key=lambda pair: (-pair[1], pair[0]))
    return fused


def _build_linked(object_id: str, store: BrainStore) -> dict:
    """적중 객체의 참조 필드를 1-hop 따라 linked를 채운다(§3.5).

    - code_locators: code_locator_ids가 가리키는 CodeLocator를
      ★{object_id, path, symbol, quote_access} 객체로★ 동반한다. title은 표시용이라
      검색 결과에서 빼고, 현재 principal/ACL evaluator가 없는 제품 경로에서는
      quote_access가 indeterminate이므로 verified_quote도 내보내지 않는다.
    - related_object_ids: 용어/결정/매핑 등 나머지 4종 엣지가 가리키는 연결 객체를
      {object_id, title}로 동반(이웃이 무엇인지 id만으론 가늠 어려워 제목 동반).
    - evidence_ref_ids: 해당 객체의 evidence_refs(★표시 전용 — 랭킹·그래프 입력 금지★).
    ★dangling id(store에 없는 참조)는 건너뛴다★.
    """
    obj = store.get(object_id) if store.has(object_id) else {}

    code_locators = []
    for cid in obj.get(_CODE_EDGE_FIELD) or []:
        if not store.has(cid):
            continue
        c = store.get(cid)
        quote_access = evaluate_quote_access(
            cid,
            store,
            principal=None,
            acl_evaluator=None,
        ).final
        linked_locator = {
            "object_id": cid,
            "path": c.get("path"),
            "symbol": c.get("symbol"),
            "quote_access": quote_access.value,
        }
        quote = c.get("verified_quote")
        if (
            quote_access is AccessState.ALLOW
            and isinstance(quote, str)
            and quote
        ):
            linked_locator["quote"] = quote
        code_locators.append(linked_locator)

    related: list[dict] = []
    seen_related: set[str] = set()
    for field in _RELATED_EDGE_FIELDS:
        for rid in obj.get(field) or []:
            if store.has(rid) and rid not in seen_related:
                seen_related.add(rid)
                related.append({"object_id": rid, "title": store.get(rid).get("title")})

    # evidence_refs는 객체에 박힌 EvidenceRef id 리스트 — store 존재 여부와 무관하게
    # 표시 전용으로 그대로 동반(랭킹·그래프 도달 계산에는 절대 안 들어간다).
    evidence_ref_ids = [e for e in (obj.get("evidence_refs") or []) if isinstance(e, str)]

    return {
        "code_locators": code_locators,
        "evidence_ref_ids": evidence_ref_ids,
        "related_object_ids": related,
    }


def _graph_signals_by_id(hit_ids, store: BrainStore):
    """top-30 적중집합 안의 그래프 신호 2종을 적중별로 센다(§3.5).

    - graph_hits(양방향 도달, 슬라이스 4 진단 신호): A의 엣지가 집합 안의 B를 가리키면
      A·B 양쪽 +1. ★재정렬에 안 쓴다★ — 허브가 가리키는 잎 용어까지 부풀어(피참조 +1)
      매핑과 안 갈라짐(실측). graph_reached/graph_hits로 그대로 표시만 한다.
    - graph_support(아웃바운드 도달, ★재정렬 1순위 신호★, §3.5 후반·§8): A가 ★자기
      엣지로★ 집합 안의 다른 적중을 가리킨 수만 센다(A만 +1, 피참조는 안 센다).
      "초점 매핑이 자기 참조 코드/용어를 적중집합에서 되찾았다"는 신호가 아웃바운드 0인
      잎 용어와 분리된다. 캡은 호출처(_rerank_by_support)에서 적용.

    evidence_refs는 두 신호 모두에서 제외(§3.5). dangling·집합 밖 참조는 안 센다.
    반환: (graph_hits 맵, graph_support 맵).
    """
    hit_set = set(hit_ids)
    hits: dict[str, int] = {oid: 0 for oid in hit_ids}
    support: dict[str, int] = {oid: 0 for oid in hit_ids}
    for src in hit_ids:
        if not store.has(src):
            continue
        obj = store.get(src)
        for field in _GRAPH_EDGE_FIELDS:
            for dst in obj.get(field) or []:
                # 적중집합 안의 다른 적중을 가리키는 엣지만 도달로 센다.
                if dst in hit_set and dst != src:
                    hits[src] += 1
                    hits[dst] += 1   # 양방향(graph_hits 전용)
                    support[src] += 1  # 아웃바운드만(graph_support 전용)
    return hits, support


def _rerank_by_support(ranked_ids, support_by_id, cap: int = _GRAPH_SUPPORT_CAP):
    """RRF 순위 + 그래프 상호지지로 결정론 재정렬한다(§3.5 후반·§8).

    ranked_ids: RRF 융합으로 이미 좋은 순(0-기반 순위 = 리스트 위치)인 object_id 리스트.
    support_by_id: object_id → 아웃바운드 도달 수(_graph_signals_by_id의 support).

    정렬 키 = (-min(support, cap), 원래 RRF 순위, object_id).
    ★RRF 점수에 임의 상수를 더하지 않는다(§3.5)★ — 분리 신호를 사전식(lexicographic)
    1순위 키로 쓰고 동점은 원래 RRF 순위, 그 동점은 object_id로 깬다(§5 결정론).
    캡이 허브(엣지 100+개)의 도달을 초점 매핑과 같은 상한으로 눌러, 허브가 그래프 신호로
    더 위로 올라가지 못하게 한다(과업 3번 허브 가드).
    """
    indexed = list(enumerate(ranked_ids))  # (원래 순위, object_id)
    indexed.sort(key=lambda pair: (-min(support_by_id.get(pair[1], 0), cap),
                                   pair[0], pair[1]))
    return [oid for _, oid in indexed]


# scope 추론에서 표면 토큰으로 인정하는 최소 길이 — 한 글자 토큰(조사 '의' 등)은
# 변별력이 없어 제외한다.
_SCOPE_SURFACE_MIN_TOKEN_LEN = 2


def _context_surface_token_sets(ctx_obj: dict) -> list[set[str]]:
    """DomainContext의 표면 후보를 토큰 집합 목록으로 만든다(infer_scope 입력).

    표면 = display_name / title(공통 접미 '도메인' 이후 제거) / context_key(하이픈 분리).
    각 표면을 tokenize한 뒤 2자 미만 토큰을 버린다 — 남는 토큰이 없으면 그 표면은 제외.
    """
    surfaces = []
    if ctx_obj.get("display_name"):
        surfaces.append(ctx_obj["display_name"])
    title = re.sub(r"\s*도메인.*$", "", ctx_obj.get("title") or "").strip()
    if title:
        surfaces.append(title)
    if ctx_obj.get("context_key"):
        surfaces.append(ctx_obj["context_key"].replace("-", " "))
    token_sets = []
    for s in surfaces:
        toks = {t for t in tokenize(s) if len(t) >= _SCOPE_SURFACE_MIN_TOKEN_LEN}
        if toks:
            token_sets.append(toks)
    return token_sets


def infer_scope(query: str, store: BrainStore):
    """질의 표면에서 DomainContext를 정확히 1개 특정할 수 있으면 그 id를 돌려준다.

    P2 3번 scope 자동 라우팅(2026-06-10): 다기능 코퍼스에서 질의가 기능명을 명시하면
    그 컨텍스트로 하드 필터를 건다. 매칭 기준은 컨텍스트 표면(_context_surface_token_sets)의
    내용 토큰이 **전부** 질의 토큰에 들어 있는가 — 일부 토큰 겹침("클리어"만)으로는
    특정하지 않는다(공유 어휘 오탐 방지, s1 회귀의 골자).

    ★구체 표면 우선(2026-06-12, 시스템 도메인 적재 선행)★: 시스템 컨텍스트 표면("함정")이
    기능 컨텍스트 표면("가시 함정")의 진부분집합이 되면, 핀포인트 질의("가시
    함정 상태")가 둘 다 매칭해 scope를 잃는다(s1 회귀 재노출). 이를 막기 위해 매칭된
    컨텍스트 중 그 매칭 표면이 **다른 매칭의 진부분집합인 것**을 제거하고(maximal만 남김) 센다
    — 더 구체적인 기능 컨텍스트가 일반 시스템 컨텍스트를 이긴다. 일반 질의("함정 점수")는
    시스템 표면만 매칭하므로 시스템으로 간다. 한 컨텍스트의 여러 표면 중에서는 질의에 전부
    포함된 최대 집합을 그 컨텍스트의 매칭 표면으로 본다.

    0개 매칭(기능 언급 없음) 또는 maximal 2개 이상(여러 기능 언급·동률)이면 None — 하드
    필터는 단일 특정일 때만 걸고, 나머지는 전체 검색의 연관도에 맡긴다(보수).
    """
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return None
    matched = []  # (context_id, 매칭 표면 토큰 집합)
    for obj in store.all():
        if obj.get("kind") != "DomainContext":
            continue
        best = None
        for token_set in _context_surface_token_sets(obj):
            if token_set <= query_tokens and (best is None or len(token_set) > len(best)):
                best = token_set
        if best is not None:
            matched.append((obj["id"], best))
    if not matched:
        return None
    # 구체 표면 우선: 매칭 표면이 다른 매칭 표면의 진부분집합이면 제거(maximal만 남김).
    maximal = [
        cid for i, (cid, ts) in enumerate(matched)
        if not any(ts < other for j, (_, other) in enumerate(matched) if i != j)
    ]
    if len(maximal) == 1:
        return maximal[0]
    return None


def _guard_index_freshness(db_path, store, brain_root) -> None:
    """§7 신선도 가드 — stale 색인을 명시 거부하고 rebuild 안내."""
    from project_brain.search_index import (
        StaleIndexError,
        compute_corpus_fingerprint,
        read_meta_fingerprint,
    )

    indexed = read_meta_fingerprint(db_path)
    if indexed is None:
        return  # 지문 없는 구버전 색인은 schema_version 가드가 이미 거부한다
    current = compute_corpus_fingerprint(store, brain_root)
    if indexed != current:
        raise StaleIndexError(
            "색인이 코퍼스보다 오래됨(stale) — 객체 변경이 색인에 반영되지 않았다. "
            "`project-brain index rebuild`로 재생성 후 다시 검색하라."
        )


# scope 오류 메시지에 나열하는 context id 최대 개수(그 이상은 총 개수만).
_SCOPE_SUGGESTION_LIMIT = 10


def _known_scopes(db_path, store) -> set[str]:
    """코퍼스가 아는 context 집합 = 색인 행의 context_id ∪ 적재된 DomainContext id.

    앞쪽이 scope 하드 필터가 실제로 대조하는 값이다(객체·raw·projection 행의
    documents.context_id — Insight 레인은 "가로지르는" 객체라 scope 필터를 안 받는다)
    — raw 원문만 있고 객체가 아직 없는 컨텍스트도 포함된다. 뒤쪽은 적재만 되고 아직
    소속 행이 없는 빈 컨텍스트를 오타로 몰지 않기 위한 것이다(그 경우의 정직한 답은
    오류가 아니라 0건).

    ★documents를 읽기 전에 스키마 버전을 먼저 가드한다★(§4 규약) — 구버전 DDL은
    컬럼이 없어 SELECT가 원시 OperationalError로 터진다(2026-06-11 실사고와 같은
    모양). 다른 색인 쿼리(search_bm25·search_vector)와 같은 순서다.

    토크나이저 가드(§6, _guard_tokenizer)는 여기서 부르지 않는다 — 이 SELECT는
    토큰화를 쓰지 않는 열 대조라 불일치가 결과를 왜곡하지 않고, 실제로 토큰을 쓰는
    BM25 레인이 바로 뒤에서 거부한다. 오타 난 id를 준 호출자에게는 방금 입력한 값에
    대한 오류를 먼저 돌려주는 편이 낫다.
    """
    from project_brain.search_index import _guard_schema_version, _read_meta

    conn = sqlite3.connect(str(db_path))
    try:
        _guard_schema_version(_read_meta(conn))
        rows = conn.execute(
            "SELECT DISTINCT context_id FROM documents WHERE context_id IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    known = {r[0] for r in rows if r[0]}
    known.update(ctx["id"] for ctx in store.by_kind("DomainContext"))
    return known


def _guard_scope_exists(scope, db_path, store) -> None:
    """명시 scope가 코퍼스가 아는 context인지 확인한다 — 아니면 UnknownScopeError."""
    known = _known_scopes(db_path, store)
    if scope in known:
        return
    if known:
        ordered = sorted(known)
        shown = ", ".join(ordered[:_SCOPE_SUGGESTION_LIMIT])
        if len(ordered) > _SCOPE_SUGGESTION_LIMIT:
            # ★표본임을 문구로 드러낸다★ — 사전순 앞 10개가 찾던 것을 포함한다는
            # 보장이 없으므로 "이게 전부"로 읽히면 오히려 잘못된 결론을 부른다.
            hint = (f"코퍼스의 context id {len(ordered)}개 중 사전순 앞 "
                    f"{_SCOPE_SUGGESTION_LIMIT}개: {shown} — 찾는 것이 없으면 "
                    f"검색 결과 적중의 context_id를 본다")
        else:
            hint = f"코퍼스의 context id: {shown}"
    else:
        hint = "코퍼스에 context가 하나도 없다"
    raise UnknownScopeError(
        f"scope로 지정한 context가 코퍼스에 없다: {scope} — {hint}"
    )


def recall(query: str, scope=None, db_path=None, embedder=None, brain_root=None,
           store=None, auto_scope=True) -> list[dict]:
    """BM25 + 벡터를 RRF로 융합해 §3 결과 계약 리스트를 돌려준다(슬라이스 3·4).

    BM25 top50(search_bm25) + 벡터 top50(search_vector) → RRF 융합(k=60) → top30 →
    그래프 1-hop 동반(§3.5: linked 채움 + graph_reached/graph_hits 분리 신호) →
    그래프 상호지지 재정렬(§3.5 후반·§8: capped graph_support를 1순위 키로, RRF 순위 동점).
    두 채널 중 한쪽이 비어도(예: 토큰 0개라 BM25 0건) 다른 쪽만으로 동작한다.

    scope: 주면 벡터 채널은 over-fetch 후 context_id로 거르고(search_vector 구현),
           융합 결과도 context_id로 한 번 더 거른다(BM25 채널 적중 포함) — top30
           절단 전에 거르므로 scope 밖 적중이 자리를 차지하지 않는다.
           ★scope가 확정되면 객체 레인 BM25는 search_bm25_scoped(후보 집합 내
           df 재계산)로 바뀐다 — scope 밖 적재 면역(§3.2 scoped 레인, 2026-06-12).★
           ★None이고 auto_scope면 질의 표면에서 자동 추론한다(infer_scope, P2 3번) —
           질의가 기능명을 단일 특정하면 그 컨텍스트로 하드 필터, 아니면 전체 검색.★
           명시한 id를 코퍼스가 모르면 UnknownScopeError(#74) — 조용한 전 채널
           0건으로 오타와 미적재가 섞이지 않게(_known_scopes).
    db_path: None이면 config(.project-brain.json)의 db.
    embedder: None이면 search_vector가 get_embedder()로 색인과 같은 팩토리에서 만든다.
    brain_root: None이면 config의 brain_root. 그래프 1-hop을 따라가려면 store가
                필요하다 — ★recall 호출당 1회만 로드★(과업 2번). surface 원문 승급에도 쓴다.
    auto_scope: False면 scope 자동 추론을 건너뛴다(#74 scope 해제) — scope=None과
                함께 주면 하드 필터 없이 전체 코퍼스를 회수한다. scope를 명시하면
                애초에 추론하지 않으므로 이 인자와 무관하게 그 컨텍스트만 회수한다.
    store: 이미 로드한 BrainStore를 주면 brain_root 로드를 건너뛴다(후속 b — 장수
           라우터가 질의마다 코퍼스를 다시 읽지 않게 self.store 재사용). brain_root와
           같은 코퍼스여야 한다(호출자 책임). brain_root는 store 주입 여부와 무관하게
           항상 해석한다 — 신선도 가드(§7)가 현재 코퍼스 지문 계산에 resolved_root를
           사용하므로 생략 불가.

    원소: {object_id, kind, status, context_id, score, matched_via, surface, linked,
          graph_reached, graph_hits, graph_support}. matched_via = "bm25"|"vector"|"both".
    반환 순서는 그래프 상호지지 재정렬을 따른다(점수 내림차순이 아닐 수 있음 — 재정렬 결과).
    """
    db_path = resolve_db_path(db_path)

    # store는 scope 추론·그래프 1-hop·surface 승급이 같이 쓴다 — ★호출당 1회만 로드★,
    # 주입받았으면(후속 b) 로드 생략. brain_root 해석은 신선도 가드(raw 지문)에도 필요.
    resolved_root = resolve_brain_root(brain_root)
    if store is None:
        store = BrainStore.load(resolved_root)
    # 신선도 가드(§7): 색인 meta의 코퍼스 지문 vs 현재 store 지문. stale 색인은
    # superseded 객체를 옛 status로 회상하는 침묵 오답을 만든다 — 스키마 버전
    # 가드와 같은 철학으로 시끄럽게 거부하고 해결책(rebuild)을 안내한다.
    _guard_index_freshness(db_path, store, resolved_root)
    if scope is not None:
        _guard_scope_exists(scope, db_path, store)
    elif auto_scope:
        scope = infer_scope(query, store)

    # raw 별도 레인(§2.2): 채널 검색을 과대 적재한 뒤 kind로 갈라 객체 레인은 기존
    # 상한(CHANNEL_TOP_N)으로 자른다 — 객체 파이프라인(융합·그래프·재정렬)은 raw가
    # 몇 개든 영향을 받지 않는다(레인 분리 — 회귀 가드).
    fetch_n = CHANNEL_TOP_N * _RAW_LANE_FETCH_FACTOR
    bm25_all = search_bm25(db_path, query, top_n=fetch_n)["results"]
    vector_all = search_vector(
        db_path, query, top_n=fetch_n, scope=scope, embedder=embedder
    )["results"]
    if scope is not None:
        # §3.2 scoped 레인(2026-06-12 s1 회귀 해법): scope가 단일 특정되면 객체
        # 레인 BM25는 후보 집합 안에서 df·avgdl을 재계산한다 — scope 밖 적재가
        # scope 안 순위를 못 흔든다(전역 FTS5 df 오염 면역). raw 레인은 아래
        # 전역 결과(bm25_all)에서 그대로 추출한다(발췌 보조 채널 — §2.2, 정밀
        # 순위 비대상. 전역 호출 1회가 raw 레인용으로 남는 비용은 무시 가능).
        bm25 = search_bm25_scoped(db_path, query, scope,
                                  top_n=CHANNEL_TOP_N)["results"]
    else:
        bm25 = [r for r in bm25_all
                if r.get("kind") not in _OBJECT_LANE_EXCLUDED][:CHANNEL_TOP_N]
    vector = [r for r in vector_all
              if r.get("kind") not in _OBJECT_LANE_EXCLUDED][:CHANNEL_TOP_N]
    raw_bm25 = [r for r in bm25_all if r.get("kind") == RAW_KIND][:CHANNEL_TOP_N]
    raw_vector = [r for r in vector_all if r.get("kind") == RAW_KIND][:CHANNEL_TOP_N]
    insight_bm25 = [r for r in bm25_all if r.get("kind") == INSIGHT_KIND][:CHANNEL_TOP_N]
    insight_vector = [r for r in vector_all if r.get("kind") == INSIGHT_KIND][:CHANNEL_TOP_N]
    projection_bm25 = [r for r in bm25_all if r.get("kind") == PROJECTION_KIND][:CHANNEL_TOP_N]
    projection_vector = [r for r in vector_all if r.get("kind") == PROJECTION_KIND][:CHANNEL_TOP_N]

    # 채널별 객체 메타를 모은다(첫 등장 우선 — 두 채널의 kind/status/context_id는 동일).
    meta: dict[str, dict] = {}
    bm25_ids = []
    for r in bm25:
        bm25_ids.append(r["object_id"])
        meta.setdefault(r["object_id"], r)
    vector_ids = []
    for r in vector:
        vector_ids.append(r["object_id"])
        meta.setdefault(r["object_id"], r)

    bm25_set = set(bm25_ids)
    vector_set = set(vector_ids)

    fused = rrf_fuse([bm25_ids, vector_ids])

    # scope 필터(융합 후): 벡터 채널은 search_vector가 이미 걸렀지만 BM25 채널 적중이
    # 섞여 있을 수 있다 — top30 절단 전에 context_id로 거른다(2026-06-10 리뷰 반영).
    if scope is not None:
        fused = [(oid, s) for oid, s in fused
                 if meta[oid].get("context_id") == scope]

    top = fused[:FUSED_TOP_N]
    top_ids = [oid for oid, _ in top]
    score_by_id = dict(top)

    # 그래프 1-hop — store는 초입에서 로드됨(scope 추론과 공유). 색인이 없는 객체
    # (검색 제외 kind 등)는 store.has로 걸러진다.
    graph_hits_map, graph_support_map = _graph_signals_by_id(top_ids, store)

    # 그래프 상호지지 재정렬(§3.5 후반·§8): 아웃바운드 도달(capped)을 1순위 키로 재정렬.
    # ★RRF 점수는 그대로 동반 표시하되 순서는 재정렬을 따른다★ — 점수 합산 금지(§3.5).
    reranked_ids = _rerank_by_support(top_ids, graph_support_map)

    hits: list[dict] = []
    for object_id in reranked_ids:
        score = score_by_id[object_id]
        in_bm25 = object_id in bm25_set
        in_vector = object_id in vector_set
        if in_bm25 and in_vector:
            matched_via = "both"
        elif in_bm25:
            matched_via = "bm25"
        else:
            matched_via = "vector"
        m = meta[object_id]
        # surface 승급(과업 3번): store를 어차피 로드하므로 tokenized_text 대신
        # extract_surface 원문 표면으로(슬라이스 3의 명시된 단순화 해소). store에 없거나
        # 표면이 없으면 빈 문자열.
        surface = ""
        if store.has(object_id):
            surface = extract_surface(store.get(object_id), store) or ""
        graph_hits = graph_hits_map.get(object_id, 0)
        graph_support = graph_support_map.get(object_id, 0)
        hits.append({
            "object_id": object_id,
            "kind": m.get("kind"),
            "status": m.get("status"),
            "context_id": m.get("context_id"),
            "score": score,
            "matched_via": matched_via,
            "surface": surface,
            "linked": _build_linked(object_id, store),
            "graph_reached": graph_hits > 0,
            "graph_hits": graph_hits,
            # 재정렬에 쓴 아웃바운드 도달 수(캡 미적용 원값 — 표시·진단용, §3.5 후반).
            "graph_support": graph_support,
        })

    # raw 레인(§2.2): 따로 융합해 객체 적중 ★뒤에★ 붙인다. raw 청크는 store에 없는
    # 행이라 그래프·surface 승급이 없다 — 원문은 색인의 surface_text가 운반하고,
    # linked는 빈 구조(채널 분리는 eval_recall의 raw_excerpts 몫).
    if raw_bm25 or raw_vector:
        raw_meta: dict[str, dict] = {}
        raw_bm25_ids = []
        for r in raw_bm25:
            raw_bm25_ids.append(r["object_id"])
            raw_meta.setdefault(r["object_id"], r)
        raw_vector_ids = []
        for r in raw_vector:
            raw_vector_ids.append(r["object_id"])
            raw_meta.setdefault(r["object_id"], r)
        raw_fused = rrf_fuse([raw_bm25_ids, raw_vector_ids])
        if scope is not None:
            raw_fused = [(oid, s) for oid, s in raw_fused
                         if raw_meta[oid].get("context_id") == scope]
        raw_bm25_set = set(raw_bm25_ids)
        raw_vector_set = set(raw_vector_ids)
        for object_id, score in raw_fused[:RAW_FUSED_TOP_N]:
            in_b, in_v = object_id in raw_bm25_set, object_id in raw_vector_set
            m = raw_meta[object_id]
            hits.append({
                "object_id": object_id,
                "kind": m.get("kind"),
                "status": m.get("status"),
                "context_id": m.get("context_id"),
                "score": score,
                "matched_via": "both" if (in_b and in_v) else ("bm25" if in_b else "vector"),
                "surface": m.get("surface_text") or "",
                "linked": {"code_locators": [], "evidence_ref_ids": [],
                           "related_object_ids": []},
                "graph_reached": False,
                "graph_hits": 0,
                "graph_support": 0,
            })
    # Insight 별도 레인(§4.6): 객체 적중 뒤에 붙인다. store 객체라 surface 승급·linked는
    # 하되 그래프 재정렬 입력에선 빠진다(graph_support=0). ★linked.code_locators는 담기지만
    # source_object_ids는 공용 _build_linked가 안 따라간다(critic 검토 4) — 가로지름은 router
    # advisory가 source_object_ids로 직접 노출한다. scope 필터 미적용: Insight는 context_id가
    # 없어 필터를 걸면 advisory가 항상 0이 된다(critic 검토 3).
    if insight_bm25 or insight_vector:
        ins_meta: dict[str, dict] = {}
        ins_bm25_ids = []
        for r in insight_bm25:
            ins_bm25_ids.append(r["object_id"])
            ins_meta.setdefault(r["object_id"], r)
        ins_vector_ids = []
        for r in insight_vector:
            ins_vector_ids.append(r["object_id"])
            ins_meta.setdefault(r["object_id"], r)
        ins_fused = rrf_fuse([ins_bm25_ids, ins_vector_ids])
        # scope 필터 없음: Insight는 context_id가 없어 raw처럼 context_id==scope를 걸면 전멸(위 블록 주석 참조).
        ins_bm25_set = set(ins_bm25_ids)
        ins_vector_set = set(ins_vector_ids)
        for object_id, score in ins_fused[:RAW_FUSED_TOP_N]:
            in_b, in_v = object_id in ins_bm25_set, object_id in ins_vector_set
            m = ins_meta[object_id]
            surface = ""
            if store.has(object_id):
                surface = extract_surface(store.get(object_id), store) or ""
            hits.append({
                "object_id": object_id,
                "kind": m.get("kind"),
                "status": m.get("status"),
                "context_id": m.get("context_id"),
                "score": score,
                "matched_via": "both" if (in_b and in_v) else ("bm25" if in_b else "vector"),
                "surface": surface,
                "linked": _build_linked(object_id, store),
                "graph_reached": False,
                "graph_hits": 0,
                "graph_support": 0,
            })
    # ContextProjection 재사용 레인(2026-06-17 projection_reuse): raw·Insight와 동형으로
    # 따로 융합해 객체·raw·Insight 적중 ★뒤에★ 붙인다. 원문은 색인의 surface_text가
    # 운반하고, linked는 빈 구조(채널 분리·정본 results 제외는 eval_recall 몫).
    if projection_bm25 or projection_vector:
        proj_meta: dict[str, dict] = {}
        proj_bm25_ids = []
        for r in projection_bm25:
            proj_bm25_ids.append(r["object_id"])
            proj_meta.setdefault(r["object_id"], r)
        proj_vector_ids = []
        for r in projection_vector:
            proj_vector_ids.append(r["object_id"])
            proj_meta.setdefault(r["object_id"], r)
        proj_fused = rrf_fuse([proj_bm25_ids, proj_vector_ids])
        if scope is not None:
            proj_fused = [(oid, s) for oid, s in proj_fused
                          if proj_meta[oid].get("context_id") == scope]
        proj_bm25_set = set(proj_bm25_ids)
        proj_vector_set = set(proj_vector_ids)
        for object_id, score in proj_fused[:RAW_FUSED_TOP_N]:
            in_b, in_v = object_id in proj_bm25_set, object_id in proj_vector_set
            m = proj_meta[object_id]
            hits.append({
                "object_id": object_id,
                "kind": m.get("kind"),
                "status": m.get("status"),
                "context_id": m.get("context_id"),
                "score": score,
                "matched_via": "both" if (in_b and in_v) else ("bm25" if in_b else "vector"),
                "surface": m.get("surface_text") or "",
                "linked": {"code_locators": [], "evidence_ref_ids": [],
                           "related_object_ids": []},
                "graph_reached": False,
                "graph_hits": 0,
                "graph_support": 0,
            })
    return hits


def _fts_token_expr(token: str) -> str:
    """FTS5 MATCH용 단일 토큰 인용식 — search_bm25와 같은 규칙(개별 "..." 인용, prefix 없음).

    색인·쿼리 토큰화가 같은 tokenize()를 공유하므로 색인측 토큰과 그대로 대조된다(§6).
    """
    return '"' + token.replace('"', '""') + '"'


def _document_frequency(conn: sqlite3.Connection, token: str) -> int:
    """토큰 1개가 매칭되는 ★객체★ 색인 문서 수(document frequency). FTS5 MATCH로 센다.

    ★raw 청크·Insight·ContextProjection 행은 제외★(2026-06-11·2026-06-15·2026-06-17).
    이 값은 회수 사실의 object_df로 나가며(compute_query_token_facts), raw df와 갈라
    "객체로는 회수되지 않았지만 기획서 원문에는 있다"를 말할 수 있게 하는 수다. 셋 다
    자유 텍스트 다토큰이라 객체 분포에 섞이면 그 구분이 흐려진다 — Insight·projection은
    정본 객체를 재서술·곁들이는 본문이고 raw는 애초에 짝이 되는 별도 수다.
    """
    return conn.execute(
        "SELECT COUNT(*) FROM documents_fts f "
        "JOIN documents d ON d.object_id = f.object_id "
        "WHERE documents_fts MATCH ? AND d.kind NOT IN (?, ?, ?)",
        (_fts_token_expr(token), RAW_KIND, INSIGHT_KIND, PROJECTION_KIND)
    ).fetchone()[0]


def _raw_document_frequency(conn: sqlite3.Connection, token: str) -> int:
    """토큰 1개가 매칭되는 ★raw 청크★ 행 수. 객체 df(_document_frequency)의 짝이다.

    둘을 함께 신고해야 "객체로는 회수되지 않았지만 기획서 원문에는 있다"를 "어디에도
    없다"와 가를 수 있다(#73 회수 사실 — 판정이 아니라 확인 지시).
    """
    return conn.execute(
        "SELECT COUNT(*) FROM documents_fts f "
        "JOIN documents d ON d.object_id = f.object_id "
        "WHERE documents_fts MATCH ? AND d.kind = ?",
        (_fts_token_expr(token), RAW_KIND)
    ).fetchone()[0]


def compute_query_token_facts(query: str, db_path) -> list[dict]:
    """질의 토큰 분해와 토큰별 df 사실(#73 — 회수 사실, 판정 아님).

    tokenize()가 낸 순서와 중복 제거를 ★그대로★ 노출한다(길이 필터 없음) — 형태소
    쪼개짐("인게임"→"인"+"게임")이나 표기 변형 때문에 부재가 오탐일 수 있음을
    에이전트가 직접 보고 판단해야 하기 때문이다(ADR 0008).

    원소: {token, object_df, raw_df}. object_df는 raw 청크·Insight·ContextProjection을
    제외한 색인 문서 수, raw_df는 raw 청크 수다. 어느 값도 boolean 판정이 아니다.
    """
    tokens = tokenize(query)
    if not tokens:
        return []
    conn = sqlite3.connect(str(db_path))
    try:
        return [
            {"token": token,
             "object_df": _document_frequency(conn, token),
             "raw_df": _raw_document_frequency(conn, token)}
            for token in tokens
        ]
    finally:
        conn.close()


def _matched_query_tokens_by_id(db_path, object_ids, tokens) -> dict[str, list[str]]:
    """적중별로 ★그 적중의 색인 본문에 실제로 있는★ 질의 토큰만 추린다(#73).

    documents.tokenized_text는 색인 시 tokenize() 출력을 공백으로 이은 것이라, 질의
    토큰과 같은 규칙으로 나뉜 문자열이다 — 공백 분리 집합 대조가 곧 색인 본문 대조다
    (§6 색인·쿼리 대칭). raw 청크 행도 같은 컬럼을 쓰므로 발췌 채널에도 그대로 적용된다.
    반환 리스트는 질의 토큰 순서를 보존한다.
    """
    if not object_ids or not tokens:
        return {}
    placeholders = ",".join("?" * len(object_ids))
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            f"SELECT object_id, tokenized_text FROM documents "
            f"WHERE object_id IN ({placeholders})",
            list(object_ids),
        ).fetchall()
    finally:
        conn.close()
    matched: dict[str, list[str]] = {}
    for object_id, tokenized_text in rows:
        indexed = set((tokenized_text or "").split())
        matched[object_id] = [t for t in tokens if t in indexed]
    return matched


# 회수 응답이 신고하는 scope 적용 출처(#73 origin + #74 명시 지정·해제).
#   "explicit" — 호출자가 scope를 직접 지정 (context_id = 그 값)
#   "inferred" — 질의 표면에서 자동 추론이 컨텍스트를 단일 특정 (context_id = 추론값)
#   "disabled" — 호출자가 추론을 껐다(auto_scope=False) (context_id = None)
#   "none"     — 추론했으나 단일 특정 실패 (context_id = None)
# ★"disabled"와 "none"을 가른다★(#74): 하드 필터가 없다는 결과는 같지만 이유가 다르다.
# 에이전트는 "내가 끈 것"과 "엔진이 컨텍스트를 못 좁힌 것"을 응답만 보고 구분해야
# 다음 수(다시 좁힐지, 질의를 바꿀지)를 고른다 — 사실 보고이지 판정이 아니다(ADR 0008).
def _resolve_scope(query, scope, auto_scope, store):
    """(적용할 scope, 신고할 origin)을 한 자리에서 정한다.

    ★한 자리★인 것이 계약이다 — 응답에 신고하는 값과 recall에 넘겨 실제로 걸리는
    하드 필터가 갈라지지 않는다(#73 배관 보장).
    """
    if scope is not None:
        return scope, "explicit"
    if not auto_scope:
        return None, "disabled"
    inferred = infer_scope(query, store)
    return inferred, ("inferred" if inferred is not None else "none")


def eval_recall(query: str, db_path=None, embedder=None, brain_root=None,
                store=None, scope=None, auto_scope=True,
                channel_top_k=EVAL_CHANNEL_TOP_K) -> dict:
    """평가 하네스 진입점 — recall을 검수 상태·객체 종류만으로 채널로 가른다(#77).

    ADR 0008: 엔진은 회수만 하고 답변 판정은 에이전트가 한다. 회수한 객체를 엔진
    판정으로 숨기는 층은 없다 — 채널 배치는 status·kind로만 결정된다.

    반환(§7 산출식 + §2.2 raw 채널):
      results            — reviewed 적중 top-k (Insight·ContextProjection 제외)
      candidates         — candidate 적중 top-k (Insight·ContextProjection 제외)
      raw_excerpts       — raw 청크 적중 top-k ("원문 발췌(미검수)")
      advisories         — reviewed Insight 적중 top-k (가로지르는 위험/교훈 — 곁들임 채널.
                            candidate Insight는 1차 미노출)
      projection_reuse   — ContextProjection 적중 top-k (이전 착수 브리핑 재사용 채널 —
                            status 무관 한 통로. results/candidates에는 안 섞인다)

    회수 사실(#73, ADR 0008 — 엔진은 회수만 하고 답변 판정은 에이전트가 한다). 아래
    필드는 전부 결정론 계산이며 어떤 값도 boolean 판정이 아니다. 명부 매칭 사실은 싣지
    않는다(등재 어휘가 걸리면 GlossaryTerm 객체 자체가 results에 오른다).
      query_tokens       — [{token, object_df, raw_df}] 질의 토큰 분해와 토큰별 문서 빈도.
                            tokenize 순서·중복 제거 그대로(길이 필터 없음).
      scope              — {context_id, origin} 적용된 scope. origin은 네 값이다 —
                            "explicit"(호출자 지정), "inferred"(질의 표면에서 자동 추론),
                            "disabled"(auto_scope=False로 추론을 껐다),
                            "none"(추론했으나 단일 특정 실패). 뒤 둘은 context_id=None
                            으로 결과가 같지만 이유가 달라 값을 가른다(_resolve_scope).
      matched_query_tokens — 채널 적중마다 동반. 질의 토큰 중 그 적중의 색인 본문에
                            실제로 있는 것만(raw 발췌 포함).

    db_path 미지정 시 config(.project-brain.json)의 db를 쓰며, 색인이 없으면 명확한
    에러를 던진다 — 하네스(evaluate)가 per-scenario 실패로 기록한다. brain_root는
    recall에 그대로 넘겨 그래프 1-hop store를 로드한다(None이면 config의 brain_root).
    store는 recall로 그대로 넘긴다(후속 b — 주면 brain_root 재로드 생략).

    scope/auto_scope는 _resolve_scope를 거쳐 recall로 넘어간다(#74) — 지정하면 그
    context로만 회수하고, auto_scope=False면 추론 없이 전체를 회수한다(origin은 각각
    "explicit"·"disabled"). 모르는 id는 UnknownScopeError.
    channel_top_k는 채널별 상한이며 기본값은 EVAL_CHANNEL_TOP_K(=5)다 — 하네스는
    recall_fn(query) 한 인자로만 부르므로 측정 단위가 이 기본값으로 고정되고, 표시
    상한을 넓히는 쪽(CLI)이 명시로 넘긴다. 상한은 자르기만 하므로 recall 레인 절단
    (FUSED_TOP_N·RAW_FUSED_TOP_N)보다 많이 보여줄 수는 없다.
    """
    db_path = resolve_db_path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(
            f"색인 DB 없음: {db_path} — `cli index rebuild` 먼저 실행해야 한다(스펙 §4)."
        )

    resolved_root = resolve_brain_root(brain_root)
    if store is None:
        store = BrainStore.load(resolved_root)

    # scope는 여기서 한 번 풀어 recall에 넘긴다 — 응답에 신고하는 값과 실제로 적용된
    # 하드 필터가 같은 값임을 배관으로 보장하기 위해서다(#73). 세 갈래를 여기서 다
    # 정하고 recall에는 auto_scope=False로 넘겨(#74) recall이 다시 추론하지 않게 한다.
    scope, scope_origin = _resolve_scope(query, scope, auto_scope, store)
    hits = recall(query, scope=scope, db_path=db_path, embedder=embedder,
                  brain_root=resolved_root, store=store, auto_scope=False)
    # 회수 사실(#73): 질의 토큰 분해·토큰별 df·적중별 겹친 질의 토큰. 채널을 가르기
    # ★전에★ 적중에 붙여 다섯 채널이 같은 사실을 그대로 들고 나가게 한다.
    query_tokens = compute_query_token_facts(query, db_path)
    matched = _matched_query_tokens_by_id(
        db_path, [h["object_id"] for h in hits], [f["token"] for f in query_tokens])
    hits = [{**h, "matched_query_tokens": matched.get(h["object_id"], [])} for h in hits]

    results = [h for h in hits
               if h.get("status") == "reviewed"
               and h.get("kind") != INSIGHT_KIND
               and h.get("kind") != PROJECTION_KIND][:channel_top_k]
    candidates = [h for h in hits
                  if h.get("status") == "candidate"
                  and h.get("kind") != INSIGHT_KIND
                  and h.get("kind") != PROJECTION_KIND][:channel_top_k]
    raw_excerpts = [h for h in hits
                    if h.get("status") == RAW_STATUS][:channel_top_k]
    # advisories(§4.6 C1): reviewed Insight를 별도 통로로 — "가로지르는" 곁들임이라
    # results에 섞지 않는다. candidate Insight는 1차 미노출(미룸 §7).
    advisories = [h for h in hits
                  if h.get("kind") == INSIGHT_KIND
                  and h.get("status") == "reviewed"][:channel_top_k]
    # projection_reuse(spec 2026-06-17 Task A5): ContextProjection을 별도 통로로 —
    # candidate·reviewed status 무관 한 채널로(results/candidates에는 위에서 제외).
    projection_reuse = [h for h in hits
                        if h.get("kind") == PROJECTION_KIND][:channel_top_k]
    return {
        "results": results,
        "candidates": candidates,
        "raw_excerpts": raw_excerpts,
        "advisories": advisories,
        "projection_reuse": projection_reuse,
        "query_tokens": query_tokens,
        "scope": {"context_id": scope, "origin": scope_origin},
    }
