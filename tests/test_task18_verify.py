from __future__ import annotations

import hashlib
import inspect
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

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
    output_lock_held: list[bool] = []
    real_pathspec_create = module._atomic_create_pathspec
    real_report_create = module.atomic_create_receipt

    def create_pathspec(*args, **kwargs):
        output_order.append("pathspec")
        from project_brain import corpus_io
        output_lock_held.append(corpus_io._CORPUS_LOCK_SCOPE.get() is not None)
        return real_pathspec_create(*args, **kwargs)

    def create_report(*args, **kwargs):
        output_order.append("report")
        from project_brain import corpus_io
        output_lock_held.append(corpus_io._CORPUS_LOCK_SCOPE.get() is not None)
        return real_report_create(*args, **kwargs)

    monkeypatch.setattr(module, "_atomic_create_pathspec", create_pathspec)
    failed_report = (binding.repo_root / "task18-post-failed.json").resolve()
    retained_pathspec = (tmp_path / "retained-paths.nul").resolve()

    def fail_report(*args, **kwargs):
        output_order.append("report")
        from project_brain import corpus_io
        output_lock_held.append(corpus_io._CORPUS_LOCK_SCOPE.get() is not None)
        raise RuntimeError("injected report create failure")

    monkeypatch.setattr(module, "atomic_create_receipt", fail_report)
    with pytest.raises(Task18VerificationError):
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
            report_path=failed_report,
            pathspec_output=retained_pathspec,
            generated_at="2026-08-06T12:00:00+09:00",
        )
    assert output_order == ["pathspec", "report"]
    assert output_lock_held == [True, True]
    assert retained_pathspec.read_bytes() == changed.encode() + b"\0"
    assert not failed_report.exists()

    output_order.clear()
    output_lock_held.clear()
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
    assert output_lock_held == [True, True]
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


