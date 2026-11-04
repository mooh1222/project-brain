> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

# KW-E3 실행 환경

- 작업 checkout: `/Users/al03040455/orca/workspaces/project-brain/brain-kw-e3`.
- 시작 branch `mooh1222/brain-kw-e3`, HEAD와 통합 tip 모두 `be75896a18efc076150708882c8af453ee970672` (E1 #115, E2 #116 포함).
- 작업 진입 최초 git status에는 변경이 없었다. 파일로 저장한 `engine-status.txt`는 evidence 디렉터리를 만든 뒤의 스냅샷이므로 `?? .scratch/`를 포함한다. `engine-commit.txt`, `engine.diff`에 엔진 기준점과 빈 tracked diff를 기록했다.
- Python 3.12.11 (`uv sync --frozen --python 3.12`), Codex CLI 0.166.0.
- 실행·회상·판정 세션은 `gpt-6.1-sol`, `model_reasoning_effort="high"`. 각 `*.native.jsonl`의 실제 `turn_context.model`과 `effort`, `session_meta.cli_version`을 대조한다. Astra/대체 모델 사용 없음.
- 비대화식 `codex --no-daemon exec`; 두 회차 queue가 각각 직렬 실행하며 Codex는 동시에 최대 2개. 추가 하위 에이전트 생성은 비활성화한다.
- 각 합성 프로젝트는 독립 Git repo이며 source fixture는 합성 운영 문서·조사 관찰뿐이다. 사내 코드·실코퍼스 본문은 사용하지 않는다. 도구 wrapper에 있는 엔진/Python 절대 경로는 실행 환경 연결이다.
- 검색/색인은 `PROJECT_BRAIN_EMBEDDER=stub`, regex tokenizer를 기존 테스트 주입 방식으로 고정한다. `sitecustomize.py`는 RealEmbedder의 실제 모델 로드를 거부한다. HF/Transformers offline 플래그도 사용한다. 실모델 임베딩 서비스는 호출하지 않는다.
- 매 프로젝트의 설치 report와 `installed-skills.sha256.json`을 보관한다. 회차 간 합성 원문·초기 corpus 의미는 동일하며 경로·엔진 소유 갱신 시각·SQLite bytes 등 환경 고유값은 다를 수 있다.
- 기록 세션과 회상 세션은 별개 신규 thread다. 회상 요청에는 디렉터리/일반 프로젝트 지침/설치 스킬과 자연어 질문만 제공하며, 원래 대화·저장 경로·객체 ID·기대 답변은 제공하지 않는다.
- 최초 W-T1 기록 세션은 기본 host memory 설정을 사용했다. 모든 회상 세션과 이후 기록·판정 세션은 `features.memories=false`, `features.hooks=false`로 실행하여 이전 세션 및 자동 hook 영향을 차단했다. W-T1 회상도 원래 대화를 받지 않았다.
- 최초 W-T2 두 시도는 실제 적재/회수 후 합성 프로젝트의 eval/checks 및 origin/main 준비 누락으로 전체 최종화를 완료하지 못했다. `w-t2/`는 실패/미완료 근거로 보존하고 통과 집계에서 제외한다. 동일 자연어 요청을 `w-t2-recheck/`의 새 프로젝트 두 곳에서 재실행한다. local origin은 프로젝트 자기 자신을 가리키는 합성 Git ref이며 외부 원격 서비스가 아니다.
- W-T4는 정상 회수 후 별도 읽기 세션에서 손상된 unrelated topic(JSON), mode 000인 기존 개발 제안 문서, 손상 SQLite index를 주입한다. `fault-conditions.md`에 주입 시점과 조건을 기록한다.
- W-T6는 첫 성공 ingest 뒤 첫 SHA 초안 갱신 직전에 별도 writer가 기존 공개 update_patch 인터페이스로 질문 하나를 추가한다. 전달한 expected_sha는 그대로 사용되므로 stale-SHA가 실제 발생해야 한다. `race-injected.txt`, `ingest-calls.txt`, 원래 명령 로그로 복구 및 재적재 유무를 확인한다.
- 재사용 평가 schema, registry, 새 엔진 명령/채널은 만들지 않는다. 여기에 있는 스크립트는 이 run의 환경 준비·순차 실행·기존 로그 Markdown 관찰만 수행하는 로컬 증거다.
- 파일 해시는 합성 프로젝트의 파일 본문을 대상으로 하며 `.git` 내부와 Python `__pycache__`는 제외한다. Git은 별도 `git status --short --branch`로 비교한다. mode 000 파일은 해시 목록의 PermissionError와 주입 전 별도 SHA를 함께 보존하며, 조회 중 권한을 풀지 않는다.
