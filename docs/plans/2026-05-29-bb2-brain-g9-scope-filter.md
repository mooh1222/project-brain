# BB2 Brain G9 — Scope Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `QueryRouter._scoped_facts`를 하드코딩된 `"5.5"` 매칭에서 데이터 기반 다차원 conjunctive scope 필터로 일반화하고, release 차원 모호성에 대해 clarification을 요청한다.

**Architecture:** reviewed `TemporalFact`의 `scope` 딕셔너리에서 차원별 distinct 값을 수집해, 그 값 문자열이 query에 등장하면 해당 차원을 필수 필터로 추가한다(차원 간 conjunctive, 차원 내 OR). project 추론과 한국어→영문 scope 값 매핑(GlossaryTerm)은 G11로 이관한다. release 차원이 query에 없는데 후보 fact가 복수 release에 걸치면 silent pick 대신 `needs_clarification`으로 되묻는다.

**Tech Stack:** Python 3, `unittest`, 기존 `scripts/bb2_brain/` 프로토타입.

---

## 설계 근거 (작업원칙 기록)

- **출처**: query-routing spec §6.1 L116-117 / §6.3 L172-175, object-model spec §TemporalFact L262-269(scope 6차원: project/release/feature/surface/platform/module). vault에 Brain 설계 노트 없음(게임코드 패턴 무관). 외부 웹 리서치 불필요(scope 추출 알고리즘은 spec 공백 — G8과 동일하게 설계 충전).
- **Q1 결정 = 데이터 기반 풀 메커니즘**: 6차원 conjunctive 필터 엔진을 지금 전부 만든다. 단 fact의 scope 값은 영문("PopupEnter")이고 한국어 query("입장팝업")와 글자가 안 맞으므로, 현재는 query가 영문 값/release 숫자를 직접 포함할 때만 좁혀진다. 한국어→영문 다리(GlossaryTerm 단일-leaf 추론, spec §6.3 L173)는 **G11로 이관**(GlossaryTerm에 scope 필드 부재, object-model L581-591 — G11의 GlossaryTerm preflight와 결합). G8과 동일한 결정론적 구조.
- **Q2 결정 = release 차원 clarification만 G9**: surface/platform 모호성 clarification은 한국어→영문 다리(G11) 전에는 한국어 query가 surface 값을 줄 수 없어 매 쿼리마다 오발(노이즈)되므로 **G11 이후로 이관**. release는 query가 "5.5"로 직접 주므로 지금 의미 있다(spec §6.3 L174).
- **G9 범위 밖(명시 이관)**: §6.3 L173 project 추론(현 fixture는 전부 `bb2-client` 단일값이라 필터 무영향 — dead machinery 미작성), L173 GlossaryTerm scope 추론(G11), L175 assumed as_of 명시(as_of 날짜 파싱 자체가 미구현 — 별도 gap).
- **의미기반 candidate discovery**(spec §7 / IndexRecord vector)는 G9 다음 게이트로 당김 — task 레벨 결정, 본 플랜 범위 밖.
- **G11 carry-forward (코드 리뷰 발견)**: scope 값 매칭이 `value in query` substring이라 numeric release prefix 충돌(`"5.5" in "5.50"` → 둘 다 매칭 + release가 필터에 잡혀 `_release_ambiguous` 단락 → silent 오포함, 경고 없음) 및 surface prefix 충돌(`"Popup"` vs `"PopupEnter"`) 가능. 현 fixture는 단일 release/구분된 surface라 미발동. G11에서 한국어→영문 글로서리 다리를 넣을 때 word-boundary / exact-token 매칭으로 함께 교체.

---

## File Structure

- `scripts/bb2_brain/router.py` (Modify): `_scoped_facts` 일반화 + `_query_scope_filters`/`_release_ambiguous` 헬퍼 추가 + `answer()` clarification 배선.
- `scripts/bb2_brain/tests/test_router.py` (Modify): 신규 테스트 4개 추가. 멀티 release/surface fixture는 각 테스트 내 인라인 임시 store로 구성(기존 `test_evidence_provenance_restricted_when_redaction` 패턴).

