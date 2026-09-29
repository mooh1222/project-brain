#!/usr/bin/env bash
# 여러 항목 적재가 모두 끝난 뒤 한 번만 실행하는 semantic gate wrapper.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 엔진(project_brain)이 깔린 Python을 한 번 고른다 — release 설치본은 uv tool 환경에만 있다.
PY="$(python3 "$HERE/engine_python.py")"
exec "$PY" "$HERE/finalize_ingest.py" "$@"
