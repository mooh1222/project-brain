# BB2 Brain 갱신 메커니즘 정리 + 세션24 후속 작업 계획

> **For agentic workers:** 이 계획서가 다음 세션의 **작업 순서 단일 출처**다. 코드 작업(Task 7 골든셋)만 테스트 우선(TDD)이고, 나머지는 문서 정리·실측·검증이라 체크리스트다. 통짜 TDD를 욱여넣지 않는다. 실행은 `superpowers:executing-plans`로 Task 단위.

**Goal:** 이어서24 세션 점검에서 드러난 "갱신 메커니즘 개념 혼선"을 한 곳에 정리하고, 스킬/문서의 진짜 갭만 보강하고, 다음 실제 작업(갈래2 위치 층 실측 등)을 다음 세션이 막힘없이 잇도록 단일 계획서로 박는다.

**Architecture:** brain은 2-레포다 — 게임 레포(`bb2_client`)에 데이터(`brain/`)·스킬·이 계획서, 엔진은 별도 레포(`~/Downloads/codes/project-brain`, `project-brain` CLI). 이 계획은 코드 개발이 거의 없다. 대부분 문서 정리·실측·검증이고, 코드 작업은 골든셋 시나리오 추가 1건뿐이다.

**Tech Stack:** `project-brain` CLI (ingest/index/eval/search), vault task(마크다운), brain 객체(JSON), 골든셋(`brain/eval_scenarios.json`).

---

## 이 계획이 나온 경로 (세션 이력·근거)

다음 세션이 "왜 이렇게 정해졌나"를 거슬러 보려면 아래 세션 기록을 본다.

- **점검 대상 세션 = 이어서 24** (`f1f4b0fd-2734-4a8d-a13c-f1e9423a7398`, 2026-06-12~13)
  - 경로: `~/.claude/projects/-Users-al03040455-Desktop-bb2-client/f1f4b0fd-2734-4a8d-a13c-f1e9423a7398.jsonl`
  - 핵심 메시지(`msg [N]` = 그 세션 트랜스크립트 순번):
    - `[19]` 작업 A(스킬 정식화) 선택 → `[68][74]` writing-skills RED(맨몸 실패) 과적용 인정 → `[79][82]` recall §7 정식화 → `[101~109]` 용어 "개념 단위" 정정 → `[114~120]` ingest §6 정식화
    - `[146]` recall 근거문서(ops-layer §2) 충돌 없음·새 설계문서 안 만듦 → `[170][174]` 후순위 단계 구분 정정
    - `[175][185]` "위치 갱신 = 기존 CodeLocator 객체 제자리 수정" 답변
    - `[186][204]` 고슴도치 cloud 수정 develop 머지 트리거 확인(`8618ead3bb` / develop `45c1f12aed`)
    - **`[265]` 헤맨 부분·엔진/스킬 수정 체크 + 이어서22 lint·백필 정리** ← 사용자 점검 요청
    - **`[277]` "갱신 대상 찾기 명령" 미구현 갭 확인 / `[285]` 대상 알아서 update-rules로 / `[292]` 진행중 개발·개선수정 ingest 표준 흐름** ← 개념 정리 1·2번의 출처
    - `[295~340]` 고슴도치 supersede 7객체 적재 실행·검증·커밋 `e12cd63108`
- **점검 세션 = 이번** (`6549650c-73c9-4fb2-9905-f20baad1511b`, 2026-06-13)
  - 워크플로우 `wvzxefnj7`(5청크 정밀 추출 + 핸드오프 대조)로 누락 점검
  - 직접 검수: `project-brain` 엔진 `lint.py`·`schema.py`, `object-model.md` 실물 확인 → 서브에이전트 주장 검증, 정정 2건(아래)
