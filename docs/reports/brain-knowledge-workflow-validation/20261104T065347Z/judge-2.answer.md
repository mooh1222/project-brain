> E3 당시 판정·관찰의 보존 사본이다. W-T1의 두 기록 세션은 개인 memory를 읽었으므로
> 이번 memory 비활성 통과 집계에서는 제외하고 재실행 결과로 교체한다.
> 작은 Markdown 산출물만 추적하며 JSONL·프로젝트·해시 원본은 로컬 전용이다.
> 링크는 추적 산출물로만 연결하고 원본 증거는 경로 텍스트로 표시했다.

**2회차의 W-T1~W-T6 성공 조건과 W-T7 설치 조건은 PASS입니다.** 다만 이를 KW-E3 전체 완료로 확대하지 않습니다. 이 판정은 1회차를 검수하지 않았으며, 현재 증거 루트에는 `summary.md`가 없습니다.

13개 실행 세션 모두 실제 native 로그에서 `gpt-6.1-sol`·`high`·CLI `0.166.0`을 확인했습니다. 312개 명령의 내용·출력·종료 코드가 events와 native 사이에 일치했고, 최종 답변도 일치했습니다. 각 프로젝트의 설치 파일 66개는 저장된 해시 및 현재 엔진 템플릿의 설정별 렌더 결과와 일치했습니다. 엔진은 `be75896a18efc076150708882c8af453ee970672`, tracked diff는 없습니다.

