# BB2 Brain — B+C 검수 모델 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 라우터가 검수된 것만 답하는 현재의 이진 동작에, 저신뢰 후보를 "확인 필요" 라벨로 함께 노출(C)하고, 사용 시점에 사람이 후보를 확정(`cli promote`)하며, 적재 시 검증된 근거가 있는 객체를 자동 검수됨으로 두는(B) 흐름을 더한다.

**Architecture:** 라우터는 읽기 전용을 유지한 채 `glossary_meaning` 의도에서 candidate GlossaryTerm 정의를 별도 수집기로 모아 라벨 달아 노출한다(충돌·추론 로직 입력에는 검수 전용 유지). 답 dict에 승격 후보 전용 필드 `promotable_candidate_ids`를 더한다. `cli promote`가 `promote.py` 단건 변환 결과(승격 객체 + 검토 기록)를 둘 다 `save_object`로 저장하고 사후 lint 1회를 돈다. `schema.py`는 검수된 DomainMapping·GlossaryTerm에 비어있지 않은 `evidence_refs`를 강제한다(코드앵커는 비강제).

**Tech Stack:** Python 3 표준 라이브러리, unittest. brain 엔진은 `scripts/bb2_brain/`(게임 런타임과 분리된 메타 시스템). 절대 임포트(`from scripts.bb2_brain.X import Y`). 테스트 실행은 repo 루트에서 `python -m pytest scripts/bb2_brain/tests/`.

**권위 spec:** `docs/superpowers/specs/2026-06-05-bb2-brain-bc-review-model-design-v2.md`

---

## 사전 측정 결과 (플랜 작성 중 실측, 근거)

플랜 작성 전에 실제 코드·데이터로 아래를 확인했다. 모든 후속 Task가 이 측정에 의존한다.

1. **디스크 테스트 베이스라인 = 29 passed** (메모리의 156이 아님). 현재 디스크에 있는 테스트: `test_cli.py`, `test_ingest.py`, `test_objbase.py`, `test_promote.py`, `test_universal_ingest_e2e.py`. 삭제(staged) 상태: `test_router/status/schema/lint/store/intent/context_projection.py` 7개 + fixture 7개.
2. **실코퍼스(`scripts/bb2_brain/brain`) = 466객체.** reviewed DomainMapping 64개는 **전부** `evidence_refs` 비어있지 않음(코드앵커 없는 서버규칙류 6개 포함). reviewed GlossaryTerm은 `g.sally-canoe.naming-canoe-race` **1개뿐이고 `evidence_refs`가 빔.**
3. **★spec §6.4/§11의 "근거 빈 검수됨 0건" 주장은 GlossaryTerm에서 1건 틀렸다.★** 그 1건(`g.sally-canoe.naming-canoe-race`)은 강등 대상이 아니라 backfill 대상이다 — 짝 매핑 `mapping.sally-canoe.event-naming`이 같은 명칭 사실을 `evref.sally-canoe.naming-spec`·`evref.sally-canoe.naming-code`로 근거를 댄다. 두 evref 모두 store에 실재(확인됨). 용어가 근거를 안 단 것뿐, 근거는 존재한다.
4. **§6.4 schema 규칙을 임시 적용해 실측한 회귀: 기존 테스트 정확히 6개가 깨진다.** (한 번 패치→측정→원복 했다.)
   - `test_ingest.py::TestIngest::test_ingest_allows_candidate_to_reviewed`
   - `test_ingest.py::TestIngest::test_ingest_rejects_reviewed_to_candidate_demotion`
   - `test_ingest.py::TestIngest::test_ingest_reviewed_to_reviewed_ok`
   - `test_promote.py::TestSingleObject::test_single_object_drops_conflict_candidate`
   - `test_promote.py::TestSingleObject::test_single_object_promoted_passes_schema`
   - `test_promote.py::TestMappingBundle::test_mapping_bundle_passes_schema`
   - 원인: 이 테스트들의 합성 헬퍼가 evidence 없는 reviewed 용어/매핑을 만든다(옛 불변조건). 새 불변조건(reviewed는 근거 필수)을 헬퍼가 반영하도록 고쳐야 한다. Task 4가 정확한 편집을 명시한다.

---

## 결정해야 할 것 (구현 전 확인)

spec §11이 plan으로 미룬 미해결 결정 + 사전 측정이 드러낸 결정. 아래는 이 플랜이 택한 답이며, 구현 중 바뀌면 후속 Task가 따라 바뀐다.

- **§6.4 "검증된 근거"의 코드 정의** → `evidence_refs` non-empty로 본다(근거 종류·검증표시 코드 강제 안 함). 근거: spec §11 "이 게이트는 B/C 분류기가 아니라 근거가 통째로 빈 적재만 막는 회귀 바닥". 현 코퍼스에서 이 게이트가 거르는 객체는 backfill 후 0건.
- **cli promote가 근거 없는(zero-evidence) 후보를 승격하면?** → 코드 가드는 후보 자격을 막지 않으나(사람이 판정자, spec §5.2), 승격 결과물이 §6.4를 어기면 **`_run_promote`가 디스크에 쓰기 전 일괄 schema 검증(`validate_object`)으로 막는다** — `save_object`(store.py:60-63)가 어차피 `validate_object`를 거쳐 `SchemaError`를 raise하므로, `_run_promote`는 쓰기 전에 미리 검증해 깔끔한 rc=1을 내고 부분 쓰기를 막는다(원자성). ★리뷰 정정: 이건 "사후 lint"가 아니다 — 사후 lint는 쓰기 후이고, 근거 부재는 쓰기 전 schema가 잡는다. 따라서 "근거 약한"(weak-but-present) 후보는 승격 가능, "근거 없는"(zero) 후보는 쓰기 전 schema가 막는다. §5.2("근거 약한 후보 승격 허용")와 §6.4(근거 필수)를 함께 만족시키는 해석이다.
- **답 구조 후보 표기 형식** → candidate는 section의 `candidate_terms` 키(각 항목 `trust_label="확인 필요"`)로 검수 `mappings`/`object_ids`와 **구조적으로 분리**해 식별 가능하게 한다(spec §4.3 "검수됨/후보 구분"). 답 dict 최상위에 승격 후보 전용 `promotable_candidate_ids`. `candidate_object_ids`(보조 CurrentView)는 손대지 않음. ★리뷰 반영: section 레벨 `reviewed_trust_label` 키는 두지 않는다 — glossary_meaning section은 검수 매핑·무조건 덤프되는 DomainContext·후보가 섞여 단일 라벨이 의미 모호. 검수/후보 구분은 키(`mappings`/`object_ids` vs `candidate_terms`)로 한다.
- **★candidate-only 답의 needs_clarification (spec §4.3)** → `(not source_ids)`에 의존하지 않는다. `glossary_meaning` 분기가 reviewed DomainContext를 매칭과 무관하게 `source_ids`에 무조건 넣어(router.py:191-195) 실코퍼스에서도 source_ids가 비지 않기 때문(reviewed `context.sally-canoe` 상존). 대신 **후보가 노출됐고 매칭된 검수 매핑(`matched_mappings`)이 없으면 `clarification_needed=True`를 명시 설정**한다. 이게 운영 환경에서도 §4.3을 도달 가능하게 한다(리뷰어 4명 합의 critical 반영).
- **자동 승격 적재 방법(B)** → 이미 `ingest.py`가 status를 그대로 저장하고 후퇴만 막으므로(§6.3), `status:"reviewed"`로 적재하면 자동 승격. 별도 코드 불필요. Task 4는 §6.4 게이트만 추가하고 자동 승격 흐름은 합성 테스트로 검증.

