# 이 스킬이 맞는 상황인가 (적재 시나리오 경계)

Brain 적재에는 세 시나리오가 있고, 이 스킬은 그중 하나만 다룬다. 헷갈리면 멈추고 사용자에게
어느 시나리오인지 확인하라.

| 시나리오 | 뼈대 | 이 스킬이 다루나 |
|---|---|---|
| (가) 진행 중 개발 — 세션 도중 적재 | 기획서로 저장 후보 선점 → 코드 생기며 연결 | **아니오 — `{{PROJECT}}-brain-session-ingest`** |
| (나) 완료 스펙 소급 적재 | **코드** | **예 — 이 스킬** |
| (다) 과거 세션 히스토리에서 추출 | 끝난 세션 로그 마이닝 | **아니오 — `{{PROJECT}}-brain-session-ingest`** |

## (나) 완료 소급 적재의 조건

이 스킬을 쓰려면 그 기능이 **소급 적재 대상일 만큼 완료**되어 있어야 한다. 완료 여부(`feature_done`)는
사용자 선언, QA/release 맥락, 이슈 상태로 판단한다. Jira/Slack 데이터 유무가 기능 완료 조건은 아니다.

- 코드가 {{DEFAULT_BRANCH}}에 들어가 있다(앵커 잡을 `commit_sha`가 고정된다).
- 1층 현재 소스가 한자리에 있다 — 현행 기획서 원문, {{DEFAULT_BRANCH}} 코드, 서버 위키.
- 이미 일어난 변경(QA 버그수정·개선)은 "지금 진행 중"이 아니라 **완결된 이력**으로 존재할 수 있다.
  이 이력은 `history_coverage`를 높일 때만 필수다.

예: 베타 QA까지 끝나 리얼 QA 중인 이벤트. 1층 현재 소스로 `current_ingest_done`을 만들고, Jira/Slack/PR/commit
이력까지 확인하면 `history_coverage=complete`로 닫을 수 있다.

## 기능 완료 / 현재 적재 / 이력 커버리지 구분

이 스킬을 쓰는 중에도 적재 완성도는 단계가 갈린다.

| 축 | 확인한 것 | 답할 수 있는 질문 |
|---|---|---|
| `feature_done` | 기능이 소급 적재 대상일 만큼 완료됐다는 외부 상태 | 적재를 시작해도 되는가 |
| `current_ingest_done` | 현재 {{DEFAULT_BRANCH}} 코드 + 현행 기획서 + 서버 위키 | 뭐야 / 어디 / 지금 |
| `history_coverage` | Jira/Slack/PR/commit 변경 이력 확인 범위 | 왜 / 그때 |

이력 확인 전이면 `DomainMapping.caveats`나 ingest memo에 `history_coverage=unsearched` 또는
`history_coverage=partial`을 남긴다. `history_coverage=complete` 없이 이력 질문을 답하지 마라.

## (가)와의 구분 — "코드가 없다"가 아니다

(가) 진행 중 개발에서도 코드는 생기고 변경된다. (가)의 핵심은 "개발 시작에 기획서 분석으로 저장
후보를 미리 잡아두고, 작업하며 코드가 생기면 그 후보에 연결한다"는 시간차 흐름이다. 코드가 아직
**확정 안 됐고 계속 바뀌는 중**이면 (가)다 — 이 스킬을 쓰지 말고 사용자에게 알려라.

(가)와 (다)는 "세션에 어떤 코드를 봤는지 흔적이 남는다"는 점에서 이어진다. `{{PROJECT}}-brain-session-ingest`가 다룬다.

## 범위 밖이면

사용자 요청이 (가)나 (다)로 보이면 `{{PROJECT}}-brain-session-ingest` 스킬로 전환하라. 억지로
완료 소급 적재 절차를 진행하지 마라 — 코드가 확정 안 된 상태에서 {{DEFAULT_BRANCH}} 앵커를 박으면 곧 깨진다.
