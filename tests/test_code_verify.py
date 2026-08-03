"""CodeLocator의 opt-in 원문 인용구를 Git blob 바이트로 검증한다."""

import subprocess
import tempfile
import unittest
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest import mock

from project_brain.code_verify import (
    CodeVerificationError,
    make_git_blob_reader,
    verify_code_quotes,
    verify_locator_for_write,
)
from project_brain.repo_context import resolve_repo_context
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


class VerifyLocatorForWriteTest(unittest.TestCase):
    def _git(self, repo, *args):
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    def _committed_repo(self, files):
        td = tempfile.TemporaryDirectory()
        repo = Path(td.name).resolve()
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
        context = resolve_repo_context(
            repo,
            expected_repo_id="demo",
            configured_repo_id="demo",
            expected_revision_ref="HEAD",
        )
        return td, repo, sha, context

    def _locator(self, sha, **extra):
        value = {
            "id": "code.ctx.anchor",
            "kind": "CodeLocator",
            "repo": "demo",
            "commit_sha": sha,
            "path": "src/example.cpp",
            "symbol": "Foo::bar",
            "verified_quote": "void Foo::bar() { return; }",
            "verified_at": "1900-01-01T00:00:00+09:00",
        }
        value.update(extra)
        return value

    def _failure_code(self, locator, context, *, manual=None):
        with self.assertRaises(CodeVerificationError) as ctx:
            verify_locator_for_write(
                locator,
                repo=context,
                manual_symbol_verification=manual,
            )
        return ctx.exception.failure.code

    def test_commit_missing_has_distinct_error_code(self):
        td, _repo, _sha, context = self._committed_repo({
            "src/example.cpp": b"void Foo::bar() { return; }\n",
        })
        self.addCleanup(td.cleanup)

        code = self._failure_code(
            self._locator("0" * 40),
            context,
        )

        self.assertEqual(code, "commit_missing")

    def test_sha256_commit_abbreviation_is_not_an_exact_commit_sha(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        repo = Path(td.name).resolve()
        self._git(repo, "init", "--object-format=sha256")
        self._git(repo, "config", "user.email", "test@example.com")
        self._git(repo, "config", "user.name", "Test User")
        (repo / "src").mkdir()
        (repo / "src" / "example.cpp").write_bytes(
            b"void Foo::bar() { return; }\n",
        )
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-m", "fixture")
        full_sha = self._git(repo, "rev-parse", "HEAD").stdout.decode().strip()
        self.assertEqual(len(full_sha), 64)
        context = resolve_repo_context(
            repo,
            expected_repo_id="demo",
            configured_repo_id="demo",
            expected_revision_ref="HEAD",
        )

        code = self._failure_code(self._locator(full_sha[:40]), context)

        self.assertEqual(code, "commit_missing")

    def test_commit_not_reachable_has_distinct_error_code(self):
        td, repo, sha, context = self._committed_repo({
            "src/example.cpp": b"void Foo::bar() { return; }\n",
        })
        self.addCleanup(td.cleanup)
        self._git(repo, "checkout", "-b", "side")
        (repo / "side.txt").write_text("side\n", encoding="utf-8")
        self._git(repo, "add", ".")
        self._git(repo, "commit", "-m", "side")
        side_sha = self._git(repo, "rev-parse", "HEAD").stdout.decode().strip()
        self.assertNotEqual(side_sha, sha)

        code = self._failure_code(self._locator(side_sha), context)

        self.assertEqual(code, "commit_not_reachable")

    def test_shallow_history_boundary_is_not_reported_as_unreachable(self):
        td, source, ancestor_sha, _source_context = self._committed_repo({
            "src/example.cpp": b"void Foo::bar() { return; }\n",
        })
        self.addCleanup(td.cleanup)
        for number in (2, 3):
            (source / "sequence.txt").write_text(f"{number}\n", encoding="utf-8")
            self._git(source, "add", ".")
            self._git(source, "commit", "-m", f"fixture {number}")

        clone_parent = tempfile.TemporaryDirectory()
        self.addCleanup(clone_parent.cleanup)
        shallow = Path(clone_parent.name).resolve() / "shallow"
        subprocess.run(
            ["git", "clone", "--depth", "1", source.as_uri(), str(shallow)],
            check=True,
            capture_output=True,
        )
        self._git(shallow, "fetch", "--depth", "1", "origin", ancestor_sha)
        context = resolve_repo_context(
            shallow,
            expected_repo_id="demo",
            configured_repo_id="demo",
            expected_revision_ref="HEAD",
        )
        ancestry = subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                ancestor_sha,
                context.target_revision_sha,
            ],
            cwd=shallow,
            capture_output=True,
        )
        self.assertEqual(ancestry.returncode, 1)

        code = self._failure_code(self._locator(ancestor_sha), context)

        self.assertEqual(code, "shallow_or_unfetched")

    def test_merge_base_operational_error_is_not_semantic_unreachable(self):
        td, _repo, sha, context = self._committed_repo({
            "src/example.cpp": b"void Foo::bar() { return; }\n",
        })
        self.addCleanup(td.cleanup)
        broken_context = replace(context, target_revision_sha="f" * 40)

        with self.assertRaises(CodeVerificationError) as ctx:
            verify_locator_for_write(self._locator(sha), repo=broken_context)

        self.assertEqual(ctx.exception.failure.code, "commit_missing")
        self.assertIn("merge-base failed", ctx.exception.failure.detail)

    def test_path_missing_at_commit_has_distinct_error_code(self):
        td, _repo, sha, context = self._committed_repo({
            "src/example.cpp": b"void Foo::bar() { return; }\n",
        })
        self.addCleanup(td.cleanup)

        code = self._failure_code(
            self._locator(sha, path="src/missing.cpp"),
            context,
        )

        self.assertEqual(code, "path_missing_at_commit")

    def test_path_with_nul_is_structured_path_missing(self):
        td, _repo, sha, context = self._committed_repo({
            "src/example.cpp": b"void Foo::bar() { return; }\n",
        })
        self.addCleanup(td.cleanup)

        code = self._failure_code(
            self._locator(sha, path="src/example.cpp\x00unexpected"),
            context,
        )

        self.assertEqual(code, "path_missing_at_commit")

    def test_non_blob_path_has_blob_read_failed_error_code(self):
        td, _repo, sha, context = self._committed_repo({
            "src/example.cpp": b"void Foo::bar() { return; }\n",
        })
        self.addCleanup(td.cleanup)

        code = self._failure_code(self._locator(sha, path="src"), context)

        self.assertEqual(code, "blob_read_failed")

    def test_quote_not_found_has_distinct_error_code(self):
        td, _repo, sha, context = self._committed_repo({
            "src/example.cpp": b"void Foo::bar() { return; }\n",
        })
        self.addCleanup(td.cleanup)

        code = self._failure_code(
            self._locator(sha, verified_quote="void missing() {}"),
            context,
        )

        self.assertEqual(code, "quote_not_found")

    def test_quote_with_unpaired_surrogate_is_structured_quote_not_found(self):
        td, _repo, sha, context = self._committed_repo({
            "src/example.cpp": b"void Foo::bar() { return; }\n",
        })
        self.addCleanup(td.cleanup)

        code = self._failure_code(
            self._locator(sha, verified_quote="\ud800"),
            context,
        )

        self.assertEqual(code, "quote_not_found")

    def test_symbol_mismatch_has_distinct_error_code(self):
        td, _repo, sha, context = self._committed_repo({
            "src/example.cpp": b"void Other::bar() { return; }\n",
        })
        self.addCleanup(td.cleanup)

        code = self._failure_code(
            self._locator(
                sha,
                verified_quote="void Other::bar() { return; }",
                symbol="Foo::bar",
            ),
            context,
        )

        self.assertEqual(code, "symbol_mismatch")

    def test_unsupported_symbol_without_manual_evidence_is_rejected(self):
        quote = "def run(): pass"
        td, _repo, sha, context = self._committed_repo({
            "tools/example.py": (quote + "\n").encode(),
        })
        self.addCleanup(td.cleanup)

        code = self._failure_code(
            self._locator(
                sha,
                path="tools/example.py",
                symbol="run",
                verified_quote=quote,
            ),
            context,
        )

        self.assertEqual(code, "symbol_verification_missing")

    def test_manual_symbol_evidence_requires_all_fields_and_exact_identity(self):
        quote = "def run(): pass"
        td, _repo, sha, context = self._committed_repo({
            "tools/example.py": (quote + "\n").encode(),
        })
        self.addCleanup(td.cleanup)
        target = self._locator(
            sha,
            path="tools/example.py",
            symbol="run",
            verified_quote=quote,
        )
        complete = {
            "reviewer": "reviewer@example.com",
            "repo": "demo",
            "commit": sha,
            "path": "tools/example.py",
            "symbol": "run",
            "quote_sha256": sha256(quote.encode()).hexdigest(),
            "rationale": "Python parser adapter is not supported in this release.",
        }

        for missing in complete:
            with self.subTest(missing=missing):
                manual = dict(complete)
                manual.pop(missing)
                self.assertEqual(
                    self._failure_code(target, context, manual=manual),
                    "symbol_verification_missing",
                )
        wrong_repo = dict(complete, repo="other")
        self.assertEqual(
            self._failure_code(target, context, manual=wrong_repo),
            "symbol_verification_missing",
        )

        result = verify_locator_for_write(
            target,
            repo=context,
            manual_symbol_verification=complete,
        )
        self.assertEqual(result.symbol_status, "manual_verified")

    def test_manual_symbol_evidence_must_be_a_mapping(self):
        quote = "def run(): pass"
        td, _repo, sha, context = self._committed_repo({
            "tools/example.py": (quote + "\n").encode(),
        })
        self.addCleanup(td.cleanup)
        target = self._locator(
            sha,
            path="tools/example.py",
            symbol="run",
            verified_quote=quote,
        )
        non_mapping = [
            "reviewer",
            "repo",
            "commit",
            "path",
            "symbol",
            "quote_sha256",
            "rationale",
        ]

        code = self._failure_code(target, context, manual=non_mapping)

        self.assertEqual(code, "symbol_verification_missing")

    def test_success_returns_quote_hash_and_engine_timestamp(self):
        quote = "void Foo::bar() { return; }"
        td, _repo, sha, context = self._committed_repo({
            "src/example.cpp": (quote + "\n").encode(),
        })
        self.addCleanup(td.cleanup)
        target = self._locator(sha)

        with mock.patch(
            "project_brain.code_verify.now_kst",
            return_value="2026-07-28T12:34:56+09:00",
        ):
            result = verify_locator_for_write(target, repo=context)

        self.assertEqual(result.quote_sha256, sha256(quote.encode()).hexdigest())
        self.assertEqual(result.verified_at, "2026-07-28T12:34:56+09:00")
        self.assertEqual(result.symbol_status, "verified")
        self.assertEqual(result.locator["verified_at"], result.verified_at)
        self.assertNotEqual(result.locator["verified_at"], target["verified_at"])

    def test_locator_repo_must_match_resolved_repo_context(self):
        td, _repo, sha, context = self._committed_repo({
            "src/example.cpp": b"void Foo::bar() { return; }\n",
        })
        self.addCleanup(td.cleanup)

        code = self._failure_code(
            self._locator(sha, repo="other"),
            context,
        )

        self.assertEqual(code, "repo_identity_mismatch")
