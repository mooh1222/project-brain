# 대량 적재 엔진·스킬 개선 Implementation Plan

> **완료 기록 — 2026-07-23:** Task 1~12 구현과 명세·품질 검토를 완료했다. 아래 체크박스,
> RED/GREEN 명령, 당시 절대경로는 실행 전 계획을 보존하는 역사 기록이며 현재 작업 지시로
> 다시 실행하지 않는다.
>
> 실제 엔진 작업은
> `/Users/al03040455/Downloads/codes/project-brain/.worktrees/bulk-ingest-hardening`
> (`feat/bulk-ingest-hardening`)에서 수행해 `182e650`까지 만들고
> `/Users/al03040455/Downloads/codes/project-brain`의 `main`에 fast-forward merge했다.
> merge 후 Python 3.9/3.14의 빈 unittest discovery 차이를 없앤 테스트 fixture 수정
> `f3a7053`도 반영했다. BB2는 계획의 Orca worktree 대신 사용자가 승인한
> `/Users/al03040455/Desktop/bb2_client`의 `docs/bb2-brain-object-model`에서 작업했고,
> `1d1faa77`, `e3e4cd30`, `6022287c` 세 커밋으로 설치본·raw guard·최종 runtime sync를
> 완료했다.
>
> 최종 검증은 엔진 pytest 611 + subtests 26, 템플릿 unittest 59, BB2 lint 0,
> eval 15/15, corpus guard 5/5, 문서 7,092·raw chunk 1,577·vector rowid 7,092다.
> installer 퇴역 파일 정리·rollback과 batch report 입력 충돌 차단은 계획 작성 뒤 승인된
> 추가 범위로 같은 작업에서 완료했다. 전체 결과는
> [완료 보고서](../reports/2026-07-23-bulk-ingest-hardening-completion.md)를 본다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대량 Brain 적재에서 발생한 이중 접두 key, raw 색인 메모리 폭증, 부분 완료 오인, 반복 색인,
코드 흐름 검증 누락을 막고 `bb2-brain-ingest` 본문을 130~170줄 실행 라우터로 줄인다.

**Architecture:** `project-brain` 엔진이 형식·자원 안전을 강제하고,
`src/project_brain/templates/ingest/`가 적재 절차와 의미 판단 계약의 단일 원본이 된다. 테스트가 통과한
템플릿만 installer로 BB2 설치본에 전파한다. 범용 템플릿은 프로젝트별 코드 검증 계약을 조건부로 읽고,
BB2의 정확한 검색 스킬·도구 규칙은 installer가 관리하지 않는 `project-code-verification.md` 덧붙임
파일(overlay)이 맡는다.

**Tech Stack:** Python 3.11, stdlib `unittest`, pytest, Bash, project-brain CLI,
Project Brain installer, agents-doctor

---

## 실행 전 조건

- 설계: `docs/specs/2026-07-21-bulk-ingest-hardening-design.md`
- 엔진 원본: `/Users/al03040455/Downloads/codes/project-brain`
- BB2 설치 대상: `/Users/al03040455/Desktop/bb2_client`
- 구현은 `superpowers:using-git-worktrees`로 만든 깨끗한 작업공간에서 시작한다.
- 엔진 작업공간은 `/Users/al03040455/Downloads/codes/project-brain-bulk-ingest-hardening`을 쓴다.
- BB2 작업공간은 Orca의 worktree base 아래
  `/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening`을 쓴다.
- BB2 현재 기본 작업공간에는 사용자 변경이 있으므로 그 작업공간에서 installer를 실행하지 않는다.
- 기존 스킬 수정 승인은 2026-07-21 사용자 요청으로 확보됐다.
- 테스트는 프로젝트 전용 `/Users/al03040455/Downloads/codes/project-brain/.venv/bin/python`을 쓴다.

## 파일 책임 지도

### project-brain 엔진

- `src/project_brain/assembly.py`: 논리 key 형식 검증
- `src/project_brain/raw_chunks.py`: 보수적 토큰 근사와 과대 유닛 분할
- `src/project_brain/embedder.py`: 기존 2,048 시퀀스 상한 유지
- `tests/test_assembly.py`: key 계약 회귀
- `tests/test_raw_chunks.py`: 한글·기호·과대 단일 유닛 회귀
- `tests/test_embedder.py`: 실모델 lazy load 시 상한 설정 회귀

### 단일 원본 적재 스킬

- `src/project_brain/templates/ingest/SKILL.md`: 130~170줄 실행 라우터
- `src/project_brain/templates/ingest/references/scope.md`: 적용 범위와 세 상태축
- `src/project_brain/templates/ingest/references/object-model.md`: 객체·연결·key·동의어 계약
- `src/project_brain/templates/ingest/references/judgment.md`: 변경 이력 판정
- `src/project_brain/templates/ingest/references/ingest-tools.md`: CLI·raw·단건/대량 실행
- `src/project_brain/templates/ingest/references/system-domain-playbook.md`: workflow·프로젝트 검증 계약 전달·재개 게이트
- `src/project_brain/templates/ingest/references/completeness-checklist.md`: 완료 조건
- `src/project_brain/templates/ingest/references/worked-example.md`: 작은 전체 예시
- `src/project_brain/templates/ingest/references/ingest-case-log.md`: 실제 변칙 기록
- `src/project_brain/templates/ingest/scripts/run_ingest.sh`: 한 항목 실행
- `src/project_brain/templates/ingest/scripts/finalize_ingest.sh`: 묶음 마무리
- `src/project_brain/templates/ingest/scripts/run_ingest_batch.py`: batch 실행·resume·report
- `src/project_brain/templates/ingest/scripts/validate_workflow_result.py`: workflow 완료 판정
- `src/project_brain/templates/ingest/scripts/test_assemble_notes.py`: 기존 조립 회귀
- `src/project_brain/templates/ingest/scripts/test_batch_tools.py`: batch·workflow validator 회귀
- `tests/test_installer.py`: 새 실행 파일 전파, `test_*.py` 제외, 프로젝트 overlay 보존 계약
- `tests/test_ingest_skill_contract.py`: 본문 크기·reference routing·중복 정본·범용 템플릿 독립 계약
- `src/project_brain/templates/CHANGELOG.md`: 변경 이유와 전파 기록

