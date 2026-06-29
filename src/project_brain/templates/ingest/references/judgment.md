# 판정 규칙 — 대체 / 보완 / 충돌

변경 이력(4단계)을 박을 때, 새로 들어온 결정이 기존 지식을 **대체**하는지, **보완**하는지,
아니면 **판단 불가(충돌)**인지를 네가 정해야 한다. 코드는 이 판정을 하지 않는다 — `lint`는 신호만 준다.

이 판정이 영구히 에이전트 몫인 이유: 같은 `subject`+`predicate`라도 값이 바뀐 게 "옛 값을 대신한다"는
뜻일 수도, "다른 조건의 별개 값"일 수도 있다. 코드 자동 비교는 멀쩡한 사실을 잘못 닫는다.

## 대체 (supersede)

같은 `subject`+`predicate`인데 값이 바뀌었고, 새 값이 옛 값을 **대신한다**고 판단되면:

1. 옛 객체 `status = "superseded"`.
2. 새 객체를 만들고 `supersedes`(매핑이면 `supersedes_mapping_ids`)로 옛 것을 가리킨다.
3. 변경 사건을 `EventLedgerRecord`로 만들어 "왜·언제 바뀌었나"에 답한다.

예: 재참여 가능 조건 값이 A → B로 변경. 옛 fact superseded, 새 fact + ledger.

주의: `lint` 8d는 "다른 매핑이 supersede했는데 옛 매핑이 아직 reviewed로 남아있으면" 문제로 잡는다.
대체 처리하면 옛 객체 status를 반드시 `superseded`로 내려야 한다.

## 보완 (추가)

기존 동작에 **더해지는** 것은 대체가 아니다. 새 `DecisionRecord`를 만들고 기존 매핑의
`decision_record_ids`에 연결한다(기존 매핑·사실은 그대로 둔다).

예: "레이스 중 순위영역 터치 시 이동 기능 추가" — 기존 레이스 동작을 대신하는 게 아니라 더한 것.
supersede 체인을 만들지 마라.

주의: `lint` 8c는 "결정이 reviewed 매핑에 영향을 주는데 그 매핑이 결정을 반영(decision_record_ids에
포함)하지 않았으면" review-needed 신호를 띄운다. 보완 결정을 만들었으면 영향 매핑의
`decision_record_ids`에 그 결정 id를 넣어 반영해야 신호가 꺼진다.

## 충돌 (판단 불가)

어느 게 맞는지 확신이 안 서면 **둘 다 두고** 판정을 보류한다. `lint`가 충돌/needs_clarification 신호를
띄우게 두고, 사용자에게 확인받은 뒤 대체 또는 보완으로 정리한다.

`lint`의 충돌 검사: 같은 `subject`+`predicate`에 `valid_until` 없는 reviewed fact가 값이 갈리며 2개
이상이면 conflict로 보고한다. 즉 둘 다 reviewed·열린 상태로 두면 신호가 뜬다 — 이게 의도된 동작이다.

## spec_reflected — drift 추적

QA·개선 결정이 Jira엔 있지만 **기획서에 반영 안 됐으면** `DecisionRecord.spec_reflected = "no"`로
표시한다. 이게 기획서-구현 drift 신호다. 반영됐으면 `yes`, 모르면 `unknown`, 해당 없으면
`not_applicable`. 추측으로 `yes`를 박지 마라 — 기획서 원문에서 확인되지 않으면 `unknown`이다.
