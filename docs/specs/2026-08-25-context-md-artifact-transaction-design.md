# context_md ContextProjection 객체·생성 파일 생명주기 설계

- 작성일: 2026-08-25
- 상태: 설계복귀 후보 2 — 독립 검수 전, 검수 1/3·설계복귀 1/1
- 선행 계약: [evidence preparation 핵심](2026-08-25-evidence-preparation-repair-design.md)
- 대상: GitHub #38, `ContextProjection(format=context_md)`와 생성 `docs/contexts/generated/**/CONTEXT.md`

## 1. 이름과 범위

`context_md`는 파일명이 아니라 `ContextProjection.format` 값이다. `ContextProjection` JSON 객체는
brain root에 있고, 생성 Markdown artifact는 consumer repo root의
`docs/contexts/generated/**/CONTEXT.md`에 있다. 루트의 수동 `CONTEXT.md`와 지식 초안
`brain/drafts/<topic-id>.md`는 이 설계의 입력·출력·삭제 대상이 아니다.

이 설계는 현재 내부 함수인 `build_context_projection()`을 전용 공개 명령에 연결하고 JSON 객체와
생성 파일의 create/update/delete/no-change, 누락 파일 복구, locator 이동, rollback, crash recovery를
한 transaction으로 닫는다. `prompt_payload`, CurrentView·KnowledgePage·Insight builder, 서로 다른
filesystem을 잇는 2단계 복구는 범위 밖이다.

## 2. config와 두 root 결속

```text
project-brain projection build-context \
  --context-id <id> \
  --output docs/contexts/generated/<context-key>/CONTEXT.md \
  --evidence-plan-file <canonical-json-path> \
  [--project-config <absolute-.project-brain.json>] \
  [--brain-root <absolute-path>]

project-brain projection delete-context \
  --projection-id <id> \
  --expected-output docs/contexts/generated/<context-key>/CONTEXT.md \
  [--project-config <absolute-.project-brain.json>] \
  [--brain-root <absolute-path>]
```

consumer root를 소유하는 `.project-brain.json`은 두 명령에서 필수다. `--project-config`가 없으면 현재
디렉터리부터 기존 discovery로 하나만 찾는다. config의 parent가 consumer root다. `--brain-root`가
없으면 config 값을 쓰고, 있으면 config가 가리키는 brain root와 path·device·inode가 정확히 같아야
한다. 명시 brain root가 config를 우회해 다른 consumer root를 고르는 경로는 없다.

config는 symlink·비정규 파일·hardlink를 거부하고 anchored no-follow read 두 번의 metadata와 bytes가
같아야 한다. config snapshot exact key는 `path`, `device`, `inode`, `link_count`, `mode`, `size`,
`bytes_sha256`이다. root binding exact key는 `kind`, `selector`, `path`, `parent_bindings`, `device`,
`inode`이며 `kind`는 `brain|consumer`, brain selector는 `config|explicit_match`, consumer selector는
`owning_config`다. `parent_bindings`는 lexical parent부터 root direct parent까지 exact
`path`, `device`, `inode` 배열이다.

준비 identity에는 config snapshot과 두 root binding을 넣는다. root binding은 lexical parent부터 root까지
각 component의 path·device·inode도 함께 가진다. apply lock 안에서 다시 관측해 config, parent binding,
root 중 하나가 바뀌었으면 journal 전에 `projection_artifact_snapshot_changed`로 0-write 실패한다. 두
root의 `st_dev`가 다르면 `projection_artifact_filesystem_mismatch`로 실패한다.

artifact는 consumer root 기준 `docs/contexts/generated/**/CONTEXT.md` 정규 파일만 허용한다. 절대 경로,
`..`, symlink, hardlink, root 밖 해석, 한 plan의 중복 destination, 다른 projection이 소유한 destination을
거부한다. 모든 read/write/delete는 root pin에서 anchored open으로 수행한다. consumer root부터 leaf의
existing parent와 leaf는 모두 no-follow로 열고 `st_dev == brain root st_dev`인지 확인한다. 중간 mount나
다른 device component가 하나라도 있으면 `projection_artifact_mount_mismatch`로 journal 전 0-write다.