---

## File Structure

| 파일 | 책임 | 이번 작업 |
|------|------|----------|
| `scripts/bb2_brain/router.py` | 질의→답 라우팅. 읽기 전용 | Task 1: glossary_meaning에 candidate 노출 수집기 + 답 dict에 `promotable_candidate_ids` |
| `scripts/bb2_brain/cli.py` | CLI 진입점(query/ingest) | Task 2: `promote` 서브커맨드 신설 |
| `scripts/bb2_brain/schema.py` | 객체 단위 schema 검증 | Task 4: reviewed DomainMapping·GlossaryTerm `evidence_refs` non-empty 강제 |
| `scripts/bb2_brain/tests/test_router.py` | (신규) 라우터 회귀 베이스라인 + C 노출 | Task 0 생성, Task 1 확장 |
| `scripts/bb2_brain/tests/test_status.py` | (신규) status 회귀 베이스라인 | Task 0 생성 |
| `scripts/bb2_brain/tests/test_schema.py` | (신규) schema 회귀 베이스라인 + §6.4 | Task 0 생성, Task 4 확장 |
| `scripts/bb2_brain/tests/test_lint.py` | (신규) lint 회귀 베이스라인 | Task 0 생성 |
| `scripts/bb2_brain/tests/test_cli.py` | CLI 테스트 | Task 2: promote 왕복 테스트 추가 |
| `scripts/bb2_brain/tests/test_ingest.py` | ingest 테스트 | Task 4: reviewed_term 헬퍼 + 3개 테스트 §6.4 반영 |
| `scripts/bb2_brain/tests/test_promote.py` | promote 테스트 | Task 4: candidate 헬퍼 2개에 evidence_refs 추가 |
| `scripts/bb2_brain/brain/.../g.sally-canoe.naming-canoe-race.json` | 실코퍼스 데이터 | Task 4: evidence_refs backfill (git 미추적) |

손대지 않는 것: `status.py`(신뢰 라벨 모델 불변, spec §8), `lint.py`(8a 깨진 참조 검사 보완 그대로), `promote.py`, `ingest.py`, `objbase.py`, `store.py`, `intent.py`.

---

## Task 0: 회귀 베이스라인 테스트 (선행)

삭제된 7개 테스트는 복원하지 않고(spec §0 변경 6), C/promote/B가 손댈 모듈(`router.answer`·`status.py`·`schema.py`·`lint.py`)에 대한 새 베이스라인 테스트를 만들어 현재 동작을 고정한다. 이 테스트들은 변경 전후로 깨지지 않아야 할 안정 동작만 단언한다(C/B의 새 동작은 Task 1·4가 추가).

**선행조건 (clean baseline 확인 — 리뷰 반영):** 착수 전 작업 트리가 플랜이 가정하는 baseline인지 확인한다. 다른 에이전트가 같은 트리를 동시에 변경 중이면 실행하지 않는다.

```bash
cd /Users/al03040455/Desktop/bb2_client
git diff --stat scripts/bb2_brain/schema.py scripts/bb2_brain/router.py   # 비어야 함(이 플랜이 처음 손대는 파일)
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/ -q  # 29 passed 확인
```

Expected: schema.py·router.py diff 없음(clean), `29 passed`. 둘 중 하나라도 어긋나면 멈추고 원인 확인(`git checkout`으로 복원하거나 동시 실행 에이전트 종료).

**Files:**
- Create: `scripts/bb2_brain/tests/test_status.py`
- Create: `scripts/bb2_brain/tests/test_schema.py`
- Create: `scripts/bb2_brain/tests/test_lint.py`
- Create: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: `test_status.py` 작성 (status.py 회귀 베이스라인)**

```python
"""status.py 회귀 베이스라인 (B+C 작업 선행). claim_status/answer_status는
신뢰 라벨 모델의 단일 진실 — spec §8에서 불변. C가 후보를 답 재료에 섞으면
answer_status가 candidate(severity 2) 이상을 반영해야 하므로 그 동작을 고정한다."""

import unittest

from scripts.bb2_brain.status import answer_status, claim_status


class TestClaimStatus(unittest.TestCase):
    def test_reviewed_with_available_raw(self):
        obj = {"status": "reviewed", "evidence_refs": ["ev.ref"]}
        self.assertEqual(claim_status(obj, raw_available=True, restricted=False), "reviewed")

    def test_reviewed_but_raw_missing(self):
        obj = {"status": "reviewed", "evidence_refs": ["ev.ref"]}
        self.assertEqual(claim_status(obj, raw_available=False, restricted=False), "raw-unavailable")

    def test_candidate(self):
        obj = {"status": "candidate"}
        self.assertEqual(claim_status(obj, raw_available=True, restricted=False), "candidate")

    def test_restricted_overrides(self):
        obj = {"status": "reviewed", "evidence_refs": ["ev.ref"]}
        self.assertEqual(claim_status(obj, raw_available=True, restricted=True), "restricted")


class TestAnswerStatus(unittest.TestCase):
    def test_empty_is_raw_only(self):
        self.assertEqual(answer_status([]), "raw-only")

    def test_max_severity_wins(self):
        self.assertEqual(answer_status(["reviewed", "candidate"]), "candidate")
        self.assertEqual(answer_status(["restricted", "candidate"]), "restricted")
        self.assertEqual(answer_status(["reviewed", "reviewed"]), "reviewed")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실행해서 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_status.py -v`
Expected: PASS (status.py는 변경 없음, 현재 동작 고정)

- [ ] **Step 3: `test_schema.py` 작성 (schema.py 회귀 베이스라인)**

`test_ingest.py`의 합성 헬퍼를 재사용한다(DRY — `test_cli.py`도 이미 그렇게 함).

```python
"""schema.py 회귀 베이스라인 (B+C 작업 선행). 현재 통과/거부 동작을 고정한다.
Task 4가 §6.4(reviewed DomainMapping·GlossaryTerm evidence_refs 강제)를 여기 확장."""

import unittest

from scripts.bb2_brain.schema import validate_object
from scripts.bb2_brain.tests.test_ingest import (
    candidate_mapping,
    candidate_term,
    context,
    manifest,
)


class TestValidateObject(unittest.TestCase):
    def test_valid_manifest_passes(self):
        self.assertEqual(validate_object(manifest()), [])

    def test_valid_candidate_term_passes(self):
        self.assertEqual(validate_object(candidate_term()), [])

    def test_missing_base_field_reported(self):
        bad = {"id": "bad", "kind": "GlossaryTerm"}
        errors = validate_object(bad)
        self.assertTrue(any("missing base field" in e for e in errors))

    def test_unknown_kind_reported(self):
        errors = validate_object({"id": "x", "kind": "Nope"})
        self.assertEqual(errors, ["x: unknown kind 'Nope'"])

    def test_invalid_status_reported(self):
        obj = candidate_term()
        obj["status"] = "bogus"
        errors = validate_object(obj)
        self.assertTrue(any("invalid status" in e for e in errors))

    def test_candidate_mapping_passes(self):
        # context_id resolve는 lint 몫 — schema는 객체 단위. 필수 필드만 본다.
        self.assertEqual(validate_object(candidate_mapping("m.x", glossary_term_ids=["g.x"])), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: 실행해서 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_schema.py -v`
