# session zero-work·미해결 후보 종료 설계

- 작성일: 2026-08-25
- 상태: 신규 design admission 후보, 독립 검수 전
- 선행 계약: [정상 session completion](2026-08-25-session-completion-repair-design.md)
- 대상: `zero_objects`, `unresolved_only`, `partial_unresolved`, zero-work `failed`

## 1. 분리 원칙

이 설계는 정상 SessionProcessingReportV1 schema를 넓히지 않는다. zero-work 성공·실패는
`ZeroWorkCompletionReportV1`, 미해결 후보 중단은 `SessionDeferredReportV1`이라는 서로 구분되는 exact
variant를 쓴다. `session complete`는 valid zero-work 성공만 marker로 닫고 deferred report는 절대 완료로
받지 않는다.

## 2. 상태 조합

| item 수 | unresolved 수 | attestation | finalization | 결과 | 외부 효과 소유자 |
|---|---|---|---|---|---|
| 0 | 0 | valid | 성공 | `zero_objects` | runner가 finalization·receipt·report, SessionCompletion이 marker |
| 0 | 0 | valid | 실패 | zero-work `failed` | runner가 실패 report, marker writer 없음 |
| 0 | 0 | 없음·invalid | 어떤 값 | invalid, 0-write | 없음 |
| 0 | 1+ | null | 실행 안 함 | `unresolved_only` | prepare/runner가 deferred report만 create-only |
| 1+ | 1+ | null | 실행 안 함 | `partial_unresolved` | item preflight가 deferred report만 create-only |
| 1+ | 0 | 어떤 값 | 어떤 값 | 정상 session 계약으로 위임 | 이 설계가 효과를 만들지 않음 |
| 그 밖의 조합 | 어떤 값 | 어떤 값 | 어떤 값 | invalid, 0-write | 없음 |

unresolved가 하나라도 있으면 item mutation, transaction, durable item receipt, finalization, marker를 모두
시작하지 않는다.

## 3. ZeroWorkAttestationV1

exact key는 `version`, `reason`, `claimed_producer`, `claimed_verifiers`, `checks`다.
`reason=zero_objects`다.

actor는 #33의 claimed identity를 쓰고 verifier는 producer와 다른 agent 또는 human이 최소 한 명이어야
한다. checks는 다음 ID를 정확히 한 번씩 가진다.

- `session.zero-work.no-durable-knowledge`
- `session.zero-work.no-unresolved-candidates`

outcome은 모두 pass이고 summary는 비어 있지 않다. 엔진은 구조·독립성·transcript 결속을 검증하지만
주장의 의미적 진실을 transcript에서 다시 추론하지 않는다. producer는 unresolved 목록의 완전성을,
verifier는 zero-work 두 판단을 확인했다는 역할별 공동 주장을 소유한다.

attestation canonical SHA는 transcript size/hash, zero-work binding, report, receipt, closure ID에
결속된다.

## 4. zero-work 실행·receipt·report

runner는 corpus transaction을 만들지 않고 finalization contract의 관문을 실행한다.

- index rebuild만 `skipped=true`, `reason=zero_objects`
- lint, audit, graph, eval, 소비 데이터 checks는 선언대로 실행
- recall checks는 빈 배열과 `reason=zero_objects`를 함께 요구
- transactions와 item records는 빈 배열

`ZeroWorkExecutionReportV1` exact key는 `version`, `session_binding_sha256`, `execution_state`,
`before_corpus_fingerprint`, `after_corpus_fingerprint`, `finalization`, `failure`다. 성공은 before/after
fingerprint가 같고 `finalization.ok=true`, `failure=null`이다. 실패는 가능한 검사 원문을 finalization에
보존하고 `{stage,artifact}` failure를 둔다.

성공 뒤 runner는 `.brain-local/session-zero-work/<receipt-id>.json`에 create-only
`ZeroWorkReceiptV1`을 쓴다. exact key는 다음과 같다.