def _closure_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import project_brain.task18_binding as create_module
    import project_brain.task18_verify as module
    from project_brain.snapshot import GitDirtReceipt, SnapshotVerification
    from project_brain.store import BrainStore
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
    ancestry = {"engine": True, "bb2": True, "calls": []}

    def require_ancestor(root, ancestor, descendant):
        label = "engine" if Path(root) == engine_root else "bb2"
        ancestry["calls"].append((label, ancestor, descendant))
        if not ancestry[label]:
            raise Task18VerificationError(f"{label}_head_not_ancestor")

    monkeypatch.setattr(module, "require_commit_is_ancestor", require_ancestor, raising=False)

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
    pre_snapshot_root = Path(created.value["pre_mutation_snapshot"]["path"])
    snapshot_files = []
    for relative in (
        "objects/code/legacy-locator-name.json",
        "objects/evidence_refs/legacy-ref-name.json",
    ):
        source = brain_root / relative
        payload = source.read_bytes()
        snapshot_relative = f"payload/brain/{relative}"
        target = pre_snapshot_root / snapshot_relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        snapshot_files.append({
            "scope": "brain",
            "path": relative,
            "snapshot_path": snapshot_relative,
            "sha256": _sha(payload),
            "size": len(payload),
            "copied": True,
        })
    (pre_snapshot_root / "manifest.json").write_bytes(canonical_receipt_bytes({
        "files": snapshot_files,
    }))
    targets = created.value["migration"]["targets"]
    before_objects = [dict(fixture.store.get(row["id"])) for row in targets]
    after_objects = [
        {**before, "title": target["expected_title"]}
        for before, target in zip(before_objects, targets, strict=True)
    ]
    source_sha_by_id = {
        obj["id"]: fixture.store.source_sha256(obj["id"])
        for obj in before_objects
    }
    intent = {
        "intent_version": 1,
        "operation": "display_migration",
        "engine_sha": created.value["pre_mutation_snapshot"]["engine_head"],
        "request": {
            "objects": before_objects,
            "delete_ids": [],
            "renames": {},
            "preconditions": source_sha_by_id,
            "expected_corpus_fingerprint": created.value["migration"][
                "before_corpus_fingerprint"
            ],
            "context_id": None,
            "external_reference_rewrites": {},
            "external_reference_rewrite_bindings": [],
            "auxiliary_updates": [],
            "canonical_repair_intents": [],
            "canonical_repair_reference_collapses": [],
            "canonical_repair_binding": None,
        },
        "preview": {
            "after_objects": after_objects,
            "after_sha256_by_id": {
                obj["id"]: _sha(BrainStore.object_bytes(obj))
                for obj in after_objects
            },
            "actions": [{
                "action": "update",
                "object_id": obj["id"],
                "object_kind": obj["kind"],
                "source_id": obj["id"],
                "timestamp_policy": "preserve",
            } for obj in before_objects],
            "reference_rewrites": [],
            "external_reference_bindings": [],
            "before_fingerprint": created.value["migration"][
                "before_corpus_fingerprint"
            ],
            "expected_after_fingerprint": created.value["migration"][
                "expected_after_corpus_fingerprint"
            ],
            "source_sha256_by_id": source_sha_by_id,
        },
    }
    manifest_path = (tmp_path / "manifest.json").resolve()
    manifest_path.write_bytes(canonical_receipt_bytes({
        "migration_version": 3,
        "migration_kind": "display_only",
        "intent": intent,
        "snapshot_id": created.value["pre_mutation_snapshot"]["snapshot_id"],
        "snapshot_manifest_sha256": created.value["pre_mutation_snapshot"][
            "manifest_sha256"
        ],
        "task18_binding_path": str(created.path),
        "task18_binding_sha256": created.sha256,
    }))
    post_path = (tmp_path / "post.json").resolve()
    quote_input = created.value["inputs"]["quote_debt"]
    changed_paths = [
        "brain/objects/code/legacy-locator-name.json",
        "brain/objects/evidence_refs/legacy-ref-name.json",
    ]
    for relative in changed_paths:
        path = repo_root / relative
        obj = json.loads(path.read_bytes())
        obj["title"] = "Ns::run"
        path.write_bytes(BrainStore.object_bytes(obj))
    graph_rows = [
        ("evref.ctx.run", "/locator/code_locator_id", "code.ctx.run"),
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
        "reference_graph": {
            "edge_count": 1,
            "sha256": _json_sha(graph_rows),
            "unchanged": True,
        },
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
    create_args = dict(
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
    return SimpleNamespace(
        module=module,
        created=created,
        snapshot=snapshot,
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        engine_git=engine_git,
        repo_git=repo_git,
        current_git=current_git,
        ancestry=ancestry,
        verify_path=verify_path,
        manifest_path=manifest_path,
        post_path=post_path,
        post_value=post_value,
        completion=completion,
        roadmap=roadmap,
        closure=closure,
        create_args=create_args,
    )


def _write_post_variant(fixture, tmp_path: Path, name: str, mutate) -> tuple[Path, dict]:
    value = deepcopy(fixture.post_value)
    mutate(value)
    path = (tmp_path / f"{name}.json").resolve()
    path.write_bytes(canonical_receipt_bytes(value))
    return path, {**fixture.create_args, "post_report_path": path,
                  "expected_post_report_sha256": _sha(path.read_bytes()),
                  "report_path": (tmp_path / f"{name}-closure.json").resolve()}


def _write_linked_artifact_variant(
    fixture,
    tmp_path: Path,
    name: str,
    *,
    mutate_binding=None,
    mutate_manifest=None,
):
    binding_value = deepcopy(fixture.created.value)
    if mutate_binding is not None:
        mutate_binding(binding_value)
    binding_path = (tmp_path / f"{name}-binding.json").resolve()
    binding_path.write_bytes(canonical_receipt_bytes(binding_value))
    binding_sha = _sha(binding_path.read_bytes())

    manifest_value = json.loads(fixture.manifest_path.read_bytes())
    manifest_value["task18_binding_path"] = str(binding_path)
    manifest_value["task18_binding_sha256"] = binding_sha
    if mutate_manifest is not None:
        mutate_manifest(manifest_value)
    manifest_path = (tmp_path / f"{name}-manifest.json").resolve()
    manifest_path.write_bytes(canonical_receipt_bytes(manifest_value))
    manifest_sha = _sha(manifest_path.read_bytes())

    post_value = deepcopy(fixture.post_value)
    post_value["binding"] = {"path": str(binding_path), "sha256": binding_sha}
    post_value["display_manifest"] = {
        "path": str(manifest_path),
        "sha256": manifest_sha,
    }
    post_value["target_ids_sha256"] = binding_value["migration"][
        "target_ids_sha256"
    ]
    post_path = (tmp_path / f"{name}-post.json").resolve()
    post_path.write_bytes(canonical_receipt_bytes(post_value))
    post_sha = _sha(post_path.read_bytes())
    return SimpleNamespace(
        binding_path=binding_path,
        manifest_path=manifest_path,
        post_path=post_path,
        create_args={
            **fixture.create_args,
            "binding_path": binding_path,
            "expected_binding_sha256": binding_sha,
            "manifest_path": manifest_path,
            "expected_manifest_sha256": manifest_sha,
            "post_report_path": post_path,
            "expected_post_report_sha256": post_sha,
            "report_path": (tmp_path / f"{name}-closure.json").resolve(),
        },
    )


def _write_forged_closure(
    fixture,
    result,
    tmp_path: Path,
    *,
    binding_path: Path | None = None,
    manifest_path: Path | None = None,
    post_path: Path | None = None,
    mutate=None,
) -> tuple[Path, str]:
    value = json.loads(fixture.closure.read_bytes())
    for label, path in (
        ("binding", binding_path),
        ("display_manifest", manifest_path),
        ("post_report", post_path),
    ):
        if path is not None:
            value["artifacts"][label] = dict(
                fixture.module.capture_bound_file(path)
            )
    if mutate is not None:
        mutate(value)
    path = (tmp_path / f"forged-{len(list(tmp_path.glob('forged-*.json')))}.json").resolve()
    payload = canonical_receipt_bytes(value)
    path.write_bytes(payload)
    return path, _sha(payload)


def _forge_expected_title(binding: dict) -> None:
    targets = binding["migration"]["targets"]
    targets[0]["expected_title"] = "FORGED TITLE"
    binding["migration"]["targets_sha256"] = _json_sha(targets)


@pytest.mark.parametrize("pathway", ("create", "verify"))
def test_closure_rejects_rebound_forged_binding_target_semantics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pathway: str,
):
    fixture = _closure_fixture(tmp_path, monkeypatch)
    linked = _write_linked_artifact_variant(
        fixture,
        tmp_path,
        f"forged-target-{pathway}",
        mutate_binding=_forge_expected_title,
    )
    if pathway == "create":
        with pytest.raises(
            Task18VerificationError,
            match="closure_binding_plan_mismatch",
        ):
            create_task18_closure_receipt(**linked.create_args)
        return

    result = create_task18_closure_receipt(**fixture.create_args)
    closure_path, closure_sha = _write_forged_closure(
        fixture,
        result,
        tmp_path,
        binding_path=linked.binding_path,
        manifest_path=linked.manifest_path,
        post_path=linked.post_path,
    )
    with pytest.raises(
        Task18VerificationError,
        match="closure_binding_plan_mismatch",
    ):
        verify_task18_closure_receipt(
            closure_path=closure_path,
            expected_closure_sha256=closure_sha,
            engine_root=fixture.engine_root,
            repo_root=fixture.repo_root,
            brain_root=fixture.brain_root,
            report_path=(tmp_path / "forged-target-verify-report.json").resolve(),
        )


@pytest.mark.parametrize("pathway", ("create", "verify"))
def test_closure_rejects_rebound_forged_manifest_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pathway: str,
):
    fixture = _closure_fixture(tmp_path, monkeypatch)
    linked = _write_linked_artifact_variant(
        fixture,
        tmp_path,
        f"forged-intent-{pathway}",
        mutate_manifest=lambda value: value.__setitem__("intent", {"forged": True}),
    )
    if pathway == "create":
        with pytest.raises(
            Task18VerificationError,
            match="display_manifest_intent_mismatch",
        ):
            create_task18_closure_receipt(**linked.create_args)
        return

    result = create_task18_closure_receipt(**fixture.create_args)
    closure_path, closure_sha = _write_forged_closure(
        fixture,
        result,
        tmp_path,
        binding_path=linked.binding_path,
        manifest_path=linked.manifest_path,
        post_path=linked.post_path,
    )
    with pytest.raises(
        Task18VerificationError,
        match="display_manifest_intent_mismatch",
    ):
        verify_task18_closure_receipt(
            closure_path=closure_path,
            expected_closure_sha256=closure_sha,
            engine_root=fixture.engine_root,
            repo_root=fixture.repo_root,
            brain_root=fixture.brain_root,
            report_path=(tmp_path / "forged-intent-verify-report.json").resolve(),
        )


