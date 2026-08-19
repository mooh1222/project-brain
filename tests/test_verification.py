import hashlib
from copy import deepcopy

import pytest

import project_brain.verification as verification_module
from project_brain.corpus_io import (
    corpus_lock,
    recover_unfinished_transaction_unlocked,
)
from project_brain.mutation import (
    MutationOperation,
    MutationRequest,
    MutationService,
    corpus_fingerprint,
)
from project_brain.objbase import base
from project_brain.promote import promote
from project_brain.schema import validate_mutation_input_schema, validate_object
from project_brain.store import BrainStore
from project_brain.verification import (
    evaluate_candidate_verification,
    prepare_candidate_verification,
)
from tests.coverage_helpers import direct_coverage
from tests.test_ingest import T, manifest


def candidate_evidence_ref(*, candidate=None):
    payload = {
        "id": "evref.neutral.candidate",
        "kind": "EvidenceRef",
        "status": "candidate",
        "truth_role": "reference",
        "title": "후보 근거",
        "evidence_manifest_id": "manifest.neutral.source",
        "ref_type": "spec_section",
        "locator": {"section": "1"},
        "summary": "검증할 인용",
    }
    if candidate is not None:
        payload["candidate"] = candidate
    return base(payload, tags=["neutral"], created_at=T, updated_at=T)


def test_legacy_candidate_without_verification_is_unverified():
    subject = candidate_evidence_ref()
    store = BrainStore({
        "manifest.neutral.source": manifest(),
        subject["id"]: subject,
    })

    result = evaluate_candidate_verification(subject, store)

    assert result.verification_status == "unverified"
    assert result.reason_codes == ("verification_missing",)


def _candidate_metadata():
    return {
        "candidate_state": "evidence_verified",
        "candidate_source": "spec",
        "proposed_by": "agent:extractor",
        "proposed_at": T,
        "open_questions": [],
    }


def _caller_checks():
    return [
        {
            "id": "common.content-supported",
            "outcome": "pass",
            "authority": "agent",
            "summary": "인용 내용이 manifest 원문과 맞는다.",
        },
        {
            "id": "common.kind-fit",
            "outcome": "pass",
            "authority": "agent",
            "summary": "이 대상은 원문 일부를 가리키는 EvidenceRef다.",
        },
        {
            "id": "common.questions-resolved",
            "outcome": "pass",
            "authority": "agent",
            "summary": "남은 질문이 없다.",
        },
    ]


def test_prepare_candidate_verification_builds_exact_ready_v1_envelope():
    subject = candidate_evidence_ref(candidate=_candidate_metadata())
    store = BrainStore({
        "manifest.neutral.source": manifest(),
        subject["id"]: subject,
    })

    prepared = prepare_candidate_verification(
        subject,
        store,
        checks=_caller_checks(),
        engine_sha="e" * 40,
        executed_at=T,
        producer={"kind": "agent", "id": "agent:extractor", "version": "1"},
        verifiers=[{"kind": "agent", "id": "agent:reviewer", "version": "1"}],
    )

    assert prepared["status"] == "candidate"
    envelope = prepared["candidate"]["verification"]
    assert set(envelope) == {"version", "profile", "bindings", "checks", "execution"}
    assert envelope["profile"] == {"id": "verification.evidence-ref", "version": 1}
    assert set(envelope["bindings"]) == {
        "content_sha256",
        "evidence_sha256",
        "rules_sha256",
        "execution_sha256",
    }
    assert all(len(value) == 64 for value in envelope["bindings"].values())
    prepared_store = BrainStore({
        "manifest.neutral.source": manifest(),
        prepared["id"]: prepared,
    })
    evaluation = evaluate_candidate_verification(prepared, prepared_store)
    assert evaluation.verification_status == "ready"
    assert evaluation.reason_codes == ()


def _prepared_subject(*, candidate=None, checks=None):
    subject = candidate_evidence_ref(
        candidate=candidate if candidate is not None else _candidate_metadata()
    )
    store = BrainStore({
        "manifest.neutral.source": manifest(),
        subject["id"]: subject,
    })
    prepared = prepare_candidate_verification(
        subject,
        store,
        checks=checks if checks is not None else _caller_checks(),
        engine_sha="e" * 40,
        executed_at=T,
        producer={"kind": "agent", "id": "agent:extractor", "version": "1"},
        verifiers=[{"kind": "agent", "id": "agent:reviewer", "version": "1"}],
    )
    return prepared, store.get("manifest.neutral.source")


