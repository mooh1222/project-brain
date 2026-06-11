"""cli.py 서브커맨드 테스트 (Task 5).

새 중립 합성 데이터(tempfile brain root + 인라인 객체 dict)만 사용한다 — 삭제된
fixture(tests/fixtures/...)를 일절 참조하지 않고 자기완결. argparse 서브파서 전환이
기존 query 경로(AC6 회상이 쓰는 경로)를 깨지 않는지(test_cli_query_path_unchanged),
ingest 서브커맨드가 ingest()를 호출해 store에 적재하는지(test_cli_ingest_subcommand_writes)
검증한다(spec §3.1 CLI subcommand)."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from project_brain import cli
from project_brain.store import BrainStore
from tests.test_ingest import (
    candidate_term,
    context,
    evidence_ref,
    manifest,
)


class TestCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # bundle JSON은 brain_root 바깥에 둔다(BrainStore.load가 객체로 오인하지 않게)
        self._tmp_in = tempfile.TemporaryDirectory()
        self.input_dir = Path(self._tmp_in.name)

    def tearDown(self):
        self._tmp.cleanup()
        self._tmp_in.cleanup()

    def test_cli_query_path_unchanged(self):
        # tempfile store에 새 중립 객체 적재(query 경로가 회수할 대상)
        for obj in (manifest(), evidence_ref(), candidate_term()):
            BrainStore.save_object(self.root, obj)
        # 서브커맨드 없는 위치인자 query — 기존 query 경로 호환 유지(AC6)
        argv = ["--brain-root", str(self.root), "용어가 무슨 뜻이야?"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        answer = json.loads(out.getvalue())
        # answer JSON이 나옴(QueryRouter.answer 결과 형태)
        self.assertIn("intents", answer)

    def test_cli_query_with_db_enables_recall(self):
        # 후속 c(2026-06-11): cli query에 --db·--stub-embedder 배선 — 색인을 주면
        # 라우터 recall이 켜져 top-K로 좁힌다(전량 12 아님). --db 없는 기존 경로는
        # test_cli_query_path_unchanged가 보장한다.
        from project_brain.embedder import StubEmbedder
        from project_brain.search_index import rebuild
        from tests.test_search import code_locator
        for i in range(12):
            BrainStore.save_object(
                self.root,
                code_locator(f"code.{i:02d}", path=f"a/Lane{i}.cpp", symbol=f"makeLanes{i}"))
        db = self.input_dir / "index.db"
        rebuild(self.root, db, embedder=StubEmbedder())
        argv = ["--brain-root", str(self.root), "--db", str(db),
                "--stub-embedder", "makeLanes0 어디 구현?"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        answer = json.loads(out.getvalue())
        loc = next(s for s in answer["sections"]
                   if s["intent"] == "implementation_location")
        self.assertGreaterEqual(len(loc["object_ids"]), 1)
        self.assertLessEqual(len(loc["object_ids"]), 5)

    def test_cli_ingest_subcommand_writes(self):
        bundle = [manifest(), evidence_ref(), candidate_term()]
        objects_file = self.input_dir / "bundle.json"
        objects_file.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        argv = [
            "ingest",
            "--brain-root",
            str(self.root),
            "--objects-file",
            str(objects_file),
        ]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        # ingest()가 호출되어 store에 적재됨
        store = BrainStore.load(self.root)
        self.assertTrue(store.has("ev.manifest"))
        self.assertTrue(store.has("ev.ref"))
        self.assertEqual(store.get("g.x")["status"], "candidate")

    def test_cli_index_rebuild_subcommand(self):
        # argparse 와이어링 + JSON 출력 계약 (하부 rebuild()는 test_search_index가
        # 충실히 검증 — 여기는 CLI 레벨만, 리뷰 minor 반영).
        # ★--stub-embedder★: 테스트는 실모델 로드 없이 stub로 결정론 실행(§5·§10).
        for obj in (manifest(), evidence_ref(), candidate_term()):
            BrainStore.save_object(self.root, obj)
        db = self.input_dir / "index.db"
        argv = ["index", "rebuild", "--brain-root", str(self.root), "--db", str(db),
                "--stub-embedder"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["indexed"], 1)  # GlossaryTerm 1건 이상 색인
        self.assertEqual(payload["db"], str(db))
        self.assertIn("tokenizer", payload)
        # --stub-embedder면 embed_model이 stub 접두로 기록(§4·§5).
        self.assertTrue(payload["embed_model"].startswith("stub:"))
        self.assertTrue(db.exists())


def candidate_term_with_evidence(tid="g.x", term="갈고리"):
    """근거(ev.ref) 보유 candidate GlossaryTerm. promote 후 §6.4(reviewed 근거 필수)를 통과한다."""
    from project_brain.objbase import base
    return base(
        {
            "id": tid,
            "kind": "GlossaryTerm",
            "status": "candidate",
            "truth_role": "domain",
            "title": f"Candidate term: {term}",
            "context_id": "context.neutral",
            "term": term,
            "definition": "후보 정의",
            "evidence_refs": ["ev.ref"],
            "candidate": {"candidate_state": "ready_for_review", "candidate_source": "spec"},
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


class TestCliPromote(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _ingest(self):
        from project_brain.ingest import ingest
        ingest(self.root, [manifest(), evidence_ref(), candidate_term_with_evidence()])

    def test_promote_round_trip(self):
        self._ingest()
        # promote 전: 후보가 candidate로 노출
        self.assertEqual(BrainStore.load(self.root).get("g.x")["status"], "candidate")
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.x", "--reviewer", "user-confirmed",
            "--reviewed-at", "2026-06-06T00:00:00Z",
        ]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])
        store = BrainStore.load(self.root)
        # 승격 객체 + 검토 기록 둘 다 저장됨
        self.assertEqual(store.get("g.x")["status"], "reviewed")
        self.assertEqual(store.get("g.x")["review_record_id"], "review.g.x")
        self.assertTrue(store.has("review.g.x"))
        # 없는 기록 가리킴 0건(사후 lint clean)
        from project_brain.lint import lint_store
        self.assertEqual(lint_store(store), [])

    def test_promote_missing_id_returns_error(self):
        self._ingest()
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.nope", "--reviewer", "user-confirmed",
            "--reviewed-at", "2026-06-06T00:00:00Z",
        ]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)

    def test_promote_requery_moves_candidate_to_reviewed(self):
        # spec §5.3 루프 폐쇄: 질의(후보) → promote → 재질의(검수). 리뷰 minor 반영.
        from project_brain.router import QueryRouter
        self._ingest()  # candidate g.x (term=갈고리, evidence 보유) + manifest + ref
        before = QueryRouter(BrainStore.load(self.root)).answer("갈고리 용어 무슨 뜻?")
        self.assertIn("g.x", before["promotable_candidate_ids"])
        self.assertNotIn("g.x", before["source_object_ids"])
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.x", "--reviewer", "user-confirmed",
            "--reviewed-at", "2026-06-06T00:00:00Z",
        ]
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        after = QueryRouter(BrainStore.load(self.root)).answer("갈고리 용어 무슨 뜻?")
        # 승격 후: 후보에서 빠지고 검수 source로(reviewed GlossaryTerm은 glossary_objects 덤프로 노출)
        self.assertNotIn("g.x", after["promotable_candidate_ids"])
        self.assertIn("g.x", after["source_object_ids"])

    def test_promote_zero_evidence_rejected(self):
        # §6.4 활성 후: 근거 없는 candidate(candidate엔 §6.4 미적용 → 적재는 됨)를 승격하면
        # 승격 결과물(reviewed, 근거 빔)이 쓰기 전 일괄 검증에 걸려 rc=1, 디스크 불변(원자성).
        from project_brain.ingest import ingest
        from tests.test_ingest import candidate_term  # evidence_refs=[] 기본
        ingest(self.root, [candidate_term("g.noev")])
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.noev", "--reviewer", "user-confirmed",
            "--reviewed-at", "2026-06-06T00:00:00Z",
        ]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)
        result = json.loads(out.getvalue())
        self.assertFalse(result["ok"])
        self.assertIn("requires non-empty evidence_refs", result["error"])
        # 원자성: 거부됐으니 g.noev는 여전히 candidate(부분 쓰기·review 기록 생성 없음)
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.noev")["status"], "candidate")
        self.assertFalse(store.has("review.g.noev"))

    def test_promote_backfills_empty_evidence_from_mapping(self):
        # 빈 근거 candidate + 짝 reviewed 매핑 → 수동 promote가 backfill해 §6.4 통과.
        from project_brain.ingest import ingest
        ingest(self.root, [
            manifest(), _ar_evref("evref.a"), context(),
            _ar_term("g.empty", term="빈근거"),
            _ar_mapping("m.empty", term_ids=["g.empty"], evidence_refs=["evref.a"], mapping_key="me"),
        ])
        argv = ["promote", "--brain-root", str(self.root),
                "--ids", "g.empty", "--reviewer", "user-confirmed",
                "--reviewed-at", "2026-06-08T00:00:00Z"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.empty")["status"], "reviewed")
        self.assertEqual(store.get("g.empty")["evidence_refs"], ["evref.a"])

    def test_promote_rejects_already_reviewed(self):
        # 멱등 가드: 같은 id 두 번 promote → 두 번째 rc=1.
        self._ingest()  # candidate g.x (term=갈고리, evidence 보유)
        base_argv = ["promote", "--brain-root", str(self.root),
                     "--ids", "g.x", "--reviewer", "user-confirmed",
                     "--reviewed-at", "2026-06-06T00:00:00Z"]
        with mock.patch("sys.argv", ["cli"] + base_argv), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + base_argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)
        self.assertIn("already reviewed", json.loads(out.getvalue())["error"])

    def test_promote_conflict_records_resolution(self):
        # 수동 conflict 승격(spec §5.2 사람 판정 허용) → 해소 근거가 검수 기록에 남음.
        from project_brain.ingest import ingest
        conflict_term = _ar_term("g.c", term="충돌", candidate_state="conflict",
                                 evidence_refs=["evref.a"])
        ingest(self.root, [manifest(), _ar_evref("evref.a"), context(), conflict_term])
        argv = ["promote", "--brain-root", str(self.root),
                "--ids", "g.c", "--reviewer", "user-confirmed",
                "--reviewed-at", "2026-06-08T00:00:00Z",
                "--conflict-resolution", "위키 정설 채택"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.c")["status"], "reviewed")
        self.assertEqual(store.get("review.g.c")["conflict_resolution"], "위키 정설 채택")


def _ar_evref(rid, manifest_id="ev.manifest"):
    from project_brain.objbase import base
    return base(
        {
            "id": rid, "kind": "EvidenceRef", "status": "reviewed", "truth_role": "reference",
            "title": "ref", "evidence_manifest_id": manifest_id, "ref_type": "spec_section",
            "locator": {"section": "1"}, "summary": "인용",
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


def _ar_term(tid, *, term, candidate_state="evidence_verified", evidence_refs=None):
    from project_brain.objbase import base
    return base(
        {
            "id": tid, "kind": "GlossaryTerm", "status": "candidate", "truth_role": "domain",
            "title": f"Candidate term: {term}", "context_id": "context.neutral",
            "term": term, "definition": "후보 정의",
            "evidence_refs": evidence_refs if evidence_refs is not None else [],
            "candidate": {"candidate_state": candidate_state, "candidate_source": "spec"},
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


def _ar_mapping(mid, *, term_ids, evidence_refs, mapping_key):
    from project_brain.objbase import base
    return base(
        {
            "id": mid, "kind": "DomainMapping", "status": "reviewed", "truth_role": "domain",
            "title": "매핑", "context_id": "context.neutral", "mapping_key": mapping_key,
            "canonical_summary": "요약", "meaning": "의미", "boundary": "경계",
            "glossary_term_ids": term_ids, "decision_record_ids": [], "evidence_refs": evidence_refs,
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


class TestCliPromoteAuto(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _ingest_corpus(self):
        from project_brain.ingest import ingest
        bundle = [
            manifest(),
            _ar_evref("evref.a"), _ar_evref("evref.b"),
            context(),
            _ar_term("g.empty", term="빈근거"),                       # 빈 근거 → backfill 대상
            _ar_term("g.has", term="근거있음", evidence_refs=["evref.b"]),
            _ar_term("g.conflict", term="충돌", candidate_state="conflict"),
            _ar_term("g.multi", term="다중참조"),                     # 매핑 2개가 참조
            _ar_mapping("m.empty", term_ids=["g.empty"], evidence_refs=["evref.a"], mapping_key="me"),
            _ar_mapping("m.has", term_ids=["g.has"], evidence_refs=["evref.b"], mapping_key="mh"),
            _ar_mapping("m.conflict", term_ids=["g.conflict"], evidence_refs=["evref.a"], mapping_key="mc"),
            _ar_mapping("m.z", term_ids=["g.multi"], evidence_refs=["evref.b"], mapping_key="z"),
            _ar_mapping("m.a", term_ids=["g.multi"], evidence_refs=["evref.a"], mapping_key="a"),
        ]
        ingest(self.root, bundle)

    def _run(self, ids):
        argv = ["promote-auto", "--brain-root", str(self.root),
                "--ids", *ids, "--reviewed-at", "2026-06-08T00:00:00Z"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_batch_promotes_eligible_skips_conflict_and_unknown(self):
        self._ingest_corpus()
        rc, result = self._run(["g.empty", "g.has", "g.conflict", "g.multi", "g.nope"])
        self.assertEqual(rc, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(set(result["promoted"]), {"g.empty", "g.has", "g.multi"})
        self.assertEqual(result["skipped"]["conflict"], ["g.conflict"])
        self.assertEqual(result["skipped"]["unknown_id"], ["g.nope"])
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.empty")["status"], "reviewed")
        # backfill: 빈 근거 용어가 짝 매핑 evref로 채워짐
        self.assertEqual(store.get("g.empty")["evidence_refs"], ["evref.a"])
        from project_brain.lint import lint_store
        self.assertEqual(lint_store(store), [])

    def test_review_record_records_auto_reviewer_and_vouched_by(self):
        self._ingest_corpus()
        self._run(["g.empty", "g.multi"])
        store = BrainStore.load(self.root)
        rr_empty = store.get("review.g.empty")
        self.assertEqual(rr_empty["reviewer"], "auto:mapping-vouched")
        self.assertEqual(rr_empty["vouched_by_mapping_ids"], ["m.empty"])
        # 다중 참조: 보증 매핑 전부, 정렬됨
        rr_multi = store.get("review.g.multi")
        self.assertEqual(rr_multi["vouched_by_mapping_ids"], ["m.a", "m.z"])

    def test_dedup_multi_mapping_promotes_once(self):
        self._ingest_corpus()
        rc, result = self._run(["g.multi", "g.multi"])
        self.assertEqual(rc, 0)
        self.assertEqual(result["promoted"], ["g.multi"])

    def test_rerun_is_idempotent(self):
        self._ingest_corpus()
        self._run(["g.empty", "g.has", "g.multi"])
        rc, result = self._run(["g.empty", "g.has", "g.multi"])
        self.assertEqual(rc, 0)
        self.assertEqual(result["promoted"], [])
        self.assertEqual(set(result["skipped"]["already_reviewed"]), {"g.empty", "g.has", "g.multi"})


def _ar_legacy_manifest(mid="ev.wiki", source_type="wiki"):
    from project_brain.objbase import base
    return base(
        {
            "id": mid, "kind": "EvidenceManifest", "status": "reviewed", "truth_role": "source",
            "title": "위키 manifest", "source_type": source_type, "locator": "wiki://x",
            "captured_at": "2026-06-04T00:00:00Z", "captured_by": "n", "sensitivity": "internal",
            "acl": ["team"], "redaction_status": "approved",
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


def _ar_legacy_evref(rid="evref.wiki", manifest_id="ev.wiki"):
    from project_brain.objbase import base
    return base(
        {
            "id": rid, "kind": "EvidenceRef", "status": "reviewed", "truth_role": "reference",
            "title": "위키 ref", "evidence_manifest_id": manifest_id, "ref_type": "wiki_section",
            "locator": {"section": "1"}, "summary": "위키 인용",
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


class TestCliPromoteAtomicity(unittest.TestCase):
    """원자성(lint를 save 전에) + backfill legacy 필터 회귀 — 2026-06-08 사고 재발 방지."""
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_manual_promote_legacy_only_rejected_disk_unchanged(self):
        # legacy(wiki) 근거만 가진 용어를 수동 승격하면 reviewed가 legacy-only(lint 6 위반).
        # 사전 lint가 막아 rc=1, 디스크는 candidate 그대로(원자성 — save 전 lint).
        from project_brain.ingest import ingest
        term = _ar_term("g.legacy", term="레거시", evidence_refs=["evref.wiki"])
        ingest(self.root, [_ar_legacy_manifest(), _ar_legacy_evref(), context(), term])
        argv = ["promote", "--brain-root", str(self.root),
                "--ids", "g.legacy", "--reviewer", "user-confirmed",
                "--reviewed-at", "2026-06-08T00:00:00Z"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)
        self.assertIn("legacy-only", json.dumps(json.loads(out.getvalue()), ensure_ascii=False))
        # 원자성: 디스크 불변(부분 쓰기·review 기록 생성 없음)
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.legacy")["status"], "candidate")
        self.assertFalse(store.has("review.g.legacy"))

    def test_promote_auto_skips_legacy_only_evidence(self):
        # 짝 매핑 evidence가 wiki(legacy)뿐인 용어는 자동 승격 부적격 → skip. 정상 용어만 승격.
        from project_brain.ingest import ingest
        from project_brain.lint import lint_store
        ingest(self.root, [
            manifest(), _ar_evref("evref.spec"),
            _ar_legacy_manifest("ev.wiki"), _ar_legacy_evref("evref.wiki", "ev.wiki"),
            context(),
            _ar_term("g.ok", term="정상"),
            _ar_term("g.legacy", term="레거시"),
            _ar_mapping("m.ok", term_ids=["g.ok"], evidence_refs=["evref.spec"], mapping_key="mok"),
            _ar_mapping("m.legacy", term_ids=["g.legacy"], evidence_refs=["evref.wiki"], mapping_key="mleg"),
        ])
        argv = ["promote-auto", "--brain-root", str(self.root),
                "--ids", "g.ok", "g.legacy", "--reviewed-at", "2026-06-08T00:00:00Z"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["promoted"], ["g.ok"])
        self.assertEqual(result["skipped"]["legacy_only_evidence"], ["g.legacy"])
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.ok")["status"], "reviewed")
        self.assertEqual(store.get("g.legacy")["status"], "candidate")
        self.assertEqual(lint_store(store), [])


class TestCliSearch(unittest.TestCase):
    """cli search 서브커맨드(스펙 §7) — recall + 게이트 결과를 검수상태·linked와 함께
    JSON 출력. 전부 --stub-embedder(실모델 로드 없음, §5)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = Path(self._tmp.name) / "brain"
        self.db = Path(self._tmp.name) / "index.db"

    def tearDown(self):
        self._tmp.cleanup()

    def _build_index(self, objs):
        from project_brain.embedder import StubEmbedder
        from project_brain.search_index import rebuild
        for obj in objs:
            BrainStore.save_object(self.brain, obj)
        rebuild(self.brain, self.db, embedder=StubEmbedder())

    def _search(self, query):
        argv = ["search", query, "--db", str(self.db),
                "--brain-root", str(self.brain), "--stub-embedder"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_search_returns_results_with_status_and_linked(self):
        from tests.test_search import code_locator, domain_mapping, glossary_term
        self._build_index([
            glossary_term("g.lane", term="레인", definition="레인 영역 배치"),
            domain_mapping("m.lane", meaning="레인 영역 배치",
                           glossary_term_ids=["g.lane"], code_locator_ids=["code.lane"]),
            code_locator("code.lane", path="a/Lane.cpp", symbol="makeLanes"),
        ])
        rc, payload = self._search("레인 영역 배치")
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])
        self.assertIn("results", payload)
        self.assertIn("candidates", payload)
        self.assertIn("needs_clarification", payload)
        # reviewed 적중에 검수상태·linked(코드 위치)가 동반된다.
        ids = {h["object_id"] for h in payload["results"]}
        self.assertIn("m.lane", ids)
        m = next(h for h in payload["results"] if h["object_id"] == "m.lane")
        self.assertEqual(m["status"], "reviewed")
        locs = {c["object_id"] for c in m["linked"]["code_locators"]}
        self.assertIn("code.lane", locs)

    def test_search_candidate_channel(self):
        from tests.test_search import glossary_term
        self._build_index([
            glossary_term("g.cand", term="레인", definition="레인 영역 배치", status="candidate"),
        ])
        rc, payload = self._search("레인 영역 배치")
        self.assertEqual(rc, 0)
        cand_ids = {h["object_id"] for h in payload["candidates"]}
        self.assertIn("g.cand", cand_ids)
        # reviewed 게이트 통과 0건 → needs_clarification.
        self.assertEqual(payload["results"], [])
        self.assertTrue(payload["needs_clarification"])

    def test_search_raw_excerpts_channel(self):
        # raw 원문 청크가 "원문 발췌(미검수)" 라벨 채널로 나온다(§2.2, 2026-06-11).
        from tests.test_search import glossary_term
        src = self.brain / "raw" / "sources" / "foo-ctx"
        src.mkdir(parents=True)
        (src / "spec.md").write_text(
            "# 광고 버튼\n광고 시청 버튼은 빈 보유량 상태에서 노출 비율을 줄인다.\n",
            encoding="utf-8")
        self._build_index([
            glossary_term("g.ad", term="광고 버튼", definition="광고 시청 버튼 정의"),
        ])
        rc, payload = self._search("광고 시청 버튼 노출 비율")
        self.assertEqual(rc, 0)
        self.assertIn("raw_excerpts", payload)
        self.assertTrue(payload["raw_excerpts"])
        for h in payload["raw_excerpts"]:
            self.assertEqual(h["trust_label"], "원문 발췌(미검수)")
            self.assertTrue(h["object_id"].startswith("raw.foo-ctx."))
            self.assertTrue(h["surface"])

    def test_search_missing_index_errors(self):
        argv = ["search", "레인", "--db", str(self.db),
                "--brain-root", str(self.brain), "--stub-embedder"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("index rebuild", payload["error"])


class TestCliInstallDoctor(unittest.TestCase):
    def test_install_subcommand_creates_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            argv = ["install", "--target", td, "--project", "demo"]
            out = io.StringIO()
            with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
                rc = cli.main()
            self.assertEqual(rc, 0)
            payload = json.loads(out.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["config"], "created")
            target = Path(td)
            self.assertTrue((target / ".project-brain.json").exists())
            self.assertTrue(
                (target / ".claude" / "skills" / "demo-brain-recall" / "SKILL.md").exists()
            )

    def test_doctor_subcommand_runs(self):
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli", "doctor"]), redirect_stdout(out):
            rc = cli.main()
        payload = json.loads(out.getvalue())
        # 이 venv에는 필수 의존성이 전부 있다 — required 통과 → rc 0.
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])
        names = {c["name"] for c in payload["checks"]}
        self.assertIn("sqlite-vec", names)
        self.assertIn("fts5", names)


if __name__ == "__main__":
    unittest.main()
