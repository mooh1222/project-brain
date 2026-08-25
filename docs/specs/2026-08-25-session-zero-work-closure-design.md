# session zero-work·미해결 후보 종료 설계

- 작성일: 2026-08-25
- 상태: 설계확정 — 후보 3 독립 검수 PASS, 검수 3/3·설계복귀 2/2
- 선행 계약: [정상 session completion](2026-08-25-session-completion-repair-design.md)
- 대상: GitHub #39, `zero_objects`, `unresolved_only`, `partial_unresolved`, zero-work `failed`

## 1. 분리 원칙과 공개 seam

이 설계는 normal `SessionProcessingReportV1` schema를 넓히지 않는다. zero-work 성공·실패는
`ZeroWorkCompletionReportV1`, 미해결 후보 중단은 `SessionDeferredReportV1`이라는 exact variant를
쓴다. `session complete`는 valid zero-work 성공만 marker로 닫고 deferred report는 완료로 받지 않는다.

#34와 같은 public command가 draft `variant`로 exact parser를 고른다.

```bash
project-brain session prepare-batch \
  --transcript <absolute-session.jsonl> \
  --draft <zero-or-deferred-draft.json> \
  [--attestation <zero-work-attestation.json>] \
  [--brain-root <path>]

run_ingest_batch.py <zero-work-manifest> [--resume <failed-zero-report>]

project-brain session complete \
  --transcript <absolute-session.jsonl> \
  --report <successful-zero-report> \
  [--brain-root <path>]
```

zero-work manifest·report path는 #34 run root 아래 engine이 정한다. deferred에는 runner와 `--resume`이
없다. installed runner가 deferred manifest를 받으면 `session_deferred_manifest_not_executable`,
`session complete`가 deferred report를 받으면 `session_unresolved_candidates`로 corpus·receipt·marker
0-write다.

## 2. state matrix와 유일한 writer

| item 수 | unresolved 수 | attestation | finalization | 결과 | 유일한 외부 효과 소유자 |
|---|---|---|---|---|---|
| 0 | 0 | valid | 성공 | `zero_objects` | `SessionPreparation`이 UUID root/lock provision+manifest, runner가 finalization·execution·receipt·report·head와 head 복구, `SessionCompletion`이 marker |
| 0 | 0 | valid | 실패 | zero-work `failed` | `SessionPreparation`이 UUID root/lock provision+manifest, runner가 immutable execution·failure report·head와 head 복구, marker 없음 |
| 0 | 0 | 없음·invalid | 어떤 값 | invalid | 없음, durable 0-write |
| 0 | 1+ | 금지 | 실행 안 함 | `unresolved_only` | `SessionPreparation`만 UUID root/lock provision+manifest+deferred report create-only |
| 1+ | 1+ | 금지 | 실행 안 함 | `partial_unresolved` | `SessionPreparation`만 UUID root/lock provision+manifest+deferred report create-only |
| 1+ | 0 | 금지 | normal 값 | normal 계약으로 위임 | 이 설계가 효과를 만들지 않음 |
| 그 밖의 조합 | 어떤 값 | 어떤 값 | 어떤 값 | invalid | 없음, durable 0-write |

unresolved가 하나라도 있으면 item mutation, corpus/index transaction, item receipt, finalization, marker를
시작하지 않는다. deferred report writer는 `SessionPreparation` 하나다. runner와 prepare가 상황에 따라
같은 report를 쓰는 경로는 없다.

## 3. exact draft, binding, manifest

canonical JSON·file SHA·ID 공식은 #34 3절을 그대로 쓴다. variant별 parser는 다른 variant의 field와
null placeholder를 거부한다.

### 3.1 zero-work variant

zero draft exact key는 다음과 같다.

```text
version, variant, repo_root, expected_repo_id, expected_revision_ref,
engine_sha, items, unresolved_candidate_ids, finalization
```

`variant=zero_work`, items와 unresolved는 exact `[]`다. actor를 draft에 중복하지 않고 필수
`--attestation`에서만 가져온다.

`ZeroWorkSessionBindingV1` exact key는 다음과 같다.

