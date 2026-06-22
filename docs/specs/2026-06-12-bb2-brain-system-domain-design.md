# BB2 Brain 시스템 도메인 적재 + 개발 착수 조립 모드 — 설계 문서

**작성**: 2026-06-12 (이어서 22 후반, 세션 f08fdf80 후속 논의 세션)
**리뷰**: 2026-06-12 적대 리뷰 3렌즈(사실 검증·자기완결성·적대 설계 비판, Explore+opus 읽기 전용)
— 사실 검증 18항목 전부 일치 / 발견 수용 17건 반영(H3·M4·L3 + 적대 6공격 중 5) / 기각 1건
(mininest 오라우팅 반례 — 리뷰어가 title 표면을 누락, 시뮬레이션으로 불성립 확인). 주요 신규
발견: shootable-bubble-remover 고아(이주 선행 조건), disturbList 가로 심볼 분산(귀속 규칙 미결),
eval 7/7↔s9 신설 충돌(건수 갱신 규칙), 스킬 분기 미반영 절차 게이트.
**위상**: ★시범 적재 완료(2026-06-12 이어서 23) — §11이 실측 결과★. §3 결정 2 TDD·방해버블 시스템
38객체 적재·baseline 대조·§9 미결 1·3·4 해소까지 검증. 남은 것=미결 2(동의어, 후속)·미결 6(스킬
정식화, 승인 대기). 설계 전제·실측·실험 기록은 이 문서가 정본이고, vault task [[bb2-project-brain-build]]
"이어서 22·23" 이력은 요약본이다.
**데드라인 맥락**: 5.6 스펙이 다음 주 확정. 5.5 기능 적재물은 5.6 개발에 직접 안 쓰이므로(사용자 확인),
5.6에서 brain이 기여하려면 시스템 도메인 지식이 그 전에 서 있어야 한다.

---

## 1. 목적 함수 재정의 — 이 설계의 출발점 (사용자 발언, 06-12)

> "단순히 어떻게 동작하는지를 묻는 게 아니라, a기능 추가 필요 b기능 수정 등 이 요구사항일 때
> brain에서 필요한 내용을 찾아 context를 만들 수 있어야 해. 그래야 brain에 있는 내용이면 매번
> 컨텍스트 설명을 하지 않아도 되고 너가 개발할 수 있는 지식이 쌓이면 점점 우리 프로젝트 이해도가
> 높아질 거 잖아."

> "시스템 도메인 지식뿐만 아니라, 지금 적재된 내용도 질문에 답은 물론 개발에 기여해야 하는 게
> 핵심이야. 실제 개발자가 프로젝트 지식이 있어야 개발하고 답변도 하는 거처럼 마찬가지 역할"

- **brain = 에이전트의 프로젝트 지식.** 질문 답변과 개발 기여가 동격 목적이다.
  기존 적재물을 포함한 brain 전체의 역할 기준이지, 시스템 도메인 적재만의 기준이 아니다.
- 정본 wiki [[bb2-project-brain]] §1에 발언 추가 완료(06-12). 최초 구상(05-23 "같이 개발한 동료")의
  명시화이지 스코프 변경이 아니다.
- 따라오는 변화 3가지:
  1. **적재 완성 기준**: "질문에 답 나옴" + "이 도메인의 추가/수정 요구 시 brain 회수만으로 착수 가능"
  2. **회상**: 단건 질의 외에 "요구사항 → 착수 브리핑" 조립 모드 (§7)
  3. **평가**: 골든셋에 개발 착수 시나리오 계열(s9~) 신설 (§8)

### 논의의 발단 (맥락 복원용)

이어서 21 Phase C에서 "방해버블 공통 용어 소속 컨텍스트"를 보류(권장)로 닫았는데, 사용자가
범위를 일반화해 재오픈: "방해버블 외에도 공통 개념이 많고, 별도 기획서가 없는 인게임 로직 관련
내용 등에 대해서 어떻게 처리해야 할지 지금 논의하면 좋겠어." 이어서 "에이전트가 방해버블 동작
방식이라던가, 인게임 슈팅, 트레이스, 바운더리, 그룹로직 등 기획서에 없는 내용들 물어보면 하나도
모를 거잖아" → 목적 함수 재정의로 확장.

---

## 2. 실측 현황 (2026-06-12, 전부 직접 확인)

