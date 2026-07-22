# Raw-name replay

- Fixture source: `tests/fixtures/ingest_skill_behavior/raw_names/`
- Target cwd: `$TARGET` (`$REPO_ROOT/.task9-run/raw_names/`)
- Policy source: installed `.agents/skills/behavior-brain-ingest/references/ingest-tools.md`

target cwd에서 아래를 실행한다.

```bash
"$REPO_ROOT/.venv/bin/python" "$REPLAY_ROOT/raw_names/replay_raw_names.py"
```

실제 종료 코드는 0이었다. driver는 source bundle root를 `sources/`로 두고, 그 아래 상대경로만 받으며 `.` 제거, NFC, `/`, 대소문자 보존 규칙으로 collision SHA-256 입력을 만든다. ASCII-only stem이 비면 `document`를 쓴다. source bundle root나 그 아래의 심볼릭 링크는 쓰기 전에 거부한다. raw target이 비어 있지 않으면 두 번째 실행도 거부하며, suffix 12~64 글자가 모두 충돌하면 오류로 끝낸다.

실행 뒤 target cwd에서 다음으로 결과와 원본 byte를 확인한다.

```bash
find brain/raw/sources -type f -name '*.md' -exec openssl dgst -sha256 {} \;
cmp -s sources/collision-a/'Collision Notes.md' brain/raw/sources/legacy-archive/collision-notes.md
```

두 번째 collision, non-ASCII fallback, 두 revision과 20개 old 문서의 전체 source→result·SHA-256·cmp 결과는 상위 행동 증거 표에 있다.