@pytest.mark.parametrize("pathway", ("create", "verify"))
@pytest.mark.parametrize("invalid_version", (True, 3.0))
def test_closure_rejects_non_integer_display_manifest_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pathway: str,
    invalid_version: object,
):
    fixture = _closure_fixture(tmp_path, monkeypatch)
    linked = _write_linked_artifact_variant(
        fixture,
        tmp_path,
        f"manifest-version-{pathway}-{invalid_version!r}",
        mutate_manifest=lambda value: value.__setitem__(
            "migration_version", invalid_version,
        ),
    )
    if pathway == "create":
        with pytest.raises(
            Task18VerificationError,
            match="display_manifest_binding_mismatch",
        ):
            create_task18_closure_receipt(**linked.create_args)
        return

    result = create_task18_closure_receipt(**fixture.create_args)
    closure_path, closure_sha = _write_forged_closure(
        fixture,
        result,
        tmp_path,
        binding_path=linked.binding_path,
        manifest_path=linked.manifest_path,
        post_path=linked.post_path,
    )
    with pytest.raises(
        Task18VerificationError,
        match="display_manifest_binding_mismatch",
    ):
        verify_task18_closure_receipt(
            closure_path=closure_path,
            expected_closure_sha256=closure_sha,
            engine_root=fixture.engine_root,
            repo_root=fixture.repo_root,
            brain_root=fixture.brain_root,
            report_path=(tmp_path / "manifest-version-verify-report.json").resolve(),
        )


