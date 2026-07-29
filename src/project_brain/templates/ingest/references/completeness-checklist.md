# 완료 점검표

완료라고 요약하기 전에 적재 전 의미 완전성과 실행 후 일곱 게이트를 순서대로 통과시킨다. 상태축과 코드 흐름 근거의
세부 규칙은 `scope.md`와 `system-domain-playbook.md`를 따른다.

사전 조건으로 `history_coverage`는 `unsearched`, `partial`, `complete` 가운데 정확히 하나다.

## 적재 전 의미 완전성

- 대상 클래스는 1-pass로 모두 훑고, 독립 public 메서드는 2-pass로 확인하며, enum 값을 독립 의미 원자로 승격할지 판정한다.
- 재현 가능한 산출물로 심볼 인벤토리, 원자별 누락 판정, 확인한 이력 종류를 남긴다.
- 기획서 기능 목차와 코드 뼈대를 대조해 서버 규칙과 순수 규칙이 통째로 빠지지 않았는지 확인한다.
- `history_coverage=complete`인데 ledger가 없거나 결정 종류가 한쪽으로 편중되면 갭 신호다. 값 변경은 ledger와 supersede 체인을 함께 확인한다.
- reviewed 근거를 확인하고 코드 앵커 없는 규칙은 없는 척하지 말고 그 이유를 boundary/caveats에 남긴다.
- `reviewed`는 근거와 해석을 검증했다는 뜻이다. `unmerged`는 기본 브랜치 범위를 알리는 advisory일 뿐이므로,
  검증된 prototype을 합쳐지지 않았다는 이유만으로 candidate로 내리지 않는다. candidate는 근거나 의미가
  불확실할 때 쓴다.
- Jira/Slack 등의 변경 흔적은 있는데 DecisionRecord가 없는 의미상 고아가 없는지 확인한다.
- 메모리나 이전 서사의 claim-bearing field는 원문·코드로 독립 재구성하고 실제 반박을 시도한다. 근거 개수가 아니라 내용이 주장을 뒷받침하는지 본다.
- lint는 형식과 끊긴 참조를 잡지만 통째로 빠진 규칙은 찾지 못하므로 수동 의미 검사가 필요하다.

## 실행 후 일곱 게이트

1. 동적 workflow 결과가 있으면 `scripts/validate_workflow_result.py <결과.json>`이 통과했다. 직접 단건 실행이면 `해당 없음`으로 기록한다.
2. batch 모드면 `batch-report.json`에서 `expected == len(item_records)`, 모든 record의
   `status=committed`, `failed=[]`, `finalized=true`, `finalization.ok=true`다. authoritative
   `item_records` 각각에 item/input binding과 exact transaction이 한 객체로 묶였고, root-anchored
   intent/journal의 `durable receipt`와 일치한다. canonical `manifest_sha256`, operation, engine SHA,
   action object IDs, before/after/current corpus fingerprint, ingest ID/count가 확인됐다. receipt가
   없거나 불일치하거나 noncommitted면 `finalized=false`여야 한다. 최초 `isolation_baseline`이
   보존됐고 absolute repo identity, resolved `target_revision_sha`, 실제 engine root/HEAD, root
   inode, batch manifest hash, immutable staged 입력 hash, finalization 계약이 resume 입력과
   일치한다. `transactions`·`succeeded`·`failed`는 item_records에서 파생된 호환 필드다.
   post head == baseline head이고, post unmerged는 baseline union expected와 일치한다. legacy
   baseline은 그 제한을 그대로 적용하며, 사용할 수 없는 감사 상태를 만들어 내지 않는다.
   직접 단건은 config 선행검사와 적재 전 baseline을 확인한다.
3. lint 결과가 0건이다.
4. `project-brain eval`이 모두 통과했다.
5. finalization의 `unexpected_new_ids=[]`다. 이번 적재로 새로 생긴 고립 객체 중
   `intentional_terminal_ids`에 객체 ID·분류·근거를 기록한 의도적 종착점만 허용하며, 0개를 만들려고 의미 없는 연결은 추가하지 않는다.
6. `python3 -m unittest discover -s {{BRAIN_ROOT}}/checks -p "test_*.py"`가 통과했다.
7. 모든 recall check의 `missing_object_ids=[]`, `missing_code_locator_object_ids=[]`다. 즉 manifest에
   선언한 도메인 질문이 기대 객체를 회수하고, 요구한 mapping에는 연결된 code locator가 함께 나온다.

하나라도 실패하면 완료로 처리하지 말고 실패 항목, 근거, 같은 입력으로 재개할 절차를 보고한다.
