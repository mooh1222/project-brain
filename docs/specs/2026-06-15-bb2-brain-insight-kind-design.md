# BB2 Brain 인사이트 그릇 (Insight kind) 설계

- 작성일: 2026-06-15
- 정본: `wiki/bb2-client/bb2-project-brain.md` §7 미결 1 / task `bb2-project-brain-build` P3
- 합의: 메인(Claude) + architect(codex gpt-5.5) + critic(Opus 4.8 max) 3자 + 사용자 승인
- 상태: 설계 확정, 구현 계획(writing-plans) 대기

## 1. 목적과 배경

project-brain은 BB2 프로젝트 지식을 "구조화 객체 + 검수 사다리(candidate→reviewed, 사람 승인)"로 쌓는 저장소다. 기존 18종 kind(CodeLocator/GlossaryTerm/DecisionRecord/DomainMapping/TemporalFact 등)와 검색층(BM25+벡터+RRF+그래프 재정렬)을 갖췄다.

그런데 기존 18종으로 담기지 않는 지식이 있다: **여러 객체·구현·결정을 가로질러 관찰한 패턴/위험/교훈**. 단일 코드 위치(CodeLocator)도, 단일 결정(DecisionRecord)도, 단일 용어(GlossaryTerm)도 아니다.

기준 실례: "스테이지 클리어 토큰 노출 게이트가 입장 팝업과 이어하기 팝업에 서로 다른 판정 데이터로 이중 구현돼 있어, 한쪽만 고치면 어긋난다(LGBBTWO-4695의 구조적 원인)." 이 "구조적 위험" 자체가 알맹이라 기존 kind 어디에도 자연스럽게 안 들어간다.

이 그릇 = 신설 `Insight` kind.

## 2. 방향 (전제)

- "실례 데이터가 쌓일 때까지 설계 대기"(옛 가드)는 **폐기**. brain이 팀 공유가 목적이라 "기능 부재(아예 없음) ≠ 기능 개선(추후)" → **최소 그릇을 먼저 만들고 개발하며 수정**.
- 단 "머리로 분류 체계 짓기"는 여전히 금지. 설계 입력은 vault 6개 시스템 딥다이브(honcho/hindsight/Mercury/gbrain/mem0/supermemory)와 실제 실례.
- 검증된 실례는 1건(노출 게이트) + 개발 흐름(B형) 1건. 발굴 후보 20여 개는 미검증 풀이라 설계 전제로 쓰지 않는다 — dragon 오판 사례(조사 요청 발화를 확정 인사이트로, 단일 원인을 이중 구현으로 오해)가 LLM 발굴은 환각/오해가 섞인다는 것, 곧 검수 사다리 필요성의 실증.

## 3. 정체성 — Insight란

기존 18종으로 안 담기는, **2개 이상의 객체·구현·결정·기능을 가로지르는** 관찰/위험/교훈을 담는 자유 텍스트 객체. 두 결로 나뉜다:

- **A형 (`cross-cutting-risk`)**: 코드·구현·결정 사이의 어긋남/위험. 예: 노출 게이트 이중 구현.
- **B형 (`operational-lesson`)**: 운영·프로세스 교훈. 예: "알파 구현만 근거로 reviewed 처리하면 리얼 QA에서 뒤집힐 수 있다."

개발 흐름 **자체**(알파→베타→리얼→릴리즈 정의)는 Insight가 아니라 DomainContext류에 둔다. 그 흐름에서 나오는 교훈/위험만 Insight(B형)로 받는다.

## 4. 설계 결정

### 4.1 신설 + truth_role=synthesis 재사용

신설 kind. 기존 `KnowledgePage`는 `truth_role=synthesis`에 path 기반 종합 문서라(schema.py KIND_REQUIRED) 자유 텍스트 인사이트와 안 맞아 재정의하지 않는다.

`truth_role`은 **기존 `synthesis` 재사용**(새 값 안 만듦). 이유: 검색층이 `truth_role`을 읽지 않고 kind/status로 분기하므로(search.py에 truth_role 참조 0건), 새 값은 스키마·검색·테스트 계약만 넓힌다. "KnowledgePage와 다르다"는 차이는 kind로 표현한다.

**영구 전제(P3)**: synthesis를 CurrentView/KnowledgePage/Insight 셋이 공유한다(schema.py:50-51). "앞으로도 truth_role로 이 셋을 구분하지 않는다"를 전제로 둔다 — truth_role로 분기하는 코드를 미래에 추가하면 셋이 구분 불가가 되므로 넣지 않는다.