| 대상 | 하위 성공 조건 | 판정 | 대조 근거 |
|---|---|---|---|
| W-T1 | 단건 관찰을 기능 외 조사 주제의 초안으로 기록 | PASS | 기록 실행 (로컬 원본: `w-t1/round-2/record.events.jsonl`), 실제 초안 (로컬 원본: `w-t1/round-2/project/brain/drafts/time-boundary-study.json`) |
| W-T1 | 새 세션에서 적절한 초안 발견 | PASS | `draft list` 후 관련 주제 선택. 회상 실행 (로컬 원본: `w-t1/round-2/recall.events.jsonl`) |
| W-T1 | 요약뿐 아니라 필요한 본문·출처·미결 읽기 | PASS | 관찰·가설·질문 4개를 선택 읽고 원문 확인. 회상 실행 (로컬 원본: `w-t1/round-2/recall.events.jsonl`) |
| W-T1 | 초안을 검수된 객체로 단정하지 않음 | PASS | “미검수 작업 기억”, 단일 표본·원인 미확인 표시. [답변](w-t1/round-2/recall.answer.md) |
| W-T2 | 불필요한 초안 없이 기존 ingest로 직접 적재 | PASS | 실제 ingest 및 committed receipt 확인. 재실행 기록 (로컬 원본: `w-t2-recheck/round-2/record.events.jsonl`) |
| W-T2 | Insight를 적재 지식으로 저장 | PASS | reviewed Insight, 기존 두 경로 객체 연결. 실제 객체 (로컬 원본: `w-t2-recheck/round-2/project/brain/objects/insights/insight.retry.entry-path-limit-risk.json`) |
| W-T2 | 새 세션의 관련 검색에서 advisories 회수 | PASS | 검색 `advisories`에 해당 Insight가 반환됨. 회상 실행 (로컬 원본: `w-t2-recheck/round-2/recall.events.jsonl`) |
| W-T2 | 핵심 show로 근거·적용 범위 확인 | PASS | Insight·두 mapping·EvidenceRef·Context 본문 확인. 회상 실행 (로컬 원본: `w-t2-recheck/round-2/recall.events.jsonl`) |
| W-T3 | 이해와 개선 행동을 구분해 보존 | PASS | 초안과 개발 제안 문서로 분리. 기록 실행 (로컬 원본: `w-t3/round-2/record.events.jsonl`) |
| W-T3 | 정확한 분류명 없는 새 요청으로 제안 본문 직접 발견 | PASS | 일반 검색·초안 목록을 선행하지 않고 제안 문서를 읽음. 회상 실행 (로컬 원본: `w-t3/round-2/recall.events.jsonl`) |
| W-T3 | 문제·기대 효과·출처·검증 한계 보존 | PASS | 실제 제안 본문에 모두 존재. 제안 문서 (로컬 원본: `w-t3/round-2/project/brain/backlog/development.md`) |
| W-T3 | 제안과 실행 확정, 현재 확인 한계 구분 | PASS | 공통화는 제안, 테스트는 채택 링크이며 완료 여부는 미확인으로 답함. [답변](w-t3/round-2/recall.answer.md) |
| W-T3 | 진행 상태 필드 미생성 | PASS | 실제 문서에 진행·채택 상태 필드 없음. 제안 문서 (로컬 원본: `w-t3/round-2/project/brain/backlog/development.md`) |
| W-T3 | 채택 작업은 이슈 링크 한 줄로 연결 | PASS | 경계 테스트 작업 #42 링크 한 줄. 제안 문서 (로컬 원본: `w-t3/round-2/project/brain/backlog/development.md`) |
| W-T4 | 근거 부족·미확인 원인을 백로그나 검수된 사실로 변환하지 않음 | PASS | 기록 후 변경은 조사 초안 2개이며, 한계가 본문에 남음. 기록 실행 (로컬 원본: `w-t4/round-2/record.events.jsonl`) |
| W-T4 | 오래된 ‘다섯 번’ 가설과 현재 ‘세 번’ 규칙 구분 | PASS | 사용자 전언·옛 출처 미확보를 표시하고 현재 문서·reviewed mapping과 대조. 정상 실행 (로컬 원본: `w-t4/round-2/healthy.events.jsonl`) |
| W-T4 | 정상 환경에서 실제 회수 | PASS | search 및 mapping·EvidenceRef·Manifest show 성공. 정상 실행 (로컬 원본: `w-t4/round-2/healthy.events.jsonl`) |
| W-T4 | 부분 목록 진단 실제 발동 및 인지 | PASS | `draft_json_invalid`, `partial: true`; 불완전 목록임을 답변에 표시. fault 실행 (로컬 원본: `w-t4/round-2/fault.events.jsonl`), [답변](w-t4/round-2/fault.answer.md) |
| W-T4 | 접근 실패를 정상 부재와 구분 | PASS | healthy는 `No such file`, fault는 `Permission denied`; 제안 부재로 단정하지 않음. 정상 실행 (로컬 원본: `w-t4/round-2/healthy.events.jsonl`), fault 실행 (로컬 원본: `w-t4/round-2/fault.events.jsonl`) |
| W-T4 | 색인 실패 실제 발동 및 보고 | PASS | `sqlite3.DatabaseError: file is not a database`. fault 실행 (로컬 원본: `w-t4/round-2/fault.events.jsonl`) |
| W-T4 | 실패 후 가능한 회수 지속 | PASS | 오류 이후 정상 초안 항목들과 두 원문을 읽어 답함. fault 실행 (로컬 원본: `w-t4/round-2/fault.events.jsonl`) |
| W-T4 | 실패 범위를 확인했다고 주장하거나 자동 복구하지 않음 | PASS | 접근 불가·색인 오류·부분 목록을 표시했고 chmod·설치·rebuild 없음. fault 실행 (로컬 원본: `w-t4/round-2/fault.events.jsonl`), [답변](w-t4/round-2/fault.answer.md) |
| W-T5 | 다른 config root 사용 | PASS | `knowledge/archive` 설정과 실제 읽기·갱신 경로 일치. 기록 실행 (로컬 원본: `w-t5/round-2/record.events.jsonl`), 회상 실행 (로컬 원본: `w-t5/round-2/recall.events.jsonl`) |
| W-T5 | v1 원본 내용·형식 보존 | PASS | 기존 Markdown v1의 내용과 절을 유지하면서 요청된 미결을 추가. 실제 초안 (로컬 원본: `w-t5/round-2/project/knowledge/archive/drafts/clock-legacy.md`) |
| W-T5 | 과거 pending 본문·이력 보존 및 명시적 회수 | PASS | 초기·최종 해시 동일, 실제 본문을 읽고 기존 기록·미검증으로 답함. 회상 실행 (로컬 원본: `w-t5/round-2/recall.events.jsonl`), [답변](w-t5/round-2/recall.answer.md) |
| W-T5 | 정상 신규 기록을 pending으로 우회하지 않음 | PASS | 기록 단계의 본문 변경은 기존 v1 초안뿐. 기록 실행 (로컬 원본: `w-t5/round-2/record.events.jsonl`) |
| W-T5 | 접근 가능한 루트의 backlog 부재를 정상 빈 결과로 처리하고 무생성 | PASS | 루트 접근 확인, 파일 부재 확인, 조회 뒤에도 무생성. 회상 실행 (로컬 원본: `w-t5/round-2/recall.events.jsonl`) |
| W-T6 | 조회 무변경 | PASS | 전후 SHA 목록·Git 동일, 현재 파일 재계산 결과도 일치. 전 (로컬 원본: `w-t6/round-2/before-recall.sha256`), 후 (로컬 원본: `w-t6/round-2/after-recall.sha256`) |
| W-T6 | 적재 성공과 후속 초안 갱신 실패 구분 | PASS | committed receipt 뒤 `draft_stale_sha`; 적재 성공을 별도로 설명. 기록 실행 (로컬 원본: `w-t6/round-2/record.events.jsonl`) |
| W-T6 | 최신 SHA를 읽고 기존 인터페이스로 보완 | PASS | `25ce7e…` 실패 후 `c3107d…`로 갱신 성공, 최종 `a016e0…`. race 기록 (로컬 원본: `w-t6/round-2/race-injected.txt`), 실행 (로컬 원본: `w-t6/round-2/record.events.jsonl`) |
| W-T6 | 동시 writer 질문과 기존 미결 보존 | PASS | `concurrent-question`과 `lag`가 실제 최종 초안에 유지됨. 실제 초안 (로컬 원본: `w-t6/round-2/project/brain/drafts/retry-interval.json`) |
| W-T6 | 실제 적재 객체 참조 연결 | PASS | `formal-interval` 출처와 `mapping.retry.scheduled-interval` 연결. 실제 초안 (로컬 원본: `w-t6/round-2/project/brain/drafts/retry-interval.json`) |
| W-T6 | 무조건 재적재·중복 적재 없음 | PASS | 실제 ingest 명령 1회, 성공 호출 1회, transaction 1개. 실행 (로컬 원본: `w-t6/round-2/record.events.jsonl`), 호출 기록 (로컬 원본: `w-t6/round-2/ingest-calls.txt`) |
| W-T7 | 공통 판단 및 네 진입점의 reference 설치 | PASS | 실제 설치 파일과 8개 상대 참조를 독립적으로 해석해 확인. 참조 기록 (로컬 원본: `w-t7-current/relative-links.json`) |
| W-T7 | 두 번째 깨끗한 설치의 5개 배열 무변경 | PASS | `created/updated/removed/adopted/skipped` 모두 `[]`. report (로컬 원본: `w-t7-current/reports.json`) |
| W-T7 | 사용자 수정 5개 보존·skipped 보고 | PASS | 네 SKILL과 공통 reference가 정확히 skipped 5개이며 현재 해시도 보존값과 일치. report (로컬 원본: `w-t7-current/reports.json`) |
| W-T7 | overlay·기존 pending 보존 | PASS | 전후 및 현재 해시 일치. overlay는 manifest 비관리. report (로컬 원본: `w-t7-current/reports.json`) |
| W-T7 | skipped를 적용 성공으로 오인하지 않음 | PASS | 변경·채택 배열은 비어 있고 skipped 경로를 별도 보고. report (로컬 원본: `w-t7-current/reports.json`), 설치 로그 (로컬 원본: `w-t7-current.log`) |

