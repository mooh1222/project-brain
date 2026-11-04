> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

**1회차 W-T1~W-T6와 W-T7의 기능 조건은 모두 PASS입니다.** 최초 `w-t2/round-1`은 통과 근거에서 제외했습니다. 다만 **KW-E3 전체 통과는 아직 선언할 수 없습니다.** 이번 검수는 1회차만 대상으로 했고, 검수 시점에 프로토콜이 요구하는 `summary.md`도 없었습니다.

| 대상 | 판정 | 범위 |
|---|---|---|
| W-T1~W-T6 1회차 | **PASS** | 아래 하위 조건 모두 확인 |
| W-T4 healthy·fault | **PASS** | 정상 회수와 세 장애 모두 실제 발동 |
| W-T7 | **PASS** | 설치 report·실제 파일·해시·참조 대조 |
| 증거 종합 `summary.md` | **NOT_EXECUTED** | 검수 시점 파일 없음 |
| 스펙 전체 2/2 통과 | **판정 보류** | 2회차는 이번 검수 범위 밖이며, 미실행으로 간주하지 않음 |

Testing Decisions·실행 프로토콜 (로컬 원본: `../../../specs/2026-11-04-brain-knowledge-workflow.md`)과 [환경 기록](environment.md)을 기준으로 판정했습니다.

실행 환경과 증거의 연결도 확인했습니다.

| 확인 항목 | 판정 | 근거 |
|---|---|---|
| 실행 모델·effort·CLI | PASS | 대상 13개 세션의 native 기록이 모두 `gpt-6.1-sol` / `high` / `0.166.0`. 판정 세션도 동일. [관찰 기록](w-t1/round-1/observations.md) · 판정 세션 메타데이터 (로컬 원본: `/Users/al03040455/.codex/sessions/2026/11/04/rollout-2026-11-04T16-12-45-01a1a567-3144-7500-ba7e-c4cacdb88d6c.jsonl`) |
| 기록·회상 세션 분리 | PASS | 서로 다른 thread ID. native 사용자 요청은 저장된 request와 일치하며, 회상 요청에 저장 경로·객체 ID·강제 스킬 호출·원래 대화가 추가되지 않음. 실행 방식 (로컬 원본: `run-session.sh`) · 각 사례의 native 링크 |
| 엔진·설치 스킬 일치 | PASS | HEAD `be75896a18efc076150708882c8af453ee970672`, tracked diff 없음. 각 프로젝트의 설치 파일 66개가 기록된 해시 및 현 checkout 템플릿 렌더 결과와 일치. 엔진 상태 (로컬 원본: `engine-status.txt`) · 설치 해시 예시 (로컬 원본: `w-t1/round-1/installed-skills.sha256.json`) |
| 결정론 검색 | PASS | wrapper의 StubEmbedder·regex 주입과 실제 최종화 출력의 `stub:sha256-gaussian`, `regex` 확인. 실제 출력 (로컬 원본: `w-t2-recheck/round-1/record.events.jsonl`) |
| 요청·실행·답변 연결 | PASS | 13개 세션의 request·thread ID·최종 answer를 events/native와 대조. 회상에서 사용한 핵심 본문·명령 출력도 native에 확인됨. [사례별 관찰](w-t6/round-1/observations.md) |

하위 성공 조건별 판정은 다음과 같습니다.

