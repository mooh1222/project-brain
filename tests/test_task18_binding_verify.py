from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from project_brain.task18_binding import Task18BindingError
from project_brain.task18_binding_verify import verify_task18_binding


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
