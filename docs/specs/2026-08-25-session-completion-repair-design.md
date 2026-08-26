# 정상 세션 완료와 처리 marker 결속 설계

- 작성일: 2026-08-25
- 상태: #34 후보 4 RETURN — normal resume의 적재 전 상태 보존 1건을 구현 전에 닫아야 함
- 대상: GitHub #34와 후속 #3
- 선행 계약: GitHub #33의 actor·loaded engine identity
- 폐기된 설계: GitHub #39 [zero-work·미해결 후보 종료](2026-08-25-session-zero-work-closure-design.md)
- 미래 논의: GitHub #40 과거 세션 일괄 적재의 미리보기·중복 방지

## 1. 범위와 variant 경계

이 설계는 item이 한 개 이상이고 미해결 후보가 없는 정상 session batch만 다룬다. transcript,
verification projection, planned objects, durable item receipt, finalization, processing report, closure ID를
결속하고 `SessionCompletion`만 marker v2를 쓰게 한다.

모든 새 session draft·manifest·binding·report의 exact `variant`는 `normal` 하나다. 기존 비-session
generic BatchBinding과 batch report는 읽기 호환만 유지한다.

normal outcome은 `committed|no_changes|failed`다. normal draft에서 `items=[]` 또는
`unresolved_candidate_ids`가 한 개 이상이면 manifest·report·corpus·index·receipt·marker를 만들지 않고
각각 다음 오류를 낸다.

- `session_items_required`
- `session_unresolved_candidates`

미해결 후보가 있으면 별도 deferred report나 재개 체인을 만들지 않는다. 판단을 마친 뒤 item 전체를 다시
확정해 normal 적재를 처음부터 준비한다. item이 없는 과거 세션은 이 실행 경계 밖이며, 현재 수동
`session mark-processed --note`를 필요에 따라 사용한다. 미래 일괄 적재는 #40에서 논의한다.

## 2. 공개 seam, durable root, 효과 소유자

```bash
project-brain session prepare-batch \
  --transcript <absolute-session.jsonl> \
  --draft <session-draft.json> \
  [--brain-root <path>]

run_ingest_batch.py <engine-produced-manifest> [--resume <matching-failed-session-report>]

project-brain session complete \
  --transcript <absolute-session.jsonl> \
  --report <engine-produced-session-report> \
  [--brain-root <path>] \
  [--replace-legacy-marker-sha256 <64hex>]
```

`prepare-batch` stdout은 JSON 객체 하나와 마지막 LF다. durable file canonical JSON과 달리 CLI 출력은
현재 CLI 관례인 `ensure_ascii=False`, `indent=2`를 쓰며 ID나 file SHA 입력이 아니다. 성공 exact key는
`ok`, `version`, `variant`, `next`, `manifest_path`이고 `ok=true`, `version=1`, `variant=normal`,
`next=run`이다. `manifest_path`는 engine이 정한 canonical absolute path다. 실패 stdout exact key는
`ok`, `error`이고 `ok=false`, `error` exact key는 `code`, `message`다. 성공은 exit 0과 빈 stderr,
실패는 exit 1을 반환한다.

session manifest에서는 caller가 `--output`이나 runner `--report`로 durable 정본 위치를 고르지 못한다.
기존 generic manifest에만 현재 runner `--report` 호환을 유지한다. `--resume`은 같은 run root의 현재
valid normal failed leaf report에만 허용하고 success·과거 leaf·다른 binding report면 item 실행 전
0-write다.

UUID execution root와 그 아래 binding run root는 다음처럼 분리한다.

```text
<brain-root>/.brain-local/session-runs/<uuid>/
<brain-root>/.brain-local/session-runs/<uuid>/<session-binding-sha256>/
```

UUID execution root에는 normal runner가 쓰는 `runner.lock` 하나만 둔다. binding run root에는
`manifest.json`, `normal-receipts/<receipt-id>.json`, `normal-reports/<closure-id>.json`을 anchored no-follow
create-only+file fsync+parent fsync로 쓴다. binding run root 안의 `runner.lock`은 v1 계약이 아니며 어떤 runner도 만들거나
획득하지 않는다. exact bytes가 이미 있으면 byte-preserving no-op이고 malformed·different bytes는
`session_prepare_conflict` 또는 artifact별 conflict다.

