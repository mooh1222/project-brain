# Insight Kind Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** project-brain 엔진에 신설 `Insight` kind(여러 객체·구현·결정을 가로지르는 관찰/위험/교훈)를 추가하고, 일반 검색 결과에 섞이지 않는 별도 회상 통로(advisories)로 노출한다.

**Architecture:** 기존 18종 kind 옆에 `Insight`(truth_role=`synthesis` 재사용)를 더한다. 검색층은 raw 청크 레인과 동형으로 Insight를 **별도 레인**으로 분리해 객체 융합·그래프 재정렬을 흔들지 않고(C2), `eval_recall`은 kind 기반 **advisories 채널**로 가른다(C1). 표면 추출기 등록은 색인 진입이므로, 실코퍼스 Insight 적재는 엔진 전체 머지 뒤로 미룬다.

**Tech Stack:** Python 3.11, src 레이아웃 패키지 `project_brain`, unittest + pytest, SQLite FTS5(BM25) + sqlite-vec(벡터) + RRF 융합. 엔진 레포 `~/Downloads/codes/project-brain`, 데이터 레포 `~/Desktop/bb2_client/brain`.

---

## 설계 모호성 해소 (spec → plan 정밀화)

구현 전 spec과 실제 코드를 대조해 확정한 결정 3건. spec과 어긋나지 않고 정밀화한 것이다.

**1. surface 등록 "맨 마지막"(spec 4.6)의 재해석 — 코드는 먼저, 색인 진입은 마지막.**
spec 4.6은 표면 추출기 등록을 맨 마지막에 두라 한다(근거: "분리 없이 등록하면 일반 답에 샌다"). 그러나 TDD에서는 표면 추출기가 있어야 Insight를 색인해 레인·채널을 검증할 수 있다. 핵심: **실코퍼스에 Insight 객체가 0건이면 추출기를 먼저 등록해도 색인에 Insight 행이 안 생긴다**(`extract_surface`는 객체가 있어야 표면을 만들고, `rebuild`는 `store.all()`을 돈다 — search_index.py:144). 따라서:
- 코드 작성 순서는 추출기(Task 4) → 레인(Task 5) → 채널(Task 6) → router(Task 7)로 둔다.
- spec의 불변("분리 없이 색인 진입 금지")은 **실코퍼스에 Insight를 적재·rebuild하는 것을 엔진 8개 Task 전부 머지된 뒤(Task 8 회귀 통과 후)로 미루는 것**으로 보장한다. 그 적재는 이 plan의 범위 밖(실사용)이다.
- 엔진 main에 추출기만 등록된 중간 상태도 무해하다 — 그 시점 실코퍼스 Insight 0건이라 색인에 Insight 행이 없다.

**2. ingest.py 검토 라운드(spec 4.8 C5) — 엔진 변경 없음, 운영 게이트로 충족.**
현재 `ingest`는 reviewed→reviewed를 멱등 허용하고(test_ingest.py:219 `test_ingest_reviewed_to_reviewed_ok`), reviewed→candidate 후퇴만 거부한다(ingest.py:31). supersede는 적재자가 "새 객체 candidate + 기존 superseded" 번들을 짜는 **수동 흐름**이지 진입점 자동화가 아니다. spec §5는 "재사용 가능 여부 확인"이라 자체 불확실성을 표시했다. 결론: **ingest.py에 새 강제 로직을 넣지 않는다.** C5(검토 이력 보존)는 id 규약(`insight.<주제-slug>`)과 검수 게이트 5번("기존 reviewed Insight 대조")으로 처리한다(데이터·운영). Task 3이 이 조사를 테스트로 확정한다.

**3. 골든셋(spec §6) — 엔진은 판정 키 + stub 단위 테스트, 실데이터 적재는 실사용.**
advisories 회수 + 객체 레인 불변(C2)은 stub embedder + tmp 색인 단위 테스트로 검증한다(Task 5·6). 실코퍼스 골든셋 시나리오(노출 게이트 Insight 적재 후 advisories 회수, s1·s2 점수 불변)는 실제 Insight 적재가 선행이라 plan 범위 밖이다. 단 Task 7에서 `eval_harness`에 `advisories_top5_any` 판정 키를 미리 넣어 나중에 시나리오만 추가하면 되게 한다.

**4. advisories 게이트·candidate·노출 — critic 검토(2026-06-15) 반영.**
- advisories는 **reviewed Insight만** 곁들인다. 게이트는 `channel="reviewed"` 재사용(reviewed 점수 바닥 + 질의 앵커 적용) — raw가 앵커를 건너뛰는 근거("객체화 안 된 미검수 발췌라 부정확 노출의 해가 낮다")가 검수된 Insight엔 없으므로 발췌보다 엄격해야 맞다(critic 검토 1 통과). **트레이드오프**: 앵커는 질의에 희소 토큰이 있어야 뜨므로, 사용자가 위험을 몰라 막연히 묻는 질의엔 경고가 안 뜬다("막연한 질의에 능동 경고"는 별도 설계가 필요한 미해결 영역). **Task 5 fix(Insight를 anchor df에서 제외)와의 상호작용 — 구현 중 발견·사용자 결정으로 앵커 유지:** Insight만 매칭되는 질의(객체 토큰 없음)는 `anchor_df=None`이라 advisory가 차단된다. 실코퍼스는 객체(매핑·용어)가 풍부해 질의가 객체 토큰을 매칭하면 anchor가 잡혀 무해하나, **Task 6 단위 테스트는 anchor를 제공하는 객체(reviewed 또는 candidate)를 반드시 동반해야 advisory가 뜬다**(Insight-only 코퍼스 가정은 비현실적). "바닥만(앵커 미적용)" 대안은 critic의 앵커 합의를 벗어나고 무관 위험 누적(C4) 여지가 있어 기각.
- **candidate Insight는 1차에서 적재 자체를 거부한다**(validate_object) — 노출 통로가 reviewed(advisories)뿐이라 candidate로 두면 회상의 어느 통로에도 안 떠 "조용히 묻히는" 함정이 된다(critic 검토 2). "미룸"과 "candidate 적재 허용"이 충돌하지 않도록 적재를 막아 함정을 없앤다. 후보 통로(promotable) 노출은 실사용 트리거 때 신설(범위 밖). 후보 통로를 만들 때 이 거부를 푼다.
- Insight 레인은 **scope 필터를 적용하지 않는다**. 1차 근거는 "가로지름"이지만 더 근본적으로 **Insight에 `context_id`가 없어**(BASE/KIND_REQUIRED 둘 다 없음 → 색인 시 None) scope 필터(`context_id == scope`)를 걸면 모든 Insight가 걸러져 advisory가 항상 0이 된다 — 즉 미적용은 강제된 결과다(critic 검토 3). 부수 효과: scope 단일특정 질의에선 벡터 채널이 `context_id`로 Insight를 버려 advisory가 **BM25 단독 회수**가 된다. Insight가 쌓이면 scope 질의에 무관한 위험이 섞일 수 있다(scope 적합성 판정은 미해결 — Insight의 `source_object_ids`가 현재 scope 객체를 하나라도 가리키면 포함하는 식이 후보).
- advisory 노출에 **`source_object_ids`를 포함한다** — Insight의 정체성("2개 이상 객체를 가로지름")이 바로 이 필드인데, 공용 `_build_linked`는 이 필드를 안 따라가므로(추가하면 그래프 재정렬 오염) router advisory dict에 직접 담아 "어느 객체를 가로지르는지"를 보인다(critic 검토 4). `_build_linked`는 건드리지 않는다.

