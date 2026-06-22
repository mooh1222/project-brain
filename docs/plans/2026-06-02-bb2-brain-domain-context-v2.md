# BB2 Brain Domain Context v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Brain-first domain context v2 migration so `DomainContext`/`GlossaryTerm` are canonical Brain objects, generated `CONTEXT.md` is a disposable projection, and the Sally Canoe lifecycle/state spine proves the end-to-end path.

**Architecture:** The implementation updates the repo specs first, then tightens Python object validation, lint, export/projection generation, and seed data. Existing stage-clear-token data is migrated away from `CONTEXT.md`-first assumptions, then a separate Sally Canoe seed script creates the v2 acceptance slice and exports a generated context adapter from reviewed vocabulary only.

**Tech Stack:** Python 3.11, `unittest`, per-file JSON Brain store under `scripts/bb2_brain/brain/`, Markdown specs/plans, generated Markdown context adapter.

---

## Scope Check

This plan intentionally stays one implementation slice because the pieces are coupled by one invariant: **Brain objects are the domain vocabulary source of truth, and generated files are projections.** Splitting docs, schema, lint, projection, and seed migration would allow old `CONTEXT.md`-first data to pass in between tasks.

Out of scope:

- Direct Brain prompt injection transport.
- Full Slack/Jira/code connector automation.
- A new `DomainTermProposal` object.
- Migrating every existing context file.
- Rewriting the `domain-context-writer` skill.

---

## File Structure

- **Modify** `docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md` — replace old file/path `DomainContext` contract with v2 namespace fields, add `ContextProjection`, update acceptance text.
- **Modify** `docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md` — remove deterministic "context glossary terms" source wording and state Brain vocabulary/raw evidence policy.
- **Modify** `docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md` — remove `docs/contexts/stage-clear-token/CONTEXT.md` dependency and describe Brain-object glossary preflight.
- **Modify** `scripts/bb2_brain/schema.py` — add truth-role enum/kind guards, v2 domain schema, candidate metadata checks, `ContextProjection`, and `IndexRecord`.
- **Modify** `scripts/bb2_brain/store.py` — add save directories for `ContextProjection` and `IndexRecord`.
- **Modify** `scripts/bb2_brain/lint.py` — add domain-context lint rules and optional generated-file hash checks.
- **Create** `scripts/bb2_brain/context_projection.py` — render generated context markdown and build `ContextProjection` objects.
- **Modify** `scripts/bb2_brain/cli.py` — add `--export-context` path while preserving existing query usage.
- **Modify** `scripts/bb2_brain/seed_first_slice.py` — migrate existing stage-clear-token domain objects and review records to v2 truth roles/fields.
- **Create** `scripts/bb2_brain/seed_sally_canoe_domain_v2.py` — add Sally Canoe `DomainContext`, five lifecycle/state terms, and evidence refs.
- **Modify/Create Tests**:
  - `scripts/bb2_brain/tests/test_schema.py`
  - `scripts/bb2_brain/tests/test_store.py`
  - `scripts/bb2_brain/tests/test_lint.py`
  - `scripts/bb2_brain/tests/test_context_projection.py`
  - `scripts/bb2_brain/tests/test_seed_first_slice.py`
  - `scripts/bb2_brain/tests/test_seed_sally_canoe_domain_v2.py`
- **Generated output** `docs/contexts/generated/sally-canoe/CONTEXT.md` — disposable adapter generated from Brain reviewed glossary.

---

## Task 1: Spec migration from `CONTEXT.md` source to Brain object source

**Files:**

- Modify: `docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md:554-592,646-674`
- Modify: `docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md:148-166`
- Modify: `docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md:1-10,303-315`
- Reference: `docs/superpowers/specs/2026-06-02-bb2-brain-domain-context-v2-design.md`

- [ ] **Step 1: Confirm current legacy references**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
rg -n "docs/contexts/stage-clear-token/CONTEXT.md|context glossary terms|source_format: \"mattpocock-context-md\"|path: string;" docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md
```

Expected: matches in object-model §11/§14, storage §6, and query-routing frontmatter/acceptance.

- [ ] **Step 2: Replace object-model §11 with v2 contract**

In `docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md`, replace §11 with:

```markdown
## 11. Domain context objects

### 11.1 DomainContext

**쉬운 설명**: Brain 안의 도메인 용어 네임스페이스와 경계다. `CONTEXT.md` 파일 경로가 아니라 reviewed `GlossaryTerm` 묶음의 소유자다.

```ts
interface DomainContext extends BrainObjectBase {
  kind: "DomainContext";
  truth_role: "domain";
  poc_priority: "P0";

  context_key: string;
  project_id: string;
  display_name: string;

  parent_context_id?: ObjectId;
  child_context_ids?: ObjectId[];

  boundary_summary: string;
  in_scope: string[];
  out_of_scope: string[];

  injection_profile: {
    default_audience: "coding-agent" | "planner" | "reviewer" | "search-router";
    max_terms?: number;
    include_candidates?: boolean;
  };

  export_targets?: {
    format: "context_md" | "prompt_payload";
    locator?: string;
  }[];

  glossary_term_ids: ObjectId[];
}
```

### 11.2 GlossaryTerm

**쉬운 설명**: Brain-native ubiquitous language의 한 단어다. 후보도 같은 객체를 쓰되, reviewed로 승격되기 전에는 agent-facing context export에 들어가지 않는다.

```ts
interface GlossaryTerm extends BrainObjectBase {
  kind: "GlossaryTerm";
  truth_role: "domain";
  poc_priority: "P0";

  context_id: ObjectId;
  term: string;
  definition: string;

  avoid?: string[];
  synonyms?: string[];
  scope_hint?: { feature?: string; surface?: string; release?: string };

  related_terms?: ObjectId[];
  related_objects?: ObjectId[];

  candidate?: {
    candidate_state:
      | "observed"
      | "evidence_verified"
      | "needs_user_confirmation"
      | "conflict"
      | "ready_for_review";
    candidate_source:
      | "spec"
      | "code"
      | "session"
      | "slack"
      | "jira"
      | "legacy_context"
      | "legacy_wiki"
      | "manual";
    open_questions?: string[];
    conflicts_with?: ObjectId[];
    promotion_criteria?: string[];
  };

  rejection?: {
    rejection_reason: string;
    canonical_replacement_id?: ObjectId;
  };
}
```

### 11.3 ContextProjection

**쉬운 설명**: Brain vocabulary에서 만든 disposable export metadata다. generated `CONTEXT.md`나 prompt payload를 추적하지만, evidence나 source of truth가 아니다.

```ts
interface ContextProjection extends BrainObjectBase {
  kind: "ContextProjection";
  truth_role: "index";
  poc_priority: "P0";

  context_id: ObjectId;
  format: "context_md" | "prompt_payload";
  output_locator?: string;

  source_object_ids: ObjectId[];
  source_content_hash: string;
  projection_hash: string;
  generated_at: ISODateTime;
  generated_by: string;

  stale_policy: "fail_on_manual_edit";
  manual_edit_detected?: boolean;
}
```

불변조건:

- `DomainContext`는 `path` / `source_format`을 canonical field로 사용하지 않는다.
- `GlossaryTerm(status="candidate")`는 `candidate` metadata를 가져야 한다.
- `GlossaryTerm(status="reviewed")`는 unresolved `open_questions` 또는 `candidate_state="conflict"`를 가질 수 없다.
- Reviewed term은 agent-facing context export에 들어갈 수 있다.
- Candidate term은 review queue, diagnostics, explicit candidate view에만 들어간다.
- `ContextProjection`은 삭제 후 재생성 가능해야 하며 evidence로 인용하지 않는다.
- generated `CONTEXT.md` 수동 편집은 P0에서 lint 실패다.
- `scope_hint`의 feature/surface/release 값은 동일 차원의 `TemporalFact.scope` 값과 같은 ASCII canonical 식별자여야 한다.
```

- [ ] **Step 3: Update object-model §14 acceptance text**

Replace the line:

```markdown
용어 사전 기준: `docs/contexts/stage-clear-token/CONTEXT.md`
```

with:

```markdown
용어 사전 기준: Brain reviewed `DomainContext(context_key="stage-clear-token")` + reviewed `GlossaryTerm` objects. Existing `docs/contexts/stage-clear-token/CONTEXT.md` is legacy migration hint only and cannot be sole evidence for reviewed terms.
```

Replace the first acceptance step:

```markdown
1. `GlossaryTerm`에서 “입장팝업”, “이벤트 클러스터”, “해피블록”, “요정의 선물” 용어를 확인한다.
```

with:

```markdown
1. Brain `DomainContext`에서 도메인 경계를 확인하고, reviewed `GlossaryTerm`에서 “입장팝업”, “이벤트 클러스터”, “해피블록”, “요정의 선물” 용어를 확인한다. Candidate terms are visible only in review/diagnostic surfaces.
```

- [ ] **Step 4: Update storage ingest wording**

In `docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md`, replace:

```markdown
- Deterministic extraction is preferred when source structure is stable, such as markdown headings, Jira keys, PR numbers, code locators, and context glossary terms.
```

with:

```markdown
- Deterministic extraction is preferred when source structure is stable, such as markdown headings, Jira keys, PR numbers, code locators, and Brain reviewed vocabulary objects.
- Existing context/wiki pages can seed candidates as legacy migration hints, but reviewed vocabulary promotion must cite primary spec/session/code/Slack/Jira evidence.
```

- [ ] **Step 5: Update query-routing dependency and preflight**

In frontmatter, remove:

```yaml
  - docs/contexts/stage-clear-token/CONTEXT.md