`SessionPreparation`은 transcript·draft와 모든 prepare 입력이 valid임을 확인하고 target
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
처음부터 다시 열어 exact 검증한다. normal runner는 이 같은 inode를 manifest scan 전부터
item/finalization과 terminal report publish까지 유지하므로 같은 UUID의 서로 다른 binding도 동시에 외부
효과를 만들 수 없다. 서로 다른 UUID의 UUID lock은 서로를 막지 않지만
corpus mutation은 기존 공용 corpus lock과 receipt drift 계약을 그대로 따른다.

v1은 `execution-owner.json` 같은 영구 binding 선점 파일을 만들지 않는다. sibling binding의 과거
manifest/report가 있다는 이유만으로 UUID를 영구 예약하지도 않는다. 공용 runner lock은 실행 구간
직렬화만 소유하고, 각 요청의 허용 여부는 lock 획득 뒤 기존 binding·receipt·drift 계약으로 다시 판정한다.

runner lock 순서는 UUID `runner.lock` → 필요한 corpus/finalization 내부 lock이고 해제는 역순이다.
`SessionCompletion`은 이 runner lock을 잡지 않고 기존 marker UUID lock만 쓴다. terminal report가 아직
없으면 marker 0-write로 재시도를 안내하고 runner state를 대신 완성하지 않는다. success report가
fsync된 뒤에는 immutable chain만 읽는다. 어떤 경로도 corpus lock이나 marker lock을 잡은 채 UUID runner
lock을 역순으로 요청하지 않는다.

| 효과 | 유일한 소유자 | 금지 대상 |
|---|---|---|
| transcript·verify·coverage에서 UUID root/runner lock provision과 binding/manifest create-only 쓰기 | `SessionPreparation` / `session prepare-batch` | runner·agent·설치 스킬의 수기 lock/binding/manifest |
| 같은 UUID의 normal 실행 직렬화 | installed normal runner의 UUID `runner.lock` | binding별 lock·SessionPreparation·SessionCompletion·agent |
| normal item mutation, corpus/index, durable item receipt, finalization, normal report | installed `run_ingest_batch.py` | SessionCompletion·agent |
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

normal runner가 쓰는 exact key는 다음과 같다.

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
item 실행 전 0-write다. 기존 non-session `BatchBinding`과 `MutationReceiptV1`의 exact field·canonical
bytes·`receipt_id` 공식은 바꾸지 않는다. 기존 `MutationReceiptV1.manifest_sha256`은 계속 mutation journal
manifest SHA다. 새 session artifact는 session manifest file SHA를 `session_manifest_sha256`으로만 부르며
bare `manifest_sha256`을 쓰지 않는다.

`SessionItemReceiptV1` exact key는 다음과 같다.

```text
version, variant, receipt_id, session_binding_sha256,
session_manifest_sha256, item_key, item_verification_sha256,
mutation_receipt
```

`version=1`, `variant=normal`이다. `mutation_receipt`는 journal 또는 durable no-change intent에서 회수해
`normalize_mutation_receipt()`를 통과한 기존 exact `MutationReceiptV1` object다. 안쪽 receipt의
`receipt_id`와 `manifest_sha256`은 다시 계산하거나 이름을 바꾸지 않는다. 바깥 `receipt_id`는 자기 key만
제외한 `SessionItemReceiptV1` canonical object의 SHA-256이다. 따라서 두 ID와 두 manifest SHA는 서로 다른
이름과 hash 공식으로 보존된다.

runner는 corpus lock 안에서 기존 durable receipt를 먼저 exact 회수한 뒤 wrapper를
`normal-receipts/<outer-receipt-id>.json`에 create-only+fsync한다. mutation commit 뒤 wrapper 전 crash는
같은 durable receipt를 다시 회수해 wrapper 꼬리만 완성하며 mutation을 재실행하지 않는다. malformed·다른
wrapper는 `session_normal_artifact_conflict`로 새 mutation·receipt·report 0-write다.

## 4. normal report와 receipt chain

`SessionProcessingReportV1` exact key는 다음과 같다.

```text
version, variant, attempt, resumed_from_closure_id,
session_binding_sha256, session_manifest_sha256,
verification_items, planned_objects, outcome,
batch_report, corpus_lineage, resume, closure_id
```

`variant=normal`이고 `closure_id`는 자신만 제외한 report 전체 exact object의 canonical SHA-256이다.
첫 terminal report는 `attempt=1`, `resumed_from_closure_id=null`이고 valid resume이 만든 다음 report는
부모 failed closure ID와 `attempt+1`을 쓴다. report에는 zero-work, attestation, unresolved nullable
field가 없다.

