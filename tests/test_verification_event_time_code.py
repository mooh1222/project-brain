import hashlib
import subprocess
from copy import deepcopy

import pytest

from project_brain.mutation import (
    MutationOperation,
    MutationRequest,
    MutationService,
    corpus_fingerprint,
)
from project_brain.objbase import base
from project_brain.promote import promote
from project_brain.repo_context import resolve_repo_context
from project_brain.store import BrainStore
from project_brain.verification import (
    evaluate_candidate_verification,
    prepare_candidate_verification,
)
from tests.coverage_helpers import direct_coverage
from tests.test_ingest import T, evidence_ref, manifest


ENGINE_SHA = "e" * 40
PRODUCER = {"kind": "agent", "id": "agent:extractor", "version": "1"}


def _candidate_metadata():
    return {
        "candidate_state": "evidence_verified",
        "candidate_source": "spec",
        "proposed_by": PRODUCER["id"],
        "proposed_at": T,
        "open_questions": [],
    }


def _event_candidate():
    return base(
        {
            "id": "ledger.neutral.release",
            "kind": "EventLedgerRecord",
            "status": "candidate",
            "truth_role": "event",
            "title": "중립 릴리스 사건",
            "event_type": "release",
            "happened_at": "2026-06-03T12:00:00+09:00",
            "summary": "중립 릴리스가 배포됐다.",
            "related_objects": [],
            "evidence_refs": ["evref.neutral.ref"],
            "candidate": _candidate_metadata(),
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _event_checks():
    return [
        {
            "id": "common.content-supported",
            "outcome": "pass",
            "authority": "agent",
            "summary": "사건 설명이 직접 근거에 의해 뒷받침된다.",
        },
        {
            "id": "common.kind-fit",
            "outcome": "pass",
            "authority": "agent",
            "summary": "대상은 발생 시각이 있는 사건 기록이다.",
        },
        {
            "id": "common.questions-resolved",
            "outcome": "pass",
            "authority": "agent",
            "summary": "남은 질문이 없다.",
        },
        {
            "id": "event.source-support",
            "outcome": "pass",
            "authority": "agent",
            "summary": "출처가 사건 발생을 직접 뒷받침한다.",
        },
        {
            "id": "event.correction-policy",
            "outcome": "pass",
            "authority": "agent",
            "summary": "정정은 후속 사건으로 남기는 정책을 따른다.",
        },
    ]


def _temporal_candidate(event_id):
    return base(
        {
            "id": "fact.neutral.release-state",
            "kind": "TemporalFact",
            "status": "candidate",
            "truth_role": "fact",
            "title": "중립 릴리스 상태",
            "subject": "release.neutral",
            "predicate": "state",
            "value": "deployed",
            "scope": {"environment": "test"},
            "valid_from": "2026-06-03T12:00:00+09:00",
            "derived_from_event_id": event_id,
            "confidence": "high",
            "evidence_refs": ["evref.neutral.ref"],
            "candidate": _candidate_metadata(),
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _temporal_checks():
    return [
        {
            "id": "common.content-supported",
            "outcome": "pass",
            "authority": "agent",
            "summary": "시간 사실이 원인 사건과 직접 근거에 의해 뒷받침된다.",
        },
        {
            "id": "common.kind-fit",
            "outcome": "pass",
            "authority": "agent",
            "summary": "대상은 유효 기간을 가진 시간 사실이다.",
        },
        {
            "id": "common.questions-resolved",
            "outcome": "pass",
            "authority": "agent",
            "summary": "남은 질문이 없다.",
        },
        {
            "id": "fact.time-scope-valid",
            "outcome": "pass",
            "authority": "agent",
            "summary": "유효 시작과 종료 범위가 모순되지 않는다.",
        },
    ]


def _common_agent_checks(kind_summary):
    return [
        {
            "id": "common.content-supported",
            "outcome": "pass",
            "authority": "agent",
            "summary": "내용이 직접 근거에 의해 뒷받침된다.",
        },
        {
            "id": "common.kind-fit",
            "outcome": "pass",
            "authority": "agent",
            "summary": kind_summary,
        },
        {
            "id": "common.questions-resolved",
            "outcome": "pass",
            "authority": "agent",
            "summary": "남은 질문이 없다.",
        },
    ]


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repo, check=True
    )
    (repo / "Foo.cpp").write_text("void Foo::bar() {}\n", encoding="utf-8")
    subprocess.run(["git", "add", "Foo.cpp"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    context = resolve_repo_context(
        repo.resolve(),
        expected_repo_id="demo",
        configured_repo_id="demo",
        expected_revision_ref=sha,
    )
    return repo, context, sha


def _code_candidate(commit_sha):
    return base(
        {
            "id": "code.neutral.answer",
            "kind": "CodeLocator",
            "status": "candidate",
            "truth_role": "reference",
            "title": "Foo.cpp: Foo::bar",
            "repo": "demo",
            "path": "Foo.cpp",
            "symbol": "Foo::bar",
            "commit_sha": commit_sha,
            "verified_quote": "void Foo::bar() {}",
            "locator_source": "rg",
            "verified_at": T,
            "evidence_refs": ["evref.neutral.ref"],
            "candidate": _candidate_metadata(),
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _candidate_update_request(brain_root, before, after, *, repo_context=None):
    return MutationRequest(
        operation=MutationOperation.INGEST,
        brain_root=brain_root,
        repo_context=repo_context,
        engine_sha=ENGINE_SHA,
        objects=(after,),
        preconditions={
            before["id"]: hashlib.sha256(BrainStore.object_bytes(before)).hexdigest(),
        },
        coverage=direct_coverage(after),
    )


def _promotion_request(brain_root, before, promoted, records, *, repo_context=None):
    store = BrainStore.load(brain_root)
    return MutationRequest(
        operation=MutationOperation.PROMOTE,
        brain_root=brain_root,
        repo_context=repo_context,
        engine_sha=ENGINE_SHA,
        objects=tuple(promoted + records),
        preconditions={
            before["id"]: hashlib.sha256(
                BrainStore.object_bytes(store.get(before["id"]))
            ).hexdigest(),
        },
        expected_corpus_fingerprint=corpus_fingerprint(store),
    )


def test_event_candidate_runs_through_public_prepare_and_promotion(tmp_path):
    source_manifest = manifest()
    source_ref = evidence_ref()
    legacy = _event_candidate()
    for obj in (source_manifest, source_ref, legacy):
        BrainStore.save_object(tmp_path, obj)
    store = BrainStore.load(tmp_path)

    prepared = prepare_candidate_verification(
        legacy,
        store,
        checks=_event_checks(),
        engine_sha=ENGINE_SHA,
        executed_at=T,
        producer=PRODUCER,
        verifiers=[],
    )

    envelope = prepared["candidate"]["verification"]
    assert envelope["profile"] == {
        "id": "verification.event-ledger-record",
        "version": 1,
    }
    assert [check["id"] for check in envelope["checks"]] == [
        "common.content-supported",
        "common.current",
        "common.evidence-resolved",
        "common.kind-fit",
        "common.questions-resolved",
        "event.correction-policy",
        "event.occurred-at-valid",
        "event.source-support",
    ]
    prepared_result = MutationService(clock=lambda: T).apply(
        (prepared,), request=_candidate_update_request(tmp_path, legacy, prepared)
    )
    assert prepared_result.ok

    prepared_store = BrainStore.load(tmp_path)
    stored_candidate = prepared_store.get(prepared["id"])
    assert evaluate_candidate_verification(
        stored_candidate, prepared_store
    ).verification_status == "ready"
    promoted, records = promote(
        [stored_candidate],
        [stored_candidate["id"]],
        "single_object",
        reviewer="human:owner",
        reviewed_at=T,
        store=prepared_store,
    )
    assert len(promoted) == 1
    assert len(records) == 1

    promotion_result = MutationService(clock=lambda: T).apply(
        tuple(promoted + records),
        request=_promotion_request(tmp_path, stored_candidate, promoted, records),
    )

    assert promotion_result.ok
    final_store = BrainStore.load(tmp_path)
    assert final_store.get(stored_candidate["id"])["status"] == "reviewed"
    assert final_store.get(records[0]["id"])["verification"] == envelope
    assert len(final_store.by_kind("ReviewRecord")) == 1


def test_temporal_candidate_binds_causal_event_and_promotes_once(tmp_path):
    source_manifest = manifest()
    source_ref = evidence_ref()
    causal_event = _event_candidate()
    causal_event["status"] = "reviewed"
    causal_event.pop("candidate")
    candidate = _temporal_candidate(causal_event["id"])
    for obj in (source_manifest, source_ref, causal_event, candidate):
        BrainStore.save_object(tmp_path, obj)
    store = BrainStore.load(tmp_path)

    prepared = prepare_candidate_verification(
        candidate,
        store,
        checks=_temporal_checks(),
        engine_sha=ENGINE_SHA,
        executed_at=T,
        producer=PRODUCER,
        verifiers=[],
    )

    envelope = prepared["candidate"]["verification"]
    assert envelope["profile"] == {
        "id": "verification.temporal-fact",
        "version": 1,
    }
    assert [check["id"] for check in envelope["checks"]] == [
        "common.content-supported",
        "common.current",
        "common.evidence-resolved",
        "common.kind-fit",
        "common.questions-resolved",
        "fact.event-linked",
        "fact.supersession-valid",
        "fact.time-scope-valid",
    ]
    prepared_result = MutationService(clock=lambda: T).apply(
        (prepared,), request=_candidate_update_request(tmp_path, candidate, prepared)
    )
    assert prepared_result.ok

    prepared_store = BrainStore.load(tmp_path)
    stored_candidate = prepared_store.get(candidate["id"])
    assert evaluate_candidate_verification(
        stored_candidate, prepared_store
    ).verification_status == "ready"
    promoted, records = promote(
        [stored_candidate],
        [stored_candidate["id"]],
        "single_object",
        reviewer="human:owner",
        reviewed_at=T,
        store=prepared_store,
    )
    promotion_result = MutationService(clock=lambda: T).apply(
        tuple(promoted + records),
        request=_promotion_request(tmp_path, stored_candidate, promoted, records),
    )

    assert promotion_result.ok
    final_store = BrainStore.load(tmp_path)
    assert final_store.get(stored_candidate["id"])["status"] == "reviewed"
    assert final_store.get(records[0]["id"])["verification"] == envelope
    assert len(final_store.by_kind("ReviewRecord")) == 1


def test_temporal_causal_event_drift_becomes_stale():
    source_manifest = manifest()
    source_ref = evidence_ref()
    causal_event = _event_candidate()
    causal_event["status"] = "reviewed"
    causal_event.pop("candidate")
    candidate = _temporal_candidate(causal_event["id"])
    store = BrainStore(
        {obj["id"]: obj for obj in (source_manifest, source_ref, causal_event, candidate)}
    )
    prepared = prepare_candidate_verification(
        candidate,
        store,
        checks=_temporal_checks(),
        engine_sha=ENGINE_SHA,
        executed_at=T,
        producer=PRODUCER,
        verifiers=[],
    )
    changed_event = deepcopy(causal_event)
    changed_event["summary"] = "원인 사건의 의미가 바뀌었다."
    changed_store = BrainStore(
        {
            obj["id"]: obj
            for obj in (source_manifest, source_ref, changed_event, prepared)
        }
    )

    evaluation = evaluate_candidate_verification(prepared, changed_store)

    assert evaluation.verification_status == "stale"
    assert evaluation.reason_codes == ("evidence_changed",)


def test_temporal_invalid_time_range_and_supersession_are_blocked():
    source_manifest = manifest()
    source_ref = evidence_ref()
    causal_event = _event_candidate()
    causal_event["status"] = "reviewed"
    causal_event.pop("candidate")
    candidate = _temporal_candidate(causal_event["id"])
    candidate["valid_until"] = "2026-06-02T12:00:00+09:00"
    candidate["supersedes"] = "fact.neutral.missing"
    store = BrainStore(
        {obj["id"]: obj for obj in (source_manifest, source_ref, causal_event, candidate)}
    )
    checks = _temporal_checks()
    next(
        check for check in checks if check["id"] == "fact.time-scope-valid"
    )["outcome"] = "fail"
    prepared = prepare_candidate_verification(
        candidate,
        store,
        checks=checks,
        engine_sha=ENGINE_SHA,
        executed_at=T,
        producer=PRODUCER,
        verifiers=[],
    )
    prepared_store = BrainStore(
        {obj["id"]: obj for obj in (source_manifest, source_ref, causal_event, prepared)}
    )
    supersession_check = next(
        check
        for check in prepared["candidate"]["verification"]["checks"]
        if check["id"] == "fact.supersession-valid"
    )

    assert supersession_check["authority"] == "engine"
    assert supersession_check["outcome"] == "fail"
    evaluation = evaluate_candidate_verification(prepared, prepared_store)
    assert evaluation.verification_status == "blocked"
    assert evaluation.reason_codes == ("check_failed",)


def test_code_candidate_binds_current_checkout_quote_and_revision(tmp_path):
    _repo, repo_context, commit_sha = _git_repo(tmp_path)
    brain_root = tmp_path / "brain"
    source_manifest = manifest()
    source_ref = evidence_ref()
    candidate = _code_candidate(commit_sha)
    for obj in (source_manifest, source_ref, candidate):
        BrainStore.save_object(brain_root, obj)
    store = BrainStore.load(brain_root)

    prepared = prepare_candidate_verification(
        candidate,
        store,
        checks=_common_agent_checks("대상은 현재 checkout의 코드 위치다."),
        engine_sha=ENGINE_SHA,
        executed_at=T,
        producer=PRODUCER,
        verifiers=[],
        repo_context=repo_context,
    )

    envelope = prepared["candidate"]["verification"]
    assert envelope["profile"] == {
        "id": "verification.code-locator",
        "version": 1,
    }
    assert [check["id"] for check in envelope["checks"]] == [
        "code.locator-resolves",
        "code.quote-matches",
        "code.revision-bound",
        "common.content-supported",
        "common.current",
        "common.evidence-resolved",
        "common.kind-fit",
        "common.questions-resolved",
    ]
    prepared_result = MutationService(clock=lambda: T).apply(
        (prepared,),
        request=_candidate_update_request(
            brain_root, candidate, prepared, repo_context=repo_context
        ),
    )
    assert prepared_result.ok

    prepared_store = BrainStore.load(brain_root)
    stored_candidate = prepared_store.get(candidate["id"])
    assert evaluate_candidate_verification(
        stored_candidate, prepared_store, repo_context=repo_context
    ).verification_status == "ready"
    promoted, records = promote(
        [stored_candidate],
        [stored_candidate["id"]],
        "single_object",
        reviewer="human:owner",
        reviewed_at=T,
        store=prepared_store,
        repo_context=repo_context,
    )
    promotion_result = MutationService(clock=lambda: T).apply(
        tuple(promoted + records),
        request=_promotion_request(
            brain_root,
            stored_candidate,
            promoted,
            records,
            repo_context=repo_context,
        ),
    )

    assert promotion_result.ok
    final_store = BrainStore.load(brain_root)
    assert final_store.get(stored_candidate["id"])["status"] == "reviewed"
    assert final_store.get(records[0]["id"])["verification"] == envelope
    assert len(final_store.by_kind("ReviewRecord")) == 1


def test_code_checkout_revision_drift_becomes_stale_and_cannot_promote(tmp_path):
    repo, repo_context, commit_sha = _git_repo(tmp_path)
    candidate = _code_candidate(commit_sha)
    source_manifest = manifest()
    source_ref = evidence_ref()
    store = BrainStore(
        {obj["id"]: obj for obj in (source_manifest, source_ref, candidate)}
    )
    prepared = prepare_candidate_verification(
        candidate,
        store,
        checks=_common_agent_checks("대상은 현재 checkout의 코드 위치다."),
        engine_sha=ENGINE_SHA,
        executed_at=T,
        producer=PRODUCER,
        verifiers=[],
        repo_context=repo_context,
    )
    (repo / "README.md").write_text("revision drift\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "drift"], cwd=repo, check=True)
    current_store = BrainStore(
        {obj["id"]: obj for obj in (source_manifest, source_ref, prepared)}
    )

    evaluation = evaluate_candidate_verification(
        prepared, current_store, repo_context=repo_context
    )

    assert evaluation.verification_status == "stale"
    assert evaluation.reason_codes == ("evidence_changed",)
    with pytest.raises(ValueError, match="verification_not_ready"):
        promote(
            [prepared],
            [prepared["id"]],
            "single_object",
            reviewer="human:owner",
            reviewed_at=T,
            store=current_store,
            repo_context=repo_context,
        )


def test_event_source_drift_is_candidate_local():
    first_manifest = manifest("manifest.neutral.first")
    second_manifest = manifest("manifest.neutral.second")
    first_ref = evidence_ref("evref.neutral.first", first_manifest["id"])
    second_ref = evidence_ref("evref.neutral.second", second_manifest["id"])
    first = _event_candidate()
    first["id"] = "ledger.neutral.first"
    first["evidence_refs"] = [first_ref["id"]]
    second = _event_candidate()
    second["id"] = "ledger.neutral.second"
    second["evidence_refs"] = [second_ref["id"]]
    initial_store = BrainStore(
        {
            obj["id"]: obj
            for obj in (first_manifest, second_manifest, first_ref, second_ref, first, second)
        }
    )
    prepared_first = prepare_candidate_verification(
        first,
        initial_store,
        checks=_event_checks(),
        engine_sha=ENGINE_SHA,
        executed_at=T,
        producer=PRODUCER,
        verifiers=[],
    )
    prepared_second = prepare_candidate_verification(
        second,
        initial_store,
        checks=_event_checks(),
        engine_sha=ENGINE_SHA,
        executed_at=T,
        producer=PRODUCER,
        verifiers=[],
    )
    changed_ref = deepcopy(first_ref)
    changed_ref["summary"] = "첫 번째 사건 근거만 바뀌었다."
    changed_store = BrainStore(
        {
            obj["id"]: obj
            for obj in (
                first_manifest,
                second_manifest,
                changed_ref,
                second_ref,
                prepared_first,
                prepared_second,
            )
        }
    )

    first_evaluation = evaluate_candidate_verification(
        prepared_first, changed_store
    )
    second_evaluation = evaluate_candidate_verification(
        prepared_second, changed_store
    )

    assert first_evaluation.verification_status == "stale"
    assert first_evaluation.reason_codes == ("evidence_changed",)
    assert second_evaluation.verification_status == "ready"


def test_event_profile_rejects_authority_outside_fixed_contract():
    subject = _event_candidate()
    source_manifest = manifest()
    source_ref = evidence_ref()
    store = BrainStore(
        {obj["id"]: obj for obj in (source_manifest, source_ref, subject)}
    )
    checks = _event_checks()
    next(
        check for check in checks if check["id"] == "event.correction-policy"
    )["authority"] = "human"

    with pytest.raises(ValueError, match="authority"):
        prepare_candidate_verification(
            subject,
            store,
            checks=checks,
            engine_sha=ENGINE_SHA,
            executed_at=T,
            producer=PRODUCER,
            verifiers=[],
        )


def test_invalid_event_time_is_an_engine_failure_that_caller_cannot_override():
    subject = _event_candidate()
    subject["happened_at"] = "2026-06-03T12:00:00"
    source_manifest = manifest()
    source_ref = evidence_ref()
    store = BrainStore(
        {obj["id"]: obj for obj in (source_manifest, source_ref, subject)}
    )

    prepared = prepare_candidate_verification(
        subject,
        store,
        checks=_event_checks(),
        engine_sha=ENGINE_SHA,
        executed_at=T,
        producer=PRODUCER,
        verifiers=[],
    )
    prepared_store = BrainStore(
        {obj["id"]: obj for obj in (source_manifest, source_ref, prepared)}
    )
    check = next(
        check
        for check in prepared["candidate"]["verification"]["checks"]
        if check["id"] == "event.occurred-at-valid"
    )

    assert check["authority"] == "engine"
    assert check["outcome"] == "fail"
    assert evaluate_candidate_verification(
        prepared, prepared_store
    ).verification_status == "blocked"


def test_event_promotion_revalidates_source_drift_before_any_write(tmp_path):
    source_manifest = manifest()
    source_ref = evidence_ref()
    candidate = _event_candidate()
    initial_store = BrainStore(
        {obj["id"]: obj for obj in (source_manifest, source_ref, candidate)}
    )
    prepared = prepare_candidate_verification(
        candidate,
        initial_store,
        checks=_event_checks(),
        engine_sha=ENGINE_SHA,
        executed_at=T,
        producer=PRODUCER,
        verifiers=[],
    )
    ready_store = BrainStore(
        {obj["id"]: obj for obj in (source_manifest, source_ref, prepared)}
    )
    promoted, records = promote(
        [prepared],
        [prepared["id"]],
        "single_object",
        reviewer="human:owner",
        reviewed_at=T,
        store=ready_store,
    )
    changed_ref = deepcopy(source_ref)
    changed_ref["summary"] = "승격 직전에 바뀐 사건 근거"
    for obj in (source_manifest, changed_ref, prepared):
        BrainStore.save_object(tmp_path, obj)
    index_path = tmp_path / ".brain-local" / "index.db"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(b"existing-index")
    request = _promotion_request(tmp_path, prepared, promoted, records)

    result = MutationService().apply(request.objects, request=request)

    assert (result.ok, result.error_code) == (False, "verification_not_ready")
    stored = BrainStore.load(tmp_path)
    assert stored.get(prepared["id"]) == prepared
    assert not stored.has(records[0]["id"])
    assert index_path.read_bytes() == b"existing-index"
    assert not (tmp_path / ".brain-local" / "batch-intents").exists()
    assert not (tmp_path / ".brain-local" / "transactions").exists()
    assert not (tmp_path / ".brain-local" / "preparing-transactions").exists()


@pytest.mark.parametrize(
    "legacy",
    [
        _event_candidate(),
        _temporal_candidate("ledger.neutral.release"),
        _code_candidate("0" * 40),
    ],
    ids=["event", "temporal", "code"],
)
def test_legacy_candidate_without_verification_is_not_promotable(legacy):
    store = BrainStore({legacy["id"]: legacy})

    evaluation = evaluate_candidate_verification(legacy, store)

    assert evaluation.verification_status == "unverified"
    assert evaluation.reason_codes == ("verification_missing",)
    with pytest.raises(ValueError, match="verification_missing"):
        promote(
            [legacy],
            [legacy["id"]],
            "single_object",
            reviewer="human:owner",
            reviewed_at=T,
            store=store,
        )
