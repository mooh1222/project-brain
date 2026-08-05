from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import fields, replace
from pathlib import Path
from unittest import mock

import pytest

from project_brain.migration import (
    MigrationError,
    MigrationRow,
    apply_migration_artifact,
    canonical_payload_hash_pair,
    create_migration_artifact,
    plan_display_migration,
    plan_id_migration,
    trusted_migration_context,
    validate_live_snapshot_corpus,
    validate_snapshot_binding,
)
from project_brain.mutation import corpus_fingerprint
from project_brain.store import BrainStore
from project_brain.snapshot import SnapshotVerification
from tests.test_ingest import (
    candidate_term,
    context,
    evidence_ref,
    manifest,
    review_record_for,
)
from tests.test_mutation import _code_locator, _write_raw


SNAPSHOT_ID = "trusted-before-id-migration"
SNAPSHOT_SHA = "a" * 64
ENGINE_SHA = "e" * 40


def test_promoted_migration_context_helpers_preserve_the_trusted_contract(
    tmp_path,
):
    brain_root = (tmp_path / "brain").resolve()
    _write_raw(brain_root, context())
    existing = BrainStore.load(brain_root)
    snapshot, repo_root, engine_root, engine_head = _trusted_snapshot_for(
        brain_root,
    )

    validate_snapshot_binding(snapshot)
    repo_context = trusted_migration_context(
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        engine_sha=engine_head,
        snapshot=snapshot,
    )
    validate_live_snapshot_corpus(existing, snapshot)

    assert repo_context.repo_root == repo_root
    assert repo_context.target_revision_sha == snapshot.repo_head


def _snapshot_verification(
    *,
    snapshot_id: str = SNAPSHOT_ID,
    manifest_sha256: str = SNAPSHOT_SHA,
    repo_head: str = "b" * 40,
    engine_head: str = ENGINE_SHA,
    corpus_fingerprint_value: str = "c" * 64,
) -> SnapshotVerification:
    return SnapshotVerification(
        ok=True,
        snapshot_id=snapshot_id,
        manifest_sha256=manifest_sha256,
        file_count=1,
        repo_head=repo_head,
        engine_head=engine_head,
        corpus_fingerprint=corpus_fingerprint_value,
    )


def _git_repo(root: Path) -> str:
    root.mkdir(parents=True, exist_ok=True)
    if (root / ".git").is_dir():
        return subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "migration@test.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Migration Test"],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "fixture",
        ],
        check=True,
    )
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _migration_roots(
    brain_root: Path,
) -> tuple[Path, Path, str, str]:
    repo_root = brain_root.parent.resolve()
    engine_root = (repo_root / "engine-fixture").resolve()
    repo_head = _git_repo(repo_root)
    engine_head = _git_repo(engine_root)
    return repo_root, engine_root, repo_head, engine_head


def _trusted_snapshot_for(
    brain_root: Path,
    *,
    snapshot_id: str = SNAPSHOT_ID,
    manifest_sha256: str = SNAPSHOT_SHA,
) -> tuple[SnapshotVerification, Path, Path, str]:
    repo_root, engine_root, repo_head, engine_head = _migration_roots(
        brain_root,
    )
    snapshot = _snapshot_verification(
        snapshot_id=snapshot_id,
        manifest_sha256=manifest_sha256,
        repo_head=repo_head,
        engine_head=engine_head,
        corpus_fingerprint_value=corpus_fingerprint(
            BrainStore.load(brain_root)
        ),
    )
    return snapshot, repo_root, engine_root, engine_head


def _apply(artifact, brain_root: Path, **overrides):
    snapshot, repo_root, engine_root, engine_head = _trusted_snapshot_for(
        brain_root,
    )
    kwargs = {
        "manifest_bytes": artifact.manifest_bytes,
        "expected_manifest_sha256": artifact.manifest_sha256,
        "brain_root": brain_root,
        "repo_root": repo_root,
        "engine_root": engine_root,
        "engine_sha": engine_head,
        "snapshot_root": brain_root.parent / "snapshot",
        "expected_snapshot_manifest_sha256": SNAPSHOT_SHA,
        **overrides,
    }
    with mock.patch(
        "project_brain.migration.verify_snapshot",
        return_value=snapshot,
    ):
        return apply_migration_artifact(**kwargs)