- **점검 결론 한 단락:** 이어서24의 실행(스킬 정식화·고슴도치 supersede)은 task에 정확히 반영됐다. 그러나 사용자가 헷갈려 다시 설명받은 **개념(적재 흐름·린트 정체·백필vs대체)이 핸드오프에서 빠졌다.** 이 계획서가 그 빠진 개념을 담고, 다음 작업을 잇는다.

---

## 배경 — 갱신 메커니즘 개념 (다음 세션이 또 헷갈리지 않게)

> 이게 이어서24 핸드오프에서 빠진 것. 사용자가 `[27][32][35][40]`에서 물어 정리받았으나 작업 큐에만 신경 쓰느라 task에 안 남았다. 여기를 단일 출처로 둔다.

**1. 진행 중 개발·개선 수정을 brain에 적재하는 표준 흐름** (출처: 세션 f1f4b0fd `[292]`)

가장 흔한 실제 흐름(예: 완성한 A 기능을 베타 점검 중 개선 수정 → 그 세션에서 적재). 순서는 **추출 → 기존 객체 찾기 → 갱신 방식 판정 → 저장**:

1. **추출** — 이번에 무엇이 바뀌었는지 지식으로 뽑는다 (내가 고쳤으니 무엇이 바뀐지 안다).
2. **기존 객체 찾기** — 그 지식에 해당하는 객체가 brain에 이미 있는지 `project-brain search`로 찾는다.
3. **갱신 방식 판정** — `update-rules.md` 분기표로 정한다.
   - 의미가 바뀜 → **대체** (옛 매핑 status를 `superseded`로 막고 새 매핑으로 잇기)
   - 값(숫자·설정값)이 바뀜 → 변경 사건 기록 + 새 사실값 한 묶음
   - 위치·줄번호만 바뀜 → 그 자리에서 고치기(제자리 수정)
   - 아예 없던 새 개념 → 새로 만들기
   - 원인이 있으면(예: 점검 중 개선) → 결정 기록(`decision_type=improvement`) 연결
4. **저장** — 만든 묶음을 `ingest`가 검사·저장 + 색인 다시 만들기.

핵심: **`ingest`는 '저장'만 한다.** '기존 객체 찾기'와 '어떻게 갱신할지 판정'은 사람(에이전트)이 `update-rules`로 한다. 그리고 2번 '찾기'는 엔진이 전체를 자동으로 훑는 게 아니라, **자기가 고친 범위를 알고 그 단어로 검색**하는 것. (해당 기능이 brain에 안 들어가 있으면 검색이 비니 그냥 새로 만든다.)

**2. 린트(lint)의 정체** (출처: `[265][277]`, 이번 세션 `lint.py` 직접 확인)

린트는 보통 "규칙 어긴 곳·오류를 찾아 알려주는 검사"가 맞다. brain의 린트도 그 계열인데, **검사 대상이 "brain에 저장된 객체들끼리 안 맞는 곳"** 이다 (`lint.py` 직접 확인):

- 끊긴 연결(dangling): A가 가리키는 B가 brain에 없음
- 모순(conflict): 같은 주제+서술인데 값이 다른 검토완료 사실이 둘 이상
- 대체 일관성: 대체된 옛 매핑이 아직 `reviewed`로 남음
- 안 따라간 갱신: 결정이 매핑에 영향을 주는데 매핑이 아직 반영 안 함 → "검토 필요" 신호

**결정적: 린트는 게임 코드(`.cpp`)를 절대 안 읽는다.** brain 안에서만 본다. 그리고 **별도 명령이 아니라 `ingest`·`promote` 안에서 저장 직전에 도는 내부 검사**다(`cli.py:136`·`218`).

**3. '빈 칸 채우기(백필)'와 '대체(supersede)'는 다른 일** (출처: `[265]`)

| | 무엇이 바뀌나 | 처리 |
|---|---|---|
| 이어서22의 commit_sha 348개 채우기 | 의미 그대로, 빈 칸(기준점)만 | **제자리 수정** (필드 채우기, 새 객체 안 만듦) |
| 이번 cloud 수정 | 매핑 의미가 '누락'→'복어와 같음' | **대체** (옛 매핑 막고 새 매핑) |

