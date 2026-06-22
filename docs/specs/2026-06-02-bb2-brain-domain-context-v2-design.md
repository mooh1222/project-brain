---
title: BB2 Brain Domain Context v2 Design
date: 2026-06-02
status: draft-for-review
scope: domain-context-v2
supersedes:
  - docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md#11-domain-context-objects
related:
  - docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md
  - docs/superpowers/specs/2026-05-28-bb2-brain-query-routing-design.md
  - docs/superpowers/specs/2026-06-02-bb2-brain-domain-mapping-lifecycle-design.md
---

# BB2 Brain Domain Context v2 Design

## 1. Purpose

This spec revises the BB2 Brain domain vocabulary model after the 2026-06-02 deep interview and Prometheus/Codex reviews.

The previous design treated Matt Pocock-style `CONTEXT.md` as a source file that Brain could ingest. That creates a duplicate source of truth. In v2, Brain owns the domain vocabulary directly:

```text
DomainContext + GlossaryTerm(reviewed) = canonical domain context
generated CONTEXT.md = disposable adapter/export
```

The existing `docs/contexts/.../CONTEXT.md` files are not canonical inputs for new Brain domains. They may be used only as legacy migration hints or design provenance.

## 2. Design decisions

### 2.1 Brain-first source of truth

`DomainContext` and reviewed `GlossaryTerm` objects are the source of truth for ubiquitous language.

Rules:

- Do not create or edit `CONTEXT.md` before creating Brain vocabulary objects.
- Do not promote a term using a context file alone.
- Term evidence must point to raw spec, session, code, Slack, Jira, or other primary evidence.
- Legacy context files can appear as secondary migration hints, but they cannot be the only evidence for reviewed terms.

### 2.2 Generated adapter, not source file

Direct Brain context injection is the long-term runtime path. Until every agent can consume Brain directly, Brain may generate a `CONTEXT.md` adapter.

Generated adapters are disposable projections:

- They must contain a generated header: `GENERATED FROM BB2 BRAIN - DO NOT EDIT`.
- They must record source object ids, projection hash, and generated timestamp.
- They must be linted for staleness against source object hashes.
- Manual edits are treated as lint failures in P0.

Manual-edit import can be considered later, but P0 must pick one policy. P0 chooses **fail on manual edit** to prevent a second source of truth from reappearing.

### 2.3 Three-layer split

The domain-context system has three separate layers:

| Layer | Objects | Responsibility | Cannot do |
|---|---|---|---|
| Canonical vocabulary | `DomainContext`, `GlossaryTerm` | Define approved domain language and avoid aliases. | Discover all candidates by itself. |
| Discovery | `IndexRecord` and candidate extraction | Find candidate terms, aliases, UI names, QA names, code symbols. | Canonicalize vocabulary without reviewed terms. |
| Runtime injection/export | `ContextProjection` or direct Brain injection | Produce prompt payloads or generated files under context-budget rules. | Become evidence or source truth. |

Query routing may use discovery first, but final answers and prompt payloads must return to canonical Brain objects.

## 3. Object model changes

### 3.1 `DomainContext` v2

`DomainContext` is no longer "a path to `CONTEXT.md`". It is a Brain namespace and boundary object.

```ts
interface DomainContext extends BrainObjectBase {
  kind: "DomainContext";
  truth_role: "domain";
  poc_priority: "P0";

  context_key: string;         // stable id, e.g. "sally-canoe"
  project_id: string;          // e.g. "bb2-client"; P0 uses string, not ProjectContext object
  display_name: string;        // human-readable name

  parent_context_id?: ObjectId;
  child_context_ids?: ObjectId[];

  boundary_summary: string;
  in_scope: string[];
  out_of_scope: string[];

  injection_profile: {
    default_audience: "coding-agent" | "planner" | "reviewer" | "search-router";
    max_terms?: number;
    include_candidates?: boolean; // default false for agent-facing prompt
  };

  export_targets?: {
    format: "context_md" | "prompt_payload";
    locator?: string;           // output path when format is context_md
  }[];

  glossary_term_ids: ObjectId[];
}
```

P0 uses `project_id` as a canonical string. A separate `ProjectContext` object is deferred until multi-project metadata needs behavior beyond a stable id.

### 3.2 `GlossaryTerm` v2

`GlossaryTerm` remains the vocabulary unit. P0 does not introduce a separate `DomainTermProposal` type. Candidate lifecycle is modeled as metadata on `GlossaryTerm`.

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

