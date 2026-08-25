# 정상 세션 완료와 처리 marker 결속 설계

- 작성일: 2026-08-25
- 상태: #34 후보 2 독립 검수 RETURN — Critical 0 / Major 2, 검수 2/3·설계복귀 2/2; 추가 승인 전 수정 금지
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

durable root는 다음 하나다.

```text
<brain-root>/.brain-local/session-runs/<uuid>/<session-binding-sha256>/
```

그 아래 `manifest.json`, `normal-reports/<closure-id>.json`과 variant별 #39 artifact를 anchored no-follow
create-only로 쓴다. runner serialization file은 같은 root의 `runner.lock`이다. exact bytes가 이미 있으면 byte-preserving no-op이고 malformed·different bytes는
`session_prepare_conflict` 또는 artifact별 conflict다.

| 효과 | 유일한 소유자 | 금지 대상 |
|---|---|---|
| transcript·verify·coverage에서 binding/manifest create-only 쓰기 | `SessionPreparation` / `session prepare-batch` | agent·설치 스킬의 수기 binding/manifest |
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
batch_report, resume, closure_id
```

`variant=normal`이고 `closure_id`는 자신만 제외한 report 전체 exact object의 canonical SHA-256이다.
report에는 zero-work, attestation, unresolved nullable field가 없다.

| outcome | batch_report | resume | marker |
|---|---|---|---|
| `committed` | item 1개 이상, 하나 이상 committed, 나머지 committed/no_changes, `finalized=true`, finalization 성공 | `null` | 작성 |
| `no_changes` | item 1개 이상, 전부 exact no-change receipt, 허용된 index skip, finalization 성공 | `null` | 작성 |
| `failed` | durable item state와 receipt/finalization 원문 | exact `{stage,artifact}` | 금지 |

manifest parse·execution-state preflight가 실패하면 session report를 만들지 않는다. item 실행을 시작한 뒤
실패하면 runner는 현재 immutable receipt와 recovery state를 결속한 failed report를 create-only로
남긴다. 재호출은 manifest, current execution state, existing item receipt를 검증하고 current runner
resume 계약으로만 이어 간다. 성공 report가 있으면 모든 참조 bytes를 재검증한 뒤 exact no-op다.

runner는 run-root `runner.lock`을 anchored exclusive lock으로 잡고 manifest·receipt·normal report scan부터
item mutation, finalization, terminal report publish까지 유지한다. 같은 manifest의 valid success report가
있으면 resume 인자와 관계없이 exact no-op로 반환한다. failed resume은 현재 durable item/finalization
state와 resume stage가 일치하는 유일한 failed report만 받으며 옛 state report는
`session_normal_resume_not_current`로 item 실행 전 거부한다.

`SessionCompletion`은 report 값만 믿지 않는다. sibling `manifest.json`, transcript, durable item receipt,
execution state, current corpus fingerprint, finalization 원문 hash를 다시 검증한다. 각 ref의 path는
run-root-relative canonical POSIX path이고 `{path,sha256}` exact shape를 쓴다.

## 5. marker v2와 재시도

marker exact key는 `version`, `state`, `uuid`, `transcript_sha256`, `closure_id`, `outcome`,
`receipt_ids`, `processed_at`, `replaced_legacy_sha256`다. outcome은 normal의 `committed|no_changes`와 #39의
`zero_objects`다. normal receipt IDs는 item key 순이고 zero-work는 exact zero receipt ID 하나다.
`SessionCompletion`은 outcome으로 report variant를 고르고 zero-work면 #39 execution·receipt·fingerprint
chain을 검증한다. v2 marker의 `state=processed`이며 다른 값은 malformed다.

`SessionCompletion`은 anchored sessions directory 안 UUID별 lock을 잡고 marker를 다시 읽는다. 같은
lock 안에서 transcript와 report chain을 재확인하고 temp write, file fsync, atomic replace, directory
fsync를 수행한다.

| live marker | 요청 | 결과 |
|---|---|---|
| 없음 | valid committed/no_changes closure | marker v2 작성 |
| 없음 | valid #39 zero_objects closure | zero receipt 하나를 결속한 marker v2 작성 |
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
| 1. normal discriminator·네 효과 소유자·zero/deferred fail-closed 경계가 하나로 고정된다 | `.venv/bin/python -m pytest -q tests/test_session_completion.py tests/test_cli.py -k 'variant or owner or zero_work_contract or unresolved_contract'` | normal만 실행, 다른 variant field 혼합·empty/unresolved·writer 우회는 durable 0-write |
| 2. transcript→verification→planned objects→item receipt→finalization→closure chain이 exact다 | `.venv/bin/python -m pytest -q tests/test_session_completion.py tests/test_corpus_io.py -k 'binding or execution_state or receipt_chain or closure or drift'` | 정상 chain 성공, transcript/verify/root/engine/receipt/finalization drift는 marker 0-write |
| 3. committed/no_changes/failed와 public runner·resume 관측이 표와 같다 | `.venv/bin/python -m pytest -q tests/test_session_completion.py tests/test_cli.py -k 'committed or no_changes or failed or resume or preflight'` | normal 3 outcome exact, preflight는 report 없음, success retry exact no-op |
| 4. marker absent/same/conflict/legacy/filesystem 상태가 lock 안에서 결정된다 | `.venv/bin/python -m pytest -q tests/test_session.py tests/test_session_completion.py -k 'marker or legacy or concurrent or symlink or hardlink'` | exact retry bytes 보존, conflict·stale·legacy mismatch 0-write, list 상태 exact |
| 5. 설치 runtime과 전체 엔진 계약이 구현 고정 후보에서 통과한다 | `PATH="$PWD/.venv/bin:$PATH" PYTHONPATH="$PWD/src" .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py' && PYTHONPATH=src .venv/bin/python -m pytest -q` | 전체 성공, installer 변경 시 임시 대상 두 번째 설치 report의 변경 배열 모두 빈 값 |

구현 독립 검증 묶음은 1) schema·CLI, 2) runner·receipt·outcome, 3) marker·installer·전체 회귀 세 개다.

## 8. 별도 design admission 종료 조건

구현 테스트는 설계 admission 결과를 만들지 않는다. #33 9절의 candidate + progress-only receipt
프로토콜로 고정한 `CANDIDATE_SHA`에서 독립 reviewer가 이 문서와 #39 문서를 읽는다. 별도 reviewer
receipt가 exact
`reviewed_sha=$CANDIDATE_SHA`, `A1=high`, `A2=PASS`, `A3=PASS`, `A4=PASS`, `A5=PASS`, `Critical=0`,
`Major=0`, `verdict=PASS`일 때만 admission을 통과한다. Major가 하나라도 있으면 테스트 성공과 관계없이
RETURN으로 기록한다. 이 gate는 구현 완료 조건 5개와 구현 검증 묶음 3개에 포함하지 않는다. 네 문서
공통 reviewer receipt 형식과 실패 시 중지 규칙은 #33 9절을 따른다.