def test_status_recomputes_content_evidence_rules_and_execution_bindings(monkeypatch):
    prepared, current_manifest = _prepared_subject()

    content_changed = dict(prepared)
    content_changed["summary"] = "바뀐 인용"
    content_store = BrainStore({prepared["id"]: content_changed, current_manifest["id"]: current_manifest})
    assert evaluate_candidate_verification(content_changed, content_store).reason_codes == (
        "content_changed",
    )

    changed_manifest = dict(current_manifest)
    changed_manifest["title"] = "바뀐 원출처"
    evidence_store = BrainStore({prepared["id"]: prepared, changed_manifest["id"]: changed_manifest})
    assert evaluate_candidate_verification(prepared, evidence_store).reason_codes == (
        "evidence_changed",
    )

    old_rules = "0" * 64
    monkeypatch.setattr(verification_module, "_rules_sha256", lambda: old_rules)
    old_prepared, _ = _prepared_subject()
    monkeypatch.undo()
    rules_store = BrainStore({prepared["id"]: old_prepared, current_manifest["id"]: current_manifest})
    assert evaluate_candidate_verification(old_prepared, rules_store).reason_codes == (
        "rules_changed",
    )

    execution_changed = dict(prepared)
    execution_changed["candidate"] = dict(prepared["candidate"])
    execution_changed["candidate"]["verification"] = dict(
        prepared["candidate"]["verification"]
    )
    execution_changed["candidate"]["verification"]["execution"] = dict(
        prepared["candidate"]["verification"]["execution"]
    )
    execution_changed["candidate"]["verification"]["execution"]["executed_at"] = (
        "2026-06-05T00:00:00Z"
    )
    execution_store = BrainStore({
        execution_changed["id"]: execution_changed,
        current_manifest["id"]: current_manifest,
    })
    evaluation = evaluate_candidate_verification(execution_changed, execution_store)
    assert evaluation.verification_status == "blocked"
    assert evaluation.reason_codes == ("execution_invalid",)


def test_multiple_reasons_use_the_specified_fixed_order():
    candidate = _candidate_metadata()
    candidate["candidate_state"] = "conflict"
    candidate["open_questions"] = ["어느 인용을 쓸까?"]
    checks = _caller_checks()
    checks[0]["outcome"] = "fail"
    checks[2]["outcome"] = "needs_human"
    prepared, current_manifest = _prepared_subject(candidate=candidate, checks=checks)
    store = BrainStore({prepared["id"]: prepared, current_manifest["id"]: current_manifest})

    evaluation = evaluate_candidate_verification(prepared, store)

    assert evaluation.verification_status == "blocked"
    assert evaluation.reason_codes == (
        "candidate_conflict",
        "check_failed",
        "human_required",
        "open_questions",
    )


def test_schema_accepts_legacy_but_rejects_malformed_present_envelope():
    legacy = candidate_evidence_ref()
    assert validate_object(legacy) == []
    prepared, _ = _prepared_subject()
    assert validate_object(prepared) == []

    malformed = dict(prepared)
    malformed["candidate"] = dict(prepared["candidate"])
    malformed["candidate"]["verification"] = dict(
        prepared["candidate"]["verification"]
    )
    malformed["candidate"]["verification"]["ready"] = True

    assert any(
        "verification top-level keys must be exact" in error
        for error in validate_object(malformed)
    )


def test_prepare_rejects_authority_outside_the_profile():
    checks = _caller_checks()
    checks[1]["authority"] = "human"
    subject = candidate_evidence_ref(candidate=_candidate_metadata())
    store = BrainStore({subject["id"]: subject, manifest()["id"]: manifest()})

    try:
        prepare_candidate_verification(
            subject,
            store,
            checks=checks,
            engine_sha="e" * 40,
            executed_at=T,
            producer={"kind": "agent", "id": "agent:extractor", "version": "1"},
            verifiers=[],
        )
    except ValueError as exc:
        assert "authority" in str(exc)
    else:
        raise AssertionError("invalid authority was accepted")


def test_manual_promotion_moves_verification_to_initial_review_record():
    prepared, current_manifest = _prepared_subject()
    store = BrainStore({prepared["id"]: prepared, current_manifest["id"]: current_manifest})

    promoted, records = promote(
        [prepared],
        [prepared["id"]],
        "single_object",
        reviewer="human:owner",
        reviewed_at=T,
        store=store,
    )

    assert promoted[0]["status"] == "reviewed"
    assert "candidate" not in promoted[0]
    assert records[0]["verification"] == prepared["candidate"]["verification"]
    assert records[0]["verification_origin"] == "candidate_promotion"
    assert records[0]["verification_history"] == []
    assert validate_mutation_input_schema(
        records[0],
        omitted_required_fields=frozenset({"created_at", "updated_at"}),
    ) == []


