# brain 감사 후속 — 누락·드리프트 정비 구현 플랜

> **진행 상태 (2026-06-29 완료):** 우선순위1~3 + stale 운용(재논의→audit 신설) + 줄번호 정합 **완료·커밋**
> (엔진 브랜치 `fix/audit-remediation-p1`, bb2 path-limited 커밋, 엔진 530 테스트 통과, 적대검증 5회 통과).
> stale 운용 주체 = `project-brain audit`(lint+isolated+stale 한 패스, checkup→audit 개명). 줄번호는 문서 정합
> 완료·데이터 마이그레이션만 보류. **유일 미결 = 우선순위4(단일원본/installer 확장)** → 별도 결정 문서
> [2026-06-29-engine-single-source-decision.md](2026-06-29-engine-single-source-decision.md)에서 다음 세션 논의.
>
> **For agentic workers:** 우선순위 1은 TDD 단위 스텝으로 실행한다(subagent-driven-development 권장). 우선순위 2~4는 데이터레포·승인 게이트가 걸린 범위 작업이라 각 단계 착수 직전 사용자 승인을 받는다.

**Goal:** 2026-06-26~27 엔진/스킬 변경으로 생긴 누락·드리프트(advisories 죽은 채널, stale docstring 정책 위배, bb2 스킬 정합)를 코드 검증된 work-list로 정비한다.

**Architecture:** 4개 독립 서브시스템을 우선순위로 분리 — 엔진 코드(즉시·git추적) → bb2 데이터 → bb2 설치본 스킬 → 단일원본 싱크(최후순위). 단계 간 의존은 advisories(우선순위1)가 bb2 Insight 회수 검증(우선순위2)의 전제라는 것 하나.

**Tech Stack:** Python 3.11, pytest, FTS5+bge-m3, uv venv(`.venv/bin/python`). 데이터레포 = `/Users/al03040455/Desktop/bb2_client`.

## Global Constraints

- **검수 정책 B+C 절대 준수**: 근거 확실→에이전트 자동(reviewed), 애매→candidate, **완전 애매한 것만** 사용자. "사람이 판정/수동 판정/자동 불가"라고 쓰지 말 것. docstring이 그래도 정책 우선. ([[engine-review-policy-bc-hybrid]])
- **결정론**: 테스트는 StubEmbedder/`--stub-embedder`. 실모델 금지.
- **surgical**: 변경 줄은 이 work-list 항목에 직접 연결. 인접 코드 개선·리팩터 금지.
- **스킬·데이터레포 수정은 사용자 승인 후**(git 추적 밖일 수 있음). bb2 working tree의 사용자 WIP(dev-ui, cpp, luckybox, test_real_corpus.py)는 안 건드림 — 별도 path-limited 커밋.
- **단계2(단일원본 싱크)는 최후순위**(사용자 결정 2026-06-27). 방향은 "엔진이 최종 스킬 관리 소스".
- **stale 운용 배선은 재논의 대기** — 이 플랜은 docstring 정정만 포함(우선순위1).

---

## 우선순위 1 — 엔진 코드·베이스 템플릿 갭 (즉시·독립·전 사용자 반영, 엔진 레포·git추적·승인 불필요)

git 추적 코드·템플릿이라 바로 실행 가능. 작업 브랜치에서 진행. (적대검증 교정: engine-template owner 항목을 단계2 최후순위로 미루면 신규 install 회귀·역수입 충돌이라 여기로 끌어올림.)

### Task 1: search 출력에 advisories 채널 복구

**배경(코드 검증됨):** `eval_recall`은 `advisories`(reviewed Insight)를 반환하나(`search.py:735-756`), `_run_search`(`cli.py:376-382`)가 출력 dict에서 버린다. `projection_reuse`/`raw_excerpts`는 trust_label 블록으로 실리는데(`cli.py:364-375`) advisories만 빠진 **비대칭 누락**. router 경로(`router.py:420-436`)로만 노출돼, query 스킬이 쓰는 search로는 검수 Insight가 영영 안 보임(bb2 실측: "니코샵 노출 제한"에 search advisories 0건, router 1건).

**Files:**
- Modify: `src/project_brain/cli.py:376-382`
- Modify: `src/project_brain/templates/query.md` (채널표에 advisories 행 — 코드 채널 복구와 사용 지침은 한 커밋)
- Test: `tests/test_cli.py` (TestCliSearch 클래스)