@pytest.mark.parametrize("pathway", ("create", "verify"))
@pytest.mark.parametrize(
    "invalid_created_at",
    (False, None, 7, "", "2026-08-06", "not-time"),
)
def test_closure_rejects_invalid_created_at(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pathway: str,
    invalid_created_at: object,
):
    fixture = _closure_fixture(tmp_path, monkeypatch)
    if pathway == "create":
        with pytest.raises(
            Task18VerificationError,
            match="closure_created_at_invalid",
        ):
            create_task18_closure_receipt(**{
                **fixture.create_args,
                "generated_at": invalid_created_at,
            })
        return

    result = create_task18_closure_receipt(**fixture.create_args)
    closure_path, closure_sha = _write_forged_closure(
        fixture,
        result,
        tmp_path,
        mutate=lambda value: value.__setitem__(
            "created_at", invalid_created_at,
        ),
    )
    with pytest.raises(Task18VerificationError, match="closure_schema_invalid"):
        verify_task18_closure_receipt(
            closure_path=closure_path,
            expected_closure_sha256=closure_sha,
            engine_root=fixture.engine_root,
            repo_root=fixture.repo_root,
            brain_root=fixture.brain_root,
            report_path=(tmp_path / "created-at-verify-report.json").resolve(),
        )


def test_closure_receipt_binds_snapshot_heads_and_committed_docs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from project_brain.snapshot import GitDirtReceipt

    fixture = _closure_fixture(tmp_path, monkeypatch)
    unrelated_path, unrelated_args = _write_post_variant(
        fixture,
        tmp_path,
        "unrelated-post",
        lambda value: value.__setitem__(
            "binding", {"path": str(fixture.created.path), "sha256": "0" * 64},
        ),
    )
    assert unrelated_path.exists()
    with pytest.raises(Task18VerificationError, match="post_report_binding_mismatch"):
        create_task18_closure_receipt(**unrelated_args)

    result = create_task18_closure_receipt(**fixture.create_args)
    assert result.ok is True
    verify_report = (tmp_path / "closure-verify-report.json").resolve()
    verified = verify_task18_closure_receipt(
        closure_path=fixture.closure,
        expected_closure_sha256=result.closure_sha256,
        engine_root=fixture.engine_root,
        repo_root=fixture.repo_root,
        brain_root=fixture.brain_root,
        report_path=verify_report,
    )
    assert verified.ok is True

    changed_dirt = GitDirtReceipt(
        str(fixture.repo_root), fixture.repo_git.head,
        b"?? user.txt\0", _sha(b"?? user.txt\0"), 1,
        b"[]\n", _sha(b"[]\n"),
    )
    fixture.current_git["value"] = (fixture.engine_git, changed_dirt)
    with pytest.raises(Task18VerificationError, match="closure_user_dirt_drift"):
        verify_task18_closure_receipt(
            closure_path=fixture.closure,
            expected_closure_sha256=result.closure_sha256,
            engine_root=fixture.engine_root,
            repo_root=fixture.repo_root,
            brain_root=fixture.brain_root,
            report_path=(tmp_path / "closure-dirt-report.json").resolve(),
        )
    fixture.current_git["value"] = (fixture.engine_git, fixture.repo_git)
    fixture.completion.write_text("drifted\n", encoding="utf-8")
    with pytest.raises(Task18VerificationError, match="committed_docs_drift"):
        verify_task18_closure_receipt(
            closure_path=fixture.closure,
            expected_closure_sha256=result.closure_sha256,
            engine_root=fixture.engine_root,
            repo_root=fixture.repo_root,
            brain_root=fixture.brain_root,
            report_path=(tmp_path / "closure-doc-drift-report.json").resolve(),
        )


