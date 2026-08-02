# Task 17 canonical ID 복구 설계

> 상태: **대화에서 승인한 설계의 문서 검토 대기본 — 구현 계획과 구현은 아직 시작하지 않음**
>
> 기준일: 2026-07-31
>
> 범위: Project Brain 엔진의 일반 복구 계약과 BB2 Task 17 실코퍼스 복구

이 문서는
[`2026-07-28-brain-ingest-recovery-design.md`](2026-07-28-brain-ingest-recovery-design.md)의
Task 17 및 ID-only migration 부분만 대체한다. Task 13~16의 완료 상태, snapshot,
commit과 나머지 복구 설계는 바꾸지 않는다.

무시되는 `.superpowers/sdd/` 아래의 기존 Task 17 수정 설계와 실행 계획은 조사
자료로만 취급한다. 특히 임시 파일의 hash만 남긴 증거 보존, 사용자 승인 없이
staging에서 live로 이어지는 흐름, `/brain` 아래 신규 파일의 Git stage 방법은 이
문서의 계약으로 교체한다.

이 문서가 승인됐다는 사실만으로 엔진 코드, BB2 corpus, index, stale-set, Git
stage·commit이 바뀌었다고 보지 않는다. 구현은 별도로 작성하고 승인받을 실행 계획을
따른다.

## 1. 확인된 기준선과 문제

Task 17 Phase A는 다음 두 Git 상태를 대상으로 한 읽기 전용 조사였다.

- engine:
  `90c53a70fdcc917ec5523129eee59918603f7489`
- BB2:
  `53671bce5e94edf38a7afa11706963581065fb0f`

현재까지 확인된 수치는 다음과 같다.

| 항목 | 수치 |
| --- | ---: |
| live objects | 10,943 |
| invalid objects | 155 |
| structured problems | 158 |
| object registry references | 153 files / 309 pointers |
| eval expected references | 3 |
| stale references | 36 IDs / 40 pointers |
| 안전한 ID-only closure | self rename 31 / affected objects 62 |
| 안전 closure 뒤 잔여 | invalid objects 125 / problems 128 |

Phase A의 분류 원장은 invalid source 155개와 target rename 때문에 함께 바뀌어야 하는
현재-valid single ReviewRecord 1개를 합친 156행이다.

| 분류 | 행 |
| --- | ---: |
| self ID one-to-one rename | 28 |
| target-derived single ReviewRecord rename | 11 |
| bundle reference-only rewrite | 1 |
| non-reference field correction | 4 |
| existing-target collision | 2 |
| semantic/canonical judgment | 110 |
| 합계 | 156 |

기존 Task 17 계획처럼 ID와 등록 참조만 바꾸는 작업으로는 전체를 끝낼 수 없다.

- 현재 필드만으로 canonical target을 정할 수 없는 행이 121개다.
- 그중 CodeLocator, EvidenceRef, GlossaryTerm 109개는 path, symbol, title,
  context와 evidence를 함께 보고 사람이 canonical ID를 정해야 한다.
- Sally DomainMapping 4개는 self ID뿐 아니라 ID에서 투영되는 `/mapping_key`도
  함께 고쳐야 한다.
- 위 GlossaryTerm target에 종속된 single ReviewRecord 8개는 target이 정해져야
  self ID를 계산할 수 있다.
- payload가 서로 다른 existing-target collision 2개는 overwrite나 자동 merge를
  할 수 없다.
- mixed-kind ReviewRecord 1개는 단순 reference rewrite 뒤에도 구조 검증을
  통과하지 않으므로 승인된 shape repair가 필요하다.

따라서 기존 strict ID migration은 유지하되, ID-only로 표현할 수 없는 다섯 객체를
처리하는 제한된 `canonical_repair`를 그 앞에 둔다.

기존 Phase A 임시 산출물은 영구 증거로 쓰지 않지만, 재생성 결과를 대조할 provenance로
다음 SHA-256을 기록한다.

