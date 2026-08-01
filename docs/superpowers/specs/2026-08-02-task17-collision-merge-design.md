# Task 17 Collision Merge Design

## Status

- 상태: 사용자 방향 승인 및 독립 설계 자문 반영 완료
- 기준 엔진: `f4ec72e720a9e1f2f3a4affc113ba3ab66949b10`
- 대상 단계: Task 8A를 새로 추가하고, 완료 뒤 Task 7 binding과 Task 8 ledger를 재생성
- 사용자 선택: 기존 canonical target의 본문을 정본으로 유지하고 source 전용 근거를 보존
- 독립 자문: Orca Run `run_c165cf8dde37`, Task `task_2311c586fb46`,
  Dispatch `ctx_9922f1740bc1`, Claude Opus 5 High, 판정 `AGREE_WITH_CHANGES`

## 배경

Task 8은 156행 canonicalization ledger를 만들기 전에 collision 두 건에서 중단됐다.
각 source는 별도 의미가 아니라 이미 존재하는 canonical target의 간략판이며,
`context_id`와 `mapping_key`도 target과 같다.

1. `mapping.disturb-drone.cloud-reskin-identity`
   → `mapping.disturb-drone.drone-cloud-reskin-identity`
2. `mapping.disturb-hedgehog.angry-shoot-block`
   → `mapping.disturb-hedgehog.angry-shoot-bubble-removal`

기존 `collision_distinct_rename`은 빈 새 ID를 요구하고 field change를 금지한다. 두 source의
유일한 canonical ID는 이미 점유돼 있으므로 distinct rename은 의미상·구조상 모두 거짓이다.
source를 조용히 버리면 source에만 있는 evidence와 backreference를 잃는다. 따라서 기존
canonical target을 survivor로 삼아 근거를 보존하는 first-class merge가 필요하다.

## 목표

- `collision_merge_into_existing`을 canonical repair의 정식 ledger action으로 추가한다.
- 기존 canonical target의 의미 본문을 유지한다.
- source에만 있는 관계 근거를 결정적으로 survivor에 합친다.
- source를 가리키는 모든 허용 참조를 survivor로 옮긴다.
- source와 survivor가 한 배열에 같이 있으면 source 항목만 제거하고 나머지 상대 순서를
  보존한다.
- merge의 delete/update/reference-collapse를 snapshot, ledger, canonical artifact,
  mutation manifest, intermediate receipt로 검증 가능하게 만든다.
- 기존 atomic apply, recovery, rollback, pure ID rename 단계를 깨지 않는다.
- 엔진 SHA 변경 뒤 Task 7 산출물과 Task 8 workbook을 새 SHA에 다시 묶는다.

## 비목표

- 일반 목적의 임의 객체 merge 프레임워크를 만들지 않는다.
- 서로 다른 의미의 DomainMapping을 자동 합성하지 않는다.
- 제목·요약·meaning·boundary를 새 문장으로 다시 쓰지 않는다.
- provenance reference를 다른 객체로 조용히 재지정하지 않는다.
- 이번 설계 단계나 엔진 구현 단계에서 BB2 object, eval, index, stale를 변경하지 않는다.
- Task 8의 정확한 ledger bytes에 대한 사용자 승인 게이트를 없애지 않는다.

## 검토한 접근

### A. Canonical repair 내부 first-class merge — 채택

기존 snapshot → ledger → plan → canonical artifact → live replan → atomic mutation 사슬을
그대로 사용한다. merge는 payload-identical rename이 아니므로 pure ID 단계보다 먼저
실행한다. 새 transaction 계층을 만들 필요가 없다.

### B. 별도 merge migration 단계 — 기각

두 행을 위해 snapshot·manifest·apply·resume 사슬을 복제해야 한다. recovery surface와
승인 지점만 늘고 신뢰 이득이 없다.

### C. 일반 delete/update mutation으로 우회 — 기각

