"""오프라인 무결성 검사. store 전체를 스캔해 object-model 불변조건 위반을 모아 보고한다.
런타임(router ⑤ _resolve_current_conflicts)은 쿼리 시점 충돌만, Lint는 전수 선제 검사.
충돌 탐지는 router의 순수 함수 _conflicting_fact_groups를 재사용한다(중복 구현 금지)."""

from pathlib import Path

from project_brain.hash_utils import sha256_text as _sha256_text
from project_brain.hash_utils import stable_json as _stable_json
from project_brain.promote import select_vouched_candidates
from project_brain.router import _conflicting_fact_groups
from project_brain.schema import validate_object
from project_brain.store import BrainStore

GENERATED_HEADER = "GENERATED FROM PROJECT BRAIN - DO NOT EDIT"
LEGACY_SOURCE_TYPES = {"context", "wiki"}


def _compute_source_content_hash(store: BrainStore, source_object_ids: list[str]) -> str:
    """source_object_ids 에 해당하는 현재 store 내용으로 source_content_hash 를 재계산한다."""
    parts = [_stable_json(store.get(oid)) for oid in source_object_ids if store.has(oid)]
    return _sha256_text("\n".join(parts))


def projection_is_fresh(store: BrainStore, projection: dict) -> bool:
    """ContextProjection의 저장 source_content_hash가 현재 store로 재계산한 값과 같은가.

    구성 객체(source_object_ids)가 바뀌면 재계산 해시가 어긋나 False — 그 projection은
    낡았다. rebuild·compute_corpus_fingerprint가 같은 판정으로 stale projection을
    색인/지문에서 빼는 데 재사용한다(중복 구현 금지)."""
    source_object_ids = projection.get("source_object_ids") or []
    # source가 store에서 사라졌으면(dangling) 근거가 없어진 것이라 stale로 본다.
    # _compute_source_content_hash가 없는 id를 조용히 건너뛰므로, 여기서 막지 않으면
    # 없는 source만 가리키는 projection이 sha256("")로 fresh 통과해 색인에 남는다.
    if any(not store.has(oid) for oid in source_object_ids):
        return False
    expected_hash = _compute_source_content_hash(store, source_object_ids)
    return expected_hash == projection.get("source_content_hash")


def _source_type_for_evidence_ref(store: BrainStore, ref_id: str) -> str | None:
    if not store.has(ref_id):
        return None
    ref = store.get(ref_id)
    manifest_id = ref.get("evidence_manifest_id")
    if not manifest_id or not store.has(manifest_id):
        return None
    return store.get(manifest_id).get("source_type")


def _has_only_legacy_evidence(store: BrainStore, obj: dict) -> bool:
    refs = obj.get("evidence_refs", [])
    if not refs:
        return False
    source_types = [_source_type_for_evidence_ref(store, ref_id) for ref_id in refs]
    return bool(source_types) and all(source_type in LEGACY_SOURCE_TYPES for source_type in source_types)


def _lint_generated_projection_file(projection: dict, workspace_root: Path) -> list[str]:
    problems: list[str] = []
    output_locator = projection.get("output_locator")
    if not output_locator:
        return problems
    output_path = workspace_root / output_locator
    if not output_path.exists():
        return problems
    content = output_path.read_text(encoding="utf-8")
    if GENERATED_HEADER not in content:
        problems.append(
            f"{projection['id']}: generated header missing from {output_locator}"
        )
    actual_hash = _sha256_text(content)
    if actual_hash != projection.get("projection_hash"):
        problems.append(
            f"{projection['id']}: projection_hash mismatch for {output_locator}"
        )
    return problems


def _lint_generated_files_have_projection(store: BrainStore, workspace_root: Path) -> list[str]:
    problems: list[str] = []
    generated_root = workspace_root / "docs/contexts/generated"
    if not generated_root.exists():
        return problems
    projected_locators = {
        projection.get("output_locator")
        for projection in store.by_kind("ContextProjection")
        if projection.get("format") == "context_md"
    }
    for path in generated_root.rglob("CONTEXT.md"):
        rel = path.relative_to(workspace_root).as_posix()
        if rel not in projected_locators:
            problems.append(f"{rel}: generated context file has no ContextProjection")
    return problems


