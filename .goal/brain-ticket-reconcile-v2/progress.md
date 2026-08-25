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
- 공통 현재 시각: 2026-08-25 Asia/Seoul

## 정본·티켓 구조 정리

- 단계: 검수
- 후보: 1 / 3
- 검수: 0 / 3
- 설계복귀: 0 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: 문서 7개 exact 범위 고정, architecture docs 15 passed, 원본 WIP hash 보존
- 마지막 갱신: 2026-08-25
- 다음 행동: 문서-only commit으로 후보 1 SHA를 고정한 뒤 독립 검수에 넘긴다.

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
- 검수: 2 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: Major 8건을 core와 `context_md`로 분배하고 완료 조건 6개·검증 묶음 4개로 고정
- 마지막 갱신: 2026-08-25
- 다음 행동: 고정 SHA에서 마지막 검수 3/3으로 A1~A5와 Critical/Major를 판정한다.

## #34 session completion 설계 admission

- 단계: 검수
- 후보: 1 / 3
- 검수: 0 / 3
- 설계복귀: 1 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: normal session을 zero-work·unresolved와 분리하고 완료 조건 5개·검증 묶음 4개로 고정
- 마지막 갱신: 2026-08-25
- 다음 행동: 고정 SHA 독립 검수 뒤 `ready-for-agent`를 제거하고 본문·dependency를 교정한다.

### 입장 판정

- 결과: RETURN
- 이유: 완료 조건 7개로 A4 상한을 넘고, 조건별 정확한 검증 명령·기대 관측 연결이 없어 A3도 닫히지 않음
- 재개 조건: #33을 blocker로 추가하고 core와 zero-work를 각각 완료 조건 6개 이하로 분리

## 신규 `context_md` object+artifact lifecycle 설계

- 단계: 검수
- 후보: 1 / 3
- 검수: 0 / 3
- 설계복귀: 0 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: root `CONTEXT.md`·지식 초안 제외와 두 root transaction·artifact 상태표 고정
- 마지막 갱신: 2026-08-25
- 다음 행동: 고정 SHA 독립 검수 뒤 `needs-triage` 신규 issue를 만든다.

## 신규 session zero-work·unresolved closure 설계

- 단계: 검수
- 후보: 1 / 3
- 검수: 0 / 3
- 설계복귀: 0 / 1
- 전체검사: 0 / 2
- 마지막으로 닫힌 완료 조건: normal report와 zero/deferred variant를 분리하고 완료 조건 5개·검증 묶음 4개로 고정
- 마지막 갱신: 2026-08-25
- 다음 행동: 고정 SHA 독립 검수 뒤 `needs-triage` 신규 issue를 만든다.

## 보존 확인

- main WIP 상태 목록 SHA-256: `7be3dcf9c6a119de8c273c7ea804962f477d9921f809dd8161eb3ad75a6a04b9`
- #33 원본 WIP diff SHA-256: `8d9385dab45cd9ea159353354a18fbd1316b79ea6116bc845ecaaac339936b32`
- 다음 확인: local 후보 고정 전, GitHub 변경 뒤, commit 전