검증 명령 (전체):
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store
```

---

## Task 1: 데이터 기반 conjunctive scope 필터

`_scoped_facts`를 하드코딩 `"5.5"`에서 일반 다차원 필터로 교체. 차원 간 conjunctive, 차원 내 OR. release뿐 아니라 임의 scope 차원 값이 query에 등장하면 좁혀짐을 증명한다.

**Files:**
- Modify: `scripts/bb2_brain/router.py:101-105` (`_scoped_facts`)
- Test: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: surface 차원으로 좁혀지는 실패 테스트 작성**

`scripts/bb2_brain/tests/test_router.py`의 `RouterTest` 클래스 끝에 추가:

```python
    def test_scope_filter_narrows_by_non_release_dimension(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/facts/enter.json", {
            "id": "fact.enter",
            "kind": "TemporalFact",
            "status": "reviewed",
            "truth_role": "fact",
            "scope": {"project": "bb2-client", "release": "5.5", "surface": "PopupEnter"},
            "valid_from": "2026-05-26T00:00:00+09:00",
            "evidence_refs": [],
        })
        write_object(root, "objects/facts/continue.json", {
            "id": "fact.continue",
            "kind": "TemporalFact",
            "status": "reviewed",
            "truth_role": "fact",
            "scope": {"project": "bb2-client", "release": "5.5", "surface": "PopupContinue"},
            "valid_from": "2026-05-26T00:00:00+09:00",
            "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("PopupContinue 현재 규칙은 뭐야?")
        self.assertIn("fact.continue", answer["source_object_ids"])
        self.assertNotIn("fact.enter", answer["source_object_ids"])
        self.assertFalse(answer["needs_clarification"])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_scope_filter_narrows_by_non_release_dimension -v`
Expected: FAIL — 현재 `_scoped_facts`는 `"5.5"`만 필터하므로 query에 "5.5" 없음 → 필터 없음 → `fact.enter`도 source에 포함되어 `assertNotIn` 실패.

- [ ] **Step 3: `_scoped_facts` 일반화 + `_query_scope_filters` 헬퍼 구현**

`scripts/bb2_brain/router.py`에서 기존 `_scoped_facts` (L101-105):

```python
    def _scoped_facts(self, query: str) -> list[dict]:
        facts = self._reviewed_by_kind("TemporalFact")
        if "5.5" in query:
            facts = [fact for fact in facts if fact.get("scope", {}).get("release") == "5.5"]
        return facts
```

를 아래로 교체:

```python
    _SCOPE_DIMENSIONS = ("release", "feature", "surface", "platform", "module")

    def _query_scope_filters(self, query: str) -> dict[str, set[str]]:
        filters: dict[str, set[str]] = {}
        for fact in self._reviewed_by_kind("TemporalFact"):
            scope = fact.get("scope", {})
            for dim in self._SCOPE_DIMENSIONS:
                value = scope.get(dim)
                if value and value in query:
                    filters.setdefault(dim, set()).add(value)
        return filters

    def _scoped_facts(self, query: str) -> list[dict]:
        facts = self._reviewed_by_kind("TemporalFact")
        for dim, values in self._query_scope_filters(query).items():
            facts = [fact for fact in facts if fact.get("scope", {}).get(dim) in values]
        return facts
```

(주: scope 값은 reviewed `TemporalFact`에서 수집한다. `project`는 현 데이터가 단일값이라 필터에 넣지 않는다 — `_SCOPE_DIMENSIONS`에서 제외. 한국어→영문 매핑 부재는 G11에서 해소.)

- [ ] **Step 4: 신규 테스트 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_scope_filter_narrows_by_non_release_dimension -v`
Expected: PASS

- [ ] **Step 5: 전체 회귀 확인 (release 5.5 필터 보존 포함)**

Run:
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store
```
Expected: OK (기존 28 + 신규 1 = 29). 특히 `test_current_status_uses_fact_truth_not_current_view_truth`(5.5 필터), `test_as_of_history_includes_superseded_fact`, `test_dangling_evidence_ref_does_not_crash`, `test_evidence_provenance_restricted_when_redaction`(release 무필터) 통과.

- [ ] **Step 6: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "$(cat <<'EOF'
feat: generalize BB2 Brain scoped-fact filter to conjunctive scope dimensions

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: release 차원 모호성 clarification

query가 release를 지정하지 않았는데 후보 fact가 복수 release에 걸치면 `needs_clarification=true` + 후보 release를 warning으로 노출한다(spec §6.3 L174). `current_status`와 `as_of_history` 두 intent에 적용한다.

**Files:**
- Modify: `scripts/bb2_brain/router.py` (`answer()` init/current_status/as_of_history 분기 + return, `_release_ambiguous` 헬퍼 추가)
- Test: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: 실패 테스트 3개 작성**

`scripts/bb2_brain/tests/test_router.py`의 `RouterTest` 클래스 끝에 추가. 헬퍼로 멀티 release fixture 구성:

```python
    def _multi_release_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/facts/r55.json", {
            "id": "fact.r55",
            "kind": "TemporalFact",
            "status": "reviewed",
            "truth_role": "fact",
            "scope": {"project": "bb2-client", "release": "5.5", "surface": "PopupEnter"},
            "valid_from": "2026-05-26T00:00:00+09:00",
            "evidence_refs": [],
        })
        write_object(root, "objects/facts/r54.json", {
            "id": "fact.r54",
            "kind": "TemporalFact",
            "status": "reviewed",
            "truth_role": "fact",
            "scope": {"project": "bb2-client", "release": "5.4", "surface": "PopupEnter"},
            "valid_from": "2026-05-01T00:00:00+09:00",
            "evidence_refs": [],
        })
        return BrainStore.load(root)

    def test_current_status_release_ambiguity_requests_clarification(self):
        router = QueryRouter(self._multi_release_store())
        answer = router.answer("현재 규칙은 뭐야?")
        self.assertEqual(answer["intents"], ["current_status"])
        self.assertTrue(answer["needs_clarification"])
        self.assertTrue(
            any("release" in w and "5.4" in w and "5.5" in w for w in answer["warnings"])
        )

    def test_release_specified_avoids_ambiguity(self):
        router = QueryRouter(self._multi_release_store())
        answer = router.answer("5.5 현재 규칙은 뭐야?")
        self.assertFalse(answer["needs_clarification"])
        self.assertIn("fact.r55", answer["source_object_ids"])
        self.assertNotIn("fact.r54", answer["source_object_ids"])

    def test_as_of_release_ambiguity_requests_clarification(self):
        router = QueryRouter(self._multi_release_store())
        answer = router.answer("그때 규칙은 뭐였어?")
        self.assertEqual(answer["intents"], ["as_of_history"])
        self.assertTrue(answer["needs_clarification"])
        self.assertTrue(
            any("release" in w and "5.4" in w and "5.5" in w for w in answer["warnings"])
        )
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_current_status_release_ambiguity_requests_clarification scripts.bb2_brain.tests.test_router.RouterTest.test_as_of_release_ambiguity_requests_clarification -v`
Expected: FAIL — 현재 `needs_clarification = not source_ids`인데 facts가 있어 `False` → `assertTrue` 실패. (`test_release_specified_avoids_ambiguity`는 Task 1 필터로 이미 통과할 수 있으나 회귀 보호용으로 함께 둔다.)

- [ ] **Step 3: `_release_ambiguous` 헬퍼 + `answer()` 배선 구현**

`scripts/bb2_brain/router.py`에서:

(3-1) `answer()` 초기화부 — 기존:
```python
        claim_statuses: list[str] = []
        warnings: list[str] = []