@pytest.mark.parametrize(
    "artifact_name",
    ("snapshot", "snapshot_verify", "binding", "manifest", "post", "completion", "roadmap"),
)
def test_closure_verifier_reverse_tail_revalidates_every_bound_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_name: str,
):
    fixture = _closure_fixture(tmp_path, monkeypatch)
    result = create_task18_closure_receipt(**fixture.create_args)
    paths = {
        "snapshot_verify": fixture.verify_path,
        "binding": fixture.created.path,
        "manifest": fixture.manifest_path,
        "post": fixture.post_path,
        "completion": fixture.completion,
        "roadmap": fixture.roadmap,
    }
    if artifact_name == "snapshot":
        snapshot_state = {"value": fixture.snapshot}
        monkeypatch.setattr(
            fixture.module,
            "verify_snapshot",
            lambda *args, **kwargs: snapshot_state["value"],
        )

        def drift():
            snapshot_state["value"] = replace(
                fixture.snapshot,
                corpus_fingerprint="0" * 64,
            )
    else:
        target = paths[artifact_name]
        original = target.read_bytes()

        def drift():
            target.write_bytes(original + b" ")

    monkeypatch.setattr(fixture.module, "_closure_reverse_tail_hook", drift)
    with pytest.raises(Task18VerificationError):
        verify_task18_closure_receipt(
            closure_path=fixture.closure,
            expected_closure_sha256=result.closure_sha256,
            engine_root=fixture.engine_root,
            repo_root=fixture.repo_root,
            brain_root=fixture.brain_root,
            report_path=(tmp_path / f"tail-{artifact_name}.json").resolve(),
        )


