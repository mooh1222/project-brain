"""cli.py 서브커맨드 테스트 (Task 5).

새 중립 합성 데이터(tempfile brain root + 인라인 객체 dict)만 사용한다 — 삭제된
fixture(tests/fixtures/...)를 일절 참조하지 않고 자기완결. bare 자유질의와 explicit search의
공개 동작, 네 조회 축 query, ingest 서브커맨드가 store에 적재하는지를 검증한다."""

import io
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from project_brain import assembly, cli
from project_brain.cli import _run_build
from project_brain.id_grammar import format_id
from project_brain.mutation import (
    MutationOperation,
    MutationService,
    corpus_fingerprint,
)
from project_brain.repo_context import (
    RepoContext,
    resolve_git_checkout,
)
from project_brain.store import BrainStore
from project_brain.transaction_receipt import BatchBinding
from tests.coverage_helpers import direct_coverage
from tests.test_ingest import (
    candidate_term,
    context,
    evidence_ref,
    manifest,
)
from tests.test_session import _completion_artifacts

ENGINE_ARGS = ("--engine-sha", "e" * 40)


def _commit_git_fixture(root: Path) -> str:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "cli@test.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "CLI Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "fixture"],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _context_object(ctx):
    from project_brain.assembly import build_context
    return build_context(
        {
            "context": {
                "key": ctx,
                "repo": "demoapp",
                "display_name": "합성 컨텍스트",
                "boundary_summary": "합성 테스트 경계",
            },
        },
        "2026-06-16T00:00:00Z",
    )[0]


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

    def _coverage_file(self, name, objects):
        path = self.input_dir / name
        path.write_text(
            json.dumps(direct_coverage(*objects), ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def _assembled_ingest_files(self):
        from tests.test_mutation import _assembled_artifacts

        coverage, objects, build_binding = _assembled_artifacts(
            self.root,
            context_mode="create",
        )
        objects_file = self.input_dir / "assembled-objects.json"
        coverage_file = self.input_dir / "assembled-coverage.json"
        report_file = self.input_dir / "assembled-build-report.json"
        objects_file.write_text(json.dumps(list(objects)), encoding="utf-8")
        coverage_file.write_text(json.dumps(coverage), encoding="utf-8")
        report = {
            "ok": True,
            "built": len(objects),
            "objects_file": str(objects_file),
            "diff": {},
            "resolved_refs": [],
            "preconditions": {},
            "warnings": [],
            "coverage_sha256": build_binding["coverage_sha256"],
            "expected_objects": build_binding["expected_objects"],
            "actual_objects": build_binding["actual_objects"],
            "objects_sha256": build_binding["objects_sha256"],
            "build_binding": build_binding,
        }
        report_file.write_text(json.dumps(report), encoding="utf-8")
        return objects_file, coverage_file, report_file, report

    def _run_ingest_error(self, *args):
        out = io.StringIO()
        with redirect_stdout(out):
            rc = cli._run_ingest(list(args))
        self.assertEqual(rc, 1)
        payload = json.loads(out.getvalue())
        self.assertEqual(
            set(payload),
            {"ok", "error_code", "error", "error_details"},
        )
        self.assertFalse(payload["ok"])
        return payload

    def _run_bare_and_explicit_search(self, args):
        outcomes = []
        for prefix in (["search"], []):
            out = io.StringIO()
            with mock.patch("sys.argv", ["cli", *prefix, *args]), redirect_stdout(out):
                rc = cli.main()
            outcomes.append((rc, json.loads(out.getvalue())))
        return outcomes

    def test_bare_free_query_matches_explicit_search(self):
        from project_brain.embedder import StubEmbedder
        from project_brain.search_index import rebuild
        from tests.test_search import glossary_term

        BrainStore.save_object(
            self.root,
            glossary_term("g.lane", term="레인", definition="레인 영역 배치"),
        )
        db = self.input_dir / "index.db"
        rebuild(self.root, db, embedder=StubEmbedder())
        args = [
            "레인 영역 배치",
            "--db",
            str(db),
            "--brain-root",
            str(self.root),
            "--stub-embedder",
        ]

        outcomes = self._run_bare_and_explicit_search(args)

        self.assertEqual([outcome[0] for outcome in outcomes], [0, 0])
        self.assertEqual(outcomes[1][1], outcomes[0][1])

    def test_bare_free_query_matches_search_missing_index_failure(self):
        args = [
            "레인 영역 배치",
            "--db",
            str(self.input_dir / "missing.db"),
            "--brain-root",
            str(self.root),
            "--stub-embedder",
        ]

        outcomes = self._run_bare_and_explicit_search(args)

        self.assertEqual(outcomes[1], outcomes[0])
        self.assertEqual(outcomes[1][0], 1)
        self.assertFalse(outcomes[1][1]["ok"])

    def test_bare_free_query_matches_search_stale_index_failure(self):
        from project_brain.embedder import StubEmbedder
        from project_brain.search_index import rebuild
        from tests.test_search import glossary_term

        BrainStore.save_object(
            self.root,
            glossary_term("g.lane", term="레인", definition="레인 영역 배치"),
        )
        db = self.input_dir / "index.db"
        rebuild(self.root, db, embedder=StubEmbedder())
        BrainStore.save_object(
            self.root,
            glossary_term("g.other", term="다른 레인", definition="색인 이후 변경"),
        )
        args = [
            "레인 영역 배치",
            "--db",
            str(db),
            "--brain-root",
            str(self.root),
            "--stub-embedder",
        ]

        outcomes = self._run_bare_and_explicit_search(args)

        self.assertEqual(outcomes[1], outcomes[0])
        self.assertEqual(outcomes[1][0], 1)
        self.assertFalse(outcomes[1][1]["ok"])

    def test_cli_query_and_simple_confirmation_leave_corpus_index_cache_and_git_unchanged(self):
        from project_brain.embedder import StubEmbedder
        from project_brain.search_index import rebuild

        for obj in (manifest(), evidence_ref(), candidate_term()):
            BrainStore.save_object(self.root, obj)
        db = self.root / ".brain-local" / "index.db"
        rebuild(self.root, db, embedder=StubEmbedder())
        stale_set = self.root / ".brain-local" / "stale-set.json"
        stale_set.write_bytes(b'{"computed_at":"before-query"}\n')
        _commit_git_fixture(self.root)

        def snapshot() -> dict[str, bytes]:
            return {
                str(path.relative_to(self.root)): path.read_bytes()
                for path in sorted(self.root.rglob("*"))
                if path.is_file() and ".git" not in path.parts
            }

        def git_status() -> str:
            return subprocess.run(
                ["git", "-C", str(self.root), "status", "--porcelain=v1"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout

        before_files = snapshot()
        before_git = git_status()
        for question in ("용어가 무슨 뜻이야?", "맞아"):
            out = io.StringIO()
            with mock.patch(
                "sys.argv",
                [
                    "cli",
                    "query",
                    "--brain-root",
                    str(self.root),
                    question,
                ],
            ), redirect_stdout(out):
                self.assertEqual(cli.main(), 0)
            self.assertIsInstance(json.loads(out.getvalue()), dict)

        self.assertEqual(snapshot(), before_files)
        self.assertEqual(git_status(), before_git)

    def test_explicit_query_subcommand_routes_without_becoming_query_text(self):
        with mock.patch.object(cli, "_run_query", return_value=0) as run_query, \
             mock.patch("sys.argv", ["cli", "query", "왜 바뀌었어?"]):
            rc = cli.main()
        self.assertEqual(rc, 0)
        run_query.assert_called_once_with(["왜 바뀌었어?"])

    def test_explicit_query_general_question_guides_to_search_then_show(self):
        from tests.test_search import domain_mapping, glossary_term

        for obj in (
            glossary_term("g.lane", term="레인", definition="레인 영역 배치"),
            domain_mapping(
                "m.lane",
                meaning="레인 영역 배치 의미",
                glossary_term_ids=["g.lane"],
            ),
            glossary_term(
                "g.candidate",
                term="후보 레인",
                definition="확인 전 레인 의미",
                status="candidate",
            ),
        ):
            BrainStore.save_object(self.root, obj)

        out = io.StringIO()
        with mock.patch(
            "sys.argv",
            ["cli", "query", "--brain-root", str(self.root), "레인은 무슨 뜻이야?"],
        ), redirect_stdout(out):
            self.assertEqual(cli.main(), 0)

        answer = json.loads(out.getvalue())
        self.assertEqual(answer["source_object_ids"], [])
        self.assertTrue(all(not section["object_ids"] for section in answer["sections"]))
        self.assertIn("project-brain search", json.dumps(answer, ensure_ascii=False))
        self.assertIn("project-brain show", json.dumps(answer, ensure_ascii=False))
        self.assertNotIn("promotable_candidate_ids", answer)
        self.assertNotIn("additional_candidates", answer)
        self.assertNotIn("advisories", answer)

    def test_explicit_query_does_not_read_index_for_deterministic_axis(self):
        invalid_db = self.input_dir / "invalid.db"
        invalid_db.write_text("not a sqlite database", encoding="utf-8")
        project = self.input_dir / "project"
        project.mkdir()
        (project / ".project-brain.json").write_text(
            json.dumps({"brain_root": str(self.root), "db": str(invalid_db)}),
            encoding="utf-8",
        )
        out = io.StringIO()
        with mock.patch("project_brain.config.Path.cwd", return_value=project), \
             mock.patch("sys.argv", ["cli", "query", "지금 상태는?"]), \
             redirect_stdout(out):
            rc = cli.main()

        self.assertEqual(rc, 0)
        answer = json.loads(out.getvalue())
        self.assertEqual(answer["intents"], ["current_status"])

    def test_explicit_query_evidence_does_not_add_general_recall_companions(self):
        from tests.test_search import domain_mapping, glossary_term

        for obj in (
            glossary_term("g.lane", term="레인", definition="레인 영역 배치"),
            domain_mapping(
                "m.lane",
                meaning="레인 영역 배치 의미",
                glossary_term_ids=["g.lane"],
            ),
        ):
            BrainStore.save_object(self.root, obj)

        out = io.StringIO()
        with mock.patch(
            "sys.argv",
            [
                "cli",
                "query",
                "--brain-root",
                str(self.root),
                "레인은 무슨 뜻이야? 근거는?",
            ],
        ), redirect_stdout(out):
            self.assertEqual(cli.main(), 0)

        answer = json.loads(out.getvalue())
        self.assertEqual(answer["source_object_ids"], [])
        self.assertEqual(
            {section["intent"] for section in answer["sections"]},
            {"evidence_provenance", "search_show"},
        )
        self.assertTrue(all(not section["object_ids"] for section in answer["sections"]))

    def test_audit_stale_check_and_mark_checked_use_configured_default_branch(self):
        from project_brain.stale_check import MarkCheckedPlan

        project = self.root / "project"
        brain = project / "brain"
        project.mkdir()
        (project / ".project-brain.json").write_text(
            json.dumps({"brain_root": "brain", "default_branch": "trunk"}),
            encoding="utf-8",
        )
        stale_calls = []
        head_calls = []

        def fake_stale_check(store, **kwargs):
            stale_calls.append(kwargs)
            return {"target_head": "HEAD", "candidates": [], "locator_group": [],
                    "unmerged_anchors": [], "coverage": {"covered_mappings": [],
                                                        "uncovered_mappings": []}}

        def fake_target_head(git_runner, **kwargs):
            head_calls.append(kwargs)
            return "HEAD"

        with mock.patch("project_brain.audit.make_git_runner", return_value=object()), \
             mock.patch("project_brain.audit.stale_check", side_effect=fake_stale_check), \
             mock.patch("sys.argv", ["cli", "audit", "--brain-root", str(brain), "--no-fetch"]), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(stale_calls[-1]["default_branch"], "trunk")

        with mock.patch("project_brain.stale_check.make_git_runner", return_value=object()), \
             mock.patch("project_brain.stale_check.stale_check", side_effect=fake_stale_check), \
             mock.patch("sys.argv", ["cli", "stale-check", "--brain-root", str(brain), "--no-fetch"]), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(stale_calls[-1]["default_branch"], "trunk")

        mark_context = RepoContext(
            repo_root=project,
            expected_repo_id="demo",
            expected_revision_ref="HEAD",
            target_revision_sha="a" * 40,
        )
        with mock.patch("project_brain.stale_check.make_git_runner", return_value=object()), \
             mock.patch("project_brain.stale_check.resolve_target_head", side_effect=fake_target_head), \
             mock.patch(
                 "project_brain.stale_check.plan_mark_checked",
                 return_value=MarkCheckedPlan(
                     updated=(),
                     blocked=(),
                     warnings=(),
                     preconditions={},
                     expected_corpus_fingerprint="f" * 64,
                     repo_context=mark_context,
                     engine_sha="e" * 40,
                 ),
             ), \
             mock.patch.object(
                 cli,
                 "_resolve_mutation_context",
                 return_value=mark_context,
             ), \
             mock.patch("sys.argv", ["cli", "mark-checked", "--brain-root", str(brain),
                                      "--mappings", "mapping.neutral.any",
                                      "--checked-head", "HEAD", "--no-fetch",
                                      *ENGINE_ARGS]), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(head_calls[-1]["default_branch"], "trunk")

    def test_cli_ingest_subcommand_writes(self):
        bundle = [manifest(), evidence_ref(), context(), candidate_term()]
        objects_file = self.input_dir / "bundle.json"
        objects_file.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        coverage_file = self._coverage_file("bundle.coverage.json", bundle)
        argv = [
            "ingest",
            "--brain-root",
            str(self.root),
            "--objects-file",
            str(objects_file),
            "--coverage-file",
            str(coverage_file),
            *ENGINE_ARGS,
        ]
        out = io.StringIO()
        original_apply = MutationService.apply
        from project_brain import ingest as ingest_module
        with mock.patch.object(
            BrainStore,
            "save_object",
            side_effect=AssertionError("direct save_object call"),
        ), mock.patch.object(
            MutationService,
            "apply",
            autospec=True,
            side_effect=original_apply,
        ) as apply, mock.patch(
            "project_brain.ingest._new_mutation_service",
            return_value=MutationService(
                clock=lambda: "2026-08-05T12:34:56+09:00"
            ),
        ), mock.patch(
            "sys.argv",
            ["cli"] + argv,
        ), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        self.assertEqual(apply.call_count, 1)
        payload = json.loads(out.getvalue())
        expected = {
            "version": 1,
            "receipt_id": "2fe42bc987bc38e0e05be551dcaf83b9395601e3d070a2834d2b335a57e5fa20",
            "ok": True,
            "outcome": "committed",
            "operation": "ingest",
            "committed": True,
            "transaction_id": "f145095bc82fa708e13872dda9795a4314575129900e85f29af7e2f06e78d302",
            "manifest_sha256": "ccba14bfe72888682d7f37b5d76e47c05b40e7c9bc2f63ec74e87fe32c37b623",
            "coverage_sha256": "7a05b32eed05a81200013ec59f03a058dcc3038552d121c296fb1f37b6ee5fe9",
            "expected_objects": [
                {"id": "context.neutral", "kind": "DomainContext"},
                {"id": "evref.neutral.ref", "kind": "EvidenceRef"},
                {"id": "g.neutral.x", "kind": "GlossaryTerm"},
                {
                    "id": "manifest.neutral.source",
                    "kind": "EvidenceManifest",
                },
            ],
            "verified_objects": [
                {"id": "context.neutral", "kind": "DomainContext"},
                {"id": "evref.neutral.ref", "kind": "EvidenceRef"},
                {"id": "g.neutral.x", "kind": "GlossaryTerm"},
                {
                    "id": "manifest.neutral.source",
                    "kind": "EvidenceManifest",
                },
            ],
            "changed_objects": [
                {
                    "action": "create",
                    "id": "context.neutral",
                    "kind": "DomainContext",
                },
                {
                    "action": "create",
                    "id": "evref.neutral.ref",
                    "kind": "EvidenceRef",
                },
                {
                    "action": "create",
                    "id": "g.neutral.x",
                    "kind": "GlossaryTerm",
                },
                {
                    "action": "create",
                    "id": "manifest.neutral.source",
                    "kind": "EvidenceManifest",
                },
            ],
            "before_fingerprint": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "after_fingerprint": "d279ffd2f0bc7f7bc105ec27031bbbacdd0d582cd2a5d612887db4634ebb1848",
        }
        self.assertEqual(payload, expected)
        self.assertIs(
            apply.call_args.kwargs["request"].operation,
            MutationOperation.INGEST,
        )
        # ingest()가 호출되어 store에 적재됨
        store = BrainStore.load(self.root)
        self.assertTrue(store.has("manifest.neutral.source"))
        self.assertTrue(store.has("evref.neutral.ref"))
        self.assertEqual(store.get("g.neutral.x")["status"], "candidate")

    def test_cli_ingest_no_change_is_exit_zero_without_commit(self):
        obj = context()
        objects_file = self.input_dir / "noop-bundle.json"
        objects_file.write_text(json.dumps([obj], ensure_ascii=False), encoding="utf-8")
        coverage_file = self._coverage_file("noop.coverage.json", [obj])
        argv = [
            "cli",
            "ingest",
            "--brain-root",
            str(self.root),
            "--objects-file",
            str(objects_file),
            "--coverage-file",
            str(coverage_file),
            *ENGINE_ARGS,
        ]
        from project_brain import ingest as ingest_module
        service = MutationService(clock=lambda: "2026-08-05T12:34:56+09:00")
        with mock.patch.object(
            ingest_module,
            "_new_mutation_service",
            return_value=service,
        ), mock.patch("sys.argv", argv), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        out = io.StringIO()
        with mock.patch.object(
            ingest_module,
            "_new_mutation_service",
            return_value=service,
        ), mock.patch("sys.argv", argv), redirect_stdout(out):
            rc = cli.main()

        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(payload["outcome"], "no_changes")
        self.assertIs(payload["committed"], False)
        self.assertIsNone(payload["transaction_id"])

    def test_cli_ingest_requires_coverage_file(self):
        objects_file = self.input_dir / "missing-coverage-objects.json"
        objects_file.write_text("[]", encoding="utf-8")

        with self.assertRaises(SystemExit):
            cli._run_ingest([
                "--brain-root",
                str(self.root),
                "--objects-file",
                str(objects_file),
                *ENGINE_ARGS,
            ])

    def test_cli_direct_coverage_rejects_build_report(self):
        obj = context()
        objects_file = self.input_dir / "direct-objects.json"
        objects_file.write_text(json.dumps([obj]), encoding="utf-8")
        coverage_file = self._coverage_file("direct-coverage.json", [obj])
        report_file = self.input_dir / "direct-report.json"
        report_file.write_text("{}", encoding="utf-8")

        payload = self._run_ingest_error(
            "--brain-root",
            str(self.root),
            "--objects-file",
            str(objects_file),
            "--coverage-file",
            str(coverage_file),
            "--build-report",
            str(report_file),
            *ENGINE_ARGS,
        )

        self.assertEqual(payload["error_code"], "coverage_binding_mismatch")
        self.assertEqual(payload["error_details"]["unexpected"], ["build_report"])

    def test_cli_assembled_coverage_requires_build_report_as_json_error(self):
        objects_file, coverage_file, _, _ = self._assembled_ingest_files()

        payload = self._run_ingest_error(
            "--brain-root",
            str(self.root),
            "--objects-file",
            str(objects_file),
            "--coverage-file",
            str(coverage_file),
            *ENGINE_ARGS,
        )

        self.assertEqual(payload["error_code"], "coverage_binding_mismatch")
        self.assertEqual(payload["error_details"]["missing"], ["build_report"])

    def test_cli_assembled_coverage_rejects_preconditions_as_json_error(self):
        objects_file, coverage_file, report_file, _ = (
            self._assembled_ingest_files()
        )
        preconditions_file = self.input_dir / "assembled-preconditions.json"
        preconditions_file.write_text("{}", encoding="utf-8")

        payload = self._run_ingest_error(
            "--brain-root",
            str(self.root),
            "--objects-file",
            str(objects_file),
            "--coverage-file",
            str(coverage_file),
            "--build-report",
            str(report_file),
            "--preconditions-file",
            str(preconditions_file),
            *ENGINE_ARGS,
        )

        self.assertEqual(payload["error_code"], "coverage_binding_mismatch")
        self.assertEqual(
            payload["error_details"]["unexpected"],
            ["preconditions_file"],
        )

    def test_cli_invalid_coverage_uses_ingest_error_json_shape(self):
        objects_file = self.input_dir / "invalid-coverage-objects.json"
        coverage_file = self.input_dir / "invalid-coverage.json"
        objects_file.write_text("[]", encoding="utf-8")
        coverage_file.write_text("{", encoding="utf-8")

        payload = self._run_ingest_error(
            "--brain-root",
            str(self.root),
            "--objects-file",
            str(objects_file),
            "--coverage-file",
            str(coverage_file),
            *ENGINE_ARGS,
        )

        self.assertEqual(payload["error_code"], "coverage_invalid")
        self.assertIsInstance(payload["error"], str)
        self.assertIsInstance(payload["error_details"], dict)

    def test_cli_recomputed_object_sha_uses_ingest_error_json_shape(self):
        objects_file, coverage_file, report_file, _ = (
            self._assembled_ingest_files()
        )
        objects = json.loads(objects_file.read_text(encoding="utf-8"))
        objects[0]["title"] = "build 뒤 변조"
        objects_file.write_text(json.dumps(objects), encoding="utf-8")

        payload = self._run_ingest_error(
            "--brain-root",
            str(self.root),
            "--objects-file",
            str(objects_file),
            "--coverage-file",
            str(coverage_file),
            "--build-report",
            str(report_file),
            *ENGINE_ARGS,
        )

        self.assertEqual(payload["error_code"], "coverage_binding_mismatch")
        self.assertEqual(payload["error_details"]["section"], "objects")

    def test_cli_assembled_build_report_rejects_unknown_top_level_key(self):
        objects_file, coverage_file, report_file, report = (
            self._assembled_ingest_files()
        )
        report["future_field"] = True
        report_file.write_text(json.dumps(report), encoding="utf-8")

        payload = self._run_ingest_error(
            "--brain-root",
            str(self.root),
            "--objects-file",
            str(objects_file),
            "--coverage-file",
            str(coverage_file),
            "--build-report",
            str(report_file),
            *ENGINE_ARGS,
        )

        self.assertEqual(payload["error_code"], "coverage_binding_mismatch")
        self.assertEqual(payload["error_details"]["section"], "build_report")
        self.assertEqual(payload["error_details"]["unexpected"], ["future_field"])

    def test_cli_preserves_structured_coverage_failure(self):
        obj = context()
        objects_file = self.input_dir / "kind-mismatch-objects.json"
        objects_file.write_text(json.dumps([obj]), encoding="utf-8")
        coverage = direct_coverage(obj)
        obj["kind"] = "GlossaryTerm"
        objects_file.write_text(json.dumps([obj]), encoding="utf-8")
        coverage_file = self.input_dir / "kind-mismatch-coverage.json"
        coverage_file.write_text(json.dumps(coverage), encoding="utf-8")
        out = io.StringIO()

        with redirect_stdout(out):
            rc = cli._run_ingest([
                "--brain-root",
                str(self.root),
                "--objects-file",
                str(objects_file),
                "--coverage-file",
                str(coverage_file),
                *ENGINE_ARGS,
            ])

        self.assertEqual(rc, 1)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["error_code"], "coverage_binding_mismatch")
        self.assertEqual(
            payload["error_details"]["object_id"],
            obj["id"],
        )

    def test_cli_batch_ingest_binds_inputs_state_and_durable_receipt(self):
        project = self.input_dir / "batch-project"
        brain = project / "brain"
        project.mkdir()
        brain.mkdir()
        (project / ".project-brain.json").write_text(
            json.dumps({"brain_root": "brain", "repo": "demo"}),
            encoding="utf-8",
        )
        _commit_git_fixture(project)
        target_sha = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        engine = resolve_git_checkout(Path(cli.__file__))
        brain_stat = brain.stat()
        verify = self.input_dir / "batch-verify.json"
        domain = self.input_dir / "batch-domain.py"
        verify.write_text("{}\n", encoding="utf-8")
        obj = context()
        coverage_file = self._coverage_file("batch.coverage.json", [obj])
        coverage_contract = direct_coverage(obj)
        domain.write_text(
            f"COVERAGE = {coverage_contract!r}\n",
            encoding="utf-8",
        )
        from project_brain.coverage import read_coverage

        binding = BatchBinding(
            batch_manifest_sha256="a" * 64,
            item_key="one",
            item_input_fingerprint="b" * 64,
            verify_json_sha256=hashlib.sha256(
                verify.read_bytes()
            ).hexdigest(),
            domain_spec_py_sha256=hashlib.sha256(
                domain.read_bytes()
            ).hexdigest(),
            coverage_sha256=read_coverage(coverage_file).sha256,
            repo_root=str(project.resolve()),
            brain_root=str(brain.resolve()),
            brain_root_device=brain_stat.st_dev,
            brain_root_inode=brain_stat.st_ino,
            expected_repo_id="demo",
            expected_revision_ref="HEAD",
            target_revision_sha=target_sha,
            engine_root=str(engine.root),
            engine_sha=engine.head_sha,
        )
        binding_file = self.input_dir / "batch-binding.json"
        binding_file.write_text(
            json.dumps(
                asdict(binding),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        objects_file = self.input_dir / "batch-objects.json"
        objects_file.write_text(
            json.dumps([obj], ensure_ascii=False),
            encoding="utf-8",
        )
        wrong_project = self.input_dir / "wrong-batch-project"
        wrong_brain = wrong_project / "brain"
        wrong_brain.mkdir(parents=True)
        (wrong_project / ".project-brain.json").write_text(
            json.dumps({"brain_root": "brain", "repo": "demo"}),
            encoding="utf-8",
        )
        wrong_obj = dict(obj)
        wrong_obj["title"] = "wrong corpus sentinel"
        wrong_path = BrainStore.object_path(wrong_brain, wrong_obj)
        wrong_path.parent.mkdir(parents=True)
        wrong_path.write_bytes(BrainStore.object_bytes(wrong_obj))
        out = io.StringIO()
        original_apply = MutationService.apply
        argv = [
            "cli",
            "ingest",
            "--brain-root",
            str(brain.resolve()),
            "--objects-file",
            str(objects_file),
            "--coverage-file",
            str(coverage_file),
            "--repo-root",
            str(project.resolve()),
            "--expected-repo-id",
            "demo",
            "--expected-revision-ref",
            "HEAD",
            "--engine-sha",
            engine.head_sha,
            "--batch-binding-file",
            str(binding_file.resolve()),
            "--verify-json",
            str(verify.resolve()),
            "--domain-spec-py",
            str(domain.resolve()),
        ]

        original_cwd = Path.cwd()
        try:
            os.chdir(wrong_project)
            with mock.patch.object(
                MutationService,
                "apply",
                autospec=True,
                side_effect=original_apply,
            ) as apply, mock.patch("sys.argv", argv), redirect_stdout(out):
                self.assertEqual(cli.main(), 0)
        finally:
            os.chdir(original_cwd)

        payload = json.loads(out.getvalue())
        self.assertTrue(payload["committed"])
        self.assertEqual(payload["changed_objects"], [
            {"action": "create", "id": obj["id"], "kind": obj["kind"]}
        ])
        request = apply.call_args.kwargs["request"]
        self.assertEqual(request.batch_binding, binding)
        self.assertEqual(
            request.repo_context.target_revision_sha,
            binding.target_revision_sha,
        )
        self.assertEqual(
            BrainStore.load(wrong_brain).get(obj["id"])["title"],
            "wrong corpus sentinel",
        )

    def test_cli_ingest_resolves_config_repo_context_and_exact_revision(self):
        from tests.test_mutation import _code_locator, _write_raw

        project = self.input_dir / "project"
        brain = project / "brain"
        project.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=project,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=project,
            check=True,
        )
        (project / "Foo.cpp").write_text(
            "void Foo::bar() {}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "Foo.cpp"], cwd=project, check=True)
        subprocess.run(
            ["git", "commit", "-qm", "fixture"],
            cwd=project,
            check=True,
        )
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/develop", sha],
            cwd=project,
            check=True,
        )
        (project / ".project-brain.json").write_text(
            json.dumps({
                "brain_root": "brain",
                "repo": "demo",
                "default_branch": "develop",
            }),
            encoding="utf-8",
        )
        locator = _code_locator(commit_sha=sha, verified_at=None)
        objects_file = self.input_dir / "locator-bundle.json"
        objects_file.write_text(
            json.dumps([locator], ensure_ascii=False),
            encoding="utf-8",
        )
        coverage_file = self._coverage_file("locator.coverage.json", [locator])
        argv = [
            "ingest",
            "--brain-root",
            str(brain.resolve()),
            "--objects-file",
            str(objects_file),
            "--coverage-file",
            str(coverage_file),
            *ENGINE_ARGS,
        ]
        original_apply = MutationService.apply
        with mock.patch.object(
            BrainStore,
            "save_object",
            side_effect=AssertionError("direct save_object call"),
        ), mock.patch.object(
            MutationService,
            "apply",
            autospec=True,
            side_effect=original_apply,
        ) as apply, mock.patch(
            "sys.argv",
            ["cli"] + argv,
        ), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)

        request = apply.call_args.kwargs["request"]
        self.assertEqual(request.brain_root, brain.resolve())
        self.assertEqual(request.repo_context.repo_root, project.resolve())
        self.assertEqual(request.repo_context.expected_repo_id, "demo")
        self.assertEqual(
            request.repo_context.expected_revision_ref,
            "origin/develop",
        )
        self.assertEqual(request.repo_context.target_revision_sha, sha)
        self.assertEqual(request.engine_sha, "e" * 40)
        stored = BrainStore.load(brain).get(locator["id"])
        self.assertEqual(stored["title"], "Foo::bar")
        self.assertIn("verified_at", stored)

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

    def test_cli_index_rebuild_lock_contention_is_normal_json_failure(self):
        from project_brain.search_index import IndexRebuildInProgressError

        argv = ["index", "rebuild", "--brain-root", str(self.root),
                "--db", str(self.input_dir / "index.db"), "--stub-embedder"]
        out = io.StringIO()
        with mock.patch.object(
            cli, "index_rebuild",
            side_effect=IndexRebuildInProgressError("색인 재구축이 이미 진행 중입니다"),
        ), mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()

        self.assertEqual(rc, 1)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["committed"])
        self.assertIn("진행 중", payload["error"])

    def test_cli_index_rebuild_structures_precommit_runtime_and_os_errors(self):
        argv = ["index", "rebuild", "--brain-root", str(self.root),
                "--db", str(self.input_dir / "index.db"), "--stub-embedder"]
        cases = [
            ("get_embedder", RuntimeError("injected embedder failure")),
            ("index_rebuild", OSError("injected replace failure")),
        ]
        for target, error in cases:
            with self.subTest(target=target):
                out = io.StringIO()
                err = io.StringIO()
                with mock.patch.object(cli, target, side_effect=error), \
                     mock.patch("sys.argv", ["cli"] + argv), \
                     redirect_stdout(out), redirect_stderr(err):
                    rc = cli.main()

                self.assertEqual(rc, 1)
                payload = json.loads(out.getvalue())
                self.assertFalse(payload["ok"])
                self.assertFalse(payload["committed"])
                self.assertIn(str(error), payload["error"])
                self.assertEqual(err.getvalue(), "")

    def test_cli_index_rebuild_does_not_swallow_keyboard_interrupt(self):
        argv = ["index", "rebuild", "--brain-root", str(self.root),
                "--db", str(self.input_dir / "index.db"), "--stub-embedder"]
        interrupted = KeyboardInterrupt("injected interrupt")
        with mock.patch.object(cli, "index_rebuild", side_effect=interrupted), \
             mock.patch("sys.argv", ["cli"] + argv):
            with self.assertRaises(KeyboardInterrupt) as ctx:
                cli.main()
        self.assertIs(ctx.exception, interrupted)

    def test_cli_index_rebuild_durability_failure_reports_committed(self):
        from project_brain.search_index import IndexRebuildDurabilityError

        argv = ["index", "rebuild", "--brain-root", str(self.root),
                "--db", str(self.input_dir / "index.db"), "--stub-embedder"]
        out = io.StringIO()
        with mock.patch.object(
            cli, "index_rebuild",
            side_effect=IndexRebuildDurabilityError("새 DB는 이미 교체됐습니다"),
        ), mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()

        self.assertEqual(rc, 1)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["committed"])
        self.assertIn("교체", payload["error"])

    def test_cli_bootstrap_lock_contention_is_json_failure_with_uncommitted_state(self):
        from project_brain.search_index import IndexRebuildInProgressError

        brain = self.root / "brain"
        (brain / "objects").mkdir(parents=True)
        cfg = {"brain_root": brain, "db": self.input_dir / "index.db"}
        out = io.StringIO()
        with mock.patch("project_brain.installer.install", return_value={"ok": True}), \
             mock.patch("project_brain.config.load_config", return_value=cfg), \
             mock.patch.object(cli, "index_rebuild",
                               side_effect=IndexRebuildInProgressError("색인 재구축이 진행 중")), \
             mock.patch("sys.argv", ["cli", "bootstrap", "--stub-embedder"]), \
             redirect_stdout(out):
            rc = cli.main()

        self.assertEqual(rc, 1)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["committed"])
        self.assertIn("진행 중", payload["error"])

    def test_cli_bootstrap_structures_precommit_runtime_and_os_errors(self):
        brain = self.root / "brain"
        (brain / "objects").mkdir(parents=True)
        cfg = {"brain_root": brain, "db": self.input_dir / "index.db"}
        cases = [
            ("get_embedder", RuntimeError("injected embedder failure")),
            ("index_rebuild", OSError("injected file fsync failure")),
        ]
        for target, error in cases:
            with self.subTest(target=target):
                out = io.StringIO()
                err = io.StringIO()
                with mock.patch("project_brain.installer.install", return_value={"ok": True}), \
                     mock.patch("project_brain.config.load_config", return_value=cfg), \
                     mock.patch.object(cli, target, side_effect=error), \
                     mock.patch("sys.argv", ["cli", "bootstrap", "--stub-embedder"]), \
                     redirect_stdout(out), redirect_stderr(err):
                    rc = cli.main()

                self.assertEqual(rc, 1)
                payload = json.loads(out.getvalue())
                self.assertFalse(payload["ok"])
                self.assertFalse(payload["committed"])
                self.assertIn(str(error), payload["error"])
                self.assertEqual(err.getvalue(), "")

    def test_cli_lint_clean_store_ok(self):
        # 깨끗한 store(서로 참조 정상) → lint ok=true, problems 0 (test_lint.py와 동일 조합)
        for obj in (manifest(), evidence_ref(), context(), candidate_term()):
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
            self.root,
            insight(source_object_ids=[
                "mapping.neutral.gone",
                "mapping.neutral.gone2",
            ]),
        )
        argv = ["lint", "--brain-root", str(self.root)]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)
        report = json.loads(out.getvalue())
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("dangling source_object_ids" in p for p in report["problems"]))


