# 세션 적재 완료와 처리 marker 결속 보강 설계

- 작성일: 2026-08-25
- 상태: 설계 복귀 수정안, 최종 독립 재검수 대기
- 대상: GitHub #3과 부모 #1
- 기준 후보: `75e97fa98308b8bd7434070e05a99e69f2a5adef`

## 1. 발견한 공백

기준 후보는 검증 묶음의 `pass`·`fixed` 판정과 적재 item별 영수증, 최종화 결과를 엄격하게
검사한다. 그러나 세션의 최종 완료 표시는 이 결과와 결속되지 않았다.

- `project-brain session mark-processed <uuid>`는 UUID만으로 즉시 marker를 쓴다.
- marker는 transcript bytes, 검증 결과, 적재 영수증, 최종화 결과를 가리키지 않는다.
- 같은 UUID를 다시 호출하면 이전 marker를 덮어쓰므로 충돌과 정확한 재시도를 구별하지 못한다.
- 설치 스킬은 적재 실패에는 marker를 금지하지만, 3회 검토 뒤 미합의 후보만 남은 경우에는
  marker를 허용한다. "정확한 성공 영수증에서만 완료"라는 #3 계약과 충돌한다.
- 현재 batch runner, coverage, finalizer는 모두 item이 최소 한 개라고 전제한다. 진짜 zero-work
  session을 우연한 `no_changes`로 표현하거나 빈 배열만 허용해서는 안전하게 닫을 수 없다.

파일 존재나 종료 코드만으로 완료를 복구하지 않는다. transcript부터 검증, 적재, 최종화가 같은
세션 실행에 속한다는 사실을 durable binding과 canonical report가 함께 증명해야 한다.

## 2. 채택할 Module과 공개 Seam

계층을 뒤집지 않기 위해 engine core에 `session_completion_contract.py`를 둔다. 이 모듈이
`SessionBindingV1`, item verification projection, session batch binding, zero-work receipt,
processing report의 exact parser와 canonical hash를 소유한다. 설치 batch runner와
`SessionCompletion`은 둘 다 이 모듈을 import한다. 엔진이 설치 template script를 역으로 import하거나
두 구현이 report shape를 따로 재구성하지 않는다.

`SessionCompletion`은 transcript와 processing report, durable receipt를 검증하고 marker를 쓰는
유일한 효과 소유자다.

session manifest는 설치 스킬이나 agent가 JSON을 손으로 만들지 않는다. 아래 명령이 transcript,
현재 verify JSON, coverage를 읽고 `SessionBindingV1`과 item verification projection을 계산해
create-only로 쓴다.

```bash
project-brain session prepare-batch \
  --transcript <absolute-session.jsonl> \
  --draft <session-batch-draft.json> \
  --output <session-batch-manifest.json>
```

`run_ingest_batch.py`는 이 manifest를 소비해 `SessionProcessingReportV1`을 만드는 유일한
producer다. session-ingest agent는 draft의 item 입력, 의미 판정인
`unresolved_candidate_ids`, 또는 아래 zero-work attestation만 제안할 수 있다. binding,
verification projection, batch report, zero-work receipt, outcome, closure ID는 만들지 않는다.

```bash
project-brain session complete \
  --transcript <absolute-session.jsonl> \
  --report <session-processing-report.json> \
  [--brain-root <path>] \
  [--replace-legacy-marker-sha256 <64hex>]
```

호출자는 UUID, 완료 상태, note, marker 내용, receipt ID를 직접 넘기지 않는다. legacy 교체 hash는
marker 내용이 아니라 명시적인 compare-and-swap precondition이다. UUID는 transcript 파일명에서
읽으며 report와 정확히 같아야 한다. `SessionCompletion`은 corpus·index·Git을 쓰지 않는다.

구현 후 기존 `mark-processed` 쓰기 명령은 고정 오류 `session_completion_report_required`로
실패시키고 위 명령을 안내한다. 현재 기준 후보의 `mark-processed`는 아직 UUID만으로 marker를 바로
쓰므로 이 문장은 목표 동작이며 현재 동작이 아니다.

