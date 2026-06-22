# BB2 Brain P0 Router Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local P0 BB2 Brain prototype that loads canonical Brain object JSON files, routes queries deterministically by intent, assigns answer status labels, and passes the stage clear token acceptance slice.

**Architecture:** Keep the prototype outside game runtime code under `scripts/bb2_brain/`. Use one JSON file per Brain object for canonical storage because it is easy to diff, inspect, and load during the PoC. Treat `CurrentView` and `IndexRecord` as candidate discovery only; final answers are assembled from loaded source objects and their evidence/review chain.

**Tech Stack:** Python 3 standard library, `unittest`, JSON files, local CLI run through `/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python`.

---

## Scope

This plan implements the P0 deterministic router only.

Included:

- Object-per-file JSON loader.
- Candidate discovery from `CurrentView` and `IndexRecord`.
- Intent classification for current status, why changed, as-of history, implementation location, glossary meaning, and evidence provenance.
- Status label calculation for `reviewed`, `candidate`, `raw-only`, `restricted`, and `raw-unavailable`.
- Stage clear token acceptance fixture and CLI query.

Excluded:

- Vector search and reranker weights.
- Slack/Jira/PPT connectors.
- Review UI.
- Real BB2 code indexing.
- Game client code changes.
- SQLite projection schema.

## File Structure

- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/__init__.py`
  - Responsibility: package marker.
- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/store.py`
  - Responsibility: load canonical object JSON files and provide simple indexed lookup by `id`, `kind`, `status`, and source links.
- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/intent.py`
  - Responsibility: normalize known terms and classify deterministic P0 intents.
- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/status.py`
  - Responsibility: calculate claim and answer status labels.
- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/router.py`
  - Responsibility: implement read order, truth order, scope filters, conflict behavior, and answer assembly.
- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/cli.py`
  - Responsibility: run one local query against a Brain fixture directory.
- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/tests/__init__.py`
  - Responsibility: unittest package marker.
- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/tests/fixtures/stage_clear_token_brain/brain/...`
  - Responsibility: small object-per-file fixture for the acceptance slice.
- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/tests/test_store.py`
  - Responsibility: loader and source-object lookup tests.
- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/tests/test_intent.py`
  - Responsibility: term normalization and intent decomposition tests.
- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/tests/test_status.py`
  - Responsibility: answer status precedence tests.
- Create: `/Users/al03040455/Desktop/bb2_client/scripts/bb2_brain/tests/test_router.py`
  - Responsibility: routing behavior and acceptance tests.

## Object File Encoding Decision

Use one JSON file per Brain object:

```text
brain/
  objects/
    domain/domain_stage_clear_token.json
    domain/term_popup_enter.json
    facts/fact_stage_clear_token_popup_enter_current_rule.json
    ledger/event_popup_space_pressure.json
    code/locator_original_popup_enter_draw_event_cluster.json
    evidence_refs/ref_slack_space_pressure.json
    reviews/review_fact_stage_clear_token_popup_enter_current_rule.json
  views/current/current_stage_clear_token_feature_status.json
  indexes/entity/index_entity_popup_enter.json
```

Each file contains one object with at least:

```json
{
  "id": "fact.stage-clear-token.popup-enter.current-rule",
  "kind": "TemporalFact",
  "schema_version": "0.1",
  "status": "reviewed",
  "truth_role": "fact",
  "title": "Stage clear token popup enter current display rule",
  "evidence_refs": ["ref.slack.space-pressure"],
  "review_record_id": "review.fact.stage-clear-token.popup-enter.current-rule"
}
```

## Verification Commands

Use the shared Python resolution rule:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest discover -s scripts/bb2_brain/tests -v
```

Expected final result:

```text
OK
```

Use document checks before each commit:

```bash
git diff --check -- scripts/bb2_brain docs/superpowers/plans/2026-05-28-bb2-brain-p0-router.md
```

Expected: no output.

---

### Task 1: Add Object Store Loader

**Files:**
- Create: `scripts/bb2_brain/__init__.py`
- Create: `scripts/bb2_brain/store.py`
- Create: `scripts/bb2_brain/tests/__init__.py`
- Create: `scripts/bb2_brain/tests/test_store.py`