def _write_eval(brain_root: Path, payload: dict) -> bytes:
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    (brain_root / "eval_scenarios.json").write_bytes(encoded)
    return encoded


def _id_plan(brain_root: Path, renames: dict[str, str]):
    snapshot, repo_root, engine_root, engine_head = _trusted_snapshot_for(
        brain_root,
    )
    return plan_id_migration(
        existing=BrainStore.load(brain_root),
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        engine_sha=engine_head,
        renames=renames,
        snapshot=snapshot,
    )


def _target_derived_review_plan_args(
    tmp_path: Path,
    *,
    review_scope: str | None = "absent",
    tamper: str | None = None,
) -> dict:
    brain_root = tmp_path / "brain"
    target = candidate_term("g.neutral.x")
    target["context_id"] = "context.other"
    other_context = context("context.other")
    other_context["context_key"] = "other"
    review = review_record_for("review.g.neutral.x", target["id"])
    if review_scope != "absent":
        review["review_scope"] = review_scope

    renames = {
        target["id"]: "g.other.x",
        review["id"]: "review.g.other.x",
    }
    if tamper == "independent_self_id":
        renames[review["id"]] = "review.g.neutral.other"
    elif tamper == "target_not_renamed":
        del renames[target["id"]]
    elif tamper == "payload":
        target["context_id"] = "context.third"
        renames[target["id"]] = "g.other.x"
    elif tamper == "bundle":
        review["id"] = "review.bundle.neutral.review"
        review.pop("target_object_id")
        review.update({
            "review_scope": "mapping_bundle",
            "bundle_key": "bundle.neutral.review",
            "confirmation_key": "bundle.neutral.review",
            "target_object_ids": ["mapping.neutral.review"],
        })
        renames = {
            target["id"]: "g.other.x",
            review["id"]: "review.bundle.neutral.renamed",
        }

    _write_raw(brain_root, target)
    _write_raw(brain_root, other_context)
    _write_raw(brain_root, review)
    snapshot, repo_root, engine_root, engine_head = _trusted_snapshot_for(
        brain_root,
    )
    return {
        "existing": BrainStore.load(brain_root),
        "brain_root": brain_root,
        "repo_root": repo_root,
        "engine_root": engine_root,
        "engine_sha": engine_head,
        "renames": renames,
        "snapshot": snapshot,
    }


def test_plan_binds_explicit_git_roots_heads_and_snapshot_corpus(tmp_path):
    repo_root = (tmp_path / "repo").resolve()
    brain_root = repo_root / "brain"
    engine_root = (tmp_path / "engine").resolve()
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    repo_head = _git_repo(repo_root)
    engine_head = _git_repo(engine_root)
    existing = BrainStore.load(brain_root)
    snapshot = _snapshot_verification(
        repo_head=repo_head,
        engine_head=engine_head,
        corpus_fingerprint_value=corpus_fingerprint(existing),
    )

    plan = plan_id_migration(
        existing=existing,
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        engine_sha=engine_head,
        renames={old["id"]: "code.neutral.legacy"},
        snapshot=snapshot,
    )

    assert plan.request.repo_context is not None
    assert plan.request.repo_context.repo_root == repo_root
    assert plan.request.repo_context.target_revision_sha == repo_head
    assert plan.request.engine_sha == engine_head


@pytest.mark.parametrize(
    ("change", "error_code"),
    [
        ("repo_head", "snapshot_repo_head_mismatch"),
        ("engine_head", "snapshot_engine_head_mismatch"),
        ("engine_sha", "snapshot_engine_head_mismatch"),
        ("corpus", "snapshot_corpus_fingerprint_mismatch"),
    ],
)
def test_plan_rejects_snapshot_or_current_binding_mismatch(
    tmp_path,
    change,
    error_code,
):
    repo_root = (tmp_path / "repo").resolve()
    brain_root = repo_root / "brain"
    engine_root = (tmp_path / "engine").resolve()
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    repo_head = _git_repo(repo_root)
    engine_head = _git_repo(engine_root)
    snapshot = _snapshot_verification(
        repo_head=(
            "0" * 40 if change == "repo_head" else repo_head
        ),
        engine_head=(
            "0" * 40 if change == "engine_head" else engine_head
        ),
        corpus_fingerprint_value=(
            "0" * 64
            if change == "corpus"
            else corpus_fingerprint(BrainStore.load(brain_root))
        ),
    )

    with pytest.raises(MigrationError) as caught:
        plan_id_migration(
            existing=BrainStore.load(brain_root),
            brain_root=brain_root,
            repo_root=repo_root,
            engine_root=engine_root,
            engine_sha=(
                "0" * 40 if change == "engine_sha" else engine_head
            ),
            renames={old["id"]: "code.neutral.legacy"},
            snapshot=snapshot,
        )

    assert caught.value.code == error_code


