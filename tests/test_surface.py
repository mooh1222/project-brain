"""surface.extract_surface / content_hash 결정론 검증.

spec: docs/superpowers/specs/2026-06-10-bb2-brain-search-layer-design.md §2.1·§4

합성 객체(objbase.base 픽스처 패턴 — test_ingest/test_router 참고)로 kind별 추출·
제외·해시 불변성(updated_at 변경 무영향 / status 변경 시 변경)을 결정론 검증한다.
(실코퍼스 표면 카운트 가드는 데이터 레포 쪽 CLI 가드로 옮겨졌다 — 2-레포 분리.)
"""

import unittest

from project_brain.objbase import base
from project_brain.store import BrainStore
from project_brain.surface import (
    EXTRACTOR_VERSION,
    content_hash,
    extract_surface,
)

T = "2026-06-04T00:00:00Z"


def store_of(*objs):
    return BrainStore({o["id"]: o for o in objs})


def _b(obj):
    return base(obj, tags=["neutral"], created_at=T, updated_at=T)


def glossary_term(tid="g.x", *, term="용어", definition="정의", status="reviewed",
                  synonyms=None, aliases=None, avoid=None, boundary=None):
    obj = {
        "id": tid, "kind": "GlossaryTerm", "status": status, "truth_role": "domain",
        "title": f"Term: {term}", "context_id": "context.neutral",
        "term": term, "definition": definition,
    }
    if synonyms is not None:
        obj["synonyms"] = synonyms
    if aliases is not None:
        obj["aliases"] = aliases
    if avoid is not None:
        obj["avoid"] = avoid
    if boundary is not None:
        obj["boundary"] = boundary
    if status == "candidate":
        obj["candidate"] = {"candidate_state": "ready_for_review", "candidate_source": "spec"}
    return _b(obj)


def domain_mapping(mid="m.x", *, glossary_term_ids, canonical_summary="요약",
                   meaning="의미", boundary="경계"):
    return _b({
        "id": mid, "kind": "DomainMapping", "status": "reviewed", "truth_role": "domain",
        "title": "매핑", "context_id": "context.neutral", "mapping_key": "key",
        "canonical_summary": canonical_summary, "meaning": meaning, "boundary": boundary,
        "glossary_term_ids": glossary_term_ids, "decision_record_ids": [],
        "caveats": ["history_coverage=unsearched"],
    })


def decision_record(did="d.x", *, summary="결정 요약", decision="결정 상세 이유"):
    return _b({
        "id": did, "kind": "DecisionRecord", "status": "reviewed", "truth_role": "event",
        "title": "결정", "decision_type": "improvement", "summary": summary,
        "decision": decision, "source_object_ids": [], "affected_context_ids": [],
        "spec_reflected": "unknown",
    })


def code_locator(cid="code.x", *, path="path/to/File.cpp", symbol="Foo::bar"):
    return _b({
        "id": cid, "kind": "CodeLocator", "status": "reviewed", "truth_role": "reference",
        "title": "코드", "repo": "bb2_client", "path": path, "symbol": symbol,
        "locator_source": "rg", "verified_at": T,
    })


def domain_context(cid="context.neutral", *, display_name="표시명",
                   boundary_summary="경계 요약"):
    return _b({
        "id": cid, "kind": "DomainContext", "status": "reviewed", "truth_role": "domain",
        "title": "컨텍스트", "context_key": "neutral", "project_id": "p",
        "display_name": display_name, "boundary_summary": boundary_summary,
        "in_scope": ["a"], "out_of_scope": ["b"],
        "injection_profile": {"default_audience": "coding-agent"}, "glossary_term_ids": [],
    })


def temporal_fact(fid="t.x", *, subject="주어", predicate="술어", value="값"):
    return _b({
        "id": fid, "kind": "TemporalFact", "status": "reviewed", "truth_role": "fact",
        "title": "팩트", "subject": subject, "predicate": predicate, "value": value,
        "scope": {}, "valid_from": T, "derived_from_event_id": "ev.x", "confidence": "high",
    })


class ExtractGlossaryTermTest(unittest.TestCase):
    def test_term_and_definition(self):
        surface = extract_surface(glossary_term(term="레이스", definition="카누 경주"), None)
        self.assertIn("레이스", surface)
        self.assertIn("카누 경주", surface)

    def test_synonyms_aliases_avoid_boundary_included_when_present(self):
        obj = glossary_term(
            term="getNextLevel", definition="다음 레벨 반환",
            synonyms=["NL", "NextRaceNo"], aliases=["별칭A"],
            avoid=["회피어"], boundary="경계설명",
        )
        surface = extract_surface(obj, None)
        for token in ("getNextLevel", "다음 레벨 반환", "NL", "NextRaceNo",
                      "별칭A", "회피어", "경계설명"):
            self.assertIn(token, surface)

    def test_missing_optional_fields_skipped(self):
        # synonyms/aliases/avoid/boundary 없는 객체도 term+definition만으로 표면 생성
        surface = extract_surface(glossary_term(term="용어", definition="정의"), None)
        self.assertEqual(surface, "용어\n정의")


