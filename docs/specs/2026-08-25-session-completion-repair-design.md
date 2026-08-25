# 정상 세션 완료와 처리 marker 결속 설계

- 작성일: 2026-08-25
- 상태: #34 설계복귀 후보 3 — 독립 검수 전, 검수 2/3·설계복귀 3/3
- 대상: GitHub #34와 후속 #3
- 선행 계약: GitHub #33의 actor·loaded engine identity
- 별도 설계: GitHub #39 [zero-work·미해결 후보 종료](2026-08-25-session-zero-work-closure-design.md)

## 1. 범위와 variant 경계

이 설계는 item이 한 개 이상이고 미해결 후보가 없는 정상 session batch만 다룬다. transcript,
verification projection, planned objects, durable item receipt, finalization, processing report, closure ID를
결속하고 `SessionCompletion`만 marker v2를 쓰게 한다.

모든 새 session draft·manifest·binding·report는 `variant`를 가진 tagged union이다. 이 문서의 exact
variant는 `normal` 하나다. #39가 `zero_work|unresolved_only|partial_unresolved`를 각각 별도 schema로
정의한다. parser는 variant로 먼저 분기하고 다른 variant의 nullable/unused field를 허용하지 않는다.
기존 비-session generic BatchBinding과 batch report는 읽기 호환만 유지한다.

normal outcome은 `committed|no_changes|failed`다. normal draft에서 `items=[]` 또는
`unresolved_candidate_ids`가 한 개 이상이면 manifest·report·corpus·index·receipt·marker 0-write로
각각 다음 오류를 낸다.

- `session_zero_work_contract_required`
- `session_unresolved_contract_required`

정상 schema에 future zero-work nullable field를 미리 넣지 않는다.

## 2. 공개 seam, durable root, 효과 소유자

```bash
project-brain session prepare-batch \
  --transcript <absolute-session.jsonl> \
  --draft <session-draft.json> \
  [--attestation <zero-work-attestation.json>] \
  [--brain-root <path>]

run_ingest_batch.py <engine-produced-manifest> [--resume <matching-failed-session-report>]

project-brain session complete \
  --transcript <absolute-session.jsonl> \
  --report <engine-produced-session-report> \
  [--brain-root <path>] \
  [--replace-legacy-marker-sha256 <64hex>]
```

`prepare-batch`는 manifest의 canonical path를 stdout으로 반환한다. session manifest에서는 caller가
`--output`이나 runner `--report`로 durable 정본 위치를 고르지 못한다. 기존 generic manifest에만 현재
runner `--report` 호환을 유지한다. normal manifest에 `--attestation`을 주면 고정 오류다. `--resume`은
같은 run root의 valid normal failed report에만 허용하고 success·다른 variant·다른 binding report면
item 실행 전 0-write다.

UUID execution root와 그 아래 binding run root는 다음처럼 분리한다.

```text
<brain-root>/.brain-local/session-runs/<uuid>/
<brain-root>/.brain-local/session-runs/<uuid>/<session-binding-sha256>/
```

UUID execution root에는 normal과 #39 zero-work가 함께 쓰는 `runner.lock` 하나만 둔다. binding run root에는
`manifest.json`, `normal-receipts/<receipt-id>.json`, `normal-reports/<closure-id>.json`과 variant별 #39
artifact를 anchored no-follow create-only+file fsync+parent fsync로 쓴다. binding run root 안의
`runner.lock`은 v1 계약이 아니며 어떤 runner도 만들거나
획득하지 않는다. exact bytes가 이미 있으면 byte-preserving no-op이고 malformed·different bytes는
`session_prepare_conflict` 또는 artifact별 conflict다.

