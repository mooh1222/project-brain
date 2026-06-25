# CodeLocator evref locator 객체화 + 줄 번호 입력 선택값화 Implementation Plan

> ⚠️ **SUPERSEDED (2026-06-24)** — 이 계획은 `2026-06-24-brain-code-evidence-cleanup.md`로 대체됨.
> 검토 끝에 방향이 바뀜: locator를 `{path,symbol,line,line}` 객체가 아니라 `{code_locator_id}` 번호표(참조)로,
> 줄번호는 선택값이 아니라 제거. 아래 내용(이미 커밋된 2개 작업)은 그 새 계획의 "배경/현재 상태"로만 참고.
> **아래 'For agentic workers' 실행 지시와 본문 `- [ ]` 체크박스는 대체 전 원본의 잔재다 — 실행하지 말 것.** 실제 실행 대상은 `2026-06-24-brain-code-evidence-cleanup.md`(이미 완료).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `build_code_evidence`가 (1) code_locator EvidenceRef의 `locator`를 설계 정본대로 **객체**로 만들게 하고, (2) code_anchor의 `line_start`/`line_end` 입력을 **선택값**으로 바꾼다.

**Architecture:** 두 변경 모두 `assembly.py`의 같은 함수 `build_code_evidence`(+ 인접 `validate_notes`의 `_ITEM_REQUIRED`)만 건드린다. 순서가 중요하다 — 먼저 locator를 객체로 바꾸고(Task 1), 그 위에서 줄 번호를 선택값으로 만든다(Task 2). 반대로 하면 문자열 `path:line`에 None이 끼어 throwaway 분기 코드가 생긴다.

**Tech Stack:** Python, unittest. 개발 venv: `.venv/bin/python`.

## Global Constraints

- 결정론 유지 — 테스트에서 실모델 금지. 이 작업은 순수 dict 변환이라 임베더·모델과 무관하다.
- 합성 테스트로 끝낸다. **실코퍼스 회귀 불필요** — 근거: 엔진이 locator 내용과 줄 번호를 검색·회상·답변 어디서도 안 읽고(`.locator` 파서 0건, surface는 path/symbol만 추출), 데이터 레포 골든셋·실측 가드의 줄 번호 의존 0건, 기존 데이터는 안 건드린다(앞으로 적재 입력만 변경).
- `build_code_evidence`를 호출하는 테스트는 `tests/test_assembly.py` **하나뿐**이다(`grep -rln build_code_evidence`로 확인). 다른 테스트(`test_universal_ingest_e2e.py`, `test_stale_check.py`)는 evref locator를 직접 객체로 만들어 픽스처로 쓰므로 이 변경의 영향을 안 받는다.
- 정본 근거: `docs/specs/2026-05-27-bb2-brain-object-model-design.md:167` (§6.2) — `EvidenceRef.locator`는 `{ path?, line_start?, line_end?, code_locator_id?, ... }` **객체**.

### 설계 결정 — locator 객체에 넣을 칸

`build`가 만들 locator 객체는 **`{path, symbol}` + (있으면) `line_start`/`line_end`**로 한다.

- 근거: 실데이터의 code_locator evref가 `{path, symbol, line_start, line_end}` 형태다(턴9 실데이터 확인). 이 형식에 맞추는 게 "엔진 출력과 데이터를 맞춘다"는 목표 그대로다.
- `symbol`은 정본 spec의 locator 타입 목록엔 없지만 실데이터엔 있다. 스키마 검증이 locator 내부를 타입 검사하지 않으므로(아래 확인) 무해하고, 코드를 찾는 데 유용해 포함한다. (spec과 data의 이 불일치는 우리 버그와 별개의 기존 사안이다.)
- `code_locator_id`는 **넣지 않는다**(YAGNI). 실데이터 예시에 없고, 읽는 코드도 없다. 필요하면 별도 작업.
- 스키마가 막지 않는 근거: `schema.py:13`의 `EvidenceRef` 필수는 필드 **이름만**(`locator` 존재 여부)이고, `schema.py:145-147`은 `ref_type` enum만 검사한다. locator가 문자열이든 객체든 검증을 통과한다.

---

### Task 1: code_locator EvidenceRef의 locator를 객체로 생성

**Files:**
- Modify: `src/project_brain/assembly.py:60-73` (`build_code_evidence` 안 `ev`의 locator 생성)
- Test: `tests/test_assembly.py:44` (`BuildCodeEvidenceTest.test_anchor_expands_to_locator_and_evref`의 locator 단언)

**Interfaces:**
- Consumes: 없음 (기존 코드 수정)
- Produces: `build_code_evidence(notes, now)`가 만드는 EvidenceRef의 `ev["locator"]`가 `dict` — `{"path": str, "symbol": str, "line_start": int, "line_end": int}`. (Task 2가 이 객체의 line 칸을 선택값으로 만든다.)

- [ ] **Step 1: 기존 테스트의 locator 단언을 객체로 바꿔 red 만들기**

`tests/test_assembly.py:44`의 한 줄을 교체한다.

바꾸기 전:
```python
        self.assertEqual(ev["locator"], "TrapObject.h:206")
```