def unpromoted_vouched_terms(store: BrainStore) -> list[str]:
    """비차단 드리프트 경고(spec §4.6): reviewed 매핑이 보증하는데 아직 candidate인 비-conflict 용어.

    lint_store(차단 무결성)와 분리한다 — candidate는 적재 직후 정상이라 차단하면 모든 ingest가
    깨진다. 자동 승격(promote-auto) + 커버리지 통과분 적재 후엔 0이어야 하며, 남는 것은
    커버리지 보류분(사람 검토 큐, §8). conflict는 selection에서 제외돼 여기 안 뜬다(별도 신호).
    """
    warnings = []
    for tid, mapping_ids in sorted(select_vouched_candidates(store).items()):
        warnings.append(
            f"{tid}: vouched by reviewed mapping {mapping_ids} but still candidate; "
            f"run promote-auto after coverage verification (non-blocking drift)"
        )
    return warnings


def lint_store(store: BrainStore, workspace_root: Path | None = None) -> list[str]:
    problems: list[str] = []
    objs = store.all()

    # 1) 스키마 위반 (kind별 필수 필드)
    for obj in objs:
        problems.extend(validate_object(obj))

    # 2) 같은 subject+predicate에 valid_until 없는 reviewed fact가 값 갈리며 2+ (object-model L298)
    for group in _conflicting_fact_groups(store.by_kind("TemporalFact")):
        ids = ", ".join(sorted(f["id"] for f in group))
        problems.append(f"conflict: open reviewed facts [{ids}] share subject+predicate but differ in value")

    # 3) CurrentView가 없는 fact를 가리킴
    for view in store.by_kind("CurrentView"):
        for fid in view.get("source_fact_ids", []):
            if not store.has(fid):
                problems.append(f"{view['id']}: dangling source_fact_id {fid}")

    # 4) dangling evidence_refs / review_record_id
    for obj in objs:
        for ref in obj.get("evidence_refs", []):
            if not store.has(ref):
                problems.append(f"{obj['id']}: dangling evidence_ref {ref}")
        rrid = obj.get("review_record_id")
        if rrid and not store.has(rrid):
            problems.append(f"{obj['id']}: dangling review_record_id {rrid}")

    # 5) DomainContext v2: legacy path/source_format must not be canonical fields.
    for context in store.by_kind("DomainContext"):
        for legacy_field in ("path", "source_format"):
            if legacy_field in context:
                problems.append(f"{context['id']}: DomainContext legacy field {legacy_field} is not allowed")

    # 6) GlossaryTerm lifecycle/evidence guard.
    for term in store.by_kind("GlossaryTerm"):
        if term.get("status") == "candidate" and not term.get("candidate"):
            problems.append(f"{term['id']}: candidate GlossaryTerm missing candidate metadata")
        candidate = term.get("candidate") or {}
        if term.get("status") == "reviewed":
            if candidate.get("candidate_state") == "conflict" or candidate.get("open_questions"):
                problems.append(f"{term['id']}: reviewed GlossaryTerm has unresolved candidate metadata")
            if _has_only_legacy_evidence(store, term):
                problems.append(f"{term['id']}: reviewed GlossaryTerm has legacy-only evidence")
        if term.get("status") == "rejected" and not term.get("rejection"):
            problems.append(f"{term['id']}: rejected GlossaryTerm missing rejection metadata")

    # 7) ContextProjection guard.
    for projection in store.by_kind("ContextProjection"):
        if projection.get("manual_edit_detected"):
            problems.append(f"{projection['id']}: manual_edit_detected is true")
        source_object_ids = projection.get("source_object_ids") or []
        # dangling source_object_ids (DomainMapping 8a·DecisionRecord 8b·Insight 9와 동형):
        # 가리키는 근거가 사라지면 브리핑이 조용히 깨진다.
        for ref_id in source_object_ids:
            if ref_id and not store.has(ref_id):
                problems.append(f"{projection['id']}: dangling source_object_id {ref_id}")
        if source_object_ids:
            expected_hash = _compute_source_content_hash(store, source_object_ids)
            if expected_hash != projection.get("source_content_hash"):
                problems.append(
                    f"{projection['id']}: source_content_hash mismatch"
                    " (source objects changed since projection was generated)"
                )
        if workspace_root is not None:
            problems.extend(_lint_generated_projection_file(projection, Path(workspace_root)))

    # 8) DomainMapping / DecisionRecord lifecycle integrity (spec §5, §6.1, §8.3).
    mappings = store.by_kind("DomainMapping")
    decisions = store.by_kind("DecisionRecord")

    # 8a) dangling mapping reference links
    for mapping in mappings:
        link_fields = (
            ("context_id", [mapping.get("context_id")]),
            ("glossary_term_ids", mapping.get("glossary_term_ids") or []),
            ("decision_record_ids", mapping.get("decision_record_ids") or []),
            ("spec_revision_ids", mapping.get("spec_revision_ids") or []),
            ("code_locator_ids", mapping.get("code_locator_ids") or []),
            ("supersedes_mapping_ids", mapping.get("supersedes_mapping_ids") or []),
        )
        for field_name, ids in link_fields:
            for ref_id in ids:
                if ref_id and not store.has(ref_id):
                    problems.append(f"{mapping['id']}: dangling {field_name} {ref_id}")

    # 8b) dangling decision reference links
    for decision in decisions:
        link_fields = (
            ("source_object_ids", decision.get("source_object_ids") or []),
            ("affected_context_ids", decision.get("affected_context_ids") or []),
            ("affected_mapping_ids", decision.get("affected_mapping_ids") or []),
            ("affected_glossary_term_ids", decision.get("affected_glossary_term_ids") or []),
            ("spec_revision_ids", decision.get("spec_revision_ids") or []),
            ("jira_issue_ids", decision.get("jira_issue_ids") or []),
            ("slack_thread_ids", decision.get("slack_thread_ids") or []),
            ("code_locator_ids", decision.get("code_locator_ids") or []),
        )
        for field_name, ids in link_fields:
            for ref_id in ids:
                if ref_id and not store.has(ref_id):
                    problems.append(f"{decision['id']}: dangling {field_name} {ref_id}")

    # 8c) review-needed drift (spec §8.3): a decision affects a reviewed mapping the mapping has
    #     not incorporated (not in decision_record_ids) and is not superseded (status != reviewed).
    #     Blocking, and mapping-specific — never a whole-bundle rollback (spec §6.1).
    #     Detection is by non-incorporation (update-ingest arrival order), NOT wall-clock
    #     timestamps: fixtures share one timestamp, and "affects but not incorporated" is the
    #     precise drift signal — a created_at gate would both miss old-but-unincorporated
    #     decisions and break the same-timestamp Jira update fixture.
    mappings_by_id = {m["id"]: m for m in mappings}
    for decision in decisions:
        for mapping_id in decision.get("affected_mapping_ids") or []:
            mapping = mappings_by_id.get(mapping_id)
            if mapping is None or mapping.get("status") != "reviewed":
                continue
            if decision["id"] in (mapping.get("decision_record_ids") or []):
                continue
            problems.append(
                f"{mapping_id}: unincorporated decision {decision['id']} may affect reviewed mapping; "
                f"review needed (spec_reflected={decision.get('spec_reflected')})"
            )

    # 8d) supersession consistency: a mapping superseded by another must not stay reviewed.
    for mapping in mappings:
        for superseded_id in mapping.get("supersedes_mapping_ids") or []:
            if not store.has(superseded_id):
                continue  # dangling already reported in 8a
            if store.get(superseded_id).get("status") == "reviewed":
                problems.append(
                    f"{superseded_id}: superseded by {mapping['id']} but status is still 'reviewed'"
                )

    # 8e) ReviewRecord target resolution (single + bundle).
    for review in store.by_kind("ReviewRecord"):
        target = review.get("target_object_id")
        if target and not store.has(target):
            problems.append(f"{review['id']}: dangling target_object_id {target}")
        for target_id in review.get("target_object_ids") or []:
            if not store.has(target_id):
                problems.append(f"{review['id']}: dangling target_object_ids {target_id}")

    # 9) Insight dangling source_object_ids / code_locator_ids (spec 2026-06-15 §4.7).
    #    "여러 객체를 가로지른다"가 본질이라 가리키는 근거가 사라지면 조용히 깨진다 —
    #    DomainMapping(8a)·DecisionRecord(8b)와 동형으로 막는다.
    for insight in store.by_kind("Insight"):
        link_fields = (
            ("source_object_ids", insight.get("source_object_ids") or []),
            ("code_locator_ids", insight.get("code_locator_ids") or []),
        )
        for field_name, ids in link_fields:
            for ref_id in ids:
                if ref_id and not store.has(ref_id):
                    problems.append(f"{insight['id']}: dangling {field_name} {ref_id}")

    if workspace_root is not None:
        problems.extend(_lint_generated_files_have_projection(store, Path(workspace_root)))

    return problems
