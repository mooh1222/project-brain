# BB2 Brain G6 — why_changed 인과 모델(supersession 사슬 + qa_result 규칙 + inference 라벨) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** why_changed 분기가 변경의 "원인"을 spec §6.2 규칙대로 모델링한다 — event에 연결된 TemporalFact의 supersedes 사슬로 before→after를 보이고(L145), qa_result는 후속 변경을 유발했을 때만 원인으로 분류하며(L154), 원인이 복수 event 추론이면 inference로 라벨한다(L153).

**Architecture:** `scripts/bb2_brain/router.py`의 `why_changed` 분기에 두 헬퍼(`_facts_derived_from`, `_event_role`)를 추가하고, 분기 본문이 reviewed event 외에 그 event들에서 `derived_from_event_id`로 파생된 reviewed TemporalFact를 함께 로드한다. fact별 before 값은 기존 `_supersedes_reachable`(스칼라 사슬 walk, cycle/missing 가드)를 재사용해 구한다. qa_result 원인 판정은 "변경된 fact가 그 qa_result에서 직접 파생됐는가"(`derived_from_event_id == qa_result.id`)라는 결정론적 신호만 쓴다(텍스트매칭 없음, 기존 스키마만 사용 — 5번/G5 충돌해소 철학 계승). inference 라벨은 section 단위 `causal_basis`로, deriving event가 정확히 1개(또는 event가 1개)면 `stated`, 아니면 `inferred`.

**Tech Stack:** Python 3, `unittest`. 게임 런타임과 분리된 `scripts/bb2_brain/` 프로토타입.

**설계 근거(권위):** spec §6.2 (`docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md` L138-L155), object-model §6.4 EventLedgerRecord / §6.5 TemporalFact (`docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md` L213-L300, fact↔event 연결=`derived_from_event_id`, before/after=`supersedes` 스칼라). 두 핵심 분기는 사용자 결정(2026-06-01): (1) qa_result 원인 신호 = "변경 fact 직접 파생", (2) supersession 사슬·qa_result 규칙·inference 라벨을 한 게이트로. 실데이터 anchor = 슬랙 `p1779766838001279`(입장팝업 공간 이슈 → 표시 변경, 깜박임 다음 단계만) — G4가 쓴 동일 스레드 확장.

