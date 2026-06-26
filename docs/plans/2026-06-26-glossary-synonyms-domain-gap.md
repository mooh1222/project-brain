# GlossaryTerm 동의어 채우기(도메인·언어 갭 recall 보강) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GlossaryTerm 객체에 `synonyms`/`aliases`(특히 한국어↔영문 등가어)를 채워, 다른 어휘로 물어도 그 용어를 찾게 해 검색 recall을 높인다.

**Architecture:** 색인 표면(`surface.py`)은 이미 `synonyms`/`aliases`를 읽는다 — 비어 있을 뿐이다. 따라서 (1) 적재 조립(`build_glossary_terms`)이 노트의 동의어를 객체에 실어 나르게 하고, (2) 기존 객체 백필 통로(`apply_updates` allowlist)를 열고, (3) 적재 스킬에 동의어 작성 규칙을 명시하고, (4) 데이터레포 골든셋·실측 가드로 precision 부작용(표면 앵커 df 약화)이 없는지 측정한 뒤에만 전체 백필로 확장한다. `surface.py`는 건드리지 않으므로 `EXTRACTOR_VERSION` bump는 불필요하다(추출 로직 불변, 데이터만 채워짐).

**Tech Stack:** Python(엔진 `src/project_brain/`), unittest(합성 테스트), SQLite+FTS5+sqlite-vec+bge-m3(색인, 검증 단계), 데이터 레포 `brain/`(bb2_client).

## Global Constraints

- 결정론 유지 — 테스트는 실모델 금지, 임베딩은 StubEmbedder(`PROJECT_BRAIN_EMBEDDER=stub`). (CLAUDE.md)
- `surface.py`를 수정하지 않는다 — `_surface_glossary_term`이 이미 `synonyms`/`aliases`/`avoid`를 읽는다(surface.py:66). 동의어 메커니즘은 "새 코드"가 아니라 "기존 빈 필드 채우기"다.
- `EXTRACTOR_VERSION`(surface.py:27)을 올리지 않는다 — 추출 로직이 안 바뀌므로. (올리면 불필요한 전체 rebuild 트리거.)
- 동의어에 흔한 단일어("팝업"·"이벤트"·"모드")를 넣지 않는다 — 답변 게이트의 표면 앵커(`_ANCHOR_DF_MAX=30`, search.py)를 흔들어 거짓양성 가드를 약화시킨다. 고유성 있는 구(句)·한국어↔영문 등가어만.
- 색인 영향 변경이므로 엔진 합성 테스트만으로 완료가 아니다 — 데이터 레포 회귀(`eval` 골든셋 7종 + `brain/checks`)가 통과해야 완료다. (CLAUDE.md "엔진 수정 후 실코퍼스 회귀")
- 경로·날짜 하드코딩 금지(config 해석).

---

## File Structure

- `src/project_brain/assembly.py` — 적재 조립 코어. **수정 2곳**: `build_glossary_terms`(동의어 실어 나르기), `_UNION_ALLOWLIST`(백필 통로).
- `tests/test_assembly.py` — 합성 테스트. **추가**: 동의어 운반 테스트, 백필 union 테스트.
- `src/project_brain/templates/ingest.md` — 적재 스킬 템플릿. **추가**: 동의어 작성 규칙 섹션.
- `tests/test_installer.py` — 템플릿 manifest 보존 가드. **실행만**(변경 없음, Task 3 회귀 확인용).
- (데이터 레포) `bb2_client/brain/objects/domain/g.*.json` — Task 4·5에서 백필 대상(엔진 레포 밖).

`surface.py`·`schema.py`·`search.py`·`search_index.py`는 **변경하지 않는다** — 이미 동의어를 읽고/허용하고/색인한다.

---

## Task 1: build_glossary_terms가 노트의 synonyms/aliases를 객체에 싣는다

**Files:**
- Modify: `src/project_brain/assembly.py:36-46` (`build_glossary_terms`의 `obj` dict)
- Test: `tests/test_assembly.py` (`BuildGlossaryTest` 류 클래스에 추가, 기존 `test_builds_reviewed_term_with_evidence`:139 패턴)

