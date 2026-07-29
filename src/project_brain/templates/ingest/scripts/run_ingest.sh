#!/usr/bin/env bash
# 한 항목 적재 러너: assemble_notes → build → ingest. 전체 검증은 finalize_ingest.sh가 맡는다.
set -euo pipefail
DRY=0
DEFER_FINALIZE=0
REPO_ROOT=""
EXPECTED_REPO_ID=""
EXPECTED_REVISION_REF=""
ENGINE_SHA=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry) DRY=1; shift ;;
    --defer-finalize) DEFER_FINALIZE=1; shift ;;
    --repo-root) REPO_ROOT="${2:?--repo-root requires a value}"; shift 2 ;;
    --expected-repo-id) EXPECTED_REPO_ID="${2:?--expected-repo-id requires a value}"; shift 2 ;;
    --expected-revision-ref) EXPECTED_REVISION_REF="${2:?--expected-revision-ref requires a value}"; shift 2 ;;
    --engine-sha) ENGINE_SHA="${2:?--engine-sha requires a value}"; shift 2 ;;
    --) shift; break ;;
    -*) echo "usage: run_ingest.sh [--dry] [--defer-finalize] [mutation context] <verify.json> <domain_spec.py>" >&2; exit 2 ;;
    *) break ;;
  esac
done
VERIFY="${1:?usage: run_ingest.sh [--dry] [--defer-finalize] [mutation context] <verify.json> <domain_spec.py>}"
SPEC="${2:?usage: run_ingest.sh [--dry] [--defer-finalize] [mutation context] <verify.json> <domain_spec.py>}"
if [ "$#" -ne 2 ]; then
  echo "usage: run_ingest.sh [--dry] [--defer-finalize] [mutation context] <verify.json> <domain_spec.py>" >&2
  exit 2
fi
if [ "$DRY" = "0" ] && { [ -z "$REPO_ROOT" ] || [ -z "$EXPECTED_REPO_ID" ] || [ -z "$EXPECTED_REVISION_REF" ] || [ -z "$ENGINE_SHA" ]; }; then
  echo "write mode requires --repo-root, --expected-repo-id, --expected-revision-ref, --engine-sha" >&2
  exit 2
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTES="$(mktemp -t notes.XXXXXX.json)"
OBJS="$(mktemp -t objects.XXXXXX.json)"
BUILD_REPORT="$(mktemp -t build-report.XXXXXX.json)"
FINALIZATION_CONFIG="$(mktemp -t finalization.XXXXXX.json)"
ISOLATION_BASELINE="$(mktemp -t isolation-baseline.XXXXXX.json)"
TRANSACTION_RESULT="$(mktemp -t transaction-result.XXXXXX.json)"
trap 'rm -f "$NOTES" "$OBJS" "$BUILD_REPORT" "$FINALIZATION_CONFIG" "$ISOLATION_BASELINE" "$TRANSACTION_RESULT"' EXIT

step() { echo "── [$1] ──" >&2; }

step "assemble_notes"
ASSEMBLE=(python3 "$HERE/assemble_notes.py" "$VERIFY" "$SPEC" -o "$NOTES")
if [ "$DRY" = "0" ] && [ "$DEFER_FINALIZE" = "0" ]; then
  ASSEMBLE+=(--finalization-out "$FINALIZATION_CONFIG")
fi
"${ASSEMBLE[@]}" >&2
if [ "$DRY" = "0" ] && [ "$DEFER_FINALIZE" = "0" ]; then
  python3 "$HERE/finalize_ingest.py" --validate-config "$FINALIZATION_CONFIG" >/dev/null
fi

step "build"
project-brain build --notes "$NOTES" --objects-file "$OBJS" | tee "$BUILD_REPORT" >&2

if [ "$DRY" = "1" ]; then
  echo "── [dry] build까지 OK (ingest/finalize 생략) ──"
  exit 0
fi

if [ "$DEFER_FINALIZE" = "0" ]; then
  step "isolation baseline"
  "$HERE/finalize_ingest.sh" --capture-baseline > "$ISOLATION_BASELINE"
fi

step "ingest"
project-brain ingest \
  --objects-file "$OBJS" \
  --preconditions-file "$BUILD_REPORT" \
  --repo-root "$REPO_ROOT" \
  --expected-repo-id "$EXPECTED_REPO_ID" \
  --expected-revision-ref "$EXPECTED_REVISION_REF" \
  --engine-sha "$ENGINE_SHA" \
  > "$TRANSACTION_RESULT"
python3 "$HERE/finalize_ingest.py" --validate-transaction "$TRANSACTION_RESULT" >/dev/null

if [ "$DEFER_FINALIZE" = "1" ]; then
  step "defer-finalize ingest까지 OK"
  command cat "$TRANSACTION_RESULT"
  exit 0
fi

"$HERE/finalize_ingest.sh" \
  --config "$FINALIZATION_CONFIG" \
  --baseline "$ISOLATION_BASELINE" \
  --transaction-result "$TRANSACTION_RESULT"
