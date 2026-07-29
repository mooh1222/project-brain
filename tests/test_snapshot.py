from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from project_brain import snapshot
from project_brain.snapshot import (
    SnapshotError,
    SnapshotRequest,
    create_snapshot,
    restore_snapshot,
    verify_snapshot,
)
from project_brain.store import BrainStore


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _git_commit(root: Path) -> str:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "snapshot@test.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Snapshot Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "--allow-empty", "-m", "fixture"],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _snapshot_fixture(
    tmp_path: Path,
    *,
    initialize_git: bool = True,
) -> tuple[SnapshotRequest, dict[str, Path]]:
    repo_root = tmp_path / "repo"
    brain_root = repo_root / "brain"
    engine_root = tmp_path / "engine"
    output_root = repo_root / ".snapshots"
    engine_root.mkdir()

    for kind, relative_directory in BrainStore._KIND_DIR.items():
        _write(
            brain_root / relative_directory / f"{kind}.json",
            json.dumps({"id": kind, "kind": kind}).encode("utf-8"),
        )
    source_a = brain_root / "raw" / "sources" / "a.md"
    source_b = brain_root / "raw" / "sources" / "nested" / "b.json"
    _write(source_a, b"source-a\n")
    _write(source_b, b'{"source":"b"}\n')
    for name in ("index.db", "index.db-wal", "index.db-shm"):
        _write(brain_root / ".brain-local" / name, name.encode("ascii"))
    _write(brain_root / ".brain-local" / "stale-set.json", b'{"stale":[]}\n')
    _write(brain_root / "eval_scenarios.json", b'{"scenarios":[]}\n')
    _write(repo_root / ".project-brain.json", b'{"brain_root":"brain"}\n')

    managed = repo_root / ".agents" / "skills" / "demo" / "SKILL.md"
    _write(managed, b"managed\n")
    _write(
        repo_root / ".project-brain-manifest.json",
        json.dumps({
            "files": {
                ".agents/skills/demo/SKILL.md": _sha256(managed),
            },
        }).encode("utf-8"),
    )
    if initialize_git:
        _git_commit(repo_root)
        _git_commit(engine_root)
    return (
        SnapshotRequest(
            brain_root=brain_root.resolve(),
            repo_root=repo_root.resolve(),
            engine_root=engine_root.resolve(),
            output_root=output_root.resolve(),
            snapshot_id="fixture-001",
        ),
        {
            "source_a": source_a,
            "object": (
                brain_root
                / BrainStore._KIND_DIR["DomainContext"]
                / "DomainContext.json"
            ),
            "managed": managed,
        },
    )


def test_create_snapshot_rejects_non_git_repo_and_engine_roots(tmp_path):
    request, _ = _snapshot_fixture(tmp_path, initialize_git=False)

    with pytest.raises(SnapshotError) as caught:
        create_snapshot(request)

    assert caught.value.code == "git_head_invalid"
    assert not (request.output_root / request.snapshot_id).exists()


@pytest.mark.parametrize("field", ["repo_head", "engine_head"])
def test_verify_snapshot_rejects_non_exact_git_head(tmp_path, field):
    request, _ = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest[field] = "a" * 64
    tampered = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    result.manifest_path.write_bytes(tampered)

    with pytest.raises(SnapshotError) as caught:
        verify_snapshot(
            result.snapshot_root,
            expected_manifest_sha256=hashlib.sha256(tampered).hexdigest(),
        )

    assert caught.value.code == "snapshot_manifest_invalid"


