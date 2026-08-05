from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from project_brain import foundation
from project_brain.foundation import (
    FoundationError,
    atomic_create_bound_receipt,
    atomic_create_receipt,
    BB2_MANAGED_SKILL_ROOTS,
    build_foundation_handoff,
    canonical_receipt_bytes,
    capture_foundation_baseline,
    capture_tree_receipt,
    foundation_command_specs,
    run_foundation_gate,
    task15_stage_paths,
    validate_task15_cached_paths,
    verify_artifact_inventory,
    verify_bound_receipt,
    verify_foundation_invariants,
)
from project_brain.snapshot import SnapshotRequest, create_snapshot, verify_snapshot


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _commit(root: Path, message: str = "fixture") -> str:
    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "foundation@test.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "Foundation Test"],
            check=True,
        )
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", message],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@dataclass
class FoundationFixture:
    engine: Path
    repo: Path
    brain: Path
    artifact_root: Path
    snapshots_root: Path
    managed: Path
    manifest: Path
    object_file: Path
    raw_file: Path
    index_db: Path
    stale_set: Path
    user_dirt: Path

    @property
    def capture_args(self) -> dict[str, Path]:
        return {
            "engine_root": self.engine,
            "repo_root": self.repo,
            "brain_root": self.brain,
            "artifact_root": self.artifact_root,
            "ignored_snapshots_root": self.snapshots_root,
        }

    def verify(self, baseline, **overrides):
        values = {
            **self.capture_args,
            "allowed_managed_paths": (),
            "allowed_installer_control_paths": (),
            "allowed_artifact_files": (),
            "verified_snapshot_root": None,
        }
        values.update(overrides)
        return verify_foundation_invariants(baseline, **values)


@pytest.fixture
def foundation_fixture(tmp_path, monkeypatch) -> FoundationFixture:
    engine = (tmp_path / "engine").resolve()
    _write(engine / "src/project_brain/__init__.py", b"\n")
    _write(engine / "src/project_brain/cli.py", b"def main(): pass\n")
    _write(engine / "pyproject.toml", b"[project]\nname='fixture'\n")
    _write(engine / "uv.lock", b"version = 1\n")
    _commit(engine, "engine")

    repo = (tmp_path / "bb2").resolve()
    brain = repo / "brain"
    object_file = brain / "objects/domain/context.json"
    raw_file = brain / "raw/sources/source.md"
    _write(
        object_file,
        json.dumps({"id": "domain.fixture", "kind": "DomainContext"}).encode(),
    )
    _write(raw_file, b"fixture raw source\n")
    managed = repo / ".agents/skills/bb2-brain-ingest/SKILL.md"
    _write(managed, b"managed-v1\n")
    manifest = repo / ".project-brain-manifest.json"
    _write(
        manifest,
        canonical_receipt_bytes({"files": {managed.relative_to(repo).as_posix(): _sha(managed.read_bytes())}}),
    )
    _write(
        repo / ".project-brain.json",
        canonical_receipt_bytes({
            "project": "bb2",
            "brain_root": "brain",
            "default_branch": "develop",
            "repo": "bb2_client",
        }),
    )
    _write(repo / ".gitignore", b".snapshots/\nbrain/.brain-local/\n")
    user_dirt = repo / "user-note.txt"
    _write(user_dirt, b"clean\n")
    _commit(repo, "bb2")
    _write(user_dirt, b"dirty-before-baseline\n")

    index_db = brain / ".brain-local/index.db"
    index_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(index_db) as conn:
        conn.execute(
            "CREATE TABLE meta (schema_version INTEGER, embed_model TEXT, "
            "tokenizer TEXT, extractor_version TEXT, corpus_fingerprint TEXT)"
        )
        conn.execute("INSERT INTO meta VALUES (4, 'stub', 'stub', 'fixture', 'meta-fingerprint')")
    stale_set = brain / ".brain-local/stale-set.json"
    _write(stale_set, b'{"stale":[]}\n')
    snapshots_root = repo / ".snapshots"
    artifact_root = snapshots_root / "2026-08-05/p0-foundation"
    artifact_root.mkdir(parents=True)

    monkeypatch.setattr(
        foundation,
        "resolved_project_brain_file",
        lambda: engine / "src/project_brain/__init__.py",
    )
    monkeypatch.setattr(
        foundation,
        "resolved_cli_source_file",
        lambda: engine / "src/project_brain/cli.py",
    )
    return FoundationFixture(
        engine=engine,
        repo=repo,
        brain=brain,
        artifact_root=artifact_root,
        snapshots_root=snapshots_root,
        managed=managed,
        manifest=manifest,
        object_file=object_file,
        raw_file=raw_file,
        index_db=index_db,
        stale_set=stale_set,
        user_dirt=user_dirt,
    )


def _capture(fixture: FoundationFixture):
    return capture_foundation_baseline(**fixture.capture_args)


def test_tree_receipt_is_canonical_and_rejects_unsafe_inputs(tmp_path):
    root = (tmp_path / "root").resolve()
    root.mkdir()
    _write(root / "safe.json", b"{}\n")
    (root / "link.json").symlink_to(root / "safe.json")
    os.mkfifo(root / "pipe")

    receipt = capture_tree_receipt(root, ["safe.json"])
    assert receipt.root == str(root)
    assert receipt.entries[0].path == "safe.json"
    assert receipt.entries[0].entry_type == "regular"
    assert receipt.entries[0].sha256 == _sha(b"{}\n")

    for relative in ("", ".", "../outside", "/absolute"):
        with pytest.raises(FoundationError) as exc:
            capture_tree_receipt(root, [relative])
        assert exc.value.code == "tree_path_invalid"
    for relative, cause in [("link.json", "symlink_forbidden"), ("pipe", "source_type_invalid")]:
        with pytest.raises(FoundationError) as exc:
            capture_tree_receipt(root, [relative])
        assert exc.value.cause_code == cause


