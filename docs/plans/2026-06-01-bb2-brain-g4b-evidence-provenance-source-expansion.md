# BB2 Brain ④ — evidence_provenance 소스 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `evidence_provenance` 분기가 사실(TemporalFact)만 defend하던 것을, 질의에 함께 분류된 의도가 가리키는 source object(EventLedgerRecord / CodeLocator / GlossaryTerm·DomainContext / TemporalFact)의 출처 사슬까지 defend하도록 확장한다.

**Architecture:** object-model BrainObjectBase가 모든 객체에 `evidence_refs` + `review_record_id?`를 부여하므로(L100-101), 사실에 쓰던 체인워크(review_record_id + evidence_refs → manifest, `claim_status`)를 4종에 **그대로** 적용한다. 선택 규칙은 "정밀"(사용자 결정 2026-06-01): evidence 분기가 `classified.intents`의 co-occurring 의도별로 defend 대상을 재수집(각 의도 collector 재사용 → 루프 디커플 유지, order-independent). 단독 evidence는 `_scoped_facts` fallback(기존 동작 보존). CurrentView 출처(§6.6 L232)는 이번 범위 제외.

**Tech Stack:** Python, unittest. `scripts/bb2_brain/`.

**근거:** query-routing §6.6(read order 1 = "source object being defended: TemporalFact, EventLedgerRecord, CodeLocator, or GlossaryTerm"; rules = restricted→restricted / reviewed+raw 없음→raw-unavailable / EvidenceRef 없으면 fabricate 금지), §5(mixed-intent = decomposition, 각 의도 독립 답형태). 선택 규칙은 spec 공백 → 설계 패스에서 "정밀" 확정(task 작업이력 2026-06-01).

**설계 결정(정밀, AskUserQuestion):** evidence가 어느 종류를 defend할지 = 함께 온 의도가 결정. why_changed→EventLedgerRecord, implementation_location→CodeLocator, glossary_meaning→DomainContext+GlossaryTerm, current_status→`_current_facts`, as_of_history→`_scoped_facts`. **단독 evidence(`intents=={evidence_provenance}`)만 `_scoped_facts` fallback** = 기존 테스트 2건 보존. (포괄=과다노출 / 최소=단독 변경근거 미포착 → 기각.)

---

### Task 1: evidence_provenance 분기를 co-intent 기반 소스 수집으로 확장

**Files:**
- Modify: `scripts/bb2_brain/router.py:116-128` (evidence_provenance 분기)
- Test: `scripts/bb2_brain/tests/test_router.py` (신규 테스트 3건 append)

**기존 테스트(회귀 가드, 유지)**: `test_evidence_provenance_surfaces_review_and_evidence_chain`("입장팝업 규칙의 근거가 뭐야?" 단독 evidence → 사실의 review+ref), `test_evidence_provenance_restricted_when_redaction`(단독 evidence → 비공개 manifest → restricted). 둘 다 단독이라 fallback 경로 = 기존 동작.

- [ ] **Step 1: 실패 테스트 3건 작성**

`test_router.py` 끝에 append:

```python
    def test_evidence_with_why_changed_defends_event_provenance(self):
        router = QueryRouter(self.build_store())
        answer = router.answer("입장팝업 표시가 왜 바뀌었고 근거는?")
        self.assertIn("why_changed", answer["intents"])
        self.assertIn("evidence_provenance", answer["intents"])
        # evidence가 변경 사건(event)의 출처 사슬을 defend → 사건의 evidence ref가 surface
        self.assertIn("ref.slack", answer["source_object_ids"])

    def test_evidence_with_implementation_location_defends_locator_provenance(self):
        router = QueryRouter(self.build_store())
        answer = router.answer("drawEventCluster 어디 구현됐고 근거는?")
        self.assertIn("implementation_location", answer["intents"])
        self.assertIn("evidence_provenance", answer["intents"])
        # evidence가 코드 위치(locator)의 출처 사슬을 defend → locator의 evidence ref가 surface
        self.assertIn("ref.code", answer["source_object_ids"])

    def test_evidence_with_glossary_defends_glossary_provenance(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/domain/term.json", {
            "id": "term.flower-point",
            "kind": "GlossaryTerm",
            "status": "reviewed",
            "truth_role": "reference",
            "term": "플라워포인트",
            "definition": "요정의 선물 랭킹 포인트.",
            "review_record_id": "review.term.flower-point",
            "evidence_refs": ["ref.term"],
        })
        write_object(root, "objects/reviews/review_term.json", {
            "id": "review.term.flower-point",
            "kind": "ReviewRecord",
            "status": "reviewed",
            "truth_role": "reference",
            "subject_id": "term.flower-point",
            "decision": "approved",
            "evidence_refs": [],
        })
        write_object(root, "objects/evidence_refs/ref_term.json", {
            "id": "ref.term",
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "summary": "Glossary term reference",
            "evidence_manifest_id": "manifest.term",
            "evidence_refs": [],
        })
        write_object(root, "objects/raw/manifest_term.json", {
            "id": "manifest.term",
            "kind": "EvidenceManifest",
            "status": "reviewed",
            "truth_role": "source",
            "redaction_status": "approved",
            "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("플라워포인트 무슨 뜻이고 근거는?")
        self.assertIn("glossary_meaning", answer["intents"])
        self.assertIn("evidence_provenance", answer["intents"])
        # evidence가 용어의 출처 사슬을 defend → 용어의 review record + evidence ref가 surface
        # (glossary_meaning 분기는 용어 id만 추가하고 review/ref 사슬은 추가하지 않음)
        self.assertIn("review.term.flower-point", answer["source_object_ids"])
        self.assertIn("ref.term", answer["source_object_ids"])
```