def candidate_term_with_evidence(tid="g.neutral.x", term="갈고리"):
    """근거(ev.ref) 보유 candidate GlossaryTerm. promote 후 §6.4(reviewed 근거 필수)를 통과한다."""
    from project_brain.objbase import base
    tid = format_id("GlossaryTerm", ctx="neutral", key=tid.rsplit(".", 1)[-1])
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
            "evidence_refs": ["evref.neutral.ref"],
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
        from tests.test_ingest import ingest
        ingest(
            self.root,
            [manifest(), evidence_ref(), context(), candidate_term_with_evidence()],
        )

    def test_promote_round_trip(self):
        self._ingest()
        # promote 전: 후보가 candidate로 노출
        self.assertEqual(
            BrainStore.load(self.root).get("g.neutral.x")["status"],
            "candidate",
        )
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.neutral.x", "--reviewer", "user-confirmed",
            "--reviewed-at", "2026-06-06T00:00:00Z",
            *ENGINE_ARGS,
        ]
        out = io.StringIO()
        original_apply = MutationService.apply
        with mock.patch.object(
            BrainStore,
            "save_object",
            side_effect=AssertionError("direct save_object call"),
        ), mock.patch.object(
            MutationService,
            "apply",
            autospec=True,
            side_effect=original_apply,
        ) as apply, mock.patch(
            "sys.argv",
            ["cli"] + argv,
        ), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        self.assertEqual(apply.call_count, 1)
        self.assertIs(
            apply.call_args.kwargs["request"].operation,
            MutationOperation.PROMOTE,
        )
        result = json.loads(out.getvalue())
        self.assertTrue(result["ok"])
        store = BrainStore.load(self.root)
        # 승격 객체 + 검토 기록 둘 다 저장됨
        self.assertEqual(store.get("g.neutral.x")["status"], "reviewed")
        self.assertEqual(
            store.get("g.neutral.x")["review_record_id"],
            "review.g.neutral.x",
        )
        self.assertTrue(store.has("review.g.neutral.x"))
        # 없는 기록 가리킴 0건(사후 lint clean)
        from project_brain.lint import lint_store
        self.assertEqual(lint_store(store), [])

    def test_promote_reviewed_at_defaults_to_kst_when_omitted(self):
        from project_brain import ingest as ingest_module

        self._ingest()
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.neutral.x", "--reviewer", "user-confirmed",
            *ENGINE_ARGS,
        ]
        out = io.StringIO()
        with mock.patch.object(
            ingest_module,
            "_new_mutation_service",
            return_value=MutationService(
                clock=lambda: "2026-08-05T12:34:56+09:00"
            ),
        ), mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        rr = BrainStore.load(self.root).get("review.g.neutral.x")
        self.assertEqual(rr["reviewed_at"], "2026-08-05T12:34:56+09:00")
        self.assertEqual(rr["created_at"], rr["updated_at"])
        self.assertEqual(rr["reviewed_at"], rr["updated_at"])

    def test_promote_missing_id_returns_error(self):
        self._ingest()
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.neutral.nope", "--reviewer", "user-confirmed",
            "--reviewed-at", "2026-06-06T00:00:00Z",
            *ENGINE_ARGS,
        ]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)

    def test_promote_zero_evidence_rejected(self):
        # §6.4 활성 후: 근거 없는 candidate(candidate엔 §6.4 미적용 → 적재는 됨)를 승격하면
        # 승격 결과물(reviewed, 근거 빔)이 쓰기 전 일괄 검증에 걸려 rc=1, 디스크 불변(원자성).
        from tests.test_ingest import ingest
        from tests.test_ingest import candidate_term  # evidence_refs=[] 기본
        ingest(self.root, [context(), candidate_term("g.neutral.noev")])
        argv = [
            "promote", "--brain-root", str(self.root),
            "--ids", "g.neutral.noev", "--reviewer", "user-confirmed",
            "--reviewed-at", "2026-06-06T00:00:00Z",
            *ENGINE_ARGS,
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
        self.assertEqual(store.get("g.neutral.noev")["status"], "candidate")
        self.assertFalse(store.has("review.g.neutral.noev"))

    def test_promote_backfills_empty_evidence_from_mapping(self):
        # 빈 근거 candidate + 짝 reviewed 매핑 → 수동 promote가 backfill해 §6.4 통과.
        from tests.test_ingest import ingest
        ingest(self.root, [
            manifest(), _ar_evref("evref.a"), context(),
            _ar_term("g.empty", term="빈근거"),
            _ar_mapping("m.empty", term_ids=["g.empty"], evidence_refs=["evref.a"], mapping_key="me"),
        ])
        argv = ["promote", "--brain-root", str(self.root),
                "--ids", "g.neutral.empty", "--reviewer", "user-confirmed",
                "--reviewed-at", "2026-06-08T00:00:00Z", *ENGINE_ARGS]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.neutral.empty")["status"], "reviewed")
        self.assertEqual(
            store.get("g.neutral.empty")["evidence_refs"],
            ["evref.neutral.a"],
        )

    def test_promote_rejects_already_reviewed(self):
        # 멱등 가드: 같은 id 두 번 promote → 두 번째 rc=1.
        self._ingest()  # candidate g.x (term=갈고리, evidence 보유)
        base_argv = ["promote", "--brain-root", str(self.root),
                     "--ids", "g.neutral.x", "--reviewer", "user-confirmed",
                     "--reviewed-at", "2026-06-06T00:00:00Z", *ENGINE_ARGS]
        with mock.patch("sys.argv", ["cli"] + base_argv), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(), 0)
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + base_argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)
        self.assertIn("already reviewed", json.loads(out.getvalue())["error"])

    def test_promote_fails_closed_if_target_changes_before_apply(self):
        from project_brain.promote import promote

        self._ingest()
        original_apply = cli._apply_mutation

        def apply_after_competing_promotion(**kwargs):
            stale_target = BrainStore.load(self.root).get("g.neutral.x")
            first_promoted, first_records = promote(
                [stale_target],
                [stale_target["id"]],
                "single_object",
                reviewer="first-reviewer",
                reviewed_at="2026-06-05T00:00:00Z",
            )
            first_promoted[0]["updated_at"] = "2026-06-05T00:00:00Z"
            first_records[0]["created_at"] = "2026-06-05T00:00:00Z"
            first_records[0]["updated_at"] = "2026-06-05T00:00:00Z"
            for obj in first_promoted + first_records:
                BrainStore.save_object(self.root, obj)
            return original_apply(**kwargs)

        argv = [
            "promote",
            "--brain-root",
            str(self.root),
            "--ids",
            "g.neutral.x",
            "--reviewer",
            "second-reviewer",
            "--reviewed-at",
            "2026-06-06T00:00:00Z",
            *ENGINE_ARGS,
        ]
        out = io.StringIO()
        with mock.patch.object(
            cli,
            "_apply_mutation",
            side_effect=apply_after_competing_promotion,
        ), mock.patch(
            "sys.argv",
            ["cli"] + argv,
        ), redirect_stdout(out):
            rc = cli.main()

        self.assertEqual(rc, 1)
        stored = BrainStore.load(self.root)
        self.assertEqual(
            stored.get("review.g.neutral.x")["reviewer"],
            "first-reviewer",
        )
        self.assertEqual(
            stored.get("g.neutral.x")["updated_at"],
            "2026-06-05T00:00:00Z",
        )

    def test_promote_conflict_records_resolution(self):
        # 수동 conflict 승격(spec §5.2 사람 판정 허용) → 해소 근거가 검수 기록에 남음.
        from tests.test_ingest import ingest
        conflict_term = _ar_term("g.c", term="충돌", candidate_state="conflict",
                                 evidence_refs=["evref.a"])
        ingest(self.root, [manifest(), _ar_evref("evref.a"), context(), conflict_term])
        argv = ["promote", "--brain-root", str(self.root),
                "--ids", "g.neutral.c", "--reviewer", "user-confirmed",
                "--reviewed-at", "2026-06-08T00:00:00Z",
                "--conflict-resolution", "위키 정설 채택", *ENGINE_ARGS]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.neutral.c")["status"], "reviewed")
        self.assertEqual(
            store.get("review.g.neutral.c")["conflict_resolution"],
            "위키 정설 채택",
        )


