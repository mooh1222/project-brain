from project_brain.hash_utils import sha256_text as _sha256_text
from project_brain.hash_utils import stable_json as _stable_json
from project_brain.store import BrainStore

GENERATED_HEADER = "GENERATED FROM PROJECT BRAIN - DO NOT EDIT"
SCHEMA_VERSION = "0.1"


def _reviewed_terms_for_context(store: BrainStore, context: dict) -> list[dict]:
    terms = []
    for term_id in context.get("glossary_term_ids", []):
        if not store.has(term_id):
            continue
        term = store.get(term_id)
        if term.get("kind") == "GlossaryTerm" and term.get("status") == "reviewed":
            terms.append(term)
    return sorted(terms, key=lambda term: term.get("term", ""))


def _reviewed_mappings_for_context(store: BrainStore, context_id: str) -> list[dict]:
    mappings = [
        obj for obj in store.by_kind("DomainMapping")
        if obj.get("context_id") == context_id and obj.get("status") == "reviewed"
    ]
    return sorted(mappings, key=lambda mapping: mapping.get("mapping_key", ""))


def render_context_markdown(store: BrainStore, context_id: str) -> str:
    context = store.get(context_id)
    terms = _reviewed_terms_for_context(store, context)
    lines = [
        GENERATED_HEADER,
        f"source_context_id: {context_id}",
        "",
        f"# {context.get('display_name') or context.get('title')}",
        "",
        "## Boundary",
        "",
        context.get("boundary_summary", ""),
        "",
        "## In scope",
        "",
    ]
    lines.extend(f"- {item}" for item in context.get("in_scope", []))
    lines.extend(["", "## Out of scope", ""])
    lines.extend(f"- {item}" for item in context.get("out_of_scope", []))
    lines.extend(["", "## Reviewed glossary", ""])
    if not terms:
        lines.append("_No reviewed terms._")
    for term in terms:
        lines.append(f"### {term['term']}")
        lines.append("")
        lines.append(term["definition"])
        avoid = term.get("avoid") or []
        if avoid:
            lines.append("")
            lines.append("Avoid aliases: " + ", ".join(avoid))
        synonyms = term.get("synonyms") or []
        if synonyms:
            lines.append("")
            lines.append("Synonyms: " + ", ".join(synonyms))
        scope_hint = term.get("scope_hint") or {}
        if scope_hint:
            rendered_scope = ", ".join(f"{key}={value}" for key, value in sorted(scope_hint.items()))
            lines.append("")
            lines.append("Scope hint: " + rendered_scope)
        lines.append("")
    mappings = _reviewed_mappings_for_context(store, context_id)
    lines.extend(["", "## Reviewed mappings", ""])
    if not mappings:
        lines.append("_No reviewed mappings._")
    for mapping in mappings:
        lines.append(f"### {mapping['mapping_key']}")
        lines.append("")
        lines.append(mapping.get("canonical_summary", ""))
        lines.append("")
        lines.append("Meaning: " + mapping.get("meaning", ""))
        lines.append("")
        lines.append("Boundary: " + mapping.get("boundary", ""))
        non_goals = mapping.get("non_goals") or []
        if non_goals:
            lines.append("")
            lines.append("Non-goals: " + "; ".join(non_goals))
        caveats = mapping.get("caveats") or []
        if caveats:
            lines.append("")
            lines.append("Caveats: " + "; ".join(caveats))
        code_locator_ids = mapping.get("code_locator_ids") or []
        if code_locator_ids:
            lines.append("")
            lines.append("Code locators: " + ", ".join(code_locator_ids))
        projection_notes = mapping.get("projection_notes") or []
        if projection_notes:
            lines.append("")
            lines.append("Projection notes: " + "; ".join(projection_notes))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_context_projection(
    store: BrainStore,
    context_id: str,
    *,
    output_locator: str,
    generated_at: str,
    generated_by: str,
) -> tuple[dict, str]:
    context = store.get(context_id)
    terms = _reviewed_terms_for_context(store, context)
    mappings = _reviewed_mappings_for_context(store, context_id)
    source_objects = [context] + terms + mappings
    source_object_ids = [obj["id"] for obj in source_objects]
    source_content_hash = _sha256_text("\n".join(_stable_json(obj) for obj in source_objects))
    content = render_context_markdown(store, context_id)
    projection_hash = _sha256_text(content)
    projection_id = f"projection.{context.get('context_key', context_id)}.context-md"
    projection = {
        "id": projection_id,
        "kind": "ContextProjection",
        "schema_version": SCHEMA_VERSION,
        "status": "reviewed",
        "poc_priority": "P0",
        "truth_role": "index",
        "title": f"Generated context_md projection for {context.get('display_name') or context_id}",
        "created_at": generated_at,
        "updated_at": generated_at,
        "tags": context.get("tags", []),
        "evidence_refs": [],
        "context_id": context_id,
        "format": "context_md",
        "output_locator": output_locator,
        "source_object_ids": source_object_ids,
        "source_content_hash": source_content_hash,
        "projection_hash": projection_hash,
        "generated_at": generated_at,
        "generated_by": generated_by,
        "stale_policy": "fail_on_manual_edit",
    }
    return projection, content


def build_reuse_projection(
    store: BrainStore,
    *,
    context_id: str,
    requirement_key: str,
    source_object_ids: list,
    reuse_payload: str,
    title: str,
    generated_at: str,
    generated_by: str,
) -> dict:
    """요구 부분집합 prompt_payload candidate projection을 생성한다.

    source_object_ids에 해당하는 객체들의 내용으로 source_content_hash를 계산하고,
    reuse_payload 텍스트로 projection_hash를 계산한다. 두 해시 모두 필수 필드.
    """
    context = store.get(context_id)
    source_content_hash = _sha256_text(
        "\n".join(_stable_json(store.get(oid)) for oid in source_object_ids)
    )
    projection_hash = _sha256_text(reuse_payload)
    ckey = context.get("context_key", context_id)
    return {
        "id": f"projection.{ckey}.{requirement_key}.reuse",
        "kind": "ContextProjection",
        "schema_version": SCHEMA_VERSION,
        "status": "candidate",
        "poc_priority": "P0",
        "truth_role": "index",
        "title": title,
        "created_at": generated_at,
        "updated_at": generated_at,
        "tags": context.get("tags", []),
        "evidence_refs": [],
        "context_id": context_id,
        "format": "prompt_payload",
        "reuse_payload": reuse_payload,
        "output_locator": f"indexes/context_projections/{ckey}.{requirement_key}.reuse.txt",
        "source_object_ids": list(source_object_ids),
        "source_content_hash": source_content_hash,
        "projection_hash": projection_hash,
        "generated_at": generated_at,
        "generated_by": generated_by,
        "stale_policy": "fail_on_manual_edit",
    }
