"""graph.find_isolated 단위 테스트 (C1) — 인바운드 0(아무도 안 가리킴) 잎 탐지.

핵심 두 축(plan Step 1):
① 매핑 없는 CodeLocator는 고립으로 잡히고, evidence_refs/단수 brain-참조 _id로만
   가리켜진 잎은 안 잡힌다(인바운드 필드 집합 정확성).
② 구조적 인바운드0 kind(CurrentView·Insight 등)는 잎이 아니라 안 잡힌다 — 이 폭주
   방지 가드가 없으면 CodeLocator만 보고 거짓 통과한다(plan이 명시한 핵심).
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from project_brain import cli
from project_brain.graph import edges, find_isolated, referenced_ids
from project_brain.store import BrainStore


def _store(*objs):
    return BrainStore({o["id"]: o for o in objs})


def _obj(oid, kind, **fields):
    return {"id": oid, "kind": kind, **fields}


class TestFindIsolated(unittest.TestCase):
    def test_unreferenced_code_locator_is_isolated(self):
        # 아무것도 안 가리키는 CodeLocator → 고립으로 잡힘(도구 주목적).
        store = _store(_obj("code.lonely", "CodeLocator"))
        self.assertEqual(find_isolated(store), ["code.lonely"])

    def test_code_locator_referenced_by_mapping_not_isolated(self):
        # DomainMapping.code_locator_ids가 가리키면 고립 아님.
        store = _store(
            _obj("code.linked", "CodeLocator"),
            _obj("m.x", "DomainMapping", code_locator_ids=["code.linked"]),
        )
        self.assertEqual(find_isolated(store), [])

    def test_evidence_ref_pointed_only_by_evidence_refs_not_isolated(self):
        # EvidenceRef는 evidence_refs로만 가리켜진다 — 인바운드 집합에서 빼면 전부 거짓 고립.
        store = _store(
            _obj("evref.a", "EvidenceRef"),
            _obj("g.t", "GlossaryTerm", evidence_refs=["evref.a"]),
        )
        self.assertNotIn("evref.a", find_isolated(store, kinds=["EvidenceRef"]))

    def test_glossary_term_pointed_only_by_singular_id_not_isolated(self):
        # 단수 brain-참조 _id(ReviewRecord.target_object_id)로만 가리켜져도 고립 아님.
        store = _store(
            _obj("g.reviewed", "GlossaryTerm"),
            _obj("review.1", "ReviewRecord", target_object_id="g.reviewed"),
        )
        self.assertNotIn("g.reviewed", find_isolated(store, kinds=["GlossaryTerm"]))

    def test_structural_inbound_zero_kinds_not_flagged(self):
        # CurrentView·Insight는 구조적으로 인바운드 0이 정상 — 잎 kind가 아니라 안 잡힌다.
        # (이 가드 없으면 점검 대상을 잘못 잡아 코퍼스가 고립으로 폭주한다.)
        store = _store(
            _obj("view.now", "CurrentView"),
            _obj("insight.x", "Insight"),
            _obj("code.lonely", "CodeLocator"),
        )
        self.assertEqual(find_isolated(store), ["code.lonely"])

    def test_external_keys_not_counted_as_inbound(self):
        # channel_id·project_id는 외부 키라 인바운드로 안 센다 — 우연히 같은 문자열을 가져도
        # 거짓으로 '가리켜짐' 처리되면 고립을 놓친다.
        store = _store(
            _obj("slack.t", "SlackThread", channel_id="code.lonely"),
            _obj("code.lonely", "CodeLocator"),
        )
        self.assertIn("code.lonely", find_isolated(store))

    def test_self_reference_does_not_count_as_inbound(self):
        # 자기 자신을 가리키는 self-ref는 인바운드로 치지 않는다(supersedes 체인 등).
        store = _store(_obj("g.self", "GlossaryTerm", glossary_term_ids=["g.self"]))
        self.assertEqual(find_isolated(store, kinds=["GlossaryTerm"]), ["g.self"])

    def test_referenced_ids_collects_singular_and_plural(self):
        # referenced_ids(C8 공유 1차 헬퍼)가 단수·복수 인바운드를 모두 모은다.
        store = _store(
            _obj("a", "DomainMapping", context_id="ctx", code_locator_ids=["c1", "c2"]),
        )
        refs = referenced_ids(store)
        self.assertEqual(refs, {"ctx", "c1", "c2"})


class TestEdges(unittest.TestCase):
    """graph.edges — 정본 INBOUND_REF_FIELDS 기준 from→to 엣지 목록(시각화용).

    referenced_ids와 같은 필드·self-ref 규칙을 공유하되, 양 끝이 store에 존재하는
    엣지만 만든다(끊긴 참조는 그릴 노드가 없다)."""

    def test_edges_from_singular_and_plural_fields(self):
        # 단수(context_id)·복수(code_locator_ids)를 모두 from→to 엣지로 편다. 정렬로 결정론.
        store = _store(
            _obj("m", "DomainMapping", context_id="ctx", code_locator_ids=["c1", "c2"]),
            _obj("ctx", "DomainContext"),
            _obj("c1", "CodeLocator"),
            _obj("c2", "CodeLocator"),
        )
        self.assertEqual(edges(store), [("m", "c1"), ("m", "c2"), ("m", "ctx")])

    def test_edges_exclude_dangling_and_self_ref(self):
        # store에 없는 to(끊긴 참조)·자기 자신 참조는 엣지에서 뺀다.
        store = _store(
            _obj("m", "DomainMapping",
                 code_locator_ids=["c1", "missing"], supersedes_mapping_ids=["m"]),
            _obj("c1", "CodeLocator"),
        )
        self.assertEqual(edges(store), [("m", "c1")])

    def test_edges_external_keys_not_edges(self):
        # channel_id 등 외부 키는 INBOUND_REF_FIELDS 밖이라 엣지가 아니다(거짓 연결 방지).
        store = _store(
            _obj("slack.t", "SlackThread", channel_id="code.x"),
            _obj("code.x", "CodeLocator"),
        )
        self.assertEqual(edges(store), [])

    def test_edges_exclude_none_id_from(self):
        # from 객체에 id가 없으면(None) 그 엣지는 안 만든다 — to 가드와 대칭, '양 끝 존재' 약속.
        store = _store(
            _obj(None, "DomainMapping", code_locator_ids=["c1"]),
            _obj("c1", "CodeLocator"),
        )
        self.assertEqual(edges(store), [])

    def test_edges_dedupe_same_pair(self):
        # 한 객체가 같은 대상을 여러 필드로 가리켜도 엣지는 한 번만.
        store = _store(
            _obj("m", "DomainMapping",
                 target_object_id="g", affected_glossary_term_ids=["g"]),
            _obj("g", "GlossaryTerm"),
        )
        self.assertEqual(edges(store), [("m", "g")])


class TestGraphIsolatedCli(unittest.TestCase):
    """`graph isolated` CLI — 읽기 전용 JSON 리포트(dispatch + 집계 배선 확인)."""

    def test_cli_graph_isolated_reports_isolated_leaves(self):
        from tests.test_search import code_locator, domain_mapping
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            BrainStore.save_object(root, code_locator("code.linked", path="a/A.cpp", symbol="f"))
            BrainStore.save_object(root, code_locator("code.lonely", path="b/B.cpp", symbol="g"))
            BrainStore.save_object(
                root, domain_mapping("m.x", meaning="매핑", code_locator_ids=["code.linked"]))
            out = io.StringIO()
            argv = ["graph", "isolated", "--brain-root", str(root)]
            with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
                rc = cli.main()
            payload = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])
        self.assertIn("code.lonely", payload["isolated"])
        self.assertNotIn("code.linked", payload["isolated"])
        self.assertEqual(payload["by_kind"], {"CodeLocator": 1})

    def test_cli_graph_isolated_kind_filter(self):
        from tests.test_search import code_locator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            BrainStore.save_object(root, code_locator("code.lonely", path="b/B.cpp", symbol="g"))
            out = io.StringIO()
            argv = ["graph", "isolated", "--brain-root", str(root), "--kind", "GlossaryTerm"]
            with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
                rc = cli.main()
            payload = json.loads(out.getvalue())
        self.assertEqual(rc, 0)
        # GlossaryTerm만 점검 → CodeLocator 고립은 안 잡힌다.
        self.assertEqual(payload["isolated"], [])


class TestGraphExportCli(unittest.TestCase):
    """`graph export <out>` CLI — store를 vis-network HTML로 쓰고 요약을 JSON으로 낸다."""

    def test_cli_graph_export_writes_html_and_summary(self):
        from tests.test_search import code_locator, domain_mapping
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            BrainStore.save_object(root, code_locator("code.x", path="a/A.cpp", symbol="f"))
            BrainStore.save_object(
                root, domain_mapping("m.x", meaning="매핑", code_locator_ids=["code.x"]))
            out_path = root / "graph.html"
            out = io.StringIO()
            argv = ["graph", "export", str(out_path), "--brain-root", str(root)]
            with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
                rc = cli.main()
            payload = json.loads(out.getvalue())
            html = out_path.read_text(encoding="utf-8")
        self.assertEqual(rc, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["out"], str(out_path))
        self.assertEqual(payload["nodes"], 2)
        self.assertEqual(payload["edges"], 1)        # m.x → code.x
        self.assertIn("vis-network", html)
        self.assertIn("code.x", html)

    def test_cli_graph_export_creates_missing_parent_dirs(self):
        # 없는 부모 디렉터리로 내보내면 폴더를 만들어 쓴다(흔한 케이스 — 트레이스백 금지).
        from tests.test_search import code_locator
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            BrainStore.save_object(root, code_locator("code.x", path="a/A.cpp", symbol="f"))
            out_path = root / "sub" / "deep" / "graph.html"   # 부모 미존재
            out = io.StringIO()
            argv = ["graph", "export", str(out_path), "--brain-root", str(root)]
            with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
                rc = cli.main()
            existed = out_path.exists()        # tmp 디렉터리 정리 전에 확인
        self.assertEqual(rc, 0)
        self.assertTrue(existed)


if __name__ == "__main__":
    unittest.main()
