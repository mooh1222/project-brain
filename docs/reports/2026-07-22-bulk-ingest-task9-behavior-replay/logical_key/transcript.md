# Logical-key replay

- Fixture source: `tests/fixtures/ingest_skill_behavior/logical_key/`
- Target cwd: `$TARGET` (`$REPO_ROOT/.task9-run/logical_key/`)
- Installed runner: `./.agents/skills/behavior-brain-ingest/scripts/run_ingest.sh`
- Synthetic baseline commit: `32b33afe30787125a66078dd7c4e2911622558a0`; `domain_spec.py`의 `COMMIT`도 이 값이다.

target cwd에서 아래를 실행한다.

```bash
PATH="$REPO_ROOT/.venv/bin:$PATH"   ./.agents/skills/behavior-brain-ingest/scripts/run_ingest.sh   --dry verify.json domain_spec.py
```

`command -v project-brain`은 `$REPO_ROOT/.venv/bin/project-brain`을 가리켰다. 종료 코드는 1이며 build 전 JSON 오류는 조립된 code anchor `--0`, mapping의 full ID, code evidence reference `--0` key가 논리 key 형식이 아니라는 세 항목이다. `--dry` 결과 brain 파일은 없다.