- [ ] **Step 1: Write loader tests**

Create `scripts/bb2_brain/tests/test_store.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from scripts.bb2_brain.store import BrainStore


def write_object(root: Path, relative_path: str, payload: dict) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class BrainStoreTest(unittest.TestCase):
    def test_loads_objects_by_id_and_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/facts/fact.json", {
                "id": "fact.current-rule",
                "kind": "TemporalFact",
                "status": "reviewed",
                "truth_role": "fact",
                "title": "Current rule",
                "evidence_refs": ["ref.rule"],
            })

            store = BrainStore.load(root)

            self.assertEqual(store.get("fact.current-rule")["kind"], "TemporalFact")
            self.assertEqual([obj["id"] for obj in store.by_kind("TemporalFact")], ["fact.current-rule"])

    def test_ignores_index_directory_when_indexes_are_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "brain"
            write_object(root, "objects/ledger/event.json", {
                "id": "event.change",
                "kind": "EventLedgerRecord",
                "status": "reviewed",
                "truth_role": "event",
                "title": "Change event",
                "evidence_refs": [],
            })

            store = BrainStore.load(root)

            self.assertEqual(store.get("event.change")["truth_role"], "event")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_store -v
```

Expected: fail with `ModuleNotFoundError` or `ImportError` because `BrainStore` does not exist.

- [ ] **Step 3: Add minimal package and loader**

Create `scripts/bb2_brain/__init__.py`:

```python
"""Local BB2 Brain prototype tools."""
```

Create `scripts/bb2_brain/tests/__init__.py`:

```python
"""Tests for local BB2 Brain prototype tools."""
```

Create `scripts/bb2_brain/store.py`:

```python
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


class BrainStore:
    def __init__(self, objects: dict[str, dict[str, Any]]):
        self._objects = objects
        self._by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for obj in objects.values():
            self._by_kind[obj.get("kind", "")].append(obj)

    @classmethod
    def load(cls, brain_root: Path) -> "BrainStore":
        objects: dict[str, dict[str, Any]] = {}
        for path in sorted(brain_root.rglob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            object_id = payload["id"]
            objects[object_id] = payload
        return cls(objects)

    def get(self, object_id: str) -> dict[str, Any]:
        return self._objects[object_id]

    def by_kind(self, kind: str) -> list[dict[str, Any]]:
        return list(self._by_kind.get(kind, []))

    def all(self) -> list[dict[str, Any]]:
        return list(self._objects.values())
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_store -v
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain
git commit -m "feat: add BB2 Brain object store loader"
```

### Task 2: Add Intent Classification and Term Normalization

**Files:**
- Create: `scripts/bb2_brain/intent.py`
- Create: `scripts/bb2_brain/tests/test_intent.py`

- [ ] **Step 1: Write intent tests**

Create `scripts/bb2_brain/tests/test_intent.py`:

```python
import unittest

from scripts.bb2_brain.intent import classify_query, normalize_terms


class IntentTest(unittest.TestCase):
    def test_normalizes_avoided_popup_term(self):
        normalized = normalize_terms("5.5 기준 시작팝업 QA 기준이 뭐야?")
        self.assertIn("입장팝업", normalized.canonical_query)
        self.assertIn("시작팝업", normalized.avoided_terms)

    def test_decomposes_mixed_why_and_current_status(self):
        result = classify_query("5.5 기준 입장팝업 표시가 왜 바뀌었고 현재 QA 기준은 뭐야?")
        self.assertEqual(result.intents, ["why_changed", "current_status"])

    def test_classifies_code_location(self):
        result = classify_query("drawEventCluster 어디 구현돼 있어?")
        self.assertEqual(result.intents, ["implementation_location"])
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_intent -v
```

Expected: fail because `scripts.bb2_brain.intent` does not exist.

- [ ] **Step 3: Add deterministic classifier**

