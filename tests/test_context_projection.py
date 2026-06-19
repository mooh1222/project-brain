"""build_reuse_projection 단위 테스트 (Task A2).

candidate prompt_payload projection을 생성하고 스키마 검증(validate_object)이
통과하는지 확인한다. projection_hash와 source_content_hash가 모두 채워지는지
필수 필드 기준으로 검증한다.
"""

import unittest

from project_brain.context_projection import build_reuse_projection
from project_brain.lint import projection_is_fresh
from project_brain.objbase import base
from project_brain.store import BrainStore

T = "2026-06-17T00:00:00Z"


def _context(cid="context.mina-kayak", *, context_key="mina-kayak"):
    """DomainContext 최소 픽스처."""
    return base(
        {
            "id": cid,
            "kind": "DomainContext",
            "status": "reviewed",
            "truth_role": "domain",
            "title": "미나 카약",
            "context_key": context_key,
            "project_id": "neutral-proj",
            "display_name": "Mina Kayak",
            "boundary_summary": "미나 카약 이벤트 경계",
            "in_scope": ["경주"],
            "out_of_scope": [],
            "injection_profile": {"default_audience": "coding-agent"},
            "glossary_term_ids": [],
        },
        tags=[], created_at=T, updated_at=T,
    )


def _mapping(mid="mapping.mina-kayak.race-end-result-achieve", context_id="context.mina-kayak"):
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
            _context("context.mina-kayak", context_key="mina-kayak"),
            _mapping("mapping.mina-kayak.race-end-result-achieve", "context.mina-kayak"),
        ])
        return build_reuse_projection(
            store,
            context_id="context.mina-kayak",
            requirement_key="result-popup-rank",
            source_object_ids=["mapping.mina-kayak.race-end-result-achieve"],
            reuse_payload="데이터 출처: RaceInfo recordMap...",
            title="미나 결과 팝업 순위 표시",
            generated_at=T,
            generated_by="demo-brain-query",
        )

    def test_build_reuse_projection_validates(self):
        from project_brain.schema import validate_object
        proj = self._make_proj()

        self.assertEqual(proj["status"], "candidate")
        self.assertEqual(proj["format"], "prompt_payload")
        self.assertEqual(proj["id"], "projection.mina-kayak.result-popup-rank.reuse")
        self.assertTrue(proj["projection_hash"], "projection_hash는 비면 안 됨")
        self.assertTrue(proj["source_content_hash"], "source_content_hash는 비면 안 됨")
        self.assertEqual(validate_object(proj), [])  # 스키마 통과

    def test_id_uses_context_key_not_context_id(self):
        """context_key('mina-kayak')를 id에 쓰고 context_id 전체를 쓰지 않는다."""
        proj = self._make_proj()
        self.assertIn("mina-kayak", proj["id"])
        self.assertNotIn("context.mina-kayak", proj["id"])

    def test_projection_hash_matches_reuse_payload(self):
        """projection_hash는 reuse_payload 텍스트의 sha256이다."""
        from project_brain.hash_utils import sha256_text
        proj = self._make_proj()
        expected = sha256_text("데이터 출처: RaceInfo recordMap...")
        self.assertEqual(proj["projection_hash"], expected)

    def test_stale_policy_is_fail_on_manual_edit(self):
        proj = self._make_proj()
        self.assertEqual(proj["stale_policy"], "fail_on_manual_edit")


class TestBuildReuseFreshnessRoundtrip(unittest.TestCase):
    """build_reuse_projection(생성식)이 박은 source_content_hash ↔ projection_is_fresh
    (검사식, lint._compute_source_content_hash 경유)가 동치임을 고정한다. 두 해시 공식
    중 한쪽만 직렬화가 바뀌어도 이 라운드트립이 깨져 잡힌다(현재 별도 미커버)."""

    def _store_and_proj(self):
        store = _store_with([
            _context("context.mina-kayak", context_key="mina-kayak"),
            _mapping("mapping.mina-kayak.race-end-result-achieve", "context.mina-kayak"),
        ])
        proj = build_reuse_projection(
            store,
            context_id="context.mina-kayak",
            requirement_key="result-popup-rank",
            source_object_ids=["mapping.mina-kayak.race-end-result-achieve"],
            reuse_payload="데이터 출처: RaceInfo recordMap...",
            title="미나 결과 팝업 순위 표시",
            generated_at=T,
            generated_by="demo-brain-query",
        )
        return store, proj

    def test_built_projection_is_fresh_against_same_store(self):
        # 생성 직후, 구성 객체가 그대로인 store에서는 fresh=True.
        store, proj = self._store_and_proj()
        self.assertTrue(projection_is_fresh(store, proj))

    def test_mutating_source_object_makes_projection_stale(self):
        # 구성 객체(source mapping)를 변형하면 재계산 해시가 어긋나 fresh=False.
        store, proj = self._store_and_proj()
        store.get("mapping.mina-kayak.race-end-result-achieve")["meaning"] = "변형된 의미"
        self.assertFalse(projection_is_fresh(store, proj))


class TestDanglingSourceMakesStale(unittest.TestCase):
    """외부 리뷰 재현(Important 1): source_object_ids가 store에 없는 id를 가리키는데도
    source_content_hash가 sha256("")(없는 id는 _compute_source_content_hash가 조용히 건너뜀)
    이라 fresh=True로 통과해버리는 문제. dangling source는 stale로 판정해야 한다."""

    def test_dangling_source_projection_is_stale(self):
        from project_brain.hash_utils import sha256_text
        store = BrainStore({})  # missing.source가 store에 없다
        proj = {
            "id": "projection.x.req.reuse",
            "kind": "ContextProjection",
            "source_object_ids": ["missing.source"],
            "source_content_hash": sha256_text(""),  # 없는 id를 건너뛴 결과와 동일
        }
        # dangling source → fresh가 아니어야 함(rebuild/fingerprint가 색인에서 뺀다).
        self.assertFalse(projection_is_fresh(store, proj))


if __name__ == "__main__":
    unittest.main()
