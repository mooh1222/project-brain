# project-brain 범용 조립 도구 (build + assembly) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** brain 적재 시 매번 손으로 짜던 "구조화 노트 → brain 객체 묶음" 조립을 엔진의 `project-brain build` 명령 + `project_brain.assembly` 라이브러리 하나로 대체한다.

**Architecture:** `assembly.py`가 노트(JSON)를 받아 완성 객체 묶음 + 기존 대비 diff를 만들지만 **저장은 하지 않는다**. 저장은 기존 `ingest`가 담당한다. 조립은 기계적 변환만 한다 — id 파생·객체 연결·근거 묶기·끊긴 참조 검사. 의미 판단(supersede·강등·충돌 해소·이력 판정)은 절대 하지 않는다(그건 적재하는 에이전트가 노트에 명시). 기존 객체 갱신(`updates`)은 set(scalar 교체)·union(list 합치기) 2종만 허용하고, 의미 필드를 고치면 근거 동반을 강제하며, 낙관적 잠금(`expected_updated_at`)을 build 시점과 ingest 저장 직전 두 번 검사한다.

**Tech Stack:** Python 3 (표준 라이브러리만 — jsonschema 의존성 추가 없이 수동 검증), argparse, 기존 `project_brain.objbase.base` / `schema.validate_object` / `lint.lint_store` / `store.BrainStore` 재사용.

**구현 대상 레포:** 엔진 레포 `~/Downloads/codes/project-brain` (Task 1~7, 8의 ingest 부분). 문서 갱신만 BB2 레포 `~/Desktop/bb2_client` (Task 8의 reference 부분).

**설계 출처:** codex(bb2_brain surface)와 3턴 비판 토론 합의 (2026-06-16). 핵심 합의: 같은 코어를 CLI·라이브러리 두 표면으로 / 노트는 판단 결과 양식이지 프로그래밍 언어 아님 / updates 1차 포함하되 가드 다중 / TOCTOU(검사–저장 시점차) 막는 preconditions 재검사.

---

## File Structure

**엔진 레포 (`~/Downloads/codes/project-brain`):**
- Create: `src/project_brain/assembly.py` — 조립 코어 (id 파생·노트 변환·refs resolve·updates·2층 검증·diff). 단일 책임: 노트→객체묶음 변환.
- Modify: `src/project_brain/cli.py` — `_run_build` 추가 + `main()` dispatch 한 줄.
- Modify: `src/project_brain/ingest.py` — `ingest()`에 `preconditions` 인자 + 저장 직전 재검사.
- Create: `tests/test_assembly.py` — 조립 코어 단위 테스트.
- Modify: `tests/test_ingest.py` — preconditions 테스트 추가.
- Modify: `tests/test_cli.py` — build CLI 테스트 추가.

**BB2 레포 (`~/Desktop/bb2_client`):**
- Modify: `.agents/skills/bb2-brain-ingest/references/ingest-tools.md` — "노트 작성 → build → ingest → 색인/평가/검색" 절차.
- Modify: `.agents/skills/bb2-brain-ingest/references/system-domain-playbook.md` — §1 "결정론적 조립"을 손스크립트 대신 build 호출로 갱신.

**노트 스키마 (입력 형식, 코드 아님 — 참조용):**
```jsonc
{
  "context": { "key": "disturb-bubble-system", "commit": "183f4ee134",
               "now": "2026-06-16T00:00:00Z", "repo": "bb2_client" },
  "sources": [ { "id": "manifest.x.session-...", "source_type": "session",
                 "title": "...", "locator": "...", "captured_by": "user-statement",
                 "redaction_status": "approved" } ],
  "glossary": [ { "key": "hit", "term": "hit (직접 타격)", "definition": "...",
                  "evidence_refs": ["evref.x.hit-hook", "evref.x.hit-session"] } ],
                  // evidence_refs = 이미 만들어질/만들 evref id를 직접 적는다.
                  // code 근거는 code_anchors가 evref.<ctx>.<key>로 만들어 주고,
                  // session 진술 같은 비-code 근거 EvidenceRef는 extra_objects로 직접 넣어 그 id를 여기서 가리킨다.
  "code_anchors": [ { "key": "hit-hook", "path": "...", "symbol": "...",
                      "line_start": 217, "line_end": 217, "quote": "...",
                      "manifest": "manifest.x.code-v2" } ],
  "mappings": [ { "key": "...", "canonical_summary": "...", "meaning": "...",
                  "boundary": "...", "glossary_term_refs": ["near_pop_hook"],
                  "glossary_keys": ["hit"], "code_evref_keys": ["..."] } ],
  "refs": { "terms": { "near_pop_hook": { "id": "g.disturb-bubble-system.do-disturb-on-near-bubble-pop",
                                          "expect": { "kind": "GlossaryTerm", "status": "reviewed" } } } },
  "updates": [ { "id": "mapping.x.hook-catalog", "expected_updated_at": "2026-06-16T00:00:00Z",
                 "set": { "meaning": "..." }, "union": { "glossary_term_ids": ["g.x.hit"] },
                 "evidence_unchanged": true } ],
  "extra_objects": [ /* 노트로 못 담는 완성 객체 직접 (탈출구) */ ]
}
```

---

## Task 1: assembly 코어 — id 파생 + glossary 변환

조립의 기본 단위. 노트의 `glossary[]` 항목을 GlossaryTerm 객체로 변환하고 id를 규칙대로 만든다.

**Files:**
- Create: `~/Downloads/codes/project-brain/src/project_brain/assembly.py`
- Test: `~/Downloads/codes/project-brain/tests/test_assembly.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assembly.py
import unittest
from project_brain.assembly import derive_id, build_glossary_terms

NOW = "2026-06-16T00:00:00Z"


class DeriveIdTest(unittest.TestCase):
    def test_glossary_id(self):
        self.assertEqual(derive_id("GlossaryTerm", "disturb-bubble-system", "hit"),
                         "g.disturb-bubble-system.hit")

    def test_mapping_id(self):
        self.assertEqual(derive_id("DomainMapping", "ctx", "k"), "mapping.ctx.k")

    def test_code_and_evref_id(self):
        self.assertEqual(derive_id("CodeLocator", "ctx", "a"), "code.ctx.a")
        self.assertEqual(derive_id("EvidenceRef", "ctx", "a"), "evref.ctx.a")


class BuildGlossaryTest(unittest.TestCase):
    def test_builds_reviewed_term_with_evidence(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc", "now": NOW, "repo": "bb2_client"},
            "glossary": [{"key": "hit", "term": "hit (직접 타격)", "definition": "슈팅버블이…",
                          "evidence_refs": ["evref.ctx.hit-session"]}],
        }
        objs = build_glossary_terms(notes, NOW)
        self.assertEqual(len(objs), 1)
        t = objs[0]
        self.assertEqual(t["id"], "g.ctx.hit")
        self.assertEqual(t["kind"], "GlossaryTerm")
        self.assertEqual(t["status"], "reviewed")
        self.assertEqual(t["truth_role"], "domain")
        self.assertEqual(t["context_id"], "context.ctx")
        self.assertEqual(t["term"], "hit (직접 타격)")
        self.assertEqual(t["evidence_refs"], ["evref.ctx.hit-session"])
        self.assertIn("created_at", t)  # base() 적용 확인
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py -v`
Expected: FAIL with "No module named 'project_brain.assembly'" / ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# src/project_brain/assembly.py
"""범용 조립 코어 — 구조화 노트 → brain 객체 묶음.

판정은 에이전트(노트 작성), 변환은 기계적(이 모듈). supersede/강등/충돌 해소/이력
판정은 하지 않는다. objbase.base 위에 kind별 변환 + refs + updates + 2층 검증을 얹는다.
저장은 절대 안 한다 — build()는 객체 묶음 + diff만 반환하고 ingest가 저장한다.
"""
from project_brain.objbase import base

# id 파생 규칙 (kind → prefix). 컨벤션: g.<ctx>.<key> / mapping.<ctx>.<key> 등.
_ID_PREFIX = {
    "GlossaryTerm": "g",
    "DomainMapping": "mapping",
    "CodeLocator": "code",
    "EvidenceRef": "evref",
    "DecisionRecord": "decision",
    "DomainContext": "context",
}


