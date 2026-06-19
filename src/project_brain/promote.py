"""candidate 객체를 reviewed로 승격하는 generic promote — 도메인 무지.

폐기 ingest_mina_kayak_source.build_reviewed_terms(single_object)의 변환을 흡수한다.
GlossaryTerm 전용 title 문구("Reviewed term: ")는 흡수하지 않는다(spec §3.2) — title은
caller가 bundle에 미리 박는다. reviewer/reviewed_at은 caller 주입(도메인/시점 상수 0).

review_extra_by_id(single_object 전용)는 {object_id: {추가필드}}로, 각 검수기록에 per-id로
merge한다 — 자동 승격의 vouched_by_mapping_ids(§4.5), 수동 conflict 해소 기록(§4.4)에 쓴다.
"""

from project_brain.objbase import review_record


def vouching_mappings(term_id, store):
    """이 용어를 glossary_term_ids로 참조하는 reviewed DomainMapping 목록(id 오름차순).

    candidate 매핑은 보증하지 않는다(reviewed만). 결정론을 위해 id로 정렬한다.
    """
    matched = [
        m for m in store.by_kind("DomainMapping")
        if m.get("status") == "reviewed" and term_id in (m.get("glossary_term_ids") or [])
    ]
    return sorted(matched, key=lambda m: m["id"])


def backfill_evidence(term, store):
    """candidate term의 evidence_refs가 비면 짝 reviewed 매핑 evref 합집합으로 채운 새 dict 반환.

    합집합은 중복 제거 + store.has 실존하는 것만(깨진 참조 제외, spec §4.1). 이미 근거가
    있으면 손대지 않는다(최소 변경). 원본은 불변(dict 복사 반환).
    """
    out = dict(term)
    if out.get("evidence_refs"):
        return out
    union = []
    seen = set()
    for mapping in vouching_mappings(term["id"], store):
        for ref in mapping.get("evidence_refs") or []:
            if ref not in seen and store.has(ref):
                seen.add(ref)
                union.append(ref)
    out["evidence_refs"] = union
    return out


def select_vouched_candidates(store):
    """1단계 기계 선별(spec §4.2): reviewed 매핑이 참조하는 비-conflict candidate GlossaryTerm.

    반환: {term_id: [보증 reviewed 매핑 id 오름차순]}. 매핑 미참조·conflict·reviewed는 제외.
    실코퍼스 기준 115개(122 candidate − 7 conflict, 미참조 0)를 산출한다.
    """
    vouchers = {}  # term_id -> set(mapping_id)
    for mapping in store.by_kind("DomainMapping"):
        if mapping.get("status") != "reviewed":
            continue
        for tid in mapping.get("glossary_term_ids") or []:
            vouchers.setdefault(tid, set()).add(mapping["id"])
    result = {}
    for term in store.by_kind("GlossaryTerm"):
        if term.get("status") != "candidate":
            continue
        if (term.get("candidate") or {}).get("candidate_state") == "conflict":
            continue
        tid = term["id"]
        if tid in vouchers:
            result[tid] = sorted(vouchers[tid])
    return result


def promote(objects, ids, scope, *, bundle_key=None, reviewer, reviewed_at,
            review_extra_by_id=None):
    """ids에 해당하는 객체를 reviewed로 승격하고 (promoted_objects, review_records)를 반환.

    scope == "single_object": 각 id를 독립 승격. candidate 키 통째 pop + 객체별
    ReviewRecord(target_object_id 단수, 승격 객체 evidence_refs 복사) 생성.

    scope == "mapping_bundle": ids 전체를 한 review bundle로 승격. 각 mapping을
    reviewed로 바꾸고 공유 review_record_id + review_state 3키를 박는다. 단일
    bundle ReviewRecord(target_object_ids 복수, bundle_key/confirmation_key) 1개 생성.
    bundle_key가 없으면 ValueError.
    """
    index = {o["id"]: o for o in objects}
    if scope == "single_object":
        extra_by_id = review_extra_by_id or {}
        promoted_objects = []
        review_records = []
        for tid in ids:
            obj = index[tid]  # 없는 id면 KeyError
            reviewed = dict(obj)
            reviewed["status"] = "reviewed"
            reviewed["updated_at"] = reviewed_at
            reviewed.pop("candidate", None)
            review_id = "review." + reviewed["id"]
            reviewed["review_record_id"] = review_id
            rr = review_record(
                review_id,
                target_object_id=reviewed["id"],
                reviewer=reviewer,
                reviewed_at=reviewed_at,
                verdict="approved",
                tags=reviewed.get("tags", []),
                created_at=reviewed_at,
                updated_at=reviewed_at,
                evidence_refs=reviewed.get("evidence_refs", []),
                **extra_by_id.get(tid, {}),
            )
            promoted_objects.append(reviewed)
            review_records.append(rr)
        return promoted_objects, review_records
    if scope == "mapping_bundle":
        if not bundle_key:
            raise ValueError("mapping_bundle promote requires bundle_key")
        review_id = "review." + bundle_key
        promoted_objects = []
        for mid in ids:
            obj = index[mid]  # 없는 id면 KeyError
            m = dict(obj)
            m["status"] = "reviewed"
            m["updated_at"] = reviewed_at
            m["review_record_id"] = review_id
            m["review_state"] = {
                "meaning_reviewed": True,
                "evidence_reviewed": True,
                "projection_reviewed": True,
            }
            m.pop("candidate", None)
            promoted_objects.append(m)
        rr = review_record(
            review_id,
            target_object_ids=list(ids),
            reviewer=reviewer,
            reviewed_at=reviewed_at,
            verdict="approved",
            tags=[],
            created_at=reviewed_at,
            updated_at=reviewed_at,
            review_type="meaning_review",
            review_scope="mapping_bundle",
            bundle_key=bundle_key,
            confirmation_key=bundle_key,
        )
        return promoted_objects, [rr]
    raise ValueError(f"unknown promote scope {scope!r}")
