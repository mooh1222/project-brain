"""오프라인 무결성 검사. store 전체를 스캔해 object-model 불변조건 위반을 모아 보고한다.
런타임(router ⑤ _resolve_current_conflicts)은 쿼리 시점 충돌만, Lint는 전수 선제 검사.
충돌 탐지는 router의 순수 함수 _conflicting_fact_groups를 재사용한다(중복 구현 금지)."""

from dataclasses import dataclass
from pathlib import Path

from project_brain.hash_utils import sha256_text as _sha256_text
from project_brain.hash_utils import source_content_hash as _source_content_hash
from project_brain.promote import select_vouched_candidates
from project_brain.reference_fields import ObjectRef, iter_object_refs
from project_brain.router import _conflicting_fact_groups
from project_brain.schema import (
    VALID_KINDS,
    id_problem_code,
    validate_mutation_input_schema,
    validate_object_id,
    validate_object_schema,
)
from project_brain.store import BrainStore

GENERATED_HEADER = "GENERATED FROM PROJECT BRAIN - DO NOT EDIT"
LEGACY_SOURCE_TYPES = {"context", "wiki"}


@dataclass(frozen=True, order=True)
class LintProblem:
    code: str
    object_ids: tuple[str, ...]
    message: str


def _object_id(obj: dict) -> str:
    value = obj.get("id")
    return value if isinstance(value, str) else "?"


def _pointer_field(pointer: str) -> str:
    tokens = [token.replace("~1", "/").replace("~0", "~")
              for token in pointer.removeprefix("/").split("/")]
    if tokens[-1].isdigit():
        return tokens[-2]
    return tokens[-1]


def _dangling_label(obj: dict, ref: ObjectRef) -> str:
    field = _pointer_field(ref.pointer)
    if field == "evidence_refs":
        return "evidence_ref"
    if obj.get("kind") == "CurrentView" and field == "source_fact_ids":
        return "source_fact_id"
    if obj.get("kind") == "ContextProjection" and field == "source_object_ids":
        return "source_object_id"
    return field


def _compute_source_content_hash(store: BrainStore, source_object_ids: list[str]) -> str:
    """source_object_ids 에 해당하는 현재 store 내용으로 source_content_hash 를 재계산한다.

    시각·버전 메타 제외는 hash_utils.source_content_hash가 담당한다(생성식과 단일 공식 공유)."""
    return _source_content_hash(store.get(oid) for oid in source_object_ids if store.has(oid))


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


