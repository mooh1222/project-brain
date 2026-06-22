# BB2 Brain Router DomainMapping Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax. Executed via dynamic workflow orchestration.

**Goal:** Make `QueryRouter.glossary_meaning` answer with reviewed `DomainMapping` content (meaning / boundary / caveats / code_locator_ids) prioritized over plain `GlossaryTerm` definitions, so a question about Race Status / Cooldown / Dummy NPC / Canoe Race is answered from the reviewed mapping, not just the term gloss.

**Architecture:** Additive change to `scripts/bb2_brain/router.py`. New pure-ish helper `_matched_mappings(query)` finds reviewed `DomainMapping` objects whose referenced glossary terms' `term`/`synonyms` text appears in the (canonicalized) query. The `glossary_meaning` branch surfaces those mappings first (with an enriched `mappings` section field) and keeps `DomainContext` + `GlossaryTerm` as trailing alias/definition context. No schema, no intent-classifier change.

**Tech Stack:** Python 3 stdlib, `unittest`. Run from repo root with `PY=/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python`.

**Spec basis:** `docs/superpowers/specs/2026-06-02-bb2-brain-domain-mapping-lifecycle-design.md` (commit `4298f486f2`) §7 ("What does this term mean when I say it?" → reviewed `DomainMapping` plus `GlossaryTerm` aliases) and §9 (mapping-centered, candidate terms still excluded from content).

**Locked design decisions:**
- Extend the existing `glossary_meaning` intent branch; do NOT add a new intent and do NOT change `intent.py` (`"무슨 뜻"`/`"용어"` already classify these queries).
- Match a reviewed `DomainMapping` when the canonical query contains the `term` or any `synonym` of a `GlossaryTerm` the mapping references via `glossary_term_ids` — even if that term is `candidate`, because the mapping is the reviewed unit and the term is only its language surface (spec §3.3/§9). This is required: on disk the Sally terms (race-state, cooldown, dummy-npc, canoe-race) are `candidate`; only the mappings are reviewed.
- We surface the candidate term's *text as a lookup key only*; the answer content comes from the reviewed mapping, so no candidate definition is projected (consistent with §9 "candidate terms excluded from content").
- The router returns ids + an enriched section (like `why_changed` carries `events`/`fact_changes`); it does not render prose. "Prioritize meaning/boundary/caveats/code_locator_ids" = put those mapping fields in the section's new `mappings` list and list mapping ids before glossary ids.
- Out of scope (surgical, note as follow-up): the `evidence_provenance` co-intent mapping defense; a dedicated "what should the coding agent assume now?" intent; generic ingest automation.

**Baseline (verify before starting):** `PY -m pytest scripts/bb2_brain/tests -q` → 154 passed; disk store lint-clean (92 objects). The router's current `glossary_meaning` branch is `scripts/bb2_brain/router.py:174-179`; helper `_matched_glossary_terms` is `router.py:263-278`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `scripts/bb2_brain/router.py` | Query routing | Modify: add `_matched_mappings`; enrich `glossary_meaning` branch |
| `scripts/bb2_brain/tests/test_router.py` | Router unit tests | Modify: add 2 mapping-prioritization tests |

`PY=/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python`

---

## Task 1: Prioritize reviewed DomainMapping in glossary_meaning

**Files:**
- Modify: `scripts/bb2_brain/router.py`
- Test: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: Write the failing tests**

Add these two methods to `class RouterTest` in `scripts/bb2_brain/tests/test_router.py` (place them right after `test_glossary_meaning_routes_to_domain_context_and_glossary_term`):