parent directory는 coordinator가 action으로 계획한다. `docs`는 미리 존재하는 실제 directory여야 한다.
그 아래 `contexts/generated/<context-key>/`에서 빠진 component만 얕은 순서로 mode `0755` create action을
만든다. existing component는 directory여야 하며 symlink·다른 device를 거부한다. rollback은 이
transaction이 만든 directory를 깊은 순서로, 기록한 device·inode가 같고 비어 있을 때만 지운다. 외부
entry가 생겼거나 identity가 다르면 덮어쓰거나 재귀 삭제하지 않고 `RECOVERY_REQUIRED`다.

delete의 `--expected-output`은 항상 필수다. object가 있으면 stored `output_locator`와 exact 같아야 하고,
object가 없으면 그 한 경로의 orphan 여부를 관측하는 데만 쓴다. object 없는 orphan을 이 인자로 지우지는
않는다. 다른 알 수 없는 locator의 orphan 전수 탐지는 lint/audit가 소유한다.

## 3. 객체와 artifact 상태표

artifact의 exact 정상 bytes는 현재 저장 객체의 `projection_hash`와 일치하는 UTF-8 content다.
`stale_policy=fail_on_manual_edit`이므로 존재하는 파일의 bytes가 이 hash와 다르면 수동 수정으로 본다.

| object 상태 | artifact 상태 | 요청 | object action | artifact action | 결과·시각 |
|---|---|---|---|---|---|
| 없음 | 없음 | build | create | create | object clock 1회 |
| fresh, locator A | exact A | 같은 build | no_change | no_change | byte-preserving, clock·journal 없음 |
| fresh, locator A | A 없음 | 같은 build | no_change | create | 누락 파일 복구, object 시각 보존 |
| fresh, locator A | A bytes drift | 같은 build | no_change | 없음 | `projection_artifact_manual_edit`, 0-write |
| stale/source 변경, locator A | exact old A | build A | update | update | object clock 1회 |
| stale/source 변경, locator A | A 없음 | build A | update | create | object clock 1회 |
| stale/source 변경, locator A | A bytes drift | build A | 없음 | 없음 | 수동 수정 보호, 0-write |
| locator A | exact A, B 없음 | build B | update | A delete+B create | object clock 1회, 한 transaction |
| locator A | A 없음·drift 또는 B 존재 | build B | 없음 | 없음 | precondition/collision 오류, 0-write |
| object 존재 | exact artifact | delete | delete | delete | 한 transaction, 새 object stamp 없음 |
| object 존재 | artifact 없음·drift | delete | 없음 | 없음 | `projection_artifact_delete_precondition_failed`, object 보존 |
| object 없음 | artifact 존재 | build/delete | 없음 | 없음 | `projection_artifact_orphan`, 0-write |
| 준비 뒤 object/source/config/root/artifact drift | 어떤 요청 | apply | 없음 | 없음 | `projection_artifact_snapshot_changed`, 0-write |

일반 build는 수동 수정 파일을 덮어쓰거나 지우지 않는다. 누락 artifact만 엔진이 저장 객체 또는 현재
reviewed source에서 다시 만든 exact bytes로 복구한다. locator A→B와 object delete는 A가 저장 hash와
정확히 맞을 때만 허용한다.

## 4. 전용 준비 handoff

`build_context_projection()`은 projected store의 reviewed DomainContext·GlossaryTerm·DomainMapping만
읽는 순수 builder다. coordinator는 #33의 `ContextProjectionBuildRequestV1`과 exact EvidencePlan entry를
evidence core에 넘기고 object-only `PreparedObjectPlanV1`을 받는다. target status, source IDs/hash,
projection hash, Markdown hash, `generated_by`, 실제 builder module identity가 모두 준비본과 proof에
결속된다.

coordinator가 만드는 `PreparedContextProjectionV1` exact key는 다음과 같다.

```text
version, operation, prepared_object, markdown_bytes,
prepared_config, root_bindings, artifact_actions,
sealed_identity_sha256
```

`operation=build|delete`다. build의 `prepared_object`는 #33 반환값이고 delete는 기존 object snapshot과
delete precondition이다. `prepared_object`는 operation으로 구분하는 tagged union이다.