Create `scripts/bb2_brain/intent.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedQuery:
    original_query: str
    canonical_query: str
    avoided_terms: list[str]


@dataclass(frozen=True)
class ClassifiedQuery:
    normalized: NormalizedQuery
    intents: list[str]


AVOIDED_TERMS = {
    "시작팝업": "입장팝업",
}


def normalize_terms(query: str) -> NormalizedQuery:
    canonical = query
    avoided: list[str] = []
    for avoided_term, canonical_term in AVOIDED_TERMS.items():
        if avoided_term in canonical:
            avoided.append(avoided_term)
            canonical = canonical.replace(avoided_term, canonical_term)
    return NormalizedQuery(original_query=query, canonical_query=canonical, avoided_terms=avoided)


def classify_query(query: str) -> ClassifiedQuery:
    normalized = normalize_terms(query)
    text = normalized.canonical_query
    intents: list[str] = []

    if "왜" in text or "이유" in text or "바뀌" in text:
        intents.append("why_changed")
    if "현재" in text or "지금" in text or "QA 기준" in text:
        intents.append("current_status")
    if "그때" in text or "당시" in text or "as-of" in text:
        intents.append("as_of_history")
    if "어디 구현" in text or "어느 함수" in text or "어디에 구현" in text:
        intents.append("implementation_location")
    if "무슨 뜻" in text or "용어" in text:
        intents.append("glossary_meaning")
    if "근거" in text or "누가 확정" in text or "출처" in text:
        intents.append("evidence_provenance")

    if "why_changed" in intents and "current_status" in intents:
        intents = ["why_changed", "current_status"] + [
            intent for intent in intents if intent not in {"why_changed", "current_status"}
        ]

    if not intents:
        intents.append("unknown")

    return ClassifiedQuery(normalized=normalized, intents=intents)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_intent -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain/intent.py scripts/bb2_brain/tests/test_intent.py
git commit -m "feat: add BB2 Brain intent classifier"
```

### Task 3: Add Status Label Calculation

**Files:**
- Create: `scripts/bb2_brain/status.py`
- Create: `scripts/bb2_brain/tests/test_status.py`

- [ ] **Step 1: Write status tests**

Create `scripts/bb2_brain/tests/test_status.py`:

```python
import unittest

from scripts.bb2_brain.status import answer_status, claim_status


class StatusTest(unittest.TestCase):
    def test_reviewed_claim_with_evidence_is_reviewed(self):
        status = claim_status({"status": "reviewed", "evidence_refs": ["ref.ok"]}, raw_available=True, restricted=False)
        self.assertEqual(status, "reviewed")

    def test_reviewed_claim_missing_raw_is_raw_unavailable(self):
        status = claim_status({"status": "reviewed", "evidence_refs": ["ref.missing"]}, raw_available=False, restricted=False)
        self.assertEqual(status, "raw-unavailable")

    def test_candidate_is_more_severe_than_raw_only(self):
        self.assertEqual(answer_status(["reviewed", "raw-only", "candidate"]), "candidate")

    def test_restricted_is_most_severe(self):
        self.assertEqual(answer_status(["reviewed", "restricted", "raw-unavailable"]), "restricted")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_status -v
```

Expected: fail because `scripts.bb2_brain.status` does not exist.

- [ ] **Step 3: Add status functions**

Create `scripts/bb2_brain/status.py`:

```python
SEVERITY = {
    "reviewed": 0,
    "raw-only": 1,
    "candidate": 2,
    "raw-unavailable": 3,
    "restricted": 4,
}


def claim_status(obj: dict, *, raw_available: bool, restricted: bool) -> str:
    if restricted:
        return "restricted"
    if obj.get("status") == "reviewed":
        if obj.get("evidence_refs") and not raw_available:
            return "raw-unavailable"
        return "reviewed"
    if obj.get("status") == "candidate":
        return "candidate"
    return "raw-only"


def answer_status(statuses: list[str]) -> str:
    if not statuses:
        return "raw-only"
    return max(statuses, key=lambda status: SEVERITY[status])
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_status -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain/status.py scripts/bb2_brain/tests/test_status.py
git commit -m "feat: add BB2 Brain status labels"
```

### Task 4: Add Router for Current Status, Why Changed, and As-Of Scope

**Files:**
- Create: `scripts/bb2_brain/router.py`
- Create: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: Write router unit tests**

