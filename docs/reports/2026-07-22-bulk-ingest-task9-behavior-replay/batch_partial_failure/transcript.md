# Batch partial-failure replay

- Fixture source: `tests/fixtures/ingest_skill_behavior/batch_partial_failure/`
- Target cwd: `$TARGET` (`$REPO_ROOT/.task9-run/batch_partial_failure/`)
- Installed validator: `./.agents/skills/behavior-brain-ingest/scripts/validate_workflow_result.py`

target cwd에서 다음을 실행한다.

```bash
"$REPO_ROOT/.venv/bin/python"   ./.agents/skills/behavior-brain-ingest/scripts/validate_workflow_result.py   workflow-result.json
```

종료 코드는 1이고 stdout은 `{"ok": false, "errors": ["items[1].verify_status가 ok가 아닙니다"]}`다. 이 단계에서는 batch report·ingest·finalization을 만들지 않는다. 같은 workflow 입력과 run ID에서 실패 항목을 고친 뒤 validator를 다시 통과시키고, 그 다음에 batch manifest runner를 시작한다.
