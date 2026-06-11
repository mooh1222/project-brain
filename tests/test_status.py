"""status.py 회귀 베이스라인 (B+C 작업 선행). claim_status/answer_status는
신뢰 라벨 모델의 단일 진실 — spec §8에서 불변. C가 후보를 답 재료에 섞으면
answer_status가 candidate(severity 2) 이상을 반영해야 하므로 그 동작을 고정한다."""

import unittest

from project_brain.status import answer_status, claim_status


class TestClaimStatus(unittest.TestCase):
    def test_reviewed_with_available_raw(self):
        obj = {"status": "reviewed", "evidence_refs": ["ev.ref"]}
        self.assertEqual(claim_status(obj, raw_available=True, restricted=False), "reviewed")

    def test_reviewed_but_raw_missing(self):
        obj = {"status": "reviewed", "evidence_refs": ["ev.ref"]}
        self.assertEqual(claim_status(obj, raw_available=False, restricted=False), "raw-unavailable")

    def test_candidate(self):
        obj = {"status": "candidate"}
        self.assertEqual(claim_status(obj, raw_available=True, restricted=False), "candidate")

    def test_restricted_overrides(self):
        obj = {"status": "reviewed", "evidence_refs": ["ev.ref"]}
        self.assertEqual(claim_status(obj, raw_available=True, restricted=True), "restricted")


class TestAnswerStatus(unittest.TestCase):
    def test_empty_is_raw_only(self):
        self.assertEqual(answer_status([]), "raw-only")

    def test_max_severity_wins(self):
        self.assertEqual(answer_status(["reviewed", "candidate"]), "candidate")
        self.assertEqual(answer_status(["restricted", "candidate"]), "restricted")
        self.assertEqual(answer_status(["reviewed", "reviewed"]), "reviewed")


if __name__ == "__main__":
    unittest.main()