classification, decision ledger, snapshot binding과 semantic approval을 우회한다. Task 17의
감사 계약보다 약하다.

## Ledger 계약

`CanonicalAction`에 다음 값을 추가한다.

```text
collision_merge_into_existing
```

merge decision row는 기존 row exact keys를 그대로 쓴다.

- `source_id`: 삭제할 invalid collision source
- `source_kind`: `DomainMapping`
- `source_sha256`: Phase A와 live source raw bytes의 SHA-256
- `action`: `collision_merge_into_existing`
- `new_id`: 이미 존재하는 canonical survivor ID
- `field_changes`: 빈 배열
- `decision_reason`: 같은 의미임과 target 본문 승계, 근거 union, caveat 결과를 설명
- `decision_evidence`: workbook source row와 `collision_target` pointer를 모두 포함

검증기는 merge action에만 existing target을 허용한다. 다른 rename action은 계속 target
부재를 요구한다. Task 17 ledger는 merge action이 정확히 두 행이어야 하고
`collision_distinct_rename`은 0행이어야 한다.

## Merge endpoint 검증

각 merge pair는 다음을 모두 만족해야 한다.

- source는 live store에 존재하고 ledger SHA와 exact다.
- target은 live store에 존재하며 canonical `DomainMapping`이다.
- source와 target은 서로 다른 ID다.
- merge target은 유일하며 다른 merge 또는 rename target과 겹치지 않는다.
- merge target은 156행 ledger의 다른 `source_id`가 아니다.
- source와 target의 `kind`, `context_id`, `mapping_key`, `review_record_id`가 같다.
- source는 `source_object_id` 또는 `source_object_ids` provenance 위치에서 참조되지 않는다.
- source를 참조하는 `ContextProjection`이 있으면 중단한다.
- source는 delete 대상이지만 explicit rename 대상은 아니다.
- target은 update 대상이며 create/delete 대상이 아니다.

corpus fingerprint, pre-snapshot, repo HEAD, engine SHA가 target의 before bytes까지 묶는다.
merge artifact는 target의 raw before SHA와 canonical after SHA를 추가로 기록한다.

## Payload 병합

병합은 새 pure helper 한 곳에서 만들며 planner와 mutation validator가 같은 함수를 사용한다.
별도 구현을 두지 않는다.

### Target-authoritative fields

다음 필드는 existing canonical target 값을 그대로 유지한다.

- `title`
- `canonical_summary`
- `meaning`
- `boundary`
- `poc_priority`

### Exact-equality fields

다음 필드는 source와 target이 JSON-exact로 같아야 한다.

- `kind`
- `schema_version`
- `status`
- `truth_role`
- `context_id`
- `mapping_key`
- `review_record_id`
- `review_state`
- `created_at`
- `updated_at`

### Target-first stable-union fields

각 입력은 중복 없는 `list[str]`이어야 한다. target의 기존 순서를 유지한 뒤 source에만 있는
값을 source 순서대로 붙인다.

- `code_locator_ids`
- `decision_record_ids`
- `evidence_refs`
- `glossary_term_ids`
- `tags`

### Caveat 신뢰 규칙

`caveats`는 단순 union하지 않는다.

- 각 입력은 중복 없는 `list[str]`이어야 한다.
- `history_coverage=<value>`가 한쪽에 있으면 양쪽 모두 정확히 하나씩 가져야 한다.
- 허용값의 보수성 순서는 `unsearched < partial < complete`다.
- 결과는 두 값 중 더 보수적인 값을 정확히 하나만 가진다.
- 다른 `key=value` caveat가 같은 key에서 충돌하면 중단한다.
- 충돌하지 않는 keyed caveat와 일반 문자열은 target-first stable union한다.

따라서 hedgehog의 `unsearched` + `partial`은 `unsearched` 하나로 남고, drone의
`partial` + `partial`은 `partial` 하나로 남는다. `complete`가 더 약한 근거와 합쳐져
신뢰를 높이는 일은 없다.