**Interfaces:**
- Consumes: 모듈 상수 `NOW = "2026-06-16T00:00:00Z"`(test_assembly.py:9), `build_glossary_terms(notes, now)`.
- Produces: `build_glossary_terms`가 만드는 GlossaryTerm obj에 `synonyms: list[str]`, `aliases: list[str]` 키가 항상 존재(노트에 없으면 `[]`).

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_assembly.py`의 glossary 빌드 테스트 근처에 추가:

```python
def test_glossary_carries_synonyms_and_aliases(self):
    notes = {
        "context": {"key": "ctx", "commit": "a"},
        "glossary": [{"key": "tok", "term": "CLEAR_PASS_TICKET_RECOVER",
                      "definition": "토큰 환불 복구 요청 타입",
                      "evidence_refs": ["evref.ctx.x"],
                      "synonyms": ["클리어 패스 티켓 복구", "토큰 환불 복구"],
                      "aliases": ["CPTR"]}],
    }
    objs = build_glossary_terms(notes, NOW)
    self.assertEqual(objs[0]["synonyms"], ["클리어 패스 티켓 복구", "토큰 환불 복구"])
    self.assertEqual(objs[0]["aliases"], ["CPTR"])

def test_glossary_synonyms_default_empty(self):
    notes = {
        "context": {"key": "ctx", "commit": "a"},
        "glossary": [{"key": "t", "term": "T", "definition": "d",
                      "evidence_refs": ["evref.ctx.x"]}],
    }
    objs = build_glossary_terms(notes, NOW)
    self.assertEqual(objs[0]["synonyms"], [])
    self.assertEqual(objs[0]["aliases"], [])
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_assembly.py -k "synonyms" -q`
Expected: FAIL — `KeyError: 'synonyms'`(obj에 키 없음).

- [ ] **Step 3: 구현 — obj에 2줄 추가**

`src/project_brain/assembly.py`의 `build_glossary_terms` `obj` dict에서 `"evidence_refs": g.get("evidence_refs", []),` 다음에 추가:

```python
            "synonyms": g.get("synonyms", []),
            "aliases": g.get("aliases", []),
```

(기존 `evidence_refs`와 같은 `g.get(..., [])` 패턴 — 노트에 없으면 빈 리스트. surface.py가 빈 리스트를 무해하게 거른다.)

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_assembly.py -q`
Expected: PASS(신규 2개 포함 전체).

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "feat(assembly): build_glossary_terms가 노트의 synonyms/aliases를 객체에 운반"
```

---

## Task 2: 기존 GlossaryTerm 백필 통로 열기 (apply_updates allowlist)

**Files:**
- Modify: `src/project_brain/assembly.py:231` (`_UNION_ALLOWLIST["GlossaryTerm"]`)
- Test: `tests/test_assembly.py` (apply_updates 테스트, 기존 `test_set_scalar_and_union_list`:174 패턴)

**Interfaces:**
- Consumes: `apply_updates(notes, store, now)` → `(out, diffs, errors)`; 모듈 상수 `T0 = "2026-06-01T00:00:00Z"`(test_assembly.py:158, 해당 테스트 클래스 스코프).
- Produces: GlossaryTerm의 `synonyms`/`aliases`가 `union` 연산 allowlist 안에 듦(claim 필드 아니라 근거 동반 불필요).

- [ ] **Step 1: 실패 테스트 작성**

apply_updates 테스트 클래스(`T0` 상수가 보이는 곳)에 추가. `T0`가 클래스 안에만 있으면 같은 클래스에, 모듈 레벨이면 어디든:

```python
def test_glossary_synonyms_union_allowed(self):
    store = BrainStore({"g.ctx.x": {
        "id": "g.ctx.x", "kind": "GlossaryTerm", "updated_at": T0,
        "synonyms": ["기존"], "aliases": []}})
    notes = {"updates": [{"id": "g.ctx.x", "expected_updated_at": T0,
                          "union": {"synonyms": ["추가"], "aliases": ["AKA"]}}]}
    objs, diffs, errors = apply_updates(notes, store, NOW)
    self.assertEqual(errors, [])
    self.assertEqual(objs[0]["synonyms"], ["기존", "추가"])
    self.assertEqual(objs[0]["aliases"], ["AKA"])
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/test_assembly.py -k "synonyms_union" -q`
Expected: FAIL — errors에 `"union 필드 'synonyms'는 GlossaryTerm allowlist 밖"`(assembly.py:271).

- [ ] **Step 3: 구현 — allowlist에 2개 추가**

`src/project_brain/assembly.py:231`을 수정:

```python
    "GlossaryTerm": {"evidence_refs", "synonyms", "aliases"},
