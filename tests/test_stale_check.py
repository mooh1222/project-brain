"""stale-check / mark-checked 로직·CLI 테스트.

자기완결: 인라인 객체 빌더 + 가짜 git_runner만 쓴다(실 git·네트워크 없음).
spec: docs/superpowers/specs/2026-06-14-bb2-brain-stale-check-design.md
"""
import unittest

from project_brain.store import BrainStore


def code_locator(cid, *, path, commit_sha, symbol="sym", line_start=10, line_end=20):
    from project_brain.objbase import base
    return base({
        "id": cid, "kind": "CodeLocator", "status": "reviewed", "truth_role": "reference",
        "title": f"Code: {symbol}", "repo": "bb2_client", "path": path, "symbol": symbol,
        "line_start": line_start, "line_end": line_end,
        "locator_source": "rg", "verified_at": "2026-06-12T00:00:00Z",
        "commit_sha": commit_sha, "evidence_refs": [],
    }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")


def domain_mapping(mid, *, code_locator_ids, status="reviewed"):
    from project_brain.objbase import base
    obj = {
        "id": mid, "kind": "DomainMapping", "status": status, "truth_role": "domain",
        "title": f"Mapping {mid}", "context_id": "context.x", "mapping_key": mid,
        "canonical_summary": "요약", "meaning": "의미", "boundary": "경계",
        "glossary_term_ids": [], "decision_record_ids": [],
        "code_locator_ids": code_locator_ids,
        "evidence_refs": ["ev.x"] if status == "reviewed" else [],
    }
    if status == "candidate":
        obj["candidate"] = {"candidate_state": "ready_for_review", "candidate_source": "spec"}
    return base(obj, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")


def _store(*objs):
    return BrainStore({o["id"]: o for o in objs})


class ComputeClosureTest(unittest.TestCase):
    def test_blocking_is_reviewed_only_superseded_excluded_candidate_nonblocking(self):
        from project_brain.stale_check import compute_closure
        store = _store(
            code_locator("code.shared", path="a/X.cpp", commit_sha="SHA1"),
            domain_mapping("m.r1", code_locator_ids=["code.shared"], status="reviewed"),
            domain_mapping("m.r2", code_locator_ids=["code.shared"], status="reviewed"),
            domain_mapping("m.cand", code_locator_ids=["code.shared"], status="candidate"),
            domain_mapping("m.sup", code_locator_ids=["code.shared"], status="superseded"),
        )
        closure = compute_closure(store, "code.shared")
        self.assertEqual(closure["blocking"], ["m.r1", "m.r2"])
        self.assertEqual(closure["nonblocking"], ["m.cand", "m.sup"])

    def test_locator_with_no_referencing_mappings(self):
        from project_brain.stale_check import compute_closure
        store = _store(code_locator("code.lonely", path="a/Y.cpp", commit_sha="SHA1"))
        self.assertEqual(compute_closure(store, "code.lonely"),
                         {"blocking": [], "nonblocking": []})
