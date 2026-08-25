# Brain 티켓 정리 v2 진행 기록

- 범위: #2~#13 후보 분리, #33~#39 설계 복귀, `context_md`와 session zero-work 계약 분리
- 기준점: `b35d351ee77093392ca170f799d0edc1a8414070`
- 조율자: 현재 Codex 세션 한 곳
- 실행 방식: Project Brain 저장소와 GitHub Issues만 사용. agent-team 스킬·엔진·Run은 사용하지 않음
- 과거 기록: `codex/brain-ticket-reconcile-20260825:.goal/brain-ticket-reconcile/progress.md`
- 티켓당 사람 개입 없는 실행 시간: 90분
- 진행 판정 간격: 45분
- 기본 후보: 3회
- 기본 검수: 3회
- 기본 설계복귀: 1회
- 기본 전체검사: 2회
- 승인된 예외: #2·#4·#5는 각각 현재 3/4이며 최종 후보 4를 한 번만 추가할 수 있음. 후보 4는 아직 생성하지 않음
- 2026-08-25 추가 승인: #33 설계복귀 상한 1→2·검수 상한 3→4, #34 설계복귀 상한 1→2
- #38·#39는 기존 설계복귀 1/1 안에서 후보 2를 만들며 상한을 늘리지 않음
- 권한 경계: 이 기록은 상한만 늘린다. 이번 1단계에서 #2·#4·#5 코드 후보를 만들 권한은 없음
- 정리 후보 1: `2db3de1bf430c4c663d087dc52ef033dd3923a31`
- 후보 1 독립 검수: Critical 0 / Major 6 / RETURN
- 정리 후보 2: `6c4a411c072f5d0546709779bdc0a8645e667d6a`
- 후보 2 구조 검수: Critical 0 / Major 0 / Minor 0 / PASS
- 공통 현재 시각: 2026-08-25 Asia/Seoul

## 정본·티켓 구조 정리

- 단계: 1단계 완료
- 후보: 2 / 3
- 검수: 2 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: #38·#39 생성, label·dependency·본문 exact 역조회, 후보 2 구조 검수 PASS
- 마지막 갱신: 2026-08-25
- 다음 행동: 설계복귀 후보 2를 exact commit으로 고정하고 한 번의 독립 검수를 수행한다.

## #2 query·audit 읽기 전용 WIP 안정화

- 단계: 준비
- 후보: 3 / 4
- 검수: 2 / 3
- 설계복귀: 0 / 1
- 전체검사: 1 / 2
- 마지막으로 닫힌 완료 조건: 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: `main@b35d351` 위에 `9aefa36`의 정확한 파일 집합만 옮겨 최종 후보 4를 만든다.

## #4 19종 capability registry 확장 단계

- 단계: 준비
- 후보: 3 / 4
- 검수: 2 / 3
- 설계복귀: 0 / 1
- 전체검사: 1 / 2
- 마지막으로 닫힌 완료 조건: 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: #2 종료 뒤 `698dc3e`의 registry와 단위 테스트만 최종 후보 4로 고정한다.

## #5 snapshot v1·v2의 19종 대상을 동결

- 단계: 준비
- 후보: 3 / 4
- 검수: 2 / 3
- 설계복귀: 0 / 1
- 전체검사: 1 / 2
- 마지막으로 닫힌 완료 조건: 없음
- 마지막 갱신: 2026-08-25
- 다음 행동: #4 종료 뒤 `160050c`의 snapshot 동결 범위만 최종 후보 4로 고정한다.

## #33 evidence preparation 설계 admission

- 단계: 설계복귀 후보 2 고정
- 후보: 2 / 3
- 검수: 3 / 4
- 설계복귀: 2 / 2
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: EvidencePlan source union·mixed plan·raw snapshot·`generated_by`와 #38 전용 handoff 보강
- 마지막 갱신: 2026-08-25
- 다음 행동: 네 spec의 exact candidate SHA를 기록하고 #33 최종 독립 검수 4/4를 한 번 수행한다. Major가 남으면 추가 연장 없이 중지한다.

## #34 session completion 설계 admission