바꾼 후:
```python
        self.assertEqual(ev["locator"], {"path": "TrapObject.h",
                                         "symbol": "TrapObject::_doTrapOnPop",
                                         "line_start": 206, "line_end": 206})
```

- [ ] **Step 2: 테스트가 실패하는지 확인 (red)**

Run: `.venv/bin/python -m pytest tests/test_assembly.py::BuildCodeEvidenceTest::test_anchor_expands_to_locator_and_evref -q`
Expected: FAIL — `assert 'TrapObject.h:206' == {...}` (현재 build가 문자열을 만들기 때문)

- [ ] **Step 3: build_code_evidence가 객체 locator를 만들게 수정**

`src/project_brain/assembly.py`의 `ev` 딕셔너리 바로 위에 `locator` 변수를 만들고, `ev`의 locator를 그 변수로 바꾼다.

바꾸기 전 (`assembly.py:68-73`):
```python
        ev = {
            "id": derive_id("EvidenceRef", ctx, key),
            "kind": "EvidenceRef", "status": "reviewed", "truth_role": "reference",
            "title": quote[:120], "evidence_manifest_id": a["manifest"],
            "ref_type": "code_locator", "locator": f"{a['path']}:{a['line_start']}",
            "summary": quote[:500],
        }
```

바꾼 후:
```python
        locator = {
            "path": a["path"], "symbol": a["symbol"],
            "line_start": a["line_start"], "line_end": a["line_end"],
        }
        ev = {
            "id": derive_id("EvidenceRef", ctx, key),
            "kind": "EvidenceRef", "status": "reviewed", "truth_role": "reference",
            "title": quote[:120], "evidence_manifest_id": a["manifest"],
            "ref_type": "code_locator", "locator": locator,
            "summary": quote[:500],
        }
```

- [ ] **Step 4: 테스트가 통과하는지 확인 (green)**

Run: `.venv/bin/python -m pytest tests/test_assembly.py::BuildCodeEvidenceTest::test_anchor_expands_to_locator_and_evref -q`
Expected: PASS

- [ ] **Step 5: 전체 테스트로 회귀 없는지 확인**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 전부 PASS (다른 테스트는 build_code_evidence를 안 거치므로 영향 없음)

- [ ] **Step 6: Commit**

```bash
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "fix(assembly): code_locator evref locator를 정본대로 객체로 생성

spec §6.2(object-model-design.md:167)은 EvidenceRef.locator를 객체로 규정하나
build는 path:line 문자열을 만들어 정본·실데이터와 어긋났다. 회상엔 무해하나
형식 일탈이라 객체({path,symbol,line_start,line_end})로 정정.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: code_anchor의 line_start/line_end 입력을 선택값으로 (B안)

**Files:**
- Modify: `src/project_brain/assembly.py:254` (`_ITEM_REQUIRED["code_anchors"]`에서 line 제거)
- Modify: `src/project_brain/assembly.py:63` (CodeLocator의 line을 `a.get`으로)
- Modify: `src/project_brain/assembly.py` (Task 1에서 만든 `locator` 변수를 조건부 포함으로)
- Test: `tests/test_assembly.py` (`ValidateNotesTest`에 1개, `BuildCodeEvidenceTest`에 1개 추가)

**Interfaces:**
- Consumes: Task 1이 만든 `locator` 변수 구조.
- Produces: 줄 번호 없는 code_anchor도 `validate_notes`를 통과하고, `build_code_evidence`가 `loc["line_start"] is None`인 CodeLocator와 `{"path","symbol"}`만 든 locator 객체를 만든다.

- [ ] **Step 1: validate_notes가 줄 번호 없는 anchor를 받아들이는 red 테스트 추가**

`tests/test_assembly.py`의 `ValidateNotesTest` 클래스(line 243~) 끝에 메서드를 추가한다.

```python
    def test_code_anchor_without_line_numbers_accepted(self):
        # B안: code_anchor의 line_start/line_end는 선택값 — 없어도 1층 검증 통과
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "code_anchors": [{"key": "k", "path": "Foo.cpp",
                                                   "symbol": "Foo::bar",
                                                   "manifest": "manifest.c.code"}]})
        self.assertEqual(errors, [])
```

- [ ] **Step 2: build가 줄 번호 없는 anchor를 처리하는 red 테스트 추가**

`tests/test_assembly.py`의 `BuildCodeEvidenceTest` 클래스(line 24~)에 메서드를 추가한다.

```python
    def test_anchor_without_line_numbers(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc123", "now": NOW, "repo": "demoapp"},
            "code_anchors": [{"key": "no-line", "path": "Foo.cpp", "symbol": "Foo::bar",
                              "quote": "void bar();", "manifest": "manifest.ctx.code-v2"}],
        }
        objs = build_code_evidence(notes, NOW)
        kinds = {o["kind"]: o for o in objs}
        loc, ev = kinds["CodeLocator"], kinds["EvidenceRef"]
        self.assertIsNone(loc["line_start"])
        self.assertIsNone(loc["line_end"])
        self.assertEqual(ev["locator"], {"path": "Foo.cpp", "symbol": "Foo::bar"})