## 3. 공통 결속 계약

### 3.1 canonical JSON

모든 ID hash 입력은 `json.dumps(..., ensure_ascii=False, allow_nan=False, sort_keys=True,
separators=(",", ":"))`의 UTF-8 bytes다. hash 입력에는 newline을 넣지 않고, 파일로 보존하는 bytes는
그 canonical bytes 뒤에 `\n` 하나를 붙인다. parser는 의미상 같은 JSON이 아니라 이 exact file
bytes를 요구한다.

### 3.2 item verification projection

session completion v1은 현재 session-ingest가 사용하는 assembled coverage item만 받는다. direct
coverage를 transcript 완료에 쓰면 `session_binding_mode_unsupported`로 실패하며, 후속 버전에서
별도 의미 검증 계약을 먼저 정한다.

각 item projection exact key는 `item_key`, `mode`, `coverage_sha256`, `verify_json_sha256`, `groups`다.
`mode`는 `assembled`이고 groups는 coverage의 `verify_groups.names` 순서와 exact 일치한다. group은
기존 runtime 용어를 그대로 사용한다.

```json
{
  "item_key": "feature-one",
  "mode": "assembled",
  "coverage_sha256": "64hex",
  "verify_json_sha256": "64hex",
  "groups": [
    {
      "group": "결정",
      "verify": {
        "verdict": "pass",
        "corrected_atoms": []
      }
    }
  ]
}
```

`verify` exact key는 `verdict`, `corrected_atoms`다. verdict는 `pass|fixed`이고, pass면 staged
verify JSON의 `extract.atoms`와 exact 같아야 한다. 이 판정은 batch runner가 staged verify bytes와
coverage를 함께 읽어 공통 contract module로 계산한다. item projection hash는 이 JSON의 SHA-256이다.

### 3.3 SessionBindingV1과 durable item 결속

`SessionBindingV1` exact key는 다음과 같다.

```json
{
  "version": 1,
  "uuid": "01234567-89ab-cdef-0123-456789abcdef",
  "transcript_size": 123,
  "transcript_sha256": "64hex",
  "verification_projection_sha256": "64hex",
  "planned_objects_sha256": "64hex",
  "zero_work_attestation_sha256": null
}
```

verification projection은 item key 순으로 정렬된 item projection 배열이다. planned objects는 모든
item coverage의 `expected_objects`를 합친 뒤 `(id,kind)`로 정렬·중복 제거한 배열이다. report의
`planned_objects`와 batch report의 `item_records[].expected_objects` 합집합이 이 배열과 exact 같아야
한다. `zero_work_attestation_sha256`은 normal·unresolved variant에서 `null`, explicit zero-work에서
아래 attestation canonical JSON의 SHA-256이다.

기존 비세션 `BatchBinding` shape는 바꾸지 않는다. session batch는 별도
`SessionBatchBindingV1` variant를 쓰며 기존 필드에 `session_binding_sha256`과
`item_verification_sha256`을 추가한다. batch manifest parser는 기존 exact field set 또는 session
variant exact field set 둘 중 하나만 허용한다. 각 mutation journal의 manifest와 receipt recovery가
이 variant를 그대로 검증하므로, processing report에 UUID·hash를 나중에 적어 넣는 것만으로는 정상
receipt를 위조할 수 없다.

### 3.4 SessionBatchManifestV1

`prepare-batch`가 받는 draft exact key는 `repo_root`, `expected_repo_id`,
`expected_revision_ref`, `engine_sha`, `items`, `finalization`, `unresolved_candidate_ids`,
`zero_work_attestation`이다. item exact key는 `key`, `verify_json`, `domain_spec_py`이며 세 값은 현재 batch
manifest와 같은 상대 경로·중복 규칙을 따른다. agent가 만든 draft는 durable 완료 증거가 아니며
다시 시작할 때 입력으로만 쓴다.

`SessionBatchManifestV1` top-level exact key는 다음과 같다.

```text
version, session_binding, verification_items, repo_root,
expected_repo_id, expected_revision_ref, engine_sha, items,
finalization, unresolved_candidate_ids, zero_work_attestation
```

