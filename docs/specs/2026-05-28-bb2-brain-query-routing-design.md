---
title: BB2 Brain Query Routing Design
date: 2026-05-28
status: draft-for-review
scope: query-routing
depends_on:
  - docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md
  - docs/superpowers/specs/2026-05-28-bb2-brain-storage-layout-design.md
---

# BB2 Brain Query Routing Design

## 1. Purpose

This spec defines the P0 query routing behavior for BB2 Brain.

The object model defines what can be stored. The storage layout defines where canonical objects, views, and indexes live. This routing spec defines which Brain objects are read first for each question type, how candidate discovery is separated from answer verification, and which answer status label must be shown.

The P0 goal is deterministic, inspectable routing. Vector search, cross-encoder reranking, and learned weight tuning are deliberately excluded from this spec.

## 2. Scope

### Included

- Query intent classes.
- Intent-specific first-source order.
- Lookup priority for `CurrentView`, `TemporalFact`, `EventLedgerRecord`, `EvidenceRef`, `CodeLocator`, `DomainContext`, and `GlossaryTerm`.
- The role of `IndexRecord` as candidate discovery only.
- Answer status labels: `reviewed`, `candidate`, `raw-only`, `restricted`, `raw-unavailable`.
- Stage clear token acceptance behavior.

### Excluded

- Vector index weighting.
- Cross-encoder or reranker behavior.
- Natural-language query rewriting beyond simple term normalization.
- Slack/Jira connector implementation.
- ACL redaction implementation.
- PPT slide diff extraction.
- Review UI.

## 3. Decision

Use an object-priority deterministic router.

Rejected alternatives:

| Alternative | Rejection reason |
|---|---|
| Index-weighted hybrid router | Too early for P0. It would hide answer behavior behind score tuning before object truth and status labels are stable. |
| CurrentView-only answer path | Fast, but it would make summaries look like truth and weaken provenance, as-of, and "why changed" answers. |
| Full multi-arm retrieval with vector and reranker | Useful later, but P0 needs deterministic source priority and failure labels first. |

Recommended P0 behavior:

```text
question
  -> normalize domain terms
  -> classify intent
  -> discover candidates from CurrentView and indexes
  -> load canonical source objects
  -> verify review/evidence/raw availability
  -> answer with status label and citations
```

`IndexRecord` may decide which object IDs to inspect first. It must not be cited as final evidence. Final answers cite source objects and their `EvidenceRef` / `EvidenceManifest` chain.

This spec separates two orders:

- **Read order**: what the router opens first to find candidate object IDs quickly.
- **Truth order**: what the router may use as final answer evidence after loading source objects.

`CurrentView` and `IndexRecord` are read-order accelerators. `TemporalFact`, `EventLedgerRecord`, `EvidenceRef`, `ReviewRecord`, `EvidenceManifest`, `CodeLocator`, `DomainContext`, and `GlossaryTerm` determine final truth and status.

## 4. Routing preflight

Every query runs a small preflight before intent routing.

1. Normalize domain terms with `DomainContext` and `GlossaryTerm` when the query contains known or avoided terms.
2. Preserve the user's wording in the answer when useful, but answer with canonical terms.
3. If a term is explicitly avoided in the relevant context, route through the canonical term and mention the correction only when it affects the answer.
4. Use `IndexRecord` only to find candidate object IDs. The router must load the source object before trusting the hit.
5. (G11c) The normalized canonical query is actually passed to the fact/scope/glossary routing helpers (`answer()` injects `canonical = canonical_query` into those calls). The user-facing `query` in the output is preserved raw (rule 2). When an avoided term is corrected, the correction is disclosed in warnings (rule 3, `용어 보정 적용: ...`).

For the stage clear token context:

- `스테이지 클리어 토큰` is the feature context term.
- `입장팝업` is the canonical term.
- `시작팝업` routes to `입장팝업`.
- `컨티뉴 팝업` is a direct token-usable UI and must not be widened to every continue popup family.
- `이벤트 클러스터` is entrance popup event display UI history, not a functional sub-feature of stage clear token.

