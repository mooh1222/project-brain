# BB2 Brain ⑤ — §9 충돌 reviewed fact 해소·보고 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 같은 subject+predicate에 reviewed TemporalFact가 둘 이상 동시에 현재 유효(open=`valid_until` 없음)로 남아 있을 때, 라우터가 말없이 하나를 고르거나 무차별 나열하지 않게 한다. `supersedes` 대체 사슬로 자동 해소하고, 못 가르면 충돌 사실을 응답에 드러내 되묻는다(`current_status` 경로 한정).

**Architecture:** 충돌의 1차 묶기는 store 비의존 순수 함수 `_conflicting_fact_groups(facts)`(같은 subject+predicate, open, reviewed, value 상이)로 추출해 런타임(⑤)과 이후 Phase 3a Lint가 공유한다. 해소 사다리는 (A) `supersedes` 사슬 walk → (C) 잔여 보고 2단계다. query 차원으로 좁히는 선택은 이미 G9 candidate 필터(`_scoped_facts`, router.py:232-236)가 끝내므로 충돌 해소에 scope 매칭 단계를 두지 않는다. 보고는 신규 status 라벨 없이 기존 `conflicts`(구조 필드)·`warnings`·`needs_clarification` 채널로만 한다.

**Tech Stack:** Python, unittest. `scripts/bb2_brain/`.

**근거 / 합의:** 설계 권위 = query-routing spec §9(L287) + object-model §6.5(L255-301, 특히 L272 `supersedes?: ObjectId` 스칼라 / L298 No-silent-overwrite 불변조건 / L300 좁은 scope 자동 override 금지). 본 플랜은 ralplan 합의(planner/architect/critic) 산출물 `/tmp/brain_gate5_final_design.md`를 옮긴 것이다. 합의 경로: 라운드1 critic OKAY → 오케스트레이터가 (B) scope-매칭 해소 단계 실행불가(dead code) 결함 발견 → architect 진단 확인(교집합 필터 통과 fact는 query 차원을 전부 동일 만족 → scope 점수 동점) → (B) 제거 → 잔재 정리 → critic 최종 OKAY.

**확정 결정 7개 (합의):**
1. 적용 범위는 `current_status`(`_current_facts`, open fact) 경로만. `as_of_history` 충돌은 defer(intent.py에 as_of 시점 추출 없음 + §6.3 유효구간 필터 미구현 → 별도 게이트).
2. 탐지 키 = `subject + predicate` (open + reviewed + value 상이). scope는 탐지에도 해소에도 두지 않는다 — query 차원 좁히기는 G9 `_scoped_facts` candidate 필터 소관.
3. 해소 사다리 (A) supersedes 사슬 → (C) 보고. (B) scope 매칭 단계 없음(G9가 candidate 단계에서 수행).
4. `supersedes`는 스칼라(`supersedes?: ObjectId`) 정본. test_router.py:41 배열을 스칼라로 정정.
5. Lint 본체는 만들지 않음(Phase 3a). 단 `_conflicting_fact_groups`를 store 비의존 순수 함수로 빼서 3a Lint가 import 가능하게.
6. fact 종류별 차등 해소 안 함(uniform). membase식 recency-priority는 spec rejected-alternatives에 거절 사유 명문화.
7. 보고 채널: (a) `conflicts: [{fact_ids, predicate, values}]` 섹션 필드 항상 + (b) `warnings` 사람용 한 줄(탐지 시 항상) + (c) `needs_clarification=True`는 해소 불가일 때만. 신규 status 라벨 금지.

---

## File Structure

- `scripts/bb2_brain/router.py` — 수정. 모듈 레벨 순수 함수 `_conflicting_fact_groups` 추가, `QueryRouter`에 `_supersedes_reachable`/`_supersedes_winner`/`_resolve_current_conflicts` 추가, `current_status` 분기(L63-77) wiring. `from collections import defaultdict` import 추가.
- `scripts/bb2_brain/tests/test_router.py` — 수정. supersedes fixture 스칼라 정정(L41) + 신규 충돌 테스트 추가.
- `docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md` — §9 rejected-alternatives + §9 L287 (B)=G9 소관 명시.
- `~/Desktop/vault/tasks/active/bb2-brain.md` — L43 "동일 scope" → "겹치는 scope" 문구 정정(작업 이력에서 처리).

