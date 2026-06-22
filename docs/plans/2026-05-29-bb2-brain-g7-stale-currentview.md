# BB2 Brain G7 — Stale CurrentView 감지·표시 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `current_status` intent에서 CurrentView가 reviewed TemporalFact와 불일치하면 view를 stale로 감지·경고한다.

**Architecture:** CurrentView는 truth가 아니라 `source_fact_ids`로 source를 가리키는 synthesis(합성물)다. value 같은 진리 필드가 없어 직접 비교가 불가능하므로, **stale 판정은 `source_fact_ids` 무결성 검사**로 결정론적으로 구현한다. router는 이미 fact를 truth로 쓰고 view는 candidate로만 둔다(test L148). G7은 거기에 stale 경고만 더한다 — 답변 truth 경로는 바뀌지 않는다.

**Tech Stack:** Python 3, unittest, `scripts/bb2_brain/router.py` + `store.py` 기존 구조.

---

## 설계 결정과 근거 (spec 직결 + 비자명 분기 명시)

| 결정 | 내용 | 근거 |
|---|---|---|
| 판정 기준 | `CurrentView.source_fact_ids` 무결성만 | CurrentView fixture에 `value` 등 truth 필드 없음 → 텍스트 `summary` 직접 비교 비결정론적. spec §6.1 L128 "synthesis of already verified source object IDs", L132 "summary map, not independent truth" |
| stale 조건 3종 | ① source fact **부재**(dangling) ② source fact **미검수**(status≠reviewed) ③ source fact **닫힘**(`valid_until` 설정=superseded) | spec §6.1 L133 "CurrentView and reviewed facts disagree → prefer fact, mark view stale". ③이 전형적 "disagree"(fact가 superseded됐는데 view 미갱신) |
| 표시 방식 | 기존 `warnings` 리스트에 view id + 사유 포함 문자열 추가 | implementation_location 분기(router.py L55/L58)가 이미 동일 패턴. 별도 필드 신설은 YAGNI |
| view 유지 | stale여도 `candidate_object_ids`에서 제거 안 함 | spec "mark view stale" = 제거가 아닌 표시 |
| **범위 밖(비자명, 의도적 제외)** | `source_event_ids` 무결성 / 누락 current fact 감지(scope 매칭) | event 무결성은 spec이 "reviewed **facts** disagree"로 fact 명시 → Tier 3 후보. 누락 current fact는 view↔fact scope 매칭 필요 → task가 분리해 둔 **G9(스코프 필터)** 영역 |

> 비자명 분기 2건(event 무결성, 누락 current fact)은 task의 G7/G8/G9 경계에 따라 G7에서 제외. 설계 리뷰 시 이의 있으면 조정.

## File Structure

- Modify: `scripts/bb2_brain/router.py` — `_stale_view_warnings` 헬퍼 추가 + `current_status` 분기에 1줄 통합
- Test: `scripts/bb2_brain/tests/test_router.py` — stale 시나리오 4개 추가

`store.py`는 변경 없음. `BrainStore.get()`이 dict 참조를 반환하므로 테스트는 fixture mutate로 stale 상태를 만든다.

---

### Task 1: CurrentView source_fact_ids 무결성 기반 stale 감지

**Files:**
- Modify: `scripts/bb2_brain/router.py:34-41` (current_status 분기), 헬퍼는 `_current_facts` 뒤(L106 근처)에 추가
- Test: `scripts/bb2_brain/tests/test_router.py` (RouterTest 클래스에 메서드 추가)

- [ ] **Step 1: 실패 테스트 4개 작성**

`scripts/bb2_brain/tests/test_router.py`의 `RouterTest` 클래스에 추가:

