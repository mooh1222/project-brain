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
from pathlib import Path
from types import MappingProxyType

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
from project_brain.lint import lint_store
from project_brain.mutation import corpus_fingerprint
from project_brain.snapshot import (
    SnapshotError,
    capture_git_dirt_receipt,
    decode_nul_paths,
    read_regular_no_follow,
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


def _canonical_document(path: Path, expected_sha256: str, label: str) -> Mapping[str, object]:
    try:
        data, _ = read_regular_no_follow(path)
    except SnapshotError as exc:
        raise _dependency(exc) from exc
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        _fail(f"{label}_sha256_mismatch")
    value = _strict_json(data, f"{label}_json_invalid")
    try:
        canonical = canonical_receipt_bytes(value) if isinstance(value, Mapping) else None
    except FoundationError as exc:
        raise _dependency(exc) from exc
    if not isinstance(value, Mapping) or canonical != data:
        _fail(f"{label}_json_invalid", "document must be canonical JSON")
    return value


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
        or value.get("version") != 1
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
        or len(targets)
        != REQUIRED_CODE_LOCATOR_COUNT + REQUIRED_EVIDENCE_REF_COUNT
    ):
        _fail("binding_schema_invalid", "migration summary differs")
    for row in targets:
        if (
            row.get("kind") not in {"CodeLocator", "EvidenceRef"}
            or not isinstance(row.get("expected_title"), str)
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
        for label in _INPUT_KEYS - {"design", "plan"}:
            bound = inputs[label]
            assert isinstance(bound, Mapping)
            if capture_bound_file(Path(str(bound["path"]))) != bound:
                _fail(f"{label}_drift")
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
    if (
        snapshot.ok is not True
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
        or value.get("migration_version") != 3
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


def _snapshot_object_sources(binding: ParsedTask18Binding) -> dict[str, tuple[str, bytes, Mapping[str, object]]]:
    manifest_path = binding.snapshot_root / "manifest.json"
    try:
        manifest_data, _ = read_regular_no_follow(manifest_path)
    except SnapshotError as exc:
        raise _dependency(exc) from exc
    manifest = _strict_json(manifest_data, "snapshot_manifest_invalid")
    files = manifest.get("files") if isinstance(manifest, Mapping) else None
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes, bytearray)):
        _fail("snapshot_manifest_invalid")
    wanted = {str(row["id"]) for row in binding.migration_targets}
    result: dict[str, tuple[str, bytes, Mapping[str, object]]] = {}
    for entry in files:
        if not isinstance(entry, Mapping) or entry.get("scope") != "brain":
            continue
        relative = entry.get("path")
        snapshot_relative = entry.get("snapshot_path")
        if not isinstance(relative, str) or not isinstance(snapshot_relative, str):
            _fail("snapshot_manifest_invalid")
        if not any(relative.startswith(f"{directory}/") for directory in BrainStore._KIND_DIR.values()):
            continue
        try:
            payload, _ = read_regular_no_follow(binding.snapshot_root / snapshot_relative)
        except SnapshotError as exc:
            raise _dependency(exc) from exc
        value = _strict_json(payload, "snapshot_object_invalid")
        object_id = value.get("id") if isinstance(value, Mapping) else None
        if object_id not in wanted:
            continue
        if object_id in result:
            _fail("snapshot_target_duplicate", str(object_id))
        result[str(object_id)] = (relative, payload, value)
    if set(result) != wanted:
        _fail("snapshot_target_set_mismatch", repr(sorted(wanted - set(result))))
    return result


