# Ingest Recovery Baseline

engine_source_head: `36baa7347f3f5b6e24c1da21475150b882e413e6`

engine_worktree_head: `36baa7347f3f5b6e24c1da21475150b882e413e6`

engine_source_dirty_paths:

- `M CLAUDE.md`
- `M src/project_brain/assembly.py`
- `M src/project_brain/ingest.py`
- `M src/project_brain/router.py`
- `M tests/test_assembly.py`
- `M tests/test_ingest.py`
- `M tests/test_router.py`
- `?? AGENTS.md`
- `?? docs/plans/2026-07-27-ingest-fix-execution-plan.md`
- `?? docs/reports/2026-07-27-plan-delta-bg.md`
- `?? docs/reports/2026-07-27-two-ingest-session-review.md`
- `?? docs/reports/2026-07-28-brain-ingest-redesign-review.html`
- `?? docs/superpowers/plans/2026-07-27-handoff-consumer.md`
- `?? docs/superpowers/plans/2026-07-28-brain-ingest-recovery.md`

bb2_head: `d1294e7032d6304fe4371e7792b7a8e3010f3e5c`

bb2_dirty_paths:

- `M .agents/skills/guardrails/SKILL.md`
- `M .agents/skills/guardrails/hooks/block-dangerous-git.sh`
- `M .agents/skills/guardrails/hooks/block-pbxproj-settings.sh`
- `M .agents/skills/guardrails/hooks/tests/test_block_dangerous_git.py`
- `M Podfile.lock`
- `M brain/checks/test_real_corpus.py`
- `M brain/objects/code/code.disturb-bubble-system.bubble-object-factory-disturb-creation-0.json`
- `M brain/objects/code/code.disturb-bubble-system.bubble-object-factory-disturb-creation-1.json`
- `M brain/objects/code/code.disturb-bubble-system.bubble-object-factory-disturb-creation-2.json`
- `M brain/objects/code/code.disturb-bubble-system.bubble-object-factory-disturb-creation-3.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-base-class.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-list.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-support-list-0.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-support-list-1.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-support-list-2.json`
- `M brain/objects/code/code.disturb-bubble-system.disturb-support-list-3.json`
- `M brain/objects/code/code.disturb-bubble-system.ext-enum-factory.json`
- `M brain/objects/code/code.disturb-bubble-system.ext-sprite-tutorial.json`
- `M brain/objects/code/code.disturb-bubble-system.ext-stagecode.json`
- `M brain/objects/code/code.disturb-bubble-system.score-init.json`
- `M brain/objects/code/code.disturb-bubble-system.term-bubble-object-factory.json`
- `M brain/objects/code/code.disturb-bubble-system.term-create-bubble-object-disturb.json`
- `M brain/objects/code/code.disturb-bubble-system.term-disturb-support-list-field.json`
- `M brain/objects/code/code.disturb-bubble-system.term-disturb-support-type.json`
- `M brain/objects/code/code.disturb-bubble-system.term-initilize-with-game-start-object.json`
- `M brain/objects/code/code.ingame-area-expansion.admin-row-adjustment--4.json`
- `?? .agents/skills/guardrails/hooks/tests/run-tests.sh`
- `?? .agents/skills/guardrails/hooks/tests/test_block_pbxproj_settings.py`

bb2_local_exclude_brain: true

검증 근거: `git check-ignore -v brain/objects/code/code.petskill-kamehameha.aim-degree-limit--0.json`은 `.git/info/exclude:18:/brain`을 반환했다.

baseline_pytest: `PASS — 674 passed, 32 subtests passed in 16.40s`

baseline_template_unittest: `PASS — Ran 75 tests in 8.837s`

## Task 12 final engine verification

verified_code_head:
`88428eac2a61fd60d3b351a65293a11d687b557b`

이 값은 이 보고서만 추가하기 전, 실제로 검증한 엔진 코드 HEAD다. 같은 commit은 자기
SHA를 자기 내용에 넣을 수 없으므로 이 tracked 보고서에는 최종 보고서 commit SHA를
예측해 쓰지 않는다. 최종 Task 12 commit SHA와 그 SHA에서 다시 실행한 검증 결과는
ignored
`.superpowers/sdd/2026-07-28-brain-ingest-recovery/task-12-engine-receipt.md`에 기록한다.
Task 13 이후의 `ENGINE_SHA`는 이 외부 receipt가 가리키는 최종 Task 12 commit SHA만
사용한다.

### Pre-report gates

- `PYTHONPATH=src .venv/bin/python -m pytest -q`
  - `PASS — 1146 passed, 64 subtests passed in 91.37s`
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'`
  - `PASS — Ran 99 tests in 10.690s`
- `uv lock --check`
  - `PASS — Resolved 72 packages in 12ms`
  - `uv.lock`은 `verified_code_head`와 비교해 변경 없음.
- 시작 상태
  - `verified_code_head`에서 tracked/untracked worktree 상태가 clean임을 확인했다.

### Placeholder scan

명령:

```bash
rg -n 'TODO|FIXME|NotImplemented|pass\s*(#.*)?$' src/project_brain tests
```

