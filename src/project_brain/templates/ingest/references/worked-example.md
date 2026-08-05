# 작은 전체 예시

이 문서는 source에서 verify까지 가는 판단 흐름과, 그대로 실행할 수 있는 JSON 예시를 연결한다.
구체적인 payload를 새로 추측하지 말고 다음 다섯 파일을 함께 본다.

- [object-templates/build-coverage.complete.template.json](object-templates/build-coverage.complete.template.json):
  notes 8개 section과 `expected_objects`를 결속하는 assembled coverage
- [object-templates/direct-coverage.template.json](object-templates/direct-coverage.template.json):
  완성 객체를 직접 적재할 때 쓰는 exact `(id, kind)` coverage

- [object-templates/build-notes.complete.template.json](object-templates/build-notes.complete.template.json):
  9개 section을 모두 사용한 build 입력
- [object-templates/object-graph.complete.template.json](object-templates/object-graph.complete.template.json):
  schema·ID·lint를 통과하는 6-object 연결 그래프
- [object-templates/invalid/manifest.json](object-templates/invalid/manifest.json):
  notes·schema·lint·mutation에서 실패해야 하는 10개 반례와 실행 준비

아래 "참여 가능 조건" 설명은 의미를 추출하는 방법을 보여 주는 서술 예시다. 실제 JSON 모양과
검증 결과는 위 파일이 맡는다.

## 1. source 묶음 선언

대상은 참여 가능 조건이다.
이번 source packet에는 {{DEFAULT_BRANCH}} 코드, 현행 기능 문서, 서버 규칙 문서가 들어 있다.
코드 기준점과 상태 기록은 `scope.md`에 따라 남긴다.

## 2. 의미 원자 추출

코드에서 참여 가능 여부를 계산하는 심볼과 결과를 표시하는 경계를 찾는다.
문서와 서버 규칙에서 참여 가능한 조건, 반복 참여 예외, 화면에 보이는 설명을 확인한다.

추출 결과는 다음 원자로 정리한다.

- 참여 가능 조건의 현재 규칙
- 반복 참여가 가능한 예외
- 조건을 계산하는 코드 경계
- 결과를 표시하는 코드 경계

문서에만 있고 코드에 없는 운영 규칙은 근거를 붙여 별도 원자로 둔다.
확인할 수 없는 값은 후보에 넣지 않고 예외 목록으로 보낸다.

## 3. build 입력 조립

각 원자에 논리 key와 이번 source packet의 EvidenceRef를 붙이고 `COVERAGE`에 verify group,
context mode, 8개 section identity, `expected_objects`를 독립 선언한다.
코드 원자에는 확인한 심볼과 기준 commit SHA를 붙인다.
원자 사이 연결은 논리 key로 적고 build가 완성 ID와 객체 연결을 조립하게 한다.

기존 용어가 있으면 새 객체를 만들기 전에 참조와 갱신 경로를 확인한다.
구체적인 key와 용어 표면형 규칙은 `object-model.md`를 따른다. JSON 구조는
`object-templates/build-notes.complete.template.json`을 복사해 바꾼다. 일반 section에서는 build가
ID·공통 metadata를 만들지만, `extra_objects[]`에는 완성된 저장 객체 전체를 넣어야 한다.

## 4. verify 결과

독립 검증자는 각 코드 앵커가 실제 심볼과 경계를 가리키는지 확인한다.
규칙 설명이 source를 넘지 않는지, 예외가 본 규칙을 흐리지 않는지, 중복 원자가 없는지 반박한다.

검증 결과가 `fixed`면 수정한 원자와 근거를 다시 확인한다.
근거가 모자라면 그 원자를 적재하지 않고 필요한 source를 예외 목록에 남긴다.

## 5. 적재와 확인

build 오류가 없고 verify가 통과하면 한 묶음으로 ingest한다.
그 뒤 lint, 평가, 고립 객체, 샘플 회상을 완료 점검표에 따라 확인한다.

실행 순서는 다음과 같다.

1. assemble에서 `--coverage-out coverage.json`을 만들고 notes identity와 exact 비교한다.
2. `project-brain build --notes notes.json --coverage-file coverage.json --objects-file out.json > report.json`을 실행한다. 정상 `--dry`는 `objects/`, `raw/`, index를 쓰지 않는다.
3. build 결과의 `errors`가 비었고 `expected_objects`·`actual_objects`, `resolved_refs`, `preconditions`가 예상과 같은지 확인한다.
4. 독립 verify 뒤 `project-brain ingest --objects-file out.json --coverage-file coverage.json --build-report report.json ...`을 실행한다. coverage가 없으면 pre-write 실패다.
5. receipt의 `expected_objects == verified_objects`와 `committed|no_changes`를 확인한 뒤 finalize한다.
6. ingest 뒤 lint/audit와 소비 데이터 레포의 회귀 범위를 작업 종류에 맞게 실행한다.
7. 실패 관문을 확인할 때는 `invalid/manifest.json`의 `setup`, `validator`, `expected`를 함께 쓴다.

coverage는 원문 의미가 완전하다고 추론하지 않는다. 수기 JSON은 write boundary를 우회하므로
다음 audit 전까지 문제의 즉시 탐지를 보장하지 않는다.

이 예시는 현재 사실 한 조각을 끝까지 잇는 모습만 보여 준다. 상태값의 뜻은 `scope.md`, 변경의
결론은 `judgment.md`, 19종 전체 저장 계약은 `object-templates/README.md`에서 확인한다.
