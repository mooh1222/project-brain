#!/usr/bin/env python3
"""P0 foundation baseline, 비변이 gate, snapshot handoff wrapper."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from project_brain.foundation import (
    FoundationError,
    atomic_create_bound_receipt,
    build_foundation_handoff,
    capture_foundation_baseline,
    run_foundation_gate,
    validate_p0_project_config,
    verify_artifact_inventory,
)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--engine-root", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--brain-root", required=True)
    parser.add_argument("--artifact-root", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="validate_foundation.py")
    actions = parser.add_subparsers(dest="action", required=True)

    baseline = actions.add_parser("baseline")
    _common(baseline)
    baseline.add_argument("--output", required=True)
    baseline.add_argument("--binding-output", required=True)

    verify = actions.add_parser("verify")
    _common(verify)
    verify.add_argument("--baseline", required=True)
    verify.add_argument("--baseline-binding", required=True)
    verify.add_argument("--install-report-1", required=True)
    verify.add_argument("--install-report-2", required=True)
    verify.add_argument("--output", required=True)
    verify.add_argument("--binding-output", required=True)

    handoff = actions.add_parser("handoff")
    _common(handoff)
    handoff.add_argument("--baseline", required=True)
    handoff.add_argument("--baseline-binding", required=True)
    handoff.add_argument("--gate", required=True)
    handoff.add_argument("--gate-binding", required=True)
    handoff.add_argument("--snapshot-root", required=True)
    handoff.add_argument("--snapshot-create-receipt", required=True)
    handoff.add_argument("--snapshot-verify-receipt", required=True)
    handoff.add_argument("--output", required=True)
    return parser


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    return (
        Path(args.engine_root),
        Path(args.repo_root),
        Path(args.brain_root),
        Path(args.artifact_root),
    )


def _run(args: argparse.Namespace) -> dict[str, object]:
    engine_root, repo_root, brain_root, artifact_root = _paths(args)
    ignored_snapshots_root = repo_root / ".snapshots"
    if args.action == "baseline":
        validate_p0_project_config(repo_root)
        receipt = capture_foundation_baseline(
            engine_root=engine_root,
            repo_root=repo_root,
            brain_root=brain_root,
            artifact_root=artifact_root,
            ignored_snapshots_root=ignored_snapshots_root,
        )
        output = Path(args.output)
        binding = Path(args.binding_output)
        atomic_create_bound_receipt(
            receipt_path=output,
            binding_path=binding,
            value=receipt,
        )
        verify_artifact_inventory(
            artifact_root,
            allowed_files=(output, binding),
        )
        return receipt

    if args.action == "verify":
        report = run_foundation_gate(
            engine_root=engine_root,
            repo_root=repo_root,
            brain_root=brain_root,
            artifact_root=artifact_root,
            baseline_path=Path(args.baseline),
            baseline_binding_path=Path(args.baseline_binding),
            install_report_1_path=Path(args.install_report_1),
            install_report_2_path=Path(args.install_report_2),
        )
        if not report["ok"]:
            return report
        output = Path(args.output)
        binding = Path(args.binding_output)
        atomic_create_bound_receipt(
            receipt_path=output,
            binding_path=binding,
            value=report,
        )
        verify_artifact_inventory(
            artifact_root,
            allowed_files=(
                Path(args.baseline),
                Path(args.baseline_binding),
                Path(args.install_report_1),
                Path(args.install_report_2),
                output,
                binding,
            ),
        )
        return report

    return build_foundation_handoff(
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        artifact_root=artifact_root,
        baseline_path=Path(args.baseline),
        baseline_binding_path=Path(args.baseline_binding),
        gate_path=Path(args.gate),
        gate_binding_path=Path(args.gate_binding),
        snapshot_root=Path(args.snapshot_root),
        snapshot_create_receipt_path=Path(args.snapshot_create_receipt),
        snapshot_verify_receipt_path=Path(args.snapshot_verify_receipt),
        output_path=Path(args.output),
    )


def main_result(argv: list[str]) -> tuple[int, dict[str, object]]:
    if not argv:
        return 2, {
            "ok": False,
            "error_code": "argument_error",
            "error": "subcommand is required",
        }
    try:
        args = _parser().parse_args(argv)
        report = _run(args)
    except SystemExit as exc:
        return int(exc.code or 2), {
            "ok": False,
            "error_code": "argument_error",
            "error": "invalid foundation arguments",
        }
    except FoundationError as exc:
        return 1, {
            "ok": False,
            "error_code": exc.code,
            "error": exc.detail,
        }
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return 1, {
            "ok": False,
            "error_code": "foundation_runtime_error",
            "error": str(exc),
        }
    return (0 if report.get("ok", True) else 1), report


def main(argv: list[str] | None = None) -> int:
    rc, report = main_result(list(sys.argv[1:] if argv is None else argv))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
