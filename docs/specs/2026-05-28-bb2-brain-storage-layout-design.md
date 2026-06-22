---
title: BB2 Brain Storage Layout Design
date: 2026-05-28
status: draft-for-review
scope: storage-layout
depends_on:
  - docs/superpowers/specs/2026-05-27-bb2-brain-object-model-design.md
---

# BB2 Brain Storage Layout Design

## 1. Purpose

This spec defines the v0.1 storage layout for BB2 Brain.

The object model already separates evidence, reviewed ledger, temporal facts, current views, and disposable indexes. This storage spec makes that separation physical so ingest, query, rebuild, and review do not depend on a single mutable wiki page or a fragile vector index.

## 2. Basis / source mapping

This layout is based on three inputs: user interview decisions in the design thread, existing vault research, and prior HTML/report material imported into the vault. External search can add candidate patterns later, but it must not override reviewed local decisions without review.

Key source mappings:

| Source pattern | Local source | Storage implication |
|---|---|---|
| Karpathy LLM Wiki 3-tier: raw sources, wiki, schema | `LLM Wiki 패턴.md` | Raw evidence must be immutable; wiki/current views are maintained synthesis. |
| Karpathy `index.md` + append-only `log.md` | `LLM Wiki 패턴.md` | Keep an append-only timeline plus rebuildable catalog/index views. |
| GBrain markdown as source of truth, DB as retrieval layer | `LLM Wiki 패턴.md` | Treat retrieval DB/indexes as disposable projections, not canonical truth. |
| Sentra episodic + semantic split | `sentra-company-brain-deep-dive.md` | Separate exact event/source history from semantic retrieval structures. |
| Sentra bi-temporal invalidation | `sentra-company-brain-deep-dive.md` | Close old facts with validity timestamps; do not delete or overwrite them. |
| Mnemosyne TripleStore | `mnemosyne-deep-dive.md` | Variable facts use `valid_from` / `valid_until`; as-of views are queryable without snapshots. |
| Mnemosyne AnnotationStore distinction | `mnemosyne-deep-dive.md` | Cumulative annotations are append-only and should not use single-current-truth semantics. |
| MemPalace drawer/closet/KG | `MemPalace 코드 딥다이브.md` | Store raw verbatim chunks separately from topic/entity/date pointers and temporal KG facts. |
| Hindsight multi-arm retrieval | `2026-05-26-hindsight-deep-dive.md` | Query can combine BM25, semantic, graph, and temporal candidates, but answer verification returns to source objects. |
| Brain Vault hash-based BM25 cache | `Brain Vault 설계.md` | Index rebuilds should be content-hash driven in P0. |

## 3. Recommended approach

Use an append-only object store with disposable projections.

The canonical store is a set of immutable or append-only files. `CurrentView`, `KnowledgePage`, SQLite/FTS/vector indexes, and search catalogs are projections. They can be deleted and rebuilt from reviewed objects.

Rejected alternatives:

| Alternative | Rejection reason |
|---|---|
| Wiki page as primary truth | Easy to read, but loses event/fact provenance and makes as-of answers fragile. |
| SQLite-only canonical store | Good for query, but harder to inspect, diff, review, and recover manually during early PoC. |
| Vector DB as primary store | Retrieval quality becomes coupled to index health; prior research treats embedding-only retrieval as a similarity oracle, not memory. |

## 4. Canonical layout

```text
brain/
  raw/
    manifests/
    bundles/
  objects/
    evidence_refs/
    reviews/
    ledger/
    facts/
    specs/
    comms/
    code/
    build/
    sessions/
    domain/
  views/
    current/
    knowledge_pages/
  indexes/
    fts/
    timeline/
    entity/
    code_locator/
    vector/
  manifests/
    object-hashes.json
    index-hashes.json
```

### 4.1 `raw/`

`raw/` contains `EvidenceManifest` files and approved citation bundles.

Rules:

- Raw local sources are never rewritten in place.
- Shared Brain only uses citation bundles with approved redaction status.
- If a source changes, create a new manifest or bundle version instead of mutating the old one.

### 4.2 `objects/`

`objects/` contains canonical Brain objects from the object model.

Rules:

- `EventLedgerRecord` is append-only.
- `TemporalFact` and variable facts close old rows with `valid_until`; they do not overwrite old values.
- Cumulative annotations, mentions, candidate links, and extraction hints are append-only records, not single-current-truth facts.
- Candidate objects can exist, but `CurrentView` may only read reviewed objects.

### 4.3 `views/`

`views/` contains human-readable projections.

Rules:

- `CurrentView` is materialized from reviewed facts and reviewed ledger records.
- `KnowledgePage` is synthesis and must keep `source_object_ids`.
- A stale or contradictory view is rebuilt; it is not treated as independent truth.

### 4.4 `indexes/`

`indexes/` contains retrieval projections.

P0 indexes:

- `fts`: keyword/BM25-style search over object summaries and selected text.
- `timeline`: event time and valid-time lookup.
- `entity`: glossary terms, feature names, Jira keys, PR numbers, code symbols, and actors.
- `code_locator`: code pointer lookup by repo/path/symbol.

P1/P2 indexes:

- `vector`: semantic retrieval.
- graph edges or reranker metadata.

Rules:

- Indexes can be deleted and rebuilt from `objects/` and approved `raw/` bundles.
- Every `IndexRecord` stores `source_object_id` and `content_hash`.
- Query answers must cite source objects, not index hits.

## 5. Time model

Storage must preserve three time axes:

| Field family | Meaning | Example use |
|---|---|---|
| `created_at` / `updated_at` | Brain object storage lifecycle | When Brain stored or edited the object. |
| `happened_at` | Event ledger occurrence time | When a Slack clarification, QA result, build result, or implementation event happened. |
| `valid_from` / `valid_until` | Domain truth validity window | Which rule was true for release 5.5 at a given time. |

`as_of` query uses `valid_from` / `valid_until` for facts, not the index build time. Recency ranking, if added later, is a separate retrieval boost and must not rewrite validity.

## 6. Ingest flow

```text
source capture
  -> EvidenceManifest
  -> EvidenceRef
  -> candidate EventLedgerRecord / TemporalFact / CodeLocator / GlossaryTerm
  -> ReviewRecord
  -> reviewed objects
  -> CurrentView rebuild
  -> index rebuild/update
```

Rules:

- LLM extraction creates candidates, not reviewed truth.
- Deterministic extraction is preferred when source structure is stable, such as markdown headings, Jira keys, PR numbers, code locators, and Brain reviewed vocabulary objects.
- Existing context/wiki pages can seed candidates as legacy migration hints, but reviewed vocabulary promotion must cite primary spec/session/code/Slack/Jira evidence.
- LLM extraction is allowed for summaries, proposed links, and ambiguity detection, but review decides promotion.
- Failed or rejected candidates remain auditable or are archived according to retention policy; they do not enter current views.

## 7. Query flow

```text
question
  -> route by intent
  -> retrieve candidates from indexes/current views
  -> load source Brain objects
  -> verify evidence/ledger/fact status
  -> answer with reviewed/candidate/raw-only labels and citations
```

Intent routing in P0:

| Query intent | First source |
|---|---|
| "지금 뭐야?" | `CurrentView` + valid reviewed `TemporalFact` |
| "왜 바뀌었어?" | `EventLedgerRecord` + `EvidenceRef` |
| "그때는 뭐였어?" | `TemporalFact` as-of query |
| "어디 구현돼 있어?" | `CodeLocator` + related event/fact |
| "이 용어 무슨 뜻이야?" | `DomainContext` + `GlossaryTerm` |

Indexes can find candidates quickly, but the final answer must verify against the loaded source objects.

## 8. Rebuild and integrity

P0 rebuild uses content hashes.

Rules:

- `object-hashes.json` stores hash per canonical object file.
- `index-hashes.json` stores the source object hash set used for each index.
- If a source object hash differs, affected indexes are stale.
- `views/current/` is stale when any source fact/event hash changes.
- Rebuild should be deterministic enough that two rebuilds over the same reviewed objects produce equivalent current views and index records.

Manual recovery requirement:

- If every index is deleted, Brain must still answer by scanning `objects/` more slowly.
- If `views/current/` is deleted, Brain must rebuild it from reviewed facts and ledger records.
- If `raw/bundles/` are missing or redaction is not approved, Brain must downgrade answer status to `raw-unavailable` or `restricted`, not invent citations.

## 9. Stage clear token slice

The first acceptance slice uses the stage clear token and entrance popup event cluster.

Required stored objects:

- `EvidenceManifest` for spec, session discussion, code-search evidence, and context docs.
- `EvidenceRef` for relevant slides, session turns, and code locators.
- `EventLedgerRecord` for UI-space-driven event cluster change, direct item-usable UI clarification, and glossary clarification.
- `TemporalFact` for current reviewed UI rules.
- `CodeLocator` for entrance popup, continue popup, and event cluster code anchors.
- `DomainContext` / `GlossaryTerm` for "입장팝업", "컨티뉴 팝업", "이벤트 클러스터", "스테이지 클리어 토큰".
- `CurrentView` for current feature status.

Explicit boundary:

- `요정의 선물` and `해피블록` may be referenced as event display candidates in this slice, but their standalone event specs are separate future contexts.
- The event cluster UI change is stored as related UI history, not as a functional sub-feature of stage clear token.

## 10. Decisions closed by this spec

| Decision | Result |
|---|---|
| Canonical storage style | Append-only object store plus disposable projections. |
| Raw source boundary | Raw evidence and approved citation bundles live under `raw/`; reviewed Brain objects live under `objects/`. |
| Current view boundary | `CurrentView` is materialized from reviewed facts/events, not hand-authored truth. |
| Time fields | Keep `created_at`, `happened_at`, and `valid_from` / `valid_until` separate. |
| P0 indexes | FTS, timeline, entity, and code locator. Vector/graph/rerank are deferred. |
| Rebuild trigger | Content-hash manifest in P0; no cron or background daemon required. |
| LLM extraction role | Candidate generation only; review promotes truth. |

## 11. Deferred decisions

| Decision | Why deferred |
|---|---|
| Exact file encoding: JSONL vs one JSON file per object | Needs prototype ergonomics check with git diff, append semantics, and partial rewrite cost. |
| SQLite projection schema | Belongs to implementation plan after object file format is chosen. |
| Query routing weights | Belongs to Query Routing Spec. |
| Review UI / approval UX | Needs PoC operation feedback. |
| Slack/Jira ACL redaction policy | Needs privacy/redaction research before shared Brain. |
| PPT slide diff extraction detail | Needs spec extraction research. |

## 12. Self-review notes

- The layout keeps object truth separate from retrieval indexes.
- The design does not require vector search for P0.
- The stage clear token slice avoids making `요정의 선물` or `해피블록` main contexts.
- `CONTEXT.md` remains glossary-only; code anchors stay in object/code locator records or inventory-style evidence, not in glossary definitions.
