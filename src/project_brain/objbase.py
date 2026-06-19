"""공용 객체 조립 헬퍼 — 도메인 무지(domain-agnostic).

세 폐기 스크립트가 중복하던 base() setdefault 묶음을 caller 파라미터화한 단일
헬퍼로 모은다. status default는 빼서(spec §3.3) generic 부품이 도메인/시점에
무지하게 한다. ReviewRecord 조립도 헬퍼화한다.
"""


def base(obj, *, tags, created_at, updated_at, schema_version="0.1", poc_priority="P0"):
    """BASE_REQUIRED 공통 기본값을 setdefault로 채운다. caller가 준 키는 안 덮는다.

    status는 default하지 않는다(spec §3.3) — generic 부품의 도메인/시점 무지점.
    """
    defaults = {
        "schema_version": schema_version,
        "poc_priority": poc_priority,
        "created_at": created_at,
        "updated_at": updated_at,
        "tags": tags,
        "evidence_refs": [],
    }
    for k, v in defaults.items():
        obj.setdefault(k, v)
    return obj


def review_record(
    rid,
    *,
    target_object_id=None,
    target_object_ids=None,
    reviewer,
    reviewed_at,
    verdict,
    tags,
    created_at,
    updated_at,
    title="검수 기록",
    truth_role="review",
    **extra,
):
    """ReviewRecord 객체를 조립한다. base()로 공통 채우고 review 전용 필드를 박는다.

    target_object_id(단수, single_object)와 target_object_ids(복수, mapping_bundle)는
    caller가 모드에 맞게 넘긴다. extra는 review_scope/bundle_key/confirmation_key/
    review_type 등을 merge한다.
    """
    obj = {
        "id": rid,
        "kind": "ReviewRecord",
        "status": "reviewed",
        "truth_role": truth_role,
        "title": title,
        "reviewer": reviewer,
        "reviewed_at": reviewed_at,
        "verdict": verdict,
    }
    if target_object_id is not None:
        obj["target_object_id"] = target_object_id
    if target_object_ids is not None:
        obj["target_object_ids"] = target_object_ids
    obj.update(extra)
    return base(obj, tags=tags, created_at=created_at, updated_at=updated_at)