**비범위:** `as_of_history` 충돌, `scripts/bb2_brain/lint.py` 본체, 신규 status 라벨, recency-priority 구현.

---

### Task 1: `supersedes` fixture 스칼라 정정 (결정 4)

**Files:**
- Modify: `scripts/bb2_brain/tests/test_router.py:41`

object-model §6.5 L272는 `supersedes?: ObjectId`(스칼라)인데 fixture만 배열이다. `supersedes`를 읽는 런타임 코드는 아직 없으므로(이번 Task 3가 최초 소비) 정정은 기존 동작에 영향 없다.

- [ ] **Step 1: 다른 소비처 없음 확인**

Run: `rg "supersedes" scripts/bb2_brain`
Expected: `test_router.py:41`(fixture)와 본 플랜 신규 코드 외 런타임 소비처 없음. (spec 문서 언급은 무관)

- [ ] **Step 2: fixture 스칼라로 정정**

`scripts/bb2_brain/tests/test_router.py:41`:

```python
            "supersedes": "fact.old-rule",
```

(기존 `"supersedes": ["fact.old-rule"]`에서 배열 → 스칼라)

- [ ] **Step 3: 기존 테스트 전부 green 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store`
Expected: 기존 52 tests PASS (정정 inert — as_of 경로는 supersedes를 읽지 않음).

- [ ] **Step 4: Commit**

```bash
git add scripts/bb2_brain/tests/test_router.py
git commit -m "fix: supersedes fixture를 object-model L272 스칼라로 정정 (G5 준비)"
```

---

### Task 2: 순수 1차 묶기 함수 `_conflicting_fact_groups` (결정 2·5)

**Files:**
- Modify: `scripts/bb2_brain/router.py` (모듈 레벨 함수 추가 + `from collections import defaultdict`)
- Test: `scripts/bb2_brain/tests/test_router.py` (신규 단위 테스트 append)

store에 의존하지 않는 순수 함수. open(`valid_until` 없음)+reviewed인데 같은 `(subject, predicate)`에서 `value`가 2종 이상 갈리는 묶음만 반환. scope·supersedes는 보지 않는다(해소 단계가 처리). Phase 3a Lint가 그대로 import한다.

- [ ] **Step 1: 실패 테스트 작성**

`test_router.py` 끝에 append (모듈 함수 직접 호출 단위 테스트):

```python
    def test_conflicting_fact_groups_pure_helper(self):
        from scripts.bb2_brain.router import _conflicting_fact_groups
        open_a = {"id": "f.a", "subject": "s", "predicate": "uses", "value": "A",
                  "status": "reviewed"}
        open_b = {"id": "f.b", "subject": "s", "predicate": "uses", "value": "B",
                  "status": "reviewed"}
        same_val = {"id": "f.c", "subject": "s", "predicate": "uses", "value": "A",
                    "status": "reviewed"}
        closed = {"id": "f.d", "subject": "s", "predicate": "uses", "value": "C",
                  "status": "reviewed", "valid_until": "2026-05-26T00:00:00+09:00"}
        other_subj = {"id": "f.e", "subject": "z", "predicate": "uses", "value": "Z",
                      "status": "reviewed"}
        candidate = {"id": "f.f", "subject": "s", "predicate": "uses", "value": "X",
                     "status": "candidate"}
        no_subj = {"id": "f.g", "predicate": "uses", "value": "Y", "status": "reviewed"}

        # 충돌: open A vs open B (같은 s/uses, value 상이)
        groups = _conflicting_fact_groups([open_a, open_b])
        self.assertEqual(len(groups), 1)
        self.assertEqual({f["id"] for f in groups[0]}, {"f.a", "f.b"})

        # 같은 value 둘 → 충돌 아님
        self.assertEqual(_conflicting_fact_groups([open_a, same_val]), [])
        # closed 섞임 → open 하나만 남아 충돌 아님
        self.assertEqual(_conflicting_fact_groups([open_a, closed]), [])
        # 다른 subject → 묶이지 않음
        self.assertEqual(_conflicting_fact_groups([open_a, other_subj]), [])
        # candidate 섞임 → reviewed 하나만 → 충돌 아님
        self.assertEqual(_conflicting_fact_groups([open_a, candidate]), [])
        # subject 없음 → 제외
        self.assertEqual(_conflicting_fact_groups([open_a, no_subj]), [])