| 기존 임시 산출물 | SHA-256 |
| --- | --- |
| `measurement.json` | `5834e968a5249fc8a77205da5f1f210aa73829f52164c9536b9b8c48e2f6a78f` |
| `classification.json` | `7015e145848b8b69fbb173d89119d3fdc42d33cda29a68be12b45fa9c9fcbe48` |
| `feasibility.json` | `8036e9aa4ba94592409902706659faf997397ec43611f993cb1bd36dc7eb7669` |

새 scanner가 provenance용 metadata를 추가해 bytes가 달라질 수 있으므로 위 SHA를
새 파일의 예상 SHA로 하드코딩하지 않는다. 대신 기존 JSON을 decoder로 읽은 semantic
projection과 새 JSON의 분류·수치·source SHA를 exact 비교한다. 기존 임시 파일을
읽을 수 없더라도 새 durable evidence 생성은 가능해야 하며, 이 경우 기존
Phase A report의 수치와 현재 corpus를 교차 확인한다.

## 2. 목표와 제외 범위

### 2.1 목표

1. strict ID grammar와 `validate_id_fields`를 완화하지 않는다.
2. corpus별 의미 판단을 엔진 정책과 분리된 결정 원장으로 남긴다.
3. 모든 Phase A 증거를 임시 디렉터리가 아닌 BB2 recovery bundle에서 재현하고
   Git으로 보존한다.
4. ID-only 밖의 변화는 DomainMapping 4개와 mixed-kind ReviewRecord 1개에 필요한
   최소 field diff로 제한한다.
5. canonical repair와 ID-only migration 사이에 검증된 intermediate snapshot을
   둔다.
6. 최종 상태에서 structured ID problem과 dangling reference를 각각 0으로 만든다.
7. engine SHA, snapshot, corpus fingerprint, source object hash, 결정 원장과
   mutation manifest를 서로 묶어 drift를 fail-closed로 막는다.
8. Task 13~16의 결과와 engine 원본 checkout 및 BB2의 기존 사용자 변경을 그대로
   보존한다.

### 2.2 하지 않는 것

- ID 문법이나 projected-field 검증 완화
- generic slugify 또는 legacy ID 예외 목록 도입
- existing target overwrite
- payload가 다른 객체의 자동 merge, supersede, split
- 결정 원장 밖의 의미, title, evidence, code 좌표, quote, 검수 상태 변경
- index 또는 stale-set의 문자열 치환
- Task 18 display migration
- 전면 quote 보강
- push, merge, PR 생성
- 사용자가 이미 복구했다고 밝힌 터미널 권한의 재진단·재검증

## 3. 산출물과 책임 경계

### 3.1 Project Brain 엔진

엔진은 corpus의 canonical ID를 고르지 않는다. 승인된 입력이 허용된 변화인지
검증하고, 원자적으로 계획·적용·복구하는 일반 기능만 맡는다.

- `src/project_brain/canonical_repair.py`
  - 결정 원장 decoding과 pre-repair corpus 대조
  - canonical repair plan, artifact, apply
  - snapshot, engine, corpus, ledger binding
- `src/project_brain/mutation.py`
  - `MutationOperation.CANONICAL_REPAIR`
  - 허용 pointer와 exact before/after diff 검증
  - target-derived single ReviewRecord ID-only closure
- `src/project_brain/migration.py`
  - 기존 ID-only 계약 유지
  - target-derived ReviewRecord의 좁은 예외만 추가
- `src/project_brain/snapshot.py`
  - engine clean receipt와 사용자 dirt content receipt
  - snapshot의 engine/BB2 HEAD 및 manifest binding
- `src/project_brain/corpus_io.py`
  - 기존 caller 동작을 유지하는 stable sibling lock의 fail-fast 옵션
- `src/project_brain/cli.py`
  - `migration canonical-repair plan|apply`
  - 기존 `migration id plan|apply` 유지

엔진 테스트와 canonical design 및 roadmap 갱신도 같은 engine commit에 포함한다.
새 engine commit이 만들어진 뒤에는 그 SHA를 사용하는 새 pre-Task17 snapshot을
만든다. 이전 engine SHA에 묶인 post-ingame snapshot을 새 mutation receipt로
재사용하지 않는다.