@pytest.mark.parametrize("unsafe_kind", ["symlink", "non_git"])
def test_plan_rejects_unsafe_or_non_git_explicit_roots(
    tmp_path,
    unsafe_kind,
):
    real_repo = (tmp_path / "real-repo").resolve()
    brain_root = real_repo / "brain"
    engine_root = (tmp_path / "engine").resolve()
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    repo_head = _git_repo(real_repo)
    engine_head = _git_repo(engine_root)
    if unsafe_kind == "symlink":
        repo_root = (tmp_path / "repo-link").absolute()
        repo_root.symlink_to(real_repo, target_is_directory=True)
        plan_brain_root = repo_root / "brain"
    else:
        repo_root = real_repo
        plan_brain_root = brain_root
        engine_root = (tmp_path / "not-git").resolve()
        engine_root.mkdir()
    snapshot = _snapshot_verification(
        repo_head=repo_head,
        engine_head=engine_head,
        corpus_fingerprint_value=corpus_fingerprint(
            BrainStore.load(brain_root)
        ),
    )

    with pytest.raises(MigrationError) as caught:
        plan_id_migration(
            existing=BrainStore.load(brain_root),
            brain_root=plan_brain_root,
            repo_root=repo_root,
            engine_root=engine_root,
            engine_sha=engine_head,
            renames={old["id"]: "code.neutral.legacy"},
            snapshot=snapshot,
        )

    assert caught.value.code in {
        "symlink_forbidden",
        "source_unavailable",
        "git_head_invalid",
    }


@pytest.mark.parametrize(
    "drift",
    ["repo_head", "engine_head", "corpus", "root_swap"],
)
def test_apply_rejects_checkout_or_corpus_drift_since_plan(tmp_path, drift):
    repo_root = (tmp_path / "repo").resolve()
    brain_root = repo_root / "brain"
    engine_root = (tmp_path / "engine").resolve()
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    repo_head = _git_repo(repo_root)
    engine_head = _git_repo(engine_root)
    snapshot = _snapshot_verification(
        repo_head=repo_head,
        engine_head=engine_head,
        corpus_fingerprint_value=corpus_fingerprint(
            BrainStore.load(brain_root)
        ),
    )
    plan = plan_id_migration(
        existing=BrainStore.load(brain_root),
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        engine_sha=engine_head,
        renames={old["id"]: "code.neutral.legacy"},
        snapshot=snapshot,
    )
    artifact = create_migration_artifact(plan)
    if drift in {"repo_head", "engine_head"}:
        drift_root = repo_root if drift == "repo_head" else engine_root
        subprocess.run(
            [
                "git",
                "-C",
                str(drift_root),
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "drift",
            ],
            check=True,
        )
    elif drift == "corpus":
        changed = dict(old)
        changed["title"] = "drifted"
        _write_raw(brain_root, changed)
    else:
        moved = tmp_path / "repo-moved"
        repo_root.rename(moved)
        repo_root.symlink_to(moved, target_is_directory=True)

    with mock.patch(
        "project_brain.migration.verify_snapshot",
        return_value=snapshot,
    ), pytest.raises(MigrationError) as caught:
        apply_migration_artifact(
            manifest_bytes=artifact.manifest_bytes,
            expected_manifest_sha256=artifact.manifest_sha256,
            brain_root=brain_root,
            repo_root=repo_root,
            engine_root=engine_root,
            engine_sha=engine_head,
            snapshot_root=tmp_path / "snapshot",
            expected_snapshot_manifest_sha256=SNAPSHOT_SHA,
        )

    assert caught.value.code in {
        "snapshot_repo_head_mismatch",
        "snapshot_engine_head_mismatch",
        "snapshot_corpus_fingerprint_mismatch",
        "symlink_forbidden",
        "source_unavailable",
    }