---

## File Structure

모두 엔진 레포 `~/Downloads/codes/project-brain` 안. 데이터 레포는 회귀 확인(Task 8)만 한다.

| 파일 | 책임 | 이 작업의 변경 |
|------|------|--------------|
| `src/project_brain/schema.py` | kind별 필수 필드·enum 검증 | `Insight` 등록, `insight_type` enum, source 개수 검사 |
| `src/project_brain/lint.py` | 전수 무결성(dangling 등) | Insight `source_object_ids`/`code_locator_ids` dangling 블록 |
| `src/project_brain/ingest.py` | 적재 진입점 | **변경 없음** (Task 3 조사 결론) |
| `src/project_brain/surface.py` | kind별 검색 표면 추출 | `_surface_insight` 등록 + `EXTRACTOR_VERSION` bump |
| `src/project_brain/search.py` | RRF 융합·recall·eval_recall | Insight 별도 레인 + advisories 채널 |
| `src/project_brain/router.py` | 의도별 답변 조립 | `answer()` 반환 dict에 `advisories` 키 |
| `src/project_brain/eval_harness.py` | 골든셋 평가 | `advisories_top5_any` 판정 키 |
| `tests/test_*.py` | 단위 테스트 | 각 파일에 Insight 케이스 |

**구현 순서(spec 4.6 의존)**: schema → lint → (ingest 조사) → surface → recall 레인 → eval_recall 채널 → router → eval_harness → 회귀. 검색 분리(레인·채널)가 표면 등록 직후 연속 완성되어, 실데이터 적재 전에 통로가 준비된다.

**테스트 명령(엔진 레포 루트에서):**
```bash
cd ~/Downloads/codes/project-brain
.venv/bin/python -m pytest tests/ -q
```
베이스라인: `378 passed`.

---

## Task 1: schema.py — Insight kind 등록 + insight_type enum + source 개수 검사

**Files:**
- Modify: `src/project_brain/schema.py:35` (KIND_REQUIRED), `:59` (KIND_TRUTH_ROLE), `:104` 근처(새 enum 상수), `:213` 뒤(validate_object 분기)
- Modify: `tests/test_ingest.py` (insight 픽스처 추가)
- Test: `tests/test_schema.py`

- [ ] **Step 1: insight 픽스처를 test_ingest.py에 추가**

`tests/test_ingest.py`의 `candidate_mapping` 정의(line 157) 바로 뒤에 추가:

```python
def insight(iid="insight.x", *, insight_type="cross-cutting-risk",
            source_object_ids=None, body="노출 게이트가 두 팝업에 이중구현돼 어긋난다",
            status="reviewed", scope="스테이지 클리어 토큰 노출", code_locator_ids=None):
    """중립 Insight 한 개(2026-06-15 신설 kind). A형(cross-cutting-risk) 기본 — source≥2."""
    obj = {
        "id": iid,
        "kind": "Insight",
        "status": status,
        "truth_role": "synthesis",
        "title": "인사이트: 노출 게이트 이중구현",
        "body": body,
        "source_object_ids": source_object_ids if source_object_ids is not None
                             else ["m.a", "m.b"],
        "scope": scope,
    }
    if insight_type is not None:
        obj["insight_type"] = insight_type
    if code_locator_ids is not None:
        obj["code_locator_ids"] = code_locator_ids
    return base(obj, tags=["neutral"], created_at=T, updated_at=T)
```

- [ ] **Step 2: 실패 테스트 작성**

`tests/test_schema.py`의 `TestRefTypeEnum` 클래스 뒤(line 95, `if __name__` 앞)에 추가:

```python
class TestInsightKind(unittest.TestCase):
    """Insight kind(2026-06-15 신설) — truth_role=synthesis 재사용, insight_type A/B enum,
    source_object_ids 개수 검사(공통 ≥1, A형 cross-cutting-risk ≥2)."""

    def test_valid_cross_cutting_risk_passes(self):
        from tests.test_ingest import insight
        self.assertEqual(validate_object(insight()), [])

    def test_valid_operational_lesson_passes(self):
        from tests.test_ingest import insight
        obj = insight("insight.b", insight_type="operational-lesson",
                      source_object_ids=["ctx.a"])
        self.assertEqual(validate_object(obj), [])

    def test_truth_role_must_be_synthesis(self):
        from tests.test_ingest import insight
        obj = insight()
        obj["truth_role"] = "domain"
        errors = validate_object(obj)
        self.assertTrue(any("invalid truth_role" in e for e in errors))

    def test_invalid_insight_type_rejected(self):
        from tests.test_ingest import insight
        obj = insight()
        obj["insight_type"] = "risk"
        errors = validate_object(obj)
        self.assertTrue(any("invalid insight_type" in e for e in errors))

    def test_cross_cutting_risk_requires_two_sources(self):
        from tests.test_ingest import insight
        obj = insight(source_object_ids=["m.only"])
        errors = validate_object(obj)
        self.assertTrue(any(">=2 source_object_ids" in e for e in errors))

    def test_no_type_requires_at_least_one_source(self):
        from tests.test_ingest import insight
        obj = insight(insight_type=None, source_object_ids=[])
        errors = validate_object(obj)
        self.assertTrue(any(">=1 source_object_ids" in e for e in errors))

    def test_missing_body_reported(self):
        from tests.test_ingest import insight
        obj = insight()
        del obj["body"]
        errors = validate_object(obj)
        self.assertTrue(any("Insight missing field 'body'" in e for e in errors))

    def test_candidate_insight_rejected(self):
        # 1차 제약(critic 검토 2): candidate Insight는 노출 통로가 없어 적재 거부.
        from tests.test_ingest import insight
        obj = insight(status="candidate")
        errors = validate_object(obj)
        self.assertTrue(any("candidate Insight not supported" in e for e in errors))
```