def _ar_evref(rid, manifest_id="manifest.neutral.source"):
    from project_brain.objbase import base
    rid = format_id(
        "EvidenceRef",
        ctx="neutral",
        anchor_key=rid.rsplit(".", 1)[-1],
    )
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
    tid = format_id("GlossaryTerm", ctx="neutral", key=tid.rsplit(".", 1)[-1])
    canonical_evidence_refs = [
        format_id(
            "EvidenceRef",
            ctx="neutral",
            anchor_key=evidence_ref_id.rsplit(".", 1)[-1],
        )
        for evidence_ref_id in (evidence_refs if evidence_refs is not None else [])
    ]
    return base(
        {
            "id": tid, "kind": "GlossaryTerm", "status": "candidate", "truth_role": "domain",
            "title": f"Candidate term: {term}", "context_id": "context.neutral",
            "term": term, "definition": "후보 정의",
            "evidence_refs": canonical_evidence_refs,
            "candidate": {"candidate_state": candidate_state, "candidate_source": "spec"},
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


def _ar_mapping(mid, *, term_ids, evidence_refs, mapping_key):
    from project_brain.objbase import base
    mid = format_id("DomainMapping", ctx="neutral", key=mapping_key)
    term_ids = [
        format_id("GlossaryTerm", ctx="neutral", key=term_id.rsplit(".", 1)[-1])
        for term_id in term_ids
    ]
    evidence_refs = [
        format_id(
            "EvidenceRef",
            ctx="neutral",
            anchor_key=evidence_ref_id.rsplit(".", 1)[-1],
        )
        for evidence_ref_id in evidence_refs
    ]
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
        from tests.test_ingest import ingest
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
                "--ids", *ids, "--reviewed-at", "2026-06-08T00:00:00Z",
                *ENGINE_ARGS]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_batch_promotes_eligible_skips_conflict_and_unknown(self):
        self._ingest_corpus()
        original_apply = MutationService.apply
        with mock.patch.object(
            BrainStore,
            "save_object",
            side_effect=AssertionError("direct save_object call"),
        ), mock.patch.object(
            MutationService,
            "apply",
            autospec=True,
            side_effect=original_apply,
        ) as apply:
            rc, result = self._run([
                "g.neutral.empty",
                "g.neutral.has",
                "g.neutral.conflict",
                "g.neutral.multi",
                "g.neutral.nope",
            ])
        self.assertEqual(rc, 0)
        self.assertEqual(apply.call_count, 1)
        self.assertIs(
            apply.call_args.kwargs["request"].operation,
            MutationOperation.PROMOTE_AUTO,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            set(result["promoted"]),
            {"g.neutral.empty", "g.neutral.has", "g.neutral.multi"},
        )
        self.assertEqual(result["skipped"]["conflict"], ["g.neutral.conflict"])
        self.assertEqual(result["skipped"]["unknown_id"], ["g.neutral.nope"])
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.neutral.empty")["status"], "reviewed")
        # backfill: 빈 근거 용어가 짝 매핑 evref로 채워짐
        self.assertEqual(
            store.get("g.neutral.empty")["evidence_refs"],
            ["evref.neutral.a"],
        )
        from project_brain.lint import lint_store
        self.assertEqual(lint_store(store), [])

    def test_review_record_records_auto_reviewer_and_vouched_by(self):
        self._ingest_corpus()
        self._run(["g.neutral.empty", "g.neutral.multi"])
        store = BrainStore.load(self.root)
        rr_empty = store.get("review.g.neutral.empty")
        self.assertEqual(rr_empty["reviewer"], "auto:mapping-vouched")
        self.assertEqual(
            rr_empty["vouched_by_mapping_ids"],
            ["mapping.neutral.me"],
        )
        # 다중 참조: 보증 매핑 전부, 정렬됨
        rr_multi = store.get("review.g.neutral.multi")
        self.assertEqual(
            rr_multi["vouched_by_mapping_ids"],
            ["mapping.neutral.a", "mapping.neutral.z"],
        )

    def test_dedup_multi_mapping_promotes_once(self):
        self._ingest_corpus()
        rc, result = self._run(["g.neutral.multi", "g.neutral.multi"])
        self.assertEqual(rc, 0)
        self.assertEqual(result["promoted"], ["g.neutral.multi"])

    def test_rerun_is_idempotent(self):
        self._ingest_corpus()
        self._run(["g.neutral.empty", "g.neutral.has", "g.neutral.multi"])
        rc, result = self._run(
            ["g.neutral.empty", "g.neutral.has", "g.neutral.multi"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(result["promoted"], [])
        self.assertEqual(
            set(result["skipped"]["already_reviewed"]),
            {"g.neutral.empty", "g.neutral.has", "g.neutral.multi"},
        )

    def test_auto_fails_closed_if_vouching_snapshot_changes_before_apply(self):
        self._ingest_corpus()
        original_apply = cli._apply_mutation

        def apply_after_voucher_change(**kwargs):
            store = BrainStore.load(self.root)
            mapping = dict(store.get("mapping.neutral.me"))
            mapping["glossary_term_ids"] = []
            BrainStore.save_object(self.root, mapping)
            return original_apply(**kwargs)

        out = io.StringIO()
        argv = [
            "promote-auto",
            "--brain-root",
            str(self.root),
            "--ids",
            "g.neutral.empty",
            "--reviewed-at",
            "2026-06-08T00:00:00Z",
            *ENGINE_ARGS,
        ]
        with mock.patch.object(
            cli,
            "_apply_mutation",
            side_effect=apply_after_voucher_change,
        ), mock.patch(
            "sys.argv",
            ["cli"] + argv,
        ), redirect_stdout(out):
            rc = cli.main()

        self.assertEqual(rc, 1)
        stored = BrainStore.load(self.root)
        self.assertEqual(stored.get("g.neutral.empty")["status"], "candidate")
        self.assertFalse(stored.has("review.g.neutral.empty"))


def _ar_legacy_manifest(mid="manifest.neutral.wiki", source_type="wiki"):
    from project_brain.objbase import base
    mid = format_id(
        "EvidenceManifest",
        ctx="neutral",
        key=mid.rsplit(".", 1)[-1],
    )
    return base(
        {
            "id": mid, "kind": "EvidenceManifest", "status": "reviewed", "truth_role": "source",
            "title": "위키 manifest", "source_type": source_type, "locator": "wiki://x",
            "captured_at": "2026-06-04T00:00:00Z", "captured_by": "n", "sensitivity": "internal",
            "acl": ["team"], "redaction_status": "approved",
        },
        tags=["neutral"], created_at="2026-06-04T00:00:00Z", updated_at="2026-06-04T00:00:00Z",
    )


def _ar_legacy_evref(
    rid="evref.neutral.wiki",
    manifest_id="manifest.neutral.wiki",
):
    from project_brain.objbase import base
    rid = format_id(
        "EvidenceRef",
        ctx="neutral",
        anchor_key=rid.rsplit(".", 1)[-1],
    )
    manifest_id = format_id(
        "EvidenceManifest",
        ctx="neutral",
        key=manifest_id.rsplit(".", 1)[-1],
    )
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
        from tests.test_ingest import ingest
        term = _ar_term("g.legacy", term="레거시", evidence_refs=["evref.wiki"])
        ingest(self.root, [_ar_legacy_manifest(), _ar_legacy_evref(), context(), term])
        argv = ["promote", "--brain-root", str(self.root),
                "--ids", "g.neutral.legacy", "--reviewer", "user-confirmed",
                "--reviewed-at", "2026-06-08T00:00:00Z", *ENGINE_ARGS]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)
        self.assertIn("legacy-only", json.dumps(json.loads(out.getvalue()), ensure_ascii=False))
        # 원자성: 디스크 불변(부분 쓰기·review 기록 생성 없음)
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.neutral.legacy")["status"], "candidate")
        self.assertFalse(store.has("review.g.neutral.legacy"))

    def test_promote_auto_skips_legacy_only_evidence(self):
        # 짝 매핑 evidence가 wiki(legacy)뿐인 용어는 자동 승격 부적격 → skip. 정상 용어만 승격.
        from tests.test_ingest import ingest
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
                "--ids", "g.neutral.ok", "g.neutral.legacy",
                "--reviewed-at", "2026-06-08T00:00:00Z", *ENGINE_ARGS]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result["promoted"], ["g.neutral.ok"])
        self.assertEqual(
            result["skipped"]["legacy_only_evidence"],
            ["g.neutral.legacy"],
        )
        store = BrainStore.load(self.root)
        self.assertEqual(store.get("g.neutral.ok")["status"], "reviewed")
        self.assertEqual(store.get("g.neutral.legacy")["status"], "candidate")
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
        # 답변 게이트 폐지(#77) — 응답에 엔진 판정 플래그가 없다.
        self.assertNotIn("needs_clarification", payload)
        # reviewed 적중에 검수상태·linked(코드 위치)가 동반된다.
        ids = {h["object_id"] for h in payload["results"]}
        self.assertIn("mapping.neutral.lane", ids)
        m = next(
            h for h in payload["results"]
            if h["object_id"] == "mapping.neutral.lane"
        )
        self.assertEqual(m["status"], "reviewed")
        locs = {c["object_id"] for c in m["linked"]["code_locators"]}
        self.assertIn("code.neutral.lane", locs)
        linked = next(
            c for c in m["linked"]["code_locators"]
            if c["object_id"] == "code.neutral.lane"
        )
        self.assertEqual(
            linked,
            {
                "object_id": "code.neutral.lane",
                "path": "a/Lane.cpp",
                "symbol": "makeLanes",
                "quote_access": "indeterminate",
            },
        )

    def test_search_candidate_channel(self):
        from tests.test_search import glossary_term
        self._build_index([
            glossary_term("g.cand", term="레인", definition="레인 영역 배치", status="candidate"),
        ])
        rc, payload = self._search("레인 영역 배치")
        self.assertEqual(rc, 0)
        cand_ids = {h["object_id"] for h in payload["candidates"]}
        self.assertIn("g.neutral.cand", cand_ids)
        # reviewed 적중이 없으면 results는 빈 채로 나간다(판정 플래그 없음).
        self.assertEqual(payload["results"], [])
        self.assertNotIn("needs_clarification", payload)

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

    def test_search_advisories_channel(self):
        # reviewed Insight가 advisories 채널로 노출된다(spec 2026-06-15 §4.6).
        # 회귀 가드: eval_recall은 advisories를 반환하나 _run_search 출력에서
        # 빠져 있던 비대칭 누락 복구(2026-06-27). g.token이 anchor 토큰 제공.
        from tests.test_search import glossary_term, insight
        self._build_index([
            glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰 노출"),
            insight("insight.gate", body="클리어 토큰 노출 게이트가 두 팝업에 이중구현"),
        ])
        rc, payload = self._search("클리어 토큰 노출 게이트 이중구현")
        self.assertEqual(rc, 0)
        self.assertIn("advisories", payload)
        self.assertIn(
            "insight.neutral.gate",
            {h["object_id"] for h in payload["advisories"]},
        )
        for h in payload["advisories"]:
            self.assertEqual(h["trust_label"], "가로지르는 위험·교훈(검증됨)")

    # 신뢰 라벨을 덧붙이는 채널 — 그 외 키는 회수 응답 그대로 나와야 한다.
    _LABELED_CHANNELS = {"raw_excerpts", "advisories", "projection_reuse"}

    def test_search_passes_through_every_recall_key(self):
        """CLI가 회수 응답 키를 손으로 옮겨 적다 새 필드를 흘리지 않게 강제한다(#73).

        키 목록을 테스트에 적지 않고 eval_recall 응답에서 뽑아 대조한다 — 회수 진입점에
        키가 늘면 이 테스트가 CLI 누락을 잡는다(2026-06-27 advisories 누락 사고 재발 방지).
        """
        from project_brain.embedder import StubEmbedder
        from project_brain.search import eval_recall
        from tests.test_search import glossary_term, insight

        src = self.brain / "raw" / "sources" / "foo-ctx"
        src.mkdir(parents=True)
        (src / "spec.md").write_text(
            "# 클리어 토큰\n클리어 토큰 노출 기획 서술.\n", encoding="utf-8")
        self._build_index([
            glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰 노출"),
            insight("insight.gate", body="클리어 토큰 노출 게이트가 두 팝업에 이중구현"),
        ])
        query = "클리어 토큰 노출 게이트 이중구현"

        rc, payload = self._search(query)
        resp = eval_recall(query, db_path=self.db, embedder=StubEmbedder(),
                           brain_root=self.brain)

        self.assertEqual(rc, 0)
        self.assertEqual(set(resp) - set(payload), set())
        for key, value in resp.items():
            if key in self._LABELED_CHANNELS:
                # 라벨만 덧붙고 적중 순서·개수는 그대로다.
                self.assertEqual([h["object_id"] for h in payload[key]],
                                 [h["object_id"] for h in value])
            else:
                self.assertEqual(payload[key], value, key)

    def test_search_reports_query_token_facts_and_scope(self):
        # 회수 사실(#73)이 CLI JSON에 그대로 실린다 — 부재 토큰은 df 0으로 신고된다.
        from tests.test_search import glossary_term
        self._build_index([
            glossary_term("g.token", term="클리어 토큰", definition="스테이지 클리어 토큰 노출"),
        ])
        rc, payload = self._search("클리어 토큰 크리스마스")
        self.assertEqual(rc, 0)
        facts = {f["token"]: f for f in payload["query_tokens"]}
        self.assertEqual(facts["크리스마스"], {"token": "크리스마스",
                                          "object_df": 0, "raw_df": 0})
        self.assertGreater(facts["토큰"]["object_df"], 0)
        self.assertEqual(payload["scope"], {"context_id": None, "origin": "none"})
        for hit in payload["results"]:
            self.assertNotIn("크리스마스", hit["matched_query_tokens"])

    def test_audit_bundles_lint_isolated_skips_stale(self):
        # audit(코퍼스 감사): lint(무결성) + graph isolated(고아)를 한 보고로 묶는다.
        # stale는 git 의존이라 --no-stale로 건너뛴다(결정론). 고아 candidate 용어는
        # evidence_refs=[]라 dangling 없이 isolated만 잡힌다.
        from tests.test_search import glossary_term
        BrainStore.save_object(self.brain, context())
        BrainStore.save_object(
            self.brain, glossary_term("g.orphan", term="고아", definition="d", status="candidate"))
        argv = ["audit", "--no-stale", "--brain-root", str(self.brain)]
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 0)  # lint clean → rc 0
        self.assertTrue(payload["lint"]["ok"])
        self.assertIn("g.neutral.orphan", payload["isolated"]["isolated"])
        self.assertIsNone(payload["stale"])        # 기존 --no-stale 계약 보존
        self.assertTrue(payload["stale_status"]["ok"])
        self.assertTrue(payload["stale_status"]["skipped"])
        self.assertTrue(payload["code_quotes"]["check_skipped"])
        self.assertFalse(payload["code_quotes"]["ok"])
        self.assertEqual(payload["code_quotes"]["checked"], 0)
        self.assertIsNone(payload["cache_written"])

    def test_audit_timestamp_details_are_opt_in_and_canonical(self):
        legacy = manifest()
        legacy["captured_at"] = "legacy"
        BrainStore.save_object(self.brain, legacy)
        details = Path(self._tmp.name) / "timestamp-details.json"

        out = io.StringIO()
        with mock.patch(
            "sys.argv",
            ["cli", "audit", "--brain-root", str(self.brain), "--no-stale"],
        ), redirect_stdout(out):
            rc = cli.main()

        self.assertEqual(rc, 0)
        self.assertFalse(details.exists())
        self.assertNotIn("object_ids_by_bucket", out.getvalue())
        details.write_text("old", encoding="utf-8")

        out = io.StringIO()
        with mock.patch(
            "sys.argv",
            [
                "cli",
                "audit",
                "--brain-root",
                str(self.brain),
                "--no-stale",
                "--timestamp-details-file",
                str(details),
            ],
        ), redirect_stdout(out):
            rc = cli.main()

        expected = {
            "timestamp_format_legacy": {
                "count": 1,
                "by_field": {"captured_at": 1},
                "by_reason": {"not_datetime": 1},
                "by_date": {"unknown": 1},
            },
            "midnight_density": {
                "total_timestamp_values": 3,
                "midnight_values": 2,
                "ratio": 2 / 3,
                "by_field": {"created_at": 1, "updated_at": 1},
                "by_context": {"neutral": 2},
                "by_date": {"2026-06-04": 2},
            },
            "object_ids_by_bucket": {
                "timestamp_format_legacy": {
                    "captured_at:not_datetime": ["manifest.neutral.source"],
                },
                "midnight_density": {
                    "created_at": ["manifest.neutral.source"],
                    "updated_at": ["manifest.neutral.source"],
                },
            },
        }
        expected_bytes = (
            json.dumps(
                expected,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        self.assertEqual(rc, 0)
        self.assertNotIn("object_ids_by_bucket", out.getvalue())
        self.assertEqual(details.read_bytes(), expected_bytes)

    def test_audit_timestamp_details_reject_unsafe_output_paths(self):
        BrainStore.save_object(self.brain, manifest())
        target = Path(self._tmp.name) / "target.json"
        target.write_text("keep", encoding="utf-8")
        symlink = Path(self._tmp.name) / "details-link.json"
        symlink.symlink_to(target)
        directory = Path(self._tmp.name) / "details-dir"
        directory.mkdir()

        for unsafe in ("", "relative.json", str(symlink), str(directory)):
            with self.subTest(path=unsafe):
                out = io.StringIO()
                with mock.patch(
                    "sys.argv",
                    [
                        "cli",
                        "audit",
                        "--brain-root",
                        str(self.brain),
                        "--no-stale",
                        "--timestamp-details-file",
                        unsafe,
                    ],
                ), redirect_stdout(out):
                    rc = cli.main()
                payload = json.loads(out.getvalue())
                self.assertNotEqual(rc, 0)
                self.assertFalse(payload["ok"])
                self.assertTrue(payload["audit_ok"])
                self.assertFalse(payload["timestamp_details"]["ok"])
                self.assertNotIn("object_ids_by_bucket", out.getvalue())

        self.assertEqual(target.read_text(encoding="utf-8"), "keep")

    def test_timestamp_details_swap_race_preserves_pre_exchange_target(self):
        variants = (
            "temp_symlink",
            "temp_regular",
            "target_symlink",
            "target_directory",
            "target_fifo",
            "target_regular",
            "target_absent",
        )
        original_target_stat = cli._timestamp_details_target_stat

        for variant in variants:
            with self.subTest(variant=variant):
                case_dir = Path(self._tmp.name) / f"existing-{variant}"
                case_dir.mkdir()
                target = case_dir / "details.json"
                target.write_bytes(b"old\n")
                victim = case_dir / "victim.txt"
                victim.write_bytes(b"victim\n")
                calls = 0

                def inject_after_final_stat(parent_fd, name):
                    nonlocal calls
                    result = original_target_stat(parent_fd, name)
                    calls += 1
                    if calls != 2:
                        return result
                    temporary = next(
                        entry
                        for entry in os.listdir(parent_fd)
                        if entry.startswith(".details.json.")
                        and entry.endswith(".tmp")
                    )
                    entry = temporary if variant.startswith("temp_") else name
                    os.unlink(entry, dir_fd=parent_fd)
                    if variant == "target_absent":
                        return result
                    if variant.endswith("symlink"):
                        os.symlink(str(victim), entry, dir_fd=parent_fd)
                    elif variant.endswith("directory"):
                        os.mkdir(entry, dir_fd=parent_fd)
                    elif variant.endswith("fifo"):
                        os.mkfifo(entry, dir_fd=parent_fd)
                    else:
                        descriptor = os.open(
                            entry,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                            0o600,
                            dir_fd=parent_fd,
                        )
                        try:
                            os.write(descriptor, b"injected\n")
                        finally:
                            os.close(descriptor)
                    return result

                with mock.patch.object(
                    cli,
                    "_timestamp_details_target_stat",
                    side_effect=inject_after_final_stat,
                ):
                    with self.assertRaises((OSError, ValueError)):
                        cli._atomic_write_timestamp_details(target, b"new\n")

                self.assertEqual(victim.read_bytes(), b"victim\n")
                self.assertFalse(
                    any(
                        path.name.endswith(
                            (".guard", ".tmp", ".cleanup", ".recovery")
                        )
                        for path in case_dir.iterdir()
                    )
                )
                if variant.startswith("temp_"):
                    self.assertEqual(target.read_bytes(), b"old\n")
                elif variant == "target_symlink":
                    self.assertTrue(target.is_symlink())
                    self.assertEqual(target.resolve(), victim.resolve())
                elif variant == "target_directory":
                    self.assertTrue(target.is_dir())
                elif variant == "target_fifo":
                    self.assertTrue(stat.S_ISFIFO(target.lstat().st_mode))
                elif variant == "target_regular":
                    self.assertEqual(target.read_bytes(), b"injected\n")
                else:
                    self.assertFalse(target.exists())
                    self.assertFalse(target.is_symlink())

    def test_timestamp_details_absent_race_preserves_concurrent_target(self):
        variants = (
            "temp_symlink",
            "temp_regular",
            "target_symlink",
            "target_directory",
            "target_fifo",
            "target_regular",
        )
        original_target_stat = cli._timestamp_details_target_stat

        for variant in variants:
            with self.subTest(variant=variant):
                case_dir = Path(self._tmp.name) / f"absent-{variant}"
                case_dir.mkdir()
                target = case_dir / "details.json"
                victim = case_dir / "victim.txt"
                victim.write_bytes(b"victim\n")
                calls = 0

                def inject_after_final_stat(parent_fd, name):
                    nonlocal calls
                    result = original_target_stat(parent_fd, name)
                    calls += 1
                    if calls != 2:
                        return result
                    temporary = next(
                        entry
                        for entry in os.listdir(parent_fd)
                        if entry.startswith(".details.json.")
                        and entry.endswith(".tmp")
                    )
                    entry = temporary if variant.startswith("temp_") else name
                    if variant.startswith("temp_"):
                        os.unlink(entry, dir_fd=parent_fd)
                    if variant.endswith("symlink"):
                        os.symlink(str(victim), entry, dir_fd=parent_fd)
                    elif variant.endswith("directory"):
                        os.mkdir(entry, dir_fd=parent_fd)
                    elif variant.endswith("fifo"):
                        os.mkfifo(entry, dir_fd=parent_fd)
                    else:
                        descriptor = os.open(
                            entry,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                            0o600,
                            dir_fd=parent_fd,
                        )
                        try:
                            os.write(descriptor, b"injected\n")
                        finally:
                            os.close(descriptor)
                    return result

                with mock.patch.object(
                    cli,
                    "_timestamp_details_target_stat",
                    side_effect=inject_after_final_stat,
                ):
                    with self.assertRaises((OSError, ValueError)):
                        cli._atomic_write_timestamp_details(target, b"new\n")

                self.assertEqual(victim.read_bytes(), b"victim\n")
                self.assertFalse(
                    any(
                        path.name.endswith(
                            (".guard", ".tmp", ".cleanup", ".recovery")
                        )
                        for path in case_dir.iterdir()
                    )
                )
                if variant.startswith("temp_"):
                    self.assertFalse(target.exists())
                    self.assertFalse(target.is_symlink())
                elif variant == "target_symlink":
                    self.assertTrue(target.is_symlink())
                    self.assertEqual(target.resolve(), victim.resolve())
                elif variant == "target_directory":
                    self.assertTrue(target.is_dir())
                elif variant == "target_fifo":
                    self.assertTrue(stat.S_ISFIFO(target.lstat().st_mode))
                else:
                    self.assertEqual(target.read_bytes(), b"injected\n")

    def test_timestamp_details_link_cleanup_preserves_later_winner(self):
        case_dir = Path(self._tmp.name) / "link-later-winner"
        case_dir.mkdir()
        target = case_dir / "details.json"
        real_link = os.link
        real_cleanup = cli._remove_linked_target_if_unchanged

        def link_then_substitute_temp(
            source,
            destination,
            *,
            src_dir_fd=None,
            dst_dir_fd=None,
            follow_symlinks=True,
        ):
            result = real_link(
                source,
                destination,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
                follow_symlinks=follow_symlinks,
            )
            if destination == target.name and str(source).endswith(".tmp"):
                os.unlink(source, dir_fd=src_dir_fd)
                descriptor = os.open(
                    source,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=src_dir_fd,
                )
                try:
                    os.write(descriptor, b"substituted\n")
                finally:
                    os.close(descriptor)
            return result

        def publish_winner_before_cleanup(
            parent_fd,
            *,
            target_name,
            linked_stat,
        ):
            os.unlink(target_name, dir_fd=parent_fd)
            descriptor = os.open(
                target_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=parent_fd,
            )
            try:
                os.write(descriptor, b"winner\n")
            finally:
                os.close(descriptor)
            return real_cleanup(
                parent_fd,
                target_name=target_name,
                linked_stat=linked_stat,
            )

        with mock.patch.object(os, "link", side_effect=link_then_substitute_temp), \
             mock.patch.object(
                 cli,
                 "_remove_linked_target_if_unchanged",
                 side_effect=publish_winner_before_cleanup,
             ):
            with self.assertRaises((OSError, ValueError)):
                cli._atomic_write_timestamp_details(target, b"loser\n")

        self.assertEqual(target.read_bytes(), b"winner\n")
        self.assertEqual(
            sorted(path.name for path in case_dir.iterdir()),
            ["details.json"],
        )

    def test_timestamp_details_cleanup_capture_preserves_post_compare_winner(self):
        case_dir = Path(self._tmp.name) / "cleanup-post-compare-winner"
        case_dir.mkdir()
        target = case_dir / "details.json"
        target.write_bytes(b"linked-by-loser\n")
        linked_stat = target.lstat()
        parent_fd = os.open(
            case_dir,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        real_same_inode = cli._same_inode
        comparisons = 0

        def publish_winner_after_ownership_compare(left, right):
            nonlocal comparisons
            result = real_same_inode(left, right)
            comparisons += 1
            if comparisons == 2:
                os.unlink(target.name, dir_fd=parent_fd)
                descriptor = os.open(
                    target.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=parent_fd,
                )
                try:
                    os.write(descriptor, b"winner\n")
                finally:
                    os.close(descriptor)
            return result

        try:
            with mock.patch.object(
                cli,
                "_same_inode",
                side_effect=publish_winner_after_ownership_compare,
            ):
                cli._remove_linked_target_if_unchanged(
                    parent_fd,
                    target_name=target.name,
                    linked_stat=linked_stat,
                )
        finally:
            os.close(parent_fd)

        self.assertEqual(target.read_bytes(), b"winner\n")
        self.assertEqual(
            sorted(path.name for path in case_dir.iterdir()),
            ["details.json"],
        )

    def test_timestamp_details_cleanup_retains_recovery_on_continuous_race(self):
        case_dir = Path(self._tmp.name) / "cleanup-continuous-race"
        case_dir.mkdir()
        target = case_dir / "details.json"
        real_link = os.link
        real_cleanup = cli._remove_linked_target_if_unchanged
        real_no_replace = cli._rename_directory_entry_no_replace

        def link_then_substitute_temp(
            source,
            destination,
            *,
            src_dir_fd=None,
            dst_dir_fd=None,
            follow_symlinks=True,
        ):
            result = real_link(
                source,
                destination,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
                follow_symlinks=follow_symlinks,
            )
            if destination == target.name and str(source).endswith(".tmp"):
                os.unlink(source, dir_fd=src_dir_fd)
                descriptor = os.open(
                    source,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=src_dir_fd,
                )
                try:
                    os.write(descriptor, b"substituted\n")
                finally:
                    os.close(descriptor)
            return result

        def cleanup_under_continuous_race(
            parent_fd,
            *,
            target_name,
            linked_stat,
        ):
            real_same_inode = cli._same_inode
            comparisons = 0
            moves = 0

            def publish_winner_after_ownership_compare(left, right):
                nonlocal comparisons
                result = real_same_inode(left, right)
                comparisons += 1
                if comparisons == 2:
                    os.unlink(target_name, dir_fd=parent_fd)
                    descriptor = os.open(
                        target_name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=parent_fd,
                    )
                    try:
                        os.write(descriptor, b"winner\n")
                    finally:
                        os.close(descriptor)
                return result

            def publish_later_target_after_capture(
                parent,
                source,
                destination,
            ):
                nonlocal moves
                moves += 1
                result = real_no_replace(parent, source, destination)
                if moves == 1:
                    descriptor = os.open(
                        target_name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=parent_fd,
                    )
                    try:
                        os.write(descriptor, b"later\n")
                    finally:
                        os.close(descriptor)
                return result

            with mock.patch.object(
                cli,
                "_same_inode",
                side_effect=publish_winner_after_ownership_compare,
            ), mock.patch.object(
                cli,
                "_rename_directory_entry_no_replace",
                side_effect=publish_later_target_after_capture,
            ):
                return real_cleanup(
                    parent_fd,
                    target_name=target_name,
                    linked_stat=linked_stat,
                )

        with mock.patch.object(
            os,
            "link",
            side_effect=link_then_substitute_temp,
        ), mock.patch.object(
            cli,
            "_remove_linked_target_if_unchanged",
            side_effect=cleanup_under_continuous_race,
        ):
            with self.assertRaisesRegex(
                OSError,
                "captured winner retained at .*\\.recovery",
            ) as raised:
                cli._atomic_write_timestamp_details(target, b"loser\n")

        self.assertEqual(target.read_bytes(), b"later\n")
        recovery_paths = list(case_dir.glob(".*.recovery"))
        self.assertEqual(len(recovery_paths), 1)
        self.assertEqual(recovery_paths[0].read_bytes(), b"winner\n")
        self.assertEqual(raised.exception.filename, recovery_paths[0].name)
        self.assertEqual(
            sorted(path.name for path in case_dir.iterdir()),
            sorted(["details.json", recovery_paths[0].name]),
        )

    def test_audit_succeeds_when_stale_and_exact_quote_checks_pass(self):
        from tests.test_stale_check import code_locator
        loc = code_locator("code.quoted", path="a/X.cpp", commit_sha="SHA1")
        loc["verified_quote"] = "void sym() {}"
        BrainStore.save_object(self.brain, loc)
        stale = {"target_head": "TARGET", "candidates": [], "locator_group": [],
                 "unmerged_anchors": [], "coverage": {"covered_mappings": [],
                                                        "uncovered_mappings": []}}
        out = io.StringIO()
        with mock.patch("project_brain.audit.make_git_runner", return_value=object()), \
             mock.patch("project_brain.audit.stale_check", return_value=stale), \
             mock.patch("project_brain.audit.make_git_blob_reader",
                        return_value=lambda _commit, _path: b"void sym() {}"), \
             mock.patch("sys.argv", ["cli", "audit", "--brain-root", str(self.brain), "--no-fetch"]), \
             redirect_stdout(out):
            rc = cli.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["stale_status"]["ok"])
        self.assertEqual(payload["code_quotes"],
                         {"ok": True, "checked": 1, "skipped": 0, "failures": []})

    def test_audit_defaults_to_read_only_and_runs_full_git_checks(self):
        from tests.test_stale_check import code_locator

        repo_root = self.brain.parent
        source = repo_root / "a" / "X.cpp"
        source.parent.mkdir()
        source.write_text("void sym() {}\n", encoding="utf-8")
        commit = _commit_git_fixture(repo_root)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "update-ref",
                "refs/remotes/origin/develop",
                commit,
            ],
            check=True,
        )
        loc = code_locator("code.quoted", path="a/X.cpp", commit_sha=commit)
        loc["verified_quote"] = "void sym() {}"
        BrainStore.save_object(self.brain, loc)

        stale_set = self.brain / ".brain-local" / "stale-set.json"
        stale_set.parent.mkdir(parents=True)
        bound_bytes = b'{"computed_at":"bound-task18-cache"}\n'
        stale_set.write_bytes(bound_bytes)

        out = io.StringIO()
        with mock.patch(
            "sys.argv",
            [
                "cli",
                "audit",
                "--brain-root",
                str(self.brain),
                "--repo-root",
                str(repo_root),
            ],
        ), redirect_stdout(out):
            rc = cli.main()

        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertIsNotNone(payload["stale"])
        self.assertEqual(
            payload["stale_status"],
            {"ok": True, "skipped": False},
        )
        self.assertEqual(
            payload["code_quotes"],
            {"ok": True, "checked": 1, "skipped": 0, "failures": []},
        )
        self.assertEqual(payload["locators"][0]["code_quote"], "verified")
        self.assertIsNone(payload["cache_written"])
        self.assertEqual(stale_set.read_bytes(), bound_bytes)

    def test_audit_fetch_and_stale_cache_updates_require_positive_flags(self):
        report = {"ok": True}
        out = io.StringIO()
        with mock.patch(
            "project_brain.audit.run_audit",
            return_value=report,
        ) as run_audit, redirect_stdout(out):
            rc = cli._run_audit([
                "--brain-root",
                str(self.brain),
                "--fetch",
                "--write-stale-cache",
            ])

        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.getvalue()), report)
        self.assertTrue(run_audit.call_args.kwargs["fetch"])
        self.assertTrue(run_audit.call_args.kwargs["write_stale_cache"])

    def test_audit_fails_closed_on_global_git_error(self):
        from project_brain.stale_check import GitError
        out = io.StringIO()
        with mock.patch("project_brain.audit.make_git_runner", return_value=object()), \
             mock.patch("project_brain.audit.stale_check", side_effect=GitError("fetch failed")), \
             mock.patch("sys.argv", ["cli", "audit", "--brain-root", str(self.brain), "--no-fetch"]), \
             redirect_stdout(out):
            rc = cli.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["stale_status"]["ok"])
        self.assertEqual(payload["stale"]["error"], "fetch failed")

    def test_audit_serializes_git_process_start_failure(self):
        out = io.StringIO()
        with mock.patch("project_brain.stale_check.subprocess.run",
                        side_effect=FileNotFoundError("git executable missing")), \
             mock.patch("sys.argv", ["cli", "audit", "--brain-root", str(self.brain), "--no-fetch"]), \
             redirect_stdout(out), redirect_stderr(io.StringIO()):
            rc = cli.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["stale_status"]["ok"])
        self.assertIn("could not start", payload["stale"]["error"])

    def test_audit_fails_closed_on_unverifiable_anchor(self):
        stale = {"target_head": "TARGET", "candidates": [], "locator_group": [],
                 "unmerged_anchors": [{"locator_id": "code.neutral.unknown",
                                        "path": "a/X.cpp",
                                        "from_commit": "MISSING", "reason": "anchor_unverifiable",
                                        "blocking_affected_mapping_ids": [],
                                        "nonblocking_affected_mapping_ids": []}],
                 "coverage": {"covered_mappings": [], "uncovered_mappings": []}}
        out = io.StringIO()
        with mock.patch("project_brain.audit.make_git_runner", return_value=object()), \
             mock.patch("project_brain.audit.stale_check", return_value=stale), \
             mock.patch("sys.argv", ["cli", "audit", "--brain-root", str(self.brain), "--no-fetch"]), \
             redirect_stdout(out):
            rc = cli.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["stale_status"]["ok"])

    def test_audit_keeps_not_ancestor_as_successful_advisory(self):
        stale = {"target_head": "TARGET", "candidates": [], "locator_group": [],
                 "unmerged_anchors": [{"locator_id": "code.neutral.work",
                                        "path": "a/X.cpp",
                                        "from_commit": "WORK", "reason": "not_ancestor",
                                        "blocking_affected_mapping_ids": [],
                                        "nonblocking_affected_mapping_ids": []}],
                 "coverage": {"covered_mappings": [], "uncovered_mappings": []}}
        out = io.StringIO()
        with mock.patch("project_brain.audit.make_git_runner", return_value=object()), \
             mock.patch("project_brain.audit.stale_check", return_value=stale), \
             mock.patch("sys.argv", ["cli", "audit", "--brain-root", str(self.brain), "--no-fetch"]), \
             redirect_stdout(out):
            rc = cli.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["stale_status"]["ok"])

    def test_audit_fails_when_verified_quote_is_missing_from_blob(self):
        from tests.test_stale_check import code_locator
        loc = code_locator("code.quoted", path="a/X.cpp", commit_sha="SHA1")
        loc["verified_quote"] = "void sym() {}"
        BrainStore.save_object(self.brain, loc)
        stale = {"target_head": "TARGET", "candidates": [], "locator_group": [],
                 "unmerged_anchors": [], "coverage": {"covered_mappings": [],
                                                        "uncovered_mappings": []}}
        out = io.StringIO()
        with mock.patch("project_brain.audit.make_git_runner", return_value=object()), \
             mock.patch("project_brain.audit.stale_check", return_value=stale), \
             mock.patch("project_brain.audit.make_git_blob_reader",
                        return_value=lambda _commit, _path: b"void other() {}"), \
             mock.patch("sys.argv", ["cli", "audit", "--brain-root", str(self.brain), "--no-fetch"]), \
             redirect_stdout(out):
            rc = cli.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["locators"][0]["code_quote"], "mismatch")
        self.assertEqual(payload["code_quotes"]["failures"], [
            {"locator_id": "code.x.quoted", "reason": "mismatch"},
        ])

    def test_audit_no_stale_skips_both_git_dependent_checks(self):
        from tests.test_stale_check import code_locator
        loc = code_locator("code.quoted", path="a/X.cpp", commit_sha="SHA1")
        loc["verified_quote"] = "void sym() {}"
        BrainStore.save_object(self.brain, loc)
        out = io.StringIO()
        with mock.patch("project_brain.audit.make_git_blob_reader") as blob_reader, \
             mock.patch("sys.argv", ["cli", "audit", "--brain-root", str(self.brain), "--no-stale"]), \
             redirect_stdout(out):
            rc = cli.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["stale"])
        self.assertTrue(payload["stale_status"]["skipped"])
        self.assertTrue(payload["code_quotes"]["check_skipped"])
        self.assertFalse(payload["code_quotes"]["ok"])
        self.assertEqual(payload["locators"][0]["stale"], "unverifiable")
        self.assertEqual(payload["locators"][0]["code_quote"], "unverifiable")
        self.assertEqual(
            payload["locators"][0]["symbol_relation"],
            "unverifiable",
        )
        blob_reader.assert_not_called()

    def test_audit_unknown_id_grammar_returns_rc1(self):
        from tests.test_stale_check import code_locator

        loc = code_locator("code.bad", path="a/X.cpp", commit_sha="SHA1")
        loc["id"] = "mystery.x.bad"
        path = (
            self.brain
            / BrainStore._KIND_DIR["CodeLocator"]
            / "mystery.x.bad.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(BrainStore.object_bytes(loc))

        out = io.StringIO()
        with mock.patch(
            "sys.argv",
            ["cli", "audit", "--brain-root", str(self.brain), "--no-stale"],
        ), redirect_stdout(out):
            rc = cli.main()
        payload = json.loads(out.getvalue())

        self.assertEqual(rc, 1)
        self.assertEqual(payload["locators"][0]["id_format"], "unknown_grammar")

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
                (target / ".agents" / "skills" / "demo-brain-query" / "SKILL.md").exists()
            )

    def test_install_retired_conflict_returns_json_error_without_traceback(self):
        from project_brain.installer import MANIFEST_FILENAME, install

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            install(target, project="demo")
            rel_key = ".agents/skills/demo-brain-query/references/retired.md"
            retired = target / rel_key
            retired.parent.mkdir(parents=True, exist_ok=True)
            retired.write_text("managed\n", encoding="utf-8")
            manifest_path = target / MANIFEST_FILENAME
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_data["files"][rel_key] = hashlib.sha256(b"managed\n").hexdigest()
            manifest_path.write_text(
                json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            retired.write_text("사용자 수정\n", encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            argv = ["install", "--target", td, "--project", "demo", "--force"]

            with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(stdout), redirect_stderr(stderr):
                rc = cli.main()

            self.assertNotEqual(rc, 0)
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            self.assertIn("retired.md", payload["error"])
            self.assertIn("사용자 수정", payload["error"])
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_install_migration_destination_conflict_returns_json_error_before_write(self):
        import project_brain.installer as inst
        from project_brain.installer import MANIFEST_FILENAME, install

        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            templates = target / "templates"
            old_source = templates / "query" / "references" / "old.md"
            old_source.parent.mkdir(parents=True)
            old_source.write_text("managed old\n", encoding="utf-8")
            original_dir, original_skills = inst._TEMPLATES_DIR, inst._SKILLS
            inst._TEMPLATES_DIR, inst._SKILLS = templates, {"query": "brain-query"}
            try:
                install(target, project="demo")
                old_installed = (target / ".agents" / "skills" / "demo-brain-query" /
                                 "references" / "old.md")
                new_installed = old_installed.with_name("new.md")
                old_source.unlink()
                old_source.with_name("new.md").write_text("managed new\n", encoding="utf-8")
                new_installed.write_text("user destination\n", encoding="utf-8")
                config_path = target / ".project-brain.json"
                config = json.loads(config_path.read_text(encoding="utf-8"))
                config.pop("repo")
                config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
                config_before = config_path.read_bytes()
                manifest_path = target / MANIFEST_FILENAME
                manifest_before = manifest_path.read_bytes()
                stdout, stderr = io.StringIO(), io.StringIO()
                argv = ["install", "--target", td, "--project", "demo",
                        "--repo", "would-have-been-backfilled"]

                with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(stdout), \
                     redirect_stderr(stderr):
                    rc = cli.main()

                self.assertNotEqual(rc, 0)
                payload = json.loads(stdout.getvalue())
                self.assertFalse(payload["ok"])
                self.assertIn("new.md", payload["error"])
                self.assertIn("manifest 밖", payload["error"])
                self.assertEqual(old_installed.read_text(encoding="utf-8"), "managed old\n")
                self.assertEqual(new_installed.read_text(encoding="utf-8"), "user destination\n")
                self.assertEqual(config_path.read_bytes(), config_before)
                self.assertEqual(manifest_path.read_bytes(), manifest_before)
                self.assertNotIn("Traceback", stderr.getvalue())
            finally:
                inst._TEMPLATES_DIR, inst._SKILLS = original_dir, original_skills

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
        rc, output = self._run_cli_result(argv)
        self.assertEqual(rc, 0)
        return output

    def _run_cli_result(self, argv):
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        return rc, out.getvalue()

    def _run_session_failure(self, argv, *, resolve_error=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(mock.patch("sys.argv", ["cli"] + argv))
            if resolve_error is not None:
                stack.enter_context(mock.patch.object(
                    cli, "resolve_brain_root", side_effect=resolve_error,
                ))
            with redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    rc = cli.main()
                except SystemExit as exc:
                    rc = exc.code
        return rc, stdout.getvalue(), stderr.getvalue()

    def test_session_argument_and_configuration_failures_use_stdout_json(self):
        cases = (
            (
                ["session", "complete", "abc"],
                None,
                "session_argument_invalid",
            ),
            (
                ["session", "list", "--not-a-session-option"],
                None,
                "session_argument_invalid",
            ),
            (
                ["session", "list"],
                cli.ConfigError("brain root unavailable"),
                "session_configuration_invalid",
            ),
        )
        for argv, resolve_error, error_code in cases:
            with self.subTest(argv=argv):
                rc, stdout, stderr = self._run_session_failure(
                    argv, resolve_error=resolve_error,
                )

                self.assertEqual(rc, 1)
                self.assertEqual(stderr, "")
                payload = json.loads(stdout)
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["error_code"], error_code)
                self.assertTrue(payload["error"])

    def test_session_config_loader_failures_use_stdout_json(self):
        cases = (
            ("config_absent", None, None),
            ("relative_brain_root", None, "relative-brain"),
            ("malformed_json", b"{", None),
            ("top_level_list", b"[]", None),
            ("top_level_scalar", b"1", None),
            ("invalid_utf8", b"\xff", None),
            ("brain_root_list", b'{"brain_root": []}', None),
            ("read_failure", b'{"brain_root": "brain"}', OSError("config unreadable")),
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, config_bytes, third in cases:
                with self.subTest(name=name):
                    project = root / name
                    project.mkdir()
                    config_path = project / ".project-brain.json"
                    argv = ["session", "list"]
                    read_error = None
                    if config_bytes is not None:
                        config_path.write_bytes(config_bytes)
                    if isinstance(third, str):
                        argv.extend(["--brain-root", third])
                    elif isinstance(third, OSError):
                        read_error = third

                    with ExitStack() as stack:
                        stack.enter_context(mock.patch(
                            "project_brain.config.Path.cwd", return_value=project,
                        ))
                        if read_error is not None:
                            stack.enter_context(mock.patch(
                                "project_brain.config.Path.read_text",
                                side_effect=read_error,
                            ))
                        rc, stdout, stderr = self._run_session_failure(argv)

                    self.assertEqual(rc, 1)
                    self.assertEqual(stderr, "")
                    self.assertNotIn("Traceback", stdout)
                    payload = json.loads(stdout)
                    self.assertEqual(set(payload), {"ok", "error_code", "error"})
                    self.assertFalse(payload["ok"])
                    self.assertEqual(payload["error_code"], "session_configuration_invalid")
                    self.assertTrue(payload["error"])

    def test_session_mark_processed_without_uuid_is_a_json_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            brain_root = Path(td) / "brain"
            rc, stdout, stderr = self._run_session_failure([
                "session", "mark-processed", "--brain-root", str(brain_root),
            ])

            self.assertEqual(rc, 1)
            self.assertEqual(stderr, "")
            payload = json.loads(stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error_code"], "session_completion_report_required")
            self.assertIn("session complete", payload["error"])
            self.assertFalse((brain_root / ".brain-local" / "sessions").exists())

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
            artifacts = _completion_artifacts(Path(td) / "artifacts", uuid="abc")
            self._run_cli([
                "session", "complete", "abc",
                "--transcript", str(artifacts["transcript"]),
                "--manifest", str(artifacts["manifest"]),
                "--report", str(artifacts["report"]),
                "--brain-root", str(artifacts["brain_root"]),
            ])
            out = self._run_cli(["session", "list", "--transcript-root", str(root),
                                 "--brain-root", str(artifacts["brain_root"]), "--unprocessed"])
            payload = json.loads(out)
            self.assertEqual([s["uuid"] for s in payload["sessions"]], ["def"])

    def test_session_complete_writes_v2_marker_and_keeps_same_bytes_on_retry(self):
        with tempfile.TemporaryDirectory() as td:
            artifacts = _completion_artifacts(Path(td))
            argv = [
                "session", "complete", "abc",
                "--transcript", str(artifacts["transcript"]),
                "--manifest", str(artifacts["manifest"]),
                "--report", str(artifacts["report"]),
                "--brain-root", str(artifacts["brain_root"]),
            ]

            first = json.loads(self._run_cli(argv))
            marker = artifacts["brain_root"] / ".brain-local" / "sessions" / "abc.json"
            first_bytes = marker.read_bytes()
            second = json.loads(self._run_cli(argv))

            self.assertTrue(first["ok"])
            self.assertEqual(first["state"], "processed")
            self.assertEqual(second["receipt_ids"], first["receipt_ids"])
            self.assertEqual(marker.read_bytes(), first_bytes)

    def test_session_complete_preserves_legacy_marker_and_mark_processed_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            artifacts = _completion_artifacts(Path(td))
            marker = artifacts["brain_root"] / ".brain-local" / "sessions" / "abc.json"
            marker.parent.mkdir(parents=True, exist_ok=True)
            legacy_bytes = b'{"uuid":"abc","processed_at":"old","note":"legacy"}\n'
            marker.write_bytes(legacy_bytes)
            complete_argv = [
                "session", "complete", "abc",
                "--transcript", str(artifacts["transcript"]),
                "--manifest", str(artifacts["manifest"]),
                "--report", str(artifacts["report"]),
                "--brain-root", str(artifacts["brain_root"]),
            ]

            rc, output = self._run_cli_result(complete_argv)
            payload = json.loads(output)

            self.assertEqual(rc, 1)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error_code"], "legacy_unverified")
            self.assertEqual(marker.read_bytes(), legacy_bytes)

            fresh_brain = Path(td) / "fresh-brain"
            rc, output = self._run_cli_result([
                "session", "mark-processed", "abc",
                "--brain-root", str(fresh_brain),
            ])
            payload = json.loads(output)
            self.assertEqual(rc, 1)
            self.assertEqual(payload["error_code"], "session_completion_report_required")
            self.assertFalse((fresh_brain / ".brain-local" / "sessions" / "abc.json").exists())


class RunBuildTest(unittest.TestCase):
    @staticmethod
    def _write_coverage(path, *objects):
        path.write_text(json.dumps({
            "version": 1,
            "mode": "direct",
            "objects": list(objects),
        }), encoding="utf-8")

    def test_build_writes_objects_file(self):
        with tempfile.TemporaryDirectory() as td:
            notes_path = Path(td) / "notes.json"
            coverage_path = Path(td) / "coverage.json"
            out_path = Path(td) / "out.json"
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            BrainStore.save_object(brain, _context_object("ctx"))
            # reviewed GlossaryTerm은 evidence_refs가 필수(schema) → source+code_anchor로 닫는다
            notes_path.write_text(json.dumps({
                "context": {"key": "ctx", "commit": "abc", "repo": "demoapp"},
                "sources": [{"id": "manifest.ctx.code", "source_type": "code_search",
                             "title": "코드", "locator": "...", "captured_by": "agent",
                             "captured_at": "2026-06-16T00:00:00Z", "acl": ["team"],
                             "redaction_status": "approved"}],
                "code_anchors": [{"key": "hit-hook", "path": "D.h", "symbol": "S",
                                  "line_start": 1, "line_end": 1, "quote": "q",
                                  "manifest": "manifest.ctx.code"}],
                "glossary": [{"key": "hit", "term": "hit", "definition": "정의",
                              "evidence_refs": ["evref.ctx.hit-hook"]}],
            }), encoding="utf-8")
            self._write_coverage(
                coverage_path,
                {"id": "code.ctx.hit-hook", "kind": "CodeLocator"},
                {"id": "evref.ctx.hit-hook", "kind": "EvidenceRef"},
                {"id": "g.ctx.hit", "kind": "GlossaryTerm"},
                {"id": "manifest.ctx.code", "kind": "EvidenceManifest"},
            )
            rc = _run_build(["--notes", str(notes_path),
                             "--coverage-file", str(coverage_path),
                             "--objects-file", str(out_path),
                             "--brain-root", str(brain)])
            self.assertEqual(rc, 0)
            objs = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertTrue(any(o["id"] == "g.ctx.hit" for o in objs))

    def test_context_now_cannot_override_build_clock(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            notes_path, coverage_path, out_path = _write_complete_build_inputs(root)
            notes = json.loads(notes_path.read_text(encoding="utf-8"))
            notes["context"]["now"] = "2000-01-01T00:00:00+09:00"
            notes_path.write_text(json.dumps(notes), encoding="utf-8")

            out = io.StringIO()
            with redirect_stdout(out):
                rc = cli._run_build([
                    "--notes", str(notes_path),
                    "--coverage-file", str(coverage_path),
                    "--objects-file", str(out_path),
                    "--brain-root", str(root / "brain"),
                ])

            self.assertEqual(rc, 1)
            self.assertEqual(json.loads(out.getvalue())["error_code"], "notes_invalid")
            self.assertFalse(out_path.exists())

    def test_build_errors_return_1_and_no_file(self):
        with tempfile.TemporaryDirectory() as td:
            notes_path = Path(td) / "notes.json"
            coverage_path = Path(td) / "coverage.json"
            out_path = Path(td) / "out.json"
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            notes_path.write_text(json.dumps({"glossary": []}), encoding="utf-8")  # context 없음
            self._write_coverage(
                coverage_path,
                {"id": "ledger.ctx.placeholder", "kind": "EventLedgerRecord"},
            )
            rc = _run_build(["--notes", str(notes_path),
                             "--coverage-file", str(coverage_path),
                             "--objects-file", str(out_path),
                             "--brain-root", str(brain)])
            self.assertEqual(rc, 1)
            self.assertFalse(out_path.exists())

    def test_build_auto_fills_now_kst_when_note_omits_now(self):
        # C4 회귀: 노트 context에 now를 생략하면 엔진이 now_kst()로 created_at/updated_at을
        # 자동 기입한다(cli.py `now = ... or now_kst()`). 폴백이 빠지면 now=None이라
        # created_at이 빈 값/None이 돼 이 단언이 깨진다 — 시점 분산 재발 가드. 신규 코드 0줄.
        with tempfile.TemporaryDirectory() as td:
            notes_path = Path(td) / "notes.json"
            coverage_path = Path(td) / "coverage.json"
            out_path = Path(td) / "out.json"
            brain = Path(td) / "brain"
            (brain / "objects").mkdir(parents=True)
            BrainStore.save_object(brain, _context_object("ctx"))
            notes_path.write_text(json.dumps({
                "context": {"key": "ctx", "commit": "abc", "repo": "demoapp"},  # now 생략
                "sources": [{"id": "manifest.ctx.code", "source_type": "code_search",
                             "title": "코드", "locator": "...", "captured_by": "agent",
                             "captured_at": "2026-06-16T00:00:00Z", "acl": ["team"],
                             "redaction_status": "approved"}],
                "code_anchors": [{"key": "hit-hook", "path": "D.h", "symbol": "S",
                                  "line_start": 1, "line_end": 1, "quote": "q",
                                  "manifest": "manifest.ctx.code"}],
                "glossary": [{"key": "hit", "term": "hit", "definition": "정의",
                              "evidence_refs": ["evref.ctx.hit-hook"]}],
            }), encoding="utf-8")
            self._write_coverage(
                coverage_path,
                {"id": "code.ctx.hit-hook", "kind": "CodeLocator"},
                {"id": "evref.ctx.hit-hook", "kind": "EvidenceRef"},
                {"id": "g.ctx.hit", "kind": "GlossaryTerm"},
                {"id": "manifest.ctx.code", "kind": "EvidenceManifest"},
            )
            rc = _run_build(["--notes", str(notes_path),
                             "--coverage-file", str(coverage_path),
                             "--objects-file", str(out_path),
                             "--brain-root", str(brain)])
            self.assertEqual(rc, 0)
            objs = json.loads(out_path.read_text(encoding="utf-8"))
            term = next(o for o in objs if o["id"] == "g.ctx.hit")
            # KST 표준(+09:00, microsecond 없음)으로 자동 기입, created_at == updated_at.
            self.assertTrue(term["created_at"].endswith("+09:00"), term["created_at"])
            self.assertEqual(term["created_at"], term["updated_at"])


def _write_complete_build_inputs(tmp_path):
    notes_path = tmp_path / "notes.json"
    coverage_path = tmp_path / "coverage.json"
    objects_path = tmp_path / "objects.json"
    notes_path.write_text(json.dumps({
        "context": {
            "key": "ctx", "commit": "abc",
            "repo": "demoapp", "display_name": "컨텍스트", "boundary_summary": "경계",
            "in_scope": [], "out_of_scope": [], "glossary_term_ids": [],
            "claim_status": "reviewed",
        },
        "sources": [{
            "id": "manifest.ctx.code", "source_type": "code_search", "title": "코드",
            "locator": "demoapp@abc", "captured_by": "agent",
            "captured_at": "2026-06-16T00:00:00Z", "acl": ["team"],
            "redaction_status": "approved",
        }],
        "code_anchors": [{
            "key": "anchor-one", "path": "D.h", "symbol": "S", "quote": "q",
            "manifest": "manifest.ctx.code",
        }],
    }), encoding="utf-8")
    coverage_path.write_text(json.dumps({
        "version": 1,
        "mode": "assembled",
        "verify_groups": {"names": [], "empty_reason": "직접 작성한 합성 노트"},
        "context": {"key": "ctx", "mode": "create"},
        "sections": {
            "sources": {"ids": ["manifest.ctx.code"]},
            "glossary": {"keys": [], "empty_reason": "용어 없음"},
            "code_anchors": {"keys": ["anchor-one"]},
            "mappings": {"keys": [], "empty_reason": "매핑 없음"},
            "decisions": {"items": [], "empty_reason": "결정 없음"},
            "refs": {"items": [], "empty_reason": "참조 없음"},
            "updates": {"ids": [], "empty_reason": "갱신 없음"},
            "extra_objects": {"objects": [], "empty_reason": "추가 객체 없음"},
        },
        "expected_objects": [
            {"id": "code.ctx.anchor-one", "kind": "CodeLocator"},
            {"id": "context.ctx", "kind": "DomainContext"},
            {"id": "evref.ctx.anchor-one", "kind": "EvidenceRef"},
            {"id": "manifest.ctx.code", "kind": "EvidenceManifest"},
        ],
    }), encoding="utf-8")
    return notes_path, coverage_path, objects_path


@pytest.mark.parametrize("mutation", ["missing", "unexpected"])
def test_build_rejects_missing_or_unexpected_object(
    mutation, monkeypatch, tmp_path, capsys
):
    notes_path, coverage_path, objects_path = _write_complete_build_inputs(tmp_path)
    real_build = assembly.build

    def changed_build(notes, store, now):
        result = real_build(notes, store, now)
        if mutation == "missing":
            result["objects"] = [
                obj for obj in result["objects"] if obj["kind"] != "CodeLocator"
            ]
        else:
            result["objects"].append({
                "id": "ledger.ctx.unexpected", "kind": "EventLedgerRecord"
            })
        return result

    monkeypatch.setattr(assembly, "build", changed_build)
    assert cli._run_build([
        "--notes", str(notes_path),
        "--coverage-file", str(coverage_path),
        "--objects-file", str(objects_path),
        "--brain-root", str(tmp_path / "brain"),
    ]) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "coverage_build_mismatch"
    assert not objects_path.exists()


def test_build_cli_requires_coverage_file():
    with pytest.raises(SystemExit):
        cli._run_build(["--notes", "notes.json", "--objects-file", "objects.json"])


def test_build_reads_invalid_coverage_before_missing_notes(tmp_path, capsys):
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text("{", encoding="utf-8")

    assert cli._run_build([
        "--notes", str(tmp_path / "missing-notes.json"),
        "--coverage-file", str(coverage_path),
        "--objects-file", str(tmp_path / "objects.json"),
        "--brain-root", str(tmp_path / "brain"),
    ]) == 1

    assert json.loads(capsys.readouterr().out)["error_code"] == "coverage_invalid"


def test_build_reads_invalid_coverage_before_store_access(
    tmp_path, capsys, monkeypatch
):
    coverage_path = tmp_path / "coverage.json"
    coverage_path.write_text("{", encoding="utf-8")
    notes_path = tmp_path / "notes.json"
    notes_path.write_text("{}", encoding="utf-8")

    def unexpected_store_access(cls, brain_root):
        raise AssertionError(f"store accessed before coverage: {brain_root}")

    monkeypatch.setattr(BrainStore, "load", classmethod(unexpected_store_access))

    assert cli._run_build([
        "--notes", str(notes_path),
        "--coverage-file", str(coverage_path),
        "--objects-file", str(tmp_path / "objects.json"),
        "--brain-root", str(tmp_path / "brain"),
    ]) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "coverage_invalid"


def test_build_report_contains_exact_coverage_binding_fields(tmp_path, capsys):
    notes_path, coverage_path, objects_path = _write_complete_build_inputs(tmp_path)

    assert cli._run_build([
        "--notes", str(notes_path),
        "--coverage-file", str(coverage_path),
        "--objects-file", str(objects_path),
        "--brain-root", str(tmp_path / "brain"),
    ]) == 0

    report = json.loads(capsys.readouterr().out)
    identities = [
        {"id": "code.ctx.anchor-one", "kind": "CodeLocator"},
        {"id": "context.ctx", "kind": "DomainContext"},
        {"id": "evref.ctx.anchor-one", "kind": "EvidenceRef"},
        {"id": "manifest.ctx.code", "kind": "EvidenceManifest"},
    ]
    assert report["expected_objects"] == identities
    assert report["actual_objects"] == identities
    assert len(report["coverage_sha256"]) == 64
    assert len(report["objects_sha256"]) == 64
    assert report["build_binding"] == {
        "version": 1,
        "coverage_sha256": report["coverage_sha256"],
        "expected_objects": identities,
        "actual_objects": identities,
        "objects_sha256": report["objects_sha256"],
    }


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
            *ENGINE_ARGS,
            *extra,
        ]

    def _run(self, *extra):
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + self._argv(*extra)), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_write_ingests_projection_readable_from_store(self):
        # (a) source 다 존재 시 --write로 ingest 경유 저장 → store에서 읽힘.
        original_apply = MutationService.apply
        with mock.patch.object(
            BrainStore,
            "save_object",
            side_effect=AssertionError("direct save_object call"),
        ), mock.patch.object(
            MutationService,
            "apply",
            autospec=True,
            side_effect=original_apply,
        ) as apply:
            rc, payload = self._run("--write")
        self.assertEqual(rc, 0, payload)
        self.assertEqual(apply.call_count, 1)
        self.assertIs(
            apply.call_args.kwargs["request"].operation,
            MutationOperation.PROJECTION,
        )
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
            "--source-object-ids", "mapping.neutral.race-end",
            "mapping.neutral.does-not-exist",
            "--title", "결과 팝업 순위 표시 착수 브리핑",
            "--payload-file", str(self.payload_file),
            "--generated-by", "demo-brain-query",
            "--write",
            *ENGINE_ARGS,
        ]
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        payload = json.loads(out.getvalue())
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("mapping.neutral.does-not-exist", payload["error"])
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
            generated_by="t")
        proj["created_at"] = self.GEN_AT
        proj["updated_at"] = self.GEN_AT
        proj["generated_at"] = self.GEN_AT
        self.pid = proj["id"]
        # 일부러 stale: 저장 hash를 틀린 값으로(C2 이전 옛 해시·수작업 오류 모사).
        proj["source_content_hash"] = "stale-wrong-hash"
        BrainStore.save_object(self.root, proj)

    def tearDown(self):
        self._tmp.cleanup()

    def _run_refresh(self, *extra):
        out = io.StringIO()
        argv = ["projection", "refresh", "--brain-root", str(self.root), *extra]
        argv.extend(ENGINE_ARGS)
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

    def test_refresh_routes_once_as_projection_repair_without_direct_save(self):
        from project_brain.mutation import MutationOperation, MutationService

        original_apply = MutationService.apply
        with mock.patch.object(
            BrainStore,
            "save_object",
            side_effect=AssertionError("direct save_object call"),
        ), mock.patch.object(
            MutationService,
            "apply",
            autospec=True,
            side_effect=original_apply,
        ) as apply:
            rc, payload = self._run_refresh()

        self.assertEqual(rc, 0, payload)
        self.assertEqual(apply.call_count, 1)
        request = apply.call_args.kwargs["request"]
        self.assertIs(request.operation, MutationOperation.PROJECTION_REPAIR)
        self.assertEqual(
            set(request.preconditions),
            {self.pid},
        )

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
            "source_object_ids": ["mapping.neutral.does-not-exist"],
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
        self.assertIn("draft", text)
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
        rc, payload = self._show("mapping.neutral.x")
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["object"]["id"], "mapping.neutral.x")
        self.assertTrue(payload["display_only"])
        self.assertTrue(payload["object"]["display_only"])
        by_nb = {n["object_id"]: n for n in payload["neighbors"]}
        # 이웃은 저장소에 실존하는 참조만 — 종류·제목 동반.
        self.assertEqual(by_nb["g.neutral.race"]["kind"], "GlossaryTerm")
        self.assertEqual(by_nb["g.neutral.race"]["title"], "Term: 레이스")
        self.assertTrue(by_nb["g.neutral.race"]["display_only"])
        self.assertEqual(by_nb["code.neutral.x"]["kind"], "CodeLocator")
        # 끊긴 참조(evidence_refs=["evref.neutral.mapping"])·자기참조(id)는 이웃에 안 뜬다.
        self.assertNotIn("evref.neutral.map", by_nb)
        self.assertNotIn("mapping.neutral.x", by_nb)

    def test_show_attaches_stale_advisory_for_stale_mapping(self):
        # Step 2: show 대상이 stale-set에 들면 payload 최상위에 stale_advisory(객체 본문 불변).
        from project_brain.stale_check import write_stale_set
        from tests.test_search import build_store_dir, domain_mapping, glossary_term
        build_store_dir(self.root, [
            glossary_term("g.race", term="레이스"),
            domain_mapping("m.x", meaning="레이스 시작", glossary_term_ids=["g.race"]),
        ])
        write_stale_set(self.root, {
            "target_head": "T", "computed_at": "t",
            "stale_mapping_ids": ["mapping.neutral.x"],
            "detail": {
                "mapping.neutral.x": {
                    "change_types": ["M"], "paths": ["a/X.cpp"]
                }
            }})
        rc, payload = self._show("mapping.neutral.x")
        self.assertEqual(rc, 0)
        self.assertEqual(payload["stale_advisory"]["change_types"], ["M"])
        self.assertNotIn("stale_advisory", payload["object"])  # 객체 본문은 불변

    def test_show_attaches_both_advisory_axes_without_changing_status(self):
        from project_brain.stale_check import write_stale_set
        from tests.test_search import build_store_dir, domain_mapping, glossary_term
        build_store_dir(self.root, [
            glossary_term("g.race", term="레이스"),
            domain_mapping("m.x", meaning="레이스 시작", glossary_term_ids=["g.race"]),
        ])
        write_stale_set(self.root, {
            "target_head": "T", "computed_at": "t",
            "stale_mapping_ids": ["mapping.neutral.x"],
            "detail": {"mapping.neutral.x": {
                               "code_changed": True, "unmerged_anchor": True,
                               "unmerged_reasons": ["not_ancestor"],
                               "locator_ids": [
                                   "code.neutral.changed",
                                   "code.neutral.work",
                               ],
                               "from_commits": ["SHA1", "WORK"], "change_types": ["M"],
                               "paths": ["a/Race.cpp"]}}})
        rc, payload = self._show("mapping.neutral.x")
        self.assertEqual(rc, 0)
        self.assertTrue(payload["stale_advisory"]["code_changed"])
        self.assertTrue(payload["stale_advisory"]["unmerged_anchor"])
        self.assertEqual(payload["object"]["status"], "reviewed")

    def test_show_no_advisory_when_not_stale(self):
        from tests.test_search import build_store_dir, domain_mapping, glossary_term
        build_store_dir(self.root, [
            glossary_term("g.race", term="레이스"),
            domain_mapping("m.x", meaning="레이스 시작", glossary_term_ids=["g.race"]),
        ])
        rc, payload = self._show("mapping.neutral.x")  # 캐시 안 떨굼
        self.assertEqual(rc, 0)
        self.assertNotIn("stale_advisory", payload)

    def test_show_missing_id_errors(self):
        rc, payload = self._show("mapping.neutral.missing")
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("mapping.neutral.missing", payload["error"])

    def test_snapshot_create_verify_restore_subcommands(self):
        project = self.root / "snapshot-project"
        brain = project / "brain"
        engine = self.root / "snapshot-engine"
        snapshots = project / ".snapshots"
        engine.mkdir()
        project.mkdir(exist_ok=True)
        (project / ".project-brain.json").write_text(
            json.dumps({"brain_root": "brain"}),
            encoding="utf-8",
        )
        original = context()
        BrainStore.save_object(brain, original)
        _commit_git_fixture(project)
        _commit_git_fixture(engine)

        create_out = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "snapshot", "create",
            "--brain-root", str(brain.resolve()),
            "--repo-root", str(project.resolve()),
            "--engine-root", str(engine.resolve()),
            "--output-root", str(snapshots.resolve()),
            "--snapshot-id", "cli-snapshot",
        ]), redirect_stdout(create_out):
            self.assertEqual(cli.main(), 0)
        created = json.loads(create_out.getvalue())
        self.assertTrue(created["ok"])
        self.assertEqual(created["restore_scope"], "brain_only")

        verify_out = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "snapshot", "verify",
            "--snapshot-root", created["snapshot_root"],
            "--expected-manifest-sha256", created["manifest_sha256"],
        ]), redirect_stdout(verify_out):
            self.assertEqual(cli.main(), 0)
        self.assertTrue(json.loads(verify_out.getvalue())["ok"])

        changed = dict(original)
        changed["title"] = "changed"
        BrainStore.save_object(brain, changed)
        restore_out = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "snapshot", "restore",
            "--snapshot-root", created["snapshot_root"],
            "--brain-root", str(brain.resolve()),
            "--expected-manifest-sha256", created["manifest_sha256"],
        ]), redirect_stdout(restore_out):
            self.assertEqual(cli.main(), 0)
        self.assertEqual(BrainStore.load(brain).get(original["id"]), original)
        self.assertEqual(
            json.loads(restore_out.getvalue())["restore_scope"],
            "brain_only",
        )

    def test_context_replace_plan_is_read_only_and_apply_requires_exact_sha(self):
        brain = (self.root / "context-brain").resolve()
        input_dir = self.root / "context-inputs"
        input_dir.mkdir()
        old = candidate_term("g.neutral.old", term="이전")
        old_context = context(glossary_term_ids=[old["id"]])
        for obj in (old_context, old):
            BrainStore.save_object(brain, obj)
        new = candidate_term("g.neutral.new", term="새 값")
        desired_context = dict(old_context)
        desired_context["glossary_term_ids"] = [new["id"]]
        desired_file = input_dir / "desired.json"
        moves_file = input_dir / "moves.json"
        manifest_file = input_dir / "context-replace.manifest.json"
        desired_file.write_text(
            json.dumps([desired_context, new], ensure_ascii=False),
            encoding="utf-8",
        )
        moves_file.write_text(
            json.dumps({old["id"]: new["id"]}),
            encoding="utf-8",
        )

        plan_out = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "context-replace", "plan",
            "--brain-root", str(brain),
            "--context-id", old_context["id"],
            "--desired-objects-file", str(desired_file),
            "--expected-moves-file", str(moves_file),
            "--manifest", str(manifest_file),
            *ENGINE_ARGS,
        ]), redirect_stdout(plan_out):
            self.assertEqual(cli.main(), 0)
        planned = json.loads(plan_out.getvalue())
        self.assertTrue(manifest_file.is_file())
        self.assertTrue(BrainStore.load(brain).has(old["id"]))
        self.assertFalse(BrainStore.load(brain).has(new["id"]))

        wrong_out = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "context-replace", "apply",
            "--brain-root", str(brain),
            "--manifest", str(manifest_file),
            "--expected-manifest-sha256", "0" * 64,
            *ENGINE_ARGS,
        ]), redirect_stdout(wrong_out):
            self.assertEqual(cli.main(), 1)
        self.assertTrue(BrainStore.load(brain).has(old["id"]))

        apply_out = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "context-replace", "apply",
            "--brain-root", str(brain),
            "--manifest", str(manifest_file),
            "--expected-manifest-sha256", planned["manifest_sha256"],
            *ENGINE_ARGS,
        ]), redirect_stdout(apply_out):
            self.assertEqual(cli.main(), 0, apply_out.getvalue())
        store = BrainStore.load(brain)
        self.assertFalse(store.has(old["id"]))
        self.assertTrue(store.has(new["id"]))

    def test_id_migration_cli_plan_is_read_only_and_apply_requires_receipts(self):
        from project_brain.snapshot import SnapshotVerification
        from tests.test_mutation import _code_locator, _write_raw

        brain = (self.root / "migration-brain").resolve()
        input_dir = self.root / "migration-inputs"
        input_dir.mkdir()
        old = _code_locator(
            object_id="code.Legacy",
            quote=None,
            title="legacy display",
        )
        _write_raw(brain, old)
        (brain / "eval_scenarios.json").write_text(
            json.dumps({
                "scenarios": [{
                    "id": "s",
                    "query": "q",
                    "expect": {"top5_any": [old["id"]]},
                }],
            }),
            encoding="utf-8",
        )
        renames_file = input_dir / "renames.json"
        manifest_file = input_dir / "id-migration.manifest.json"
        renames_file.write_text(
            json.dumps({old["id"]: "code.neutral.legacy"}),
            encoding="utf-8",
        )
        snapshot_root = input_dir / "snapshot"
        snapshot_receipt = "a" * 64
        repo_head = "b" * 40
        verification = SnapshotVerification(
            ok=True,
            snapshot_id="trusted-migration-snapshot",
            manifest_sha256=snapshot_receipt,
            file_count=1,
            repo_head=repo_head,
            engine_head=ENGINE_ARGS[1],
            corpus_fingerprint=corpus_fingerprint(BrainStore.load(brain)),
        )

        plan_out = io.StringIO()
        with mock.patch(
            "project_brain.migration.verify_snapshot",
            return_value=verification,
        ) as verify_snapshot_call, mock.patch(
            "project_brain.migration.verify_git_root_head",
            side_effect=lambda root, label: (
                repo_head if label == "repo_root" else ENGINE_ARGS[1]
            ),
        ), mock.patch("sys.argv", [
            "cli", "migration", "id", "plan",
            "--brain-root", str(brain),
            "--repo-root", str(self.root.resolve()),
            "--engine-root", str(input_dir.resolve()),
            "--renames-file", str(renames_file),
            "--snapshot-root", str(snapshot_root),
            "--expected-snapshot-manifest-sha256", snapshot_receipt,
            "--manifest", str(manifest_file),
            *ENGINE_ARGS,
        ]), redirect_stdout(plan_out):
            self.assertEqual(cli.main(), 0, plan_out.getvalue())
        planned = json.loads(plan_out.getvalue())
        self.assertEqual(verify_snapshot_call.call_count, 1)
        self.assertTrue(BrainStore.load(brain).has(old["id"]))
        artifact = json.loads(manifest_file.read_bytes())
        self.assertEqual(
            set(artifact["rows"][0]),
            {
                "old_id",
                "new_id",
                "kind",
                "canonical_payload_hash",
                "reference_rewrites",
                "dependent_artifacts",
                "snapshot_id",
            },
        )

        wrong_out = io.StringIO()
        with mock.patch(
            "project_brain.migration.verify_snapshot",
            return_value=verification,
        ), mock.patch(
            "project_brain.migration.verify_git_root_head",
            side_effect=lambda root, label: (
                repo_head if label == "repo_root" else ENGINE_ARGS[1]
            ),
        ), mock.patch("sys.argv", [
            "cli", "migration", "id", "apply",
            "--brain-root", str(brain),
            "--repo-root", str(self.root.resolve()),
            "--engine-root", str(input_dir.resolve()),
            "--snapshot-root", str(snapshot_root),
            "--expected-snapshot-manifest-sha256", snapshot_receipt,
            "--manifest", str(manifest_file),
            "--expected-manifest-sha256", "0" * 64,
            *ENGINE_ARGS,
        ]), redirect_stdout(wrong_out):
            self.assertEqual(cli.main(), 1)
        self.assertTrue(BrainStore.load(brain).has(old["id"]))

        apply_out = io.StringIO()
        with mock.patch(
            "project_brain.migration.verify_snapshot",
            return_value=verification,
        ), mock.patch(
            "project_brain.migration.verify_git_root_head",
            side_effect=lambda root, label: (
                repo_head if label == "repo_root" else ENGINE_ARGS[1]
            ),
        ), mock.patch("sys.argv", [
            "cli", "migration", "id", "apply",
            "--brain-root", str(brain),
            "--repo-root", str(self.root.resolve()),
            "--engine-root", str(input_dir.resolve()),
            "--snapshot-root", str(snapshot_root),
            "--expected-snapshot-manifest-sha256", snapshot_receipt,
            "--manifest", str(manifest_file),
            "--expected-manifest-sha256", planned["manifest_sha256"],
            *ENGINE_ARGS,
        ]), redirect_stdout(apply_out):
            self.assertEqual(cli.main(), 0, apply_out.getvalue())
        store = BrainStore.load(brain)
        self.assertFalse(store.has(old["id"]))
        self.assertTrue(store.has("code.neutral.legacy"))

    def _canonical_cli_fixture(self, name):
        from project_brain.snapshot import (
            SnapshotRequest,
            create_snapshot,
        )
        from tests.test_canonical_repair import _canonical_plan_fixture

        fixture = _canonical_plan_fixture(self.root / name)
        input_dir = self.root / f"{name}-inputs"
        input_dir.mkdir()
        decisions_file = input_dir / "canonicalization-decisions.json"
        classification_file = input_dir / "phase-a-classification.json"
        manifest_file = input_dir / "canonical-repair.manifest.json"
        decisions_file.write_bytes(fixture.ledger_bytes)
        classification_file.write_bytes(fixture.classification_bytes)
        snapshot_result = create_snapshot(SnapshotRequest(
            brain_root=fixture.brain_root,
            repo_root=fixture.repo_root,
            engine_root=fixture.engine_root,
            output_root=(self.root / f"{name}-snapshots").resolve(),
            snapshot_id=f"{name}-before",
        ))
        common_args = [
            "--brain-root", str(fixture.brain_root),
            "--repo-root", str(fixture.repo_root),
            "--engine-root", str(fixture.engine_root),
            "--snapshot-root", str(snapshot_result.snapshot_root),
            "--expected-snapshot-manifest-sha256",
            snapshot_result.manifest_sha256,
            "--decisions-file", str(decisions_file),
            "--expected-decisions-sha256", fixture.ledger.sha256,
            "--classification-file", str(classification_file),
            "--expected-classification-sha256",
            fixture.classification_sha256,
            "--manifest", str(manifest_file),
            "--engine-sha", fixture.engine_sha,
        ]
        return fixture, common_args, manifest_file, snapshot_result

    def test_canonical_repair_cli_plan_is_read_only_and_apply_is_receipt_bound(self):
        fixture, common_args, manifest_file, snapshot_result = (
            self._canonical_cli_fixture("canonical-cli")
        )
        apply_success_keys = {
            "ok",
            "migration_kind",
            "manifest",
            "manifest_sha256",
            "transaction_id",
            "row_count",
            "action_count",
            "decision_ledger_sha256",
            "phase_a_classification_sha256",
            "snapshot_id",
            "snapshot_manifest_sha256",
        }
        plan_success_keys = apply_success_keys - {"transaction_id"}
        before = corpus_fingerprint(BrainStore.load(fixture.brain_root))

        plan_out = io.StringIO()
        plan_err = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "migration", "canonical-repair", "plan", *common_args,
        ]), redirect_stdout(plan_out), redirect_stderr(plan_err):
            self.assertEqual(cli.main(), 0, plan_out.getvalue())
        planned = json.loads(plan_out.getvalue())
        self.assertEqual(set(planned), plan_success_keys)
        self.assertEqual(planned["migration_kind"], "canonical_repair")
        self.assertEqual(planned["row_count"], 7)
        self.assertEqual(
            planned["decision_ledger_sha256"],
            fixture.ledger.sha256,
        )
        self.assertEqual(
            planned["phase_a_classification_sha256"],
            fixture.classification_sha256,
        )
        self.assertEqual(
            planned["snapshot_manifest_sha256"],
            snapshot_result.manifest_sha256,
        )
        self.assertEqual(plan_err.getvalue(), "")
        self.assertEqual(
            corpus_fingerprint(BrainStore.load(fixture.brain_root)),
            before,
        )

        wrong_out = io.StringIO()
        wrong_err = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "migration", "canonical-repair", "apply",
            *common_args,
            "--expected-manifest-sha256", "0" * 64,
        ]), redirect_stdout(wrong_out), redirect_stderr(wrong_err):
            self.assertEqual(cli.main(), 1)
        wrong = json.loads(wrong_out.getvalue())
        self.assertEqual(set(wrong), {"ok", "error_code", "error"})
        self.assertIs(wrong["ok"], False)
        self.assertEqual(wrong["error_code"], "manifest_sha256_mismatch")
        self.assertEqual(wrong_err.getvalue(), "")
        self.assertEqual(
            corpus_fingerprint(BrainStore.load(fixture.brain_root)),
            before,
        )

        apply_out = io.StringIO()
        apply_err = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "migration", "canonical-repair", "apply",
            *common_args,
            "--expected-manifest-sha256", planned["manifest_sha256"],
        ]), redirect_stdout(apply_out), redirect_stderr(apply_err):
            self.assertEqual(cli.main(), 0, apply_out.getvalue())
        applied = json.loads(apply_out.getvalue())
        self.assertEqual(set(applied), apply_success_keys)
        self.assertEqual(applied["migration_kind"], "canonical_repair")
        self.assertEqual(applied["row_count"], 7)
        self.assertEqual(
            applied["action_count"],
            planned["action_count"],
        )
        self.assertEqual(
            applied["decision_ledger_sha256"],
            fixture.ledger.sha256,
        )
        self.assertEqual(apply_err.getvalue(), "")
        after = BrainStore.load(fixture.brain_root)
        self.assertFalse(after.has("mapping.neutral.Legacy0"))
        self.assertTrue(after.has("mapping.neutral.repair-0"))
        self.assertFalse(after.has("review.bundle.Neutral.domain-mapping"))
        self.assertTrue(after.has("review.bundle.neutral.domain-mapping"))

    def test_canonical_repair_cli_plan_reports_corrupt_object_as_json(self):
        fixture, common_args, _, _ = self._canonical_cli_fixture(
            "canonical-plan-corrupt",
        )
        corrupt_path = BrainStore.object_path(
            fixture.brain_root,
            fixture.existing.get("mapping.neutral.Legacy0"),
        )
        corrupt_path.write_bytes(b"{")
        out = io.StringIO()
        err = io.StringIO()

        with mock.patch("sys.argv", [
            "cli", "migration", "canonical-repair", "plan", *common_args,
        ]), redirect_stdout(out), redirect_stderr(err):
            result = cli.main()

        self.assertEqual(result, 1)
        payload = json.loads(out.getvalue())
        self.assertEqual(set(payload), {"ok", "error_code", "error"})
        self.assertIs(payload["ok"], False)
        self.assertEqual(payload["error_code"], "object_json_invalid")
        self.assertEqual(
            payload["error"],
            (
                f"tracked object JSON is invalid at {corrupt_path}: "
                "Expecting property name enclosed in double quotes: "
                "line 1 column 2 (char 1)"
            ),
        )
        self.assertEqual(err.getvalue(), "")

    def test_canonical_repair_cli_apply_reports_corpus_io_error_as_json(self):
        fixture, common_args, _, _ = self._canonical_cli_fixture(
            "canonical-apply-corrupt",
        )
        plan_out = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "migration", "canonical-repair", "plan", *common_args,
        ]), redirect_stdout(plan_out):
            self.assertEqual(cli.main(), 0, plan_out.getvalue())
        planned = json.loads(plan_out.getvalue())
        lock_path = fixture.brain_root / ".brain-local" / "corpus.lock"
        lock_path.unlink()
        lock_path.mkdir()
        out = io.StringIO()
        err = io.StringIO()

        with mock.patch("sys.argv", [
            "cli", "migration", "canonical-repair", "apply",
            *common_args,
            "--expected-manifest-sha256", planned["manifest_sha256"],
        ]), redirect_stdout(out), redirect_stderr(err):
            result = cli.main()

        self.assertEqual(result, 1)
        payload = json.loads(out.getvalue())
        self.assertEqual(set(payload), {"ok", "error_code", "error"})
        self.assertIs(payload["ok"], False)
        self.assertEqual(payload["error_code"], "anchored_io_failed")
        self.assertEqual(
            payload["error"],
            (
                f"anchored path operation failed for {lock_path}: "
                "[Errno 21] Is a directory: 'corpus.lock'"
            ),
        )
        self.assertEqual(err.getvalue(), "")

    def test_display_plan_and_apply_require_absolute_binding_and_expected_sha(self):
        for action in ("plan", "verify-plan", "apply"):
            out = io.StringIO()
            err = io.StringIO()
            with mock.patch("sys.argv", [
                "cli", "migration", "display", action,
                "--brain-root", "/tmp/brain",
            ]), redirect_stdout(out), redirect_stderr(err):
                with self.assertRaises(SystemExit) as raised:
                    cli.main()
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("--task18-binding", err.getvalue())
            self.assertIn(
                "--expected-task18-binding-sha256",
                err.getvalue(),
            )

    def test_task18_cli_refuses_existing_report_before_action(self):
        report = (self.root / "existing-report.json").resolve()
        report.write_text("do not replace\n", encoding="utf-8")
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "migration", "display", "binding-verify",
            "--brain-root", str(self.root.resolve()),
            "--repo-root", str(self.root.resolve()),
            "--engine-root", str(self.root.resolve()),
            "--task18-binding", str((self.root / "missing.json").resolve()),
            "--expected-task18-binding-sha256", "a" * 64,
            "--report", str(report),
        ]), redirect_stdout(out), redirect_stderr(err):
            result = cli.main()
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(out.getvalue())["error_code"], "report_exists")
        self.assertEqual(report.read_text(encoding="utf-8"), "do not replace\n")
        self.assertEqual(err.getvalue(), "")

    def test_generic_apply_cannot_dispatch_display_manifest(self):
        manifest = (self.root / "display-v3.json").resolve()
        manifest.write_text(json.dumps({
            "migration_version": 3,
            "migration_kind": "display_only",
        }), encoding="utf-8")
        out = io.StringIO()
        with mock.patch("sys.argv", [
            "cli", "migration", "id", "apply",
            "--brain-root", str(self.root.resolve()),
            "--repo-root", str(self.root.resolve()),
            "--engine-root", str(self.root.resolve()),
            "--snapshot-root", str(self.root.resolve()),
            "--expected-snapshot-manifest-sha256", "a" * 64,
            "--manifest", str(manifest),
            "--expected-manifest-sha256", hashlib.sha256(
                manifest.read_bytes()
            ).hexdigest(),
            *ENGINE_ARGS,
        ]), redirect_stdout(out):
            result = cli.main()
        self.assertEqual(result, 1)
        self.assertIn("display artifact requires", out.getvalue())