If a query uses an avoided term, the router still uses the canonical term internally. The answer mentions the correction only when the avoided term would otherwise change the scope or cause ambiguity.

## 5. Intent classes

| Intent | Example question | Primary answer shape |
|---|---|---|
| Current status | "지금 QA 기준이 뭐야?", "현재 구현 상태가 뭐야?" | Current reviewed state plus status label. |
| Why changed | "왜 바뀌었어?", "이 결정 이유가 뭐야?" | Change events, causal notes, and evidence chain. |
| As-of history | "그때는 뭐였어?", "5.5 당시 규칙은?" | Time-windowed facts and supersession chain. |
| Implementation location | "어디 구현돼 있어?", "어느 함수 봐야 해?" | Verified code locators plus drift warning when needed. |
| Glossary meaning | "입장팝업이 무슨 뜻이야?" | Glossary definition and boundary. |
| Evidence provenance | "근거가 뭐야?", "누가 확정했어?" | Evidence refs, manifests, review records, source object chain. |

Mixed intent is handled by decomposition. The router should answer rationale before current state when both are present, even if the user phrase puts current state first. For example, "왜 바뀌었고 지금 QA 기준은 뭐야?" runs `why changed` first for change history and `current status` second for current rules. The answer must keep "why" and "current" separate.

## 6. First-source order by intent

### 6.1 Current status

Use when the user asks what is true now.

Read order:

1. `CurrentView` with matching `view_type`, such as `feature_status` or `qa_status`.
2. Reviewed `TemporalFact` records with matching subject/scope and open `valid_until`.
3. Reviewed `EventLedgerRecord` records that produced or recently changed those facts.
4. Related `CodeLocator` only when implementation status is part of the question.
5. `EvidenceRef` chain for citations.

Truth order:

1. Reviewed `TemporalFact`.
2. Reviewed `EventLedgerRecord` that produced or changed the fact.
3. `EvidenceRef` / `EvidenceManifest`.
4. `CodeLocator` when the claim is about implementation location.
5. `CurrentView` only as a synthesis of already verified source object IDs.

Rules:

- `CurrentView` is a summary map, not independent truth.
- If `CurrentView` and reviewed facts disagree, prefer reviewed `TemporalFact` and mark the view stale.
- If no matching `CurrentView` exists, continue with reviewed `TemporalFact` lookup. Do not broaden to unrelated `view_type` values unless they share source object IDs with the matched feature or scope.
- Candidate facts can be mentioned only under `candidate`.

### 6.2 Why changed

Use when the user asks for rationale, cause, clarification, or decision history.

Read order:

1. Reviewed `EventLedgerRecord` with event types such as `spec_revised`, `spec_clarified`, `decision_made`, `bug_reported`, `qa_result`, `review_comment`, or `domain_term_added`.
2. `TemporalFact` supersession chain connected to those events.
3. `EvidenceRef` records for the exact spec slide, Slack/Jira message, session turn, or code locator.
4. `EvidenceManifest` availability and redaction status.
5. `CurrentView` only as a final summary, not as the cause.

Rules:

- Do not collapse "source spec said X" and "later clarification changed Y" into one undifferentiated answer.
- If a cause is inferred from multiple events rather than directly stated, label it as an inference.
- `qa_result` is used as rationale only when it records a failed/changed expectation that caused a later rule or implementation change. Otherwise it is supporting context, not the cause.
- If only raw evidence exists and no reviewed event exists, answer as `raw-only`.

### 6.3 As-of history

Use when the user asks what was true at a date, release, spec revision, or previous state.

Read order:

1. `TemporalFact` filtered by scope first, then by `valid_from <= as_of` and `valid_until` empty or after `as_of`.
2. `TemporalFact.supersedes` chain for before/after comparison.
3. `EventLedgerRecord.happened_at` near the relevant transition.
4. `EvidenceRef` chain for the fact and transition event.
5. `CurrentView` only if it is materialized for the requested `as_of`; otherwise do not use current views for historical truth.

Rules:

