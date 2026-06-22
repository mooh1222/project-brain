---
title: BB2 Brain Universal Ingest Design
date: 2026-06-04
scope: universal-ingest
status: draft-for-review
related:
  - docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md
  - docs/superpowers/specs/2026-06-02-bb2-brain-domain-mapping-lifecycle-design.md
  - docs/superpowers/specs/2026-06-02-bb2-brain-domain-context-v2-design.md
  - docs/superpowers/specs/2026-06-02-bb2-brain-sally-canoe-real-ingest-design.md
---

# BB2 Brain Universal Ingest Design

## 1. Purpose, scope, non-goals

### 1.1 Purpose

Today, putting objects into the Brain store is done by per-domain hand-written
scripts (`ingest_sally_canoe_source.py`, `ingest_sally_canoe_mappings.py`,
`seed_first_slice.py`, `seed_sally_canoe_domain_v2.py`). Each script bakes in
domain knowledge: which terms exist, which mappings to build, which evidence to
cite, and which ids to promote. (The one exception is
`seed_sally_canoe_domain_v2.py`, which holds no assembly of its own — it just
delegates to `ingest_sally_canoe_source.py`; see §5.) That does not scale, and it
forces every new source to copy a script.

This spec defines a **domain-agnostic ingest infrastructure**: a small set of
reusable code parts that take objects an agent already extracted and persist them
with full schema and link-integrity checks. The code never knows what a "race
status" or a "cooldown" is. The act of reading a source (spec PPT, code, Slack,
session, insight) and turning it into Brain objects is done by an **agent in a
session**, not by code.

### 1.2 Scope (this slice)

1. A single ingest entry point `ingest(objects)` that takes a bundle of objects
   plus their cross-links and runs: per-object schema validation, whole-bundle
   link-integrity lint, then store write — as one operation. Also exposed as a
   CLI subcommand.
2. A domain-agnostic `promote(ids, scope)` that lifts `candidate` objects to
   `reviewed`: status transition, candidate-metadata removal, and `ReviewRecord`
   creation. Two modes: `single_object` and `mapping_bundle`.
3. Shared helpers: `ReviewRecord` construction and `base()` default-field
   assembly, factored out of the scripts that currently duplicate them (`base()`
   is duplicated in three scripts — see §3.3).
4. Deprecation of the four per-domain scripts above, after their reusable work
   (object assembly, promotion, `ReviewRecord` creation) is absorbed into the
   parts above.

### 1.3 Non-goals

- **Source extraction is out of scope.** Reading a source and producing the
  object bundle is the agent's job. Wrapping that procedure as a reusable
  *agent procedure* (a skill) is explicitly a **follow-up**, not part of this
  spec. This spec defines the code that receives an already-extracted bundle.
- **Connector automation is out of scope.** This does not auto-parse Slack/Jira/
  code into objects. That stays consistent with domain-context-v2
  §9 (`docs/superpowers/specs/2026-06-02-bb2-brain-domain-context-v2-design.md:328`,
  "Do not build full Slack/Jira/code connector automation"). The ingest entry
  point receives a manually/agent-captured bundle, not a live connector pull.
- **Update ingest (amend / supersede) is out of scope** for this slice — see
  §5.3. This slice covers only **initial ingest plus promotion**.
- No new object kind. `mapping_bundle` review continues to be expressed on
  `ReviewRecord` (`review_scope = "mapping_bundle"`), not a new `ReviewBundle`
  kind, per mapping-lifecycle §6.1
  (`docs/superpowers/specs/2026-06-02-bb2-brain-domain-mapping-lifecycle-design.md:261`).
- No `DomainTermProposal` kind; candidate metadata stays sufficient
  (domain-context-v2 §9, line 330).

## 2. Current reusable parts (verified inventory)

These parts already exist and are reused as-is. File:line confirmed by reading.