def test_baseline_has_exact_top_level_shape(foundation_fixture):
    baseline = _capture(foundation_fixture)

    assert set(baseline) == {
        "version",
        "purpose",
        "roots",
        "artifact_root",
        "artifact_inventory",
        "ignored_snapshots_inventory",
        "engine",
        "bb2",
        "corpus",
        "search_index",
        "runtime",
        "stale_set",
    }
    assert baseline["purpose"] == "p0-foundation-baseline"
    assert baseline["engine"]["core_paths"] == [
        "src/project_brain",
        "pyproject.toml",
        "uv.lock",
    ]
    assert baseline["engine"]["entrypoint"] == "project_brain.cli:main"
    assert baseline["engine"]["status_porcelain_v1_z_base64"] == ""
    assert baseline["bb2"]["status_porcelain_v1_z_base64"]


def test_baseline_verifier_rejects_boolean_version(foundation_fixture):
    baseline = _capture(foundation_fixture)
    baseline["version"] = True

    with pytest.raises(FoundationError) as exc:
        foundation_fixture.verify(baseline)

    assert exc.value.code == "baseline_invalid"


def test_baseline_rejects_engine_core_dirt(foundation_fixture):
    _write(foundation_fixture.engine / "src/project_brain/new_untracked.py", b"x=1\n")

    with pytest.raises(FoundationError) as exc:
        _capture(foundation_fixture)

    assert exc.value.code == "engine_core_dirty"


def test_baseline_rejects_import_from_another_checkout(foundation_fixture, monkeypatch):
    monkeypatch.setattr(
        foundation,
        "resolved_project_brain_file",
        lambda: Path("/tmp/other/project_brain/__init__.py"),
    )

    with pytest.raises(FoundationError) as exc:
        _capture(foundation_fixture)

    assert exc.value.code == "engine_checkout_mismatch"


def test_baseline_rejects_noncanonical_absolute_root(foundation_fixture):
    args = dict(foundation_fixture.capture_args)
    args["engine_root"] = foundation_fixture.engine / ".." / foundation_fixture.engine.name

    with pytest.raises(FoundationError) as exc:
        capture_foundation_baseline(**args)

    assert exc.value.code == "root_invalid"


def _mutate_object(fixture):
    _write(fixture.object_file, b'{"id":"domain.changed","kind":"DomainContext"}\n')


def _mutate_raw(fixture):
    _write(fixture.raw_file, b"changed raw\n")


def _mutate_index(fixture):
    with fixture.index_db.open("ab") as stream:
        stream.write(b"changed")


def _mutate_user_dirt(fixture):
    _write(fixture.user_dirt, b"dirty-after-baseline\n")


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (_mutate_object, "objects_changed"),
        (_mutate_raw, "raw_changed"),
        (_mutate_index, "index_db_changed"),
        (_mutate_user_dirt, "user_dirt_changed"),
    ],
)
def test_foundation_verify_rejects_immutable_drift(
    foundation_fixture,
    mutator,
    code,
):
    baseline = _capture(foundation_fixture)
    mutator(foundation_fixture)

    report = foundation_fixture.verify(baseline)

    assert report["ok"] is False
    assert code in report["errors"]


def test_foundation_verify_allows_only_stale_set_local_mutation(foundation_fixture):
    baseline = _capture(foundation_fixture)
    _write(foundation_fixture.stale_set, b'{"stale":["domain.fixture"]}\n')

    report = foundation_fixture.verify(baseline)

    assert report["ok"] is True, report
    assert report["observed_changes"]["expected_local_mutation"] == [
        "brain/.brain-local/stale-set.json"
    ]


def test_allowed_bb2_head_change_is_derived_from_manifest_delta(foundation_fixture):
    baseline = _capture(foundation_fixture)
    _write(foundation_fixture.managed, b"managed-v2\n")
    _write(
        foundation_fixture.manifest,
        canonical_receipt_bytes({
            "files": {
                foundation_fixture.managed.relative_to(foundation_fixture.repo).as_posix():
                    _sha(foundation_fixture.managed.read_bytes()),
            }
        }),
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(foundation_fixture.repo),
            "add",
            foundation_fixture.managed.relative_to(foundation_fixture.repo).as_posix(),
            foundation_fixture.manifest.name,
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(foundation_fixture.repo), "commit", "-q", "-m", "install"],
        check=True,
    )

    report = foundation_fixture.verify(
        baseline,
        allowed_managed_paths=[
            foundation_fixture.managed.relative_to(foundation_fixture.repo).as_posix()
        ],
        allowed_installer_control_paths=[foundation_fixture.manifest.name],
    )

    assert report["ok"] is True, report
    assert set(report["observed_changes"]["bb2_commit_paths"]) == set(
        report["allowed_changes"]["managed_runtime_paths"]
        + report["allowed_changes"]["installer_control_paths"]
    )
    assert report["allowed_changes"]["installer_control_paths"] == [
        ".project-brain-manifest.json"
    ]


def test_receipt_excludes_only_exact_declared_artifact_paths(foundation_fixture):
    baseline = _capture(foundation_fixture)
    receipt = foundation_fixture.artifact_root / "baseline.json"
    _write(receipt, b"{}\n")
    _write(foundation_fixture.artifact_root / "undeclared.json", b"{}\n")

    report = foundation_fixture.verify(
        baseline,
        allowed_artifact_files=[receipt],
    )

    assert report["ok"] is False
    assert "unexpected_dirt_path" in report["errors"]


def test_foundation_rejects_ignored_snapshot_drift_outside_artifact_root(
    foundation_fixture,
):
    baseline = _capture(foundation_fixture)
    _write(foundation_fixture.snapshots_root / "2026-08-04/extra.json", b"{}\n")

    report = foundation_fixture.verify(baseline)

    assert report["ok"] is False
    assert "ignored_snapshots_changed" in report["errors"]


def test_foundation_rejects_artifact_and_ignored_root_substitution(
    foundation_fixture,
    tmp_path,
):
    baseline = _capture(foundation_fixture)
    other_snapshots = (tmp_path / "other-snapshots").resolve()
    other_artifact = other_snapshots / "2026-08-05/p0-foundation"
    other_artifact.mkdir(parents=True)

    report = foundation_fixture.verify(
        baseline,
        artifact_root=other_artifact,
        ignored_snapshots_root=other_snapshots,
    )

    assert report["ok"] is False
    assert "artifact_root_mismatch" in report["errors"]
    assert "ignored_snapshots_root_mismatch" in report["errors"]