def _lint_store_report(
    store: BrainStore,
    workspace_root: Path | None,
    *,
    mutation_input: bool,
) -> tuple[LintProblem, ...]:
    problems: list[LintProblem] = []
    objs = store.all()

    def add(code: str, object_ids: tuple[str, ...], message: str) -> None:
        problems.append(
            LintProblem(
                code=code,
                object_ids=tuple(sorted(object_ids)),
                message=message,
            )
        )

    # 1) 스키마 위반 (kind별 필수 필드)
    schema_valid_objs: list[dict] = []
    for obj in objs:
        object_id = _object_id(obj)
        schema_problems = (
            validate_mutation_input_schema(obj)
            if mutation_input
            else validate_object_schema(obj)
        )
        for message in schema_problems:
            add("schema", (object_id,), message)
        id_problems = (
            validate_object_id(obj)
            if obj.get("kind") in VALID_KINDS
            else []
        )
        for message in id_problems:
            add(id_problem_code(obj), (object_id,), message)
        if not schema_problems and not id_problems:
            schema_valid_objs.append(obj)

    # 타입을 전제로 하는 후속 의미 검사는 schema-valid 객체만 소비한다. 위반 객체를
    # 계속 흘리면 malformed 참조 원소가 hash lookup 등에서 예외를 내 schema 진단을 가린다.
    # 단 공용 iter 기반 dangling은 malformed를 안전히 skip하므로 원본 objs/store로 전수한다.
    semantic_store = BrainStore({obj["id"]: obj for obj in schema_valid_objs})

    # 2) 같은 subject+predicate에 valid_until 없는 reviewed fact가 값 갈리며 2+ (object-model L298)
    for group in _conflicting_fact_groups(semantic_store.by_kind("TemporalFact")):
        object_ids = tuple(sorted(f["id"] for f in group))
        ids = ", ".join(object_ids)
        add(
            "temporal_conflict",
            object_ids,
            f"conflict: open reviewed facts [{ids}] share subject+predicate but differ in value",
        )

    # 3) 공용 registry가 선언한 Brain 객체 참조의 dangling 검사.
    for obj in objs:
        for ref in iter_object_refs(obj):
            if not store.has(ref.object_id):
                label = _dangling_label(obj, ref)
                object_id = _object_id(obj)
                add(
                    "dangling_reference",
                    (object_id,),
                    f"{object_id}: dangling {label} {ref.object_id}",
                )

    # 4) DomainContext v2: legacy path/source_format must not be canonical fields.
    for context in semantic_store.by_kind("DomainContext"):
        for legacy_field in ("path", "source_format"):
            if legacy_field in context:
                add(
                    "domain_context_legacy_field",
                    (context["id"],),
                    f"{context['id']}: DomainContext legacy field {legacy_field} is not allowed",
                )

    # 5) GlossaryTerm lifecycle/evidence guard.
    for term in semantic_store.by_kind("GlossaryTerm"):
        if term.get("status") == "candidate" and not term.get("candidate"):
            add(
                "glossary_lifecycle",
                (term["id"],),
                f"{term['id']}: candidate GlossaryTerm missing candidate metadata",
            )
        candidate = term.get("candidate") or {}
        if term.get("status") == "reviewed":
            if candidate.get("candidate_state") == "conflict" or candidate.get("open_questions"):
                add(
                    "glossary_lifecycle",
                    (term["id"],),
                    f"{term['id']}: reviewed GlossaryTerm has unresolved candidate metadata",
                )
            if _has_only_legacy_evidence(semantic_store, term):
                add(
                    "legacy_only_evidence",
                    (term["id"],),
                    f"{term['id']}: reviewed GlossaryTerm has legacy-only evidence",
                )
        if term.get("status") == "rejected" and not term.get("rejection"):
            add(
                "glossary_lifecycle",
                (term["id"],),
                f"{term['id']}: rejected GlossaryTerm missing rejection metadata",
            )

    # 6) ContextProjection guard.
    for projection in semantic_store.by_kind("ContextProjection"):
        if projection.get("manual_edit_detected"):
            add(
                "projection_manual_edit",
                (projection["id"],),
                f"{projection['id']}: manual_edit_detected is true",
            )
        source_object_ids = projection.get("source_object_ids") or []
        if source_object_ids:
            expected_hash = _compute_source_content_hash(
                semantic_store,
                source_object_ids,
            )
            if expected_hash != projection.get("source_content_hash"):
                add(
                    "projection_source_hash_mismatch",
                    (projection["id"],),
                    (
                        f"{projection['id']}: source_content_hash mismatch"
                        " (source objects changed since projection was generated)"
                    ),
                )
        if workspace_root is not None:
            for message in _lint_generated_projection_file(
                projection,
                Path(workspace_root),
            ):
                add("projection_file_mismatch", (projection["id"],), message)

    # 7) DomainMapping / DecisionRecord lifecycle integrity (spec §5, §6.1, §8.3).
    mappings = semantic_store.by_kind("DomainMapping")
    decisions = semantic_store.by_kind("DecisionRecord")

    # 7a) review-needed drift (spec §8.3): a decision affects a reviewed mapping the mapping has
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
            add(
                "unincorporated_decision",
                (mapping_id, decision["id"]),
                (
                    f"{mapping_id}: unincorporated decision {decision['id']} "
                    "may affect reviewed mapping; review needed "
                    f"(spec_reflected={decision.get('spec_reflected')})"
                ),
            )

    # 7b) supersession consistency: a mapping superseded by another must not stay reviewed.
    for mapping in mappings:
        for superseded_id in mapping.get("supersedes_mapping_ids") or []:
            if not semantic_store.has(superseded_id):
                continue  # dangling은 공용 registry 검사에서 이미 보고됨
            if semantic_store.get(superseded_id).get("status") == "reviewed":
                add(
                    "supersession_lifecycle",
                    (superseded_id, mapping["id"]),
                    (
                        f"{superseded_id}: superseded by {mapping['id']} "
                        "but status is still 'reviewed'"
                    ),
                )

    if workspace_root is not None:
        for message in _lint_generated_files_have_projection(
            semantic_store,
            Path(workspace_root),
        ):
            add("generated_file_without_projection", (), message)

    return tuple(problems)


def lint_store_report(
    store: BrainStore,
    workspace_root: Path | None = None,
) -> tuple[LintProblem, ...]:
    """최종 저장 객체에 대한 엄격한 구조화 lint."""
    return _lint_store_report(
        store,
        workspace_root,
        mutation_input=False,
    )


def lint_mutation_input_store_report(
    store: BrainStore,
    workspace_root: Path | None = None,
) -> tuple[LintProblem, ...]:
    """MutationService에 넘길 draft bundle 전용 lint.

    CodeLocator의 ``verified_at`` 누락만 verifier 실행 전까지 허용한다.
    일반/public lint와 최종 merged lint는 이 함수를 사용하지 않는다.
    """
    return _lint_store_report(
        store,
        workspace_root,
        mutation_input=True,
    )


def lint_store(store: BrainStore, workspace_root: Path | None = None) -> list[str]:
    """호환용 문자열 message 목록 wrapper."""
    return [
        problem.message
        for problem in lint_store_report(store, workspace_root=workspace_root)
    ]
