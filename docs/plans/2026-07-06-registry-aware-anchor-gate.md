# 명부 인식 앵커 게이트 (Registry-Aware Anchor Gate) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 앵커 게이트가 질의의 엔티티 존재를 "코퍼스 토큰 빈도(anchor_df)" 하나가 아니라 "엔티티 명부(GlossaryTerm term+synonyms+aliases) 표면형이 질의에 통째로 등장하는가(D1)"와 **OR로 함께** 판정하게 해서, 잘 적재된 엔티티 질의(럭키박스류)의 거짓음성 0건 문제를 없애되 미적재 엔티티(크리스마스류) 거짓양성 가드는 유지한다.

**Architecture:** `compute_query_signals`가 store를 받아 새 신호 `registry_match`(명부 표면형 중 길이 3자+가 질의 소문자에 부분문자열로 등장하면 True)를 계산한다. 순수 함수 `_gate_pass`는 앵커 차단 앞에 `registry_match` 단락(short-circuit)을 넣어 `registry_match OR anchor_df≤30`의 **단조 완화**(기존 통과 질의 회귀 0)를 만든다. `eval_recall`은 store를 1회 로드해 recall과 compute_query_signals 양쪽에 넘긴다(배관 1단계). 규칙은 lint(schema.py)로 강제하고 적재 스킬·문서로 안내한다.

**Tech Stack:** Python 3.11, sqlite3(FTS5), unittest, StubEmbedder(결정론 테스트), uv venv(`.venv/bin/python`).

## Global Constraints

- 테스트에 실모델 금지 — `StubEmbedder` 또는 `PROJECT_BRAIN_EMBEDDER=stub`. (프로젝트 CLAUDE.md)
- 결정론 유지 — 토큰화는 정규식 폴백 강제 패턴 사용(기존 test_search.py 방식 그대로).
- `_gate_pass`는 순수 함수를 유지한다 — store/DB 접근 금지, 신호는 전부 `signals` dict로 받는다.
- 단조 완화 불변식: 기존에 통과하던 질의(`anchor_df≤_ANCHOR_DF_MAX` & score≥floor)는 변경 후에도 전부 통과해야 한다(회귀 0). 새로 열리는 건 registry_match 경로뿐이다.
- 명부 표면형 매칭은 **대소문자 무시 + 표면형 strip 후 길이 3자 이상**만. 이 길이 문턱(`_REGISTRY_MIN_SURFACE_LEN`)과 lint 최소 길이(`_SYNONYM_MIN_LEN`)는 값이 3으로 일치해야 한다.
- raw 채널은 앵커·명부 미적용(기존 설계 고정) — 이번 변경은 reviewed/candidate 채널만 건드린다.
- 편집은 항상 `src/project_brain/templates/` 원본에서(단일 원본), 배포본 직접 수정 금지.
- 실코퍼스(bb2) 회귀는 이 플랜 밖(동반 플랜 `2026-07-06-bb2-anchor-golden-set-backfill.md`). 이 플랜은 합성 테스트로 자체 완결한다.

**선행 조건:** 동반 bb2 플랜의 "골든셋 보강"이 먼저 머지돼 실코퍼스 안전망이 있어야 이 엔진 변경을 실데이터에 신뢰 투입할 수 있다. 단 이 엔진 플랜의 합성 TDD는 bb2 없이 독립 진행 가능하다.

---

## File Structure

- `src/project_brain/search.py` — `compute_query_signals`에 store 인자+`registry_match` 신호 추가, `_registry_surfaces` 헬퍼 신설, `_gate_pass`에 registry 단락 추가, `eval_recall` store 배관. 상수 `_REGISTRY_MIN_SURFACE_LEN` 추가.
- `src/project_brain/schema.py` — GlossaryTerm 검증 블록에 synonyms/aliases 값 규칙(최소 길이·단독 일반명사 금지) 추가. 상수 `_SYNONYM_MIN_LEN`·`_SYNONYM_GENERIC_BLOCKLIST` 추가.
- `tests/test_search.py` — 테스트 헬퍼 `glossary_term`에 `synonyms`/`aliases` kwarg 추가, `_gate_pass`/`compute_query_signals`/`eval_recall` 신규 테스트.
- `tests/test_schema.py`(또는 lint 테스트 위치) — synonyms/aliases lint 규칙 테스트.
- `src/project_brain/templates/ingest/SKILL.md` — "용어 동의어" 섹션을 "게이트 통과권"으로 승격 + 백필 규칙 + 최소 3글자·근거 갱신.
- `src/project_brain/templates/ingest/references/worked-example.md`·`references/object-model.md` — synonyms/aliases 게이트 역할 문서화.
- `docs/search-internals.md` — 게이트 설명을 "명부 D1 OR anchor_df≤30"으로 갱신.