```

In §14 expected route, replace steps 1-2 with:

```markdown
1. Preflight Brain glossary objects:
   - Load matching `DomainContext(context_key="stage-clear-token")`.
   - Load reviewed `GlossaryTerm` objects for `입장팝업`, `이벤트 클러스터`, `스테이지 클리어 토큰`, and `컨티뉴 팝업` when direct token-usable UI surfaces are relevant.
   - Do not read glossary terms from `docs/contexts/stage-clear-token/CONTEXT.md`.
2. Treat `요정의 선물` and `해피블록` as event display candidates in this slice, not as standalone main contexts.
```

- [ ] **Step 6: Verify legacy source wording is gone from active spec paths**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
rg -n "Preflight glossary terms from `docs/contexts|source_format: \"mattpocock-context-md\"|context glossary terms|용어 사전 기준: `docs/contexts" docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md
```

Expected: no matches.

- [ ] **Step 7: Commit**

```bash
git add -f docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md
git commit -m "docs: migrate BB2 Brain specs to domain context v2" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 2: Schema/store support for v2 domain objects

**Files:**

- Modify: `scripts/bb2_brain/schema.py`
- Modify: `scripts/bb2_brain/store.py`
- Modify: `scripts/bb2_brain/tests/test_schema.py`
- Modify: `scripts/bb2_brain/tests/test_store.py`

- [ ] **Step 1: Add failing schema tests**

Append these helpers/tests to `scripts/bb2_brain/tests/test_schema.py` inside `SchemaTest`:

```python
    def _domain_context(self, **over):
        obj = {
            "id": "context.sally-canoe", "kind": "DomainContext", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "domain",
            "title": "Sally Canoe", "created_at": "2026-06-02T00:00:00+09:00",
            "updated_at": "2026-06-02T00:00:00+09:00", "tags": ["bb2-client"], "evidence_refs": [],
            "context_key": "sally-canoe", "project_id": "bb2-client", "display_name": "Sally Canoe",
            "boundary_summary": "Sally Canoe lifecycle/state vocabulary.",
            "in_scope": ["Lifecycle and race state terms."],
            "out_of_scope": ["UI layout details."],
            "injection_profile": {"default_audience": "coding-agent", "include_candidates": False},
            "export_targets": [{"format": "context_md", "locator": "docs/contexts/generated/sally-canoe/CONTEXT.md"}],
            "glossary_term_ids": ["glossary.sally-canoe.race-stage"],
        }
        obj.update(over)
        return obj

    def _glossary_term(self, **over):
        obj = {
            "id": "glossary.sally-canoe.race-stage", "kind": "GlossaryTerm", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "domain",
            "title": "Race Stage", "created_at": "2026-06-02T00:00:00+09:00",
            "updated_at": "2026-06-02T00:00:00+09:00", "tags": ["bb2-client"], "evidence_refs": ["ref.sally.basic-info"],
            "context_id": "context.sally-canoe", "term": "Race Stage",
            "definition": "A 1-3 stage progression spine that changes required clear count and reward.",
            "scope_hint": {"feature": "sally-canoe", "release": "5.5"},
        }
        obj.update(over)
        return obj

    def _projection(self, **over):
        obj = {
            "id": "projection.sally-canoe.context-md", "kind": "ContextProjection", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "index",
            "title": "Generated Sally Canoe CONTEXT.md", "created_at": "2026-06-02T00:00:00+09:00",
            "updated_at": "2026-06-02T00:00:00+09:00", "tags": ["bb2-client"], "evidence_refs": [],
            "context_id": "context.sally-canoe", "format": "context_md",
            "output_locator": "docs/contexts/generated/sally-canoe/CONTEXT.md",
            "source_object_ids": ["context.sally-canoe", "glossary.sally-canoe.race-stage"],
            "source_content_hash": "abc123", "projection_hash": "def456",
            "generated_at": "2026-06-02T00:00:00+09:00", "generated_by": "seed_sally_canoe_domain_v2",
            "stale_policy": "fail_on_manual_edit",
        }
        obj.update(over)
        return obj

    def test_domain_context_v2_valid(self):
        self.assertEqual(validate_object(self._domain_context()), [])

    def test_domain_context_rejects_legacy_path_source_format(self):
        errors = validate_object(self._domain_context(path="docs/contexts/sally-canoe", source_format="mattpocock-context-md"))
        self.assertTrue(any("legacy field" in e and "path" in e for e in errors))
        self.assertTrue(any("legacy field" in e and "source_format" in e for e in errors))

    def test_domain_truth_role_reference_rejected(self):
        errors = validate_object(self._domain_context(truth_role="reference"))
        self.assertTrue(any("invalid truth_role" in e and "DomainContext" in e for e in errors))

    def test_review_record_truth_role_must_be_review(self):
        review = {
            "id": "review.x", "kind": "ReviewRecord", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "reference",
            "title": "review", "created_at": "2026-06-02T00:00:00+09:00",
            "updated_at": "2026-06-02T00:00:00+09:00", "tags": [], "evidence_refs": [],
            "target_object_id": "fact.x", "reviewer": "minhyun-ji",
            "reviewed_at": "2026-06-02T00:00:00+09:00", "verdict": "approved",
        }
        errors = validate_object(review)
        self.assertTrue(any("invalid truth_role" in e and "ReviewRecord" in e for e in errors))

    def test_candidate_glossary_requires_candidate_metadata(self):
        errors = validate_object(self._glossary_term(status="candidate", evidence_refs=[]))
        self.assertTrue(any("candidate metadata" in e for e in errors))

    def test_reviewed_glossary_rejects_unresolved_conflict_candidate(self):
        errors = validate_object(self._glossary_term(candidate={
            "candidate_state": "conflict",
            "candidate_source": "spec",
            "open_questions": ["State enum boundary is unresolved."],
        }))
        self.assertTrue(any("reviewed GlossaryTerm" in e and "conflict" in e for e in errors))

    def test_context_projection_valid(self):
        self.assertEqual(validate_object(self._projection()), [])

    def test_context_projection_rejects_wrong_stale_policy(self):
        errors = validate_object(self._projection(stale_policy="manual_review"))
        self.assertTrue(any("stale_policy" in e for e in errors))
```

- [ ] **Step 2: Update store test fixture to include v2 GlossaryTerm fields**

In `scripts/bb2_brain/tests/test_store.py`, update `test_save_object_validates_and_round_trips` object so it contains `context_id`:

```python
                "context_id": "context.stage-clear-token",
                "term": "입장팝업", "definition": "스테이지 진입 시 뜨는 팝업.",
```

Add a new save test for `ContextProjection`:

```python
    def test_save_context_projection_uses_index_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            obj = {
                "id": "projection.sally-canoe.context-md", "kind": "ContextProjection",
                "schema_version": "0.1", "status": "reviewed", "poc_priority": "P0",
                "truth_role": "index", "title": "projection", "tags": [],
                "created_at": "2026-06-02T00:00:00+09:00",
                "updated_at": "2026-06-02T00:00:00+09:00", "evidence_refs": [],
                "context_id": "context.sally-canoe", "format": "context_md",
                "output_locator": "docs/contexts/generated/sally-canoe/CONTEXT.md",
                "source_object_ids": ["context.sally-canoe"],
                "source_content_hash": "abc123", "projection_hash": "def456",
                "generated_at": "2026-06-02T00:00:00+09:00", "generated_by": "test",
                "stale_policy": "fail_on_manual_edit",
            }
            path = BrainStore.save_object(root, obj)
            self.assertEqual(path.relative_to(root).as_posix(), "indexes/context_projections/projection.sally-canoe.context-md.json")
```

- [ ] **Step 3: Run tests to verify failures**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_schema scripts.bb2_brain.tests.test_store -v
```

Expected: FAIL with missing `context_id`, unknown `ContextProjection`, missing truth-role/candidate validations, or missing `ContextProjection` save directory.

- [ ] **Step 4: Replace schema constants and add v2 validation**

In `scripts/bb2_brain/schema.py`, update `KIND_REQUIRED`, add enum sets, and extend `validate_object` with this exact logic:

```python
KIND_REQUIRED = {
    "EvidenceManifest": ("source_type", "locator", "captured_at", "captured_by",
                         "sensitivity", "acl", "redaction_status"),
    "EvidenceRef": ("evidence_manifest_id", "ref_type", "locator", "summary"),
    "ReviewRecord": ("target_object_id", "reviewer", "reviewed_at", "verdict"),
    "EventLedgerRecord": ("event_type", "happened_at", "summary", "related_objects"),
    "TemporalFact": ("subject", "predicate", "value", "scope", "valid_from",
                     "derived_from_event_id", "confidence"),
    "CodeLocator": ("repo", "path", "locator_source", "verified_at"),
    "DomainContext": ("context_key", "project_id", "display_name", "boundary_summary",
                      "in_scope", "out_of_scope", "injection_profile", "glossary_term_ids"),
    "GlossaryTerm": ("context_id", "term", "definition"),
    "ContextProjection": ("context_id", "format", "source_object_ids", "source_content_hash",
                          "projection_hash", "generated_at", "generated_by", "stale_policy"),
    "CurrentView": ("view_type", "as_of", "source_fact_ids", "source_event_ids", "summary"),
    "KnowledgePage": ("category", "path", "summary", "source_object_ids", "stale_policy"),
    "IndexRecord": ("index_name", "source_object_id", "indexed_at", "content_hash"),
    "SpecDocument": ("source_system", "canonical_locator"),
    "SpecRevision": ("spec_document_id", "revision_label", "captured_at", "slide_refs"),
    "SlideRef": ("spec_revision_id", "slide_no"),
    "SlackThread": ("channel_id", "thread_ts", "participants", "message_refs", "summary"),
}

