"""promote() single_object 모드 단위 테스트 (Task 2).
새 중립 합성 데이터(인라인 dict)만 사용한다 — 삭제된 fixture/테스트/폐기 스크립트
데이터 미참조. promote는 build_reviewed_terms(폐기 ingest_mina_kayak_source.py)의
변환을 흡수하되 GlossaryTerm 전용 title 문구는 제외(spec §3.2)."""

import unittest

from project_brain.objbase import base
from project_brain.promote import (
    promote,
    vouching_mappings,
    backfill_evidence,
    select_vouched_candidates,
)
from project_brain.schema import validate_mutation_input_schema
from project_brain.store import BrainStore

T = "2026-06-04T00:00:00Z"


def candidate_term(tid, *, candidate=None, term="용어", title="Candidate term: 용어"):
    """승격 대상 candidate GlossaryTerm 한 개를 만든다(중립 합성)."""
    if candidate is None:
        candidate = {
            "candidate_state": "ready_for_review",
            "candidate_source": "spec",
            "promotion_criteria": ["spec confirmed"],
        }
    return base(
        {
            "id": tid,
            "kind": "GlossaryTerm",
            "status": "candidate",
            "truth_role": "domain",
            "title": title,
            "context_id": "context.neutral",
            "term": term,
            "definition": "중립 정의",
            "evidence_refs": ["ev.ref"],
            "candidate": candidate,
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


class TestSingleObject(unittest.TestCase):
    def test_omitted_reviewed_at_remains_unset_until_mutation(self):
        promoted, records = promote(
            [candidate_term("g.neutral.x")],
            ["g.neutral.x"],
            "single_object",
            reviewer="user-confirmed",
            reviewed_at=None,
        )

        self.assertNotIn("updated_at", promoted[0])
        self.assertFalse(
            {"created_at", "updated_at", "reviewed_at"} & records[0].keys()
        )

    def test_single_object_promotes_candidate_glossary(self):
        objs = [candidate_term("g.neutral.x")]
        promoted, records = promote(
            objs, ["g.neutral.x"], "single_object", reviewer="user-confirmed", reviewed_at=T,
        )
        self.assertEqual(len(promoted), 1)
        p = promoted[0]
        self.assertEqual(p["status"], "reviewed")
        self.assertNotIn("candidate", p)
        self.assertNotIn("updated_at", p)
        self.assertEqual(p["review_record_id"], "review.g.neutral.x")
        self.assertEqual(len(records), 1)
        rr = records[0]
        self.assertEqual(rr["target_object_id"], "g.neutral.x")
        self.assertNotIn("target_object_ids", rr)
        self.assertEqual(rr["verdict"], "approved")
        self.assertEqual(rr["reviewer"], "user-confirmed")
        self.assertEqual(rr["reviewed_at"], T)
        self.assertEqual(rr["evidence_refs"], p["evidence_refs"])

    def test_single_object_promoted_passes_schema(self):
        objs = [candidate_term("g.neutral.x")]
        promoted, records = promote(
            objs, ["g.neutral.x"], "single_object", reviewer="user-confirmed", reviewed_at=T,
        )
        self.assertEqual(
            validate_mutation_input_schema(
                promoted[0], omitted_required_fields=frozenset({"updated_at"})
            ),
            [],
        )
        self.assertEqual(
            validate_mutation_input_schema(
                records[0],
                omitted_required_fields=frozenset({"created_at", "updated_at"}),
            ),
            [],
        )

    def test_single_object_drops_conflict_candidate(self):
        conflict = {
            "candidate_state": "conflict",
            "candidate_source": "spec",
            "conflicts_with": ["g.other"],
        }
        objs = [candidate_term("g.neutral.c", candidate=conflict)]
        promoted, _ = promote(
            objs, ["g.neutral.c"], "single_object", reviewer="user-confirmed", reviewed_at=T,
        )
        self.assertNotIn("candidate", promoted[0])
        self.assertEqual(
            validate_mutation_input_schema(
                promoted[0], omitted_required_fields=frozenset({"updated_at"})
            ),
            [],
        )

    def test_single_object_does_not_rewrite_title(self):
        objs = [candidate_term("g.neutral.x", title="원본 제목")]
        promoted, _ = promote(
            objs, ["g.neutral.x"], "single_object", reviewer="user-confirmed", reviewed_at=T,
        )
        self.assertEqual(promoted[0]["title"], "원본 제목")

    def test_single_object_unknown_id_raises(self):
        objs = [candidate_term("g.neutral.x")]
        with self.assertRaises((KeyError, ValueError)):
            promote(
                objs,
                ["g.neutral.missing"],
                "single_object",
                reviewer="user-confirmed",
                reviewed_at=T,
            )

    def test_single_object_noncanonical_target_id_is_rejected(self):
        objs = [candidate_term("bad_target")]
        with self.assertRaises(ValueError):
            promote(
                objs,
                ["bad_target"],
                "single_object",
                reviewer="user-confirmed",
                reviewed_at=T,
            )

    def test_single_object_merges_review_extra(self):
        objs = [candidate_term("g.neutral.x")]
        promoted, records = promote(
            objs, ["g.neutral.x"], "single_object",
            reviewer="auto:mapping-vouched", reviewed_at=T,
            review_extra_by_id={
                "g.neutral.x": {
                    "vouched_by_mapping_ids": [
                        "mapping.neutral.z",
                        "mapping.neutral.a",
                    ]
                }
            },
        )
        rr = records[0]
        self.assertEqual(rr["reviewer"], "auto:mapping-vouched")
        self.assertEqual(
            rr["vouched_by_mapping_ids"],
            ["mapping.neutral.z", "mapping.neutral.a"],
        )
        # 추가 필드가 있어도 mutation 전 스키마를 통과한다.
        self.assertEqual(
            validate_mutation_input_schema(
                rr,
                omitted_required_fields=frozenset({"created_at", "updated_at"}),
            ),
            [],
        )

    def test_single_object_no_extra_when_absent(self):
        objs = [candidate_term("g.neutral.x")]
        _, records = promote(
            objs, ["g.neutral.x"], "single_object", reviewer="user-confirmed", reviewed_at=T,
        )
        self.assertNotIn("vouched_by_mapping_ids", records[0])


def candidate_mapping(mid, *, mapping_key="key", title="Candidate mapping: key"):
    """승격 대상 candidate DomainMapping 한 개를 만든다(중립 합성)."""
    return base(
        {
            "id": mid,
            "kind": "DomainMapping",
            "status": "candidate",
            "truth_role": "domain",
            "title": title,
            "context_id": "context.neutral",
            "mapping_key": mapping_key,
            "canonical_summary": "중립 요약",
            "meaning": "중립 의미",
            "boundary": "중립 경계",
            "glossary_term_ids": ["g.x"],
            "decision_record_ids": ["d.x"],
            "evidence_refs": ["ev.ref"],
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


class TestMappingBundle(unittest.TestCase):
    def test_mapping_bundle_promotes_all_members(self):
        objs = [
            candidate_mapping("mapping.neutral.one", mapping_key="one"),
            candidate_mapping("mapping.neutral.two", mapping_key="two"),
        ]
        promoted, _ = promote(
            objs, ["mapping.neutral.one", "mapping.neutral.two"], "mapping_bundle",
            bundle_key="bundle.neutral.domain-mapping",
            reviewer="user-confirmed", reviewed_at=T,
        )
        self.assertEqual(len(promoted), 2)
        for p in promoted:
            self.assertEqual(p["status"], "reviewed")
            self.assertEqual(
                p["review_record_id"],
                "review.bundle.neutral.domain-mapping",
            )
            self.assertEqual(
                p["review_state"],
                {"meaning_reviewed": True, "evidence_reviewed": True, "projection_reviewed": True},
            )
            self.assertNotIn("implementation_reviewed", p["review_state"])
            self.assertNotIn("candidate", p)

    def test_mapping_bundle_builds_single_review_record(self):
        objs = [
            candidate_mapping("mapping.neutral.one", mapping_key="one"),
            candidate_mapping("mapping.neutral.two", mapping_key="two"),
        ]
        _, records = promote(
            objs, ["mapping.neutral.one", "mapping.neutral.two"], "mapping_bundle",
            bundle_key="bundle.neutral.domain-mapping",
            reviewer="user-confirmed", reviewed_at=T,
        )
        self.assertEqual(len(records), 1)
        rr = records[0]
        self.assertEqual(rr["id"], "review.bundle.neutral.domain-mapping")
        self.assertEqual(rr["review_scope"], "mapping_bundle")
        self.assertEqual(rr["review_type"], "meaning_review")
        self.assertEqual(
            rr["target_object_ids"],
            ["mapping.neutral.one", "mapping.neutral.two"],
        )
        self.assertEqual(rr["bundle_key"], "bundle.neutral.domain-mapping")
        self.assertEqual(rr["confirmation_key"], "bundle.neutral.domain-mapping")

    def test_mapping_bundle_passes_schema(self):
        objs = [
            candidate_mapping("mapping.neutral.one", mapping_key="one"),
            candidate_mapping("mapping.neutral.two", mapping_key="two"),
        ]
        promoted, records = promote(
            objs, ["mapping.neutral.one", "mapping.neutral.two"], "mapping_bundle",
            bundle_key="bundle.neutral.domain-mapping",
            reviewer="user-confirmed", reviewed_at=T,
        )
        for p in promoted:
            self.assertEqual(
                validate_mutation_input_schema(
                    p, omitted_required_fields=frozenset({"updated_at"})
                ),
                [],
            )
        self.assertEqual(
            validate_mutation_input_schema(
                records[0],
                omitted_required_fields=frozenset({"created_at", "updated_at"}),
            ),
            [],
        )

    def test_mapping_bundle_requires_bundle_key(self):
        objs = [candidate_mapping("mapping.neutral.one", mapping_key="one")]
        with self.assertRaises(ValueError):
            promote(
                objs, ["mapping.neutral.one"], "mapping_bundle",
                bundle_key=None, reviewer="user-confirmed", reviewed_at=T,
            )


def _ev_ref(rid):
    """store.has 통과용 최소 EvidenceRef (backfill은 store.has만 본다)."""
    return base(
        {
            "id": rid,
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "title": "ref",
            "evidence_manifest_id": "ev.manifest",
            "ref_type": "spec_section",
            "locator": {"section": "1"},
            "summary": "인용",
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def _reviewed_mapping(mid, *, term_ids, evidence_refs, mapping_key="key"):
    """짝 매핑 — reviewed DomainMapping."""
    return base(
        {
            "id": mid,
            "kind": "DomainMapping",
            "status": "reviewed",
            "truth_role": "domain",
            "title": "매핑",
            "context_id": "context.neutral",
            "mapping_key": mapping_key,
            "canonical_summary": "요약",
            "meaning": "의미",
            "boundary": "경계",
            "glossary_term_ids": term_ids,
            "decision_record_ids": [],
            "evidence_refs": evidence_refs,
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def _empty_candidate(tid, *, term="용어", candidate_state="evidence_verified"):
    """evidence_refs 빈 candidate GlossaryTerm."""
    return base(
        {
            "id": tid,
            "kind": "GlossaryTerm",
            "status": "candidate",
            "truth_role": "domain",
            "title": "Candidate term: 용어",
            "context_id": "context.neutral",
            "term": term,
            "definition": "정의",
            "evidence_refs": [],
            "candidate": {"candidate_state": candidate_state, "candidate_source": "spec"},
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def _store(*objs):
    return BrainStore({o["id"]: o for o in objs})


class TestBackfillEvidence(unittest.TestCase):
    def test_empty_term_filled_from_paired_mapping(self):
        store = _store(
            _ev_ref("evref.a"),
            _empty_candidate("g.e"),
            _reviewed_mapping("m.e", term_ids=["g.e"], evidence_refs=["evref.a"]),
        )
        out = backfill_evidence(store.get("g.e"), store)
        self.assertEqual(out["evidence_refs"], ["evref.a"])
        # 원본 불변 (새 dict 반환)
        self.assertEqual(store.get("g.e")["evidence_refs"], [])

    def test_term_with_evidence_unchanged(self):
        term = _empty_candidate("g.e")
        term["evidence_refs"] = ["evref.existing"]
        store = _store(
            _ev_ref("evref.existing"),
            term,
            _reviewed_mapping("m.e", term_ids=["g.e"], evidence_refs=["evref.a"]),
        )
        out = backfill_evidence(store.get("g.e"), store)
        self.assertEqual(out["evidence_refs"], ["evref.existing"])

    def test_no_paired_mapping_stays_empty(self):
        store = _store(_empty_candidate("g.e"))
        out = backfill_evidence(store.get("g.e"), store)
        self.assertEqual(out["evidence_refs"], [])

    def test_dangling_mapping_ref_excluded(self):
        store = _store(
            _ev_ref("evref.a"),
            _empty_candidate("g.e"),
            # evref.gone 은 store에 없음 → backfill에서 제외
            _reviewed_mapping("m.e", term_ids=["g.e"], evidence_refs=["evref.a", "evref.gone"]),
        )
        out = backfill_evidence(store.get("g.e"), store)
        self.assertEqual(out["evidence_refs"], ["evref.a"])

    def test_candidate_mapping_does_not_vouch(self):
        # candidate 상태 매핑은 보증하지 않는다 (reviewed만).
        cand_map = _reviewed_mapping("m.c", term_ids=["g.e"], evidence_refs=["evref.a"])
        cand_map["status"] = "candidate"
        store = _store(_ev_ref("evref.a"), _empty_candidate("g.e"), cand_map)
        out = backfill_evidence(store.get("g.e"), store)
        self.assertEqual(out["evidence_refs"], [])


class TestSelectVouchedCandidates(unittest.TestCase):
    def test_includes_observed_and_evidence_verified(self):
        store = _store(
            _ev_ref("evref.a"),
            _empty_candidate("g.obs", candidate_state="observed"),
            _empty_candidate("g.ev", candidate_state="evidence_verified"),
            _reviewed_mapping("m1", term_ids=["g.obs", "g.ev"], evidence_refs=["evref.a"]),
        )
        sel = select_vouched_candidates(store)
        self.assertEqual(set(sel), {"g.obs", "g.ev"})

    def test_excludes_conflict(self):
        store = _store(
            _ev_ref("evref.a"),
            _empty_candidate("g.c", candidate_state="conflict"),
            _reviewed_mapping("m1", term_ids=["g.c"], evidence_refs=["evref.a"]),
        )
        self.assertEqual(select_vouched_candidates(store), {})

    def test_excludes_unreferenced(self):
        store = _store(_empty_candidate("g.lonely"))
        self.assertEqual(select_vouched_candidates(store), {})

    def test_multi_mapping_collects_all_sorted(self):
        store = _store(
            _ev_ref("evref.a"),
            _ev_ref("evref.b"),
            _empty_candidate("g.multi"),
            _reviewed_mapping("m.z", term_ids=["g.multi"], evidence_refs=["evref.b"], mapping_key="z"),
            _reviewed_mapping("m.a", term_ids=["g.multi"], evidence_refs=["evref.a"], mapping_key="a"),
        )
        sel = select_vouched_candidates(store)
        self.assertEqual(sel, {"g.multi": ["m.a", "m.z"]})  # 정렬됨

    def test_candidate_mapping_does_not_select(self):
        cand_map = _reviewed_mapping("m.c", term_ids=["g.e"], evidence_refs=["evref.a"])
        cand_map["status"] = "candidate"
        store = _store(_ev_ref("evref.a"), _empty_candidate("g.e"), cand_map)
        self.assertEqual(select_vouched_candidates(store), {})


class TestVouchingMappings(unittest.TestCase):
    def test_returns_reviewed_mappings_sorted_by_id(self):
        store = _store(
            _ev_ref("evref.a"),
            _empty_candidate("g.x"),
            _reviewed_mapping("m.b", term_ids=["g.x"], evidence_refs=["evref.a"], mapping_key="b"),
            _reviewed_mapping("m.a", term_ids=["g.x"], evidence_refs=["evref.a"], mapping_key="a"),
        )
        ms = vouching_mappings("g.x", store)
        self.assertEqual([m["id"] for m in ms], ["m.a", "m.b"])


if __name__ == "__main__":
    unittest.main()
