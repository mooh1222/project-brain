"""RRF 융합 + recall() + 그래프 1-hop + eval_recall 어댑터 (스펙 §3.4·§3.5·§3 결과 계약).

spec: docs/superpowers/specs/2026-06-10-project-brain-search-layer-design.md

BM25 채널(search_bm25)과 벡터 채널(search_vector)을 각각 top 50 받아 RRF로 융합한다
(§3.4: score = Σ 1/(60+rank), k=60). 두 채널은 이미 "좋은 순"으로 정렬돼 있으므로
(BM25 점수는 작을수록·벡터 거리도 작을수록 좋음) rank만 쓰면 된다. 융합 결과 top 30을
§3 결과 계약 dict로 만든다.

슬라이스 4(§3.5 그래프 1-hop): 융합 top-30 적중에서 참조 필드를 1-hop 따라 linked를
채우고(code_locators는 {object_id, path, symbol} 객체형), top-30 적중집합 안의 상호
연결 도달 횟수를 graph_reached(bool)·graph_hits(횟수)로 분리 기록한다. evidence_refs는
표시 전용(linked.evidence_ref_ids)이라 랭킹·그래프 도달 계산에서 제외한다.

캘리브레이션(§3.5 후반·§8 그래프 재정렬): 융합 top-30을 그래프 ★상호지지★로 결정론
재정렬한다 — graph_support(자기 엣지가 적중집합 안의 다른 적중을 가리킨 아웃바운드 도달
수)를 캡(_GRAPH_SUPPORT_CAP)으로 자른 뒤 사전식(lexicographic) 1순위 키로, 동점은 원래
RRF 순위·object_id로 깬다. ★RRF 점수에 임의 상수를 더하지 않는다(§3.5)★. 캡이 허브
객체(엣지 100+개)의 도달을 초점 매핑과 같은 상한으로 눌러 허브가 그래프 신호로 더
굳어지는 것을 막는다(과업 3번). 실측: s1 목표 매핑 10등→top5, s2 9등→top5(§8).

슬라이스 5(§7·§8 다신호 답변 게이트): `eval_recall(query)`는 recall 융합 결과를
다신호 게이트에 통과시킨 뒤 검수 상태별 채널로 가른다. 게이트 신호 3개 —
(i) RRF 절대 점수 (ii) 1등-2등 점수 차(margin) (iii) ★표면 앵커★(질의의 코퍼스
존재 내용 토큰 중 가장 희소한 토큰의 document frequency). "존재하지 않는 엔티티"
질의는 (iii)가 우선 신호 — 코퍼스에 흔한 토큰(보상·이벤트)만 매칭되고 희소한
핵심 엔티티(크리스마스 — df 0)가 미매칭이면 표면 앵커가 없어 needs_clarification을
켠다. 단일 임계가 아니라 다신호라서 시나리오 3(적중)과 5(거짓 양성 가드)를 동시에
만족한다(§7·§8). 게이트는 순수 함수(_gate_pass)로 분리해 합성 입력 단위 테스트가
가능하고, candidate/reviewed는 채널별로 임계를 나눈다(§7 채널 분리 — candidate는
후보 채널이라 더 관대한 바닥).
"""

import re
import sqlite3
from pathlib import Path

from project_brain.config import resolve_brain_root, resolve_db_path
from project_brain.raw_chunks import RAW_KIND, RAW_STATUS
from project_brain.search_index import (
    search_bm25,
    search_bm25_scoped,
    search_vector,
)
from project_brain.store import BrainStore
from project_brain.surface import extract_surface
from project_brain.tokenize_ko import tokenize

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

# eval_recall이 채널별로 노출하는 상한(§8 평가 — top-5 적중 측정 단위).
EVAL_CHANNEL_TOP_K = 5

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

