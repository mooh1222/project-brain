"""Replay raw-name driver must stay fail-closed and reproducible."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from project_brain.installer import install
from project_brain.mutation import MutationOperation, MutationRequest, MutationService
from tests.coverage_helpers import direct_coverage
from tests.test_ingest import manifest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ingest_skill_behavior" / "raw_names"
DRIVER = (ROOT / "docs" / "reports" / "2026-07-22-bulk-ingest-task9-behavior-replay"
          / "raw_names" / "replay_raw_names.py")
EXPECTED_RAW_HASHES = {
    "feature-revisions/spec-v1.md": "2f84de119bbbf853dd03bb553fbfb8863d1c9d2b038b9a056b34c535f8c28ea2",
    "feature-revisions/spec-v2.md": "af74c89ddecf4fdcab8b73f4c0d9a947bd48f8ced06ecea28a03bc81c04af1f2",
    "legacy-archive/collision-notes-01967d62e17e.md": "5f1417e2bc761ec75d1682c0f360258c9f843af3b7b43dd55be2cbb4df482eed",
    "legacy-archive/collision-notes.md": "3d9da81e35def52e472f3d80c9709886522622eb214631f6dc2dae8bfc0d3a79",
    "legacy-archive/document.md": "4802063ee382e72cdc04f591a68ae9c026d20192054a96820be10dda233f9cbc",
    "legacy-archive/legacy-plan-01.md": "ac34797a75d32e8bd7e40dce09d37eb61821c4f2186d2125532efdbc1d275241",
    "legacy-archive/legacy-plan-02.md": "5a02769e8c99f32479528f27ced4349ba2d476915112469bbf2980bf2700221a",
    "legacy-archive/legacy-plan-03.md": "936348b2559285d9486c248d89bca11224d1ffffd5ef311fe2d603caa1ec35f4",
    "legacy-archive/legacy-plan-04.md": "b0678019f7a76be481353acdd97992b4d26555e309edebead86c64c4762e0661",
    "legacy-archive/legacy-plan-05.md": "154ea902427ee2abaffa8e430f2d1f8bd331505d2a774b7b0ac11add72cdbaa8",
    "legacy-archive/legacy-plan-06.md": "ded8313c791ea46d8c33c3d623eb3b53c2927a19a3132558c5fd9c18d5899336",
    "legacy-archive/legacy-plan-07.md": "80e261f0b07901a9d239fb195b508b66b4f591ea5263d08c5b0a70d592e9d129",
    "legacy-archive/legacy-plan-08.md": "28a09b5bdd075cd45d836e84499719d2740d472e4d04b244503ccb29f6d2a0ca",
    "legacy-archive/legacy-plan-09.md": "bc91ac309bf781f2bd1dea7825c4355e179381889e4e9753de268b95fc6385aa",
    "legacy-archive/legacy-plan-10.md": "6fa414e486d7e50159e7b048cbd6a328ccb3eea4d3a261f385d3a25a0da44ccd",
    "legacy-archive/legacy-plan-11.md": "299c07e362433fd7d90d58c77a01c1c67c26cbeff770e3593f94ac91dfc3a12d",
    "legacy-archive/legacy-plan-12.md": "6df078869aa845fb71a94113b356a98535aa5fcf7bbf20ec30bfbc7008418d8d",
    "legacy-archive/legacy-plan-13.md": "e8cba501601b9cb2887a82909fc77b06912c230178f146ab5bbfc506ef13260d",
    "legacy-archive/legacy-plan-14.md": "375a55c1ca64e8573d1d068969110fa17faddfcab80b3602c0147856816444e0",
    "legacy-archive/legacy-plan-15.md": "0cb4613ca6b5fb75bbfd5f4032170bb986982cd21880d9e184b5b80a479634dd",
    "legacy-archive/legacy-plan-16.md": "74886aedb1cf64bdd20e2e1dadc10bda6c22416ce5236a50a3fe1c71328ce13b",
    "legacy-archive/legacy-plan-17.md": "6078d14ba9ed0cb6df0e0940be2663157aad69cabba83b6bcfde3dfeec9e04ac",
}


def _write_surface_inventory(root: Path) -> dict[str, bytes | None]:
    inventory: dict[str, bytes | None] = {}
    for relative in (
        "brain/objects",
        "brain/raw",
        "brain/indexes",
        "brain/views",
        ".brain-local",
    ):
        base = root / relative
        if not base.exists():
            continue
        inventory[relative + "/"] = None
        for path in sorted(base.rglob("*")):
            key = path.relative_to(root).as_posix()
            inventory[key + ("/" if path.is_dir() else "")] = (
                None if path.is_dir() else path.read_bytes()
            )
    return inventory


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CoverageWriteBoundaryReplayTest(unittest.TestCase):
    def test_direct_plan_is_a_no_write_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            brain_root = root / "brain"
            obj = manifest()
            before = _write_surface_inventory(root)
            request = MutationRequest(
                operation=MutationOperation.INGEST,
                brain_root=brain_root,
                repo_context=None,
                engine_sha="e" * 40,
                objects=(obj,),
                coverage=direct_coverage(obj),
            )

            result = MutationService().plan((obj,), request=request)

            self.assertTrue(result.ok, (result.error_code, result.detail))
            self.assertEqual(_write_surface_inventory(root), before)

    def test_installed_batch_rejects_missing_coverage_before_runner_or_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install(root, project="demo")
            verify = root / "verify.json"
            domain = root / "domain.py"
            manifest_path = root / "batch.json"
            report = root / "batch-report.json"
            verify.write_text('{"groups": []}\n', encoding="utf-8")
            domain.write_text('CTX = "missing-coverage"\n', encoding="utf-8")
            manifest_path.write_text(json.dumps({
                "repo_root": str(root.resolve()),
                "expected_repo_id": "demo",
                "expected_revision_ref": "HEAD",
                "engine_sha": "e" * 40,
                "items": [{
                    "key": "one",
                    "verify_json": verify.name,
                    "domain_spec_py": domain.name,
                }],
                "finalization": {},
            }), encoding="utf-8")
            runtime = (
                root / ".agents/skills/demo-brain-ingest/scripts/run_ingest_batch.py"
            )
            module = _load_module(runtime, "installed_batch_missing_coverage")
            runner = mock.Mock(side_effect=AssertionError("runner must not start"))
            before = _write_surface_inventory(root)

            with self.assertRaisesRegex(ValueError, "COVERAGE가 없습니다"):
                module.run_batch(manifest_path, report, item_runner=runner)

            runner.assert_not_called()
            self.assertFalse(report.exists())
            self.assertEqual(_write_surface_inventory(root), before)

    def test_installed_assembled_dry_run_checks_coverage_without_corpus_writes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install(root, project="demo")
            verify = root / "verify.json"
            domain = root / "domain.py"
            bin_dir = root / "bin"
            tmp_dir = root / "tmp"
            calls = root / "calls.jsonl"
            bin_dir.mkdir()
            tmp_dir.mkdir()
            verify.write_text('{"groups": []}\n', encoding="utf-8")
            domain.write_text(textwrap.dedent('''\
                CTX = "dry-fixture"
                COMMIT = "a" * 40
                REPO = "demo"
                MANIFESTS = {}
                DISPLAY_NAME = "비파괴 조립 fixture"
                BOUNDARY_SUMMARY = "coverage dry-run 경계"
                IN_SCOPE = []
                OUT_OF_SCOPE = []
                COVERAGE = {
                    "version": 1,
                    "mode": "assembled",
                    "verify_groups": {"names": [], "empty_reason": "검증 그룹 없음"},
                    "context": {"key": "dry-fixture", "mode": "create"},
                    "sections": {
                        "sources": {"ids": [], "empty_reason": "출처 없음"},
                        "glossary": {"keys": [], "empty_reason": "용어 없음"},
                        "code_anchors": {"keys": [], "empty_reason": "코드 없음"},
                        "mappings": {"keys": [], "empty_reason": "매핑 없음"},
                        "decisions": {"items": [], "empty_reason": "결정 없음"},
                        "refs": {"items": [], "empty_reason": "참조 없음"},
                        "updates": {"ids": [], "empty_reason": "갱신 없음"},
                        "extra_objects": {"objects": [], "empty_reason": "추가 없음"},
                    },
                    "expected_objects": [
                        {"id": "context.dry-fixture", "kind": "DomainContext"}
                    ],
                }
                EXCLUDE_TERMS = set()
                HISTORY_COVERAGE = "unsearched"
                CLAIM_STATUS = "reviewed"
                CORRECTIONS = {}
                DECISIONS = []
            '''), encoding="utf-8")
            fake_cli = bin_dir / "project-brain"
            fake_cli.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''\
                import json
                import os
                import sys
                from pathlib import Path
                from project_brain.cli import main

                with Path(os.environ["CALL_LOG"]).open("a", encoding="utf-8") as stream:
                    print(json.dumps({"command": sys.argv[1], "args": sys.argv[2:]}), file=stream)
                raise SystemExit(main())
            '''), encoding="utf-8")
            fake_cli.chmod(0o755)
            runner = root / ".agents/skills/demo-brain-ingest/scripts/run_ingest.sh"
            before = _write_surface_inventory(root)
            env = dict(
                os.environ,
                PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                PYTHONPATH=str(ROOT / "src"),
                TMPDIR=str(tmp_dir),
                CALL_LOG=str(calls),
            )

            result = subprocess.run(
                [str(runner), "--dry", str(verify), str(domain)],
                env=env,
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            recorded = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual([item["command"] for item in recorded], ["build"])
            self.assertEqual(_write_surface_inventory(root), before)


class RawReplayDriverTest(unittest.TestCase):
    def make_target(self) -> tempfile.TemporaryDirectory[str]:
        td = tempfile.TemporaryDirectory()
        shutil.copytree(FIXTURE, Path(td.name), dirs_exist_ok=True)
        return td

    def test_installed_runtime_source_has_no_exit_only_or_quote_bypass_success(self):
        scripts = ROOT / "src" / "project_brain" / "templates" / "ingest" / "scripts"
        batch = (scripts / "run_ingest_batch.py").read_text(encoding="utf-8")
        finalizer = (scripts / "finalize_ingest.py").read_text(encoding="utf-8")
        shell = (scripts / "run_ingest.sh").read_text(encoding="utf-8")
        combined = "\n".join((batch, finalizer, shell))

        for token in (
            "validate_transaction_results",
            "manifest_sha256",
            "resume_contract_mismatch",
            "--validate-transaction",
            "item_records",
            "recover_batch_receipts",
            "target_revision_sha",
            "batch-binding.json",
            "--brain-root",
            "brain_root_inode",
            "post-finalizer verification",
            "post_gate_object_tail",
            "strict_commit",
        ):
            self.assertIn(token, combined)
        self.assertNotIn("allow_missing_quote", combined)
        self.assertNotIn("allow-missing-quote", combined)

    def run_driver(self, target: Path, *, timeout: float = 2) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(DRIVER)], cwd=target, text=True,
                              capture_output=True, check=False, timeout=timeout)

    def test_normal_fixture_writes_exactly_twenty_two_byte_equal_sources(self):
        with self.make_target() as td:
            target = Path(td)
            result = self.run_driver(target)
            self.assertEqual(result.returncode, 0, result.stderr)
            raw_files = sorted((target / "brain" / "raw" / "sources").rglob("*.md"))
            self.assertEqual(len(raw_files), 22)
            actual_hashes = {
                path.relative_to(target / "brain" / "raw" / "sources").as_posix():
                hashlib.sha256(path.read_bytes()).hexdigest()
                for path in raw_files
            }
            self.assertEqual(actual_hashes, EXPECTED_RAW_HASHES)
            self.assertEqual(
                (target / "sources" / "collision-a" / "Collision Notes.md").read_bytes(),
                (target / "brain" / "raw" / "sources" / "legacy-archive" / "collision-notes.md").read_bytes(),
            )

    def test_module_import_does_not_run_the_driver(self):
        spec = importlib.util.spec_from_file_location("replay_raw_names_under_test", DRIVER)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.run))

    def test_second_run_fails_closed_without_changing_inventory(self):
        with self.make_target() as td:
            target = Path(td)
            self.assertEqual(self.run_driver(target).returncode, 0)
            raw_root = target / "brain" / "raw" / "sources"
            before = {p.relative_to(raw_root): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in raw_root.rglob("*.md")}

            second = self.run_driver(target)

            self.assertNotEqual(second.returncode, 0)
            after = {p.relative_to(raw_root): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in raw_root.rglob("*.md")}
            self.assertEqual(after, before)

    def test_symlinked_source_is_rejected_before_raw_write(self):
        with self.make_target() as td, tempfile.TemporaryDirectory() as outside:
            target = Path(td)
            external = Path(outside) / "external.md"
            external.write_text("outside", encoding="utf-8")
            (target / "sources" / "escape.md").symlink_to(external)

            result = self.run_driver(target)

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((target / "brain" / "raw" / "sources").exists())

    def test_destination_component_symlinks_are_rejected_before_external_write(self):
        for component in ("brain", "brain/raw", "brain/raw/sources"):
            with self.subTest(component=component), self.make_target() as td, tempfile.TemporaryDirectory() as outside:
                target = Path(td)
                destination = target / component
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(Path(outside), target_is_directory=True)

                result = self.run_driver(target)

                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(Path(outside).iterdir()), [])

    def test_empty_destination_directory_is_nonempty_and_unchanged(self):
        with self.make_target() as td:
            target = Path(td)
            raw_root = target / "brain" / "raw" / "sources"
            empty_entry = raw_root / "empty-entry"
            empty_entry.mkdir(parents=True)

            result = self.run_driver(target)

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(empty_entry.is_dir())
            self.assertEqual(list(raw_root.iterdir()), [empty_entry])

    def test_all_collision_prefixes_finish_with_explicit_error(self):
        with self.make_target() as td:
            target = Path(td)
            archive = target / "brain" / "raw" / "sources" / "legacy-archive"
            archive.mkdir(parents=True)
            canonical = "collision-a/Collision Notes.md"
            archive.joinpath("collision-notes.md").write_text("occupied", encoding="utf-8")
            digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            for width in range(12, 65):
                archive.joinpath(f"collision-notes-{digest[:width]}.md").write_text(
                    "occupied", encoding="utf-8")

            result = self.run_driver(target, timeout=2)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("collision", result.stderr.lower())

    def test_existing_revision_with_different_bytes_is_not_overwritten(self):
        with self.make_target() as td:
            target = Path(td)
            destination = target / "brain" / "raw" / "sources" / "feature-revisions" / "spec-v1.md"
            destination.parent.mkdir(parents=True)
            destination.write_text("old bytes", encoding="utf-8")

            result = self.run_driver(target)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(destination.read_text(encoding="utf-8"), "old bytes")