- build는 #33 `PreparedObjectPlanV1` exact shape다.
- delete는 `PreparedContextDeleteV1`이며 exact key는 `version`, `operation`, `target_id`,
  `before_unstamped_sha256`, `output_locator`, `artifact_before_sha256`,
  `sealed_delete_identity_sha256`다. `operation=delete`이고 stored object bytes, locator, exact artifact bytes를
  결속하며 EvidencePlan·proof·ReviewRecord는 없다.

`artifact_actions`는 #38이 추가하며 evidence core에는 이 타입을 넣지 않는다.
receipt/report path와 bytes는 transaction ID와 committed manifest에서 뒤 단계가 파생하며 준비본에 넣지
않는다. 이 타입만 `MutationService.apply_context_projection()`에 들어갈 수 있고 generic ingest, 일반
`auxiliary_updates`, caller가 조립한 dict는 runtime type과 sealed identity 검증에서 거부한다.

## 5. journal과 recovery

brain corpus lock이 유일한 조정 lock이다. apply와 recovery는 다음 순서를 고정한다.

1. brain corpus lock을 잡는다.
2. brain root를 path·device·inode가 같은 open directory handle로 pin한다.
3. consumer root를 두 번째 open directory handle로 pin한다.
4. 준비본의 config·root·object·source·artifact snapshot과 같은 filesystem을 다시 확인한다.
5. brain root의 `.brain-local/transactions/<transaction-id>/`에 불변 `manifest.json`과 recovery
   `state.json`을 만든다.

consumer 전용 두 번째 lock은 만들지 않는다. root pin과 before hash precondition으로 외부 수정을
탐지하며, 모든 Project Brain artifact writer가 brain corpus lock을 사용한다.

manifest top-level exact key는 다음과 같다.

```text
version, transaction_id, operation, prepared_config, root_bindings,
object_actions, artifact_actions, index_actions,
before_corpus_fingerprint, sealed_identity_sha256
```

file action exact key는 `kind`, `root`, `path`, `action`, `before_exists`, `before_mode`, `before_sha256`,
`after_exists`, `after_mode`, `after_sha256`다. `kind=file`, action은 `create|update|delete|no_change`다.
mode는 permission bits이며 absent side는 mode와 SHA가 모두 null이다. directory action exact key는
`kind`, `root`, `path`, `action`, `before_exists`, `expected_mode`이고 `kind=directory`, action은
`create|no_change`다. `index_actions`는 brain-root-relative derived/index file을 같은 file action exact
shape로 펼친 배열이며 object bytes가 안 바뀌면 exact `[]`다. manifest action에는
절대 apply path를 저장하지 않고 root-relative path만 둔다. root binding의 recorded absolute root path는
recovery를 위해 남긴다. transaction ID는 자기 key만 제외한 manifest identity projection의
canonical SHA-256이고, sealed identity는 config·두 root selector·object/artifact/index actions를 결속한다.
canonical effect 순서는 directory create를 depth/path 순, object file을 target ID/path 순, artifact file을
path 순, index actions를 path 순으로 마지막에 둔다. before/after가 없으면 해당 SHA는 null이며 다른 생략 표현은
허용하지 않는다.

manifest file은 create-only 불변이다. `manifest_sha256`은 LF까지 포함한 canonical manifest file bytes
hash다. mutable `ProjectionArtifactTransactionStateV1` exact key는 `version`, `transaction_id`,
`manifest_sha256`, `phase`, `working_snapshots`, `next_action_index`, `applied_actions`다.
`next_action_index`는 null 또는 현재 effect의 0-based index, `applied_actions`는 완료된 index의
오름차순·중복 없는 배열이다. `working_snapshots` row exact key는 `action_index`, `before_path`,
`before_sha256`, `stage_path`, `stage_device`, `stage_inode`, `stage_sha256`, `moved_path`이며 적용되지 않는
값은 null이다. staged directory는 SHA 대신 device·inode를 쓴다. state update만
temp+fsync+atomic replace+directory fsync를 쓴다. 따라서 receipt/report가 manifest를 참조해도 manifest가
다시 그 bytes hash를 담는 순환이 없다.

manifest의 canonical action 순서로 각 index의 작업 path를 결정적으로 파생한다.

