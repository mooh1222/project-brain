# 객체 갱신 규약

기존 객체와 현실이 달라졌을 때 모든 쓰기 흐름이 따르는 공통 정본이다.

## 책임 경계

- `judgment.md`: 새 사실이 기존 사실을 대체·보완·충돌하는지 의미를 분류한다.
- `update-rules.md`: 분류 결과를 kind별 객체 묶음과 상태 전환으로 옮긴다.
- `object-model.md`: 필드 모양, enum, 연결 불변을 정한다.
- `ingest-tools.md`: build·ingest·promote CLI 호출법을 정한다.

## 엔진이 강제하는 것

- ingest는 모든 객체의 schema와 병합 store lint를 먼저 통과시킨 뒤 하나의 rollback transaction으로 쓴다.
- reviewed→candidate 강등은 거부한다. reviewed→reviewed same-ID 갱신과 reviewed→superseded 전환은 허용한다.
- 새 DomainMapping의 `supersedes_mapping_ids`가 가리키는 옛 mapping이 reviewed로 남으면 lint가 거부한다.
- 같은 subject·predicate에 값이 다른 open reviewed TemporalFact가 둘 이상이면 lint가 거부한다.
- build `updates`는 kind별 허용 필드와 `set`/`union`/`expected_updated_at`을 검사한다.

## 사람이 지키는 절차

- reviewed 객체의 의미 변경은 사용자 승인 뒤 reviewed 상태로 반영한다. 이는 사람 절차이며 엔진은 의미 승인 여부를 판정하지 않는다.
- DecisionRecord와 EventLedgerRecord는 모든 변경에 자동으로 붙이지 않는다. 결정과 시간 사건은 역할이 다르며 서로 대체재가 아니다.
- 후보 선점과 최종 승인 전환을 분리한다. 후보가 기존 정설을 대체할 가능성만으로 완결 supersede 묶음을 만들지 않는다.
- ingest 전에 전체 묶음과 diff를 검토하고, 저장 뒤 공통 완료 게이트를 실행한다.

## 현재 엔진 빈틈

엔진은 TemporalFact의 `derived_from_event_id`와 `supersedes` 대상이 존재하는지, 올바른 kind인지,
사슬에 cycle이 없는지를 충분히 검증하지 않는다. 따라서 Event가 없으면 적재 자체가 항상 실패한다고
가정하면 안 된다. 쓰기 전에 연결 대상을 직접 확인하고, 이 빈틈을 통과 근거로 쓰지 않는다.

## kind별 갱신

### DomainMapping 완료 대체

옛 전체 객체를 `status=superseded`로 바꾸고, 새 ID의 reviewed mapping에
`supersedes_mapping_ids: [<old id>]`를 넣어 같은 ingest 묶음으로 저장한다. 변경 이유가 독립 결정이면
DecisionRecord를 연결한다. 옛 reviewed 잔존은 lint가 막는다. candidate 선점 시점에 곧바로
supersedes 링크를 달면 옛 reviewed가 남아 lint에 막힐 수 있으므로, 최종 승인 묶음에서 전환한다.

### TemporalFact 완료 값 변경

옛 fact는 reviewed를 유지한 채 `valid_until`을 변경 시점으로 닫는다. reviewed EventLedgerRecord와
reviewed 새 fact를 같은 묶음에 넣는다. 새 fact의 `supersedes`는 old id 하나인 scalar,
`derived_from_event_id`는 Event id, scope는 객체다. 옛 `old status=superseded` 전환은 as-of reviewed
경로에서 사라지므로 기본 금지다. candidate 선점은 새 값 후보만 기록하고, 승인 때 old 닫기·Event·새 fact를 함께 적용한다.

### GlossaryTerm과 DomainContext

generic supersede 링크가 없다. 같은 ID를 amend하거나 build `updates`의 `set`/`union`과
`expected_updated_at`을 사용한다. 의미 변경 승인을 거쳤는지와 근거 변화는 diff에 남긴다.

### CodeLocator

코드가 그대로인지 다시 확인한 경우 `project-brain mark-checked`가 `commit_sha`, `verified_at`,
`updated_at`을 갱신한다. path·symbol 자체를 고칠 때는 direct same-ID amend를 쓴다. 코드 변경이
mapping 의미까지 바꾸면 CodeLocator만 고치지 말고 DomainMapping 흐름으로 판정한다.
새 locator와 좌표 변경 locator의 `verified_at`은 write verifier가 실제 blob·symbol·quote를
확인한 뒤 기록한다. 외부 `verified_at`이나 `title`을 검증 근거로 받지 않는다. title은
display_only이고, verified quote가 필요한 쓰기에는 일반 quote 우회 flag가 없다.
