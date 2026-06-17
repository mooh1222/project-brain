"""검색층 평가 하네스 (스펙 §8, 구현 슬라이스 1).

시나리오 파일(eval_scenarios.json)의 질의→기대 object_id 기준을 recall 응답에
대조한다. 측정값: top-5 적중, 그래프 동반, 반환 개수 상한, 게이트("없다" 유지),
(참고) 쿼리 지연. 실 코퍼스+실 모델 측정(슬라이스 3.5/6)도 이 하네스를 그대로 쓴다.

recall 응답 계약 — §3 결과 계약 + §7 채널 분리를 평가 관점에서 합친 형태.
슬라이스 3의 recall()(어댑터 경유)과 슬라이스 5의 라우터 통합이 이 형태를 채운다:

    {
      "results": [...],            # reviewed source 채널 (게이트 통과분, top-K)
      "candidates": [...],         # candidate 후보 채널 (§7 채널 분리 — 관대한 임계)
      "needs_clarification": bool  # 게이트 통과 0건 → True ("no evidence → 없다" 보존)
    }

results/candidates 원소는 §3 계약 dict(object_id, kind, status, score, matched_via,
surface, linked). 하네스는 object_id와 linked(code_locators/related_object_ids)만
본다 — linked 원소는 id 문자열이든 객체 dict든 허용(§3 계약이 객체 동반을 허용).
"""

import json
import time
from pathlib import Path

# 시나리오 expect에 허용되는 판정 키. 시나리오 파일은 데이터라 오타가 조용히
# 통과하면 측정이 비므로 load 시점에 미지 키를 거부한다.
ASSERTION_KEYS = {
    "top5_any",            # results 채널 top-5에 ≥1 적중
    "any_channel_top5_any",  # results/candidates 어느 채널이든 top-5에 ≥1 적중
    "linked_any_groups",   # results top-5의 그래프 동반에서 그룹별 ≥1 적중
    "max_results",         # results 반환 개수 상한 (무더기 반환 가드)
    "no_answer",           # 게이트 작동: needs_clarification=True + results 0건
    "raw_top5_prefix_any",  # raw_excerpts top-5에 프리픽스 일치 id ≥1 (§2.2 raw 채널 —
                            # 청크 id는 청커 산출이라 정확 id 대신 프리픽스로 판정)
    "advisories_top5_any",  # advisories(reviewed Insight) top-5에 ≥1 적중 (§4.6)
    "projection_reuse_top5_any",  # projection_reuse(ContextProjection 재사용) top-5에 ≥1 적중
                                  # (spec 2026-06-17 Task A5)
}


class ScenarioError(ValueError):
    """시나리오 파일 무결성 위반."""