def derive_id(kind, ctx, key):
    """kind+컨텍스트+key로 객체 id를 만든다. 규칙은 _ID_PREFIX 고정."""
    return f"{_ID_PREFIX[kind]}.{ctx}.{key}"


def build_glossary_terms(notes, now):
    """노트의 glossary[] 항목을 reviewed GlossaryTerm 객체로 변환한다."""
    ctx = notes["context"]["key"]
    out = []
    for g in notes.get("glossary", []):
        obj = {
            "id": derive_id("GlossaryTerm", ctx, g["key"]),
            "kind": "GlossaryTerm",
            "status": "reviewed",
            "truth_role": "domain",
            "title": g["key"],
            "context_id": f"context.{ctx}",
            "term": g["term"],
            "definition": g["definition"],
            "evidence_refs": g.get("evidence_refs", []),
        }
        out.append(base(obj, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2"))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "feat(assembly): id 파생 + glossary 노트 변환 코어"
```

---

## Task 2: code_anchors → CodeLocator + EvidenceRef 쌍

노트의 `code_anchors[]` 한 항목이 CodeLocator 1개 + EvidenceRef 1개로 펼쳐진다. EvidenceRef는 `evidence_manifest_id`로 노트의 manifest를 가리킨다.

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/assembly.py`
- Test: `~/Downloads/codes/project-brain/tests/test_assembly.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assembly.py 에 추가
from project_brain.assembly import build_code_evidence


class BuildCodeEvidenceTest(unittest.TestCase):
    def test_anchor_expands_to_locator_and_evref(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc123", "now": NOW, "repo": "bb2_client"},
            "code_anchors": [{"key": "hit-hook", "path": "DisturbObject.h",
                              "symbol": "DisturbObject::_doDisturbOnPop", "line_start": 206,
                              "line_end": 206, "quote": "virtual void _doDisturbOnPop(...){};",
                              "manifest": "manifest.ctx.code-v2"}],
        }
        objs = build_code_evidence(notes, NOW)
        kinds = {o["kind"]: o for o in objs}
        self.assertEqual(set(kinds), {"CodeLocator", "EvidenceRef"})
        loc, ev = kinds["CodeLocator"], kinds["EvidenceRef"]
        self.assertEqual(loc["id"], "code.ctx.hit-hook")
        self.assertEqual(loc["path"], "DisturbObject.h")
        self.assertEqual(loc["commit_sha"], "abc123")
        self.assertEqual(loc["repo"], "bb2_client")
        self.assertEqual(ev["id"], "evref.ctx.hit-hook")
        self.assertEqual(ev["evidence_manifest_id"], "manifest.ctx.code-v2")
        self.assertEqual(ev["ref_type"], "code_locator")
        self.assertEqual(ev["locator"], "DisturbObject.h:206")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py::BuildCodeEvidenceTest -v`
Expected: FAIL with "cannot import name 'build_code_evidence'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/project_brain/assembly.py 에 추가
def build_code_evidence(notes, now):
    """code_anchors[] 각 항목을 CodeLocator + EvidenceRef 쌍으로 펼친다."""
    cx = notes["context"]
    ctx, commit, repo = cx["key"], cx["commit"], cx.get("repo", "bb2_client")
    out = []
    for a in notes.get("code_anchors", []):
        key = a["key"]
        quote = a.get("quote") or a["symbol"]
        loc = {
            "id": derive_id("CodeLocator", ctx, key),
            "kind": "CodeLocator", "status": "reviewed", "truth_role": "reference",
            "title": quote[:120], "repo": repo, "path": a["path"], "symbol": a["symbol"],
            "line_start": a["line_start"], "line_end": a["line_end"],
            "locator_source": a.get("locator_source", "rg"),
            "commit_sha": commit, "verified_at": now,
        }
        ev = {
            "id": derive_id("EvidenceRef", ctx, key),
            "kind": "EvidenceRef", "status": "reviewed", "truth_role": "reference",
            "title": quote[:120], "evidence_manifest_id": a["manifest"],
            "ref_type": "code_locator", "locator": f"{a['path']}:{a['line_start']}",
            "summary": quote[:500],
        }
        out.append(base(loc, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2"))
        out.append(base(ev, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2"))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "feat(assembly): code_anchors → CodeLocator+EvidenceRef 변환"
```

---

## Task 3: refs resolve — 기존 객체 참조 (id 직접 기입)

노트의 `refs` 섹션에서 로컬 키를 실제 객체 id로 해소한다. **1차는 id 직접 기입만 지원한다** — 노트가 `id`를 주면 그 id가 store에 실존하는지와 `expect`(kind·status)가 맞는지 검증한다. kind+context_id+key로 자동 검색하는 key resolve는 2차로 미룬다(자동 검색은 0개·2개+ 모호성 처리가 필요해 별도 설계). 결과물에는 실제 id만 들어가고 `resolved_refs` 리포트를 남긴다.

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/assembly.py`
- Test: `~/Downloads/codes/project-brain/tests/test_assembly.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assembly.py 에 추가
from project_brain.assembly import resolve_refs
from project_brain.store import BrainStore


def _store(*objs):
    return BrainStore({o["id"]: o for o in objs})


class ResolveRefsTest(unittest.TestCase):
    def test_id_direct_passthrough(self):
        store = _store({"id": "g.ctx.x", "kind": "GlossaryTerm"})
        notes = {"refs": {"terms": {"loc": {"id": "g.ctx.x",
                                            "expect": {"kind": "GlossaryTerm"}}}}}
        refs_map, report, errors = resolve_refs(notes, store)
        self.assertEqual(errors, [])
        self.assertEqual(refs_map["loc"], "g.ctx.x")
        self.assertIn("g.ctx.x", report.values())

    def test_missing_id_is_error(self):
        store = _store()
        notes = {"refs": {"terms": {"loc": {"id": "g.ctx.missing",
                                            "expect": {"kind": "GlossaryTerm"}}}}}
        _, _, errors = resolve_refs(notes, store)
        self.assertTrue(any("g.ctx.missing" in e for e in errors))

    def test_expect_kind_mismatch_is_error(self):
        store = _store({"id": "g.ctx.x", "kind": "GlossaryTerm", "status": "reviewed"})
        notes = {"refs": {"terms": {"loc": {"id": "g.ctx.x",
                                            "expect": {"kind": "DomainMapping"}}}}}
        _, _, errors = resolve_refs(notes, store)
        self.assertTrue(any("expect" in e.lower() or "kind" in e.lower() for e in errors))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py::ResolveRefsTest -v`
Expected: FAIL with "cannot import name 'resolve_refs'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/project_brain/assembly.py 에 추가
def resolve_refs(notes, store):
    """refs 섹션의 로컬 키를 실제 id로 해소. id 직접 기입 + expect 검증.

    반환: (refs_map {로컬키: 실제id}, report {로컬키: 실제id}, errors[]).
    id가 store에 없거나 expect(kind/status)가 어긋나면 errors에 담는다.
    """
    refs_map, report, errors = {}, {}, []
    refs = notes.get("refs", {})
    for _section, entries in refs.items():
        for local_key, spec in entries.items():
            obj_id = spec.get("id")
            if obj_id is None:
                errors.append(f"refs.{local_key}: id 미기입 (1차는 id 직접 기입만)")
                continue
            if not store.has(obj_id):
                errors.append(f"refs.{local_key}: {obj_id} store에 없음")
                continue
            obj = store.get(obj_id)
            expect = spec.get("expect", {})
            for field, want in expect.items():
                if obj.get(field) != want:
                    errors.append(
                        f"refs.{local_key}: {obj_id} expect {field}={want!r} "
                        f"but got {obj.get(field)!r}")
            refs_map[local_key] = obj_id
            report[local_key] = obj_id
    return refs_map, report, errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py::ResolveRefsTest -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "feat(assembly): refs resolve (id 직접 기입 + expect 검증)"
```

---

## Task 4: mappings + sources + context 변환

나머지 신규 객체 섹션을 변환한다. mappings는 `glossary_keys`(이번 노트의 신규 용어)와 `glossary_term_refs`(refs로 해소한 기존 용어)를 합쳐 `glossary_term_ids`로, `code_evref_keys`를 `code_locator_ids`/`evidence_refs`로 연결한다.

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/assembly.py`
- Test: `~/Downloads/codes/project-brain/tests/test_assembly.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assembly.py 에 추가
from project_brain.assembly import build_mappings


class BuildMappingsTest(unittest.TestCase):
    def test_mapping_links_new_and_ref_terms(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc", "now": NOW, "repo": "bb2_client"},
            "mappings": [{"key": "hit-trigger", "canonical_summary": "요약",
                          "meaning": "의미", "boundary": "경계",
                          "glossary_keys": ["hit"], "glossary_term_refs": ["near_pop_hook"],
                          "code_evref_keys": ["hit-hook"]}],
        }
        refs_map = {"near_pop_hook": "g.ctx.do-disturb-on-near-bubble-pop"}
        objs = build_mappings(notes, refs_map, NOW)
        m = objs[0]
        self.assertEqual(m["id"], "mapping.ctx.hit-trigger")
        self.assertEqual(m["kind"], "DomainMapping")
        self.assertEqual(m["status"], "reviewed")
        self.assertEqual(sorted(m["glossary_term_ids"]),
                         ["g.ctx.do-disturb-on-near-bubble-pop", "g.ctx.hit"])
        self.assertEqual(m["code_locator_ids"], ["code.ctx.hit-hook"])
        self.assertEqual(m["evidence_refs"], ["evref.ctx.hit-hook"])
        self.assertEqual(m["caveats"], ["history_coverage=unsearched"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py::BuildMappingsTest -v`
Expected: FAIL with "cannot import name 'build_mappings'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/project_brain/assembly.py 에 추가
def build_mappings(notes, refs_map, now):
    """mappings[]를 DomainMapping으로. 신규 용어(glossary_keys) + 기존 용어(glossary_term_refs)
    를 합쳐 glossary_term_ids로, code_evref_keys를 locator/evref로 연결한다."""
    ctx = notes["context"]["key"]
    out = []
    for m in notes.get("mappings", []):
        gids = [derive_id("GlossaryTerm", ctx, k) for k in m.get("glossary_keys", [])]
        gids += [refs_map[r] for r in m.get("glossary_term_refs", [])]
        code_ids = [derive_id("CodeLocator", ctx, k) for k in m.get("code_evref_keys", [])]
        evref_ids = [derive_id("EvidenceRef", ctx, k) for k in m.get("code_evref_keys", [])]
        obj = {
            "id": derive_id("DomainMapping", ctx, m["key"]),
            "kind": "DomainMapping", "status": "reviewed", "truth_role": "domain",
            "title": m["canonical_summary"][:120], "context_id": f"context.{ctx}",
            "mapping_key": m["key"], "canonical_summary": m["canonical_summary"],
            "meaning": m["meaning"], "boundary": m["boundary"],
            "caveats": m.get("caveats", ["history_coverage=unsearched"]),
            "glossary_term_ids": sorted(set(gids)),
            "decision_record_ids": [derive_id("DecisionRecord", ctx, k)
                                    for k in m.get("decision_keys", [])],
            "code_locator_ids": code_ids, "evidence_refs": evref_ids,
        }
        out.append(base(obj, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2"))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py -v`
Expected: PASS (전체)

- [ ] **Step 5: Commit**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "feat(assembly): mappings 변환 (신규+기존 용어 연결)"
```

- [ ] **Step 6a: build_manifests + build_context 실패 테스트**

```python
# tests/test_assembly.py 에 추가
from project_brain.assembly import build_manifests, build_context


class BuildManifestsContextTest(unittest.TestCase):
    def test_source_becomes_manifest(self):
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "bb2_client"},
                 "sources": [{"id": "manifest.ctx.s", "source_type": "session",
                              "title": "T", "locator": "...", "captured_by": "user-statement"}]}
        objs = build_manifests(notes, NOW)
        self.assertEqual(len(objs), 1)
        m = objs[0]
        self.assertEqual(m["id"], "manifest.ctx.s")
        self.assertEqual(m["kind"], "EvidenceManifest")
        self.assertEqual(m["truth_role"], "source")
        self.assertEqual(m["redaction_status"], "none")  # default
        self.assertEqual(m["acl"], ["bb2-team"])          # default

    def test_context_built_only_with_display_fields(self):
        base_cx = {"key": "ctx", "commit": "a", "now": NOW, "repo": "bb2_client"}
        self.assertEqual(build_context({"context": base_cx}, NOW), [])  # display_name 없으면 빈 리스트
        rich = dict(base_cx, display_name="방해버블", boundary_summary="...")
        objs = build_context({"context": rich}, NOW)
        self.assertEqual(objs[0]["id"], "context.ctx")
        self.assertEqual(objs[0]["kind"], "DomainContext")
        self.assertEqual(objs[0]["truth_role"], "domain")
```

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py::BuildManifestsContextTest -v`
Expected: FAIL with "cannot import name 'build_manifests'"

- [ ] **Step 6b: build_manifests + build_context 구현**

`build_glossary_terms`와 동일한 base() 패턴. 필드는 실제 적재된 객체에서 확인됨(EvidenceManifest·DomainContext).

```python
# src/project_brain/assembly.py 에 추가
def build_manifests(notes, now):
    """sources[] → EvidenceManifest. id는 노트에 직접 기입(컨벤션 manifest.<ctx>.<...>)."""
    ctx = notes["context"]["key"]
    out = []
    for s in notes.get("sources", []):
        obj = {
            "id": s["id"], "kind": "EvidenceManifest", "status": "reviewed",
            "truth_role": "source", "title": s["title"], "source_type": s["source_type"],
            "locator": s["locator"], "captured_at": s.get("captured_at", now),
            "captured_by": s.get("captured_by", "agent"),
            "sensitivity": s.get("sensitivity", "internal"),
            "acl": s.get("acl", ["bb2-team"]),
            "redaction_status": s.get("redaction_status", "none"),
        }
        out.append(base(obj, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2"))
    return out


def build_context(notes, now):
    """노트 context에 display_name·boundary_summary가 있으면 신규 DomainContext 생성.
    없으면(key·commit만) 빈 리스트 — 기존 컨텍스트 갱신은 updates[]가 담당."""
    cx = notes["context"]
    if "display_name" not in cx or "boundary_summary" not in cx:
        return []
    ctx = cx["key"]
    obj = {
        "id": f"context.{ctx}", "kind": "DomainContext", "status": "reviewed",
        "truth_role": "domain", "title": cx["display_name"][:80], "context_key": ctx,
        "project_id": cx.get("repo", "bb2_client"), "display_name": cx["display_name"],
        "boundary_summary": cx["boundary_summary"], "in_scope": cx.get("in_scope", []),
        "out_of_scope": cx.get("out_of_scope", []),
        "injection_profile": {"default_audience": "coding-agent"},
        "glossary_term_ids": cx.get("glossary_term_ids", []),
    }
    return [base(obj, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2")]
```

- [ ] **Step 7: Run tests + commit (Task 4 전체)**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py -v` → PASS

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "feat(assembly): mappings + sources(manifest) + context 변환"
```

> **decisions는 1차 제외:** `DecisionRecord`의 필수 필드는 이미 `schema.KIND_REQUIRED["DecisionRecord"]`(decision_type·summary·decision·source_object_ids·affected_context_ids·spec_reflected)에 있다. 1차에서 빼는 이유는 필수 필드를 몰라서가 아니라, **노트의 decisions 섹션을 어떤 양식으로 받아 어떻게 객체로 매핑할지(조립 의미·섹션 노트 스키마)를 아직 합의하지 않았기** 때문이다. 그래서 1차 build는 decisions 섹션을 지원하지 않고, DecisionRecord가 필요한 적재는 `extra_objects[]`(완성 객체 직접) 탈출구를 쓴다. 2차에서 decisions 노트 스키마를 합의해 `build_decisions`를 추가한다.

---

## Task 5: updates 적용 — set/union + 가드 다중

가장 위험한 부분. 기존 객체를 갱신한다. set은 scalar 필드 교체, union은 list 필드 합치기. **allowlist는 객체 kind별로 분리** — `cur["kind"]`에 맞는 필드만 set/union 가능(예: DomainContext의 `meaning` set 같은 엉뚱한 조합 차단). 의미 필드(claim) 수정 시 근거 동반 강제. `expected_updated_at` 낙관적 잠금. reviewed→candidate 강등 금지. **연산은 set·union 2종뿐 — remove·조건·계산·status 변경 없음.** diff는 필드별 before/after 값을 담아 사람이 검수할 수 있게 한다(union 대상 id 실존 검사는 이번 묶음도 봐야 해 build()가 담당).

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/assembly.py`
- Test: `~/Downloads/codes/project-brain/tests/test_assembly.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assembly.py 에 추가
from project_brain.assembly import apply_updates

T0 = "2026-06-01T00:00:00Z"


def _mapping(**over):
    o = {"id": "mapping.ctx.hook", "kind": "DomainMapping", "status": "reviewed",
         "truth_role": "domain", "title": "t", "context_id": "context.ctx",
         "mapping_key": "hook", "canonical_summary": "s", "meaning": "옛 의미",
         "boundary": "b", "caveats": [], "glossary_term_ids": ["g.ctx.a"],
         "decision_record_ids": [], "code_locator_ids": [], "evidence_refs": ["evref.ctx.x"],
         "schema_version": "0.1", "poc_priority": "P2", "created_at": T0, "updated_at": T0,
         "tags": ["ctx"]}
    o.update(over)
    return o


class ApplyUpdatesTest(unittest.TestCase):
    def test_set_scalar_and_union_list(self):
        # title(비-claim scalar) set + glossary_term_ids union — 둘 다 근거 동반 불필요.
        # claim 필드(meaning·boundary 등)는 별도 테스트(test_claim_*)에서 근거 강제 검증.
        store = _store(_mapping())
        notes = {"updates": [{"id": "mapping.ctx.hook", "expected_updated_at": T0,
                              "union": {"glossary_term_ids": ["g.ctx.b"]},
                              "set": {"title": "새 제목"}}]}
        objs, diffs, errors = apply_updates(notes, store, NOW)
        self.assertEqual(errors, [])
        m = objs[0]
        self.assertEqual(sorted(m["glossary_term_ids"]), ["g.ctx.a", "g.ctx.b"])
        self.assertEqual(m["title"], "새 제목")
        self.assertEqual(m["updated_at"], NOW)
        self.assertEqual(m["status"], "reviewed")  # 강등 없음

    def test_claim_field_requires_evidence(self):
        # meaning(claim) 수정인데 evidence 변경도 evidence_unchanged도 없으면 실패
        store = _store(_mapping())
        notes = {"updates": [{"id": "mapping.ctx.hook", "expected_updated_at": T0,
                              "set": {"meaning": "새 의미"}}]}
        _, _, errors = apply_updates(notes, store, NOW)
        self.assertTrue(any("evidence" in e.lower() for e in errors))

    def test_claim_with_evidence_unchanged_ok(self):
        store = _store(_mapping())
        notes = {"updates": [{"id": "mapping.ctx.hook", "expected_updated_at": T0,
                              "set": {"meaning": "새 의미"}, "evidence_unchanged": True}]}
        _, _, errors = apply_updates(notes, store, NOW)
        self.assertEqual(errors, [])

    def test_expected_updated_at_mismatch_fails(self):
        store = _store(_mapping())
        notes = {"updates": [{"id": "mapping.ctx.hook", "expected_updated_at": "2099-01-01T00:00:00Z",
                              "set": {"boundary": "x"}}]}
        _, _, errors = apply_updates(notes, store, NOW)
        self.assertTrue(any("expected_updated_at" in e for e in errors))

    def test_field_not_in_allowlist_fails(self):
        store = _store(_mapping())
        notes = {"updates": [{"id": "mapping.ctx.hook", "expected_updated_at": T0,
                              "set": {"status": "candidate"}}]}
        _, _, errors = apply_updates(notes, store, NOW)
        self.assertTrue(any("allowlist" in e.lower() or "status" in e for e in errors))

    def test_per_kind_allowlist_rejects_foreign_field(self):
        # GlossaryTerm에 DomainMapping 전용 scalar(meaning)를 set → GlossaryTerm allowlist 밖
        term = {"id": "g.ctx.t", "kind": "GlossaryTerm", "status": "reviewed",
                "truth_role": "domain", "title": "t", "context_id": "context.ctx",
                "term": "용어", "definition": "정의", "evidence_refs": ["evref.ctx.x"],
                "schema_version": "0.1", "poc_priority": "P2",
                "created_at": T0, "updated_at": T0, "tags": ["ctx"]}
        store = _store(term)
        notes = {"updates": [{"id": "g.ctx.t", "expected_updated_at": T0,
                              "set": {"meaning": "엉뚱"}}]}
        _, _, errors = apply_updates(notes, store, NOW)
        self.assertTrue(any("allowlist" in e.lower() for e in errors))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py::ApplyUpdatesTest -v`
Expected: FAIL with "cannot import name 'apply_updates'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/project_brain/assembly.py 에 추가
import copy

# kind별 allowlist — set(scalar 교체)/union(list 합치기)으로 고칠 수 있는 필드만.
# status·id·kind·created_at·context_id 등 정체성·생명주기 필드는 어느 kind에서도 불가.
_SET_ALLOWLIST = {
    "DomainMapping": {"meaning", "boundary", "canonical_summary", "title"},
    "GlossaryTerm": {"term", "definition", "title"},
    "DomainContext": {"display_name", "boundary_summary", "title"},
}
_UNION_ALLOWLIST = {
    "DomainMapping": {"glossary_term_ids", "code_locator_ids", "decision_record_ids",
                      "evidence_refs", "caveats"},
    "GlossaryTerm": {"evidence_refs"},
    "DomainContext": {"glossary_term_ids", "in_scope", "out_of_scope"},
}
# 의미 주장 필드(kind 무관) — 고치면 근거 동반 강제.
_CLAIM_FIELDS = {"meaning", "boundary", "canonical_summary", "definition",
                 "boundary_summary"}


def apply_updates(notes, store, now):
    """updates[]를 기존 객체에 적용한 '갱신 반영 객체'를 만든다. store는 안 바꾼다.

    가드: expected_updated_at 일치 / set·union은 cur["kind"]별 allowlist 안에서만 /
    claim 필드 수정 시 evidence_refs 변경 또는 evidence_unchanged:true 필수 / status·id
    등 정체성 필드는 allowlist 밖이라 자동 거부. union 대상 id의 실존 검사는 store뿐 아니라
    이번 묶음(new_objs)도 봐야 하므로 build()가 담당한다(여기선 안 함).
    반환: (updated_objs[], diffs[], errors[]). diff는 필드별 before/after 값을 담는다.
    """
    out, diffs, errors = [], [], []
    for up in notes.get("updates", []):
        oid = up["id"]
        if not store.has(oid):
            errors.append(f"updates {oid}: store에 없음")
            continue
        cur = store.get(oid)
        if cur.get("updated_at") != up.get("expected_updated_at"):
            errors.append(f"updates {oid}: expected_updated_at 불일치 "
                          f"(노트 {up.get('expected_updated_at')!r} != 현재 {cur.get('updated_at')!r})")
            continue
        kind = cur.get("kind")
        set_allow = _SET_ALLOWLIST.get(kind, set())
        union_allow = _UNION_ALLOWLIST.get(kind, set())
        new = copy.deepcopy(cur)
        set_fields = up.get("set", {})
        union_fields = up.get("union", {})
        # kind별 allowlist 검사
        for f in set_fields:
            if f not in set_allow:
                errors.append(f"updates {oid}: set 필드 {f!r}는 {kind} allowlist 밖")
        for f in union_fields:
            if f not in union_allow:
                errors.append(f"updates {oid}: union 필드 {f!r}는 {kind} allowlist 밖")
        # claim 필드 수정 시 근거 동반 강제
        touched_claims = (set(set_fields) | set(union_fields)) & _CLAIM_FIELDS
        evidence_touched = ("evidence_refs" in set_fields or "evidence_refs" in union_fields
                            or up.get("evidence_unchanged") is True)
        if touched_claims and not evidence_touched:
            errors.append(f"updates {oid}: claim 필드 {sorted(touched_claims)} 수정엔 "
                          f"evidence_refs 변경 또는 evidence_unchanged:true 필요")
        # 실제 적용 + 필드별 before/after diff (errors 있어도 diff 위해 적용은 함; build()가 errors로 막음)
        changes = {}
        for f, v in set_fields.items():
            changes[f] = {"before": cur.get(f), "after": v}
            new[f] = v
        for f, vs in union_fields.items():
            merged_list = sorted(set(new.get(f, []) + vs))
            changes[f] = {"before": cur.get(f, []), "after": merged_list}
            new[f] = merged_list
        new["updated_at"] = now
        out.append(new)
        diffs.append({"id": oid, "changes": changes,
                      "before_updated_at": cur.get("updated_at")})
    return out, diffs, errors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py::ApplyUpdatesTest -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "feat(assembly): updates 적용 + 가드(allowlist·claim근거·낙관적잠금)"
```

---

## Task 6: 노트 1층 검증 + build() 통합 (2층 의미검증 + diff + preconditions)

`build()`가 전체를 묶는다: 1층 노트 형식 검증 → refs resolve → 신규 객체 변환 → updates 적용 → 2층 의미 검증(validate_object·dangling·lint_store) → 묶음 + diff + preconditions 반환. **저장 안 함.**

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/assembly.py`
- Test: `~/Downloads/codes/project-brain/tests/test_assembly.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_assembly.py 에 추가
from project_brain.assembly import validate_notes, build


def _ref_objs(ctx="ctx"):
    """_mapping()이 가리키는 참조 대상을 닫는 최소 객체들 — build의 lint를 통과시키려면
    evidence_refs(evref)·context_id(context)가 store에 실존해야 한다."""
    manifest = {"id": f"manifest.{ctx}.src", "kind": "EvidenceManifest", "status": "reviewed",
                "truth_role": "source", "title": "src", "source_type": "session",
                "locator": "...", "captured_at": T0, "captured_by": "user-statement",
                "sensitivity": "internal", "acl": ["bb2-team"], "redaction_status": "approved",
                "schema_version": "0.1", "poc_priority": "P2",
                "created_at": T0, "updated_at": T0, "tags": [ctx], "evidence_refs": []}
    evref = {"id": f"evref.{ctx}.x", "kind": "EvidenceRef", "status": "reviewed",
             "truth_role": "reference", "title": "e", "evidence_manifest_id": f"manifest.{ctx}.src",
             "ref_type": "session_turn", "locator": "...", "summary": "s",
             "schema_version": "0.1", "poc_priority": "P2",
             "created_at": T0, "updated_at": T0, "tags": [ctx], "evidence_refs": []}
    context = {"id": f"context.{ctx}", "kind": "DomainContext", "status": "reviewed",
               "truth_role": "domain", "title": "C", "context_key": ctx,
               "project_id": "bb2_client", "display_name": "C", "boundary_summary": "b",
               "in_scope": [], "out_of_scope": [],
               "injection_profile": {"default_audience": "coding-agent"},
               "glossary_term_ids": [], "schema_version": "0.1", "poc_priority": "P2",
               "created_at": T0, "updated_at": T0, "tags": [ctx], "evidence_refs": []}
    return [manifest, evref, context]


class ValidateNotesTest(unittest.TestCase):
    def test_unknown_section_fails(self):
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "bogus_section": []})
        self.assertTrue(any("bogus_section" in e for e in errors))

    def test_missing_context_fails(self):
        errors = validate_notes({"glossary": []})
        self.assertTrue(any("context" in e for e in errors))

    def test_remove_operation_rejected(self):
        # set/union 외 연산 키(remove 등)는 미지원 — 거부
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "updates": [{"id": "x", "expected_updated_at": NOW,
                                              "remove": {"caveats": ["old"]}}]})
        self.assertTrue(any("remove" in e for e in errors))

    def test_section_wrong_type_rejected(self):
        # glossary는 list여야 — dict면 실패
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "glossary": {"not": "a list"}})
        self.assertTrue(any("glossary" in e for e in errors))

    def test_item_missing_required_field_rejected(self):
        # glossary 항목에 definition 누락 → 1층에서 잡음
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "glossary": [{"key": "hit", "term": "hit"}]})
        self.assertTrue(any("definition" in e for e in errors))

    def test_glossary_empty_evidence_rejected(self):
        # reviewed로 만들어질 glossary가 빈 evidence_refs면 1층에서 잡힌다(2층 schema 전에)
        errors = validate_notes({"context": {"key": "c", "commit": "x", "now": NOW},
                                 "glossary": [{"key": "h", "term": "h", "definition": "d",
                                               "evidence_refs": []}]})
        self.assertTrue(any("evidence_refs" in e for e in errors))