def test_legacy_evidence_ref_candidate_cannot_be_promoted():
    subject = candidate_evidence_ref()
    store = BrainStore({subject["id"]: subject, manifest()["id"]: manifest()})

    with pytest.raises(ValueError, match="verification_missing"):
        promote(
            [subject],
            [subject["id"]],
            "single_object",
            reviewer="human:owner",
            reviewed_at=T,
            store=store,
        )


def _save_promotion_store(brain_root, prepared, current_manifest):
    BrainStore.save_object(brain_root, current_manifest)
    BrainStore.save_object(brain_root, prepared)


def _promotion_request(brain_root, prepared, promoted, records):
    store = BrainStore.load(brain_root)
    return MutationRequest(
        operation=MutationOperation.PROMOTE,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=tuple(promoted + records),
        preconditions={
            prepared["id"]: hashlib.sha256(BrainStore.object_bytes(
                store.get(prepared["id"])
            )).hexdigest(),
        },
        expected_corpus_fingerprint=corpus_fingerprint(store),
    )


def test_mutation_revalidates_verification_inside_the_live_store_lock(tmp_path):
    prepared, current_manifest = _prepared_subject()
    original_store = BrainStore({
        prepared["id"]: prepared,
        current_manifest["id"]: current_manifest,
    })
    promoted, records = promote(
        [prepared], [prepared["id"]], "single_object",
        reviewer="human:owner", reviewed_at=T, store=original_store,
    )
    changed_manifest = dict(current_manifest)
    changed_manifest["title"] = "승격 직전 바뀐 원출처"
    _save_promotion_store(tmp_path, prepared, changed_manifest)
    index_path = tmp_path / ".brain-local" / "index.db"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(b"existing-index")
    request = _promotion_request(tmp_path, prepared, promoted, records)

    result = MutationService().apply(request.objects, request=request)

    assert (result.ok, result.error_code) == (False, "verification_not_ready")
    stored = BrainStore.load(tmp_path)
    assert stored.get(prepared["id"])["status"] == "candidate"
    assert not stored.has(records[0]["id"])
    assert index_path.read_bytes() == b"existing-index"
    assert not (tmp_path / ".brain-local" / "batch-intents").exists()
    assert not (tmp_path / ".brain-local" / "transactions").exists()
    assert not (tmp_path / ".brain-local" / "preparing-transactions").exists()


def test_promotion_apply_failure_recovers_target_and_review_record_together(tmp_path):
    prepared, current_manifest = _prepared_subject()
    _save_promotion_store(tmp_path, prepared, current_manifest)
    store = BrainStore.load(tmp_path)
    promoted, records = promote(
        [prepared], [prepared["id"]], "single_object",
        reviewer="human:owner", reviewed_at=T, store=store,
    )
    index_path = tmp_path / ".brain-local" / "index.db"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(b"existing-index")
    request = _promotion_request(tmp_path, prepared, promoted, records)

    class InjectedCrash(RuntimeError):
        pass

    def crash_after_first_replace(stage):
        if stage == "after_first_live_replace":
            raise InjectedCrash(stage)

    with pytest.raises(InjectedCrash):
        MutationService(clock=lambda: "2026-08-20T02:30:00+09:00").apply(
            request.objects,
            request=request,
            failure_injector=crash_after_first_replace,
        )

    with corpus_lock(tmp_path, exclusive=True):
        recover_unfinished_transaction_unlocked(tmp_path)
    recovered = BrainStore.load(tmp_path)
    assert recovered.get(prepared["id"]) == prepared
    assert not recovered.has(records[0]["id"])
    assert index_path.read_bytes() == b"existing-index"
    assert not (tmp_path / ".brain-local" / "batch-intents").exists()


def _candidate_update_request(brain_root, before, after):
    return MutationRequest(
        operation=MutationOperation.INGEST,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=(after,),
        preconditions={
            before["id"]: hashlib.sha256(BrainStore.object_bytes(before)).hexdigest(),
        },
        coverage=direct_coverage(after),
    )