---

## Task 1: `_gate_pass` registry_match OR-보강 (순수 함수)

**Files:**
- Modify: `src/project_brain/search.py:650-679` (`_gate_pass`)
- Test: `tests/test_search.py` (`GatePureFunctionTest`, 735줄 근방)

**Interfaces:**
- Consumes: `signals` dict — 기존 키 `top_score/margin/anchor_df` + 신규 `registry_match: bool`.
- Produces: `_gate_pass(score: float, signals: dict, *, channel: str) -> bool` (시그니처 불변, 동작만 확장).

- [ ] **Step 1: 실패 테스트 작성** — `GatePureFunctionTest`의 `_signals` 헬퍼에 registry_match 기본값 추가 + 새 테스트 3개

`tests/test_search.py`의 `GatePureFunctionTest._signals`를 교체(기본 False 추가):

```python
    def _signals(self, *, top_score=0.02, second=0.01, anchor_df=5, registry_match=False):
        # margin은 _gate_pass boolean에 안 들어가지만 신호 dict 형태를 맞춰 둔다.
        return {"top_score": top_score, "margin": round(top_score - second, 6),
                "anchor_df": anchor_df, "registry_match": registry_match}
```

같은 클래스에 테스트 추가:

```python
    def test_registry_match_opens_despite_high_anchor_df(self):
        # ★확정설계 핵심(OR 보강)★: anchor_df가 상한을 넘어 원래 차단될 신호라도
        # registry_match=True면 열린다. 단조 완화 — 새로 열리는 유일한 경로.
        sig = self._signals(top_score=0.02, anchor_df=52, registry_match=True)
        self.assertTrue(_gate_pass(0.02, sig, channel="reviewed"))
        self.assertTrue(_gate_pass(0.02, sig, channel="candidate"))

    def test_registry_match_still_requires_floor(self):
        # registry_match=True라도 절대 점수 바닥 미만이면 차단(보강은 앵커만 우회, 바닥은 유지).
        sig = self._signals(top_score=0.0001, second=0.0, anchor_df=52, registry_match=True)
        self.assertFalse(_gate_pass(0.0001, sig, channel="reviewed"))

    def test_no_registry_match_preserves_s5_block(self):
        # ★s5 가드 보존★: registry_match=False + anchor_df>상한 → 여전히 차단.
        sig = self._signals(top_score=0.0275, anchor_df=52, registry_match=False)
        self.assertFalse(_gate_pass(0.0275, sig, channel="reviewed"))
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_search.py::GatePureFunctionTest -q`
Expected: `test_registry_match_opens_despite_high_anchor_df` FAIL (현재 anchor_df 52라 차단됨).

- [ ] **Step 3: 최소 구현** — `_gate_pass`에 registry 단락 추가

`src/project_brain/search.py`의 `_gate_pass` 본문에서 raw 단락 뒤, 앵커 블록 앞에 삽입:

```python
    if channel == "raw":
        return True
    if signals.get("registry_match"):
        return True
    anchor_df = signals.get("anchor_df")
    if anchor_df is None or anchor_df > _ANCHOR_DF_MAX:
        return False
    return True
```

docstring 규칙 2번(표면 앵커) 설명에 한 줄 보강:

```python
    2. (iii) 표면 앵커 — ★명부 매칭(registry_match)이 없을 때만★ anchor_df가
       None이거나 _ANCHOR_DF_MAX를 넘으면 차단한다. 질의가 아는 엔티티 표면형을
       통째로 포함하면(registry_match) anchor_df와 무관하게 연다(OR 보강, 단조 완화).
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_search.py::GatePureFunctionTest -q`
Expected: PASS (기존 테스트 전부 + 신규 3개). 특히 `test_blocks_when_anchor_absent`(registry 없음)도 그대로 PASS = s5 회귀 없음.

