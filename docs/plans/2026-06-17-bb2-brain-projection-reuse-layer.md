# Projection 재사용층 (Projection Reuse Lane) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **개정 이력:** v2(2026-06-17) — codex(project-brain 엔진) 합성 검증 리뷰 반영. 블로커 4·중요 3·사소 2 수정: A2 projection_hash 추가 / df 제외·scope 누수 정확 지점 / 채널 전파(eval_recall·cli·eval_harness) / promote task 제거(범용기) / reviewed projection 전용 채널.
> v2.1(2026-06-17) — codex 최종 리뷰 반영. 블로커 1·중요 2 수정: (1) projection은 promote 후에도 `projection_reuse` 채널 유지(채널 이동 아님), A5 cli 라벨을 status별 분리(candidate=재사용 후보(미검증)/reviewed=재사용 브리핑(검증됨)) + reviewed 채널 유지·라벨 테스트 추가 (2) A5 게이트를 `channel="raw"`로 통일(코드·주석 모순 해소 — 앵커 미적용) (3) A4 scope 테스트를 `search_bm25_scoped` 직접 검증으로 교체(옛 테스트는 동어반복).

**Goal:** 한 기능 안에서 조립한 착수 브리핑을 `ContextProjection`(format=prompt_payload)으로 저장해, 비슷한 개발 요구 재방문 시 별도 검색 레인에서 "재사용 후보(미검증)"로 회수하여 §8 재조립을 건너뛴다.

**Architecture:** 엔진(project-brain)에서 ContextProjection을 raw·Insight와 같은 "별도 레인"으로 색인·회수하고(객체 레인 비잠식, df 계산·scope 레인·정본 results 채널 모두에서 분리), 구성 객체가 바뀌면 rebuild에서 걸러낸다. 스킬(bb2-brain-query)이 §8 조립 완료 시 candidate projection을 명시 저장하고, 재방문 시 후보를 먼저 확인해 보강·승격한다.

**Tech Stack:** Python 3.11+ (project-brain, pytest), SQLite FTS5 + sqlite-vec, mecab-ko. 스킬은 마크다운 SKILL.md.

## Global Constraints

- 엔진 레포: `~/Downloads/codes/project-brain` (패키지 `project_brain`, src 레이아웃). 테스트: `pytest`(현재 378 passed 기준 회귀 금지).
- 데이터·스킬 레포: `bb2_client`. 실코퍼스 가드: `brain/checks/`. 골든셋: `brain/eval_scenarios.json`(현재 eval 8/8 회귀 금지).
- ContextProjection은 **새 kind를 만들지 않고 기존 kind를 확장**한다. REQUIRED 필드(schema.py:22-23): `context_id, format, source_object_ids, source_content_hash, projection_hash, generated_at, generated_by, stale_policy`. **`projection_hash`는 필수** — 빠지면 `validate_object()` 실패(codex 합성 검증 확인). `format ∈ {context_md, prompt_payload}`, `stale_policy`는 `"fail_on_manual_edit"`만 허용.
- **projection은 status(candidate/reviewed)와 무관하게 전용 채널(projection_reuse)로만 노출**한다 — `eval_recall`의 정본 `results`/`candidates`에 절대 섞이면 안 된다(promote 후에도). 이유: `eval_recall`(search.py:667-674)이 reviewed/candidate non-Insight를 정본 채널로 보내므로, projection을 kind로 따로 빼지 않으면 정본 답변에 섞인다.
- 검색 점수 계산(앵커 df)에서 projection 제외는 `_OBJECT_LANE_EXCLUDED`가 아니라 **`_document_frequency`의 SQL**(search.py:555-569, 현재 RAW·Insight 제외)에서 한다. scope 질의 누수는 **`search_bm25_scoped`**(search_index.py:404, 현재 RAW만 제외)에서 막는다.
- projection 검색 본문은 **객체 필드(`reuse_payload`)에 둔다**(raw의 surface_text 운반은 store 없는 raw 전용 예외 경로 — codex 확인). `extract_surface`가 그 필드를 표면으로 뽑고, rebuild가 `documents.surface_text`를 파생 생성한다.
- candidate projection 저장은 스킬의 명시 단계(검색 중 자동 저장 금지). 낡음 거르기 1차 방어선은 rebuild 시점.
- 정확한 줄 번호는 코드가 바뀌므로 구현 시 재확인. 인용 심볼은 2026-06-17 기준 실재 확인(직접 + codex 합성 검증).

## File Structure