def test_candidate_meaning_change_requires_fresh_envelope_or_removal(tmp_path):
    prepared, current_manifest = _prepared_subject()
    _save_promotion_store(tmp_path, prepared, current_manifest)
    stale = dict(prepared)
    stale["summary"] = "검증 뒤 바뀐 인용"
    stale_request = _candidate_update_request(tmp_path, prepared, stale)

    rejected = MutationService().apply(stale_request.objects, request=stale_request)

    assert (rejected.ok, rejected.error_code) == (False, "verification_not_ready")
    assert BrainStore.load(tmp_path).get(prepared["id"]) == prepared

    unverified = dict(stale)
    unverified["candidate"] = dict(stale["candidate"])
    unverified["candidate"].pop("verification")
    removal_request = _candidate_update_request(tmp_path, prepared, unverified)
    applied = MutationService(clock=lambda: "2026-08-20T02:30:00+09:00").apply(
        removal_request.objects,
        request=removal_request,
    )

    assert applied.ok
    stored = BrainStore.load(tmp_path).get(prepared["id"])
    assert stored["summary"] == "검증 뒤 바뀐 인용"
    assert "verification" not in stored["candidate"]


@pytest.mark.parametrize(
    ("mutate", "expected_status", "expected_reasons"),
    [
        (
            lambda envelope: envelope.__setitem__("version", 2),
            "stale",
            ("unsupported_version",),
        ),
        (
            lambda envelope: envelope["profile"].__setitem__(
                "id", "verification.other"
            ),
            "stale",
            ("profile_mismatch",),
        ),
    ],
)
def test_unsupported_version_and_profile_mismatch_are_stale(
    mutate,
    expected_status,
    expected_reasons,
):
    prepared, current_manifest = _prepared_subject()
    changed = deepcopy(prepared)
    mutate(changed["candidate"]["verification"])
    store = BrainStore({changed["id"]: changed, current_manifest["id"]: current_manifest})

    evaluation = evaluate_candidate_verification(changed, store)

    assert evaluation.verification_status == expected_status
    assert evaluation.reason_codes == expected_reasons


def test_invalid_review_shape_is_blocked():
    subject = candidate_evidence_ref(candidate=_candidate_metadata())
    subject["id"] = "not-a-canonical-id"
    store = BrainStore({subject["id"]: subject, manifest()["id"]: manifest()})
    prepared = prepare_candidate_verification(
        subject,
        store,
        checks=_caller_checks(),
        engine_sha="e" * 40,
        executed_at=T,
        producer={"kind": "agent", "id": "agent:extractor", "version": "1"},
        verifiers=[],
    )
    prepared_store = BrainStore({
        prepared["id"]: prepared,
        manifest()["id"]: manifest(),
    })

    evaluation = evaluate_candidate_verification(prepared, prepared_store)

    assert evaluation.verification_status == "blocked"
    assert evaluation.reason_codes == ("review_shape_invalid",)


def test_prepared_envelope_is_stored_through_the_public_mutation_path(tmp_path):
    legacy = candidate_evidence_ref(candidate=_candidate_metadata())
    _save_promotion_store(tmp_path, legacy, manifest())
    store = BrainStore.load(tmp_path)
    prepared = prepare_candidate_verification(
        legacy,
        store,
        checks=_caller_checks(),
        engine_sha="e" * 40,
        executed_at=T,
        producer={"kind": "agent", "id": "agent:extractor", "version": "1"},
        verifiers=[],
    )
    request = _candidate_update_request(tmp_path, legacy, prepared)

    result = MutationService(clock=lambda: "2026-08-20T02:30:00+09:00").apply(
        request.objects,
        request=request,
    )

    assert result.ok
    stored = BrainStore.load(tmp_path).get(prepared["id"])
    assert stored["status"] == "candidate"
    assert stored["candidate"]["verification"] == prepared["candidate"]["verification"]


def test_successful_mutation_commits_reviewed_target_and_review_record(tmp_path):
    prepared, current_manifest = _prepared_subject()
    _save_promotion_store(tmp_path, prepared, current_manifest)
    store = BrainStore.load(tmp_path)
    promoted, records = promote(
        [prepared], [prepared["id"]], "single_object",
        reviewer="human:owner", reviewed_at=T, store=store,
    )
    request = _promotion_request(tmp_path, prepared, promoted, records)

    result = MutationService(clock=lambda: "2026-08-20T02:30:00+09:00").apply(
        request.objects,
        request=request,
    )

    assert result.ok
    stored = BrainStore.load(tmp_path)
    reviewed = stored.get(prepared["id"])
    record = stored.get(records[0]["id"])
    assert reviewed["status"] == "reviewed"
    assert record["target_object_id"] == reviewed["id"]
    assert record["verification"]["bindings"]["content_sha256"] == (
        prepared["candidate"]["verification"]["bindings"]["content_sha256"]
    )
    assert record["verification"]["bindings"]["evidence_sha256"] == (
        prepared["candidate"]["verification"]["bindings"]["evidence_sha256"]
    )