class BuildIntegrationTest(unittest.TestCase):
    def test_build_new_objects_bundle(self):
        notes = {
            "context": {"key": "ctx", "commit": "abc", "now": NOW, "repo": "bb2_client"},
            "sources": [{"id": "manifest.ctx.code-v2", "source_type": "code_search",
                         "title": "코드", "locator": "...", "captured_by": "agent"}],
            "code_anchors": [{"key": "hit-hook", "path": "D.h", "symbol": "S",
                              "line_start": 1, "line_end": 1, "quote": "q",
                              "manifest": "manifest.ctx.code-v2"}],
            "glossary": [{"key": "hit", "term": "hit", "definition": "정의",
                          "evidence_refs": ["evref.ctx.hit-hook"]}],
        }
        result = build(notes, _store(), NOW)
        self.assertEqual(result["errors"], [])
        ids = {o["id"] for o in result["objects"]}
        self.assertIn("g.ctx.hit", ids)
        self.assertIn("code.ctx.hit-hook", ids)
        self.assertIn("evref.ctx.hit-hook", ids)

    def test_build_dangling_ref_caught(self):
        # glossary가 없는 evref를 가리키면 2층(dangling)이 잡는다
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "bb2_client"},
                 "glossary": [{"key": "x", "term": "x", "definition": "d",
                               "evidence_refs": ["evref.ctx.nonexistent"]}]}
        result = build(notes, _store(), NOW)
        self.assertTrue(result["errors"])

    def test_build_evref_dangling_manifest_caught(self):
        # extra_objects로 들어온 EvidenceRef가 없는 manifest를 가리키면 build 2층이 잡는다
        # (lint는 EvidenceRef→manifest를 안 보므로 build가 직접 검사)
        evref = {"id": "evref.ctx.x", "kind": "EvidenceRef", "status": "reviewed",
                 "truth_role": "reference", "title": "e",
                 "evidence_manifest_id": "manifest.ctx.missing", "ref_type": "session_turn",
                 "locator": "...", "summary": "s", "schema_version": "0.1", "poc_priority": "P2",
                 "created_at": T0, "updated_at": T0, "tags": ["ctx"], "evidence_refs": []}
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "bb2_client"},
                 "extra_objects": [evref]}
        result = build(notes, _store(), NOW)
        self.assertTrue(any("evidence_manifest_id" in e for e in result["errors"]))

    def test_build_union_target_missing_caught(self):
        # DomainContext.glossary_term_ids union 대상이 store·묶음 어디에도 없으면 build가 잡는다
        # (lint는 DomainMapping 링크만 봐서 DomainContext union은 사각지대)
        store = _store(*_ref_objs())  # context.ctx 포함
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "bb2_client"},
                 "updates": [{"id": "context.ctx", "expected_updated_at": T0,
                              "union": {"glossary_term_ids": ["g.ctx.nonexistent"]}}]}
        result = build(notes, store, NOW)
        self.assertTrue(any("g.ctx.nonexistent" in e for e in result["errors"]))

    def test_build_emits_preconditions_for_updates(self):
        # title(비-claim) set + 참조 닫힌 픽스처 → errors 없이 preconditions 방출
        store = _store(_mapping(glossary_term_ids=[]), *_ref_objs())
        notes = {"context": {"key": "ctx", "commit": "a", "now": NOW, "repo": "bb2_client"},
                 "updates": [{"id": "mapping.ctx.hook", "expected_updated_at": T0,
                              "set": {"title": "새 제목"}}]}
        result = build(notes, store, NOW)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["preconditions"], {"mapping.ctx.hook": T0})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py::BuildIntegrationTest -v`
Expected: FAIL with "cannot import name 'build'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/project_brain/assembly.py 에 추가
from project_brain.schema import validate_object
from project_brain.lint import lint_store
from project_brain.store import BrainStore

_VALID_SECTIONS = {"context", "sources", "glossary", "code_anchors", "mappings",
                   "refs", "updates", "extra_objects"}  # decisions는 2차(Task 4 노트 참고)
_LIST_SECTIONS = {"sources", "glossary", "code_anchors", "mappings", "updates", "extra_objects"}
_DICT_SECTIONS = {"context", "refs"}
_UPDATE_KEYS = {"id", "expected_updated_at", "set", "union", "evidence_unchanged"}
# 섹션 항목별 필수 필드(중첩 검증). 변환 함수가 default 채우는 필드는 여기 안 넣는다.
_ITEM_REQUIRED = {
    # glossary는 항상 reviewed로 만들어지므로 evidence_refs 필수(2층 schema가 막는 걸 1층에서 친절히).
    "glossary": ("key", "term", "definition", "evidence_refs"),
    "code_anchors": ("key", "path", "symbol", "line_start", "line_end", "manifest"),
    "mappings": ("key", "canonical_summary", "meaning", "boundary"),
    "sources": ("id", "source_type", "title", "locator"),
}


def validate_notes(notes):
    """1층: 노트 형식 검증. 모르는 섹션·필수 누락·잘못된 타입·미지원 연산은 경고가 아니라 실패."""
    errors = []
    for section, value in notes.items():
        if section not in _VALID_SECTIONS:
            errors.append(f"노트: 알 수 없는 섹션 {section!r} (허용: {sorted(_VALID_SECTIONS)})")
            continue
        if section in _LIST_SECTIONS and not isinstance(value, list):
            errors.append(f"노트: 섹션 {section!r}는 list여야 함 (현재 {type(value).__name__})")
        if section in _DICT_SECTIONS and not isinstance(value, dict):
            errors.append(f"노트: 섹션 {section!r}는 object여야 함 (현재 {type(value).__name__})")
    cx = notes.get("context")
    if not isinstance(cx, dict) or "key" not in cx or "commit" not in cx:
        errors.append("노트: context.key·context.commit 필수")
    # 섹션 항목 중첩 필수 필드
    for section, required in _ITEM_REQUIRED.items():
        value = notes.get(section)
        if not isinstance(value, list):
            continue
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                errors.append(f"노트: {section}[{i}]는 object여야 함")
                continue
            for field in required:
                if field not in item:
                    errors.append(f"노트: {section}[{i}] 필수 필드 {field!r} 누락")
    # glossary는 reviewed로 생성되므로 evidence_refs가 비어 있어도 안 됨(2층 schema:186을 1층에서 친절히).
    # _ITEM_REQUIRED는 키 존재만 보므로 빈 리스트는 여기서 별도로 잡는다.
    glossary = notes.get("glossary")
    for i, g in enumerate(glossary if isinstance(glossary, list) else []):
        if isinstance(g, dict) and "evidence_refs" in g and not g["evidence_refs"]:
            errors.append(f"노트: glossary[{i}] evidence_refs가 비어 있음 (reviewed 용어는 근거 필수)")
    # updates: 연산 키 화이트리스트(remove·조건·계산 차단) + 타입
    updates = notes.get("updates")
    for up in updates if isinstance(updates, list) else []:
        if not isinstance(up, dict):
            errors.append("노트: updates 항목은 object여야 함")
            continue
        for key in up:
            if key not in _UPDATE_KEYS:
                errors.append(f"updates {up.get('id')}: 미지원 연산 키 {key!r} "
                              f"(허용: {sorted(_UPDATE_KEYS)} — remove·조건·계산 없음)")
        if "expected_updated_at" not in up:
            errors.append(f"updates {up.get('id')}: expected_updated_at 필수")
        if not (up.get("set") or up.get("union")):
            errors.append(f"updates {up.get('id')}: set 또는 union 중 하나 필요")
        for op in ("set", "union"):
            if op in up and not isinstance(up[op], dict):
                errors.append(f"updates {up.get('id')}: {op}은 object여야 함")
    return errors


def build(notes, store, now):
    """노트 → 완성 객체 묶음 + diff + preconditions. 저장은 안 한다.

    반환 dict: objects[], diff[], resolved_refs{}, preconditions{id: expected_updated_at},
               errors[]. errors가 비어야 안전하게 ingest 가능.
    """
    errors = list(validate_notes(notes))
    if errors:
        return {"objects": [], "diff": [], "resolved_refs": {},
                "preconditions": {}, "errors": errors}

    refs_map, resolved, ref_errors = resolve_refs(notes, store)
    errors += ref_errors

    new_objs = []
    new_objs += build_manifests(notes, now)        # Task 4 Step 6
    new_objs += build_code_evidence(notes, now)    # Task 2
    new_objs += build_glossary_terms(notes, now)   # Task 1
    new_objs += build_mappings(notes, refs_map, now)  # Task 4
    new_objs += build_context(notes, now)          # Task 4 Step 6 (신규 context)
    new_objs += list(notes.get("extra_objects", []))  # 탈출구: 완성 객체 직접

    upd_objs, diffs, upd_errors = apply_updates(notes, store, now)
    errors += upd_errors
    preconditions = {up["id"]: up["expected_updated_at"] for up in notes.get("updates", [])}

    all_objs = new_objs + upd_objs

    # 2층: 객체 스키마 + dangling + merged lint
    for o in all_objs:
        errors += validate_object(o)
    merged = {o["id"]: o for o in store.all()}
    for o in all_objs:
        merged[o["id"]] = o

    # EvidenceRef → EvidenceManifest dangling (lint.py 사각지대 — lint는 EvidenceRef가
    # 가리키는 manifest 실존을 안 본다. _source_type_for_evidence_ref는 None만 반환).
    for o in all_objs:
        if o.get("kind") == "EvidenceRef":
            mid = o.get("evidence_manifest_id")
            if mid and mid not in merged:
                errors.append(f"{o['id']}: dangling evidence_manifest_id {mid}")

    # updates union 대상 id 실존 (lint.py 사각지대 — lint는 DomainMapping 링크만 보므로
    # DomainContext.glossary_term_ids 등은 직접 검사. id 리스트 필드만, 자유텍스트 list 제외).
    for up in notes.get("updates", []):
        for f, vs in (up.get("union") or {}).items():
            if f.endswith("_ids") or f == "evidence_refs":
                for v in vs:
                    if v not in merged:
                        errors.append(f"updates {up.get('id')}: union {f} 대상 {v} 없음 "
                                      f"(store·이번 묶음 어디에도)")

    errors += lint_store(BrainStore(merged))

    return {"objects": all_objs, "diff": diffs, "resolved_refs": resolved,
            "preconditions": preconditions, "errors": errors}
```