def _mutate_post_evidence(value: dict, case: str) -> None:
    if case == "changed_paths":
        value["changed_paths"] = [
            "brain/objects/code/fake-a.json",
            "brain/objects/code/fake-b.json",
        ]
    elif case == "symbol_hash":
        value["noncanonical_symbol_state"]["ids_sha256"] = "0" * 64
    elif case == "graph_evidence":
        value["reference_graph"] = {
            "edge_count": 0,
            "sha256": "0" * 64,
            "unchanged": True,
        }
    elif case == "integer_bool":
        value["create_count"] = False
    elif case == "integer_float":
        value["delete_count"] = 0.0
    elif case == "version_bool":
        value["version"] = True
    elif case == "version_float":
        value["version"] = 1.0
    else:  # pragma: no cover
        raise AssertionError(case)


@pytest.mark.parametrize(
    "case",
    (
        "changed_paths",
        "symbol_hash",
        "graph_evidence",
        "integer_bool",
        "integer_float",
        "version_bool",
        "version_float",
    ),
)
def test_closure_create_rebinds_post_evidence_to_final_corpus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
):
    fixture = _closure_fixture(tmp_path, monkeypatch)
    _, create_args = _write_post_variant(
        fixture,
        tmp_path,
        f"bad-create-{case}",
        lambda value: _mutate_post_evidence(value, case),
    )
    with pytest.raises(Task18VerificationError):
        create_task18_closure_receipt(**create_args)


@pytest.mark.parametrize(
    "case",
    (
        "changed_paths",
        "symbol_hash",
        "graph_evidence",
        "integer_bool",
        "integer_float",
        "version_bool",
        "version_float",
    ),
)
def test_closure_verify_independently_rebinds_post_evidence_to_final_corpus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
):
    fixture = _closure_fixture(tmp_path, monkeypatch)
    result = create_task18_closure_receipt(**fixture.create_args)
    post_path, _ = _write_post_variant(
        fixture,
        tmp_path,
        f"bad-verify-{case}",
        lambda value: _mutate_post_evidence(value, case),
    )
    closure_path, closure_sha = _write_forged_closure(
        fixture,
        result,
        tmp_path,
        post_path=post_path,
    )
    with pytest.raises(Task18VerificationError):
        verify_task18_closure_receipt(
            closure_path=closure_path,
            expected_closure_sha256=closure_sha,
            engine_root=fixture.engine_root,
            repo_root=fixture.repo_root,
            brain_root=fixture.brain_root,
            report_path=(tmp_path / f"bad-verify-{case}-report.json").resolve(),
        )


def test_closure_create_rejects_unrelated_binding_heads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture = _closure_fixture(tmp_path, monkeypatch)
    fixture.ancestry["bb2"] = False
    with pytest.raises(Task18VerificationError, match="bb2_head_not_ancestor"):
        create_task18_closure_receipt(**fixture.create_args)


def test_closure_verify_rejects_unrelated_binding_heads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture = _closure_fixture(tmp_path, monkeypatch)
    result = create_task18_closure_receipt(**fixture.create_args)
    fixture.ancestry["engine"] = False
    with pytest.raises(Task18VerificationError, match="engine_head_not_ancestor"):
        verify_task18_closure_receipt(
            closure_path=fixture.closure,
            expected_closure_sha256=result.closure_sha256,
            engine_root=fixture.engine_root,
            repo_root=fixture.repo_root,
            brain_root=fixture.brain_root,
            report_path=(tmp_path / "unrelated-head-verify.json").resolve(),
        )


@pytest.mark.parametrize("invalid_version", (True, 1.0))
def test_closure_verify_rejects_non_integer_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid_version: object,
):
    fixture = _closure_fixture(tmp_path, monkeypatch)
    result = create_task18_closure_receipt(**fixture.create_args)
    closure_path, closure_sha = _write_forged_closure(
        fixture,
        result,
        tmp_path,
        mutate=lambda value: value.__setitem__("version", invalid_version),
    )
    with pytest.raises(Task18VerificationError, match="closure_schema_invalid"):
        verify_task18_closure_receipt(
            closure_path=closure_path,
            expected_closure_sha256=closure_sha,
            engine_root=fixture.engine_root,
            repo_root=fixture.repo_root,
            brain_root=fixture.brain_root,
            report_path=(tmp_path / "bool-version-report.json").resolve(),
        )