def _live_object_sources(brain_root: Path, wanted: set[str]) -> dict[str, tuple[str, bytes, Mapping[str, object]]]:
    try:
        files = read_tracked_json_files(brain_root, BrainStore._KIND_DIR.values())
    except CorpusIOError as exc:
        raise _dependency(exc) from exc
    result: dict[str, tuple[str, bytes, Mapping[str, object]]] = {}
    for path, payload in files:
        value = _strict_json(payload, "live_object_invalid")
        object_id = value.get("id") if isinstance(value, Mapping) else None
        if object_id not in wanted:
            continue
        if object_id in result:
            _fail("live_target_duplicate", str(object_id))
        result[str(object_id)] = (path.relative_to(brain_root).as_posix(), payload, value)
    if set(result) != wanted:
        _fail("live_target_set_mismatch", repr(sorted(wanted - set(result))))
    return result


def _compare_snapshot_before_to_live(binding: ParsedTask18Binding) -> tuple[str, ...]:
    before = _snapshot_object_sources(binding)
    wanted = set(before)
    live = _live_object_sources(binding.brain_root, wanted)
    target_by_id = {str(row["id"]): row for row in binding.migration_targets}
    changed_paths: list[str] = []
    for object_id in sorted(wanted):
        before_path, before_bytes, before_obj = before[object_id]
        live_path, _, live_obj = live[object_id]
        target = target_by_id[object_id]
        if before_path != live_path:
            _fail("target_path_changed", object_id)
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
        changed_paths.append((binding.brain_root / live_path).relative_to(binding.repo_root).as_posix())
    return tuple(changed_paths)


def _quote_inventory(path: Path, expected_sha256: str) -> tuple[Mapping[str, object], list[str]]:
    value = _canonical_document(path, expected_sha256, "quote_debt")
    ids = value.get("quote_debt_ids")
    if (
        not isinstance(ids, Sequence)
        or isinstance(ids, (str, bytes, bytearray))
        or not all(isinstance(item, str) and item for item in ids)
        or list(ids) != sorted(ids)
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


def _snapshot_store(binding: ParsedTask18Binding) -> BrainStore:
    objects: dict[str, dict] = {}
    for _, payload, value in _snapshot_object_sources_all(binding):
        assert isinstance(value, Mapping)
        object_id = value.get("id")
        if not isinstance(object_id, str) or object_id in objects:
            _fail("snapshot_object_set_invalid")
        objects[object_id] = dict(value)
    return BrainStore(objects)


def _snapshot_object_sources_all(binding: ParsedTask18Binding):
    manifest_data, _ = read_regular_no_follow(binding.snapshot_root / "manifest.json")
    manifest = _strict_json(manifest_data, "snapshot_manifest_invalid")
    files = manifest.get("files") if isinstance(manifest, Mapping) else None
    if not isinstance(files, Sequence) or isinstance(files, (str, bytes, bytearray)):
        _fail("snapshot_manifest_invalid")
    for entry in files:
        if not isinstance(entry, Mapping) or entry.get("scope") != "brain":
            continue
        relative = entry.get("path")
        snapshot_relative = entry.get("snapshot_path")
        if (
            not isinstance(relative, str)
            or not isinstance(snapshot_relative, str)
            or not any(relative.startswith(f"{directory}/") for directory in BrainStore._KIND_DIR.values())
        ):
            continue
        payload, _ = read_regular_no_follow(binding.snapshot_root / snapshot_relative)
        value = _strict_json(payload, "snapshot_object_invalid")
        if not isinstance(value, Mapping):
            _fail("snapshot_object_invalid")
        yield relative, payload, value


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
    quote_debt_path: Path,
    expected_quote_debt_sha256: str,
) -> None:
    _, quote_ids = _quote_inventory(quote_debt_path, expected_quote_debt_sha256)
    try:
        before_store = _snapshot_store(binding)
        live_store = BrainStore.load(binding.brain_root)
        state = capture_task18_corpus_state(binding.brain_root)
    except Exception as exc:
        raise _dependency(exc) from exc
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
    if _noncanonical_symbol_ids(before_store) != _noncanonical_symbol_ids(live_store):
        _fail("noncanonical_symbols_changed")
    if len(before_store.all()) != len(live_store.all()):
        _fail("object_count_changed")
    if corpus_fingerprint(live_store) != binding.expected_after_corpus_fingerprint:
        _fail("after_corpus_fingerprint_mismatch")
    if lint_store(live_store, binding.repo_root):
        _fail("lint_not_clean")
    if _paired_title_mismatches(live_store):
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


