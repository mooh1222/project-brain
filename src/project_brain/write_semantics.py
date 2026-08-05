"""Mutation 전용 쓰기 의미값과 operation/action별 timestamp 정책."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from project_brain.reference_fields import iter_object_refs, rewrite_object_refs
from project_brain.schema import BASE_REQUIRED, KIND_REQUIRED


class TimestampPolicy(StrEnum):
    LIVE = "live"
    PRESERVE = "preserve"


class ObjectActionKind(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RENAME = "rename"
    REFERENCE_REWRITE = "reference_rewrite"
    NO_CHANGE = "no_change"


@dataclass(frozen=True)
class ObjectWriteAction:
    action: ObjectActionKind
    object_id: str
    object_kind: str
    source_id: str | None
    timestamp_policy: TimestampPolicy | None


@dataclass(frozen=True, order=True)
class VerifiedReferenceRewrite:
    object_id: str
    pointer: str
    before_id: str
    after_id: str


@dataclass(frozen=True, order=True)
class WriteSemanticProblem:
    code: str
    object_id: str
    field: str
    value_fingerprint: str
    message: str


@dataclass(frozen=True)
class WriteSemanticsReport:
    errors: tuple[WriteSemanticProblem, ...]
    grandfathered: tuple[WriteSemanticProblem, ...]


CALLER_TEMPORAL_FIELDS = {
    "EvidenceManifest": frozenset({"captured_at"}),
    "SpecRevision": frozenset({"captured_at"}),
    "ReviewRecord": frozenset({"reviewed_at"}),
    "EventLedgerRecord": frozenset({"happened_at"}),
    "TemporalFact": frozenset({"valid_from", "valid_until"}),
    "CurrentView": frozenset({"as_of"}),
    "IndexRecord": frozenset({"indexed_at"}),
}

_LIFECYCLE_FIELDS = frozenset({"created_at", "updated_at"})
_KIND_ENGINE_TEMPORAL_FIELDS = {
    "CodeLocator": frozenset({"verified_at"}),
    "ContextProjection": frozenset({"generated_at"}),
}
_REGISTERED_OPERATIONS = frozenset(
    {
        "ingest",
        "promote",
        "promote_auto",
        "mark_checked",
        "projection",
        "projection_repair",
        "context_replace",
        "id_only_migration",
        "display_migration",
        "canonical_repair",
    }
)
_LIVE_OPERATIONS = frozenset(
    {"ingest", "promote", "promote_auto", "mark_checked", "projection"}
)
_PRESERVE_OPERATIONS = frozenset(
    {
        "projection_repair",
        "id_only_migration",
        "display_migration",
        "canonical_repair",
    }
)
_ALLOWED_TIMESTAMP_ACTIONS = {
    "ingest": frozenset(
        {
            ObjectActionKind.CREATE,
            ObjectActionKind.UPDATE,
        }
    ),
    "promote": frozenset(
        {
            ObjectActionKind.CREATE,
            ObjectActionKind.UPDATE,
        }
    ),
    "promote_auto": frozenset(
        {
            ObjectActionKind.CREATE,
            ObjectActionKind.UPDATE,
        }
    ),
    "mark_checked": frozenset({ObjectActionKind.UPDATE}),
    "projection": frozenset({ObjectActionKind.CREATE, ObjectActionKind.UPDATE}),
    "projection_repair": frozenset({ObjectActionKind.UPDATE}),
    "id_only_migration": frozenset(
        {ObjectActionKind.RENAME, ObjectActionKind.REFERENCE_REWRITE}
    ),
    "display_migration": frozenset({ObjectActionKind.UPDATE}),
    "canonical_repair": frozenset(
        {
            ObjectActionKind.UPDATE,
            ObjectActionKind.RENAME,
            ObjectActionKind.REFERENCE_REWRITE,
        }
    ),
    "context_replace": frozenset(
        {
            ObjectActionKind.CREATE,
            ObjectActionKind.UPDATE,
            ObjectActionKind.RENAME,
            ObjectActionKind.REFERENCE_REWRITE,
        }
    ),
}

_NONBLANK_STRING_FIELDS = frozenset(
    {
        # 공통
        "id",
        "kind",
        "status",
        "poc_priority",
        "truth_role",
        "title",
        "created_at",
        "updated_at",
        # Evidence 계열
        "source_type",
        "captured_at",
        "captured_by",
        "sensitivity",
        "redaction_status",
        "ref_type",
        "summary",
        # 시간·검토 계열
        "reviewer",
        "reviewed_at",
        "verdict",
        "event_type",
        "happened_at",
        "valid_from",
        # 코드·도메인 계열
        "repo",
        "path",
        "locator_source",
        "verified_at",
        "context_key",
        "project_id",
        "display_name",
        "boundary_summary",
        "term",
        "definition",
        "mapping_key",
        "canonical_summary",
        "meaning",
        "boundary",
        # 합성·문서 계열
        "format",
        "source_content_hash",
        "projection_hash",
        "generated_at",
        "generated_by",
        "stale_policy",
        "view_type",
        "as_of",
        "category",
        "source_system",
        "canonical_locator",
        "revision_label",
        "channel_id",
        "thread_ts",
        "decision_type",
        "decision",
        "spec_reflected",
        "body",
    }
)


def _operation_value(operation: str) -> str:
    value = str(operation)
    if value not in _REGISTERED_OPERATIONS:
        raise ValueError(f"timestamp_policy_missing: unknown operation {value!r}")
    return value


def engine_owned_temporal_fields(kind: str) -> frozenset[str]:
    """kind별 engine 소유 lifecycle·검증·생성 시각 필드를 반환한다."""
    return _LIFECYCLE_FIELDS | _KIND_ENGINE_TEMPORAL_FIELDS.get(
        kind, frozenset()
    )


def engine_owned_input_fields(operation: str, kind: str) -> frozenset[str]:
    """operation이 pre-schema에서 생략을 받아들일 engine 입력 필드 집합."""
    operation_value = _operation_value(operation)
    fields = engine_owned_temporal_fields(kind)
    if (
        kind == "ReviewRecord"
        and operation_value in {"promote", "promote_auto"}
    ):
        fields |= frozenset({"reviewed_at"})
    return fields


def _json_exact(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        assert isinstance(right, dict)
        return left.keys() == right.keys() and all(
            _json_exact(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        assert isinstance(right, list)
        return len(left) == len(right) and all(
            _json_exact(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _reference_map(obj: Mapping[str, object]) -> dict[str, str]:
    return {ref.pointer: ref.object_id for ref in iter_object_refs(obj)}


def _substantive_shape(obj: Mapping[str, object]) -> dict[str, object]:
    engine_temporal = engine_owned_temporal_fields(str(obj.get("kind", "")))
    return {key: value for key, value in obj.items() if key not in engine_temporal}


def reference_only_rewrite(
    before: Mapping[str, object],
    after: Mapping[str, object],
    replacements: Mapping[str, str],
) -> bool:
    """같은 pointer의 등록 참조만 replacements대로 바뀌었는지 판정한다."""
    before_refs = _reference_map(before)
    after_refs = _reference_map(after)
    if before_refs.keys() != after_refs.keys():
        return False
    changed = {
        pointer
        for pointer in before_refs
        if before_refs[pointer] != after_refs[pointer]
    }
    if not changed:
        return False
    if any(
        replacements.get(before_refs[pointer]) != after_refs[pointer]
        for pointer in changed
    ):
        return False
    rewritten, _ = rewrite_object_refs(_substantive_shape(before), replacements)
    return _json_exact(rewritten, _substantive_shape(after))


def _timestamp_policy(
    operation: str,
    action: ObjectActionKind,
    *,
    exact_context_preserve: bool = False,
) -> TimestampPolicy | None:
    if action in {ObjectActionKind.DELETE, ObjectActionKind.NO_CHANGE}:
        return None
    operation_value = _operation_value(operation)
    if action not in _ALLOWED_TIMESTAMP_ACTIONS[operation_value]:
        raise ValueError(
            "timestamp_policy_missing: "
            f"operation={operation_value!r} action={action.value!r}"
        )
    if operation_value in _LIVE_OPERATIONS:
        return TimestampPolicy.LIVE
    if operation_value in _PRESERVE_OPERATIONS:
        return TimestampPolicy.PRESERVE
    if operation_value == "context_replace":
        return (
            TimestampPolicy.PRESERVE
            if exact_context_preserve
            else TimestampPolicy.LIVE
        )
    raise ValueError(
        "timestamp_policy_missing: "
        f"operation={operation_value!r} action={action.value!r}"
    )


def _rename_is_exact(
    before: Mapping[str, object],
    after: Mapping[str, object],
    replacements: Mapping[str, str],
) -> bool:
    projected = _substantive_shape(before)
    projected["id"] = after.get("id")
    projected, _ = rewrite_object_refs(projected, replacements)
    return _json_exact(projected, _substantive_shape(after))


def _verified_rewrite_is_exact(
    object_id: str,
    before: Mapping[str, object],
    after: Mapping[str, object],
    verified: Sequence[VerifiedReferenceRewrite],
) -> bool:
    expected = tuple(sorted(item for item in verified if item.object_id == object_id))
    if not expected:
        return False
    before_refs = _reference_map(before)
    after_refs = _reference_map(after)
    actual = tuple(
        sorted(
            VerifiedReferenceRewrite(
                object_id=object_id,
                pointer=pointer,
                before_id=before_refs[pointer],
                after_id=after_refs[pointer],
            )
            for pointer in sorted(set(before_refs) & set(after_refs))
            if before_refs[pointer] != after_refs[pointer]
        )
    )
    replacements = {item.before_id: item.after_id for item in expected}
    return actual == expected and reference_only_rewrite(
        before, after, replacements
    )


def classify_object_actions(
    *,
    operation: str,
    existing_by_id: Mapping[str, Mapping[str, object]],
    transformed_by_id: Mapping[str, Mapping[str, object]],
    delete_ids: Collection[str],
    rename_pairs: Sequence[tuple[str, str]],
    verified_reference_rewrites: Sequence[VerifiedReferenceRewrite],
) -> tuple[ObjectWriteAction, ...]:
    """before/after와 검증된 rewrite 결속으로 객체 action을 결정론적으로 분류한다."""
    operation_value = _operation_value(operation)
    replacements = dict(rename_pairs)
    renamed_old_ids = set(replacements)
    renamed_new_ids = set(replacements.values())
    actions: list[ObjectWriteAction] = []

    for old_id, new_id in sorted(rename_pairs):
        before = existing_by_id[old_id]
        after = transformed_by_id[new_id]
        exact_move = _rename_is_exact(before, after, replacements)
        source_id = (
            new_id
            if (
                operation_value == "canonical_repair"
                and new_id in existing_by_id
            )
            else old_id
        )
        actions.append(
            ObjectWriteAction(
                action=ObjectActionKind.RENAME,
                object_id=new_id,
                object_kind=str(after.get("kind", before.get("kind", ""))),
                source_id=source_id,
                timestamp_policy=_timestamp_policy(
                    operation_value,
                    ObjectActionKind.RENAME,
                    exact_context_preserve=exact_move,
                ),
            )
        )

    common_ids = (
        set(existing_by_id) & set(transformed_by_id)
    ) - renamed_old_ids - renamed_new_ids
    for object_id in sorted(common_ids):
        before = existing_by_id[object_id]
        after = transformed_by_id[object_id]
        if _json_exact(_substantive_shape(before), _substantive_shape(after)):
            action_kind = ObjectActionKind.NO_CHANGE
            exact_reference_rewrite = False
        elif _verified_rewrite_is_exact(
            object_id,
            before,
            after,
            verified_reference_rewrites,
        ):
            action_kind = ObjectActionKind.REFERENCE_REWRITE
            exact_reference_rewrite = True
        else:
            action_kind = ObjectActionKind.UPDATE
            exact_reference_rewrite = False
        actions.append(
            ObjectWriteAction(
                action=action_kind,
                object_id=object_id,
                object_kind=str(after.get("kind", before.get("kind", ""))),
                source_id=object_id,
                timestamp_policy=_timestamp_policy(
                    operation_value,
                    action_kind,
                    exact_context_preserve=exact_reference_rewrite,
                ),
            )
        )

    create_ids = set(transformed_by_id) - set(existing_by_id) - renamed_new_ids
    for object_id in sorted(create_ids):
        obj = transformed_by_id[object_id]
        actions.append(
            ObjectWriteAction(
                action=ObjectActionKind.CREATE,
                object_id=object_id,
                object_kind=str(obj.get("kind", "")),
                source_id=None,
                timestamp_policy=_timestamp_policy(
                    operation_value, ObjectActionKind.CREATE
                ),
            )
        )

    for object_id in sorted(set(delete_ids) - renamed_old_ids):
        before = existing_by_id[object_id]
        actions.append(
            ObjectWriteAction(
                action=ObjectActionKind.DELETE,
                object_id=object_id,
                object_kind=str(before.get("kind", "")),
                source_id=object_id,
                timestamp_policy=None,
            )
        )

    return tuple(actions)


def _temporal_fields(kind: str) -> frozenset[str]:
    fields = engine_owned_temporal_fields(kind) | CALLER_TEMPORAL_FIELDS.get(
        kind, frozenset()
    )
    if kind == "SlackThread":
        fields |= frozenset({"thread_ts"})
    return fields


def apply_timestamp_policy(
    objects: Sequence[Mapping[str, object]],
    *,
    actions: Sequence[ObjectWriteAction],
    existing_by_id: Mapping[str, Mapping[str, object]],
    operation: str,
    verified_object_ids: Collection[str],
    event_time: str | None,
) -> tuple[dict, ...]:
    """분류된 action에 LIVE/PRESERVE timestamp 정책을 순수하게 적용한다."""
    operation_value = _operation_value(operation)
    action_by_id = {action.object_id: action for action in actions}
    verified_ids = set(verified_object_ids)
    stamped: list[dict] = []
    for item in objects:
        object_id = str(item.get("id", ""))
        action = action_by_id.get(object_id)
        if action is None:
            stamped.append(dict(item))
            continue
        source = (
            existing_by_id.get(action.source_id)
            if action.source_id is not None
            else None
        )
        if action.action is ObjectActionKind.NO_CHANGE:
            stamped.append(dict(source if source is not None else item))
            continue

        obj = dict(item)
        if action.timestamp_policy is TimestampPolicy.PRESERVE:
            if source is None:
                raise ValueError(
                    f"timestamp_source_invalid: {object_id!r} has no source"
                )
            for field in _temporal_fields(str(obj.get("kind", ""))):
                if field in source:
                    obj[field] = source[field]
                else:
                    obj.pop(field, None)
        elif action.timestamp_policy is TimestampPolicy.LIVE:
            if event_time is None or _timestamp_reason(event_time) is not None:
                raise ValueError("timestamp_invalid: event_time must be timezone-aware ISO")
            if action.action is ObjectActionKind.CREATE:
                obj["created_at"] = event_time
            elif source is not None and "created_at" in source:
                obj["created_at"] = source["created_at"]
            obj["updated_at"] = event_time
            kind = str(obj.get("kind", ""))
            if kind == "CodeLocator" and object_id in verified_ids:
                obj["verified_at"] = event_time
            if kind == "ContextProjection" and operation_value == "projection":
                obj["generated_at"] = event_time
            if (
                kind == "ReviewRecord"
                and operation_value in {"promote", "promote_auto"}
                and "reviewed_at" not in obj
            ):
                obj["reviewed_at"] = event_time
        stamped.append(obj)
    return tuple(stamped)


def _value_fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _timestamp_reason(value: object) -> str | None:
    if not isinstance(value, str):
        return "not_string"
    if "T" not in value:
        return "not_datetime"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "invalid_iso"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return "timezone_missing"
    return None


def _problem(
    *,
    code: str,
    object_id: str,
    field: str,
    value: object,
    message: str,
) -> WriteSemanticProblem:
    return WriteSemanticProblem(
        code=code,
        object_id=object_id,
        field=field,
        value_fingerprint=_value_fingerprint(value),
        message=message,
    )


def _object_write_problems(obj: Mapping[str, object]) -> tuple[WriteSemanticProblem, ...]:
    object_id = obj.get("id") if isinstance(obj.get("id"), str) else "?"
    kind = obj.get("kind") if isinstance(obj.get("kind"), str) else ""
    required_fields = frozenset(BASE_REQUIRED) | frozenset(
        KIND_REQUIRED.get(kind, ())
    )
    problems: list[WriteSemanticProblem] = []
    for field in sorted(required_fields & _NONBLANK_STRING_FIELDS):
        if field not in obj:
            continue
        value = obj[field]
        if not isinstance(value, str) or not value.strip():
            problems.append(
                _problem(
                    code="write_semantics_invalid",
                    object_id=object_id,
                    field=field,
                    value=value,
                    message=(
                        f"{object_id}: required string field {field!r} "
                        "must be nonblank"
                    ),
                )
            )
    for field in sorted(_temporal_fields(kind) - {"thread_ts"}):
        if field not in obj:
            continue
        value = obj[field]
        reason = _timestamp_reason(value)
        if reason is not None:
            problems.append(
                _problem(
                    code="timestamp_invalid",
                    object_id=object_id,
                    field=field,
                    value=value,
                    message=(
                        f"{object_id}: timestamp field {field!r} must be "
                        f"timezone-aware ISO ({reason})"
                    ),
                )
            )
    return tuple(sorted(problems))


def validate_write_semantics(
    *,
    before_by_id: Mapping[str, Mapping[str, object]],
    after_by_id: Mapping[str, Mapping[str, object]],
    source_id_by_after_id: Mapping[str, str],
) -> WriteSemanticsReport:
    """신규·변경 문제는 막고 같은 source field/value의 기존 문제만 유예한다."""
    before_problem_keys = {
        (object_id, problem.field, problem.value_fingerprint)
        for object_id, obj in before_by_id.items()
        for problem in _object_write_problems(obj)
    }
    errors: list[WriteSemanticProblem] = []
    grandfathered: list[WriteSemanticProblem] = []
    for after_id in sorted(after_by_id):
        source_id = source_id_by_after_id.get(after_id, after_id)
        for problem in _object_write_problems(after_by_id[after_id]):
            source_key = (source_id, problem.field, problem.value_fingerprint)
            if source_key in before_problem_keys:
                grandfathered.append(problem)
            else:
                errors.append(problem)
    return WriteSemanticsReport(
        errors=tuple(sorted(errors)),
        grandfathered=tuple(sorted(grandfathered)),
    )


def collect_timestamp_diagnostics(
    objects: Iterable[Mapping[str, object]],
    *,
    include_object_ids: bool = False,
) -> dict[str, object]:
    """legacy 형식 문제와 정상 자정 밀도를 서로 다른 비차단 축으로 집계한다."""
    invalid_by_field: Counter[str] = Counter()
    invalid_by_reason: Counter[str] = Counter()
    invalid_by_date: Counter[str] = Counter()
    midnight_by_field: Counter[str] = Counter()
    midnight_by_context: Counter[str] = Counter()
    midnight_by_date: Counter[str] = Counter()
    invalid_ids: dict[str, set[str]] = {}
    midnight_ids: dict[str, set[str]] = {}
    total = 0
    midnight = 0

    for obj in objects:
        object_id = str(obj.get("id", "?"))
        kind = str(obj.get("kind", ""))
        context = str(
            obj.get("context_id")
            or obj.get("context_key")
            or (object_id.split(".")[1] if "." in object_id else "unknown")
        )
        for field in sorted(_temporal_fields(kind) - {"thread_ts"}):
            if field not in obj:
                continue
            total += 1
            value = obj[field]
            reason = _timestamp_reason(value)
            if reason is not None:
                invalid_by_field[field] += 1
                invalid_by_reason[reason] += 1
                date_bucket = (
                    value[:10]
                    if isinstance(value, str) and len(value) >= 10
                    else "unknown"
                )
                invalid_by_date[date_bucket] += 1
                invalid_ids.setdefault(f"{field}:{reason}", set()).add(object_id)
                continue
            assert isinstance(value, str)
            parsed = datetime.fromisoformat(value)
            if parsed.hour == parsed.minute == parsed.second == parsed.microsecond == 0:
                midnight += 1
                date_bucket = parsed.date().isoformat()
                midnight_by_field[field] += 1
                midnight_by_context[context] += 1
                midnight_by_date[date_bucket] += 1
                midnight_ids.setdefault(field, set()).add(object_id)

    report: dict[str, object] = {
        "timestamp_format_legacy": {
            "count": sum(invalid_by_field.values()),
            "by_field": dict(sorted(invalid_by_field.items())),
            "by_reason": dict(sorted(invalid_by_reason.items())),
            "by_date": dict(sorted(invalid_by_date.items())),
        },
        "midnight_density": {
            "total_timestamp_values": total,
            "midnight_values": midnight,
            "ratio": midnight / total if total else 0.0,
            "by_field": dict(sorted(midnight_by_field.items())),
            "by_context": dict(sorted(midnight_by_context.items())),
            "by_date": dict(sorted(midnight_by_date.items())),
        },
    }
    if include_object_ids:
        report["object_ids_by_bucket"] = {
            "timestamp_format_legacy": {
                key: sorted(ids) for key, ids in sorted(invalid_ids.items())
            },
            "midnight_density": {
                key: sorted(ids) for key, ids in sorted(midnight_ids.items())
            },
        }
    return report
