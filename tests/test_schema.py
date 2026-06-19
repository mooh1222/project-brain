"""schema.py 회귀 베이스라인 (B+C 작업 선행). 현재 통과/거부 동작을 고정한다.
Task 4가 §6.4(reviewed DomainMapping·GlossaryTerm evidence_refs 강제)를 여기 확장."""

import unittest

from project_brain.schema import validate_object
from tests.test_ingest import (
    candidate_mapping,
    candidate_term,
    context,
    manifest,
)


class TestValidateObject(unittest.TestCase):
    def test_valid_manifest_passes(self):
        self.assertEqual(validate_object(manifest()), [])

    def test_valid_candidate_term_passes(self):
        self.assertEqual(validate_object(candidate_term()), [])

    def test_missing_base_field_reported(self):
        bad = {"id": "bad", "kind": "GlossaryTerm"}
        errors = validate_object(bad)
        self.assertTrue(any("missing base field" in e for e in errors))

    def test_unknown_kind_reported(self):
        errors = validate_object({"id": "x", "kind": "Nope"})
        self.assertEqual(errors, ["x: unknown kind 'Nope'"])

    def test_invalid_status_reported(self):
        obj = candidate_term()
        obj["status"] = "bogus"
        errors = validate_object(obj)
        self.assertTrue(any("invalid status" in e for e in errors))

    def test_candidate_mapping_passes(self):
        # context_id resolve는 lint 몫 — schema는 객체 단위. 필수 필드만 본다.
        self.assertEqual(validate_object(candidate_mapping("m.x", glossary_term_ids=["g.x"])), [])


class TestEvidenceGate(unittest.TestCase):
    def test_reviewed_glossary_term_requires_evidence(self):
        from tests.test_ingest import reviewed_term
        obj = reviewed_term("g.noev")
        obj["evidence_refs"] = []
        errors = validate_object(obj)
        self.assertTrue(any("reviewed GlossaryTerm requires non-empty evidence_refs" in e for e in errors))

    def test_reviewed_glossary_term_with_evidence_passes(self):
        from tests.test_ingest import reviewed_term
        obj = reviewed_term("g.ev")
        obj["evidence_refs"] = ["ev.ref"]
        self.assertEqual(validate_object(obj), [])

    def test_reviewed_mapping_requires_evidence(self):
        m = candidate_mapping("m.noev", glossary_term_ids=["g.x"])
        m["status"] = "reviewed"
        m["evidence_refs"] = []
        errors = validate_object(m)
        self.assertTrue(any("reviewed DomainMapping requires non-empty evidence_refs" in e for e in errors))

    def test_reviewed_mapping_with_evidence_but_no_code_locator_passes(self):
        # 서버규칙: 코드앵커 없어도 근거 있으면 통과(spec §6.1)
        m = candidate_mapping("m.server", glossary_term_ids=["g.x"])
        m["status"] = "reviewed"
        m["evidence_refs"] = ["ev.ref"]
        m["code_locator_ids"] = []
        self.assertEqual(validate_object(m), [])

    def test_candidate_without_evidence_still_valid(self):
        # 후보는 근거 강제 안 함(C로 노출되는 게 정상) — candidate는 evidence 빈 채로 OK
        obj = candidate_term()
        obj["evidence_refs"] = []
        self.assertEqual(validate_object(obj), [])


class TestRefTypeEnum(unittest.TestCase):
    """EvidenceRef.ref_type에 commit/pr/jira_issue 추가 (source_type 비대칭 메움).
    변경 출처(커밋/PR/지라)를 정식 근거 객체로 타입 명시해 연결하기 위함."""

    def test_commit_pr_jira_issue_ref_types_valid(self):
        from tests.test_ingest import evidence_ref
        for rt in ("commit", "pr", "jira_issue"):
            obj = evidence_ref()
            obj["ref_type"] = rt
            self.assertEqual(validate_object(obj), [], f"ref_type {rt!r} should be valid")

    def test_bogus_ref_type_still_rejected(self):
        from tests.test_ingest import evidence_ref
        obj = evidence_ref()
        obj["ref_type"] = "bogus_xyz"
        errors = validate_object(obj)
        self.assertTrue(any("invalid ref_type" in e for e in errors))


class TestInsightKind(unittest.TestCase):
    """Insight kind(2026-06-15 신설) — truth_role=synthesis 재사용, insight_type A/B enum,
    source_object_ids 개수 검사(공통 ≥1, A형 cross-cutting-risk ≥2)."""

    def test_valid_cross_cutting_risk_passes(self):
        from tests.test_ingest import insight
        self.assertEqual(validate_object(insight()), [])

    def test_valid_operational_lesson_passes(self):
        from tests.test_ingest import insight
        obj = insight("insight.b", insight_type="operational-lesson",
                      source_object_ids=["ctx.a"])
        self.assertEqual(validate_object(obj), [])

    def test_truth_role_must_be_synthesis(self):
        from tests.test_ingest import insight
        obj = insight()
        obj["truth_role"] = "domain"
        errors = validate_object(obj)
        self.assertTrue(any("invalid truth_role" in e for e in errors))

    def test_invalid_insight_type_rejected(self):
        from tests.test_ingest import insight
        obj = insight()
        obj["insight_type"] = "risk"
        errors = validate_object(obj)
        self.assertTrue(any("invalid insight_type" in e for e in errors))

    def test_cross_cutting_risk_requires_two_sources(self):
        from tests.test_ingest import insight
        obj = insight(source_object_ids=["m.only"])
        errors = validate_object(obj)
        self.assertTrue(any(">=2 source_object_ids" in e for e in errors))

    def test_no_type_requires_at_least_one_source(self):
        from tests.test_ingest import insight
        obj = insight(insight_type=None, source_object_ids=[])
        errors = validate_object(obj)
        self.assertTrue(any(">=1 source_object_ids" in e for e in errors))

    def test_missing_body_reported(self):
        from tests.test_ingest import insight
        obj = insight()
        del obj["body"]
        errors = validate_object(obj)
        self.assertTrue(any("Insight missing field 'body'" in e for e in errors))

    def test_candidate_insight_rejected(self):
        # 1차 제약(critic 검토 2): candidate Insight는 노출 통로가 없어 적재 거부.
        from tests.test_ingest import insight
        obj = insight(status="candidate")
        errors = validate_object(obj)
        self.assertTrue(any("candidate Insight not supported" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
