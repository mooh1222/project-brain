"""stale-check / mark-checked 로직·CLI 테스트.

자기완결: 인라인 객체 빌더 + 가짜 git_runner만 쓴다(실 git·네트워크 없음).
spec: docs/superpowers/specs/2026-06-14-project-brain-stale-check-design.md
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from project_brain import cli
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


def code_locator(cid, *, path, commit_sha, symbol="sym"):
    from project_brain.objbase import base
    return base({
        "id": cid, "kind": "CodeLocator", "status": "reviewed", "truth_role": "reference",
        "title": f"Code: {symbol}", "repo": "demoapp", "path": path, "symbol": symbol,
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


class StaleCheckTest(unittest.TestCase):
    def _corpus(self):
        return _store(
            code_locator("code.changed", path="a/Changed.cpp", commit_sha="SHA1"),
            code_locator("code.same", path="a/Same.cpp", commit_sha="SHA1"),
            domain_mapping("m.on_changed", code_locator_ids=["code.changed"]),
            domain_mapping("m.on_same", code_locator_ids=["code.same"]),
            domain_mapping("m.uncovered", code_locator_ids=[]),
        )

    def test_only_changed_file_mappings_become_candidates(self):
        from project_brain.stale_check import stale_check
        runner = fake_git_runner("TARGET", {("SHA1", "a/Changed.cpp"): "M"})
        report = stale_check(self._corpus(), git_runner=runner, fetch=True)
        self.assertEqual(report["target_head"], "TARGET")
        cand_ids = [c["mapping_id"] for c in report["candidates"]]
        self.assertEqual(cand_ids, ["m.on_changed"])  # 안 바뀐 code.same 매핑은 제외

    def test_locator_group_carries_closure_and_change_type(self):
        from project_brain.stale_check import stale_check
        runner = fake_git_runner("TARGET", {("SHA1", "a/Changed.cpp"): "M"})
        report = stale_check(self._corpus(), git_runner=runner, fetch=True)
        self.assertEqual(len(report["locator_group"]), 1)
        g = report["locator_group"][0]
        self.assertEqual(g["locator_id"], "code.changed")
        self.assertEqual(g["change_type"], "M")
        self.assertEqual(g["from_commit"], "SHA1")
        self.assertEqual(g["target_head"], "TARGET")
        self.assertEqual(g["blocking_affected_mapping_ids"], ["m.on_changed"])
        self.assertEqual(g["nonblocking_affected_mapping_ids"], [])

    def test_coverage_included(self):
        from project_brain.stale_check import stale_check
        runner = fake_git_runner("TARGET", {})
        report = stale_check(self._corpus(), git_runner=runner, fetch=True)
        uncovered_ids = {u["mapping_id"] for u in report["coverage"]["uncovered_mappings"]}
        self.assertIn("m.uncovered", uncovered_ids)
        self.assertEqual(report["candidates"], [])  # 아무것도 안 바뀌면 후보 0

    def test_explicit_target_head_skips_resolve(self):
        from project_brain.stale_check import stale_check
        runner = fake_git_runner("UNUSED", {("SHA1", "a/Changed.cpp"): "M"})
        report = stale_check(self._corpus(), git_runner=runner, target_head="GIVEN")
        self.assertEqual(report["target_head"], "GIVEN")
        # target_head 주면 fetch도 rev-parse도 안 함 — diff만 호출됨(회귀 방지로 둘 다 assert)
        self.assertTrue(all(c[0] != "fetch" for c in runner.calls))
        self.assertTrue(all(c[0] != "rev-parse" for c in runner.calls))

    def test_candidate_lists_multiple_stale_locators(self):
        # 한 매핑이 여러 locator를 가리키고 둘 다 바뀌면 candidate.stale_locators에 둘 다.
        from project_brain.stale_check import stale_check
        store = _store(
            code_locator("code.a", path="a/A.cpp", commit_sha="SHA1"),
            code_locator("code.b", path="a/B.cpp", commit_sha="SHA1"),
            domain_mapping("m.multi", code_locator_ids=["code.a", "code.b"]),
        )
        runner = fake_git_runner("TARGET",
                                 {("SHA1", "a/A.cpp"): "M", ("SHA1", "a/B.cpp"): "M"})
        report = stale_check(store, git_runner=runner, target_head="TARGET")
        cand = next(c for c in report["candidates"] if c["mapping_id"] == "m.multi")
        locs = {sl["locator_id"] for sl in cand["stale_locators"]}
        self.assertEqual(locs, {"code.a", "code.b"})

    def test_locator_without_commit_sha_skipped(self):
        from project_brain.stale_check import stale_check
        from project_brain.objbase import base
        loc_no_sha = base({
            "id": "code.nosha", "kind": "CodeLocator", "status": "reviewed",
            "truth_role": "reference", "title": "t", "repo": "demoapp",
            "path": "a/NoSha.cpp", "symbol": "s", "locator_source": "rg",
            "verified_at": "2026-06-12T00:00:00Z", "evidence_refs": [],
        }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")
        store = _store(loc_no_sha,
                       domain_mapping("m.x", code_locator_ids=["code.nosha"]))
        runner = fake_git_runner("TARGET", {})
        report = stale_check(store, git_runner=runner, target_head="TARGET")
        self.assertEqual(report["candidates"], [])  # 기준점 없는 locator는 건너뜀


class CliStaleCheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, argv, runner):
        out = io.StringIO()
        # CLI가 make_git_runner로 만드는 실제 runner를 가짜로 바꿔치기.
        with mock.patch("project_brain.stale_check.make_git_runner", return_value=runner), \
             mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_stale_check_outputs_candidates_and_coverage(self):
        for obj in (
            code_locator("code.changed", path="a/Changed.cpp", commit_sha="SHA1"),
            domain_mapping("m.on_changed", code_locator_ids=["code.changed"]),
            domain_mapping("m.uncovered", code_locator_ids=[]),
        ):
            BrainStore.save_object(self.root, obj)
        runner = fake_git_runner("TARGET", {("SHA1", "a/Changed.cpp"): "M"})
        rc, payload = self._run(
            ["stale-check", "--brain-root", str(self.root), "--no-fetch"], runner)
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual([c["mapping_id"] for c in payload["candidates"]], ["m.on_changed"])
        uncovered_ids = {u["mapping_id"] for u in payload["coverage"]["uncovered_mappings"]}
        self.assertIn("m.uncovered", uncovered_ids)
        self.assertEqual(payload["target_head"], "TARGET")
        # 읽기 전용: locator의 commit_sha가 그대로다(stale-check는 갱신 안 함).
        self.assertEqual(BrainStore.load(self.root).get("code.changed")["commit_sha"], "SHA1")

    def test_stale_check_git_error_returns_rc1(self):
        # --no-fetch 없이 실행 → resolve_target_head의 fetch 단계에서 GitError → rc=1.
        BrainStore.save_object(
            self.root, code_locator("code.a", path="a/X.cpp", commit_sha="SHA1"))

        def boom(args):
            from project_brain.stale_check import GitError
            raise GitError("git rev-parse origin/develop failed: unknown revision")

        rc, payload = self._run(
            ["stale-check", "--brain-root", str(self.root)], boom)
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("failed", payload["error"])


class MarkCheckedTest(unittest.TestCase):
    def _shared(self):
        # code.shared를 reviewed 매핑 둘이 공유 + candidate 1 + superseded 1이 가리킴.
        return _store(
            code_locator("code.shared", path="a/X.cpp", commit_sha="OLD"),
            domain_mapping("m.r1", code_locator_ids=["code.shared"]),
            domain_mapping("m.r2", code_locator_ids=["code.shared"]),
            domain_mapping("m.cand", code_locator_ids=["code.shared"], status="candidate"),
            domain_mapping("m.sup", code_locator_ids=["code.shared"], status="superseded"),
        )

    def test_full_closure_updates_keeps_lines_warns_candidate_only(self):
        from project_brain.stale_check import mark_checked
        store = self._shared()
        result = mark_checked(store, mapping_ids=["m.r1", "m.r2"],
                              checked_head="NEW", current_head="NEW",
                              now="2026-06-14T12:00:00Z")
        self.assertTrue(result["ok"])
        self.assertEqual([l["id"] for l in result["updated"]], ["code.shared"])
        loc = result["updated"][0]
        self.assertEqual(loc["commit_sha"], "NEW")
        self.assertEqual(loc["verified_at"], "2026-06-14T12:00:00Z")
        self.assertEqual(loc["updated_at"], "2026-06-14T12:00:00Z")
        # warning은 candidate만 — superseded(m.sup)는 현재 사실 아니라 제외(spec §4).
        self.assertEqual(result["warnings"],
                         [{"locator_id": "code.shared", "candidate_mapping_ids": ["m.cand"]}])
        # store 불변(저장은 CLI 책임) — 핵심 갱신 경로에서 원본 commit_sha가 안 바뀜.
        self.assertEqual(store.get("code.shared")["commit_sha"], "OLD")

    def test_partial_closure_blocks_and_does_not_update(self):
        from project_brain.stale_check import mark_checked
        result = mark_checked(self._shared(), mapping_ids=["m.r1"],
                              checked_head="NEW", current_head="NEW",
                              now="2026-06-14T12:00:00Z")
        self.assertTrue(result["ok"])
        self.assertEqual(result["updated"], [])  # m.r2가 빠져 갱신 안 함
        self.assertEqual(result["blocked"],
                         [{"locator_id": "code.shared", "missing_mapping_ids": ["m.r2"]}])

    def test_head_moved_guard(self):
        from project_brain.stale_check import mark_checked
        result = mark_checked(self._shared(), mapping_ids=["m.r1", "m.r2"],
                              checked_head="A", current_head="B",
                              now="2026-06-14T12:00:00Z")
        self.assertFalse(result["ok"])
        self.assertIn("head moved", result["error"])
        self.assertEqual(result["updated"], [])

    def test_rejects_non_reviewed_inputs(self):
        # blocker 방지(spec §4): 입력은 존재하는 reviewed DomainMapping만. candidate/
        # superseded/unknown이 섞이면 ok:False로 거부 — candidate가 빈 reviewed closure를
        # vacuous하게 통과시켜 commit_sha를 갱신하는 사각을 입력 단에서 막는다.
        from project_brain.stale_check import mark_checked
        result = mark_checked(self._shared(),
                              mapping_ids=["m.r1", "m.cand", "m.sup", "m.nope"],
                              checked_head="NEW", current_head="NEW",
                              now="2026-06-14T12:00:00Z")
        self.assertFalse(result["ok"])
        reasons = {x["id"]: x["reason"] for x in result["invalid_inputs"]}
        self.assertEqual(reasons["m.cand"], "status_candidate")
        self.assertEqual(reasons["m.sup"], "status_superseded")
        self.assertEqual(reasons["m.nope"], "unknown_id")
        self.assertEqual(result["updated"], [])  # 거부 시 아무것도 안 건드림

    def test_non_code_locator_id_in_code_locator_ids_skipped(self):
        # future bad data 방어(재리뷰 major): code_locator_ids에 비-CodeLocator id가 섞여도
        # commit_sha를 엉뚱한 kind 객체에 쓰지 않는다. reviewed 매핑이 GlossaryTerm을 잘못 가리킨 상황.
        from project_brain.objbase import base
        from project_brain.stale_check import mark_checked
        not_a_loc = base({
            "id": "g.notaloc", "kind": "GlossaryTerm", "status": "reviewed",
            "truth_role": "domain", "title": "용어", "context_id": "context.x",
            "term": "용어", "definition": "정의", "evidence_refs": ["ev.x"],
        }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")
        store = _store(
            domain_mapping("m.bad", code_locator_ids=["g.notaloc"]), not_a_loc)
        result = mark_checked(store, mapping_ids=["m.bad"],
                              checked_head="NEW", current_head="NEW",
                              now="2026-06-14T12:00:00Z")
        self.assertTrue(result["ok"])
        self.assertEqual(result["updated"], [])  # 비-CodeLocator는 건너뜀
        self.assertEqual(store.get("g.notaloc")["updated_at"], "2026-06-12T00:00:00Z")


class CliMarkCheckedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for obj in (
            code_locator("code.shared", path="a/X.cpp", commit_sha="OLD"),
            domain_mapping("m.r1", code_locator_ids=["code.shared"]),
            domain_mapping("m.r2", code_locator_ids=["code.shared"]),
            domain_mapping("m.cand", code_locator_ids=["code.shared"], status="candidate"),
        ):
            BrainStore.save_object(self.root, obj)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, argv, runner):
        out = io.StringIO()
        with mock.patch("project_brain.stale_check.make_git_runner", return_value=runner), \
             mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_full_closure_persists_updated_locator(self):
        runner = fake_git_runner("NEW", {})  # 현재 develop = NEW
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "m.r1", "m.r2", "--checked-head", "NEW", "--no-fetch"],
            runner)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["updated"], ["code.shared"])
        # 디스크에 갱신 반영 — commit_sha=NEW.
        loc = BrainStore.load(self.root).get("code.shared")
        self.assertEqual(loc["commit_sha"], "NEW")
        # candidate가 같은 locator를 가리키므로 CLI 출력 warnings에 전달된다.
        self.assertEqual(payload["warnings"],
                         [{"locator_id": "code.shared", "candidate_mapping_ids": ["m.cand"]}])

    def test_partial_closure_blocked_rc0_disk_unchanged(self):
        runner = fake_git_runner("NEW", {})
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "m.r1", "--checked-head", "NEW", "--no-fetch"],
            runner)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["updated"], [])
        self.assertEqual(payload["blocked"],
                         [{"locator_id": "code.shared", "missing_mapping_ids": ["m.r2"]}])
        # 갱신 안 됐으니 commit_sha 그대로.
        self.assertEqual(BrainStore.load(self.root).get("code.shared")["commit_sha"], "OLD")

    def test_head_moved_returns_rc1_disk_unchanged(self):
        runner = fake_git_runner("NEW", {})  # 현재 develop은 NEW인데
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "m.r1", "m.r2", "--checked-head", "STALE", "--no-fetch"],
            runner)
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("head moved", payload["error"])
        self.assertEqual(BrainStore.load(self.root).get("code.shared")["commit_sha"], "OLD")

    def test_mixed_update_and_block_in_one_call(self):
        # 한 호출에서 X는 closure 완전(갱신), Y는 부분(blocked) — 독립 처리 + 디스크 반영.
        for obj in (
            code_locator("code.x", path="a/X2.cpp", commit_sha="OLD"),
            code_locator("code.y", path="a/Y2.cpp", commit_sha="OLD"),
            domain_mapping("m.x1", code_locator_ids=["code.x"]),
            domain_mapping("m.x2", code_locator_ids=["code.x"]),
            domain_mapping("m.y1", code_locator_ids=["code.y"]),
            domain_mapping("m.y2", code_locator_ids=["code.y"]),
        ):
            BrainStore.save_object(self.root, obj)
        runner = fake_git_runner("NEW", {})
        # m.x1+m.x2로 code.x는 완전, m.y1만 줘 code.y는 m.y2가 빠져 blocked.
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "m.x1", "m.x2", "m.y1", "--checked-head", "NEW", "--no-fetch"],
            runner)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["updated"], ["code.x"])
        self.assertEqual(payload["blocked"],
                         [{"locator_id": "code.y", "missing_mapping_ids": ["m.y2"]}])
        loaded = BrainStore.load(self.root)
        self.assertEqual(loaded.get("code.x")["commit_sha"], "NEW")  # 완전 → 갱신
        self.assertEqual(loaded.get("code.y")["commit_sha"], "OLD")  # blocked → 불변

    def test_candidate_input_rejected_rc1_disk_unchanged(self):
        # candidate 매핑을 --mappings로 주면 입력 검증에서 거부(rc=1), locator 불변(blocker 방지).
        runner = fake_git_runner("NEW", {})
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "m.cand", "--checked-head", "NEW", "--no-fetch"],
            runner)
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["invalid_inputs"][0]["reason"], "status_candidate")
        self.assertEqual(BrainStore.load(self.root).get("code.shared")["commit_sha"], "OLD")