- `created_at` and index build time are not domain truth time.
- If the query says "5.5 기준", release scope must be part of the fact filter.
- Scope filters are conjunctive for dimensions the query or matched context supplies: `project`, `release`, `feature`, `surface`, `platform`, and `module`.
- The router may infer `project = "bb2-client"` from repository context and may infer `feature` or `surface` from a matched `GlossaryTerm` only when the context map has a single matching leaf. It must state the inferred scope in the answer when that scope affects the result.
- (G11b) feature/surface 추론은 matched `GlossaryTerm.scope_hint`로 수행한다. 한 leaf가 복수 surface를 묶는 경우 "single matching leaf" 가드만으론 surface granularity가 부족하므로, leaf 단위 대신 term별 `scope_hint`를 source로 쓴다. 추론이 결과를 좁힐 때(다른 값을 가진 fact를 배제할 때)만 그 사실을 답변에 공시한다.
- If release, surface, or platform changes the likely answer and the query does not specify it, ask a clarification instead of silently picking one.
- If the requested time is ambiguous, state the assumed `as_of` in the answer.

### 6.4 Implementation location

Use when the user asks where code lives or what implementation anchor backs a claim.

Read order:

1. `CodeLocator` records matching path, symbol, feature, or domain term.
2. Related reviewed `EventLedgerRecord` or `TemporalFact` explaining why that code is relevant.
3. `EvidenceRef` with `ref_type = "code_locator"`.
4. `CommitRef` or `PRRef` when available.
5. `IndexRecord` from `code_locator` index only for candidate discovery.

Rules:

- A `CodeLocator` is a pointer, not the code truth itself.
- If `commit_sha` is missing, the answer must warn that line numbers can drift.
- If `commit_sha` is present but differs from the current working `HEAD`, the answer must identify the locator commit and treat current-line accuracy as unverified unless code is rechecked.
- If code is not verified, use `candidate` rather than `reviewed`.

### 6.5 Glossary meaning

Use when the user asks what a term means or when the term affects routing.

Read order:

1. `DomainContext` for the relevant context path.
2. `GlossaryTerm` for canonical term, synonyms, avoided terms, and related terms.
3. `EvidenceRef` with `ref_type = "context_term"` when available.
4. Related `TemporalFact` or `EventLedgerRecord` only if the user asks behavior or history.

Rules:

- `CONTEXT.md` remains glossary-only.
- Code anchors and owner paths belong in `INVENTORY.md`, evidence, or `CodeLocator`, not in glossary definitions.
- If the term is a candidate in `INVENTORY.md` but not promoted to `CONTEXT.md`, do not present it as canonical vocabulary.

### 6.6 Evidence provenance

Use when the user asks for source, approval, citation, or confidence.

Read order:

1. Source object being defended: `TemporalFact`, `EventLedgerRecord`, `CodeLocator`, or `GlossaryTerm`.
2. `ReviewRecord` for approval state.
3. `EvidenceRef` records attached to the source object.
4. `EvidenceManifest` for raw locator, sensitivity, ACL, and redaction state.
5. Raw bundle only when permitted.

Rules:

- If evidence exists but is restricted, answer with `restricted`.
- If a reviewed object exists but the raw bundle is unavailable, answer the reviewed claim and mark evidence as `raw-unavailable`.
- If no `EvidenceRef` exists, do not fabricate provenance.
- If the user asks for provenance of a `CurrentView`, defend the view by following `source_fact_ids` and `source_event_ids` to their source objects. Do not defend the view summary as independent truth.

## 7. Candidate discovery layer

P0 candidate discovery can use these projections:

| Projection | Use | Cannot do |
|---|---|---|
| `CurrentView` | Fast entry point for current feature or QA status. | Cannot override reviewed facts. |
| `IndexRecord` `fts` | Keyword lookup for object titles, summaries, terms, Jira keys, PR numbers, and symbols. | Cannot be cited as evidence. |
| `IndexRecord` `timeline` | Candidate events and facts by `happened_at`, `valid_from`, and `valid_until`. | Cannot define as-of truth without loading facts. |
| `IndexRecord` `entity` | Candidate terms, features, actors, Jira keys, PRs, and event names. | Cannot canonicalize vocabulary without `GlossaryTerm`. |
| `IndexRecord` `code_locator` | Candidate code pointers. | Cannot prove implementation relevance without `CodeLocator` and related objects. |

