"""session 모듈 테스트 — jsonl 스캔(payload cwd 정본·메타 라인 처리)과 처리 마킹.

스펙 §7: 세션 파일 선두는 mode/queue-operation/file-history-snapshot 같은
cwd 없는 메타 라인인 경우가 보통(실측). cwd는 "cwd 키가 있는 첫 라인"에서,
시작시각·메시지 수는 type ∈ {user, assistant} 라인 기준으로 산출한다.
"""
import json
import hashlib
import threading
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from project_brain.corpus_io import (
    record_no_change_receipt,
    recover_committed_receipt,
)
from project_brain.coverage import normalize_coverage
from project_brain import session as session_module
from project_brain.mutation import (
    MutationOperation,
    MutationRequest,
    MutationService,
)
from project_brain.objbase import base
from project_brain.session import (
    SessionCompletionError,
    complete_session,
    is_processed,
    mark_processed,
    scan_sessions,
)
from project_brain.store import BrainStore
from project_brain.transaction_receipt import (
    BatchBinding,
    normalize_mutation_receipt,
)
from tests.coverage_helpers import direct_coverage


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(l, ensure_ascii=False) for l in lines) + "\n",
        encoding="utf-8",
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _no_change_receipt(coverage_sha256: str) -> dict:
    receipt = {
        "version": 1,
        "receipt_id": "0" * 64,
        "ok": True,
        "outcome": "no_changes",
        "operation": "ingest",
        "committed": False,
        "transaction_id": None,
        "manifest_sha256": "d" * 64,
        "coverage_sha256": coverage_sha256,
        "expected_objects": [],
        "verified_objects": [],
        "changed_objects": [],
        "before_fingerprint": "e" * 64,
        "after_fingerprint": "e" * 64,
    }
    receipt["receipt_id"] = _sha256(json.dumps(
        {key: value for key, value in receipt.items() if key != "receipt_id"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8"))
    return receipt


def _domain_context(object_id: str) -> dict:
    context_key = object_id.removeprefix("context.")
    return base(
        {
            "id": object_id,
            "kind": "DomainContext",
            "status": "reviewed",
            "truth_role": "domain",
            "title": context_key,
            "context_key": context_key,
            "project_id": "fixture",
            "display_name": context_key,
            "boundary_summary": context_key,
            "in_scope": ["fixture"],
            "out_of_scope": ["other"],
            "injection_profile": {"default_audience": "coding-agent"},
            "glossary_term_ids": [],
        },
        tags=["fixture"],
        created_at="2026-08-26T00:00:00+09:00",
        updated_at="2026-08-26T00:00:00+09:00",
    )


def _completion_artifacts(
    root: Path,
    *,
    uuid: str = "abc",
    finalized: bool = True,
    committed: bool = False,
) -> dict[str, Path]:
    brain_root = root / "brain"
    brain_root.mkdir(parents=True)
    transcript = root / f"{uuid}.jsonl"
    _write_jsonl(transcript, SESSION_LINES)
    manifest = root / "ingest-batch-manifest.json"
    manifest.write_bytes(b'{"fixture":"generic-batch"}\n')

    brain_stat = brain_root.stat()
    receipt_object = _domain_context("context.session-receipt") if committed else None
    coverage = direct_coverage(receipt_object) if receipt_object else None
    coverage_sha256 = (
        normalize_coverage(coverage).sha256 if coverage else "c" * 64
    )
    binding = BatchBinding(
        batch_manifest_sha256=_sha256(manifest.read_bytes()),
        item_key="fixture",
        item_input_fingerprint="a" * 64,
        verify_json_sha256="b" * 64,
        domain_spec_py_sha256="c" * 64,
        coverage_sha256=coverage_sha256,
        repo_root="/fixture/repo",
        brain_root=str(brain_root.resolve()),
        brain_root_device=brain_stat.st_dev,
        brain_root_inode=brain_stat.st_ino,
        expected_repo_id="fixture-repo",
        expected_revision_ref="HEAD",
        target_revision_sha="d" * 40,
        engine_root="/fixture/engine",
        engine_sha="e" * 40,
    )
    if receipt_object is None:
        receipt = _no_change_receipt(coverage_sha256)
        record_no_change_receipt(
            brain_root,
            binding=binding,
            receipt=normalize_mutation_receipt(receipt),
            verified_source_sha256_by_id={},
        )
    else:
        result = MutationService().apply(
            (receipt_object,),
            request=MutationRequest(
                operation=MutationOperation.INGEST,
                brain_root=brain_root,
                repo_context=None,
                engine_sha=binding.engine_sha,
                objects=(receipt_object,),
                batch_binding=binding,
                coverage=coverage,
            ),
        )
        assert result.ok, result.detail
        receipt = recover_committed_receipt(brain_root, binding)
    item_record = {
        "binding": asdict(binding),
        "status": receipt["outcome"],
        "failure": None,
        "expected_objects": receipt["expected_objects"],
        "verified_objects": receipt["verified_objects"],
        "changed_objects": receipt["changed_objects"],
        "receipt": receipt,
    }
    finalization = {
        "ok": True,
        "transactions": [receipt],
        "commands": {},
        "isolation": {},
        "unmerged": {},
        "recall_checks": [],
        "errors": [],
    } if finalized else None
    report = {
        "brain_root": str(brain_root.resolve()),
        "brain_root_device": brain_stat.st_dev,
        "brain_root_inode": brain_stat.st_ino,
        "manifest_sha256": _sha256(manifest.read_bytes()),
        "expected": 1,
        "item_records": [item_record],
        "succeeded": ["fixture"],
        "failed": [],
        "transactions": [receipt],
        "finalized": finalized,
        "finalization": finalization,
        "finalize_failure": None if finalized else {"exit_code": 1, "stderr": "pending"},
    }
    report_path = root / "ingest-batch-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    return {
        "brain_root": brain_root,
        "transcript": transcript,
        "manifest": manifest,
        "report": report_path,
    }


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


class SessionCompletionTest(unittest.TestCase):
    def test_complete_writes_receipt_bound_v2_marker_and_preserves_same_bytes(self):
        with TemporaryDirectory() as td:
            artifacts = _completion_artifacts(Path(td))

            completed = complete_session("abc", **artifacts)

            marker = artifacts["brain_root"] / ".brain-local" / "sessions" / "abc.json"
            first_bytes = marker.read_bytes()
            on_disk = json.loads(first_bytes)
            self.assertEqual(
                set(on_disk),
                {
                    "version", "state", "uuid", "transcript_sha256",
                    "manifest_sha256", "report_sha256", "receipt_ids", "processed_at",
                },
            )
            self.assertEqual(on_disk["version"], 2)
            self.assertEqual(on_disk["state"], "processed")
            self.assertEqual(on_disk["uuid"], "abc")
            receipt_id = json.loads(
                artifacts["report"].read_text(encoding="utf-8")
            )["item_records"][0]["receipt"]["receipt_id"]
            self.assertEqual(completed["receipt_ids"], [receipt_id])

            retried = complete_session("abc", **artifacts)

            self.assertEqual(retried["state"], "processed")
            self.assertEqual(marker.read_bytes(), first_bytes)
            self.assertTrue(is_processed("abc", brain_root=artifacts["brain_root"]))

    def test_complete_preserves_matching_marker_after_unrelated_corpus_change(self):
        with TemporaryDirectory() as td:
            artifacts = _completion_artifacts(Path(td), committed=True)
            completed = complete_session("abc", **artifacts)
            marker = artifacts["brain_root"] / ".brain-local" / "sessions" / "abc.json"
            marker_before = marker.read_bytes()

            unrelated = _domain_context("context.unrelated")
            unrelated_path = BrainStore.object_path(artifacts["brain_root"], unrelated)
            unrelated_path.parent.mkdir(parents=True, exist_ok=True)
            unrelated_path.write_bytes(BrainStore.object_bytes(unrelated))

            retried = complete_session("abc", **artifacts)

            self.assertEqual(retried, completed)
            self.assertEqual(marker.read_bytes(), marker_before)

    def test_concurrent_different_completion_requests_do_not_overwrite_marker(self):
        with TemporaryDirectory() as td:
            artifacts = _completion_artifacts(Path(td))
            alternate_dir = Path(td) / "alternate"
            alternate_dir.mkdir()
            alternate_transcript = alternate_dir / "abc.jsonl"
            alternate_transcript.write_bytes(
                artifacts["transcript"].read_bytes() + b"\n"
            )
            marker = artifacts["brain_root"] / ".brain-local" / "sessions" / "abc.json"
            replace_barrier = threading.Barrier(2)
            real_replace = session_module.os.replace
            outcomes: list[tuple[str, Path, object]] = []

            def synchronized_replace(source, destination):
                replace_barrier.wait(timeout=5)
                return real_replace(source, destination)

            def run_completion(transcript: Path) -> None:
                try:
                    result = complete_session(
                        "abc",
                        transcript=transcript,
                        manifest=artifacts["manifest"],
                        report=artifacts["report"],
                        brain_root=artifacts["brain_root"],
                    )
                    outcomes.append(("success", transcript, result))
                except SessionCompletionError as exc:
                    outcomes.append(("failure", transcript, exc))

            with mock.patch.object(session_module.os, "replace",
                                   side_effect=synchronized_replace):
                threads = [
                    threading.Thread(target=run_completion, args=(artifacts["transcript"],)),
                    threading.Thread(target=run_completion, args=(alternate_transcript,)),
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=5)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            successes = [outcome for outcome in outcomes if outcome[0] == "success"]
            failures = [outcome for outcome in outcomes if outcome[0] == "failure"]
            self.assertEqual(len(successes), 1)
            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0][2].code, "session_completion_conflict")
            self.assertEqual(
                json.loads(marker.read_bytes())["transcript_sha256"],
                _sha256(successes[0][1].read_bytes()),
            )

    def test_incomplete_or_drifted_report_never_creates_a_marker(self):
        with TemporaryDirectory() as td:
            artifacts = _completion_artifacts(Path(td), finalized=False)
            marker = artifacts["brain_root"] / ".brain-local" / "sessions" / "abc.json"
            report_before = artifacts["report"].read_bytes()

            with self.assertRaises(SessionCompletionError) as caught:
                complete_session("abc", **artifacts)

            self.assertEqual(caught.exception.code, "session_completion_report_invalid")
            self.assertFalse(marker.exists())
            self.assertEqual(artifacts["report"].read_bytes(), report_before)

        with TemporaryDirectory() as td:
            artifacts = _completion_artifacts(Path(td))
            report = json.loads(artifacts["report"].read_text(encoding="utf-8"))
            report["item_records"][0]["receipt"]["receipt_id"] = "0" * 64
            artifacts["report"].write_text(json.dumps(report), encoding="utf-8")
            marker = artifacts["brain_root"] / ".brain-local" / "sessions" / "abc.json"
            report_before = artifacts["report"].read_bytes()

            with self.assertRaises(SessionCompletionError) as caught:
                complete_session("abc", **artifacts)

            self.assertEqual(caught.exception.code, "session_completion_report_invalid")
            self.assertFalse(marker.exists())
            self.assertEqual(artifacts["report"].read_bytes(), report_before)

    def test_legacy_marker_is_not_processed_or_overwritten(self):
        with TemporaryDirectory() as td:
            artifacts = _completion_artifacts(Path(td))
            marker = artifacts["brain_root"] / ".brain-local" / "sessions" / "abc.json"
            marker.parent.mkdir(parents=True, exist_ok=True)
            legacy_bytes = (
                b'{"uuid":"abc","processed_at":"2026-08-26T00:00:00+09:00",'
                b'"note":"legacy"}\n'
            )
            marker.write_bytes(legacy_bytes)

            with self.assertRaises(SessionCompletionError) as caught:
                complete_session("abc", **artifacts)

            self.assertEqual(caught.exception.code, "legacy_unverified")
            self.assertEqual(marker.read_bytes(), legacy_bytes)
            self.assertFalse(is_processed("abc", brain_root=artifacts["brain_root"]))

    def test_mark_processed_requires_receipt_bound_completion_without_writing(self):
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            marker = brain_root / ".brain-local" / "sessions" / "abc.json"

            with self.assertRaises(SessionCompletionError) as caught:
                mark_processed("abc", brain_root=brain_root, note="미합의 2건")

            self.assertEqual(caught.exception.code, "session_completion_report_required")
            self.assertFalse(marker.exists())

    def test_scan_annotates_completed_marker(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "transcripts"
            proj = root / "p"
            proj.mkdir(parents=True)
            _write_jsonl(proj / "abc-123.jsonl", SESSION_LINES)
            artifacts = _completion_artifacts(Path(td) / "artifacts", uuid="abc-123")
            complete_session("abc-123", **artifacts)

            s = scan_sessions(transcript_root=root, brain_root=artifacts["brain_root"])[0]
            self.assertTrue(s["processed"])


if __name__ == "__main__":
    unittest.main()
