---
status: accepted
decision_date: 2026-08-14
implementation: not_implemented
contract_status: integrated_spec_published
superseded_by: null
---

# 문맥 의존 어휘 판정을 정식 비색인 객체로 재사용한다

공통 규칙만으로 반복 판정하기 어려운 표현을 새 `GlossaryTerm`으로 만들지 않기로 확정하면 정식 비색인 객체 `GlossaryClassificationRecord`로 남긴다. 이 객체들의 모음을 어휘 판정 명부라고 부른다. 명백한 함수·필드·enum 같은 일반 코드 토큰은 공통 규칙으로 제외하고 개별 객체를 만들지 않으며, 지식 초안이나 `rejected GlossaryTerm`을 탈락 판정 저장소로 사용하지 않는다.

명부 항목은 `적용 도메인 + 정규화한 표현 + 그 자리에서 맡은 역할과 의미`를 구분하고, 현재 판정은 새 어휘 제외 또는 기존 대표 어휘 연결을 나타낸다. 한 문맥에서 탈락한 철자가 다른 문맥의 다른 개념까지 자동으로 막지는 않지만, 다른 문맥이라는 이유만으로 허용하지도 않는다. 예를 들어 `IDLE`이 enum 값 역할로 쓰이는 동안에는 어느 도메인에서도 공통 규칙으로 제외하되 문자열 자체를 프로젝트 전체 금지어로 만들지 않는다. 전혀 다른 곳에서 실제 화면명이나 기능명으로 쓰이면 그 양성 근거를 다시 검증한다.

같은 문맥·표현·역할에는 현재 유효한 판정 객체 하나만 두고 과거 내용은 Git과 transaction 이력으로 확인한다. 이전 판정과 맞지 않는 새로운 1차 근거가 생기면 새 어휘를 조용히 만들거나 과거 판정으로 자동 차단하지 않고 재판정한다. 새 어휘가 맞으면 기존 판정 객체 제거와 검증 정보를 갖춘 `GlossaryTerm` 생성을 같은 mutation에서 처리하고, 끝내 모호한 경우에만 사용자에게 확인한다.

기존 어휘의 다른 이름으로 판정한 경우에는 `GlossaryClassificationRecord`만 만들어 끝내지 않는다. 실제로 이름처럼 쓰인 근거가 있으면 대상 `GlossaryTerm.aliases`와 그 변경에 대한 종류별 재검증 결과를 같은 mutation에서 갱신해야 일반 query가 해당 표현을 회수할 수 있다. 이미 `reviewed`인 대상이라면 갱신된 검수 증거도 `ReviewRecord`에 함께 남긴다. 코드 식별자라는 이유만으로 별칭을 추가하지 않는다.

`brain-ingest`·`session-ingest` 등 적재 절차는 어휘를 추출하고 분류하기 전에 명부를 읽어 잘못된 제안을 피한다. 엔진은 모든 `GlossaryTerm` 생성·수정 경로가 합류하는 쓰기 관문에서 명부를 다시 대조하고 해소되지 않은 충돌이 있으면 저장하지 않는다. 객체 JSON을 손으로 고쳐 쓰기 관문을 건너뛴 경우에는 같은 검사를 `audit`에서 다시 수행한다.

명부 조회는 어휘 자격 검증을 대신하지 않는다. 새 표현은 먼저 실제 이름 사용 근거·독립 개념 여부·정의와 범위·대표 이름·중복·소유 도메인을 독립 검증하고 그 결과를 기존 판정과 대조한다. 이 관문은 새 오분류와 재발을 막는 계약이며 이미 적재된 잘못된 어휘를 자동으로 삭제하거나 바꾸지 않는다.

`GlossaryClassificationRecord`는 다른 정식 Brain 객체처럼 schema·ID·참조·snapshot·audit·mutation 계약을 사용하지만 일반 검색과 기본 그래프에서는 숨긴다. 별도 판정 파일 저장소나 초기화 manifest를 만들지 않는다. 객체 파일 손상은 다른 정식 Brain 객체 손상과 마찬가지로 코퍼스 로드 실패로 처리한다.

도입 시에는 새 어휘와 어휘의 의미 표면이 바뀌는 쓰기부터 관문을 적용한다. 기존 `term`·`synonyms`·`aliases`는 읽기 전용으로 전수 재감사하고 승인된 migration으로 정리한 뒤에만 전체 기존 코퍼스 불일치를 차단 오류로 전환한다. 기존 오분류를 판정 명부에 먼저 넣어 어휘와 무관한 갱신까지 막지 않는다.

기존 `GlossaryTerm`이 새 기준에서 어휘가 아닌 것으로 판정되면 `rejected` 객체로 남기지 않고 승인된 migration으로 제거한다. 필요한 의미는 `DomainMapping`·`CodeLocator` 등 알맞은 객체에 보존하고, 원문과 `EvidenceRef`는 유지하며, 문맥 때문에 재발할 위험이 있는 경우에만 `GlossaryClassificationRecord`를 만든다. 이전 객체와 제거 이력은 Git·snapshot·migration 기록으로 확인한다.