```text
version, variant, uuid, transcript_size, transcript_sha256,
attestation_sha256, finalization_sha256, expected_corpus_fingerprint,
claimed_producer, claimed_verifiers
```

zero manifest exact key는 다음과 같다.

```text
version, variant, session_binding, execution_state, attestation,
items, finalization, unresolved_candidate_ids
```

items와 unresolved는 계속 exact `[]`다. `execution_state`는 #34
`SessionExecutionStateV1`이다. prepare가 관측한 corpus fingerprint와 finalization draft hash도 binding에
들어가므로 runner가 다른 corpus 또는 finalization으로 같은 zero claim을 실행할 수 없다.

### 3.2 deferred variant

deferred draft exact key는 다음과 같다.

```text
version, variant, repo_root, expected_repo_id, expected_revision_ref,
engine_sha, items, unresolved_candidate_ids, claimed_producer
```

unresolved는 canonical ID 오름차순·중복 없는 1개 이상이다. items가 비면
`variant=unresolved_only`, 한 개 이상이면 `variant=partial_unresolved`다. attestation·finalization key는
금지한다.

`DeferredItemProjectionV1` exact key는 `verification_items`, `planned_objects`다. unresolved-only에서는
둘 다 exact `[]`; partial에서는 normal item 규칙으로 계산한다. `DeferredSessionBindingV1` exact key는
다음과 같다.

```text
version, variant, uuid, transcript_size, transcript_sha256,
item_projection_sha256, unresolved_candidate_ids_sha256,
claimed_producer
```

deferred manifest exact key는 다음과 같다.

```text
version, variant, session_binding, execution_state,
item_projection, items, unresolved_candidate_ids
```

## 4. ZeroWorkAttestationV1

exact key는 `version`, `variant`, `uuid`, `transcript_size`, `transcript_sha256`, `reason`,
`claimed_producer`, `claimed_verifiers`, `checks`다. `variant=zero_work`, `reason=zero_objects`다.

actor는 #33 claimed identity를 쓰고 verifier는 producer와 actor tuple 전체가 다른 human 또는 agent가
최소 한 명이어야 한다. checks row exact key는 `id`, `outcome`, `summary`다. 다음 ID가 오름차순으로
정확히 한 번씩 있고 outcome은 모두 `pass`, summary는 비어 있지 않아야 한다.

- `session.zero-work.no-durable-knowledge`
- `session.zero-work.no-unresolved-candidates`

엔진은 구조·actor 독립성·UUID·transcript size/hash 결속을 검증하지만 판단의 의미적 진실을
transcript에서 재추론하지 않는다. producer는 unresolved 목록 완전성, verifier는 두 zero-work 판단을
확인했다는 공동 주장을 소유한다. attestation SHA가 binding에 들어가며 attestation이 binding hash를
다시 담는 순환은 없다.

## 5. zero-work immutable execution·receipt·completion

runner는 corpus transaction을 만들지 않고 finalization contract만 실행한다.

- index rebuild만 `skipped=true`, `reason=zero_objects`
- lint, audit, graph, eval, 소비 데이터 checks는 draft 선언대로 실행
- recall checks는 빈 배열과 `reason=zero_objects`를 함께 요구
- transactions와 item records는 빈 배열

UUID execution root와 binding run root의 durable path는 다음이다.

```text
<brain-root>/.brain-local/session-runs/<uuid>/runner.lock
<brain-root>/.brain-local/session-runs/<uuid>/<session-binding-sha256>/zero-head.json
<brain-root>/.brain-local/session-runs/<uuid>/<session-binding-sha256>/zero-executions/<execution-id>.json
<brain-root>/.brain-local/session-runs/<uuid>/<session-binding-sha256>/zero-receipts/<receipt-id>.json
<brain-root>/.brain-local/session-runs/<uuid>/<session-binding-sha256>/zero-reports/<closure-id>.json
```

