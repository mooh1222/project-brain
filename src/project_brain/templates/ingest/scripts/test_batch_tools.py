from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


SCRIPTS = Path(__file__).resolve().parent
BATCH_SCRIPT = SCRIPTS / "run_ingest_batch.py"
VALIDATOR_SCRIPT = SCRIPTS / "validate_workflow_result.py"
FAILURE_SUFFIX = "::failed-item-stderr-tail::\n"


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

with Path(os.environ["FAKE_CALL_LOG"]).open("a", encoding="utf-8") as log:
    print(json.dumps({"kind": "finalize", "argv": sys.argv[1:]}), file=log)
if os.environ.get("FAKE_FINALIZER_FAIL") == "1":
    print("finalizer failed", file=sys.stderr)
    raise SystemExit(23)
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
        manifest.write_text(json.dumps({"items": items}), encoding="utf-8")
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
        self.assertEqual([call["kind"] for call in calls], ["item", "item", "item"])
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
                         ["item", "item", "item", "item", "finalize"])
        self._assert_item_invocations(calls, manifest, ("a", "b", "c", "c"))
        saved = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(saved["succeeded"], ["a", "b", "c"])
        self.assertEqual(saved["failed"], [])
        self.assertTrue(saved["finalized"])

    def test_finalizer_failure_returns_one_without_marking_report_finalized(self):
        self._copy_runtime_scripts()
        result = self._run_batch(self._manifest(), self.root / "report.json", finalizer_fails=True)

        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads((self.root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["succeeded"], ["a", "b", "c"])
        self.assertFalse(report["finalized"])
        self.assertEqual([call["kind"] for call in self._calls()],
                         ["item", "item", "item", "finalize"])


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


if __name__ == "__main__":
    unittest.main()
