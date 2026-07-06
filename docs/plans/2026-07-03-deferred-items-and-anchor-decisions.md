# 미결 항목 일괄 결정 + 앵커 게이트 근본 방향 (2026-07-03)

- 상태: **일부 실행 완료 / 앵커는 구체 설계 확정(2026-07-06 전수조사 → critic 2라운드 실측 → 메인 독립 재검증)·구현 대기(bb2 골든셋 선행)**
- 발단: 사용자가 "럭키박스 앵커 + ROADMAP 미뤄둔 목록 + 발견3(결정 근거 어휘)을 전부, 미루지 말고
  근본 해결안으로 결정한다. '트리거 생기면 한다' 식 열린 보류 금지"를 요구.
- 방법: 항목별 병렬 분석(워크플로우 16 에이전트) → 메인 코드 재검증 → surface:104 brain(critic) 2라운드
  검수(1차 조건부 승인 + 재작업 3건, 2차 [OKAY]). critic는 bb2 실코퍼스(3156객체)에 직접 질의해 검증.
- 인용한 file:line은 2026-07-03 스냅샷.

## 프레임 — 지시와 가드레일의 양립

사용자 지시("전부 근본 해결")와 Karpathy 가드레일("요청 안 한 투기적 기능·추상화 금지")은
**"미루지 말고 결정"을 "지금 코드를 다 만들라"로 읽으면 충돌하고, "트리거 대기라는 열린 보류를 확정
결론으로 바꿔라"로 읽으면 양립**한다. 그래서 결함만 지금 고치고, 기능·정책·헛일은 "안 만든다"를
근거 대고 종결한다. "안 만들기로 지금 결정"과 "트리거 생기면 본다"는 다르다 — 앞은 확정, 뒤는 열림.

---

## 1. 지금 고친 진짜 결함 (실행 완료 — 엔진 합성 545 통과)

### 결함 A — router `_restricted_for` fail-open (신뢰 게이트가 열려 있었다)
- 증상: `router.py:764`가 `redaction_status not in (None, "approved")`라 **None(키 누락)을 통과**시켰다.
  `schema.py:87-89` 주석은 "`_restricted_for`가 'approved'만 통과시키는 화이트리스트"라 서술 — **주석
  의도와 코드 불일치.** 수기 manifest가 키를 누락하면 lint 전 창에서 미승인 근거가 reviewed로 신뢰
  오표시(지난 "none" 사고의 정반대 방향).
- 수정: `!= "approved"`로 fail-closed. 정상 데이터는 redaction_status가 필수·enum이라 None은
  비정상 상태 — 의심스러우면 막는 쪽(프로젝트 원칙 "거짓양성 > 거짓음성").
- 테스트: `tests/test_router.py::TestRestrictedForFailClosed` 3종(approved 통과 / 누락·비승인 restricted).
- bb2 영향: bb2는 전량 approved(2026-07-02 정리)라 restricted 판정 불변(0→0 기대). **회귀로 실측 확인 필요.**

### 결함 B — 발견3: 결정 근거(decisions[].evidence) 어휘가 commit/jira/pr로 좁음
- 재분류 근거: 1차엔 "결함 아님"이었으나(실수요 0 전제), **기획서→구현 이후 최초와 달라지는 변경
  (Jira 개선·Slack 기획요청·기획서 개정)이 '결정'이 되고 그 근거가 Slack/spec/wiki인 경우가 실재**한다.
  특히 `spec_reflected=no`(schema.py) 결정은 commit 근거 자체가 없다. 우회로(extra_objects 손발행)는
  자동조립 편의를 다 버려 정상 흐름의 걸림돌 → 전제가 깨졌으니 결론을 뒤집는 게 정직하다.
- 저위험 확인: 스키마 `REF_TYPE_VALUES`(schema.py:82-84)가 이미 slack_thread·spec_section·wiki_section
  지원. 커밋 외 타입은 이미 노트가 locator 제공(assembly.py:129·validate_notes:378) — 새 규약 발명 불필요.
