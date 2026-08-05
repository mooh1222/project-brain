---
name: {{PROJECT}}-brain-session-ingest
description: |
  Use when BB2(LineBubble2) 개발을 진행하면서 brain에 적재하거나(시나리오 가 — 기능 개발
  시작·개발 중 "이거 저장해두자"·저장된 객체 값 갱신), 과거 세션 기록에서 지식을 추출할 때
  (시나리오 다 — "이 세션에서 추출", "과거 세션에서 뽑아줘", "백필", "세션 지식 추출").
  "개발하면서 brain에", "기획서 후보 선점", "이 결정 저장해줘", "세션 백필"처럼 진행 중
  적재·세션 추출이 BB2 맥락에서 나오면 스킬 이름 없이도 이 스킬을 쓴다.
  완료된 기능의 소급 적재는 {{PROJECT}}-brain-ingest 몫이고, 조회(읽기)는 {{PROJECT}}-brain-query 몫이다.
---

# {{PROJECT}} Brain 세션 적재 — 진행 중 개발 + 과거 세션 추출

추출 판단은 작업자가 하고 CLI는 기록·마킹·스캔을 맡는다. 객체 모양과 갱신은 sibling ingest 스킬이 정본이다.

## 어느 시나리오인가

| 상황 | 절차 |
|---|---|
| 기능 개발 시작·개발 중 적재·객체 값 갱신 | references/dev-ingest.md ((가) 4단계) |
| 끝난 세션에서 지식 추출 (지정/주제/일괄) | references/session-extract.md ((다) 코어+3모드) |
| 이미 저장된 객체와 현실이 다름 | `{{PROJECT}}-brain-ingest/references/update-rules.md` — 양쪽 공통 |

## 공통 불변 규칙

- 적재와 최종화는 `{{PROJECT}}-brain-ingest/references/ingest-tools.md` 및 `{{PROJECT}}-brain-ingest/references/completeness-checklist.md`를 직접 따른다. direct/assembled 모두 coverage 없는 쓰기를 허용하지 않고 단계 수는 여기 복제하지 않는다.
- 적재로 raw 청크 수가 변하면 실코퍼스 가드의 `EXPECTED_RAW_CHUNKS`(`{{BRAIN_ROOT}}/checks/test_real_corpus.py`)를 **의식적으로 갱신**하고 같은 커밋에 포함한다(객체 색인 행은 디스크의 색인 대상 `.json` 수로 자동 대조되니 손갱신 불필요).
- 파괴 작업(promote·일괄 수정) 전 "커밋 먼저".
- 검수 상태: 사용자 명시 지시 = reviewed(reviewer=user-statement) / 작업자 판단 = candidate. reviewed 의미 변경은 `{{PROJECT}}-brain-ingest/references/update-rules.md`를 따른다.
- 분류 3종(스펙 §6): 팀 지식 → 적재 / 개인 메모리(주어가 사용자·어시스턴트·작업 방식) → 적재 안 함, auto-memory·handoff에 / 기존 kind로 못 담는 교훈·함정 → `{{BRAIN_ROOT}}/raw/sources/insights/backlog.md`에 누적(P3 실례 수집 — 날짜·출처 세션 uuid·한 줄 요약·핵심 인용. raw 색인 대상이라 추가 후 rebuild까지 한 동작).
- Insight(인사이트, 2026-06-15 신설 kind): 2개 이상 객체·구현·결정을 가로지르는 **검증된** 관찰/위험/교훈은 raw backlog가 아니라 Insight kind로 적재한다(candidate 거부·reviewed 직접·source 개수·사용자 진술 근거 — 절차는 `{{PROJECT}}-brain-ingest/references/object-model.md` "Insight 적재 규칙"). 미검증 후보는 여전히 backlog.