| 항목 | 실태 |
|---|---|
| DomainContext | 18개 전부 기능 단위 (5.5 적재 14 + 샐리·토큰·입장팝업·꿀통) — 시스템/공통 단위 0 |
| 컨텍스트 간 용어 중복 | 0건 — 공통 개념은 첫 등장 기능에 단독 적재 |
| (별건) sally-canoe 내부 용어 중복 | 9건 (COOLTIME·FERR·FINISHED·LaneIndex·PopupSallyCanoeResult·RACE_END·SALLY_CANOE_RACE_STATUS·SallyCanoeRaceFinishNoticePopup·targetStages — 같은 term 2~3파일). 데이터 위생 이슈로 별도 처리 대상, 이 설계와 무관 |
| 교차 컨텍스트 참조 | 0건 (매핑 glossary_term_ids가 타 컨텍스트 용어를 가리키는 사례 전무 — 컨텍스트들이 섬) |
| 공통 개념 소속 실태 | `슈팅버블 제거 방해버블 (isShootableBubbleRemover)`=disturb-hedgehog 용어 — ★단 이 용어를 glossary_term_ids로 가리키는 매핑·결정이 전 코퍼스에 0개(고아) — 이주해도 그래프가 끌어올 엣지가 없으므로 연결 선행 필요(리뷰 발견)★ / `CLOUD_DO_POP_ON_NEAR_THIS_POP`=disturb-drone 용어, cloud 매핑(cloud-near-pop-attribution-missing)은 disturb-hedgehog 소속 — ★"어긋남"의 실체: 링크가 아니라 소속 분산(해당 매핑의 glossary_term_ids는 빈 배열 — 개념의 용어와 그 개념을 다루는 매핑이 다른 컨텍스트에 살면서 서로 연결도 안 된 상태)★ / `disturbList`=용어 부재(locator·evref·decision에 언급만). ★가로 심볼 분산 실례: disturbList를 다루는 매핑 3건(disturb-mininest.score·bird-hit-score / disturb-ghost-mirror.score)이 같은 정본 파일(ScoreCalculateFactor.h)을 앵커로 2개 컨텍스트에 흩어짐 — §9 미결 1의 귀속 규칙이 답할 충돌(리뷰 발견)★ |
| 사용자 예시 개념의 코드 실재 | 트레이스·바운더리·그룹로직 → `game/logic`(PuzzleLogic.h·BaseGameLogic.h)·`game/model`(BubbleMapData) 등에 실재. brain은 빈손 |

### 기존 자산이 이 갭을 못 메우는 이유

| 자산 | 성격 | 판정 |
|---|---|---|
| dev-* 스킬 8개 (disturb-bubble·petskill 등) | 작업 가이드 (만질 때 절차·주의) | "동작 방식" 설명 아님. ★dev-disturb-bubble은 만들고 사용한 적 없음 — 참고 부적격 (사용자 확인, 06-12)★ |
| CLAUDE.md 9개 (game/ 계열) | Do/Don't 작업 가이드 | 동작 설명 아님 |
| CONTEXT-MAP.md | 코드 도메인 사전 지도 | 빈 껍데기 (stage-clear-token 1개뿐) |
| vault wiki (bb2-code-pattern-reference 등) | 개인 노트 | ★사용자 개인용 — brain 정본 경로 아님. "vault는 나중에 안 쓸 거고 내 개인용" (사용자, 06-12)★ |

---

## 3. 설계 결정 5건 (논의 합의 — 시범 적재가 검증)

### 결정 1. 컨텍스트 단위 = 개념 단위 (코드 모듈 단위 아님)

"슈팅이 어떻게 동작해?"는 game/logic+model+state를 가로지른다. 디렉토리 따라 자르면 질문과
어긋난다. **질문이 단위다** — 인게임 슈팅·트레이스, 버블 그룹/매칭 판정, 방해버블 시스템,
펫스킬 시스템, 점수 계산, 게임 상태 흐름 같은 단위. 사용자가 예로 든 것들이 정확히 이 단위.

★미해결 충돌(리뷰 발견, §9 미결 1)★: 한 심볼이 두 개념 단위에 동시에 걸칠 때의 귀속 규칙이
없다. 실례가 이미 코퍼스에 있다 — disturbList(ScoreCalculateFactor.h)는 "방해버블 시스템"
후보이면서 "점수 계산" 가로축인데, 현재 매핑 3건이 mininest·ghost-mirror 두 기능 컨텍스트에
흩어져 같은 파일을 앵커한다. 시범 적재 첫 객체부터 부딪히는 문제이므로 시범에서 귀속 규칙을
실측으로 정한다 (후보: 의미 매핑은 개념 소유 컨텍스트 1곳 + 다른 컨텍스트는 용어/매핑이
그래프 참조로 연결 — 미리 확정하지 않음).

### 결정 2. 기능 컨텍스트와 평면 유지 + 그래프 연결 (계층 신설 안 함)

엔진에 컨텍스트 부모-자식 개념이 없고 만들지 않는다. 시스템 컨텍스트의 용어를 기능 매핑·결정이
`glossary_term_ids`로 참조하면(스키마는 교차 참조를 막지 않음 — lint도 끊긴 id만 검사) 그래프
재정렬이 끌어온다.

★선행 과제 — infer_scope "구체 표면 우선" 규칙 (엔진 TDD)★

함정 실측: `_context_surface_token_sets`(search.py:238)는 display_name/title/context_key를 토큰
집합으로 만들고, infer_scope(search.py:260)는 "표면 토큰이 **전부** 질의에 포함"이면 매칭,
**2개 이상 매칭이면 None**(scope 포기). disturb 4종의 표면에 전부 "방해버블"이 들어 있어
(예: display "고슴도치 방해버블"), 시스템 컨텍스트 표면을 "방해버블"로 만들면:

- "고슴도치 방해버블 화난 상태?" → {고슴도치,방해버블}(hedgehog)와 {방해버블}(시스템) 둘 다 매칭
  → 다중 → scope=None → **기존 핀포인트 질의가 scoped BM25 보호를 상실** (s1 회귀 재노출)