**엔진 (project-brain/src/project_brain/)**
- `surface.py` — `_surface_context_projection` 추가(prompt_payload 본문), `_EXTRACTORS` 등록, `EXCLUDED_KINDS`에서 ContextProjection 제거.
- `search.py` — `PROJECTION_KIND` 상수, `_OBJECT_LANE_EXCLUDED`에 추가, `recall()` projection 융합 블록, `_document_frequency` SQL에 projection 제외, `eval_recall()` projection_reuse 채널 + 정본 채널에서 projection 제외.
- `search_index.py` — `search_bm25_scoped` kind 제외에 projection 추가, `rebuild()`·`compute_corpus_fingerprint()`에서 stale projection 제외.
- `cli.py` — `_run_search()` 출력에 projection_reuse 채널 + trust_label "재사용 후보(미검증)".
- `eval_harness.py` — raw/advisories처럼 projection_reuse 채널 인지(필요 시).
- `context_projection.py` — `build_reuse_projection`(요구 부분집합, candidate, projection_hash 포함).
- `tests/` — 대응 테스트.

**스킬 (bb2_client/.agents/skills/)**
- `bb2-brain-query/SKILL.md` — §8 회수·저장·promote·라벨.
- `brain/eval_scenarios.json` — 재사용 시나리오.

**제거됨(v1 대비):** promote task — `promote()`(promote.py:70)는 single_object에서 kind를 안 가리는 범용 승격기라 ContextProjection이 이미 그대로 승격되고 `validate_object`를 통과한다(codex 합성 검증). stale candidate 승격 거부는 CLI의 merged-store lint 단계(cli.py:129 → lint.py:143)가 이미 막는다. 별도 promote 작업 불필요.

---

## Phase A — 엔진 (project-brain)

### Task A1: ContextProjection 검색 표면 추출기 + 별도 레인 색인 진입

**Files:**
- Modify: `src/project_brain/surface.py` (EXCLUDED_KINDS, _EXTRACTORS, 새 추출기)
- Modify: `src/project_brain/search.py` (PROJECTION_KIND, _OBJECT_LANE_EXCLUDED)
- Test: `tests/test_surface.py`

**Interfaces:**
- Produces: `_surface_context_projection(obj, store) -> list[str]`, `PROJECTION_KIND = "ContextProjection"`(search.py). `extract_surface(prompt_payload_projection, store)`가 None 아닌 표면 반환; `format != "prompt_payload"`이면(예: context_md 덤프) `[]` → None.
- Consumes: 선례 `_surface_insight`(surface.py:147-155), `_EXTRACTORS`(surface.py:159-169).

- [ ] **Step 1: 실패 테스트** — `tests/test_surface.py`

```python
def test_context_projection_prompt_payload_surface():
    store = _store_with([{
        "id": "projection.sally-canoe.result-popup-rank.reuse",
        "kind": "ContextProjection",
        "context_id": "context.sally-canoe",
        "format": "prompt_payload",
        "status": "candidate",
        "title": "샐리 결과 팝업 순위 표시 착수 브리핑",
        "reuse_payload": "데이터 출처: RaceInfo recordMap. 확장 지점: PopupSallyCanoeResult.",
        "source_object_ids": ["mapping.sally-canoe.race-end-result-achieve"],
        "source_content_hash": "x", "projection_hash": "y",
        "generated_at": "2026-06-17T00:00:00Z", "generated_by": "test",
        "stale_policy": "fail_on_manual_edit",
    }])
    obj = store.get("projection.sally-canoe.result-popup-rank.reuse")
    surface = extract_surface(obj, store)
    assert surface is not None and "PopupSallyCanoeResult" in surface

def test_context_md_projection_has_no_surface():
    # context_md 덤프 projection은 검색 표면 없음(None) — 재사용 레인 대상 아님
    store = _store_with([{**_min_projection(), "format": "context_md"}])
    assert extract_surface(store.get(_MIN_PROJECTION_ID), store) is None
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_surface.py::test_context_projection_prompt_payload_surface -v`
Expected: FAIL — ContextProjection이 EXCLUDED_KINDS라 None.

- [ ] **Step 3: 구현**

`surface.py`:
1. `EXCLUDED_KINDS`(L29-31)에서 `"ContextProjection"` 제거.
2. 추출기 추가:
```python
def _surface_context_projection(obj, store) -> list[str]:
    # prompt_payload 재사용 projection만 검색 표면을 가진다. context_md 덤프는 None.
    if obj.get("format") != "prompt_payload":
        return []
    parts: list[str] = []
    for field in ("title", "reuse_payload"):
        s = _norm_str(obj.get(field))
        if s is not None:
            parts.append(s)
    return parts
```
3. `_EXTRACTORS`(L159)에 `"ContextProjection": _surface_context_projection,` 추가.

