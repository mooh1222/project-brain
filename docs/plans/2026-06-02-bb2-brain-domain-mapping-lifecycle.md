# BB2 Brain Domain Mapping Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan is executed via dynamic workflow orchestration per the user's standing request.

**Goal:** Add `DecisionRecord` and `DomainMapping` objects, mapping review bundles, mapping-level drift lint, mapping-centered context projection, and a Sally Canoe mapping bundle fixture + update-ingest tests — so Brain can store evidence-backed domain meanings, project reviewed mappings, and flag when a newer decision needs re-review.

**Architecture:** Per-file JSON object graph under `scripts/bb2_brain/brain/`. Schema validation is field/enum based (`schema.py`); lint scans the whole store for integrity (`lint.py`); projection renders disposable `CONTEXT.md` from reviewed objects (`context_projection.py`). New kinds follow the existing per-concept storage-dir convention. Review bundles reuse `ReviewRecord` (no new object kind). "review-needed" is a blocking lint problem, never a status value.

**Tech Stack:** Python 3 stdlib only, `unittest`. Run with `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-06-02-bb2-brain-domain-mapping-lifecycle-design.md` (commit `4298f486f2`).

**Locked design decisions (from spec + user):**
- `review-needed` is **not** a new status value. A newer `DecisionRecord` that affects a reviewed mapping the mapping has not incorporated → blocking lint problem for **that one mapping only** (never whole-bundle rollback). Spec §6.1, §8.3.
- Sally Canoe's 4 mappings are promoted as **one bundle** via `confirmation_key = "bundle.sally-canoe.domain-mapping"` producing one auditable `ReviewRecord` with `review_scope = "mapping_bundle"`. Spec §10, AC §12.6–7.
- Storage dirs: `DomainMapping` → `objects/mappings/`, `DecisionRecord` → `objects/decisions/` (matches the existing split-by-concept convention: specs/comms/code each have their own dir).
- The Jira-not-reflected update scenario is **test-only**, not materialized on disk — materializing it would intentionally make the disk store lint-dirty (a blocking review-needed problem is the expected output).
- Out of scope (surgical): `router.py` glossary_meaning integration, generic ingest automation (spec §13.7), the "reviewed glossary term has no mapping" lint bullet (would flag the existing stage-clear-token store). Note these as follow-ups, do not implement.

**Baseline (verified before planning):** 123 tests pass; disk store lint-clean with 83 objects; `glossary.sally-canoe.race-stage` is the only reviewed Sally term; projection `source_object_ids = [context.sally-canoe, glossary.sally-canoe.race-stage]`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `scripts/bb2_brain/schema.py` | Kind required-fields + enum validation | Modify: add `DecisionRecord`, `DomainMapping` kinds; `ReviewRecord` review_type/review_scope/bundle fields; new enum sets |
| `scripts/bb2_brain/store.py` | Kind → storage dir map | Modify: add 2 `_KIND_DIR` entries |
| `scripts/bb2_brain/lint.py` | Store-wide integrity scan | Modify: add mapping/decision dangling-link, review-needed drift, supersession, ReviewRecord target checks |
| `scripts/bb2_brain/context_projection.py` | Render reviewed objects → CONTEXT.md | Modify: add reviewed-mapping section + source ids/hash |
| `scripts/bb2_brain/ingest_sally_canoe_mappings.py` | Sally Canoe mapping bundle fixture + update/supersession fixtures + CLI | Create |
| `scripts/bb2_brain/tests/test_schema.py` | Schema unit tests | Modify: add DecisionRecord/DomainMapping/ReviewRecord tests |
| `scripts/bb2_brain/tests/test_lint.py` | Lint unit tests | Modify: add mapping lint tests |
| `scripts/bb2_brain/tests/test_context_projection.py` | Projection unit tests | Modify: add reviewed-mapping tests |
| `scripts/bb2_brain/tests/test_ingest_sally_canoe_mappings.py` | Mapping ingest + bundle + update tests | Create |
| `scripts/bb2_brain/brain/objects/decisions/*.json` | Materialized DecisionRecords | Create (Task 6, via CLI) |
| `scripts/bb2_brain/brain/objects/mappings/*.json` | Materialized DomainMappings | Create (Task 6, via CLI) |
| `scripts/bb2_brain/brain/objects/reviews/review.bundle.sally-canoe.domain-mapping.json` | Bundle review record | Create (Task 6, via CLI) |
| `docs/contexts/generated/sally-canoe/CONTEXT.md` + projection object | Regenerated projection | Modify (Task 6, via CLI) |

`PY` shorthand used in commands: `PY=/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python`

---

## Task 1: Schema for DecisionRecord, DomainMapping, ReviewRecord bundle fields

**Files:**
- Modify: `scripts/bb2_brain/schema.py`
- Modify: `scripts/bb2_brain/store.py`
- Test: `scripts/bb2_brain/tests/test_schema.py`

- [ ] **Step 1: Write the failing tests**

Add these methods to `class SchemaTest` in `scripts/bb2_brain/tests/test_schema.py`:

```python
    def _decision(self, **over):
        obj = {
            "id": "decision.sally-canoe.naming", "kind": "DecisionRecord", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "event",
            "title": "naming decision", "created_at": "2026-06-02T00:00:00+09:00",
            "updated_at": "2026-06-02T00:00:00+09:00", "tags": ["bb2-client"], "evidence_refs": [],
            "decision_type": "naming_decision", "summary": "Canoe Race canonical name.",
            "decision": "Canoe Race is canonical; Sally Canoe / 샐리의 카누 are aliases.",
            "source_object_ids": ["manifest.sally-canoe-spec-v8"],
            "affected_context_ids": ["context.sally-canoe"],
            "spec_reflected": "yes",
        }
        obj.update(over)
        return obj

    def test_decision_record_valid(self):
        self.assertEqual(validate_object(self._decision()), [])

    def test_decision_record_invalid_decision_type_reported(self):
        errors = validate_object(self._decision(decision_type="rename"))
        self.assertTrue(any("invalid decision_type" in e for e in errors))

    def test_decision_record_invalid_spec_reflected_reported(self):
        errors = validate_object(self._decision(spec_reflected="maybe"))
        self.assertTrue(any("invalid spec_reflected" in e for e in errors))

    def test_decision_record_missing_required_reported(self):
        obj = self._decision()
        del obj["decision"]
        errors = validate_object(obj)
        self.assertTrue(any("decision" in e for e in errors))

    def test_decision_record_truth_role_must_be_event(self):
        errors = validate_object(self._decision(truth_role="domain"))
        self.assertTrue(any("invalid truth_role" in e and "DecisionRecord" in e for e in errors))

    def _mapping(self, **over):
        obj = {
            "id": "mapping.sally-canoe.naming", "kind": "DomainMapping", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "domain",
            "title": "naming mapping", "created_at": "2026-06-02T00:00:00+09:00",
            "updated_at": "2026-06-02T00:00:00+09:00", "tags": ["bb2-client"], "evidence_refs": [],
            "context_id": "context.sally-canoe", "mapping_key": "naming",
            "canonical_summary": "Canoe Race is the current planning name for the Sally Canoe event.",
            "meaning": "User words Sally Canoe / 샐리의 카누 refer to the Canoe Race event concept.",
            "boundary": "Naming only; race rules are covered by other mappings.",
            "glossary_term_ids": ["glossary.sally-canoe.canoe-race"],
            "decision_record_ids": ["decision.sally-canoe.naming"],
            "review_state": {"meaning_reviewed": True, "projection_reviewed": True},
        }
        obj.update(over)
        return obj

    def test_domain_mapping_valid(self):
        self.assertEqual(validate_object(self._mapping()), [])

    def test_domain_mapping_truth_role_must_be_domain(self):
        errors = validate_object(self._mapping(truth_role="event"))
        self.assertTrue(any("invalid truth_role" in e and "DomainMapping" in e for e in errors))

    def test_domain_mapping_missing_required_reported(self):
        obj = self._mapping()
        del obj["meaning"]
        errors = validate_object(obj)
        self.assertTrue(any("meaning" in e for e in errors))

    def test_domain_mapping_invalid_review_state_key_reported(self):
        errors = validate_object(self._mapping(review_state={"bogus_reviewed": True}))
        self.assertTrue(any("invalid review_state key" in e for e in errors))

    def test_domain_mapping_non_boolean_review_state_reported(self):
        errors = validate_object(self._mapping(review_state={"meaning_reviewed": "yes"}))
        self.assertTrue(any("review_state" in e and "boolean" in e for e in errors))

    def _bundle_review(self, **over):
        obj = {
            "id": "review.bundle.sally-canoe.domain-mapping", "kind": "ReviewRecord", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "review",
            "title": "Sally Canoe mapping bundle review", "created_at": "2026-06-02T00:00:00+09:00",
            "updated_at": "2026-06-02T00:00:00+09:00", "tags": ["bb2-client"], "evidence_refs": [],
            "reviewer": "user-confirmed", "reviewed_at": "2026-06-02T00:00:00+09:00", "verdict": "approved",
            "review_type": "meaning_review", "review_scope": "mapping_bundle",
            "bundle_key": "bundle.sally-canoe.domain-mapping",
            "confirmation_key": "bundle.sally-canoe.domain-mapping",
            "target_object_ids": ["mapping.sally-canoe.naming", "mapping.sally-canoe.race-status"],
        }
        obj.update(over)
        return obj

    def test_bundle_review_record_valid(self):
        self.assertEqual(validate_object(self._bundle_review()), [])

    def test_bundle_review_requires_target_object_ids(self):
        obj = self._bundle_review()
        del obj["target_object_ids"]
        errors = validate_object(obj)
        self.assertTrue(any("target_object_ids" in e for e in errors))

    def test_bundle_review_requires_confirmation_key(self):
        obj = self._bundle_review()
        del obj["confirmation_key"]
        errors = validate_object(obj)
        self.assertTrue(any("confirmation_key" in e for e in errors))

    def test_single_review_still_requires_target_object_id(self):
        review = self._bundle_review(review_scope="single_object", target_object_ids=None)
        del review["target_object_ids"]
        review.pop("target_object_id", None)
        errors = validate_object(review)
        self.assertTrue(any("target_object_id" in e for e in errors))

    def test_invalid_review_type_reported(self):
        errors = validate_object(self._bundle_review(review_type="bogus_review"))
        self.assertTrue(any("invalid review_type" in e for e in errors))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PY=/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python; $PY -m pytest scripts/bb2_brain/tests/test_schema.py -q`