```

- [ ] **Step 2: 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_conflicting_fact_groups_pure_helper -v`
Expected: FAIL — `ImportError: cannot import name '_conflicting_fact_groups'`.

- [ ] **Step 3: 함수 구현**

`scripts/bb2_brain/router.py` 상단 import에 `from collections import defaultdict` 추가하고, `_SCOPE_TOKEN_RE` 정의 아래(클래스 밖, 모듈 레벨)에 추가:

```python
def _conflicting_fact_groups(facts: list[dict]) -> list[list[dict]]:
    """store 비의존 순수 함수. open(valid_until 없음) + reviewed fact 중
    같은 (subject, predicate)인데 value가 2종 이상 갈리는 묶음만 반환한다.
    scope·supersedes는 보지 않는다(해소 단계가 처리). 런타임(⑤)과 Lint(3a)가 공유."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for fact in facts:
        if fact.get("status") != "reviewed" or fact.get("valid_until"):
            continue
        subject, predicate = fact.get("subject"), fact.get("predicate")
        if subject is None or predicate is None:
            continue
        groups[(subject, predicate)].append(fact)
    result = []
    for members in groups.values():
        values = {repr(m.get("value")) for m in members}
        if len(members) >= 2 and len(values) >= 2:
            result.append(members)
    return result
```

- [ ] **Step 4: 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_conflicting_fact_groups_pure_helper -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: 충돌 1차 묶기 순수 함수 _conflicting_fact_groups (G5 §9, 결정2/5)"
```

---

### Task 3: `supersedes` 사슬 walk + 승자 판정 (해소 A단계, 결정 3·4)

**Files:**
- Modify: `scripts/bb2_brain/router.py` (`QueryRouter`에 `_supersedes_reachable`, `_supersedes_winner` 추가)
- Test: `scripts/bb2_brain/tests/test_router.py`

`supersedes` 사슬 walk은 다른 객체를 id로 조회(store 접근)하므로 `QueryRouter` 메서드로 둔다. cycle 가드(이미 본 id 재방문 중단)와 missing-id 가드(`store.has` 후 `store.get`) 포함.

- [ ] **Step 1: 실패 테스트 작성**

`test_router.py`에 append. 충돌 store를 직접 구성하는 헬퍼 + 단위 테스트:

```python
    def _reviewed_fact(self, fid, value, *, supersedes=None, surface=None):
        scope = {"project": "bb2-client", "release": "5.5"}
        if surface:
            scope["surface"] = surface
        payload = {
            "id": fid, "kind": "TemporalFact", "status": "reviewed",
            "truth_role": "fact", "subject": "conflict.subj", "predicate": "uses",
            "value": value, "scope": scope, "valid_from": "2026-05-26T00:00:00+09:00",
            "evidence_refs": [],
        }
        if supersedes is not None:
            payload["supersedes"] = supersedes
        return payload

    def _conflict_router(self, *fact_payloads):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "brain"
        for payload in fact_payloads:
            write_object(root, f"objects/facts/{payload['id']}.json", payload)
        return QueryRouter(BrainStore.load(root))

    def test_supersedes_winner_picks_survivor(self):
        router = self._conflict_router(
            self._reviewed_fact("fact.win", "A", supersedes="fact.lose"),
            self._reviewed_fact("fact.lose", "B"),
        )
        group = [router.store.get("fact.win"), router.store.get("fact.lose")]
        winner = router._supersedes_winner(group)
        self.assertIsNotNone(winner)
        self.assertEqual(winner["id"], "fact.win")

    def test_supersedes_winner_none_without_link(self):
        router = self._conflict_router(
            self._reviewed_fact("fact.a", "A"),
            self._reviewed_fact("fact.b", "B"),
        )
        group = [router.store.get("fact.a"), router.store.get("fact.b")]
        self.assertIsNone(router._supersedes_winner(group))

    def test_supersedes_reachable_cycle_guard(self):
        router = self._conflict_router(
            self._reviewed_fact("fact.x", "A", supersedes="fact.y"),
            self._reviewed_fact("fact.y", "B", supersedes="fact.x"),
        )
        # cycle이어도 무한 루프 없이 끝남. 서로 dominated → 단일 승자 없음.
        self.assertIsNone(router._supersedes_winner(
            [router.store.get("fact.x"), router.store.get("fact.y")]))

    def test_supersedes_reachable_missing_id_guard(self):
        router = self._conflict_router(
            self._reviewed_fact("fact.x", "A", supersedes="fact.gone"),
            self._reviewed_fact("fact.y", "B"),
        )
        # fact.gone은 store에 없음 → walk이 store.has에서 멈춤, 예외 없음.
        # 둘 중 누구도 상대를 dominate 못 함 → 단일 승자 없음.
        self.assertIsNone(router._supersedes_winner(
            [router.store.get("fact.x"), router.store.get("fact.y")]))