if __name__ == "__main__":
    unittest.main()


def _canonical_task18_cli_args(tmp_path: Path) -> dict[tuple[str, str], list[str]]:
    root = tmp_path.resolve()
    engine = (root / "engine").resolve()
    repo = (root / "repo").resolve()
    brain = repo / "brain"
    for path in (engine, brain):
        path.mkdir(parents=True, exist_ok=True)
    sha = "a" * 64
    _commit_git_fixture(engine)
    head = _commit_git_fixture(repo)
    roots = [
        "--brain-root", str(brain),
        "--repo-root", str(repo),
        "--engine-root", str(engine),
    ]
    binding = [
        "--task18-binding", str(root / "binding.json"),
        "--expected-task18-binding-sha256", sha,
    ]
    display_common = roots + binding
    return {
        ("quote-debt", "build"): [
            "--brain-root", str(brain),
            "--repo-root", str(repo),
            "--target-revision", head,
            "--measurement", str(root / "measurement.json"),
            "--expected-measurement-sha256", sha,
            "--generated-at", "2026-08-06T12:00:00+09:00",
            "--output", str(root / "quote-debt.json"),
        ],
        ("quote-debt", "verify"): [
            "--brain-root", str(brain),
            "--inventory", str(root / "quote-debt.json"),
            "--expected-inventory-sha256", sha,
            "--stale-report", str(root / "stale.json"),
            "--phase", "pre_migration",
            "--report", str(root / "quote-verify.json"),
        ],
        ("display", "binding-create"): roots + [
            "--binding", str(root / "binding.json"),
            "--expected-engine-head", head,
            "--expected-repo-head", head,
            "--expected-engine-status-sha256", sha,
            "--expected-engine-dirt-content-sha256", sha,
            "--expected-repo-status-sha256", sha,
            "--expected-repo-dirt-content-sha256", sha,
            "--local-target-ref", "refs/remotes/origin/develop",
            "--remote", "origin",
            "--remote-target-ref", "refs/heads/develop",
            "--target-revision-sha", head,
            "--p0-handoff", str(root / "p0.json"),
            "--expected-p0-handoff-sha256", sha,
            "--measurement", str(root / "measurement.json"),
            "--expected-measurement-sha256", sha,
            "--design", str(engine / "design.md"),
            "--design-commit-sha", head,
            "--expected-design-file-sha256", sha,
            "--plan", str(engine / "plan.md"),
            "--plan-commit-sha", head,
            "--expected-plan-file-sha256", sha,
            "--quote-debt", str(root / "quote.json"),
            "--expected-quote-debt-sha256", sha,
            "--snapshot-root", str(root / "pre"),
            "--expected-snapshot-manifest-sha256", sha,
            "--snapshot-verify-receipt", str(root / "pre-verify.json"),
            "--expected-snapshot-verify-receipt-sha256", sha,
            "--generated-at", "2026-08-06T12:00:00+09:00",
        ],
        ("display", "binding-verify"): display_common + [
            "--report", str(root / "binding-verify.json"),
        ],
        ("display", "plan"): display_common + [
            "--manifest", str(root / "display.json"),
            "--report", str(root / "plan-report.json"),
        ],
        ("display", "verify-plan"): display_common + [
            "--manifest", str(root / "display.json"),
            "--expected-manifest-sha256", sha,
            "--report", str(root / "verify-plan-report.json"),
        ],
        ("display", "apply"): display_common + [
            "--manifest", str(root / "display.json"),
            "--expected-manifest-sha256", sha,
            "--report", str(root / "apply-report.json"),
        ],
        ("display", "post-verify"): display_common + [
            "--manifest", str(root / "display.json"),
            "--expected-manifest-sha256", sha,
            "--quote-debt", str(root / "quote.json"),
            "--expected-quote-debt-sha256", sha,
            "--pathspec-output", str(root / "paths.zlist"),
            "--generated-at", "2026-08-06T12:00:00+09:00",
            "--report", str(root / "post.json"),
        ],
        ("display", "closure-create"): roots + binding + [
            "--corpus-snapshot", str(root / "final"),
            "--expected-snapshot-manifest-sha256", sha,
            "--snapshot-verify", str(root / "final-verify.json"),
            "--expected-snapshot-verify-sha256", sha,
            "--display-manifest", str(root / "display.json"),
            "--expected-display-manifest-sha256", sha,
            "--post-report", str(root / "post.json"),
            "--expected-post-report-sha256", sha,
            "--completion-report", str(engine / "completion.md"),
            "--roadmap", str(engine / "ROADMAP.md"),
            "--expected-engine-head", head,
            "--expected-bb2-head", head,
            "--generated-at", "2026-08-06T12:00:00+09:00",
            "--report", str(root / "closure.json"),
        ],
        ("display", "closure-verify"): roots + [
            "--closure", str(root / "closure.json"),
            "--expected-closure-sha256", sha,
            "--report", str(root / "closure-verify.json"),
        ],
    }


