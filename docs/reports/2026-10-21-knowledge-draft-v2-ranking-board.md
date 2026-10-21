# 지식 초안 v2 — 랭킹보드 실사용 검증

실행 이슈: [#112](https://github.com/mooh1222/project-brain/issues/112), 상위 스펙
[#108](https://github.com/mooh1222/project-brain/issues/108).

실제로 작업하며 사용한 랭킹보드 초안을 v2로 전환하고, 별도 문맥의 선택 재개·갱신과 원문
독립 대조를 거쳐 **랭킹보드 사실 21개를 실제 적재했다.** canonical receipt의 예정/검증 객체
145개가 일치하고, semantic finalization의 색인 재구축·평가·회상도 모두 통과했다.
샐리 카누 재현이나 prepare만으로 이 결과를 대신하지 않는다.

## 실제 대상과 승인된 기준

사용자는 2026-10-21 “이미 다 작업된 샐리의 카누를 왜해”, “랭킹보드 -> 초안 -> 실적재를
해봐야하는거 잖아”라고 검증 대상을 정했다. 다음 두 가지를 실제 후보와 함께 확인했다.

- 미커밋 v1 원문을 엔진 `.snapshots/2026-10-21/112-ranking-board/`에 보존하고 v2로
  전환: “이 위치로 보존하고 v2 전환” 승인.
- 미머지 기능 브랜치 기준 실적재: “1번으로 해줘 아직 pr머지전이야.” 승인.
  이번 검증의 범위 예외이며 설치 스킬의 일반 develop 앵커 규칙을 고치지 않았다.

엔진은 `28d95ab8e1f18d899ab7696074e95deff1d503dd`, 데이터 checkout은
`docs/bb2-brain-object-model`의 `86f4ca5e8d349750aa1250b4d65444f73247d04c`다.
실제 코드 checkout은 `feature/5.7/ranking-board`의
`e9f9d0e89b38ffa8ca2e845f2b9c836e4e88a049`이며 그곳의 brain은 위 데이터 checkout을 가리킨다.
원격 `git ls-remote`도 이 기능 브랜치 SHA와
`develop=f3e5578509be55ffd8208592ea86929b90621693`을 반환했다.
현재 구현은 develop의 조상이 아니며 develop tree에 RankingBoard 디렉터리가 없다.
검증된 코드 사실과 develop 머지·기기 QA 완료를 구분한다.

실제 실행 단위는 단일 컨텍스트·하나의 원자적 coverage 묶음이므로
Source Intake: `route=single`, `history_coverage=unsearched`로 정정한다. 초기 탐색에서 여러 검증 항목을 batch로
불렀으나 여러 적재 항목을 나눈 배치 실행을 하지는 않았다. 대상은 주간 랭킹을 제외한
5.7 랭킹보드다. 실제 기획서 r2의 목차/관련 절과 구현 코드를 대조했고, 서버 최신 계약과 과거
사용자 결정은 원문 확인 없이 적재하지 않았다. Concept Intake: `none(어휘 변경 없음)`.

## 원문 보존과 실제 v2 사용

기존 `brain/drafts/ranking-board-5-7.md`는 미커밋 포함 603줄, 96,920 bytes다.
SHA256은 `56da37d788fa9b496f42a48163fab9cca34dc47a700c009119f25b482fd35372`다.

승인된 위치에 같은 bytes의 `ranking-board-5-7.v1.56da37d788fa.md`를 보존하고, 교체 직전
source SHA를 다시 확인했다. 공통 draft writer lock 안에서 JSON을 설치하고 활성 Markdown을
제거했다. 단일 활성 파일은 데이터 checkout의 `brain/drafts/ranking-board-5-7.json`이다.
32개 보존 항목의 본문을 순서대로 합치면 원문 전체와 완전히 같다. v1 출처 목록·결정·가설·미결을
지우거나 현재 검수 사실로 승격하지 않았고, 보존본은 정식 raw 근거로 등록하지 않았다.

독립 `gpt-6.1-sol / high` 문맥에 topic ID를 주지 않았다. 먼저 실제 코드의 public 메서드·enum·
요청/표시 경계 인벤토리를 만들고, 공개 `draft list`로 랭킹보드 topic을 발견한 뒤 기본 show와
필요한 기존 5개 항목만 읽었다. 코드 원문을 대조해 새 finding 12개와 실제 관찰 source 41개를
expected-SHA patch로 기록하고 일부 표현을 다시 정밀화했다. 전체 show나 초안 파일 전체
직접 읽기로 재개를 대체하지 않았다. 이때 확인한 기존 5개 본문은 변경되지 않았다.

후속 독립 검수와 코드 보완으로 최종 초안은 **기존 32개 + 코드 사실 21개 + 미결 1개 = 54개**다.
대상/전체 draft lint가 통과했다. 각 코드 관찰은 실제 checkout·full SHA·dirty=false·quote present를
엔진이 기록했다. `b2_ranking_board_world_list_frame.png`는 항목 안에만 있고 목록 metadata에는
없음을 실제 공개 CLI로 확인했다. topic 단위 발견이 내부 식별자만으로의 회수를 보장하지는 않는다.

## 원문 독립 검수와 적재 범위

네 탭의 초기 복원·선요청·선택/표시 분리·재시도, FRIEND 선갱신/복귀, CLUB HOME과 후속 요청·
하위 탭·시즌 만료, SPECIAL 네 상태/요청 gate, 팝업 재사용·새 dispatch 보호, WORLD 응답/목록/
내 배너, CLUB 보상 선택, SPECIAL 포스터 대체, 뱃지 확인 상태와 FRIEND 로컬 프로필 보강을
21개 mapping으로 정했다. 주간 랭킹과 UI 좌표·실기·배포·서버 운영/과거 결정은 이 적재에서 제외했다.

별도 `gpt-6.1-sol / high` 검수자가 각각 core와 보완 원문을 함수 전체·호출처로 반박했다.
핵심 교정은 다음과 같다.

- CLUB은 HOME 뒤 SEASON·MY_CLUB을 각각 발신한다. 두 응답을 직렬로 기다리지 않으며
  로컬 gate·멤버 상태·실패 경로에 따라 요청 수가 달라진다.
- 요청 selectedTab과 표시 shownTab을 구분한다. 실패 상태 도달이 전용 오류 화면 존재를 뜻하지 않는다.
- WORLD의 1~1000등은 고정 배너 자격이다. 서버가 1000명을 제공한다는 보장이 아니다.
  실제 판정은 처음 ID가 일치한 행의 `cellAtIndex` 존재이며 기하학적 완전 가시성 판정이 아니다.
- CLUB 보상은 첫 grade 일치를 반환한다. 중복 grade까지 순서 독립성을 보장하지 않는다.
- cleanup은 새 dispatch 입구를 막는다. 모든 늦은 netcb 부수효과·추가 API를 취소하지 않는다.

core 12개 중 11 pass/1 fixed 해결과 추가 2개 확인, 보완 7개 중 3 pass/4 fixed 해결을 반영했다.
61개 코드 anchor의 bytes/심볼 관계도 검사했다. 타입 이름과 멤버 인용이 어긋났던 2개는
실제 namespace/field 심볼과 그 선언 인용으로 정밀화했다. 원문 의미 검증과 AST/quote 검증을
구분했으며 엔진 코드·설치 템플릿은 바꾸지 않았다.

코드 탐색 실행 파일 `scripts/codesearch/bb2code`가 없어 `rg`와 직접 source 양끝 읽기로
대체했다. 관련 심볼/실행 query/호출 경계/누락/불확실성을 검수 JSON에 기록했다.
CDB refresh와 게임 빌드는 하지 않았다. 어휘는 개념 선언이 없어 candidate로도 만들지 않았다.
`pending_concepts`: 랭킹보드와 네 탭의 이름/뜻은 기획서 및 코드에 있으나, 이번에는 코드 동작
mapping만 적재했다. 기존 초안의 어휘 관찰은 그대로 남아 있다.

## prepare·실제 쓰기·보존 결과

prepare는 확정 finding 21개와 question 1개를 선택했다. `partial=true`, diagnostics는 빈 배열,
미결은 `pending-runtime-and-source-confirmation` 한 개다. 준비 전후 10,699개 기존
파일의 hash가 같았다. 일부 미결을 성공한 정식 사실로 취급하지 않았다.

기존 `assemble_notes.py` → coverage-bound `build` → `MutationService.preview` → 공개 ingest를
사용했다. 최종 plan과 쓰기는 모두 신규 객체만 대상으로 했고 기존 reviewed 객체는 고치지 않았다.

| 종류 | 신규 개수 |
|---|---:|
| DomainContext | 1 |
| DomainMapping | 21 |
| CodeLocator | 61 |
| EvidenceRef | 61 |
| EvidenceManifest | 1 |
| 합계 | 145 |

canonical receipt의 `outcome=committed`, `committed=true`, `expected_objects=verified_objects=145`다.
transaction ID는 `b7b798d050769c2d82243abce7ed13c824d5486f5bda12039c77239cae6f5a06`,
coverage SHA256은 `f9cfdd71d82b08874b5c7868694febebd408e85adc11ec86d4590a6e577c4c88`다.
원래 객체·raw·다른 초안·양쪽 checkout의 기존 게임/프로젝트 WIP는 hash 대조에서 변경이 없었다.
현재 store fingerprint도 receipt의 after fingerprint와 일치했다.

## 최종 검증

`finalization-result.json`은 `ok=true`, `errors=[]`다. 실제 실행 결과는 다음과 같다.

| 검사 | 결과 |
|---|---|
| 실모델 색인 rebuild | 1회 성공, 8,242행/벡터, raw 2,753청크, 약 291.4초 |
| 임베딩 | BAAI/bge-m3, vectors_computed=8,242, no_previous_index |
| lint·audit | 모두 성공 |
| 기존 eval | 18/18 통과, 실패 0 |
| 실코퍼스 checks | 16건 중 15 통과·1 skip, 실패 0 |
| 랭킹보드 회상 | 21/21, missing_object_ids/missing_code_locator_object_ids 모두 빈 배열 |
| 고립 객체 | 기존 14개 그대로, 새 고립 0 |
| 미머지 코드 앵커 | 기존 40 + 예상 신규 61 = 101, 예상 밖/누락 0 |
| 감사 기준 develop HEAD | 시작과 끝 모두 f3e5578509be55ffd8208592ea86929b90621693 |
| 엔진 문서 표적 검사 | tests/test_architecture_docs.py 16 passed |

공개 show로 저장된 CLUB 분기 mapping의 본문과 이웃도 확인했다(`sample-club-show.json`).
초안은 삭제하지 않고 재개 요약에 위 실제 완료와 남은 미결을 기록했다.

## 비용·효용의 실측 한계

| 관찰 | UTF-8 stdout bytes |
|---|---:|
| 같은 보존 원문을 공개 v1 show로 읽는 프로토콜 기준 | 99,833 |
| 별도 문맥의 첫 v2 기본 show | 11,258 |
| 그 문맥의 기존 5개 선택 show 합계 | 28,314 |
| 그 문맥의 확인/재조회 포함 전체 25회 draft show 합계 | 182,249 |
| 그 문맥에 기록된 모든 명령 stdout 합계 | 410,399 |

첫 선택 읽기는 작았지만 실제 확인·재조회 누계는 단일 v1 전체 응답보다 컸다. 같은 작업량의
독립 v1 모델 대조군은 아니므로 비용 악화 비율도 계산하지 않는다. 나머지 문맥·원문 조사·전환·
검증 스크립트 재시도·적재의 모델 입출력과 원래 v1 작성 비용은 미측정이다. 응답 metadata만 남긴
대조도 오프라인 프로토콜일 뿐 모델 총비용 실험으로 보지 않는다. 총 토큰/비용 절감과 품질 우위는
입증하지 않았다. 확인한 효용은 실제 초안의 선택 재개·갱신과 원문 기반 실적재 연결이다.

## 범위 검수와 근거 산출물

- 완료산출물: 실제 랭킹보드 초안의 v2 사용 → 기존 적재·최종화·회상 증거.
- 첫 사용 가능 결과: 원문 보존과 단일 활성 v2 전환. 샐리 성공이나 prepare로 완료를 대체하면 계약 위반이다.
- 소유: 원문 보존·v2 선택 재개/갱신·원문 독립 대조·실제 적재/영수증·최종화/회상.
- 추가 의무 연결: bytes 대조는 데이터 손실 방지, 원문 대조는 기억의 오승격 방지, receipt와 최종화는 실제 완료 확인에 직접 필요하다.
- 제외: 게임 코드 수정·빌드/실기 수행·머지·일반 변환기·새 migration 명령·팀 공유/release·새 계측 체계.
- 허용 불완전성: 미결은 초안에 유지, 미측정 비용 명시, 필요한 사람 판단은 실제 후보로 확인.
- 계약 공백: 원문 보존 위치와 미머지 코드 기준을 실제 질문으로 제시했고 두 가지 모두 사용자 승인으로 닫았다.

이 제외 목록과 허용 불완전성은 후속 설계·검수 기준이며 재포함에는 현재 요청과의 연결 근거가 필요하다.

독립 최종 Standards 검수 지적은 0건이다. Spec 검수가 찾은 낡은 티켓 checkpoint 문구를
실제 저장·최종화 결과로 고쳤고 재검수의 미해결 지적도 0건이다.

로컬 검증 산출물은 엔진 `.snapshots/2026-10-21/112-ranking-board/`의 `conversion-check.json`,
`resume-observation.json`, `verified-ranking-core.json`, `core-verification.json`,
`supplemental-verification.json`, `materials/materials.json`, `prepare-invariance.json`,
`verify.json`, `domain_spec.py`, `coverage.json`, `objects.json`, `build-report.json`,
`preflight.json`, `ingest-result.json`, `finalization-*.json`, `preservation-result.json`,
`io-observation.json`, `discovery-negative-case.json`이다. 보존본과 초안 발췌는 정식 raw 근거가 아니다.

## Git 보존 경계

신규 corpus 객체 145개만 BB2 `93857c73f8e698bd773e3f826c32bf2991208efe`에 로컬 커밋했다.
원격에는 push하지 않았다. 기존 미커밋 랭킹보드 초안과 겹치는 Markdown→JSON 전환은 자동
stage/commit에서 제외했다. 승인한 원본 사본과 활성 JSON은 모두 로컬에 보존되며 다른 WIP도
그대로다. 엔진 변경은 이 결과 문서·ROADMAP·샐리 관찰의 범위 정정뿐이다.