`SessionNormalBatchReportV1` exact key는 `version`, `item_records`, `finalization`, `failure`다.
`version=1`이고 item record exact key는 `item_key`, `status`, `receipt`, `failure`다. status는
`pending|failed|committed|no_changes`다. committed/no_changes만 receipt에 outer session receipt의
`DurableArtifactRefV1`을 갖고, failed만 failure exact `{exit_code,stderr}`를 가지며 다른 조합은 null이다.
`finalization`은 실행 전이면 null, 실행 뒤에는 기존 semantic finalization result의 exact key
`ok`, `transactions`, `commands`, `isolation`, `unmerged`, `recall_checks`, `errors`다. transactions는
안쪽 기존 `MutationReceiptV1` 배열이다. 이 batch report는 session이 소유하는 immutable projection이다.
현재 non-session generic batch report의 exact field와 caller-chosen `--report` 동작은 그대로 두며 session
report 안에 raw generic report를 embed하거나 별도 generic report path를 참조하지 않는다.

batch `failure`는 성공이면 null, 실패면 `SessionNormalFailureV1`이고 exact key는 `stage`, `artifact`,
`exit_code`, `stderr`다. stage enum은 `item|finalization` 둘뿐이다. item stage의 artifact는 failed
`item_key`, finalization stage의 artifact는 exact 문자열 `finalization`이다. receipt 회수·wrapper publish
실패는 해당 item stage로 합치고 resume가 먼저 durable receipt를 회수하므로 이미 끝난 mutation을 다시
실행하지 않는다. report publish 중 crash는 failure stage가 아니라 durable scan으로 완성하는 꼬리다.

successful normal report의 `corpus_lineage`는 `SessionCorpusLineageV1`이고 exact key는
`version`, `before_corpus_fingerprint`, `after_corpus_fingerprint`, `receipt_chain`,
`finalization_transactions_sha256`이다. `version=1`이다. `receipt_chain` row exact key는 다음과 같다.

```text
item_key, outcome, path, sha256, receipt_id, mutation_receipt_id, transaction_id,
before_corpus_fingerprint, after_corpus_fingerprint
```

row는 canonical item key 순이고 성공 batch의 outer item receipt와 정확히 일대일이다. path는 binding
run-root-relative canonical POSIX path이며 SHA는 LF를 포함한 immutable wrapper file bytes hash다. outer
ID는 `receipt_id`, 안쪽 기존 ID는 `mutation_receipt_id`로 복사하고 transaction ID·outcome·before/after
값은 안쪽 receipt에서 byte-exact로 복사한다. 첫 row before는 UUID runner lock을 잡은 뒤 첫 item 직전에
관측한 corpus fingerprint, 각 다음 row before는 바로 앞 row after와 같고, `committed` row의 transaction
ID는 64hex, `no_changes` row의 transaction ID는 null이고 before=after다. top-level before/after는 각각
첫 before와 마지막 after다.

finalization은 brain corpus를 쓰지 않으며, runner는 마지막 item transaction 뒤 corpus lock 안에서 관측한
after가 마지막 receipt와 같은지 확인한 뒤에만 successful report를 만든다. `failed` report의
`corpus_lineage`는 null이다. `finalization_transactions_sha256`은 finalization 원문의 canonical
`transactions` 배열 hash이며 배열의 generic receipt ID는 receipt chain의 `mutation_receipt_id`와 canonical
순서로 exact 같아야 한다. outer session receipt ID는 finalization의 generic transaction 배열에 넣지 않는다.

각 `normal-receipts/<receipt-id>.json`은 engine이 만든 canonical `SessionItemReceiptV1` bytes다.
`committed`는 `MutationService` durable intent→COMMITTED journal에서 안쪽 receipt를 회수해
mutation manifest·item·transaction·before/after를 byte-exact 검증한다. `no_changes`는 durable v2
no-change intent에서 회수해 transaction ID null과 before=after를 검증한다. item 사이 다른 UUID mutation
때문에 다음 receipt before가 바로 앞 after와 달라지면 성공 lineage를 만들지 않고 durable failed report로
끝낸다.

모든 item receipt가 연결되고 finalization이 성공하면 마지막 corpus lock 구간에서 current
fingerprint=마지막 receipt after와 finalization transaction 배열 일치를 확인한다. 같은 corpus lock을
successful report create-only write, file fsync, binding-root fsync까지 유지한 뒤 푼다. 이 report fsync가
historical closure의 선형화 지점이며 그 뒤의 mutation만 정상 후속 mutation으로 보고 이미 고정한 lineage를
바꾸지 않는다.

