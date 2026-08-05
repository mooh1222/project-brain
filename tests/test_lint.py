"""lint.py 회귀 베이스라인 (B+C 작업 선행). 깨끗한 합성 store는 0 problem,
dangling evidence_ref는 1 problem. promote 사후 lint가 의존하는 동작을 고정한다."""

import unittest

from project_brain.lint import (
    LintProblem,
    lint_mutation_input_store_report,
    lint_store,
    lint_store_report,
    unpromoted_vouched_terms,
)
from project_brain.objbase import base
from project_brain.store import BrainStore
from tests.test_ingest import (
    candidate_term,
    context,
    evidence_ref,
    malformed_reference_cases,
    manifest,
    reviewed_term,
    review_record_for,
)

T = "2026-06-04T00:00:00Z"


def store_of(*objs):
    return BrainStore({o["id"]: o for o in objs})


def _change_event():
    return base(
        {
            "id": "ledger.neutral.change",
            "kind": "EventLedgerRecord",
            "status": "reviewed",
            "truth_role": "event",
            "title": "변경 사건",
            "event_type": "rule_change",
            "happened_at": T,
            "summary": "합성 변경 사건",
            "related_objects": [],
            "evidence_refs": [],
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _temporal_fact(fid, *, value, supersedes=None, closed=False):
    obj = {
        "id": fid,
        "kind": "TemporalFact",
        "status": "reviewed",
        "truth_role": "fact",
        "title": "시간 사실",
        "subject": "합성 규칙",
        "predicate": "enabled",
        "value": value,
        "scope": {"release": "test"},
        "valid_from": T,
        "derived_from_event_id": "ledger.neutral.change",
        "confidence": "high",
        "evidence_refs": [],
    }
    if supersedes is not None:
        obj["supersedes"] = supersedes
    if closed:
        obj["valid_until"] = T
    return base(obj, tags=["neutral"], created_at=T, updated_at=T)


class TestLintStore(unittest.TestCase):
    def test_mutation_input_lint_opt_in_does_not_weaken_default_lint(self):
        locator = base(
            {
                "id": "code.neutral.foo",
                "kind": "CodeLocator",
                "status": "reviewed",
                "truth_role": "reference",
                "title": "Foo::bar",
                "repo": "demo",
                "path": "Foo.cpp",
                "symbol": "Foo::bar",
                "commit_sha": "a" * 40,
                "locator_source": "rg",
                "verified_quote": "void Foo::bar() {}",
            },
            tags=["neutral"],
            created_at=T,
            updated_at=T,
        )
        store = store_of(locator)

        self.assertTrue(
            any("verified_at" in problem.message for problem in lint_store_report(store))
        )
        self.assertEqual(
            lint_mutation_input_store_report(store, operation="ingest"),
            (),
        )

    def test_mutation_input_lint_does_not_allow_missing_engine_fields_before_task6(self):
        projection = _projection(
            source_object_ids=[],
            source_content_hash="e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855",
        )
        del projection["generated_at"]

        report = lint_mutation_input_store_report(
            store_of(projection),
            operation="projection",
        )

        assert any(
            problem.code == "schema" and "generated_at" in problem.message
            for problem in report
        )

    def test_structured_report_keeps_wrapper_messages_compatible(self):
        term = candidate_term()
        term["evidence_refs"] = ["evref.neutral.missing"]
        store = store_of(context(), term)
        report = lint_store_report(store)

        self.assertEqual(
            report,
            (
                LintProblem(
                    code="dangling_reference",
                    object_ids=("g.neutral.x",),
                    message=(
                        "g.neutral.x: dangling evidence_ref "
                        "evref.neutral.missing"
                    ),
                ),
            ),
        )
        self.assertEqual(lint_store(store), [problem.message for problem in report])

    def test_invalid_id_and_unknown_grammar_have_distinct_codes(self):
        invalid = context("context.Bad")
        invalid["context_key"] = "Bad"
        unknown = context("mystery.neutral")
        unknown["context_key"] = "neutral"

        invalid_report = lint_store_report(store_of(invalid))
        unknown_report = lint_store_report(store_of(unknown))

        self.assertTrue(invalid_report)
        self.assertEqual({problem.code for problem in invalid_report}, {"invalid_id"})
        self.assertTrue(unknown_report)
        self.assertEqual({problem.code for problem in unknown_report}, {"unknown_grammar"})

    def test_nested_review_target_with_unknown_prefix_is_unknown_grammar(self):
        review = review_record_for(
            "review.legacy.target",
            "legacy.target",
        )

        report = lint_store_report(store_of(review))

        id_codes = {
            problem.code
            for problem in report
            if "invalid id" in problem.message
        }
        self.assertEqual(id_codes, {"unknown_grammar"})

    def test_clean_store_no_problems(self):
        store = store_of(manifest(), evidence_ref(), context(), candidate_term())
        self.assertEqual(lint_store(store), [])

    def test_dangling_evidence_ref_reported(self):
        term = candidate_term()
        term["evidence_refs"] = ["ev.missing"]
        store = store_of(term)
        problems = lint_store(store)
        self.assertTrue(any("dangling evidence_ref ev.missing" in p for p in problems))

    def test_nested_code_locator_dangling_reported(self):
        ref = evidence_ref()
        ref["locator"] = {"code_locator_id": "code.neutral.missing"}
        problems = lint_store(store_of(manifest(), ref))
        self.assertTrue(
            any("dangling code_locator_id code.neutral.missing" in p for p in problems),
            problems,
        )

    def test_external_ids_are_not_dangling_brain_references(self):
        decision = base(
            {
                "id": "decision.neutral.external-ids",
                "kind": "DecisionRecord",
                "status": "candidate",
                "truth_role": "event",
                "title": "외부 ID",
                "decision_type": "implementation_boundary",
                "summary": "외부 시스템 ID는 Brain 참조가 아니다.",
                "decision": "외부 ID를 그대로 둔다.",
                "source_object_ids": [],
                "affected_context_ids": [],
                "spec_reflected": "not_applicable",
                "jira_issue_ids": ["LGBBTWO-234"],
                "channel_id": "C123",
                "project_id": "bb2",
                "evidence_refs": [],
            },
            tags=["neutral"],
            created_at=T,
            updated_at=T,
        )

        problems = lint_store(store_of(decision))

        self.assertFalse([p for p in problems if "dangling" in p], problems)

    def test_malformed_reference_types_are_rejected(self):
        for label, obj, expected in malformed_reference_cases():
            with self.subTest(label=label):
                self.assertIn(expected, lint_store(store_of(obj)))

    def test_schema_invalid_reference_items_do_not_escape_semantic_lint(self):
        term = reviewed_term(evidence_refs=[{"bad": "id"}])

        mapping = _drift_mapping("mapping.neutral.invalid-ref", term_ids=[])
        mapping["mapping_key"] = "invalid-ref"
        mapping["supersedes_mapping_ids"] = [{"bad": "id"}]

        decision = base(
            {
                "id": "decision.neutral.invalid-ref",
                "kind": "DecisionRecord",
                "status": "candidate",
                "truth_role": "event",
                "title": "잘못된 참조 타입",
                "decision_type": "implementation_boundary",
                "summary": "합성 결정",
                "decision": "참조 타입 검증",
                "source_object_ids": [],
                "affected_context_ids": [],
                "affected_mapping_ids": [{"bad": "id"}],
                "spec_reflected": "not_applicable",
                "evidence_refs": [],
            },
            tags=["neutral"],
            created_at=T,
            updated_at=T,
        )

        projection = _projection(
            source_object_ids=[{"bad": "id"}],
            source_content_hash="invalid-object-is-not-semantically-linted",
        )

        cases = (
            (
                term,
                "g.neutral.x",
                "evidence_refs",
            ),
            (
                mapping,
                "mapping.neutral.invalid-ref",
                "supersedes_mapping_ids",
            ),
            (
                decision,
                "decision.neutral.invalid-ref",
                "affected_mapping_ids",
            ),
            (
                projection,
                "projection.x.req.reuse",
                "source_object_ids",
            ),
        )
        for obj, object_id, field in cases:
            with self.subTest(field=field):
                problems = lint_store(store_of(obj))
                self.assertEqual(
                    [problem for problem in problems if "reference field" in problem],
                    [
                        f"{object_id}: reference field {field!r} at /{field}/0 "
                        "must be a string, got dict"
                    ],
                )

    def test_valid_term_does_not_dereference_schema_invalid_evidence_ref(self):
        bad_ref = evidence_ref()
        bad_ref["evidence_manifest_id"] = {"bad": "id"}
        term = reviewed_term(evidence_refs=["evref.neutral.ref"])

        self.assertEqual(
            lint_store(store_of(context(), bad_ref, term)),
            [
                "evref.neutral.ref: reference field 'evidence_manifest_id' at "
                "/evidence_manifest_id must be a string, got dict"
            ],
        )

    def test_valid_projection_does_not_hash_schema_invalid_source(self):
        from project_brain.hash_utils import source_content_hash

        bad_source = _drift_mapping(
            "mapping.neutral.invalid-source",
            term_ids=[],
        )
        bad_source["mapping_key"] = "invalid-source"
        bad_source["evidence_refs"] = [{"bad": "id"}]

        projection = _projection(
            pid="projection.neutral.req.reuse",
            source_object_ids=["mapping.neutral.invalid-source"],
            source_content_hash=source_content_hash([]),
        )
        projection["context_id"] = "context.neutral"

        self.assertEqual(
            lint_store(
                store_of(
                    context(),
                    manifest(),
                    evidence_ref(),
                    bad_source,
                    projection,
                )
            ),
            [
                "mapping.neutral.invalid-source: reference field 'evidence_refs' at "
                "/evidence_refs/0 must be a string, got dict"
            ],
        )

    def test_valid_mapping_does_not_consume_schema_invalid_superseded_target(self):
        bad_old = _drift_mapping("mapping.neutral.old", term_ids=[])
        bad_old["mapping_key"] = "old"
        bad_old["evidence_refs"] = [{"bad": "id"}]

        current = _drift_mapping("mapping.neutral.current", term_ids=[])
        current["mapping_key"] = "current"
        current["evidence_refs"] = ["evref.neutral.ref"]
        current["supersedes_mapping_ids"] = ["mapping.neutral.old"]

        self.assertEqual(
            lint_store(
                store_of(
                    context(),
                    manifest(),
                    evidence_ref(),
                    bad_old,
                    current,
                )
            ),
            [
                "mapping.neutral.old: reference field 'evidence_refs' at "
                "/evidence_refs/0 must be a string, got dict"
            ],
        )

    def test_schema_invalid_source_keeps_safe_dangling_reference_diagnostics(self):
        term = candidate_term()
        term["status"] = "bogus"
        term["evidence_refs"] = ["ev.missing"]

        self.assertEqual(
            lint_store(store_of(context(), term)),
            [
                "g.neutral.x: invalid status 'bogus'",
                "g.neutral.x: dangling evidence_ref ev.missing",
            ],
        )

    def test_temporal_fact_supersedes_resolves_old_fact(self):
        old = _temporal_fact("fact.neutral.old", value=False, closed=True)
        new = _temporal_fact(
            "fact.neutral.new",
            value=True,
            supersedes="fact.neutral.old",
        )

        problems = lint_store(store_of(_change_event(), old, new))

        self.assertFalse([p for p in problems if "dangling" in p], problems)

    def test_temporal_fact_dangling_supersedes_reported(self):
        fact = _temporal_fact(
            "fact.neutral.new",
            value=True,
            supersedes="fact.neutral.missing",
        )

        problems = lint_store(store_of(_change_event(), fact))

        self.assertEqual(
            [p for p in problems if "dangling supersedes" in p],
            ["fact.neutral.new: dangling supersedes fact.neutral.missing"],
        )


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
        # C2 이후 해시는 시각·버전 메타를 제외하므로 fixture도 정본 헬퍼로 fresh하게 만든다
        # (옛 sha256_text(stable_json(src))는 stale가 돼 source_content_hash mismatch를 냈다).
        from project_brain.hash_utils import source_content_hash
        src = _drift_mapping("m.src", term_ids=[])
        proj = _projection(
            source_object_ids=["m.src"],
            source_content_hash=source_content_hash([src]),
        )
        problems = lint_store(store_of(src, proj))
        self.assertFalse([p for p in problems if "dangling source_object_id" in p], problems)


if __name__ == "__main__":
    unittest.main()