Expected: FAIL — `test_domain_mapping_valid` etc. report "unknown kind 'DomainMapping'" / "unknown kind 'DecisionRecord'"; bundle tests fail because `target_object_id` is still unconditionally required.

- [ ] **Step 3: Implement schema additions**

In `scripts/bb2_brain/schema.py`, add the two new kinds to `KIND_REQUIRED` (after the `"SlackThread"` entry) and **change the `ReviewRecord` entry** to drop `target_object_id` (handled conditionally):

```python
    "ReviewRecord": ("reviewer", "reviewed_at", "verdict"),
```

Add inside `KIND_REQUIRED` dict:

```python
    "DecisionRecord": ("decision_type", "summary", "decision", "source_object_ids",
                       "affected_context_ids", "spec_reflected"),
    "DomainMapping": ("context_id", "mapping_key", "canonical_summary", "meaning",
                      "boundary", "glossary_term_ids", "decision_record_ids"),
```

Add to `KIND_TRUTH_ROLE` dict:

```python
    "DecisionRecord": "event",
    "DomainMapping": "domain",
```

Add new enum sets near the other `*_VALUES` frozensets:

```python
# spec §5.1 DecisionRecord.decision_type / spec_reflected
DECISION_TYPE_VALUES = frozenset({
    "spec_clarification", "spec_revision", "improvement", "qa_issue",
    "sanity_change", "hotfix_change", "naming_decision", "implementation_boundary",
})
SPEC_REFLECTED_VALUES = frozenset({"yes", "no", "unknown", "not_applicable"})
# spec §6 ReviewRecord.review_type / §6.1 review_scope / §5.2 DomainMapping.review_state
REVIEW_TYPE_VALUES = frozenset({
    "meaning_review", "evidence_review", "implementation_review",
    "projection_review", "supersession_review",
})
REVIEW_SCOPE_VALUES = frozenset({"single_object", "mapping_bundle"})
REVIEW_STATE_KEYS = frozenset({
    "meaning_reviewed", "evidence_reviewed", "implementation_reviewed", "projection_reviewed",
})
```

Add validation branches at the end of `validate_object`, before `return errors` (extend the existing `if kind == ... elif ...` chain):

```python
    elif kind == "DecisionRecord":
        decision_type = obj.get("decision_type")
        if decision_type is not None and decision_type not in DECISION_TYPE_VALUES:
            errors.append(f"{obj['id']}: DecisionRecord invalid decision_type {decision_type!r}")
        spec_reflected = obj.get("spec_reflected")
        if spec_reflected is not None and spec_reflected not in SPEC_REFLECTED_VALUES:
            errors.append(f"{obj['id']}: DecisionRecord invalid spec_reflected {spec_reflected!r}")
    elif kind == "DomainMapping":
        review_state = obj.get("review_state")
        if review_state is not None:
            if not isinstance(review_state, dict):
                errors.append(f"{obj['id']}: DomainMapping review_state must be an object")
            else:
                for rs_key, rs_val in review_state.items():
                    if rs_key not in REVIEW_STATE_KEYS:
                        errors.append(f"{obj['id']}: DomainMapping invalid review_state key {rs_key!r}")
                    elif not isinstance(rs_val, bool):
                        errors.append(f"{obj['id']}: DomainMapping review_state {rs_key!r} must be boolean")
    elif kind == "ReviewRecord":
        review_type = obj.get("review_type")
        if review_type is not None and review_type not in REVIEW_TYPE_VALUES:
            errors.append(f"{obj['id']}: ReviewRecord invalid review_type {review_type!r}")
        review_scope = obj.get("review_scope")
        if review_scope is not None and review_scope not in REVIEW_SCOPE_VALUES:
            errors.append(f"{obj['id']}: ReviewRecord invalid review_scope {review_scope!r}")
        if review_scope == "mapping_bundle":
            if not obj.get("target_object_ids"):
                errors.append(f"{obj['id']}: mapping_bundle ReviewRecord requires target_object_ids")
            if not obj.get("confirmation_key"):
                errors.append(f"{obj['id']}: mapping_bundle ReviewRecord requires confirmation_key")
        elif "target_object_id" not in obj:
            errors.append(f"{obj['id']}: ReviewRecord missing field 'target_object_id'")
```

- [ ] **Step 4: Add storage dirs**

In `scripts/bb2_brain/store.py`, add to `_KIND_DIR` (after the `"DomainContext"`/`"GlossaryTerm"` entries):

```python
        "DomainMapping": "objects/mappings",
        "DecisionRecord": "objects/decisions",
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `$PY -m pytest scripts/bb2_brain/tests/test_schema.py -q`
Expected: PASS (all new + existing schema tests). Then run the full suite to confirm no regression: `$PY -m pytest scripts/bb2_brain/tests -q` → Expected: PASS (still 123 + new schema tests).

- [ ] **Step 6: Commit**

```bash
git add scripts/bb2_brain/schema.py scripts/bb2_brain/store.py scripts/bb2_brain/tests/test_schema.py
git commit -m "feat: add DecisionRecord/DomainMapping schema and review bundle fields

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Lint guards for mapping links, review-needed drift, supersession

**Files:**
- Modify: `scripts/bb2_brain/lint.py`
- Test: `scripts/bb2_brain/tests/test_lint.py`

Depends on Task 1 (schema kinds + storage dirs).

- [ ] **Step 1: Write the failing tests**

Add these helpers + tests to `class LintTest` in `scripts/bb2_brain/tests/test_lint.py`:

```python
    def _mapping(self, **over):
        obj = {
            "id": "mapping.sally-canoe.race-status", "kind": "DomainMapping", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "domain",
            "title": "race-status mapping", "tags": [], "evidence_refs": [],
            "created_at": "2026-06-02T00:00:00+09:00", "updated_at": "2026-06-02T00:00:00+09:00",
            "context_id": "context.sally-canoe", "mapping_key": "race-status",
            "canonical_summary": "Server SALLY_CANOE_RACE_STATUS is the domain status.",
            "meaning": "Race status is the server enum; view state is a UI display mapping.",
            "boundary": "Server status vs UI display state.",
            "glossary_term_ids": [], "decision_record_ids": ["decision.sally-canoe.race-status"],
        }
        obj.update(over)
        return obj

    def _decision(self, **over):
        obj = {
            "id": "decision.sally-canoe.race-status", "kind": "DecisionRecord", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "event",
            "title": "race-status decision", "tags": [], "evidence_refs": [],
            "created_at": "2026-06-02T00:00:00+09:00", "updated_at": "2026-06-02T00:00:00+09:00",
            "decision_type": "implementation_boundary", "summary": "Server status is the domain truth.",
            "decision": "Domain status = server SALLY_CANOE_RACE_STATUS; view state derives from it.",
            "source_object_ids": [], "affected_context_ids": ["context.sally-canoe"],
            "affected_mapping_ids": ["mapping.sally-canoe.race-status"], "spec_reflected": "yes",
        }
        obj.update(over)
        return obj

    def test_mapping_dangling_decision_record_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/mappings/m.json",
                         self._mapping(decision_record_ids=["decision.ghost"]))
            problems = lint_store(BrainStore.load(root))
            self.assertTrue(any("dangling decision_record_ids" in p and "decision.ghost" in p for p in problems))

    def test_decision_dangling_affected_mapping_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/decisions/d.json",
                         self._decision(affected_mapping_ids=["mapping.ghost"]))
            problems = lint_store(BrainStore.load(root))
            self.assertTrue(any("dangling affected_mapping_ids" in p and "mapping.ghost" in p for p in problems))

    def test_incorporated_decision_no_review_needed(self):
        """Initial state: mapping already lists the decision that affects it → no drift problem."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/mappings/m.json", self._mapping())
            write_object(root, "objects/decisions/d.json", self._decision())
            problems = lint_store(BrainStore.load(root))
            self.assertFalse(any("review needed" in p for p in problems))

    def test_unincorporated_decision_emits_review_needed_for_that_mapping_only(self):
        """A later decision affects the reviewed mapping but is not incorporated → blocking review-needed,
        and only the affected mapping is flagged (no whole-bundle rollback)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/mappings/m.json", self._mapping())
            write_object(root, "objects/mappings/other.json", self._mapping(
                id="mapping.sally-canoe.cooldown", mapping_key="cooldown",
                decision_record_ids=["decision.sally-canoe.cooldown"]))
            write_object(root, "objects/decisions/d.json", self._decision())  # incorporated by race-status
            write_object(root, "objects/decisions/jira.json", self._decision(
                id="decision.sally-canoe.race-status-v2", decision_type="improvement",
                spec_reflected="no", affected_mapping_ids=["mapping.sally-canoe.race-status"]))
            problems = lint_store(BrainStore.load(root))
            review_needed = [p for p in problems if "review needed" in p]
            self.assertTrue(any("mapping.sally-canoe.race-status" in p and "decision.sally-canoe.race-status-v2" in p
                                and "spec_reflected=no" in p for p in review_needed))
            self.assertFalse(any("mapping.sally-canoe.cooldown" in p for p in review_needed))

    def test_superseded_mapping_must_not_stay_reviewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/mappings/old.json", self._mapping())  # status reviewed
            write_object(root, "objects/mappings/new.json", self._mapping(
                id="mapping.sally-canoe.race-status-v2", mapping_key="race-status",
                supersedes_mapping_ids=["mapping.sally-canoe.race-status"]))
            problems = lint_store(BrainStore.load(root))
            self.assertTrue(any("mapping.sally-canoe.race-status" in p and "superseded by" in p
                                and "still 'reviewed'" in p for p in problems))

    def test_supersession_clean_when_old_marked_superseded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/mappings/old.json", self._mapping(status="superseded"))
            write_object(root, "objects/mappings/new.json", self._mapping(
                id="mapping.sally-canoe.race-status-v2", mapping_key="race-status",
                supersedes_mapping_ids=["mapping.sally-canoe.race-status"],
                decision_record_ids=["decision.sally-canoe.race-status"]))
            write_object(root, "objects/decisions/d.json",
                         self._decision(affected_mapping_ids=["mapping.sally-canoe.race-status-v2"]))
            problems = lint_store(BrainStore.load(root))
            self.assertFalse(any("superseded by" in p or "review needed" in p for p in problems))

    def test_review_record_dangling_target_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/reviews/r.json", {
                "id": "review.bundle.x", "kind": "ReviewRecord", "schema_version": "0.1",
                "status": "reviewed", "poc_priority": "P0", "truth_role": "review",
                "title": "bundle", "tags": [], "evidence_refs": [],
                "created_at": "2026-06-02T00:00:00+09:00", "updated_at": "2026-06-02T00:00:00+09:00",
                "reviewer": "user-confirmed", "reviewed_at": "2026-06-02T00:00:00+09:00", "verdict": "approved",
                "review_scope": "mapping_bundle", "confirmation_key": "bundle.x",
                "target_object_ids": ["mapping.ghost"],
            })
            problems = lint_store(BrainStore.load(root))
            self.assertTrue(any("dangling target_object_ids" in p and "mapping.ghost" in p for p in problems))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest scripts/bb2_brain/tests/test_lint.py -q`
Expected: FAIL — the new drift/supersession/dangling problems are not yet produced by `lint_store`.

- [ ] **Step 3: Implement lint guards**

In `scripts/bb2_brain/lint.py`, inside `lint_store`, after the existing block 7 (`ContextProjection guard`) and before the `if workspace_root is not None:` block, insert:

```python
    # 8) DomainMapping / DecisionRecord lifecycle integrity (spec §5, §6.1, §8.3).
    mappings = store.by_kind("DomainMapping")
    decisions = store.by_kind("DecisionRecord")

    # 8a) dangling mapping reference links
    for mapping in mappings:
        link_fields = (
            ("context_id", [mapping.get("context_id")]),
            ("glossary_term_ids", mapping.get("glossary_term_ids") or []),
            ("decision_record_ids", mapping.get("decision_record_ids") or []),
            ("spec_revision_ids", mapping.get("spec_revision_ids") or []),
            ("code_locator_ids", mapping.get("code_locator_ids") or []),
            ("supersedes_mapping_ids", mapping.get("supersedes_mapping_ids") or []),
        )
        for field_name, ids in link_fields:
            for ref_id in ids:
                if ref_id and not store.has(ref_id):
                    problems.append(f"{mapping['id']}: dangling {field_name} {ref_id}")

    # 8b) dangling decision reference links
    for decision in decisions:
        link_fields = (
            ("source_object_ids", decision.get("source_object_ids") or []),
            ("affected_context_ids", decision.get("affected_context_ids") or []),
            ("affected_mapping_ids", decision.get("affected_mapping_ids") or []),
            ("affected_glossary_term_ids", decision.get("affected_glossary_term_ids") or []),
            ("spec_revision_ids", decision.get("spec_revision_ids") or []),
            ("jira_issue_ids", decision.get("jira_issue_ids") or []),
            ("slack_thread_ids", decision.get("slack_thread_ids") or []),
            ("code_locator_ids", decision.get("code_locator_ids") or []),
        )
        for field_name, ids in link_fields:
            for ref_id in ids:
                if ref_id and not store.has(ref_id):
                    problems.append(f"{decision['id']}: dangling {field_name} {ref_id}")

    # 8c) review-needed drift (spec §8.3): a decision affects a reviewed mapping the mapping has
    #     not incorporated (not in decision_record_ids) and is not superseded (status != reviewed).
    #     Blocking, and mapping-specific — never a whole-bundle rollback (spec §6.1).
    #     Detection is by non-incorporation (update-ingest arrival order), NOT wall-clock
    #     timestamps: fixtures share one timestamp, and "affects but not incorporated" is the
    #     precise drift signal — a created_at gate would both miss old-but-unincorporated
    #     decisions and break the same-timestamp Jira update fixture.
    mappings_by_id = {m["id"]: m for m in mappings}
    for decision in decisions:
        for mapping_id in decision.get("affected_mapping_ids") or []:
            mapping = mappings_by_id.get(mapping_id)
            if mapping is None or mapping.get("status") != "reviewed":
                continue
            if decision["id"] in (mapping.get("decision_record_ids") or []):
                continue
            problems.append(
                f"{mapping_id}: unincorporated decision {decision['id']} may affect reviewed mapping; "
                f"review needed (spec_reflected={decision.get('spec_reflected')})"
            )

    # 8d) supersession consistency: a mapping superseded by another must not stay reviewed.
    for mapping in mappings:
        for superseded_id in mapping.get("supersedes_mapping_ids") or []:
            if not store.has(superseded_id):
                continue  # dangling already reported in 8a
            if store.get(superseded_id).get("status") == "reviewed":
                problems.append(
                    f"{superseded_id}: superseded by {mapping['id']} but status is still 'reviewed'"
                )

    # 8e) ReviewRecord target resolution (single + bundle).
    for review in store.by_kind("ReviewRecord"):
        target = review.get("target_object_id")
        if target and not store.has(target):
            problems.append(f"{review['id']}: dangling target_object_id {target}")
        for target_id in review.get("target_object_ids") or []:
            if not store.has(target_id):
                problems.append(f"{review['id']}: dangling target_object_ids {target_id}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest scripts/bb2_brain/tests/test_lint.py -q`