| Part | Location | What it does | Reuse role |
|---|---|---|---|
| `BrainStore.save_object` | `scripts/bb2_brain/store.py:57-68` | Runs `validate_object` on one object, then `write_text` to `<kind-dir>/<id>.json`. `write_text` overwrites the same id. No bundle/link check. | Per-object write step of `ingest`. Overwrite behavior is the basis of decision (a) idempotent update (§5.1). |
| `BrainStore(objects)` ctor + `.load/.get/.has/.by_kind/.all` | `scripts/bb2_brain/store.py:8-33` | In-memory object map; `load` is disk `rglob`. | `ingest` builds a merged in-memory `BrainStore` (existing `all()` + new objects) to run lint before writing (§3.1). |
| `validate_object` | `scripts/bb2_brain/schema.py:109-223` | Per-object schema/enum validation for 18 kinds. | Step 1 of `ingest`; also called inside `save_object`. |
| `lint_store` | `scripts/bb2_brain/lint.py:79-219` | Whole-store integrity: dangling `evidence_refs`/`review_record_id` (4), DomainMapping link dangling 8a, DecisionRecord link dangling 8b, ReviewRecord `target_object_id`/`target_object_ids` dangling 8e, plus conflict/projection guards. | Step 2 of `ingest` — strict bundle integrity gate (§5.2). |
| `_conflicting_fact_groups` | `scripts/bb2_brain/router.py:11-28` (reused by `lint.py:9,88`) | Pure conflict-group detector. | Reused transitively via `lint_store`; ingest does not re-implement conflict detection. |
| `claim_status` | `scripts/bb2_brain/status.py:10-25` | Maps object status + raw availability to a claim status. | Read-side only; ingest does not call it, but the `candidate`/`reviewed` distinction it reads is what `promote` produces. |
| `QueryRouter.answer` + `cli.py` | `scripts/bb2_brain/router.py`, `scripts/bb2_brain/cli.py` | Query-only. `cli.py:9-23` parses `--brain-root` + `query` and prints an answer. **No ingest/promote subcommand exists today** (verified: `cli.py` has only the query path). | The acceptance recall query (§7) runs through this unchanged. |

## 3. New parts

### 3.1 `ingest(objects)` — single ingest entry point

**Input.** A list of fully-formed Brain object dicts (the bundle). Each object
already carries its `id`, `kind`, links (`evidence_refs`, `glossary_term_ids`,
`decision_record_ids`, `target_object_ids`, …) and any `candidate` metadata. The
agent produced these in-session; `ingest` does not invent or infer fields.

**Order — validate, then integrity, then store, as one operation:**

1. **Per-object schema validation.** For every object in the bundle, run
   `validate_object` (`schema.py:109`). If any object reports errors, abort the
   whole bundle (nothing is written). This is the same check `save_object` runs
   per object, run up front for the whole bundle so a bad object never reaches
   disk.
2. **Whole-bundle link integrity.** Build a merged in-memory store from the
   existing on-disk objects (`BrainStore.load(brain_root).all()`) plus the new
   bundle, construct a `BrainStore(objects)` from the merged map, and run
   `lint_store` on it. If `lint_store` returns any problem, abort the whole
   bundle. This is where orphan/dangling references are caught: a mapping that
   points at a `glossary_term_id` not present in either the existing store or the
   bundle is rejected before any write. (`BrainStore(objects)` ctor exists at
   `store.py:8`, so merging is mechanical; assembling the merged map is the new
   code.) **`ingest` calls `lint_store(store)` without `workspace_root`** — i.e.
   reference/link integrity only. `lint_store` skips the generated-projection-file
   checks when `workspace_root is None` (`lint.py:138-139`, `lint.py:216-217`), so
   ingest does not gate on projection-file drift. This is consistent with §4.2 not
   newly enabling the deferred projection guard.
3. **Store write.** Only after 1 and 2 pass, call `BrainStore.save_object` for
   each object in the bundle (`store.py:57`).