# ── 다신호 답변 게이트 계수(§7·§8 — 단일 임계 금지, 3신호) ──────────────────
# 셋 다 실모델 cli eval 캘리브레이션 값(2026-06-10, 골든셋 s1~s5). 값 단언 테스트
# (test_calibration_constants_pinned)가 침묵 드리프트를 막는다 — 바꾸려면 실모델
# cli eval 재측정 후 단언을 같이 갱신할 것.

# (iii) 표면 앵커 상한: 질의의 ★코퍼스 존재 내용 토큰★ 중 가장 희소한 토큰(앵커)의
# document frequency가 이 값을 넘으면 = 흔한 토큰만 매칭되고 희소한 핵심 엔티티가
# 미매칭 = 표면 앵커 부재 → 게이트. ★s5 거짓 양성 가드의 핵심★: '보상'(df 52)·
# '이벤트'(df 68)는 흔해 의미 점수만으론 못 거르지만, 질의의 유일한 희소 토큰
# '크리스마스'는 코퍼스 df 0이라 present 앵커의 최소 df가 52로 높다. 실측 앵커 df:
# s1=1·s2=17·s3=6·s4=5(전부 ≤17, anchored) / s5=52(>30, gated). 18~51 전 구간에서
# s1~s4 통과+s5 차단 동시 만족(프로브 실측) — 30은 그 폭의 중앙(코퍼스 302문서의
# ≈10%, "10% 이상 문서에 든 토큰은 generic"이라는 해석. 한쪽 경계에 붙인 값이 아님).
_ANCHOR_DF_MAX = 30