Rules:

- `status = "candidate"` requires `candidate`.
- `status = "reviewed"` must not contain unresolved `open_questions` or `candidate_state = "conflict"`.
- `status = "rejected"` must contain `rejection`.
- Reviewed terms can appear in agent-facing context exports.
- Candidate terms can appear only in review queues, diagnostics, or explicit candidate views.
- If rejected/conflict terms make the schema hard to reason about, split them into `DomainTermProposal` in a later spec.

### 3.3 `ContextProjection`

P0 adds `ContextProjection` as a disposable export metadata object. It uses existing `truth_role = "index"` because projections are rebuildable and must not be cited as evidence.

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

Rules:

- A projection can be deleted and rebuilt.
- A projection cannot be used as evidence for a reviewed term.
- If `manual_edit_detected = true`, domain-context lint fails.
- `ContextProjection` is the only P0 object allowed to point at generated `CONTEXT.md` output paths.

## 4. Evidence and legacy context policy

Legacy context files can help find candidates, but they cannot be the authority for reviewed terms.

| Source | P0 role | Promotion use |
|---|---|---|
| Raw spec markdown/PPT extraction | Primary evidence | Can support reviewed terms. |
| Code locator / code search | Primary evidence for implementation vocabulary | Can support reviewed terms when term boundary is code-visible. |
| Session transcript / design interview | Primary evidence for user intent and naming decisions | Can support reviewed terms when captured and reviewable. |
| Slack/Jira/PR | Primary evidence for operational decisions | Can support reviewed terms and facts. |
| Existing `CONTEXT.md` | Legacy migration hint or generated projection | Cannot be sole evidence for reviewed terms. |
| Existing vault wiki | Legacy migration hint or design provenance | Cannot be sole evidence for reviewed terms. |

The previous `EvidenceManifest.source_type = "context"` should not be used for canonical reviewed term evidence in new slices. Existing data can keep it during migration, but lint must flag it when it is the only evidence for a reviewed `GlossaryTerm`.

## 5. Schema and lint guards

P0 must add schema/lint checks because Codex review found spec/data drift.

### 5.1 Kind-to-truth-role guard

The schema validator must verify both enum membership and kind-specific allowed values.

Minimum P0 mapping:

| Kind | Allowed `truth_role` |
|---|---|
| `EvidenceManifest` | `source` |
| `EvidenceRef` | `reference` |
| `ReviewRecord` | `review` |
| `EventLedgerRecord` | `event` |
| `TemporalFact` | `fact` |
| `KnowledgePage` | `synthesis` |
| `CurrentView` | `synthesis` |
| `CodeLocator` | `reference` |
| `DomainContext` | `domain` |
| `GlossaryTerm` | `domain` |
| `ContextProjection` | `index` |
| `IndexRecord` | `index` |

### 5.2 Domain-context lint

Lint must fail when:

- `DomainContext` uses old `path` / `source_format` as canonical fields.
- `GlossaryTerm(status="candidate")` lacks `candidate`.
- `GlossaryTerm(status="reviewed")` has unresolved candidate conflict state.
- A reviewed `GlossaryTerm` has only legacy context/wiki evidence.
- A generated context file exists but has no `ContextProjection`.
- A generated context file hash differs from `ContextProjection.projection_hash`.
- `ContextProjection.manual_edit_detected = true`.

## 6. Query and injection behavior

### 6.1 Query preflight

Query routing must stop reading glossary preflight terms from `docs/contexts/.../CONTEXT.md`.

New preflight order:

1. Identify candidate context by explicit query terms, project scope, or `IndexRecord` entity hits.
2. Load matching `DomainContext`.
3. Load reviewed `GlossaryTerm` objects for canonical terms, synonyms, avoid aliases, and scope hints.
4. Use candidate `GlossaryTerm` only for clarification or review surfaces, not for final canonicalization.
5. Continue to evidence/fact/event/code objects before producing claims.

### 6.2 Agent context injection

P0 supports generated adapter injection. Direct Brain injection remains the target architecture.

Generated prompt/context payload should include:

- context key and boundary summary
- reviewed terms only
- avoid aliases
- relevant scope hints
- source object ids for traceability
- projection hash

It must not include unresolved candidate terms in normal coding-agent mode. Candidate terms can be included only when the task is domain review.

## 7. Migration plan

