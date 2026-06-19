"""object-model 스키마의 kind별 필수 필드 검증 (첫 슬라이스 13종).
spec: docs/superpowers/specs/2026-05-27-project-brain-object-model-design.md
router가 실제로 읽는 필드는 일부지만, 적재 무결성을 위해 spec 필수 필드 전체를 강제한다."""

BASE_REQUIRED = (
    "id", "kind", "schema_version", "status", "poc_priority",
    "truth_role", "title", "created_at", "updated_at", "tags", "evidence_refs",
)

KIND_REQUIRED = {
    "EvidenceManifest": ("source_type", "locator", "captured_at", "captured_by",
                         "sensitivity", "acl", "redaction_status"),
    "EvidenceRef": ("evidence_manifest_id", "ref_type", "locator", "summary"),
    "ReviewRecord": ("reviewer", "reviewed_at", "verdict"),
    "EventLedgerRecord": ("event_type", "happened_at", "summary", "related_objects"),
    "TemporalFact": ("subject", "predicate", "value", "scope", "valid_from",
                     "derived_from_event_id", "confidence"),
    "CodeLocator": ("repo", "path", "locator_source", "verified_at"),
    "DomainContext": ("context_key", "project_id", "display_name", "boundary_summary",
                      "in_scope", "out_of_scope", "injection_profile", "glossary_term_ids"),
    "GlossaryTerm": ("context_id", "term", "definition"),
    "ContextProjection": ("context_id", "format", "source_object_ids", "source_content_hash",
                          "projection_hash", "generated_at", "generated_by", "stale_policy"),
    "CurrentView": ("view_type", "as_of", "source_fact_ids", "source_event_ids", "summary"),
    "KnowledgePage": ("category", "path", "summary", "source_object_ids", "stale_policy"),
    "IndexRecord": ("index_name", "source_object_id", "indexed_at", "content_hash"),
    "SpecDocument": ("source_system", "canonical_locator"),
    "SpecRevision": ("spec_document_id", "revision_label", "captured_at", "slide_refs"),
    "SlideRef": ("spec_revision_id", "slide_no"),
    "SlackThread": ("channel_id", "thread_ts", "participants", "message_refs", "summary"),
    "DecisionRecord": ("decision_type", "summary", "decision", "source_object_ids",
                       "affected_context_ids", "spec_reflected"),
    "DomainMapping": ("context_id", "mapping_key", "canonical_summary", "meaning",
                      "boundary", "glossary_term_ids", "decision_record_ids"),
    "Insight": ("body", "source_object_ids"),
}

TRUTH_ROLE_VALUES = frozenset({
    "source", "reference", "review", "event", "fact", "synthesis", "domain", "index",
})
KIND_TRUTH_ROLE = {
    "EvidenceManifest": "source",
    "EvidenceRef": "reference",
    "ReviewRecord": "review",
    "EventLedgerRecord": "event",
    "TemporalFact": "fact",
    "CodeLocator": "reference",
    "DomainContext": "domain",
    "GlossaryTerm": "domain",
    "ContextProjection": "index",
    "CurrentView": "synthesis",
    "KnowledgePage": "synthesis",
    "IndexRecord": "index",
    "SpecDocument": "reference",
    "SpecRevision": "reference",
    "SlideRef": "reference",
    "SlackThread": "source",
    "DecisionRecord": "event",
    "DomainMapping": "domain",
    "Insight": "synthesis",
}
OBJECT_STATUS_VALUES = frozenset({"candidate", "reviewed", "superseded", "archived", "rejected"})
POC_PRIORITY_VALUES = frozenset({"P0", "P1", "P2"})
AUDIENCE_VALUES = frozenset({"coding-agent", "planner", "reviewer", "search-router"})
CANDIDATE_STATE_VALUES = frozenset({
    "observed", "evidence_verified", "needs_user_confirmation", "conflict", "ready_for_review",
})
CANDIDATE_SOURCE_VALUES = frozenset({
    "spec", "code", "session", "slack", "jira", "legacy_context", "legacy_wiki", "manual",
})
PROJECTION_FORMAT_VALUES = frozenset({"context_md", "prompt_payload"})
INDEX_NAME_VALUES = frozenset({"fts", "timeline", "entity", "code_locator", "trigram", "vector"})

