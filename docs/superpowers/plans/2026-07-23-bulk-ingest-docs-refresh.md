# Bulk Ingest Documentation Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대량 적재 강화 뒤 달라진 Project Brain 엔진·installer·스킬 계약을 현재 정본 문서와 완료 기록에 반영하고 검증된 `main`을 push한다.

**Architecture:** 과거 날짜 문서는 당시 실행 기록으로 보존하고, 현재 동작을 설명하는 living docs를 코드에 맞춘다. 이번 설계·계획에는 완료 메모만 추가하고, 별도 완료 보고서가 구현·검증·BB2 전파 증거의 단일 요약본을 맡는다.

**Tech Stack:** Markdown, Python 3.11 pytest/unittest, Bash syntax checks, Git

---

### Task 1: 사용자·유지보수자 진입 문서 갱신

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: README의 installer 계약을 현재 코드로 교체한다**

`## 프로젝트에 붙이기` 아래에 다음 계약을 명시한다.

```markdown
- manifest와 일치하는 관리 파일만 자동 갱신한다.
- 내용이 같은 manifest 밖 파일은 채택하고 실행 비트를 템플릿과 맞춘다.
- 템플릿에서 사라진 관리 파일은 미수정 상태일 때만 제거한다.
- 사용자 수정 파일·프로젝트 overlay는 보존한다.
- 퇴역 처리나 manifest 확정이 실패하면 옮긴 파일을 원위치로 rollback한다.
```

- [ ] **Step 2: README에 단건·batch 적재 경로를 추가한다**

`## 주요 명령` 뒤에 `## 적재 실행 경로`를 만들고 다음 흐름을 설명한다.

```text
single: validate workflow(해당 시) → run_ingest.sh → semantic finalization
batch: validate_workflow_result.py → run_ingest_batch.py --report ... [--resume ...]
       → 모든 item 성공 → semantic finalization 1회
```

logical key, `--defer-finalize`, 항목별 exact `ok`, report 입력 파일 충돌 금지,
`finalized=true` 완료 기준을 함께 적는다.

- [ ] **Step 3: CLAUDE.md의 개발·실코퍼스 검증 계약을 갱신한다**

개발 루프에 아래 두 명령을 모두 넣는다.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

실코퍼스 설명의 `골든셋 7종`은 현재 BB2 검증값 `15/15`로 고치고, 데이터 레포 명령도
명시적인 feature/main 엔진 Python을 쓸 수 있음을 적는다. installer 변경 체크리스트에는
퇴역 파일·manifest rollback·overlay 비관리·2회차 no-op을 추가한다.

- [ ] **Step 4: 문서 diff를 검사한다**

Run:

```bash
git diff --check -- README.md CLAUDE.md
rg -n '퇴역|rollback|run_ingest_batch|15/15|test_.*\.py' README.md CLAUDE.md
```

Expected: whitespace 오류가 없고 새 계약이 두 문서에서 검색된다.

### Task 2: 설계 정본·구현 참조·로드맵 갱신

**Files:**
- Modify: `ROADMAP.md`
- Modify: `docs/design-canonical.md`
- Modify: `docs/search-internals.md`
- Modify: `src/project_brain/templates/CHANGELOG.md`

- [ ] **Step 1: ROADMAP 현황과 문서 개수를 현재 값으로 맞춘다**

문서 개수는 `docs/specs/` 19개, `docs/plans/` 46개, `docs/skill-drafts/` 3개로 적는다.
층별 현황의 L0와 L4에 각각 보수적 raw chunk 분할과 single/batch semantic completion gate를
추가한다.

- [ ] **Step 2: ROADMAP에 2026-07-22~23 완료 단계를 추가한다**

다음을 하나의 완료 섹션으로 기록한다.

```text
logical key fail-fast
conservative raw token estimate + oversized unit split
resumable batch + exact workflow validator + semantic finalizer
compact ingest router + centralized update-rules
installer retired-file pruning, safe path preflight, executable adoption,
manifest/input collision rejection, rollback on interrupted retirement
BB2 7,092 documents / 1,577 raw chunks / eval 15/15
engine 611 pytest + 26 subtests / template 59 unittest
```

기존 2026-06-29 installer 섹션에는 이번 hardening을 후속 계약으로 연결한다.

- [ ] **Step 3: design-canonical에 엔진 강제 경계를 추가한다**

L4 적재와 엔진/데이터 경계에 다음 원칙을 넣는다.

- 판단은 스킬·사람이 하고 엔진은 logical key·schema·완료 상태를 fail-closed로 검증한다.
- batch item은 색인 없이 적재하고 전체 성공 뒤 finalization을 한 번만 수행한다.
- installer manifest는 범용 템플릿 소유 파일만 관리하며 프로젝트 overlay는 소유하지 않는다.
- 템플릿 퇴역 파일은 미수정 관리 파일만 transaction-like rollback 경로로 제거한다.

- [ ] **Step 4: search-internals의 raw·embedder 설명을 코드에 맞춘다**

`src/project_brain/embedder.py`와 `raw_chunks.py`를 근거로 다음을 반영한다.

```text
RealEmbedder: model max sequence length를 2,048 이하로 제한하고 batch size 8 사용
approx_tokens: ASCII word 1 + Hangul syllable 1 + other non-space symbols 2 chars per token
oversized unit: 한 유닛이 target을 넘으면 문자 경계로 다시 분할
```

오래된 줄번호를 현재 `rg -n` 결과에 맞추고, 동작 설명과 코드가 어긋나지 않는지 확인한다.

- [ ] **Step 5: template CHANGELOG에 최종 안전 보강을 추가한다**

