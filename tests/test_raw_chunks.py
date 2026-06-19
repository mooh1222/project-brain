"""raw 원문 청커 (스펙 §2.2, P4 raw 본문 색인 — 2026-06-11).

hwi_PKM chunker 채택(task 참조 지도): 헤더 기준 1차 섹션화 → 토큰 초과 섹션만
문장 경계 2차 분할 + 15% 겹침. 토큰은 근사(영문 단어수 + 한글 글자수/2).
난수·시각 없이 완전 결정론 — 같은 입력이면 항상 같은 청크.
"""

import tempfile
import unittest
from pathlib import Path

from project_brain.raw_chunks import (
    CHUNK_TARGET_TOKENS,
    approx_tokens,
    iter_raw_sources,
    split_markdown,
)


class ApproxTokensTest(unittest.TestCase):
    def test_ascii_words_counted(self):
        self.assertEqual(approx_tokens("hello world foo"), 3)

    def test_hangul_chars_halved(self):
        # 한글 4글자 → 2토큰 근사(hwi_PKM 동일 근사).
        self.assertEqual(approx_tokens("가나다라"), 2)

    def test_mixed(self):
        self.assertEqual(approx_tokens("hello 가나다라"), 3)


class SplitMarkdownTest(unittest.TestCase):
    def test_header_sections_become_chunks(self):
        text = "# 제목 하나\n본문 첫째 줄\n\n## 제목 둘\n본문 둘째 줄\n"
        chunks = split_markdown(text)
        self.assertEqual(len(chunks), 2)
        self.assertIn("제목 하나", chunks[0])
        self.assertIn("본문 첫째 줄", chunks[0])
        self.assertIn("제목 둘", chunks[1])

    def test_preamble_before_first_header_kept(self):
        text = "헤더 전 서문 줄\n\n# 제목\n본문\n"
        chunks = split_markdown(text)
        self.assertEqual(len(chunks), 2)
        self.assertIn("서문", chunks[0])

    def test_consecutive_headers_group_until_body(self):
        # 제목만 있는 거의 빈 청크를 만들지 않는다 — 본문 없는 헤더는 다음 섹션에 붙는다.
        text = "# 큰 제목\n## 작은 제목\n본문\n"
        chunks = split_markdown(text)
        self.assertEqual(len(chunks), 1)
        self.assertIn("큰 제목", chunks[0])
        self.assertIn("본문", chunks[0])

    def test_oversized_section_splits_with_overlap(self):
        # 한 섹션이 목표 토큰을 한참 넘으면 문장 경계로 나뉘고 15% 겹침이 있다.
        sentence = "스테이지 클리어 토큰은 즉시 클리어에 쓰이는 재화이다."
        body = " ".join(f"{i}번째 문장. {sentence}" for i in range(200))
        text = f"# 큰 섹션\n{body}\n"
        chunks = split_markdown(text)
        self.assertGreater(len(chunks), 1)
        # 각 청크는 목표 토큰의 1.5배를 넘지 않는다(문장 하나가 통째로 들어가는 여유 허용).
        for c in chunks:
            self.assertLessEqual(approx_tokens(c), int(CHUNK_TARGET_TOKENS * 1.5))
        # 겹침: 앞 청크의 마지막 문장 조각이 다음 청크에도 나타난다.
        tail = chunks[0].splitlines()[-1]
        self.assertIn(tail, chunks[1])

    def test_deterministic(self):
        text = "# 제목\n" + " ".join(f"{i}번 문장." for i in range(300))
        self.assertEqual(split_markdown(text), split_markdown(text))

    def test_blank_only_input_returns_empty(self):
        self.assertEqual(split_markdown("\n  \n"), [])


class IterRawSourcesTest(unittest.TestCase):
    def test_discovers_md_and_builds_ids(self):
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td)
            src = brain / "raw" / "sources" / "foo-ctx"
            src.mkdir(parents=True)
            (src / "spec-v1.md").write_text("# 제목\n본문 내용\n", encoding="utf-8")
            chunks = iter_raw_sources(brain)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["chunk_id"], "raw.foo-ctx.spec-v1#000")
        self.assertEqual(chunks[0]["context_id"], "context.foo-ctx")
        self.assertIn("본문 내용", chunks[0]["text"])

    def test_missing_raw_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(iter_raw_sources(Path(td)), [])

    def test_sorted_traversal_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td)
            for ctx in ("b-ctx", "a-ctx"):
                d = brain / "raw" / "sources" / ctx
                d.mkdir(parents=True)
                (d / "z.md").write_text("# 제목\nz 본문\n", encoding="utf-8")
                (d / "a.md").write_text("# 제목\na 본문\n", encoding="utf-8")
            ids = [c["chunk_id"] for c in iter_raw_sources(brain)]
        self.assertEqual(ids, [
            "raw.a-ctx.a#000", "raw.a-ctx.z#000",
            "raw.b-ctx.a#000", "raw.b-ctx.z#000",
        ])

    def test_non_md_files_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            brain = Path(td)
            src = brain / "raw" / "sources" / "foo-ctx"
            src.mkdir(parents=True)
            (src / "image.png").write_bytes(b"\x89PNG")
            (src / "spec.md").write_text("# 제목\n본문\n", encoding="utf-8")
            chunks = iter_raw_sources(brain)
        self.assertEqual([c["chunk_id"] for c in chunks], ["raw.foo-ctx.spec#000"])


if __name__ == "__main__":
    unittest.main()