def test_corrupt_index_bytes_still_report_index_db_changed(foundation_fixture):
    baseline = _capture(foundation_fixture)
    _write(foundation_fixture.index_db, b"not-a-sqlite-database\n")

    report = foundation_fixture.verify(baseline)

    assert report["ok"] is False
    assert "index_db_changed" in report["errors"]


@pytest.mark.parametrize("entry_kind", ["file", "symlink", "fifo"])
def test_artifact_inventory_rejects_unlisted_or_special_entry(
    foundation_fixture,
    entry_kind,
):
    entry = foundation_fixture.artifact_root / "unexpected"
    if entry_kind == "file":
        _write(entry, b"unexpected\n")
    elif entry_kind == "symlink":
        entry.symlink_to(foundation_fixture.user_dirt)
    else:
        os.mkfifo(entry)

    with pytest.raises(FoundationError) as exc:
        verify_artifact_inventory(
            foundation_fixture.artifact_root,
            allowed_files=(),
        )

    assert exc.value.code == "artifact_inventory_invalid"


def test_artifact_inventory_allows_only_manifest_verified_snapshot_subtree(
    foundation_fixture,
):
    result = create_snapshot(
        SnapshotRequest(
            brain_root=foundation_fixture.brain,
            repo_root=foundation_fixture.repo,
            engine_root=foundation_fixture.engine,
            output_root=foundation_fixture.artifact_root,
            snapshot_id="verified-snapshot",
        )
    )

    receipt = verify_artifact_inventory(
        foundation_fixture.artifact_root,
        allowed_files=(),
        verified_snapshot_root=result.snapshot_root,
    )

    assert receipt.entries
    assert any(entry.path == "verified-snapshot/manifest.json" for entry in receipt.entries)


@pytest.mark.parametrize("mutation_point", ["after_verify", "before_final_scan"])
def test_artifact_inventory_binds_verified_snapshot_before_and_after_scan(
    foundation_fixture,
    monkeypatch,
    mutation_point,
):
    result = create_snapshot(
        SnapshotRequest(
            brain_root=foundation_fixture.brain,
            repo_root=foundation_fixture.repo,
            engine_root=foundation_fixture.engine,
            output_root=foundation_fixture.artifact_root,
            snapshot_id="verified-snapshot",
        )
    )
    rogue = result.snapshot_root / "rogue.json"
    if mutation_point == "after_verify":
        original_verify = foundation.snapshot.verify_snapshot

        def verify_then_mutate(*args, **kwargs):
            verification = original_verify(*args, **kwargs)
            _write(rogue, b"{}\n")
            return verification

        monkeypatch.setattr(
            foundation.snapshot,
            "verify_snapshot",
            verify_then_mutate,
        )
    else:
        monkeypatch.setattr(
            foundation,
            "_after_verified_snapshot_receipt_hook",
            lambda: _write(rogue, b"{}\n"),
            raising=False,
        )

    with pytest.raises(FoundationError) as exc:
        verify_artifact_inventory(
            foundation_fixture.artifact_root,
            allowed_files=(),
            verified_snapshot_root=result.snapshot_root,
        )

    assert exc.value.code == "artifact_inventory_invalid"


def test_baseline_records_absent_artifact_root_without_creating_it(
    foundation_fixture,
):
    foundation_fixture.artifact_root.rmdir()
    foundation_fixture.artifact_root.parent.rmdir()

    baseline = _capture(foundation_fixture)

    assert baseline["artifact_inventory"] == {
        "root": str(foundation_fixture.artifact_root),
        "entries": [],
        "sha256": hashlib.sha256(b'{"entries":[]}\n').hexdigest(),
    }
    assert not foundation_fixture.artifact_root.exists()
    assert not foundation_fixture.artifact_root.parent.exists()


def test_artifact_only_parent_does_not_change_ignored_snapshot_inventory(
    foundation_fixture,
):
    foundation_fixture.artifact_root.rmdir()
    foundation_fixture.artifact_root.parent.rmdir()
    baseline = _capture(foundation_fixture)

    receipt = foundation_fixture.artifact_root / "foundation-baseline.json"
    _write(receipt, b"{}\n")

    report = foundation_fixture.verify(
        baseline,
        allowed_artifact_files=[receipt],
    )
    state = foundation.capture_foundation_state(
        engine_root=foundation_fixture.engine,
        repo_root=foundation_fixture.repo,
        brain_root=foundation_fixture.brain,
        artifact_root=foundation_fixture.artifact_root,
        ignored_snapshots_root=foundation_fixture.snapshots_root,
        protected_artifact_files=[receipt],
    )

    assert report["ok"] is True, report
    assert (
        state["ignored_snapshots_inventory"]
        == baseline["ignored_snapshots_inventory"]
    )

    _write(foundation_fixture.artifact_root.parent / "sibling.json", b"{}\n")

    drift = foundation_fixture.verify(
        baseline,
        allowed_artifact_files=[receipt],
    )

    assert drift["ok"] is False
    assert "ignored_snapshots_changed" in drift["errors"]


def _receipt_fixture(*, purpose="p0-foundation-baseline"):
    if purpose == "p0-foundation-gate":
        return {
            "version": 1,
            "purpose": purpose,
            "heads": {"engine": "a" * 40, "bb2_after": "b" * 40},
        }
    return {
        "version": 1,
        "purpose": purpose,
        "engine": {"head": "a" * 40},
        "bb2": {"head": "b" * 40},
    }


def test_canonical_receipt_bytes_is_strict_and_has_one_final_lf():
    assert canonical_receipt_bytes({"b": 2, "a": "한글"}) == (
        '{"a":"한글","b":2}\n'.encode()
    )
    for value in ({"bad": float("nan")}, {"bad": object()}):
        with pytest.raises(FoundationError) as exc:
            canonical_receipt_bytes(value)
        assert exc.value.code == "receipt_json_invalid"


