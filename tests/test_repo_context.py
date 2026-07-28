"""쓰기 전 Git repository context 검증 테스트."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project_brain.repo_context import RepoVerificationError, resolve_repo_context


class RepoContextTest(unittest.TestCase):
    def _git(self, repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True,
        )

    def _repo(self) -> tuple[tempfile.TemporaryDirectory, Path, str]:
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name).resolve()
        self._git(repo, "init")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Test User")
        (repo / "src").mkdir()
        (repo / "src" / "example.cpp").write_text(
            "void Foo::bar() { return; }\n", encoding="utf-8",
        )
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-m", "fixture")
        sha = self._git(repo, "rev-parse", "HEAD").stdout.decode().strip()
        return td, repo, sha

    def test_resolves_absolute_exact_git_toplevel_and_revision(self):
        td, repo, sha = self._repo()
        self.addCleanup(td.cleanup)

        context = resolve_repo_context(
            repo,
            expected_repo_id="demo",
            configured_repo_id="demo",
            expected_revision_ref="HEAD",
        )

        self.assertEqual(context.repo_root, repo)
        self.assertEqual(context.expected_repo_id, "demo")
        self.assertEqual(context.expected_revision_ref, "HEAD")
        self.assertEqual(context.target_revision_sha, sha)

    def test_not_git_repo_has_distinct_error_code(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RepoVerificationError) as ctx:
                resolve_repo_context(
                    Path(td).resolve(),
                    expected_repo_id="demo",
                    configured_repo_id="demo",
                    expected_revision_ref="HEAD",
                )

        self.assertEqual(ctx.exception.failure.code, "not_git_repo")

    def test_repo_identity_mismatch_has_distinct_error_code(self):
        td, repo, _sha = self._repo()
        self.addCleanup(td.cleanup)

        with self.assertRaises(RepoVerificationError) as ctx:
            resolve_repo_context(
                repo,
                expected_repo_id="demo",
                configured_repo_id="other",
                expected_revision_ref="HEAD",
            )

        self.assertEqual(ctx.exception.failure.code, "repo_identity_mismatch")

    def test_nested_git_directory_is_not_accepted_as_repo_root(self):
        td, repo, _sha = self._repo()
        self.addCleanup(td.cleanup)

        with self.assertRaises(RepoVerificationError) as ctx:
            resolve_repo_context(
                repo / "src",
                expected_repo_id="demo",
                configured_repo_id="demo",
                expected_revision_ref="HEAD",
            )

        self.assertEqual(ctx.exception.failure.code, "repo_identity_mismatch")

    def test_relative_repo_root_is_rejected(self):
        with self.assertRaises(ValueError):
            resolve_repo_context(
                Path("relative/repo"),
                expected_repo_id="demo",
                configured_repo_id="demo",
                expected_revision_ref="HEAD",
            )

    def test_repo_root_with_nul_is_structured_not_git_repo(self):
        with self.assertRaises(RepoVerificationError) as ctx:
            resolve_repo_context(
                Path("/tmp/invalid\x00repo"),
                expected_repo_id="demo",
                configured_repo_id="demo",
                expected_revision_ref="HEAD",
            )

        self.assertEqual(ctx.exception.failure.code, "not_git_repo")

    def test_revision_ref_with_nul_is_structured_commit_missing(self):
        td, repo, _sha = self._repo()
        self.addCleanup(td.cleanup)

        with self.assertRaises(RepoVerificationError) as ctx:
            resolve_repo_context(
                repo,
                expected_repo_id="demo",
                configured_repo_id="demo",
                expected_revision_ref="HEAD\x00unexpected",
            )

        self.assertEqual(ctx.exception.failure.code, "commit_missing")

    def test_undecodable_git_toplevel_is_structured_not_git_repo(self):
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.CompletedProcess(
                ["git", "rev-parse", "--show-toplevel"],
                0,
                stdout=b"\xff\n",
                stderr=b"",
            )
            with mock.patch(
                "project_brain.repo_context.subprocess.run",
                return_value=result,
            ):
                with self.assertRaises(RepoVerificationError) as ctx:
                    resolve_repo_context(
                        Path(td).resolve(),
                        expected_repo_id="demo",
                        configured_repo_id="demo",
                        expected_revision_ref="HEAD",
                    )

        self.assertEqual(ctx.exception.failure.code, "not_git_repo")

    def test_missing_revision_in_complete_repo_is_commit_missing(self):
        td, repo, _sha = self._repo()
        self.addCleanup(td.cleanup)

        with self.assertRaises(RepoVerificationError) as ctx:
            resolve_repo_context(
                repo,
                expected_repo_id="demo",
                configured_repo_id="demo",
                expected_revision_ref="refs/heads/does-not-exist",
            )

        self.assertEqual(ctx.exception.failure.code, "commit_missing")

    def test_missing_revision_in_shallow_repo_is_shallow_or_unfetched(self):
        td, source, first_sha = self._repo()
        self.addCleanup(td.cleanup)
        (source / "src" / "example.cpp").write_text(
            "void Foo::bar() { return; }\nvoid newer() {}\n", encoding="utf-8",
        )
        self._git(source, "add", ".")
        self._git(source, "commit", "-m", "newer")

        clone_parent = tempfile.TemporaryDirectory()
        self.addCleanup(clone_parent.cleanup)
        shallow = Path(clone_parent.name).resolve() / "shallow"
        subprocess.run(
            ["git", "clone", "--depth", "1", source.as_uri(), str(shallow)],
            check=True,
            capture_output=True,
        )

        with self.assertRaises(RepoVerificationError) as ctx:
            resolve_repo_context(
                shallow,
                expected_repo_id="demo",
                configured_repo_id="demo",
                expected_revision_ref=first_sha,
            )

        self.assertEqual(ctx.exception.failure.code, "shallow_or_unfetched")


if __name__ == "__main__":
    unittest.main()
