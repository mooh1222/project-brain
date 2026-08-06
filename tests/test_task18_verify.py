from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest

from project_brain.foundation import canonical_receipt_bytes
from project_brain.mutation import corpus_fingerprint
from project_brain.task18_verify import (
    ParsedTask18Binding,
    Task18VerificationError,
    create_task18_closure_receipt,
    load_task18_post_authorization,
    read_task18_json_bytes,
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
    binding_bytes = canonical_receipt_bytes({})
    binding_path.write_bytes(binding_bytes)
    stored_after = json.loads(after_bytes)
    after_store = __import__("project_brain.store", fromlist=["BrainStore"]).BrainStore(
        {after["id"]: stored_after},
        source_sha256_by_id={after["id"]: _sha(after_bytes)},
    )
    return ParsedTask18Binding(
        path=binding_path,
        sha256=_sha(binding_bytes),
        value={"pre_mutation_snapshot": {
            "snapshot_id": "pre",
            "manifest_sha256": "a" * 64,
            "file_count": 1,
            "repo_head": "1" * 40,
            "engine_head": "2" * 40,
            "corpus_fingerprint": "3" * 64,
        }},
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        snapshot_root=snapshot_root,
        snapshot_manifest_sha256="a" * 64,
        migration_targets=(target,),
        target_ids_sha256=_json_sha([before["id"]]),
        expected_after_corpus_fingerprint=corpus_fingerprint(after_store),
        baseline_status_bytes=b"",
        baseline_dirt_manifest_bytes=b"[]\n",
    )


def test_post_verifier_does_not_reuse_pre_apply_binding_verifier():
    import project_brain.task18_verify as module

    source = inspect.getsource(module)
    assert "verify_task18_binding(" not in source
    assert "from project_brain.task18_binding_verify import" not in source


@pytest.mark.parametrize(
    "payload",
    (
        b'{"ok":true,"ok":false}\n',
        b'{"value":NaN}\n',
        b'{"value":Infinity}\n',
    ),
)
def test_task18_json_reader_rejects_duplicate_keys_and_nonfinite_values(
    tmp_path: Path,
    payload: bytes,
):
    path = (tmp_path / "hostile.json").resolve()
    path.write_bytes(payload)
    with pytest.raises(Task18VerificationError, match="hostile_json_invalid"):
        read_task18_json_bytes(path, expected_sha256=_sha(payload), label="hostile")


def test_task18_output_preflight_rejects_symlink_parent(
    tmp_path: Path,
):
    import project_brain.task18_verify as module

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(Task18VerificationError, match="report_parent_invalid"):
        module._preflight_output((link / "report.json").absolute(), "report")


@pytest.mark.parametrize(("field", "bad_value"), (("ok", 1), ("file_count", 7.0)))
def test_snapshot_verify_receipt_rejects_bool_and_integer_lookalikes(
    field: str,
    bad_value: object,
):
    import project_brain.task18_verify as module

    value = {
        "ok": True,
        "snapshot_id": "snapshot",
        "manifest_sha256": "a" * 64,
        "file_count": 7,
        "repo_head": "b" * 40,
        "engine_head": "c" * 40,
        "corpus_fingerprint": "d" * 64,
    }
    value[field] = bad_value
    assert module._valid_snapshot_verify_receipt(value) is False


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
    monkeypatch.setattr(module, "REQUIRED_TARGET_COUNT", 2)

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
    quote_ids: list[str] = []
    quote_path.write_bytes(canonical_receipt_bytes({
        "quote_debt_ids": quote_ids,
        "quote_debt_ids_sha256": _json_sha(quote_ids),
    }))
    report_path = (binding.repo_root / "task18-post.json").resolve()
    pathspec = (tmp_path / "paths.nul").resolve()
    changed = "brain/objects/code/run.json"
    monkeypatch.setattr(
        module,
        "parse_task18_binding_for_post_verify",
        lambda **kwargs: binding,
    )
    stats = module._PostInvariantStats(
        object_count=1,
        actual_after_fingerprint=binding.expected_after_corpus_fingerprint,
        reference_edge_count=0,
        reference_graph_sha256=_json_sha([]),
        pair_count=0,
        quote_count=0,
        quote_ids_sha256=_json_sha([]),
        symbol_count=0,
        symbol_ids_sha256=_json_sha([]),
        search_index={},
        stale_set_sha256="5" * 64,
    )
    monkeypatch.setattr(module, "_assert_post_invariants", lambda *args, **kwargs: stats)
    monkeypatch.setattr(module, "run_git_bytes", lambda *args: changed.encode() + b"\0")
    from project_brain.snapshot import GitDirtReceipt, SnapshotVerification

    dirt = GitDirtReceipt(
        str(binding.repo_root), "1" * 40, b"", _sha(b""), 0,
        b"[]\n", _sha(b"[]\n"),
    )
    monkeypatch.setattr(module, "verify_git_dirt_preserved", lambda *args, **kwargs: dirt)
    monkeypatch.setattr(module, "_parse_binding_bytes", lambda data: {})
    monkeypatch.setattr(module, "_assert_bound_control_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module,
        "capture_task18_corpus_state",
        lambda *args: {"search_index": {}, "stale_set": {"sha256": "5" * 64}},
    )
    monkeypatch.setattr(module, "REQUIRED_QUOTE_DEBT_COUNT", 0)
    monkeypatch.setattr(
        module,
        "verify_snapshot",
        lambda *args, **kwargs: SnapshotVerification(
            True, "pre", "a" * 64, 1, "1" * 40, "2" * 40, "3" * 64,
        ),
    )
    output_order: list[str] = []
    real_pathspec_create = module._atomic_create_pathspec
    real_report_create = module.atomic_create_receipt

    def create_pathspec(*args, **kwargs):
        output_order.append("pathspec")
        return real_pathspec_create(*args, **kwargs)

    def create_report(*args, **kwargs):
        output_order.append("report")
        return real_report_create(*args, **kwargs)

    monkeypatch.setattr(module, "_atomic_create_pathspec", create_pathspec)
    monkeypatch.setattr(module, "atomic_create_receipt", create_report)

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
    assert output_order == ["pathspec", "report"]
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
    import project_brain.task18_binding as create_module
    import project_brain.task18_verify as module
    from project_brain.snapshot import GitDirtReceipt, SnapshotVerification
    from project_brain.task18_binding import create_task18_binding
    from tests.test_task18_binding import task18_fixture as fixture_definition

    fixture = fixture_definition.__wrapped__(tmp_path)
    fixture.install(monkeypatch, create_module)
    created = create_task18_binding(
        fixture.request,
        clock=lambda: "2026-08-06T12:00:00+09:00",
    )
    fixture.install(monkeypatch, module)
    monkeypatch.setattr(module, "REQUIRED_TARGET_COUNT", 2)
    monkeypatch.setattr(module, "REQUIRED_QUOTE_DEBT_COUNT", 1)
    monkeypatch.setattr(module, "REQUIRED_NONCANONICAL_SYMBOL_COUNT", 0)
    monkeypatch.setattr(module, "REQUIRED_PAIR_COUNT", 1)

    engine_root = fixture.request.engine_root
    repo_root = fixture.request.repo_root
    brain_root = fixture.request.brain_root
    snapshot_root = (tmp_path / "corpus-final").resolve()
    snapshot_root.mkdir(parents=True)
    expected_after = created.value["migration"]["expected_after_corpus_fingerprint"]
    snapshot = SnapshotVerification(
        ok=True,
        snapshot_id="task18-final",
        manifest_sha256="a" * 64,
        file_count=7,
        repo_head="2" * 40,
        engine_head=fixture.engine_git.head,
        corpus_fingerprint=expected_after,
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
    current_git = {"value": (engine_git, repo_git)}
    monkeypatch.setattr(module, "_current_git_closure", lambda *args: current_git["value"])

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
        "repo_head": snapshot.repo_head,
        "engine_head": snapshot.engine_head,
        "corpus_fingerprint": snapshot.corpus_fingerprint,
    }))
    manifest_path = (tmp_path / "manifest.json").resolve()
    manifest_path.write_bytes(canonical_receipt_bytes({
        "migration_version": 3,
        "migration_kind": "display_only",
        "intent": {},
        "snapshot_id": created.value["pre_mutation_snapshot"]["snapshot_id"],
        "snapshot_manifest_sha256": created.value["pre_mutation_snapshot"]["manifest_sha256"],
        "task18_binding_path": str(created.path),
        "task18_binding_sha256": created.sha256,
    }))
    post_path = (tmp_path / "post.json").resolve()
    quote_input = created.value["inputs"]["quote_debt"]
    changed_paths = [
        "brain/objects/code/legacy-locator-name.json",
        "brain/objects/evidence_refs/legacy-ref-name.json",
    ]
    post_value = {
        "version": 1,
        "purpose": "task18-post-apply-verification",
        "generated_at": "2026-08-06T12:00:00+09:00",
        "binding": {"path": str(created.path), "sha256": created.sha256},
        "display_manifest": {"path": str(manifest_path), "sha256": _sha(manifest_path.read_bytes())},
        "quote_debt": {"path": quote_input["path"], "sha256": quote_input["sha256"]},
        "target_ids_sha256": created.value["migration"]["target_ids_sha256"],
        "expected_after_corpus_fingerprint": expected_after,
        "actual_after_corpus_fingerprint": expected_after,
        "object_count": 2,
        "changed_paths": changed_paths,
        "update_count": 2,
        "create_count": 0,
        "delete_count": 0,
        "rename_count": 0,
        "reference_graph": {"edge_count": 1, "sha256": _json_sha([]), "unchanged": True},
        "lint_problem_count": 0,
        "pairs": {"total": 1, "mismatch_count": 0},
        "quote_debt_state": {"count": 1, "ids_sha256": _json_sha(["code.ctx.run"])},
        "noncanonical_symbol_state": {"count": 0, "ids_sha256": _json_sha([])},
        "search_index": created.value["search_index"],
        "stale_set_sha256": created.value["stale_set"]["sha256"],
        "git": {
            "baseline_status_sha256": fixture.bb2_git.status_sha256,
            "baseline_dirt_content_sha256": fixture.bb2_git.content_manifest_sha256,
            "current_status_sha256": fixture.bb2_git.status_sha256,
            "current_dirt_content_sha256": fixture.bb2_git.content_manifest_sha256,
        },
        "quote_debt_unchanged": True,
        "noncanonical_symbols_unchanged": True,
        "index_db_unchanged": True,
        "user_dirt_preserved": True,
    }
    post_path.write_bytes(canonical_receipt_bytes(post_value))
    completion = (engine_root / "completion.md").resolve()
    roadmap = (engine_root / "ROADMAP.md").resolve()
    completion.write_text("done\n", encoding="utf-8")
    roadmap.write_text("task 18 done\n", encoding="utf-8")
    closure = (tmp_path / "closure.json").resolve()

    unrelated_path = (tmp_path / "unrelated-post.json").resolve()
    unrelated = dict(post_value)
    unrelated["binding"] = {"path": str(created.path), "sha256": "0" * 64}
    unrelated_path.write_bytes(canonical_receipt_bytes(unrelated))
    with pytest.raises(Task18VerificationError, match="post_report_binding_mismatch"):
        create_task18_closure_receipt(
            report_path=(tmp_path / "bad-closure.json").resolve(),
            corpus_final_snapshot_root=snapshot_root,
            expected_snapshot_manifest_sha256=snapshot.manifest_sha256,
            snapshot_verify_receipt_path=verify_path,
            expected_snapshot_verify_receipt_sha256=_sha(verify_path.read_bytes()),
            binding_path=created.path,
            expected_binding_sha256=created.sha256,
            manifest_path=manifest_path,
            expected_manifest_sha256=_sha(manifest_path.read_bytes()),
            post_report_path=unrelated_path,
            expected_post_report_sha256=_sha(unrelated_path.read_bytes()),
            engine_root=engine_root,
            repo_root=repo_root,
            brain_root=brain_root,
            completion_report_path=completion,
            roadmap_path=roadmap,
            expected_engine_head=engine_git.head,
            expected_repo_head=repo_git.head,
            generated_at="2026-08-06T12:00:00+09:00",
        )

    result = create_task18_closure_receipt(
        report_path=closure,
        corpus_final_snapshot_root=snapshot_root,
        expected_snapshot_manifest_sha256=snapshot.manifest_sha256,
        snapshot_verify_receipt_path=verify_path,
        expected_snapshot_verify_receipt_sha256=_sha(verify_path.read_bytes()),
        binding_path=created.path,
        expected_binding_sha256=created.sha256,
        manifest_path=manifest_path,
        expected_manifest_sha256=_sha(manifest_path.read_bytes()),
        post_report_path=post_path,
        expected_post_report_sha256=_sha(post_path.read_bytes()),
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        completion_report_path=completion,
        roadmap_path=roadmap,
        expected_engine_head=engine_git.head,
        expected_repo_head=repo_git.head,
        generated_at="2026-08-06T12:00:00+09:00",
    )
    assert result.ok is True
    verify_report = (tmp_path / "closure-verify-report.json").resolve()
    verified = verify_task18_closure_receipt(
        closure_path=closure,
        expected_closure_sha256=result.closure_sha256,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        report_path=verify_report,
    )
    assert verified.ok is True

    changed_dirt = GitDirtReceipt(
        str(repo_root), repo_git.head, b"?? user.txt\0", _sha(b"?? user.txt\0"), 1,
        b"[]\n", _sha(b"[]\n"),
    )
    current_git["value"] = (engine_git, changed_dirt)
    with pytest.raises(Task18VerificationError, match="closure_user_dirt_drift"):
        verify_task18_closure_receipt(
            closure_path=closure,
            expected_closure_sha256=result.closure_sha256,
            engine_root=engine_root,
            repo_root=repo_root,
            brain_root=brain_root,
            report_path=(tmp_path / "closure-dirt-report.json").resolve(),
        )
    current_git["value"] = (engine_git, repo_git)
    completion.write_text("drifted\n", encoding="utf-8")
    with pytest.raises(Task18VerificationError, match="committed_docs_drift"):
        verify_task18_closure_receipt(
            closure_path=closure,
            expected_closure_sha256=result.closure_sha256,
            engine_root=engine_root,
            repo_root=repo_root,
            brain_root=brain_root,
            report_path=(tmp_path / "closure-doc-drift-report.json").resolve(),
        )