기준 한 줄: **의미가 바뀌면 대체, 안 바뀌면 제자리 수정.** (`update-rules.md` 분기표의 서로 다른 줄)

**4. 위치 갱신은 '제자리 고치기'다 — 대체 아님** (출처: `[175][185]`, 이번 세션 `update-rules.md` 확인)

코드 위치 객체(CodeLocator)는 라인이 밀려도 객체를 갈아끼우지 않고 그 자리에서 줄번호만 고친다. **대체(supersede) 장치는 매핑·사실 전용이고 CodeLocator엔 없다**(`update-rules.md` "스냅샷 갱신=제자리 수정" 줄). `object-model.md` 153줄 철학: 라인은 조사 당시 스냅샷일 뿐, 앵커의 본질은 경로+심볼이라 라인이 어긋나도 찾아진다. → Task 4가 이걸 실측한다.

**5. "갱신 대상 찾기" 검사(큐)의 정체** (출처: `[277]`, 사용자가 1번 린트로 떠올린 것)

사용자가 원한 **"저장된 객체 중, 코드가 바뀌어서 갱신해야 할 게 있는지 찾기"** 는 코드와 brain을 맞대보는 일 — 지금 린트가 안 하고, **그런 기능이 아예 없다.** 이건 개발 대상이 맞고(= Task 5), 지금 있는 린트를 고치는 게 아니라 새 검사를 추가하는 것이다. 이름(코드 동기화 린트/별도 명령)은 정하기 나름. 실사용 우선으로 보류 중이고, **Task 4 갈래2 실측이 그 첫 설계 입력**이다.

---

## 작업

> 권장 순서: Task 1(계획서 완성 직후 vault 갱신) → Task 2 → Task 4(갈래2, 권장 1순위) → Task 5(Task 4 결과로 판단) → Task 6 → Task 7. Task 3은 검수로 이미 결론남(보강 불필요).

### Task 1: vault task를 이 계획서 가리키게 갱신 — 세션 트리거 놓치지 않게

**Files:**
- Modify: `~/Desktop/vault/tasks/active/bb2-project-brain-build.md`

**왜:** 다음 세션이 이 계획서를 안 열면 전부 무용지물. 포인터를 두 곳(vault task 시작점 + 다음 세션 시작 프롬프트)에 둬서 한쪽을 놓쳐도 다른 쪽이 잡게 한다. SessionStart hook이 active task 목록을 자동 주입하므로, task만 active면 자동 노출된다.

- [ ] **Step 1: "🔶 다음 세션 시작점" 헤더를 14차로 갱신하고 계획서를 1순위로 박기**
  - 헤더 문구에 `docs/superpowers/plans/2026-06-13-bb2-brain-update-mechanism-followup.md`를 1번으로 명시
  - "★작업 순서·개념의 단일 출처 = 이 계획서★ (이어서24 개념 정리는 계획서로 이관됨)" 한 줄 박기
- [ ] **Step 2: "관련 문서" 표에 이 계획서 행 추가** (카테고리 plan, 갱신 트리거 "후속 작업 진행/완료")
- [ ] **Step 3: 이어서24 단락에 "개념 정리는 계획서로 이관" 포인터 한 줄** — 같은 내용이 task·계획서 두 곳에 흩어지지 않게(중복 방지)
- [ ] **Step 4: 검증** — `grep -n "2026-06-13-bb2-brain-update-mechanism-followup" ~/Desktop/vault/tasks/active/bb2-project-brain-build.md` 로 시작점·관련문서 두 곳에 경로가 들어갔는지 확인
- [ ] **Step 5:** vault 변경이라 커밋은 평소대로 분리 (brain 데이터 커밋과 섞지 않음)

### Task 2: dev-ingest.md (가) 3단계에 "추출→찾기" 앞단계 보강 [사용자 승인됨]

