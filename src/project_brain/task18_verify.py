"""Task 18 적용 뒤 상태와 최종 closure를 독립적으로 검증한다.

pre-apply binding 검증기는 live corpus가 snapshot과 같은지를 전제로 한다. 이 모듈은
그 전제를 느슨하게 바꾸지 않고, 같은 binding bytes를 별도로 해석해 결속된 title 변경만
허용하는 post-apply 검증 경계를 제공한다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType

from project_brain.corpus_io import (
    CorpusIOError,
    assert_corpus_readable,
    corpus_lock,
    read_tracked_json_files,
)
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
from project_brain.lint import lint_store
from project_brain.mutation import corpus_fingerprint
from project_brain.objbase import now_kst
from project_brain.reference_fields import iter_object_refs
from project_brain.snapshot import (
    SnapshotError,
    capture_git_dirt_receipt,
    decode_nul_paths,
    read_regular_no_follow,
    require_commit_is_ancestor,
    run_git_bytes,
    verify_git_dirt_preserved,
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


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
_TOP_KEYS = {
    "version", "purpose", "created_at", "task18_allowed", "roots",
    "engine", "bb2", "target_revision", "corpus", "search_index",
    "stale_set", "inputs", "pre_mutation_snapshot", "migration",
}
_ROOT_KEYS = {"engine", "bb2", "brain"}
_GIT_KEYS = {
    "head", "status_bytes_base64", "status_sha256",
    "dirt_manifest_base64", "dirt_content_sha256", "cached_paths",
}
_TARGET_REVISION_KEYS = {
    "local_ref", "local_sha", "remote", "remote_ref", "remote_sha",
    "target_revision_sha",
}
_INPUT_KEYS = {
    "p0_handoff", "measurement", "design", "plan", "quote_debt",
    "snapshot_verify_receipt",
}
_FILE_KEYS = {"path", "sha256", "size", "mode"}
_SNAPSHOT_KEYS = {
    "path", "manifest_sha256", "snapshot_id", "file_count", "repo_head",
    "engine_head", "corpus_fingerprint", "verify_receipt_path",
    "verify_receipt_sha256",
}
_MIGRATION_KEYS = {
    "target_ids_sha256", "targets_sha256", "code_locator_count",
    "evidence_ref_count", "total_count", "before_corpus_fingerprint",
    "expected_after_corpus_fingerprint", "targets",
}
_TARGET_KEYS = {
    "id", "kind", "paired_locator_id", "before_object_sha256",
    "before_non_title_sha256", "expected_title",
}
_DISPLAY_MANIFEST_KEYS = {
    "migration_version", "migration_kind", "intent", "snapshot_id",
    "snapshot_manifest_sha256", "task18_binding_path",
    "task18_binding_sha256",
}
_POST_REPORT_KEYS = {
    "version", "purpose", "generated_at", "binding", "display_manifest",
    "quote_debt", "target_ids_sha256", "expected_after_corpus_fingerprint",
    "actual_after_corpus_fingerprint", "raw_tree_sha256", "object_count", "changed_paths",
    "update_count", "create_count", "delete_count", "rename_count",
    "reference_graph", "lint_problem_count", "pairs", "quote_debt_state",
    "noncanonical_symbol_state", "search_index", "stale_set_sha256", "git",
    "quote_debt_unchanged", "noncanonical_symbols_unchanged",
    "index_db_unchanged", "user_dirt_preserved",
}
_CLOSURE_KEYS = {
    "version", "purpose", "created_at", "roots", "corpus_final_snapshot",
    "artifacts", "heads", "git", "committed_docs",
}
_CLOSURE_ROOT_KEYS = {"engine", "bb2", "brain"}
_CLOSURE_SNAPSHOT_KEYS = {
    "path", "manifest_sha256", "snapshot_id", "file_count", "verify_receipt",
}
_CLOSURE_ARTIFACT_KEYS = {"binding", "display_manifest", "post_report"}
_CLOSURE_HEAD_KEYS = {"implementation", "corpus", "docs"}
_CLOSURE_GIT_KEYS = {
    "engine_cached_empty", "bb2_cached_empty", "engine_status_sha256",
    "engine_dirt_content_sha256", "bb2_status_sha256",
    "bb2_dirt_content_sha256",
}
_CLOSURE_DOC_KEYS = {"completion_report", "roadmap"}
REQUIRED_CODE_LOCATOR_COUNT = 3305
REQUIRED_EVIDENCE_REF_COUNT = 3186
REQUIRED_TARGET_COUNT = 6491
REQUIRED_QUOTE_DEBT_COUNT = 3307
REQUIRED_NONCANONICAL_SYMBOL_COUNT = 289
REQUIRED_PAIR_COUNT = 3202
_SNAPSHOT_VERIFY_RECEIPT_KEYS = {
    "ok", "snapshot_id", "manifest_sha256", "file_count", "repo_head",
    "engine_head", "corpus_fingerprint",
}


class Task18VerificationError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class ParsedTask18Binding:
    path: Path
    sha256: str
    value: Mapping[str, object]
    engine_root: Path
    repo_root: Path
    brain_root: Path
    snapshot_root: Path
    snapshot_manifest_sha256: str
    migration_targets: tuple[Mapping[str, object], ...]
    target_ids_sha256: str
    expected_after_corpus_fingerprint: str
    baseline_status_bytes: bytes
    baseline_dirt_manifest_bytes: bytes


@dataclass(frozen=True)
class Task18PostVerification:
    update_count: int
    quote_debt_unchanged: bool
    noncanonical_symbols_unchanged: bool
    index_db_unchanged: bool
    user_dirt_preserved: bool
    report_path: Path
    report_sha256: str


@dataclass(frozen=True)
class Task18PostAuthorization:
    binding_path: Path
    binding_sha256: str
    expected_titles: Mapping[str, str]
    target_ids_sha256: str


@dataclass(frozen=True)
class Task18ClosureResult:
    closure_path: Path
    closure_sha256: str
    report_path: Path
    report_sha256: str
    ok: bool = True


@dataclass(frozen=True)
class Task18JsonDocument:
    data: bytes
    value: Mapping[str, object]
    sha256: str
    mode: int


@dataclass(frozen=True)
class _PostInvariantStats:
    object_count: int
    actual_after_fingerprint: str
    raw_tree_sha256: str
    reference_edge_count: int
    reference_graph_sha256: str
    pair_count: int
    quote_count: int
    quote_ids_sha256: str
    symbol_count: int
    symbol_ids_sha256: str
    search_index: Mapping[str, object]
    stale_set_sha256: str


@dataclass(frozen=True)
class _FinalCorpusEvidence:
    object_count: int
    corpus_fingerprint: str
    raw_tree_sha256: str
    changed_paths: tuple[str, ...]
    quote_count: int
    quote_ids_sha256: str
    symbol_count: int
    symbol_ids_sha256: str
    reference_edge_count: int
    reference_graph_sha256: str


def _fail(code: str, detail: str = "") -> None:
    raise Task18VerificationError(code, detail)


def _dependency(exc: Exception) -> Task18VerificationError:
    if isinstance(exc, Task18VerificationError):
        return exc
    if isinstance(
        exc,
        (SnapshotError, FoundationError, Task18StateError, StoreLoadError, CorpusIOError),
    ):
        return Task18VerificationError(exc.code, getattr(exc, "detail", ""))
    return Task18VerificationError("task18_state_capture_failed", str(exc))


def _bound_raw_tree_sha256(binding: Mapping[str, object]) -> str:
    corpus = binding.get("corpus")
    raw_tree_sha256 = corpus.get("raw_tree_sha256") if isinstance(corpus, Mapping) else None
    if (
        not isinstance(raw_tree_sha256, str)
        or _SHA256.fullmatch(raw_tree_sha256) is None
    ):
        _fail("binding_schema_invalid", "corpus.raw_tree_sha256 is invalid")
    return raw_tree_sha256


def _raw_tree_sha256_from_state(
    state: Mapping[str, object],
    *,
    label: str,
) -> str:
    corpus = state.get("corpus")
    raw_tree_sha256 = corpus.get("raw_tree_sha256") if isinstance(corpus, Mapping) else None
    if (
        not isinstance(raw_tree_sha256, str)
        or _SHA256.fullmatch(raw_tree_sha256) is None
    ):
        _fail(f"{label}_raw_tree_state_invalid")
    return raw_tree_sha256


def _capture_matching_raw_tree_sha256(
    *,
    brain_root: Path,
    binding: Mapping[str, object],
    label: str,
) -> str:
    try:
        state = capture_task18_corpus_state(brain_root)
    except Exception as exc:
        raise _dependency(exc) from exc
    raw_tree_sha256 = _raw_tree_sha256_from_state(state, label=label)
    if raw_tree_sha256 != _bound_raw_tree_sha256(binding):
        _fail(f"{label}_raw_tree_sha256_mismatch")
    return raw_tree_sha256


def _exact_absolute(path: Path, label: str) -> Path:
    value = Path(path)
    if not value.is_absolute() or value != Path(os.path.abspath(value)):
        _fail("path_invalid", f"{label} must be exact absolute: {value}")
    return value


def _json_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _strict_json(data: bytes, code: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
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


def read_task18_json_bytes(
    path: Path,
    *,
    expected_sha256: str | None,
    label: str,
) -> Task18JsonDocument:
    try:
        data, mode = read_regular_no_follow(path)
    except SnapshotError as exc:
        raise _dependency(exc) from exc
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        _fail(f"{label}_sha256_mismatch")
    value = _strict_json(data, f"{label}_json_invalid")
    if not isinstance(value, Mapping):
        _fail(f"{label}_json_invalid", "document must be a JSON object")
    return Task18JsonDocument(data=data, value=value, sha256=actual_sha256, mode=mode)


def read_task18_canonical_document(
    path: Path,
    expected_sha256: str,
    *,
    label: str,
) -> Mapping[str, object]:
    document = read_task18_json_bytes(
        path,
        expected_sha256=expected_sha256,
        label=label,
    )
    value = document.value
    try:
        canonical = canonical_receipt_bytes(value)
    except FoundationError as exc:
        raise _dependency(exc) from exc
    if canonical != document.data:
        _fail(f"{label}_json_invalid", "document must be canonical JSON")
    return value


def _canonical_document(path: Path, expected_sha256: str, label: str) -> Mapping[str, object]:
    return read_task18_canonical_document(
        path,
        expected_sha256,
        label=label,
    )


def _decode_bound_bytes(section: Mapping[str, object], field: str) -> bytes:
    value = section.get(field)
    if not isinstance(value, str):
        _fail("binding_schema_invalid", field)
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        _fail("binding_schema_invalid", f"{field}: {exc}")
    if base64.b64encode(data).decode("ascii") != value:
        _fail("binding_schema_invalid", f"{field} is not canonical base64")
    return data


def _valid_file_receipt(value: object, *, committed: bool = False) -> bool:
    keys = _FILE_KEYS | ({"commit_sha"} if committed else set())
    return (
        isinstance(value, Mapping)
        and set(value) == keys
        and isinstance(value.get("path"), str)
        and Path(str(value["path"])).is_absolute()
        and Path(str(value["path"])) == Path(os.path.abspath(str(value["path"])))
        and isinstance(value.get("sha256"), str)
        and _SHA256.fullmatch(str(value["sha256"])) is not None
        and type(value.get("size")) is int
        and int(value["size"]) >= 0
        and type(value.get("mode")) is int
        and (
            not committed
            or (
                isinstance(value.get("commit_sha"), str)
                and _GIT_SHA.fullmatch(str(value["commit_sha"])) is not None
            )
        )
    )


def _valid_snapshot_verify_receipt(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == _SNAPSHOT_VERIFY_RECEIPT_KEYS
        and value.get("ok") is True
        and isinstance(value.get("snapshot_id"), str)
        and bool(value.get("snapshot_id"))
        and type(value.get("file_count")) is int
        and int(value["file_count"]) >= 0
        and all(
            isinstance(value.get(key), str)
            and _GIT_SHA.fullmatch(str(value[key])) is not None
            for key in ("repo_head", "engine_head")
        )
        and all(
            isinstance(value.get(key), str)
            and _SHA256.fullmatch(str(value[key])) is not None
            for key in ("manifest_sha256", "corpus_fingerprint")
        )
    )


def _read_bound_file_once(
    bound: Mapping[str, object],
    *,
    label: str,
) -> bytes:
    path = Path(str(bound["path"]))
    try:
        data, mode = read_regular_no_follow(path)
    except SnapshotError as exc:
        raise _dependency(exc) from exc
    current = {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "mode": mode,
    }
    if current != {key: bound[key] for key in _FILE_KEYS}:
        _fail(f"{label}_drift")
    return data


def _parse_binding_bytes(data: bytes) -> Mapping[str, object]:
    value = _strict_json(data, "binding_json_invalid")
    try:
        canonical = canonical_receipt_bytes(value) if isinstance(value, Mapping) else None
    except FoundationError as exc:
        raise _dependency(exc) from exc
    if not isinstance(value, Mapping) or canonical != data:
        _fail("binding_json_invalid", "binding must be canonical JSON")
    if (
        set(value) != _TOP_KEYS
        or type(value.get("version")) is not int
        or not _exact_int(value.get("version"), expected=1)
        or value.get("purpose") != "task18-display-labels-and-quote-debt-final-binding"
        or value.get("task18_allowed") is not True
        or not isinstance(value.get("created_at"), str)
        or not value.get("created_at")
    ):
        _fail("binding_schema_invalid", "top-level shape differs")
    roots = value.get("roots")
    if not isinstance(roots, Mapping) or set(roots) != _ROOT_KEYS:
        _fail("binding_schema_invalid", "roots shape differs")
    if any(
        not isinstance(roots.get(key), str)
        or Path(str(roots[key])) != Path(os.path.abspath(str(roots[key])))
        for key in _ROOT_KEYS
    ):
        _fail("binding_schema_invalid", "roots are not exact absolute paths")
    for label in ("engine", "bb2"):
        section = value.get(label)
        if not isinstance(section, Mapping) or set(section) != _GIT_KEYS:
            _fail("binding_schema_invalid", f"{label} shape differs")
        status = _decode_bound_bytes(section, "status_bytes_base64")
        dirt = _decode_bound_bytes(section, "dirt_manifest_base64")
        if (
            not isinstance(section.get("head"), str)
            or _GIT_SHA.fullmatch(str(section["head"])) is None
            or hashlib.sha256(status).hexdigest() != section.get("status_sha256")
            or hashlib.sha256(dirt).hexdigest() != section.get("dirt_content_sha256")
            or section.get("cached_paths") != []
        ):
            _fail("binding_schema_invalid", f"{label} bytes differ")
    target_revision = value.get("target_revision")
    if not isinstance(target_revision, Mapping) or set(target_revision) != _TARGET_REVISION_KEYS:
        _fail("binding_schema_invalid", "target revision shape differs")
    if not all(
        isinstance(target_revision.get(key), str) and target_revision.get(key)
        for key in ("local_ref", "remote", "remote_ref")
    ) or not all(
        isinstance(target_revision.get(key), str)
        and _GIT_SHA.fullmatch(str(target_revision[key])) is not None
        for key in ("local_sha", "remote_sha", "target_revision_sha")
    ):
        _fail("binding_schema_invalid", "target revision values differ")
    for label, keys in (
        ("corpus", {"mutation_fingerprint", "objects_tree_sha256", "raw_tree_sha256"}),
        ("search_index", {"live_corpus_fingerprint", "meta_corpus_fingerprint", "db_file_sha256"}),
        ("stale_set", {"sha256"}),
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
        if not _valid_file_receipt(inputs[label], committed=label in {"design", "plan"}):
            _fail("binding_schema_invalid", f"input {label} shape differs")
    snapshot = value.get("pre_mutation_snapshot")
    if not isinstance(snapshot, Mapping) or set(snapshot) != _SNAPSHOT_KEYS:
        _fail("binding_schema_invalid", "snapshot shape differs")
    if (
        not isinstance(snapshot.get("path"), str)
        or Path(str(snapshot["path"])) != Path(os.path.abspath(str(snapshot["path"])))
        or type(snapshot.get("file_count")) is not int
        or int(snapshot["file_count"]) < 0
        or not isinstance(snapshot.get("snapshot_id"), str)
        or not snapshot.get("snapshot_id")
        or not isinstance(snapshot.get("verify_receipt_path"), str)
        or Path(str(snapshot["verify_receipt_path"]))
        != Path(os.path.abspath(str(snapshot["verify_receipt_path"])))
        or not all(
            isinstance(snapshot.get(key), str)
            and _GIT_SHA.fullmatch(str(snapshot[key])) is not None
            for key in ("repo_head", "engine_head")
        )
        or not all(
            isinstance(snapshot.get(key), str)
            and _SHA256.fullmatch(str(snapshot[key])) is not None
            for key in ("manifest_sha256", "corpus_fingerprint", "verify_receipt_sha256")
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
        _fail("binding_schema_invalid", "migration targets differ")
    ids = [row.get("id") for row in targets]
    if (
        not all(isinstance(object_id, str) and object_id for object_id in ids)
        or ids != sorted(ids)
        or len(ids) != len(set(ids))
        or migration.get("target_ids_sha256") != _json_sha(ids)
        or migration.get("targets_sha256") != _json_sha(targets)
        or type(migration.get("total_count")) is not int
        or migration.get("total_count") != len(targets)
        or type(migration.get("code_locator_count")) is not int
        or type(migration.get("evidence_ref_count")) is not int
        or migration.get("code_locator_count")
        != sum(row.get("kind") == "CodeLocator" for row in targets)
        or migration.get("evidence_ref_count")
        != sum(row.get("kind") == "EvidenceRef" for row in targets)
        or migration.get("code_locator_count") != REQUIRED_CODE_LOCATOR_COUNT
        or migration.get("evidence_ref_count") != REQUIRED_EVIDENCE_REF_COUNT
        or len(targets) != REQUIRED_TARGET_COUNT
        or REQUIRED_TARGET_COUNT
        != REQUIRED_CODE_LOCATOR_COUNT + REQUIRED_EVIDENCE_REF_COUNT
    ):
        _fail("binding_schema_invalid", "migration summary differs")
    for row in targets:
        if (
            row.get("kind") not in {"CodeLocator", "EvidenceRef"}
            or not isinstance(row.get("expected_title"), str)
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
            or not all(
                isinstance(row.get(key), str)
                and _SHA256.fullmatch(str(row[key])) is not None
                for key in ("before_object_sha256", "before_non_title_sha256")
            )
        ):
            _fail("binding_schema_invalid", "migration target values differ")
    return value


def _assert_bound_control_state(value: Mapping[str, object], *, engine_root: Path, repo_root: Path) -> None:
    inputs = value["inputs"]
    snapshot_section = value["pre_mutation_snapshot"]
    target = value["target_revision"]
    assert isinstance(inputs, Mapping)
    assert isinstance(snapshot_section, Mapping)
    assert isinstance(target, Mapping)
    try:
        bound_input_bytes: dict[str, bytes] = {}
        for label in _INPUT_KEYS - {"design", "plan"}:
            bound = inputs[label]
            assert isinstance(bound, Mapping)
            bound_input_bytes[label] = _read_bound_file_once(bound, label=label)
        for label in ("design", "plan"):
            bound = inputs[label]
            assert isinstance(bound, Mapping)
            path = Path(str(bound["path"]))
            committed = capture_committed_input(
                engine_root,
                path.relative_to(engine_root),
                str(bound["commit_sha"]),
            )
            current = capture_bound_file(path)
            if (
                committed.get("path") != bound.get("path")
                or committed.get("commit_sha") != bound.get("commit_sha")
                or committed.get("file_sha256") != bound.get("sha256")
                or committed.get("mode") != bound.get("mode")
                or current != {key: bound[key] for key in _FILE_KEYS}
            ):
                _fail(f"{label}_drift")
        snapshot = verify_snapshot(
            Path(str(snapshot_section["path"])),
            expected_manifest_sha256=str(snapshot_section["manifest_sha256"]),
        )
        remote = capture_remote_ref(
            repo_root,
            local_ref=str(target["local_ref"]),
            remote=str(target["remote"]),
            remote_ref=str(target["remote_ref"]),
        )
        engine_git = capture_git_dirt_receipt(engine_root, label="engine")
        bb2_git = capture_git_dirt_receipt(repo_root, label="bb2")
        if capture_cached_paths(engine_root) or capture_cached_paths(repo_root):
            _fail("cached_paths_not_empty")
    except Exception as exc:
        raise _dependency(exc) from exc
    engine_bound = value["engine"]
    bb2_bound = value["bb2"]
    assert isinstance(engine_bound, Mapping)
    assert isinstance(bb2_bound, Mapping)
    verify_bound = inputs["snapshot_verify_receipt"]
    assert isinstance(verify_bound, Mapping)
    verify_value = _strict_json(
        bound_input_bytes["snapshot_verify_receipt"],
        "snapshot_verify_receipt_json_invalid",
    )
    if (
        not isinstance(verify_value, Mapping)
        or canonical_receipt_bytes(verify_value)
        != bound_input_bytes["snapshot_verify_receipt"]
    ):
        _fail("snapshot_verify_receipt_json_invalid")
    expected_verify = {
        "ok": True,
        "snapshot_id": snapshot.snapshot_id,
        "manifest_sha256": snapshot.manifest_sha256,
        "file_count": snapshot.file_count,
        "repo_head": snapshot.repo_head,
        "engine_head": snapshot.engine_head,
        "corpus_fingerprint": snapshot.corpus_fingerprint,
    }
    if (
        not _valid_snapshot_verify_receipt(verify_value)
        or verify_value != expected_verify
        or snapshot.ok is not True
        or snapshot.snapshot_id != snapshot_section["snapshot_id"]
        or snapshot.repo_head != snapshot_section["repo_head"]
        or snapshot.engine_head != snapshot_section["engine_head"]
        or remote.local_sha != target["local_sha"]
        or remote.remote_sha != target["remote_sha"]
        or remote.local_sha != target["target_revision_sha"]
        or engine_git.head != engine_bound["head"]
        or engine_git.status_bytes != _decode_bound_bytes(engine_bound, "status_bytes_base64")
        or engine_git.content_manifest_bytes
        != _decode_bound_bytes(engine_bound, "dirt_manifest_base64")
        or bb2_git.head != bb2_bound["head"]
    ):
        _fail("binding_control_state_drift")


def parse_task18_binding_for_post_verify(
    *,
    binding_path: Path,
    expected_binding_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
) -> ParsedTask18Binding:
    """post 의미로 binding bytes와 바뀌지 않아야 할 control state를 검증한다."""
    binding_path = _exact_absolute(binding_path, "binding_path")
    engine_root = _exact_absolute(engine_root, "engine_root")
    repo_root = _exact_absolute(repo_root, "repo_root")
    brain_root = _exact_absolute(brain_root, "brain_root")
    if not isinstance(expected_binding_sha256, str) or _SHA256.fullmatch(expected_binding_sha256) is None:
        _fail("binding_sha256_invalid")
    try:
        data, _ = read_regular_no_follow(binding_path)
    except SnapshotError as exc:
        raise _dependency(exc) from exc
    if hashlib.sha256(data).hexdigest() != expected_binding_sha256:
        _fail("binding_sha256_mismatch")
    value = _parse_binding_bytes(data)
    roots = value["roots"]
    assert isinstance(roots, Mapping)
    if roots != {
        "engine": str(engine_root),
        "bb2": str(repo_root),
        "brain": str(brain_root),
    } or not brain_root.is_relative_to(repo_root):
        _fail("binding_roots_mismatch")
    _assert_bound_control_state(value, engine_root=engine_root, repo_root=repo_root)
    migration = value["migration"]
    snapshot = value["pre_mutation_snapshot"]
    bb2 = value["bb2"]
    assert isinstance(migration, Mapping)
    assert isinstance(snapshot, Mapping)
    assert isinstance(bb2, Mapping)
    targets = tuple(dict(row) for row in migration["targets"])
    return ParsedTask18Binding(
        path=binding_path,
        sha256=expected_binding_sha256,
        value=value,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        snapshot_root=Path(str(snapshot["path"])),
        snapshot_manifest_sha256=str(snapshot["manifest_sha256"]),
        migration_targets=targets,
        target_ids_sha256=str(migration["target_ids_sha256"]),
        expected_after_corpus_fingerprint=str(migration["expected_after_corpus_fingerprint"]),
        baseline_status_bytes=_decode_bound_bytes(bb2, "status_bytes_base64"),
        baseline_dirt_manifest_bytes=_decode_bound_bytes(bb2, "dirt_manifest_base64"),
    )


def load_task18_post_authorization(
    *,
    binding_path: Path,
    expected_binding_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
) -> Task18PostAuthorization:
    binding = parse_task18_binding_for_post_verify(
        binding_path=binding_path,
        expected_binding_sha256=expected_binding_sha256,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
    )
    titles = {
        str(row["id"]): str(row["expected_title"])
        for row in binding.migration_targets
    }
    return Task18PostAuthorization(
        binding_path=binding.path,
        binding_sha256=binding.sha256,
        expected_titles=MappingProxyType(titles),
        target_ids_sha256=binding.target_ids_sha256,
    )


def _read_display_manifest(path: Path, expected_sha256: str, binding: ParsedTask18Binding) -> Mapping[str, object]:
    value = _canonical_document(path, expected_sha256, "display_manifest")
    if (
        set(value) != _DISPLAY_MANIFEST_KEYS
        or not _exact_int(value.get("migration_version"), expected=3)
        or value.get("migration_kind") != "display_only"
        or not isinstance(value.get("intent"), Mapping)
        or value.get("task18_binding_path") != str(binding.path)
        or value.get("task18_binding_sha256") != binding.sha256
    ):
        _fail("display_manifest_invalid")
    snapshot = binding.value.get("pre_mutation_snapshot")
    if isinstance(snapshot, Mapping) and (
        value.get("snapshot_id") != snapshot.get("snapshot_id")
        or value.get("snapshot_manifest_sha256") != binding.snapshot_manifest_sha256
    ):
        _fail("display_manifest_snapshot_mismatch")
    return value


def _snapshot_object_sources_all(
    binding: ParsedTask18Binding,
) -> dict[str, tuple[str, bytes, Mapping[str, object]]]:
    try:
        manifest_data, _ = read_regular_no_follow(binding.snapshot_root / "manifest.json")
    except SnapshotError as exc:
        raise _dependency(exc) from exc
    manifest = _strict_json(manifest_data, "snapshot_manifest_invalid")
    files = manifest.get("files") if isinstance(manifest, Mapping) else None
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes, bytearray)):
        _fail("snapshot_manifest_invalid")
    result: dict[str, tuple[str, bytes, Mapping[str, object]]] = {}
    for entry in files:
        if not isinstance(entry, Mapping) or entry.get("scope") != "brain":
            continue
        relative = entry.get("path")
        snapshot_relative = entry.get("snapshot_path")
        if (
            not isinstance(relative, str)
            or not isinstance(snapshot_relative, str)
            or not any(
                relative.startswith(f"{directory}/")
                for directory in BrainStore._KIND_DIR.values()
            )
        ):
            continue
        try:
            payload, _ = read_regular_no_follow(binding.snapshot_root / snapshot_relative)
        except SnapshotError as exc:
            raise _dependency(exc) from exc
        value = _strict_json(payload, "snapshot_object_invalid")
        object_id = value.get("id") if isinstance(value, Mapping) else None
        if not isinstance(object_id, str) or not object_id or object_id in result:
            _fail("snapshot_object_set_invalid", str(object_id))
        result[object_id] = (relative, payload, value)
    return result


def _live_object_sources_all(
    brain_root: Path,
) -> dict[str, tuple[str, bytes, Mapping[str, object]]]:
    try:
        files = read_tracked_json_files(brain_root, BrainStore._KIND_DIR.values())
    except CorpusIOError as exc:
        raise _dependency(exc) from exc
    result: dict[str, tuple[str, bytes, Mapping[str, object]]] = {}
    for path, payload in files:
        value = _strict_json(payload, "live_object_invalid")
        object_id = value.get("id") if isinstance(value, Mapping) else None
        if not isinstance(object_id, str) or not object_id or object_id in result:
            _fail("live_object_set_invalid", str(object_id))
        result[object_id] = (path.relative_to(brain_root).as_posix(), payload, value)
    return result


def _store_from_sources(
    sources: Mapping[str, tuple[str, bytes, Mapping[str, object]]],
) -> BrainStore:
    return BrainStore(
        {object_id: dict(item[2]) for object_id, item in sources.items()},
        source_sha256_by_id={
            object_id: hashlib.sha256(item[1]).hexdigest()
            for object_id, item in sources.items()
        },
    )


def _reference_graph(store: BrainStore) -> tuple[int, str]:
    rows = sorted(
        (str(obj["id"]), ref.pointer, ref.object_id)
        for obj in store.all()
        for ref in iter_object_refs(obj)
    )
    return len(rows), _json_sha(rows)


def _exact_int(value: object, *, expected: int | None = None, minimum: int | None = None) -> bool:
    if type(value) is not int:
        return False
    if expected is not None and value != expected:
        return False
    return minimum is None or value >= minimum


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value or "T" not in value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _canonical_value_equal(left: object, right: object) -> bool:
    try:
        return json.dumps(
            left,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") == json.dumps(
            right,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return False


def _closure_snapshot_sources(
    binding: Mapping[str, object],
    *,
    label: str,
) -> tuple[
    dict[str, tuple[str, bytes, Mapping[str, object]]],
    str,
]:
    snapshot = binding.get("pre_mutation_snapshot")
    if not isinstance(snapshot, Mapping):
        _fail("binding_schema_invalid", "pre_mutation_snapshot missing")
    snapshot_root = Path(str(snapshot.get("path")))
    try:
        manifest_data, _ = read_regular_no_follow(snapshot_root / "manifest.json")
    except SnapshotError as exc:
        raise _dependency(exc) from exc
    manifest = _strict_json(manifest_data, f"{label}_snapshot_manifest_invalid")
    files = manifest.get("files") if isinstance(manifest, Mapping) else None
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes, bytearray)):
        _fail(f"{label}_snapshot_manifest_invalid")
    sources: dict[str, tuple[str, bytes, Mapping[str, object]]] = {}
    for entry in files:
        if not isinstance(entry, Mapping) or entry.get("scope") != "brain":
            continue
        relative = entry.get("path")
        snapshot_relative = entry.get("snapshot_path")
        if (
            not isinstance(relative, str)
            or not isinstance(snapshot_relative, str)
            or Path(relative).is_absolute()
            or Path(snapshot_relative).is_absolute()
            or ".." in Path(relative).parts
            or ".." in Path(snapshot_relative).parts
            or not any(
                relative.startswith(f"{directory}/")
                for directory in BrainStore._KIND_DIR.values()
            )
        ):
            continue
        try:
            payload, _ = read_regular_no_follow(snapshot_root / snapshot_relative)
        except SnapshotError as exc:
            raise _dependency(exc) from exc
        if (
            entry.get("sha256") != hashlib.sha256(payload).hexdigest()
            or not _exact_int(entry.get("size"), expected=len(payload))
        ):
            _fail(f"{label}_snapshot_object_receipt_mismatch", relative)
        value = _strict_json(payload, f"{label}_snapshot_object_invalid")
        object_id = value.get("id") if isinstance(value, Mapping) else None
        if not isinstance(object_id, str) or not object_id or object_id in sources:
            _fail(f"{label}_snapshot_object_set_invalid", str(object_id))
        sources[object_id] = (relative, payload, value)
    return sources, hashlib.sha256(manifest_data).hexdigest()


def _final_corpus_evidence(
    *,
    brain_root: Path,
    repo_root: Path,
    binding: Mapping[str, object],
) -> _FinalCorpusEvidence:
    migration = binding.get("migration")
    if not isinstance(migration, Mapping):
        _fail("binding_schema_invalid", "migration missing")
    targets = migration.get("targets")
    if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes, bytearray)):
        _fail("binding_schema_invalid", "migration targets missing")
    with corpus_lock(brain_root, exclusive=False):
        assert_corpus_readable(brain_root)
        raw_tree_sha256 = _capture_matching_raw_tree_sha256(
            brain_root=brain_root,
            binding=binding,
            label="closure_create",
        )
        sources = _live_object_sources_all(brain_root)
        target_ids = [str(row["id"]) for row in targets if isinstance(row, Mapping)]
        if len(target_ids) != len(targets) or not set(target_ids).issubset(sources):
            _fail("final_corpus_target_set_mismatch")
        store = _store_from_sources(sources)
        quote_ids = sorted(
            str(obj["id"])
            for obj in store.by_kind("CodeLocator")
            if "verified_quote" not in obj
        )
        symbol_ids = _noncanonical_symbol_ids(store)
        edge_count, graph_sha = _reference_graph(store)
        changed_paths = tuple(
            (brain_root / sources[object_id][0]).relative_to(repo_root).as_posix()
            for object_id in target_ids
        )
        return _FinalCorpusEvidence(
            object_count=len(store.all()),
            corpus_fingerprint=corpus_fingerprint(store),
            raw_tree_sha256=raw_tree_sha256,
            changed_paths=changed_paths,
            quote_count=len(quote_ids),
            quote_ids_sha256=_json_sha(quote_ids),
            symbol_count=len(symbol_ids),
            symbol_ids_sha256=_json_sha(symbol_ids),
            reference_edge_count=edge_count,
            reference_graph_sha256=graph_sha,
        )


def _final_corpus_evidence_independent(
    *,
    brain_root: Path,
    repo_root: Path,
    binding: Mapping[str, object],
) -> _FinalCorpusEvidence:
    """closure verify가 현재 raw/object 상태를 생성 경로와 별도로 다시 계산한다."""
    migration = binding.get("migration")
    corpus = binding.get("corpus")
    if not isinstance(migration, Mapping) or not isinstance(corpus, Mapping):
        _fail("binding_schema_invalid")
    targets = migration.get("targets")
    bound_raw_tree_sha256 = corpus.get("raw_tree_sha256")
    if (
        not isinstance(targets, Sequence)
        or isinstance(targets, (str, bytes, bytearray))
        or not isinstance(bound_raw_tree_sha256, str)
        or _SHA256.fullmatch(bound_raw_tree_sha256) is None
    ):
        _fail("binding_schema_invalid")
    with corpus_lock(brain_root, exclusive=False):
        assert_corpus_readable(brain_root)
        try:
            current_state = capture_task18_corpus_state(brain_root)
        except Exception as exc:
            raise _dependency(exc) from exc
        current_corpus = current_state.get("corpus")
        current_raw_tree_sha256 = (
            current_corpus.get("raw_tree_sha256")
            if isinstance(current_corpus, Mapping)
            else None
        )
        if (
            not isinstance(current_raw_tree_sha256, str)
            or _SHA256.fullmatch(current_raw_tree_sha256) is None
        ):
            _fail("closure_verify_raw_tree_state_invalid")
        if current_raw_tree_sha256 != bound_raw_tree_sha256:
            _fail("closure_verify_raw_tree_sha256_mismatch")

        sources = _live_object_sources_all(brain_root)
        target_ids = [str(row["id"]) for row in targets if isinstance(row, Mapping)]
        if len(target_ids) != len(targets) or not set(target_ids).issubset(sources):
            _fail("final_corpus_target_set_mismatch")
        store = _store_from_sources(sources)
        quote_ids = sorted(
            str(obj["id"])
            for obj in store.by_kind("CodeLocator")
            if "verified_quote" not in obj
        )
        symbol_ids = _noncanonical_symbol_ids(store)
        edge_count, graph_sha = _reference_graph(store)
        changed_paths = tuple(
            (brain_root / sources[object_id][0]).relative_to(repo_root).as_posix()
            for object_id in target_ids
        )
        return _FinalCorpusEvidence(
            object_count=len(store.all()),
            corpus_fingerprint=corpus_fingerprint(store),
            raw_tree_sha256=current_raw_tree_sha256,
            changed_paths=changed_paths,
            quote_count=len(quote_ids),
            quote_ids_sha256=_json_sha(quote_ids),
            symbol_count=len(symbol_ids),
            symbol_ids_sha256=_json_sha(symbol_ids),
            reference_edge_count=edge_count,
            reference_graph_sha256=graph_sha,
        )


def _validate_create_closure_semantics(
    *,
    binding: Mapping[str, object],
    manifest: Mapping[str, object],
    brain_root: Path,
) -> None:
    migration = binding.get("migration")
    snapshot = binding.get("pre_mutation_snapshot")
    if not isinstance(migration, Mapping) or not isinstance(snapshot, Mapping):
        _fail("binding_schema_invalid")
    bound_targets = migration.get("targets")
    if not isinstance(bound_targets, Sequence) or isinstance(
        bound_targets, (str, bytes, bytearray),
    ):
        _fail("binding_schema_invalid")
    before, actual_manifest_sha256 = _closure_snapshot_sources(
        binding,
        label="create",
    )
    if actual_manifest_sha256 != snapshot.get("manifest_sha256"):
        _fail("create_snapshot_manifest_sha256_mismatch")
    with corpus_lock(brain_root, exclusive=False):
        assert_corpus_readable(brain_root)
        final = _live_object_sources_all(brain_root)
    if set(before) != set(final) or any(
        before[object_id][0] != final[object_id][0]
        for object_id in before
    ):
        _fail("closure_semantic_object_set_mismatch")

    locators = {
        object_id: source[2]
        for object_id, source in before.items()
        if source[2].get("kind") == "CodeLocator"
    }
    expected_targets: list[dict[str, object]] = []
    after_by_id = {
        object_id: dict(source[2])
        for object_id, source in before.items()
    }
    for object_id in sorted(before):
        _, source_bytes, obj = before[object_id]
        kind = obj.get("kind")
        paired: str | None = None
        expected_title: str | None = None
        if kind == "CodeLocator":
            title = canonical_locator_title(obj)
            if obj.get("title") != title:
                expected_title = title
        elif kind == "EvidenceRef":
            paired = paired_code_locator_id(obj)
            locator = locators.get(paired) if paired is not None else None
            if locator is not None:
                title = canonical_locator_title(locator)
                if obj.get("title") != title:
                    expected_title = title
        if expected_title is None:
            continue
        expected_targets.append({
            "id": object_id,
            "kind": kind,
            "paired_locator_id": paired,
            "before_object_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "before_non_title_sha256": non_title_sha256(obj),
            "expected_title": expected_title,
        })
        after_by_id[object_id]["title"] = expected_title

    expected_target_ids = [row["id"] for row in expected_targets]
    before_store = _store_from_sources(before)
    after_store = BrainStore(after_by_id)
    if (
        not _canonical_value_equal(list(bound_targets), expected_targets)
        or migration.get("target_ids_sha256") != _json_sha(expected_target_ids)
        or migration.get("targets_sha256") != _json_sha(expected_targets)
        or migration.get("before_corpus_fingerprint")
        != corpus_fingerprint(before_store)
        or migration.get("expected_after_corpus_fingerprint")
        != corpus_fingerprint(after_store)
    ):
        _fail("closure_binding_plan_mismatch")

    target_ids = set(expected_target_ids)
    for object_id in sorted(before):
        before_path, before_bytes, before_obj = before[object_id]
        final_path, final_bytes, final_obj = final[object_id]
        if before_path != final_path:
            _fail("closure_final_path_mismatch", object_id)
        if object_id not in target_ids:
            if final_bytes != before_bytes:
                _fail("closure_final_non_target_changed", object_id)
            continue
        expected_after = after_by_id[object_id]
        if (
            final_obj.get("title") != expected_after.get("title")
            or non_title_sha256(final_obj) != non_title_sha256(before_obj)
            or final_bytes != BrainStore.object_bytes(expected_after)
        ):
            _fail("closure_final_target_mismatch", object_id)
    if corpus_fingerprint(_store_from_sources(final)) != corpus_fingerprint(after_store):
        _fail("closure_final_fingerprint_mismatch")

    before_inputs = [dict(before[str(row["id"])][2]) for row in expected_targets]
    after_outputs = [dict(after_by_id[str(row["id"])]) for row in expected_targets]
    source_hashes = {
        str(row["id"]): hashlib.sha256(before[str(row["id"])][1]).hexdigest()
        for row in expected_targets
    }
    expected_intent = {
        "intent_version": 1,
        "operation": "display_migration",
        "engine_sha": snapshot.get("engine_head"),
        "request": {
            "objects": before_inputs,
            "delete_ids": [],
            "renames": {},
            "preconditions": {
                str(obj["id"]): hashlib.sha256(
                    BrainStore.object_bytes(obj),
                ).hexdigest()
                for obj in before_inputs
            },
            "expected_corpus_fingerprint": corpus_fingerprint(before_store),
            "context_id": None,
            "external_reference_rewrites": {},
            "external_reference_rewrite_bindings": [],
            "auxiliary_updates": [],
            "canonical_repair_intents": [],
            "canonical_repair_reference_collapses": [],
            "canonical_repair_binding": None,
        },
        "preview": {
            "after_objects": after_outputs,
            "after_sha256_by_id": {
                str(obj["id"]): hashlib.sha256(
                    BrainStore.object_bytes(obj),
                ).hexdigest()
                for obj in after_outputs
            },
            "actions": [{
                "action": "update",
                "object_id": obj["id"],
                "object_kind": obj["kind"],
                "source_id": obj["id"],
                "timestamp_policy": "preserve",
            } for obj in before_inputs],
            "reference_rewrites": [],
            "external_reference_bindings": [],
            "before_fingerprint": corpus_fingerprint(before_store),
            "expected_after_fingerprint": corpus_fingerprint(after_store),
            "source_sha256_by_id": source_hashes,
        },
    }
    if not _canonical_value_equal(manifest.get("intent"), expected_intent):
        _fail("display_manifest_intent_mismatch")


def _verify_closure_semantics_independent(
    *,
    binding: Mapping[str, object],
    manifest: Mapping[str, object],
    brain_root: Path,
) -> None:
    migration = binding.get("migration")
    snapshot = binding.get("pre_mutation_snapshot")
    if not isinstance(migration, Mapping) or not isinstance(snapshot, Mapping):
        _fail("binding_schema_invalid")
    supplied_targets = migration.get("targets")
    if not isinstance(supplied_targets, Sequence) or isinstance(
        supplied_targets, (str, bytes, bytearray),
    ):
        _fail("binding_schema_invalid")
    snapshot_sources, independently_read_manifest_sha256 = (
        _closure_snapshot_sources(binding, label="verify")
    )
    if independently_read_manifest_sha256 != snapshot.get("manifest_sha256"):
        _fail("verify_snapshot_manifest_sha256_mismatch")
    with corpus_lock(brain_root, exclusive=False):
        assert_corpus_readable(brain_root)
        live_sources = _live_object_sources_all(brain_root)
    snapshot_ids = sorted(snapshot_sources)
    if snapshot_ids != sorted(live_sources) or any(
        snapshot_sources[object_id][0] != live_sources[object_id][0]
        for object_id in snapshot_ids
    ):
        _fail("closure_semantic_object_set_mismatch")

    locator_by_id = {
        object_id: item[2]
        for object_id, item in snapshot_sources.items()
        if item[2].get("kind") == "CodeLocator"
    }
    rebuilt_targets: list[dict[str, object]] = []
    rebuilt_after = {
        object_id: dict(item[2])
        for object_id, item in snapshot_sources.items()
    }
    for object_id in snapshot_ids:
        _, payload, obj = snapshot_sources[object_id]
        object_kind = obj.get("kind")
        locator_id = None
        canonical_title = None
        if object_kind == "CodeLocator":
            candidate = canonical_locator_title(obj)
            if obj.get("title") != candidate:
                canonical_title = candidate
        if object_kind == "EvidenceRef":
            locator_id = paired_code_locator_id(obj)
            locator = locator_by_id.get(locator_id) if locator_id else None
            if locator is not None:
                candidate = canonical_locator_title(locator)
                if obj.get("title") != candidate:
                    canonical_title = candidate
        if canonical_title is None:
            continue
        row = {
            "id": object_id,
            "kind": object_kind,
            "paired_locator_id": locator_id,
            "before_object_sha256": hashlib.sha256(payload).hexdigest(),
            "before_non_title_sha256": non_title_sha256(obj),
            "expected_title": canonical_title,
        }
        rebuilt_targets.append(row)
        rebuilt_after[object_id]["title"] = canonical_title

    rebuilt_ids = [row["id"] for row in rebuilt_targets]
    snapshot_store = _store_from_sources(snapshot_sources)
    planned_after_store = BrainStore(rebuilt_after)
    rebuilt_before_fingerprint = corpus_fingerprint(snapshot_store)
    rebuilt_after_fingerprint = corpus_fingerprint(planned_after_store)
    if (
        not _canonical_value_equal(list(supplied_targets), rebuilt_targets)
        or migration.get("target_ids_sha256") != _json_sha(rebuilt_ids)
        or migration.get("targets_sha256") != _json_sha(rebuilt_targets)
        or migration.get("before_corpus_fingerprint")
        != rebuilt_before_fingerprint
        or migration.get("expected_after_corpus_fingerprint")
        != rebuilt_after_fingerprint
    ):
        _fail("closure_binding_plan_mismatch")

    rebuilt_id_set = set(rebuilt_ids)
    for object_id in snapshot_ids:
        _, original_bytes, original = snapshot_sources[object_id]
        _, live_bytes, live = live_sources[object_id]
        if object_id not in rebuilt_id_set:
            if live_bytes != original_bytes:
                _fail("closure_final_non_target_changed", object_id)
            continue
        planned = rebuilt_after[object_id]
        if (
            live.get("title") != planned.get("title")
            or non_title_sha256(live) != non_title_sha256(original)
            or live_bytes != BrainStore.object_bytes(planned)
        ):
            _fail("closure_final_target_mismatch", object_id)
    if corpus_fingerprint(_store_from_sources(live_sources)) != rebuilt_after_fingerprint:
        _fail("closure_final_fingerprint_mismatch")

    request_objects = [
        dict(snapshot_sources[str(row["id"])][2])
        for row in rebuilt_targets
    ]
    preview_objects = [
        dict(rebuilt_after[str(row["id"])])
        for row in rebuilt_targets
    ]
    independent_source_hashes = {
        str(row["id"]): hashlib.sha256(
            snapshot_sources[str(row["id"])][1],
        ).hexdigest()
        for row in rebuilt_targets
    }
    independently_rebuilt_intent = {
        "intent_version": 1,
        "operation": "display_migration",
        "engine_sha": snapshot.get("engine_head"),
        "request": {
            "objects": request_objects,
            "delete_ids": [],
            "renames": {},
            "preconditions": {
                str(obj["id"]): hashlib.sha256(
                    BrainStore.object_bytes(obj),
                ).hexdigest()
                for obj in request_objects
            },
            "expected_corpus_fingerprint": rebuilt_before_fingerprint,
            "context_id": None,
            "external_reference_rewrites": {},
            "external_reference_rewrite_bindings": [],
            "auxiliary_updates": [],
            "canonical_repair_intents": [],
            "canonical_repair_reference_collapses": [],
            "canonical_repair_binding": None,
        },
        "preview": {
            "after_objects": preview_objects,
            "after_sha256_by_id": {
                str(obj["id"]): hashlib.sha256(
                    BrainStore.object_bytes(obj),
                ).hexdigest()
                for obj in preview_objects
            },
            "actions": [{
                "action": "update",
                "object_id": obj["id"],
                "object_kind": obj["kind"],
                "source_id": obj["id"],
                "timestamp_policy": "preserve",
            } for obj in request_objects],
            "reference_rewrites": [],
            "external_reference_bindings": [],
            "before_fingerprint": rebuilt_before_fingerprint,
            "expected_after_fingerprint": rebuilt_after_fingerprint,
            "source_sha256_by_id": independent_source_hashes,
        },
    }
    if not _canonical_value_equal(
        manifest.get("intent"), independently_rebuilt_intent,
    ):
        _fail("display_manifest_intent_mismatch")


def _compare_snapshot_before_to_live(
    binding: ParsedTask18Binding,
) -> tuple[tuple[str, ...], BrainStore, BrainStore]:
    before = _snapshot_object_sources_all(binding)
    live = _live_object_sources_all(binding.brain_root)
    before_ids = set(before)
    live_ids = set(live)
    if before_ids != live_ids:
        _fail(
            "object_set_changed",
            repr({"creates": sorted(live_ids - before_ids), "deletes": sorted(before_ids - live_ids)}),
        )
    renamed = sorted(
        object_id for object_id in before_ids if before[object_id][0] != live[object_id][0]
    )
    if renamed:
        _fail("object_paths_changed", repr(renamed))
    target_by_id = {str(row["id"]): row for row in binding.migration_targets}
    changed_ids = {
        object_id
        for object_id in before_ids
        if before[object_id][1] != live[object_id][1]
    }
    if changed_ids != set(target_by_id):
        _fail(
            "changed_target_set_mismatch",
            repr(sorted(changed_ids ^ set(target_by_id))),
        )
    changed_paths: list[str] = []
    expected_locator_titles = {
        object_id: str(row["expected_title"])
        for object_id, row in target_by_id.items()
        if row["kind"] == "CodeLocator"
    }
    for object_id in sorted(target_by_id):
        before_path, before_bytes, before_obj = before[object_id]
        live_path, _, live_obj = live[object_id]
        target = target_by_id[object_id]
        if hashlib.sha256(before_bytes).hexdigest() != target["before_object_sha256"]:
            _fail("snapshot_before_hash_mismatch", object_id)
        if before_obj.get("kind") != target["kind"] or live_obj.get("kind") != target["kind"]:
            _fail("target_kind_changed", object_id)
        if non_title_sha256(before_obj) != target["before_non_title_sha256"]:
            _fail("snapshot_non_title_hash_mismatch", object_id)
        if non_title_sha256(live_obj) != target["before_non_title_sha256"]:
            _fail("non-title change", object_id)
        if live_obj.get("title") != target["expected_title"]:
            _fail("title_mismatch", object_id)
        paired = target.get("paired_locator_id")
        if target["kind"] == "CodeLocator":
            if paired is not None or target["expected_title"] != canonical_locator_title(live_obj):
                _fail("target_pair_binding_mismatch", object_id)
        elif (
            paired_code_locator_id(before_obj) != paired
            or paired_code_locator_id(live_obj) != paired
            or expected_locator_titles.get(str(paired)) != target["expected_title"]
        ):
            _fail("target_pair_binding_mismatch", object_id)
        changed_paths.append(
            (binding.brain_root / live_path).relative_to(binding.repo_root).as_posix()
        )
    before_store = _store_from_sources(before)
    live_store = _store_from_sources(live)
    if _reference_graph(before_store) != _reference_graph(live_store):
        _fail("reference_graph_changed")
    return tuple(changed_paths), before_store, live_store


def _quote_inventory(path: Path, expected_sha256: str) -> tuple[Mapping[str, object], list[str]]:
    value = _canonical_document(path, expected_sha256, "quote_debt")
    ids = value.get("quote_debt_ids")
    if (
        not isinstance(ids, Sequence)
        or isinstance(ids, (str, bytes, bytearray))
        or not all(isinstance(item, str) and item for item in ids)
        or list(ids) != sorted(ids)
        or len(ids) != REQUIRED_QUOTE_DEBT_COUNT
        or value.get("quote_debt_ids_sha256") != _json_sha(list(ids))
    ):
        _fail("quote_debt_inventory_invalid")
    return value, list(ids)


def _noncanonical_symbol_ids(store: BrainStore) -> list[str]:
    from project_brain.symbol_verify import is_canonical_symbol_shape

    return sorted(
        str(obj["id"])
        for obj in store.by_kind("CodeLocator")
        if not is_canonical_symbol_shape(obj.get("symbol"))
    )


def _paired_title_mismatches(store: BrainStore) -> list[str]:
    locators = {obj["id"]: obj for obj in store.by_kind("CodeLocator")}
    mismatches: list[str] = []
    for obj in store.all():
        locator_id = paired_code_locator_id(obj)
        locator = locators.get(locator_id) if locator_id is not None else None
        if locator is not None and obj.get("title") != canonical_locator_title(locator):
            mismatches.append(str(obj.get("id")))
    return sorted(mismatches)


def _assert_post_invariants(
    binding: ParsedTask18Binding,
    *,
    before_store: BrainStore,
    live_store: BrainStore,
    quote_debt_path: Path,
    expected_quote_debt_sha256: str,
) -> _PostInvariantStats:
    _, quote_ids = _quote_inventory(quote_debt_path, expected_quote_debt_sha256)
    try:
        state = capture_task18_corpus_state(binding.brain_root)
    except Exception as exc:
        raise _dependency(exc) from exc
    raw_tree_sha256 = _raw_tree_sha256_from_state(state, label="post_invariants")
    if raw_tree_sha256 != _bound_raw_tree_sha256(binding.value):
        _fail("post_invariants_raw_tree_sha256_mismatch")
    live_quote_ids = sorted(
        str(obj["id"])
        for obj in live_store.by_kind("CodeLocator")
        if "verified_quote" not in obj
    )
    before_quote_presence = {
        str(obj["id"]): "verified_quote" in obj
        for obj in before_store.by_kind("CodeLocator")
    }
    live_quote_presence = {
        str(obj["id"]): "verified_quote" in obj
        for obj in live_store.by_kind("CodeLocator")
    }
    if live_quote_ids != quote_ids or before_quote_presence != live_quote_presence:
        _fail("quote_debt_changed")
    before_symbols = _noncanonical_symbol_ids(before_store)
    live_symbols = _noncanonical_symbol_ids(live_store)
    if live_symbols != before_symbols or len(live_symbols) != REQUIRED_NONCANONICAL_SYMBOL_COUNT:
        _fail("noncanonical_symbols_changed")
    if len(before_store.all()) != len(live_store.all()):
        _fail("object_count_changed")
    if corpus_fingerprint(live_store) != binding.expected_after_corpus_fingerprint:
        _fail("after_corpus_fingerprint_mismatch")
    if lint_store(live_store, binding.repo_root):
        _fail("lint_not_clean")
    pair_count = sum(
        paired_code_locator_id(obj) is not None
        for obj in live_store.by_kind("EvidenceRef")
    )
    if pair_count != REQUIRED_PAIR_COUNT or _paired_title_mismatches(live_store):
        _fail("paired_title_mismatch")
    bound_search = binding.value.get("search_index")
    bound_stale = binding.value.get("stale_set")
    if (
        not isinstance(bound_search, Mapping)
        or not isinstance(bound_stale, Mapping)
        or state.get("search_index") != bound_search
        or state.get("stale_set") != bound_stale
    ):
        _fail("index_or_stale_state_changed")
    edge_count, graph_sha = _reference_graph(live_store)
    search_index = state["search_index"]
    stale_set = state["stale_set"]
    assert isinstance(search_index, Mapping)
    assert isinstance(stale_set, Mapping)
    return _PostInvariantStats(
        object_count=len(live_store.all()),
        actual_after_fingerprint=corpus_fingerprint(live_store),
        raw_tree_sha256=raw_tree_sha256,
        reference_edge_count=edge_count,
        reference_graph_sha256=graph_sha,
        pair_count=pair_count,
        quote_count=len(quote_ids),
        quote_ids_sha256=_json_sha(quote_ids),
        symbol_count=len(live_symbols),
        symbol_ids_sha256=_json_sha(live_symbols),
        search_index=dict(search_index),
        stale_set_sha256=str(stale_set["sha256"]),
    )


def _atomic_create_pathspec(path: Path, paths: Sequence[str]) -> str:
    from project_brain.foundation import _create_at, _preflight_absent, _validate_output_path

    payload = b"".join(os.fsencode(value) + b"\0" for value in paths)
    parent_fd = -1
    try:
        parent_fd, name = _validate_output_path(path, label="pathspec")
        _preflight_absent(parent_fd, name, label="pathspec")
        _create_at(parent_fd, name, payload, label="pathspec")
    except FoundationError as exc:
        raise _dependency(exc) from exc
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)
    return hashlib.sha256(payload).hexdigest()


def _preflight_output(path: Path, label: str) -> None:
    from project_brain.foundation import _preflight_absent, _validate_output_path

    parent_fd = -1
    try:
        parent_fd, name = _validate_output_path(path, label=label)
        _preflight_absent(parent_fd, name, label=label)
    except FoundationError as exc:
        raise _dependency(exc) from exc
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


def _post_reverse_tail_hook() -> None:
    """Deterministic test seam immediately before the reverse tail."""


def verify_task18_applied(
    *,
    binding_path: Path,
    expected_binding_sha256: str,
    manifest_path: Path,
    expected_manifest_sha256: str,
    quote_debt_path: Path,
    expected_quote_debt_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    report_path: Path,
    pathspec_output: Path,
    generated_at: str,
) -> Task18PostVerification:
    report_path = _exact_absolute(report_path, "report_path")
    pathspec_output = _exact_absolute(pathspec_output, "pathspec_output")
    _preflight_output(report_path, "report")
    _preflight_output(pathspec_output, "pathspec")
    binding = parse_task18_binding_for_post_verify(
        binding_path=binding_path,
        expected_binding_sha256=expected_binding_sha256,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
    )
    manifest_path = _exact_absolute(Path(manifest_path), "manifest_path")
    quote_debt_path = _exact_absolute(Path(quote_debt_path), "quote_debt_path")
    with corpus_lock(binding.brain_root, exclusive=False):
        assert_corpus_readable(binding.brain_root)
        raw_tree_sha256 = _capture_matching_raw_tree_sha256(
            brain_root=binding.brain_root,
            binding=binding.value,
            label="post_initial",
        )
        _read_display_manifest(manifest_path, expected_manifest_sha256, binding)
        changed_paths, before_store, live_store = _compare_snapshot_before_to_live(binding)
        stats = _assert_post_invariants(
            binding,
            before_store=before_store,
            live_store=live_store,
            quote_debt_path=quote_debt_path,
            expected_quote_debt_sha256=expected_quote_debt_sha256,
        )
        if stats.raw_tree_sha256 != raw_tree_sha256:
            _fail("post_invariants_raw_tree_sha256_mismatch")
        try:
            brain_objects = (binding.brain_root / "objects").relative_to(binding.repo_root).as_posix()
            git_changed = set(decode_nul_paths(run_git_bytes(
                binding.repo_root, "diff", "--name-only", "-z", "HEAD", "--", brain_objects,
            )))
            if git_changed != set(changed_paths):
                _fail("git_target_path_mismatch", repr(sorted(git_changed ^ set(changed_paths))))
            allowed = list(changed_paths)
            if report_path.is_relative_to(binding.repo_root):
                allowed.append(report_path.relative_to(binding.repo_root).as_posix())
            dirt = verify_git_dirt_preserved(
                binding.repo_root,
                baseline_status_bytes=binding.baseline_status_bytes,
                baseline_content_manifest_bytes=binding.baseline_dirt_manifest_bytes,
                label="task18_post_apply",
                allowed_extra_paths=tuple(sorted(allowed)),
            )
        except Exception as exc:
            raise _dependency(exc) from exc
        _post_reverse_tail_hook()
        tail_binding = read_task18_json_bytes(
            binding.path,
            expected_sha256=binding.sha256,
            label="binding",
        )
        _parse_binding_bytes(tail_binding.data)
        _assert_bound_control_state(
            binding.value,
            engine_root=binding.engine_root,
            repo_root=binding.repo_root,
        )
        _read_display_manifest(manifest_path, expected_manifest_sha256, binding)
        _quote_inventory(quote_debt_path, expected_quote_debt_sha256)
        snapshot = verify_snapshot(
            binding.snapshot_root,
            expected_manifest_sha256=binding.snapshot_manifest_sha256,
        )
        snapshot_bound = binding.value["pre_mutation_snapshot"]
        assert isinstance(snapshot_bound, Mapping)
        if _expected_snapshot_verify(snapshot) != {
            "ok": True,
            "snapshot_id": snapshot_bound["snapshot_id"],
            "manifest_sha256": snapshot_bound["manifest_sha256"],
            "file_count": snapshot_bound["file_count"],
            "repo_head": snapshot_bound["repo_head"],
            "engine_head": snapshot_bound["engine_head"],
            "corpus_fingerprint": snapshot_bound["corpus_fingerprint"],
        }:
            _fail("snapshot_drift")
        tail_paths, _, tail_store = _compare_snapshot_before_to_live(binding)
        if tail_paths != changed_paths or corpus_fingerprint(tail_store) != binding.expected_after_corpus_fingerprint:
            _fail("corpus_changed_during_post_verify")
        try:
            tail_state = capture_task18_corpus_state(binding.brain_root)
        except Exception as exc:
            raise _dependency(exc) from exc
        if (
            _raw_tree_sha256_from_state(tail_state, label="post_tail")
            != raw_tree_sha256
        ):
            _fail("post_tail_raw_tree_sha256_mismatch")
        if (
            tail_state.get("search_index") != stats.search_index
            or not isinstance(tail_state.get("stale_set"), Mapping)
            or tail_state["stale_set"].get("sha256") != stats.stale_set_sha256
        ):
            _fail("index_or_stale_state_changed_during_post_verify")
        try:
            tail_dirt = verify_git_dirt_preserved(
                binding.repo_root,
                baseline_status_bytes=binding.baseline_status_bytes,
                baseline_content_manifest_bytes=binding.baseline_dirt_manifest_bytes,
                label="task18_post_apply_tail",
                allowed_extra_paths=tuple(sorted(allowed)),
            )
        except Exception as exc:
            raise _dependency(exc) from exc
        if (
            tail_dirt.status_bytes != dirt.status_bytes
            or tail_dirt.content_manifest_bytes != dirt.content_manifest_bytes
        ):
            _fail("git_dirt_changed_during_post_verify")
        report = {
            "version": 1,
            "purpose": "task18-post-apply-verification",
            "generated_at": generated_at,
            "binding": {"path": str(binding.path), "sha256": binding.sha256},
            "display_manifest": {"path": str(manifest_path), "sha256": expected_manifest_sha256},
            "quote_debt": {"path": str(quote_debt_path), "sha256": expected_quote_debt_sha256},
            "target_ids_sha256": binding.target_ids_sha256,
            "expected_after_corpus_fingerprint": binding.expected_after_corpus_fingerprint,
            "actual_after_corpus_fingerprint": stats.actual_after_fingerprint,
            "raw_tree_sha256": stats.raw_tree_sha256,
            "object_count": stats.object_count,
            "changed_paths": list(changed_paths),
            "update_count": len(changed_paths),
            "create_count": 0,
            "delete_count": 0,
            "rename_count": 0,
            "reference_graph": {
                "edge_count": stats.reference_edge_count,
                "sha256": stats.reference_graph_sha256,
                "unchanged": True,
            },
            "lint_problem_count": 0,
            "pairs": {"total": stats.pair_count, "mismatch_count": 0},
            "quote_debt_state": {
                "count": stats.quote_count,
                "ids_sha256": stats.quote_ids_sha256,
            },
            "noncanonical_symbol_state": {
                "count": stats.symbol_count,
                "ids_sha256": stats.symbol_ids_sha256,
            },
            "search_index": dict(stats.search_index),
            "stale_set_sha256": stats.stale_set_sha256,
            "git": {
                "baseline_status_sha256": hashlib.sha256(binding.baseline_status_bytes).hexdigest(),
                "baseline_dirt_content_sha256": hashlib.sha256(binding.baseline_dirt_manifest_bytes).hexdigest(),
                "current_status_sha256": dirt.status_sha256,
                "current_dirt_content_sha256": dirt.content_manifest_sha256,
            },
            "quote_debt_unchanged": True,
            "noncanonical_symbols_unchanged": True,
            "index_db_unchanged": True,
            "user_dirt_preserved": True,
        }
        try:
            _atomic_create_pathspec(pathspec_output, changed_paths)
            report_sha = atomic_create_receipt(report_path, report)
        except Exception as exc:
            raise _dependency(exc) from exc
        return Task18PostVerification(
            update_count=len(changed_paths),
            quote_debt_unchanged=True,
            noncanonical_symbols_unchanged=True,
            index_db_unchanged=True,
            user_dirt_preserved=True,
            report_path=report_path,
            report_sha256=report_sha,
        )


def _artifact_document(
    path: Path,
    expected_sha256: str,
    label: str,
) -> tuple[Task18JsonDocument, dict[str, object]]:
    path = _exact_absolute(path, label)
    document = read_task18_json_bytes(
        path,
        expected_sha256=expected_sha256,
        label=label,
    )
    try:
        if canonical_receipt_bytes(document.value) != document.data:
            _fail(f"{label}_json_invalid", "document must be canonical JSON")
    except FoundationError as exc:
        raise _dependency(exc) from exc
    return document, {
        "path": str(path),
        "sha256": document.sha256,
        "size": len(document.data),
        "mode": document.mode,
    }


def _artifact_receipt(path: Path, expected_sha256: str, label: str) -> dict[str, object]:
    return _artifact_document(path, expected_sha256, label)[1]


def _committed_doc(root: Path, path: Path, head: str, label: str) -> dict[str, object]:
    path = _exact_absolute(path, label)
    if not path.is_relative_to(root):
        _fail("committed_docs_invalid", label)
    try:
        committed = capture_committed_input(root, path.relative_to(root), head)
        file_receipt = capture_bound_file(path)
    except Exception as exc:
        _fail("committed_docs_drift", f"{label}: {exc}")
    if committed.get("file_sha256") != file_receipt.get("sha256"):
        _fail("committed_docs_drift", label)
    return {**file_receipt, "commit_sha": head}


def _current_git_closure(engine_root: Path, repo_root: Path) -> tuple[object, object]:
    try:
        engine = capture_git_dirt_receipt(engine_root, label="engine")
        repo = capture_git_dirt_receipt(repo_root, label="bb2")
        if capture_cached_paths(engine_root) or capture_cached_paths(repo_root):
            _fail("cached_paths_not_empty")
    except Exception as exc:
        raise _dependency(exc) from exc
    return engine, repo


def _closure_binding(
    *,
    path: Path,
    expected_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
) -> tuple[Mapping[str, object], dict[str, object]]:
    document, receipt = _artifact_document(path, expected_sha256, "binding")
    value = _parse_binding_bytes(document.data)
    roots = value["roots"]
    if roots != {
        "engine": str(engine_root),
        "bb2": str(repo_root),
        "brain": str(brain_root),
    }:
        _fail("binding_roots_mismatch")
    return value, receipt


def _expected_snapshot_verify(snapshot: object) -> dict[str, object]:
    return {
        "ok": True,
        "snapshot_id": snapshot.snapshot_id,
        "manifest_sha256": snapshot.manifest_sha256,
        "file_count": snapshot.file_count,
        "repo_head": snapshot.repo_head,
        "engine_head": snapshot.engine_head,
        "corpus_fingerprint": snapshot.corpus_fingerprint,
    }


def _assert_closure_post_report(
    value: Mapping[str, object],
    *,
    binding_path: Path,
    binding_sha256: str,
    manifest_path: Path,
    manifest_sha256: str,
    binding: Mapping[str, object],
) -> None:
    migration = binding["migration"]
    search_index = binding["search_index"]
    stale_set = binding["stale_set"]
    corpus = binding["corpus"]
    inputs = binding["inputs"]
    bb2 = binding["bb2"]
    assert isinstance(migration, Mapping)
    assert isinstance(search_index, Mapping)
    assert isinstance(stale_set, Mapping)
    assert isinstance(corpus, Mapping)
    assert isinstance(inputs, Mapping)
    assert isinstance(bb2, Mapping)
    pairs = value.get("pairs")
    quote = value.get("quote_debt_state")
    symbols = value.get("noncanonical_symbol_state")
    graph = value.get("reference_graph")
    git = value.get("git")
    quote_input = inputs["quote_debt"]
    assert isinstance(quote_input, Mapping)
    _, bound_quote_ids = _quote_inventory(
        Path(str(quote_input["path"])),
        str(quote_input["sha256"]),
    )
    if (
        set(value) != _POST_REPORT_KEYS
        or not _exact_int(value.get("version"), expected=1)
        or value.get("purpose") != "task18-post-apply-verification"
        or not isinstance(value.get("generated_at"), str)
        or not value.get("generated_at")
        or value.get("binding") != {"path": str(binding_path), "sha256": binding_sha256}
        or value.get("display_manifest")
        != {"path": str(manifest_path), "sha256": manifest_sha256}
        or value.get("target_ids_sha256") != migration["target_ids_sha256"]
        or value.get("expected_after_corpus_fingerprint")
        != migration["expected_after_corpus_fingerprint"]
        or value.get("actual_after_corpus_fingerprint")
        != migration["expected_after_corpus_fingerprint"]
        or not isinstance(value.get("raw_tree_sha256"), str)
        or _SHA256.fullmatch(str(value["raw_tree_sha256"])) is None
        or value.get("raw_tree_sha256") != corpus["raw_tree_sha256"]
        or value.get("quote_debt")
        != {"path": quote_input["path"], "sha256": quote_input["sha256"]}
        or not _exact_int(value.get("object_count"), minimum=REQUIRED_TARGET_COUNT)
        or not _exact_int(value.get("update_count"), expected=REQUIRED_TARGET_COUNT)
        or not _exact_int(value.get("create_count"), expected=0)
        or not _exact_int(value.get("delete_count"), expected=0)
        or not _exact_int(value.get("rename_count"), expected=0)
        or not isinstance(value.get("changed_paths"), list)
        or len(value["changed_paths"]) != REQUIRED_TARGET_COUNT
        or len(set(value["changed_paths"])) != REQUIRED_TARGET_COUNT
        or not all(
            isinstance(path, str) and path.startswith("brain/objects/")
            for path in value["changed_paths"]
        )
        or not _exact_int(value.get("lint_problem_count"), expected=0)
        or not isinstance(pairs, Mapping)
        or set(pairs) != {"total", "mismatch_count"}
        or not _exact_int(pairs.get("total"), expected=REQUIRED_PAIR_COUNT)
        or not _exact_int(pairs.get("mismatch_count"), expected=0)
        or not isinstance(quote, Mapping)
        or set(quote) != {"count", "ids_sha256"}
        or not _exact_int(quote.get("count"), expected=REQUIRED_QUOTE_DEBT_COUNT)
        or quote.get("ids_sha256") != _json_sha(bound_quote_ids)
        or not isinstance(quote.get("ids_sha256"), str)
        or _SHA256.fullmatch(str(quote["ids_sha256"])) is None
        or not isinstance(symbols, Mapping)
        or set(symbols) != {"count", "ids_sha256"}
        or not _exact_int(
            symbols.get("count"), expected=REQUIRED_NONCANONICAL_SYMBOL_COUNT,
        )
        or not isinstance(symbols.get("ids_sha256"), str)
        or _SHA256.fullmatch(str(symbols["ids_sha256"])) is None
        or not isinstance(graph, Mapping)
        or set(graph) != {"edge_count", "sha256", "unchanged"}
        or graph.get("unchanged") is not True
        or type(graph.get("edge_count")) is not int
        or int(graph["edge_count"]) < 0
        or not isinstance(graph.get("sha256"), str)
        or _SHA256.fullmatch(str(graph["sha256"])) is None
        or value.get("search_index") != search_index
        or value.get("stale_set_sha256") != stale_set["sha256"]
        or not isinstance(git, Mapping)
        or set(git) != {
            "baseline_status_sha256", "baseline_dirt_content_sha256",
            "current_status_sha256", "current_dirt_content_sha256",
        }
        or git.get("baseline_status_sha256") != bb2["status_sha256"]
        or git.get("baseline_dirt_content_sha256") != bb2["dirt_content_sha256"]
        or not all(
            isinstance(git.get(key), str)
            and _SHA256.fullmatch(str(git[key])) is not None
            for key in git
        )
        or any(
            value.get(label) is not True
            for label in (
                "quote_debt_unchanged",
                "noncanonical_symbols_unchanged",
                "index_db_unchanged",
                "user_dirt_preserved",
            )
        )
    ):
        _fail("post_report_binding_mismatch")


def _assert_post_matches_final_corpus(
    post: Mapping[str, object],
    evidence: _FinalCorpusEvidence,
) -> None:
    graph = post.get("reference_graph")
    quote = post.get("quote_debt_state")
    symbols = post.get("noncanonical_symbol_state")
    if (
        post.get("object_count") != evidence.object_count
        or post.get("actual_after_corpus_fingerprint") != evidence.corpus_fingerprint
        or post.get("raw_tree_sha256") != evidence.raw_tree_sha256
        or post.get("changed_paths") != list(evidence.changed_paths)
        or not isinstance(quote, Mapping)
        or quote.get("count") != evidence.quote_count
        or quote.get("ids_sha256") != evidence.quote_ids_sha256
        or not isinstance(symbols, Mapping)
        or symbols.get("count") != evidence.symbol_count
        or symbols.get("ids_sha256") != evidence.symbol_ids_sha256
        or not isinstance(graph, Mapping)
        or graph.get("edge_count") != evidence.reference_edge_count
        or graph.get("sha256") != evidence.reference_graph_sha256
    ):
        _fail("post_report_final_corpus_mismatch")


def _closure_artifacts(
    *,
    binding_path: Path,
    expected_binding_sha256: str,
    manifest_path: Path,
    expected_manifest_sha256: str,
    post_report_path: Path,
    expected_post_report_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
) -> tuple[
    Mapping[str, object],
    dict[str, dict[str, object]],
    Mapping[str, object],
]:
    binding, binding_receipt = _closure_binding(
        path=binding_path,
        expected_sha256=expected_binding_sha256,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
    )
    manifest_doc, manifest_receipt = _artifact_document(
        manifest_path, expected_manifest_sha256, "display_manifest",
    )
    snapshot = binding["pre_mutation_snapshot"]
    assert isinstance(snapshot, Mapping)
    if (
        set(manifest_doc.value) != _DISPLAY_MANIFEST_KEYS
        or not _exact_int(manifest_doc.value.get("migration_version"), expected=3)
        or manifest_doc.value.get("migration_kind") != "display_only"
        or manifest_doc.value.get("task18_binding_path") != str(binding_path)
        or manifest_doc.value.get("task18_binding_sha256") != expected_binding_sha256
        or manifest_doc.value.get("snapshot_id") != snapshot["snapshot_id"]
        or manifest_doc.value.get("snapshot_manifest_sha256")
        != snapshot["manifest_sha256"]
    ):
        _fail("display_manifest_binding_mismatch")
    _validate_create_closure_semantics(
        binding=binding,
        manifest=manifest_doc.value,
        brain_root=brain_root,
    )
    post_doc, post_receipt = _artifact_document(
        post_report_path, expected_post_report_sha256, "post_report",
    )
    _assert_closure_post_report(
        post_doc.value,
        binding_path=binding_path,
        binding_sha256=expected_binding_sha256,
        manifest_path=manifest_path,
        manifest_sha256=expected_manifest_sha256,
        binding=binding,
    )
    return (
        binding,
        {
            "binding": binding_receipt,
            "display_manifest": manifest_receipt,
            "post_report": post_receipt,
        },
        post_doc.value,
    )


def _verify_closure_artifacts_independent(
    *,
    binding_receipt: Mapping[str, object],
    manifest_receipt: Mapping[str, object],
    post_receipt: Mapping[str, object],
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
) -> tuple[Mapping[str, object], dict[str, dict[str, object]], Mapping[str, object]]:
    binding_path = Path(str(binding_receipt["path"]))
    binding_doc, current_binding_receipt = _artifact_document(
        binding_path, str(binding_receipt["sha256"]), "binding",
    )
    binding = _parse_binding_bytes(binding_doc.data)
    if binding.get("roots") != {
        "engine": str(engine_root),
        "bb2": str(repo_root),
        "brain": str(brain_root),
    }:
        _fail("binding_roots_mismatch")

    manifest_path = Path(str(manifest_receipt["path"]))
    manifest_doc, current_manifest_receipt = _artifact_document(
        manifest_path, str(manifest_receipt["sha256"]), "display_manifest",
    )
    snapshot = binding.get("pre_mutation_snapshot")
    if not isinstance(snapshot, Mapping) or (
        set(manifest_doc.value) != _DISPLAY_MANIFEST_KEYS
        or not _exact_int(manifest_doc.value.get("migration_version"), expected=3)
        or manifest_doc.value.get("migration_kind") != "display_only"
        or not isinstance(manifest_doc.value.get("intent"), Mapping)
        or manifest_doc.value.get("task18_binding_path") != str(binding_path)
        or manifest_doc.value.get("task18_binding_sha256") != binding_receipt["sha256"]
        or manifest_doc.value.get("snapshot_id") != snapshot.get("snapshot_id")
        or manifest_doc.value.get("snapshot_manifest_sha256")
        != snapshot.get("manifest_sha256")
    ):
        _fail("display_manifest_binding_mismatch")
    _verify_closure_semantics_independent(
        binding=binding,
        manifest=manifest_doc.value,
        brain_root=brain_root,
    )

    post_path = Path(str(post_receipt["path"]))
    post_doc, current_post_receipt = _artifact_document(
        post_path, str(post_receipt["sha256"]), "post_report",
    )
    post = post_doc.value
    migration = binding.get("migration")
    inputs = binding.get("inputs")
    search_index = binding.get("search_index")
    stale_set = binding.get("stale_set")
    corpus = binding.get("corpus")
    bb2 = binding.get("bb2")
    if not all(
        isinstance(item, Mapping)
        for item in (migration, inputs, search_index, stale_set, corpus, bb2)
    ):
        _fail("binding_schema_invalid")
    assert isinstance(migration, Mapping)
    assert isinstance(inputs, Mapping)
    assert isinstance(search_index, Mapping)
    assert isinstance(stale_set, Mapping)
    assert isinstance(corpus, Mapping)
    assert isinstance(bb2, Mapping)
    quote_input = inputs.get("quote_debt")
    if not isinstance(quote_input, Mapping):
        _fail("binding_schema_invalid")
    _, quote_ids = _quote_inventory(
        Path(str(quote_input["path"])), str(quote_input["sha256"]),
    )
    pairs = post.get("pairs")
    quote = post.get("quote_debt_state")
    symbols = post.get("noncanonical_symbol_state")
    graph = post.get("reference_graph")
    git = post.get("git")
    changed = post.get("changed_paths")
    if (
        set(post) != _POST_REPORT_KEYS
        or not _exact_int(post.get("version"), expected=1)
        or post.get("purpose") != "task18-post-apply-verification"
        or not isinstance(post.get("generated_at"), str)
        or not post.get("generated_at")
        or post.get("binding")
        != {"path": str(binding_path), "sha256": binding_receipt["sha256"]}
        or post.get("display_manifest")
        != {"path": str(manifest_path), "sha256": manifest_receipt["sha256"]}
        or post.get("quote_debt")
        != {"path": quote_input["path"], "sha256": quote_input["sha256"]}
        or post.get("target_ids_sha256") != migration.get("target_ids_sha256")
        or post.get("expected_after_corpus_fingerprint")
        != migration.get("expected_after_corpus_fingerprint")
        or post.get("actual_after_corpus_fingerprint")
        != migration.get("expected_after_corpus_fingerprint")
        or not isinstance(post.get("raw_tree_sha256"), str)
        or _SHA256.fullmatch(str(post["raw_tree_sha256"])) is None
        or post.get("raw_tree_sha256") != corpus.get("raw_tree_sha256")
        or not _exact_int(post.get("object_count"), minimum=REQUIRED_TARGET_COUNT)
        or not _exact_int(post.get("update_count"), expected=REQUIRED_TARGET_COUNT)
        or not _exact_int(post.get("create_count"), expected=0)
        or not _exact_int(post.get("delete_count"), expected=0)
        or not _exact_int(post.get("rename_count"), expected=0)
        or not _exact_int(post.get("lint_problem_count"), expected=0)
        or not isinstance(changed, list)
        or len(changed) != REQUIRED_TARGET_COUNT
        or len(set(changed)) != REQUIRED_TARGET_COUNT
        or not all(isinstance(path, str) for path in changed)
        or not isinstance(pairs, Mapping)
        or set(pairs) != {"total", "mismatch_count"}
        or not _exact_int(pairs.get("total"), expected=REQUIRED_PAIR_COUNT)
        or not _exact_int(pairs.get("mismatch_count"), expected=0)
        or not isinstance(quote, Mapping)
        or set(quote) != {"count", "ids_sha256"}
        or not _exact_int(quote.get("count"), expected=REQUIRED_QUOTE_DEBT_COUNT)
        or quote.get("ids_sha256") != _json_sha(quote_ids)
        or not isinstance(symbols, Mapping)
        or set(symbols) != {"count", "ids_sha256"}
        or not _exact_int(
            symbols.get("count"), expected=REQUIRED_NONCANONICAL_SYMBOL_COUNT,
        )
        or not isinstance(symbols.get("ids_sha256"), str)
        or _SHA256.fullmatch(str(symbols["ids_sha256"])) is None
        or not isinstance(graph, Mapping)
        or set(graph) != {"edge_count", "sha256", "unchanged"}
        or not _exact_int(graph.get("edge_count"), minimum=0)
        or not isinstance(graph.get("sha256"), str)
        or _SHA256.fullmatch(str(graph["sha256"])) is None
        or graph.get("unchanged") is not True
        or post.get("search_index") != search_index
        or post.get("stale_set_sha256") != stale_set.get("sha256")
        or not isinstance(git, Mapping)
        or set(git) != {
            "baseline_status_sha256", "baseline_dirt_content_sha256",
            "current_status_sha256", "current_dirt_content_sha256",
        }
        or git.get("baseline_status_sha256") != bb2.get("status_sha256")
        or git.get("baseline_dirt_content_sha256") != bb2.get("dirt_content_sha256")
        or not all(
            isinstance(git.get(key), str)
            and _SHA256.fullmatch(str(git[key])) is not None
            for key in git
        )
        or any(
            post.get(label) is not True
            for label in (
                "quote_debt_unchanged", "noncanonical_symbols_unchanged",
                "index_db_unchanged", "user_dirt_preserved",
            )
        )
    ):
        _fail("post_report_binding_mismatch")
    return (
        binding,
        {
            "binding": current_binding_receipt,
            "display_manifest": current_manifest_receipt,
            "post_report": current_post_receipt,
        },
        post,
    )


def _verify_post_final_evidence_independent(
    post: Mapping[str, object],
    evidence: _FinalCorpusEvidence,
) -> None:
    quote = post.get("quote_debt_state")
    symbols = post.get("noncanonical_symbol_state")
    graph = post.get("reference_graph")
    if not isinstance(quote, Mapping) or not isinstance(symbols, Mapping) or not isinstance(graph, Mapping):
        _fail("post_report_final_corpus_mismatch")
    if (
        post.get("object_count") != evidence.object_count
        or post.get("actual_after_corpus_fingerprint") != evidence.corpus_fingerprint
        or post.get("raw_tree_sha256") != evidence.raw_tree_sha256
        or post.get("changed_paths") != list(evidence.changed_paths)
        or quote.get("count") != evidence.quote_count
        or quote.get("ids_sha256") != evidence.quote_ids_sha256
        or symbols.get("count") != evidence.symbol_count
        or symbols.get("ids_sha256") != evidence.symbol_ids_sha256
        or graph.get("edge_count") != evidence.reference_edge_count
        or graph.get("sha256") != evidence.reference_graph_sha256
    ):
        _fail("post_report_final_corpus_mismatch")


def _assert_baseline_git(
    binding: Mapping[str, object],
    engine_git: object,
    repo_git: object,
) -> None:
    engine = binding["engine"]
    bb2 = binding["bb2"]
    assert isinstance(engine, Mapping)
    assert isinstance(bb2, Mapping)
    if (
        engine_git.status_bytes != _decode_bound_bytes(engine, "status_bytes_base64")
        or engine_git.content_manifest_bytes != _decode_bound_bytes(engine, "dirt_manifest_base64")
        or repo_git.status_bytes != _decode_bound_bytes(bb2, "status_bytes_base64")
        or repo_git.content_manifest_bytes != _decode_bound_bytes(bb2, "dirt_manifest_base64")
    ):
        _fail("closure_user_dirt_drift")


def _closure_reverse_tail_hook() -> None:
    """Deterministic test seam immediately before closure output creation."""


def create_task18_closure_receipt(
    *,
    report_path: Path,
    corpus_final_snapshot_root: Path,
    expected_snapshot_manifest_sha256: str,
    snapshot_verify_receipt_path: Path,
    expected_snapshot_verify_receipt_sha256: str,
    binding_path: Path,
    expected_binding_sha256: str,
    manifest_path: Path,
    expected_manifest_sha256: str,
    post_report_path: Path,
    expected_post_report_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    completion_report_path: Path,
    roadmap_path: Path,
    expected_engine_head: str,
    expected_repo_head: str,
    generated_at: str,
) -> Task18ClosureResult:
    report_path = _exact_absolute(report_path, "report_path")
    engine_root = _exact_absolute(engine_root, "engine_root")
    repo_root = _exact_absolute(repo_root, "repo_root")
    brain_root = _exact_absolute(brain_root, "brain_root")
    if not _valid_timestamp(generated_at):
        _fail("closure_created_at_invalid")
    _preflight_output(report_path, "report")
    if _GIT_SHA.fullmatch(expected_engine_head) is None or _GIT_SHA.fullmatch(expected_repo_head) is None:
        _fail("expected_head_invalid")
    try:
        snapshot = verify_snapshot(
            _exact_absolute(corpus_final_snapshot_root, "corpus_final_snapshot_root"),
            expected_manifest_sha256=expected_snapshot_manifest_sha256,
        )
    except Exception as exc:
        raise _dependency(exc) from exc
    engine_git, repo_git = _current_git_closure(engine_root, repo_root)
    binding, artifacts, post_value = _closure_artifacts(
        binding_path=_exact_absolute(binding_path, "binding"),
        expected_binding_sha256=expected_binding_sha256,
        manifest_path=_exact_absolute(manifest_path, "display_manifest"),
        expected_manifest_sha256=expected_manifest_sha256,
        post_report_path=_exact_absolute(post_report_path, "post_report"),
        expected_post_report_sha256=expected_post_report_sha256,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
    )
    final_evidence = _final_corpus_evidence(
        brain_root=brain_root,
        repo_root=repo_root,
        binding=binding,
    )
    _assert_post_matches_final_corpus(post_value, final_evidence)
    _assert_baseline_git(binding, engine_git, repo_git)
    binding_engine = binding["engine"]
    binding_bb2 = binding["bb2"]
    migration = binding["migration"]
    assert isinstance(binding_engine, Mapping)
    assert isinstance(binding_bb2, Mapping)
    assert isinstance(migration, Mapping)
    try:
        require_commit_is_ancestor(
            engine_root, str(binding_engine["head"]), expected_engine_head,
        )
        require_commit_is_ancestor(
            repo_root, str(binding_bb2["head"]), expected_repo_head,
        )
    except Exception as exc:
        raise _dependency(exc) from exc
    if (
        engine_git.head != expected_engine_head
        or repo_git.head != expected_repo_head
        or snapshot.repo_head != expected_repo_head
        or snapshot.engine_head != binding_engine["head"]
        or snapshot.corpus_fingerprint != migration["expected_after_corpus_fingerprint"]
    ):
        _fail("closure_heads_or_corpus_mismatch")
    verify_doc, verify_receipt = _artifact_document(
        snapshot_verify_receipt_path,
        expected_snapshot_verify_receipt_sha256,
        "snapshot_verify_receipt",
    )
    if (
        not _valid_snapshot_verify_receipt(verify_doc.value)
        or verify_doc.value != _expected_snapshot_verify(snapshot)
    ):
        _fail("snapshot_verify_receipt_mismatch")
    completion = _committed_doc(engine_root, completion_report_path, expected_engine_head, "completion_report")
    roadmap = _committed_doc(engine_root, roadmap_path, expected_engine_head, "roadmap")
    value = {
        "version": 1,
        "purpose": "task18-final-closure",
        "created_at": generated_at,
        "roots": {"engine": str(engine_root), "bb2": str(repo_root), "brain": str(brain_root)},
        "corpus_final_snapshot": {
            "path": str(corpus_final_snapshot_root),
            "manifest_sha256": snapshot.manifest_sha256,
            "snapshot_id": snapshot.snapshot_id,
            "file_count": snapshot.file_count,
            "verify_receipt": verify_receipt,
        },
        "artifacts": artifacts,
        "heads": {
            "implementation": snapshot.engine_head,
            "corpus": snapshot.repo_head,
            "docs": expected_engine_head,
        },
        "git": {
            "engine_cached_empty": True,
            "bb2_cached_empty": True,
            "engine_status_sha256": engine_git.status_sha256,
            "engine_dirt_content_sha256": engine_git.content_manifest_sha256,
            "bb2_status_sha256": repo_git.status_sha256,
            "bb2_dirt_content_sha256": repo_git.content_manifest_sha256,
        },
        "committed_docs": {"completion_report": completion, "roadmap": roadmap},
    }
    _closure_reverse_tail_hook()
    try:
        tail_snapshot = verify_snapshot(
            Path(corpus_final_snapshot_root),
            expected_manifest_sha256=expected_snapshot_manifest_sha256,
        )
    except Exception as exc:
        raise _dependency(exc) from exc
    tail_engine_git, tail_repo_git = _current_git_closure(engine_root, repo_root)
    tail_verify_doc, tail_verify_receipt = _artifact_document(
        Path(snapshot_verify_receipt_path),
        expected_snapshot_verify_receipt_sha256,
        "snapshot_verify_receipt",
    )
    tail_binding, tail_artifacts, tail_post_value = _closure_artifacts(
        binding_path=Path(binding_path),
        expected_binding_sha256=expected_binding_sha256,
        manifest_path=Path(manifest_path),
        expected_manifest_sha256=expected_manifest_sha256,
        post_report_path=Path(post_report_path),
        expected_post_report_sha256=expected_post_report_sha256,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
    )
    tail_evidence = _final_corpus_evidence(
        brain_root=brain_root,
        repo_root=repo_root,
        binding=tail_binding,
    )
    _assert_post_matches_final_corpus(tail_post_value, tail_evidence)
    _assert_baseline_git(tail_binding, tail_engine_git, tail_repo_git)
    if (
        tail_snapshot != snapshot
        or tail_engine_git != engine_git
        or tail_repo_git != repo_git
        or tail_verify_receipt != verify_receipt
        or tail_verify_doc.value != _expected_snapshot_verify(tail_snapshot)
        or tail_artifacts != artifacts
        or tail_evidence != final_evidence
        or _committed_doc(
            engine_root, completion_report_path, expected_engine_head, "completion_report",
        ) != completion
        or _committed_doc(
            engine_root, roadmap_path, expected_engine_head, "roadmap",
        ) != roadmap
    ):
        _fail("closure_state_changed_during_create")
    try:
        closure_sha = atomic_create_receipt(report_path, value)
    except FoundationError as exc:
        raise _dependency(exc) from exc
    return Task18ClosureResult(
        closure_path=report_path,
        closure_sha256=closure_sha,
        report_path=report_path,
        report_sha256=closure_sha,
    )


def verify_task18_closure_receipt(
    *,
    closure_path: Path,
    expected_closure_sha256: str,
    engine_root: Path,
    repo_root: Path,
    brain_root: Path,
    report_path: Path,
) -> Task18ClosureResult:
    """생성 payload builder를 쓰지 않고 closure와 현재 상태를 다시 계산한다."""
    closure_path = _exact_absolute(closure_path, "closure_path")
    report_path = _exact_absolute(report_path, "report_path")
    _preflight_output(report_path, "report")
    value = _canonical_document(closure_path, expected_closure_sha256, "closure")
    if (
        set(value) != _CLOSURE_KEYS
        or not _exact_int(value.get("version"), expected=1)
        or value.get("purpose") != "task18-final-closure"
        or not _valid_timestamp(value.get("created_at"))
    ):
        _fail("closure_schema_invalid")
    roots = value.get("roots")
    snapshot_section = value.get("corpus_final_snapshot")
    artifacts = value.get("artifacts")
    heads = value.get("heads")
    git = value.get("git")
    docs = value.get("committed_docs")
    if not all(isinstance(section, Mapping) for section in (roots, snapshot_section, artifacts, heads, git, docs)):
        _fail("closure_schema_invalid")
    assert isinstance(roots, Mapping)
    assert isinstance(snapshot_section, Mapping)
    assert isinstance(artifacts, Mapping)
    assert isinstance(heads, Mapping)
    assert isinstance(git, Mapping)
    assert isinstance(docs, Mapping)
    if (
        set(roots) != _CLOSURE_ROOT_KEYS
        or set(snapshot_section) != _CLOSURE_SNAPSHOT_KEYS
        or set(artifacts) != _CLOSURE_ARTIFACT_KEYS
        or set(heads) != _CLOSURE_HEAD_KEYS
        or set(git) != _CLOSURE_GIT_KEYS
        or set(docs) != _CLOSURE_DOC_KEYS
        or not all(_valid_file_receipt(artifacts[label]) for label in _CLOSURE_ARTIFACT_KEYS)
        or not all(_valid_file_receipt(docs[label], committed=True) for label in _CLOSURE_DOC_KEYS)
        or not _valid_file_receipt(snapshot_section.get("verify_receipt"))
        or not all(
            isinstance(heads.get(label), str)
            and _GIT_SHA.fullmatch(str(heads[label])) is not None
            for label in _CLOSURE_HEAD_KEYS
        )
        or git.get("engine_cached_empty") is not True
        or git.get("bb2_cached_empty") is not True
        or not all(
            isinstance(git.get(label), str)
            and _SHA256.fullmatch(str(git[label])) is not None
            for label in _CLOSURE_GIT_KEYS
            if label not in {"engine_cached_empty", "bb2_cached_empty"}
        )
    ):
        _fail("closure_schema_invalid")
    engine_root = _exact_absolute(engine_root, "engine_root")
    repo_root = _exact_absolute(repo_root, "repo_root")
    brain_root = _exact_absolute(brain_root, "brain_root")
    if roots != {"engine": str(engine_root), "bb2": str(repo_root), "brain": str(brain_root)}:
        _fail("closure_roots_mismatch")
    try:
        snapshot = verify_snapshot(
            Path(str(snapshot_section["path"])),
            expected_manifest_sha256=str(snapshot_section["manifest_sha256"]),
        )
    except Exception as exc:
        raise _dependency(exc) from exc
    engine_git, repo_git = _current_git_closure(engine_root, repo_root)
    expected_snapshot = {
        "path": str(snapshot_section["path"]),
        "manifest_sha256": snapshot.manifest_sha256,
        "snapshot_id": snapshot.snapshot_id,
        "file_count": snapshot.file_count,
        "verify_receipt": snapshot_section.get("verify_receipt"),
    }
    if snapshot_section != expected_snapshot:
        _fail("corpus_final_snapshot_drift")
    verify_receipt = snapshot_section.get("verify_receipt")
    if not isinstance(verify_receipt, Mapping):
        _fail("closure_schema_invalid")
    verify_value = _canonical_document(
        Path(str(verify_receipt["path"])),
        str(verify_receipt["sha256"]),
        "snapshot_verify_receipt",
    )
    if (
        not _valid_snapshot_verify_receipt(verify_value)
        or verify_value != _expected_snapshot_verify(snapshot)
    ):
        _fail("snapshot_verify_receipt_mismatch")
    binding_receipt = artifacts.get("binding")
    manifest_receipt = artifacts.get("display_manifest")
    post_receipt = artifacts.get("post_report")
    assert isinstance(binding_receipt, Mapping)
    assert isinstance(manifest_receipt, Mapping)
    assert isinstance(post_receipt, Mapping)
    binding, current_artifacts, post_value = _verify_closure_artifacts_independent(
        binding_receipt=binding_receipt,
        manifest_receipt=manifest_receipt,
        post_receipt=post_receipt,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
    )
    if current_artifacts != artifacts:
        _fail("closure_artifact_drift")
    final_evidence = _final_corpus_evidence_independent(
        brain_root=brain_root,
        repo_root=repo_root,
        binding=binding,
    )
    _verify_post_final_evidence_independent(post_value, final_evidence)
    _assert_baseline_git(binding, engine_git, repo_git)
    binding_engine = binding["engine"]
    binding_bb2 = binding["bb2"]
    migration = binding["migration"]
    assert isinstance(binding_engine, Mapping)
    assert isinstance(binding_bb2, Mapping)
    assert isinstance(migration, Mapping)
    try:
        require_commit_is_ancestor(
            engine_root, str(binding_engine["head"]), engine_git.head,
        )
        require_commit_is_ancestor(
            repo_root, str(binding_bb2["head"]), repo_git.head,
        )
    except Exception as exc:
        raise _dependency(exc) from exc
    if heads != {
        "implementation": snapshot.engine_head,
        "corpus": snapshot.repo_head,
        "docs": engine_git.head,
    } or repo_git.head != snapshot.repo_head or snapshot.engine_head != binding_engine["head"] or snapshot.corpus_fingerprint != migration["expected_after_corpus_fingerprint"]:
        _fail("closure_heads_drift")
    if git != {
        "engine_cached_empty": True,
        "bb2_cached_empty": True,
        "engine_status_sha256": engine_git.status_sha256,
        "engine_dirt_content_sha256": engine_git.content_manifest_sha256,
        "bb2_status_sha256": repo_git.status_sha256,
        "bb2_dirt_content_sha256": repo_git.content_manifest_sha256,
    }:
        _fail("closure_git_drift")
    for label in ("completion_report", "roadmap"):
        receipt = docs.get(label)
        if not isinstance(receipt, Mapping):
            _fail("committed_docs_drift", label)
        path = Path(str(receipt["path"]))
        current = _committed_doc(engine_root, path, engine_git.head, label)
        if current != receipt:
            _fail("committed_docs_drift", label)
    _closure_reverse_tail_hook()
    tail_closure = read_task18_json_bytes(
        closure_path,
        expected_sha256=expected_closure_sha256,
        label="closure",
    )
    try:
        if canonical_receipt_bytes(tail_closure.value) != tail_closure.data:
            _fail("closure_json_invalid")
    except FoundationError as exc:
        raise _dependency(exc) from exc
    tail_engine_git, tail_repo_git = _current_git_closure(engine_root, repo_root)
    if tail_engine_git != engine_git or tail_repo_git != repo_git:
        _fail("closure_state_changed_during_verify")
    try:
        tail_snapshot = verify_snapshot(
            Path(str(snapshot_section["path"])),
            expected_manifest_sha256=str(snapshot_section["manifest_sha256"]),
        )
    except Exception as exc:
        raise _dependency(exc) from exc
    if _expected_snapshot_verify(tail_snapshot) != _expected_snapshot_verify(snapshot):
        _fail("corpus_final_snapshot_drift")
    tail_verify_doc, tail_verify_receipt = _artifact_document(
        Path(str(verify_receipt["path"])),
        str(verify_receipt["sha256"]),
        "snapshot_verify_receipt",
    )
    if (
        tail_verify_receipt != verify_receipt
        or not _valid_snapshot_verify_receipt(tail_verify_doc.value)
        or tail_verify_doc.value != _expected_snapshot_verify(tail_snapshot)
    ):
        _fail("snapshot_verify_receipt_mismatch")
    tail_binding, tail_artifacts, tail_post = _verify_closure_artifacts_independent(
        binding_receipt=binding_receipt,
        manifest_receipt=manifest_receipt,
        post_receipt=post_receipt,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
    )
    if tail_artifacts != artifacts or tail_binding != binding or tail_post != post_value:
        _fail("closure_artifact_drift")
    tail_evidence = _final_corpus_evidence_independent(
        brain_root=brain_root,
        repo_root=repo_root,
        binding=tail_binding,
    )
    _verify_post_final_evidence_independent(tail_post, tail_evidence)
    if tail_evidence != final_evidence:
        _fail("closure_state_changed_during_verify")
    try:
        require_commit_is_ancestor(
            engine_root, str(binding_engine["head"]), tail_engine_git.head,
        )
        require_commit_is_ancestor(
            repo_root, str(binding_bb2["head"]), tail_repo_git.head,
        )
    except Exception as exc:
        raise _dependency(exc) from exc
    for label in ("completion_report", "roadmap"):
        receipt = docs[label]
        assert isinstance(receipt, Mapping)
        if _committed_doc(
            engine_root,
            Path(str(receipt["path"])),
            tail_engine_git.head,
            label,
        ) != receipt:
            _fail("committed_docs_drift", label)
    report = {
        "version": 1,
        "purpose": "task18-final-closure-verification",
        "generated_at": now_kst(),
        "ok": True,
        "closure": {"path": str(closure_path), "sha256": expected_closure_sha256},
    }
    try:
        report_sha = atomic_create_receipt(report_path, report)
    except FoundationError as exc:
        raise _dependency(exc) from exc
    return Task18ClosureResult(
        closure_path=closure_path,
        closure_sha256=expected_closure_sha256,
        report_path=report_path,
        report_sha256=report_sha,
    )
