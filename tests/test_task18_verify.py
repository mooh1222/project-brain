from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from project_brain.foundation import canonical_receipt_bytes
from project_brain.task18_verify import (
    ParsedTask18Binding,
    Task18VerificationError,
    create_task18_closure_receipt,
    load_task18_post_authorization,
    verify_task18_applied,
    verify_task18_closure_receipt,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_sha(value: object) -> str:
    return _sha(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


def _parsed_binding(tmp_path: Path) -> ParsedTask18Binding:
    engine_root = (tmp_path / "engine").resolve()
    repo_root = (tmp_path / "repo").resolve()
    brain_root = repo_root / "brain"
    snapshot_root = (tmp_path / "snapshot").resolve()
    for path in (engine_root, brain_root / "objects/code", snapshot_root / "payload/brain/objects/code"):
        path.mkdir(parents=True, exist_ok=True)

    before = {
        "id": "code.ctx.run",
        "kind": "CodeLocator",
        "title": "old title",
        "repo": "demo",
        "path": "src/Run.cpp",
        "symbol": "Ns::run",
        "locator_source": "symbol",
        "verified_at": "2026-08-06T00:00:00+09:00",
    }
    after = {**before, "title": "Ns::run"}
    before_bytes = canonical_receipt_bytes(before)
    after_bytes = canonical_receipt_bytes(after)
    relative = "objects/code/run.json"
    (snapshot_root / "payload/brain" / relative).write_bytes(before_bytes)
    (brain_root / relative).write_bytes(after_bytes)
    manifest = {
        "files": [{
            "scope": "brain",
            "path": relative,
            "sha256": _sha(before_bytes),
            "size": len(before_bytes),
            "copied": True,
            "snapshot_path": f"payload/brain/{relative}",
        }]
    }
    (snapshot_root / "manifest.json").write_bytes(canonical_receipt_bytes(manifest))
    target = {
        "id": before["id"],
        "kind": before["kind"],
        "paired_locator_id": None,
        "before_object_sha256": _sha(before_bytes),
        "before_non_title_sha256": _json_sha({
            key: value for key, value in before.items() if key != "title"
        }),
        "expected_title": after["title"],
    }
    binding_path = (tmp_path / "binding.json").resolve()
    binding_path.write_bytes(b"binding\n")
    return ParsedTask18Binding(
        path=binding_path,
        sha256=_sha(b"binding\n"),
        value={},
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        snapshot_root=snapshot_root,
        snapshot_manifest_sha256="a" * 64,
        migration_targets=(target,),
        target_ids_sha256=_json_sha([before["id"]]),
        expected_after_corpus_fingerprint="b" * 64,
        baseline_status_bytes=b"",
        baseline_dirt_manifest_bytes=b"[]\n",
    )


def test_post_verifier_does_not_reuse_pre_apply_binding_verifier():
    import project_brain.task18_verify as module

    source = inspect.getsource(module)
    assert "verify_task18_binding(" not in source
    assert "from project_brain.task18_binding_verify import" not in source


def test_post_parser_checks_binding_bytes_schema_roots_remote_inputs_and_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as create_module
    import project_brain.task18_verify as module
    from project_brain.task18_binding import create_task18_binding
    from tests.test_task18_binding import task18_fixture as fixture_definition

    fixture = fixture_definition.__wrapped__(tmp_path)
    fixture.install(monkeypatch, create_module)
    created = create_task18_binding(
        fixture.request,
        clock=lambda: "2026-08-06T12:00:00+09:00",
    )
    fixture.install(monkeypatch, module)

    parsed = module.parse_task18_binding_for_post_verify(
        binding_path=created.path,
        expected_binding_sha256=created.sha256,
        engine_root=fixture.request.engine_root,
        repo_root=fixture.request.repo_root,
        brain_root=fixture.request.brain_root,
    )
    assert parsed.target_ids_sha256 == created.value["migration"]["target_ids_sha256"]
    assert [row["id"] for row in parsed.migration_targets] == [
        "code.ctx.run",
        "evref.ctx.run",
    ]


def test_post_authorization_requires_exact_binding_sha_and_returns_only_bound_titles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_verify as module

    binding = _parsed_binding(tmp_path)
    monkeypatch.setattr(
        module,
        "parse_task18_binding_for_post_verify",
        lambda **kwargs: binding,
    )
    value = load_task18_post_authorization(
        binding_path=binding.path,
        expected_binding_sha256=binding.sha256,
        engine_root=binding.engine_root,
        repo_root=binding.repo_root,
        brain_root=binding.brain_root,
    )
    assert value.binding_sha256 == binding.sha256
    assert value.expected_titles == {"code.ctx.run": "Ns::run"}
    assert value.target_ids_sha256 == binding.target_ids_sha256


def test_post_verify_rejects_non_title_object_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_verify as module

    binding = _parsed_binding(tmp_path)
    live_path = binding.brain_root / "objects/code/run.json"
    live = json.loads(live_path.read_bytes())
    live["path"] = "src/Other.cpp"
    live_path.write_bytes(canonical_receipt_bytes(live))
    manifest_path = (tmp_path / "display.json").resolve()
    manifest_bytes = canonical_receipt_bytes({
        "migration_version": 3,
        "migration_kind": "display_only",
        "intent": {},
        "snapshot_id": "pre",
        "snapshot_manifest_sha256": "a" * 64,
        "task18_binding_path": str(binding.path),
        "task18_binding_sha256": binding.sha256,
    })
    manifest_path.write_bytes(manifest_bytes)
    quote_path = (tmp_path / "quote.json").resolve()
    quote_path.write_bytes(canonical_receipt_bytes({}))
    monkeypatch.setattr(
        module,
        "parse_task18_binding_for_post_verify",
        lambda **kwargs: binding,
    )

    with pytest.raises(Task18VerificationError, match="non-title"):
        verify_task18_applied(
            binding_path=binding.path,
            expected_binding_sha256=binding.sha256,
            manifest_path=manifest_path,
            expected_manifest_sha256=_sha(manifest_bytes),
            quote_debt_path=quote_path,
            expected_quote_debt_sha256=_sha(quote_path.read_bytes()),
            engine_root=binding.engine_root,
            repo_root=binding.repo_root,
            brain_root=binding.brain_root,
            report_path=(binding.repo_root / "task18-post.json").resolve(),
            pathspec_output=(tmp_path / "paths.nul").resolve(),
            generated_at="2026-08-06T12:00:00+09:00",
        )


def test_post_verify_creates_report_and_nul_pathspec_only_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_verify as module

    binding = _parsed_binding(tmp_path)
    manifest_path = (tmp_path / "display.json").resolve()
    manifest_bytes = canonical_receipt_bytes({
        "migration_version": 3,
        "migration_kind": "display_only",
        "intent": {},
        "snapshot_id": "pre",
        "snapshot_manifest_sha256": "a" * 64,
        "task18_binding_path": str(binding.path),
        "task18_binding_sha256": binding.sha256,
    })
    manifest_path.write_bytes(manifest_bytes)
    quote_path = (tmp_path / "quote.json").resolve()
    quote_path.write_bytes(canonical_receipt_bytes({}))
    report_path = (binding.repo_root / "task18-post.json").resolve()
    pathspec = (tmp_path / "paths.nul").resolve()
    changed = "brain/objects/code/run.json"
    monkeypatch.setattr(
        module,
        "parse_task18_binding_for_post_verify",
        lambda **kwargs: binding,
    )
    monkeypatch.setattr(module, "_assert_post_invariants", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "run_git_bytes", lambda *args: changed.encode() + b"\0")
    monkeypatch.setattr(module, "verify_git_dirt_preserved", lambda *args, **kwargs: None)

    result = verify_task18_applied(
        binding_path=binding.path,
        expected_binding_sha256=binding.sha256,
        manifest_path=manifest_path,
        expected_manifest_sha256=_sha(manifest_bytes),
        quote_debt_path=quote_path,
        expected_quote_debt_sha256=_sha(quote_path.read_bytes()),
        engine_root=binding.engine_root,
        repo_root=binding.repo_root,
        brain_root=binding.brain_root,
        report_path=report_path,
        pathspec_output=pathspec,
        generated_at="2026-08-06T12:00:00+09:00",
    )
    assert result.update_count == 1
    assert pathspec.read_bytes() == changed.encode() + b"\0"
    assert json.loads(report_path.read_bytes())["user_dirt_preserved"] is True
    with pytest.raises(Task18VerificationError, match="report_exists"):
        verify_task18_applied(
            binding_path=binding.path,
            expected_binding_sha256=binding.sha256,
            manifest_path=manifest_path,
            expected_manifest_sha256=_sha(manifest_bytes),
            quote_debt_path=quote_path,
            expected_quote_debt_sha256=_sha(quote_path.read_bytes()),
            engine_root=binding.engine_root,
            repo_root=binding.repo_root,
            brain_root=binding.brain_root,
            report_path=report_path,
            pathspec_output=pathspec,
            generated_at="2026-08-06T12:00:00+09:00",
        )


def test_closure_receipt_binds_snapshot_heads_and_committed_docs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_verify as module
    from project_brain.snapshot import GitDirtReceipt, SnapshotVerification

    engine_root = (tmp_path / "engine").resolve()
    repo_root = (tmp_path / "repo").resolve()
    brain_root = repo_root / "brain"
    snapshot_root = (tmp_path / "corpus-final").resolve()
    for path in (engine_root, brain_root, snapshot_root):
        path.mkdir(parents=True, exist_ok=True)
    snapshot = SnapshotVerification(
        ok=True,
        snapshot_id="task18-final",
        manifest_sha256="a" * 64,
        file_count=7,
        repo_head="2" * 40,
        engine_head="1" * 40,
        corpus_fingerprint="b" * 64,
    )
    empty_git = lambda root, head: GitDirtReceipt(
        str(root),
        head,
        b"",
        _sha(b""),
        0,
        b"[]\n",
        _sha(b"[]\n"),
    )
    engine_git = empty_git(engine_root, "3" * 40)
    repo_git = empty_git(repo_root, snapshot.repo_head)
    monkeypatch.setattr(module, "verify_snapshot", lambda *args, **kwargs: snapshot)
    monkeypatch.setattr(module, "_current_git_closure", lambda *args: (engine_git, repo_git))

    def committed_doc(root, path, head, label):
        receipt = dict(module.capture_bound_file(path))
        return {**receipt, "commit_sha": head}

    monkeypatch.setattr(module, "_committed_doc", committed_doc)
    verify_path = (tmp_path / "snapshot-verify.json").resolve()
    verify_path.write_bytes(canonical_receipt_bytes({
        "ok": True,
        "snapshot_id": snapshot.snapshot_id,
        "manifest_sha256": snapshot.manifest_sha256,
        "file_count": snapshot.file_count,
    }))
    artifacts = []
    for name in ("binding", "manifest", "post"):
        path = (tmp_path / f"{name}.json").resolve()
        path.write_bytes(canonical_receipt_bytes({"name": name}))
        artifacts.append(path)
    completion = (engine_root / "completion.md").resolve()
    roadmap = (engine_root / "ROADMAP.md").resolve()
    completion.write_text("done\n", encoding="utf-8")
    roadmap.write_text("task 18 done\n", encoding="utf-8")
    closure = (tmp_path / "closure.json").resolve()
    create_report = (tmp_path / "closure-create-report.json").resolve()

    result = create_task18_closure_receipt(
        closure_path=closure,
        report_path=create_report,
        corpus_final_snapshot_root=snapshot_root,
        expected_snapshot_manifest_sha256=snapshot.manifest_sha256,
        snapshot_verify_receipt_path=verify_path,
        expected_snapshot_verify_receipt_sha256=_sha(verify_path.read_bytes()),
        binding_path=artifacts[0],
        expected_binding_sha256=_sha(artifacts[0].read_bytes()),
        manifest_path=artifacts[1],
        expected_manifest_sha256=_sha(artifacts[1].read_bytes()),
        post_report_path=artifacts[2],
        expected_post_report_sha256=_sha(artifacts[2].read_bytes()),
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        completion_report_path=completion,
        roadmap_path=roadmap,
        generated_at="2026-08-06T12:00:00+09:00",
    )
    assert result.ok is True
    completion.write_text("drifted\n", encoding="utf-8")
    with pytest.raises(Task18VerificationError, match="committed_docs_drift"):
        verify_task18_closure_receipt(
            closure_path=closure,
            expected_closure_sha256=result.closure_sha256,
            engine_root=engine_root,
            repo_root=repo_root,
            report_path=(tmp_path / "closure-verify-report.json").resolve(),
            generated_at="2026-08-06T12:01:00+09:00",
        )
