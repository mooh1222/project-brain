"""Brain 객체 mutation의 순수 preflight와 고정 manifest."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath

from project_brain.code_verify import (
    CodeVerificationError,
    verify_locator_for_write,
)
from project_brain.corpus_io import (
    CorpusIOError,
    apply_transaction,
    corpus_lock,
    read_tracked_file_bytes,
    recover_unfinished_transaction_unlocked,
)
from project_brain.hash_utils import stable_json
from project_brain.id_grammar import IdGrammarError, parse_id
from project_brain.lint import LintProblem, lint_store_report
from project_brain.objbase import now_kst
from project_brain.reference_fields import iter_object_refs, rewrite_object_refs
from project_brain.repo_context import RepoContext
from project_brain.schema import (
    id_problem_code,
    validate_mutation_input_schema,
    validate_object_id,
)
from project_brain.store import BrainStore, StoreLoadError
from project_brain.transaction_receipt import (
    BatchBinding,
    batch_binding_dict,
    normalize_batch_binding,
)


_COORDINATE_FIELDS = (
    "repo",
    "path",
    "commit_sha",
    "symbol",
    "verified_quote",
)
_EXACT_GIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOGICAL_KEY_FIELDS = (
    "logical_key",
    "mapping_key",
    "context_key",
)
_STRUCTURED_ID_LINT_CODES = frozenset({"invalid_id", "unknown_grammar"})


class MutationOperation(StrEnum):
    INGEST = "ingest"
    PROMOTE = "promote"
    PROMOTE_AUTO = "promote_auto"
    MARK_CHECKED = "mark_checked"
    PROJECTION = "projection"
    PROJECTION_REPAIR = "projection_repair"
    CONTEXT_REPLACE = "context_replace"
    ID_ONLY_MIGRATION = "id_only_migration"
    DISPLAY_MIGRATION = "display_migration"


@dataclass(frozen=True)
class AuxiliaryFileUpdate:
    path: str
    before_sha256: str
    after_sha256: str
    after_bytes: bytes = field(repr=False)


@dataclass(frozen=True)
class MutationRequest:
    operation: MutationOperation
    brain_root: Path
    repo_context: RepoContext | None
    engine_sha: str
    objects: tuple[dict, ...]
    delete_ids: tuple[str, ...] = ()
    renames: Mapping[str, str] = field(default_factory=dict)
    preconditions: Mapping[str, str] = field(default_factory=dict)
    expected_corpus_fingerprint: str | None = None
    auxiliary_updates: tuple[AuxiliaryFileUpdate, ...] = ()
    batch_binding: BatchBinding | None = None


@dataclass(frozen=True)
class MutationManifest:
    transaction_id: str
    operation: str
    engine_sha: str
    creates: tuple[dict, ...]
    updates: tuple[dict, ...]
    deletes: tuple[dict, ...]
    renames: tuple[dict, ...]
    reference_rewrites: tuple[dict, ...]
    auxiliary_updates: tuple[dict, ...]
    before_fingerprint: str
    expected_after_fingerprint: str
    grandfathered_problems_before: tuple[dict, ...]
    grandfathered_problems_after: tuple[dict, ...]
    batch_binding: dict[str, object] | None


@dataclass(frozen=True)
class MutationPlanResult:
    ok: bool
    error_code: str | None = None
    detail: str | None = None
    after: dict | None = None
    after_objects: tuple[dict, ...] = ()
    manifest: MutationManifest | None = None
    manifest_bytes: bytes = b""
    manifest_sha256: str = ""
    auxiliary_after_files: Mapping[str, bytes] = field(default_factory=dict)


class MutationService:
    def apply(
        self,
        objects: Sequence[dict],
        *,
        request: MutationRequest,
        failure_injector: Callable[[str], None] | None = None,
    ) -> MutationPlanResult:
        inputs, request_error = _validate_request_shape(objects, request)
        if request_error is not None:
            return request_error
        assert inputs is not None

        with corpus_lock(request.brain_root, exclusive=True):
            recover_unfinished_transaction_unlocked(request.brain_root)
            try:
                existing_store = BrainStore.load_unlocked(request.brain_root)
            except StoreLoadError as exc:
                if isinstance(exc.__cause__, CorpusIOError):
                    raise exc.__cause__
                return _store_load_failure(exc)
            result = self.plan(
                inputs,
                request=request,
                _existing_store=existing_store,
            )
            if not result.ok or result.manifest is None:
                return result
            writable_actions = (
                result.manifest.creates + result.manifest.updates
            )
            actions = (
                writable_actions
                + result.manifest.deletes
                + result.manifest.renames
                + result.manifest.auxiliary_updates
            )
            if not actions:
                return result
            after_paths = {
                str(action["path"])
                for action in writable_actions
            }
            after_paths.update(
                str(action["new_path"])
                for action in result.manifest.renames
            )
            after_files = {
                relative_path: BrainStore.object_bytes(obj)
                for obj in result.after_objects
                if (
                    relative_path := BrainStore.object_path(
                        request.brain_root,
                        obj,
                    ).relative_to(request.brain_root).as_posix()
                ) in after_paths
            }
            after_files.update(result.auxiliary_after_files)
            apply_transaction(
                request.brain_root,
                manifest=asdict(result.manifest),
                after_files=after_files,
                failure_injector=failure_injector,
            )
            return result

    def plan(
        self,
        objects: Sequence[dict],
        *,
        request: MutationRequest,
        _existing_store: BrainStore | None = None,
    ) -> MutationPlanResult:
        inputs, request_error = _validate_request_shape(objects, request)
        if request_error is not None:
            return request_error
        assert inputs is not None

        # 1) sequence에서 완성 object ID 중복 검사. dict로 접기 전에 수행한다.
        seen_ids: set[object] = set()
        for obj in inputs:
            object_id = obj.get("id")
            if not isinstance(object_id, str):
                continue
            if object_id in seen_ids:
                return _failure(
                    "duplicate_object_id",
                    f"duplicate object id in input sequence: {object_id!r}",
                )
            seen_ids.add(object_id)

        # 2) 입력 logical key와 source ID 중복 검사.
        duplicate = _find_duplicate_identity(inputs, _LOGICAL_KEY_FIELDS)
        if duplicate is not None:
            field_name, value = duplicate
            return _failure(
                "duplicate_logical_key",
                f"duplicate {field_name} in input sequence: {value!r}",
            )
        duplicate = _find_duplicate_source_id(inputs)
        if duplicate is not None:
            _, value = duplicate
            return _failure(
                "duplicate_source_id",
                f"duplicate source_id in input sequence: {value!r}",
            )
        # delete_ids 중복은 store 상태가 아니라 request sequence 자체의 모순이므로
        # schema·lifecycle보다 앞선 입력 shape 단계에서 닫는다.
        delete_ids = tuple(request.delete_ids)
        if len(set(delete_ids)) != len(delete_ids):
            return _failure(
                "duplicate_delete_id",
                "delete_ids contains a duplicate object id",
            )

        # 이 시점 이후에만 ID map을 만든다.
        input_by_id = {
            obj["id"]: obj
            for obj in inputs
            if isinstance(obj.get("id"), str)
        }
        if _existing_store is None:
            try:
                existing_store = BrainStore.load(request.brain_root)
            except StoreLoadError as exc:
                return _store_load_failure(exc)
        else:
            existing_store = _existing_store
        existing_by_id = {obj["id"]: obj for obj in existing_store.all()}

        auxiliary_error = _validate_auxiliary_updates(request)
        if auxiliary_error is not None:
            return auxiliary_error

        # 3) schema와 enum.
        for obj in inputs:
            errors = validate_mutation_input_schema(obj)
            if errors:
                return _failure("schema_invalid", "; ".join(errors))

        # 4) ID parse와 필드 합치. 구조화된 ID 문제는 merged lint에서 기존 문제·객체
        # hash까지 묶어 grandfather 여부를 판단한다.
        for obj in inputs:
            id_errors = validate_object_id(obj)
            if (
                id_errors
                and id_problem_code(obj) in _STRUCTURED_ID_LINT_CODES
            ):
                object_id = obj.get("id")
                previous = (
                    existing_by_id.get(object_id)
                    if isinstance(object_id, str)
                    else None
                )
                if (
                    previous is None
                    or _stable_object_hash(previous) != _stable_object_hash(obj)
                    or validate_object_id(previous) != id_errors
                ):
                    return _failure(
                        "new_or_modified_lint_problem",
                        "; ".join(id_errors),
                    )

        if request.operation is MutationOperation.PROJECTION_REPAIR:
            repair_error = _validate_projection_repair_request(
                request,
                input_by_id=input_by_id,
                existing_by_id=existing_by_id,
            )
            if repair_error is not None:
                return repair_error
        if request.operation in {
            MutationOperation.PROMOTE,
            MutationOperation.PROMOTE_AUTO,
        }:
            promotion_error = _validate_promotion_request(
                request,
                input_by_id=input_by_id,
                existing_by_id=existing_by_id,
            )
            if promotion_error is not None:
                return promotion_error

        # 5) 허용된 상태 전이.
        for object_id, obj in input_by_id.items():
            previous = existing_by_id.get(object_id)
            if (
                previous is not None
                and previous.get("status") == "reviewed"
                and obj.get("status") == "candidate"
            ):
                return _failure(
                    "status_transition_invalid",
                    f"{object_id}: refuse reviewed→candidate demotion",
                )

        # 6-7) repo/commit/blob 뒤 quote와 symbol 관계. 신규 또는 좌표가 바뀐
        # CodeLocator만 검사한다. ID-only legacy rename은 stage 8의 before-state
        # 증거로 예외 여부를 결정하므로 여기서 외부 verified_at을 소비하지 않는다.
        planned_inputs: list[dict] = []
        verified_locator_ids: set[str] = set()
        if request.operation is not MutationOperation.ID_ONLY_MIGRATION:
            for obj in inputs:
                planned = dict(obj)
                if planned.get("kind") == "CodeLocator":
                    object_id = str(planned["id"])
                    previous = existing_by_id.get(object_id)
                    needs_verification = (
                        request.operation is MutationOperation.MARK_CHECKED
                        or previous is None
                        or any(
                            previous.get(field_name) != planned.get(field_name)
                            for field_name in _COORDINATE_FIELDS
                        )
                    )
                    if needs_verification:
                        quote = planned.get("verified_quote")
                        if not isinstance(quote, str) or not quote:
                            return _failure(
                                "quote_required",
                                f"{object_id}: verified_quote is required",
                            )
                        if request.repo_context is None:
                            return _failure(
                                "repo_context_required",
                                f"{object_id}: explicit repo context is required",
                            )
                        try:
                            verified = verify_locator_for_write(
                                planned,
                                repo=request.repo_context,
                                manual_symbol_verification=planned.get(
                                    "manual_symbol_verification"
                                ),
                            )
                        except CodeVerificationError as exc:
                            return _failure(
                                exc.failure.code,
                                exc.failure.detail,
                            )
                        planned = verified.locator
                        verified_locator_ids.add(object_id)
                        planned["title"] = (
                            previous.get("title")
                            if (
                                previous is not None
                                and request.operation
                                is MutationOperation.MARK_CHECKED
                            )
                            else _canonical_locator_title(planned)
                        )
                    elif previous is not None:
                        planned["verified_at"] = previous.get("verified_at")
                        planned["title"] = (
                            _canonical_locator_title(planned)
                            if (
                                request.operation
                                is MutationOperation.DISPLAY_MIGRATION
                            )
                            else previous.get("title")
                        )
                planned_inputs.append(planned)

        if request.operation is MutationOperation.MARK_CHECKED:
            verification_event_at = now_kst()
            for planned in planned_inputs:
                if planned.get("id") not in verified_locator_ids:
                    continue
                planned["verified_at"] = verification_event_at
                planned["updated_at"] = verification_event_at

        # 8) 기존 객체 precondition과 before hash.
        explicit_rename_pairs, explicit_rename_error = (
            _validate_explicit_renames(
                request,
                existing_by_id=existing_by_id,
                input_by_id=input_by_id,
                delete_ids=delete_ids,
            )
        )
        if explicit_rename_error is not None:
            return explicit_rename_error
        for object_id in delete_ids:
            if object_id not in existing_by_id:
                return _failure(
                    "delete_target_missing",
                    f"delete target is missing: {object_id}",
                )
            if object_id in input_by_id:
                return _failure(
                    "delete_update_conflict",
                    f"object cannot be updated and deleted together: {object_id}",
                )
        rename_pairs, rename_error = (
            _infer_id_only_renames(
                request.operation,
                existing_by_id,
                input_by_id,
                delete_ids,
            )
            if request.operation is MutationOperation.ID_ONLY_MIGRATION
            else (explicit_rename_pairs, None)
        )
        if rename_error is not None:
            return rename_error
        if request.operation is MutationOperation.ID_ONLY_MIGRATION:
            planned_inputs = [dict(obj) for obj in inputs]
        planned_by_id = {obj["id"]: obj for obj in planned_inputs}

        before_fingerprint = _corpus_fingerprint(existing_by_id)
        if (
            request.expected_corpus_fingerprint is not None
            and request.expected_corpus_fingerprint != before_fingerprint
        ):
            return _failure(
                "corpus_fingerprint_mismatch",
                "expected corpus fingerprint does not match the current store",
            )
        for object_id, expected_hash in sorted(request.preconditions.items()):
            previous = existing_by_id.get(object_id)
            if previous is None:
                return _failure(
                    "precondition_target_missing",
                    f"{object_id}: precondition target is missing",
                )
            actual_hash = _object_hash(previous)
            if actual_hash != expected_hash:
                return _failure(
                    "precondition_hash_mismatch",
                    (
                        f"{object_id}: precondition hash {expected_hash!r} "
                        f"does not match {actual_hash!r}"
                    ),
                )

        merged = dict(existing_by_id)
        for object_id in delete_ids:
            merged.pop(object_id)
        merged.update(planned_by_id)
        merged_store = BrainStore(merged)

        # 9) 입력과 기존 store를 합친 상태의 모든 참조.
        for obj in merged_store.all():
            for ref in iter_object_refs(obj):
                if not merged_store.has(ref.object_id):
                    return _failure(
                        "dangling_reference",
                        (
                            f"{obj.get('id', '?')}: dangling reference "
                            f"{ref.object_id} at {ref.pointer}"
                        ),
                    )

        # 10) merged lint. grandfather는 기존 invalid_id의 문제·객체 hash가
        # 모두 같은 경우만 허용한다.
        before_report = lint_store_report(existing_store)
        if request.operation is MutationOperation.PROJECTION_REPAIR:
            before_non_id = tuple(
                problem
                for problem in before_report
                if problem.code not in _STRUCTURED_ID_LINT_CODES
            )
            disallowed_before = tuple(
                problem
                for problem in before_non_id
                if problem.code != "projection_source_hash_mismatch"
            )
            if disallowed_before:
                return _failure(
                    "existing_lint_problem",
                    disallowed_before[0].message,
                )
            mismatch_ids = {
                object_id
                for problem in before_non_id
                for object_id in problem.object_ids
            }
            if mismatch_ids != set(input_by_id):
                return _failure(
                    "projection_repair_incomplete",
                    (
                        "projection repair targets must exactly match all "
                        "existing projection_source_hash_mismatch objects"
                    ),
                )
        else:
            for problem in before_report:
                if problem.code not in _STRUCTURED_ID_LINT_CODES:
                    return _failure(
                        "existing_lint_problem",
                        problem.message,
                    )

        before_grandfathered = _grandfathered_problems(
            before_report,
            existing_by_id,
        )
        before_keys = {_grandfather_key(item) for item in before_grandfathered}
        after_report = lint_store_report(merged_store)
        after_grandfathered = _grandfathered_problems(after_report, merged)
        after_keys = {_grandfather_key(item) for item in after_grandfathered}
        non_id_after = [
            problem
            for problem in after_report
            if problem.code not in _STRUCTURED_ID_LINT_CODES
        ]
        if (
            request.operation is MutationOperation.PROJECTION_REPAIR
            and non_id_after
        ):
            return _failure(
                "projection_repair_incomplete",
                non_id_after[0].message,
            )
        if non_id_after or not after_keys.issubset(before_keys):
            problem = non_id_after[0] if non_id_after else next(
                problem
                for problem in after_report
                if _grandfather_key(
                    _grandfathered_problem(problem, merged)
                ) not in before_keys
            )
            return _failure(
                "new_or_modified_lint_problem",
                problem.message,
            )
        if (
            request.operation is MutationOperation.ID_ONLY_MIGRATION
            and after_grandfathered
        ):
            return _failure(
                "grandfathered_problems_remaining",
                "ID-only migration must finish with zero grandfathered problems",
            )

        expected_after_fingerprint = _corpus_fingerprint(merged)
        required_source_receipt_ids = _required_source_receipt_ids(
            existing_by_id=existing_by_id,
            planned_by_id=planned_by_id,
            delete_ids=delete_ids,
            rename_pairs=rename_pairs,
        )
        source_sha256_by_id: dict[str, str] = {}
        for object_id in required_source_receipt_ids:
            source_sha256 = existing_store.source_sha256(object_id)
            if source_sha256 is None:
                return _failure(
                    "source_receipt_missing",
                    f"{object_id}: loaded source receipt is missing",
                )
            if (
                not isinstance(source_sha256, str)
                or _SHA256.fullmatch(source_sha256) is None
            ):
                return _failure(
                    "source_receipt_invalid",
                    f"{object_id}: loaded source receipt is invalid",
                )
            source_sha256_by_id[object_id] = source_sha256
        manifest = _build_manifest(
            request=request,
            existing_by_id=existing_by_id,
            planned_by_id=planned_by_id,
            merged=merged,
            delete_ids=delete_ids,
            rename_pairs=rename_pairs,
            source_sha256_by_id=source_sha256_by_id,
            before_fingerprint=before_fingerprint,
            expected_after_fingerprint=expected_after_fingerprint,
            before_grandfathered=before_grandfathered,
            after_grandfathered=after_grandfathered,
        )
        manifest_bytes = _manifest_bytes(manifest)
        after = planned_inputs[0] if len(planned_inputs) == 1 else None
        return MutationPlanResult(
            ok=True,
            after=after,
            after_objects=tuple(planned_inputs),
            manifest=manifest,
            manifest_bytes=manifest_bytes,
            manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            auxiliary_after_files={
                update.path: update.after_bytes
                for update in request.auxiliary_updates
            },
        )


def _failure(code: str, detail: str) -> MutationPlanResult:
    return MutationPlanResult(ok=False, error_code=code, detail=detail)


def _validate_auxiliary_updates(
    request: MutationRequest,
) -> MutationPlanResult | None:
    updates = request.auxiliary_updates
    if not updates:
        return None
    if request.operation is not MutationOperation.ID_ONLY_MIGRATION:
        return _failure(
            "auxiliary_update_operation_invalid",
            "auxiliary updates are allowed only for ID-only migration",
        )
    seen: set[str] = set()
    for update in updates:
        if update.path in seen:
            return _failure(
                "duplicate_auxiliary_update",
                f"duplicate auxiliary update path: {update.path}",
            )
        seen.add(update.path)
        if update.path != "eval_scenarios.json":
            return _failure(
                "auxiliary_update_path_invalid",
                "only eval_scenarios.json may be updated",
            )
        if (
            _SHA256.fullmatch(update.before_sha256) is None
            or _SHA256.fullmatch(update.after_sha256) is None
        ):
            return _failure(
                "auxiliary_update_hash_invalid",
                f"{update.path}: auxiliary hashes must be lowercase SHA-256",
            )
        if update.before_sha256 == update.after_sha256:
            return _failure(
                "auxiliary_update_noop",
                f"{update.path}: auxiliary update must change content",
            )
        if (
            hashlib.sha256(update.after_bytes).hexdigest()
            != update.after_sha256
        ):
            return _failure(
                "auxiliary_after_hash_mismatch",
                f"{update.path}: after bytes do not match after_sha256",
            )
        try:
            before_bytes = read_tracked_file_bytes(
                request.brain_root,
                update.path,
            )
        except CorpusIOError as exc:
            return _failure(
                "auxiliary_update_missing"
                if exc.code == "tracked_file_missing"
                else exc.code,
                exc.detail,
            )
        if hashlib.sha256(before_bytes).hexdigest() != update.before_sha256:
            return _failure(
                "auxiliary_before_hash_mismatch",
                f"{update.path}: current bytes do not match before_sha256",
            )
    return None


def _validate_projection_repair_request(
    request: MutationRequest,
    *,
    input_by_id: Mapping[str, dict],
    existing_by_id: Mapping[str, dict],
) -> MutationPlanResult | None:
    if request.delete_ids:
        return _failure(
            "projection_repair_delete_forbidden",
            "projection repair does not allow deletes",
        )
    input_ids = set(input_by_id)
    if set(request.preconditions) != input_ids:
        return _failure(
            "projection_repair_precondition_set_mismatch",
            "projection repair target IDs and precondition IDs must exactly match",
        )
    for object_id, replacement in input_by_id.items():
        previous = existing_by_id.get(object_id)
        if previous is None:
            return _failure(
                "projection_repair_create_forbidden",
                f"projection repair target does not exist: {object_id}",
            )
        if (
            previous.get("kind") != "ContextProjection"
            or replacement.get("kind") != "ContextProjection"
        ):
            return _failure(
                "projection_repair_kind_invalid",
                f"projection repair target must be ContextProjection: {object_id}",
            )
        changed_fields = {
            field_name
            for field_name in set(previous) | set(replacement)
            if (
                field_name not in previous
                or field_name not in replacement
                or previous.get(field_name) != replacement.get(field_name)
            )
        }
        if not changed_fields.issubset({"source_content_hash"}):
            return _failure(
                "projection_repair_field_invalid",
                (
                    f"{object_id}: projection repair may only change "
                    f"source_content_hash, got {sorted(changed_fields)!r}"
                ),
            )
    return None


def _validate_promotion_request(
    request: MutationRequest,
    *,
    input_by_id: Mapping[str, dict],
    existing_by_id: Mapping[str, dict],
) -> MutationPlanResult | None:
    review_records = tuple(
        obj
        for obj in input_by_id.values()
        if obj.get("kind") == "ReviewRecord"
    )
    target_ids: set[str] = set()
    for record in review_records:
        target_id = record.get("target_object_id")
        if isinstance(target_id, str):
            target_ids.add(target_id)
        target_object_ids = record.get("target_object_ids")
        if isinstance(target_object_ids, list):
            target_ids.update(
                object_id
                for object_id in target_object_ids
                if isinstance(object_id, str)
            )
    replacement_target_ids = {
        object_id
        for object_id, obj in input_by_id.items()
        if obj.get("kind") != "ReviewRecord"
    }
    if not target_ids or target_ids != replacement_target_ids:
        return _failure(
            "promotion_target_set_mismatch",
            "promotion ReviewRecord targets must exactly match replacement targets",
        )
    if set(request.preconditions) != target_ids:
        return _failure(
            "promotion_precondition_set_mismatch",
            "promotion target IDs and precondition IDs must exactly match",
        )
    if request.expected_corpus_fingerprint is None:
        return _failure(
            "promotion_corpus_fingerprint_required",
            "promotion requires the exact selection corpus fingerprint",
        )
    for target_id in sorted(target_ids):
        previous = existing_by_id.get(target_id)
        if previous is None:
            return _failure(
                "promotion_target_missing",
                f"promotion target is missing: {target_id}",
            )
        if previous.get("status") != "candidate":
            return _failure(
                "promotion_target_not_candidate",
                (
                    f"{target_id}: promotion requires current candidate status, "
                    f"got {previous.get('status')!r}"
                ),
            )
        if input_by_id[target_id].get("status") != "reviewed":
            return _failure(
                "promotion_result_not_reviewed",
                f"{target_id}: promotion replacement must be reviewed",
            )
    for record in review_records:
        if record["id"] in existing_by_id:
            return _failure(
                "promotion_review_record_exists",
                f"promotion ReviewRecord already exists: {record['id']}",
            )
    return None


def _store_load_failure(exc: StoreLoadError) -> MutationPlanResult:
    error_code = (
        exc.code
        if exc.code == "duplicate_existing_object_id"
        else "corpus_invalid"
    )
    return _failure(error_code, f"{exc.code}: {exc.detail}")


def _validate_request_shape(
    objects: object,
    request: object,
) -> tuple[tuple[dict, ...] | None, MutationPlanResult | None]:
    """Filesystem 접근 전에 public request/input runtime shape를 전수 검증한다."""
    try:
        if not isinstance(request, MutationRequest):
            raise ValueError("request must be MutationRequest")
        if not isinstance(request.operation, MutationOperation):
            raise ValueError("operation must be MutationOperation")
        if not isinstance(request.brain_root, Path):
            raise ValueError("brain_root must be Path")
        if not request.brain_root.is_absolute():
            raise ValueError("brain_root must be absolute")
        if request.repo_context is not None and not isinstance(
            request.repo_context,
            RepoContext,
        ):
            raise ValueError("repo_context must be RepoContext or None")
        if (
            not isinstance(request.engine_sha, str)
            or _EXACT_GIT_SHA.fullmatch(request.engine_sha) is None
        ):
            raise ValueError("engine_sha must be an exact lowercase Git SHA")
        if not isinstance(request.objects, tuple) or not all(
            isinstance(obj, dict)
            for obj in request.objects
        ):
            raise ValueError("request.objects must be tuple[dict, ...]")
        if (
            not isinstance(objects, Sequence)
            or isinstance(objects, (str, bytes, bytearray))
        ):
            raise ValueError("objects must be a non-string Sequence")
        raw_inputs = tuple(objects)
        if not all(isinstance(obj, dict) for obj in raw_inputs):
            raise ValueError("objects entries must be dict")
        if raw_inputs != request.objects:
            raise ValueError(
                "objects must exactly match request.objects in sequence order"
            )
        if not isinstance(request.delete_ids, tuple) or not all(
            isinstance(object_id, str)
            for object_id in request.delete_ids
        ):
            raise ValueError("delete_ids must be tuple[str, ...]")
        if not isinstance(request.renames, Mapping) or not all(
            isinstance(old_id, str) and isinstance(new_id, str)
            for old_id, new_id in request.renames.items()
        ):
            raise ValueError("renames must be Mapping[str, str]")
        if not isinstance(request.preconditions, Mapping) or not all(
            isinstance(object_id, str) and isinstance(expected_hash, str)
            for object_id, expected_hash in request.preconditions.items()
        ):
            raise ValueError("preconditions must be Mapping[str, str]")
        if (
            not isinstance(request.auxiliary_updates, tuple)
            or not all(
                isinstance(update, AuxiliaryFileUpdate)
                and isinstance(update.path, str)
                and isinstance(update.before_sha256, str)
                and isinstance(update.after_sha256, str)
                and isinstance(update.after_bytes, bytes)
                for update in request.auxiliary_updates
            )
        ):
            raise ValueError(
                "auxiliary_updates must be tuple[AuxiliaryFileUpdate, ...]"
            )
        if (
            request.expected_corpus_fingerprint is not None
            and (
                not isinstance(request.expected_corpus_fingerprint, str)
                or not request.expected_corpus_fingerprint.strip()
            )
        ):
            raise ValueError(
                "expected_corpus_fingerprint must be None or a non-empty string"
            )
        binding = normalize_batch_binding(request.batch_binding)
        if binding is not None:
            if request.operation is not MutationOperation.INGEST:
                raise ValueError(
                    "batch_binding is allowed only for ingest mutations"
                )
            if binding.engine_sha != request.engine_sha:
                raise ValueError(
                    "batch_binding.engine_sha must match request.engine_sha"
                )
            brain_root = request.brain_root.resolve(strict=True)
            brain_stat = brain_root.stat()
            if (
                binding.brain_root != str(brain_root)
                or binding.brain_root_device != brain_stat.st_dev
                or binding.brain_root_inode != brain_stat.st_ino
            ):
                raise ValueError(
                    "batch_binding brain_root identity must match request.brain_root"
                )
        return tuple(dict(obj) for obj in raw_inputs), None
    except Exception as exc:
        return None, _failure("request_invalid", str(exc))


def _find_duplicate_identity(
    objects: Sequence[Mapping[str, object]],
    field_names: Sequence[str],
) -> tuple[str, object] | None:
    seen: set[tuple[object, ...]] = set()
    for obj in objects:
        for field_name in field_names:
            if field_name not in obj:
                continue
            value = obj[field_name]
            identity = (
                field_name,
                obj.get("kind"),
                obj.get("context_id"),
                value,
            )
            try:
                if identity in seen:
                    return field_name, value
                seen.add(identity)
            except TypeError:
                continue
    return None


def _find_duplicate_source_id(
    objects: Sequence[Mapping[str, object]],
) -> tuple[str, object] | None:
    seen: set[object] = set()
    for obj in objects:
        if "source_id" not in obj:
            continue
        value = obj["source_id"]
        try:
            if value in seen:
                return "source_id", value
            seen.add(value)
        except TypeError:
            continue
    return None


def _object_hash(obj: Mapping[str, object]) -> str:
    return hashlib.sha256(BrainStore.object_bytes(obj)).hexdigest()


def _stable_object_hash(obj: Mapping[str, object]) -> str:
    return hashlib.sha256(stable_json(dict(obj)).encode("utf-8")).hexdigest()


def _canonical_locator_title(locator: Mapping[str, object]) -> str:
    symbol = locator.get("symbol")
    if isinstance(symbol, str) and symbol:
        return symbol
    path = locator.get("path")
    basename = (
        PurePosixPath(path).name
        if isinstance(path, str) and path
        else "unknown"
    )
    object_id = locator.get("id")
    anchor_key = (
        object_id.rsplit(".", 1)[-1]
        if isinstance(object_id, str) and object_id
        else "unknown"
    )
    return f"{basename}:{anchor_key}"


def _corpus_fingerprint(objects: Mapping[str, Mapping[str, object]]) -> str:
    digest = hashlib.sha256()
    for object_id in sorted(objects):
        digest.update(object_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(BrainStore.object_bytes(objects[object_id]))
        digest.update(b"\0")
    return digest.hexdigest()


def corpus_fingerprint(store: BrainStore) -> str:
    """현재 in-memory store snapshot의 exact corpus fingerprint."""
    return _corpus_fingerprint({
        obj["id"]: obj
        for obj in store.all()
    })


def _validate_explicit_renames(
    request: MutationRequest,
    *,
    existing_by_id: Mapping[str, dict],
    input_by_id: Mapping[str, dict],
    delete_ids: tuple[str, ...],
) -> tuple[tuple[tuple[str, str], ...], MutationPlanResult | None]:
    pairs = tuple(sorted(request.renames.items()))
    if not pairs:
        return (), None
    if request.operation is not MutationOperation.CONTEXT_REPLACE:
        return (), _failure(
            "explicit_rename_operation_invalid",
            "explicit renames are allowed only for context_replace",
        )
    targets = [new_id for _, new_id in pairs]
    if len(set(targets)) != len(targets):
        return (), _failure(
            "explicit_rename_target_duplicate",
            "explicit renames contain a duplicate target object id",
        )
    delete_set = set(delete_ids)
    for old_id, new_id in pairs:
        if old_id == new_id:
            return (), _failure(
                "explicit_rename_identity",
                f"{old_id}: rename source and target must differ",
            )
        if old_id not in existing_by_id:
            return (), _failure(
                "explicit_rename_old_missing",
                f"{old_id}: rename source is missing from the current store",
            )
        if old_id not in delete_set:
            return (), _failure(
                "explicit_rename_old_not_deleted",
                f"{old_id}: rename source must be an explicit delete target",
            )
        if old_id in input_by_id:
            return (), _failure(
                "explicit_rename_old_conflict",
                f"{old_id}: rename source cannot also be an input object",
            )
        if new_id not in input_by_id:
            return (), _failure(
                "explicit_rename_new_missing",
                f"{new_id}: rename target is missing from input objects",
            )
        if new_id in existing_by_id:
            return (), _failure(
                "explicit_rename_new_not_create",
                f"{new_id}: rename target must be a newly created object",
            )
    return pairs, None


def is_target_derived_single_review_rename(
    before: Mapping[str, object],
    after: Mapping[str, object],
    replacements: Mapping[str, str],
) -> bool:
    """대상 ID rename에 딸린 current-valid single ReviewRecord인지 확인한다."""
    if (
        before.get("kind") != "ReviewRecord"
        or after.get("kind") != "ReviewRecord"
    ):
        return False
    before_id = before.get("id")
    after_id = after.get("id")
    before_target = before.get("target_object_id")
    after_target = after.get("target_object_id")
    if not all(
        isinstance(value, str) and value
        for value in (before_id, after_id, before_target, after_target)
    ):
        return False
    if (
        ("review_scope" in before and before["review_scope"] != "single_object")
        or ("review_scope" in after and after["review_scope"] != "single_object")
    ):
        return False
    try:
        before_parsed = parse_id(before_id, "ReviewRecord")
        after_parsed = parse_id(after_id, "ReviewRecord")
    except IdGrammarError:
        return False
    if (
        before_parsed.variant != "single"
        or after_parsed.variant != "single"
        or validate_object_id(dict(before))
        or before_parsed.target_object_id != before_target
        or after_parsed.target_object_id != after_target
        or before_id != f"review.{before_target}"
        or after_id != f"review.{after_target}"
        or replacements.get(before_id) != after_id
        or replacements.get(before_target) != after_target
        or sum(value == after_id for value in replacements.values()) != 1
        or sum(value == after_target for value in replacements.values()) != 1
    ):
        return False
    expected, _ = rewrite_object_refs(before, replacements)
    expected["id"] = after_id
    return expected == after


def _infer_id_only_renames(
    operation: MutationOperation,
    existing_by_id: Mapping[str, dict],
    input_by_id: Mapping[str, dict],
    delete_ids: tuple[str, ...],
) -> tuple[tuple[tuple[str, str], ...], MutationPlanResult | None]:
    if operation is not MutationOperation.ID_ONLY_MIGRATION:
        return (), None

    created_ids = [
        object_id
        for object_id in input_by_id
        if object_id not in existing_by_id
    ]
    unused_new = set(created_ids)
    pairs: list[tuple[str, str]] = []
    for old_id in sorted(delete_ids):
        old = existing_by_id[old_id]
        comparable_old = _id_only_shape(old)
        matches = [
            new_id
            for new_id in sorted(unused_new)
            if input_by_id[new_id].get("kind") == old.get("kind")
            and _id_only_shape(input_by_id[new_id]) == comparable_old
        ]
        if len(matches) != 1:
            return (), _failure(
                "id_only_payload_changed",
                (
                    f"{old_id}: ID-only migration requires exactly one "
                    "payload-identical replacement"
                ),
            )
        new_id = matches[0]
        unused_new.remove(new_id)
        pairs.append((old_id, new_id))

    if unused_new:
        return (), _failure(
            "id_only_payload_changed",
            "ID-only migration contains a new object without a legacy source",
        )

    structured_id_problem_ids = {
        object_id
        for problem in lint_store_report(BrainStore(dict(existing_by_id)))
        if problem.code in _STRUCTURED_ID_LINT_CODES
        for object_id in problem.object_ids
    }
    replacements = dict(pairs)
    for old_id, new_id in pairs:
        is_allowed_source = (
            old_id in structured_id_problem_ids
            or is_target_derived_single_review_rename(
                existing_by_id[old_id],
                input_by_id[new_id],
                replacements,
            )
        )
        if not is_allowed_source:
            return (), _failure(
                "id_only_legacy_source_not_invalid",
                (
                    f"{old_id}: ID-only rename source has no structured "
                    "ID problem"
                ),
            )
        new_id_errors = validate_object_id(input_by_id[new_id])
        if new_id_errors:
            return (), _failure(
                "id_only_replacement_invalid",
                f"{new_id}: replacement ID is not canonical",
            )

    for old_id, new_id in pairs:
        expected, _ = rewrite_object_refs(
            existing_by_id[old_id],
            replacements,
        )
        expected["id"] = new_id
        if expected != input_by_id[new_id]:
            return (), _failure(
                "id_only_payload_changed",
                (
                    f"{old_id}: replacement changes fields other than "
                    "the object ID or registered references"
                ),
            )
    for object_id in sorted(set(existing_by_id) & set(input_by_id)):
        expected, _ = rewrite_object_refs(
            existing_by_id[object_id],
            replacements,
        )
        if expected != input_by_id[object_id]:
            return (), _failure(
                "id_only_payload_changed",
                (
                    f"{object_id}: update changes fields other than "
                    "registered references"
                ),
            )
    return tuple(pairs), None


def _id_only_shape(obj: Mapping[str, object]) -> dict:
    replacements = {
        ref.object_id: "$REFERENCE"
        for ref in iter_object_refs(obj)
    }
    shaped, _ = rewrite_object_refs(obj, replacements)
    shaped.pop("id", None)
    return shaped


def _problem_object_hash(
    problem: LintProblem,
    objects: Mapping[str, Mapping[str, object]],
) -> str:
    serialized = [
        stable_json(dict(objects[object_id]))
        for object_id in sorted(problem.object_ids)
        if object_id in objects
    ]
    return hashlib.sha256("\n".join(serialized).encode("utf-8")).hexdigest()


def _grandfathered_problem(
    problem: LintProblem,
    objects: Mapping[str, Mapping[str, object]],
) -> dict:
    return {
        "object_id": problem.object_ids[0] if len(problem.object_ids) == 1 else None,
        "problem": problem.message,
        "object_hash": _problem_object_hash(problem, objects),
    }


def _grandfathered_problems(
    report: Sequence[LintProblem],
    objects: Mapping[str, Mapping[str, object]],
) -> tuple[dict, ...]:
    return tuple(
        _grandfathered_problem(problem, objects)
        for problem in report
        if problem.code in _STRUCTURED_ID_LINT_CODES
    )


def _grandfather_key(problem: Mapping[str, object]) -> tuple[object, ...]:
    return (
        problem.get("object_id"),
        problem.get("problem"),
        problem.get("object_hash"),
    )


def _relative_object_path(
    brain_root: Path,
    obj: Mapping[str, object],
) -> str:
    return BrainStore.object_path(brain_root, obj).relative_to(brain_root).as_posix()


def _reference_rewrites(
    existing_by_id: Mapping[str, dict],
    planned_by_id: Mapping[str, dict],
    rename_pairs: tuple[tuple[str, str], ...],
) -> tuple[dict, ...]:
    rewrites: list[dict] = []
    comparisons = [
        (object_id, object_id, object_id)
        for object_id in sorted(set(existing_by_id) & set(planned_by_id))
    ]
    comparisons.extend(
        (old_id, new_id, new_id)
        for old_id, new_id in sorted(rename_pairs)
    )
    for before_id, after_id, manifest_object_id in comparisons:
        before = {
            ref.pointer: ref.object_id
            for ref in iter_object_refs(existing_by_id[before_id])
        }
        after = {
            ref.pointer: ref.object_id
            for ref in iter_object_refs(planned_by_id[after_id])
        }
        for pointer in sorted(set(before) & set(after)):
            if before[pointer] == after[pointer]:
                continue
            rewrites.append(
                {
                    "object_id": manifest_object_id,
                    "pointer": pointer,
                    "before_id": before[pointer],
                    "after_id": after[pointer],
                }
            )
    return tuple(rewrites)


def _required_source_receipt_ids(
    *,
    existing_by_id: Mapping[str, dict],
    planned_by_id: Mapping[str, dict],
    delete_ids: tuple[str, ...],
    rename_pairs: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    renamed_old_ids = {old_id for old_id, _ in rename_pairs}
    required = {
        object_id
        for object_id, obj in planned_by_id.items()
        if (
            object_id in existing_by_id
            and _object_hash(existing_by_id[object_id]) != _object_hash(obj)
        )
    }
    required.update(
        object_id
        for object_id in delete_ids
        if object_id not in renamed_old_ids
    )
    required.update(renamed_old_ids)
    return tuple(sorted(required))


def _build_manifest(
    *,
    request: MutationRequest,
    existing_by_id: Mapping[str, dict],
    planned_by_id: Mapping[str, dict],
    merged: Mapping[str, dict],
    delete_ids: tuple[str, ...],
    rename_pairs: tuple[tuple[str, str], ...],
    source_sha256_by_id: Mapping[str, str],
    before_fingerprint: str,
    expected_after_fingerprint: str,
    before_grandfathered: tuple[dict, ...],
    after_grandfathered: tuple[dict, ...],
) -> MutationManifest:
    renamed_old_ids = {old_id for old_id, _ in rename_pairs}
    renamed_new_ids = {new_id for _, new_id in rename_pairs}

    creates = tuple(
        {
            "object_id": object_id,
            "path": _relative_object_path(request.brain_root, obj),
            "before_sha256": None,
            "after_sha256": _object_hash(obj),
        }
        for object_id, obj in sorted(planned_by_id.items())
        if object_id not in existing_by_id and object_id not in renamed_new_ids
    )
    updates = tuple(
        {
            "object_id": object_id,
            "path": _relative_object_path(request.brain_root, obj),
            "before_sha256": source_sha256_by_id[object_id],
            "after_sha256": _object_hash(obj),
        }
        for object_id, obj in sorted(planned_by_id.items())
        if (
            object_id in existing_by_id
            and _object_hash(existing_by_id[object_id]) != _object_hash(obj)
        )
    )
    deletes = tuple(
        {
            "object_id": object_id,
            "path": _relative_object_path(
                request.brain_root,
                existing_by_id[object_id],
            ),
            "before_sha256": source_sha256_by_id[object_id],
            "after_sha256": None,
        }
        for object_id in sorted(delete_ids)
        if object_id not in renamed_old_ids
    )
    renames = tuple(
        {
            "old_id": old_id,
            "new_id": new_id,
            "old_path": _relative_object_path(
                request.brain_root,
                existing_by_id[old_id],
            ),
            "new_path": _relative_object_path(
                request.brain_root,
                merged[new_id],
            ),
            "before_sha256": source_sha256_by_id[old_id],
            "after_sha256": _object_hash(merged[new_id]),
        }
        for old_id, new_id in sorted(rename_pairs)
    )
    reference_rewrites = _reference_rewrites(
        existing_by_id,
        planned_by_id,
        rename_pairs,
    )
    auxiliary_updates = tuple(
        {
            "path": update.path,
            "before_sha256": update.before_sha256,
            "after_sha256": update.after_sha256,
        }
        for update in sorted(
            request.auxiliary_updates,
            key=lambda item: item.path,
        )
    )
    batch_binding = batch_binding_dict(request.batch_binding)
    seed = {
        "operation": request.operation.value,
        "engine_sha": request.engine_sha,
        "creates": creates,
        "updates": updates,
        "deletes": deletes,
        "renames": renames,
        "reference_rewrites": reference_rewrites,
        "auxiliary_updates": auxiliary_updates,
        "before_fingerprint": before_fingerprint,
        "expected_after_fingerprint": expected_after_fingerprint,
        "grandfathered_problems_before": before_grandfathered,
        "grandfathered_problems_after": after_grandfathered,
        "batch_binding": batch_binding,
    }
    transaction_id = hashlib.sha256(
        json.dumps(
            seed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return MutationManifest(
        transaction_id=transaction_id,
        operation=request.operation.value,
        engine_sha=request.engine_sha,
        creates=creates,
        updates=updates,
        deletes=deletes,
        renames=renames,
        reference_rewrites=reference_rewrites,
        auxiliary_updates=auxiliary_updates,
        before_fingerprint=before_fingerprint,
        expected_after_fingerprint=expected_after_fingerprint,
        grandfathered_problems_before=before_grandfathered,
        grandfathered_problems_after=after_grandfathered,
        batch_binding=batch_binding,
    )


def _manifest_bytes(manifest: MutationManifest) -> bytes:
    return (
        json.dumps(
            asdict(manifest),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