def test_all_ten_task18_canonical_actions_parse_and_dispatch(tmp_path: Path):
    commands = _canonical_task18_cli_args(tmp_path)
    assert len(commands) == 10
    with mock.patch("project_brain.cli._run_task18_migration", return_value=0) as run:
        for (mode, action), args in commands.items():
            run.reset_mock()
            assert cli._run_migration([mode, action, *args]) == 0
            parsed = run.call_args.args[0]
            assert (parsed.mode, parsed.action) == (mode, action)


def test_all_ten_task18_canonical_actions_reach_their_service_seams(tmp_path: Path):
    commands = _canonical_task18_cli_args(tmp_path)
    sha = "a" * 64
    head = "b" * 40
    service_patches = {
        ("quote-debt", "build"): "project_brain.quote_debt.build_quote_debt_inventory",
        ("quote-debt", "verify"): "project_brain.quote_debt.verify_quote_debt_inventory",
        ("display", "binding-create"): "project_brain.task18_binding.create_task18_binding",
        ("display", "binding-verify"): "project_brain.task18_binding_verify.verify_task18_binding",
        ("display", "plan"): "project_brain.migration.plan_display_migration",
        ("display", "verify-plan"): "project_brain.migration.verify_display_migration_artifact",
        ("display", "apply"): "project_brain.migration.apply_display_migration_artifact",
        ("display", "post-verify"): "project_brain.task18_verify.verify_task18_applied",
        ("display", "closure-create"): "project_brain.task18_verify.create_task18_closure_receipt",
        ("display", "closure-verify"): "project_brain.task18_verify.verify_task18_closure_receipt",
    }
    return_values = {
        ("quote-debt", "build"): {"quote_debt_ids": []},
        ("quote-debt", "verify"): {"ok": True},
        ("display", "binding-create"): SimpleNamespace(
            path=Path(commands[("display", "binding-create")][
                commands[("display", "binding-create")].index("--binding") + 1
            ]),
            sha256=sha,
        ),
        ("display", "binding-verify"): SimpleNamespace(
            path="binding.json", sha256=sha, migration_targets=(),
        ),
        ("display", "plan"): SimpleNamespace(request=SimpleNamespace(objects=[])),
        ("display", "verify-plan"): SimpleNamespace(ok=True),
        ("display", "apply"): SimpleNamespace(
            transaction_id="tx", action_count=0, snapshot_id="snapshot",
        ),
        ("display", "post-verify"): SimpleNamespace(
            report_path=tmp_path / "post.json", report_sha256=sha, update_count=0,
        ),
        ("display", "closure-create"): SimpleNamespace(
            ok=True, closure_path=tmp_path / "closure.json", closure_sha256=sha,
        ),
        ("display", "closure-verify"): SimpleNamespace(
            ok=True,
            closure_path=tmp_path / "closure.json",
            closure_sha256=sha,
            report_path=tmp_path / "closure-verify.json",
            report_sha256=sha,
        ),
    }
    with ExitStack() as stack:
        services = {
            key: stack.enter_context(mock.patch(path, return_value=return_values[key]))
            for key, path in service_patches.items()
        }
        stack.enter_context(mock.patch(
            "project_brain.foundation.atomic_create_receipt", return_value=sha,
        ))
        stack.enter_context(mock.patch(
            "project_brain.cli._atomic_create_bytes_exclusive", return_value=sha,
        ))
        stack.enter_context(mock.patch(
            "project_brain.migration.create_display_migration_artifact",
            return_value=SimpleNamespace(manifest_bytes=b"{}\n", manifest_sha256=sha),
        ))
        stack.enter_context(mock.patch("project_brain.store.BrainStore.load", return_value=SimpleNamespace()))
        stack.enter_context(mock.patch("project_brain.snapshot.verify_git_root_head", return_value=head))
        stack.enter_context(mock.patch("project_brain.stale_check.make_git_runner", return_value=object()))
        stack.enter_context(mock.patch("project_brain.stale_check.stale_check", return_value={}))
        stack.enter_context(mock.patch(
            "project_brain.task18_verify.read_task18_canonical_document", return_value={},
        ))
        stack.enter_context(mock.patch(
            "project_brain.task18_verify.read_task18_json_bytes",
            return_value=SimpleNamespace(data=b"{}\n", value={}),
        ))
        for key, args in commands.items():
            with redirect_stdout(io.StringIO()):
                assert cli._run_migration([*key, *args]) == 0
            services[key].assert_called_once()


