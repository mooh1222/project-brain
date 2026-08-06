from __future__ import annotations

import base64
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from project_brain.task18_binding import Task18BindingError
from project_brain.task18_binding_verify import verify_task18_binding


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def test_binding_sha_is_checked_before_json_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    path = (tmp_path / "binding.json").resolve()
    path.write_bytes(b"not-json\n")

    def should_not_collect(*args, **kwargs):
        raise AssertionError("state collection ran before binding SHA verification")

    import project_brain.task18_binding_verify as module

    monkeypatch.setattr(module, "capture_git_dirt_receipt", should_not_collect)
    with pytest.raises(Task18BindingError, match="binding_sha256_mismatch"):
        verify_task18_binding(
            binding_path=path,
            expected_binding_sha256="0" * 64,
            engine_root=tmp_path.resolve(),
            repo_root=tmp_path.resolve(),
            brain_root=tmp_path.resolve(),
        )


def test_verifier_does_not_reuse_generator_payload_or_state_collector():
    import project_brain.task18_binding_verify as module

    source = inspect.getsource(module)
    assert "build_binding_value" not in source
    assert "collect_generator_state" not in source
    assert "from project_brain.task18_binding import" in source
    assert "Task18BindingError" in source


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(version=True),
        lambda value: value["engine"].update(extra=True),
        lambda value: value["engine"].pop("cached_paths"),
        lambda value: value["engine"].update(status_bytes_base64="YQ"),
        lambda value: value["inputs"]["measurement"].update(
            path="/tmp/root/../escaped.json"
        ),
    ],
    ids=["version-bool", "nested-add", "nested-drop", "base64", "path-escape"],
)
def test_exact_parser_rejects_bool_nested_and_encoding_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate,
):
    import project_brain.task18_binding_verify as module

    # parser만 통과할 수 있을 만큼의 exact 합성 binding을 만든다.
    empty = base64.b64encode(b"").decode("ascii")
    empty_manifest = base64.b64encode(b"[]\n").decode("ascii")
    sha_empty = hashlib.sha256(b"").hexdigest()
    sha_manifest = hashlib.sha256(b"[]\n").hexdigest()
    input_bytes = _canonical({})
    input_path = (tmp_path / "input.json").resolve()
    input_path.write_bytes(input_bytes)
    file_receipt = {
        "path": str(input_path),
        "sha256": hashlib.sha256(input_bytes).hexdigest(),
        "size": len(input_bytes),
        "mode": 0o644,
    }
    committed = {**file_receipt, "commit_sha": "2" * 40}
    git = {
        "head": "3" * 40,
        "status_bytes_base64": empty,
        "status_sha256": sha_empty,
        "dirt_manifest_base64": empty_manifest,
        "dirt_content_sha256": sha_manifest,
        "cached_paths": [],
    }
    value = {
        "version": 1,
        "purpose": "task18-display-labels-and-quote-debt-final-binding",
        "created_at": "2026-08-06T12:00:00+09:00",
        "task18_allowed": True,
        "roots": {"engine": str(tmp_path), "bb2": str(tmp_path), "brain": str(tmp_path)},
        "engine": dict(git),
        "bb2": dict(git),
        "target_revision": {
            "local_ref": "refs/remotes/origin/develop",
            "local_sha": "4" * 40,
            "remote": "origin",
            "remote_ref": "refs/heads/develop",
            "remote_sha": "4" * 40,
            "target_revision_sha": "4" * 40,
        },
        "corpus": {
            "mutation_fingerprint": "5" * 64,
            "objects_tree_sha256": "6" * 64,
            "raw_tree_sha256": "7" * 64,
        },
        "search_index": {
            "live_corpus_fingerprint": "8" * 64,
            "meta_corpus_fingerprint": "8" * 64,
            "db_file_sha256": "9" * 64,
        },
        "stale_set": {"sha256": "a" * 64},
        "inputs": {
            "p0_handoff": dict(file_receipt),
            "measurement": dict(file_receipt),
            "design": dict(committed),
            "plan": dict(committed),
            "quote_debt": dict(file_receipt),
            "snapshot_verify_receipt": dict(file_receipt),
        },
        "pre_mutation_snapshot": {
            "path": str(tmp_path),
            "manifest_sha256": "b" * 64,
            "snapshot_id": "snapshot",
            "file_count": 1,
            "repo_head": "3" * 40,
            "engine_head": "3" * 40,
            "corpus_fingerprint": "5" * 64,
            "verify_receipt_path": str(input_path),
            "verify_receipt_sha256": hashlib.sha256(input_bytes).hexdigest(),
        },
        "migration": {
            "target_ids_sha256": hashlib.sha256(b"[]").hexdigest(),
            "targets_sha256": hashlib.sha256(b"[]").hexdigest(),
            "code_locator_count": 0,
            "evidence_ref_count": 0,
            "total_count": 0,
            "before_corpus_fingerprint": "5" * 64,
            "expected_after_corpus_fingerprint": "5" * 64,
            "targets": [],
        },
    }
    mutate(value)
    path = (tmp_path / "binding.json").resolve()
    data = _canonical(value)
    path.write_bytes(data)
    monkeypatch.setattr(
        module,
        "capture_git_dirt_receipt",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("collected")),
    )

    with pytest.raises(Task18BindingError, match="binding_schema_invalid"):
        verify_task18_binding(
            binding_path=path,
            expected_binding_sha256=hashlib.sha256(data).hexdigest(),
            engine_root=tmp_path.resolve(),
            repo_root=tmp_path.resolve(),
            brain_root=tmp_path.resolve(),
        )


@pytest.mark.parametrize(
    "data",
    [
        b'{"version":1,"version":1}\n',
        b'{"version":NaN}\n',
    ],
    ids=["duplicate-key", "nan"],
)
def test_parser_normalizes_duplicate_key_and_nan_to_binding_error(
    tmp_path: Path,
    data: bytes,
):
    path = (tmp_path / "binding.json").resolve()
    path.write_bytes(data)

    with pytest.raises(Task18BindingError):
        verify_task18_binding(
            binding_path=path,
            expected_binding_sha256=hashlib.sha256(data).hexdigest(),
            engine_root=tmp_path.resolve(),
            repo_root=tmp_path.resolve(),
            brain_root=tmp_path.resolve(),
        )