### 4.2 구조 (필드)

최소 골격 + 열린 확장 지점. 구조(슬롯)는 처음부터 두되 분류 값 체계는 강제하지 않는다. 근거: 비용 비대칭 — 선택 필드 나중 추가는 기존 객체를 안 깨뜨리지만(validate_object는 KIND_REQUIRED만 강제, schema.py:119-121), 잘못 박은 필수 분류 체계는 기존 객체 재적재 + 회상 랭킹 영향을 부른다.

- **필수**: BASE_REQUIRED(11개) + `body`(자유 텍스트 본문) + `source_object_ids`(가로지르는 근거 객체, 공통 ≥1)
- **`insight_type`**: A/B 두 값만 enum 강제(`cross-cutting-risk` / `operational-lesson`). 세부 분류는 열어둔다. 근거(P2): A/B조차 코드로 안 갈리면 승격 게이트(A형 source≥2)와 검색 분기가 성립하지 않는다. 세부 값까지 강제하면 "머리로 분류 체계 짓기"가 된다.
- **`code_locator_ids`**(선택, A형): 코드 앵커를 `source_object_ids`와 **별도**로 둔다. 근거(P1): 미래 stale-check 연동이 `code_locator_ids`를 본다(stale_check.py). 지금 분리해 두면 연동 시 재설계 비용이 준다.
- **`scope`**(적용 범위): 이 인사이트가 어느 작업/범위에서 영향을 주는지. 특히 B형은 범위가 없으면 "좋은 말" 저장소로 전락한다. 스키마상으로는 선택 필드지만, reviewed 승격 게이트(4.5의 4번)에서 존재를 확인한다 — 스키마 강제가 아니라 검수 강제다.
- **검수**: 기존 candidate→reviewed 재사용.

### 4.3 A형 / B형 — 한 kind, 분리는 나중

당장은 한 kind에 `insight_type`로 구분한다. 둘 다 "여러 객체를 가로지르는, 사람이 검수한 관찰"이라 저장 불변 조건이 같다. 나중에 A형이 코드 stale-check와, B형이 운영 타임라인/문맥 주입과 묶여 필수 필드·검색 경로가 갈리면 그때 별도 kind로 분리한다.

### 4.4 B형 경계

개발 흐름 같은 운영 배경 "자체"는 DomainContext류(또는 운영 컨텍스트 객체)에 둔다. 그 흐름에서 나오는 교훈/위험만 Insight(B형). 경계 예: "알파→베타→리얼→릴리즈 흐름" 정의는 DomainContext, "알파 구현만 근거로 reviewed하면 리얼 QA서 뒤집힌다"는 Insight.

### 4.5 승격 게이트 (검수 사다리에서 확인)

candidate→reviewed 승격 시 아래를 통과해야 한다. 못 통과하면 Insight가 아니라 기존 kind 또는 raw backlog로 보낸다(자유 노트 저장소 전락 방지):

1. 기존 18종 중 하나로 못 담는가?
2. 2개 이상 source 객체 사이의 관계/위험/교훈인가? (A형은 `source_object_ids` ≥2 강제, B형은 ≥1 + 적용 범위)
3. 다음 작업에서 실제로 영향받는 판단/행동이 있는가?
4. 적용 범위(`scope`)가 적혀 있는가?
5. 기존 reviewed Insight와 대조했는가? (C4 — 중복 누적 방지)

### 4.6 검색·회상 통로 (C1·C2)

Insight를 일반 검색 결과에 섞으면 안 된다. 두 가지 이유:
- reviewed면 kind 무관하게 results(확신 답)로 나간다(search.py:612-617, router.py:364-388) — 일반 질의 답에 긴 인사이트 본문이 끼어든다.
- 자유 텍스트 다토큰이라 융합 top-30의 객체 자리를 잠식해 그래프 재정렬(핀포인트의 열쇠)을 약화시킨다(search.py:78-81 주석의 raw 청크 회귀와 동형).

따라서 **구현 순서**(이 순서가 깨지면 분리가 동작하지 않음):
1. recall() 융합 단계에서 Insight를 raw처럼 **별도 레인**으로 분리(과대적재 후 kind 분리, search.py:367-387 패턴)
2. eval_recall에 kind 기반 **advisories 채널** 신설(results/candidates는 status만 보므로 별도 분기)
3. router 반환 dict에 **advisories 키** 추가(현재 source_object_ids/promotable_candidate_ids/candidate_object_ids/sections만 있음)
4. 위가 된 다음에야 surface.py 표면 추출기에 Insight 등록

