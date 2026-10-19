# 초안 재료로 기존 적재 시작하기

`project-brain-draft-materials-v1`의 materials.json은 항목·원문 위치·기계적 bytes 상태를
모은 재생성 가능한 입력이다. 준비 성공과 적재 완료를 구분한다. 초안, packet, 그 안의
발췌 사본이나 에이전트 요약을 EvidenceManifest의 raw 원문으로 등록하지 않는다.

1. **범위와 원문 확인.** packet의 draft SHA·선택 key·목표 repo/revision을 읽고 이번
   Source Intake에 실제 코드·문서·세션 원문을 선언한다. 선택한 topic의 최신 상태와 다르면
   차이를 확인한다. metadata나 packet의 items만으로 최종 소스 범위를 정하지 않는다.
2. **미결과 상태 해석.** diagnostics, unresolved_items와 limits를 읽는다. hypothesis/question은
   자동 적재하지 않는다. partial은 일부 근거가 부족한 재료를 뜻하며 단건/배치 적재의 부분
   성공을 허용하는 표지가 아니다. 필요한 원문이 없으면 보완하거나 해당 주장을 보류한다.
3. **원문 대조와 독립 검증.** 저장 quote와 목표 파일의 quote 상태를 구분한다. present/absent/
   multiple·file hash 차이·파일 부재/조회 불가는 의미 검증이 아니다. code는 실제 목표 코드와
   프로젝트 코드 검증 계약을 따르고, 문서는 유일한 절과 문맥을 직접 확인한다. 외부 locator는
   해당 도구로 확인하며 packet 생성이 외부 fetch를 했다고 가정하지 않는다.
4. **사용자 의도·결정.** 보존 발화와 질문 맥락·원 session/위치/시각을 제시하고, 적재할 진술을
   이번 적재 세션에서 문장 단위로 확인받는다. 확인 세션의 기존 `source_type=session` manifest와
   `reviewer=user-statement` 경로로 근거화한다. 코드 사실은 사용자 확인만으로 reviewed가 되지
   않는다. 미확인 발췌는 draft에 남긴다. `user_statement` raw 범위는 확장하지 않는다.
5. **기존 객체 설계와 적재.** 개념 선언·의미 원자·객체 경계/ID/status/history·coverage와
   독립 expected planner를 기존 절차로 정한다. 어휘는 사용자가 승인한 개념에서만 만든다.
   코드 중심 입력은 assembled, 문서/세션 등은 지원되는 direct 또는 build extra_objects로
   연결한다. 새 draft 전용 쓰기 경로는 없다.
6. **실제 완료 확인.** 같은 ID의 객체가 있어도 내용·근거·현재 상태를 비교하고 update/supersede/
   no_changes를 판단한다. MutationService의 canonical receipt와 기존 semantic finalization으로
   변경/무변경·부분 실패·재실행을 확인한다. prepare 성공, 옛 quote 일치나 기존 ID만으로 완료를
   보고하지 않는다. 실제 생성/갱신 객체 ID와 require_code_locators를 기존 회상 검사에 맞춘다.

모든 적재 후보는 처음의 의미 검증이 필요하다. 완전성 점검은 최종 소스 구조를 초안과 독립적으로
대조해 미기록·미결·충돌을 찾는다. packet의 선택 목록을 의미 완전성의 증거로 쓰지 않는다.
쓰기 인자·coverage·receipt·최종화는 `ingest-tools.md`, 의미 완전성은
`completeness-checklist.md`가 정본이다. 보완이 필요하면 재료를 draft 스킬로 넘기며
ingest가 초안을 직접 갱신하거나 실패 때문에 삭제/완료 표시하지 않는다.
