#!/usr/bin/env python3
"""여러 적재 항목을 순서대로 실행하고 재개 가능한 상태 보고서를 남긴다."""
from __future__ import annotations

import argparse
import errno
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


ItemRunner = Callable[[dict[str, Any]], Any]
Finalizer = Callable[[dict[str, Any], dict[str, Any], list[dict[str, Any]]], Any]
BaselineCollector = Callable[[], Any]
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ENGINE_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")

_UNSUPPORTED_PARENT_FSYNC_ERRNOS = {errno.EINVAL}
for _errno_name in ("ENOTSUP", "EOPNOTSUPP"):
    _errno_value = getattr(errno, _errno_name, None)
    if _errno_value is not None:
        _UNSUPPORTED_PARENT_FSYNC_ERRNOS.add(_errno_value)


def _stderr_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else str(value)


def _fsync_parent_directory(path: Path) -> None:
    directory_fd: int | None = None
    try:
        directory_fd = os.open(path, os.O_RDONLY)
        os.fsync(directory_fd)
    except OSError as exc:
        if exc.errno in _UNSUPPORTED_PARENT_FSYNC_ERRNOS:
            return
        raise
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _write_report(path: Path, report: dict) -> None:
    temporary_path: Path | None = None
    try:
        if path.exists() and path.is_dir():
            raise OSError(f"report 경로가 디렉터리입니다: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp", delete=False) as f:
            temporary_path = Path(f.name)
            json.dump(report, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        _fsync_parent_directory(path.parent)
    except OSError as exc:
        raise ValueError(f"report를 저장할 수 없습니다: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _finalizer_module():
    script = Path(__file__).resolve().with_name("finalize_ingest.py")
    spec = importlib.util.spec_from_file_location("project_brain_semantic_finalizer", script)
    if spec is None or spec.loader is None:
        raise ValueError("semantic finalizer를 불러올 수 없습니다")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _has_symlink_component(path: Path) -> bool:
    # macOS의 /var -> /private/var 같은 시스템 경로 별칭은 허용하되,
    # 호출자가 지정한 마지막 경로 자체가 link인 경우는 거부한다.
    return path.absolute().is_symlink()


def _canonical_input_file(path: Path, *, field: str) -> Path:
    absolute = path.absolute()
    if _has_symlink_component(absolute):
        raise ValueError(f"{field} 경로에 symbolic link가 있습니다")
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{field} 경로가 없습니다: {absolute}: {exc}") from exc
    if not resolved.is_file():
        raise ValueError(f"{field} 경로가 regular file이 아닙니다: {resolved}")
    return resolved


def _repo_contract(payload: dict[str, Any]) -> dict[str, Any]:
    repo_root_value = payload.get("repo_root")
    if not isinstance(repo_root_value, str) or not Path(repo_root_value).is_absolute():
        raise ValueError("manifest.repo_root는 absolute path여야 합니다")
    repo_root_path = Path(repo_root_value)
    if _has_symlink_component(repo_root_path):
        raise ValueError("manifest.repo_root는 symbolic link를 포함할 수 없습니다")
    try:
        repo_root = repo_root_path.resolve(strict=True)
        repo_stat = repo_root.stat()
    except OSError as exc:
        raise ValueError(f"manifest.repo_root를 확인할 수 없습니다: {exc}") from exc
    if not repo_root.is_dir():
        raise ValueError("manifest.repo_root는 directory여야 합니다")
    expected_repo_id = payload.get("expected_repo_id")
    expected_revision_ref = payload.get("expected_revision_ref")
    engine_sha = payload.get("engine_sha")
    if not isinstance(expected_repo_id, str) or not expected_repo_id.strip():
        raise ValueError("manifest.expected_repo_id가 없습니다")
    if not isinstance(expected_revision_ref, str) or not expected_revision_ref.strip():
        raise ValueError("manifest.expected_revision_ref가 없습니다")
    if not isinstance(engine_sha, str) or _ENGINE_SHA.fullmatch(engine_sha) is None:
        raise ValueError("manifest.engine_sha는 exact lowercase Git SHA여야 합니다")
    return {
        "repo_root": str(repo_root),
        "expected_repo_id": expected_repo_id,
        "expected_revision_ref": expected_revision_ref,
        "engine_sha": engine_sha,
        "repo_root_device": repo_stat.st_dev,
        "repo_root_inode": repo_stat.st_ino,
    }


def _load_manifest(
    path: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], str]:
    try:
        manifest_bytes = path.read_bytes()
        payload = json.loads(manifest_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"manifest를 읽을 수 없습니다: {exc}") from exc
    required_fields = {
        "repo_root",
        "expected_repo_id",
        "expected_revision_ref",
        "engine_sha",
        "items",
        "finalization",
    }
    if not isinstance(payload, dict):
        raise ValueError("manifest 필드가 정확하지 않습니다")
    if "finalization" not in payload:
        raise ValueError("manifest.finalization이 없습니다")
    if set(payload) != required_fields:
        raise ValueError("manifest 필드가 정확하지 않습니다")
    if not isinstance(payload.get("items"), list):
        raise ValueError("manifest.items는 배열이어야 합니다")
    if not payload["items"]:
        raise ValueError("manifest.items는 최소 1개여야 합니다")

    keys: set[str] = set()
    items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(payload["items"]):
        if not isinstance(raw_item, dict):
            raise ValueError(f"items[{index}]는 객체여야 합니다")
        key = raw_item.get("key")
        if not isinstance(key, str) or not key:
            raise ValueError(f"items[{index}].key가 없습니다")
        if key in keys:
            raise ValueError(f"중복 key: {key}")
        keys.add(key)
        resolved: dict[str, Any] = {"key": key}
        for field in ("verify_json", "domain_spec_py"):
            value = raw_item.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"items[{index}].{field}가 없습니다")
            relative = Path(value)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"items[{index}].{field} 경로는 manifest-relative여야 합니다")
            source_path = _canonical_input_file(
                path.parent / relative,
                field=f"items[{index}].{field}",
            )
            if not source_path.is_relative_to(path.parent):
                raise ValueError(f"items[{index}].{field} 경로가 manifest root를 탈출합니다")
            resolved[field] = source_path
        items.append(resolved)
    try:
        finalization = _finalizer_module().validate_contract(payload.get("finalization"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"manifest.finalization이 올바르지 않습니다: {exc}") from exc
    return (
        items,
        finalization,
        _repo_contract(payload),
        hashlib.sha256(manifest_bytes).hexdigest(),
    )


def _manifest_fingerprint(items: list[dict[str, Any]], finalization: dict[str, Any]) -> str:
    fingerprint_items = []
    for item in items:
        try:
            verify_content = item["verify_json"].read_bytes()
            domain_spec_content = item["domain_spec_py"].read_bytes()
        except OSError as exc:
            raise ValueError(f"manifest 입력을 읽을 수 없습니다: {exc}") from exc
        fingerprint_items.append({
            "key": item["key"],
            "verify_json_path": str(item["verify_json"]),
            "verify_json_sha256": hashlib.sha256(verify_content).hexdigest(),
            "domain_spec_py_path": str(item["domain_spec_py"]),
            "domain_spec_py_sha256": hashlib.sha256(domain_spec_content).hexdigest(),
        })
    canonical = json.dumps({"items": fingerprint_items, "finalization": finalization},
                           ensure_ascii=True, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _reject_report_input_collision(report_path: Path, manifest_path: Path,
                                   items: list[dict[str, Any]]) -> None:
    inputs = [manifest_path]
    for item in items:
        inputs.extend((item["verify_json"], item["domain_spec_py"]))
    if any(report_path == input_path for input_path in inputs):
        raise ValueError("report 경로가 manifest 또는 항목 입력과 같습니다")


def _default_item_runner(item: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().with_name("run_ingest.sh")
    return subprocess.run(
        [
            str(script),
            "--defer-finalize",
            "--repo-root",
            item["repo_root"],
            "--expected-repo-id",
            item["expected_repo_id"],
            "--expected-revision-ref",
            item["expected_revision_ref"],
            "--engine-sha",
            item["engine_sha"],
            str(item["verify_json"]),
            str(item["domain_spec_py"]),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def _default_baseline_collector() -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().with_name("finalize_ingest.sh")
    return subprocess.run([str(script), "--capture-baseline"], text=True,
                          capture_output=True, check=False)


def _default_finalizer(
    contract: dict[str, Any],
    baseline: dict[str, Any],
    transactions: list[dict[str, Any]],
) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().with_name("finalize_ingest.sh")
    with tempfile.TemporaryDirectory(prefix="project-brain-finalize-") as td:
        root = Path(td)
        config_path = root / "config.json"
        baseline_path = root / "baseline.json"
        transactions_path = root / "transactions.json"
        config_path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        baseline_path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
        transactions_path.write_text(
            json.dumps(transactions, ensure_ascii=False),
            encoding="utf-8",
        )
        return subprocess.run(
            [
                str(script),
                "--config",
                str(config_path),
                "--baseline",
                str(baseline_path),
                "--transactions",
                str(transactions_path),
            ],
            text=True, capture_output=True, check=False)


def _transaction_details(
    result: Any,
) -> tuple[dict[str, Any] | None, int, str]:
    if isinstance(result, int) and not isinstance(result, bool) and result != 0:
        return None, result, ""
    if (
        isinstance(result, tuple)
        and len(result) == 2
        and isinstance(result[0], int)
        and not isinstance(result[0], bool)
        and result[0] != 0
        and isinstance(result[1], str)
    ):
        return None, result[0], result[1]
    if isinstance(result, dict):
        payload = result
        exit_code = 0 if payload.get("ok") is True else 1
        stderr = ""
    elif isinstance(result, subprocess.CompletedProcess):
        exit_code = (
            result.returncode
            if isinstance(result.returncode, int) and not isinstance(result.returncode, bool)
            else 1
        )
        stderr = _stderr_text(result.stderr)
        try:
            payload = json.loads(_stderr_text(result.stdout))
        except (TypeError, json.JSONDecodeError):
            payload = None
    else:
        return None, 1, f"구조화 transaction 결과가 아님: {result!r}"
    if exit_code != 0:
        return None, exit_code, stderr
    try:
        normalized = _finalizer_module().validate_transaction_results([payload])
    except (OSError, ValueError) as exc:
        return None, 1, str(exc)
    return normalized[0], 0, stderr


def _run_item(
    runner: ItemRunner,
    item: dict[str, Any],
) -> tuple[dict[str, Any] | None, int, str]:
    try:
        return _transaction_details(runner(item))
    except Exception as exc:  # 실행 오류도 항목 실패로 남겨야 재개할 수 있다.
        return None, 1, str(exc)


def _json_payload(result: Any) -> tuple[dict[str, Any] | None, int, str]:
    if isinstance(result, dict):
        payload = result
        exit_code = 0 if payload.get("ok") is True else 1
        return payload, exit_code, ""
    if isinstance(result, subprocess.CompletedProcess):
        exit_code = (result.returncode if isinstance(result.returncode, int)
                     and not isinstance(result.returncode, bool) else 1)
        try:
            stdout = _stderr_text(result.stdout)
            payload = json.loads(stdout)
        except (TypeError, json.JSONDecodeError):
            payload = None
        return payload if isinstance(payload, dict) else None, exit_code, _stderr_text(result.stderr)
    return None, 1, f"구조화 JSON 실행 결과가 아님: {result!r}"


def _baseline_details(result: Any, expected_unmerged_locator_ids: list[str]) -> tuple[dict[str, Any] | None, str]:
    payload, exit_code, stderr = _json_payload(result)
    if exit_code != 0 or not isinstance(payload, dict) or payload.get("ok") is not True:
        return None, stderr or "고립 baseline 결과가 올바르지 않습니다"
    try:
        normalized = _finalizer_module().normalize_baseline(
            payload, expected_unmerged_locator_ids)
    except (OSError, ValueError) as exc:
        return None, str(exc)
    if not normalized["git_baseline_available"]:
        return {"ok": True, "isolated_ids": normalized["isolated_ids"]}, ""
    return {key: normalized[key] for key in
            ("ok", "isolated_ids", "target_head", "unmerged_locator_ids")}, ""


def _finalization_details(result: Any) -> tuple[dict[str, Any], int, str]:
    payload, exit_code, stderr = _json_payload(result)
    required = {
        "ok",
        "transactions",
        "commands",
        "isolation",
        "unmerged",
        "recall_checks",
        "errors",
    }
    valid = (isinstance(payload, dict) and set(payload) == required
             and isinstance(payload.get("ok"), bool)
             and isinstance(payload.get("transactions"), list)
             and isinstance(payload.get("commands"), dict)
             and isinstance(payload.get("isolation"), dict)
             and isinstance(payload.get("unmerged"), dict)
             and isinstance(payload.get("recall_checks"), list)
             and isinstance(payload.get("errors"), list)
             and all(isinstance(error, str) for error in payload.get("errors", [])))
    if not valid:
        failure = {"ok": False, "transactions": [], "commands": {},
                   "isolation": {}, "unmerged": {}, "recall_checks": [],
                   "errors": [stderr or "finalizer가 구조화 결과를 반환하지 않았습니다"]}
        return failure, 1, stderr
    if payload["ok"] is not (exit_code == 0):
        payload = dict(payload)
        payload["ok"] = False
        payload["errors"] = [*payload["errors"], "finalizer 종료 코드와 ok가 일치하지 않습니다"]
        return payload, 1, stderr
    return payload, exit_code, stderr


def _load_resume_state(path: Path, *, expected: int, valid_keys: set[str],
                       manifest_fingerprint: str, manifest_sha256: str,
                       repo_contract: dict[str, Any],
                       expected_unmerged_locator_ids: list[str]
                       ) -> tuple[set[str], dict[str, Any], list[dict[str, Any]]]:
    try:
        resume_file = _canonical_input_file(path, field="resume report")
        with resume_file.open(encoding="utf-8") as f:
            previous = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"resume report를 읽을 수 없습니다: {exc}") from exc
    required = {
        "repo_root",
        "expected_repo_id",
        "expected_revision_ref",
        "engine_sha",
        "repo_root_device",
        "repo_root_inode",
        "manifest_sha256",
        "manifest_fingerprint",
        "expected",
        "succeeded",
        "failed",
        "transactions",
        "isolation_baseline",
        "finalized",
        "finalization",
        "finalize_failure",
    }
    if not isinstance(previous, dict) or set(previous) != required:
        raise ValueError("resume_contract_mismatch: report fields")
    expected_contract = {
        **repo_contract,
        "manifest_sha256": manifest_sha256,
        "manifest_fingerprint": manifest_fingerprint,
    }
    for field, expected_value in expected_contract.items():
        if previous.get(field) != expected_value:
            raise ValueError(f"resume_contract_mismatch: {field}")
    if (not isinstance(previous["expected"], int)
            or isinstance(previous["expected"], bool)
            or previous["expected"] != expected):
        raise ValueError("resume_contract_mismatch: expected")
    if not isinstance(previous["succeeded"], list):
        raise ValueError("resume_contract_mismatch: succeeded")
    succeeded = previous["succeeded"]
    if (any(not isinstance(key, str) or not key for key in succeeded)
            or len(succeeded) != len(set(succeeded))
            or not set(succeeded).issubset(valid_keys)):
        raise ValueError("resume_contract_mismatch: succeeded")
    if not isinstance(previous["failed"], list):
        raise ValueError("resume_contract_mismatch: failed")
    failed_keys: set[str] = set()
    for failure in previous["failed"]:
        if not isinstance(failure, dict):
            raise ValueError("resume_contract_mismatch: failed")
        key = failure.get("key")
        exit_code = failure.get("exit_code")
        stderr = failure.get("stderr")
        if (not isinstance(key, str) or not key or key not in valid_keys
                or key in failed_keys or key in succeeded
                or not isinstance(exit_code, int) or isinstance(exit_code, bool)
                or not isinstance(stderr, str)):
            raise ValueError("resume_contract_mismatch: failed")
        failed_keys.add(key)
    if not isinstance(previous["finalized"], bool):
        raise ValueError("resume_contract_mismatch: finalized")
    if previous["transactions"] == [] and succeeded == []:
        transactions = []
    else:
        try:
            transactions = _finalizer_module().validate_transaction_results(
                previous["transactions"]
            )
        except (OSError, ValueError) as exc:
            raise ValueError(f"resume_contract_mismatch: transactions: {exc}") from exc
    if len(transactions) != len(succeeded):
        raise ValueError("resume_contract_mismatch: transactions")
    try:
        normalized = _finalizer_module().normalize_baseline(
            previous["isolation_baseline"], expected_unmerged_locator_ids)
    except (OSError, ValueError) as exc:
        raise ValueError(f"resume_contract_mismatch: isolation_baseline: {exc}") from exc
    if not normalized["git_baseline_available"]:
        return (
            set(succeeded),
            {"ok": True, "isolated_ids": normalized["isolated_ids"]},
            transactions,
        )
    baseline = {key: normalized[key] for key in
                ("ok", "isolated_ids", "target_head", "unmerged_locator_ids")}
    return set(succeeded), baseline, transactions


def run_batch(manifest_path, report_path, *, resume_path=None,
              item_runner=None, finalizer=None, baseline_collector=None) -> dict:
    """manifest의 항목을 실행하고 항목마다 원자적으로 report를 갱신한다.

    ``item_runner``는 절대 경로가 들어간 ``key``, ``verify_json``, ``domain_spec_py`` 항목
    dict를 받고, 정확한 transaction dict나 stdout이 그 JSON인
    ``subprocess.CompletedProcess``를 반환한다. bool이 아닌 종료 코드(int)와
    ``(종료 코드, stderr 문자열)`` tuple은 실패 경로 테스트용으로만 허용한다.
    """
    manifest = _canonical_input_file(Path(manifest_path), field="manifest")
    report_file = Path(report_path).resolve()
    if report_file.exists() and report_file.is_dir():
        raise ValueError(f"report 경로가 디렉터리입니다: {report_file}")
    items, finalization_contract, repo_contract, manifest_sha256 = (
        _load_manifest(manifest)
    )  # 실행 전 전체 입력을 검사한다.
    _reject_report_input_collision(report_file, manifest, items)
    manifest_fingerprint = _manifest_fingerprint(items, finalization_contract)

    prior_succeeded: set[str] = set()
    transactions: list[dict[str, Any]] = []
    isolation_baseline: dict[str, Any]
    if resume_path is not None:
        valid_keys = {item["key"] for item in items}
        prior_succeeded, isolation_baseline, transactions = _load_resume_state(
            Path(resume_path), expected=len(items), valid_keys=valid_keys,
            manifest_fingerprint=manifest_fingerprint,
            manifest_sha256=manifest_sha256,
            repo_contract=repo_contract,
            expected_unmerged_locator_ids=finalization_contract["expected_unmerged_locator_ids"])
    else:
        collect: BaselineCollector = (_default_baseline_collector if baseline_collector is None
                                      else baseline_collector)
        try:
            isolation_baseline, baseline_error = _baseline_details(
                collect(), finalization_contract["expected_unmerged_locator_ids"])
        except Exception as exc:
            isolation_baseline, baseline_error = None, str(exc)
        if isolation_baseline is None:
            raise ValueError(f"적재 전 isolation baseline 수집 실패: {baseline_error}")

    report = {
        **repo_contract,
        "manifest_sha256": manifest_sha256,
        "expected": len(items),
        "manifest_fingerprint": manifest_fingerprint,
        "succeeded": [item["key"] for item in items if item["key"] in prior_succeeded],
        "failed": [],
        "transactions": list(transactions),
        "isolation_baseline": isolation_baseline,
        "finalized": False,
        "finalization": None,
        "finalize_failure": None,
    }
    _write_report(report_file, report)
    runner: ItemRunner = _default_item_runner if item_runner is None else item_runner
    for item in items:
        if item["key"] in prior_succeeded:
            continue
        item_input = {**item, **repo_contract}
        transaction, exit_code, stderr = _run_item(runner, item_input)
        if exit_code == 0 and transaction is not None:
            report["succeeded"].append(item["key"])
            report["transactions"].append(transaction)
        else:
            report["failed"].append({
                "key": item["key"],
                "exit_code": exit_code,
                "stderr": stderr[-2000:],
            })
        _write_report(report_file, report)

    if report["failed"]:
        return report

    finish: Finalizer = _default_finalizer if finalizer is None else finalizer
    try:
        finalization, final_exit_code, final_stderr = _finalization_details(
            finish(
                finalization_contract,
                isolation_baseline,
                report["transactions"],
            ))
    except Exception as exc:
        finalization = {"ok": False, "transactions": [], "commands": {},
                        "isolation": {}, "unmerged": {},
                        "recall_checks": [], "errors": [str(exc)]}
        final_exit_code = 1
        final_stderr = str(exc)
    report["finalization"] = finalization
    transactions_match = finalization.get("transactions") == report["transactions"]
    if not transactions_match:
        finalization["ok"] = False
        finalization["errors"] = [
            *finalization.get("errors", []),
            "finalizer transaction results가 batch report와 다릅니다",
        ]
        if final_exit_code == 0:
            final_exit_code = 1
    report["finalized"] = (
        final_exit_code == 0
        and finalization["ok"] is True
        and transactions_match
        and bool(report["transactions"])
    )
    if not report["finalized"]:
        report["finalize_failure"] = {
            "exit_code": final_exit_code,
            "stderr": final_stderr[-2000:],
        }
    _write_report(report_file, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="여러 적재 항목을 순서대로 실행합니다")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--resume", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_batch(args.manifest, args.report, resume_path=args.resume)
    except ValueError as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not report["failed"] and report["finalized"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
