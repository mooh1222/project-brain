---
title: BB2 Brain Domain Mapping Lifecycle Design
date: 2026-06-02
status: draft-for-review
scope: domain-mapping-lifecycle
related:
  - docs/superpowers/specs/2026-06-02-bb2-brain-domain-context-v2-design.md
  - docs/superpowers/specs/2026-06-02-bb2-brain-sally-canoe-real-ingest-design.md
  - docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md
---

# BB2 Brain Domain Mapping Lifecycle Design

## 1. Purpose

Domain Context v2 proved that Brain can own domain vocabulary directly and generate disposable `CONTEXT.md` adapters from reviewed objects. The Sally Canoe real ingest slice then exposed a larger design issue: a `GlossaryTerm` review is too small as the primary review unit for BB2 development knowledge.

This spec defines the next design direction:

```text
Evidence + Decision
  -> DomainMapping(reviewed)
  -> GlossaryTerm / ContextProjection
```

The goal is not to turn Brain into a release tracker. The goal is to let an agent understand the user's domain words without repeated clarification by mapping those words to planning documents, Slack/Jira decisions, QA findings, and implemented code boundaries.

## 2. Problem statement

The v2 model is safe but vocabulary-centered:

```text
DomainContext + GlossaryTerm(reviewed) = canonical domain context
```

That is enough for canonical names, synonyms, and avoid aliases. It is not enough to capture how BB2 knowledge is actually formed:

- A spec is written first, but it changes often during alpha development.
- Beta sanity can produce spec improvements before full QA.
- Jira contains both QA issues and improvement requests, and may contain the effective change even when the spec update is omitted.
- Slack discussions can resolve ambiguous planning points and trigger spec updates.
- Code is the implemented interpretation, but it may reflect decisions not yet mirrored in the planning document.
- Hotfixes can amend released behavior after the original spec and QA pass.

If Brain stores only the first spec and promotes terms one by one, it drifts. The error is not that the domain context should be tied to alpha/beta/REAL phases. The error is that Brain needs a persistent evidence and decision lifecycle around the domain context.

## 3. Design principles

### 3.1 Domain context is phase-independent

`DomainContext` represents a meaning namespace and boundary. It should not be modeled as "alpha context", "beta context", or "REAL context".

Development phases are provenance and evidence metadata. They explain where a decision came from, when it was observed, and whether newer evidence may supersede it.

### 3.2 A planning document is important but not exclusive truth

Planning specs remain primary evidence for planner intent, but they are not the only authority for domain meaning. Slack, Jira, QA/sanity outcomes, code, commits, PRs, and hotfix notes can all be primary evidence for a domain decision.

Brain must be able to represent:

```text
Spec says A
Slack/Jira later decides B
Spec update is missing or delayed
Code implements B
```

without silently reverting to A.

### 3.3 Glossary terms are language surfaces

`GlossaryTerm` remains valuable for canonical names, aliases, avoid terms, and query preflight. It should not carry the full burden of "what this feature behavior means in code".

The primary reviewed unit should be a mapping between a user/domain phrase and the evidence-backed implementation meaning.

### 3.4 Reviewed means "safe to use for this purpose"

The current object `status = "reviewed"` is too broad unless the review reason is recorded. A domain term can be meaning-reviewed while its code locator is stale, or an implementation mapping can be reviewed while a spec reflection is still missing.

Review records need typed review intent.

## 4. BB2 source lifecycle

The development flow Brain must support is:

```text
Initial spec
  -> alpha implementation
      -> frequent spec edits
      -> Slack clarification / improvement decisions
  -> beta sanity
      -> spec improvements can be made
      -> Jira improvement or QA issue can be created
  -> beta QA
  -> REAL QA
  -> release
  -> optional hotfix
```

This flow changes Brain requirements in two ways:

1. **Update ingest is as important as initial ingest.** A first spec snapshot becomes stale unless later Jira, Slack, spec revision, QA, and code evidence can amend it.
2. **Drift detection must operate at mapping level.** When a new decision conflicts with an existing reviewed meaning, Brain should mark the mapping as review-needed or superseded instead of continuing to project old knowledge.

## 5. Object model additions

### 5.1 `DecisionRecord`

`DecisionRecord` records why a domain meaning changed or became clarified.