Create the first part of `scripts/bb2_brain/tests/test_router.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from scripts.bb2_brain.router import QueryRouter
from scripts.bb2_brain.store import BrainStore


def write_object(root: Path, relative_path: str, payload: dict) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class RouterTest(unittest.TestCase):
    def build_store(self) -> BrainStore:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "brain"
        write_object(root, "views/current/current.json", {
            "id": "view.stage-clear-token.current",
            "kind": "CurrentView",
            "status": "reviewed",
            "truth_role": "synthesis",
            "view_type": "feature_status",
            "source_fact_ids": ["fact.current-rule"],
            "source_event_ids": ["event.space-pressure"],
            "summary": "Current feature status",
            "evidence_refs": [],
        })
        write_object(root, "objects/facts/current_rule.json", {
            "id": "fact.current-rule",
            "kind": "TemporalFact",
            "status": "reviewed",
            "truth_role": "fact",
            "subject": "stage-clear-token.PopupEnter.eventCluster.displayRule",
            "predicate": "uses",
            "value": "drawEventCluster",
            "scope": {"project": "bb2-client", "release": "5.5", "feature": "stage-clear-token", "surface": "PopupEnter"},
            "valid_from": "2026-05-26T00:00:00+09:00",
            "evidence_refs": ["ref.spec"],
            "review_record_id": "review.fact.current-rule",
        })
        write_object(root, "objects/ledger/event.json", {
            "id": "event.space-pressure",
            "kind": "EventLedgerRecord",
            "status": "reviewed",
            "truth_role": "event",
            "event_type": "spec_clarified",
            "happened_at": "2026-05-26T00:00:00+09:00",
            "summary": "Token UI created popup space pressure, so event display moved into event cluster.",
            "evidence_refs": ["ref.slack"],
        })
        write_object(root, "objects/evidence_refs/ref_spec.json", {
            "id": "ref.spec",
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "summary": "Spec slide reference",
            "evidence_manifest_id": "manifest.spec",
            "evidence_refs": [],
        })
        write_object(root, "objects/evidence_refs/ref_slack.json", {
            "id": "ref.slack",
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "summary": "Clarification reference",
            "evidence_manifest_id": "manifest.slack",
            "evidence_refs": [],
        })
        return BrainStore.load(root)

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def test_current_status_uses_fact_truth_not_current_view_truth(self):
        router = QueryRouter(self.build_store())
        answer = router.answer("5.5 기준 입장팝업 현재 QA 기준은 뭐야?")
        self.assertEqual(answer["status"], "reviewed")
        self.assertIn("fact.current-rule", answer["source_object_ids"])
        self.assertIn("view.stage-clear-token.current", answer["candidate_object_ids"])

    def test_why_changed_returns_event_before_current_status(self):
        router = QueryRouter(self.build_store())
        answer = router.answer("5.5 기준 입장팝업 표시가 왜 바뀌었고 현재 QA 기준은 뭐야?")
        self.assertEqual(answer["intents"], ["why_changed", "current_status"])
        self.assertEqual(answer["sections"][0]["intent"], "why_changed")
        self.assertIn("event.space-pressure", answer["source_object_ids"])
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -v
```

Expected: fail because `QueryRouter` does not exist.

- [ ] **Step 3: Add minimal router**

Create `scripts/bb2_brain/router.py`:

```python
from scripts.bb2_brain.intent import classify_query
from scripts.bb2_brain.status import answer_status, claim_status
from scripts.bb2_brain.store import BrainStore


class QueryRouter:
    def __init__(self, store: BrainStore):
        self.store = store

    def answer(self, query: str) -> dict:
        classified = classify_query(query)
        candidate_ids: list[str] = []
        source_ids: list[str] = []
        sections: list[dict] = []
        claim_statuses: list[str] = []

        for intent in classified.intents:
            if intent == "why_changed":
                events = self._reviewed_by_kind("EventLedgerRecord")
                if events:
                    event = events[0]
                    source_ids.append(event["id"])
                    claim_statuses.append(claim_status(event, raw_available=True, restricted=False))
                    sections.append({"intent": intent, "object_ids": [event["id"]], "summary": event.get("summary", "")})
            elif intent == "current_status":
                views = self._reviewed_by_kind("CurrentView")
                candidate_ids.extend(view["id"] for view in views)
                facts = self._current_facts(query)
                for fact in facts:
                    source_ids.append(fact["id"])
                    claim_statuses.append(claim_status(fact, raw_available=True, restricted=False))
                sections.append({"intent": intent, "object_ids": [fact["id"] for fact in facts], "summary": "Current reviewed facts"})
            elif intent == "unknown":
                sections.append({"intent": intent, "object_ids": [], "summary": "No matching intent"})

        return {
            "query": query,
            "canonical_query": classified.normalized.canonical_query,
            "intents": classified.intents,
            "status": answer_status(claim_statuses),
            "candidate_object_ids": sorted(set(candidate_ids)),
            "source_object_ids": sorted(set(source_ids)),
            "sections": sections,
        }

    def _reviewed_by_kind(self, kind: str) -> list[dict]:
        return [obj for obj in self.store.by_kind(kind) if obj.get("status") == "reviewed"]

    def _current_facts(self, query: str) -> list[dict]:
        facts = self._reviewed_by_kind("TemporalFact")
        if "5.5" in query:
            facts = [fact for fact in facts if fact.get("scope", {}).get("release") == "5.5"]
        return [fact for fact in facts if not fact.get("valid_until")]
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -v
```

