---
name: {{PROJECT}}-brain-ingest
description: |
  Use when 완료된 기능이나 도메인 지식을 Brain 객체로 소급 적재할 때.
  진행 중 개발의 실시간 적재나 과거 세션 로그 마이닝은 이 스킬 범위가 아니다.
---

# {{PROJECT}} Brain 적재

완료된 기능 또는 확정된 도메인 지식을 근거와 코드 앵커에 연결해 Brain에 적재한다.
이 문서는 실행 순서만 정한다. 객체 모양, 판정 기준, 명령과 저장 규약은 해당 reference가 정본이다.

## 적용 범위

이 스킬은 완료된 사양이나 확정된 도메인을 소급 적재할 때만 쓴다.
진행 중 개발의 후보 선점과 끝난 세션 로그 마이닝은 다른 적재 흐름으로 넘긴다.

사용자가 기능 이름만 주면 이름은 대상일 뿐 근거가 아니다.
기본 source packet은 현재 {{DEFAULT_BRANCH}} 코드, 현행 기능 문서, 현재 운영·서비스 규칙이다.
기본 목표는 현재 사실 적재이며, 이력 범위는 `references/scope.md`의 `history_coverage=unsearched`로 기록한다.
기본 source packet을 선언한 뒤에만 코드와 문서를 탐색한다.
소스 읽기 전에 사용자에게 보이는 첫 진행 보고에 `Source Intake`, `route=single|batch` 중 하나, `history_coverage=<값>`, 그리고 `Concept Intake: <개념 수>` 또는 `Concept Intake: none(어휘 변경 없음)`을 정확히 표기하고 대상·소스 묶음·코드 기준점을 남긴다; 보류해도 이 선언은 생략하지 않는다.

소스 위치를 찾지 못했거나 사용자가 소스 범위를 제한했으면 필요한 범위만 짧게 확인한다.
소스 충돌, 현행 소스 부재, 경계 불명확, 이력 근거 부족, 원자 승격이 결과를 바꾸는 경우, 개념 선언에 없는 개념 후보(표현·출처·잠정 뜻)만 예외 큐로 모은다.
그 밖의 세부 판단은 source에 맞으면 조용히 진행하고, 예외 큐만 사용자에게 확인한다.

적재 전 대상이 완료 소급 적재인지, 코드 앵커를 {{DEFAULT_BRANCH}}에서 고정할 수 있는지 확인한다.
머지 전 코드라면 안전하게 앵커를 고정할 수 있을 때까지 기다린다.

작은 기능은 이 라우터와 reference만으로 진행한다.
여러 컨텍스트, 대량 원자, 긴 코드 흐름이 얽히면 대규모 운영 reference를 함께 읽는다.

상태축과 머지 전·후 경계는 `references/scope.md`가 정한다.
상태 이름을 적었다고 적재나 이력 확인이 끝난 것으로 간주하지 않는다.

`GlossaryTerm`을 생성하거나 변경할 때 `references/glossary-criteria.md`를 먼저 읽는다. 어휘를 만들거나 바꾸지 않는 적재에서는 이 기준을 읽을 필요가 없고 개념 선언도 생략할 수 있다; 생략했으면 `GlossaryTerm` 생성·변경을 하지 않는다.
`GlossaryTerm`은 사용자의 개념 선언에서만 만든다. 사용자가 없어 선언을 받지 못하면 candidate로도 만들지 않고, mapping·CodeLocator는 정상 적재하되 어휘는 적재 보고서의 `pending_concepts`(컨텍스트, 후보 표현, 출처)에만 남긴다. 지속 상태나 corpus 흔적은 만들지 않으며, 그 컨텍스트의 다음 적재가 Concept Intake에서 이 목록을 다시 제시한다.

## 절대 규칙

1. Source Intake를 먼저 선언하고, 대상과 이번 소스 묶음을 분리한다.
2. 사실의 우선순위는 코드 동작, 주석, 보조 문서 순서다.
3. 메모리, handoff, 이전 대화는 원문 근거가 아니며 이번 소스 묶음으로 다시 확인한다.
4. 코드 앵커는 {{DEFAULT_BRANCH}} 이력에서 도달 가능한 commit SHA와 확인한 심볼을 함께 남긴다.
5. 독립 질문·근거·변경 이력이 있는 것만 의미 원자로 객체화한다.
6. 논리 key 자리에 완성 ID를 넣지 않으며, 형식과 예외는 `references/object-model.md`를 따른다.
7. 고아를 남기지 않고, 연결은 primary 하나와 실제 공동 primary까지만 둔다.
   `history_coverage=complete` 판정과 현재 검수 상태는 `references/scope.md` 기준으로 분리한다.