VALID_KINDS = frozenset(KIND_REQUIRED)

# enum 값 집합 (spec §6.1 EvidenceManifest.source_type / §6.2 EvidenceRef.ref_type).
# 필드 존재만 보던 검증이 잘못된 값(예: spec_ppt, slide)을 통과시켰던 회귀를 막는다.
SOURCE_TYPE_VALUES = frozenset({
    "session", "slack", "jira", "pr", "commit", "spec",
    "build_log", "code_search", "wiki", "context",
})
REF_TYPE_VALUES = frozenset({
    "slack_message", "slack_thread", "jira_comment", "spec_slide", "spec_section",
    "code_locator", "build_log_range", "session_turn", "wiki_section", "context_term",
    "commit", "pr", "jira_issue",
})
# spec §10.1 CodeLocator.locator_source
LOCATOR_SOURCE_VALUES = frozenset({"codanna", "rg", "clangd", "manual"})
# spec §6.5 TemporalFact.confidence
CONFIDENCE_VALUES = frozenset({"high", "medium", "low", "unknown"})
# spec §5.1 DecisionRecord.decision_type / spec_reflected
DECISION_TYPE_VALUES = frozenset({
    "spec_clarification", "spec_revision", "improvement", "qa_issue",
    "sanity_change", "hotfix_change", "naming_decision", "implementation_boundary",
})
SPEC_REFLECTED_VALUES = frozenset({"yes", "no", "unknown", "not_applicable"})
# spec §6 ReviewRecord.review_type / §6.1 review_scope / §5.2 DomainMapping.review_state
REVIEW_TYPE_VALUES = frozenset({
    "meaning_review", "evidence_review", "implementation_review",
    "projection_review", "supersession_review",
})
REVIEW_SCOPE_VALUES = frozenset({"single_object", "mapping_bundle"})
REVIEW_STATE_KEYS = frozenset({
    "meaning_reviewed", "evidence_reviewed", "implementation_reviewed", "projection_reviewed",
})
# spec(2026-06-15 Insight kind §4.2): A/B 두 결만 강제, 세부 분류는 연다.
# insight_type은 필수가 아니되 값이 있으면 이 둘 중 하나여야 한다.
INSIGHT_TYPE_VALUES = frozenset({"cross-cutting-risk", "operational-lesson"})


class SchemaError(ValueError):
    pass