surface.py 등록은 맨 마지막. 먼저 등록하면 일반 답에 새고, "통로 없이 색인 보류"는 미등록=회상 0건이라 자가모순이다.

### 4.7 무결성 검사 (C3)

- `validate_object`에 Insight 전용 검사: `source_object_ids` ≥1(A형 ≥2). 현재 검증은 필드 "존재"만 보고 빈 리스트도 통과하므로(schema.py:119-121) 별도 코드가 필요하다.
- `lint_store`에 Insight `source_object_ids` dangling 블록 추가(lint.py:163-180 패턴). 없으면 Insight가 supersede/삭제된 객체를 가리켜도 안 잡혀 "가로지른다"는 본질이 조용히 깨진다.

### 4.8 중복·덮어쓰기 (C4·C5 — 사용자 승인)

- **C4 중복**: 자유 텍스트라 자동 dedup 불가. 검수 게이트 5번("기존 reviewed Insight 대조")으로 사람이 막는다. 같은 위험을 다른 문장으로 새로 적재하지 말고 기존 인사이트에 source를 보강한다. (주제 키 같은 강제 장치는 안 둔다 — 또 분류 체계 박기가 되므로.)
- **C5 덮어쓰기**: id 네이밍 규약을 둔다(`insight.<주제-slug>`). 같은 id로 reviewed를 다시 적재하면 **거부하지 않고 검토 라운드 강제**(기존 supersede 흐름과 동일 — candidate로 받아 검토 후 기존을 superseded, 새 것을 reviewed). 검토 이력이 보존된다(ingest.py:31-36 last-write-wins 덮어쓰기 방지).

## 5. 엔진 변경 범위 (project-brain 레포)

- `schema.py`: KIND_REQUIRED에 Insight(body, source_object_ids), KIND_TRUTH_ROLE에 Insight=synthesis, insight_type enum(A/B), validate_object에 source 개수 검사
- `lint.py`: Insight source_object_ids dangling 블록
- `search.py`: recall 융합에서 Insight 별도 레인, eval_recall advisories 채널
- `router.py`: 반환 dict에 advisories 키
- `surface.py`: Insight 표면 추출기 등록(맨 마지막)
- `ingest.py`: reviewed→reviewed 검토 라운드 강제(기존 supersede 경로 재사용 가능 여부 확인)

## 6. 검증 기준

- 엔진 단위 테스트: Insight 적재 / 검증(source 개수, A형 ≥2) / lint dangling / 검토 라운드 강제
- 골든셋: 노출 게이트 인사이트 적재 후 "스테이지 클리어 토큰 수정" 질의 → **advisories 통로로 회수되고 기존 results·핀포인트(s1·s2)는 점수 불변**(C2 회귀 방지 확인)
- B형 시나리오: 개발 흐름 교훈 적재 후 "이벤트 매핑 reviewed 승격 전 확인" 질의 회수
- 실례 1건(노출 게이트)으로 end-to-end 1회 적재·회상 검증

## 7. 미룸 (이번 범위 밖)

- `insight_type` 세부 값 체계 확정(A/B 아래 하위 분류) — 실사용으로 채움
- 점수(confidence 등)의 검색 반영
- 관계 타입(derives-from 등) 강제
- A형의 stale-check 연동(stale-check가 현재 DomainMapping 전용 — `code_locator_ids` 필드만 미리 둬서 미래 연동 비용을 줄임, P1)
- A형/B형의 별도 kind 분리

## 8. 3자 합의 기록

- **architect(codex gpt-5.5)**: Q1~Q4 검토. source≥2를 전체 필수처럼 본 충돌을 인정하고 (b)로 정밀화(공통 ≥1, A형 ≥2 승격 조건, B형 ≥1+적용범위). synthesis 재사용 + 별도 통로 + 적용범위 게이트 제안.
- **critic(Opus 4.8 max)**: 엔진 코드 직접 검증으로 결함 C1~C5 + 트레이드오프 P1~P3 + 통과 조건 5개. C1·C2(별도 통로가 기본 동작으로는 안 일어남)·C4(팀 공유 시 중복으로 신호가 묽어짐)가 핵심.
- **메인 + 사용자**: critic 통과 조건 전부 수용. C4(사람 대조 게이트)·C5(검토 라운드 강제) 사용자 승인.
- **코드 근거**: schema.py:38·50-51·119-121, search.py:78-81·367-387·612-617, router.py:364-388, lint.py:163-180, ingest.py:31-36, stale_check.py:16·200