class ExtractDomainMappingTest(unittest.TestCase):
    def test_own_fields(self):
        m = domain_mapping(glossary_term_ids=[], canonical_summary="요약txt",
                           meaning="의미txt", boundary="경계txt")
        surface = extract_surface(m, store_of(m))
        for token in ("요약txt", "의미txt", "경계txt"):
            self.assertIn(token, surface)

    def test_referenced_term_surface_delegated(self):
        # 참조 용어의 term/synonyms가 매핑 표면에 포함 (router._matched_mappings 계승)
        t = glossary_term("g.ref", term="targetStages", definition="목표 스테이지 수",
                          synonyms=["목표개수"], status="candidate")
        m = domain_mapping(glossary_term_ids=["g.ref"])
        surface = extract_surface(m, store_of(t, m))
        self.assertIn("targetStages", surface)
        self.assertIn("목표개수", surface)
        # 참조 용어의 definition은 매핑 표면에 포함하지 않음(라우터 매핑 경로와 동일)
        self.assertNotIn("목표 스테이지 수", surface)

    def test_referenced_term_aliases_not_delegated(self):
        # 매핑 표면 위임은 term+synonyms만 — aliases는 포함 안 함(router.py:379-397)
        t = glossary_term("g.ref", term="카누", definition="d",
                          aliases=["샐리의카누별칭"], status="reviewed",
                          synonyms=[])
        m = domain_mapping(glossary_term_ids=["g.ref"])
        surface = extract_surface(m, store_of(t, m))
        self.assertIn("카누", surface)
        self.assertNotIn("샐리의카누별칭", surface)

    def test_missing_referenced_id_skipped(self):
        # store에 없는 term_id는 건너뜀(KeyError 안 남)
        m = domain_mapping(glossary_term_ids=["g.absent"])
        surface = extract_surface(m, store_of(m))
        self.assertIsNotNone(surface)
        self.assertIn("의미", surface)


class ExtractOtherKindsTest(unittest.TestCase):
    def test_decision_record(self):
        surface = extract_surface(decision_record(summary="s요약", decision="d상세"), None)
        self.assertIn("s요약", surface)
        self.assertIn("d상세", surface)

    def test_code_locator_path_and_symbol(self):
        surface = extract_surface(
            code_locator(path="a/b/C.cpp", symbol="Foo::bar"), None)
        self.assertEqual(surface, "a/b/C.cpp\nFoo::bar")

    def test_domain_context(self):
        surface = extract_surface(
            domain_context(display_name="샐리 카누", boundary_summary="경계요약txt"), None)
        self.assertIn("샐리 카누", surface)
        self.assertIn("경계요약txt", surface)

    def test_temporal_fact(self):
        surface = extract_surface(
            temporal_fact(subject="주어x", predicate="술어x", value="값x"), None)
        for token in ("주어x", "술어x", "값x"):
            self.assertIn(token, surface)


class ExcludedKindTest(unittest.TestCase):
    def test_excluded_kinds_return_none(self):
        for kind in ("EvidenceManifest", "EvidenceRef", "ReviewRecord", "ContextProjection"):
            obj = {"id": f"x.{kind}", "kind": kind, "status": "reviewed", "summary": "텍스트"}
            self.assertIsNone(extract_surface(obj, None), kind)

    def test_unsupported_kind_returns_none(self):
        # §2.1 표에 없는 kind(예: KnowledgePage)는 None
        obj = {"id": "x.kp", "kind": "KnowledgePage", "status": "reviewed", "summary": "텍스트"}
        self.assertIsNone(extract_surface(obj, None))

    def test_empty_surface_returns_none(self):
        # 텍스트 필드가 다 비면 None (빈 행 색인 방지)
        obj = glossary_term(term="", definition="")
        self.assertIsNone(extract_surface(obj, None))


class ContentHashTest(unittest.TestCase):
    def test_deterministic(self):
        obj = glossary_term(term="레이스", definition="경주")
        self.assertEqual(content_hash(obj, None), content_hash(obj, None))

    def test_updated_at_change_does_not_change_hash(self):
        # 멱등 재저장(updated_at만 변경)은 해시 불변 (§4)
        a = glossary_term(term="레이스", definition="경주")
        b = glossary_term(term="레이스", definition="경주")
        b["updated_at"] = "2099-01-01T00:00:00Z"
        b["created_at"] = "2099-01-01T00:00:00Z"
        self.assertEqual(content_hash(a, None), content_hash(b, None))

    def test_status_change_changes_hash(self):
        a = glossary_term(term="레이스", definition="경주", status="candidate")
        b = glossary_term(term="레이스", definition="경주", status="reviewed")
        self.assertNotEqual(content_hash(a, None), content_hash(b, None))

    def test_surface_change_changes_hash(self):
        a = glossary_term(term="레이스", definition="경주")
        b = glossary_term(term="레이스", definition="다른 정의")
        self.assertNotEqual(content_hash(a, None), content_hash(b, None))

    def test_excluded_kind_still_hashes_deterministically(self):
        # 표면 None인 객체도 결정론 해시(빈 표면 + status)
        obj = {"id": "x.rr", "kind": "ReviewRecord", "status": "reviewed", "summary": "t"}
        self.assertEqual(content_hash(obj, None), content_hash(obj, None))


class ExtractorVersionTest(unittest.TestCase):
    def test_version_is_positive_int(self):
        self.assertIsInstance(EXTRACTOR_VERSION, int)
        self.assertGreaterEqual(EXTRACTOR_VERSION, 1)


if __name__ == "__main__":
    unittest.main()
