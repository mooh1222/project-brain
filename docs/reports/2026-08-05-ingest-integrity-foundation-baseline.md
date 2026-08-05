# P0 적재 무결성 구현 baseline

- source_head: `06fa7b7bbe846d6baf75ddb31e6cc6573a3150e6`
- worktree_head: `06fa7b7bbe846d6baf75ddb31e6cc6573a3150e6`
- source_tracked_dirty_paths: 없음
- source_untracked_preserved_paths:
  - `decks/project-brain-new/project-brain-new-overview.pptx`
  - `decks/project-brain-new/project-brain-presentation-script.md`
  - `docs/plans/2026-07-27-ingest-fix-execution-plan.md`
  - `docs/reports/2026-07-27-plan-delta-bg.md`
  - `docs/reports/2026-07-27-two-ingest-session-review.md`
  - `docs/reports/2026-07-28-agents-doctor-global-skill-mirror-final-review.md`
  - `docs/reports/2026-07-28-agents-doctor-global-skill-mirror-ledger.md`
  - `docs/reports/2026-07-28-brain-ingest-redesign-review.html`
  - `docs/superpowers/plans/2026-07-27-handoff-consumer.md`
  - `docs/superpowers/plans/2026-07-28-agents-doctor-global-skill-mirror.md`
  - `docs/superpowers/plans/2026-07-28-brain-ingest-recovery.md`
  - `docs/superpowers/plans/2026-08-04-task18-display-labels-and-quote-backlog.md`
  - `docs/superpowers/specs/2026-08-04-task18-display-labels-and-quote-backlog-design.md`
- baseline_pytest: PASS — `1542 passed, 105 subtests passed in 145.62s (0:02:25)`
- baseline_runtime_unittest: PASS — `Ran 99 tests in 10.115s`, `OK`
- production_now_call_sites: 13건
  - `src/project_brain/audit.py`, `code_verify.py`, `mutation.py`, `session.py`, `snapshot.py`, `stale_check.py`, `objbase.py` 각 1건
  - `src/project_brain/cli.py` 5건
- ingest_call_sites: 50건
  - `src/project_brain/cli.py` 4건, `ingest.py` 1건, `templates/ingest/references/ingest-tools.md` 3건
  - `tests/test_cli.py` 9건, `test_ingest.py` 26건, `test_universal_ingest_e2e.py` 1건, `test_update_rules_engine.py` 6건
- mutation_request_call_sites: 21건
  - `src/project_brain/canonical_repair.py`, `context_replace.py`, `ingest.py` 각 1건, `migration.py` 2건
  - `src/project_brain/templates/ingest/scripts/test_batch_tools.py`, `test_finalize_ingest.py` 각 1건
  - `tests/test_corpus_io.py` 10건, `test_mutation.py`, `test_object_contract_templates.py` 각 1건, `test_stale_check.py` 2건

## 수행 내용과 실제 명령

`main` checkout에서 설계 커밋 `77f0898c132556e254fbdf2cd033dd2a03c2fe2c`가 HEAD의 조상이고, `.worktrees`가 무시되며 대상 branch/path가 없음을 확인했다. 이후 `06fa7b7bbe846d6baf75ddb31e6cc6573a3150e6`에서 `feat/ingest-integrity-foundation` branch와 격리 worktree를 만들었다.

```bash
uv sync --extra mecab
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" -m pytest -q
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest discover -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
rg -n 'now_kst\(' "$ENGINE/src/project_brain"
rg -n '\bingest\(' "$ENGINE/src/project_brain" "$ENGINE/tests"
rg -n 'MutationRequest\(' "$ENGINE/src/project_brain" "$ENGINE/tests"
```

위 명령의 검사 결과는 모두 PASS다. runtime unittest 출력에는 `domain_spec.HOOK` 사용 경고가 한 번 있었지만, suite는 `OK`로 종료했다.

## 바뀐 파일

- `docs/reports/2026-08-05-ingest-integrity-foundation-baseline.md` 추가

## 자기 검토

- 원본 `main`의 기존 미추적 파일은 이동·수정·삭제·stage하지 않았다.
- production code나 테스트 코드는 바꾸지 않았다.
- stage와 commit 대상은 이 baseline 문서 하나로 제한한다.

## 우려 사항

- baseline 자체는 녹색이지만, runtime unittest에서 `domain_spec.HOOK` 사용 경고가 출력됐다. 이번 Task 0에서는 기존 동작을 바꾸지 않고 기록만 한다.