Expected: PASS

- [ ] **Step 5: `test_lint.py` 작성 (lint.py 회귀 베이스라인)**

```python
"""lint.py 회귀 베이스라인 (B+C 작업 선행). 깨끗한 합성 store는 0 problem,
dangling evidence_ref는 1 problem. promote 사후 lint가 의존하는 동작을 고정한다."""

import unittest

from scripts.bb2_brain.lint import lint_store
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.tests.test_ingest import (
    candidate_term,
    evidence_ref,
    manifest,
)


def store_of(*objs):
    return BrainStore({o["id"]: o for o in objs})


class TestLintStore(unittest.TestCase):
    def test_clean_store_no_problems(self):
        store = store_of(manifest(), evidence_ref(), candidate_term())
        self.assertEqual(lint_store(store), [])

    def test_dangling_evidence_ref_reported(self):
        term = candidate_term()
        term["evidence_refs"] = ["ev.missing"]
        store = store_of(term)
        problems = lint_store(store)
        self.assertTrue(any("dangling evidence_ref ev.missing" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: 실행해서 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_lint.py -v`
Expected: PASS

- [ ] **Step 7: `test_router.py` 작성 (router.answer 회귀 베이스라인)**

읽기 전용 + 검수된 glossary 노출이라는, Task 1 이후에도 깨지면 안 되는 안정 동작만 고정한다. ("후보 미노출"은 Task 1이 뒤집을 동작이라 베이스라인에 넣지 않는다.)

```python
"""router.answer 회귀 베이스라인 (B+C 작업 선행). 읽기 전용 불변(answer 전후 store
불변) + 검수된 glossary 노출이라는 안정 동작을 고정한다. Task 1이 C(후보 노출)를
이 파일에 확장한다 — 후보 미노출 동작은 Task 1이 뒤집으므로 베이스라인에 넣지 않는다."""

import copy
import unittest

from scripts.bb2_brain.router import QueryRouter
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.tests.test_ingest import context


def store_of(*objs):
    return BrainStore({o["id"]: o for o in objs})


def reviewed_term_with_evidence(tid, term, *, evidence_refs):
    """근거 가진 reviewed GlossaryTerm (Task 4 §6.4 이후에도 유효하도록 evidence 보유)."""
    from scripts.bb2_brain.objbase import base
    return base(
        {
            "id": tid,
            "kind": "GlossaryTerm",
            "status": "reviewed",
            "truth_role": "domain",
            "title": f"Term: {term}",
            "context_id": "context.neutral",
            "term": term,
            "definition": f"{term} 검수 정의",
            "evidence_refs": evidence_refs,
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


class TestRouterReadOnly(unittest.TestCase):
    def test_answer_does_not_mutate_store(self):
        store = store_of(context(glossary_term_ids=["g.r"]),
                         reviewed_term_with_evidence("g.r", "갈고리", evidence_refs=[]))
        before = copy.deepcopy(store._objects)
        QueryRouter(store).answer("갈고리 용어 무슨 뜻?")
        self.assertEqual(store._objects, before)


class TestGlossaryReviewedExposure(unittest.TestCase):
    def test_reviewed_glossary_term_surfaces(self):
        store = store_of(context(glossary_term_ids=["g.r"]),
                         reviewed_term_with_evidence("g.r", "갈고리", evidence_refs=[]))
        answer = QueryRouter(store).answer("갈고리 용어 무슨 뜻?")
        self.assertIn("glossary_meaning", answer["intents"])
        self.assertIn("g.r", answer["source_object_ids"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 8: 실행해서 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_router.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: 전체 스위트 실행 — 회귀 없음 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/ -q`
Expected: 기존 29 그대로 통과 + 신규 16(status 6 = TestClaimStatus 4 + TestAnswerStatus 2 / schema 6 / lint 2 / router 2) = **45 passed**. (정확 합계는 실행으로 확정 — 핵심은 기존 29가 불변인 것.)

- [ ] **Step 10: 커밋 (삭제된 7개 테스트 + 7개 fixture의 staged 삭제 포함)**

spec §9 단계0: "누락된 삭제 커밋은 이번 작업 커밋에 포함." Task 0이 재생성하는 4개(router/status/schema/lint)는 staged 삭제(D)가 새 내용으로 해소되고, 재생성 안 하는 3개(store/intent/context_projection)는 순수 삭제로 남는다. `git add -A`로 신규+삭제+fixture를 한 번에 스테이징하고 커밋 전 `git status`로 눈으로 확인한다(리뷰 반영 — 파일을 두 그룹에 중복 기재하지 않음).

```bash
# .py만 스테이징(__pycache__/*.pyc 빌드 산출물 제외 — 리뷰 minor 반영). 삭제 3개(store/intent/
# context_projection)는 이미 staged(D)라 자동 포함, fixture 삭제는 별도 add.
git add scripts/bb2_brain/tests/*.py
git add scripts/bb2_brain/tests/fixtures
git status --short scripts/bb2_brain/tests/   # 신규 4 + 삭제 3 + fixture 삭제 확인, .pyc 안 잡혔는지 확인
git commit -m "test(brain): regression baselines for router/status/schema/lint; drop stale test files"
```

> **주의(사용자 확인 필요):** `git status`상 `cli.py`(M)와 엔진 파일(`ingest.py`/`objbase.py`/`promote.py`)·일부 테스트가 아직 미커밋(universal-ingest 이전 작업분)이다. 이들을 이 커밋에 포함할지 별도로 둘지는 커밋 위생 결정이라 사용자에게 확인한다(메모리 `feedback_brain_branch_auto_commit`: brain 소스만 검증 후 auto-commit OK). 위 `git add`는 Task 0 산출물 + staged 삭제만 명시한다.

---

## Task 1: C — 저신뢰 노출 + 승격 후보 필드 (router)

`glossary_meaning` 의도에서 candidate GlossaryTerm 정의를 "확인 필요" 라벨로 노출하고, 답 dict에 승격 후보 전용 필드를 더한다. 후보는 노출 재료로만 합류하고 충돌·추론 로직 입력에는 넣지 않는다(spec §4.2).

**Files:**
- Modify: `scripts/bb2_brain/router.py:48-53` (초기화 블록), `:174-197` (glossary_meaning 분기), `:236-246` (답 dict), 신규 메서드 1개
- Test: `scripts/bb2_brain/tests/test_router.py` (Task 0 파일에 추가)

- [ ] **Step 1: 실패 테스트 작성 — candidate 정의 노출 + needs_clarification + 격리**

`test_router.py`에 추가:

```python
def candidate_term_inline(tid, term, *, definition="후보 정의", aliases=None):
    """노출 대상 candidate GlossaryTerm (매칭용 term/aliases 보유)."""
    from scripts.bb2_brain.objbase import base
    obj = {
        "id": tid,
        "kind": "GlossaryTerm",
        "status": "candidate",
        "truth_role": "domain",
        "title": f"Candidate term: {term}",
        "context_id": "context.neutral",
        "term": term,
        "definition": definition,
        "candidate": {"candidate_state": "ready_for_review", "candidate_source": "spec"},
    }
    if aliases is not None:
        obj["aliases"] = aliases
    return base(obj, tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z")


class TestCandidateExposure(unittest.TestCase):
    def test_only_candidate_exposed_with_clarification(self):
        # 후보만 매칭(매칭된 검수 매핑 없음) → 후보 노출 + needs_clarification=True.
        # ★context()(reviewed DomainContext)를 일부러 둔다 — 실코퍼스에도 reviewed DomainContext가
        #   상존해 source_ids가 안 비므로, (not source_ids)가 아니라 명시 clarification_needed로
        #   §4.3이 작동함을 이 픽스처가 증명한다(리뷰 critical 반영).
        store = store_of(context(glossary_term_ids=[]),
                         candidate_term_inline("g.c", "갈고리"))
        answer = QueryRouter(store).answer("갈고리 용어 무슨 뜻?")
        gloss = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
        cand_ids = [c["id"] for c in gloss["candidate_terms"]]
        self.assertIn("g.c", cand_ids)
        self.assertEqual(gloss["candidate_terms"][0]["trust_label"], "확인 필요")
        # 후보 정의가 실제로 노출됨(silent 제거)
        self.assertEqual(gloss["candidate_terms"][0]["definition"], "후보 정의")
        # 후보 전용 필드에 승격 후보 번호
        self.assertIn("g.c", answer["promotable_candidate_ids"])
        # 후보만 노출 → 검수된 source 없음 → needs_clarification
        self.assertNotIn("g.c", answer["source_object_ids"])
        self.assertTrue(answer["needs_clarification"])
        # 답 전체 라벨은 candidate(severity 2) 이상
        self.assertEqual(answer["status"], "candidate")
        # 담담한 단서 한 줄
        self.assertTrue(any("확인 필요한 후보 항목 포함" in w for w in answer["warnings"]))

    def test_alias_matches_candidate(self):
        store = store_of(context(glossary_term_ids=[]),
                         candidate_term_inline("g.a", "카누 레이스", aliases=["샐리의 카누"]))
        answer = QueryRouter(store).answer("샐리의 카누 용어 무슨 뜻?")
        gloss = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
        self.assertIn("g.a", [c["id"] for c in gloss["candidate_terms"]])

    def test_irrelevant_candidate_not_exposed(self):
        # 질의에 안 나오는 term은 노출 안 함(노이즈 배제)
        store = store_of(context(glossary_term_ids=[]),
                         candidate_term_inline("g.c", "갈고리"),
                         candidate_term_inline("g.z", "전혀다른용어"))
        answer = QueryRouter(store).answer("갈고리 용어 무슨 뜻?")
        gloss = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
        ids = [c["id"] for c in gloss["candidate_terms"]]
        self.assertIn("g.c", ids)
        self.assertNotIn("g.z", ids)

    def test_candidate_not_fed_into_conflict_resolution(self):
        # glossary_meaning + current_status를 함께 유발하는 질의.
        # current_status 분기의 kept/conflicts에 candidate가 절대 안 섞여야 함(spec §4.2).
        store = store_of(context(glossary_term_ids=[]),
                         candidate_term_inline("g.c", "갈고리"))
        answer = QueryRouter(store).answer("갈고리 용어 현재 규칙 무슨 뜻?")
        current = next(s for s in answer["sections"] if s["intent"] == "current_status")
        self.assertNotIn("g.c", current["object_ids"])
        for entry in current.get("conflicts", []):
            self.assertNotIn("g.c", entry["fact_ids"])
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_router.py::TestCandidateExposure -v`
Expected: FAIL — `KeyError: 'candidate_terms'` / `KeyError: 'promotable_candidate_ids'` (아직 미구현)

- [ ] **Step 3: `promotable_ids` 초기화 추가**

`scripts/bb2_brain/router.py`의 `answer()` 초기화 블록(현재 48-53행) 수정:

```python
        candidate_ids: list[str] = []
        promotable_ids: list[str] = []
        source_ids: list[str] = []
        sections: list[dict] = []
        claim_statuses: list[str] = []
        warnings: list[str] = []
        clarification_needed = False
```

- [ ] **Step 4: `_matched_candidate_terms` 메서드 추가**

`_matched_glossary_terms`(현재 281-296행) 바로 뒤에 추가:

```python
    def _matched_candidate_terms(self, query: str) -> list[dict]:
        """query 텍스트에 term/synonyms/aliases가 등장하는 candidate GlossaryTerm.
        노출 전용(spec §4.2) — 충돌 해소·scope 추론 입력에는 절대 넣지 않는다.
        검수된 GlossaryTerm은 제외(이미 _reviewed_by_kind 경로로 노출됨)."""
        result = []
        for term in self.store.by_kind("GlossaryTerm"):
            if term.get("status") != "candidate":
                continue
            surfaces = {term.get("term")}
            surfaces.update(term.get("synonyms") or [])
            surfaces.update(term.get("aliases") or [])
            if any(surface and surface in query for surface in surfaces):
                result.append(term)
        return result
```

- [ ] **Step 5: glossary_meaning 분기에 candidate 노출 추가**

`scripts/bb2_brain/router.py`의 glossary_meaning 분기(현재 174-197행)에서, 검수된 `glossary_objects` 루프 다음·`summary`/`sections.append` 직전에 candidate 수집을 끼운다. 최종 형태:

```python
            elif intent == "glossary_meaning":
                # spec §7: "내가 이 용어 말하면 무슨 뜻?" → reviewed DomainMapping 우선, GlossaryTerm은 alias.
                matched_mappings = self._matched_mappings(canonical)
                section_ids: list[str] = []
                mapping_details = []
                for mapping in matched_mappings:
                    source_ids.append(mapping["id"])
                    section_ids.append(mapping["id"])
                    claim_statuses.append(claim_status(mapping, raw_available=self._raw_available_for(mapping), restricted=self._restricted_for(mapping)))
                    mapping_details.append({
                        "id": mapping["id"],
                        "mapping_key": mapping.get("mapping_key"),
                        "meaning": mapping.get("meaning", ""),
                        "boundary": mapping.get("boundary", ""),
                        "caveats": mapping.get("caveats") or [],
                        "code_locator_ids": mapping.get("code_locator_ids") or [],
                    })
                glossary_objects = self._reviewed_by_kind("DomainContext") + self._reviewed_by_kind("GlossaryTerm")
                for obj in glossary_objects:
                    source_ids.append(obj["id"])
                    section_ids.append(obj["id"])
                    claim_statuses.append(claim_status(obj, raw_available=self._raw_available_for(obj), restricted=False))
                # C (spec §4.2): candidate GlossaryTerm 정의를 "확인 필요" 라벨로 노출.
                # source_ids에 넣지 않아 needs_clarification 식(§4.3)을 보존하고,
                # 별도 수집기(매칭만)라 충돌·scope 추론 입력에는 들어가지 않는다.
                candidate_details = []
                for term in self._matched_candidate_terms(canonical):
                    promotable_ids.append(term["id"])
                    claim_statuses.append(claim_status(term, raw_available=self._raw_available_for(term), restricted=self._restricted_for(term)))
                    candidate_details.append({
                        "id": term["id"],
                        "term": term.get("term"),
                        "definition": term.get("definition", ""),
                        "trust_label": "확인 필요",
                    })
                if candidate_details:
                    warnings.append("확인 필요한 후보 항목 포함 — 사용 시점에 확정(promote) 가능")
                    # spec §4.3: 후보만 노출되고 매칭된 검수 답(matched_mappings)이 없으면 사람 확인 유도.
                    # (not source_ids)에 기대지 않는다 — reviewed DomainContext가 매칭 무관하게
                    # source_ids에 무조건 들어가(router.py:191-195) 실코퍼스에서도 source_ids는 안 빈다.
                    if not matched_mappings:
                        clarification_needed = True
                summary = "Glossary definition (reviewed mappings prioritized)" if matched_mappings else "Glossary definition"
                # 검수/후보 구분은 키로: object_ids·mappings = 검수됨, candidate_terms = 후보(각 trust_label).
                sections.append({
                    "intent": intent,
                    "object_ids": section_ids,
                    "mappings": mapping_details,
                    "candidate_terms": candidate_details,
                    "summary": summary,
                })
```

