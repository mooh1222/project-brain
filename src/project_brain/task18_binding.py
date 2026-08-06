"""Task 18 display migration의 create-only 최종 상태 결속."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
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
    atomic_create_receipt,
    canonical_receipt_bytes,
)
from project_brain.id_grammar import IdGrammarError, parse_id
from project_brain.mutation import corpus_fingerprint
from project_brain.objbase import now_kst
from project_brain.snapshot import (
    GitDirtReceipt,
    SnapshotError,
    SnapshotVerification,
    capture_git_dirt_receipt,
    read_regular_no_follow,
    verify_snapshot,
)
from project_brain.store import BrainStore, StoreLoadError
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
TASK18_BINDING_KEYS = {
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
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_INPUT_KEYS = {
    "p0_handoff",
    "measurement",
    "design",
    "plan",
    "quote_debt",
    "snapshot_verify_receipt",
}
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
_SNAPSHOT_VERIFY_RECEIPT_KEYS = {
    "ok",
    "snapshot_id",
    "manifest_sha256",
    "file_count",
    "repo_head",
    "engine_head",
    "corpus_fingerprint",
}


class Task18BindingError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class Task18BindingRequest:
    binding_path: Path
    engine_root: Path
    repo_root: Path
    brain_root: Path
    expected_engine_head: str
    expected_repo_head: str
    expected_engine_status_sha256: str
    expected_engine_dirt_content_sha256: str
    expected_repo_status_sha256: str
    expected_repo_dirt_content_sha256: str
    local_target_ref: str
    remote: str
    remote_target_ref: str
    target_revision_sha: str
    p0_handoff_path: Path
    expected_p0_handoff_sha256: str
    measurement_path: Path
    expected_measurement_sha256: str
    design_path: Path
    design_commit_sha: str
    expected_design_file_sha256: str
    plan_path: Path
    plan_commit_sha: str
    expected_plan_file_sha256: str
    quote_debt_path: Path
    expected_quote_debt_sha256: str
    snapshot_root: Path
    expected_snapshot_manifest_sha256: str
    snapshot_verify_receipt_path: Path
    expected_snapshot_verify_receipt_sha256: str


@dataclass(frozen=True)
class Task18BindingCreateResult:
    path: Path
    sha256: str
    value: Mapping[str, object]


def _fail(code: str, detail: str = "") -> None:
    raise Task18BindingError(code, detail)


def _exact_absolute(path: Path, label: str) -> Path:
    value = Path(path)
    if not value.is_absolute() or value != Path(os.path.abspath(value)):
        _fail("binding_path_invalid", f"{label} must be exact absolute: {value}")
    return value


def _require_sha(value: str, label: str, *, git: bool = False) -> None:
    pattern = _GIT_SHA if git else _SHA256
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _fail("binding_request_invalid", f"{label} has an invalid digest")


def _validate_request(request: Task18BindingRequest) -> None:
    if not isinstance(request, Task18BindingRequest):
        _fail("binding_request_invalid", "request type is invalid")
    for field in (
        "binding_path",
        "engine_root",
        "repo_root",
        "brain_root",
        "p0_handoff_path",
        "measurement_path",
        "design_path",
        "plan_path",
        "quote_debt_path",
        "snapshot_root",
        "snapshot_verify_receipt_path",
    ):
        _exact_absolute(getattr(request, field), field)
    if not request.brain_root.is_relative_to(request.repo_root):
        _fail("binding_path_invalid", "brain_root must be inside repo_root")
    if not request.design_path.is_relative_to(request.engine_root):
        _fail("binding_path_invalid", "design_path must be inside engine_root")
    if not request.plan_path.is_relative_to(request.engine_root):
        _fail("binding_path_invalid", "plan_path must be inside engine_root")
    for field in (
        "expected_engine_head",
        "expected_repo_head",
        "target_revision_sha",
        "design_commit_sha",
        "plan_commit_sha",
    ):
        _require_sha(getattr(request, field), field, git=True)
    for field in (
        "expected_engine_status_sha256",
        "expected_engine_dirt_content_sha256",
        "expected_repo_status_sha256",
        "expected_repo_dirt_content_sha256",
        "expected_p0_handoff_sha256",
        "expected_measurement_sha256",
        "expected_design_file_sha256",
        "expected_plan_file_sha256",
        "expected_quote_debt_sha256",
        "expected_snapshot_manifest_sha256",
        "expected_snapshot_verify_receipt_sha256",
    ):
        _require_sha(getattr(request, field), field)
    if not all(
        isinstance(value, str) and value and "\0" not in value
        for value in (
            request.local_target_ref,
            request.remote,
            request.remote_target_ref,
        )
    ):
        _fail("binding_request_invalid", "remote ref fields must be non-empty")


def _json_sha(value: object) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _strict_json(data: bytes, *, label: str) -> object:
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
        _fail(f"{label}_json_invalid", str(exc))


def _read_canonical_json(
    path: Path,
    *,
    expected_sha256: str,
    label: str,
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    receipt = capture_bound_file(path)
    if receipt.get("sha256") != expected_sha256:
        _fail(f"{label}_sha256_mismatch")
    try:
        data, mode = read_regular_no_follow(path)
        value = _strict_json(data, label=label)
    except SnapshotError as exc:
        _fail(f"{label}_json_invalid", str(exc))
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        _fail(f"{label}_changed_during_capture")
    try:
        canonical = canonical_receipt_bytes(value) if isinstance(value, Mapping) else None
    except FoundationError as exc:
        _fail(f"{label}_json_invalid", exc.detail)
    if not isinstance(value, Mapping) or canonical != data:
        _fail(f"{label}_json_invalid", "document must be canonical JSON object")
    if receipt != {
        "path": str(path),
        "sha256": expected_sha256,
        "size": len(data),
        "mode": mode,
    }:
        _fail(f"{label}_changed_during_capture")
    return value, receipt


def _git_value(receipt: GitDirtReceipt, cached: Sequence[str]) -> dict[str, object]:
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


def _assert_git_expected(
    receipt: GitDirtReceipt,
    cached: Sequence[str],
    *,
    expected_head: str,
    expected_status_sha256: str,
    expected_content_sha256: str,
    label: str,
) -> None:
    if receipt.head != expected_head:
        _fail(f"{label}_head_mismatch")
    if receipt.status_sha256 != expected_status_sha256:
        _fail(f"{label}_status_mismatch")
    if receipt.content_manifest_sha256 != expected_content_sha256:
        _fail(f"{label}_dirt_content_mismatch")
    if tuple(cached):
        _fail(f"{label}_cached_paths_not_empty", repr(tuple(cached)))


def _ids(value: object, *, label: str) -> list[str]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not all(isinstance(item, str) and item for item in value)
    ):
        _fail("measurement_closure_mismatch", f"{label} IDs are invalid")
    result = list(value)
    if result != sorted(result) or len(result) != len(set(result)):
        _fail("measurement_closure_mismatch", f"{label} IDs are not canonical")
    return result


def _measurement_sections(
    measurement: Mapping[str, object],
) -> tuple[list[str], str, list[str], str, str]:
    display = measurement.get("display_labels")
    pairs = measurement.get("evidence_ref_pairs")
    quote = measurement.get("quote_backlog")
    if not all(isinstance(value, Mapping) for value in (display, pairs, quote)):
        _fail("measurement_closure_mismatch", "required measurement sections missing")
    assert isinstance(display, Mapping)
    assert isinstance(pairs, Mapping)
    assert isinstance(quote, Mapping)
    display_ids = _ids(display.get("target_ids"), label="display")
    display_hash = _json_sha(display_ids)
    if (
        type(display.get("target_count")) is not int
        or display.get("target_count") != len(display_ids)
        or display.get("target_ids_sha256") != display_hash
    ):
        _fail("measurement_closure_mismatch", "display metadata differs")
    pair_hash = pairs.get("pair_rows_sha256")
    if not isinstance(pair_hash, str) or _SHA256.fullmatch(pair_hash) is None:
        _fail("measurement_closure_mismatch", "pair rows hash is invalid")
    quote_ids = _ids(quote.get("target_ids"), label="quote debt")
    quote_hash = _json_sha(quote_ids)
    if (
        type(quote.get("target_count")) is not int
        or quote.get("target_count") != len(quote_ids)
        or quote.get("target_ids_sha256") != quote_hash
    ):
        _fail("measurement_closure_mismatch", "quote debt metadata differs")
    return display_ids, display_hash, quote_ids, quote_hash, pair_hash


def _inventory_quote_ids(
    inventory: Mapping[str, object],
) -> tuple[list[str], str]:
    if (
        set(inventory) != _QUOTE_INVENTORY_KEYS
        or type(inventory.get("version")) is not int
        or inventory.get("version") != 1
        or inventory.get("purpose") != "legacy_code_locator_quote_debt"
    ):
        _fail("quote_debt_inventory_invalid", "inventory exact shape differs")
    ids = _ids(inventory.get("quote_debt_ids"), label="inventory quote debt")
    digest = _json_sha(ids)
    if inventory.get("quote_debt_ids_sha256") != digest:
        _fail("measurement_closure_mismatch", "inventory quote debt hash differs")
    rows = inventory.get("rows")
    if (
        not isinstance(rows, Sequence)
        or isinstance(rows, (str, bytes, bytearray))
        or [row.get("locator_id") for row in rows if isinstance(row, Mapping)] != ids
        or len(rows) != len(ids)
    ):
        _fail("quote_debt_inventory_invalid", "inventory rows differ from IDs")
    return ids, digest


def _snapshot_verify_receipt_has_exact_schema(
    value: Mapping[str, object],
) -> bool:
    return (
        set(value) == _SNAPSHOT_VERIFY_RECEIPT_KEYS
        and value.get("ok") is True
        and isinstance(value.get("snapshot_id"), str)
        and bool(value.get("snapshot_id"))
        and type(value.get("file_count")) is int
        and value["file_count"] >= 0
        and isinstance(value.get("manifest_sha256"), str)
        and _SHA256.fullmatch(str(value["manifest_sha256"])) is not None
        and isinstance(value.get("repo_head"), str)
        and _GIT_SHA.fullmatch(str(value["repo_head"])) is not None
        and isinstance(value.get("engine_head"), str)
        and _GIT_SHA.fullmatch(str(value["engine_head"])) is not None
        and isinstance(value.get("corpus_fingerprint"), str)
        and _SHA256.fullmatch(str(value["corpus_fingerprint"])) is not None
    )


def _live_closure(
    store: BrainStore,
) -> tuple[list[dict[str, object]], list[str], str, list[str], str]:
    locators = {
        str(obj["id"]): obj
        for obj in store.by_kind("CodeLocator")
        if isinstance(obj.get("id"), str)
    }
    display_ids = sorted(
        object_id
        for object_id, obj in locators.items()
        if obj.get("title") != canonical_locator_title(obj)
    )
    pair_rows: list[dict[str, object]] = []
    evidence_targets: list[tuple[Mapping[str, object], str]] = []
    for obj in store.by_kind("EvidenceRef"):
        locator_id = paired_code_locator_id(obj)
        locator = locators.get(locator_id) if locator_id is not None else None
        if locator is None:
            continue
        canonical = canonical_locator_title(locator)
        pair_rows.append({
            "evidence_ref_id": obj.get("id"),
            "code_locator_id": locator_id,
            "titles_equal_now": obj.get("title") == locator.get("title"),
            "titles_equal_after_locator_canonicalization": obj.get("title") == canonical,
        })
        if obj.get("title") != canonical:
            evidence_targets.append((obj, locator_id))
    pair_rows.sort(key=lambda row: (str(row["evidence_ref_id"]), str(row["code_locator_id"])))

    targets: list[dict[str, object]] = []
    after_by_id = {str(obj["id"]): dict(obj) for obj in store.all()}
    for object_id in display_ids:
        obj = locators[object_id]
        source_sha = store.source_sha256(object_id)
        if not isinstance(source_sha, str) or _SHA256.fullmatch(source_sha) is None:
            _fail("measurement_closure_mismatch", f"source hash missing: {object_id}")
        expected_title = canonical_locator_title(obj)
        targets.append({
            "id": object_id,
            "kind": "CodeLocator",
            "paired_locator_id": None,
            "before_object_sha256": source_sha,
            "before_non_title_sha256": non_title_sha256(obj),
            "expected_title": expected_title,
        })
        after_by_id[object_id]["title"] = expected_title
    for obj, locator_id in evidence_targets:
        object_id = obj.get("id")
        if not isinstance(object_id, str) or not object_id:
            _fail("measurement_closure_mismatch", "paired EvidenceRef ID is invalid")
        source_sha = store.source_sha256(object_id)
        if not isinstance(source_sha, str) or _SHA256.fullmatch(source_sha) is None:
            _fail("measurement_closure_mismatch", f"source hash missing: {object_id}")
        expected_title = canonical_locator_title(locators[locator_id])
        targets.append({
            "id": object_id,
            "kind": "EvidenceRef",
            "paired_locator_id": locator_id,
            "before_object_sha256": source_sha,
            "before_non_title_sha256": non_title_sha256(obj),
            "expected_title": expected_title,
        })
        after_by_id[object_id]["title"] = expected_title
    targets.sort(key=lambda row: str(row["id"]))
    quote_ids = sorted(
        object_id
        for object_id, obj in locators.items()
        if "verified_quote" not in obj
    )
    after_store = BrainStore(after_by_id)
    return targets, display_ids, _json_sha(pair_rows), quote_ids, corpus_fingerprint(after_store)


def _assert_target_dirt_disjoint(
    *,
    target_paths: Mapping[str, str],
    bb2_git: GitDirtReceipt,
) -> None:
    try:
        rows = json.loads(bb2_git.content_manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail("bb2_dirt_manifest_invalid", str(exc))
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        _fail("bb2_dirt_manifest_invalid")
    dirt_paths = {row.get("path") for row in rows}
    overlap = sorted(set(target_paths.values()) & dirt_paths)
    if overlap:
        _fail("target_overlaps_user_dirt", repr(overlap))


def _scan_target_sources(
    *,
    brain_root: Path,
    repo_root: Path,
    targets: Sequence[Mapping[str, object]],
) -> dict[str, str]:
    """실제 corpus 파일에서 target ID별 repo 상대 경로를 결속한다."""
    expected = {str(row.get("id")): row for row in targets}
    if len(expected) != len(targets):
        _fail("migration_target_source_invalid", "duplicate target ID")
    for object_id, row in expected.items():
        kind = row.get("kind")
        try:
            parse_id(object_id, str(kind))
        except (IdGrammarError, TypeError) as exc:
            _fail("migration_target_source_invalid", f"{object_id}: {exc}")
    found: dict[str, str] = {}
    try:
        files = read_tracked_json_files(
            brain_root,
            set(BrainStore._KIND_DIR.values()),
        )
    except CorpusIOError as exc:
        _fail("migration_target_source_invalid", exc.detail)
    for path, data in files:
        try:
            if (
                not path.is_absolute()
                or path != Path(os.path.abspath(path))
                or not path.is_relative_to(brain_root)
                or not path.is_relative_to(repo_root)
            ):
                _fail("migration_target_source_invalid", f"unsafe source path: {path}")
            brain_relative = path.relative_to(brain_root)
            repo_relative = path.relative_to(repo_root)
            if (
                brain_relative.as_posix() in {"", "."}
                or repo_relative.as_posix() in {"", "."}
                or ".." in brain_relative.parts
                or ".." in repo_relative.parts
                or path.suffix != ".json"
            ):
                _fail("migration_target_source_invalid", f"unsafe source path: {path}")
            value = _strict_json(data, label="migration_target_source")
        except Task18BindingError as exc:
            _fail("migration_target_source_invalid", exc.detail or exc.code)
        if not isinstance(value, Mapping):
            _fail("migration_target_source_invalid", f"non-object source: {path}")
        object_id = value.get("id")
        if object_id not in expected:
            continue
        if object_id in found:
            _fail("migration_target_source_invalid", f"duplicate source: {object_id}")
        row = expected[str(object_id)]
        digest = hashlib.sha256(data).hexdigest()
        if value.get("kind") != row.get("kind") or digest != row.get(
            "before_object_sha256"
        ):
            _fail("migration_target_source_invalid", f"source mismatch: {object_id}")
        found[str(object_id)] = repo_relative.as_posix()
    missing = sorted(set(expected) - set(found))
    if missing:
        _fail("migration_target_source_invalid", f"missing sources: {missing!r}")
    return found


def _input_value(
    committed_receipt: Mapping[str, object],
    file_receipt: Mapping[str, object],
    *,
    commit_sha: str,
) -> dict[str, object]:
    if (
        committed_receipt.get("path") != file_receipt.get("path")
        or committed_receipt.get("file_sha256") != file_receipt.get("sha256")
        or committed_receipt.get("mode") != file_receipt.get("mode")
    ):
        _fail("committed_input_changed_during_capture")
    return {
        "path": file_receipt["path"],
        "sha256": file_receipt["sha256"],
        "size": file_receipt["size"],
        "mode": file_receipt["mode"],
        "commit_sha": commit_sha,
    }


def _dependency_error(exc: Exception) -> Task18BindingError:
    if isinstance(exc, (SnapshotError, FoundationError, Task18StateError, StoreLoadError)):
        return Task18BindingError(exc.code, getattr(exc, "detail", ""))
    return Task18BindingError("binding_state_capture_failed", str(exc))


def _recheck_before_create(
    request: Task18BindingRequest,
    *,
    input_receipts: Mapping[str, Mapping[str, object]],
    snapshot: SnapshotVerification,
    corpus_state: Mapping[str, object],
    remote: object,
    engine_git: GitDirtReceipt,
    bb2_git: GitDirtReceipt,
    engine_cached: Sequence[str],
    bb2_cached: Sequence[str],
) -> None:
    """출력 파일을 만들기 직전에 장시간 수집 구간 drift를 다시 확인한다."""
    paths = {
        "p0_handoff": request.p0_handoff_path,
        "measurement": request.measurement_path,
        "design": request.design_path,
        "plan": request.plan_path,
        "quote_debt": request.quote_debt_path,
        "snapshot_verify_receipt": request.snapshot_verify_receipt_path,
    }
    try:
        # 오래 걸리거나 외부 상태를 보는 검사는 먼저 끝낸다. 그 뒤 로컬
        # precondition을 짧은 전방/역방향 pass로 감싸 Task 7 재검증에 넘긴다.
        final_snapshot = verify_snapshot(
            request.snapshot_root,
            expected_manifest_sha256=request.expected_snapshot_manifest_sha256,
        )
        final_remote = capture_remote_ref(
            request.repo_root,
            local_ref=request.local_target_ref,
            remote=request.remote,
            remote_ref=request.remote_target_ref,
        )
        inputs_before = {
            label: capture_bound_file(path)
            for label, path in paths.items()
        }
        final_corpus = capture_task18_corpus_state(request.brain_root)
        final_engine_cached = capture_cached_paths(request.engine_root)
        final_bb2_cached = capture_cached_paths(request.repo_root)
        final_engine_git = capture_git_dirt_receipt(
            request.engine_root,
            label="engine",
        )
        final_bb2_git = capture_git_dirt_receipt(request.repo_root, label="bb2")
        inputs_after = {
            label: capture_bound_file(path)
            for label, path in reversed(tuple(paths.items()))
        }
    except Exception as exc:
        if isinstance(exc, Task18BindingError):
            raise
        raise _dependency_error(exc) from exc
    if (
        inputs_before != input_receipts
        or inputs_after != input_receipts
        or inputs_before != inputs_after
        or final_snapshot != snapshot
        or final_corpus != corpus_state
        or final_remote != remote
        or tuple(final_engine_cached) != tuple(engine_cached)
        or tuple(final_bb2_cached) != tuple(bb2_cached)
        or final_engine_git != engine_git
        or final_bb2_git != bb2_git
    ):
        _fail("state_changed_before_binding")


def create_task18_binding(
    request: Task18BindingRequest,
    *,
    clock: Callable[[], str] = now_kst,
) -> Task18BindingCreateResult:
    """현재 상태와 측정 closure가 정확히 같을 때 binding을 새로 만든다."""
    _validate_request(request)
    try:
        # 생성기 순서: Git -> remote -> corpus -> inputs -> snapshot -> live store.
        engine_git = capture_git_dirt_receipt(request.engine_root, label="engine")
        engine_cached = capture_cached_paths(request.engine_root)
        bb2_git = capture_git_dirt_receipt(request.repo_root, label="bb2")
        bb2_cached = capture_cached_paths(request.repo_root)
        remote = capture_remote_ref(
            request.repo_root,
            local_ref=request.local_target_ref,
            remote=request.remote,
            remote_ref=request.remote_target_ref,
        )
        corpus_state = capture_task18_corpus_state(request.brain_root)
        p0, p0_receipt = _read_canonical_json(
            request.p0_handoff_path,
            expected_sha256=request.expected_p0_handoff_sha256,
            label="p0_handoff",
        )
        measurement, measurement_receipt = _read_canonical_json(
            request.measurement_path,
            expected_sha256=request.expected_measurement_sha256,
            label="measurement",
        )
        quote_inventory, quote_receipt = _read_canonical_json(
            request.quote_debt_path,
            expected_sha256=request.expected_quote_debt_sha256,
            label="quote_debt",
        )
        verify_receipt, snapshot_verify_file = _read_canonical_json(
            request.snapshot_verify_receipt_path,
            expected_sha256=request.expected_snapshot_verify_receipt_sha256,
            label="snapshot_verify_receipt",
        )
        design = capture_committed_input(
            request.engine_root,
            request.design_path.relative_to(request.engine_root),
            request.design_commit_sha,
        )
        plan = capture_committed_input(
            request.engine_root,
            request.plan_path.relative_to(request.engine_root),
            request.plan_commit_sha,
        )
        design_file = capture_bound_file(request.design_path)
        plan_file = capture_bound_file(request.plan_path)
        snapshot = verify_snapshot(
            request.snapshot_root,
            expected_manifest_sha256=request.expected_snapshot_manifest_sha256,
        )
        store = BrainStore.load(request.brain_root)
    except Exception as exc:
        if isinstance(exc, Task18BindingError):
            raise
        raise _dependency_error(exc) from exc

    # caller가 고정한 기대값을 closure 해석보다 먼저 확인한다.
    _assert_git_expected(
        engine_git,
        engine_cached,
        expected_head=request.expected_engine_head,
        expected_status_sha256=request.expected_engine_status_sha256,
        expected_content_sha256=request.expected_engine_dirt_content_sha256,
        label="engine",
    )
    _assert_git_expected(
        bb2_git,
        bb2_cached,
        expected_head=request.expected_repo_head,
        expected_status_sha256=request.expected_repo_status_sha256,
        expected_content_sha256=request.expected_repo_dirt_content_sha256,
        label="bb2",
    )
    if (
        remote.local_sha != request.target_revision_sha
        or remote.remote_sha != request.target_revision_sha
    ):
        _fail("remote_ref_mismatch")
    if design.get("file_sha256") != request.expected_design_file_sha256:
        _fail("design_file_sha256_mismatch")
    if plan.get("file_sha256") != request.expected_plan_file_sha256:
        _fail("plan_file_sha256_mismatch")
    if (
        quote_inventory.get("measurement_path") != str(request.measurement_path)
        or quote_inventory.get("measurement_sha256")
        != request.expected_measurement_sha256
    ):
        _fail("quote_debt_measurement_mismatch")
    measurement_p0 = measurement.get("p0_handoff")
    if measurement_p0 != {
        "path": str(request.p0_handoff_path),
        "sha256": request.expected_p0_handoff_sha256,
    }:
        _fail("measurement_p0_handoff_mismatch")
    if not isinstance(p0, Mapping):
        _fail("p0_handoff_json_invalid")

    measured_display_ids, _, measured_quote_ids, measured_quote_hash, pair_hash = (
        _measurement_sections(measurement)
    )
    inventory_quote_ids, inventory_quote_hash = _inventory_quote_ids(quote_inventory)
    targets, live_display_ids, live_pair_hash, live_quote_ids, after_fingerprint = (
        _live_closure(store)
    )
    locator_count = sum(target["kind"] == "CodeLocator" for target in targets)
    ref_count = sum(target["kind"] == "EvidenceRef" for target in targets)
    if (
        live_display_ids != measured_display_ids
        or live_pair_hash != pair_hash
        or live_quote_ids != measured_quote_ids
        or live_quote_ids != inventory_quote_ids
        or measured_quote_hash != inventory_quote_hash
        or locator_count != REQUIRED_CODE_LOCATOR_COUNT
        or ref_count != REQUIRED_EVIDENCE_REF_COUNT
        or len(targets) != REQUIRED_CODE_LOCATOR_COUNT + REQUIRED_EVIDENCE_REF_COUNT
    ):
        _fail("measurement_closure_mismatch")
    target_paths = _scan_target_sources(
        brain_root=request.brain_root,
        repo_root=request.repo_root,
        targets=targets,
    )
    _assert_target_dirt_disjoint(
        target_paths=target_paths,
        bb2_git=bb2_git,
    )
    before_fingerprint = corpus_fingerprint(store)
    if corpus_state["corpus"].get("mutation_fingerprint") != before_fingerprint:
        _fail("corpus_fingerprint_mismatch")
    expected_verify_receipt = {
        "ok": True,
        "snapshot_id": snapshot.snapshot_id,
        "manifest_sha256": snapshot.manifest_sha256,
        "file_count": snapshot.file_count,
        "repo_head": snapshot.repo_head,
        "engine_head": snapshot.engine_head,
        "corpus_fingerprint": snapshot.corpus_fingerprint,
    }
    if (
        not _snapshot_verify_receipt_has_exact_schema(verify_receipt)
        or verify_receipt != expected_verify_receipt
    ):
        _fail("snapshot_verify_receipt_mismatch")
    if (
        snapshot.ok is not True
        or snapshot.repo_head != bb2_git.head
        or snapshot.engine_head != engine_git.head
        or snapshot.corpus_fingerprint != before_fingerprint
    ):
        _fail("snapshot_state_mismatch")

    inputs = {
        "p0_handoff": dict(p0_receipt),
        "measurement": dict(measurement_receipt),
        "design": _input_value(
            design,
            design_file,
            commit_sha=request.design_commit_sha,
        ),
        "plan": _input_value(
            plan,
            plan_file,
            commit_sha=request.plan_commit_sha,
        ),
        "quote_debt": dict(quote_receipt),
        "snapshot_verify_receipt": dict(snapshot_verify_file),
    }
    if set(inputs) != _INPUT_KEYS:
        _fail("binding_schema_invalid")
    value: dict[str, object] = {
        "version": 1,
        "purpose": "task18-display-labels-and-quote-debt-final-binding",
        "created_at": clock(),
        "task18_allowed": True,
        "roots": {
            "engine": str(request.engine_root),
            "bb2": str(request.repo_root),
            "brain": str(request.brain_root),
        },
        "engine": _git_value(engine_git, engine_cached),
        "bb2": _git_value(bb2_git, bb2_cached),
        "target_revision": {
            "local_ref": remote.local_ref,
            "local_sha": remote.local_sha,
            "remote": remote.remote,
            "remote_ref": remote.remote_ref,
            "remote_sha": remote.remote_sha,
            "target_revision_sha": request.target_revision_sha,
        },
        "corpus": dict(corpus_state["corpus"]),
        "search_index": dict(corpus_state["search_index"]),
        "stale_set": dict(corpus_state["stale_set"]),
        "inputs": inputs,
        "pre_mutation_snapshot": {
            "path": str(request.snapshot_root),
            "manifest_sha256": snapshot.manifest_sha256,
            "snapshot_id": snapshot.snapshot_id,
            "file_count": snapshot.file_count,
            "repo_head": snapshot.repo_head,
            "engine_head": snapshot.engine_head,
            "corpus_fingerprint": snapshot.corpus_fingerprint,
            "verify_receipt_path": str(request.snapshot_verify_receipt_path),
            "verify_receipt_sha256": request.expected_snapshot_verify_receipt_sha256,
        },
        "migration": {
            "target_ids_sha256": _json_sha([target["id"] for target in targets]),
            "targets_sha256": _json_sha(targets),
            "code_locator_count": locator_count,
            "evidence_ref_count": ref_count,
            "total_count": len(targets),
            "before_corpus_fingerprint": before_fingerprint,
            "expected_after_corpus_fingerprint": after_fingerprint,
            "targets": targets,
        },
    }
    if (
        set(value) != TASK18_BINDING_KEYS
        or value["task18_allowed"] is not True
        or not isinstance(value["created_at"], str)
        or not value["created_at"]
    ):
        _fail("binding_schema_invalid")
    _recheck_before_create(
        request,
        input_receipts={
            "p0_handoff": p0_receipt,
            "measurement": measurement_receipt,
            "design": design_file,
            "plan": plan_file,
            "quote_debt": quote_receipt,
            "snapshot_verify_receipt": snapshot_verify_file,
        },
        snapshot=snapshot,
        corpus_state=corpus_state,
        remote=remote,
        engine_git=engine_git,
        bb2_git=bb2_git,
        engine_cached=engine_cached,
        bb2_cached=bb2_cached,
    )
    try:
        binding_sha256 = atomic_create_receipt(request.binding_path, value)
    except FoundationError as exc:
        raise Task18BindingError(exc.code, exc.detail) from exc
    return Task18BindingCreateResult(request.binding_path, binding_sha256, value)