```text
before/<index>.bytes   # before copy
stage/<index>.leaf     # create/update after; update exchange 뒤에는 실제 old leaf
stage-dir/<index>/     # directory create용 미리 만든 exact inode
moved/<index>.leaf     # delete가 옮긴 실제 old leaf
```

모두 transaction directory 기준이다. before copy·stage file/directory를 만들고 metadata·bytes를
`working_snapshots`에 기록한 `prepared` state를 먼저 fsync한다. effect 전
`next_action_index=index` state를 fsync하고, effect와 관련 directory fsync·live after 재관측이 끝난 뒤
index를 `applied_actions`에 넣고 `next_action_index=null` state를 fsync한다.

file publish는 다음 알고리즘만 쓴다.

1. after bytes를 transaction `stage/<index>.leaf`에 create-only로 쓰고 stage directory를 fsync한다. 두
   root가 같은 device이므로 여기서 live destination으로 rename/exchange한다.
2. create는 platform atomic no-replace publish(`renameat2(RENAME_NOREPLACE)` 또는
   `renamex_np(RENAME_EXCL)`) 한 번으로 temp를 absent destination에 옮긴다.
3. update는 platform atomic exchange(`renameat2(RENAME_EXCHANGE)` 또는 `renamex_np(RENAME_SWAP)`)로
   temp와 live leaf를 바꾼다. temp로 옮겨진 실제 old leaf가 sealed before snapshot과 같은지 확인한다.
   다르면 live가 아직 이 transaction의 after hash일 때만 exchange를 되돌리고 실패한다.
4. delete는 live leaf를 journal backup path로 atomic no-replace rename한 뒤 실제 backup이 sealed before와
   같은지 확인한다. 다르면 destination이 비어 있을 때만 되돌린다.
5. 외부 writer가 destination을 선점했거나 live after bytes를 다시 바꿨으면 덮어쓰지 않고
   `RECOVERY_REQUIRED`다. 필요한 atomic primitive 지원 여부는 journal 전에 확인한다.

rollback도 live leaf가 이 transaction의 after identity와 같을 때만 atomic exchange/replace로 before를
복원한다. directory create는 transaction 안의 staged directory를 atomic no-replace rename하며, live
directory가 recorded staged device·inode와 같을 때만 이 transaction이 만든 것으로 본다. 이미 생긴
directory를 자기 action으로 채택하지 않는다.

여러 root·여러 leaf가 한 CPU 명령으로 동시에 바뀐다는 전역 atomic은 주장하지 않는다. 보장 범위는
각 leaf publish/delete가 원자적이고, 미완료 journal이 있으면 모든 Project Brain corpus read와 새
mutation이 recovery를 먼저 수행하며, recovery 뒤 안정 상태가 전체 before 또는 전체 after라는 것이다.
외부 도구가 lock을 무시하고 commit 중 여러 파일을 직접 읽는 것은 이 보장 밖이다.

phase exact enum은 `preparing|prepared|committing|committed|reported|rolled_back|recovery_required`다.
apply 순서는 manifest/state fsync → 서로 다른 `before/` copy와 `stage/` after temp fsync → `prepared` → `committing` →
directory/object/artifact/index action → 두 root fsync → after-image 검증 → `committed` → receipt/report
create-only publish → `reported`다.

- `preparing|prepared|committing`에서 실패·crash면 `applied_actions` 역순으로 두 root와 index를
  rollback한다. exact 복원이 끝나야 `rolled_back`이다.
- `next_action_index`가 남은 crash는 action별로 live와 working snapshot을 비교한다. create는
  `live=after + stage 없음`, update는 `live=after + stage=before`, delete는
  `live 없음 + moved=before`, directory create는 `live device/inode=recorded stage + stage 없음`이면 effect
  후다. 반대쪽 exact precondition과 stage after가 남아 있으면 effect 전이다. index action도 recorded
  before/after invalidation identity로 같은 판정을 한다. 어느 조합에도 exact하지 않거나 외부 bytes가
  섞였으면 `recovery_required`다. 이 규칙 때문에 leaf effect와 applied-state 기록 사이 crash도 빠지지
  않는다.
- `committed`는 object·artifact·index after 상태가 fsync·검증된 지점이다. 여기서는 절대 rollback하지
  않고, manifest에서 receipt/report exact bytes를 다시 계산해 absent 파일은 만들고 exact 파일은
  재사용한 뒤 `reported`로 진행한다.
