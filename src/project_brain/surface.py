"""kind별 객체 텍스트 표면 추출 + content_hash (검색 색인 입력).

spec: docs/superpowers/specs/2026-06-10-project-brain-search-layer-design.md §2.1·§4

색인 대상 객체에서 "검색이 매칭할 텍스트"만 뽑아 하나의 문자열로 만든다(표면).
색인 제외 kind(EvidenceManifest/EvidenceRef/ReviewRecord 및
§2.1 표에 없는 kind)는 None을 돌려 색인에서 빠진다.
ContextProjection은 prompt_payload면 별도 레인(projection_reuse)으로 색인되고,
context_md 덤프는 표면이 None이다(2026-06-17).

content_hash는 객체 JSON 전체가 아니라 추출 표면 + status의 SHA-256이다(§4).
이렇게 하면 updated_at만 바뀌는 멱등 재저장은 해시가 안 바뀌어 재색인을 안 부르고,
추출 로직(EXTRACTOR_VERSION)이 바뀌면 색인 meta 불일치로 rebuild가 트리거된다.

★실코퍼스 대조 결과(2026-06-10, brain/objects/ 샘플 + schema.py KIND_REQUIRED)★
- spec §2.1 표는 GlossaryTerm 표면에 avoid/boundary를 예시로 들지만, 실코퍼스
  GlossaryTerm 125개에 avoid·boundary 필드는 0건이다. synonyms는 1건, aliases는
  1건만 존재. 그래도 표면 추출은 필드가 있으면 포함하는 방식(있으면 쓰고 없으면
  건너뜀)이라 데이터가 채워지면 자동 반영된다.
- DomainMapping은 표 예시(meaning/boundary/canonical_summary) 외에 caveats(list)와
  title도 실재한다. caveats는 history_coverage 같은 한계 표기라 표면에 넣지 않는다.
"""

from project_brain.hash_utils import sha256_text

# 추출 로직이 바뀌면 올린다(§4 meta의 rebuild 트리거). v2: Insight 추출기 추가(2026-06-15). v3: ContextProjection 추출기 추가(2026-06-17).
EXTRACTOR_VERSION = 3

# §2.1 색인 제외 kind. 이 목록에 든 kind는 extract_surface가 None을 돌려준다.
# 표에 없는(미지원) kind도 None이 되도록, 추출은 _EXTRACTORS dispatch로만 한다.
# ContextProjection은 별도 레인(projection_reuse)으로 색인되므로 제외 목록에서 뺐다(2026-06-17).
EXCLUDED_KINDS = frozenset({
    "EvidenceManifest", "EvidenceRef", "ReviewRecord",
})


def _norm_str(value) -> str | None:
    """문자열이고 공백 제거 후 내용이 있으면 strip 결과, 아니면 None."""
    if isinstance(value, str):
        s = value.strip()
        if s:
            return s
    return None


def _norm_list(value) -> list[str]:
    """리스트 안의 빈 문자열 아닌 문자열만 모은다(원래 순서 유지)."""
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        s = _norm_str(item)
        if s is not None:
            out.append(s)
    return out


def _surface_glossary_term(obj, store) -> list[str]:
    # spec §2.1: term, synonyms, aliases, avoid, definition, boundary
    # (avoid/boundary는 실코퍼스 GlossaryTerm에 없지만 있으면 포함.)
    parts: list[str] = []
    for field in ("term", "definition", "boundary"):
        s = _norm_str(obj.get(field))
        if s is not None:
            parts.append(s)
    for field in ("synonyms", "aliases", "avoid"):
        parts.extend(_norm_list(obj.get(field)))
    return parts


def _surface_domain_mapping(obj, store) -> list[str]:
    # spec §2.1: meaning, boundary, canonical_summary + 참조 용어의 term/synonyms.
    # 참조 용어 표면 위임은 현 라우터 _matched_mappings(router.py:379-397) 로직 계승 —
    # term + synonyms만 더하고(aliases는 라우터 매핑 경로도 안 씀), 없는 id는 건너뜀.
    parts: list[str] = []
    for field in ("canonical_summary", "meaning", "boundary"):
        s = _norm_str(obj.get(field))
        if s is not None:
            parts.append(s)
    for term_id in obj.get("glossary_term_ids") or []:
        if store is None or not store.has(term_id):
            continue
        term = store.get(term_id)
        s = _norm_str(term.get("term"))
        if s is not None:
            parts.append(s)
        parts.extend(_norm_list(term.get("synonyms")))
    return parts


