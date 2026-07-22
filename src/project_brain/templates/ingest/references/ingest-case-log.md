# 적재 케이스 로그 (verify 변칙 누적)

scripts/의 표본 파생 처리가 어떤 실변칙을 봤는지 적재별로 1줄 남긴다. HOOK이 반복되면
일반 정규화 층(assemble_notes.py)으로 승격하는 신호. 세션 너머 분석 보존 — 다음 적재는
재발견이 아니라 여기를 읽고 일반화한다.

| 적재 | 날짜 | verify 형태 | 변칙 | 처리 |
|---|---|---|---|---|
| ball-select | 2026-06-26 | `{groups}` 래핑 | 14 DecisionRecord(jira/commit 근거) | decisions[] 노트(엔진 build_decisions) |
| main-map | 2026-06-25 | list | `map-stage-episode` 그룹 verify가 corrected_atoms 빈 반환 + 의미 보정 2건 | extract.atoms 폴백(정규화 층) + CORRECTIONS(선언적) |
| 대량 적재 | 2026-07-21 | batch | 136개 항목에서 단건 러너만으로는 마무리 작업이 반복돼 임시 wave/finalize 러너가 생김 | batch runner와 한 번의 finalization으로 항목 실행과 마무리를 분리 |
| 대량 적재 | 2026-07-21 | workflow | 최상위 상태는 completed지만 내부 27개 항목이 실패함 | 예상 수, 항목 결과, 실패 목록을 validator로 확인한 뒤에만 진행 |
| 조립 노트 | 2026-07-21 | build | 완성 ID를 논리 key에 넣어 이중 접두 객체 24개가 생기고 65개 객체를 롤백함 | 논리 key 형식을 검사하고 완성 ID를 자동 보정하지 않음 |
| 코드 흐름 검증 | 2026-07-21 | extract/verify | 프로젝트 호출처 검증 계약을 빼면 흐름 근거가 빠져 68개를 재검증하고 33개를 수정함 | 계약을 적용해 항목별 호출 흐름을 다시 검증하고 수정 |
