# bb2 앵커 골든셋 보강 + synonyms 백필 (데이터레포 동반 플랜)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. 이 플랜은 **bb2 데이터레포**(`<소비 프로젝트 루트>`, 예 `/Users/al03040455/Desktop/bb2_client`)에서 실행한다. 엔진 코드 플랜(`2026-07-06-registry-aware-anchor-gate.md`)의 동반이다. 검증은 합성 단위테스트가 아니라 **실모델 eval·checks**다.

**Goal:** (1) 엔진 앵커 변경을 실코퍼스에서 검증할 안전망(거짓양성 골든셋)을 먼저 세우고, (2) 럭키박스류 엔티티 질의가 게이트를 통과하도록 synonyms를 백필하며(데이터 품질 향상), (3) 새 lint 규칙(최소 3글자·단독 일반명사 금지)에 걸리는 기존 데이터를 정리한다.

**Architecture:** 골든셋(`brain/eval_scenarios.json`)에 미적재 엔티티 no_answer 변형과 럭키박스 진양성을 추가한다. 진양성은 엔진 변경+백필 전까지 red, 후에 green(실코퍼스 TDD). 백필은 컨텍스트 대표 GlossaryTerm에 한국어 대표명을 검수정책 B+C로 넣는 소량 큐레이션(수십 개).

**Tech Stack:** `project-brain` CLI(편집 설치된 엔진), `brain/checks/` unittest, `brain/eval_scenarios.json` 골든셋, 실모델 bge-m3(eval).

## Global Constraints

- bb2는 데이터레포 — 엔진 코드는 이 플랜에서 안 고친다(엔진 플랜 소관).
- 골든셋·checks는 bb2 소유(이 레포에서만 편집). 엔진 레포에 복사본 만들지 않는다.
- synonyms 백필은 **459 전수 번역 금지** — 컨텍스트 대표명만(수십 개), 검수정책 B+C(근거 확실→reviewed 자동, 애매→candidate).
- 백필 표면형은 **최소 3글자·단독 일반명사 금지**(엔진 lint와 동일 규칙). 억지 흔한단어 금지.
- 실모델 eval은 색인 최신이어야 한다 — 색인 영향 변경 후 `project-brain index rebuild` 선행(StaleIndexError 방지).

**레포 간 순서:** 이 플랜 Task 1(골든셋) → 엔진 플랜 Task 1~6 → 이 플랜 Task 2~4(백필·정리·회귀).

---

## Task 1: 거짓양성 골든셋 보강 (안전망 — 엔진 변경 전 선행)

**Files:**
- Modify: `brain/eval_scenarios.json` (scenarios 배열)

- [ ] **Step 1: 현재 골든셋 구조·시나리오 확인**

Run: `cd <bb2 루트> && python3 -c "import json;d=json.load(open('brain/eval_scenarios.json'));[print(s['id'], s.get('expect',{}), '::', s['query']) for s in d['scenarios']]"`
Expected: s1~s12(s8·s10 결번) 출력. no_answer는 s5 하나, s9와 s11 query가 동일(중복)임을 눈으로 확인.

- [ ] **Step 2: s11 중복 제거 — 실제 변형으로 교체**

`brain/eval_scenarios.json`에서 s11의 `query`를 s9와 다른 실제 어휘 변형으로 바꾼다(같은 정답 객체를 다른 표현으로 물음). 예:

```json
{ "id": "s11-projection-reuse-sally-result-ranking",
  "query": "카누 레이스 끝나고 순위표 어떻게 띄워",
  "expect": { ... 기존 기대 유지 ... } }
```

(s9 원문 "샐리 카누 결과 팝업에 전체 레이서 순위를 표시하려면"과 문자열이 달라야 한다.)

- [ ] **Step 3: no_answer 변형 3개 추가 (critic 실모델 확정본)**

미적재 엔티티 + 3글자+ generic 토큰 포함 + 명부 표면형 통째 미등장 + **희소 의문사(언제/어디) 회피**. `expect.no_answer=true`. 아래 3개는 critic bb2 실모델 eval로 results=0·needs_clarification=True 확정 + 메인 독립 재검증 일치:

```json
{ "id": "s13-absent-halloween", "query": "핼러윈 이벤트 보상 뭐였지",
  "expect": { "no_answer": true } },
{ "id": "s14-absent-attendance", "query": "출석 이벤트 보상 뭐야",
  "expect": { "no_answer": true } },
{ "id": "s15-absent-valentine", "query": "발렌타인 이벤트 보상 뭐였지",
  "expect": { "no_answer": true } }
```