def load_scenarios(path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ScenarioError("scenarios 배열이 비었거나 없음")
    seen = set()
    for sc in scenarios:
        for field in ("id", "query", "expect"):
            if not sc.get(field):
                raise ScenarioError(f"시나리오 필수 필드 누락: {field} ({sc.get('id')})")
        if sc["id"] in seen:
            raise ScenarioError(f"시나리오 id 중복: {sc['id']}")
        seen.add(sc["id"])
        unknown = set(sc["expect"]) - ASSERTION_KEYS
        if unknown:
            raise ScenarioError(f"미지 판정 키 {sorted(unknown)} ({sc['id']})")
    return scenarios


def expected_object_ids(scenarios) -> set[str]:
    """시나리오가 참조하는 모든 기대 object_id — 실코퍼스 존재 가드 테스트가 사용."""
    ids: set[str] = set()
    for sc in scenarios:
        expect = sc["expect"]
        ids.update(expect.get("top5_any") or [])
        ids.update(expect.get("any_channel_top5_any") or [])
        ids.update(expect.get("advisories_top5_any") or [])
        ids.update(expect.get("projection_reuse_top5_any") or [])
        for group in expect.get("linked_any_groups") or []:
            ids.update(group)
    return ids


def empty_recall(query) -> dict:
    """검색층 미구현 시의 stub — 빈 응답이므로 게이트 시나리오만 통과한다(의도된 빨간 베이스라인)."""
    return {"results": [], "candidates": [], "needs_clarification": True}


def load_recall_fn():
    """평가 진입점 회상 함수를 찾는다 → (recall_fn, implemented).

    슬라이스 3이 project_brain.search 모듈에 eval_recall(query)를 신설하면
    그쪽을 쓰고, 미구현이면 empty_recall로 빨간 베이스라인을 측정한다.
    """
    try:
        from project_brain.search import eval_recall  # 슬라이스 3 신설 예정
        return eval_recall, True
    except ImportError:
        return empty_recall, False


def _hit_ids(hits, limit=None) -> list[str]:
    sliced = hits if limit is None else hits[:limit]
    return [h.get("object_id") for h in sliced]


def _linked_ids(hit) -> list[str]:
    linked = hit.get("linked") or {}
    out = []
    for key in ("code_locators", "related_object_ids"):
        for entry in linked.get(key) or []:
            if isinstance(entry, str):
                out.append(entry)
            elif isinstance(entry, dict):
                out.append(entry.get("object_id") or entry.get("id"))
    return [oid for oid in out if oid]


def evaluate(recall_fn, scenarios) -> dict:
    """시나리오별 판정 + 요약. recall_fn 예외는 해당 시나리오 실패로 기록(부분 구현 측정 허용)."""
    scenario_reports = []
    for sc in scenarios:
        start = time.perf_counter()
        try:
            response = recall_fn(sc["query"])
        except Exception as exc:  # noqa: BLE001 — 측정 리포트에 실패 사유를 남기는 게 목적
            scenario_reports.append({
                "id": sc["id"],
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
                "checks": {},
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            })
            continue
        latency_ms = round((time.perf_counter() - start) * 1000, 1)

        results = response.get("results") or []
        candidates = response.get("candidates") or []
        expect = sc["expect"]
        checks = {}

        if "top5_any" in expect:
            top5 = _hit_ids(results, 5)
            matched = [oid for oid in expect["top5_any"] if oid in top5]
            checks["top5_any"] = {"passed": bool(matched), "matched": matched, "top5": top5}

        if "any_channel_top5_any" in expect:
            pool = _hit_ids(results, 5) + _hit_ids(candidates, 5)
            matched = [oid for oid in expect["any_channel_top5_any"] if oid in pool]
            checks["any_channel_top5_any"] = {
                "passed": bool(matched),
                "matched": matched,
                "top5_results": _hit_ids(results, 5),
                "top5_candidates": _hit_ids(candidates, 5),
            }

        if "linked_any_groups" in expect:
            linked: set[str] = set()
            for h in results[:5]:
                linked.update(_linked_ids(h))
            groups = []
            for group in expect["linked_any_groups"]:
                matched = [oid for oid in group if oid in linked]
                groups.append({"passed": bool(matched), "matched": matched})
            checks["linked_any_groups"] = {
                "passed": all(g["passed"] for g in groups),
                "groups": groups,
            }

        if "max_results" in expect:
            checks["max_results"] = {
                "passed": len(results) <= expect["max_results"],
                "returned": len(results),
                "cap": expect["max_results"],
            }

        if "raw_top5_prefix_any" in expect:
            raw_top5 = _hit_ids(response.get("raw_excerpts") or [], 5)
            matched = [p for p in expect["raw_top5_prefix_any"]
                       if any(oid and oid.startswith(p) for oid in raw_top5)]
            checks["raw_top5_prefix_any"] = {
                "passed": bool(matched), "matched": matched, "top5_raw": raw_top5,
            }

        if "advisories_top5_any" in expect:
            adv_top5 = _hit_ids(response.get("advisories") or [], 5)
            matched = [oid for oid in expect["advisories_top5_any"] if oid in adv_top5]
            checks["advisories_top5_any"] = {
                "passed": bool(matched), "matched": matched, "top5_advisories": adv_top5,
            }

        if "projection_reuse_top5_any" in expect:
            proj_top5 = _hit_ids(response.get("projection_reuse") or [], 5)
            matched = [oid for oid in expect["projection_reuse_top5_any"] if oid in proj_top5]
            checks["projection_reuse_top5_any"] = {
                "passed": bool(matched), "matched": matched, "top5_projection_reuse": proj_top5,
            }

        if expect.get("no_answer"):
            gated = bool(response.get("needs_clarification")) and not results
            checks["no_answer"] = {
                "passed": gated,
                "needs_clarification": bool(response.get("needs_clarification")),
                "returned": len(results),
            }

        scenario_reports.append({
            "id": sc["id"],
            "passed": all(c["passed"] for c in checks.values()),
            "checks": checks,
            "latency_ms": latency_ms,
        })

    passed = sum(1 for r in scenario_reports if r["passed"])
    return {
        "ok": passed == len(scenario_reports),
        "summary": {"passed": passed, "failed": len(scenario_reports) - passed,
                    "total": len(scenario_reports)},
        "scenarios": scenario_reports,
    }
