from hashlib import sha256
from pathlib import Path

from project_brain.audit import run_audit
from project_brain.store import BrainStore


def _store(*objects: dict) -> BrainStore:
    return BrainStore({obj["id"]: obj for obj in objects})


def _locator(
    *,
    object_id: str = "code.ctx.anchor",
    quote: str | None = None,
) -> dict:
    locator = {
        "id": object_id,
        "kind": "CodeLocator",
        "status": "reviewed",
        "truth_role": "reference",
        "title": "Code: anchor",
        "repo": "demo",
        "path": "src/example.py",
        "symbol": "anchor",
        "locator_source": "rg",
        "commit_sha": "a" * 40,
        "verified_at": "2026-07-28T00:00:00+09:00",
        "created_at": "2026-07-28T00:00:00+09:00",
        "updated_at": "2026-07-28T00:00:00+09:00",
        "tags": ["ctx"],
        "evidence_refs": [],
    }
    if quote is not None:
        locator["verified_quote"] = quote
    return locator


def _unchanged_git_runner(calls: list[list[str]]):
    def run(args):
        calls.append(args)
        if args[:1] == ["merge-base"]:
            return "a" * 40 + "\n"
        if args[:2] == ["diff", "--name-status"]:
            return ""
        raise AssertionError(f"unexpected git args: {args}")

    return run


def test_locator_always_has_six_axes_and_missing_quote_does_not_skip_stale(
    tmp_path: Path,
):
    git_calls: list[list[str]] = []
    report = run_audit(
        _store(_locator()),
        brain_root=tmp_path,
        git_runner=_unchanged_git_runner(git_calls),
        blob_reader=lambda _commit, _path: (_ for _ in ()).throw(
            AssertionError("missing quote must not read a blob")
        ),
        target_head="b" * 40,
        principal=None,
        acl_evaluator=None,
        now="2026-07-29T00:00:00+09:00",
    )

    assert report["locators"] == [{
        "locator_id": "code.ctx.anchor",
        "stale": "unchanged",
        "code_quote": "missing",
        "symbol_relation": "unsupported",
        "quote_access": "indeterminate",
        "id_format": "valid",
        "references": "intact",
    }]
    assert any(call[:2] == ["diff", "--name-status"] for call in git_calls)


def test_reverse_evidence_ref_with_missing_manifest_is_dangling(
    tmp_path: Path,
):
    evidence_ref = {
        "id": "evref.ctx.anchor",
        "kind": "EvidenceRef",
        "evidence_manifest_id": "manifest.ctx.missing",
        "locator": {"code_locator_id": "code.ctx.anchor"},
    }
    report = run_audit(
        _store(_locator(), evidence_ref),
        brain_root=tmp_path,
        git_runner=_unchanged_git_runner([]),
        blob_reader=lambda _commit, _path: b"",
        target_head="b" * 40,
        principal=None,
        acl_evaluator=None,
        now="2026-07-29T00:00:00+09:00",
    )

    entry = report["locators"][0]
    assert entry["references"] == "dangling"
    assert entry["quote_access"] == "indeterminate"


def test_no_stale_marks_git_dependent_axes_unverifiable(tmp_path: Path):
    report = run_audit(
        _store(_locator(quote="anchor = 1")),
        brain_root=tmp_path,
        no_stale=True,
        principal=None,
        acl_evaluator=None,
        now="2026-07-29T00:00:00+09:00",
    )

    entry = report["locators"][0]
    assert entry["stale"] == "unverifiable"
    assert entry["code_quote"] == "unverifiable"
    assert entry["symbol_relation"] == "unsupported"
    assert report["code_quotes"]["ok"] is False
    assert report["code_quotes"]["check_skipped"] is True


def test_unknown_locator_id_grammar_is_an_independent_failure_axis(
    tmp_path: Path,
):
    report = run_audit(
        _store(_locator(object_id="mystery.ctx.anchor")),
        brain_root=tmp_path,
        no_stale=True,
        principal=None,
        acl_evaluator=None,
        now="2026-07-29T00:00:00+09:00",
    )

    assert report["locators"][0]["id_format"] == "unknown_grammar"
    assert report["ok"] is False


def test_exact_manual_symbol_evidence_is_reported_independently(
    tmp_path: Path,
):
    quote = "def anchor(): pass"
    locator = _locator(quote=quote)
    locator["manual_symbol_verification"] = {
        "reviewer": "reviewer@example.com",
        "repo": "demo",
        "commit": "a" * 40,
        "path": "src/example.py",
        "symbol": "anchor",
        "quote_sha256": sha256(quote.encode()).hexdigest(),
        "rationale": "Python parser support is outside this release.",
    }
    report = run_audit(
        _store(locator),
        brain_root=tmp_path,
        git_runner=_unchanged_git_runner([]),
        blob_reader=lambda _commit, _path: quote.encode(),
        target_head="b" * 40,
        principal=None,
        acl_evaluator=None,
        now="2026-07-29T00:00:00+09:00",
    )

    assert report["locators"][0]["code_quote"] == "verified"
    assert report["locators"][0]["symbol_relation"] == "manual_verified"
