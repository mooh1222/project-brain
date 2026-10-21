# 지식 초안 v2 BB2 파일럿 — 적재 문장 확인 대기

> 2026-10-21 범위 정정: 아래는 샐리 카누에서의 사전 기능 관찰 기록이다. #112의 실제 검증
> 대상은 작업하며 사용한 랭킹보드 초안으로 고정했다. 이 재현이나 샐리 mapping 정정 승인을
> 랭킹보드 실사용 검증의 성공 또는 진행 조건으로 삼지 않는다.
> 현재 상태는 [랭킹보드 checkpoint](2026-10-21-knowledge-draft-v2-ranking-board.md)를 따른다.

실행 이슈: [#112](https://github.com/mooh1222/project-brain/issues/112), 상위 스펙
[#108](https://github.com/mooh1222/project-brain/issues/108).

설치·신규 기록·별도 문맥의 발견/재개·읽기 전용 prepare는 확인했다. 실제 적재와 semantic
finalization은 아직 실행하지 않았다. 기존 reviewed mapping의 부정확한 범위 설명을 발견했고,
소비 프로젝트 규칙에 따른 사용자 문장 확인을 기다린다. 총 모델 토큰과 비용 효용은 미측정이다.

## 범위와 시작 상태

- 엔진: main `88171dc6b25954abf4570330bf451a8eb5a28b59`.
- BB2: `docs/bb2-brain-object-model`, 시작 HEAD `84e5efe3bbfd319f9e6f6d0ff09f77c30d86d46d`,
  원격 대비 ahead 37. 이 브랜치 전체를 push하지 않는다.
  설치 파일과 신규 draft만 로컬 checkpoint `86f4ca5e8d`로 commit했고 원격에는 push하지 않았다.
- Source Intake: `route=single`, `history_coverage=unsearched`,
  `Concept Intake: none(어휘 변경 없음)`.
- 실행 전에 신규 topic `sally-canoe-howto-v2-pilot`과 버튼 생성 순서·성공 조건·클릭 delegate
  위임 범위를 선언했다. 기존 dirty v1 랭킹 초안은 변환하지 않았다.
- 목표 develop: `f3e5578509be55ffd8208592ea86929b90621693`. 선택 코드 파일은 실제 작업
  checkout과 목표 revision의 bytes가 같다. 현재 관찰 HEAD를 과거 기준점으로 대신 쓰지 않았다.
- 시작 색인 fingerprint는 현재 corpus와 이미 달랐다. 초안 발견은 성공했고 정식 search는
  stale 오류로 실패했다. 이를 정식 객체 부재로 해석하지 않는다.

## 확인한 기능

1. 기존 config·manifest·스킬 복사본의 preview 뒤 live 설치를 실행했다. 신규 4개·갱신 13개,
   removed/adopted/skipped 0개였다. 두 번째 설치의 다섯 변경 배열은 모두 비어 있다.
2. 설치된 `engine_python.py`가 명시한 엔진 venv를 선택하고 실제로 해당 checkout의
   `project_brain`을 import함을 확인했다. 시스템 Python으로 시작한 finalizer의 config 검증도
   성공했다. 공유 스킬에 개인 절대경로를 넣지 않았다.
3. 신규 v2에 finding 4개와 question 1개, 원문 code source 3개를 기록했다. 기존
   drafts/objects/raw/.brain-local 파일 10,696개의 hash가 그대로였고 신규 draft만 추가됐다.
4. 별도 문맥의 `gpt-6.1-sol / high` 검수 세션에 topic ID를 주지 않았다. query/discovery
   스킬을 읽고 `draft list`로 5개 topic 중 새 topic을 발견했다. 본문을 읽기 전에 develop
   원문의 독립 inventory를 만든 뒤 요약과 각 항목을 선택 조회했다.
5. 독립 대조에서 생성 순서·버튼/라벨/delegate guard의 모순은 없었다. init의 상위 초기화
   실패·레이어 geometry는 질문 핵심 밖이며 UI 좌표/이미지는 객체화 범위에서 제외했다.
   `makeCloseButton`은 서술에서 생략됐지만 보존 source quote에 있다. 실제 팝업 런타임은 미결이다.
6. metadata에는 없고 항목에만 있는 이미지 식별자를 음성 사례로 확인했다. topic 단위
   발견은 이 문자열만 받은 질문의 회수를 보장하지 않는다.
7. prepare는 code quote 존재·hash·관찰/목표 revision과 선택 key를 보존했다. question은
   `unresolved_items`로 분리되어 `partial=true`, 원문 diagnostics는 빈 배열이었다.
   준비 전후 위 네 영역의 파일 hash는 같았다. 준비 성공을 적재 완료로 처리하지 않았다.

그 뒤 finalization baseline 수집은 기존 스크립트의 `audit --no-fetch --write-stale-cache`를
실행해 로컬 derived `stale-set.json`을 만들었다. 이후 요약을 검수/대기 지점으로 갱신하고 다시
prepare한 checkpoint의 네 영역 파일은 10,698개이며 준비 전후 불변이다. 기록 당시의
신규 draft 단독 추가 증거를 baseline 수집 이후 전체 파일 상태로 확대하지 않는다.

## 독립 검수와 실제 적재 후보

Standards 검수는 설치 파일 65개의 bytes/manifest/template 렌더·실행 비트, Claude mirror 5개의
canonical symlink, 프로젝트 overlay 비관리, 기존 WIP 13개의 내용·symlink 보존을 확인했다.
설치·초안 범위의 규칙 위반과 수정이 필요한 smell은 0건이다.

Spec 검수는 실제 발견/재개를 관찰하고 기존 reviewed mapping의 범위 설명에서 P2 1건을
발견했다. 원문과 호출처를 대조하면 직접 delegate는 Scene이고 그 뒤 Presenter로 전달된다.
기존 설명은 delegate를 presenter라고 단정했다. 제안 정정은 수신 delegate 내부와 실제 팝업
표시를 이 슬라이스 범위 밖으로만 설명하며 새 팝업 동작을 객체에 추가하지 않는다.

BB2 `bb2-brain-ingest/references/update-rules.md`는 다음을 명시한다.

> reviewed 객체의 의미 변경은 사용자 승인 뒤 reviewed 상태로 반영한다.

따라서 제안 문장을 제시했지만 승인 전에는 정식 객체를 쓰지 않았다. 기존 객체가 있다는
이유로 no-op 성공으로 닫지도 않았다. exact direct coverage와 ID→hash 전제조건을 준비했고,
MutationService의 읽기 전용 plan은 mapping 1개 update만 계획했다. 초기 전제조건 hash 형식
실수는 preflight에서 거부됐으며 `BrainStore.object_bytes` 기준으로 바로잡아 통과했다.
schema/coverage plan 통과는 의미 승인을 대신하지 않는다.

다음 실행 입력과 finalization config는 준비됐다. baseline은 고립 14개, 기존 미머지 locator
40개와 목표 develop HEAD를 보존한다. 이 값들을 0으로 만드는 추가 정비는 하지 않는다.
승인 후에는 원문·전제조건·draft SHA를 재확인하고 기존 ingest의 canonical receipt와
semantic finalization을 확인해야 한다. 그 전까지 이 이슈와 상위 스펙은 미완료다.

코드 검증에는 소비 프로젝트의 `project-code-verification.md`와 `bb2-code-search-routing`을
적용했다. 이 checkout에 `scripts/codesearch/bb2code`가 없어 `rg`로 selector·callback·delegate
연결 양끝을 확인했다. clangd 호출 그래프, 기기 터치 전달, 팝업 런타임은 검증하지 않았다.
CDB refresh와 빌드는 실행하지 않았다.

## 비용·품질과 효용의 한계

측정 가능한 것은 이 작은 fixture의 UTF-8 stdout bytes뿐이다. v1 대조는 동일 item/source
값을 고정 v1 Markdown의 JSON 블록으로 렌더한 프로토콜 fixture이며 모델이 독립 작성한
기준군이 아니다. 응답 축소 대조도 저장된 v1 응답에서 metadata만 남긴 오프라인 처리다.
현재 공개 v1 응답은 변경하지 않았다.

| 응답 | UTF-8 bytes |
|---|---:|
| v1 전체 update/show, 각각 | 6,506 |
| v1 update 응답 metadata만 남긴 오프라인 대조 | 206 |
| v2 항목/source patch update | 467 |
| v2 기본 show | 2,001 |
| v2 클릭 항목 show | 2,207 |
| v2 명시적 전체 show | 7,144 |

큰 응답을 줄였다는 사실만으로 총비용 감소를 입증하지 않는다. 별도 세션은 요약 뒤 5개
항목을 읽었으므로 작은 초안에서는 여러 응답의 metadata/source 반복이 불리할 수 있다.
기록·모든 재개·적재·재작업의 모델 입력/출력 토큰은 모두 미측정이다. v1·응답 축소 대조군의
전체 모델 실험과 품질 대조도 실행하지 않았다. 따라서 총 토큰 절감과 비용 효용은 미입증이다.

관찰한 품질 결과는 v2의 핵심 사실 일치, scope 밖 미결 유지, 기존 mapping의 과장 검출이다.
이를 v1보다 높은 품질이나 게임 기능 QA로 확대하지 않는다.

로컬 실행 로그·원문 재료·후보 diff·검사 JSON은 `/tmp/brain-ticket-registration.AaoWie/112-*`에
있다. 임시 진단 자료이며 재개 시 현재 checkout·승인 상태·원문·전제조건을 다시 확인한다.
