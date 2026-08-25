# session zero-work·미해결 후보 종료 설계

- 작성일: 2026-08-25
- 상태: 설계복귀 후보 2 — 독립 검수 전, 검수 1/3·설계복귀 1/1
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
| 0 | 0 | valid | 성공 | `zero_objects` | `SessionPreparation`이 manifest, runner가 finalization·receipt·report, `SessionCompletion`이 marker |
| 0 | 0 | valid | 실패 | zero-work `failed` | runner가 immutable failure report, marker 없음 |
| 0 | 0 | 없음·invalid | 어떤 값 | invalid | 없음, durable 0-write |
| 0 | 1+ | 금지 | 실행 안 함 | `unresolved_only` | `SessionPreparation`만 manifest+deferred report create-only |
| 1+ | 1+ | 금지 | 실행 안 함 | `partial_unresolved` | `SessionPreparation`만 manifest+deferred report create-only |
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

durable path는 run root 아래 다음이다.

```text
runner.lock
zero-head.json
zero-executions/<execution-id>.json
zero-receipts/<receipt-id>.json
zero-reports/<closure-id>.json
```

execution·receipt·report 파일은 anchored no-follow canonical create-only+fsync다. `zero-head.json`은
temp+file fsync+atomic replace+run-root fsync를 쓰는 mutable pointer이고 `runner.lock`은 symlink·비정규·
hardlink를 거부하는 advisory lock file이다. `DurableArtifactRefV1` exact key는 `path`, `sha256`이고 path는
run-root-relative canonical POSIX path, SHA는 LF를 포함한 file bytes hash다.

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

runner는 run-root `runner.lock`을 anchored exclusive lock으로 잡은 뒤에만 terminal artifact를 읽거나
쓴다. `ZeroWorkRunHeadV1` exact key는 `version`, `session_binding_sha256`, `manifest_sha256`, `attempt`,
`closure_id`, `outcome`, `execution_id`다. head는 atomic replace되는 직렬화 pointer일 뿐 closure/receipt ID
입력은 아니다. outcome은 `failed|zero_objects`이고 head attempt·closure·execution은 tip report와
byte-exact 일치해야 한다. lock 진입 때 immutable report chain에서 유일한 tip을 재계산한다. head가 바로 이전
ancestor이고 child가 하나뿐이면 crash tail로 보고 tip까지 앞으로 복구하며, malformed head나 둘 이상의
child/tip은 `session_zero_work_artifact_conflict`다. `--resume` report는 현재 tip인 failed closure와 exact
같을 때만 허용한다. 따라서 옛 failure 재사용과 동시 runner 분기는 없다.

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
| valid failed execution만 있고 completion report 없음 | 같은 manifest run | immutable execution을 재사용해 failed report만 완성, 자동 재실행 없음 |
| valid success execution만 있고 receipt/report 없음 | 같은 manifest run | execution 재검증 뒤 receipt와 success report만 완성 |
| current-tip failed report | `--resume` 없음 | `session_zero_work_resume_required`, 새 실행 없음 |
| current-tip failed report | exact `--resume <report>` | lock 안 head/binding/manifest/attestation/current fingerprint 확인 뒤 `attempt+1` finalization 전체 재실행 |
| ancestor failed report | `--resume <old-report>` | `session_zero_work_resume_not_current`, 새 실행 없음 |
| success receipt만 있고 completion report 없음 | 같은 manifest run | receipt exact 복구 후 report만 create-only 완성 |
| valid success report | 같은 manifest run | execution/receipt/report 재검증 뒤 byte-preserving no-op |
| report 뒤 marker 전 crash | `session complete` | chain 재검증 뒤 marker 작성 |
| corpus fingerprint 변경 | run/resume | `session_zero_work_state_changed`, 재실행 0회 |
| malformed·different terminal artifact | run/resume | `session_zero_work_artifact_conflict`, 0-write |

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
| 1. zero/deferred binding·tagged draft/manifest·public seam·durable root·writer가 exact다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py tests/test_cli.py -k 'schema or binding or public or durable_root or owner'` | variant field 혼합 거부, zero는 runner만, deferred는 prepare만 report 작성 |
| 2. item×unresolved×attestation×finalization 조합이 네 상태 또는 invalid를 유일하게 고른다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py -k 'state_matrix or invalid_combination'` | 표의 조합 exact, invalid는 manifest·corpus·report·receipt·marker 0-write |
| 3. producer·독립 verifier와 attestation hash chain의 역할·한계가 고정된다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py -k 'attestation or producer or verifier or transcript'` | 같은 actor·누락 check·transcript drift 거부, valid canonical hash 재계산 일치 |
| 4. zero execution·receipt·completion 성공/실패와 retry/crash tail이 durable하다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py tests/test_corpus_io.py -k 'zero_objects or finalization or receipt or retry or crash or fingerprint'` | immutable failure, bound fingerprint, receipt-only recovery, success no-op, conflict marker 없음 |
| 5. deferred closure가 item 전 멈추고 새 manifest만 허용하며 normal schema와 설치·전체 회귀가 불변이다 | `PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py' && PYTHONPATH=src .venv/bin/python -m pytest -q` | deferred transaction·receipt·marker 0개, past chain 재사용 거부, normal schema 불변, 전체 성공 |

구현 독립 검증 묶음은 1) schema·state·actor, 2) zero durable chain, 3) deferred·normal·설치 전체 회귀 세
개다.

## 9. 별도 design admission 종료 조건

#33 9절의 candidate + progress-only receipt 프로토콜로 고정한 같은 candidate를 같은 독립 reviewer가 한
번만 검수한다. 구현 pytest는 이 결과를 대신하지 않는다. 별도 receipt가 exact
`reviewed_sha=$CANDIDATE_SHA`, `A1=high`, `A2=PASS`, `A3=PASS`, `A4=PASS`,
`A5=PASS`, `Critical=0`, `Major=0`, `verdict=PASS`일 때만 통과한다. 이 gate는 구현 완료 조건 5개와
구현 검증 묶음 3개에 포함하지 않는다. 네 문서 공통 receipt와 실패 시 중지 규칙은 #33 9절을 따른다.