- [ ] **Step 3: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_schema.py::TestInsightKind -q`
Expected: FAIL — `unknown kind 'Insight'`(KIND_REQUIRED에 없음).

- [ ] **Step 4: schema.py 구현**

4-1. `KIND_REQUIRED`의 `DomainMapping` 항목 뒤, 닫는 `}`(line 35) 앞에 추가:

```python
    "DomainMapping": ("context_id", "mapping_key", "canonical_summary", "meaning",
                      "boundary", "glossary_term_ids", "decision_record_ids"),
    "Insight": ("body", "source_object_ids"),
}
```

4-2. `KIND_TRUTH_ROLE`의 `DomainMapping` 항목 뒤, 닫는 `}`(line 59) 앞에 추가:

```python
    "DomainMapping": "domain",
    "Insight": "synthesis",
}
```

4-3. `REVIEW_STATE_KEYS` 정의(line 101-103) 뒤에 새 enum 상수 추가:

```python
# spec(2026-06-15 Insight kind §4.2): A/B 두 결만 강제, 세부 분류는 연다.
# insight_type은 필수가 아니되 값이 있으면 이 둘 중 하나여야 한다.
INSIGHT_TYPE_VALUES = frozenset({"cross-cutting-risk", "operational-lesson"})
```

4-4. `validate_object`의 `DomainMapping` 분기 끝(line 213, `errors.append(... reviewed DomainMapping ...)` 뒤) — `elif kind == "ReviewRecord":`(line 214) **앞**에 분기 추가:

```python
    elif kind == "Insight":
        # 1차 제약(critic 검토 2, 2026-06-15): candidate Insight는 노출 통로가 없다
        # (advisories는 reviewed만). candidate로 두면 회상 어디에도 안 떠 조용히 묻히므로
        # 적재 자체를 거부한다. 후보 통로(promotable) 신설 시 이 블록을 제거한다.
        if obj.get("status") == "candidate":
            errors.append(
                f"{obj['id']}: candidate Insight not supported (no recall channel — "
                f"only reviewed surfaces via advisories; would be silently buried)")
        # spec(2026-06-15) §4.2·§4.7: insight_type 값 enum + source 개수 검사.
        # KIND_REQUIRED가 source_object_ids "존재"만 보므로(빈 리스트도 통과) 개수는 여기서.
        insight_type = obj.get("insight_type")
        if insight_type is not None and insight_type not in INSIGHT_TYPE_VALUES:
            errors.append(f"{obj['id']}: Insight invalid insight_type {insight_type!r}")
        source_ids = obj.get("source_object_ids")
        if isinstance(source_ids, list):
            min_required = 2 if insight_type == "cross-cutting-risk" else 1
            if len(source_ids) < min_required:
                errors.append(
                    f"{obj['id']}: Insight requires >={min_required} source_object_ids "
                    f"(insight_type={insight_type!r})")
```

- [ ] **Step 5: 통과 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_schema.py tests/test_ingest.py -q`
Expected: PASS (TestInsightKind 7건 + 기존 ingest/schema 전부).

- [ ] **Step 6: 커밋**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/schema.py tests/test_schema.py tests/test_ingest.py
git commit -m "feat(schema): Insight kind 등록 — synthesis 재사용·insight_type A/B enum·source 개수 검사"
```

---

## Task 2: lint.py — Insight source/locator dangling 블록

**Files:**
- Modify: `src/project_brain/lint.py:232` 근처(8e 블록 뒤, `if workspace_root` 앞)
- Test: `tests/test_lint.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_lint.py`의 끝(`if __name__` 앞, 없으면 파일 끝)에 추가:

```python
class TestInsightDangling(unittest.TestCase):
    """Insight dangling 가드(spec 2026-06-15 §4.7) — 가리키는 근거 객체가 supersede/삭제되면
    '가로지른다'는 본질이 조용히 깨지므로 DomainMapping 8a·DecisionRecord 8b와 동형으로 잡는다."""

    def test_dangling_source_object_id_reported(self):
        from tests.test_ingest import insight
        ins = insight(source_object_ids=["m.gone", "m.gone2"])
        problems = lint_store(store_of(ins))
        self.assertTrue(any("dangling source_object_ids m.gone" in p for p in problems))

    def test_dangling_code_locator_id_reported(self):
        from tests.test_ingest import insight
        ins = insight(code_locator_ids=["code.gone"])
        problems = lint_store(store_of(ins))
        self.assertTrue(any("dangling code_locator_ids code.gone" in p for p in problems))

    def test_resolved_sources_no_dangling(self):
        from tests.test_ingest import insight, context, candidate_mapping, candidate_term
        g = candidate_term("g.x")
        ctx = context(glossary_term_ids=["g.x"])
        m1 = candidate_mapping("m.a", glossary_term_ids=["g.x"])
        m2 = candidate_mapping("m.b", glossary_term_ids=["g.x"])
        ins = insight(source_object_ids=["m.a", "m.b"])
        problems = lint_store(store_of(g, ctx, m1, m2, ins))
        self.assertFalse([p for p in problems if "insight.x" in p])
```

- [ ] **Step 2: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_lint.py::TestInsightDangling -q`
Expected: FAIL — dangling 메시지 없음(아직 블록 미구현).

- [ ] **Step 3: lint.py 구현**

`lint_store`의 8e 블록(line 225-231 ReviewRecord target resolution) 뒤, `if workspace_root is not None:`(line 233) **앞**에 추가:

```python
    # 9) Insight dangling source_object_ids / code_locator_ids (spec 2026-06-15 §4.7).
    #    "여러 객체를 가로지른다"가 본질이라 가리키는 근거가 사라지면 조용히 깨진다 —
    #    DomainMapping(8a)·DecisionRecord(8b)와 동형으로 막는다.
    for insight in store.by_kind("Insight"):
        link_fields = (
            ("source_object_ids", insight.get("source_object_ids") or []),
            ("code_locator_ids", insight.get("code_locator_ids") or []),
        )
        for field_name, ids in link_fields:
            for ref_id in ids:
                if ref_id and not store.has(ref_id):
                    problems.append(f"{insight['id']}: dangling {field_name} {ref_id}")
```

- [ ] **Step 4: 통과 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_lint.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/lint.py tests/test_lint.py
git commit -m "feat(lint): Insight source/locator dangling 가드"
```

---

## Task 3: store.py _KIND_DIR 보완 + ingest 멱등 동작 고정

**먼저 store.py 갭 보완(Task 1 누락 — 실행 중 발견):** schema에 kind를 등록(Task 1)하면 store의 `_KIND_DIR`(kind→저장 디렉토리 매핑)에도 항목이 있어야 `save_object`가 동작한다. Task 1이 이를 빠뜨려 Insight 저장이 `KeyError: 'Insight'`를 낸다(store.py:72 `rel = cls._KIND_DIR[obj["kind"]]`). Task 1·2 테스트는 `validate_object`/`BrainStore(dict)`만 써 디스크 저장을 안 타 안 드러났고, 이 Task의 `ingest()`가 처음 `save_object`를 타며 노출했다.

ingest.py는 **변경하지 않는다**(설계 모호성 해소 2). 기존 멱등 가드가 Insight에도 적용됨을 테스트로 고정한다. (candidate Insight 거부는 `validate_object` — Task 1 — 가 처리하므로 여기선 reviewed 멱등만 본다.)

**Files:**
- Modify: `src/project_brain/store.py:44` (`_KIND_DIR`에 `"Insight": "objects/insights"`) — Task 1 누락 보완
- Test: `tests/test_ingest.py` (Insight 케이스 추가)

- [ ] **Step 0: store.py `_KIND_DIR` 보완 (Task 1 누락)**

`src/project_brain/store.py`의 `_KIND_DIR` dict(line 44~)에 한 줄 추가(다른 kind 컨벤션 `objects/<복수형>` 따름 — 예: DomainMapping=`objects/mappings`):

```python
        "Insight": "objects/insights",
