#!/usr/bin/env bash
# 적재 후 단계 러너: assemble_notes → build → ingest → index → lint → eval → unittest → search → graph isolated.
# 단계 실패 시 즉시 중단·어느 단계인지 표시. 같은 NOW(domain_spec)라 재실행 멱등.
# --dry: assemble + build(저장 안 함)까지만(비파괴 검증).
set -euo pipefail
DRY=0
if [ "${1:-}" = "--dry" ]; then DRY=1; shift; fi
VERIFY="${1:?usage: run_ingest.sh [--dry] <verify.json> <domain_spec.py>}"
SPEC="${2:?usage: run_ingest.sh [--dry] <verify.json> <domain_spec.py>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOTES="$(mktemp -t notes.XXXXXX.json)"
OBJS="$(mktemp -t objects.XXXXXX.json)"

step() { echo "── [$1] ──"; }

step "assemble_notes"
python3 "$HERE/assemble_notes.py" "$VERIFY" "$SPEC" -o "$NOTES"

step "build"
project-brain build --notes "$NOTES" --objects-file "$OBJS"

if [ "$DRY" = "1" ]; then
  echo "── [dry] build까지 OK (objects=$OBJS, ingest/index 생략) ──"; exit 0
fi

step "ingest";        project-brain ingest --objects-file "$OBJS"
# index rebuild는 실모델 임베더(bge-m3)라 객체 많으면 분 단위 정상. 빠른 검증은 --dry로 이 단계 전에 멈춘다.
step "index rebuild"; project-brain index rebuild
step "lint";          project-brain lint
step "eval";          project-brain eval 2>/dev/null | jq '.summary'
step "unittest";      python3 -m unittest discover -s {{BRAIN_ROOT}}/checks
step "search 샘플";   project-brain search "이 컨텍스트 핵심 동작" 2>/dev/null | jq '.results | length'
step "graph isolated"; project-brain graph isolated
echo "── 적재 완료 ──"