- [ ] **Step 6: 답 dict에 `promotable_candidate_ids` 추가**

`scripts/bb2_brain/router.py`의 return 문(현재 236-246행) 수정:

```python
        return {
            "query": query,
            "canonical_query": classified.normalized.canonical_query,
            "intents": classified.intents,
            "status": answer_status(claim_statuses),
            "candidate_object_ids": sorted(set(candidate_ids)),
            "promotable_candidate_ids": sorted(set(promotable_ids)),
            "source_object_ids": sorted(set(source_ids)),
            "sections": sections,
            "warnings": warnings,
            "needs_clarification": (not source_ids) or clarification_needed,
        }
```

- [ ] **Step 7: 실행해서 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_router.py -v`
Expected: PASS (TestRouterReadOnly + TestGlossaryReviewedExposure + TestCandidateExposure 전부)

- [ ] **Step 8: 전체 스위트 — 회귀 없음 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/ -q`
Expected: 전부 통과. 특히 `test_universal_ingest_e2e.py`의 `assertIn("mapping.cooltime", answer["source_object_ids"])`(L555)가 그대로 통과(후보는 `promotable_candidate_ids`로 가고 source_object_ids는 불변).

- [ ] **Step 9: 커밋**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat(brain): expose candidate glossary terms with 확인필요 label (C); add promotable_candidate_ids"
```

---

## Task 2: 사용 시점 promote — `cli promote` 신설

답하다 사람이 "맞다" 하면 그 자리에서 후보를 검수됨으로 확정하는 CLI. `promote.py`가 반환하는 (승격 객체, 검토 기록)을 **둘 다** `save_object`로 저장하고 사후 lint 1회를 돈다(spec §5.2).

**Files:**
- Modify: `scripts/bb2_brain/cli.py` (import 추가, `_run_promote` 신설, `main` 분기 추가)
- Test: `scripts/bb2_brain/tests/test_cli.py` (기존 파일에 추가)

- [ ] **Step 1: 실패 테스트 작성 — promote 왕복 + 검토 기록 동반 저장**

`test_cli.py`에 추가. 승격 대상 candidate는 **evidence_refs를 보유**하게 만든다(Task 4 §6.4 이후에도 사후 lint를 통과하도록 forward-compatible). `test_ingest`의 `manifest`/`evidence_ref`를 재사용.

```python
def candidate_term_with_evidence(tid="g.x", term="갈고리"):
    """근거(ev.ref) 보유 candidate GlossaryTerm. promote 후 §6.4(reviewed 근거 필수)를 통과한다."""
    from scripts.bb2_brain.objbase import base
    return base(
        {
            "id": tid,
            "kind": "GlossaryTerm",
            "status": "candidate",
            "truth_role": "domain",
            "title": f"Candidate term: {term}",
            "context_id": "context.neutral",
            "term": term,
            "definition": "후보 정의",
            "evidence_refs": ["ev.ref"],
            "candidate": {"candidate_state": "ready_for_review", "candidate_source": "spec"},
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


class TestCliPromote(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _ingest(self):
        from scripts.bb2_brain.ingest import ingest
        ingest(self.root, [manifest(), evidence_ref(), candidate_term_with_evidence()])

    def test_promote_round_trip(self):
        self._ingest()
        # promote 전: 후보가 candidate로 노출
        self.assertEqual(BrainStore.load(self.root).get("g.x")["status"], "candidate")
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.x", "--reviewer", "user-confirmed",
            "--reviewed-at", "2026-06-06T00:00:00Z",
        ]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])
        store = BrainStore.load(self.root)
        # 승격 객체 + 검토 기록 둘 다 저장됨
        self.assertEqual(store.get("g.x")["status"], "reviewed")
        self.assertEqual(store.get("g.x")["review_record_id"], "review.g.x")
        self.assertTrue(store.has("review.g.x"))
        # 없는 기록 가리킴 0건(사후 lint clean)
        from scripts.bb2_brain.lint import lint_store
        self.assertEqual(lint_store(store), [])

    def test_promote_missing_id_returns_error(self):
        self._ingest()
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.nope", "--reviewer", "user-confirmed",
            "--reviewed-at", "2026-06-06T00:00:00Z",
        ]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)

    def test_promote_requery_moves_candidate_to_reviewed(self):
        # spec §5.3 루프 폐쇄: 질의(후보) → promote → 재질의(검수). 리뷰 minor 반영.
        from scripts.bb2_brain.router import QueryRouter
        self._ingest()  # candidate g.x (term=갈고리, evidence 보유) + manifest + ref
        before = QueryRouter(BrainStore.load(self.root)).answer("갈고리 용어 무슨 뜻?")
        self.assertIn("g.x", before["promotable_candidate_ids"])
        self.assertNotIn("g.x", before["source_object_ids"])
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.x", "--reviewer", "user-confirmed",
            "--reviewed-at", "2026-06-06T00:00:00Z",
        ]
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        after = QueryRouter(BrainStore.load(self.root)).answer("갈고리 용어 무슨 뜻?")
        # 승격 후: 후보에서 빠지고 검수 source로(reviewed GlossaryTerm은 glossary_objects 덤프로 노출)
        self.assertNotIn("g.x", after["promotable_candidate_ids"])
        self.assertIn("g.x", after["source_object_ids"])
```

`candidate_term_with_evidence`는 위 Step 1에서 정의한 헬퍼다(term="갈고리", evidence_refs=["ev.ref"]). `test_cli.py` 상단 import에 `evidence_ref`가 이미 있는지 확인하고 없으면 추가(`from ...test_ingest import candidate_term, context, evidence_ref, manifest`).

- [ ] **Step 2: 실행해서 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_cli.py::TestCliPromote -v`
Expected: FAIL — `parser.error` 또는 query 경로로 falling through (promote 분기 없음)

- [ ] **Step 3: cli.py에 import 추가**

`scripts/bb2_brain/cli.py` 상단 import 블록(현재 6-8행) 수정:

```python
from scripts.bb2_brain.ingest import IngestError, ingest
from scripts.bb2_brain.lint import lint_store
from scripts.bb2_brain.promote import promote
from scripts.bb2_brain.router import QueryRouter
from scripts.bb2_brain.schema import validate_object
from scripts.bb2_brain.store import BrainStore
```

(SchemaError는 import하지 않는다 — `_run_promote`는 `save_object`가 던질 SchemaError를 잡는 게 아니라 쓰기 전에 `validate_object`가 돌려주는 오류 목록으로 막으므로 불필요. 리뷰 false_positive 반영.)

- [ ] **Step 4: `_run_promote` 함수 추가**

`_run_ingest` 다음(현재 42행 뒤)에 추가:

