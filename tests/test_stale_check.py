"""stale-check / mark-checked 로직·CLI 테스트.

자기완결: 인라인 객체 빌더 + 가짜 git_runner만 쓴다(실 git·네트워크 없음).
spec: docs/superpowers/specs/2026-06-14-bb2-brain-stale-check-design.md
"""
import unittest

from project_brain.store import BrainStore


def fake_git_runner(target_head, changed):
    """changed: {(from_commit, path): change_type}. 없는 키는 '안 바뀜'(빈 출력).

    git diff args 형태: ["diff", "--name-status", "FROM..TARGET", "--", "PATH"].
    """
    calls = []

    def run(args):
        calls.append(args)
        if args[:1] == ["fetch"]:
            return ""
        if args[:1] == ["rev-parse"]:
            return target_head + "\n"
        if args[:2] == ["diff", "--name-status"]:
            from_commit = args[2].split("..")[0]
            path = args[4]
            ct = changed.get((from_commit, path))
            return f"{ct}\t{path}\n" if ct else ""
        raise AssertionError(f"unexpected git args: {args}")

    run.calls = calls
    return run


def code_locator(cid, *, path, commit_sha, symbol="sym", line_start=10, line_end=20):
    from project_brain.objbase import base
    return base({
        "id": cid, "kind": "CodeLocator", "status": "reviewed", "truth_role": "reference",
        "title": f"Code: {symbol}", "repo": "bb2_client", "path": path, "symbol": symbol,
        "line_start": line_start, "line_end": line_end,
        "locator_source": "rg", "verified_at": "2026-06-12T00:00:00Z",
        "commit_sha": commit_sha, "evidence_refs": [],
    }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")


def domain_mapping(mid, *, code_locator_ids, status="reviewed"):
    from project_brain.objbase import base
    obj = {
        "id": mid, "kind": "DomainMapping", "status": status, "truth_role": "domain",
        "title": f"Mapping {mid}", "context_id": "context.x", "mapping_key": mid,
        "canonical_summary": "요약", "meaning": "의미", "boundary": "경계",
        "glossary_term_ids": [], "decision_record_ids": [],
        "code_locator_ids": code_locator_ids,
        "evidence_refs": ["ev.x"] if status == "reviewed" else [],
    }
    if status == "candidate":
        obj["candidate"] = {"candidate_state": "ready_for_review", "candidate_source": "spec"}
    return base(obj, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")


def _store(*objs):
    return BrainStore({o["id"]: o for o in objs})


class ComputeClosureTest(unittest.TestCase):
    def test_blocking_is_reviewed_only_superseded_excluded_candidate_nonblocking(self):
        from project_brain.stale_check import compute_closure
        store = _store(
            code_locator("code.shared", path="a/X.cpp", commit_sha="SHA1"),
            domain_mapping("m.r1", code_locator_ids=["code.shared"], status="reviewed"),
            domain_mapping("m.r2", code_locator_ids=["code.shared"], status="reviewed"),
            domain_mapping("m.cand", code_locator_ids=["code.shared"], status="candidate"),
            domain_mapping("m.sup", code_locator_ids=["code.shared"], status="superseded"),
        )
        closure = compute_closure(store, "code.shared")
        self.assertEqual(closure["blocking"], ["m.r1", "m.r2"])
        self.assertEqual(closure["nonblocking"], ["m.cand", "m.sup"])

    def test_locator_with_no_referencing_mappings(self):
        from project_brain.stale_check import compute_closure
        store = _store(code_locator("code.lonely", path="a/Y.cpp", commit_sha="SHA1"))
        self.assertEqual(compute_closure(store, "code.lonely"),
                         {"blocking": [], "nonblocking": []})


class CoverageReportTest(unittest.TestCase):
    def test_covered_vs_uncovered_with_reason_and_code_evref_flag(self):
        from project_brain.objbase import base
        from project_brain.stale_check import coverage_report
        # code를 가리키는 EvidenceRef(ref_type=='code_locator')만 가진 uncovered 매핑.
        code_evref = base({
            "id": "evref.code", "kind": "EvidenceRef", "status": "reviewed",
            "truth_role": "reference", "title": "code ref",
            "evidence_manifest_id": "ev.m", "ref_type": "code_locator",
            "locator": {"object_id": "code.z"}, "summary": "코드 근거",
        }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")
        m_code_evref = domain_mapping("m.codeevref", code_locator_ids=[])
        m_code_evref["evidence_refs"] = ["evref.code"]
        store = _store(
            code_locator("code.a", path="a/X.cpp", commit_sha="SHA1"),
            domain_mapping("m.covered", code_locator_ids=["code.a"]),
            domain_mapping("m.empty", code_locator_ids=[]),
            code_evref, m_code_evref,
        )
        report = coverage_report(store)
        self.assertEqual(report["covered_mappings"], ["m.covered"])
        unc = {u["mapping_id"]: u for u in report["uncovered_mappings"]}
        self.assertEqual(set(unc), {"m.empty", "m.codeevref"})
        self.assertEqual(unc["m.empty"]["skipped_reason"], "no_code_locator_ids")
        self.assertFalse(unc["m.empty"]["has_code_evidence_ref"])
        # m.codeevref는 code_locator_ids는 없지만 code EvidenceRef를 가짐 → subset 가시화.
        self.assertTrue(unc["m.codeevref"]["has_code_evidence_ref"])

    def test_missing_code_locator_ids_field_is_uncovered(self):
        from project_brain.objbase import base
        from project_brain.stale_check import coverage_report
        # code_locator_ids 키 자체가 없는 매핑도 uncovered(빈 것과 동급).
        m = base({
            "id": "m.nofield", "kind": "DomainMapping", "status": "reviewed",
            "truth_role": "domain", "title": "t", "context_id": "context.x",
            "mapping_key": "k", "canonical_summary": "s", "meaning": "m",
            "boundary": "b", "glossary_term_ids": [], "decision_record_ids": [],
            "evidence_refs": ["ev.x"],
        }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")
        store = _store(m)
        report = coverage_report(store)
        self.assertEqual([u["mapping_id"] for u in report["uncovered_mappings"]], ["m.nofield"])
        self.assertEqual(report["uncovered_mappings"][0]["skipped_reason"], "no_code_locator_ids")


class GitDetectionTest(unittest.TestCase):
    def test_resolve_target_head_fetches_then_rev_parse(self):
        from project_brain.stale_check import resolve_target_head
        runner = fake_git_runner("TARGETSHA", {})
        head = resolve_target_head(runner, fetch=True)
        self.assertEqual(head, "TARGETSHA")
        self.assertEqual(runner.calls[0], ["fetch", "origin", "develop"])
        self.assertEqual(runner.calls[1], ["rev-parse", "origin/develop"])

    def test_resolve_target_head_no_fetch_skips_fetch(self):
        from project_brain.stale_check import resolve_target_head
        runner = fake_git_runner("TARGETSHA", {})
        resolve_target_head(runner, fetch=False)
        self.assertEqual(runner.calls, [["rev-parse", "origin/develop"]])

    def test_path_changed_returns_change_type_when_changed(self):
        from project_brain.stale_check import path_changed
        runner = fake_git_runner("TARGET", {("SHA1", "a/X.cpp"): "M"})
        self.assertEqual(path_changed(runner, "SHA1", "TARGET", "a/X.cpp"), "M")

    def test_path_changed_returns_none_when_unchanged(self):
        from project_brain.stale_check import path_changed
        runner = fake_git_runner("TARGET", {})
        self.assertIsNone(path_changed(runner, "SHA1", "TARGET", "a/X.cpp"))

    def test_path_changed_rename_returns_status_token(self):
        # rename은 실제 git에서 R100\told\tnew 3컬럼이지만 path_changed는 첫 탭 토큰만 쓴다.
        from project_brain.stale_check import path_changed
        runner = fake_git_runner("TARGET", {("SHA1", "a/X.cpp"): "R100"})
        self.assertEqual(path_changed(runner, "SHA1", "TARGET", "a/X.cpp"), "R100")
