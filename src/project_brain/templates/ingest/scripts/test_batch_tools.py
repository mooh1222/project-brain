from __future__ import annotations

import importlib.util
import errno
import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory


SCRIPTS = Path(__file__).resolve().parent
BATCH_SCRIPT = SCRIPTS / "run_ingest_batch.py"
VALIDATOR_SCRIPT = SCRIPTS / "validate_workflow_result.py"
FAILURE_SUFFIX = "::failed-item-stderr-tail::\n"
FINALIZATION = {
    "recall_checks": [{
        "key": "feature-a",
        "query": "기능 A 핵심 동작",
        "expected_object_ids": ["mapping.a"],
        "require_code_locators": True,
    }],
    "intentional_terminal_ids": [],
}
FINALIZATION_RESULT = {
    "ok": True,
    "commands": {},
    "isolation": {},
    "recall_checks": [],
    "errors": [],
}


def load_script(path: Path, module_name: str):
    if not path.is_file():
        raise AssertionError(f"Task 5 runtime script is missing: {path.name}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load runtime script: {path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BatchRunnerCliTest(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.root = Path(self._td.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.manifest_dir = self.root / "manifest"
        self.manifest_dir.mkdir()
        self.run_dir = self.root / "unrelated-cwd"
        self.run_dir.mkdir()
        self.log = self.root / "calls.log"

    def tearDown(self):
        self._td.cleanup()

    def _write_executable(self, name: str, source: str) -> Path:
        path = self.runtime / name
        path.write_text(source, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def _copy_runtime_scripts(self):
        self.assertTrue(BATCH_SCRIPT.is_file(), "Task 5 batch runner is missing")
        self.assertTrue(VALIDATOR_SCRIPT.is_file(), "Task 5 workflow validator is missing")
        shutil.copy2(BATCH_SCRIPT, self.runtime / BATCH_SCRIPT.name)
        shutil.copy2(VALIDATOR_SCRIPT, self.runtime / VALIDATOR_SCRIPT.name)
        shutil.copy2(SCRIPTS / "finalize_ingest.py", self.runtime / "finalize_ingest.py")
        self._write_executable(
            "run_ingest.sh",
            """#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path

args = sys.argv[1:]
input_args = [arg for arg in args if arg != "--defer-finalize"]
key = Path(input_args[0]).stem if input_args else "missing-key"
def observe(path_text):
    path = Path(path_text).resolve()
    return {
        "resolved": str(path),
        "exists": path.is_file(),
        "content": path.read_text(encoding="utf-8") if path.is_file() else None,
    }
with Path(os.environ["FAKE_CALL_LOG"]).open("a", encoding="utf-8") as log:
    print(json.dumps({
        "kind": "item",
        "key": key,
        "argv": args,
        "inputs": [observe(path_text) for path_text in input_args],
    }), file=log)
if key in os.environ.get("FAKE_FAIL_KEYS", "").split(","):
    print("x" * 2_100 + f"::{key}::failed-item-stderr-tail::", file=sys.stderr)
    raise SystemExit(17)
""",
        )
        self._write_executable(
            "finalize_ingest.sh",
            """#!/usr/bin/env python3
import os
import sys
import json
from pathlib import Path

kind = "baseline" if "--capture-baseline" in sys.argv else "finalize"
with Path(os.environ["FAKE_CALL_LOG"]).open("a", encoding="utf-8") as log:
    print(json.dumps({"kind": kind, "argv": sys.argv[1:]}), file=log)
if kind == "baseline":
    print(json.dumps({"ok": True, "isolated_ids": ["code.before"]}))
    raise SystemExit(0)
if os.environ.get("FAKE_FINALIZER_FAIL") == "1":
    print(json.dumps({"ok": False, "commands": {}, "isolation": {},
                      "recall_checks": [], "errors": ["finalizer failed"]}))
    print("finalizer failed", file=sys.stderr)
    raise SystemExit(23)
print(json.dumps({"ok": True, "commands": {}, "isolation": {},
                  "recall_checks": [], "errors": []}))
""",
        )

    def _manifest(self) -> Path:
        items = []
        inputs = self.manifest_dir / "inputs"
        inputs.mkdir()
        for key in ("a", "b", "c"):
            verify = inputs / f"{key}.json"
            domain_spec = inputs / f"{key}.py"
            verify.write_text("{}\n", encoding="utf-8")
            domain_spec.write_text("# fixture\n", encoding="utf-8")
            items.append({
                "key": key,
                "verify_json": str(verify.relative_to(self.manifest_dir)),
                "domain_spec_py": str(domain_spec.relative_to(self.manifest_dir)),
            })
        manifest = self.manifest_dir / "batch.json"
        manifest.write_text(json.dumps({"items": items, "finalization": FINALIZATION}),
                            encoding="utf-8")
        return manifest

    def _run_batch(self, manifest: Path, report: Path, *, resume: bool = False,
                   failed_keys: str = "",
                   finalizer_fails: bool = False) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, FAKE_CALL_LOG=str(self.log), FAKE_FAIL_KEYS=failed_keys,
                   FAKE_FINALIZER_FAIL="1" if finalizer_fails else "0")
        command = [sys.executable, str(self.runtime / BATCH_SCRIPT.name), str(manifest),
                   "--report", str(report)]
        if resume:
            command.extend(["--resume", str(report)])
        return subprocess.run(command, cwd=self.run_dir, env=env, text=True,
                              capture_output=True, check=False)

    def _calls(self) -> list[dict]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    @staticmethod
    def _failure_stderr(key: str) -> str:
        return "x" * 2_100 + f"::{key}" + FAILURE_SUFFIX

    @staticmethod
    def _item_calls(calls: list[dict]) -> list[dict]:
        return [call for call in calls if call["kind"] == "item"]

    def _expected_item_inputs(self, manifest: Path, key: str) -> list[dict]:
        inputs = manifest.parent / "inputs"
        return [
            {"resolved": str((inputs / f"{key}.json").resolve()),
             "exists": True, "content": "{}\n"},
            {"resolved": str((inputs / f"{key}.py").resolve()),
             "exists": True, "content": "# fixture\n"},
        ]

    def _assert_item_invocations(self, calls: list[dict], manifest: Path,
                                 keys: tuple[str, ...]) -> None:
        item_calls = self._item_calls(calls)
        self.assertEqual([call["key"] for call in item_calls], list(keys))
        for call, key in zip(item_calls, keys):
            with self.subTest(key=key):
                self.assertEqual(call["argv"].count("--defer-finalize"), 1)
                self.assertEqual(call["inputs"], self._expected_item_inputs(manifest, key))

    def test_partial_failure_blocks_finalization_and_returns_one(self):
        self._copy_runtime_scripts()
        manifest = self._manifest()
        result = self._run_batch(manifest, self.root / "report.json", failed_keys="c")

        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["expected"], 3)
        self.assertEqual(report["succeeded"], ["a", "b"])
        failed = report["failed"][0]
        self.assertEqual(failed["key"], "c")
        self.assertEqual(failed["exit_code"], 17)
        self.assertEqual(failed["stderr"], self._failure_stderr("c")[-2_000:])
        self.assertFalse(report["finalized"])
        calls = self._calls()
        self.assertEqual([call["kind"] for call in calls],
                         ["baseline", "item", "item", "item"])
        self._assert_item_invocations(calls, manifest, ("a", "b", "c"))

    def test_resume_retries_only_the_failed_item(self):
        self._copy_runtime_scripts()
        manifest = self._manifest()
        report = self.root / "report.json"
        first = self._run_batch(manifest, report, failed_keys="c")
        resumed = self._run_batch(manifest, report, resume=True)

        self.assertEqual(first.returncode, 1, first.stderr)
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        calls = self._calls()
        self.assertEqual([call["kind"] for call in calls],
                         ["baseline", "item", "item", "item", "item", "finalize"])
        self._assert_item_invocations(calls, manifest, ("a", "b", "c", "c"))
        saved = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(saved["succeeded"], ["a", "b", "c"])
        self.assertEqual(saved["failed"], [])
        self.assertTrue(saved["finalized"])
        self.assertEqual(saved["isolation_baseline"], ["code.before"])

    def test_finalizer_failure_returns_one_without_marking_report_finalized(self):
        self._copy_runtime_scripts()
        result = self._run_batch(self._manifest(), self.root / "report.json", finalizer_fails=True)

        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["succeeded"], ["a", "b", "c"])
        self.assertFalse(report["finalized"])
        self.assertEqual(report["finalize_failure"],
                         {"exit_code": 23, "stderr": "finalizer failed\n"})
        self.assertFalse(report["finalization"]["ok"])
        self.assertEqual([call["kind"] for call in self._calls()],
                         ["baseline", "item", "item", "item", "finalize"])

    def test_preflight_rejects_duplicate_keys_and_missing_paths_before_running(self):
        self._copy_runtime_scripts()
        manifest = self._manifest()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["items"][1]["key"] = "a"
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        duplicate = self._run_batch(manifest, self.root / "duplicate-report.json")
        self.assertEqual(duplicate.returncode, 1, duplicate.stderr)
        self.assertEqual(self._calls(), [])

    def test_preflight_rejects_missing_semantic_finalization_before_running(self):
        self._copy_runtime_scripts()
        manifest = self._manifest()
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload.pop("finalization")
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        result = self._run_batch(manifest, self.root / "missing-finalization.json")

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self._calls(), [])
        self.assertIn("manifest.finalization", json.loads(result.stdout)["errors"][0])

        payload["items"][1]["key"] = "b"
        payload["items"][1]["verify_json"] = "inputs/missing.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        missing_path = self._run_batch(manifest, self.root / "missing-report.json")
        self.assertEqual(missing_path.returncode, 1, missing_path.stderr)
        self.assertEqual(self._calls(), [])

    def test_empty_manifest_is_rejected_before_runner_or_finalizer(self):
        self._copy_runtime_scripts()
        manifest = self.manifest_dir / "empty-batch.json"
        manifest.write_text(json.dumps({"items": [], "finalization": FINALIZATION}), encoding="utf-8")
        report = self.root / "empty-report.json"

        result = self._run_batch(manifest, report)

        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(any("최소 1개" in error for error in payload["errors"]))
        self.assertEqual(self._calls(), [])
        self.assertFalse(report.exists())

    def test_invalid_report_target_fails_before_any_item_with_json_error(self):
        self._copy_runtime_scripts()
        report_directory = self.root / "report-directory"
        report_directory.mkdir()
        result = self._run_batch(self._manifest(), report_directory)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self._calls(), [])
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["errors"])

    def test_cli_rejects_report_paths_that_alias_manifest_inputs_before_runtime(self):
        self._copy_runtime_scripts()
        manifest = self._manifest()
        inputs = manifest.parent / "inputs"
        verify = inputs / "a.json"
        domain_spec = inputs / "a.py"
        report_alias = self.root / "report-alias.json"
        report_alias.symlink_to(verify)
        original_inputs = {
            manifest: manifest.read_bytes(),
            verify: verify.read_bytes(),
            domain_spec: domain_spec.read_bytes(),
        }
        for label, report_path, source in (
            ("manifest", manifest, manifest),
            ("verify", verify, verify),
            ("domain", domain_spec, domain_spec),
            ("symlink", report_alias, verify),
        ):
            with self.subTest(label=label):
                for path, data in original_inputs.items():
                    path.write_bytes(data)
                self.log.write_text("", encoding="utf-8")
                before = source.read_bytes()
                result = self._run_batch(manifest, report_path)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(self._calls(), [])
                self.assertIn("report", json.loads(result.stdout)["errors"][0])

    def test_unreadable_resume_report_returns_json_error_before_any_item(self):
        self._copy_runtime_scripts()
        resume_directory = self.root / "resume-directory"
        resume_directory.mkdir()
        result = self._run_batch(self._manifest(), resume_directory, resume=True)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self._calls(), [])
        self.assertFalse(json.loads(result.stdout)["ok"])