```python
    def _mapping_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/domain/context.json", {
            "id": "context.sally-canoe", "kind": "DomainContext", "status": "reviewed",
            "truth_role": "domain", "title": "Sally Canoe", "context_key": "sally-canoe",
            "project_id": "bb2-client", "display_name": "Sally Canoe",
            "boundary_summary": "Race lifecycle vocabulary.", "in_scope": [], "out_of_scope": [],
            "injection_profile": {"default_audience": "coding-agent", "include_candidates": False},
            "glossary_term_ids": ["glossary.sally-canoe.race-state"], "evidence_refs": [],
        })
        # The term that carries the user-facing text is candidate; the MAPPING is the reviewed unit.
        write_object(root, "objects/domain/term_race_state.json", {
            "id": "glossary.sally-canoe.race-state", "kind": "GlossaryTerm", "status": "candidate",
            "truth_role": "domain", "term": "Race Status", "synonyms": ["Race State"],
            "definition": "candidate gloss, should not be the primary answer.",
            "candidate": {"candidate_state": "conflict", "candidate_source": "spec",
                          "open_questions": ["server vs view"]},
            "context_id": "context.sally-canoe", "evidence_refs": [],
        })
        write_object(root, "objects/mappings/race_status.json", {
            "id": "mapping.sally-canoe.race-status", "kind": "DomainMapping", "status": "reviewed",
            "truth_role": "domain", "title": "race-status mapping",
            "context_id": "context.sally-canoe", "mapping_key": "race-status",
            "canonical_summary": "Server SALLY_CANOE_RACE_STATUS is the domain status.",
            "meaning": "Race status is the server enum; presenter derives the view state.",
            "boundary": "Server status is the domain truth; view state is derived.",
            "caveats": ["View state READY/RACING/COOLDOWN/ENDED is a UI projection."],
            "glossary_term_ids": ["glossary.sally-canoe.race-state"],
            "decision_record_ids": ["decision.sally-canoe.race-status"],
            "code_locator_ids": ["locator.sally.event-model-hpp", "locator.sally.viewdata-state"],
            "evidence_refs": [], "review_record_id": "review.bundle.sally-canoe.domain-mapping",
        })
        return BrainStore.load(root)

    def test_glossary_meaning_prioritizes_reviewed_domain_mapping(self):
        router = QueryRouter(self._mapping_store())
        answer = router.answer("Race Status 무슨 뜻이야?")
        self.assertEqual(answer["intents"], ["glossary_meaning"])
        self.assertIn("mapping.sally-canoe.race-status", answer["source_object_ids"])
        section = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
        # mapping is surfaced first, before the glossary/context ids
        self.assertEqual(section["object_ids"][0], "mapping.sally-canoe.race-status")
        # enriched mapping content is carried for prioritized use
        self.assertEqual(len(section["mappings"]), 1)
        detail = section["mappings"][0]
        self.assertEqual(detail["id"], "mapping.sally-canoe.race-status")
        self.assertEqual(detail["mapping_key"], "race-status")
        self.assertIn("server enum", detail["meaning"])
        self.assertIn("domain truth", detail["boundary"])
        self.assertTrue(detail["caveats"])
        self.assertIn("locator.sally.event-model-hpp", detail["code_locator_ids"])
        # the candidate term is only a routing key (matched as the mapping's language surface);
        # per spec §9 candidate terms are NOT surfaced as separate context objects — the link lives in the mapping.
        self.assertNotIn("glossary.sally-canoe.race-state", section["object_ids"])
        self.assertIn(
            "glossary.sally-canoe.race-state",
            router.store.get("mapping.sally-canoe.race-status")["glossary_term_ids"],
        )
        self.assertEqual(answer["status"], "reviewed")

    def test_glossary_meaning_without_mapping_keeps_legacy_behavior(self):
        router = QueryRouter(self.build_store())
        answer = router.answer("입장팝업이 무슨 뜻이야?")
        section = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
        self.assertEqual(section["mappings"], [])
        self.assertIn("context.stage-clear-token", answer["source_object_ids"])
        self.assertIn("term.popup-enter", answer["source_object_ids"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PY=/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python; $PY -m pytest scripts/bb2_brain/tests/test_router.py -q -k "glossary_meaning"`
Expected: `test_glossary_meaning_prioritizes_reviewed_domain_mapping` FAILS (no `mappings` key / mapping not surfaced); `test_glossary_meaning_without_mapping_keeps_legacy_behavior` FAILS with `KeyError: 'mappings'`.

- [ ] **Step 3: Add the `_matched_mappings` helper**

In `scripts/bb2_brain/router.py`, add this method to `class QueryRouter` (place it right after `_matched_glossary_terms`, which ends at line ~278):

```python
    def _matched_mappings(self, query: str) -> list[dict]:
        """query에 등장하는 용어 텍스트로 reviewed DomainMapping을 찾는다.
        매핑이 검수 단위이므로, 참조하는 GlossaryTerm이 candidate여도 그 term/synonym 텍스트를
        매핑의 언어 표면(language surface)으로 써서 매칭한다 (spec §3.3/§9). 답변 내용은 후보 용어
        정의가 아니라 reviewed 매핑에서 나오므로 candidate 정의가 노출되지는 않는다."""
        result = []
        for mapping in self._reviewed_by_kind("DomainMapping"):
            surfaces: set[str] = set()
            for term_id in mapping.get("glossary_term_ids", []):
                if not self.store.has(term_id):
                    continue
                term = self.store.get(term_id)
                if term.get("term"):
                    surfaces.add(term["term"])
                for synonym in term.get("synonyms") or []:
                    surfaces.add(synonym)
            if any(surface and surface in query for surface in surfaces):
                result.append(mapping)
        return result
```

- [ ] **Step 4: Enrich the `glossary_meaning` branch**

In `scripts/bb2_brain/router.py`, replace the current `glossary_meaning` branch (lines ~174-179):

```python
            elif intent == "glossary_meaning":
                glossary_objects = self._reviewed_by_kind("DomainContext") + self._reviewed_by_kind("GlossaryTerm")
                for obj in glossary_objects:
                    source_ids.append(obj["id"])
                    claim_statuses.append(claim_status(obj, raw_available=self._raw_available_for(obj), restricted=False))
                sections.append({"intent": intent, "object_ids": [obj["id"] for obj in glossary_objects], "summary": "Glossary definition"})
```