`search.py`:
4. `PROJECTION_KIND = "ContextProjection"` 정의(INSIGHT_KIND 옆 L91), `_OBJECT_LANE_EXCLUDED`(L93)를 `(RAW_KIND, INSIGHT_KIND, PROJECTION_KIND)`로.

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_surface.py -v`
Expected: PASS. `tests/test_surface.py:183` 인근 EXCLUDED 케이스 테스트도 ContextProjection 제거 반영해 수정 후 PASS.

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/surface.py src/project_brain/search.py tests/test_surface.py
git commit -m "feat(projection): prompt_payload surface extractor, move ContextProjection to separate lane"
```

### Task A2: 요구 부분집합 prompt_payload candidate 빌더 (projection_hash 포함)

**Files:**
- Modify: `src/project_brain/context_projection.py`
- Test: `tests/test_context_projection.py`

**Interfaces:**
- Produces: `build_reuse_projection(store, *, context_id, requirement_key, source_object_ids, reuse_payload, title, generated_at, generated_by) -> dict` — `kind="ContextProjection"`, `format="prompt_payload"`, `status="candidate"`, `id=f"projection.{context_key}.{requirement_key}.reuse"`, **`source_content_hash`**(source_object_ids로 계산), **`projection_hash`**(reuse_payload 텍스트의 sha256 — 필수 필드), `stale_policy="fail_on_manual_edit"`.
- Consumes: 선례 `build_context_projection`(context_projection.py:100-139) — `source_content_hash = _sha256_text("\n".join(_stable_json(obj) ...))`, `projection_hash = _sha256_text(content)`(L115).

- [ ] **Step 1: 실패 테스트** — `tests/test_context_projection.py`

```python
def test_build_reuse_projection_validates():
    from project_brain.schema import validate_object
    store = _store_with([_context("context.sally-canoe", context_key="sally-canoe"),
                         _mapping("mapping.sally-canoe.race-end-result-achieve", "context.sally-canoe")])
    proj = build_reuse_projection(
        store, context_id="context.sally-canoe", requirement_key="result-popup-rank",
        source_object_ids=["mapping.sally-canoe.race-end-result-achieve"],
        reuse_payload="데이터 출처: RaceInfo recordMap...", title="샐리 결과 팝업 순위 표시",
        generated_at="2026-06-17T00:00:00Z", generated_by="bb2-brain-query")
    assert proj["status"] == "candidate"
    assert proj["format"] == "prompt_payload"
    assert proj["id"] == "projection.sally-canoe.result-popup-rank.reuse"
    assert proj["projection_hash"]  # 필수 — 비면 validate 실패
    assert proj["source_content_hash"]
    assert validate_object(proj) == []  # 스키마 통과
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_context_projection.py::test_build_reuse_projection_validates -v`
Expected: FAIL — `build_reuse_projection` 미정의.