**Files:**
- Modify: `.claude/skills/bb2-brain-session-ingest/references/dev-ingest.md`

**왜:** 배경 개념 1번(적재 표준 흐름)이 문서에도 빠져 있다. 현재 (가) 3단계는 "갱신: update-rules 분기표" 한 줄이라 "추출→기존 객체 찾기" 앞단계가 없다. 세션 f1f4b0fd `[292]`에서 정리한 흐름을 문서에 박는다. (스킬 파일은 git 추적 밖 — `.agents/skills/` symlink 자동 반영, 커밋 불필요.)

- [ ] **Step 1: 현재 3단계 문구 확인** — `dev-ingest.md`의 "3. **갱신** (값·구조가 바뀔 때): references/update-rules.md 분기표." 줄
- [ ] **Step 2: 3단계를 아래로 교체**

```
3. **갱신** (이미 있는 걸 고칠 때 — 가장 흔한 흐름): **추출(뭐가 바뀜) → `search`로 기존 객체
   있는지 찾기 → references/update-rules.md 분기표로 처리 판정**. ingest는 '저장'만 한다 —
   '찾기'와 '판정'은 에이전트 몫. '찾기'는 자동 전수조사가 아니라 **자기 수정 범위를 알고 그
   단어로 search**하는 것(개발자는 자기가 뭘 고쳤는지 안다). 기존 객체가 없으면(search 0건)
   그냥 신설. 점검·개선 수정이면 원인이 있으니 DecisionRecord(decision_type=`improvement`) 연결.
```

- [ ] **Step 3: symlink 반영 확인** — `grep -c "추출(뭐가 바뀜)" .agents/skills/bb2-brain-session-ingest/references/dev-ingest.md` 가 1이면 반영됨
- [ ] **Step 4:** 커밋 불필요(git 추적 밖). 다음 세션이 이 흐름을 그대로 쓸 수 있는지만 확인

### Task 3: ReviewRecord verdict — 검수 결과 "보강 불필요"로 종결

**왜:** 이어서24와 서브에이전트가 "`object-model.md`에 verdict 허용값(approved 등)이 빠짐 → 보강 후보"라 했으나, 이번 세션에 `schema.py`를 직접 보니 **틀렸다.**

- `schema.py:14` ReviewRecord 필수 필드 = `(reviewer, reviewed_at, verdict)` — verdict는 필수
- `schema.py:218~223` enum 검증은 `review_type`·`review_scope`에만 있음 — **verdict는 enum 검증이 없다(자유 문자열)**
- `object-model.md` 42줄 필수표엔 verdict 있고, 97·99줄 enum 목록엔 `review_type`·`review_scope`만 — **이건 엔진과 정확히 일치**(verdict는 enum이 아니니 enum 목록에 없는 게 맞음)

- [ ] **결론: 보강 불필요.** 문서가 엔진을 정확히 반영 중. 다음 세션 큐에서 "verdict 보강" 항목 제거.
- [ ] **(선택, 사용자 원할 때만)** verdict가 자유 문자열이라 헷갈릴 수 있으니, `object-model.md`에 "verdict는 enum 강제 없음 — 관례상 `approved`/`rejected` 사용" 안내 한 줄 추가. 스킬 수정이라 별도 승인 필요. **기본은 안 함(YAGNI).**

### Task 4: 갈래2 위치 층 locator 실측 [권장 1순위]

**Files:**
- 조사 대상: `brain/objects/code/` (CodeLocator JSON), `BubbleObjectDisturbHedgehog.cpp` (develop)
- 산출물 기록: vault task / `brain/raw/sources/insights/backlog.md`

