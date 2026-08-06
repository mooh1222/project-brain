"""Task 18 final binding을 현재 상태에서 독립적으로 다시 검증한다."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from project_brain.corpus_io import CorpusIOError, read_tracked_json_files
from project_brain.display_contract import (
    canonical_locator_title,
    non_title_sha256,
    paired_code_locator_id,
)
from project_brain.foundation import (
    FoundationError,
    canonical_receipt_bytes,
)
from project_brain.id_grammar import IdGrammarError, parse_id
from project_brain.mutation import corpus_fingerprint
from project_brain.snapshot import (
    GitDirtReceipt,
    SnapshotError,
    capture_git_dirt_receipt,
    read_regular_no_follow,
    verify_snapshot,
)
from project_brain.store import BrainStore, StoreLoadError
from project_brain.task18_binding import Task18BindingError
from project_brain.task18_state import (
    Task18StateError,
    capture_bound_file,
    capture_cached_paths,
    capture_committed_input,
    capture_remote_ref,
    capture_task18_corpus_state,
)


REQUIRED_CODE_LOCATOR_COUNT = 3305
REQUIRED_EVIDENCE_REF_COUNT = 3186
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TOP_KEYS = {
    "version",
    "purpose",
    "created_at",
    "task18_allowed",
    "roots",
    "engine",
    "bb2",
    "target_revision",
    "corpus",
    "search_index",
    "stale_set",
    "inputs",
    "pre_mutation_snapshot",
    "migration",
}
_ROOT_KEYS = {"engine", "bb2", "brain"}
_GIT_KEYS = {
    "head",
    "status_bytes_base64",
    "status_sha256",
    "dirt_manifest_base64",
    "dirt_content_sha256",
    "cached_paths",
}
_TARGET_REVISION_KEYS = {
    "local_ref",
    "local_sha",
    "remote",
    "remote_ref",
    "remote_sha",
    "target_revision_sha",
}
_INPUT_KEYS = {
    "p0_handoff",
    "measurement",
    "design",
    "plan",
    "quote_debt",
    "snapshot_verify_receipt",
}
_FILE_KEYS = {"path", "sha256", "size", "mode"}
_COMMITTED_FILE_KEYS = _FILE_KEYS | {"commit_sha"}
_SNAPSHOT_KEYS = {
    "path",
    "manifest_sha256",
    "snapshot_id",
    "file_count",
    "repo_head",
    "engine_head",
    "corpus_fingerprint",
    "verify_receipt_path",
    "verify_receipt_sha256",
}
_MIGRATION_KEYS = {
    "target_ids_sha256",
    "targets_sha256",
    "code_locator_count",
    "evidence_ref_count",
    "total_count",
    "before_corpus_fingerprint",
    "expected_after_corpus_fingerprint",
    "targets",
}
_TARGET_KEYS = {
    "id",
    "kind",
    "paired_locator_id",
    "before_object_sha256",
    "before_non_title_sha256",
    "expected_title",
}
_CORPUS_KEYS = {
    "mutation_fingerprint",
    "objects_tree_sha256",
    "raw_tree_sha256",
}
_SEARCH_INDEX_KEYS = {
    "live_corpus_fingerprint",
    "meta_corpus_fingerprint",
    "db_file_sha256",
}
_STALE_SET_KEYS = {"sha256"}
_QUOTE_INVENTORY_KEYS = {
    "version",
    "purpose",
    "legacy_quote_semantics",
    "engine_sha",
    "repo_sha",
    "target_revision_sha",
    "brain_root",
    "index_db_path",
    "measurement_path",
    "measurement_sha256",
    "generated_at",
    "quote_debt_ids",
    "quote_debt_ids_sha256",
    "rows",
}
_SNAPSHOT_VERIFY_KEYS = {
    "ok",
    "snapshot_id",
    "manifest_sha256",
    "file_count",
    "repo_head",
    "engine_head",
    "corpus_fingerprint",
}


@dataclass(frozen=True)
class Task18BindingVerification:
    path: str
    sha256: str
    task18_allowed: bool
    snapshot_root: Path
    snapshot_manifest_sha256: str
    migration_targets: tuple[Mapping[str, object], ...]


def _fail(code: str, detail: str = "") -> None:
    raise Task18BindingError(code, detail)


def _exact_absolute(path: Path, label: str) -> Path:
    value = Path(path)
    if not value.is_absolute() or value != Path(os.path.abspath(value)):
        _fail("binding_path_invalid", f"{label} must be exact absolute: {value}")
    return value


def _json_sha(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _decode_base64(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        _fail("binding_schema_invalid", f"{label} must be base64 text")
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        _fail("binding_schema_invalid", f"{label}: {exc}")
    if base64.b64encode(data).decode("ascii") != value:
        _fail("binding_schema_invalid", f"{label} is not canonical base64")
    return data


def _strict_json(data: bytes, *, code: str) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(
            data,
            object_pairs_hook=pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON value: {value}")
            ),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        _fail(code, str(exc))


def _valid_file_receipt(value: object, *, committed: bool) -> bool:
    keys = _COMMITTED_FILE_KEYS if committed else _FILE_KEYS
    if not isinstance(value, Mapping) or set(value) != keys:
        return False
    return (
        isinstance(value.get("path"), str)
        and Path(str(value["path"])).is_absolute()
        and Path(str(value["path"]))
        == Path(os.path.abspath(str(value["path"])))
        and isinstance(value.get("sha256"), str)
        and _SHA256.fullmatch(str(value["sha256"])) is not None
        and type(value.get("size")) is int
        and value["size"] >= 0
        and type(value.get("mode")) is int
        and (
            not committed
            or (
                isinstance(value.get("commit_sha"), str)
                and re.fullmatch(r"[0-9a-f]{40}", str(value["commit_sha"]))
                is not None
            )
        )
    )


def _parse_binding(data: bytes) -> Mapping[str, object]:
    value = _strict_json(data, code="binding_json_invalid")
    try:
        canonical = canonical_receipt_bytes(value) if isinstance(value, Mapping) else None
    except FoundationError as exc:
        _fail("binding_json_invalid", exc.detail)
    if not isinstance(value, Mapping) or canonical != data:
        _fail("binding_json_invalid", "binding must be a canonical JSON object")
    if (
        set(value) != _TOP_KEYS
        or type(value.get("version")) is not int
        or value.get("version") != 1
        or value.get("purpose") != "task18-display-labels-and-quote-debt-final-binding"
        or value.get("task18_allowed") is not True
        or not isinstance(value.get("created_at"), str)
        or not value.get("created_at")
    ):
        _fail("binding_schema_invalid", "top-level shape differs")
    roots = value.get("roots")
    if (
        not isinstance(roots, Mapping)
        or set(roots) != _ROOT_KEYS
        or not all(isinstance(roots[key], str) for key in _ROOT_KEYS)
    ):
        _fail("binding_schema_invalid", "roots shape differs")
    if any(
        Path(str(roots[key])) != Path(os.path.abspath(str(roots[key])))
        for key in _ROOT_KEYS
    ):
        _fail("binding_schema_invalid", "roots are not exact absolute paths")
    for label in ("engine", "bb2"):
        git = value.get(label)
        if not isinstance(git, Mapping) or set(git) != _GIT_KEYS:
            _fail("binding_schema_invalid", f"{label} shape differs")
        status = _decode_base64(git.get("status_bytes_base64"), f"{label}.status")
        dirt = _decode_base64(git.get("dirt_manifest_base64"), f"{label}.dirt")
        if (
            not isinstance(git.get("head"), str)
            or re.fullmatch(r"[0-9a-f]{40}", str(git["head"])) is None
            or not isinstance(git.get("status_sha256"), str)
            or _SHA256.fullmatch(str(git["status_sha256"])) is None
            or not isinstance(git.get("dirt_content_sha256"), str)
            or _SHA256.fullmatch(str(git["dirt_content_sha256"])) is None
            or hashlib.sha256(status).hexdigest() != git.get("status_sha256")
            or hashlib.sha256(dirt).hexdigest() != git.get("dirt_content_sha256")
            or git.get("cached_paths") != []
        ):
            _fail("binding_schema_invalid", f"{label} bytes or cached paths differ")
    target = value.get("target_revision")
    if not isinstance(target, Mapping) or set(target) != _TARGET_REVISION_KEYS:
        _fail("binding_schema_invalid", "target revision shape differs")
    if (
        not all(
            isinstance(target.get(key), str) and target.get(key)
            for key in ("local_ref", "remote", "remote_ref")
        )
        or not all(
            isinstance(target.get(key), str)
            and re.fullmatch(r"[0-9a-f]{40}", str(target[key])) is not None
            for key in ("local_sha", "remote_sha", "target_revision_sha")
        )
    ):
        _fail("binding_schema_invalid", "target revision values differ")
    for label, keys in (
        ("corpus", _CORPUS_KEYS),
        ("search_index", _SEARCH_INDEX_KEYS),
        ("stale_set", _STALE_SET_KEYS),
    ):
        section = value.get(label)
        if (
            not isinstance(section, Mapping)
            or set(section) != keys
            or not all(
                isinstance(section.get(key), str)
                and _SHA256.fullmatch(str(section[key])) is not None
                for key in keys
            )
        ):
            _fail("binding_schema_invalid", f"{label} shape differs")
    inputs = value.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != _INPUT_KEYS:
        _fail("binding_schema_invalid", "inputs shape differs")
    for label in _INPUT_KEYS:
        if not _valid_file_receipt(
            inputs[label], committed=label in {"design", "plan"}
        ):
            _fail("binding_schema_invalid", f"input {label} shape differs")
    snapshot = value.get("pre_mutation_snapshot")
    if not isinstance(snapshot, Mapping) or set(snapshot) != _SNAPSHOT_KEYS:
        _fail("binding_schema_invalid", "snapshot shape differs")
    if (
        not isinstance(snapshot.get("path"), str)
        or Path(str(snapshot["path"]))
        != Path(os.path.abspath(str(snapshot["path"])))
        or type(snapshot.get("file_count")) is not int
        or snapshot["file_count"] < 0
        or not isinstance(snapshot.get("snapshot_id"), str)
        or not snapshot.get("snapshot_id")
        or not isinstance(snapshot.get("verify_receipt_path"), str)
        or Path(str(snapshot["verify_receipt_path"]))
        != Path(os.path.abspath(str(snapshot["verify_receipt_path"])))
        or not all(
            isinstance(snapshot.get(key), str)
            and re.fullmatch(r"[0-9a-f]{40}", str(snapshot[key])) is not None
            for key in ("repo_head", "engine_head")
        )
        or not all(
            isinstance(snapshot.get(key), str)
            and _SHA256.fullmatch(str(snapshot[key])) is not None
            for key in (
                "manifest_sha256",
                "corpus_fingerprint",
                "verify_receipt_sha256",
            )
        )
    ):
        _fail("binding_schema_invalid", "snapshot values differ")
    migration = value.get("migration")
    if not isinstance(migration, Mapping) or set(migration) != _MIGRATION_KEYS:
        _fail("binding_schema_invalid", "migration shape differs")
    targets = migration.get("targets")
    if (
        not isinstance(targets, Sequence)
        or isinstance(targets, (str, bytes, bytearray))
        or not all(isinstance(row, Mapping) and set(row) == _TARGET_KEYS for row in targets)
    ):
        _fail("binding_schema_invalid", "migration target shape differs")
    for row in targets:
        if (
            not isinstance(row.get("id"), str)
            or not row.get("id")
            or row.get("kind") not in {"CodeLocator", "EvidenceRef"}
            or (
                row.get("kind") == "CodeLocator"
                and row.get("paired_locator_id") is not None
            )
            or (
                row.get("kind") == "EvidenceRef"
                and (
                    not isinstance(row.get("paired_locator_id"), str)
                    or not row.get("paired_locator_id")
                )
            )
            or not isinstance(row.get("expected_title"), str)
            or not all(
                isinstance(row.get(key), str)
                and _SHA256.fullmatch(str(row[key])) is not None
                for key in ("before_object_sha256", "before_non_title_sha256")
            )
        ):
            _fail("binding_schema_invalid", "migration target values differ")
    target_ids = [row["id"] for row in targets]
    if (
        target_ids != sorted(target_ids)
        or len(target_ids) != len(set(target_ids))
        or migration.get("target_ids_sha256") != _json_sha(target_ids)
        or migration.get("targets_sha256") != _json_sha(targets)
        or type(migration.get("total_count")) is not int
        or migration.get("total_count") != len(targets)
        or type(migration.get("code_locator_count")) is not int
        or type(migration.get("evidence_ref_count")) is not int
        or migration.get("code_locator_count")
        != sum(row["kind"] == "CodeLocator" for row in targets)
        or migration.get("evidence_ref_count")
        != sum(row["kind"] == "EvidenceRef" for row in targets)
        or not all(
            isinstance(migration.get(key), str)
            and _SHA256.fullmatch(str(migration[key])) is not None
            for key in (
                "target_ids_sha256",
                "targets_sha256",
                "before_corpus_fingerprint",
                "expected_after_corpus_fingerprint",
            )
        )
    ):
        _fail("binding_schema_invalid", "migration summary differs")
    return value


def _read_document(path: Path, expected: Mapping[str, object], label: str) -> Mapping[str, object]:
    receipt = capture_bound_file(path)
    if receipt != expected:
        _fail(f"{label}_drift")
    try:
        data, mode = read_regular_no_follow(path)
        value = _strict_json(data, code=f"{label}_drift")
    except SnapshotError as exc:
        _fail(f"{label}_drift", str(exc))
    try:
        canonical = canonical_receipt_bytes(value) if isinstance(value, Mapping) else None
    except FoundationError as exc:
        _fail(f"{label}_drift", exc.detail)
    if (
        not isinstance(value, Mapping)
        or canonical != data
        or hashlib.sha256(data).hexdigest() != expected.get("sha256")
        or len(data) != expected.get("size")
        or mode != expected.get("mode")
    ):
        _fail(f"{label}_drift")
    return value


def _id_list(value: object, label: str) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not all(isinstance(item, str) and item for item in value)
    ):
        _fail("measurement_closure_mismatch", f"{label} IDs invalid")
    ids = list(value)
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        _fail("measurement_closure_mismatch", f"{label} IDs not canonical")
    return ids


def _measurement_contract(value: Mapping[str, object]) -> tuple[list[str], list[str], str]:
    display = value.get("display_labels")
    quote = value.get("quote_backlog")
    pairs = value.get("evidence_ref_pairs")
    if not all(isinstance(section, Mapping) for section in (display, quote, pairs)):
        _fail("measurement_closure_mismatch", "measurement sections missing")
    assert isinstance(display, Mapping)
    assert isinstance(quote, Mapping)
    assert isinstance(pairs, Mapping)
    display_ids = _id_list(display.get("target_ids"), "display")
    quote_ids = _id_list(quote.get("target_ids"), "quote debt")
    pair_hash = pairs.get("pair_rows_sha256")
    if (
        type(display.get("target_count")) is not int
        or display.get("target_count") != len(display_ids)
        or display.get("target_ids_sha256") != _json_sha(display_ids)
        or type(quote.get("target_count")) is not int
        or quote.get("target_count") != len(quote_ids)
        or quote.get("target_ids_sha256") != _json_sha(quote_ids)
        or not isinstance(pair_hash, str)
        or _SHA256.fullmatch(pair_hash) is None
    ):
        _fail("measurement_closure_mismatch", "measurement summary differs")
    return display_ids, quote_ids, pair_hash


def _inventory_contract(value: Mapping[str, object]) -> list[str]:
    if (
        set(value) != _QUOTE_INVENTORY_KEYS
        or type(value.get("version")) is not int
        or value.get("version") != 1
        or value.get("purpose") != "legacy_code_locator_quote_debt"
    ):
        _fail("quote_debt_inventory_invalid")
    ids = _id_list(value.get("quote_debt_ids"), "inventory quote debt")
    rows = value.get("rows")
    if (
        value.get("quote_debt_ids_sha256") != _json_sha(ids)
        or not isinstance(rows, Sequence)
        or isinstance(rows, (str, bytes, bytearray))
        or len(rows) != len(ids)
        or [row.get("locator_id") for row in rows if isinstance(row, Mapping)] != ids
    ):
        _fail("quote_debt_inventory_invalid")
    return ids


def _valid_snapshot_verify_document(value: Mapping[str, object]) -> bool:
    if set(value) != _SNAPSHOT_VERIFY_KEYS or value.get("ok") is not True:
        return False
    snapshot_id = value.get("snapshot_id")
    file_count = value.get("file_count")
    if (
        not isinstance(snapshot_id, str)
        or not snapshot_id
        or type(file_count) is not int
        or file_count < 0
    ):
        return False
    digest_fields = ("manifest_sha256", "corpus_fingerprint")
    head_fields = ("repo_head", "engine_head")
    return all(
        isinstance(value.get(field), str)
        and _SHA256.fullmatch(str(value[field])) is not None
        for field in digest_fields
    ) and all(
        isinstance(value.get(field), str)
        and re.fullmatch(r"[0-9a-f]{40}", str(value[field])) is not None
        for field in head_fields
    )


def _current_migration(
    store: BrainStore,
) -> tuple[list[dict[str, object]], list[str], list[str], str, str]:
    # 검증기는 전체 객체를 ID 순으로 한 번 돌며 generator의 kind별 순회를 재사용하지 않는다.
    objects = sorted(store.all(), key=lambda obj: str(obj.get("id")))
    locators = {
        str(obj["id"]): obj
        for obj in objects
        if obj.get("kind") == "CodeLocator" and isinstance(obj.get("id"), str)
    }
    display_ids: list[str] = []
    quote_ids: list[str] = []
    evidence: list[tuple[Mapping[str, object], str]] = []
    pair_rows: list[dict[str, object]] = []
    for obj in objects:
        object_id = obj.get("id")
        if obj.get("kind") == "CodeLocator":
            assert isinstance(object_id, str)
            if obj.get("title") != canonical_locator_title(obj):
                display_ids.append(object_id)
            if "verified_quote" not in obj:
                quote_ids.append(object_id)
            continue
        locator_id = paired_code_locator_id(obj)
        locator = locators.get(locator_id) if locator_id is not None else None
        if locator is None:
            continue
        canonical = canonical_locator_title(locator)
        pair_rows.append({
            "evidence_ref_id": object_id,
            "code_locator_id": locator_id,
            "titles_equal_now": obj.get("title") == locator.get("title"),
            "titles_equal_after_locator_canonicalization": obj.get("title") == canonical,
        })
        if obj.get("title") != canonical:
            evidence.append((obj, locator_id))
    pair_rows.sort(key=lambda row: (str(row["evidence_ref_id"]), str(row["code_locator_id"])))

    targets: list[dict[str, object]] = []
    after_objects = {str(obj["id"]): dict(obj) for obj in objects}
    for object_id in display_ids:
        obj = locators[object_id]
        source_sha = store.source_sha256(object_id)
        expected_title = canonical_locator_title(obj)
        targets.append({
            "id": object_id,
            "kind": "CodeLocator",
            "paired_locator_id": None,
            "before_object_sha256": source_sha,
            "before_non_title_sha256": non_title_sha256(obj),
            "expected_title": expected_title,
        })
        after_objects[object_id]["title"] = expected_title
    for obj, locator_id in evidence:
        object_id = str(obj["id"])
        expected_title = canonical_locator_title(locators[locator_id])
        targets.append({
            "id": object_id,
            "kind": "EvidenceRef",
            "paired_locator_id": locator_id,
            "before_object_sha256": store.source_sha256(object_id),
            "before_non_title_sha256": non_title_sha256(obj),
            "expected_title": expected_title,
        })
        after_objects[object_id]["title"] = expected_title
    targets.sort(key=lambda row: str(row["id"]))
    if any(
        not isinstance(row["before_object_sha256"], str)
        or _SHA256.fullmatch(str(row["before_object_sha256"])) is None
        for row in targets
    ):
        _fail("measurement_closure_mismatch", "source object hash missing")
    return (
        targets,
        display_ids,
        quote_ids,
        _json_sha(pair_rows),
        corpus_fingerprint(BrainStore(after_objects)),
    )


def _git_mapping(receipt: GitDirtReceipt, cached: Sequence[str]) -> dict[str, object]:
    return {
        "head": receipt.head,
        "status_bytes_base64": base64.b64encode(receipt.status_bytes).decode("ascii"),
        "status_sha256": receipt.status_sha256,
        "dirt_manifest_base64": base64.b64encode(
            receipt.content_manifest_bytes
        ).decode("ascii"),
        "dirt_content_sha256": receipt.content_manifest_sha256,
        "cached_paths": list(cached),
    }


def _assert_dirt_disjoint(
    *,
    target_paths: Mapping[str, str],
    receipt: GitDirtReceipt,
) -> None:
    try:
        rows = json.loads(receipt.content_manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail("bb2_dirt_manifest_invalid", str(exc))
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        _fail("bb2_dirt_manifest_invalid")
    dirt = {row.get("path") for row in rows}
    overlap = sorted(dirt & set(target_paths.values()))
    if overlap:
        _fail("target_overlaps_user_dirt", repr(overlap))


def _resolve_target_source_paths(
    *,
    brain_root: Path,
    repo_root: Path,
    targets: Sequence[Mapping[str, object]],
) -> dict[str, str]:
    """검증기 자체 순회로 실제 target source 경로와 bytes를 확인한다."""
    required: dict[str, Mapping[str, object]] = {}
    for row in targets:
        object_id = row.get("id")
        kind = row.get("kind")
        if not isinstance(object_id, str) or object_id in required:
            _fail("migration_target_source_invalid", "invalid or duplicate target ID")
        try:
            parse_id(object_id, str(kind))
        except (IdGrammarError, TypeError) as exc:
            _fail("migration_target_source_invalid", f"{object_id}: {exc}")
        required[object_id] = row
    resolved: dict[str, str] = {}
    try:
        scanned = read_tracked_json_files(
            brain_root,
            BrainStore._KIND_DIR.values(),
        )
    except CorpusIOError as exc:
        _fail("migration_target_source_invalid", exc.detail)
    for absolute, payload in scanned:
        if (
            not absolute.is_absolute()
            or absolute != Path(os.path.abspath(absolute))
            or not absolute.is_relative_to(brain_root)
            or not absolute.is_relative_to(repo_root)
            or absolute.suffix != ".json"
        ):
            _fail("migration_target_source_invalid", f"unsafe source path: {absolute}")
        brain_relative = absolute.relative_to(brain_root)
        repo_relative = absolute.relative_to(repo_root)
        if (
            ".." in brain_relative.parts
            or ".." in repo_relative.parts
            or brain_relative.as_posix() in {"", "."}
        ):
            _fail("migration_target_source_invalid", f"unsafe source path: {absolute}")
        parsed = _strict_json(payload, code="migration_target_source_invalid")
        if not isinstance(parsed, Mapping):
            _fail("migration_target_source_invalid", f"non-object source: {absolute}")
        object_id = parsed.get("id")
        if object_id not in required:
            continue
        assert isinstance(object_id, str)
        if object_id in resolved:
            _fail("migration_target_source_invalid", f"duplicate source: {object_id}")
        row = required[object_id]
        if (
            parsed.get("kind") != row.get("kind")
            or hashlib.sha256(payload).hexdigest()
            != row.get("before_object_sha256")
        ):
            _fail("migration_target_source_invalid", f"source mismatch: {object_id}")
        resolved[object_id] = repo_relative.as_posix()
    unresolved = sorted(set(required) - set(resolved))
    if unresolved:
        _fail("migration_target_source_invalid", f"missing sources: {unresolved!r}")
    return resolved


def _dependency_error(exc: Exception) -> Task18BindingError:
    if isinstance(exc, (SnapshotError, FoundationError, Task18StateError, StoreLoadError)):
        return Task18BindingError(exc.code, getattr(exc, "detail", ""))
    return Task18BindingError("binding_state_capture_failed", str(exc))


def _recheck_before_return(
    *,
    binding_path: Path,
    expected_binding_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    inputs: Mapping[str, Mapping[str, object]],
    snapshot_binding: Mapping[str, object],
    target_binding: Mapping[str, object],
    snapshot: object,
    corpus_state: Mapping[str, object],
    remote: object,
    engine_cached: Sequence[str],
    bb2_cached: Sequence[str],
    engine_git: GitDirtReceipt,
    bb2_git: GitDirtReceipt,
) -> None:
    expected_files = {
        label: {
            "path": receipt["path"],
            "sha256": receipt["sha256"],
            "size": receipt["size"],
            "mode": receipt["mode"],
        }
        for label, receipt in inputs.items()
    }
    try:
        # snapshot/remote처럼 오래 걸리거나 외부를 보는 검사를 먼저 끝낸다.
        # 로컬 mutable precondition은 corpus scan을 사이에 둔 reverse bracket이다.
        final_snapshot = verify_snapshot(
            Path(str(snapshot_binding["path"])),
            expected_manifest_sha256=str(snapshot_binding["manifest_sha256"]),
        )
        final_remote = capture_remote_ref(
            repo_root,
            local_ref=str(target_binding["local_ref"]),
            remote=str(target_binding["remote"]),
            remote_ref=str(target_binding["remote_ref"]),
        )
        files_before = {
            label: capture_bound_file(Path(str(receipt["path"])))
            for label, receipt in inputs.items()
        }
        final_corpus = capture_task18_corpus_state(brain_root)
        final_bb2_cached = capture_cached_paths(repo_root)
        final_engine_cached = capture_cached_paths(engine_root)
        final_bb2_git = capture_git_dirt_receipt(repo_root, label="bb2")
        final_engine_git = capture_git_dirt_receipt(engine_root, label="engine")
        final_binding_bytes, _ = read_regular_no_follow(binding_path)
        files_after = {
            label: capture_bound_file(Path(str(receipt["path"])))
            for label, receipt in reversed(tuple(inputs.items()))
        }
        rebound_binding_bytes, _ = read_regular_no_follow(binding_path)
    except Exception as exc:
        if isinstance(exc, Task18BindingError):
            raise
        raise _dependency_error(exc) from exc
    if (
        files_before != expected_files
        or files_after != expected_files
        or files_before != files_after
        or final_snapshot != snapshot
        or final_corpus != corpus_state
        or final_remote != remote
        or tuple(final_engine_cached) != tuple(engine_cached)
        or tuple(final_bb2_cached) != tuple(bb2_cached)
        or final_engine_git != engine_git
        or final_bb2_git != bb2_git
        or hashlib.sha256(final_binding_bytes).hexdigest()
        != expected_binding_sha256
        or rebound_binding_bytes != final_binding_bytes
    ):
        _fail("state_changed_during_verification")


def verify_task18_binding(
    *,
    binding_path: Path,
    expected_binding_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
) -> Task18BindingVerification:
    """binding bytes와 현재 상태를 생성기와 다른 순서로 다시 증명한다."""
    binding_path = _exact_absolute(binding_path, "binding_path")
    engine_root = _exact_absolute(engine_root, "engine_root")
    repo_root = _exact_absolute(repo_root, "repo_root")
    brain_root = _exact_absolute(brain_root, "brain_root")
    try:
        binding_bytes, _ = read_regular_no_follow(binding_path)
    except SnapshotError as exc:
        raise Task18BindingError(exc.code, exc.detail) from exc
    # 반드시 JSON parse보다 binding 자체 SHA를 먼저 확인한다.
    if hashlib.sha256(binding_bytes).hexdigest() != expected_binding_sha256:
        _fail("binding_sha256_mismatch")
    value = _parse_binding(binding_bytes)
    roots = value["roots"]
    assert isinstance(roots, Mapping)
    if roots != {
        "engine": str(engine_root),
        "bb2": str(repo_root),
        "brain": str(brain_root),
    }:
        _fail("binding_roots_mismatch")
    if not brain_root.is_relative_to(repo_root):
        _fail("binding_roots_mismatch")

    inputs = value["inputs"]
    snapshot_binding = value["pre_mutation_snapshot"]
    target_binding = value["target_revision"]
    assert isinstance(inputs, Mapping)
    assert isinstance(snapshot_binding, Mapping)
    assert isinstance(target_binding, Mapping)
    try:
        # 검증기 순서: inputs -> snapshot -> live store -> corpus -> remote -> cached -> Git.
        p0 = _read_document(
            Path(str(inputs["p0_handoff"]["path"])), inputs["p0_handoff"], "p0_handoff"
        )
        measurement = _read_document(
            Path(str(inputs["measurement"]["path"])), inputs["measurement"], "measurement"
        )
        quote_inventory = _read_document(
            Path(str(inputs["quote_debt"]["path"])), inputs["quote_debt"], "quote_debt"
        )
        snapshot_verify = _read_document(
            Path(str(inputs["snapshot_verify_receipt"]["path"])),
            inputs["snapshot_verify_receipt"],
            "snapshot_verify_receipt",
        )
        design_path = Path(str(inputs["design"]["path"]))
        plan_path = Path(str(inputs["plan"]["path"]))
        design = capture_committed_input(
            engine_root,
            design_path.relative_to(engine_root),
            str(inputs["design"]["commit_sha"]),
        )
        plan = capture_committed_input(
            engine_root,
            plan_path.relative_to(engine_root),
            str(inputs["plan"]["commit_sha"]),
        )
        design_file = capture_bound_file(design_path)
        plan_file = capture_bound_file(plan_path)
        snapshot = verify_snapshot(
            Path(str(snapshot_binding["path"])),
            expected_manifest_sha256=str(snapshot_binding["manifest_sha256"]),
        )
        store = BrainStore.load(brain_root)
        targets, display_ids, quote_ids, pair_hash, after_fingerprint = (
            _current_migration(store)
        )
        corpus_state = capture_task18_corpus_state(brain_root)
        remote = capture_remote_ref(
            repo_root,
            local_ref=str(target_binding["local_ref"]),
            remote=str(target_binding["remote"]),
            remote_ref=str(target_binding["remote_ref"]),
        )
        bb2_cached = capture_cached_paths(repo_root)
        engine_cached = capture_cached_paths(engine_root)
        bb2_git = capture_git_dirt_receipt(repo_root, label="bb2")
        engine_git = capture_git_dirt_receipt(engine_root, label="engine")
    except Exception as exc:
        if isinstance(exc, Task18BindingError):
            raise
        raise _dependency_error(exc) from exc

    if not isinstance(p0, Mapping):
        _fail("p0_handoff_drift")
    measured_display, measured_quote, measured_pair_hash = _measurement_contract(measurement)
    inventory_quote = _inventory_contract(quote_inventory)
    if (
        display_ids != measured_display
        or quote_ids != measured_quote
        or quote_ids != inventory_quote
        or pair_hash != measured_pair_hash
    ):
        _fail("measurement_closure_mismatch")
    p0_ref = measurement.get("p0_handoff")
    if p0_ref != {
        "path": inputs["p0_handoff"]["path"],
        "sha256": inputs["p0_handoff"]["sha256"],
    }:
        _fail("measurement_p0_handoff_mismatch")
    for label, actual in (("design", design), ("plan", plan)):
        bound = inputs[label]
        file_receipt = design_file if label == "design" else plan_file
        if (
            actual.get("path") != bound.get("path")
            or actual.get("commit_sha") != bound.get("commit_sha")
            or actual.get("file_sha256") != bound.get("sha256")
            or actual.get("mode") != bound.get("mode")
            or file_receipt != {
                "path": bound["path"],
                "sha256": bound["sha256"],
                "size": bound["size"],
                "mode": bound["mode"],
            }
        ):
            _fail(f"{label}_drift")
    if (
        quote_inventory.get("measurement_path") != inputs["measurement"]["path"]
        or quote_inventory.get("measurement_sha256")
        != inputs["measurement"]["sha256"]
    ):
        _fail("quote_debt_measurement_mismatch")
    expected_snapshot_verify = {
        "ok": True,
        "snapshot_id": snapshot.snapshot_id,
        "manifest_sha256": snapshot.manifest_sha256,
        "file_count": snapshot.file_count,
        "repo_head": snapshot.repo_head,
        "engine_head": snapshot.engine_head,
        "corpus_fingerprint": snapshot.corpus_fingerprint,
    }
    if (
        not _valid_snapshot_verify_document(snapshot_verify)
        or snapshot_verify != expected_snapshot_verify
    ):
        _fail("snapshot_verify_receipt_mismatch")
    before_fingerprint = corpus_fingerprint(store)
    if snapshot_binding != {
        "path": str(Path(str(snapshot_binding["path"]))),
        "manifest_sha256": snapshot.manifest_sha256,
        "snapshot_id": snapshot.snapshot_id,
        "file_count": snapshot.file_count,
        "repo_head": snapshot.repo_head,
        "engine_head": snapshot.engine_head,
        "corpus_fingerprint": snapshot.corpus_fingerprint,
        "verify_receipt_path": inputs["snapshot_verify_receipt"]["path"],
        "verify_receipt_sha256": inputs["snapshot_verify_receipt"]["sha256"],
    }:
        _fail("snapshot_state_mismatch")
    if (
        snapshot.ok is not True
        or snapshot.repo_head != bb2_git.head
        or snapshot.engine_head != engine_git.head
        or snapshot.corpus_fingerprint != before_fingerprint
    ):
        _fail("snapshot_state_mismatch")
    if corpus_state != {
        "corpus": value["corpus"],
        "search_index": value["search_index"],
        "stale_set": value["stale_set"],
    }:
        _fail("corpus_state_drift")
    if corpus_state["corpus"].get("mutation_fingerprint") != before_fingerprint:
        _fail("corpus_fingerprint_mismatch")
    if (
        remote.local_ref != target_binding["local_ref"]
        or remote.local_sha != target_binding["local_sha"]
        or remote.remote != target_binding["remote"]
        or remote.remote_ref != target_binding["remote_ref"]
        or remote.remote_sha != target_binding["remote_sha"]
        or remote.local_sha != target_binding["target_revision_sha"]
        or remote.remote_sha != target_binding["target_revision_sha"]
    ):
        _fail("remote_ref_mismatch")
    if _git_mapping(engine_git, engine_cached) != value["engine"]:
        _fail("engine_state_drift")
    if _git_mapping(bb2_git, bb2_cached) != value["bb2"]:
        _fail("bb2_state_drift")
    target_paths = _resolve_target_source_paths(
        brain_root=brain_root,
        repo_root=repo_root,
        targets=targets,
    )
    _assert_dirt_disjoint(target_paths=target_paths, receipt=bb2_git)
    locator_count = sum(row["kind"] == "CodeLocator" for row in targets)
    ref_count = sum(row["kind"] == "EvidenceRef" for row in targets)
    migration = value["migration"]
    expected_migration = {
        "target_ids_sha256": _json_sha([row["id"] for row in targets]),
        "targets_sha256": _json_sha(targets),
        "code_locator_count": locator_count,
        "evidence_ref_count": ref_count,
        "total_count": len(targets),
        "before_corpus_fingerprint": before_fingerprint,
        "expected_after_corpus_fingerprint": after_fingerprint,
        "targets": targets,
    }
    if (
        locator_count != REQUIRED_CODE_LOCATOR_COUNT
        or ref_count != REQUIRED_EVIDENCE_REF_COUNT
        or migration != expected_migration
    ):
        _fail("migration_binding_drift")
    _recheck_before_return(
        binding_path=binding_path,
        expected_binding_sha256=expected_binding_sha256,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        inputs=inputs,
        snapshot_binding=snapshot_binding,
        target_binding=target_binding,
        snapshot=snapshot,
        corpus_state=corpus_state,
        remote=remote,
        engine_cached=engine_cached,
        bb2_cached=bb2_cached,
        engine_git=engine_git,
        bb2_git=bb2_git,
    )
    return Task18BindingVerification(
        path=str(binding_path),
        sha256=expected_binding_sha256,
        task18_allowed=True,
        snapshot_root=Path(str(snapshot_binding["path"])),
        snapshot_manifest_sha256=str(snapshot_binding["manifest_sha256"]),
        migration_targets=tuple(targets),
    )