`version=1`이고 normal variant는 `items`가 한 개 이상, `zero_work_attestation=null`이다. 각 manifest item은
draft와 같은 세 key만 가지며, `verification_items`의 같은 `item_key`와 일대일로 대응한다.
`prepare-batch`는 transcript와 모든 item 입력을 두 번 읽어 drift를 확인하고, coverage에서
planned objects와 verification projection을 직접 계산한 뒤 `session_binding`을 만든다. runner는
실행 직전 같은 파일에서 projection을 다시 계산해 manifest 값과 다르면 0-write로 실패한다.

zero-work의 의미 판정은 엔진이 transcript를 재추출해 발명하지 않는다. agent가 다음 exact
`ZeroWorkAttestationV1`을 제안하고 producer와 다른 agent 또는 human verifier를 최소 한 명 둔다.

```json
{
  "version": 1,
  "reason": "zero_objects",
  "claimed_producer": {"kind": "agent", "id": "agent:assembler", "version": "1"},
  "claimed_verifiers": [
    {"kind": "agent", "id": "agent:independent-reviewer", "version": "1"}
  ],
  "checks": [
    {
      "id": "session.zero-work.no-durable-knowledge",
      "outcome": "pass",
      "summary": "transcript에서 적재할 durable knowledge가 없다."
    },
    {
      "id": "session.zero-work.no-unresolved-candidates",
      "outcome": "pass",
      "summary": "미확정 후보로 남겨야 할 항목도 없다."
    }
  ]
}
```

actor exact key와 한계는 evidence contract의 claimed identity와 같다. verifier 배열은 identity
순으로 정렬·중복 없이 두고 producer와 같은 identity를 거부한다. checks는 위 두 ID를 정렬해
정확히 한 번씩 가지며 outcome은 모두 `pass`, summary는 비어 있지 않아야 한다. 엔진은 이 주장의
구조·독립성·transcript 결속을 검증하지만 의미적 진실을 재추출해 보증하지 않는다. attestation
canonical hash는 `SessionBindingV1`, processing report, closure ID, durable zero-work receipt chain에
결속된다.

zero-item variant는 `items=[]`다. `unresolved_candidate_ids`가 비어 있으면
유효한 `zero_work_attestation`과 아래 zero-work finalization contract를 요구하고,
한 개 이상이면 `zero_work_attestation=null`, `finalization=null`인 `unresolved_only` 입력이다. 다른 조합은
parser가 거부한다. normal item과 정렬된 unresolved ID가 함께 있으면 `partial_unresolved` 입력이다.
v1은 unresolved가 하나라도 있으면 batch item을 실행하지 않는 fail-closed preflight를 사용한다.

## 4. SessionProcessingReport v1

top-level exact key는 `version`, `session_binding`, `verification_items`, `planned_objects`,
`unresolved_candidate_ids`, `zero_work_attestation`, `outcome`, `batch_report`, `zero_work_report`,
`zero_work_receipt`, `resume`, `closure_id`다.

- `verification_items`는 위 item projection 배열이다.
- `unresolved_candidate_ids`는 session-ingest agent와 사용자 검토가 만든 정렬·중복 없는 후보 ID다.
  엔진은 transcript 의미를 다시 추출하지 않으므로 이 목록의 의미적 완전성은 producer 경계다.
  다만 목록 자체와 producer가 선택한 결과는 closure에 결속하며 한 개라도 있으면 marker를 금지한다.
- `zero_work_attestation`은 `zero_objects`에서 manifest와 byte-exact 같은 valid object이고 그 밖에는
  `null`이다. `SessionCompletion`은 canonical hash와 claimed producer/verifier 경계를 다시 검증한다.
- `batch_report`는 normal variant에서 현재 설치 runtime의 canonical report exact object다. 공통
  contract module이 현재 top-level exact key set, item record exact shape, finalization, 각 durable
  receipt와 session binding을 검증한다. zero-item과 unresolved preflight에서는 `null`이다.
