---
status: accepted
decision_date: 2026-08-14
implementation: not_implemented
contract_status: integrated_spec_published
superseded_by: null
---

# 후보 안에 검증 결과를 보존한다

후보 검증을 위해 `ObjectVerificationRecord`나 `GlossaryQualificationRecord` 같은 객체 종류를 새로 만들지 않는다. 모든 승격 가능한 후보는 기존 `candidate` 영역 하나에 공통 검사와 종류별 검사의 현재 결과를 함께 보존한다. 공통 검사는 대상 내용·근거·현재 유효성·미해결 질문을 다루고, 어휘에는 실제 프로젝트 이름·독립 개념·적절한 크기·대표 이름·중복·소유 도메인 검사를, 코드 위치와 의미 매핑 등에는 각 종류에 맞는 검사를 추가한다.

검증 정보는 검증 대상 내용과 근거, 적용한 규칙, 검증 실행에 묶여야 한다. 하나라도 바뀌면 승격 준비 상태를 다시 계산하고, 모든 필수 검사를 통과했으며 미해결 질문이 없을 때만 승격 준비 후보로 본다. 별도 승격 준비 명부는 만들지 않고 현재 후보의 검증 정보에서 목록을 계산한다.

수동 승격·명시적인 즉시 승격·`promote-auto`는 모두 같은 최신 검증 준비 상태를 소비한다. `promote-auto` 명령은 기존 자동화 호환을 위해 유지하지만 reviewed `DomainMapping`에 연결됐다는 사실만 검증으로 대신하지 않으며, 최신 `candidate.verification`을 통과한 후보만 처리한다. 검증이 없는 기존 후보는 자동으로 승격하지 않고 후보로 유지한다.

승격할 때는 `candidate` 영역을 제거하고 검증 요약과 결속 정보를 기존 `ReviewRecord`에 남긴다. `ReviewRecord`는 검증 진행 상태가 아니라 실제로 `reviewed`로 올린 최종 승인 기록이라는 기존 역할을 유지한다. 대규모 검증은 한 실행에서 관련 후보 여러 개를 함께 검사할 수 있지만 결과는 후보별로 남겨 한 항목의 변경이 다른 항목까지 낡게 만들지 않는다.

기존 후보에 검증 정보가 없으면 검증을 통과했다고 추정하지 않고 미검증 후보로 다룬다. 새 후보와 의미 있는 변경부터 이 계약을 적용하고, 기존 후보는 조회·수정·승격하려는 시점에 검증 정보를 보강한다. 명백한 비어휘는 정상 제외하며, 문맥 때문에 반복 오분류될 위험이 있는 경우에만 별도 `GlossaryClassificationRecord`를 사용한다.

근거가 명확해 후보를 거치지 않고 곧바로 `reviewed`로 적재하는 객체도 같은 공통 검사와 종류별 검사를 우회하지 않는다. 이 경로에서는 후보를 억지로 만들지 않고 검증 결과를 해당 ingest 실행과 transaction 증거에 결속한다. 기존 `reviewed` 객체의 의미나 근거를 바꾸는 경우에도 변경된 내용으로 다시 검증하고 같은 mutation에서 검수 증거를 갱신한다.

## 구현 메모 (2026-08-25)

통합 후보 `75e97fa`는 common envelope, 현재 상태 재계산, candidate promotion의 ReviewRecord 결속과
일부 종류별 profile을 구현했다. 다만 main에 반영되지 않았고 공개 ingest의 준비 경계,
GlossaryTerm·DomainMapping profile, direct reviewed create/update 이력은 아직 닫히지 않았다. 그래서
frontmatter의 `implementation: not_implemented`를 유지한다. 정확한 부분 구현과 보강 순서는
[재정리 보고서](../reports/2026-08-25-issues-2-13-reconciliation.md)와
[evidence preparation 보강 설계](../specs/2026-08-25-evidence-preparation-repair-design.md)를 본다.