- 수정: `_DECISION_REF_TYPE`(assembly.py:106)에 `slack→slack_thread`·`spec→spec_section`·`wiki→wiki_section`
  추가 **+ `validate_notes`의 하드코딩 튜플 `("commit","jira","pr")`을 `_DECISION_REF_TYPE` 키 참조로 변경**
  (critic가 잡은 오류 — dict만 고치면 1층에서 계속 거부됨). 딱 3개만, 무한 확장 아님(밖 타입은 여전히 거부).
- 매핑 granularity 실측(critic, bb2): spec_section 116·spec_slide 47·wiki_section 64·slack_message 7·
  slack_thread 2. slack→slack_thread는 실데이터 다수파(message)와 다르나 jira→jira_issue 선례처럼
  "대표 단위" 철학으로 일관. message 단위가 필요하면 extra_objects로(기존 규약). 엔진이 locator 내용을
  안 읽으므로 동작 차이 없음.
- 테스트: `tests/test_assembly.py` slack/spec/wiki 수용·빌드 + 밖 타입 거부 2종.

### 운영 규율 (코드 무변경)
- CLAUDE.md 주의 절에 "raw/manifests 수기 편집 후 `project-brain audit` 필수" 추가. enum 검증은
  write(save_object) + lint_store 전수 두 층인데 수기 편집은 write를 건너뛰므로 audit로 태워야 잡힘.

---

## 2. 앵커 게이트 거짓음성 — 근본 방향: "엔티티 명부 기반" (설계 확정, bb2 선행 대기)

### 문제 (2026-06-30 plan에서 이월)
잘 적재된 럭키박스 질의("아이콘 클릭하면"·"API 쓰나")가 results 0건. 원인: `anchor_df=min(개별 present
토큰 df)`(search.py:645), "럭키"·"박스"가 흔해져(>30) 차단. `_ANCHOR_DF_MAX=30`은 코퍼스 크기 무관 절대상수.

### 왜 빈도 조정 4안이 전부 탈락인가 (실측)
1. **상대 문턱(df÷N, IDF류)**: 흔한 토큰 df는 코퍼스 크기 N에 비례하지 않음(도메인 종속). 럭키 df41과
   s5 보상 df(코드 주석 52, critic 실측 현재 93 — 오히려 논증 강화)가 좁아, 럭키 열고 s5 막는 단일 비율이
   실제 코퍼스 크기 어디서도 성립 불가.
2·3. **bigram 인접쌍**: min이 질의의 모든 인접쌍을 훑어, 미적재 엔티티 질의('크리스마스 보상 지급')의
   generic 인접쌍('보상 지급' — 워크플로우 주장 df18은 허위, critic 실측 df3)이 통과 → s5 거짓양성 재도입.
   (워크플로우 적대 agent의 "mecab이 '이벤트'를 '이/벤트'로 분해" 주장도 허위 — 삭제.)
4. **절대 상향(30→41)**: critic 실측 — MAX 41~92는 기존 골든셋 7종 전부 통과하나 s5 변형
   '크리스마스 보상 지급'(anchor_df 34 실측)이 뚫림 → **기존 골든셋만으론 거짓 인증.**

### 근본 방향 (사용자 통찰 → critic 검증)
빈도(df)는 "엔티티가 코퍼스에 있나?"의 조잡한 대용품이다. 우린 **엔티티 명부(GlossaryTerm·DomainMapping)**를
직접 가졌으니, 앵커가 "질의가 아는 엔티티와 매칭되나?"를 확인하면 된다.
- 장점: (1)근본 직격, (2)크리스마스는 명부에 없어 여전히 차단(거짓양성 유지), (3)**빈도 무관이라 코퍼스
  성장에 안 무너짐**(4안 전부 실패한 근본 원인 제거).
