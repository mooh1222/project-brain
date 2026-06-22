# BB2 Brain 세션 적재 경로 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 적재 3경로 중 미구현 2경로 — (가) 진행 중 개발 적재, (다) 과거 세션 추출 — 와 공통 갱신 규약·색인 신선도 가드를 구축한다.

**Architecture:** 추출 판단은 Claude(신설 스킬 `bb2-brain-session-ingest`), 기록·마킹·스캔만 CLI(엔진 `project-brain`). 엔진에 session 모듈(jsonl 스캔+처리 마킹)과 색인 신선도 가드(meta 코퍼스 지문+검색 진입 대조)를 추가하고, 게임 레포에 스킬·규약 문서를 깐다. 스키마(18 kind) 변경 0.

**Tech Stack:** Python 표준 라이브러리(엔진 — sqlite3·json·hashlib), unittest(엔진 합성 테스트), 마크다운 스킬(게임 레포).

**스펙(권위):** `docs/superpowers/specs/2026-06-11-bb2-brain-session-ingest-design.md` (커밋 `f3b154a024`까지 3회 개정 — 적대 리뷰 15건 반영 포함)

**두 레포 주의:**
- 엔진 작업 디렉토리 = `~/Downloads/codes/project-brain` (편집 설치라 수정 즉시 `project-brain` 명령에 반영). 테스트: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/ -q` (venv 불필요 — 표준 unittest, 단 임베딩 테스트는 stub만 사용). push는 인자 없는 `git push`(보호 훅 우회 관례).
- 게임 레포 = `/Users/al03040455/Desktop/bb2_client`. 가드: `python3 -m pytest brain/checks/ -q` (아무 파이썬 OK). 골든셋: `project-brain eval --check-ids` 후 `project-brain eval`.
- 게임 레포 무관 더티 4파일(UserGameDataManager.cpp, MapController.cpp, SplashController.cpp, Podfile.lock)은 절대 staging 금지.

---

## Task 1: 엔진 — session.py 스캔 (payload cwd·메타 라인 처리)

**Files:**
- Create: `~/Downloads/codes/project-brain/src/project_brain/session.py`
- Test: `~/Downloads/codes/project-brain/tests/test_session.py`

- [x] **Step 1: 실패하는 테스트 작성**

`tests/test_session.py` 생성:

```python
"""session 모듈 테스트 — jsonl 스캔(payload cwd 정본·메타 라인 처리)과 처리 마킹.

스펙 §7: 세션 파일 선두는 mode/queue-operation/file-history-snapshot 같은
cwd 없는 메타 라인인 경우가 보통(실측). cwd는 "cwd 키가 있는 첫 라인"에서,
시작시각·메시지 수는 type ∈ {user, assistant} 라인 기준으로 산출한다.
"""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from project_brain.session import scan_sessions


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
    {"type": "attachment", "cwd": "/Users/x/Desktop/bb2_client",
     "timestamp": "2026-06-11T01:00:02.000Z"},
    {"type": "user", "cwd": "/Users/x/Desktop/bb2_client",
     "message": {"role": "user", "content": "질문"},
     "timestamp": "2026-06-11T01:00:03.000Z"},
    {"type": "assistant", "cwd": "/Users/x/Desktop/bb2_client",
     "message": {"role": "assistant", "content": []},
     "timestamp": "2026-06-11T01:00:04.000Z"},
    {"type": "user", "cwd": "/Users/x/Desktop/bb2_client",
     "message": {"role": "user", "content": "후속"},
     "timestamp": "2026-06-11T01:00:05.000Z"},
]


