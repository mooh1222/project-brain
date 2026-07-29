from __future__ import annotations

import hashlib
import json
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


def _snapshot_fixture(tmp_path: Path) -> tuple[SnapshotRequest, dict[str, Path]]:
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


def test_create_snapshot_covers_full_contract_and_verifies(tmp_path):
    request, paths = _snapshot_fixture(tmp_path)

    result = create_snapshot(request)
    verification = verify_snapshot(result.snapshot_root)
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
        verify_snapshot(result.snapshot_root)

    assert caught.value.code == "snapshot_payload_hash_mismatch"


def test_restore_snapshot_replaces_captured_scope_and_removes_new_entries(tmp_path):
    request, paths = _snapshot_fixture(tmp_path)
    original_object = paths["object"].read_bytes()
    result = create_snapshot(request)
    paths["object"].write_bytes(b"changed\n")
    extra = paths["object"].parent / "extra.json"
    extra.write_bytes(b"extra\n")

    restored = restore_snapshot(result.snapshot_root, request.brain_root)

    assert restored.snapshot_id == request.snapshot_id
    assert paths["object"].read_bytes() == original_object
    assert not extra.exists()
    assert verify_snapshot(result.snapshot_root).ok is True


def test_restore_activation_failure_rolls_live_tree_back(tmp_path):
    request, paths = _snapshot_fixture(tmp_path)
    result = create_snapshot(request)
    paths["object"].write_bytes(b"live-before-failed-restore\n")
    before = paths["object"].read_bytes()
    original_rename = snapshot._rename_path
    calls = 0

    def fail_second_rename(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected activation failure")
        original_rename(source, destination)

    with mock.patch.object(snapshot, "_rename_path", side_effect=fail_second_rename):
        with pytest.raises(SnapshotError) as caught:
            restore_snapshot(result.snapshot_root, request.brain_root)

    assert caught.value.code == "restore_activation_failed"
    assert paths["object"].read_bytes() == before