```

`load()`는 `set(_KIND_DIR.values())`를 스캔하므로(store.py:20) 새 디렉토리가 자동 포함된다. 별도 커밋:

```bash
git add src/project_brain/store.py
git commit -m "fix(store): Insight _KIND_DIR 매핑 — Task 1 schema 등록 누락 보완"
```

- [ ] **Step 1: 동작 고정 테스트 작성**

`tests/test_ingest.py`의 `TestIngest` 클래스 끝(`test_ingest_merges_existing_store_for_lint` 뒤, line 233)에 추가:

```python
    def _insight_bundle(self):
        # Insight source 객체(m.a·m.b)를 store에 동봉해 dangling을 피한다.
        return [
            context(glossary_term_ids=["g.x"]),
            candidate_term("g.x"),
            candidate_mapping("m.a", glossary_term_ids=["g.x"]),
            candidate_mapping("m.b", glossary_term_ids=["g.x"]),
        ]

    def test_ingest_insight_reviewed_idempotent(self):
        from tests.test_ingest import insight
        ingest(self.root, self._insight_bundle() + [insight()])
        # 같은 reviewed Insight 재적재(멱등) — 기존 ingest 로직 그대로 성공.
        ingest(self.root, [insight()])
        self.assertEqual(BrainStore.load(self.root).get("insight.x")["status"], "reviewed")
```

- [ ] **Step 2: 통과 확인 (코드 변경 없이 기존 로직이 처리)**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_ingest.py -q`
Expected: PASS — ingest.py 무변경으로 통과(멱등·후퇴 가드가 kind 무관 동작).

- [ ] **Step 3: 커밋**

```bash
cd ~/Downloads/codes/project-brain
git add tests/test_ingest.py
git commit -m "test(ingest): Insight 멱등·후퇴 가드 동작 고정 (C5는 운영 게이트로, 엔진 무변경)"
```

---

## Task 4: surface.py — Insight 표면 추출기 등록 + EXTRACTOR_VERSION bump

**Files:**
- Modify: `src/project_brain/surface.py:25` (EXTRACTOR_VERSION), `:145` 근처(추출기 함수), `:157` (_EXTRACTORS dispatch)
- Test: `tests/test_surface.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_surface.py`의 끝(`if __name__` 앞, 없으면 파일 끝)에 추가:

```python
def insight(iid="insight.x", *, body="노출 게이트가 두 팝업에 이중구현돼 어긋난다",
            scope="스테이지 클리어 토큰", status="reviewed"):
    return _b({
        "id": iid, "kind": "Insight", "status": status, "truth_role": "synthesis",
        "title": "인사이트", "body": body, "scope": scope,
        "source_object_ids": ["m.a", "m.b"], "insight_type": "cross-cutting-risk",
    })


class TestInsightSurface(unittest.TestCase):
    """Insight 표면(2026-06-15) — body + scope만. source/code_locator는 그래프 동반(linked)."""

    def test_surface_includes_body_and_scope(self):
        s = extract_surface(insight(), store_of())
        self.assertIn("이중구현", s)
        self.assertIn("스테이지 클리어 토큰", s)

    def test_extractor_version_bumped(self):
        # Insight 추출기 추가 = 추출 로직 변경 → 색인 meta 불일치로 rebuild 트리거(§4).
        self.assertGreaterEqual(EXTRACTOR_VERSION, 2)
```

- [ ] **Step 2: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_surface.py::TestInsightSurface -q`
Expected: FAIL — `extract_surface`가 Insight에 None 반환(미지원 kind) + EXTRACTOR_VERSION=1.

- [ ] **Step 3: surface.py 구현**

3-1. `EXTRACTOR_VERSION = 1`(line 25)을 변경:

```python
# 추출 로직이 바뀌면 올린다(§4 meta의 rebuild 트리거). v2: Insight 추출기 추가(2026-06-15).
EXTRACTOR_VERSION = 2
```

3-2. `_surface_domain_context` 함수(line 137-144) 뒤, `_EXTRACTORS` 정의(line 147) **앞**에 추가:

```python
def _surface_insight(obj, store) -> list[str]:
    # spec(2026-06-15 Insight kind): 자유 텍스트 본문 + 적용 범위가 검색 표면.
    # source_object_ids/code_locator_ids는 linked(그래프 동반)로 따라가므로 표면에 안 넣는다.
    parts: list[str] = []
    for field in ("body", "scope"):
        s = _norm_str(obj.get(field))
        if s is not None:
            parts.append(s)
    return parts
```

3-3. `_EXTRACTORS` dict(line 148-157)의 `"DomainContext": _surface_domain_context,` 뒤에 추가:

```python
    "DomainContext": _surface_domain_context,
    "Insight": _surface_insight,
}
```

- [ ] **Step 4: 통과 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_surface.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/surface.py tests/test_surface.py
git commit -m "feat(surface): Insight 표면 추출기 등록(body+scope) + EXTRACTOR_VERSION v2"
```

---

## Task 5: search.py recall() — Insight 별도 레인 (C2)

객체 레인에서 Insight를 빼고(raw와 동형) 별도 융합해 hits 뒤에 붙인다. 객체 융합·그래프 재정렬은 Insight 개수에 영향받지 않는다.

**리뷰 반영(2026-06-15 quality 검토 — 별도 fix 커밋):** recall() 레인 분리만으로는 C2가 게이트층까지 안 닿는다. `_document_frequency`(anchor_df 계산, search.py)가 RAW만 df에서 제외하고 Insight를 포함해, Insight가 한 앵커 토큰으로 31개 이상 쌓이면 그 토큰 df가 `_ANCHOR_DF_MAX(30)`를 넘겨 객체(reviewed/candidate) 답변 게이트가 닫힌다 — "객체 파이프라인이 Insight 개수에 무관"이라는 C2 정신의 잔여 누수. SQL을 `d.kind NOT IN (RAW_KIND, INSIGHT_KIND)`로 넓혀 닫았고(`test_signals_anchor_df_excludes_insight_rows` — Insight 40개 flood에도 anchor_df=객체 df), append 블록에 scope 필터 미적용 의도를 인라인 주석으로 명시했다.

**Files:**
- Modify: `src/project_brain/search.py:82` 근처(상수), `:384-387`(레인 분리), `:494` 근처(Insight 레인 append)
- Test: `tests/test_search.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_search.py`의 `RawGatePassTest` 클래스(line 1033) **앞**에 추가:

