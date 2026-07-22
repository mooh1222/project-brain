#!/usr/bin/env bash
# 여러 항목 적재가 모두 끝난 뒤 한 번만 실행하는 공통 검증 단계.
set -euo pipefail

step() { echo "── [$1] ──"; }

step "index rebuild"
project-brain index rebuild
step "lint"
project-brain lint
step "eval"
project-brain eval 2>/dev/null | jq '.summary'
step "search 샘플"
project-brain search "이 컨텍스트 핵심 동작" 2>/dev/null | jq '.results | length'
step "graph isolated"
project-brain graph isolated
step "unittest"
python3 -m unittest discover -s {{BRAIN_ROOT}}/checks -p 'test_*.py'
echo "── 적재 완료 ──"
