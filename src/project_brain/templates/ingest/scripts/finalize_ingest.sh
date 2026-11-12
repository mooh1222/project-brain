#!/usr/bin/env bash
# 여러 항목 적재가 모두 끝난 뒤 한 번만 실행하는 semantic gate wrapper.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 명시 환경이 없으면 프로젝트 고정 release만 사용한다. 전역 엔진으로 폴백하지 않는다.
PY="$(python3 "$HERE/engine_python.py")"
if [ -z "${PROJECT_BRAIN_PYTHON:-}" ]; then
  export PATH="$(dirname "$PY"):$PATH"
  unset PYTHONPATH PYTHONHOME
fi
exec "$PY" "$HERE/finalize_ingest.py" "$@"