with:

```python
            elif intent == "glossary_meaning":
                # spec §7: "내가 이 용어 말하면 무슨 뜻?" → reviewed DomainMapping 우선, GlossaryTerm은 alias.
                matched_mappings = self._matched_mappings(canonical)
                section_ids: list[str] = []
                mapping_details = []
                for mapping in matched_mappings:
                    source_ids.append(mapping["id"])
                    section_ids.append(mapping["id"])
                    claim_statuses.append(claim_status(mapping, raw_available=self._raw_available_for(mapping), restricted=self._restricted_for(mapping)))
                    mapping_details.append({
                        "id": mapping["id"],
                        "mapping_key": mapping.get("mapping_key"),
                        "meaning": mapping.get("meaning", ""),
                        "boundary": mapping.get("boundary", ""),
                        "caveats": mapping.get("caveats") or [],
                        "code_locator_ids": mapping.get("code_locator_ids") or [],
                    })
                glossary_objects = self._reviewed_by_kind("DomainContext") + self._reviewed_by_kind("GlossaryTerm")
                for obj in glossary_objects:
                    source_ids.append(obj["id"])
                    section_ids.append(obj["id"])
                    claim_statuses.append(claim_status(obj, raw_available=self._raw_available_for(obj), restricted=False))
                summary = "Glossary definition (reviewed mappings prioritized)" if matched_mappings else "Glossary definition"
                sections.append({"intent": intent, "object_ids": section_ids, "mappings": mapping_details, "summary": summary})
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `$PY -m pytest scripts/bb2_brain/tests/test_router.py -q`
Expected: PASS (both new tests + all existing router tests; the legacy glossary fixtures have no `DomainMapping`, so `mappings` is `[]` and `source_object_ids` still contain the context/term ids).

Then the full suite: `$PY -m pytest scripts/bb2_brain/tests -q`
Expected: PASS (154 prior + 2 new = 156).

- [ ] **Step 6: Disk smoke check (real Sally store)**

Run from repo root:

```bash
$PY -c "
from pathlib import Path
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.router import QueryRouter
r = QueryRouter(BrainStore.load(Path('scripts/bb2_brain/brain')))
for q in ['Race Status 무슨 뜻이야?', 'Cooldown 무슨 뜻이야?', 'Dummy NPC 용어 설명해줘', 'Canoe Race 무슨 뜻이야?']:
    a = r.answer(q)
    sec = next(s for s in a['sections'] if s['intent']=='glossary_meaning')
    print(q, '->', [m['id'] for m in sec['mappings']])
"
```
Expected: each query prints the matching `mapping.sally-canoe.*` id (race-status, cooldown, participant for Dummy NPC, naming for Canoe Race). This is a smoke check, not a committed test.

- [ ] **Step 7: Lint stays clean**

```bash
$PY -c "
from pathlib import Path
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.lint import lint_store
print('PROBLEMS', lint_store(BrainStore.load(Path('scripts/bb2_brain/brain')), workspace_root=Path('.')))
"
```
Expected: `PROBLEMS []` (this task changes no objects, so lint is unaffected — confirm anyway).

- [ ] **Step 8: Commit**

Do NOT stage the unrelated dirty files (`LineBubble2/Classes/bo/UserGameDataManager.cpp`, `LineBubble2/Classes/main/map/MapController.cpp`, `LineBubble2/Classes/splash/SplashController.cpp`, `Podfile.lock`).

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: route glossary_meaning to reviewed domain mappings

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** §7 "what does this term mean when I say it" → reviewed `DomainMapping` prioritized + `GlossaryTerm` aliases retained (Task 1). §9 candidate-terms-excluded-from-content honored: candidate term text is used only as a match key; answer content is the reviewed mapping (Task 1 design note + the candidate-term-in-fixture test).

**Backward compatibility:** existing `glossary_meaning` tests use fixtures with no `DomainMapping`; the branch adds `mappings: []` and still appends `DomainContext` + `GlossaryTerm` to `source_object_ids`, so `test_glossary_meaning_routes_to_domain_context_and_glossary_term` and `test_evidence_with_glossary_defends_glossary_provenance` remain green. The new `mappings` section key is additive (no existing test asserts the absence of section keys).

**Type/name consistency:** helper `_matched_mappings`; section field `mappings` with `{id, mapping_key, meaning, boundary, caveats, code_locator_ids}`; matched mapping ids are prepended to `object_ids` and to `source_ids`. `canonical` (already computed at the top of `answer()`) is the query passed to `_matched_mappings`, matching how other branches use the normalized query.

**Deferred (noted, not implemented):** `evidence_provenance` co-intent does not yet defend mapping evidence chains; no dedicated "what should the coding agent assume now?" intent; generic ingest automation (spec §13.7).