```

- [ ] **Step 2: 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_supersedes_winner_picks_survivor -v`
Expected: FAIL — `AttributeError: 'QueryRouter' object has no attribute '_supersedes_winner'`.

- [ ] **Step 3: 메서드 구현**

`scripts/bb2_brain/router.py`의 `QueryRouter` 클래스에 추가(`_current_facts` 근처):

```python
    def _supersedes_reachable(self, fact):
        """fact가 supersedes 스칼라 사슬로 도달하는 id 목록. cycle/missing-id 가드."""
        reached, visited, current = [], set(), fact
        while True:
            sid = current.get("supersedes")            # 스칼라(결정 4)
            if not sid or sid in visited or not self.store.has(sid):
                break
            visited.add(sid)
            reached.append(sid)
            current = self.store.get(sid)
        return reached

    def _supersedes_winner(self, group):
        """(A) 그룹 안에서 supersedes 사슬로 다른 fact를 대체해 유일하게 남는 fact. 없으면 None."""
        ids_in_group = {f["id"] for f in group}
        dominated = set()
        for fact in group:
            for reached in self._supersedes_reachable(fact):
                if reached in ids_in_group:
                    dominated.add(reached)
        survivors = [f for f in group if f["id"] not in dominated]
        return survivors[0] if len(survivors) == 1 else None
```