8. 고위험 객체는 추출자와 분리된 적대 검증을 거친다.
9. 기존 사용자 변경은 작업 범위 밖 불변 상태로 보존한다. stage와 commit은 승인된 경로만 명시한다.

위반이 발견되면 저장 전에 소스 묶음, 원자, 연결을 고친 뒤 다시 검증한다.
근거가 서로 맞지 않으면 빠르게 하나를 고르지 말고 판정 reference의 절차를 따른다.

고위험은 아래 일곱 경우만 뜻한다.

- `DecisionRecord`를 만들거나 바꿀 때
- 기존 사실을 supersede할 때
- `spec_reflected=no`를 기록할 때
- `confidence=low`를 기록할 때
- 이번 적재에서 새 `source_type`을 처음 쓸 때
- 코드 앵커를 새로 만들거나 바꿀 때
- `history_coverage=complete`를 선언할 때

## 실행 흐름

1. **Source Intake.** 대상, 현재 사실 또는 이력 범위, 이번 소스 묶음, 코드 기준점을 짧게 선언한다.
2. **개념 선언(Concept Intake).** 사용자가 이번 컨텍스트의 개념을 먼저 말한다. 개념마다 네 칸 — 대표 이름, 팀의 뜻(한두 문장), 예시, 아님/이웃(헷갈리는 이웃 개념) — 을 받고, 동의어·별칭 후보는 있으면 적되 표면 규칙은 `references/object-model.md`를 따른다. 인터뷰가 아니라 역제안 후 확인이다: 선언 없이 기능 이름만 왔으면 소스를 읽어 개념 후보 목록(이름·잠정 뜻·출처)을 만들고 "맞다 / 빼라 / 더 있다"를 한 번에 받는다 — 후보는 질문지일 뿐 객체(candidate 포함)로 만들지 않으며, 열린 질문은 이것 하나다. 질문마다 에이전트의 추정 답과 근거를 붙여 "예 / 아니오 / 수정"으로 끝나게 하고, 횟수 상한은 두지 않되 확인형으로 닫히지 않는 개념은 이번 적재에서 어휘로 만들지 않고 보류한다. 그 외 모호성은 `references/glossary-criteria.md`의 사용자 판단 네 가지를 그대로 따른다. 사용자가 문장 단위로 확인해 승인한 선언만 raw 문서로 저장하고 `EvidenceManifest`(`source_type=user_statement`)로 등록한다 — 저장 규약과 근거 조립은 `references/ingest-tools.md`. 답은 선언 문서에 그대로 들어가 근거가 되며, 확인한 대상과 질문을 명시하고 확인 하나를 다른 개념의 승격으로 넓히지 않는다.
3. **소스 읽기.** 코드·현행 문서·보조 근거를 읽고, 코드로 확인 가능한 흐름은 프로젝트 규칙에 맞춰 추적한다. 선언에 없는 개념 후보가 나오면 term을 만들지 않고 즉시 묻지도 않으며, 예외 큐에 모아 한 번에 묻는다.
4. **원자·coverage 선언.** 의미 원자와 독립 expected planner 입력을 먼저 정해 `COVERAGE`의 `expected_objects`에 정확한 `(id, kind)`를 선언한다. coverage는 원문 의미 완전성을 추론하지 않는다.
5. **연결 조립.** coverage를 `--coverage-out`으로 고정하고 notes와 exact 비교한 뒤, build에 같은 `--coverage-file`을 넘겨 ID와 연결을 조립한다. `GlossaryTerm` 정의의 첫 문장은 선언의 "팀의 뜻"을 그대로 또는 다듬어 쓰고, 코드 대응(관리 클래스·식별 코드·저장 필드)은 두 번째 문장 이후에 둔다; 첫 문장에 코드 식별자가 있으면 다시 쓰되 이름 유래를 밝히는 짧은 괄호 설명은 허용하고, 문자열 기계 거부 게이트는 두지 않는다. 선언 개념이 기존 `GlossaryTerm`과 같은 개념이면 ID를 승계하고 정의를 선언의 뜻으로 다시 쓴다(`references/update-rules.md`). mapping의 `glossary_term_ids`에 term을 넣는 조건은 "그 mapping이 개념의 정의·범위나 개념이 발동·적용·처리되는 동작을 설명한다"이며, 개념을 지나가며 언급하거나 다른 개념의 설명 안에서 참조만 하는 mapping은 연결하지 않는다 — 그 mapping은 본문에 개념 이름을 쓰므로 검색 표면에서는 회수된다.
6. **적대 검증.** 별도 검증자가 근거, 경계, 코드 앵커, 중복을 반박하며 확인한다. 변경 이력의 결론은 `references/judgment.md`로 판정한다.
7. **수정 또는 보류.** 기존 사실을 갱신하거나 대체하면 `references/update-rules.md`의 kind별 묶음을 따른다. 근거가 없는 항목은 억지로 채우지 않는다.
8. **적재.** build 오류가 없고 coverage-bound build report가 맞을 때만 같은 `--coverage-file`로 한 묶음 ingest한다. coverage 없는 single/batch는 쓰기 전에 실패해야 한다.
9. **마무리.** 적재 뒤 검증과 회상 확인은 `references/completeness-checklist.md` 및 `references/ingest-tools.md`를 따른다.

