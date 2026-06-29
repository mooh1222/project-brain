# 완전성 점검 체크리스트 (적재 전 자가 점검)

SKILL.md 5단계에서 참조. `ingest`/`lint`는 "없는 id 참조·충돌·고아"만 잡고
**"규칙이 빠졌다"는 못 잡는다.** 그 빈틈을 네가 메운다. 32객체 1차 적재가
미완성으로 끝난 실제 갭이 이 점검의 근거다.

## 점검 항목

### 0. source packet을 선언했나
- 기능명은 target이지 EvidenceRef가 아니다. 기능명만 받은 뒤 바로 코드 검색·객체 생성·EvidenceManifest 생성을
  시작하지 않았나.
- 사용자 요청이 소스·이력 범위를 지정하지 않았으면 기본값을 선언했나:
  current {{DEFAULT_BRANCH}} 코드 + 현행 기획서 + 서버위키, `current_ingest_done` 목표,
  `history_coverage=unsearched`.
- wiki/handoff/memory를 이번 source packet에 넣겠다고 명시하지 않았으면 EvidenceRef로 쓰지 않았나.
- 애매한 의미 원자마다 질문하지 않고, 소스 충돌·현행 소스 부재·경계 불명확·history complete 선언 불가 같은
  진짜 예외만 묶어 예외 큐로 만들었나.

### 1. `feature_done`, `current_ingest_done`, `history_coverage`를 분리했나
- `feature_done`: 기능이 소급 적재 대상일 만큼 완료됐다는 외부 상태. Jira/Slack 데이터 유무가 조건은 아니다.
- `current_ingest_done`: 현재 {{DEFAULT_BRANCH}} 코드 + 현행 기획서 + 서버위키로 현재 meaning/value/boundary가 확인된 상태.
- `history_coverage`: 변경 이력 확인 범위. why/as-of 질의 가능 여부만 결정한다.
- `DomainMapping.caveats`나 슬라이스 ingest memo에 아래 고정 literal 중 정확히 하나가 남았나:
  - `history_coverage=unsearched`
  - `history_coverage=partial`
  - `history_coverage=complete`
- `history_coverage=complete`가 아니면 `why_changed`/`as_of_history` 질의는 답하지 말고 변경 이력 미적재 또는
  부분 적재라고 표시한다.

### 2. 코드 심볼 인벤토리가 의미 원자로 전부 커버됐나
- 코드 심볼은 발견 단위이고 저장 단위는 의미 원자다.
- {{DEFAULT_BRANCH}} 대상 클래스 전부를 1-pass로 훑고, 독립 규칙/동작을 담은 public 메서드를 2-pass로 승격했나.
- 독립적으로 질문되고, 독립 근거를 가지며, 독립 변경 이력을 가질 수 있으면 별도 DomainMapping으로 저장했나.
- enum 값은 기본적으로 한 의미 원자의 값 목록으로 두되, 특정 값이 독립 행동 규칙·독립 근거·독립 변경 이력을
  가지면 별도 의미 원자로 승격했나.

### 3. 기획서 기능 목차 대비 빠진 규칙이 없나
- 기획서 섹션을 체크리스트로 훑어 코드 뼈대에서 안 잡힌 서버·순수 규칙
  (선착순·완주 기준·참가 인원·참여 가능 조건 등)이 객체로 들어갔나.

### 4. `history_coverage`가 실제 EvidenceRef와 맞나
- `history_coverage=unsearched`: 1층 의미 골격만 봤다. EventLedgerRecord가 없어도 현재 질의는 가능하지만
  why/as-of는 차단한다.
- `history_coverage=partial`: 일부 Jira/Slack/PR/commit만 봤다. 확인한 이력만 답하고 빠진 소스를 경고한다.
- `history_coverage=complete`: 베타·리얼 QA를 거치며 들어온 변경이 DecisionRecord/EventLedgerRecord로 들어갔다.
  - Jira QA issue → `qa_issue`
  - 개선 티켓 → `improvement`
  - beta sanity 피드백 → `sanity_change`
  - 릴리즈 후 수정 → `hotfix_change`
  - Slack 모호점 해소 → `spec_clarification`
