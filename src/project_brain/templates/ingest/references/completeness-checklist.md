# 완료 점검표

적재 직전과 직후에 아래 게이트를 순서대로 확인한다.
상태축의 뜻과 허용값은 `scope.md`가 정한다.

## 적재 전

- 대상과 이번 source packet을 선언했고, 메모리나 handoff를 원문 근거로 쓰지 않았다.
- 현재 사실과 이력 범위의 상태를 `scope.md`에 따라 기록했다.
- `history_coverage`는 `scope.md`의 허용값 가운데 정확히 하나다.
- 의미 원자는 독립 질문·근거·변경 이력 기준을 만족하며, 근거가 없는 값은 채우지 않았다.
- 논리 key와 완성 ID를 구분했고 코드 앵커의 기준 commit SHA를 확인했다.
- 필요한 객체 연결과 EvidenceRef가 build에서 해소된다.
- SKILL.md에 열거된 고위험 경우의 적대 검증 결과와 수정 사항을 다시 확인했다.
- 코드 기반 검증이라면 프로젝트 코드 검증 계약을 적용한 기록이 있다.

## workflow와 대량 적재

- workflow 결과가 `validate_workflow_result.py`를 통과했다.
- batch report의 `expected == len(succeeded)`다.
- batch report의 `failed`는 비어 있고 `finalized`는 참이다.
- 중단된 묶음은 같은 입력과 보고서로 재개했으며, 성공 항목을 다시 실행하지 않았다.

## 적재 후

- lint 문제는 0개다.
- 평가가 모두 통과했다.
- 새 고립 객체는 0개이거나 의도와 연결 근거가 기록돼 있다.
- 실제 코퍼스 unittest가 통과했다.
- 샘플 회상에서 mapping과 연결된 code locator가 함께 나온다.

하나라도 실패하면 완료로 요약하지 말고 실패 항목, 근거, 재개 입력을 보고한다.