해법 — 규칙 정식 정의 (TDD 명세):

> matched(매칭된 컨텍스트들)에서, 매칭에 사용된 표면 토큰 집합이 **다른 매칭의 표면 토큰
> 집합의 진부분집합**인 것을 제거한다(maximal만 남김). 남은 maximal이 1개면 단일 특정,
> 2개 이상(비포함 관계 또는 동률)이면 기존대로 None.

{고슴도치,방해버블} ⊃ {방해버블} → hedgehog 승. "방해버블 점수 처리?"(고유명 토큰 없음)는
시스템 컨텍스트만 매칭 → 시스템으로. 표면 디테일(엔진 실측): 표면=display_name/title/context_key
3종, title은 "도메인" 접미 제거 후, 2자 미만 토큰 제외 — 한 컨텍스트가 여러 표면을 가지므로
**컨텍스트당 "매칭된 표면 중 최대 집합"으로 비교**한다(예: mininest는 display가 안 맞아도
title {미니둥지,방해버블}로 매칭됨 — 리뷰의 오라우팅 우려는 title 표면 덕에 실제로는 불성립,
시뮬레이션 확인).

합성 red 테스트 케이스 (StubEmbedder·합성 DomainContext — 시스템 컨텍스트 적재 전이라
실코퍼스 검증 불가한 닭-달걀을 합성으로 끊는다):

| 질의 토큰 | 표면들 | 기대 scope |
|---|---|---|
| {결제} | A={구매,결제} | None (0매칭 — 전부-포함 불충족) |
| {고슴도치,방해버블,상태} | H={고슴도치,방해버블}, S={방해버블} | H (포함 관계 → maximal 승) |
| {방해버블,점수} | H={고슴도치,방해버블}, S={방해버블} | S (S만 매칭 — 단일) |
| {고슴도치,드론,방해버블} | H={고슴도치,방해버블}, D={드론,방해버블}, S={방해버블} | None (maximal 2개 — H·D 비포함 관계) |

골든셋: 기존 **s1~s7**(현재 전부 — s8은 부존재, 재랭커 트리거용 미래 계획) 회귀 무결 확인.
실코퍼스 시스템 컨텍스트 케이스는 시범 적재 후 골든셋에 추가(§8).

### 결정 3. 소스 패킷 = 코드 정본

기존 절대 규칙 6("view 심볼↔기획서, model 심볼↔서버위키")은 기획서 있는 기능 전제라 시스템
도메인에 그대로 안 맞는다. 시스템 도메인 전용 소스 패킷:

1. **코드 + 코드 주석 (정본)** — 동작·경계·값의 진실
2. git 이력 (PR·커밋, 있는 만큼) — "왜"의 근거
3. 과거 기획서·서버위키 단편 (있으면) — 보조
4. 개발자·사용자 확인 — 코드로 판정 안 되는 의도

confidence: 코드에서 직접 검증된 사실=high. 의도·역사는 이력 없으면 `history_coverage=unsearched`
정직 표기 (기존 규약 그대로).

보강 2건 (리뷰 반영):
- **정본 순위: 코드 동작 > 코드 주석.** 주석은 코드 변경 시 같이 안 바뀌는 stale 소스다(이
  프로젝트 실측 — 꿀통 멤버 주석 stale, locator 어긋남 3건). 주석과 동작이 어긋나면 동작이
  진실이고, 어긋남 자체를 caveat으로 적는다. 의도-코드 분기(cloud 누락 버그 같은)는 코드로
  "왜"를 판정할 수 없으므로 소스 4순위(개발자·사용자 확인)로 — 기존 cloud 건 처리 방식 그대로.
- **EvidenceRef 단독 쏠림**: 시스템 도메인 reviewed 매핑의 근거가 코드 EvidenceRef 한 종류로
  쏠리는 것은 허용한다(기획서가 없는 도메인의 정직한 상태). §6.4 non-empty 강제는 충족되고,
  교차 검증 부재는 confidence·caveat으로 드러낸다 — 빈 근거 가짜 채움 금지.

### 결정 4. 절차 = 기존 적재 스킬(bb2-brain-ingest)에 시스템 도메인 분기 추가 (신설 스킬 아님)

시스템 도메인은 "완료" 개념이 없는 살아있는 시스템이라 Source Intake Gate·추출 5단계의 전제가
다르지만, 객체 모델·검증·승격 절차는 동일하다. 별도 스킬보다 분기가 유지비가 싸다.
스킬 수정은 승인 필요 (skill-and-project-files 룰).

### 결정 5. 시작 = 시범 1개 검증 후 확산

인게임 전체는 거대하다. 시범 1개(방해버블 시스템 — 사용자 확정)로 방식을 검증하고 패턴을 확립한
뒤 확산한다. `ingame-core` 같은 거대 그릇을 미리 만들지 않는다 (실사용 없이 미리 짓기 금지).

---

## 4. 실험 A — 개발 착수 조립이 기능 도메인에서 되는가 (성공)

**설계**: 적재가 두터운 기능에 가상 수정 요구를 던지고 brain만으로(코드 검색 금지) 착수 브리핑을
조립 → 코드 실측과 대조. 재는 것은 "있는 지식을 작업 컨텍스트로 묶어내는 능력".