### 3.2 BB2 읽기 전용 Phase A scanner와 증거

BB2 recovery bundle에는 다음 파일을 보존한다.

```text
brain/recovery/2026-07-28/id-migration/
├── scan_task17.py
├── test_scan_task17.py
├── phase-a-measurement.json
├── phase-a-classification.json
├── phase-a-feasibility.json
├── canonicalization-decisions.json
├── run_task17_live.py
└── test_run_task17_live.py
```

기존 `/private/tmp/project-brain-task17-phase-a-engine90-20260730/`의 JSON 세 개를
그대로 복사하지 않는다. 먼저 현재 corpus를 읽기만 하는 `scan_task17.py`와 합성
fixture 테스트를 검토한다. 그 scanner를 고정된 engine/BB2 기준선에서 실행해
measurement, classification, feasibility를 다시 생성한다.

재생성 결과는 다음을 만족해야 한다.

- invalid source 155개와 dependent valid ReviewRecord 1개, 합계 156행
- 행 중복과 누락 0
- source object canonical bytes SHA 포함
- engine SHA, BB2 HEAD, corpus fingerprint 포함
- 기존 Phase A 수치와 일치
- 차이가 있으면 기존 수치에 맞추지 않고 drift로 중단한 뒤 다시 설계

scanner는 분석과 분류만 한다. 새 ID, collision 처리, shape 변경을 자동으로
결정하지 않는다.

### 3.3 Canonicalization decision ledger

`canonicalization-decisions.json`은 이번 BB2 corpus에만 적용되는 사람이 검토한
정본 입력이다. Phase A classification 156행을 정확히 한 번씩 덮는다.

각 행은 최소한 다음을 가진다.

```json
{
  "source_id": "mapping.sally-canoe.enter-popup-flow.state-machine",
  "source_kind": "DomainMapping",
  "source_sha256": "64 lowercase hex",
  "action": "projected_field_repair",
  "new_id": "mapping.sally-canoe.enter-popup-flow-state-machine",
  "field_changes": [
    {
      "pointer": "/mapping_key",
      "before": "enter-popup-flow.state-machine",
      "after": "enter-popup-flow-state-machine"
    }
  ],
  "decision_reason": "mapping_key must equal the parsed DomainMapping key",
  "decision_evidence": [
    "brain/recovery/2026-07-28/id-migration/phase-a-classification.json"
  ]
}
```

허용 action은 다음 여섯 개뿐이다.

- `id_only_rename`
- `target_derived_review_rename`
- `reference_only`
- `projected_field_repair`
- `review_shape_repair`
- `collision_distinct_rename`

원장 validator는 다음을 보장한다.

- Phase A source 156개를 중복·누락 없이 exact coverage
- source ID, kind, source SHA가 Phase A와 exact
- 새 ID가 필요한 행은 모두 non-empty
- pure rename target은 one-to-one이고 current store에 없음
- `reference_only`는 self ID를 바꾸지 않음
- `projected_field_repair`는 이번 corpus의 DomainMapping `/mapping_key`만 허용
- `review_shape_repair`는 exact before/after와 판단 근거를 기록
- collision 2개는 payload 비교 결과와 서로 다른 비어 있는 canonical ID를 기록
- merge나 supersede가 필요하다는 결론이면 별도 의미 변경 승인을 받기 전 Task 17 중단

109개 ID는 문법상 가능한 문자열을 자동 선택하지 않는다. source object와 path,
symbol, title, context, evidence를 함께 검토한 이유를 행마다 남긴다. Sally
DomainMapping 4개의 mapping key와 mixed-kind ReviewRecord 1개의 shape 변화도
원장에 명시한다. 종속 ReviewRecord ID는 승인된 target ID에서 결정론적으로
계산하되 결과를 원장에 고정한다.

### 3.4 BB2 live runner