- [ ] **Step 4: 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_supersedes_winner_picks_survivor scripts.bb2_brain.tests.test_router.RouterTest.test_supersedes_winner_none_without_link scripts.bb2_brain.tests.test_router.RouterTest.test_supersedes_reachable_cycle_guard scripts.bb2_brain.tests.test_router.RouterTest.test_supersedes_reachable_missing_id_guard -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: supersedes 사슬 walk + 승자 판정 (G5 §9 해소 A, cycle/missing-id 가드)"
```

---

### Task 4: 해소 orchestration + `current_status` wiring + AC 통합 테스트 (결정 1·3·7)

**Files:**
- Modify: `scripts/bb2_brain/router.py` (`_resolve_current_conflicts` 추가 + `current_status` 분기 L63-77 wiring)
- Test: `scripts/bb2_brain/tests/test_router.py`

`_resolve_current_conflicts(self, facts)`가 `_conflicting_fact_groups` + `_supersedes_winner`를 묶어 `(kept, conflict_entries, any_unresolved)`를 돌려준다. 해소 시 승자만 `kept`, 미해소 시 경쟁 fact 전부 `kept`(투명 노출)+`any_unresolved=True`.

- [ ] **Step 1: 실패 테스트 작성 (AC1/AC2/AC3/AC5/AC6/AC7)**

`test_router.py`에 append:

```python
    def test_ac1_supersedes_resolves_silently(self):
        # AC1: open 2개, 같은 subject+predicate, value 상이, X.supersedes=Y(스칼라).
        router = self._conflict_router(
            self._reviewed_fact("fact.win", "drawEventCluster", supersedes="fact.lose"),
            self._reviewed_fact("fact.lose", "separate icons"),
        )
        answer = router.answer("지금 conflict.subj 상태?")
        self.assertIn("current_status", answer["intents"])
        self.assertIn("fact.win", answer["source_object_ids"])
        self.assertNotIn("fact.lose", answer["source_object_ids"])
        section = next(s for s in answer["sections"] if s["intent"] == "current_status")
        self.assertEqual(len(section["conflicts"]), 1)
        self.assertEqual(set(section["conflicts"][0]["fact_ids"]), {"fact.win", "fact.lose"})
        self.assertFalse(answer["needs_clarification"])

    def test_ac2_g9_scope_filter_singularizes_not_conflict(self):
        # AC2: broad{release} vs narrow{release,surface}. query가 surface(PopupEnter) 제약
        # → _scoped_facts가 broad 탈락 → narrow만 생존 → 충돌 아님(신규 회귀 가드).
        router = self._conflict_router(
            self._reviewed_fact("fact.broad", "broad-value"),
            self._reviewed_fact("fact.narrow", "narrow-value", surface="PopupEnter"),
        )
        answer = router.answer("지금 PopupEnter conflict.subj 상태?")
        section = next(s for s in answer["sections"] if s["intent"] == "current_status")
        self.assertEqual(section["conflicts"], [])
        self.assertIn("fact.narrow", answer["source_object_ids"])
        self.assertNotIn("fact.broad", answer["source_object_ids"])
        self.assertFalse(answer["needs_clarification"])

    def test_ac3_unresolved_conflict_reported(self):
        # AC3: AC2와 같은 두 fact, 단 query가 surface 미제약 → 둘 다 생존 → 미해소 보고.
        router = self._conflict_router(
            self._reviewed_fact("fact.broad", "broad-value"),
            self._reviewed_fact("fact.narrow", "narrow-value", surface="PopupEnter"),
        )
        answer = router.answer("지금 conflict.subj 상태?")
        section = next(s for s in answer["sections"] if s["intent"] == "current_status")
        self.assertEqual(len(section["conflicts"]), 1)
        self.assertIn("fact.broad", answer["source_object_ids"])
        self.assertIn("fact.narrow", answer["source_object_ids"])
        self.assertTrue(answer["needs_clarification"])

    def test_ac5_single_open_fact_happy_path(self):
        # AC5: open fact 1개 → 충돌 그룹 미생성, 기존 동작 보존.
        router = self._conflict_router(self._reviewed_fact("fact.only", "X"))
        answer = router.answer("지금 conflict.subj 상태?")
        section = next(s for s in answer["sections"] if s["intent"] == "current_status")
        self.assertEqual(section["conflicts"], [])
        self.assertIn("fact.only", answer["source_object_ids"])

    def test_ac6_cycle_reports_unresolved(self):
        # AC6: X.supersedes=Y, Y.supersedes=X, value 상이 → (A) 단일 승자 없음 → (C) 보고.
        router = self._conflict_router(
            self._reviewed_fact("fact.x", "A", supersedes="fact.y"),
            self._reviewed_fact("fact.y", "B", supersedes="fact.x"),
        )
        answer = router.answer("지금 conflict.subj 상태?")
        section = next(s for s in answer["sections"] if s["intent"] == "current_status")
        self.assertEqual(len(section["conflicts"]), 1)
        self.assertTrue(answer["needs_clarification"])

    def test_ac7_missing_id_does_not_crash(self):
        # AC7: X.supersedes=존재안함 → walk 멈춤, 단일 승자 없음 → (C) 보고. 예외 없음.
        router = self._conflict_router(
            self._reviewed_fact("fact.x", "A", supersedes="fact.gone"),
            self._reviewed_fact("fact.y", "B"),
        )
        answer = router.answer("지금 conflict.subj 상태?")
        section = next(s for s in answer["sections"] if s["intent"] == "current_status")
        self.assertEqual(len(section["conflicts"]), 1)
        self.assertTrue(answer["needs_clarification"])
```

- [ ] **Step 2: 실패 확인 + 라우팅 검증**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_ac1_supersedes_resolves_silently -v`
Expected: FAIL — `KeyError: 'conflicts'`(섹션에 키 없음) 또는 `AttributeError: _resolve_current_conflicts`. **이 단계에서 `intents`에 `current_status`가 잡히고 두 fact가 `_current_facts`로 들어오는지 확인**(아니면 query/fixture scope 조정 — "지금"은 current_status 트리거, scope 토큰 없으면 필터 0 → 두 fact 다 생존).