**Status is the bundle's, not ingest's.** `ingest` writes each object with
whatever `status` it carries (`candidate` or `reviewed`); it never invents or
flips status. This is what lets the direct-`reviewed` seed form (§5,
`seed_first_slice.py`) pass through `ingest` alone with no `promote` step — the
agent hands `ingest` an already-`reviewed` bundle and ingest preserves it. The
only status comparison ingest ever makes is the demotion guard in §4.1 (reject
`reviewed`→`candidate` for an existing id); it never sets status itself.

**Atomicity.** Validation and integrity are checked *before* any write, so a
bundle that fails either gate writes nothing. Within step 3, `save_object`
writes per file; this spec does not add multi-file rollback (no current part
provides it, and the strict pre-write gates make a partial write require an I/O
failure mid-loop, not a logic error). If stronger write atomicity is later
needed it is a separate concern.

**CLI subcommand.** Expose ingest as a Brain CLI subcommand that reads a bundle
(objects as JSON) and a `--brain-root`, then runs the flow above. `cli.py` today
is query-only (`cli.py:9-23`); adding an ingest subcommand is new wiring. The
exact CLI shape (argument names, JSON-on-stdin vs file) is an implementation
detail for the plan; the contract is "feed a validated bundle, get all-or-nothing
ingest."

### 3.2 `promote(ids, scope)` — domain-agnostic promotion

`promote` lifts `candidate` objects to `reviewed`. It is the generic version of
`build_reviewed_terms` (source.py) and the `bundle_confirmed` toggle
(mappings.py). It takes the ids to promote and a `scope`.

> **Note (2026-06-04):** the absorbed scripts were removed in commit
> `1af5b69ef9` (deprecation done first). The `file:line` citations in §3.2/§3.3/§5
> refer to **pre-removal** code — read the original with
> `git show 1af5b69ef9^:scripts/bb2_brain/<file>`. Each absorbed behavior is also
> described in prose here, so this spec stays self-contained without the files.

**Mode `single_object`** — absorbs `build_reviewed_terms`
(`ingest_sally_canoe_source.py:370-397`). For each id in `ids`:

- Copy the object, set `status = "reviewed"`, refresh `updated_at`.
- Remove the entire `candidate` key (`reviewed.pop("candidate", None)`), not
  individual candidate fields. This is required: schema rejects a `reviewed`
  GlossaryTerm that keeps `candidate_state == "conflict"` or unresolved
  `open_questions` (`schema.py:173-177`; the same check is duplicated in lint at
  `lint.py:118-120`).
- Assign `review_record_id` (id rule `"review." + id`).
- Build one paired `ReviewRecord` per object with `truth_role = "review"`,
  `verdict = "approved"`, `target_object_id = <promoted id>` (singular), and
  `evidence_refs` copied from the promoted object. `review_scope` may be left
  unset — schema treats it as `single_object` and requires `target_object_id`
  (`schema.py:213-222`). The ReviewRecord must also carry `reviewer` and
  `reviewed_at`: both are schema-required for every ReviewRecord
  (`KIND_REQUIRED["ReviewRecord"] = ("reviewer", "reviewed_at", "verdict")`,
  `schema.py:14`), and the absorbed `build_reviewed_terms` sets them
  (`reviewer = "user-confirmed"`, `reviewed_at = T_REVIEW`, `source.py:392-393`).
  Whether the value comes from the caller/agent or a default is a plan decision;
  the fields must be present or `validate_object` rejects the record.

Note: the source script also rewrites `title` to a fixed `"Reviewed term: "`
prefix (`source.py:379`). That string is GlossaryTerm-specific. The generic
`promote` should refresh status/`updated_at`/`review_record_id` and drop
`candidate`, and leave object-kind-specific title wording to the caller/agent
rather than hard-coding a GlossaryTerm phrase. (This is the one place the generic
part is deliberately narrower than the script it absorbs.)

**Mode `mapping_bundle`** — absorbs the `bundle_confirmed=True` path
(`ingest_sally_canoe_mappings.py:102-126`) and `build_bundle_review`
(`mappings.py:180-196`). For the set of mapping ids in `ids`:

- For each mapping: set `status = "reviewed"`, set
  `review_record_id = "review." + <bundle confirmation key>` (all members share
  the one bundle review id), and set `review_state` to the dimensions the bundle
  actually covered. For the Sally Canoe bundle that is
  `{meaning_reviewed, evidence_reviewed, projection_reviewed}` all true;
  `implementation_reviewed` stays absent unless code anchors were separately
  re-verified (mapping-lifecycle §6.1, line 266; matches `mappings.py:125`).
  Concretely, generic `promote` puts only the review dimensions the caller passed
  into the `review_state` dict and leaves the rest as **absent keys** (not
  `false`) — this is the current code behavior (`mappings.py:125` omits
  `implementation_reviewed` from the dict entirely), and schema allows but does
  not require all four `REVIEW_STATE_KEYS` (`schema.py:199-208`). DomainMapping
  has no `candidate` key to drop — only status/title/`review_record_id`/
  `review_state` toggle.
- Build **one** `ReviewRecord` for the bundle: `review_scope = "mapping_bundle"`,
  `review_type = "meaning_review"`, `target_object_ids = <all promoted mapping
  ids>` (plural), `bundle_key` and `confirmation_key` both set to the bundle key.
  Schema enforces that `mapping_bundle` ReviewRecords carry `target_object_ids`
  and `confirmation_key` (`schema.py:216-220`), so `promote` must fill both. As
  with the single-object record, the bundle ReviewRecord must also carry the
  always-required `reviewer` and `reviewed_at` (`schema.py:14`); the absorbed
  `build_bundle_review` sets them (`mappings.py:187-188`). The `confirmation_key`
  names the review operation, not individual mappings (mapping-lifecycle §6.1,
  line 264; example `bundle.sally-canoe.domain-mapping`).

`promote` returns the promoted (reviewed) objects plus the new `ReviewRecord`(s).
The caller then feeds them to `ingest` (so the same validate→integrity→store gate
applies to promotion output).

### 3.3 Shared helpers

- **`base()` default-field assembly.** A near-identical `base()` appears in
  **three** scripts (`ingest_sally_canoe_source.py:34-45`,
  `ingest_sally_canoe_mappings.py:33-44`, `seed_first_slice.py:38-51`), each
  filling `schema_version`, `poc_priority`, `created_at`, `updated_at`, `tags`,
  `evidence_refs` via `setdefault`. They differ in the `tags` last element
  (`real-ingest` vs `domain-mapping` vs `stage-clear-token`/`popup-enter`) and the
  timestamp constant. The shared `base()` takes `tags` and timestamps as caller
  parameters so it covers all three; `setdefault` keeps the existing behavior of
  not overwriting fields the caller already set.
  - **One divergence: `status` default.** The two Sally Canoe `base()`s do **not**
    default `status`, but `seed_first_slice.base()` adds `status = "reviewed"`
    (`seed_first_slice.py:42`) so its objects start `reviewed`. The shared `base()`
    does **not** carry a `status` default — status is the caller's responsibility:
    `promote` sets it explicitly, and the direct-`reviewed` seed form (§5) has the
    agent put `status = "reviewed"` on the bundle objects directly. Leaving
    `status` out of shared `base()` keeps the helper neutral and avoids re-baking
    the seed-only `reviewed` default into a domain-agnostic part.
- **`ReviewRecord` construction.** The `single_object` and `mapping_bundle`
  review objects are assembled inside `promote` via the shared `base()` plus the
  per-mode fields described in §3.2. This factors out the two inline
  `ReviewRecord` literals at `source.py:385-396` and `mappings.py:180-196`.

## 4. Decisions (the three open points)

### 4.1 (a) Idempotent re-ingest, with a reviewed→candidate guard

Re-ingesting the same id is an **idempotent update**: it is allowed and
overwrites the existing object. This follows directly from `save_object` using
`write_text` (`store.py:67`), which already overwrites same-id files.