```

- [ ] **Step 3: 두 테스트가 실패하는지 확인 (red)**

Run: `.venv/bin/python -m pytest "tests/test_assembly.py::ValidateNotesTest::test_code_anchor_without_line_numbers_accepted" "tests/test_assembly.py::BuildCodeEvidenceTest::test_anchor_without_line_numbers" -q`
Expected: 둘 다 FAIL — validate 쪽은 `line_start`/`line_end` 누락 에러가 남아 `errors == []` 실패, build 쪽은 `a["line_start"]`에서 `KeyError`

- [ ] **Step 4: _ITEM_REQUIRED에서 line 제거**

`src/project_brain/assembly.py:254` 한 줄 교체.

바꾸기 전:
```python
    "code_anchors": ("key", "path", "symbol", "line_start", "line_end", "manifest"),
```

바꾼 후:
```python
    "code_anchors": ("key", "path", "symbol", "manifest"),
```

- [ ] **Step 5: CodeLocator와 locator 객체의 line을 선택값으로**

`src/project_brain/assembly.py`에서 두 곳을 바꾼다.

`loc`의 line 줄(`assembly.py:63`) 바꾸기 전:
```python
            "line_start": a["line_start"], "line_end": a["line_end"],
```
바꾼 후:
```python
            "line_start": a.get("line_start"), "line_end": a.get("line_end"),
```

Task 1에서 만든 `locator` 변수 바꾸기 전:
```python
        locator = {
            "path": a["path"], "symbol": a["symbol"],
            "line_start": a["line_start"], "line_end": a["line_end"],
        }
```
바꾼 후:
```python
        locator = {"path": a["path"], "symbol": a["symbol"]}
        if a.get("line_start") is not None:
            locator["line_start"] = a["line_start"]
        if a.get("line_end") is not None:
            locator["line_end"] = a["line_end"]
```

- [ ] **Step 6: 추가한 두 테스트가 통과하는지 확인 (green)**

Run: `.venv/bin/python -m pytest "tests/test_assembly.py::ValidateNotesTest::test_code_anchor_without_line_numbers_accepted" "tests/test_assembly.py::BuildCodeEvidenceTest::test_anchor_without_line_numbers" -q`
Expected: 둘 다 PASS

- [ ] **Step 7: 전체 테스트로 회귀 없는지 확인 (Task 1의 줄 번호 있는 테스트도 여전히 통과)**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 전부 PASS. 특히 `test_anchor_expands_to_locator_and_evref`(줄 번호 있는 경로)가 그대로 통과해야 한다 — 줄 번호를 주면 locator에 line이 그대로 들어가기 때문.

- [ ] **Step 8: Commit**

```bash
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "feat(assembly): code_anchor line_start/line_end 입력을 선택값으로 (B안)

스키마는 줄 번호를 선택값으로 두나 적재 1층(_ITEM_REQUIRED)과 build가
강제했다. 엔진은 줄 번호를 검색·회상·답변 어디서도 안 읽으므로 입력 강제만
해제. 기존 데이터·동작 불변(줄 번호를 주면 그대로 저장), 마이그레이션 불필요.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- "locator 형식 버그 정정(문자열→객체)" → Task 1. ✅
- "줄 번호 입력 선택값화(B안)" → Task 2. ✅
- 두 사안이 독립이라 했지만 같은 함수의 같은 줄을 건드려 한 계획에 순서로 묶음 — Task 1(객체) 먼저, Task 2(선택값)가 그 위에 얹힘. ✅

**2. Placeholder scan:** TODO/TBD/"적절히 처리" 없음. 모든 코드 단계에 실제 before/after 코드 블록 포함. ✅

**3. Type consistency:**
- `build_code_evidence` 함수명 일관(test import와 일치, `build_code_anchors` 아님). ✅
- Task 1이 만든 `locator` 변수를 Task 2가 그대로 받아 조건부로 변경 — 이름·구조 일치. ✅
- locator 객체 칸(`path`, `symbol`, `line_start?`, `line_end?`)이 Task 1·2·설계결정 노트에서 동일. ✅
- `assertIsNone(loc["line_start"])` — Task 2 Step 5에서 `a.get("line_start")`가 None을 넣으므로 키는 존재하고 값이 None. `loc["line_start"]` 접근이 KeyError 안 남. ✅

## References

- `src/project_brain/assembly.py:51` — `build_code_evidence` 정의
- `src/project_brain/assembly.py:60-73` — CodeLocator + EvidenceRef 생성(수정 대상)
- `src/project_brain/assembly.py:254` — `_ITEM_REQUIRED["code_anchors"]`
- `src/project_brain/assembly.py:260` — `validate_notes` (에러 형식: `"노트: {section}[{i}] 필수 필드 {field!r} 누락"`)
- `src/project_brain/schema.py:13,145-147` — locator 타입 미검사(문자열/객체 둘 다 통과)
- `docs/specs/2026-05-27-bb2-brain-object-model-design.md:167` — 정본 locator 객체 정의
- `tests/test_assembly.py:24` `BuildCodeEvidenceTest`, `:243` `ValidateNotesTest`