def test_atomic_create_receipt_refuses_existing_and_symlink_without_data_loss(tmp_path):
    path = (tmp_path / "receipt.json").resolve()
    _write(path, b"existing\n")
    with pytest.raises(FoundationError) as exc:
        atomic_create_receipt(path, _receipt_fixture())
    assert exc.value.code == "receipt_exists"
    assert path.read_bytes() == b"existing\n"

    path.unlink()
    outside = tmp_path / "outside.json"
    _write(outside, b"outside\n")
    path.symlink_to(outside)
    with pytest.raises(FoundationError) as exc:
        atomic_create_receipt(path, _receipt_fixture())
    assert exc.value.code == "receipt_symlink"
    assert path.is_symlink()
    assert outside.read_bytes() == b"outside\n"


def test_atomic_create_bound_receipt_rolls_back_owned_first_file_on_second_race(
    tmp_path,
    monkeypatch,
):
    receipt = (tmp_path / "receipt.json").resolve()
    binding = (tmp_path / "binding.json").resolve()

    def occupy_binding():
        _write(binding, b"preexisting-racer\n")

    monkeypatch.setattr(foundation, "_before_binding_create_hook", occupy_binding)

    with pytest.raises(FoundationError) as exc:
        atomic_create_bound_receipt(
            receipt_path=receipt,
            binding_path=binding,
            value=_receipt_fixture(),
        )

    assert exc.value.code == "binding_create_failed"
    assert not receipt.exists()
    assert binding.read_bytes() == b"preexisting-racer\n"


def test_atomic_create_receipt_removes_partial_file_on_raw_write_failure(
    tmp_path,
    monkeypatch,
):
    receipt = (tmp_path / "receipt.json").resolve()

    def fail_write(_descriptor, _data):
        raise OSError("injected write failure")

    monkeypatch.setattr(foundation.os, "write", fail_write)

    with pytest.raises(FoundationError) as exc:
        atomic_create_receipt(receipt, _receipt_fixture())

    assert exc.value.code == "receipt_create_failed"
    assert not receipt.exists()


def test_atomic_cleanup_never_deletes_competing_winner_between_stat_and_unlink(
    tmp_path,
    monkeypatch,
):
    receipt = (tmp_path / "receipt.json").resolve()
    original_stat = foundation.os.stat
    original_write = foundation.os.write
    raced = False

    def race_after_stat(name, *args, **kwargs):
        nonlocal raced
        current = original_stat(name, *args, **kwargs)
        if name == receipt.name and not raced:
            raced = True
            parent_fd = kwargs["dir_fd"]
            os.unlink(name, dir_fd=parent_fd)
            winner_fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
            try:
                original_write(winner_fd, b"winner\n")
            finally:
                os.close(winner_fd)
        return current

    monkeypatch.setattr(foundation.os, "stat", race_after_stat)
    monkeypatch.setattr(
        foundation.os,
        "write",
        lambda _descriptor, _data: (_ for _ in ()).throw(OSError("fail")),
    )

    with pytest.raises(FoundationError):
        atomic_create_receipt(receipt, _receipt_fixture())

    assert raced is True
    assert receipt.read_bytes() == b"winner\n"


def test_bound_second_raw_write_failure_rolls_back_both_owned_files(
    tmp_path,
    monkeypatch,
):
    receipt = (tmp_path / "receipt.json").resolve()
    binding = (tmp_path / "binding.json").resolve()
    original_write = foundation.os.write
    calls = 0

    def fail_second_write(descriptor, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected binding write failure")
        return original_write(descriptor, data)

    monkeypatch.setattr(foundation.os, "write", fail_second_write)

    with pytest.raises(FoundationError) as exc:
        atomic_create_bound_receipt(
            receipt_path=receipt,
            binding_path=binding,
            value=_receipt_fixture(),
        )

    assert exc.value.code == "binding_create_failed"
    assert not receipt.exists()
    assert not binding.exists()


@pytest.mark.parametrize(
    "tamper",
    ["receipt_sha256", "receipt_path", "purpose", "engine_head", "bb2_head"],
)
def test_verify_bound_receipt_rejects_tamper_path_purpose_sha_or_head(
    tmp_path,
    tamper,
):
    receipt = (tmp_path / "receipt.json").resolve()
    binding = (tmp_path / "binding.json").resolve()
    atomic_create_bound_receipt(
        receipt_path=receipt,
        binding_path=binding,
        value=_receipt_fixture(),
    )
    if tamper == "receipt_sha256":
        receipt.write_bytes(receipt.read_bytes() + b" ")
    else:
        value = json.loads(binding.read_bytes())
        value[tamper] = {
            "receipt_path": str(tmp_path / "other.json"),
            "purpose": "p0-foundation-gate-binding",
            "engine_head": "c" * 40,
            "bb2_head": "d" * 40,
        }[tamper]
        binding.write_bytes(canonical_receipt_bytes(value))

    with pytest.raises(FoundationError) as exc:
        verify_bound_receipt(
            receipt_path=receipt,
            binding_path=binding,
            expected_purpose="p0-foundation-baseline-binding",
        )

    assert tamper in exc.value.detail


def test_gate_binding_uses_only_gate_head_fields(tmp_path):
    receipt = (tmp_path / "gate.json").resolve()
    binding = (tmp_path / "gate-binding.json").resolve()
    value = _receipt_fixture(purpose="p0-foundation-gate")
    value["engine"] = {"head": "c" * 40}
    value["bb2"] = {"head": "d" * 40}

    atomic_create_bound_receipt(
        receipt_path=receipt,
        binding_path=binding,
        value=value,
    )

    bound = json.loads(binding.read_bytes())
    assert bound["purpose"] == "p0-foundation-gate-binding"
    assert bound["engine_head"] == "a" * 40
    assert bound["bb2_head"] == "b" * 40
    assert verify_bound_receipt(
        receipt_path=receipt,
        binding_path=binding,
        expected_purpose="p0-foundation-gate-binding",
    ) == value


def test_bound_receipt_creator_and_verifier_reject_boolean_version(tmp_path):
    receipt = (tmp_path / "receipt.json").resolve()
    binding = (tmp_path / "binding.json").resolve()
    invalid = _receipt_fixture()
    invalid["version"] = True

    with pytest.raises(FoundationError) as exc:
        atomic_create_bound_receipt(
            receipt_path=receipt,
            binding_path=binding,
            value=invalid,
        )
    assert exc.value.code == "binding_version_invalid"
    assert not receipt.exists()
    assert not binding.exists()

    atomic_create_bound_receipt(
        receipt_path=receipt,
        binding_path=binding,
        value=_receipt_fixture(),
    )
    bound = json.loads(binding.read_bytes())
    bound["version"] = True
    binding.write_bytes(canonical_receipt_bytes(bound))

    with pytest.raises(FoundationError) as exc:
        verify_bound_receipt(
            receipt_path=receipt,
            binding_path=binding,
            expected_purpose="p0-foundation-baseline-binding",
        )
    assert exc.value.code == "binding_invalid"


def test_bound_receipt_closes_first_parent_if_second_parent_validation_fails(
    tmp_path,
    monkeypatch,
):
    receipt = (tmp_path / "receipt.json").resolve()
    outside = tmp_path / "outside"
    outside.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    binding = linked_parent / "binding.json"
    opened: list[int] = []
    original_open = foundation.snapshot._open_absolute_directory

    def capture_open(path, *, create):
        descriptor = original_open(path, create=create)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(
        foundation.snapshot,
        "_open_absolute_directory",
        capture_open,
    )

    with pytest.raises(FoundationError):
        atomic_create_bound_receipt(
            receipt_path=receipt,
            binding_path=binding,
            value=_receipt_fixture(),
        )

    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])