- ★대상 선정 정정(사용자)★: 처음 고슴도치(73객체 최다)로 했다가 중단 — "인게임 내용이 브레인에
  하나도 없어서 어떻게 연관되어지는지 모르잖아". 인게임 동작 수정 요구는 시스템 지식이 0이라
  조립 검증이 아니라 빈손 확인이 된다. **샐리의 카누로 교체** — 이벤트 기능이라 적재물이
  자기완결적이어서 조립 능력을 순수하게 잰다. (여기서 "하나도 없다"는 방해버블 기능별 reskin
  객체(§2 — 있음)가 아니라 **인게임 동작 로직·시스템 계약 지식이 0**이라는 뜻 — 기능 객체는
  "A는 B한다"를 답하지만 "A를 수정하려면 어디를 만지나"의 베이스를 못 준다.)
- **가상 요구**: "샐리 카누 — 경주 결과 팝업에 내 순위뿐 아니라 전체 레이서 순위 목록이 표시되도록 수정"

### 질의 로그 (동의어·조립 모드·s9 설계의 1차 데이터)

| # | 질의 | 결과 |
|---|---|---|
| Q1 | 샐리의 카누 경주 결과 팝업 구현 위치 | ★미스★ — top3=how-to-banner-howto-popup·alert-popups-pyn-forced-order·alert-popups-race-finish-notice. 정답(race-end-result-*) top5 밖. 원인: "경주"≠도메인 용어 "레이스" + "구현 위치"가 변별 토큰 아님 |
| Q2 | 샐리의 카누 레이스 결과 팝업 순위 표시 | 적중 시작 — race-end-result-failure 1등, race-status-lifecycle 4등. raw 동반 spec-v8 #037·025·026 |
| Q3 | PopupSallyCanoeResult (식별자 직격) | ★최정확★ — race-end-result-achieve·finish-notice·failure·branch가 top4 (결과 팝업 군집 일괄 회수) |
| Q4 | 샐리의 카누 레이서 완주 순위 보상 | rewards-rank-structure 추가 회수. candidate 채널: rewards-rno·rewards-post-reward |
| Q5 | 샐리의 카누 RankingModel 레인 순위 데이터 | 데이터 층 군집 — ranking-raceinfo-rpmap-lane·rankingmodel-fields·server-record-naming·npc-movement-roster |

점수대 0.02~0.031 (상위권 격차 작음). failure 매핑의 핵심 디테일(순위 보정 규칙)은 검색 surface에서
잘려 **객체 JSON 원문 직접 열람**으로 확보 — 조립 모드가 원문 열람 단계를 포함해야 하는 근거.

### 조립된 착수 브리핑 (산출물 요약)

- **데이터 출처**: RaceInfo recordMap이 본인 포함 7명의 RankingModel(getRank·getIsMyRank·
  getLaneIndex) 보유. 현재 달성 팝업은 getIsMyRank()로 내 것만 뽑아 myRank 스칼라 전달
  (mapping.race-end-result-branch — makeEnterFlow [4-achieve] step) → **시그니처 변경이 작업 중심**
- **표시 구조**: 달성 PopupSallyCanoeResult(PopupEventCommonReward 상속·race.end.in.popup rank
  포맷·박스 SAM 시퀀스·보상 지연 생성) / 실패 SallyCanoeRaceFailurePopup의 `_makeProfileArea`
  (프로필+레인 색 카누 스프라이트+순위 라벨)가 **레이서 1명 표시 패턴 재사용 후보**
- **함정(기존 규칙)**: rank≤0(진행도 0)이면 recordMap.count()를 꼴찌 순위로 보정 / 결과 팝업은
  1.4s 추가 대기 버퍼 뒤 노출 / 종료 사운드 EVENT_SALLY_CANOE_RESULT / 달성·실패는 씬 진입부터
  다른 분기 (LGBBTWO-4540)
- **brain에 없는 것 (정직 명시)**: 신규 UI 배치(디자인 가이드 필요·당연) / RankingModel 전체 필드 시그니처

**코드 대조 (3/3 일치, 재현 가능하도록 위치 전부 명기)**:
- `PopupSallyCanoeResult::create` — SallyCanoePopups.hpp:130
- recordMap/getIsMyRank 사용처 — SallyCanoePresenter.cpp (makeEnterFlow 내, getIsMyRank 2건)
  ·SallyCanoePopupEnterRaceInfoNode.cpp (isMe 판정)
- 순위 보정 구현 — SallyCanoePopups.cpp:435-442 (`if (displayRank <= 0)` → `pRecordMap->count()`)
- (1.4s 버퍼의 코드 위치는 SallyCanoePresenter.cpp:117-127 `withAdditionalDelay(bRaceEnded ? 1.4f : 0.0f)`
  — locator 백필 때 수선·실측한 위치)

**결론은 기능 도메인 한정이다.** 샐리는 적재 584객체·기획서/Jira/wiki raw까지 있는 가장 두터운
기능이라, 이 성공이 "얇고 기획서 없고 가로로 얽힌 시스템 도메인에서도 조립이 된다"의 증거는
아니다(리뷰 지적 수용). 시스템 도메인의 조립 가능성은 §5 시범의 실측으로만 주장한다.
★시범 전 baseline 의무★: 시스템 컨텍스트 적재 **전에** 가로 질의("신규 방해버블 추가하려면?"
"방해버블 점수 어떻게?")를 현 코퍼스로 돌려 빈손의 모양을 박제 → 적재 후 동일 질의와 대조가
시범의 성공 판정이 된다.

