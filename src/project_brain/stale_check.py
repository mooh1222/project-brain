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
import hashlib
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from project_brain.repo_context import RepoContext
from project_brain.store import BrainStore


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
        except OSError as exc:
            raise GitError(f"git {' '.join(args)} could not start: {exc}") from exc
        if result.returncode != 0:
            raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result.stdout
    return run


def resolve_target_head(git_runner, *, default_branch="develop", fetch=True):
    """origin/<default_branch>의 현재 sha. fetch=True면 먼저 그 브랜치를 가져온다.

    brain 브랜치 워킹트리는 기준 브랜치보다 구버전일 수 있어 비교 기준은 항상 origin/<default_branch>.
    """
    if fetch:
        git_runner(["fetch", "origin", default_branch])
    return git_runner(["rev-parse", f"origin/{default_branch}"]).strip()


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


def stale_check(store, *, git_runner, target_head=None, default_branch="develop", fetch=True):
    """바뀐 파일을 가리키는 매핑 후보 + locator_group + coverage + target_head.

    target_head를 주면 git fetch/rev-parse를 건너뛴다(테스트·재실행). 읽기 전용 —
    brain 데이터는 절대 안 건드린다. 구현 키는 (path, commit_sha) 쌍이다(같은 path를
    commit_sha 다른 locator가 가리키면 각각 판정).
    """
    if target_head is None:
        target_head = resolve_target_head(
            git_runner, default_branch=default_branch, fetch=fetch)

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
            closure = compute_closure(store, loc["id"])
            unmerged_anchors.append({
                "locator_id": loc["id"], "path": path, "from_commit": from_commit,
                "reason": "not_ancestor" if merged is False else "anchor_unverifiable",
                "blocking_affected_mapping_ids": list(closure["blocking"]),
                "nonblocking_affected_mapping_ids": list(closure["nonblocking"]),
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

    def entry(mapping_id):
        return detail.setdefault(mapping_id, {
            "code_changed": False,
            "unmerged_anchor": False,
            "unmerged_reasons": set(),
            "locator_ids": set(),
            "from_commits": set(),
            "change_types": set(),
            "paths": set(),
        })

    for c in report["candidates"]:
        d = entry(c["mapping_id"])
        d["code_changed"] = True
        for sl in c["stale_locators"]:
            d["locator_ids"].add(sl["locator_id"])
            d["from_commits"].add(sl["from_commit"])
            d["change_types"].add(sl["change_type"])
            d["paths"].add(sl["path"])
    for anchor in report.get("unmerged_anchors") or []:
        mapping_ids = set(anchor.get("blocking_affected_mapping_ids") or [])
        mapping_ids.update(anchor.get("nonblocking_affected_mapping_ids") or [])
        for mapping_id in sorted(mapping_ids):
            d = entry(mapping_id)
            d["unmerged_anchor"] = True
            d["unmerged_reasons"].add(anchor["reason"])
            d["locator_ids"].add(anchor["locator_id"])
            d["from_commits"].add(anchor["from_commit"])
            d["paths"].add(anchor["path"])

    for d in detail.values():
        for key in ("unmerged_reasons", "locator_ids", "from_commits", "change_types", "paths"):
            d[key] = sorted(d[key])
    return {
        "target_head": report["target_head"],
        "computed_at": now,
        "stale_mapping_ids": sorted(mid for mid, d in detail.items() if d["code_changed"]),
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
            # 새 캐시의 false도 보존하되, 필드 없는 옛 캐시는 stale-set의 기존 뜻대로
            # "코드 변경"으로 읽는다.
            "code_changed": d.get("code_changed", True),
            "unmerged_anchor": d.get("unmerged_anchor", False),
            "unmerged_reasons": d.get("unmerged_reasons", []),
            "locator_ids": d.get("locator_ids", []),
            "from_commits": d.get("from_commits", []),
            "change_types": d.get("change_types", []),
            "paths": d.get("paths", []),
            "target_head": (stale_set or {}).get("target_head"),
            "computed_at": (stale_set or {}).get("computed_at"),
        }
    return out


_EXACT_GIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


@dataclass(frozen=True)
class MarkCheckedPlan:
    updated: tuple[dict, ...]
    blocked: tuple[dict, ...]
    warnings: tuple[dict, ...]
    preconditions: Mapping[str, str]
    expected_corpus_fingerprint: str
    repo_context: RepoContext
    engine_sha: str


class MarkCheckedError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        locator_ids: Sequence[str] = (),
        invalid_inputs: Sequence[dict] = (),
    ):
        self.code = code
        self.detail = detail
        self.locator_ids = tuple(locator_ids)
        self.invalid_inputs = tuple(invalid_inputs)
        super().__init__(f"{code}: {detail}")


def plan_mark_checked(
    store: BrainStore,
    *,
    mapping_ids: Sequence[str],
    checked_head: str,
    repo_context: RepoContext,
    engine_sha: str,
) -> MarkCheckedPlan:
    """reviewed mapping closure를 실제 target blob에서 다시 확인해 쓰기 묶음을 만든다."""
    from project_brain.code_verify import (
        CodeVerificationError,
        verify_locator_for_write,
    )
    from project_brain.mutation import corpus_fingerprint
    from project_brain.objbase import now_kst
    if not isinstance(repo_context, RepoContext):
        raise MarkCheckedError(
            "repo_context_required",
            "explicit RepoContext is required",
        )
    if checked_head != repo_context.target_revision_sha:
        raise MarkCheckedError(
            "head_moved",
            (
                f"head moved: checked head {checked_head!r} does not match resolved target "
                f"{repo_context.target_revision_sha!r}"
            ),
        )
    if (
        not isinstance(engine_sha, str)
        or _EXACT_GIT_SHA.fullmatch(engine_sha) is None
    ):
        raise MarkCheckedError(
            "engine_sha_invalid",
            "engine_sha must be an exact lowercase Git SHA",
        )

    invalid_inputs = []
    for mapping_id in mapping_ids:
        if not store.has(mapping_id):
            invalid_inputs.append({"id": mapping_id, "reason": "unknown_id"})
        elif store.get(mapping_id).get("kind") != "DomainMapping":
            invalid_inputs.append({
                "id": mapping_id,
                "reason": "not_domain_mapping",
            })
        elif store.get(mapping_id).get("status") != "reviewed":
            invalid_inputs.append({
                "id": mapping_id,
                "reason": f"status_{store.get(mapping_id).get('status')}",
            })
    if invalid_inputs:
        raise MarkCheckedError(
            "invalid_mapping_inputs",
            "mappings must be existing reviewed DomainMapping",
            invalid_inputs=invalid_inputs,
        )

    input_set = set(mapping_ids)
    candidate_locator_ids = sorted({
        locator_id
        for mapping_id in mapping_ids
        for locator_id in (
            store.get(mapping_id).get("code_locator_ids") or []
        )
    })
    invalid_locators = [
        locator_id
        for locator_id in candidate_locator_ids
        if (
            not store.has(locator_id)
            or store.get(locator_id).get("kind") != "CodeLocator"
        )
    ]
    if invalid_locators:
        raise MarkCheckedError(
            "locator_reference_invalid",
            "code_locator_ids must reference existing CodeLocator objects",
            locator_ids=invalid_locators,
        )

    eligible = []
    blocked = []
    warnings = []
    for locator_id in candidate_locator_ids:
        closure = compute_closure(store, locator_id)
        missing = sorted(
            mapping_id
            for mapping_id in closure["blocking"]
            if mapping_id not in input_set
        )
        if missing:
            blocked.append({
                "locator_id": locator_id,
                "missing_mapping_ids": missing,
            })
            continue
        candidate_only = sorted(
            mapping_id
            for mapping_id in closure["nonblocking"]
            if store.get(mapping_id).get("status") == "candidate"
        )
        if candidate_only:
            warnings.append({
                "locator_id": locator_id,
                "candidate_mapping_ids": candidate_only,
            })
        eligible.append(store.get(locator_id))

    no_quote = sorted(
        str(locator["id"])
        for locator in eligible
        if (
            not isinstance(locator.get("verified_quote"), str)
            or not locator.get("verified_quote")
        )
    )
    if no_quote:
        raise MarkCheckedError(
            "refused_unverifiable",
            "mark-checked requires a non-empty verified_quote",
            locator_ids=no_quote,
        )

    verified_locators = []
    for locator in eligible:
        target = dict(locator)
        target["commit_sha"] = checked_head
        try:
            verified = verify_locator_for_write(
                target,
                repo=repo_context,
                manual_symbol_verification=target.get(
                    "manual_symbol_verification"
                ),
            )
        except CodeVerificationError as exc:
            raise MarkCheckedError(
                exc.failure.code,
                exc.failure.detail,
                locator_ids=(str(locator["id"]),),
            ) from exc
        verified_locators.append(verified.locator)

    verification_event_at = now_kst()
    updated = []
    for locator in verified_locators:
        replacement = dict(locator)
        replacement["verified_at"] = verification_event_at
        replacement["updated_at"] = verification_event_at
        updated.append(replacement)

    preconditions = {
        locator["id"]: hashlib.sha256(
            store.object_bytes(store.get(locator["id"]))
        ).hexdigest()
        for locator in updated
    }
    return MarkCheckedPlan(
        updated=tuple(updated),
        blocked=tuple(blocked),
        warnings=tuple(warnings),
        preconditions=preconditions,
        expected_corpus_fingerprint=corpus_fingerprint(store),
        repo_context=repo_context,
        engine_sha=engine_sha,
    )