- `zero_work_report`는 zero-work finalization을 시작한 성공·실패에서만 아래 exact object이고 그
  밖에는 `null`이다. finalization 원문을 보존해 hash와 결과를 다시 검증할 수 있게 한다.
- `zero_work_receipt`는 `zero_objects`에서만 object이고 그 밖에는 JSON `null`이다.
- `resume`은 완료 outcome에서는 `null`, 비완료 outcome에서는 `{"stage": str, "artifact": str}`다.
- outcome exact enum은 `committed | no_changes | zero_objects | unresolved_only |
  partial_unresolved | failed`다.
- `closure_id`는 자신을 제외한 report canonical JSON의 SHA-256이며 엔진이 다시 계산한다.

outcome별 nullable 필드 조합은 다음 하나만 허용한다.

| outcome | `batch_report` | `zero_work_report` | `zero_work_receipt` | `resume` |
|---|---|---|---|---|
| `committed`, `no_changes` | 성공·`finalized=true` object | `null` | `null` | `null` |
| `zero_objects` | `null` | 성공·`finalization.ok=true` object | valid object | `null` |
| `unresolved_only`, `partial_unresolved` | `null` | `null` | `null` | object |
| normal `failed` | 실패 상태를 보존한 object | `null` | `null` | object |
| zero-work `failed` | `null` | 실패·`finalization.ok=false` object | `null` | object |

manifest parse나 실행 상태 해석처럼 canonical batch report를 시작하기 전에 실패하면 runner는
고정 CLI 오류만 출력하고 processing report 파일을 만들지 않는다. 따라서 `failed` report는
runner가 initial batch report를 durable하게 쓴 뒤 실패한 경우만 나타낸다.

완료 outcome의 transcript는 report 검증 전과 marker rename 직전에 다시 읽는다. UUID는 canonical UUID
문자열이고 transcript basename, binding UUID와 exact 같아야 하며 size/hash drift는
`session_transcript_changed`다.

## 5. 상태와 효과 소유자

| outcome | 요구 조건 | marker | 효과 소유자 |
|---|---|---|---|
| `committed` | item 1개 이상, 하나 이상 committed, 나머지 committed/no_changes, 모든 durable SessionBatchBinding exact, `finalized=true`, `finalization.ok=true` | 작성 | `SessionCompletion` |
| `no_changes` | item 1개 이상, 전부 exact no_changes receipt, index rebuild만 skip, 나머지 finalization 성공 | 작성 | `SessionCompletion` |
| `zero_objects` | planned와 unresolved가 비고 independent verifier가 붙은 attestation과 아래 durable ZeroWorkReceipt exact | 작성 | `SessionCompletion` |
| `unresolved_only` | planned가 비고 unresolved가 한 개 이상, `batch_report=null` | 작성 금지, report 경로로 재개 | 없음 |
| `partial_unresolved` | planned와 unresolved가 모두 있고 preflight에서 item 실행 전 중단, `batch_report=null` | 작성 금지, draft/검증 단계로 재개 | 없음 |
| `failed` | normal batch 또는 zero-work finalization 실패·receipt 불일치 | 작성 금지 | 없음 |

corpus·index·batch report는 batch runner가 소유하고 marker는 `SessionCompletion`만 소유한다. 완료
검증 실패가 이미 성공한 corpus transaction을 되돌리지는 않지만 marker는 쓰지 않는다.

### 5.1 explicit zero-work

`zero_objects`를 빈 배열에 대한 `all()` 결과로 `no_changes`라 부르지 않는다. session manifest의
별도 exact zero-work variant는 `items=[]`, `session_binding`, 유효한 `zero_work_attestation`을
가진다. 일반 manifest의 item 최소 1개와 coverage expected object 최소 1개 계약은 유지한다.

batch runner는 transaction을 만들지 않고 다음 관문을 실행한다.

- index rebuild: 실행하지 않고 `skipped=true`, `reason=zero_objects`
- lint, audit, graph, eval, 데이터 레포 corpus checks: finalization contract에 선언된 그대로 실행
- recall checks: 빈 목록을 허용하되 zero-work finalization contract의
  `reason=zero_objects`를 함께 요구