### 실측 갭 2건

1. **질의 어휘 민감도** — 자연어 요구사항의 단어가 도메인 용어와 어긋나면 미스(Q1).
   식별자 직격이 최정확. 동의어 흡수가 필요 (어디서: §9 미결 2).
2. **일괄 조립 모드 부재** — 브리핑 1개 = 질의 5번 + 원문 열람, 전부 수동. 표준 절차화 필요 (§7).
   엔진 변경은 불요 추정 (검색층 위에 스킬 절차로 충분).

### 착수 브리핑 5요소 (= 시스템 도메인 적재의 내용 기준)

1. **데이터 출처** (어느 모델/테이블이 무엇을 들고 있나)
2. **구조/표시 패턴** (어느 클래스가 어떤 구조로, 재사용 후보 포함)
3. **확장 지점** (신규 추가/수정 시 만지는 곳들)
4. **기존 규칙/함정** (보정 규칙·타이밍·컨벤션)
5. **과거 결정** (왜 이런 구조인가, 관련 이슈)

---

## 5. 시범 적재 계획 — 방해버블 시스템 (다음 세션)

**0단계 — 절차 게이트 (리뷰 H2 반영)**: 시범 적재 전에 둘 중 하나를 결정한다.
(a) §6 분기를 ingest 스킬에 먼저 반영(skill-and-project-files 룰 — 사용자 승인 필요) 후 적재, 또는
(b) 이번 시범은 분기 없이 §4 착수 브리핑 5요소를 **수동 체크리스트**로 적용하고, 분기 정식화는
시범 결과 반영(§9) 때 — 시범이 분기 내용을 검증한 뒤 박는 게 순서상 자연스러우므로 **(b) 권장**.

- **컨텍스트**: 가칭 `context.disturb-bubble-system` — 확정 전까지 이 표기로 통일, 최종 명명은
  §9 미결 3에서. 표면(display_name 등)은 "방해버블"을 포함하되, 결정 2의 구체 표면 우선 규칙이
  엔진에 들어간 **뒤에** 색인 — 순서 주의.
- **적재 대상 (착수 브리핑 5요소 기준)**:
  - 방해버블 공통 동작 계약: BubbleObject 파생 구조, 타이밍 패턴(NearBubblePop/AddBallToTheMap/
    PostProcess 계열 — 코드에서 실측해 확정, dev 스킬 서술은 참고만), disturbList 등록(점수 연계),
    isShootableBubbleRemover 분류, BUBBLE_TYPE enum 범위(kMASK_DISTURB_TYPE)
  - ★확장 지점★: 신종 방해버블 추가 시 만지는 곳 전부 (enum·클래스·등록 테이블·리소스 로드)
    — 코드 실측 기준
  - 공통 개념 이주: `슈팅버블 제거 방해버블 (isShootableBubbleRemover)`(hedgehog→시스템)·
    `CLOUD_DO_POP_ON_NEAR_THIS_POP`(drone→시스템)·`disturbList`(신설).
    GlossaryTerm은 supersede 필드가 없으므로 **제자리 context_id 수정 + DecisionRecord**
    (꿀통 개칭 방식, 이어서 16 스펙 분기표 준수).
    ★이주 선행 조건(리뷰 발견)★: shootable-bubble-remover는 현재 **고아**(참조 매핑·결정 0)라
    이주만 하면 그래프가 끌어올 엣지가 없다 — 이주 전/동시에 시스템 분류 매핑(또는 기존
    hedgehog 매핑)에 glossary_term_ids로 엮는 연결 작업이 먼저다. 규칙 7(고아 금지)의 기존
    위반 해소를 겸한다.
- **소스 패킷 선언**: 코드 정본 (결정 3). 기획서 단편은 disturb 4종 raw가 이미 있음 — 참조 가능.
- **검증 (순서 의무 — 리뷰 H1·M2 반영)**:
  1. baseline: 적재 **전** 가로 질의 2건("신규 방해버블 추가하려면?"·"방해버블 점수 어떻게?")
     결과 박제 (§4 baseline 의무)
  2. 적재 후 `project-brain eval` — **s9 신설 전이므로 기대값 7/7**(s1 핀포인트 무결 = 결정 2
     선행의 검증 겸함)
  3. 가상 질의 실연: baseline과 동일 질의 재실행 → 확장 지점·분류 용어 회수 대조
  4. 교차 연결 확인 (구체 절차): ① lint 0 (끊긴 id 없음) ② `project-brain search "고슴도치
     방해버블 슈팅버블 제거"` → hedgehog 매핑이 results에, 이주된 용어가 linked로 동반되는지
     ③ `project-brain search "방해버블 분류"` (고유명 없는 일반 질의) → 시스템 컨텍스트로
     라우팅되는지 (scope 추론 로그 확인)

## 6. (참고) 적재 스킬 분기 초안 — 시스템 도메인 모드

bb2-brain-ingest에 추가할 분기의 골자 (승인 후 반영):