- 코드 사실: 앵커(compute_query_signals, search.py:619-647)는 지금 glossary/mapping을 **전혀 참조 안 함** —
  tokenize+df만. 기존 동의어 기능은 검색엔 도움되나 앵커엔 무효(질의가 쪼개짐).
- 전제 실측(critic): bb2에 럭키박스 노드 실재 — DomainMapping 8개 + GlossaryTerm 1개. s5 통째매칭 안전
  ('보상'·'이벤트' 단독 term 없음, 전부 복합명 25개).

### 확정 설계 (bb2 전수조사 → critic 2라운드 실측 → 메인 독립 재검증, 2026-07-06)

전수조사(GlossaryTerm 459·DomainMapping 364·DomainContext 27, 메인 직접 jq/python): 골격 필드는
100% 채워졌으나 term 네이밍은 규칙 부재(순수영문 234·한국어 139·병기 58·혼합 등), synonyms/aliases는
6/459만 채움(채운 6건은 규칙 준수). "럭키박스" 단독 표면형은 명부 어디에도 없음(term 1건도 "럭키박스
info 아이콘"으로 구문에 묻힘). 이 실측 위에 18개 조합(명부필드 F1~F3 × 매칭방향 D1/D1n/D2/D3) 매트릭스로
확정. 미해결 3질문(매칭 방향·명부 집합·df 폴백)이 전부 실측으로 결정됨:

- **명부 = F1 (GlossaryTerm term+synonyms+aliases)만.** DomainContext display_name·DomainMapping
  title/canonical을 넣어도(F2/F3) 안전 방향 D1에선 결과 불변(굵은 구문은 질의에 통째로 안 들어감) +
  표면형만 466→1221로 부풀어 조각 방향 누수만 커짐 → 기각. 럭키박스는 백필이 필수 경로.
- **매칭 방향 = D1** (명부 표면형이 질의 원문에 통째 부분문자열로 등장, 대소문자 무시, 표면형 길이 3+).
  조각 매칭(D2/D3)·토큰 df 접근은 전부 s5 재도입으로 기각 — generic '이벤트'(102개 표면형) 조각이
  크리스마스 질의를 대신 열어버림. 토큰 수준은 명부 kind로 좁혀도 럭키36·박스37(>30), 존재판정이면
  보상89·이벤트168이 걸려 실패. **문자열 통째 매칭(D1)만 s5를 안 뚫음**(빈도조정 기각의 명부 버전 확장).
- **폴백 = OR 보강. 게이트 = `명부 D1 매칭 OR anchor_df≤30 → 통과`.** 완전 대체는 기각(D1 명부 매칭이
  양성 골든 4/9만 열어 s3·s7·s9·s11·s12 서술형 질의 5개 즉사). 보강은 단조 완화라 기존 통과 질의 회귀 0.
- **백필 = 컨텍스트 대표명 소량 큐레이션(수십 개, 검수정책 B+C).** definition 자동 추출은 기각(definition은
  100% 한국어지만 서술문이라 '버블'·'이벤트' generic 명사가 섞여 D1 표면 오염 → s5 문 열림). DomainContext
  display_name(깨끗한 한국어)을 단서로 컨텍스트당 대표 엔티티명 1~3개를 그 컨텍스트 대표 GlossaryTerm
  synonyms에. 459 전수 번역 아님.
- **적재 규칙 보강**: "한국어 표면형 있으면 synonyms에" + 이 설계로 synonyms가 "검색 리콜 보조"에서
  **"게이트 통과권"으로 승격**되므로 **단독 일반명사 금지·최소 3글자** 제약을 적재 규칙과 lint 양쪽에 박음
  (누가 "이벤트"를 synonyms에 넣는 순간 D1이 뚫림).
- **배관 1단계**: `compute_query_signals`(search.py:619)에 store(또는 표면형 목록)를 내려야 D1 가능
  (색인은 term 평탄화 저장이라 db_path만으론 불가; eval_recall은 이미 store 받음 search.py:682-683).
  색인에 표면형 테이블을 굽는 대안은 stale 관리 증가로 비추천.

### 착수 순서 (TDD — 채점표 먼저, bb2 데이터레포)
1. **bb2 거짓양성 골든셋 보강** (스펙 확정): (i) s9==s11 완전중복 → s11 실변형 교체, (ii) no_answer가
   s5 하나뿐 → **3글자+ generic 토큰('이벤트' 등) 포함하되 명부 표면형 통째 미등장**인 미적재 엔티티 변형
   2~3개 추가('크리스마스 보상 지급'류는 '보상/지급' 2글자가 길이필터에 잘려 차단된 취약 사례라 견고성
   증거가 안 됨), (iii) 럭키박스 진양성 1~2개. **채점표 자체는 앵커를 안 고침 — 안전한 변경을 찾게 해주는 도구.**
2. 백필(수십 개) + 앵커 코드(F1·D1·OR 보강·store 배관) 구현 → 실모델 eval로 럭키박스 열림+s5 차단 검증.

### 검증 상태 (메인 독립 재실행 2026-07-06)
- 18조합 매트릭스 재현: D1/D1n만 block 질의 무누수, 나머지 전부 generic '이벤트*' 표면형으로 s5·크리스마스 누수.
- 백필 시뮬(럭키박스 synonyms 1개 추가): F1×D1이 럭키박스 질의 2개 열림(T,T) + 크리스마스 3개 차단 유지(F,F,F).
- 게이트 우회 recall(실모델 bge-m3): 럭키박스 질의 top5 전부 luckybox 객체(1위 0.031, reviewed 바닥의 6배),
  eval_recall은 results=0·raw_excerpts=5·needs_clarification로 증상 재현 → **차단 지점이 게이트 하나뿐**을 실증.
- s5 "크리스마스 이벤트 보상" anchor_df=93(>30) → df·명부 양쪽 실패로 차단 유지. 원시자료·판정 전문:
  critic-anchor-verdict.md(scratchpad), critic 서브에이전트 스크립트(measure_bb2·02_sim·task2·task3).
- 잔여 위험(골든셋 감시, 설계 기각 사유 아님): 미적재 엔티티가 우연히 명부 표면형 통째 포함 시 D1 오열림 /
  2글자 단독 엔티티명은 df 폴백만.
- **알려진 기존 게이트 한계(이번 스코프 밖, 명부 개편과 무관 — critic 2026-07-06 실측 발견):** "미적재
  엔티티 + 희소 의문사('언제' df15·'어디' df7)" 질의는 현행 게이트도 뚫린다(2글자 의문사가 present 앵커로
  살아남아 min을 가져감, `_ANCHOR_MIN_TOKEN_LEN=2`). 예 "핼러윈 이벤트 보상 언제 지급돼"→results=5(실측).
  이번 앵커 작업은 이걸 안 고친다(별개 이슈) — 골든셋 no_answer는 의문사 회피형("~뭐였지")으로 짠다.
