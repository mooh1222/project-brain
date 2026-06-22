# BB2 Brain G11c — Canonical Query Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `answer()`가 정규화된 `canonical_query`로 fact/scope/glossary 라우팅을 수행하게 해, 도메인 용어 보정(avoided→canonical)이 실제 라우팅에 도달하고(§4 preflight rule 1) 보정 사실을 공시한다(§4 rule 3).

**Architecture:** `answer()`는 `classify_query` 직후 `search = classified.normalized.canonical_query`를 한 번 계산하고, 본문 안에서 query를 소비하는 모든 헬퍼 호출(`_current_facts`/`_release_ambiguous`/`_glossary_scope_disclosures`/`_scoped_facts`)에 raw `query` 대신 `search`를 넘긴다. 출력 dict의 `"query": query`는 raw 유지(§4 rule 2 사용자 표현 보존), `"canonical_query"`는 그대로. 보정이 적용되면(avoided_terms 비지 않으면) 경고에 보정 공시를 추가한다. 현재 정규화 매핑 출처는 하드코딩 `AVOIDED_TERMS`(intent.py) — 이 게이트는 그 출처를 건드리지 않는다(출처 코드→데이터 이전은 후속 G11d, 이 게이트의 end-to-end 테스트가 그 refactor의 parity anchor).

**Tech Stack:** Python 3, unittest, `scripts/bb2_brain/`.