def test_create_snapshot_covers_full_contract_and_verifies(tmp_path):
    request, paths = _snapshot_fixture(tmp_path)

    result = create_snapshot(request)
    verification = verify_snapshot(
        result.snapshot_root,
        expected_manifest_sha256=result.manifest_sha256,
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    assert verification.ok is True
    assert verification.manifest_sha256 == result.manifest_sha256
    assert manifest["brain_targets"]["object_kinds"] == dict(
        sorted(BrainStore._KIND_DIR.items())
    )
    assert len(manifest["brain_targets"]["object_kinds"]) == 19
    brain_paths = {
        entry["path"]
        for entry in manifest["files"]
        if entry["scope"] == "brain"
    }
    for kind, relative_directory in BrainStore._KIND_DIR.items():
        assert f"{relative_directory}/{kind}.json" in brain_paths
    assert {
        "raw/sources/a.md",
        "raw/sources/nested/b.json",
        ".brain-local/index.db",
        ".brain-local/index.db-wal",
        ".brain-local/index.db-shm",
        ".brain-local/stale-set.json",
        "eval_scenarios.json",
    } <= brain_paths
    source_inventory = {
        entry["path"]: entry["sha256"]
        for entry in manifest["raw_sources"]
    }
    assert source_inventory == {
        "raw/sources/a.md": _sha256(paths["source_a"]),
        "raw/sources/nested/b.json": hashlib.sha256(
            b'{"source":"b"}\n'
        ).hexdigest(),
    }
    assert manifest["managed_files"] == [{
        "path": ".agents/skills/demo/SKILL.md",
        "recorded_sha256": _sha256(paths["managed"]),
        "actual_sha256": _sha256(paths["managed"]),
        "matches_recorded": True,
    }]


def test_verify_requires_trusted_receipt_before_manifest_parse(tmp_path):
    request, _ = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    result.manifest_path.write_bytes(b"{not-json")

    with pytest.raises(SnapshotError) as caught:
        verify_snapshot(
            result.snapshot_root,
            expected_manifest_sha256="0" * 64,
        )

    assert caught.value.code == "manifest_sha256_mismatch"


def test_coordinated_manifest_and_payload_object_removal_fails_receipt(
    tmp_path,
):
    request, _ = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    removed = next(
        entry for entry in manifest["files"]
        if entry["path"].endswith("/DomainContext.json")
    )
    manifest["files"].remove(removed)
    (result.snapshot_root / removed["snapshot_path"]).unlink()
    result.manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(SnapshotError) as caught:
        verify_snapshot(
            result.snapshot_root,
            expected_manifest_sha256=result.manifest_sha256,
        )

    assert caught.value.code == "manifest_sha256_mismatch"


def test_manifest_completeness_metadata_is_internally_derived(tmp_path):
    request, _ = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["corpus"]["object_ids"]) == 19
    assert set(manifest["corpus"]["kind_counts"]) == set(BrainStore._KIND_DIR)
    assert set(manifest["derived"]["index"]) == {
        "index.db",
        "index.db-wal",
        "index.db-shm",
    }
    manifest["corpus"]["kind_counts"]["DomainContext"] = 0
    tampered = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    result.manifest_path.write_bytes(tampered)

    with pytest.raises(SnapshotError) as caught:
        verify_snapshot(
            result.snapshot_root,
            expected_manifest_sha256=hashlib.sha256(tampered).hexdigest(),
        )

    assert caught.value.code == "snapshot_metadata_mismatch"


def test_create_snapshot_fails_closed_if_source_changes_during_copy(tmp_path):
    request, paths = _snapshot_fixture(tmp_path)
    original_copy = snapshot._copy_file
    changed = False

    def mutate_after_copy(source: Path, destination: Path) -> None:
        nonlocal changed
        original_copy(source, destination)
        if source == paths["source_a"] and not changed:
            changed = True
            source.write_bytes(b"changed-during-snapshot\n")

    with mock.patch.object(snapshot, "_copy_file", side_effect=mutate_after_copy):
        with pytest.raises(SnapshotError) as caught:
            create_snapshot(request)

    assert caught.value.code == "source_fingerprint_changed"
    assert not (request.output_root / request.snapshot_id).exists()


def test_verify_snapshot_rejects_tampered_payload(tmp_path):
    request, _ = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    copied = next(entry for entry in manifest["files"] if entry["copied"])
    (result.snapshot_root / copied["snapshot_path"]).write_bytes(b"tampered")

    with pytest.raises(SnapshotError) as caught:
        verify_snapshot(
            result.snapshot_root,
            expected_manifest_sha256=result.manifest_sha256,
        )

    assert caught.value.code == "snapshot_payload_hash_mismatch"


def test_restore_snapshot_replaces_captured_scope_and_removes_new_entries(tmp_path):
    request, paths = _snapshot_fixture(tmp_path)
    original_object = paths["object"].read_bytes()
    result = create_snapshot(request)
    paths["object"].write_bytes(b"changed\n")
    extra = paths["object"].parent / "extra.json"
    extra.write_bytes(b"extra\n")

    restored = restore_snapshot(
        result.snapshot_root,
        request.brain_root,
        expected_manifest_sha256=result.manifest_sha256,
    )

    assert restored.snapshot_id == request.snapshot_id
    assert paths["object"].read_bytes() == original_object
    assert not extra.exists()
    assert verify_snapshot(
        result.snapshot_root,
        expected_manifest_sha256=result.manifest_sha256,
    ).ok is True


