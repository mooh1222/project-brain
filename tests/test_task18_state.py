from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

import pytest

from project_brain import search_index
from project_brain.store import BrainStore


def _state_module():
    return import_module("project_brain.task18_state")


def _run(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    ).stdout


@dataclass
class GitRepo:
    root: Path

    def write(self, relative: str, data: bytes) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def stage(self, relative: str, data: bytes) -> None:
        self.write(relative, data)
        _run(self.root, "add", "--", relative)

    def commit_file(self, relative: str, data: bytes) -> str:
        self.stage(relative, data)
        _run(self.root, "commit", "-q", "-m", f"commit {relative}")
        return _run(self.root, "rev-parse", "HEAD").decode().strip()


@pytest.fixture
def git_repo(tmp_path) -> GitRepo:
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "develop", str(root)], check=True)
    _run(root, "config", "user.email", "task18@test.invalid")
    _run(root, "config", "user.name", "Task 18 Test")
    repo = GitRepo(root)
    repo.commit_file("README.md", b"fixture\n")
    return repo


@dataclass
class GitRemote:
    root: Path
    develop_sha: str


@pytest.fixture
def git_remote(tmp_path) -> GitRemote:
    root = (tmp_path / "work").resolve()
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "develop", str(root)], check=True)
    _run(root, "config", "user.email", "task18@test.invalid")
    _run(root, "config", "user.name", "Task 18 Test")
    (root / "tracked.txt").write_bytes(b"develop\n")
    _run(root, "add", "tracked.txt")
    _run(root, "commit", "-q", "-m", "develop")
    develop_sha = _run(root, "rev-parse", "HEAD").decode().strip()
    remote = (tmp_path / "remote.git").resolve()
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _run(root, "remote", "add", "origin", str(remote))
    _run(root, "push", "-q", "-u", "origin", "develop")
    return GitRemote(root=root, develop_sha=develop_sha)


@pytest.fixture
def brain_root(tmp_path) -> Path:
    root = (tmp_path / "brain").resolve()
    object_path = root / "objects/domain/context.json"
    object_path.parent.mkdir(parents=True)
    object_path.write_text(
        json.dumps({"id": "domain.fixture", "kind": "DomainContext"}),
        encoding="utf-8",
    )
    raw_path = root / "raw/sources/source.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("source\n", encoding="utf-8")
    local = root / ".brain-local"
    local.mkdir()
    live_fingerprint = search_index.compute_corpus_fingerprint(
        BrainStore.load(root), root
    )
    with sqlite3.connect(local / "index.db") as connection:
        connection.execute(
            "CREATE TABLE meta (schema_version INTEGER, embed_model TEXT, "
            "tokenizer TEXT, extractor_version TEXT, corpus_fingerprint TEXT)"
        )
        connection.execute(
            "INSERT INTO meta VALUES (4, 'stub', 'stub', 'fixture', ?)",
            (live_fingerprint,),
        )
    (local / "stale-set.json").write_bytes(b'{"stale":[]}\n')
    return root


def test_capture_cached_paths_is_nul_safe_and_sorted(git_repo):
    git_repo.stage("z.json", b"z")
    git_repo.stage("name with newline\ninside.json", b"payload")

    assert _state_module().capture_cached_paths(git_repo.root) == (
        "name with newline\ninside.json",
        "z.json",
    )


def test_capture_remote_ref_requires_local_and_ls_remote_exact_match(git_remote):
    receipt = _state_module().capture_remote_ref(
        git_remote.root,
        local_ref="refs/remotes/origin/develop",
        remote="origin",
        remote_ref="refs/heads/develop",
    )

    assert receipt.local_sha == receipt.remote_sha == git_remote.develop_sha


def test_capture_remote_ref_rejects_mismatch(git_remote):
    previous = git_remote.develop_sha
    (git_remote.root / "tracked.txt").write_bytes(b"advanced\n")
    _run(git_remote.root, "add", "tracked.txt")
    _run(git_remote.root, "commit", "-q", "-m", "advance")
    advanced = _run(git_remote.root, "rev-parse", "HEAD").decode().strip()
    _run(git_remote.root, "push", "-q", "origin", "develop")
    assert advanced != previous
    _run(
        git_remote.root,
        "update-ref",
        "refs/remotes/origin/develop",
        previous,
    )

    with pytest.raises(_state_module().Task18StateError, match="remote_ref_mismatch"):
        _state_module().capture_remote_ref(
            git_remote.root,
            local_ref="refs/remotes/origin/develop",
            remote="origin",
            remote_ref="refs/heads/develop",
        )


def test_capture_bound_file_rejects_symlink_leaf_or_parent(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    (tmp_path / "link.json").symlink_to(target)
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    (real_parent / "bound.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "linked-parent").symlink_to(real_parent, target_is_directory=True)

    for path in (tmp_path / "link.json", tmp_path / "linked-parent/bound.json"):
        with pytest.raises(_state_module().Task18StateError):
            _state_module().capture_bound_file(path)


def test_capture_bound_file_returns_exact_bytes_receipt(tmp_path):
    path = (tmp_path / "bound.json").resolve()
    path.write_bytes(b"{}\n")

    assert _state_module().capture_bound_file(path) == {
        "path": str(path),
        "sha256": hashlib.sha256(b"{}\n").hexdigest(),
        "size": 3,
        "mode": 0o644,
    }


def test_capture_task18_corpus_state_includes_objects_raw_index_and_stale(
    brain_root,
):
    state = _state_module().capture_task18_corpus_state(brain_root)

    assert set(state) == {"corpus", "search_index", "stale_set"}
    assert set(state["corpus"]) == {
        "mutation_fingerprint",
        "objects_tree_sha256",
        "raw_tree_sha256",
    }
    assert state["search_index"]["live_corpus_fingerprint"] == state[
        "search_index"
    ]["meta_corpus_fingerprint"]
    assert state["stale_set"]["sha256"] == hashlib.sha256(
        b'{"stale":[]}\n'
    ).hexdigest()


def test_capture_committed_input_rejects_dirty_or_non_ancestor_bytes(git_repo):
    committed = git_repo.commit_file("docs/plan.md", b"committed\n")
    git_repo.write("docs/plan.md", b"dirty\n")

    with pytest.raises(
        _state_module().Task18StateError, match="committed_input"
    ):
        _state_module().capture_committed_input(
            git_repo.root, Path("docs/plan.md"), committed
        )

    _run(git_repo.root, "restore", "docs/plan.md")
    _run(git_repo.root, "checkout", "-q", "-b", "side")
    non_ancestor = git_repo.commit_file("docs/side.md", b"side\n")
    _run(git_repo.root, "checkout", "-q", "develop")
    git_repo.commit_file("docs/develop.md", b"develop\n")

    with pytest.raises(
        _state_module().Task18StateError, match="committed_input"
    ):
        _state_module().capture_committed_input(
            git_repo.root, Path("docs/side.md"), non_ancestor
        )


def test_capture_committed_input_returns_commit_bound_receipt(git_repo):
    committed = git_repo.commit_file("docs/plan.md", b"committed\n")

    assert _state_module().capture_committed_input(
        git_repo.root, Path("docs/plan.md"), committed
    ) == {
        "path": str((git_repo.root / "docs/plan.md").resolve()),
        "commit_sha": committed,
        "file_sha256": hashlib.sha256(b"committed\n").hexdigest(),
        "mode": 0o644,
    }