def test_apply_replan_reuses_strict_eval_validator_before_mutation(tmp_path):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    _write_eval(brain_root, {
        "scenarios": [{
            "id": "s",
            "query": "q",
            "expect": {"top5_any": [old["id"]]},
        }],
    })
    local = brain_root / ".brain-local"
    local.mkdir()
    (local / "index.db").write_bytes(b"index")
    plan = _id_plan(
        brain_root,
        {old["id"]: "code.neutral.legacy"},
    )
    artifact = create_migration_artifact(plan)
    (brain_root / "eval_scenarios.json").write_bytes(
        b'{"scenarios":[{"id":"s","query":"q","expect":'
        b'{"top5_any":["code.Legacy"],'
        b'"top5_any":["code.Legacy"]}}]}\n'
    )

    with pytest.raises(MigrationError) as caught:
        _apply(artifact, brain_root)

    assert caught.value.code == "eval_invalid"
    assert BrainStore.load(brain_root).has(old["id"])
    assert not BrainStore.load(brain_root).has("code.neutral.legacy")
    assert (local / "index.db").read_bytes() == b"index"
    assert not (local / "transactions").exists()


def test_migration_row_has_exact_contract_fields():
    assert [field.name for field in fields(MigrationRow)] == [
        "old_id",
        "new_id",
        "kind",
        "canonical_payload_hash",
        "reference_rewrites",
        "dependent_artifacts",
        "snapshot_id",
    ]


def test_id_plan_tokenizes_self_and_registered_refs_and_lists_every_pointer(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    old_locator = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy display",
    )
    old_review = review_record_for("review.code.Legacy", old_locator["id"])
    _write_raw(brain_root, old_locator)
    _write_raw(brain_root, old_review)
    eval_before = {
        "scenarios": [{
            "id": "migration",
            "query": "query keeps code.Legacy literally",
            "expect": {
                "top5_any": ["code.Legacy"],
                "linked_any_groups": [["review.code.Legacy"]],
                "raw_top5_prefix_any": ["code.Legacy"],
            },
        }],
        "note": "code.Legacy outside registry stays unchanged",
    }
    _write_eval(brain_root, eval_before)
    local = brain_root / ".brain-local"
    local.mkdir()
    (local / "stale-set.json").write_text(
        json.dumps({
            "stale_mapping_ids": ["code.Legacy"],
            "note": "code.Legacy",
        }),
        encoding="utf-8",
    )
    (local / "index.db").write_bytes(b"synthetic index")

    plan = _id_plan(brain_root, {
        "code.Legacy": "code.neutral.legacy",
        "review.code.Legacy": "review.code.neutral.legacy",
    })

    assert plan.mutation_plan.ok is True
    assert [row.old_id for row in plan.rows] == [
        "code.Legacy",
        "review.code.Legacy",
    ]
    assert all(
        set(row.__dict__) == {
            "old_id",
            "new_id",
            "kind",
            "canonical_payload_hash",
            "reference_rewrites",
            "dependent_artifacts",
            "snapshot_id",
        }
        for row in plan.rows
    )
    locator_row, review_row = plan.rows
    assert locator_row.canonical_payload_hash
    assert locator_row.reference_rewrites == ({
        "object_id": "review.code.neutral.legacy",
        "pointer": "/target_object_id",
        "before_id": "code.Legacy",
        "after_id": "code.neutral.legacy",
    },)
    assert {
        (item["artifact"], item["action"])
        for item in locator_row.dependent_artifacts
    } >= {
        ("eval_scenarios.json", "rewrite"),
        (".brain-local/stale-set.json", "invalidate"),
        (".brain-local/index.db*", "invalidate"),
    }
    rewritten_eval = json.loads(
        plan.request.auxiliary_updates[0].after_bytes
    )
    scenario = rewritten_eval["scenarios"][0]
    assert scenario["expect"]["top5_any"] == ["code.neutral.legacy"]
    assert scenario["expect"]["linked_any_groups"] == [
        ["review.code.neutral.legacy"],
    ]
    assert scenario["expect"]["raw_top5_prefix_any"] == ["code.Legacy"]
    assert scenario["query"] == "query keeps code.Legacy literally"
    assert rewritten_eval["note"] == eval_before["note"]