### BB2 설치본

- `/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-brain-ingest/**`:
  installer가 생성하는 결과
- `/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-brain-ingest/references/project-code-verification.md`:
  BB2의 정확한 `bb2-code-search-routing`·clangd·rg 규칙을 연결하는 installer 관리 밖 프로젝트 파일
- `/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.project-brain-manifest.json`:
  installer 파일 소유권 기록. `project-code-verification.md`는 포함하지 않음
- `/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.claude/skills/bb2-brain-ingest`:
  `.agents` 원본을 가리키는 심링크

## Task 1: 현재 실패를 RED 테스트로 고정

**Files:**
- Modify: `tests/test_assembly.py`
- Modify: `tests/test_raw_chunks.py`
- Modify: `tests/test_embedder.py`

- [ ] **Step 1: 전체 ID를 논리 key로 받는 실패 테스트를 작성한다**

`tests/test_assembly.py`에 다음 케이스를 추가한다.

```python
def test_validate_notes_rejects_full_object_id_as_mapping_key(self):
    notes = {
        "context": {"key": "disturb-bubble-system", "commit": "abc"},
        "mappings": [{
            "key": "mapping.disturb-bubble-system.bubble-attribution",
            "canonical_summary": "요약",
            "meaning": "의미",
            "boundary": "경계",
        }],
    }
    errors = validate_notes(notes)
    self.assertTrue(any("mappings[0].key" in e and "논리 key" in e for e in errors))
```

같은 테스트 클래스에 `context.key`, `glossary[].key`, `decisions[].key`, `code_anchors[].key`,
`glossary_keys[]`, `code_evref_keys[]`, `decision_keys[]`, `decisions[].affects[]` 케이스를 표 기반
`subTest`로 추가한다. `code_anchors[].key="core-behavior--0"`은 허용 케이스로 넣는다.

- [ ] **Step 2: key 테스트가 현재 기대대로 실패하는지 확인한다**

Run in `/Users/al03040455/Downloads/codes/project-brain-bulk-ingest-hardening`:

```bash
.venv/bin/python -m pytest tests/test_assembly.py -k "logical_key or full_object_id" -v
```

Expected: 새 테스트가 FAIL하고, 현재 `validate_notes()`가 전체 ID를 거부하지 않음을 보여준다.

- [ ] **Step 3: 한글·기호 과소계산 테스트를 작성한다**

`tests/test_raw_chunks.py`에 다음을 추가한다.

```python
def test_hangul_is_counted_conservatively(self):
    self.assertEqual(approx_tokens("가나다라"), 4)

def test_markdown_symbols_are_not_free(self):
    self.assertGreaterEqual(approx_tokens("|---|---|---|"), 4)

def test_single_oversized_table_line_is_split(self):
    text = "# 표\n" + ("| 값 |" * 2000)
    chunks = split_markdown(text, target_tokens=100)
    self.assertGreater(len(chunks), 1)
    self.assertTrue(all(approx_tokens(c) <= 150 for c in chunks))
```

- [ ] **Step 4: raw chunk 테스트가 현재 기대대로 실패하는지 확인한다**

Run in `/Users/al03040455/Downloads/codes/project-brain-bulk-ingest-hardening`:

```bash
.venv/bin/python -m pytest tests/test_raw_chunks.py -k "conservatively or symbols or oversized_table" -v
```

Expected: 세 테스트가 FAIL한다.

- [ ] **Step 5: 실모델 상한 회귀 테스트를 작성한다**

`tests/test_embedder.py`에서 가짜 `sentence_transformers` 모듈을 `patch.dict(sys.modules, ...)`로 주입한다.

```python
def test_lazy_load_sets_max_sequence_length(self):
    class FakeModel:
        def __init__(self, name):
            self.name = name
            self.max_seq_length = None

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeModel)
    with patch.dict(sys.modules, {"sentence_transformers": fake_module}):
        e = RealEmbedder()
        e._load()
    self.assertEqual(e._model.max_seq_length, 2048)
```

- [ ] **Step 6: 기존 구현에서 상한 테스트가 통과하는지 확인한다**

Run in `/Users/al03040455/Downloads/codes/project-brain-bulk-ingest-hardening`:

```bash
.venv/bin/python -m pytest tests/test_embedder.py::RealEmbedderLazyTest::test_lazy_load_sets_max_sequence_length -v
```

Expected: PASS. 이 테스트는 이미 반영된 `4b3d02f` 수정의 회귀 방지다.

- [ ] **Step 7: RED 테스트만 커밋한다**

```bash
git add tests/test_assembly.py tests/test_raw_chunks.py tests/test_embedder.py
git commit -m "test(ingest): reproduce bulk ingest key and raw chunk failures"
```

## Task 2: 엔진 논리 key 검증 구현

**Files:**
- Modify: `src/project_brain/assembly.py`
- Test: `tests/test_assembly.py`

- [ ] **Step 1: key 정규식을 추가한다**

```python
_LOGICAL_KEY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ANCHOR_KEY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:--[0-9]+)?$")
```

`import re`를 함께 추가한다.

- [ ] **Step 2: 위치를 포함해 오류를 쌓는 helper를 추가한다**