- [ ] **Step 3: orchestration 메서드 구현**

`scripts/bb2_brain/router.py`의 `QueryRouter`에 추가:

```python
    def _resolve_current_conflicts(self, facts):
        """returns (kept_facts, conflict_entries, any_unresolved).
        kept_facts: 충돌 무관 fact + 각 충돌그룹의 승자(A). 미해소 그룹은 승자 없이 그룹 전체를
                    kept에 포함(경쟁 fact 투명 노출)하고 any_unresolved=True.
        conflict_entries: [{fact_ids, predicate, values}] — 탐지된 모든 그룹."""
        groups = _conflicting_fact_groups(facts)
        conflicting_ids = {f["id"] for group in groups for f in group}
        kept = [f for f in facts if f["id"] not in conflicting_ids]
        entries, any_unresolved = [], False
        for group in groups:
            winner = self._supersedes_winner(group)          # (A) — 못 가르면 바로 (C)
            entries.append({
                "fact_ids": sorted(f["id"] for f in group),
                "predicate": group[0].get("predicate"),
                "values": sorted({repr(f.get("value")) for f in group}),
            })
            if winner is not None:
                kept.append(winner)
            else:
                kept.extend(group)
                any_unresolved = True
        return kept, entries, any_unresolved
```

- [ ] **Step 4: `current_status` 분기 wiring**

`scripts/bb2_brain/router.py`의 `current_status` 분기(L63-77)를 아래로 교체. `facts` 적재 루프가 `kept`를 돌고, `conflict_entries`/`any_unresolved`를 반영한다:

```python
            elif intent == "current_status":
                facts = self._current_facts(canonical)
                kept, conflict_entries, any_unresolved = self._resolve_current_conflicts(facts)
                ambiguous = self._release_ambiguous(kept, canonical)
                if ambiguous:
                    clarification_needed = True
                    warnings.append(f"release 모호: {', '.join(sorted(ambiguous))} 중 지정 필요")
                if any_unresolved:
                    clarification_needed = True
                for entry in conflict_entries:
                    ids = ", ".join(entry["fact_ids"])
                    vals = ", ".join(entry["values"])
                    warnings.append(f"충돌 reviewed fact: {ids} ({entry['predicate']} 값 상이: {vals})")
                all_views = self._reviewed_by_kind("CurrentView")
                warnings.extend(self._stale_view_warnings(all_views))
                warnings.extend(self._glossary_scope_disclosures(canonical))
                relevant_views = self._views_for_current_facts(all_views, kept)
                candidate_ids.extend(view["id"] for view in relevant_views)
                for fact in kept:
                    source_ids.append(fact["id"])
                    claim_statuses.append(claim_status(fact, raw_available=self._raw_available_for(fact), restricted=False))
                sections.append({"intent": intent, "object_ids": [fact["id"] for fact in kept], "conflicts": conflict_entries, "summary": "Current reviewed facts"})
```

변경 요지: `facts`→`kept`로 적재 루프·release 모호성·relevant view 전부 전환, `any_unresolved`를 `clarification_needed`에 OR 합류, 충돌 그룹별 warning 추가, 섹션에 `"conflicts": conflict_entries` 키 추가(빈 리스트 포함 항상).

- [ ] **Step 5: 신규 테스트 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_ac1_supersedes_resolves_silently scripts.bb2_brain.tests.test_router.RouterTest.test_ac2_g9_scope_filter_singularizes_not_conflict scripts.bb2_brain.tests.test_router.RouterTest.test_ac3_unresolved_conflict_reported scripts.bb2_brain.tests.test_router.RouterTest.test_ac5_single_open_fact_happy_path scripts.bb2_brain.tests.test_router.RouterTest.test_ac6_cycle_reports_unresolved scripts.bb2_brain.tests.test_router.RouterTest.test_ac7_missing_id_does_not_crash -v`
Expected: 6 PASS.

- [ ] **Step 6: 전체 회귀 (AC4 = 기존 as_of 회귀 포함)**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store`
Expected: 기존 52 + 신규 전부 PASS. 특히 `test_as_of_history_includes_superseded_fact`(AC4)가 green — as_of 경로 무변경, old+current 둘 다 반환, `conflicts` 키 안 생김, `needs_clarification` 불변.