- [ ] **Step 3: 구현** — `context_projection.py`에 추가:
```python
def build_reuse_projection(store, *, context_id, requirement_key, source_object_ids,
                           reuse_payload, title, generated_at, generated_by) -> dict:
    context = store.get(context_id)
    source_content_hash = _sha256_text(
        "\n".join(_stable_json(store.get(oid)) for oid in source_object_ids))
    projection_hash = _sha256_text(reuse_payload)
    ckey = context.get("context_key", context_id)
    return {
        "id": f"projection.{ckey}.{requirement_key}.reuse",
        "kind": "ContextProjection",
        "schema_version": SCHEMA_VERSION,
        "status": "candidate",
        "poc_priority": "P0",
        "truth_role": "index",
        "title": title,
        "created_at": generated_at,
        "updated_at": generated_at,
        "tags": context.get("tags", []),
        "evidence_refs": [],
        "context_id": context_id,
        "format": "prompt_payload",
        "reuse_payload": reuse_payload,
        "output_locator": f"indexes/context_projections/{ckey}.{requirement_key}.reuse.txt",
        "source_object_ids": list(source_object_ids),
        "source_content_hash": source_content_hash,
        "projection_hash": projection_hash,
        "generated_at": generated_at,
        "generated_by": generated_by,
        "stale_policy": "fail_on_manual_edit",
    }
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_context_projection.py -v`
Expected: PASS(스키마 통과 포함).

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/context_projection.py tests/test_context_projection.py
git commit -m "feat(projection): build_reuse_projection (candidate, projection_hash, requirement subset)"
```

### Task A3: recall 별도 레인 회수 융합

**Files:**
- Modify: `src/project_brain/search.py` (`recall()` projection 채널 분리 + 융합 블록)
- Test: `tests/test_search.py`

**Interfaces:**
- Consumes: A1의 `PROJECTION_KIND`, `_OBJECT_LANE_EXCLUDED`.
- Produces: `recall(...)` hits에 projection 적중이 **객체·raw 적중 뒤**로 append(kind=ContextProjection, linked 빈 구조, surface는 색인 surface_text).

- [ ] **Step 1: 실패 테스트** — `tests/test_search.py`

```python
def test_projection_in_recall_after_objects():
    hits = recall(query="샐리 결과 팝업 순위 표시", db_path=DB, store=STORE)
    kinds = [h["kind"] for h in hits]
    assert "ContextProjection" in kinds
    proj_idx = kinds.index("ContextProjection")
    obj_idx = next(i for i, k in enumerate(kinds)
                   if k not in ("ContextProjection", "RawChunk", "Insight"))
    assert obj_idx < proj_idx
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_search.py::test_projection_in_recall_after_objects -v`
Expected: FAIL — projection 융합 블록 부재.

- [ ] **Step 3: 구현** — `search.py` `recall()`:
1. raw·Insight 채널 분리(L397-400) 옆에 추가:
```python
projection_bm25 = [r for r in bm25_all if r.get("kind") == PROJECTION_KIND][:CHANNEL_TOP_N]
projection_vector = [r for r in vector_all if r.get("kind") == PROJECTION_KIND][:CHANNEL_TOP_N]
```
2. raw 융합 블록(L471-499) **동형**으로 projection 융합 블록 추가 — hits에 **객체·raw 뒤** append, `linked` 빈 구조, scope 있으면 context_id 필터, `kind=PROJECTION_KIND`. (Insight 융합 블록이 있으면 그 뒤, 없으면 raw 뒤.)

> 주의: 정본 results 채널 분리는 A5(eval_recall)에서 한다. recall()은 hits에 모든 레인을 순서대로 담기만 한다.

- [ ] **Step 4: 통과 + 회귀**

Run: `pytest tests/test_search.py -v && pytest`
Expected: PASS, 기존 378 회귀 없음.

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/search.py tests/test_search.py
git commit -m "feat(projection): recall separate lane fusion (after object/raw hits)"
```

### Task A4: df 계산·scope 레인에서 projection 제외 (정본 비잠식)

**Files:**
- Modify: `src/project_brain/search.py` (`_document_frequency` SQL)
- Modify: `src/project_brain/search_index.py` (`search_bm25_scoped` kind 제외)
- Test: `tests/test_search.py`, `tests/test_search_index.py`

**Interfaces:**
- Consumes: `PROJECTION_KIND`.
- Produces: 앵커 df 계산이 projection 행을 세지 않음 / scope 질의의 BM25 객체 레인에 projection이 안 섞임.

**선례 (실측):** `_document_frequency`(search.py:555-569)는 SQL 파라미터 `(expr, RAW_KIND, INSIGHT_KIND)`로 raw·Insight df를 제외(L569). `search_bm25_scoped`(search_index.py:372-405)는 `WHERE context_id = ? AND kind != ?`, `(scope, RAW_KIND)`로 RAW만 제외(L404-405).

- [ ] **Step 1: 실패 테스트** — `tests/test_search.py`

```python
def test_projection_excluded_from_anchor_df():
    # projection 본문에만 있는 희귀 토큰의 df가 0(존재 안 함)으로 잡힌다 — projection 행 미집계.
    # raw/Insight df 제외 테스트와 동형. (구현 시 기존 df 제외 테스트 패턴을 따른다)
    df = _document_frequency(conn, RARE_TOKEN_ONLY_IN_PROJECTION)
    assert df == 0

def test_scoped_bm25_excludes_projection():  # tests/test_search_index.py
    # scope 객체 레인(search_bm25_scoped)이 projection 행을 안 집는다 — 직접 검증.
    # (옛 recall 기반 테스트는 obj_lane 자체가 ContextProjection을 이미 빼서 동어반복이었다 — codex 지적.)
    # 시그니처(실측): search_bm25_scoped(db_path, query, scope, top_n=50) -> {"results", "warnings"}.
    # SQL이 WHERE context_id=? AND kind NOT IN (?, ?)로 RAW·PROJECTION 제외해야 통과.
    out = search_bm25_scoped(DB, "샐리 결과 팝업", scope="context.sally-canoe")
    assert all(r.get("kind") != "ContextProjection" for r in out["results"])
```

