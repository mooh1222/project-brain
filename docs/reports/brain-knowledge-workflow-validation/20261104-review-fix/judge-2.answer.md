**W-T1·W-T3 재실행 2회차의 기능 하위 조건은 모두 PASS입니다.** 실행자 보고와 별개로 실제 저장 파일, events/native 로그, 전후 SHA·Git 및 현재 상태를 대조했습니다. 다른 회차와 W-T2·W-T4~6은 판정하지 않았습니다.

증거 경로는 다음 루트 기준입니다.

`/Users/al03040455/orca/workspaces/project-brain/brain-kw-fix/.scratch/brain-knowledge-workflow-validation/20261104-review-fix`

| W-T1 하위 조건 | 판정 | 독립 확인 결과 |
|---|---|---|
| 이해·가설·미결과 출처 보존 | PASS | `w-t1/round-2/project/brain/drafts/time-boundary-study.json`에 단일 관찰, 네트워크 지연 가설, 추가 표본·시계 동기화 미결이 구분되어 저장됨 |
| 단건·기능 외 조사 주제 허용 | PASS | 기능 구현 없이 시간 경계 조사 한 주제를 기존 draft 명령으로 생성·SHA 갱신함 |
| 새 세션의 초안 발견 | PASS | 자연어 요청만 받은 별도 thread에서 `draft list` → `draft show`로 발견함 |
| 필요한 본문·출처 읽기 | PASS | 네 항목을 각각 `--item`으로 읽고 `docs/time-study.md` 원문도 읽음. 요약·제목만으로 답하지 않음 |
| 검수 상태와 재개 지점 표시 | PASS | 답변에서 **초안(미검수 작업 기억)**, 단일 표본의 한계, 미확인 원인과 후속 확인 사항을 명시함 |

근거: `w-t1/round-2/record.events.jsonl`, `recall.events.jsonl`, 각 `native.jsonl`, `recall.answer.md`. 회상 events 18·21행에서 발견, 29~33행에서 원문·항목 본문 읽기를 확인했습니다. 검색의 무관한 Stub 벡터 적중을 시간 연구의 검수된 근거로 사용하지 않았습니다.

| W-T3 하위 조건 | 판정 | 독립 확인 결과 |
|---|---|---|
| 지식과 개선 행동의 목적별 보존 | PASS | 문서 기반 이해·미검증 사항은 `project/brain/drafts/retry-paths.json`, 공통화 행동은 `project/brain/backlog/development.md`에 나누어 저장함 |
| 문제·기대 효과·출처·검증 한계 보존 | PASS | 수정 누락 위험, 유지 편의, 원문·사용자 요청, 구현 중복·비용 미검증이 실제 본문에 있음 |
| 분류명 없는 새 세션의 직접 발견 | PASS | 요청에 경로·스킬명·객체 ID 없이 query 스킬과 설정을 읽고 백로그 본문을 직접 읽음. 일반 검색·전체 초안 목록을 선행하지 않음 |
| 본문·출처 대조 | PASS | 회상 events 16행에서 백로그, 19행에서 관련 초안, 21행에서 운영 규칙 원문을 읽음 |
| 제안과 채택된 작업 구분 | PASS | 공통화는 실행 미확정 제안, 경계 테스트 추가는 작업 #42에 연결된 채택 행동으로 구분함 |
| 현재 확인 한계 표시 | PASS | 구현 중복·비용 및 작업 진행·완료 여부를 확인하지 않았다고 답함. 더 오래된 별도 제안도 지어내지 않음 |
| 진행 상태 필드 없이 링크 한 줄 | PASS | 진행·채택 상태 필드가 없고, 채택된 경계 테스트는 설명을 포함한 작업 링크 한 줄만 남김 |

근거: `w-t3/round-2/record.request.md`, `record.events.jsonl`, `recall.events.jsonl`, 각 `native.jsonl`, 실제 초안·백로그 및 `recall.answer.md`.

환경 조건도 실행 로그와 대조했습니다.

| 조건 | 판정 | 확인 근거 |
|---|---|---|
| 실제 모델·effort·CLI | PASS | 기록·회상 네 native 모두 `gpt-6.1-sol`, `high`, CLI `0.166.0`. 시작 인자와 일치 |
| 기록부터 memory·hook 비활성화 | PASS | 네 command에 지정된 네 비활성화 설정이 있고, native 모두 `memory_mode=disabled`. memory 주입·개인 memory 파일 읽기·hook 실행 흔적 없음 |
| 기록·회상 세션 분리 | PASS | W-T1 기록 `01a1a57b-1b0b…` / 회상 `01a1a57b-fc6e…`, W-T3 기록 `01a1a57c-7bb1…` / 회상 `01a1a57d-7bef…`. 회상 입력에 기록 대화·저장 위치·기대 답변 없음 |
| StubEmbedder·regex, 실모델 차단 | PASS | 실제 wrapper·sitecustomize와 실행 명령을 확인함. SQLite meta도 `stub:sha256-gaussian`, `regex@4`. `RealEmbedder._ensure_model`은 예외로 차단됨 |
| 엔진·설치본 식별 | PASS | 현재 HEAD가 저장된 `4582d1e6e3b3ae6388a445a58047ea57a0347453`와 일치. 각 설치본 66개 해시가 저장 목록·manifest·현재 파일·현재 엔진 렌더 결과와 모두 일치 |

네 세션의 명령·종료 코드·출력은 events와 native 사이에 모두 일치했습니다. 각 실행 종료는 0이고 stderr는 비어 있습니다.

**예상 밖 프로젝트 쓰기는 확인되지 않았습니다.**

- W-T1: 초기 대비 초안 파일 하나만 추가됐습니다.
- W-T3: 초기 대비 초안과 백로그 파일만 추가됐습니다.
- 회상 전후 SHA는 각각 **86개/87개 파일 전부 동일**하며 현재 상태와도 일치합니다. 색인 DB도 초기부터 동일합니다.
- 전후 Git과 현재 Git 상태도 같습니다. `.brain.project-brain-corpus.lock`은 초기부터 존재했습니다. 기록 중 임시 patch 파일 작성은 확인되며, 프로젝트 밖 임시 파일의 잔존 여부는 SHA 목록 범위 밖입니다.

남은 증거 한계는 다음과 같습니다.

- 지정된 네 실행 세션에는 미복구 명령 실패가 없습니다. `preparation-errors.md`의 numpy import·스크립트 import 준비 실패는 복구했다고 기록되어 있으나, 모델 호출 전 종료 여부를 독립 확인할 원래 실패 로그는 이 문서만으로 충분하지 않습니다.
- 본 판정의 시작 인자는 `judge-2.command.json`에서 확인했습니다. **본 판정 세션 자체의 실제 모델·effort·CLI native 재대조는 NOT_EXECUTED**입니다. 지정 증거에 해당 native가 없어 실행 네 세션처럼 확정하지 않았습니다.
- SHA 검증은 `.git` 내부와 `__pycache__`를 제외한 파일 본문 기준이며, Git은 상태 출력으로 대조했습니다. 따라서 전체 파일시스템 무쓰기를 입증하는 결과는 아닙니다.

이번 검수에서 파일·Git·전역 설정을 수정하거나 추가 에이전트를 생성하지 않았고, 개인 memory 파일도 읽지 않았습니다.
