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
from typing import Mapping


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_BATCH_BINDING_FIELDS = {
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


class MutationOutcome(StrEnum):
    COMMITTED = "committed"
    NO_CHANGES = "no_changes"


@dataclass(frozen=True)
class BatchBinding:
    """Immutable identity joining one batch item to one mutation."""

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


def normalize_batch_binding(
    value: BatchBinding | Mapping[str, object] | None,
) -> BatchBinding | None:
    """Return an exact validated binding; ``None`` is the non-batch contract."""
    if value is None:
        return None
    if isinstance(value, BatchBinding):
        raw: Mapping[str, object] = asdict(value)
    elif isinstance(value, Mapping):
        raw = value
    else:
        raise ValueError("batch_binding must be BatchBinding, mapping, or None")
    if set(raw) != _BATCH_BINDING_FIELDS:
        raise ValueError("batch_binding fields do not match the contract")
    for field_name in (
        "batch_manifest_sha256",
        "item_input_fingerprint",
        "verify_json_sha256",
        "domain_spec_py_sha256",
    ):
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
    return BatchBinding(**{
        field_name: (
            raw[field_name]
            if field_name in {"brain_root_device", "brain_root_inode"}
            else str(raw[field_name])
        )
        for field_name in BatchBinding.__dataclass_fields__
    })


def batch_binding_dict(
    value: BatchBinding | Mapping[str, object] | None,
) -> dict[str, object] | None:
    normalized = normalize_batch_binding(value)
    return None if normalized is None else asdict(normalized)


def batch_intent_id(
    value: BatchBinding | Mapping[str, object],
) -> str:
    """Canonical identity includes batch, item key, and immutable input."""
    binding = normalize_batch_binding(value)
    assert binding is not None
    identity = {
        "batch_manifest_sha256": binding.batch_manifest_sha256,
        "item_key": binding.item_key,
        "item_input_fingerprint": binding.item_input_fingerprint,
    }
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


def _file_sha256_nofollow(path: Path, *, field: str) -> str:
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
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
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
    return digest.hexdigest()


def verify_batch_input_files(
    binding: BatchBinding | Mapping[str, object],
    *,
    verify_json: Path,
    domain_spec_py: Path,
) -> None:
    """Recheck immutable staged input bytes immediately around mutation."""
    normalized = normalize_batch_binding(binding)
    assert normalized is not None
    observed = {
        "verify_json_sha256": _file_sha256_nofollow(
            verify_json,
            field="verify_json",
        ),
        "domain_spec_py_sha256": _file_sha256_nofollow(
            domain_spec_py,
            field="domain_spec_py",
        ),
    }
    for field_name, actual in observed.items():
        if actual != getattr(normalized, field_name):
            raise ValueError(f"{field_name} does not match batch binding")