> 위 scope 테스트는 `search_bm25_scoped`가 있는 `tests/test_search_index.py`에 둔다. df 제외 테스트(`test_projection_excluded_from_anchor_df`)는 `tests/test_search.py`에 둔다.

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_search.py::test_projection_excluded_from_anchor_df -v`
Expected: FAIL — `_document_frequency`가 projection 행을 df에 셈.

- [ ] **Step 3: 구현**
1. `search.py` `_document_frequency`(L555-569): SQL의 kind 제외 목록에 PROJECTION_KIND 추가 — `(expr, RAW_KIND, INSIGHT_KIND, PROJECTION_KIND)`로(SQL의 `kind NOT IN (?, ?, ?)` 형태에 맞춰 placeholder 추가).
2. `search_index.py` `search_bm25_scoped`(L404-405): `WHERE context_id = ? AND kind NOT IN (?, ?)`로 바꾸고 `(scope, RAW_KIND, PROJECTION_KIND)`. (Insight는 기존대로 scope 레인에 남김 — 객체라 의도된 포함. projection만 추가 제외.)

- [ ] **Step 4: 통과 + 회귀**

Run: `pytest tests/test_search.py tests/test_search_index.py -v && pytest`
Expected: PASS, 기존 회귀 없음(특히 골든셋 회귀 테스트).

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/search.py src/project_brain/search_index.py tests/
git commit -m "feat(projection): exclude projections from anchor df and scoped object lane"
```

### Task A5: eval_recall projection_reuse 채널 + CLI/하네스 전파

**Files:**
- Modify: `src/project_brain/search.py` (`eval_recall`)
- Modify: `src/project_brain/cli.py` (`_run_search`)
- Modify: `src/project_brain/eval_harness.py` (채널 인지, 필요 시)
- Test: `tests/test_search.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `PROJECTION_KIND`, A3의 recall hits.
- Produces: `eval_recall(...)` 반환 dict에 `projection_reuse` 키 추가; **`results`/`candidates`에서 projection 제외**(status 무관). `_run_search` 출력에 `projection_reuse`(trust_label "재사용 후보(미검증)").

**선례 (실측):** `eval_recall`(search.py:636-694) — results는 `status=="reviewed" and kind != INSIGHT_KIND and _gate_pass(..., "reviewed")`(L667-670), candidates는 candidate 버전(L671-674), raw_excerpts(L675-677), advisories(reviewed Insight, L684-687). `_run_search`(cli.py:316-356)는 results/candidates/raw_excerpts/needs_clarification 출력(L350-355), raw_excerpts에 trust_label "원문 발췌(미검수)" 부착(L348).

- [ ] **Step 1: 실패 테스트** — `tests/test_search.py`

```python
def test_eval_recall_projection_in_own_channel_not_results():
    # candidate projection도 results/candidates가 아니라 projection_reuse로만 나온다.
    resp = eval_recall(query="샐리 결과 팝업 순위 표시", db_path=DB, store=STORE)
    assert "projection_reuse" in resp
    assert all(h["kind"] != "ContextProjection" for h in resp["results"])
    assert all(h["kind"] != "ContextProjection" for h in resp["candidates"])
    assert any(h["kind"] == "ContextProjection" for h in resp["projection_reuse"])

def test_eval_recall_reviewed_projection_stays_in_reuse_channel():
    # 핵심 가드(codex 블로커): promote된(reviewed) projection도 results가 아니라
    # projection_reuse에 남는다 — 채널 이동 없음. DB_REVIEWED_PROJ 픽스처는
    # status="reviewed" projection 1개를 색인에 포함한다.
    resp = eval_recall(query="샐리 결과 팝업 순위 표시", db_path=DB_REVIEWED_PROJ, store=STORE)
    assert all(h["kind"] != "ContextProjection" for h in resp["results"])
    assert any(h["kind"] == "ContextProjection" and h.get("status") == "reviewed"
               for h in resp["projection_reuse"])