- [ ] **Step 5: 커밋**

```bash
git add tests/test_search.py src/project_brain/search.py
git commit -m "feat(search): _gate_pass에 registry_match OR-보강 (앵커 단조 완화)"
```

---

## Task 2: `compute_query_signals` registry_match 신호 + `_registry_surfaces`

**Files:**
- Modify: `src/project_brain/search.py:619-647` (`compute_query_signals`), 상수 구역(파일 상단 `_ANCHOR_DF_MAX` 근방)
- Test: `tests/test_search.py` (`ComputeQuerySignalsTest`, 806줄 근방) + 헬퍼 `glossary_term`(44줄)

**Interfaces:**
- Consumes: `store`(BrainStore 또는 `by_kind(kind)->list[dict]`를 가진 객체), `_REGISTRY_MIN_SURFACE_LEN=3`.
- Produces: `compute_query_signals(query, hits, db_path, store=None) -> dict` — 반환 dict에 `registry_match: bool` 추가. `_registry_surfaces(store) -> set[str]`.

- [ ] **Step 1: 실패 테스트 작성**

먼저 `tests/test_search.py:44`의 `glossary_term` 헬퍼에 kwarg 추가(교체):

```python
def glossary_term(tid, *, term, definition="정의", status="reviewed",
                  context_id="context.neutral", synonyms=None, aliases=None):
    obj = {
        "id": tid, "kind": "GlossaryTerm", "status": status, "truth_role": "domain",
        "title": f"Term: {term}", "context_id": context_id,
        "term": term, "definition": definition,
        "evidence_refs": ["ev.x"] if status == "reviewed" else [],
    }
    if synonyms is not None:
        obj["synonyms"] = synonyms
    if aliases is not None:
        obj["aliases"] = aliases
    if status == "candidate":
        obj["candidate"] = {"candidate_state": "ready_for_review", "candidate_source": "spec"}
    return _b(obj)
```

`ComputeQuerySignalsTest`에 테스트 추가(가벼운 fake store로 명부 로직만 격리 — db_path는 setUp의 stub 색인 재사용):

```python
    def test_registry_match_true_when_surface_in_query(self):
        # 명부 표면형('럭키박스', 3자+)이 질의에 통째 등장 → registry_match True.
        class _FakeStore:
            def by_kind(self, kind):
                return ([{"term": "PopupLuckyBoxInfo", "synonyms": ["럭키박스"], "aliases": []}]
                        if kind == "GlossaryTerm" else [])
        sig = compute_query_signals("럭키박스 API 쓰나", [], self.db, store=_FakeStore())
        self.assertTrue(sig["registry_match"])

    def test_registry_match_false_when_no_surface(self):
        # 질의에 명부 표면형이 없으면 False (미적재 엔티티 질의).
        class _FakeStore:
            def by_kind(self, kind):
                return ([{"term": "PopupLuckyBoxInfo", "synonyms": ["럭키박스"], "aliases": []}]
                        if kind == "GlossaryTerm" else [])
        sig = compute_query_signals("크리스마스 이벤트 보상", [], self.db, store=_FakeStore())
        self.assertFalse(sig["registry_match"])

    def test_registry_ignores_short_surfaces(self):
        # 길이 2자 이하 표면형('NL')은 명부에서 제외 → 오매칭 방지.
        class _FakeStore:
            def by_kind(self, kind):
                return ([{"term": "NL", "synonyms": [], "aliases": []}]
                        if kind == "GlossaryTerm" else [])
        sig = compute_query_signals("NL 값 알려줘", [], self.db, store=_FakeStore())
        self.assertFalse(sig["registry_match"])

    def test_registry_match_absent_when_no_store(self):
        # store 미주입(구 호출자 호환) → registry_match False, 기존 anchor 경로만.
        sig = compute_query_signals("레이스", [], self.db)
        self.assertFalse(sig["registry_match"])
        self.assertIn("registry_match", sig)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_search.py::ComputeQuerySignalsTest -q`
Expected: 신규 4개 FAIL (`KeyError: 'registry_match'` 또는 TypeError: unexpected kwarg 'store').

- [ ] **Step 3: 최소 구현**

`src/project_brain/search.py` 상수 구역(`_ANCHOR_DF_MAX = 30` 근방)에 추가:

```python
_REGISTRY_MIN_SURFACE_LEN = 3  # 명부 표면형 매칭 최소 길이(2자 이하 오매칭 방지). schema._SYNONYM_MIN_LEN과 일치해야 함.
```

`_registry_surfaces` 헬퍼를 `compute_query_signals` 위에 신설:

```python
def _registry_surfaces(store) -> set[str]:
    """게이트 명부 표면형 집합 — GlossaryTerm term+synonyms+aliases 중 strip 후
    길이 _REGISTRY_MIN_SURFACE_LEN 이상만, 소문자화. 질의와 D1(부분문자열) 대조용."""
    surfaces: set[str] = set()
    for term in store.by_kind("GlossaryTerm"):
        for v in (term.get("term"), *(term.get("synonyms") or []), *(term.get("aliases") or [])):
            if isinstance(v, str):
                s = v.strip().lower()
                if len(s) >= _REGISTRY_MIN_SURFACE_LEN:
                    surfaces.add(s)
    return surfaces
```

`compute_query_signals` 시그니처·반환 교체:

```python
def compute_query_signals(query: str, hits: list[dict], db_path, store=None) -> dict:
```

(docstring에 `registry_match` 한 줄 추가) 반환 직전에:

```python
    registry_match = False
    if store is not None:
        q = query.lower()
        registry_match = any(surface in q for surface in _registry_surfaces(store))

    return {"top_score": top_score, "margin": margin, "anchor_df": anchor_df,
            "registry_match": registry_match}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_search.py::ComputeQuerySignalsTest -q`
Expected: PASS (기존 + 신규 4개).

- [ ] **Step 5: 커밋**

```bash
git add tests/test_search.py src/project_brain/search.py
git commit -m "feat(search): compute_query_signals에 registry_match 신호 + _registry_surfaces"
```

---

## Task 3: `eval_recall` store 배관 + 통합 테스트

**Files:**
- Modify: `src/project_brain/search.py:682-714` (`eval_recall`)
- Test: `tests/test_search.py` (`EvalRecallGateAppliedTest`, 873줄 근방)

**Interfaces:**
- Consumes: `BrainStore.load`, `resolve_brain_root`(search.py에 이미 import·사용됨 — recall 본문 참조).
- Produces: `eval_recall(...)` 동작 — store를 1회 로드해 recall + compute_query_signals에 전달, 게이트에 registry_match 반영.

- [ ] **Step 1: 실패 테스트 작성**

`EvalRecallGateAppliedTest`에 추가:

```python
    def test_registry_query_opens_and_absent_still_blocked(self):
        # 배관 검증: store가 compute_query_signals까지 닿아 registry_match가 게이트에 반영된다.
        # (OR 로직 인과 격리는 _gate_pass·compute_query_signals 단위테스트 담당.)
        n = _ANCHOR_DF_MAX + 5
        common = [glossary_term(f"g.c{i}", term="보상", definition="흔한 보상 토큰")
                  for i in range(n)]
        target = glossary_term("g.lb", term="럭키박스구성품",
                               definition="럭키박스 구성품 표시 기능",
                               synonyms=["럭키박스표시팝업"])
        brain, db = self._build(common + [target])
        # 명부 표면형('럭키박스표시팝업', 3자+)을 통째 포함한 질의 → 열림.
        opened = eval_recall("럭키박스표시팝업 알려줘", db_path=db,
                             embedder=self.embedder, brain_root=brain)
        self.assertIn("g.lb", {h["object_id"] for h in opened["results"]})
        self.assertFalse(opened["needs_clarification"])
        # 명부에 없는 엔티티 + 흔한 토큰만 → registry_match 없음 → s5 가드로 여전히 차단.
        blocked = eval_recall("없는엔티티 보상", db_path=db,
                              embedder=self.embedder, brain_root=brain)
        self.assertEqual(blocked["results"], [])
        self.assertTrue(blocked["needs_clarification"])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_search.py::EvalRecallGateAppliedTest::test_registry_query_opens_and_absent_still_blocked -q`
Expected: FAIL — `g.lb`가 results에 없음(현재 eval_recall은 store를 compute_query_signals에 안 넘겨 registry_match=False).

- [ ] **Step 3: 최소 구현**

`src/project_brain/search.py`의 `eval_recall` 본문에서 recall·signals 호출부를 교체:

```python
    resolved_root = resolve_brain_root(brain_root)
    if store is None:
        store = BrainStore.load(resolved_root)

    hits = recall(query, db_path=db_path, embedder=embedder, brain_root=resolved_root,
                  store=store)
    signals = compute_query_signals(query, hits, db_path, store=store)
```

(docstring `store` 설명에 "compute_query_signals의 명부 registry_match에도 쓴다" 한 줄 보강.)

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_search.py::EvalRecallGateAppliedTest -q`
Expected: PASS (신규 + 기존 s5 테스트 `test_anchorless_query_gates_all_channels` 그대로 PASS).

- [ ] **Step 5: 전체 search 테스트 회귀 확인**

Run: `.venv/bin/python -m pytest tests/test_search.py -q`
Expected: PASS 전부(회귀 0).

- [ ] **Step 6: 커밋**

```bash
git add tests/test_search.py src/project_brain/search.py
git commit -m "feat(search): eval_recall이 store를 게이트 명부 판정까지 전달(배관)"
```

---

## Task 4: lint — synonyms/aliases 게이트 통과권 규칙 강제 (schema.py)

**Files:**
- Modify: `src/project_brain/schema.py` (상수 구역 + GlossaryTerm 검증 블록, `elif kind == "GlossaryTerm":` ~ reviewed evidence_refs 체크 뒤)
- Test: `tests/test_schema.py`(없으면 lint 테스트가 있는 파일 — `grep -rln "validate_object\|lint_store" tests/`로 확인)

**Interfaces:**
- Consumes: `_SYNONYM_MIN_LEN=3`(search._REGISTRY_MIN_SURFACE_LEN과 일치), `_SYNONYM_GENERIC_BLOCKLIST`.
- Produces: `validate_object`가 GlossaryTerm synonyms/aliases에 최소 길이·단독 일반명사 위반 시 error 추가. `lint_store` 경유 자동 반영.

- [ ] **Step 1: 실패 테스트 작성**

lint 테스트 파일에 추가(파일 위치는 위 grep으로 확정; 예시는 `tests/test_schema.py`):

```python
    def test_glossary_synonym_too_short_rejected(self):
        obj = {"id": "g.x", "kind": "GlossaryTerm", "status": "reviewed",
               "truth_role": "domain", "title": "T", "context_id": "context.n",
               "term": "온전한용어", "definition": "정의", "evidence_refs": ["ev.x"],
               "synonyms": ["NL"]}
        errors = validate_object(obj)
        self.assertTrue(any("too short" in e for e in errors))

    def test_glossary_synonym_bare_generic_rejected(self):
        obj = {"id": "g.y", "kind": "GlossaryTerm", "status": "reviewed",
               "truth_role": "domain", "title": "T", "context_id": "context.n",
               "term": "온전한용어", "definition": "정의", "evidence_refs": ["ev.x"],
               "synonyms": ["이벤트"]}
        errors = validate_object(obj)
        self.assertTrue(any("generic" in e for e in errors))

    def test_glossary_good_synonym_passes(self):
        obj = {"id": "g.z", "kind": "GlossaryTerm", "status": "reviewed",
               "truth_role": "domain", "title": "T", "context_id": "context.n",
               "term": "온전한용어", "definition": "정의", "evidence_refs": ["ev.x"],
               "synonyms": ["럭키박스", "클리어 패스 티켓 복구"]}
        errors = validate_object(obj)
        self.assertFalse(any(("too short" in e or "generic" in e) for e in errors))
```

(파일 상단에 `from project_brain.schema import validate_object` 없으면 추가.)

- [ ] **Step 2: 테스트 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_schema.py -q -k "synonym"`
Expected: 앞 2개 FAIL(현재 synonyms 값 검증 0줄이라 error 안 남).

- [ ] **Step 3: 최소 구현**

`src/project_brain/schema.py` 상수 구역에 추가:

```python
_SYNONYM_MIN_LEN = 3  # synonyms/aliases는 게이트 통과권 표면형 — search._REGISTRY_MIN_SURFACE_LEN과 일치.
# 단독으로 쓰면 아무 질의에나 부분문자열로 걸려 게이트를 오염시키는 흔한 일반명사(3자+, bb2 실측 critic 확정).
# 2자 이하 일반명사(버블 283·팝업 180·모드·보상·영역·타입)는 _SYNONYM_MIN_LEN 규칙이 이미 막는다.
# ★유한 목록은 완전성을 주장 못 한다 — 명백한 실수의 즉시 차단용. 실가드는 B+C 검수 + 골든셋 eval.
# df 기반 하드 판정은 불가(고유명·generic df 구간 겹침: 레이스121>아이콘79, 카테고리17<리스킨22).
# 스테이지148·레이스121·말풍선44는 도메인 고유명이라 넣으면 안 됨(B+C 판단 영역).
_SYNONYM_GENERIC_BLOCKLIST = frozenset({
    "이벤트", "아이콘", "카테고리", "레이아웃", "리스트", "메시지", "프로필"})
```

`validate_object`의 GlossaryTerm 블록 끝(reviewed evidence_refs 체크 바로 뒤, `elif kind == "ContextProjection":` 직전)에 삽입:

```python
        for field in ("synonyms", "aliases"):
            for surface in obj.get(field) or []:
                s = surface.strip() if isinstance(surface, str) else ""
                if len(s) < _SYNONYM_MIN_LEN:
                    errors.append(
                        f"{obj['id']}: GlossaryTerm {field} {surface!r} too short "
                        f"(min {_SYNONYM_MIN_LEN} — 게이트 통과권 표면형)")
                elif s.lower() in _SYNONYM_GENERIC_BLOCKLIST:
                    errors.append(
                        f"{obj['id']}: GlossaryTerm {field} {surface!r} bare generic "
                        f"(게이트 오염 — 고유성 있는 표현만)")
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_schema.py -q -k "synonym"`
Expected: PASS 3개.

- [ ] **Step 5: 길이 문턱 일치 핀 테스트 추가**

`GatePureFunctionTest.test_calibration_constants_pinned`(test_search.py:747) 끝에 추가:

```python
        # 명부 길이 문턱은 lint 최소 길이와 일치해야 오매칭/규칙 불일치가 안 생긴다.
        from project_brain.schema import _SYNONYM_MIN_LEN
        self.assertEqual(_REGISTRY_MIN_SURFACE_LEN, 3)
        self.assertEqual(_SYNONYM_MIN_LEN, _REGISTRY_MIN_SURFACE_LEN)
```

(test_search.py 상단 import에 `_REGISTRY_MIN_SURFACE_LEN` 추가.)

- [ ] **Step 6: 전체 스위트 회귀(기존 픽스처 위반 색출)**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS 전부. 만약 기존 합성 픽스처에 2자 synonyms가 있어 실패하면, 그 픽스처를 3자+로 고친다(테스트 데이터 수정만, 규칙 유지).

- [ ] **Step 7: 커밋**

```bash
git add tests/test_schema.py tests/test_search.py src/project_brain/schema.py
git commit -m "feat(schema): GlossaryTerm synonyms/aliases 게이트 통과권 규칙 lint 강제"
```

---

## Task 5: 적재 스킬 + 참조 문서 — synonyms "게이트 통과권" 승격

**Files:**
- Modify: `src/project_brain/templates/ingest/SKILL.md:339-357` ("용어 동의어" 섹션)
- Modify: `src/project_brain/templates/ingest/references/worked-example.md:38`
- Modify: `src/project_brain/templates/ingest/references/object-model.md:47` 근방(GlossaryTerm 필드 표)
- Test: `tests/test_installer.py`

**Interfaces:**
- Consumes: 없음(문서). Produces: 적재 에이전트가 따르는 규칙 텍스트 — 코드(Task 2·4)와 의미 일치.

- [ ] **Step 1: 설치 테스트 baseline 확인(변경 전 녹색)**

Run: `.venv/bin/python -m pytest tests/test_installer.py -q`
Expected: PASS(현재 상태 기준선).

- [ ] **Step 2: SKILL.md "용어 동의어" 섹션 갱신**

`src/project_brain/templates/ingest/SKILL.md`의 339줄 제목을 교체:

```markdown
## 용어 동의어 — 게이트 통과권 (엔티티 존재 표면형)
```

341-342줄 효과 설명을 교체(메커니즘을 D1로):

