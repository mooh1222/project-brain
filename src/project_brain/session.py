"""세션 transcript 스캔과 receipt-bound 완료 marker.

transcript의 의미 해석이나 지식 추출은 이 모듈의 책임이 아니다. ``session complete``는
이미 generic ingest batch가 만든 manifest, report, durable receipt를 다시 대조해 성공이
확정된 경우에만 처리 marker v2를 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from project_brain.objbase import now_kst

DEFAULT_TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"
_MESSAGE_TYPES = {"user", "assistant"}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MARKER_V2_FIELDS = {
    "version",
    "state",
    "uuid",
    "transcript_sha256",
    "manifest_sha256",
    "report_sha256",
    "receipt_ids",
    "processed_at",
}
_LEGACY_MARKER_FIELDS = {"uuid", "processed_at", "note"}
_ITEM_RECORD_FIELDS = {
    "binding",
    "status",
    "failure",
    "expected_objects",
    "verified_objects",
    "changed_objects",
    "receipt",
}
_FINALIZATION_FIELDS = {
    "ok",
    "transactions",
    "commands",
    "isolation",
    "unmerged",
    "recall_checks",
    "errors",
}


class SessionCompletionError(RuntimeError):
    """세션 완료 입력이 marker를 쓸 조건을 만족하지 않을 때의 구조화 오류."""

    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(detail)


def scan_sessions(
    transcript_root=None,
    project_filter: str | None = None,
    brain_root=None,
) -> list[dict]:
    """transcript_root 아래 모든 세션 jsonl의 요약 목록.

    반환 원소: {uuid, path, cwd, started_at, message_count}.
    project_filter: cwd에 이 부분 문자열이 포함된 세션만(예: "demoapp").
    brain_root: 지정하면 processed와 marker_state를 함께 반환한다.
    """
    root = Path(transcript_root) if transcript_root else DEFAULT_TRANSCRIPT_ROOT
    sessions = []
    for path in sorted(root.glob("*/*.jsonl")):
        info = _summarize(path)
        if project_filter and project_filter not in (info["cwd"] or ""):
            continue
        if brain_root is not None:
            state = marker_state(info["uuid"], brain_root)
            info["processed"] = state == "processed"
            info["marker_state"] = state
        sessions.append(info)
    return sessions


def _marks_dir(brain_root) -> Path:
    return Path(brain_root) / ".brain-local" / "sessions"


def _marker_path(uuid: str, brain_root) -> Path:
    return _marks_dir(brain_root) / f"{uuid}.json"


def _valid_uuid(uuid: object) -> bool:
    return (
        isinstance(uuid, str)
        and bool(uuid)
        and Path(uuid).name == uuid
        and uuid not in {".", ".."}
    )


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _valid_v2_marker(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != _MARKER_V2_FIELDS:
        return False
    receipt_ids = value.get("receipt_ids")
    return (
        value.get("version") == 2
        and value.get("state") == "processed"
        and _valid_uuid(value.get("uuid"))
        and _is_sha256(value.get("transcript_sha256"))
        and _is_sha256(value.get("manifest_sha256"))
        and _is_sha256(value.get("report_sha256"))
        and isinstance(receipt_ids, list)
        and bool(receipt_ids)
        and all(_is_sha256(receipt_id) for receipt_id in receipt_ids)
        and len(set(receipt_ids)) == len(receipt_ids)
        and isinstance(value.get("processed_at"), str)
        and bool(value["processed_at"])
    )


def _is_legacy_marker(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == _LEGACY_MARKER_FIELDS
        and _valid_uuid(value.get("uuid"))
        and isinstance(value.get("processed_at"), str)
        and isinstance(value.get("note"), (str, type(None)))
    )


def marker_state(uuid: str, brain_root) -> str:
    """현재 marker의 구조만 보고 processed 여부를 보수적으로 분류한다."""
    if not _valid_uuid(uuid):
        return "invalid_marker"
    path = _marker_path(uuid, brain_root)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        return "invalid_marker"
    if not path.exists():
        return "unprocessed"
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "invalid_marker"
    if _valid_v2_marker(marker) and marker.get("uuid") == uuid:
        return "processed"
    if _is_legacy_marker(marker):
        return "legacy_unverified"
    return "invalid_marker"


def is_processed(uuid: str, brain_root) -> bool:
    """v2 receipt-bound marker가 있는 세션만 처리 완료로 본다."""
    return marker_state(uuid, brain_root) == "processed"


def mark_processed(uuid: str, brain_root, note: str | None = None) -> dict:
    """구형 수동 marker는 더 이상 쓰지 않는다.

    ``note``는 하위 호출자 호환을 위해 받지만, 처리 완료 증거를 대신할 수 없다.
    """
    del uuid, brain_root, note
    raise SessionCompletionError(
        "session_completion_report_required",
        "session complete에 transcript, manifest, report를 함께 지정해야 합니다",
    )


def complete_session(
    uuid: str,
    *,
    transcript: Path | str,
    manifest: Path | str,
    report: Path | str,
    brain_root: Path | str,
) -> dict[str, Any]:
    """exact generic batch success를 transcript에 결속해 marker v2를 만든다."""
    if not _valid_uuid(uuid):
        raise SessionCompletionError(
            "session_completion_report_invalid", "session uuid가 올바르지 않습니다"
        )
    transcript_path = Path(transcript)
    if transcript_path.stem != uuid:
        raise SessionCompletionError(
            "session_completion_report_invalid",
            "transcript basename의 stem이 session uuid와 다릅니다",
        )
    root = Path(brain_root).resolve()
    try:
        root_stat = root.stat()
    except OSError as exc:
        raise SessionCompletionError(
            "session_completion_report_invalid", f"brain root를 읽을 수 없습니다: {exc}"
        ) from exc
    if not root.is_dir():
        raise SessionCompletionError(
            "session_completion_report_invalid", "brain root가 directory가 아닙니다"
        )

    transcript_bytes = _read_regular_bytes(transcript_path, field="transcript")
    manifest_bytes = _read_regular_bytes(Path(manifest), field="manifest")
    report_bytes = _read_regular_bytes(Path(report), field="report")

    transcript_sha256 = _sha256(transcript_bytes)
    manifest_sha256 = _sha256(manifest_bytes)
    report_sha256 = _sha256(report_bytes)
    marker = _marker_path(uuid, root)
    if not marker.is_symlink() and (not marker.exists() or marker.is_file()):
        existing = _read_existing_marker(marker)
        if existing is not None:
            _, existing_payload = existing
            if _valid_v2_marker(existing_payload):
                assert isinstance(existing_payload, dict)
                if (
                    existing_payload["uuid"] == uuid
                    and existing_payload["transcript_sha256"] == transcript_sha256
                    and existing_payload["manifest_sha256"] == manifest_sha256
                    and existing_payload["report_sha256"] == report_sha256
                ):
                    receipt_ids = existing_payload["receipt_ids"]
                    assert isinstance(receipt_ids, list)
                    return _completion_result(uuid, marker, receipt_ids)

    try:
        report_payload = json.loads(report_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionCompletionError(
            "session_completion_report_invalid", f"report JSON이 올바르지 않습니다: {exc}"
        ) from exc

    receipt_ids = _validate_success_report(
        report_payload,
        manifest_sha256=manifest_sha256,
        brain_root=root,
        brain_stat=root_stat,
    )
    marker_payload = {
        "version": 2,
        "state": "processed",
        "uuid": uuid,
        "transcript_sha256": transcript_sha256,
        "manifest_sha256": manifest_sha256,
        "report_sha256": report_sha256,
        "receipt_ids": receipt_ids,
        "processed_at": now_kst(),
    }
    existing_result = _existing_marker_result(
        _read_existing_marker(marker),
        marker_payload=marker_payload,
        marker=marker,
        uuid=uuid,
        receipt_ids=receipt_ids,
    )
    if existing_result is not None:
        return existing_result
    if not _write_new_marker(marker, marker_payload):
        existing_result = _existing_marker_result(
            _read_existing_marker(marker),
            marker_payload=marker_payload,
            marker=marker,
            uuid=uuid,
            receipt_ids=receipt_ids,
        )
        if existing_result is not None:
            return existing_result
        raise SessionCompletionError(
            "session_completion_conflict", "marker 생성 경쟁 결과를 읽을 수 없습니다"
        )
    return _completion_result(uuid, marker, receipt_ids)


def _completion_result(uuid: str, marker: Path, receipt_ids: list[str]) -> dict[str, Any]:
    return {
        "ok": True,
        "uuid": uuid,
        "state": "processed",
        "marker_path": str(marker),
        "receipt_ids": receipt_ids,
    }


def _read_regular_bytes(path: Path, *, field: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SessionCompletionError(
            "session_completion_report_invalid", f"{field}가 일반 파일이 아닙니다"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SessionCompletionError(
            "session_completion_report_invalid", f"{field}를 읽을 수 없습니다: {exc}"
        ) from exc


def _validate_success_report(
    report: object,
    *,
    manifest_sha256: str,
    brain_root: Path,
    brain_stat: os.stat_result,
) -> list[str]:
    if not isinstance(report, dict):
        _report_invalid("report가 JSON 객체가 아닙니다")
    required = {
        "brain_root", "brain_root_device", "brain_root_inode", "manifest_sha256",
        "expected", "item_records", "succeeded", "failed", "transactions",
        "finalized", "finalization", "finalize_failure",
    }
    if not required <= set(report):
        _report_invalid("generic batch report의 필수 필드가 없습니다")
    if report.get("manifest_sha256") != manifest_sha256:
        _report_invalid("report가 지정 manifest에 결속되지 않았습니다")
    if (
        report.get("brain_root") != str(brain_root)
        or report.get("brain_root_device") != brain_stat.st_dev
        or report.get("brain_root_inode") != brain_stat.st_ino
    ):
        _report_invalid("report가 현재 brain root에 결속되지 않았습니다")
    records = report.get("item_records")
    expected = report.get("expected")
    if (
        type(expected) is not int
        or expected < 1
        or not isinstance(records, list)
        or len(records) != expected
    ):
        _report_invalid("report item_records가 비어 있거나 expected와 다릅니다")
    if report.get("failed") != [] or report.get("finalized") is not True:
        _report_invalid("batch가 실패했거나 finalization을 완료하지 못했습니다")
    if report.get("finalize_failure") is not None:
        _report_invalid("batch finalize_failure가 남아 있습니다")

    normalized_records: list[dict[str, Any]] = []
    receipt_ids: list[str] = []
    item_keys: list[str] = []
    seen_receipt_ids: set[str] = set()
    for index, raw_record in enumerate(records):
        if not isinstance(raw_record, dict) or set(raw_record) != _ITEM_RECORD_FIELDS:
            _report_invalid(f"item_records[{index}] 필드가 generic batch 계약과 다릅니다")
        try:
            from project_brain.transaction_receipt import (
                batch_binding_dict,
                mutation_receipt_dict,
                normalize_batch_binding,
            )

            binding = normalize_batch_binding(raw_record.get("binding"))
            assert binding is not None
            binding_payload = batch_binding_dict(binding)
            assert binding_payload is not None
            receipt = mutation_receipt_dict(raw_record.get("receipt"))
        except (AssertionError, ValueError) as exc:
            _report_invalid(f"item_records[{index}] binding 또는 receipt가 올바르지 않습니다: {exc}")
        if raw_record["binding"] != binding_payload:
            _report_invalid(f"item_records[{index}] binding이 정규화 결과와 다릅니다")
        if (
            binding_payload["batch_manifest_sha256"] != manifest_sha256
            or binding_payload["brain_root"] != str(brain_root)
            or binding_payload["brain_root_device"] != brain_stat.st_dev
            or binding_payload["brain_root_inode"] != brain_stat.st_ino
        ):
            _report_invalid(f"item_records[{index}] binding이 manifest 또는 brain root와 다릅니다")
        item_key = binding_payload["item_key"]
        if item_key in item_keys:
            _report_invalid(f"item_records[{index}] item_key가 중복입니다")
        item_keys.append(item_key)
        if raw_record.get("status") not in {"committed", "no_changes"}:
            _report_invalid(f"item_records[{index}]가 terminal receipt 상태가 아닙니다")
        if raw_record.get("failure") is not None:
            _report_invalid(f"item_records[{index}] failure가 남아 있습니다")
        if (
            raw_record["receipt"] != receipt
            or raw_record["status"] != receipt["outcome"]
            or receipt["operation"] != "ingest"
            or receipt["coverage_sha256"] != binding_payload["coverage_sha256"]
            or raw_record["expected_objects"] != receipt["expected_objects"]
            or raw_record["verified_objects"] != receipt["verified_objects"]
            or raw_record["changed_objects"] != receipt["changed_objects"]
        ):
            _report_invalid(f"item_records[{index}] receipt 결속이 다릅니다")
        receipt_id = receipt["receipt_id"]
        if receipt_id in seen_receipt_ids:
            _report_invalid(f"item_records[{index}] receipt_id가 중복입니다")
        seen_receipt_ids.add(receipt_id)
        receipt_ids.append(receipt_id)
        normalized_records.append({"binding": binding_payload, "receipt": receipt})

    receipts = [record["receipt"] for record in normalized_records]
    if report.get("succeeded") != item_keys or report.get("transactions") != receipts:
        _report_invalid("report의 succeeded 또는 transactions가 item_records와 다릅니다")
    finalization = report.get("finalization")
    if (
        not isinstance(finalization, dict)
        or set(finalization) != _FINALIZATION_FIELDS
        or finalization.get("ok") is not True
        or finalization.get("transactions") != receipts
        or not isinstance(finalization.get("commands"), dict)
        or not isinstance(finalization.get("isolation"), dict)
        or not isinstance(finalization.get("unmerged"), dict)
        or not isinstance(finalization.get("recall_checks"), list)
        or not isinstance(finalization.get("errors"), list)
        or not all(isinstance(error, str) for error in finalization["errors"])
    ):
        _report_invalid("finalization success receipt가 generic batch report와 다릅니다")

    try:
        from project_brain.corpus_io import recover_batch_receipts

        recovered = recover_batch_receipts(
            brain_root,
            [record["binding"] for record in normalized_records],
            expected_receipts=receipts,
            verification_mode="strict_commit",
        )
    except Exception as exc:
        _report_invalid(f"durable receipt recovery가 실패했습니다: {exc}")
    if list(recovered) != receipts:
        _report_invalid("durable receipt recovery 결과가 report와 다릅니다")
    return receipt_ids


def _report_invalid(detail: str) -> None:
    raise SessionCompletionError("session_completion_report_invalid", detail)


def _read_existing_marker(marker: Path) -> tuple[bytes, object] | None:
    if marker.is_symlink() or (marker.exists() and not marker.is_file()):
        raise SessionCompletionError(
            "session_completion_conflict", "기존 marker가 일반 파일이 아닙니다"
        )
    if not marker.exists():
        return None
    try:
        payload = marker.read_bytes()
        return payload, json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return b"", None


def _existing_marker_result(
    existing: tuple[bytes, object] | None,
    *,
    marker_payload: dict[str, Any],
    marker: Path,
    uuid: str,
    receipt_ids: list[str],
) -> dict[str, Any] | None:
    if existing is None:
        return None
    _existing_bytes, existing_payload = existing
    if _valid_v2_marker(existing_payload):
        same_request = all(
            existing_payload[field] == marker_payload[field]
            for field in (
                "version", "state", "uuid", "transcript_sha256",
                "manifest_sha256", "report_sha256", "receipt_ids",
            )
        )
        if same_request:
            return _completion_result(uuid, marker, receipt_ids)
        raise SessionCompletionError(
            "session_completion_conflict",
            "기존 v2 marker가 이번 완료 요청과 다릅니다",
        )
    if _is_legacy_marker(existing_payload):
        raise SessionCompletionError(
            "legacy_unverified",
            "기존 legacy marker는 receipt-bound processed 상태로 바꾸지 않습니다",
        )
    raise SessionCompletionError(
        "session_completion_conflict", "기존 marker 형식이 올바르지 않습니다"
    )


def _write_new_marker(marker: Path, payload: dict[str, Any]) -> bool:
    """새 marker만 원자적으로 만든다. 이미 있으면 절대 바꾸지 않는다."""
    directory = marker.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SessionCompletionError(
            "session_completion_conflict", f"marker 디렉터리를 만들 수 없습니다: {exc}"
        ) from exc
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=directory, prefix=f".{marker.name}.", suffix=".tmp"
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8") + b"\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, marker)
        except FileExistsError:
            return False
        temporary.unlink()
        temporary = None
        directory_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return True
    except OSError as exc:
        raise SessionCompletionError(
            "session_completion_conflict", f"marker를 저장할 수 없습니다: {exc}"
        ) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _summarize(path: Path) -> dict:
    cwd = None
    started_at = None
    message_count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue  # 깨진 라인은 집계에서 제외(스캔은 보수적으로 계속)
            if cwd is None and payload.get("cwd"):
                cwd = payload["cwd"]
            if payload.get("type") in _MESSAGE_TYPES:
                message_count += 1
                if started_at is None:
                    started_at = payload.get("timestamp")
    return {
        "uuid": path.stem,
        "path": str(path),
        "cwd": cwd,
        "started_at": started_at,
        "message_count": message_count,
    }