def test_cli_projection_label_split_by_status():  # tests/test_cli.py
    # candidate=재사용 후보(미검증), reviewed=재사용 브리핑(검증됨). 채널은 공통.
    out = _run_search("샐리 결과 팝업 순위 표시", db_path=DB_REVIEWED_PROJ)
    labels = {h.get("status"): h["trust_label"] for h in out["projection_reuse"]}
    assert labels.get("reviewed") == "재사용 브리핑(검증됨)"
    if "candidate" in labels:
        assert labels["candidate"] == "재사용 후보(미검증)"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_search.py::test_eval_recall_projection_in_own_channel_not_results -v`
Expected: FAIL — `projection_reuse` 키 없음 + reviewed projection이 results에 섞임.

- [ ] **Step 3: 구현**
1. `search.py` `eval_recall`: results/candidates 필터에 `and h.get("kind") != PROJECTION_KIND` 추가(INSIGHT_KIND 옆 — reviewed projection이 results에, candidate projection이 candidates에 안 새도록 status 무관 제외). 새 채널 추가:
```python
projection_reuse = [h for h in hits
                    if h.get("kind") == PROJECTION_KIND
                    and _gate_pass(h["score"], signals, channel="raw")][:EVAL_CHANNEL_TOP_K]
```
반환 dict에 `"projection_reuse": projection_reuse,` 추가. **게이트는 `channel="raw"`로 통일**(코드·주석 일치) — `_gate_pass`는 `channel in ("candidate","raw")`면 같은 관대한 바닥, `channel=="raw"`면 앵커 df를 건너뛴다(search.py:624-629 실측). projection에 앵커를 걸면 객체 코퍼스에 앵커가 없는 어휘 드리프트 요구(예: "경주"≠"레이스")가 막혀 projection 레인의 존재 이유(어휘 달라도 의미로 재사용 회수 — spec §1 통점)가 깎인다. 라벨이 "미검증/검증됨"이라 부정확 노출의 해도 낮다(raw 면제 논리와 동형). candidate·reviewed 두 status 다 이 한 채널로. needs_clarification 산정엔 안 들어감(results 기반 유지).
2. `cli.py` `_run_search`: raw_excerpts 라벨(L348) 패턴 동형으로 **status별 라벨 분리** —
```python
projection_reuse = [
    {**h, "trust_label": ("재사용 브리핑(검증됨)" if h.get("status") == "reviewed"
                          else "재사용 후보(미검증)")}
    for h in resp.get("projection_reuse", [])
]
```
출력 dict(L350-355)에 `"projection_reuse": projection_reuse,` 추가. 채널은 candidate·reviewed 공통 `projection_reuse`, **라벨만 status로 가른다**(채널 이동 없음).
3. `eval_harness.py`: raw/advisories를 채널로 아는 지점(L27, L168 인근)에 projection_reuse를 동형 추가(시나리오가 채널을 지정할 수 있게). 골든셋 시나리오가 projection_reuse를 안 쓰면 무변경으로도 회귀 없음 — 쓰는 경우만 필요.

- [ ] **Step 4: 통과 + 회귀**

Run: `pytest tests/test_search.py tests/test_cli.py -v && pytest`
Expected: PASS, 기존 378 회귀 없음(특히 eval 8/8 — projection 없을 때 빈 채널).

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/search.py src/project_brain/cli.py src/project_brain/eval_harness.py tests/
git commit -m "feat(projection): projection_reuse channel in eval_recall + CLI + harness, exclude from canonical channels"
```

### Task A6: rebuild·fingerprint에서 stale projection 제외

**Files:**
- Modify: `src/project_brain/search_index.py` (`rebuild`, `compute_corpus_fingerprint`)
- Modify: `src/project_brain/lint.py` (재사용 헬퍼 노출, 선택)
- Test: `tests/test_search_index.py`

**Interfaces:**
- Consumes: `lint._compute_source_content_hash(store, source_object_ids)`(lint.py:18, 실측).
- Produces: `rebuild()`가 stale projection(저장 `source_content_hash` ≠ 현재 재계산)을 색인 제외, `compute_corpus_fingerprint()`도 동일 규칙.

**선례 (실측):** `search_index.py:110 rebuild()`, `:155 surface = extract_surface(obj, store)`, `:273 compute_corpus_fingerprint()`. `lint.py:18 _compute_source_content_hash`, `:149-152` source_content_hash mismatch 검사 존재.

- [ ] **Step 1: 실패 테스트** — `tests/test_search_index.py`

