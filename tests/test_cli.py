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
from project_brain.cli import _run_build
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

    def test_cli_query_surfaces_stale_advisory_from_cache(self):
        # Step 2: .brain-local/stale-set.json이 있으면 query가 읽어 매핑에 stale_advisory 부착.
        from project_brain.stale_check import write_stale_set
        from tests.test_search import domain_mapping, glossary_term
        for obj in (glossary_term("g.boost", term="강화폭탄"),
                    domain_mapping("m.boost", meaning="강화폭탄 적재 의미",
                                   glossary_term_ids=["g.boost"])):
            BrainStore.save_object(self.root, obj)
        write_stale_set(self.root, {
            "target_head": "T", "computed_at": "t", "stale_mapping_ids": ["m.boost"],
            "detail": {"m.boost": {"change_types": ["M"], "paths": ["a/X.cpp"]}}})
        argv = ["--brain-root", str(self.root), "강화폭탄 무슨 뜻?"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        answer = json.loads(out.getvalue())
        gm = next(s for s in answer["sections"] if s["intent"] == "glossary_meaning")
        m = next(x for x in gm["mappings"] if x["id"] == "m.boost")
        self.assertEqual(m["stale_advisory"]["change_types"], ["M"])

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

    def test_cli_projection_label_split_by_status(self):
        # spec 2026-06-17 Task A5: projection_reuse 채널의 신뢰 라벨이 status로 갈린다 —
        # reviewed=재사용 브리핑(검증됨), candidate=재사용 후보(미검증). 채널은 공통.
        from project_brain.embedder import StubEmbedder
        from project_brain.search_index import rebuild
        from tests.test_search import build_store_dir, domain_mapping, projection
        src = domain_mapping("mapping.mina-kayak.race-end-result-achieve",
                             meaning="미나 결과 팝업 순위 표시", context_id="context.mina-kayak")
        build_store_dir(self.root, [
            src,
            projection("projection.mina-kayak.result-popup-rank.reviewed",
                       context_id="context.mina-kayak",
                       title="미나 결과 팝업 순위 표시 착수 브리핑(검증)",
                       reuse_payload="데이터 출처: RaceInfo recordMap. 확장 지점: PopupMinaKayakResult.",
                       source_object_ids=["mapping.mina-kayak.race-end-result-achieve"],
                       source_objects=[src],
                       status="reviewed"),
            projection("projection.mina-kayak.result-popup-rank.candidate",
                       context_id="context.mina-kayak",
                       title="미나 결과 팝업 순위 표시 착수 브리핑(후보)",
                       reuse_payload="데이터 출처: RaceInfo recordMap. 확장 지점: PopupMinaKayakResult.",
                       source_object_ids=["mapping.mina-kayak.race-end-result-achieve"],
                       source_objects=[src],
                       status="candidate"),
        ])
        db = self.input_dir / "index.db"
        rebuild(self.root, db, embedder=StubEmbedder())
        argv = ["search", "미나 결과 팝업 순위 표시", "--brain-root", str(self.root),
                "--db", str(db), "--stub-embedder"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        answer = json.loads(out.getvalue())
        self.assertIn("projection_reuse", answer)
        labels = {h.get("status"): h["trust_label"] for h in answer["projection_reuse"]}
        self.assertEqual(labels.get("reviewed"), "재사용 브리핑(검증됨)")
        if "candidate" in labels:
            self.assertEqual(labels["candidate"], "재사용 후보(미검증)")

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

    def test_cli_lint_clean_store_ok(self):
        # 깨끗한 store(서로 참조 정상) → lint ok=true, problems 0 (test_lint.py와 동일 조합)
        for obj in (manifest(), evidence_ref(), candidate_term()):
            BrainStore.save_object(self.root, obj)
        argv = ["lint", "--brain-root", str(self.root)]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        report = json.loads(out.getvalue())
        self.assertTrue(report["ok"])
        self.assertEqual(report["problems"], [])

    def test_cli_lint_reports_dangling(self):
        # 근거 객체가 없는 Insight → dangling source_object_ids 보고 + rc=1
        from tests.test_ingest import insight
        BrainStore.save_object(
            self.root, insight(source_object_ids=["m.gone", "m.gone2"]))
        argv = ["lint", "--brain-root", str(self.root)]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)
        report = json.loads(out.getvalue())
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("dangling source_object_ids" in p for p in report["problems"]))


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

    def test_promote_reviewed_at_defaults_to_kst_when_omitted(self):
        # --reviewed-at 생략 시 엔진이 현재 KST(+09:00)를 박는다(시점은 caller 주입이 아니라 엔진 자동).
        self._ingest()
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.x", "--reviewer", "user-confirmed",
        ]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        rr = BrainStore.load(self.root).get("review.g.x")
        self.assertTrue(rr["reviewed_at"].endswith("+09:00"), rr["reviewed_at"])

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

    def test_search_stale_index_errors_clean_json(self):
        # 스펙 리뷰 관찰(2026-06-11): 신선도 가드(RuntimeError)는 정상 흐름(적재 후
        # rebuild 누락)에서 터진다 — traceback이 아니라 누락 색인과 같은 모양의
        # JSON 에러(ok=False, error에 해결책 rebuild)로 나와야 한다.
        from tests.test_search import glossary_term
        self._build_index([
            glossary_term("g.stale", term="레인", definition="레인 영역 배치",
                          status="candidate"),
        ])
        # 색인 빌드 후 객체 변경(status 플립) → 색인이 stale, rebuild는 안 함
        BrainStore.save_object(
            self.brain,
            glossary_term("g.stale", term="레인", definition="레인 영역 배치"))
        argv = ["search", "레인", "--db", str(self.db),
                "--brain-root", str(self.brain), "--stub-embedder"]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])
        self.assertIn("rebuild", payload["error"])

    def test_search_unrelated_runtime_error_escapes(self):
        # 품질 리뷰(2026-06-11): 환경 장애(임베더 모델 로드 실패·sqlite-vec 미설치 등)의
        # RuntimeError는 rebuild 안내 JSON으로 강등하면 안 된다 — 그대로 새어 나와
        # 시끄럽게 실패해야 stale 색인과 다른 조치를 한다(StaleIndexError만 정상 안내).
        # eval_recall은 _run_search가 함수 안에서 import하므로 search 모듈 쪽을 패치한다
        # (검증 대상은 cli의 예외 라우팅이지 검색 스택이 아님).
        argv = ["search", "레인", "--db", str(self.db),
                "--brain-root", str(self.brain), "--stub-embedder"]
        with mock.patch("project_brain.search.eval_recall",
                        side_effect=RuntimeError("모델 로드 실패")), \
             mock.patch("sys.argv", ["cli"] + argv), \
             redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError) as ctx:
                cli.main()
        self.assertIn("모델 로드 실패", str(ctx.exception))


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
                (target / ".claude" / "skills" / "demo-brain-query" / "SKILL.md").exists()
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


