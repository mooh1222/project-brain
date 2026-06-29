# 워크된 예시 — 샐리 카누 "참여 가능 조건" 심볼 끝까지 따라가기

5단계 절차가 한 심볼에서 실제로 어떤 객체 묶음을 만드는지 한눈에 보여준다. 전체 기능이 아니라
**한 매핑 슬라이스**만 끝까지 따라간다. 실제 적재는 이런 슬라이스를 기능 전체에 대해 반복한다.

## 0. 상황

샐리 카누 이벤트가 베타 QA까지 끝나 리얼 QA 중. {{DEFAULT_BRANCH}}에 코드가 있고 현행 기획서(spec-v8)·서버 위키를
찾을 수 있다 → 완료 소급 적재(시나리오 나).

단, 기능 완료와 현재 사실 적재와 변경 이력 확인 범위는 분리한다. 아래 참여 가능 조건 슬라이스에서
Jira/Slack/PR 변경 이력까지 확인하지 않았어도 `current_ingest_done`은 가능하고, 매핑에는
`history_coverage=unsearched` 또는 `history_coverage=partial`을 남긴다. 이력까지 확인했을 때만
`history_coverage=complete`다.

사용자가 "샐리 카누 brain에 넣어줘"라고만 했다면 기본 source packet을 선언하고 진행한다:
현재 {{DEFAULT_BRANCH}} 코드 + 현행 기획서 + 서버위키, `history_coverage=unsearched`.

## 0단계 — 컨텍스트 + 매니페스트

- `DomainContext` `context.sally-canoe` 1개(경계: 레이스 lifecycle/state).
- `EvidenceManifest`: 기획서(`source_type=spec`), 코드(`code_search`), 서버 위키(`wiki`).
  기획서 원문은 brain raw 보관, 나머지는 링크. Jira/Slack/PR은 변경 이력까지 확인할 때만 추가한다.

## 1단계 — 코드 심볼 인벤토리

참여 가능 조건 관련 심볼을 {{DEFAULT_BRANCH}}에서 찾는다. 예를 들어 `SallyCanoeEventManager.hpp`의 판정 헬퍼가
레이스 시작 가능 시점을 판단한다면 model 계층(데이터 판정) → 매칭 소스는 서버 위키 + 기획서 규칙이다.

그 판정 헬퍼가 "완주 후 일정 조건을 만족해야 새 레이스를 시작할 수 있다"는 독립 규칙을 담으면 클래스가
아니라 이 판정 헬퍼 묶음을 매핑으로 잡는다. 라인은 {{DEFAULT_BRANCH}} 기준 `git show`로 확정한다.

## 2단계 — 심볼에 소스 붙여 매핑

참여 가능 조건이 "무엇이고 어떤 규칙인가"를 기획서·위키에서 찾아 객체를 만들고 연결한다:

- `CodeLocator` `code.join-availability-manager` — path/symbol/line/locator_source=rg/verified_at, {{DEFAULT_BRANCH}} 기준.
- `GlossaryTerm` `g.join-availability`(참여 가능 조건), `g.repeat-join`(반복 참여) — 용어 + 정의(+ 별칭이 있으면).
- `EvidenceRef` `ev.ref.spec.join-availability` — 기획서 참여 조건 섹션을 가리킴(ref_type=spec_section,
  evidence_manifest_id=기획서 매니페스트).
- `DomainMapping` `mapping.join-availability` — mapping_key="join-availability-repeat", meaning/boundary,
  glossary_term_ids=[g.join-availability, g.repeat-join], code_locator_ids=[code.join-availability-manager],
  caveats=[`history_coverage=unsearched` 또는 `history_coverage=partial` 또는 `history_coverage=complete`],
  evidence_refs=[ev.ref.spec.join-availability],
  decision_record_ids=[decision.join-availability](아래 3·4단계 결과).

(각 객체의 실물 JSON은 `object-model.md` 마지막 예시 절 참고.)

## 3단계 — 코드에 안 잡힌 규칙 보충

기획서 목차를 훑어 "반복 참여 MAX 제한" 같은 규칙이 코드 뼈대에서 다 잡혔는지 본다. 참여 가능 조건 값
자체가 서버가 내리는 값이면 `TemporalFact`(confidence는 위키 출처라 medium)로 저장하고,
클라가 그 값을 받아 표시하는 지점이 있으면 그 CodeLocator에 "클라 경계"로 연결한다.

## 4단계 — 변경 이력

참여 가능 조건 규칙이 처음 어떻게 정해졌는지/바뀌었는지를 결정으로 박는다:

- 최초 명시 → `DecisionRecord` `decision.join-availability`(decision_type=spec_clarification, spec_reflected=yes,
  affected_mapping_ids=[mapping.join-availability], affected_context_ids=[context.sally-canoe]).
- 만약 베타에서 참여 가능 조건 값이 바뀌었다면(가정): 옛 fact `superseded` + 새 fact +
  `EventLedgerRecord`(왜·언제) + 그 변경의 `DecisionRecord`(decision_type=improvement 또는 sanity_change).
  판정 기준은 `judgment.md`.
- Jira/Slack/PR/commit을 끝까지 확인했으면 `mapping.join-availability.caveats`의 literal을
  `history_coverage=complete`로 둔다. 일부만 봤으면 `history_coverage=partial`, 안 봤으면
  `history_coverage=unsearched`다.

## 완전성 자가 점검

- 참여 가능 조건 심볼 매핑됨, 기획서 참여 조건 규칙 누락 없음, mapping.join-availability가 code_locator 가짐,
  g.join-availability/g.repeat-join이 mapping에 연결됨(고아 아님), decision.join-availability가 mapping에 반영됨.
- `history_coverage` literal이 실제 확인 범위와 맞음. `history_coverage=complete`가 아니면 why/as-of 질의는 차단함.

## 적재 실행

1. 위 객체들(candidate 매핑 + reviewed인 code/decision/context 등)을 JSON 배열 파일로 모아
   `project-brain ingest`. 스키마·연결무결성 통과하면 저장.
2. 사용자에게 참여 가능 조건 슬라이스(의미·경계)와 예외 큐를 보여 확인.
3. 확인되면 `promote(scope="mapping_bundle", bundle_key="bundle.sally-canoe.domain-mapping")`로
   매핑을 reviewed 승격 → 승격 결과를 다시 ingest.
4. `lint_store` 0건 + query로 "참여 가능 조건" 질의가 mapping.join-availability를 회수하는지 확인.

이 슬라이스 한 덩어리를 기능 전체 심볼/규칙에 대해 반복하면 한 기능의 소급 적재가 끝난다.