```python
def test_stale_projection_excluded_from_rebuild():
    store = _store_with_projection_and_sources()
    _mutate_source_mapping(store)  # source_content_hash 불일치 유발
    rebuild(brain_root=ROOT, db_path=DB)
    rows = _index_object_ids_of_kind(DB, "ContextProjection")
    assert STALE_PROJECTION_ID not in rows

def test_fresh_projection_included_in_rebuild():
    store = _store_with_projection_and_sources()
    rebuild(brain_root=ROOT, db_path=DB)
    assert FRESH_PROJECTION_ID in _index_object_ids_of_kind(DB, "ContextProjection")
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_search_index.py::test_stale_projection_excluded_from_rebuild -v`
Expected: FAIL — rebuild가 stale 여부 미검사.

- [ ] **Step 3: 구현**
1. `lint.py`의 `_compute_source_content_hash`를 재사용하는 판정 헬퍼(모듈 함수로 import 가능하게):
```python
def projection_is_fresh(store, projection) -> bool:
    return projection.get("source_content_hash") == _compute_source_content_hash(
        store, projection.get("source_object_ids", []))
```
2. `rebuild()`의 객체 순회(L155 인근)에서 `kind == "ContextProjection"`이고 `not projection_is_fresh(store, obj)`이면 `continue`(색인 제외).
3. `compute_corpus_fingerprint()`(L273-300)의 같은 순회에서도 동일 규칙으로 stale projection을 지문 입력에서 제외 — rebuild와 지문이 같은 입력을 봐야 신선도 가드가 어긋나지 않음.

- [ ] **Step 4: 통과 + 회귀**

Run: `pytest tests/test_search_index.py -v && pytest`
Expected: PASS(stale 제외 + fresh 포함), 회귀 없음.

- [ ] **Step 5: 커밋**

```bash
git add src/project_brain/search_index.py src/project_brain/lint.py tests/test_search_index.py
git commit -m "feat(projection): exclude stale projections from rebuild and corpus fingerprint"
```

---

## Phase B — 스킬 (bb2_client)

### Task B1: `bb2-brain-query` §8에 projection 회수 단계 추가

**Files:** Modify `.agents/skills/bb2-brain-query/SKILL.md` (§8)

- [ ] **Step 1: §8 시작에 회수 단계 추가**

```markdown
0. **재사용 후보 먼저 확인** — `project-brain search`로 요구를 질의하면 출력의
   `projection_reuse` 채널("재사용 후보(미검증)")에 이전 착수 브리핑이 잡힐 수 있다.
   후보가 이번 요구와 맞으면(범위·5요소) 그 payload를 토대로 빈 곳만 보강하고 2~4단계
   전체 조립은 생략한다. 없거나 낡았거나 범위가 어긋나면 1~5단계로 새로 조립한다.
   후보는 항상 "확인 필요"로 다루고, 확신은 정본 객체(results) 적중으로 확인한다.
```

- [ ] **Step 2: 검증** — §8 전체를 읽어 0단계가 기존 1~5와 모순 없는지 확인.

- [ ] **Step 3: 커밋**

```bash
git add .agents/skills/bb2-brain-query/SKILL.md
git commit -m "docs(skill): bb2-brain-query §8 add projection reuse retrieval step"
```

### Task B2: `bb2-brain-query` §8에 저장 단계 + 사용 시점 promote + 라벨

**Files:** Modify `.agents/skills/bb2-brain-query/SKILL.md` (§8 끝 + Common Mistakes)

- [ ] **Step 1: §8 끝(§8.5 뒤)에 추가**

```markdown
6. **재사용 저장(조건 충족 시에만)** — 조립이 (가) 한 기능(context)으로 수렴 (나) 5요소를 다 채움
   (다) 구성 객체 id가 확정된 경우에만, candidate projection으로 저장한다(엔진의 reuse projection
   빌더 경유 — context_id + requirement_key + source_object_ids + reuse_payload, projection_hash는
   엔진이 생성). 부분 조립·needs_clarification 단계에선 저장하지 않는다. 저장 후 `project-brain index
   rebuild`로 색인 반영. 구성 객체가 바뀌면 rebuild가 자동으로 그 projection을 색인에서 뺀다(낡음).

7. **사용 시점 승격** — 0단계에서 회수한 재사용 후보가 이번 요구에 실제로 맞았으면 reviewed로
   promote한다(`project-brain promote` — 범용 승격기라 ContextProjection도 그대로 승격되며,
   낡은 candidate는 lint 단계에서 거부된다). reviewed가 돼도 projection은 정본 results가 아니라
   projection_reuse 채널로만 노출되고(채널 이동 없음), 라벨만 "재사용 후보(미검증)"→"재사용
   브리핑(검증됨)"으로 바뀐다. 어긋났으면 promote하지 않는다.
```