class CliSessionTest(unittest.TestCase):
    def _run_cli(self, argv):
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        return out.getvalue()

    def test_session_list_outputs_json_with_processed_flag(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "t"
            proj = root / "p"
            proj.mkdir(parents=True)
            (proj / "abc.jsonl").write_text(
                '{"type": "user", "cwd": "/x/demo", "timestamp": "2026-06-11T01:00:00Z"}\n',
                encoding="utf-8",
            )
            brain_root = Path(td) / "brain"
            out = self._run_cli(["session", "list", "--transcript-root", str(root),
                                 "--brain-root", str(brain_root)])
            payload = json.loads(out)
            self.assertEqual(payload["sessions"][0]["uuid"], "abc")
            self.assertFalse(payload["sessions"][0]["processed"])

    def test_session_list_unprocessed_filters_marked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "t"
            proj = root / "p"
            proj.mkdir(parents=True)
            (proj / "abc.jsonl").write_text(
                '{"type": "user", "cwd": "/x", "timestamp": "t"}\n', encoding="utf-8")
            (proj / "def.jsonl").write_text(
                '{"type": "user", "cwd": "/x", "timestamp": "t"}\n', encoding="utf-8")
            brain_root = Path(td) / "brain"
            self._run_cli(["session", "mark-processed", "abc",
                           "--brain-root", str(brain_root)])
            out = self._run_cli(["session", "list", "--transcript-root", str(root),
                                 "--brain-root", str(brain_root), "--unprocessed"])
            payload = json.loads(out)
            self.assertEqual([s["uuid"] for s in payload["sessions"]], ["def"])

    def test_session_mark_processed_writes_note(self):
        with tempfile.TemporaryDirectory() as td:
            brain_root = Path(td)
            out = self._run_cli(["session", "mark-processed", "abc",
                                 "--brain-root", str(brain_root), "--note", "미합의 1건"])
            payload = json.loads(out)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["record"]["note"], "미합의 1건")


