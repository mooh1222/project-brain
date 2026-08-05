"""Batch mutation binding and durable receipt identity contracts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from project_brain.coverage import ObjectIdentity

if TYPE_CHECKING:
    from project_brain.mutation import MutationPlanResult


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_LEGACY_BATCH_BINDING_FIELDS = {
    "batch_manifest_sha256",
    "item_key",
    "item_input_fingerprint",
    "verify_json_sha256",
    "domain_spec_py_sha256",
    "repo_root",
    "brain_root",
    "brain_root_device",
    "brain_root_inode",
    "expected_repo_id",
    "expected_revision_ref",
    "target_revision_sha",
    "engine_root",
    "engine_sha",
}
_BATCH_BINDING_FIELDS = _LEGACY_BATCH_BINDING_FIELDS | {"coverage_sha256"}
_MUTATION_RECEIPT_FIELDS = {
    "version",
    "receipt_id",
    "ok",
    "outcome",
    "operation",
    "committed",
    "transaction_id",
    "manifest_sha256",
    "coverage_sha256",
    "expected_objects",
    "verified_objects",
    "changed_objects",
    "before_fingerprint",
    "after_fingerprint",
}
_CHANGED_ACTION_ORDER = {
    "create": 0,
    "update": 1,
    "delete": 2,
    "rename": 3,
}


class MutationOutcome(StrEnum):
    COMMITTED = "committed"
    NO_CHANGES = "no_changes"


@dataclass(frozen=True)
class LegacyBatchBindingV1:
    """Exact pre-coverage binding, accepted only for historical recovery."""

    batch_manifest_sha256: str
    item_key: str
    item_input_fingerprint: str
    verify_json_sha256: str
    domain_spec_py_sha256: str
    repo_root: str
    brain_root: str
    brain_root_device: int
    brain_root_inode: int
    expected_repo_id: str
    expected_revision_ref: str
    target_revision_sha: str
    engine_root: str
    engine_sha: str


@dataclass(frozen=True)
class BatchBinding(LegacyBatchBindingV1):
    """Immutable identity joining one batch item and its coverage to a mutation."""

    coverage_sha256: str


@dataclass(frozen=True)
class MutationReceipt:
    version: int
    receipt_id: str
    ok: bool
    outcome: MutationOutcome
    operation: str
    committed: bool
    transaction_id: str | None
    manifest_sha256: str
    coverage_sha256: str | None
    expected_objects: tuple[ObjectIdentity, ...]
    verified_objects: tuple[ObjectIdentity, ...]
    changed_objects: tuple[Mapping[str, object], ...]
    before_fingerprint: str
    after_fingerprint: str


def _canonical_receipt_identity(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != "receipt_id"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _normalize_object_identities(
    value: object,
    *,
    field: str,
) -> tuple[ObjectIdentity, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be an array")
    identities: list[ObjectIdentity] = []
    for index, raw in enumerate(value):
        if isinstance(raw, ObjectIdentity):
            identity = raw
        elif isinstance(raw, Mapping) and set(raw) == {"id", "kind"}:
            object_id = raw.get("id")
            kind = raw.get("kind")
            if (
                not isinstance(object_id, str)
                or not object_id
                or not isinstance(kind, str)
                or not kind
            ):
                raise ValueError(f"{field}[{index}] is invalid")
            identity = ObjectIdentity(object_id, kind)
        else:
            raise ValueError(f"{field}[{index}] is invalid")
        identities.append(identity)
    if len(identities) != len(set(identities)):
        raise ValueError(f"{field} contains duplicate rows")
    return tuple(sorted(identities))


def _normalize_changed_objects(
    value: object,
) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("changed_objects must be an array")
    normalized: list[dict[str, object]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise ValueError(f"changed_objects[{index}] is invalid")
        action = raw.get("action")
        if action not in _CHANGED_ACTION_ORDER:
            raise ValueError(f"changed_objects[{index}] action is invalid")
        expected_fields = (
            {"action", "old_id", "new_id", "kind"}
            if action == "rename"
            else {"action", "id", "kind"}
        )
        if set(raw) != expected_fields:
            raise ValueError(f"changed_objects[{index}] fields are invalid")
        for field_name in expected_fields - {"action"}:
            field_value = raw.get(field_name)
            if not isinstance(field_value, str) or not field_value:
                raise ValueError(
                    f"changed_objects[{index}].{field_name} is invalid"
                )
        normalized.append(
            {
                "action": action,
                "old_id": raw["old_id"],
                "new_id": raw["new_id"],
                "kind": raw["kind"],
            }
            if action == "rename"
            else {
                "action": action,
                "id": raw["id"],
                "kind": raw["kind"],
            }
        )
    frozen_rows = {
        tuple(sorted(row.items()))
        for row in normalized
    }
    if len(frozen_rows) != len(normalized):
        raise ValueError("changed_objects contains duplicate rows")

    def sort_key(row: Mapping[str, object]) -> tuple[object, ...]:
        action = str(row["action"])
        if action == "rename":
            suffix = (row["old_id"], row["new_id"], row["kind"])
        else:
            suffix = (row["id"], row["kind"])
        return (_CHANGED_ACTION_ORDER[action], *suffix)

    return tuple(sorted(normalized, key=sort_key))


def _receipt_payload(receipt: MutationReceipt) -> dict[str, object]:
    def identities(values: tuple[ObjectIdentity, ...]) -> list[dict[str, str]]:
        return [{"id": item.id, "kind": item.kind} for item in values]

    return {
        "version": receipt.version,
        "receipt_id": receipt.receipt_id,
        "ok": receipt.ok,
        "outcome": receipt.outcome.value,
        "operation": receipt.operation,
        "committed": receipt.committed,
        "transaction_id": receipt.transaction_id,
        "manifest_sha256": receipt.manifest_sha256,
        "coverage_sha256": receipt.coverage_sha256,
        "expected_objects": identities(receipt.expected_objects),
        "verified_objects": identities(receipt.verified_objects),
        "changed_objects": [dict(row) for row in receipt.changed_objects],
        "before_fingerprint": receipt.before_fingerprint,
        "after_fingerprint": receipt.after_fingerprint,
    }


def normalize_mutation_receipt(value: object) -> MutationReceipt:
    """Return the exact canonical receipt after validating all invariants."""
    raw = _receipt_payload(value) if isinstance(value, MutationReceipt) else value
    if not isinstance(raw, Mapping) or set(raw) != _MUTATION_RECEIPT_FIELDS:
        raise ValueError("mutation receipt fields do not match the contract")
    if type(raw.get("version")) is not int or raw.get("version") != 1:
        raise ValueError("mutation receipt version is invalid")
    receipt_id = raw.get("receipt_id")
    if not isinstance(receipt_id, str) or _SHA256.fullmatch(receipt_id) is None:
        raise ValueError("mutation receipt receipt_id is invalid")
    if raw.get("ok") is not True:
        raise ValueError("mutation receipt ok must be true")
    try:
        outcome = MutationOutcome(raw.get("outcome"))
    except (TypeError, ValueError) as exc:
        raise ValueError("mutation receipt outcome is invalid") from exc
    operation = raw.get("operation")
    if not isinstance(operation, str) or not operation:
        raise ValueError("mutation receipt operation is invalid")
    committed = raw.get("committed")
    if not isinstance(committed, bool):
        raise ValueError("mutation receipt committed must be bool")
    transaction_id = raw.get("transaction_id")
    if outcome is MutationOutcome.COMMITTED:
        if committed is not True or not isinstance(transaction_id, str) or (
            _SHA256.fullmatch(transaction_id) is None
        ):
            raise ValueError("committed receipt transaction fields are invalid")
    elif committed is not False or transaction_id is not None:
        raise ValueError("no_changes receipt transaction fields are invalid")
    manifest_sha256 = raw.get("manifest_sha256")
    if (
        not isinstance(manifest_sha256, str)
        or _SHA256.fullmatch(manifest_sha256) is None
    ):
        raise ValueError("mutation receipt manifest_sha256 is invalid")
    coverage_sha256 = raw.get("coverage_sha256")
    if coverage_sha256 is not None and (
        not isinstance(coverage_sha256, str)
        or _SHA256.fullmatch(coverage_sha256) is None
    ):
        raise ValueError("mutation receipt coverage_sha256 is invalid")
    expected_objects = _normalize_object_identities(
        raw.get("expected_objects"),
        field="expected_objects",
    )
    verified_objects = _normalize_object_identities(
        raw.get("verified_objects"),
        field="verified_objects",
    )
    if expected_objects != verified_objects:
        raise ValueError("expected_objects must equal verified_objects")
    changed_objects = _normalize_changed_objects(raw.get("changed_objects"))
    before_fingerprint = raw.get("before_fingerprint")
    after_fingerprint = raw.get("after_fingerprint")
    for field_name, fingerprint in (
        ("before_fingerprint", before_fingerprint),
        ("after_fingerprint", after_fingerprint),
    ):
        if not isinstance(fingerprint, str) or _SHA256.fullmatch(fingerprint) is None:
            raise ValueError(f"mutation receipt {field_name} is invalid")
    if outcome is MutationOutcome.NO_CHANGES and (
        changed_objects or before_fingerprint != after_fingerprint
    ):
        raise ValueError("no_changes receipt state invariants are invalid")
    receipt = MutationReceipt(
        version=1,
        receipt_id=receipt_id,
        ok=True,
        outcome=outcome,
        operation=operation,
        committed=committed,
        transaction_id=transaction_id,
        manifest_sha256=manifest_sha256,
        coverage_sha256=coverage_sha256,
        expected_objects=expected_objects,
        verified_objects=verified_objects,
        changed_objects=changed_objects,
        before_fingerprint=before_fingerprint,
        after_fingerprint=after_fingerprint,
    )
    if receipt_id != _canonical_receipt_identity(_receipt_payload(receipt)):
        raise ValueError("mutation receipt receipt_id does not match its payload")
    return receipt


def _build_mutation_receipt(payload: Mapping[str, object]) -> MutationReceipt:
    expected = _normalize_object_identities(
        payload.get("expected_objects"),
        field="expected_objects",
    )
    verified = _normalize_object_identities(
        payload.get("verified_objects"),
        field="verified_objects",
    )
    with_id = {
        **payload,
        "expected_objects": [
            {"id": item.id, "kind": item.kind} for item in expected
        ],
        "verified_objects": [
            {"id": item.id, "kind": item.kind} for item in verified
        ],
        "changed_objects": [
            dict(row)
            for row in _normalize_changed_objects(payload.get("changed_objects"))
        ],
        "receipt_id": "0" * 64,
    }
    with_id["receipt_id"] = _canonical_receipt_identity(with_id)
    return normalize_mutation_receipt(with_id)


def receipt_from_result(
    result: "MutationPlanResult",
    *,
    committed: bool,
) -> MutationReceipt:
    """Build a canonical receipt from one final ``MutationService.apply`` result."""
    outcome = getattr(result, "outcome", None)
    if outcome not in (MutationOutcome.COMMITTED, MutationOutcome.NO_CHANGES):
        raise ValueError("mutation result outcome is not final")
    expected_committed = outcome is MutationOutcome.COMMITTED
    if not isinstance(committed, bool) or committed != expected_committed:
        raise ValueError("committed flag does not match mutation result outcome")
    if getattr(result, "ok", None) is not True:
        raise ValueError("mutation result is not successful")
    manifest = getattr(result, "manifest", None)
    if manifest is None:
        raise ValueError("mutation result manifest is missing")
    return _build_mutation_receipt({
        "version": 1,
        "ok": True,
        "outcome": outcome.value,
        "operation": manifest.operation,
        "committed": committed,
        "transaction_id": manifest.transaction_id if committed else None,
        "manifest_sha256": result.manifest_sha256,
        "coverage_sha256": manifest.coverage_sha256,
        "expected_objects": list(manifest.expected_objects),
        "verified_objects": list(manifest.verified_objects),
        "changed_objects": list(manifest.changed_objects),
        "before_fingerprint": manifest.before_fingerprint,
        "after_fingerprint": manifest.expected_after_fingerprint,
    })


def mutation_receipt_dict(
    value: MutationReceipt | Mapping[str, object],
) -> dict[str, object]:
    return _receipt_payload(normalize_mutation_receipt(value))


def _normalize_binding_fields(
    raw: Mapping[str, object],
    *,
    binding_type: type[BatchBinding] | type[LegacyBatchBindingV1],
) -> BatchBinding | LegacyBatchBindingV1:
    expected_fields = (
        _BATCH_BINDING_FIELDS
        if binding_type is BatchBinding
        else _LEGACY_BATCH_BINDING_FIELDS
    )
    if set(raw) != expected_fields:
        raise ValueError("batch_binding fields do not match the contract")
    sha_fields = [
        "batch_manifest_sha256",
        "item_input_fingerprint",
        "verify_json_sha256",
        "domain_spec_py_sha256",
    ]
    if binding_type is BatchBinding:
        sha_fields.append("coverage_sha256")
    for field_name in sha_fields:
        value_ = raw.get(field_name)
        if not isinstance(value_, str) or _SHA256.fullmatch(value_) is None:
            raise ValueError(f"batch_binding.{field_name} must be lowercase SHA-256")
    for field_name in ("target_revision_sha", "engine_sha"):
        value_ = raw.get(field_name)
        if not isinstance(value_, str) or _GIT_SHA.fullmatch(value_) is None:
            raise ValueError(f"batch_binding.{field_name} must be an exact Git SHA")
    for field_name in (
        "item_key",
        "expected_repo_id",
        "expected_revision_ref",
    ):
        value_ = raw.get(field_name)
        if (
            not isinstance(value_, str)
            or not value_.strip()
            or "\x00" in value_
        ):
            raise ValueError(f"batch_binding.{field_name} must be non-empty")
    for field_name in ("repo_root", "brain_root", "engine_root"):
        value_ = raw.get(field_name)
        if (
            not isinstance(value_, str)
            or not Path(value_).is_absolute()
            or "\x00" in value_
        ):
            raise ValueError(f"batch_binding.{field_name} must be an absolute path")
    for field_name in ("brain_root_device", "brain_root_inode"):
        value_ = raw.get(field_name)
        if (
            not isinstance(value_, int)
            or isinstance(value_, bool)
            or value_ < 0
        ):
            raise ValueError(f"batch_binding.{field_name} must be a non-negative int")
    return binding_type(**{
        field_name: (
            raw[field_name]
            if field_name in {"brain_root_device", "brain_root_inode"}
            else str(raw[field_name])
        )
        for field_name in binding_type.__dataclass_fields__
    })


def normalize_legacy_batch_binding_v1(
    value: Mapping[str, object],
) -> LegacyBatchBindingV1:
    """Validate the exact historical bytes shape without upgrading it."""
    return _normalize_binding_fields(
        value,
        binding_type=LegacyBatchBindingV1,
    )


def normalize_batch_binding(
    value: (
        BatchBinding
        | LegacyBatchBindingV1
        | Mapping[str, object]
        | None
    ),
    *,
    allow_legacy_v1: bool = False,
) -> BatchBinding | LegacyBatchBindingV1 | None:
    """Return an exact binding; legacy is an explicit recovery-only mode."""
    if value is None:
        return None
    if isinstance(value, BatchBinding):
        raw: Mapping[str, object] = asdict(value)
        binding_type = BatchBinding
    elif isinstance(value, LegacyBatchBindingV1):
        if not allow_legacy_v1:
            raise ValueError("legacy batch_binding requires explicit legacy read mode")
        raw = asdict(value)
        binding_type = LegacyBatchBindingV1
    elif isinstance(value, Mapping):
        raw = value
        if set(raw) == _BATCH_BINDING_FIELDS:
            binding_type = BatchBinding
        elif set(raw) == _LEGACY_BATCH_BINDING_FIELDS:
            if not allow_legacy_v1:
                raise ValueError(
                    "legacy batch_binding requires explicit legacy read mode"
                )
            binding_type = LegacyBatchBindingV1
        else:
            raise ValueError("batch_binding fields do not match the contract")
    else:
        raise ValueError(
            "batch_binding must be BatchBinding, legacy binding, mapping, or None"
        )
    return _normalize_binding_fields(raw, binding_type=binding_type)


def batch_binding_dict(
    value: BatchBinding | LegacyBatchBindingV1 | Mapping[str, object] | None,
    *,
    allow_legacy_v1: bool = False,
) -> dict[str, object] | None:
    normalized = normalize_batch_binding(
        value,
        allow_legacy_v1=allow_legacy_v1,
    )
    return None if normalized is None else asdict(normalized)


def batch_intent_id(
    value: BatchBinding | LegacyBatchBindingV1 | Mapping[str, object],
    *,
    allow_legacy_v1: bool = False,
) -> str:
    """Canonical identity includes batch, item key, and immutable input."""
    binding = normalize_batch_binding(
        value,
        allow_legacy_v1=allow_legacy_v1,
    )
    assert binding is not None
    identity = {
        "batch_manifest_sha256": binding.batch_manifest_sha256,
        "item_key": binding.item_key,
        "item_input_fingerprint": binding.item_input_fingerprint,
    }
    if isinstance(binding, BatchBinding):
        identity["coverage_sha256"] = binding.coverage_sha256
    canonical = json.dumps(
        identity,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def read_batch_binding(path: Path) -> BatchBinding:
    """Read one exact canonical binding through a no-follow file descriptor."""
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError("batch binding path must be absolute")
    descriptor = os.open(
        candidate,
        os.O_RDONLY | os.O_NOFOLLOW,
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("batch binding path must be a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size)
        != (after.st_dev, after.st_ino, after.st_size)
    ):
        raise ValueError("batch binding changed while reading")
    payload = b"".join(chunks)
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"batch binding JSON is invalid: {exc}") from exc
    normalized = normalize_batch_binding(raw)
    assert normalized is not None
    canonical = (
        json.dumps(
            asdict(normalized),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    if canonical != payload:
        raise ValueError("batch binding bytes are not canonical")
    return normalized


def _file_bytes_nofollow(path: Path, *, field: str) -> bytes:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError(f"{field} path must be absolute")
    descriptor = os.open(
        candidate,
        os.O_RDONLY | os.O_NOFOLLOW,
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{field} must be a regular file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        (before.st_dev, before.st_ino, before.st_size)
        != (after.st_dev, after.st_ino, after.st_size)
        or total != before.st_size
    ):
        raise ValueError(f"{field} changed while reading")
    return b"".join(chunks)


def _file_sha256_nofollow(path: Path, *, field: str) -> str:
    return hashlib.sha256(
        _file_bytes_nofollow(path, field=field)
    ).hexdigest()


def verify_batch_input_files(
    binding: BatchBinding | Mapping[str, object],
    *,
    verify_json: Path,
    domain_spec_py: Path,
) -> None:
    """Recheck immutable staged input bytes immediately around mutation."""
    normalized = normalize_batch_binding(binding)
    assert normalized is not None
    domain_spec_payload = _file_bytes_nofollow(
        domain_spec_py,
        field="domain_spec_py",
    )
    observed = {
        "verify_json_sha256": _file_sha256_nofollow(
            verify_json,
            field="verify_json",
        ),
        "domain_spec_py_sha256": hashlib.sha256(
            domain_spec_payload
        ).hexdigest(),
    }
    try:
        from project_brain.coverage import normalize_coverage
        from project_brain.templates.ingest.scripts.assemble_notes import (
            _load_spec_bytes,
        )

        spec = _load_spec_bytes(
            domain_spec_payload,
            filename=str(domain_spec_py),
        )
        coverage = spec.get("COVERAGE")
        if not isinstance(coverage, Mapping):
            raise ValueError("domain_spec_py.COVERAGE is missing")
        observed["coverage_sha256"] = normalize_coverage(coverage).sha256
    except (OSError, ValueError) as exc:
        raise ValueError(f"domain_spec_py coverage is invalid: {exc}") from exc
    for field_name, actual in observed.items():
        if actual != getattr(normalized, field_name):
            raise ValueError(f"{field_name} does not match batch binding")
