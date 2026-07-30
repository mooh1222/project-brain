from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict
from pathlib import Path

import pytest

import project_brain.corpus_io as corpus_io
from project_brain.corpus_io import (
    CorpusIOError,
    JournalState,
    RecoveryRequiredError,
    apply_transaction,
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
from tests.test_ingest import candidate_term, context
from tests.test_mutation import _code_locator


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


class InjectedCrash(RuntimeError):
    pass


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
) -> MutationRequest:
    return MutationRequest(
        operation=MutationOperation.INGEST,
        brain_root=brain_root,
        repo_context=None,
        engine_sha="e" * 40,
        objects=objects,
        batch_binding=batch_binding,
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
    planned = MutationService().plan((new,), request=request)
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
    return (
        asdict(planned.manifest),
        {rename["new_path"]: BrainStore.object_bytes(new)},
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
    planned = MutationService().plan(tuple(new_objects), request=request)
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
    result = MutationService().apply(
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
    followup = MutationService().apply(
        (newer,),
        request=_request(brain_root, (newer,)),
    )
    assert followup.ok and followup.manifest is not None
    assert followup.manifest.batch_binding is None


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
    result = MutationService().apply(
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
    followup = MutationService().apply(
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
    result = MutationService().apply(
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
        MutationService().apply(
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
        MutationService().apply(
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


def test_committed_receipt_rejects_forged_envelope_and_intent(tmp_path):
    brain_root = tmp_path / "brain"
    before, after = _changed_context()
    _write_object(brain_root, before)
    binding = _batch_binding(brain_root=brain_root)
    result = MutationService().apply(
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
    service = MutationService()

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
    service = MutationService()
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
    MutationService().apply(
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
    MutationService().apply(
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
    MutationService().apply(
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
    service = MutationService()
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
                manifest=asdict(planned.manifest),
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
    service = MutationService()
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
        MutationService().apply(
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

    result = MutationService().apply(
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

    result = MutationService().apply(
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
    service = MutationService()

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
    service = MutationService()
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
    service = MutationService()
    planned = service.plan((after,), request=_request(brain_root, (after,)))
    manifest = asdict(planned.manifest)
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
    service = MutationService()
    planned = service.plan((after,), request=_request(brain_root, (after,)))
    relative_path = live_path.relative_to(brain_root).as_posix()

    with corpus_lock(brain_root, exclusive=True):
        with pytest.raises(InjectedCrash, match=failure_point):
            apply_transaction(
                brain_root,
                manifest=asdict(planned.manifest),
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
    service = MutationService()
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
                manifest=asdict(planned.manifest),
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
        MutationService().apply(
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
        MutationService().apply(
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
        MutationService().apply(
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
    service = MutationService()
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
        operation=MutationOperation.INGEST,
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

    result = MutationService().apply((new,), request=request)

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
        MutationService().apply(
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
        MutationService().apply(
            (new,),
            request=request,
            failure_injector=_crash_at("after_first_live_replace"),
        )

    assert MutationService().apply((), request=_request(brain_root, ())).ok
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
    manifest = asdict(planned.manifest)
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

    result = MutationService().apply(
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
        MutationService().apply(
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
            asdict(planned.manifest),
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
            MutationService().apply((new,), request=request)

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
            manifest=asdict(planned.manifest),
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
            MutationService().apply((new,), request=request)

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
    planned = MutationService().plan(
        (after,),
        request=_request(brain_root, (after,)),
    )

    with pytest.raises(InjectedCrash, match=failure_point):
        MutationService().apply(
            (after,),
            request=_request(brain_root, (after,)),
            failure_injector=_crash_at(failure_point),
        )

    empty_request = _request(brain_root, ())
    result = MutationService().apply((), request=empty_request)

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
        MutationService().apply(
            (new,),
            request=request,
            failure_injector=_crash_at(failure_point),
        )

    recovery_request = _request(brain_root, ())
    assert MutationService().apply((), request=recovery_request).ok is True
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

    result = MutationService().apply((new,), request=request)

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
    planned = MutationService().plan((), request=request)
    assert planned.ok is True

    with pytest.raises(corpus_io.CorpusIOError) as missing:
        apply_transaction(
            brain_root,
            manifest=asdict(planned.manifest),
            after_files={},
        )
    assert missing.value.code == "after_payload_invalid"

    with pytest.raises(corpus_io.CorpusIOError) as unexpected:
        apply_transaction(
            brain_root,
            manifest=asdict(planned.manifest),
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
    planned = MutationService().plan((), request=request)
    manifest = asdict(planned.manifest)
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
    planned = MutationService().plan((), request=request)
    manifest = asdict(planned.manifest)
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
        MutationService().apply(
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
            MutationService().apply(
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
    planned = MutationService().plan(
        (after,),
        request=_request(brain_root, (after,)),
    )

    with pytest.raises(InjectedCrash):
        MutationService().apply(
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
    planned = MutationService().plan(
        (after,),
        request=_request(brain_root, (after,)),
    )

    with pytest.raises(InjectedCrash):
        MutationService().apply(
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
    planned = MutationService().plan(
        (after,),
        request=_request(brain_root, (after,)),
    )
    with pytest.raises(InjectedCrash):
        MutationService().apply(
            (after,),
            request=_request(brain_root, (after,)),
            failure_injector=_crash_at("after_state_committing"),
        )

    result = recover_unfinished_transaction(brain_root)

    assert result.recovered_transaction_ids == (
        planned.manifest.transaction_id,
    )
    assert BrainStore.load(brain_root).get(before["id"]) == before