| outcome | batch_report | resume | marker |
|---|---|---|---|
| `committed` | item 1개 이상, 하나 이상 committed, 나머지 committed/no_changes, finalization 성공 | `null` | 작성 |
| `no_changes` | item 1개 이상, 전부 exact no-change receipt, 허용된 index skip, finalization 성공 | `null` | 작성 |
| `failed` | 위 exact batch report에 durable item state와 receipt/finalization 원문 | batch failure의 `stage`, `artifact` exact projection | 금지 |

manifest parse·execution-state preflight가 실패하면 session report를 만들지 않는다. item 실행을 시작한 뒤
실패하면 runner는 현재 immutable receipt와 recovery state를 결속한 failed report를 create-only로
남긴다. failed `resume` exact key는 `stage`, `artifact`이고 batch failure에서 두 값을 byte-exact 복사한다.
재호출은 manifest, current execution state, existing item receipt를 검증하고 current runner resume
계약으로만 이어 간다. 성공 report가 있으면 모든 참조 bytes를 재검증한 뒤 exact no-op다.

valid normal report chain은 root가 하나, parent당 child가 최대 하나, attempt가 1씩 증가하고 success가 leaf인
불변 chain이다. 모든 report는 root에서 도달 가능하고 leaf가 정확히 하나여야 한다. 별도 root·fork·attempt
gap·success parent·끊긴 parent는 `session_normal_artifact_conflict`다. `--resume`은 현재 유일한 failed
leaf path·bytes와 exact 같을 때만 허용하고 옛 failed report는 `session_normal_resume_not_current`로
item·finalization·report 0-write다.

runner는 UUID execution root의 공용 `runner.lock`을 anchored exclusive lock으로 잡고
manifest·receipt·normal report scan부터 item mutation, finalization, terminal report publish까지 유지한다.
같은 manifest의 valid success report가 있으면 resume 인자와 관계없이 exact no-op로 반환한다.

`SessionCompletion`은 report 값만 믿지 않는다. sibling `manifest.json`, 현재 transcript, durable item
receipt bytes, report의 `corpus_lineage`, 실행 당시 execution state와 finalization 원문 hash를 다시
검증한다. 각 ref의 path는 run-root-relative canonical POSIX path이고 `{path,sha256}` exact shape를 쓴다.

marker 단계는 과거 성공 transaction을 다시 실행하거나 현재 전체 corpus가 과거 after fingerprint와
같은지 요구하지 않는다. normal은 immutable receipt chain의 hash·순서·before→after 연속성과 report
closure ID를 검증한다. successful report 뒤 다른 정상 session이 corpus를 바꿨어도 이 과거 lineage가
유효하면 marker를 쓸 수 있다. 반대로 receipt가 없거나 bytes·순서·fingerprint 연결이 다르면
현재 corpus가 우연히 과거 값과 같아도 `session_completion_lineage_invalid`로 marker 0-write다. 현재
brain root identity와 transcript bytes는 계속 live precondition이지만, 과거 engine checkout·repo
revision·corpus bytes를 현재 상태와 같게 되돌리라고 요구하지 않는다.

## 5. marker v2와 재시도

marker exact key는 `version`, `state`, `uuid`, `transcript_sha256`, `closure_id`, `outcome`,
`receipt_ids`, `processed_at`, `replaced_legacy_sha256`다. outcome은 `committed|no_changes`다. receipt IDs는
item key 순 outer `SessionItemReceiptV1.receipt_id`다. v2 marker의 `state=processed`이며 다른 값은
malformed다.

marker, marker UUID lock, marker temp의 exact path는 다음과 같다.

```text
<brain-root>/.brain-local/sessions/<uuid>.json
<brain-root>/.brain-local/sessions/<uuid>.lock
<brain-root>/.brain-local/sessions/<uuid>.json.tmp
```

