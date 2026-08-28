---
status: accepted
decision_date: 2026-08-14
implementation: not_implemented
contract_status: mvp_scope_revalidated_2026-08-28
superseded_by: null
---

# 모든 적재 경로가 하나의 어휘 판정 규칙을 사용한다

어휘의 포함·제외·대표어·다른 이름·검수 상태를 판단하는 규칙은 지식 초안에 속하지 않고, 완료 소급 적재와 진행 중 적재를 포함한 모든 Brain 적재 경로가 함께 사용한다. 지식 초안은 개발 중 발견한 표현과 근거를 보존해 정식화 단계에 넘길 뿐이며, 그 표현을 `GlossaryTerm`으로 확정하지 않는다. 이렇게 해야 지식 초안을 거치지 않는 적재에서도 같은 어휘 기준이 적용되고, 입력 경로에 따라 어휘 품질이 달라지는 일을 막을 수 있다.

첫 적용 범위는 하나의 정본 기준과 일반 ingest·session-ingest·지식 초안 절차의 사용, 그리고 그 연결을 확인하는 계약 테스트까지다. 문자열 길이처럼 결정론적으로 판정할 수 있는 조건은 엔진이 강제하되, 실제 프로젝트 이름인지와 독립 개념인지 같은 의미 판단을 위해 모든 후보의 공통 verification 엔진이나 기존 BB2 어휘 migration을 먼저 완성하도록 요구하지 않는다.

운영 정본은 엔진의 `templates/ingest/references/glossary-criteria.md` 한 파일로 두고 소비 프로젝트에는 `<project>-brain-ingest/references/glossary-criteria.md`로 한 번만 설치한다. ingest는 `GlossaryTerm` 생성·변경 때, session-ingest는 현재 또는 과거 세션에서 어휘 후보를 추출할 때, brain-draft는 어휘 관찰을 잠정 분류할 때, audit은 기존 어휘 품질을 감사할 때 이 reference를 읽는다. query는 읽지 않으며 어느 스킬도 기준이나 template을 자기 본문에 복제하지 않는다. installer 계약 테스트는 네 소비 경로의 조건부 pointer가 같은 파일을 가리키는지 확인한다.

이 reference는 실제 프로젝트 이름·독립 개념·명명 근거·코드 토큰 제외, 비어휘 의미의 DomainMapping·CodeLocator·무객체 라우팅, 대표어·동의어·별칭, 어휘 후보 최소 문턱, 사용자 판단이 필요한 모호성과 구체적인 정답·반례를 다룬다. `GlossaryClassificationRecord`, 공통 verification hash, BB2 migration 실행 절차는 이 문서의 범위가 아니다.
