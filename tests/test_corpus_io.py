from __future__ import annotations

import errno
import hashlib
import json
import multiprocessing
import os
import stat
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path

import pytest

import project_brain.corpus_io as corpus_io
from project_brain.corpus_io import (
    CorpusIOError,
    JournalState,
    RecoveryRequiredError,
    apply_transaction,
    assert_corpus_readable,
    batch_intent_relative_path,
    corpus_lock,
    fsync_directory,
    fsync_file,
    recover_committed_receipt,
    recover_committed_receipts,
    recover_unfinished_transaction,
)
from project_brain.mutation import (
    AuxiliaryFileUpdate,
    MutationOperation,
    MutationRequest,
    MutationService,
)
from project_brain.store import BrainStore
from project_brain.transaction_receipt import BatchBinding, batch_intent_id
from tests.coverage_helpers import direct_coverage
from tests.test_ingest import candidate_term, context
from tests.test_mutation import (
    _canonical_repair_binding,
    _collision_merge_request,
    _code_locator,
    _mapping_repair_request,
)


FAILURE_POINTS = (
    "after_temp_fsync",
    "after_journal_prepared",
    "after_state_committing",
    "after_first_before_rename",
    "after_first_live_replace",
    "after_derived_invalidation",
    "before_post_commit_gate",
)
PREPARATION_FAILURE_POINTS = (
    "after_private_root_mkdir",
    "after_temp_dir_mkdir",
    "after_before_dir_mkdir",
    "after_snapshot_dir_mkdir",
    "before_active_publish",
)
TRANSACTION_TIME = "2026-06-04T00:00:00Z"


class InjectedCrash(RuntimeError):
    pass


def _service() -> MutationService:
    return MutationService(clock=lambda: TRANSACTION_TIME)


def _result_object(result, object_id: str) -> dict:
    return next(obj for obj in result.after_objects if obj["id"] == object_id)


def _journal_manifest(manifest) -> dict[str, object]:
    payload = asdict(manifest)
    for field_name in (
        "coverage_sha256",
        "expected_objects",
        "verified_objects",
        "changed_objects",
    ):
        payload.pop(field_name, None)
    return payload


def _hold_stable_lock_in_child(brain_root, ready, release) -> None:
    with corpus_io.stable_corpus_lock(
        Path(brain_root),
        exclusive=True,
    ):
        ready.set()
        if not release.wait(timeout=5):
            raise AssertionError("stable lock release was not signaled")


@contextmanager
def _other_process_holding_stable_lock(brain_root: Path):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_stable_lock_in_child,
        args=(str(brain_root), ready, release),
    )
    process.start()
    if not ready.wait(timeout=3):
        process.terminate()
        process.join(timeout=1)
        raise AssertionError("child did not acquire the stable lock")
    try:
        yield release
    finally:
        release.set()
        process.join(timeout=3)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)
            raise AssertionError("stable lock child did not exit")
        assert process.exitcode == 0


def _real_directory(path: Path) -> Path:
    path.mkdir()
    return path


def _replace_directory_binding(path: Path) -> Path:
    detached = path.with_name(f"{path.name}-detached")
    path.rename(detached)
    path.mkdir()
    return detached


