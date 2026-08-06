from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import pytest

from project_brain.foundation import canonical_receipt_bytes
from project_brain.mutation import corpus_fingerprint
from project_brain.snapshot import GitDirtReceipt, SnapshotVerification
from project_brain.store import BrainStore
from project_brain.task18_binding import (
    TASK18_BINDING_KEYS,
    Task18BindingError,
    Task18BindingRequest,
    create_task18_binding,
)
from project_brain.task18_binding_verify import verify_task18_binding
from project_brain.task18_state import RemoteRefReceipt


FIXED_TIME = "2026-08-06T12:00:00+09:00"


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


@dataclass
class SyntheticTask18:
    request: Task18BindingRequest
    store: BrainStore
    engine_git: GitDirtReceipt
    bb2_git: GitDirtReceipt
    remote: RemoteRefReceipt
    corpus_state: dict[str, object]
    snapshot: SnapshotVerification
    committed: dict[str, dict[str, object]]
    engine_cached: tuple[str, ...] = ()
    bb2_cached: tuple[str, ...] = ()

    def install(self, monkeypatch: pytest.MonkeyPatch, module) -> list[str]:
        calls: list[str] = []

        def git_dirt(root: Path, *, label: str):
            calls.append(f"git:{label}")
            return self.engine_git if root == self.request.engine_root else self.bb2_git

        def cached(root: Path):
            calls.append("cached:engine" if root == self.request.engine_root else "cached:bb2")
            return self.engine_cached if root == self.request.engine_root else self.bb2_cached

        def remote(*args, **kwargs):
            calls.append("remote")
            return self.remote

        def corpus(root: Path):
            calls.append("corpus")
            return deepcopy(self.corpus_state)

        def committed(root: Path, relative: Path, commit: str):
            calls.append(f"committed:{relative.as_posix()}")
            return deepcopy(self.committed[relative.as_posix()])

        def snapshot(root: Path, *, expected_manifest_sha256: str):
            calls.append("snapshot")
            return self.snapshot

        def load(root: Path):
            calls.append("store")
            return self.store

        monkeypatch.setattr(module, "capture_git_dirt_receipt", git_dirt)
        monkeypatch.setattr(module, "capture_cached_paths", cached)
        monkeypatch.setattr(module, "capture_remote_ref", remote)
        monkeypatch.setattr(module, "capture_task18_corpus_state", corpus)
        monkeypatch.setattr(module, "capture_committed_input", committed)
        monkeypatch.setattr(module, "verify_snapshot", snapshot)
        monkeypatch.setattr(module.BrainStore, "load", load)
        monkeypatch.setattr(module, "REQUIRED_CODE_LOCATOR_COUNT", 1)
        monkeypatch.setattr(module, "REQUIRED_EVIDENCE_REF_COUNT", 1)
        return calls