def _installer_gate_report(root: Path) -> dict[str, object]:
    managed = ".agents/skills/bb2-brain-ingest/scripts/validate_foundation.py"
    return {
        "ok": True,
        "target_root": str(root),
        "config": "kept",
        "created": [managed],
        "updated": [],
        "removed": [],
        "adopted": [],
        "skipped": [],
        "installer_control_paths": [".project-brain-manifest.json"],
    }


def test_task15_stage_paths_are_exactly_managed_changes_plus_manifest(tmp_path):
    root = (tmp_path / "bb2").resolve()
    root.mkdir()
    report = _installer_gate_report(root)
    assert task15_stage_paths(report) == [
        ".agents/skills/bb2-brain-ingest/scripts/validate_foundation.py",
        ".project-brain-manifest.json",
    ]

    report["created"] = [".agents/skills/bb2-brain-unlisted/SKILL.md"]
    with pytest.raises(FoundationError, match="managed runtime path"):
        task15_stage_paths(report)

    assert BB2_MANAGED_SKILL_ROOTS == (
        ".agents/skills/bb2-brain-query/",
        ".agents/skills/bb2-brain-ingest/",
        ".agents/skills/bb2-brain-session-ingest/",
        ".agents/skills/bb2-brain-audit/",
    )


def test_task15_cached_paths_must_be_nonempty_subset_without_preexisting_paths(tmp_path):
    root = (tmp_path / "bb2").resolve()
    root.mkdir()
    allowed = task15_stage_paths(_installer_gate_report(root))
    with pytest.raises(FoundationError, match="preexisting cached"):
        validate_task15_cached_paths(
            preexisting_cached_paths=["user-owned.txt"],
            cached_paths=allowed[:1],
            allowed_paths=allowed,
        )
    with pytest.raises(FoundationError, match="empty cached"):
        validate_task15_cached_paths(
            preexisting_cached_paths=[],
            cached_paths=[],
            allowed_paths=allowed,
        )
    with pytest.raises(FoundationError, match="cached path"):
        validate_task15_cached_paths(
            preexisting_cached_paths=[],
            cached_paths=["brain/objects/user-owned.json"],
            allowed_paths=allowed,
        )
    validate_task15_cached_paths(
        preexisting_cached_paths=[],
        cached_paths=allowed[:1],
        allowed_paths=allowed,
    )


def test_foundation_command_set_has_exact_order_and_forbids_mutating_commands(tmp_path):
    engine = (tmp_path / "engine").resolve()
    repo = (tmp_path / "bb2").resolve()
    brain = repo / "brain"
    runtime = repo / ".agents/skills/bb2-brain-ingest/scripts/validate_foundation.py"
    smoke = (tmp_path / "smoke").resolve()
    rows = foundation_command_specs(
        engine_root=engine,
        repo_root=repo,
        brain_root=brain,
        installed_runtime=runtime,
        smoke_root=smoke,
        python_executable=Path(sys.executable),
    )
    assert [row.id for row in rows] == [
        "installed-runtime-unittest",
        "bb2-checks",
        "lint",
        "audit-no-fetch",
        "eval",
        "coverage-build-dry-smoke",
    ]
    assert rows[0].argv == (
        str(Path(sys.executable)),
        "-m",
        "unittest",
        "src.project_brain.templates.ingest.scripts.test_validate_foundation",
    )
    assert rows[1].argv[-4:] == ("-s", "brain/checks", "-p", "test_*.py")
    assert rows[2].argv[-3:] == ("lint", "--brain-root", str(brain))
    assert rows[3].argv[-6:] == (
        "audit", "--brain-root", str(brain), "--repo-root", str(repo), "--no-fetch"
    )
    assert rows[4].argv[-3:] == ("eval", "--brain-root", str(brain))
    rendered = "\n".join(" ".join(row.argv) for row in rows)
    assert "finalize_ingest" not in rendered
    assert "index rebuild" not in rendered


def test_coverage_build_smoke_writes_only_to_temporary_root(
    tmp_path,
    foundation_fixture,
):
    engine_root = Path(__file__).resolve().parents[1]
    installed_runtime = (
        engine_root
        / "src/project_brain/templates/ingest/scripts/validate_foundation.py"
    )
    smoke_root = (tmp_path / "coverage-smoke").resolve()
    protected = {
        path: path.read_bytes()
        for path in (
            foundation_fixture.object_file,
            foundation_fixture.raw_file,
            foundation_fixture.index_db,
        )
    }

    foundation.prepare_coverage_smoke(
        installed_runtime=installed_runtime,
        smoke_root=smoke_root,
    )
    command = foundation_command_specs(
        engine_root=engine_root,
        repo_root=foundation_fixture.repo,
        brain_root=foundation_fixture.brain,
        installed_runtime=installed_runtime,
        smoke_root=smoke_root,
        python_executable=Path(sys.executable),
    )[-1]

    row = foundation._command_row(command)

    assert row["ok"] is True, row["stderr"]
    assert (smoke_root / "objects.json").is_file()
    assert json.loads((smoke_root / "objects.json").read_text(encoding="utf-8"))
    assert {path: path.read_bytes() for path in protected} == protected


