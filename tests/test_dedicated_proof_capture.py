from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest

from project_brain.dedicated_proof_capture import prepare_capture_proof
from project_brain.ingest import IngestError, ingest as product_ingest
from project_brain.mutation import MutationOperation, MutationRequest, MutationService
from project_brain.objbase import base
from project_brain.store import BrainStore
from project_brain.transaction_receipt import receipt_from_result
from project_brain.write_semantics import ObjectActionKind
from tests.coverage_helpers import direct_coverage


T = "2026-08-21T00:00:00+09:00"
T2 = "2026-08-21T00:01:00+09:00"
ENGINE_SHA = "e" * 40
PRODUCER = {"kind": "capture", "id": "source-intake", "version": "1"}


def _manifest(*, locator: str) -> dict:
    return base(
        {
            "id": "manifest.neutral.spec",
            "kind": "EvidenceManifest",
            "status": "reviewed",
            "truth_role": "source",
            "title": "Neutral spec",
            "source_type": "spec",
            "locator": locator,
            "captured_at": T,
            "captured_by": "source-intake",
            "sensitivity": "internal",
            "acl": ["neutral-team"],
            "redaction_status": "approved",
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _spec_document() -> dict:
    return base(
        {
            "id": "spec.neutral-spec",
            "kind": "SpecDocument",
            "status": "reviewed",
            "truth_role": "reference",
            "title": "Neutral spec",
            "source_system": "spec",
            "canonical_locator": "spec://neutral/spec-v1",
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _spec_revision() -> dict:
    return base(
        {
            "id": "revision.neutral-spec.v1",
            "kind": "SpecRevision",
            "status": "reviewed",
            "truth_role": "reference",
            "title": "Neutral spec v1",
            "spec_document_id": "spec.neutral-spec",
            "revision_label": "v1",
            "captured_at": T,
            "slide_refs": [],
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _slide_ref() -> dict:
    return base(
        {
            "id": "slide.neutral-spec.v1.3",
            "kind": "SlideRef",
            "status": "reviewed",
            "truth_role": "reference",
            "title": "Neutral spec slide 3",
            "spec_revision_id": "revision.neutral-spec.v1",
            "slide_no": 3,
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _slack_thread() -> dict:
    return base(
        {
            "id": "slack.neutral.thread",
            "kind": "SlackThread",
            "status": "reviewed",
            "truth_role": "source",
            "title": "Neutral thread",
            "channel_id": "C123",
            "thread_ts": "1710000000.000100",
            "participants": ["U123"],
            "message_refs": ["1710000000.000100", "1710000001.000200"],
            "summary": "Agreed neutral behavior.",
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _write(brain_root: Path, obj: dict) -> None:
    path = BrainStore.object_path(brain_root, obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(BrainStore.object_bytes(obj))


def _request(
    brain_root: Path,
    *objects: dict,
    proofs=(),
) -> MutationRequest:
    inputs = tuple(objects)
    return MutationRequest(
        operation=MutationOperation.INGEST,
        brain_root=brain_root,
        repo_context=None,
        engine_sha=ENGINE_SHA,
        objects=inputs,
        dedicated_proofs=tuple(proofs),
        coverage=direct_coverage(*inputs),
    )


def test_evidence_manifest_reviewed_create_uses_current_source_ingest_proof(
    tmp_path,
):
    brain_root = (tmp_path / "brain").resolve()
    source_path = "raw/sources/neutral/spec-v1.md"
    source_bytes = b"# Neutral spec\n\nCanonical source.\n"
    absolute_source = brain_root / source_path
    absolute_source.parent.mkdir(parents=True)
    absolute_source.write_bytes(source_bytes)
    subject = _manifest(locator="spec://neutral/spec-v1")

    proof = prepare_capture_proof(
        subject,
        BrainStore({}),
        brain_root=brain_root,
        before=None,
        action=ObjectActionKind.CREATE,
        source_path=source_path,
        producer=PRODUCER,
        verifiers=(),
        receipt={
            "kind": "ingest",
            "id": hashlib.sha256(source_bytes).hexdigest(),
        },
    )
    result = product_ingest(
        brain_root,
        (subject,),
        engine_sha=ENGINE_SHA,
        coverage=direct_coverage(subject),
        dedicated_proofs=(proof,),
    )

    assert result.ok is True
    stored = BrainStore.load(brain_root)
    assert "dedicated_proof" not in stored.get(subject["id"])
    assert result.manifest is not None
    assert result.manifest.dedicated_proofs[0]["profile"] == {
        "id": "dedicated.evidence-manifest-capture",
        "version": 1,
    }
    assert stored.by_kind("ReviewRecord") == []


def test_spec_document_reviewed_create_binds_locator_and_capture_receipt(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    source_path = "raw/sources/neutral/spec-v1.md"
    source_bytes = b"# Neutral spec\n"
    absolute_source = brain_root / source_path
    absolute_source.parent.mkdir(parents=True)
    absolute_source.write_bytes(source_bytes)
    subject = _spec_document()

    proof = prepare_capture_proof(
        subject,
        BrainStore({}),
        brain_root=brain_root,
        before=None,
        action=ObjectActionKind.CREATE,
        source_path=source_path,
        producer=PRODUCER,
        verifiers=(),
        receipt={"kind": "capture", "id": hashlib.sha256(source_bytes).hexdigest()},
    )
    result = MutationService().apply(
        (subject,),
        request=_request(brain_root, subject, proofs=(proof,)),
    )

    assert result.ok is True
    assert proof.inputs == {
        "source_system": "spec",
        "canonical_locator": "spec://neutral/spec-v1",
        "source_path": source_path,
    }


def test_spec_revision_binds_parent_document_locator_and_revision(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    source_path = "raw/sources/neutral/spec-v1.md"
    absolute_source = brain_root / source_path
    absolute_source.parent.mkdir(parents=True)
    absolute_source.write_bytes(b"# Neutral spec v1\n")
    document = _spec_document()
    _write(brain_root, document)
    store = BrainStore.load(brain_root)
    subject = _spec_revision()

    proof = prepare_capture_proof(
        subject,
        store,
        brain_root=brain_root,
        before=None,
        action=ObjectActionKind.CREATE,
        source_path=source_path,
        producer=PRODUCER,
        verifiers=(),
        receipt={"kind": "capture", "id": "a" * 64},
    )
    result = MutationService().apply(
        (subject,),
        request=_request(brain_root, subject, proofs=(proof,)),
    )

    assert result.ok is True
    assert proof.inputs == {
        "spec_document_id": document["id"],
        "canonical_locator": document["canonical_locator"],
        "revision_label": "v1",
        "captured_at": T,
        "source_path": source_path,
    }


def test_slide_ref_binds_document_revision_and_slide_number(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    source_path = "raw/sources/neutral/spec-v1.pdf"
    absolute_source = brain_root / source_path
    absolute_source.parent.mkdir(parents=True)
    absolute_source.write_bytes(b"%PDF-neutral")
    document = _spec_document()
    revision = _spec_revision()
    for obj in (document, revision):
        _write(brain_root, obj)
    store = BrainStore.load(brain_root)
    subject = _slide_ref()

    proof = prepare_capture_proof(
        subject,
        store,
        brain_root=brain_root,
        before=None,
        action=ObjectActionKind.CREATE,
        source_path=source_path,
        producer=PRODUCER,
        verifiers=(),
        receipt={"kind": "capture", "id": "b" * 64},
    )
    result = MutationService().apply(
        (subject,),
        request=_request(brain_root, subject, proofs=(proof,)),
    )

    assert result.ok is True
    assert proof.inputs == {
        "spec_revision_id": revision["id"],
        "spec_document_id": document["id"],
        "canonical_locator": document["canonical_locator"],
        "revision_label": revision["revision_label"],
        "slide_no": 3,
        "source_path": source_path,
    }


def test_slack_thread_binds_canonical_thread_locator_and_capture(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    source_path = "raw/sources/neutral/slack-thread.json"
    absolute_source = brain_root / source_path
    absolute_source.parent.mkdir(parents=True)
    absolute_source.write_bytes(b'{"thread_ts":"1710000000.000100"}\n')
    subject = _slack_thread()

    proof = prepare_capture_proof(
        subject,
        BrainStore({}),
        brain_root=brain_root,
        before=None,
        action=ObjectActionKind.CREATE,
        source_path=source_path,
        producer=PRODUCER,
        verifiers=(),
        receipt={"kind": "capture", "id": "c" * 64},
    )
    result = MutationService().apply(
        (subject,),
        request=_request(brain_root, subject, proofs=(proof,)),
    )

    assert result.ok is True
    assert proof.inputs == {
        "canonical_locator": "slack://C123/1710000000.000100",
        "channel_id": "C123",
        "thread_ts": "1710000000.000100",
        "message_refs": ["1710000000.000100", "1710000001.000200"],
        "source_path": source_path,
    }


@pytest.mark.parametrize(
    "factory",
    [_manifest, _spec_document, _spec_revision, _slide_ref, _slack_thread],
)
def test_capture_kinds_forbid_new_candidates(tmp_path, factory):
    brain_root = (tmp_path / "brain").resolve()
    subject = (
        factory(locator="spec://neutral/spec-v1")
        if factory is _manifest
        else factory()
    )
    subject["status"] = "candidate"

    result = MutationService().apply(
        (subject,),
        request=_request(brain_root, subject),
    )

    assert (result.ok, result.error_code) == (
        False,
        "dedicated_candidate_forbidden",
    )
    assert not BrainStore.object_path(brain_root, subject).exists()


@pytest.mark.parametrize(
    "operation",
    [MutationOperation.PROMOTE, MutationOperation.PROMOTE_AUTO],
)
def test_capture_kinds_forbid_manual_and_automatic_promotion(tmp_path, operation):
    brain_root = (tmp_path / "brain").resolve()
    candidate = _manifest(locator="spec://neutral/spec-v1")
    candidate["status"] = "candidate"
    _write(brain_root, candidate)
    reviewed = _manifest(locator="spec://neutral/spec-v1")

    result = MutationService().apply(
        (reviewed,),
        request=MutationRequest(
            operation=operation,
            brain_root=brain_root,
            repo_context=None,
            engine_sha=ENGINE_SHA,
            objects=(reviewed,),
        ),
    )

    assert (result.ok, result.error_code) == (
        False,
        "dedicated_promotion_forbidden",
    )
    assert BrainStore.load(brain_root).get(candidate["id"])["status"] == "candidate"


def test_missing_or_stale_capture_proof_is_zero_write_including_index(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    source_path = "raw/sources/neutral/spec-v1.md"
    absolute_source = brain_root / source_path
    absolute_source.parent.mkdir(parents=True)
    absolute_source.write_bytes(b"v1\n")
    index_path = brain_root / ".brain-local/index.db"
    index_path.parent.mkdir(parents=True)
    index_path.write_bytes(b"index-before")
    subject = _manifest(locator="spec://neutral/spec-v1")

    with pytest.raises(IngestError) as missing:
        product_ingest(
            brain_root,
            (subject,),
            engine_sha=ENGINE_SHA,
            coverage=direct_coverage(subject),
        )
    assert missing.value.code == "dedicated_proof_missing"

    proof = prepare_capture_proof(
        subject,
        BrainStore({}),
        brain_root=brain_root,
        before=None,
        action=ObjectActionKind.CREATE,
        source_path=source_path,
        producer=PRODUCER,
        verifiers=(),
        receipt={"kind": "ingest", "id": "d" * 64},
    )
    absolute_source.write_bytes(b"v2\n")
    stale = MutationService().apply(
        (subject,),
        request=_request(brain_root, subject, proofs=(proof,)),
    )

    assert (stale.ok, stale.error_code) == (
        False,
        "dedicated_proof_not_ready",
    )
    assert not BrainStore.object_path(brain_root, subject).exists()
    assert index_path.read_bytes() == b"index-before"
    assert BrainStore.load(brain_root).by_kind("ReviewRecord") == []


@pytest.mark.parametrize(
    ("mutator", "receipt_kind"),
    [
        (lambda obj: obj.update(locator="raw/sources/spec.md"), "ingest"),
        (lambda obj: obj.update(acl=[]), "ingest"),
        (lambda obj: obj.update(redaction_status="rejected"), "ingest"),
        (lambda _obj: None, "capture"),
    ],
)
def test_manifest_capture_rejects_invalid_locator_acl_redaction_or_receipt(
    tmp_path,
    mutator,
    receipt_kind,
):
    brain_root = (tmp_path / "brain").resolve()
    source_path = "raw/sources/neutral/spec-v1.md"
    absolute_source = brain_root / source_path
    absolute_source.parent.mkdir(parents=True)
    absolute_source.write_bytes(b"v1\n")
    subject = _manifest(locator="spec://neutral/spec-v1")
    mutator(subject)

    with pytest.raises(ValueError):
        prepare_capture_proof(
            subject,
            BrainStore({}),
            brain_root=brain_root,
            before=None,
            action=ObjectActionKind.CREATE,
            source_path=source_path,
            producer=PRODUCER,
            verifiers=(),
            receipt={"kind": receipt_kind, "id": "e" * 64},
        )


def test_legacy_reviewed_noop_reads_but_first_meaning_update_requires_proof(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    source_path = "raw/sources/neutral/spec-v1.md"
    absolute_source = brain_root / source_path
    absolute_source.parent.mkdir(parents=True)
    absolute_source.write_bytes(b"v1\n")
    legacy = _manifest(locator="spec://neutral/spec-v1")
    _write(brain_root, legacy)
    service = MutationService()

    noop = service.apply(
        (legacy,),
        request=_request(brain_root, legacy),
    )
    assert noop.ok is True

    changed = deepcopy(legacy)
    changed["locator"] = "spec://neutral/spec-v1-recaptured"
    changed["updated_at"] = T2
    missing = service.apply(
        (changed,),
        request=_request(brain_root, changed),
    )
    assert (missing.ok, missing.error_code) == (False, "dedicated_proof_missing")
    assert BrainStore.load(brain_root).get(legacy["id"]) == legacy

    store = BrainStore.load(brain_root)
    proof = prepare_capture_proof(
        changed,
        store,
        brain_root=brain_root,
        before=legacy,
        action=ObjectActionKind.UPDATE,
        source_path=source_path,
        producer=PRODUCER,
        verifiers=(),
        receipt={"kind": "ingest", "id": "f" * 64},
    )
    updated = service.apply(
        (changed,),
        request=_request(brain_root, changed, proofs=(proof,)),
    )

    assert updated.ok is True
    assert BrainStore.load(brain_root).get(legacy["id"])["locator"] == changed["locator"]
    assert BrainStore.load(brain_root).by_kind("ReviewRecord") == []
    receipt = receipt_from_result(updated, committed=True)
    assert [dict(row) for row in receipt.changed_objects] == [
        {"action": "update", "id": legacy["id"], "kind": "EvidenceManifest"}
    ]


def test_spec_revision_rejects_parent_locator_drift_before_write(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    source_path = "raw/sources/neutral/spec-v1.md"
    absolute_source = brain_root / source_path
    absolute_source.parent.mkdir(parents=True)
    absolute_source.write_bytes(b"v1\n")
    document = _spec_document()
    _write(brain_root, document)
    subject = _spec_revision()
    proof = prepare_capture_proof(
        subject,
        BrainStore.load(brain_root),
        brain_root=brain_root,
        before=None,
        action=ObjectActionKind.CREATE,
        source_path=source_path,
        producer=PRODUCER,
        verifiers=(),
        receipt={"kind": "capture", "id": "1" * 64},
    )
    changed_document = deepcopy(document)
    changed_document["canonical_locator"] = "spec://neutral/spec-v2"
    changed_document["updated_at"] = T2
    _write(brain_root, changed_document)

    result = MutationService().apply(
        (subject,),
        request=_request(brain_root, subject, proofs=(proof,)),
    )

    assert (result.ok, result.error_code) == (
        False,
        "dedicated_proof_not_ready",
    )
    assert not BrainStore.object_path(brain_root, subject).exists()


def test_spec_document_requires_capture_receipt_kind(tmp_path):
    brain_root = (tmp_path / "brain").resolve()
    source_path = "raw/sources/neutral/spec-v1.md"
    absolute_source = brain_root / source_path
    absolute_source.parent.mkdir(parents=True)
    absolute_source.write_bytes(b"v1\n")

    with pytest.raises(ValueError):
        prepare_capture_proof(
            _spec_document(),
            BrainStore({}),
            brain_root=brain_root,
            before=None,
            action=ObjectActionKind.CREATE,
            source_path=source_path,
            producer=PRODUCER,
            verifiers=(),
            receipt={"kind": "ingest", "id": "2" * 64},
        )
