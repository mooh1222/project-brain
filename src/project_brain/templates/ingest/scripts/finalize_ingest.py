#!/usr/bin/env python3
"""적재 뒤 공통 게이트를 실행하고 머신 판독 가능한 결과를 낸다."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Callable


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]
ReceiptRecoverer = Callable[
    ...,
    tuple[dict[str, Any] | None, ...],
]
_TRANSACTION_FIELDS = {
    "version",
    "receipt_id",
    "ok",
    "outcome",
    "transaction_id",
    "operation",
    "committed",
    "manifest_sha256",
    "coverage_sha256",
    "expected_objects",
    "verified_objects",
    "changed_objects",
    "before_fingerprint",
    "after_fingerprint",
}
_CHANGED_ACTION_ORDER = {
    "create": 0,
    "update": 1,
    "delete": 2,
    "rename": 3,
}


def _normalize_identity_rows(value: Any, field: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError(f"{field}는 배열이어야 합니다")
    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(value):
        if (
            not isinstance(raw, dict)
            or set(raw) != {"id", "kind"}
            or not isinstance(raw.get("id"), str)
            or not raw["id"]
            or not isinstance(raw.get("kind"), str)
            or not raw["kind"]
            or raw["id"] in seen_ids
        ):
            raise ValueError(f"{field}[{index}]가 올바르지 않습니다")
        seen_ids.add(raw["id"])
        rows.append({"id": raw["id"], "kind": raw["kind"]})
    canonical = sorted(rows, key=lambda row: (row["id"], row["kind"]))
    if rows != canonical:
        raise ValueError(f"{field}가 canonical 순서가 아닙니다")
    return rows


def _normalize_changed_rows(value: Any, field: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError(f"{field}는 배열이어야 합니다")
    rows: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict):
            raise ValueError(f"{field}[{index}]가 올바르지 않습니다")
        action = raw.get("action")
        expected_fields = (
            {"action", "old_id", "new_id", "kind"}
            if action == "rename"
            else {"action", "id", "kind"}
        )
        if action not in _CHANGED_ACTION_ORDER or set(raw) != expected_fields:
            raise ValueError(f"{field}[{index}] 필드가 올바르지 않습니다")
        if any(
            not isinstance(raw.get(name), str) or not raw[name]
            for name in expected_fields
        ):
            raise ValueError(f"{field}[{index}] 값이 올바르지 않습니다")
        row = {name: raw[name] for name in raw}
        identity = tuple(sorted(row.items()))
        if identity in seen:
            raise ValueError(f"{field}에 중복 행이 있습니다")
        seen.add(identity)
        rows.append(row)

    def sort_key(row: dict[str, str]) -> tuple[object, ...]:
        action = row["action"]
        suffix = (
            (row["old_id"], row["new_id"], row["kind"])
            if action == "rename"
            else (row["id"], row["kind"])
        )
        return (_CHANGED_ACTION_ORDER[action], *suffix)

    canonical = sorted(rows, key=sort_key)
    if rows != canonical:
        raise ValueError(f"{field}가 canonical 순서가 아닙니다")
    return rows


def _string_list(value: Any, field: str, *, nonempty: bool = False) -> list[str]:
    if (not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            or len(value) != len(set(value))
            or (nonempty and not value)):
        suffix = " 비어 있지 않은" if nonempty else ""
        raise ValueError(f"{field}는 중복 없는{suffix} 문자열 배열이어야 합니다")
    return list(value)


def validate_contract(contract: Any) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise ValueError("finalization은 객체여야 합니다")
    allowed_fields = {"recall_checks", "intentional_terminal_ids", "expected_unmerged_locator_ids"}
    if set(contract) not in (allowed_fields, allowed_fields - {"expected_unmerged_locator_ids"}):
        raise ValueError("finalization 필드는 recall_checks, intentional_terminal_ids, "
                         "expected_unmerged_locator_ids만 허용합니다")
    raw_checks = contract.get("recall_checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        raise ValueError("finalization.recall_checks는 최소 1개여야 합니다")
    keys: set[str] = set()
    checks = []
    for index, raw in enumerate(raw_checks):
        if not isinstance(raw, dict):
            raise ValueError(f"recall_checks[{index}]는 객체여야 합니다")
        if set(raw) != {"key", "query", "expected_object_ids", "require_code_locators"}:
            raise ValueError(f"recall_checks[{index}] 필드가 정확하지 않습니다")
        key = raw.get("key")
        query = raw.get("query")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError(f"recall_checks[{index}].key가 없거나 중복입니다")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"recall_checks[{index}].query가 없습니다")
        keys.add(key)
        expected = _string_list(raw.get("expected_object_ids"),
                                f"recall_checks[{index}].expected_object_ids", nonempty=True)
        require_code = raw.get("require_code_locators", True)
        if not isinstance(require_code, bool):
            raise ValueError(f"recall_checks[{index}].require_code_locators는 bool이어야 합니다")
        checks.append({
            "key": key,
            "query": query,
            "expected_object_ids": expected,
            "require_code_locators": require_code,
        })
    terminals = _string_list(contract.get("intentional_terminal_ids", []),
                             "finalization.intentional_terminal_ids")
    expected_unmerged = _string_list(contract.get("expected_unmerged_locator_ids", []),
                                     "finalization.expected_unmerged_locator_ids")
    return {"recall_checks": checks, "intentional_terminal_ids": terminals,
            "expected_unmerged_locator_ids": expected_unmerged}


def validate_transaction_results(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("transaction results는 비어 있지 않은 배열이어야 합니다")
    normalized: list[dict[str, Any]] = []
    receipt_ids: set[str] = set()
    for index, raw in enumerate(value):
        prefix = f"transaction results[{index}]"
        if not isinstance(raw, dict) or set(raw) != _TRANSACTION_FIELDS:
            raise ValueError(f"{prefix} 필드가 정확하지 않습니다")
        try:
            from project_brain.transaction_receipt import mutation_receipt_dict

            receipt = mutation_receipt_dict(raw)
        except ValueError as exc:
            raise ValueError(f"{prefix} receipt가 올바르지 않습니다: {exc}") from exc
        if receipt.get("operation") != "ingest":
            raise ValueError(f"{prefix}.operation은 ingest여야 합니다")
        receipt_id = str(receipt["receipt_id"])
        if receipt_id in receipt_ids:
            raise ValueError(f"{prefix}.receipt_id가 중복입니다")
        receipt_ids.add(receipt_id)
        normalized.append(receipt)
    return normalized


def validate_item_records(value: Any) -> list[dict[str, Any]]:
    """Validate the authoritative batch records before journal recovery."""
    from project_brain.transaction_receipt import (
        batch_binding_dict,
        normalize_batch_binding,
    )

    if not isinstance(value, list) or not value:
        raise ValueError("item records는 비어 있지 않은 배열이어야 합니다")
    normalized: list[dict[str, Any]] = []
    item_keys: set[str] = set()
    for index, raw in enumerate(value):
        prefix = f"item records[{index}]"
        if (
            not isinstance(raw, dict)
            or set(raw) != {
                "binding",
                "status",
                "failure",
                "expected_objects",
                "verified_objects",
                "changed_objects",
                "receipt",
            }
        ):
            raise ValueError(f"{prefix} 필드가 정확하지 않습니다")
        binding = normalize_batch_binding(raw.get("binding"))
        assert binding is not None
        binding_payload = batch_binding_dict(binding)
        assert binding_payload is not None
        if binding.item_key in item_keys:
            raise ValueError(f"{prefix}.binding.item_key가 중복입니다")
        item_keys.add(binding.item_key)
        status = raw.get("status")
        if status not in {"pending", "failed", "committed", "no_changes"}:
            raise ValueError(f"{prefix}.status가 올바르지 않습니다")
        expected_objects = _normalize_identity_rows(
            raw.get("expected_objects"),
            f"{prefix}.expected_objects",
        )
        verified_objects = _normalize_identity_rows(
            raw.get("verified_objects"),
            f"{prefix}.verified_objects",
        )
        changed_objects = _normalize_changed_rows(
            raw.get("changed_objects"),
            f"{prefix}.changed_objects",
        )
        failure = raw.get("failure")
        receipt = raw.get("receipt")
        normalized_receipt: dict[str, Any] | None = None
        if status == "pending":
            valid_state = (
                failure is None
                and receipt is None
                and verified_objects == []
                and changed_objects == []
            )
        elif status == "failed":
            valid_state = (
                isinstance(failure, dict)
                and set(failure) == {"exit_code", "stderr"}
                and isinstance(failure.get("exit_code"), int)
                and not isinstance(failure.get("exit_code"), bool)
                and isinstance(failure.get("stderr"), str)
                and receipt is None
                and verified_objects == []
                and changed_objects == []
            )
        else:
            try:
                normalized_receipt = validate_transaction_results([receipt])[0]
            except ValueError as exc:
                raise ValueError(f"{prefix}.receipt가 올바르지 않습니다: {exc}") from exc
            valid_state = (
                failure is None
                and normalized_receipt["outcome"] == status
                and normalized_receipt["coverage_sha256"]
                == binding_payload["coverage_sha256"]
                and normalized_receipt["expected_objects"] == expected_objects
                and normalized_receipt["verified_objects"] == verified_objects
                and normalized_receipt["changed_objects"] == changed_objects
            )
        if not valid_state:
            raise ValueError(
                f"{prefix} status/expected_objects/verified_objects/"
                "changed_objects/receipt invariant가 맞지 않습니다"
            )
        normalized.append({
            "binding": binding_payload,
            "status": status,
            "failure": None if failure is None else dict(failure),
            "expected_objects": [dict(row) for row in expected_objects],
            "verified_objects": [dict(row) for row in verified_objects],
            "changed_objects": [dict(row) for row in changed_objects],
            "receipt": normalized_receipt,
        })
    return normalized


def _default_config_loader(start: Path) -> dict[str, Any] | None:
    from project_brain.config import load_config

    return load_config(start=start)


def _default_receipt_recoverer(
    brain_root: Path,
    bindings: tuple[dict[str, object], ...],
    expected_receipts: tuple[dict[str, Any], ...],
    *,
    verification_mode: str,
) -> tuple[dict[str, Any] | None, ...]:
    from project_brain.corpus_io import recover_batch_receipts

    return recover_batch_receipts(
        brain_root,
        bindings,
        expected_receipts=expected_receipts,
        verification_mode=verification_mode,
    )


def recover_item_record_transactions(
    value: Any,
    *,
    repo_root: Path,
    receipt_recoverer: ReceiptRecoverer = _default_receipt_recoverer,
    config_loader: Callable[[Path], dict[str, Any] | None] = _default_config_loader,
    verification_mode: str = "strict_commit",
) -> list[dict[str, Any]]:
    """Resolve exact committed receipts from the durable intent/journal chain."""
    records = validate_item_records(value)
    if any(
        record["status"] not in {"committed", "no_changes"}
        for record in records
    ):
        raise ValueError("item records에는 terminal receipt만 허용됩니다")
    root = Path(repo_root).resolve()
    try:
        configured = config_loader(root)
    except Exception as exc:
        raise ValueError(
            "item record receipt verification config loading failed: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    try:
        config_matches = (
            isinstance(configured, dict)
            and Path(configured.get("root", "")).resolve() == root
            and isinstance(configured.get("brain_root"), Path)
        )
    except Exception as exc:
        raise ValueError(
            "item record receipt verification config is invalid: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if (
        not config_matches
    ):
        raise ValueError("item record receipt verification config is unavailable")
    assert isinstance(configured, dict)
    bindings = tuple(record["binding"] for record in records)
    brain_root = configured["brain_root"].resolve()
    try:
        brain_stat = brain_root.stat()
    except OSError as exc:
        raise ValueError(f"item record brain_root is unavailable: {exc}") from exc
    if any(
        binding.get("repo_root") != str(root)
        or binding.get("brain_root") != str(brain_root)
        or binding.get("brain_root_device") != brain_stat.st_dev
        or binding.get("brain_root_inode") != brain_stat.st_ino
        for binding in bindings
    ):
        raise ValueError("item record brain_root identity does not match config")
    expected = tuple(record["receipt"] for record in records)
    try:
        recovered = receipt_recoverer(
            brain_root,
            bindings,
            expected,
            verification_mode=verification_mode,
        )
    except Exception as exc:
        raise ValueError(f"durable receipt recovery failed: {exc}") from exc
    if len(recovered) != len(expected):
        raise ValueError("durable receipt result length mismatch")
    transactions: list[dict[str, Any]] = []
    for index, (actual, expected_receipt) in enumerate(zip(recovered, expected)):
        if actual != expected_receipt:
            raise ValueError(
                f"item records[{index}] durable receipt does not match"
            )
        transactions.append(expected_receipt)
    return transactions


def normalize_baseline(value: Any, expected_unmerged_locator_ids: Any = ()) -> dict[str, Any]:
    """새 Git baseline과 기대 미머지 ID를 검증하고, 구형 baseline은 빈 기대값만 허용한다."""
    expected = _string_list(expected_unmerged_locator_ids,
                            "finalization.expected_unmerged_locator_ids")
    if isinstance(value, dict):
        if set(value) == {"ok", "isolated_ids"}:
            if value.get("ok") is not True:
                raise ValueError("isolation baseline envelope의 ok가 true가 아닙니다")
            isolated = _string_list(value.get("isolated_ids"), "isolation baseline")
            if expected:
                raise ValueError("expected_unmerged_locator_ids에는 Git baseline envelope가 필요합니다")
            return {"ok": True, "isolated_ids": isolated, "target_head": None,
                    "unmerged_locator_ids": [], "git_baseline_available": False}
        if set(value) != {"ok", "isolated_ids", "target_head", "unmerged_locator_ids"}:
            raise ValueError("isolation baseline envelope 필드가 정확하지 않습니다")
        if value.get("ok") is not True:
            raise ValueError("isolation baseline envelope의 ok가 true가 아닙니다")
        target_head = value.get("target_head")
        if not isinstance(target_head, str) or not target_head:
            raise ValueError("isolation baseline target_head가 없습니다")
        return {"ok": True,
                "isolated_ids": _string_list(value.get("isolated_ids"), "isolation baseline"),
                "target_head": target_head,
                "unmerged_locator_ids": _string_list(value.get("unmerged_locator_ids"),
                                                      "unmerged locator baseline"),
                "git_baseline_available": True}
    isolated = _string_list(value, "isolation baseline")
    if expected:
        raise ValueError("expected_unmerged_locator_ids에는 Git baseline envelope가 필요합니다")
    return {"ok": True, "isolated_ids": isolated, "target_head": None,
            "unmerged_locator_ids": [], "git_baseline_available": False}


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else str(value)


def _run_command(runner: CommandRunner, command: list[str], *, json_output: bool) -> dict:
    try:
        completed = runner(command)
        exit_code = completed.returncode
        stdout = _text(completed.stdout)
        stderr = _text(completed.stderr)[-2000:]
    except Exception as exc:
        return {"ok": False, "exit_code": 1, "payload": None, "stderr": str(exc)[-2000:]}
    payload: Any = None
    parse_ok = True
    if json_output:
        try:
            payload = json.loads(stdout)
        except (TypeError, json.JSONDecodeError):
            parse_ok = False
        payload_ok = isinstance(payload, dict) and payload.get("ok") is True
    else:
        payload = {"stdout": stdout[-2000:]}
        payload_ok = True
    ok = (isinstance(exit_code, int) and not isinstance(exit_code, bool)
          and exit_code == 0 and parse_ok and payload_ok)
    return {"ok": ok, "exit_code": exit_code if isinstance(exit_code, int) else 1,
            "payload": payload, "stderr": stderr}


def _audit_git_state(result: dict) -> tuple[dict[str, Any] | None, str]:
    """audit JSON의 실제 stale 출력에서 target head와 미머지 CodeLocator ID를 읽는다."""
    payload = result.get("payload")
    stale = payload.get("stale") if isinstance(payload, dict) else None
    stale_error = stale.get("error") if isinstance(stale, dict) else None
    if isinstance(stale_error, str) and stale_error:
        return None, f"audit stale error: {stale_error}"
    target_head = stale.get("target_head") if isinstance(stale, dict) else None
    anchors = stale.get("unmerged_anchors") if isinstance(stale, dict) else None
    if not isinstance(target_head, str) or not target_head or not isinstance(anchors, list):
        return None, "audit stale state unavailable"
    locator_ids = []
    for anchor in anchors:
        locator_id = anchor.get("locator_id") if isinstance(anchor, dict) else None
        reason = anchor.get("reason") if isinstance(anchor, dict) else None
        if reason != "not_ancestor":
            reason_text = "<missing>" if reason is None else str(reason)
            locator_text = "<missing>" if locator_id is None else str(locator_id)
            return None, (
                "audit unmerged anchor state unavailable: "
                f"reason={reason_text} locator_id={locator_text}"
            )
        if not isinstance(locator_id, str) or not locator_id:
            return None, (
                "audit unmerged anchor state unavailable: "
                "reason=not_ancestor locator_id=<invalid>"
            )
        locator_ids.append(locator_id)
    if len(locator_ids) != len(set(locator_ids)):
        return None, "audit stale state unavailable"
    return {"target_head": target_head, "unmerged_locator_ids": sorted(locator_ids)}, ""


def capture_isolation_baseline(runner: CommandRunner = _default_runner) -> dict:
    result = _run_command(runner, ["project-brain", "graph", "isolated"], json_output=True)
    audit = _run_command(
        runner,
        ["project-brain", "audit", "--no-fetch", "--write-stale-cache"],
        json_output=True,
    )
    payload = result.get("payload")
    isolated = payload.get("isolated") if isinstance(payload, dict) else None
    if (not result["ok"] or not isinstance(isolated, list)
            or any(not isinstance(item, str) for item in isolated)):
        return {"ok": False, "isolated_ids": [], "error": result["stderr"] or "고립 baseline 수집 실패"}
    git_state, audit_diagnostic = _audit_git_state(audit)
    if not audit["ok"] or git_state is None:
        return {"ok": False, "isolated_ids": [],
                "error": audit_diagnostic or audit["stderr"] or "Git baseline 수집 실패"}
    return {"ok": True, "isolated_ids": sorted(set(isolated)),
            "target_head": git_state["target_head"],
            "unmerged_locator_ids": git_state["unmerged_locator_ids"]}


def run_finalization(
    contract: Any,
    baseline_ids: Any,
    transaction_results: Any = None,
    runner: CommandRunner = _default_runner,
    *,
    item_records: Any = None,
    repo_root: Path | None = None,
    receipt_recoverer: ReceiptRecoverer = _default_receipt_recoverer,
    config_loader: Callable[[Path], dict[str, Any] | None] = _default_config_loader,
) -> dict:
    config = validate_contract(contract)
    if item_records is not None:
        if transaction_results is not None or repo_root is None:
            raise ValueError(
                "item records에는 repo_root가 필요하며 transaction results와 함께 쓸 수 없습니다"
            )
        transactions = recover_item_record_transactions(
            item_records,
            repo_root=repo_root,
            receipt_recoverer=receipt_recoverer,
            config_loader=config_loader,
        )
    else:
        transactions = validate_transaction_results(transaction_results)
    baseline = normalize_baseline(baseline_ids, config["expected_unmerged_locator_ids"])
    commands = {
        "index_rebuild": _run_command(
            runner, ["project-brain", "index", "rebuild"], json_output=True),
        "lint": _run_command(runner, ["project-brain", "lint"], json_output=True),
        "eval": _run_command(runner, ["project-brain", "eval"], json_output=True),
        "graph_isolated": _run_command(
            runner, ["project-brain", "graph", "isolated"], json_output=True),
        "audit": _run_command(
            runner,
            ["project-brain", "audit", "--no-fetch", "--write-stale-cache"],
            json_output=True,
        ),
        "corpus_tests": _run_command(
            runner,
            ["python3", "-m", "unittest", "discover", "-s", "{{BRAIN_ROOT}}/checks",
             "-p", "test_*.py"],
            json_output=False),
    }
    errors = [f"{name} failed" for name, result in commands.items() if not result["ok"]]

    graph_payload = commands["graph_isolated"]["payload"]
    raw_current = graph_payload.get("isolated", []) if isinstance(graph_payload, dict) else []
    if (not isinstance(raw_current, list)
            or any(not isinstance(item, str) or not item for item in raw_current)):
        commands["graph_isolated"]["ok"] = False
        errors.append("graph_isolated payload failed")
        raw_current = []
    current = sorted(set(item for item in raw_current if isinstance(item, str)))
    baseline_set = set(baseline["isolated_ids"])
    new_ids = sorted(set(current) - baseline_set)
    terminal_set = set(config["intentional_terminal_ids"])
    allowed = sorted(set(new_ids) & terminal_set)
    unexpected = sorted(set(new_ids) - terminal_set)
    isolation_ok = commands["graph_isolated"]["ok"] and not unexpected
    isolation = {
        "ok": isolation_ok,
        "baseline_ids": sorted(baseline_set),
        "current_ids": current,
        "new_ids": new_ids,
        "intentional_terminal_ids": sorted(terminal_set),
        "allowed_new_ids": allowed,
        "unexpected_new_ids": unexpected,
    }
    if unexpected:
        errors.append(f"unexpected isolated ids: {unexpected}")

    audit_state, audit_diagnostic = _audit_git_state(commands["audit"])
    if audit_state is None:
        commands["audit"]["ok"] = False
        errors.append(audit_diagnostic)
        current_unmerged: set[str] | None = None
        current_target_head = None
    else:
        current_unmerged = set(audit_state["unmerged_locator_ids"])
        current_target_head = audit_state["target_head"]
    baseline_unmerged = set(baseline["unmerged_locator_ids"])
    expected_unmerged = set(config["expected_unmerged_locator_ids"])
    expected_current = baseline_unmerged | expected_unmerged
    if current_unmerged is None:
        new_unmerged = None
        resolved_unmerged = None
        missing_expected = None
        unexpected_unmerged = None
        target_head_changed = False
    else:
        new_unmerged = sorted(current_unmerged - baseline_unmerged)
        resolved_unmerged = sorted(baseline_unmerged - current_unmerged)
        missing_expected = sorted(expected_unmerged - current_unmerged)
        unexpected_unmerged = sorted(current_unmerged - expected_current)
        target_head_changed = (baseline["git_baseline_available"]
                               and current_target_head != baseline["target_head"])
    unmerged_ok = commands["audit"]["ok"] and audit_state is not None
    if baseline["git_baseline_available"] and current_unmerged is not None:
        unmerged_ok = (unmerged_ok and not resolved_unmerged and not missing_expected
                       and not unexpected_unmerged and not target_head_changed)
        if unexpected_unmerged:
            errors.append(f"unexpected unmerged locator ids: {unexpected_unmerged}")
        if resolved_unmerged:
            errors.append(f"baseline unmerged locator ids disappeared: {resolved_unmerged}")
        if missing_expected:
            errors.append(f"expected unmerged locator ids missing: {missing_expected}")
        if target_head_changed:
            errors.append("target head changed: "
                          f"baseline={baseline['target_head']} current={current_target_head}")
    unmerged = {
        "ok": unmerged_ok,
        "baseline_ids": sorted(baseline_unmerged),
        "current_state_available": current_unmerged is not None,
        "current_ids": sorted(current_unmerged) if current_unmerged is not None else None,
        "expected_ids": sorted(expected_unmerged),
        "new_ids": new_unmerged,
        "resolved_ids": resolved_unmerged,
        "missing_expected_ids": missing_expected,
        "unexpected_new_ids": unexpected_unmerged,
        "baseline_target_head": baseline["target_head"],
        "current_target_head": current_target_head,
    }

    recall_reports = []
    for check in config["recall_checks"]:
        command_result = _run_command(
            runner, ["project-brain", "search", check["query"]], json_output=True)
        payload = command_result["payload"]
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        by_id = {hit.get("object_id"): hit for hit in raw_results if isinstance(hit, dict)}
        expected = check["expected_object_ids"]
        found = [object_id for object_id in expected if object_id in by_id]
        missing = [object_id for object_id in expected if object_id not in by_id]
        missing_code = []
        if check["require_code_locators"]:
            for object_id in found:
                linked = by_id[object_id].get("linked")
                locators = linked.get("code_locators") if isinstance(linked, dict) else None
                if not isinstance(locators, list) or not locators:
                    missing_code.append(object_id)
        ok = command_result["ok"] and not missing and not missing_code
        recall_reports.append({
            "key": check["key"],
            "query": check["query"],
            "expected_object_ids": expected,
            "found_object_ids": found,
            "missing_object_ids": missing,
            "missing_code_locator_object_ids": missing_code,
            "ok": ok,
        })
        if not ok:
            errors.append(f"recall check failed: {check['key']}")

    if item_records is not None:
        try:
            post_gate_transactions = recover_item_record_transactions(
                item_records,
                repo_root=repo_root,
                receipt_recoverer=receipt_recoverer,
                config_loader=config_loader,
                verification_mode="post_gate_object_tail",
            )
            if post_gate_transactions != transactions:
                raise ValueError("recovered transactions changed")
        except Exception as exc:
            errors.append(
                f"post-gate durable receipt verification failed: {exc}"
            )

    return {"ok": not errors, "transactions": transactions,
            "commands": commands, "isolation": isolation,
            "unmerged": unmerged,
            "recall_checks": recall_reports, "errors": errors}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON을 읽을 수 없습니다: {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="semantic ingest finalization")
    parser.add_argument("--capture-baseline", action="store_true")
    parser.add_argument("--validate-config", type=Path)
    parser.add_argument("--validate-transaction", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--transactions", type=Path)
    parser.add_argument("--transaction-result", type=Path)
    parser.add_argument("--item-records", type=Path)
    parser.add_argument("--repo-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.validate_config is not None:
            if (args.capture_baseline or args.config is not None
                    or args.baseline is not None or args.transactions is not None
                    or args.transaction_result is not None
                    or args.item_records is not None or args.repo_root is not None
                    or args.validate_transaction is not None):
                raise ValueError("--validate-config은 다른 모드 인자와 함께 쓸 수 없습니다")
            validate_contract(_read_json(args.validate_config))
            report = {"ok": True, "validated": True}
        elif args.validate_transaction is not None:
            if (args.capture_baseline or args.config is not None
                    or args.baseline is not None or args.transactions is not None
                    or args.transaction_result is not None
                    or args.item_records is not None or args.repo_root is not None):
                raise ValueError("--validate-transaction은 다른 모드 인자와 함께 쓸 수 없습니다")
            validate_transaction_results([_read_json(args.validate_transaction)])
            report = {"ok": True, "validated_transactions": 1}
        elif args.capture_baseline:
            if (args.config is not None or args.baseline is not None
                    or args.transactions is not None or args.transaction_result is not None
                    or args.item_records is not None or args.repo_root is not None):
                raise ValueError("--capture-baseline은 다른 인자와 함께 쓸 수 없습니다")
            report = capture_isolation_baseline()
        else:
            if (
                args.config is None
                or args.baseline is None
                or sum(
                    value is not None
                    for value in (
                        args.transactions,
                        args.transaction_result,
                        args.item_records,
                    )
                ) != 1
                or (args.item_records is None) != (args.repo_root is None)
            ):
                raise ValueError(
                    "--config, --baseline과 transaction 입력 하나가 필요합니다"
                )
            transaction_results = None
            if args.transactions is not None:
                transaction_results = _read_json(args.transactions)
            elif args.transaction_result is not None:
                transaction_results = [_read_json(args.transaction_result)]
            report = run_finalization(
                _read_json(args.config),
                _read_json(args.baseline),
                transaction_results,
                item_records=(
                    _read_json(args.item_records)
                    if args.item_records is not None
                    else None
                ),
                repo_root=args.repo_root,
            )
    except Exception as exc:
        report = {"ok": False, "transactions": [], "commands": {},
                  "isolation": {}, "unmerged": {},
                  "recall_checks": [], "errors": [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