테스트 의도:
- 1(why+근거): 변경 사건의 출처(`ref.slack`)는 why_changed 분기가 안 내놓음(event id만 추가). evidence가 사건을 defend해야 surface. **pre-④엔 evidence가 `_scoped_facts`만 봐서 `ref.slack` 부재 → 실패.**
- 2(impl+근거): locator의 출처(`ref.code`)도 implementation_location 분기는 안 내놓음. evidence가 locator를 defend해야 surface. **pre-④ 부재 → 실패.**
- 3(glossary+근거): glossary_meaning 분기는 용어 id만 추가, review/ref 사슬은 안 함. evidence가 용어를 defend해야 `review.term.flower-point`+`ref.term` surface. 전용 fixture(사실 0개 → pre-④ fallback `_scoped_facts`는 빈 결과라 사슬 부재 → 실패).

- [ ] **Step 2: 실패 확인**

Run:
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_evidence_with_why_changed_defends_event_provenance scripts.bb2_brain.tests.test_router.RouterTest.test_evidence_with_implementation_location_defends_locator_provenance scripts.bb2_brain.tests.test_router.RouterTest.test_evidence_with_glossary_defends_glossary_provenance -v
```
Expected: 3건 FAIL — 각 `assertIn`이 `ref.slack` / `ref.code` / `review.term.flower-point` 부재로 실패.

- [ ] **Step 3: evidence_provenance 분기 구현**

`router.py:116-128` 분기를 아래로 교체:

```python
            elif intent == "evidence_provenance":
                # 정밀 규칙(§6.6): 함께 분류된 의도가 가리키는 source object의 출처 사슬만 defend.
                # 각 의도 collector를 재사용해 재수집하므로 루프 순서와 무관하다.
                # 단독 evidence(다른 의도 없음)는 scope 매칭 사실로 fallback(기존 동작 보존).
                intents_present = set(classified.intents)
                sources: list[dict] = []
                if "why_changed" in intents_present:
                    sources.extend(self._reviewed_by_kind("EventLedgerRecord"))
                if "implementation_location" in intents_present:
                    sources.extend(self._reviewed_by_kind("CodeLocator"))
                if "glossary_meaning" in intents_present:
                    sources.extend(self._reviewed_by_kind("DomainContext"))
                    sources.extend(self._reviewed_by_kind("GlossaryTerm"))
                if "current_status" in intents_present:
                    sources.extend(self._current_facts(canonical))
                if "as_of_history" in intents_present:
                    sources.extend(self._scoped_facts(canonical))
                if intents_present == {"evidence_provenance"}:
                    sources = self._scoped_facts(canonical)
                section_ids: list[str] = []
                seen: set[str] = set()
                for obj in sources:
                    if obj["id"] in seen:
                        continue
                    seen.add(obj["id"])
                    section_ids.append(obj["id"])
                    review_id = obj.get("review_record_id")
                    if review_id and self.store.has(review_id):
                        section_ids.append(review_id)
                    for ref_id in obj.get("evidence_refs", []):
                        if self.store.has(ref_id):
                            section_ids.append(ref_id)
                    claim_statuses.append(claim_status(obj, raw_available=self._raw_available_for(obj), restricted=self._restricted_for(obj)))
                source_ids.extend(section_ids)
                sections.append({"intent": intent, "object_ids": section_ids, "summary": "Evidence provenance"})
```

변경 핵심: `for fact in self._scoped_facts(canonical)` 단일 소스를, `intents_present` 기반 다종 소스 수집으로 교체. 체인워크 본체(review_record_id + evidence_refs + claim_status)는 동일하되 `fact`→`obj`로 일반화 + `seen` dedup. 단독 evidence는 `intents_present == {"evidence_provenance"}` 분기로 `_scoped_facts` 유지.

- [ ] **Step 4: 신규 3건 + 기존 evidence 회귀 가드 통과 확인**

Run:
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_evidence_with_why_changed_defends_event_provenance scripts.bb2_brain.tests.test_router.RouterTest.test_evidence_with_implementation_location_defends_locator_provenance scripts.bb2_brain.tests.test_router.RouterTest.test_evidence_with_glossary_defends_glossary_provenance scripts.bb2_brain.tests.test_router.RouterTest.test_evidence_provenance_surfaces_review_and_evidence_chain scripts.bb2_brain.tests.test_router.RouterTest.test_evidence_provenance_restricted_when_redaction -v
```
Expected: 신규 3 + 기존 2(단독 evidence) 전부 PASS.

- [ ] **Step 5: 전체 스위트 회귀 확인**

Run:
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store
```
Expected: `OK`, 52 tests(49 + 신규 3).

- [ ] **Step 6: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: evidence_provenance defends co-intent source objects (§6.6)"
```

---

## Self-Review

**Spec coverage:** §6.6 read order 1(4종 source object defend) — Task 1이 why→Event / impl→Code / glossary→Glossary+DomainContext / current·as_of→Fact로 구현. §6.6 rules(restricted/raw-unavailable/EvidenceRef 없으면 fabricate 금지)는 `claim_status` + `store.has` 가드로 기존 보존. §5 decomposition — evidence가 다른 의도 결과를 재수집(독립 collector)하므로 분리 유지. CurrentView 출처(L232)는 사용자 결정으로 범위 제외(별도 항목).

**Placeholder scan:** 없음. 모든 코드/명령 실체 포함.

**Type consistency:** `_reviewed_by_kind(str)`/`_current_facts(canonical)`/`_scoped_facts(canonical)`/`claim_status(obj,*,raw_available,restricted)`/`_raw_available_for`/`_restricted_for` — 전부 기존 시그니처 재사용. `classified.intents`는 `ClassifiedQuery.intents: list[str]`. 단독 판정 `intents_present == {"evidence_provenance"}`로 기존 단독 테스트 경로 보존.