`run_task17_live.py`는 승인된 원장과 검증된 engine artifact만 소비하는 BB2 전용
one-shot coordinator다.

runner는 다음을 하지 않는다.

- canonical ID 추론
- 원장 자동 보충
- collision merge 또는 overwrite
- 독립 CLI 프로세스를 셸로 이어 붙여 lock을 흉내 내기
- 실패 뒤 Git reset, amend, revert

runner는 하나의 stable sibling lock을 잡은 상태에서 live preflight, 두 mutation,
intermediate snapshot, ID-only live replan equality, index rebuild, 실코퍼스 검증,
commit 전 실패 복구를 조정한다.

## 4. 두 mutation의 계약

### 4.1 제한된 canonical repair

`canonical_repair`는 ID-only로 표현할 수 없는 다섯 객체만 처리한다.

- Sally DomainMapping 4개
  - self `id`
  - `/mapping_key`
- mixed-kind ReviewRecord 1개
  - 승인된 self `id`
  - 승인된 `/target_object_ids`

모든 객체에서 공통으로 허용되는 변화는 self ID와 등록된 registry reference의
old→new 치환뿐이다. reason별 추가 변화는 위 pointer에 한정한다.

DomainMapping의 after `mapping_key`는 parsed new ID key와 exact여야 한다.
ReviewRecord repair는 다음을 추가로 보장한다.

- `review_scope`, `bundle_key`, `confirmation_key`, `review_type` 불변
- source ID는 소문자로 바꿔 같은 `bundle_key`의 bundle ReviewRecord로 파싱되는
  대소문자 부채 철자이거나, 원래 ID가 ReviewRecord로 파싱되지 않고
  `target_object_id`도 없는 byte-exact
  `review.{bundle_key.removeprefix('bundle.')}` 철자
- 문법 파싱을 먼저 적용해 `review.context.neutral` 같은 유효한 single ReviewRecord를
  bundle ReviewRecord source로 다시 해석하지 않음
- new self ID가 불변 `bundle_key`에서 계산한 bundle ReviewRecord ID와 exact
- after target이 non-empty이고 모두 같은 context의 canonical DomainMapping
- before에 실재하는 DomainMapping target은 승인된 rename으로 exact 보존
- grammar가 허용하지 않는 non-DomainMapping target만 승인된 diff로 제거 가능
- dangling target, target 추가, 무관한 mapping 교체, 순서만 바꾸는 no-op 거부

status, title, meaning, canonical summary, evidence 의미, code 좌표, quote,
verified_at과 임의 JSON pointer 변경은 거부한다. planner를 거치지 않고
`MutationService`를 직접 부른 경우에도 같은 exact diff 검증을 다시 수행한다.

canonical repair가 끝난 intermediate 상태는 다음을 만족해야 한다.

- 다섯 대상 canonical
- 기존 158 problems에서 정확히 repair 대상 문제만 감소
- 남은 grandfathered ID problems의 object ID와 problem text exact
- 원장에 열거된 self ID, registry reference, 허용 pointer 밖 payload diff 0
- dangling 0
- 새 non-ID lint problem 0

### 4.2 ID-only migration

나머지 행은 기존 `plan_id_migration`과 apply 계약으로 처리한다. rename 수를
하드코딩하지 않고 승인된 원장에서 결정론적으로 계산한다.

현재-valid single ReviewRecord는 아래 조건을 모두 만족할 때만 target-derived
closure에 포함할 수 있다.

1. kind가 `ReviewRecord`
2. parsed ID가 single ReviewRecord variant
3. `review_scope`가 없거나 exact `single_object`
4. old object가 현재 `validate_object_id`를 통과
5. old self ID가 exact `review.<old target_object_id>`
6. target ID가 같은 rename map에서 old→new로 바뀜
7. new self ID가 exact `review.<new target_object_id>`
8. self ID와 등록 reference 밖 payload 변화 0
9. source/target one-to-one이고 target이 비어 있음

일반 valid object, bundle ReviewRecord, 독립 valid ReviewRecord rename은 계속
거부한다.