2026-07-23 항목으로 update-rules 소유권 이동, exact workflow gate, semantic finalization,
report 입력 충돌 거부, 실행 비트 채택, 퇴역 파일 rollback을 기록한다.

- [ ] **Step 6: 정본 문서 diff를 검사한다**

Run:

```bash
git diff --check -- ROADMAP.md docs/design-canonical.md \
  docs/search-internals.md src/project_brain/templates/CHANGELOG.md
rg -n '1,577|15/15|rollback|2,048|logical key' \
  ROADMAP.md docs/design-canonical.md docs/search-internals.md \
  src/project_brain/templates/CHANGELOG.md
```

Expected: 현재 수치와 계약이 검색되고 whitespace 오류가 없다.

### Task 3: 이번 작업의 완료 기록 작성

**Files:**
- Modify: `docs/specs/2026-07-21-bulk-ingest-hardening-design.md`
- Modify: `docs/plans/2026-07-21-bulk-ingest-hardening.md`
- Create: `docs/reports/2026-07-23-bulk-ingest-hardening-completion.md`

- [ ] **Step 1: spec와 plan 맨 앞에 완료 메모를 추가한다**

두 문서의 제목 바로 아래에 2026-07-23 완료 상태를 적는다. plan에는 원래 경로와 체크박스가
역사 기록임을 밝히고, 실제 실행 경로를 다음처럼 기록한다.

```text
Project Brain: /Users/al03040455/Downloads/codes/project-brain
feature worktree: .worktrees/bulk-ingest-hardening
BB2: /Users/al03040455/Desktop/bb2_client
engine main merge: 182e650, post-merge test fix: f3a7053
```

- [ ] **Step 2: 최종 완료 보고서를 작성한다**

보고서는 요약, 변경 영역, Task 9 행동 증거, installer 안전 모델, BB2 전파, 실코퍼스 수치,
검증 명령·결과, 운영 주의 순으로 구성한다. 검증값은 다음으로 고정한다.

```text
engine: 611 passed, 26 subtests
template: 59 unittest
BB2 corpus guard: 5 unittest
BB2 lint: 0 problems
BB2 eval: 15/15
BB2 graph isolated: 15 existing nodes
index: 7,092 documents, 1,577 raw_chunk, 7,092 vector rowids
fingerprint: 3afb552862238abbfeb6853b9fc688e12e285981281f2094be2a227e48a602f3
```

모델 캐시는 삭제하지 않았고, 올바른 feature 엔진으로 실모델 rebuild를 한 번 완료했으며,
마지막 검증은 rebuild 없이 기존 캐시를 읽었다는 경계도 기록한다.

- [ ] **Step 3: 문서 링크와 완료 기록을 검사한다**

Run:

```bash
git diff --check -- docs/specs/2026-07-21-bulk-ingest-hardening-design.md \
  docs/plans/2026-07-21-bulk-ingest-hardening.md \
  docs/reports/2026-07-23-bulk-ingest-hardening-completion.md
rg -n '상태.*완료|역사 기록|611 passed|1,577|3afb5528' \
  docs/specs/2026-07-21-bulk-ingest-hardening-design.md \
  docs/plans/2026-07-21-bulk-ingest-hardening.md \
  docs/reports/2026-07-23-bulk-ingest-hardening-completion.md
```

Expected: 세 문서가 완료 상태와 실제 수치를 포함한다.

- [ ] **Step 4: 문서 변경을 커밋한다**

```bash
git add README.md CLAUDE.md ROADMAP.md docs/design-canonical.md \
  docs/search-internals.md src/project_brain/templates/CHANGELOG.md \
  docs/specs/2026-07-21-bulk-ingest-hardening-design.md \
  docs/plans/2026-07-21-bulk-ingest-hardening.md \
  docs/reports/2026-07-23-bulk-ingest-hardening-completion.md
git commit -m "docs: finalize bulk ingest hardening guidance"
```

### Task 4: 전체 검증과 push

**Files:**
- Verify only: entire repository

- [ ] **Step 1: 문서 상대 링크를 검사한다**

Python 표준 라이브러리로 변경된 Markdown의 상대 링크를 추출하고, anchor·외부 URL을 제외한
각 대상 파일이 존재하는지 확인한다.

- [ ] **Step 2: stale 문구와 placeholder를 검사한다**

```bash
rg -n '한글.*절반|골든셋 7종|571 passed|572 passed|607 passed|608 passed' \
  README.md ROADMAP.md CLAUDE.md docs/design-canonical.md docs/search-internals.md \
  src/project_brain/templates/CHANGELOG.md
rg -n 'T[B]D|T[O]DO|implement[[:space:]]+later|fill[[:space:]]+in' \
  docs/reports/2026-07-23-bulk-ingest-hardening-completion.md
```

Expected: stale 문구와 placeholder가 없다.

- [ ] **Step 3: 엔진과 템플릿 회귀를 실행한다**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
bash -n src/project_brain/templates/ingest/scripts/*.sh
git diff --check
```

Expected: `611 passed, 26 subtests passed`, `Ran 59 tests ... OK`, shell과 diff 검사 exit 0.

- [ ] **Step 4: push 직전 원격 관계를 확인한다**

```bash
git fetch origin main
git rev-list --left-right --count main...origin/main
git status --short --branch
```

Expected: 오른쪽 값 0, worktree clean.

- [ ] **Step 5: main을 push하고 원격 반영을 확인한다**

```bash
git push origin main
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

Expected: 로컬 HEAD와 원격 `refs/heads/main` SHA가 같다.
