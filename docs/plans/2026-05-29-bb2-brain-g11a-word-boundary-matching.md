# BB2 Brain G11a — Scope Token Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `QueryRouter._query_scope_filters`의 scope 값 매칭을 `value in query` substring에서 **토큰 단위 정확 매칭**으로 바꿔, `"5.5"`가 `"5.50"`에·`"PopupEnter"`가 `"PopupEnterRanking"`에 잘못 걸리는 silent 오포함(G9 코드 리뷰 carry-forward)을 막는다.

**Architecture:** query를 `[0-9A-Za-z._-]+` 런(scope 값이 가질 수 있는 문자 집합)으로 토큰화한 뒤, scope 값이 그 토큰 집합에 **완전 일치**할 때만 필터로 채택한다. 한국어→영문 글로서리 다리, preflight 일반화, 용어 가드는 G11b(별도, object-model 결정 포함).

**Tech Stack:** Python 3 `re`, `unittest`, 기존 `scripts/bb2_brain/` 프로토타입.

---

## 설계 근거 (작업원칙 기록)

- **출처**: G9 코드 quality 리뷰(opus) Issue 1 — `value in query` substring이 `"5.5" in "5.50"`(둘 다 매칭 + release가 필터에 잡혀 `_release_ambiguous` 단락 → 경고 없는 오포함) 및 surface prefix 충돌(`"PopupEnter" in "PopupEnterRanking"`) 발생. G9 plan "설계 근거"의 G11 carry-forward 항목.
- **결정 0개(안전)**: object-model·글로서리·fact 데이터 미변경. 매칭 함수 내부만 토큰화로 교체. 한국어→영문 scope 다리(GlossaryTerm scope 필드 신설 여부)와 preflight 일반화(글로서리 `term`/`avoid` vs fixture `canonical_term`/`avoided_terms` 필드명 불일치 해소)는 **G11b**로 분리.
- **토큰 문자 집합 `[0-9A-Za-z._-]`**: 현 scope 값(release `5.5`, feature `stage-clear-token`, surface `PopupEnter`, platform `ios/android/common`, module 식별자)이 전부 이 집합 안. 한국어는 토큰에서 제외되므로 한국어 쿼리의 영문 scope 값 매칭은 G9와 동일하게 "쿼리가 영문 값을 직접 포함할 때만" 동작(한국어 다리는 G11b).

---

## File Structure

- `scripts/bb2_brain/router.py` (Modify): `import re` 추가, 모듈 상수 `_SCOPE_TOKEN_RE` 추가, `_query_scope_filters` 본문 한 줄 교체(`value in query` → `value in tokens`).
- `scripts/bb2_brain/tests/test_router.py` (Modify): 충돌 회귀 테스트 2개 추가.