The one guard: an ingest that would **demote** an object from `reviewed` to
`candidate` is **rejected**. Before writing, ingest reads the on-disk object (if
present) and, if the existing status is `reviewed` and the incoming status is
`candidate` for the same id, aborts. **This guard is new code** — it exists
nowhere today (`save_object`/`schema`/`lint` do not compare against prior
on-disk status). It lives in the ingest entry point, not in `save_object`
(`save_object` stays a dumb writer). This is the only "new logic, not absorbed"
item; everything else in §3 is absorbed from existing scripts.

### 4.2 (b) Strict integrity at store time — orphan references rejected

Integrity is checked **immediately before write**, on the merged bundle, and the
bundle is rejected if `lint_store` reports any problem (orphan/dangling
references included). This is strict by design and directly fixes the current
weakness: the scripts' `main()` loops call `save_object` per object with **no
bundle lint** (`source.py:428-429`, `mappings.py:319-320`), so a dangling link
across objects is never caught at ingest time. `lint_store` already detects all
the dangling-link classes ingest cares about — `evidence_refs`/`review_record_id`
(`lint.py:99-105`), DomainMapping links 8a (`lint.py:146-158`), DecisionRecord
links 8b (`lint.py:161-175`), ReviewRecord targets 8e (`lint.py:208-214`) — so
ingest reuses it rather than re-implementing reference checks.

Interaction with the deferred projection guard: mapping-lifecycle §8.3 note
(line 328) allows the "reviewed glossary term has no mapping for projection use"
guard to be deferred if it would make pre-mapping stores lint-dirty. Strict
ingest runs whatever `lint_store` currently enforces; it does not newly enable
that deferred guard. If that guard is later turned on, strict ingest inherits it
automatically.

### 4.3 (c) Initial ingest + promotion only; update ingest is the next slice

This slice covers **initial ingest** (mapping-lifecycle §8.1, line 286-294:
source objects + candidate glossary terms + candidate mappings) and
**promotion** (§3.2). It does **not** cover **update ingest** — the amend /
supersede / keep / review-needed comparison of §8.2 (line 296-305).

Evidence this is the right cut: update-ingest behavior **is not implemented in
code today**. Searching `amend|supersede|supersedes` across the Brain code, every
hit is either (1) a *check* that reports a problem without changing storage
(`lint.py:177-205`, drift 8c and supersession-consistency 8d), (2) a *read-side*
query resolver that walks `supersedes` chains to pick a conflict winner
(`router.py` `_supersedes_*`), or (3) a **test-only** fixture that hand-assembles
objects with a literal `status: "superseded"` and is explicitly **not written by
`main()`** (`ingest_sally_canoe_mappings.py:7-9, 206-309`). `save_object` only
overwrites by id (`store.py:67`); it has no amend/supersede lifecycle. So the
keep/amend/supersede comparison logic does not exist yet — deferring it to the
next slice is faithful to the current code, not an arbitrary narrowing.

## 5. Deprecation plan

Four scripts are deprecated **after** their reusable work is absorbed into the
parts in §3. Absorption map (what moves to which generic part):

