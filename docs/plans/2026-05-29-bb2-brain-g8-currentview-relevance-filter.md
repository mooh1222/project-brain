# BB2 Brain G8 — CurrentView 관련성 필터 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `current_status` intent에서 CurrentView를 `source_fact_ids` 관련성으로 필터해, 현재 query에 매칭된 current fact를 가리키지 않는 무관 view를 candidate에서 제외한다.

**Architecture:** spec L116 "matching view_type"은 query→view_type 매핑 알고리즘을 명시하지 않았고, 단어 매칭("QA"→qa_status)은 acceptance question "현재 QA 기준 동작"의 "QA"가 qa_status인지 feature의 QA 상태인지 구분 불가해 비결정론적이다. CurrentView 스키마에는 scope/feature 필드도 없다(object-model L328-343) → query와 view를 잇는 결정론적 단서는 `source_fact_ids`뿐. 따라서 **view.source_fact_ids ∩ (query 매칭 current fact ids)** 가 비지 않은 view만 관련 view로 본다(spec L134 "share source object IDs"). G7 stale 감지는 전체 reviewed view 무결성으로 유지하고, G8은 candidate 노출만 관련 view로 좁힌다.

**Tech Stack:** Python 3, unittest, `scripts/bb2_brain/router.py` + 기존 G7 헬퍼.

---

## 설계 결정과 근거

| 결정 | 내용 | 근거 |
|---|---|---|
| 관련성 기준 | `view.source_fact_ids` ∩ (query로 매칭된 current fact ids) 비지 않으면 관련 | spec §6.1 L134 "Do not broaden to unrelated view_type unless they share source object IDs". CurrentView에 scope 필드 부재(object-model L328-343) → source_fact_ids가 유일한 결정론적 연결고리 |
| view_type 단어 매칭 기각 | query 텍스트 "QA"/"구현" 단어로 view_type 추론 안 함 | acceptance "현재 QA 기준 동작"의 "QA"가 qa_status 의도인지 feature의 QA상태인지 단어로 구분 불가 + 비결정론적. dump handoff retrieval order("current views for candidate discovery, then load source objects")와도 source 기반이 일치 |
| **G7↔G8 분리** | G7 stale = 전체 reviewed view 무결성(불변). G8 candidate = 관련 view만 | stale은 데이터 무결성 신호(query 무관하게 유효), candidate는 query 응답 구성(관련만). 목적이 다름 |
| closed/missing/non-reviewed view | source fact가 현재 매칭 fact가 아니면(닫힘/부재/미검수로 current에서 빠짐) → 무관 → candidate 제외. G7 stale 경고는 별도로 유지 | G8 필터의 직접 귀결. 기존 G7 테스트 `_source_fact_closed`의 candidate assert(stale view도 candidate 유지)는 G8 규칙으로 반전됨 |
| **범위 밖(의도적 제외)** | view_type 표시/우선순위, 여러 view 동률 정렬, scope(release/surface) 필터 | view_type 표시는 Tier 3. scope 필터는 G9 영역. fixture가 단일 view라 동률 정렬 불필요(YAGNI) |

> G7 테스트 수정은 회귀가 아니라 규칙 진화다: G7은 "view stale 감지", G8은 candidate 구성을 관련 view로 좁히면서 closed-only view가 candidate에서 빠진다. stale 경고(G7 핵심)는 그대로 유지된다.

## File Structure

- Modify: `scripts/bb2_brain/router.py` — `current_status` 분기 재배열(facts 먼저 계산) + `_views_for_current_facts` 헬퍼 추가
- Test: `scripts/bb2_brain/tests/test_router.py` — G8 신규 1개 + 기존 G7 테스트 2개 candidate assert 조정

---

### Task 1: source_fact_ids 관련성으로 CurrentView candidate 필터

**Files:**
- Modify: `scripts/bb2_brain/router.py` current_status 분기(L34-42) + `_stale_view_warnings`(L108-121) 뒤에 헬퍼 추가
- Test: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: 테스트 작성(신규) + 기존 G7 테스트 2개 수정**

신규 — `RouterTest`에 추가:

```python
    def test_current_status_includes_currentview_sharing_current_fact(self):
        router = QueryRouter(self.build_store())
        answer = router.answer("5.5 기준 입장팝업 현재 QA 기준은 뭐야?")
        # view.source_fact_ids=["fact.current-rule"]이 현재 매칭 fact와 겹침 → 관련 → candidate
        self.assertIn("view.stage-clear-token.current", answer["candidate_object_ids"])

    def test_current_status_excludes_currentview_with_no_current_source_fact(self):
        store = self.build_store()
        # source가 닫힌 fact만 → 현재 fact 아님 → 무관 view
        store.get("view.stage-clear-token.current")["source_fact_ids"] = ["fact.old-rule"]
        router = QueryRouter(store)
        answer = router.answer("5.5 기준 입장팝업 현재 QA 기준은 뭐야?")
        self.assertNotIn("view.stage-clear-token.current", answer["candidate_object_ids"])
```

기존 `test_current_status_marks_view_stale_when_source_fact_closed` — candidate assert를 **반전**(assertIn → assertNotIn):