- 부수 관찰: mecab-ko가 '이벤트'를 문맥에 따라 ['이벤트'](df187) 또는 ['이','벤트'](벤트 df43)로 다르게
  분절 — 앵커 토큰명이 문맥 의존적(두 갈래 다 30 초과라 이번 판정엔 무영향).
- 데이터레포(bb2) 의존: 골든셋·백필은 bb2 소유라 엔진 단독으로 완결 불가.

### 구현 완료 실측 (2026-07-06, feat/registry-anchor-gate)
확정 설계대로 구현·검증 완료. 엔진 7커밋(registry_match: `_gate_pass` OR 보강 → `compute_query_signals`
신호+`_registry_surfaces` → `eval_recall` store 배관 → schema lint synonyms/aliases 게이트 통과권 규칙 →
적재 스킬/내부 문서). 엔진 합성 556 통과. bb2 5커밋(골든셋 보강 + NL 정리 + 럭키박스 백필 + 타겟 대표명
백필 6컨텍스트 + 가드 갱신).
- **럭키박스 거짓음성 해소 실측**: 실모델 eval 15/15 — s16·s17(럭키박스 진양성) red→green, s5·s13·s14·s15
  (미적재 no_answer) 차단 유지, s1~s12 회귀 0.
- **백필은 실측 기반 타겟팅**: 27개 컨텍스트 중 이름이 흔한-토큰으로만 이뤄져 핵심 질의가 게이트에 막히던
  6개(볼셀렉·방해버블·고슴도치·인게임로직·인게임뷰·메인맵)만 백필. 나머지는 자연어 질의로 이미 도달해 제외
  (플랜의 "수십 개" 대량 백필 가정을 실측이 축소 — 저가치 churn·거짓열림 표면 증가 회피).