- 단계: 설계복귀 후보 2 고정
- 후보: 2 / 3
- 검수: 1 / 3
- 설계복귀: 2 / 2
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: tagged normal 계약, SessionExecutionState, durable run root와 구현 test/design admission 분리
- 마지막 갱신: 2026-08-25
- 다음 행동: #39와 같은 fixed SHA를 독립 검수하고 결과를 구현 test와 별도로 기록한다.

### 초기 입장 판정

- 결과: RETURN
- 이유: 완료 조건 7개로 A4 상한을 넘고, 조건별 정확한 검증 명령·기대 관측 연결이 없어 A3도 닫히지 않음
- 재개 조건: #33을 blocker로 추가하고 core와 zero-work를 각각 완료 조건 6개 이하로 분리

## #38 `context_md` object+artifact lifecycle 설계

- 단계: 설계복귀 후보 2 고정
- 후보: 2 / 3
- 검수: 1 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: #33 handoff, parent/mount, atomic leaf, pre-commit rollback과 committed receipt/report tail 보강
- 마지막 갱신: 2026-08-25
- 다음 행동: #33과 같은 fixed SHA를 독립 검수한다.

## #39 session zero-work·unresolved closure 설계

- 단계: 설계복귀 후보 2 고정
- 후보: 2 / 3
- 검수: 1 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: zero/deferred bindings, public variant seam, deferred sole writer와 immutable zero retry chain 보강
- 마지막 갱신: 2026-08-25
- 다음 행동: #34와 같은 fixed SHA를 독립 검수한다.

## 설계복귀 후보 2 독립 검수 입력

- 파일: `docs/specs/2026-08-25-evidence-preparation-repair-design.md`
- 파일: `docs/specs/2026-08-25-context-md-artifact-transaction-design.md`
- 파일: `docs/specs/2026-08-25-session-completion-repair-design.md`
- 파일: `docs/specs/2026-08-25-session-zero-work-closure-design.md`
- 설계복귀 후보 2 SHA: d9d91391baece86f87ef3ea5612da76697e763ff
- 검수 횟수: 네 파일을 한 exact candidate로 한 번만 검수하며 #33은 4/4, #34·#38·#39는 각각 2/3으로 센다.
- 통과: A1 high, A2~A5 PASS, Critical 0, Major 0
- 통과 뒤: #33·#34·#38·#39를 설계확정으로 바꾸고, E1~E15·C1~C6·N1~N4·Z1~Z4 각각의 GitHub child
  issue와 progress block 생성안을 사용자에게 먼저 보여준다.
- 중지: 어느 issue든 Major 또는 contract gap이 하나라도 남으면 모든 설계복귀 상한이 끝난 상태이므로
  추가 수정·재검수를 시작하지 않고 사용자에게 반환한다.

## 보존 확인

- main WIP 상태 목록 SHA-256: `7be3dcf9c6a119de8c273c7ea804962f477d9921f809dd8161eb3ad75a6a04b9`
- #33 원본 WIP diff SHA-256: `8d9385dab45cd9ea159353354a18fbd1316b79ea6116bc845ecaaac339936b32`
- 후보 1 고정 뒤 재확인: 두 hash 모두 기준값과 exact 일치
- 후보 2 commit 전·GitHub 변경 뒤 재확인: 두 hash 모두 기준값과 exact 일치
- 설계복귀 후보 2 commit 전 재확인: main status는 `git status --short --untracked-files=all`, #33은
  `git diff` 기준으로 두 hash 모두 exact 일치

## GitHub 적용 확인

- #3 blocked by `[34,39]`
- #10 blocked by `[4,6,33,38]`
- #33 blocked by `[]`
- #34 blocked by `[33]`
- #38 blocked by `[33]`
- #39 blocked by `[34]`
- #3·#10·#33·#34·#38·#39: 모두 OPEN, labels exact `enhancement,needs-triage`
- Wayfinder 다섯 label이 붙은 issue: 모두 0개
- local main·origin/main·실제 원격 main: `b35d351ee77093392ca170f799d0edc1a8414070`