execution·receipt·report 파일은 anchored no-follow canonical create-only+fsync다. `zero-head.json`은
첫 pointer면 temp+file fsync+atomic no-replace+binding-root fsync, 기존 pointer 전진이면
temp+file fsync+atomic replace+binding-root fsync를 쓰는 mutable pointer다. `runner.lock`은 #34가 소유한
valid prepare의 create-once UUID 공용 실행 lock이며 runner는 기존 inode만 획득하고 binding run root에는
variant별 lock을 두지 않는다. symlink·비정규·hardlink를
거부하는 link count 1 advisory lock file이다. `DurableArtifactRefV1` exact key는 `path`, `sha256`이고 path는
binding-run-root-relative canonical POSIX path, SHA는 LF를 포함한 file bytes hash다.

head publish의 고정 temp path는 binding root의 `zero-head.json.tmp`다. zero runner만 UUID lock 안에서
anchored `O_CREAT|O_EXCL|O_NOFOLLOW`로 만든다. crash 뒤 남은 temp는 live head가 아니다. 다음 runner는
temp를 건드리기 전에 immutable report/head/binding과 요청 preflight를 모두 read-only로 판정한다. malformed
report/head, unsafe ref, state_changed처럼 결과가 conflict·0-write면 safe temp도 보존한다. head-only recovery,
new execution 또는 no-op처럼 요청이 허용된 뒤에만 정규 파일·link count 1·same-device temp를
unlink+binding-root fsync하고 선택한 규칙을 수행한다. temp가 symlink·비정규·hardlink·다른 device면 지우지 않고
`session_zero_work_artifact_conflict`다. `SessionCompletion`은 temp를 무시하며 live head가 없으면
`session_zero_work_recovery_required`로 marker 0-write다.

`ZeroWorkExecutionReportV1` exact key는 다음과 같다.

```text
version, variant, execution_id, attempt, resumed_from_closure_id,
session_binding_sha256, manifest_sha256,
execution_state_sha256, before_corpus_fingerprint, after_corpus_fingerprint,
finalization, failure
```

`attempt`는 1부터 시작하는 정수다. 첫 실행은 `resumed_from_closure_id=null`, failed report의 valid resume는
그 report closure ID와 `attempt+1`을 쓴다. `execution_id`는 자신만 제외한 canonical object hash다. 성공은 before=after=bound expected fingerprint,
`finalization.ok=true`, `failure=null`이다. 실패는 가능한 검사 원문과 exact `{stage,artifact}` failure를
가진다. 매 terminal 시도를 새 immutable execution file로 남기므로 나중 재시도가 과거 failure closure를
바꾸지 않는다.

runner는 #34 UUID execution root의 공용 `runner.lock`을 anchored exclusive lock으로 잡고, lock 안에서
zero manifest·binding·attestation을 다시 연 뒤에만 terminal artifact를 읽거나 쓴다. normal runner도 같은
inode를 잡으므로 같은 UUID의 normal item mutation과 zero finalization은 동시에 실행되지 않는다. lock은
terminal report publish와 아래 head fsync가 모두 끝날 때까지 유지한다.

lock 안 판정 순서는 structural binding·manifest·attestation 검증 → immutable terminal scan과 필요한
head-only recovery → 요청 판정 → 새 finalization 직전 current fingerprint 검증이다. valid terminal
report의 head-only recovery와 success no-op는 과거 execution·receipt를 검증하며 현재 fingerprint를 과거
값과 비교하지 않는다. failed tip의 새 resume attempt와 terminal report가 없는 새 실행만 current
fingerprint=bound expected를 요구한다.

`ZeroWorkRunHeadV1` exact key는 `version`, `session_binding_sha256`, `manifest_sha256`, `attempt`,
`closure_id`, `outcome`, `execution_id`다. head는 최초 atomic no-replace create, 이후 atomic replace되는
직렬화 pointer일 뿐 closure/receipt ID
입력은 아니다. outcome은 `failed|zero_objects`이고 head attempt·closure·execution은 tip report와
byte-exact 일치해야 한다. terminal publish 순서는 immutable execution → 성공이면 receipt → completion
report → head다. head writer와 recovery owner는 installed zero runner 하나이며 `SessionPreparation`과
`SessionCompletion`은 head를 만들거나 고치지 않는다.

