# BB2 Brain G11b — Glossary Scope Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 한국어 쿼리에서 GlossaryTerm의 `scope_hint`를 통해 scope 필터가 작동하게 한다 (한↔영 scope 다리).

**Architecture:** GlossaryTerm에 `scope_hint?: {feature?, surface?}` 신규 필드. `_query_scope_filters`가 query에 substring 포함된 GlossaryTerm을 string-containment longest-match로 골라 그 scope_hint(ASCII canonical 값)를 기존 필터 set에 합류. 토크나이저 미변경 — 한글은 glossary 경유로만 ASCII scope로 변환. intent 모듈은 건드리지 않음(시그니처 변경·하드코딩 제거는 G11c).

**Tech Stack:** Python 3, unittest, `scripts/bb2_brain/`.

**Spec:** `docs/superpowers/specs/2026-05-30-bb2-brain-g11b-glossary-scope-bridge-design.md` (advisor 리뷰 반영본)

---

## Conventions

- 테스트 실행: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -v`
- 커밋 대상은 **코드만**(`scripts/bb2_brain/`은 git 추적). `docs/*`는 `.gitignore`라 미추적 — 문서 편집은 커밋하지 않고 working tree에만 남긴다(단 object-model/query-routing spec은 추적 파일이라 Task 5에서 커밋 가능).
- `write_object(root, rel_path, obj_dict)` 헬퍼는 test_router.py 상단에 이미 존재. fixture 객체는 dict.
- 기존 baseline: 34 tests 통과.

## File Structure

- Modify: `scripts/bb2_brain/router.py` — `_SCOPE_HINT_DIMENSIONS` 상수, `_matched_glossary_terms()`, `_glossary_scope_disclosures()` 신규 + `_query_scope_filters()` 확장 + `answer()` current_status/as_of 브랜치에 공시 합류.
- Modify: `scripts/bb2_brain/tests/test_router.py` — 신규 테스트 4종 + `build_store()` fixture GlossaryTerm rename/scope_hint + 신규 term 2종.
- Modify (추적 문서): `docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md` §11.2.
- Modify (추적 문서): `docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md` §6.3.

---

## Task 1: Korean glossary → scope 주입 (코어)

**Files:**
- Modify: `scripts/bb2_brain/router.py:114-125`
- Test: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: 실패 테스트 작성** (test_router.py 끝에 추가)

```python
    def test_korean_glossary_term_injects_surface_scope(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/domain/term_enter.json", {
            "id": "term.enter", "kind": "GlossaryTerm", "status": "reviewed",
            "truth_role": "reference", "term": "입장팝업",
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
        answer = router.answer("입장팝업 현재 규칙은 뭐야?")
        self.assertIn("fact.enter", answer["source_object_ids"])
        self.assertNotIn("fact.continue", answer["source_object_ids"])
```

- [ ] **Step 2: 실패 확인**

Run: `... -m unittest scripts.bb2_brain.tests.test_router.<TestClass>.test_korean_glossary_term_injects_surface_scope -v`
Expected: FAIL — `fact.continue`가 source에 포함됨(한글 scope 필터 미작동, 현재 surface 필터 안 걸려 두 fact 다 반환).

- [ ] **Step 3: 최소 구현** (router.py)

`_SCOPE_DIMENSIONS = (...)` 줄(현 114) 바로 아래에 추가:

```python
    _SCOPE_HINT_DIMENSIONS = ("feature", "surface")

    def _matched_glossary_terms(self, query: str) -> list[dict]:
        matched = [
            term for term in self._reviewed_by_kind("GlossaryTerm")
            if term.get("term") and term["term"] in query
        ]
        result = []
        for term in matched:
            text = term["term"]
            contained = any(
                other is not term and len(other["term"]) > len(text) and text in other["term"]
                for other in matched
            )
            if not contained:
                result.append(term)
        return result
```

`_query_scope_filters`의 `return filters` 직전(현 124와 125 사이)에 주입 블록 추가:

```python
        for term in self._matched_glossary_terms(query):
            hint = term.get("scope_hint", {})
            for dim in self._SCOPE_HINT_DIMENSIONS:
                value = hint.get(dim)
                if value:
                    filters.setdefault(dim, set()).add(value)
```

- [ ] **Step 4: 통과 확인**

Run: `... test_korean_glossary_term_injects_surface_scope -v`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: inject GlossaryTerm scope_hint into BB2 Brain scope filters (G11b core)"
```

---

## Task 2: string-containment longest-match (겹침 가드)

**Files:**
- Test: `scripts/bb2_brain/tests/test_router.py`
- (구현은 Task 1의 `_matched_glossary_terms`가 이미 처리 — 이 task는 가드 회귀 테스트)

- [ ] **Step 1: 실패/회귀 테스트 작성**

```python
    def test_longest_match_drops_contained_glossary_term(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/domain/term_popup.json", {
            "id": "term.popup", "kind": "GlossaryTerm", "status": "reviewed",
            "truth_role": "reference", "term": "팝업",
            "scope_hint": {"surface": "PopupContinue"},
            "definition": "팝업 일반", "evidence_refs": [],
        })
        write_object(root, "objects/domain/term_enter.json", {
            "id": "term.enter", "kind": "GlossaryTerm", "status": "reviewed",
            "truth_role": "reference", "term": "입장팝업",
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
        answer = router.answer("입장팝업 현재 규칙은 뭐야?")
        # "팝업" ⊂ "입장팝업" → "팝업" 드롭 → surface={PopupEnter}만 주입
        self.assertIn("fact.enter", answer["source_object_ids"])
        self.assertNotIn("fact.continue", answer["source_object_ids"])
```

- [ ] **Step 2: 통과 확인** (Task 1 구현으로 이미 통과해야 함)

Run: `... test_longest_match_drops_contained_glossary_term -v`
Expected: PASS. (FAIL 시 `_matched_glossary_terms`의 containment 조건 점검.)

- [ ] **Step 3: 커밋**

```bash
git add scripts/bb2_brain/tests/test_router.py
git commit -m "test: cover string-containment longest-match for BB2 Brain glossary scope (G11b)"
```

---

## Task 3: 조건부 추론 공시

**Files:**
- Modify: `scripts/bb2_brain/router.py` (`_glossary_scope_disclosures` 신규 + answer() current_status/as_of 브랜치)
- Test: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: 실패 테스트 작성**

```python
    def test_glossary_scope_inference_is_disclosed_when_it_narrows(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/domain/term_enter.json", {
            "id": "term.enter", "kind": "GlossaryTerm", "status": "reviewed",
            "truth_role": "reference", "term": "입장팝업",
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
        answer = router.answer("입장팝업 현재 규칙은 뭐야?")
        self.assertTrue(any("입장팝업" in w and "PopupEnter" in w for w in answer["warnings"]))
```

- [ ] **Step 2: 실패 확인**

Run: `... test_glossary_scope_inference_is_disclosed_when_it_narrows -v`
Expected: FAIL — warnings에 추론 공시 없음.

- [ ] **Step 3: 구현** (router.py)

`_matched_glossary_terms` 아래에 추가:

```python
    def _glossary_scope_disclosures(self, query: str) -> list[str]:
        messages: list[str] = []
        all_facts = self._reviewed_by_kind("TemporalFact")
        for term in self._matched_glossary_terms(query):
            hint = term.get("scope_hint", {})
            for dim in self._SCOPE_HINT_DIMENSIONS:
                value = hint.get(dim)
                if not value:
                    continue
                if any(f.get("scope", {}).get(dim) not in (None, value) for f in all_facts):
                    messages.append(f"scope inferred from glossary term '{term['term']}' → {dim}={value}")
        return messages
```

`answer()`의 `current_status` 브랜치: `warnings.extend(self._stale_view_warnings(all_views))`(현 46) 다음 줄에 추가:

```python
                warnings.extend(self._glossary_scope_disclosures(query))
```

`answer()`의 `as_of_history` 브랜치: ambiguous 처리 블록(현 55-58) 다음, `for fact in facts:`(현 59) 직전에 추가:

```python
                warnings.extend(self._glossary_scope_disclosures(query))
```

- [ ] **Step 4: 통과 확인**

Run: `... test_glossary_scope_inference_is_disclosed_when_it_narrows -v`
Expected: PASS.

- [ ] **Step 5: 비-narrow 시 무공시 회귀 테스트 추가**

```python
    def test_glossary_scope_not_disclosed_when_no_other_surface(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/domain/term_enter.json", {
            "id": "term.enter", "kind": "GlossaryTerm", "status": "reviewed",
            "truth_role": "reference", "term": "입장팝업",
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
        answer = router.answer("입장팝업 현재 규칙은 뭐야?")
        self.assertFalse(any("inferred from glossary" in w for w in answer["warnings"]))
```

- [ ] **Step 6: 통과 확인 + 커밋**

Run: `... test_glossary_scope_not_disclosed_when_no_other_surface -v`
Expected: PASS.

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: disclose BB2 Brain glossary scope inference when it narrows facts (G11b)"
```

---

## Task 4: build_store fixture 정합 + 용어 가드 + ASCII 단언 + 회귀

**Files:**
- Modify: `scripts/bb2_brain/tests/test_router.py:122-132` (term.popup-enter) + 신규 term 2종 + ASCII 테스트

- [ ] **Step 1: build_store의 term.popup-enter rename + scope_hint**

`test_router.py:122-132`의 `term_popup_enter.json` 블록을 교체:

```python
        write_object(root, "objects/domain/term_popup_enter.json", {
            "id": "term.popup-enter",
            "kind": "GlossaryTerm",
            "status": "reviewed",
            "truth_role": "reference",
            "term": "입장팝업",
            "synonyms": [],
            "avoided_terms": ["시작팝업"],
            "scope_hint": {"surface": "PopupEnter"},
            "definition": "스테이지 진입 시 뜨는 팝업. 직접 토큰 사용 가능 UI.",
            "evidence_refs": [],
        })
```

(`canonical_term`→`term`, `scope_hint` 추가. `avoided_terms`는 G11c까지 유지.)

- [ ] **Step 2: 신규 용어 가드 term 2종 추가** (위 블록 바로 다음)

```python
        write_object(root, "objects/domain/term_popup_continue.json", {
            "id": "term.popup-continue", "kind": "GlossaryTerm", "status": "reviewed",
            "truth_role": "reference", "term": "컨티뉴 팝업",
            "scope_hint": {"surface": "PopupContinue"},
            "definition": "이어하기 팝업.", "evidence_refs": [],
        })
        write_object(root, "objects/domain/term_event_cluster.json", {
            "id": "term.event-cluster", "kind": "GlossaryTerm", "status": "reviewed",
            "truth_role": "reference", "term": "이벤트 클러스터",
            "scope_hint": {"surface": "PopupEnter"},
            "definition": "입장팝업 내 여러 이벤트 묶음 슬롯 UI.", "evidence_refs": [],
        })
```

- [ ] **Step 3: ASCII 단언 테스트 추가**

```python
    def test_scope_and_scope_hint_values_are_ascii(self):
        router = QueryRouter(self.build_store())
        for fact in router._reviewed_by_kind("TemporalFact"):
            for value in fact.get("scope", {}).values():
                self.assertTrue(str(value).isascii(), f"non-ASCII scope: {value}")
        for term in router._reviewed_by_kind("GlossaryTerm"):
            for value in term.get("scope_hint", {}).values():
                self.assertTrue(str(value).isascii(), f"non-ASCII scope_hint: {value}")
```

- [ ] **Step 4: 전체 회귀 실행**

Run: `... -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store -v`
Expected: 전부 PASS (기존 34 + 신규). build_store 기반 "입장팝업" 쿼리들은 surface=PopupEnter 주입받지만 fixture fact.current-rule이 PopupEnter(`test_router.py:39,53`)라 회귀 없음.
주의: 실패하면 fixture의 모든 reviewed TemporalFact surface가 PopupEnter인지 확인(다른 surface fact가 있으면 입장팝업 쿼리가 그걸 제외해 기존 assert 깨질 수 있음 — 그 경우 해당 기존 테스트의 기대치 재확인).

- [ ] **Step 5: 커밋**

```bash
git add scripts/bb2_brain/tests/test_router.py
git commit -m "test: align BB2 Brain glossary fixture to spec + scope_hint guards + ASCII assert (G11b)"
```

---

## Task 5: 문서 정합 (object-model §11.2 + query-routing §6.3)

**Files:**
- Modify: `docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md` (§11.2 GlossaryTerm interface, 현 581-591)
- Modify: `docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md` (§6.3, 현 173 부근)

- [ ] **Step 1: object-model §11.2에 scope_hint 추가**

`interface GlossaryTerm` 본문(현 588 `synonyms?` 다음)에 한 줄 추가:

```ts
  scope_hint?: { feature?: string; surface?: string };
```

불변조건 목록(현 594-597)에 추가:

```
- `scope_hint`의 feature/surface 값은 동일 차원의 `TemporalFact.scope` 값과 같은 ASCII canonical 식별자여야 한다 (G11b).
```

- [ ] **Step 2: query-routing §6.3 추론 메커니즘 갱신**

§6.3 L173("The router may infer `feature` or `surface` from a matched `GlossaryTerm` only when the context map has a single matching leaf.")에 한 줄 보강(대체 명시):

```
- (G11b) feature/surface 추론은 matched `GlossaryTerm.scope_hint`로 수행한다. 한 leaf가 복수 surface를 묶어 "single matching leaf" 가드만으론 surface granularity가 부족하므로, leaf 단위 대신 term별 `scope_hint`를 source로 쓴다.
```

- [ ] **Step 3: 커밋** (두 spec 모두 git 추적 파일)

```bash
git add docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md
git commit -m "docs: add GlossaryTerm.scope_hint + update query-routing §6.3 inference (G11b)"
```

(주의: `docs/*`는 일반적으로 gitignore지만 이 두 파일은 기존부터 git 추적됨 — `git ls-files`로 확인 후 add. 미추적이면 working tree에만 남기고 커밋 생략.)

---

## Self-Review

**Spec coverage:** §4.1 scope_hint 2차원(T1·T5 fixture·T5 doc) / §4.2 router 주입+조건부 공시(T1·T3) / §4.4 fixture rename+가드(T4) / §4.5 §6.3 doc(T5) / §5 ASCII 테스트(T4)·string-containment(T2)·회귀(T4). D2 잔여 충돌 한계 = 테스트로 막지 않음(설계상 큐레이션 책임, T2 주석). 전부 task로 커버.

**Placeholder scan:** 없음 — 모든 step에 실제 코드/명령.

**Type consistency:** `_SCOPE_HINT_DIMENSIONS`(T1) = `_glossary_scope_disclosures`(T3)에서 동일 사용. `_matched_glossary_terms`(T1) → T2·T3 재사용. fixture 필드 `term`/`scope_hint`(T1 테스트 store)와 build_store(T4) 일치. GlossaryTerm 읽기는 전부 `.get("term")`/`.get("scope_hint", {})`.

**G11c 경계:** intent.py·normalize_terms·classify_query·AVOIDED_TERMS·test_intent.py·avoided_terms→avoid는 이 플랜에서 건드리지 않음.