```
를:
```python
        claim_statuses: list[str] = []
        warnings: list[str] = []
        clarification_needed = False
```

(3-2) `current_status` 분기 — 기존 (L34-43):
```python
            elif intent == "current_status":
                facts = self._current_facts(query)
                all_views = self._reviewed_by_kind("CurrentView")
```
를:
```python
            elif intent == "current_status":
                facts = self._current_facts(query)
                ambiguous = self._release_ambiguous(facts, query)
                if ambiguous:
                    clarification_needed = True
                    warnings.append(f"release 모호: {', '.join(sorted(ambiguous))} 중 지정 필요")
                all_views = self._reviewed_by_kind("CurrentView")
```

(3-3) `as_of_history` 분기 — 기존 (L44-49):
```python
            elif intent == "as_of_history":
                facts = self._scoped_facts(query)
                for fact in facts:
```
를:
```python
            elif intent == "as_of_history":
                facts = self._scoped_facts(query)
                ambiguous = self._release_ambiguous(facts, query)
                if ambiguous:
                    clarification_needed = True
                    warnings.append(f"release 모호: {', '.join(sorted(ambiguous))} 중 지정 필요")
                for fact in facts:
```

(3-4) return문 — 기존:
```python
            "needs_clarification": not source_ids,
```
를:
```python
            "needs_clarification": (not source_ids) or clarification_needed,
