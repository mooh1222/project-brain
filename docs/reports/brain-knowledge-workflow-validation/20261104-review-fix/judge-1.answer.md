**W-T1 1회차: PASS. W-T3 1회차: PASS.** 실제 저장 내용, 본문·출처 조회 결과, native 로그와 현재 파일 상태를 대조했습니다. 다른 회차와 W-T2/W-T4~6은 판정하지 않았습니다.

아래 경로는 다음 증거 루트 기준입니다.

`/Users/al03040455/orca/workspaces/project-brain/brain-kw-fix/.scratch/brain-knowledge-workflow-validation/20261104-review-fix`

| 사례·하위 조건 | 판정 | 확인 근거 |
|---|---|---|
| W-T1 — 이해·가설·미결 보존 | PASS | `w-t1/round-1/project/brain/drafts/time-boundary-study.json`에 단일 관찰, 미확인 네트워크 지연 가설, 추가 표본·시계 동기화 질문이 분리되어 있음 |
| W-T1 — 단건·기능 외 조사 주제 허용 | PASS | 기능 구현이 아닌 시간 경계 조사 하나를 기존 draft create/update로 기록함 |
| W-T1 — 새 세션에서 적절한 초안 발견 | PASS | 저장 위치·ID 없는 회상 요청에서 `draft list`로 발견하고 `draft show`로 선택함 |
| W-T1 — 필요한 본문·출처·미결로 재개 | PASS | 네 항목을 각각 `--item`으로 읽고 `docs/time-study.md` 원문도 조회함. 회수된 항목·출처가 현재 저장 내용과 일치함 |
| W-T1 — 검수 상태 구분 | PASS | 회상 답변에 **“초안(미검수 작업 기억)”**, 단일 표본의 일반화 한계와 인과관계 미확인을 명시함 |
| W-T3 — 지식과 개선 행동 분리 | PASS | `project/brain/drafts/retry-rules.json`에 문서상 이해·미결을, `project/brain/backlog/development.md`에 개선 행동을 보존함 |
| W-T3 — 제안의 문제·효과·출처·한계 보존 | PASS | 공통화 제안에 수정 누락 위험, 유지 편의 효과, 운영 규칙·사용자 요청 출처, 구현 중복·비용 미검증을 기록함 |
| W-T3 — 분류명 없는 새 요청에서 본문 직접 발견 | PASS | query 스킬과 설정을 읽고 백로그 본문을 직접 조회함. 일반 검색이나 전체 초안 목록을 선행하지 않음 |
| W-T3 — 제안·채택 작업·현재 확인 한계 구분 | PASS | 공통화는 실행 미확정 제안, 선행 경계 테스트는 작업 #42로 구분함. 연결을 완료로 해석하지 않고 현재 진행·완료 여부 미확인을 명시함 |
| W-T3 — 진행 상태 필드 금지·채택 링크만 기록 | PASS | 진행·채택 상태 필드가 없고, 채택된 경계 테스트 항목에는 제목 아래 작업 링크 한 줄만 있음 |

주요 의미 동작 증거는 각 회차의 `record.request.md`, `recall.request.md`, `record.events.jsonl`, `recall.events.jsonl`, `record.native.jsonl`, `recall.native.jsonl`, 실제 프로젝트 파일 및 답변입니다. native와 events의 명령·출력·종료 코드는 W-T1 기록/회상 **16/17건**, W-T3 **22/10건** 모두 일치했고, 저장된 최종 답변도 native 응답과 일치했습니다.

**환경 조건도 확인 범위에서 PASS입니다.**