결과는 28건이며 모두 문맥을 읽어 다음처럼 분류했다. 의도되지 않은 제품
placeholder는 0건이다.

의도된 예외 타입의 빈 본문 3건:

- `src/project_brain/schema.py:142` — `SchemaError` 표식 예외 타입.
- `src/project_brain/stale_check.py:77` — `GitError` 표식 예외 타입.
- `src/project_brain/ingest.py:21` — `IngestError` 표식 예외 타입.

의도된 예외 처리·정리·경합 처리의 no-op 19건:

- `src/project_brain/embedder.py:87` — 선택적 `torch` 스레드 고정 실패 시 모델
  로딩을 계속하는 명시적 fallback.
- `src/project_brain/snapshot.py:624` — output이 brain 밖이라는 정상
  `relative_to` 실패 경로.
- `src/project_brain/snapshot.py:656` — 아직 snapshot이 없다는 정상 경로.
- `src/project_brain/installer.py:117` — 실패한 임시 파일 정리 중 이미 없는 파일.
- `src/project_brain/installer.py:130` — atomic 교체 뒤 이미 없는 임시 파일.
- `src/project_brain/installer.py:157` — retirement backup 정리 중 이미 없는 파일.
- `src/project_brain/installer.py:430` — manifest 임시 파일 정리 중 이미 없는 파일.
- `src/project_brain/installer.py:437` — 확정된 retirement backup이 이미 정리된 경로.
- `src/project_brain/cli.py:160` — atomic CLI 출력 임시 파일이 이미 교체된 경로.
- `src/project_brain/corpus_io.py:137` — pinned FD close 중 이미 닫힌 descriptor.
- `src/project_brain/corpus_io.py:178` — no-follow directory 생성 경합에서 상대가 먼저
  만든 정상 경로.
- `src/project_brain/corpus_io.py:1143` — restore-state marker가 없다는 정상 경로.
- `src/project_brain/corpus_io.py:1297` — 복구 실패를 기록하는 최후 시도 자체가 실패한
  경우 원래 복구 오류를 보존.
- `src/project_brain/corpus_io.py:1311` — 복구용 descriptor 정리 중 이미 닫힌 경로.
- `src/project_brain/corpus_io.py:2099` — rollback 실패 기록의 최후 시도 실패 시 원래
  오류를 보존.
- `src/project_brain/corpus_io.py:2113` — transaction descriptor 정리 중 이미 닫힌 경로.
- `src/project_brain/templates/ingest/scripts/run_ingest_batch.py:96` — report 임시 파일이
  이미 교체된 정상 정리 경로.
- `src/project_brain/templates/ingest/scripts/run_ingest_batch.py:368` — staged 하위
  directory 권한 복구의 best-effort 정리.
- `src/project_brain/templates/ingest/scripts/run_ingest_batch.py:372` — staged root 권한
  복구의 best-effort 정리.

명시적으로 채워 사용하는 ingest 템플릿 슬롯 4건:

- `src/project_brain/templates/ingest/scripts/extract_template.js:22` — group별 extract
  prompt 슬롯.
- `src/project_brain/templates/ingest/scripts/extract_template.js:23` — 실행 환경이 주입하는
  `llmExtract` 호출 슬롯.
- `src/project_brain/templates/ingest/scripts/extract_template.js:24` — group별 verify
  prompt 슬롯.
- `src/project_brain/templates/ingest/scripts/extract_template.js:25` — 실행 환경이 주입하는
  `llmVerify` 호출 슬롯.

의도된 테스트 fixture 2건:

- `tests/test_corpus_io.py:56` — crash injection 전용 `InjectedCrash` 예외 타입.
- `tests/test_corpus_io.py:1160` — lock 진입 자체가 실패하는지 확인하는 빈 context body.

### Direct writer scan

명령:

```bash
rg -n 'BrainStore\.save_object' src/project_brain
```

출력 0건, 종료 코드 1이다. 제품 코드의 `BrainStore.save_object` 직접 writer는 0건이며
모든 제품 mutation은 공통 transaction 경계를 사용한다.

### Static type and shape comparison

수동 대조 결과는 모두 일치했다.

- Mutation operation
  - `src/project_brain/mutation.py:58-68`의 `MutationOperation`과
    `src/project_brain/corpus_io.py:86-96`의 manifest allowlist는 다음 9개 문자열로
    정확히 같다:
    `ingest`, `promote`, `promote_auto`, `mark_checked`, `projection`,
    `projection_repair`, `context_replace`, `id_only_migration`,
    `display_migration`.
  - `src/project_brain/mutation.py:1317-1355`는 seed와 `MutationManifest.operation`에
    `request.operation.value`를 쓴다.
  - `src/project_brain/cli.py:397-407`은 별도 변환 없이 `manifest.operation`을 CLI
    transaction JSON의 `operation`으로 낸다.
  - 설치 runtime은 ingest receipt만 받으므로
    `src/project_brain/templates/ingest/scripts/finalize_ingest.py:85-128`에서 같은
    `"ingest"` 값을 exact 검증한다.