**검증 명령(전 구간):**
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store
```

---

## File Structure

- **Modify** `scripts/bb2_brain/router.py`
  - 새 헬퍼 `_facts_derived_from(self, event_ids: set[str]) -> list[dict]` (이미 있는 `_reviewed_by_kind` 옆, 예: `_facts_derived_from`는 `_scoped_facts`/`_current_facts` 근방 L319 부근).
  - 새 헬퍼 `_event_role(self, event: dict, deriving_event_ids: set[str]) -> str`.
  - `answer()`의 `if intent == "why_changed":` 분기 본문(현재 L61-L83) 확장.
  - 책임: why_changed가 event chronology + fact before/after + 원인/보조 분류 + 추론 라벨을 한 section에 합성.
- **Modify** `scripts/bb2_brain/tests/test_router.py`
  - 헬퍼 단위 테스트 2개.
  - why_changed 통합 테스트(qa_result cause / qa_result supporting / supersession before-after / build_store 통합).
  - 기존 `test_why_changed_returns_multiple_events_ordered_and_separated`(L716)에 inferred 단언 추가.
  - `build_store()` fixture의 `fact.current-rule`에 `derived_from_event_id` 추가(현재 코드의 displayRule fact가 space-pressure 해명 event에서 파생됐다는 실제 관계 반영).

새 객체 타입·필드·스키마 변경 없음. spec/object-model 무변경(순수 라우팅 구현, G10과 동일 성격). 모든 신규 필드는 answer section 내부 출력 dict 키(`role`, `fact_changes`, `causal_basis`)로, 추가만 하므로 기존 단언은 additive-safe.

---

## Task 1: `_facts_derived_from` 헬퍼

주어진 event 집합에서 `derived_from_event_id`로 파생된 **reviewed** TemporalFact만 반환한다. 미검수(open) fact와 다른 event에서 파생된 fact는 제외.

**Files:**
- Modify: `scripts/bb2_brain/router.py` (`_reviewed_by_kind` 아래, L196 근방)
- Test: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`scripts/bb2_brain/tests/test_router.py`의 헬퍼 테스트 클래스(파일 끝 `_reviewed_fact` 헬퍼가 있는 클래스, L937 근방) 또는 새 메서드로 추가:

```python
    def test_facts_derived_from_returns_only_reviewed_linked_facts(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/ledger/ev_a.json", {
            "id": "event.a", "kind": "EventLedgerRecord", "status": "reviewed",
            "truth_role": "event", "event_type": "spec_revised",
            "happened_at": "2026-05-20T00:00:00+09:00", "summary": "x", "evidence_refs": [],
        })
        write_object(root, "objects/facts/linked.json", {
            "id": "fact.linked", "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact", "subject": "s", "predicate": "uses", "value": "new",
            "scope": {}, "valid_from": "2026-05-20T00:00:00+09:00",
            "derived_from_event_id": "event.a", "evidence_refs": [],
        })
        write_object(root, "objects/facts/unreviewed.json", {
            "id": "fact.unreviewed", "kind": "TemporalFact", "status": "open",
            "truth_role": "fact", "subject": "s", "predicate": "uses", "value": "x",
            "scope": {}, "valid_from": "2026-05-20T00:00:00+09:00",
            "derived_from_event_id": "event.a", "evidence_refs": [],
        })
        write_object(root, "objects/facts/other.json", {
            "id": "fact.other", "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact", "subject": "s", "predicate": "uses", "value": "y",
            "scope": {}, "valid_from": "2026-05-20T00:00:00+09:00",
            "derived_from_event_id": "event.not-loaded", "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        result = router._facts_derived_from({"event.a"})
        self.assertEqual([f["id"] for f in result], ["fact.linked"])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -k test_facts_derived_from_returns_only_reviewed_linked_facts -v`
Expected: FAIL — `AttributeError: 'QueryRouter' object has no attribute '_facts_derived_from'`

- [ ] **Step 3: 최소 구현**

`scripts/bb2_brain/router.py`에서 `_reviewed_by_kind`(L194-195) 바로 아래에 추가:

```python
    def _facts_derived_from(self, event_ids: set[str]) -> list[dict]:
        """주어진 event들에서 파생된 reviewed TemporalFact. fact는 derived_from_event_id로
        자신을 만든 event를 가리킨다(object-model §6.5). 미검수 fact·다른 event 파생 fact는 제외."""
        return [
            fact for fact in self._reviewed_by_kind("TemporalFact")
            if fact.get("derived_from_event_id") in event_ids
        ]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -k test_facts_derived_from_returns_only_reviewed_linked_facts -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: G6 _facts_derived_from — event에서 파생된 reviewed fact 로드 (§6.2 L145)"
```

---

## Task 2: `_event_role` 헬퍼

event의 원인/보조 역할을 판정한다. qa_result는 fact를 파생했을 때만(=후속 규칙/구현 변경을 유발) `cause`, 아니면 `supporting_context`. 그 외 event_type은 §6.2 읽기순서상 rationale 자체이므로 항상 `cause`. 순수 로직(store 비의존)이라 직접 호출로 테스트한다.

**Files:**
- Modify: `scripts/bb2_brain/router.py`
- Test: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
    def test_event_role_qa_result_is_cause_only_when_it_derived_a_fact(self):
        router = QueryRouter(self.build_store())  # store는 무관(순수 로직)
        qa = {"id": "event.qa", "event_type": "qa_result"}
        spec = {"id": "event.spec", "event_type": "spec_revised"}
        # qa_result가 fact를 파생한 경우(deriving 집합에 포함) → cause
        self.assertEqual(router._event_role(qa, {"event.qa"}), "cause")
        # qa_result가 아무 fact도 파생 안 함 → supporting_context
        self.assertEqual(router._event_role(qa, set()), "supporting_context")
        # qa_result 외 event는 항상 cause
        self.assertEqual(router._event_role(spec, set()), "cause")
```

이 테스트는 `build_store`/`QueryRouter`를 쓰는 메인 라우터 테스트 클래스(L17 `build_store`가 정의된 클래스)에 추가한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -k test_event_role_qa_result_is_cause_only_when_it_derived_a_fact -v`
Expected: FAIL — `AttributeError: 'QueryRouter' object has no attribute '_event_role'`

- [ ] **Step 3: 최소 구현**

`_facts_derived_from` 아래에 추가:

```python
    def _event_role(self, event: dict, deriving_event_ids: set[str]) -> str:
        """qa_result는 reviewed fact를 파생(후속 규칙/구현 변경을 유발)했을 때만 'cause',
        아니면 'supporting_context'(§6.2 L154). 그 외 event_type은 §6.2 읽기순서상
        rationale 자체이므로 'cause'."""
        if event.get("event_type") == "qa_result":
            return "cause" if event["id"] in deriving_event_ids else "supporting_context"
        return "cause"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -k test_event_role_qa_result_is_cause_only_when_it_derived_a_fact -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: G6 _event_role — qa_result는 변경 유발 시에만 원인 (§6.2 L154)"
```

---

## Task 3: why_changed 분기 확장 — fact_changes + role + causal_basis

두 헬퍼를 써서 why_changed section에 `fact_changes`(before→after), event별 `role`, section `causal_basis`(stated/inferred)와 경고를 추가한다. 통합 테스트 4개를 먼저 작성(실패)한 뒤 분기를 한 번에 재작성한다.

**Files:**
- Modify: `scripts/bb2_brain/router.py` (`answer()` L61-L83 why_changed 분기)
- Modify: `scripts/bb2_brain/tests/test_router.py` (신규 통합 테스트 3개 + 기존 multi-event 테스트 L716 확장)

- [ ] **Step 1: 실패하는 통합 테스트 작성**

메인 라우터 테스트 클래스에 신규 3개 추가:

```python
    def test_why_changed_shows_supersession_before_after(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/ledger/clarify.json", {
            "id": "event.clarify", "kind": "EventLedgerRecord", "status": "reviewed",
            "truth_role": "event", "event_type": "spec_clarified",
            "happened_at": "2026-05-26T00:00:00+09:00",
            "summary": "표시 방식 개편", "evidence_refs": [],
        })
        write_object(root, "objects/facts/new_rule.json", {
            "id": "fact.new", "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact", "subject": "displayRule", "predicate": "uses",
            "value": "drawEventCluster", "scope": {}, "valid_from": "2026-05-26T00:00:00+09:00",
            "supersedes": "fact.old", "derived_from_event_id": "event.clarify", "evidence_refs": [],
        })
        write_object(root, "objects/facts/old_rule.json", {
            "id": "fact.old", "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact", "subject": "displayRule", "predicate": "uses",
            "value": "separate icons", "scope": {}, "valid_from": "2026-05-01T00:00:00+09:00",
            "valid_until": "2026-05-26T00:00:00+09:00", "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("표시가 왜 바뀌었어?")
        self.assertEqual(answer["intents"], ["why_changed"])
        section = answer["sections"][0]
        self.assertEqual(section["fact_changes"], [{
            "fact_id": "fact.new",
            "subject": "displayRule",
            "predicate": "uses",
            "before_value": "separate icons",
            "after_value": "drawEventCluster",
            "derived_from_event_id": "event.clarify",
        }])
        self.assertEqual(section["causal_basis"], "stated")  # deriving event 1개

    def test_why_changed_qa_result_that_changed_rule_is_cause(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        # 실데이터 anchor: 슬랙 p1779766838001279 "깜박임 다음 단계만"
        write_object(root, "objects/ledger/qa_blink.json", {
            "id": "event.qa-blink", "kind": "EventLedgerRecord", "status": "reviewed",
            "truth_role": "event", "event_type": "qa_result",
            "happened_at": "2026-05-26T10:00:00+09:00",
            "summary": "QA: 깜박임이 전체 단계 아이콘에 적용돼 혼란 → 다음 단계만 깜박이도록 변경",
            "evidence_refs": [],
        })
        write_object(root, "objects/facts/blink_new.json", {
            "id": "fact.blink-new", "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact", "subject": "effectBlinkRule", "predicate": "uses",
            "value": "blink_only_next_stage", "scope": {}, "valid_from": "2026-05-26T10:00:00+09:00",
            "supersedes": "fact.blink-old", "derived_from_event_id": "event.qa-blink", "evidence_refs": [],
        })
        write_object(root, "objects/facts/blink_old.json", {
            "id": "fact.blink-old", "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact", "subject": "effectBlinkRule", "predicate": "uses",
            "value": "blink_all_stages", "scope": {}, "valid_from": "2026-05-01T00:00:00+09:00",
            "valid_until": "2026-05-26T10:00:00+09:00", "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("깜박임 규칙이 왜 바뀌었어?")
        section = answer["sections"][0]
        roles = {e["id"]: e["role"] for e in section["events"]}
        self.assertEqual(roles["event.qa-blink"], "cause")
        self.assertEqual(section["causal_basis"], "stated")
        self.assertEqual(section["fact_changes"][0]["before_value"], "blink_all_stages")
        self.assertEqual(section["fact_changes"][0]["after_value"], "blink_only_next_stage")

    def test_why_changed_qa_result_without_change_is_supporting_context(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/ledger/qa_observe.json", {
            "id": "event.qa-observe", "kind": "EventLedgerRecord", "status": "reviewed",
            "truth_role": "event", "event_type": "qa_result",
            "happened_at": "2026-05-20T09:00:00+09:00",
            "summary": "QA: 표시 영역이 좁다는 관찰(조치 없음)", "evidence_refs": [],
        })
        write_object(root, "objects/ledger/spec_revise.json", {
            "id": "event.spec-revise", "kind": "EventLedgerRecord", "status": "reviewed",
            "truth_role": "event", "event_type": "spec_revised",
            "happened_at": "2026-05-22T00:00:00+09:00",
            "summary": "표시 방식 개편(기획 개정)", "evidence_refs": [],
        })
        write_object(root, "objects/facts/changed.json", {
            "id": "fact.changed", "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact", "subject": "displayRule", "predicate": "uses",
            "value": "drawEventCluster", "scope": {}, "valid_from": "2026-05-22T00:00:00+09:00",
            "derived_from_event_id": "event.spec-revise", "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("표시가 왜 바뀌었어?")
        section = answer["sections"][0]
        roles = {e["id"]: e["role"] for e in section["events"]}
        self.assertEqual(roles["event.qa-observe"], "supporting_context")
        self.assertEqual(roles["event.spec-revise"], "cause")
        self.assertEqual(section["causal_basis"], "stated")  # deriving event 1개(spec-revise)
        self.assertTrue(any("보조 맥락" in w for w in answer["warnings"]))

    def test_why_changed_two_direct_changes_stay_stated(self):
        # deriving event 2개: 두 변경이 각자 자기 event에서 직접 파생 → 둘 다 직접 명시이므로
        # stated(추론 아님). "deriving==1만 stated" 규칙이었으면 잘못 inferred로 갔을 케이스.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/ledger/ev1.json", {
            "id": "event.e1", "kind": "EventLedgerRecord", "status": "reviewed",
            "truth_role": "event", "event_type": "spec_clarified",
            "happened_at": "2026-05-20T00:00:00+09:00", "summary": "규칙 A 변경", "evidence_refs": [],
        })
        write_object(root, "objects/ledger/ev2.json", {
            "id": "event.e2", "kind": "EventLedgerRecord", "status": "reviewed",
            "truth_role": "event", "event_type": "spec_clarified",
            "happened_at": "2026-05-21T00:00:00+09:00", "summary": "규칙 B 변경", "evidence_refs": [],
        })
        write_object(root, "objects/facts/fa.json", {
            "id": "fact.a", "kind": "TemporalFact", "status": "reviewed", "truth_role": "fact",
            "subject": "ruleA", "predicate": "uses", "value": "a2", "scope": {},
            "valid_from": "2026-05-20T00:00:00+09:00", "derived_from_event_id": "event.e1", "evidence_refs": [],
        })
        write_object(root, "objects/facts/fb.json", {
            "id": "fact.b", "kind": "TemporalFact", "status": "reviewed", "truth_role": "fact",
            "subject": "ruleB", "predicate": "uses", "value": "b2", "scope": {},
            "valid_from": "2026-05-21T00:00:00+09:00", "derived_from_event_id": "event.e2", "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("규칙이 왜 바뀌었어?")
        section = answer["sections"][0]
        self.assertEqual(section["causal_basis"], "stated")
        self.assertEqual(len(section["fact_changes"]), 2)
        self.assertFalse(any("추론" in w for w in answer["warnings"]))
```

기존 `test_why_changed_returns_multiple_events_ordered_and_separated`(L716) 끝(L759 `self.assertEqual([e["event_type"] ...)` 단언 다음)에 추가:

```python
        # G6: 3개 event, 파생 fact 0개 → 원인이 복수 event에서 추론됨(inferred)
        self.assertEqual(section["causal_basis"], "inferred")
        self.assertEqual(section["fact_changes"], [])
        self.assertTrue(any("추론" in w for w in answer["warnings"]))
        # qa_result 없으므로 전원 cause
        self.assertEqual({e["role"] for e in section["events"]}, {"cause"})
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -k why_changed -v`
Expected: 신규 4개 + 확장된 multi-event 테스트가 `KeyError: 'fact_changes'` / `KeyError: 'causal_basis'` / `KeyError: 'role'`로 FAIL. 기존 `test_why_changed_returns_event_before_current_status` 등은 PASS.

- [ ] **Step 3: why_changed 분기 재작성**

`scripts/bb2_brain/router.py`의 `if intent == "why_changed":` 분기(현재 L61-L83) 전체를 아래로 교체:

```python
            if intent == "why_changed":
                # §6.2: 변경 이력은 단일 event가 아니라 happened_at 순 복수 event다.
                # G4: spec_revised(기획 원문)/spec_clarified(슬랙)를 event_type 인라인으로 분리.
                # G6: (1) event에서 파생된 TemporalFact의 supersedes 사슬로 before→after(L145),
                #     (2) qa_result는 후속 변경을 유발했을 때만 원인(L154),
                #     (3) 원인이 복수 event 추론이면 causal_basis=inferred로 라벨(L153).
                events = sorted(
                    self._reviewed_by_kind("EventLedgerRecord"),
                    key=lambda e: e.get("happened_at", ""),
                )
                if events:
                    happened = {e["id"]: e.get("happened_at", "") for e in events}
                    event_ids = set(happened)
                    derived = sorted(
                        self._facts_derived_from(event_ids),
                        key=lambda f: (happened[f["derived_from_event_id"]], f["id"]),
                    )
                    deriving_event_ids = {f["derived_from_event_id"] for f in derived}
                    event_details = []
                    for event in events:
                        source_ids.append(event["id"])
                        claim_statuses.append(claim_status(event, raw_available=self._raw_available_for(event), restricted=False))
                        event_details.append({
                            "id": event["id"],
                            "event_type": event.get("event_type"),
                            "summary": event.get("summary", ""),
                            "role": self._event_role(event, deriving_event_ids),
                        })
                    fact_changes = []
                    for fact in derived:
                        source_ids.append(fact["id"])
                        claim_statuses.append(claim_status(fact, raw_available=self._raw_available_for(fact), restricted=False))
                        reached = self._supersedes_reachable(fact)
                        before_value = self.store.get(reached[0]).get("value") if reached else None
                        fact_changes.append({
                            "fact_id": fact["id"],
                            "subject": fact.get("subject"),
                            "predicate": fact.get("predicate"),
                            "before_value": before_value,
                            "after_value": fact.get("value"),
                            "derived_from_event_id": fact["derived_from_event_id"],
                        })
                    # 변경이 event에서 직접 파생됐으면(deriving event가 하나라도 있으면) 원인이
                    # 직접 명시된 것 = stated. 파생 fact가 하나도 없고 event가 복수면, 원인을
                    # event 나열에서 읽어 추론한 것 = inferred(L153). event 1개면 그 event가 직접 명시.
                    causal_basis = "inferred" if (not deriving_event_ids and len(events) >= 2) else "stated"
                    if causal_basis == "inferred":
                        warnings.append("원인이 단일 event로 직접 명시되지 않음 — 복수 event에서 추론(inference)")
                    for ev in event_details:
                        if ev["event_type"] == "qa_result" and ev["role"] == "supporting_context":
                            warnings.append(f"{ev['id']}: qa_result는 후속 변경을 직접 유발하지 않아 보조 맥락(원인 아님)")
                    sections.append({
                        "intent": intent,
                        "object_ids": [e["id"] for e in events],
                        "events": event_details,
                        "fact_changes": fact_changes,
                        "causal_basis": causal_basis,
                        "summary": "Change rationale (chronological)",
                    })
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -k why_changed -v`
Expected: 신규 3개 + multi-event 포함 전부 PASS.

- [ ] **Step 5: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: G6 why_changed 인과 모델 — fact_changes/role/causal_basis (§6.2 L145·L153·L154)"
```

---

## Task 4: build_store fixture 정합 + 통합 단언

build_store의 displayRule fact(`fact.current-rule`)는 실제로 space-pressure 해명 event(`event.space-pressure`, spec_clarified)에서 파생됐다. 이 관계를 fixture에 반영(`derived_from_event_id` 추가)하면 canonical 예제의 why_changed가 before→after를 보인다. 기존 why 단언은 멤버십(`assertIn`) 기반이라 영향 없음.

**Files:**
- Modify: `scripts/bb2_brain/tests/test_router.py` (`build_store` L31-L44 `fact.current-rule` + 신규 통합 테스트)

- [ ] **Step 1: 실패하는 통합 테스트 작성**

메인 라우터 테스트 클래스에 추가:

```python
    def test_why_changed_build_store_shows_displayrule_before_after(self):
        router = QueryRouter(self.build_store())
        answer = router.answer("입장팝업 표시가 왜 바뀌었어?")
        section = answer["sections"][0]
        self.assertEqual(section["intent"], "why_changed")
        changes = {f["fact_id"]: f for f in section["fact_changes"]}
        self.assertIn("fact.current-rule", changes)
        self.assertEqual(changes["fact.current-rule"]["before_value"], "separate event icons")
        self.assertEqual(changes["fact.current-rule"]["after_value"], "drawEventCluster")
        self.assertEqual(section["causal_basis"], "stated")
        # G6 후 why-only 쿼리에도 파생 fact가 source로 들어옴(provenance 고정)
        self.assertIn("fact.current-rule", answer["source_object_ids"])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -k test_why_changed_build_store_shows_displayrule_before_after -v`
Expected: FAIL — `fact.current-rule`이 `derived_from_event_id` 없어 fact_changes에 안 들어옴 → `AssertionError: 'fact.current-rule' not found`.

- [ ] **Step 3: fixture에 derived_from_event_id 추가**

`scripts/bb2_brain/tests/test_router.py` `build_store`의 `fact.current-rule` 객체(L31-L44)에서 `"supersedes": "fact.old-rule",` 줄 다음에 한 줄 추가:

```python
            "supersedes": "fact.old-rule",
            "derived_from_event_id": "event.space-pressure",
```

- [ ] **Step 4: 테스트 통과 확인 (회귀 포함)**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -v`
Expected: 신규 테스트 PASS + 기존 `test_why_changed_returns_event_before_current_status`, `test_stage_clear_token_acceptance_answer`, `test_why_changed_missing_raw_bundle_is_raw_unavailable` 전부 PASS (모두 멤버십 단언이라 fact_changes 추가에 영향 없음. raw-unavailable 테스트는 manifest.slack만 누락 → event.space-pressure가 raw-unavailable, current-rule은 manifest.spec로 reviewed, max-severity = raw-unavailable 유지).

- [ ] **Step 5: 커밋**

```bash
git add scripts/bb2_brain/tests/test_router.py
git commit -m "test: G6 build_store displayRule fact를 space-pressure event 파생으로 정합 + before/after 통합 단언"
```

---

## Task 5: 전 구간 검증

- [ ] **Step 1: 4개 테스트 모듈 전체 실행**

Run:
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store
```
Expected: `OK` — 기존 63개 + 신규(헬퍼 2 + 통합 5) = 70개 전후 전부 통과. 실패 0.

- [ ] **Step 2: 신규 동작 수동 점검(선택)**

위 통합 테스트가 (1) before→after, (2) qa_result cause/supporting 분리, (3) stated/inferred 라벨을 모두 커버하는지 재확인. 누락된 spec §6.2 규칙 없는지 대조: L145(supersession 사슬)=Task 3 fact_changes / L153(inference)=causal_basis / L154(qa_result)=role. L152(spec/clarification 비뭉개기)=G4 event_type 인라인(기 구현) / L155(raw-only)=기존 raw-unavailable 경로(무변경).

---

## Self-Review

**1. Spec coverage (§6.2 read order + rules):**
- 읽기순서 1 (reviewed EventLedgerRecord 로드) → 기존 + Task 3 유지.
- 읽기순서 2 (TemporalFact supersession 사슬, event 연결) → Task 1 `_facts_derived_from` + Task 3 `fact_changes`(before via `_supersedes_reachable`). ✓ (L145)
- 읽기순서 3-5 (EvidenceRef/Manifest/CurrentView) → 범위 밖. CurrentView "final summary only"는 why_changed가 view를 cause로 안 쓰는 현 동작과 일치(무변경). EvidenceRef 사슬 표면화는 evidence_provenance 의도(④에서 처리). 본 게이트 비대상 — 의도적.
- 규칙 L152 (spec/clarification 비뭉개기) → G4 `event_type` 인라인으로 기 충족.
- 규칙 L153 (복수 event 추론 = inference) → Task 3 `causal_basis`. ✓
- 규칙 L154 (qa_result 조건부 원인) → Task 2 `_event_role` + Task 3 role/warning. ✓
- 규칙 L155 (reviewed event 없이 raw만 = raw-only) → 기존 raw-unavailable/`needs_clarification` 경로 무변경(why-only에서 event 없으면 section 미생성 → source 비어 needs_clarification). 본 게이트 미변경 — 의도적.

**2. Placeholder scan:** 모든 step에 실제 코드/명령/기대출력 포함. "적절히 처리" 류 없음. ✓

**3. Type consistency:** `_facts_derived_from(event_ids: set[str])` ↔ Task 3 호출부 `event_ids = set(happened)` 일치. `_event_role(event, deriving_event_ids: set[str])` ↔ 호출부 `deriving_event_ids = {f["derived_from_event_id"] for f in derived}` 일치. `_supersedes_reachable(fact) -> list[str]`(기존 L273) → `reached[0]`로 직접 선행 fact id 접근. section 키 `events`/`fact_changes`/`causal_basis`/`role` 신규, 기존 `object_ids`/`summary`/`intent` 유지.

**경계(범위 밖, 의도적):**
- supersession 사슬은 직접 선행(`reached[0]`)의 value만 before로 노출. 2단계 이상 과거 전체 타임라인은 as_of_history(§6.3) 소관 — why_changed는 "왜 지금 값이 됐나"의 직전 대비.
- qa_result 원인 신호는 직접 파생만. QA→decision→fact 간접 인과(related_objects 경유)는 사용자 결정으로 비채택 — 실데이터에서 직접파생이 못 잡는 사슬이 관측되면 재방문(5번 recency 거절과 동일 패턴: 결정론 우선, 휴리스틱 보류).
- qa_result가 파생한 fact가 아직 reviewed로 승격되기 전(open 상태)이면 cause로 잡히지 않고 supporting_context가 된다. `_facts_derived_from`이 reviewed fact만 보기 때문 — 미검수는 아직 truth가 아니므로 의도된 동작이다. 그 fact가 reviewed가 되는 순간 cause로 전환된다. 실데이터에서 "변경을 유발했는데 보조 맥락으로 표시"가 보이면 결함이 아니라 이 경계다(critic 검토 major 1).
- cause 판정의 정확도는 `derived_from_event_id`를 적재 때 옳게 채웠는지에 전적으로 의존한다. 단순 관찰만 한 qa_result는 fact를 파생하지 않아야 supporting_context로 분류된다(object-model §6.4: event 하나가 반드시 fact를 만들 필요는 없다). 관찰만 했는데 fact를 잘못 파생시켜 cause로 잡히는 건 적재 단계(Phase 3 이후) 책임이다(critic 검토 major 2).

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-01-bb2-brain-g6-why-changed-causality.md`.**

이 task의 확립된 프로세스는 **subagent-driven TDD (구현 sonnet / 리뷰 opus xhigh 2스테이지: spec 적합 → 품질 holistic)**. 실행 전 설계 패스(critic 리뷰)로 dead-step/엣지케이스를 한 번 더 거른다(5번에서 B-tier dead-step을 plan 단계에서 잡은 선례).