@dataclass
class GateFixture:
    base: FoundationFixture
    baseline_path: Path
    baseline_binding_path: Path
    install_one_path: Path
    install_two_path: Path
    installed_runtime: Path
    managed_changes: list[str]


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    _write(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _successful_command_row(spec) -> dict[str, object]:
    return {
        "id": spec.id,
        "argv": list(spec.argv),
        "cwd": spec.cwd,
        "exit_code": 0,
        "stdout": "ok\n",
        "stdout_sha256": _sha(b"ok\n"),
        "stderr": "",
        "stderr_sha256": _sha(b""),
        "ok": True,
    }


@pytest.fixture
def gate_fixture(foundation_fixture, monkeypatch) -> GateFixture:
    base = foundation_fixture
    baseline = _capture(base)
    baseline_path = base.artifact_root / "foundation-baseline.json"
    baseline_binding_path = base.artifact_root / "foundation-baseline.binding.json"
    atomic_create_bound_receipt(
        receipt_path=baseline_path,
        binding_path=baseline_binding_path,
        value=baseline,
    )

    skill = base.repo / ".agents/skills/bb2-brain-ingest"
    installed_runtime = skill / "scripts/validate_foundation.py"
    source_templates = (
        Path(__file__).resolve().parents[1]
        / "src/project_brain/templates/ingest/references/object-templates"
    )
    installed_templates = skill / "references/object-templates"
    sources = {
        installed_runtime: (
            Path(__file__).resolve().parents[1]
            / "src/project_brain/templates/ingest/scripts/validate_foundation.py"
        ),
        installed_templates / "build-notes.complete.template.json": (
            source_templates / "build-notes.complete.template.json"
        ),
        installed_templates / "build-coverage.complete.template.json": (
            source_templates / "build-coverage.complete.template.json"
        ),
        installed_templates / "object-graph.complete.template.json": (
            source_templates / "object-graph.complete.template.json"
        ),
    }
    for destination, source in sources.items():
        _write(destination, source.read_bytes())
    installed_runtime.chmod(0o755)
    managed_changes = sorted(path.relative_to(base.repo).as_posix() for path in sources)
    manifest = json.loads(base.manifest.read_text(encoding="utf-8"))
    for path in sources:
        relative = path.relative_to(base.repo).as_posix()
        manifest["files"][relative] = _sha(path.read_bytes())
    _write(base.manifest, canonical_receipt_bytes(manifest))
    subprocess.run(
        ["git", "-C", str(base.repo), "add", "--", *managed_changes, base.manifest.name],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(base.repo), "commit", "-q", "-m", "runtime install"],
        check=True,
    )

    install_one_path = base.artifact_root / "install-1.json"
    install_two_path = base.artifact_root / "install-2.json"
    first = {
        "ok": True,
        "target_root": str(base.repo),
        "config": "kept",
        "created": managed_changes,
        "updated": [],
        "removed": [],
        "adopted": [],
        "skipped": [],
        "installer_control_paths": [".project-brain-manifest.json"],
    }
    second = {
        **first,
        "created": [],
    }
    _write_json(install_one_path, first)
    _write_json(install_two_path, second)
    monkeypatch.setattr(foundation, "_command_row", _successful_command_row)
    return GateFixture(
        base=base,
        baseline_path=baseline_path,
        baseline_binding_path=baseline_binding_path,
        install_one_path=install_one_path,
        install_two_path=install_two_path,
        installed_runtime=installed_runtime,
        managed_changes=managed_changes,
    )


def _run_gate(fixture: GateFixture) -> dict[str, object]:
    base = fixture.base
    return run_foundation_gate(
        engine_root=base.engine,
        repo_root=base.repo,
        brain_root=base.brain,
        artifact_root=base.artifact_root,
        baseline_path=fixture.baseline_path,
        baseline_binding_path=fixture.baseline_binding_path,
        install_report_1_path=fixture.install_one_path,
        install_report_2_path=fixture.install_two_path,
        installed_runtime=fixture.installed_runtime,
        python_executable=Path(sys.executable),
    )


def test_gate_records_exact_six_commands_and_nonzero_result(gate_fixture, monkeypatch):
    def fail_lint(spec):
        row = _successful_command_row(spec)
        if spec.id == "lint":
            row.update({
                "exit_code": 1,
                "stderr": "lint failed\n",
                "stderr_sha256": _sha(b"lint failed\n"),
                "ok": False,
            })
        return row

    monkeypatch.setattr(foundation, "_command_row", fail_lint)
    report = _run_gate(gate_fixture)
    assert report["ok"] is False
    assert [row["id"] for row in report["commands"]] == [
        "installed-runtime-unittest",
        "bb2-checks",
        "lint",
        "audit-no-fetch",
        "eval",
        "coverage-build-dry-smoke",
    ]
    assert next(row for row in report["commands"] if row["id"] == "lint")["ok"] is False
    assert set(report["allowed_changes"]) == {
        "managed_runtime_paths",
        "installer_control_paths",
        "expected_local_mutation_paths",
    }


def test_gate_rejects_tampered_baseline_without_rebinding(gate_fixture):
    gate_fixture.baseline_path.write_bytes(gate_fixture.baseline_path.read_bytes() + b" ")
    with pytest.raises(FoundationError) as exc:
        _run_gate(gate_fixture)
    assert exc.value.code == "baseline_sha256_mismatch"


def test_gate_checks_invariants_after_each_command(gate_fixture, monkeypatch):
    def mutate_after_lint(spec):
        row = _successful_command_row(spec)
        if spec.id == "lint":
            gate_fixture.base.object_file.write_bytes(
                gate_fixture.base.object_file.read_bytes() + b" "
            )
        return row

    monkeypatch.setattr(foundation, "_command_row", mutate_after_lint)
    with pytest.raises(FoundationError) as exc:
        _run_gate(gate_fixture)
    assert exc.value.code == "objects_changed"