TRUTH_ROLE_VALUES = frozenset({
    "source", "reference", "review", "event", "fact", "synthesis", "domain", "index",
})
KIND_TRUTH_ROLE = {
    "EvidenceManifest": "source",
    "EvidenceRef": "reference",
    "ReviewRecord": "review",
    "EventLedgerRecord": "event",
    "TemporalFact": "fact",
    "CodeLocator": "reference",
    "DomainContext": "domain",
    "GlossaryTerm": "domain",
    "ContextProjection": "index",
    "CurrentView": "synthesis",
    "KnowledgePage": "synthesis",
    "IndexRecord": "index",
    "SpecDocument": "reference",
    "SpecRevision": "reference",
    "SlideRef": "reference",
    "SlackThread": "source",
}
OBJECT_STATUS_VALUES = frozenset({"candidate", "reviewed", "superseded", "archived", "rejected"})
POC_PRIORITY_VALUES = frozenset({"P0", "P1", "P2"})
AUDIENCE_VALUES = frozenset({"coding-agent", "planner", "reviewer", "search-router"})
CANDIDATE_STATE_VALUES = frozenset({
    "observed", "evidence_verified", "needs_user_confirmation", "conflict", "ready_for_review",
})
CANDIDATE_SOURCE_VALUES = frozenset({
    "spec", "code", "session", "slack", "jira", "legacy_context", "legacy_wiki", "manual",
})
PROJECTION_FORMAT_VALUES = frozenset({"context_md", "prompt_payload"})
INDEX_NAME_VALUES = frozenset({"fts", "timeline", "entity", "code_locator", "trigram", "vector"})
```

Inside `validate_object`, after the required-field loops and before the kind-specific enum block, add:

```python
    status = obj.get("status")
    if status is not None and status not in OBJECT_STATUS_VALUES:
        errors.append(f"{obj['id']}: invalid status {status!r}")
    priority = obj.get("poc_priority")
    if priority is not None and priority not in POC_PRIORITY_VALUES:
        errors.append(f"{obj['id']}: invalid poc_priority {priority!r}")
    truth_role = obj.get("truth_role")
    if truth_role is not None and truth_role not in TRUTH_ROLE_VALUES:
        errors.append(f"{obj['id']}: invalid truth_role {truth_role!r}")
    expected_truth_role = KIND_TRUTH_ROLE.get(kind)
    if truth_role is not None and expected_truth_role is not None and truth_role != expected_truth_role:
        errors.append(f"{obj['id']}: {kind} invalid truth_role {truth_role!r}, expected {expected_truth_role!r}")
```

Add these new kind branches:

```python
    elif kind == "DomainContext":
        for legacy_field in ("path", "source_format"):
            if legacy_field in obj:
                errors.append(f"{obj['id']}: DomainContext legacy field {legacy_field!r} is not canonical in v2")
        profile = obj.get("injection_profile") or {}
        audience = profile.get("default_audience")
        if audience is not None and audience not in AUDIENCE_VALUES:
            errors.append(f"{obj['id']}: DomainContext invalid default_audience {audience!r}")
        for export_target in obj.get("export_targets") or []:
            fmt = export_target.get("format")
            if fmt not in PROJECTION_FORMAT_VALUES:
                errors.append(f"{obj['id']}: DomainContext invalid export target format {fmt!r}")
    elif kind == "GlossaryTerm":
        candidate = obj.get("candidate")
        if obj.get("status") == "candidate" and not candidate:
            errors.append(f"{obj['id']}: candidate GlossaryTerm requires candidate metadata")
        if candidate:
            state = candidate.get("candidate_state")
            source = candidate.get("candidate_source")
            if state not in CANDIDATE_STATE_VALUES:
                errors.append(f"{obj['id']}: GlossaryTerm invalid candidate_state {state!r}")
            if source not in CANDIDATE_SOURCE_VALUES:
                errors.append(f"{obj['id']}: GlossaryTerm invalid candidate_source {source!r}")
            if obj.get("status") == "reviewed":
                if state == "conflict":
                    errors.append(f"{obj['id']}: reviewed GlossaryTerm cannot keep candidate_state 'conflict'")
                if candidate.get("open_questions"):
                    errors.append(f"{obj['id']}: reviewed GlossaryTerm cannot keep unresolved open_questions")
        if obj.get("status") == "rejected" and not obj.get("rejection"):
            errors.append(f"{obj['id']}: rejected GlossaryTerm requires rejection metadata")
    elif kind == "ContextProjection":
        fmt = obj.get("format")
        if fmt is not None and fmt not in PROJECTION_FORMAT_VALUES:
            errors.append(f"{obj['id']}: ContextProjection invalid format {fmt!r}")
        stale_policy = obj.get("stale_policy")
        if stale_policy != "fail_on_manual_edit":
            errors.append(f"{obj['id']}: ContextProjection invalid stale_policy {stale_policy!r}")
    elif kind == "IndexRecord":
        index_name = obj.get("index_name")
        if index_name is not None and index_name not in INDEX_NAME_VALUES:
            errors.append(f"{obj['id']}: IndexRecord invalid index_name {index_name!r}")
```

Keep the existing `EvidenceManifest`, `EvidenceRef`, `CodeLocator`, and `TemporalFact` enum checks after these branches. If the file currently uses an `elif` chain, merge the new branches into the same chain so each kind is checked exactly once.

- [ ] **Step 5: Add store directories**

In `scripts/bb2_brain/store.py`, add these entries to `_KIND_DIR`:

```python
        "ContextProjection": "indexes/context_projections",
        "KnowledgePage": "views/knowledge",
        "IndexRecord": "indexes/records",
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_schema scripts.bb2_brain.tests.test_store -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/bb2_brain/schema.py scripts/bb2_brain/store.py scripts/bb2_brain/tests/test_schema.py scripts/bb2_brain/tests/test_store.py
git commit -m "feat: validate BB2 Brain domain context v2 schema" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 3: Domain-context lint guards

**Files:**

- Modify: `scripts/bb2_brain/lint.py`
- Modify: `scripts/bb2_brain/tests/test_lint.py`

- [ ] **Step 1: Add failing lint tests**

Append these tests to `scripts/bb2_brain/tests/test_lint.py` inside `LintTest`:

```python
    def _domain_context(self, **over):
        obj = {
            "id": "context.sally-canoe", "kind": "DomainContext", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "domain",
            "title": "Sally Canoe", "tags": [], "evidence_refs": [],
            "created_at": "2026-06-02T00:00:00+09:00",
            "updated_at": "2026-06-02T00:00:00+09:00",
            "context_key": "sally-canoe", "project_id": "bb2-client", "display_name": "Sally Canoe",
            "boundary_summary": "Sally Canoe lifecycle/state vocabulary.",
            "in_scope": ["Lifecycle and race state terms."],
            "out_of_scope": ["UI layout details."],
            "injection_profile": {"default_audience": "coding-agent", "include_candidates": False},
            "glossary_term_ids": [],
        }
        obj.update(over)
        return obj

    def _term(self, **over):
        obj = {
            "id": "glossary.sally-canoe.race-stage", "kind": "GlossaryTerm", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "domain",
            "title": "Race Stage", "tags": [], "evidence_refs": ["ref.spec"],
            "created_at": "2026-06-02T00:00:00+09:00",
            "updated_at": "2026-06-02T00:00:00+09:00",
            "context_id": "context.sally-canoe", "term": "Race Stage",
            "definition": "Stage progression spine.", "scope_hint": {"feature": "sally-canoe"},
        }
        obj.update(over)
        return obj

    def _manifest(self, mid, source_type):
        return {
            "id": mid, "kind": "EvidenceManifest", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "source",
            "title": mid, "tags": [], "evidence_refs": [],
            "created_at": "2026-06-02T00:00:00+09:00",
            "updated_at": "2026-06-02T00:00:00+09:00",
            "source_type": source_type, "locator": "loc",
            "captured_at": "2026-06-02T00:00:00+09:00",
            "captured_by": "minhyun-ji", "sensitivity": "internal",
            "acl": ["bb2-client-team"], "redaction_status": "approved",
        }

    def _ref(self, rid, manifest_id):
        return {
            "id": rid, "kind": "EvidenceRef", "schema_version": "0.1",
            "status": "reviewed", "poc_priority": "P0", "truth_role": "reference",
            "title": rid, "tags": [], "evidence_refs": [],
            "created_at": "2026-06-02T00:00:00+09:00",
            "updated_at": "2026-06-02T00:00:00+09:00",
            "evidence_manifest_id": manifest_id, "ref_type": "spec_section",
            "locator": {"path": "spec-v8.md", "line_start": 36, "line_end": 65},
            "summary": "spec section",
        }

    def test_reviewed_glossary_only_legacy_context_evidence_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "raw/manifests/context.json", self._manifest("manifest.context", "context"))
            write_object(root, "objects/evidence_refs/context.json", self._ref("ref.context", "manifest.context"))
            write_object(root, "objects/domain/term.json", self._term(evidence_refs=["ref.context"]))
            problems = lint_store(BrainStore.load(root))
            self.assertTrue(any("legacy-only evidence" in p and "glossary.sally-canoe.race-stage" in p for p in problems))

    def test_reviewed_glossary_with_spec_evidence_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "raw/manifests/spec.json", self._manifest("manifest.spec", "spec"))
            write_object(root, "objects/evidence_refs/spec.json", self._ref("ref.spec", "manifest.spec"))
            write_object(root, "objects/domain/term.json", self._term(evidence_refs=["ref.spec"]))
            problems = lint_store(BrainStore.load(root))
            self.assertFalse(any("legacy-only evidence" in p for p in problems))

    def test_context_projection_manual_edit_detected_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "indexes/context_projections/p.json", {
                "id": "projection.sally-canoe.context-md", "kind": "ContextProjection",
                "schema_version": "0.1", "status": "reviewed", "poc_priority": "P0",
                "truth_role": "index", "title": "projection", "tags": [],
                "created_at": "2026-06-02T00:00:00+09:00",
                "updated_at": "2026-06-02T00:00:00+09:00", "evidence_refs": [],
                "context_id": "context.sally-canoe", "format": "context_md",
                "output_locator": "docs/contexts/generated/sally-canoe/CONTEXT.md",
                "source_object_ids": ["context.sally-canoe"],
                "source_content_hash": "abc123", "projection_hash": "def456",
                "generated_at": "2026-06-02T00:00:00+09:00", "generated_by": "test",
                "stale_policy": "fail_on_manual_edit", "manual_edit_detected": True,
            })
            problems = lint_store(BrainStore.load(root))
            self.assertTrue(any("manual_edit_detected" in p for p in problems))

    def test_generated_context_hash_mismatch_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = workspace / "brain"
            generated = workspace / "docs/contexts/generated/sally-canoe/CONTEXT.md"
            generated.parent.mkdir(parents=True)
            generated.write_text("GENERATED FROM BB2 BRAIN - DO NOT EDIT\nchanged\n", encoding="utf-8")
            write_object(root, "indexes/context_projections/p.json", {
                "id": "projection.sally-canoe.context-md", "kind": "ContextProjection",
                "schema_version": "0.1", "status": "reviewed", "poc_priority": "P0",
                "truth_role": "index", "title": "projection", "tags": [],
                "created_at": "2026-06-02T00:00:00+09:00",
                "updated_at": "2026-06-02T00:00:00+09:00", "evidence_refs": [],
                "context_id": "context.sally-canoe", "format": "context_md",
                "output_locator": "docs/contexts/generated/sally-canoe/CONTEXT.md",
                "source_object_ids": ["context.sally-canoe"],
                "source_content_hash": "abc123", "projection_hash": "wrong-hash",
                "generated_at": "2026-06-02T00:00:00+09:00", "generated_by": "test",
                "stale_policy": "fail_on_manual_edit",
            })
            problems = lint_store(BrainStore.load(root), workspace)
            self.assertTrue(any("projection_hash mismatch" in p for p in problems))

    def test_generated_context_without_projection_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            root = workspace / "brain"
            root.mkdir(parents=True)
            generated = workspace / "docs/contexts/generated/sally-canoe/CONTEXT.md"
            generated.parent.mkdir(parents=True)
            generated.write_text("GENERATED FROM BB2 BRAIN - DO NOT EDIT\n# Sally Canoe\n", encoding="utf-8")
            problems = lint_store(BrainStore.load(root), workspace)
            self.assertTrue(any("generated context file has no ContextProjection" in p for p in problems))
```