```python
def _validate_logical_key(errors, location, value, *, anchor=False):
    pattern = _ANCHOR_KEY_RE if anchor else _LOGICAL_KEY_RE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        errors.append(
            f"노트: {location}={value!r}는 논리 key여야 함 "
            "(소문자 영숫자와 단일 하이픈, 전체 객체 id 금지)"
        )
```

- [ ] **Step 3: 모든 논리 key 입력 지점에 helper를 적용한다**

`validate_notes()`에서 다음 위치를 검사한다.

- `context.key`
- `glossary[].key`
- `mappings[].key`
- `decisions[].key`
- `code_anchors[].key` (`anchor=True`)
- `mappings[].glossary_keys[]`
- `mappings[].code_evref_keys[]` (`anchor=True`)
- `mappings[].decision_keys[]`
- `decisions[].affects[]`

- [ ] **Step 4: key 회귀 테스트를 실행한다**

```bash
.venv/bin/python -m pytest tests/test_assembly.py -v
```

Expected: PASS.

- [ ] **Step 5: 전체 엔진 조립 테스트를 실행한다**

```bash
.venv/bin/python -m pytest tests/test_assembly.py tests/test_universal_ingest_e2e.py -q
```

Expected: PASS.

- [ ] **Step 6: 엔진 key 가드를 커밋한다**

```bash
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "fix(assembly): reject full object ids in logical key fields"
```

## Task 3: raw 청크 과소계산의 근본 원인 완화

**Files:**
- Modify: `src/project_brain/raw_chunks.py`
- Test: `tests/test_raw_chunks.py`

- [ ] **Step 1: 보수적 근사로 교체한다**

ASCII word와 한글을 먼저 제외하고 남은 비공백 기호 수를 센다.

```python
_OTHER_NONSPACE_RE = re.compile(r"[^\sA-Za-z0-9_가-힣]")

def approx_tokens(text: str) -> int:
    ascii_words = len(_ASCII_WORD_RE.findall(text))
    hangul_chars = len(_HANGUL_RE.findall(text))
    other_chars = len(_OTHER_NONSPACE_RE.findall(text))
    return ascii_words + hangul_chars + ((other_chars + 1) // 2)
```

- [ ] **Step 2: 단일 유닛이 목표를 넘을 때 분할하는 helper를 추가한다**

```python
def _split_oversized_unit(unit: str, target: int) -> list[str]:
    out, buf = [], []
    for ch in unit:
        candidate = "".join(buf) + ch
        if buf and approx_tokens(candidate) > target:
            out.append("".join(buf))
            buf = [ch]
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out
```

`_units()`의 반환 전에 각 unit을 이 helper로 펼치거나 `_windows()` 진입 전에 정규화한다. 빈 문자열은 버린다.

- [ ] **Step 3: 문서 문자열을 새 계약에 맞춘다**

`raw_chunks.py` 모듈 설명과 `tests/test_raw_chunks.py` 설명에서 “한글 글자수/2”를 제거하고 보수적 근사
계약을 적는다.

- [ ] **Step 4: raw chunk 테스트를 실행한다**

```bash
.venv/bin/python -m pytest tests/test_raw_chunks.py -v
```

Expected: PASS.

- [ ] **Step 5: 색인 회귀 테스트를 실행한다**

```bash
.venv/bin/python -m pytest tests/test_search_index.py -q
```

Expected: PASS.

- [ ] **Step 6: 청커 수정을 커밋한다**

```bash
git add src/project_brain/raw_chunks.py tests/test_raw_chunks.py
git commit -m "fix(raw-index): count Korean and markdown symbols conservatively"
```

## Task 4: 스킬 행동 계약 테스트를 먼저 추가

**Files:**
- Create: `tests/test_ingest_skill_contract.py`
- Create: `src/project_brain/templates/ingest/scripts/test_batch_tools.py`
- Modify: `tests/test_installer.py`

- [ ] **Step 1: 실제 세션 실패를 요구사항 표로 고정한다**

`tests/test_ingest_skill_contract.py` 상단 docstring에 다음 다섯 회귀를 적는다.

1. 전체 ID를 logical key로 쓰지 않는다.
2. 대량 적재는 item ingest와 finalization을 분리한다.
3. workflow top-level `completed`만으로 완료 처리하지 않는다.
4. 코드 흐름 적대검증은 프로젝트별 코드 검증 계약을 읽고 하위 작업자에게도 전달한다.
5. raw 파일명은 versioned spec과 bulk archive를 구분한다.

- [ ] **Step 2: SKILL 본문 크기와 routing 계약 테스트를 작성한다**

```python
def test_skill_is_a_compact_router(self):
    text = SKILL.read_text(encoding="utf-8")
    self.assertLessEqual(len(text.splitlines()), 170)
    for ref in REQUIRED_REFERENCES:
        self.assertIn(f"references/{ref}", text)

def test_generic_skill_routes_optional_project_code_verification(self):
    skill = SKILL.read_text(encoding="utf-8")
    playbook = (REFERENCES / "system-domain-playbook.md").read_text(encoding="utf-8")
    template_markdown = "\n".join(
        path.read_text(encoding="utf-8")
        for path in TEMPLATE_ROOT.rglob("*.md")
    )
    self.assertIn("validate_workflow_result.py", skill)
    self.assertIn("references/project-code-verification.md", skill)
    self.assertIn("프로젝트", playbook)
    self.assertIn("하위 작업자", playbook)
    self.assertNotIn("bb2-code-search-routing", template_markdown)
    self.assertNotIn("clangd callers", template_markdown)
```

`REQUIRED_REFERENCES`에는 파일 책임 지도에 나온 8개 reference를 넣는다.

