from collections.abc import Callable
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from types import MappingProxyType
from unittest import mock

import pytest

from project_brain import corpus_io, evidence_preparation, foundation
from project_brain.evidence_preparation import (
    BasePlanTarget,
    EvidenceLoadedIdentity,
    EvidencePreparationError,
    ProjectedStore,
    capture_evidence_loaded_identity,
    capture_loaded_adapter_identity,
    plan_base,
    verify_evidence_loaded_identity,
)
from project_brain.evidence_plan import EvidencePlanRequirement, parse_evidence_plan
from project_brain.mutation import MutationService
from project_brain.store import BrainStore


_STAMP = "2026-08-27T09:00:00+09:00"


def _candidate(object_id: str, meaning: str, *, stamp: str = _STAMP) -> dict:
    return {
        "id": object_id,
        "kind": "DomainMapping",
        "status": "candidate",
        "title": f"Candidate {object_id.rsplit('.', 1)[-1]}",
        "meaning": meaning,
        "created_at": stamp,
        "updated_at": stamp,
    }


def _decoded(value: bytes) -> dict:
    return json.loads(value.decode("utf-8"))


def _commit_test_engine(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "e3@test.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "E3 Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "fixture"],
        check=True,
    )


def _identity_fixture(tmp_path: Path, monkeypatch) -> tuple[Path, Path, Path]:
    engine_root = (tmp_path / "engine").resolve()
    package = engine_root / "src/project_brain"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(b"\n")
    (package / "cli.py").write_bytes(b"def main(): pass\n")
    adapter_module = package / "evidence_preparation.py"
    adapter_module.write_bytes(b"adapter-v1\n")
    (engine_root / "pyproject.toml").write_bytes(b"[project]\nname='fixture'\n")
    (engine_root / "uv.lock").write_bytes(b"version = 1\n")
    _commit_test_engine(engine_root)

    brain_root = (tmp_path / "brain").resolve()
    raw = brain_root / "raw/sources/issue-43.md"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"raw source v1\n")
    monkeypatch.setattr(
        foundation,
        "resolved_project_brain_file",
        lambda: package / "__init__.py",
    )
    monkeypatch.setattr(
        foundation,
        "resolved_cli_source_file",
        lambda: package / "cli.py",
    )
    monkeypatch.setattr(
        evidence_preparation,
        "_loaded_adapter_module_path",
        lambda: adapter_module,
    )
    return engine_root, brain_root, adapter_module


