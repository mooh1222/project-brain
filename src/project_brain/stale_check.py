"""코드 변경 → 의미 갱신 대상 발견 (stale-check) 로직.

spec: docs/superpowers/specs/2026-06-14-project-brain-stale-check-design.md
git 호출은 git_runner 콜러블로 주입한다 — 로직 함수는 git을 모른다(테스트는
합성 입력으로 대체, 네트워크·실레포 무관). 기계는 "어느 파일이 바뀌어 어느
매핑이 영향권인가"까지 찾고, 영향권 후보의 처리는 검수 정책 B+C를 따른다 —
근거 확실하면 에이전트가 자동(reviewed) 갱신/supersede, 모호하면 candidate,
완전 애매한 것만 사용자(정본: docs/plans/2026-06-25-brain-stale-automation-bc.md §2).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


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


class GitError(RuntimeError):
    pass


def make_git_runner(repo_root, *, timeout=60):
    """repo_root에서 git을 실행하는 runner를 만든다. 실패·타임아웃 시 GitError.

    timeout: git 호출(특히 fetch)이 네트워크 행으로 무한 블로킹하지 않게 하는 상한(초).
    """
    def run(args):
        try:
            result = subprocess.run(
                ["git"] + args, capture_output=True, text=True,
                cwd=str(repo_root), timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from exc
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout
    return run


def resolve_target_head(git_runner, *, fetch=True):
    """origin/develop의 현재 sha. fetch=True면 먼저 origin develop을 가져온다.

    brain 브랜치 워킹트리는 develop보다 구버전이라 비교 기준은 항상 origin/develop.
    """
    if fetch:
        git_runner(["fetch", "origin", "develop"])
    return git_runner(["rev-parse", "origin/develop"]).strip()


def path_changed(git_runner, from_commit, target_head, path):
    """from_commit 이후 target_head까지 path가 바뀌었으면 change_type(M/A/D/R…),
    안 바뀌었으면 None. --name-status로 rename/delete 종류까지 사람이 보게 한다."""
    out = git_runner(
        ["diff", "--name-status", f"{from_commit}..{target_head}", "--", path]
    ).strip()
    if not out:
        return None
    # 첫 줄의 첫 탭 토큰이 status(rename은 R100 등) — 대표값 그대로 운반.
    return out.splitlines()[0].split("\t")[0]


def anchor_merged(git_runner, from_commit, target_head):
    """from_commit이 target_head(origin/develop)의 조상인가 = develop에 머지됨.

    merge-base가 from_commit(의 전체 sha)를 돌려주면 조상이다. 저장 commit_sha는
    약식일 수 있고 merge-base는 전체 sha를 내므로 prefix로 비교한다. merge-base가
    실패(커밋 미존재·무관 히스토리)하면 GitError가 전파된다 — 호출자가 미검증으로 분류.
    """
    base = git_runner(["merge-base", from_commit, target_head]).strip()
    return base.startswith(from_commit)


def stale_check(store, *, git_runner, target_head=None, fetch=True):
    """바뀐 파일을 가리키는 매핑 후보 + locator_group + coverage + target_head.

    target_head를 주면 git fetch/rev-parse를 건너뛴다(테스트·재실행). 읽기 전용 —
    brain 데이터는 절대 안 건드린다. 구현 키는 (path, commit_sha) 쌍이다(같은 path를
    commit_sha 다른 locator가 가리키면 각각 판정).
    """
    if target_head is None:
        target_head = resolve_target_head(git_runner, fetch=fetch)

    change_cache = {}  # (path, commit_sha) → change_type or None
    ancestor_cache = {}  # from_commit → bool(머지됨) / None(검증 불가)
    locator_group = []
    candidate_mapping_ids = set()
    unmerged_anchors = []
    for loc in store.by_kind("CodeLocator"):
        path = loc.get("path")
        from_commit = loc.get("commit_sha")
        if not path or not from_commit:
            continue  # 기준점 없는 locator는 비교 불가 — 건너뜀
        if from_commit not in ancestor_cache:
            try:
                ancestor_cache[from_commit] = anchor_merged(
                    git_runner, from_commit, target_head)
            except GitError:
                ancestor_cache[from_commit] = None  # 커밋 미존재·무관 히스토리 — 검증 불가
        merged = ancestor_cache[from_commit]
        if merged is not True:
            # 미머지/검증불가 앵커: from..develop diff가 거짓 변경을 내므로 후보에서 빼고
            # 별개 범주로 라벨(차단 아님). 머지되면 다음 실행에서 자동 해소(설계 §5).
            unmerged_anchors.append({
                "locator_id": loc["id"], "path": path, "from_commit": from_commit,
                "reason": "not_ancestor" if merged is False else "anchor_unverifiable",
            })
            continue
        key = (path, from_commit)
        if key not in change_cache:
            change_cache[key] = path_changed(git_runner, from_commit, target_head, path)
        change_type = change_cache[key]
        if change_type is None:
            continue
        closure = compute_closure(store, loc["id"])
        locator_group.append({
            "locator_id": loc["id"],
            "path": path,
            "from_commit": from_commit,
            "target_head": target_head,
            "change_type": change_type,
            "blocking_affected_mapping_ids": list(closure["blocking"]),
            "nonblocking_affected_mapping_ids": list(closure["nonblocking"]),
        })
        candidate_mapping_ids.update(closure["blocking"])

    locator_group.sort(key=lambda g: g["locator_id"])
    candidates = []
    for mid in sorted(candidate_mapping_ids):
        m = store.get(mid)
        locs = [g for g in locator_group
                if mid in g["blocking_affected_mapping_ids"]]
        candidates.append({
            "mapping_id": mid,
            "mapping_key": m.get("mapping_key"),
            "stale_locators": [
                {"locator_id": g["locator_id"], "path": g["path"],
                 "change_type": g["change_type"], "from_commit": g["from_commit"]}
                for g in locs
            ],
        })

    return {
        "target_head": target_head,
        "candidates": candidates,
        "locator_group": locator_group,
        "unmerged_anchors": sorted(unmerged_anchors, key=lambda u: u["locator_id"]),
        "coverage": coverage_report(store),
    }


def build_stale_set(report, *, now):
    """stale_check() 리포트를 query 캐시 형태로 압축한다(순수). computed_at은 주입."""
    detail = {}
    for c in report["candidates"]:
        detail[c["mapping_id"]] = {
            "change_types": sorted({sl["change_type"] for sl in c["stale_locators"]}),
            "paths": sorted({sl["path"] for sl in c["stale_locators"]}),
        }
    return {
        "target_head": report["target_head"],
        "computed_at": now,
        "stale_mapping_ids": sorted(detail),
        "detail": detail,
    }


def stale_set_path(brain_root):
    """query가 읽는 stale 캐시 경로. 색인 DB·세션 마킹과 같은 .brain-local 파생물 위치."""
    return Path(brain_root) / ".brain-local" / "stale-set.json"


def write_stale_set(brain_root, stale_set):
    path = stale_set_path(brain_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stale_set, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_stale_set(brain_root):
    """캐시 dict 또는 None(파일 없음). query/show가 advisory 부착에 쓴다."""
    path = stale_set_path(brain_root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def advisories_by_mapping(stale_set):
    """캐시를 매핑id→advisory dict로. 캐시 None/빈 dict면 {}(advisory 0건)."""
    out = {}
    for mid, d in ((stale_set or {}).get("detail") or {}).items():
        out[mid] = {
            "code_changed": True,
            "change_types": d["change_types"],
            "paths": d["paths"],
            "target_head": (stale_set or {}).get("target_head"),
            "computed_at": (stale_set or {}).get("computed_at"),
        }
    return out


def mark_checked(store, *, mapping_ids, checked_head, current_head, now):
    """검토 완료 reviewed 매핑이 어떤 locator의 blocking closure를 전부 덮으면 갱신.

    입력은 존재하는 reviewed DomainMapping만 허용한다(spec §4 'reviewed-only blocking').
    unknown/candidate/superseded/non-mapping이 섞이면 ok:False로 거부한다 — candidate가
    reviewed closure 빈 locator를 vacuous하게 통과시켜 commit_sha를 갱신하는 사각을 입력
    단에서 차단한다. 그래서 후보 locator의 blocking은 항상 입력 매핑을 포함해 비지 않는다.

    반환(체크 순서대로):
      head 이동: {"ok": False, "error": "head moved", "checked_head", "current_head", ...빈}
      거부: {"ok": False, "error": ..., "invalid_inputs": [{id, reason}...], updated/blocked/warnings 빈}
      정상: {"ok": True, "updated": [갱신 locator 객체...],
             "blocked": [{locator_id, missing_mapping_ids}...],
             "warnings": [{locator_id, candidate_mapping_ids}...]}
    저장은 호출자(CLI). line_* 불변. warnings는 candidate만(superseded 제외, spec §4).

    staleness는 재확인하지 않는다 — 사람이 검토 선언한 매핑의 blocking closure 충족이
    유일한 갱신 조건이다(이 함수는 git을 받지 않는다). 안 바뀐 locator라도 그 reviewed
    closure가 입력에 전부 들어오면 commit_sha가 checked_head로 갱신되며, checked_head는
    origin/develop ancestor라 무해하다(stale 여부 판정은 stale-check의 몫).
    """
    empty = {"updated": [], "blocked": [], "warnings": []}
    if checked_head != current_head:
        return {"ok": False, "error": "head moved",
                "checked_head": checked_head, "current_head": current_head, **empty}

    # 입력 검증: 존재하는 reviewed DomainMapping만(spec §4 — vacuous pass 차단).
    invalid_inputs = []
    for mid in mapping_ids:
        if not store.has(mid):
            invalid_inputs.append({"id": mid, "reason": "unknown_id"})
        elif store.get(mid).get("kind") != "DomainMapping":
            invalid_inputs.append({"id": mid, "reason": "not_domain_mapping"})
        elif store.get(mid).get("status") != "reviewed":
            invalid_inputs.append(
                {"id": mid, "reason": f"status_{store.get(mid).get('status')}"})
    if invalid_inputs:
        return {"ok": False, "error": "mappings must be existing reviewed DomainMapping",
                "invalid_inputs": invalid_inputs, **empty}

    input_set = set(mapping_ids)
    candidate_locator_ids = set()
    for mid in mapping_ids:
        for lid in (store.get(mid).get("code_locator_ids") or []):
            candidate_locator_ids.add(lid)

    updated, blocked, warnings = [], [], []
    for lid in sorted(candidate_locator_ids):
        # 갱신 대상은 실제 CodeLocator만 — schema/lint는 code_locator_ids의 "존재"만 보고
        # "CodeLocator인가"는 강제하지 않으므로(엔진 lint.py), future bad data에서 비-CodeLocator
        # id가 섞여도 commit_sha/verified_at/updated_at를 엉뚱한 객체에 쓰지 않게 막는다.
        if not store.has(lid) or store.get(lid).get("kind") != "CodeLocator":
            continue
        closure = compute_closure(store, lid)
        missing = sorted(m for m in closure["blocking"] if m not in input_set)
        if missing:
            blocked.append({"locator_id": lid, "missing_mapping_ids": missing})
            continue
        # warning은 candidate만 — superseded는 현재 사실이 아니라 제외(spec §4).
        # sorted로 명시(missing_mapping_ids와 일관 — _mappings_referencing 정렬에 암묵 의존하지 않음).
        candidate_only = sorted(
            m for m in closure["nonblocking"]
            if store.get(m).get("status") == "candidate")
        if candidate_only:
            warnings.append({"locator_id": lid, "candidate_mapping_ids": candidate_only})
        loc = dict(store.get(lid))
        loc["commit_sha"] = checked_head
        loc["verified_at"] = now
        loc["updated_at"] = now
        updated.append(loc)
    return {"ok": True, "updated": updated, "blocked": blocked, "warnings": warnings}