- [ ] **Step 3: raw 정책의 단일 위치 계약을 작성한다**

`SKILL.md`에는 raw 상세 규칙 대신 `ingest-tools.md` 포인터만 있어야 하고,
`ingest-tools.md`에는 `spec-v<N>.md`, `sanitized-original-basename`, `analyze-spec-ppt`가 모두 있어야 한다.

- [ ] **Step 4: batch report와 workflow validator 테스트를 작성한다**

`test_batch_tools.py`에 다음 동작을 고정한다.

- 3개 중 2개 성공·1개 실패면 `finalized=false`이고 프로세스 반환값 1
- resume report에 성공한 2개가 있으면 실패한 1개만 재실행
- workflow `expected=3`, items 2개면 실패
- `failures`가 비어 있지 않으면 실패
- verify status가 `error`면 실패
- verdict가 `pass|fixed`가 아니면 실패
- 3개 모두 정상일 때만 성공

batch runner의 외부 명령은 임시 가짜 실행 파일을 만들어 호출 횟수와 exit code를 제어한다.

- [ ] **Step 5: installer 새 파일 계약을 작성한다**

`tests/test_installer.py`의 실제 템플릿 렌더 테스트에서 아래 파일이 설치되는지 확인한다.

- `scripts/finalize_ingest.sh`
- `scripts/run_ingest_batch.py`
- `scripts/validate_workflow_result.py`

`scripts/test_batch_tools.py`는 설치되지 않아야 한다. 설치 대상에 미리
`references/project-code-verification.md`를 만들고 installer를 두 번 실행한 뒤에도 내용이 같고,
`.project-brain-manifest.json`의 파일 목록에 이 경로가 없는지도 확인한다.

- [ ] **Step 6: 계약 테스트가 현재 실패하는지 확인한다**

```bash
.venv/bin/python -m pytest tests/test_ingest_skill_contract.py tests/test_installer.py -v
.venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

Expected: 새 파일과 축소 본문이 아직 없어 FAIL.

- [ ] **Step 7: RED 계약 테스트를 커밋한다**

```bash
git add tests/test_ingest_skill_contract.py tests/test_installer.py \
  src/project_brain/templates/ingest/scripts/test_batch_tools.py
git commit -m "test(ingest-skill): define bulk workflow and compact routing contracts"
```

## Task 5: 대량 실행과 workflow 완료 validator 구현

**Files:**
- Modify: `src/project_brain/templates/ingest/scripts/run_ingest.sh`
- Create: `src/project_brain/templates/ingest/scripts/finalize_ingest.sh`
- Create: `src/project_brain/templates/ingest/scripts/run_ingest_batch.py`
- Create: `src/project_brain/templates/ingest/scripts/validate_workflow_result.py`
- Test: `src/project_brain/templates/ingest/scripts/test_batch_tools.py`

- [ ] **Step 1: `run_ingest.sh`를 한 항목 책임으로 줄인다**

지원 인자:

```text
run_ingest.sh [--dry] [--defer-finalize] <verify.json> <domain_spec.py>
```

- 기본: assemble → build → ingest → `finalize_ingest.sh`
- `--dry`: assemble → build 후 종료
- `--defer-finalize`: assemble → build → ingest 후 종료
- `mktemp` 파일은 `trap`으로 정리한다.

- [ ] **Step 2: `finalize_ingest.sh`를 작성한다**

다음 순서를 `set -euo pipefail`로 실행한다.

```bash
project-brain index rebuild
project-brain lint
project-brain eval 2>/dev/null | jq '.summary'
project-brain search "이 컨텍스트 핵심 동작" 2>/dev/null | jq '.results | length'
project-brain graph isolated
python3 -m unittest discover -s brain/checks -p 'test_*.py'
```

`unittest` 실패를 “적재는 성공”으로 바꾸지 않는다. raw chunk 상수 드리프트라면 report에서 원인을 밝히고
상수를 의식적으로 갱신한 뒤 finalization 전체를 다시 실행한다.

- [ ] **Step 3: `validate_workflow_result.py`를 작성한다**

공개 함수는 다음 시그니처로 고정한다.

```python
def validate_result(payload: dict) -> list[str]:
    """빈 리스트면 완료, 아니면 적재를 막을 오류 목록."""
```

CLI는 JSON 경로 하나를 받고 성공 시 `{"ok": true, "completed": N}`를 출력하며 0, 실패 시
`{"ok": false, "errors": [...]}`를 출력하며 1을 반환한다.

- [ ] **Step 4: `run_ingest_batch.py`를 작성한다**

공개 함수와 CLI 계약:

```python
def run_batch(manifest_path, report_path, *, resume_path=None,
              item_runner=None, finalizer=None) -> dict:
    ...
```

- manifest 상대경로는 manifest 파일 디렉터리 기준으로 해석
- key 중복과 필수 경로 누락은 실행 전 실패
- item runner 기본값은 `run_ingest.sh --defer-finalize`
- 모든 item 성공 시에만 finalizer 호출
- report는 item마다 즉시 원자적으로 갱신
- `--resume`은 `succeeded` key만 건너뜀
- 실패 item은 key, exit code, stderr 마지막 2,000자를 기록

- [ ] **Step 5: batch 도구 테스트를 실행한다**

```bash
.venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

Expected: PASS.

- [ ] **Step 6: shell 문법을 검사한다**

```bash
bash -n src/project_brain/templates/ingest/scripts/run_ingest.sh
bash -n src/project_brain/templates/ingest/scripts/finalize_ingest.sh
```

Expected: 출력 없이 exit 0.

- [ ] **Step 7: batch 도구를 커밋한다**

```bash
git add src/project_brain/templates/ingest/scripts
git commit -m "feat(ingest-skill): add resumable batch runner and completion gate"
```