- [ ] **Step 2: Verify failures**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_lint -v
```

Expected: FAIL because lint does not yet know legacy-only evidence, manual edit, or hash mismatch rules.

- [ ] **Step 3: Add domain lint helpers**

Replace `scripts/bb2_brain/lint.py` with this implementation, preserving `_conflicting_fact_groups` reuse:

```python
"""오프라인 무결성 검사. store 전체를 스캔해 object-model 불변조건 위반을 모아 보고한다.
런타임(router ⑤ _resolve_current_conflicts)은 쿼리 시점 충돌만, Lint는 전수 선제 검사.
충돌 탐지는 router의 순수 함수 _conflicting_fact_groups를 재사용한다(중복 구현 금지)."""

import hashlib
from pathlib import Path

from scripts.bb2_brain.router import _conflicting_fact_groups
from scripts.bb2_brain.schema import validate_object
from scripts.bb2_brain.store import BrainStore

GENERATED_HEADER = "GENERATED FROM BB2 BRAIN - DO NOT EDIT"
LEGACY_SOURCE_TYPES = {"context", "wiki"}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _source_type_for_evidence_ref(store: BrainStore, ref_id: str) -> str | None:
    if not store.has(ref_id):
        return None
    ref = store.get(ref_id)
    manifest_id = ref.get("evidence_manifest_id")
    if not manifest_id or not store.has(manifest_id):
        return None
    return store.get(manifest_id).get("source_type")


def _has_only_legacy_evidence(store: BrainStore, obj: dict) -> bool:
    refs = obj.get("evidence_refs", [])
    if not refs:
        return False
    source_types = [_source_type_for_evidence_ref(store, ref_id) for ref_id in refs]
    return bool(source_types) and all(source_type in LEGACY_SOURCE_TYPES for source_type in source_types)


def _lint_generated_projection_file(projection: dict, workspace_root: Path) -> list[str]:
    problems: list[str] = []
    output_locator = projection.get("output_locator")
    if not output_locator:
        return problems


def _lint_generated_files_have_projection(store: BrainStore, workspace_root: Path) -> list[str]:
        problems: list[str] = []
        generated_root = workspace_root / "docs/contexts/generated"
        if not generated_root.exists():
            return problems
        projected_locators = {
            projection.get("output_locator")
            for projection in store.by_kind("ContextProjection")
            if projection.get("format") == "context_md"
        }
        for path in generated_root.rglob("CONTEXT.md"):
            rel = path.relative_to(workspace_root).as_posix()
            content = path.read_text(encoding="utf-8")
            if GENERATED_HEADER in content and rel not in projected_locators:
                problems.append(f"{rel}: generated context file has no ContextProjection")
        return problems
    output_path = workspace_root / output_locator
    if not output_path.exists():
        return problems
    content = output_path.read_text(encoding="utf-8")
    if GENERATED_HEADER in content:
        actual_hash = _sha256_text(content)
        if actual_hash != projection.get("projection_hash"):
            problems.append(
                f"{projection['id']}: projection_hash mismatch for {output_locator}"
            )
    return problems


def lint_store(store: BrainStore, workspace_root: Path | None = None) -> list[str]:
    problems: list[str] = []
    objs = store.all()

    # 1) 스키마 위반 (kind별 필수 필드)
    for obj in objs:
        problems.extend(validate_object(obj))

    # 2) 같은 subject+predicate에 valid_until 없는 reviewed fact가 값 갈리며 2+ (object-model L298)
    for group in _conflicting_fact_groups(store.by_kind("TemporalFact")):
        ids = ", ".join(sorted(f["id"] for f in group))
        problems.append(f"conflict: open reviewed facts [{ids}] share subject+predicate but differ in value")

    # 3) CurrentView가 없는 fact를 가리킴
    for view in store.by_kind("CurrentView"):
        for fid in view.get("source_fact_ids", []):
            if not store.has(fid):
                problems.append(f"{view['id']}: dangling source_fact_id {fid}")

    # 4) dangling evidence_refs / review_record_id
    for obj in objs:
        for ref in obj.get("evidence_refs", []):
            if not store.has(ref):
                problems.append(f"{obj['id']}: dangling evidence_ref {ref}")
        rrid = obj.get("review_record_id")
        if rrid and not store.has(rrid):
            problems.append(f"{obj['id']}: dangling review_record_id {rrid}")

    # 5) DomainContext v2: legacy path/source_format must not be canonical fields.
    for context in store.by_kind("DomainContext"):
        for legacy_field in ("path", "source_format"):
            if legacy_field in context:
                problems.append(f"{context['id']}: DomainContext legacy field {legacy_field} is not allowed")

    # 6) GlossaryTerm lifecycle/evidence guard.
    for term in store.by_kind("GlossaryTerm"):
        if term.get("status") == "candidate" and not term.get("candidate"):
            problems.append(f"{term['id']}: candidate GlossaryTerm missing candidate metadata")
        candidate = term.get("candidate") or {}
        if term.get("status") == "reviewed":
            if candidate.get("candidate_state") == "conflict" or candidate.get("open_questions"):
                problems.append(f"{term['id']}: reviewed GlossaryTerm has unresolved candidate metadata")
            if _has_only_legacy_evidence(store, term):
                problems.append(f"{term['id']}: reviewed GlossaryTerm has legacy-only evidence")
        if term.get("status") == "rejected" and not term.get("rejection"):
            problems.append(f"{term['id']}: rejected GlossaryTerm missing rejection metadata")

    # 7) ContextProjection guard.
    for projection in store.by_kind("ContextProjection"):
        if projection.get("manual_edit_detected"):
            problems.append(f"{projection['id']}: manual_edit_detected is true")
        if workspace_root is not None:
            problems.extend(_lint_generated_projection_file(projection, Path(workspace_root)))

    if workspace_root is not None:
        problems.extend(_lint_generated_files_have_projection(store, Path(workspace_root)))

    return problems
```

- [ ] **Step 4: Run lint tests**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_lint -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain/lint.py scripts/bb2_brain/tests/test_lint.py
git commit -m "feat: add domain context v2 lint guards" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 4: ContextProjection renderer and CLI export

**Files:**

- Create: `scripts/bb2_brain/context_projection.py`
- Modify: `scripts/bb2_brain/cli.py`
- Create: `scripts/bb2_brain/tests/test_context_projection.py`

- [ ] **Step 1: Write failing projection tests**

Create `scripts/bb2_brain/tests/test_context_projection.py`:

```python
import tempfile
import unittest
from pathlib import Path

from scripts.bb2_brain.context_projection import (
    GENERATED_HEADER,
    build_context_projection,
    render_context_markdown,
)
from scripts.bb2_brain.store import BrainStore
from scripts.bb2_brain.tests.test_router import write_object


def _base(obj):
    obj.setdefault("schema_version", "0.1")
    obj.setdefault("poc_priority", "P0")
    obj.setdefault("created_at", "2026-06-02T00:00:00+09:00")
    obj.setdefault("updated_at", "2026-06-02T00:00:00+09:00")
    obj.setdefault("tags", ["bb2-client"])
    obj.setdefault("evidence_refs", [])
    return obj