Expected: router tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: add BB2 Brain deterministic router"
```

### Task 5: Add CodeLocator and Raw-Unavailable Routing Tests

**Files:**
- Modify: `scripts/bb2_brain/router.py`
- Modify: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: Add failing tests for stale locator and raw-unavailable**

Append to `RouterTest` in `scripts/bb2_brain/tests/test_router.py`:

```python
    def test_code_locator_without_current_head_verification_is_candidate(self):
        store = self.build_store()
        router = QueryRouter(store, current_head="HEAD_NOW")
        answer = router.answer("drawEventCluster 어디 구현돼 있어?")
        self.assertIn("candidate", answer["status"])

    def test_missing_raw_bundle_downgrades_reviewed_claim(self):
        store = self.build_store()
        router = QueryRouter(store, missing_raw_manifest_ids={"manifest.spec"})
        answer = router.answer("5.5 기준 입장팝업 현재 QA 기준은 뭐야?")
        self.assertEqual(answer["status"], "raw-unavailable")
```

Also add a `CodeLocator` and `EvidenceManifest` objects inside `build_store()`:

```python
        write_object(root, "objects/code/locator.json", {
            "id": "locator.draw-event-cluster",
            "kind": "CodeLocator",
            "status": "reviewed",
            "truth_role": "reference",
            "path": "LineBubble2/Classes/main/popup_enter/OriginalPopupEnter.cpp",
            "symbol": "OriginalPopupEnter::drawEventCluster",
            "commit_sha": "OLD_HEAD",
            "evidence_refs": ["ref.code"],
        })
        write_object(root, "objects/evidence_refs/ref_code.json", {
            "id": "ref.code",
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "summary": "Code locator reference",
            "evidence_manifest_id": "manifest.code",
            "evidence_refs": [],
        })
        write_object(root, "objects/raw/manifest_spec.json", {
            "id": "manifest.spec",
            "kind": "EvidenceManifest",
            "status": "reviewed",
            "truth_role": "source",
            "redaction_status": "approved",
            "evidence_refs": [],
        })
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -v
```

Expected: fail because `QueryRouter` does not accept `current_head` or `missing_raw_manifest_ids`.

- [ ] **Step 3: Update router constructor and status checks**

Modify `scripts/bb2_brain/router.py`:

```python
class QueryRouter:
    def __init__(
        self,
        store: BrainStore,
        *,
        current_head: str | None = None,
        missing_raw_manifest_ids: set[str] | None = None,
    ):
        self.store = store
        self.current_head = current_head
        self.missing_raw_manifest_ids = missing_raw_manifest_ids or set()
```

Add implementation-location handling:

```python
            elif intent == "implementation_location":
                locators = self._reviewed_by_kind("CodeLocator")
                for locator in locators:
                    source_ids.append(locator["id"])
                    locator_stale = (
                        self.current_head is not None
                        and locator.get("commit_sha") is not None
                        and locator.get("commit_sha") != self.current_head
                    )
                    claim_statuses.append("candidate" if locator_stale else "reviewed")
                sections.append({"intent": intent, "object_ids": [locator["id"] for locator in locators], "summary": "Code locators"})
