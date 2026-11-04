---
name: {{PROJECT}}-brain-session-ingest
description: |
  Use when {{PROJECT}} 개발을 진행하면서 brain에 적재하거나(시나리오 가 — 기능 개발
  시작·개발 중 "이거 저장해두자"·저장된 객체 값 갱신), 과거 세션 기록에서 지식을 추출할 때
  (시나리오 다 — "이 세션에서 추출", "과거 세션에서 뽑아줘", "백필", "세션 지식 추출").
  "개발하면서 brain에", "기획서 후보 선점", "이 결정 저장해줘", "세션 백필", "나중에 고치자",
  "백로그에 남겨", "조사하던 이해·가설을 이어가자"처럼 진행 중 기록·개선 제안·세션 추출이 {{PROJECT}}
  맥락에서 나오면 스킬 이름 없이도 이 스킬을 쓴다.
  완료된 기능의 소급 적재는 {{PROJECT}}-brain-ingest 몫이고, 조회(읽기)는 {{PROJECT}}-brain-query 몫이다.
---

# {{PROJECT}} Brain 세션 적재 — 진행 중 개발 + 과거 세션 추출

추출 판단은 작업자가 하고 CLI는 기록·마킹·스캔을 맡는다. 객체 모양과 갱신은 sibling ingest 스킬이 정본이다.
이 스킬은 현재 세션과 과거 세션에서 재사용할 자료를 추출·분류한다. 진행 중·미결 재료는
정식 객체로 밀어 넣지 않고 `{{PROJECT}}-brain-draft`로 넘기며, 정식 적재 가능한 지식만
`{{PROJECT}}-brain-ingest` 절차로 넘긴다. 지식 초안의 생성·재개·갱신 수명주기는
`{{PROJECT}}-brain-draft`가 맡고 이 스킬은 재료 추출에서 멈춘다.

기록 경로를 판단할 때 먼저
`../{{PROJECT}}-brain-draft/references/knowledge-workflow.md`를 읽는다.
개발 재료나 현재·과거 세션의 지식 주제를 다루기 전에
`../{{PROJECT}}-brain-draft/references/discovery.md`를 읽고 관련 초안 목록을 먼저 확인한다.
선택한 topic과 미결 재료를 draft 스킬에 넘기며, 아래 절차에서 같은 목록을 반복 조회하지 않는다.
개선 제안만 기록하는 요청에는 전체 초안 발견을 선행하지 않는다.

## 어느 시나리오인가

| 상황 | 절차 |
|---|---|
| 기능 개발 시작·개발 중 기록·명시적 적재·객체 값 갱신 | references/dev-ingest.md (draft 기록과 정식 적재 분기) |
| 끝난 세션에서 지식 추출 (지정/주제/일괄) | references/session-extract.md ((다) 코어+3모드) |
| 이미 저장된 객체와 현실이 다름 | `{{PROJECT}}-brain-ingest/references/update-rules.md` — 양쪽 공통 |

## 공통 불변 규칙

- 현재 세션이나 과거 세션에서 어휘 후보를 추출할 때 `../{{PROJECT}}-brain-ingest/references/glossary-criteria.md`를 먼저 읽는다. 어휘 후보가 없는 세션 작업에서는 읽지 않으며 기준을 이 스킬에 복제하지 않는다.
- 적재와 최종화는 `{{PROJECT}}-brain-ingest/references/ingest-tools.md` 및 `{{PROJECT}}-brain-ingest/references/completeness-checklist.md`를 직접 따른다. direct/assembled 모두 coverage 없는 쓰기를 허용하지 않고 단계 수는 여기 복제하지 않는다.
- 적재로 raw 청크 수가 변하면 실코퍼스 가드의 `EXPECTED_RAW_CHUNKS`(`{{BRAIN_ROOT}}/checks/test_real_corpus.py`)를 **의식적으로 갱신**하고 같은 커밋에 포함한다(객체 색인 행은 디스크의 색인 대상 `.json` 수로 자동 대조되니 손갱신 불필요).
- 많은 객체를 바꾸기 전 복구 기준이 필요하면 승인된 작업 경로만 명시적으로 stage·commit한다.
  `git add -A`, `git add .`, `git commit -a`는 쓰지 않는다. 기존 사용자 변경과 겹치면
  자동 commit·stash하지 않고 겹친 범위를 보고한 뒤 멈춘다.
- 검수 상태: 코드로 확인 가능한 사실은 현재 checkout과 근거를 대조하기 전 사용자 진술만으로 reviewed로
  올리지 않는다. 코드에 없는 의도·결정에 관한 사용자 본인 진술은 `reviewer=user-statement`로
  reviewed가 될 수 있고, 작업자 판단은 candidate다. reviewed 의미 변경은
  `{{PROJECT}}-brain-ingest/references/update-rules.md`를 따른다.
- 개인 메모리(주어가 사용자·어시스턴트·작업 방식)는 Brain에 넣지 않고 auto-memory·handoff에만
  표시한다. 원문과 합성 지식의 구분·기록 위치·기존 검증 대기 자료 보존은 공통 판단 reference를 따른다.
- Insight의 상세 적재 조건(candidate 거부·reviewed 직접·source 개수·사용자 진술 근거)은
  `../{{PROJECT}}-brain-ingest/references/object-model.md`의 "Insight 적재 규칙"을 따른다.
