"""stale-check / mark-checked 로직·CLI 테스트.

자기완결: 인라인 객체 빌더 + 가짜 git_runner만 쓴다(실 git·네트워크 없음).
spec: docs/superpowers/specs/2026-06-14-project-brain-stale-check-design.md
"""
import io
import hashlib
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from project_brain import cli
from project_brain.code_verify import VerifiedLocator
from project_brain.id_grammar import format_id, parse_id
from project_brain.mutation import (
    MutationOperation,
    MutationRequest,
    MutationService,
    corpus_fingerprint,
)
from project_brain.repo_context import RepoContext, resolve_repo_context
from project_brain.store import BrainStore

ENGINE_SHA = "e" * 40


def fake_git_runner(target_head, changed, *, merge_base=None):
    """changed: {(from_commit, path): change_type}. 없는 키는 '안 바뀜'(빈 출력).
    merge_base: {from_commit: base_sha}. 없는 from_commit은 자기 자신을 base로 반환
    = target_head의 조상(머지됨)으로 본다(기본 — 기존 테스트 보존).

    git diff args 형태: ["diff", "--name-status", "FROM..TARGET", "--", "PATH"].
    """
    merge_base = merge_base or {}
    calls = []

    def run(args):
        calls.append(args)
        if args[:1] == ["fetch"]:
            return ""
        if args[:1] == ["rev-parse"]:
            return target_head + "\n"
        if args[:1] == ["merge-base"]:
            fc = args[1]
            return merge_base.get(fc, fc) + "\n"
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
    cid = format_id(
        "CodeLocator",
        ctx="x",
        anchor_key=cid.rsplit(".", 1)[-1],
    )
    return base({
        "id": cid, "kind": "CodeLocator", "status": "reviewed", "truth_role": "reference",
        "title": f"Code: {symbol}", "repo": "demoapp", "path": path, "symbol": symbol,
        "locator_source": "rg", "verified_at": "2026-06-12T00:00:00Z",
        "verified_quote": f"synthetic quote for {symbol}",
        "commit_sha": commit_sha, "evidence_refs": [],
    }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")


def domain_mapping(mid, *, code_locator_ids, status="reviewed"):
    from project_brain.objbase import base
    mid = format_id(
        "DomainMapping",
        ctx="x",
        key=mid.rsplit(".", 1)[-1].replace("_", "-"),
    )
    canonical_locator_ids = []
    for cid in code_locator_ids:
        kind = "GlossaryTerm" if cid.startswith("g.") else "CodeLocator"
        field = "key" if kind == "GlossaryTerm" else "anchor_key"
        canonical_locator_ids.append(format_id(
            kind,
            ctx="x",
            **{field: cid.rsplit(".", 1)[-1].replace("_", "-")},
        ))
    obj = {
        "id": mid, "kind": "DomainMapping", "status": status, "truth_role": "domain",
        "title": f"Mapping {mid}", "context_id": "context.x",
        "mapping_key": parse_id(mid, "DomainMapping").key,
        "canonical_summary": "요약", "meaning": "의미", "boundary": "경계",
        "glossary_term_ids": [], "decision_record_ids": [],
        "code_locator_ids": canonical_locator_ids,
        "evidence_refs": ["evref.x.source"] if status == "reviewed" else [],
    }
    if status == "candidate":
        obj["candidate"] = {"candidate_state": "ready_for_review", "candidate_source": "spec"}
    return base(obj, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")


def lint_support_objects():
    """MutationService의 merged-store lint를 만족하는 공통 근거·컨텍스트."""
    from project_brain.objbase import base

    timestamp = "2026-06-12T00:00:00Z"
    manifest = base({
        "id": "manifest.x.source",
        "kind": "EvidenceManifest",
        "status": "reviewed",
        "truth_role": "source",
        "title": "stale-check synthetic source",
        "source_type": "spec",
        "locator": "spec://stale-check",
        "captured_at": timestamp,
        "captured_by": "test",
        "sensitivity": "internal",
        "acl": ["team"],
        "redaction_status": "approved",
    }, tags=["x"], created_at=timestamp, updated_at=timestamp)
    evidence_ref = base({
        "id": "evref.x.source",
        "kind": "EvidenceRef",
        "status": "reviewed",
        "truth_role": "reference",
        "title": "stale-check synthetic evidence",
        "evidence_manifest_id": manifest["id"],
        "ref_type": "spec_section",
        "locator": {"section": "synthetic"},
        "summary": "stale-check synthetic evidence",
    }, tags=["x"], created_at=timestamp, updated_at=timestamp)
    context = base({
        "id": "context.x",
        "kind": "DomainContext",
        "status": "reviewed",
        "truth_role": "domain",
        "title": "Stale-check context",
        "context_key": "x",
        "project_id": "demoapp",
        "display_name": "Stale-check",
        "boundary_summary": "stale-check synthetic boundary",
        "in_scope": ["stale-check"],
        "out_of_scope": ["other"],
        "injection_profile": {"default_audience": "coding-agent"},
        "glossary_term_ids": [],
    }, tags=["x"], created_at=timestamp, updated_at=timestamp)
    return manifest, evidence_ref, context


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
        closure = compute_closure(store, "code.x.shared")
        self.assertEqual(closure["blocking"], ["mapping.x.r1", "mapping.x.r2"])
        self.assertEqual(closure["nonblocking"], ["mapping.x.cand", "mapping.x.sup"])

    def test_locator_with_no_referencing_mappings(self):
        from project_brain.stale_check import compute_closure
        store = _store(code_locator("code.lonely", path="a/Y.cpp", commit_sha="SHA1"))
        self.assertEqual(compute_closure(store, "code.x.lonely"),
                         {"blocking": [], "nonblocking": []})


class CoverageReportTest(unittest.TestCase):
    def test_covered_vs_uncovered_with_reason_and_code_evref_flag(self):
        from project_brain.objbase import base
        from project_brain.stale_check import coverage_report
        # code를 가리키는 EvidenceRef(ref_type=='code_locator')만 가진 uncovered 매핑.
        code_evref = base({
            "id": "evref.x.code", "kind": "EvidenceRef", "status": "reviewed",
            "truth_role": "reference", "title": "code ref",
            "evidence_manifest_id": "manifest.x.source", "ref_type": "code_locator",
            "locator": {"object_id": "code.x.z"}, "summary": "코드 근거",
        }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")
        m_code_evref = domain_mapping("m.codeevref", code_locator_ids=[])
        m_code_evref["evidence_refs"] = ["evref.x.code"]
        store = _store(
            code_locator("code.a", path="a/X.cpp", commit_sha="SHA1"),
            domain_mapping("m.covered", code_locator_ids=["code.a"]),
            domain_mapping("m.empty", code_locator_ids=[]),
            code_evref, m_code_evref,
        )
        report = coverage_report(store)
        self.assertEqual(report["covered_mappings"], ["mapping.x.covered"])
        unc = {u["mapping_id"]: u for u in report["uncovered_mappings"]}
        self.assertEqual(set(unc), {"mapping.x.empty", "mapping.x.codeevref"})
        self.assertEqual(unc["mapping.x.empty"]["skipped_reason"], "no_code_locator_ids")
        self.assertFalse(unc["mapping.x.empty"]["has_code_evidence_ref"])
        # m.codeevref는 code_locator_ids는 없지만 code EvidenceRef를 가짐 → subset 가시화.
        self.assertTrue(unc["mapping.x.codeevref"]["has_code_evidence_ref"])

    def test_missing_code_locator_ids_field_is_uncovered(self):
        from project_brain.objbase import base
        from project_brain.stale_check import coverage_report
        # code_locator_ids 키 자체가 없는 매핑도 uncovered(빈 것과 동급).
        m = base({
            "id": "mapping.x.nofield", "kind": "DomainMapping", "status": "reviewed",
            "truth_role": "domain", "title": "t", "context_id": "context.x",
            "mapping_key": "nofield", "canonical_summary": "s", "meaning": "m",
            "boundary": "b", "glossary_term_ids": [], "decision_record_ids": [],
            "evidence_refs": ["evref.x.source"],
        }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")
        store = _store(m)
        report = coverage_report(store)
        self.assertEqual(
            [u["mapping_id"] for u in report["uncovered_mappings"]],
            ["mapping.x.nofield"],
        )
        self.assertEqual(report["uncovered_mappings"][0]["skipped_reason"], "no_code_locator_ids")


class GitDetectionTest(unittest.TestCase):
    def test_make_git_runner_wraps_process_start_oserror(self):
        from project_brain.stale_check import GitError, make_git_runner
        with mock.patch("project_brain.stale_check.subprocess.run",
                        side_effect=FileNotFoundError("git executable missing")):
            with self.assertRaises(GitError) as ctx:
                make_git_runner("/tmp/repo")(["rev-parse", "HEAD"])
        self.assertIn("could not start", str(ctx.exception))

    def test_resolve_target_head_uses_configured_branch(self):
        from project_brain.stale_check import resolve_target_head
        runner = fake_git_runner("TARGETSHA", {})
        head = resolve_target_head(runner, default_branch="main", fetch=True)
        self.assertEqual(head, "TARGETSHA")
        self.assertEqual(runner.calls[0], ["fetch", "origin", "main"])
        self.assertEqual(runner.calls[1], ["rev-parse", "origin/main"])

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


class GitDagReachabilityTest(unittest.TestCase):
    def _git(self, cwd, *args):
        return subprocess.run(
            ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        ).stdout.strip()

    def _commit_file(self, work, path, content, message):
        (work / path).write_text(content, encoding="utf-8")
        self._git(work, "add", path)
        self._git(work, "commit", "-m", message)
        return self._git(work, "rev-parse", "HEAD")

    def test_anchor_reachability_uses_real_main_and_trunk_dags(self):
        from project_brain.stale_check import anchor_merged, make_git_runner, resolve_target_head

        for default_branch in ("main", "trunk"):
            with self.subTest(default_branch=default_branch), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                origin = root / "origin.git"
                work = root / "work"
                self._git(root, "init", "--bare", str(origin))
                self._git(root, "clone", str(origin), str(work))
                self._git(work, "config", "user.name", "Test User")
                self._git(work, "config", "user.email", "test@example.com")
                self._git(work, "checkout", "-b", default_branch)
                self._commit_file(work, "base.txt", "base\n", "base")
                self._git(work, "push", "-u", "origin", default_branch)

                # fast-forward와 일반 merge는 원래 앵커가 최종 브랜치의 조상으로 남는다.
                self._git(work, "checkout", "-b", "fast-forward")
                fast_forward_anchor = self._commit_file(
                    work, "fast-forward.txt", "ff\n", "fast forward anchor")
                self._git(work, "checkout", default_branch)
                self._git(work, "merge", "--ff-only", "fast-forward")

                self._git(work, "checkout", "-b", "normal-merge")
                normal_merge_anchor = self._commit_file(
                    work, "normal.txt", "normal\n", "normal merge anchor")
                self._git(work, "checkout", default_branch)
                self._commit_file(work, "main-only.txt", "main\n", "advance main")
                self._git(work, "merge", "--no-ff", "normal-merge", "-m", "normal merge")

                # 충돌을 해결한 일반 merge도 앵커는 보존하지만 파일 내용은 달라질 수 있다.
                self._commit_file(work, "conflict.txt", "base\n", "conflict base")
                self._git(work, "checkout", "-b", "conflict-merge")
                conflict_anchor = self._commit_file(
                    work, "conflict.txt", "feature\n", "conflict anchor")
                self._git(work, "checkout", default_branch)
                self._commit_file(work, "conflict.txt", "main\n", "main conflict change")
                conflict = subprocess.run(
                    ["git", "merge", "--no-ff", "conflict-merge", "-m", "conflict merge"],
                    cwd=work, capture_output=True, text=True,
                )
                self.assertNotEqual(conflict.returncode, 0)
                self._commit_file(work, "conflict.txt", "resolved\n", "resolve conflict")

                # squash, rebase, cherry-pick은 원래 commit 객체를 조상으로 보존하지 않는다.
                self._git(work, "checkout", "-b", "squash-source")
                squash_anchor = self._commit_file(work, "squash.txt", "squash\n", "squash anchor")
                self._git(work, "checkout", default_branch)
                self._git(work, "merge", "--squash", "squash-source")
                self._git(work, "commit", "-m", "squash merge")

                self._git(work, "checkout", "-b", "rebase-source")
                rebase_anchor = self._commit_file(work, "rebase.txt", "rebase\n", "rebase anchor")
                self._git(work, "checkout", default_branch)
                self._commit_file(work, "after-rebase.txt", "main\n", "advance for rebase")
                self._git(work, "checkout", "rebase-source")
                self._git(work, "rebase", default_branch)
                self._git(work, "checkout", default_branch)
                self._git(work, "merge", "--ff-only", "rebase-source")

                self._git(work, "checkout", "-b", "cherry-source")
                cherry_anchor = self._commit_file(work, "cherry.txt", "cherry\n", "cherry anchor")
                self._git(work, "checkout", default_branch)
                self._commit_file(work, "before-cherry.txt", "main\n", "advance for cherry-pick")
                self._git(work, "cherry-pick", cherry_anchor)
                self._git(work, "push", "origin", default_branch)

                runner = make_git_runner(work)
                target_head = resolve_target_head(runner, default_branch=default_branch)
                self.assertEqual(target_head, self._git(work, "rev-parse", f"origin/{default_branch}"))
                self.assertNotEqual(
                    subprocess.run(
                        ["git", "rev-parse", "--verify", "origin/develop"],
                        cwd=work, capture_output=True, text=True,
                    ).returncode,
                    0,
                )
                self.assertTrue(anchor_merged(runner, fast_forward_anchor, target_head))
                self.assertTrue(anchor_merged(runner, normal_merge_anchor, target_head))
                self.assertTrue(anchor_merged(runner, conflict_anchor, target_head))
                self.assertEqual((work / "conflict.txt").read_text(encoding="utf-8"), "resolved\n")
                self.assertFalse(anchor_merged(runner, squash_anchor, target_head))
                self.assertFalse(anchor_merged(runner, rebase_anchor, target_head))
                self.assertFalse(anchor_merged(runner, cherry_anchor, target_head))


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
        self.assertEqual(cand_ids, ["mapping.x.on-changed"])  # 안 바뀐 code.same 매핑은 제외

    def test_locator_group_carries_closure_and_change_type(self):
        from project_brain.stale_check import stale_check
        runner = fake_git_runner("TARGET", {("SHA1", "a/Changed.cpp"): "M"})
        report = stale_check(self._corpus(), git_runner=runner, fetch=True)
        self.assertEqual(len(report["locator_group"]), 1)
        g = report["locator_group"][0]
        self.assertEqual(g["locator_id"], "code.x.changed")
        self.assertEqual(g["change_type"], "M")
        self.assertEqual(g["from_commit"], "SHA1")
        self.assertEqual(g["target_head"], "TARGET")
        self.assertEqual(g["blocking_affected_mapping_ids"], ["mapping.x.on-changed"])
        self.assertEqual(g["nonblocking_affected_mapping_ids"], [])

    def test_coverage_included(self):
        from project_brain.stale_check import stale_check
        runner = fake_git_runner("TARGET", {})
        report = stale_check(self._corpus(), git_runner=runner, fetch=True)
        uncovered_ids = {u["mapping_id"] for u in report["coverage"]["uncovered_mappings"]}
        self.assertIn("mapping.x.uncovered", uncovered_ids)
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
        cand = next(
            c for c in report["candidates"] if c["mapping_id"] == "mapping.x.multi"
        )
        locs = {sl["locator_id"] for sl in cand["stale_locators"]}
        self.assertEqual(locs, {"code.x.a", "code.x.b"})

    def test_locator_without_commit_sha_skipped(self):
        from project_brain.stale_check import stale_check
        from project_brain.objbase import base
        loc_no_sha = base({
            "id": "code.x.nosha", "kind": "CodeLocator", "status": "reviewed",
            "truth_role": "reference", "title": "t", "repo": "demoapp",
            "path": "a/NoSha.cpp", "symbol": "s", "locator_source": "rg",
            "verified_at": "2026-06-12T00:00:00Z", "evidence_refs": [],
        }, tags=["x"], created_at="2026-06-12T00:00:00Z", updated_at="2026-06-12T00:00:00Z")
        store = _store(loc_no_sha,
                       domain_mapping("m.x", code_locator_ids=["code.nosha"]))
        runner = fake_git_runner("TARGET", {})
        report = stale_check(store, git_runner=runner, target_head="TARGET")
        self.assertEqual(report["candidates"], [])  # 기준점 없는 locator는 건너뜀

    def test_unmerged_anchor_excluded_from_candidates_and_listed(self):
        # 앵커 commit_sha=WORK가 develop 조상이 아니면(미머지) 거짓 신호 방지로 후보에서 빼고
        # unmerged_anchors에 별도 라벨. diff가 'D'를 내도 후보로 새지 않아야 한다.
        from project_brain.stale_check import stale_check
        store = _store(
            code_locator("code.work", path="a/Work.cpp", commit_sha="WORK"),
            domain_mapping("m.work", code_locator_ids=["code.work"]),
        )
        runner = fake_git_runner(
            "TARGET", {("WORK", "a/Work.cpp"): "D"}, merge_base={"WORK": "OLDBASE"})
        report = stale_check(store, git_runner=runner, target_head="TARGET")
        self.assertEqual(report["candidates"], [])          # 미머지 → 후보 아님
        self.assertEqual(
            [u["locator_id"] for u in report["unmerged_anchors"]],
            ["code.x.work"],
        )
        self.assertEqual(report["unmerged_anchors"][0]["reason"], "not_ancestor")
        self.assertEqual(
            report["unmerged_anchors"][0]["blocking_affected_mapping_ids"],
            ["mapping.x.work"],
        )

    def test_stale_check_cache_keeps_code_and_branch_axes_independent(self):
        from project_brain.stale_check import advisories_by_mapping, build_stale_set, stale_check
        store = _store(
            code_locator("code.changed", path="a/Changed.cpp", commit_sha="SHA1"),
            code_locator("code.same", path="a/Same.cpp", commit_sha="SHA1"),
            code_locator("code.work", path="a/Work.cpp", commit_sha="WORK"),
            domain_mapping("m.changed", code_locator_ids=["code.changed"]),
            domain_mapping("m.same", code_locator_ids=["code.same"]),
            domain_mapping("m.unmerged", code_locator_ids=["code.work"]),
            domain_mapping("m.both", code_locator_ids=["code.changed", "code.work"]),
        )
        report = stale_check(
            store,
            git_runner=fake_git_runner(
                "TARGET", {("SHA1", "a/Changed.cpp"): "M"},
                merge_base={"WORK": "OLDBASE"}),
            target_head="TARGET",
        )
        adv = advisories_by_mapping(build_stale_set(report, now="t"))
        self.assertNotIn("mapping.x.same", adv)  # unchanged + merged
        self.assertEqual((adv["mapping.x.changed"]["code_changed"],
                          adv["mapping.x.changed"]["unmerged_anchor"]),
                         (True, False))  # changed + merged
        self.assertEqual((adv["mapping.x.unmerged"]["code_changed"],
                          adv["mapping.x.unmerged"]["unmerged_anchor"]),
                         (False, True))  # unchanged + unmerged
        self.assertEqual((adv["mapping.x.both"]["code_changed"],
                          adv["mapping.x.both"]["unmerged_anchor"]),
                         (True, True))  # changed + unmerged

    def test_abbreviated_anchor_sha_detected_as_merged(self):
        # 약식 sha 함정 회귀: commit_sha가 약식이고 merge-base가 전체 sha를 돌려줘도
        # prefix 비교로 '머지됨'으로 본다 → 정상적으로 변경 감지(후보)된다.
        from project_brain.stale_check import stale_check
        store = _store(
            code_locator("code.ab", path="a/Ab.cpp", commit_sha="b27a23e385"),
            domain_mapping("m.ab", code_locator_ids=["code.ab"]),
        )
        runner = fake_git_runner(
            "TARGET", {("b27a23e385", "a/Ab.cpp"): "M"},
            merge_base={"b27a23e385": "b27a23e38598ffcaffee0011"})  # 전체 sha
        report = stale_check(store, git_runner=runner, target_head="TARGET")
        self.assertEqual(
            [c["mapping_id"] for c in report["candidates"]],
            ["mapping.x.ab"],
        )
        self.assertEqual(report["unmerged_anchors"], [])


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
        self.assertEqual(
            [c["mapping_id"] for c in payload["candidates"]],
            ["mapping.x.on-changed"],
        )
        uncovered_ids = {u["mapping_id"] for u in payload["coverage"]["uncovered_mappings"]}
        self.assertIn("mapping.x.uncovered", uncovered_ids)
        self.assertEqual(payload["target_head"], "TARGET")
        # 읽기 전용: locator의 commit_sha가 그대로다(stale-check는 갱신 안 함).
        self.assertEqual(
            BrainStore.load(self.root).get("code.x.changed")["commit_sha"],
            "SHA1",
        )

    def test_stale_check_surfaces_unmerged_anchors(self):
        for obj in (
            code_locator("code.work", path="a/Work.cpp", commit_sha="WORK"),
            domain_mapping("m.work", code_locator_ids=["code.work"]),
        ):
            BrainStore.save_object(self.root, obj)
        runner = fake_git_runner(
            "TARGET", {("WORK", "a/Work.cpp"): "D"}, merge_base={"WORK": "OLDBASE"})
        rc, payload = self._run(
            ["stale-check", "--brain-root", str(self.root), "--no-fetch"], runner)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["candidates"], [])
        self.assertEqual(
            [u["locator_id"] for u in payload["unmerged_anchors"]],
            ["code.x.work"],
        )

    def test_stale_check_write_cache_persists_stale_set(self):
        from project_brain.stale_check import load_stale_set
        for obj in (
            code_locator("code.changed", path="a/Changed.cpp", commit_sha="SHA1"),
            domain_mapping("m.on_changed", code_locator_ids=["code.changed"]),
        ):
            BrainStore.save_object(self.root, obj)
        runner = fake_git_runner("TARGET", {("SHA1", "a/Changed.cpp"): "M"})
        rc, payload = self._run(
            ["stale-check", "--brain-root", str(self.root), "--no-fetch", "--write-cache"],
            runner)
        self.assertEqual(rc, 0)
        self.assertIn("cache_written", payload)
        ss = load_stale_set(self.root)
        self.assertEqual(ss["stale_mapping_ids"], ["mapping.x.on-changed"])
        self.assertEqual(ss["target_head"], "TARGET")

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


class StaleSetCacheTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_build_stale_set_from_report(self):
        from project_brain.stale_check import build_stale_set
        report = {
            "target_head": "TARGET",
            "candidates": [{
                "mapping_id": "mapping.x.a", "mapping_key": "a",
                "stale_locators": [
                    {"locator_id": "code.x.x", "path": "a/X.cpp",
                     "change_type": "M", "from_commit": "SHA1"}],
            }],
        }
        ss = build_stale_set(report, now="2026-06-25T12:00:00+09:00")
        self.assertEqual(ss["target_head"], "TARGET")
        self.assertEqual(ss["computed_at"], "2026-06-25T12:00:00+09:00")
        self.assertEqual(ss["stale_mapping_ids"], ["mapping.x.a"])
        self.assertEqual(ss["detail"]["mapping.x.a"], {
            "code_changed": True, "unmerged_anchor": False, "unmerged_reasons": [],
            "locator_ids": ["code.x.x"], "from_commits": ["SHA1"],
            "change_types": ["M"], "paths": ["a/X.cpp"],
        })

    def test_build_stale_set_preserves_independent_code_and_branch_axes(self):
        from project_brain.stale_check import advisories_by_mapping, build_stale_set
        report = {
            "target_head": "TARGET",
            "candidates": [
                {"mapping_id": "mapping.x.changed", "stale_locators": [
                    {"locator_id": "code.x.changed", "path": "a/Changed.cpp",
                     "change_type": "M", "from_commit": "SHA1"}]},
                {"mapping_id": "mapping.x.both", "stale_locators": [
                    {"locator_id": "code.x.b", "path": "z/B.cpp",
                     "change_type": "D", "from_commit": "SHA2"},
                    {"locator_id": "code.x.a", "path": "a/A.cpp",
                     "change_type": "M", "from_commit": "SHA1"}]},
            ],
            "unmerged_anchors": [
                {"locator_id": "code.x.unmerged", "path": "u/Only.cpp",
                 "from_commit": "WORK", "reason": "not_ancestor",
                 "blocking_affected_mapping_ids": ["mapping.x.unmerged"]},
                {"locator_id": "code.x.c", "path": "c/C.cpp", "from_commit": "SHA3",
                 "reason": "anchor_unverifiable",
                 "blocking_affected_mapping_ids": ["mapping.x.both"]},
                {"locator_id": "code.x.a", "path": "a/A.cpp", "from_commit": "SHA1",
                 "reason": "not_ancestor",
                 "blocking_affected_mapping_ids": ["mapping.x.both"]},
            ],
        }
        stale_set = build_stale_set(report, now="2026-07-23T12:00:00+09:00")
        adv = advisories_by_mapping(stale_set)

        self.assertEqual(
            stale_set["stale_mapping_ids"],
            ["mapping.x.both", "mapping.x.changed"],
        )
        self.assertNotIn("mapping.x.unchanged-merged", adv)
        self.assertEqual(adv["mapping.x.changed"]["code_changed"], True)
        self.assertEqual(adv["mapping.x.changed"]["unmerged_anchor"], False)
        self.assertEqual(adv["mapping.x.unmerged"]["code_changed"], False)
        self.assertEqual(adv["mapping.x.unmerged"]["unmerged_anchor"], True)
        self.assertEqual(adv["mapping.x.both"]["code_changed"], True)
        self.assertEqual(adv["mapping.x.both"]["unmerged_anchor"], True)
        self.assertEqual(adv["mapping.x.both"]["unmerged_reasons"],
                         ["anchor_unverifiable", "not_ancestor"])
        self.assertEqual(
            adv["mapping.x.both"]["locator_ids"],
            ["code.x.a", "code.x.b", "code.x.c"],
        )
        self.assertEqual(adv["mapping.x.both"]["from_commits"], ["SHA1", "SHA2", "SHA3"])
        self.assertEqual(adv["mapping.x.both"]["paths"], ["a/A.cpp", "c/C.cpp", "z/B.cpp"])
        self.assertEqual(adv["mapping.x.both"]["target_head"], "TARGET")
        self.assertEqual(
            adv["mapping.x.both"]["computed_at"],
            "2026-07-23T12:00:00+09:00",
        )

    def test_build_stale_set_keeps_nonblocking_unmerged_mapping_advisory(self):
        from project_brain.stale_check import advisories_by_mapping, build_stale_set
        report = {
            "target_head": "TARGET",
            "candidates": [],
            "unmerged_anchors": [{
                "locator_id": "code.x.candidate", "path": "a/Candidate.cpp",
                "from_commit": "WORK", "reason": "not_ancestor",
                "nonblocking_affected_mapping_ids": ["mapping.x.candidate"],
            }],
        }
        stale_set = build_stale_set(report, now="t")
        self.assertEqual(stale_set["stale_mapping_ids"], [])
        self.assertEqual(advisories_by_mapping(stale_set)["mapping.x.candidate"], {
            "code_changed": False, "unmerged_anchor": True,
            "unmerged_reasons": ["not_ancestor"], "locator_ids": ["code.x.candidate"],
            "from_commits": ["WORK"], "change_types": [], "paths": ["a/Candidate.cpp"],
            "target_head": "TARGET", "computed_at": "t",
        })

    def test_write_then_load_roundtrip(self):
        from project_brain.stale_check import write_stale_set, load_stale_set, stale_set_path
        self.assertIsNone(load_stale_set(self.root))  # 없으면 None
        ss = {"target_head": "T", "computed_at": "t", "stale_mapping_ids": [], "detail": {}}
        path = write_stale_set(self.root, ss)
        self.assertEqual(path, stale_set_path(self.root))
        self.assertEqual(load_stale_set(self.root), ss)

    def test_advisories_by_mapping(self):
        from project_brain.stale_check import advisories_by_mapping
        ss = {"target_head": "T", "computed_at": "t2",
              "stale_mapping_ids": ["mapping.x.a"],
              "detail": {
                  "mapping.x.a": {"change_types": ["M"], "paths": ["a/X.cpp"]}
              }}
        adv = advisories_by_mapping(ss)
        self.assertEqual(adv["mapping.x.a"], {
            "code_changed": True, "unmerged_anchor": False, "unmerged_reasons": [],
            "locator_ids": [], "from_commits": [], "change_types": ["M"],
            "paths": ["a/X.cpp"], "target_head": "T", "computed_at": "t2"})

    def test_advisories_by_mapping_accepts_legacy_cache_without_branch_fields(self):
        from project_brain.stale_check import advisories_by_mapping
        legacy = {
            "target_head": "T", "computed_at": "t2",
            "stale_mapping_ids": ["mapping.x.a"],
            "detail": {
                "mapping.x.a": {"change_types": ["M"], "paths": ["a/X.cpp"]}
            },
        }
        self.assertEqual(advisories_by_mapping(legacy)["mapping.x.a"], {
            "code_changed": True, "unmerged_anchor": False, "unmerged_reasons": [],
            "locator_ids": [], "from_commits": [], "change_types": ["M"],
            "paths": ["a/X.cpp"], "target_head": "T", "computed_at": "t2"})

    def test_advisories_by_mapping_empty_when_no_cache(self):
        from project_brain.stale_check import advisories_by_mapping
        self.assertEqual(advisories_by_mapping(None), {})
        self.assertEqual(advisories_by_mapping({}), {})


class MarkCheckedTest(unittest.TestCase):
    def _repo(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        repo = Path(td.name).resolve()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo,
            check=True,
        )
        source = repo / "Foo.cpp"
        source.write_text("void Foo::bar() {}\n", encoding="utf-8")
        subprocess.run(["git", "add", "Foo.cpp"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "old"], cwd=repo, check=True)
        old = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        source.write_text(
            "void Foo::bar() {}\n// reviewed target\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "Foo.cpp"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-qm", "target"], cwd=repo, check=True)
        checked = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        context = resolve_repo_context(
            repo,
            expected_repo_id="demoapp",
            configured_repo_id="demoapp",
            expected_revision_ref=checked,
        )
        return context, old, checked

    def _shared(self, old):
        locator = code_locator(
            "code.shared",
            path="Foo.cpp",
            commit_sha=old,
            symbol="Foo::bar",
        )
        locator["verified_quote"] = "void Foo::bar() {}"
        return _store(
            locator,
            domain_mapping("m.r1", code_locator_ids=["code.shared"]),
            domain_mapping("m.r2", code_locator_ids=["code.shared"]),
            domain_mapping(
                "m.cand",
                code_locator_ids=["code.shared"],
                status="candidate",
            ),
            domain_mapping(
                "m.sup",
                code_locator_ids=["code.shared"],
                status="superseded",
            ),
        )

    def test_full_closure_reverifies_quote_and_symbol_with_one_event_time(self):
        from project_brain.stale_check import plan_mark_checked

        repo_context, old, checked = self._repo()
        store = self._shared(old)
        plan = plan_mark_checked(
            store,
            mapping_ids=["mapping.x.r1", "mapping.x.r2"],
            checked_head=checked,
            repo_context=repo_context,
            engine_sha=ENGINE_SHA,
        )

        self.assertEqual([loc["id"] for loc in plan.updated], ["code.x.shared"])
        locator = plan.updated[0]
        self.assertEqual(locator["commit_sha"], checked)
        self.assertEqual(locator["verified_at"], locator["updated_at"])
        self.assertNotEqual(
            locator["verified_at"],
            store.get("code.x.shared")["verified_at"],
        )
        self.assertEqual(plan.warnings, ({
            "locator_id": "code.x.shared",
            "candidate_mapping_ids": ["mapping.x.cand"],
        },))
        self.assertIn("code.x.shared", plan.preconditions)
        self.assertEqual(store.get("code.x.shared")["commit_sha"], old)

    def test_quote_missing_refuses_entire_bundle_before_any_plan_is_returned(self):
        from project_brain.stale_check import (
            MarkCheckedError,
            plan_mark_checked,
        )

        repo_context, old, checked = self._repo()
        store = self._shared(old)
        store.get("code.x.shared").pop("verified_quote")

        with self.assertRaises(MarkCheckedError) as raised:
            plan_mark_checked(
                store,
                mapping_ids=["mapping.x.r1", "mapping.x.r2"],
                checked_head=checked,
                repo_context=repo_context,
                engine_sha=ENGINE_SHA,
            )

        self.assertEqual(raised.exception.code, "refused_unverifiable")
        self.assertEqual(
            raised.exception.locator_ids,
            ("code.x.shared",),
        )
        self.assertEqual(store.get("code.x.shared")["commit_sha"], old)

    def test_symbol_mismatch_refuses_entire_bundle(self):
        from project_brain.stale_check import (
            MarkCheckedError,
            plan_mark_checked,
        )

        repo_context, old, checked = self._repo()
        store = self._shared(old)
        store.get("code.x.shared")["symbol"] = "Other::bar"

        with self.assertRaises(MarkCheckedError) as raised:
            plan_mark_checked(
                store,
                mapping_ids=["mapping.x.r1", "mapping.x.r2"],
                checked_head=checked,
                repo_context=repo_context,
                engine_sha=ENGINE_SHA,
            )

        self.assertEqual(raised.exception.code, "symbol_mismatch")
        self.assertEqual(store.get("code.x.shared")["commit_sha"], old)

    def test_partial_closure_is_blocked_without_verification(self):
        from project_brain.stale_check import plan_mark_checked

        repo_context, old, checked = self._repo()
        plan = plan_mark_checked(
            self._shared(old),
            mapping_ids=["mapping.x.r1"],
            checked_head=checked,
            repo_context=repo_context,
            engine_sha=ENGINE_SHA,
        )

        self.assertEqual(plan.updated, ())
        self.assertEqual(plan.blocked, ({
            "locator_id": "code.x.shared",
            "missing_mapping_ids": ["mapping.x.r2"],
        },))

    def test_checked_head_must_equal_resolved_repository_target(self):
        from project_brain.stale_check import (
            MarkCheckedError,
            plan_mark_checked,
        )

        repo_context, old, _checked = self._repo()
        with self.assertRaises(MarkCheckedError) as raised:
            plan_mark_checked(
                self._shared(old),
                mapping_ids=["mapping.x.r1", "mapping.x.r2"],
                checked_head=old,
                repo_context=repo_context,
                engine_sha=ENGINE_SHA,
            )

        self.assertEqual(raised.exception.code, "head_moved")

    def test_same_sha_apply_reverifies_and_stamps_one_new_event_time(self):
        repo_context, _old, checked = self._repo()
        brain_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(brain_tmp.cleanup)
        brain_root = Path(brain_tmp.name).resolve()
        locator = code_locator(
            "code.same-sha",
            path="Foo.cpp",
            commit_sha=checked,
            symbol="Foo::bar",
        )
        locator["verified_quote"] = "void Foo::bar() {}"
        BrainStore.save_object(brain_root, locator)
        store = BrainStore.load(brain_root)
        objects = (dict(locator),)
        request = MutationRequest(
            operation=MutationOperation.MARK_CHECKED,
            brain_root=brain_root,
            repo_context=repo_context,
            engine_sha=ENGINE_SHA,
            objects=objects,
            preconditions={
                locator["id"]: hashlib.sha256(
                    BrainStore.object_bytes(locator)
                ).hexdigest(),
            },
            expected_corpus_fingerprint=corpus_fingerprint(store),
        )

        result = MutationService().apply(objects, request=request)

        self.assertTrue(result.ok)
        persisted = BrainStore.load(brain_root).get(locator["id"])
        self.assertEqual(persisted["commit_sha"], checked)
        self.assertEqual(persisted["title"], locator["title"])
        self.assertEqual(persisted["verified_at"], persisted["updated_at"])
        self.assertNotEqual(
            persisted["verified_at"],
            locator["verified_at"],
        )

    def test_same_sha_symbol_failure_refuses_entire_apply_bundle(self):
        repo_context, _old, checked = self._repo()
        brain_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(brain_tmp.cleanup)
        brain_root = Path(brain_tmp.name).resolve()
        valid = code_locator(
            "code.valid-same",
            path="Foo.cpp",
            commit_sha=checked,
            symbol="Foo::bar",
        )
        valid["verified_quote"] = "void Foo::bar() {}"
        invalid = code_locator(
            "code.invalid-same",
            path="Foo.cpp",
            commit_sha=checked,
            symbol="Other::bar",
        )
        invalid["verified_quote"] = "void Foo::bar() {}"
        for locator in (valid, invalid):
            BrainStore.save_object(brain_root, locator)
        store = BrainStore.load(brain_root)
        objects = (dict(valid), dict(invalid))
        request = MutationRequest(
            operation=MutationOperation.MARK_CHECKED,
            brain_root=brain_root,
            repo_context=repo_context,
            engine_sha=ENGINE_SHA,
            objects=objects,
            preconditions={
                locator["id"]: hashlib.sha256(
                    BrainStore.object_bytes(locator)
                ).hexdigest()
                for locator in (valid, invalid)
            },
            expected_corpus_fingerprint=corpus_fingerprint(store),
        )

        result = MutationService().apply(objects, request=request)

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "symbol_mismatch")
        persisted = BrainStore.load(brain_root)
        self.assertEqual(
            persisted.get(valid["id"])["verified_at"],
            valid["verified_at"],
        )
        self.assertEqual(
            persisted.get(invalid["id"])["verified_at"],
            invalid["verified_at"],
        )


class CliMarkCheckedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        for obj in (
            *lint_support_objects(),
            code_locator("code.shared", path="a/X.cpp", commit_sha="OLD"),
            domain_mapping("m.r1", code_locator_ids=["code.shared"]),
            domain_mapping("m.r2", code_locator_ids=["code.shared"]),
            domain_mapping("m.cand", code_locator_ids=["code.shared"], status="candidate"),
        ):
            BrainStore.save_object(self.root, obj)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, argv, runner):
        checked_head = argv[argv.index("--checked-head") + 1]

        def verify_fixture_locator(
            locator,
            *,
            repo,
            manual_symbol_verification=None,
        ):
            verified_at = "2026-07-29T00:00:00+09:00"
            verified = dict(locator)
            verified["verified_at"] = verified_at
            return VerifiedLocator(
                locator=verified,
                quote_sha256="f" * 64,
                verified_at=verified_at,
                symbol_status="verified",
            )

        out = io.StringIO()
        with mock.patch("project_brain.stale_check.make_git_runner", return_value=runner), \
             mock.patch.object(
                 cli,
                 "_resolve_mutation_context",
                 return_value=RepoContext(
                     repo_root=self.root,
                     expected_repo_id="demoapp",
                     expected_revision_ref="origin/develop",
                     target_revision_sha=checked_head,
                 ),
             ), \
             mock.patch(
                 "project_brain.code_verify.verify_locator_for_write",
                 side_effect=verify_fixture_locator,
             ), \
             mock.patch(
                 "project_brain.mutation.verify_locator_for_write",
                 side_effect=verify_fixture_locator,
             ), \
             mock.patch(
                 "sys.argv",
                 ["cli"] + argv + ["--engine-sha", ENGINE_SHA],
             ), \
             redirect_stdout(out):
            rc = cli.main()
        return rc, json.loads(out.getvalue())

    def test_full_closure_persists_updated_locator(self):
        runner = fake_git_runner("NEW", {})  # 현재 develop = NEW
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "mapping.x.r1", "mapping.x.r2",
             "--checked-head", "NEW", "--no-fetch"],
            runner)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["updated"], ["code.x.shared"])
        # 디스크에 갱신 반영 — commit_sha=NEW.
        loc = BrainStore.load(self.root).get("code.x.shared")
        self.assertEqual(loc["commit_sha"], "NEW")
        self.assertEqual(loc["verified_at"], loc["updated_at"])
        # candidate가 같은 locator를 가리키므로 CLI 출력 warnings에 전달된다.
        self.assertEqual(payload["warnings"],
                         [{"locator_id": "code.x.shared",
                           "candidate_mapping_ids": ["mapping.x.cand"]}])

    def test_partial_closure_blocked_rc0_disk_unchanged(self):
        runner = fake_git_runner("NEW", {})
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "mapping.x.r1", "--checked-head", "NEW", "--no-fetch"],
            runner)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["updated"], [])
        self.assertEqual(payload["blocked"],
                         [{"locator_id": "code.x.shared",
                           "missing_mapping_ids": ["mapping.x.r2"]}])
        # 갱신 안 됐으니 commit_sha 그대로.
        self.assertEqual(
            BrainStore.load(self.root).get("code.x.shared")["commit_sha"],
            "OLD",
        )

    def test_quote_missing_refuses_whole_bundle_without_disk_changes(self):
        missing = dict(BrainStore.load(self.root).get("code.x.shared"))
        missing.pop("verified_quote")
        BrainStore.save_object(self.root, missing)
        for obj in (
            code_locator(
                "code.valid",
                path="a/Valid.cpp",
                commit_sha="OLD",
            ),
            domain_mapping(
                "m.valid",
                code_locator_ids=["code.valid"],
            ),
        ):
            BrainStore.save_object(self.root, obj)

        rc, payload = self._run(
            [
                "mark-checked",
                "--brain-root",
                str(self.root),
                "--mappings",
                "mapping.x.r1",
                "mapping.x.r2",
                "mapping.x.valid",
                "--checked-head",
                "NEW",
                "--no-fetch",
            ],
            fake_git_runner("NEW", {}),
        )

        self.assertEqual(rc, 1)
        self.assertEqual(payload["error_code"], "refused_unverifiable")
        loaded = BrainStore.load(self.root)
        self.assertEqual(loaded.get("code.x.shared")["commit_sha"], "OLD")
        self.assertEqual(loaded.get("code.x.valid")["commit_sha"], "OLD")

    def test_head_moved_returns_rc1_disk_unchanged(self):
        runner = fake_git_runner("NEW", {})  # 현재 develop은 NEW인데
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "mapping.x.r1", "mapping.x.r2",
             "--checked-head", "STALE", "--no-fetch"],
            runner)
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertIn("head moved", payload["error"])
        self.assertEqual(
            BrainStore.load(self.root).get("code.x.shared")["commit_sha"],
            "OLD",
        )

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
             "--mappings", "mapping.x.x1", "mapping.x.x2", "mapping.x.y1",
             "--checked-head", "NEW", "--no-fetch"],
            runner)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["updated"], ["code.x.x"])
        self.assertEqual(payload["blocked"],
                         [{"locator_id": "code.x.y",
                           "missing_mapping_ids": ["mapping.x.y2"]}])
        loaded = BrainStore.load(self.root)
        self.assertEqual(loaded.get("code.x.x")["commit_sha"], "NEW")  # 완전 → 갱신
        self.assertEqual(loaded.get("code.x.y")["commit_sha"], "OLD")  # blocked → 불변

    def test_candidate_input_rejected_rc1_disk_unchanged(self):
        # candidate 매핑을 --mappings로 주면 입력 검증에서 거부(rc=1), locator 불변(blocker 방지).
        runner = fake_git_runner("NEW", {})
        rc, payload = self._run(
            ["mark-checked", "--brain-root", str(self.root),
             "--mappings", "mapping.x.cand", "--checked-head", "NEW", "--no-fetch"],
            runner)
        self.assertEqual(rc, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["invalid_inputs"][0]["reason"], "status_candidate")
        self.assertEqual(
            BrainStore.load(self.root).get("code.x.shared")["commit_sha"],
            "OLD",
        )
