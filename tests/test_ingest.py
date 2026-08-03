"""ingest() 단위 테스트 (Task 4).

새 중립 합성 데이터(tempfile brain root + 인라인 dict 번들)만 사용한다 — 삭제된
fixture/테스트(test_store 등)/폐기 스크립트 데이터를 일절 참조하지 않고 자기완결.
ingest는 bundle 전체에 per-object validate → merged store lint → save 를 원자적으로
묶고(spec §3.1, §4.2), 멱등 갱신과 reviewed→candidate 후퇴 가드(유일 신규 로직,
spec §4.1)를 진입점에 둔다."""

import ast
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project_brain.ingest import IngestError, ingest as _product_ingest
from project_brain.objbase import base
from project_brain.store import BrainStore

T = "2026-06-04T00:00:00Z"
ENGINE_SHA = "e" * 40


def ingest(brain_root, objects, preconditions=None, **kwargs):
    """합성 테스트 writer도 exact engine SHA를 명시한다."""
    return _product_ingest(
        brain_root,
        objects,
        preconditions=preconditions,
        engine_sha=kwargs.pop("engine_sha", ENGINE_SHA),
        **kwargs,
    )


def manifest(mid="manifest.neutral.source"):
    """중립 EvidenceManifest 한 개."""
    return base(
        {
            "id": mid,
            "kind": "EvidenceManifest",
            "status": "reviewed",
            "truth_role": "source",
            "title": "중립 manifest",
            "source_type": "spec",
            "locator": "spec://neutral",
            "captured_at": T,
            "captured_by": "neutral",
            "sensitivity": "internal",
            "acl": ["team"],
            "redaction_status": "approved",
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def evidence_ref(
    rid="evref.neutral.ref",
    manifest_id="manifest.neutral.source",
):
    """중립 EvidenceRef 한 개. bundle 내 manifest를 가리킴."""
    return base(
        {
            "id": rid,
            "kind": "EvidenceRef",
            "status": "reviewed",
            "truth_role": "reference",
            "title": "중립 ref",
            "evidence_manifest_id": manifest_id,
            "ref_type": "spec_section",
            "locator": {"section": "1"},
            "summary": "중립 인용",
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def candidate_term(tid="g.neutral.x", *, term="용어"):
    """중립 candidate GlossaryTerm 한 개."""
    return base(
        {
            "id": tid,
            "kind": "GlossaryTerm",
            "status": "candidate",
            "truth_role": "domain",
            "title": "Candidate term: 용어",
            "context_id": "context.neutral",
            "term": term,
            "definition": "중립 정의",
            "candidate": {
                "candidate_state": "ready_for_review",
                "candidate_source": "spec",
                "promotion_criteria": ["spec confirmed"],
            },
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def reviewed_term(
    tid="g.neutral.x",
    *,
    term="용어",
    review_record_id=None,
    evidence_refs=None,
):
    """중립 reviewed GlossaryTerm 한 개(candidate 메타 없음). §6.4: reviewed는 근거 필수."""
    obj = {
        "id": tid,
        "kind": "GlossaryTerm",
        "status": "reviewed",
        "truth_role": "domain",
        "title": "Term: 용어",
        "context_id": "context.neutral",
        "term": term,
        "definition": "중립 정의",
        "evidence_refs": (
            evidence_refs if evidence_refs is not None else ["evref.neutral.ref"]
        ),
    }
    if review_record_id is not None:
        obj["review_record_id"] = review_record_id
    return base(obj, tags=["neutral"], created_at=T, updated_at=T)


def review_record_for(rrid, target_id):
    """중립 single_object ReviewRecord 한 개."""
    return base(
        {
            "id": rrid,
            "kind": "ReviewRecord",
            "status": "reviewed",
            "truth_role": "review",
            "title": "검수 기록",
            "target_object_id": target_id,
            "reviewer": "user-confirmed",
            "reviewed_at": T,
            "verdict": "approved",
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def context(cid="context.neutral", *, glossary_term_ids=None):
    """중립 DomainContext 한 개. mapping의 context_id가 resolve되게 store에 동봉."""
    return base(
        {
            "id": cid,
            "kind": "DomainContext",
            "status": "reviewed",
            "truth_role": "domain",
            "title": "중립 컨텍스트",
            "context_key": "neutral",
            "project_id": "neutral-proj",
            "display_name": "Neutral",
            "boundary_summary": "중립 경계 요약",
            "in_scope": ["a"],
            "out_of_scope": ["b"],
            "injection_profile": {"default_audience": "coding-agent"},
            "glossary_term_ids": glossary_term_ids or [],
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def malformed_reference_cases():
    """참조 registry 필드의 대표적인 타입 위반 객체와 기대 오류."""
    scalar = evidence_ref()
    scalar["evidence_manifest_id"] = ["manifest.neutral.source"]

    list_container = context(glossary_term_ids="g.neutral.x")

    list_item = context(glossary_term_ids=[7])

    nested = evidence_ref()
    nested["locator"] = {"code_locator_id": 7}

    return (
        (
            "scalar",
            scalar,
            "evref.neutral.ref: reference field 'evidence_manifest_id' at "
            "/evidence_manifest_id must be a string, got list",
        ),
        (
            "list-container",
            list_container,
            "context.neutral: reference field 'glossary_term_ids' at "
            "/glossary_term_ids must be a list of strings, got str",
        ),
        (
            "list-item",
            list_item,
            "context.neutral: reference field 'glossary_term_ids' at "
            "/glossary_term_ids/0 must be a string, got int",
        ),
        (
            "nested",
            nested,
            "evref.neutral.ref: reference field 'code_locator_id' at "
            "/locator/code_locator_id must be a string, got int",
        ),
    )


def candidate_mapping(
    mid="mapping.neutral.key",
    *,
    glossary_term_ids,
    mapping_key="key",
):
    """중립 candidate DomainMapping 한 개. decision_record_ids는 빈 리스트."""
    return base(
        {
            "id": mid,
            "kind": "DomainMapping",
            "status": "candidate",
            "truth_role": "domain",
            "title": "Candidate mapping: key",
            "context_id": "context.neutral",
            "mapping_key": mapping_key,
            "canonical_summary": "중립 요약",
            "meaning": "중립 의미",
            "boundary": "중립 경계",
            "glossary_term_ids": glossary_term_ids,
            "decision_record_ids": [],
        },
        tags=["neutral"], created_at=T, updated_at=T,
    )


def insight(iid="insight.neutral.risk", *, insight_type="cross-cutting-risk",
            source_object_ids=None, body="노출 게이트가 두 팝업에 이중구현돼 어긋난다",
            status="reviewed", scope="스테이지 클리어 토큰 노출", code_locator_ids=None):
    """중립 Insight 한 개(2026-06-15 신설 kind). A형(cross-cutting-risk) 기본 — source≥2."""
    obj = {
        "id": iid,
        "kind": "Insight",
        "status": status,
        "truth_role": "synthesis",
        "title": "인사이트: 노출 게이트 이중구현",
        "body": body,
        "source_object_ids": source_object_ids if source_object_ids is not None
                             else ["mapping.neutral.a", "mapping.neutral.b"],
        "scope": scope,
    }
    if insight_type is not None:
        obj["insight_type"] = insight_type
    if code_locator_ids is not None:
        obj["code_locator_ids"] = code_locator_ids
    return base(obj, tags=["neutral"], created_at=T, updated_at=T)


class TestIngest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_ingest_writes_valid_bundle(self):
        bundle = [manifest(), evidence_ref(), context(), candidate_term()]
        with mock.patch.object(
            BrainStore,
            "save_object",
            side_effect=AssertionError("direct save_object call"),
        ), mock.patch(
            "project_brain.ingest.MutationService.apply",
            autospec=True,
            side_effect=__import__(
                "project_brain.mutation",
                fromlist=["MutationService"],
            ).MutationService.apply,
        ) as apply:
            ingest(self.root, bundle, engine_sha=ENGINE_SHA)
        self.assertEqual(apply.call_count, 1)
        store = BrainStore.load(self.root)
        self.assertTrue(store.has("manifest.neutral.source"))
        self.assertTrue(store.has("evref.neutral.ref"))
        self.assertEqual(store.get("g.neutral.x")["status"], "candidate")

    def test_product_code_has_no_direct_brain_store_save_calls(self):
        package = Path(__file__).parents[1] / "src" / "project_brain"
        offenders = []
        for path in sorted(package.rglob("*.py")):
            relative_path = path.relative_to(package).as_posix()
            if relative_path in {"store.py", "mutation.py"}:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "save_object"
                ):
                    offenders.append(f"{relative_path}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_ingest_rejects_schema_violation_writes_nothing(self):
        bad = {"id": "bad", "kind": "GlossaryTerm"}  # base 필드 다수 누락
        bundle = [manifest(), bad]
        with self.assertRaises(IngestError):
            ingest(self.root, bundle)
        # 원자성: 아무 파일도 안 쓰임
        self.assertEqual(BrainStore.load(self.root).all(), [])

    def test_ingest_rejects_malformed_reference_types_writes_nothing(self):
        for label, obj, expected in malformed_reference_cases():
            with self.subTest(label=label):
                with self.assertRaises(IngestError) as caught:
                    ingest(self.root, [obj])
                self.assertIn(expected, str(caught.exception))
                self.assertEqual(BrainStore.load(self.root).all(), [])

    def test_ingest_rejects_dangling_link_writes_nothing(self):
        # context는 동봉해 resolve되지만 mapping이 store에도 bundle에도 없는
        # glossary_term_id를 가리킴 → dangling link 거부(lint.py 8a)
        bundle = [
            context(),
            candidate_mapping(
                "mapping.neutral.key",
                glossary_term_ids=["g.neutral.missing"],
            ),
        ]
        with self.assertRaises(IngestError):
            ingest(self.root, bundle)
        self.assertEqual(BrainStore.load(self.root).all(), [])

    def test_ingest_idempotent_overwrite(self):
        bundle = [manifest(), evidence_ref(), context(), candidate_term()]
        ingest(self.root, bundle)
        # 같은 객체 두 번째 ingest 도 성공(write_text 덮어쓰기)
        ingest(self.root, [manifest(), evidence_ref(), context(), candidate_term()])
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.neutral.x")["status"], "candidate")

    def test_ingest_allows_candidate_to_reviewed(self):
        ingest(self.root, [manifest(), evidence_ref(), context(), candidate_term()])
        # 같은 id를 reviewed로 ingest(승격). reviewed_term은 기존 evref를 참조 → §6.4·lint 통과
        rr = review_record_for("review.g.neutral.x", "g.neutral.x")
        ingest(self.root, [reviewed_term(review_record_id="review.g.neutral.x"), rr])
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.neutral.x")["status"], "reviewed")
        self.assertTrue(store.has("review.g.neutral.x"))

    def test_ingest_rejects_reviewed_to_candidate_demotion(self):
        rr = review_record_for("review.g.neutral.x", "g.neutral.x")
        ingest(
            self.root,
            [
                manifest(),
                evidence_ref(),
                context(),
                reviewed_term(review_record_id="review.g.neutral.x"),
                rr,
            ],
        )
        # 같은 id를 candidate로 덮으려 하면 거부(후퇴 가드)
        with self.assertRaises(IngestError):
            ingest(self.root, [candidate_term()])
        # 기존 reviewed 보존
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.neutral.x")["status"], "reviewed")

    def test_ingest_reviewed_to_reviewed_ok(self):
        rr = review_record_for("review.g.neutral.x", "g.neutral.x")
        ingest(
            self.root,
            [
                manifest(),
                evidence_ref(),
                context(),
                reviewed_term(review_record_id="review.g.neutral.x"),
                rr,
            ],
        )
        # 다시 reviewed로 ingest(멱등) — 성공
        ingest(
            self.root,
            [reviewed_term(review_record_id="review.g.neutral.x"), rr],
        )
        self.assertEqual(
            BrainStore.load(self.root).get("g.neutral.x")["status"],
            "reviewed",
        )

    def test_ingest_merges_existing_store_for_lint(self):
        # 기존 store에 context + candidate term 적재
        ingest(
            self.root,
            [
                context(glossary_term_ids=["g.neutral.x"]),
                candidate_term("g.neutral.x"),
            ],
        )
        # 새 bundle의 mapping이 기존 store의 term/context를 가리킴 → merge 후 lint 통과
        ingest(
            self.root,
            [
                candidate_mapping(
                    "mapping.neutral.key",
                    glossary_term_ids=["g.neutral.x"],
                )
            ],
        )
        store = BrainStore.load(self.root)
        self.assertTrue(store.has("mapping.neutral.key"))
        self.assertTrue(store.has("g.neutral.x"))

    def _insight_bundle(self):
        # Insight source 객체(m.a·m.b)를 store에 동봉해 dangling을 피한다.
        return [
            context(glossary_term_ids=["g.neutral.x"]),
            candidate_term("g.neutral.x"),
            candidate_mapping(
                "mapping.neutral.a",
                glossary_term_ids=["g.neutral.x"],
                mapping_key="a",
            ),
            candidate_mapping(
                "mapping.neutral.b",
                glossary_term_ids=["g.neutral.x"],
                mapping_key="b",
            ),
        ]

    def test_ingest_insight_reviewed_idempotent(self):
        from tests.test_ingest import insight
        ingest(self.root, self._insight_bundle() + [insight()])
        # 같은 reviewed Insight 재적재(멱등) — 기존 ingest 로직 그대로 성공.
        ingest(self.root, [insight()])
        self.assertEqual(
            BrainStore.load(self.root).get("insight.neutral.risk")["status"],
            "reviewed",
        )


T0 = "2026-06-10T00:00:00Z"


def _refs():
    """mapping.ctx.x가 가리키는 context·evref·manifest를 닫는다(reviewed mapping은
    evidence_refs 필수[schema], context_id·evidence_ref는 dangling 금지[lint])."""
    manifest = {"id": "manifest.ctx.src", "kind": "EvidenceManifest", "status": "reviewed",
                "truth_role": "source", "title": "src", "source_type": "session",
                "locator": "...", "captured_at": T0, "captured_by": "user-statement",
                "sensitivity": "internal", "acl": ["demo-team"], "redaction_status": "approved",
                "schema_version": "0.1", "poc_priority": "P2",
                "created_at": T0, "updated_at": T0, "tags": ["ctx"], "evidence_refs": []}
    evref = {"id": "evref.ctx.x", "kind": "EvidenceRef", "status": "reviewed",
             "truth_role": "reference", "title": "e", "evidence_manifest_id": "manifest.ctx.src",
             "ref_type": "session_turn", "locator": "...", "summary": "s",
             "schema_version": "0.1", "poc_priority": "P2",
             "created_at": T0, "updated_at": T0, "tags": ["ctx"], "evidence_refs": []}
    context = {"id": "context.ctx", "kind": "DomainContext", "status": "reviewed",
               "truth_role": "domain", "title": "C", "context_key": "ctx",
               "project_id": "demoapp", "display_name": "C", "boundary_summary": "b",
               "in_scope": [], "out_of_scope": [],
               "injection_profile": {"default_audience": "coding-agent"},
               "glossary_term_ids": [], "schema_version": "0.1", "poc_priority": "P2",
               "created_at": T0, "updated_at": T0, "tags": ["ctx"], "evidence_refs": []}
    return [context, manifest, evref]


def _mapping_obj(updated_at, **over):
    o = {"id": "mapping.ctx.x", "kind": "DomainMapping", "status": "reviewed",
         "truth_role": "domain", "title": "t", "context_id": "context.ctx",
         "mapping_key": "x", "canonical_summary": "s", "meaning": "m", "boundary": "b",
         "caveats": [], "glossary_term_ids": [], "decision_record_ids": [],
         "code_locator_ids": [], "evidence_refs": ["evref.ctx.x"],
         "schema_version": "0.1", "poc_priority": "P2",
         "created_at": T0, "updated_at": updated_at, "tags": ["ctx"]}
    o.update(over)
    return o


class PreconditionsTest(unittest.TestCase):
    def test_precondition_mismatch_blocks_save(self):
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            ingest(brain, _refs() + [_mapping_obj("2026-06-15T00:00:00Z")])  # 현재 06-15
            # 노트는 옛 시점(06-10)을 기대 → 그 사이 누가 06-15로 고침 → 거부
            new = _mapping_obj("2026-06-16T00:00:00Z", meaning="새 의미")
            with self.assertRaises(IngestError):
                ingest(brain, [new], preconditions={"mapping.ctx.x": "0" * 64})

    def test_precondition_match_allows_save(self):
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            current = _mapping_obj("2026-06-15T00:00:00Z")
            ingest(brain, _refs() + [current])
            new = _mapping_obj("2026-06-16T00:00:00Z", boundary="새 경계")
            import hashlib

            expected = hashlib.sha256(BrainStore.object_bytes(current)).hexdigest()
            ingest(brain, [new], preconditions={"mapping.ctx.x": expected})

    def test_precondition_target_missing_is_error(self):
        """대상이 사라졌으면 조용히 건너뛰지 않고 거부한다.

        건너뛰면 build 이후 삭제된 객체가 옛 id 그대로 되살아난다 — 오류·경고 없이."""
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            ingest(brain, _refs() + [_mapping_obj("2026-06-15T00:00:00Z")])
            # build로 사전조건을 뜬 뒤 누가(다른 세션·정비 절차) 그 객체를 지웠다
            for p in brain.rglob("mapping.ctx.x.json"):
                p.unlink()
            new = _mapping_obj("2026-06-16T00:00:00Z", boundary="새 경계")
            with self.assertRaises(IngestError) as cm:
                ingest(brain, [new], preconditions={"mapping.ctx.x": "2026-06-15T00:00:00Z"})
            # 문구가 아니라 엔진 에러 코드로 고정한다 — 이 검증은 mutation 층으로
            # 내려가면서 해시 대조까지 하는 더 강한 게이트가 됐고, 메시지는 영어다.
            self.assertIn("precondition_target_missing", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