```python
    def test_current_status_no_stale_warning_when_source_fact_open_and_reviewed(self):
        router = QueryRouter(self.build_store())
        answer = router.answer("5.5 기준 입장팝업 현재 QA 기준은 뭐야?")
        stale = [w for w in answer["warnings"] if "stale" in w]
        self.assertEqual(stale, [])

    def test_current_status_marks_view_stale_when_source_fact_closed(self):
        store = self.build_store()
        store.get("view.stage-clear-token.current")["source_fact_ids"] = ["fact.old-rule"]
        router = QueryRouter(store)
        answer = router.answer("5.5 기준 입장팝업 현재 QA 기준은 뭐야?")
        stale = [w for w in answer["warnings"] if "stale" in w]
        self.assertTrue(
            any("view.stage-clear-token.current" in w and "fact.old-rule" in w for w in stale)
        )
        self.assertIn("view.stage-clear-token.current", answer["candidate_object_ids"])

    def test_current_status_marks_view_stale_when_source_fact_missing(self):
        store = self.build_store()
        store.get("view.stage-clear-token.current")["source_fact_ids"] = ["fact.ghost"]
        router = QueryRouter(store)
        answer = router.answer("5.5 기준 입장팝업 현재 QA 기준은 뭐야?")
        self.assertTrue(
            any("fact.ghost" in w and "stale" in w for w in answer["warnings"])
        )

    def test_current_status_marks_view_stale_when_source_fact_not_reviewed(self):
        store = self.build_store()
        store.get("fact.current-rule")["status"] = "candidate"
        router = QueryRouter(store)
        answer = router.answer("5.5 기준 입장팝업 현재 QA 기준은 뭐야?")
        self.assertTrue(
            any("fact.current-rule" in w and "stale" in w for w in answer["warnings"])
        )
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && python3 -m unittest scripts.bb2_brain.tests.test_router -v`
Expected: 3개 신규 stale 테스트 FAIL (warnings에 stale 없음). `no_stale_warning` 테스트는 PASS(현재도 warning 미생성).

- [ ] **Step 3: 헬퍼 추가 + current_status 분기 통합**

`scripts/bb2_brain/router.py` current_status 분기(L34-41)를 수정 — `warnings.extend` 1줄 추가:

```python
            elif intent == "current_status":
                views = self._reviewed_by_kind("CurrentView")
                candidate_ids.extend(view["id"] for view in views)
                warnings.extend(self._stale_view_warnings(views))
                facts = self._current_facts(query)
                for fact in facts:
                    source_ids.append(fact["id"])
                    claim_statuses.append(claim_status(fact, raw_available=self._raw_available_for(fact), restricted=False))
                sections.append({"intent": intent, "object_ids": [fact["id"] for fact in facts], "summary": "Current reviewed facts"})
```

`_current_facts`(L105-106) 뒤에 헬퍼 추가:

```python
    def _stale_view_warnings(self, views: list[dict]) -> list[str]:
        messages: list[str] = []
        for view in views:
            for fact_id in view.get("source_fact_ids", []):
                if not self.store.has(fact_id):
                    messages.append(f"{view['id']}: source fact {fact_id} 부재, view stale")
                    continue
                fact = self.store.get(fact_id)
                if fact.get("status") != "reviewed":
                    messages.append(f"{view['id']}: source fact {fact_id} 미검수, view stale")
                elif fact.get("valid_until"):
                    messages.append(f"{view['id']}: source fact {fact_id} 닫힘(superseded), view stale")
        return messages
```

- [ ] **Step 4: 실행해서 통과 확인**

Run: `cd /Users/al03040455/Desktop/bb2_client && python3 -m unittest scripts.bb2_brain.tests.test_router -v`
Expected: 신규 4개 포함 전체 PASS (Tier 1 회귀 없음, 총 26 tests).

- [ ] **Step 5: 커밋**

```bash
cd /Users/al03040455/Desktop/bb2_client
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: detect stale BB2 Brain CurrentView via source fact integrity"
```

---

## Self-Review

**1. Spec coverage:**
- §6.1 L133 "disagree → mark view stale" → Task 1 stale 조건 ③(닫힘) + 표시
- §9 L282 "Stale current view → prefer fact, mark stale" → fact truth 경로 불변(기존) + 경고 추가
- L335 "stale if it conflicts with reviewed facts" → 무결성 3종
- L132 "summary map, not independent truth" → value 비교 대신 source 무결성 채택 근거
- 제외 범위(event 무결성/누락 fact)는 결정 표에 근거와 함께 명시 — 갭 아닌 의도적 경계.

**2. Placeholder scan:** 없음. 모든 step에 실제 코드/명령/예상 출력.

**3. Type consistency:** `_stale_view_warnings(views: list[dict]) -> list[str]`. `warnings`는 answer() 지역 리스트(router.py L24), `warnings.extend(...)` 일관. `store.has`/`store.get` 시그니처(store.py L23-27) 일치. fixture id `view.stage-clear-token.current`/`fact.current-rule`/`fact.old-rule`는 test_router.py build_store와 일치.