def test_restore_activation_failure_rolls_live_tree_back(tmp_path):
    request, paths = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    paths["object"].write_bytes(b"live-before-failed-restore\n")
    before = paths["object"].read_bytes()
    original_rename = snapshot._rename_entry
    calls = 0

    def fail_second_rename(source_fd, source_name, destination_fd, destination_name):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected activation failure")
        original_rename(source_fd, source_name, destination_fd, destination_name)

    with mock.patch.object(snapshot, "_rename_entry", side_effect=fail_second_rename):
        with pytest.raises(SnapshotError) as caught:
            restore_snapshot(
                result.snapshot_root,
                request.brain_root,
                expected_manifest_sha256=result.manifest_sha256,
            )

    assert caught.value.code == "restore_activation_failed"
    assert paths["object"].read_bytes() == before


def test_restore_recovers_after_process_exit_immediately_after_live_rename(
    tmp_path,
):
    request, paths = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    original_object = paths["object"].read_bytes()
    paths["object"].write_bytes(b"live-before-crash\n")
    script = f"""
import os
from pathlib import Path
import project_brain.snapshot as snapshot

brain = Path({str(request.brain_root)!r})
original_rename = snapshot._rename_entry
def crash_after_live_rename(source_fd, source_name, destination_fd, destination_name):
    original_rename(source_fd, source_name, destination_fd, destination_name)
    if source_name == brain.name and destination_name == "backup":
        os._exit(91)
snapshot._rename_entry = crash_after_live_rename
snapshot.restore_snapshot(
    Path({str(result.snapshot_root)!r}),
    brain,
    expected_manifest_sha256={result.manifest_sha256!r},
)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONPATH": "src"},
        cwd=Path(__file__).parents[1],
        check=False,
    )

    assert crashed.returncode == 91
    state_root = snapshot._restore_state_root(request.brain_root)
    assert (state_root / "journal.json").is_file()
    assert not request.brain_root.exists()

    restored = restore_snapshot(
        result.snapshot_root,
        request.brain_root,
        expected_manifest_sha256=result.manifest_sha256,
    )

    assert restored.snapshot_id == request.snapshot_id
    assert paths["object"].read_bytes() == original_object
    assert not state_root.exists()


def test_recovery_rejects_symlink_replacement_of_backup_without_mutation(
    tmp_path,
):
    request, paths = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    paths["object"].write_bytes(b"live-before-crash\n")
    script = f"""
import os
from pathlib import Path
import project_brain.snapshot as snapshot

brain = Path({str(request.brain_root)!r})
original_rename = snapshot._rename_entry
def crash_after_live_rename(source_fd, source_name, destination_fd, destination_name):
    original_rename(source_fd, source_name, destination_fd, destination_name)
    if source_name == brain.name and destination_name == "backup":
        os._exit(91)
snapshot._rename_entry = crash_after_live_rename
snapshot.restore_snapshot(
    Path({str(result.snapshot_root)!r}),
    brain,
    expected_manifest_sha256={result.manifest_sha256!r},
)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONPATH": "src"},
        cwd=Path(__file__).parents[1],
        check=False,
    )
    assert crashed.returncode == 91

    state_root = snapshot._restore_state_root(request.brain_root)
    journal_path = state_root / "journal.json"
    journal_before = journal_path.read_bytes()
    workspace = Path(json.loads(journal_before)["workspace"])
    backup = workspace / "backup"
    external_backup = tmp_path / "external-backup"
    backup.rename(external_backup)
    backup.symlink_to(external_backup, target_is_directory=True)

    with pytest.raises(SnapshotError) as caught:
        restore_snapshot(
            result.snapshot_root,
            request.brain_root,
            expected_manifest_sha256=result.manifest_sha256,
        )

    assert caught.value.code == "recovery_required"
    assert not request.brain_root.exists()
    assert backup.is_symlink()
    assert journal_path.read_bytes() == journal_before