def _atomic_create_pathspec(path: Path, paths: Sequence[str]) -> str:
    path = _exact_absolute(path, "pathspec_output")
    payload = b"".join(os.fsencode(value) + b"\0" for value in paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        _fail("pathspec_exists", str(path))
    except OSError as exc:
        _fail("pathspec_create_failed", str(exc))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return hashlib.sha256(payload).hexdigest()


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
    if report_path.exists():
        _fail("report_exists", str(report_path))
    if pathspec_output.exists():
        _fail("pathspec_exists", str(pathspec_output))
    binding = parse_task18_binding_for_post_verify(
        binding_path=binding_path,
        expected_binding_sha256=expected_binding_sha256,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
    )
    _read_display_manifest(Path(manifest_path), expected_manifest_sha256, binding)
    changed_paths = _compare_snapshot_before_to_live(binding)
    _assert_post_invariants(
        binding,
        quote_debt_path=Path(quote_debt_path),
        expected_quote_debt_sha256=expected_quote_debt_sha256,
    )
    try:
        brain_objects = (binding.brain_root / "objects").relative_to(binding.repo_root).as_posix()
        git_changed = set(
            decode_nul_paths(
                run_git_bytes(
                    binding.repo_root,
                    "diff", "--name-only", "-z", "HEAD", "--", brain_objects,
                )
            )
        )
        if git_changed != set(changed_paths):
            _fail("git_target_path_mismatch", repr(sorted(git_changed ^ set(changed_paths))))
        allowed = tuple(sorted((*changed_paths, report_path.relative_to(binding.repo_root).as_posix())))
        verify_git_dirt_preserved(
            binding.repo_root,
            baseline_status_bytes=binding.baseline_status_bytes,
            baseline_content_manifest_bytes=binding.baseline_dirt_manifest_bytes,
            label="task18_post_apply",
            allowed_extra_paths=allowed,
        )
    except Exception as exc:
        raise _dependency(exc) from exc
    report = {
        "version": 1,
        "purpose": "task18-post-apply-verification",
        "generated_at": generated_at,
        "binding": {"path": str(binding.path), "sha256": binding.sha256},
        "display_manifest": {"path": str(manifest_path), "sha256": expected_manifest_sha256},
        "quote_debt": {"path": str(quote_debt_path), "sha256": expected_quote_debt_sha256},
        "target_ids_sha256": binding.target_ids_sha256,
        "changed_paths": list(changed_paths),
        "update_count": len(changed_paths),
        "quote_debt_unchanged": True,
        "noncanonical_symbols_unchanged": True,
        "index_db_unchanged": True,
        "user_dirt_preserved": True,
    }
    try:
        report_sha = atomic_create_receipt(report_path, report)
        _atomic_create_pathspec(pathspec_output, changed_paths)
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


def _artifact_receipt(path: Path, expected_sha256: str, label: str) -> dict[str, object]:
    path = _exact_absolute(path, label)
    receipt = dict(capture_bound_file(path))
    if receipt["sha256"] != expected_sha256:
        _fail(f"{label}_sha256_mismatch")
    return receipt


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


def create_task18_closure_receipt(
    *,
    closure_path: Path,
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
    generated_at: str,
) -> Task18ClosureResult:
    closure_path = _exact_absolute(closure_path, "closure_path")
    report_path = _exact_absolute(report_path, "report_path")
    engine_root = _exact_absolute(engine_root, "engine_root")
    repo_root = _exact_absolute(repo_root, "repo_root")
    brain_root = _exact_absolute(brain_root, "brain_root")
    if closure_path.exists():
        _fail("closure_exists", str(closure_path))
    if report_path.exists():
        _fail("report_exists", str(report_path))
    try:
        snapshot = verify_snapshot(
            _exact_absolute(corpus_final_snapshot_root, "corpus_final_snapshot_root"),
            expected_manifest_sha256=expected_snapshot_manifest_sha256,
        )
    except Exception as exc:
        raise _dependency(exc) from exc
    engine_git, repo_git = _current_git_closure(engine_root, repo_root)
    if snapshot.repo_head != repo_git.head:
        _fail("corpus_head_mismatch")
    verify_receipt = _artifact_receipt(
        snapshot_verify_receipt_path,
        expected_snapshot_verify_receipt_sha256,
        "snapshot_verify_receipt",
    )
    verify_value = _canonical_document(
        Path(snapshot_verify_receipt_path),
        expected_snapshot_verify_receipt_sha256,
        "snapshot_verify_receipt",
    )
    if verify_value != {
        "ok": True,
        "snapshot_id": snapshot.snapshot_id,
        "manifest_sha256": snapshot.manifest_sha256,
        "file_count": snapshot.file_count,
    }:
        _fail("snapshot_verify_receipt_mismatch")
    completion = _committed_doc(engine_root, completion_report_path, engine_git.head, "completion_report")
    roadmap = _committed_doc(engine_root, roadmap_path, engine_git.head, "roadmap")
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
        "artifacts": {
            "binding": _artifact_receipt(binding_path, expected_binding_sha256, "binding"),
            "display_manifest": _artifact_receipt(manifest_path, expected_manifest_sha256, "display_manifest"),
            "post_report": _artifact_receipt(post_report_path, expected_post_report_sha256, "post_report"),
        },
        "heads": {
            "implementation": snapshot.engine_head,
            "corpus": snapshot.repo_head,
            "docs": engine_git.head,
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
    try:
        closure_sha = atomic_create_receipt(closure_path, value)
    except FoundationError as exc:
        raise _dependency(exc) from exc
    return verify_task18_closure_receipt(
        closure_path=closure_path,
        expected_closure_sha256=closure_sha,
        engine_root=engine_root,
        repo_root=repo_root,
        report_path=report_path,
        generated_at=generated_at,
    )


def verify_task18_closure_receipt(
    *,
    closure_path: Path,
    expected_closure_sha256: str,
    engine_root: Path,
    repo_root: Path,
    report_path: Path,
    generated_at: str,
) -> Task18ClosureResult:
    """생성 payload builder를 쓰지 않고 closure와 현재 상태를 다시 계산한다."""
    closure_path = _exact_absolute(closure_path, "closure_path")
    report_path = _exact_absolute(report_path, "report_path")
    if report_path.exists():
        _fail("report_exists", str(report_path))
    value = _canonical_document(closure_path, expected_closure_sha256, "closure")
    if (
        set(value) != _CLOSURE_KEYS
        or value.get("version") != 1
        or value.get("purpose") != "task18-final-closure"
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
    if roots.get("engine") != str(engine_root) or roots.get("bb2") != str(repo_root):
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
    if verify_value != {
        "ok": True,
        "snapshot_id": snapshot.snapshot_id,
        "manifest_sha256": snapshot.manifest_sha256,
        "file_count": snapshot.file_count,
    }:
        _fail("snapshot_verify_receipt_mismatch")
    for label in ("binding", "display_manifest", "post_report"):
        receipt = artifacts.get(label)
        if not isinstance(receipt, Mapping) or capture_bound_file(Path(str(receipt["path"]))) != receipt:
            _fail(f"{label}_drift")
    if heads != {
        "implementation": snapshot.engine_head,
        "corpus": snapshot.repo_head,
        "docs": engine_git.head,
    } or repo_git.head != snapshot.repo_head:
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
    report = {
        "version": 1,
        "purpose": "task18-final-closure-verification",
        "generated_at": generated_at,
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