### Unknown-field gate

source와 target의 key set은 같아야 한다. `id`, 위 target-authoritative, exact-equality,
stable-union, caveat 필드 밖의 모든 값은 JSON-exact로 같아야 한다. 한쪽에만 있는 필드나
값 차이는 조용히 버리지 않고 중단한다.

## 참조 치환과 배열 collapse

merge pair는 일반 rename pair와 별도로 취급한다.

- scalar registered reference가 source면 target으로 바꾼다.
- list reference에 source만 정확히 한 번 있으면 같은 자리에서 target으로 바꾼다.
- list에 source와 target이 각각 한 번 있으면 source 항목을 제거한다.
- source를 제거한 뒤 남은 항목의 상대 순서는 바꾸지 않는다. 절대 인덱스 보존을 약속하지
  않는다.
- source 또는 target이 merge 전부터 두 번 이상 있으면 중단한다.
- unrelated duplicate나 malformed list를 이 작업에서 조용히 정리하지 않는다.

두 bundle review는 source와 target을 모두 가진다. 이 두 배열은 source 항목을 제거한다.
drone의 DecisionRecord 두 개는 source만 가진 단일 원소 배열이므로 target으로 제자리
치환한다.

## 감사 receipt

기존 `MutationManifest.reference_rewrites`는 배열 원소 제거로 뒤 인덱스가 이동하면 가짜
pointer rewrite를 만든다. 따라서 역할을 분리한다.

- scalar 및 길이가 변하지 않는 list 치환은 기존 `reference_rewrites`에 남긴다.
- merge 때문에 길이가 줄어드는 list field는 일반 pointer diff에서 제외한다.
- 각 merge `CanonicalRepairRow`에 `merge_receipt`를 추가한다.
- non-merge row의 `merge_receipt`는 `null`이다.

merge receipt exact shape:

```json
{
  "source_delete_before_sha256": "<raw source sha256>",
  "target_id": "<existing survivor id>",
  "target_before_sha256": "<raw survivor sha256>",
  "target_after_sha256": "<canonical survivor sha256>",
  "reference_collapses": [
    {
      "object_id": "<referrer id>",
      "pointer": "/target_object_ids",
      "before_ids": ["..."],
      "after_ids": ["..."],
      "removed_index": 0
    }
  ]
}
```

`target_after_sha256`는 row의 `canonical_payload_hash`와 같아야 한다. collapse row는
`before_ids[removed_index] == source_id`, `after_ids == before_ids`에서 그 항목만 제거한
결과, target이 before/after에 정확히 한 번 존재함을 검증한다.

Mutation manifest top-level schema와 transaction journal schema는 바꾸지 않는다.
source는 `deletes`, survivor와 referrer는 `updates`, 길이가 변하지 않는 치환은
`reference_rewrites`에 기록된다. file transition recovery는 기존 before/after SHA로
충분하고, semantic collapse 감사는 canonical artifact merge receipt가 담당한다.

## Planner와 mutation validator

ledger에서 세 map을 분리한다.

- field-repair rename map: 기존 5행
- merge map: 새 2행
- later pure ID rename map: merge 2행을 제외한 ID-only 행

canonical repair plan은 공통 replacement view를 쓰되 file operation은 분리한다.

1. field-repair source는 delete + new-create + explicit rename이다.
2. merge source는 request object에 넣지 않고 delete한다.
3. merge survivor는 pure helper로 만든 update object를 한 번만 넣는다.
4. inbound referrer는 merge-aware rewrite/collapse helper 결과로 update한다.
5. precondition은 field-repair source, merge source, merge survivor, 모든 변경 referrer를
   exact before hash로 묶는다.
6. `request.renames`에는 field-repair rename만 넣고 merge pair는 넣지 않는다.
7. canonical intents는 5 rename intent와 2 merge intent를 모두 가진다.