# (i) 절대 점수 바닥(채널별). RRF 점수 스케일은 ~0.014~0.033(실측). 이 바닥은 s5
# 게이트가 아니라(s5 top 점수 0.0275는 confident 수준이라 점수만으론 못 거름 — 그건
# 앵커 신호 몫) ★degenerate한 약한 적중★을 막는 방어선이다. reviewed 골든셋 최저
# 유지 대상은 s3 reviewed target 0.0278이므로 그보다 한참 낮게 둔다. candidate는 후보
# 채널이라 더 관대(낮은 바닥) — "후보 노출 안 되면 승격 기회 영영 없음"(06-05)과
# 거짓 양성 가드를 채널 분리로 동시 충족(§7). s3 candidate target 최저 0.0257 유지.
_ABS_SCORE_FLOOR_REVIEWED = 0.005
_ABS_SCORE_FLOOR_CANDIDATE = 0.001


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

    - code_locators: code_locator_ids가 가리키는 CodeLocator를 ★{object_id, path, symbol}
      객체로★ 동반(jira→코드 핀포인트 — id만으론 핀포인트가 아니다, 과업 1번).
    - related_object_ids: 용어/결정/매핑 등 나머지 4종 엣지가 가리키는 연결 객체 id.
    - evidence_ref_ids: 해당 객체의 evidence_refs(★표시 전용 — 랭킹·그래프 입력 금지★).
    ★dangling id(store에 없는 참조)는 건너뛴다★.
    """
    obj = store.get(object_id) if store.has(object_id) else {}

    code_locators = []
    for cid in obj.get(_CODE_EDGE_FIELD) or []:
        if not store.has(cid):
            continue
        c = store.get(cid)
        code_locators.append({
            "object_id": cid,
            "path": c.get("path"),
            "symbol": c.get("symbol"),
        })

    related: list[str] = []
    for field in _RELATED_EDGE_FIELDS:
        for rid in obj.get(field) or []:
            if store.has(rid) and rid not in related:
                related.append(rid)

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


def recall(query: str, scope=None, db_path=None, embedder=None, brain_root=None,
           store=None) -> list[dict]:
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
           ★None이면 질의 표면에서 자동 추론한다(infer_scope, P2 3번) — 질의가
           기능명을 단일 특정하면 그 컨텍스트로 하드 필터, 아니면 전체 검색.★
    db_path: None이면 config(.project-brain.json)의 db.
    embedder: None이면 search_vector가 get_embedder()로 색인과 같은 팩토리에서 만든다.
    brain_root: None이면 config의 brain_root. 그래프 1-hop을 따라가려면 store가
                필요하다 — ★recall 호출당 1회만 로드★(과업 2번). surface 원문 승급에도 쓴다.
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
    if scope is None:
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


# ── 다신호 게이트(§7·§8) ────────────────────────────────────────────────────
# 내용 토큰 휴리스틱: 길이 2자 이상 토큰만 앵커 후보로 본다(1글자 조사·어미·숫자
# 제외). 정밀한 품사 태깅이 아니라 ★단순 규칙★(과설계 금지, 과업 1번) — 1글자
# 문법 형태소가 앵커 df를 인위적으로 낮추는 것만 막으면 충분하다(s5 가드 목적).
_ANCHOR_MIN_TOKEN_LEN = 2


def _document_frequency(conn: sqlite3.Connection, token: str) -> int:
    """토큰 1개가 매칭되는 색인 문서 수(document frequency). FTS5 MATCH로 센다.

    search_bm25와 같은 토큰 인용 규칙(개별 "..." 인용, prefix 없음)을 쓴다 — 색인·쿼리
    토큰화가 같은 tokenize()를 공유하므로 색인측 토큰과 그대로 대조된다(§6).
    ★raw 청크·Insight·ContextProjection 행은 제외★(2026-06-11·2026-06-15·2026-06-17) —
    앵커 df 상한(_ANCHOR_DF_MAX=30)은 객체 코퍼스 분포로 보정된 값(§8)이라, 셋 다 자유
    텍스트 다토큰이라 분포를 흔들면 보정이 깨진다(Insight가 31개 이상 쌓이면 공유 토큰 df가
    상한을 넘겨 객체 게이트를 닫는 C2 누수). projection은 정본 객체를 재서술한 본문이라
    앵커 df에 섞이면 정본 회수를 잠식한다.
    """
    expr = '"' + token.replace('"', '""') + '"'
    return conn.execute(
        "SELECT COUNT(*) FROM documents_fts f "
        "JOIN documents d ON d.object_id = f.object_id "
        "WHERE documents_fts MATCH ? AND d.kind NOT IN (?, ?, ?)",
        (expr, RAW_KIND, INSIGHT_KIND, PROJECTION_KIND)
    ).fetchone()[0]


def compute_query_signals(query: str, hits: list[dict], db_path) -> dict:
    """질의·융합 결과에서 다신호 게이트 입력 3종을 1회 계산한다(§7·§8 — 질의 레벨).

    - top_score   (i)   : 융합 top 적중의 RRF 절대 점수(없으면 0.0).
    - margin      (ii)  : 1등-2등 점수 차(2등 없으면 top_score).
    - anchor_df   (iii) : 질의의 ★코퍼스 존재 내용 토큰★(길이 2자+) 중 가장 희소한
                          토큰의 document frequency. present 내용 토큰이 하나도 없으면
                          None(앵커 부재) — '크리스마스'처럼 핵심 엔티티만 df 0인
                          질의에서, 남는 present 토큰이 흔하면(df 큼) 앵커 df가 높아진다.

    db_path는 anchor_df의 df 조회용 — recall이 이미 검증한 색인 DB를 그대로 받는다.
    """
    top_score = hits[0]["score"] if hits else 0.0
    second = hits[1]["score"] if len(hits) > 1 else 0.0
    margin = round(top_score - second, _SCORE_ROUND)

    content_tokens = [t for t in tokenize(query) if len(t) >= _ANCHOR_MIN_TOKEN_LEN]
    anchor_df = None
    if content_tokens:
        conn = sqlite3.connect(str(db_path))
        try:
            present_dfs = [df for df in (_document_frequency(conn, t) for t in content_tokens)
                           if df > 0]
        finally:
            conn.close()
        if present_dfs:
            anchor_df = min(present_dfs)

    return {"top_score": top_score, "margin": margin, "anchor_df": anchor_df}


def _gate_pass(score: float, signals: dict, *, channel: str) -> bool:
    """한 적중이 답변 게이트를 통과하는지 판정한다(§7·§8 다신호, ★순수 함수★).

    채널별 다신호 규칙:
    1. (i) 절대 점수 바닥 — channel에 따라 reviewed/candidate 바닥을 쓴다(채널 분리,
       §7). candidate는 더 관대(낮은 바닥)해 후보 노출 기회를 보존한다.
    2. (iii) 표면 앵커 — anchor_df가 None(present 내용 토큰 0)이거나 _ANCHOR_DF_MAX를
       넘으면(흔한 토큰만 매칭) 차단한다. ★s5 거짓 양성 가드의 우선 신호★ — 의미
       점수가 confident해도 질의 핵심 엔티티의 표면 앵커가 없으면 "없다"로 간다.

    (ii) margin은 signals에 동반돼 호출처·보고에 노출되지만 boolean 규칙에는 안 쓴다 —
    s5는 오히려 margin이 ★크다★(lone spurious spike, 실측 0.0119)라 "margin 크면
    confident"가 거꾸로 작동하기 때문이다. 단일 신호 과적합을 피하려 앵커(iii)+바닥(i)만
    boolean에 쓰고 margin은 진단·보고 신호로 둔다(과업 1번 "가장 단순한 규칙").

    ★raw 채널은 바닥만 적용, 앵커 미적용★(2026-06-11 설계 고정): 앵커는 단정 답
    채널(reviewed/candidate)용으로 보정된 가드다. raw 레인의 존재 이유가 "객체화
    안 된 기획서 서술 회수"(객체화 경계 규약)라 객체 코퍼스 앵커로 막으면 본말전도
    이고, raw는 "원문 발췌(미검수)" 라벨이 붙는 발췌 자료라 부정확 노출의 해가 낮다.
    """
    floor = (_ABS_SCORE_FLOOR_CANDIDATE if channel in ("candidate", "raw")
             else _ABS_SCORE_FLOOR_REVIEWED)
    if score < floor:
        return False
    if channel == "raw":
        return True
    anchor_df = signals.get("anchor_df")
    if anchor_df is None or anchor_df > _ANCHOR_DF_MAX:
        return False
    return True


def eval_recall(query: str, db_path=None, embedder=None, brain_root=None,
                store=None) -> dict:
    """평가 하네스 진입점 — recall을 다신호 게이트에 통과시켜 채널로 가른다(§7·§8).

    슬라이스 5(다신호 답변 게이트 적용판): recall 융합 결과에서 질의 레벨 신호 3종을
    1회 계산(compute_query_signals)한 뒤 적중마다 _gate_pass로 채널별 게이트를 적용한다.

    반환(§7 산출식 + §2.2 raw 채널):
      results            — ★게이트 통과★ reviewed 적중 top-5 (확신 채널, Insight 제외)
      candidates         — ★게이트 통과★ candidate 적중 top-5 (후보 채널 — 관대한 바닥, Insight 제외)
      raw_excerpts       — raw 청크 적중 top-5 ("원문 발췌(미검수)" — 바닥만, 앵커 미적용)
      advisories         — reviewed Insight 적중 top-5 (가로지르는 위험/교훈 — 곁들임 채널.
                            게이트는 reviewed 재사용 — 앵커 적용, 질의 토큰을 가진 객체가 있어야 뜸)
      projection_reuse   — ContextProjection 적중 top-5 (이전 착수 브리핑 재사용 채널 —
                            status 무관 한 통로, 게이트는 raw(바닥만, 앵커 미적용)라 어휘
                            드리프트 요구를 막지 않는다. results/candidates에는 안 섞인다)
      needs_clarification — reviewed 게이트 통과 0건 bool ("no evidence → 없다" 보존,
                            raw 발췌·advisories·projection_reuse는 단정 답이 아니라 이 판정에 안 들어간다)

    db_path 미지정 시 config(.project-brain.json)의 db를 쓰며, 색인이 없으면 명확한
    에러를 던진다 — 하네스(evaluate)가 per-scenario 실패로 기록한다. brain_root는
    recall에 그대로 넘겨 그래프 1-hop store를 로드한다(None이면 config의 brain_root).
    store는 recall로 그대로 넘긴다(후속 b — 주면 brain_root 재로드 생략).
    """
    db_path = resolve_db_path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(
            f"색인 DB 없음: {db_path} — `cli index rebuild` 먼저 실행해야 한다(스펙 §4)."
        )

    hits = recall(query, db_path=db_path, embedder=embedder, brain_root=brain_root,
                  store=store)
    signals = compute_query_signals(query, hits, db_path)

    results = [h for h in hits
               if h.get("status") == "reviewed"
               and h.get("kind") != INSIGHT_KIND
               and h.get("kind") != PROJECTION_KIND
               and _gate_pass(h["score"], signals, channel="reviewed")][:EVAL_CHANNEL_TOP_K]
    candidates = [h for h in hits
                  if h.get("status") == "candidate"
                  and h.get("kind") != INSIGHT_KIND
                  and h.get("kind") != PROJECTION_KIND
                  and _gate_pass(h["score"], signals, channel="candidate")][:EVAL_CHANNEL_TOP_K]
    raw_excerpts = [h for h in hits
                    if h.get("status") == RAW_STATUS
                    and _gate_pass(h["score"], signals, channel="raw")][:EVAL_CHANNEL_TOP_K]
    # advisories(§4.6 C1): reviewed Insight를 별도 통로로. 게이트는 reviewed 재사용
    # (앵커 적용) — 질의 토큰을 가진 객체가 코퍼스에 있어야 곁들임이 뜬다. anchor_df는
    # 객체(Insight·raw 제외) df라, Insight만 있는 코퍼스(객체 0)는 anchor=None으로
    # 닫힌다(비현실적 경우 — 실코퍼스는 매핑·용어가 풍부). candidate Insight는 1차
    # 미노출(미룸 §7). 단정 답이 아니라 needs_clarification(results 기반)에는 안
    # 들어간다(raw_excerpts와 동일).
    advisories = [h for h in hits
                  if h.get("kind") == INSIGHT_KIND
                  and h.get("status") == "reviewed"
                  and _gate_pass(h["score"], signals, channel="reviewed")][:EVAL_CHANNEL_TOP_K]
    # projection_reuse(spec 2026-06-17 Task A5): ContextProjection을 별도 통로로 —
    # candidate·reviewed status 무관 한 채널로(results/candidates에는 위에서 제외).
    # 게이트는 raw 채널(바닥만, 앵커 미적용)로 통일한다. projection에 앵커를 걸면
    # 객체 코퍼스에 없는 어휘 드리프트 요구("경주"≠"레이스")가 막혀 재사용 레인의
    # 존재 이유(어휘 달라도 의미로 재사용 회수)가 깎인다. 라벨이 "미검증/검증됨"이라
    # 부정확 노출의 해는 낮다(raw 면제 논리와 동형). needs_clarification(results 기반)
    # 에는 안 들어간다(단정 답이 아니라 재사용 후보).
    projection_reuse = [h for h in hits
                        if h.get("kind") == PROJECTION_KIND
                        and _gate_pass(h["score"], signals, channel="raw")][:EVAL_CHANNEL_TOP_K]
    return {
        "results": results,
        "candidates": candidates,
        "raw_excerpts": raw_excerpts,
        "advisories": advisories,
        "projection_reuse": projection_reuse,
        "needs_clarification": not results,
    }