```ts
interface DecisionRecord extends BrainObjectBase {
  kind: "DecisionRecord";
  truth_role: "event";
  poc_priority: "P0";

  decision_type:
    | "spec_clarification"
    | "spec_revision"
    | "improvement"
    | "qa_issue"
    | "sanity_change"
    | "hotfix_change"
    | "naming_decision"
    | "implementation_boundary";

  summary: string;
  decision: string;

  source_object_ids: ObjectId[];
  affected_context_ids: ObjectId[];
  affected_mapping_ids?: ObjectId[];
  affected_glossary_term_ids?: ObjectId[];

  spec_reflected: "yes" | "no" | "unknown" | "not_applicable";
  spec_revision_ids?: ObjectId[];
  jira_issue_ids?: ObjectId[];
  slack_thread_ids?: ObjectId[];
  code_locator_ids?: ObjectId[];
}
```

Rules:

- `spec_reflected = "no"` is a first-class state, not a lint failure. BB2 can have Jira/Slack decisions that are not yet reflected in the spec.
- A decision can affect multiple mappings and terms.
- A decision is evidence for why a mapping is accepted, amended, or superseded; it is not a prompt projection by itself.

### 5.2 `DomainMapping`

`DomainMapping` is the reviewed meaning unit. It links user language, spec meaning, operational decisions, and code anchors.

```ts
interface DomainMapping extends BrainObjectBase {
  kind: "DomainMapping";
  truth_role: "domain";
  poc_priority: "P0";

  context_id: ObjectId;
  mapping_key: string;

  canonical_summary: string;
  meaning: string;
  boundary: string;
  non_goals?: string[];

  glossary_term_ids: ObjectId[];
  decision_record_ids: ObjectId[];
  spec_revision_ids?: ObjectId[];
  code_locator_ids?: ObjectId[];

  projection_notes?: string[];
  caveats?: string[];

  supersedes_mapping_ids?: ObjectId[];
  review_state?: {
    meaning_reviewed?: boolean;
    evidence_reviewed?: boolean;
    implementation_reviewed?: boolean;
    projection_reviewed?: boolean;
  };
}
```

Rules:

- A normal coding-agent projection should be based on reviewed `DomainMapping` objects, not only reviewed `GlossaryTerm` objects.
- `GlossaryTerm` can point to mappings through `related_objects`.
- `DomainMapping` may include caveats such as "spec update missing, Jira decision is newer".
- A mapping with unresolved caveats can remain candidate or review-needed even if some related glossary terms are reviewed.

### 5.3 Existing source objects remain useful

The existing objects should be used instead of replaced:

| Existing object | Lifecycle role |
|---|---|
| `SpecDocument` | Stable planning document identity. |
| `SpecRevision` | Versioned spec snapshot such as v7/v8/v9. |
| `SlideRef` / `EvidenceRef` | Specific planning section or slide evidence. |
| `SlackThread` / `EvidenceManifest(source_type="slack")` | Clarification and development discussion source. |
| `EvidenceManifest(source_type="jira")` | QA issue, improvement request, attached decision source. |
| `CodeLocator` | Implementation anchor for a mapping. |
| `EventLedgerRecord` / `TemporalFact` | Historical fact/event layer for why/current/as-of questions. |
| `ContextProjection` | Disposable generated context metadata. |

## 6. Review model

`ReviewRecord` should gain a review-type concept. P0 can add it as an optional field before enforcing it.

```ts
review_type:
  | "meaning_review"
  | "evidence_review"
  | "implementation_review"
  | "projection_review"
  | "supersession_review"
```

Meaning:

| Review type | Confirms |
|---|---|
| `meaning_review` | The user and agent agree on the domain meaning and boundary. |
| `evidence_review` | The cited spec/Jira/Slack/source evidence actually supports the mapping. |
| `implementation_review` | The code anchors match the mapping. |
| `projection_review` | The mapping is safe to include in agent-facing context. |
| `supersession_review` | A newer mapping correctly replaces an older one. |

This prevents one `reviewed` label from implying more certainty than was actually checked.

### 6.1 Mapping review bundles

Domain review should not ask the user to approve every planning statement or glossary term one by one. Some domain slices need a coherent review operation over several `DomainMapping` objects.

P0 concept:

```text
MappingReviewBundle
  = a review operation that approves a coherent set of DomainMapping objects
    for one domain slice.
```