- [ ] **Step 7: Commit**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: current_status 충돌 reviewed fact 해소·보고 (G5 §9 — A 해소/C 보고, conflicts 채널)"
```

---

### Task 5: spec/문서 정정 (결정 6, §9 L287 (B)=G9 명시)

**Files:**
- Modify: `docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md`

코드와 spec이 어긋나지 않게 정정. (vault task L43 "동일 scope" → "겹치는 scope" 문구는 task 작업 이력 갱신에서 처리 — 본 Task 범위 밖.)

- [ ] **Step 1: §9 / rejected-alternatives 정정 추가**

query-routing spec의 §9 충돌 관련 부분 또는 rejected-alternatives 섹션에 두 줄 추가:

```markdown
- §9 L287 "(B) choose the fact whose full scope matches more query dimensions"는 §7 candidate discovery의 conjunctive scope filter(`_scoped_facts`)가 candidate 단계에서 수행한다. 충돌 해소 사다리(런타임 ⑤)에는 supersedes(A)와 conflict report(C)만 둔다 — `_current_facts`로 들어온 fact는 이미 query 차원을 동일 만족하므로 scope 재매칭은 항상 동점(dead step)이기 때문이다.
- Rejected alternative: fact 종류별 차등 해소 / membase식 recency-priority(최신 `valid_from` 자동 선택). 최신성은 `supersedes`/`valid_until`이 담당하며 별도 휴리스틱은 "silent overwrite 금지"(object-model L298)를 위반하고 결정론을 깎는다. Phase 3a 실데이터 충돌 노이즈가 관측되면 재방문.
```

- [ ] **Step 2: 전체 테스트 재확인 (문서 변경이라 코드 불변이지만 확인)**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store`
Expected: 전부 PASS (불변).

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md
git commit -m "docs: §9 충돌해소 (B)=G9 candidate 필터 소관 명시 + recency 거절-대안 (G5)"
```

---

## Self-Review

**Spec coverage (확정 결정 7개 대조):**
- 결정1(current만, as_of defer) → Task 4 wiring은 `current_status` 분기만 수정, as_of 무변경. AC4(기존 as_of 회귀)가 잠금. ✓
- 결정2(탐지 키 subject+predicate) → Task 2 `_conflicting_fact_groups`. ✓
- 결정3(A→C 사다리, B 없음) → Task 3(A) + Task 4(`_resolve_current_conflicts`는 supersedes_winner None → 바로 C). scope 매칭 단계 없음. ✓
- 결정4(supersedes scalar) → Task 1 fixture 정정 + Task 3 `_supersedes_reachable`가 스칼라 `current.get("supersedes")` walk. ✓
- 결정5(Lint 분리, 순수 함수 공유) → Task 2 모듈 레벨 store 비의존 함수. lint.py 본체 없음. ✓
- 결정6(uniform, recency 거절) → Task 5 spec 명문화. 코드에 차등 분기 없음. ✓
- 결정7(conflicts/warnings/needs_clarification, 신규 status 금지) → Task 4 Step 4 wiring. status 무변경. ✓

**Placeholder scan:** 모든 Step에 실제 코드/명령 포함. TODO·"적절히 처리" 없음. ✓

**Type consistency:** `_conflicting_fact_groups(facts)→list[list[dict]]`, `_supersedes_winner(group)→dict|None`, `_resolve_current_conflicts(facts)→(kept, entries, any_unresolved)`. Task 4가 Task 2·3의 시그니처를 그대로 사용. `conflicts` 필드 모양 `{fact_ids, predicate, values}` 일관(Task 4 entries 생성부 = 결정 7a). ✓

**검증 명령(게이트 완료 기준):**
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store
```
기존 52 tests green 유지 + 신규(helper 1 + supersedes 4 + AC 6 = 11) PASS.