검증 명령 (전체):
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store
```
베이스라인 32 tests OK.

---

## Task 1: scope 값 토큰 정확 매칭

**Files:**
- Modify: `scripts/bb2_brain/router.py` (`import`, 모듈 상수, `_query_scope_filters`)
- Test: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: 충돌 회귀 테스트 2개 작성**

`scripts/bb2_brain/tests/test_router.py`의 `RouterTest` 클래스 끝에 추가:

```python
    def test_scope_filter_rejects_numeric_release_prefix_collision(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/facts/r55.json", {
            "id": "fact.r55",
            "kind": "TemporalFact",
            "status": "reviewed",
            "truth_role": "fact",
            "scope": {"project": "bb2-client", "release": "5.5"},
            "valid_from": "2026-05-26T00:00:00+09:00",
            "evidence_refs": [],
        })
        write_object(root, "objects/facts/r550.json", {
            "id": "fact.r550",
            "kind": "TemporalFact",
            "status": "reviewed",
            "truth_role": "fact",
            "scope": {"project": "bb2-client", "release": "5.50"},
            "valid_from": "2026-05-26T00:00:00+09:00",
            "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("5.50 현재 규칙은 뭐야?")
        self.assertIn("fact.r550", answer["source_object_ids"])
        self.assertNotIn("fact.r55", answer["source_object_ids"])
        self.assertFalse(answer["needs_clarification"])

    def test_scope_filter_rejects_surface_prefix_collision(self):
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
        write_object(root, "objects/facts/ranking.json", {
            "id": "fact.ranking",
            "kind": "TemporalFact",
            "status": "reviewed",
            "truth_role": "fact",
            "scope": {"project": "bb2-client", "release": "5.5", "surface": "PopupEnterRanking"},
            "valid_from": "2026-05-26T00:00:00+09:00",
            "evidence_refs": [],
        })
        router = QueryRouter(BrainStore.load(root))
        answer = router.answer("PopupEnterRanking 현재 규칙은 뭐야?")
        self.assertIn("fact.ranking", answer["source_object_ids"])
        self.assertNotIn("fact.enter", answer["source_object_ids"])
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_scope_filter_rejects_numeric_release_prefix_collision scripts.bb2_brain.tests.test_router.RouterTest.test_scope_filter_rejects_surface_prefix_collision -v`
Expected: FAIL — 현재 substring 매칭이라 `"5.5" in "5.50 …"` / `"PopupEnter" in "PopupEnterRanking …"` 둘 다 True → 짧은 값이 잘못 필터에 잡혀 `fact.r55`/`fact.enter`가 source에 포함, `assertNotIn` 실패.

- [ ] **Step 3: 토큰 정확 매칭 구현**

`scripts/bb2_brain/router.py` 상단 import 블록(3줄) 바로 아래에 추가:
```python
import re
```
(기존 `from scripts.bb2_brain...` 3줄은 유지. `import re`는 표준 라이브러리이므로 관례상 맨 위에 둔다 — 기존 import가 전부 `from` 형식이라, `import re`를 3줄 위 맨 첫 줄에 두고 그 아래 기존 `from` 3줄을 잇는다.)

import 블록과 `class QueryRouter` 사이(빈 줄 영역)에 모듈 상수 추가:
```python
_SCOPE_TOKEN_RE = re.compile(r"[0-9A-Za-z._-]+")
```

기존 `_query_scope_filters` (router.py):
```python
    def _query_scope_filters(self, query: str) -> dict[str, set[str]]:
        filters: dict[str, set[str]] = {}
        for fact in self._reviewed_by_kind("TemporalFact"):
            scope = fact.get("scope", {})
            for dim in self._SCOPE_DIMENSIONS:
                value = scope.get(dim)
                if value and value in query:
                    filters.setdefault(dim, set()).add(value)
        return filters
```
를 아래로 교체(쿼리를 한 번 토큰화하고 멤버십 비교):
```python
    def _query_scope_filters(self, query: str) -> dict[str, set[str]]:
        tokens = set(_SCOPE_TOKEN_RE.findall(query))
        filters: dict[str, set[str]] = {}
        for fact in self._reviewed_by_kind("TemporalFact"):
            scope = fact.get("scope", {})
            for dim in self._SCOPE_DIMENSIONS:
                value = scope.get(dim)
                if value and value in tokens:
                    filters.setdefault(dim, set()).add(value)
        return filters
```

- [ ] **Step 4: 신규 테스트 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router.RouterTest.test_scope_filter_rejects_numeric_release_prefix_collision scripts.bb2_brain.tests.test_router.RouterTest.test_scope_filter_rejects_surface_prefix_collision -v`
Expected: PASS (2건)

- [ ] **Step 5: 전체 회귀 확인**

Run:
```bash
cd /Users/al03040455/Desktop/bb2_client && /Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router scripts.bb2_brain.tests.test_intent scripts.bb2_brain.tests.test_status scripts.bb2_brain.tests.test_store
```
Expected: OK (32 + 2 = 34). 기존 positive 매칭은 토큰화 후에도 보존:
- `test_current_status_uses_fact_truth_not_current_view_truth` 등 "5.5 …" 쿼리 → 토큰 `"5.5"` 정확 일치 → release 필터 유지.
- `test_scope_filter_narrows_by_non_release_dimension` "PopupContinue …" → 토큰 `"PopupContinue"` 정확 일치 → surface 필터 유지.
- 한국어 전용 쿼리(`test_evidence_provenance_restricted_when_redaction` "이 규칙 근거가 뭐야?") → 토큰 없음 → 필터 없음(기존과 동일).

- [ ] **Step 6: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "$(cat <<'EOF'
fix: match BB2 Brain scope values by whole token to avoid prefix collisions

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. 갭 커버:** G9 carry-forward(substring prefix 충돌)의 두 부류(numeric release `5.5`/`5.50`, surface prefix `PopupEnter`/`PopupEnterRanking`)를 각각 테스트로 고정. 토큰 집합 `[0-9A-Za-z._-]`는 현 scope 값 전부 포함.

**2. Placeholder scan:** 없음. 모든 스텝 실제 코드.

**3. Type consistency:** `_query_scope_filters` 반환형(dict[str, set[str]]) 불변 — 호출처(`_scoped_facts`, `_release_ambiguous`) 영향 없음. `_SCOPE_TOKEN_RE`는 모듈 상수로 1회 컴파일.

**4. 회귀 안전성:** 매칭만 substring→토큰 정확비교로 좁혀짐. 기존 테스트의 positive 매칭은 전부 완전 토큰(`5.5`, `PopupContinue`)이라 보존. 좁아지는 방향이라 과매칭 회귀 없음.

**5. 범위 경계:** 한국어→영문 다리·preflight 일반화·용어 가드는 G11b. 본 plan은 매칭 정합성만.
