import io
import json
import sys
from contextlib import redirect_stdout
from unittest import mock

from project_brain import cli


UPDATED = "2026-08-28T18:30:00+09:00"


def _run_cli(*args: str) -> tuple[int, dict]:
    output = io.StringIO()
    with mock.patch.object(sys, "argv", ["project-brain", *args]):
        with redirect_stdout(output):
            rc = cli.main()
    return rc, json.loads(output.getvalue())


def test_draft_create_list_and_show_resolve_brain_root_from_config(tmp_path, monkeypatch):
    (tmp_path / ".project-brain.json").write_text(
        json.dumps({"brain_root": "knowledge"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with mock.patch("project_brain.draft.now_kst", return_value=UPDATED):
        create_rc, created = _run_cli(
            "draft",
            "create",
            "canoe-audit",
            "--title",
            "카누 어휘 감사",
            "--scope",
            "기획과 서버 의미 대조",
            "--source",
            "manifest.sally-canoe.spec-v8",
        )
    list_rc, listed = _run_cli("draft", "list")
    show_rc, shown = _run_cli("draft", "show", "canoe-audit")

    assert (create_rc, list_rc, show_rc) == (0, 0, 0)
    assert created["draft"] == shown["draft"]
    assert listed == {
        "ok": True,
        "drafts": [{
            "topic_id": "canoe-audit",
            "title": "카누 어휘 감사",
            "scope": "기획과 서버 의미 대조",
            "updated": UPDATED,
        }],
    }


def test_draft_update_reports_stale_sha_as_json_without_overwriting(tmp_path, monkeypatch):
    (tmp_path / ".project-brain.json").write_text(
        json.dumps({"brain_root": "brain"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with mock.patch("project_brain.draft.now_kst", return_value=UPDATED):
        _, created = _run_cli(
            "draft",
            "create",
            "update-topic",
            "--title",
            "갱신 초안",
            "--scope",
            "갱신 범위",
        )
    first = created["draft"]
    content_path = tmp_path / "updated.md"
    content_path.write_text(
        first["content"].replace(
            f"Updated: {UPDATED}",
            "Updated: 2026-08-28T19:00:00+09:00",
        ),
        encoding="utf-8",
    )

    update_rc, updated = _run_cli(
        "draft",
        "update",
        "update-topic",
        "--expected-sha",
        first["sha256"],
        "--content-file",
        str(content_path),
    )
    stale_rc, stale = _run_cli(
        "draft",
        "update",
        "update-topic",
        "--expected-sha",
        first["sha256"],
        "--content-file",
        str(content_path),
    )
    _, shown = _run_cli("draft", "show", "update-topic")

    assert update_rc == 0
    assert stale_rc == 1
    assert stale["error_code"] == "draft_stale_sha"
    assert stale["actual_sha"] == updated["draft"]["sha256"]
    assert shown["draft"] == updated["draft"]


def test_draft_lint_returns_json_and_nonzero_for_a_broken_draft(tmp_path, monkeypatch):
    (tmp_path / ".project-brain.json").write_text(
        json.dumps({"brain_root": "brain"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    with mock.patch("project_brain.draft.now_kst", return_value=UPDATED):
        _, created = _run_cli(
            "draft",
            "create",
            "lint-topic",
            "--title",
            "검사 초안",
            "--scope",
            "검사 범위",
        )

    clean_rc, clean = _run_cli("draft", "lint")
    draft_path = tmp_path / "brain" / created["draft"]["path"]
    draft_path.write_text(
        created["draft"]["content"].replace(
            "<!-- project-brain-draft:v1 -->\n",
            "",
        ),
        encoding="utf-8",
    )
    broken_rc, broken = _run_cli("draft", "lint", "lint-topic")

    assert clean_rc == 0
    assert clean == {"ok": True, "problems": []}
    assert broken_rc == 1
    assert broken["ok"] is False
    assert [problem["code"] for problem in broken["problems"]] == [
        "draft_marker_invalid"
    ]


def test_configured_symlinked_brain_root_cannot_escape_draft_writes(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    outside_root = tmp_path / "outside-brain"
    project_root.mkdir()
    outside_root.mkdir()
    (project_root / "brain").symlink_to(outside_root, target_is_directory=True)
    (project_root / ".project-brain.json").write_text(
        json.dumps({"brain_root": "brain"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(project_root)

    rc, payload = _run_cli(
        "draft",
        "create",
        "escaped-topic",
        "--title",
        "이탈 초안",
        "--scope",
        "이탈 범위",
    )

    assert rc == 1
    assert payload["error_code"] == "draft_path_invalid"
    assert not (outside_root / "drafts" / "escaped-topic.md").exists()