@pytest.mark.parametrize(
    "artifact",
    ["staged", "workspace", "journal", "phases", "missing_staged"],
)
def test_recovery_rejects_inode_replacement_without_mutation(tmp_path, artifact):
    request, paths = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    paths["object"].write_bytes(b"live-before-double-failure\n")
    original_rename = snapshot._rename_entry
    calls = 0

    def fail_activation_and_rollback(
        source_fd,
        source_name,
        destination_fd,
        destination_name,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise OSError(f"injected rename failure {calls}")
        original_rename(source_fd, source_name, destination_fd, destination_name)

    with mock.patch.object(
        snapshot,
        "_rename_entry",
        side_effect=fail_activation_and_rollback,
    ):
        with pytest.raises(SnapshotError):
            restore_snapshot(
                result.snapshot_root,
                request.brain_root,
                expected_manifest_sha256=result.manifest_sha256,
            )

    state_root = snapshot._restore_state_root(request.brain_root)
    journal_path = state_root / "journal.json"
    journal_before = journal_path.read_bytes()
    workspace = Path(json.loads(journal_before)["workspace"])
    if artifact in {"staged", "missing_staged"}:
        target = workspace / "staged"
    elif artifact == "workspace":
        target = workspace
    elif artifact == "journal":
        target = journal_path
    else:
        target = state_root / "phases.log"
    displaced = tmp_path / f"displaced-{artifact}"
    target.rename(displaced)
    if artifact not in {"missing_staged"}:
        if displaced.is_dir():
            shutil.copytree(displaced, target)
        else:
            target.write_bytes(displaced.read_bytes())

    with pytest.raises(SnapshotError) as caught:
        restore_snapshot(
            result.snapshot_root,
            request.brain_root,
            expected_manifest_sha256=result.manifest_sha256,
        )

    assert caught.value.code == "recovery_required"
    assert not request.brain_root.exists()
    if artifact == "missing_staged":
        assert not target.exists()
    else:
        assert target.exists()
    assert journal_path.read_bytes() == journal_before


def test_restore_preserves_recovery_state_if_activation_and_rollback_fail(
    tmp_path,
):
    request, paths = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    original_object = paths["object"].read_bytes()
    paths["object"].write_bytes(b"live-before-double-failure\n")
    original_rename = snapshot._rename_entry
    calls = 0

    def fail_activation_and_rollback(
        source_fd,
        source_name,
        destination_fd,
        destination_name,
    ) -> None:
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise OSError(f"injected rename failure {calls}")
        original_rename(source_fd, source_name, destination_fd, destination_name)

    with mock.patch.object(
        snapshot,
        "_rename_entry",
        side_effect=fail_activation_and_rollback,
    ):
        with pytest.raises(SnapshotError) as caught:
            restore_snapshot(
                result.snapshot_root,
                request.brain_root,
                expected_manifest_sha256=result.manifest_sha256,
            )

    state_root = snapshot._restore_state_root(request.brain_root)
    assert caught.value.code == "recovery_required"
    assert state_root in caught.value.paths
    assert (state_root / "journal.json").is_file()
    journal = json.loads((state_root / "journal.json").read_text(encoding="utf-8"))
    workspace = Path(journal["workspace"])
    assert (workspace / "backup").is_dir()
    assert (workspace / "staged").is_dir()

    restore_snapshot(
        result.snapshot_root,
        request.brain_root,
        expected_manifest_sha256=result.manifest_sha256,
    )

    assert paths["object"].read_bytes() == original_object
    assert not state_root.exists()


def test_managed_file_intermediate_symlink_is_rejected(tmp_path):
    request, paths = _snapshot_fixture(tmp_path)
    outside = tmp_path / "outside"
    outside_skill = outside / "skills" / "demo" / "SKILL.md"
    _write(outside_skill, paths["managed"].read_bytes())
    agents = request.repo_root / ".agents"
    agents.rename(request.repo_root / ".agents-real")
    agents.symlink_to(outside, target_is_directory=True)

    with pytest.raises(SnapshotError) as caught:
        create_snapshot(request)

    assert caught.value.code == "symlink_forbidden"


def test_symlinked_output_root_cannot_redirect_snapshot_into_brain(tmp_path):
    request, _ = _snapshot_fixture(tmp_path)
    request.output_root.symlink_to(
        request.brain_root / "redirected-snapshots",
        target_is_directory=True,
    )

    with pytest.raises(SnapshotError) as caught:
        create_snapshot(request)

    assert caught.value.code in {"symlink_forbidden", "output_inside_brain"}
    assert not (request.brain_root / "redirected-snapshots" / request.snapshot_id).exists()


def test_symlink_manifest_is_rejected_even_when_target_bytes_match(tmp_path):
    request, _ = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    external = tmp_path / "external-manifest.json"
    result.manifest_path.rename(external)
    result.manifest_path.symlink_to(external)

    with pytest.raises(SnapshotError) as caught:
        verify_snapshot(
            result.snapshot_root,
            expected_manifest_sha256=result.manifest_sha256,
        )

    assert caught.value.code == "symlink_forbidden"


@pytest.mark.parametrize("entry_kind", ["dangling_symlink", "directory", "fifo"])
def test_verify_rejects_every_unexpected_payload_entry(tmp_path, entry_kind):
    request, _ = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    unexpected = result.snapshot_root / "payload" / "unexpected"
    if entry_kind == "dangling_symlink":
        unexpected.symlink_to(tmp_path / "missing")
    elif entry_kind == "directory":
        unexpected.mkdir()
    else:
        os.mkfifo(unexpected)

    with pytest.raises(SnapshotError) as caught:
        verify_snapshot(
            result.snapshot_root,
            expected_manifest_sha256=result.manifest_sha256,
        )

    assert caught.value.code == "snapshot_payload_inventory_mismatch"