class ScanSessionsTest(unittest.TestCase):
    def test_scan_reads_cwd_from_first_line_having_cwd_not_first_line(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            proj = root / "-Users-x-Desktop-bb2-client"
            proj.mkdir()
            _write_jsonl(proj / "abc-123.jsonl", SESSION_LINES)

            sessions = scan_sessions(transcript_root=root)

            self.assertEqual(len(sessions), 1)
            s = sessions[0]
            self.assertEqual(s["uuid"], "abc-123")
            # 첫 줄(mode)이 아니라 cwd 키가 처음 등장한 라인의 cwd
            self.assertEqual(s["cwd"], "/Users/x/Desktop/bb2_client")

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

            hits = scan_sessions(transcript_root=root, project_filter="bb2_client")
            self.assertEqual([s["uuid"] for s in hits], ["a"])


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/test_session.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'project_brain.session'`

- [x] **Step 3: 최소 구현**

`src/project_brain/session.py` 생성:

```python
"""세션 transcript 스캔·처리 마킹 — (다) 과거 세션 추출의 CLI 보조(스펙 §7).

경계 불변: transcript 본문 해석·지식 추출은 CLI가 하지 않는다. 여기는
결정론 로직(스캔·집계·마킹)만 — 추출 판단은 스킬(Claude) 몫.

★jsonl 파싱 요구(스펙 §7, 실측)★: 세션 파일 선두는 mode/queue-operation/
file-history-snapshot 같은 cwd 없는 메타 라인인 경우가 보통이다. cwd는
"cwd 키가 있는 첫 라인"에서 읽고(디렉토리명은 인코딩 손실이라 정본 아님 —
워크트리 세션은 다른 디렉토리에 쌓인다), 시작시각·메시지 수는
type ∈ {user, assistant} 라인 기준으로 산출한다.
"""
from __future__ import annotations

import json
from pathlib import Path

DEFAULT_TRANSCRIPT_ROOT = Path.home() / ".claude" / "projects"
_MESSAGE_TYPES = {"user", "assistant"}


def scan_sessions(transcript_root=None, project_filter: str | None = None) -> list[dict]:
    """transcript_root 아래 모든 세션 jsonl의 요약 목록.

    반환 원소: {uuid, path, cwd, started_at, message_count}.
    project_filter: cwd에 이 부분 문자열이 포함된 세션만(예: "bb2_client").
    """
    root = Path(transcript_root) if transcript_root else DEFAULT_TRANSCRIPT_ROOT
    sessions = []
    for path in sorted(root.glob("*/*.jsonl")):
        info = _summarize(path)
        if project_filter and project_filter not in (info["cwd"] or ""):
            continue
        sessions.append(info)
    return sessions


def _summarize(path: Path) -> dict:
    cwd = None
    started_at = None
    message_count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue  # 깨진 라인은 집계에서 제외(스캔은 보수적으로 계속)
            if cwd is None and payload.get("cwd"):
                cwd = payload["cwd"]
            if payload.get("type") in _MESSAGE_TYPES:
                message_count += 1
                if started_at is None:
                    started_at = payload.get("timestamp")
    return {
        "uuid": path.stem,
        "path": str(path),
        "cwd": cwd,
        "started_at": started_at,
        "message_count": message_count,
    }
```

- [x] **Step 4: 통과 확인**

Run: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/test_session.py -q`
Expected: PASS (4 passed)

- [x] **Step 5: 커밋**

```bash
cd ~/Downloads/codes/project-brain && git add src/project_brain/session.py tests/test_session.py && git commit -m "feat(session): transcript 스캔 — payload cwd 정본·메타 라인 처리 (스펙 §7)"
```

---

## Task 2: 엔진 — 처리 마킹 (mark_processed / is_processed)

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/session.py`
- Test: `~/Downloads/codes/project-brain/tests/test_session.py`

- [x] **Step 1: 실패하는 테스트 추가**

`tests/test_session.py`에 import 갱신 + 클래스 추가:

```python
from project_brain.session import is_processed, mark_processed, scan_sessions
```

```python
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
```

- [x] **Step 2: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/test_session.py -q`
Expected: FAIL — `ImportError: cannot import name 'is_processed'`

- [x] **Step 3: 구현**

`session.py`에 추가 (scan_sessions 시그니처에 `brain_root=None` 추가, 마킹은 `.brain-local/sessions/` — 스펙 §7: 세션 jsonl 자체가 머신 로컬 자산이라 마킹도 머신 로컬, 소실 시 재백필 비용만):

```python
from datetime import datetime, timezone


def _marks_dir(brain_root) -> Path:
    return Path(brain_root) / ".brain-local" / "sessions"


def is_processed(uuid: str, brain_root) -> bool:
    return (_marks_dir(brain_root) / f"{uuid}.json").exists()


def mark_processed(uuid: str, brain_root, note: str | None = None) -> dict:
    """처리 완료 마킹 — 같은 uuid 재호출은 덮어쓴다(재실행 안전)."""
    d = _marks_dir(brain_root)
    d.mkdir(parents=True, exist_ok=True)
    record = {
        "uuid": uuid,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "note": note,
    }
    (d / f"{uuid}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return record
```

그리고 `scan_sessions`를 수정해 `brain_root` 인자(기본 None)와 processed 플래그를 단다:

```python
def scan_sessions(transcript_root=None, project_filter: str | None = None,
                  brain_root=None) -> list[dict]:
    root = Path(transcript_root) if transcript_root else DEFAULT_TRANSCRIPT_ROOT
    sessions = []
    for path in sorted(root.glob("*/*.jsonl")):
        info = _summarize(path)
        if project_filter and project_filter not in (info["cwd"] or ""):
            continue
        if brain_root is not None:
            info["processed"] = is_processed(info["uuid"], brain_root)
        sessions.append(info)
    return sessions
```

- [x] **Step 4: 통과 확인**

Run: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/test_session.py -q`
Expected: PASS (7 passed)

- [x] **Step 5: 커밋**

```bash
cd ~/Downloads/codes/project-brain && git add src/project_brain/session.py tests/test_session.py && git commit -m "feat(session): 처리 마킹 — .brain-local/sessions/, 재실행 덮어쓰기 (스펙 §7)"
```

---

## Task 3: 엔진 — CLI `session list` / `session mark-processed`

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/cli.py`
- Test: `~/Downloads/codes/project-brain/tests/test_cli.py`

- [x] **Step 1: 실패하는 테스트 추가**

`tests/test_cli.py`에 추가. 기존 패턴(실측 확인): `mock.patch("sys.argv", ["cli"] + argv)` + `redirect_stdout` + `cli.main()` — 파일 상단에 이미 `io`·`json`·`mock`·`redirect_stdout`·`cli` import가 있다.

```python
class CliSessionTest(unittest.TestCase):
    def _run_cli(self, argv):
        out = io.StringIO()
        with mock.patch("sys.argv", ["cli"] + argv), redirect_stdout(out):
            rc = cli.main()
        self.assertEqual(rc, 0)
        return out.getvalue()

    def test_session_list_outputs_json_with_processed_flag(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "t"
            proj = root / "p"
            proj.mkdir(parents=True)
            (proj / "abc.jsonl").write_text(
                '{"type": "user", "cwd": "/x/bb2", "timestamp": "2026-06-11T01:00:00Z"}\n',
                encoding="utf-8",
            )
            brain_root = Path(td) / "brain"
            out = self._run_cli(["session", "list", "--transcript-root", str(root),
                                 "--brain-root", str(brain_root)])
            payload = json.loads(out)
            self.assertEqual(payload["sessions"][0]["uuid"], "abc")
            self.assertFalse(payload["sessions"][0]["processed"])

    def test_session_list_unprocessed_filters_marked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "t"
            proj = root / "p"
            proj.mkdir(parents=True)
            (proj / "abc.jsonl").write_text(
                '{"type": "user", "cwd": "/x", "timestamp": "t"}\n', encoding="utf-8")
            (proj / "def.jsonl").write_text(
                '{"type": "user", "cwd": "/x", "timestamp": "t"}\n', encoding="utf-8")
            brain_root = Path(td) / "brain"
            self._run_cli(["session", "mark-processed", "abc",
                           "--brain-root", str(brain_root)])
            out = self._run_cli(["session", "list", "--transcript-root", str(root),
                                 "--brain-root", str(brain_root), "--unprocessed"])
            payload = json.loads(out)
            self.assertEqual([s["uuid"] for s in payload["sessions"]], ["def"])

    def test_session_mark_processed_writes_note(self):
        with tempfile.TemporaryDirectory() as td:
            brain_root = Path(td)
            out = self._run_cli(["session", "mark-processed", "abc",
                                 "--brain-root", str(brain_root), "--note", "미합의 1건"])
            payload = json.loads(out)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["record"]["note"], "미합의 1건")
```

- [x] **Step 2: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/test_cli.py -k session -q`
Expected: FAIL (session 분기 없음 — query 폴백 경로로 빠져 에러)

- [x] **Step 3: 구현**

`cli.py`에 `_run_session` 추가 + main 분기 추가 (다른 `_run_*`과 같은 모양):

```python
def _run_session(argv) -> int:
    """세션 transcript 스캔·처리 마킹 (스펙 §7) — (다) 과거 세션 추출의 CLI 보조.

    `session list [--unprocessed] [--project <substr>] [--transcript-root <p>] [--brain-root <p>]`
    `session mark-processed <uuid> [--note <text>] [--brain-root <p>]`

    추출 판단은 스킬(Claude) 몫 — 여기는 결정론 스캔·마킹만(경계 불변).
    """
    parser = argparse.ArgumentParser(prog="cli session")
    sub = parser.add_subparsers(dest="action", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--unprocessed", action="store_true",
                        help="처리 마킹 없는 세션만")
    p_list.add_argument("--project", help="cwd 부분 문자열 필터 (예: bb2_client)")
    p_list.add_argument("--transcript-root", help="기본: ~/.claude/projects")
    p_list.add_argument("--brain-root", help="brain root (마킹 대조, 기본: config)")

    p_mark = sub.add_parser("mark-processed")
    p_mark.add_argument("uuid")
    p_mark.add_argument("--note", help="비고 (예: '미합의 2건' — 스펙 §4)")
    p_mark.add_argument("--brain-root", help="brain root (기본: config)")

    args = parser.parse_args(argv)
    from project_brain.session import mark_processed, scan_sessions

    brain_root = resolve_brain_root(args.brain_root)
    if args.action == "list":
        sessions = scan_sessions(
            transcript_root=args.transcript_root,
            project_filter=args.project,
            brain_root=brain_root,
        )
        if args.unprocessed:
            sessions = [s for s in sessions if not s["processed"]]
        print(json.dumps({"ok": True, "sessions": sessions}, ensure_ascii=False, indent=2))
        return 0
    record = mark_processed(args.uuid, brain_root=brain_root, note=args.note)
    print(json.dumps({"ok": True, "record": record}, ensure_ascii=False, indent=2))
    return 0
```

main()의 분기 사다리에 추가 (`if argv and argv[0] == "search":` 줄 앞에):

```python
        if argv and argv[0] == "session":
            return _run_session(argv[1:])
```

주의: `resolve_brain_root` import가 cli.py에 이미 있는지 확인(다른 `_run_*`이 쓰고 있음) — 있으면 재사용.

- [x] **Step 4: 통과 확인**

Run: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/test_cli.py -q`
Expected: PASS (기존 + 신규 3)

- [x] **Step 5: 커밋**

```bash
cd ~/Downloads/codes/project-brain && git add src/project_brain/cli.py tests/test_cli.py && git commit -m "feat(cli): session list/mark-processed — (다) 백필 보조 (스펙 §7)"
```

---

## Task 4: 엔진 — 코퍼스 지문 (rebuild가 meta에 기록)

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/search_index.py`
- Test: `~/Downloads/codes/project-brain/tests/test_search_index.py`

- [x] **Step 1: 기존 meta 테스트 확인**

Run: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/test_search_index.py -k meta -q`
Expected: PASS — `test_rebuild_writes_meta`가 현재 meta 컬럼을 어떻게 단언하는지 읽어둔다 (컬럼 추가 시 이 테스트도 갱신).

- [x] **Step 2: 실패하는 테스트 추가**

`tests/test_search_index.py`에 (기존 RebuildTest 패턴 — `_b(obj)` 헬퍼·TemporaryDirectory 셋업 재사용):

```python
class CorpusFingerprintTest(unittest.TestCase):
    def test_rebuild_writes_corpus_fingerprint(self):
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            obj = _b({"id": "g.t.a", "kind": "GlossaryTerm", "status": "candidate",
                      "title": "용어", "context_id": "context.t",
                      "term": "용어", "definition": "정의"})
            BrainStore.save_object(brain_root, obj)
            db = brain_root / "idx.db"

            rebuild(brain_root=brain_root, db_path=db)

            conn = sqlite3.connect(db)
            fp = conn.execute("SELECT corpus_fingerprint FROM meta").fetchone()[0]
            conn.close()
            self.assertTrue(fp)  # 64자리 sha256 hex
            self.assertEqual(len(fp), 64)

    def test_fingerprint_changes_when_object_changes(self):
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            obj = _b({"id": "g.t.a", "kind": "GlossaryTerm", "status": "candidate",
                      "title": "용어", "context_id": "context.t",
                      "term": "용어", "definition": "정의"})
            BrainStore.save_object(brain_root, obj)
            db = brain_root / "idx.db"
            rebuild(brain_root=brain_root, db_path=db)
            conn = sqlite3.connect(db)
            fp1 = conn.execute("SELECT corpus_fingerprint FROM meta").fetchone()[0]
            conn.close()

            obj2 = dict(obj, status="reviewed")  # status 플립 = supersede 계열 변경
            BrainStore.save_object(brain_root, obj2)
            rebuild(brain_root=brain_root, db_path=db)
            conn = sqlite3.connect(db)
            fp2 = conn.execute("SELECT corpus_fingerprint FROM meta").fetchone()[0]
            conn.close()

            self.assertNotEqual(fp1, fp2)

    def test_compute_fingerprint_is_deterministic(self):
        from project_brain.search_index import compute_corpus_fingerprint
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            obj = _b({"id": "g.t.a", "kind": "GlossaryTerm", "status": "candidate",
                      "title": "용어", "context_id": "context.t",
                      "term": "용어", "definition": "정의"})
            BrainStore.save_object(brain_root, obj)
            store = BrainStore.load(brain_root)
            a = compute_corpus_fingerprint(store, brain_root)
            b = compute_corpus_fingerprint(store, brain_root)
            self.assertEqual(a, b)
```

- [x] **Step 3: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/test_search_index.py -k fingerprint -q`
Expected: FAIL — `no such column: corpus_fingerprint` / ImportError

- [x] **Step 4: 구현**

`search_index.py` 수정 4곳:

4-1. `SCHEMA_VERSION = 3` → `4` (search_index.py:35 실측 — meta 테이블 구조 변경이므로. **이 bump가 마이그레이션 전부다**: 구버전 색인은 기존 `_guard_schema_version`이 거부하고 rebuild를 안내한다).

4-2. 지문 함수 신설 (모듈 상단 함수들 근처):

```python
def compute_corpus_fingerprint(store, brain_root) -> str:
    """색인 대상 전체(객체 표면 + raw 청크)의 결정론 지문 — 신선도 가드(§7)용.

    rebuild가 색인하는 것과 같은 입력(extract_surface 표면 + iter_raw_sources
    청크)을 같은 규칙으로 직렬화해 sha256. 색인에 반영 안 되는 변경(예: 색인
    제외 kind의 필드)은 지문도 안 바뀐다 — 가드는 "색인이 코퍼스의 색인 대상
    내용과 일치하나"만 묻는다.
    """
    rows = []
    for obj in store.all():
        surface = extract_surface(obj)
        if surface is None:
            continue
        rows.append(f"{obj['kind']}\t{obj['id']}\t{obj.get('status', '')}\t{surface}")
    for ch in iter_raw_sources(Path(brain_root)):
        rows.append(f"{RAW_KIND}\t{ch['chunk_id']}\t{RAW_STATUS}\t{ch['text']}")
    payload = "\n".join(sorted(rows))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

확인됨(실측): `iter_raw_sources`는 `{chunk_id, context_id, text}`를 돌려준다(raw_chunks.py:107-126) — 위 코드의 키가 정확하다. `hashlib` import 추가 필요. `extract_surface`·`iter_raw_sources`(RAW_KIND·RAW_STATUS 포함)는 search_index.py에 이미 import돼 있다.

4-3. meta DDL에 컬럼 추가:

```python
    conn.execute(
        "CREATE TABLE meta ("
        "schema_version INTEGER, embed_model TEXT, tokenizer TEXT, "
        "extractor_version INTEGER, corpus_fingerprint TEXT)"
    )
```

4-4. rebuild의 meta INSERT를 지문 포함으로:

```python
        fingerprint = compute_corpus_fingerprint(store, Path(brain_root))
        conn.execute(
            "INSERT INTO meta (schema_version, embed_model, tokenizer, "
            "extractor_version, corpus_fingerprint) VALUES (?, ?, ?, ?, ?)",
            (SCHEMA_VERSION, embed_model, tokenizer, EXTRACTOR_VERSION, fingerprint),
        )
```

4-5. `_read_meta`(search_index.py:236-245, dict 반환 실측 확인) 갱신 — SELECT에 컬럼 추가 + 반환 dict에 키 추가:

```python
def _read_meta(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT schema_version, embed_model, tokenizer, extractor_version, "
        "corpus_fingerprint FROM meta LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return {"schema_version": row[0], "embed_model": row[1],
            "tokenizer": row[2], "extractor_version": row[3],
            "corpus_fingerprint": row[4]}
```

- [x] **Step 5: 통과 확인 + 기존 meta 테스트 갱신**

Run: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/test_search_index.py -q`
Expected: 신규 3 PASS. `test_rebuild_writes_meta`가 컬럼 수·값을 단언하다 깨지면 corpus_fingerprint 포함으로 갱신(단언 추가, 약화 금지).

- [x] **Step 6: 커밋**

```bash
cd ~/Downloads/codes/project-brain && git add src/project_brain/search_index.py tests/test_search_index.py && git commit -m "feat(index): 코퍼스 지문을 meta에 기록 — 신선도 가드 1/2 (스펙 §7, SCHEMA_VERSION bump)"
```

---

## Task 5: 엔진 — 검색 진입 신선도 대조 (stale 색인 명시 거부)

**Files:**
- Modify: `~/Downloads/codes/project-brain/src/project_brain/search.py`
- Test: `~/Downloads/codes/project-brain/tests/test_search.py`

- [x] **Step 1: 실패하는 테스트 추가**

`tests/test_search.py`에 (기존 recall 테스트의 셋업 패턴 — stub embedder로 rebuild 후 recall 호출 — 을 먼저 읽고 동일하게):

```python
class IndexFreshnessGuardTest(unittest.TestCase):
    def _seed_and_build(self, brain_root, db):
        obj = _b({"id": "g.t.a", "kind": "GlossaryTerm", "status": "candidate",
                  "title": "용어", "context_id": "context.t",
                  "term": "용어", "definition": "정의"})
        BrainStore.save_object(brain_root, obj)
        rebuild(brain_root=brain_root, db_path=db, embedder=StubEmbedder())

    def test_recall_raises_on_stale_index(self):
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            db = brain_root / "idx.db"
            self._seed_and_build(brain_root, db)

            # 색인 빌드 후 객체 변경(status 플립) → 색인이 stale
            obj2 = _b({"id": "g.t.a", "kind": "GlossaryTerm", "status": "reviewed",
                       "title": "용어", "context_id": "context.t",
                       "term": "용어", "definition": "정의"})
            BrainStore.save_object(brain_root, obj2)

            with self.assertRaises(RuntimeError) as ctx:
                recall("용어", db_path=db, brain_root=brain_root,
                       embedder=StubEmbedder())
            self.assertIn("rebuild", str(ctx.exception))  # 해결책이 담긴 메시지

    def test_recall_passes_on_fresh_index(self):
        with TemporaryDirectory() as td:
            brain_root = Path(td)
            db = brain_root / "idx.db"
            self._seed_and_build(brain_root, db)
            results = recall("용어", db_path=db, brain_root=brain_root,
                             embedder=StubEmbedder())
            self.assertIsInstance(results, list)  # 신선하면 기존 동작 그대로
```

- [x] **Step 2: 실패 확인**

Run: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/test_search.py -k freshness -q`
Expected: `test_recall_raises_on_stale_index` FAIL (에러 없이 결과 반환)

- [x] **Step 3: 구현**

`search.py`의 recall에서 store 확보 직후에 대조를 삽입한다. recall의 store 분기(현재
`if store is None: store = BrainStore.load(resolve_brain_root(brain_root))`)를 **resolve를
밖으로 빼는 형태**로 바꾼다 — 주입 store 경로(후속 b)에서도 raw 청크 지문 계산에
brain_root가 필요하기 때문(주입 최적화의 본질은 store 로드 생략이고 경로 해석은 싸다):

```python
    # store는 scope 추론·그래프 1-hop·surface 승급이 같이 쓴다 — ★호출당 1회만 로드★,
    # 주입받았으면(후속 b) 로드 생략. brain_root 해석은 신선도 가드(raw 지문)에도 필요.
    resolved_root = resolve_brain_root(brain_root)
    if store is None:
        store = BrainStore.load(resolved_root)
    # 신선도 가드(§7): 색인 meta의 코퍼스 지문 vs 현재 store 지문. stale 색인은
    # superseded 객체를 옛 status로 회상하는 침묵 오답을 만든다 — 스키마 버전
    # 가드와 같은 철학으로 시끄럽게 거부하고 해결책(rebuild)을 안내한다.
    _guard_index_freshness(db_path, store, resolved_root)
```

같은 파일에 가드 함수 추가:

```python
def _guard_index_freshness(db_path, store, brain_root) -> None:
    from project_brain.search_index import (
        compute_corpus_fingerprint, read_meta_fingerprint,
    )

    indexed = read_meta_fingerprint(db_path)
    if indexed is None:
        return  # 지문 없는 구버전 색인은 schema_version 가드가 이미 거부한다
    current = compute_corpus_fingerprint(store, brain_root)
    if indexed != current:
        raise RuntimeError(
            "색인이 코퍼스보다 오래됨(stale) — 객체 변경이 색인에 반영되지 않았다. "
            "`project-brain index rebuild`로 재생성 후 다시 검색하라."
        )
```

주의: 기존 recall docstring의 "store 주입 시 brain_root는 해석하지 않는다" 문구를 위 변경에
맞춰 갱신할 것(해석은 하되 로드만 생략).

`search_index.py`에 `read_meta_fingerprint(db_path)` 헬퍼 추가 (`_read_meta` 재사용):

```python
def read_meta_fingerprint(db_path) -> str | None:
    """색인 meta의 코퍼스 지문. 색인/meta/컬럼이 없으면 None."""
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    try:
        row = _read_meta(conn)
        return row["corpus_fingerprint"] if row else None
    except (sqlite3.OperationalError, KeyError, IndexError):
        return None
    finally:
        conn.close()
```

(시그니처·brain_root 전달은 위 코드에 반영 완료. `_read_meta`는 dict 반환 — 실측 확인,
Task 4의 4-5에서 corpus_fingerprint 키가 추가된다.)

- [x] **Step 4: 통과 확인 + 전체 회귀**

Run: `cd ~/Downloads/codes/project-brain && python3 -m pytest tests/ -q`
Expected: 전체 PASS (현재 317 + 신규 ~12). 기존 recall 테스트 중 "rebuild 후 객체 추가" 시나리오가 있으면 가드에 걸려 깨질 수 있다 — 그 테스트는 시나리오 의도에 맞게 rebuild를 다시 부르도록 수정(가드 약화 금지).

- [x] **Step 5: 커밋 + push**

```bash
cd ~/Downloads/codes/project-brain && git add src/project_brain/search.py src/project_brain/search_index.py tests/test_search.py && git commit -m "feat(search): 신선도 가드 — stale 색인 명시 거부+rebuild 안내, 신선도 가드 2/2 (스펙 §7)" && git push
```

---

## Task 6: 게임 레포 — 색인 재생성 + 가드·골든셋 회귀

**Files:**
- Modify: `/Users/al03040455/Desktop/bb2_client/brain/.brain-local/index.db` (재생성 — git 밖)

- [x] **Step 1: 색인 재생성 (SCHEMA_VERSION bump로 기존 색인은 거부됨)**

Run: `cd /Users/al03040455/Desktop/bb2_client && project-brain index rebuild`
Expected: JSON에 `indexed` ≈ 457, `raw_chunks` ≈ 96 (Task 4의 bump 때문에 rebuild 전 `project-brain search`는 schema_version 에러가 나는 게 정상 — 그게 가드).

- [x] **Step 2: 가드 + 골든셋 + 신선도 가드 실연**

```bash
cd /Users/al03040455/Desktop/bb2_client
python3 -m pytest brain/checks/ -q          # 5 passed
project-brain eval --check-ids               # 기대 id 실존
project-brain eval                           # 골든셋 7/7
project-brain search "스테이지 클리어 개수 어디 구현"   # 기존 회상 불변 확인
```

Expected: 가드 5 passed / 골든셋 summary passed 7 failed 0 / search 결과 reviewed 매핑+code locator 동반 (분리 전과 동일).

- [x] **Step 3: 신선도 가드 실코퍼스 실연 (통과 기준 §0.3)**

```bash
cd /Users/al03040455/Desktop/bb2_client
touch /tmp/fresh-check && python3 - <<'EOF'
import json, pathlib
p = sorted(pathlib.Path("brain/objects/domain").glob("*.json"))[0]
d = json.loads(p.read_text())
d["tags"] = list(d.get("tags", [])) + ["freshness-probe"]
p.write_text(json.dumps(d, ensure_ascii=False, indent=1))
EOF
project-brain search "스테이지 클리어" ; echo "exit=$?"
git -C . checkout -- brain/objects/domain/   # 프로브 원복
project-brain search "스테이지 클리어" | head -3   # 원복 후 정상
```

Expected: 프로브 후 search가 "stale — rebuild" 에러(exit 0 아님), 원복 후 정상. (tags는 표면에 안 들어가면 지문이 안 변한다 — 그 경우 definition을 건드리는 프로브로 바꿔서 확인. extract_surface가 무엇을 표면에 넣는지에 따라 조정.)

- [x] **Step 4: 결과 기록**

이 시점 게임 레포 커밋 없음(색인은 git 밖). 수치를 Task 10 검증 보고에 합류.

---

## Task 7: 게임 레포 — 신설 스킬 `bb2-brain-session-ingest`

**Files:**
- Create: `/Users/al03040455/Desktop/bb2_client/.claude/skills/bb2-brain-session-ingest/SKILL.md`
- Create: `.claude/skills/bb2-brain-session-ingest/references/update-rules.md`
- Create: `.claude/skills/bb2-brain-session-ingest/references/dev-ingest.md`
- Create: `.claude/skills/bb2-brain-session-ingest/references/session-extract.md`
- Create: symlink `.agents/skills/bb2-brain-session-ingest` → `../../.claude/skills/bb2-brain-session-ingest`

- [x] **Step 1: SKILL.md 작성**

```markdown
---
name: bb2-brain-session-ingest
description: |
  Use when BB2(LineBubble2) 개발을 진행하면서 brain에 적재하거나(시나리오 가 — 기능 개발
  시작·개발 중 "이거 저장해두자"·저장된 객체 값 갱신), 과거 세션 기록에서 지식을 추출할 때
  (시나리오 다 — "이 세션에서 추출", "과거 세션에서 뽑아줘", "백필", "세션 지식 추출").
  "개발하면서 brain에", "기획서 후보 선점", "이 결정 저장해줘", "세션 백필"처럼 진행 중
  적재·세션 추출이 BB2 맥락에서 나오면 스킬 이름 없이도 이 스킬을 쓴다.
  완료된 기능의 소급 적재는 bb2-brain-ingest 몫이고, 회상(읽기)은 bb2-brain-query 몫이다.
---

# BB2 Brain 세션 적재 — (가) 진행 중 개발 + (다) 과거 세션 추출

스펙(권위): `docs/superpowers/specs/2026-06-11-bb2-brain-session-ingest-design.md`
경계: 추출 판단(무엇을 지식으로 뽑나)은 이 스킬(Claude), 기록·마킹·스캔만 CLI.

## 어느 시나리오인가

| 상황 | 절차 |
|---|---|
| 기능 개발 시작·개발 중 적재·객체 값 갱신 | references/dev-ingest.md ((가) 4단계) |
| 끝난 세션에서 지식 추출 (지정/주제/일괄) | references/session-extract.md ((다) 코어+3모드) |
| 이미 저장된 객체와 현실이 다름 | references/update-rules.md (갱신 분기표) — 양쪽 공통 |

## 공통 불변 규칙

- 적재 후 4단계: `project-brain ingest …` 성공 → `index rebuild` → `eval --check-ids && eval`(골든셋) → 샘플 `search`. 색인 신선도 가드가 rebuild 누락을 막아주지만, 골든셋 회귀는 절차로만 잡힌다.
- 적재로 색인 행 수가 변하면 실코퍼스 가드 수치(`brain/checks/test_real_corpus.py`)를 **의식적으로 갱신**하고 같은 커밋에 포함한다.
- 파괴 작업(promote·일괄 수정) 전 "커밋 먼저".
- 검수 상태: 사용자 명시 지시 = reviewed(reviewer=user-statement) / 어시스턴트 판단 = candidate. reviewed 객체의 의미 변경은 검토 라운드 없이 금지(update-rules.md).
- 분류 3종(스펙 §6): 팀 지식 → 적재 / 개인 메모리(주어가 사용자·어시스턴트·작업 방식) → 적재 안 함, auto-memory·handoff에 / 기존 kind로 못 담는 교훈·함정 → `brain/raw/insight-backlog.md`에 누적(P3 실례 수집 — 날짜·출처 세션 uuid·한 줄 요약·핵심 인용).
```

- [x] **Step 2: references/update-rules.md 작성 (스펙 §5의 운반본)**

```markdown
# 갱신 운용 규약 — 이미 저장된 객체와 현실이 다를 때

분기 판단 한 줄: **"과거 시점 질문('전엔 어땠어/왜 바뀌었어')의 답이 되는 변경인가?"**
그렇다 → supersede(매핑)/TemporalFact 묶음(값). 아니다 → 제자리 수정.

| 변경 유형 | 처리 | 예 |
|---|---|---|
| 매핑 의미 변경 (DomainMapping) | supersede: 새 매핑 + `supersedes_mapping_ids` 연결, 옛 매핑 status=`superseded` — lint 8d가 잔존 차단 | 매핑 대상 교체 |
| 값 변경 (수치·enum) | **3객체 묶음**: EventLedgerRecord(원인) + 새 TemporalFact(`derived_from_event_id`=그 event, `supersedes`=옛 fact id). TemporalFact는 derived_from_event_id 필수 + why_changed 회상은 event 파생 fact만 사슬을 탐 — EventLedgerRecord 없이는 적재도 회상도 안 됨 | 광고 버튼 82%→85% |
| 그 외 kind 의미 변경 (GlossaryTerm 정의 등) | 제자리 수정 + DecisionRecord 연결 (supersede 장치는 매핑·fact 전용 — 용어엔 없음. "왜"는 DecisionRecord가, 과거 표현은 git 이력이 담당) | 용어 정의 변경·개칭 |
| 스냅샷 갱신 (코드 위치·라인·verified_at·오타) | 제자리 수정 + updated_at만 | 함수 이동, 라인 드리프트 |
| 원인이 있는 변경 | 위 처리 + DecisionRecord 연결. lint(8c)는 **reviewed 매핑에만** 발화 — candidate 구간은 이 절차가 책임 | 기획 변경 |

## 원자성 의무 (06-09 부분쓰기 사고 계열 차단)

supersede 묶음 = **새 객체 + status=superseded로 바꾼 옛 객체 + (값 변경이면) EventLedgerRecord를
한 번들로 `project-brain ingest`**. ingest는 번들 객체만 쓴다 — 옛 객체를 번들에서 빠뜨리면
디스크에 reviewed로 잔존해 옛 정설이 계속 회상된다. 적재 후 index rebuild까지가 한 동작.

## reviewed 객체의 의미 변경

반드시 검토 라운드(사용자 확인)를 거쳐 **reviewed 유지**로 수정한다. 어시스턴트 단독으로는
reviewed 의미 변경 금지(새 candidate 제안만 가능) — ingest의 reviewed→candidate 강등 거부
가드와 정합(강등 시나리오를 만들지 않는다).

## 값 변경 3객체 묶음 견본 (스펙 §5 — 코퍼스에 전례 0건이라 첫 실전용 견본)

광고 버튼 82%→85% 가정. 한 번들로 `project-brain ingest`:

```json
[
  {
    "id": "event.stage-clear-token.ad-button-scale-20260701",
    "kind": "EventLedgerRecord", "schema_version": "0.1", "status": "candidate",
    "poc_priority": "P2", "truth_role": "event",
    "title": "광고 버튼 스케일 82%→85% 변경",
    "event_type": "spec_revision", "happened_at": "2026-07-01T00:00:00Z",
    "summary": "기획 개정으로 광고 버튼 setScale 0.82f→0.85f",
    "related_objects": ["fact.stage-clear-token.ad-button-scale-v2"],
    "created_at": "2026-07-01T00:00:00Z", "updated_at": "2026-07-01T00:00:00Z",
    "tags": ["stage-clear-token"], "evidence_refs": []
  },
  {
    "id": "fact.stage-clear-token.ad-button-scale-v2",
    "kind": "TemporalFact", "schema_version": "0.1", "status": "candidate",
    "poc_priority": "P2", "truth_role": "fact",
    "title": "광고 버튼 스케일 = 85%",
    "subject": "mapping.stage-clear-token.ad-button", "predicate": "scale",
    "value": "0.85", "scope": "context.stage-clear-token",
    "valid_from": "2026-07-01T00:00:00Z",
    "derived_from_event_id": "event.stage-clear-token.ad-button-scale-20260701",
    "confidence": "high",
    "supersedes": "fact.stage-clear-token.ad-button-scale-v1",
    "created_at": "2026-07-01T00:00:00Z", "updated_at": "2026-07-01T00:00:00Z",
    "tags": ["stage-clear-token"], "evidence_refs": []
  }
]
```

(옛 fact가 이미 있으면 `supersedes`로 잇고, 옛 fact는 번들에 status=`superseded`로 동봉 —
원자성 의무. 옛 fact가 없으면(첫 기록) supersedes 생략. subject·id는 실제 대상 객체에 맞출 것.)
```

- [x] **Step 3: references/dev-ingest.md 작성 (스펙 §3의 운반본)**

```markdown
# (가) 진행 중 개발 적재 — 시간차 흐름 4단계

발동: 기획서 기반 기능 개발 착수, 또는 개발 중 "이거 저장해두자".

1. **후보 선점** (개발 시작): 기획서 분석에서 저장 후보(용어·매핑·결정)를 candidate로 바로
   적재. 코드 앵커 없이 가능(candidate는 evidence 강제 없음). EvidenceRef는 기획서
   (raw/sources/<context>/ 보관 — 규약 brain/README.md). DomainContext도 이때 신설.
2. **코드 연결** (개발 중): 코드가 생기면 CodeLocator 추가 + 매핑 연결. locator는 경로+심볼
   힌트(라인=조사 당시 스냅샷, verified_at이 시점) — 작업 브랜치 기준으로 달고, develop 머지
   시 스냅샷 갱신(제자리)으로 정정한다.
3. **갱신** (값·구조가 바뀔 때): references/update-rules.md 분기표.
4. **완료 마무리** (기능 완료): reviewed 승격 검토 + history 보강 — 완료 소급(bb2-brain-ingest)
   수준으로 닫는다. develop 기준으로 locator 수렴. 중복·병합 판정은 에이전트.

**폐기 경로**: 기능 폐기·기획 취소 시 그 context의 후보 선점 candidate를 일괄
status=`rejected`로 전환(사유 노트). 코드 앵커 없는 candidate가 잔존하면 회상 후보 채널에
실재하지 않는 기능이 계속 떠 오답을 유도한다.
```

- [x] **Step 4: references/session-extract.md 작성 (스펙 §4의 운반본)**

```markdown
# (다) 과거 세션 추출 — 코어 절차 + 입력 3모드

## 입력 3모드 (코어는 동일)

| 모드 | 흐름 |
|---|---|
| 세션 직접 지정 | 사용자가 지목한 세션에 코어 절차 |
| 주제·기능 단위 | `project-brain session list --project bb2_client`로 후보 발견 → 관련성 판단(요약·grep) → 관련 세션들에 코어 반복 |
| 일괄 백필 | `session list --unprocessed` 순회 → 세션마다 코어. 마킹 덕에 중단·재개 안전 |

## 코어 절차

1. transcript Read — 세션 경로는 `session list` 출력의 path. cwd는 CLI가 payload 기준으로
   판별해 줌(디렉토리명은 정본 아님 — 워크트리 세션 포함).
2. kind별 후보 추출: DecisionRecord·GlossaryTerm·DomainMapping·TemporalFact(값 변경이면
   update-rules.md의 3객체 묶음). 기존 kind로 못 담는 교훈·함정 → `brain/raw/insight-backlog.md`
   누적(버리지 않는다 — P3 실례). 개인 메모리(주어가 사용자·어시스턴트)는 적재 안 함, 표시만.
3. **검토 라운드** (최대 3): 후보를 표로 일괄 제시 → 사용자 자연어 일괄 응답 → 반영.
   중복 의심은 경고 표시만(자동 제외 금지). **3라운드 소진 후 미합의 후보는 적재하지 않고**
   mark-processed `--note`("미합의 N건")로 남긴다 — 사용자가 결정하지 않은 것은 코퍼스에
   넣지 않는다.
4. ingest → 적재 후 4단계(SKILL.md 공통 규칙) → `project-brain session mark-processed <uuid>`.

## 가드

- **과거 진술 주의**: 세션 내용은 "그 시점 사실" — 현재 develop 코드와 대조 전에는 reviewed
  금지. 충돌 시 코드 정설 + caveat. 단 코드에 없는 지식(의도·결정)의 사용자 진술 자체는
  reviewer=user-statement로 reviewed 가능(전례: decision.petskill-honeyjar.data-first-processing-order).
- **id 안정성**: 추출물 id는 의미 기반 결정론(`kind.context.slug`) — 같은 대상은 재추출에서도
  같은 id(부분 적재 후 재실행이 ingest 멱등과 결합돼 중복을 안 만든다).
- **EvidenceManifest**: source_type=session, locator=`claude-session:<uuid>#<날짜>`,
  redaction_status=**"approved" 명시**(화이트리스트 게이트 — 다른 값은 답이 restricted 처리됨).
  세션 로그 raw는 brain에 저장하지 않는다(참조만).
```

- [x] **Step 5: symlink + 검증**

```bash
cd /Users/al03040455/Desktop/bb2_client && ln -s ../../.claude/skills/bb2-brain-session-ingest .agents/skills/bb2-brain-session-ingest && ls -la .agents/skills/ | grep session
```

Expected: symlink가 기존 스킬들과 같은 상대 경로 패턴 (기존 symlink를 `ls -la .agents/skills/`로 먼저 보고 동일 형태 확인).

스킬 파일은 git 미추적(기존 관례) — 커밋 없음.

---

## Task 8: 게임 레포 — 기존 스킬 정정 + README + 백로그 자리

**Files:**
- Modify: `.claude/skills/bb2-brain-ingest/references/scope.md` (시나리오 표)
- Modify: `brain/README.md` (추적 경계 표 2행)
- Create: `brain/raw/insight-backlog.md`

- [x] **Step 1: scope.md 시나리오 표 갱신**

(가)(다) 행의 "**아니오** (follow-up)"를 신설 스킬 안내로:

```markdown
| 시나리오 | 뼈대 | 이 스킬이 다루나 |
|---|---|---|
| (가) 진행 중 개발 — 세션 도중 적재 | 기획서로 저장 후보 선점 → 코드 생기며 연결 | **아니오 — `bb2-brain-session-ingest`** |
| (나) 완료 스펙 소급 적재 | **코드** | **예 — 이 스킬** |
| (다) 과거 세션 히스토리에서 추출 | 끝난 세션 로그 마이닝 | **아니오 — `bb2-brain-session-ingest`** |
```

같은 파일 끝의 "범위 밖이면" 문단도 "이 스킬은 아직 그걸 안 다룬다고 알리고 멈춰라"를
"`bb2-brain-session-ingest` 스킬로 전환하라"로 수정. SKILL.md frontmatter의
"진행 중 개발의 실시간 적재나 과거 세션 로그 마이닝은 범위 밖이다(references/scope.md)"는
"…는 bb2-brain-session-ingest 몫이다(references/scope.md)"로.

- [x] **Step 2: brain/README.md 추적 경계 표에 2행 추가**

기존 표(`brain/.brain-local/` 행 근처)에:

```markdown
| brain/raw/insight-backlog.md | git 추적 | 기존 kind로 못 담는 세션 인사이트 누적 — P3(인사이트 그릇 kind) 설계의 실례 입력 |
| brain/.brain-local/sessions/ | 로컬 (gitignore) | 세션 처리 마킹 — 비파생 운영 상태 예외. 소실 시 재백필 비용만(데이터 무손상, 적재 멱등은 에이전트 몫) |
```

- [x] **Step 3: insight-backlog.md 생성**

```markdown
# 인사이트 백로그 — 기존 kind로 못 담는 것 (P3 설계 입력)

스펙: docs/superpowers/specs/2026-06-11-bb2-brain-session-ingest-design.md §6.
항목 형식: 날짜 / 출처 세션 uuid / 한 줄 요약 / 핵심 원문 인용.
이 파일이 쌓이면 P3(인사이트 그릇 kind)의 "실사용 실례 확보 후 설계" 가드 요건이 충족된다.

---
```

- [x] **Step 4: 게임 레포 커밋 (README·백로그만 — 스킬은 미추적)**

```bash
cd /Users/al03040455/Desktop/bb2_client && git add brain/README.md brain/raw/insight-backlog.md && git commit -m "docs(brain): 세션 적재 규약 — insight-backlog 신설 + 마킹 예외 행 (스펙 §6·§7)"
```

(scope.md는 .claude/skills/ 아래라 미추적 — staging에 안 잡히는 게 정상.)

---

## Task 9: (다) 실세션 검증 — 추출 완주 (스펙 §0.1)

**Files:**
- Modify: `brain/` (적재 객체), `brain/checks/test_real_corpus.py` (가드 수치)

- [x] **Step 1: 세션 후보 제시 → 사용자 선택**

```bash
cd /Users/al03040455/Desktop/bb2_client && project-brain session list --project bb2_client --unprocessed | python3 -c "import json,sys; d=json.load(sys.stdin); [print(s['uuid'][:8], s['started_at'], s['message_count']) for s in d['sessions'][-15:]]"
```

후보 목록을 사용자에게 보이고 추출 대상 세션 1개를 고른다 (페트스킬 꿀통 QA나 샐리 카누 QA처럼 도메인 지식이 흐른 세션 권장).

- [x] **Step 2: 신설 스킬 절차로 추출 완주**

`bb2-brain-session-ingest`의 session-extract.md 코어 절차 그대로: transcript Read → kind별 후보+백로그+개인메모리 분류 → 검토 라운드(사용자) → ingest → 적재 후 4단계 → mark-processed.

- [x] **Step 3: 가드 수치 갱신 + 전체 검증**

적재 후 `project-brain index rebuild` 출력의 indexed·raw_chunks 수치로 `brain/checks/test_real_corpus.py`의 `EXPECTED_OBJECT_ROWS`/`EXPECTED_RAW_CHUNKS`를 갱신:

```bash
cd /Users/al03040455/Desktop/bb2_client
python3 -m pytest brain/checks/ -q     # 갱신 후 5 passed
project-brain eval                      # 골든셋 7/7
project-brain search "<추출한 지식에 대한 질의>"   # 재회상 확인
```

- [x] **Step 4: 커밋**

```bash
cd /Users/al03040455/Desktop/bb2_client && git add brain/ && git commit -m "feat(brain): (다) 첫 실세션 추출 — <세션 요약> N객체 (스펙 §0.1 통과)"
```

(무관 더티 4파일 staging 금지 재확인 — `git status`로 brain/ 만 잡혔는지 확인 후 커밋.)

---

## Task 10: 마무리 — recall 스킬 한 줄(승인) + 문서 갱신

- [x] **Step 1: recall 스킬 보강 승인 요청**

사용자에게: bb2-brain-query에 "superseded 객체는 회상에서 제외되고 why_changed가 supersedes 사슬로 변경 이력을 답한다" 인지 한 줄 추가 승인 요청 (스킬 수정은 승인 필수 — 기준선: raw_excerpts는 이미 반영돼 있음). 승인 시 SKILL.md 채널 해석 표 아래에 추가.

- [x] **Step 2: vault task·정본 갱신**

`~/Desktop/vault/tasks/active/bb2-project-brain-build.md`: 작업 이력에 이번 세션 항목 추가 (스펙 3커밋 + 엔진 커밋들 + 게임 레포 커밋 + (다) 첫 완주 수치), 로드맵 P5의 미결 6(hook)은 보류 유지 표기, "다음 세션 시작점" 갱신. 정본 `[[bb2-project-brain]]` §4 표에 L4 적재 행 갱신(3경로 완성) + §7 미결 표 갱신.

- [x] **Step 3: 최종 보고**

전체 검증 수치(엔진 N passed / 가드 5 / 골든셋 7/7 / (다) 완주 결과 / 신선도 가드 실연)를 사용자에게 보고.