`_validate_canonical_repair_request`는 intent를 reason별로 나눈다.

- explicit rename pairs는 rename intent하고만 exact match
- delete IDs는 rename source와 merge source의 합집합
- created IDs는 rename target하고만 exact match
- merge target은 existing update여야 함
- merge source는 input에 없어야 함
- merge survivor와 referrer의 expected payload는 planner와 같은 pure helper로 재계산
- 그 밖의 input 변화는 계속 `canonical_repair_payload_changed`로 거부

기존 `delete_only` 금지는 유지한다. existing target merge는 정확한 merge intent와 ledger
binding이 있을 때만 허용한다.

## Grandfather와 lint

before/after grandfather hash normalization은 rename map만 쓰면 안 된다. field-repair와
merge의 전체 logical replacement 및 collapse 규칙을 같은 pure helper로 적용해야 한다.
그렇지 않으면 merge 참조가 있는 기존 invalid object의 hash가 달라져 가짜 신규 lint로
판정된다.

after store는 다음을 만족해야 한다.

- merge source 2개 부재
- survivor 2개 존재 및 canonical
- dangling reference 0
- 새 non-ID lint 0
- structured ID grandfather 문제는 원래 허용 집합의 부분집합
- ContextProjection source hash를 바꿔야 하는 상황은 사전 gate에서 중단

## Intermediate receipt와 pure ID 단계

기존 intermediate 검증은 update/rename만 transition으로 보고 merge source의 부재를 오류로
판정한다. merge decision은 별도 경로로 검증한다.

1. intermediate store에 source가 없어야 한다.
2. artifact `deletes`의 source `before_sha256`가 ledger source SHA와 같아야 한다.
3. artifact `updates`에 survivor가 정확히 하나 있어야 한다.
4. update `before_sha256`가 merge receipt의 target before SHA와 같아야 한다.
5. update `after_sha256`, live survivor SHA, merge receipt target after SHA,
   row canonical payload hash가 모두 같아야 한다.
6. reference collapse receipt와 intermediate live referrer 배열이 exact해야 한다.
7. merge source는 later `id_renames`에 포함하지 않는다.

이 검증 뒤 trusted receipt는 남은 pure ID rename map만 반환한다. merge source가 이미
없어도 classification 156행과 ledger 156행의 원본 binding은 artifact delete receipt로
계속 증명된다.

## Atomicity와 recovery

merge는 기존 `MutationOperation.CANONICAL_REPAIR` transaction 하나에 포함된다.

- plan과 apply 사이 live replan byte equality를 유지한다.
- stage write, parent binding, replacement, journal terminal state, rollback 경로를 재사용한다.
- source delete와 survivor/referrer update는 한 transaction에서 원자적으로 적용된다.
- apply 중 fault injection에서 source만 삭제되거나 survivor만 갱신된 상태가 최종 상태로
  남으면 안 된다.
- recovery 뒤에는 전체 before 또는 전체 after 중 하나만 허용한다.

## 엔진 SHA 변경 뒤 Task 7/8 재바인딩

Task 8A 엔진 코드가 review PASS되고 새 ENGINE_SHA가 확정되면 기존 Task 7 산출물은 stale다.
실코퍼스 object를 바꾸기 전에 다음을 수행한다.

1. 기존 pre-snapshot, Phase A JSON 3개, workbook, 관련 receipts를 Git 밖 receipts 아래에
   raw bytes와 manifest SHA를 보존해 archive한다.