`SessionPreparation`은 transcript·draft·attestation과 모든 prepare 입력이 valid임을 확인하고 target
binding root를 read-only scan한다. malformed·different manifest/report나 unsafe root가 있으면 UUID
root·lock을 새로 만들지 않고 기존 `session_prepare_conflict`로 0-write다. target manifest가 absent여서 새
prepare를 publish할 때만, manifest보다 먼저 UUID execution root와 absent `runner.lock`을 공통 helper로 mode `0600`, anchored
`O_CREAT|O_RDWR|O_NOFOLLOW` create-once하고 root를 fsync한다. invalid prepare는 UUID root·lock도 만들지
않는다. 한 번 만든 lock은 engine이 replace·unlink·truncate하지 않으며 이후 valid prepare는 같은 inode를
재사용한다. lock fsync 뒤 manifest 전 crash에서는 lock 하나만 남을 수 있다. 이는 session outcome이나
binding 선점이 아니라 안전한 기반 파일이며 같은 valid prepare가 identity를 재검증해 그대로 재사용한다.
exact existing manifest 재호출은 기존 safe lock이 같은 inode일 때만 byte-preserving no-op이고 lock이
없거나 바뀌었으면 새로 보충하지 않고 `session_prepare_conflict`다.

runner는 lock 밖에서 brain root와 transcript basename의 canonical UUID를 locator로만 읽는다. UUID execution
root를 anchored no-follow로 열고 기존 lock만 연다. missing lock은 `session_runner_lock_missing`으로
corpus·finalization·receipt·report·head 0-write이며 runner가 대신 만들지 않는다. preparation과 모든 runner
호출은 path와 열린 fd가 같은 device·inode인 link count 1 정규 파일인지 확인한다. lock과 UUID execution
root의 device는 brain root device와 같아야 한다. symlink·비정규·hardlink·교체 inode·다른 device는 boundary
오류로 durable 0-write다. runner는 같은 inode에 exclusive lock을 잡는다. 정상 contention은 conflict가
아니라 기다렸다가 lock을 획득한 뒤 아래 preflight를 처음부터 다시 판정한다.

lock 안에서 transcript, manifest, binding UUID·SHA와 binding run root를
처음부터 다시 열어 exact 검증한다. normal과 zero-work runner는 이 같은 inode를 manifest scan 전부터
item/finalization, terminal report publish, #39 zero head fsync까지 유지하므로 같은 UUID의 서로 다른
binding·variant도 동시에 외부 효과를 만들 수 없다. 서로 다른 UUID의 UUID lock은 서로를 막지 않지만
corpus mutation은 기존 공용 corpus lock과 receipt drift 계약을 그대로 따른다.

v1은 `execution-owner.json` 같은 영구 binding 선점 파일을 만들지 않는다. sibling binding의 과거
manifest/report가 있다는 이유만으로 UUID를 영구 예약하지도 않는다. 공용 runner lock은 실행 구간
직렬화만 소유하고, 각 요청의 허용 여부는 lock 획득 뒤 기존 binding·receipt·drift 계약으로 다시 판정한다.

runner lock 순서는 UUID `runner.lock` → 필요한 corpus/finalization 내부 lock이고 해제는 역순이다.
`SessionCompletion`은 이 runner lock을 잡지 않고 기존 marker UUID lock만 쓴다. terminal report가 아직
없거나 #39 zero head가 아직 없다면 marker 0-write로 재시도를 안내하고 runner state를 대신 완성하지
않는다. success report와 필요한 head가 fsync된 뒤에는 immutable chain만 읽는다. 어떤 경로도 corpus
lock이나 marker lock을 잡은 채 UUID runner lock을 역순으로 요청하지 않는다.

| 효과 | 유일한 소유자 | 금지 대상 |
|---|---|---|
| transcript·verify·coverage에서 UUID root/runner lock provision과 binding/manifest create-only 쓰기 | `SessionPreparation` / `session prepare-batch` | runner·agent·설치 스킬의 수기 lock/binding/manifest |
| 같은 UUID의 normal/zero 실행 직렬화 | installed normal/zero runner의 UUID `runner.lock` | binding별 lock·SessionPreparation·SessionCompletion·agent |
| normal item mutation, corpus/index, durable item receipt, finalization, normal report | installed `run_ingest_batch.py` | SessionCompletion·agent |
| #39 deferred report | `SessionPreparation` | runner·SessionCompletion |
| report/receipt/transcript 재검증과 marker v2 | `SessionCompletion` / `session complete` | runner·agent·기존 `mark-processed` |