valid report chain은 다음 조건을 모두 만족해야 한다. 모든 report의 canonical path·closure ID,
execution/receipt path·file SHA·ID, binding·manifest·attestation SHA가 exact다. root report는 정확히 하나고
그 execution은 `attempt=1`, `resumed_from_closure_id=null`이다. root가 아닌 report는 존재하는 failed
parent closure를 가리키며 execution attempt가 parent attempt+1이다. parent당 child는 최대 하나고 성공
report는 leaf여야 한다. 모든 report는 root에서 도달 가능하고 leaf가 정확히 하나다. 이 leaf만 tip이다.
malformed file, 별도 root, 끊긴 ref, fork, attempt gap, success parent는 report 일부를 무시하고 진행하는
상태가 아니라 전체 `session_zero_work_artifact_conflict`다.

`head_for(tip)`은 `ZeroWorkRunHeadV1`의 exact projection이다. version은 1, binding·manifest SHA와
closure ID·outcome은 tip report 값, attempt·execution ID는 tip execution 값이다. canonical head bytes가
이 projection과 같을 때만 head와 tip이 exact하다고 판정한다.

lock 진입 때 runner는 이 binding의 immutable completion report와 참조 execution·receipt를 모두 읽어
유일한 chain tip을 재계산한 뒤 다음 표로만 head를 판정한다.

| live head | immutable report 상태 | 결과 |
|---|---|---|
| 없음 | report 없음 | 새 terminal 실행 또는 빠진 execution→receipt→report 완성 허용 |
| 없음 | valid report 정확히 1개이고 참조 execution이 `attempt=1`, `resumed_from_closure_id=null`, binding·manifest·모든 ref exact | 최초 report 뒤 head 전 crash tail. report에서 head bytes를 다시 계산해 atomic no-replace로 한 번 만들고 binding root fsync; finalization 재실행 없음 |
| 없음 | report가 2개 이상이거나 유일 report가 attempt 1의 최초 report가 아님 | `session_zero_work_artifact_conflict`, 0-write |
| valid head | head가 `head_for(tip)`과 exact | head write 없음, 아래 retry 요청 규칙 적용 |
| valid head | head가 `head_for(parent)`와 exact이고 parent가 tip의 바로 이전 ancestor이며 그 valid child가 tip 하나 | child tip으로 atomic replace+fsync 전진, finalization 재실행 없음 |
| malformed·다른 binding head | 어떤 상태든 | `session_zero_work_artifact_conflict`, 0-write |
| valid head | report 없음, 둘 이상의 child/tip, 끊긴 ref, head가 chain 밖·tip보다 한 단계보다 더 오래된 ancestor | `session_zero_work_artifact_conflict`, 0-write |

최초 head 복구에서 “report 정확히 1개”는 report directory만 세는 약식 조건이 아니다. canonical path,
closure ID, execution path/hash/ID, 성공 receipt path/hash/ID, attempt/resume, binding·manifest hash를 모두
재검증한 뒤 다른 valid terminal branch가 없음을 확인한 경우만 뜻한다. `--resume` report는 이렇게
복구·확정한 현재 tip인 failed closure와 exact 같을 때만 허용한다. 따라서 옛 failure 재사용, head 없는
비최초 chain의 임의 채택, 동시 runner 분기는 없다.

head 판정과 필요한 head-only 복구를 먼저 끝낸 뒤 요청을 판정한다. tip이 성공이면 기존 report를
반환하며 head가 이미 exact였으면 전체 byte-preserving no-op, head가 없었던 최초 crash tail이면 head 한
파일만 새로 생긴다. failed tip과 resume 없음은 `session_zero_work_resume_required`, exact current failed
report만 attempt+1, 과거·다른 report는 `session_zero_work_resume_not_current`다.

성공 때만 `ZeroWorkReceiptV1`을 쓴다. exact key는 다음과 같다.

```text
version, variant, receipt_id, session_binding_sha256, manifest_sha256,
execution_report_sha256, execution_state_sha256,
before_corpus_fingerprint, after_corpus_fingerprint,
finalization_sha256, outcome
```

