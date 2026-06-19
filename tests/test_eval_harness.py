"""검색층 평가 하네스 테스트 (스펙 §8, 구현 슬라이스 1).

하네스 자체의 판정 로직(top-5 적중·그래프 동반·반환 상한·게이트)을 가짜 recall
응답으로 결정론 검증한다. 골든셋 파일(eval_scenarios.json) 자체의 무결성·기대
object_id 실존 가드는 데이터 레포 쪽 CLI 가드(`eval --check-ids`)로 옮겨졌다.

실 모델 측정(슬라이스 3.5/6)은 cli eval이 담당 — 여기는 하네스 역학만."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from project_brain import cli
from project_brain.eval_harness import (
    ASSERTION_KEYS,
    ScenarioError,
    empty_recall,
    evaluate,
    expected_object_ids,
    load_recall_fn,
    load_scenarios,
)
from project_brain.store import BrainStore


def hit(object_id, *, status="reviewed", linked=None):
    """§3 결과 계약 형태의 최소 hit. 하네스는 object_id와 linked만 본다."""
    return {
        "object_id": object_id,
        "kind": "DomainMapping",
        "status": status,
        "score": 0.03,
        "matched_via": "both",
        "surface": object_id,
        "linked": linked or {},
    }


def recall_of(results=None, candidates=None, needs_clarification=False):
    response = {
        "results": results or [],
        "candidates": candidates or [],
        "needs_clarification": needs_clarification,
    }
    return lambda query: response


def scenario(sid, expect, query="질의"):
    return {"id": sid, "query": query, "expect": expect}


class TestExpectedObjectIds(unittest.TestCase):
    def test_raw_prefixes_excluded(self):
        # raw_top5_prefix_any의 프리픽스는 객체 id가 아니다 — 코퍼스 실존 가드
        # (`eval --check-ids`)에 새어 들어가면 거짓 실패한다.
        scenarios = [
            scenario("a", {"top5_any": ["m.x"]}),
            scenario("b", {"raw_top5_prefix_any": ["raw.spec-v1"]}),
        ]
        ids = expected_object_ids(scenarios)
        self.assertIn("m.x", ids)
        self.assertFalse(any(oid.startswith("raw.") for oid in ids))


class TestLoadScenarios(unittest.TestCase):
    def _write(self, payload):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        self.addCleanup(Path(tmp.name).unlink)
        json.dump(payload, tmp, ensure_ascii=False)
        tmp.close()
        return tmp.name

    def test_rejects_duplicate_ids(self):
        path = self._write(
            {"scenarios": [scenario("a", {"no_answer": True}), scenario("a", {"no_answer": True})]}
        )
        with self.assertRaises(ScenarioError):
            load_scenarios(path)

    def test_rejects_unknown_assertion_key(self):
        # 시나리오 파일은 데이터라 오타가 조용히 통과하면 측정이 빈다 — 미지 키는 거부.
        path = self._write({"scenarios": [scenario("a", {"top5_alllll": ["x"]})]})
        with self.assertRaises(ScenarioError):
            load_scenarios(path)

    def test_rejects_empty_expect(self):
        path = self._write({"scenarios": [scenario("a", {})]})
        with self.assertRaises(ScenarioError):
            load_scenarios(path)


class TestEvaluate(unittest.TestCase):
    def test_top5_any_pass(self):
        scenarios = [scenario("s", {"top5_any": ["m.target"]})]
        report = evaluate(recall_of(results=[hit("m.other"), hit("m.target")]), scenarios)
        self.assertTrue(report["ok"])
        self.assertTrue(report["scenarios"][0]["checks"]["top5_any"]["passed"])

    def test_top5_any_fails_when_hit_is_rank_6(self):
        results = [hit(f"m.{i}") for i in range(5)] + [hit("m.target")]
        report = evaluate(recall_of(results=results), scenarios=[
            scenario("s", {"top5_any": ["m.target"]})
        ])
        self.assertFalse(report["ok"])

    def test_linked_any_groups_requires_every_group(self):
        # 그룹별 ≥1 매칭 (시나리오 1: 용어 그룹 + CodeLocator 그룹이 둘 다 따라와야 함)
        linked = {"code_locators": ["code.a"], "related_object_ids": [{"object_id": "g.term"}]}
        scenarios = [scenario("s", {
            "top5_any": ["m.target"],
            "linked_any_groups": [["g.term"], ["code.a", "code.b"]],
        })]
        report = evaluate(recall_of(results=[hit("m.target", linked=linked)]), scenarios)
        self.assertTrue(report["ok"])
        # 한 그룹이 비면 실패
        scenarios_fail = [scenario("s", {
            "top5_any": ["m.target"],
            "linked_any_groups": [["g.term"], ["code.missing"]],
        })]
        report = evaluate(recall_of(results=[hit("m.target", linked=linked)]), scenarios_fail)
        self.assertFalse(report["ok"])

    def test_any_channel_top5_accepts_candidate_channel(self):
        # 시나리오 3: candidate 채널 노출이 통과 (§7 채널 분리)
        scenarios = [scenario("s", {"any_channel_top5_any": ["g.cand"]})]
        report = evaluate(
            recall_of(candidates=[hit("g.cand", status="candidate")]), scenarios
        )
        self.assertTrue(report["ok"])

    def test_max_results_cap(self):
        # 무더기 반환 가드 (06-05 실측 110개 무더기의 재발 방지 측정)
        scenarios = [scenario("s", {"top5_any": ["m.t"], "max_results": 5})]
        report = evaluate(recall_of(results=[hit("m.t")] + [hit(f"m.{i}") for i in range(9)]), scenarios)
        self.assertFalse(report["ok"])
        self.assertFalse(report["scenarios"][0]["checks"]["max_results"]["passed"])

    def test_no_answer_passes_only_when_gated_empty(self):
        scenarios = [scenario("s", {"no_answer": True})]
        self.assertTrue(evaluate(recall_of(needs_clarification=True), scenarios)["ok"])
        # 결과가 실려 있으면 "없다" 보장이 깨진 것
        self.assertFalse(
            evaluate(recall_of(results=[hit("m.x")], needs_clarification=True), scenarios)["ok"]
        )
        self.assertFalse(evaluate(recall_of(needs_clarification=False), scenarios)["ok"])

    def test_raw_top5_prefix_any(self):
        # raw 채널 판정(§2.2): raw_excerpts top-5에 프리픽스 일치 id가 ≥1이면 통과.
        def fn(query):
            return {"results": [], "candidates": [],
                    "raw_excerpts": [hit("raw.foo-ctx.spec#003", status="raw")],
                    "needs_clarification": True}
        ok = evaluate(fn, [scenario("s", {"raw_top5_prefix_any": ["raw.foo-ctx."]})])
        self.assertTrue(ok["scenarios"][0]["passed"])
        miss = evaluate(fn, [scenario("s", {"raw_top5_prefix_any": ["raw.other."]})])
        self.assertFalse(miss["scenarios"][0]["passed"])

    def test_recall_error_marks_scenario_failed(self):
        def boom(query):
            raise RuntimeError("모델 로드 실패")

        report = evaluate(boom, [scenario("s", {"no_answer": True})])
        self.assertFalse(report["ok"])
        self.assertIn("모델 로드 실패", report["scenarios"][0]["error"])

    def test_summary_counts_and_latency(self):
        scenarios = [
            scenario("pass", {"no_answer": True}),
            scenario("fail", {"top5_any": ["m.absent"]}),
        ]
        report = evaluate(recall_of(needs_clarification=True), scenarios)
        self.assertEqual(report["summary"], {"passed": 1, "failed": 1, "total": 2})
        for sc in report["scenarios"]:
            self.assertGreaterEqual(sc["latency_ms"], 0)


class TestCliEval(unittest.TestCase):
    def test_search_layer_now_implemented(self):
        # 슬라이스 3에서 project_brain.search.eval_recall이 생겼으므로 베이스라인이
        # "미구현"→"구현됨"으로 전이한다(과업 요구사항 2). load_recall_fn이 더는
        # empty_recall을 돌려주지 않는다.
        from project_brain.search import eval_recall
        recall_fn, implemented = load_recall_fn()
        self.assertTrue(implemented)
        self.assertIs(recall_fn, eval_recall)
        self.assertIsNot(recall_fn, empty_recall)

    def _write_scenarios(self, scenarios):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        self.addCleanup(Path(tmp.name).unlink)
        json.dump({"scenarios": scenarios}, tmp, ensure_ascii=False)
        tmp.close()
        return tmp.name

    def test_cli_eval_runs_with_injected_recall(self):
        # cli eval 실행 단언은 색인 DB 존재·실모델·실코퍼스 골든셋에 의존하면 안 된다.
        # load_recall_fn을 stub recall로 주입하고 합성 시나리오를 --scenarios로 줘
        # 결정론으로 rc·리포트 형태를 검증한다. 빈 응답 stub이면 게이트(no_answer)
        # 시나리오만 통과 → rc=1(부분 통과 측정).
        def stub_recall(query):
            return {"results": [], "candidates": [], "needs_clarification": True}

        path = self._write_scenarios([
            scenario("hit", {"top5_any": ["m.target"]}),
            scenario("gate", {"no_answer": True}),
        ])
        out = io.StringIO()
        with mock.patch(
            "project_brain.cli.load_recall_fn", return_value=(stub_recall, True)
        ), mock.patch("sys.argv", ["cli", "eval", "--scenarios", path]), \
                redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 1)  # gate만 통과 → 전체 ok=False
        report = json.loads(out.getvalue())
        self.assertTrue(report["implemented"])
        self.assertEqual(report["summary"], {"passed": 1, "failed": 1, "total": 2})
        by_id = {s["id"]: s for s in report["scenarios"]}
        self.assertTrue(by_id["gate"]["passed"])
        self.assertFalse(by_id["hit"]["passed"])

    def test_cli_eval_check_ids_reports_missing(self):
        # --check-ids: 기대 object_id의 코퍼스 실존만 검사(모델·색인 불필요) —
        # 데이터 레포 골든셋 가드가 쓰는 경로. raw 프리픽스는 검사 대상이 아니다.
        from tests.test_ingest import context

        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            BrainStore.save_object(brain, context())
            path = self._write_scenarios([
                scenario("ok", {"top5_any": ["context.neutral"]}),
                scenario("missing", {"top5_any": ["m.absent"]}),
                scenario("raw", {"raw_top5_prefix_any": ["raw.spec"]}),
            ])
            out = io.StringIO()
            argv = ["cli", "eval", "--check-ids", "--scenarios", path,
                    "--brain-root", str(brain)]
            with mock.patch("sys.argv", argv), redirect_stdout(out):
                rc = cli.main()
            report = json.loads(out.getvalue())
            self.assertEqual(rc, 1)
            self.assertFalse(report["ok"])
            self.assertEqual(report["missing"], ["m.absent"])

    def test_cli_eval_check_ids_ok_when_all_exist(self):
        from tests.test_ingest import context

        with tempfile.TemporaryDirectory() as td:
            brain = Path(td) / "brain"
            BrainStore.save_object(brain, context())
            path = self._write_scenarios(
                [scenario("ok", {"top5_any": ["context.neutral"]})]
            )
            out = io.StringIO()
            argv = ["cli", "eval", "--check-ids", "--scenarios", path,
                    "--brain-root", str(brain)]
            with mock.patch("sys.argv", argv), redirect_stdout(out):
                rc = cli.main()
            report = json.loads(out.getvalue())
            self.assertEqual(rc, 0)
            self.assertTrue(report["ok"])
            self.assertEqual(report["missing"], [])


class TestAdvisoriesAssertion(unittest.TestCase):
    """advisories_top5_any 판정 키(spec 2026-06-15) — advisories 채널 top-5에 ≥1 적중."""

    def test_advisories_top5_any_passes(self):
        scenarios = [{"id": "adv", "query": "q",
                      "expect": {"advisories_top5_any": ["insight.gate"]}}]
        def fake_recall(q):
            return {"results": [], "candidates": [], "raw_excerpts": [],
                    "advisories": [{"object_id": "insight.gate"}],
                    "needs_clarification": True}
        report = evaluate(fake_recall, scenarios)
        self.assertTrue(report["ok"])

    def test_advisories_top5_any_fails_when_absent(self):
        scenarios = [{"id": "adv", "query": "q",
                      "expect": {"advisories_top5_any": ["insight.gate"]}}]
        def fake_recall(q):
            return {"results": [], "candidates": [], "raw_excerpts": [],
                    "advisories": [], "needs_clarification": True}
        report = evaluate(fake_recall, scenarios)
        self.assertFalse(report["ok"])

    def test_advisories_key_is_known_assertion(self):
        # load_scenarios가 미지 키로 거부하지 않는다(ASSERTION_KEYS 등록 확인).
        self.assertIn("advisories_top5_any", ASSERTION_KEYS)


if __name__ == "__main__":
    unittest.main()