The router may read indexes first for speed, but every answer path must return to canonical source objects before producing claims.

## 8. Answer status labels

Every answer must carry one top-level status label and may label individual claims when mixed evidence exists.

| Label | Meaning | Answer behavior |
|---|---|---|
| `reviewed` | The claim is backed by reviewed Brain objects and usable evidence refs. | State normally and cite source objects. |
| `candidate` | The claim comes from unreviewed candidate objects or unverified code locators. | State as provisional; do not present as settled truth. |
| `raw-only` | Raw evidence or citation refs exist, but no reviewed fact/event has promoted the claim. | Summarize cautiously and say it has not been reviewed. |
| `restricted` | Evidence exists but ACL or redaction status prevents showing it. | State only allowed metadata and say the evidence is restricted. |
| `raw-unavailable` | Reviewed object exists, but raw bundle or approved citation is missing. | State the reviewed claim, but disclose missing raw citation. |

Top-level status is the most severe status among the material claims required to answer the question. Incidental side notes do not change the top-level label unless they are necessary to the answer.

Status precedence for a single answer:

```text
restricted > raw-unavailable > candidate > raw-only > reviewed
```

This precedence is conservative:

- `restricted` is most severe because the router knows evidence exists but cannot show it.
- `raw-unavailable` means a reviewed object exists, but the raw or approved bundle needed for audit is missing.
- `candidate` means Brain has an extracted object but it has not passed review.
- `raw-only` means the router can point at raw evidence, but no reviewed Brain object has promoted it yet.
- `reviewed` means all material claims are backed by reviewed objects and usable evidence refs.

If one material claim is restricted or raw-unavailable, the answer should not present the whole response as cleanly reviewed without calling out that claim.

## 9. Failure and fallback behavior

| Failure | Behavior |
|---|---|
| No index available | Scan canonical objects more slowly. Do not downgrade status only because the index is missing. |
| Stale index hash | Use index for discovery only after loading source objects; report stale index only if it affects answer completeness. |
| Stale current view | Prefer reviewed `TemporalFact` / `EventLedgerRecord` and mark view stale. |
| Missing raw bundle | Use `raw-unavailable` if reviewed object exists; otherwise do not cite it. |
| No matching intent | Run glossary preflight, then search `entity` and `fts` indexes for candidate source objects. If no defended source object is found, ask a concise clarification instead of entering evidence-provenance routing with an empty source. |
| Conflicting reviewed facts | (A) Prefer an explicitly linked `supersedes` chain. (C) If no supersession resolves it, answer with conflict details instead of choosing silently. Scope-based narrowing ("the fact whose full scope matches more query dimensions") is NOT a conflict-resolution step here — it is done upstream by §7 candidate discovery's conjunctive scope filter (`_scoped_facts`). Facts that reach conflict resolution have already matched the query's scope dimensions equally, so re-scoring scope is a dead step (see note below). Never assume a narrower scope overrides a broader scope unless the `supersedes` chain says so. |

- 註(충돌 해소 사다리, 런타임 ⑤): 위 표대로 supersedes(A) → conflict report(C) 2단계만 둔다. "scope가 query 차원을 더 많이 매칭하는 fact 선택"은 충돌 해소 단계가 아니라 §7 candidate discovery의 conjunctive scope filter(`_scoped_facts`)가 candidate 단계에서 수행한다 — `_current_facts`로 들어온 fact는 이미 query 차원을 동일 만족하므로, 해소 단계에서 scope를 재채점하면 항상 동점이 되는 dead step이기 때문이다. (구현: `_conflicting_fact_groups` + `_resolve_current_conflicts`, plan `2026-06-01-bb2-brain-g5-conflict-resolution.md`.)
- Rejected alternative: fact 종류별 차등 해소 / membase식 recency-priority(최신 `valid_from` 자동 선택). 최신성은 `supersedes`/`valid_until`이 담당하며 별도 휴리스틱은 "silent overwrite 금지"(object-model L298)를 위반하고 결정론을 깎는다. Phase 3a 실데이터 충돌 노이즈가 관측되면 재방문.