```python
def insight(iid, *, body, scope="범위", status="reviewed",
            source_object_ids=None, code_locator_ids=None,
            insight_type="cross-cutting-risk"):
    obj = {
        "id": iid, "kind": "Insight", "status": status, "truth_role": "synthesis",
        "title": f"인사이트: {iid}", "body": body, "scope": scope,
        "source_object_ids": source_object_ids or ["m.a", "m.b"],
        "insight_type": insight_type, "evidence_refs": [],
    }
    if code_locator_ids is not None:
        obj["code_locator_ids"] = code_locator_ids
    return _b(obj)


class InsightLaneTest(unittest.TestCase):
    """Insight 별도 레인(spec 2026-06-15 §4.6) — raw와 동형으로 객체 융합·그래프
    재정렬을 흔들지 않고, hits 뒤에 별도로 붙는다. surface 승급·linked는 유지(advisory가
    어느 코드와 관련인지 보여줘야 하므로). 전부 stub embedder."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()

    def tearDown(self):
        self._td.cleanup()

    def test_insight_appended_as_separate_lane_after_objects(self):
        build_store_dir(self.brain, [
            glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰"),
            insight("insight.gate", body="클리어 토큰 노출 게이트가 두 팝업에 이중구현"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)
        hits = recall("클리어 토큰 노출 게이트", db_path=self.db, embedder=self.embedder,
                      brain_root=self.brain)
        kinds = [h["kind"] for h in hits]
        self.assertIn("Insight", kinds)
        # Insight는 객체 뒤 별도 레인 — 첫 Insight 이후에 일반 객체가 나오지 않는다.
        first_ins = kinds.index("Insight")
        self.assertTrue(all(k in ("Insight", "raw_chunk") for k in kinds[first_ins:]))
        ins_hit = next(h for h in hits if h["kind"] == "Insight")
        self.assertEqual(ins_hit["status"], "reviewed")
        self.assertIn("이중구현", ins_hit["surface"])  # 표면 승급(body)
        self.assertEqual(ins_hit["graph_support"], 0)  # 재정렬 입력 아님

    def test_insight_flood_does_not_crowd_object_lane(self):
        # Insight 60개가 있어도 객체 적중(그래프 재정렬 입력)은 그대로 살아남는다(레인 분리).
        objs = [glossary_term("g.race", term="레이스", definition="레이스 보상 지급")]
        objs += [insight(f"insight.{i}", body="레이스 보상 지급 위험 서술") for i in range(60)]
        build_store_dir(self.brain, objs)
        rebuild(self.brain, self.db, embedder=self.embedder)
        hits = recall("레이스 보상 지급", db_path=self.db, embedder=self.embedder,
                      brain_root=self.brain)
        object_ids = [h["object_id"] for h in hits
                      if h["kind"] not in ("Insight", "raw_chunk")]
        self.assertIn("g.race", object_ids)

    def test_insight_linked_carries_code_locators(self):
        build_store_dir(self.brain, [
            code_locator("code.enter", path="a/Enter.cpp", symbol="Enter::gate"),
            insight("insight.gate", body="클리어 토큰 노출 게이트 이중구현",
                    code_locator_ids=["code.enter"]),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)
        hits = recall("클리어 토큰 노출 게이트 이중구현", db_path=self.db,
                      embedder=self.embedder, brain_root=self.brain)
        ins_hit = next(h for h in hits if h["kind"] == "Insight")
        locs = {c["object_id"] for c in ins_hit["linked"]["code_locators"]}
        self.assertIn("code.enter", locs)
```

- [ ] **Step 2: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_search.py::InsightLaneTest -q`
Expected: FAIL — Insight가 객체 레인에 섞여 `test_insight_appended_as_separate_lane_after_objects`가 깨지거나(객체가 Insight 뒤에 옴), graph_support가 0이 아님.

- [ ] **Step 3: search.py 구현**

3-1. raw 레인 상수(line 82-84) 뒤에 Insight 레인 상수 추가:

```python
_RAW_LANE_FETCH_FACTOR = 3
# raw 레인 융합 절단 — eval 채널이 top-5만 노출하므로 여유분 포함 10이면 충분.
RAW_FUSED_TOP_N = 10

# ── Insight 별도 레인(spec 2026-06-15 §4.6) ──────────────────────────────────
# Insight는 store 객체(RAW_KIND 아님)라 객체 레인에 남는다 — 자유 텍스트 다토큰이라
# 융합 top-30의 객체 자리를 잠식해 그래프 재정렬을 약화시킨다(raw 청크 회귀와 동형).
# raw처럼 별도 레인으로 빼되, store 객체라 surface 승급·linked는 유지한다. scope
# 필터는 미적용 — "가로지르는" 객체라 단일 context_id가 없다.
INSIGHT_KIND = "Insight"
# 객체 레인에서 제외할 kind(별도 레인으로 빠지는 것들).
_OBJECT_LANE_EXCLUDED = (RAW_KIND, INSIGHT_KIND)
```

3-2. 객체/벡터 레인 필터(line 383-387)를 변경:

```python
    if scope is not None:
        # §3.2 scoped 레인(2026-06-12): scope 단일 특정 시 객체 레인 BM25는 후보
        # 집합 안에서 df·avgdl 재계산. scoped 후보는 context_id=scope·RAW 제외라
        # context_id 없는 Insight도 자연 제외된다.
        bm25 = search_bm25_scoped(db_path, query, scope,
                                  top_n=CHANNEL_TOP_N)["results"]
    else:
        bm25 = [r for r in bm25_all
                if r.get("kind") not in _OBJECT_LANE_EXCLUDED][:CHANNEL_TOP_N]
    vector = [r for r in vector_all
              if r.get("kind") not in _OBJECT_LANE_EXCLUDED][:CHANNEL_TOP_N]
    raw_bm25 = [r for r in bm25_all if r.get("kind") == RAW_KIND][:CHANNEL_TOP_N]
    raw_vector = [r for r in vector_all if r.get("kind") == RAW_KIND][:CHANNEL_TOP_N]
    insight_bm25 = [r for r in bm25_all if r.get("kind") == INSIGHT_KIND][:CHANNEL_TOP_N]
    insight_vector = [r for r in vector_all if r.get("kind") == INSIGHT_KIND][:CHANNEL_TOP_N]
```

3-3. raw 레인 append 블록(line 461-493, `if raw_bm25 or raw_vector:` ... 끝) 뒤, `return hits`(line 494) **앞**에 Insight 레인 append 추가:

```python
    # Insight 별도 레인(§4.6): 객체 적중 뒤에 붙인다. store 객체라 surface 승급·linked는
    # 하되 그래프 재정렬 입력에선 빠진다(graph_support=0). ★linked.code_locators는 담기지만
    # source_object_ids는 공용 _build_linked가 안 따라간다(critic 검토 4) — 가로지름은 router
    # advisory가 source_object_ids로 직접 노출한다. scope 필터 미적용: Insight는 context_id가
    # 없어 필터를 걸면 advisory가 항상 0이 된다(critic 검토 3).
    if insight_bm25 or insight_vector:
        ins_meta: dict[str, dict] = {}
        ins_bm25_ids = []
        for r in insight_bm25:
            ins_bm25_ids.append(r["object_id"])
            ins_meta.setdefault(r["object_id"], r)
        ins_vector_ids = []
        for r in insight_vector:
            ins_vector_ids.append(r["object_id"])
            ins_meta.setdefault(r["object_id"], r)
        ins_fused = rrf_fuse([ins_bm25_ids, ins_vector_ids])
        ins_bm25_set = set(ins_bm25_ids)
        ins_vector_set = set(ins_vector_ids)
        for object_id, score in ins_fused[:RAW_FUSED_TOP_N]:
            in_b, in_v = object_id in ins_bm25_set, object_id in ins_vector_set
            m = ins_meta[object_id]
            surface = ""
            if store.has(object_id):
                surface = extract_surface(store.get(object_id), store) or ""
            hits.append({
                "object_id": object_id,
                "kind": m.get("kind"),
                "status": m.get("status"),
                "context_id": m.get("context_id"),
                "score": score,
                "matched_via": "both" if (in_b and in_v) else ("bm25" if in_b else "vector"),
                "surface": surface,
                "linked": _build_linked(object_id, store),
                "graph_reached": False,
                "graph_hits": 0,
                "graph_support": 0,
            })
    return hits
