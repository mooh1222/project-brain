# session zero-work·미해결 후보 종료 설계 — 폐기 결정

- 최초 작성일: 2026-08-25
- 결정일: 2026-08-26
- 상태: 구현하지 않음
- 종료 대상: GitHub #39
- 미래 논의: GitHub #40

## 결정

세션에서 저장할 지식이 정말 없었는지는 Brain 엔진이 증명할 대상이 아니다. 현재 과거 세션 적재는
사람이나 에이전트가 세션을 읽고 필요한 지식을 고른 뒤 수동으로 적재하는 흐름이며, 여러 세션을 한 번에
자동 추출·적재하는 공개 기능은 없다. Brain 전체 검사·평가·그래프·색인 상태는 세션에서 중요한 지식을
놓쳤는지 증명하지 못하므로 zero-work 전용 finalization·attestation·receipt·report·head·retry를 만들지
않는다.

2026-08-26 BB2에서 기존 `session list`를 읽기 전용으로 실행했을 때 현재 보이는 세션은 84개였고, 기존
완료 표시 3개와 겹치는 세션은 없었다. 실제 일괄 적재가 생기기 전에 별도 zero-work 실행 계층을 만드는
것보다 실제 세션 탐색 범위와 중복 판정을 먼저 확인하는 편이 맞다.

## 남는 규칙

- item이 한 개 이상이고 미해결 후보가 없는 실제 적재만 #34 normal session completion이 다룬다.
- 미해결 후보가 하나라도 있으면 적재·receipt·완료 표시를 시작하지 않는다. 판단을 마친 뒤 normal 적재를
  처음부터 다시 준비한다. 이를 위한 deferred report나 재개 체인은 만들지 않는다.
- 과거 세션을 확인했지만 건질 내용이 없으면 현재의 수동 `session mark-processed --note`를 필요에 따라
  사용할 수 있다. 이 표시는 지식 부재의 증명이 아니다.
- 미래에 실제 일괄 적재 기능을 논의할 때는 #40에서 실제 BB2 `--dry-run`, 처리·건너뜀 이유, 성공한
  세션의 중복 방지를 함께 결정한다.

## 폐기한 범위

- `zero_work`, `zero_objects`, `unresolved_only`, `partial_unresolved` 실행 variant
- zero-work 전용 baseline과 전체 검사·평가·그래프·색인 계약
- attestation, immutable execution·receipt·completion report, mutable head와 crash recovery
- 미해결 후보 전용 manifest·deferred report·resume
- #34와 #3의 구현 선행 조건으로서의 #39

과거 후보의 상세 설계와 독립 검수 기록은 Git 이력과
`.goal/brain-ticket-reconcile-v2/progress.md`에 보존한다. 이 파일의 과거 revision을 현재 구현 입력으로
사용하지 않는다.
