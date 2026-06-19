"""doctor — 의존성·백엔드·프로젝트 상태 진단.

의존성 체크는 실환경(이 venv에 전부 설치돼 있음)으로, 프로젝트 상태 체크는
tmp 코퍼스로 검증한다. required 실패가 하나라도 있으면 전체 ok=False.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_brain.doctor import diagnose
from project_brain.store import BrainStore

from tests.test_ingest import context


class DiagnoseEnvTest(unittest.TestCase):
    def test_required_checks_pass_in_dev_env(self):
        # 이 venv에는 필수 의존성이 전부 있다 — required 체크는 전부 통과해야 한다.
        report = diagnose(start=Path("/"))  # config 없는 위치
        required = [c for c in report["checks"] if c["severity"] == "required"]
        self.assertTrue(required)
        for c in required:
            self.assertTrue(c["ok"], c)

    def test_report_shape(self):
        report = diagnose(start=Path("/"))
        for c in report["checks"]:
            self.assertIn("name", c)
            self.assertIn("ok", c)
            self.assertIn("severity", c)
            self.assertIn("detail", c)

    def test_missing_config_is_optional_failure_not_fatal(self):
        report = diagnose(start=Path("/"))
        cfg = next(c for c in report["checks"] if c["name"] == "config")
        self.assertFalse(cfg["ok"])
        self.assertEqual(cfg["severity"], "optional")


class DiagnoseProjectTest(unittest.TestCase):
    def test_project_checks_with_corpus(self):
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            (root / ".project-brain.json").write_text("{}", encoding="utf-8")
            BrainStore.save_object(root / "brain", context())
            (root / "brain" / "eval_scenarios.json").write_text(
                json.dumps({"scenarios": [
                    {"id": "s", "query": "q", "expect": {"no_answer": True}}
                ]}), encoding="utf-8")
            report = diagnose(start=root)
            by_name = {c["name"]: c for c in report["checks"]}
            self.assertTrue(by_name["config"]["ok"])
            self.assertTrue(by_name["corpus"]["ok"])
            self.assertIn("1", by_name["corpus"]["detail"])  # 객체 1개
            self.assertTrue(by_name["scenarios"]["ok"])
            self.assertFalse(by_name["index"]["ok"])  # 색인은 아직 없음


if __name__ == "__main__":
    unittest.main()
