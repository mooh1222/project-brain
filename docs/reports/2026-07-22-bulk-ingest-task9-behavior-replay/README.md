# Task 9 행동 재생 자료

이 디렉터리는 행동 실행 뒤에 보존한 입력·드라이버·전사 기록이다. 중립 fixture에는 결과 이름이나 hash를 넣지 않고, 재생에 필요한 실행 입력만 여기 둔다.

아래 명령은 **이 worktree의 루트**에서 시작한다. `REPO_ROOT`, `REPLAY_ROOT`, `TASK9_ROOT`, `TARGET`는 모두 절대 경로다. 결과물은 `$TASK9_ROOT` 아래에만 생기며 커밋하지 않는다.

```bash
set -euo pipefail
REPO_ROOT=$(pwd -P)
test -x "$REPO_ROOT/.venv/bin/project-brain"
REPLAY_ROOT="$REPO_ROOT/docs/reports/2026-07-22-bulk-ingest-task9-behavior-replay"
TASK9_ROOT="$REPO_ROOT/.task9-run"
test ! -e "$TASK9_ROOT"
mkdir "$TASK9_ROOT"
```

single, code_flow, logical_key는 fixture만으로 합성 Git 저장소를 만들고, 각 시나리오의 target subshell 안에서 고정 이름·이메일·시각으로 `fixture baseline`을 커밋한다. 정확한 설정은 각 시나리오 블록에 있다.

## single

```bash
TARGET="$TASK9_ROOT/single"
mkdir -p "$TARGET"
cp -R "$REPO_ROOT/tests/fixtures/ingest_skill_behavior/single/." "$TARGET/"
(
  cd "$TARGET"
  git init -b main
  git config user.name task9-fixture
  git config user.email fixture@example.invalid
  git config commit.gpgsign false
  git add -A
  GIT_AUTHOR_NAME=task9-fixture GIT_AUTHOR_EMAIL=fixture@example.invalid   GIT_AUTHOR_DATE=2026-07-22T00:00:00+09:00 GIT_COMMITTER_NAME=task9-fixture   GIT_COMMITTER_EMAIL=fixture@example.invalid GIT_COMMITTER_DATE=2026-07-22T00:00:00+09:00     git commit -m 'fixture baseline'
  test "$(git rev-parse HEAD)" = 8362e8d9d09600cd8468e28e5a49c02dd78bd892
)
"$REPO_ROOT/.venv/bin/project-brain" install --target "$TARGET" --project behavior --brain-root brain --default-branch main --repo fixture/single
cp "$REPLAY_ROOT/single/verify.json" "$TARGET/verify.json"
cp "$REPLAY_ROOT/single/domain_spec.py" "$TARGET/domain_spec.py"
(
  cd "$TARGET"
  PATH="$REPO_ROOT/.venv/bin:$PATH"     ./.agents/skills/behavior-brain-ingest/scripts/run_ingest.sh     --defer-finalize verify.json domain_spec.py
)
```

## code_flow

```bash
TARGET="$TASK9_ROOT/code_flow"
mkdir -p "$TARGET"
cp -R "$REPO_ROOT/tests/fixtures/ingest_skill_behavior/code_flow/." "$TARGET/"
(
  cd "$TARGET"
  git init -b main
  git config user.name task9-fixture
  git config user.email fixture@example.invalid
  git config commit.gpgsign false
  git add -A
  GIT_AUTHOR_NAME=task9-fixture GIT_AUTHOR_EMAIL=fixture@example.invalid   GIT_AUTHOR_DATE=2026-07-22T00:00:00+09:00 GIT_COMMITTER_NAME=task9-fixture   GIT_COMMITTER_EMAIL=fixture@example.invalid GIT_COMMITTER_DATE=2026-07-22T00:00:00+09:00     git commit -m 'fixture baseline'
  test "$(git rev-parse HEAD)" = 5c880d519c6bc3ae1a0cbcdc4e1d831241ba084f
)
"$REPO_ROOT/.venv/bin/project-brain" install --target "$TARGET" --project behavior --brain-root brain --default-branch main --repo fixture/code-flow
cp "$REPLAY_ROOT/code_flow/verify.json" "$TARGET/verify.json"
cp "$REPLAY_ROOT/code_flow/domain_spec.py" "$TARGET/domain_spec.py"
(
  cd "$TARGET"
  "$REPO_ROOT/.venv/bin/python" "$REPLAY_ROOT/code_flow/clangd_call_hierarchy.py"
  PATH="$REPO_ROOT/.venv/bin:$PATH"     ./.agents/skills/behavior-brain-ingest/scripts/run_ingest.sh     --defer-finalize verify.json domain_spec.py
)
```