Expected: PASS. Then confirm the existing disk store is still lint-clean (no new false positives — disk has no mappings/decisions yet, and all review targets resolve):

```bash
$PY -c "
from pathlib import Path
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.lint import lint_store
print('PROBLEMS:', lint_store(BrainStore.load(Path('scripts/bb2_brain/brain')), workspace_root=Path('.')))
"
```
Expected: `PROBLEMS: []`

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain/lint.py scripts/bb2_brain/tests/test_lint.py
git commit -m "feat: lint mapping links, review-needed drift, supersession

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Mapping-centered context projection

**Files:**
- Modify: `scripts/bb2_brain/context_projection.py`
- Test: `scripts/bb2_brain/tests/test_context_projection.py`

Depends on Task 1.

- [ ] **Step 1: Write the failing tests**

Add to `class ContextProjectionTest` in `scripts/bb2_brain/tests/test_context_projection.py` a store builder with mappings and tests. Extend the existing `_store` to also write two mappings (one reviewed, one candidate) by adding this new method and tests:

```python
    def _store_with_mappings(self):
        store = self._store()  # reuses context + reviewed race-stage term + candidate dummy-npc term
        # re-load into a writable root so we can add mappings
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        for obj in store.all():
            write_object(root, f"objects/domain/{obj['id']}.json", obj)
        write_object(root, "objects/mappings/naming.json", _base({
            "id": "mapping.sally-canoe.naming", "kind": "DomainMapping", "status": "reviewed",
            "truth_role": "domain", "title": "naming mapping",
            "context_id": "context.sally-canoe", "mapping_key": "naming",
            "canonical_summary": "Canoe Race is the current planning name.",
            "meaning": "Sally Canoe / 샐리의 카누 refer to the Canoe Race event.",
            "boundary": "Naming only.",
            "caveats": ["Spec v8 uses 카누 레이스; planning name may change."],
            "code_locator_ids": ["locator.sally.event-model-cpp-parse"],
            "glossary_term_ids": ["glossary.sally-canoe.race-stage"],
            "decision_record_ids": ["decision.sally-canoe.naming"],
        }))
        write_object(root, "objects/mappings/cooldown.json", _base({
            "id": "mapping.sally-canoe.cooldown", "kind": "DomainMapping", "status": "candidate",
            "truth_role": "domain", "title": "cooldown mapping",
            "context_id": "context.sally-canoe", "mapping_key": "cooldown",
            "canonical_summary": "Cooldown is the repeat-participation wait rule.",
            "meaning": "Wait window before a new race can start.",
            "boundary": "Repeat participation timing only.",
            "glossary_term_ids": ["glossary.sally-canoe.race-stage"],
            "decision_record_ids": ["decision.sally-canoe.cooldown"],
        }))
        return BrainStore.load(root)

    def test_render_includes_reviewed_mapping_excludes_candidate_mapping(self):
        content = render_context_markdown(self._store_with_mappings(), "context.sally-canoe")
        self.assertIn("## Reviewed mappings", content)
        self.assertIn("### naming", content)
        self.assertIn("Canoe Race is the current planning name.", content)
        self.assertIn("Spec v8 uses 카누 레이스", content)        # caveat surfaced
        self.assertIn("locator.sally.event-model-cpp-parse", content)  # code locator surfaced
        self.assertNotIn("### cooldown", content)                 # candidate excluded

    def test_build_projection_source_ids_include_reviewed_mappings(self):
        projection, content = build_context_projection(
            self._store_with_mappings(), "context.sally-canoe",
            output_locator="docs/contexts/generated/sally-canoe/CONTEXT.md",
            generated_at="2026-06-02T00:00:00+09:00", generated_by="test",
        )
        self.assertEqual(projection["source_object_ids"], [
            "context.sally-canoe",
            "glossary.sally-canoe.race-stage",
            "mapping.sally-canoe.naming",
        ])
        self.assertIn("### naming", content)
        self.assertNotIn("### cooldown", content)
```

Add the missing import at the top of the test file:

```python
from scripts.bb2_brain.tests.test_router import write_object
```