def validate_object(obj: dict) -> list[str]:
    """위반 메시지 목록을 반환한다(빈 목록 = 통과). Lint가 모아 보고하도록 예외 대신 목록."""
    kind = obj.get("kind")
    if kind not in VALID_KINDS:
        return [f"{obj.get('id', '?')}: unknown kind {kind!r}"]
    errors = []
    for field in BASE_REQUIRED:
        if field not in obj:
            errors.append(f"{obj['id']}: missing base field {field!r}")
    for field in KIND_REQUIRED[kind]:
        if field not in obj:
            errors.append(f"{obj['id']}: {kind} missing field {field!r}")
    status = obj.get("status")
    if status is not None and status not in OBJECT_STATUS_VALUES:
        errors.append(f"{obj['id']}: invalid status {status!r}")
    priority = obj.get("poc_priority")
    if priority is not None and priority not in POC_PRIORITY_VALUES:
        errors.append(f"{obj['id']}: invalid poc_priority {priority!r}")
    truth_role = obj.get("truth_role")
    if truth_role is not None and truth_role not in TRUTH_ROLE_VALUES:
        errors.append(f"{obj['id']}: invalid truth_role {truth_role!r}")
    expected_truth_role = KIND_TRUTH_ROLE.get(kind)
    if truth_role is not None and expected_truth_role is not None and truth_role != expected_truth_role:
        errors.append(f"{obj['id']}: {kind} invalid truth_role {truth_role!r}, expected {expected_truth_role!r}")
    # enum 값 검증 (필드가 있을 때만 — 누락은 위에서 이미 보고).
    if kind == "EvidenceManifest":
        source_type = obj.get("source_type")
        if source_type is not None and source_type not in SOURCE_TYPE_VALUES:
            errors.append(f"{obj['id']}: EvidenceManifest invalid source_type {source_type!r}")
    elif kind == "EvidenceRef":
        ref_type = obj.get("ref_type")
        if ref_type is not None and ref_type not in REF_TYPE_VALUES:
            errors.append(f"{obj['id']}: EvidenceRef invalid ref_type {ref_type!r}")
    elif kind == "CodeLocator":
        locator_source = obj.get("locator_source")
        if locator_source is not None and locator_source not in LOCATOR_SOURCE_VALUES:
            errors.append(f"{obj['id']}: CodeLocator invalid locator_source {locator_source!r}")
    elif kind == "TemporalFact":
        confidence = obj.get("confidence")
        if confidence is not None and confidence not in CONFIDENCE_VALUES:
            errors.append(f"{obj['id']}: TemporalFact invalid confidence {confidence!r}")
    elif kind == "DomainContext":
        for legacy_field in ("path", "source_format"):
            if legacy_field in obj:
                errors.append(f"{obj['id']}: DomainContext legacy field {legacy_field!r} is not canonical in v2")
        profile = obj.get("injection_profile") or {}
        audience = profile.get("default_audience")
        if audience is not None and audience not in AUDIENCE_VALUES:
            errors.append(f"{obj['id']}: DomainContext invalid default_audience {audience!r}")
        for export_target in obj.get("export_targets") or []:
            fmt = export_target.get("format")
            if fmt not in PROJECTION_FORMAT_VALUES:
                errors.append(f"{obj['id']}: DomainContext invalid export target format {fmt!r}")
    elif kind == "GlossaryTerm":
        candidate = obj.get("candidate")
        if obj.get("status") == "candidate" and not candidate:
            errors.append(f"{obj['id']}: candidate GlossaryTerm requires candidate metadata")
        if candidate:
            state = candidate.get("candidate_state")
            source = candidate.get("candidate_source")
            if state not in CANDIDATE_STATE_VALUES:
                errors.append(f"{obj['id']}: GlossaryTerm invalid candidate_state {state!r}")
            if source not in CANDIDATE_SOURCE_VALUES:
                errors.append(f"{obj['id']}: GlossaryTerm invalid candidate_source {source!r}")
            if obj.get("status") == "reviewed":
                if state == "conflict":
                    errors.append(f"{obj['id']}: reviewed GlossaryTerm cannot keep candidate_state 'conflict'")
                if candidate.get("open_questions"):
                    errors.append(f"{obj['id']}: reviewed GlossaryTerm cannot keep unresolved open_questions")
        if obj.get("status") == "rejected" and not obj.get("rejection"):
            errors.append(f"{obj['id']}: rejected GlossaryTerm requires rejection metadata")
        if obj.get("status") == "reviewed" and not obj.get("evidence_refs"):
            errors.append(f"{obj['id']}: reviewed GlossaryTerm requires non-empty evidence_refs")
    elif kind == "ContextProjection":
        fmt = obj.get("format")
        if fmt is not None and fmt not in PROJECTION_FORMAT_VALUES:
            errors.append(f"{obj['id']}: ContextProjection invalid format {fmt!r}")
        stale_policy = obj.get("stale_policy")
        if stale_policy != "fail_on_manual_edit":
            errors.append(f"{obj['id']}: ContextProjection invalid stale_policy {stale_policy!r}")
    elif kind == "IndexRecord":
        index_name = obj.get("index_name")
        if index_name is not None and index_name not in INDEX_NAME_VALUES:
            errors.append(f"{obj['id']}: IndexRecord invalid index_name {index_name!r}")
    elif kind == "DecisionRecord":
        decision_type = obj.get("decision_type")
        if decision_type is not None and decision_type not in DECISION_TYPE_VALUES:
            errors.append(f"{obj['id']}: DecisionRecord invalid decision_type {decision_type!r}")
        spec_reflected = obj.get("spec_reflected")
        if spec_reflected is not None and spec_reflected not in SPEC_REFLECTED_VALUES:
            errors.append(f"{obj['id']}: DecisionRecord invalid spec_reflected {spec_reflected!r}")
    elif kind == "DomainMapping":
        review_state = obj.get("review_state")
        if review_state is not None:
            if not isinstance(review_state, dict):
                errors.append(f"{obj['id']}: DomainMapping review_state must be an object")
            else:
                for rs_key, rs_val in review_state.items():
                    if rs_key not in REVIEW_STATE_KEYS:
                        errors.append(f"{obj['id']}: DomainMapping invalid review_state key {rs_key!r}")
                    elif not isinstance(rs_val, bool):
                        errors.append(f"{obj['id']}: DomainMapping review_state {rs_key!r} must be boolean")
        if obj.get("status") == "reviewed" and not obj.get("evidence_refs"):
            errors.append(f"{obj['id']}: reviewed DomainMapping requires non-empty evidence_refs")
    elif kind == "Insight":
        # 1차 제약(critic 검토 2, 2026-06-15): candidate Insight는 노출 통로가 없다
        # (advisories는 reviewed만). candidate로 두면 회상 어디에도 안 떠 조용히 묻히므로
        # 적재 자체를 거부한다. 후보 통로(promotable) 신설 시 이 블록을 제거한다.
        if obj.get("status") == "candidate":
            errors.append(
                f"{obj['id']}: candidate Insight not supported (no recall channel — "
                f"only reviewed surfaces via advisories; would be silently buried)")
        # spec(2026-06-15) §4.2·§4.7: insight_type 값 enum + source 개수 검사.
        # KIND_REQUIRED가 source_object_ids "존재"만 보므로(빈 리스트도 통과) 개수는 여기서.
        insight_type = obj.get("insight_type")
        if insight_type is not None and insight_type not in INSIGHT_TYPE_VALUES:
            errors.append(f"{obj['id']}: Insight invalid insight_type {insight_type!r}")
        source_ids = obj.get("source_object_ids")
        if isinstance(source_ids, list):
            min_required = 2 if insight_type == "cross-cutting-risk" else 1
            if len(source_ids) < min_required:
                errors.append(
                    f"{obj['id']}: Insight requires >={min_required} source_object_ids "
                    f"(insight_type={insight_type!r})")
    elif kind == "ReviewRecord":
        # 선택 필드(검증·강제 안 함, 버전 bump 없음, spec §4.5):
        #   vouched_by_mapping_ids: list[str] — auto:mapping-vouched 승격이 보증한 reviewed 매핑 id.
        #   conflict_resolution: str — 수동 conflict 용어 승격 시 정설 선택 근거.
        review_type = obj.get("review_type")
        if review_type is not None and review_type not in REVIEW_TYPE_VALUES:
            errors.append(f"{obj['id']}: ReviewRecord invalid review_type {review_type!r}")
        review_scope = obj.get("review_scope")
        if review_scope is not None and review_scope not in REVIEW_SCOPE_VALUES:
            errors.append(f"{obj['id']}: ReviewRecord invalid review_scope {review_scope!r}")
        if review_scope == "mapping_bundle":
            if not obj.get("target_object_ids"):
                errors.append(f"{obj['id']}: mapping_bundle ReviewRecord requires target_object_ids")
            if not obj.get("confirmation_key"):
                errors.append(f"{obj['id']}: mapping_bundle ReviewRecord requires confirmation_key")
        elif "target_object_id" not in obj:
            errors.append(f"{obj['id']}: ReviewRecord missing field 'target_object_id'")
    return errors
