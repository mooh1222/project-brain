"""Context 단위의 완전한 desired-state diff를 shared mutation으로 계획한다."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from project_brain.mutation import (
    MutationManifest,
    MutationOperation,
    MutationRequest,
    MutationService,
    corpus_fingerprint,
)
from project_brain.reference_fields import iter_object_refs, rewrite_object_refs
from project_brain.repo_context import RepoContext
from project_brain.store import BrainStore


@dataclass(frozen=True)
class ContextReplaceError(RuntimeError):
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


@dataclass(frozen=True)
class ContextReplaceArtifact:
    manifest: dict
    manifest_bytes: bytes
    manifest_sha256: str


@dataclass(frozen=True)
class ContextReplaceApplyResult:
    transaction_id: str
    action_count: int


def _fail(code: str, detail: str) -> None:
    raise ContextReplaceError(code, detail)


def _object_hash(obj: Mapping[str, object]) -> str:
    return hashlib.sha256(BrainStore.object_bytes(obj)).hexdigest()


def _belongs_to_context(obj: Mapping[str, object], context_id: str) -> bool:
    return obj.get("id") == context_id or obj.get("context_id") == context_id


def _context_closure(
    objects: Mapping[str, dict],
    context_id: str,
) -> set[str]:
    """Direct context members plus their forward registered references."""
    owned = {
        object_id
        for object_id, obj in objects.items()
        if _belongs_to_context(obj, context_id)
    }
    pending = list(sorted(owned))
    while pending:
        object_id = pending.pop()
        for ref in iter_object_refs(objects[object_id]):
            if ref.object_id not in objects or ref.object_id in owned:
                continue
            owned.add(ref.object_id)
            pending.append(ref.object_id)
    return owned


def _validate_string_mapping(
    value: Mapping[str, str],
    *,
    name: str,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or not all(
        isinstance(old_id, str)
        and bool(old_id)
        and isinstance(new_id, str)
        and bool(new_id)
        for old_id, new_id in value.items()
    ):
        _fail("request_invalid", f"{name} must be Mapping[str, str]")
    return dict(sorted(value.items()))


def plan_context_replace(
    *,
    context_id: str,
    existing: BrainStore,
    brain_root: Path,
    repo_context: RepoContext | None,
    engine_sha: str,
    desired_objects: Sequence[dict],
    expected_drop_ids: Collection[str],
    expected_moves: Mapping[str, str],
    external_reference_rewrites: Mapping[str, str],
) -> MutationRequest:
    """Return one complete, fingerprint-bound context replacement request."""
    if not isinstance(context_id, str) or not context_id:
        _fail("request_invalid", "context_id must be a non-empty string")
    if not isinstance(existing, BrainStore):
        _fail("request_invalid", "existing must be BrainStore")
    if not isinstance(brain_root, Path) or not brain_root.is_absolute():
        _fail("request_invalid", "brain_root must be an absolute Path")
    if (
        not isinstance(desired_objects, Sequence)
        or isinstance(desired_objects, (str, bytes, bytearray))
        or not all(isinstance(obj, dict) for obj in desired_objects)
    ):
        _fail("request_invalid", "desired_objects must be Sequence[dict]")
    desired = tuple(dict(obj) for obj in desired_objects)
    desired_ids = [obj.get("id") for obj in desired]
    if not all(isinstance(object_id, str) and object_id for object_id in desired_ids):
        _fail("desired_id_invalid", "every desired object needs a non-empty string id")
    if len(set(desired_ids)) != len(desired_ids):
        _fail("desired_id_duplicate", "desired_objects contains a duplicate id")
    desired_by_id = {str(obj["id"]): obj for obj in desired}
    desired_context_ids = _context_closure(desired_by_id, context_id)
    wrong_context = sorted(set(desired_by_id) - desired_context_ids)
    if wrong_context:
        _fail(
            "desired_context_mismatch",
            "desired objects outside the requested context: "
            + ", ".join(sorted(wrong_context)),
        )

    existing_objects = {obj["id"]: obj for obj in existing.all()}
    current_context_ids = _context_closure(existing_objects, context_id)
    current_context = {
        object_id: existing_objects[object_id]
        for object_id in current_context_ids
    }
    if context_id not in current_context and context_id not in set(desired_ids):
        _fail("context_missing", f"context object is missing: {context_id}")
    removed_ids = set(current_context) - set(desired_by_id)
    created_ids = set(desired_by_id) - set(current_context)

    if (
        not isinstance(expected_drop_ids, Collection)
        or isinstance(expected_drop_ids, (str, bytes, bytearray))
        or not all(isinstance(object_id, str) for object_id in expected_drop_ids)
    ):
        _fail("request_invalid", "expected_drop_ids must be a string collection")
    drop_ids = set(expected_drop_ids)
    if len(drop_ids) != len(tuple(expected_drop_ids)):
        _fail("drop_id_duplicate", "expected_drop_ids contains a duplicate id")
    moves = _validate_string_mapping(expected_moves, name="expected_moves")
    if len(set(moves.values())) != len(moves):
        _fail("move_target_duplicate", "expected_moves contains a duplicate target")
    overlap = drop_ids & set(moves)
    if overlap:
        _fail(
            "move_drop_overlap",
            "IDs cannot be both drops and move sources: "
            + ", ".join(sorted(overlap)),
        )
    if set(moves) - removed_ids:
        _fail(
            "move_source_mismatch",
            "move sources are not removed desired-state IDs: "
            + ", ".join(sorted(set(moves) - removed_ids)),
        )
    if set(moves.values()) - created_ids:
        _fail(
            "move_target_mismatch",
            "move targets are not newly created desired-state IDs: "
            + ", ".join(sorted(set(moves.values()) - created_ids)),
        )
    actual_drops = removed_ids - set(moves)
    if drop_ids != actual_drops:
        _fail(
            "drop_set_mismatch",
            "expected_drop_ids must exactly match removed non-move IDs",
        )

    external_rewrites = _validate_string_mapping(
        external_reference_rewrites,
        name="external_reference_rewrites",
    )
    external_objects = {
        object_id: obj
        for object_id, obj in existing_objects.items()
        if object_id not in current_context
    }
    externally_referenced_removed: set[str] = set()
    for obj in external_objects.values():
        externally_referenced_removed.update(
            ref.object_id
            for ref in iter_object_refs(obj)
            if ref.object_id in removed_ids
        )
    missing_rewrites = externally_referenced_removed - set(external_rewrites)
    extra_rewrites = set(external_rewrites) - externally_referenced_removed
    if missing_rewrites:
        _fail(
            "external_reference_rewrite_required",
            "external references remain for deleted IDs: "
            + ", ".join(sorted(missing_rewrites)),
        )
    if extra_rewrites:
        _fail(
            "external_reference_rewrite_unmatched",
            "declared external rewrites have no matching backreference: "
            + ", ".join(sorted(extra_rewrites)),
        )
    surviving_ids = (
        (set(existing_objects) - removed_ids)
        | set(desired_by_id)
    )
    invalid_targets = set(external_rewrites.values()) - surviving_ids
    if invalid_targets:
        _fail(
            "external_reference_target_missing",
            "external rewrite targets will not exist: "
            + ", ".join(sorted(invalid_targets)),
        )

    rewritten_external: list[dict] = []
    for object_id in sorted(external_objects):
        rewritten, changed = rewrite_object_refs(
            external_objects[object_id],
            external_rewrites,
        )
        if changed:
            rewritten_external.append(rewritten)

    request_objects = tuple(
        sorted(
            (*desired, *rewritten_external),
            key=lambda obj: str(obj["id"]),
        )
    )
    precondition_ids = (
        {
            object_id
            for object_id, desired_obj in desired_by_id.items()
            if (
                object_id in current_context
                and current_context[object_id] != desired_obj
            )
        }
        | removed_ids
        | {obj["id"] for obj in rewritten_external}
    )
    preconditions = {
        object_id: _object_hash(existing_objects[object_id])
        for object_id in sorted(precondition_ids)
    }
    return MutationRequest(
        operation=MutationOperation.CONTEXT_REPLACE,
        brain_root=brain_root,
        repo_context=repo_context,
        engine_sha=engine_sha,
        objects=request_objects,
        delete_ids=tuple(sorted(removed_ids)),
        renames=moves,
        preconditions=preconditions,
        expected_corpus_fingerprint=corpus_fingerprint(existing),
    )


def _repo_context_payload(repo_context: RepoContext | None) -> dict | None:
    if repo_context is None:
        return None
    return {
        "repo_root": str(repo_context.repo_root),
        "expected_repo_id": repo_context.expected_repo_id,
        "expected_revision_ref": repo_context.expected_revision_ref,
        "target_revision_sha": repo_context.target_revision_sha,
    }


def create_context_replace_artifact(
    request: MutationRequest,
) -> ContextReplaceArtifact:
    """Run pure mutation preflight and serialize its exact apply payload."""
    if (
        not isinstance(request, MutationRequest)
        or request.operation is not MutationOperation.CONTEXT_REPLACE
    ):
        _fail("request_invalid", "context replace request is required")
    planned = MutationService().plan(request.objects, request=request)
    if not planned.ok or planned.manifest is None:
        _fail(
            planned.error_code or "mutation_plan_failed",
            planned.detail or "context replace mutation preflight failed",
        )
    artifact = {
        **asdict(planned.manifest),
        "context_replace_version": 1,
        "objects": list(planned.after_objects),
        "repo_context": _repo_context_payload(request.repo_context),
    }
    payload = (
        json.dumps(
            artifact,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return ContextReplaceArtifact(
        manifest=artifact,
        manifest_bytes=payload,
        manifest_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _parse_artifact(
    manifest_bytes: bytes,
    *,
    expected_manifest_sha256: str,
) -> tuple[dict, dict]:
    actual_sha = hashlib.sha256(manifest_bytes).hexdigest()
    if actual_sha != expected_manifest_sha256:
        _fail(
            "manifest_sha256_mismatch",
            "manifest bytes do not match --expected-manifest-sha256",
        )
    try:
        artifact = json.loads(manifest_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        _fail("manifest_invalid", str(exc))
    core_keys = {field.name for field in fields(MutationManifest)}
    expected_keys = core_keys | {
        "context_replace_version",
        "objects",
        "repo_context",
    }
    if not isinstance(artifact, dict) or set(artifact) != expected_keys:
        _fail("manifest_invalid", "context replace manifest keys are invalid")
    if (
        artifact["context_replace_version"] != 1
        or artifact["operation"] != MutationOperation.CONTEXT_REPLACE.value
        or not isinstance(artifact["objects"], list)
        or not all(isinstance(obj, dict) for obj in artifact["objects"])
    ):
        _fail("manifest_invalid", "context replace manifest payload is invalid")
    return artifact, {
        key: artifact[key]
        for key in core_keys
    }


def _verify_repo_context(
    expected: object,
    actual: RepoContext | None,
) -> None:
    actual_payload = _repo_context_payload(actual)
    if expected != actual_payload:
        _fail(
            "repo_context_mismatch",
            "apply repository context differs from the planned context",
        )


def apply_context_replace_artifact(
    *,
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
    brain_root: Path,
    repo_context: RepoContext | None,
    engine_sha: str,
) -> ContextReplaceApplyResult:
    """Apply only the exact planned bytes through journaled corpus I/O."""
    from project_brain.corpus_io import (
        CorpusIOError,
        apply_transaction,
        corpus_lock,
        recover_unfinished_transaction_unlocked,
    )

    artifact, core = _parse_artifact(
        manifest_bytes,
        expected_manifest_sha256=expected_manifest_sha256,
    )
    if artifact["engine_sha"] != engine_sha:
        _fail(
            "engine_sha_mismatch",
            "apply engine SHA differs from the planned engine SHA",
        )
    _verify_repo_context(artifact["repo_context"], repo_context)
    object_by_id: dict[str, dict] = {}
    for obj in artifact["objects"]:
        object_id = obj.get("id")
        if not isinstance(object_id, str) or object_id in object_by_id:
            _fail("manifest_invalid", "manifest object IDs are invalid or duplicated")
        object_by_id[object_id] = obj

    writable: list[tuple[str, str, str]] = []
    for field_name in ("creates", "updates"):
        actions = artifact.get(field_name)
        if not isinstance(actions, list):
            _fail("manifest_invalid", f"{field_name} must be a list")
        writable.extend(
            (
                str(action.get("object_id")),
                str(action.get("path")),
                str(action.get("after_sha256")),
            )
            for action in actions
            if isinstance(action, dict)
        )
    renames = artifact.get("renames")
    if not isinstance(renames, list):
        _fail("manifest_invalid", "renames must be a list")
    writable.extend(
        (
            str(action.get("new_id")),
            str(action.get("new_path")),
            str(action.get("after_sha256")),
        )
        for action in renames
        if isinstance(action, dict)
    )
    after_files: dict[str, bytes] = {}
    for object_id, relative_path, expected_sha in writable:
        obj = object_by_id.get(object_id)
        if obj is None:
            _fail("manifest_invalid", f"missing after object: {object_id}")
        expected_path = (
            BrainStore.object_path(brain_root, obj)
            .relative_to(brain_root)
            .as_posix()
        )
        payload = BrainStore.object_bytes(obj)
        if (
            expected_path != relative_path
            or hashlib.sha256(payload).hexdigest() != expected_sha
        ):
            _fail(
                "manifest_invalid",
                f"after payload does not match action: {object_id}",
            )
        after_files[relative_path] = payload

    with corpus_lock(brain_root, exclusive=True):
        recover_unfinished_transaction_unlocked(brain_root)
        current = BrainStore.load_unlocked(brain_root)
        if corpus_fingerprint(current) != artifact["before_fingerprint"]:
            _fail(
                "corpus_fingerprint_mismatch",
                "live corpus differs from the planned before fingerprint",
            )
        try:
            apply_transaction(
                brain_root,
                manifest=core,
                after_files=after_files,
            )
        except (CorpusIOError, ValueError, OSError) as exc:
            _fail("mutation_apply_failed", str(exc))
    return ContextReplaceApplyResult(
        transaction_id=str(artifact["transaction_id"]),
        action_count=(
            len(artifact["creates"])
            + len(artifact["updates"])
            + len(artifact["deletes"])
            + len(artifact["renames"])
        ),
    )