**설계 결정(이 Task가 택한 것):** 최소·정합 안 = `projection_reuse`와 **동형 trust_label 패스스루**. eval_recall hit은 object_id/kind/status/score/surface/linked를 이미 보유하므로 그대로 + 라벨이면 검수 Insight가 search에 뜬다. router가 store에서 끌어오는 `insight_type`/`source_object_ids` 추가 노출은 hit dict에 없어 store 접근이 필요한 **별개 개선** — 죽은 채널 복구가 본 목적이므로 이번엔 패스스루까지(karpathy 단순성). (richer 노출이 필요해지면 후속.)

- [ ] **Step 1: 실패 테스트 작성** (`tests/test_cli.py` TestCliSearch에 추가)

```python
    def test_search_advisories_channel(self):
        # reviewed Insight가 advisories 채널로 노출된다(spec 2026-06-15 §4.6).
        # 회귀 가드: eval_recall은 advisories를 반환하나 _run_search 출력에서
        # 빠져 있던 비대칭 누락 복구(2026-06-27). g.token이 anchor 토큰 제공.
        from tests.test_search import glossary_term, insight
        self._build_index([
            glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰 노출"),
            insight("insight.gate", body="클리어 토큰 노출 게이트가 두 팝업에 이중구현"),
        ])
        rc, payload = self._search("클리어 토큰 노출 게이트 이중구현")
        self.assertEqual(rc, 0)
        self.assertIn("advisories", payload)
        self.assertIn("insight.gate", {h["object_id"] for h in payload["advisories"]})
        for h in payload["advisories"]:
            self.assertEqual(h["trust_label"], "가로지르는 위험·교훈(검증됨)")
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_cli.py::TestCliSearch::test_search_advisories_channel -v`
Expected: FAIL — `KeyError: 'advisories'` 또는 `assertIn` 실패(키 부재).

- [ ] **Step 3: 구현** (`cli.py:376` print 직전에 블록 추가 + dict에 키 추가)

```python
    # advisories 채널(spec 2026-06-15 §4.6): reviewed Insight를 신뢰 라벨과 함께 낸다 —
    # eval_recall이 이미 반환하나(search.py:753) 출력에서 빠져 있던 비대칭 누락 복구.
    # projection_reuse/raw_excerpts 라벨 규약과 동형(검수된 통찰이라 "검증됨" 라벨).
    advisories = [{**h, "trust_label": "가로지르는 위험·교훈(검증됨)"}
                  for h in resp.get("advisories", [])]
    print(json.dumps(
        {"ok": True, "query": args.query,
         "results": resp["results"], "candidates": resp["candidates"],
         "raw_excerpts": raw_excerpts,
         "advisories": advisories,
         "projection_reuse": projection_reuse,
         "needs_clarification": resp["needs_clarification"]},
        ensure_ascii=False, indent=2))
```

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_cli.py::TestCliSearch -v`
Expected: PASS (기존 6 + 신규 1 = 7).

- [ ] **Step 5: query.md 채널표에 advisories 행 추가** (엔진 템플릿)

`src/project_brain/templates/query.md`의 채널표(results/candidates/raw_excerpts/projection_reuse/needs_clarification 행이 있는 표)에 advisories 행 1줄 추가 — 어시스턴트가 키를 읽고 다루는 지침. 라벨은 코드와 동형:
`| advisories | 가로지르는 위험·교훈(검증됨) — 질의와 가로지르는 reviewed Insight. 단정 답 아님, 답에 참고로 곁들임 |`
⚠️ 적대검증 발견: cli 키만 추가하고 채널표 행이 없으면 출력엔 떠도 어시스턴트가 안 읽어 **반쪽 복구**.

- [ ] **Step 6: 커밋**

```bash
git add tests/test_cli.py src/project_brain/cli.py src/project_brain/templates/query.md
git commit -m "fix(cli): search 출력에 advisories 채널 복구 + query.md 채널표 안내 (eval_recall은 반환·_run_search가 버리던 비대칭 누락)"
```

### Task 2: stale_check docstring을 B+C 정책에 맞게 정정

**배경(검증됨):** `stale_check.py:5-6` docstring "의미가 진짜 낡았나는 **사람이 판정**한다"는 stale 자동화 정본(`docs/plans/2026-06-25-brain-stale-automation-bc.md` §2: "사용자 1인 전수 검수는 병목이라 안 한다 — 확실하면 자동")과 정반대. 이 문구가 6-25·6-27 2회 정책 위배의 발화점.

**Files:**
- Modify: `src/project_brain/stale_check.py:5-6`

- [ ] **Step 1: docstring 정정**

old (`stale_check.py:5-6`):
```python
합성 입력으로 대체, 네트워크·실레포 무관). 기계는 "어느 파일이 바뀌어 어느
매핑이 영향권인가"까지 찾고, "의미가 진짜 낡았나"는 사람이 판정한다.
```
new:
```python
합성 입력으로 대체, 네트워크·실레포 무관). 기계는 "어느 파일이 바뀌어 어느
매핑이 영향권인가"까지 찾고, 영향권 후보의 처리는 검수 정책 B+C를 따른다 —
근거 확실하면 에이전트가 자동(reviewed) 갱신/supersede, 모호하면 candidate,
완전 애매한 것만 사용자(정본: docs/plans/2026-06-25-brain-stale-automation-bc.md §2).
```

- [ ] **Step 2: 회귀 확인**

Run: `.venv/bin/python -m pytest tests/test_stale_check.py -q`
Expected: PASS (docstring 변경이라 동작 무영향, 회귀 0).

- [ ] **Step 3: 커밋**

```bash
git add src/project_brain/stale_check.py
git commit -m "docs(stale): docstring '사람이 판정'을 검수 정책 B+C로 정정 (정본과 어긋난 문구)"
```

### Task 3: ROADMAP 주입 SKILL.md 개수 오기 정정

**배경(검증됨):** `installer.py:25-29`는 query/ingest/session-ingest **3개** SKILL.md를 주입하나, ROADMAP "팀 공개" 항목의 동반작업 줄이 "SKILL.md **2개** 외에 ... session-ingest는 미주입"이라 적음 — 개수(2→3)와 "session-ingest 미주입"(실제는 주입됨, 미주입은 references/scripts) 둘 다 오기. 프롬프트가 콕 집은 항목.

**Files:**
- Modify: `ROADMAP.md` (4. 팀 공개 항목 "동반 작업" 줄)

- [ ] **Step 1: 오기 정정**

old:
```
   - 동반 작업: 스킬 범용화(엔진 install이 주입하는 `SKILL.md` 2개 외에 `references/`·
     session-ingest는 미주입 — 범용화는 삭제가 아니라 추상화, 맞춤은 설치 후 실사용으로).
