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

# BB2 Brain 세션 적재 — (가) 진행 중 개발 + (다) 과거 세션 추출

스펙(권위): `docs/superpowers/specs/2026-06-11-{{PROJECT}}-brain-session-ingest-design.md`
경계: 추출 판단(무엇을 지식으로 뽑나)은 이 스킬(Claude), 기록·마킹·스캔만 CLI.

## 어느 시나리오인가

| 상황 | 절차 |
|---|---|
| 기능 개발 시작·개발 중 적재·객체 값 갱신 | references/dev-ingest.md ((가) 4단계) |
| 끝난 세션에서 지식 추출 (지정/주제/일괄) | references/session-extract.md ((다) 코어+3모드) |
| 이미 저장된 객체와 현실이 다름 | references/update-rules.md (갱신 분기표) — 양쪽 공통 |

## 공통 불변 규칙

- 적재 후 6단계: `project-brain ingest …` 성공 → `lint`(무결성 — 끊긴 참조 0) → `index rebuild` → `eval --check-ids && eval`(골든셋) → 샘플 `search` → 고립 재점검(`project-brain graph isolated`로 신규/잔여 고립을 나열 — 명백한 건 에이전트가 (a)즉시 연결 (b)의도적 종착점 유지 (c)제거로 처리하고, 애매한 것만 사용자 확인. 정본 절차는 `{{PROJECT}}-brain-ingest/references/ingest-tools.md` "적재 후 확인"). 색인 신선도 가드가 rebuild 누락을 막아주지만, 골든셋 회귀는 절차로만 잡힌다. eval/search 출력은 `2>/dev/null | jq`로 읽는다(stdout=깨끗한 JSON·노이즈는 stderr; eval 통과수=`.summary`의 passed/failed/total, search 적중=`.results`) — `2>&1`로 합쳐 손파싱 금지(키 혼동·잔여줄로 깨짐).
- 적재로 raw 청크 수가 변하면 실코퍼스 가드의 `EXPECTED_RAW_CHUNKS`(`{{BRAIN_ROOT}}/checks/test_real_corpus.py`)를 **의식적으로 갱신**하고 같은 커밋에 포함한다(객체 색인 행은 디스크의 색인 대상 `.json` 수로 자동 대조되니 손갱신 불필요).
- 파괴 작업(promote·일괄 수정) 전 "커밋 먼저".
- 검수 상태: 사용자 명시 지시 = reviewed(reviewer=user-statement) / 어시스턴트 판단 = candidate. reviewed 객체의 의미 변경은 검토 라운드 없이 금지(update-rules.md).
- 분류 3종(스펙 §6): 팀 지식 → 적재 / 개인 메모리(주어가 사용자·어시스턴트·작업 방식) → 적재 안 함, auto-memory·handoff에 / 기존 kind로 못 담는 교훈·함정 → `{{BRAIN_ROOT}}/raw/sources/insights/backlog.md`에 누적(P3 실례 수집 — 날짜·출처 세션 uuid·한 줄 요약·핵심 인용. raw 색인 대상이라 추가 후 rebuild까지 한 동작).
- Insight(인사이트, 2026-06-15 신설 kind): 2개 이상 객체·구현·결정을 가로지르는 **검증된** 관찰/위험/교훈은 raw backlog가 아니라 Insight kind로 적재한다(candidate 거부·reviewed 직접·source 개수·사용자 진술 근거 — 절차는 `{{PROJECT}}-brain-ingest/references/object-model.md` "Insight 적재 규칙"). 미검증 후보는 여전히 backlog.
