"""갱신 문서가 설명하는 현재 엔진 경계를 합성 객체로 고정한다."""
from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from project_brain.ingest import IngestError
from project_brain.objbase import base
from project_brain.router import QueryRouter
from project_brain.store import BrainStore
from tests.test_ingest import context, evidence_ref, ingest, manifest

T1 = "2026-07-01T00:00:00+09:00"
T2 = "2026-07-02T00:00:00+09:00"


def mapping(mid, status, *, supersedes=None):
    obj = base({
        "id": mid, "kind": "DomainMapping", "status": status, "truth_role": "domain",
        "title": mid, "context_id": "context.neutral", "mapping_key": mid.rsplit(".", 1)[-1],
        "canonical_summary": "현재 의미", "meaning": "현재 의미", "boundary": "경계",
        "glossary_term_ids": [],
        "decision_record_ids": [],
        "evidence_refs": ["evref.neutral.ref"],
    }, tags=["neutral"], created_at=T1, updated_at=T2)
    if supersedes:
        obj["supersedes_mapping_ids"] = supersedes
    return obj


def event(eid, happened_at):
    return base({
        "id": eid, "kind": "EventLedgerRecord", "status": "reviewed", "truth_role": "event",
        "title": eid, "event_type": "spec_revision", "happened_at": happened_at,
        "summary": "값 변경", "related_objects": [],
    }, tags=["neutral"], created_at=happened_at, updated_at=happened_at)


def fact(fid, value, *, event_id, valid_from, valid_until=None, supersedes=None):
    obj = base({
        "id": fid, "kind": "TemporalFact", "status": "reviewed", "truth_role": "fact",
        "title": f"값 {value}", "subject": "setting.scale", "predicate": "value",
        "value": value, "scope": {"release": "live"}, "valid_from": valid_from,
        "derived_from_event_id": event_id, "confidence": "high",
    }, tags=["neutral"], created_at=valid_from, updated_at=T2)
    if valid_until is not None:
        obj["valid_until"] = valid_until
    if supersedes is not None:
        obj["supersedes"] = supersedes
    return obj


class UpdateRulesEngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_mapping_supersession_requires_old_reviewed_to_close_in_same_bundle(self):
        old = mapping("mapping.neutral.old", "reviewed")
        ingest(self.root, [manifest(), evidence_ref(), context(), old])
        new = mapping("mapping.neutral.new", "reviewed", supersedes=[old["id"]])

        with self.assertRaisesRegex(IngestError, "status is still 'reviewed'"):
            ingest(self.root, [new])

        closed = deepcopy(old)
        closed["status"] = "superseded"
        ingest(self.root, [closed, new])
        store = BrainStore.load(self.root)
        self.assertEqual(store.get(old["id"])["status"], "superseded")
        self.assertEqual(store.get(new["id"])["status"], "reviewed")

    def test_temporal_change_closes_old_fact_and_keeps_current_history_boundary(self):
        old_event = event("ledger.scale.old", T1)
        old = fact("fact.scale.old", "0.82", event_id=old_event["id"], valid_from=T1)
        ingest(self.root, [old_event, old])
        new_event = event("ledger.scale.new", T2)
        new = fact("fact.scale.new", "0.85", event_id=new_event["id"],
                   valid_from=T2, supersedes=old["id"])

        with self.assertRaisesRegex(IngestError, "open reviewed facts"):
            ingest(self.root, [new_event, new])

        closed = deepcopy(old)
        closed["valid_until"] = T2
        ingest(self.root, [closed, new_event, new])
        router = QueryRouter(BrainStore.load(self.root))
        self.assertEqual([item["id"] for item in router._current_facts("")], [new["id"]])
        why = router.answer("왜 값이 바뀌었어?")
        changes = [change for section in why["sections"]
                   if section["intent"] == "why_changed"
                   for change in section.get("fact_changes", [])]
        current_change = next(change for change in changes if change["fact_id"] == new["id"])
        self.assertEqual(current_change["before_value"], "0.82")
        self.assertEqual(current_change["after_value"], "0.85")


if __name__ == "__main__":
    unittest.main()
