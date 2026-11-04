# KW 통합 검수 재실행 환경

- 기준 HEAD: `4582d1e6e3b3ae6388a445a58047ea57a0347453`, branch `mooh1222/brain-kw-fix`.
- 통합 tip `mooh1222/brain-knowledge-workflow` 병합 확인: `Already up to date`.
- Codex CLI 0.166.0, 실행·회상·판정 `gpt-6.1-sol`, high. 모델과 effort는 각 native JSONL의 turn_context로 별도 확인한다.
- 기록·회상·판정 전 과정 `features.memories=false`, `memories.use_memories=false`, `memories.generate_memories=false`, `features.hooks=false`, `features.multi_agent=false`. 각 command.json에 정확한 시작 인자가 있다.
- `codex --no-daemon exec`, 독립 두 회차 큐 안에서 직렬 실행, 동시 최대 2개. 판정은 실행과 별도 신규 세션이다. 추가 에이전트 생성은 허용하지 않는다.
- Python 3.12.11. 각 합성 프로젝트는 현재 템플릿을 새로 설치한다. 기록·회상 요청은 E3의 W-T1/W-T3와 동일하다. 회차별 원문·초기 corpus의 의미는 같으며 경로·갱신 시각·SQLite bytes는 환경 고유값이다.
- PROJECT_BRAIN_EMBEDDER=stub, StubEmbedder와 regex tokenizer 주입. sitecustomize가 RealEmbedder._ensure_model을 예외로 차단하고 HF/Transformers offline을 지정한다. 실모델 임베딩 로드 금지.
- 회상에는 자연어 요청과 통상 프로젝트 지침·설치 스킬·작업 디렉터리만 제공한다. 기록 대화·저장 경로·객체 ID·기대 답변을 전달하지 않는다.
- before/after-recall SHA 목록은 .git 내부와 __pycache__를 제외한 프로젝트 파일 본문이며 Git 상태는 따로 비교한다. 판정 뒤 현재 상태와도 재대조한다.
- engine.diff는 합성 환경 준비 시의 변경이다. final-engine.diff는 커밋 전 문서·보고서 변경까지 포함한다. 설치 파일 해시는 각 회차 installed-skills.sha256.json이다.
- 기존 E3 W-T1 두 회차는 memory를 읽었으므로 이번 통과 집계에서 제외한다. 기존 E3 W-T2·W-T4~W-T6은 과거 기준점의 증거를 유지하며 이번에 재실행했다고 표시하지 않는다.
- doctor 정합성 검사: 오류 0, 경고 2. 두 경고 모두 기존 Codex wrapper가 plugin list에 --profile을 전달하여 CLI가 거부한 환경 조회 문제다. 프로젝트 파일 정합성 오류는 없으며 전역 설정은 수정하지 않았다.
