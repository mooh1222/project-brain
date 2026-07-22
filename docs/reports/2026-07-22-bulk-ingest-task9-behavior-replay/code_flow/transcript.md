# Code-flow replay

- Fixture source: `tests/fixtures/ingest_skill_behavior/code_flow/`
- Target cwd: `$TARGET` (`$REPO_ROOT/.task9-run/code_flow/`)
- Installed runner: `./.agents/skills/behavior-brain-ingest/scripts/run_ingest.sh`
- Synthetic baseline commit: `5c880d519c6bc3ae1a0cbcdc4e1d831241ba084f`; `domain_spec.py`의 `COMMIT`도 이 값이다.

target cwd에서 아래를 실행한다. 종료 코드는 0이었다.

```bash
"$REPO_ROOT/.venv/bin/python" "$REPLAY_ROOT/code_flow/clangd_call_hierarchy.py"
```

driver는 `prepareCallHierarchy`를 `runtime::transform`, line 2/character 5에 보내고 두 번의 `incomingCalls`를 보낸다. 변환하지 않은 실제 stdout은 다음과 같다.

```json
{"prepare": {"name": "transform", "symbol": "runtime::transform", "position": [2, 5]}, "incoming_transform": [{"name": "dispatch", "uri": "runtime.cpp", "range": {"end": {"character": 20, "line": 7}, "start": {"character": 11, "line": 7}}}], "incoming_dispatch": [{"name": "run", "uri": "runtime.cpp", "range": {"end": {"character": 19, "line": 11}, "start": {"character": 11, "line": 11}}}]}
```

그 뒤 같은 target cwd에서 다음을 실행한다.

```bash
PATH="$REPO_ROOT/.venv/bin:$PATH"   ./.agents/skills/behavior-brain-ingest/scripts/run_ingest.sh   --defer-finalize verify.json domain_spec.py
```

종료 코드는 0이고 핵심 출력은 `mappings=1 anchors=2 terms=0`, build `built=7`, ingest `ingested=7`이다. 결과 SHA-256은 target cwd에서 single과 같은 `find`/`openssl` 명령으로 상위 증거 표와 비교한다.