**근거:** query-routing §4 preflight (rule 1 canonical 라우팅 / rule 2 사용자 표현 보존 / rule 3 보정 공시). advisor(surface:93) 2026-05-31 재랭크: wiring을 G11d(출처 refactor) 앞에 둬 behavior-preserving refactor의 anchor로 삼음(Karpathy goal #4). 회귀 수학적 0 — 기존 40 테스트 쿼리 중 유일 avoided 토큰 "시작팝업"을 포함하는 쿼리가 0개라 모든 기존 케이스에서 `canonical == query`.

---

## Conventions

- 테스트 실행: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store`
- 단일 테스트: `... -m unittest scripts.bb2_brain.tests.test_router.<TestClass>.<method> -v` (클래스명은 test_router.py 상단에서 확인)
- 커밋 대상은 코드(`scripts/bb2_brain/`, git 추적). query-routing spec(§4 문서)은 추적 파일이라 Task 3에서 커밋. (`docs/*`는 .gitignore지만 이 spec은 기존 추적됨 — `git add`, 필요시 `-f`.)
- `write_object(root, rel_path, obj_dict)` 헬퍼는 test_router.py 상단에 이미 존재.
- 현재 baseline: 40 tests 통과.

## File Structure

- Modify: `scripts/bb2_brain/router.py` — `answer()` 본문(현 L23~L99)에서 query 소비 헬퍼 호출을 `search`로 치환 + 보정 공시 추가. 출력 dict(L101~) 불변.
- Modify: `scripts/bb2_brain/tests/test_router.py` — 신규 end-to-end 테스트(canonical이 scope 다리에 도달) + 보정 공시 테스트.
- Modify (추적 문서): `docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md` — §4 preflight에 canonical이 라우팅 헬퍼에 실제 적용됨 + 보정 공시 명시.

intent.py·AVOIDED_TERMS·fixture 필드명은 이 게이트에서 **건드리지 않는다**(G11d 영역).

---

## Task 1: canonical을 라우팅 헬퍼에 주입 (end-to-end wiring)

**Files:**
- Modify: `scripts/bb2_brain/router.py` (`answer()` 본문)
- Test: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: 실패 테스트 작성** (test_router.py 테스트 클래스에 메서드 추가)

이 테스트는 avoided 용어("시작팝업")로 질의했을 때 정규화된 canonical("입장팝업")이 scope 다리에 도달해 PopupContinue fact를 배제하는지 검증한다. 자체 tempdir store 사용.

```python
    def test_avoided_term_query_routes_through_canonical_to_scope(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/domain/term_enter.json", {
            "id": "term.enter", "kind": "GlossaryTerm", "status": "reviewed",
            "truth_role": "reference", "term": "입장팝업",
            "avoid": ["시작팝업"],
            "scope_hint": {"surface": "PopupEnter"},
            "definition": "진입 팝업", "evidence_refs": [],
        })
        write_object(root, "objects/facts/enter.json", {
            "id": "fact.enter", "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact",
            "scope": {"project": "bb2-client", "release": "5.5", "surface": "PopupEnter"},
            "valid_from": "2026-05-26T00:00:00+09:00", "evidence_refs": [],
        })
        write_object(root, "objects/facts/continue.json", {
            "id": "fact.continue", "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact",
            "scope": {"project": "bb2-client", "release": "5.5", "surface": "PopupContinue"},
            "valid_from": "2026-05-26T00:00:00+09:00", "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("시작팝업 현재 규칙 뭐야?")
        # 정규화 시작팝업→입장팝업이 scope 헬퍼에 도달 → surface=PopupEnter 주입 → PopupContinue 배제
        self.assertIn("fact.enter", answer["source_object_ids"])
        self.assertNotIn("fact.continue", answer["source_object_ids"])
```

(주의: 이 게이트 시점엔 정규화 출처가 하드코딩 `AVOIDED_TERMS={"시작팝업":"입장팝업"}`이라 GlossaryTerm의 `avoid` 필드는 아직 정규화에 안 쓰인다. `avoid`를 미리 넣어 두는 건 후속 G11d가 같은 테스트를 green으로 유지하며 출처를 glossary로 옮기기 위함 — 지금은 무해한 forward-compat 데이터.)

- [ ] **Step 2: 실패 확인**

Run: `... -m unittest scripts.bb2_brain.tests.test_router.<TestClass>.test_avoided_term_query_routes_through_canonical_to_scope -v`
Expected: FAIL — `fact.continue`가 source에 포함됨. 이유: `answer()`가 raw "시작팝업 현재 규칙 뭐야?"를 scope 헬퍼에 넘겨 `_matched_glossary_terms`가 "입장팝업"을 못 찾음 → surface 필터 미주입 → 두 fact 다 반환.

- [ ] **Step 3: wiring 구현** (router.py `answer()`)

먼저 `answer()`를 끝까지 읽어 query를 소비하는 모든 헬퍼 호출 위치를 확인한다(현 기준: `_current_facts` L40, `_release_ambiguous` L41·L56, `_glossary_scope_disclosures` L47·L60, `_scoped_facts` L55·L87). 라인 번호는 근사 — 직접 확인.

`classified = classify_query(query)`(현 L23) 바로 다음 줄에 추가:

```python
        search = classified.normalized.canonical_query
```

그런 다음 `answer()` 본문 안에서 **query를 인자로 받는 모든 헬퍼 호출의 `query`를 `search`로 치환**한다. 원칙: 내부 라우팅/매칭 헬퍼는 canonical(search)로 동작(§4 rule 1). 구체적으로:
- `self._current_facts(query)` → `self._current_facts(search)`
- `self._release_ambiguous(facts, query)` → `self._release_ambiguous(facts, search)` (현 2곳)
- `self._glossary_scope_disclosures(query)` → `self._glossary_scope_disclosures(search)` (현 2곳)
- `self._scoped_facts(query)` → `self._scoped_facts(search)` (현 2곳 — as_of_history, evidence_provenance)

**출력 dict는 건드리지 않는다**: `"query": query`(raw 유지, §4 rule 2), `"canonical_query": classified.normalized.canonical_query`(그대로). `_reviewed_by_kind(...)` 호출들은 query를 안 받으므로 무변경.

(`why_changed`/`glossary_meaning`/`unknown` 브랜치는 query를 매칭에 안 쓰므로 치환 대상 없음 — 확인만.)

- [ ] **Step 4: 통과 확인**

Run: `... test_avoided_term_query_routes_through_canonical_to_scope -v`
Expected: PASS — canonical "입장팝업 현재 규칙 뭐야?"가 scope 다리에 도달, surface=PopupEnter 주입, PopupContinue 배제.

- [ ] **Step 5: 전체 회귀**

Run: `... -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store`
Expected: 전부 PASS, 41 tests (기존 40 + 신규 1). 회귀 0 — 기존 어떤 쿼리도 "시작팝업"을 포함하지 않아 모든 케이스에서 `search == query`(문자열 동일)라 헬퍼 실행이 동일.
주의: 실패하면 기존 테스트 쿼리 중 avoided 토큰("시작팝업")을 포함하는 게 있는지 `rg "시작팝업" scripts/bb2_brain/tests/test_router.py`로 확인(현재 L131 fixture 필드에만 존재, 쿼리엔 없음 → 0 회귀 보장).

- [ ] **Step 6: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: route BB2 Brain fact/scope helpers on canonical query (G11c §4 preflight)"
```

---

## Task 2: 용어 보정 공시 (§4 rule 3)

**Files:**
- Modify: `scripts/bb2_brain/router.py` (`answer()` — 보정 공시 추가)
- Test: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
    def test_avoided_term_correction_is_disclosed(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/domain/term_enter.json", {
            "id": "term.enter", "kind": "GlossaryTerm", "status": "reviewed",
            "truth_role": "reference", "term": "입장팝업",
            "avoid": ["시작팝업"],
            "scope_hint": {"surface": "PopupEnter"},
            "definition": "진입 팝업", "evidence_refs": [],
        })
        write_object(root, "objects/facts/enter.json", {
            "id": "fact.enter", "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact",
            "scope": {"project": "bb2-client", "release": "5.5", "surface": "PopupEnter"},
            "valid_from": "2026-05-26T00:00:00+09:00", "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("시작팝업 현재 규칙 뭐야?")
        self.assertTrue(any("보정" in w and "시작팝업" in w for w in answer["warnings"]))
```

- [ ] **Step 2: 실패 확인**

Run: `... test_avoided_term_correction_is_disclosed -v`
Expected: FAIL — warnings에 보정 공시 없음.

- [ ] **Step 3: 구현** (router.py `answer()`)

`search = classified.normalized.canonical_query`(Task 1에서 추가) 다음에 보정 공시 블록을 추가한다. `classified.normalized.avoided_terms`가 비지 않으면(=보정이 적용됨) 경고를 추가:

```python
        if classified.normalized.avoided_terms:
            corrected = ", ".join(sorted(set(classified.normalized.avoided_terms)))
            warnings.append(f"용어 보정 적용: {corrected} → canonical 질의로 라우팅")
```

(주의: `warnings` 리스트는 현재 `answer()`에서 `for intent` 루프 진입 전에 초기화된다(현 L28). 이 블록은 그 초기화 뒤, 루프 전 어디든 둘 수 있다 — `search` 정의 근처가 자연스럽다. 공시는 보정이 적용된 모든 질의에서 발화한다. G11b scope 공시와 같은 "항상 truthful" 패턴이되, 여기선 counterfactual narrows 판정 없이 "보정이 일어났다"는 사실만 공시 — 더 엄격한 narrows-only는 결과 변화 비교가 필요해 후속 과제로 둔다.)

- [ ] **Step 4: 통과 확인**

Run: `... test_avoided_term_correction_is_disclosed -v`
Expected: PASS.

- [ ] **Step 5: 비-보정 시 무공시 회귀 테스트**

```python
    def test_no_correction_disclosure_without_avoided_term(self):
        router = QueryRouter(self.build_store())
        answer = router.answer("입장팝업 현재 QA 기준은 뭐야?")
        self.assertFalse(any("용어 보정" in w for w in answer["warnings"]))
```

(build_store 쿼리엔 avoided 토큰 "시작팝업"이 없으므로 보정 공시가 없어야 한다.)

- [ ] **Step 6: 통과 확인 + 전체 회귀 + 커밋**

Run: `... test_no_correction_disclosure_without_avoided_term -v` → PASS.
Run 전체: `... -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store` → 43 tests PASS (41 + 2).

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: disclose BB2 Brain avoided-term correction in warnings (G11c §4 rule 3)"
```

---

## Task 3: 문서 정합 (query-routing §4 preflight)

**Files:**
- Modify: `docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md` (§4 preflight 섹션)

- [ ] **Step 1: §4 preflight에 canonical 라우팅 + 보정 공시 명시**

먼저 `docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md`의 §4 preflight 섹션(현 L80 부근 "Normalize domain terms ..." 규칙 목록)을 읽는다. 규칙 목록 끝에 한 줄 추가(G11c 구현 명시):

```
- (G11c) 정규화된 canonical query가 fact/scope/glossary 라우팅 헬퍼에 실제 전달된다(`answer()`가 `search = canonical_query`를 해당 헬퍼에 주입). 출력의 사용자 표현(`query`)은 raw로 보존한다(rule 2). avoided 용어 보정이 적용되면 경고에 공시한다(rule 3, `용어 보정 적용: ...`).
```

(§4에 번호 매겨진 규칙이 있으면 그 스타일에 맞춰 bullet 추가. 기존 문장 삭제·리플로우 금지 — 추가만.)

- [ ] **Step 2: 커밋** (query-routing spec은 git 추적 파일)

```bash
git add docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md
git commit -m "docs: note canonical routing + correction disclosure in query-routing §4 (G11c)"
```

(주의: `docs/*`는 일반적으로 gitignore지만 이 파일은 기존 추적됨 — `git ls-files`로 확인 후 add, 필요시 `-f`.)

---

## Self-Review

**Spec coverage:** §4 rule 1(canonical 라우팅 = Task 1 wiring) / rule 2(출력 query raw 보존 = Task 1 Step 3 출력 dict 불변) / rule 3(보정 공시 = Task 2). end-to-end 검증(시작팝업→입장팝업→PopupEnter 배제 = Task 1 테스트). §4 문서 정합(Task 3). 전부 task로 커버.

**Placeholder scan:** 없음 — 모든 step에 실제 코드/명령. 라인 번호는 "현 기준 근사, 직접 확인" 명시.

**Type consistency:** `search`(str) = `classified.normalized.canonical_query`(NormalizedQuery.canonical_query: str, intent.py:7). `classified.normalized.avoided_terms`(list[str], intent.py:8) — Task 2에서 비었는지 검사. 헬퍼 시그니처(`_current_facts`/`_release_ambiguous`/`_glossary_scope_disclosures`/`_scoped_facts`)는 모두 기존 query 위치 인자에 search(str)를 넘기는 것뿐 — 시그니처 무변경.

**G11d 경계:** intent.py·`AVOIDED_TERMS`·`normalize_terms`/`classify_query` 시그니처·fixture `avoided_terms→avoid` rename·test_intent는 이 플랜에서 **건드리지 않는다**. Task 1·2 테스트의 GlossaryTerm에 넣은 `avoid: ["시작팝업"]`은 G11d가 같은 테스트를 green으로 유지하며 출처를 옮기기 위한 forward-compat 데이터(현재 정규화는 하드코딩 AVOIDED_TERMS 사용).

**회귀 0 논증:** wiring은 query→search 치환. search는 canonical = query에서 avoided 토큰만 치환. 기존 40 테스트 쿼리에 유일 avoided 토큰 "시작팝업"이 0개 → 전부 search==query → 헬퍼 실행 동일 → 회귀 수학적 0(advisor 검증).
