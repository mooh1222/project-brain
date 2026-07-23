"""CodeLocator의 opt-in 원문 인용구를 Git blob 바이트로 검증한다."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from project_brain.code_verify import make_git_blob_reader, verify_code_quotes
from project_brain.stale_check import GitError


def locator(locator_id, **extra):
    obj = {
        "id": locator_id,
        "kind": "CodeLocator",
        "commit_sha": "abc123",
        "path": "src/example.cpp",
    }
    obj.update(extra)
    return obj


class VerifyCodeQuotesTest(unittest.TestCase):
    def _git(self, repo, *args):
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    def _committed_repo(self, files):
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name)
        self._git(repo, "init")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Test User")
        for path, content in files.items():
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-m", "fixture")
        sha = self._git(repo, "rev-parse", "HEAD").stdout.decode().strip()
        return td, repo, sha

    def test_default_reader_uses_committed_blob_not_modified_working_tree(self):
        td, repo, sha = self._committed_repo({"src/example.cpp": b"return committed;\r\n"})
        self.addCleanup(td.cleanup)
        (repo / "src/example.cpp").write_bytes(b"return working-tree-only;\r\n")

        result = verify_code_quotes(
            [locator("code.committed", commit_sha=sha, path="src/example.cpp",
                     verified_quote="return committed;\r\n")],
            blob_reader=make_git_blob_reader(repo),
        )

        self.assertEqual(result, {"ok": True, "checked": 1, "skipped": 0, "failures": []})

    def test_default_reader_rejects_directory_tree_even_if_listing_matches_quote(self):
        td, repo, sha = self._committed_repo({"src/quoted-name.cpp": b"return content;\n"})
        self.addCleanup(td.cleanup)

        result = verify_code_quotes(
            [locator("code.tree", commit_sha=sha, path="src", verified_quote="quoted-name.cpp")],
            blob_reader=make_git_blob_reader(repo),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"][0]["locator_id"], "code.tree")
        self.assertEqual(result["failures"][0]["reason"], "blob_read_failed")

    def test_matches_tabs_newlines_and_crlf_as_exact_bytes(self):
        quote = "if (ready)\r\n\treturn value;\r\n"
        calls = []

        def read_blob(commit, path):
            calls.append((commit, path))
            return b"void run() {\r\n" + quote.encode("utf-8") + b"}\r\n"

        result = verify_code_quotes(
            [locator("code.crlf", verified_quote=quote)], blob_reader=read_blob)

        self.assertEqual(result, {"ok": True, "checked": 1, "skipped": 0, "failures": []})
        self.assertEqual(calls, [("abc123", "src/example.cpp")])

    def test_collapsed_whitespace_is_not_a_match(self):
        result = verify_code_quotes(
            [locator("code.spaces", verified_quote="if (ready) return value;")],
            blob_reader=lambda _commit, _path: b"if (ready)\n\treturn value;\n",
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["failures"], [
            {"locator_id": "code.spaces", "reason": "quote_not_found"},
        ])

    def test_missing_verified_quote_is_skipped_without_reading_blob(self):
        result = verify_code_quotes(
            [locator("code.legacy")],
            blob_reader=lambda _commit, _path: self.fail("legacy locator must be skipped"),
        )

        self.assertEqual(result, {"ok": True, "checked": 0, "skipped": 1, "failures": []})

    def test_present_invalid_quote_values_fail_without_reading_blob(self):
        result = verify_code_quotes(
            [locator("code.empty", verified_quote=""),
             locator("code.none", verified_quote=None),
             locator("code.number", verified_quote=7)],
            blob_reader=lambda _commit, _path: self.fail("invalid quote must not read blob"),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["checked"], 3)
        self.assertEqual(result["failures"], [
            {"locator_id": "code.empty", "reason": "invalid_verified_quote"},
            {"locator_id": "code.none", "reason": "invalid_verified_quote"},
            {"locator_id": "code.number", "reason": "invalid_verified_quote"},
        ])

    def test_missing_or_invalid_locator_anchor_is_structured_failure(self):
        result = verify_code_quotes(
            [locator("code.no-commit", verified_quote="x", commit_sha=None),
             locator("code.no-path", verified_quote="x", path=""),
             locator("code.bad-commit", verified_quote="x", commit_sha=3),
             locator("code.bad-path", verified_quote="x", path=3)],
            blob_reader=lambda _commit, _path: self.fail("invalid anchor must not read blob"),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"], [
            {"locator_id": "code.bad-commit", "reason": "invalid_commit"},
            {"locator_id": "code.bad-path", "reason": "invalid_path"},
            {"locator_id": "code.no-commit", "reason": "missing_commit"},
            {"locator_id": "code.no-path", "reason": "missing_path"},
        ])

    def test_blob_reader_errors_are_structured_and_deterministic(self):
        def read_blob(_commit, _path):
            raise GitError("git show failed: missing blob")

        result = verify_code_quotes(
            [locator("code.z", verified_quote="z"), locator("code.a", verified_quote="a")],
            blob_reader=read_blob,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["failures"], [
            {"locator_id": "code.a", "reason": "blob_read_failed", "error": "git show failed: missing blob"},
            {"locator_id": "code.z", "reason": "blob_read_failed", "error": "git show failed: missing blob"},
        ])
