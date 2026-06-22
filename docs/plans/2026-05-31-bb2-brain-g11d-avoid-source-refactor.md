# BB2 Brain G11d — Avoid-Correction Source Refactor (hardcode → GlossaryTerm.avoid)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development (behavior-preserving refactor — keep parity anchor green through the change). Steps use checkbox (`- [ ]`) syntax.

**Goal:** 도메인 용어 보정(avoided→canonical)의 출처를 intent.py 하드코딩 `AVOIDED_TERMS={"시작팝업":"입장팝업"}`에서 데이터(`GlossaryTerm.avoid` 필드, object-model §11.2)로 이전한다. `normalize_terms`/`classify_query` 시그니처를 일반화해 보정 map을 인자로 주입받게 한다. **behavior-preserving** — G11c가 남긴 e2e 테스트 `test_avoided_term_query_routes_through_canonical_to_scope`가 parity anchor(하드코딩→glossary 출처 스왑 후에도 green 유지 = 동작 보존 증명).

**Architecture (설계 결정):**
- intent.py는 **순수 문자열 정규화 모듈**로 유지한다(advisor 하드 제약: BrainStore import 금지). 시그니처: `normalize_terms(query, avoid_map=None)` / `classify_query(query, avoid_map=None)`. `avoid_map: dict[str,str]`는 `{avoided_term: canonical_term}`. 기본값 None→{} (무보정).
- router가 `_reviewed_by_kind("GlossaryTerm")`에서 보정 map을 구축(`_avoid_corrections()`)해 `classify_query`에 주입한다. router는 이미 GlossaryTerm 스키마(`.term`/`.scope_hint`)를 읽는 유일한 모듈이므로 `.avoid` 읽기도 여기 집약.
- **고려한 대안 (B)**: glossary dict 리스트를 intent.py에 그대로 넘겨 intent.py가 `.term`/`.avoid`를 읽게 함(advisor 노트 "glossary 객체를 인자로 주입; router가 `_reviewed_by_kind` 전달"의 문자적 독해). **채택 (A)**: router가 `{avoided:canonical}` map을 미리 구축해 주입. 이유 — intent.py에 도메인 스키마 결합을 퍼뜨리지 않고 GlossaryTerm 스키마 지식을 router 한 곳에 집약(단일 책임), test_intent가 plain dict만 받아 단순. 동작은 (A)/(B) 동일, parity anchor 양쪽 green. advisor 하드 제약(BrainStore import 금지)은 (A)가 더 강하게 충족(intent.py 도메인 결합 0).

**Tech Stack:** Python 3, unittest, `scripts/bb2_brain/`.

**근거:** object-model §11.2 `avoid?: string[]`(canonical 필드명). query-routing §4 preflight(정규화는 DomainContext/GlossaryTerm 기반). g11b design §58이 이 작업을 명시(시그니처 일반화 + `GlossaryTerm.avoid` 읽기 + 하드코딩 제거 + `avoided_terms→avoid` rename + test_intent 갱신; g11b는 게이트 번호를 "G11c"로 적었으나 advisor 2026-05-31 재랭크로 canonical wiring이 G11c 차지 → 이 작업은 G11d. 작업 내용 동일). G11c plan Self-Review "G11d 경계" 절.

---

## Conventions

