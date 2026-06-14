"""코드 변경 → 의미 갱신 대상 발견 (stale-check) 로직.

spec: docs/superpowers/specs/2026-06-14-bb2-brain-stale-check-design.md
git 호출은 git_runner 콜러블로 주입한다 — 로직 함수는 git을 모른다(테스트는
합성 입력으로 대체, 네트워크·실레포 무관). 기계는 "어느 파일이 바뀌어 어느
매핑이 영향권인가"까지 찾고, "의미가 진짜 낡았나"는 사람이 판정한다.
"""
from __future__ import annotations


def _mappings_referencing(store, locator_id):
    """code_locator_ids에 locator_id를 가진 DomainMapping 목록(id 정렬). compute_closure 전용 내부 헬퍼."""
    out = [m for m in store.by_kind("DomainMapping")
           if locator_id in (m.get("code_locator_ids") or [])]
    return sorted(out, key=lambda m: m["id"])


def compute_closure(store, locator_id):
    """locator를 가리키는 매핑을 status로 분류.

    blocking = status==reviewed (현재 진실 — mark 충족 대상).
    nonblocking = candidate/superseded/archived/rejected (mark를 막지 않음).
    """
    blocking, nonblocking = [], []
    for m in _mappings_referencing(store, locator_id):
        if m.get("status") == "reviewed":
            blocking.append(m["id"])
        else:
            nonblocking.append(m["id"])
    return {"blocking": blocking, "nonblocking": nonblocking}


def _has_code_evidence_ref(store, mapping):
    """매핑의 evidence_refs 중 코드를 가리키는 것(ref_type=='code_locator')이 있나."""
    for rid in (mapping.get("evidence_refs") or []):
        if store.has(rid) and store.get(rid).get("ref_type") == "code_locator":
            return True
    return False


def coverage_report(store):
    """매핑을 code_locator_ids 유무로 분류(spec §3·§6).

    covered_mappings = code_locator_ids 비어있지 않음(stale-check 역추적 가능)의 id 목록.
    uncovered_mappings = 비었거나 키 없음의 [{mapping_id, skipped_reason, has_code_evidence_ref}]
      — "왜 사각인지"(skipped_reason)와 code EvidenceRef만 가진 부분집합
      (has_code_evidence_ref)을 출력 계약에 박아 가시화한다. 자동 처리는 안 한다.
    """
    covered, uncovered = [], []
    for m in store.by_kind("DomainMapping"):
        if m.get("code_locator_ids"):
            covered.append(m["id"])
        else:
            uncovered.append({
                "mapping_id": m["id"],
                "skipped_reason": "no_code_locator_ids",
                "has_code_evidence_ref": _has_code_evidence_ref(store, m),
            })
    return {"covered_mappings": sorted(covered),
            "uncovered_mappings": sorted(uncovered, key=lambda u: u["mapping_id"])}