completion 검증 실패가 이미 성공한 corpus transaction을 되돌리지는 않는다. marker를 쓰지 않고 exact
report path와 오류를 반환한다. 기존 `session mark-processed` 쓰기는
`session_completion_report_required`로 0-write 실패하고 `session complete`를 안내한다.

## 3. canonical binding과 manifest

모든 JSON은 UTF-8 strict canonical JSON(`ensure_ascii=False`, `allow_nan=False`, key sort, compact
separator, newline 없음)이다. file bytes는 canonical bytes 뒤 LF 하나다. unknown/missing/duplicate key,
bool-as-int, NaN, 비정규 Unicode를 거부한다. binding·execution·receipt·closure ID는 자기 ID key 하나만
제외한 newline 없는 canonical JSON의 SHA-256이다. `*_sha256` file ref는 LF까지 포함한 canonical file
bytes의 SHA-256이다.

### 3.1 item verification

각 item projection exact key는 `item_key`, `mode`, `coverage_sha256`, `verify_json_sha256`, `groups`다.
`mode=assembled`, item 수는 한 개 이상이다. groups는 coverage의 `verify_groups.names`와 exact
일치하고 각 verdict는 `pass|fixed`다. planned objects는 모든 item의 expected objects를 `(id,kind)`로
정렬·중복 제거한 exact 배열이다.

### 3.2 SessionExecutionStateV1

normal과 #39 zero-work runner가 공유하는 exact key는 다음과 같다.

```text
brain_root, brain_root_device, brain_root_inode,
repo_root, repo_root_device, repo_root_inode,
expected_repo_id, expected_revision_ref, target_revision_sha,
engine_identity_sha256
```

root는 실제 open directory identity, target revision은 실제 해석한 commit, engine identity는 #33의
loaded checkout identity다. prepare와 runner가 각각 관측해 canonical SHA가 다르면 item/finalization 전
`session_execution_state_changed`로 0-write다.

### 3.3 SessionBindingV1과 SessionBatchManifestV1

`SessionBindingV1` exact key는 다음과 같다.

```text
version, variant, uuid, transcript_size, transcript_sha256,
verification_projection_sha256, planned_objects_sha256,
claimed_producer
```

`version=1`, `variant=normal`이다. UUID는 transcript basename에서 읽은 canonical UUID다.
`claimed_producer`는 #33 exact claimed actor다. producer는 unresolved 목록이 비었다는 current session
판정의 완전성을 주장한다. 엔진은 transcript에서 그 의미를 새로 추론하지 않지만 transcript hash와
주장을 binding에 결속한다.

normal draft exact key는 다음과 같다.

```text
version, variant, repo_root, expected_repo_id, expected_revision_ref,
engine_sha, items, finalization, unresolved_candidate_ids, claimed_producer
```

`items`는 한 개 이상, unresolved는 exact `[]`다. manifest exact key는 다음과 같다.

```text
version, variant, session_binding, execution_state,
verification_items, items, finalization, unresolved_candidate_ids
```

`prepare-batch`는 transcript와 모든 item 입력을 metadata→bytes→metadata로 읽어 drift를 확인하고
projection과 planned objects를 직접 만든다. runner는 실행 직전 전부 다시 계산한다. manifest와 다르면
item 실행 전 0-write다. 기존 non-session BatchBinding shape는 바꾸지 않고 session item receipt에만
`session_binding_sha256`, `item_verification_sha256`, `manifest_sha256`을 추가한다.

## 4. normal report와 receipt chain

`SessionProcessingReportV1` exact key는 다음과 같다.

```text
version, variant, session_binding_sha256, manifest_sha256,
verification_items, planned_objects, outcome,
batch_report, corpus_lineage, resume, closure_id
```

`variant=normal`이고 `closure_id`는 자신만 제외한 report 전체 exact object의 canonical SHA-256이다.
report에는 zero-work, attestation, unresolved nullable field가 없다.