- 발동: 대상이 기능(이벤트/픽스)이 아니라 시스템/모듈 개념일 때
- Source Intake Gate 변형: 소스 패킷 기본값 = 현재 develop 코드+주석 (기획서·서버위키는 있으면 보조)
- 추출 뼈대: 절대 규칙 6(계층-소스 매칭) 대신 **착수 브리핑 5요소**가 추출 체크리스트
- `feature_done` 축 대신: 시스템은 살아있으므로 "이 시점 코드 기준" 스냅샷 선언(commit_sha 의무 —
  이어서 22 전반에서 의무화 완료)과 갱신 트리거(코드 변경 감지 → 재확인)로 관리

## 7. recall 조립 모드 — 실험 A 절차의 표준화 (recall 스킬 확장 초안)

요구사항이 들어오면:

1. **도메인 특정** — 요구사항에서 기능/시스템 컨텍스트 후보 식별
2. **분해 질의** — 최소 3축: 구조/표시("X 팝업·화면 구조"), 데이터("X 데이터 모델·출처"),
   흐름/결정("X 흐름·분기·이력"). 각 질의는 **도메인 용어로 치환해 변형 1회 재시도**
   (Q1 미스 패턴 대응 — 예: "경주"→"레이스") + 알면 식별자 직격 추가 (Q3 최정확 패턴).
   ★치환할 용어를 어디서 얻나(닭-달걀 — 리뷰 지적)★: 1차 질의가 미스여도 같은 컨텍스트의
   인접 객체는 대개 회수된다(실험 A의 Q1도 sally 객체들은 나왔고 그 표면에서 "레이스"를 습득해
   Q2를 만들었다 — 실증된 경로). 1차가 needs_clarification으로 닫혀도 **변형 재시도는 의무**
   (없다 단정은 재시도 후). 근본 해법은 용어 객체 동의어 표면 보강 — §9 미결 2가 1순위로 검토
3. **적중 객체 원문 열람** — 검색 surface는 잘린다. 핵심 매핑은 JSON 원문(meaning·boundary·caveats)까지 읽는다
4. **브리핑 조립** — 5요소 틀(§4)에 채우고, 각 사실에 근거(객체 id) 표기
5. **없는 것 명시** — "brain에 없음" 목록 (기존 recall 계약 그대로)

엔진 변경 없음 — 스킬 절차 확장 (승인 후 반영).

## 8. 골든셋 s9 계획 — 개발 착수 시나리오

- 형태: 요구사항 문장 질의 → 기대 회수 = 해당 도메인의 핵심 매핑 군집 (top5_any + linked_any_groups
  기존 골격 재사용)
- 1차 후보: 실험 A 요구사항 그대로 (s9 = "샐리 결과 팝업 전체 순위 표시" → race-end-result-branch·
  failure 등 기대) + 시범 적재 후 방해버블 확장 질의 (s10 후보)
- 위상: 조립 모드 전체(질의 여러 번+원문 열람)가 아니라 **첫 질의의 회수 품질**을 고정하는 회귀 가드
- ★기대 건수 갱신 규칙 (리뷰 H1 반영)★: 본 문서의 "eval 7/7"은 전부 **s9 신설 전** 기준이다
  (현재 골든셋 s1~s7, 7건 실측). s9/s10 추가 순서 = 시범 적재 검증(7/7)이 끝난 **뒤** — 추가
  시점부터 검증 기준은 "신규 포함 전건 통과(8/8, 9/9)"로 갱신되고, 가드 스크립트·task의 "7/7"
  표기도 그때 함께 갱신한다.

## 9. 미결 — 시범 적재가 답할 것 + 절차 게이트 + 별건 큐

★시범 후 갱신(2026-06-12 이어서 23): 미결 1·3·4 ✅ 해소 — 실측 답은 §11.4. 미결 2(동의어)·
6(스킬 정식화)은 후속(§11.6). 아래는 시범 전 원안.★

1. **확장 지점 지식의 그릇**: DomainMapping(mapping_key="신종 추가 확장 지점", locator 여러 개)으로
   충분한가, 아니면 어색한가 → 시범에서 실제로 만들어보고 판정. P3 인사이트 그릇과의 경계도 여기서.
   ★+가로 심볼 귀속 규칙(결정 1의 미해결 충돌)★: disturbList처럼 두 개념 단위에 걸치는 심볼의
   의미 매핑을 어디 한 곳에 두고 어떻게 연결하는지 — 시범 첫 객체에서 실측으로 정한다.
2. **동의어 흡수 위치**: ★1순위 검토=용어 객체 동의어 표면 보강★(s1 골든셋 note가 이미
   "synonyms 빈 상태"를 미스 원인으로 기록 — 닭-달걀이 없는 유일한 위치, 리뷰 반영으로 우선순위
   교체) vs 조립 모드의 질의 변형(§7-2, 스킬 층 — 이미 절차에 포함, 보조) vs 검색층(엔진) —
   시범 후 실측으로.
3. **시스템 컨텍스트 표면 설계 + 최종 명명**: "방해버블" 단독 표면이 구체 우선 규칙과 결합해
   의도대로 라우팅되는지 (일반 질의→시스템, 핀포인트→기능). context_key/display_name 최종
   명명(가칭 disturb-bubble-system)도 이 시점에 확정.