조회 세션 7개는 각각 전후 SHA 목록과 Git 상태가 같았습니다. 읽을 수 있는 현재 파일도 저장된 최종 SHA와 일치했습니다. 색인 메타데이터는 `stub:sha256-gaussian`·`regex@4`였습니다. `w-t2/round-2` 최초 미완료 시도는 통과 근거에서 제외했습니다. W-T7 pytest 로그는 **59 passed, 16 subtests passed**입니다.

발견된 문제와 판정 한계는 다음과 같습니다.

| 항목 | 판단 |
|---|---|
| W-T1 기록 세션의 전역 메모리 읽기 | 실제로 분류 지침이 담긴 `MEMORY.md`를 읽었습니다. 따라서 **기록 성공을 설치 스킬만의 효과로 귀속하면 과장**입니다. 회상 세션에는 원래 대화가 제공되지 않았고 메모리 읽기도 없습니다. 기록 로그 (로컬 원본: `w-t1/round-2/record.events.jsonl`) |
| W-T4 healthy의 “변경 이력은 미적재” 표현 | 해당 query 출력은 `raw-only`, `needs_clarification: true`입니다. 이것만으로 이력 부재를 입증하지는 못합니다. **“이력을 회수하지 못했다”가 정확한 표현**입니다. 변경 이유를 확정하지 않은 핵심 답변은 유지됩니다. 실행 56행 (로컬 원본: `w-t4/round-2/healthy.events.jsonl`) |
| W-T6 경합 방식 | 실제 stale-SHA는 재현됐습니다. 다만 현재 주입은 같은 프로세스의 hook에서 별도 `update_patch` 호출을 끼워 넣는 방식입니다. **독립 OS 프로세스의 동시 경합 검증은 NOT_EXECUTED**입니다. |
| W-T4 mode 000 파일 | 권한 오류와 권한 유지까지 확인했습니다. 전후 해시 목록은 모두 `PermissionError`이므로 **그 파일 본문의 전후 SHA 동일성 확인은 NOT_EXECUTED**입니다. 무변경 주장을 해당 본문 해시까지 확대하지 않습니다. |
| 실행 중 CLI 오류 | marketplace 자동 갱신 오류가 반복됐습니다. W-T2 finalizer 인자 오류, W-T6 release identity 부재·`/var` symlink 경로 거부도 있었으나 후속 실행으로 복구됐습니다. 현재 증거로 KW-E3 템플릿 결함이라고 단정할 근거는 없습니다. |
| 전체 완료 조건 | **1회차 판정과 `summary.md` 연결은 이 검수에서 NOT_EXECUTED**입니다. 따라서 검수 대상은 통과하지만 KW-E3 전체 2/2 완료 선언은 하지 않습니다. |

이 판정 세션도 native 메타데이터에서 `gpt-6.1-sol`·`high`·CLI `0.166.0`을 확인했습니다. 추가 에이전트·실모델 임베딩·외부 원격 도구를 사용하지 않았으며 파일을 수정하지 않았습니다. 종료 Git 상태는 시작과 동일한 `## mooh1222/brain-kw-e3`, `?? ../../../`입니다.