def test_id_plan_renames_unknown_grammar_review_and_rewrites_reference(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    old_locator = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy display",
    )
    old_review = review_record_for(
        "review.disturb-boostedbomb.depth-config",
        old_locator["id"],
    )
    _write_raw(brain_root, old_locator)
    _write_raw(brain_root, old_review)

    plan = _id_plan(brain_root, {
        old_locator["id"]: "code.neutral.legacy",
        old_review["id"]: "review.code.neutral.legacy",
    })

    assert plan.mutation_plan.ok is True
    assert {
        (row.old_id, row.new_id)
        for row in plan.rows
    } == {
        ("code.Legacy", "code.neutral.legacy"),
        (
            "review.disturb-boostedbomb.depth-config",
            "review.code.neutral.legacy",
        ),
    }
    assert {
        (
            rewrite["object_id"],
            rewrite["pointer"],
            rewrite["before_id"],
            rewrite["after_id"],
        )
        for rewrite in plan.mutation_plan.reference_rewrites
    } == {
        (
            "review.code.neutral.legacy",
            "/target_object_id",
            "code.Legacy",
            "code.neutral.legacy",
        ),
    }


def test_id_plan_unknown_grammar_rename_still_requires_zero_structured_debt(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    source = review_record_for(
        "review.disturb-boostedbomb.depth-config",
        "context.neutral",
    )
    remaining = context("context.Legacy")
    remaining["context_key"] = "Legacy"
    _write_raw(brain_root, context())
    _write_raw(brain_root, source)
    _write_raw(brain_root, remaining)

    with pytest.raises(MigrationError) as caught:
        _id_plan(brain_root, {
            source["id"]: "review.context.neutral",
        })

    assert caught.value.code == "grandfathered_problems_remaining"


def test_id_plan_allows_target_derived_review_without_scope(tmp_path):
    args = _target_derived_review_plan_args(tmp_path, review_scope="absent")

    plan = plan_id_migration(**args)

    assert [row.kind for row in plan.rows] == ["GlossaryTerm", "ReviewRecord"]


def test_id_plan_allows_target_derived_review_with_single_scope(tmp_path):
    args = _target_derived_review_plan_args(
        tmp_path,
        review_scope="single_object",
    )

    assert plan_id_migration(**args).migration_kind == "id_only"


@pytest.mark.parametrize("scope", [None, "mapping_bundle", "other"])
def test_id_plan_rejects_target_derived_review_with_bad_scope(tmp_path, scope):
    args = _target_derived_review_plan_args(tmp_path, review_scope=scope)

    with pytest.raises(MigrationError) as exc:
        plan_id_migration(**args)

    assert exc.value.code == "id_only_legacy_source_not_invalid"


@pytest.mark.parametrize(
    "tamper",
    ["independent_self_id", "target_not_renamed", "payload", "bundle"],
)
def test_id_plan_rejects_non_exact_review_closure(tmp_path, tamper):
    args = _target_derived_review_plan_args(tmp_path, tamper=tamper)

    with pytest.raises(MigrationError):
        plan_id_migration(**args)


def test_canonical_payload_rejects_every_non_registry_semantic_change():
    before = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy display",
    )
    after = dict(before)
    after["id"] = "code.neutral.legacy"
    expected = canonical_payload_hash_pair(
        before,
        after,
        renames={"code.Legacy": "code.neutral.legacy"},
        old_id="code.Legacy",
        new_id="code.neutral.legacy",
    )
    assert len(expected) == 64

    for field_name, value in (
        ("title", "changed"),
        ("status", "candidate"),
        ("path", "Changed.cpp"),
        ("symbol", "Changed"),
        ("commit_sha", "1" * 40),
        ("verified_at", "2099-01-01T00:00:00Z"),
        ("verified_quote", "changed quote"),
        ("meaning", "changed meaning"),
    ):
        changed = dict(after)
        changed[field_name] = value
        with pytest.raises(MigrationError, match="canonical payload"):
            canonical_payload_hash_pair(
                before,
                changed,
                renames={"code.Legacy": "code.neutral.legacy"},
                old_id="code.Legacy",
                new_id="code.neutral.legacy",
            )