It confirms that the mapping set captures the agreed user meaning, evidence boundary, and code/spec relationship for that slice. It does not mean every source sentence or every term alias was individually approved.

Recommended P0 representation:

```ts
interface ReviewRecord {
  review_type?: "meaning_review" | "evidence_review" | "implementation_review" | "projection_review" | "supersession_review";
  review_scope?: "single_object" | "mapping_bundle";
  bundle_key?: string;
  confirmation_key?: string;
  target_object_id?: ObjectId;
  target_object_ids?: ObjectId[];
}
```

Rules:

- Do not introduce a separate `ReviewBundle` object kind in P0 unless the implementation strongly needs it.
- A bundle approval may promote multiple candidate `DomainMapping` objects to reviewed together.
- Bundle approval should create one auditable review record with `review_scope = "mapping_bundle"` and `target_object_ids`, or equivalent per-target records that share the same `bundle_key` and `confirmation_key`.
- The confirmation key should name the review operation, not individual mappings. Example: `bundle.sally-canoe.domain-mapping`.
- Later drift is mapping-specific. A new `DecisionRecord` that affects one mapping should produce a lint review-needed problem for that mapping, not automatically roll back the whole bundle.
- Bundle-approved mappings may mark the review dimensions actually covered by the bundle. For the Sally Canoe P0 bundle, `meaning_reviewed`, `evidence_reviewed`, and `projection_reviewed` are appropriate; `implementation_reviewed` should remain false/absent unless the code anchors were separately re-verified as an implementation review.
- A later mapping that supersedes one member of a bundle should not reuse the original bundle review as if the bundle had approved the new mapping. It should get its own `ReviewRecord` with `review_type = "supersession_review"` and `target_object_id` pointing to the superseding mapping.
- `review-needed` is not a new P0 status. Keep the existing object status/review state and surface the need as a blocking lint/update-ingest problem.

## 7. Source precedence by question intent

Brain should not use one global precedence rule such as "latest spec always wins". The answer depends on the user's question.

| User intent | Preferred source path |
|---|---|
| "What did the planner intend?" | Latest relevant `SpecRevision` plus linked decision records. |
| "What does this term mean when I say it?" | Reviewed `DomainMapping` plus `GlossaryTerm` aliases. |
| "Where is it implemented?" | `DomainMapping.code_locator_ids` and current code verification. |
| "Why did it change?" | `DecisionRecord`, `EventLedgerRecord`, Jira/Slack/spec revision evidence. |
| "What should the coding agent assume now?" | Reviewed `DomainMapping` with projection-approved notes and caveats. |

If sources disagree, Brain should surface the disagreement rather than auto-picking a hidden winner.

## 8. Ingest and update behavior

### 8.1 Initial ingest

Initial ingest creates source objects, candidate glossary terms, and candidate mappings.

```text
SpecRevision + code anchors
  -> GlossaryTerm(candidate)
  -> DomainMapping(candidate)
```

### 8.2 Update ingest

Update ingest handles later spec revisions, Jira tickets, Slack decisions, QA issues, and hotfix evidence.

```text
New evidence
  -> DecisionRecord(candidate/reviewed)
  -> compare with existing DomainMapping
  -> keep, amend, supersede, or emit review-needed lint problem
```

### 8.3 Drift detection

Lint or update ingest should flag:

- A reviewed mapping cites a spec revision superseded by a newer revision that changed the same concept.
- A Jira/Slack decision says the spec is not yet reflected.
- A `DecisionRecord` affects a reviewed mapping but the mapping has not incorporated that decision in `decision_record_ids`, and the mapping has not been superseded.
- A code locator commit differs from current HEAD when implementation review is required.
- A reviewed glossary term has no mapping for projection use.
- A generated projection is stale against source mappings.

The affected-mapping drift check is incorporation-based, not wall-clock based. Do not require `decision.created_at > mapping.updated_at`: old-but-unincorporated decisions are still drift, and same-timestamp fixtures should not mask a missing incorporation edge.

When this happens, lint/update ingest should report a blocking problem such as:

```text
mapping.sally-canoe.race-status: unincorporated decision decision.sally-canoe.race-status-v2 may affect reviewed mapping; review needed
```

Do not solve this by adding `review-needed` as a status label in P0.