def test_gate_semantic_validator_rejects_each_forged_contract(gate_fixture):
    gate = _run_gate(gate_fixture)
    baseline = json.loads(gate_fixture.baseline_path.read_text(encoding="utf-8"))
    binding = json.loads(
        gate_fixture.baseline_binding_path.read_text(encoding="utf-8")
    )
    first_raw = json.loads(gate_fixture.install_one_path.read_text(encoding="utf-8"))
    second_raw = json.loads(gate_fixture.install_two_path.read_text(encoding="utf-8"))
    first, second, allowed_managed = foundation.validate_foundation_install_reports(
        first_raw,
        second_raw,
        repo_root=gate_fixture.base.repo,
    )
    mutations = {
        "command_argv": lambda value: value["commands"][0].update({
            "argv": ["/tmp/not-engine-python", "-c", "print(1)"],
        }),
        "command_cwd": lambda value: value["commands"][0].update({
            "cwd": "/tmp",
        }),
        "stdout_sha": lambda value: value["commands"][0].update({
            "stdout_sha256": "0" * 64,
        }),
        "stderr_sha": lambda value: value["commands"][0].update({
            "stderr_sha256": "0" * 64,
        }),
        "heads": lambda value: value["heads"].update({"engine": "0" * 40}),
        "install": lambda value: value["install"]["first"].update({"config": "created"}),
        "allowed": lambda value: value["allowed_changes"].update({
            "expected_local_mutation_paths": [],
        }),
        "observed": lambda value: value["observed_changes"].update({
            "bb2_commit_paths": [],
        }),
        "state": lambda value: value.update({"before": {}}),
    }
    accepted = []

    for label, mutate in mutations.items():
        forged = copy.deepcopy(gate)
        mutate(forged)
        try:
            foundation._validate_gate_receipt(
                forged,
                baseline=baseline,
                baseline_path=gate_fixture.baseline_path,
                baseline_sha=binding["receipt_sha256"],
                engine_root=gate_fixture.base.engine,
                repo_root=gate_fixture.base.repo,
                brain_root=gate_fixture.base.brain,
                installed_runtime=gate_fixture.installed_runtime,
                python_executable=Path(sys.executable),
                install_first=first,
                install_second=second,
                allowed_managed=allowed_managed,
            )
        except FoundationError:
            continue
        accepted.append(label)

    assert accepted == []


