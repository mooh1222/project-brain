# GitHub #2~#13 정리 실행 계획

- 승인일: 2026-08-25
- 코드 기준점: `b35d351ee77093392ca170f799d0edc1a8414070`
- 작업 branch: `codex/brain-ticket-reconcile-v2-20260825`
- 과거 통합 후보: `75e97fa98308b8bd7434070e05a99e69f2a5adef`
- 과거 정리 branch: `codex/brain-ticket-reconcile-20260825` (`272b303`)
- #33 보존 branch: `codex/issue-33-evidence-design-admission` (`8341d7a`)

## 목적과 변경 경계

이 계획은 현재 `main`의 공개 기능, `main`에 남은 내부 부분 구현, 미병합 후보, 설계 전용 작업을
분리한 뒤 안전한 후보부터 독립적으로 닫는 실행 순서다. 과거 통합 후보를 통째로 병합하거나 새
제품 기준선으로 사용하지 않는다.

현재 승인 범위는 다음뿐이다.

- 이 실행 계획과 새 진행 기록 작성
- evidence preparation과 `context_md` artifact lifecycle 설계 분리
- session completion과 zero-work closure 설계 분리
- GitHub #34의 입장 상태 교정과 신규 설계 issue·dependency 생성
- #2·#4·#5의 최종 분리 후보를 위해 후보 상한을 각각 3회에서 4회로 한 번만 확장

엔진 코드 수정, `main` 병합·push, 기존 issue 종료는 이 승인에 포함되지 않는다. 각 단계의 파일
수정·commit·push·GitHub 변경은 고정된 대상과 예상 효과를 먼저 확인한 뒤 실행한다.

## 보존 경계

다음 작업물은 원본 위치에서 수정·stage·stash·clean하지 않는다.

| 위치 | 보존 대상 | 기준 |
|---|---|---|
| main checkout | `.gitignore`, `.agent-team/**`, `.agents/**` | 상태 목록 SHA-256 `7be3dcf9c6a119de8c273c7ea804962f477d9921f809dd8161eb3ad75a6a04b9` |
| #33 worktree | `docs/specs/2026-08-25-evidence-preparation-repair-design.md` 미커밋 수정 | diff SHA-256 `8d9385dab45cd9ea159353354a18fbd1316b79ea6116bc845ecaaac339936b32` |
| 과거 정리 branch | 코드·문서·진행 기록 전체 | `272b3031353a2da104ef5b2dae6601b478e75792` |

새 정리는 `main@b35d351`에서 만든 격리 worktree 한 곳에서만 쓴다. 과거 `.goal/brain-ticket-reconcile/
progress.md`는 당시 후보·검수·설계복귀 기록으로 보존하며 새 실행 장부로 이어 쓰지 않는다.

## 현재 정본

| 구분 | 현재 사실 |
|---|---|
| 공개 기능 | `main`의 기존 query/audit/ingest/promote, `projection build-reuse/refresh`, `session list/mark-processed` |
| 내부 부분 구현 | `context_projection.py`의 `render_context_markdown()`·`build_context_projection()`과 `context_md` schema/lint 기반. 공개 builder 명령과 실제 생성 artifact 근거는 없음 |
| 미병합 후보 | #2~#10 코드·테스트와 두 명확한 수리(locator evidence v2, CodeLocator promote repo context). 공개 ingest 회귀와 미완성 계약 때문에 전체 병합 금지 |
| 설계 전용 | evidence/session repair, #11~#13·#33~#37, 지식 초안 ADR과 #20~#23 |
| 수동 문서 | 루트 `CONTEXT.md`. 생성 `CONTEXT.md`, `context_md` format, 지식 초안과 서로 다른 대상 |

지식 초안은 소비 프로젝트의 `brain/drafts/<topic-id>.md`에 둘 설계 제안이다. `ContextProjection`,
생성 `CONTEXT.md`, session 처리 기록과 합치지 않는다. #20~#23은 기존 blocker가 풀릴 때까지 건드리지
않는다.

## 후보 처리 결정

| 범위 | 결정 | 다음 후보의 정확한 경계 |
|---|---|---|
| #2 | 유지·분리 | `9aefa36`의 query/audit·설치 template·관련 테스트만 `main` 위에 재구성 |
| #4 | 유지·분리 | `698dc3e`의 `capabilities.py`와 `tests/test_capabilities.py` |
| #5 | 유지·분리 | `160050c`의 snapshot 동결 코드·테스트·runtime map |
| #3 | 보강 | #34와 zero-work 설계가 각각 입장 통과한 뒤 새 session-runtime child issue·새 장부 생성. parent #3에는 새 후보를 직접 만들지 않음 |
| #6 | 유지·보강 | common verification과 locator/promote 수리는 유지하고 public evidence preparation은 새 child issue에서 구현 |
| #7·#8 | 유지·후순위 | #6 공개 경계 뒤 종류별 public ingest/projection/promote 회귀를 새 child issue에서 다시 고정 |
| #9 | 분리 | local raw observation과 원격 source-specific Adapter를 각각 새 child issue로 분리 |
| #10 | 분리 | derived output validation·실제 builder child와 `context_md` object+artifact child를 새 issue로 분리. parent #10은 둘 다 끝난 뒤에만 종료 |
| 전체 branch | 폐기 | `272b303` 또는 `75e97fa` 전체 병합과 이를 다음 제품 기준선으로 쓰는 경로 |