- Journal state
  - `src/project_brain/corpus_io.py:28-35`의 값은 `preparing`, `prepared`,
    `committing`, `committed`, `rolled_back`, `recovery_required`다.
  - writer는 같은 파일의 `1803`, `1954`, `1959`, `2067`, `2089-2094`에서 enum
    `.value`만 기록하고, reader/model validator는 `2607`에서 `JournalState(...)`로
    다시 파싱한다. terminal set도 `73-76`의 enum 값으로 구성된다.
- Audit/access state
  - `src/project_brain/quote_access.py:12-16`의 `AccessState`는 `allow`, `deny`,
    `indeterminate`이고, `src/project_brain/audit.py:191-196`은
    `evaluate_quote_access(...).final.value`를 `quote_access` JSON에 그대로 쓴다.
  - `src/project_brain/symbol_verify.py:35-39`의 symbol 값은 `verified`,
    `manual_verified`, `mismatch`, `unsupported`이고,
    `src/project_brain/audit.py:75-143`의 audit 변환 문자열과 같다.
  - audit의 code quote 값은 같은 함수의 `missing`, `unverifiable`, `error`,
    `mismatch`, `verified`로 닫혀 있다.
  - `src/project_brain/schema.py:104-107`의 redaction 값은 `raw_local`, `staged`,
    `approved`, `rejected`이고, `src/project_brain/quote_access.py:69-85`는
    `approved`만 allow, 그 밖의 유효 값은 deny로 처리한다.
  - `src/project_brain/cli.py:822-849`는 `run_audit` report를 값 변환 없이 JSON으로
    직렬화한다.
- Manifest, receipt, binding, item record
  - `src/project_brain/mutation.py:94-109`의 `MutationManifest` 14개 필드는
    `transaction_id`, `operation`, `engine_sha`, `creates`, `updates`, `deletes`,
    `renames`, `reference_rewrites`, `auxiliary_updates`, `before_fingerprint`,
    `expected_after_fingerprint`, `grandfathered_problems_before`,
    `grandfathered_problems_after`, `batch_binding`이다.
  - `src/project_brain/corpus_io.py:2709-2734`의 canonical manifest reader도 위
    14개 필드의 exact set을 요구한다.
  - CLI transaction receipt와
    `src/project_brain/templates/ingest/scripts/finalize_ingest.py:19-29`의
    `_TRANSACTION_FIELDS`는 `ok`, `transaction_id`, `operation`, `committed`,
    `manifest_sha256`, `before_fingerprint`, `after_fingerprint`, `ingested_ids`,
    `ingested_count` 9개로 같다.
  - `src/project_brain/transaction_receipt.py:17-51`의 `BatchBinding`은
    `batch_manifest_sha256`, `item_key`, `item_input_fingerprint`,
    `verify_json_sha256`, `domain_spec_py_sha256`, `repo_root`, `brain_root`,
    `brain_root_device`, `brain_root_inode`, `expected_repo_id`,
    `expected_revision_ref`, `target_revision_sha`, `engine_root`, `engine_sha`
    14개 exact field를 갖고, 같은 파일 `67`에서 mapping의 exact set을 검증한다.
  - batch의 `src/project_brain/templates/ingest/scripts/run_ingest_batch.py:660-666`과
    finalizer의 `src/project_brain/templates/ingest/scripts/finalize_ingest.py:131-165`
    모두 item record를 `binding`, `status`, `failure`, `transaction` 4개 exact
    field로 사용한다.
  - batch resume report는
    `src/project_brain/templates/ingest/scripts/run_ingest_batch.py:980-1007`의
    `repo_root`, `brain_root`, `brain_root_device`, `brain_root_inode`,
    `expected_repo_id`, `expected_revision_ref`, `target_revision_sha`,
    `engine_sha`, `engine_root`, `repo_root_device`, `repo_root_inode`,
    `engine_root_device`, `engine_root_inode`, `manifest_sha256`,
    `manifest_fingerprint`, `expected`, `item_records`, `succeeded`, `failed`,
    `transactions`, `isolation_baseline`, `finalized`, `finalization`,
    `finalize_failure` 24개 exact field를 요구한다.
  - finalizer output과 batch parser는 `ok`, `transactions`, `commands`,
    `isolation`, `unmerged`, `recall_checks`, `errors` 7개 exact field로
    일치한다(`finalize_ingest.py:549-552`,
    `run_ingest_batch.py:931-955`).

### Scope and source state

- 원본 project-brain은 read-only로만 확인했으며 HEAD는 Task 0과 같은
  `36baa7347f3f5b6e24c1da21475150b882e413e6`이다. 이 보고서의 기존 Task 0
  dirty-path baseline은 수정하지 않았다. 이후 생긴 사용자 소유 dirty path도 건드리지 않았다.
- BB2는 read-only로만 확인했으며 HEAD는 Task 0과 같은
  `d1294e7032d6304fe4371e7792b7a8e3010f3e5c`이다. 기존 corpus와 사용자 소유
  dirty path를 수정하지 않았다.
- Task 12 tracked 변경 허용 범위는 이 보고서 한 파일뿐이다.
