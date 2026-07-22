# Single replay

- Fixture source: `tests/fixtures/ingest_skill_behavior/single/`
- Target cwd: `$TARGET` (`$REPO_ROOT/.task9-run/single/`)
- Synthetic baseline commit: `8362e8d9d09600cd8468e28e5a49c02dd78bd892`; `domain_spec.py`의 `COMMIT`도 이 값이다.
- [README](../README.md)의 single 블록처럼 target에서 fixture를 커밋하고 설치한 뒤 `verify.json`, `domain_spec.py`를 복사한다.

target cwd에서 실행한 명령은 다음과 같다.

```bash
PATH="$REPO_ROOT/.venv/bin:$PATH"   ./.agents/skills/behavior-brain-ingest/scripts/run_ingest.sh   --defer-finalize verify.json domain_spec.py
```

`command -v project-brain`은 `$REPO_ROOT/.venv/bin/project-brain`을 가리켰고 종료 코드는 0이었다. 핵심 출력은 `mappings=1 anchors=1 terms=0`, build `built=5`, ingest `ingested=5`, `defer-finalize`였다. 결과는 target cwd에서 `find brain -type f -name '*.json' -exec openssl dgst -sha256 {} \;`로 다시 계산해 상위 증거 표와 비교한다.