## 문서 적용 원칙

- `ROADMAP.md`에는 위 네 상태와 실제 실행 순서만 기록한다.
- `docs/architecture/**`는 해당 코드가 `main`에 들어가는 후보와 같은 commit에서만 바꾼다. 아직 없는
  `capabilities.py`, `verification.py`, `dedicated_proof*.py`를 현재 `main` 경로처럼 먼저 적지 않는다.
- ADR 0004·0005의 `implementation: not_implemented`는 실제 공개 경계가 합쳐질 때까지 유지한다.
- 지식 초안 ADR 0006과 `CONTEXT.md`는 이미 개념 경계를 충분히 설명하므로 이번 정리에서 고치지 않는다.
- 과거 재정리 보고서와 진행 기록은 증거로 보존하되 새 정본 문서로 복사하지 않는다.

## 역사 상한과 새 child 경계

과거 장부의 카운터를 새 장부에서 0으로 초기화하지 않는다.

- #3·#6·#9·#10 parent는 검수 3/3과 설계복귀 1/1에 도달했으므로 새 구현 후보·exact review를
  parent에 직접 기록하지 않는다. admission을 통과하면 범위가 닫힌 새 구현 child issue와 새 progress
  block을 만들고 그 child만 새 상한을 사용한다.
- #7·#8 parent는 후보 3/3이라 새 후보를 직접 만들 수 없다. #6 public 경계가 끝난 뒤 표적 회귀를
  별도 child로 발행한다.
- #2·#4·#5만 사용자가 승인한 예외에 따라 parent의 후보 4를 한 번 만들 수 있다.
- #3·#6·#7·#8·#9·#10 parent는 child 결과와 기존 blocker를 모으는 closeout-only umbrella다. 이번
  1단계에서는 구현 child를 만들지 않는다.

## GitHub 목표 구조

현재 상태가 맞는 issue는 유지한다.

- #3·#6·#9·#10·#11·#12·#13: `needs-triage`
- #2·#4·#5·#7·#8: `ready-for-agent`
- #33: `needs-triage`
- #35 blocked by #33, #36·#37 blocked by #35
- #20~#23: 기존 upstream dependency 유지

이번 단계에서 교정할 구조는 다음과 같다.

1. #34는 완료 조건 7개와 조건별 정확한 명령 부재 때문에 입장 조건 A3·A4를 충족하지 않는다.
   `ready-for-agent`를 제거하고 `needs-triage`로 돌린 뒤 #33을 blocker로 둔다.
2. evidence preparation 핵심과 `context_md` artifact lifecycle을 분리한다.
   - #33: common/dedicated evidence preparation, public ingest/projection input, identity, receipt, TOCTOU
   - 신규 issue: `context_md` object+artifact path, action, journal, rollback, recovery
3. session completion 핵심과 explicit zero-work를 분리한다.
   - #34: item이 한 개 이상인 session binding, report, marker v2, retry·legacy
   - 신규 issue: zero-work attestation·finalization·receipt와 unresolved-only/partial-unresolved 재시작
4. dependency 방향은 `child blocked by blocker`로 검증한다.
   - #34 blocked by #33
   - `context_md` 신규 issue blocked by #33; #10 closeout blocked by 신규 issue
   - zero-work 신규 issue blocked by #34; #3 blocked by zero-work 신규 issue

이 작업은 Wayfinder map 탐색이 아니라 이미 승인된 #1 issue graph의 계약 복구다. Wayfinder 라벨이나
별도 map issue를 자동으로 만들지 않는다.

## 실행 순서와 완료 확인

### 1단계: 정본 문서와 설계 issue 분리

대상 파일:

- `docs/plans/2026-08-25-issues-2-13-cleanup-execution-plan.md`
- `.goal/brain-ticket-reconcile-v2/progress.md`
- `ROADMAP.md`
- `docs/specs/2026-08-25-evidence-preparation-repair-design.md`
- `docs/specs/2026-08-25-context-md-artifact-transaction-design.md`
- `docs/specs/2026-08-25-session-completion-repair-design.md`
- `docs/specs/2026-08-25-session-zero-work-closure-design.md`

