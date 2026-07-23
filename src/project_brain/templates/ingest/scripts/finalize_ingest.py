#!/usr/bin/env python3
"""적재 뒤 공통 게이트를 실행하고 머신 판독 가능한 결과를 낸다."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Callable


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]


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
        if not isinstance(locator_id, str) or not locator_id:
            return None, "audit stale state unavailable"
        locator_ids.append(locator_id)
    if len(locator_ids) != len(set(locator_ids)):
        return None, "audit stale state unavailable"
    return {"target_head": target_head, "unmerged_locator_ids": sorted(locator_ids)}, ""


def capture_isolation_baseline(runner: CommandRunner = _default_runner) -> dict:
    result = _run_command(runner, ["project-brain", "graph", "isolated"], json_output=True)
    audit = _run_command(runner, ["project-brain", "audit", "--no-fetch"], json_output=True)
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


def run_finalization(contract: Any, baseline_ids: Any,
                     runner: CommandRunner = _default_runner) -> dict:
    config = validate_contract(contract)
    baseline = normalize_baseline(baseline_ids, config["expected_unmerged_locator_ids"])
    commands = {
        "index_rebuild": _run_command(
            runner, ["project-brain", "index", "rebuild"], json_output=True),
        "lint": _run_command(runner, ["project-brain", "lint"], json_output=True),
        "eval": _run_command(runner, ["project-brain", "eval"], json_output=True),
        "graph_isolated": _run_command(
            runner, ["project-brain", "graph", "isolated"], json_output=True),
        "audit": _run_command(runner, ["project-brain", "audit", "--no-fetch"], json_output=True),
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

    return {"ok": not errors, "commands": commands, "isolation": isolation,
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
    parser.add_argument("--config", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.validate_config is not None:
            if args.capture_baseline or args.config is not None or args.baseline is not None:
                raise ValueError("--validate-config은 다른 모드 인자와 함께 쓸 수 없습니다")
            validate_contract(_read_json(args.validate_config))
            report = {"ok": True, "validated": True}
        elif args.capture_baseline:
            if args.config is not None or args.baseline is not None:
                raise ValueError("--capture-baseline은 다른 인자와 함께 쓸 수 없습니다")
            report = capture_isolation_baseline()
        else:
            if args.config is None or args.baseline is None:
                raise ValueError("--config와 --baseline이 필요합니다")
            report = run_finalization(_read_json(args.config), _read_json(args.baseline))
    except ValueError as exc:
        report = {"ok": False, "commands": {}, "isolation": {}, "unmerged": {},
                  "recall_checks": [], "errors": [str(exc)]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
