"""objbase.base() + review_record() 공용 헬퍼 단위 테스트 (Task 1).
새 중립 합성 데이터(인라인 dict)만 사용한다 — 삭제된 fixture/테스트 미참조."""

import unittest
from datetime import datetime

from project_brain.objbase import base, now_kst, review_record
from project_brain.schema import validate_object

T = "2026-06-04T00:00:00Z"


class TestBase(unittest.TestCase):
    def test_base_fills_defaults_via_setdefault(self):
        out = base({"id": "x", "kind": "GlossaryTerm"}, tags=["t"], created_at=T, updated_at=T)
        self.assertEqual(out["schema_version"], "0.1")
        self.assertEqual(out["poc_priority"], "P0")
        self.assertEqual(out["created_at"], T)
        self.assertEqual(out["tags"], ["t"])
        self.assertEqual(out["evidence_refs"], [])

    def test_base_does_not_default_status(self):
        out = base({"id": "x", "kind": "GlossaryTerm"}, tags=["t"], created_at=T, updated_at=T)
        self.assertNotIn("status", out)

    def test_base_does_not_overwrite_caller_fields(self):
        out = base(
            {"id": "x", "kind": "GlossaryTerm", "evidence_refs": ["a"], "status": "reviewed"},
            tags=["t"], created_at=T, updated_at=T,
        )
        self.assertEqual(out["evidence_refs"], ["a"])
        self.assertEqual(out["status"], "reviewed")


class TestReviewRecord(unittest.TestCase):
    def test_review_record_assembles_required_fields(self):
        rr = review_record(
            "review.g.x", target_object_id="g.x", reviewer="user-confirmed",
            reviewed_at=T, verdict="approved", tags=["t"], created_at=T, updated_at=T,
        )
        self.assertEqual(validate_object(rr), [])
        self.assertEqual(rr["kind"], "ReviewRecord")
        self.assertEqual(rr["truth_role"], "review")
        self.assertEqual(rr["status"], "reviewed")


class TestNowKst(unittest.TestCase):
    def test_now_kst_is_kst_offset_without_microsecond(self):
        s = now_kst()
        self.assertTrue(s.endswith("+09:00"), s)
        dt = datetime.fromisoformat(s)
        self.assertEqual(dt.utcoffset().total_seconds(), 9 * 3600)
        self.assertEqual(dt.microsecond, 0)


if __name__ == "__main__":
    unittest.main()
