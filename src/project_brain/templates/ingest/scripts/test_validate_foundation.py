"""설치되는 foundation wrapper의 공개 명령 계약."""

from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path


SOURCE_RUNTIME = Path(__file__).with_name("validate_foundation.py")


def load_runtime_under_test():
    runtime = Path(os.environ.get("PROJECT_BRAIN_FOUNDATION_RUNTIME", SOURCE_RUNTIME))
    spec = importlib.util.spec_from_file_location("project_brain_foundation_runtime", runtime)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"foundation runtime을 불러올 수 없음: {runtime}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ValidateFoundationRuntimeTest(unittest.TestCase):
    def test_env_can_select_installed_runtime(self):
        module = load_runtime_under_test()
        self.assertEqual(
            Path(module.__file__).resolve(),
            Path(os.environ.get("PROJECT_BRAIN_FOUNDATION_RUNTIME", SOURCE_RUNTIME)).resolve(),
        )

    def test_main_result_rejects_missing_subcommand(self):
        module = load_runtime_under_test()
        rc, report = module.main_result([])
        self.assertEqual(rc, 2)
        self.assertEqual(report["error_code"], "argument_error")


if __name__ == "__main__":
    unittest.main()