원자별로 source의 위치, 확인한 경계, 남은 불확실성을 짧게 기록한다.
나중에 추적할 수 없는 설명은 검증을 통과한 것으로 취급하지 않는다.

커밋이 필요한 작업에서는 시작과 끝의 `git status --short`를 대조한다. `git add -A`,
`git add .`, `git commit -a`를 쓰지 않고 승인된 경로만 stage한다. 기존 변경과 작업 경로가
겹치면 자동 commit·stash로 정리하지 말고 중단해 겹친 범위를 보고한다.

코드 근거가 없는 서버 규칙이나 문서 규칙도 근거가 충분하면 적재 대상이다.
코드 앵커가 없다는 이유만으로 저장 대상에서 빼지 않는다.

반대로 코드에 심볼이 있다고 해서 그 심볼 하나를 곧바로 객체 하나로 만들지 않는다.
표시 세부나 단순 헬퍼는 독립 회상 가치가 없으면 원자에 흡수한다.

코드 기반 extract 또는 verify를 시작하기 전 `references/project-code-verification.md` 존재 여부를 확인한다.
있으면 먼저 읽고 프로젝트의 코드 검증 계약을 이번 작업의 기준으로 적용한다.
코드 흐름의 확인 기록, 끊긴 경계, 대체 확인은 검증 결과에 남긴다.

동적 workflow나 하위 작업자에게 코드 기반 extract/verify를 맡길 때는,
읽은 프로젝트 코드 검증 계약을 작업 설명과 프롬프트에 그대로 전달한다.
프로젝트 계약을 지키는 확인 기록이 없으면 사용자 확인 대기가 아니라 검증 실패다.

## 단건과 대량 분기

항목 하나면 단건 실행 흐름을 쓴다. direct/assembled coverage와 build·적재 전 검증을 끝낸 뒤에만 마무리 단계로 간다.
실행 인자, `--dry`, 저장 규약은 `references/ingest-tools.md`를 따른다.

단건도 부분 결과를 성공으로 부르지 않는다.
검증이나 적재가 실패하면 원인을 고친 뒤 같은 완료 게이트를 다시 통과한다.

여러 항목이면 batch manifest와 report를 사용한다. 배치 시작 전에 배치에 든 컨텍스트들의 개념 선언을 한 세션에서 모아 받고(추정: 컨텍스트 10개면 30~40분), 그 뒤 에이전트가 자율로 돈다. 선언을 못 받은 컨텍스트는 mapping·locator만 적재하고 어휘는 `pending_concepts`로 남겨 배치가 막히지 않게 한다.
각 항목은 build·검증·ingest까지만 수행하고, 중간에 색인 재생성이나 전체 검수를 반복하지 않는다.
실패 항목이 하나라도 있으면 finalization을 호출하지 않는다.

report의 `item_records`가 manifest 항목과 같은 순서·key인지 확인한다. 각 record는 item/input
바인딩, 상태, 실패 정보, canonical mutation receipt를 한 객체에 묶는다. terminal record는 `status=committed|no_changes`이고 receipt의 `expected_objects`와 `verified_objects`가 같아야 한다.
`transactions`·`succeeded`·`failed`는 이 정본에서 파생된 호환 필드일 뿐 독립 근거가 아니다.
batch `manifest_sha256`, target config가 해석한 canonical brain root와 inode, immutable staged
입력 hash, resolved target commit과 실제 engine HEAD를 포함한 resume 계약이 그대로인지 확인한다.
finalization은 durable intent/journal에서 복구한 receipt와 record가 정확히 일치한 뒤에만 실행한다.
semantic gate 전에는 `strict_commit`, 끝난 뒤에는 derived 출력만 허용하는
`post_gate_object_tail` mode로 receipt/current object corpus tail을 다시 확인한다. batch는
finalizer가 돌아온 뒤 state/input/receipt를 post-finalizer로 다시 확인해야만 완료한다.
config 해석 등 실행 상태 확인에서 발생한 일반 예외는 traceback으로 빠져나오지 않고
`ok=false` 또는 `finalized=false`인 JSON 실패로 남아야 한다.
새 wave용 임시 스크립트로 운영 규약을 우회하지 않는다.