```
new:
```
   - 동반 작업: 스킬 범용화(엔진 install이 주입하는 `SKILL.md` 3개(query/ingest/session-ingest)
     외에 `references/`·`scripts/`는 미주입 — 범용화는 삭제가 아니라 추상화, 맞춤은 설치 후 실사용으로).
```

- [ ] **Step 2: 커밋**

```bash
git add ROADMAP.md
git commit -m "docs(roadmap): 주입 SKILL.md '2개→3개' 오기 정정 + references/scripts 미주입 명확화"
```

### Task 4: 엔진 베이스 session-ingest.md 정합 (engine-template owner)

**배경(적대검증 확정):** owner=engine-template인 항목을 단계2(최후순위)로 미루면 신규 `install`에 회귀가 남고, 단계2 역수입 때 bb2와 어긋난다. git추적 템플릿이라 승인 불필요·즉시 가능 — 베이스를 먼저 정본화한다.

**Files:**
- Modify: `src/project_brain/templates/session-ingest.md` (필요 시 `src/project_brain/templates/ingest.md`도)
- Verify: `tests/test_installer.py`

- [ ] **Step 1: UTC Z 견본 → KST.** 129·132·142·146줄의 `"...Z"` datetime 견본을 `+09:00` 표기로(코퍼스 표준 KST, `objbase.py:10·15` `now_kst`). bb2 update-rules.md 견본과 같은 값으로.
- [ ] **Step 2: Insight 출처 개수 정밀화.** :31 "2개 이상" → `schema.py:234` 분기 명시(cross-cutting-risk≥2, operational-lesson≥1 — enum 두 값 명시).
- [ ] **Step 3: graph isolated 단계 추가.** 적재 절차에 "적재 후 `graph isolated`로 고립 객체 점검" 한 단계(bb2 SKILL.md:27은 이미 6단계, 베이스는 미반영).
- [ ] **Step 4: raw 경로 {{BRAIN_ROOT}} 치환.** `grep -n "raw/" src/project_brain/templates/session-ingest.md src/project_brain/templates/ingest.md`로 치환자 없는 `raw/...` 줄을 찾아 `{{BRAIN_ROOT}}` 접두어(설치 시 brain/ 누락 방지).
- [ ] **Step 5: 검증·커밋**

Run: `.venv/bin/python -m pytest tests/test_installer.py -q` (render_template 치환 무결 + manifest 보존 회귀 0)
```bash
git add src/project_brain/templates/session-ingest.md src/project_brain/templates/ingest.md
git commit -m "docs(templates): 엔진 베이스 session-ingest 정합 (UTC Z→KST·Insight 1/2 분기·graph isolated·BRAIN_ROOT)"
```

### 우선순위 1 완료 게이트
- [ ] `.venv/bin/python -m pytest tests/ -q` 전체 통과(회귀 0).
- [ ] (선택) 데이터레포에서 `project-brain search "니코샵 노출 제한"` → advisories에 `insight.nico-shop.zero-block-trap` 실제로 뜨는지 확인(글로벌 도구 편집설치라 머지/체크아웃 상태 의존).

---

## 우선순위 2 — bb2 데이터: 검수 Insight 승격 (데이터레포, 승인·사용자 주도)

**의존:** 2a 회수 검증은 우선순위1 Task 1 머지 후라야 search에 보임.
**owner:** bb2 brain 데이터. 코드/스킬 변경 없음(엔진은 Insight·advisories 통로 완비).
**주의:** bb2 현재 브랜치 `docs/bb2-brain-object-model`에 사용자 WIP 多 → 승격은 별도 path-limited 커밋.

- **2a [high] 06-11 팝업게이트 → cross-cutting-risk Insight 승격.** source 2건 reviewed 실재 검증됨: `decision.stage-clear-token.continue-popup-mode-gate` + `mapping.stage-clear-token.enter-popup-instant-clear-button-visibility`. spec §1이 직접 예시로 든 케이스. → 승격(reviewed 직접, source≥2) → index rebuild → `search`로 advisories 회수 확인.
  - verify: `project-brain lint` clean + `eval`의 `advisories_top5_any` 적중 + search advisories에 등장.
- **2b backlog.md 머리말 갱신.** 제목 'P3 설계입력' 제거 + 'P3 가드 충족' 문장 삭제 + 승격 3갈래(자동/candidate/부적격) 명시. ⚠️ **깨진 경로 주의(적대검증)**: backlog.md:3은 `docs/superpowers/specs/2026-06-11-bb2-brain-session-ingest-design.md §6`인데 그 파일이 실재 안 함(bb2엔 `docs/specs/` 디렉터리 자체가 없고 `docs/superpowers/specs/`만 있음). 착수 직전 실경로 재확인 후 **실존 정본으로 교체하거나, 없으면 참조 삭제.**
- **2c 분류.** 06-18 빅버블 공통화 → Insight 부적격(단일 함수 리팩터) → DecisionRecord/코드백로그. 06-12·06-13 line drift → bb2 도메인 아닌 엔진 기능 관찰 → 엔진 ROADMAP으로 분리.

---

## 우선순위 3 — bb2 설치본 스킬 정합 (데이터레포, 승인)

**근거:** 사용자가 매일 쓰는 스킬. 단계2(싱크)가 최후순위라, 지금 bb2를 직접 바로잡아야 일상 사용이 정확.
**owner·중복 주의(적대검증 교정):** references-only 파일(object-model.md·ingest-tools.md)은 엔진 베이스에 대응본이 없어(find 0건) "bb2 정합 → 단계2 단방향 역수입"이라 두 번 편집 아님. **그러나 session-ingest.md는 엔진 베이스에도 사본이 있어**(우선순위1 Task 4에서 베이스 먼저 정정), bb2의 그 항목(update-rules.md UTC Z·source 개수·graph isolated)은 베이스와 **같은 값으로** 맞춘다 — 단계2 역수입 충돌 방지. 정리: engine-template owner = Task 4(베이스) + 여기(bb2 미러), bb2 전용 = 여기만.

- **3a [high] `references/ingest-tools.md` decisions 자기모순 정정**(29·32·50줄). "decisions 1차 미지원/extra_objects" → "decisions[] 패스스루로 build_decisions가 DecisionRecord+EvidenceRef 조립·affects 역채움". 같은 스킬 object-model.md·SKILL.md와 정합. 엔진 `build_decisions`(7c2f87c·91a9a6c)가 1차 지원.
- **3b `references/object-model.md` 줄번호·UTC Z 정정.** CodeLocator 줄번호 잔존(167·170·213-214) 제거(엔진 미저장). created_at/updated_at UTC `Z` **9줄**(195-196·216·219-220·244-245·283-284) → KST(+09:00).
- **3c GlossaryTerm 동의어 *규칙* 역수입**(`references/object-model.md` GlossaryTerm 항목). 한↔영 등가어 우선·흔한 단일어 금지(anchor_df)·definition 본문 중복 금지·기존 용어는 updates[] union. **scripts 자동 추출 통로는 분리/보류** — 자동 추출이 흔한 단일어를 넣어 df 가드를 약화시킬 위험이라 보수적 경로(사람 선언) 확인 후 별도 결정.
- **3d bb2 미러 정합(베이스 Task 4와 같은 값).** dev-ingest.md(9·10)·update-rules.md(11) 줄번호 제거(bb2-data owner). update-rules.md UTC Z(6건)→KST·Insight source 1·2 분기·graph isolated = **Task 4 베이스와 동일 값**으로(engine-template owner의 bb2 미러). bb2 query SKILL.md 채널표(46-53)에 advisories 행 **+ projection_reuse 행** 추가(현재 표엔 results/candidates/raw_excerpts/needs_clarification 4행뿐 — projection_reuse도 표엔 누락, 본문엔 있음).

---

## 우선순위 4 (최후순위) — 단일원본 확립 (엔진 + cross-repo)

**사용자 결정:** 방향은 "엔진이 최종 스킬 관리 소스"가 맞으나 **가장 후순위**. 착수 전 G2 결정 게이트.

**⚠️ 착수 전 결정 게이트 G2 (배포모델):** installer 디렉토리 주입 확장 / 별도 scaffold 배포 / 베이스 ingest.md에 손조립 대안 문서화 — 셋 중. 이전 세션이 "installer 확장"으로 기울었으나 검증상 "재설계 수준"이라 정식 결정 필요.

**내부 절대순서(installer 확장 택할 때):**
1. installer를 디렉토리 walk로 확장(`__pycache__`·`.pyc`·fixtures 제외 필터, `.md`/`.py` 치환 분기). templates/에 references/·scripts/ 신설.
2. bb2 정합본 역수입: `bb2`→`{{PROJECT}}`, `REPO='bb2_client'`(4곳)·`develop`(8파일) 일반화(새 변수/재서술), 도메인 예시 일반화, fixtures 제외. **(범용화는 SKILL.md만 쉬움 — references/scripts는 하드코딩 多, 단순 치환 불가)**
3. 엔진 머지(우선순위1 Task 4에서 이미 정정한 베이스 항목 제외): bb2 정합본의 references/scripts를 엔진 templates로 신규 이식 + session-ingest 동의어 규칙(베이스 신규) + scaffold 배포모델 ROADMAP 항목화. (UTC Z·{{BRAIN_ROOT}}·graph isolated·Insight 1/2·query advisories 행은 Task 4에서 완료됨.)
4. **역수입 완료 확인 후에만** manifest 채우기/install. `--force` 없음·manifest 비어 전부 skip → 순서 어기면 엔진 164줄이 bb2 363줄 덮어 발전분 소실.
5. 이후 규율: bb2 직접수정 금지(단일원본 대가).

**no-action(명시 닫음):** show §8.3 edge 키·실존필터 보강 = 정확성 무해한 군더더기.

---

## 재논의 대기 — stale 운용 배선

**확정(우선순위1 Task 2):** docstring 정정.
**재논의 필요(사용자 요청):** "이전에 같이 결정했는데 뭔가 이상하게 적용된 듯" — 코드/정본 대조 결과:
- **결정(정본 §2)**: B+C — 확실 자동(reviewed), 모호 candidate+query 노출, 사용자는 예외 판정+사용 시점 수정만. Step 1·2 구현완료, Step 3(자동 트리아지) 보류, 방아쇠=수동 triage가 거슬릴 때(§7).
- **구현 상태**: 읽기 경로(`cli.py:62-68` stale_advisories 주입)는 배선됨. 그러나 `stale-check --write-cache`를 **도는 주체가 없어** bb2에 캐시 없음 → advisory 한 번도 발화 안 됨.
- **이상하게 적용 = 2개**: (1) docstring이 정책과 정반대(정정 확정), (2) 갈래2 채널이 구현됐으나 *갱신 주체(누가/언제 --write-cache 도나)*가 미정이라 죽은 상태. §7상 "방아쇠 전"이라 의도일 수도 있으나, 운용 주체를 정해야 채널이 산다.
- **재논의 질문**: stale-check write-cache를 누가/언제 도나(session-ingest의 develop pull 후 배선 vs 수동 유지)? 이 결정 후 우선순위3/별도 작업으로.
- **읽기측 동반(적대검증)**: 운용 배선을 켤 때 query.md(엔진+bb2)에 stale_advisory·warnings 해석 안내도 같이 — 현재 양쪽 0건. 쓰기 주체가 정해지기 전엔 죽은 문구라 지금은 안 넣음.

---

## 완료 기준
- 우선순위1: pytest 전체 통과, advisories search 노출 실측 확인.
- 우선순위2~3: bb2 lint clean + 사용자 승인 커밋.
- 우선순위4: G2 결정 후, 역수입 완료→manifest 순서 준수, test_installer 통과.
- stale 운용: 재논의 후 별도 착수.
