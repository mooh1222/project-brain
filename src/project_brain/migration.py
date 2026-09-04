"""ID-only와 CodeLocator display-only migration 계획·적용."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from project_brain.corpus_io import (
    CorpusIOError,
    inspect_tracked_file,
    read_tracked_file_bytes,
)
from project_brain.display_contract import (
    canonical_locator_title,
    non_title_sha256,
    paired_code_locator_id,
)
from project_brain.eval_harness import ASSERTION_KEYS
from project_brain.hash_utils import stable_json
from project_brain.id_grammar import IdGrammarError, parse_id
from project_brain.mutation import (
    AuxiliaryFileUpdate,
    MutationOperation,
    MutationPlanResult,
    MutationRequest,
    MutationService,
    canonical_unstamped_intent,
    corpus_fingerprint,
    is_target_derived_single_review_rename,
)
from project_brain.reference_fields import iter_object_refs, rewrite_object_refs
from project_brain.repo_context import RepoContext
from project_brain.snapshot import (
    SnapshotError,
    SnapshotVerification,
    verify_git_root_head,
    verify_snapshot,
)
from project_brain.store import BrainStore
from project_brain.task18_binding_verify import (
    Task18BindingVerification,
    verify_task18_binding,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SNAPSHOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_EVAL_ID_LIST_KEYS = frozenset({
    "top5_any",
    "any_channel_top5_any",
    "advisories_top5_any",
    "projection_reuse_top5_any",
})
# id 리스트가 아닌 문자열 리스트 판정 키 — 형태만 검증하고 rename 재작성은 하지
# 않는다. raw_top5_prefix_any는 청크 프리픽스,
# query_tokens_object_df_zero_any(#76)는 질의 토큰이라 둘 다 object_id가 아니다.
_EVAL_STRING_LIST_KEYS = _EVAL_ID_LIST_KEYS | {
    "raw_top5_prefix_any",
    "query_tokens_object_df_zero_any",
}
_MIGRATION_TAG = "__project_brain_migration_placeholder__"
_INDEX_PATHS = (
    ".brain-local/index.db",
    ".brain-local/index.db-wal",
    ".brain-local/index.db-shm",
    ".brain-local/index.db-journal",
)
DISPLAY_ARTIFACT_KEYS = {
    "migration_version",
    "migration_kind",
    "intent",
    "snapshot_id",
    "snapshot_manifest_sha256",
    "task18_binding_path",
    "task18_binding_sha256",
}


@dataclass(frozen=True)
class MigrationError(RuntimeError):
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True)
class MigrationRow:
    old_id: str
    new_id: str
    kind: str
    canonical_payload_hash: str
    reference_rewrites: tuple[dict, ...]
    dependent_artifacts: tuple[dict, ...]
    snapshot_id: str


@dataclass(frozen=True)
class MigrationPlan:
    migration_kind: str
    request: MutationRequest
    mutation_plan: MutationPlanResult
    rows: tuple[MigrationRow, ...]
    snapshot_id: str
    snapshot_manifest_sha256: str
    binding_path: Path | None = None
    binding_sha256: str | None = None


@dataclass(frozen=True)
class MigrationArtifact:
    manifest: dict
    manifest_bytes: bytes
    manifest_sha256: str


@dataclass(frozen=True)
class MigrationApplyResult:
    transaction_id: str
    action_count: int
    snapshot_id: str


@dataclass(frozen=True)
class MigrationArtifactVerification:
    ok: bool
    artifact: Mapping[str, object]
    plan: MigrationPlan


def _fail(code: str, detail: str) -> None:
    raise MigrationError(code, detail)


def _object_hash(obj: Mapping[str, object]) -> str:
    return hashlib.sha256(BrainStore.object_bytes(obj)).hexdigest()


def validate_snapshot_binding(
    snapshot: SnapshotVerification,
) -> None:
    if (
        not isinstance(snapshot, SnapshotVerification)
        or snapshot.ok is not True
    ):
        _fail("snapshot_verification_invalid", "trusted snapshot is invalid")
    if (
        not isinstance(snapshot.snapshot_id, str)
        or _SNAPSHOT_ID.fullmatch(snapshot.snapshot_id) is None
    ):
        _fail("snapshot_id_invalid", "snapshot_id is empty or unsafe")
    if (
        not isinstance(snapshot.manifest_sha256, str)
        or _SHA256.fullmatch(snapshot.manifest_sha256) is None
    ):
        _fail(
            "snapshot_receipt_invalid",
            "trusted snapshot receipt must be an exact lowercase SHA-256",
        )
    if (
        not isinstance(snapshot.repo_head, str)
        or re.fullmatch(r"[0-9a-f]{40}", snapshot.repo_head) is None
        or not isinstance(snapshot.engine_head, str)
        or re.fullmatch(r"[0-9a-f]{40}", snapshot.engine_head) is None
    ):
        _fail(
            "snapshot_git_head_invalid",
            "trusted snapshot Git heads must be lowercase 40-hex SHAs",
        )
    if (
        not isinstance(snapshot.corpus_fingerprint, str)
        or _SHA256.fullmatch(snapshot.corpus_fingerprint) is None
    ):
        _fail(
            "snapshot_corpus_fingerprint_invalid",
            "trusted snapshot corpus fingerprint must be lowercase SHA-256",
        )


def trusted_migration_context(
    *,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
    engine_sha: str,
    snapshot: SnapshotVerification,
) -> RepoContext:
    validate_snapshot_binding(snapshot)
    _validate_engine_sha(engine_sha)
    if (
        not isinstance(brain_root, Path)
        or not brain_root.is_absolute()
        or not isinstance(repo_root, Path)
        or not repo_root.is_absolute()
        or not isinstance(engine_root, Path)
        or not engine_root.is_absolute()
    ):
        _fail(
            "request_invalid",
            "brain_root, repo_root, and engine_root must be absolute Paths",
        )
    if not brain_root.is_relative_to(repo_root):
        _fail(
            "repo_root_mismatch",
            "brain_root must be inside the explicit repo_root",
        )
    try:
        repo_head = verify_git_root_head(repo_root, label="repo_root")
        engine_head = verify_git_root_head(engine_root, label="engine_root")
    except SnapshotError as exc:
        _fail(exc.code, exc.detail)
    if repo_head != snapshot.repo_head:
        _fail(
            "snapshot_repo_head_mismatch",
            "current repo HEAD differs from the trusted snapshot",
        )
    if engine_head != snapshot.engine_head or engine_sha != engine_head:
        _fail(
            "snapshot_engine_head_mismatch",
            "current engine HEAD or engine_sha differs from the trusted snapshot",
        )
    return RepoContext(
        repo_root=repo_root,
        expected_repo_id="migration-snapshot",
        expected_revision_ref="HEAD",
        target_revision_sha=repo_head,
    )


def validate_live_snapshot_corpus(
    existing: BrainStore,
    snapshot: SnapshotVerification,
) -> None:
    live_fingerprint = corpus_fingerprint(existing)
    if live_fingerprint != snapshot.corpus_fingerprint:
        _fail(
            "snapshot_corpus_fingerprint_mismatch",
            "live corpus differs from the trusted snapshot baseline",
        )


def _validate_engine_sha(engine_sha: str) -> None:
    if not isinstance(engine_sha, str) or _GIT_SHA.fullmatch(engine_sha) is None:
        _fail("engine_sha_invalid", "engine_sha must be an exact lowercase Git SHA")


def _validate_renames(
    existing_by_id: Mapping[str, dict],
    renames: Mapping[str, str],
) -> dict[str, str]:
    if not isinstance(renames, Mapping) or not renames:
        _fail("renames_invalid", "renames must be a non-empty mapping")
    pairs: dict[str, str] = {}
    for old_id, new_id in renames.items():
        if (
            not isinstance(old_id, str)
            or not old_id
            or not isinstance(new_id, str)
            or not new_id
            or old_id == new_id
        ):
            _fail("renames_invalid", "rename IDs must be distinct non-empty strings")
        pairs[old_id] = new_id
    if len(set(pairs.values())) != len(pairs):
        _fail("duplicate_new_id", "rename mapping contains a duplicate new ID")
    for old_id, new_id in sorted(pairs.items()):
        if old_id not in existing_by_id:
            _fail("migration_source_missing", f"migration source is missing: {old_id}")
        if new_id in existing_by_id:
            _fail("migration_target_exists", f"migration target already exists: {new_id}")
    return dict(sorted(pairs.items()))


def _placeholder(kind: str, ordinal: int | None = None) -> dict:
    payload: dict[str, object] = {"kind": kind}
    if ordinal is not None:
        payload["ordinal"] = ordinal
    return {_MIGRATION_TAG: payload}


def _reference_tokens(
    renames: Mapping[str, str],
) -> tuple[dict[str, dict], dict[str, dict]]:
    before: dict[str, dict] = {}
    after: dict[str, dict] = {}
    for index, (old_id, new_id) in enumerate(
        sorted(renames.items()),
        start=1,
    ):
        token = _placeholder("reference", index)
        before[old_id] = token
        after[new_id] = token
    return before, after


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    return tuple(
        token.replace("~1", "/").replace("~0", "~")
        for token in pointer[1:].split("/")
    )


def _set_pointer_value(obj: dict, pointer: str, value: object) -> None:
    tokens = _pointer_tokens(pointer)
    current: object = obj
    for token in tokens[:-1]:
        current = (
            current[int(token)]
            if isinstance(current, list)
            else current[token]
        )
    final = tokens[-1]
    if isinstance(current, list):
        current[int(final)] = value
    else:
        current[final] = value


def _canonical_shape(
    obj: Mapping[str, object],
    *,
    self_id: str,
    reference_tokens: Mapping[str, dict],
) -> dict:
    shaped = deepcopy(dict(obj))
    for ref in iter_object_refs(obj):
        replacement = reference_tokens.get(ref.object_id)
        if replacement is not None:
            _set_pointer_value(shaped, ref.pointer, deepcopy(replacement))
    if shaped.get("id") != self_id:
        _fail("canonical_payload_invalid", "self ID does not match the migration row")
    shaped["id"] = _placeholder("self")
    return shaped


def canonical_payload_hash_pair(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    renames: Mapping[str, str],
    old_id: str,
    new_id: str,
) -> str:
    """Hash one ID-only pair after structural self/reference tokenization."""
    before_tokens, after_tokens = _reference_tokens(renames)
    before_shape = _canonical_shape(
        before,
        self_id=old_id,
        reference_tokens=before_tokens,
    )
    after_shape = _canonical_shape(
        after,
        self_id=new_id,
        reference_tokens=after_tokens,
    )
    before_json = stable_json(before_shape)
    after_json = stable_json(after_shape)
    if before_json != after_json:
        _fail(
            "canonical_payload_mismatch",
            f"{old_id}: canonical payload changed outside ID/registry references",
        )
    return hashlib.sha256(before_json.encode("utf-8")).hexdigest()


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _rewrite_string_list(
    value: object,
    *,
    pointer: str,
    renames: Mapping[str, str],
    rewrites: list[dict],
) -> None:
    if not isinstance(value, list):
        _fail("eval_invalid", f"expected ID list at {pointer}")
    for index, item in enumerate(value):
        item_pointer = f"{pointer}/{index}"
        if isinstance(item, list):
            _rewrite_string_list(
                item,
                pointer=item_pointer,
                renames=renames,
                rewrites=rewrites,
            )
            continue
        if not isinstance(item, str):
            _fail("eval_invalid", f"expected string ID at {item_pointer}")
        replacement = renames.get(item)
        if replacement is None:
            continue
        value[index] = replacement
        rewrites.append({
            "artifact": "eval_scenarios.json",
            "action": "rewrite",
            "pointer": item_pointer,
            "before_id": item,
            "after_id": replacement,
        })


def _rewrite_eval(
    payload: object,
    renames: Mapping[str, str],
) -> tuple[dict, tuple[dict, ...]]:
    if not isinstance(payload, dict):
        _fail("eval_invalid", "eval_scenarios.json must contain an object")
    rewritten = json.loads(json.dumps(payload, ensure_ascii=False))
    scenarios = rewritten.get("scenarios")
    if not isinstance(scenarios, list):
        _fail("eval_invalid", "eval_scenarios.json scenarios must be a list")
    rewrites: list[dict] = []
    for scenario_index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict) or not isinstance(
            scenario.get("expect"),
            dict,
        ):
            _fail("eval_invalid", f"scenario {scenario_index} expect is invalid")
        expect = scenario["expect"]
        expect_pointer = f"/scenarios/{scenario_index}/expect"
        for key in sorted(_EVAL_ID_LIST_KEYS):
            if key not in expect:
                continue
            _rewrite_string_list(
                expect[key],
                pointer=f"{expect_pointer}/{_pointer_token(key)}",
                renames=renames,
                rewrites=rewrites,
            )
        if "linked_any_groups" in expect:
            _rewrite_string_list(
                expect["linked_any_groups"],
                pointer=f"{expect_pointer}/linked_any_groups",
                renames=renames,
                rewrites=rewrites,
            )
    return rewritten, tuple(sorted(rewrites, key=lambda item: item["pointer"]))


def _duplicate_key_rejector(pairs: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("eval_invalid", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_string_list(
    value: object,
    *,
    pointer: str,
) -> None:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
        or len(set(value)) != len(value)
    ):
        _fail(
            "eval_invalid",
            f"{pointer} must be an exact non-empty list of unique strings",
        )


def _validate_eval_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        _fail("eval_invalid", "eval_scenarios.json must contain an object")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        _fail("eval_invalid", "scenarios must be a non-empty list")
    seen_scenario_ids: set[str] = set()
    for index, scenario in enumerate(scenarios):
        pointer = f"/scenarios/{index}"
        if not isinstance(scenario, dict):
            _fail("eval_invalid", f"{pointer} must be an object")
        scenario_id = scenario.get("id")
        query = scenario.get("query")
        expect = scenario.get("expect")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            _fail("eval_invalid", f"{pointer}/id must be a non-empty string")
        if scenario_id in seen_scenario_ids:
            _fail("eval_invalid", f"duplicate scenario id: {scenario_id}")
        seen_scenario_ids.add(scenario_id)
        if not isinstance(query, str) or not query.strip():
            _fail("eval_invalid", f"{pointer}/query must be a non-empty string")
        if not isinstance(expect, dict) or not expect:
            _fail("eval_invalid", f"{pointer}/expect must be a non-empty object")
        unknown = set(expect) - ASSERTION_KEYS
        if unknown:
            _fail(
                "eval_invalid",
                f"{pointer}/expect has unknown keys: {sorted(unknown)}",
            )
        for key in sorted(_EVAL_STRING_LIST_KEYS & set(expect)):
            _validate_string_list(
                expect[key],
                pointer=f"{pointer}/expect/{key}",
            )
        if "linked_any_groups" in expect:
            groups = expect["linked_any_groups"]
            if not isinstance(groups, list) or not groups:
                _fail(
                    "eval_invalid",
                    f"{pointer}/expect/linked_any_groups must be list[list[str]]",
                )
            seen_ids: set[str] = set()
            for group_index, group in enumerate(groups):
                _validate_string_list(
                    group,
                    pointer=(
                        f"{pointer}/expect/linked_any_groups/{group_index}"
                    ),
                )
                overlap = seen_ids & set(group)
                if overlap:
                    _fail(
                        "eval_invalid",
                        f"duplicate linked expected IDs: {sorted(overlap)}",
                    )
                seen_ids.update(group)
        if "max_results" in expect and (
            type(expect["max_results"]) is not int
            or expect["max_results"] <= 0
        ):
            _fail(
                "eval_invalid",
                f"{pointer}/expect/max_results must be a positive integer",
            )
    return payload


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _eval_update(
    brain_root: Path,
    renames: Mapping[str, str],
) -> tuple[tuple[AuxiliaryFileUpdate, ...], tuple[dict, ...]]:
    try:
        before_bytes = read_tracked_file_bytes(
            brain_root,
            "eval_scenarios.json",
        )
    except CorpusIOError as exc:
        if exc.code == "tracked_file_missing":
            return (), ()
        _fail(exc.code, exc.detail)
    try:
        before_payload = json.loads(
            before_bytes,
            object_pairs_hook=_duplicate_key_rejector,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail("eval_invalid", str(exc))
    before_payload = _validate_eval_payload(before_payload)
    after_payload, rewrites = _rewrite_eval(before_payload, renames)
    if not rewrites:
        return (), ()
    after_bytes = _canonical_json_bytes(after_payload)
    return (
        (AuxiliaryFileUpdate(
            path="eval_scenarios.json",
            before_sha256=hashlib.sha256(before_bytes).hexdigest(),
            after_sha256=hashlib.sha256(after_bytes).hexdigest(),
            after_bytes=after_bytes,
        ),),
        rewrites,
    )


def _exact_string_pointers(
    value: object,
    target: str,
    pointer: str = "",
) -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, dict):
        for key in sorted(value):
            child_pointer = f"{pointer}/{_pointer_token(str(key))}"
            if key == target:
                found.append(child_pointer)
            found.extend(_exact_string_pointers(
                value[key],
                target,
                child_pointer,
            ))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_exact_string_pointers(
                item,
                target,
                f"{pointer}/{index}",
            ))
    elif value == target:
        found.append(pointer)
    return tuple(found)


def _dependent_invalidations(
    brain_root: Path,
    renames: Mapping[str, str],
    eval_rewrites: tuple[dict, ...],
) -> dict[str, tuple[dict, ...]]:
    by_old: dict[str, list[dict]] = {old_id: [] for old_id in renames}
    for rewrite in eval_rewrites:
        by_old[rewrite["before_id"]].append(dict(rewrite))
    try:
        stale_bytes = read_tracked_file_bytes(
            brain_root,
            ".brain-local/stale-set.json",
        )
    except CorpusIOError as exc:
        if exc.code != "tracked_file_missing":
            _fail(exc.code, exc.detail)
    else:
        try:
            stale = json.loads(stale_bytes)
        except (UnicodeError, json.JSONDecodeError):
            stale = None
        for old_id in renames:
            for pointer in _exact_string_pointers(stale, old_id):
                by_old[old_id].append({
                    "artifact": ".brain-local/stale-set.json",
                    "action": "invalidate",
                    "pointer": pointer,
                    "object_id": old_id,
                })
    has_index = False
    for path in _INDEX_PATHS:
        try:
            if inspect_tracked_file(brain_root, path)["had_before"]:
                has_index = True
                break
        except CorpusIOError as exc:
            _fail(exc.code, exc.detail)
    if has_index:
        for old_id in renames:
            by_old[old_id].append({
                "artifact": ".brain-local/index.db*",
                "action": "invalidate",
                "document_id": old_id,
            })
    return {
        old_id: tuple(sorted(
            items,
            key=lambda item: (
                str(item.get("artifact")),
                str(item.get("pointer", "")),
                str(item.get("document_id", "")),
            ),
        ))
        for old_id, items in by_old.items()
    }


def plan_id_migration(
    *,
    existing: BrainStore,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
    engine_sha: str,
    renames: Mapping[str, str],
    snapshot: SnapshotVerification,
) -> MigrationPlan:
    if not isinstance(existing, BrainStore):
        _fail("request_invalid", "existing must be BrainStore")
    repo_context = trusted_migration_context(
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        engine_sha=engine_sha,
        snapshot=snapshot,
    )
    validate_live_snapshot_corpus(existing, snapshot)
    existing_by_id = {obj["id"]: obj for obj in existing.all()}
    pairs = _validate_renames(existing_by_id, renames)
    request_objects: list[dict] = []
    for object_id in sorted(existing_by_id):
        rewritten, changed_refs = rewrite_object_refs(
            existing_by_id[object_id],
            pairs,
        )
        new_id = pairs.get(object_id, object_id)
        if new_id != object_id:
            rewritten["id"] = new_id
        if new_id != object_id or changed_refs:
            request_objects.append(rewritten)
    request_by_id = {obj["id"]: obj for obj in request_objects}
    for old_id, new_id in pairs.items():
        before = existing_by_id[old_id]
        after = request_by_id[new_id]
        try:
            parsed = parse_id(old_id, "ReviewRecord")
        except IdGrammarError:
            continue
        if (
            parsed.variant == "single"
            and before.get("target_object_id") == parsed.target_object_id
            and not is_target_derived_single_review_rename(
                before,
                after,
                pairs,
            )
        ):
            _fail(
                "id_only_legacy_source_not_invalid",
                f"{old_id}: ID-only rename source has no structured ID problem",
            )
    auxiliary_updates, eval_rewrites = _eval_update(brain_root, pairs)
    preconditions = {
        old_id: _object_hash(existing_by_id[old_id])
        for old_id in pairs
    }
    for obj in request_objects:
        object_id = str(obj["id"])
        if object_id in existing_by_id:
            preconditions[object_id] = _object_hash(existing_by_id[object_id])
    request = MutationRequest(
        operation=MutationOperation.ID_ONLY_MIGRATION,
        brain_root=brain_root,
        repo_context=repo_context,
        engine_sha=engine_sha,
        objects=tuple(request_objects),
        delete_ids=tuple(pairs),
        preconditions=dict(sorted(preconditions.items())),
        expected_corpus_fingerprint=corpus_fingerprint(existing),
        auxiliary_updates=auxiliary_updates,
    )
    mutation_plan = MutationService().preview(request.objects, request=request)
    if not mutation_plan.ok:
        _fail(
            mutation_plan.error_code or "mutation_plan_failed",
            mutation_plan.detail or "ID-only mutation preflight failed",
        )
    after_by_id = {
        obj["id"]: obj
        for obj in mutation_plan.after_objects
    }
    dependent = _dependent_invalidations(
        brain_root,
        pairs,
        eval_rewrites,
    )
    rows: list[MigrationRow] = []
    for old_id, new_id in pairs.items():
        before = existing_by_id[old_id]
        after = after_by_id[new_id]
        canonical_hash = canonical_payload_hash_pair(
            before,
            after,
            renames=pairs,
            old_id=old_id,
            new_id=new_id,
        )
        row_rewrites = tuple(
            dict(rewrite)
            for rewrite in mutation_plan.reference_rewrites
            if (
                rewrite["before_id"] == old_id
                and rewrite["after_id"] == new_id
            )
        )
        rows.append(MigrationRow(
            old_id=old_id,
            new_id=new_id,
            kind=str(before["kind"]),
            canonical_payload_hash=canonical_hash,
            reference_rewrites=row_rewrites,
            dependent_artifacts=dependent[old_id],
            snapshot_id=snapshot.snapshot_id,
        ))
    return MigrationPlan(
        migration_kind="id_only",
        request=request,
        mutation_plan=mutation_plan,
        rows=tuple(rows),
        snapshot_id=snapshot.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
    )


def _display_migration_inputs(
    existing_by_id: Mapping[str, dict],
) -> tuple[dict, ...]:
    locators = {
        object_id: obj
        for object_id, obj in existing_by_id.items()
        if obj.get("kind") == "CodeLocator"
    }
    inputs: list[dict] = []
    for object_id in sorted(existing_by_id):
        obj = existing_by_id[object_id]
        if obj.get("kind") == "CodeLocator":
            if obj.get("title") != canonical_locator_title(obj):
                inputs.append(dict(obj))
            continue
        locator_id = paired_code_locator_id(obj)
        locator = locators.get(locator_id) if locator_id is not None else None
        if (
            locator is not None
            and obj.get("title") != canonical_locator_title(locator)
        ):
            inputs.append(dict(obj))
    return tuple(inputs)


def plan_display_migration(
    *,
    existing: BrainStore,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
    task18_binding_path: Path,
    expected_task18_binding_sha256: str,
) -> MigrationPlan:
    binding_path = _validate_task18_binding_caller(
        task18_binding_path,
        expected_task18_binding_sha256,
    )
    binding = verify_task18_binding(
        binding_path=binding_path,
        expected_binding_sha256=expected_task18_binding_sha256,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
    )
    _validate_verified_task18_binding(
        binding,
        binding_path=binding_path,
        binding_sha256=expected_task18_binding_sha256,
    )
    snapshot = _verify_task18_snapshot(binding)
    return _build_bound_display_plan(
        existing=existing,
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        binding=binding,
        snapshot=snapshot,
    )


def _validate_task18_binding_caller(
    binding_path: Path,
    binding_sha256: str,
) -> Path:
    path = Path(binding_path)
    if (
        not path.is_absolute()
        or path != Path(os.path.abspath(path))
        or not isinstance(binding_sha256, str)
        or _SHA256.fullmatch(binding_sha256) is None
    ):
        _fail(
            "task18_binding_invalid",
            "display artifact requires an exact binding path and SHA",
        )
    return path


def _validate_verified_task18_binding(
    binding: Task18BindingVerification,
    *,
    binding_path: Path,
    binding_sha256: str,
) -> None:
    if (
        not isinstance(binding, Task18BindingVerification)
        or binding.path != str(binding_path)
        or binding.sha256 != binding_sha256
        or binding.task18_allowed is not True
    ):
        _fail(
            "task18_binding_mismatch",
            "verified Task 18 binding differs from the caller binding",
        )


def _verify_task18_snapshot(
    binding: Task18BindingVerification,
) -> SnapshotVerification:
    try:
        snapshot = verify_snapshot(
            binding.snapshot_root,
            expected_manifest_sha256=binding.snapshot_manifest_sha256,
        )
    except SnapshotError as exc:
        _fail(exc.code, exc.detail)
    validate_snapshot_binding(snapshot)
    if snapshot.manifest_sha256 != binding.snapshot_manifest_sha256:
        _fail(
            "snapshot_binding_mismatch",
            "verified snapshot differs from the Task 18 binding",
        )
    return snapshot


def _build_bound_display_plan(
    *,
    existing: BrainStore,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
    binding: Task18BindingVerification,
    snapshot: SnapshotVerification,
) -> MigrationPlan:
    repo_context = trusted_migration_context(
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        engine_sha=snapshot.engine_head,
        snapshot=snapshot,
    )
    validate_live_snapshot_corpus(existing, snapshot)
    unbound = plan_display_migration_unbound(
        existing=existing,
        brain_root=brain_root,
        repo_context=repo_context,
        engine_sha=snapshot.engine_head,
        snapshot=snapshot,
    )
    _validate_bound_display_targets(existing, unbound, binding)
    return replace(
        unbound,
        binding_path=Path(binding.path),
        binding_sha256=binding.sha256,
    )


def _validate_bound_display_targets(
    existing: BrainStore,
    plan: MigrationPlan,
    binding: Task18BindingVerification,
) -> None:
    before_by_id = {
        str(obj["id"]): obj
        for obj in plan.request.objects
    }
    after_by_id = {
        str(obj["id"]): obj
        for obj in plan.mutation_plan.after_objects
    }
    targets: list[dict[str, object]] = []
    for object_id in sorted(before_by_id):
        before = before_by_id[object_id]
        after = after_by_id.get(object_id)
        if after is None:
            _fail(
                "manifest_revalidation_failed",
                f"{object_id}: display plan has no bound after object",
            )
        targets.append({
            "id": object_id,
            "kind": before.get("kind"),
            "paired_locator_id": paired_code_locator_id(before),
            "before_object_sha256": existing.source_sha256(object_id),
            "before_non_title_sha256": non_title_sha256(before),
            "expected_title": after.get("title"),
        })
    if tuple(targets) != tuple(binding.migration_targets):
        _fail(
            "manifest_revalidation_failed",
            "live display plan differs from the verified Task 18 targets",
        )


def plan_display_migration_unbound(
    *,
    existing: BrainStore,
    brain_root: Path,
    repo_context: RepoContext,
    engine_sha: str,
    snapshot: SnapshotVerification,
) -> MigrationPlan:
    """이미 검증된 저장소와 migration 결속으로 display plan을 만든다."""
    existing_by_id = {obj["id"]: obj for obj in existing.all()}
    inputs = _display_migration_inputs(existing_by_id)
    request = MutationRequest(
        operation=MutationOperation.DISPLAY_MIGRATION,
        brain_root=brain_root,
        repo_context=repo_context,
        engine_sha=engine_sha,
        objects=inputs,
        preconditions={
            obj["id"]: _object_hash(existing_by_id[obj["id"]])
            for obj in inputs
        },
        expected_corpus_fingerprint=corpus_fingerprint(existing),
    )
    mutation_plan = MutationService().preview(inputs, request=request)
    if not mutation_plan.ok:
        _fail(
            mutation_plan.error_code or "mutation_plan_failed",
            mutation_plan.detail or "display mutation preflight failed",
        )
    for after in mutation_plan.after_objects:
        before = existing_by_id[after["id"]]
        if non_title_sha256(before) != non_title_sha256(after):
            _fail(
                "display_payload_changed",
                f"{after['id']}: display migration changed a non-title field",
            )
    return MigrationPlan(
        migration_kind="display_only",
        request=request,
        mutation_plan=mutation_plan,
        rows=(),
        snapshot_id=snapshot.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
    )


def create_migration_artifact(plan: MigrationPlan) -> MigrationArtifact:
    if plan.migration_kind != "id_only":
        _fail(
            "display_artifact_requires_task18_binding",
            "display artifact requires the Task 18 bound v3 interface",
        )
    intent, _, _ = canonical_unstamped_intent(
        plan.request,
        plan.mutation_plan,
    )
    artifact = {
        "migration_version": 2,
        "migration_kind": plan.migration_kind,
        "rows": [asdict(row) for row in plan.rows],
        "intent": intent,
        "snapshot_id": plan.snapshot_id,
        "snapshot_manifest_sha256": plan.snapshot_manifest_sha256,
    }
    payload = _canonical_json_bytes(artifact)
    return MigrationArtifact(
        manifest=artifact,
        manifest_bytes=payload,
        manifest_sha256=hashlib.sha256(payload).hexdigest(),
    )


def create_display_migration_artifact(
    plan: MigrationPlan,
) -> MigrationArtifact:
    if (
        not isinstance(plan, MigrationPlan)
        or plan.migration_kind != "display_only"
        or not isinstance(plan.binding_path, Path)
        or not isinstance(plan.binding_sha256, str)
        or not isinstance(plan.snapshot_id, str)
        or _SNAPSHOT_ID.fullmatch(plan.snapshot_id) is None
        or not isinstance(plan.snapshot_manifest_sha256, str)
        or _SHA256.fullmatch(plan.snapshot_manifest_sha256) is None
    ):
        _fail(
            "display_plan_unbound",
            "display artifact requires a Task 18 bound plan",
        )
    binding_path = _validate_task18_binding_caller(
        plan.binding_path,
        plan.binding_sha256,
    )
    intent, _, _ = canonical_unstamped_intent(
        plan.request,
        plan.mutation_plan,
    )
    artifact = {
        "migration_version": 3,
        "migration_kind": "display_only",
        "intent": intent,
        "snapshot_id": plan.snapshot_id,
        "snapshot_manifest_sha256": plan.snapshot_manifest_sha256,
        "task18_binding_path": str(binding_path),
        "task18_binding_sha256": plan.binding_sha256,
    }
    payload = _canonical_json_bytes(artifact)
    return MigrationArtifact(
        manifest=artifact,
        manifest_bytes=payload,
        manifest_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _parse_display_artifact(
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
) -> dict:
    if (
        not isinstance(manifest_bytes, bytes)
        or not isinstance(expected_manifest_sha256, str)
        or _SHA256.fullmatch(expected_manifest_sha256) is None
        or hashlib.sha256(manifest_bytes).hexdigest()
        != expected_manifest_sha256
    ):
        _fail(
            "manifest_sha256_mismatch",
            "manifest bytes do not match the trusted receipt",
        )
    try:
        artifact = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail("display_manifest_invalid", str(exc))
    if not isinstance(artifact, dict) or set(artifact) != DISPLAY_ARTIFACT_KEYS:
        _fail(
            "display_manifest_invalid",
            "display migration artifact keys are invalid",
        )
    if (
        artifact["migration_version"] != 3
        or artifact["migration_kind"] != "display_only"
        or not isinstance(artifact["intent"], dict)
        or not isinstance(artifact["snapshot_id"], str)
        or _SNAPSHOT_ID.fullmatch(artifact["snapshot_id"]) is None
        or not isinstance(artifact["snapshot_manifest_sha256"], str)
        or _SHA256.fullmatch(artifact["snapshot_manifest_sha256"]) is None
        or not isinstance(artifact["task18_binding_path"], str)
        or not isinstance(artifact["task18_binding_sha256"], str)
        or _SHA256.fullmatch(artifact["task18_binding_sha256"]) is None
    ):
        _fail(
            "display_manifest_invalid",
            "display migration artifact payload is invalid",
        )
    return artifact


def verify_display_migration_artifact(
    *,
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
    task18_binding_path: Path,
    expected_task18_binding_sha256: str,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
) -> MigrationArtifactVerification:
    artifact = _parse_display_artifact(
        manifest_bytes,
        expected_manifest_sha256,
    )
    binding_path = _validate_task18_binding_caller(
        task18_binding_path,
        expected_task18_binding_sha256,
    )
    if (
        artifact["task18_binding_path"] != str(binding_path)
        or artifact["task18_binding_sha256"]
        != expected_task18_binding_sha256
    ):
        _fail(
            "task18_binding_mismatch",
            "display manifest binding differs from the caller binding",
        )
    binding = verify_task18_binding(
        binding_path=binding_path,
        expected_binding_sha256=expected_task18_binding_sha256,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
    )
    _validate_verified_task18_binding(
        binding,
        binding_path=binding_path,
        binding_sha256=expected_task18_binding_sha256,
    )
    snapshot = _verify_task18_snapshot(binding)
    if (
        artifact["snapshot_id"] != snapshot.snapshot_id
        or artifact["snapshot_manifest_sha256"]
        != snapshot.manifest_sha256
    ):
        _fail(
            "snapshot_binding_mismatch",
            "display manifest snapshot differs from the bound snapshot",
        )
    replanned = _build_bound_display_plan(
        existing=BrainStore.load(brain_root),
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        binding=binding,
        snapshot=snapshot,
    )
    expected = create_display_migration_artifact(replanned)
    if expected.manifest_bytes != manifest_bytes:
        _fail(
            "manifest_revalidation_failed",
            "live replan differs from the supplied display artifact",
        )
    return MigrationArtifactVerification(
        ok=True,
        artifact=artifact,
        plan=replanned,
    )


def apply_display_migration_artifact(
    *,
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
    task18_binding_path: Path,
    expected_task18_binding_sha256: str,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
) -> MigrationApplyResult:
    verified = verify_display_migration_artifact(
        manifest_bytes=manifest_bytes,
        expected_manifest_sha256=expected_manifest_sha256,
        task18_binding_path=task18_binding_path,
        expected_task18_binding_sha256=expected_task18_binding_sha256,
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
    )
    intent = verified.artifact["intent"]
    assert isinstance(intent, dict)
    intent_payload = _canonical_json_bytes(intent)
    result = MutationService().apply_bound_intent(
        request=verified.plan.request,
        artifact_intent=intent,
        expected_intent_sha256=hashlib.sha256(intent_payload).hexdigest(),
    )
    if not result.ok or result.manifest is None:
        _fail(
            result.error_code or "mutation_apply_failed",
            result.detail or "display migration mutation failed",
        )
    return MigrationApplyResult(
        transaction_id=result.manifest.transaction_id,
        action_count=(
            len(result.manifest.creates)
            + len(result.manifest.updates)
            + len(result.manifest.deletes)
            + len(result.manifest.renames)
            + len(result.manifest.auxiliary_updates)
        ),
        snapshot_id=verified.plan.snapshot_id,
    )


def _parse_artifact(
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
) -> dict:
    if (
        not isinstance(expected_manifest_sha256, str)
        or _SHA256.fullmatch(expected_manifest_sha256) is None
        or hashlib.sha256(manifest_bytes).hexdigest()
        != expected_manifest_sha256
    ):
        _fail(
            "manifest_sha256_mismatch",
            "manifest bytes do not match the trusted receipt",
        )
    try:
        artifact = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail("manifest_invalid", str(exc))
    if (
        isinstance(artifact, dict)
        and (
            artifact.get("migration_kind") == "display_only"
            or artifact.get("migration_version") == 3
        )
    ):
        _fail(
            "display_artifact_requires_task18_binding",
            "display artifact requires the Task 18 bound v3 interface",
        )
    expected_keys = {
        "migration_version",
        "migration_kind",
        "rows",
        "intent",
        "snapshot_id",
        "snapshot_manifest_sha256",
    }
    if not isinstance(artifact, dict) or set(artifact) != expected_keys:
        _fail("manifest_invalid", "migration artifact keys are invalid")
    if (
        artifact["migration_version"] != 2
        or artifact["migration_kind"] != "id_only"
        or not isinstance(artifact["rows"], list)
        or not isinstance(artifact["intent"], dict)
    ):
        _fail("manifest_invalid", "migration artifact payload is invalid")
    return artifact


def apply_migration_artifact(
    *,
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
    engine_sha: str,
    snapshot_root: Path,
    expected_snapshot_manifest_sha256: str,
) -> MigrationApplyResult:
    artifact = _parse_artifact(
        manifest_bytes,
        expected_manifest_sha256,
    )
    try:
        snapshot = verify_snapshot(
            snapshot_root,
            expected_manifest_sha256=(
                expected_snapshot_manifest_sha256
            ),
        )
    except SnapshotError as exc:
        _fail(exc.code, exc.detail)
    snapshot_id = snapshot.snapshot_id
    snapshot_manifest_sha256 = snapshot.manifest_sha256
    validate_snapshot_binding(snapshot)
    if (
        artifact["snapshot_id"] != snapshot_id
        or artifact["snapshot_manifest_sha256"]
        != snapshot_manifest_sha256
    ):
        _fail(
            "snapshot_binding_mismatch",
            "apply snapshot differs from the planned trusted snapshot",
        )
    if artifact["intent"].get("engine_sha") != engine_sha:
        _fail("engine_sha_mismatch", "apply engine SHA differs from the plan")
    trusted_migration_context(
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        engine_sha=engine_sha,
        snapshot=snapshot,
    )
    existing = BrainStore.load(brain_root)
    renames: dict[str, str] = {}
    for row in artifact["rows"]:
        if (
            not isinstance(row, dict)
            or set(row) != {field.name for field in fields(MigrationRow)}
            or not isinstance(row.get("old_id"), str)
            or not isinstance(row.get("new_id"), str)
        ):
            _fail("manifest_invalid", "migration row is invalid")
        renames[row["old_id"]] = row["new_id"]
    replanned = plan_id_migration(
        existing=existing,
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        engine_sha=engine_sha,
        renames=renames,
        snapshot=snapshot,
    )
    expected = create_migration_artifact(replanned)
    if expected.manifest_bytes != manifest_bytes:
        _fail(
            "manifest_revalidation_failed",
            "live replan differs from the supplied migration artifact",
        )
    intent_payload = _canonical_json_bytes(artifact["intent"])
    result = MutationService().apply_bound_intent(
        request=replanned.request,
        artifact_intent=artifact["intent"],
        expected_intent_sha256=hashlib.sha256(intent_payload).hexdigest(),
    )
    if not result.ok or result.manifest is None:
        _fail(
            result.error_code or "mutation_apply_failed",
            result.detail or "migration mutation failed",
        )
    return MigrationApplyResult(
        transaction_id=result.manifest.transaction_id,
        action_count=(
            len(result.manifest.creates)
            + len(result.manifest.updates)
            + len(result.manifest.deletes)
            + len(result.manifest.renames)
            + len(result.manifest.auxiliary_updates)
        ),
        snapshot_id=snapshot_id,
    )