```markdown
GlossaryTerm 노트(`glossary[]`)에 `synonyms`/`aliases`를 채우면, **답변 게이트가 그 표면형이
질의에 통째로 등장할 때 "이 엔티티가 코퍼스에 있다"고 인정해 결과를 연다**(엔티티 명부 D1 매칭 —
`compute_query_signals`/`_gate_pass`). 부수적으로 BM25 recall + 색인 표면도 넓어진다(`surface.py`).
term이 영문 코드명이라 한국어 질의로는 안 걸리는 경우, synonyms의 한국어 표면형이 게이트 통과권이 된다.
```

348줄 예시 `getNextLevel → ["NL", "NextLevel"]`을 3글자+로 교체(NL 제거):

```markdown
3. **코드 식별자 변형.** 약어·대소문자(3글자 이상만). 예: `getNextLevel` → `["NextLevel", "NextRaceNo"]`.
```

350-352줄 "지켜야 할 두 규칙"을 세 규칙으로 교체(근거 갱신 + 최소 3글자 + 백필):

```markdown
지켜야 할 규칙:
- **단독 일반명사 금지 + 최소 3글자.** "이벤트"·"아이콘"·"카테고리" 같은 흔한 낱말을 단독으로
  넣지 마라 — 게이트가 D1(부분문자열)로 판정하므로 일반명사 표면형은 아무 질의에나 걸려 미적재
  엔티티를 거짓으로 열어버린다(s5 거짓양성). 고유성 있는 구(句)만. 2글자 이하는 lint가 거부한다
  (`schema.py` GlossaryTerm 검증).
- **definition 본문에 이미 있는 단어는 넣지 마라** — 이미 색인된다. 본문에 없는 다른 표현만.
- **컨텍스트 대표 엔티티명 백필.** 컨텍스트의 대표 GlossaryTerm에는 사용자가 그 기능을 부르는
  한국어 대표명(예: 럭키박스 컨텍스트 → "럭키박스")을 synonyms로 넣어, 그 엔티티 질의가 게이트를
  통과하게 한다. DomainContext `display_name`이 깨끗한 한국어 단서다.
```

- [ ] **Step 3: worked-example.md 갱신**

`references/worked-example.md:38`의 "(+ 별칭이 있으면)"을 교체:

```markdown
- `GlossaryTerm` `g.join-availability`(참여 가능 조건), `g.repeat-join`(반복 참여) — 용어 + 정의 + **synonyms/aliases에 한국어 대표명·등가어(게이트 통과권, 최소 3글자·단독 일반명사 금지)**.
```

- [ ] **Step 4: object-model.md 갱신**

`references/object-model.md`의 GlossaryTerm 필수필드 표(47줄 `| GlossaryTerm | context_id, term, definition |`) 아래 설명 구역에 한 줄 추가(표 바로 다음 문단 또는 GlossaryTerm 관련 절):

```markdown
- **GlossaryTerm synonyms/aliases** (선택 필드지만 게이트 통과권): 표면형이 질의에 통째 등장하면
  답변 게이트가 엔티티 존재를 인정한다(D1 매칭). 최소 3글자·단독 일반명사 금지(lint 강제).
```

- [ ] **Step 5: 설치 테스트 회귀(템플릿 렌더 안전 확인)**

Run: `.venv/bin/python -m pytest tests/test_installer.py -q`
Expected: PASS. 특히 `test_real_templates_render_with_synthetic_values` — 새로 `{{ }}` 리터럴을 넣지 않았으니 통과해야 한다. 파일 개수 불변(신규 파일 없음)이라 카운트 테스트도 통과.

- [ ] **Step 6: 커밋**

```bash
git add src/project_brain/templates/ingest/SKILL.md src/project_brain/templates/ingest/references/worked-example.md src/project_brain/templates/ingest/references/object-model.md
git commit -m "docs(ingest-skill): synonyms를 게이트 통과권으로 승격 + 백필·최소3글자 규칙"
```

---

## Task 6: 엔진 내부 문서 — 게이트 설명 갱신 (search-internals.md)

**Files:**
- Modify: `docs/search-internals.md:135-139` (게이트·표면 앵커 설명)

**Interfaces:** 없음(문서). 코드(Task 1-3)와 동작 서술 일치.

- [ ] **Step 1: 게이트 설명 갱신**

`docs/search-internals.md`의 게이트 서술(135-139줄 근방, "세 신호는 ... 표면 앵커 ...")에서 표면 앵커 설명을 명부 OR 보강 반영으로 교체:

