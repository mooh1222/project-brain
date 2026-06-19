"""session 모듈 테스트 — jsonl 스캔(payload cwd 정본·메타 라인 처리)과 처리 마킹.

스펙 §7: 세션 파일 선두는 mode/queue-operation/file-history-snapshot 같은
cwd 없는 메타 라인인 경우가 보통(실측). cwd는 "cwd 키가 있는 첫 라인"에서,
시작시각·메시지 수는 type ∈ {user, assistant} 라인 기준으로 산출한다.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_brain.session import is_processed, mark_processed, scan_sessions


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n",
        encoding="utf-8",
    )


# 실측 구조 재현: 선두 2줄은 cwd 없는 메타 라인, cwd는 3번째 줄(attachment),
# user/assistant가 그 뒤. timestamp는 모든 라인에 있다.
SESSION_LINES = [
    {"type": "mode", "mode": "default", "timestamp": "2026-06-11T01:00:00.000Z"},
    {"type": "file-history-snapshot", "snapshot": {}, "timestamp": "2026-06-11T01:00:01.000Z"},
    {"type": "attachment", "cwd": "/Users/x/Desktop/demoapp",
     "timestamp": "2026-06-11T01:00:02.000Z"},
    {"type": "user", "cwd": "/Users/x/Desktop/demoapp",
     "message": {"role": "user", "content": "질문"},
     "timestamp": "2026-06-11T01:00:03.000Z"},
    {"type": "assistant", "cwd": "/Users/x/Desktop/demoapp",
     "message": {"role": "assistant", "content": []},
     "timestamp": "2026-06-11T01:00:04.000Z"},
    {"type": "user", "cwd": "/Users/x/Desktop/demoapp",
     "message": {"role": "user", "content": "후속"},
     "timestamp": "2026-06-11T01:00:05.000Z"},
]


class ScanSessionsTest(unittest.TestCase):
    def test_scan_reads_cwd_from_first_line_having_cwd_not_first_line(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            proj = root / "-Users-x-Desktop-demoapp"
            proj.mkdir()
            _write_jsonl(proj / "abc-123.jsonl", SESSION_LINES)

            sessions = scan_sessions(transcript_root=root)

            self.assertEqual(len(sessions), 1)
            s = sessions[0]
            self.assertEqual(s["uuid"], "abc-123")
            # 첫 줄(mode)이 아니라 cwd 키가 처음 등장한 라인의 cwd
            self.assertEqual(s["cwd"], "/Users/x/Desktop/demoapp")

    def test_scan_counts_only_user_assistant_messages(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            proj = root / "p"
            proj.mkdir()
            _write_jsonl(proj / "abc-123.jsonl", SESSION_LINES)

            s = scan_sessions(transcript_root=root)[0]
            # 메타 라인 3개 제외 — user 2 + assistant 1
            self.assertEqual(s["message_count"], 3)
            # 시작시각도 메시지 라인 기준(메타 라인 시각 아님)
            self.assertEqual(s["started_at"], "2026-06-11T01:00:03.000Z")

    def test_scan_skips_malformed_lines_and_empty_files(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            proj = root / "p"
            proj.mkdir()
            (proj / "empty.jsonl").write_text("", encoding="utf-8")
            broken = proj / "broken.jsonl"
            broken.write_text('{"type": "user", "cwd": "/x", "timestamp": "t"}\nnot-json\n',
                              encoding="utf-8")

            sessions = scan_sessions(transcript_root=root)
            # 빈 파일은 메시지 0건이라도 항목으로 나오되 cwd=None, 깨진 라인은 건너뜀
            by_uuid = {s["uuid"]: s for s in sessions}
            self.assertIn("empty", by_uuid)
            self.assertIsNone(by_uuid["empty"]["cwd"])
            self.assertEqual(by_uuid["broken"]["message_count"], 1)

    def test_scan_filters_by_cwd_substring(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            proj = root / "p"
            proj.mkdir()
            _write_jsonl(proj / "a.jsonl", SESSION_LINES)
            other = [dict(l, cwd="/Users/x/other") if "cwd" in l else l
                     for l in SESSION_LINES]
            _write_jsonl(proj / "b.jsonl", other)

            hits = scan_sessions(transcript_root=root, project_filter="demoapp")
            self.assertEqual([s["uuid"] for s in hits], ["a"])


class MarkProcessedTest(unittest.TestCase):
    def test_mark_then_is_processed_roundtrip(self):
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            self.assertFalse(is_processed("abc-123", brain_root=brain_root))

            record = mark_processed("abc-123", brain_root=brain_root, note="미합의 2건")

            self.assertTrue(is_processed("abc-123", brain_root=brain_root))
            on_disk = json.loads(
                (brain_root / ".brain-local" / "sessions" / "abc-123.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(on_disk["uuid"], "abc-123")
            self.assertEqual(on_disk["note"], "미합의 2건")
            self.assertIn("processed_at", on_disk)
            self.assertEqual(record["uuid"], "abc-123")

    def test_mark_is_idempotent_overwrite(self):
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            mark_processed("abc-123", brain_root=brain_root)
            mark_processed("abc-123", brain_root=brain_root, note="재실행")
            on_disk = json.loads(
                (brain_root / ".brain-local" / "sessions" / "abc-123.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(on_disk["note"], "재실행")

    def test_scan_annotates_processed_flag(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "transcripts"
            proj = root / "p"
            proj.mkdir(parents=True)
            _write_jsonl(proj / "abc-123.jsonl", SESSION_LINES)
            brain_root = Path(td) / "brain"
            mark_processed("abc-123", brain_root=brain_root)

            s = scan_sessions(transcript_root=root, brain_root=brain_root)[0]
            self.assertTrue(s["processed"])


if __name__ == "__main__":
    unittest.main()