```

(`_UNION_ALLOWLIST`는 list 합치기 — synonyms/aliases는 list라 union이 맞다. `_SET_ALLOWLIST`엔 넣지 않는다 — 동의어는 누적·합치기지 통째 교체 대상이 아니다. synonyms/aliases는 `_CLAIM_FIELDS`(meaning/definition 등)가 아니므로 근거 동반 강제도 안 걸린다.)

- [ ] **Step 4: 통과 확인**

Run: `.venv/bin/python -m pytest tests/test_assembly.py -q`
Expected: PASS(전체).

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "feat(assembly): GlossaryTerm synonyms/aliases 백필 통로(union allowlist)"
```

---

## Task 3: 적재 스킬에 동의어 작성 규칙 명시

**Files:**
- Modify: `src/project_brain/templates/ingest.md` (「객체화 경계」 섹션 다음, 「적재 실행」 앞에 새 섹션)
- Test: `tests/test_installer.py` (실행만 — manifest 보존 회귀 확인)

**Interfaces:**
- Consumes: 없음(문서).
- Produces: 적재 에이전트가 GlossaryTerm 노트의 `synonyms`/`aliases`를 어떤 기준으로 채울지 아는 규칙.

- [ ] **Step 1: ingest.md에 섹션 추가**

`## 객체화 경계 — 독립 회상 가치` 블록 끝(라인 65 `...범위까지만.` 다음)과 `## 적재 실행 (B+C)` 사이에 삽입:

```markdown
## 용어 동의어 — 검색 어휘 넓히기 (선택, recall 보강)

GlossaryTerm 노트(`glossary[]`)에 `synonyms`/`aliases`를 채우면 다른 어휘로 물어도
그 용어를 찾는다(BM25 recall + 색인 표면 확장 — `surface.py`가 이미 읽는다). 우선순위:

1. **한국어↔영문 등가어 (최우선).** term이 영문 코드명·enum·메시지키면 한국어로
   부르는 말을 넣는다. 예: `CLEAR_PASS_TICKET_RECOVER` → `["클리어 패스 티켓 복구",
   "토큰 환불 복구"]`. (코퍼스 term의 다수가 영문이라 효과가 가장 크다.)
2. **기획서·구어 표현.** 같은 대상을 다르게 부르는 말. 예: 입장팝업 → `["시작 팝업"]`.
3. **코드 식별자 변형.** 약어·대소문자. 예: `getNextLevel` → `["NL", "NextLevel"]`.

지켜야 할 두 규칙:
- **흔한 단일어 금지.** "팝업"·"이벤트"·"모드" 같은 일반어는 넣지 마라 — 답변 게이트의
  표면 앵커(df)를 흔들어 "기록 없으면 없다"는 거짓양성 가드를 약화시킨다. 고유성 있는 구(句)만.
- **definition 본문에 이미 있는 단어는 넣지 마라** — 이미 색인된다. 동의어 자리엔
  본문에 없는 다른 표현만 넣어 어휘를 넓힌다.

기존 용어에 뒤늦게 채울 때는 `updates[]`의 `union`으로 합친다(덮어쓰기 아님):
`{"id": "g.<ctx>.<key>", "expected_updated_at": "<현재값>", "union": {"synonyms": [...]}}`.
```

- [ ] **Step 2: manifest 보존 회귀 확인**

Run: `.venv/bin/python -m pytest tests/test_installer.py -q`
Expected: PASS — 템플릿 본문 변경이 manifest 보존(사용자 수정 파일 skip) 동작을 안 깬다.

