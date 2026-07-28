"""코퍼스 감사 결과를 서로 독립적인 상태축으로 조립한다."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from hashlib import sha256
from pathlib import Path

from project_brain.code_verify import (
    BlobReader,
    make_git_blob_reader,
    manual_symbol_evidence_matches,
)
from project_brain.graph import find_isolated
from project_brain.lint import lint_store
from project_brain.objbase import now_kst
from project_brain.quote_access import AccessState, evaluate_quote_access
from project_brain.reference_fields import iter_object_refs
from project_brain.schema import id_problem_code, validate_object_id
from project_brain.stale_check import (
    GitError,
    build_stale_set,
    make_git_runner,
    stale_check,
    write_stale_set,
)
from project_brain.store import BrainStore
from project_brain.symbol_verify import SymbolStatus, verify_symbol_relation


AclEvaluator = Callable[
    [object, Mapping[str, object]],
    AccessState,
]


def _reverse_evidence_refs(
    store: BrainStore,
    locator_id: str,
) -> tuple[dict, ...]:
    refs = []
    for ref in store.by_kind("EvidenceRef"):
        locator = ref.get("locator")
        if (
            isinstance(locator, Mapping)
            and locator.get("code_locator_id") == locator_id
        ):
            refs.append(ref)
    return tuple(sorted(refs, key=lambda ref: str(ref.get("id", ""))))


def _references_state(
    store: BrainStore,
    locator: Mapping[str, object],
) -> str:
    related = (locator, *_reverse_evidence_refs(store, str(locator["id"])))
    return (
        "dangling"
        if any(
            not store.has(ref.object_id)
            for obj in related
            for ref in iter_object_refs(obj)
        )
        else "intact"
    )


def _id_state(locator: Mapping[str, object]) -> str:
    if not validate_object_id(locator):
        return "valid"
    return id_problem_code(locator)


def _symbol_state(
    locator: Mapping[str, object],
    *,
    blob: bytes,
    quote_bytes: bytes,
) -> str:
    offsets = []
    start = 0
    while True:
        offset = blob.find(quote_bytes, start)
        if offset < 0:
            break
        offsets.append(offset)
        start = offset + 1
    results = [
        verify_symbol_relation(
            path=str(locator.get("path", "")),
            blob=blob,
            quote_start=offset,
            quote_end=offset + len(quote_bytes),
            symbol=locator.get("symbol"),
        )
        for offset in offsets
    ]
    if any(result.status is SymbolStatus.VERIFIED for result in results):
        return "verified"
    if any(result.status is SymbolStatus.MISMATCH for result in results):
        return "mismatch"
    manual = locator.get("manual_symbol_verification")
    if (
        any(result.status is SymbolStatus.UNSUPPORTED for result in results)
        and manual_symbol_evidence_matches(
            manual if isinstance(manual, Mapping) else None,
            repo_id=str(locator.get("repo", "")),
            commit=str(locator.get("commit_sha", "")),
            path=str(locator.get("path", "")),
            symbol=str(locator.get("symbol", "")),
            quote_hash=sha256(quote_bytes).hexdigest(),
        )
    ):
        return "manual_verified"
    return "unsupported"


def _quote_and_symbol_state(
    locator: Mapping[str, object],
    *,
    blob_reader: BlobReader,
) -> tuple[str, str]:
    quote = locator.get("verified_quote")
    if not isinstance(quote, str) or not quote:
        return "missing", "unsupported"
    commit = locator.get("commit_sha")
    path = locator.get("path")
    if not isinstance(commit, str) or not isinstance(path, str):
        return "unverifiable", "unsupported"
    try:
        quote_bytes = quote.encode("utf-8")
        blob = blob_reader(commit, path)
        if not isinstance(blob, bytes):
            raise TypeError("blob reader must return bytes")
    except (Exception, UnicodeError):
        return "error", "unsupported"
    if quote_bytes not in blob:
        return "mismatch", "unsupported"
    return "verified", _symbol_state(
        locator,
        blob=blob,
        quote_bytes=quote_bytes,
    )


def run_audit(
    store: BrainStore,
    *,
    brain_root: Path,
    repo_root: Path | None = None,
    default_branch: str = "develop",
    fetch: bool = True,
    no_stale: bool = False,
    git_runner=None,
    blob_reader: BlobReader | None = None,
    target_head: str | None = None,
    principal: object | None,
    acl_evaluator: AclEvaluator | None,
    now: str | None = None,
) -> dict:
    problems = lint_store(store)
    isolated = find_isolated(store)
    by_kind: dict[str, int] = {}
    for object_id in isolated:
        kind = str(store.get(object_id).get("kind"))
        by_kind[kind] = by_kind.get(kind, 0) + 1

    locators = sorted(
        store.by_kind("CodeLocator"),
        key=lambda locator: str(locator.get("id", "")),
    )
    entries = {
        str(locator["id"]): {
            "locator_id": str(locator["id"]),
            "stale": "unverifiable" if no_stale else "unchanged",
            "code_quote": (
                "missing"
                if not isinstance(locator.get("verified_quote"), str)
                or not locator.get("verified_quote")
                else "unverifiable" if no_stale else "missing"
            ),
            "symbol_relation": "unsupported",
            "quote_access": evaluate_quote_access(
                str(locator["id"]),
                store,
                principal=principal,
                acl_evaluator=acl_evaluator,
            ).final.value,
            "id_format": _id_state(locator),
            "references": _references_state(store, locator),
        }
        for locator in locators
    }

    stale = None
    cache_written = None
    if no_stale:
        stale_status = {"ok": True, "skipped": True, "reason": "no_stale"}
    else:
        root = Path(repo_root) if repo_root is not None else Path(brain_root).parent
        runner = git_runner if git_runner is not None else make_git_runner(root)
        try:
            stale = stale_check(
                store,
                git_runner=runner,
                target_head=target_head,
                default_branch=default_branch,
                fetch=fetch,
            )
            cache_written = str(
                write_stale_set(
                    brain_root,
                    build_stale_set(stale, now=now or now_kst()),
                )
            )
        except GitError as exc:
            stale = {"error": str(exc)}
            stale_status = {"ok": False, "skipped": False}
            for entry in entries.values():
                entry["stale"] = "error"
        else:
            for changed in stale.get("locator_group") or []:
                locator_id = changed.get("locator_id")
                if locator_id in entries:
                    entries[locator_id]["stale"] = "changed"
            unverifiable = False
            for anchor in stale.get("unmerged_anchors") or []:
                if anchor.get("reason") != "anchor_unverifiable":
                    continue
                unverifiable = True
                locator_id = anchor.get("locator_id")
                if locator_id in entries:
                    entries[locator_id]["stale"] = "error"
            stale_status = {"ok": not unverifiable, "skipped": False}

    quote_failures = []
    checked = 0
    skipped = 0
    if no_stale:
        skipped = len(locators)
        code_quotes = {
            "ok": False,
            "checked": 0,
            "skipped": skipped,
            "check_skipped": True,
            "failures": [],
        }
    else:
        root = Path(repo_root) if repo_root is not None else Path(brain_root).parent
        reader = blob_reader if blob_reader is not None else make_git_blob_reader(root)
        for locator in locators:
            locator_id = str(locator["id"])
            code_quote, symbol_relation = _quote_and_symbol_state(
                locator,
                blob_reader=reader,
            )
            entries[locator_id]["code_quote"] = code_quote
            entries[locator_id]["symbol_relation"] = symbol_relation
            if code_quote == "missing":
                skipped += 1
            else:
                checked += 1
            if code_quote in {"mismatch", "error", "unverifiable"}:
                quote_failures.append({
                    "locator_id": locator_id,
                    "reason": code_quote,
                })
            elif symbol_relation == "mismatch":
                quote_failures.append({
                    "locator_id": locator_id,
                    "reason": "symbol_mismatch",
                })
        code_quotes = {
            "ok": not quote_failures,
            "checked": checked,
            "skipped": skipped,
            "failures": quote_failures,
        }

    locator_results = list(entries.values())
    axes_ok = all(
        entry["id_format"] == "valid"
        and entry["references"] == "intact"
        and entry["stale"] != "error"
        and entry["code_quote"] not in {"mismatch", "error"}
        and entry["symbol_relation"] != "mismatch"
        for entry in locator_results
    )
    ok = (
        not problems
        and stale_status["ok"]
        and axes_ok
        and (no_stale or code_quotes["ok"])
    )
    return {
        "ok": ok,
        "lint": {"ok": not problems, "problems": problems},
        "isolated": {
            "isolated_count": len(isolated),
            "by_kind": {kind: by_kind[kind] for kind in sorted(by_kind)},
            "isolated": isolated,
        },
        "stale": stale,
        "stale_status": stale_status,
        "code_quotes": code_quotes,
        "locators": locator_results,
        "cache_written": cache_written,
    }
