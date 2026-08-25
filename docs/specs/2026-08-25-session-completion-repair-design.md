# 정상 세션 완료와 처리 marker 결속 설계

- 작성일: 2026-08-25
- 상태: #34 후보 1 독립 검수 RETURN — Critical 0 / Major 1, 추가 설계복귀 승인 전 수정 금지
- 대상: GitHub #34와 후속 #3
- 선행 계약: GitHub #33의 actor·loaded engine identity
- 별도 설계: [zero-work·미해결 후보 종료](2026-08-25-session-zero-work-closure-design.md)

## 1. 범위

이 설계는 item이 한 개 이상이고 미해결 후보가 없는 정상 session batch만 다룬다. transcript,
verification projection, planned objects, durable item receipt, finalization, processing report, closure ID를
결속하고 `SessionCompletion`만 marker v2를 쓰게 한다.

outcome은 `committed|no_changes|failed` 세 개다. `items=[]`, `unresolved_candidate_ids`가 한 개 이상인
입력, zero-work attestation·receipt·finalization은 별도 설계가 구현되기 전 다음 고정 오류로
manifest·report·corpus·index·receipt·marker 0-write 거부한다.

- `session_zero_work_contract_required`
- `session_unresolved_contract_required`

정상 report의 exact schema에 future zero-work nullable field를 미리 넣지 않는다.

## 2. 공개 seam과 효과 소유자

```bash
project-brain session prepare-batch \
  --transcript <absolute-session.jsonl> \
  --draft <session-batch-draft.json> \
  --output <session-batch-manifest.json>

project-brain session complete \
  --transcript <absolute-session.jsonl> \
  --report <session-processing-report.json> \
  [--brain-root <path>] \
  [--replace-legacy-marker-sha256 <64hex>]
```

| 효과 | 유일한 소유자 | 금지 대상 |
|---|---|---|
| transcript·verify·coverage에서 binding/manifest create-only 쓰기 | `session prepare-batch` | agent·설치 스킬의 수기 binding/manifest |
| item mutation, corpus/index, durable item receipt, finalization, normal processing report | `run_ingest_batch.py` | SessionCompletion·agent |
| report/receipt/transcript 재검증과 marker v2 쓰기 | `SessionCompletion` | runner·agent·기존 `mark-processed` |

completion 검증 실패가 이미 성공한 corpus transaction을 되돌리지는 않는다. 대신 marker를 쓰지 않고
정확한 report·resume 경로를 반환한다. 기존 `session mark-processed` 쓰기는
`session_completion_report_required`로 0-write 실패하고 `session complete`를 안내한다.

## 3. canonical binding

모든 hash 입력은 UTF-8 canonical JSON(`ensure_ascii=False`, `allow_nan=False`, key sort, compact
separator, newline 없음)이다. 파일 bytes는 canonical bytes 뒤 newline 하나다. parser는 key 집합과
file bytes를 exact 검증한다.

### 3.1 item verification

각 item projection exact key는 `item_key`, `mode`, `coverage_sha256`, `verify_json_sha256`, `groups`다.
`mode=assembled`, item 수는 한 개 이상이다. groups는 coverage의 `verify_groups.names`와 exact
일치하고 각 verdict는 `pass|fixed`다. planned objects는 모든 item의 expected objects를 `(id,kind)`로
정렬·중복 제거한 exact 배열이다.

### 3.2 SessionBindingV1

```text
version, uuid, transcript_size, transcript_sha256,
verification_projection_sha256, planned_objects_sha256,
claimed_producer
```

UUID는 transcript basename에서 읽고 canonical UUID여야 한다. `claimed_producer`는 #33의 exact
claimed actor identity를 사용한다. producer는 `unresolved_candidate_ids=[]`가 현재 session 판정의 전체
결과라는 책임을 진다. 엔진은 그 의미를 transcript에서 새로 추론하지 않지만, 이 주장과 transcript
hash를 closure에 결속한다.

### 3.3 SessionBatchManifestV1

draft exact key는 `repo_root`, `expected_repo_id`, `expected_revision_ref`, `engine_sha`, `items`,
`finalization`, `unresolved_candidate_ids`, `claimed_producer`다. `items`는 한 개 이상이고 unresolved는
빈 배열이어야 한다.

manifest exact key는 다음과 같다.

```text
version, session_binding, verification_items, repo_root,
expected_repo_id, expected_revision_ref, engine_sha, items,
finalization, unresolved_candidate_ids
```

`prepare-batch`는 transcript와 모든 item 입력을 두 번 읽어 drift를 확인하고 projection을 직접 만든다.
runner는 실행 직전 다시 계산해 manifest와 다르면 item 실행 전 0-write 실패한다. 기존 비세션
BatchBinding shape는 바꾸지 않고 session variant만 `session_binding_sha256`과
`item_verification_sha256`을 추가한다.

## 4. normal processing report와 receipt chain

`SessionProcessingReportV1` exact key는 다음과 같다.

```text
version, session_binding, verification_items, planned_objects,
outcome, batch_report, resume, closure_id
```