- receipt/report bytes가 다르거나 committed live after가 다르면 `recovery_required`다. 외부 변경을
  덮어쓰거나 새 transaction ID로 다시 발급하지 않는다.
- `reported|rolled_back`은 terminal이다. exact no-change는 transaction·durable receipt/report 없이 stdout
  `outcome=no_changes`만 반환하고 재시도 때 상태표를 다시 판정한다.

따라서 object receipt 뒤, artifact receipt 뒤, report 뒤 state 변경 전 어느 지점에서 crash해도
`committed` tail을 같은 bytes로 앞으로 완성한다. commit 전 crash만 rollback한다.

crash recovery는 현재 config로 consumer root를 다시 해석하지 않는다. manifest에 결속된 path를 열어
기록된 device·inode와 비교하고 같은 root면 config가 없어졌거나 바뀌었어도 rollback/roll-forward를
끝낸다. bound root가 없거나 교체됐으면 journal을 삭제하거나 새 mutation을 시작하지 않고
`RECOVERY_REQUIRED`와 두 recorded root path를 보고한다. 사용자가 원래 root를 복구한 뒤 같은 brain
root로 다시 실행해야 한다.

준비 뒤 apply 전 config drift는 0-write 오류지만, partial apply 뒤 recovery에서는 config drift가
rollback을 막지 않는다. 이 둘을 같은 상태로 취급하지 않는다.

## 6. 효과·시각·receipt 소유자

- `build_context_projection()`은 reviewed source에서 object와 Markdown bytes를 만드는 순수 builder다.
- projection coordinator는 config/root/output 요청을 해석하고 evidence core에 object preparation을
  요청한다.
- `MutationService`만 corpus lock, 두 root pin, journal, apply, rollback/recovery를 소유한다.
- 설치 스킬, caller, 일반 `auxiliary_updates`, ID migration은 generated artifact를 쓰거나 지우지 않는다.

object create/update가 있을 때만 mutation clock을 정확히 한 번 호출해 `generated_at`과 object
`created_at`/`updated_at`에 같은 event time을 쓴다. artifact-only create는 object bytes·시각과 index를
보존한다. artifact에는 별도 시각을 넣지 않는다. object+artifact exact no-change에는 journal과 receipt가
없다.

`ProjectionArtifactReceiptV1` exact key는 `version`, `receipt_id`, `transaction_id`, `manifest_sha256`,
`root_bindings_sha256`, `actions`다. `receipt_id`는 자기 key만 제외한 canonical object hash다.
locator A→B는 artifact receipt 하나의 정렬된 `delete A`, `create B` action으로 묶는다.

`ProjectionArtifactTransactionReportV1` exact key는 `version`, `transaction_id`, `manifest_sha256`,
`root_bindings_sha256`, `object_actions`, `artifact_actions`, `index_actions`, `before_corpus_fingerprint`,
`after_corpus_fingerprint`, `object_receipt`, `artifact_receipt`, `outcome`이다. outcome은 `committed`다.
object/artifact receipt ref는 null 또는 exact `path`, `bytes_sha256`, `receipt_id`다.
receipt `actions`와 report의 `object_actions`·`artifact_actions`는 해당 manifest action의 exact key와
canonical 순서를 그대로 투영한다. receipt/report용 다른 action shape나 재정렬은 없다.

durable path는 brain root 아래 다음으로 고정한다.

```text
.brain-local/transactions/<transaction-id>/manifest.json
.brain-local/transactions/<transaction-id>/state.json
.brain-local/receipts/context-projection/<transaction-id>/object.json
.brain-local/receipts/context-projection/<transaction-id>/artifact.json
.brain-local/reports/context-projection/<transaction-id>.json
```

object bytes가 바뀔 때만 기존 mutation receipt와 index invalidation을 만들고, artifact action이 있을
때만 artifact receipt를 만든다. artifact-only 누락 복구는 object receipt·index 불변이고 artifact
receipt만 남긴다. report와 두 receipt는 같은 manifest SHA를 가져 다른 실행을 조합할 수 없다.

## 7. 90분 child 경계

한 writer가 다음 순서로 나누며 각 child는 90분을 넘기지 않는다.