def _write_object(brain_root: Path, obj: dict) -> Path:
    path = BrainStore.object_path(brain_root, obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(BrainStore.object_bytes(obj))
    return path


def _batch_binding(
    *,
    brain_root: Path,
    item_key: str = "one",
    item_input_fingerprint: str = "1" * 64,
) -> BatchBinding:
    brain_stat = brain_root.stat()
    return BatchBinding(
        batch_manifest_sha256="a" * 64,
        item_key=item_key,
        item_input_fingerprint=item_input_fingerprint,
        verify_json_sha256="b" * 64,
        domain_spec_py_sha256="c" * 64,
        repo_root="/repo",
        brain_root=str(brain_root.resolve()),
        brain_root_device=brain_stat.st_dev,
        brain_root_inode=brain_stat.st_ino,
        expected_repo_id="demo",
        expected_revision_ref="HEAD",
        target_revision_sha="d" * 40,
        engine_root="/engine",
        engine_sha="e" * 40,
    )


def _request(
    brain_root: Path,
    objects: tuple[dict, ...],
    *,
    batch_binding: BatchBinding | None = None,
    operation: MutationOperation = MutationOperation.INGEST,
) -> MutationRequest:
    return MutationRequest(
        operation=operation,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=objects,
        batch_binding=batch_binding,
        coverage=(
            direct_coverage(*objects)
            if operation is MutationOperation.INGEST
            else None
        ),
    )


def _seed_derived_files(brain_root: Path) -> None:
    local = brain_root / ".brain-local"
    local.mkdir(parents=True, exist_ok=True)
    for name, payload in (
        ("index.db", b"index"),
        ("index.db-wal", b"wal"),
        ("index.db-shm", b"shm"),
        ("index.db-journal", b"journal"),
        ("stale-set.json", b'{"stale":true}\n'),
    ):
        (local / name).write_bytes(payload)


def _state_fingerprint(brain_root: Path) -> str:
    digest = hashlib.sha256()
    paths: list[Path] = []
    for rel in set(BrainStore._KIND_DIR.values()):
        root = brain_root / rel
        if root.is_dir():
            paths.extend(root.rglob("*.json"))
    local = brain_root / ".brain-local"
    for name in (
        "index.db",
        "index.db-wal",
        "index.db-shm",
        "index.db-journal",
        "stale-set.json",
    ):
        path = local / name
        if path.exists():
            paths.append(path)
    eval_path = brain_root / "eval_scenarios.json"
    if eval_path.exists():
        paths.append(eval_path)
    for path in sorted(paths):
        digest.update(path.relative_to(brain_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _auxiliary_update(before: bytes, after: bytes) -> AuxiliaryFileUpdate:
    return AuxiliaryFileUpdate(
        path="eval_scenarios.json",
        before_sha256=hashlib.sha256(before).hexdigest(),
        after_sha256=hashlib.sha256(after).hexdigest(),
        after_bytes=after,
    )


def _changed_context() -> tuple[dict, dict]:
    before = context()
    after = dict(before)
    after["title"] = "changed"
    return before, after


def _crash_at(point: str):
    def inject(actual: str) -> None:
        if actual == point:
            raise InjectedCrash(point)

    return inject


def _case_only_migration(tmp_path):
    """Build one APFS spelling-only rename from a valid migration plan."""
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.neutral.Legacy",
        quote=None,
        title="legacy spelling",
    )
    new = dict(old)
    new["id"] = "code.neutral.legacy"
    _write_object(brain_root, old)
    _seed_derived_files(brain_root)
    request = MutationRequest(
        operation=MutationOperation.ID_ONLY_MIGRATION,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=(new,),
        delete_ids=(old["id"],),
    )
    planned = _service().plan((new,), request=request)
    assert planned.ok and planned.manifest is not None
    rename = planned.manifest.renames[0]
    old_path = brain_root / rename["old_path"]
    new_path = brain_root / rename["new_path"]
    assert old_path.is_file()
    assert new_path.is_file()
    assert old_path.samefile(new_path)
    return brain_root, old, new, request, planned, old_path, new_path


def _exact_child_names(path: Path) -> set[str]:
    return {child.name for child in path.iterdir()}


def _case_only_apply_inputs(planned, new: dict) -> tuple[dict, dict[str, bytes]]:
    rename = planned.manifest.renames[0]
    stamped_new = _result_object(planned, new["id"])
    return (
        _journal_manifest(planned.manifest),
        {rename["new_path"]: BrainStore.object_bytes(stamped_new)},
    )


def _case_only_multi_migration(tmp_path, *, count: int = 3):
    """Build multiple spelling-only renames in one transaction."""
    brain_root = tmp_path / "brain"
    old_objects = []
    new_objects = []
    for suffix in ("ALegacy", "BLegacy", "ZLegacy")[:count]:
        old = _code_locator(
            object_id=f"code.neutral.{suffix}",
            quote=None,
            title=f"legacy {suffix}",
        )
        new = dict(old)
        new["id"] = f"code.neutral.{suffix.lower()}"
        _write_object(brain_root, old)
        old_objects.append(old)
        new_objects.append(new)
    _seed_derived_files(brain_root)
    request = MutationRequest(
        operation=MutationOperation.ID_ONLY_MIGRATION,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=tuple(new_objects),
        delete_ids=tuple(obj["id"] for obj in old_objects),
    )
    planned = _service().plan(tuple(new_objects), request=request)
    assert planned.ok and planned.manifest is not None
    assert len(planned.manifest.renames) == count
    pairs = tuple(
        (
            brain_root / rename["old_path"],
            brain_root / rename["new_path"],
            old,
            new,
        )
        for rename, old, new in zip(
            planned.manifest.renames,
            old_objects,
            new_objects,
            strict=True,
        )
    )
    assert all(old_path.samefile(new_path) for old_path, new_path, _, _ in pairs)
    return brain_root, request, planned, pairs


def test_low_level_api_exposes_exact_journal_states_and_fsyncs(tmp_path):
    assert tuple(state.value for state in JournalState) == (
        "preparing",
        "prepared",
        "committing",
        "committed",
        "rolled_back",
        "recovery_required",
    )
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    path = brain_root / "payload"
    path.write_bytes(b"payload")

    fsync_file(path)
    fsync_directory(brain_root)
    with corpus_lock(brain_root, exclusive=False):
        assert (brain_root / ".brain-local" / "corpus.lock").is_file()


def test_stable_corpus_lock_nonblocking_reports_busy(tmp_path):
    brain_root = tmp_path / "brain"
    with _other_process_holding_stable_lock(brain_root) as release:
        watchdog = threading.Timer(1, release.set)
        watchdog.start()
        try:
            started = time.monotonic()
            with pytest.raises(CorpusIOError) as exc:
                with corpus_io.stable_corpus_lock(
                    brain_root,
                    exclusive=True,
                    blocking=False,
                ):
                    raise AssertionError("lock body must not run")
            elapsed = time.monotonic() - started
            assert elapsed < 0.5
        finally:
            watchdog.cancel()
    assert exc.value.code == "corpus_lock_busy"


def test_stable_corpus_lock_default_still_blocks_until_release(tmp_path):
    brain_root = tmp_path / "brain"
    acquired = threading.Event()
    errors: list[BaseException] = []

    def acquire_default_lock() -> None:
        try:
            with corpus_io.stable_corpus_lock(
                brain_root,
                exclusive=True,
            ):
                acquired.set()
        except BaseException as exc:
            errors.append(exc)

    with _other_process_holding_stable_lock(brain_root):
        waiter = threading.Thread(target=acquire_default_lock)
        waiter.start()
        assert not acquired.wait(timeout=0.1)

    assert acquired.wait(timeout=1)
    waiter.join(timeout=1)
    assert not waiter.is_alive()
    assert errors == []


def test_stable_corpus_lock_same_process_nesting_remains_reentrant(tmp_path):
    brain_root = tmp_path / "brain"

    with corpus_io.stable_corpus_lock(brain_root, exclusive=True):
        with corpus_io.stable_corpus_lock(
            brain_root,
            exclusive=False,
            blocking=False,
        ):
            pass


def test_stable_corpus_lock_rejects_intermediate_symlink_ancestor(tmp_path):
    target = _real_directory(tmp_path / "external")
    target_parent = _real_directory(target / "nested")
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    brain_root = alias / "nested" / "brain"
    target_lock = target_parent / ".brain.project-brain-corpus.lock"
    body_ran = False
    error: CorpusIOError | None = None

    try:
        with corpus_io.stable_corpus_lock(brain_root, exclusive=True):
            body_ran = True
    except CorpusIOError as exc:
        error = exc

    assert not target_lock.exists()
    assert body_ran is False
    assert error is not None
    assert error.code == "symlink_forbidden"


def test_anchored_directory_closes_parent_fd_when_fstat_fails(
    tmp_path,
    monkeypatch,
):
    parent = _real_directory(tmp_path / "snapshots")
    real_fstat = os.fstat
    failed_fd: int | None = None

    def fail_parent_fstat(descriptor):
        nonlocal failed_fd
        failed_fd = descriptor
        raise OSError(errno.EIO, "injected fstat failure")

    monkeypatch.setattr(corpus_io.os, "fstat", fail_parent_fstat)

    with pytest.raises(OSError) as exc:
        corpus_io.create_anchored_temp_directory(
            parent,
            prefix=".task17-",
        )

    assert exc.value.errno == errno.EIO
    assert failed_fd is not None
    with pytest.raises(OSError) as closed:
        real_fstat(failed_fd)
    assert closed.value.errno == errno.EBADF


def test_anchored_temp_rejects_intermediate_symlink_ancestor(tmp_path):
    target = _real_directory(tmp_path / "external")
    target_snapshots = _real_directory(target / ".snapshots")
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    error: CorpusIOError | None = None

    try:
        corpus_io.create_anchored_temp_directory(
            alias / ".snapshots",
            prefix=".task17-",
        )
    except CorpusIOError as exc:
        error = exc

    assert tuple(target_snapshots.iterdir()) == ()
    assert error is not None
    assert error.code == "symlink_forbidden"


def test_anchored_named_rejects_intermediate_symlink_ancestor(tmp_path):
    target = _real_directory(tmp_path / "external")
    target_snapshots = _real_directory(target / ".snapshots")
    actual_parent = corpus_io.create_anchored_temp_directory(
        target_snapshots,
        prefix=".task17-",
    )
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    aliased_parent = replace(
        actual_parent,
        path=alias / ".snapshots" / actual_parent.path.name,
    )
    payload = actual_parent.path / "payload"
    error: CorpusIOError | None = None

    try:
        corpus_io.create_anchored_directory(
            aliased_parent,
            name=payload.name,
        )
    except CorpusIOError as exc:
        error = exc

    assert not payload.exists()
    assert error is not None
    assert error.code == "path_binding_changed"


def test_root_level_var_alias_supports_lock_and_anchored_staging(tmp_path):
    root_alias = Path("/var")
    if sys.platform == "darwin":
        assert root_alias.is_symlink()
    elif not root_alias.is_symlink():
        pytest.skip("platform has no root-level /var symlink")
    link_target = Path(os.readlink(root_alias))
    assert not link_target.is_absolute()
    physical_var = Path("/") / link_target
    try:
        relative_tmp = tmp_path.relative_to(physical_var)
    except ValueError:
        pytest.skip("tmp_path is not below the root-level /var alias")
    lexical_tmp = root_alias / relative_tmp
    physical_snapshots = _real_directory(tmp_path / "snapshots")
    lexical_snapshots = lexical_tmp / physical_snapshots.name

    with corpus_io.stable_corpus_lock(
        lexical_tmp / "brain",
        exclusive=True,
    ):
        pass
    binding = corpus_io.create_anchored_temp_directory(
        lexical_snapshots,
        prefix=".task17-",
    )

    assert (tmp_path / ".brain.project-brain-corpus.lock").is_file()
    assert binding.path.parent == lexical_snapshots
    assert binding.path.is_dir()
    corpus_io.verify_directory_binding(binding)


def test_anchored_staging_creates_bound_direct_children(tmp_path):
    parent = _real_directory(tmp_path / "snapshots")

    temporary = corpus_io.create_anchored_temp_directory(
        parent,
        prefix=".task17-",
    )
    named = corpus_io.create_anchored_directory(
        temporary,
        name="payload",
        mode=0o750,
    )

    parent_stat = os.lstat(parent)
    temporary_stat = os.lstat(temporary.path)
    named_stat = os.lstat(named.path)
    assert temporary.path.parent == parent
    assert temporary.path.name.startswith(".task17-")
    assert stat.S_ISDIR(temporary_stat.st_mode)
    assert stat.S_IMODE(temporary_stat.st_mode) == 0o700
    assert (
        temporary.parent_device,
        temporary.parent_inode,
        temporary.device,
        temporary.inode,
    ) == (
        parent_stat.st_dev,
        parent_stat.st_ino,
        temporary_stat.st_dev,
        temporary_stat.st_ino,
    )
    assert named.path == temporary.path / "payload"
    assert stat.S_ISDIR(named_stat.st_mode)
    assert stat.S_IMODE(named_stat.st_mode) == 0o750
    assert (named.parent_device, named.parent_inode) == (
        temporary.device,
        temporary.inode,
    )
    corpus_io.verify_directory_binding(temporary)
    corpus_io.verify_directory_binding(named)


def test_anchored_staging_rejects_symlink_parent(tmp_path):
    target = _real_directory(tmp_path / "real-snapshots")
    parent = tmp_path / "snapshots"
    parent.symlink_to(target, target_is_directory=True)

    with pytest.raises(CorpusIOError) as exc:
        corpus_io.create_anchored_temp_directory(
            parent,
            prefix=".task17-",
        )

    assert exc.value.code == "symlink_forbidden"
    assert tuple(target.iterdir()) == ()


def test_anchored_staging_rejects_existing_child(tmp_path):
    root = _real_directory(tmp_path / "snapshots")
    parent = corpus_io.create_anchored_temp_directory(
        root,
        prefix=".task17-",
    )
    (parent.path / "existing").mkdir()

    with pytest.raises(CorpusIOError) as exc:
        corpus_io.create_anchored_directory(parent, name="existing")

    assert exc.value.code == "path_already_exists"


def test_anchored_staging_rejects_fifo_child(tmp_path):
    root = _real_directory(tmp_path / "snapshots")
    parent = corpus_io.create_anchored_temp_directory(
        root,
        prefix=".task17-",
    )
    os.mkfifo(parent.path / "payload")

    with pytest.raises(CorpusIOError) as exc:
        corpus_io.create_anchored_directory(parent, name="payload")

    assert exc.value.code == "file_type_invalid"


def test_anchored_staging_detects_parent_replacement(tmp_path):
    parent = _real_directory(tmp_path / "snapshots")
    child = corpus_io.create_anchored_temp_directory(
        parent,
        prefix=".task17-",
    )
    _replace_directory_binding(parent)

    with pytest.raises(CorpusIOError) as exc:
        corpus_io.verify_directory_binding(child)

    assert exc.value.code == "path_binding_changed"


def test_anchored_staging_detects_child_replacement(tmp_path):
    parent = _real_directory(tmp_path / "snapshots")
    child = corpus_io.create_anchored_temp_directory(
        parent,
        prefix=".task17-",
    )
    _replace_directory_binding(child.path)

    with pytest.raises(CorpusIOError) as exc:
        corpus_io.verify_directory_binding(child)

    assert exc.value.code == "path_binding_changed"


def test_anchored_staging_rejects_cross_filesystem_child(
    tmp_path,
    monkeypatch,
):
    parent = _real_directory(tmp_path / "snapshots")
    real_observed_device = corpus_io._observed_device

    def observe_other_filesystem(path: str, actual_device: int) -> int:
        if Path(path).parent == parent:
            return actual_device + 1
        return real_observed_device(path, actual_device)

    monkeypatch.setattr(
        corpus_io,
        "_observed_device",
        observe_other_filesystem,
    )

    with pytest.raises(CorpusIOError) as exc:
        corpus_io.create_anchored_temp_directory(
            parent,
            prefix=".cross-device-",
        )

    assert exc.value.code == "filesystem_mismatch"
    assert all(not tuple(path.iterdir()) for path in parent.iterdir())


@pytest.mark.parametrize("name", ("", ".", "..", "nested/payload"))
def test_anchored_staging_rejects_non_child_name(tmp_path, name):
    root = _real_directory(tmp_path / "snapshots")
    parent = corpus_io.create_anchored_temp_directory(
        root,
        prefix=".task17-",
    )

    with pytest.raises(ValueError, match="direct child"):
        corpus_io.create_anchored_directory(parent, name=name)

    assert tuple(parent.path.iterdir()) == ()


def test_manifest_always_contains_canonical_repair_binding(tmp_path):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)

    planned = _service().plan(
        (after,),
        request=_request(brain_root, (after,)),
    )

    assert planned.ok and planned.manifest is not None
    assert "canonical_repair_binding" in _journal_manifest(planned.manifest)
    assert planned.manifest.canonical_repair_binding is None


@pytest.mark.parametrize(
    ("operation", "binding"),
    (
        (
            "canonical_repair",
            {
                "decision_ledger_sha256": "a" * 64,
                "unexpected": "b" * 64,
            },
        ),
        (
            "canonical_repair",
            {
                "decision_ledger_sha256": "A" * 64,
                "phase_a_classification_sha256": "b" * 64,
            },
        ),
        ("ingest", _canonical_repair_binding()),
        ("canonical_repair", None),
    ),
)
def test_invalid_canonical_repair_binding_is_rejected_before_journal_publish(
    tmp_path,
    operation,
    binding,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    planned = _service().plan(
        (after,),
        request=_request(brain_root, (after,)),
    )
    assert planned.ok and planned.manifest is not None
    manifest = _journal_manifest(planned.manifest)
    manifest["operation"] = operation
    manifest["canonical_repair_binding"] = binding
    after_path = planned.manifest.updates[0]["path"]

    with pytest.raises(ValueError, match="canonical_repair_binding"):
        apply_transaction(
            brain_root,
            manifest=manifest,
            after_files={after_path: BrainStore.object_bytes(after)},
        )

    transactions = brain_root / ".brain-local" / "transactions"
    assert not transactions.exists() or not tuple(
        transactions.rglob("journal.json")
    )


def test_manifest_missing_canonical_repair_binding_is_rejected_before_publish(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    planned = _service().plan(
        (after,),
        request=_request(brain_root, (after,)),
    )
    assert planned.ok and planned.manifest is not None
    manifest = _journal_manifest(planned.manifest)
    manifest.pop("canonical_repair_binding")

    with pytest.raises(ValueError, match="manifest keys"):
        apply_transaction(brain_root, manifest=manifest, after_files={})

    transactions = brain_root / ".brain-local" / "transactions"
    assert not transactions.exists() or not tuple(
        transactions.rglob("journal.json")
    )


def test_direct_canonical_repair_apply_revalidates_current_source(tmp_path):
    request = _mapping_repair_request(tmp_path)
    initially_valid = _service().plan(
        request.objects,
        request=request,
    )
    assert initially_valid.ok is True
    current_source = BrainStore.load(request.brain_root).get(
        request.delete_ids[0]
    )
    current_source["title"] = "concurrent drift"
    _write_object(request.brain_root, current_source)

    result = _service().apply(request.objects, request=request)

    assert result.error_code == "canonical_repair_payload_changed"
    store = BrainStore.load(request.brain_root)
    assert store.get(current_source["id"]) == current_source
    assert not store.has(request.objects[0]["id"])


@pytest.mark.parametrize("failure_point", FAILURE_POINTS)
def test_canonical_repair_rolls_back_every_transaction_failure_point(
    tmp_path,
    failure_point,
):
    request = _mapping_repair_request(tmp_path)
    _seed_derived_files(request.brain_root)
    before_fingerprint = _state_fingerprint(request.brain_root)

    with pytest.raises(InjectedCrash, match=failure_point):
        _service().apply(
            request.objects,
            request=request,
            failure_injector=_crash_at(failure_point),
        )

    recovery_request = _request(
        request.brain_root,
        (),
        operation=MutationOperation.PROJECTION,
    )
    assert _service().apply((), request=recovery_request).ok is True
    assert _state_fingerprint(request.brain_root) == before_fingerprint
    store = BrainStore.load(request.brain_root)
    assert store.has(request.delete_ids[0])
    assert not store.has(request.objects[0]["id"])


@pytest.mark.parametrize("failure_point", FAILURE_POINTS)
def test_canonical_merge_rolls_back_every_transaction_failure_point(
    tmp_path,
    failure_point,
):
    request = _collision_merge_request(tmp_path)
    brain_root = request.brain_root
    _seed_derived_files(brain_root)
    service = _service()
    planned = service.plan(request.objects, request=request)
    assert planned.ok and planned.manifest is not None
    manifest = planned.manifest

    merge_intent = next(
        intent
        for intent in request.canonical_repair_intents
        if intent.reason_code == "collision_merge_into_existing"
    )
    (collapse,) = request.canonical_repair_reference_collapses
    source_action = next(
        action
        for action in manifest.deletes
        if action["object_id"] == merge_intent.source_id
    )
    survivor_action = next(
        action
        for action in manifest.updates
        if action["object_id"] == merge_intent.new_id
    )
    referrer_action = next(
        action
        for action in manifest.updates
        if action["object_id"] == collapse.object_id
    )
    actions = (*manifest.updates, *manifest.deletes)
    action_paths = tuple(action["path"] for action in actions)
    assert len(action_paths) == len(set(action_paths))

    def file_sha_state() -> frozenset[tuple[str, str | None]]:
        return frozenset(
            (
                relative_path,
                (
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    if path.is_file()
                    else None
                ),
            )
            for relative_path in action_paths
            for path in (brain_root / relative_path,)
        )

    before_state = frozenset(
        (action["path"], action["before_sha256"])
        for action in actions
    )
    after_state = frozenset(
        (action["path"], action["after_sha256"])
        for action in actions
    )
    before_fingerprint = _state_fingerprint(brain_root)
    assert file_sha_state() == before_state

    with pytest.raises(InjectedCrash, match=failure_point):
        service.apply(
            request.objects,
            request=request,
            failure_injector=_crash_at(failure_point),
        )

    interrupted_state = dict(file_sha_state())
    source_missing = interrupted_state[source_action["path"]] is None
    survivor_before = (
        interrupted_state[survivor_action["path"]]
        == survivor_action["before_sha256"]
    )
    referrer_before = (
        interrupted_state[referrer_action["path"]]
        == referrer_action["before_sha256"]
    )
    assert not (
        source_missing
        and survivor_before
        and referrer_before
    )
    with pytest.raises(RecoveryRequiredError):
        assert_corpus_readable(brain_root)

    recovered = recover_unfinished_transaction(brain_root)
    observed_state = file_sha_state()

    assert recovered.recovered_transaction_ids == (manifest.transaction_id,)
    assert observed_state in {before_state, after_state}
    assert observed_state == before_state
    assert _state_fingerprint(brain_root) == before_fingerprint


def test_batch_intent_identity_binds_key_even_when_input_bytes_match(tmp_path):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    first = _batch_binding(brain_root=brain_root, item_key="one")
    second = _batch_binding(brain_root=brain_root, item_key="two")

    assert first.item_input_fingerprint == second.item_input_fingerprint
    assert batch_intent_id(first) != batch_intent_id(second)
    assert batch_intent_id(first) == hashlib.sha256(
        json.dumps(
            {
                "batch_manifest_sha256": first.batch_manifest_sha256,
                "item_input_fingerprint": first.item_input_fingerprint,
                "item_key": first.item_key,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_legacy_nonbatch_committed_journal_without_binding_remains_readable(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    result = _service().apply(
        (after,),
        request=_request(brain_root, (after,)),
    )
    assert result.ok and result.manifest is not None
    journal_path = (
        brain_root
        / ".brain-local"
        / "transactions"
        / result.manifest.transaction_id
        / "journal.json"
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal.pop("batch_binding") is None
    assert journal["manifest"].pop("batch_binding") is None
    journal_path.write_text(
        json.dumps(journal, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    assert BrainStore.load(brain_root).get(after["id"]) == after
    newer = dict(after)
    newer["title"] = "legacy followup"
    followup = _service().apply(
        (newer,),
        request=_request(brain_root, (newer,)),
    )
    assert followup.ok and followup.manifest is not None
    assert followup.manifest.batch_binding is None


def _historical_context_replace_journal(
    tmp_path: Path,
    *,
    state: str,
) -> tuple[Path, Path, dict]:
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    request = _request(
        brain_root,
        (after,),
        operation=MutationOperation.CONTEXT_REPLACE,
    )
    result = _service().apply((after,), request=request)
    assert result.ok and result.manifest is not None
    journal_path = (
        brain_root
        / ".brain-local"
        / "transactions"
        / result.manifest.transaction_id
        / "journal.json"
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["state"] = state
    assert journal["manifest"].pop("canonical_repair_binding") is None
    if state == JournalState.ROLLED_BACK.value:
        _write_object(brain_root, before)
        expected = before
    else:
        expected = after
    journal_path.write_bytes(
        (
            json.dumps(
                journal,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    return brain_root, journal_path, expected


@pytest.mark.parametrize(
    "state",
    (JournalState.COMMITTED.value, JournalState.ROLLED_BACK.value),
)
def test_historical_terminal_manifest_without_canonical_binding_is_read_only_compatible(
    tmp_path,
    state,
):
    brain_root, journal_path, expected = _historical_context_replace_journal(
        tmp_path,
        state=state,
    )
    before_bytes = journal_path.read_bytes()

    assert_corpus_readable(brain_root)
    assert BrainStore.load(brain_root).get(expected["id"]) == expected
    recovered = recover_unfinished_transaction(brain_root)

    assert recovered.recovered_transaction_ids == ()
    assert journal_path.read_bytes() == before_bytes


@pytest.mark.parametrize(
    "state",
    (JournalState.PREPARED.value, JournalState.COMMITTING.value),
)
def test_historical_nonterminal_manifest_without_canonical_binding_is_rejected(
    tmp_path,
    state,
):
    brain_root, journal_path, _ = _historical_context_replace_journal(
        tmp_path,
        state=state,
    )
    before_bytes = journal_path.read_bytes()

    with pytest.raises(RecoveryRequiredError, match="journal structure is invalid"):
        assert_corpus_readable(brain_root)

    assert journal_path.read_bytes() == before_bytes


def test_terminal_canonical_repair_manifest_missing_binding_is_rejected(tmp_path):
    request = _mapping_repair_request(tmp_path)
    result = _service().apply(request.objects, request=request)
    assert result.ok and result.manifest is not None
    journal_path = (
        request.brain_root
        / ".brain-local"
        / "transactions"
        / result.manifest.transaction_id
        / "journal.json"
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal["manifest"].pop("canonical_repair_binding")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")

    with pytest.raises(RecoveryRequiredError, match="journal structure is invalid"):
        BrainStore.load(request.brain_root)


@pytest.mark.parametrize(
    "tamper",
    ("missing_other", "extra", "malformed", "invalid_nonnull_binding"),
)
def test_historical_terminal_manifest_compatibility_remains_fail_closed(
    tmp_path,
    tamper,
):
    brain_root, journal_path, _ = _historical_context_replace_journal(
        tmp_path,
        state=JournalState.COMMITTED.value,
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    manifest = journal["manifest"]
    if tamper == "missing_other":
        manifest.pop("engine_sha")
    elif tamper == "extra":
        manifest["unexpected"] = None
    elif tamper == "malformed":
        manifest["engine_sha"] = "invalid"
    else:
        manifest["canonical_repair_binding"] = {"unexpected": "a" * 64}
    journal_path.write_text(json.dumps(journal), encoding="utf-8")

    with pytest.raises(RecoveryRequiredError, match="journal structure is invalid"):
        BrainStore.load(brain_root)


def test_historical_terminal_manifest_rejects_combined_legacy_omissions(
    tmp_path,
):
    brain_root, journal_path, _ = _historical_context_replace_journal(
        tmp_path,
        state=JournalState.COMMITTED.value,
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal.pop("batch_binding") is None
    assert journal["manifest"].pop("batch_binding") is None
    journal_path.write_bytes(
        (
            json.dumps(
                journal,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    before_bytes = journal_path.read_bytes()

    with pytest.raises(RecoveryRequiredError, match="journal structure is invalid"):
        BrainStore.load(brain_root)

    assert journal_path.read_bytes() == before_bytes


def test_current_noncanonical_journal_writes_explicit_null_canonical_binding(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    request = _request(
        brain_root,
        (after,),
        operation=MutationOperation.CONTEXT_REPLACE,
    )

    result = _service().apply((after,), request=request)

    assert result.ok and result.manifest is not None
    journal_path = (
        brain_root
        / ".brain-local"
        / "transactions"
        / result.manifest.transaction_id
        / "journal.json"
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert "canonical_repair_binding" in journal["manifest"]
    assert journal["manifest"]["canonical_repair_binding"] is None


@pytest.mark.parametrize(
    ("legacy_state", "unfinished"),
    (
        ("rolled_back", False),
        ("preparing", True),
        ("committing", True),
    ),
)
def test_legacy_nonbatch_terminal_and_unfinished_journals_recover_then_write_null(
    tmp_path,
    legacy_state,
    unfinished,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    result = _service().apply(
        (after,),
        request=_request(brain_root, (after,)),
    )
    assert result.ok and result.manifest is not None
    journal_path = (
        brain_root
        / ".brain-local"
        / "transactions"
        / result.manifest.transaction_id
        / "journal.json"
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal.pop("batch_binding")
    journal["manifest"].pop("batch_binding")
    journal["state"] = legacy_state
    if legacy_state == "rolled_back":
        _write_object(brain_root, before)
    journal_path.write_text(
        json.dumps(journal, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    if unfinished:
        recovered = recover_unfinished_transaction(brain_root)
        assert recovered.recovered_transaction_ids == (
            result.manifest.transaction_id,
        )
    assert BrainStore.load(brain_root).get(before["id"]) == before

    newer = dict(before)
    newer["title"] = f"after legacy {legacy_state}"
    followup = _service().apply(
        (newer,),
        request=_request(brain_root, (newer,)),
    )
    assert followup.ok and followup.manifest is not None
    followup_journal = json.loads(
        (
            brain_root
            / ".brain-local"
            / "transactions"
            / followup.manifest.transaction_id
            / "journal.json"
        ).read_text(encoding="utf-8")
    )
    assert "batch_binding" in followup_journal
    assert followup_journal["batch_binding"] is None
    assert "batch_binding" in followup_journal["manifest"]
    assert followup_journal["manifest"]["batch_binding"] is None


def test_legacy_batch_binding_partial_presence_is_rejected(tmp_path):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    result = _service().apply(
        (after,),
        request=_request(brain_root, (after,)),
    )
    assert result.ok and result.manifest is not None
    journal_path = (
        brain_root
        / ".brain-local"
        / "transactions"
        / result.manifest.transaction_id
        / "journal.json"
    )
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal.pop("batch_binding")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")

    with pytest.raises(RecoveryRequiredError, match="journal structure is invalid"):
        BrainStore.load(brain_root)


def test_batch_intent_is_durable_before_commit_and_noncommitted_is_rejected(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    binding = _batch_binding(brain_root=brain_root)

    with pytest.raises(InjectedCrash, match="after_batch_intent_fsync"):
        _service().apply(
            (after,),
            request=_request(
                brain_root,
                (after,),
                batch_binding=binding,
            ),
            failure_injector=_crash_at("after_batch_intent_fsync"),
        )

    intent_path = brain_root / batch_intent_relative_path(binding)
    assert intent_path.is_file()
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    assert intent["batch_binding"] == asdict(binding)
    journal = json.loads(
        (
            brain_root
            / ".brain-local"
            / "transactions"
            / intent["transaction_id"]
            / "journal.json"
        ).read_text(encoding="utf-8")
    )
    assert journal["state"] != "committed"
    with pytest.raises(CorpusIOError, match="receipt_not_committed"):
        recover_committed_receipt(brain_root, binding)


def test_crash_after_committed_before_report_recovers_exact_receipt(tmp_path):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    binding = _batch_binding(brain_root=brain_root)

    with pytest.raises(InjectedCrash, match="after_journal_committed"):
        _service().apply(
            (after,),
            request=_request(
                brain_root,
                (after,),
                batch_binding=binding,
            ),
            failure_injector=_crash_at("after_journal_committed"),
        )

    receipt = recover_committed_receipt(brain_root, binding)

    assert receipt == {
        "ok": True,
        "transaction_id": receipt["transaction_id"],
        "operation": "ingest",
        "committed": True,
        "manifest_sha256": receipt["manifest_sha256"],
        "before_fingerprint": receipt["before_fingerprint"],
        "after_fingerprint": receipt["after_fingerprint"],
        "ingested_ids": [after["id"]],
        "ingested_count": 1,
    }
    assert len(receipt["transaction_id"]) == 64
    assert len(receipt["manifest_sha256"]) == 64
    assert BrainStore.load(brain_root).get(after["id"]) == after


def test_historical_committed_batch_receipt_preserves_original_manifest_sha(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    binding = _batch_binding(brain_root=brain_root)
    result = _service().apply(
        (after,),
        request=_request(brain_root, (after,), batch_binding=binding),
    )
    assert result.ok and result.manifest is not None
    journal_path = (
        brain_root
        / ".brain-local"
        / "transactions"
        / result.manifest.transaction_id
        / "journal.json"
    )
    intent_path = brain_root / batch_intent_relative_path(binding)
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    assert journal["manifest"].pop("canonical_repair_binding") is None
    historical_manifest_bytes = (
        json.dumps(
            journal["manifest"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    historical_manifest_sha256 = hashlib.sha256(
        historical_manifest_bytes
    ).hexdigest()
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["manifest_sha256"] = historical_manifest_sha256
    journal_path.write_bytes(
        (
            json.dumps(
                journal,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    intent_path.write_bytes(
        (
            json.dumps(
                intent,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    )
    journal_before = journal_path.read_bytes()
    intent_before = intent_path.read_bytes()

    receipt = recover_committed_receipt(brain_root, binding)

    assert receipt["transaction_id"] == result.manifest.transaction_id
    assert receipt["manifest_sha256"] == historical_manifest_sha256
    assert receipt["ingested_ids"] == [after["id"]]
    assert journal_path.read_bytes() == journal_before
    assert intent_path.read_bytes() == intent_before


def test_committed_receipt_rejects_forged_envelope_and_intent(tmp_path):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    binding = _batch_binding(brain_root=brain_root)
    result = _service().apply(
        (after,),
        request=_request(brain_root, (after,), batch_binding=binding),
    )
    receipt = recover_committed_receipt(brain_root, binding)

    forged = dict(receipt, manifest_sha256="0" * 64)
    with pytest.raises(CorpusIOError, match="receipt_mismatch"):
        recover_committed_receipt(
            brain_root,
            binding,
            expected_receipt=forged,
        )

    intent_path = brain_root / batch_intent_relative_path(binding)
    intent = json.loads(intent_path.read_text(encoding="utf-8"))
    intent["transaction_id"] = "f" * 64
    intent_path.write_text(
        json.dumps(intent, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        (CorpusIOError, RecoveryRequiredError),
        match="intent|transaction|journal",
    ):
        recover_committed_receipt(brain_root, binding)
    assert result.manifest is not None


def test_existing_batch_intent_never_overwrites_mismatched_plan(tmp_path):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    binding = _batch_binding(brain_root=brain_root)
    service = _service()

    with pytest.raises(InjectedCrash):
        service.apply(
            (after,),
            request=_request(brain_root, (after,), batch_binding=binding),
            failure_injector=_crash_at("after_batch_intent_fsync"),
        )
    recover_unfinished_transaction(brain_root)
    original_intent = (
        brain_root / batch_intent_relative_path(binding)
    ).read_bytes()
    different = dict(after, title="different")

    with pytest.raises(CorpusIOError, match="batch_intent_mismatch"):
        service.apply(
            (different,),
            request=_request(
                brain_root,
                (different,),
                batch_binding=binding,
            ),
        )
    assert (
        brain_root / batch_intent_relative_path(binding)
    ).read_bytes() == original_intent
    assert BrainStore.load(brain_root).get(before["id"]) == before


def test_committed_receipt_chain_verifies_all_items_and_current_tail(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    original = context()
    first_after = dict(original, title="first")
    second_after = dict(original, title="second")
    _write_object(brain_root, original)
    first_binding = _batch_binding(brain_root=brain_root, item_key="one")
    second_binding = _batch_binding(brain_root=brain_root, item_key="two")
    service = _service()
    service.apply(
        (first_after,),
        request=_request(
            brain_root,
            (first_after,),
            batch_binding=first_binding,
        ),
    )
    service.apply(
        (second_after,),
        request=_request(
            brain_root,
            (second_after,),
            batch_binding=second_binding,
        ),
    )

    receipts = recover_committed_receipts(
        brain_root,
        (first_binding, second_binding),
        expected_receipts=(None, None),
    )

    assert all(receipt is not None for receipt in receipts)
    assert receipts[0]["after_fingerprint"] == receipts[1]["before_fingerprint"]
    assert receipts[0]["transaction_id"] != receipts[1]["transaction_id"]
    assert BrainStore.load(brain_root).get(original["id"]) == second_after


def test_post_gate_receipt_mode_allows_derived_index_output(tmp_path):
    brain_root = tmp_path / "brain"
    original, after = _changed_context()
    _write_object(brain_root, original)
    binding = _batch_binding(brain_root=brain_root)
    _service().apply(
        (after,),
        request=_request(
            brain_root,
            (after,),
            batch_binding=binding,
        ),
    )
    receipt = recover_committed_receipt(brain_root, binding)
    local = brain_root / ".brain-local"
    local.mkdir(exist_ok=True)
    (local / "index.db").write_bytes(b"normal derived index output")

    recovered = recover_committed_receipts(
        brain_root,
        (binding,),
        expected_receipts=(receipt,),
        verification_mode="post_gate_object_tail",
    )

    assert recovered == (receipt,)
    with pytest.raises(
        CorpusIOError,
        match="committed_receipt_state_mismatch",
    ):
        recover_committed_receipts(
            brain_root,
            (binding,),
            expected_receipts=(receipt,),
            verification_mode="strict_commit",
        )


@pytest.mark.parametrize("drift_kind", ("action_object", "unknown_object"))
def test_post_gate_receipt_mode_rejects_any_object_corpus_drift(
    tmp_path,
    drift_kind,
):
    brain_root = tmp_path / drift_kind
    original, after = _changed_context()
    _write_object(brain_root, original)
    binding = _batch_binding(brain_root=brain_root)
    _service().apply(
        (after,),
        request=_request(
            brain_root,
            (after,),
            batch_binding=binding,
        ),
    )
    receipt = recover_committed_receipt(brain_root, binding)
    if drift_kind == "action_object":
        _write_object(brain_root, dict(after, title="tampered"))
    else:
        _write_object(brain_root, context("context.unexpected"))

    with pytest.raises(
        CorpusIOError,
        match="committed_receipt_state_mismatch",
    ):
        recover_committed_receipts(
            brain_root,
            (binding,),
            expected_receipts=(receipt,),
            verification_mode="post_gate_object_tail",
        )


def test_committed_receipt_chain_allows_missing_tail_but_not_gaps(tmp_path):
    brain_root = tmp_path / "brain"
    original, first_after = _changed_context()
    _write_object(brain_root, original)
    first_binding = _batch_binding(brain_root=brain_root, item_key="one")
    missing_binding = _batch_binding(brain_root=brain_root, item_key="two")
    _service().apply(
        (first_after,),
        request=_request(
            brain_root,
            (first_after,),
            batch_binding=first_binding,
        ),
    )

    receipts = recover_committed_receipts(
        brain_root,
        (first_binding, missing_binding),
        expected_receipts=(None, None),
    )

    assert receipts[0] is not None
    assert receipts[1] is None


def test_locked_reader_uses_pinned_root_after_lexical_root_swap(tmp_path):
    brain_root = tmp_path / "brain"
    detached_root = tmp_path / "detached-brain"
    before, replacement = _changed_context()
    _write_object(brain_root, before)

    with corpus_lock(brain_root, exclusive=False):
        brain_root.rename(detached_root)
        _write_object(brain_root, replacement)

        loaded = BrainStore.load_unlocked(brain_root)

    assert loaded.get(before["id"]) == before


def test_local_swap_cannot_create_an_overlapping_second_writer(tmp_path):
    brain_root = tmp_path / "brain"
    local_root = brain_root / ".brain-local"
    detached_local = brain_root / ".brain-local-detached"
    local_root.mkdir(parents=True)
    first_acquired = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    second_acquired = threading.Event()
    errors: list[BaseException] = []

    def first_writer() -> None:
        try:
            with corpus_lock(brain_root, exclusive=True):
                first_acquired.set()
                if not release_first.wait(timeout=2):
                    raise AssertionError("first writer release was not signaled")
        except BaseException as exc:
            errors.append(exc)

    def second_writer() -> None:
        try:
            second_started.set()
            with corpus_lock(brain_root, exclusive=True):
                second_acquired.set()
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=first_writer)
    second = threading.Thread(target=second_writer)
    first.start()
    assert first_acquired.wait(timeout=1)
    local_root.rename(detached_local)
    local_root.mkdir()
    second.start()
    assert second_started.wait(timeout=1)
    try:
        assert not second_acquired.wait(timeout=0.1)
    finally:
        release_first.set()
    assert second_acquired.wait(timeout=1)
    first.join(timeout=1)
    second.join(timeout=1)
    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []


def test_local_binding_swap_before_live_fails_without_mutating_corpus(tmp_path):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    live_path = _write_object(brain_root, before)
    service = _service()
    planned = service.plan((after,), request=_request(brain_root, (after,)))
    assert planned.manifest is not None
    local_root = brain_root / ".brain-local"
    detached_local = brain_root / ".brain-local-detached"
    relative_path = live_path.relative_to(brain_root).as_posix()

    with corpus_lock(brain_root, exclusive=True):
        local_root.rename(detached_local)
        local_root.mkdir()
        with pytest.raises(RuntimeError) as caught:
            apply_transaction(
                brain_root,
                manifest=_journal_manifest(planned.manifest),
                after_files={
                    relative_path: BrainStore.object_bytes(after),
                },
            )

    assert getattr(caught.value, "code", None) == "path_binding_changed"
    assert not (local_root / "transactions").exists()
    assert BrainStore.load(brain_root).get(before["id"]) == before


def test_local_swap_after_first_live_replace_rolls_back_on_pinned_scope(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    service = _service()
    planned = service.plan((after,), request=_request(brain_root, (after,)))
    assert planned.manifest is not None
    local_root = brain_root / ".brain-local"
    detached_local = brain_root / ".brain-local-detached"
    replacement_sentinel = local_root / "replacement-sentinel"

    def swap_local(point: str) -> None:
        if point != "after_first_live_replace":
            return
        local_root.rename(detached_local)
        local_root.mkdir()
        replacement_sentinel.write_bytes(b"replacement")

    with pytest.raises(RuntimeError) as caught:
        service.apply(
            (after,),
            request=_request(brain_root, (after,)),
            failure_injector=swap_local,
        )

    assert getattr(caught.value, "code", None) == "path_binding_changed"
    assert BrainStore.load(brain_root).get(before["id"]) == before
    assert replacement_sentinel.read_bytes() == b"replacement"
    assert not (local_root / "transactions").exists()
    journal_path = (
        detached_local
        / "transactions"
        / planned.manifest.transaction_id
        / "journal.json"
    )
    assert json.loads(journal_path.read_text(encoding="utf-8"))["state"] == (
        "rolled_back"
    )


@pytest.mark.parametrize(
    "swap_point",
    ["after_temp_fsync", "after_first_live_replace"],
)
def test_root_binding_swap_never_mutates_replacement_and_rolls_back_pinned_root(
    tmp_path,
    swap_point,
):
    brain_root = tmp_path / "brain"
    detached_root = tmp_path / "detached-brain"
    before, after = _changed_context()
    replacement = dict(before)
    replacement["title"] = "replacement"
    _write_object(brain_root, before)
    replacement_fingerprint: str | None = None

    def swap_root(point: str) -> None:
        nonlocal replacement_fingerprint
        if point != swap_point:
            return
        brain_root.rename(detached_root)
        _write_object(brain_root, replacement)
        replacement_fingerprint = _state_fingerprint(brain_root)

    with pytest.raises(RuntimeError) as caught:
        _service().apply(
            (after,),
            request=_request(brain_root, (after,)),
            failure_injector=swap_root,
        )

    assert getattr(caught.value, "code", None) == "path_binding_changed"
    assert replacement_fingerprint is not None
    assert _state_fingerprint(brain_root) == replacement_fingerprint
    assert BrainStore.load(detached_root).get(before["id"]) == before


def test_apply_uses_the_required_stage_order_and_invalidates_derived_files(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    _seed_derived_files(brain_root)
    observed: list[str] = []

    result = _service().apply(
        (after,),
        request=_request(brain_root, (after,)),
        failure_injector=observed.append,
    )

    assert result.ok is True
    assert observed == list(FAILURE_POINTS)
    assert BrainStore.load(brain_root).get(after["id"])["title"] == "changed"
    local = brain_root / ".brain-local"
    assert not (local / "index.db").exists()
    assert not (local / "index.db-wal").exists()
    assert not (local / "index.db-shm").exists()
    assert not (local / "index.db-journal").exists()
    assert not (local / "stale-set.json").exists()
    journal = json.loads(
        (
            local
            / "transactions"
            / result.manifest.transaction_id
            / "journal.json"
        ).read_text(encoding="utf-8")
    )
    assert journal["state"] == "committed"
    assert len(journal["before_derived_fingerprint"]) == 64
    assert len(journal["expected_after_derived_fingerprint"]) == 64


def test_noop_apply_preserves_derived_files_and_creates_no_transaction(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before = context()
    _write_object(brain_root, before)
    _seed_derived_files(brain_root)
    fingerprint = _state_fingerprint(brain_root)

    result = _service().apply(
        (before,),
        request=_request(brain_root, (before,)),
    )

    assert result.ok is True
    assert _state_fingerprint(brain_root) == fingerprint
    assert not (brain_root / ".brain-local" / "transactions").exists()


def test_identical_committed_manifest_can_run_again_after_later_reversion(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    service = _service()

    first = service.apply(
        (after,),
        request=_request(brain_root, (after,)),
    )
    first_journal_path = (
        brain_root
        / ".brain-local"
        / "transactions"
        / first.manifest.transaction_id
        / "journal.json"
    )
    first_journal_bytes = first_journal_path.read_bytes()
    reverted = service.apply(
        (before,),
        request=_request(brain_root, (before,)),
    )
    repeated = service.apply(
        (after,),
        request=_request(brain_root, (after,)),
    )

    assert first.ok is True
    assert reverted.ok is True
    assert repeated.ok is True
    assert repeated.manifest.transaction_id == first.manifest.transaction_id
    assert BrainStore.load(brain_root).get(after["id"]) == after
    archived = sorted(
        (
            brain_root
            / ".brain-local"
            / "transaction-history"
            / first.manifest.transaction_id
        ).glob("attempt-*/journal.json")
    )
    assert len(archived) == 1
    assert archived[0].read_bytes() == first_journal_bytes
    assert first_journal_path.is_file()
    assert json.loads(first_journal_path.read_text(encoding="utf-8"))["state"] == (
        "committed"
    )


def test_rolled_back_evidence_is_preserved_when_same_mutation_is_retried(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    service = _service()
    planned = service.plan((after,), request=_request(brain_root, (after,)))
    transaction_id = planned.manifest.transaction_id
    journal_path = (
        brain_root
        / ".brain-local"
        / "transactions"
        / transaction_id
        / "journal.json"
    )

    with pytest.raises(InjectedCrash):
        service.apply(
            (after,),
            request=_request(brain_root, (after,)),
            failure_injector=_crash_at("after_first_live_replace"),
        )
    recovered = recover_unfinished_transaction(brain_root)
    rolled_back_bytes = journal_path.read_bytes()

    retried = service.apply(
        (after,),
        request=_request(brain_root, (after,)),
    )

    assert recovered.recovered_transaction_ids == (transaction_id,)
    assert retried.ok is True
    archived = sorted(
        (
            brain_root
            / ".brain-local"
            / "transaction-history"
            / transaction_id
        ).glob("attempt-*/journal.json")
    )
    assert len(archived) == 1
    assert archived[0].read_bytes() == rolled_back_bytes
    assert json.loads(archived[0].read_text(encoding="utf-8"))["state"] == (
        "rolled_back"
    )
    assert json.loads(journal_path.read_text(encoding="utf-8"))["state"] == (
        "committed"
    )


def test_reader_and_recovery_ignore_archived_attempts(tmp_path):
    brain_root = tmp_path / "brain"
    before = context()
    _write_object(brain_root, before)
    archived = (
        brain_root
        / ".brain-local"
        / "transaction-history"
        / "archived-id"
        / "attempt-000001"
        / "journal.json"
    )
    archived.parent.mkdir(parents=True)
    archived.write_text(
        json.dumps({
            "transaction_id": "archived-id",
            "state": "committing",
        }),
        encoding="utf-8",
    )

    store = BrainStore.load(brain_root)
    recovered = recover_unfinished_transaction(brain_root)

    assert store.get(before["id"]) == before
    assert recovered.recovered_transaction_ids == ()
    assert json.loads(archived.read_text(encoding="utf-8"))["state"] == (
        "committing"
    )


@pytest.mark.parametrize("state", ["committed", "prepared"])
def test_minimal_or_malformed_journal_is_never_treated_as_valid(
    tmp_path,
    state,
):
    brain_root = tmp_path / "brain"
    before = context()
    _write_object(brain_root, before)
    journal = (
        brain_root
        / ".brain-local"
        / "transactions"
        / "malformed"
        / "journal.json"
    )
    journal.parent.mkdir(parents=True)
    journal.write_text(
        json.dumps({
            "transaction_id": "malformed",
            "state": state,
        }),
        encoding="utf-8",
    )

    with pytest.raises(RecoveryRequiredError):
        BrainStore.load(brain_root)
    with pytest.raises(RecoveryRequiredError):
        recover_unfinished_transaction(brain_root)

    assert json.loads(journal.read_text(encoding="utf-8"))["state"] == state


@pytest.mark.parametrize("mismatch", ["before_hash", "after_bytes"])
def test_preparation_validation_failure_leaves_no_active_poison(
    tmp_path,
    mismatch,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    live_path = _write_object(brain_root, before)
    service = _service()
    planned = service.plan((after,), request=_request(brain_root, (after,)))
    manifest = _journal_manifest(planned.manifest)
    relative_path = live_path.relative_to(brain_root).as_posix()
    after_files = {relative_path: BrainStore.object_bytes(after)}
    if mismatch == "before_hash":
        external = dict(before)
        external["title"] = "external"
        live_path.write_bytes(BrainStore.object_bytes(external))
    else:
        after_files[relative_path] = b"wrong"

    with corpus_lock(brain_root, exclusive=True):
        with pytest.raises(RuntimeError):
            apply_transaction(
                brain_root,
                manifest=manifest,
                after_files=after_files,
            )

    active = (
        brain_root
        / ".brain-local"
        / "transactions"
        / planned.manifest.transaction_id
    )
    assert not active.exists()
    assert BrainStore.load(brain_root).has(before["id"])
    current = BrainStore.load(brain_root).get(before["id"])
    next_object = dict(current)
    next_object["title"] = "next"
    result = service.apply(
        (next_object,),
        request=_request(brain_root, (next_object,)),
    )
    assert result.ok is True


@pytest.mark.parametrize("failure_point", PREPARATION_FAILURE_POINTS)
def test_private_preparation_interruption_never_publishes_partial_active(
    tmp_path,
    failure_point,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    live_path = _write_object(brain_root, before)
    service = _service()
    planned = service.plan((after,), request=_request(brain_root, (after,)))
    relative_path = live_path.relative_to(brain_root).as_posix()

    with corpus_lock(brain_root, exclusive=True):
        with pytest.raises(InjectedCrash, match=failure_point):
            apply_transaction(
                brain_root,
                manifest=_journal_manifest(planned.manifest),
                after_files={
                    relative_path: BrainStore.object_bytes(after),
                },
                preparation_injector=_crash_at(failure_point),
            )

    active = (
        brain_root
        / ".brain-local"
        / "transactions"
        / planned.manifest.transaction_id
    )
    assert not active.exists()
    assert BrainStore.load(brain_root).get(before["id"]) == before
    retried = service.apply(
        (after,),
        request=_request(brain_root, (after,)),
    )
    assert retried.ok is True


def test_different_private_attempt_ids_do_not_accumulate_and_reader_ignores_them(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before = context()
    _write_object(brain_root, before)
    service = _service()
    transaction_ids: list[str] = []

    for title in ("first attempt", "second attempt"):
        after = dict(before)
        after["title"] = title
        planned = service.plan((after,), request=_request(brain_root, (after,)))
        assert planned.manifest is not None
        transaction_ids.append(planned.manifest.transaction_id)
        relative_path = BrainStore.object_path(
            brain_root,
            after,
        ).relative_to(brain_root).as_posix()

        with pytest.raises(InjectedCrash, match="after_private_root_mkdir"):
            apply_transaction(
                brain_root,
                manifest=_journal_manifest(planned.manifest),
                after_files={
                    relative_path: BrainStore.object_bytes(after),
                },
                preparation_injector=_crash_at(
                    "after_private_root_mkdir"
                ),
            )

        assert BrainStore.load(brain_root).get(before["id"]) == before

    private_root = (
        brain_root / ".brain-local" / "preparing-transactions"
    )
    assert sorted(path.name for path in private_root.iterdir()) == [
        transaction_ids[-1]
    ]


def test_exclusive_entry_rejects_private_symlink_without_following_it(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before = context()
    _write_object(brain_root, before)
    private_root = (
        brain_root / ".brain-local" / "preparing-transactions"
    )
    private_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"keep")
    (private_root / "poison").symlink_to(
        outside,
        target_is_directory=True,
    )

    assert BrainStore.load(brain_root).get(before["id"]) == before
    with pytest.raises(RuntimeError) as caught:
        with corpus_lock(brain_root, exclusive=True):
            pass

    assert getattr(caught.value, "code", None) == (
        "private_transaction_invalid"
    )
    assert sentinel.read_bytes() == b"keep"


def test_parent_symlink_swap_after_temp_fsync_never_mutates_outside(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    live_path = _write_object(brain_root, before)
    live_parent = live_path.parent
    detached_parent = live_parent.with_name("domain-detached")
    outside_parent = tmp_path / "outside-domain"
    outside_parent.mkdir()
    outside_file = outside_parent / live_path.name
    before_bytes = BrainStore.object_bytes(before)
    outside_file.write_bytes(before_bytes)

    def swap_parent(point: str) -> None:
        if point != "after_temp_fsync":
            return
        live_parent.rename(detached_parent)
        live_parent.symlink_to(outside_parent, target_is_directory=True)

    with pytest.raises(RuntimeError):
        _service().apply(
            (after,),
            request=_request(brain_root, (after,)),
            failure_injector=swap_parent,
        )

    assert outside_file.read_bytes() == before_bytes
    assert (detached_parent / live_path.name).read_bytes() == before_bytes
    journal_paths = tuple(
        (brain_root / ".brain-local" / "transactions").rglob("journal.json")
    )
    assert len(journal_paths) == 1
    with pytest.raises(RecoveryRequiredError):
        recover_unfinished_transaction(brain_root)
    assert json.loads(journal_paths[0].read_text(encoding="utf-8"))["state"] == (
        "recovery_required"
    )


@pytest.mark.parametrize("symlink_kind", ["live_file", "parent_component"])
def test_symlink_action_path_is_rejected_before_transaction_prepare(
    tmp_path,
    symlink_kind,
):
    brain_root = tmp_path / "brain"
    outside = tmp_path / "outside"
    outside.mkdir()
    before, after = _changed_context()
    object_path = BrainStore.object_path(brain_root, before)
    if symlink_kind == "live_file":
        object_path.parent.mkdir(parents=True)
        outside_file = outside / "context.json"
        outside_file.write_bytes(BrainStore.object_bytes(before))
        object_path.symlink_to(outside_file)
    else:
        outside_domain = outside / "domain"
        outside_domain.mkdir()
        outside_file = outside_domain / object_path.name
        outside_file.write_bytes(BrainStore.object_bytes(before))
        object_path.parent.parent.mkdir(parents=True)
        object_path.parent.symlink_to(outside_domain, target_is_directory=True)
    before_bytes = outside_file.read_bytes()
    _seed_derived_files(brain_root)
    before_fingerprint = _state_fingerprint(brain_root)

    with pytest.raises(RuntimeError) as caught:
        _service().apply(
            (after,),
            request=_request(brain_root, (after,)),
        )

    assert getattr(caught.value, "code", None) == "symlink_forbidden"
    assert outside_file.read_bytes() == before_bytes
    if symlink_kind == "live_file":
        assert object_path.is_symlink()
    else:
        assert object_path.parent.is_symlink()
    assert _state_fingerprint(brain_root) == before_fingerprint
    transactions = brain_root / ".brain-local" / "transactions"
    assert not transactions.exists() or not tuple(
        transactions.rglob("journal.json")
    )


@pytest.mark.parametrize(
    "mismatch_location",
    ["existing_live", "destination_parent", "transaction_parent"],
)
def test_device_mismatch_is_rejected_before_transaction_prepare(
    tmp_path,
    monkeypatch,
    mismatch_location,
):
    brain_root = tmp_path / "brain"
    local_root = brain_root / ".brain-local"
    local_root.mkdir(parents=True)
    _seed_derived_files(brain_root)
    before, after = _changed_context()
    if mismatch_location == "destination_parent":
        destination_parent = BrainStore.object_path(brain_root, before).parent
        destination_parent.mkdir(parents=True)
        objects = (before,)
        mismatch_relative = destination_parent.relative_to(
            brain_root
        ).as_posix()
    else:
        _write_object(brain_root, before)
        objects = (after,)
        mismatch_target = (
            BrainStore.object_path(brain_root, before)
            if mismatch_location == "existing_live"
            else local_root
        )
        mismatch_relative = mismatch_target.relative_to(
            brain_root
        ).as_posix()
    before_fingerprint = _state_fingerprint(brain_root)

    def fake_observed_device(
        relative_path: str,
        actual_device: int,
    ) -> int:
        if relative_path == mismatch_relative:
            return actual_device + 1
        return actual_device

    monkeypatch.setattr(
        corpus_io,
        "_observed_device",
        fake_observed_device,
    )

    with pytest.raises(RuntimeError) as caught:
        _service().apply(
            objects,
            request=_request(brain_root, objects),
        )

    assert getattr(caught.value, "code", None) == "filesystem_mismatch"
    assert _state_fingerprint(brain_root) == before_fingerprint
    transactions = brain_root / ".brain-local" / "transactions"
    assert not transactions.exists() or not tuple(
        transactions.rglob("journal.json")
    )


def test_apply_handles_create_update_delete_and_rename_actions(tmp_path):
    service = _service()
    brain_root = tmp_path / "brain"
    old_term = candidate_term("g.neutral.old")
    old_context = context(glossary_term_ids=[old_term["id"]])
    _write_object(brain_root, old_term)
    _write_object(brain_root, old_context)
    new_term = candidate_term("g.neutral.new")
    new_context = dict(old_context)
    new_context["title"] = "updated"
    new_context["glossary_term_ids"] = [new_term["id"]]
    objects = (new_context, new_term)
    request = MutationRequest(
        operation=MutationOperation.CONTEXT_REPLACE,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=objects,
        delete_ids=(old_term["id"],),
    )

    changed = service.apply(objects, request=request)

    assert changed.ok is True
    store = BrainStore.load(brain_root)
    assert store.get(new_context["id"]) == new_context
    assert store.get(new_term["id"]) == new_term
    assert not store.has(old_term["id"])

    legacy_root = tmp_path / "legacy-brain"
    legacy = context()
    legacy["id"] = "context.Legacy"
    canonical = dict(legacy)
    canonical["id"] = "context.neutral"
    _write_object(legacy_root, legacy)
    rename_request = MutationRequest(
        operation=MutationOperation.ID_ONLY_MIGRATION,
        brain_root=legacy_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=(canonical,),
        delete_ids=(legacy["id"],),
    )

    renamed = service.apply((canonical,), request=rename_request)

    assert renamed.ok is True
    renamed_store = BrainStore.load(legacy_root)
    assert renamed_store.get(canonical["id"]) == canonical
    assert not renamed_store.has(legacy["id"])


def test_case_only_rename_commits_exact_new_spelling_on_apfs(tmp_path):
    """Removing exact-entry handling must fail this APFS transaction."""
    (
        brain_root,
        old,
        new,
        request,
        planned,
        old_path,
        new_path,
    ) = _case_only_migration(tmp_path)
    before_fingerprint = _state_fingerprint(brain_root)

    result = _service().apply((new,), request=request)

    assert result.ok is True
    assert _state_fingerprint(brain_root) != before_fingerprint
    assert new_path.name in _exact_child_names(new_path.parent)
    assert old_path.name not in _exact_child_names(old_path.parent)
    assert new_path.read_bytes() == BrainStore.object_bytes(new)
    assert BrainStore.load(brain_root).get(new["id"]) == new
    assert not BrainStore.load(brain_root).has(old["id"])
    assert planned.manifest.expected_after_fingerprint == corpus_io._corpus_fingerprint(
        brain_root
    )
    assert not (brain_root / ".brain-local" / "index.db").exists()


@pytest.mark.parametrize(
    "failure_point",
    FAILURE_POINTS,
)
def test_case_only_rename_recovery_restores_old_exact_spelling(tmp_path, failure_point):
    """Changing rollback order to old-first must lose the restored APFS name."""
    (
        brain_root,
        old,
        new,
        request,
        planned,
        old_path,
        new_path,
    ) = _case_only_migration(tmp_path)
    before_fingerprint = _state_fingerprint(brain_root)

    with pytest.raises(InjectedCrash, match=failure_point):
        _service().apply(
            (new,),
            request=request,
            failure_injector=_crash_at(failure_point),
        )

    recovered = recover_unfinished_transaction(brain_root)

    assert recovered.recovered_transaction_ids == (planned.manifest.transaction_id,)
    assert _state_fingerprint(brain_root) == before_fingerprint
    assert old_path.name in _exact_child_names(old_path.parent)
    assert new_path.name not in _exact_child_names(new_path.parent)
    assert old_path.read_bytes() == BrainStore.object_bytes(old)
    assert not BrainStore.load(brain_root).has(new["id"])
    journal = json.loads(
        (
            brain_root
            / ".brain-local"
            / "transactions"
            / planned.manifest.transaction_id
            / "journal.json"
        ).read_text(encoding="utf-8")
    )
    assert journal["state"] == "rolled_back"


def test_next_mutation_recovers_case_only_rename_without_roll_forward(tmp_path):
    """Skipping recovery before the next apply would leave the new spelling live."""
    (
        brain_root,
        old,
        new,
        request,
        planned,
        old_path,
        new_path,
    ) = _case_only_migration(tmp_path)
    before_fingerprint = _state_fingerprint(brain_root)

    with pytest.raises(InjectedCrash, match="after_first_live_replace"):
        _service().apply(
            (new,),
            request=request,
            failure_injector=_crash_at("after_first_live_replace"),
        )

    assert _service().apply(
        (),
        request=_request(
            brain_root,
            (),
            operation=MutationOperation.PROJECTION,
        ),
    ).ok
    assert _state_fingerprint(brain_root) == before_fingerprint
    assert old_path.name in _exact_child_names(old_path.parent)
    assert new_path.name not in _exact_child_names(new_path.parent)
    assert old_path.read_bytes() == BrainStore.object_bytes(old)
    journal = json.loads(
        (
            brain_root
            / ".brain-local"
            / "transactions"
            / planned.manifest.transaction_id
            / "journal.json"
        ).read_text(encoding="utf-8")
    )
    assert journal["state"] == "rolled_back"


def test_multi_case_only_rename_rejects_second_inode_swap_before_move(tmp_path):
    """Removing per-old revalidation accepts an unseen later inode swap."""
    brain_root, _request, planned, pairs = _case_only_multi_migration(
        tmp_path,
        count=2,
    )
    before_fingerprint = _state_fingerprint(brain_root)
    manifest = _journal_manifest(planned.manifest)
    after_files = {
        rename["new_path"]: BrainStore.object_bytes(new)
        for rename, (_old_path, _new_path, _old, new) in zip(
            planned.manifest.renames,
            pairs,
            strict=True,
        )
    }
    second_old_path = pairs[1][0]
    initial_inode = second_old_path.stat().st_ino

    def replace_second_after_first_move(point: str) -> None:
        if point != "after_first_before_rename":
            return
        replacement = second_old_path.with_name(".same-bytes-new-inode")
        replacement.write_bytes(second_old_path.read_bytes())
        os.replace(replacement, second_old_path)
        assert second_old_path.stat().st_ino != initial_inode

    with pytest.raises(CorpusIOError, match="path_binding_changed"):
        apply_transaction(
            brain_root,
            manifest=manifest,
            after_files=after_files,
            failure_injector=replace_second_after_first_move,
        )

    assert _state_fingerprint(brain_root) == before_fingerprint
    for old_path, new_path, old, _new in pairs:
        assert old_path.name in _exact_child_names(old_path.parent)
        assert new_path.name not in _exact_child_names(new_path.parent)
        assert old_path.read_bytes() == BrainStore.object_bytes(old)
    journal = json.loads(
        (
            brain_root
            / ".brain-local"
            / "transactions"
            / planned.manifest.transaction_id
            / "journal.json"
        ).read_text(encoding="utf-8")
    )
    assert journal["state"] == "rolled_back"


def test_three_case_only_renames_commit_exact_new_spellings(tmp_path):
    """Treating a three-pair transaction as one alias loses a Jira-like rename."""
    brain_root, request, planned, pairs = _case_only_multi_migration(tmp_path)

    result = _service().apply(
        tuple(new for _old_path, _new_path, _old, new in pairs),
        request=request,
    )

    assert result.ok is True
    assert len(planned.manifest.renames) == 3
    for old_path, new_path, old, new in pairs:
        assert old_path.name not in _exact_child_names(old_path.parent)
        assert new_path.name in _exact_child_names(new_path.parent)
        assert new_path.read_bytes() == BrainStore.object_bytes(new)
        assert not BrainStore.load(brain_root).has(old["id"])
        assert BrainStore.load(brain_root).get(new["id"]) == new


@pytest.mark.parametrize(
    "failure_point",
    ("after_first_before_rename", "after_first_live_replace"),
)
def test_three_case_only_renames_recover_major_crashes(tmp_path, failure_point):
    """Rollback must restore every exact old entry in a Jira-shaped batch."""
    brain_root, request, planned, pairs = _case_only_multi_migration(tmp_path)
    before_fingerprint = _state_fingerprint(brain_root)

    with pytest.raises(InjectedCrash, match=failure_point):
        _service().apply(
            tuple(new for _old_path, _new_path, _old, new in pairs),
            request=request,
            failure_injector=_crash_at(failure_point),
        )

    recover_unfinished_transaction(brain_root)

    assert _state_fingerprint(brain_root) == before_fingerprint
    for old_path, new_path, old, _new in pairs:
        assert old_path.name in _exact_child_names(old_path.parent)
        assert new_path.name not in _exact_child_names(new_path.parent)
        assert old_path.read_bytes() == BrainStore.object_bytes(old)
    journal = json.loads(
        (
            brain_root
            / ".brain-local"
            / "transactions"
            / planned.manifest.transaction_id
            / "journal.json"
        ).read_text(encoding="utf-8")
    )
    assert journal["state"] == "rolled_back"


def test_folded_rename_with_genuinely_absent_new_lookup_stays_general(tmp_path, monkeypatch):
    """Forcing a special binding for an absent new lookup breaks normal rename."""
    brain_root, _request, planned, pairs = _case_only_multi_migration(
        tmp_path,
        count=1,
    )
    old_path, new_path, old, new = pairs[0]
    relative_new_path = planned.manifest.renames[0]["new_path"]
    original_file_stat = corpus_io._file_stat_at
    original_inspect = corpus_io._AnchoredRoot.inspect_file

    def absent_new_lookup(parent_fd: int, name: str):
        if name == new_path.name:
            return None
        return original_file_stat(parent_fd, name)

    def inspect_with_absent_new_lookup(anchored, relative_path: str):
        if relative_path == relative_new_path:
            return {
                "path": relative_path,
                "had_before": False,
                "before_sha256": None,
            }
        return original_inspect(anchored, relative_path)

    monkeypatch.setattr(corpus_io, "_file_stat_at", absent_new_lookup)
    monkeypatch.setattr(
        corpus_io._AnchoredRoot,
        "inspect_file",
        inspect_with_absent_new_lookup,
    )
    with corpus_io._AnchoredRoot(brain_root) as anchored:
        assert corpus_io._inspect_case_only_renames(
            anchored,
            _journal_manifest(planned.manifest),
        ) == ()
    manifest, after_files = _case_only_apply_inputs(planned, new)
    apply_transaction(brain_root, manifest=manifest, after_files=after_files)
    assert new_path.name in _exact_child_names(new_path.parent)
    assert old_path.name not in _exact_child_names(old_path.parent)

    recovery_root, _recovery_request, recovery_plan, recovery_pairs = (
        _case_only_multi_migration(tmp_path / "recovery", count=1)
    )
    recovery_old_path, recovery_new_path, recovery_old, recovery_new = recovery_pairs[0]
    recovery_relative_new = recovery_plan.manifest.renames[0]["new_path"]

    def inspect_recovery_with_absent_new_lookup(anchored, relative_path: str):
        if relative_path == recovery_relative_new:
            return {
                "path": relative_path,
                "had_before": False,
                "before_sha256": None,
            }
        return original_inspect(anchored, relative_path)

    monkeypatch.setattr(
        corpus_io._AnchoredRoot,
        "inspect_file",
        inspect_recovery_with_absent_new_lookup,
    )
    recovery_manifest, recovery_after_files = _case_only_apply_inputs(
        recovery_plan,
        recovery_new,
    )
    with pytest.raises(InjectedCrash, match="after_first_live_replace"):
        apply_transaction(
            recovery_root,
            manifest=recovery_manifest,
            after_files=recovery_after_files,
            failure_injector=_crash_at("after_first_live_replace"),
        )
    recover_unfinished_transaction(recovery_root)
    assert recovery_old_path.name in _exact_child_names(recovery_old_path.parent)
    assert recovery_new_path.name not in _exact_child_names(recovery_new_path.parent)
    assert recovery_old_path.read_bytes() == BrainStore.object_bytes(recovery_old)
    assert old_path.name not in _exact_child_names(old_path.parent)
    assert new_path.read_bytes() == BrainStore.object_bytes(new)


def test_case_only_rename_rejects_exact_new_entry_collision(tmp_path):
    """Dropping exact new-name collision checks would overwrite a live file."""
    (
        brain_root,
        _old,
        new,
        request,
        _planned,
        old_path,
        new_path,
    ) = _case_only_migration(tmp_path)
    old_payload = old_path.read_bytes()
    # APFS cannot host the case-only second entry, so an exact test seam is
    # needed for the collision matrix; production must reject it before write.
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            corpus_io,
            "_exact_name_exists_at",
            lambda _fd, name: name == new_path.name or name == old_path.name,
        )
        with pytest.raises(CorpusIOError, match="case_only_rename_collision"):
            _service().apply((new,), request=request)

    assert old_path.read_bytes() == old_payload


def test_case_only_rename_rejects_hard_linked_before_image(tmp_path):
    """Removing link-count validation would make rollback target ambiguous."""
    (
        brain_root,
        _old,
        new,
        _request,
        planned,
        old_path,
        _new_path,
    ) = _case_only_migration(tmp_path)
    sibling = old_path.with_name("unrelated-hard-link.json")
    os.link(old_path, sibling)

    with pytest.raises(CorpusIOError, match="case_only_rename_ambiguous"):
        apply_transaction(
            brain_root,
            manifest=_journal_manifest(planned.manifest),
            after_files={
                planned.manifest.renames[0]["new_path"]: BrainStore.object_bytes(
                    new
                )
            },
        )

    assert old_path.read_bytes() == sibling.read_bytes()


def test_exact_name_helper_does_not_treat_apfs_lookup_alias_as_entry(tmp_path):
    """Replacing enumeration with stat lookup would claim both spellings exist."""
    (
        _brain_root,
        _old,
        _new,
        _request,
        _planned,
        old_path,
        new_path,
    ) = _case_only_migration(tmp_path)
    extra = old_path.with_name("zzz-unrelated-entry")
    extra.write_bytes(b"unrelated")
    parent_fd = os.open(old_path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert corpus_io._exact_name_exists_at(parent_fd, old_path.name)
        assert not corpus_io._exact_name_exists_at(parent_fd, new_path.name)
        assert corpus_io._exact_names_at(parent_fd) == tuple(
            sorted((old_path.name, extra.name))
        )
    finally:
        os.close(parent_fd)


def test_case_only_rename_rejects_normalization_equivalent_entry_set(tmp_path):
    """Accepting a second folded entry would make exact restore non-unique."""
    (
        brain_root,
        _old,
        new,
        request,
        _planned,
        old_path,
        new_path,
    ) = _case_only_migration(tmp_path)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            corpus_io,
            "_exact_names_at",
            lambda _fd: (old_path.name, new_path.name.swapcase()),
        )
        with pytest.raises(CorpusIOError, match="case_only_rename_ambiguous"):
            _service().apply((new,), request=request)

    assert old_path.name in _exact_child_names(old_path.parent)


def test_case_only_rename_rejects_raw_content_change_before_journal(tmp_path):
    """Dropping raw receipt revalidation would commit a changed before image."""
    (
        brain_root,
        _old,
        new,
        _request,
        planned,
        old_path,
        _new_path,
    ) = _case_only_migration(tmp_path)
    manifest, after_files = _case_only_apply_inputs(planned, new)
    old_path.write_bytes(old_path.read_bytes() + b" ")

    with pytest.raises(CorpusIOError, match="before_hash_mismatch"):
        apply_transaction(brain_root, manifest=manifest, after_files=after_files)

    assert not (brain_root / ".brain-local" / "transactions").exists()


def test_case_only_rename_rejects_same_content_inode_swap_before_snapshot(
    tmp_path,
    monkeypatch,
):
    """Ignoring the captured inode would accept a same-byte replacement."""
    (
        brain_root,
        _old,
        new,
        _request,
        planned,
        old_path,
        _new_path,
    ) = _case_only_migration(tmp_path)
    manifest, after_files = _case_only_apply_inputs(planned, new)
    original_verify = corpus_io._verify_live_bindings
    swapped = False

    def swap_after_temp(anchored, live_parents):
        nonlocal swapped
        original_verify(anchored, live_parents)
        if swapped:
            return
        swapped = True
        replacement = old_path.with_name(".same-content-replacement")
        replacement.write_bytes(old_path.read_bytes())
        os.replace(replacement, old_path)

    monkeypatch.setattr(corpus_io, "_verify_live_bindings", swap_after_temp)
    with pytest.raises(CorpusIOError, match="path_binding_changed"):
        apply_transaction(brain_root, manifest=manifest, after_files=after_files)


@pytest.mark.parametrize("entry_kind", ("symlink", "fifo"))
def test_case_only_rename_rejects_non_regular_exact_old_entry(tmp_path, entry_kind):
    """Following a special or linked old leaf would escape the transaction gate."""
    (
        brain_root,
        _old,
        new,
        _request,
        planned,
        old_path,
        _new_path,
    ) = _case_only_migration(tmp_path)
    manifest, after_files = _case_only_apply_inputs(planned, new)
    old_path.unlink()
    if entry_kind == "symlink":
        outside = tmp_path / "outside"
        outside.write_bytes(b"outside")
        old_path.symlink_to(outside)
    else:
        os.mkfifo(old_path)

    with pytest.raises(CorpusIOError, match="symlink_forbidden|file_type_invalid"):
        apply_transaction(brain_root, manifest=manifest, after_files=after_files)


@pytest.mark.parametrize("failure_point", FAILURE_POINTS)
def test_next_mutation_rolls_back_every_injected_crash_without_roll_forward(
    tmp_path,
    failure_point,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    _seed_derived_files(brain_root)
    before_fingerprint = _state_fingerprint(brain_root)
    planned = _service().plan(
        (after,),
        request=_request(brain_root, (after,)),
    )

    with pytest.raises(InjectedCrash, match=failure_point):
        _service().apply(
            (after,),
            request=_request(brain_root, (after,)),
            failure_injector=_crash_at(failure_point),
        )

    empty_request = _request(
        brain_root,
        (),
        operation=MutationOperation.PROJECTION,
    )
    result = _service().apply((), request=empty_request)

    assert result.ok is True
    assert _state_fingerprint(brain_root) == before_fingerprint
    assert BrainStore.load(brain_root).get(before["id"])["title"] == before["title"]
    journal_path = (
        brain_root
        / ".brain-local"
        / "transactions"
        / planned.manifest.transaction_id
        / "journal.json"
    )
    assert json.loads(journal_path.read_text(encoding="utf-8"))["state"] == "rolled_back"


@pytest.mark.parametrize("failure_point", FAILURE_POINTS)
def test_id_migration_rolls_object_eval_and_derived_back_together(
    tmp_path,
    failure_point,
):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy display",
    )
    new = dict(old)
    new["id"] = "code.neutral.legacy"
    _write_object(brain_root, old)
    eval_before = (
        b'{"scenarios":[{"id":"s","query":"q","expect":'
        b'{"top5_any":["code.Legacy"]}}]}\n'
    )
    eval_after = (
        b'{"scenarios":[{"expect":{"top5_any":["code.neutral.legacy"]},'
        b'"id":"s","query":"q"}]}\n'
    )
    (brain_root / "eval_scenarios.json").write_bytes(eval_before)
    _seed_derived_files(brain_root)
    update = _auxiliary_update(eval_before, eval_after)
    request = MutationRequest(
        operation=MutationOperation.ID_ONLY_MIGRATION,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=(new,),
        delete_ids=(old["id"],),
        auxiliary_updates=(update,),
    )
    before_fingerprint = _state_fingerprint(brain_root)

    with pytest.raises(InjectedCrash, match=failure_point):
        _service().apply(
            (new,),
            request=request,
            failure_injector=_crash_at(failure_point),
        )

    recovery_request = _request(
        brain_root,
        (),
        operation=MutationOperation.PROJECTION,
    )
    assert _service().apply((), request=recovery_request).ok is True
    assert _state_fingerprint(brain_root) == before_fingerprint
    assert BrainStore.load(brain_root).has(old["id"])
    assert not BrainStore.load(brain_root).has(new["id"])
    assert (brain_root / "eval_scenarios.json").read_bytes() == eval_before


def test_id_migration_commits_object_eval_and_derived_together(tmp_path):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy display",
    )
    new = dict(old)
    new["id"] = "code.neutral.legacy"
    _write_object(brain_root, old)
    eval_before = b'{"scenarios":[{"expect":{"top5_any":["code.Legacy"]}}]}\n'
    eval_after = b'{"scenarios":[{"expect":{"top5_any":["code.neutral.legacy"]}}]}\n'
    (brain_root / "eval_scenarios.json").write_bytes(eval_before)
    _seed_derived_files(brain_root)
    update = _auxiliary_update(eval_before, eval_after)
    request = MutationRequest(
        operation=MutationOperation.ID_ONLY_MIGRATION,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=(new,),
        delete_ids=(old["id"],),
        auxiliary_updates=(update,),
    )

    result = _service().apply((new,), request=request)

    assert result.ok is True
    assert BrainStore.load(brain_root).has(new["id"])
    assert not BrainStore.load(brain_root).has(old["id"])
    assert (brain_root / "eval_scenarios.json").read_bytes() == eval_after
    assert not (brain_root / ".brain-local" / "index.db").exists()
    assert not (brain_root / ".brain-local" / "stale-set.json").exists()


def test_transaction_rejects_missing_or_unexpected_auxiliary_after_bytes(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    before = b"{}\n"
    after = b'{"scenarios":[]}\n'
    (brain_root / "eval_scenarios.json").write_bytes(before)
    update = _auxiliary_update(before, after)
    request = MutationRequest(
        operation=MutationOperation.ID_ONLY_MIGRATION,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=(),
        auxiliary_updates=(update,),
    )
    planned = _service().plan((), request=request)
    assert planned.ok is True

    with pytest.raises(corpus_io.CorpusIOError) as missing:
        apply_transaction(
            brain_root,
            manifest=_journal_manifest(planned.manifest),
            after_files={},
        )
    assert missing.value.code == "after_payload_invalid"

    with pytest.raises(corpus_io.CorpusIOError) as unexpected:
        apply_transaction(
            brain_root,
            manifest=_journal_manifest(planned.manifest),
            after_files={
                "eval_scenarios.json": after,
                "unexpected.json": b"unexpected",
            },
        )
    assert unexpected.value.code == "after_payload_invalid"
    assert (brain_root / "eval_scenarios.json").read_bytes() == before


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        (
            lambda manifest: manifest.update(operation="ingest"),
            "allowed only for id_only_migration",
        ),
        (
            lambda manifest: manifest["auxiliary_updates"][0].update(
                path="other.json",
            ),
            "path is invalid",
        ),
        (
            lambda manifest: manifest["auxiliary_updates"][0].update(
                path="../eval_scenarios.json",
            ),
            "stay below brain_root",
        ),
        (
            lambda manifest: manifest["auxiliary_updates"][0].update(
                before_sha256=None,
            ),
            "before_sha256 is invalid",
        ),
    ],
)
def test_low_level_manifest_auxiliary_allowlist_fails_closed(
    tmp_path,
    mutation,
    expected_message,
):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    before = b"{}\n"
    after = b'{"scenarios":[]}\n'
    (brain_root / "eval_scenarios.json").write_bytes(before)
    update = _auxiliary_update(before, after)
    request = MutationRequest(
        operation=MutationOperation.ID_ONLY_MIGRATION,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=(),
        auxiliary_updates=(update,),
    )
    planned = _service().plan((), request=request)
    manifest = _journal_manifest(planned.manifest)
    mutation(manifest)

    with pytest.raises(ValueError, match=expected_message):
        apply_transaction(
            brain_root,
            manifest=manifest,
            after_files={"eval_scenarios.json": after},
        )
    assert (brain_root / "eval_scenarios.json").read_bytes() == before


def test_low_level_manifest_rejects_auxiliary_noop_without_invalidation(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    unchanged = b'{"scenarios":[]}\n'
    (brain_root / "eval_scenarios.json").write_bytes(unchanged)
    _seed_derived_files(brain_root)
    update = _auxiliary_update(
        unchanged,
        b'{"scenarios":[{"id":"s","query":"q","expect":'
        b'{"no_answer":true}}]}\n',
    )
    request = MutationRequest(
        operation=MutationOperation.ID_ONLY_MIGRATION,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=(),
        auxiliary_updates=(update,),
    )
    planned = _service().plan((), request=request)
    manifest = _journal_manifest(planned.manifest)
    action = manifest["auxiliary_updates"][0]
    action["after_sha256"] = action["before_sha256"]

    with pytest.raises(ValueError, match="must change content"):
        apply_transaction(
            brain_root,
            manifest=manifest,
            after_files={"eval_scenarios.json": unchanged},
        )

    assert (brain_root / "eval_scenarios.json").read_bytes() == unchanged
    assert (brain_root / ".brain-local" / "index.db").read_bytes() == b"index"
    assert (
        brain_root / ".brain-local" / "stale-set.json"
    ).read_bytes() == b'{"stale":true}\n'
    assert not (brain_root / ".brain-local" / "transactions").exists()
    assert not (
        brain_root / ".brain-local" / "preparing-transactions"
    ).exists()


def test_reader_fails_closed_while_unfinished_journal_exists(tmp_path):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)

    with pytest.raises(InjectedCrash):
        _service().apply(
            (after,),
            request=_request(brain_root, (after,)),
            failure_injector=_crash_at("after_first_live_replace"),
        )

    with pytest.raises(RecoveryRequiredError):
        BrainStore.load(brain_root)
    assert BrainStore.load_unlocked(brain_root).get(before["id"])["title"] == "changed"


def test_reader_waits_for_writer_and_never_observes_partial_corpus(tmp_path):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    writer_inside_partial_state = threading.Event()
    release_writer = threading.Event()
    reader_done = threading.Event()
    errors: list[BaseException] = []
    reader_titles: list[str] = []

    def inject(point: str) -> None:
        if point == "after_first_before_rename":
            writer_inside_partial_state.set()
            if not release_writer.wait(timeout=5):
                raise AssertionError("reader visibility test timed out")

    def run_writer() -> None:
        try:
            _service().apply(
                (after,),
                request=_request(brain_root, (after,)),
                failure_injector=inject,
            )
        except BaseException as exc:
            errors.append(exc)

    def run_reader() -> None:
        try:
            reader_titles.append(
                BrainStore.load(brain_root).get(before["id"])["title"]
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            reader_done.set()

    writer = threading.Thread(target=run_writer)
    writer.start()
    assert writer_inside_partial_state.wait(timeout=5)
    reader = threading.Thread(target=run_reader)
    reader.start()
    assert not reader_done.wait(timeout=0.2)

    release_writer.set()
    writer.join(timeout=5)
    reader.join(timeout=5)

    assert not writer.is_alive()
    assert not reader.is_alive()
    assert errors == []
    assert reader_titles == ["changed"]


def test_corpus_lock_remains_exclusive_across_root_inode_swap(tmp_path):
    brain_root = tmp_path / "brain"
    brain_root.mkdir()
    backup = tmp_path / "backup"
    reader_started = threading.Event()
    reader_acquired = threading.Event()
    reader_errors: list[BaseException] = []

    def run_reader() -> None:
        reader_started.set()
        try:
            with corpus_lock(brain_root, exclusive=False):
                reader_acquired.set()
        except BaseException as exc:
            reader_errors.append(exc)

    with corpus_lock(brain_root, exclusive=True):
        brain_root.rename(backup)
        brain_root.mkdir()
        reader = threading.Thread(target=run_reader)
        reader.start()
        assert reader_started.wait(timeout=5)
        assert not reader_acquired.wait(timeout=0.2)

    reader.join(timeout=5)
    assert not reader.is_alive()
    assert reader_errors == []
    assert reader_acquired.is_set()


def test_transaction_temp_and_before_images_share_live_filesystem(tmp_path):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    planned = _service().plan(
        (after,),
        request=_request(brain_root, (after,)),
    )

    with pytest.raises(InjectedCrash):
        _service().apply(
            (after,),
            request=_request(brain_root, (after,)),
            failure_injector=_crash_at("after_journal_prepared"),
        )

    transaction_root = (
        brain_root
        / ".brain-local"
        / "transactions"
        / planned.manifest.transaction_id
    )
    live_device = brain_root.stat().st_dev
    assert (transaction_root / "temp").is_dir()
    assert (transaction_root / "before").is_dir()
    assert (transaction_root / "snapshots").is_dir()
    assert {
        path.stat().st_dev
        for path in transaction_root.rglob("*")
    } == {live_device}


def test_recovery_failure_is_persisted_and_requires_manual_intervention(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    planned = _service().plan(
        (after,),
        request=_request(brain_root, (after,)),
    )

    with pytest.raises(InjectedCrash):
        _service().apply(
            (after,),
            request=_request(brain_root, (after,)),
            failure_injector=_crash_at("after_first_live_replace"),
        )

    transaction_root = (
        brain_root
        / ".brain-local"
        / "transactions"
        / planned.manifest.transaction_id
    )
    for root_name in ("before", "snapshots"):
        for path in (transaction_root / root_name).rglob("*"):
            if path.is_file():
                path.unlink()

    with pytest.raises(RecoveryRequiredError):
        recover_unfinished_transaction(brain_root)

    journal = json.loads(
        (transaction_root / "journal.json").read_text(encoding="utf-8")
    )
    assert journal["state"] == "recovery_required"


def test_explicit_recovery_reports_all_rolled_back_transactions(tmp_path):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    planned = _service().plan(
        (after,),
        request=_request(brain_root, (after,)),
    )
    with pytest.raises(InjectedCrash):
        _service().apply(
            (after,),
            request=_request(brain_root, (after,)),
            failure_injector=_crash_at("after_state_committing"),
        )

    result = recover_unfinished_transaction(brain_root)

    assert result.recovered_transaction_ids == (
        planned.manifest.transaction_id,
    )
    assert BrainStore.load(brain_root).get(before["id"]) == before