완료 조건:

- 네 설계는 각각 완료 조건 6개 이하, 독립 검증 묶음 4개 이하이다.
- 각 완료 조건에 정확한 명령과 기대 관측값이 연결된다.
- 새 문맥의 독립 검수가 A1~A5와 계약 공백/계약 위반을 판정한다.
- `git diff --check`와 `tests/test_architecture_docs.py`가 통과한다.
- GitHub label·dependency를 다시 조회해 목표 구조와 exact 일치한다.
- main과 #33 원본 WIP hash가 보존 기준과 같다.

### 2단계: #2 최종 분리 후보

`9aefa36`에서 다음 경로만 새 `main` 기준 후보로 옮긴다.

```text
README.md
docs/architecture/change-map.md
docs/architecture/runtime-map.md
src/project_brain/audit.py
src/project_brain/cli.py
src/project_brain/foundation.py
src/project_brain/templates/audit/SKILL.md
src/project_brain/templates/ingest/references/ingest-tools.md
src/project_brain/templates/ingest/scripts/finalize_ingest.py
src/project_brain/templates/ingest/scripts/test_finalize_ingest.py
src/project_brain/templates/query/SKILL.md
tests/test_agent_skill_contract.py
tests/test_architecture_docs.py
tests/test_cli.py
tests/test_foundation.py
tests/test_ingest_skill_contract.py
```

완료 확인은 표적 RED/회귀, 전체 엔진 pytest, 설치 runtime unittest, installer 두 번째 설치 무변경,
change-map이 요구하는 소비 데이터 검사, exact-candidate 독립 검수 순이다. merge·main push·#2 종료는
각각 별도 승인 뒤 실행한다.

### 3단계: #4와 #5 최종 분리 후보

순서는 #4 뒤 #5다.

```text
#4
src/project_brain/capabilities.py
tests/test_capabilities.py

#5
docs/architecture/runtime-map.md
src/project_brain/snapshot.py
tests/test_snapshot.py
```

각각 표적 테스트, 전체 엔진 pytest, 설치 runtime unittest, exact-candidate 독립 검수를 통과한 뒤에만
별도 승인으로 병합·push·issue 종료한다.

### 4단계: 설계 복귀와 후속 구현

후보 1(`2db3de1`) 독립 검수는 Critical 0 / Major 6 / RETURN이다. #33은 검수 3/3·설계복귀
1/1에 도달했고 #34도 승인된 설계복귀를 이미 사용했으므로, 아래 순서는 추가 설계·검수 예산을 별도
승인받기 전에는 시작하지 않는다. 이번 1단계는 반송 상태와 dependency를 정확히 기록하는 데서 멈춘다.

한 shared-checkout writer가 다음 순서로 처리한다.

1. #33 evidence preparation 입장 통과
2. #34 session completion, #35 direct reviewed, `context_md` 신규 설계의 읽기 전용 검수
3. zero-work 신규 설계
4. #34와 zero-work가 모두 통과한 뒤 새 session-runtime child issue·장부 생성 → 구현 → #3 closeout
5. #33 통과 뒤 #6용 common verification public preparation child issue·장부 생성
6. #6 child 완료 뒤 #7 → #8 public profile 회귀 child issue를 각각 생성
7. #33 통과 뒤 #9 local capture와 원격 Adapter child issue를 각각 생성
8. #33 통과 뒤 #10의 비-`context_md` derived output validation·실제 builder child 생성
9. `context_md` 설계 통과 뒤 object+artifact transaction 구현 child 생성
10. #10 parent는 8·9의 child와 기존 blocker가 모두 끝난 뒤에만 종료
11. #11 → #12 → #13
12. 기존 dependency에 따라 #14~#19 뒤에만 지식 초안 #20~#23

각 새 구현 child ticket은 설계 확정 → RED → 구현 → 고정 후보 → 별도 문맥 검수 → 필요한 전체 회귀 →
병합 승인 → push 승인 → 원격·GitHub 종료 근거 확인으로 닫는다. 계약 공백이 하나라도 나오면 코드를
고치지 않고 설계로 돌린다.

## 검증 상한

- 기본: 후보 3회, 검수 3회, 설계복귀 1회, 전체 검사 2회
- 사용자 승인 예외: #2·#4·#5는 현재 각각 후보 3/4이며, 분리 최종 후보 4를 한 번만 만들 수 있음
- 이 예외는 상한 기록일 뿐 이번 1단계에서 후보 4를 생성하거나 2단계 코드 작업을 시작할 권한이 아님
- 위 예외는 검수·설계복귀·전체 검사 상한을 늘리지 않는다.
- 같은 ticket에서 추가 상한이 필요하면 자동으로 늘리지 않고 중지해 다시 승인받는다.