★critic가 잡은 함정(메인 재검증 완료)★: 원안 "핼러윈 이벤트 보상 **언제** 지급돼"·"출석 도장 아이콘 **어디** 있어"는 **열린다**(anchor_df 15·7 — 2글자 의문사 '언제'/'어디'가 present 앵커로 살아남아 min을 가져가 통과, 실측 results=5). "뭐였지/뭐야"로 끝내 희소 의문사를 피해야 명부 미매칭+anchor_df>30으로 견고히 차단(s13' 43·s14' 93·발렌타인 93, 전부 results=0). '이벤트'는 3글자 generic이라 옛 2글자 길이필터가 아닌 명부/앵커로 막힘 = 견고성 증거(확정 설계 §2 착수순서 ii).

- [ ] **Step 4: 럭키박스 진양성 1~2개 추가 (엔진+백필 전까지 red)**

```json
{ "id": "s16-luckybox-api", "query": "럭키박스 API 쓰나",
  "expect": { "object_ids": ["mapping.luckybox-contents.luckybox-api-unused"] } },
{ "id": "s17-luckybox-icon", "query": "럭키박스 아이콘 클릭하면 뭐 뜨는지",
  "expect": { "object_ids": ["mapping.luckybox-contents.luckybox-popup-entry"] } }
```

(expect 형식은 기존 시나리오의 진양성 형식을 그대로 따른다 — Step 1 출력에서 확인.)

- [ ] **Step 5: 미적재 전제 실측 확인(추가한 no_answer 엔티티가 진짜 미적재인지)**

핼러윈·출석·발렌타인은 critic가 3겹(표기변이 df=0 / objects grep 0건 / 게이트 우회 recall 흔적 0)으로 미적재 확인 + 메인 재검증(results=0)했다. 착수 시 재확인:
Run: `cd <bb2 루트> && project-brain recall "핼러윈 이벤트 보상 뭐였지"` (및 s14·s15 질의)
Expected: reviewed results 0(needs_clarification). 만약 결과가 뜨면 그 엔티티는 적재된 것 — 다른 미적재 엔티티로 교체(예비 후보도 "~이벤트 보상 뭐였지" 패턴 유지).

- [ ] **Step 6: 색인 재빌드 후 eval — 현 상태 red/green 기록**

Run: `cd <bb2 루트> && project-brain index rebuild && project-brain eval`
Expected: no_answer(s5·s13·s14·s15) green(차단), 럭키박스(s16·s17) **red**(아직 0건 — 엔진+백필 전이라 정상). 이 red가 목표.

- [ ] **Step 7: 커밋 (bb2 레포)**

```bash
cd <bb2 루트>
git add brain/eval_scenarios.json
git commit -m "test(brain): 앵커 골든셋 보강 — s11 중복 교체 + s5류 no_answer 2개 + 럭키박스 진양성 2개"
```

> 여기서 **엔진 플랜(`2026-07-06-registry-aware-anchor-gate.md`) Task 1~6을 먼저 완료**한다. 편집 설치라 엔진 코드 변경은 `project-brain`에 즉시 반영된다.

---

## Task 2: 기존 2자 synonyms 정리 (새 lint 통과 조건)

**Files:**
- Modify: `brain/objects/domain/g.sally-canoe.enter-popup-flow.get-next-level.json`(및 audit가 잡는 다른 위반 파일)

- [ ] **Step 1: 새 lint 규칙 위반 색출**

Run: `cd <bb2 루트> && project-brain audit`
Expected: 엔진 새 규칙으로 `GlossaryTerm synonyms 'NL' too short (min 3)` 류 error. **단독 일반명사(blocklist) 위반은 critic 실측상 0건**(현재 synonyms/aliases에 단독 generic 없음 — lint는 예방용). 걸리는 건 **최소 길이 규칙**뿐이고 getNextLevel "NL"(2자) 1건이 유력 — audit 출력으로 전량 확인.

- [ ] **Step 2: 위반 표면형 제거/교체**

해당 GlossaryTerm의 synonyms에서 2자 항목("NL")을 제거하거나 3자+ 등가어로 교체(예 "NextLevel"·"NextRaceNo"만 남김). 수기 편집이므로 write 층을 건너뛴다 — Step 3의 audit로 재검증한다(프로젝트 CLAUDE.md 주의).

- [ ] **Step 3: audit 재확인**

Run: `cd <bb2 루트> && project-brain audit`
Expected: synonyms 길이/일반명사 error 0.

- [ ] **Step 4: 커밋**

```bash
cd <bb2 루트>
git add brain/objects/
git commit -m "fix(brain): 2자 synonyms 정리(NL) — 게이트 통과권 최소 3글자 규칙 준수"
```