successful normal report의 `corpus_lineage`는 `SessionCorpusLineageV1`이고 exact key는
`version`, `before_corpus_fingerprint`, `after_corpus_fingerprint`, `receipt_chain`,
`finalization_transactions_sha256`이다. `version=1`이다.
`receipt_chain` row exact key는 다음과 같다.

```text
item_key, outcome, path, sha256, receipt_id, transaction_id,
before_corpus_fingerprint, after_corpus_fingerprint
```

row는 canonical item key 순이고 성공 batch의 item receipt와 정확히 일대일이다. path는 binding
run-root-relative canonical POSIX path이며 SHA는 LF를 포함한 immutable receipt file bytes hash다. row의
ID·transaction ID·outcome·before/after 값은 그 receipt에서 byte-exact로 복사한다. 첫 row before는 UUID runner lock을
잡은 뒤 첫 item 직전에 관측한 corpus fingerprint, 각 다음 row before는 바로 앞 row after와 같고,
`committed` row의 transaction ID는 64hex, `no_changes` row의 transaction ID는 null이고 before=after다.
top-level before/after는 각각 첫 before와 마지막 after다.
finalization은 brain corpus를 쓰지 않으며, runner는 마지막 item transaction 뒤 corpus lock 안에서 관측한
after가 마지막 receipt와 같은지 확인한 뒤에만 successful report를 만든다. `failed` report의
`corpus_lineage`는 null이다. `finalization_transactions_sha256`은 finalization 원문의 canonical
`transactions` 배열 hash이며 배열은 receipt chain에서 transaction ID가 null이 아닌 row의 ID와 canonical
순서로 exact 같아야 한다. finalization의 receipt ID 배열은 모든 receipt-chain row와 exact 같아야 한다.

각 `normal-receipts/<receipt-id>.json`은 engine이 만든 canonical item receipt bytes다. `committed`는
MutationService durable intent→COMMITTED journal에서 회수해 manifest·item·transaction·before/after를
byte-exact 검증한다. `no_changes`는 durable v2 no-change intent에서 회수해 transaction ID null과
before=after를 검증한다. runner는 각각 corpus lock 안에서 create-only publish한다. item 사이 다른 UUID
mutation 때문에 다음 receipt before가 바로 앞 after와 달라지면 성공 lineage를 만들지 않고 durable failed
report로 끝낸다.

모든 item receipt가 연결되고 finalization이 성공하면 마지막 corpus lock 구간에서 current
fingerprint=마지막 receipt after와 finalization transaction/receipt 배열 일치를 확인한다. 같은 corpus lock을
successful report create-only write, file fsync, binding-root fsync까지 유지한 뒤 푼다. 이 report fsync가
historical closure의 선형화 지점이며 그 뒤의 mutation만 정상 후속 mutation으로 보고 이미 고정한 lineage를
바꾸지 않는다.

| outcome | batch_report | resume | marker |
|---|---|---|---|
| `committed` | item 1개 이상, 하나 이상 committed, 나머지 committed/no_changes, `finalized=true`, finalization 성공 | `null` | 작성 |
| `no_changes` | item 1개 이상, 전부 exact no-change receipt, 허용된 index skip, finalization 성공 | `null` | 작성 |
| `failed` | durable item state와 receipt/finalization 원문 | exact `{stage,artifact}` | 금지 |

manifest parse·execution-state preflight가 실패하면 session report를 만들지 않는다. item 실행을 시작한 뒤
실패하면 runner는 현재 immutable receipt와 recovery state를 결속한 failed report를 create-only로
남긴다. 재호출은 manifest, current execution state, existing item receipt를 검증하고 current runner
resume 계약으로만 이어 간다. 성공 report가 있으면 모든 참조 bytes를 재검증한 뒤 exact no-op다.

runner는 UUID execution root의 공용 `runner.lock`을 anchored exclusive lock으로 잡고
manifest·receipt·normal report scan부터
item mutation, finalization, terminal report publish까지 유지한다. 같은 manifest의 valid success report가
있으면 resume 인자와 관계없이 exact no-op로 반환한다. failed resume은 현재 durable item/finalization
state와 resume stage가 일치하는 유일한 failed report만 받으며 옛 state report는
`session_normal_resume_not_current`로 item 실행 전 거부한다.

