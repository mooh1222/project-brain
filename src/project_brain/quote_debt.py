"""Legacy CodeLocator quote 부채의 결정론적 목록과 단계별 검증 계약.

목록에 든 legacy 객체는 적재 당시 검수됐지만, 현재 시점에 기계적으로 다시
대조할 quote가 없는 대상이다. 이 모듈은 그 집합과 불변 필드를 고정할 뿐,
quote가 있는 객체를 검사하는 ``verify_code_quotes``의 범위를 넓히지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Literal

from project_brain.display_contract import (
    canonical_locator_title,
    non_title_sha256,
    paired_code_locator_id,
)
from project_brain.foundation import canonical_receipt_bytes
from project_brain.id_grammar import IdGrammarError, parse_id
from project_brain.store import BrainStore
from project_brain.symbol_verify import is_canonical_symbol_shape


Phase = Literal["pre_migration", "post_migration"]
_PHASES = frozenset({"pre_migration", "post_migration"})
_AXIS_KEYS = (
    "stale",
    "unmerged_or_unverifiable",
    "line_range",
    "candidate",
    "noncanonical_symbol",
)


class QuoteDebtError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        message = code if not detail else f"{code}: {detail}"
        super().__init__(message)


def _fail(code: str, detail: str = "") -> None:
    raise QuoteDebtError(code, detail)


def _read_and_verify_measurement(
    path: Path,
    expected_sha256: str,
) -> Mapping[str, object]:
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        _fail("measurement_read_failed", str(exc))
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        _fail(
            "measurement_sha256_mismatch",
            f"expected {expected_sha256}, got {actual_sha256}",
        )
    try:
        value = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail("measurement_json_invalid", str(exc))
    if not isinstance(value, Mapping):
        _fail("measurement_json_invalid", "receipt must be a JSON object")
    if canonical_receipt_bytes(value) != data:
        _fail("measurement_not_canonical", "receipt bytes are not canonical")
    return value


def _quote_debt_ids_sha256(target_ids: Sequence[str]) -> str:
    data = json.dumps(
        list(target_ids),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _measurement_quote_debt(
    measurement: Mapping[str, object],
) -> tuple[list[str], str]:
    """고정 measurement의 quote_backlog ID/count/hash를 검증해 반환한다."""
    backlog = measurement.get("quote_backlog")
    if not isinstance(backlog, Mapping):
        _fail("measurement_quote_backlog_missing")
    target_ids = backlog.get("target_ids")
    if (
        not isinstance(target_ids, Sequence)
        or isinstance(target_ids, (str, bytes, bytearray))
        or not all(isinstance(value, str) and value for value in target_ids)
    ):
        _fail("measurement_quote_debt_ids_invalid")
    values = list(target_ids)
    if values != sorted(values) or len(values) != len(set(values)):
        _fail("measurement_quote_debt_ids_not_canonical")

    target_count = backlog.get("target_count")
    if (
        isinstance(target_count, bool)
        or not isinstance(target_count, int)
        or target_count != len(values)
    ):
        _fail("measurement_quote_debt_count_mismatch")
    target_ids_sha256 = backlog.get("target_ids_sha256")
    computed_sha256 = _quote_debt_ids_sha256(values)
    if target_ids_sha256 != computed_sha256:
        _fail("measurement_quote_debt_ids_sha256_mismatch")
    return values, computed_sha256


def _report_locator_ids(
    stale_report: Mapping[str, object],
    field: str,
) -> frozenset[str]:
    rows = stale_report[field]
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        _fail("stale_report_invalid", f"{field} must be an array")
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            _fail("stale_report_invalid", f"{field} row must be an object")
        locator_id = row.get("locator_id")
        if not isinstance(locator_id, str) or not locator_id:
            _fail("stale_report_invalid", f"{field} row requires locator_id")
        ids.add(locator_id)
    return frozenset(ids)


def _string_array(value: object) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and all(isinstance(item, str) and item for item in value)
    )


def _require_stale_row_strings(
    row: Mapping[str, object],
    fields: Sequence[str],
    *,
    row_name: str,
) -> None:
    if not all(isinstance(row.get(field), str) and row.get(field) for field in fields):
        _fail("stale_report_invalid", f"{row_name} requires {list(fields)!r}")


def _validate_fresh_stale_report(stale_report: Mapping[str, object]) -> None:
    required = {
        "target_head",
        "candidates",
        "locator_group",
        "unmerged_anchors",
        "coverage",
    }
    if not isinstance(stale_report, Mapping) or not required <= set(stale_report):
        _fail("stale_report_invalid", "fresh stale-check report keys are required")
    if not isinstance(stale_report.get("target_head"), str) or not stale_report[
        "target_head"
    ]:
        _fail("stale_report_invalid", "target_head must be a non-empty string")

    for field in ("candidates", "locator_group", "unmerged_anchors"):
        rows = stale_report[field]
        if not isinstance(rows, Sequence) or isinstance(
            rows, (str, bytes, bytearray)
        ):
            _fail("stale_report_invalid", f"{field} must be an array")

    for row in stale_report["candidates"]:
        if not isinstance(row, Mapping):
            _fail("stale_report_invalid", "candidate row must be an object")
        _require_stale_row_strings(row, ("mapping_id",), row_name="candidate")
        if row.get("mapping_key") is not None and not isinstance(
            row.get("mapping_key"), str
        ):
            _fail("stale_report_invalid", "candidate mapping_key is invalid")
        stale_locators = row.get("stale_locators")
        if not isinstance(stale_locators, Sequence) or isinstance(
            stale_locators, (str, bytes, bytearray)
        ):
            _fail("stale_report_invalid", "candidate stale_locators is invalid")
        for stale_locator in stale_locators:
            if not isinstance(stale_locator, Mapping):
                _fail("stale_report_invalid", "stale locator must be an object")
            _require_stale_row_strings(
                stale_locator,
                ("locator_id", "path", "change_type", "from_commit"),
                row_name="stale locator",
            )

    target_head = stale_report["target_head"]
    for row in stale_report["locator_group"]:
        if not isinstance(row, Mapping):
            _fail("stale_report_invalid", "locator_group row must be an object")
        _require_stale_row_strings(
            row,
            ("locator_id", "path", "from_commit", "target_head", "change_type"),
            row_name="locator_group",
        )
        if row.get("target_head") != target_head:
            _fail("stale_report_invalid", "locator row target_head mismatch")
        for field in (
            "blocking_affected_mapping_ids",
            "nonblocking_affected_mapping_ids",
        ):
            if not _string_array(row.get(field)):
                _fail("stale_report_invalid", f"locator_group {field} is invalid")

    for row in stale_report["unmerged_anchors"]:
        if not isinstance(row, Mapping):
            _fail("stale_report_invalid", "unmerged row must be an object")
        _require_stale_row_strings(
            row,
            ("locator_id", "path", "from_commit", "reason"),
            row_name="unmerged anchor",
        )
        if row.get("reason") not in {"not_ancestor", "anchor_unverifiable"}:
            _fail("stale_report_invalid", "unmerged reason is invalid")
        for field in (
            "blocking_affected_mapping_ids",
            "nonblocking_affected_mapping_ids",
        ):
            if not _string_array(row.get(field)):
                _fail("stale_report_invalid", f"unmerged {field} is invalid")

    coverage = stale_report["coverage"]
    if not isinstance(coverage, Mapping) or not {
        "covered_mappings",
        "uncovered_mappings",
    } <= set(coverage):
        _fail("stale_report_invalid", "coverage shape is invalid")
    if not _string_array(coverage.get("covered_mappings")):
        _fail("stale_report_invalid", "covered_mappings is invalid")
    uncovered = coverage.get("uncovered_mappings")
    if not isinstance(uncovered, Sequence) or isinstance(
        uncovered, (str, bytes, bytearray)
    ):
        _fail("stale_report_invalid", "uncovered_mappings is invalid")
    for row in uncovered:
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("mapping_id"), str)
            or row.get("skipped_reason") != "no_code_locator_ids"
            or not isinstance(row.get("has_code_evidence_ref"), bool)
        ):
            _fail("stale_report_invalid", "uncovered mapping row is invalid")


def _assert_stale_target(
    stale_report: Mapping[str, object],
    target_revision_sha: object,
) -> None:
    _validate_fresh_stale_report(stale_report)
    if (
        not isinstance(target_revision_sha, str)
        or not target_revision_sha
        or stale_report.get("target_head") != target_revision_sha
    ):
        _fail(
            "stale_report_target_mismatch",
            "stale_report must come from the exact target revision",
        )


def _context_for(locator: Mapping[str, object]) -> str:
    try:
        parsed = parse_id(locator.get("id"), "CodeLocator")
    except (IdGrammarError, TypeError) as exc:
        _fail("locator_id_invalid", str(exc))
    return str(parsed.ctx)


def _paired_refs_by_locator(existing: BrainStore) -> dict[str, list[dict[str, object]]]:
    refs: dict[str, list[dict[str, object]]] = {}
    for obj in existing.by_kind("EvidenceRef"):
        locator_id = paired_code_locator_id(obj)
        if locator_id is None or not existing.has(locator_id):
            continue
        locator = existing.get(locator_id)
        if locator.get("kind") != "CodeLocator":
            continue
        refs.setdefault(locator_id, []).append({
            "id": obj.get("id"),
            "title": obj.get("title"),
            "non_title_sha256": non_title_sha256(obj),
        })
    for values in refs.values():
        values.sort(key=lambda value: str(value["id"]))
    return refs


def _is_legacy_quote_debt(locator: Mapping[str, object]) -> bool:
    return "verified_quote" not in locator


def _build_sorted_quote_debt_rows(
    existing: BrainStore,
    *,
    stale_report: Mapping[str, object],
) -> list[dict[str, object]]:
    stale_ids = _report_locator_ids(stale_report, "locator_group")
    unmerged_ids = _report_locator_ids(stale_report, "unmerged_anchors")
    refs_by_locator = _paired_refs_by_locator(existing)
    rows: list[dict[str, object]] = []
    for locator in sorted(existing.by_kind("CodeLocator"), key=lambda obj: obj["id"]):
        if not _is_legacy_quote_debt(locator):
            continue
        locator_id = locator.get("id")
        if not isinstance(locator_id, str) or not locator_id:
            _fail("locator_id_invalid")
        rows.append({
            "locator_id": locator_id,
            "title": locator.get("title"),
            "non_title_sha256": non_title_sha256(locator),
            "paired_refs": refs_by_locator.get(locator_id, []),
            "context": _context_for(locator),
            "path": locator.get("path"),
            "symbol": locator.get("symbol"),
            "commit": locator.get("commit_sha"),
            "status": locator.get("status"),
            "source": locator.get("locator_source"),
            "axes": {
                "stale": locator_id in stale_ids,
                "unmerged_or_unverifiable": locator_id in unmerged_ids,
                "line_range": (
                    "line_start" in locator or "line_end" in locator
                ),
                "candidate": locator.get("status") == "candidate",
                "noncanonical_symbol": not is_canonical_symbol_shape(
                    locator.get("symbol")
                ),
            },
        })
    return rows


def _verify_measurement_id_sets(
    measurement: Mapping[str, object],
    rows: Sequence[Mapping[str, object]],
) -> tuple[list[str], str]:
    measured_ids, measured_ids_sha256 = _measurement_quote_debt(measurement)
    current_ids = [str(row["locator_id"]) for row in rows]
    if measured_ids != current_ids:
        _fail(
            "measurement_quote_debt_id_set_mismatch",
            f"measurement={measured_ids!r}, current={current_ids!r}",
        )
    return measured_ids, measured_ids_sha256


def build_quote_debt_inventory(
    existing: BrainStore,
    *,
    measurement_path: Path,
    expected_measurement_sha256: str,
    stale_report: Mapping[str, object],
    engine_sha: str,
    repo_sha: str,
    target_revision_sha: str,
    brain_root: Path,
    index_db_path: Path,
    generated_at: str,
) -> dict[str, object]:
    """측정 receipt와 현재 store를 같은 quote debt 집합으로 결속한다."""
    _assert_stale_target(stale_report, target_revision_sha)
    measurement = _read_and_verify_measurement(
        Path(measurement_path), expected_measurement_sha256
    )
    rows = _build_sorted_quote_debt_rows(existing, stale_report=stale_report)
    quote_debt_ids, quote_debt_ids_sha256 = _verify_measurement_id_sets(
        measurement, rows
    )
    value: dict[str, object] = {
        "version": 1,
        "purpose": "legacy_code_locator_quote_debt",
        "legacy_quote_semantics": (
            "reviewed at ingest, not mechanically re-checkable now"
        ),
        "engine_sha": engine_sha,
        "repo_sha": repo_sha,
        "target_revision_sha": target_revision_sha,
        "brain_root": str(Path(brain_root)),
        "index_db_path": str(Path(index_db_path)),
        "measurement_path": str(Path(measurement_path)),
        "measurement_sha256": expected_measurement_sha256,
        "generated_at": generated_at,
        "quote_debt_ids": quote_debt_ids,
        "quote_debt_ids_sha256": quote_debt_ids_sha256,
        "rows": rows,
    }
    canonical_receipt_bytes(value)
    return value


def _validate_inventory_shape(value: Mapping[str, object]) -> list[Mapping[str, object]]:
    rows = value.get("rows")
    quote_debt_ids = value.get("quote_debt_ids")
    if (
        not isinstance(rows, Sequence)
        or isinstance(rows, (str, bytes, bytearray))
        or not all(isinstance(row, Mapping) for row in rows)
    ):
        _fail("inventory_rows_invalid")
    if (
        not isinstance(quote_debt_ids, Sequence)
        or isinstance(quote_debt_ids, (str, bytes, bytearray))
        or not all(isinstance(value, str) and value for value in quote_debt_ids)
    ):
        _fail("inventory_quote_debt_ids_invalid")
    locator_ids = [row.get("locator_id") for row in rows]
    if (
        locator_ids != list(quote_debt_ids)
        or locator_ids != sorted(locator_ids)
        or len(locator_ids) != len(set(locator_ids))
    ):
        _fail("inventory_not_canonical", "row and quote debt ID order differ")
    if value.get("quote_debt_ids_sha256") != _quote_debt_ids_sha256(
        list(quote_debt_ids)
    ):
        _fail("inventory_quote_debt_ids_sha256_mismatch")
    for row in rows:
        axes = row.get("axes")
        if not isinstance(axes, Mapping) or set(axes) != set(_AXIS_KEYS):
            _fail("inventory_axes_invalid")
        if not all(isinstance(axes[key], bool) for key in _AXIS_KEYS):
            _fail("inventory_axes_invalid")
        paired_refs = row.get("paired_refs")
        if (
            not isinstance(paired_refs, Sequence)
            or isinstance(paired_refs, (str, bytes, bytearray))
            or not all(isinstance(ref, Mapping) for ref in paired_refs)
        ):
            _fail("inventory_paired_refs_invalid")
        paired_ids = [ref.get("id") for ref in paired_refs]
        if paired_ids != sorted(paired_ids):
            _fail("inventory_paired_refs_not_canonical")
    canonical_receipt_bytes(value)
    return list(rows)


def _authorized_post_rows(
    rows: Sequence[Mapping[str, object]],
    authorized_titles: Mapping[str, str],
    *,
    existing: BrainStore,
) -> list[dict[str, object]]:
    required_titles: dict[str, str] = {}
    for row in rows:
        canonical_title = canonical_locator_title({
            "id": row["locator_id"],
            "path": row.get("path"),
            "symbol": row.get("symbol"),
        })
        if row.get("title") != canonical_title:
            required_titles[str(row["locator_id"])] = canonical_title
        for ref in row["paired_refs"]:
            if ref.get("title") != canonical_title:
                required_titles[str(ref["id"])] = canonical_title
    if any(
        authorized_titles.get(object_id) != expected_title
        for object_id, expected_title in required_titles.items()
    ):
        _fail(
            "post_migration_authorized_titles_mismatch",
            "authorization must contain every required bound title migration",
        )

    # 전체 binding의 진위는 load_task18_post_authorization이 검증한다. 이 계층은
    # quote inventory 밖의 정상 display target을 재구성하지 않고, extra entry가
    # 현재 store의 실제 display 객체/title과 맞는지만 최소 방어한다.
    for object_id in sorted(set(authorized_titles) - set(required_titles)):
        if not existing.has(object_id):
            _fail("post_migration_authorization_extra_invalid", object_id)
        obj = existing.get(object_id)
        if obj.get("kind") == "CodeLocator":
            pass
        elif obj.get("kind") == "EvidenceRef":
            locator_id = paired_code_locator_id(obj)
            if (
                locator_id is None
                or not existing.has(locator_id)
                or existing.get(locator_id).get("kind") != "CodeLocator"
            ):
                _fail("post_migration_authorization_extra_invalid", object_id)
        else:
            _fail("post_migration_authorization_extra_invalid", object_id)
        if obj.get("title") != authorized_titles[object_id]:
            _fail("post_migration_authorization_extra_title_mismatch", object_id)

    expected_rows = deepcopy(list(rows))
    for row in expected_rows:
        locator_id = row["locator_id"]
        if locator_id in authorized_titles:
            row["title"] = authorized_titles[locator_id]
        for ref in row["paired_refs"]:
            ref_id = ref["id"]
            if ref_id in authorized_titles:
                ref["title"] = authorized_titles[ref_id]
    return expected_rows


def verify_quote_debt_inventory(
    value: Mapping[str, object],
    *,
    existing: BrainStore,
    stale_report: Mapping[str, object],
    phase: Phase,
    authorized_titles: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """현재 projection이 pre 원본 또는 허가된 post title 변경뿐인지 검증한다."""
    if phase not in _PHASES:
        _fail("phase_invalid", repr(phase))
    inventory_rows = _validate_inventory_shape(value)
    _assert_stale_target(stale_report, value.get("target_revision_sha"))
    if phase == "pre_migration" and authorized_titles is not None:
        _fail("pre_migration_does_not_accept_authorization")
    if phase == "post_migration" and authorized_titles is None:
        _fail("post_migration_requires_authorized_titles")
    if authorized_titles is not None and (
        not isinstance(authorized_titles, Mapping)
        or not all(
            isinstance(key, str) and key and isinstance(title, str)
            for key, title in authorized_titles.items()
        )
    ):
        _fail("authorized_titles_invalid")

    current_rows = _build_sorted_quote_debt_rows(
        existing, stale_report=stale_report
    )
    expected_rows = list(inventory_rows)
    if phase == "post_migration":
        assert authorized_titles is not None
        expected_rows = _authorized_post_rows(
            expected_rows,
            authorized_titles,
            existing=existing,
        )
    if current_rows != expected_rows:
        _fail(
            "quote_debt_projection_mismatch",
            "current rows differ outside the phase authorization",
        )
    current_ids = [row["locator_id"] for row in current_rows]
    if current_ids != list(value["quote_debt_ids"]):
        _fail("quote_debt_projection_id_set_mismatch")

    inventory_sha256 = hashlib.sha256(canonical_receipt_bytes(value)).hexdigest()
    return {
        "ok": True,
        "phase": phase,
        "inventory_sha256": inventory_sha256,
        "quote_debt_count": len(current_ids),
    }