- transactions와 item records: 빈 배열

`ZeroWorkExecutionReportV1` exact key는 `version`, `session_binding_sha256`, `execution_state`,
`before_corpus_fingerprint`, `after_corpus_fingerprint`, `finalization`, `failure`다. 성공이면
`finalization.ok=true`, before/after fingerprint가 같고 `failure=null`이다. 관문이 실패하면 가능한
검사 결과를 같은 exact `finalization` object에 보존하고 `failure={"stage": str,
"artifact": str}`를 둔다. 실패 report에는 receipt가 없고 marker도 쓰지 않지만, 이 object가
SessionProcessingReport에 남아 재개 지점을 설명한다.

성공 뒤 batch runner는 `.brain-local/session-zero-work/<receipt-id>.json`에 create-only
`ZeroWorkReceiptV1`을 원자적으로 보존한다. zero-work finalization contract exact key는
`reason`, `recall_checks`, `intentional_terminal_ids`, `expected_unmerged_locator_ids`이며 값은 각각
`zero_objects`, `[]`, 정렬·중복 없는 ID 배열, 정렬·중복 없는 ID 배열이다. finalization 결과는
normal 결과와 같은 exact key `ok`, `transactions`, `commands`, `isolation`, `unmerged`,
`recall_checks`, `errors`를 가지며 `transactions=[]`, `recall_checks=[]`다.

`ZeroWorkReceiptV1` exact key는 다음과 같다.

```text
version, receipt_id, kind, session_binding_sha256, execution_state,
before_corpus_fingerprint, after_corpus_fingerprint,
finalization_sha256, outcome
```

`execution_state` exact key는 `repo_root`, `repo_root_device`, `repo_root_inode`, `brain_root`,
`brain_root_device`, `brain_root_inode`, `expected_repo_id`, `expected_revision_ref`,
`target_revision_sha`, `engine_root`, `engine_root_device`, `engine_root_inode`, `engine_sha`다.
runner가 normal batch와 같은 resolver로 직접 만들며 caller 값은 받지 않는다. zero-work에서는
before/after corpus fingerprint가 같아야 한다. `finalization_sha256`은 processing report의
`zero_work_report.finalization` exact object canonical JSON SHA-256이다. `kind=session_zero_work`,
`outcome=zero_objects`이고 receipt ID는
`receipt_id`를 제외한 전체 exact object의 canonical JSON SHA-256이다.

receipt 경로가 없으면 temp write, file fsync, create-only rename, directory fsync 순서로 쓴다. 같은
receipt ID 파일이 이미 있고 canonical bytes가 exact 같으면 byte-preserving no-op다. bytes가 다르거나
malformed면 `session_zero_work_receipt_conflict`로 0-write 실패한다. `SessionCompletion`은 report
값만 믿지 않고 lock 안에서 execution state를 다시 해석하고, 현재 corpus fingerprint가 receipt의
before/after와 같은지, durable file bytes와 report에 보존된 finalization projection의 canonical
hash가 같은지 다시 검사한다.

normal `committed`·`no_changes`는 batch report의 item binding과 receipt를
`verification_mode=post_gate_object_tail`로 다시 recovery한다. 그 뒤 transcript와 execution state를
한 번 더 확인하고 marker rename을 수행한다.

`unresolved_only`와 `partial_unresolved`는 batch runner의 `--resume` 경로를 사용하지 않는다. corpus
transaction을 하나도 시작하지 않았으므로 unresolved가 해결되면 agent가 current transcript와 전체
최종 item set으로 새 draft를 만들고 `session prepare-batch`를 다시 실행한다. 이전 unresolved report는
진단·재개 정보일 뿐 최종 closure receipt chain에 합치지 않는다. 따라서 create-mode item을 일부
먼저 쓴 뒤 새 manifest에서 재실행하는 상태를 만들지 않는다.

## 6. marker v2, 동시 실행, legacy