class WorkflowResultValidatorTest(unittest.TestCase):
    def _validate(self, payload: dict) -> list[str]:
        module = load_script(VALIDATOR_SCRIPT, "validate_workflow_result_under_test")
        return module.validate_result(payload)

    @staticmethod
    def _valid_payload() -> dict:
        return {
            "expected": 3,
            "items": [
                {"key": "a", "extract_status": "ok", "verify_status": "ok", "verdict": "pass"},
                {"key": "b", "extract_status": "ok", "verify_status": "ok", "verdict": "fixed"},
                {"key": "c", "extract_status": "ok", "verify_status": "ok", "verdict": "pass"},
            ],
            "failures": [],
        }

    def test_completed_status_does_not_override_missing_item(self):
        payload = self._valid_payload()
        payload["items"].pop()
        payload["status"] = "completed"
        self.assertTrue(self._validate(payload))

    def test_cli_rejects_empty_completed_workflow_result(self):
        payload = {"status": "completed", "expected": 0, "items": [], "failures": []}
        with TemporaryDirectory() as td:
            path = Path(td) / "empty-result.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = subprocess.run([sys.executable, str(VALIDATOR_SCRIPT), str(path)],
                                    text=True, capture_output=True, check=False)

        self.assertEqual(result.returncode, 1, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output["ok"])
        self.assertTrue(any("1 이상의 정수" in error for error in output["errors"]))

    def test_rejects_invalid_expected_scalars(self):
        for expected in (False, -1, "3", None):
            with self.subTest(expected=expected):
                payload = self._valid_payload()
                payload["expected"] = expected
                errors = self._validate(payload)
                self.assertTrue(any("1 이상의 정수" in error for error in errors))

    def test_rejects_duplicate_item_keys(self):
        payload = self._valid_payload()
        payload["items"][2]["key"] = "b"
        self.assertTrue(self._validate(payload))

    def test_rejects_non_ok_extract_status(self):
        payload = self._valid_payload()
        payload["items"][0]["extract_status"] = "blocked"
        self.assertTrue(self._validate(payload))

    def test_rejects_reported_failure(self):
        payload = self._valid_payload()
        payload["failures"] = [{"key": "b", "reason": "timeout"}]
        self.assertTrue(self._validate(payload))

    def test_rejects_any_non_ok_verify_status(self):
        for verify_status in ("error", "blocked", "skipped", "", None):
            with self.subTest(verify_status=verify_status):
                payload = self._valid_payload()
                payload["items"][1]["verify_status"] = verify_status
                self.assertTrue(self._validate(payload))

    def test_rejects_invalid_verdict(self):
        payload = self._valid_payload()
        payload["items"][2]["verdict"] = "needs_user"
        self.assertTrue(self._validate(payload))

    def test_accepts_only_all_good_result(self):
        self.assertEqual(self._validate(self._valid_payload()), [])

    def test_cli_prints_required_json_and_exit_status(self):
        with TemporaryDirectory() as td:
            path = Path(td) / "result.json"
            path.write_text(json.dumps(self._valid_payload()), encoding="utf-8")
            valid = subprocess.run([sys.executable, str(VALIDATOR_SCRIPT), str(path)],
                                   text=True, capture_output=True, check=False)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(json.loads(valid.stdout), {"ok": True, "completed": 3})

            payload = self._valid_payload()
            payload["failures"] = [{"key": "b"}]
            path.write_text(json.dumps(payload), encoding="utf-8")
            invalid = subprocess.run([sys.executable, str(VALIDATOR_SCRIPT), str(path)],
                                     text=True, capture_output=True, check=False)
            self.assertEqual(invalid.returncode, 1, invalid.stderr)
            self.assertFalse(json.loads(invalid.stdout)["ok"])

    def test_cli_invalid_input_always_returns_json_error(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            invalid_inputs = {
                "invalid-utf8": b"\xff",
                "malformed": b"{",
                "array": b"[]",
            }
            for name, content in invalid_inputs.items():
                with self.subTest(name=name):
                    path = root / f"{name}.json"
                    path.write_bytes(content)
                    result = subprocess.run([sys.executable, str(VALIDATOR_SCRIPT), str(path)],
                                            text=True, capture_output=True, check=False)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    payload = json.loads(result.stdout)
                    self.assertFalse(payload["ok"])
                    self.assertTrue(payload["errors"])
                    self.assertNotIn("Traceback", result.stderr)
            missing = subprocess.run([sys.executable, str(VALIDATOR_SCRIPT), str(root / "missing.json")],
                                     text=True, capture_output=True, check=False)
            self.assertEqual(missing.returncode, 1, missing.stderr)
            self.assertFalse(json.loads(missing.stdout)["ok"])


class BatchRunnerApiTest(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.root = Path(self._td.name)
        self.manifest_dir = self.root / "manifest"
        self.manifest_dir.mkdir()
        (self.manifest_dir / "verify.json").write_text("{}\n", encoding="utf-8")
        (self.manifest_dir / "domain.py").write_text("# fixture\n", encoding="utf-8")
        self.manifest = self.manifest_dir / "batch.json"
        self.manifest.write_text(json.dumps({"items": [{
            "key": "one", "verify_json": "verify.json", "domain_spec_py": "domain.py",
        }], "finalization": FINALIZATION}), encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def _module(self):
        module = load_script(BATCH_SCRIPT, "run_ingest_batch_under_test")
        module._default_baseline_collector = lambda: {"ok": True, "isolated_ids": ["code.before"]}
        return module

    def test_unknown_or_bool_injected_results_fail_closed(self):
        module = self._module()
        invalid_results = (None, "ok", True, (0,), (False, "stderr"), ("0", "stderr"))
        for index, result in enumerate(invalid_results):
            with self.subTest(result=repr(result)):
                report = module.run_batch(
                    self.manifest, self.root / f"unknown-{index}.json",
                    item_runner=lambda item, value=result: value,
                finalizer=lambda *_: FINALIZATION_RESULT,
                )
                self.assertEqual(report["succeeded"], [])
                self.assertFalse(report["finalized"])
                self.assertEqual(report["failed"][0]["key"], "one")

    def test_exit_zero_without_structured_finalization_fails_closed(self):
        module = self._module()
        report = module.run_batch(
            self.manifest, self.root / "exit-only-finalizer.json",
            item_runner=lambda item: 0,
            finalizer=lambda *_: 0,
        )

        self.assertFalse(report["finalized"])
        self.assertFalse(report["finalization"]["ok"])
        self.assertTrue(report["finalization"]["errors"])

    def test_baseline_failure_blocks_items_and_report_creation(self):
        module = self._module()
        calls = []
        report_path = self.root / "baseline-failure.json"
        with self.assertRaises(ValueError):
            module.run_batch(
                self.manifest, report_path,
                item_runner=lambda item: calls.append(item["key"]) or 0,
                baseline_collector=lambda: {"ok": False, "error": "graph failed"},
            )
        self.assertEqual(calls, [])
        self.assertFalse(report_path.exists())

    def test_api_rejects_report_paths_that_alias_manifest_inputs_before_callbacks(self):
        module = self._module()
        verify = self.manifest_dir / "verify.json"
        domain_spec = self.manifest_dir / "domain.py"
        report_alias = self.root / "report-alias.json"
        report_alias.symlink_to(verify)
        original_inputs = {
            self.manifest: self.manifest.read_bytes(),
            verify: verify.read_bytes(),
            domain_spec: domain_spec.read_bytes(),
        }
        for label, report_path, source in (
            ("manifest", self.manifest, self.manifest),
            ("verify", verify, verify),
            ("domain", domain_spec, domain_spec),
            ("symlink", report_alias, verify),
        ):
            with self.subTest(label=label):
                for path, data in original_inputs.items():
                    path.write_bytes(data)
                before = source.read_bytes()
                calls = []
                with self.assertRaisesRegex(ValueError, "report.*입력"):
                    module.run_batch(
                        self.manifest, report_path,
                        baseline_collector=lambda: calls.append("baseline") or {
                            "ok": True, "isolated_ids": []},
                        item_runner=lambda item: calls.append("item") or 0,
                        finalizer=lambda *_: calls.append("finalizer") or FINALIZATION_RESULT,
                    )
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(calls, [])

    def test_batch_passes_normalized_baseline_list_to_finalizer(self):
        module = self._module()
        observed = []
        report = module.run_batch(
            self.manifest, self.root / "baseline-list.json",
            item_runner=lambda item: 0,
            baseline_collector=lambda: {"ok": True, "isolated_ids": ["code.before"]},
            finalizer=lambda contract, baseline: (
                observed.append((contract, baseline)) or FINALIZATION_RESULT
            ),
        )

        self.assertTrue(report["finalized"])
        self.assertEqual(observed[0][1], ["code.before"])

    def test_supported_injected_results_and_falsey_callables_succeed(self):
        module = self._module()

        class FalseyCallable:
            def __init__(self, result):
                self.result = result
                self.calls = 0

            def __bool__(self):
                return False

            def __call__(self, *args):
                self.calls += 1
                return self.result

        for index, result in enumerate((0, (0, ""), subprocess.CompletedProcess([], 0, stderr=""))):
            with self.subTest(result=repr(result)):
                runner = FalseyCallable(result)
                finalizer = FalseyCallable(FINALIZATION_RESULT)
                report = module.run_batch(self.manifest, self.root / f"accepted-{index}.json",
                                          item_runner=runner, finalizer=finalizer)
                self.assertEqual(report["succeeded"], ["one"])
                self.assertTrue(report["finalized"])
                self.assertEqual((runner.calls, finalizer.calls), (1, 1))

    def test_injected_exceptions_become_item_or_finalizer_failures(self):
        module = self._module()
        item_failure = module.run_batch(
            self.manifest, self.root / "item-exception.json",
            item_runner=lambda item: (_ for _ in ()).throw(RuntimeError("item boom")),
            finalizer=lambda *_: FINALIZATION_RESULT,
        )
        self.assertEqual(item_failure["failed"][0]["stderr"], "item boom")
        self.assertFalse(item_failure["finalized"])

        finalizer_failure = module.run_batch(
            self.manifest, self.root / "finalizer-exception.json",
            item_runner=lambda item: 0,
            finalizer=lambda *_: (_ for _ in ()).throw(RuntimeError("finalizer boom")),
        )
        self.assertTrue(finalizer_failure["succeeded"])
        self.assertFalse(finalizer_failure["finalized"])
        self.assertEqual(finalizer_failure["finalize_failure"]["stderr"], "finalizer boom")

    def test_completed_process_bytes_stderr_is_recorded_as_text(self):
        module = self._module()
        report = module.run_batch(
            self.manifest, self.root / "bytes-stderr.json",
            item_runner=lambda item: subprocess.CompletedProcess([], 7, stderr=b"byte failure"),
        )
        self.assertEqual(report["failed"][0]["stderr"], "byte failure")

    def test_invalid_resume_reports_are_rejected_before_item_execution(self):
        module = self._module()
        invalid_reports = (
            [],
            {"expected": 1, "succeeded": [], "failed": []},
            {"expected": True, "succeeded": [], "failed": [], "finalized": False},
            {"expected": 2, "succeeded": [], "failed": [], "finalized": False},
            {"expected": 1, "succeeded": ["one", "one"], "failed": [], "finalized": False},
            {"expected": 1, "succeeded": [1], "failed": [], "finalized": False},
            {"expected": 1, "succeeded": ["foreign"], "failed": [], "finalized": False},
            {"expected": 1, "succeeded": [], "failed": "bad", "finalized": False},
            {"expected": 1, "succeeded": [], "failed": [{"key": 1}], "finalized": False},
            {"expected": 1, "succeeded": [], "failed": [{"key": "foreign"}], "finalized": False},
            {"expected": 1, "succeeded": [], "failed": [
                {"key": "one", "exit_code": 1, "stderr": "x"},
                {"key": "one", "exit_code": 1, "stderr": "x"},
            ], "finalized": False},
            {"expected": 1, "succeeded": ["one"], "failed": [{"key": "one"}], "finalized": False},
            {"expected": 1, "succeeded": [], "failed": [], "finalized": 0},
        )
        calls: list[str] = []
        for index, payload in enumerate(invalid_reports):
            with self.subTest(payload=payload):
                resume = self.root / f"invalid-resume-{index}.json"
                resume.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    module.run_batch(self.manifest, self.root / f"report-{index}.json",
                                     resume_path=resume,
                                     item_runner=lambda item: calls.append(item["key"]) or 0)
        self.assertEqual(calls, [])

    def test_report_fingerprint_allows_resume_of_unchanged_inputs(self):
        module = self._module()
        report_path = self.root / "resume-report.json"
        failed = module.run_batch(self.manifest, report_path, item_runner=lambda item: 9)
        self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["manifest_fingerprint"],
                         failed["manifest_fingerprint"])
        calls: list[str] = []
        resumed = module.run_batch(report_path=report_path, manifest_path=self.manifest,
                                   resume_path=report_path,
                                   item_runner=lambda item: calls.append(item["key"]) or 0,
                                   finalizer=lambda *_: FINALIZATION_RESULT)
        self.assertEqual(calls, ["one"])
        self.assertTrue(resumed["finalized"])
        self.assertIsInstance(resumed["manifest_fingerprint"], str)
        self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["manifest_fingerprint"],
                         resumed["manifest_fingerprint"])

    def test_resume_rejects_changed_verify_content_before_item_execution(self):
        module = self._module()
        report_path = self.root / "changed-verify-report.json"
        module.run_batch(self.manifest, report_path, item_runner=lambda item: 9)
        (self.manifest_dir / "verify.json").write_text('{"changed": true}\n', encoding="utf-8")
        calls: list[str] = []
        with self.assertRaises(ValueError):
            module.run_batch(self.manifest, report_path, resume_path=report_path,
                             item_runner=lambda item: calls.append(item["key"]) or 0)
        self.assertEqual(calls, [])

    def test_resume_rejects_changed_finalization_contract_before_execution(self):
        module = self._module()
        report_path = self.root / "changed-finalization-report.json"
        module.run_batch(self.manifest, report_path, item_runner=lambda item: 9)
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        payload["finalization"]["recall_checks"][0]["query"] = "달라진 질의"
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")
        calls = []
        with self.assertRaises(ValueError):
            module.run_batch(self.manifest, report_path, resume_path=report_path,
                             item_runner=lambda item: calls.append(item["key"]) or 0)
        self.assertEqual(calls, [])

    def test_resume_rejects_same_key_with_different_resolved_input(self):
        module = self._module()
        report_path = self.root / "different-path-report.json"
        module.run_batch(self.manifest, report_path, item_runner=lambda item: 9)
        other_verify = self.manifest_dir / "other-verify.json"
        other_verify.write_text((self.manifest_dir / "verify.json").read_text(encoding="utf-8"),
                                encoding="utf-8")
        self.manifest.write_text(json.dumps({"items": [{
            "key": "one", "verify_json": "other-verify.json", "domain_spec_py": "domain.py",
        }], "finalization": FINALIZATION}), encoding="utf-8")
        calls: list[str] = []
        with self.assertRaises(ValueError):
            module.run_batch(self.manifest, report_path, resume_path=report_path,
                             item_runner=lambda item: calls.append(item["key"]) or 0)
        self.assertEqual(calls, [])

    def test_resume_rejects_missing_or_malformed_fingerprint_before_execution(self):
        module = self._module()
        base_report = {
            "expected": 1, "succeeded": [], "failed": [], "finalized": False,
        }
        calls: list[str] = []
        for index, fingerprint in enumerate((None, 3, "")):
            with self.subTest(fingerprint=fingerprint):
                payload = dict(base_report)
                if fingerprint is not None:
                    payload["manifest_fingerprint"] = fingerprint
                resume = self.root / f"bad-fingerprint-{index}.json"
                resume.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    module.run_batch(self.manifest, self.root / f"target-{index}.json",
                                     resume_path=resume,
                                     item_runner=lambda item: calls.append(item["key"]) or 0)
        self.assertEqual(calls, [])

    def test_parent_directory_unsupported_fsync_errno_is_tolerated(self):
        module = self._module()
        report_path = self.root / "unsupported-parent-fsync.json"
        original_parent_fsync = module._fsync_parent_directory

        def unsupported_parent_fsync(path):
            with mock.patch.object(module.os, "fsync",
                                   side_effect=OSError(errno.EINVAL, "unsupported directory fsync")):
                return original_parent_fsync(path)

        with mock.patch.object(module, "_fsync_parent_directory",
                               side_effect=unsupported_parent_fsync):
            module._write_report(report_path, {"ok": True})
        self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), {"ok": True})

    def test_parent_directory_eio_surfaces_and_cleans_temporary_file(self):
        module = self._module()
        report_path = self.root / "eio-parent-fsync.json"
        original_parent_fsync = module._fsync_parent_directory

        def eio_parent_fsync(path):
            with mock.patch.object(module.os, "fsync", side_effect=OSError(errno.EIO, "disk error")):
                return original_parent_fsync(path)

        with mock.patch.object(module, "_fsync_parent_directory", side_effect=eio_parent_fsync):
            with self.assertRaises(ValueError):
                module._write_report(report_path, {"ok": True})
        self.assertEqual(list(self.root.glob(f".{report_path.name}.*.tmp")), [])