P0 implementation note: the global "reviewed glossary term has no mapping for projection use" guard can be deferred if enabling it would make existing pre-mapping stores lint-dirty. If deferred, it must be recorded as an explicit follow-up rather than silently omitted.

## 9. Projection behavior

Agent-facing context should become mapping-centered.

Minimum projection content:

- `DomainContext` boundary summary.
- Canonical terms and aliases from related `GlossaryTerm` objects.
- Reviewed `DomainMapping` meaning and boundary.
- Important caveats, especially spec-not-reflected decisions.
- Code locator ids or stable symbols when useful for coding-agent routing.
- Source object ids and projection hash for traceability.

Candidate terms should still be excluded from normal coding-agent context unless the task is explicitly a domain review task.

## 10. Sally Canoe implications

Sally Canoe should not be treated as a special model. It is only the first example that revealed the issue.

The current real ingest slice remains valid as a P0 vocabulary/evidence slice. The next Sally Canoe update should add mappings such as:

- Naming mapping: `Canoe Race` is the current planning name; `Sally Canoe`, `Sally Canoe Event`, and `샐리의 카누` are aliases for the same event concept.
- Race status mapping: the domain status is the server `SALLY_CANOE_RACE_STATUS`; view state is UI display mapping.
- Participant mapping: race participants include the player and server-managed dummy participants; the client updates view data from server-provided records instead of simulating dummy behavior.
- Cooldown mapping: cooldown is the repeat-participation wait rule before a new race can start or entry surfaces reappear.

These should be reviewed as meaning/code mappings, not as isolated term approvals.

For P0, these Sally Canoe mappings should be handled as one mapping review bundle:

```text
confirmation_key = "bundle.sally-canoe.domain-mapping"
target mappings =
  - mapping.sally-canoe.naming
  - mapping.sally-canoe.race-status
  - mapping.sally-canoe.participant
  - mapping.sally-canoe.cooldown
```

The user review question should be bundle-shaped:

```text
Does this Sally Canoe mapping set correctly represent the agreed domain meanings and implementation boundaries?
```

It should not be four independent approval prompts for the four planning items. After bundle approval, later Jira/Slack/spec/code drift can still affect only one mapping.

## 11. Non-goals

- Do not model alpha/beta/REAL as separate `DomainContext` namespaces.
- Do not require a full Jira/Slack connector before storing manually captured evidence.
- Do not make `CONTEXT.md` canonical again.
- Do not auto-promote mappings from a single source without review.
- Do not replace `GlossaryTerm`; reduce its responsibility to language indexing and projection support.

## 12. Acceptance criteria

P0 implementation should prove:

1. `DomainMapping` objects can be stored, linted, and projected.
2. `DecisionRecord` objects can cite spec/Jira/Slack/code evidence and record `spec_reflected`.
3. A mapping can connect multiple `GlossaryTerm` aliases to one domain meaning.
4. Projection can include reviewed mapping boundaries and exclude candidate mappings.
5. An unincorporated affected decision can emit a review-needed lint problem for an existing mapping or be resolved through mapping supersession.
6. A mapping review bundle can promote multiple candidate mappings with one auditable confirmation.
7. Sally Canoe can represent the naming, race-status, participant, and cooldown mappings through `bundle.sally-canoe.domain-mapping` without asking the user to approve each term or planning item as a standalone object.
8. If a later Sally Canoe mapping supersedes one bundled mapping, that superseding mapping is reviewed by a separate `supersession_review` record rather than by reusing the original bundle review.
9. The materialized store and generated projection are lint-clean end to end; renderer-only unit tests may use partial fixtures, but lint cleanliness must be proven by integration/materialization tests.

## 13. Implementation order

Recommended next plan:

1. Add schema support for `DecisionRecord` and `DomainMapping`.
2. Add review model support for mapping bundles, preferably via `ReviewRecord.review_scope`, `bundle_key`, `confirmation_key`, and `target_object_ids`.
3. Add lint guards for dangling mapping links, review-needed decisions, and projection source hashes.
4. Update context projection to read reviewed mappings plus related glossary terms.
5. Add a Sally Canoe mapping fixture/update script using the already ingested evidence and `bundle.sally-canoe.domain-mapping`.
6. Add update-ingest tests for a Jira/Slack decision that is not reflected in a spec revision.
7. Revisit generic ingest automation only after the mapping lifecycle is proven.
