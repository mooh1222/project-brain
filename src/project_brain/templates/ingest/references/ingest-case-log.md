# 적재 케이스 로그 (verify 변칙 누적)

scripts/의 표본 파생 처리가 어떤 실변칙을 봤는지 적재별로 1줄 남긴다. HOOK이 반복되면
일반 정규화 층(assemble_notes.py)으로 승격하는 신호. 세션 너머 분석 보존 — 다음 적재는
재발견이 아니라 여기를 읽고 일반화한다.

| 적재 | 날짜 | verify 형태 | 변칙 | 처리 |
|---|---|---|---|---|
| ball-select | 2026-06-26 | `{groups}` 래핑 | 14 DecisionRecord(jira/commit 근거) | decisions[] 노트(엔진 build_decisions) |
| main-map | 2026-06-25 | list | `map-stage-episode` 그룹 verify가 corrected_atoms 빈 반환 + 의미 보정 2건 | extract.atoms 폴백(정규화 층) + CORRECTIONS(선언적) |