`SessionCompletion`은 report 값만 믿지 않는다. sibling `manifest.json`, 현재 transcript, durable item
receipt bytes, report의 `corpus_lineage`, 실행 당시 execution state와 finalization 원문 hash를 다시
검증한다. 각 ref의 path는 run-root-relative canonical POSIX path이고 `{path,sha256}` exact shape를 쓴다.

marker 단계는 과거 성공 transaction을 다시 실행하거나 현재 전체 corpus가 과거 after fingerprint와
같은지 요구하지 않는다. normal은 immutable receipt chain의 hash·순서·before→after 연속성과 report
closure ID를 검증한다. #39 zero-work는 immutable execution·receipt의 before=after=bound expected
fingerprint를 검증한다. 둘 다 successful report 뒤 다른 정상 session이 corpus를 바꿨어도 이 과거
lineage가 유효하면 marker를 쓸 수 있다. 반대로 receipt가 없거나 bytes·순서·fingerprint 연결이 다르면
현재 corpus가 우연히 과거 값과 같아도 `session_completion_lineage_invalid`로 marker 0-write다. 현재
brain root identity와 transcript bytes는 계속 live precondition이지만, 과거 engine checkout·repo
revision·corpus bytes를 현재 상태와 같게 되돌리라고 요구하지 않는다.

## 5. marker v2와 재시도

marker exact key는 `version`, `state`, `uuid`, `transcript_sha256`, `closure_id`, `outcome`,
`receipt_ids`, `processed_at`, `replaced_legacy_sha256`다. outcome은 normal의 `committed|no_changes`와 #39의
`zero_objects`다. normal receipt IDs는 item key 순이고 zero-work는 exact zero receipt ID 하나다.
`SessionCompletion`은 outcome으로 report variant를 고르고 zero-work면 #39 execution·receipt·fingerprint
chain을 검증한다. v2 marker의 `state=processed`이며 다른 값은 malformed다.

`SessionCompletion`은 anchored sessions directory 안 marker UUID lock을 잡고 marker를 다시 읽는다. 같은
lock 안에서 transcript와 완전히 publish된 immutable report chain을 재확인하고 temp write, file fsync,
atomic replace, directory fsync를 수행한다. terminal report 또는 zero head가 없으면 concurrent runner를
기다리거나 그 state를 고치지 않고 고정 오류와 0-write로 끝낸다.

| live marker | 요청 | 결과 |
|---|---|---|
| 없음 | valid committed/no_changes closure | marker v2 작성 |
| 없음 | valid #39 zero_objects closure | zero receipt 하나를 결속한 marker v2 작성 |
| 없음 | valid 과거 closure, 뒤이은 정상 corpus mutation 존재 | live fingerprint 동등성 없이 lineage로 marker v2 작성 |
| 같은 valid v2 UUID·transcript·closure | 같은 report | byte-preserving 성공 no-op |
| 다른 valid v2, stale v2, malformed | 어떤 완료 요청 | `session_completion_conflict`, 0-write |
| legacy | precondition 없음·불일치 | `session_legacy_marker_precondition_required`, 0-write |
| legacy | lock 안 live bytes SHA와 exact precondition | valid closure일 때만 v2 교체 |
| symlink·비정규·hardlink | 어떤 요청 | 경계 오류, 0-write |
| temp만 남음 | 같은 report 재시도 | temp를 marker로 보지 않고 정상 재시도 |

`session list`는 `processed|unprocessed|legacy_unverified|stale_v2|invalid_marker`를 구분한다. 현재
transcript와 맞는 valid v2만 processed다.

## 6. 90분 child 경계

한 writer가 다음 순서로 나누며 각 child는 90분을 넘기지 않는다.

1. N1 `session-normal-schema`: tagged canonical schema·run-root·SessionExecutionState와 prepare CLI
2. N2 `session-normal-runner`: normal runner·receipt chain·outcome/report·resume
3. N3 `session-normal-marker`: `session complete`, marker v2 lock·retry·legacy CAS·session list
4. N4 `session-normal-install`: session-ingest template·installer·architecture 문서와 두 번째 설치 무변경·전체 회귀