- [ ] **Step 3: 커밋**

```bash
git add src/project_brain/templates/ingest.md
git commit -m "docs(templates): ingest 스킬에 GlossaryTerm 동의어 작성 규칙(한↔영 우선·일반어 금지)"
```

---

## Task 4: 검증 게이트 — 샘플 백필 + 골든셋·실측 회귀 (데이터 레포)

> 이 task는 엔진 레포 밖(데이터 레포 `bb2_client/brain`)에서 돈다. Task 1·2가 설치된 엔진(`uv tool install -e .` 편집 설치라 자동 반영)으로 실행한다. **전체 백필(Task 5) 전 필수 게이트** — 동의어가 recall은 올리되 precision/거짓양성 가드를 안 깨는지 실측한다.

**Files:**
- Create(임시): `<scratchpad>/glossary-synonyms-sample.json` (updates 노트 묶음)
- Modify(데이터 레포): `bb2_client/brain/objects/domain/g.*.json` 5~10개(ingest가 기록)

**Interfaces:**
- Consumes: Task 1·2가 반영된 `project-brain build`/`ingest`/`promote`.

- [ ] **Step 1: 영문 term 샘플 5~10개 선정**

데이터 레포에서 한국어↔영문 갭이 큰 reviewed GlossaryTerm을 고른다(예시 — 실재 확인된 것):
`g.stage-clear-token.clear-pass-ticket-recover`, `g.ingame-logic.game-play-mode`,
`g.sally-canoe.racing-main-page-desc-label`, `g.disturb-bubble-system.force-pop-enabled`.

```bash
cd /Users/al03040455/Desktop/bb2_client/brain
.venv/bin/python - <<'PY'  # (없으면 python3) 영문 term이면서 synonyms 빈 것 추리기
import json, glob
for f in sorted(glob.glob("objects/domain/g.*.json")):
    d = json.load(open(f))
    t = d.get("term") or ""
    if not (d.get("synonyms")) and any(c.isascii() and c.isalpha() for c in t):
        print(d["id"], "|", t[:50], "| updated_at:", d.get("updated_at"))
PY
```

- [ ] **Step 2: before 측정 — 한국어 질의로 못 찾는지 기록**

각 샘플의 "한국어로 부를 법한 표현"으로 검색해 현재 누락을 기록:

```bash
cd /Users/al03040455/Desktop/bb2_client
project-brain search "토큰 환불 복구" 2>/dev/null | jq '.results[].object_id'
project-brain search "게임 플레이 모드 종류" 2>/dev/null | jq '.results[].object_id'
```

Expected: 대상 id가 top 결과에 **없거나 약함**(= 메울 갭이 실재함을 확인). 없으면 그 샘플은 갭이 아니므로 교체.

- [ ] **Step 3: 동의어 백필 노트 작성 + ingest**

`updates[]` 묶음을 만들어 적재한다. `expected_updated_at`은 Step 1 출력의 현재 값을 그대로:

```json
[
  {"id": "g.stage-clear-token.clear-pass-ticket-recover",
   "expected_updated_at": "<Step1 값>",
   "union": {"synonyms": ["클리어 패스 티켓 복구", "토큰 환불 복구", "비정상 종료 토큰 환불"]}}
]
```

(엔진 build/ingest 경로로 적용 — 스킬 `ingest.md` 절차. updates 묶음은 `build`→`ingest`로 흐른다.)

- [ ] **Step 4: 색인 재생성**

```bash
cd /Users/al03040455/Desktop/bb2_client
project-brain index rebuild     # 실모델 배치 임베딩 — 수십 초 정상
```

- [ ] **Step 5: after 측정 — recall 향상 확인**

Step 2와 같은 질의를 다시:

Run: `project-brain search "토큰 환불 복구" 2>/dev/null | jq '.results[].object_id'`
Expected: 대상 id가 이제 top에 **나타남**(recall 향상 = 동의어 효과 실증).

- [ ] **Step 6: precision/거짓양성 가드 회귀 (게이트)**

