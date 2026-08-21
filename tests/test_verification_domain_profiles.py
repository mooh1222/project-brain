import hashlib
from copy import deepcopy

import pytest

import project_brain.verification as verification_module
from project_brain.context_projection import build_reuse_projection
from project_brain.objbase import base
from project_brain.mutation import (
    MutationOperation,
    MutationRequest,
    MutationService,
    corpus_fingerprint,
)
from project_brain.promote import promote
from project_brain.store import BrainStore
from project_brain.verification import (
    evaluate_candidate_verification,
    prepare_candidate_verification,
)


T = "2026-08-21T00:00:00+09:00"


def _candidate_metadata(*, open_questions=None):
    return {
        "candidate_state": "evidence_verified",
        "candidate_source": "spec",
        "proposed_by": "agent:extractor",
        "proposed_at": T,
        "open_questions": open_questions or [],
    }


def _domain_context():
    return base(
        {
            "id": "context.neutral",
            "kind": "DomainContext",
            "status": "candidate",
            "truth_role": "domain",
            "title": "중립 도메인",
            "context_key": "neutral",
            "project_id": "neutral-project",
            "display_name": "중립",
            "boundary_summary": "중립 기능의 경계를 소유한다.",
            "in_scope": ["중립 기능"],
            "out_of_scope": ["다른 기능"],
            "injection_profile": {"default_audience": "coding-agent"},
            "glossary_term_ids": [],
            "candidate": _candidate_metadata(),
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _domain_checks():
    return [
        {
            "id": "common.content-supported",
            "outcome": "pass",
            "authority": "agent",
            "summary": "내용이 근거와 맞는다.",
        },
        {
            "id": "common.kind-fit",
            "outcome": "pass",
            "authority": "agent",
            "summary": "독립 DomainContext가 맞다.",
        },
        {
            "id": "common.questions-resolved",
            "outcome": "pass",
            "authority": "agent",
            "summary": "남은 질문이 없다.",
        },
        {
            "id": "domain.boundary-explicit",
            "outcome": "pass",
            "authority": "human",
            "summary": "포함과 제외 경계가 명확하다.",
        },
        {
            "id": "domain.glossary-coherent",
            "outcome": "pass",
            "authority": "agent",
            "summary": "소유 어휘가 일관된다.",
        },
        {
            "id": "domain.owner-distinct",
            "outcome": "pass",
            "authority": "human",
            "summary": "다른 도메인과 소유 범위가 구분된다.",
        },
    ]


def _reviewed_domain_context():
    context = _domain_context()
    context["status"] = "reviewed"
    context.pop("candidate")
    return context


def _decision_record():
    return base(
        {
            "id": "decision.neutral.boundary",
            "kind": "DecisionRecord",
            "status": "candidate",
            "truth_role": "event",
            "title": "중립 경계 결정",
            "decision_type": "implementation_boundary",
            "summary": "중립 기능은 독립 도메인이다.",
            "decision": "중립 기능의 변경은 독립 경계에서 처리한다.",
            "source_object_ids": ["context.neutral"],
            "affected_context_ids": ["context.neutral"],
            "spec_reflected": "yes",
            "candidate": _candidate_metadata(),
        },
        tags=["neutral"],
        created_at=T,
        updated_at=T,
    )


def _decision_checks():
    return [
        {
            "id": "common.content-supported",
            "outcome": "pass",
            "authority": "human",
            "summary": "결정 진술이 출처와 맞는다.",
        },
        {
            "id": "common.kind-fit",
            "outcome": "pass",
            "authority": "agent",
            "summary": "DecisionRecord가 맞다.",
        },
        {
            "id": "common.questions-resolved",
            "outcome": "pass",
            "authority": "agent",
            "summary": "남은 질문이 없다.",
        },
        {
            "id": "decision.scope-explicit",
            "outcome": "pass",
            "authority": "human",
            "summary": "결정 범위가 명확하다.",
        },
        {
            "id": "decision.statement-supported",
            "outcome": "pass",
            "authority": "human",
            "summary": "결정문이 출처에서 뒷받침된다.",
        },
        {
            "id": "decision.supersession-valid",
            "outcome": "pass",
            "authority": "agent",
            "summary": "결정 대체 관계가 현재 lifecycle과 맞는다.",
        },
    ]


def _prompt_projection(store):
    projection = build_reuse_projection(
        store,
        context_id="context.neutral",
        requirement_key="boundary-summary",
        source_object_ids=["context.neutral"],
        reuse_payload="중립 기능은 독립 경계에서 처리한다.",
        title="중립 경계 prompt projection",
        generated_by="agent:extractor",
    )
    projection["candidate"] = _candidate_metadata()
    projection["created_at"] = T
    projection["updated_at"] = T
    projection["generated_at"] = T
    return projection


def _projection_checks():
    return [
        {
            "id": "common.content-supported",
            "outcome": "pass",
            "authority": "agent",
            "summary": "payload가 source 내용에 맞는다.",
        },
        {
            "id": "common.kind-fit",
            "outcome": "pass",
            "authority": "agent",
            "summary": "재사용 prompt projection이 맞다.",
        },
        {
            "id": "common.questions-resolved",
            "outcome": "pass",
            "authority": "agent",
            "summary": "남은 질문이 없다.",
        },
        {
            "id": "projection.scope-bounded",
            "outcome": "pass",
            "authority": "agent",
            "summary": "요구 범위에 필요한 source만 사용한다.",
        },
    ]


def _prepare(subject, store, checks):
    return prepare_candidate_verification(
        subject,
        store,
        checks=checks,
        engine_sha="e" * 40,
        executed_at=T,
        producer={"kind": "agent", "id": "agent:extractor", "version": "1"},
        verifiers=[{"kind": "human", "id": "human:owner", "version": "1"}],
    )


def test_domain_context_uses_exact_profile_and_becomes_ready():
    subject = _domain_context()
    store = BrainStore({subject["id"]: subject})

    prepared = _prepare(subject, store, _domain_checks())
    prepared_store = BrainStore({prepared["id"]: prepared})

    envelope = prepared["candidate"]["verification"]
    assert envelope["profile"] == {
        "id": "verification.domain-context",
        "version": 1,
    }
    assert [check["id"] for check in envelope["checks"]] == [
        "common.content-supported",
        "common.current",
        "common.evidence-resolved",
        "common.kind-fit",
        "common.questions-resolved",
        "domain.boundary-explicit",
        "domain.glossary-coherent",
        "domain.owner-distinct",
    ]
    evaluation = evaluate_candidate_verification(prepared, prepared_store)
    assert evaluation.verification_status == "ready"
    assert evaluation.reason_codes == ()


def test_decision_record_validates_sources_supersession_and_impacts():
    context = _reviewed_domain_context()
    subject = _decision_record()
    store = BrainStore({context["id"]: context, subject["id"]: subject})

    prepared = _prepare(subject, store, _decision_checks())
    prepared_store = BrainStore({context["id"]: context, prepared["id"]: prepared})

    envelope = prepared["candidate"]["verification"]
    assert envelope["profile"] == {
        "id": "verification.decision-record",
        "version": 1,
    }
    checks = {check["id"]: check for check in envelope["checks"]}
    assert checks["decision.supersession-valid"]["authority"] == "agent"
    assert checks["decision.supersession-valid"]["outcome"] == "pass"
    assert checks["decision.impacts-linked"]["authority"] == "engine"
    assert checks["decision.impacts-linked"]["outcome"] == "pass"
    assert evaluate_candidate_verification(
        prepared,
        prepared_store,
    ).verification_status == "ready"


def test_prompt_projection_reuses_official_source_hash_and_freshness():
    context = _reviewed_domain_context()
    source_store = BrainStore({context["id"]: context})
    subject = _prompt_projection(source_store)
    store = BrainStore({context["id"]: context, subject["id"]: subject})

    prepared = _prepare(subject, store, _projection_checks())
    prepared_store = BrainStore({
        context["id"]: context,
        prepared["id"]: prepared,
    })

    envelope = prepared["candidate"]["verification"]
    assert envelope["profile"] == {
        "id": "verification.context-projection",
        "version": 1,
    }
    assert prepared["source_content_hash"] == subject["source_content_hash"]
    assert evaluate_candidate_verification(
        prepared,
        prepared_store,
    ).verification_status == "ready"


def _prepared_case(kind):
    context = _reviewed_domain_context()
    if kind == "DomainContext":
        subject = _domain_context()
        source_objects = []
        checks = _domain_checks()
    elif kind == "DecisionRecord":
        subject = _decision_record()
        source_objects = [context]
        checks = _decision_checks()
    else:
        source_store = BrainStore({context["id"]: context})
        subject = _prompt_projection(source_store)
        source_objects = [context]
        checks = _projection_checks()
    store = BrainStore({
        obj["id"]: obj
        for obj in [*source_objects, subject]
    })
    prepared = _prepare(subject, store, checks)
    prepared_store = BrainStore({
        obj["id"]: obj
        for obj in [*source_objects, prepared]
    })
    return prepared, prepared_store


@pytest.mark.parametrize(
    "kind",
    ["DomainContext", "DecisionRecord", "ContextProjection"],
)
def test_each_supported_candidate_promotes_with_one_matching_review_record(kind):
    prepared, store = _prepared_case(kind)

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
    assert len(records) == 1
    assert records[0]["verification"] == prepared["candidate"]["verification"]
    assert records[0]["verification_origin"] == "candidate_promotion"
    assert records[0]["verification_history"] == []


@pytest.mark.parametrize("kind", ["DecisionRecord", "ContextProjection"])
def test_source_change_before_locked_promotion_is_zero_write(tmp_path, kind):
    prepared, original_store = _prepared_case(kind)
    promoted, records = promote(
        [prepared],
        [prepared["id"]],
        "single_object",
        reviewer="human:owner",
        reviewed_at=T,
        store=original_store,
    )
    live_candidate = prepared
    context = original_store.get("context.neutral")
    if kind == "DecisionRecord":
        context = dict(context)
        context["boundary_summary"] = "승격 직전에 바뀐 경계"
    else:
        live_candidate = deepcopy(prepared)
        live_candidate["candidate"]["verification"]["profile"]["id"] = (
            "verification.decision-record"
        )
    BrainStore.save_object(tmp_path, context)
    BrainStore.save_object(tmp_path, live_candidate)
    live_store = BrainStore.load(tmp_path)
    index_path = tmp_path / ".brain-local" / "index.db"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(b"existing-index")
    request = MutationRequest(
        operation=MutationOperation.PROMOTE,
        brain_root=tmp_path,
        repo_context=None,
        engine_sha="e" * 40,
        objects=tuple(promoted + records),
        preconditions={
            prepared["id"]: hashlib.sha256(
                BrainStore.object_bytes(live_store.get(prepared["id"]))
            ).hexdigest(),
        },
        expected_corpus_fingerprint=corpus_fingerprint(live_store),
    )

    result = MutationService().apply(request.objects, request=request)

    assert (result.ok, result.error_code) == (False, "verification_not_ready")
    stored = BrainStore.load(tmp_path)
    assert stored.get(prepared["id"])["status"] == "candidate"
    assert not stored.has(records[0]["id"])
    assert index_path.read_bytes() == b"existing-index"
    assert not (tmp_path / ".brain-local" / "batch-intents").exists()
    assert not (tmp_path / ".brain-local" / "transactions").exists()


def test_needs_human_and_open_question_are_blocked_without_mutating_subject():
    subject = _domain_context()
    subject["candidate"]["open_questions"] = ["소유 경계를 확정할까요?"]
    checks = _domain_checks()
    checks[3]["outcome"] = "needs_human"
    before = deepcopy(subject)
    store = BrainStore({subject["id"]: subject})

    prepared = _prepare(subject, store, checks)
    prepared_store = BrainStore({prepared["id"]: prepared})
    evaluation = evaluate_candidate_verification(prepared, prepared_store)

    assert evaluation.verification_status == "blocked"
    assert evaluation.reason_codes == ("human_required", "open_questions")
    assert subject == before
    assert "verification" not in subject["candidate"]


def test_context_md_candidate_cannot_use_prompt_projection_verification():
    context = _reviewed_domain_context()
    source_store = BrainStore({context["id"]: context})
    subject = _prompt_projection(source_store)
    subject["format"] = "context_md"
    store = BrainStore({context["id"]: context, subject["id"]: subject})

    with pytest.raises(ValueError, match="supported candidate verification profile"):
        _prepare(subject, store, _projection_checks())

    with pytest.raises(ValueError, match="prompt_payload"):
        promote(
            [subject],
            [subject["id"]],
            "single_object",
            reviewer="human:owner",
            reviewed_at=T,
            store=store,
        )


@pytest.mark.parametrize(
    ("kind", "check_index"),
    [
        ("DomainContext", 4),
        ("DecisionRecord", 3),
        ("ContextProjection", 3),
    ],
)
def test_profile_rejects_authority_outside_its_exact_allowlist(kind, check_index):
    prepared, store = _prepared_case(kind)
    subject = deepcopy(prepared)
    subject["candidate"].pop("verification")
    checks = {
        "DomainContext": _domain_checks,
        "DecisionRecord": _decision_checks,
        "ContextProjection": _projection_checks,
    }[kind]()
    checks[check_index]["authority"] = "engine"
    before = deepcopy(subject)

    with pytest.raises(ValueError, match="authority is not allowed"):
        _prepare(subject, store, checks)

    assert subject == before


@pytest.mark.parametrize(
    "kind",
    ["DomainContext", "DecisionRecord", "ContextProjection"],
)
def test_legacy_candidate_is_readable_but_unverified_and_not_promotable(kind):
    prepared, store = _prepared_case(kind)
    legacy = deepcopy(prepared)
    legacy["candidate"].pop("verification")
    legacy_store = BrainStore({
        **{obj["id"]: obj for obj in store.all() if obj["id"] != legacy["id"]},
        legacy["id"]: legacy,
    })

    evaluation = evaluate_candidate_verification(legacy, legacy_store)

    assert evaluation.verification_status == "unverified"
    assert evaluation.reason_codes == ("verification_missing",)
    with pytest.raises(ValueError, match="verification_missing"):
        promote(
            [legacy],
            [legacy["id"]],
            "single_object",
            reviewer="human:owner",
            reviewed_at=T,
            store=legacy_store,
        )


def test_prompt_projection_source_change_recalculates_current_status():
    prepared, store = _prepared_case("ContextProjection")
    changed_context = deepcopy(store.get("context.neutral"))
    changed_context["boundary_summary"] = "검증 뒤 바뀐 경계"
    changed_store = BrainStore({
        changed_context["id"]: changed_context,
        prepared["id"]: prepared,
    })

    evaluation = evaluate_candidate_verification(prepared, changed_store)

    assert evaluation.verification_status == "stale"
    assert evaluation.reason_codes == ("evidence_changed",)


def test_domain_profile_rules_change_recalculates_current_status(monkeypatch):
    subject = _domain_context()
    store = BrainStore({subject["id"]: subject})
    monkeypatch.setattr(
        verification_module,
        "_rules_binding",
        lambda _profile: "0" * 64,
    )
    prepared = _prepare(subject, store, _domain_checks())
    monkeypatch.undo()
    prepared_store = BrainStore({prepared["id"]: prepared})

    evaluation = evaluate_candidate_verification(prepared, prepared_store)

    assert evaluation.verification_status == "stale"
    assert evaluation.reason_codes == ("rules_changed",)


@pytest.mark.parametrize(
    "kind",
    ["DomainContext", "DecisionRecord", "ContextProjection"],
)
def test_each_supported_candidate_promotes_through_mutation_service(tmp_path, kind):
    prepared, store = _prepared_case(kind)
    for obj in store.all():
        BrainStore.save_object(tmp_path, obj)
    live_store = BrainStore.load(tmp_path)
    promoted, records = promote(
        [prepared],
        [prepared["id"]],
        "single_object",
        reviewer="human:owner",
        reviewed_at=T,
        store=live_store,
    )
    request = MutationRequest(
        operation=MutationOperation.PROMOTE,
        brain_root=tmp_path,
        repo_context=None,
        engine_sha="e" * 40,
        objects=tuple(promoted + records),
        preconditions={
            prepared["id"]: hashlib.sha256(
                BrainStore.object_bytes(live_store.get(prepared["id"]))
            ).hexdigest(),
        },
        expected_corpus_fingerprint=corpus_fingerprint(live_store),
    )

    result = MutationService(clock=lambda: T).apply(
        request.objects,
        request=request,
    )

    assert result.ok
    stored = BrainStore.load(tmp_path)
    assert stored.get(prepared["id"])["status"] == "reviewed"
    assert stored.get(records[0]["id"])["verification"] == (
        prepared["candidate"]["verification"]
    )