| 사례 | 하위 성공 조건 | 판정 | 교차 확인한 근거 |
|---|---|---|---|
| W-T1 | 이해·가설·미결을 구분해 기록 | PASS | 관찰 1건, 네트워크 지연 가설, 추가 표본·동기화 질문을 별도 항목으로 저장. 실제 초안 (로컬 원본: `w-t1/round-1/project/brain/drafts/time-boundary-study.json`) |
| W-T1 | 새 세션이 적절한 초안을 발견 | PASS | `draft list` → 관련 topic 선택 → `draft show`. 요청에는 topic ID가 없음. 회상 로그 (로컬 원본: `w-t1/round-1/recall.events.jsonl`) |
| W-T1 | 필요한 본문·출처·미결을 읽고 재개 | PASS | 항목별 본문과 `docs/time-study.md`를 읽고 추가 표본·동기화 확인을 재개 지점으로 제시. 회상 로그 (로컬 원본: `w-t1/round-1/recall.events.jsonl`) · [답변](w-t1/round-1/recall.answer.md) |
| W-T1 | 단건 허용 | PASS | 관찰 하나로 초안을 만들었으며 크기 문턱을 요구하지 않음. [기록 관찰](w-t1/round-1/observations.md) |
| W-T1 | 기능 외 조사 주제 허용 | PASS | 시간 경계 연구를 독립 조사 주제로 저장. 실제 초안 (로컬 원본: `w-t1/round-1/project/brain/drafts/time-boundary-study.json`) |
| W-T1 | 초안을 검수된 객체로 단정하지 않음 | PASS | 답변에 ‘미검수 작업 기억’, 단일 표본·원인 미확인 표시. [답변](w-t1/round-1/recall.answer.md) |
| W-T2 | 불필요한 초안 없이 기존 ingest 사용 | PASS | 실제 `ingest --objects-file` 실행. 기록 전후 증가분에 draft·pending 없음. 기록 로그 (로컬 원본: `w-t2-recheck/round-1/record.events.jsonl`) |
| W-T2 | Insight를 적재 지식으로 저장 | PASS | committed receipt와 실제 `kind=Insight`, `status=reviewed` 객체 확인. 로그 (로컬 원본: `w-t2-recheck/round-1/record.events.jsonl`) · 객체 (로컬 원본: `w-t2-recheck/round-1/project/brain/objects/insights/insight.retry.entry-limit-change-risk.json`) |
| W-T2 | 새 세션의 관련 advisories에서 회수 | PASS | 검색 결과의 `advisories`에 해당 Insight가 나오고 이어서 `show` 실행. 회상 로그 (로컬 원본: `w-t2-recheck/round-1/recall.events.jsonl`) |
| W-T2 | 근거·적용 범위와 함께 설명 | PASS | 두 source mapping, EvidenceRef·원문을 확인하고 합성 문서 규칙 범위와 코드·장치 미검증을 명시. 객체 (로컬 원본: `w-t2-recheck/round-1/project/brain/objects/insights/insight.retry.entry-limit-change-risk.json`) · [답변](w-t2-recheck/round-1/recall.answer.md) |
| W-T3 | 지식과 개선 행동을 목적별로 보존 | PASS | 이해·미결은 draft, 공통화 행동은 개발 제안 문서에 저장하고 연결. native의 실제 `apply_patch`도 확인. [기록 관찰](w-t3/round-1/observations.md) · 제안 본문 (로컬 원본: `w-t3/round-1/project/brain/backlog/development.md`) |
| W-T3 | 정확한 분류명 없는 새 요청으로 회상 | PASS | “공통화하자던 거” 요청에서 query 스킬과 직접 읽기 분기 선택. 회상 로그 (로컬 원본: `w-t3/round-1/recall.events.jsonl`) |
| W-T3 | 개선 제안의 실제 본문·출처 읽기 | PASS | 제안 문서를 `nl -ba`로 읽고 규칙 원문도 확인. 일반 search·전체 draft 목록을 선행하지 않음. 회상 로그 (로컬 원본: `w-t3/round-1/recall.events.jsonl`) |
| W-T3 | 제안·확정 여부·현재 확인 한계 구분 | PASS | 공통화는 실행 미확정, 경계 테스트는 연결된 채택 기록, 이슈 현재 진행·완료는 미확인으로 답함. [답변](w-t3/round-1/recall.answer.md) |
| W-T3 | 진행 상태 필드 미생성 | PASS | 실제 문서에 미착수·진행 중·완료 등의 상태 필드 없음. 본문 (로컬 원본: `w-t3/round-1/project/brain/backlog/development.md`) |
| W-T3 | 채택 항목은 작업 링크 한 줄로 연결 | PASS | 경계 테스트 행동은 이슈 #42 링크 한 줄이며 진행은 링크 대상이 소유. 본문 (로컬 원본: `w-t3/round-1/project/brain/backlog/development.md`) |
| W-T4 | 근거 부족을 백로그·검수 사실로 바꾸지 않음 | PASS | 기록 세션은 미검수 초안만 생성. 단일 표본·과거 출처 미확보를 한계로 저장. [기록 관찰](w-t4/round-1/observations.md) |
| W-T4 | 현재 규칙과 오래된 가설 구분 | PASS | 과거 ‘5회’는 출처 없는 사용자 진술·가설, 현재 ‘3회’는 reviewed mapping과 원문으로 구분. healthy 로그 (로컬 원본: `w-t4/round-1/healthy.events.jsonl`) · [답변](w-t4/round-1/healthy.answer.md) |
| W-T4 | 최신 시각만으로 우선순위를 결정하지 않음 | PASS | 더 최근 초안의 5회 가설을 현재 사실로 채택하지 않고, 실제 5→3 변경 이력도 단정하지 않음. [답변](w-t4/round-1/healthy.answer.md) |
| W-T4 | healthy에서 정상 회수 | PASS | 정상 목록, 검색, 핵심 객체 `show`, 초안 항목·원문 읽기 성공. healthy 로그 (로컬 원본: `w-t4/round-1/healthy.events.jsonl`) |
| W-T4 | 정상 부재와 실패 구분 | PASS | healthy에서는 접근 가능한 `brain` 아래 backlog 부재를 확인하고 해당 위치의 빈 결과로 답함. healthy 로그 (로컬 원본: `w-t4/round-1/healthy.events.jsonl`) |
| W-T4 | partial diagnostics 실제 발동·보고 | PASS | `draft_json_invalid`, `partial=true`가 출력됐고 답변에 목록 불완전을 명시. fault 로그 (로컬 원본: `w-t4/round-1/fault.events.jsonl`) |
| W-T4 | 접근 실패 실제 발동·보고 | PASS | mode `000` 문서에서 실제 `Permission denied`. ‘제안 없음’으로 바꾸지 않음. fault 로그 (로컬 원본: `w-t4/round-1/fault.events.jsonl`) · [답변](w-t4/round-1/fault.answer.md) |
| W-T4 | 색인 실패 실제 발동·보고 | PASS | 검색이 `sqlite3.DatabaseError: file is not a database`로 실패. fault 로그 (로컬 원본: `w-t4/round-1/fault.events.jsonl`) |
| W-T4 | 가능한 결과를 계속 회수하고 불확실성 유지 | PASS | 정상 초안과 mapping·근거 객체를 직접 읽어 답변. rebuild·권한 변경 없이 실패 범위를 명시. fault 로그 (로컬 원본: `w-t4/round-1/fault.events.jsonl`) · [답변](w-t4/round-1/fault.answer.md) |
| W-T5 | 다른 config root 사용 | PASS | `brain_root=knowledge/archive`를 읽고 해당 루트로 조회·갱신. 기본 `brain/`은 생성되지 않음. 회상 로그 (로컬 원본: `w-t5/round-1/recall.events.jsonl`) · [관찰](w-t5/round-1/observations.md) |
| W-T5 | v1 원본 내용·형식 보존 | PASS | Git 기준 원본과 실제 갱신본 대조. v1 marker·Topic ID·제목·기존 본문을 유지하고 날짜와 요청된 내용을 갱신. JSON 변환 없음. 실제 v1 (로컬 원본: `w-t5/round-1/project/knowledge/archive/drafts/clock-legacy.md`) · [갱신 로그](w-t5/round-1/observations.md) |
| W-T5 | 과거 pending·이력 보존 및 명시적 조회 | PASS | pending SHA가 전후 `494232dc…bd918`로 동일. 실제 본문을 읽고 2025년 기존 미검증 관찰로 답함. 회상 로그 (로컬 원본: `w-t5/round-1/recall.events.jsonl`) · [답변](w-t5/round-1/recall.answer.md) |
| W-T5 | 신규 기록을 pending으로 우회하지 않음 | PASS | 기존 v1 초안만 갱신. pending 및 다른 corpus 파일 변경 없음. [관찰](w-t5/round-1/observations.md) |
| W-T5 | backlog 부재를 정상 빈 결과로 처리·무생성 | PASS | 접근 가능한 루트 확인 후 `No such file or directory`를 구분해 답하고 파일을 만들지 않음. 회상 로그 (로컬 원본: `w-t5/round-1/recall.events.jsonl`) |
| W-T6 | 조회 무변경 | PASS | 전체 7개 조회 세션의 전후 SHA 목록·Git 상태 동일. 현재 파일도 저장된 조회 후 상태와 일치. [사례별 상태 링크](w-t6/round-1/observations.md) |
| W-T6 | 적재 성공과 초안 정리 실패 구분 | PASS | committed ingest·최종화 성공 뒤 초안 갱신만 실패. 진행 메시지에서도 두 효과를 구분. 기록 로그 (로컬 원본: `w-t6/round-1/record.events.jsonl`) |
| W-T6 | stale-SHA 충돌 실제 발동 | PASS | 주입 기록의 이전 SHA `f3255666…9772bc`로 갱신했다가 `draft_stale_sha`, `actual_sha=ee9db886…c8e6b` 출력. 주입 기록 (로컬 원본: `w-t6/round-1/race-injected.txt`) · 실제 오류 (로컬 원본: `w-t6/round-1/record.events.jsonl`) |
| W-T6 | 최신 SHA로 기존 인터페이스를 통해 보완 | PASS | 최신 초안·항목을 다시 읽고 `ee9db886…c8e6b`로 재갱신 성공. 최종 SHA `edd620e0…7e9c`. 기록 로그 (로컬 원본: `w-t6/round-1/record.events.jsonl`) |
| W-T6 | 동시 writer 질문·남은 미결·적재 참조 보존 | PASS | `concurrent-question`을 그대로 보존하고 `lag` 질문 및 실제 mapping 참조를 연결. 새 회상에서도 세 내용을 구분. 최종 초안 (로컬 원본: `w-t6/round-1/project/brain/drafts/retry-interval.json`) · 회상 로그 (로컬 원본: `w-t6/round-1/recall.events.jsonl`) |
| W-T6 | 무조건 재적재·중복 적재 없음 | PASS | `ingest-calls.txt` 1행, 실제 ingest 명령 1회, transaction 1개. 객체 사본 증가는 없음. 호출 기록 (로컬 원본: `w-t6/round-1/ingest-calls.txt`) · 기록 로그 (로컬 원본: `w-t6/round-1/record.events.jsonl`) |
| W-T7 | 공통 판단 및 네 진입점 참조 설치 | PASS | 실제 설치 파일과 참조 대상 대조. 상대 참조 8개가 존재하는 파일로 해석됨. 참조 결과 (로컬 원본: `w-t7-current/relative-links.json`) |
| W-T7 | 두 번째 깨끗한 설치의 5개 배열 모두 빈 배열 | PASS | `created/updated/removed/adopted/skipped=[]` 각각 확인. report (로컬 원본: `w-t7-current/reports.json`) |
| W-T7 | 사용자 수정 파일 5개 보존·skipped 보고 | PASS | 네 SKILL과 공통 reference가 정확히 skipped. report 전후 해시 및 현재 실제 파일 해시 일치. report (로컬 원본: `w-t7-current/reports.json`) |
| W-T7 | overlay·과거 pending 보존 | PASS | 두 파일의 전후·현재 해시 일치. overlay는 manifest 비관리이며 backlog도 생성되지 않음. report (로컬 원본: `w-t7-current/reports.json`) |
| W-T7 | skipped를 적용 성공으로 오인하지 않음 | PASS | report는 수정본을 `updated`가 아닌 `skipped`로 보고. 설치 기능 검증과 자연어 동작 검증을 구분. report (로컬 원본: `w-t7-current/reports.json`) · 설치 로그 (로컬 원본: `w-t7-current.log`) |

