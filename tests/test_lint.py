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


class TestInsightDangling(unittest.TestCase):
    """Insight dangling 가드(spec 2026-06-15 §4.7) — 가리키는 근거 객체가 supersede/삭제되면
    '가로지른다'는 본질이 조용히 깨지므로 DomainMapping 8a·DecisionRecord 8b와 동형으로 잡는다."""

    def test_dangling_source_object_id_reported(self):
        from tests.test_ingest import insight
        ins = insight(source_object_ids=["m.gone", "m.gone2"])
        problems = lint_store(store_of(ins))
        self.assertTrue(any("dangling source_object_ids m.gone" in p for p in problems))

    def test_dangling_code_locator_id_reported(self):
        from tests.test_ingest import insight
        ins = insight(code_locator_ids=["code.gone"])
        problems = lint_store(store_of(ins))
        self.assertTrue(any("dangling code_locator_ids code.gone" in p for p in problems))

    def test_resolved_sources_no_dangling(self):
        from tests.test_ingest import insight, context, candidate_mapping, candidate_term
        g = candidate_term("g.x")
        ctx = context(glossary_term_ids=["g.x"])
        m1 = candidate_mapping("m.a", glossary_term_ids=["g.x"])
        m2 = candidate_mapping("m.b", glossary_term_ids=["g.x"])
        ins = insight(source_object_ids=["m.a", "m.b"])
        problems = lint_store(store_of(g, ctx, m1, m2, ins))
        self.assertFalse([p for p in problems if "insight.x" in p])


def _projection(pid="projection.x.req.reuse", *, source_object_ids, source_content_hash):
    """ContextProjection 최소 픽스처(스키마 필수 필드 충족)."""
    return base(
        {
            "id": pid, "kind": "ContextProjection", "status": "candidate", "truth_role": "index",
            "title": "착수 브리핑", "context_id": "context.x",
            "format": "prompt_payload", "reuse_payload": "재사용 본문",
            "output_locator": f"indexes/context_projections/{pid}.txt",
            "source_object_ids": source_object_ids,
            "source_content_hash": source_content_hash, "projection_hash": "y",
            "generated_at": T, "generated_by": "test",
            "stale_policy": "fail_on_manual_edit",
            "evidence_refs": [],
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


class TestContextProjectionDangling(unittest.TestCase):
    """외부 리뷰 재현(Important 1): source_object_ids가 store에 없는 id를 가리키는 projection은
    DomainMapping(8a)·DecisionRecord(8b)·Insight(9)와 동형으로 dangling을 보고해야 한다.
    조용히 건너뛰면 근거 사라진 브리핑이 색인에 계속 남는다."""

    def test_dangling_source_object_id_reported(self):
        from project_brain.hash_utils import sha256_text
        proj = _projection(source_object_ids=["missing.source"],
                           source_content_hash=sha256_text(""))
        problems = lint_store(store_of(proj))
        self.assertTrue(
            any("dangling source_object_id missing.source" in p for p in problems),
            problems,
        )

    def test_all_sources_present_no_dangling(self):
        # 회귀 가드: 모든 source가 store에 있으면 dangling 문제 없음.
        from project_brain.hash_utils import sha256_text, stable_json
        src = _drift_mapping("m.src", term_ids=[])
        proj = _projection(
            source_object_ids=["m.src"],
            source_content_hash=sha256_text(stable_json(src)),
        )
        problems = lint_store(store_of(src, proj))
        self.assertFalse([p for p in problems if "dangling source_object_id" in p], problems)


if __name__ == "__main__":
    unittest.main()
