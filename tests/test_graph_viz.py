"""graph_viz 단위 테스트 — 객체 그래프 → vis-network 단일 HTML.

payload 빌더(파이썬)만 검증한다. HTML 안 JS는 단위 테스트 대상이 아니라 렌더
스모크(치환·필수 스크립트 포함)로만 본다. 핵심: 엣지를 정본 graph.edges로 그려
graph isolated와 같은 그래프를 보여준다(외부 키는 엣지가 아니다)."""

import json
import unittest

from project_brain.graph_viz import build_payload, render_html
from tests.test_graph import _obj, _store


class TestBuildPayload(unittest.TestCase):
    def test_uses_canonical_edges_excluding_external_keys(self):
        # channel_id 등 외부 키는 graph.edges가 안 그린다 → payload edges도 비어야 한다.
        store = _store(
            _obj("slack.t", "SlackThread", channel_id="code.x", title="T"),
            _obj("code.x", "CodeLocator", path="a/A.cpp"),
        )
        payload = build_payload(store)
        self.assertEqual(payload["edges"], [])
        self.assertEqual({n["id"] for n in payload["nodes"]}, {"slack.t", "code.x"})

    def test_edges_kinds_and_details(self):
        store = _store(
            _obj("m", "DomainMapping", title="매핑", code_locator_ids=["c1"]),
            _obj("c1", "CodeLocator", path="a/A.cpp"),
        )
        payload = build_payload(store)
        self.assertIn({"from": "m", "to": "c1"}, payload["edges"])
        self.assertEqual(payload["kinds"], {"DomainMapping": 1, "CodeLocator": 1})
        self.assertEqual(payload["details"]["m"]["title"], "매핑")
        self.assertTrue(payload["details"]["m"]["display_only"])
        self.assertTrue(next(n for n in payload["nodes"] if n["id"] == "m")["display_only"])


class TestNodeLabel(unittest.TestCase):
    """노드 라벨 휴리스틱(graph_viz) — 30자 절단·LABEL_FIELDS 폴백 고정."""

    def test_long_label_truncated_to_30_with_ellipsis(self):
        # 30자 초과 라벨은 29자 + … = 길이 30으로 자른다(off-by-one 슬라이스 고정).
        store = _store(_obj("m", "DomainMapping", title="가" * 40))
        node = build_payload(store)["nodes"][0]
        self.assertEqual(len(node["label"]), 30)
        self.assertTrue(node["label"].endswith("…"))

    def test_label_falls_back_to_id_tail_when_label_fields_empty(self):
        # LABEL_FIELDS(title/term/mapping_key/symbol/path)가 전부 없으면 id 꼬리로 폴백.
        store = _store(_obj("ns.sub.tail", "EvidenceManifest"))
        node = build_payload(store)["nodes"][0]
        self.assertEqual(node["label"], "tail")

    def test_code_locator_labels_stay_unique_after_thirty_character_limit(self):
        # 긴 공통 anchor_key와 같은 symbol도 graph에서 서로 구분돼야 한다.
        store = _store(
            _obj(
                "code.demo.shared-prefix-that-is-very-very-long-a",
                "CodeLocator",
                path="src/first.cpp",
                symbol="Ns::Widget::run",
            ),
            _obj(
                "code.demo.shared-prefix-that-is-very-very-long-b",
                "CodeLocator",
                path="src/second.cpp",
                symbol="Ns::Widget::run",
            ),
        )
        labels = [
            node["label"]
            for node in build_payload(store)["nodes"]
            if node["group"] == "CodeLocator"
        ]
        self.assertEqual(len(labels), len(set(labels)))
        self.assertTrue(all(len(label) <= 30 for label in labels))
        self.assertTrue(labels[0].endswith("·1"))
        self.assertTrue(labels[1].endswith("·2"))

    def test_code_locator_suffixes_do_not_collide_with_singleton_candidates(self):
        common_symbol_prefix = "x" * 20
        objects = (
            _obj(
                "code.first.shared",
                "CodeLocator",
                path="src/first.cpp",
                symbol=f"{common_symbol_prefix}aa",
            ),
            _obj(
                "code.second.shared",
                "CodeLocator",
                path="src/second.cpp",
                symbol=f"{common_symbol_prefix}bb",
            ),
            _obj(
                "code.singleton.shared",
                "CodeLocator",
                path="src/singleton.cpp",
                symbol=f"{'x' * 19}·1",
            ),
        )

        def labels_for(items):
            return {
                node["id"]: node["label"]
                for node in build_payload(_store(*items))["nodes"]
                if node["group"] == "CodeLocator"
            }

        labels = labels_for(objects)
        expected_reviewer_collision = f"shared · {'x' * 19}·1"
        self.assertEqual(labels["code.singleton.shared"], expected_reviewer_collision)
        self.assertEqual(len(labels.values()), len(set(labels.values())))
        self.assertTrue(all(len(label) <= 30 for label in labels.values()))
        self.assertEqual(labels_for(tuple(reversed(objects))), labels)

    def test_code_locator_tooltip_contains_full_symbol_and_path(self):
        store = _store(
            _obj(
                "code.demo.widget-run",
                "CodeLocator",
                path="src/widget.cpp",
                symbol="Ns::Widget::run",
            )
        )
        node = build_payload(store)["nodes"][0]
        self.assertIn("Ns::Widget::run", node["title"])
        self.assertIn("src/widget.cpp", node["title"])

    def test_code_locator_without_symbol_uses_path_and_anchor_key(self):
        store = _store(
            _obj(
                "code.demo.widget-anchor",
                "CodeLocator",
                path="src/widget.cpp",
            )
        )
        node = build_payload(store)["nodes"][0]
        self.assertEqual(node["label"], "widget.cpp:widget-anchor")


class TestRenderHtml(unittest.TestCase):
    def test_injects_payload_and_no_placeholder_left(self):
        store = _store(_obj("c1", "CodeLocator", path="a/A.cpp"))
        html = render_html(store)
        self.assertNotIn("__DATA__", html)       # 치환 완료
        self.assertIn("vis-network", html)        # CDN 스크립트 포함
        self.assertIn("c1", html)                 # 노드 데이터 주입됨

    def test_payload_is_valid_json_in_html(self):
        # 한글 등 비ASCII가 깨지지 않고, 주입된 DATA가 파싱 가능한 JSON이어야 한다.
        store = _store(_obj("g.한글", "GlossaryTerm", term="용어"))
        html = render_html(store)
        marker = "const DATA = "
        start = html.index(marker) + len(marker)
        end = html.index(";\n", start)
        data = json.loads(html[start:end])
        self.assertEqual(data["kinds"], {"GlossaryTerm": 1})


if __name__ == "__main__":
    unittest.main()
