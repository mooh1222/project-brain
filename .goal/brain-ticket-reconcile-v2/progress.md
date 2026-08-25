# Brain 티켓 정리 v2 진행 기록

- 범위: #2~#13 후보 분리, #33~#37 설계 복귀, `context_md`와 session zero-work 계약 분리
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
- 권한 경계: 이 기록은 상한만 늘린다. 이번 1단계에서 #2·#4·#5 코드 후보를 만들 권한은 없음
- 정리 후보 1: `2db3de1bf430c4c663d087dc52ef033dd3923a31`
- 후보 1 독립 검수: Critical 0 / Major 6 / RETURN
- 공통 현재 시각: 2026-08-25 Asia/Seoul

## 정본·티켓 구조 정리

- 단계: 검수
- 후보: 2 / 3
- 검수: 1 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 후보 1 독립 검수 RETURN과 기존 parent→새 child 장부 경계 반영
- 마지막 갱신: 2026-08-25
- 다음 행동: 후보 2에서 실행안의 parent/child 경계만 확인하고 기술 spec은 반송 상태로 보존한다.

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

- 단계: 검수
- 후보: 1 / 3
- 검수: 3 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: Major 8건 소유권 분리, 후보 1 검수 Critical 0 / Major 2 / RETURN
- 마지막 갱신: 2026-08-25
- 다음 행동: 중지. EvidencePlan source exact schema와 전용 `context_md` coordinator 계약을 고칠 추가 설계·검수 예산을 사용자에게 별도 승인받는다.

## #34 session completion 설계 admission

- 단계: 검수
- 후보: 1 / 3
- 검수: 1 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: normal/zero 분리, 후보 1 검수 A2/A4/A5 PASS·A3 RETURN
- 마지막 갱신: 2026-08-25
- 다음 행동: GitHub를 `needs-triage`로 교정한 뒤 중지. 추가 설계복귀 승인 전 완료 조건 5의 admission/test 관측 혼합을 고치지 않는다.

### 입장 판정

- 결과: RETURN
- 이유: 완료 조건 7개로 A4 상한을 넘고, 조건별 정확한 검증 명령·기대 관측 연결이 없어 A3도 닫히지 않음
- 재개 조건: #33을 blocker로 추가하고 core와 zero-work를 각각 완료 조건 6개 이하로 분리

## 신규 `context_md` object+artifact lifecycle 설계

- 단계: 검수
- 후보: 1 / 3
- 검수: 1 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 대상 분리와 상태표 고정, 후보 1 검수 Critical 0 / Major 2 / RETURN
- 마지막 갱신: 2026-08-25
- 다음 행동: `needs-triage` 신규 issue를 만든 뒤 #33 계약·추가 설계 예산을 기다린다.

## 신규 session zero-work·unresolved closure 설계

- 단계: 검수
- 후보: 1 / 3
- 검수: 1 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: normal/zero schema 분리, 후보 1 검수 Critical 0 / Major 2 / RETURN
- 마지막 갱신: 2026-08-25
- 다음 행동: `needs-triage` 신규 issue를 만든 뒤 #34 계약·추가 설계 예산을 기다린다.

## 보존 확인

- main WIP 상태 목록 SHA-256: `7be3dcf9c6a119de8c273c7ea804962f477d9921f809dd8161eb3ad75a6a04b9`
- #33 원본 WIP diff SHA-256: `8d9385dab45cd9ea159353354a18fbd1316b79ea6116bc845ecaaac339936b32`
- 후보 1 고정 뒤 재확인: 두 hash 모두 기준값과 exact 일치
- 다음 확인: 후보 2 commit 전, GitHub 변경 뒤