최종 ID-only gate는 다음과 같다.

- structured ID problem 0
- canonical payload hash 전수 일치
- one-to-one rename
- target pre-existence 0
- dangling 0
- ID와 등록 reference 밖 payload 변화 0

## 5. 명시적인 사용자 승인 게이트

Task 17은 자동으로 끝까지 실행하지 않는다. 아래 두 지점에서 사용자 승인이
필수다.

### 승인 게이트 1 — 의미 결정 승인

다음이 준비되고 검토된 뒤 멈춘다.

- 새 engine 구현, 전체 엔진 테스트, 코드 리뷰, clean engine commit
- 검토된 read-only scanner와 합성 테스트
- 현재 corpus에서 재생성한 Phase A 증거 세 개
- Phase A 156행을 전부 덮는 canonicalization decision ledger
- 109개 사람 검토 ID와 근거
- Sally DomainMapping 4개의 ID와 mapping key
- collision 2개의 distinct canonical ID와 payload 비교 결과
- mixed-kind ReviewRecord의 exact shape repair
- 종속 ReviewRecord의 결정론적 target-derived ID

사용자는 위 ledger 전체를 검토하고 승인한다. 승인 전에는 canonical repair
staging도 만들지 않는다. 원장이 바뀌면 SHA가 바뀌므로 이전 승인은 무효이며 다시
승인받는다.

### 승인 게이트 2 — live 적용 승인

승인된 원장으로 byte-exact staging 전체를 만든 뒤 다음 증거를 제시하고 멈춘다.

- canonical repair와 ID-only manifest 및 SHA
- intermediate snapshot create/verify receipt
- 최종 staging의 ID problem 0, dangling 0, payload drift 0
- audit, lint, 실코퍼스 checks의 실제 통과 출력과 skipped 0
- eval 15/15
- staging의 격리된 색인 검증 결과와 live real-model rebuild 입력 계약
- live corpus/index/stale, BB2 HEAD, engine SHA, 사용자 dirt가 아직 preflight
  기준선과 exact라는 receipt

사용자의 두 번째 명시적 승인 전에는 stable live lock을 잡거나 live corpus,
index, stale-set을 바꾸지 않는다. staging 결과나 manifest가 바뀌면 다시 검증하고
재승인받는다.

## 6. 실행 흐름

### 6.1 Engine과 durable evidence

1. engine 기능을 TDD로 구현하고 합성 회귀를 모두 통과시킨다.
2. 코드 리뷰와 필요한 수정을 끝낸 뒤 engine 변경만 commit한다.
3. engine HEAD와 tracked, staged, non-ignored untracked 상태가 clean인지 고정한다.
4. post-ingame snapshot의 corpus/index/stale와 live 상태가 byte-exact인지
   확인한다.
5. 새 engine SHA와 기존 BB2 HEAD에 묶인 pre-Task17 snapshot을 만들고 external
   manifest SHA로 explicit verify한다.
6. read-only scanner를 검토·테스트한 뒤 Phase A 증거를 현재 corpus에서
   재생성한다.
7. 156행 decision ledger를 완성하고 승인 게이트 1에서 멈춘다.

### 6.2 Byte-exact staging

1. 승인된 ledger SHA, Phase A SHA, engine SHA, pre-Task17 snapshot과 corpus
   fingerprint를 다시 대조한다.
2. verified BB2 root 안의 기존 ignore 대상인 `.snapshots` 아래에 anchored
   no-follow 방식으로 staging을 만든다. live `brain`과 같은 경로, 상위·하위,
   symlink alias는 거부한다.
3. staging에서 canonical repair plan/apply를 실행한다.
4. intermediate snapshot을 만들고 external manifest SHA로 verify한다.
5. intermediate snapshot과 ledger에서 ID-only rename map을 계산한다.
6. ID-only plan/apply를 실행한다.
7. audit, lint, checks, eval과 targeted query/recall 회귀를 수행한다.
8. live와 사용자 dirt가 불변인지 확인하고 승인 게이트 2에서 멈춘다.

