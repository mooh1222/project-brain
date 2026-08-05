from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from project_brain.corpus_io import recover_committed_receipt
from project_brain.mutation import (
    MutationOperation,
    MutationRequest,
    MutationService,
)
from project_brain.objbase import base
from project_brain.transaction_receipt import BatchBinding


SCRIPT = Path(__file__).with_name("finalize_ingest.py")
WRAPPER = Path(__file__).with_name("finalize_ingest.sh")
TRANSACTION = {
    "version": 1,
    "receipt_id": "ddbb23d71949730119dec1aef3ad7781a9a30b9414f60ff48865c8d7fa73c427",
    "ok": True,
    "outcome": "committed",
    "transaction_id": "1" * 64,
    "operation": "ingest",
    "committed": True,
    "manifest_sha256": "2" * 64,
    "coverage_sha256": "5" * 64,
    "expected_objects": [{"id": "mapping.a", "kind": "DomainMapping"}],
    "verified_objects": [{"id": "mapping.a", "kind": "DomainMapping"}],
    "changed_objects": [
        {"action": "create", "id": "mapping.a", "kind": "DomainMapping"}
    ],
    "before_fingerprint": "3" * 64,
    "after_fingerprint": "4" * 64,
}
NO_CHANGE_TRANSACTION = {
    **TRANSACTION,
    "receipt_id": "3f1e1060ea17906d1f1a61259f3eb3b7d4947aa8998c8d15e75770ea2c0c9a13",
    "outcome": "no_changes",
    "committed": False,
    "transaction_id": None,
    "changed_objects": [],
    "after_fingerprint": TRANSACTION["before_fingerprint"],
}
BINDING = {
    "batch_manifest_sha256": "5" * 64,
    "item_key": "one",
    "item_input_fingerprint": "6" * 64,
    "verify_json_sha256": "7" * 64,
    "domain_spec_py_sha256": "8" * 64,
    "coverage_sha256": "5" * 64,
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
    "expected_objects": TRANSACTION["expected_objects"],
    "verified_objects": TRANSACTION["verified_objects"],
    "changed_objects": TRANSACTION["changed_objects"],
    "receipt": TRANSACTION,
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
        self.assertEqual(
            module.validate_transaction_results(
                [TRANSACTION, NO_CHANGE_TRANSACTION]
            ),
            [TRANSACTION, NO_CHANGE_TRANSACTION],
        )
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

    def test_finalizer_compares_expected_and_verified_per_item(self):
        module = load_module()
        bad = {**NO_CHANGE_TRANSACTION, "verified_objects": []}

        with self.assertRaisesRegex(
            ValueError,
            "expected_objects.*verified_objects",
        ):
            module.validate_transaction_results([bad])

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

        def recoverer(
            brain_root,
            bindings,
            expected_receipts,
            *,
            verification_mode,
        ):
            observed.append((
                brain_root,
                bindings,
                expected_receipts,
                verification_mode,
            ))
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
        self.assertEqual(observed, [
            (*expected_call, "strict_commit"),
            (*expected_call, "post_gate_object_tail"),
        ])

    def test_receipt_recovery_uses_strict_then_post_gate_modes(self):
        module = load_module()
        observed_modes = []

        def recoverer(
            _brain_root,
            _bindings,
            expected_receipts,
            *,
            verification_mode,
        ):
            observed_modes.append(verification_mode)
            return expected_receipts

        report = module.run_finalization(
            self.contract,
            ["code.before"],
            item_records=[self.item_record],
            repo_root=self.repo_root,
            receipt_recoverer=recoverer,
            config_loader=lambda _start: {
                "root": self.repo_root,
                "brain_root": self.brain_root,
            },
            runner=self._runner(),
        )

        self.assertTrue(report["ok"])
        self.assertEqual(
            observed_modes,
            ["strict_commit", "post_gate_object_tail"],
        )

    def test_normal_index_output_passes_real_post_gate_receipt_recovery(self):
        module = load_module()
        (self.repo_root / ".project-brain.json").write_text(
            "{}\n",
            encoding="utf-8",
        )
        stamp = "2026-07-29T00:00:00+09:00"
        obj = base({
            "id": "context.post-gate-index",
            "kind": "DomainContext",
            "status": "reviewed",
            "truth_role": "domain",
            "title": "post gate index",
            "context_key": "post-gate-index",
            "project_id": "fixture",
            "display_name": "post gate index",
            "boundary_summary": "post gate index",
            "in_scope": ["fixture"],
            "out_of_scope": ["other"],
            "injection_profile": {"default_audience": "coding-agent"},
            "glossary_term_ids": [],
        }, tags=["fixture"], created_at=stamp, updated_at=stamp)
        from project_brain.coverage import normalize_coverage

        coverage = {
            "version": 1,
            "mode": "direct",
            "objects": [{"id": obj["id"], "kind": obj["kind"]}],
        }
        binding = BatchBinding(**{
            **self.binding,
            "coverage_sha256": normalize_coverage(coverage).sha256,
        })
        result = MutationService().apply(
            (obj,),
            request=MutationRequest(
                operation=MutationOperation.INGEST,
                brain_root=self.brain_root,
                repo_context=None,
                engine_sha=binding.engine_sha,
                objects=(obj,),
                batch_binding=binding,
                coverage=coverage,
            ),
        )
        self.assertTrue(result.ok, result.detail)
        receipt = recover_committed_receipt(self.brain_root, binding)
        record = {
            "binding": asdict(binding),
            "status": "committed",
            "failure": None,
            "expected_objects": receipt["expected_objects"],
            "verified_objects": receipt["verified_objects"],
            "changed_objects": receipt["changed_objects"],
            "receipt": receipt,
        }
        runner = self._runner()

        def indexing_runner(command):
            if command[:3] == ["project-brain", "index", "rebuild"]:
                local = self.brain_root / ".brain-local"
                local.mkdir(exist_ok=True)
                (local / "index.db").write_bytes(b"normal index output")
            return runner(command)

        report = module.run_finalization(
            self.contract,
            ["code.before"],
            item_records=[record],
            repo_root=self.repo_root,
            runner=indexing_runner,
        )

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["transactions"], [receipt])

    def test_config_loader_non_system_exception_is_normalized(self):
        module = load_module()

        with self.assertRaisesRegex(
            ValueError,
            "receipt verification config loading failed",
        ):
            module.recover_item_record_transactions(
                [self.item_record],
                repo_root=self.repo_root,
                config_loader=lambda _start: (_ for _ in ()).throw(
                    RuntimeError("broken config loader")
                ),
            )
        for system_error in (KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(system_error=type(system_error).__name__):
                with self.assertRaises(type(system_error)):
                    module.recover_item_record_transactions(
                        [self.item_record],
                        repo_root=self.repo_root,
                        config_loader=lambda _start, error=system_error: (
                            _ for _ in ()
                        ).throw(error),
                    )

    def test_main_malformed_top_level_project_config_returns_json_error(self):
        config_path = self.repo_root / "finalization.json"
        baseline_path = self.repo_root / "baseline.json"
        records_path = self.repo_root / "item-records.json"
        config_path.write_text(
            json.dumps(self.contract),
            encoding="utf-8",
        )
        baseline_path.write_text(
            json.dumps(["code.before"]),
            encoding="utf-8",
        )
        records_path.write_text(
            json.dumps([self.item_record]),
            encoding="utf-8",
        )
        (self.repo_root / ".project-brain.json").write_text(
            "[]\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--config",
                str(config_path),
                "--baseline",
                str(baseline_path),
                "--item-records",
                str(records_path),
                "--repo-root",
                str(self.repo_root),
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(set(payload), {
            "ok",
            "transactions",
            "commands",
            "isolation",
            "unmerged",
            "recall_checks",
            "errors",
        })
        self.assertFalse(payload["ok"])
        self.assertIn(
            "receipt verification config loading failed",
            "\n".join(payload["errors"]),
        )

    def test_item_record_forgery_or_noncommitted_state_blocks_before_commands(self):
        module = load_module()
        cases = (
            [{
                **self.item_record,
                "status": "pending",
                "verified_objects": [],
                "changed_objects": [],
                "receipt": None,
            }],
            [{
                **self.item_record,
                "receipt": {**TRANSACTION, "manifest_sha256": "f" * 64},
            }],
        )
        for records in cases:
            calls = []
            with self.subTest(records=records), self.assertRaises(ValueError):
                module.run_finalization(
                    self.contract,
                    ["code.before"],
                    item_records=records,
                    repo_root=self.repo_root,
                    receipt_recoverer=lambda _root, _bindings, _expected, **_kwargs: (
                        TRANSACTION,
                    ),
                    config_loader=lambda start: {
                        "root": self.repo_root,
                        "brain_root": self.brain_root,
                    },
                    runner=lambda command: calls.append(command),
                )
            self.assertEqual(calls, [])

    def test_item_record_rejects_per_item_expected_mismatch(self):
        module = load_module()
        forged = {
            **self.item_record,
            "expected_objects": [
                {"id": "mapping.other", "kind": "DomainMapping"}
            ],
        }

        with self.assertRaisesRegex(ValueError, r"item records\[0\].*expected_objects"):
            module.validate_item_records([forged])

    def test_pending_item_record_rejects_malformed_saved_expected_as_value_error(self):
        module = load_module()
        malformed = {
            **self.item_record,
            "status": "pending",
            "failure": None,
            "expected_objects": [{"id": "mapping.a"}],
            "verified_objects": [],
            "changed_objects": [],
            "receipt": None,
        }

        with self.assertRaisesRegex(ValueError, "expected_objects"):
            module.validate_item_records([malformed])

    def test_receipt_chain_is_revalidated_after_semantic_commands(self):
        module = load_module()
        recover_calls = 0
        commands = []

        def recoverer(
            _brain_root,
            _bindings,
            expected_receipts,
            **_kwargs,
        ):
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
                    receipt_recoverer=lambda _root, _bindings, expected, **_kwargs: (
                        expected
                    ),
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