## Task 6: SKILL.md를 실행 라우터로 축소

**Files:**
- Modify: `src/project_brain/templates/ingest/SKILL.md`
- Modify: `src/project_brain/templates/ingest/references/scope.md`
- Modify: `src/project_brain/templates/ingest/references/object-model.md`
- Modify: `src/project_brain/templates/ingest/references/judgment.md`
- Modify: `src/project_brain/templates/ingest/references/completeness-checklist.md`
- Modify: `src/project_brain/templates/ingest/references/worked-example.md`

- [ ] **Step 1: 현재 세션을 RED 행동 증거로 기록한다**

`ingest-case-log.md`에 다음 네 행을 추가한다.

- 136개 대량 적재에서 단건 러너 대신 임시 wave/finalize 러너 작성
- workflow top-level completed와 내부 27개 실패 불일치
- 전체 ID key로 인한 이중 접두 24객체와 65객체 롤백
- 프로젝트 호출처 검증 계약을 적용해 68개 항목을 재검증하고 33개 수정

서술은 재사용 가능한 증상·조치만 남기고 세션 이야기를 길게 쓰지 않는다.

- [ ] **Step 2: 본문을 다섯 섹션으로 다시 쓴다**

최종 섹션은 아래로 고정한다.

1. `# {{PROJECT}} Brain 적재`
2. `## 적용 범위`
3. `## 절대 규칙`
4. `## 실행 흐름`
5. `## 단건과 대량 분기`
6. `## 완료 게이트`
7. `## Reference routing`

본문에는 객체 필드 표, 판정 다이어그램, 긴 실수 표, raw 상세 명령을 넣지 않는다.
`Reference routing`에는 `references/project-code-verification.md`가 존재하면 코드 기반 extract/verify 전에
직접 읽고, 그 계약을 동적 workflow와 하위 작업자 프롬프트에도 전달한다는 조건부 라우팅을 둔다.
특정 프로젝트 이름·스킬 이름·검색 도구 이름은 범용 본문에 넣지 않는다.

- [ ] **Step 3: 본문의 필수 규칙을 8개 이하로 정리한다**

반드시 남길 규칙:

- Source Intake 먼저
- 코드 동작 > 주석 > 보조 문서
- 메모리·handoff는 원문 근거가 아님
- 코드 앵커는 `{{DEFAULT_BRANCH}}` commit SHA
- 의미 원자 기준 객체화
- logical key에 전체 ID 금지
- 고위험 객체는 독립 적대검증
- `history_coverage`와 현재 검수 상태 분리

- [ ] **Step 4: 세 상태축의 단일 원본을 `scope.md`로 옮긴다**

본문·checklist·worked-example에서는 정의를 반복하지 않고 `scope.md`를 가리킨다. checklist에는 값이 정확히
하나 있는지만 남긴다.

- [ ] **Step 5: 객체와 key 계약을 `object-model.md`로 모은다**

logical key 정규식, anchor `--N` 예외, 완성 ID와의 차이, synonyms/aliases 게이트를 이 파일에서 한 번만
설명한다. 100줄을 넘으면 문서 첫 부분에 목차를 추가한다.

- [ ] **Step 6: 판정과 예시 중복을 줄인다**

대체·보완·충돌의 정의는 `judgment.md`만 소유한다. `worked-example.md`는 한 기능의 source → atom →
build → verify 결과만 보여준다.

- [ ] **Step 7: 본문 크기 계약을 확인한다**

```bash
wc -l -w src/project_brain/templates/ingest/SKILL.md
```

Expected: 130~170줄. 단어 수는 1,200 이하.

- [ ] **Step 8: 스킬 계약 테스트를 실행한다**

```bash
.venv/bin/python -m pytest tests/test_ingest_skill_contract.py -v
```

Expected: raw/batch 관련 후속 Task가 아직 반영되지 않았다면 해당 assertion만 FAIL하고, 크기·routing은 PASS.

- [ ] **Step 9: 본문과 핵심 reference 재배치를 커밋한다**

```bash
git add src/project_brain/templates/ingest/SKILL.md \
  src/project_brain/templates/ingest/references/{scope,object-model,judgment,completeness-checklist,worked-example,ingest-case-log}.md
git commit -m "docs(ingest-skill): reduce main skill to an execution router"
```

## Task 7: 대규모 코드 검증·raw 규약·실행 문서를 정리

**Files:**
- Modify: `src/project_brain/templates/ingest/references/system-domain-playbook.md`
- Modify: `src/project_brain/templates/ingest/references/ingest-tools.md`
- Modify: `src/project_brain/templates/ingest/references/completeness-checklist.md`
- Modify: `src/project_brain/templates/ingest/references/ingest-case-log.md`

- [ ] **Step 1: `system-domain-playbook.md`에 코드 검색 게이트를 추가한다**

다음을 명시한다.

```markdown
코드 흐름을 근거로 쓰면 프로젝트 AGENTS.md의 코드 검색 규칙을 따른다.
`references/project-code-verification.md`가 있으면 extract/verify 전에 읽는다.
호출처 추적 기록이나 추적이 불가능한 경계와 대체 확인 기록을 결과에 남긴다.
동적 workflow와 하위 작업자에게는 읽은 프로젝트 검증 계약을 프롬프트로 전달한다.
```

이 범용 문서에는 `bb2-code-search-routing`, clangd 같은 BB2 전용 이름을 넣지 않는다. 정확한 검색 도구와
예외 처리는 Task 10의 BB2 overlay가 소유한다.

- [ ] **Step 2: workflow 완료 게이트와 resume 절차를 추가한다**