def _source_entry(target_id: str, source: dict[str, object]):
    return parse_evidence_plan(
        (
            json.dumps(
                {
                    "entries": [
                        {
                            "target_id": target_id,
                            "source": source,
                            "claimed_producer": {
                                "kind": "agent",
                                "id": "issue-43-test",
                                "version": "1",
                            },
                            "claimed_verifiers": [],
                        },
                    ],
                    "version": 1,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    ).entries[0]


def _raw_source_entry(target_id: str, raw_path: str):
    return _source_entry(
        target_id,
        {"type": "raw_source_observation", "path": raw_path},
    )


def _raw_source_target(
    target_id: str = "manifest.ctx.source",
    kind: str = "EvidenceManifest",
) -> BasePlanTarget:
    return BasePlanTarget(
        target_id=target_id,
        kind=kind,
        action="create",
        before_unstamped_bytes=None,
        before_semantic_sha256=None,
        base_unstamped_bytes=b"{}",
        base_semantic_sha256="0" * 64,
    )


def _capture_raw_identity(
    engine_root: Path,
    brain_root: Path,
    raw_path: str = "raw/sources/issue-43.md",
):
    target = _raw_source_target()
    return capture_evidence_loaded_identity(
        engine_root=engine_root,
        brain_root=brain_root,
        target=target,
        entry=_raw_source_entry(target.target_id, raw_path),
    )


def test_loaded_identity_is_capture_only_deeply_immutable_baseline(
    tmp_path,
    monkeypatch,
):
    engine_root, brain_root, _adapter_module = _identity_fixture(tmp_path, monkeypatch)
    with pytest.raises(TypeError):
        EvidenceLoadedIdentity(
            engine_root=engine_root,
            brain_root=brain_root,
            target_kind="EvidenceManifest",
            raw_path="raw/sources/issue-43.md",
            engine={},
            adapter={},
            raw_snapshot={},
        )

    identity = _capture_raw_identity(engine_root, brain_root)

    with pytest.raises(TypeError):
        identity.engine["head"] = "caller-forged"
    with pytest.raises(TypeError):
        identity.adapter["id"] = "caller-forged"
    with pytest.raises(TypeError):
        identity.raw_snapshot["file"]["bytes_sha256"] = "0" * 64

    (brain_root / "raw/sources/issue-43.md").write_bytes(b"raw source v2\n")
    _assert_identity_drift_is_zero_write(identity)


def test_loaded_adapter_identity_uses_only_base_target_and_e1_raw_source(
    tmp_path,
    monkeypatch,
):
    engine_root, brain_root, module = _identity_fixture(tmp_path, monkeypatch)
    target = _raw_source_target()
    entry = _raw_source_entry(target.target_id, "raw/sources/issue-43.md")

    adapter = capture_evidence_loaded_identity(
        engine_root=engine_root,
        brain_root=brain_root,
        target=target,
        entry=entry,
    ).adapter

    assert (
        adapter.id,
        adapter.version,
        adapter.module_path,
        adapter.module_sha256,
    ) == (
        "local_raw_observation",
        "1",
        str(module),
        "7a2084cf00ac07d47f1385f3534bc87202862e783aba40dc5705e80aa5f0af47",
    )

    for mismatched_target, mismatched_entry in (
        (
            target,
            _raw_source_entry("manifest.ctx.other", "raw/sources/issue-43.md"),
        ),
        (
            _raw_source_target(kind="SpecDocument"),
            entry,
        ),
        (
            target,
            _source_entry(target.target_id, {"type": "existing_sources"}),
        ),
    ):
        with pytest.raises(EvidencePreparationError) as raised:
            capture_evidence_loaded_identity(
                engine_root=engine_root,
                brain_root=brain_root,
                target=mismatched_target,
                entry=mismatched_entry,
            )

        assert raised.value.code == "evidence_source_variant_mismatch"

    with pytest.raises(EvidencePreparationError) as raised:
        capture_evidence_loaded_identity(
            engine_root=engine_root,
            brain_root=brain_root,
            target=_raw_source_target("mapping.ctx.source", "DomainMapping"),
            entry=_raw_source_entry("mapping.ctx.source", "raw/sources/issue-43.md"),
        )

    assert raised.value.code == "evidence_adapter_unavailable"


def _object(
    object_id: str,
    *,
    kind: str,
    status: str,
    stamp: str = _STAMP,
    **fields: object,
) -> dict:
    return {
        "id": object_id,
        "kind": kind,
        "status": status,
        "title": object_id,
        "value": object_id,
        "created_at": stamp,
        "updated_at": stamp,
        **fields,
    }


def test_loaded_adapter_identity_uses_closed_raw_registry_and_loaded_module_bytes(
    tmp_path,
    monkeypatch,
):
    module = (tmp_path / "local_raw_adapter.py").resolve()
    module.write_bytes(b"adapter-v1\n")
    monkeypatch.setattr(
        evidence_preparation,
        "_loaded_adapter_module_path",
        lambda: module,
    )

    for target_id, kind in (
        ("manifest.ctx.source", "EvidenceManifest"),
        ("spec.document", "SpecDocument"),
        ("revision.document.one", "SpecRevision"),
        ("slide.document.one.1", "SlideRef"),
        ("slack.ctx.thread", "SlackThread"),
    ):
        target = _raw_source_target(target_id, kind)
        adapter = capture_loaded_adapter_identity(
            target=target,
            entry=_raw_source_entry(target_id, "raw/sources/issue-43.md"),
        )
        assert (
            adapter.id,
            adapter.version,
            adapter.module_path,
            adapter.module_sha256,
        ) == (
            "local_raw_observation",
            "1",
            str(module),
            "7a2084cf00ac07d47f1385f3534bc87202862e783aba40dc5705e80aa5f0af47",
        )


def test_raw_snapshot_parent_binding_rejects_symlink_and_hardlink_to_initial_invalid(
    tmp_path,
    monkeypatch,
):
    engine_root, brain_root, _adapter_module = _identity_fixture(tmp_path, monkeypatch)
    brain_root = (tmp_path / "brain").resolve()
    source_directory = brain_root / "raw/sources"
    source_directory.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "outside-source.md"
    target.write_bytes(b"outside\n")
    symlink = source_directory / "symlink.md"
    symlink.symlink_to(target)

    with pytest.raises(EvidencePreparationError) as raised:
        _capture_raw_identity(engine_root, brain_root, "raw/sources/symlink.md")

    assert raised.value.code == "evidence_raw_source_invalid"

    hardlinked = source_directory / "hardlinked.md"
    hardlinked.write_bytes(b"hardlinked\n")
    os.link(hardlinked, source_directory / "second-name.md")

    with pytest.raises(EvidencePreparationError) as raised:
        _capture_raw_identity(engine_root, brain_root, "raw/sources/hardlinked.md")

    assert raised.value.code == "evidence_raw_source_invalid"


def test_loaded_identity_maps_unreadable_initial_raw_source_to_unavailable(
    tmp_path,
    monkeypatch,
):
    engine_root, brain_root, _adapter_module = _identity_fixture(tmp_path, monkeypatch)

    with pytest.raises(EvidencePreparationError) as raised:
        _capture_raw_identity(engine_root, brain_root, "raw/sources/missing.md")

    assert raised.value.code == "evidence_raw_source_unavailable"


def test_identity_drift_is_zero_write_when_loaded_engine_changes(
    tmp_path,
    monkeypatch,
):
    engine_root, brain_root, _adapter_module = _identity_fixture(tmp_path, monkeypatch)
    identity = _capture_raw_identity(engine_root, brain_root)
    (engine_root / "src/project_brain/cli.py").write_bytes(b"def main(): changed\n")

    _assert_identity_drift_is_zero_write(identity)


def _assert_identity_drift_is_zero_write(identity) -> None:

    filesystem = mock.Mock(side_effect=AssertionError("filesystem write called"))
    journal = mock.Mock(side_effect=AssertionError("journal called"))
    receipt = mock.Mock(side_effect=AssertionError("receipt called"))
    clock = mock.Mock(side_effect=AssertionError("clock called"))
    mutation = mock.Mock(side_effect=AssertionError("mutation called"))
    with (
        mock.patch.object(BrainStore, "save_object", filesystem),
        mock.patch.object(corpus_io, "apply_transaction", journal),
        mock.patch.object(corpus_io, "record_no_change_receipt", receipt),
        mock.patch.object(MutationService, "apply", mutation),
        mock.patch.object(time, "time", clock),
    ):
        with pytest.raises(EvidencePreparationError) as raised:
            verify_evidence_loaded_identity(identity)

    assert raised.value.code == "evidence_snapshot_changed"
    assert not filesystem.called
    assert not journal.called
    assert not receipt.called
    assert not mutation.called
    assert not clock.called


def test_identity_drift_is_zero_write_when_loaded_adapter_module_changes(
    tmp_path,
    monkeypatch,
):
    engine_root, brain_root, adapter_module = _identity_fixture(tmp_path, monkeypatch)
    identity = _capture_raw_identity(engine_root, brain_root)
    adapter_module.write_bytes(b"adapter-v2\n")

    _assert_identity_drift_is_zero_write(identity)


def test_identity_drift_is_zero_write_when_raw_snapshot_parent_binding_changes_after_ordered_capture(
    tmp_path,
    monkeypatch,
):
    engine_root, brain_root, _adapter_module = _identity_fixture(tmp_path, monkeypatch)
    original_parent = brain_root / "raw/sources/briefs"
    original_source = original_parent / "issue-43.md"
    original_parent.mkdir()
    original_source.write_bytes(b"raw source v1\n")
    identity = _capture_raw_identity(
        engine_root,
        brain_root,
        "raw/sources/briefs/issue-43.md",
    )

    assert (
        identity.raw_snapshot.root.path,
        identity.raw_snapshot.root.device,
        identity.raw_snapshot.root.inode,
    ) == (
        str(brain_root),
        brain_root.stat().st_dev,
        brain_root.stat().st_ino,
    )
    assert identity.raw_snapshot.path == "raw/sources/briefs/issue-43.md"
    assert [
        (binding.path, binding.device, binding.inode)
        for binding in identity.raw_snapshot.parent_bindings
    ] == [
        ("raw", (brain_root / "raw").stat().st_dev, (brain_root / "raw").stat().st_ino),
        (
            "raw/sources",
            (brain_root / "raw/sources").stat().st_dev,
            (brain_root / "raw/sources").stat().st_ino,
        ),
        (
            "raw/sources/briefs",
            original_source.parent.stat().st_dev,
            original_source.parent.stat().st_ino,
        ),
    ]

    original_parent.rename(brain_root / "raw/sources/briefs-before")
    rebound_parent = brain_root / "raw/sources/briefs"
    rebound_parent.mkdir()
    (rebound_parent / "issue-43.md").write_bytes(b"raw source v1\n")

    _assert_identity_drift_is_zero_write(identity)


def test_identity_drift_is_zero_write_when_brain_root_rebinds(
    tmp_path,
    monkeypatch,
):
    engine_root, brain_root, _adapter_module = _identity_fixture(tmp_path, monkeypatch)
    identity = _capture_raw_identity(engine_root, brain_root)
    moved = tmp_path / "moved-brain"
    brain_root.rename(moved)
    shutil.copytree(moved, brain_root)

    _assert_identity_drift_is_zero_write(identity)


def test_identity_drift_is_zero_write_when_brain_root_rebind_preserves_raw_subtree(
    tmp_path,
    monkeypatch,
):
    engine_root, brain_root, _adapter_module = _identity_fixture(tmp_path, monkeypatch)
    identity = _capture_raw_identity(engine_root, brain_root)
    source = brain_root / "raw/sources/issue-43.md"
    captured_root = (brain_root.stat().st_dev, brain_root.stat().st_ino)
    captured_parent = (source.parent.stat().st_dev, source.parent.stat().st_ino)
    captured_file = (source.stat().st_dev, source.stat().st_ino, source.read_bytes())

    moved = tmp_path / "moved-brain"
    brain_root.rename(moved)
    brain_root.mkdir()
    (moved / "raw").rename(brain_root / "raw")

    source = brain_root / "raw/sources/issue-43.md"
    assert (brain_root.stat().st_dev, brain_root.stat().st_ino) != captured_root
    assert (source.parent.stat().st_dev, source.parent.stat().st_ino) == captured_parent
    assert (source.stat().st_dev, source.stat().st_ino, source.read_bytes()) == captured_file

    _assert_identity_drift_is_zero_write(identity)


def test_identity_drift_is_zero_write_when_raw_file_changes(
    tmp_path,
    monkeypatch,
):
    engine_root, brain_root, _adapter_module = _identity_fixture(tmp_path, monkeypatch)
    identity = _capture_raw_identity(engine_root, brain_root)
    (brain_root / "raw/sources/issue-43.md").write_bytes(b"raw source v2\n")

    _assert_identity_drift_is_zero_write(identity)


@pytest.mark.parametrize(
    "after_images,delete_ids",
    (
        (
            [
                _candidate("candidate.duplicate", "first"),
                _candidate("candidate.duplicate", "second"),
            ],
            (),
        ),
        ([], ("candidate.delete", "candidate.delete")),
        ([_candidate("candidate.live", "planned")], ("candidate.live",)),
        ([], ("candidate.missing",)),
    ),
    ids=(
        "duplicate-after",
        "duplicate-delete",
        "after-delete-overlap",
        "missing-delete",
    ),
)
@pytest.mark.parametrize("seam", (plan_base, ProjectedStore))
def test_e2_public_seams_reject_invalid_base_ids_before_planning(
    after_images: list[dict],
    delete_ids: tuple[str, ...],
    seam: Callable[..., object],
) -> None:
    live = _candidate("candidate.live", "live")
    delete = _candidate("candidate.delete", "live")
    store = BrainStore({live["id"]: live, delete["id"]: delete})

    with pytest.raises(EvidencePreparationError) as raised:
        seam(store, after_images, delete_ids=delete_ids)

    assert raised.value.code == "evidence_base_plan_invalid"


def test_base_plan_four_actions():
    before_update = _candidate("candidate.update", "old")
    before_same = _candidate("candidate.same", "same")
    before_delete = _candidate("candidate.delete", "gone")
    store = BrainStore({
        before_update["id"]: before_update,
        before_same["id"]: before_same,
        before_delete["id"]: before_delete,
    })

    plan = plan_base(
        store,
        [
            _candidate("candidate.create", "new"),
            _candidate("candidate.update", "new", stamp="2099-01-01T00:00:00Z"),
            _candidate("candidate.same", "same", stamp="2099-01-01T00:00:00Z"),
        ],
        delete_ids=("candidate.delete",),
    )

    assert [(target.target_id, target.action) for target in plan.targets] == [
        ("candidate.create", "create"),
        ("candidate.delete", "delete"),
        ("candidate.same", "no_change"),
        ("candidate.update", "update"),
    ]

    targets = {target.target_id: target for target in plan.targets}
    assert targets["candidate.create"].before_unstamped_bytes is None
    assert _decoded(targets["candidate.create"].base_unstamped_bytes) == {
        "id": "candidate.create",
        "kind": "DomainMapping",
        "status": "candidate",
        "title": "Candidate create",
        "meaning": "new",
    }
    assert targets["candidate.create"].base_semantic_sha256 == (
        "dfc395cf2fd856d8e01a791e66cd2435f8ac329acb71c7faa029a5c7a721c7c9"
    )

    assert _decoded(targets["candidate.update"].before_unstamped_bytes) == {
        "id": "candidate.update",
        "kind": "DomainMapping",
        "status": "candidate",
        "title": "Candidate update",
        "meaning": "old",
    }
    assert _decoded(targets["candidate.update"].base_unstamped_bytes) == {
        "id": "candidate.update",
        "kind": "DomainMapping",
        "status": "candidate",
        "title": "Candidate update",
        "meaning": "new",
    }
    assert targets["candidate.update"].before_semantic_sha256 == (
        "a38f52220abe4b1246fb635a6ffabde6deee393bc4c23b340d382bffd90622b1"
    )
    assert targets["candidate.update"].base_semantic_sha256 == (
        "1555b1fdf81067680370c9c13cd2644b67e8c57cfb16a807eac787c5e7f07570"
    )

    assert targets["candidate.same"].before_unstamped_bytes == (
        b'{\n'
        b'  "id": "candidate.same",\n'
        b'  "kind": "DomainMapping",\n'
        b'  "status": "candidate",\n'
        b'  "title": "Candidate same",\n'
        b'  "meaning": "same"\n'
        b'}\n'
    )
    assert targets["candidate.same"].base_unstamped_bytes == (
        b'{\n'
        b'  "id": "candidate.same",\n'
        b'  "kind": "DomainMapping",\n'
        b'  "status": "candidate",\n'
        b'  "title": "Candidate same",\n'
        b'  "meaning": "same"\n'
        b'}\n'
    )
    assert targets["candidate.same"].before_semantic_sha256 == (
        "75b3d37f454e1717e21f154976ddc11104f2b1573d53ec651b588954034d55dd"
    )
    assert targets["candidate.same"].base_semantic_sha256 == (
        "75b3d37f454e1717e21f154976ddc11104f2b1573d53ec651b588954034d55dd"
    )

    assert targets["candidate.delete"].before_unstamped_bytes == (
        b'{\n'
        b'  "id": "candidate.delete",\n'
        b'  "kind": "DomainMapping",\n'
        b'  "status": "candidate",\n'
        b'  "title": "Candidate delete",\n'
        b'  "meaning": "gone"\n'
        b'}\n'
    )
    assert targets["candidate.delete"].before_semantic_sha256 == (
        "afd53ffe5f374dbff73feddc8a10bdf00fe8671fb40ae5c7b429d27628f54d59"
    )
    assert targets["candidate.delete"].base_unstamped_bytes is None
    assert targets["candidate.delete"].base_semantic_sha256 is None


def test_projected_store_after_images_and_deletes():
    live_update = _candidate("candidate.update", "live")
    live_delete = _candidate("candidate.delete", "live")
    live_keep = _candidate("candidate.keep", "live")
    store = BrainStore({
        live_update["id"]: live_update,
        live_delete["id"]: live_delete,
        live_keep["id"]: live_keep,
    })
    after_update = _candidate("candidate.update", "planned")
    after_create = _candidate("candidate.create", "planned")

    projected = ProjectedStore(
        store,
        [after_update, after_create],
        delete_ids=("candidate.delete",),
    )

    assert projected.get("candidate.update")["meaning"] == "planned"
    assert projected.get("candidate.create")["meaning"] == "planned"
    assert not projected.has("candidate.delete")
    assert {obj["id"] for obj in projected.all()} == {
        "candidate.create",
        "candidate.keep",
        "candidate.update",
    }
    assert store.get("candidate.update")["meaning"] == "live"
    assert store.has("candidate.delete")

    after_update["meaning"] = "caller-mutated"
    returned = projected.get("candidate.update")
    returned["meaning"] = "return-mutated"

    assert projected.get("candidate.update")["meaning"] == "planned"
    assert store.get("candidate.update")["meaning"] == "live"


def test_projected_store_keeps_deep_snapshot_and_returns_fresh_copies():
    live = _candidate("candidate.update", "live")
    live["nested"] = {"values": ["live"]}
    store = BrainStore({live["id"]: live})
    after = _candidate("candidate.update", "planned")
    after["nested"] = MappingProxyType({"values": ["planned"]})

    projected = ProjectedStore(store, [after])

    after["nested"]["values"].append("caller-mutated")
    store.get("candidate.update")["nested"]["values"].append("live-mutated")
    returned = projected.get("candidate.update")
    returned["nested"]["values"].append("get-mutated")
    returned_all = projected.all()[0]
    returned_all["nested"]["values"].append("all-mutated")
    returned_by_kind = projected.by_kind("DomainMapping")[0]
    returned_by_kind["nested"]["values"].append("by-kind-mutated")

    expected = {"values": ["planned"]}
    assert projected.get("candidate.update")["nested"] == expected
    assert projected.all()[0]["nested"] == expected
    assert projected.by_kind("DomainMapping")[0]["nested"] == expected
    assert store.get("candidate.update")["nested"] == {
        "values": ["live", "live-mutated"]
    }


def test_target_requirement_from_action_and_capability():
    before_delete = _candidate("candidate.delete", "live")
    before_reviewed_same = _object(
        "mapping.reviewed-same",
        kind="DomainMapping",
        status="reviewed",
    )
    store = BrainStore({
        before_delete["id"]: before_delete,
        before_reviewed_same["id"]: before_reviewed_same,
    })

    plan = plan_base(
        store,
        [
            _candidate("candidate.optional", "candidate"),
            _object(
                "manifest.required",
                kind="EvidenceManifest",
                status="reviewed",
            ),
            _object(
                "mapping.direct-reviewed",
                kind="DomainMapping",
                status="reviewed",
            ),
            _object(
                "mapping.reviewed-same",
                kind="DomainMapping",
                status="reviewed",
                stamp="2099-01-01T00:00:00Z",
            ),
            _object(
                "projection.context",
                kind="ContextProjection",
                status="reviewed",
                format="context_md",
            ),
        ],
        delete_ids=("candidate.delete",),
    )

    assert plan.requirements == (
        EvidencePlanRequirement(
            "candidate.delete",
            "forbidden",
            "evidence_plan_delete_target",
        ),
        EvidencePlanRequirement("candidate.optional", "optional_unverified"),
        EvidencePlanRequirement(
            "manifest.required",
            "required",
        ),
        EvidencePlanRequirement(
            "mapping.direct-reviewed",
            "forbidden",
            "direct_reviewed_evidence_unavailable",
        ),
        EvidencePlanRequirement(
            "mapping.reviewed-same",
            "optional_unverified",
        ),
        EvidencePlanRequirement(
            "projection.context",
            "forbidden",
            "evidence_profile_unavailable",
        ),
    )


def test_base_plan_has_no_external_effects():
    before = _candidate("candidate.before", "before")
    after = _candidate("candidate.after", "after")
    store = BrainStore({before["id"]: before})
    forbidden_context = mock.Mock(name="adapter-and-repo-context")

    filesystem = mock.Mock(side_effect=AssertionError("filesystem called"))
    journal = mock.Mock(side_effect=AssertionError("journal called"))
    receipt = mock.Mock(side_effect=AssertionError("receipt called"))
    clock = mock.Mock(side_effect=AssertionError("clock called"))
    apply = mock.Mock(side_effect=AssertionError("mutation apply called"))

    with (
        mock.patch.object(BrainStore, "load", filesystem),
        mock.patch.object(BrainStore, "save_object", filesystem),
        mock.patch.object(corpus_io, "apply_transaction", journal),
        mock.patch.object(corpus_io, "record_no_change_receipt", receipt),
        mock.patch.object(MutationService, "apply", apply),
        mock.patch.object(time, "time", clock),
    ):
        plan = plan_base(
            store,
            [after],
            delete_ids=(before["id"],),
            repo_context=forbidden_context,
        )

    assert [target.action for target in plan.targets] == ["create", "delete"]
    assert not forbidden_context.mock_calls
    assert not filesystem.called
    assert not journal.called
    assert not receipt.called
    assert not apply.called
    assert not clock.called


def test_invalid_base_plan_has_no_external_effects():
    before = _candidate("candidate.before", "before")
    store = BrainStore({before["id"]: before})
    adapter = mock.Mock(name="adapter-and-repo-context")

    filesystem = mock.Mock(side_effect=AssertionError("filesystem called"))
    journal = mock.Mock(side_effect=AssertionError("journal called"))
    receipt = mock.Mock(side_effect=AssertionError("receipt called"))
    clock = mock.Mock(side_effect=AssertionError("clock called"))
    apply = mock.Mock(side_effect=AssertionError("mutation apply called"))

    with (
        mock.patch.object(BrainStore, "load", filesystem),
        mock.patch.object(BrainStore, "save_object", filesystem),
        mock.patch.object(corpus_io, "apply_transaction", journal),
        mock.patch.object(corpus_io, "record_no_change_receipt", receipt),
        mock.patch.object(MutationService, "apply", apply),
        mock.patch.object(time, "time", clock),
    ):
        with pytest.raises(EvidencePreparationError) as raised:
            plan_base(
                store,
                [_candidate(before["id"], "planned")],
                delete_ids=(before["id"],),
                repo_context=adapter,
            )

    assert raised.value.code == "evidence_base_plan_invalid"
    assert not adapter.mock_calls
    assert not filesystem.called
    assert not journal.called
    assert not receipt.called
    assert not apply.called
    assert not clock.called