def test_gate_rejects_stale_change_after_last_command_post(
    gate_fixture,
    monkeypatch,
):
    original = foundation.capture_foundation_state
    calls = 0

    def mutate_before_final_capture(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 14:
            gate_fixture.base.stale_set.write_bytes(b'{"stale":["not-from-audit"]}\n')
        return original(**kwargs)

    monkeypatch.setattr(
        foundation,
        "capture_foundation_state",
        mutate_before_final_capture,
    )

    with pytest.raises(FoundationError) as exc:
        _run_gate(gate_fixture)

    assert exc.value.code == "stale_set_changed"


@dataclass
class HandoffFixture:
    gate: GateFixture
    gate_path: Path
    gate_binding_path: Path
    snapshot_root: Path
    snapshot_create_path: Path
    snapshot_verify_path: Path
    output: Path


@pytest.fixture
def handoff_fixture(gate_fixture) -> HandoffFixture:
    gate = _run_gate(gate_fixture)
    assert gate["ok"] is True
    base = gate_fixture.base
    gate_path = base.artifact_root / "foundation-gate.json"
    gate_binding_path = base.artifact_root / "foundation-gate.binding.json"
    atomic_create_bound_receipt(
        receipt_path=gate_path,
        binding_path=gate_binding_path,
        value=gate,
    )
    result = create_snapshot(SnapshotRequest(
        brain_root=base.brain,
        repo_root=base.repo,
        engine_root=base.engine,
        output_root=base.artifact_root,
        snapshot_id="p0-foundation-corpus",
    ))
    verification = verify_snapshot(
        result.snapshot_root,
        expected_manifest_sha256=result.manifest_sha256,
    )
    snapshot_create_path = base.artifact_root / "snapshot-create.json"
    snapshot_verify_path = base.artifact_root / "snapshot-verify.json"
    _write_json(snapshot_create_path, {
        "ok": True,
        "snapshot_id": result.snapshot_id,
        "snapshot_root": str(result.snapshot_root),
        "manifest_path": str(result.manifest_path),
        "manifest_sha256": result.manifest_sha256,
        "file_count": result.file_count,
        "restore_scope": "brain_only",
    })
    _write_json(snapshot_verify_path, {
        "ok": verification.ok,
        "snapshot_id": verification.snapshot_id,
        "manifest_sha256": verification.manifest_sha256,
        "file_count": verification.file_count,
    })
    return HandoffFixture(
        gate=gate_fixture,
        gate_path=gate_path,
        gate_binding_path=gate_binding_path,
        snapshot_root=result.snapshot_root,
        snapshot_create_path=snapshot_create_path,
        snapshot_verify_path=snapshot_verify_path,
        output=base.artifact_root / "p0-handoff.json",
    )


def _build_handoff(fixture: HandoffFixture) -> dict[str, object]:
    base = fixture.gate.base
    return build_foundation_handoff(
        engine_root=base.engine,
        repo_root=base.repo,
        brain_root=base.brain,
        artifact_root=base.artifact_root,
        baseline_path=fixture.gate.baseline_path,
        baseline_binding_path=fixture.gate.baseline_binding_path,
        gate_path=fixture.gate_path,
        gate_binding_path=fixture.gate_binding_path,
        snapshot_root=fixture.snapshot_root,
        snapshot_create_receipt_path=fixture.snapshot_create_path,
        snapshot_verify_receipt_path=fixture.snapshot_verify_path,
        output_path=fixture.output,
    )


def test_handoff_rechecks_state_and_publishes_canonical_receipt(handoff_fixture):
    receipt = _build_handoff(handoff_fixture)
    assert receipt["ok"] is True
    assert receipt["snapshot"]["ok"] is True
    assert receipt["task18_status"] == "blocked_pending_new_measurement_design_binding"
    assert receipt["final_recheck"]["first"] == receipt["final_recheck"]["second"]
    assert handoff_fixture.output.read_bytes() == canonical_receipt_bytes(receipt)


def test_handoff_rejects_gate_tamper_without_rebinding(handoff_fixture):
    handoff_fixture.gate_path.write_bytes(handoff_fixture.gate_path.read_bytes() + b" ")
    with pytest.raises(FoundationError) as exc:
        _build_handoff(handoff_fixture)
    assert exc.value.code == "gate_sha256_mismatch"
    assert not handoff_fixture.output.exists()


def test_handoff_rejects_post_write_allowed_artifact_metadata_tamper(
    handoff_fixture,
    monkeypatch,
):
    targets = (
        handoff_fixture.gate_path,
        handoff_fixture.gate_binding_path,
        handoff_fixture.gate.install_one_path,
        handoff_fixture.snapshot_verify_path,
    )
    for target in targets:
        before = target.read_bytes()
        monkeypatch.setattr(
            foundation,
            "_after_handoff_write_hook",
            lambda target=target, before=before: target.write_bytes(before + b" "),
        )

        with pytest.raises(FoundationError) as exc:
            _build_handoff(handoff_fixture)

        assert exc.value.code == "artifact_inventory_changed"
        assert not handoff_fixture.output.exists()
        assert target.read_bytes() == before + b" "
        target.write_bytes(before)


def test_handoff_rejects_pre_publish_allowed_artifact_metadata_tamper(
    handoff_fixture,
    monkeypatch,
):
    binding = handoff_fixture.gate_binding_path
    before = binding.read_bytes()
    monkeypatch.setattr(
        foundation,
        "_before_handoff_publish_hook",
        lambda: binding.write_bytes(before + b" "),
    )

    with pytest.raises(FoundationError) as exc:
        _build_handoff(handoff_fixture)

    assert exc.value.code == "artifact_inventory_changed"
    assert not handoff_fixture.output.exists()
    assert binding.read_bytes() == before + b" "


def test_handoff_rejects_snapshot_receipts_forged_consistently(
    handoff_fixture,
):
    create = json.loads(handoff_fixture.snapshot_create_path.read_text(encoding="utf-8"))
    verify = json.loads(handoff_fixture.snapshot_verify_path.read_text(encoding="utf-8"))
    create.update({"snapshot_id": "forged-snapshot", "file_count": 999999})
    verify.update({"snapshot_id": "forged-snapshot", "file_count": 999999})
    _write_json(handoff_fixture.snapshot_create_path, create)
    _write_json(handoff_fixture.snapshot_verify_path, verify)

    with pytest.raises(FoundationError) as exc:
        _build_handoff(handoff_fixture)

    assert exc.value.code == "snapshot_verify_result_mismatch"
    assert not handoff_fixture.output.exists()


@pytest.mark.parametrize(
    ("path_getter", "expected_code"),
    [
        (lambda fixture: fixture.gate.base.engine / "pyproject.toml", "engine_core_changed"),
        (lambda fixture: fixture.gate.installed_runtime, "runtime_changed"),
    ],
)
def test_handoff_normalizes_capture_failures_to_drift_codes(
    handoff_fixture,
    path_getter,
    expected_code,
):
    path = path_getter(handoff_fixture)
    path.write_bytes(path.read_bytes() + b"tamper\n")

    with pytest.raises(FoundationError) as exc:
        _build_handoff(handoff_fixture)

    assert exc.value.code == expected_code
    assert not handoff_fixture.output.exists()


def test_handoff_detects_snapshot_tamper_after_write_and_removes_owned_output(
    handoff_fixture,
    monkeypatch,
):
    payload_file = next(
        path for path in handoff_fixture.snapshot_root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    monkeypatch.setattr(
        foundation,
        "_after_handoff_write_hook",
        lambda: payload_file.write_bytes(payload_file.read_bytes() + b"tamper"),
    )
    with pytest.raises(FoundationError, match="snapshot"):
        _build_handoff(handoff_fixture)
    assert not handoff_fixture.output.exists()


def test_handoff_does_not_delete_competitor_replacement(handoff_fixture, monkeypatch):
    def replace_output():
        handoff_fixture.output.unlink()
        handoff_fixture.output.write_bytes(b"competitor\n")

    monkeypatch.setattr(foundation, "_after_handoff_write_hook", replace_output)
    with pytest.raises(FoundationError, match="handoff"):
        _build_handoff(handoff_fixture)
    assert handoff_fixture.output.read_bytes() == b"competitor\n"


def test_handoff_preserves_unexpected_sibling_when_owned_output_is_removed(
    handoff_fixture,
    monkeypatch,
):
    sibling = handoff_fixture.gate.base.artifact_root / "unexpected-user-file.json"
    monkeypatch.setattr(
        foundation,
        "_after_handoff_write_hook",
        lambda: sibling.write_bytes(b"{}\n"),
    )
    with pytest.raises(FoundationError, match="artifact inventory"):
        _build_handoff(handoff_fixture)
    assert not handoff_fixture.output.exists()
    assert sibling.read_bytes() == b"{}\n"


def test_handoff_reruns_snapshot_verifier_exactly_once(handoff_fixture, monkeypatch):
    calls = []
    original = foundation.snapshot.verify_snapshot

    def counted(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(foundation.snapshot, "verify_snapshot", counted)
    _build_handoff(handoff_fixture)
    assert len(calls) == 1


def test_handoff_detects_snapshot_race_between_post_scan_and_inventory(
    handoff_fixture,
    monkeypatch,
):
    payload_file = next(
        path for path in handoff_fixture.snapshot_root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    original = foundation.verify_artifact_inventory

    def race(artifact_root, *, allowed_files, verified_snapshot_root=None):
        if handoff_fixture.output in allowed_files:
            payload_file.write_bytes(payload_file.read_bytes() + b"raced")
        return original(
            artifact_root,
            allowed_files=allowed_files,
            verified_snapshot_root=verified_snapshot_root,
        )

    monkeypatch.setattr(foundation, "verify_artifact_inventory", race)
    with pytest.raises(FoundationError, match="snapshot"):
        _build_handoff(handoff_fixture)
    assert not handoff_fixture.output.exists()