```

Add helper and use it when calculating fact status:

```python
    def _raw_available_for(self, obj: dict) -> bool:
        for ref_id in obj.get("evidence_refs", []):
            ref = self.store.get(ref_id)
            manifest_id = ref.get("evidence_manifest_id")
            if manifest_id in self.missing_raw_manifest_ids:
                return False
        return True
```

Replace current fact status calculation with:

```python
claim_statuses.append(claim_status(fact, raw_available=self._raw_available_for(fact), restricted=False))
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest scripts.bb2_brain.tests.test_router -v
```

Expected: all router tests pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/bb2_brain/router.py scripts/bb2_brain/tests/test_router.py
git commit -m "feat: handle BB2 Brain locator and raw status"
```

### Task 6: Add Stage Clear Token Fixture and CLI Acceptance

**Files:**
- Create fixture files under `scripts/bb2_brain/tests/fixtures/stage_clear_token_brain/brain/`
- Create: `scripts/bb2_brain/cli.py`
- Modify: `scripts/bb2_brain/tests/test_router.py`

- [ ] **Step 1: Add fixture object files for CLI smoke**

Create `scripts/bb2_brain/tests/fixtures/stage_clear_token_brain/brain/views/current/current_stage_clear_token.json`:

```json
{
  "id": "view.stage-clear-token.current",
  "kind": "CurrentView",
  "schema_version": "0.1",
  "status": "reviewed",
  "truth_role": "synthesis",
  "title": "Stage clear token current view",
  "view_type": "feature_status",
  "source_fact_ids": ["fact.current-rule"],
  "source_event_ids": ["event.space-pressure"],
  "summary": "Current stage clear token entrance popup event cluster status.",
  "evidence_refs": []
}
```

Create `scripts/bb2_brain/tests/fixtures/stage_clear_token_brain/brain/objects/facts/fact_current_rule.json`:

```json
{
  "id": "fact.current-rule",
  "kind": "TemporalFact",
  "schema_version": "0.1",
  "status": "reviewed",
  "truth_role": "fact",
  "title": "Stage clear token popup enter current display rule",
  "subject": "stage-clear-token.PopupEnter.eventCluster.displayRule",
  "predicate": "uses",
  "value": "drawEventCluster",
  "scope": {
    "project": "bb2-client",
    "release": "5.5",
    "feature": "stage-clear-token",
    "surface": "PopupEnter"
  },
  "valid_from": "2026-05-26T00:00:00+09:00",
  "evidence_refs": ["ref.spec"],
  "review_record_id": "review.fact.current-rule"
}
```

Create `scripts/bb2_brain/tests/fixtures/stage_clear_token_brain/brain/objects/ledger/event_space_pressure.json`:

```json
{
  "id": "event.space-pressure",
  "kind": "EventLedgerRecord",
  "schema_version": "0.1",
  "status": "reviewed",
  "truth_role": "event",
  "title": "Entrance popup space pressure clarification",
  "event_type": "spec_clarified",
  "happened_at": "2026-05-26T00:00:00+09:00",
  "summary": "Token UI created popup space pressure, so event display moved into event cluster.",
  "evidence_refs": ["ref.slack"]
}
```

Create `scripts/bb2_brain/tests/fixtures/stage_clear_token_brain/brain/objects/code/locator_draw_event_cluster.json`:

```json
{
  "id": "locator.draw-event-cluster",
  "kind": "CodeLocator",
  "schema_version": "0.1",
  "status": "reviewed",
  "truth_role": "reference",
  "title": "OriginalPopupEnter drawEventCluster",
  "path": "LineBubble2/Classes/main/popup_enter/OriginalPopupEnter.cpp",
  "symbol": "OriginalPopupEnter::drawEventCluster",
  "commit_sha": "HEAD_NOW",
  "evidence_refs": ["ref.code"]
}
```

Create `scripts/bb2_brain/tests/fixtures/stage_clear_token_brain/brain/objects/evidence_refs/ref_spec.json`:

```json
{
  "id": "ref.spec",
  "kind": "EvidenceRef",
  "schema_version": "0.1",
  "status": "reviewed",
  "truth_role": "reference",
  "title": "Stage clear token spec reference",
  "summary": "Spec slide reference for entrance popup display rule.",
  "evidence_manifest_id": "manifest.spec",
  "evidence_refs": []
}
```