@pytest.fixture
def task18_fixture(tmp_path: Path) -> SyntheticTask18:
    engine_root = (tmp_path / "engine").resolve()
    repo_root = (tmp_path / "bb2").resolve()
    brain_root = repo_root / "brain"
    snapshot_root = repo_root / ".snapshots" / "pre"
    for path in (engine_root, brain_root, snapshot_root):
        path.mkdir(parents=True)

    locator = {
        "id": "code.ctx.run",
        "kind": "CodeLocator",
        "title": "old locator",
        "path": "src/Run.cpp",
        "symbol": "Ns::run",
    }
    ref = {
        "id": "evref.ctx.run",
        "kind": "EvidenceRef",
        "title": "old ref",
        "ref_type": "code_locator",
        "locator": {"code_locator_id": locator["id"]},
    }
    objects = {locator["id"]: locator, ref["id"]: ref}
    source_hashes = {
        object_id: _sha(BrainStore.object_bytes(obj))
        for object_id, obj in objects.items()
    }
    store = BrainStore(objects, source_sha256_by_id=source_hashes)
    actual_locator_path = brain_root / "objects/code/legacy-locator-name.json"
    actual_ref_path = brain_root / "objects/evidence_refs/legacy-ref-name.json"
    actual_locator_path.parent.mkdir(parents=True)
    actual_ref_path.parent.mkdir(parents=True)
    actual_locator_path.write_bytes(BrainStore.object_bytes(locator))
    actual_ref_path.write_bytes(BrainStore.object_bytes(ref))

    p0_path = repo_root / ".snapshots" / "p0-handoff.json"
    measurement_path = repo_root / ".snapshots" / "measurement.json"
    quote_path = brain_root / "quote-debt.json"
    snapshot_verify_path = snapshot_root / "verify.json"
    design_path = engine_root / "docs" / "design.md"
    plan_path = engine_root / "docs" / "plan.md"
    design_path.parent.mkdir()
    design_path.write_bytes(b"approved design\n")
    plan_path.write_bytes(b"committed plan\n")

    p0_bytes = canonical_receipt_bytes({"ok": True, "purpose": "p0-handoff"})
    p0_path.parent.mkdir(exist_ok=True)
    p0_path.write_bytes(p0_bytes)
    locator_ids = [locator["id"]]
    pair_rows = [{
        "evidence_ref_id": ref["id"],
        "code_locator_id": locator["id"],
        "titles_equal_now": False,
        "titles_equal_after_locator_canonicalization": False,
    }]
    measurement = {
        "p0_handoff": {"path": str(p0_path), "sha256": _sha(p0_bytes)},
        "display_labels": {
            "target_count": 1,
            "target_ids": locator_ids,
            "target_ids_sha256": _json_sha(locator_ids),
        },
        "evidence_ref_pairs": {
            "paired": 1,
            "titles_equal_now": 0,
            "titles_equal_after_locator_canonicalization": 0,
            "mismatches_after_if_only_locator_changes": 1,
            "new_mismatches_if_only_locator_changes": 1,
            "pair_rows_sha256": _json_sha(pair_rows),
        },
        "quote_backlog": {
            "target_count": 1,
            "target_ids": locator_ids,
            "target_ids_sha256": _json_sha(locator_ids),
        },
    }
    measurement_bytes = canonical_receipt_bytes(measurement)
    measurement_path.write_bytes(measurement_bytes)
    quote_inventory = {
        "version": 1,
        "purpose": "legacy_code_locator_quote_debt",
        "legacy_quote_semantics": "reviewed at ingest, not mechanically re-checkable now",
        "engine_sha": "a" * 40,
        "repo_sha": "b" * 40,
        "target_revision_sha": "c" * 40,
        "brain_root": str(brain_root),
        "index_db_path": str(brain_root / ".brain-local/index.db"),
        "measurement_path": str(measurement_path),
        "measurement_sha256": _sha(measurement_bytes),
        "generated_at": FIXED_TIME,
        "quote_debt_ids": locator_ids,
        "quote_debt_ids_sha256": _json_sha(locator_ids),
        "rows": [{"locator_id": locator["id"]}],
    }
    quote_bytes = canonical_receipt_bytes(quote_inventory)
    quote_path.write_bytes(quote_bytes)

    engine_head = "a" * 40
    repo_head = "b" * 40
    manifest_sha = "d" * 64
    snapshot = SnapshotVerification(
        ok=True,
        snapshot_id="task18-pre",
        manifest_sha256=manifest_sha,
        file_count=7,
        repo_head=repo_head,
        engine_head=engine_head,
        corpus_fingerprint=corpus_fingerprint(store),
    )
    snapshot_verify_bytes = canonical_receipt_bytes({
        "ok": True,
        "snapshot_id": snapshot.snapshot_id,
        "manifest_sha256": manifest_sha,
        "file_count": snapshot.file_count,
    })
    snapshot_verify_path.write_bytes(snapshot_verify_bytes)

    empty_status = b""
    empty_manifest = b"[]\n"
    engine_git = GitDirtReceipt(
        str(engine_root), engine_head, empty_status, _sha(empty_status), 0,
        empty_manifest, _sha(empty_manifest),
    )
    bb2_git = GitDirtReceipt(
        str(repo_root), repo_head, empty_status, _sha(empty_status), 0,
        empty_manifest, _sha(empty_manifest),
    )
    corpus_state = {
        "corpus": {
            "mutation_fingerprint": corpus_fingerprint(store),
            "objects_tree_sha256": "1" * 64,
            "raw_tree_sha256": "2" * 64,
        },
        "search_index": {
            "live_corpus_fingerprint": "3" * 64,
            "meta_corpus_fingerprint": "3" * 64,
            "db_file_sha256": "4" * 64,
        },
        "stale_set": {"sha256": "5" * 64},
    }
    design_sha = _sha(design_path.read_bytes())
    plan_sha = _sha(plan_path.read_bytes())
    design_commit = "6" * 40
    plan_commit = "7" * 40
    committed = {
        "docs/design.md": {
            "path": str(design_path),
            "commit_sha": design_commit,
            "file_sha256": design_sha,
            "mode": 0o644,
        },
        "docs/plan.md": {
            "path": str(plan_path),
            "commit_sha": plan_commit,
            "file_sha256": plan_sha,
            "mode": 0o644,
        },
    }
    request = Task18BindingRequest(
        binding_path=(snapshot_root / "binding.json").resolve(),
        engine_root=engine_root,
        repo_root=repo_root,
        brain_root=brain_root,
        expected_engine_head=engine_head,
        expected_repo_head=repo_head,
        expected_engine_status_sha256=engine_git.status_sha256,
        expected_engine_dirt_content_sha256=engine_git.content_manifest_sha256,
        expected_repo_status_sha256=bb2_git.status_sha256,
        expected_repo_dirt_content_sha256=bb2_git.content_manifest_sha256,
        local_target_ref="refs/remotes/origin/develop",
        remote="origin",
        remote_target_ref="refs/heads/develop",
        target_revision_sha="c" * 40,
        p0_handoff_path=p0_path.resolve(),
        expected_p0_handoff_sha256=_sha(p0_bytes),
        measurement_path=measurement_path.resolve(),
        expected_measurement_sha256=_sha(measurement_bytes),
        design_path=design_path.resolve(),
        design_commit_sha=design_commit,
        expected_design_file_sha256=design_sha,
        plan_path=plan_path.resolve(),
        plan_commit_sha=plan_commit,
        expected_plan_file_sha256=plan_sha,
        quote_debt_path=quote_path.resolve(),
        expected_quote_debt_sha256=_sha(quote_bytes),
        snapshot_root=snapshot_root.resolve(),
        expected_snapshot_manifest_sha256=manifest_sha,
        snapshot_verify_receipt_path=snapshot_verify_path.resolve(),
        expected_snapshot_verify_receipt_sha256=_sha(snapshot_verify_bytes),
    )
    remote = RemoteRefReceipt(
        request.local_target_ref,
        request.target_revision_sha,
        request.remote,
        request.remote_target_ref,
        request.target_revision_sha,
    )
    return SyntheticTask18(
        request, store, engine_git, bb2_git, remote, corpus_state, snapshot,
        committed,
    )