`SessionCompletion`은 모든 입력을 먼저 read-only 검증한 valid 완료 요청에서만 absent
`.brain-local/sessions`를 mode `0700` anchored directory로 만들고 parent를 fsync한 뒤 marker lock을 mode
`0600`, anchored `O_CREAT|O_RDWR|O_NOFOLLOW` create-once하고 sessions directory를 fsync한다. 기존 directory와
lock은 link count 1인 같은-device 정규 directory/file이어야 하고 lock은 한 번 만든 뒤
replace·unlink·truncate하지 않는다. 같은 inode에 exclusive lock을 잡은 뒤 marker를 다시 읽고 transcript와
완전히 publish된 immutable report chain을 재확인하며 temp write, file fsync, atomic replace, directory
fsync를 수행한다. unsafe parent·lock·교체 inode는 `session_completion_conflict`로 marker/temp 0-write다.
terminal report가 없으면 concurrent runner를 기다리거나 그 state를 고치지 않고 고정 오류와 0-write로
끝낸다. `session list`는 `.json` marker만 읽고 `.lock`과 `.json.tmp`를 무시한다.

| live marker | 요청 | 결과 |
|---|---|---|
| 없음 | valid committed/no_changes closure | marker v2 작성 |
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

구현 전에 각 stable ID로 별도 GitHub child issue와 progress block을 만든다. zero-work 실행이나
unresolved writer는 만들지 않는다.

## 7. 구현 완료 조건과 검증 연결

| 완료 조건 | 정확한 명령 | 기대 관측 |
|---|---|---|
| 1. normal 입력과 효과 소유자가 하나로 고정되고 empty·unresolved 입력은 쓰기 전에 멈춘다 | `.venv/bin/python -m pytest -q tests/test_session_completion.py tests/test_cli.py -k 'variant or owner or lock_provision or items_required or unresolved'` | valid normal prepare만 UUID lock create-once, invalid prepare lock 0개, empty·unresolved·writer 우회는 durable 0-write |
| 2. transcript→verification→planned objects→item receipt→finalization→historical corpus lineage→closure chain이 exact다 | `.venv/bin/python -m pytest -q tests/test_session_completion.py tests/test_corpus_io.py -k 'binding or execution_state or session_item_receipt or receipt_chain or corpus_lineage or historical or closure or drift'` | generic receipt ID·mutation manifest SHA 불변, outer receipt 결속과 committed/no-change 분기 성공, report 뒤 다른 session mutation 후 marker 성공, transcript·receipt bytes·lineage·finalization drift는 marker 0-write |
| 3. committed/no_changes/failed와 public prepare·runner·resume 관측이 표와 같다 | `.venv/bin/python -m pytest -q tests/test_session_completion.py tests/test_cli.py -k 'prepare_stdout or committed or no_changes or failed or attempt or resume or preflight'` | prepare variant별 exact JSON, normal 3 outcome과 current failed leaf exact, preflight는 report 없음, success retry exact no-op |
| 4. UUID runner lock과 marker absent/same/conflict/legacy/filesystem 상태가 서로 겹치지 않는 lock 경계에서 결정된다 | `.venv/bin/python -m pytest -q tests/test_session.py tests/test_session_completion.py -k 'uuid_runner_lock or marker_lock or marker or legacy or concurrent or symlink or hardlink'` | valid prepare runner lock create-once·same inode 재사용, runner missing lock 0-write, contention 대기 뒤 lock 안 재-preflight, valid completion만 marker lock create-once, unsafe/replaced/different-device lock 0-write, exact marker retry bytes 보존 |
| 5. 설치 runtime과 전체 엔진 계약이 구현 고정 후보에서 통과한다 | `PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py' && PYTHONPATH=src .venv/bin/python -m pytest -q` | 전체 성공, installer 변경 시 임시 대상 두 번째 설치 report의 변경 배열 모두 빈 값 |

구현 독립 검증 묶음은 1) schema·CLI, 2) runner·receipt·outcome, 3) marker·installer·전체 회귀 세 개다.

## 8. 현재 결정과 다음 구현 경계

후보 4 독립 검수는 normal resume가 최초 finalization baseline을 어디서 다시 읽는지 정하지 못한 한 건으로
RETURN했다. 이 문제를 새 session 전용 저장 계층으로 풀지 않는다. 현재 generic batch runner가 item 실행
전에 baseline을 report에 저장하고 resume에서 같은 값을 읽는 동작을 보존하는 방향으로 #34 구현 파일과
테스트를 먼저 특정한다.

#39 폐기는 #34 설계 후보나 검수 상한을 다시 여는 일이 아니다. 별도 후보 5와 설계-only 검수를 반복하지
않고, 사용자에게 정확한 코드·테스트 파일과 실제 BB2 영향 범위를 보여준 뒤 승인된 구현 후보에서
RED→구현→표적 실제 흐름→전체 회귀 1회→고정 SHA 독립 코드 검수 순서로 닫는다.
