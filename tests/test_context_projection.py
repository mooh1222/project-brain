"""build_reuse_projection 단위 테스트 (Task A2).

candidate prompt_payload projection을 생성하고 스키마 검증(validate_object)이
통과하는지 확인한다. projection_hash와 source_content_hash가 모두 채워지는지
필수 필드 기준으로 검증한다.
"""

import unittest

from project_brain.context_projection import build_reuse_projection
from project_brain.objbase import base
from project_brain.store import BrainStore

T = "2026-06-17T00:00:00Z"


def _context(cid="context.sally-canoe", *, context_key="sally-canoe"):
    """DomainContext 최소 픽스처."""
    return base(
        {
            "id": cid,
            "kind": "DomainContext",
            "status": "reviewed",
            "truth_role": "domain",
            "title": "샐리 카누",
            "context_key": context_key,
            "project_id": "neutral-proj",
            "display_name": "Sally Canoe",
            "boundary_summary": "샐리 카누 이벤트 경계",
            "in_scope": ["경주"],
            "out_of_scope": [],
            "injection_profile": {"default_audience": "coding-agent"},
            "glossary_term_ids": [],
        },
        tags=[], created_at=T, updated_at=T,
    )


def _mapping(mid="mapping.sally-canoe.race-end-result-achieve", context_id="context.sally-canoe"):
    """DomainMapping 최소 픽스처(candidate 수준)."""
    return base(
        {
            "id": mid,
            "kind": "DomainMapping",
            "status": "candidate",
            "truth_role": "domain",
            "title": "경주 결과 달성 매핑",
            "context_id": context_id,
            "mapping_key": "race-end-result-achieve",
            "canonical_summary": "경주 종료 결과 달성",
            "meaning": "경주가 끝난 뒤 결과 달성 여부",
            "boundary": "경주 종료 시점",
            "glossary_term_ids": [],
            "decision_record_ids": [],
        },
        tags=[], created_at=T, updated_at=T,
    )


def _store_with(objs):
    return BrainStore({o["id"]: o for o in objs})


class TestBuildReuseProjection(unittest.TestCase):
    """build_reuse_projection — 필수 필드·스키마 통과 검증."""

    def _make_proj(self):
        store = _store_with([
            _context("context.sally-canoe", context_key="sally-canoe"),
            _mapping("mapping.sally-canoe.race-end-result-achieve", "context.sally-canoe"),
        ])
        return build_reuse_projection(
            store,
            context_id="context.sally-canoe",
            requirement_key="result-popup-rank",
            source_object_ids=["mapping.sally-canoe.race-end-result-achieve"],
            reuse_payload="데이터 출처: RaceInfo recordMap...",
            title="샐리 결과 팝업 순위 표시",
            generated_at=T,
            generated_by="bb2-brain-query",
        )

    def test_build_reuse_projection_validates(self):
        from project_brain.schema import validate_object
        proj = self._make_proj()

        self.assertEqual(proj["status"], "candidate")
        self.assertEqual(proj["format"], "prompt_payload")
        self.assertEqual(proj["id"], "projection.sally-canoe.result-popup-rank.reuse")
        self.assertTrue(proj["projection_hash"], "projection_hash는 비면 안 됨")
        self.assertTrue(proj["source_content_hash"], "source_content_hash는 비면 안 됨")
        self.assertEqual(validate_object(proj), [])  # 스키마 통과

    def test_id_uses_context_key_not_context_id(self):
        """context_key('sally-canoe')를 id에 쓰고 context_id 전체를 쓰지 않는다."""
        proj = self._make_proj()
        self.assertIn("sally-canoe", proj["id"])
        self.assertNotIn("context.sally-canoe", proj["id"])

    def test_projection_hash_matches_reuse_payload(self):
        """projection_hash는 reuse_payload 텍스트의 sha256이다."""
        from project_brain.hash_utils import sha256_text
        proj = self._make_proj()
        expected = sha256_text("데이터 출처: RaceInfo recordMap...")
        self.assertEqual(proj["projection_hash"], expected)

    def test_stale_policy_is_fail_on_manual_edit(self):
        proj = self._make_proj()
        self.assertEqual(proj["stale_policy"], "fail_on_manual_edit")


if __name__ == "__main__":
    unittest.main()