def test_quote_debt_build_accepts_exact_sha_in_real_git_repo(tmp_path: Path):
    args = _canonical_task18_cli_args(tmp_path)[("quote-debt", "build")]
    target_revision = args[args.index("--target-revision") + 1]
    stale_report = {"target_head": target_revision}
    inventory = {"quote_debt_ids": []}

    with (
        mock.patch(
            "project_brain.store.BrainStore.load",
            return_value=SimpleNamespace(),
        ),
        mock.patch(
            "project_brain.stale_check.stale_check",
            return_value=stale_report,
        ) as stale,
        mock.patch(
            "project_brain.quote_debt.build_quote_debt_inventory",
            return_value=inventory,
        ) as build,
        mock.patch(
            "project_brain.foundation.atomic_create_receipt",
            return_value="a" * 64,
        ),
        redirect_stdout(io.StringIO()),
    ):
        assert cli._run_migration(["quote-debt", "build", *args]) == 0

    assert stale.call_args.kwargs["target_head"] == target_revision
    assert stale.call_args.kwargs["fetch"] is False
    assert build.call_args.kwargs["stale_report"] is stale_report
    assert build.call_args.kwargs["target_revision_sha"] == target_revision


def test_quote_debt_build_rejects_full_ref_before_service(tmp_path: Path):
    args = _canonical_task18_cli_args(tmp_path)[("quote-debt", "build")]
    target_index = args.index("--target-revision") + 1
    args[target_index] = "refs/heads/master"
    output = io.StringIO()

    with (
        mock.patch(
            "project_brain.quote_debt.build_quote_debt_inventory",
        ) as build,
        redirect_stdout(output),
    ):
        assert cli._run_migration(["quote-debt", "build", *args]) == 1

    assert json.loads(output.getvalue())["error_code"] == "commit_sha_invalid"
    build.assert_not_called()


