---
status: accepted
decision_date: 2026-09-01
implementation: implemented_issue_61
contract_status: implemented
superseded_by: null
---

# 일반 회수와 결정론 조회 축을 분리한다

일반 의미·코드 위치·개발 착수 질문은 내용 기반 `search`로 관련 객체를 회수하고, 에이전트가 핵심 객체를 `show`로 읽어 답을 조합한다. `query`는 변경 이유·현재 상태·과거 시점·근거 사슬의 조회 축만 결정론적으로 계산한다. 검수 상태는 관련성을 고르는 기준이 아니라 검색 결과의 신뢰 정보이며 candidate를 사용한 단순 확인은 승격이나 저장 승인이 아니다.

기존 intent별 객체 종류 배선은 검색된 객체를 답에서 누락할 수 있었고, 누락 때마다 spillover를 더하면 같은 문제가 반복됐다. 일반 회수를 한 경로로 모으면 ranking과 채널 계약은 `search`가, 객체 본문과 mapping stale은 `show`가, 시간·근거 계산은 `query`가 각각 소유한다. 그 결과 bare 자유질의는 explicit `search`와 같은 fresh-index 실패 계약을 따르고, `query`는 index·embedder·recall·Insight·mapping stale·현재 HEAD에 의존하지 않는다.