> **참고:** `build_manifests`/`build_context`는 Task 4 Step 6의 변환 함수. sources/context 섹션이 비면 빈 리스트를 반환한다.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_assembly.py -v`
Expected: PASS (전체)

- [ ] **Step 5: Commit**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/assembly.py tests/test_assembly.py
git commit -m "feat(assembly): build() 통합 — 1층/2층 검증 + diff + preconditions"
```

---

## Task 7: build CLI 서브커맨드

`project-brain build --notes notes.json --objects-file out.json`. 노트를 읽어 `build()`를 돌리고, errors 있으면 출력+종료코드 1, 없으면 객체 묶음을 `--objects-file`로 쓰고 diff/resolved_refs/preconditions를 stdout에 리포트로 출력. **저장(ingest)은 하지 않는다.**

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/cli.py`
- Test: `~/Downloads/codes/project-brain/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py 에 추가 (기존 import/패턴 따름)
import json, tempfile
from pathlib import Path
from project_brain.cli import _run_build


class RunBuildTest(unittest.TestCase):
    def test_build_writes_objects_file(self):
        with tempfile.TemporaryDirectory() as td:
            notes_path = Path(td) / "notes.json"
            out_path = Path(td) / "out.json"
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            # reviewed GlossaryTerm은 evidence_refs가 필수(schema) → source+code_anchor로 닫는다
            notes_path.write_text(json.dumps({
                "context": {"key": "ctx", "commit": "abc",
                            "now": "2026-06-16T00:00:00Z", "repo": "bb2_client"},
                "sources": [{"id": "manifest.ctx.code", "source_type": "code_search",
                             "title": "코드", "locator": "...", "captured_by": "agent"}],
                "code_anchors": [{"key": "hit-hook", "path": "D.h", "symbol": "S",
                                  "line_start": 1, "line_end": 1, "quote": "q",
                                  "manifest": "manifest.ctx.code"}],
                "glossary": [{"key": "hit", "term": "hit", "definition": "정의",
                              "evidence_refs": ["evref.ctx.hit-hook"]}],
            }), encoding="utf-8")
            rc = _run_build(["--notes", str(notes_path), "--objects-file", str(out_path),
                             "--brain-root", str(brain)])
            self.assertEqual(rc, 0)
            objs = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(any(o["id"] == "g.ctx.hit" for o in objs))

    def test_build_errors_return_1_and_no_file(self):
        with tempfile.TemporaryDirectory() as td:
            notes_path = Path(td) / "notes.json"
            out_path = Path(td) / "out.json"
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            notes_path.write_text(json.dumps({"glossary": []}), encoding="utf-8")  # context 없음
            rc = _run_build(["--notes", str(notes_path), "--objects-file", str(out_path),
                             "--brain-root", str(brain)])
            self.assertEqual(rc, 1)
            self.assertFalse(out_path.exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_cli.py::RunBuildTest -v`
Expected: FAIL with "cannot import name '_run_build'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/project_brain/cli.py 에 추가 (_run_ingest 근처)
def _run_build(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli build")
    parser.add_argument("--notes", required=True, help="구조화 노트 JSON 경로")
    parser.add_argument("--objects-file", required=True, help="조립 결과 객체 묶음 출력 경로")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    args = parser.parse_args(argv)

    from project_brain.assembly import build
    from project_brain.store import BrainStore

    brain_root = resolve_brain_root(args.brain_root)
    notes = json.loads(Path(args.notes).read_text(encoding="utf-8"))
    # now는 context.now에서만 받는다(top-level now는 validate_notes의 _VALID_SECTIONS 밖이라 거부됨).
    now = notes.get("context", {}).get("now")
    if not now:
        print(json.dumps({"ok": False,
                          "errors": ["노트: context.now 필수 (build 객체의 created_at/updated_at)"]},
                         ensure_ascii=False, indent=2))
        return 1
    store = BrainStore.load(brain_root)
    result = build(notes, store, now)
    if result["errors"]:
        print(json.dumps({"ok": False, "errors": result["errors"]},
                         ensure_ascii=False, indent=2))
        return 1
    Path(args.objects_file).write_text(
        json.dumps(result["objects"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "built": len(result["objects"]),
                      "objects_file": args.objects_file, "diff": result["diff"],
                      "resolved_refs": result["resolved_refs"],
                      "preconditions": result["preconditions"]},
                     ensure_ascii=False, indent=2))
    return 0
```

```python
# src/project_brain/cli.py main() dispatch에 추가 (ingest 분기 옆, line 556 근처)
        if argv and argv[0] == "build":
            return _run_build(argv[1:])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_cli.py::RunBuildTest -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/cli.py tests/test_cli.py
git commit -m "feat(cli): build 서브커맨드 (노트 → 객체묶음 + 리포트, 저장 안 함)"
```

---

## Task 8: ingest preconditions 재검사 + 스킬 문서 갱신

TOCTOU 가드: build와 사람 확인 후 ingest 사이에 store가 바뀌면 낡은 묶음이 최신 객체를 덮을 수 있다. `ingest`가 `--preconditions-file`(build 리포트의 preconditions)을 받으면 **저장 직전** expected_updated_at을 다시 확인한다. 그리고 BB2 스킬 문서에 새 절차를 적는다.

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/ingest.py`
- Modify: `~/Downloads/codes/project-brain/src/project_brain/cli.py` (`_run_ingest`)
- Modify: `~/Downloads/codes/project-brain/tests/test_ingest.py`
- Modify: `~/Desktop/bb2_client/.agents/skills/bb2-brain-ingest/references/ingest-tools.md`
- Modify: `~/Desktop/bb2_client/.agents/skills/bb2-brain-ingest/references/system-domain-playbook.md`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ingest.py 에 추가.
# (이 파일엔 이미 `from project_brain.ingest import IngestError, ingest`, tempfile/Path/unittest
#  import, 그리고 manifest()/context()/evidence_ref() 헬퍼가 있다 — test_cli.py가 import해 쓴다.
#  그 헬퍼를 재사용해도 되지만, 아래는 precondition 시나리오에 맞춰 자기완결로 인라인한다.
#  ingest/IngestError import는 이미 있으므로 다시 적지 않는다.)

T0 = "2026-06-10T00:00:00Z"


def _refs():
    """mapping.ctx.x가 가리키는 context·evref·manifest를 닫는다(reviewed mapping은
    evidence_refs 필수[schema], context_id·evidence_ref는 dangling 금지[lint])."""
    manifest = {"id": "manifest.ctx.src", "kind": "EvidenceManifest", "status": "reviewed",
                "truth_role": "source", "title": "src", "source_type": "session",
                "locator": "...", "captured_at": T0, "captured_by": "user-statement",
                "sensitivity": "internal", "acl": ["bb2-team"], "redaction_status": "approved",
                "schema_version": "0.1", "poc_priority": "P2",
                "created_at": T0, "updated_at": T0, "tags": ["ctx"], "evidence_refs": []}
    evref = {"id": "evref.ctx.x", "kind": "EvidenceRef", "status": "reviewed",
             "truth_role": "reference", "title": "e", "evidence_manifest_id": "manifest.ctx.src",
             "ref_type": "session_turn", "locator": "...", "summary": "s",
             "schema_version": "0.1", "poc_priority": "P2",
             "created_at": T0, "updated_at": T0, "tags": ["ctx"], "evidence_refs": []}
    context = {"id": "context.ctx", "kind": "DomainContext", "status": "reviewed",
               "truth_role": "domain", "title": "C", "context_key": "ctx",
               "project_id": "bb2_client", "display_name": "C", "boundary_summary": "b",
               "in_scope": [], "out_of_scope": [],
               "injection_profile": {"default_audience": "coding-agent"},
               "glossary_term_ids": [], "schema_version": "0.1", "poc_priority": "P2",
               "created_at": T0, "updated_at": T0, "tags": ["ctx"], "evidence_refs": []}
    return [context, manifest, evref]


def _mapping_obj(updated_at, **over):
    o = {"id": "mapping.ctx.x", "kind": "DomainMapping", "status": "reviewed",
         "truth_role": "domain", "title": "t", "context_id": "context.ctx",
         "mapping_key": "x", "canonical_summary": "s", "meaning": "m", "boundary": "b",
         "caveats": [], "glossary_term_ids": [], "decision_record_ids": [],
         "code_locator_ids": [], "evidence_refs": ["evref.ctx.x"],
         "schema_version": "0.1", "poc_priority": "P2",
         "created_at": T0, "updated_at": updated_at, "tags": ["ctx"]}
    o.update(over)
    return o


class PreconditionsTest(unittest.TestCase):
    def test_precondition_mismatch_blocks_save(self):
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            ingest(brain, _refs() + [_mapping_obj("2026-06-15T00:00:00Z")])  # 현재 06-15
            # 노트는 옛 시점(06-10)을 기대 → 그 사이 누가 06-15로 고침 → 거부
            new = _mapping_obj("2026-06-16T00:00:00Z", meaning="새 의미")
            with self.assertRaises(IngestError):
                ingest(brain, [new], preconditions={"mapping.ctx.x": "2026-06-10T00:00:00Z"})

    def test_precondition_match_allows_save(self):
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            ingest(brain, _refs() + [_mapping_obj("2026-06-15T00:00:00Z")])
            new = _mapping_obj("2026-06-16T00:00:00Z", boundary="새 경계")
            ingest(brain, [new], preconditions={"mapping.ctx.x": "2026-06-15T00:00:00Z"})  # 일치 → OK
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_ingest.py::PreconditionsTest -v`
Expected: FAIL with "ingest() got an unexpected keyword argument 'preconditions'"

- [ ] **Step 3: Write minimal implementation**

```python
# src/project_brain/ingest.py — ingest 시그니처와 후퇴 가드 블록 수정
def ingest(brain_root, objects, preconditions=None):
    # 1) per-object schema validation (bundle 전체 선검사)
    errors = []
    for obj in objects:
        errors.extend(validate_object(obj))
    if errors:
        raise IngestError("; ".join(errors))
    # 후퇴 가드 + preconditions 재검사 (저장 직전 TOCTOU 방지)
    existing = BrainStore.load(brain_root)
    for obj in objects:
        if existing.has(obj["id"]):
            prev = existing.get(obj["id"])
            if prev.get("status") == "reviewed" and obj.get("status") == "candidate":
                raise IngestError(f"{obj['id']}: refuse reviewed→candidate demotion")
    for oid, expected in (preconditions or {}).items():
        if existing.has(oid) and existing.get(oid).get("updated_at") != expected:
            raise IngestError(
                f"{oid}: precondition 불일치 — build 기대 updated_at {expected!r} != "
                f"현재 {existing.get(oid).get('updated_at')!r} (build 이후 store가 바뀜, 재build 필요)")
    # 2) merged store lint
    merged = {o["id"]: o for o in existing.all()}
    for obj in objects:
        merged[obj["id"]] = obj
    problems = lint_store(BrainStore(merged))
    if problems:
        raise IngestError("; ".join(problems))
    # 3) 통과 후에만 쓰기
    for obj in objects:
        BrainStore.save_object(brain_root, obj)
```

```python
# src/project_brain/cli.py — _run_ingest에 인자 추가
def _run_ingest(argv) -> int:
    parser = argparse.ArgumentParser(prog="cli ingest")
    parser.add_argument("--brain-root", help="코퍼스 루트 (기본: config .project-brain.json)")
    parser.add_argument("--objects-file", required=True)
    parser.add_argument("--preconditions-file",
                        help="build 리포트 JSON (preconditions 키 — 저장 직전 낙관적 잠금 재검사)")
    args = parser.parse_args(argv)

    brain_root = resolve_brain_root(args.brain_root)
    objects = json.loads(Path(args.objects_file).read_text(encoding="utf-8"))
    preconditions = None
    if args.preconditions_file:
        report = json.loads(Path(args.preconditions_file).read_text(encoding="utf-8"))
        preconditions = report.get("preconditions", report)
    try:
        ingest(brain_root, objects, preconditions=preconditions)
    except IngestError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"ok": True, "ingested": len(objects)}, ensure_ascii=False, indent=2))
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest tests/test_ingest.py -v`
Expected: PASS (기존 + PreconditionsTest 2개)

- [ ] **Step 5: Run full engine suite (회귀 없음 확인)**

Run: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest -q`
Expected: 전체 PASS (기존 테스트 + 신규)

- [ ] **Step 6: Update BB2 skill docs**

`~/Desktop/bb2_client/.agents/skills/bb2-brain-ingest/references/ingest-tools.md`의 절차 섹션에 추가:

```markdown
## build — 구조화 노트 → 객체 묶음 (조립 자동화, 2026-06-16)

손으로 조립 스크립트를 짜는 대신 노트(JSON)를 작성하고 build가 변환한다:

1. 노트 작성: context/sources/glossary/code_anchors/mappings/refs/updates/extra_objects
   (decisions는 1차 미지원 — DecisionRecord는 extra_objects로. 스키마는
   `project-brain build --help` + docs/superpowers/plans/2026-06-16-project-brain-assembly-build.md)
2. `project-brain build --notes notes.json --objects-file out.json`
   → 객체 묶음 + diff/resolved_refs/preconditions 리포트 출력 (저장 안 함)
3. diff 확인 (특히 updates의 기존 객체 변경)
4. `project-brain ingest --objects-file out.json --preconditions-file <build리포트.json>`
   → 저장 직전 낙관적 잠금 재검사 후 저장
5. `project-brain index rebuild && project-brain eval && project-brain search "..."`

build가 하는 것: id 파생·객체 연결·근거 묶기·끊긴 참조 검사·diff.
build가 안 하는 것: supersede/강등/충돌 해소/이력 판정 — 그건 노트에 명시(에이전트 판단).
updates는 set(scalar)+union(list) 2종만, claim 필드 수정 시 evidence 동반 필수.
노트로 못 담는 복잡한 케이스는 extra_objects[](완성 객체 직접) 탈출구.
```

`~/Desktop/bb2_client/.agents/skills/bb2-brain-ingest/references/system-domain-playbook.md` §1의 "메인이 Python 한 토막으로 조립" 문장을 "노트를 작성하고 `project-brain build`로 조립(손스크립트는 build로 표현 안 되는 임의 로직만)"으로 갱신.

- [ ] **Step 7: Commit (양 레포 각각)**

```bash
cd ~/Downloads/codes/project-brain
git add src/project_brain/ingest.py src/project_brain/cli.py tests/test_ingest.py
git commit -m "feat(ingest): preconditions 낙관적 잠금 재검사 (build TOCTOU 가드)"

cd ~/Desktop/bb2_client
git add .agents/skills/bb2-brain-ingest/references/ingest-tools.md .agents/skills/bb2-brain-ingest/references/system-domain-playbook.md
git commit -m "docs(bb2-brain-ingest): build 절차 추가 (노트→build→ingest)"
```

---

## 검증 마무리 (2026-06-16 완료)

- [x] 엔진 전체 테스트: `cd ~/Downloads/codes/project-brain && .venv/bin/python -m pytest -q` → **440 passed** (회귀 0)
- [x] 실사용 회귀: 방해버블 적재(39객체)를 노트로 재표현 → `build` → **errors 0, built 39, store 무변경(읽기전용 확인)**. id 39=39·kind 0불일치·GlossaryTerm 6 근거 연결·updates 4 결과(claim+`evidence_unchanged`)·CodeLocator 11·session EvidenceRef 6(`extra_objects`) **전부 동치**. **1차 build로 실전 적재가 닫힘이 실증됨** — 비-code 근거는 `extra_objects`, 기존 매핑 갱신은 `updates`로 깔끔히 표현.
  - **유일 차이**: code EvidenceRef 11개의 표시용 텍스트 3필드(title/summary/locator). 원인 = `code_anchors`에 evref 설명문·인용라인 입력 칸이 없어 build가 `quote`(코드 인용)·`line_start`로 파생. **엔진은 검색·회상에서 evref locator 라인을 안 읽으므로 회상 무영향**(표시 정확도 차원). build 쪽 라인이 `CodeLocator.line_start`와 오히려 더 일관적.
- [x] BB2 골든셋: `project-brain eval` → **8/8 passed** (적재 데이터 안 바뀌고 build/assembly는 검색 경로와 무관 — 회귀 0 확인)
- [x] **build_decisions 신설 (2026-06-26 완료)** — Task 4가 예고한 "decisions 2차" 이행.
  `assembly.py`에 `build_decisions(notes, now)` 추가, 노트 `decisions[]`를 DecisionRecord +
  (commit/jira/pr) EvidenceRef로 결정론 조립. `build()`에 `build_mappings` 다음·`build_context`
  앞으로 배선, 각 결정의 `affects[]`를 그 매핑의 `decision_keys`로 역채움 → `decision_record_ids`
  자동 도출 → lint 8c(매핑↔결정 양방향) 자동 충족. `_VALID_SECTIONS`/`_LIST_SECTIONS`/
  `_ITEM_REQUIRED`에 `"decisions"` 등록, `validate_notes`가 `decisions[].evidence[]` 무결성 1층
  검증. 단일 `now` → 재빌드 idempotent(churn 0). 도메인 무지: commit locator만 `{repo, sha}`
  자동, jira/pr는 노트 제공. assembly **37 passed**(31+6)·엔진 전체 **525 passed**, 볼셀렉
  실코퍼스 14결정 회귀 **"차이 0건 PASS"**. 커밋 `7c2f87c`·`91a9a6c`·`37d0da9`. 다음:
  bb2-brain-ingest 스킬/조립기가 `extra_objects` 손조립 대신 `decisions[]` 노트를 emit하도록 전환(범위 밖).

### 2차 과제 (완전 동치를 위한 선택 개선 — 회상엔 무영향, 우선순위 낮음)

검증에서 드러난 표시 정확도 차이를 없애려면 노트 `code_anchors` 항목에 선택 필드 2개를 추가한다:
- `evref_summary`(또는 `note`): code EvidenceRef의 `title`/`summary`에 코드 인용 대신 사람이 쓴 의미 설명을 넣고 싶을 때.
- `evref_line`: code EvidenceRef의 `locator` 라인을 `line_start`가 아닌 인용 위치 라인으로 지정하고 싶을 때.

둘 다 없으면 build는 `quote`·`line_start`로 파생한다(현재 동작, 회상에 충분).
