#!/usr/bin/env python3
"""여러 적재 항목을 순서대로 실행하고 재개 가능한 상태 보고서를 남긴다."""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable


ItemRunner = Callable[[dict[str, Any]], Any]
Finalizer = Callable[[], Any]

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


def _load_manifest(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"manifest를 읽을 수 없습니다: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("manifest.items는 배열이어야 합니다")

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
            source_path = (path.parent / value).resolve()
            if not source_path.is_file():
                raise ValueError(f"items[{index}].{field} 경로가 없습니다: {source_path}")
            resolved[field] = source_path
        items.append(resolved)
    return items


def _manifest_fingerprint(items: list[dict[str, Any]]) -> str:
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
    canonical = json.dumps(fingerprint_items, ensure_ascii=True, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _default_item_runner(item: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().with_name("run_ingest.sh")
    return subprocess.run(
        [str(script), "--defer-finalize", str(item["verify_json"]), str(item["domain_spec_py"])],
        text=True,
        capture_output=True,
        check=False,
    )


def _default_finalizer() -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().with_name("finalize_ingest.sh")
    return subprocess.run([str(script)], text=True, capture_output=True, check=False)


def _result_details(result: Any) -> tuple[bool, int, str]:
    if isinstance(result, subprocess.CompletedProcess):
        if isinstance(result.returncode, int) and not isinstance(result.returncode, bool):
            return True, result.returncode, _stderr_text(result.stderr)
    if isinstance(result, int) and not isinstance(result, bool):
        return True, result, ""
    if (isinstance(result, tuple) and len(result) == 2
            and isinstance(result[0], int) and not isinstance(result[0], bool)
            and isinstance(result[1], str)):
        return True, result[0], result[1]
    return False, 1, f"지원하지 않는 실행 결과: {result!r}"


def _run_item(runner: ItemRunner, item: dict[str, Any]) -> tuple[int, str]:
    try:
        _, exit_code, stderr = _result_details(runner(item))
        return exit_code, stderr
    except Exception as exc:  # 실행 오류도 항목 실패로 남겨야 재개할 수 있다.
        return 1, str(exc)


def _load_resume_succeeded(path: Path, *, expected: int, valid_keys: set[str],
                           manifest_fingerprint: str) -> set[str]:
    try:
        with path.open(encoding="utf-8") as f:
            previous = json.load(f)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"resume report를 읽을 수 없습니다: {exc}") from exc
    required = {"expected", "succeeded", "failed", "finalized", "manifest_fingerprint"}
    if not isinstance(previous, dict) or not required.issubset(previous):
        raise ValueError("resume report에 필수 상태 필드가 없습니다")
    if (not isinstance(previous["expected"], int)
            or isinstance(previous["expected"], bool)
            or previous["expected"] != expected):
        raise ValueError("resume report의 expected가 현재 manifest와 다릅니다")
    if (not isinstance(previous["manifest_fingerprint"], str)
            or previous["manifest_fingerprint"] != manifest_fingerprint):
        raise ValueError("resume report의 manifest_fingerprint가 현재 입력과 다릅니다")
    if not isinstance(previous["succeeded"], list):
        raise ValueError("resume report의 succeeded는 배열이어야 합니다")
    succeeded = previous["succeeded"]
    if (any(not isinstance(key, str) or not key for key in succeeded)
            or len(succeeded) != len(set(succeeded))
            or not set(succeeded).issubset(valid_keys)):
        raise ValueError("resume report의 succeeded key가 올바르지 않습니다")
    if not isinstance(previous["failed"], list):
        raise ValueError("resume report의 failed는 배열이어야 합니다")
    failed_keys: set[str] = set()
    for failure in previous["failed"]:
        if not isinstance(failure, dict):
            raise ValueError("resume report의 failed 항목은 객체여야 합니다")
        key = failure.get("key")
        exit_code = failure.get("exit_code")
        stderr = failure.get("stderr")
        if (not isinstance(key, str) or not key or key not in valid_keys
                or key in failed_keys or key in succeeded
                or not isinstance(exit_code, int) or isinstance(exit_code, bool)
                or not isinstance(stderr, str)):
            raise ValueError("resume report의 failed 항목이 올바르지 않습니다")
        failed_keys.add(key)
    if not isinstance(previous["finalized"], bool):
        raise ValueError("resume report의 finalized는 bool이어야 합니다")
    return set(succeeded)


def run_batch(manifest_path, report_path, *, resume_path=None,
              item_runner=None, finalizer=None) -> dict:
    """manifest의 항목을 실행하고 항목마다 원자적으로 report를 갱신한다.

    ``item_runner``는 절대 경로가 들어간 ``key``, ``verify_json``, ``domain_spec_py`` 항목 dict를
    받고, ``subprocess.CompletedProcess``, bool이 아닌 종료 코드(int), 또는
    ``(종료 코드, stderr 문자열)`` tuple을 반환한다.
    """
    manifest = Path(manifest_path).resolve()
    report_file = Path(report_path).resolve()
    items = _load_manifest(manifest)  # 실행 전 전체 입력을 검사한다.
    manifest_fingerprint = _manifest_fingerprint(items)

    prior_succeeded: set[str] = set()
    if resume_path is not None:
        valid_keys = {item["key"] for item in items}
        prior_succeeded = _load_resume_succeeded(
            Path(resume_path), expected=len(items), valid_keys=valid_keys,
            manifest_fingerprint=manifest_fingerprint)

    report = {
        "expected": len(items),
        "manifest_fingerprint": manifest_fingerprint,
        "succeeded": [item["key"] for item in items if item["key"] in prior_succeeded],
        "failed": [],
        "finalized": False,
        "finalize_failure": None,
    }
    _write_report(report_file, report)
    runner: ItemRunner = _default_item_runner if item_runner is None else item_runner
    for item in items:
        if item["key"] in prior_succeeded:
            continue
        exit_code, stderr = _run_item(runner, item)
        if exit_code == 0:
            report["succeeded"].append(item["key"])
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
        _, final_exit_code, final_stderr = _result_details(finish())
    except Exception as exc:
        final_exit_code = 1
        final_stderr = str(exc)
    report["finalized"] = final_exit_code == 0
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