```text
version, receipt_id, kind, session_binding_sha256, execution_state,
before_corpus_fingerprint, after_corpus_fingerprint,
finalization_sha256, outcome
```

`kind=session_zero_work`, `outcome=zero_objects`다. receipt ID는 자신을 제외한 canonical JSON
SHA-256이다. temp write, file fsync, create-only rename, directory fsync 순으로 쓴다. 기존 exact bytes는
no-op, 다른 bytes·malformed는 `session_zero_work_receipt_conflict`로 0-write 실패한다.

`ZeroWorkCompletionReportV1`은 binding, attestation, execution report 원문, receipt, outcome,
closure_id를 exact 결속한다. 성공만 `session complete`가 execution state와 current corpus fingerprint,
durable receipt bytes, finalization SHA를 lock 안에서 다시 확인한 뒤 정상 marker v2를 쓴다. 실패 report는
resume만 가지며 marker를 금지한다.

## 5. 미해결 후보 중단과 새 시작

`SessionDeferredReportV1` exact key는 `version`, `session_binding`, `variant`,
`unresolved_candidate_ids`, `resume`, `closure_id`다. variant는
`unresolved_only|partial_unresolved`다. unresolved ID는 정렬·중복 없는 배열이다.

deferred report는 완료 receipt가 아니라 진단·재개 정보다. item 실행 전 create-only로 쓰며 transaction,
item receipt, finalization, marker를 만들지 않는다. 해결 뒤에는 current transcript와 전체 최종 item set으로
새 draft를 만들고 `session prepare-batch`부터 다시 시작한다. 과거 deferred report, manifest, receipt,
closure chain을 새 실행에 합치거나 resume하지 않는다.

`session complete`에 deferred report를 주면 `session_unresolved_candidates`로 marker 0-write 실패한다.

## 6. 구현 경계

한 writer가 다음 90분 이하 child로 나눈다.

1. zero/deferred exact variants와 조합 parser, claimed actor·attestation
2. zero-work finalization·fingerprint·atomic receipt와 성공/실패 report
3. unresolved preflight·deferred report·새 draft 재시작
4. `session complete` zero success 검증, template·installer·architecture 회귀

## 7. 완료 조건과 검증 연결

| 완료 조건 | 정확한 명령 | 기대 관측 |
|---|---|---|
| 1. item×unresolved×attestation×finalization 조합이 네 상태 또는 invalid를 유일하게 고른다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py -k 'state_matrix or invalid_combination'` | 표의 모든 조합 exact, invalid는 corpus·report·receipt·marker 0-write |
| 2. producer·독립 verifier와 attestation hash chain의 역할·한계가 고정된다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py -k 'attestation or producer or verifier or binding'` | 같은 actor·누락 check·transcript drift 거부, valid canonical hash 재계산 일치 |
| 3. zero-work finalization·fingerprint·receipt 성공/실패와 retry가 durable하다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py tests/test_corpus_io.py -k 'zero_objects or finalization or receipt or fingerprint or retry'` | index만 고정 skip, before=after, 성공 receipt exact/no-op, conflict·실패 marker 없음 |
| 4. unresolved variants가 item 실행 전 멈추고 해결 뒤 새 manifest로 시작한다 | `.venv/bin/python -m pytest -q tests/test_session_zero_work.py tests/test_cli.py -k 'unresolved_only or partial_unresolved or deferred or restart'` | transaction·receipt·marker 0개, deferred report 존재, 과거 chain 재사용 거부 |
| 5. normal schema 불변·child 경계·설치·전체 회귀와 독립 판정이 닫힌다 | `.venv/bin/python -m pytest -q && .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'` | normal committed/no_changes 동작·schema 불변, 전체 성공, A1 high/A2~A5 PASS·Critical 0/Major 0 또는 RETURN 기록 |

독립 검증 묶음은 1) state/actor, 2) zero receipt, 3) deferred restart, 4) normal·전체 회귀 네 개다.