```bash
cd /Users/al03040455/Desktop/bb2_client
python3 -m unittest discover -s brain/checks -p "test_*.py"   # 실측 가드
project-brain eval --check-ids 2>/dev/null | jq '.summary'    # 기대 id 실존
project-brain eval 2>/dev/null | jq '.summary'                # 골든셋 7종 회귀
```

Expected(게이트 통과 조건):
- 골든셋 7종 통과 수 **유지**(동의어가 기존 적중을 안 깸).
- s5형 거짓양성("없는 엔티티는 없다") 시나리오 **유지** — needs_clarification이 여전히 켜짐.
- `brain/checks` 통과(색인 행 수 변경 시 실측 상수 의식적 갱신 후 같은 커밋에).

게이트 실패(골든셋 회귀·거짓양성 가드 약화) 시: 동의어를 빼고(`git revert` 데이터 커밋) Task 3 규칙을 재검토(일반어가 섞였는지). **통과해야만 Task 5로.**

- [ ] **Step 7: 데이터 레포 커밋**

```bash
cd /Users/al03040455/Desktop/bb2_client
git add brain/
git commit -m "docs(brain): GlossaryTerm 동의어 샘플 백필 + recall/precision 검증 통과"
```

---

## Task 5: (조건부) 전체 백필 — Task 4 게이트 통과 후에만

> Task 4가 통과(recall↑, precision 유지)했을 때만 진행. 실패했으면 이 task는 버린다.
> 이건 엔진 코드가 아니라 **적재 스킬 워크플로 반복** — LLM(에이전트)이 남은 GlossaryTerm의
> 동의어를 Task 3 규칙대로 생성해 `updates union`으로 채우는 일이다.

- [ ] **Step 1:** 남은 GlossaryTerm을 컨텍스트별로 배치 분할(한 번에 한 context).
- [ ] **Step 2:** 각 용어에 Task 3 규칙(한↔영 우선, 일반어 금지)대로 동의어 생성 → `updates union` 노트.
- [ ] **Step 3:** 배치마다 `ingest` → `index rebuild` → `eval`(골든셋 유지 확인). 배치 단위로 롤백 가능하게.
- [ ] **Step 4:** 전체 완료 후 `brain/checks` 색인 행 수 가드 갱신 + 커밋.
- [ ] **Step 5:** 메모리 갱신 — [[hwi-pkm-technique-crosscheck]]에 "동의어 적용 완료" 반영.

---

## Self-Review

**1. 스펙 커버리지:**
- 동의어를 객체에 싣기 → Task 1 ✓
- 기존 객체 백필 통로 → Task 2 ✓
- 적재 스킬 동의어 규칙(한↔영·일반어 금지) → Task 3 ✓
- anchor_df precision 부작용 검증 게이트 → Task 4 ✓
- 전체 백필(조건부) → Task 5 ✓
- "surface.py 변경 불필요·EXTRACTOR_VERSION bump 불필요" → Global Constraints + File Structure에 명시 ✓
- 데이터 레포 회귀 필수 → Task 4 Step 6 + Global Constraints ✓

**2. 플레이스홀더 스캔:** 코드 스텝은 실제 코드 포함(Task 1·2 obj 2줄·allowlist 1줄, Task 3 마크다운 전문). Task 4·5는 데이터 레포 측정/반복이라 명령·기대출력 명시. `expected_updated_at "<Step1 값>"`은 런타임 실값이라 플레이스홀더가 아니라 의도된 참조.

**3. 타입 일관성:** `synonyms`/`aliases`는 전 task에서 `list[str]`. `build_glossary_terms`(생성)·`apply_updates union`(합치기)·`surface._surface_glossary_term`(소비, 변경 안 함) 모두 list 전제 — 일관.

**주의(검증 전 단정 금지):** vault의 "5.5배 오탐감소"는 자유 위키 수치다 — project-brain은 농축 표면이라 효과가 깎인다. Task 4는 recall 향상과 precision 유지를 **이 코퍼스에서 실측**하는 게이트지, 5.5배를 전제하지 않는다.
