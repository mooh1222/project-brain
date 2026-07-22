from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("finalize_ingest.py")


def load_module():
    if not SCRIPT.is_file():
        raise AssertionError("semantic finalizer is missing")
    spec = importlib.util.spec_from_file_location("finalize_ingest_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class SemanticFinalizerTest(unittest.TestCase):
    def setUp(self):
        self.contract = {
            "recall_checks": [{
                "key": "feature-a",
                "query": "기능 A의 핵심 동작",
                "expected_object_ids": ["mapping.a"],
                "require_code_locators": True,
            }],
            "intentional_terminal_ids": ["code.allowed"],
        }

    @staticmethod
    def _runner(*, current_isolated=None, search_results=None, failures=()):
        current_isolated = ["code.before"] if current_isolated is None else current_isolated
        search_results = ([{
            "object_id": "mapping.a",
            "linked": {"code_locators": [{"id": "code.a"}]},
        }] if search_results is None else search_results)

        def run(command):
            name = " ".join(command)
            if command[:3] == ["project-brain", "index", "rebuild"]:
                payload = {"ok": True, "indexed": 3}
            elif command[:2] == ["project-brain", "lint"]:
                payload = {"ok": True, "problems": []}
            elif command[:2] == ["project-brain", "eval"]:
                payload = {"ok": True, "summary": {"failed": 0}}
            elif command[:3] == ["project-brain", "graph", "isolated"]:
                payload = {"ok": True, "isolated": current_isolated}
            elif command[:2] == ["project-brain", "search"]:
                payload = {"ok": True, "results": search_results}
            else:
                payload = None
            failed = name in failures
            stdout = "tests passed\n" if payload is None else json.dumps(payload)
            return subprocess.CompletedProcess(command, 7 if failed else 0, stdout=stdout,
                                               stderr="failed" if failed else "")
        return run

    def test_success_returns_exact_machine_readable_gate_schema(self):
        module = load_module()
        report = module.run_finalization(
            self.contract, ["code.before"], runner=self._runner()
        )

        self.assertEqual(set(report), {"ok", "commands", "isolation", "recall_checks", "errors"})
        self.assertTrue(report["ok"])
        self.assertEqual(set(report["commands"]),
                         {"index_rebuild", "lint", "eval", "graph_isolated", "corpus_tests"})
        for command in report["commands"].values():
            self.assertEqual(set(command), {"ok", "exit_code", "payload", "stderr"})
        self.assertEqual(report["isolation"], {
            "ok": True,
            "baseline_ids": ["code.before"],
            "current_ids": ["code.before"],
            "new_ids": [],
            "intentional_terminal_ids": ["code.allowed"],
            "allowed_new_ids": [],
            "unexpected_new_ids": [],
        })
        self.assertEqual(report["recall_checks"][0]["missing_object_ids"], [])
        self.assertEqual(report["recall_checks"][0]["missing_code_locator_object_ids"], [])

    def test_new_isolation_is_blocking_except_declared_terminal(self):
        module = load_module()
        allowed = module.run_finalization(
            self.contract, ["code.before"],
            runner=self._runner(current_isolated=["code.before", "code.allowed"]),
        )
        blocked = module.run_finalization(
            self.contract, ["code.before"],
            runner=self._runner(current_isolated=["code.before", "code.unexpected"]),
        )

        self.assertTrue(allowed["ok"])
        self.assertEqual(allowed["isolation"]["allowed_new_ids"], ["code.allowed"])
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["isolation"]["unexpected_new_ids"], ["code.unexpected"])

    def test_recall_requires_each_expected_id_and_its_linked_code_locator(self):
        module = load_module()
        missing = module.run_finalization(
            self.contract, ["code.before"], runner=self._runner(search_results=[])
        )
        unlinked = module.run_finalization(
            self.contract, ["code.before"],
            runner=self._runner(search_results=[{"object_id": "mapping.a", "linked": {}}]),
        )

        self.assertFalse(missing["ok"])
        self.assertEqual(missing["recall_checks"][0]["missing_object_ids"], ["mapping.a"])
        self.assertFalse(unlinked["ok"])
        self.assertEqual(unlinked["recall_checks"][0]["missing_code_locator_object_ids"],
                         ["mapping.a"])

    def test_contract_rejects_fixed_sample_or_empty_expectations(self):
        module = load_module()
        for contract in ({}, {"recall_checks": [], "intentional_terminal_ids": []}, {
            "recall_checks": [{"key": "a", "query": "", "expected_object_ids": []}],
            "intentional_terminal_ids": [],
        }):
            with self.subTest(contract=contract), self.assertRaises(ValueError):
                module.validate_contract(contract)


if __name__ == "__main__":
    unittest.main()
