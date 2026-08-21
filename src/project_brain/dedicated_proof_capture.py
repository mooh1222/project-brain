"""원출처 캡처 객체의 dedicated proof profiles."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from project_brain.corpus_io import CorpusIOError, read_tracked_file_bytes
from project_brain.dedicated_proof import (
    DedicatedProof,
    DedicatedProofContext,
    DedicatedProofMaterial,
    DedicatedProofProfile,
    prepare_dedicated_proof,
)
from project_brain.store import BrainStore
from project_brain.write_semantics import ObjectActionKind


def _canonical_source_path(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("capture source_path must be a canonical relative path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or "\\" in value
        or ".." in path.parts
        or path.parts[:2] != ("raw", "sources")
        or len(path.parts) < 3
    ):
        raise ValueError("capture source_path must be below raw/sources")
    return value


def _canonical_locator(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("capture locator must be canonical")
    parsed = urlsplit(value)
    if not parsed.scheme or (not parsed.netloc and not parsed.path):
        raise ValueError("capture locator must include a URI scheme and target")
    return value


def _captured_source(context: DedicatedProofContext) -> tuple[str, str]:
    if context.brain_root is None:
        raise ValueError("capture proof requires brain_root")
    source_path = _canonical_source_path(context.receipt.get("source_path"))
    try:
        payload = read_tracked_file_bytes(context.brain_root, source_path)
    except CorpusIOError as exc:
        raise ValueError(exc.detail) from exc
    return source_path, hashlib.sha256(payload).hexdigest()


def _source_material(
    context: DedicatedProofContext,
    *,
    pointer: str,
    inputs: Mapping[str, object],
) -> DedicatedProofMaterial:
    source_path, source_sha256 = _captured_source(context)
    return DedicatedProofMaterial(
        sources=(
            {
                "pointer": pointer,
                "source_id": source_path,
                "content_sha256": source_sha256,
            },
        ),
        inputs={**inputs, "source_path": source_path},
    )


def _manifest_material(context: DedicatedProofContext) -> DedicatedProofMaterial:
    after = context.after
    locator = _canonical_locator(after.get("locator"))
    acl = after.get("acl")
    if (
        not isinstance(acl, list)
        or not acl
        or not all(isinstance(entry, str) and entry.strip() for entry in acl)
        or len(acl) != len(set(acl))
    ):
        raise ValueError("EvidenceManifest acl must be a non-empty unique string array")
    redaction_status = after.get("redaction_status")
    if redaction_status not in {"raw_local", "staged", "approved"}:
        raise ValueError("EvidenceManifest redaction_status is not capturable")
    return _source_material(
        context,
        pointer="/locator",
        inputs={
            "locator": locator,
            "captured_at": after.get("captured_at"),
            "captured_by": after.get("captured_by"),
            "sensitivity": after.get("sensitivity"),
            "acl": list(acl),
            "redaction_status": redaction_status,
        },
    )


def _spec_document_material(context: DedicatedProofContext) -> DedicatedProofMaterial:
    after = context.after
    return _source_material(
        context,
        pointer="/canonical_locator",
        inputs={
            "source_system": after.get("source_system"),
            "canonical_locator": _canonical_locator(after.get("canonical_locator")),
        },
    )


def _stored_parent(
    context: DedicatedProofContext,
    object_id: object,
    kind: str,
) -> Mapping[str, object]:
    if not isinstance(object_id, str) or not context.store.has(object_id):
        raise ValueError(f"capture parent is missing: {object_id}")
    parent = context.store.get(object_id)
    if parent.get("kind") != kind:
        raise ValueError(f"capture parent must be {kind}: {object_id}")
    return parent


def _spec_revision_material(context: DedicatedProofContext) -> DedicatedProofMaterial:
    after = context.after
    document = _stored_parent(
        context,
        after.get("spec_document_id"),
        "SpecDocument",
    )
    return _source_material(
        context,
        pointer="/spec_document_id",
        inputs={
            "spec_document_id": document["id"],
            "canonical_locator": _canonical_locator(document.get("canonical_locator")),
            "revision_label": after.get("revision_label"),
            "captured_at": after.get("captured_at"),
        },
    )


def _slide_ref_material(context: DedicatedProofContext) -> DedicatedProofMaterial:
    after = context.after
    revision = _stored_parent(
        context,
        after.get("spec_revision_id"),
        "SpecRevision",
    )
    document = _stored_parent(
        context,
        revision.get("spec_document_id"),
        "SpecDocument",
    )
    return _source_material(
        context,
        pointer="/spec_revision_id",
        inputs={
            "spec_revision_id": revision["id"],
            "spec_document_id": document["id"],
            "canonical_locator": _canonical_locator(document.get("canonical_locator")),
            "revision_label": revision.get("revision_label"),
            "slide_no": after.get("slide_no"),
        },
    )


def _slack_thread_material(context: DedicatedProofContext) -> DedicatedProofMaterial:
    after = context.after
    channel_id = after.get("channel_id")
    thread_ts = after.get("thread_ts")
    if not all(
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and "/" not in value
        for value in (channel_id, thread_ts)
    ):
        raise ValueError("SlackThread channel_id and thread_ts must be canonical")
    message_refs = after.get("message_refs")
    if not isinstance(message_refs, list) or not all(
        isinstance(value, str) and bool(value) for value in message_refs
    ):
        raise ValueError("SlackThread message_refs must be a string array")
    canonical_locator = _canonical_locator(f"slack://{channel_id}/{thread_ts}")
    return _source_material(
        context,
        pointer="/thread_ts",
        inputs={
            "canonical_locator": canonical_locator,
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "message_refs": list(message_refs),
        },
    )


EVIDENCE_MANIFEST_CAPTURE_PROFILE = DedicatedProofProfile(
    id="dedicated.evidence-manifest-capture",
    version=1,
    subject_kind="EvidenceManifest",
    selector=lambda _subject: True,
    materialize=_manifest_material,
    receipt_kinds=frozenset({"ingest"}),
)

SPEC_DOCUMENT_CAPTURE_PROFILE = DedicatedProofProfile(
    id="dedicated.spec-document-capture",
    version=1,
    subject_kind="SpecDocument",
    selector=lambda _subject: True,
    materialize=_spec_document_material,
    receipt_kinds=frozenset({"capture"}),
)

SPEC_REVISION_CAPTURE_PROFILE = DedicatedProofProfile(
    id="dedicated.spec-revision-capture",
    version=1,
    subject_kind="SpecRevision",
    selector=lambda _subject: True,
    materialize=_spec_revision_material,
    receipt_kinds=frozenset({"capture"}),
)

SLIDE_REF_CAPTURE_PROFILE = DedicatedProofProfile(
    id="dedicated.slide-ref-capture",
    version=1,
    subject_kind="SlideRef",
    selector=lambda _subject: True,
    materialize=_slide_ref_material,
    receipt_kinds=frozenset({"capture"}),
)

SLACK_THREAD_CAPTURE_PROFILE = DedicatedProofProfile(
    id="dedicated.slack-thread-capture",
    version=1,
    subject_kind="SlackThread",
    selector=lambda _subject: True,
    materialize=_slack_thread_material,
    receipt_kinds=frozenset({"capture"}),
)

CAPTURE_PROFILES = (
    EVIDENCE_MANIFEST_CAPTURE_PROFILE,
    SPEC_DOCUMENT_CAPTURE_PROFILE,
    SPEC_REVISION_CAPTURE_PROFILE,
    SLIDE_REF_CAPTURE_PROFILE,
    SLACK_THREAD_CAPTURE_PROFILE,
)


def prepare_capture_proof(
    after: Mapping[str, object],
    store: BrainStore,
    *,
    brain_root: Path,
    before: Mapping[str, object] | None,
    action: ObjectActionKind,
    source_path: str,
    producer: Mapping[str, str],
    verifiers: Sequence[Mapping[str, str]],
    receipt: Mapping[str, object],
) -> DedicatedProof:
    """현재 raw source를 다시 읽어 reviewed create/update proof를 만든다."""
    canonical_source_path = _canonical_source_path(source_path)
    capture_receipt = dict(receipt)
    stored_source_path = capture_receipt.get("source_path")
    if stored_source_path is not None and stored_source_path != canonical_source_path:
        raise ValueError("capture receipt source_path does not match request")
    capture_receipt["source_path"] = canonical_source_path
    return prepare_dedicated_proof(
        after,
        store,
        brain_root=brain_root,
        before=before,
        action=action,
        producer=producer,
        verifiers=verifiers,
        receipt=capture_receipt,
        profiles=CAPTURE_PROFILES,
    )
