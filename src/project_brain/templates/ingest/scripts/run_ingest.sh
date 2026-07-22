#!/usr/bin/env bash
# 한 항목 적재 러너: assemble_notes → build → ingest. 전체 검증은 finalize_ingest.sh가 맡는다.
set -euo pipefail
DRY=0
DEFER_FINALIZE=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry) DRY=1; shift ;;
    --defer-finalize) DEFER_FINALIZE=1; shift ;;
    --) shift; break ;;
    -*) echo "usage: run_ingest.sh [--dry] [--defer-finalize] <verify.json> <domain_spec.py>" >&2; exit 2 ;;
    *) break ;;
  esac
done
VERIFY="${1:?usage: run_ingest.sh [--dry] [--defer-finalize] <verify.json> <domain_spec.py>}"
SPEC="${2:?usage: run_ingest.sh [--dry] [--defer-finalize] <verify.json> <domain_spec.py>}"
if [ "$#" -ne 2 ]; then
  echo "usage: run_ingest.sh [--dry] [--defer-finalize] <verify.json> <domain_spec.py>" >&2
  exit 2
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTES="$(mktemp -t notes.XXXXXX.json)"
OBJS="$(mktemp -t objects.XXXXXX.json)"
BUILD_REPORT="$(mktemp -t build-report.XXXXXX.json)"
trap 'rm -f "$NOTES" "$OBJS" "$BUILD_REPORT"' EXIT

step() { echo "── [$1] ──"; }

step "assemble_notes"
python3 "$HERE/assemble_notes.py" "$VERIFY" "$SPEC" -o "$NOTES"

step "build"
project-brain build --notes "$NOTES" --objects-file "$OBJS" | tee "$BUILD_REPORT"

if [ "$DRY" = "1" ]; then
  echo "── [dry] build까지 OK (ingest/finalize 생략) ──"
  exit 0
fi

step "ingest"
project-brain ingest --objects-file "$OBJS" --preconditions-file "$BUILD_REPORT"

if [ "$DEFER_FINALIZE" = "1" ]; then
  echo "── [defer-finalize] ingest까지 OK ──"
  exit 0
fi

"$HERE/finalize_ingest.sh"