**왜:** 개발자 커밋 `8618ead3bb`가 고슴도치 파일 `init`에 한 줄(`CLOUD_DO_POP_ON_NEAR_THIS_POP`, line 40)을 추가해 그 아래 라인이 다 밀렸다. brain의 CodeLocator 줄번호가 어긋났을 텐데, **그 어긋남이 실제 회상을 망가뜨리는지**를 처음으로 실측한다. 결과가 Task 5(갱신 대상 찾기 명령) 설계 입력이 된다. **cloud 트리거가 develop에 살아있는 지금이 측정 적기.**

- [ ] **Step 1: 고슴도치 파일을 가리키는 CodeLocator 목록 추리기**
  - `grep -rl "BubbleObjectDisturbHedgehog" brain/objects/code/` 또는 path 필드로 검색
- [ ] **Step 2: 각 locator의 `line_start`가 develop(`45c1f12aed`) 실제 코드와 맞는지 대조**
  - `git show 45c1f12aed:LineBubble2/Classes/game/model/bubbleObjects/BubbleObjectDisturbHedgehog.cpp` 의 해당 심볼 라인과 비교
  - line 40 추가 뒤를 가리키는 locator는 +1 어긋났을 것
- [ ] **Step 3: 어긋난 locator로 `project-brain search` 돌려 회상 영향 확인**
  - 그 locator가 달린 매핑/심볼 질의를 던져 회상이 망가지는지(순위 밀림·누락) 측정
- [ ] **Step 4: 판정 기록**
  - 어긋나도 회상 OK → "라인 갱신 불필요"로 `object-model.md` 153줄 철학(앵커=path+symbol 본질) 검증 완료, Task 5도 우선순위 낮춤
  - 회상 방해 → "위치 갱신 기능 필요" 확정 + 어떻게(제자리 일괄 수정 명령/재백필) 후보 — Task 5 설계 입력
  - 결론을 vault task와 insight-backlog에 기록 (라인 드리프트가 실제 회상에 주는 영향의 첫 실측 데이터)

### Task 5: [Task 4 실측 후 판단] "갱신 대상 찾기" 명령 — 지금 구현 안 함

**왜 지금 구현 계획을 안 쓰나:** 이 명령(배경 개념 5번 = 코드↔brain 비교 검사)이 무엇을 잡아야 하는지는 **Task 4 실측이 정한다.** 지금 구현 step을 쓰면 brain 재정립 때 경계한 "머리로 짓는 설계"가 된다. 실사용·실측 우선.

- [ ] **Task 4 결과로 판단:** "위치 갱신 필요"가 나오면 → 그때 이 명령을 설계 (골자: `git diff --name-only <commit_sha>..develop` → 바뀐 파일 → 그 파일 가리키는 CodeLocator·매핑을 **후보로 제시**, 판정은 사람. "코드 자동 비교 금지" 철학 유지 — lint가 끊긴 링크 잡듯 "코드 변경에 영향받은 객체" 잡는 별도 점검)
- [ ] **지금 할 일:** 위 골자만 기록. 구현 step 없음. (착수 트리거 = Task 4가 "필요" 결론)

### Task 6: application 검증 — 정식화한 스킬을 실제로 쓰는지 (서브에이전트)

**Files:**
- 검증 대상 스킬: `bb2-brain-query/SKILL.md` §7(조립 모드), `bb2-brain-session-ingest` §6(개념 단위 분기)

**왜:** 이어서24에서 RED(맨몸 실패)를 과적용했다가 "조립 워크플로우는 범용 기법형 → application 검증으로 본다"로 정정했다(`[74]`). 그 검증이 아직 안 됐다. 스킬을 쥐여준 에이전트가 절차대로 5요소 브리핑을 안정적으로, 과잉 없이 내는지 본다.

- [ ] **Step 1:** 서브에이전트(읽기전용 `Explore` agentType, 고신뢰 위해 `model: 'opus'` — memory [[feedback-workflow-explore-agent-haiku]])에게 개발 착수 요구를 준다
  - 대상 A — **샐리 카누**(5요소가 여러 컨텍스트에 흩어진 = 조립 절차의 진짜 가치 시험): 예) "샐리 결과 팝업에 전체 레이서 순위 표시"
  - 대상 B — **방해버블**(잘 적재됨 = 과잉 안 하고 멈추는지 시험): 예) "신규 방해버블 한 종 추가"
