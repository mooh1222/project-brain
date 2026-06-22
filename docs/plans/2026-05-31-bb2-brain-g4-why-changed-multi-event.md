# BB2 Brain G4 — why_changed 복수 event 로드 + spec/clarification 분리

> REQUIRED SUB-SKILL: superpowers:test-driven-development.

**Goal:** why_changed가 reviewed `EventLedgerRecord`를 **전부**(현재 `events[0]` 단일) `happened_at` 오름차순으로 로드하고, event별 claim_status를 붙이며, 출력에서 spec/clarification을 **분리**(§6.2 L152 "Do not collapse 'source spec said X' and 'later clarification changed Y'", 인수 §14 "어느 쪽이 근거인지 분리")한다.

**Architecture:** why_changed 분기에서 (1) `_reviewed_by_kind("EventLedgerRecord")`를 `happened_at` 키로 정렬, (2) 각 event를 source_ids + claim_status에 추가, (3) 섹션에 `events: [{id, event_type, summary}]`(정렬순) 인라인 노출 + `object_ids`(정렬순). event_type 노출이 spec_revised(기획 원문) vs spec_clarified(슬랙 clarification) 분리를 구조적으로 가능케 함. 라우터는 raw event_type만 노출하고 "기획 원문/clarification" 레이블링은 렌더러 몫(결정론 라우팅 유지).

**범위 경계:** G4 = 복수 로드 + 분리까지. **qa_result-as-cause 규칙(§6.2 L154)·복수이벤트 인과 추론 레이블(§6.2 L153)은 task Phase2 ⑥(별도 게이트)** — G4 아님. supersession chain(§6.2 read-order 2)도 G4 범위 밖(현 단순 로드 유지, 후속).

**실데이터 출처:** Slack thread `p1779766838001279`(입장팝업 요정의선물/해피블록 표시 변경 문의) — 인수 §14 step3 clarification의 실제 출처. 근본이유=공간 이슈로 해피블록 블럭모양→버프정보. clarification 다수(깜박임 다음단계만/플라워포인트 UI삭제/보스모드 다음단계+깜박임). fixture는 이 중 대표 spec_revised 1 + spec_clarified 2로 멀티이벤트·분리 검증.

**Tech Stack:** Python 3, unittest, `scripts/bb2_brain/`.

---

## Conventions

- 테스트: `cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store`
- 현재 baseline: 45 tests.
- 커밋 대상: `scripts/bb2_brain/` (코드만, git 추적).

## File Structure

- Modify: `scripts/bb2_brain/router.py` — why_changed 분기(현 L40~46).
- Modify: `scripts/bb2_brain/tests/test_router.py` — 신규 멀티이벤트 분리 테스트(전용 fixture).

build_store 기존 `event.space-pressure`는 건드리지 않음(surgical, 기존 why_changed 테스트 assertIn이라 호환). 단 그 event의 `spec_clarified` 타입은 사실 spec-level 내용 → 별도 cleanup 후보로만 기록(이 게이트 비포함).

---

## Task 1: why_changed 복수 event + 분리

- [ ] **Step 1: 실패 테스트** (test_router, 전용 tempdir fixture — spec_revised 1 + spec_clarified 2, happened_at 비순차 배치)