| 조건 | 독립 대조 결과 |
|---|---|
| 실제 모델·effort·CLI | 네 실행 세션과 현재 판정 세션의 native에서 `gpt-6.1-sol`, `high`, CLI `0.166.0` 확인 |
| 기록·회상 분리 | 각각 다른 thread ID이며 신규 `exec`로 실행됨. 회상 입력에 기록 대화·저장 경로·객체 ID·기대 답변이 주입되지 않음 |
| 기록 시작부터 memory/hook 비활성화 | 네 command 모두 `features.memories=false`, `memories.use_memories=false`, `memories.generate_memories=false`, `features.hooks=false` 포함. native 입력·실제 호출에서 memory 주입, 개인 memory 파일 읽기, hook 실행 흔적 없음 |
| 검색 환경 | 도구 wrapper가 stub을 강제하고 sitecustomize가 regex를 주입하며 실모델 로드를 예외로 차단함. 실제 SQLite metadata도 `stub:sha256-gaussian`, `regex@4` |
| 설치 파일 | 각 프로젝트 66개 파일의 현재 해시가 저장된 해시·manifest·현재 엔진 템플릿 렌더 결과와 모두 일치. skipped 없음 |
| 엔진 기준점 | HEAD는 `4582d1e6e3b3ae6388a445a58047ea57a0347453`. 저장된 `engine.diff`와 현재 전체 diff는 다르지만, 확인된 스펙 차이는 조사·접속 표현 세 곳이며 W-T1/W-T3 조건과 실행 프로토콜은 동일함. 실행 템플릿도 일치함 |

**조회 무변경은 PASS입니다.**

| 비교 | W-T1 | W-T3 |
|---|---|---|
| initial → 회상 전 | 초안 1개만 추가 | 초안·백로그 2개만 추가 |
| 회상 전 → 후 SHA | 86개 파일 모두 동일 | 87개 파일 모두 동일 |
| 회상 후 → 현재 재계산 SHA | 모두 동일 | 모두 동일 |
| 회상 전·후·현재 Git 상태 | 동일 | 동일 |

근거는 각 회차의 `initial.sha256`, `before-recall.sha256`, `after-recall.sha256` 및 대응 `git.txt`입니다. 색인 DB·설치 파일·원문·기존 객체도 비교에 포함됩니다. `.brain.project-brain-corpus.lock`은 초기부터 존재했습니다.

**실패와 증거 한계는 다음과 같습니다.**

- 네 세션 모두 CLI 시작 시 `bb2-agent-env` marketplace manifest 오류가 발생했습니다. 오류 자체의 복구 증거는 없지만, 이후 로컬 스킬 사용·기록·회상은 모두 exit 0으로 완료됐습니다.
- W-T3 기록 중 아직 없는 백로그를 `cat`하여 exit 1이 발생했습니다. 이후 기록 요청 권한으로 파일을 생성하고 초안 갱신·lint·새 세션 회상까지 성공했습니다. 두 사례에서 지원하지 않는 엔진 명령의 실패는 발견하지 못했습니다.
- 프로젝트 비교 범위에서는 예상 밖 쓰기가 없습니다. 다만 SHA 목록은 `.git` 내부와 `__pycache__`를 제외합니다. CLI의 프로젝트 밖 marketplace staging 갱신 시도도 있어 **전역 파일시스템까지 무변경이었다고 판정할 수는 없습니다.**
- W-T3 기록에서는 프로젝트 밖 임시 patch 파일을 만들었고 삭제 명령은 로그에 없습니다. 이는 회상 중 쓰기는 아닙니다.
- `preparation-errors.md`의 numpy/import 준비 실패는 원본 실패 로그가 없어 상세 원인을 독립 확증하지 못했습니다. 이후 판정 시작 복구는 현재 native 세션으로 확인했습니다. 이번 검수의 추출 스크립트도 한 번 `KeyError`가 났지만 읽기 전용 재조회로 대조를 완료했습니다.

판정을 막는 미충족 하위 조건은 없습니다. 다만 이 결과는 **지정된 1회차의 통과**이며 2/2 또는 전체 검증 완료를 의미하지 않습니다. 검수 중 파일 수정·추가 에이전트 생성·개인 memory 읽기는 하지 않았고, 작업 시작·종료 Git 상태도 같습니다.