## logical_key

```bash
TARGET="$TASK9_ROOT/logical_key"
mkdir -p "$TARGET"
cp -R "$REPO_ROOT/tests/fixtures/ingest_skill_behavior/logical_key/." "$TARGET/"
(
  cd "$TARGET"
  git init -b main
  git config user.name task9-fixture
  git config user.email fixture@example.invalid
  git config commit.gpgsign false
  git add -A
  GIT_AUTHOR_NAME=task9-fixture GIT_AUTHOR_EMAIL=fixture@example.invalid   GIT_AUTHOR_DATE=2026-07-22T00:00:00+09:00 GIT_COMMITTER_NAME=task9-fixture   GIT_COMMITTER_EMAIL=fixture@example.invalid GIT_COMMITTER_DATE=2026-07-22T00:00:00+09:00     git commit -m 'fixture baseline'
  test "$(git rev-parse HEAD)" = 32b33afe30787125a66078dd7c4e2911622558a0
)
"$REPO_ROOT/.venv/bin/project-brain" install --target "$TARGET" --project behavior --brain-root brain --default-branch main --repo fixture/logical-key
cp "$REPLAY_ROOT/logical_key/verify.json" "$TARGET/verify.json"
cp "$REPLAY_ROOT/logical_key/domain_spec.py" "$TARGET/domain_spec.py"
(
  cd "$TARGET"
  set +e
  PATH="$REPO_ROOT/.venv/bin:$PATH"     ./.agents/skills/behavior-brain-ingest/scripts/run_ingest.sh     --dry verify.json domain_spec.py
  status=$?
  set -e
  test "$status" -eq 1
)
```

## batch_partial_failure

```bash
TARGET="$TASK9_ROOT/batch_partial_failure"
mkdir -p "$TARGET"
cp -R "$REPO_ROOT/tests/fixtures/ingest_skill_behavior/batch_partial_failure/." "$TARGET/"
"$REPO_ROOT/.venv/bin/project-brain" install --target "$TARGET" --project behavior --brain-root brain --default-branch main --repo fixture/batch-partial-failure
(
  cd "$TARGET"
  set +e
  "$REPO_ROOT/.venv/bin/python"     ./.agents/skills/behavior-brain-ingest/scripts/validate_workflow_result.py     workflow-result.json
  status=$?
  set -e
  test "$status" -eq 1
)
```

## raw_names

```bash
TARGET="$TASK9_ROOT/raw_names"
mkdir -p "$TARGET"
cp -R "$REPO_ROOT/tests/fixtures/ingest_skill_behavior/raw_names/." "$TARGET/"
"$REPO_ROOT/.venv/bin/project-brain" install --target "$TARGET" --project behavior --brain-root brain --default-branch main --repo fixture/raw-names
(
  cd "$TARGET"
  "$REPO_ROOT/.venv/bin/python" "$REPLAY_ROOT/raw_names/replay_raw_names.py"
  find brain/raw/sources -type f -name '*.md' -exec openssl dgst -sha256 {} \;
  cmp -s sources/collision-a/'Collision Notes.md' brain/raw/sources/legacy-archive/collision-notes.md
)
```

`raw_names` 드라이버는 두 번째 실행을 거부한다. source bundle root나 그 아래에 심볼릭 링크가 있거나, collision suffix 12~64 글자가 모두 사용 중인 경우도 오류로 끝나며 기존 raw 파일은 바꾸지 않는다.

결과 SHA-256과 byte 비교 결과는 상위 [행동 증거](../2026-07-22-bulk-ingest-task9-behavior-evidence.md)에 기록한다.
