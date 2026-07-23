"""CodeLocator의 opt-in 원문 인용구를 Git blob 바이트로 검증한다."""

import unittest

from project_brain.code_verify import verify_code_quotes
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