1. C1 `context-dedicated-handoff`: #33 E14의 고정 profile·`PreparedObjectPlanV1`을 소비하는 coordinator 통합 — 완료 조건 1
2. C2 `context-root-action-plan`: config/root/path·parent/mount·directory action planner — 완료 조건 1·2
3. C3 `context-lifecycle-plan`: 순수 builder와 lifecycle state/action planner — 완료 조건 2·4
4. C4 `context-multiroot-apply`: multi-root leaf publish·pre-commit 역순 rollback — 완료 조건 3
5. C5 `context-committed-tail`: committed receipt/report tail·artifact-only index 분기 — 완료 조건 3·5
6. C6 `context-public-regression`: public build/delete, installer·lint·index와 failure injection·전체 회귀 — 완료 조건 4·5·6

admission PASS 뒤 구현 전에 각 stable ID로 별도 GitHub child issue와 progress block을 만든다. 한 child가
cross-device 2단계 복구, 수동 파일 merge, generic direct-reviewed 권한을 요구하면 즉시 중지하고 새
ticket으로 분리한다.

## 8. 완료 조건과 검증 연결

| 완료 조건 | 정확한 명령 | 기대 관측 |
|---|---|---|
| 1. 이름과 #33 handoff·config/root/path 계약이 전용 범위와 same-filesystem 경계를 fail-closed로 고정한다 | `.venv/bin/python -m pytest -q tests/test_projection_artifact_transaction.py -k 'handoff or config or root or path or filesystem or scope'` | 다섯 대상 구분, generic/direct-reviewed 우회·config 불일치·root drift·cross-device·path escape가 journal 전 0-write |
| 2. 상태표가 create/update/no-change/missing/manual edit/delete/locator 이동/orphan·collision을 유일하게 정한다 | `.venv/bin/python -m pytest -q tests/test_projection_artifact_transaction.py -k 'create or update or no_change or missing or manual_edit or rename or delete or orphan or collision'` | 표의 object/artifact action과 object 시각 횟수가 exact 일치 |
| 3. 단일 lock·두 root pin·journal이 실패 주입과 crash recovery에서 rollback/roll-forward를 유일하게 정한다 | `.venv/bin/python -m pytest -q tests/test_projection_artifact_transaction.py tests/test_corpus_io.py -k 'rollback or recovery or failure_injection or root_pin or crash_tail or atomic_exchange'` | pre-commit은 두 root 원복, committed는 receipt/report exact roll-forward, after/conflict 손상은 RECOVERY_REQUIRED |
| 4. public builder와 delete가 실제 reviewed source로 객체·Markdown을 함께 관리한다 | `.venv/bin/python -m pytest -q tests/test_cli.py tests/test_context_projection.py -k 'build_context or delete_context or prompt_payload'` | public create/update/delete·누락 복구 성공, source/projection hash 일치, prompt 경로 불변 |
| 5. durable report·receipt·lint·index가 artifact-only와 object mutation을 구분하고 crash tail에서 중복 발급되지 않는다 | `.venv/bin/python -m pytest -q tests/test_lint.py tests/test_search_index.py tests/test_mutation.py tests/test_projection_artifact_transaction.py -k 'report or receipt or artifact_only or manual_edit or index or committed or reported'` | artifact-only는 object bytes/index 불변, object update만 invalidation, 각 committed tail exact 완성과 conflict 분리 |
| 6. 설치와 전체 엔진 회귀가 고정 후보에서 함께 통과한다 | `PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_installer.py && PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py' && PYTHONPATH=src .venv/bin/python -m pytest -q` | public 명령 설치와 두 번째 설치 무변경, runtime unittest와 전체 pytest 성공 |

독립 검증 묶음은 1) scope·root/path, 2) lifecycle·clock, 3) transaction recovery,
4) public·receipt·전체 회귀 네 개다.

## 9. 별도 design admission gate

#33 9절의 한 fixed-SHA review가 이 문서도 함께 본다. 이 gate는 구현 완료 조건 6개와 검증 묶음 4개에
추가하지 않는다. #38 row가 A1 high, A2~A5 PASS, Critical 0, Major 0일 때만 확정하며 Major가 남으면
설계복귀 1/1 도달 상태로 추가 수정 없이 중지한다.