발견된 문제와 판정 한계는 다음과 같습니다.

- **환경 격리 한계:** W-T1 기록 세션은 전역 `MEMORY.md`의 관련 분류 지침을 실제로 읽었습니다. 회상 세션에는 이 읽기가 없고 원래 대화도 전달되지 않았으므로 회상 조건은 충족합니다. 다만 W-T1 기록 결과를 설치 스킬만의 효과로 귀속할 수는 없습니다. [기록 관찰](w-t1/round-1/observations.md)
- **CLI 환경 오류:** 13개 세션 모두 `bb2-agent-env` marketplace 자동 갱신 오류가 있었습니다. 과제 명령으로 외부 원격 서비스를 호출한 흔적은 없지만, CLI의 자동 갱신 시도까지 없었다고 주장할 수는 없습니다. 템플릿 결함으로 볼 근거는 없습니다. 원시 로그 예시 (로컬 원본: `w-t1/round-1/recall.events.jsonl`)
- **복구된 실행 오류:** W-T4의 지원하지 않는 `query --stub-embedder`, 반복 `--item` 사용, W-T6의 `/var` 출력 경로 실패 등이 있었습니다. 필요한 본문 재조회와 `/private/var` 경로 재시도로 복구됐습니다. 최종 성공 판단에 실패한 명령을 성공으로 계산하지 않았습니다. [W-T4](w-t4/round-1/observations.md) · [W-T6](w-t6/round-1/observations.md)
- **무변경 증명의 범위:** W-T4 mode `000` 파일은 전후 해시 목록 모두 `PermissionError`입니다. 사전 SHA·실제 접근 실패·권한 유지·쓰기 명령 부재는 확인했지만, 그 파일 본문의 전후 동일성을 직접 재해시하지는 못했습니다. `.git` 내부와 `__pycache__`도 파일 해시 대상에서 제외됩니다. [장애 조건](w-t4/round-1/fault-conditions.md)
- **충돌 검증의 범위:** W-T6는 호출 경계에 주입한 별도 SHA 갱신으로 실제 충돌을 만든 결정론 검증입니다. 독립 프로세스들의 병렬 실행 스트레스 검증으로 확대 해석할 수 없습니다. 실제 주입 코드 (로컬 원본: `w-t6/round-1/project/tools/sitecustomize.py`)
- **기록 정확성:** `engine-status.txt`에는 이미 `?? .scratch/`가 있습니다. 따라서 스냅샷 시점의 저장소 전체를 clean이라고 표현하면 부정확합니다. tracked diff는 비어 있습니다. 상태 기록 (로컬 원본: `engine-status.txt`)
- **과도한 최종 주장:** 가설을 검수 사실로 바꾸거나, 과거 제안을 현재 미해결로 단정하거나, 합성 규칙을 실제 코드 검증으로 확대하는 중대한 주장은 발견하지 못했습니다. W-T7의 `59 passed, 16 subtests passed`는 설치 관련 회귀 결과이며 의미 동작 검증을 대체하지 않습니다. pytest 로그 (로컬 원본: `w-t7-pytest.log`)

조회 중 예상 밖 쓰기는 관찰되지 않았습니다. 기록 단계의 초안·제안·적재 객체 및 색인·journal 생성은 요청된 작업에 해당하며, W-T4 손상 파일·권한·색인 변경은 검증 담당자의 장애 주입으로 구분됩니다. 이번 판정 세션도 파일을 수정하지 않았고 시작·종료 Git 상태가 같습니다.