def _surface_decision_record(obj, store) -> list[str]:
    # 실코퍼스 DecisionRecord 필드: summary(결정 내용)·decision(이유·상세).
    parts: list[str] = []
    for field in ("summary", "decision"):
        s = _norm_str(obj.get(field))
        if s is not None:
            parts.append(s)
    return parts


def _surface_temporal_fact(obj, store) -> list[str]:
    # spec §2.1: subject·predicate·value·summary 류. schema.py KIND_REQUIRED 기준.
    # (실코퍼스 데이터 0건 — 추출 함수만 정의, 적재되면 자동 포함.)
    parts: list[str] = []
    for field in ("subject", "predicate", "value", "summary"):
        s = _norm_str(obj.get(field))
        if s is not None:
            parts.append(s)
    return parts


def _surface_event_ledger_record(obj, store) -> list[str]:
    # spec §2.1: summary 류. schema EventLedgerRecord 필수 = summary.
    parts: list[str] = []
    s = _norm_str(obj.get("summary"))
    if s is not None:
        parts.append(s)
    return parts


def _surface_current_view(obj, store) -> list[str]:
    # spec §2.1: summary 류. schema CurrentView 필수 = summary.
    parts: list[str] = []
    s = _norm_str(obj.get("summary"))
    if s is not None:
        parts.append(s)
    return parts


def _surface_code_locator(obj, store) -> list[str]:
    # spec §2.1: path + symbol (예: "MinaKayakPopups MinaKayakEventAlertPopup::init").
    parts: list[str] = []
    for field in ("path", "symbol"):
        s = _norm_str(obj.get(field))
        if s is not None:
            parts.append(s)
    return parts


def _surface_domain_context(obj, store) -> list[str]:
    # spec §2.1: display_name, boundary_summary.
    parts: list[str] = []
    for field in ("display_name", "boundary_summary"):
        s = _norm_str(obj.get(field))
        if s is not None:
            parts.append(s)
    return parts


def _surface_insight(obj, store) -> list[str]:
    # spec(2026-06-15 Insight kind): 자유 텍스트 본문 + 적용 범위가 검색 표면.
    # source_object_ids/code_locator_ids는 linked(그래프 동반)로 따라가므로 표면에 안 넣는다.
    parts: list[str] = []
    for field in ("body", "scope"):
        s = _norm_str(obj.get(field))
        if s is not None:
            parts.append(s)
    return parts


def _surface_context_projection(obj, store) -> list[str]:
    # prompt_payload 재사용 projection만 검색 표면을 가진다. context_md 덤프는 None.
    if obj.get("format") != "prompt_payload":
        return []
    parts: list[str] = []
    for field in ("title", "reuse_payload"):
        s = _norm_str(obj.get(field))
        if s is not None:
            parts.append(s)
    return parts


# kind → 표면 추출 함수. 여기 없는 kind는 extract_surface가 None.
_EXTRACTORS = {
    "GlossaryTerm": _surface_glossary_term,
    "DomainMapping": _surface_domain_mapping,
    "DecisionRecord": _surface_decision_record,
    "TemporalFact": _surface_temporal_fact,
    "EventLedgerRecord": _surface_event_ledger_record,
    "CurrentView": _surface_current_view,
    "CodeLocator": _surface_code_locator,
    "DomainContext": _surface_domain_context,
    "Insight": _surface_insight,
    "ContextProjection": _surface_context_projection,
}


def extract_surface(obj, store) -> str | None:
    """색인할 텍스트 표면을 반환한다. 색인 제외/미지원 kind는 None.

    표면이 모두 비어 있으면(텍스트 필드가 다 없거나 빈 문자열) None을 돌려
    빈 행이 색인에 들어가지 않게 한다.
    """
    kind = obj.get("kind")
    if kind in EXCLUDED_KINDS:
        return None
    extractor = _EXTRACTORS.get(kind)
    if extractor is None:
        return None
    parts = extractor(obj, store)
    parts = [p for p in parts if p]
    if not parts:
        return None
    return "\n".join(parts)


def content_hash(obj, store) -> str:
    """추출 텍스트 표면 + status의 SHA-256(§4).

    객체 JSON 전체가 아니라 표면+status만 해싱하므로, updated_at만 바뀌는 멱등
    재저장은 해시가 불변이다. status 변경(candidate→reviewed 등)은 해시를 바꾼다.
    표면이 없는(색인 제외) 객체도 결정론 해시를 돌려준다(빈 표면 + status).
    """
    surface = extract_surface(obj, store) or ""
    status = obj.get("status") or ""
    return sha256_text(f"{status}\n{surface}")