Create `scripts/bb2_brain/tests/fixtures/stage_clear_token_brain/brain/objects/evidence_refs/ref_slack.json`:

```json
{
  "id": "ref.slack",
  "kind": "EvidenceRef",
  "schema_version": "0.1",
  "status": "reviewed",
  "truth_role": "reference",
  "title": "Stage clear token Slack clarification",
  "summary": "Clarification reference for popup space pressure and event cluster display.",
  "evidence_manifest_id": "manifest.slack",
  "evidence_refs": []
}
```

Create `scripts/bb2_brain/tests/fixtures/stage_clear_token_brain/brain/objects/evidence_refs/ref_code.json`:

```json
{
  "id": "ref.code",
  "kind": "EvidenceRef",
  "schema_version": "0.1",
  "status": "reviewed",
  "truth_role": "reference",
  "title": "drawEventCluster code locator evidence",
  "summary": "Code locator evidence for drawEventCluster.",
  "evidence_manifest_id": "manifest.code",
  "evidence_refs": []
}
```

- [ ] **Step 2: Add acceptance test**

Append to `RouterTest`:

```python
    def test_stage_clear_token_acceptance_answer(self):
        router = QueryRouter(self.build_store())
        answer = router.answer("5.5 기준 입장팝업의 요정의 선물/해피블록 표시가 왜 drawEventCluster 형태로 바뀌었고, 현재 QA 기준 동작은 뭐야?")

        self.assertEqual(answer["intents"], ["why_changed", "current_status", "implementation_location"])
        self.assertEqual(answer["status"], "reviewed")
        self.assertIn("event.space-pressure", answer["source_object_ids"])
        self.assertIn("fact.current-rule", answer["source_object_ids"])
        self.assertIn("locator.draw-event-cluster", answer["source_object_ids"])
```

- [ ] **Step 3: Update classifier so acceptance query includes implementation location**

Modify `scripts/bb2_brain/intent.py` so implementation intent is detected when `drawEventCluster` appears:

```python
    if "어디 구현" in text or "어느 함수" in text or "어디에 구현" in text or "drawEventCluster" in text:
        intents.append("implementation_location")
```

- [ ] **Step 4: Add CLI**

Create `scripts/bb2_brain/cli.py`:

```python
import argparse
import json
from pathlib import Path

from scripts.bb2_brain.router import QueryRouter
from scripts.bb2_brain.store import BrainStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brain-root", required=True)
    parser.add_argument("query")
    args = parser.parse_args()

    store = BrainStore.load(Path(args.brain_root))
    answer = QueryRouter(store).answer(args.query)
    print(json.dumps(answer, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run full unit tests**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest discover -s scripts/bb2_brain/tests -v
```

Expected: all tests pass.

- [ ] **Step 6: Run CLI smoke**

Run:

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m scripts.bb2_brain.cli --brain-root scripts/bb2_brain/tests/fixtures/stage_clear_token_brain/brain "5.5 기준 입장팝업의 요정의 선물/해피블록 표시가 왜 drawEventCluster 형태로 바뀌었고, 현재 QA 기준 동작은 뭐야?"
```

Expected output contains:

```json
"status": "reviewed"
```

and contains these object IDs:

```text
event.space-pressure
fact.current-rule
locator.draw-event-cluster
```

- [ ] **Step 7: Commit**

```bash
git add scripts/bb2_brain
git commit -m "feat: add BB2 Brain stage clear token acceptance"
```

### Task 7: Final Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run full tests**

```bash
/Users/al03040455/Downloads/codes/auto_worker/.venv/bin/python -m unittest discover -s scripts/bb2_brain/tests -v
```

Expected:

```text
OK
```

- [ ] **Step 2: Run whitespace check**

```bash
git diff --check HEAD
```

Expected: no output.

- [ ] **Step 3: Confirm implementation commits**

```bash
git log --oneline --decorate -8
```

Expected: shows the implementation commits from Tasks 1-6 on top of the spec commits.

- [ ] **Step 4: Report remaining non-goals**

Report that vector/reranker, connectors, review UI, and SQLite projection schema remain deferred by spec.
