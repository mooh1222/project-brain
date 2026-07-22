# 완료 점검표

완료라고 요약하기 전에 아래 일곱 게이트를 순서대로 통과시킨다. 상태축과 코드 흐름 근거의
세부 규칙은 `scope.md`와 `system-domain-playbook.md`를 따른다.

사전 조건으로 `history_coverage`는 `unsearched`, `partial`, `complete` 가운데 정확히 하나다.

1. 동적 workflow 결과가 있으면 `scripts/validate_workflow_result.py <결과.json>`이 통과했다. 직접 단건 실행이면 `해당 없음`으로 기록한다.
2. batch 모드면 `batch-report.json`에서 `expected == len(succeeded)`, `failed=[]`, `finalized=true`다. 직접 단건 실행이면 `해당 없음`으로 기록한다.
3. lint 결과가 0건이다.
4. `project-brain eval`이 모두 통과했다.
5. `project-brain graph isolated`에 이번 적재로 새로 생긴 분류되지 않은 고립 객체가 0개다. `ingest-tools.md`에 따라 객체 ID·분류·근거를 기록한 의도적 종착점만 허용하며, 0개를 만들려고 의미 없는 연결은 추가하지 않는다.
6. `python3 -m unittest discover -s {{BRAIN_ROOT}}/checks -p "test_*.py"`가 통과했다.
7. `project-brain search "<도메인 질문>"` 결과에 mapping과 연결된 code locator가 함께 나온다.

하나라도 실패하면 완료로 처리하지 말고 실패 항목, 근거, 같은 입력으로 재개할 절차를 보고한다.