def test_canonical_payload_placeholders_do_not_collide_with_literal_tokens():
    before = {
        "id": "code.Legacy",
        "kind": "CodeLocator",
        "title": "$SELF",
        "target_object_id": "$REF:000001",
        "tag_like_literal": (
            '{"__project_brain_migration_placeholder__":'
            '{"kind":"reference","ordinal":1}}'
        ),
    }
    after = {
        **before,
        "id": "code.neutral.legacy",
        "target_object_id": "code.neutral.legacy",
    }

    with pytest.raises(MigrationError, match="canonical payload"):
        canonical_payload_hash_pair(
            before,
            after,
            renames={"code.Legacy": "code.neutral.legacy"},
            old_id="code.Legacy",
            new_id="code.neutral.legacy",
        )


def test_canonical_payload_reference_ordinals_are_deterministic_and_distinct():
    before = {
        "id": "code.Z",
        "kind": "CodeLocator",
        "target_object_ids": ["code.A", "code.Z"],
    }
    after = {
        **before,
        "id": "code.new-z",
        "target_object_ids": ["code.new-a", "code.new-z"],
    }
    renames = {
        "code.Z": "code.new-z",
        "code.A": "code.new-a",
    }

    first = canonical_payload_hash_pair(
        before,
        after,
        renames=renames,
        old_id="code.Z",
        new_id="code.new-z",
    )
    second = canonical_payload_hash_pair(
        before,
        after,
        renames=dict(reversed(tuple(renames.items()))),
        old_id="code.Z",
        new_id="code.new-z",
    )

    assert first == second


@pytest.mark.parametrize(
    "eval_bytes",
    [
        b'{"scenarios":[],"scenarios":[]}\n',
        (
            b'{"scenarios":[{"id":"s","id":"s2","query":"q",'
            b'"expect":{"top5_any":["code.Legacy"]}}]}\n'
        ),
        (
            b'{"scenarios":[{"id":"s","query":"q","expect":'
            b'{"top5_any":["code.Legacy"],'
            b'"top5_any":["code.Legacy"]}}]}\n'
        ),
        b'{"scenarios":[null]}\n',
        b'{"scenarios":[{"id":"","query":"q","expect":{"no_answer":true}}]}\n',
        b'{"scenarios":[{"id":"s","query":"q"}]}\n',
        (
            b'{"scenarios":[{"id":"s","query":"q","expect":'
            b'{"unknown":["code.Legacy"]}}]}\n'
        ),
        (
            b'{"scenarios":[{"id":"s","query":"q","expect":'
            b'{"top5_any":true}}]}\n'
        ),
        (
            b'{"scenarios":[{"id":"s","query":"q","expect":'
            b'{"top5_any":null}}]}\n'
        ),
        (
            b'{"scenarios":[{"id":"s","query":"q","expect":'
            b'{"top5_any":[["code.Legacy"]]}}]}\n'
        ),
        (
            b'{"scenarios":[{"id":"s","query":"q","expect":'
            b'{"top5_any":["code.Legacy","code.Legacy"]}}]}\n'
        ),
        (
            b'{"scenarios":[{"id":"s","query":"q","expect":'
            b'{"linked_any_groups":["code.Legacy"]}}]}\n'
        ),
        (
            b'{"scenarios":[{"id":"s","query":"q","expect":'
            b'{"linked_any_groups":[[["code.Legacy"]]]}}]}\n'
        ),
        (
            b'{"scenarios":[{"id":"s","query":"q","expect":'
            b'{"max_results":true}}]}\n'
        ),
        (
            b'{"scenarios":[{"id":"s","query":"q","expect":'
            b'{"no_answer":null}}]}\n'
        ),
        (
            b'{"scenarios":[{"id":"s","query":"q","expect":'
            b'{"raw_top5_prefix_any":[["raw."]]}}]}\n'
        ),
        (
            b'{"scenarios":['
            b'{"id":"s","query":"q","expect":{"no_answer":true}},'
            b'{"id":"s","query":"q2","expect":{"no_answer":true}}]}\n'
        ),
    ],
)
def test_id_plan_rejects_ambiguous_or_noncanonical_eval(tmp_path, eval_bytes):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    (brain_root / "eval_scenarios.json").write_bytes(eval_bytes)

    with pytest.raises(MigrationError) as caught:
        _id_plan(brain_root, {old["id"]: "code.neutral.legacy"})

    assert caught.value.code == "eval_invalid"


