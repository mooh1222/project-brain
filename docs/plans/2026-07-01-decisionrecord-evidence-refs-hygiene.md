# DecisionRecord evidence_refs 비대칭 — 위생 티켓 (후순위)

- 날짜: 2026-07-01
- 상태: **기록만 / 미착수** (안전 작업 아님 — 럭키박스 해법과 섞지 말 것)
- 배경: 안전장치 설계 B 검토 중 발견. B는 폐기됨(근거:
  `docs/plans/2026-06-30-ingest-skill-retro-improvements.md`의 "P0 후속" 절).
- 인용한 file:line은 작성 시점(2026-07-01) 스냅샷이라 이후 편집으로 드리프트할 수 있다.

## 갭

reviewed 객체가 근거(evidence_refs) 없이 적재되는 걸 막는 규칙이 GlossaryTerm·DomainMapping엔 있는데
DecisionRecord엔 없다.

- `schema.py`: GlossaryTerm(186-187)·DomainMapping(217-218)은 `status==reviewed and not evidence_refs`면
  거부. DecisionRecord 블록(199-205)엔 enum 검사뿐, 그 규칙이 없다.
- DecisionRecord는 `truth_role="event"`(발생 사건)라 출처가 덜 필요할 이유가 없다 → 오버사이트일 개연성이 높다.
- 실측: bb2 reviewed 결정 38개 중 4개가 evidence_refs 빈 채 적재돼 있다(작성 시점).

## 럭키박스 해법이 아니다 (혼동 금지)

evidence_refs를 채워도 럭키박스는 통과했다(틀린 커밋이 달려 있었다). 이 규칙은 "근거 빈 reviewed"를 막을
뿐 "근거 있는데 모순"은 못 잡는다. 안전 서사와 절대 묶지 말 것.

## "2줄 미러"가 아닌 이유 (착수 전 스코프)

1. **candidate 폴백 부재:** `assembly.py:144` build_decisions가 status=reviewed를 무조건 박고 candidate
   분기가 없다. schema 규칙만 넣으면 근거 약한 결정이 하드 ingest 거부가 된다 → "근거 약한 결정은 거부냐
   candidate 강등이냐"를 같이 정해야 한다.
2. **기존 store는 validate가 안 본다:** `ingest.py:22-25` validate_object는 적재 시점만 검사. 기존 4개를
   잡으려면 `lint.py`(GlossaryTerm 가드가 있는 147행대)에 스윕을 별도로 넣어야 한다.
3. **4개 먼저 눈으로:** bb2 4개 타입을 먼저 확인한다. 십중팔구 spec_clarification/implementation_boundary
   (checklist가 이미 "근거 약한 신호"로 보는 타입)다.
   - 근거없음·저문서면 → schema 미러 + 기존 4개 lint 스윕 + candidate 폴백.
   - 정당하게 commit/jira/pr로 표현 불가하면 → 규칙이 틀린 게 아니라 evidence 어휘가 좁은 것
     (`assembly.py:134` `_DECISION_REF_TYPE`가 commit/jira/pr만) → spec/wiki 타입 확장.

## 착수 조건

bb2 4개 타입 확인 → 처리 방향 결정 → schema + lint + candidate 폴백 동반 구현 → 데이터레포 마이그레이션.