- 값이 바뀐 규칙은 EventLedgerRecord + supersede 체인으로 완결됐나.
- 갭 신호: `history_coverage=complete`인데 EventLedgerRecord가 0개거나 DecisionRecord가 전부
  `spec_clarification`/`implementation_boundary`뿐이면 변경 이력을 안 본 것이다.

### 5. reviewed DomainMapping·GlossaryTerm이 검증된 근거(evidence_refs)를 가졌나
- 근거 원칙(§6.4). reviewed 매핑·용어는 검증된 1차 근거가 있어야 한다 — 코드앵커든 서버위키든 기획서든.
  코드앵커는 근거의 한 종류일 뿐 필수가 아니다.
- 코드로 표현되는 매핑은 {{DEFAULT_BRANCH}} 코드에 `code_locator`로 닻을 내리고, 코드 흔적이 0인 서버·순수 규칙은
  서버위키·기획서 근거로 잇고 왜 코드앵커가 없는지 `boundary`/`caveats`에 적는다.
- `schema.py`는 reviewed `DomainMapping`·`GlossaryTerm`의 `evidence_refs` non-empty를 강제한다(§6.4 — 근거 빈
  reviewed는 거부). 단 `code_locator_ids` non-empty는 강제하지 않는다(코드앵커는 한 종류라 서버규칙엔 없을 수 있음).
  lint는 `code_locator_ids`가 있을 때 없는 id를 가리키는지(dangling)만 잡는다.

### 6. 고아가 없나 (32객체 실패 패턴의 핵심)
- 잇는 매핑/결정 없는 GlossaryTerm.
- 결정 0개인 변경 흔적(Jira·Slack은 봤는데 DecisionRecord로 안 묶음).
- 가리키는 EvidenceManifest 없는 EvidenceRef.

### 7. spec_reflected drift를 표시했나
- Jira·Slack엔 있는데 기획서 미반영인 결정은 `spec_reflected=no`로 표시했나.
  (lint 8c가 reviewed mapping의 미반영 결정을 review-needed로 띄운다.)

### 8. 사전지식 오염을 막았나
- 이전 세션·설계문서·작업 히스토리·메모리에서 알아버린 사실을 객체 근거로 쓰지 않았나.
- claim-bearing field(`meaning`, `boundary`, `value`, `decision`, `caveat`, `code_locator`)가 이번 소스 패킷의
  EvidenceRef를 가리키나.
- 전 객체 cold replay는 필수가 아니다. 대신 필드별 출처 태깅을 하고, 고위험 객체만 재구성 감사를 한다:
  `DecisionRecord`, supersede, `spec_reflected=no`, 낮은 confidence, 새 source type, code anchor,
  `history_coverage=complete` 선언.

## lint가 잡아주는 것 (점검 후 자동 확인)

자가 점검을 마치면 `ingest`가 내부적으로 `lint_store`를 돌려 아래를 거부한다
(엔진 레포 `src/project_brain/lint.py`):

- dangling `evidence_refs` / `review_record_id` (없는 id 참조)
- DomainMapping 링크 dangling (8a) / DecisionRecord 링크 dangling (8b)
- review-needed drift (8c): decision이 reviewed mapping을 affect하는데 mapping의
  `decision_record_ids`에 그 decision이 없음
- supersession 불일치 (8d): superseded인데 status가 still reviewed
- ReviewRecord target dangling (8e)
- 같은 subject+predicate에 값이 갈리는 open reviewed fact (충돌)

lint가 무엇을 잡는지와 **무엇을 못 잡는지**를 구분하라: 위 자가 점검 항목은
lint가 못 잡으니 네가 책임진다.