```python
def _run_promote(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli promote")
    parser.add_argument("--brain-root", required=True)
    parser.add_argument("--ids", required=True, nargs="+")
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--scope", default="single_object",
                        choices=["single_object", "mapping_bundle"])
    parser.add_argument("--bundle-key")
    args = parser.parse_args(argv)

    brain_root = Path(args.brain_root)
    store = BrainStore.load(brain_root)
    missing = [i for i in args.ids if not store.has(i)]
    if missing:
        print(json.dumps({"ok": False, "error": f"unknown ids: {missing}"},
                         ensure_ascii=False, indent=2))
        return 1
    objects = [store.get(i) for i in args.ids]
    # promote.py: (승격 객체, 검토 기록) 둘 다 반환 — 둘 다 저장해야 검토 기록 참조가 살아남는다(§5.2).
    # bundle_key 누락·잘못된 scope 등은 promote가 ValueError로 알리므로 잡아 rc=1로 돌린다(리뷰 minor 반영).
    try:
        promoted, records = promote(
            objects, args.ids, args.scope,
            bundle_key=args.bundle_key, reviewer=args.reviewer, reviewed_at=args.reviewed_at,
        )
    except (ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    # ★원자성(리뷰 major 반영): 디스크에 쓰기 전 일괄 schema 검증. zero-evidence 승격(§6.4 위반)을
    #   여기서 막아 부분 쓰기/미포착 SchemaError를 방지한다. save_object도 validate하지만 첫 객체를
    #   이미 쓴 뒤 터지면 원자성이 깨지므로 선검증한다.
    to_write = promoted + records
    schema_errors = []
    for obj in to_write:
        schema_errors.extend(validate_object(obj))
    if schema_errors:
        print(json.dumps({"ok": False, "error": "; ".join(schema_errors)}, ensure_ascii=False, indent=2))
        return 1
    for obj in to_write:
        BrainStore.save_object(brain_root, obj)
    problems = lint_store(BrainStore.load(brain_root))  # 사후 lint 1회(참조 무결성)
    if problems:
        print(json.dumps({"ok": False, "lint": problems}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(
        {"ok": True, "promoted": [o["id"] for o in promoted], "reviews": [r["id"] for r in records]},
        ensure_ascii=False, indent=2))
    return 0
```

- [ ] **Step 5: `main` 분기 추가**

`scripts/bb2_brain/cli.py`의 `main()`(현재 44-49행) 수정:

```python
def main() -> int:
    argv = sys.argv[1:]
    # 첫 인자가 서브커맨드면 해당 경로, 아니면 기존 query 경로 호환 유지(AC6)
    if argv and argv[0] == "ingest":
        return _run_ingest(argv[1:])
    if argv and argv[0] == "promote":
        return _run_promote(argv[1:])
    return _run_query(argv)
```

- [ ] **Step 6: 실행해서 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_cli.py -v`
Expected: PASS (기존 2 + TestCliPromote 3: round_trip / missing_id / requery_moves_candidate)

- [ ] **Step 7: 전체 스위트 — 회귀 없음**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/ -q`
Expected: 전부 통과

- [ ] **Step 8: 커밋**

```bash
git add scripts/bb2_brain/cli.py scripts/bb2_brain/tests/test_cli.py
git commit -m "feat(brain): add 'cli promote' for use-time candidate promotion (saves object + review record, post-lint)"
```

---

## Task 3: 사용 시점 promote 수동 검증 (실코퍼스, 선택적 — 코드 변경 없음)

코드 변경 없이 실데이터로 C→promote 루프를 1회 손으로 확인한다. brain/는 git 미추적이라 커밋 무관. 실패하면 Task 1·2로 되돌아간다. (자동 테스트가 이미 합성으로 같은 경로를 검증하므로 이 Task는 선택적 — 사용자가 실데이터 회상을 보고 싶을 때만.)

- [ ] **Step 1: 실코퍼스에서 candidate 용어 질의 → 후보 노출 확인**

실코퍼스 candidate GlossaryTerm 하나의 term을 골라 질의한다(예: store에서 candidate term 하나의 `term` 값 확인 후 사용).

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python - <<'PY'
import json, pathlib
from scripts.bb2_brain.router import QueryRouter
from scripts.bb2_brain.store import BrainStore
store = BrainStore.load(pathlib.Path("scripts/bb2_brain/brain"))
# candidate term 하나의 표면어 추출
cand = next(o for o in store.by_kind("GlossaryTerm") if o.get("status") == "candidate")
term = cand["term"]
answer = QueryRouter(store).answer(f"{term} 용어 무슨 뜻?")
print("promotable_candidate_ids:", answer["promotable_candidate_ids"][:5])
print("needs_clarification:", answer["needs_clarification"])
gloss = next((s for s in answer["sections"] if s["intent"] == "glossary_meaning"), None)
print("candidate_terms count:", len(gloss["candidate_terms"]) if gloss else 0)
PY
```

Expected: `promotable_candidate_ids`에 후보가 잡히고 `candidate_terms`에 정의가 노출됨.

> 이 Task는 산출물·커밋이 없다(읽기 전용 실증). 통과 못 하면 Task 1로 회귀.

---

## Task 4: B — §6.4 근거 강제 schema + 기존 reviewed 점검(§7)

검수된 DomainMapping·GlossaryTerm은 `evidence_refs`가 비면 안 된다(코드앵커는 비강제). 사전 측정대로 이 규칙은 기존 합성 테스트 6개 + 실코퍼스 1건을 건드린다 — 헬퍼를 새 불변조건에 맞추고, 실코퍼스 1건은 backfill한다.

**Files:**
- Modify: `scripts/bb2_brain/schema.py` (GlossaryTerm 분기 + DomainMapping 분기에 규칙 추가)
- Modify: `scripts/bb2_brain/tests/test_ingest.py` (`reviewed_term` 헬퍼 + 3개 테스트)
- Modify: `scripts/bb2_brain/tests/test_promote.py` (candidate 헬퍼 2개)
- Modify: `scripts/bb2_brain/tests/test_schema.py` (§6.4 신규 테스트)
- Modify: `scripts/bb2_brain/brain/objects/domain/g.sally-canoe.naming-canoe-race.json` (backfill, git 미추적)

- [ ] **Step 1: 실패 테스트 작성 — §6.4 규칙**

`test_schema.py`에 추가:

```python
class TestEvidenceGate(unittest.TestCase):
    def test_reviewed_glossary_term_requires_evidence(self):
        from scripts.bb2_brain.tests.test_ingest import reviewed_term
        obj = reviewed_term("g.noev")
        obj["evidence_refs"] = []
        errors = validate_object(obj)
        self.assertTrue(any("reviewed GlossaryTerm requires non-empty evidence_refs" in e for e in errors))

    def test_reviewed_glossary_term_with_evidence_passes(self):
        from scripts.bb2_brain.tests.test_ingest import reviewed_term
        obj = reviewed_term("g.ev")
        obj["evidence_refs"] = ["ev.ref"]
        self.assertEqual(validate_object(obj), [])

    def test_reviewed_mapping_requires_evidence(self):
        m = candidate_mapping("m.noev", glossary_term_ids=["g.x"])
        m["status"] = "reviewed"
        m["evidence_refs"] = []
        errors = validate_object(m)
        self.assertTrue(any("reviewed DomainMapping requires non-empty evidence_refs" in e for e in errors))

    def test_reviewed_mapping_with_evidence_but_no_code_locator_passes(self):
        # 서버규칙: 코드앵커 없어도 근거 있으면 통과(spec §6.1)
        m = candidate_mapping("m.server", glossary_term_ids=["g.x"])
        m["status"] = "reviewed"
        m["evidence_refs"] = ["ev.ref"]
        m["code_locator_ids"] = []
        self.assertEqual(validate_object(m), [])

    def test_candidate_without_evidence_still_valid(self):
        # 후보는 근거 강제 안 함(C로 노출되는 게 정상) — candidate는 evidence 빈 채로 OK
        obj = candidate_term()
        obj["evidence_refs"] = []
        self.assertEqual(validate_object(obj), [])
