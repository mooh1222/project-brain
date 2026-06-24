# brain 코드 근거 정비 — locator 번호표화 + 줄번호 제거 + 탐색 CLI (확정본)

> **For agentic workers:** REQUIRED SUB-SKILL: 구현은 superpowers:subagent-driven-development 또는 superpowers:executing-plans로 Task 단위 진행.
> **상태(2026-06-24): 확정.** route(architect) 최종 검토 통과 + 사용자 결정 반영. 이 문서는 `2026-06-24-codelocator-locator-object-and-optional-lines.md`를 대체한다.

**Goal:** 코드 근거의 위치 정보를 "코드 위치 장부(CodeLocator) 한 곳에만 두고, 근거 책갈피(EvidenceRef)는 그 장부를 id로 가리키게(번호표)" — 원래 설계 의도로 되돌린다. 안 읽고 안 갱신되는 줄번호는 적재·저장에서 없앤다. 회상으로 찾은 객체에서 그래프 연결을 따라 탐색하는 CLI(`show`)를 추가한다.

---

## 확정된 결정 (decision log)

1. **설계와 틀어져 있었음(확인됨).** 정본(spec §6.2)은 code 책갈피의 `locator`를 `code_locator_id` **참조**로 두려 했으나, `build`와 레거시 데이터가 좌표를 **복사**(문자열 `"path:line"` 또는 객체 `{path,symbol,line,line}`)하는 쪽으로 drift. 번호표화 = 설계 복원.
2. **Part A(엔진), Part C(CLI) — 지금 구현.** route 판정 CLEAR + 검증 완료.
3. **기존 데이터 일괄 변경(locator 번호표화 + 줄번호 제거) — 미룸.** 그 locator 내부는 색인·회상·랭킹·답변 어디서도 안 읽혀(검증됨) **실익 0**이고, Part A가 이미 신규 데이터의 drift를 발원지에서 막는다. 안 읽는 데이터를 일괄 편집할 이유가 없다. **착수 방아쇠: 그 칸을 실제로 읽는 기능(예: 답변에 출처 좌표 표시·점프)이 생길 때** 그때 한 번에 정비.

## route 최종 검토 결과 (완료, 2026-06-24)

- 검증: 엔진 레포 + 데이터 레포(`bb2_client/brain/`) 둘 다 직접 열어 실데이터 카운팅.
- **수치 전부 정확 확인**: code_locator evref 532(문자열 337 / 객체 195 = 4키 189 + 6키 6), CodeLocator 594(줄번호 591/없음 3), 골든셋·checks 의존 0.
- **판정**: Part A = CLEAR, Part C = CLEAR, Part B(일괄 마이그레이션) = BLOCK(전수 유일 짝짓기 가정이 데이터로 깨짐).
- **내(main) 독립 검증·보정**:
  - 진짜 구조적으로 단일 번호표 불가인 건 **~45건**(멀티좌표 자유텍스트 ~39 + orphan 6)이지, route의 "모호 105"가 전부 구조적인 건 아님 — 나머지 ~66은 단일좌표인데 자동매칭만 실패(정밀 매칭하면 풀림).
  - 멀티좌표 책갈피도 짝 장부가 **이미 존재**(예: `mapping.sally-canoe.alert-popups-event-end-notice` → hpp·cpp 장부 2개)라, 복수참조 모델이면 "이미 있는 장부 가리키기"라 수술 아님.
  - 결론적으로 **B를 지금 할지 말지는 "실익 0" 때문에 미루는 게 맞다**는 게 내 판단이고, 사용자가 미룸으로 확정.

## Global Constraints

- 결정론 유지(테스트 실모델 금지, StubEmbedder). Part A는 순수 dict 변환이라 모델 무관.
- Part A·C는 **합성 테스트로 닫는다. 실코퍼스 회귀 불필요** — locator 내부·줄번호는 회상·검색·답변에 안 쓰이고(검증됨), 기존 데이터는 안 건드림.
- 정본: `docs/specs/2026-05-27-bb2-brain-object-model-design.md` (§6.2 EvidenceRef, §10.1 CodeLocator, §13 관계).
- 브랜치 `fix/codelocator-locator-object-optional-lines`에 이미 커밋된 2개(`7d8d131` locator를 `{path,symbol,line,line}`로, `ac615e3` line 입력 선택값화)는 **이 확정본으로 재정비**한다(아래 Part A).

---

## Part A — 엔진: 책갈피 locator를 번호표로 + CodeLocator 줄번호 제거 〔지금〕

**대상:** `src/project_brain/assembly.py` `build_code_evidence`(51~81), `_ITEM_REQUIRED`(254 부근), 영향 테스트.

**목표 코드(`build_code_evidence`):**
```python
        loc = {
            "id": derive_id("CodeLocator", ctx, key),
            "kind": "CodeLocator", "status": "reviewed", "truth_role": "reference",
            "title": quote[:120], "repo": repo, "path": a["path"], "symbol": a["symbol"],
            "locator_source": a.get("locator_source", "rg"),
            "commit_sha": commit, "verified_at": now,
        }
        ev = {
            "id": derive_id("EvidenceRef", ctx, key),
            "kind": "EvidenceRef", "status": "reviewed", "truth_role": "reference",
            "title": quote[:120], "evidence_manifest_id": a["manifest"],
            "ref_type": "code_locator", "locator": {"code_locator_id": loc["id"]},
            "summary": quote[:500],
        }
```
- CodeLocator(`loc`)에서 `line_start`/`line_end` **삭제**, 입력에서도 안 읽음.
- EvidenceRef.locator = `{"code_locator_id": loc["id"]}` (번호표). `loc["id"]`가 같은 루프의 짝 CodeLocator id라 100% 존재(route 확인).
- `_ITEM_REQUIRED["code_anchors"]`는 `("key","path","symbol","manifest")` 유지(줄번호 입력 불요).