@pytest.mark.parametrize(
    ("snapshot_id", "snapshot_sha", "error_code"),
    [
        ("", SNAPSHOT_SHA, "snapshot_id_invalid"),
        ("../unsafe", SNAPSHOT_SHA, "snapshot_id_invalid"),
        (SNAPSHOT_ID, "", "snapshot_receipt_invalid"),
        (SNAPSHOT_ID, "A" * 64, "snapshot_receipt_invalid"),
    ],
)
def test_plan_rejects_empty_or_unsafe_snapshot_binding(
    tmp_path,
    snapshot_id,
    snapshot_sha,
    error_code,
):
    brain_root = (tmp_path / "brain").resolve()
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    _, repo_root, engine_root, engine_head = _trusted_snapshot_for(
        brain_root,
    )
    invalid_snapshot = _snapshot_verification(
        snapshot_id=snapshot_id,
        manifest_sha256=snapshot_sha,
        repo_head=_git_repo(repo_root),
        engine_head=engine_head,
        corpus_fingerprint_value=corpus_fingerprint(
            BrainStore.load(brain_root)
        ),
    )

    with pytest.raises(MigrationError) as caught:
        plan_id_migration(
            existing=BrainStore.load(brain_root),
            brain_root=brain_root,
            repo_root=repo_root,
            engine_root=engine_root,
            engine_sha=engine_head,
            renames={old["id"]: "code.neutral.legacy"},
            snapshot=invalid_snapshot,
        )

    assert caught.value.code == error_code


@pytest.mark.parametrize(
    ("renames", "error_code"),
    [
        (
            {
                "code.Legacy": "code.neutral.same",
                "code.Other": "code.neutral.same",
            },
            "duplicate_new_id",
        ),
        (
            {"code.Legacy": "code.Other"},
            "migration_target_exists",
        ),
        (
            {"code.Missing": "code.neutral.missing"},
            "migration_source_missing",
        ),
    ],
)
def test_id_plan_rejects_merge_or_non_one_to_one_mapping(
    tmp_path,
    renames,
    error_code,
):
    brain_root = tmp_path / "brain"
    for object_id in ("code.Legacy", "code.Other"):
        _write_raw(
            brain_root,
            _code_locator(
                object_id=object_id,
                quote=None,
                title="legacy",
            ),
        )

    with pytest.raises(MigrationError) as caught:
        _id_plan(brain_root, renames)

    assert caught.value.code == error_code


def test_display_plan_changes_only_code_locator_title(tmp_path):
    brain_root = tmp_path / "brain"
    with_symbol = _code_locator(
        object_id="code.neutral.with-symbol",
        symbol="Namespace::Run",
        title="semantic label",
        quote=None,
    )
    without_symbol = _code_locator(
        object_id="code.neutral.legacy",
        title="semantic legacy label",
        quote=None,
        path="Source/Legacy.cpp",
    )
    without_symbol.pop("symbol")
    source_manifest = manifest()
    ref = evidence_ref("evref.neutral.display")
    ref["title"] = "EvidenceRef title is not a target"
    for obj in (with_symbol, without_symbol, source_manifest, ref):
        _write_raw(brain_root, obj)
    snapshot, repo_root, engine_root, engine_head = _trusted_snapshot_for(
        brain_root,
    )

    plan = plan_display_migration(
        existing=BrainStore.load(brain_root),
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        engine_sha=engine_head,
        snapshot=snapshot,
    )

    after = {obj["id"]: obj for obj in plan.mutation_plan.after_objects}
    assert after[with_symbol["id"]]["title"] == "Namespace::Run"
    assert after[without_symbol["id"]]["title"] == "Legacy.cpp:legacy"
    assert ref["id"] not in after
    before = {with_symbol["id"]: with_symbol, without_symbol["id"]: without_symbol}
    for object_id, migrated in after.items():
        assert {
            key: value
            for key, value in migrated.items()
            if key != "title"
        } == {
            key: value
            for key, value in before[object_id].items()
            if key != "title"
        }