class ContextProjectionTest(unittest.TestCase):
    def _store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "brain"
        write_object(root, "objects/domain/context.json", _base({
            "id": "context.sally-canoe", "kind": "DomainContext", "status": "reviewed",
            "truth_role": "domain", "title": "Sally Canoe", "context_key": "sally-canoe",
            "project_id": "bb2-client", "display_name": "Sally Canoe",
            "boundary_summary": "Lifecycle/state vocabulary for Sally Canoe.",
            "in_scope": ["Race lifecycle and state spine."],
            "out_of_scope": ["UI layout details."],
            "injection_profile": {"default_audience": "coding-agent", "include_candidates": False},
            "glossary_term_ids": [
                "glossary.sally-canoe.race-stage",
                "glossary.sally-canoe.dummy-npc",
            ],
        }))
        write_object(root, "objects/domain/race_stage.json", _base({
            "id": "glossary.sally-canoe.race-stage", "kind": "GlossaryTerm",
            "status": "reviewed", "truth_role": "domain", "title": "Race Stage",
            "context_id": "context.sally-canoe", "term": "Race Stage",
            "definition": "The 1-3 progression step that changes required clear count and reward.",
            "avoid": ["단계 UI"], "synonyms": ["Race Step"],
            "scope_hint": {"feature": "sally-canoe", "release": "5.5"},
            "evidence_refs": ["ref.sally.basic-info"],
        }))
        write_object(root, "objects/domain/dummy_npc.json", _base({
            "id": "glossary.sally-canoe.dummy-npc", "kind": "GlossaryTerm",
            "status": "candidate", "truth_role": "domain", "title": "Dummy NPC",
            "context_id": "context.sally-canoe", "term": "Dummy NPC",
            "definition": "A non-real-user race participant.",
            "candidate": {
                "candidate_state": "evidence_verified",
                "candidate_source": "spec",
                "promotion_criteria": ["Confirm NPC matching boundary with planner."],
            },
            "evidence_refs": ["ref.sally.dummy-npc"],
        }))
        return BrainStore.load(root)

    def test_render_context_markdown_includes_reviewed_terms_only(self):
        content = render_context_markdown(self._store(), "context.sally-canoe")
        self.assertIn(GENERATED_HEADER, content)
        self.assertIn("Sally Canoe", content)
        self.assertIn("Race Stage", content)
        self.assertIn("The 1-3 progression step", content)
        self.assertNotIn("Dummy NPC", content)

    def test_build_context_projection_records_source_ids_and_hash(self):
        store = self._store()
        projection, content = build_context_projection(
            store,
            "context.sally-canoe",
            output_locator="docs/contexts/generated/sally-canoe/CONTEXT.md",
            generated_at="2026-06-02T00:00:00+09:00",
            generated_by="test",
        )
        self.assertEqual(projection["kind"], "ContextProjection")
        self.assertEqual(projection["truth_role"], "index")
        self.assertEqual(projection["format"], "context_md")
        self.assertEqual(projection["stale_policy"], "fail_on_manual_edit")
        self.assertEqual(
            projection["source_object_ids"],
            ["context.sally-canoe", "glossary.sally-canoe.race-stage"],
        )
        self.assertEqual(len(projection["projection_hash"]), 64)
        self.assertIn("Race Stage", content)
        self.assertNotIn("Dummy NPC", content)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_context_projection -v
```

Expected: FAIL — `ModuleNotFoundError: scripts.bb2_brain.context_projection`.

- [ ] **Step 3: Create context_projection.py**

Create `scripts/bb2_brain/context_projection.py`:

```python
import hashlib
import json

from scripts.bb2_brain.store import BrainStore

GENERATED_HEADER = "GENERATED FROM BB2 BRAIN - DO NOT EDIT"
SCHEMA_VERSION = "0.1"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _reviewed_terms_for_context(store: BrainStore, context: dict) -> list[dict]:
    terms = []
    for term_id in context.get("glossary_term_ids", []):
        if not store.has(term_id):
            continue
        term = store.get(term_id)
        if term.get("kind") == "GlossaryTerm" and term.get("status") == "reviewed":
            terms.append(term)
    return sorted(terms, key=lambda term: term.get("term", ""))


def render_context_markdown(store: BrainStore, context_id: str) -> str:
    context = store.get(context_id)
    terms = _reviewed_terms_for_context(store, context)
    lines = [
        GENERATED_HEADER,
        f"source_context_id: {context_id}",
        "",
        f"# {context.get('display_name') or context.get('title')}",
        "",
        "## Boundary",
        "",
        context.get("boundary_summary", ""),
        "",
        "## In scope",
        "",
    ]
    lines.extend(f"- {item}" for item in context.get("in_scope", []))
    lines.extend(["", "## Out of scope", ""])
    lines.extend(f"- {item}" for item in context.get("out_of_scope", []))
    lines.extend(["", "## Reviewed glossary", ""])
    if not terms:
        lines.append("_No reviewed terms._")
    for term in terms:
        lines.append(f"### {term['term']}")
        lines.append("")
        lines.append(term["definition"])
        avoid = term.get("avoid") or []
        if avoid:
            lines.append("")
            lines.append("Avoid aliases: " + ", ".join(avoid))
        synonyms = term.get("synonyms") or []
        if synonyms:
            lines.append("")
            lines.append("Synonyms: " + ", ".join(synonyms))
        scope_hint = term.get("scope_hint") or {}
        if scope_hint:
            rendered_scope = ", ".join(f"{key}={value}" for key, value in sorted(scope_hint.items()))
            lines.append("")
            lines.append("Scope hint: " + rendered_scope)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_context_projection(
    store: BrainStore,
    context_id: str,
    *,
    output_locator: str,
    generated_at: str,
    generated_by: str,
) -> tuple[dict, str]:
    context = store.get(context_id)
    terms = _reviewed_terms_for_context(store, context)
    source_objects = [context] + terms
    source_object_ids = [obj["id"] for obj in source_objects]
    source_content_hash = _sha256_text("\n".join(_stable_json(obj) for obj in source_objects))
    content = render_context_markdown(store, context_id)
    projection_hash = _sha256_text(content)
    projection_id = f"projection.{context.get('context_key', context_id)}.context-md"
    projection = {
        "id": projection_id,
        "kind": "ContextProjection",
        "schema_version": SCHEMA_VERSION,
        "status": "reviewed",
        "poc_priority": "P0",
        "truth_role": "index",
        "title": f"Generated context_md projection for {context.get('display_name') or context_id}",
        "created_at": generated_at,
        "updated_at": generated_at,
        "tags": context.get("tags", []),
        "evidence_refs": [],
        "context_id": context_id,
        "format": "context_md",
        "output_locator": output_locator,
        "source_object_ids": source_object_ids,
        "source_content_hash": source_content_hash,
        "projection_hash": projection_hash,
        "generated_at": generated_at,
        "generated_by": generated_by,
        "stale_policy": "fail_on_manual_edit",
    }
    return projection, content
```

- [ ] **Step 4: Add CLI export path**

Modify `scripts/bb2_brain/cli.py` to:

```python
import argparse
import json
from pathlib import Path