admission PASS 뒤 구현 전에 각 stable ID로 별도 GitHub child issue와 progress block을 만든다. zero-work
실행이나 unresolved writer 구현을 이 child에 끼워 넣지 않는다.

## 7. 구현 완료 조건과 검증 연결

| 완료 조건 | 정확한 명령 | 기대 관측 |
|---|---|---|
| 1. normal discriminator·효과 소유자·zero/deferred fail-closed 경계가 하나로 고정된다 | `.venv/bin/python -m pytest -q tests/test_session_completion.py tests/test_cli.py -k 'variant or owner or lock_provision or zero_work_contract or unresolved_contract'` | valid prepare만 UUID lock create-once, invalid prepare lock 0개, normal만 실행, 다른 variant field 혼합·empty/unresolved·writer 우회는 durable 0-write |
| 2. transcript→verification→planned objects→item receipt→finalization→historical corpus lineage→closure chain이 exact다 | `.venv/bin/python -m pytest -q tests/test_session_completion.py tests/test_corpus_io.py -k 'binding or execution_state or receipt_chain or corpus_lineage or historical or closure or drift'` | committed/no-change receipt 분기와 report-fsync 선형화 성공, report 뒤 다른 session mutation 후 marker 성공, transcript·receipt bytes·lineage·finalization drift는 marker 0-write |
| 3. committed/no_changes/failed와 public runner·resume 관측이 표와 같다 | `.venv/bin/python -m pytest -q tests/test_session_completion.py tests/test_cli.py -k 'committed or no_changes or failed or resume or preflight'` | normal 3 outcome exact, preflight는 report 없음, success retry exact no-op |
| 4. UUID 공용 runner lock과 marker absent/same/conflict/legacy/filesystem 상태가 서로 겹치지 않는 lock 경계에서 결정된다 | `.venv/bin/python -m pytest -q tests/test_session.py tests/test_session_completion.py tests/test_session_zero_work.py -k 'uuid_runner_lock or cross_variant or marker or legacy or concurrent or symlink or hardlink'` | valid prepare create-once·same inode 재사용, runner missing lock 0-write, contention 대기 뒤 lock 안 재-preflight, unsafe/replaced/different-device lock 0-write, 같은 UUID normal/zero 효과 직렬화, 다른 UUID lock끼리는 비차단이되 corpus lock·drift 계약 유지, exact marker retry bytes 보존 |
| 5. 설치 runtime과 전체 엔진 계약이 구현 고정 후보에서 통과한다 | `PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py' && PYTHONPATH=src .venv/bin/python -m pytest -q` | 전체 성공, installer 변경 시 임시 대상 두 번째 설치 report의 변경 배열 모두 빈 값 |

구현 독립 검증 묶음은 1) schema·CLI, 2) runner·receipt·outcome, 3) marker·installer·전체 회귀 세 개다.

## 8. 별도 design admission 종료 조건

구현 테스트는 설계 admission 결과를 만들지 않는다. #33 9절의 candidate + progress-only receipt
프로토콜과 진행 기록의 후보 3 fixed-SHA 절차로 고정한 `CANDIDATE_SHA`에서 독립 reviewer가 이 문서와
#39 문서를 읽는다. 별도 reviewer
receipt가 exact
`reviewed_sha=$CANDIDATE_SHA`, `A1=high`, `A2=PASS`, `A3=PASS`, `A4=PASS`, `A5=PASS`, `Critical=0`,
`Major=0`, `verdict=PASS`일 때만 admission을 통과한다. Major가 하나라도 있으면 테스트 성공과 관계없이
RETURN으로 기록한다. 이 gate는 구현 완료 조건 5개와 구현 검증 묶음 3개에 포함하지 않는다. reviewer
receipt 형식은 #33 9절을 따르며 Major가 남으면 설계복귀 3/3·검수 3/3 상태로 추가 수정 없이 중지한다.