def test_apply_recomputes_manifest_and_rejects_canonical_hash_tampering(
    tmp_path,
):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    _write_eval(brain_root, {
        "scenarios": [{
            "id": "s",
            "query": "q",
            "expect": {"top5_any": [old["id"]]},
        }],
    })
    plan = _id_plan(
        brain_root,
        {old["id"]: "code.neutral.legacy"},
    )
    artifact = create_migration_artifact(plan)
    tampered = json.loads(artifact.manifest_bytes)
    tampered["rows"][0]["canonical_payload_hash"] = "0" * 64
    tampered_bytes = (
        json.dumps(
            tampered,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")

    with pytest.raises(MigrationError) as caught:
        _apply(
            replace(
                artifact,
                manifest_bytes=tampered_bytes,
                manifest_sha256=hashlib.sha256(
                    tampered_bytes,
                ).hexdigest(),
            ),
            brain_root,
        )

    assert caught.value.code == "manifest_revalidation_failed"
    assert BrainStore.load(brain_root).has(old["id"])


def test_apply_requires_exact_trusted_snapshot_and_manifest_receipts(tmp_path):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    plan = _id_plan(
        brain_root,
        {old["id"]: "code.neutral.legacy"},
    )
    artifact = create_migration_artifact(plan)
    trusted, repo_root, engine_root, engine_head = _trusted_snapshot_for(
        brain_root,
    )

    for changes, verification, error_code in (
        (
            {"expected_manifest_sha256": "0" * 64},
            trusted,
            "manifest_sha256_mismatch",
        ),
        (
            {},
            replace(trusted, snapshot_id="other"),
            "snapshot_binding_mismatch",
        ),
        (
            {},
            replace(trusted, manifest_sha256="0" * 64),
            "snapshot_binding_mismatch",
        ),
    ):
        kwargs = {
            "manifest_bytes": artifact.manifest_bytes,
            "expected_manifest_sha256": artifact.manifest_sha256,
            "brain_root": brain_root,
            "repo_root": repo_root,
            "engine_root": engine_root,
            "engine_sha": engine_head,
            "snapshot_root": brain_root.parent / "snapshot",
            "expected_snapshot_manifest_sha256": SNAPSHOT_SHA,
            **changes,
        }
        with mock.patch(
            "project_brain.migration.verify_snapshot",
            return_value=verification,
        ), pytest.raises(MigrationError) as caught:
            apply_migration_artifact(**kwargs)
        assert caught.value.code == error_code


def test_id_apply_commits_exact_object_eval_and_invalidates_derived(tmp_path):
    brain_root = tmp_path / "brain"
    old = _code_locator(
        object_id="code.Legacy",
        quote=None,
        title="legacy",
    )
    _write_raw(brain_root, old)
    _write_eval(brain_root, {
        "scenarios": [{
            "id": "s",
            "query": "q",
            "expect": {"top5_any": [old["id"]]},
        }],
    })
    local = brain_root / ".brain-local"
    local.mkdir()
    (local / "index.db").write_bytes(b"index")
    (local / "stale-set.json").write_text(
        '{"stale_mapping_ids":["code.Legacy"]}\n',
        encoding="utf-8",
    )
    plan = _id_plan(
        brain_root,
        {old["id"]: "code.neutral.legacy"},
    )
    artifact = create_migration_artifact(plan)

    result = _apply(artifact, brain_root)

    assert plan.mutation_plan.manifest is None
    assert re.fullmatch(r"[0-9a-f]{64}", result.transaction_id)
    store = BrainStore.load(brain_root)
    assert not store.has(old["id"])
    assert store.has("code.neutral.legacy")
    eval_payload = json.loads((brain_root / "eval_scenarios.json").read_bytes())
    assert eval_payload["scenarios"][0]["expect"]["top5_any"] == [
        "code.neutral.legacy",
    ]
    assert not (local / "index.db").exists()
    assert not (local / "stale-set.json").exists()