`variant=zero_work`, `outcome=zero_objects`, `receipt_id`는 자신만 제외한 canonical object hash다.

`ZeroWorkCompletionReportV1` exact key는 다음과 같다.

```text
version, variant, session_binding_sha256, manifest_sha256,
attestation_sha256, execution_report, receipt,
outcome, resume, closure_id
```

`execution_report`는 `DurableArtifactRefV1`이다. 성공은 receipt도 artifact ref, outcome `zero_objects`,
resume `null`이다. 실패는 receipt `null`, outcome `failed`, resume exact
`{strategy,manifest_sha256}`이고 `strategy=rerun_zero_work_finalization`이다. closure ID는 자기 key만
제외한 report 전체 exact object를 hash하므로 ref path도 포함한다. 시각 field는 schema에 없다.

### retry와 crash tail

| durable state | 요청 | 결과 |
|---|---|---|
| terminal artifact 없음·중간 crash | 같은 manifest run | bound fingerprint 재확인 뒤 finalization 전체 재실행 |
| valid failed execution만 있고 completion report 없음 | 같은 manifest run | immutable execution을 재사용해 failed report와 head만 완성, 자동 재실행 없음 |
| valid success execution만 있고 receipt/report 없음 | 같은 manifest run | execution 재검증 뒤 receipt·success report·head만 완성 |
| 최초 valid terminal report만 있고 head 없음 | 같은 manifest run | UUID lock 안 exact 최초 유일 tip 검증 뒤 head만 atomic create, finalization 재실행 없음 |
| head 없음, non-first report 또는 여러 report/tip | run/resume | `session_zero_work_artifact_conflict`, 0-write |
| current-tip failed report | `--resume` 없음 | `session_zero_work_resume_required`, 새 실행 없음 |
| current-tip failed report | exact `--resume <report>` | lock 안 head/binding/manifest/attestation/current fingerprint 확인 뒤 `attempt+1` finalization 전체 재실행 |
| ancestor failed report | `--resume <old-report>` | `session_zero_work_resume_not_current`, 새 실행 없음 |
| success receipt만 있고 completion report 없음 | 같은 manifest run | receipt exact 복구 후 report·head만 create-only 완성 |
| valid success report와 exact tip head | 같은 manifest run | execution/receipt/report/head 재검증 뒤 byte-preserving no-op |
| success report 뒤 head 전 crash | `session complete` | `session_zero_work_recovery_required`, marker 0-write; 같은 manifest runner가 head만 복구한 뒤 재시도 |
| exact tip head 뒤 marker 전 crash | `session complete` | immutable chain과 #34 historical lineage 규칙 재검증 뒤 marker 작성 |
| corpus fingerprint 변경 | 새 finalization이 필요한 run/resume | `session_zero_work_state_changed`, execution·receipt·report·head·temp 변경 0회; terminal head-only recovery와 success no-op에는 이 live 비교를 적용하지 않음 |
| malformed·different terminal artifact | run/resume | `session_zero_work_artifact_conflict`, 0-write |

`SessionCompletion`은 exact tip head를 marker 작성의 필수 선행 상태로 확인하지만 head를 수리하지 않는다.
marker 시점에는 현재 corpus fingerprint를 과거 값과 비교하지 않고, execution·receipt에 기록된
before=after=bound expected 관계와 immutable ref를 #34의 historical lineage 규칙으로 검증한다. report 뒤
다른 정상 session이 corpus를 바꾼 것은 zero closure를 무효화하지 않는다.

## 6. deferred closure와 새 시작

`SessionDeferredReportV1` exact key는 다음과 같다.

```text
version, variant, session_binding_sha256, manifest_sha256,
unresolved_candidate_ids, resume, closure_id
```

resume exact key는 `strategy` 하나고 값은 `new_manifest_after_resolution`이다. closure ID는 자신만 제외한
report 전체 exact object hash다. path는 run root의 `deferred-reports/<closure-id>.json`이다.