`closure_id`는 자신을 제외한 report canonical JSON의 SHA-256이다. report에는 zero-work 또는
unresolved nullable field가 없다.

| outcome | batch_report | resume | marker |
|---|---|---|---|
| `committed` | item 1개 이상, 하나 이상 committed, 나머지 committed/no_changes, `finalized=true`, finalization 성공 | `null` | 작성 |
| `no_changes` | item 1개 이상, 전부 exact no-change receipt, 허용된 index skip, 나머지 finalization 성공 | `null` | 작성 |
| `failed` | runner가 durable initial report를 만든 뒤 실패한 상태와 receipt/finalization 원문 | `{stage,artifact}` | 금지 |

manifest parse나 preflight가 실패해 durable initial report 전이면 processing report 파일을 만들지 않고
고정 CLI 오류만 출력한다. runner는 item key 순서의 durable receipt와 SessionBatchBinding을 recovery해
report에 결속한다. `SessionCompletion`은 report 값만 믿지 않고 receipt file bytes, execution state,
현재 corpus fingerprint, finalization 원문 hash를 다시 검증한다.

## 5. marker v2와 재시도

marker exact key는 `version`, `state`, `uuid`, `transcript_sha256`, `closure_id`, `outcome`,
`receipt_ids`, `processed_at`, `replaced_legacy_sha256`다.

`SessionCompletion`은 anchored sessions directory 안 UUID별 lock을 잡고 marker를 다시 읽는다. 같은
lock 안에서 transcript를 재확인하고 temp write, file fsync, atomic replace, directory fsync를 수행한다.

| live marker | 요청 | 결과 |
|---|---|---|
| 없음 | valid committed/no_changes closure | marker v2 작성 |
| 같은 valid v2 UUID·transcript·closure | 같은 report | byte-preserving 성공 no-op |
| 다른 valid v2, stale v2, malformed | 어떤 완료 요청 | `session_completion_conflict`, 0-write |
| legacy | precondition 없음·불일치 | `session_legacy_marker_precondition_required`, 0-write |
| legacy | lock 안 live bytes SHA와 exact precondition | valid closure일 때만 v2 교체 |
| symlink·비정규·hardlink | 어떤 요청 | 경계 오류, 0-write |
| temp만 남음 | 같은 report 재시도 | temp를 marker로 보지 않고 정상 재시도 |

`session list`는 `processed|unprocessed|legacy_unverified|stale_v2|invalid_marker`를 구분한다. 현재
transcript와 맞는 valid v2만 processed다.

## 6. 구현 경계

한 writer가 다음 순서의 90분 이하 child를 처리한다.

1. canonical item projection, SessionBindingV1, SessionBatchBindingV1과 기존 BatchBinding read 호환
2. `prepare-batch`와 runner의 normal manifest·report·durable recovery
3. `session complete`, marker v2 lock·retry·legacy CAS·session list 상태
4. session-ingest template·installer·architecture 문서와 두 번째 설치 무변경

zero-work 또는 unresolved 지원을 이 child에 끼워 넣지 않는다.

## 7. 완료 조건과 검증 연결

| 완료 조건 | 정확한 명령 | 기대 관측 |
|---|---|---|
| 1. 세 효과 소유자와 normal-only 입력 경계가 하나로 고정된다 | `rg -n 'prepare-batch|run_ingest_batch.py|SessionCompletion|session_zero_work_contract_required|session_unresolved_contract_required' docs/specs/2026-08-25-session-completion-repair-design.md` | manifest·runner·marker writer 각각 하나, empty/unresolved 0-write 오류 모두 존재 |
| 2. transcript→verification→planned objects→item receipt→finalization→closure chain이 exact다 | `.venv/bin/python -m pytest -q tests/test_session_completion.py tests/test_corpus_io.py -k 'binding or receipt_chain or closure or drift'` | 정상 chain 성공, transcript/verify/receipt/finalization drift·위조는 marker 0-write |
| 3. committed/no_changes/failed 조합과 public runner·complete 관측이 표와 같다 | `.venv/bin/python -m pytest -q tests/test_session_completion.py tests/test_cli.py -k 'committed or no_changes or failed or unsupported'` | normal 3 outcome exact, empty/unresolved는 corpus·report·marker 0-write |
| 4. marker absent/same/conflict/legacy/filesystem 상태가 lock 안에서 결정된다 | `.venv/bin/python -m pytest -q tests/test_session.py tests/test_session_completion.py -k 'marker or legacy or concurrent or symlink or hardlink'` | exact retry bytes 보존, conflict·stale·legacy mismatch 0-write, list 상태 exact |
| 5. child 경계·설치·전체 회귀와 독립 admission 판정이 닫힌다 | `.venv/bin/python -m pytest -q && .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'` | 전체 성공, installer 변경 시 두 번째 설치 무변경, 고정 candidate에 A1 high/A2~A5 PASS·Critical 0/Major 0 또는 RETURN 기록 |

독립 검증 묶음은 1) 계약 inspection, 2) binding·receipt, 3) public outcome, 4) marker·전체 회귀 네 개다.