**세부 (route 합의):**
- **스키마는 줄번호를 "금지" 말고 "무시"**: `CodeLocator` 필수는 `("repo","path","locator_source","verified_at")`(`schema.py:18`)라 줄번호 없어도 통과. 줄번호를 거부하는 규칙은 **추가하지 않는다**(이미 줄번호 없는 CodeLocator 3건 선재 + spec optional). `build`가 안 만들 뿐.
- **`stale_check` "line 불변" 테스트 정리**: `test_stale_check.py`의 line 불변 단언(312-325, 421-422)은 모델에서 line이 사라지면 공허 → 제거/정리. stale_check 로직은 `commit_sha`+`path`만 쓰므로(`stale_check.py:122-145`) line 제거가 판정을 안 깸.

**검증/성공 기준 (TDD):**
1. (수정) `test_assembly.py` locator 단언 → `{"code_locator_id": "code.ctx.hit-hook"}`, CodeLocator에 `line_start`/`line_end` **없음** 단언.
2. 줄번호 없는 code_anchor로 `build` 성공 + locator = `{"code_locator_id": ...}`.
3. 전체 합성 테스트 통과(특히 stale_check는 line 단언 정리 후 통과).

---

## Part C — 탐색 CLI: `show <id>` 추가 + `search` 이웃에 제목 〔지금〕

**배경:** 회상으로 찾은 객체에서 그래프 연결을 따라 탐색하려는데, 단일 객체를 id로 펼쳐보는 커맨드가 없어 JSON 파일을 직접 열어야 함. `search`는 이미 이웃(`linked`)을 동반하나 이웃이 맨 id라 무엇인지 가늠 어려움.

**C-1. `show <id>` 서브커맨드 (신규):**
- `cli.py`에 `_run_show` 추가 + `main()` 분기 등록(기존 `_run_*` 패턴).
- 동작: store에서 id 조회 → 객체 본문(읽기 좋은 형태) + 연결 이웃(엣지 필드 `code_locator_ids`·`evidence_refs`·`glossary_term_ids`·`decision_record_ids`·`affected_*` 등)을 **`[종류] id — 한 줄 제목`**으로 표시.
- 제목 근거: 모든 객체는 `title` 필수(`schema.py` `BASE_REQUIRED`).
- 성공 기준: 합성 store에 객체+이웃 넣고 `show <id>`가 본문 + 이웃 id·title·종류 출력.

**C-2. `search` 이웃에 제목 (개선) — `_build_linked`에 단다 (route 권고):**
- `search.py:156-192 _build_linked`가 만드는 이웃에 `title` 추가. code_locators는 이미 store 조회 중이라 `c.get("title")` 한 줄; related_object_ids는 `{object_id, title}` dict화.
- 소비자 무영향 확인(route): `eval_harness._linked_ids`(`eval_harness.py:101-110`)는 str/dict 모두 받아 id만 추출 → title 추가 무시됨. `router`는 `object_id`로 재조회 → 무영향.
- related를 dict화하면 `test_search.py`/`test_eval_harness.py`의 related 형식 단언 같이 갱신.

**범위 제한(YAGNI):** 다단계 자동 펼침(`expand`/traverse) 커맨드는 안 만든다. `search`(입구)+`show`(이동)로 손수 탐색해보고 번거로우면 그때.

---

## Part B — 기존 데이터 정비 〔미룸 / DEFERRED〕

**결정: 지금 하지 않는다.** locator 내부는 안 읽혀 통일해도 검색·답변이 1도 안 바뀌고(실익 0), Part A가 신규 데이터 drift를 막으므로 안 읽는 데이터를 일괄 편집할 이유가 없다. 줄번호 제거(기존 데이터)도 같은 이유 + evref 객체 locator(189건)에 남는 줄번호까지 다 치우려면 결국 locator 정비와 묶이므로, **기존 데이터 변경은 통째로 미룬다.**

**착수 방아쇠:** locator 좌표를 실제로 읽는 기능(답변에 `파일:줄` 표시·점프 등)이 엔진에 생길 때. 그때 한 번에:

**그때 닫아야 할 것(검토 시 발견, 보존용):**
1. **짝짓기 실측**: 532건 = 유일확정 ~421 / 다대다모호 ~105 / orphan 6. 단일 번호표로 **구조적 불가 ~45건**(멀티좌표 자유텍스트 ~39 + orphan 6).
2. **모델 결정(설계)**: 한 근거가 코드 여러 곳을 가리키는 게 정당한 패턴이므로(hpp+cpp 등), `code_locator_id` 단수 유지(+멀티좌표는 evref 분할) vs `code_locator_ids` 복수 — 데이터 현실엔 복수가 더 맞음. 멀티좌표 책갈피의 짝 장부는 대개 **이미 존재**해 복수로 가면 정보 손실 없음.
3. **orphan 6건**(좌표 아님: `"PR #7163"`, `"git grep ..."`, 디렉토리 설명)은 수동 처리.
4. 안전: 백업 → dry-run diff → 적용. 검증 기준은 "변환 후 회상·eval 결과 동일"(안 읽으니 자동 충족).

---

## 구현 순서 (지금)

1. **Part A** (엔진, 합성 테스트로 닫힘) — 먼저. 브랜치의 기존 2커밋을 이 목표로 재정비.
2. **Part C** (CLI, 엔진 독립) — A와 병행 가능.
3. (Part B는 방아쇠 전까지 보류.)
