from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


SCRIPT = Path(__file__).with_name("finalize_ingest.py")
WRAPPER = Path(__file__).with_name("finalize_ingest.sh")
TRANSACTION = {
    "ok": True,
    "transaction_id": "1" * 64,
    "operation": "ingest",
    "committed": True,
    "manifest_sha256": "2" * 64,
    "before_fingerprint": "3" * 64,
    "after_fingerprint": "4" * 64,
    "ingested_ids": ["mapping.a"],
    "ingested_count": 1,
}
BINDING = {
    "batch_manifest_sha256": "5" * 64,
    "item_key": "one",
    "item_input_fingerprint": "6" * 64,
    "verify_json_sha256": "7" * 64,
    "domain_spec_py_sha256": "8" * 64,
    "repo_root": "/tmp/project-brain-consumer",
    "brain_root": "/tmp/project-brain-consumer/brain",
    "brain_root_device": 101,
    "brain_root_inode": 202,
    "expected_repo_id": "demo",
    "expected_revision_ref": "HEAD",
    "target_revision_sha": "9" * 40,
    "engine_root": "/tmp/project-brain-engine",
    "engine_sha": "a" * 40,
}
ITEM_RECORD = {
    "binding": BINDING,
    "status": "committed",
    "failure": None,
    "transaction": TRANSACTION,
}


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
        self._td = TemporaryDirectory()
        self.repo_root = Path(self._td.name)
        self.brain_root = self.repo_root / "brain"
        self.brain_root.mkdir()
        brain_stat = self.brain_root.stat()
        self.binding = {
            **BINDING,
            "repo_root": str(self.repo_root.resolve()),
            "brain_root": str(self.brain_root.resolve()),
            "brain_root_device": brain_stat.st_dev,
            "brain_root_inode": brain_stat.st_ino,
        }
        self.item_record = {
            **ITEM_RECORD,
            "binding": self.binding,
        }
        self.contract = {
            "recall_checks": [{
                "key": "feature-a",
                "query": "기능 A의 핵심 동작",
                "expected_object_ids": ["mapping.a"],
                "require_code_locators": True,
            }],
            "intentional_terminal_ids": ["code.allowed"],
            "expected_unmerged_locator_ids": [],
        }

    def tearDown(self):
        self._td.cleanup()

    def _finalize(self, module, contract, baseline, **kwargs):
        transaction_results = kwargs.pop("transaction_results", [TRANSACTION])
        return module.run_finalization(
            contract,
            baseline,
            transaction_results=transaction_results,
            **kwargs,
        )

    @staticmethod
    def _runner(*, current_isolated=None, search_results=None, failures=(),
                target_head="TARGET", unmerged_locator_ids=(), audit_payload=None):
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
            elif command == ["project-brain", "audit", "--no-fetch"]:
                payload = audit_payload if audit_payload is not None else {
                    "ok": True,
                    "stale": {
                        "target_head": target_head,
                        "unmerged_anchors": [
                            {"locator_id": locator_id, "reason": "not_ancestor"}
                            for locator_id in unmerged_locator_ids
                        ],
                    },
                }
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
        self.assertEqual(module.validate_transaction_results([TRANSACTION]), [TRANSACTION])
        report = self._finalize(module,
            self.contract, ["code.before"], transaction_results=[TRANSACTION],
            runner=self._runner()
        )

        self.assertEqual(set(report),
                         {"ok", "transactions", "commands", "isolation", "unmerged",
                          "recall_checks", "errors"})
        self.assertTrue(report["ok"])
        self.assertEqual(report["transactions"], [TRANSACTION])
        self.assertEqual(set(report["commands"]),
                         {"index_rebuild", "lint", "eval", "graph_isolated", "audit", "corpus_tests"})
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

    def test_missing_mismatched_noncommitted_and_needs_user_transactions_fail_closed(self):
        module = load_module()
        invalid = (
            None,
            [],
            [{**TRANSACTION, "committed": False}],
            [{**TRANSACTION, "manifest_sha256": "A" * 64}],
            [{**TRANSACTION, "status": "needs_user"}],
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "transaction"):
                    module.validate_transaction_results(value)

    def test_item_records_are_recovered_from_the_common_durable_receipt_chain(self):
        module = load_module()
        observed = []

        def recoverer(brain_root, bindings, expected_receipts):
            observed.append((brain_root, bindings, expected_receipts))
            return expected_receipts

        report = module.run_finalization(
            self.contract,
            ["code.before"],
            item_records=[self.item_record],
            repo_root=self.repo_root,
            receipt_recoverer=recoverer,
            config_loader=lambda start: {
                "root": self.repo_root,
                "brain_root": self.brain_root,
            },
            runner=self._runner(),
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["transactions"], [TRANSACTION])
        expected_call = (
            self.brain_root.resolve(),
            (self.binding,),
            (TRANSACTION,),
        )
        self.assertEqual(observed, [expected_call, expected_call])

    def test_item_record_forgery_or_noncommitted_state_blocks_before_commands(self):
        module = load_module()
        cases = (
            [{**self.item_record, "status": "pending", "transaction": None}],
            [{**self.item_record, "transaction": {**TRANSACTION, "manifest_sha256": "f" * 64}}],
        )
        for records in cases:
            calls = []
            with self.subTest(records=records), self.assertRaises(ValueError):
                module.run_finalization(
                    self.contract,
                    ["code.before"],
                    item_records=records,
                    repo_root=self.repo_root,
                    receipt_recoverer=lambda _root, _bindings, _expected: (TRANSACTION,),
                    config_loader=lambda start: {
                        "root": self.repo_root,
                        "brain_root": self.brain_root,
                    },
                    runner=lambda command: calls.append(command),
                )
            self.assertEqual(calls, [])

    def test_receipt_chain_is_revalidated_after_semantic_commands(self):
        module = load_module()
        recover_calls = 0
        commands = []

        def recoverer(_brain_root, _bindings, expected_receipts):
            nonlocal recover_calls
            recover_calls += 1
            if recover_calls == 2:
                raise ValueError("object corpus tail changed")
            return expected_receipts

        runner = self._runner()

        def observed_runner(command):
            commands.append(command)
            return runner(command)

        report = module.run_finalization(
            self.contract,
            ["code.before"],
            item_records=[self.item_record],
            repo_root=self.repo_root,
            receipt_recoverer=recoverer,
            config_loader=lambda start: {
                "root": self.repo_root,
                "brain_root": self.brain_root,
            },
            runner=observed_runner,
        )

        self.assertEqual(recover_calls, 2)
        self.assertTrue(commands)
        self.assertFalse(report["ok"])
        self.assertIn(
            "post-gate durable receipt verification failed",
            "\n".join(report["errors"]),
        )

    def test_post_gate_allows_derived_change_but_rejects_brain_root_swap(self):
        module = load_module()
        for change in ("derived", "brain_root_swap"):
            with self.subTest(change=change):
                changed = False
                runner = self._runner()

                def changing_runner(command):
                    nonlocal changed
                    if not changed:
                        changed = True
                        if change == "derived":
                            local = self.brain_root / ".brain-local"
                            local.mkdir()
                            (local / "index.db").write_bytes(b"derived")
                        else:
                            detached = self.repo_root / "brain-detached"
                            self.brain_root.rename(detached)
                            self.brain_root.mkdir()
                    return runner(command)

                report = module.run_finalization(
                    self.contract,
                    ["code.before"],
                    item_records=[self.item_record],
                    repo_root=self.repo_root,
                    receipt_recoverer=lambda _root, _bindings, expected: expected,
                    config_loader=lambda start: {
                        "root": self.repo_root,
                        "brain_root": self.brain_root,
                    },
                    runner=changing_runner,
                )

                self.assertIs(
                    report["ok"],
                    change == "derived",
                )
                if change == "brain_root_swap":
                    self.assertIn(
                        "post-gate durable receipt verification failed",
                        "\n".join(report["errors"]),
                    )

    def test_unmerged_expected_ids_are_compared_as_exact_union(self):
        module = load_module()
        baseline_ids = [f"code.baseline-{number:02d}" for number in range(1, 8)]
        expected_ids = [f"code.expected-{number:02d}" for number in range(1, 31)]
        contract = dict(self.contract, expected_unmerged_locator_ids=expected_ids)
        baseline = {
            "ok": True,
            "isolated_ids": ["code.before"],
            "target_head": "TARGET",
            "unmerged_locator_ids": baseline_ids,
        }
        report = self._finalize(module,
            contract, baseline,
            runner=self._runner(unmerged_locator_ids=[*baseline_ids, *expected_ids]),
        )

        self.assertTrue(report["ok"])
        self.assertTrue(report["unmerged"]["ok"])
        self.assertEqual(report["unmerged"]["baseline_ids"], baseline_ids)
        self.assertEqual(report["unmerged"]["expected_ids"], expected_ids)
        self.assertEqual(report["unmerged"]["new_ids"], expected_ids)

        blocked = self._finalize(module,
            contract, baseline,
            runner=self._runner(unmerged_locator_ids=[*baseline_ids, *expected_ids,
                                                       "code.unexpected-31"]),
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["unmerged"]["unexpected_new_ids"], ["code.unexpected-31"])

    def test_unmerged_expected_id_already_in_baseline_passes(self):
        module = load_module()
        contract = dict(self.contract, expected_unmerged_locator_ids=["code.existing"])
        baseline = {
            "ok": True,
            "isolated_ids": ["code.before"],
            "target_head": "TARGET",
            "unmerged_locator_ids": ["code.existing"],
        }
        report = self._finalize(module,
            contract, baseline,
            runner=self._runner(unmerged_locator_ids=["code.existing"]),
        )

        self.assertTrue(report["ok"])
        self.assertEqual(report["unmerged"]["new_ids"], [])

    def test_unmerged_reports_exact_addition_disappearance_and_head_differences(self):
        module = load_module()
        baseline = {
            "ok": True,
            "isolated_ids": ["code.before"],
            "target_head": "TARGET",
            "unmerged_locator_ids": ["code.before-unmerged"],
        }
        report = self._finalize(module,
            self.contract, baseline,
            runner=self._runner(target_head="CHANGED", unmerged_locator_ids=["code.extra"]),
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["unmerged"]["resolved_ids"], ["code.before-unmerged"])
        self.assertEqual(report["unmerged"]["unexpected_new_ids"], ["code.extra"])
        self.assertEqual(report["unmerged"]["baseline_target_head"], "TARGET")
        self.assertEqual(report["unmerged"]["current_target_head"], "CHANGED")
        self.assertIn("unexpected unmerged locator ids: ['code.extra']", report["errors"])
        self.assertIn("baseline unmerged locator ids disappeared: ['code.before-unmerged']",
                      report["errors"])
        self.assertIn("target head changed: baseline=TARGET current=CHANGED", report["errors"])

    def test_audit_failure_blocks_even_when_other_gates_pass(self):
        module = load_module()
        report = self._finalize(module,
            self.contract,
            {"ok": True, "isolated_ids": ["code.before"], "target_head": "TARGET",
             "unmerged_locator_ids": []},
            runner=self._runner(failures=("project-brain audit --no-fetch",)),
        )

        self.assertFalse(report["ok"])
        self.assertFalse(report["commands"]["audit"]["ok"])
        self.assertIn("audit failed", report["errors"])

    def test_unavailable_audit_state_does_not_fabricate_unmerged_differences(self):
        module = load_module()
        baseline = {
            "ok": True,
            "isolated_ids": ["code.before"],
            "target_head": "TARGET",
            "unmerged_locator_ids": ["code.before-unmerged"],
        }
        report = self._finalize(module,
            self.contract, baseline,
            runner=self._runner(
                failures=("project-brain audit --no-fetch",),
                audit_payload={"ok": False, "stale": {"error": "git state unavailable"}},
            ),
        )

        self.assertFalse(report["ok"])
        self.assertFalse(report["unmerged"]["current_state_available"])
        self.assertIsNone(report["unmerged"]["current_ids"])
        self.assertIsNone(report["unmerged"]["new_ids"])
        self.assertIsNone(report["unmerged"]["resolved_ids"])
        self.assertIsNone(report["unmerged"]["current_target_head"])
        self.assertNotIn("baseline unmerged locator ids disappeared", "\n".join(report["errors"]))
        self.assertNotIn("target head changed", "\n".join(report["errors"]))
        self.assertIn("audit stale error: git state unavailable", report["errors"])

    def test_non_not_ancestor_reasons_make_entire_audit_state_unavailable(self):
        module = load_module()
        baseline = {
            "ok": True,
            "isolated_ids": ["code.before"],
            "target_head": "TARGET",
            "unmerged_locator_ids": ["code.before-unmerged"],
        }
        contract = dict(
            self.contract,
            expected_unmerged_locator_ids=["code.expected-unmerged"],
        )
        cases = {
            "unverifiable": (
                [{"locator_id": "code.unknown", "reason": "anchor_unverifiable"}],
                "reason=anchor_unverifiable locator_id=code.unknown",
            ),
            "mixed": (
                [
                    {"locator_id": "code.work", "reason": "not_ancestor"},
                    {"locator_id": "code.unknown", "reason": "anchor_unverifiable"},
                ],
                "reason=anchor_unverifiable locator_id=code.unknown",
            ),
            "missing-reason": (
                [{"locator_id": "code.unknown"}],
                "reason=<missing> locator_id=code.unknown",
            ),
            "unknown-reason": (
                [{"locator_id": "code.unknown", "reason": "future_reason"}],
                "reason=future_reason locator_id=code.unknown",
            ),
        }

        for name, (anchors, diagnostic) in cases.items():
            with self.subTest(name=name):
                report = self._finalize(module,
                    contract,
                    baseline,
                    runner=self._runner(
                        audit_payload={
                            "ok": True,
                            "stale": {
                                "target_head": "TARGET",
                                "unmerged_anchors": anchors,
                            },
                        },
                    ),
                )

                self.assertFalse(report["ok"])
                self.assertFalse(report["unmerged"]["current_state_available"])
                for field in (
                    "current_target_head",
                    "current_ids",
                    "new_ids",
                    "resolved_ids",
                    "missing_expected_ids",
                    "unexpected_new_ids",
                ):
                    self.assertIsNone(report["unmerged"][field], field)
                self.assertTrue(any(
                    "audit unmerged anchor state unavailable" in error
                    and diagnostic in error
                    for error in report["errors"]
                ), report["errors"])

    def test_capture_baseline_uses_graph_and_no_fetch_audit_state(self):
        module = load_module()
        baseline = module.capture_isolation_baseline(
            runner=self._runner(current_isolated=["code.before"], target_head="TARGET",
                                unmerged_locator_ids=["code.work"]),
        )

        self.assertEqual(baseline, {
            "ok": True,
            "isolated_ids": ["code.before"],
            "target_head": "TARGET",
            "unmerged_locator_ids": ["code.work"],
        })

    def test_legacy_baseline_is_allowed_only_without_expected_unmerged_ids(self):
        module = load_module()
        legacy = {"ok": True, "isolated_ids": ["code.before"]}
        allowed = self._finalize(module, self.contract, legacy, runner=self._runner())
        self.assertTrue(allowed["ok"])

        calls = []
        contract = dict(self.contract, expected_unmerged_locator_ids=["code.new"])
        with self.assertRaisesRegex(ValueError, "Git baseline"):
            self._finalize(module, contract, legacy, runner=lambda command: calls.append(command))
        self.assertEqual(calls, [])

    def test_new_isolation_is_blocking_except_declared_terminal(self):
        module = load_module()
        allowed = self._finalize(module,
            self.contract, ["code.before"],
            runner=self._runner(current_isolated=["code.before", "code.allowed"]),
        )
        blocked = self._finalize(module,
            self.contract, ["code.before"],
            runner=self._runner(current_isolated=["code.before", "code.unexpected"]),
        )

        self.assertTrue(allowed["ok"])
        self.assertEqual(allowed["isolation"]["allowed_new_ids"], ["code.allowed"])
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["isolation"]["unexpected_new_ids"], ["code.unexpected"])

    def test_recall_requires_each_expected_id_and_its_linked_code_locator(self):
        module = load_module()
        missing = self._finalize(module,
            self.contract, ["code.before"], runner=self._runner(search_results=[])
        )
        unlinked = self._finalize(module,
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

    def test_real_wrapper_accepts_single_envelope_and_batch_list_baselines(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "project-brain"
            fake.write_text("""#!/usr/bin/env python3
import json
import sys

args = sys.argv[1:]
if args[:2] == ["graph", "isolated"]:
    payload = {"ok": True, "isolated": ["code.before"]}
elif args[:1] == ["search"]:
    payload = {"ok": True, "results": [{
        "object_id": "mapping.a",
        "linked": {"code_locators": [{"object_id": "code.a"}]},
    }]}
elif args[:2] == ["index", "rebuild"]:
    payload = {"ok": True, "indexed": 1}
elif args[:1] == ["lint"]:
    payload = {"ok": True, "problems": []}
elif args[:1] == ["eval"]:
    payload = {"ok": True, "summary": {"failed": 0}}
elif args[:1] == ["audit"]:
    payload = {"ok": True, "stale": {"target_head": "TARGET", "unmerged_anchors": []}}
else:
    payload = {"ok": False, "error": f"unexpected command: {args}"}
print(json.dumps(payload))
raise SystemExit(0 if payload["ok"] else 1)
""", encoding="utf-8")
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            checks = root / "{{BRAIN_ROOT}}" / "checks"
            checks.mkdir(parents=True)
            (checks / "test_corpus.py").write_text("""import unittest


class CorpusCheck(unittest.TestCase):
    def test_fixture_passes(self):
        self.assertTrue(True)
""", encoding="utf-8")
            config = root / "config.json"
            config.write_text(json.dumps(self.contract), encoding="utf-8")
            transactions = root / "transactions.json"
            transactions.write_text(json.dumps([TRANSACTION]), encoding="utf-8")
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

            for name, baseline in (
                ("single-envelope", {"ok": True, "isolated_ids": ["code.before"]}),
                ("batch-list", ["code.before"]),
            ):
                with self.subTest(name=name):
                    baseline_path = root / f"{name}.json"
                    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
                    result = subprocess.run(
                        [str(WRAPPER), "--config", str(config),
                         "--baseline", str(baseline_path),
                         "--transactions", str(transactions)],
                        cwd=root, env=env, text=True, capture_output=True, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
                    self.assertTrue(json.loads(result.stdout)["ok"])

    def test_invalid_baseline_envelopes_fail_before_commands(self):
        module = load_module()
        invalid = (
            {},
            {"ok": False, "isolated_ids": []},
            {"ok": True, "isolated_ids": [], "extra": True},
            {"ok": True, "isolated_ids": [""]},
            {"ok": True, "isolated_ids": ["code.a", "code.a"]},
            [""],
            ["code.a", "code.a"],
        )
        for baseline in invalid:
            calls = []
            with self.subTest(baseline=baseline), self.assertRaises(ValueError):
                self._finalize(module,
                    self.contract, baseline,
                    runner=lambda command: calls.append(command),
                )
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