from scripts.bb2_brain.context_projection import build_context_projection
from scripts.bb2_brain.router import QueryRouter
from scripts.bb2_brain.store import BrainStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brain-root", required=True)
    parser.add_argument("--current-head")
    parser.add_argument("--export-context")
    parser.add_argument("--output")
    parser.add_argument("--generated-at", default="2026-06-02T00:00:00+09:00")
    parser.add_argument("--generated-by", default="scripts.bb2_brain.cli")
    parser.add_argument("query", nargs="?")
    args = parser.parse_args()

    brain_root = Path(args.brain_root)
    store = BrainStore.load(brain_root)

    if args.export_context:
        if not args.output:
            parser.error("--output is required with --export-context")
        projection, content = build_context_projection(
            store,
            args.export_context,
            output_locator=args.output,
            generated_at=args.generated_at,
            generated_by=args.generated_by,
        )
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        BrainStore.save_object(brain_root, projection)
        print(json.dumps(projection, ensure_ascii=False, indent=2))
        return 0

    if not args.query:
        parser.error("query is required unless --export-context is used")
    answer = QueryRouter(store, current_head=args.current_head).answer(args.query)
    print(json.dumps(answer, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run projection tests**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_context_projection -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/bb2_brain/context_projection.py scripts/bb2_brain/cli.py scripts/bb2_brain/tests/test_context_projection.py
git commit -m "feat: generate BB2 Brain context projections" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 5: Migrate existing stage-clear-token seed to v2 domain rules

**Files:**

- Modify: `scripts/bb2_brain/seed_first_slice.py`
- Create: `scripts/bb2_brain/tests/test_seed_first_slice.py`

- [ ] **Step 1: Add failing seed migration tests**

Create `scripts/bb2_brain/tests/test_seed_first_slice.py`:

```python
import unittest

from scripts.bb2_brain.seed_first_slice import build_objects
from scripts.bb2_brain.lint import lint_store
from scripts.bb2_brain.store import BrainStore


class SeedFirstSliceV2Test(unittest.TestCase):
    def _objects(self):
        return {obj["id"]: obj for obj in build_objects()}

    def test_domain_context_uses_v2_fields_and_domain_truth_role(self):
        context = self._objects()["context.stage-clear-token"]
        self.assertEqual(context["truth_role"], "domain")
        self.assertEqual(context["context_key"], "stage-clear-token")
        self.assertEqual(context["project_id"], "bb2-client")
        self.assertIn("boundary_summary", context)
        self.assertIn("injection_profile", context)
        self.assertNotIn("path", context)
        self.assertNotIn("source_format", context)

    def test_glossary_terms_use_domain_truth_role_context_id_and_primary_evidence(self):
        objects = self._objects()
        for term_id in [
            "glossary.stage-clear-token",
            "glossary.popup-enter",
            "glossary.popup-continue",
            "glossary.event-cluster",
        ]:
            term = objects[term_id]
            self.assertEqual(term["truth_role"], "domain")
            self.assertEqual(term["context_id"], "context.stage-clear-token")
            self.assertNotEqual(term["evidence_refs"], ["ref.context"])

    def test_review_records_use_review_truth_role(self):
        reviews = [obj for obj in build_objects() if obj["kind"] == "ReviewRecord"]
        self.assertTrue(reviews)
        self.assertTrue(all(review["truth_role"] == "review" for review in reviews))
        self.assertTrue(all("target_object_id" in review for review in reviews))
        self.assertTrue(all("verdict" in review for review in reviews))

    def test_seed_lint_is_clean_after_v2_migration(self):
        store = BrainStore({obj["id"]: obj for obj in build_objects()})
        self.assertEqual(lint_store(store), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failures**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_seed_first_slice -v
```

Expected: FAIL because current seed uses `truth_role="reference"` for domain objects and old `path/source_format` fields.

- [ ] **Step 3: Update seed module docstring**

Replace the top docstring in `scripts/bb2_brain/seed_first_slice.py` with:

```python
"""BB2 Brain 첫 실데이터 슬라이스 적재: 스테이지 클리어 토큰 입장팝업 이벤트 클러스터.

object-model 스키마(schema.py BASE_REQUIRED + KIND_REQUIRED)로 brain/에 적재한다.
DomainContext/GlossaryTerm은 v2 Brain-first 모델을 따른다:
Brain reviewed glossary가 SoR이고, 기존 docs/contexts/stage-clear-token/CONTEXT.md는 legacy migration hint다.

재실행 가능: 시작 시 brain/을 비우고 다시 쓴다.

실행: cd /Users/al03040455/Desktop/bb2_client && python -m scripts.bb2_brain.seed_first_slice
"""
```

- [ ] **Step 4: Replace existing DomainContext block**

Replace the `context.stage-clear-token` object with:

```python
    objects.append(base({
        "id": "context.stage-clear-token",
        "kind": "DomainContext",
        "truth_role": "domain",
        "title": "도메인 컨텍스트: 스테이지 클리어 토큰 입장팝업 이벤트 표시",
        "context_key": "stage-clear-token",
        "project_id": "bb2-client",
        "display_name": "Stage Clear Token Popup Enter",
        "boundary_summary": "Stage clear token direct-use UI and PopupEnter event cluster vocabulary for release 5.5.",
        "in_scope": [
            "Stage clear token direct-use UI surfaces.",
            "PopupEnter and PopupContinue token entry points.",
            "PopupEnter event cluster display vocabulary.",
        ],
        "out_of_scope": [
            "Full item economy behavior.",
            "Every event listed in the popup cluster.",
            "Generated CONTEXT.md as source evidence.",
        ],
        "injection_profile": {
            "default_audience": "coding-agent",
            "include_candidates": False,
        },
        "export_targets": [{
            "format": "context_md",
            "locator": "docs/contexts/generated/stage-clear-token/CONTEXT.md",
        }],
        "glossary_term_ids": [
            "glossary.stage-clear-token",
            "glossary.popup-enter",
            "glossary.popup-continue",
            "glossary.event-cluster",
        ],
        "evidence_refs": ["ref.slide-happyblock", "ref.code-draw-cluster", "ref.code-enter-token", "ref.code-continue-token"],
        "review_record_id": "review.context.stage-clear-token",
    }))
```

- [ ] **Step 5: Replace four GlossaryTerm blocks with v2 fields**

Replace `glossary.stage-clear-token` with:

```python
    objects.append(base({
        "id": "glossary.stage-clear-token",
        "kind": "GlossaryTerm",
        "truth_role": "domain",
        "title": "용어: 스테이지 클리어 토큰",
        "context_id": "context.stage-clear-token",
        "term": "스테이지 클리어 토큰",
        "definition": "미클리어 대상 스테이지에서 사용할 수 있는 5.5 아이템/기능. 토큰 사용 가능 UI인 입장팝업과 컨티뉴 팝업에서의 사용 흐름을 중심으로 다룬다.",
        "synonyms": [],
        "avoid": ["클리어 패스 티켓", "clear pass ticket"],
        "scope_hint": {"feature": "stage-clear-token", "release": "5.5"},
        "evidence_refs": ["ref.slide-happyblock", "ref.code-enter-token", "ref.code-continue-token"],
        "review_record_id": "review.glossary.stage-clear-token",
    }))
```

Replace `glossary.popup-enter` with:

```python
    objects.append(base({
        "id": "glossary.popup-enter",
        "kind": "GlossaryTerm",
        "truth_role": "domain",
        "title": "용어: 입장팝업",
        "context_id": "context.stage-clear-token",
        "term": "입장팝업",
        "definition": "스테이지 진입 전에 표시되는 팝업. 스테이지 클리어 토큰 사용 가능 UI 중 하나이며, 이벤트 클러스터가 함께 배치되는 팝업 표면.",
        "synonyms": [],
        "avoid": ["시작팝업"],
        "scope_hint": {"surface": "PopupEnter", "release": "5.5"},
        "related_objects": ["locator.popup-enter-token"],
        "evidence_refs": ["ref.code-enter-token", "ref.code-draw-cluster"],
        "review_record_id": "review.glossary.popup-enter",
    }))
```

Replace `glossary.popup-continue` with:

```python
    objects.append(base({
        "id": "glossary.popup-continue",
        "kind": "GlossaryTerm",
        "truth_role": "domain",
        "title": "용어: 컨티뉴 팝업",
        "context_id": "context.stage-clear-token",
        "term": "컨티뉴 팝업",
        "definition": "실패 직후 이어하기 선택을 위해 표시되는 팝업. 스테이지 클리어 토큰을 사용할 수 있는 직접 UI 중 하나로서 실패 직후 이어하기 선택 표면.",
        "synonyms": [],
        "avoid": [],
        "scope_hint": {"surface": "PopupContinue", "release": "5.5"},
        "related_objects": ["locator.popup-continue-token"],
        "evidence_refs": ["ref.code-continue-token"],
        "review_record_id": "review.glossary.popup-continue",
    }))
```

Replace `glossary.event-cluster` with:

```python
    objects.append(base({
        "id": "glossary.event-cluster",
        "kind": "GlossaryTerm",
        "truth_role": "domain",
        "title": "용어: 이벤트 클러스터",
        "context_id": "context.stage-clear-token",
        "term": "이벤트 클러스터",
        "definition": "입장팝업에서 여러 이벤트의 표시 정보를 하나의 묶음 슬롯 UI로 보여주는 표시 영역. 스테이지 클리어 토큰 기능 자체와는 구분한다.",
        "synonyms": [],
        "avoid": ["이벤트 그룹", "서버 그룹", "클러스터 노드"],
        "scope_hint": {"surface": "PopupEnter", "release": "5.5"},
        "evidence_refs": ["ref.code-draw-cluster", "ref.slack"],
        "review_record_id": "review.glossary.event-cluster",
    }))
```

- [ ] **Step 6: Update ReviewRecord generation**

In the `ReviewRecord` loop, change:

```python
            "truth_role": "reference",
```

to:

```python
            "truth_role": "review",
```

- [ ] **Step 7: Run focused seed tests**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_seed_first_slice -v
```

Expected: PASS.

- [ ] **Step 8: Regenerate first slice data and lint it**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m scripts.bb2_brain.seed_first_slice
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python - <<'PY'
from pathlib import Path
from scripts.bb2_brain.lint import lint_store
from scripts.bb2_brain.store import BrainStore

problems = lint_store(BrainStore.load(Path("scripts/bb2_brain/brain")), Path("."))
if problems:
    print("\n".join(problems))
raise SystemExit(1 if problems else 0)
PY
```

Expected: no output from the inline lint script and exit code 0.

- [ ] **Step 9: Commit**

```bash
git add scripts/bb2_brain/seed_first_slice.py scripts/bb2_brain/tests/test_seed_first_slice.py scripts/bb2_brain/brain
git commit -m "feat: migrate first Brain seed to domain context v2" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 6: Sally Canoe v2 domain seed and generated adapter E2E

**Files:**

- Create: `scripts/bb2_brain/seed_sally_canoe_domain_v2.py`
- Create: `scripts/bb2_brain/tests/test_seed_sally_canoe_domain_v2.py`
- Generated: `docs/contexts/generated/sally-canoe/CONTEXT.md`
- Generated: `scripts/bb2_brain/brain/indexes/context_projections/projection.sally-canoe.context-md.json`

- [ ] **Step 1: Write failing Sally Canoe seed tests**

Create `scripts/bb2_brain/tests/test_seed_sally_canoe_domain_v2.py`:

```python
import unittest

from scripts.bb2_brain.context_projection import build_context_projection
from scripts.bb2_brain.seed_sally_canoe_domain_v2 import build_objects
from scripts.bb2_brain.lint import lint_store
from scripts.bb2_brain.store import BrainStore


class SallyCanoeDomainV2SeedTest(unittest.TestCase):
    def _objects(self):
        return {obj["id"]: obj for obj in build_objects()}

    def test_acceptance_shape(self):
        objects = self._objects()
        context = objects["context.sally-canoe"]
        self.assertEqual(context["kind"], "DomainContext")
        self.assertEqual(context["truth_role"], "domain")
        self.assertEqual(context["context_key"], "sally-canoe")
        terms = [
            obj for obj in objects.values()
            if obj.get("kind") == "GlossaryTerm" and obj.get("context_id") == "context.sally-canoe"
        ]
        self.assertEqual(len(terms), 5)
        self.assertEqual(len([term for term in terms if term["status"] == "reviewed"]), 1)
        self.assertEqual(len([term for term in terms if term["status"] == "candidate"]), 4)
        self.assertEqual(objects["glossary.sally-canoe.race-stage"]["status"], "reviewed")
        self.assertEqual(objects["glossary.sally-canoe.race-state"]["candidate"]["candidate_state"], "conflict")
        self.assertTrue(objects["glossary.sally-canoe.race-state"]["candidate"]["open_questions"])

    def test_reviewed_term_uses_primary_spec_evidence(self):
        objects = self._objects()
        reviewed = objects["glossary.sally-canoe.race-stage"]
        self.assertEqual(reviewed["evidence_refs"], ["ref.sally.basic-info"])
        ref = objects["ref.sally.basic-info"]
        manifest = objects[ref["evidence_manifest_id"]]
        self.assertEqual(manifest["source_type"], "spec")

    def test_projection_includes_reviewed_and_excludes_unresolved_candidates(self):
        store = BrainStore(self._objects())
        projection, content = build_context_projection(
            store,
            "context.sally-canoe",
            output_locator="docs/contexts/generated/sally-canoe/CONTEXT.md",
            generated_at="2026-06-02T00:00:00+09:00",
            generated_by="seed_sally_canoe_domain_v2",
        )
        self.assertIn("Race Stage", content)
        self.assertNotIn("Race State", content)
        self.assertNotIn("Dummy NPC", content)
        self.assertEqual(projection["source_object_ids"], [
            "context.sally-canoe",
            "glossary.sally-canoe.race-stage",
        ])

    def test_sally_seed_lint_clean_before_projection_file_check(self):
        store = BrainStore(self._objects())
        self.assertEqual(lint_store(store), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Verify failure**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_seed_sally_canoe_domain_v2 -v
```

Expected: FAIL — `ModuleNotFoundError: scripts.bb2_brain.seed_sally_canoe_domain_v2`.

- [ ] **Step 3: Create Sally Canoe seed script**

Create `scripts/bb2_brain/seed_sally_canoe_domain_v2.py`:

```python
"""BB2 Brain Domain Context v2 acceptance seed: Sally Canoe lifecycle/state spine.

This script appends the Sally Canoe domain objects to an existing brain root.
Run seed_first_slice first when rebuilding the full local corpus.
"""

from pathlib import Path

from scripts.bb2_brain.store import BrainStore

BRAIN_ROOT = Path(__file__).parent / "brain"
SCHEMA_VERSION = "0.1"
T_CREATED = "2026-06-02T00:00:00+09:00"
T_UPDATED = "2026-06-02T00:00:00+09:00"
T_CAPTURED = "2026-04-16T00:00:00+09:00"
T_REVIEW = "2026-06-02T00:00:00+09:00"


def base(obj: dict) -> dict:
    defaults = {
        "schema_version": SCHEMA_VERSION,
        "poc_priority": "P0",
        "created_at": T_CREATED,
        "updated_at": T_UPDATED,
        "tags": ["bb2-client", "sally-canoe", "domain-context-v2"],
        "evidence_refs": [],
    }
    for key, value in defaults.items():
        obj.setdefault(key, value)
    return obj


def build_objects() -> list[dict]:
    objects: list[dict] = []

    objects.append(base({
        "id": "manifest.sally-canoe-spec-v8",
        "kind": "EvidenceManifest",
        "status": "reviewed",
        "truth_role": "source",
        "title": "기획서 추출: 5.5 신규 카누 레이스 spec-v8.md",
        "source_type": "spec",
        "locator": "~/Desktop/vault/inbox/dumps/sally-canoe/spec-v8.md",
        "captured_at": T_CAPTURED,
        "captured_by": "minhyun-ji",
        "sensitivity": "internal",
        "acl": ["bb2-client-team"],
        "redaction_status": "approved",
    }))
    objects.append(base({
        "id": "ref.sally.basic-info",
        "kind": "EvidenceRef",
        "status": "reviewed",
        "truth_role": "reference",
        "title": "Sally Canoe spec-v8 basic lifecycle lines 36-65",
        "evidence_manifest_id": "manifest.sally-canoe-spec-v8",
        "ref_type": "spec_section",
        "locator": {"path": "~/Desktop/vault/inbox/dumps/sally-canoe/spec-v8.md", "line_start": 36, "line_end": 65},
        "summary": "7-player small race, 1 race time limit, 1-3 stage progression, repeated participation, cooldown after race completion.",
    }))
    objects.append(base({
        "id": "ref.sally.dummy-npc",
        "kind": "EvidenceRef",
        "status": "reviewed",
        "truth_role": "reference",
        "title": "Sally Canoe spec-v8 dummy NPC matching lines 174-185",
        "evidence_manifest_id": "manifest.sally-canoe-spec-v8",
        "ref_type": "spec_section",
        "locator": {"path": "~/Desktop/vault/inbox/dumps/sally-canoe/spec-v8.md", "line_start": 174, "line_end": 185},
        "summary": "Matching uses DUMMY NPC only and does not match real users.",
    }))
    objects.append(base({
        "id": "ref.sally.race-state",
        "kind": "EvidenceRef",
        "status": "reviewed",
        "truth_role": "reference",
        "title": "Sally Canoe spec-v8 race state display lines 1238-1250",
        "evidence_manifest_id": "manifest.sally-canoe-spec-v8",
        "ref_type": "spec_section",
        "locator": {"path": "~/Desktop/vault/inbox/dumps/sally-canoe/spec-v8.md", "line_start": 1238, "line_end": 1250},
        "summary": "Event page and floating icon display current race state, remaining race time, finishers, and progress count.",
    }))
    objects.append(base({
        "id": "ref.sally.cooldown",
        "kind": "EvidenceRef",
        "status": "reviewed",
        "truth_role": "reference",
        "title": "Sally Canoe spec-v8 cooldown lines 1438-1464 and 1888-1908",
        "evidence_manifest_id": "manifest.sally-canoe-spec-v8",
        "ref_type": "spec_section",
        "locator": {"path": "~/Desktop/vault/inbox/dumps/sally-canoe/spec-v8.md", "line_ranges": [[1438, 1464], [1888, 1908]]},
        "summary": "After race result handling, floating icon, start popup event info, and new banner are shown after cooldown ends.",
    }))

    objects.append(base({
        "id": "context.sally-canoe",
        "kind": "DomainContext",
        "status": "reviewed",
        "truth_role": "domain",
        "title": "도메인 컨텍스트: Sally Canoe lifecycle/state spine",
        "context_key": "sally-canoe",
        "project_id": "bb2-client",
        "display_name": "Sally Canoe",
        "boundary_summary": "Sally Canoe lifecycle/state vocabulary for race creation, stage progression, NPC participants, race state, and cooldown.",
        "in_scope": [
            "Race lifecycle and state spine terms.",
            "Stage progression terms that affect repeat participation.",
            "NPC participant vocabulary that affects race semantics.",
        ],
        "out_of_scope": [
            "Popup layout details.",
            "Reward item table details.",
            "Full event scene motion implementation.",
        ],
        "injection_profile": {"default_audience": "coding-agent", "include_candidates": False},
        "export_targets": [{
            "format": "context_md",
            "locator": "docs/contexts/generated/sally-canoe/CONTEXT.md",
        }],
        "glossary_term_ids": [
            "glossary.sally-canoe.event",
            "glossary.sally-canoe.race-stage",
            "glossary.sally-canoe.race-state",
            "glossary.sally-canoe.dummy-npc",
            "glossary.sally-canoe.cooldown",
        ],
        "evidence_refs": ["ref.sally.basic-info", "ref.sally.dummy-npc", "ref.sally.race-state", "ref.sally.cooldown"],
    }))

    objects.append(base({
        "id": "glossary.sally-canoe.event",
        "kind": "GlossaryTerm",
        "status": "candidate",
        "truth_role": "domain",
        "title": "Candidate term: Sally Canoe Event",
        "context_id": "context.sally-canoe",
        "term": "Sally Canoe Event",
        "definition": "The 5.5 small-group race event where players clear original/bonus stages and compete against NPC participants.",
        "scope_hint": {"feature": "sally-canoe", "release": "5.5"},
        "candidate": {
            "candidate_state": "observed",
            "candidate_source": "spec",
            "promotion_criteria": ["Confirm canonical English/Korean event name with implementation enum and spec title."],
        },
        "evidence_refs": ["ref.sally.basic-info"],
    }))
    objects.append(base({
        "id": "glossary.sally-canoe.race-stage",
        "kind": "GlossaryTerm",
        "status": "reviewed",
        "truth_role": "domain",
        "title": "Reviewed term: Race Stage",
        "context_id": "context.sally-canoe",
        "term": "Race Stage",
        "definition": "The 1-3 stage progression spine. Completion moves to the next stage, failure keeps the same stage, and each stage can require a different clear count and reward.",
        "synonyms": ["Race Step"],
        "avoid": ["UI page step"],
        "scope_hint": {"feature": "sally-canoe", "release": "5.5"},
        "evidence_refs": ["ref.sally.basic-info"],
        "review_record_id": "review.glossary.sally-canoe.race-stage",
    }))
    objects.append(base({
        "id": "glossary.sally-canoe.race-state",
        "kind": "GlossaryTerm",
        "status": "candidate",
        "truth_role": "domain",
        "title": "Candidate term: Race State",
        "context_id": "context.sally-canoe",
        "term": "Race State",
        "definition": "The current race display/behavior state, including racing, not racing, finishers, remaining race time, and challenge entry.",
        "scope_hint": {"feature": "sally-canoe", "release": "5.5"},
        "candidate": {
            "candidate_state": "conflict",
            "candidate_source": "spec",
            "open_questions": ["Confirm whether Race State is a canonical domain enum or only a UI display grouping."],
            "conflicts_with": ["glossary.sally-canoe.event"],
            "promotion_criteria": ["Find code enum/model field or planner confirmation for state boundary."],
        },
        "evidence_refs": ["ref.sally.race-state"],
    }))
    objects.append(base({
        "id": "glossary.sally-canoe.dummy-npc",
        "kind": "GlossaryTerm",
        "status": "candidate",
        "truth_role": "domain",
        "title": "Candidate term: Dummy NPC",
        "context_id": "context.sally-canoe",
        "term": "Dummy NPC",
        "definition": "A non-real-user participant used for Sally Canoe race matching.",
        "scope_hint": {"feature": "sally-canoe", "release": "5.5"},
        "candidate": {
            "candidate_state": "evidence_verified",
            "candidate_source": "spec",
            "promotion_criteria": ["Confirm implementation-side naming and whether NPC info admin affects the canonical term."],
        },
        "evidence_refs": ["ref.sally.dummy-npc"],
    }))
    objects.append(base({
        "id": "glossary.sally-canoe.cooldown",
        "kind": "GlossaryTerm",
        "status": "candidate",
        "truth_role": "domain",
        "title": "Candidate term: Cooldown",
        "context_id": "context.sally-canoe",
        "term": "Cooldown",
        "definition": "The waiting period after race completion before a new race can start and entry surfaces reappear.",
        "scope_hint": {"feature": "sally-canoe", "release": "5.5"},
        "candidate": {
            "candidate_state": "evidence_verified",
            "candidate_source": "spec",
            "promotion_criteria": ["Confirm server/client field name and repeat-participation reset semantics."],
        },
        "evidence_refs": ["ref.sally.basic-info", "ref.sally.cooldown"],
    }))

    objects.append(base({
        "id": "review.glossary.sally-canoe.race-stage",
        "kind": "ReviewRecord",
        "status": "reviewed",
        "truth_role": "review",
        "title": "검수 기록: Race Stage",
        "target_object_id": "glossary.sally-canoe.race-stage",
        "reviewer": "minhyun-ji",
        "reviewed_at": T_REVIEW,
        "verdict": "approved",
        "evidence_refs": ["ref.sally.basic-info"],
    }))

    return objects


def main() -> int:
    for obj in build_objects():
        BrainStore.save_object(BRAIN_ROOT, obj)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run Sally seed tests**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_seed_sally_canoe_domain_v2 -v
```

Expected: PASS.

- [ ] **Step 5: Generate full local corpus and Sally context projection**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m scripts.bb2_brain.seed_first_slice
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m scripts.bb2_brain.seed_sally_canoe_domain_v2
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m scripts.bb2_brain.cli \
  --brain-root scripts/bb2_brain/brain \
  --export-context context.sally-canoe \
  --output docs/contexts/generated/sally-canoe/CONTEXT.md \
  --generated-at 2026-06-02T00:00:00+09:00 \
  --generated-by seed_sally_canoe_domain_v2
```

Expected:

- `docs/contexts/generated/sally-canoe/CONTEXT.md` exists.
- `scripts/bb2_brain/brain/indexes/context_projections/projection.sally-canoe.context-md.json` exists.
- CLI prints a `ContextProjection` JSON object with `"truth_role": "index"`.

- [ ] **Step 6: Verify generated adapter contains reviewed term only**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
rg -n "GENERATED FROM BB2 BRAIN|Race Stage|Race State|Dummy NPC|Cooldown|Sally Canoe Event" docs/contexts/generated/sally-canoe/CONTEXT.md
```

Expected:

- Matches for `GENERATED FROM BB2 BRAIN` and `Race Stage`.
- No matches for `Race State`, `Dummy NPC`, `Cooldown`, or `Sally Canoe Event`.

- [ ] **Step 7: Run lint including generated projection hash**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python - <<'PY'
from pathlib import Path
from scripts.bb2_brain.lint import lint_store
from scripts.bb2_brain.store import BrainStore

problems = lint_store(BrainStore.load(Path("scripts/bb2_brain/brain")), Path("."))
if problems:
    print("\n".join(problems))
raise SystemExit(1 if problems else 0)
PY
```

Expected: no output and exit code 0.

- [ ] **Step 8: Commit**

```bash
git add scripts/bb2_brain/seed_sally_canoe_domain_v2.py scripts/bb2_brain/tests/test_seed_sally_canoe_domain_v2.py scripts/bb2_brain/brain docs/contexts/generated/sally-canoe/CONTEXT.md
git commit -m "feat: add Sally Canoe domain context v2 seed" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Task 7: Final regression, CLI smoke tests, and vault handoff update

**Files:**

- Verify: all `scripts/bb2_brain/tests/*.py`
- Verify: `scripts/bb2_brain/brain/`
- Verify: `docs/contexts/generated/sally-canoe/CONTEXT.md`
- Update if implementation is completed: vault task `~/Desktop/vault/tasks/active/bb2-brain.md`
- Update if implementation is completed: vault note `~/Desktop/vault/wiki/bb2-client/2026-06-02-bb2-brain-redesign-ingest-interview.md`
- Update if implementation is completed: vault hub `~/Desktop/vault/wiki/bb2-client/bb2-brain-design-hub.md`

- [ ] **Step 1: Run full Brain unittest suite**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest \
  scripts.bb2_brain.tests.test_schema \
  scripts.bb2_brain.tests.test_store \
  scripts.bb2_brain.tests.test_lint \
  scripts.bb2_brain.tests.test_intent \
  scripts.bb2_brain.tests.test_status \
  scripts.bb2_brain.tests.test_router \
  scripts.bb2_brain.tests.test_context_projection \
  scripts.bb2_brain.tests.test_seed_first_slice \
  scripts.bb2_brain.tests.test_seed_sally_canoe_domain_v2
```

Expected: PASS.

- [ ] **Step 2: Run stage-clear-token CLI smoke query**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m scripts.bb2_brain.cli \
  --brain-root scripts/bb2_brain/brain \
  "5.5 기준 입장팝업의 요정의 선물/해피블록 표시가 왜 drawEventCluster 형태로 바뀌었고, 현재 QA 기준 동작은 뭐야?" \
  | rg -n '"status": "reviewed"|"fact.displayrule-current"|"locator.draw-event-cluster"'
```

Expected: matches all three patterns.

- [ ] **Step 3: Run Sally Canoe generated adapter smoke check**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
test -f docs/contexts/generated/sally-canoe/CONTEXT.md
rg -n "Race Stage" docs/contexts/generated/sally-canoe/CONTEXT.md
! rg -n "Race State|Dummy NPC|Cooldown|Sally Canoe Event" docs/contexts/generated/sally-canoe/CONTEXT.md
```

Expected: `Race Stage` is present and candidate terms are absent.

- [ ] **Step 4: Check git only contains intended files for this slice**

Run:

```bash
cd /Users/al03040455/Desktop/bb2_client
git --no-pager status --short
```

Expected: unrelated pre-existing files may still appear (`UserGameDataManager.cpp`, `MapController.cpp`, `SplashController.cpp`, `Podfile.lock`, workspace artifacts). Do not stage or revert unrelated files.

- [ ] **Step 5: Update vault task and notes**

Update the vault files listed above with:

```markdown
2026-06-02 — Domain Context v2 implementation completed.
- Repo spec migration removed `CONTEXT.md`-first assumptions.
- `schema.py` now validates truth_role enum + kind-specific roles.
- `lint.py` now rejects legacy-only reviewed glossary evidence and stale/generated projection edits.
- `ContextProjection` export path generates `docs/contexts/generated/sally-canoe/CONTEXT.md`.
- Sally Canoe domain slice contains 5 lifecycle/state terms, 1 reviewed term, 1 unresolved conflict candidate, and generated adapter output excludes candidates.
- Implementation commits are the commits created by Tasks 1-6 in this plan.
```

Run vault embeddings after editing:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python ~/.claude/scripts/vault-embed-batch.py
```

Expected: embedding script reports changed files processed.

- [ ] **Step 6: Commit vault updates if they live in a git repo**

If `~/Desktop/vault` is a git repo and status shows only intentional wiki/task edits:

```bash
cd /Users/al03040455/Desktop/vault
git add tasks/active/bb2-brain.md wiki/bb2-client/2026-06-02-bb2-brain-redesign-ingest-interview.md wiki/bb2-client/bb2-brain-design-hub.md wiki/bb2-client/_index.md wiki/bb2-client/_log.md
git commit -m "docs: record BB2 Brain domain context v2 implementation" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: vault commit succeeds or is skipped because the vault is not a git repository.

---

## Final Acceptance Checklist

- [ ] Old `CONTEXT.md`-first spec wording is removed from object-model/storage/query active paths.
- [ ] `DomainContext` requires v2 namespace fields and rejects `path` / `source_format`.
- [ ] `GlossaryTerm(status="candidate")` requires candidate metadata.
- [ ] Reviewed glossary terms cannot retain conflict/open-question candidate metadata.
- [ ] `truth_role` enum and kind-specific truth-role mapping are enforced.
- [ ] `ContextProjection` validates as `truth_role="index"` and `stale_policy="fail_on_manual_edit"`.
- [ ] Lint rejects reviewed glossary terms backed only by legacy context/wiki evidence.
- [ ] Lint rejects generated context files that have no matching `ContextProjection`.
- [ ] Lint rejects generated context projection hash mismatch and `manual_edit_detected`.
- [ ] Existing stage-clear-token seed is migrated to domain truth roles and primary evidence.
- [ ] Sally Canoe domain has one `DomainContext(context_key="sally-canoe")`.
- [ ] Sally Canoe has five lifecycle/state terms total, with one reviewed term and four candidates.
- [ ] Sally Canoe keeps one conflict candidate with open questions.
- [ ] Generated Sally Canoe `CONTEXT.md` includes the reviewed term and excludes unresolved candidates.
- [ ] Full Brain unittest suite passes.
- [ ] CLI stage-clear-token smoke query still returns reviewed answer with expected source ids.