```

- [ ] **Step 4: 통과 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_search.py -q`
Expected: PASS (InsightLaneTest 3건 + 기존 RawLaneTest·RecallTest 전부 — 객체 레인 불변).

- [ ] **Step 5: 커밋**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/search.py tests/test_search.py
git commit -m "feat(search): Insight 별도 레인 — 객체 융합·그래프 재정렬 불변(raw 동형, C2)"
```

---

## Task 6: search.py eval_recall() — advisories 채널 (C1)

reviewed Insight를 results에서 빼 advisories 채널로 가른다. candidate Insight는 1차 미노출.

**Files:**
- Modify: `src/project_brain/search.py:583-626` (eval_recall)
- Test: `tests/test_search.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_search.py`의 `InsightLaneTest` 클래스 뒤에 추가:

```python
class EvalRecallAdvisoriesTest(unittest.TestCase):
    """eval_recall advisories 채널(spec 2026-06-15 §4.6 C1) — reviewed Insight는
    results에 안 섞이고 advisories로 가른다. candidate Insight는 1차 미노출."""

    def setUp(self):
        self._td = TemporaryDirectory()
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()

    def tearDown(self):
        self._td.cleanup()

    # ★앵커 메커니즘(Task 5 fix 반영): advisories 게이트가 channel="reviewed"(앵커 적용)라,
    # advisory가 뜨려면 질의 토큰을 가진 객체(reviewed/candidate, Insight·raw는 anchor df 제외)가
    # 코퍼스에 있어 anchor_df가 잡혀야 한다. 그래서 각 테스트에 anchor 제공 객체를 동반한다.
    def test_reviewed_insight_goes_to_advisories_not_results(self):
        # g.token(reviewed 객체)이 질의 토큰 "클리어 토큰"을 제공해 anchor가 잡히고,
        # reviewed Insight는 advisories로, results/candidates엔 안 섞인다.
        build_store_dir(self.brain, [
            glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰 노출"),
            insight("insight.gate", body="클리어 토큰 노출 게이트가 두 팝업에 이중구현"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)
        resp = eval_recall("클리어 토큰 노출 게이트 이중구현", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        self.assertIn("advisories", resp)
        self.assertIn("insight.gate", {h["object_id"] for h in resp["advisories"]})
        self.assertFalse([h for h in resp["results"] if h["kind"] == "Insight"])
        self.assertFalse([h for h in resp["candidates"] if h["kind"] == "Insight"])

    def test_candidate_insight_not_exposed_first_cut(self):
        # candidate Insight는 validate가 적재를 막으므로(Task 1) save_object를 우회해
        # 직접 파일로 써 store에 넣고, 검색층이 방어적으로 안 띄움을 확인(이중 안전망).
        # g.token이 anchor를 제공해도 candidate Insight는 어느 채널에도 안 뜬다.
        import json
        build_store_dir(self.brain, [
            glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰 노출"),
        ])
        cand = insight("insight.cand", body="클리어 토큰 노출 위험 후보", status="candidate")
        ins_dir = self.brain / "objects" / "insights"
        ins_dir.mkdir(parents=True, exist_ok=True)
        (ins_dir / "insight.cand.json").write_text(
            json.dumps(cand, ensure_ascii=False), encoding="utf-8")
        rebuild(self.brain, self.db, embedder=self.embedder)
        resp = eval_recall("클리어 토큰 노출 위험", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        self.assertEqual(resp["advisories"], [])
        self.assertFalse([h for h in resp["candidates"] if h["kind"] == "Insight"])

    def test_advisories_capped_at_five(self):
        # g.token이 anchor("클리어 토큰") 제공. reviewed Insight 7개 → advisories top-5.
        objs = [glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰")]
        objs += [insight(f"insight.{i}", body="클리어 토큰 노출 게이트 이중구현 위험")
                 for i in range(7)]
        build_store_dir(self.brain, objs)
        rebuild(self.brain, self.db, embedder=self.embedder)
        resp = eval_recall("클리어 토큰 노출 게이트 이중구현", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        self.assertTrue(resp["advisories"])
        self.assertLessEqual(len(resp["advisories"]), 5)

    def test_advisories_do_not_affect_needs_clarification(self):
        # advisories는 곁들임 — reviewed 객체 답(results)이 0이면 advisory가 있어도
        # needs_clarification=True. candidate term g.cand가 anchor만 제공(results 아님).
        build_store_dir(self.brain, [
            glossary_term("g.cand", term="클리어 토큰", definition="스테이지 클리어 토큰",
                          status="candidate"),
            insight("insight.gate", body="클리어 토큰 노출 게이트 이중구현"),
        ])
        rebuild(self.brain, self.db, embedder=self.embedder)
        resp = eval_recall("클리어 토큰 노출 게이트 이중구현", db_path=self.db,
                           embedder=self.embedder, brain_root=self.brain)
        self.assertTrue(resp["advisories"])
        self.assertEqual(resp["results"], [])
        self.assertTrue(resp["needs_clarification"])
```

- [ ] **Step 2: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_search.py::EvalRecallAdvisoriesTest -q`
Expected: FAIL — `KeyError: 'advisories'`(키 없음) + reviewed Insight가 results로 샘.

- [ ] **Step 3: search.py 구현**

`eval_recall`의 채널 산출부(line 612-626)를 변경:

```python
    results = [h for h in hits
               if h.get("status") == "reviewed"
               and h.get("kind") != INSIGHT_KIND
               and _gate_pass(h["score"], signals, channel="reviewed")][:EVAL_CHANNEL_TOP_K]
    candidates = [h for h in hits
                  if h.get("status") == "candidate"
                  and h.get("kind") != INSIGHT_KIND
                  and _gate_pass(h["score"], signals, channel="candidate")][:EVAL_CHANNEL_TOP_K]
    raw_excerpts = [h for h in hits
                    if h.get("status") == RAW_STATUS
                    and _gate_pass(h["score"], signals, channel="raw")][:EVAL_CHANNEL_TOP_K]
    # advisories(§4.6 C1): reviewed Insight를 별도 통로로. 게이트는 reviewed 재사용
    # (질의 앵커 있어야 곁들임). candidate Insight는 1차 미노출(미룸 §7). 단정 답이
    # 아니라 needs_clarification(results 기반)에는 안 들어간다(raw_excerpts와 동일).
    advisories = [h for h in hits
                  if h.get("kind") == INSIGHT_KIND
                  and h.get("status") == "reviewed"
                  and _gate_pass(h["score"], signals, channel="reviewed")][:EVAL_CHANNEL_TOP_K]
    return {
        "results": results,
        "candidates": candidates,
        "raw_excerpts": raw_excerpts,
        "advisories": advisories,
        "needs_clarification": not results,
    }
```

`eval_recall` docstring 반환 설명(line 590-596)에 advisories 한 줄을 추가(선택):

```python
      raw_excerpts       — raw 청크 적중 top-5 ("원문 발췌(미검수)" — 바닥만, 앵커 미적용)
      advisories         — reviewed Insight 적중 top-5 (가로지르는 위험/교훈 — 곁들임 채널)
```

- [ ] **Step 4: 통과 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_search.py -q`
Expected: PASS (EvalRecallAdvisoriesTest 4건 + 기존 eval_recall 채널 테스트 — raw/results/candidates 불변).

- [ ] **Step 5: 커밋**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/search.py tests/test_search.py
git commit -m "feat(search): eval_recall advisories 채널 — reviewed Insight 분리 노출(C1)"
```

---

## Task 7: router.py — answer() 반환 dict에 advisories 키

라우터 소비자(에이전트)에게 advisories를 가공해 노출한다.

**Files:**
- Modify: `src/project_brain/router.py:404-415` (answer 반환 dict)
- Test: `tests/test_router.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_router.py`의 끝(`if __name__` 앞, 없으면 파일 끝)에 추가. 색인 DB가 필요하므로 tmp 색인 + recall 켠 라우터로 검증한다(test_search 패턴 차용):

```python
class TestRouterAdvisories(unittest.TestCase):
    """answer() 반환에 advisories 키(spec 2026-06-15 §4.6) — recall이 켜지면 reviewed
    Insight를 가공해 노출(id/insight_type/surface/code_locators). 색인 없으면 빈 리스트."""

    def setUp(self):
        from tempfile import TemporaryDirectory
        from project_brain.embedder import StubEmbedder
        from project_brain.search_index import rebuild
        from project_brain.objbase import base
        self._td = TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        from pathlib import Path
        self.brain = Path(self._td.name) / "brain"
        self.db = Path(self._td.name) / "index.db"
        self.embedder = StubEmbedder()
        T = "2026-06-04T00:00:00Z"
        objs = [
            base({"id": "g.token", "kind": "GlossaryTerm", "status": "reviewed",
                  "truth_role": "domain", "title": "Term", "context_id": "context.neutral",
                  "term": "클리어 토큰", "definition": "스테이지 클리어 토큰 노출",
                  "evidence_refs": ["ev.x"]},
                 tags=["n"], created_at=T, updated_at=T),
            base({"id": "code.gate", "kind": "CodeLocator", "status": "reviewed",
                  "truth_role": "reference", "title": "Code", "context_id": "context.neutral",
                  "repo": "bb2_client", "path": "a/Enter.cpp", "symbol": "Enter::gate",
                  "locator_source": "rg", "verified_at": T, "evidence_refs": []},
                 tags=["n"], created_at=T, updated_at=T),
            base({"id": "insight.gate", "kind": "Insight", "status": "reviewed",
                  "truth_role": "synthesis", "title": "인사이트",
                  "body": "클리어 토큰 노출 게이트가 두 팝업에 이중구현",
                  "scope": "클리어 토큰", "insight_type": "cross-cutting-risk",
                  "source_object_ids": ["g.token", "code.gate"],
                  "code_locator_ids": ["code.gate"], "evidence_refs": []},
                 tags=["n"], created_at=T, updated_at=T),
        ]
        for o in objs:
            BrainStore.save_object(self.brain, o)
        rebuild(self.brain, self.db, embedder=self.embedder)
        self.store = BrainStore.load(self.brain)

    def _router(self):
        return QueryRouter(self.store, db_path=self.db, embedder=self.embedder,
                           brain_root=self.brain)

    def test_advisories_key_present_and_populated(self):
        resp = self._router().answer("클리어 토큰 노출 게이트 이중구현")
        self.assertIn("advisories", resp)
        ids = {a["id"] for a in resp["advisories"]}
        self.assertIn("insight.gate", ids)
        adv = next(a for a in resp["advisories"] if a["id"] == "insight.gate")
        self.assertEqual(adv["insight_type"], "cross-cutting-risk")
        self.assertIn("이중구현", adv["surface"])
        self.assertIn("code.gate", {c["object_id"] for c in adv["code_locators"]})
        # 가로지름(critic 검토 4): source_object_ids가 advisory에 직접 담긴다.
        self.assertEqual(set(adv["source_object_ids"]), {"g.token", "code.gate"})

    def test_advisories_empty_without_index(self):
        # 색인 없는 라우터(db_path 미전달)는 recall 비활성 → advisories 빈 리스트.
        resp = QueryRouter(self.store).answer("클리어 토큰 노출 게이트")
        self.assertEqual(resp["advisories"], [])
```

- [ ] **Step 2: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_router.py::TestRouterAdvisories -q`
Expected: FAIL — `KeyError: 'advisories'`(반환 dict에 키 없음).

- [ ] **Step 3: router.py 구현**

`answer()`의 `return {`(line 404) **앞**에 advisories 수집 추가:

```python
        # advisories(spec 2026-06-15 §4.6): reviewed Insight를 별도 통로로 곁들인다.
        # recall이 켜졌을 때만(색인 있음) 채워지고, 없으면 빈 리스트. needs_clarification에는
        # 영향 주지 않는다(곁들임 — eval_recall이 advisories를 needs_clarification 식에서 제외).
        advisories: list[dict] = []
        recalled = self._recall(canonical)
        if recalled is not None:
            for hit in recalled.get("advisories", []):
                oid = hit["object_id"]
                if not self.store.has(oid):
                    continue
                obj = self.store.get(oid)
                advisories.append({
                    "id": oid,
                    "insight_type": obj.get("insight_type"),
                    "surface": hit.get("surface", ""),
                    "code_locators": hit.get("linked", {}).get("code_locators", []),
                    # Insight 정체성("가로지름")은 source_object_ids 자체 — 공용 _build_linked가
                    # 안 따라가는 필드라 여기서 직접 노출한다(critic 검토 4).
                    "source_object_ids": obj.get("source_object_ids", []),
                })

        return {
```

그리고 반환 dict(line 405-415)에 `"advisories": advisories,`를 추가(`"sections"` 뒤):

```python
            "sections": sections,
            "advisories": advisories,
            "warnings": warnings,
            "needs_clarification": (not source_ids) or clarification_needed,
        }
```

- [ ] **Step 4: 통과 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_router.py -q`
Expected: PASS (TestRouterAdvisories 2건 + 기존 router 테스트 전부 — advisories는 추가 키라 기존 계약 불변).

- [ ] **Step 5: 커밋**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/router.py tests/test_router.py
git commit -m "feat(router): answer() 반환에 advisories 키 — reviewed Insight 곁들임 노출"
```

---

## Task 8: eval_harness.py — advisories_top5_any 판정 키

골든셋이 advisories 채널을 판정할 수 있게 키를 추가한다(실코퍼스 시나리오는 실사용으로 나중에).

**Files:**
- Modify: `src/project_brain/eval_harness.py:27-35` (ASSERTION_KEYS), `:61-70` (expected_object_ids), `:166-172` 근처(evaluate)
- Test: `tests/test_eval_harness.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_eval_harness.py`의 끝(`if __name__` 앞, 없으면 파일 끝)에 추가:

```python
class TestAdvisoriesAssertion(unittest.TestCase):
    """advisories_top5_any 판정 키(spec 2026-06-15) — advisories 채널 top-5에 ≥1 적중."""

    def test_advisories_top5_any_passes(self):
        scenarios = [{"id": "adv", "query": "q",
                      "expect": {"advisories_top5_any": ["insight.gate"]}}]
        def fake_recall(q):
            return {"results": [], "candidates": [], "raw_excerpts": [],
                    "advisories": [{"object_id": "insight.gate"}],
                    "needs_clarification": True}
        report = evaluate(fake_recall, scenarios)
        self.assertTrue(report["ok"])

    def test_advisories_top5_any_fails_when_absent(self):
        scenarios = [{"id": "adv", "query": "q",
                      "expect": {"advisories_top5_any": ["insight.gate"]}}]
        def fake_recall(q):
            return {"results": [], "candidates": [], "raw_excerpts": [],
                    "advisories": [], "needs_clarification": True}
        report = evaluate(fake_recall, scenarios)
        self.assertFalse(report["ok"])

    def test_advisories_key_is_known_assertion(self):
        # load_scenarios가 미지 키로 거부하지 않는다(ASSERTION_KEYS 등록 확인).
        self.assertIn("advisories_top5_any", ASSERTION_KEYS)
```

`tests/test_eval_harness.py` 상단 import에 `ASSERTION_KEYS`, `evaluate`가 없으면 추가:

```python
from project_brain.eval_harness import ASSERTION_KEYS, evaluate
```

- [ ] **Step 2: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_eval_harness.py::TestAdvisoriesAssertion -q`
Expected: FAIL — `advisories_top5_any`가 ASSERTION_KEYS에 없고 evaluate가 판정 안 함.

- [ ] **Step 3: eval_harness.py 구현**

3-1. `ASSERTION_KEYS`(line 27-35)에 추가:

```python
    "raw_top5_prefix_any",  # raw_excerpts top-5에 프리픽스 일치 id ≥1 (§2.2 raw 채널 —
                            # 청크 id는 청커 산출이라 정확 id 대신 프리픽스로 판정)
    "advisories_top5_any",  # advisories(reviewed Insight) top-5에 ≥1 적중 (§4.6)
}
```

3-2. `expected_object_ids`(line 61-70)의 루프에 advisories도 포함:

```python
    for sc in scenarios:
        expect = sc["expect"]
        ids.update(expect.get("top5_any") or [])
        ids.update(expect.get("any_channel_top5_any") or [])
        ids.update(expect.get("advisories_top5_any") or [])
        for group in expect.get("linked_any_groups") or []:
            ids.update(group)
    return ids
```

3-3. `evaluate`의 `raw_top5_prefix_any` 판정 블록(line 166-172) 뒤, `if expect.get("no_answer"):`(line 174) **앞**에 추가:

```python
        if "advisories_top5_any" in expect:
            adv_top5 = _hit_ids(response.get("advisories") or [], 5)
            matched = [oid for oid in expect["advisories_top5_any"] if oid in adv_top5]
            checks["advisories_top5_any"] = {
                "passed": bool(matched), "matched": matched, "top5_advisories": adv_top5,
            }
```

- [ ] **Step 4: 통과 확인**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_eval_harness.py -q`
Expected: PASS.

- [ ] **Step 5: 커밋**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/eval_harness.py tests/test_eval_harness.py
git commit -m "feat(eval): advisories_top5_any 판정 키 — Insight 채널 골든셋 대비"
```

---

## Task 9: 회귀 검증 — 엔진 전체 + 골든셋 불변

엔진 변경이 기존 동작을 깨지 않는지, Insight 미적재 상태에서 골든셋 8개가 그대로인지 확인한다.

**Files:** 없음(검증만).

- [ ] **Step 1: 엔진 전체 테스트**

Run:
```bash
cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/ -q
```
Expected: `PASS` — 베이스라인 378 + 신규(TestInsightKind 8 / TestInsightDangling 3 / ingest Insight 1 / TestInsightSurface 2 / InsightLaneTest 3 / EvalRecallAdvisoriesTest 4 / TestRouterAdvisories 2 / TestAdvisoriesAssertion 3 = 약 26건 증가). 실패 0.

- [ ] **Step 2: 데이터 레포 색인 재생성 (EXTRACTOR_VERSION bump 반영)**

EXTRACTOR_VERSION이 1→2로 올라 기존 색인이 stale다. 데이터 레포 루트에서 rebuild:
```bash
cd ~/Desktop/bb2_client && project-brain index rebuild
```
Expected: rebuild 완료(객체 수·raw_chunks 수 출력). 실코퍼스에 Insight 0건이라 색인 내용은 표면 추출 로직 외 동일.

- [ ] **Step 3: 골든셋 회귀 (Insight 미적재 → 기존 8개 불변)**

Run:
```bash
cd ~/Desktop/bb2_client && project-brain eval
```
Expected: `"ok": true`, 8/8 통과(s1~s7, s9). Insight 0건이라 advisories는 빈 채널이고 기존 시나리오 점수는 불변(C2 — 객체 레인 미변경).

- [ ] **Step 4: 데이터 레포 실측 가드**

Run:
```bash
cd ~/Desktop/bb2_client && pytest brain/checks/ -q
```
Expected: PASS — CLI 호출 가드(advisories는 추가 키라 기존 계약 불변).

- [ ] **Step 5: 결과 보고 (커밋 없음)**

엔진 테스트 수·골든셋 8/8을 사용자에게 보고한다. 데이터 레포(`~/Desktop/bb2_client`)의 색인 재생성은 부산물이라 커밋하지 않는다(실코퍼스 Insight 적재는 별도 실사용 단계).

---

## 범위 밖 (실사용 — 이 plan 이후)

- **실코퍼스 노출 게이트 Insight 적재**: 입장 팝업·이어하기 팝업 클리어 토큰 노출 게이트 이중 구현(LGBBTWO-4695 구조적 원인)을 A형 Insight로 적재(`bb2-brain-ingest` 스킬). source_object_ids에 두 구현 매핑/locator, code_locator_ids에 게이트 코드.
- **advisories 골든셋 시나리오(s10) 추가**: 적재 후 "스테이지 클리어 토큰 수정" 질의 → `advisories_top5_any` + s1·s2 점수 불변 실측. 데이터 레포 `brain/eval_scenarios.json`.
- **B형 Insight 적재**: 개발 흐름(알파→베타→리얼→릴리즈) 교훈을 operational-lesson으로(개발 흐름 정의 자체는 DomainContext).
- **미룸(spec §7)**: insight_type 세부 값 체계, candidate Insight 노출 채널, A형 stale-check 연동(code_locator_ids 필드는 이미 둠), A/B 별도 kind 분리.
