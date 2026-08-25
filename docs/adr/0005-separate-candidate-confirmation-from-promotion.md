---
status: accepted
decision_date: 2026-08-14
implementation: not_implemented
contract_status: integrated_spec_published
superseded_by: null
---

# 후보 확인과 승격 승인을 분리한다

질의에서 후보 내용을 사용자가 `맞다`고 확인한 답은 모호성을 푸는 근거이지 Brain 쓰기 승인이 아니다. 사용자가 `바로 승격해줘`라고 명시하면 종류별 검증을 거쳐 통과한 대상을 같은 요청에서 승격할 수 있고, `승격 준비 목록에 넣어둬`라고 명시하면 나중에 승격할 수 있도록 검증 결과를 보존하되 객체는 후보 상태로 유지한다. 단순 확인만 받았으면 현재 답변에만 반영하고 코퍼스는 바꾸지 않는다.

query는 답변이 후보의 의미에 의존하고 사람의 의미 판단이 필요할 때만 해당 후보를 확인 대상으로 제시한다. 코드 위치·근거 객체·색인·projection·현재 뷰처럼 전용 적재나 갱신 절차가 검증할 대상까지 사용자 확인으로 확대하지 않는다. 정확한 kind별 허용·금지 표는 통합 spec에서 현재 19종의 생성·후보 허용·질의 확인·승격·전용 갱신 능력을 함께 정의한다.

## 구현 메모 (2026-08-25)

통합 후보 `75e97fa`에는 query 단순 확인의 no-write 경계와 일부 candidate promotion 관문이 있다.
하지만 main에 반영되지 않았고 모든 public preparation·즉시 reviewed·종류별 profile 경계가 끝난
상태가 아니므로 frontmatter의 `implementation: not_implemented`를 유지한다. 현재 범위와 남은
공백은 [재정리 보고서](../reports/2026-08-25-issues-2-13-reconciliation.md)를 본다.