def _fixed_clock() -> str:
    return FIXED_TIME


def test_create_task18_binding_records_exact_inputs_and_display_closure(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as module

    task18_fixture.install(monkeypatch, module)
    result = create_task18_binding(task18_fixture.request, clock=_fixed_clock)

    assert set(result.value) == TASK18_BINDING_KEYS
    assert result.value["task18_allowed"] is True
    assert result.value["migration"]["total_count"] == 2
    assert result.value["migration"]["targets"][1]["kind"] == "EvidenceRef"
    assert result.value["migration"]["targets"][1]["paired_locator_id"] == "code.ctx.run"
    assert result.value["migration"]["code_locator_count"] == 1
    assert result.value["migration"]["evidence_ref_count"] == 1
    assert result.value["engine"]["cached_paths"] == []
    assert result.value["bb2"]["cached_paths"] == []


def test_independent_verifier_accepts_unchanged_binding(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as create_module
    import project_brain.task18_binding_verify as verify_module

    create_calls = task18_fixture.install(monkeypatch, create_module)
    result = create_task18_binding(task18_fixture.request, clock=_fixed_clock)
    verify_calls = task18_fixture.install(monkeypatch, verify_module)

    verification = verify_task18_binding(
        binding_path=result.path,
        expected_binding_sha256=result.sha256,
        engine_root=task18_fixture.request.engine_root,
        repo_root=task18_fixture.request.repo_root,
        brain_root=task18_fixture.request.brain_root,
    )

    assert verification.task18_allowed is True
    assert len(verification.migration_targets) == 2
    assert create_calls != verify_calls


@pytest.mark.parametrize(
    "change",
    [
        "drop_locator",
        "add_unmeasured_locator",
        "change_pair_row",
        "change_quote_debt_ids",
    ],
)
def test_create_binding_rejects_live_closure_that_differs_from_measurement(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
    change: str,
):
    import project_brain.task18_binding as module

    if change == "drop_locator":
        task18_fixture.store.get("code.ctx.run")["title"] = "Ns::run"
    elif change == "add_unmeasured_locator":
        extra = {
            "id": "code.ctx.extra",
            "kind": "CodeLocator",
            "title": "old",
            "path": "src/Extra.cpp",
            "symbol": "Ns::extra",
        }
        task18_fixture.store = BrainStore({
            **{obj["id"]: obj for obj in task18_fixture.store.all()},
            extra["id"]: extra,
        }, source_sha256_by_id={
            **{
                obj["id"]: _sha(BrainStore.object_bytes(obj))
                for obj in task18_fixture.store.all()
            },
            extra["id"]: _sha(BrainStore.object_bytes(extra)),
        })
    elif change == "change_pair_row":
        task18_fixture.store.get("evref.ctx.run")["title"] = "Ns::run"
    else:
        task18_fixture.store.get("code.ctx.run")["verified_quote"] = "quote"
    task18_fixture.install(monkeypatch, module)

    with pytest.raises(Task18BindingError, match="measurement_closure_mismatch"):
        create_task18_binding(task18_fixture.request, clock=_fixed_clock)


def test_create_and_verify_reject_target_path_overlapping_baseline_user_dirt(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as create_module

    dirty_path = "brain/objects/code/legacy-locator-name.json"
    manifest = (
        json.dumps(
            [{
                "path": dirty_path,
                "status": " M",
                "type": "regular",
                "mode": 0o644,
                "size": 1,
                "content_sha256": "8" * 64,
            }],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    task18_fixture.bb2_git = GitDirtReceipt(
        task18_fixture.bb2_git.root,
        task18_fixture.bb2_git.head,
        b" M " + dirty_path.encode() + b"\0",
        _sha(b" M " + dirty_path.encode() + b"\0"),
        1,
        manifest,
        _sha(manifest),
    )
    task18_fixture.request = Task18BindingRequest(
        **{
            **task18_fixture.request.__dict__,
            "expected_repo_status_sha256": task18_fixture.bb2_git.status_sha256,
            "expected_repo_dirt_content_sha256": task18_fixture.bb2_git.content_manifest_sha256,
        }
    )
    task18_fixture.install(monkeypatch, create_module)

    with pytest.raises(Task18BindingError, match="target_overlaps_user_dirt"):
        create_task18_binding(task18_fixture.request, clock=_fixed_clock)


def test_create_rejects_unsafe_target_id_in_actual_source_scan(
    task18_fixture: SyntheticTask18,
):
    import project_brain.task18_binding as module

    source_sha = _sha(BrainStore.object_bytes(task18_fixture.store.get("code.ctx.run")))

    with pytest.raises(Task18BindingError, match="migration_target_source_invalid"):
        module._scan_target_sources(
            brain_root=task18_fixture.request.brain_root,
            repo_root=task18_fixture.request.repo_root,
            targets=[{
                "id": "../unsafe",
                "kind": "CodeLocator",
                "before_object_sha256": source_sha,
            }],
        )


@pytest.mark.parametrize("case", ["missing", "duplicate"])
def test_create_source_scan_rejects_missing_or_duplicate_target_source(
    task18_fixture: SyntheticTask18,
    case: str,
):
    import project_brain.task18_binding as module

    locator = task18_fixture.store.get("code.ctx.run")
    source_sha = _sha(BrainStore.object_bytes(locator))
    target = {
        "id": "code.ctx.run" if case == "duplicate" else "code.ctx.missing",
        "kind": "CodeLocator",
        "before_object_sha256": source_sha,
    }
    if case == "duplicate":
        duplicate = (
            task18_fixture.request.brain_root
            / "objects/code/second-noncanonical-name.json"
        )
        duplicate.write_bytes(BrainStore.object_bytes(locator))

    with pytest.raises(Task18BindingError, match="migration_target_source_invalid"):
        module._scan_target_sources(
            brain_root=task18_fixture.request.brain_root,
            repo_root=task18_fixture.request.repo_root,
            targets=[target],
        )


def test_create_rejects_inventory_ids_that_drift_from_measurement(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as module

    inventory = json.loads(task18_fixture.request.quote_debt_path.read_bytes())
    inventory["quote_debt_ids"] = []
    inventory["quote_debt_ids_sha256"] = _json_sha([])
    inventory["rows"] = []
    data = canonical_receipt_bytes(inventory)
    task18_fixture.request.quote_debt_path.write_bytes(data)
    task18_fixture.request = Task18BindingRequest(**{
        **task18_fixture.request.__dict__,
        "expected_quote_debt_sha256": _sha(data),
    })
    task18_fixture.install(monkeypatch, module)

    with pytest.raises(Task18BindingError, match="measurement_closure_mismatch"):
        create_task18_binding(task18_fixture.request, clock=_fixed_clock)


def test_create_normalizes_nan_input_to_task18_binding_error(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as module

    data = b'{"display_labels":NaN}\n'
    task18_fixture.request.measurement_path.write_bytes(data)
    task18_fixture.request = Task18BindingRequest(**{
        **task18_fixture.request.__dict__,
        "expected_measurement_sha256": _sha(data),
    })
    task18_fixture.install(monkeypatch, module)

    with pytest.raises(Task18BindingError, match="measurement_json_invalid"):
        create_task18_binding(task18_fixture.request, clock=_fixed_clock)


@pytest.mark.parametrize(
    "input_name",
    [
        "p0_handoff_path",
        "measurement_path",
        "design_path",
        "plan_path",
        "quote_debt_path",
        "snapshot_verify_receipt_path",
    ],
)
def test_verifier_rejects_each_bound_input_drift_explicitly(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
    input_name: str,
):
    import project_brain.task18_binding as create_module
    import project_brain.task18_binding_verify as verify_module

    task18_fixture.install(monkeypatch, create_module)
    result = create_task18_binding(task18_fixture.request, clock=_fixed_clock)
    path = getattr(task18_fixture.request, input_name)
    path.write_bytes(path.read_bytes() + b"drift\n")
    task18_fixture.install(monkeypatch, verify_module)

    with pytest.raises(Task18BindingError):
        verify_task18_binding(
            binding_path=result.path,
            expected_binding_sha256=result.sha256,
            engine_root=task18_fixture.request.engine_root,
            repo_root=task18_fixture.request.repo_root,
            brain_root=task18_fixture.request.brain_root,
        )


def test_generator_rechecks_staged_paths_immediately_before_create(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as module

    task18_fixture.install(monkeypatch, module)
    calls = 0

    def cached(root: Path):
        nonlocal calls
        calls += 1
        if calls > 2 and root == task18_fixture.request.repo_root:
            return ("newly-staged.json",)
        return ()

    monkeypatch.setattr(module, "capture_cached_paths", cached)

    with pytest.raises(Task18BindingError, match="state_changed_before_binding"):
        create_task18_binding(task18_fixture.request, clock=_fixed_clock)
    assert not task18_fixture.request.binding_path.exists()


def test_generator_rechecks_corpus_immediately_before_create(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as module

    task18_fixture.install(monkeypatch, module)
    calls = 0

    def corpus(root: Path):
        nonlocal calls
        calls += 1
        value = deepcopy(task18_fixture.corpus_state)
        if calls > 1:
            value["corpus"]["objects_tree_sha256"] = "0" * 64
        return value

    monkeypatch.setattr(module, "capture_task18_corpus_state", corpus)

    with pytest.raises(Task18BindingError, match="state_changed_before_binding"):
        create_task18_binding(task18_fixture.request, clock=_fixed_clock)
    assert not task18_fixture.request.binding_path.exists()


def test_generator_rechecks_input_immediately_before_create(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as module

    task18_fixture.install(monkeypatch, module)
    original_snapshot = module.verify_snapshot
    calls = 0

    def snapshot(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original_snapshot(*args, **kwargs)
        if calls == 1:
            task18_fixture.request.p0_handoff_path.write_bytes(b"late drift\n")
        return result

    monkeypatch.setattr(module, "verify_snapshot", snapshot)

    with pytest.raises(Task18BindingError, match="state_changed_before_binding"):
        create_task18_binding(task18_fixture.request, clock=_fixed_clock)
    assert not task18_fixture.request.binding_path.exists()


def test_generator_tail_rechecks_input_changed_during_final_snapshot_verify(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as module

    task18_fixture.install(monkeypatch, module)
    original = module.verify_snapshot
    calls = 0

    def snapshot(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            task18_fixture.request.measurement_path.write_bytes(
                b"changed during final snapshot verify\n"
            )
        return result

    monkeypatch.setattr(module, "verify_snapshot", snapshot)

    with pytest.raises(Task18BindingError, match="state_changed_before_binding"):
        create_task18_binding(task18_fixture.request, clock=_fixed_clock)
    assert not task18_fixture.request.binding_path.exists()


def test_verifier_rejects_noncanonical_actual_target_path_in_bound_dirt(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as create_module
    import project_brain.task18_binding_verify as verify_module

    task18_fixture.install(monkeypatch, create_module)
    result = create_task18_binding(task18_fixture.request, clock=_fixed_clock)
    dirty_path = "brain/objects/code/legacy-locator-name.json"
    status = b" M " + dirty_path.encode() + b"\0"
    manifest = (
        json.dumps(
            [{
                "path": dirty_path,
                "status": " M",
                "type": "regular",
                "mode": 0o644,
                "size": 1,
                "content_sha256": "8" * 64,
            }],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    task18_fixture.bb2_git = GitDirtReceipt(
        task18_fixture.bb2_git.root,
        task18_fixture.bb2_git.head,
        status,
        _sha(status),
        1,
        manifest,
        _sha(manifest),
    )
    forged = deepcopy(result.value)
    forged["bb2"].update({
        "status_bytes_base64": __import__("base64").b64encode(status).decode(),
        "status_sha256": _sha(status),
        "dirt_manifest_base64": __import__("base64").b64encode(manifest).decode(),
        "dirt_content_sha256": _sha(manifest),
    })
    forged_path = result.path.with_name("forged-binding.json")
    forged_bytes = canonical_receipt_bytes(forged)
    forged_path.write_bytes(forged_bytes)
    task18_fixture.install(monkeypatch, verify_module)

    with pytest.raises(Task18BindingError, match="target_overlaps_user_dirt"):
        verify_task18_binding(
            binding_path=forged_path,
            expected_binding_sha256=_sha(forged_bytes),
            engine_root=task18_fixture.request.engine_root,
            repo_root=task18_fixture.request.repo_root,
            brain_root=task18_fixture.request.brain_root,
        )


@pytest.mark.parametrize("drift", ["staged", "corpus", "input"])
def test_verifier_rechecks_state_immediately_before_return(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
):
    import project_brain.task18_binding as create_module
    import project_brain.task18_binding_verify as verify_module

    task18_fixture.install(monkeypatch, create_module)
    result = create_task18_binding(task18_fixture.request, clock=_fixed_clock)
    task18_fixture.install(monkeypatch, verify_module)
    if drift == "staged":
        calls = 0

        def cached(root: Path):
            nonlocal calls
            calls += 1
            if calls > 2 and root == task18_fixture.request.repo_root:
                return ("late-stage.json",)
            return ()

        monkeypatch.setattr(verify_module, "capture_cached_paths", cached)
    elif drift == "corpus":
        calls = 0

        def corpus(root: Path):
            nonlocal calls
            calls += 1
            value = deepcopy(task18_fixture.corpus_state)
            if calls > 1:
                value["stale_set"]["sha256"] = "0" * 64
            return value

        monkeypatch.setattr(verify_module, "capture_task18_corpus_state", corpus)
    else:
        original = verify_module._current_migration

        def current(store: BrainStore):
            value = original(store)
            task18_fixture.request.p0_handoff_path.write_bytes(b"late input drift\n")
            return value

        monkeypatch.setattr(verify_module, "_current_migration", current)

    with pytest.raises(Task18BindingError, match="state_changed_during_verification"):
        verify_task18_binding(
            binding_path=result.path,
            expected_binding_sha256=result.sha256,
            engine_root=task18_fixture.request.engine_root,
            repo_root=task18_fixture.request.repo_root,
            brain_root=task18_fixture.request.brain_root,
        )


def test_verifier_tail_rechecks_input_changed_during_final_remote_lookup(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
):
    import project_brain.task18_binding as create_module
    import project_brain.task18_binding_verify as verify_module

    task18_fixture.install(monkeypatch, create_module)
    result = create_task18_binding(task18_fixture.request, clock=_fixed_clock)
    task18_fixture.install(monkeypatch, verify_module)
    original = verify_module.capture_remote_ref
    calls = 0

    def remote(*args, **kwargs):
        nonlocal calls
        calls += 1
        value = original(*args, **kwargs)
        if calls == 2:
            task18_fixture.request.p0_handoff_path.write_bytes(
                b"changed during final remote lookup\n"
            )
        return value

    monkeypatch.setattr(verify_module, "capture_remote_ref", remote)

    with pytest.raises(Task18BindingError, match="state_changed_during_verification"):
        verify_task18_binding(
            binding_path=result.path,
            expected_binding_sha256=result.sha256,
            engine_root=task18_fixture.request.engine_root,
            repo_root=task18_fixture.request.repo_root,
            brain_root=task18_fixture.request.brain_root,
        )


@pytest.mark.parametrize(
    "drift",
    [
        "engine_head",
        "engine_status",
        "engine_content",
        "bb2_head",
        "bb2_status",
        "bb2_content",
        "cached_path",
        "remote_ref",
        "corpus",
        "index_bytes",
        "stale_set",
        "input",
        "snapshot",
        "display_target",
    ],
)
def test_verify_task18_binding_rejects_each_bound_state_drift(
    task18_fixture: SyntheticTask18,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
):
    import project_brain.task18_binding as create_module
    import project_brain.task18_binding_verify as verify_module

    create_calls = task18_fixture.install(monkeypatch, create_module)
    result = create_task18_binding(task18_fixture.request, clock=_fixed_clock)
    if drift == "engine_head":
        task18_fixture.engine_git = GitDirtReceipt(
            task18_fixture.engine_git.root, "f" * 40,
            task18_fixture.engine_git.status_bytes,
            task18_fixture.engine_git.status_sha256,
            task18_fixture.engine_git.entry_count,
            task18_fixture.engine_git.content_manifest_bytes,
            task18_fixture.engine_git.content_manifest_sha256,
        )
    elif drift == "engine_status":
        task18_fixture.engine_git = GitDirtReceipt(
            task18_fixture.engine_git.root, task18_fixture.engine_git.head,
            b"?? new\0", _sha(b"?? new\0"), 0,
            task18_fixture.engine_git.content_manifest_bytes,
            task18_fixture.engine_git.content_manifest_sha256,
        )
    elif drift == "engine_content":
        task18_fixture.engine_git = GitDirtReceipt(
            task18_fixture.engine_git.root, task18_fixture.engine_git.head,
            task18_fixture.engine_git.status_bytes,
            task18_fixture.engine_git.status_sha256, 0,
            b"[]", _sha(b"[]"),
        )
    elif drift == "bb2_head":
        task18_fixture.bb2_git = GitDirtReceipt(
            task18_fixture.bb2_git.root, "e" * 40,
            task18_fixture.bb2_git.status_bytes,
            task18_fixture.bb2_git.status_sha256, 0,
            task18_fixture.bb2_git.content_manifest_bytes,
            task18_fixture.bb2_git.content_manifest_sha256,
        )
    elif drift == "bb2_status":
        task18_fixture.bb2_git = GitDirtReceipt(
            task18_fixture.bb2_git.root, task18_fixture.bb2_git.head,
            b"?? other\0", _sha(b"?? other\0"), 0,
            task18_fixture.bb2_git.content_manifest_bytes,
            task18_fixture.bb2_git.content_manifest_sha256,
        )
    elif drift == "bb2_content":
        task18_fixture.bb2_git = GitDirtReceipt(
            task18_fixture.bb2_git.root, task18_fixture.bb2_git.head,
            task18_fixture.bb2_git.status_bytes,
            task18_fixture.bb2_git.status_sha256, 0,
            b"[]", _sha(b"[]"),
        )
    elif drift == "cached_path":
        task18_fixture.bb2_cached = ("staged.json",)
    elif drift == "remote_ref":
        task18_fixture.remote = RemoteRefReceipt(
            task18_fixture.remote.local_ref, "f" * 40,
            task18_fixture.remote.remote, task18_fixture.remote.remote_ref,
            "f" * 40,
        )
    elif drift == "corpus":
        task18_fixture.corpus_state["corpus"]["objects_tree_sha256"] = "0" * 64
    elif drift == "index_bytes":
        task18_fixture.corpus_state["search_index"]["db_file_sha256"] = "0" * 64
    elif drift == "stale_set":
        task18_fixture.corpus_state["stale_set"]["sha256"] = "0" * 64
    elif drift == "input":
        task18_fixture.request.p0_handoff_path.write_bytes(b"changed\n")
    elif drift == "snapshot":
        task18_fixture.snapshot = SnapshotVerification(
            **{**task18_fixture.snapshot.__dict__, "file_count": 8}
        )
    else:
        task18_fixture.store.get("code.ctx.run")["title"] = "Ns::run"
    verify_calls = task18_fixture.install(monkeypatch, verify_module)

    with pytest.raises(Task18BindingError):
        verify_task18_binding(
            binding_path=result.path,
            expected_binding_sha256=result.sha256,
            engine_root=task18_fixture.request.engine_root,
            repo_root=task18_fixture.request.repo_root,
            brain_root=task18_fixture.request.brain_root,
        )
    assert create_calls != verify_calls