```markdown
게이트 boolean은 절대 점수 바닥 + (명부 매칭 OR 표면 앵커)다. **명부 매칭**(registry_match)은
질의에 GlossaryTerm term/synonyms/aliases 표면형(3자+)이 통째 부분문자열로 등장하면 참 —
`compute_query_signals`가 store로 계산한다. **표면 앵커**(anchor_df, `_ANCHOR_DF_MAX=30`)는
명부 매칭이 없을 때의 폴백 신호다. 예컨대 '크리스마스'(코퍼스 df 0, 명부 미등재)처럼 핵심
엔티티가 없으면 명부도 앵커도 실패해 게이트가 막아 거짓양성을 낸다(s5 가드). 잘 적재된 엔티티는
토큰이 흔해져 anchor_df가 상한을 넘어도 명부 표면형으로 통과한다(럭키박스 거짓음성 해소).
```

(margin이 boolean에 안 들어간다는 기존 설명은 유지.)

- [ ] **Step 2: 문서 정합 확인(수동)**

Read: `docs/search-internals.md:130-145` — 게이트 설명이 `_gate_pass`(search.py) 실코드와 일치하는지 눈으로 대조. 함수 라인 인용이 있으면 현재 값으로 갱신.

- [ ] **Step 3: 커밋**

```bash
git add docs/search-internals.md
git commit -m "docs(search-internals): 게이트를 명부 매칭 OR 표면 앵커로 갱신"
```

---

## 최종 검증 (전체)

- [ ] **엔진 합성 전체 통과**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS 전부(기존 + 신규). 회귀 0.

- [ ] **편집 설치 반영 확인(글로벌 CLI가 최신 코드 쓰는지)**

편집 설치라 코드 변경은 즉시 반영되지만, pyproject 의존성은 안 바뀌었으니 재설치 불필요.
Run(선택): `project-brain --help`가 에러 없이 뜨는지.

---

## Companion: bb2 데이터레포 플랜 (별도 파일)

이 엔진 변경은 **실코퍼스 안전망(bb2 골든셋)이 선행**돼야 신뢰 투입된다. 데이터레포 작업(골든셋 보강·synonyms 백필·기존 2자 synonyms 정리·실모델 회귀)은 별도 플랜:
`docs/plans/2026-07-06-bb2-anchor-golden-set-backfill.md`.

실행 순서(레포 간):
1. **bb2 골든셋 보강**(동반 플랜 Task 1) — 안전망 먼저.
2. **엔진 이 플랜 Task 1~6** — 합성 TDD로 코드·규칙·문서.
3. **bb2 백필 + 2자 synonyms 정리 + 실모델 회귀**(동반 플랜 Task 2~4) — `project-brain audit`(lint 신규 규칙 통과 확인) → `brain/checks` → `project-brain eval`(럭키박스 열림 + s5 차단 실측).

---

## Self-Review

- **Spec 커버리지(확정 설계 §2 대비):** 명부=F1(Task 2 `_registry_surfaces`가 GlossaryTerm term+syn+alias만) ✓ / 매칭=D1 소문자·3자+(Task 2) ✓ / 폴백=OR 보강(Task 1) ✓ / 배관 1단계(Task 3) ✓ / 적재 규칙·최소3글자·단독일반명사(Task 4 lint + Task 5 skill) ✓ / 백필 규칙 안내(Task 5) ✓ / 내부문서(Task 6) ✓ / 골든셋·백필=동반 bb2 플랜 ✓. F2/F3·조각매칭·완전대체는 확정 설계에서 기각됐으므로 미구현이 정답.
- **Placeholder 스캔:** 모든 코드 스텝에 실제 코드 블록 존재. "적절히 처리"류 없음.
- **타입 정합:** `registry_match: bool`이 Task 1(_gate_pass 소비)·Task 2(compute_query_signals 생산)·Task 3(eval_recall 배관)에서 동일 키. `_REGISTRY_MIN_SURFACE_LEN`(search) == `_SYNONYM_MIN_LEN`(schema) = 3, Task 4 Step 5가 핀으로 강제. `glossary_term` 헬퍼 kwarg(synonyms/aliases)는 Task 2에서 추가 후 Task 3에서 사용 — 순서 일치.