The v2 migration is a design prerequisite before adding the Sally Canoe domain.

### 7.1 Spec migration

Update existing specs so they no longer imply `CONTEXT.md` is canonical:

- Object model §11: replace file/path model with `DomainContext` v2 and `GlossaryTerm` v2.
- Object model acceptance: replace `docs/contexts/stage-clear-token/CONTEXT.md` with Brain reviewed glossary objects.
- Storage ingest §6: replace "context glossary terms" as deterministic source with "Brain vocabulary objects and approved raw evidence".
- Query routing frontmatter: remove `docs/contexts/stage-clear-token/CONTEXT.md` from `depends_on`.
- Query routing acceptance: preflight glossary terms from Brain objects, not context files.

### 7.2 Data/test migration

Update current seed and fixtures:

- Replace `manifest.context` as canonical evidence with primary spec/session/code evidence.
- Keep legacy context references only as `candidate_source = "legacy_context"` or design provenance.
- Set `DomainContext` and `GlossaryTerm` seed objects to `truth_role = "domain"`.
- Add `ContextProjection` only when an export file is generated.
- Add tests that fail old `truth_role = "reference"` on domain objects.
- Add tests that fail reviewed terms backed only by legacy context evidence.

## 8. Sally Canoe v2 acceptance criteria

The first Brain-first domain slice is Sally Canoe lifecycle/state spine.

Input sources:

- `spec-v8.md` PPT extraction
- existing vault analysis only as migration hint
- develop code
- relevant session/design transcript

P0 acceptance:

1. Create one `DomainContext(context_key="sally-canoe")`.
2. Create five `GlossaryTerm(status="candidate")` objects for lifecycle/state spine terms.
   - Initial candidates: `Sally Canoe Event`, `Race Stage`, `Race State`, `Dummy NPC`, `Cooldown`.
3. Keep one candidate in `candidate_state = "conflict"` with `open_questions`.
4. Promote exactly one term to `status = "reviewed"` with primary evidence refs.
5. Generate one `ContextProjection(format="context_md")` from reviewed vocabulary.
6. Prove generated output includes the reviewed term and excludes unresolved candidate terms in normal coding-agent mode.
7. Lint passes truth-role, projection-hash, and evidence-source guards.

## 9. Non-goals

- Do not implement direct Brain prompt injection in this slice.
- Do not build full Slack/Jira/code connector automation.
- Do not migrate every existing context file.
- Do not create `DomainTermProposal` unless candidate metadata proves insufficient.
- Do not use generated `CONTEXT.md` as evidence.

## 10. Deferred follow-ups

- Direct Brain injection transport is deferred. P0 uses generated adapter injection; a later spec can choose CLI, MCP, or session hook transport.
- `ProjectContext` is deferred. P0 uses `project_id` as a canonical string until a second project needs project-level metadata.
- Manual edit import is deferred. P0 always fails generated export manual edits in lint.
- `domain-context-writer` rewrite is a separate skill migration task. This spec only defines the Brain objects and acceptance criteria that the rewritten skill must target.

## 11. Follow-up: domain mapping lifecycle

The Sally Canoe real ingest slice showed that v2 is safe but too vocabulary-centered as the long-term review model. `GlossaryTerm(reviewed)` is useful for canonical names, synonyms, avoid aliases, and query preflight, but it is too small to represent how BB2 domain meaning is formed across specs, alpha implementation, Slack clarification, Jira QA/improvement tickets, beta sanity, REAL QA, release, and hotfixes.

The follow-up design is:

```text
Evidence + Decision
  -> DomainMapping(reviewed)
  -> GlossaryTerm / ContextProjection
```

Important corrections:

- `DomainContext` remains phase-independent. Alpha/beta/REAL are evidence provenance, not separate context namespaces.
- Planning specs are primary evidence, but not exclusive truth. Jira or Slack can contain a newer effective decision when the spec update is missing.
- Reviewed glossary terms should not be the only source for generated context. Agent-facing projections should eventually include reviewed `DomainMapping` boundaries, caveats, and code anchors.
- `ReviewRecord` needs typed review intent, such as meaning review, evidence review, implementation review, and projection review.

See `docs/superpowers/specs/2026-06-02-bb2-brain-domain-mapping-lifecycle-design.md` for the next design direction. This does not invalidate the v2 implementation; it extends v2 by moving the primary review unit from standalone vocabulary to evidence-backed meaning mappings.