```

- [ ] **Step 2: 실행해서 실패 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_schema.py::TestEvidenceGate -v`
Expected: FAIL — `test_reviewed_glossary_term_requires_evidence`·`test_reviewed_mapping_requires_evidence` 가 빈 errors 받음(규칙 미구현)

- [ ] **Step 3: schema.py GlossaryTerm 분기에 규칙 추가**

`scripts/bb2_brain/schema.py`의 GlossaryTerm 분기 끝(현재 178-179행 `rejected GlossaryTerm requires rejection metadata` 직후)에 추가:

```python
        if obj.get("status") == "rejected" and not obj.get("rejection"):
            errors.append(f"{obj['id']}: rejected GlossaryTerm requires rejection metadata")
        if obj.get("status") == "reviewed" and not obj.get("evidence_refs"):
            errors.append(f"{obj['id']}: reviewed GlossaryTerm requires non-empty evidence_refs")
```

- [ ] **Step 4: schema.py DomainMapping 분기에 규칙 추가**

`scripts/bb2_brain/schema.py`의 DomainMapping 분기 끝(현재 207-208행 `review_state {rs_key!r} must be boolean` 직후)에 추가:

```python
                    elif not isinstance(rs_val, bool):
                        errors.append(f"{obj['id']}: DomainMapping review_state {rs_key!r} must be boolean")
        if obj.get("status") == "reviewed" and not obj.get("evidence_refs"):
            errors.append(f"{obj['id']}: reviewed DomainMapping requires non-empty evidence_refs")
```

> 주의: 이 줄은 `for rs_key, rs_val ...` 루프 **밖**, DomainMapping `elif` 블록 안에 있어야 한다(들여쓰기 8칸 = `elif kind == "DomainMapping":` 본문 레벨). review_state가 없는 매핑도 이 검사를 받아야 한다.

- [ ] **Step 5: §6.4 신규 테스트 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/test_schema.py::TestEvidenceGate -v`
Expected: PASS (5 tests)

- [ ] **Step 6: 깨진 기존 테스트 6개 수정 — test_ingest.py `reviewed_term` 헬퍼**

`scripts/bb2_brain/tests/test_ingest.py`의 `reviewed_term`(현재 81-95행)에 `evidence_refs` 기본값 추가:

```python
def reviewed_term(tid="g.x", *, term="용어", review_record_id=None, evidence_refs=None):
    """중립 reviewed GlossaryTerm 한 개(candidate 메타 없음). §6.4: reviewed는 근거 필수."""
    obj = {
        "id": tid,
        "kind": "GlossaryTerm",
        "status": "reviewed",
        "truth_role": "domain",
        "title": "Term: 용어",
        "context_id": "context.neutral",
        "term": term,
        "definition": "중립 정의",
        "evidence_refs": evidence_refs if evidence_refs is not None else ["ev.ref"],
    }
    if review_record_id is not None:
        obj["review_record_id"] = review_record_id
    return base(obj, tags=["neutral"], created_at=T, updated_at=T)
```

(`base()`의 `evidence_refs` setdefault는 이미 채워진 키를 안 덮으므로 위 값이 유지된다.)

- [ ] **Step 7: test_ingest.py의 3개 테스트가 ev.ref를 store에 동봉하도록 수정**

`reviewed_term`이 `ev.ref`를 가리키므로, ingest 시 lint(참조 무결성)가 통과하려면 `manifest()`+`evidence_ref()`를 같은 store/bundle에 둬야 한다.

`test_ingest_allows_candidate_to_reviewed`(현재 199-206행):

```python
    def test_ingest_allows_candidate_to_reviewed(self):
        ingest(self.root, [manifest(), evidence_ref(), candidate_term()])
        # 같은 id를 reviewed로 ingest(승격). reviewed_term은 ev.ref(이미 store에) 참조 → §6.4·lint 통과
        rr = review_record_for("review.g.x", "g.x")
        ingest(self.root, [reviewed_term(review_record_id="review.g.x"), rr])
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.x")["status"], "reviewed")
        self.assertTrue(store.has("review.g.x"))
```

`test_ingest_rejects_reviewed_to_candidate_demotion`(현재 208-216행):

```python
    def test_ingest_rejects_reviewed_to_candidate_demotion(self):
        rr = review_record_for("review.g.x", "g.x")
        ingest(self.root, [manifest(), evidence_ref(), reviewed_term(review_record_id="review.g.x"), rr])
        # 같은 id를 candidate로 덮으려 하면 거부(후퇴 가드)
        with self.assertRaises(IngestError):
            ingest(self.root, [candidate_term()])
        # 기존 reviewed 보존
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.x")["status"], "reviewed")
```

`test_ingest_reviewed_to_reviewed_ok`(현재 218-223행):

```python
    def test_ingest_reviewed_to_reviewed_ok(self):
        rr = review_record_for("review.g.x", "g.x")
        ingest(self.root, [manifest(), evidence_ref(), reviewed_term(review_record_id="review.g.x"), rr])
        # 다시 reviewed로 ingest(멱등) — 성공
        ingest(self.root, [reviewed_term(review_record_id="review.g.x"), rr])
        self.assertEqual(BrainStore.load(self.root).get("g.x")["status"], "reviewed")
```

- [ ] **Step 8: test_promote.py의 candidate 헬퍼 2개에 evidence_refs 추가**

`scripts/bb2_brain/tests/test_promote.py`의 `candidate_term`(현재 15-36행) dict에 `evidence_refs` 추가:

```python
    return base(
        {
            "id": tid,
            "kind": "GlossaryTerm",
            "status": "candidate",
            "truth_role": "domain",
            "title": title,
            "context_id": "context.neutral",
            "term": term,
            "definition": "중립 정의",
            "evidence_refs": ["ev.ref"],
            "candidate": candidate,
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )
```

`candidate_mapping`(현재 94-112행) dict에 `evidence_refs` 추가:

```python
    return base(
        {
            "id": mid,
            "kind": "DomainMapping",
            "status": "candidate",
            "truth_role": "domain",
            "title": title,
            "context_id": "context.neutral",
            "mapping_key": mapping_key,
            "canonical_summary": "중립 요약",
            "meaning": "중립 의미",
            "boundary": "중립 경계",
            "glossary_term_ids": ["g.x"],
            "decision_record_ids": ["d.x"],
            "evidence_refs": ["ev.ref"],
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )
```

(promote가 `dict(obj)`로 evidence_refs를 그대로 복사하므로 승격된 reviewed 객체가 §6.4를 통과한다. validate_object는 참조 resolve를 보지 않으므로 dangling ev.ref여도 schema는 통과 — test_promote는 validate_object만 검사.)

- [ ] **Step 8b: zero-evidence cli promote 거부 테스트 추가 (§6.4 + 원자성 검증)**

§6.4가 켜진 지금, 근거 없는 후보를 승격하면 `_run_promote`의 쓰기 전 일괄 검증이 막아야 한다(리뷰 major 반영 — Task 2의 try/except + 선검증이 여기서 효과 발생). `test_cli.py`의 `TestCliPromote`에 추가:

```python
    def test_promote_zero_evidence_rejected(self):
        # §6.4 활성 후: 근거 없는 candidate(candidate엔 §6.4 미적용 → 적재는 됨)를 승격하면
        # 승격 결과물(reviewed, 근거 빔)이 쓰기 전 일괄 검증에 걸려 rc=1, 디스크 불변(원자성).
        from scripts.bb2_brain.ingest import ingest
        from scripts.bb2_brain.tests.test_ingest import candidate_term  # evidence_refs=[] 기본
        ingest(self.root, [candidate_term("g.noev")])
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.noev", "--reviewer", "user-confirmed",
            "--reviewed-at", "2026-06-06T00:00:00Z",
        ]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)
        result = json.loads(out.getvalue())
        self.assertFalse(result["ok"])
        self.assertIn("requires non-empty evidence_refs", result["error"])
        # 원자성: 거부됐으니 g.noev는 여전히 candidate(부분 쓰기·review 기록 생성 없음)
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.noev")["status"], "candidate")
        self.assertFalse(store.has("review.g.noev"))