class RunBuildTest(unittest.TestCase):
    def test_build_writes_objects_file(self):
        with tempfile.TemporaryDirectory() as td:
            notes_path = Path(td) / "notes.json"
            out_path = Path(td) / "out.json"
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            # reviewed GlossaryTerm은 evidence_refs가 필수(schema) → source+code_anchor로 닫는다
            notes_path.write_text(json.dumps({
                "context": {"key": "ctx", "commit": "abc",
                            "now": "2026-06-16T00:00:00Z", "repo": "demoapp"},
                "sources": [{"id": "manifest.ctx.code", "source_type": "code_search",
                             "title": "코드", "locator": "...", "captured_by": "agent"}],
                "code_anchors": [{"key": "hit-hook", "path": "D.h", "symbol": "S",
                                  "line_start": 1, "line_end": 1, "quote": "q",
                                  "manifest": "manifest.ctx.code"}],
                "glossary": [{"key": "hit", "term": "hit", "definition": "정의",
                              "evidence_refs": ["evref.ctx.hit-hook"]}],
            }), encoding="utf-8")
            rc = _run_build(["--notes", str(notes_path), "--objects-file", str(out_path),
                             "--brain-root", str(brain)])
            self.assertEqual(rc, 0)
            objs = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(any(o["id"] == "g.ctx.hit" for o in objs))

    def test_build_errors_return_1_and_no_file(self):
        with tempfile.TemporaryDirectory() as td:
            notes_path = Path(td) / "notes.json"
            out_path = Path(td) / "out.json"
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            notes_path.write_text(json.dumps({"glossary": []}), encoding="utf-8")  # context 없음
            rc = _run_build(["--notes", str(notes_path), "--objects-file", str(out_path),
                             "--brain-root", str(brain)])
            self.assertEqual(rc, 1)
            self.assertFalse(out_path.exists())

    def test_build_auto_fills_now_kst_when_note_omits_now(self):
        # C4 회귀: 노트 context에 now를 생략하면 엔진이 now_kst()로 created_at/updated_at을
        # 자동 기입한다(cli.py `now = ... or now_kst()`). 폴백이 빠지면 now=None이라
        # created_at이 빈 값/None이 돼 이 단언이 깨진다 — 시점 분산 재발 가드. 신규 코드 0줄.
        with tempfile.TemporaryDirectory() as td:
            notes_path = Path(td) / "notes.json"
            out_path = Path(td) / "out.json"
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            notes_path.write_text(json.dumps({
                "context": {"key": "ctx", "commit": "abc", "repo": "demoapp"},  # now 생략
                "sources": [{"id": "manifest.ctx.code", "source_type": "code_search",
                             "title": "코드", "locator": "...", "captured_by": "agent"}],
                "code_anchors": [{"key": "hit-hook", "path": "D.h", "symbol": "S",
                                  "line_start": 1, "line_end": 1, "quote": "q",
                                  "manifest": "manifest.ctx.code"}],
                "glossary": [{"key": "hit", "term": "hit", "definition": "정의",
                              "evidence_refs": ["evref.ctx.hit-hook"]}],
            }), encoding="utf-8")
            rc = _run_build(["--notes", str(notes_path), "--objects-file", str(out_path),
                             "--brain-root", str(brain)])
            self.assertEqual(rc, 0)
            objs = json.loads(out_path.read_text(encoding="utf-8"))
            term = next(o for o in objs if o["id"] == "g.ctx.hit")
            # KST 표준(+09:00, microsecond 없음)으로 자동 기입, created_at == updated_at.
            self.assertTrue(term["created_at"].endswith("+09:00"), term["created_at"])
            self.assertEqual(term["created_at"], term["updated_at"])


