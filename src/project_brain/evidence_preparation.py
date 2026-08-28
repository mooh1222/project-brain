"""Evidence preparation의 object-only base plan 경계."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from types import MappingProxyType

from project_brain import snapshot
from project_brain.capabilities import CAPABILITY_REGISTRY, VerificationMode
from project_brain.evidence_plan import (
    EvidencePlanEntry,
    EvidencePlanRequirement,
    RawSourceObservation,
)
from project_brain.foundation import FoundationError, capture_loaded_engine_identity
from project_brain.hash_utils import source_content_hash
from project_brain.id_grammar import IdGrammarError, parse_id
from project_brain.snapshot import SnapshotError, read_regular_no_follow
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
class _LocalRawAdapterSelection:
    target_id: str
    target_kind: str
    variant: str
    source_type: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.target_kind, self.variant, self.source_type)


_LOCAL_RAW_ADAPTER_REGISTRY: Mapping[tuple[str, str, str], tuple[str, str]] = MappingProxyType({
    ("EvidenceManifest", "default", "raw_source_observation"): ("local_raw_observation", "1"),
    ("SpecDocument", "default", "raw_source_observation"): ("local_raw_observation", "1"),
    ("SpecRevision", "default", "raw_source_observation"): ("local_raw_observation", "1"),
    ("SlideRef", "default", "raw_source_observation"): ("local_raw_observation", "1"),
    ("SlackThread", "default", "raw_source_observation"): ("local_raw_observation", "1"),
})


def _loaded_adapter_module_path() -> Path:
    return Path(__file__).resolve()


def _selected_local_raw_adapter(
    target: BasePlanTarget,
    entry: EvidencePlanEntry,
) -> _LocalRawAdapterSelection:
    if (
        type(target) is not BasePlanTarget
        or type(entry) is not EvidencePlanEntry
        or target.target_id != entry.target_id
        or type(entry.source) is not RawSourceObservation
    ):
        raise EvidencePreparationError(
            "evidence_source_variant_mismatch",
            "local raw adapter target and source do not match",
        )
    try:
        parsed = parse_id(target.target_id, target.kind)
    except (IdGrammarError, TypeError) as exc:
        raise EvidencePreparationError(
            "evidence_source_variant_mismatch",
            "local raw adapter target ID and kind do not match",
        ) from exc
    return _LocalRawAdapterSelection(
        target_id=target.target_id,
        target_kind=parsed.kind,
        variant=parsed.variant,
        source_type="raw_source_observation",
    )


def _capture_loaded_adapter_identity(
    selection: _LocalRawAdapterSelection,
) -> LoadedAdapterIdentity:
    registration = _LOCAL_RAW_ADAPTER_REGISTRY.get(selection.key)
    if registration is None:
        raise EvidencePreparationError(
            "evidence_adapter_unavailable",
            f"local raw adapter is unavailable for {selection.key!r}",
        )
    adapter_id, version = registration
    try:
        module_path = _loaded_adapter_module_path()
        module_bytes, _ = read_regular_no_follow(module_path)
    except (OSError, SnapshotError, ValueError) as exc:
        raise EvidencePreparationError(
            "evidence_adapter_unavailable",
            f"cannot read loaded local raw adapter module: {exc}",
        ) from exc
    return LoadedAdapterIdentity(
        id=adapter_id,
        version=version,
        module_path=str(module_path),
        module_sha256=hashlib.sha256(module_bytes).hexdigest(),
    )


def capture_loaded_adapter_identity(
    *,
    target: BasePlanTarget,
    entry: EvidencePlanEntry,
) -> LoadedAdapterIdentity:
    """BasePlan target과 E1 entry로 고른 실제 Adapter module 신원을 읽는다."""

    return _capture_loaded_adapter_identity(_selected_local_raw_adapter(target, entry))


def _raw_source_path_parts(raw_path: object) -> tuple[str, ...]:
    if type(raw_path) is not str:
        raise EvidencePreparationError(
            "evidence_plan_schema_invalid",
            "raw source path must be a string",
        )
    if not raw_path or "\\" in raw_path or "\0" in raw_path:
        raise EvidencePreparationError(
            "evidence_plan_schema_invalid",
            "raw source path is not a safe POSIX path",
        )
    parts = tuple(raw_path.split("/"))
    if (
        len(parts) < 3
        or parts[:2] != ("raw", "sources")
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise EvidencePreparationError(
            "evidence_plan_schema_invalid",
            "raw source path must be below raw/sources",
        )
    return parts


def _exact_brain_root(brain_root: Path) -> Path:
    path = Path(brain_root)
    if not path.is_absolute() or path != Path(os.path.abspath(path)):
        raise EvidencePreparationError(
            "evidence_plan_schema_invalid",
            f"brain root must be an exact absolute path: {path}",
        )
    return path


def _capture_raw_source_snapshot(
    brain_root: Path,
    raw_path: str,
) -> RawSourceSnapshot:
    _raw_source_path_parts(raw_path)
    try:
        captured = snapshot.capture_rooted_regular_file(brain_root, raw_path)
    except SnapshotError as exc:
        code = (
            "evidence_raw_source_invalid"
            if exc.code in {
                "filesystem_mismatch",
                "source_link_count_invalid",
                "source_type_invalid",
                "symlink_forbidden",
            }
            else "evidence_raw_source_unavailable"
        )
        raise EvidencePreparationError(
            code,
            f"cannot capture raw source {raw_path}: {exc.detail}",
        ) from exc
    return RawSourceSnapshot(
        root=captured.root,
        path=captured.path,
        parent_bindings=captured.parent_bindings,
        file=captured.file,
    )


@dataclass(frozen=True)
class EngineRootIdentity:
    path: str
    device: int
    inode: int


@dataclass(frozen=True)
class LoadedEngineIdentity:
    root: EngineRootIdentity
    head: str
    core_tracked_tree_sha256: str
    import_file: str
    cli_source_file: str


@dataclass(frozen=True)
class LoadedAdapterIdentity:
    id: str
    version: str
    module_path: str
    module_sha256: str


@dataclass(frozen=True)
class RawSourceSnapshot:
    root: snapshot.RootedRegularFileRootBinding
    path: str
    parent_bindings: tuple[snapshot.RootedRegularFileParentBinding, ...]
    file: snapshot.RootedRegularFile


@dataclass(frozen=True, init=False)
class EvidenceLoadedIdentity:
    engine_root: Path
    brain_root: Path
    target_id: str
    target_kind: str
    adapter_selection: _LocalRawAdapterSelection
    raw_path: str
    engine: LoadedEngineIdentity
    adapter: LoadedAdapterIdentity
    raw_snapshot: RawSourceSnapshot

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise TypeError("EvidenceLoadedIdentity is created only by its capture factory")


def _captured_evidence_loaded_identity(
    *,
    engine_root: Path,
    brain_root: Path,
    target_id: str,
    target_kind: str,
    adapter_selection: _LocalRawAdapterSelection,
    raw_path: str,
    engine: LoadedEngineIdentity,
    adapter: LoadedAdapterIdentity,
    raw_snapshot: RawSourceSnapshot,
) -> EvidenceLoadedIdentity:
    identity = object.__new__(EvidenceLoadedIdentity)
    object.__setattr__(identity, "engine_root", engine_root)
    object.__setattr__(identity, "brain_root", brain_root)
    object.__setattr__(identity, "target_id", target_id)
    object.__setattr__(identity, "target_kind", target_kind)
    object.__setattr__(identity, "adapter_selection", adapter_selection)
    object.__setattr__(identity, "raw_path", raw_path)
    object.__setattr__(identity, "engine", engine)
    object.__setattr__(identity, "adapter", adapter)
    object.__setattr__(identity, "raw_snapshot", raw_snapshot)
    return identity


def _loaded_engine_identity_value(value: Mapping[str, object]) -> LoadedEngineIdentity:
    root = value["root"]
    if not isinstance(root, Mapping):  # pragma: no cover - foundation-owned contract
        raise EvidencePreparationError("engine_identity_unavailable", "engine root is invalid")
    return LoadedEngineIdentity(
        root=EngineRootIdentity(
            path=str(root["path"]),
            device=int(root["device"]),
            inode=int(root["inode"]),
        ),
        head=str(value["head"]),
        core_tracked_tree_sha256=str(value["core_tracked_tree_sha256"]),
        import_file=str(value["import_file"]),
        cli_source_file=str(value["cli_source_file"]),
    )


def _capture_engine_identity(engine_root: Path) -> dict[str, object]:
    try:
        return capture_loaded_engine_identity(engine_root)
    except FoundationError as exc:
        raise EvidencePreparationError(exc.code, exc.detail) from exc


def capture_evidence_loaded_identity(
    *,
    engine_root: Path,
    brain_root: Path,
    target: BasePlanTarget,
    entry: EvidencePlanEntry,
) -> EvidenceLoadedIdentity:
    """E3가 준비본에 결속할 실제 engine·Adapter·raw source 신원을 읽는다."""

    exact_brain_root = _exact_brain_root(brain_root)
    selection = _selected_local_raw_adapter(target, entry)
    assert type(entry.source) is RawSourceObservation
    raw_path = entry.source.path
    engine = _loaded_engine_identity_value(_capture_engine_identity(engine_root))
    adapter = _capture_loaded_adapter_identity(selection)
    raw_snapshot = _capture_raw_source_snapshot(exact_brain_root, raw_path)
    return _captured_evidence_loaded_identity(
        engine_root=Path(engine.root.path),
        brain_root=exact_brain_root,
        target_id=target.target_id,
        target_kind=selection.target_kind,
        adapter_selection=selection,
        raw_path=raw_path,
        engine=engine,
        adapter=adapter,
        raw_snapshot=raw_snapshot,
    )


def _identity_snapshot_changed(detail: str) -> None:
    raise EvidencePreparationError("evidence_snapshot_changed", detail)


def verify_evidence_loaded_identity(identity: EvidenceLoadedIdentity) -> None:
    """준비 뒤 재관측한 E3 identity가 byte-exact로 같은지 확인한다."""

    if type(identity) is not EvidenceLoadedIdentity:
        _identity_snapshot_changed("prepared loaded identity is invalid")
    try:
        adapter = _capture_loaded_adapter_identity(identity.adapter_selection)
    except EvidencePreparationError as exc:
        _identity_snapshot_changed(f"loaded adapter changed: {exc.detail or exc.code}")
    if adapter != identity.adapter:
        _identity_snapshot_changed("loaded adapter changed")

    try:
        engine = _loaded_engine_identity_value(
            _capture_engine_identity(identity.engine_root)
        )
    except EvidencePreparationError as exc:
        _identity_snapshot_changed(f"loaded engine changed: {exc.detail or exc.code}")
    if engine != identity.engine:
        _identity_snapshot_changed("loaded engine changed")

    try:
        raw_snapshot = _capture_raw_source_snapshot(
            identity.brain_root,
            identity.raw_path,
        )
    except EvidencePreparationError as exc:
        _identity_snapshot_changed(f"raw source changed: {exc.detail or exc.code}")
    if raw_snapshot != identity.raw_snapshot:
        _identity_snapshot_changed("raw source changed")


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