| Deprecated script | Reusable work it holds | Absorbed into |
|---|---|---|
| `ingest_sally_canoe_source.py` | `build_reviewed_terms` candidate→reviewed promotion (`:370-397`) | `promote(scope="single_object")` (§3.2) |
| `ingest_sally_canoe_source.py` | per-object save loop + `--confirm-reviewed` id selection (`:419-429`) | `ingest` flow (§3.1) + `promote` `ids` arg (§3.2) |
| `ingest_sally_canoe_source.py` | `base()` defaults (`:34-45`) | shared `base()` helper (§3.3) |
| `ingest_sally_canoe_mappings.py` | `bundle_confirmed` candidate→reviewed mapping toggle (`:102-126`) | `promote(scope="mapping_bundle")` (§3.2) |
| `ingest_sally_canoe_mappings.py` | `build_bundle_review` bundle ReviewRecord (`:180-196`) | `promote(scope="mapping_bundle")` ReviewRecord build (§3.2) |
| `ingest_sally_canoe_mappings.py` | per-object save loop + `--confirm-bundle` (`:312-323`) | `ingest` flow (§3.1) |
| `ingest_sally_canoe_mappings.py` | `base()` defaults (`:33-44`) | shared `base()` helper (§3.3) |
| `seed_first_slice.py` | **already-`reviewed` seed corpus** (stage-clear-token, 58 objects) assembled directly with `base()` default `status="reviewed"` (`:42`) and inline paired ReviewRecords (`:626-636`); no candidate stage | `ingest` alone — see "two deprecation shapes" below; **no `promote`** (nothing is a candidate) |
| `seed_sally_canoe_domain_v2.py` | **none** — pure delegation wrapper that calls `ingest_sally_canoe_source.build_objects`/`main` (`:7-31`), adding only `DEFAULT_CONFIRMATIONS = {race-stage: True}`; no own assembly | nothing to absorb — simple removal alongside the source script it delegates to |

**Two deprecation shapes.** The four scripts are not one shape. Two are
candidate→promote flows; two are not:

1. **candidate→promote form** (`ingest_sally_canoe_source.py`,
   `ingest_sally_canoe_mappings.py`): they build `candidate` objects and then
   promote on confirmation. Their reusable work splits cleanly into `ingest`
   (write) + `promote` (lift), per the table rows above.
2. **direct-`reviewed` seed form** (`seed_first_slice.py`): it assembles objects
   that are already `reviewed` from the start (`base()` defaults `status="reviewed"`,
   `seed_first_slice.py:42`) with ReviewRecords paired inline
   (`seed_first_slice.py:626-636`). There is **no candidate stage**, so there is
   nothing for `promote` to lift. Under the new model the agent assembles a
   `reviewed` bundle and feeds it to `ingest` directly; `ingest` writes whatever
   status the bundle carries (see the status-preserving contract in §3.1). The
   third script, `seed_sally_canoe_domain_v2.py`, holds no assembly at all — it
   just delegates to the source script, so it is removed together with it.

**Deprecation order (updated 2026-06-04):** the four scripts and their bound
tests were **already removed first** (commit `1af5b69ef9`), per the decision to
leave no per-domain code that could mislead the design. The remaining order is:
build the generic parts, then prove Sally Canoe can be re-ingested through them
with no domain script (§7). Absorption targets above are preserved in this spec's
§3 prose and in git history (`git show 1af5b69ef9^:<path>`).

**Resolved (2026-06-04, commit `1af5b69ef9`).** The four scripts and their bound
tests were removed first (per the "no per-domain code left to mislead" decision).
133 tests pass (was 156; 23 script-bound tests removed). The coverage that
mattered is preserved independently — no relocation was needed for it:

1. **drift/supersession lint (8c/8d)** — already covered by `test_lint.py` with
   its own `_mapping()` fixtures (no script import: `test_lint.py:5-7`). The
   script-side duplicates in `test_ingest_sally_canoe_mappings.py` were removed;
   the live lint coverage stays. When the update-ingest slice (§8.2) lands it
   re-creates `build_jira_update_objects`/`build_supersession_objects` as test
   fixtures.
2. **direct-`reviewed` seed corpus** — `test_seed_first_slice.py` was an
   acceptance test for the removed seed script; it is dropped. The generic
   end-to-end re-ingest (§7 AC 2) replaces it once the generic parts exist.
3. **frozen context-projection regression** — independently covered by
   `test_context_projection.py` (no script import), so dropping
   `test_seed_sally_canoe_domain_v2.py` lost no coverage.

Acceptance criterion 2 ("all four deprecated scripts removed or unused") is now
**satisfied**; what remains is proving the generic re-ingest (§7).

## 6. Spec alignment