- 잔여(스코프 밖): bb2 `raw_chunks` 가드는 로컬 untracked `raw/sources/jungle-rush/`로 346(커밋 코퍼스
  기준 317)이라 실패하나 이번 작업 무관(건드리지 않음).

---

## 3. 안 하기로 확정 종결 (결함 아님 — 기록만, 추후 알 수 있게)

각 항목은 "결함 아님 + 착수 조건"으로 닫는다. 열린 트리거 대기가 아니다.

- **재랭커·top-K 재조정**(ROADMAP §1): 크로스인코더 코드 0건. 관측된 회상실패(럭키박스)는 순위가 아니라
  anchor_df 문제라 재랭커로 못 고침. 착수 조건 = s8(scope-None) 골든셋 red 선행.
- **L5 개인 메모리**(§2): 엔진 L5 코드 0줄. 개인 메모리는 auto-memory·handoff·vault task가 담당
  (session-ingest/SKILL.md가 경계 명시). 지금 만들면 4번째 중복 저장 레인.
- **세션 종료 hook**(§3): 형태·시점 미설계, session-handoff+auto-memory와 역할 중복.
- **팀 승격 권한**(§4): policy. 협업자 0명이라 권한 게이트가 no-op. 현행(자유 reviewer, 무게약 승격) 유지.
  팀 공개 결정 시 projection-reuse spec 정책A(cli ingest 승격 우회) 관찰을 설계 입력으로.
- **Part B locator 마이그레이션**(§5): 이미 "영구 보류 + 트리거(좌표 읽는 기능)"로 확정된 건. line_start/end
  read-path 0건이라 실익 0, ~45건 구조 불가. **이번 논의에서 재론하지 않음(그대로 유지).**
- **슬래시 커맨드**(§6): policy. 스킬 4종 description 자동트리거 + CLI 17서브커맨드로 전기능 호출됨.
  pkm 슬래시도 "스킬 써라" 위임 래퍼일 뿐. 두번째 호출표면은 중복.
- **stale 자동화 Step 3**(§7): 감지→라벨→advisory→수동해소 4단계 실재, 수동으로 충분. "자동 supersede
  초안"은 검수정책 B+C(완전 자동 supersede 금지)와 상충 — 착수해도 "확실-불변 자동 mark-checked +
  나머지 candidate"까지로 범위 한정.

---

## 4. 검증
- 엔진 합성 545 통과(기존 540 + 신규 5: router fail-closed 3 + 발견3 2). 메인이 직접 실행.
- surface:104 brain(critic) 2라운드 검수: 최종 [OKAY]. critic가 워크플로우 서브에이전트의 허위 수치 2건
  (보상 지급 df18→3, mecab 이/벤트 분해)과 내 브리핑 오류 1건(validate_notes 하드코딩 튜플)을 실측으로 잡음.
- **미완(bb2 데이터레포)**: 결함 A 회귀(restricted 0→0 diff 커밋 메시지에) + 앵커 골든셋 보강(2절 착수 순서 1번).