def test_binding_create_canonical_command_dispatches_generated_at_as_clock(
    tmp_path: Path,
):
    from project_brain.task18_binding import Task18BindingCreateResult

    args = _canonical_task18_cli_args(tmp_path)[("display", "binding-create")]
    binding_path = Path(args[args.index("--binding") + 1])
    generated_at = args[args.index("--generated-at") + 1]
    created = Task18BindingCreateResult(binding_path, "c" * 64, {})
    with mock.patch(
        "project_brain.task18_binding.create_task18_binding",
        return_value=created,
    ) as create, redirect_stdout(io.StringIO()):
        assert cli._run_migration(["display", "binding-create", *args]) == 0
    request = create.call_args.args[0]
    assert request.binding_path == binding_path
    assert create.call_args.kwargs["clock"]() == generated_at
    assert binding_path == Path(args[args.index("--binding") + 1])


def test_closure_verify_canonical_command_needs_no_generated_at(tmp_path: Path):
    from project_brain.task18_verify import Task18ClosureResult

    args = _canonical_task18_cli_args(tmp_path)[("display", "closure-verify")]
    report = Path(args[args.index("--report") + 1])
    closure = Path(args[args.index("--closure") + 1])
    result = Task18ClosureResult(
        closure_path=closure,
        closure_sha256="a" * 64,
        report_path=report,
        report_sha256="d" * 64,
    )
    with mock.patch(
        "project_brain.task18_verify.verify_task18_closure_receipt",
        return_value=result,
    ) as verify, redirect_stdout(io.StringIO()):
        assert cli._run_migration(["display", "closure-verify", *args]) == 0
    assert "generated_at" not in verify.call_args.kwargs