marker v2 exact key는 `version`, `state`, `uuid`, `transcript_sha256`, `closure_id`, `outcome`,
`receipt_ids`, `processed_at`, `replaced_legacy_sha256`다. 마지막 값은 일반 완료에서 `null`이고 명시적
legacy 교체에서만 64hex다. receipt ID는 item key 순서이며 zero-work는 durable zero-work receipt ID
한 개다.

`SessionCompletion`은 anchored sessions directory 안의 UUID별 lock을 잡은 뒤 marker를 다시 읽고,
같은 lock 안에서 transcript 재확인과 temp+file fsync+atomic replace+directory fsync를 수행한다.
파일 없음 확인과 replace 사이를 lock 밖에 두지 않는다.

- 같은 valid v2의 UUID·transcript hash·closure ID: byte-preserving 성공 no-op
- 다른 valid v2, stale v2, malformed marker: conflict, 0-write
- legacy marker: 기본 conflict. `--replace-legacy-marker-sha256`가 lock 안 live bytes hash와 같고
  completion report가 모두 유효할 때만 v2로 교체
- symlink, 비정규 파일, hardlink 경계 이탈: 0-write 실패
- 중간 종료로 temp만 남음: marker로 보지 않고 같은 report 재시도

`session list`는 marker 상태를 `processed | unprocessed | legacy_unverified | stale_v2 |
invalid_marker`로 구분한다. 현재 transcript hash와 맞는 valid v2만 `processed=true`이며
`--unprocessed`는 나머지를 모두 포함한다. legacy를 영수증이 있었던 것으로 자동 승격하지 않는다.

## 7. 고정 오류와 재개 출력

실패 JSON exact key는 `ok`, `code`, `uuid`, `report`, `resume`이고 `ok=false`, `code`·`uuid`·`report`는
문자열, `resume`은 `null` 또는 `{"stage": str, "artifact": str}`다. 대표 코드는 다음과 같다.

- `session_completion_report_required`
- `session_binding_mode_unsupported`
- `session_report_invalid`
- `session_uuid_mismatch`
- `session_transcript_changed`
- `session_verification_mismatch`
- `session_unresolved_candidates`
- `session_receipt_mismatch`
- `session_zero_work_receipt_invalid`
- `session_zero_work_attestation_invalid`
- `session_finalization_incomplete`
- `session_legacy_marker_precondition_required`
- `session_completion_conflict`

## 8. 구현 티켓 경계

의존 순서대로 다음 네 ticket으로 나눈다.

1. 공용 canonical schema/hash, `ZeroWorkAttestationV1`, `SessionBindingV1`·`SessionBatchBindingV1`,
   기존 BatchBinding 읽기 호환
2. batch runner의 session binding 발행·durable recovery와 explicit zero-work receipt
3. `session complete`, marker v2 UUID lock·재시도·list 상태·명시적 legacy CAS 교체
4. session-ingest template, architecture 문서, installer 2회 무변경 회귀

## 9. 승인된 검증 경계

```bash
.venv/bin/python -m pytest -q \
  tests/test_session.py tests/test_cli.py tests/test_corpus_io.py \
  tests/test_architecture_docs.py -k 'session or receipt or architecture'
.venv/bin/python -m unittest \
  src.project_brain.templates.ingest.scripts.test_batch_tools \
  src.project_brain.templates.ingest.scripts.test_finalize_ingest
.venv/bin/python -m pytest -q \
  tests/test_installer.py tests/test_ingest_skill_contract.py \
  tests/test_ingest_skill_behavior_replay.py
```

installer는 임시 대상에 두 번 실행해 두 번째 report의 `created/updated/removed/adopted/skipped`가 모두
빈 배열인지 확인한다. 공개 `session complete`에서 여섯 outcome, UUID/transcript drift,
위조·stale receipt, zero-work durable file, zero-work 성공·실패 report와 finalization 원문 hash,
unresolved preflight의 corpus 0-write와 새 manifest 재시작, finalization 실패, 동시 conflicting
closure, exact retry bytes 보존, legacy 상태와 CAS 교체를 관측한다. 최종 완료는 AGENTS.md의 전체 엔진 pytest와 설치
runtime unittest까지 통과해야 한다.
