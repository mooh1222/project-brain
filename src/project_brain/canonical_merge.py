"""Existing canonical 객체로 collision source를 합치는 순수 projection."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass

from project_brain.id_grammar import validate_id_fields
from project_brain.reference_fields import (
    LIST_REFERENCE_FIELDS,
    NESTED_REFERENCE_POINTERS,
    SCALAR_REFERENCE_FIELDS,
    _set_value_at_pointer,
    _value_at_pointer,
    iter_object_refs,
)


_TARGET_FIELDS = frozenset({
    "title", "canonical_summary", "meaning", "boundary", "poc_priority",
})
_EXACT_FIELDS = frozenset({
    "kind", "schema_version", "status", "truth_role", "context_id",
    "mapping_key", "review_record_id", "review_state", "created_at", "updated_at",
})
_UNION_FIELDS = frozenset({
    "code_locator_ids", "decision_record_ids", "evidence_refs",
    "glossary_term_ids", "tags",
})
_HISTORY_ORDER = {"unsearched": 0, "partial": 1, "complete": 2}


@dataclass(frozen=True)
class ReferenceCollapse:
    object_id: str
    pointer: str
    before_ids: tuple[str, ...]
    after_ids: tuple[str, ...]
    removed_index: int


@dataclass(frozen=True)
class CollisionMergeProjection:
    after_by_id: dict[str, dict]
    merge_pairs: tuple[tuple[str, str], ...]
    changed_object_ids: tuple[str, ...]
    reference_collapses: tuple[ReferenceCollapse, ...]


@dataclass(frozen=True)
class CollisionMergeError(ValueError):
    code: str
    detail: str


def _fail(code: str, detail: str) -> None:
    raise CollisionMergeError(code, detail)


def _stable_union(target: list[str], source: list[str]) -> list[str]:
    seen = set(target)
    return [*target, *(item for item in source if item not in seen)]


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


def _same_bytes(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        assert isinstance(right, dict)
        return list(left) == list(right) and all(
            _same_bytes(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        assert isinstance(right, list)
        return len(left) == len(right) and all(
            _same_bytes(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _validated_string_list(value: object, *, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _fail("merge_list_invalid", f"{field} must be list[str]")
    if len(value) != len(set(value)):
        _fail("merge_list_duplicate", f"{field} must not contain duplicates")
    return value


def _parse_caveats(value: object) -> tuple[list[str], dict[str, str]]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        _fail("merge_caveat_invalid", "caveats must be list[str]")
    if len(value) != len(set(value)):
        _fail("merge_caveat_invalid", "caveats must not contain duplicates")
    history_items = [
        caveat for caveat in value if caveat.startswith("history_coverage=")
    ]
    if len(history_items) > 1:
        _fail("merge_caveat_invalid", "history_coverage must appear exactly once")

    keyed: dict[str, str] = {}
    for caveat in value:
        if "=" not in caveat:
            continue
        key, item_value = caveat.split("=", 1)
        if not key or not item_value:
            _fail("merge_caveat_invalid", f"invalid caveat {caveat!r}")
        previous = keyed.get(key)
        if previous is not None and previous != item_value:
            _fail("merge_caveat_conflict", f"conflicting caveat key {key!r}")
        keyed[key] = item_value
    return value, keyed


def _merge_caveats(source_value: object, target_value: object) -> list[str]:
    source, source_keyed = _parse_caveats(source_value)
    target, target_keyed = _parse_caveats(target_value)

    source_history = source_keyed.get("history_coverage")
    target_history = target_keyed.get("history_coverage")
    if (source_history is None) != (target_history is None):
        _fail("merge_caveat_invalid", "history_coverage must be present on both sides")
    if source_history is not None:
        if source_history not in _HISTORY_ORDER or target_history not in _HISTORY_ORDER:
            _fail("merge_caveat_invalid", "history_coverage value is invalid")

    for key in source_keyed.keys() & target_keyed.keys() - {"history_coverage"}:
        if source_keyed[key] != target_keyed[key]:
            _fail("merge_caveat_conflict", f"conflicting caveat key {key!r}")

    if source_history is None:
        return _stable_union(target, source)

    assert target_history is not None
    history = min((source_history, target_history), key=_HISTORY_ORDER.__getitem__)
    rewritten_target = [
        f"history_coverage={history}" if item.startswith("history_coverage=") else item
        for item in target
    ]
    rewritten_source = [
        f"history_coverage={history}" if item.startswith("history_coverage=") else item
        for item in source
    ]
    return _stable_union(rewritten_target, rewritten_source)


def _merge_payload(source: Mapping[str, object], target: Mapping[str, object]) -> dict:
    if source.keys() != target.keys():
        _fail("merge_unknown_field_mismatch", "source and target key sets differ")

    for field in _EXACT_FIELDS:
        if not _json_exact(source[field], target[field]):
            _fail("merge_exact_field_mismatch", f"field {field!r} differs")

    merged = deepcopy(dict(target))
    for field in _UNION_FIELDS:
        source_list = _validated_string_list(source[field], field=field)
        target_list = _validated_string_list(target[field], field=field)
        merged[field] = _stable_union(target_list, source_list)
    merged["caveats"] = _merge_caveats(source["caveats"], target["caveats"])

    known = {"id", "caveats"} | _TARGET_FIELDS | _EXACT_FIELDS | _UNION_FIELDS
    for field in source.keys() - known:
        if not _json_exact(source[field], target[field]):
            _fail("merge_unknown_field_mismatch", f"field {field!r} differs")
    return merged


def _validate_endpoints(
    existing_by_id: Mapping[str, Mapping[str, object]],
    pairs: tuple[tuple[str, str], ...],
) -> None:
    for source_id, target_id in pairs:
        if source_id == target_id:
            _fail("merge_endpoint_identity", f"source equals target {source_id!r}")

    targets = tuple(target_id for _, target_id in pairs)
    if len(targets) != len(set(targets)):
        _fail("merge_target_duplicate", "each merge target must be unique")
    overlap = {source_id for source_id, _ in pairs} & set(targets)
    if overlap:
        _fail("merge_endpoint_overlap", f"merge endpoints overlap: {sorted(overlap)!r}")

    for source_id, target_id in pairs:
        if source_id not in existing_by_id:
            _fail("merge_source_missing", f"missing source {source_id!r}")
        if target_id not in existing_by_id:
            _fail("merge_target_missing", f"missing target {target_id!r}")

        target = existing_by_id[target_id]
        if target.get("kind") != "DomainMapping":
            _fail("merge_target_kind_invalid", f"target {target_id!r} is not DomainMapping")
        if target.get("id") != target_id or validate_id_fields(target):
            _fail("merge_target_id_invalid", f"target {target_id!r} is not canonical")


def _validate_reference_lists(
    after_by_id: Mapping[str, Mapping[str, object]],
    pairs: tuple[tuple[str, str], ...],
) -> None:
    for object_id in sorted(after_by_id):
        obj = after_by_id[object_id]
        for field in sorted(LIST_REFERENCE_FIELDS):
            if field not in obj:
                continue
            value = obj[field]
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                _fail(
                    "merge_reference_list_invalid",
                    f"{object_id} field {field!r} must be list[str]",
                )
            for source_id, target_id in pairs:
                if value.count(source_id) > 1 or value.count(target_id) > 1:
                    _fail(
                        "merge_reference_duplicate",
                        f"{object_id} field {field!r} duplicates a merge endpoint",
                    )


def _validate_merge_reference_constraints(
    existing_by_id: Mapping[str, Mapping[str, object]],
    pairs: tuple[tuple[str, str], ...],
) -> None:
    pair_by_endpoint = {
        endpoint: pair_index
        for pair_index, pair in enumerate(pairs)
        for endpoint in pair
    }
    source_ids = frozenset(source_id for source_id, _ in pairs)
    for object_id in sorted(existing_by_id):
        obj = existing_by_id[object_id]
        for field in sorted(LIST_REFERENCE_FIELDS):
            value = obj.get(field)
            if not isinstance(value, list):
                continue
            pair_indexes = {
                pair_by_endpoint[item]
                for item in value
                if isinstance(item, str) and item in pair_by_endpoint
            }
            if len(pair_indexes) > 1:
                _fail(
                    "merge_reference_multi_pair",
                    f"{object_id} field {field!r} references multiple merge pairs",
                )
            if object_id not in source_ids:
                continue
            for source_id, target_id in pairs:
                if (
                    source_id != object_id
                    and source_id in value
                    and target_id in value
                ):
                    _fail(
                        "merge_reference_source_referrer",
                        (
                            f"merge source {object_id} field {field!r} "
                            "would record another pair's collapse"
                        ),
                    )


def _validate_projection_merge_source_refs(
    existing_by_id: Mapping[str, Mapping[str, object]],
    source_ids: frozenset[str],
) -> None:
    for object_id in sorted(existing_by_id):
        obj = existing_by_id[object_id]
        if obj.get("kind") != "ContextProjection":
            continue
        for ref in iter_object_refs(obj):
            if ref.object_id in source_ids:
                _fail(
                    "merge_context_projection_reference",
                    (
                        f"{object_id} registered reference {ref.pointer} "
                        f"points to merge source {ref.object_id}"
                    ),
                )


def _validate_provenance_references(
    after_by_id: Mapping[str, Mapping[str, object]],
    source_ids: frozenset[str],
) -> None:
    for object_id in sorted(after_by_id):
        obj = after_by_id[object_id]
        scalar = obj.get("source_object_id")
        if isinstance(scalar, str) and scalar in source_ids:
            _fail(
                "merge_provenance_reference",
                f"{object_id} has provenance reference to merge source",
            )
        if obj.get("kind") == "ContextProjection":
            continue
        values = obj.get("source_object_ids", [])
        if any(item in source_ids for item in values if isinstance(item, str)):
            _fail(
                "merge_provenance_reference",
                f"{object_id} has provenance reference to merge source",
            )


def _rewrite_registered_references(
    after_by_id: dict[str, dict],
    pairs: tuple[tuple[str, str], ...],
) -> tuple[set[str], list[ReferenceCollapse]]:
    replacements = dict(pairs)
    changed_ids: set[str] = set()
    collapses: list[ReferenceCollapse] = []

    for object_id in sorted(after_by_id):
        before = after_by_id[object_id]
        if before.get("kind") == "ContextProjection":
            continue
        rewritten = deepcopy(before)

        for field in sorted(SCALAR_REFERENCE_FIELDS - {"source_object_id"}):
            value = rewritten.get(field)
            if isinstance(value, str) and value in replacements:
                rewritten[field] = replacements[value]

        for field in sorted(LIST_REFERENCE_FIELDS - {"source_object_ids"}):
            if field not in rewritten:
                continue
            value = rewritten[field]
            assert isinstance(value, list)
            for source_id, target_id in pairs:
                source_count = value.count(source_id)
                target_count = value.count(target_id)
                if source_count == 0:
                    continue
                source_index = value.index(source_id)
                if target_count == 1:
                    before_ids = tuple(value)
                    del value[source_index]
                    collapses.append(
                        ReferenceCollapse(
                            object_id=str(rewritten["id"]),
                            pointer=f"/{field}",
                            before_ids=before_ids,
                            after_ids=tuple(value),
                            removed_index=source_index,
                        )
                    )
                else:
                    value[source_index] = target_id

        for pointer in NESTED_REFERENCE_POINTERS:
            value = _value_at_pointer(rewritten, pointer)
            if isinstance(value, str) and value in replacements:
                _set_value_at_pointer(rewritten, pointer, replacements[value])

        if not _same_bytes(before, rewritten):
            after_by_id[object_id] = rewritten
            changed_ids.add(object_id)

    return changed_ids, collapses


def _validate_context_projection_dependencies(
    existing_by_id: Mapping[str, Mapping[str, object]],
    protected_ids: frozenset[str],
) -> None:
    for object_id in sorted(existing_by_id):
        obj = existing_by_id[object_id]
        if obj.get("kind") != "ContextProjection":
            continue
        source_object_ids = obj.get("source_object_ids", [])
        assert isinstance(source_object_ids, list)
        if any(item in protected_ids for item in source_object_ids):
            _fail(
                "merge_context_projection_reference",
                f"{object_id} depends on an object changed by collision merge",
            )


def project_collision_merges(
    existing_by_id: Mapping[str, Mapping[str, object]],
    merge_pairs: Mapping[str, str],
) -> CollisionMergeProjection:
    """Collision merge 결과를 입력 변경 없이 전체 logical store로 계산한다."""
    pairs = tuple(sorted(merge_pairs.items()))
    _validate_endpoints(existing_by_id, pairs)
    source_ids = frozenset(source_id for source_id, _ in pairs)
    _validate_projection_merge_source_refs(existing_by_id, source_ids)
    _validate_merge_reference_constraints(existing_by_id, pairs)
    after_by_id = {
        object_id: deepcopy(dict(obj)) for object_id, obj in existing_by_id.items()
    }
    for source_id, target_id in pairs:
        after_by_id[target_id] = _merge_payload(
            existing_by_id[source_id], existing_by_id[target_id]
        )
        del after_by_id[source_id]

    changed_ids = {
        target_id
        for _, target_id in pairs
        if not _same_bytes(existing_by_id[target_id], after_by_id[target_id])
    }
    _validate_reference_lists(after_by_id, pairs)
    _validate_provenance_references(after_by_id, source_ids)
    referrer_ids, collapses = _rewrite_registered_references(after_by_id, pairs)
    changed_ids.update(referrer_ids)
    _validate_context_projection_dependencies(
        existing_by_id,
        source_ids | frozenset(changed_ids),
    )

    return CollisionMergeProjection(
        after_by_id=after_by_id,
        merge_pairs=pairs,
        changed_object_ids=tuple(sorted(changed_ids)),
        reference_collapses=tuple(collapses),
    )