(`write_object` is already imported indirectly via the existing `from scripts.bb2_brain.tests.test_router import write_object` at line 11 — confirm it is present; if so, no change needed.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest scripts/bb2_brain/tests/test_context_projection.py -q`
Expected: FAIL — `## Reviewed mappings` / `### naming` not in output; `source_object_ids` does not include the mapping.

- [ ] **Step 3: Implement mapping-centered projection**

In `scripts/bb2_brain/context_projection.py`, add a helper after `_reviewed_terms_for_context`:

```python
def _reviewed_mappings_for_context(store: BrainStore, context_id: str) -> list[dict]:
    mappings = [
        obj for obj in store.by_kind("DomainMapping")
        if obj.get("context_id") == context_id and obj.get("status") == "reviewed"
    ]
    return sorted(mappings, key=lambda mapping: mapping.get("mapping_key", ""))
```

In `render_context_markdown`, after the reviewed-glossary loop and before `return "\n".join(lines).rstrip() + "\n"`, add:

```python
    mappings = _reviewed_mappings_for_context(store, context_id)
    lines.extend(["", "## Reviewed mappings", ""])
    if not mappings:
        lines.append("_No reviewed mappings._")
    for mapping in mappings:
        lines.append(f"### {mapping['mapping_key']}")
        lines.append("")
        lines.append(mapping.get("canonical_summary", ""))
        lines.append("")
        lines.append("Meaning: " + mapping.get("meaning", ""))
        lines.append("")
        lines.append("Boundary: " + mapping.get("boundary", ""))
        non_goals = mapping.get("non_goals") or []
        if non_goals:
            lines.append("")
            lines.append("Non-goals: " + "; ".join(non_goals))
        caveats = mapping.get("caveats") or []
        if caveats:
            lines.append("")
            lines.append("Caveats: " + "; ".join(caveats))
        code_locator_ids = mapping.get("code_locator_ids") or []
        if code_locator_ids:
            lines.append("")
            lines.append("Code locators: " + ", ".join(code_locator_ids))
        projection_notes = mapping.get("projection_notes") or []
        if projection_notes:
            lines.append("")
            lines.append("Projection notes: " + "; ".join(projection_notes))
        lines.append("")
```

In `build_context_projection`, change the source-objects assembly:

```python
    terms = _reviewed_terms_for_context(store, context)
    mappings = _reviewed_mappings_for_context(store, context_id)
    source_objects = [context] + terms + mappings
```

(leave the rest of `build_context_projection` unchanged — `source_object_ids`, hashes, and `content = render_context_markdown(...)` now include mappings automatically.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest scripts/bb2_brain/tests/test_context_projection.py scripts/bb2_brain/tests/test_ingest_sally_canoe_source.py -q`
Expected: PASS — new mapping tests pass; the existing projection tests still pass (their stores have no `DomainMapping`, so `source_object_ids` and absence assertions are unchanged).

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain/context_projection.py scripts/bb2_brain/tests/test_context_projection.py
git commit -m "feat: project reviewed domain mappings into context_md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Sally Canoe mapping bundle fixture

**Files:**
- Create: `scripts/bb2_brain/ingest_sally_canoe_mappings.py`
- Test: `scripts/bb2_brain/tests/test_ingest_sally_canoe_mappings.py`

Depends on Task 1 + Task 3. Reuses Sally source objects from `ingest_sally_canoe_source` so all references resolve.

- [ ] **Step 1: Write the failing tests**

Create `scripts/bb2_brain/tests/test_ingest_sally_canoe_mappings.py`:

```python
import tempfile
import unittest
from pathlib import Path

from scripts.bb2_brain.ingest_sally_canoe_mappings import (
    BUNDLE_KEY,
    MAPPING_IDS,
    build_mapping_objects,
    main as mappings_main,
)
from scripts.bb2_brain.ingest_sally_canoe_source import build_objects as build_source_objects
from scripts.bb2_brain.lint import lint_store
from scripts.bb2_brain.store import BrainStore


class SallyCanoeMappingTest(unittest.TestCase):
    def _source_path(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "spec-v8.md"
        path.write_text("# 카누 레이스\n7명 소규모 레이스\nDUMMY NPC 매칭\n쿨 타임 후 재시작\n", encoding="utf-8")
        return path

    def _combined_store(self, bundle_confirmed: bool) -> BrainStore:
        # race-stage reviewed so projection has a reviewed term too, like disk.
        objects = {o["id"]: o for o in build_source_objects(
            source_path=self._source_path(),
            confirmations={"glossary.sally-canoe.race-stage": True},
        )}
        for obj in build_mapping_objects(bundle_confirmed=bundle_confirmed):
            objects[obj["id"]] = obj
        return BrainStore(objects)

    def test_candidate_bundle_has_four_candidate_mappings_and_lint_clean(self):
        store = self._combined_store(bundle_confirmed=False)
        mappings = store.by_kind("DomainMapping")
        self.assertEqual({m["id"] for m in mappings}, set(MAPPING_IDS))
        self.assertTrue(all(m["status"] == "candidate" for m in mappings))
        self.assertEqual(store.by_kind("ReviewRecord"), [r for r in store.by_kind("ReviewRecord")
                                                         if r.get("review_scope") != "mapping_bundle"])
        self.assertEqual(lint_store(store), [])

    def test_bundle_confirmation_promotes_all_four_with_one_review_record(self):
        store = self._combined_store(bundle_confirmed=True)
        mappings = store.by_kind("DomainMapping")
        self.assertTrue(all(m["status"] == "reviewed" for m in mappings))
        bundles = [r for r in store.by_kind("ReviewRecord") if r.get("review_scope") == "mapping_bundle"]
        self.assertEqual(len(bundles), 1)
        bundle = bundles[0]
        self.assertEqual(bundle["confirmation_key"], BUNDLE_KEY)
        self.assertEqual(set(bundle["target_object_ids"]), set(MAPPING_IDS))
        for mapping in mappings:
            self.assertEqual(mapping["review_record_id"], bundle["id"])
        self.assertEqual(lint_store(store), [])

    def test_mapping_links_multiple_glossary_aliases(self):
        store = self._combined_store(bundle_confirmed=True)
        participant = store.get("mapping.sally-canoe.participant")
        self.assertIn("glossary.sally-canoe.race-participant", participant["glossary_term_ids"])
        self.assertIn("glossary.sally-canoe.dummy-npc", participant["glossary_term_ids"])

    def test_each_mapping_has_initial_decision_incorporated(self):
        """No review-needed false positive: every initial decision is listed by its mapping."""
        store = self._combined_store(bundle_confirmed=True)
        self.assertFalse(any("review needed" in p for p in lint_store(store)))

    def test_main_materializes_bundle_and_regenerates_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            # seed the source slice first so references resolve on disk.
            from scripts.bb2_brain.ingest_sally_canoe_source import main as source_main
            source_main([
                "--brain-root", str(root), "--source-path", str(self._source_path()),
                "--confirm-reviewed", "glossary.sally-canoe.race-stage",
            ])
            output = Path(tmp) / "generated" / "CONTEXT.md"
            rc = mappings_main([
                "--brain-root", str(root), "--confirm-bundle",
                "--export-context", str(output),
                "--generated-at", "2026-06-02T00:00:00+09:00", "--generated-by", "test",
            ])
            self.assertEqual(rc, 0)
            store = BrainStore.load(root)
            self.assertTrue(store.has("mapping.sally-canoe.naming"))
            self.assertTrue(store.has("review.bundle.sally-canoe.domain-mapping"))
            text = output.read_text(encoding="utf-8")
            self.assertIn("## Reviewed mappings", text)
            self.assertIn("### naming", text)
            self.assertEqual(lint_store(store), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest scripts/bb2_brain/tests/test_ingest_sally_canoe_mappings.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.bb2_brain.ingest_sally_canoe_mappings`.

- [ ] **Step 3: Implement the mapping fixture module**

Create `scripts/bb2_brain/ingest_sally_canoe_mappings.py`:

```python
"""Sally Canoe mapping bundle fixture.

Builds DecisionRecord + DomainMapping objects on top of the already-ingested Sally Canoe
source/code evidence (see ingest_sally_canoe_source). The four mappings are promoted together
as one mapping review bundle (spec §6.1, §10) via confirmation_key bundle.sally-canoe.domain-mapping.

Update/supersession fixtures live here too but are test-only: they are NOT written by main(),
because the spec_reflected=no Jira scenario intentionally produces a blocking review-needed
lint problem (spec §8.3).
"""

import argparse
import json
from pathlib import Path

from scripts.bb2_brain.context_projection import build_context_projection
from scripts.bb2_brain.store import BrainStore

BRAIN_ROOT = Path(__file__).parent / "brain"
CONTEXT_ID = "context.sally-canoe"
BUNDLE_KEY = "bundle.sally-canoe.domain-mapping"

SCHEMA_VERSION = "0.1"
T = "2026-06-02T00:00:00+09:00"

MAPPING_IDS = [
    "mapping.sally-canoe.naming",
    "mapping.sally-canoe.race-status",
    "mapping.sally-canoe.participant",
    "mapping.sally-canoe.cooldown",
]


def base(obj: dict) -> dict:
    defaults = {
        "schema_version": SCHEMA_VERSION,
        "poc_priority": "P0",
        "created_at": T,
        "updated_at": T,
        "tags": ["bb2-client", "sally-canoe", "domain-mapping"],
        "evidence_refs": [],
    }
    for key, value in defaults.items():
        obj.setdefault(key, value)
    return obj


def _decision(decision_id, decision_type, summary, decision, mapping_id, *,
              source_object_ids, code_locator_ids=None, spec_reflected="yes") -> dict:
    return base({
        "id": decision_id,
        "kind": "DecisionRecord",
        "status": "reviewed",
        "truth_role": "event",
        "title": summary,
        "decision_type": decision_type,
        "summary": summary,
        "decision": decision,
        "source_object_ids": source_object_ids,
        "affected_context_ids": [CONTEXT_ID],
        "affected_mapping_ids": [mapping_id],
        "spec_reflected": spec_reflected,
        "code_locator_ids": code_locator_ids or [],
    })


def build_mapping_decision_records() -> list[dict]:
    return [
        _decision(
            "decision.sally-canoe.naming", "naming_decision",
            "Canoe Race is the current planning name for the Sally Canoe event.",
            "Canoe Race is canonical; Sally Canoe, Sally Canoe Event, and 샐리의 카누 are aliases.",
            "mapping.sally-canoe.naming",
            source_object_ids=["manifest.sally-canoe-spec-v8", "ref.sally.basic-info"],
        ),
        _decision(
            "decision.sally-canoe.race-status", "implementation_boundary",
            "Domain race status is the server enum; view state is a UI display mapping.",
            "Race status = server SALLY_CANOE_RACE_STATUS; presenter derives READY/RACING/COOLDOWN/ENDED.",
            "mapping.sally-canoe.race-status",
            source_object_ids=["ref.sally.race-state", "ref.sally.code.race-status", "ref.sally.code.view-state"],
            code_locator_ids=["locator.sally.event-model-hpp", "locator.sally.viewdata-state"],
        ),
        _decision(
            "decision.sally-canoe.participant", "implementation_boundary",
            "Participants include the player and server-managed dummy participants.",
            "Server provides racer records; client updates view data and does not simulate dummy behavior.",
            "mapping.sally-canoe.participant",
            source_object_ids=["ref.sally.dummy-npc", "ref.sally.code.race-participant", "ref.sally.code.prev-progress"],
            code_locator_ids=["locator.sally.viewdata-racers", "locator.sally.manager-prev-progress"],
        ),
        _decision(
            "decision.sally-canoe.cooldown", "spec_clarification",
            "Cooldown is the repeat-participation wait rule.",
            "After race result handling, a new race and entry surfaces reappear only after cooldown ends.",
            "mapping.sally-canoe.cooldown",
            source_object_ids=["ref.sally.basic-info", "ref.sally.cooldown", "ref.sally.code.race-status"],
            code_locator_ids=["locator.sally.event-model-hpp"],
        ),
    ]


def _mapping(mapping_id, mapping_key, canonical_summary, meaning, boundary, *,
             glossary_term_ids, decision_id, code_locator_ids, evidence_refs,
             caveats=None, bundle_confirmed=False) -> dict:
    obj = base({
        "id": mapping_id,
        "kind": "DomainMapping",
        "status": "reviewed" if bundle_confirmed else "candidate",
        "truth_role": "domain",
        "title": ("Mapping" if bundle_confirmed else "Candidate mapping") + ": " + mapping_key,
        "context_id": CONTEXT_ID,
        "mapping_key": mapping_key,
        "canonical_summary": canonical_summary,
        "meaning": meaning,
        "boundary": boundary,
        "glossary_term_ids": glossary_term_ids,
        "decision_record_ids": [decision_id],
        "code_locator_ids": code_locator_ids,
        "evidence_refs": evidence_refs,
    })
    if caveats:
        obj["caveats"] = caveats
    if bundle_confirmed:
        obj["review_record_id"] = "review." + BUNDLE_KEY
        obj["review_state"] = {"meaning_reviewed": True, "evidence_reviewed": True, "projection_reviewed": True}
    return obj


def build_mappings(bundle_confirmed: bool = False) -> list[dict]:
    return [
        _mapping(
            "mapping.sally-canoe.naming", "naming",
            "Canoe Race is the current planning name for the Sally Canoe event.",
            "When the user says Sally Canoe, Sally Canoe Event, or 샐리의 카누 they mean the Canoe Race event.",
            "Naming and aliases only; race rules are covered by the other mappings.",
            glossary_term_ids=["glossary.sally-canoe.canoe-race"],
            decision_id="decision.sally-canoe.naming",
            code_locator_ids=["locator.sally.event-model-cpp-parse"],
            evidence_refs=["ref.sally.basic-info", "ref.sally.code.payload"],
            bundle_confirmed=bundle_confirmed,
        ),
        _mapping(
            "mapping.sally-canoe.race-status", "race-status",
            "Domain race status is the server SALLY_CANOE_RACE_STATUS enum.",
            "Race status is the server enum (IDLE/RACING/RACE_END/COOLTIME/FINISHED); the presenter maps it "
            "to READY/RACING/COOLDOWN/ENDED view states.",
            "Server status is the domain truth; view state is a derived UI display mapping.",
            glossary_term_ids=["glossary.sally-canoe.race-state"],
            decision_id="decision.sally-canoe.race-status",
            code_locator_ids=["locator.sally.event-model-hpp", "locator.sally.viewdata-state"],
            evidence_refs=["ref.sally.race-state", "ref.sally.code.race-status", "ref.sally.code.view-state"],
            bundle_confirmed=bundle_confirmed,
        ),
        _mapping(
            "mapping.sally-canoe.participant", "participant",
            "Race participants include the player and server-managed dummy participants.",
            "The seven-person race shows the player plus dummy NPC participants; the client renders view data "
            "from server-provided racer records and does not simulate dummy progress.",
            "View data conversion only; matching/dummy generation is server-managed.",
            glossary_term_ids=["glossary.sally-canoe.race-participant", "glossary.sally-canoe.dummy-npc"],
            decision_id="decision.sally-canoe.participant",
            code_locator_ids=["locator.sally.viewdata-racers", "locator.sally.manager-prev-progress"],
            evidence_refs=["ref.sally.dummy-npc", "ref.sally.code.race-participant", "ref.sally.code.prev-progress"],
            bundle_confirmed=bundle_confirmed,
        ),
        _mapping(
            "mapping.sally-canoe.cooldown", "cooldown",
            "Cooldown is the repeat-participation wait rule.",
            "After race result handling, a new race can start and entry surfaces reappear only after the cooldown ends.",
            "Repeat-participation timing only; reward tables are out of scope.",
            glossary_term_ids=["glossary.sally-canoe.cooldown"],
            decision_id="decision.sally-canoe.cooldown",
            code_locator_ids=["locator.sally.event-model-hpp"],
            evidence_refs=["ref.sally.basic-info", "ref.sally.cooldown", "ref.sally.code.race-status"],
            bundle_confirmed=bundle_confirmed,
        ),
    ]


def build_bundle_review() -> dict:
    return base({
        "id": "review." + BUNDLE_KEY,
        "kind": "ReviewRecord",
        "status": "reviewed",
        "truth_role": "review",
        "title": "검수 기록: Sally Canoe mapping bundle",
        "reviewer": "user-confirmed",
        "reviewed_at": T,
        "verdict": "approved",
        "review_type": "meaning_review",
        "review_scope": "mapping_bundle",
        "bundle_key": BUNDLE_KEY,
        "confirmation_key": BUNDLE_KEY,
        "target_object_ids": list(MAPPING_IDS),
        "evidence_refs": ["ref.sally.basic-info", "ref.sally.race-state", "ref.sally.cooldown"],
    })


def build_mapping_objects(*, bundle_confirmed: bool = False) -> list[dict]:
    objects = build_mapping_decision_records() + build_mappings(bundle_confirmed=bundle_confirmed)
    if bundle_confirmed:
        objects.append(build_bundle_review())
    return objects


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brain-root", default=str(BRAIN_ROOT))
    parser.add_argument("--confirm-bundle", action="store_true")
    parser.add_argument("--export-context")
    parser.add_argument("--generated-at", default=T)
    parser.add_argument("--generated-by", default="scripts.bb2_brain.ingest_sally_canoe_mappings")
    args = parser.parse_args(argv)

    brain_root = Path(args.brain_root)
    for obj in build_mapping_objects(bundle_confirmed=args.confirm_bundle):
        BrainStore.save_object(brain_root, obj)

    output = None
    if args.export_context:
        store = BrainStore.load(brain_root)
        projection, content = build_context_projection(
            store, CONTEXT_ID,
            output_locator=args.export_context,
            generated_at=args.generated_at,
            generated_by=args.generated_by,
        )
        output_path = Path(args.export_context)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        BrainStore.save_object(brain_root, projection)
        output = projection
    print(json.dumps({"saved": True, "projection": output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Note: when `--export-context` writes to the real `docs/contexts/generated/sally-canoe/CONTEXT.md`, the projection's `output_locator` must be the workspace-relative path so lint with `workspace_root` resolves it. Pass the repo-relative path in Task 6.

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest scripts/bb2_brain/tests/test_ingest_sally_canoe_mappings.py -q`
Expected: PASS (all 5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain/ingest_sally_canoe_mappings.py scripts/bb2_brain/tests/test_ingest_sally_canoe_mappings.py
git commit -m "feat: add Sally Canoe mapping bundle fixture

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Update-ingest drift + supersession tests

**Files:**
- Modify: `scripts/bb2_brain/ingest_sally_canoe_mappings.py` (add test-only fixture builders)
- Test: `scripts/bb2_brain/tests/test_ingest_sally_canoe_mappings.py`

Depends on Task 4 + Task 2.

- [ ] **Step 1: Write the failing tests**

Append to `class SallyCanoeMappingTest` in `scripts/bb2_brain/tests/test_ingest_sally_canoe_mappings.py`:

```python
    def test_jira_decision_not_reflected_marks_only_that_mapping_review_needed(self):
        from scripts.bb2_brain.ingest_sally_canoe_mappings import build_jira_update_objects
        objects = {o["id"]: o for o in build_source_objects(
            source_path=self._source_path(),
            confirmations={"glossary.sally-canoe.race-stage": True},
        )}
        for obj in build_mapping_objects(bundle_confirmed=True):
            objects[obj["id"]] = obj
        for obj in build_jira_update_objects():
            objects[obj["id"]] = obj
        problems = lint_store(BrainStore(objects))
        review_needed = [p for p in problems if "review needed" in p]
        self.assertTrue(any("mapping.sally-canoe.race-status" in p
                            and "decision.sally-canoe.race-status-v2" in p
                            and "spec_reflected=no" in p for p in review_needed))
        self.assertEqual(len(review_needed), 1)  # bundle is NOT rolled back; only one mapping flagged

    def test_supersession_resolves_review_needed(self):
        from scripts.bb2_brain.ingest_sally_canoe_mappings import (
            build_jira_update_objects, build_supersession_objects,
        )
        objects = {o["id"]: o for o in build_source_objects(
            source_path=self._source_path(),
            confirmations={"glossary.sally-canoe.race-stage": True},
        )}
        for obj in build_mapping_objects(bundle_confirmed=True):
            objects[obj["id"]] = obj
        for obj in build_jira_update_objects():
            objects[obj["id"]] = obj
        for obj in build_supersession_objects():  # marks old mapping superseded + adds v2 + supersession review
            objects[obj["id"]] = obj
        store = BrainStore(objects)
        self.assertTrue(store.has("review.sally-canoe.race-status-v2"))
        self.assertEqual(store.get("review.sally-canoe.race-status-v2")["review_type"], "supersession_review")
        problems = lint_store(store)
        self.assertFalse(any("review needed" in p for p in problems))
        self.assertFalse(any("superseded by" in p for p in problems))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `$PY -m pytest scripts/bb2_brain/tests/test_ingest_sally_canoe_mappings.py -q -k "jira or supersession"`
Expected: FAIL — `ImportError: cannot import name 'build_jira_update_objects'`.

- [ ] **Step 3: Implement the update + supersession fixture builders**

Append to `scripts/bb2_brain/ingest_sally_canoe_mappings.py` (after `build_mapping_objects`, before `main`):

```python
def build_jira_update_objects() -> list[dict]:
    """A later Jira improvement decision that is NOT reflected in the spec and affects the
    reviewed race-status mapping. Test-only: this intentionally produces a blocking review-needed
    lint problem for mapping.sally-canoe.race-status (spec §8.3). Not written by main()."""
    return [
        base({
            "id": "manifest.sally-canoe-jira-race-status",
            "kind": "EvidenceManifest",
            "status": "reviewed",
            "truth_role": "source",
            "title": "Jira 개선 티켓: race status 표시 변경",
            "source_type": "jira",
            "locator": "LGBBTWO-9001",
            "captured_at": T,
            "captured_by": "manual",
            "sensitivity": "internal",
            "acl": ["bb2-client-team"],
            "redaction_status": "approved",
        }),
        base({
            "id": "ref.sally.jira.race-status",
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "title": "Jira comment: race status display change",
            "evidence_manifest_id": "manifest.sally-canoe-jira-race-status",
            "ref_type": "jira_comment",
            "locator": {"issue": "LGBBTWO-9001"},
            "summary": "Improvement: COOLTIME should display a distinct waiting view, spec not yet updated.",
        }),
        base({
            "id": "decision.sally-canoe.race-status-v2",
            "kind": "DecisionRecord",
            "status": "reviewed",
            "truth_role": "event",
            "title": "race status v2 개선 결정 (기획서 미반영)",
            "decision_type": "improvement",
            "summary": "COOLTIME gains a distinct waiting view; spec update is pending.",
            "decision": "Add a distinct COOLTIME waiting view state; spec revision not yet made.",
            "source_object_ids": ["manifest.sally-canoe-jira-race-status", "ref.sally.jira.race-status"],
            "affected_context_ids": [CONTEXT_ID],
            "affected_mapping_ids": ["mapping.sally-canoe.race-status"],
            "spec_reflected": "no",
            "jira_issue_ids": ["manifest.sally-canoe-jira-race-status"],
        }),
    ]


def build_supersession_objects() -> list[dict]:
    """Resolve the race-status-v2 decision by superseding the old mapping with a v2 mapping that
    incorporates it. Test-only. Marks the old mapping superseded (so lint 8d is satisfied) and the
    new mapping incorporates decision.sally-canoe.race-status-v2 (so lint 8c clears)."""
    superseded_old = base({
        "id": "mapping.sally-canoe.race-status",
        "kind": "DomainMapping",
        "status": "superseded",
        "truth_role": "domain",
        "title": "Mapping: race-status (superseded)",
        "context_id": CONTEXT_ID,
        "mapping_key": "race-status",
        "canonical_summary": "Domain race status is the server SALLY_CANOE_RACE_STATUS enum.",
        "meaning": "Superseded by race-status v2.",
        "boundary": "Server status is the domain truth.",
        "glossary_term_ids": ["glossary.sally-canoe.race-state"],
        "decision_record_ids": ["decision.sally-canoe.race-status"],
        "code_locator_ids": ["locator.sally.event-model-hpp", "locator.sally.viewdata-state"],
        "evidence_refs": ["ref.sally.race-state", "ref.sally.code.race-status"],
        "review_record_id": "review." + BUNDLE_KEY,
    })
    new_v2 = base({
        "id": "mapping.sally-canoe.race-status-v2",
        "kind": "DomainMapping",
        "status": "reviewed",
        "truth_role": "domain",
        "title": "Mapping: race-status v2",
        "context_id": CONTEXT_ID,
        "mapping_key": "race-status",
        "canonical_summary": "Race status with a distinct COOLTIME waiting view.",
        "meaning": "Server enum still drives status; COOLTIME now maps to a distinct waiting view state.",
        "boundary": "Server status is the domain truth; adds COOLTIME waiting view per Jira improvement.",
        "glossary_term_ids": ["glossary.sally-canoe.race-state"],
        "decision_record_ids": ["decision.sally-canoe.race-status", "decision.sally-canoe.race-status-v2"],
        "code_locator_ids": ["locator.sally.event-model-hpp", "locator.sally.viewdata-state"],
        "evidence_refs": ["ref.sally.race-state", "ref.sally.code.view-state"],
        "supersedes_mapping_ids": ["mapping.sally-canoe.race-status"],
        "caveats": ["Spec revision pending; Jira LGBBTWO-9001 decision is newer than the spec."],
        "review_state": {"meaning_reviewed": True, "evidence_reviewed": True, "projection_reviewed": True},
        "review_record_id": "review.sally-canoe.race-status-v2",
    })
    supersession_review = base({
        "id": "review.sally-canoe.race-status-v2",
        "kind": "ReviewRecord",
        "status": "reviewed",
        "truth_role": "review",
        "title": "검수 기록: race-status v2 supersession",
        "reviewer": "user-confirmed",
        "reviewed_at": T,
        "verdict": "approved",
        "review_type": "supersession_review",
        "review_scope": "single_object",
        "target_object_id": "mapping.sally-canoe.race-status-v2",
        "evidence_refs": [],
    })
    return [superseded_old, new_v2, supersession_review]
```

Note: the v2 mapping gets its OWN `supersession_review` record — it must not borrow the bundle review's `review_record_id`, because the bundle (`target_object_ids` = the original 4) never approved v2. The old mapping keeps its bundle `review_record_id` (it *was* bundle-approved before being superseded). `supersession_review` is a `review_type` value, not a `review_state` key — it must never appear inside `review_state` (the only valid keys are `meaning_reviewed`, `evidence_reviewed`, `implementation_reviewed`, `projection_reviewed`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `$PY -m pytest scripts/bb2_brain/tests/test_ingest_sally_canoe_mappings.py -q`
Expected: PASS (all tests, including the two update tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain/ingest_sally_canoe_mappings.py scripts/bb2_brain/tests/test_ingest_sally_canoe_mappings.py
git commit -m "test: cover Jira-not-reflected drift and mapping supersession

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Materialize the Sally Canoe mapping bundle on disk

**Files:**
- Create (via CLI): `scripts/bb2_brain/brain/objects/decisions/*.json`, `scripts/bb2_brain/brain/objects/mappings/*.json`, `scripts/bb2_brain/brain/objects/reviews/review.bundle.sally-canoe.domain-mapping.json`
- Modify (via CLI): `scripts/bb2_brain/brain/indexes/context_projections/projection.sally-canoe.context-md.json`, `docs/contexts/generated/sally-canoe/CONTEXT.md`

Depends on all prior tasks. No new code — this runs the Task 4 CLI against the real brain and verifies the whole store.

- [ ] **Step 1: Run the mapping bundle ingest against the real brain**

```bash
PY=/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python
$PY -m scripts.bb2_brain.ingest_sally_canoe_mappings \
  --brain-root scripts/bb2_brain/brain \
  --confirm-bundle \
  --export-context docs/contexts/generated/sally-canoe/CONTEXT.md \
  --generated-at "2026-06-02T00:00:00+09:00" \
  --generated-by "scripts.bb2_brain.ingest_sally_canoe_mappings"
```
Expected: prints `{"saved": true, "projection": {...}}`.

- [ ] **Step 2: Verify the disk store is lint-clean (with workspace_root)**

```bash
$PY -c "
from pathlib import Path
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.lint import lint_store
store = BrainStore.load(Path('scripts/bb2_brain/brain'))
problems = lint_store(store, workspace_root=Path('.'))
print('OBJECTS:', len(store.all()))
print('MAPPINGS:', sorted(m['id'] for m in store.by_kind('DomainMapping')))
print('DECISIONS:', sorted(d['id'] for d in store.by_kind('DecisionRecord')))
print('PROBLEMS:', problems)
"
```
Expected: `OBJECTS: 92`, 4 mappings, 4 decisions, `PROBLEMS: []`.

- [ ] **Step 3: Verify the regenerated CONTEXT.md includes the reviewed mappings**

```bash
grep -c "### naming\|### race-status\|### participant\|### cooldown" docs/contexts/generated/sally-canoe/CONTEXT.md
```
Expected: `4`.

- [ ] **Step 4: Run the full test suite**

Run: `$PY -m pytest scripts/bb2_brain/tests -q`
Expected: PASS — all prior 123 tests plus the new schema/lint/projection/mapping tests.

- [ ] **Step 5: Commit the materialized data**

```bash
git add scripts/bb2_brain/brain/objects/decisions scripts/bb2_brain/brain/objects/mappings \
        scripts/bb2_brain/brain/objects/reviews/review.bundle.sally-canoe.domain-mapping.json \
        scripts/bb2_brain/brain/indexes/context_projections/projection.sally-canoe.context-md.json \
        docs/contexts/generated/sally-canoe/CONTEXT.md
git commit -m "data: ingest Sally Canoe mapping bundle into Brain

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (against spec `4298f486f2`)

**Spec coverage:**
- §5.1 DecisionRecord schema → Task 1.
- §5.2 DomainMapping schema → Task 1.
- §6 ReviewRecord.review_type → Task 1.
- §6.1 mapping review bundle (review_scope/bundle_key/confirmation_key/target_object_ids; no new kind) → Task 1 (schema) + Task 4 (bundle promotion) + Task 6 (materialize).
- §8.3 drift detection (review-needed for unincorporated decision; blocking; mapping-specific) → Task 2 (8c) + Task 5 (Jira test).
- §8.3 supersession → Task 2 (8d) + Task 5 (supersession test).
- §9 mapping-centered projection (meaning/boundary/caveats/code locators/source ids+hash) → Task 3.
- §10 Sally Canoe 4 mappings via bundle.sally-canoe.domain-mapping → Task 4 + Task 6.
- §12.1 store/lint/project mappings → Tasks 1–3, 6.
- §12.2 DecisionRecord cites spec/Jira/Slack/code + spec_reflected → Task 4 (spec/code), Task 5 (Jira).
- §12.3 one mapping ↔ multiple glossary aliases → Task 4 (participant mapping test).
- §12.4 projection includes reviewed, excludes candidate → Task 3 test.
- §12.5 unincorporated affected decision → review-needed lint or resolved by supersession → Task 5.
- §12.6 bundle promotes multiple mappings with one confirmation → Task 4.
- §12.7 Sally Canoe via bundle without per-item approval → Task 4 + Task 6.
- §12.8 superseding mapping reviewed by separate `supersession_review`, not the bundle review → Task 5.
- §12.9 materialized store + projection lint-clean end-to-end; renderer-only unit tests may use partial fixtures, lint cleanliness proven by integration/materialization → Task 4 (`test_main_materializes_bundle...`) + Task 6.

**Deferred (noted, not implemented):**
- Router `glossary_meaning` integration to include reviewed `DomainMapping` (spec §7) — out of the user's stated scope; follow-up.
- Generic ingest automation (spec §13.7) — explicitly deferred by the spec until the mapping lifecycle is proven.
- "Reviewed glossary term has no mapping for projection use" lint bullet (spec §8.3) — **not implemented, even in a `context_id == context.sally-canoe`-scoped form.** Rationale: the spec intends this as a global projection-coverage guard; a half-scoped version gives false confidence while still needing the same follow-up, and the existing stage-clear-token reviewed terms (which have no mappings) would force either lint noise or special-casing on the current clean baseline. Tracked as a follow-up, not silently dropped.
- SpecRevision evidence for Sally Canoe (none on disk — mappings use code locators + evidence refs; `spec_revision_ids` omitted).

## Review dispositions (bb2-brain review, 2026-06-02)

bb2-brain (GPT-5.5) reviewed this plan against the spec and the actual code. The overall direction and the flagged decisions (review-needed is not a status; single `ReviewRecord` bundle; `objects/mappings` + `objects/decisions`; Jira scenario test-only; router/generic-ingest exclusions) were confirmed correct. Five issues were raised; dispositions:

1. **lint 8c stays incorporation-based, not wall-clock — clarified, timestamp suggestion declined.** Suggestion was to gate on `decision.created_at > mapping.updated_at`. Declined: all fixtures share one timestamp, so the Jira update decision's `created_at` is *not* greater than the mapping's `updated_at` — a timestamp gate would break the very `test_jira_decision_not_reflected...` it should support, and would miss old-but-unincorporated decisions (false negative). The precise drift signal is "a decision affects a reviewed mapping the mapping does not list and that is not superseded"; by update-ingest arrival order that decision *is* the newer one. bb2-brain agreed; spec `4298f486f2` codified this (incorporation-based, not wall-clock) and changed the §8.3 example message to "unincorporated decision …". The lint 8c message and the test name (`test_unincorporated_decision_…`) match that wording.
2. **v2 supersession gets its own `supersession_review` ReviewRecord — accepted.** `build_supersession_objects` now creates `review.sally-canoe.race-status-v2` and the v2 mapping points to it, not the bundle review. The bundle review keeps its original 4 targets; the old mapping keeps its bundle `review_record_id` (it was bundle-approved before being superseded). The Task 5 test asserts the supersession review exists with `review_type == "supersession_review"`.
3. **Bundle `review_state` adds `evidence_reviewed` — accepted.** Per spec §6.1 a bundle confirms meaning + evidence boundary + code/spec relationship, so bundle-promoted mappings carry `{meaning_reviewed, evidence_reviewed, projection_reviewed}`. `implementation_reviewed` is intentionally omitted so future per-mapping code drift (lint 8c / HEAD checks) can demand a separate implementation review rather than falsely claiming code was re-verified at bundle time.
4. **"Reviewed glossary term has no mapping" lint — deferred with explicit rationale** (see Deferred list above).
5. **Projection unit-test fixture stays rendering-only — declined with evidence.** The Task 3 fixture's dangling `decision_record_ids`/`code_locator_ids` match the existing pattern: the current `test_context_projection.py` fixture already gives `glossary.sally-canoe.race-stage` an `evidence_refs=["ref.sally.basic-info"]` not present in the fixture, and projection unit tests deliberately never call `lint_store`. The "projection consumes lint-clean objects" guarantee is verified where it belongs — `test_main_materializes_bundle...` (Task 4) and Task 6 both assert `lint_store(store) == []` on the real store. Partially backfilling the unit fixture would not make it lint-clean (race-stage's ref would still dangle) and would mean rewriting the existing fixture for no added safety.

**Type/name consistency:** `BUNDLE_KEY` / `MAPPING_IDS` exported from the mappings module and referenced by tests; bundle review id is `review.` + `BUNDLE_KEY` everywhere; lint problem strings (`"review needed"`, `"superseded by"`, `"dangling decision_record_ids"`) match between `lint.py` and the lint tests; `review_state` keys never include `supersession_review` (that is a `review_type`).
