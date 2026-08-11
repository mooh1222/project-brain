# SDD ledger — plan: docs/superpowers/plans/2026-07-28-agents-doctor-global-skill-mirror.md
# 적응: 대상 파일이 ~/.agents (git 밖) — 리뷰 패키지는 scratchpad 백업 대비 diff -u 로 생성
Task 1: minor (deferred): 면제 가드 케이스는 Task 2 전까지 무신호 — Task 2 리뷰에서 enabledPlugins 실독 여부 함께 확인
Task 1: minor (deferred): 꺼진 플러그인(false) 면제 거부 테스트 없음 — Task 2 구현의 `enabled is not True` 경로 커버 후보
Task 1: minor (deferred): 면제 가드가 부정 assert 단독 의존(빨간 케이스가 상쇄), assert 실패 메시지 생략은 기존 관례
Task 1: complete (backup diff task-1-package.diff, review clean/Approved)
Task 2: minor (deferred): enabledPlugins가 dict 아닌 타입이면 plugin_skill_names에서 traceback — isinstance 방어 한 줄 후보 (브리프 빈틈)
Task 2: minor (deferred): 면제가 캐시 전 버전 이름 합집합 — 거짓 음성 방향 절충, 현 데이터 피해 없음
Task 2: minor (deferred): 꺼진 플러그인(false) 분기·SKILL.md 스킵에 테스트 없음 — exempt 케이스 복제+False 케이스 후보
Task 2: complete (backup diff task-2-package.diff, review clean/Approved — 실환경 WARN 9건 독립 재현·돌연변이 검증 포함)
Task 3: minor (deferred): pkm-vault는 사본 아닌 "절대경로 심링크를 담은 실물 디렉토리"였음 — 교체 정당성엔 무영향, 다음 정리 때 구분 관찰
Task 3: minor (deferred): lock 파일 끝 개행 추가(jq 부수효과, 무해) / 무수정 증거는 mtime뿐(환경 한계) / 패키지 9개 표기 중 orchestration은 선행 산출물
Task 3: complete (state evidence task-3-package.txt, review clean/Approved — diff -r 6건 내용동일·lock 의미비교·롤백 완비 검증)
Task 4: minor (deferred): SKILL.md 결과읽기의 INFO 설명이 프로젝트 모드 전용임이 미표기 — "(프로젝트 모드)" 한 마디 후보
Task 4: minor (deferred): 면제가 플러그인 캐시 실물 존재에 의존한다는 뉘앙스 미기재 — 표현 조이기 후보
Task 4: complete (backup diff task-4-package.diff, review clean/Approved — 검증 3종 리뷰어 독립 재현)
FINAL: ACCEPT (must-fix 0, deferred 9건 전부 defer 판정, 신규 Minor 4건 기록) — 완료 기준 6/6