prepare는 manifest 없음→manifest+report create, exact manifest만 있음→빠진 report 완성, exact 둘 다→
byte-preserving no-op로 동작한다. 어느 하나가 malformed·different면 `session_prepare_conflict`로 새
artifact를 만들지 않는다.

해결 뒤에는 current transcript와 전체 최종 item set으로 새 draft를 만들고 `session prepare-batch`부터
다시 시작한다. 과거 deferred manifest/report를 `--resume` 입력으로 받거나 receipt/closure chain에
합치지 않는다. 새 binding SHA와 새 run root만 허용한다.

## 7. 90분 child 경계

한 writer가 다음 순서로 나누며 각 child는 90분을 넘기지 않는다.

1. Z1 `session-zero-deferred-schema`: zero/deferred tagged parser·binding·prepare/deferred sole writer
2. Z2 `session-zero-runner`: zero finalization·immutable execution·receipt·completion report와 retry
3. Z3 `session-deferred-restart`: deferred runner rejection·새-manifest restart·normal schema 불변
4. Z4 `session-zero-complete`: `session complete` zero-success 검증, template·installer·architecture·전체 회귀

admission PASS 뒤 구현 전에 각 stable ID로 별도 GitHub child issue와 progress block을 만든다.

## 8. 구현 완료 조건과 검증 연결

| 완료 조건 | 정확한 명령 | 기대 관측 |
|---|---|---|
| 1. zero/deferred binding·tagged draft/manifest·public seam·UUID 공용 lock과 binding durable root·writer가 exact다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py tests/test_cli.py tests/test_session_completion.py -k 'schema or binding or public or durable_root or uuid_runner_lock or cross_variant or owner'` | variant field 혼합 거부, 같은 UUID normal/zero 효과 직렬화, zero는 runner만 head/report 작성, deferred는 prepare만 report 작성 |
| 2. item×unresolved×attestation×finalization 조합이 네 상태 또는 invalid를 유일하게 고른다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py -k 'state_matrix or invalid_combination'` | 표의 조합 exact, invalid는 manifest·corpus·report·receipt·marker 0-write |
| 3. producer·독립 verifier와 attestation hash chain의 역할·한계가 고정된다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py -k 'attestation or producer or verifier or transcript'` | 같은 actor·누락 check·transcript drift 거부, valid canonical hash 재계산 일치 |
| 4. zero execution·receipt·completion 성공/실패와 retry·최초 head crash tail이 durable하다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py tests/test_session_completion.py tests/test_corpus_io.py -k 'zero_objects or finalization or receipt or retry or first_head or head_temp or unique_tip or recovery_required or crash or fingerprint'` | safe temp-only cleanup 뒤 최초 유일 tip head-only 복구, unsafe temp와 non-first/multiple tip conflict, immutable 파일 SHA와 finalization 호출 수 보존, head 없는 success completion marker 0개, exact success no-op |
| 5. deferred closure가 item 전 멈추고 새 manifest만 허용하며 normal schema와 설치·전체 회귀가 불변이다 | `PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py' && PYTHONPATH=src .venv/bin/python -m pytest -q` | deferred transaction·receipt·marker 0개, past chain 재사용 거부, normal schema 불변, 전체 성공 |

구현 독립 검증 묶음은 1) schema·state·actor, 2) zero durable chain, 3) deferred·normal·설치 전체 회귀 세
개다.

## 9. 별도 design admission 종료 조건

#33 9절과 진행 기록의 후보 3 candidate + progress-only receipt 프로토콜로 고정한 같은 candidate를
독립 reviewer가 한 번만 검수한다. 구현 pytest는 이 결과를 대신하지 않는다. 별도 receipt가 exact
`reviewed_sha=$CANDIDATE_SHA`, `A1=high`, `A2=PASS`, `A3=PASS`, `A4=PASS`,
`A5=PASS`, `Critical=0`, `Major=0`, `verdict=PASS`일 때만 통과한다. 이 gate는 구현 완료 조건 5개와
구현 검증 묶음 3개에 포함하지 않는다. receipt 형식은 #33 9절을 따르며 Major가 남으면 설계복귀
2/2·검수 3/3 상태로 추가 수정 없이 중지한다.
