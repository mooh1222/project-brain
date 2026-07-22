#!/usr/bin/env bash
# 여러 항목 적재가 모두 끝난 뒤 한 번만 실행하는 semantic gate wrapper.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/finalize_ingest.py" "$@"