```

(3-5) `_release_ambiguous` 헬퍼 추가 — `_scoped_facts` 바로 아래에:
```python
    def _release_ambiguous(self, facts: list[dict], query: str) -> set[str]:
        if "release" in self._query_scope_filters(query):
            return set()
        releases = {fact.get("scope", {}).get("release") for fact in facts}
        releases.discard(None)
        return releases if len(releases) > 1 else set()
```

(주: query가 release를 지정하면 모호성 없음. 미지정 + 후보가 복수 release일 때만 set 반환. `current_status`는 open facts(`_current_facts`), `as_of_history`는 전체(`_scoped_facts`) 기준으로 각각 판정. mixed-intent에서 동일 경고가 중복될 수 있으나 기존 warnings 중복 허용 패턴(G7 관찰)과 일관 — 비차단.)

- [ ] **Step 4: 신규 테스트 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_current_status_release_ambiguity_requests_clarification scripts.bb2_brain.tests.test_router.RouterTest.test_release_specified_avoids_ambiguity scripts.bb2_brain.tests.test_router.RouterTest.test_as_of_release_ambiguity_requests_clarification -v`
Expected: PASS (3건)

- [ ] **Step 5: 전체 회귀 확인**

Run:
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store
```
Expected: OK (28 + Task1 1 + Task2 3 = 32). 기존 fixture는 전부 release 5.5 단일이라 `_release_ambiguous`가 빈 set 반환 → 기존 테스트 clarification 무영향.

- [ ] **Step 6: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "$(cat <<'EOF'
feat: request clarification on ambiguous BB2 Brain release scope

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. Spec coverage:**
- §6.3 L172 (conjunctive scope 필터, 6차원) → Task 1 (`_query_scope_filters` + `_scoped_facts`). project는 단일값이라 미적용(문서화), 한국어→영문 매핑은 G11 이관(문서화).
- §6.3 L174 (모호 시 silent pick 대신 clarification) → Task 2, release 차원. surface/platform은 G11 이관(문서화).
- §6.1 L116-117 (current_status가 matching subject/scope fact 사용) → Task 1이 `_current_facts` 경유로 자동 적용.
- §6.3 L173 project/glossary 추론, L175 assumed as_of → G9 범위 밖(설계 근거 섹션에 명시 이관).

**2. Placeholder scan:** TBD/TODO/"적절히 처리" 없음. 모든 코드 스텝에 실제 코드 포함.

**3. Type consistency:** `_query_scope_filters`(dict[str, set[str]])는 Task 1 정의 → Task 2 `_release_ambiguous`에서 `"release" in ...`로 키 멤버십만 사용(일관). `clarification_needed`(bool)는 Task 2 init→분기→return 일관. `_SCOPE_DIMENSIONS` 튜플 Task 1 정의 후 `_query_scope_filters`에서만 참조.

**4. 회귀 안전성:** 기존 28 테스트는 전부 release 5.5 단일 fixture → Task 1 필터 결과 불변, Task 2 모호성 미발동. 신규 동작은 멀티 release/surface 인라인 fixture에서만 발현.