2. scanner/test bytes가 review된 값과 같은지 확인하고 scanner 합성 회귀를 다시 돌린다.
3. 새 ENGINE_SHA로 exact-path pre-snapshot을 다시 만들고 전체 11,134개 파일을 검증한다.
4. 기존 live Phase A JSON 3개를 recoverable archive한 뒤 exact scanner로 다시 생성한다.
5. 새 classification SHA, engine SHA, repo HEAD, corpus fingerprint binding을 검증한다.
6. 기존 workbook을 archive하고 exact `--review-workbook` CLI로 새 workbook을 만든다.
7. object/eval/index/stale/journal과 사용자 dirt가 기존 baseline과 exact인지 확인한다.
8. 새 workbook으로 156행 ledger를 작성한다. collision 두 행은
   `collision_merge_into_existing`을 쓴다.
9. strict parser와 read-only plan으로 merge 2, repair 5, later pure ID map, eval closure를
   검증한다.
10. 독립 semantic/code review 뒤 exact ledger bytes를 사용자 승인 게이트 1에 제시한다.

사용자 승인 전에는 Task 9 apply를 시작하지 않는다. ledger bytes가 바뀌면 승인은 무효다.

## 테스트 전략

모든 production 변경은 RED를 먼저 확인한다.

### Ledger와 endpoint

- merge target missing
- merge target이 다른 decision source
- merge target kind/context/key/review_record mismatch
- merge endpoint overlap 또는 duplicate
- merge action count가 2가 아님
- merge target canonical invalid
- provenance `source_object_id(s)` reference 존재
- ContextProjection reference 존재

### Payload

- target-authoritative 본문 유지
- target-first stable union 및 source-only 근거 보존
- exact-equality field mismatch
- source-only/target-only unknown field
- malformed 또는 pre-duplicate list
- `history_coverage` 보수적 선택
- conflicting keyed caveat fail-closed

### Reference와 receipt

- source-only scalar/list 제자리 치환
- source+target list에서 source 제거와 상대 순서 보존
- source 또는 target pre-duplicate 거부
- bundle collapse가 가짜 pointer rewrite를 만들지 않음
- merge receipt가 before/after list와 removed index를 exact 기록
- drone DecisionRecord 두 개의 일반 rewrite가 exact 기록

### Mutation과 artifact

- merge source는 delete, survivor/referrer는 update, merge target create/rename 0
- intent/delete/create/rename endpoint 불일치 거부
- survivor/referrer payload tamper 거부
- merge target/source precondition drift 거부
- grandfather normalization이 merge replacement/collapse를 반영
- 기존 intent 없는 existing-target merge와 delete-only 거부 유지
- manifest/canonical artifact byte tamper 거부

### Intermediate와 fault recovery

- source 부재 + delete receipt + survivor update receipt가 valid할 때 pure ID map 반환
- delete/update/row/collapse SHA 하나씩 변조 시 거부
- fault injection 각 단계에서 rollback/recovery 후 whole-before 또는 whole-after만 존재
- 중단 후 재실행 idempotency와 live replan exact

### 전체 회귀

- `.venv/bin/python -m pytest -q`
- `.venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'`
- 새 ENGINE_SHA rebind 뒤 BB2 `brain/checks` 회귀
- 색인 입력·임베딩 계약은 바뀌지 않으므로 Task 8A 시점에는 실모델 rebuild를 하지 않는다.

## 완료 기준

- 새 action과 merge helper가 TDD로 구현되고 task review가 clean이다.
- 전체 엔진 합성 회귀와 ingest runtime unittest가 통과한다.
- canonical artifact가 merge source delete, survivor update, list collapse를 거짓 없이 증명한다.
- intermediate receipt가 merge source 부재를 정상 transition으로 검증한다.
- later pure ID map에 merge source가 없다.
- 기존 journal schema와 recovery가 유지된다.
- 새 ENGINE_SHA에 snapshot, Phase A, workbook이 다시 묶인다.
- 156행 ledger가 unresolved 0, target collision 0으로 strict validator와 read-only plan을
  통과한다.
- BB2 object/eval/index/stale는 사용자 승인 게이트 전까지 byte-exact 불변이다.
- exact ledger bytes와 두 merge 결과를 사용자에게 제시하고 Task 9 전에 멈춘다.