- **storage-layout §6** (`docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md:148-167`):
  the flow `… -> candidate objects -> ReviewRecord -> reviewed objects` matches
  this slice exactly — `ingest` is the "candidate objects" write, `promote` is
  the "ReviewRecord -> reviewed objects" step. The rule "LLM extraction creates
  candidates, not reviewed truth … review decides promotion" (lines 163, 166) is
  the reason ingest and promote are two separate entry points. No conflict.
- **mapping-lifecycle §8.1** (line 286-294): initial ingest = source objects +
  candidate glossary + candidate mappings, which is this slice's scope. **§8.2**
  (line 296-305) update ingest is explicitly the next slice (§4.3). No conflict.
- **mapping-lifecycle §6.1** (lines 261-268): bundle review uses
  `review_scope = "mapping_bundle"` + `target_object_ids` on `ReviewRecord` (no
  new kind); `confirmation_key` names the operation; mark only covered review
  dimensions. `promote(scope="mapping_bundle")` follows all of these. No
  conflict.
- **domain-context-v2 §9** (line 325-331): no prompt injection, no connector
  automation, no `DomainTermProposal`. Universal ingest receives an
  agent-extracted bundle (not a connector pull) and adds no new kind, so it does
  not violate any non-goal. No conflict.

**Opening the deferred item.** mapping-lifecycle §13 implementation order item 7
(`docs/superpowers/specs/2026-06-02-bb2-brain-domain-mapping-lifecycle-design.md:409`,
"Revisit generic ingest automation only after the mapping lifecycle is proven")
deferred generic ingest. The mapping lifecycle is now proven (items 1-6 of §13
are implemented; the Sally Canoe bundle was promoted and lint-clean). **This spec
formally opens §13 item 7.**

**Existing specs that need a follow-up edit** (not changed by this spec, listed
so the plan can do them):

- mapping-lifecycle §13 item 7 should be annotated as "opened by the
  universal-ingest spec (2026-06-04)" once this is accepted.
- storage-layout §6 and mapping-lifecycle §8 may add a back-reference noting the
  ingest/promote flow is now realized by generic `ingest`/`promote` rather than
  per-domain scripts.

These edits are documentation cross-links, deliberately left out of this slice's
code scope.

## 7. Acceptance criteria

1. **Generic parts exist and are domain-agnostic.** `ingest(objects)` and
   `promote(ids, scope)` contain no Sally-Canoe (or any domain) constants —
   verifiable by grepping the new modules for term/mapping ids.
2. **End-to-end re-ingest with no domain script.** Sally Canoe is re-ingested
   using only the generic `ingest`/`promote` (plus an agent-supplied object
   bundle) — the four scripts are already removed (commit `1af5b69ef9`) —
   producing the same candidate glossary/mappings and the promoted reviewed
   mappings under `bundle.sally-canoe.domain-mapping`.
3. **Strict integrity proven.** A bundle with a dangling link (e.g. a mapping
   citing a glossary term id absent from both store and bundle) is rejected by
   `ingest` and writes nothing.
4. **Idempotent + guard proven.** Re-ingesting an unchanged id is a no-op-by-
   content overwrite (succeeds); an ingest that would demote a `reviewed` object
   to `candidate` for the same id is rejected.
5. **Lint clean after ingest.** After the full re-ingest, `lint_store` returns
   no problems for the materialized store.
6. **Recall through CLI.** A Sally Canoe domain query through `cli.py`
   (unchanged query path) recalls the reviewed mapping/term — proving the
   generic-ingested store answers identically to the script-ingested store.

## 8. Follow-ups (named, out of scope)

- **Extraction skill.** Wrap the agent's source→object-bundle procedure as a
  reusable skill (the §1.3 "follow-up"). This is an agent procedure, not code.
- **Update ingest slice.** Implement §8.2 keep/amend/supersede comparison and
  wire the deprecated scripts' drift fixtures into the new model (§4.3, §5).
- **Spec cross-link edits.** Annotate mapping-lifecycle §13 item 7 as opened and
  add back-references in storage-layout §6 / mapping-lifecycle §8 (§6).
