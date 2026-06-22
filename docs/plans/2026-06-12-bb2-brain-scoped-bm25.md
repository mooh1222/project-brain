# Scoped BM25 (scope 내 점수 재계산) 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** scope가 단일 특정된 질의에서 BM25를 후보 집합 안에서만 재계산해, scope 밖 적재가 scope 안 검색 순위를 흔드는 회귀(골든셋 s1)를 근본 차단한다.

**Architecture:** project-brain 엔진의 `search_index.py`에 순수 BM25 계산 함수 + `search_bm25_scoped`를 신설하고, `search.py`의 `recall()`이 scope 확정 시 객체 레인 BM25 채널만 scoped로 교체한다. raw 레인·벡터 채널·게이트(anchor_df)·그래프 재정렬은 건드리지 않는다. cross-encoder 재랭커는 구현하지 않고 스펙에 정책만 명문화한다.

**Tech Stack:** Python(uv venv, unittest, 합성 코퍼스 + StubEmbedder), SQLite(documents 테이블 직접 조회 — FTS5 우회), 실측 검증은 게임 레포의 project-brain CLI(실모델 bge-m3 + mecab-ko).

---

## 배경 (zero-context 요약)

**2-레포 모델**: 엔진 코드는 `~/Downloads/codes/project-brain`(github mooh1222/project-brain, main 브랜치), 데이터(brain/ 코퍼스·골든셋·실측 가드)는 게임 레포 `~/Desktop/bb2_client`(브랜치 `docs/bb2-brain-object-model`). 엔진은 글로벌 도구로 편집 설치돼 있어(`uv tool install -e`) 코드를 고치면 `project-brain` 명령에 즉시 반영된다. 자세한 개발 루프는 엔진 레포 `CLAUDE.md`.

**무슨 일이 있었나 (2026-06-12)**: P2 5.5 적재 중 normal-honor(노멀명예) 기능을 적재하자 골든셋 s1(`s1-jira-4570-pinpoint`)이 깨졌다(6/7). s1 질의는 "샐리의 카누 …" LGBBTWO-4570 원문이라 scope 추론(`infer_scope`)이 sally-canoe로 정확히 좁혔는데도, **scope 안에서의 매핑 순위**가 바뀌어 정답 `mapping.sally-canoe.alert-popups-start-alert`가 top5 밖으로 밀렸다. 격리 실험으로 normal-honor가 원인임을 확정 — 잘못 넣은 게 아니라 "스테이지 클리어/개수/오픈 팝업" 어휘의 **정당한 중첩**이 단어 흔함도(df)를 바꾼 것이다.

**오염 경로 (코드로 확인됨)**:

1. FTS5 `bm25()` 점수는 **전체 색인 기준 df**로 계산된다 → scope 밖 적재가 scope 안 후보들끼리의 BM25 순위를 바꾼다.
2. scope 필터는 **융합 후**에 적용된다(`search.py:378`) → BM25 채널 top50 자리를 scope 밖 객체가 잠식한 뒤에 걸러진다.
3. 그래프 재정렬(`_rerank_by_support`)의 동점 깨기가 "원래 RRF 순위"(`search.py:227`)라서 BM25 흔들림이 동점 처리까지 전파된다.

벡터 채널은 문서별 독립 계산이라 원래 면역이다.

**설계 결정 (2026-06-12 세션 확정 — 3층 역할 분담)**:

| 층 | 결정 | 이유 |
|---|---|---|
| **(가) scoped BM25** | **지금 구현 (이 플랜)** | 오염 경로 1·2를 둘 다 원천 차단. 재료(`documents.tokenized_text`·`context_id`)가 이미 색인에 있음. 모델 없이 결정론, 후보 수백 행이라 지연 무시 가능 |
| **(다) cross-encoder 재랭커** | **구현 보류, 스펙에 정책 명문화 (Task 3)** | 정책 = scope 미특정 넓은 질의 전용(조건부). scope 특정 질의는 (가)가 df 면역을 결정론으로 보장하므로 중복. hwi_PKM이 "항상 ON"인 건 scoped 레인이 없는 구조라서. 지금은 효과를 측정할 scope-None 골든셋 시나리오가 없어 도입 불가(스펙 §8 실측 원칙) |
| **(나) 그래프 동점 보강** | **안 함 (스펙에 결정 기록)** | (가)가 동점 입력(RRF 순위)을 scope 질의에서 안정화. scope-None 동점은 (다) 도입 시 재랭커 점수가 1순위 키가 되며 자연 해소 |