- 테스트 실행: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store`
- 단일 테스트: `... -m unittest scripts.bb2_brain.tests.test_router.RouterTest.<method> -v`
- 현재 baseline: 43 tests 통과.
- 커밋 대상은 코드(`scripts/bb2_brain/`, git 추적). 플랜/spec 문서는 `docs/*`(대개 gitignore) — 코드만 커밋.
- **naming 혼동 금지**(task 경고): `NormalizedQuery.avoided_terms`(모델 출력 = 쿼리에서 감지된 보정 토큰 리스트) ≠ `avoid_map`(주입 인자, {avoided:canonical}) ≠ `GlossaryTerm.avoid`(JSON 필드, list[str]). 신규 인자명은 `avoid_map`으로 충돌 회피.

## File Structure

- Modify: `scripts/bb2_brain/intent.py` — `AVOIDED_TERMS` 제거, `normalize_terms`/`classify_query`에 `avoid_map` 인자 추가.
- Modify: `scripts/bb2_brain/router.py` — `_avoid_corrections()` 헬퍼 추가, `answer()`에서 map 구축 후 `classify_query(query, avoid_map)` 주입.
- Modify: `scripts/bb2_brain/tests/test_intent.py` — 3 콜사이트 갱신(보정 필요한 2곳에 avoid_map 주입) + 신규 1(빈 map=무보정).
- Modify: `scripts/bb2_brain/tests/test_router.py` — `build_store` fixture L131 `avoided_terms→avoid` rename, anchor 테스트 주석 갱신, 신규 1(보정 출처가 glossary임을 증명 = 하드코딩 제거 anti-regression).

object-model §11.2는 이미 `avoid`로 정의됨 — spec 변경 불필요. g11b design(역사적 dated 문서)은 건드리지 않음.

---

## Task 1: intent.py 시그니처 일반화 + 하드코딩 제거

**Files:** Modify `scripts/bb2_brain/intent.py`, Test `scripts/bb2_brain/tests/test_intent.py`

- [ ] **Step 1: test_intent.py 갱신(실패 유도)** — 3 콜사이트를 신규 시그니처로 고치고 신규 무보정 테스트 추가.

```python
import unittest

from scripts.bb2_brain.intent import classify_query, normalize_terms


class IntentTest(unittest.TestCase):
    def test_normalizes_avoided_popup_term(self):
        normalized = normalize_terms("5.5 기준 시작팝업 QA 기준이 뭐야?", {"시작팝업": "입장팝업"})
        self.assertIn("입장팝업", normalized.canonical_query)
        self.assertIn("시작팝업", normalized.avoided_terms)

    def test_no_correction_with_empty_avoid_map(self):
        # 빈 map → 보정 없음. intent.py 하드코딩 AVOIDED_TERMS 제거 증명(단위 레벨).
        normalized = normalize_terms("시작팝업 QA 기준이 뭐야?", {})
        self.assertNotIn("입장팝업", normalized.canonical_query)
        self.assertEqual(normalized.avoided_terms, [])

    def test_decomposes_mixed_why_and_current_status(self):
        result = classify_query("5.5 기준 시작팝업 QA 기준이 왜 바뀌었고 현재 상태는 뭐야?", {"시작팝업": "입장팝업"})
        self.assertEqual(result.intents, ["why_changed", "current_status"])

    def test_classifies_code_location(self):
        result = classify_query("EntryPopupController 어디서 구현돼 있어?")
        self.assertEqual(result.intents, ["implementation_location"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인** — Run test_intent. Expected FAIL: `normalize_terms()`/`classify_query()`가 2번째 인자를 안 받음(TypeError) 또는 하드코딩 의존.

- [ ] **Step 3: intent.py 구현** — `AVOIDED_TERMS` 상수 제거, 시그니처에 `avoid_map` 추가.

```python
def normalize_terms(query: str, avoid_map: dict[str, str] | None = None) -> NormalizedQuery:
    avoid_map = avoid_map or {}
    canonical = query
    avoided: list[str] = []
    for avoided_term, canonical_term in avoid_map.items():
        if avoided_term in canonical:
            avoided.append(avoided_term)
            canonical = canonical.replace(avoided_term, canonical_term)
    return NormalizedQuery(original_query=query, canonical_query=canonical, avoided_terms=avoided)


def classify_query(query: str, avoid_map: dict[str, str] | None = None) -> ClassifiedQuery:
    normalized = normalize_terms(query, avoid_map)
    text = normalized.canonical_query
    ...  # 이하 intent 분류 로직 무변경
```

- [ ] **Step 4: 통과 확인** — Run test_intent. Expected PASS (4 tests).

---

## Task 2: router가 GlossaryTerm.avoid에서 보정 map 구축·주입

**Files:** Modify `scripts/bb2_brain/router.py`, Test `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: test_router 갱신(실패 유도 + anti-regression 신규)**
  - `build_store`의 `term_popup_enter`(현 L124~135) `"avoided_terms": ["시작팝업"]` → `"avoid": ["시작팝업"]` rename.
  - anchor 테스트 `test_avoided_term_query_routes_through_canonical_to_scope`(현 L646) 주석 `# avoid는 아직 미사용 — ...` → `# G11d: 이 avoid가 정규화 출처(intent.py 하드코딩 제거됨)`로 갱신.
  - 신규 anti-regression 테스트 추가(보정이 glossary 데이터에서만 나옴 = 하드코딩 제거 증명):

```python
    def test_avoid_correction_sourced_from_glossary_not_hardcoded(self):
        # 글로서리에 "시작팝업"을 avoid로 선언한 term이 없으면 보정이 일어나지 않아야 한다.
        # intent.py 하드코딩 AVOIDED_TERMS가 남아 있으면 이 테스트는 실패한다.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/facts/enter.json", {
            "id": "fact.enter", "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact",
            "scope": {"project": "bb2-client", "release": "5.5", "surface": "PopupEnter"},
            "valid_from": "2026-05-26T00:00:00+09:00", "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("시작팝업 현재 규칙 뭐야?")
        self.assertEqual(answer["canonical_query"], "시작팝업 현재 규칙 뭐야?")
        self.assertFalse(any("보정" in w for w in answer["warnings"]))
```

- [ ] **Step 2: 실패 확인** — Run test_router. Expected FAIL: anchor 테스트(시작팝업→입장팝업 보정이 안 일어나 fact.continue 미배제) + anti-regression 테스트(하드코딩이 살아 있으면 보정 발생).

- [ ] **Step 3: router.py 구현**
  - `_avoid_corrections()` 헬퍼 추가(`_reviewed_by_kind` 근처):

```python
    def _avoid_corrections(self) -> dict[str, str]:
        corrections: dict[str, str] = {}
        for term in self._reviewed_by_kind("GlossaryTerm"):
            canonical = term.get("term")
            if not canonical:
                continue
            for avoided in term.get("avoid") or []:
                corrections[avoided] = canonical
        return corrections
```

  - `answer()` 진입부(현 L22~23) `classified = classify_query(query)` 앞에 map 구축, 호출에 주입:

```python
    def answer(self, query: str) -> dict:
        avoid_map = self._avoid_corrections()
        classified = classify_query(query, avoid_map)
        canonical = classified.normalized.canonical_query
        ...  # 이하 무변경 (canonical 라우팅·보정 공시 G11c 그대로)
```

- [ ] **Step 4: 통과 확인** — Run test_router. Expected PASS. anchor 테스트가 이제 **glossary 데이터로** green(하드코딩 제거 후에도 동작 보존 = parity 증명).

---

## Task 3: 전체 회귀 + 커밋

- [ ] **Step 1: 전체 스위트** — Run 4 모듈. Expected 45 tests PASS (기존 43 + test_intent 1 + test_router 1).
- [ ] **Step 2: 잔존 하드코딩 grep** — `rg "AVOIDED_TERMS" scripts/bb2_brain/` 결과 0 확인.
- [ ] **Step 3: 커밋**

```bash
git add scripts/bb2_brain/intent.py scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_intent.py scripts/bb2_brain/tests/test_router.py
git commit -m "refactor: source BB2 Brain term correction from GlossaryTerm.avoid (G11d)"
```

---

## Self-Review

**Spec coverage:** object-model §11.2 `avoid` 필드를 보정 출처로 채택(Task 2). 시그니처 일반화(Task 1). 하드코딩 제거(Task 1 Step 3). `avoided_terms→avoid` fixture rename(Task 2 Step 1). test_intent 갱신(Task 1). g11b §58이 명시한 4개 항목 전부 커버.

**Behavior preservation:** parity anchor `test_avoided_term_query_routes_through_canonical_to_scope`는 하드코딩 시절 green이었고, 출처 스왑 후에도 동일 fixture(`avoid:["시작팝업"]`)로 green 유지. anti-regression 신규 테스트가 "glossary 미선언 시 무보정"을 단언해 하드코딩 잔존을 차단. 회귀 0 — 기존 쿼리 중 "시작팝업" 토큰을 가진 건 anchor/correction-disclosure 2개뿐이고 둘 다 fixture에 `avoid` 선언이 있어 동작 동일.

**Naming collision 가드:** 신규 인자 `avoid_map`(dict). `NormalizedQuery.avoided_terms`(출력 list) 무변경. `GlossaryTerm.avoid`(JSON) 무변경. build_store inert `avoided_terms`는 `avoid`로 rename되어 코드가 실제 소비. 세 의미 분리 유지.

**Type consistency:** `avoid_map: dict[str,str] | None = None`. `_avoid_corrections() -> dict[str,str]`. `classify_query(query, avoid_map)` 위치 인자. intent 분류 로직·출력 dict 무변경.

**Edge cases:** 두 term이 같은 avoided 문자열 선언 → dict 마지막 승(fixture에 없음, P0 허용, 한계로 기록). `term` 없는 GlossaryTerm → skip(가드). `avoid` 없는 term → skip(`or []`).

**Surgical:** 4파일, 전부 G11d 직접 연결. intent 분류 로직·G11c canonical wiring·scope 헬퍼 무변경. 역사적 g11b spec 미수정.
