W-T1과 W-T3 재실행의 1회차를 독립 판정해. 파일 수정·추가 에이전트 생성·개인 memory 읽기는 하지 마.
엔진 checkout: /Users/al03040455/orca/workspaces/project-brain/brain-kw-fix
증거 루트: /Users/al03040455/orca/workspaces/project-brain/brain-kw-fix/.scratch/brain-knowledge-workflow-validation/20261104-review-fix
판정 기준: 엔진 docs/specs/2026-11-04-brain-knowledge-workflow.md의 W-T1, W-T3 하위 성공 조건과 실행 프로토콜. 이 작업은 통합 code-review P1/P3 수정의 재확인이며 W-T2/W-T4~6은 재실행 범위 밖이야.
증거 루트의 environment.md, w-t1/round-1/ 및 w-t3/round-1/ 전체 소규모 문서·실제 프로젝트 파일·요청·record/recall.events.jsonl·native.jsonl·설치 파일 해시·before/after-recall.sha256 및 git.txt를 읽고 대조해. 실행자 자기 보고만으로 통과시키지 마. 실제 저장 내용, 본문·출처 읽기, 새 세션의 발견·검수 표시·제안과 채택 작업 구분을 확인해.
각 command.json은 시작 인자다. native의 실제 모델/effort/CLI, 기록·회상 thread 분리, memory 주입·개인 memory 파일 읽기·hook 실행의 부재도 독립 대조해. 기록부터 memory/hook을 끈 조건이 핵심이야. 모델은 gpt-6.1-sol high여야 하고 검색은 StubEmbedder·regex이며 실모델 로드를 허용하지 않아.
조회 무변경은 저장된 전후 SHA/Git를 비교하고 현재 상태와도 대조해. 지원하지 않는 명령 등 실패가 있으면 복구 여부와 증거 한계를 공개해. W-T1/W-T3 하위 조건별 PASS/FAIL/NOT_EXECUTED, 환경 조건, 예상 밖 쓰기 여부, 남은 문제를 한국어 Markdown으로 답해. 상대 회차를 판정하지 마. 산출물의 로컬 증거는 경로 텍스트로 표시해도 돼.
