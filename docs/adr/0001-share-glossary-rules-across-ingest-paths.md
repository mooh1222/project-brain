---
status: accepted
decision_date: 2026-08-14
implementation: not_implemented
contract_status: integrated_spec_published
superseded_by: null
---

# 모든 적재 경로가 하나의 어휘 판정 규칙을 사용한다

어휘의 포함·제외·대표어·다른 이름·검수 상태를 판단하는 규칙은 지식 초안에 속하지 않고, 완료 소급 적재와 진행 중 적재를 포함한 모든 Brain 적재 경로가 함께 사용한다. 지식 초안은 개발 중 발견한 표현과 근거를 보존해 정식화 단계에 넘길 뿐이며, 그 표현을 `GlossaryTerm`으로 확정하지 않는다. 이렇게 해야 지식 초안을 거치지 않는 적재에서도 같은 어휘 기준이 적용되고, 입력 경로에 따라 어휘 품질이 달라지는 일을 막을 수 있다.