최상위 `completed`를 완료 근거로 쓰지 말고, 결과 JSON을 `validate_workflow_result.py`에 통과시킨 뒤에만
조립 단계로 이동한다. 세션 한도 실패는 동일 run ID와 동일 입력으로 재개하고 validator를 다시 실행한다.

- [ ] **Step 3: `ingest-tools.md`에 단건·대량 명령을 나눈다**

단건:

```bash
scripts/run_ingest.sh verify.json domain_spec.py
```

대량:

```bash
scripts/run_ingest_batch.py batch.json --report batch-report.json
scripts/run_ingest_batch.py batch.json --report batch-report.json --resume batch-report.json
```

중간 item 실행은 색인을 만들지 않고, 전체 성공 후 finalization 한 번이라는 점을 명시한다.

- [ ] **Step 4: raw 파일명 모드를 분리한다**

- 개정 기획서: `spec-v<N>.md`, `analyze-spec-ppt` 규약 우선
- 대량 보관/버전 불명: 안전하게 정리한 원본 basename
- manifest에는 원본 파일명·변환 도구·캡처 시각 기록
- 바이너리 미추적 유지

- [ ] **Step 5: 완료 checklist를 실행 가능한 게이트로 줄인다**

다음을 확인한다.

- workflow validator 통과
- batch report `expected == len(succeeded)`, `failed=[]`, `finalized=true`
- lint 0
- eval 전부 통과
- 신규 고립 0
- real-corpus unittest 통과
- 샘플 회상에 mapping과 linked code locator가 함께 나옴

- [ ] **Step 6: 100줄 이상 reference에 목차가 있는지 검사한다**

```bash
for f in src/project_brain/templates/ingest/references/*.md; do
  lines=$(wc -l < "$f")
  if [ "$lines" -gt 100 ]; then rg -q '^## 목차$' "$f" || exit 1; fi
done
```

Expected: exit 0.

- [ ] **Step 7: 문서 계약 테스트를 실행한다**

```bash
.venv/bin/python -m pytest tests/test_ingest_skill_contract.py -v
```

Expected: PASS.

- [ ] **Step 8: 대규모 운영 계약을 커밋한다**

```bash
git add src/project_brain/templates/ingest/references
git commit -m "docs(ingest-skill): harden bulk workflow and code-flow verification"
```

## Task 8: installer와 템플릿 전체 검증

**Files:**
- Modify: `tests/test_installer.py`
- Modify: `src/project_brain/templates/CHANGELOG.md`

- [ ] **Step 1: installer 테스트를 실행한다**

```bash
.venv/bin/python -m pytest tests/test_installer.py -v
```

Expected: 새 실행 스크립트 3개 설치, `test_batch_tools.py` 미설치, manifest 보존 테스트 PASS.

- [ ] **Step 2: 템플릿 스크립트 전체 테스트를 실행한다**

```bash
.venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

Expected: PASS.

- [ ] **Step 3: 렌더된 skill 기본 형식을 검사한다**

```bash
INGEST_VALIDATE_DIR=$(mktemp -d)
trap 'rm -rf "$INGEST_VALIDATE_DIR"' EXIT
.venv/bin/project-brain install --target "$INGEST_VALIDATE_DIR" \
  --project demo --brain-root brain --default-branch main --repo demo_repo
.venv/bin/python /Users/al03040455/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  "$INGEST_VALIDATE_DIR/.agents/skills/demo-brain-ingest"
```

Expected: valid skill.

- [ ] **Step 4: CHANGELOG에 변경 묶음을 기록한다**

한 단락에 key guard, raw chunk 보수화, batch/finalize, workflow validator, 프로젝트 코드 검증 계약 routing,
raw 이름 분기, SKILL 130~170줄 축소를 기록한다. 실제 BB2 전파 커밋은 전파 후 채운다.

- [ ] **Step 5: 엔진 관련 테스트 묶음을 실행한다**

```bash
.venv/bin/python -m pytest \
  tests/test_assembly.py tests/test_raw_chunks.py tests/test_embedder.py \
  tests/test_installer.py tests/test_ingest_skill_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: 엔진 전체 테스트를 실행한다**

```bash
.venv/bin/python -m pytest tests -q
```

Expected: PASS.

- [ ] **Step 7: 템플릿 변경을 커밋한다**

```bash
git add tests/test_installer.py tests/test_ingest_skill_contract.py \
  src/project_brain/templates/CHANGELOG.md
git commit -m "test(ingest-skill): verify canonical template and installer rollout"
```

## Task 9: 작은 행동 시나리오로 스킬 전후 검증

**Files:**
- Read: `src/project_brain/templates/ingest/SKILL.md`
- Read: `docs/specs/2026-07-21-bulk-ingest-hardening-design.md`

- [ ] **Step 1: 기존 세션을 baseline 실패로 연결한다**

다음 실제 실패를 RED 근거로 사용한다.

- full ID key → 이중 접두 24개
- workflow completed + 내부 실패
- 단건 runner 때문에 임시 wave runner 작성
- callers 미추적 뒤 재검증에서 33개 수정
- MPS 24.29GiB

- [ ] **Step 2: 수정된 스킬로 단건 시나리오를 실행한다**

Prompt:

```text
완료된 기능 sample-a를 brain에 적재해 줘. 현재 코드만 근거로 쓰고 변경 이력은 찾지 마.
```

Expected: Source Intake를 선언하고 단건 경로를 선택하며 `history_coverage=unsearched`를 남긴다.

- [ ] **Step 3: 부분 실패 batch 시나리오를 실행한다**

Prompt:

```text
세 항목을 동적 워크플로우로 추출했다. 최상위 상태는 completed지만 한 항목 verify가 error다.
이 상태에서 적재를 마무리해 줘.
```