4. **이주한 용어의 기능 쪽 연결과 scope 영향**: 이주는 의도적으로 첫 교차 컨텍스트 참조를
   만든다(§2의 "참조 0건"은 안전 주장이 아니라 현황 기록). 확인할 것 — hedgehog 매핑이 이주된
   용어를 가리킬 때 lint·회상 무결 + ★이주된 용어는 scope=hedgehog 하드 필터에서 빠지므로
   (recall의 context_id==scope 필터·색인 context_id 변경) 핀포인트 질의에서 그래프 동반
   (linked)으로 따라오는지가 판정 기준★ (§5 검증 4 절차).
5. (별건 큐 — 시범과 무관) sally-canoe 내부 용어 중복 9건 정리.
6. ★절차 게이트(리뷰 반영)★: 스킬 2종 수정 승인 — §6 ingest 시스템 도메인 분기 + §7 recall
   조립 모드 확장은 둘 다 현재 스킬에 미반영이며 skill-and-project-files 룰상 사용자 승인 필요.
   처리 시점 = §5 0단계(분기는 (b) 권장 시 시범 후) / 조립 모드는 최종 설계 확정 때 함께.

## 10. 연결

- ★작업 순서의 단일 출처는 본 문서★: §3 결정 2 선행 TDD → §5 0단계 게이트·시범 적재 →
  §9 반영·최종 설계. vault task 시작점의 단계 요약은 비구속 미러(어긋나면 본 문서 우선).
- vault task: [[bb2-project-brain-build]] "🔶 다음 세션 시작점" 11차 + "이어서 22" 이력
- 정본 wiki: [[bb2-project-brain]] §1 (목적 함수 발언 06-12 추가됨)
- 직전 작업: locator commit_sha 백필 `b8b91ccc14` (이어서 22 전반 — commit_sha 의무화가 §6의
  스냅샷 선언 전제)
- 실전 트리거: 5.6 스펙 확정(다음 주) 후 첫 개발 건 = 조립 모드 실전 / cloud 수정 PR develop 반영
  = supersede 실전 + locator 어긋남 실측

---

## 11. 시범 적재 실행 결과 (2026-06-12, 이어서 23)

본 문서대로 방해버블 시스템 도메인을 시범 적재했다. 위상이 "초안"에서 "시범 검증 완료"로 바뀐다.
아래 실측이 §9 미결 1·3·4의 답이다.

### 11.1 선행 TDD — infer_scope "구체 표면 우선"(§3 결정 2)