중단된 묶음은 같은 입력과 보고서로 재개한다. durable receipt가 확인된 committed prefix만 건너뛰고,
첫 failed/pending record부터 순서대로 재개하며 첫 실패에서 tail 실행을 멈춘다.
대규모 분할, 기존 컨텍스트 확장, 동적 workflow 운영은 `references/system-domain-playbook.md`를 따른다.

workflow 최상위 상태만으로 완료를 선언하지 않는다.
결과 JSON은 `scripts/validate_workflow_result.py`를 통과해야 조립 단계로 갈 수 있다.
재개 가능한 제한이나 실패는 미완료 보고서로 남기고, 재개 후 다시 검증한다.

## 완료 게이트

적재 전에는 이번 소스 묶음, 의미 원자, 논리 key, 연결, 적대 검증 결과를 확인한다. 어휘를 만들거나 바꾼 적재는 term별로 (1) 정의 첫 문장이 개념 선언의 "팀의 뜻"에서 왔는지 확인하고 (2) 연결 mapping마다 "정의나 동작을 설명한다"는 근거를 한 줄로 적는다; 연결 수만 세는 검사는 두지 않으며, 어긋나면 적재 전에 고친다.
상태축의 허용값과 현재 검수 상태는 `references/scope.md` 및 `references/completeness-checklist.md`로 점검한다.

단건은 build 오류가 없고 필요한 검증을 통과해야 적재한다.
대량은 모든 항목 성공, 빈 실패 목록, 한 번의 finalization이 함께 확인돼야 닫는다.

적재 후에는 lint, 색인, 평가, 고립 객체, 실제 코퍼스 검사, 샘플 회상을 확인한다.
상세 게이트와 실패 처리 순서는 `references/completeness-checklist.md`를 따른다.

검증 명령의 종료 상태와 결과 파일을 모두 확인한다.
최상위 workflow 상태, 에이전트의 구두 보고, 이전 실행 결과만으로 닫지 않는다.

검증 결과가 부족하면 성공으로 요약하지 않는다.
어느 단계가 멈췄는지와 재개에 필요한 입력을 보고서에 남긴다.

## Reference routing

- `references/glossary-criteria.md`: `GlossaryTerm` 생성·변경 전에 실제 프로젝트 이름과 코드 토큰을 구분하고 비어휘 의미의 라우팅을 정할 때 읽는다.
- `references/scope.md`: 적용 시나리오, 세 상태축, 머지 전·후 경계가 필요할 때 읽는다.
- `references/object-model.md`: 필수 필드, enum, 연결, 논리 key, 완성 ID, 코드 앵커 key, 동의어·별칭을 다룰 때 읽는다.
- `references/judgment.md`: 변경이 기존 사실을 대체·보완·충돌시키는지 판정할 때 읽는다.
- `references/update-rules.md`(설치 후 `{{PROJECT}}-brain-ingest/references/update-rules.md`): 기존 객체를 kind별로 갱신·대체할 실제 묶음과 엔진 빈틈을 확인할 때 읽는다.
- `references/ingest-tools.md`: build, ingest, raw 보관, 단건·대량 실행과 마무리 명령이 필요할 때 읽는다.
- `references/system-domain-playbook.md`: 큰 도메인 분할, 동적 workflow, 재개 운영이 필요할 때 읽는다.
- `references/completeness-checklist.md`: 적재 직전과 직후의 통과 조건을 점검할 때 읽는다.
- `references/worked-example.md`: 한 기능을 source에서 verify까지 연결한 작은 흐름이 필요할 때 읽는다.
- `references/ingest-case-log.md`: 재사용 코드나 규약으로 승격할 변칙을 기록하거나 찾을 때 읽는다.
- `references/project-code-verification.md`: 파일이 있을 때만 코드 기반 extract/verify 전에 읽고 그 계약을 작업자에게 전달한다.

reference의 상세 규칙을 이 본문에 복사하지 않는다.
충돌하면 프로젝트의 AGENTS.md와 해당 reference의 최신 계약을 우선한다.

reference를 읽은 시점과 적용한 범위는 작업 기록에 남긴다.
프로젝트 전용 overlay는 범용 템플릿의 관리 대상이 아니므로 새로 만들거나 덮어쓰지 않는다.
새 reference가 필요하면 기존 소유권과 겹치지 않는지 먼저 확인한다.
작업 중 발견한 반복 변칙은 case log에 짧게 기록한다.