- [ ] **Step 2:** 브리핑에 5요소(데이터 출처·구조 패턴·확장 지점·규칙·과거 결정)가 나오는지, 단발이 충분한데 과하게 더 캐지 않는지 판정
- [ ] **Step 3:** 빈틈 발견 시 스킬 보강 후보로 기록 (스킬 수정은 사용자 승인 필요)

### Task 7: 골든셋 s9 — 개발 착수 시나리오 (테스트 우선)

**Files:**
- Modify: `brain/eval_scenarios.json`
- Modify: `brain/checks/test_real_corpus.py` (또는 가드의 기대 건수 위치)

**왜:** 설계 §8 — 개발 착수 요구 질의의 **첫 질의 회수 품질**을 회귀로 고정한다(조립 모드 전체가 아님). "eval 7/7"은 s9 신설 전 기준이고, 추가 시점부터 "8/8"로 갱신한다.

- [ ] **Step 1: 실험 A 질의로 현재 회수 상태 확인** — `project-brain search "샐리 결과 팝업 전체 순위 표시"` 류로 `race-end-result-branch`·`race-end-result-failure` 군집이 어디 오는지 본다 ("red 없이 도입 금지" = s9가 무엇을 지키는지 명확히 하고 추가)
- [ ] **Step 2: `eval_scenarios.json`에 s9 추가** (기존 시나리오 형식 그대로 — `id`·`title`·`note`·`query`·`expect{top5_any, linked_any_groups, max_results}`)

```json
{
  "id": "s9-dev-kickoff-sally-result-ranking",
  "title": "개발 착수 요구 → 도메인 핵심 매핑 군집 회수 (첫 질의 회수 품질 가드)",
  "note": "설계 §8. 실험 A 요구사항. 조립 모드 전체가 아니라 첫 질의의 회수 품질을 고정. 실제 기대 id는 Step 1 실측으로 확정해 채운다(추측 금지).",
  "query": "샐리 카누 결과 팝업에 전체 레이서 순위를 표시하려면",
  "expect": {
    "top5_any": ["<Step1 실측으로 확정>"],
    "linked_any_groups": [["<Step1 실측으로 확정>"]],
    "max_results": 5
  }
}
```

- [ ] **Step 3: `project-brain eval --check-ids && project-brain eval`** — s9 포함 전건 통과(8/8) 확인
  - Expected: `scenario count: 8`, s9 `passed: True`
- [ ] **Step 4: 가드·문서의 "7/7" → "8/8" 갱신** — `test_real_corpus.py` 및 task·계획서 표기. 같은 커밋에 포함
- [ ] **Step 5: 커밋** — `git add brain/eval_scenarios.json brain/checks/test_real_corpus.py` + brain 브랜치 규약대로

---

## Self-Review (계획 작성자 체크)

- **개념 정리 누락 메움:** 배경 1~5번이 이어서24 핸드오프에서 빠진 것(적재 흐름·린트·백필vs대체·위치갱신·갱신대상찾기)을 전부 담음 — 점검에서 missing/partial로 나온 항목 대응.
- **검수로 정정한 것 반영:** Task 3 verdict(enum 아님 → 보강 불필요), 배경 4번 출처(update-rules "스냅샷 갱신" 줄, object-model 153줄).
- **추측 없음:** s9 기대 id는 "Step 1 실측으로 확정"으로 비워둠(현재 회수 상태를 안 봤으니 단정 금지). Task 5는 구현 step 없이 "Task 4 후 판단".
- **단일 출처:** 개념은 이 계획서, vault task는 포인터(Task 1). 중복 방지.
- **트리거 안전:** Task 1이 포인터를 vault task + 시작 프롬프트 두 곳에.
