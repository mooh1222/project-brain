from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from project_brain import foundation
from project_brain.foundation import (
    FoundationError,
    atomic_create_bound_receipt,
    atomic_create_receipt,
    canonical_receipt_bytes,
    capture_foundation_baseline,
    capture_tree_receipt,
    verify_artifact_inventory,
    verify_bound_receipt,
    verify_foundation_invariants,
)
from project_brain.snapshot import SnapshotRequest, create_snapshot


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
    managed = repo / ".agents/skills/demo/SKILL.md"
    _write(managed, b"managed-v1\n")
    manifest = repo / ".project-brain-manifest.json"
    _write(
        manifest,
        canonical_receipt_bytes({"files": {managed.relative_to(repo).as_posix(): _sha(managed.read_bytes())}}),
    )
    _write(repo / ".project-brain.json", b'{"brain_root":"brain"}\n')
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