---

## Task 3: 컨텍스트 대표명 synonyms 백필 (데이터 품질 향상, 소량 큐레이션)

**Files:**
- Modify: `brain/objects/domain/*.json` (각 컨텍스트의 대표 GlossaryTerm)

- [ ] **Step 1: 백필 대상 선정 — 컨텍스트별 대표 엔티티명**

Run: `cd <bb2 루트> && python3 -c "import json,glob;[print(json.load(open(f))['id'], json.load(open(f)).get('display_name')) for f in glob.glob('brain/objects/domain/context.*.json')]"`
Expected: DomainContext 27개 display_name 목록(깨끗한 한국어 — "럭키박스 구성품 표시", "방해버블" 등). 각 컨텍스트에서 사용자가 그 기능을 부르는 **대표명 1~3개**를 뽑는다(럭키박스 컨텍스트 → "럭키박스"). 흔한 일반명사·2자 제외.

- [ ] **Step 2: 럭키박스부터 백필(골든셋 진양성 대상)**

럭키박스 컨텍스트의 대표 GlossaryTerm(예 `g.luckybox-contents.popup-luckybox-info`)의 synonyms에 "럭키박스" 추가. `updates[]` union 문법(덮어쓰기 아님) 또는 수기 편집 후 audit. 근거가 확실하면 reviewed 유지(검수정책 B).

- [ ] **Step 3: 나머지 컨텍스트 대표명 백필(수십 개)**

Step 1에서 뽑은 대표명을 각 컨텍스트 대표 GlossaryTerm synonyms에 추가. 근거 확실→reviewed(B), 애매→candidate(C). 전수 아님 — 컨텍스트당 1~3개.

- [ ] **Step 4: audit로 규칙·enum 재검증(수기 편집 태우기)**

Run: `cd <bb2 루트> && project-brain audit`
Expected: error 0(최소 3글자·단독 일반명사·redaction enum 전부 통과).

- [ ] **Step 5: 커밋**

```bash
cd <bb2 루트>
git add brain/objects/
git commit -m "feat(brain): 컨텍스트 대표 엔티티명 synonyms 백필(럭키박스 외) — 게이트 통과권 데이터 품질"
```

---

## Task 4: 실모델 회귀 — 럭키박스 열림 + s5 차단 실측

**Files:** 없음(검증만).

- [ ] **Step 1: 색인 재빌드(백필로 surface 바뀜)**

Run: `cd <bb2 루트> && project-brain index rebuild`
Expected: 성공(수십 초, 실모델).

- [ ] **Step 2: 실측 가드(checks)**

Run: `cd <bb2 루트> && python3 -m unittest discover -s brain/checks -p "test_*.py"`
Expected: 전부 통과.

- [ ] **Step 3: 골든셋 eval — red→green 확인**

Run: `cd <bb2 루트> && project-brain eval`
Expected: **럭키박스 s16·s17 green(열림)** + no_answer s5·s13·s14·s15 green(차단 유지) + 기존 s1~s12 회귀 0. Task 1 Step 6의 red가 green으로 뒤집혔는지 대조.

- [ ] **Step 4: 럭키박스 직접 확인(눈으로)**

Run: `cd <bb2 루트> && project-brain recall "럭키박스 API 쓰나"`
Expected: reviewed results 비어있지 않음(luckybox 매핑 상위). 변경 전 0건 → 후 결과 있음.

- [ ] **Step 5: 회귀 결과를 엔진 커밋 메시지/문서에 기록**

럭키박스 열림 + s5 차단 실측 요약을 엔진 레포 `docs/plans/2026-07-03-deferred-items-and-anchor-decisions.md` §2 검증 상태에 "구현 후 실측" 한 줄로 추가(엔진 레포에서 커밋).

---

## Self-Review

- **Spec 커버리지(확정 설계 §2 착수순서 대비):** 골든셋 s11 중복교체(Task1 S2)·3글자+ no_answer 변형(Task1 S3)·럭키박스 진양성(Task1 S4) ✓ / 백필=컨텍스트 대표명 소량(Task3) ✓ / 2자 synonyms 정리(Task2, 새 lint 통과) ✓ / 실모델 회귀=럭키박스 열림+s5 차단(Task4) ✓.
- **레포 순서:** 골든셋(안전망) → 엔진 → 백필·정리·회귀. red→green 실코퍼스 TDD 성립.
- **미룬 것 없음:** 확정 설계의 데이터레포 몫을 전부 task로. 잔여 위험(우연한 표면형 통째 포함·2자 단독 엔티티명 df폴백)은 골든셋 감시 대상으로 §2에 문서화됨.