```

> 이 테스트는 §6.4가 있어야 의미가 있어 Task 4(여기)에 둔다. Task 2 시점(게이트 전)엔 zero-evidence 승격이 성공해버려 이 단언이 실패하므로 Task 2에 넣지 않는다.

- [ ] **Step 9: 전체 스위트 — 6개 회귀 해소 + 신규 통과 확인**

Run: `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest scripts/bb2_brain/tests/ -q`
Expected: 전부 PASS (사전 측정의 6개 실패가 헬퍼 수정으로 해소됨 + §6.4 신규 5 + zero-evidence cli promote 1)

- [ ] **Step 10: 실코퍼스 lint — §6.4 위반 1건 노출 확인 (§7 점검)**

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python - <<'PY'
import pathlib
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.lint import lint_store
probs = lint_store(BrainStore.load(pathlib.Path("scripts/bb2_brain/brain")))
print("corpus lint problems:", len(probs))
for p in probs: print("  ", p)
PY
```

Expected: `1` — `g.sally-canoe.naming-canoe-race: reviewed GlossaryTerm requires non-empty evidence_refs` (사전 측정대로)

- [ ] **Step 11: 실코퍼스 backfill — naming 용어에 근거 연결 (§7, 강등 아님)**

이 용어는 강등 대상이 아니라 backfill 대상이다(짝 매핑이 같은 사실을 `evref.sally-canoe.naming-spec`·`naming-code`로 근거 댐, 두 evref 실재 확인됨).

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python - <<'PY'
import json, pathlib
from scripts.bb2_brain.store import BrainStore
root = pathlib.Path("scripts/bb2_brain/brain")
p = next(root.rglob("g.sally-canoe.naming-canoe-race.json"))
obj = json.loads(p.read_text(encoding="utf-8"))
# 짝 매핑 mapping.sally-canoe.event-naming이 쓰는 명칭 근거를 용어에도 연결
obj["evidence_refs"] = ["evref.sally-canoe.naming-spec", "evref.sally-canoe.naming-code"]
BrainStore.save_object(root, obj)  # validate_object 경유(§6.4 통과: 근거 non-empty)
print("backfilled:", obj["id"], "->", obj["evidence_refs"])
PY
```

Expected: `backfilled: g.sally-canoe.naming-canoe-race -> ['evref.sally-canoe.naming-spec', 'evref.sally-canoe.naming-code']`

- [ ] **Step 12: 실코퍼스 lint — 0건 확인 (§7 통과)**

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python - <<'PY'
import pathlib
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.lint import lint_store
probs = lint_store(BrainStore.load(pathlib.Path("scripts/bb2_brain/brain")))
print("corpus lint problems:", len(probs))
for p in probs: print("  ", p)
PY
```

Expected: `0`. (이제 근거 빈 검수됨 0건 — §7 점검 완료. 다른 근거 빈 reviewed DM/GT 없음은 사전 측정에서 확인.)

- [ ] **Step 13: 커밋 (코드 + 테스트만 — brain/는 git 미추적이라 자동 제외)**

```bash
git add scripts/bb2_brain/schema.py scripts/bb2_brain/tests/test_schema.py \
        scripts/bb2_brain/tests/test_ingest.py scripts/bb2_brain/tests/test_promote.py
git commit -m "feat(brain): enforce non-empty evidence_refs on reviewed DomainMapping/GlossaryTerm (B, §6.4); code-anchor not required"
```

> backfill한 `g.sally-canoe.naming-canoe-race.json`은 `scripts/bb2_brain/brain/`(git 미추적)이라 위 `git add`에 안 잡힌다. 데이터 수정은 store에만 반영(spec §7: "코퍼스 데이터 작업이지 코드 변경 아님").

---

## Self-Review (작성자 점검)

**1. Spec coverage:**
- §3 신뢰 라벨 불변 → Task 0 test_status가 고정, 코드 미변경 ✓
- §4 C 저신뢰 노출(검수 우선 + 후보 라벨 + 충돌 입력 격리) → Task 1 ✓
- §4.3 needs_clarification(후보만이면 True) → Task 1 Step 1 테스트 ✓
- §5 사용 시점 promote(전용 필드 + cli promote + 검토 기록 동반 저장) → Task 1(필드) + Task 2(cli) ✓
- §6 B 자동 승격(ingest 그대로) + §6.4 근거 강제 → Task 4 ✓
- §7 기존 reviewed 점검 → Task 4 Step 10-12(실코퍼스 1건 backfill) ✓
- §8 불변조건(라우터 읽기 전용) → Task 0 test_router + Task 1 ✓
- §9 단계 0/1/2 순서 → Task 0 → 1·2 → 4 ✓

**2. Placeholder scan:** 모든 코드 step에 실제 코드 블록. "적절한 에러 처리" 류 없음. ✓

**3. Type consistency:** `promotable_candidate_ids`(답 dict 키)·`candidate_terms`/`trust_label`(section 키, 항목별 "확인 필요")·`_matched_candidate_terms`(메서드명)·`promote(objects, ids, scope, *, bundle_key, reviewer, reviewed_at)`(promote.py 실제 시그니처와 일치) 일관. cli promote의 인자명 `--reviewed-at`→argparse가 `args.reviewed_at`으로 받음 ✓. `reviewed_trust_label`은 두지 않음(리뷰 반영, 검수/후보 구분은 키로) — 구현·테스트·self-review 어디에도 잔재 없음 ✓.

**4. 사전 측정 반영:** §6.4가 깨뜨리는 기존 6개 테스트를 Task 4 Step 6-8에서 정확히 수정. 실코퍼스 1건을 Step 11에서 backfill. ✓

---

## 미해결·후속 (이 플랜 범위 밖)

- **빌드 3 (bb2-brain-ingest 스킬 문구 B+C 재서술)** — 코드 확정 후, 사용자 승인 후(spec §2 비범위).
- **design-hub §8/§227 갱신** — 검수 자격을 "검증된 근거+적대검증"으로 보강(spec §0 후속).
- **고아 검토기록 lint 검사 추가** — §7 강등 대상 0건이라 당장 미발동(spec §11).
- **미커밋 universal-ingest 엔진 파일 처리** — Task 0 주의 박스 참조, 사용자 커밋 위생 결정.
- **사용 시점 supersede("틀리다, 이게 맞다") 경로** — 이번엔 "맞다→승격"만, supersede는 후속(spec §11).