staging 실패는 staging만 폐기한다. 이 단계에서는 live를 바꾸지 않았으므로 live
restore를 실행하지 않는다.

### 6.3 Stable-lock live 적용

두 번째 승인 뒤 one-shot runner가 다음을 수행한다.

1. stable sibling lock을 fail-fast로 획득한다. 이미 점유 중이면 기다리지 않고
   `corpus_lock_busy`로 중단한다.
2. lock 안에서 engine SHA/clean 상태, BB2 HEAD, live fingerprint, snapshot,
   ledger/manifest SHA, 사용자 dirt content receipt를 재확인한다.
3. live canonical repair를 적용한다.
4. 즉시 intermediate snapshot을 만들고 explicit verify한다.
5. ID-only artifact를 이 live intermediate snapshot ID와 external manifest
   SHA에 새로 묶는다.
6. lock을 유지한 채 별도 staging child에서 ID-only manifest를 재생성하고 승인된
   staging manifest와 byte-exact인지 확인한다.
7. live ID-only migration을 적용한다.
8. index와 stale-set을 문자열 치환하지 않고 invalidate한 뒤 실제
   `BAAI/bge-m3`로 한 번 rebuild한다.
9. audit, lint, 실코퍼스 checks, eval 15/15와 targeted recall을 다시 실행한다.
10. commit 대상과 사용자 dirt 보존을 확인한다.

canonical repair와 ID-only migration은 manifest와 intermediate snapshot 경계를
분리하지만 BB2에서는 하나의 Task 17 commit으로 묶는다.

## 7. Drift, 실패, 복구

### 7.1 첫 write 전 실패

다음 중 하나라도 달라지면 첫 write 전에 중단한다.

- engine SHA 또는 clean status
- BB2 HEAD
- trusted snapshot ID 또는 external manifest SHA
- corpus/index/stale fingerprint
- Phase A, decision ledger, mutation manifest SHA
- source object SHA
- engine 원본 checkout 또는 BB2 사용자 dirt의 status/content receipt

권한 상태는 Task 17의 drift receipt가 아니다. 이번 작업에서는 사용자의 요청대로
터미널 권한을 재검증하지 않는다.

### 7.2 Live commit 전 실패

live canonical repair가 시작된 뒤 BB2 Task 17 commit 전까지 실패하면 stable lock을
유지한 채 verified pre-Task17 snapshot 전체를 복원한다.

- restore 범위는 snapshot이 선언한 brain corpus, index, stale-set뿐이다.
- Git history와 사용자 dirt는 restore하지 않는다.
- restore 뒤 corpus/index/stale fingerprint가 snapshot과 exact인지 확인한다.
- snapshot index가 exact하면 rebuild하지 않는다.
- Task 13~16 ancestry와 사용자 dirt receipt도 다시 확인한다.

### 7.3 BB2 commit 뒤 실패

BB2 Task 17 commit 뒤 final snapshot 또는 external binding receipt 생성이 실패해도
commit을 reset, amend, revert하지 않는다. 같은 HEAD와 이미 검증한 live 상태를
유지하고 Task 17을 incomplete, Task 18을 blocked로 둔다. 원인을 고친 뒤 같은
HEAD에서 final snapshot과 receipt만 재시도한다.

post-commit corpus/index/stale drift가 발견되면 자동 수정하지 않고 별도 복구 승인을
받을 때까지 중단한다.

## 8. Git과 사용자 변경 보존

engine 원본 checkout과 BB2의 기존 dirty 상태는 사용자 소유다. raw porcelain hash만
비교하지 않고 각 status record가 가리키는 lexical path의 type, mode, size,
regular-file bytes 또는 symlink target SHA까지 content receipt로 고정한다.
Task 17 allowlist만 별도로 제외하고 preflight, live 적용 전, commit 전후, final
binding에서 exact 비교한다.

BB2의 `/brain`은 `.git/info/exclude`로 무시된다. 따라서 새 recovery 파일을 일반
`git add`로 stage하면 누락될 수 있다. BB2 Task 17 commit은 다음 원칙을 지킨다.