Expected: 적재하지 않고 workflow validator 실패를 보고하며 실패 항목 재개를 요구한다.

- [ ] **Step 4: 코드 흐름 시나리오를 실행한다**

Prompt:

```text
일반 C++ 메서드가 실제 런타임에서 호출되는지 확인해 매핑으로 적재해 줘.
```

Expected: BB2 설치본이 `project-code-verification.md`를 읽고 `bb2-code-search-routing`을 사용하며,
clangd callers query를 근거에 남긴다.

- [ ] **Step 5: logical key 시나리오를 실행한다**

Prompt:

```text
mapping key로 mapping.sample-a.core-behavior를 사용해 적재해 줘.
```

Expected: 전체 ID를 key로 쓰지 않고 `core-behavior`로 수정하거나, build 전 입력 오류로 멈춘다.

- [ ] **Step 6: raw 이름 분기 시나리오를 실행한다**

Prompt:

```text
한 기능의 개정 기획서 2개와 서로 다른 옛 기획서 20개를 raw에 보관해 줘.
```

Expected: 개정본은 `spec-v<N>.md`, 옛 문서 묶음은 안전하게 정리한 원본 basename을 사용한다.

- [ ] **Step 7: 행동 검증 결과를 커밋 메시지 본문용 메모로 정리한다**

스킬 본문에 결과를 추가하지 않는다. 실패가 있으면 해당 계약의 최소 문구나 validator만 보강하고 같은
시나리오를 다시 실행한다.

## Task 10: BB2 설치본 전파

**Files:**
- Modify: `/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-brain-ingest/**`
- Create: `/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-brain-ingest/references/project-code-verification.md`
- Modify: `/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.project-brain-manifest.json`
- Read only: `/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/AGENTS.md`
- Read only: `/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-code-search-routing/SKILL.md`

- [ ] **Step 1: 깨끗한 BB2 작업공간인지 확인한다**

```bash
git -C /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening status --short
```

Expected: 출력 없음. 기존 `/Users/al03040455/Desktop/bb2_client` 작업공간의 사용자 변경을 사용하지 않는다.

- [ ] **Step 2: force 없이 installer를 실행한다**

```bash
PYTHONPATH=/Users/al03040455/Downloads/codes/project-brain-bulk-ingest-hardening/src \
  /Users/al03040455/Downloads/codes/project-brain/.venv/bin/python \
  -m project_brain.cli install \
  --target /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening
```

Expected: JSON `ok=true`, `skipped=[]`, ingest skill 파일은 `updated` 또는 `created`에 포함.

- [ ] **Step 3: BB2 전용 코드 검증 overlay를 추가한다**

installer 실행 뒤 다음 파일을 만든다.

```markdown
# BB2 코드 근거 검증

**REQUIRED SUB-SKILL:** 코드 흐름을 근거로 적재하거나 검증할 때 `bb2-code-search-routing`을 사용한다.

- 일반 함수·메서드 호출처는 clangd callers를 우선한다.
- 매크로 생성 심볼은 `rg`로 추적한다.
- notification/callback 경계는 발신과 수신을 `rg`로 잇고, 양쪽 심볼 callers를 가능한 범위에서 확인한다.
- 결과에는 실행한 query, 시작 심볼, 확인한 경계, 끊긴 지점을 기록한다.
- 동적 workflow와 하위 작업자 프롬프트에도 이 계약을 그대로 전달한다.
- 코드로 확인 가능한데 위 기록이 없으면 `needs_user`가 아니라 검증 실패로 판정한다.
```

이 파일은 BB2가 소유하며 project-brain 템플릿이나 installer manifest에 추가하지 않는다. 기존 `AGENTS.md`와
`bb2-code-search-routing/SKILL.md`는 이미 필요한 라우팅을 소유하므로 수정하지 않는다.

- [ ] **Step 4: installer 재실행이 overlay를 보존하는지 확인한다**

```bash
BB2_OVERLAY=/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-brain-ingest/references/project-code-verification.md
before=$(shasum -a 256 "$BB2_OVERLAY" | awk '{print $1}')
PYTHONPATH=/Users/al03040455/Downloads/codes/project-brain-bulk-ingest-hardening/src \
  /Users/al03040455/Downloads/codes/project-brain/.venv/bin/python \
  -m project_brain.cli install \
  --target /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening
after=$(shasum -a 256 "$BB2_OVERLAY" | awk '{print $1}')
test "$before" = "$after"
! rg -n 'project-code-verification\.md' \
  /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.project-brain-manifest.json
```

Expected: 재설치 report의 `skipped=[]`, overlay 해시 동일, manifest 검색 결과 없음.

- [ ] **Step 5: 템플릿 치환자가 남지 않았는지 확인한다**

```bash
rg -n '\{\{(PROJECT|BRAIN_ROOT|DEFAULT_BRANCH|REPO)\}\}' \
  /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-brain-ingest
```

Expected: 출력 없음.

- [ ] **Step 6: 설치본 스킬 형식을 검사한다**

```bash
/Users/al03040455/Downloads/codes/project-brain/.venv/bin/python \
  /Users/al03040455/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-brain-ingest
```

Expected: valid skill.

- [ ] **Step 7: BB2 코드 검증 연결을 확인한다**

```bash
rg -n 'bb2-code-search-routing|clangd callers|매크로 생성 심볼|notification/callback|하위 작업자' \
  /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-brain-ingest/references/project-code-verification.md
```

Expected: 다섯 계약이 모두 overlay에서 확인되고, 범용 template에는 BB2 전용 문자열이 없음.

- [ ] **Step 8: agents-doctor를 실행한다**

```bash
cd /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening
python3 .agents/skills/agents-doctor/scripts/doctor.py --root "$PWD"
```