```python
    def test_why_changed_returns_multiple_events_ordered_and_separated(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        # 일부러 파일/삽입 순서를 happened_at 역순으로 둬 정렬 검증
        write_object(root, "objects/ledger/clarify_flowerpoint.json", {
            "id": "event.clarify-flowerpoint", "kind": "EventLedgerRecord", "status": "reviewed",
            "truth_role": "event", "event_type": "spec_clarified",
            "happened_at": "2026-05-26T16:20:00+09:00",
            "summary": "플라워 포인트: 표시 UI 삭제 (요정의 선물과 동일하게 미표시)",
            "evidence_refs": [],
        })
        write_object(root, "objects/ledger/clarify_happyblock.json", {
            "id": "event.clarify-happyblock", "kind": "EventLedgerRecord", "status": "reviewed",
            "truth_role": "event", "event_type": "spec_clarified",
            "happened_at": "2026-05-26T16:00:00+09:00",
            "summary": "해피블록: 블럭 모양 진행단계 표시 불가(공간 이슈) → 버프 정보 표시로 변경",
            "evidence_refs": [],
        })
        write_object(root, "objects/ledger/spec_revised.json", {
            "id": "event.spec-revised", "kind": "EventLedgerRecord", "status": "reviewed",
            "truth_role": "event", "event_type": "spec_revised",
            "happened_at": "2026-05-20T00:00:00+09:00",
            "summary": "5.5 스테이지클리어토큰이 입장팝업 start 버튼 우측 영역 차지 → 이벤트 표시 공간 압박, 표시 방식 개편",
            "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("입장팝업 요정의선물/해피블록 표시가 왜 바뀌었어?")
        self.assertEqual(answer["intents"], ["why_changed"])
        # 복수 event 전부 로드
        for eid in ["event.spec-revised", "event.clarify-happyblock", "event.clarify-flowerpoint"]:
            self.assertIn(eid, answer["source_object_ids"])
        section = answer["sections"][0]
        self.assertEqual(section["intent"], "why_changed")
        # happened_at 오름차순 (spec 먼저, clarification 나중)
        self.assertEqual(
            [e["id"] for e in section["events"]],
            ["event.spec-revised", "event.clarify-happyblock", "event.clarify-flowerpoint"],
        )
        # spec/clarification 분리: event_type 인라인 노출
        self.assertEqual(
            [e["event_type"] for e in section["events"]],
            ["spec_revised", "spec_clarified", "spec_clarified"],
        )
```

- [ ] **Step 2: 실패 확인** — 현재 `events[0]`만 → clarify/flowerpoint가 source에 없음 + section에 `events` 키 없음 → FAIL.

- [ ] **Step 3: 구현** (router.py why_changed 분기)

```python
            if intent == "why_changed":
                events = sorted(
                    self._reviewed_by_kind("EventLedgerRecord"),
                    key=lambda e: e.get("happened_at", ""),
                )
                if events:
                    event_details = []
                    for event in events:
                        source_ids.append(event["id"])
                        claim_statuses.append(claim_status(event, raw_available=self._raw_available_for(event), restricted=False))
                        event_details.append({
                            "id": event["id"],
                            "event_type": event.get("event_type"),
                            "summary": event.get("summary", ""),
                        })
                    sections.append({
                        "intent": intent,
                        "object_ids": [e["id"] for e in events],
                        "events": event_details,
                        "summary": "Change rationale (chronological)",
                    })
```

- [ ] **Step 4: 통과 확인**

- [ ] **Step 5: 전체 회귀** — 46 tests(45+1) PASS. 기존 why_changed 테스트(build_store 1 event)는 정렬 trivial + `events`/`object_ids` 정렬순이라 assertIn·sections[0].intent 그대로 통과. missing-raw 테스트도 event별 claim_status라 동일.

- [ ] **Step 6: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: load all why_changed events ordered + separate spec/clarification (G4 §6.2)"
```

---

## Self-Review

**Spec coverage:** §6.2 read-order 1(복수 EventLedgerRecord 로드 = Step 3 정렬+전수) / L152(분리 = event_type 인라인 + object_ids 정렬) / 인수 §14 step4("각 clarification을 EventLedgerRecord로"). read-order 2(supersession)·L153(추론 레이블)·L154(qa_result 규칙)은 명시적으로 G4 범위 밖(Phase2 ⑥).

**회귀:** build_store 1 event → 정렬·전수가 단일 원소라 기존 동작 동일. why_changed 테스트는 assertIn/sections[0].intent만 단언 → section schema에 `events` 추가·summary 변경 무영향(어떤 테스트도 why_changed 섹션 summary/object_ids 정확 단언 안 함, 확인 필요).

**Type:** `events` 정렬 key `happened_at`(ISO8601 문자열, lexicographic=chronological). `event_details` list[dict]. claim_status 시그니처 무변경.

**Surgical:** why_changed 분기만. 다른 intent·G11 wiring·scope 헬퍼 무변경. build_store stale event 비수정(cleanup 후보 기록만).