## 10. Stage clear token acceptance slice

Acceptance question:

> 5.5 기준 입장팝업의 요정의 선물/해피블록 표시가 왜 `drawEventCluster` 형태로 바뀌었고, 현재 QA 기준 동작은 뭐야?

The router must decompose this into two intents:

1. `why changed`
2. `current status`

Expected route:

1. Preflight Brain glossary objects:
   - Load matching `DomainContext(context_key="stage-clear-token")`.
   - Load reviewed `GlossaryTerm` objects for `입장팝업`, `이벤트 클러스터`, `스테이지 클리어 토큰`, and `컨티뉴 팝업` when direct token-usable UI surfaces are relevant.
   - Do not read glossary terms from `docs/contexts/stage-clear-token/CONTEXT.md`.
2. Treat `요정의 선물` and `해피블록` as event display candidates in this slice, not as standalone main contexts.
3. For "why changed", load reviewed `EventLedgerRecord` records for UI-space pressure, event display reorganization, and spec/Slack clarification.
4. Load `EvidenceRef` records for relevant spec slides, Slack/session clarification, and code locator evidence.
5. For "current QA 기준", load reviewed `TemporalFact` records for current UI display rules in release 5.5 scope.
6. Load `CodeLocator` records for entrance popup and event cluster implementation anchors only after the behavior facts are identified.
7. Use `CurrentView` to summarize current feature or QA state, but verify it against the loaded facts.
8. Answer with separate sections for "변경 이유" and "현재 기준".
9. Attach status labels. The expected passing status is `reviewed`; if Slack/spec evidence is not review-promoted, the answer must downgrade the affected claims to `raw-only` or `candidate`.

Acceptance criteria:

- The answer does not use `시작팝업` as the canonical term.
- The answer distinguishes `이벤트 클러스터` UI history from the stage clear token feature itself.
- The answer does not promote `요정의 선물` or `해피블록` into standalone main contexts.
- The answer separates current rules from change rationale.
- The answer separates original spec evidence from later clarification evidence.
- The answer cites source objects, not index hits.
- The answer warns about `CodeLocator` line drift when no `commit_sha` exists, and marks current-line accuracy unverified when the locator commit differs from current `HEAD`.
- The answer uses `raw-unavailable` when a reviewed object exists but its raw bundle or approved citation cannot be loaded.
- The answer can still work when indexes are deleted by scanning canonical objects.

## 11. Decisions closed by this spec

| Decision | Result |
|---|---|
| P0 routing style | Object-priority deterministic routing. |
| Index role | Candidate discovery only; never final evidence. |
| First-source policy | Intent-specific source order with canonical object verification. |
| Mixed intent handling | Decompose and answer each intent separately. |
| Status labels | `reviewed`, `candidate`, `raw-only`, `restricted`, `raw-unavailable`. |
| CurrentView role | Fast current summary; stale if it conflicts with reviewed facts. |
| As-of basis | `TemporalFact.valid_from` / `valid_until`, not object creation or index time. |

## 12. Deferred decisions

| Decision | Why deferred |
|---|---|
| Vector retrieval weights | Requires prototype data and retrieval evaluation. |
| Cross-encoder reranking | P0 must first stabilize deterministic source order and labels. |
| Query rewrite | Needs observed query corpus. |
| SQLite projection schema | Belongs to implementation plan after object file encoding is chosen. |
| ACL enforcement | Needs separate privacy/redaction policy. |
| Review UI | Needs PoC operation feedback. |

## 13. Self-review notes

- This spec keeps `IndexRecord` as candidate discovery and returns to source objects for verification.
- It does not require vector search, learned weights, or reranking in P0.
- It preserves `CONTEXT.md` as glossary-only.
- It keeps the stage clear token slice focused on entrance popup event display history and current UI rules.