```python
    def test_current_status_marks_view_stale_when_source_fact_closed(self):
        store = self.build_store()
        store.get("view.stage-clear-token.current")["source_fact_ids"] = ["fact.old-rule"]
        router = QueryRouter(store)
        answer = router.answer("5.5 기준 입장팝업 현재 QA 기준은 뭐야?")
        stale = [w for w in answer["warnings"] if "stale" in w]
        self.assertTrue(
            any("view.stage-clear-token.current" in w and "fact.old-rule" in w for w in stale)
        )
        # G8: closed fact는 현재 fact 아님 → view 무관 → candidate 제외 (G7 stale 경고는 유지)
        self.assertNotIn("view.stage-clear-token.current", answer["candidate_object_ids"])
```

기존 `test_current_status_marks_view_stale_when_source_fact_missing` — candidate 제외 assert **추가**:

```python
    def test_current_status_marks_view_stale_when_source_fact_missing(self):
        store = self.build_store()
        store.get("view.stage-clear-token.current")["source_fact_ids"] = ["fact.ghost"]
        router = QueryRouter(store)
        answer = router.answer("5.5 기준 입장팝업 현재 QA 기준은 뭐야?")
        self.assertTrue(
            any("fact.ghost" in w and "stale" in w for w in answer["warnings"])
        )
        # G8: 부재 fact는 현재 fact 아님 → view 무관 → candidate 제외
        self.assertNotIn("view.stage-clear-token.current", answer["candidate_object_ids"])
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && python3 -m unittest scripts.bb2_brain.tests.test_router -v`
Expected: `_excludes_...` 신규 + 수정된 `_closed`/`_missing`의 candidate assert가 FAIL (현재는 무관 view도 candidate에 들어감). `_includes_...`는 PASS.

- [ ] **Step 3: current_status 분기 재배열 + 헬퍼 추가**

`router.py` current_status 분기(L34-42)를 아래로 교체 — facts를 먼저 계산하고, stale은 전체 view, candidate는 관련 view만:

```python
            elif intent == "current_status":
                facts = self._current_facts(query)
                all_views = self._reviewed_by_kind("CurrentView")
                warnings.extend(self._stale_view_warnings(all_views))
                relevant_views = self._views_for_current_facts(all_views, facts)
                candidate_ids.extend(view["id"] for view in relevant_views)
                for fact in facts:
                    source_ids.append(fact["id"])
                    claim_statuses.append(claim_status(fact, raw_available=self._raw_available_for(fact), restricted=False))
                sections.append({"intent": intent, "object_ids": [fact["id"] for fact in facts], "summary": "Current reviewed facts"})
```

`_stale_view_warnings`(L108-121) 바로 뒤에 헬퍼 추가:

```python
    def _views_for_current_facts(self, views: list[dict], facts: list[dict]) -> list[dict]:
        fact_ids = {fact["id"] for fact in facts}
        return [view for view in views if set(view.get("source_fact_ids", [])) & fact_ids]
```

- [ ] **Step 4: 실행해서 통과 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && python3 -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store -v`
Expected: 전체 PASS (G8 신규 1 + 수정 2 + 기존 회귀 없음, 총 27 tests).

확인 포인트:
- `test_current_status_uses_fact_truth_not_current_view_truth`(기존 L148): view가 fact.current-rule 가리킴 → 관련 → candidate 유지, 통과
- `test_why_changed_returns_event_before_current_status`: current_status 분기 거쳐도 event source assert 무관, 통과

- [ ] **Step 5: 커밋**

```bash
cd /Users/al03040455/Desktop/bb2_client
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: filter BB2 Brain CurrentView candidates by current-fact relevance"
```

---

## Self-Review

**1. Spec coverage:**
- §6.1 L116 "CurrentView with matching view_type" → query 매칭 current fact를 공유하는 view만 candidate(view_type 단어 대신 source 공유로 매칭)
- §6.1 L134 "Do not broaden to unrelated view_type unless they share source object IDs" → `source_fact_ids ∩ fact_ids` 교집합 필터로 직접 구현
- object-model L328-343 (CurrentView scope 필드 부재) → source_fact_ids 채택 근거
- G7(stale) 보존: `_stale_view_warnings(all_views)` 전체 view 유지
- 제외 범위(view_type 표시, scope 필터/G9, 동률 정렬)는 결정 표에 근거와 함께 명시

**2. Placeholder scan:** 없음. 모든 step에 실제 코드/명령/예상 출력.

**3. Type consistency:** `_views_for_current_facts(self, views: list[dict], facts: list[dict]) -> list[dict]`. `fact_ids`는 set comprehension. `set(view.get("source_fact_ids", [])) & fact_ids` 교집합. 기존 `_current_facts`/`_reviewed_by_kind`/`_stale_view_warnings` 시그니처와 일관. fixture id(`view.stage-clear-token.current`/`fact.current-rule`/`fact.old-rule`/`fact.ghost`)는 build_store와 일치.

**4. G7↔G8 회귀 점검:** 기존 G7 테스트 4개 중 `_no_stale_warning`/`_not_reviewed`는 candidate assert 없어 영향 없음. `_closed`/`_missing`은 candidate assert를 G8 규칙(무관 view 제외)으로 조정(stale 경고 assert는 유지). 이는 candidate 구성 규칙 변경의 의도된 귀결.