**건드리지 않는 것**: 답변 게이트의 `anchor_df`(전역 df 조회)는 그대로 둔다 — 순위가 아니라 "이 엔티티가 코퍼스에 존재하나"를 보는 존재 신호라 전역이 본질(s5 거짓 양성 가드).

**검증 재료**: 게임 레포의 normal-honor 적재물은 **미커밋 상태로 남아 있다**(`brain/objects/**/`*normal-honor*` 26파일, 색인 +17행). 이게 살아있는 빨간 테스트다 — 지우지 말 것. (가) 구현 후 실모델 eval이 6/7 → 7/7로 돌아오는 게 최종 실측이고, 그다음에 커밋한다(Task 4).

---

### Task 1: `search_bm25_scoped` — 순수 BM25 계산 + DB 조회 함수 (엔진 레포)

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/search_index.py` (함수 2개 + 상수 2개 + `import math` 추가)
- Test: `~/Downloads/codes/project-brain/tests/test_search_index.py` (테스트 클래스 2개 추가)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_search_index.py` 상단 import를 수정한다:

```python
from project_brain.search_index import (
    SCHEMA_VERSION,
    StaleIndexError,
    _bm25_rank_scoped,
    rebuild,
    search_bm25,
    search_bm25_scoped,
    search_vector,
)
```

파일 끝에 테스트 클래스 2개를 추가한다:

```python
class ScopedBm25PureTest(unittest.TestCase):
    """_bm25_rank_scoped 순수 함수 — BM25 성질(tf·idf 단조성, 결정론)을 손꼽이 코퍼스로 검증."""

    def test_higher_tf_scores_higher(self):
        # 같은 토큰을 더 많이 가진 문서가 위 (길이 보정 후에도 tf 2 > tf 1).
        docs = [("d1", ["알림", "팝업"]), ("d2", ["클리어", "팝업", "팝업"])]
        ranked = dict(_bm25_rank_scoped(docs, {"팝업"}))
        self.assertGreater(ranked["d2"], ranked["d1"])

    def test_rarer_token_scores_higher(self):
        # 후보 집합 안에서 "클리어" df=1 < "알림" df=2 → 희소 토큰 매칭 문서가 위.
        docs = [
            ("d1", ["알림", "팝업"]),
            ("d2", ["클리어", "팝업"]),
            ("d3", ["알림", "안내"]),
        ]
        ranked = dict(_bm25_rank_scoped(docs, {"알림", "클리어"}))
        self.assertGreater(ranked["d2"], ranked["d1"])

    def test_unmatched_docs_excluded_and_tiebreak_by_object_id(self):
        # 질의 토큰 미포함 문서는 제외, 동점은 object_id 오름차순(§5 결정론).
        docs = [("d.b", ["팝업"]), ("d.a", ["팝업"]), ("d.x", ["무관"])]
        ranked = _bm25_rank_scoped(docs, {"팝업"})
        self.assertEqual([oid for oid, _ in ranked], ["d.a", "d.b"])

    def test_empty_docs_returns_empty(self):
        self.assertEqual(_bm25_rank_scoped([], {"팝업"}), [])


class ScopedBm25SearchTest(unittest.TestCase):
    """search_bm25_scoped — ★scope 밖 적재 면역 불변식★(s1 회귀 2026-06-12의 가드).

    FTS5 bm25()는 전역 df 기반이라 scope 밖 적재가 scope 안 순위를 흔든다(대조
    테스트가 그 현상을 박제). scoped 재계산은 같은 상황에서 결과(id·score)가
    완전 불변이어야 한다.
    """

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        # context.a: 질의 "알림 클리어" 기준 a 내부 df가 알림=2(d1·d3)·클리어=1(d2)
        # → scoped에선 희소한 "클리어"를 가진 d2가 d1보다 항상 위.
        self.base_objs = [
            glossary_term("g.d1", term="알림 팝업", context_id="context.a"),
            glossary_term("g.d2", term="클리어 팝업", context_id="context.a"),
            glossary_term("g.d3", term="알림 안내", context_id="context.a"),
        ]
        # scope 밖(context.b) 어휘 중첩 — 전역 df(클리어)를 1→5로 역전시킨다.
        self.noise_objs = [
            glossary_term(f"g.n{i}", term="클리어 보상", context_id="context.b")
            for i in range(4)
        ]

    def tearDown(self):
        self._td.cleanup()

    def _rebuild(self, objs):
        # brain root에 객체를 누적 저장 후 전체 재색인(FTS만 — scoped는 임베더 불필요).
        build_store_dir(self.brain, objs)
        rebuild(self.brain, self.db)

    def test_scoped_results_immune_to_out_of_scope_ingest(self):
        # ★핵심 불변식★: context.b 적재 전후 scoped 결과(id·score)가 완전 동일.
        self._rebuild(self.base_objs)
        before = search_bm25_scoped(self.db, "알림 클리어", scope="context.a")["results"]
        self.assertTrue(before)
        self._rebuild(self.noise_objs)
        after = search_bm25_scoped(self.db, "알림 클리어", scope="context.a")["results"]
        self.assertEqual(before, after)

    def test_global_fts_bm25_shifts_with_out_of_scope_ingest(self):
        # 대조 박제: 같은 합성에서 기존 전역 search_bm25는 a 내부 순위가 뒤집힌다
        # (초기 전역 df: 클리어1 < 알림2 → d2 우위 / b 추가 후: 클리어5 > 알림2 →
        #  d1 우위). 이 현상이 s1 회귀의 원인이고 scoped 레인의 존재 이유다.
        def a_rank(results):
            return [r["object_id"] for r in results
                    if r["object_id"] in ("g.d1", "g.d2")]

        self._rebuild(self.base_objs)
        before = a_rank(search_bm25(self.db, "알림 클리어")["results"])
        self._rebuild(self.noise_objs)
        after = a_rank(search_bm25(self.db, "알림 클리어")["results"])
        self.assertEqual(before, ["g.d2", "g.d1"])
        self.assertEqual(after, ["g.d1", "g.d2"])

    def test_scope_excludes_other_context_and_raw(self):
        # scope 행만 후보 — 다른 컨텍스트·raw 청크는 결과에도 df에도 안 들어간다.
        build_store_dir(self.brain, self.base_objs + [
            glossary_term("g.out", term="알림 팝업", context_id="context.b"),
        ])
        src = self.brain / "raw" / "sources" / "a"
        src.mkdir(parents=True)
        (src / "spec.md").write_text("# 개요\n알림 팝업 클리어 서술.", encoding="utf-8")
        rebuild(self.brain, self.db)
        results = search_bm25_scoped(self.db, "알림 팝업", scope="context.a")["results"]
        ids = {r["object_id"] for r in results}
        self.assertIn("g.d1", ids)
        self.assertNotIn("g.out", ids)
        self.assertTrue(all(r["kind"] != "raw_chunk" for r in results))

    def test_deterministic(self):
        self._rebuild(self.base_objs)
        a = search_bm25_scoped(self.db, "알림 클리어 팝업", scope="context.a")
        b = search_bm25_scoped(self.db, "알림 클리어 팝업", scope="context.a")
        self.assertEqual(a, b)

    def test_no_tokens_returns_empty(self):
        self._rebuild(self.base_objs)
        self.assertEqual(
            search_bm25_scoped(self.db, "", scope="context.a")["results"], [])
```

- [ ] **Step 2: red 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_search_index.py -q`
Expected: **ImportError** (`_bm25_rank_scoped`/`search_bm25_scoped` 없음) — 수집 단계 에러로 전체 red.

- [ ] **Step 3: 구현**

`src/project_brain/search_index.py` 상단 import에 `math`를 추가한다 (`import hashlib` 옆):

```python
import hashlib
import math
import sqlite3
```

`search_bm25` 함수 정의 **앞**에 다음을 추가한다:

```python
# BM25 표준 계수(scoped 재계산 — Okapi 표준값. FTS5 bm25() 기본값과 동일 계열).
_BM25_K1 = 1.2
_BM25_B = 0.75


def _bm25_rank_scoped(doc_token_lists, query_tokens):
    """후보 집합 안에서만 df·avgdl을 계산하는 표준 BM25 — 순수 함수(단위 테스트용).

    doc_token_lists: [(object_id, [token, ...]), ...] — 후보 전체(매칭 여부 무관).
    query_tokens: 질의 토큰 집합(중복 제거).
    반환: 질의 토큰을 1개 이상 포함한 문서만 [(object_id, score)] —
          점수 내림차순 → 동점 object_id 오름차순(§5 결정론), 점수 6자리 반올림.

    IDF는 ln(1 + (N - df + 0.5)/(df + 0.5)) — 항상 양수인 Lucene 형태. FTS5
    bm25()(Okapi 원형, df > N/2면 음수)와 식이 달라도 무방하다: recall은 채널
    결과의 ★순서만★ 소비한다(RRF가 rank만 씀).
    """
    n_docs = len(doc_token_lists)
    if n_docs == 0:
        return []
    avgdl = sum(len(toks) for _, toks in doc_token_lists) / n_docs
    df = {t: 0 for t in query_tokens}
    for _, toks in doc_token_lists:
        tok_set = set(toks)
        for t in query_tokens:
            if t in tok_set:
                df[t] += 1
    scored = []
    for object_id, toks in doc_token_lists:
        tf: dict[str, int] = {}
        for tok in toks:
            if tok in query_tokens:
                tf[tok] = tf.get(tok, 0) + 1
        if not tf:
            continue
        dl = len(toks)
        score = 0.0
        for t, freq in tf.items():
            idf = math.log(1.0 + (n_docs - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * (freq * (_BM25_K1 + 1.0)) / (
                freq + _BM25_K1 * (1.0 - _BM25_B + _BM25_B * dl / avgdl))
        scored.append((object_id, round(score, 6)))
    scored.sort(key=lambda pair: (-pair[1], pair[0]))
    return scored


def search_bm25_scoped(db_path, query: str, scope: str, top_n: int = 50) -> dict:
    """scope 후보(context_id=scope, raw 제외) 안에서만 BM25를 재계산한다(§3.2 scoped 레인).

    s1 회귀(2026-06-12)의 근본 해법: FTS5 bm25()는 전역 df 기반이라 scope 밖
    적재가 scope 안 순위를 흔든다. 후보 집합의 tokenized_text로 df·avgdl을 그
    안에서만 계산하면 scope 밖에 무엇이 적재되든 결과가 수학적으로 불변이다
    (불변식 테스트가 가드). 후보는 컨텍스트당 수백 행 — 파이썬 직접 계산으로
    충분하고 FTS5 색인 구조는 읽지도 않는다(documents 테이블만 조회).

    반환 형태는 search_bm25와 대칭({results, warnings}). ★점수 방향이 다르다★ —
    여기는 클수록 좋음(표준 BM25), search_bm25는 FTS5 그대로(작을수록 좋음).
    recall은 채널 결과의 순서만 소비하므로(RRF가 rank만 씀) 영향 없다.
    """
    db_path = Path(db_path)
    tokens = tokenize(query)
    warnings: list[str] = []

    conn = sqlite3.connect(str(db_path))
    try:
        meta_row = _read_meta(conn)
        _guard_schema_version(meta_row)
        indexed_tokenizer = meta_row["tokenizer"] if meta_row else None
        query_tokenizer = active_backend()
        if indexed_tokenizer is not None and indexed_tokenizer != query_tokenizer:
            warnings.append(
                f"tokenizer 비대칭: 색인={indexed_tokenizer} 쿼리={query_tokenizer} "
                "— 색인과 쿼리 토크나이저가 달라 형태소 매칭 품질이 떨어질 수 있음(§6)"
            )
        if not tokens:
            return {"results": [], "warnings": warnings}
        rows = conn.execute(
            "SELECT object_id, kind, status, context_id, tokenized_text, surface_text "
            "FROM documents WHERE context_id = ? AND kind != ? ORDER BY object_id",
            (scope, RAW_KIND),
        ).fetchall()
    finally:
        conn.close()

    doc_token_lists = [(r[0], (r[4] or "").split()) for r in rows]
    ranked = _bm25_rank_scoped(doc_token_lists, set(tokens))

    meta_by_id = {r[0]: r for r in rows}
    results = []
    for object_id, score in ranked[:top_n]:
        r = meta_by_id[object_id]
        results.append({
            "object_id": object_id, "kind": r[1], "status": r[2],
            "context_id": r[3], "score": score, "surface_text": r[5],
        })
    return {"results": results, "warnings": warnings}
```

- [ ] **Step 4: green 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_search_index.py -q`
Expected: PASS (기존 + 신규 전부).

대조 테스트 `test_global_fts_bm25_shifts_with_out_of_scope_ingest`가 기대와 다르게 나오면(FTS5의 음수 idf 처리 차이 등): 노이즈 문서를 `range(8)`로 늘려 df 역전 폭을 키운다. 그래도 안 뒤집히면 FTS5 실동작을 출력해 기대값을 실측으로 교정한다(이 테스트는 현상 박제용 — scoped 불변식 테스트가 본체).

- [ ] **Step 5: 엔진 전체 테스트 + 커밋**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/ -q`
Expected: 전체 PASS (기준점: 직전 336개 + 신규 10개).

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/search_index.py tests/test_search_index.py
git commit -m "feat(search): scope 내 BM25 재계산(search_bm25_scoped) — scope 밖 적재 면역

s1 회귀(2026-06-12, normal-honor 적재의 정당한 어휘 중첩이 전역 df를
흔들어 sally-canoe 핀포인트가 top5 밖으로) 근본 해법 1/2.
후보 집합(context_id=scope, raw 제외)의 tokenized_text로 df·avgdl을
그 안에서만 계산 — 불변식 테스트(scope 밖 적재 전후 결과 동일)가 가드.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `recall()` 분기 배선 — scope 확정 시 객체 레인만 scoped (엔진 레포)

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/search.py` (import 1줄 + recall 내 분기 + docstring 1줄)
- Test: `~/Downloads/codes/project-brain/tests/test_search.py` (테스트 클래스 1개 추가)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_search.py` 상단 import를 수정한다:

```python
from project_brain.search_index import rebuild, search_bm25_scoped
```

파일 끝(`scoped_context` 헬퍼는 이미 280줄 부근에 존재 — 재정의 금지)에 추가한다:

```python
class ScopedBm25WiringTest(unittest.TestCase):
    """recall — scope가 정해지면 객체 레인 BM25가 scoped 재계산으로 바뀐다(§3.2).

    s1 회귀(2026-06-12)의 recall 차원 가드: 벡터 채널은 문서별 독립이라 원래
    면역 — BM25 채널이 scoped로 바뀌면 객체 레인 전체가 scope 밖 적재에 면역.
    """

    def _base_objs(self):
        return [
            scoped_context("context.a", display_name="카누 레이스",
                           title="카누 레이스 도메인", context_key="canoe-race"),
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
            recall("카누 레이스 알림 클리어", db_path=db, embedder=embedder,
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
        query = "카누 레이스 알림 클리어"
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
```

- [ ] **Step 2: red 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_search.py -q`
Expected: 배선 테스트 2개는 **AttributeError**(`project_brain.search`에 `search_bm25_scoped` 없음)로 ERROR. 행동 불변식 테스트는 FAIL이 기대(전역 df 역전으로 순서 변동) — 만약 우연히 PASS면 노이즈를 `range(8)`로 늘려 red를 확인한 뒤 진행한다(red 없는 테스트는 가드 가치 검증이 안 된 것).

- [ ] **Step 3: 구현**

`src/project_brain/search.py`의 import를 수정한다:

```python
from project_brain.search_index import (
    search_bm25,
    search_bm25_scoped,
    search_vector,
)
```

`recall()` 내부(현재 `search.py:350-356` 부근)를 다음으로 바꾼다:

```python
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
        bm25 = [r for r in bm25_all if r.get("kind") != RAW_KIND][:CHANNEL_TOP_N]
    vector = [r for r in vector_all if r.get("kind") != RAW_KIND][:CHANNEL_TOP_N]
    raw_bm25 = [r for r in bm25_all if r.get("kind") == RAW_KIND][:CHANNEL_TOP_N]
    raw_vector = [r for r in vector_all if r.get("kind") == RAW_KIND][:CHANNEL_TOP_N]
```

`recall()` docstring의 scope 항목(현재 `search.py:315-318`)에 한 문장을 덧붙인다:

```
    scope: 주면 벡터 채널은 over-fetch 후 context_id로 거르고(search_vector 구현),
           융합 결과도 context_id로 한 번 더 거른다(BM25 채널 적중 포함) — top30
           절단 전에 거르므로 scope 밖 적중이 자리를 차지하지 않는다.
           ★scope가 확정되면 객체 레인 BM25는 search_bm25_scoped(후보 집합 내
           df 재계산)로 바뀐다 — scope 밖 적재 면역(§3.2 scoped 레인, 2026-06-12).★
           ★None이면 질의 표면에서 자동 추론한다(infer_scope, P2 3번) — 질의가
           기능명을 단일 특정하면 그 컨텍스트로 하드 필터, 아니면 전체 검색.★
```

- [ ] **Step 4: green + 전체 테스트**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/ -q`
Expected: 전체 PASS. 기존 테스트 중 scope를 쓰는 것들(`test_scope_filters_bm25_channel_too`, `test_recall_auto_scope_filters_other_context`, `test_recall_explicit_scope_wins_over_inference`)이 scoped 경로로 바뀌어도 통과해야 한다 — 이들은 "scope 밖 객체 제외"를 보는 테스트라 scoped 결과에서도 성립. 깨지면 scoped 결과의 dict 키 누락(`surface_text` 등)을 의심할 것.

- [ ] **Step 5: 커밋**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/search.py tests/test_search.py
git commit -m "feat(search): recall scope 확정 시 객체 레인 BM25를 scoped로 교체

scope 추론/명시 시 search_bm25_scoped 사용 — 벡터 채널(원래 면역)과
합쳐 객체 레인 전체가 scope 밖 적재에 면역. raw 레인·게이트·그래프
재정렬은 불변. s1 회귀 근본 해법 2/2.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 스펙 갱신 — scoped 레인 반영 + (다) 재랭커 정책 명문화 + (나) 안 함 기록 (게임 레포)

**Files:**
- Modify: `~/Desktop/bb2_client/docs/superpowers/specs/2026-06-10-bb2-brain-search-layer-design.md`

- [ ] **Step 1: §3 파이프라인 2번 항목에 scoped 분기 추가**

현재 줄(57행 부근):

```
2. **BM25**: SQLite FTS5. 한국어는 **사전 형태소 분리 후 공백 결합 텍스트를 색인**(pre-tokenized column + unicode61) — 색인과 쿼리가 같은 토크나이저를 쓰면 FTS5 커스텀 토크나이저 없이 동작. top 50.
```

뒤에 다음 문장을 덧붙인다(같은 줄에 이어서):

```
 ★scope가 단일 특정되면(infer_scope 또는 명시) 객체 레인은 FTS5 전역 점수 대신 **scoped BM25**(후보 집합 context_id=scope·raw 제외 안에서 df·avgdl 재계산, `search_bm25_scoped`)로 바뀐다 — 전역 df 오염 면역(2026-06-12 s1 회귀 해법. raw 레인은 전역 유지).★
```

- [ ] **Step 2: §9 비범위의 재랭커 항목을 정책 확정형으로 교체**

현재(131행):

```
- 재랭커(P1 — §8 측정 후), ~~raw 본문 색인 적용~~(✅ 2026-06-11 §2.2 적용 완료), 그래프 멀티홉/그래프 DB, `IndexRecord` kind 활용(이 색인은 brain 객체로 저장하지 않음 — kind 자체의 존폐는 후속 재검토), 적재 자동화, 개인 메모리 층, vault 검색과의 통합.
```

다음으로 교체:

```
- 재랭커(P1 — ★정책 확정 2026-06-12★: **scope 미특정 넓은 질의 전용(조건부)**. scope 특정 질의는 scoped BM25(§3.2)가 df 면역을 결정론으로 보장하므로 재랭커를 겹쳐 돌리지 않는다 — hwi_PKM의 "항상 ON"은 scoped 레인이 없는 구조의 선택. 위치는 RRF top30 뒤(재랭커 점수 1순위 + graph_support 동점 키 — 결합 계수는 도입 시 캘리브레이션). **선행 조건: 골든셋에 scope-None 넓은 질의 시나리오(s8) 추가** — 측정 수단 없는 도입 금지(§8 원칙). 트리거: s8 FAIL 또는 scope-None 질의 품질 저하 실측. 리스크: bge-reranker-v2-m3 2.1GB + Metal 4GB 제약(embedder 배치 사망 실측 2026-06-11 전례) — 도입 시 메모리·지연 실측 필수), ~~raw 본문 색인 적용~~(✅ 2026-06-11 §2.2 적용 완료), 그래프 멀티홉/그래프 DB, `IndexRecord` kind 활용(이 색인은 brain 객체로 저장하지 않음 — kind 자체의 존폐는 후속 재검토), 적재 자동화, 개인 메모리 층, vault 검색과의 통합.
```

- [ ] **Step 3: §11 "코퍼스 성장 재방문 트리거" 항목에 1차 재방문 결과 기록**

현재(148행):

```
- **코퍼스 성장 재방문 트리거(리뷰 반영)**: top50/30/5 상수는 571객체(색인 302) 기준 — 2차(5.5 전부 적재)로 코퍼스가 커지면 고정 top-K의 회수율이 떨어지고 무가중 RRF의 한계가 드러남. **2차 적재 시작 시 top-K 상수·재랭커 필요성을 재평가**한다(설계 부채로 명시).
```

뒤에 이어 붙인다(같은 줄에):

```
 → ★1차 재방문 완료(2026-06-12)★: s1 핀포인트 회귀(normal-honor 적재의 정당한 어휘 중첩 — 두 번째 회귀 신호)로 트리거 도달 → **scoped BM25 도입으로 해소**(§3.2). 그래프 동점 처리 보강 후보는 **안 함** 결정 — scoped BM25가 동점 입력(RRF 순위)을 scope 질의에서 안정화하고, scope-None 동점은 재랭커 도입 시 재랭커 점수가 1순위 키가 되며 자연 해소. top-K 상수는 유지(7/7 복구 시 추가 변경 불요). 재랭커는 §9 확정 정책(조건부+s8 선행)대로 보류.
```

- [ ] **Step 4: 커밋은 Task 4에서 일괄** (스펙 갱신 단독 커밋 불요 — normal-honor·가드와 한 묶음이 검증 후 상태를 반영)

---

### Task 4: 실코퍼스 검증 (s1 red→green) + normal-honor 커밋 + 엔진 push

**Files:**
- Modify: `~/Desktop/bb2_client/brain/checks/test_real_corpus.py` (객체 행 수 가드 +17 갱신)
- Commit: 게임 레포 normal-honor 26파일 + 스펙 + 가드 + 플랜 문서

- [ ] **Step 1: red 기준 확인 (구현 반영 전 상태 기억)**

normal-honor 적재물(미커밋)이 그대로 있는지 확인:

```bash
cd ~/Desktop/bb2_client && git status --short | grep -c normal-honor
```

Expected: 26 (없으면 STOP — 빨간 테스트 재료가 사라진 것. 이전 세션 기록과 대조 필요).

- [ ] **Step 2: 실모델 재색인 + 골든셋 평가**

엔진은 편집 설치라 Task 1·2 코드가 `project-brain` 명령에 이미 반영돼 있다.

```bash
cd ~/Desktop/bb2_client
project-brain index rebuild     # 실모델(bge-m3+mecab-ko), 수십 초
project-brain eval              # 골든셋 7종
```

Expected: **7/7 PASS** — 특히 `s1-jira-4570-pinpoint`가 6/7의 FAIL에서 PASS로 (scoped BM25가 sally-canoe 후보 안 df로 재계산 → normal-honor 어휘 중첩 무효화).

7/7이 안 되면: `project-brain search "<s1 query>"` 류 CLI로 s1 정답 매핑의 실제 순위·graph_support를 진단한다. scoped로도 BM25 채널 순위가 부족하면 그래프 재정렬 단계(동점 캡) 문제 — 이때는 플랜 범위를 벗어나므로 진단 결과를 기록하고 사용자와 다음 분기((다) 조기 투입 포함)를 상의한다.

- [ ] **Step 3: 실측 가드 갱신 + 통과**

`brain/checks/test_real_corpus.py`의 객체 행 수 가드에 normal-honor를 반영한다. 주석 누적식 끝에 한 줄 추가 + 기대값 +17:

```
#             + 17(normal-honor 2026-06-12 — P2 5.5 적재 12번째.
#                  파일 26 중 EvidenceRef 9는 색인 제외)
```

기대 숫자는 Step 2의 rebuild 출력(`indexed`·객체 행 수)과 일치시킨다.

```bash
cd ~/Desktop/bb2_client && pytest brain/checks/ -q
```

Expected: 전부 PASS.

- [ ] **Step 4: 게임 레포 커밋**

```bash
cd ~/Desktop/bb2_client
git add brain/objects brain/checks/test_real_corpus.py \
  docs/superpowers/specs/2026-06-10-bb2-brain-search-layer-design.md \
  docs/superpowers/plans/2026-06-12-bb2-brain-scoped-bm25.md
git commit -m "feat(brain): P2 5.5 적재 12/14 — 노멀명예(normal-honor) 26객체 + scoped BM25 검증 7/7

normal-honor가 s1 핀포인트 회귀(정당한 어휘 중첩 df 오염)를 일으켜
엔진에 scoped BM25(scope 내 df 재계산) 도입 후 7/7 복구 확인.
스펙: §3.2 scoped 레인 + §9 재랭커 조건부 정책 확정 + §11 1차 재방문 기록.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

(이 브랜치 `docs/bb2-brain-object-model`은 검증 후 자동 커밋 허용 — memory `feedback_brain_branch_auto_commit`.)

- [ ] **Step 5: 엔진 push**

```bash
cd ~/Downloads/codes/project-brain && git push
```

주의: 게임 레포의 git 보호 훅이 명령 문자열의 "main" 패턴을 검사하므로 **인자 없는 `git push`**(upstream 추적)를 쓴다(2026-06-11 실측 우회).

- [ ] **Step 6: 남은 적재 재개 안내**

이 플랜 완료 후 P2 5.5 적재 잔여 2기능(ad-skip, frame-package)을 기존 절차(핸드오프 `.claude/handoffs/2026-06-12-p2-55-ingest/README.md`)로 재개한다 — 적재마다 `project-brain eval` 7/7 확인이 이제 다시 유효한 회귀 신호다.

---

## (다) cross-encoder 재랭커 — 다음 작업 트리거 (이 플랜에서 구현하지 않음)

다음 신호 중 하나가 오면 별도 플랜으로 착수한다:

1. **scope-None 넓은 질의의 품질 저하 실측** — 회상 실사용에서 기능명 없는 질의("이어하기 관련 결제 분기 어디?")의 top5가 체감 무관해질 때.
2. **골든셋 s8 추가 후 FAIL** — 착수 시 첫 단계가 s8(scope-None 넓은 질의 시나리오) 작성이다. red 시나리오 없이 재랭커를 넣지 않는다(§8 실측 원칙).

착수 시 전제(스펙 §9에 명문화됨): 조건부 정책(scope-None만), 위치 RRF top30 뒤, bge-reranker-v2-m3 2.1GB + Metal 4GB 메모리 실측 필수.

## Self-Review 결과

- 스펙 커버리지: 설계 결정 3건((가) 구현 / (다) 명문화 / (나) 안 함 기록)이 Task 1·2 / Task 3 / Task 3에 대응. 검증(s1 red→green)은 Task 4.
- 타입 일관성: `search_bm25_scoped(db_path, query, scope, top_n)` 시그니처가 Task 1 구현·Task 2 배선·테스트에서 동일. 반환 dict 키(`object_id, kind, status, context_id, score, surface_text`)는 `search_bm25`와 대칭 — recall의 `meta.setdefault` 소비와 호환.
- 플레이스홀더 없음: 전 코드 블록 실코드.
