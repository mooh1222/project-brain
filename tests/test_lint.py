"""lint.py 회귀 베이스라인 (B+C 작업 선행). 깨끗한 합성 store는 0 problem,
dangling evidence_ref는 1 problem. promote 사후 lint가 의존하는 동작을 고정한다."""

import unittest

from project_brain.lint import lint_store, unpromoted_vouched_terms
from project_brain.objbase import base
from project_brain.store import BrainStore
from tests.test_ingest import (
    candidate_term,
    evidence_ref,
    manifest,
)

T = "2026-06-04T00:00:00Z"


def store_of(*objs):
    return BrainStore({o["id"]: o for o in objs})


class TestLintStore(unittest.TestCase):
    def test_clean_store_no_problems(self):
        store = store_of(manifest(), evidence_ref(), candidate_term())
        self.assertEqual(lint_store(store), [])

    def test_dangling_evidence_ref_reported(self):
        term = candidate_term()
        term["evidence_refs"] = ["ev.missing"]
        store = store_of(term)
        problems = lint_store(store)
        self.assertTrue(any("dangling evidence_ref ev.missing" in p for p in problems))


def _drift_mapping(mid, *, term_ids, status="reviewed"):
    return base(
        {
            "id": mid, "kind": "DomainMapping", "status": status, "truth_role": "domain",
            "title": "매핑", "context_id": "context.neutral", "mapping_key": mid,
            "canonical_summary": "요약", "meaning": "의미", "boundary": "경계",
            "glossary_term_ids": term_ids, "decision_record_ids": [], "evidence_refs": ["evref.a"],
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def _drift_term(tid, *, status="candidate", candidate_state="evidence_verified"):
    obj = {
        "id": tid, "kind": "GlossaryTerm", "status": status, "truth_role": "domain",
        "title": "용어", "context_id": "context.neutral", "term": "용어", "definition": "정의",
        "evidence_refs": ["evref.a"],
    }
    if status == "candidate":
        obj["candidate"] = {"candidate_state": candidate_state, "candidate_source": "spec"}
    return base(obj, tags=["neutral"], created_at=T, updated_at=T)


class TestUnpromotedVouchedTerms(unittest.TestCase):
    def test_warns_candidate_vouched_by_reviewed_mapping(self):
        store = store_of(_drift_term("g.cand"), _drift_mapping("m", term_ids=["g.cand"]))
        warnings = unpromoted_vouched_terms(store)
        self.assertEqual(len(warnings), 1)
        self.assertIn("g.cand", warnings[0])

    def test_no_warning_for_reviewed_term(self):
        store = store_of(_drift_term("g.rev", status="reviewed"),
                         _drift_mapping("m", term_ids=["g.rev"]))
        self.assertEqual(unpromoted_vouched_terms(store), [])

    def test_no_warning_for_conflict_term(self):
        store = store_of(_drift_term("g.c", candidate_state="conflict"),
                         _drift_mapping("m", term_ids=["g.c"]))
        self.assertEqual(unpromoted_vouched_terms(store), [])

    def test_no_warning_for_unreferenced_candidate(self):
        store = store_of(_drift_term("g.lonely"))
        self.assertEqual(unpromoted_vouched_terms(store), [])

    def test_lint_store_does_not_block_on_drift(self):
        # 드리프트는 lint_store(차단)에 들어가면 안 된다 — candidate 적재가 안 깨지게.
        store = store_of(_drift_term("g.cand"), _drift_mapping("m", term_ids=["g.cand"]))
        # _drift_mapping의 evref.a/context.neutral 미존재라 lint_store는 dangling을 보고하지만,
        # 드리프트 경고 자체는 lint_store 결과에 섞이지 않는다.
        self.assertFalse(any("still candidate" in p for p in lint_store(store)))


if __name__ == "__main__":
    unittest.main()