엔진 `search.py`의 `infer_scope`를 maximal 규칙으로 교체(엔진 레포 `~/Downloads/codes/project-brain`).
매칭된 컨텍스트 중 그 매칭 표면이 다른 매칭의 진부분집합인 것을 제거하고(maximal만) 센다 — 1개면
단일 특정, 2개 이상이면 None. 합성 red 케이스(§3 표 4행)로 TDD: 핵심 red("고슴도치 방해버블
상태"가 hedgehog·system 둘 다 매칭→다중→None이던 것)가 hedgehog 단일 특정으로 통과. 엔진
test_search 75/75·전체 351/351, 게임 골든셋 s1~s7 7/7 무회귀.

### 11.2 적재물 (ingest 38건 = 신규 객체 35 + 기존 4 갱신, 신규 색인 24행)

- 컨텍스트: `context.disturb-bubble-system` (display_name="방해버블", reviewed)
- 신설 GlossaryTerm 4: `disturb-base-class`(BubbleObjectDisturb)·`disturb-type-range`
  (kMASK_DISTURB_TYPE 500~1000)·`disturb-list`(점수 분류)·`disturb-manager`
- 이주 GlossaryTerm 2: `shootable-bubble-remover`(hedgehog→system)·`cloud-do-pop-on-near-this-pop`
  (drone→system) — id 유지·context_id만 변경(제자리 재소속)
- DomainMapping 6(promote로 reviewed): `class-hierarchy`·`type-range`·**`add-new-disturb-bubble`(확장
  지점 8단계)**·`score-mechanism`·`shootable-remover-classify`·`timing-hooks`
- DecisionRecord 2(이주 사유)·CodeLocator·EvidenceRef·EvidenceManifest. commit_sha=`dadce49d35`(develop).
- 실코퍼스 가드 884→908. 색인 24행 기여 kind = CodeLocator 11+context 1+신설용어 4+매핑 6+결정 2(EvidenceRef 9·Manifest 1·Review 1은 surface.py EXCLUDED_KINDS라 색인 제외). raw 청크 불변. eval 7/7.

### 11.3 baseline 대조 — 시범 성공 판정(§4 의무)

| 질의 | 적재 전(빈손) | 적재 후 |
|---|---|---|
| "신규 방해버블 추가하려면" | 개별 기능 reskin·점수 매핑만, 확장지점 0 | **`add-new-disturb-bubble` 1등** + 시스템 매핑 5개 점령 |
| "방해버블 점수 어떻게" | 개별 기능 score 매핑만 | **`score-mechanism` 최고점**, `disturb-list` 용어 동반 |

빈손이던 가로 질의가 시스템 매핑을 top으로 회수 — 시범 성공.

### 11.4 §9 미결 실측 답

- **미결 1(확장 지점 그릇 + 가로 심볼 귀속)**: 확장 지점은 `DomainMapping`(mapping_key=
  "add-new-disturb-bubble", code_locator 5개)으로 충분 — Q-A 1등 회수, 어색하지 않음. 가로 심볼
  귀속은 **두 패턴**으로 갈렸다: (가) 공유 메커니즘을 통째로 설명하는 매핑이 없으면 시스템에 신설
  (disturbList→`score-mechanism` 신설, 기능 score 매핑은 점수값만 다룸) / (나) 기능 매핑이 이미
  메커니즘 전체를 설명하면 용어만 이주하고 그 매핑이 시스템 용어를 그래프 참조(cloud-do-pop→
  drone `near-pop-propagation` 유지). **규칙: 의미 매핑은 개념 소유 컨텍스트 1곳, 다른 컨텍스트는
  그래프 참조 — 단 "소유 매핑이 어디 있나"가 시스템 신설/기능 유지를 가른다.**
- **미결 3(시스템 표면·명명)**: `context.disturb-bubble-system`/display "방해버블" 확정.
  구체 표면 우선 규칙과 결합해 의도대로 라우팅 — 일반 질의("방해버블 분류")는 시스템으로,
  핀포인트("고슴도치 방해버블…")는 hedgehog로 단일 특정.
- **미결 4(이주 scope 영향)**: ★핵심 실측★. 이주된 용어는 색인 context_id가 system이라
  **scope=기능 하드필터에서 빠진다**. 그래서 기능 핀포인트(scope=hedgehog로 추론되는 질의)에서는
  이주 용어가 사라진다 — `shootable-bubble-remover`는 원래 고아라 이주 후 hedgehog scope에서
  완전히 끊겼다(검증 질의 results 0). **해결=기능 매핑이 시스템 용어를 glossary_term_ids로
  교차 참조**: hedgehog의 `angry-shoot-bubble-removal`에 이주 용어를 연결하니, scope=None/시스템
  질의("화난 고슴도치 슈팅버블 제거 콤보 초기화")에서 기능 매핑·시스템 매핑·이주 용어·이주 결정이
  모두 함께 회수됐다. cloud-do-pop은 drone 매핑이 이미 가리켜 자연히 동반됐다. **트레이드오프 결론:
  공통 개념 이주는 그 개념을 쓰는 각 기능 매핑이 시스템 용어를 교차 참조해야 양쪽(시스템 질의 +
  기능 핀포인트) 회수가 산다. 이주 선행 조건(고아 해소)에 "기능 매핑 교차 연결"을 추가한다.**

### 11.5 부수 발견 (코드 정본 검증 중)

- **DISTURB_BUBBLE_BASE 미사용**: `SCORE_FACTOR_KEY::DISTURB_BUBBLE_BASE`는 enum 정의(ScoreCalculateFactor.h:33)만
  있고 사용처 0. 실제 방해버블 점수는 `disturbList` 순회→서버 config `SCORE_DISTURB_%03d` 주입이다
  (ScoreCalculateFactor.cpp:110-119). 기존 `mapping.disturb-mininest.score` meaning의 "DISTURB_BUBBLE_BASE
  적용" 서술이 부정확(drone·ghost-mirror 매핑은 정확). 시스템 `score-mechanism` 매핑은 정확히 적재.
  **후속: mininest.score 매핑 정정(caveat 또는 supersede) — 별건 큐.**
- **develop 구버전 함정**: brain 브랜치(`b8b91ccc14`)의 게임코드가 develop(`dadce49d35`)보다 72파일
  구버전. 앵커 후보 중 `DisturbManager.cpp`(CLOUD 전파 `setNeedCloudTriggerOnNearPop` 추가)·
  `BubbleObjectDisturb.h`(6줄)만 develop과 다름 — 이 둘은 `git show develop:`로 라인 재확인,
  나머지는 워킹트리=develop. 메모리 "develop 신코드" 함정과 동형. commit_sha는 develop로 통일.
- **검색 게이트 민감도**: scope=hedgehog로 하드필터된 핀포인트("고슴도치 방해버블 슈팅버블 제거")는
  scoped 후보 안에서 점수가 게이트를 못 넘어 needs_clarification(results 0). 이주와 무관한 검색층
  민감도 — scope=None 질의는 정상 회수. 적재 구조 문제 아님(별건 관찰).

### 11.6 남은 일

- **미결 2(동의어 흡수)**: 시범에서 급한 필요 없었음("방해버블"이 도메인 용어와 일치). 1순위 후보
  (용어 synonyms 표면)는 유지하되 P0 실사용 막힘이 트리거.
- **미결 6(절차 게이트)**: (b)안으로 시범 완료(분기 없이 수동 체크리스트). 이제 §6 ingest 시스템
  도메인 분기 + §7 recall 조립 모드 정식화 = **스킬 2종 수정, 사용자 승인 필요**(skill-and-project-files 룰).
- **확산**: 시범이 방식을 검증했으므로, 다음 시스템 도메인(인게임 슈팅·트레이스·바운더리·그룹로직)으로
  확산 가능(실사용 우선).