class TestCliProjectionBuildReuse(unittest.TestCase):
    """`projection build-reuse` 서브커맨드 (외부 리뷰 Important 3, codex 합의 A안).

    수작업 JSON 대신 도구가 hash·source를 계산하고 ingest 경유로 저장하게 만든다.
    store에 context(context_key=neutral)·candidate mapping을 둔 뒤, source가 다
    존재하면 candidate prompt_payload projection을 만든다."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._tmp_in = tempfile.TemporaryDirectory()
        self.input_dir = Path(self._tmp_in.name)
        # store에 context + 구성 객체(candidate mapping, evidence_refs 비어 dangling 없음)
        from tests.test_search import domain_mapping
        BrainStore.save_object(self.root, context("context.neutral"))
        BrainStore.save_object(
            self.root,
            domain_mapping("mapping.neutral.race-end", meaning="경주 종료",
                           status="candidate", context_id="context.neutral"))
        self.payload_file = self.input_dir / "payload.txt"
        self.payload_file.write_text("데이터 출처: RaceInfo recordMap. 확장 지점: PopupResult.",
                                     encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()
        self._tmp_in.cleanup()

    def _argv(self, *extra):
        return [
            "projection", "build-reuse",
            "--brain-root", str(self.root),
            "--context-id", "context.neutral",
            "--requirement-key", "result-popup-rank",
            "--source-object-ids", "mapping.neutral.race-end",
            "--title", "결과 팝업 순위 표시 착수 브리핑",
            "--payload-file", str(self.payload_file),
            "--generated-by", "demo-brain-query",
            *extra,
        ]

    def _run(self, *extra):
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + self._argv(*extra)), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_write_ingests_projection_readable_from_store(self):
        # (a) source 다 존재 시 --write로 ingest 경유 저장 → store에서 읽힘.
        rc, payload = self._run("--write")
        self.assertEqual(rc, 0, payload)
        self.assertTrue(payload["ok"])
        pid = "projection.neutral.result-popup-rank.reuse"
        self.assertEqual(payload["id"], pid)
        store = BrainStore.load(self.root)
        self.assertTrue(store.has(pid))
        proj = store.get(pid)
        self.assertEqual(proj["kind"], "ContextProjection")
        self.assertEqual(proj["format"], "prompt_payload")
        self.assertEqual(proj["status"], "candidate")
        self.assertEqual(proj["generated_by"], "demo-brain-query")
        self.assertTrue(proj["projection_hash"])
        self.assertTrue(proj["source_content_hash"])

    def test_dangling_source_errors_and_no_write(self):
        # (b) source-object-ids에 store에 없는 id가 있으면 에러 종료, 저장 안 됨.
        out = io.StringIO()
        argv = [
            "projection", "build-reuse",
            "--brain-root", str(self.root),
            "--context-id", "context.neutral",
            "--requirement-key", "result-popup-rank",
            "--source-object-ids", "mapping.neutral.race-end", "mapping.does-not-exist",
            "--title", "결과 팝업 순위 표시 착수 브리핑",
            "--payload-file", str(self.payload_file),
            "--generated-by", "demo-brain-query",
            "--write",
        ]
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("mapping.does-not-exist", payload["error"])
        store = BrainStore.load(self.root)
        self.assertFalse(store.has("projection.neutral.result-popup-rank.reuse"))

    def test_hashes_computed_by_tool(self):
        # (c) 사용자가 hash를 안 줘도 source_content_hash·projection_hash가 채워진다.
        from project_brain.hash_utils import sha256_text, source_content_hash
        rc, payload = self._run("--write")
        self.assertEqual(rc, 0, payload)
        proj = BrainStore.load(self.root).get("projection.neutral.result-popup-rank.reuse")
        # projection_hash = payload 텍스트 sha256
        self.assertEqual(
            proj["projection_hash"],
            sha256_text("데이터 출처: RaceInfo recordMap. 확장 지점: PopupResult."))
        # source_content_hash = 구성 객체 의미 직렬화 sha256 (시각·버전 메타 제외, lint 공식과 동일)
        src = BrainStore.load(self.root).get("mapping.neutral.race-end")
        self.assertEqual(proj["source_content_hash"], source_content_hash([src]))

    def test_preview_only_without_write_does_not_save(self):
        # (d) --write 없으면 생성될 projection JSON만 미리보기, 저장 안 함.
        rc, payload = self._run()
        self.assertEqual(rc, 0, payload)
        # 미리보기는 생성될 projection을 담는다(저장 전).
        self.assertEqual(payload["projection"]["id"],
                         "projection.neutral.result-popup-rank.reuse")
        self.assertEqual(payload["projection"]["status"], "candidate")
        store = BrainStore.load(self.root)
        self.assertFalse(store.has("projection.neutral.result-popup-rank.reuse"))

    def test_existing_id_without_replace_fails(self):
        # (e) 같은 id가 store에 이미 있으면 --replace 없이는 실패.
        rc, _ = self._run("--write")
        self.assertEqual(rc, 0)
        rc2, payload = self._run("--write")  # 같은 id 재시도
        self.assertEqual(rc2, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("--replace", payload["error"])

    def test_existing_id_with_replace_succeeds(self):
        # --replace를 주면 같은 id 교체 허용(기존이 candidate일 때).
        rc, _ = self._run("--write")
        self.assertEqual(rc, 0)
        rc2, payload = self._run("--write", "--replace")
        self.assertEqual(rc2, 0, payload)
        self.assertTrue(payload["ok"])

    def test_reviewed_projection_regeneration_blocked_with_guidance(self):
        # reviewed reuse projection은 --replace로도 재생성 막힘(정책 A: 재검증 강제, 스펙 §3.4).
        # build-reuse는 항상 candidate를 만들고 reviewed→candidate는 후퇴라 거부된다.
        # ingest 후퇴 가드의 불친절한 메시지 전에 길 안내를 주고 기존 reviewed를 보존한다.
        rc, _ = self._run("--write")
        self.assertEqual(rc, 0)
        pid = "projection.neutral.result-popup-rank.reuse"
        store = BrainStore.load(self.root)
        reviewed = dict(store.get(pid))
        reviewed["status"] = "reviewed"  # 사용 시점 promote 모사
        BrainStore.save_object(self.root, reviewed)
        rc2, payload = self._run("--write", "--replace")
        self.assertEqual(rc2, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("intentionally blocked", payload["error"])
        # 기존 reviewed가 candidate로 덮이지 않는다(보존).
        self.assertEqual(BrainStore.load(self.root).get(pid)["status"], "reviewed")


class TestCliProjectionRefresh(unittest.TestCase):
    """`projection refresh` (C3) — 저장 ContextProjection의 source_content_hash를 현재
    store로 재계산해 같은 status로 ingest 경유 재저장한다. C2로 해시식이 바뀐 뒤 기존
    projection이 전부 stale가 되므로 전수 마이그레이션 경로. reviewed도 갱신된다
    (ingest는 reviewed→reviewed 멱등 재적재 허용 — promote의 idempotency 가드와 다름)."""

    GEN_AT = "2026-06-17T00:00:00+09:00"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        from tests.test_search import domain_mapping
        from project_brain.context_projection import build_reuse_projection
        BrainStore.save_object(self.root, context("context.neutral"))
        BrainStore.save_object(
            self.root,
            domain_mapping("mapping.neutral.race-end", meaning="경주 종료",
                           status="candidate", context_id="context.neutral"))
        store = BrainStore.load(self.root)
        proj = build_reuse_projection(
            store, context_id="context.neutral", requirement_key="rpr",
            source_object_ids=["mapping.neutral.race-end"],
            reuse_payload="착수 브리핑", title="브리핑",
            generated_at=self.GEN_AT, generated_by="t")
        self.pid = proj["id"]
        # 일부러 stale: 저장 hash를 틀린 값으로(C2 이전 옛 해시·수작업 오류 모사).
        proj["source_content_hash"] = "stale-wrong-hash"
        BrainStore.save_object(self.root, proj)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_refresh(self, *extra):
        out = io.StringIO()
        argv = ["projection", "refresh", "--brain-root", str(self.root), *extra]
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_refresh_recomputes_stale_hash_and_lint_clean(self):
        from project_brain.lint import lint_store, _compute_source_content_hash
        store = BrainStore.load(self.root)
        # 전제: 지금은 stale(저장 hash != 현재 store 재계산값).
        self.assertNotEqual(
            store.get(self.pid)["source_content_hash"],
            _compute_source_content_hash(store, ["mapping.neutral.race-end"]))
        rc, payload = self._run_refresh()
        self.assertEqual(rc, 0, payload)
        self.assertIn(self.pid, payload["refreshed"])
        store2 = BrainStore.load(self.root)
        # 재계산된 hash로 교정 → lint가 이 projection을 mismatch로 보고하지 않는다.
        self.assertEqual(
            store2.get(self.pid)["source_content_hash"],
            _compute_source_content_hash(store2, ["mapping.neutral.race-end"]))
        self.assertEqual([p for p in lint_store(store2) if self.pid in p], [])

    def test_refresh_updates_reviewed_projection(self):
        # reviewed projection도 갱신된다(plan C3 Step1 명시) — ingest 후퇴 가드는
        # reviewed→candidate만 막고 reviewed→reviewed 멱등 재적재는 허용한다.
        store = BrainStore.load(self.root)
        proj = dict(store.get(self.pid))
        proj["status"] = "reviewed"
        proj["source_content_hash"] = "stale-wrong-hash"
        BrainStore.save_object(self.root, proj)
        rc, payload = self._run_refresh()
        self.assertEqual(rc, 0, payload)
        self.assertIn(self.pid, payload["refreshed"])
        store2 = BrainStore.load(self.root)
        self.assertEqual(store2.get(self.pid)["status"], "reviewed")
        from project_brain.lint import _compute_source_content_hash
        self.assertEqual(
            store2.get(self.pid)["source_content_hash"],
            _compute_source_content_hash(store2, ["mapping.neutral.race-end"]))

    DANGLING_ID = "projection.neutral.dangling.reuse"

    def _save_dangling(self):
        # 구성 객체가 store에 없는(dangling) ContextProjection. schema는 통과(dangling은 lint 영역).
        BrainStore.save_object(self.root, {
            "id": self.DANGLING_ID, "kind": "ContextProjection",
            "schema_version": "0.1", "status": "candidate", "poc_priority": "P0",
            "truth_role": "index", "title": "끊긴 브리핑", "context_id": "context.neutral",
            "format": "prompt_payload", "reuse_payload": "x",
            "output_locator": "indexes/context_projections/dangling.txt",
            "source_object_ids": ["mapping.does-not-exist"],
            "source_content_hash": "whatever", "projection_hash": "y",
            "generated_at": self.GEN_AT, "generated_by": "t",
            "stale_policy": "fail_on_manual_edit",
            "created_at": self.GEN_AT, "updated_at": self.GEN_AT, "tags": [], "evidence_refs": [],
        })

    def test_refresh_dangling_blocks_with_clear_error(self):
        # dangling projection은 재계산해도 merged lint(전수)를 못 지나고 store에 남아 ingest를
        # 막는다. 혼란스러운 IngestError 대신 명확히 빠른 실패하고 skipped_dangling을 출력에
        # 담는다(먼저 dangling 소스를 해소하라는 안내).
        self._save_dangling()
        rc, payload = self._run_refresh("--ids", self.DANGLING_ID)
        self.assertEqual(rc, 1, payload)
        self.assertFalse(payload["ok"])
        self.assertIn(self.DANGLING_ID, payload["skipped_dangling"])
        self.assertIn("dangling", payload["error"])

    def test_refresh_mixed_dangling_and_stale_fails_atomically(self):
        # MEDIUM 회귀(code-review): 갱신 가능 stale(self.pid)과 dangling이 함께 있는 전수 실행
        # (--ids 없이)에서, dangling이 lint를 막아 refresh가 통째로 막힌다. 빠른 실패로
        # skipped_dangling을 출력에 담고, 갱신 가능분은 디스크에 쓰지 않는다(원자성).
        self._save_dangling()
        before = BrainStore.load(self.root).get(self.pid)["source_content_hash"]
        rc, payload = self._run_refresh()  # --ids 없이 전수
        self.assertEqual(rc, 1, payload)
        self.assertIn(self.DANGLING_ID, payload["skipped_dangling"])
        # 갱신 가능분(self.pid)은 안 쓰였다 — 여전히 stale(원자성).
        after = BrainStore.load(self.root).get(self.pid)["source_content_hash"]
        self.assertEqual(before, after)


class TestCliTopLevelHelp(unittest.TestCase):
    """최상위 --help가 서브커맨드 목록을 보여준다(터미널에서 명령을 발견하는 경로)."""

    def test_help_lists_subcommands_including_graph(self):
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli", "--help"]), redirect_stdout(out):
            with self.assertRaises(SystemExit):
                cli.main()
        text = out.getvalue()
        self.assertIn("graph", text)
        self.assertIn("ingest", text)
        self.assertIn("search", text)
        # bare "show"는 "-h: show this help message"와 겹쳐 거짓통과 — 서브커맨드
        # 목록 줄(검색·색인)에 실제로 실렸는지로 검사한다.
        self.assertRegex(text, r"검색·색인.*\bshow\b")


class TestCliShow(unittest.TestCase):
    """cli show <id> — 단일 객체 본문 + 1-hop 이웃(저장소에 실존하는 참조만)을 종류·
    제목과 함께 낸다(회상 결과에서 그래프 연결을 손수 따라가는 탐색 입구)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _show(self, oid):
        argv = ["show", oid, "--brain-root", str(self.root)]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_show_object_with_neighbors(self):
        from tests.test_search import (
            build_store_dir, code_locator, domain_mapping, glossary_term,
        )
        build_store_dir(self.root, [
            glossary_term("g.race", term="레이스"),
            code_locator("code.x", path="a/Race.cpp", symbol="Race::start"),
            domain_mapping("m.x", meaning="레이스 시작",
                           glossary_term_ids=["g.race"], code_locator_ids=["code.x"]),
        ])
        rc, payload = self._show("m.x")
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["object"]["id"], "m.x")
        by_nb = {n["object_id"]: n for n in payload["neighbors"]}
        # 이웃은 저장소에 실존하는 참조만 — 종류·제목 동반.
        self.assertEqual(by_nb["g.race"]["kind"], "GlossaryTerm")
        self.assertEqual(by_nb["g.race"]["title"], "Term: 레이스")
        self.assertEqual(by_nb["code.x"]["kind"], "CodeLocator")
        # 끊긴 참조(evidence_refs=["ev.map"])·자기참조(id)는 이웃에 안 뜬다.
        self.assertNotIn("ev.map", by_nb)
        self.assertNotIn("m.x", by_nb)

    def test_show_attaches_stale_advisory_for_stale_mapping(self):
        # Step 2: show 대상이 stale-set에 들면 payload 최상위에 stale_advisory(객체 본문 불변).
        from project_brain.stale_check import write_stale_set
        from tests.test_search import build_store_dir, domain_mapping, glossary_term
        build_store_dir(self.root, [
            glossary_term("g.race", term="레이스"),
            domain_mapping("m.x", meaning="레이스 시작", glossary_term_ids=["g.race"]),
        ])
        write_stale_set(self.root, {
            "target_head": "T", "computed_at": "t", "stale_mapping_ids": ["m.x"],
            "detail": {"m.x": {"change_types": ["M"], "paths": ["a/X.cpp"]}}})
        rc, payload = self._show("m.x")
        self.assertEqual(rc, 0)
        self.assertEqual(payload["stale_advisory"]["change_types"], ["M"])
        self.assertNotIn("stale_advisory", payload["object"])  # 객체 본문은 불변

    def test_show_no_advisory_when_not_stale(self):
        from tests.test_search import build_store_dir, domain_mapping, glossary_term
        build_store_dir(self.root, [
            glossary_term("g.race", term="레이스"),
            domain_mapping("m.x", meaning="레이스 시작", glossary_term_ids=["g.race"]),
        ])
        rc, payload = self._show("m.x")  # 캐시 안 떨굼
        self.assertEqual(rc, 0)
        self.assertNotIn("stale_advisory", payload)

    def test_show_missing_id_errors(self):
        rc, payload = self._show("nope.404")
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("nope.404", payload["error"])


if __name__ == "__main__":
    unittest.main()