class RunIngestCleanupTest(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.root = Path(self._td.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.tmp_dir = self.root / "tmp"
        self.tmp_dir.mkdir()
        self.call_log = self.root / "calls.jsonl"
        shutil.copy2(SCRIPTS / "run_ingest.sh", self.runtime / "run_ingest.sh")
        (self.runtime / "assemble_notes.py").write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path
            Path(sys.argv[sys.argv.index("-o") + 1]).write_text("notes", encoding="utf-8")
            if "--finalization-out" in sys.argv and os.environ.get("FAKE_OMIT_FINALIZATION") != "1":
                payload = {} if os.environ.get("FAKE_INVALID_FINALIZATION") == "1" else {
                    "recall_checks": [{"key": "one", "query": "one query",
                                       "expected_object_ids": ["mapping.one"],
                                       "require_code_locators": True}],
                    "intentional_terminal_ids": [],
                }
                Path(sys.argv[sys.argv.index("--finalization-out") + 1]).write_text(
                    json.dumps(payload), encoding="utf-8")
        """), encoding="utf-8")
        (self.runtime / "finalize_ingest.py").write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path
            with Path(os.environ["FAKE_CALL_LOG"]).open("a", encoding="utf-8") as log:
                print(json.dumps({"kind": "validate", "args": sys.argv[1:]}), file=log)
            payload = json.loads(Path(sys.argv[sys.argv.index("--validate-config") + 1]).read_text())
            if not payload.get("recall_checks"):
                raise SystemExit(31)
            print(json.dumps({"ok": True, "validated": True}))
        """), encoding="utf-8")
        (self.runtime / "finalize_ingest.sh").write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path
            kind = ("validate" if "--validate-config" in sys.argv else
                    "baseline" if "--capture-baseline" in sys.argv else "finalize")
            with Path(os.environ["FAKE_CALL_LOG"]).open("a", encoding="utf-8") as log:
                print(json.dumps({"kind": kind, "args": sys.argv[1:]}), file=log)
            if kind == "validate":
                payload = json.loads(Path(sys.argv[sys.argv.index("--validate-config") + 1]).read_text())
                if not payload.get("recall_checks"):
                    raise SystemExit(31)
                print(json.dumps({"ok": True, "validated": True}))
                raise SystemExit(0)
            if kind == "baseline":
                print(json.dumps({"ok": True, "isolated_ids": ["code.before"]}))
                raise SystemExit(0)
            raise SystemExit(int(os.environ.get("FAKE_FINALIZER_EXIT", "0")))
        """), encoding="utf-8")
        (self.bin_dir / "project-brain").write_text(textwrap.dedent("""\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            command, *args = sys.argv[1:]
            if command == "build":
                objects = Path(args[args.index("--objects-file") + 1])
                objects.write_text("[]\\n", encoding="utf-8")
                print(json.dumps({"ok": True, "preconditions": {"expected": "fresh"}}))
                raise SystemExit(int(os.environ.get("FAKE_BUILD_EXIT", "0")))
            if command == "ingest":
                observed = {"kind": "ingest", "args": args}
                if "--preconditions-file" in args:
                    report = Path(args[args.index("--preconditions-file") + 1])
                    observed["preconditions"] = report.read_text(encoding="utf-8")
                with Path(os.environ["FAKE_CALL_LOG"]).open("a", encoding="utf-8") as log:
                    print(json.dumps(observed), file=log)
                raise SystemExit(int(os.environ.get("FAKE_INGEST_EXIT", "0")))
        """), encoding="utf-8")
        for path in (self.runtime / "run_ingest.sh", self.runtime / "finalize_ingest.sh",
                     self.bin_dir / "project-brain"):
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.verify = self.root / "verify.json"
        self.spec = self.root / "domain.py"
        self.verify.write_text("{}\n", encoding="utf-8")
        self.spec.write_text("# fixture\n", encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def test_default_finalizer_returns_through_runner_shell(self):
        text = (SCRIPTS / "run_ingest.sh").read_text(encoding="utf-8")
        self.assertNotIn('exec "$HERE/finalize_ingest.sh"', text)

    def _run(self, flags=(), *, finalizer_exit=0, ingest_exit=0, build_exit=0,
             invalid_finalization=False, omit_finalization=False):
        env = dict(os.environ, TMPDIR=str(self.tmp_dir),
                   PATH=f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
                   FAKE_CALL_LOG=str(self.call_log),
                   FAKE_FINALIZER_EXIT=str(finalizer_exit),
                   FAKE_INGEST_EXIT=str(ingest_exit),
                   FAKE_BUILD_EXIT=str(build_exit),
                   FAKE_INVALID_FINALIZATION="1" if invalid_finalization else "0",
                   FAKE_OMIT_FINALIZATION="1" if omit_finalization else "0")
        return subprocess.run([str(self.runtime / "run_ingest.sh"), *flags,
                               str(self.verify), str(self.spec)],
                              env=env, text=True, capture_output=True, check=False)

    def test_build_report_is_forwarded_to_ingest_as_preconditions(self):
        result = self._run(["--defer-finalize"])

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.call_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertIn("--preconditions-file", calls[0]["args"])
        self.assertEqual(json.loads(calls[0]["preconditions"]),
                         {"ok": True, "preconditions": {"expected": "fresh"}})

    def test_single_run_captures_baseline_before_ingest_and_passes_semantic_inputs(self):
        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.call_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([call["kind"] for call in calls],
                         ["validate", "baseline", "ingest", "finalize"])
        final_args = calls[-1]["args"]
        self.assertIn("--config", final_args)
        self.assertIn("--baseline", final_args)

    def test_invalid_single_run_finalization_blocks_before_build_or_ingest(self):
        result = self._run(invalid_finalization=True)

        self.assertEqual(result.returncode, 31, result.stderr)
        calls = [json.loads(line) for line in self.call_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([call["kind"] for call in calls], ["validate"])

    def test_missing_single_run_finalization_cannot_close_successfully(self):
        result = self._run(omit_finalization=True)

        self.assertNotEqual(result.returncode, 0)
        calls = [json.loads(line) for line in self.call_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([call["kind"] for call in calls], ["validate"])

    def test_all_exit_paths_remove_all_temporary_files(self):
        cases = (
            ([], 0, 0, 0, 0),
            ([], 23, 0, 0, 23),
            (["--defer-finalize"], 0, 0, 0, 0),
            (["--dry"], 0, 0, 0, 0),
            ([], 0, 17, 0, 17),
            ([], 0, 0, 19, 19),
        )
        for flags, finalizer_exit, ingest_exit, build_exit, expected_exit in cases:
            with self.subTest(flags=flags, finalizer_exit=finalizer_exit,
                              ingest_exit=ingest_exit, build_exit=build_exit):
                env = dict(os.environ, TMPDIR=str(self.tmp_dir),
                           PATH=f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
                           FAKE_CALL_LOG=str(self.call_log),
                           FAKE_FINALIZER_EXIT=str(finalizer_exit),
                           FAKE_INGEST_EXIT=str(ingest_exit),
                           FAKE_BUILD_EXIT=str(build_exit),
                           FAKE_INVALID_FINALIZATION="0",
                           FAKE_OMIT_FINALIZATION="0")
                result = subprocess.run([str(self.runtime / "run_ingest.sh"), *flags,
                                         str(self.verify), str(self.spec)],
                                        env=env, text=True, capture_output=True, check=False)
                self.assertEqual(result.returncode, expected_exit, result.stderr)
                self.assertEqual(list(self.tmp_dir.glob("notes.*")), [])
                self.assertEqual(list(self.tmp_dir.glob("objects.*")), [])
                self.assertEqual(list(self.tmp_dir.glob("build-report.*")), [])
                self.assertEqual(list(self.tmp_dir.glob("finalization.*")), [])
                self.assertEqual(list(self.tmp_dir.glob("isolation-baseline.*")), [])


if __name__ == "__main__":
    unittest.main()