- [ ] **Step 2: Common Mistakes 행 추가**

```markdown
| 조립 끝났는데 재사용 저장 안 함 | 한 기능 수렴+5요소+source 확정이면 candidate projection 저장. 부분/clarifying은 금지 |
| 재사용 후보를 확신처럼 답함 | "재사용 후보(미검증)" 라벨 필수. 정본 results 적중으로 확인 후 promote |
```

- [ ] **Step 3: 검증** — 0단계(회수)→1~5(조립)→6(저장)→7(승격) 흐름이 과잉 금지 문구와 충돌 없는지.

- [ ] **Step 4: 커밋**

```bash
git add .agents/skills/bb2-brain-query/SKILL.md
git commit -m "docs(skill): bb2-brain-query §8 add reuse persist + use-time promote + labels"
```

### Task B3: 재사용 골든셋 시나리오 추가

**Files:** Modify `brain/eval_scenarios.json`, 적재 projection은 `brain/indexes/context_projections/` (store.py:56 — ContextProjection은 objects/가 아니라 여기로)

- [ ] **Step 1: 시나리오 추가** — prompt_payload projection 하나를 실코퍼스에 적재한 상태에서, 유사 요구 질의가 `projection_reuse` 채널에 후보를 노출하는지 + 정본 회수(results)가 밀리지 않는지(객체 적중 여전히 앞, projection은 results에 없음) 가드하는 시나리오(예: s11).

- [ ] **Step 2: 색인 후 eval**

Run: `project-brain index rebuild && project-brain eval`
Expected: 신규 시나리오 통과 + 기존 8/8 회귀 없음(총 9/9).

- [ ] **Step 3: 실코퍼스 가드**

Run: `cd brain && python -m pytest checks/`
Expected: PASS.

- [ ] **Step 4: 커밋**

```bash
git add brain/eval_scenarios.json brain/indexes/context_projections/
git commit -m "test(brain): add projection reuse golden scenario (s11), keep prior eval green"
```

---

## Self-Review (v2)

**1. Spec coverage + codex 리뷰 반영:**
- 블로커1 projection_hash → A2(필수 필드 + validate 통과 테스트). ✅
- 블로커2 df 제외(_document_frequency)·scope 누수(search_bm25_scoped) → A4(독립 task). ✅
- 블로커3 채널 전파(eval_recall·cli·eval_harness) → A5(독립 task). ✅
- 블로커4 promote 불필요 → promote task 제거, File Structure에 사유 명시 + B2.7이 기존 범용 promote 사용. ✅
- 중요1 reuse_payload 객체 필드 → A1/A2(채택, Global Constraints 명시). ✅
- 중요2 reuse_payload/requirement_key schema 추가 선택 → 필수 아님(extra 허용), malformed 검증은 후속(미반영=의도). ✅
- 중요3 reviewed projection 전용 채널 → A5(results/candidates에서 status 무관 제외 + projection_reuse). ✅ + Global Constraints 명시.
- 사소1 저장 경로 → B3(brain/indexes/context_projections/). ✅
- 사소2 함수명 → recall()/eval_recall()/_run_search()로 정정(A3/A5). ✅
- A4(옛) rebuild·fingerprint stale → A6(방향 정확, codex 확인). ✅

**v2.1 codex 최종 리뷰 반영:**
- 블로커(라벨/채널 충돌): spec §5·§4.2·§6 + plan A5 라벨을 status별 분리, projection은 promote 후에도 projection_reuse 채널 유지(이동 없음). reviewed 채널 유지·cli 라벨 테스트 추가. ✅
- 중요1(게이트 모순): A5 `channel="raw"`로 통일(앵커 미적용 — search.py:624-629 실측 근거). ✅
- 중요2(scope 테스트 동어반복): `search_bm25_scoped` 직접 검증으로 교체. ✅

**2. Placeholder scan:** df 제외·scope·채널 전파는 codex 합성 검증으로 확인된 정확 지점을 박았다(추측 아님). eval_harness 전파는 "시나리오가 채널 쓸 때만"으로 조건 명시. TBD/TODO 없음.

**3. Type consistency:** `build_reuse_projection`(A2) 시그니처 ↔ B2 저장 인자 일치. `PROJECTION_KIND`(A1) ↔ A3/A4/A5 일치. `projection_reuse` 채널명(A5) ↔ B1/B2/B3 일치. `projection_is_fresh`(A6) ↔ rebuild·fingerprint 재사용 일치.
