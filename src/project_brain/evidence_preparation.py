"""Evidence preparation의 object-only base plan 경계."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from project_brain.capabilities import CAPABILITY_REGISTRY, VerificationMode
from project_brain.evidence_plan import EvidencePlanRequirement
from project_brain.hash_utils import source_content_hash
from project_brain.store import BrainStore
from project_brain.write_semantics import (
    classify_object_actions,
    engine_owned_input_fields,
    engine_owned_temporal_fields,
)


class EvidencePreparationError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class BasePlanTarget:
    target_id: str
    kind: str
    action: str
    before_unstamped_bytes: bytes | None
    before_semantic_sha256: str | None
    base_unstamped_bytes: bytes | None
    base_semantic_sha256: str | None


@dataclass(frozen=True)
class BasePlan:
    targets: tuple[BasePlanTarget, ...]
    requirements: tuple[EvidencePlanRequirement, ...]


def _base_plan_input_error(detail: str) -> None:
    raise EvidencePreparationError("evidence_base_plan_invalid", detail)


def _exact_nonempty_id(value: object) -> bool:
    return type(value) is str and bool(value)


def _preflight_base_inputs(
    live_store: BrainStore,
    after_images: Iterable[Mapping[str, object]],
    delete_ids: Iterable[str],
) -> tuple[
    dict[str, Mapping[str, object]],
    tuple[Mapping[str, object], ...],
    tuple[str, ...],
]:
    parsed_after_images = tuple(after_images)
    parsed_delete_ids = tuple(delete_ids)

    after_ids: list[str] = []
    for obj in parsed_after_images:
        if not isinstance(obj, Mapping) or not _exact_nonempty_id(obj.get("id")):
            _base_plan_input_error("after-image ID is invalid")
        object_id = obj["id"]
        assert type(object_id) is str
        after_ids.append(object_id)
    if len(after_ids) != len(set(after_ids)):
        _base_plan_input_error("after-image IDs are duplicated")

    if not all(_exact_nonempty_id(object_id) for object_id in parsed_delete_ids):
        _base_plan_input_error("delete ID is invalid")
    if len(parsed_delete_ids) != len(set(parsed_delete_ids)):
        _base_plan_input_error("delete IDs are duplicated")
    if set(after_ids) & set(parsed_delete_ids):
        _base_plan_input_error("after-image and delete IDs overlap")

    existing_by_id = {obj["id"]: obj for obj in live_store.all()}
    if any(object_id not in existing_by_id for object_id in parsed_delete_ids):
        _base_plan_input_error("delete ID is not live")
    return existing_by_id, parsed_after_images, parsed_delete_ids


@dataclass(frozen=True)
class _FrozenList:
    values: tuple[object, ...]


def _freeze_snapshot_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({
            key: _freeze_snapshot_value(item)
            for key, item in value.items()
        })
    if isinstance(value, list):
        return _FrozenList(tuple(_freeze_snapshot_value(item) for item in value))
    return deepcopy(value)


def _freeze_snapshot_object(obj: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({
        key: _freeze_snapshot_value(value)
        for key, value in obj.items()
    })


def _snapshot_value_copy(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: _snapshot_value_copy(item)
            for key, item in value.items()
        }
    if isinstance(value, _FrozenList):
        return [_snapshot_value_copy(item) for item in value.values]
    return deepcopy(value)


def _snapshot_object_copy(obj: Mapping[str, object]) -> dict[str, object]:
    return {
        key: _snapshot_value_copy(value)
        for key, value in obj.items()
    }


@dataclass(frozen=True, init=False)
class ProjectedStore:
    """Live store에 같은 batch의 after-image와 delete를 반영한 불변 view."""

    _objects: Mapping[str, Mapping[str, object]]

    def __init__(
        self,
        live_store: BrainStore,
        after_images: Iterable[Mapping[str, object]],
        *,
        delete_ids: Iterable[str] = (),
    ) -> None:
        existing_by_id, parsed_after_images, parsed_delete_ids = _preflight_base_inputs(
            live_store,
            after_images,
            delete_ids,
        )
        objects = {
            object_id: _freeze_snapshot_object(obj)
            for object_id, obj in existing_by_id.items()
        }
        for obj in parsed_after_images:
            object_id = obj["id"]
            assert type(object_id) is str
            objects[object_id] = _freeze_snapshot_object(obj)
        for object_id in parsed_delete_ids:
            objects.pop(object_id, None)
        object.__setattr__(self, "_objects", MappingProxyType(objects))

    def get(self, object_id: str) -> dict[str, object]:
        return _snapshot_object_copy(self._objects[object_id])

    def has(self, object_id: str) -> bool:
        return object_id in self._objects

    def all(self) -> list[dict[str, object]]:
        return [
            _snapshot_object_copy(self._objects[object_id])
            for object_id in sorted(self._objects)
        ]

    def by_kind(self, kind: str) -> list[dict[str, object]]:
        return [
            _snapshot_object_copy(obj)
            for object_id, obj in sorted(self._objects.items())
            if obj.get("kind") == kind
        ]


def _unstamped_object(obj: Mapping[str, object]) -> dict[str, object]:
    kind = str(obj.get("kind", ""))
    engine_owned_fields = (
        engine_owned_temporal_fields(kind)
        | engine_owned_input_fields("ingest", kind)
    )
    return {
        field: value
        for field, value in obj.items()
        if field not in engine_owned_fields
    }


def _unstamped_identity(
    obj: Mapping[str, object] | None,
) -> tuple[bytes | None, str | None]:
    if obj is None:
        return None, None
    unstamped = _unstamped_object(obj)
    return (
        BrainStore.object_bytes(unstamped),
        source_content_hash((unstamped,)),
    )


def _target_requirement(
    *,
    target_id: str,
    action: str,
    obj: Mapping[str, object],
) -> EvidencePlanRequirement:
    if action == "delete":
        return EvidencePlanRequirement(
            target_id,
            "forbidden",
            "evidence_plan_delete_target",
        )

    kind = str(obj.get("kind", ""))
    if kind == "ContextProjection" and obj.get("format") == "context_md":
        return EvidencePlanRequirement(
            target_id,
            "forbidden",
            "evidence_profile_unavailable",
        )

    capability = CAPABILITY_REGISTRY.get(kind)
    if capability is None:
        return EvidencePlanRequirement(
            target_id,
            "forbidden",
            "evidence_profile_unavailable",
        )

    if VerificationMode.COMMON in capability.verification_modes:
        if action == "no_change" or obj.get("status") != "reviewed":
            return EvidencePlanRequirement(target_id, "optional_unverified")
        return EvidencePlanRequirement(
            target_id,
            "forbidden",
            "direct_reviewed_evidence_unavailable",
        )

    if VerificationMode.DEDICATED in capability.verification_modes:
        return EvidencePlanRequirement(target_id, "required")

    return EvidencePlanRequirement(
        target_id,
        "forbidden",
        "evidence_profile_unavailable",
    )


def plan_base(
    live_store: BrainStore,
    after_images: Iterable[Mapping[str, object]],
    *,
    delete_ids: Iterable[str] = (),
    repo_context: object | None = None,
) -> BasePlan:
    """Live store와 caller after-image로 외부 효과 없는 base plan을 만든다."""
    del repo_context
    existing_by_id, parsed_after_images, parsed_delete_ids = _preflight_base_inputs(
        live_store,
        after_images,
        delete_ids,
    )
    after_by_id = {
        obj["id"]: obj
        for obj in parsed_after_images
    }
    action_rows = classify_object_actions(
        operation="ingest",
        existing_by_id=existing_by_id,
        transformed_by_id=after_by_id,
        delete_ids=parsed_delete_ids,
        rename_pairs=(),
        verified_reference_rewrites=(),
    )

    targets: list[BasePlanTarget] = []
    requirements: list[EvidencePlanRequirement] = []
    for row in action_rows:
        before = (
            existing_by_id.get(row.source_id)
            if row.source_id is not None
            else None
        )
        base = (
            None
            if row.action.value == "delete"
            else (
                before
                if row.action.value == "no_change"
                else after_by_id[row.object_id]
            )
        )
        before_bytes, before_sha256 = _unstamped_identity(before)
        base_bytes, base_sha256 = _unstamped_identity(base)
        requirement = _target_requirement(
            target_id=row.object_id,
            action=row.action.value,
            obj=base if base is not None else before,
        )
        targets.append(
            BasePlanTarget(
                target_id=row.object_id,
                kind=row.object_kind,
                action=row.action.value,
                before_unstamped_bytes=before_bytes,
                before_semantic_sha256=before_sha256,
                base_unstamped_bytes=base_bytes,
                base_semantic_sha256=base_sha256,
            )
        )
        requirements.append(requirement)
    return BasePlan(
        targets=tuple(sorted(targets, key=lambda target: target.target_id)),
        requirements=tuple(
            sorted(requirements, key=lambda requirement: requirement.target_id)
        ),
    )