- allowlist를 NUL-delimited pathspec 파일로 만든다.
- `git add -f --pathspec-from-file=<file> --pathspec-file-nul`을 사용한다.
- broad `git add`, `git add brain`, `git add -A`는 사용하지 않는다.
- staged path를 allowlist와 byte-exact 비교한다.
- commit parent가 Task 16 BB2 HEAD인지 확인한다.
- 기존 사용자 staged/unstaged/untracked 파일은 commit에 넣지 않는다.

engine도 exact path만 stage하며 설계와 구현 commit을 섞지 않는다.

## 9. 테스트와 완료 기준

### 9.1 Engine TDD와 회귀

최소한 다음 합성 테스트를 red부터 추가한다.

- DomainMapping ID + `/mapping_key` exact repair PASS
- 허용되지 않은 meaning/title/evidence 변화 FAIL
- 원장에 없는 pointer 또는 source SHA drift FAIL
- existing target, merge, delete-only FAIL
- mixed ReviewRecord의 승인된 exact shape repair PASS
- ReviewRecord의 상태나 근거 변화 FAIL
- target-derived valid single ReviewRecord exact rename PASS
- 일반 valid object, bundle ReviewRecord, 독립 ReviewRecord rename FAIL
- snapshot, engine SHA, ledger SHA, corpus fingerprint drift FAIL
- engine tracked/staged/non-ignored untracked dirt FAIL
- partial write rollback
- stable lock busy fail-fast
- runner failure injection마다 pre-Task17 corpus/index/stale exact restore
- 사용자 status가 같아도 file bytes나 symlink target이 바뀌면 FAIL
- staging parent/child symlink 및 path binding replacement FAIL

필수 엔진 회귀는 다음 둘이다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m pytest -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m unittest discover \
  -s "$ENGINE/src/project_brain/templates/ingest/scripts" -p 'test_*.py'
```

실코퍼스 checks는 exact engine interpreter와 `PYTHONPATH`를 사용한다. 출력에
`RealCorpusRebuildGuard.test_rebuild_row_counts ... ok`가 실제로 있어야 하며
skipped는 0이어야 한다. bare CLI가 없어 skip된 exit 0은 PASS가 아니다.

staging과 live에서 audit, lint, checks, eval을 각각 확인한다. staging 색인 검증은
live DB를 건드리지 않는 격리 경로에서 수행하며 그 방식과 결과를 승인 게이트 2에
기록한다. 실제 live index rebuild는 ambient `PROJECT_BRAIN_EMBEDDER`가 unset인
상태에서 `BAAI/bge-m3`로 한 번만 실행한다. staging 검증을 이유로 live rebuild를
미리 실행하지 않는다.

### 9.2 Task 17 완료 조건

다음을 모두 만족해야 Task 17을 완료로 본다.

- engine 구현과 문서가 review된 clean engine commit에 있음
- durable Phase A scanner, 테스트, 증거 세 개가 BB2 commit에 포함됨
- 156행 decision ledger의 누락·중복·미결정 0
- 사용자 승인 게이트 1과 2가 각각 명시적으로 기록됨
- staging과 live의 canonical repair/ID-only manifest가 승인된 bytes와 exact
- 최종 structured ID problem 0
- 최종 dangling reference 0
- 허용 범위 밖 payload drift 0
- 실코퍼스 checks skipped 0, eval 15/15
- 실제 `BAAI/bge-m3` index rebuild 완료
- BB2 Task 17 exact-path commit 완료
- commit을 포함한 final full snapshot create/verify 완료
- final snapshot 바깥의 Task 18 binding receipt가 BB2 HEAD, engine SHA,
  corpus/index/stale fingerprint, 사용자 dirt receipt를 고정

final snapshot이나 binding이 끝나기 전에는 코드와 corpus가 올바르더라도 Task 17은
incomplete다. 이 설계의 완료 범위에는 push, merge와 Task 18 실행이 포함되지 않는다.