Expected: exit 0, 깨진 심링크·skill mirror 오류 없음.

- [ ] **Step 9: 설치본 스크립트 테스트와 문법 검사를 실행한다**

```bash
/Users/al03040455/Downloads/codes/project-brain/.venv/bin/python -m unittest discover \
  -s /Users/al03040455/Downloads/codes/project-brain-bulk-ingest-hardening/src/project_brain/templates/ingest/scripts \
  -p 'test_*.py'
bash -n /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-brain-ingest/scripts/run_ingest.sh
bash -n /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-brain-ingest/scripts/finalize_ingest.sh
```

Expected: PASS, shell exit 0.

- [ ] **Step 10: BB2 변경을 커밋한다**

```bash
git -C /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening add \
  .agents/skills/bb2-brain-ingest .project-brain-manifest.json
git -C /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening commit -m \
  "skills(bb2-brain-ingest): harden bulk ingest and compact routing"
```

## Task 11: 실제 코퍼스와 최종 회귀 검증

**Files:**
- Modify only if count changed intentionally: `/Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/brain/checks/test_real_corpus.py`

- [ ] **Step 1: 임시 stub 색인으로 raw chunk 수를 재측정한다**

```bash
cd /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening
tmp_db=$(mktemp -t project-brain-index.XXXXXX.db)
trap 'rm -f "$tmp_db"' EXIT
project-brain index rebuild --brain-root brain --db "$tmp_db" --stub-embedder
```

Expected: MPS를 쓰지 않고 새 `raw_chunks` 수 출력. 임시 DB 경로만 사용한다.

- [ ] **Step 2: raw chunk 가드가 바뀌면 이유를 확인하고 상수를 갱신한다**

청커 변경으로 인한 증가인지 확인한다. 객체 수나 다른 가드는 건드리지 않는다.

- [ ] **Step 3: 실제 BB2 brain 검증을 실행한다**

```bash
cd /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening
project-brain lint
project-brain eval 2>/dev/null | jq '.summary'
project-brain graph isolated 2>/dev/null | jq '{isolated_count, by_kind}'
python3 -m unittest discover -s brain/checks -p 'test_*.py'
```

Expected: lint 문제 0, eval 전부 통과, 기존 기준 대비 신규 고립 0, unittest PASS.

- [ ] **Step 4: MPS 실모델 smoke를 한 번 실행한다**

```bash
cd /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening
project-brain index rebuild
```

Expected: `Invalid buffer size` 없이 완료. 실행 중 메모리 사용량은 관찰하되 결과 판정은 exit code와 색인
출력으로 한다.

- [ ] **Step 5: 샘플 회상을 확인한다**

```bash
project-brain search "설치형 콤보폭탄이 뭐야" 2>/dev/null | jq '.results[0:5]'
project-brain search "현재 슈팅된 버블 조회" 2>/dev/null | jq '.results[0:5]'
```

Expected: 기존 reviewed mapping이 회수되고 linked code locator가 유지된다.

- [ ] **Step 6: 청크 가드 변경이 있으면 별도 BB2 커밋을 만든다**

```bash
git -C /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening add brain/checks/test_real_corpus.py
git -C /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening commit -m \
  "test(brain): update raw chunk guard for conservative token estimate"
```

가드가 바뀌지 않았으면 이 단계는 파일 수정과 커밋 없이 종료한다.

## Task 12: 완료 전 자체 검토

**Files:**
- Read: `docs/specs/2026-07-21-bulk-ingest-hardening-design.md`
- Read: `docs/plans/2026-07-21-bulk-ingest-hardening.md`

- [ ] **Step 1: 설계 요구사항과 구현 커밋을 대조한다**

E1~E3, S1~S5 각각에 코드·문서·테스트가 하나 이상 연결되는지 체크한다.

- [ ] **Step 2: 미완성 문구와 모순을 검색한다**

```bash
rg -n 'T[B]D|T[O]DO|implement[[:space:]]+later|fill[[:space:]]+in' \
  docs/specs/2026-07-21-bulk-ingest-hardening-design.md \
  docs/plans/2026-07-21-bulk-ingest-hardening.md \
  src/project_brain/templates/ingest
```

Expected: `extract_template.js`의 의도된 채워넣기 슬롯 외 새 미완성 표식 없음. 슬롯은 실행 템플릿 계약이므로
그 파일 안에서만 허용한다.

- [ ] **Step 3: 범용 템플릿과 BB2 전용 계약의 경계를 검사한다**

```bash
! rg -n 'bb2-code-search-routing|clangd callers' \
  /Users/al03040455/Downloads/codes/project-brain-bulk-ingest-hardening/src/project_brain/templates/ingest
rg -n 'bb2-code-search-routing|clangd callers' \
  /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.agents/skills/bb2-brain-ingest/references/project-code-verification.md
! rg -n 'project-code-verification\.md' \
  /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening/.project-brain-manifest.json
```

Expected: BB2 전용 이름은 overlay에서만 확인되고, 범용 템플릿과 installer manifest에는 없음.

- [ ] **Step 4: 두 저장소 diff를 검사한다**

```bash
git -C /Users/al03040455/Downloads/codes/project-brain-bulk-ingest-hardening diff --check
git -C /Users/al03040455/orca/workspaces/bb2_client/bulk-ingest-hardening diff --check
```

Expected: 출력 없이 exit 0.

- [ ] **Step 5: 최종 테스트 명령과 실제 결과를 기록한다**

엔진 전체 pytest, 템플릿 unittest, quick_validate, installer report, agents-doctor, BB2 lint/eval/graph/
unittest, MPS 실모델 색인 결과를 최종 보고에 포함한다.
