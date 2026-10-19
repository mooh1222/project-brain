import io
import json
import sys
import subprocess
from contextlib import redirect_stdout
from unittest import mock
import hashlib
import pytest

from project_brain.draft import create as create_legacy

from project_brain import cli


def run_cli(*args):
    output = io.StringIO()
    with mock.patch.object(sys, "argv", ["project-brain", *map(str, args)]):
        with redirect_stdout(output):
            rc = cli.main()
    return rc, json.loads(output.getvalue())


def test_new_topic_is_json_and_default_show_is_a_small_resume_view(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "brain"
    rc, created = run_cli(
        "draft", "create", "coupon", "--title", "쿠폰", "--scope", "만료 판정",
        "--brain-root", root,
    )
    assert rc == 0
    assert created["draft"]["format"] == "json-v2"
    assert created["draft"]["path"] == "drafts/coupon.json"
    assert created["draft"]["resume_summary"] == ""
    assert created["draft"]["items"] == []
    assert "content" not in created["draft"]
    document = json.loads((root / "drafts/coupon.json").read_text())
    assert document["version"] == 2
    assert document["sources"] == []
    show_rc, shown = run_cli("draft", "show", "coupon", "--brain-root", root)
    assert show_rc == 0
    assert shown == created


def test_patch_records_items_and_reads_only_selected_sources(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "brain"
    _, created = run_cli("draft", "create", "coupon", "--title", "쿠폰", "--scope", "만료", "--brain-root", root)
    patch = tmp_path / "patch.json"
    patch.write_text(json.dumps({
        "resume_summary": "서버 시각 기준 판정 확인",
        "sources": [{"op": "add", "value": {
            "key": "spec", "kind": "document", "locator": {"path": "spec.md", "section": "만료"},
        }}],
        "items": [
            {"op": "add", "value": {"key": "expiry", "kind": "finding", "text": "서버 시각으로 만료를 판정한다.", "source_keys": ["spec"], "recall_question": "쿠폰 만료 시각 기준은?"}},
            {"op": "add", "value": {"key": "unknown", "kind": "question", "text": "표시는 어떤 시각을 쓰나?", "source_keys": []}},
        ],
    }), encoding="utf-8")
    rc, updated = run_cli("draft", "update", "coupon", "--brain-root", root,
                          "--expected-sha", created["draft"]["sha256"], "--patch-file", patch)
    assert rc == 0
    assert updated["draft"]["changed_items"] == ["expiry", "unknown"]
    assert "document" not in updated["draft"] and "content" not in updated["draft"]
    rc, selected = run_cli("draft", "show", "coupon", "--brain-root", root, "--item", "expiry")
    assert rc == 0
    assert selected["draft"]["item"]["text"] == "서버 시각으로 만료를 판정한다."
    assert [s["key"] for s in selected["draft"]["sources"]] == ["spec"]
    assert "unknown" not in json.dumps(selected, ensure_ascii=False)
    rc, overview = run_cli("draft", "show", "coupon", "--brain-root", root)
    assert rc == 0
    assert overview["draft"]["resume_summary"] == "서버 시각 기준 판정 확인"
    assert [item["key"] for item in overview["draft"]["items"]] == ["expiry", "unknown"]
    assert "sources" not in overview["draft"]
    rc, full = run_cli("draft", "show", "coupon", "--brain-root", root, "--full")
    assert rc == 0
    assert full["draft"]["document"]["items"][0]["recall_question"] == "쿠폰 만료 시각 기준은?"


def test_current_code_observation_uses_working_checkout_and_metadata_patch_preserves_it(tmp_path, monkeypatch):
    repo = tmp_path / "working"
    repo.mkdir()
    for args in (("init",), ("config", "user.email", "test@example.invalid"), ("config", "user.name", "Test")):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / "code.cpp").write_text("int server_time = 1;\n")
    subprocess.run(["git", "add", "code.cpp"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / ".project-brain.json").write_text(json.dumps({"repo": "demo", "brain_root": "brain"}))
    (repo / "code.cpp").write_text("int server_time = 2;\n")
    monkeypatch.chdir(repo)
    root = tmp_path / "shared-brain"
    _, created = run_cli("draft", "create", "coupon", "--title", "쿠폰", "--scope", "만료", "--brain-root", root)
    patch = tmp_path / "observe.json"
    patch.write_text(json.dumps({"sources": [{"op": "add", "value": {
        "key": "code", "kind": "code", "locator": {"repo": "demo", "path": "code.cpp", "symbol": "server_time"},
        "quote": "server_time = 2", "observe": True,
    }}]}))
    rc, updated = run_cli("draft", "update", "coupon", "--brain-root", root, "--expected-sha", created["draft"]["sha256"], "--patch-file", patch)
    assert rc == 0
    _, full = run_cli("draft", "show", "coupon", "--full", "--brain-root", root)
    observation = full["draft"]["document"]["sources"][0]["observation"]
    assert observation["status"] == "current"
    assert observation["repo_root"] == str(repo)
    assert observation["head_sha"] == head
    assert observation["path_dirty"] is True
    assert observation["quote_status"] == "present"
    patch.write_text(json.dumps({"resume_summary": "다음 세션에 전달"}))
    rc, _ = run_cli("draft", "update", "coupon", "--brain-root", root, "--expected-sha", updated["draft"]["sha256"], "--patch-file", patch)
    assert rc == 0
    _, full = run_cli("draft", "show", "coupon", "--full", "--brain-root", root)
    assert full["draft"]["document"]["sources"][0]["observation"] == observation

    patch.write_text(json.dumps({"sources": [{"op": "replace", "value": {
        "key": "code", "kind": "code", "locator": {"repo": "another-repo", "path": "code.cpp"},
        "observe": True,
    }}]}))
    current_sha = full["draft"]["sha256"]
    rc, _ = run_cli("draft", "update", "coupon", "--brain-root", root, "--expected-sha", current_sha, "--patch-file", patch)
    assert rc == 0
    _, full = run_cli("draft", "show", "coupon", "--full", "--brain-root", root)
    assert full["draft"]["document"]["sources"][0]["observation"]["status"] == "unavailable"


@pytest.mark.parametrize("invalid_source", [
    {"key": "code", "kind": "code", "locator": {"repo": "demo", "path": "code.cpp"}, "quote": [], "observe": True},
    {"key": [], "kind": "code", "locator": {"repo": "demo", "path": "code.cpp"}, "observation": {"status": "current"}},
])
def test_invalid_source_is_a_structured_zero_write_error_before_observation(tmp_path, invalid_source):
    root = tmp_path / "brain"
    _, created = run_cli("draft", "create", "coupon", "--title", "쿠폰", "--scope", "만료", "--brain-root", root)
    path = root / created["draft"]["path"]
    before = path.read_bytes()
    patch = tmp_path / "patch.json"
    patch.write_text(json.dumps({"sources": [{"op": "add", "value": invalid_source}]}))
    rc, error = run_cli("draft", "update", "coupon", "--brain-root", root, "--expected-sha", created["draft"]["sha256"], "--patch-file", patch)
    assert rc == 1 and error["ok"] is False
    assert path.read_bytes() == before


@pytest.mark.parametrize("bad_patch", [
    {"items": [{"op": "replace", "value": {"key": "missing"}}]},
    {"sources": [{"op": "delete", "key": "spec"}]},
    {"items": [{"op": "add", "value": {"key": "expiry", "kind": "finding", "text": "중복", "source_keys": []}}]},
    {"items": [{"op": "add", "value": {"key": "other", "kind": "finding", "text": "잘못된 참조", "source_keys": ["missing"]}}]},
    {"updated": "2020-01-01T00:00:00+09:00"},
    {"items": [{"op": "add", "value": {"key": "other", "kind": [], "text": "오류", "source_keys": []}}]},
])
def test_invalid_patch_and_stale_sha_are_zero_write(tmp_path, bad_patch):
    root = tmp_path / "brain"
    _, created = run_cli("draft", "create", "coupon", "--title", "쿠폰", "--scope", "만료", "--source", "spec.md", "--brain-root", root)
    patch = tmp_path / "patch.json"
    patch.write_text(json.dumps({"items": [{"op": "add", "value": {
        "key": "expiry", "kind": "finding", "text": "서버 시각", "source_keys": ["source-1"],
    }}]}))
    rc, updated = run_cli("draft", "update", "coupon", "--brain-root", root, "--expected-sha", created["draft"]["sha256"], "--patch-file", patch)
    assert rc == 0
    path = root / "drafts/coupon.json"
    before = path.read_bytes()
    # 삭제 사례는 실제로 참조되는 source의 삭제다.
    if "sources" in bad_patch:
        bad_patch = {"sources": [{"op": "delete", "key": "source-1"}]}
    patch.write_text(json.dumps(bad_patch))
    rc, _ = run_cli("draft", "update", "coupon", "--brain-root", root, "--expected-sha", updated["draft"]["sha256"], "--patch-file", patch)
    assert rc == 1
    assert path.read_bytes() == before
    patch.write_text(json.dumps({"resume_summary": "다음"}))
    rc, error = run_cli("draft", "update", "coupon", "--brain-root", root, "--expected-sha", created["draft"]["sha256"], "--patch-file", patch)
    assert rc == 1 and error["error_code"] == "draft_stale_sha"
    assert path.read_bytes() == before


def test_v1_and_v2_coexist_but_same_topic_is_a_conflict(tmp_path):
    root = tmp_path / "brain"
    legacy = create_legacy(root, topic_id="legacy", title="기존", scope="범위")
    _, modern = run_cli("draft", "create", "modern", "--title", "신규", "--scope", "범위", "--brain-root", root)
    rc, listed = run_cli("draft", "list", "--brain-root", root)
    assert rc == 0
    assert [(d["topic_id"], d["format"]) for d in listed["drafts"]] == [("legacy", "markdown-v1"), ("modern", "json-v2")]
    for name in ("legacy", "modern"):
        rc, error = run_cli("draft", "create", name, "--title", "중복", "--scope", "범위", "--brain-root", root)
        assert rc == 1 and error["error_code"] == "draft_exists"
    rc, _ = run_cli("draft", "show", "legacy", "--item", "x", "--brain-root", root)
    assert rc == 1
    assert (root / legacy["path"]).read_text() == legacy["content"]
    document = json.loads((root / modern["draft"]["path"]).read_text())
    document["topic_id"] = "legacy"
    (root / "drafts/legacy.json").write_text(json.dumps(document))
    for action in ("show", "lint"):
        rc, _ = run_cli("draft", action, "legacy", "--brain-root", root)
        assert rc == 1
    rc, listed = run_cli("draft", "list", "--brain-root", root)
    assert rc == 0 and listed["partial"] is True
    assert [d["topic_id"] for d in listed["drafts"]] == ["modern"]
    assert {d["code"] for d in listed["diagnostics"]} == {"draft_topic_conflict"}


def test_metadata_order_is_by_topic_even_when_one_topic_is_a_prefix(tmp_path):
    root = tmp_path / "brain"
    create_legacy(root, topic_id="topic-child", title="하위", scope="범위")
    run_cli("draft", "create", "topic", "--title", "주제", "--scope", "범위", "--brain-root", root)
    rc, payload = run_cli("draft", "list", "--brain-root", root)
    assert rc == 0
    assert [d["topic_id"] for d in payload["drafts"]] == ["topic", "topic-child"]


def test_historical_session_material_is_not_reobserved_or_relabelled(tmp_path):
    root = tmp_path / "brain"
    _, created = run_cli("draft", "create", "coupon", "--title", "쿠폰", "--scope", "만료", "--brain-root", root)
    source = {"key": "decision", "kind": "session", "locator": {
        "session_id": "session-1", "position": "message-4", "occurred_at": "2026-08-01T12:00:00+09:00",
    }, "quote": "기존 팝업은 그대로 두자.", "context": "사용자 의도", "observation": {"status": "historical", "observed_at": "2026-08-01T12:00:00+09:00"}}
    patch = tmp_path / "patch.json"
    patch.write_text(json.dumps({"sources": [{"op": "add", "value": source}]}))
    rc, _ = run_cli("draft", "update", "coupon", "--brain-root", root, "--expected-sha", created["draft"]["sha256"], "--patch-file", patch)
    assert rc == 0
    _, full = run_cli("draft", "show", "coupon", "--full", "--brain-root", root)
    assert full["draft"]["document"]["sources"] == [source]
    assert "reviewed" not in json.dumps(full)


@pytest.mark.parametrize("legacy", [False, True])
def test_competing_writers_only_one_can_replace_the_same_sha(tmp_path, legacy):
    root = tmp_path / "brain"
    if legacy:
        original = create_legacy(root, topic_id="topic", title="주제", scope="범위")
    else:
        _, response = run_cli("draft", "create", "topic", "--title", "주제", "--scope", "범위", "--brain-root", root)
        original = response["draft"]
    program = '''
import json, sys
from pathlib import Path
from project_brain.draft import DraftError, update, update_patch
root, sha, mode, value = sys.argv[1:]
print("ready", flush=True)
sys.stdin.readline()
try:
    if mode == "legacy":
        result = update(Path(root), "topic", expected_sha=sha, content=value)
    else:
        result = update_patch(Path(root), "topic", expected_sha=sha, patch={"resume_summary":value})
    print(json.dumps({"ok":True,"sha":result["sha256"]}), flush=True)
except DraftError as exc:
    print(json.dumps({"ok":False,"code":exc.code}), flush=True)
'''
    processes = []
    try:
        for value in ("첫 번째 기록", "두 번째 기록"):
            content = original["content"].replace("## 확인된 이해\n", f"## 확인된 이해\n\n{value}\n") if legacy else value
            processes.append(subprocess.Popen(
                [sys.executable, "-c", program, str(root), original["sha256"], "legacy" if legacy else "v2", content],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))
        for process in processes:
            assert process.stdout.readline().strip() == "ready"
        for process in processes:
            process.stdin.write("\n")
            process.stdin.flush()
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout))
        assert sorted(result["ok"] for result in results) == [False, True]
        assert next(r for r in results if not r["ok"])["code"] == "draft_stale_sha"
        rc, shown = run_cli("draft", "show", "topic", "--brain-root", root)
        assert rc == 0
        assert shown["draft"]["sha256"] == next(r for r in results if r["ok"])["sha"]
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate()


def test_json_duplicates_and_format_option_mix_are_rejected_without_writing(tmp_path):
    root = tmp_path / "brain"
    _, created = run_cli("draft", "create", "coupon", "--title", "쿠폰", "--scope", "만료", "--brain-root", root)
    path = root / created["draft"]["path"]
    before = path.read_bytes()
    patch = tmp_path / "patch.json"
    patch.write_text('{"resume_summary":"first", "resume_summary":"second"}')
    rc, _ = run_cli("draft", "update", "coupon", "--brain-root", root, "--expected-sha", created["draft"]["sha256"], "--patch-file", patch)
    assert rc == 1
    rc, error = run_cli("draft", "update", "coupon", "--brain-root", root, "--expected-sha", created["draft"]["sha256"], "--content-file", patch)
    assert rc == 1 and error["error_code"] == "draft_format_mismatch"
    assert path.read_bytes() == before
    (root / "drafts/broken.json").write_text('{"version": 2, "version": 2}')
    rc, listed = run_cli("draft", "list", "--brain-root", root)
    assert rc == 0 and listed["partial"] is True
    assert [entry["topic_id"] for entry in listed["drafts"]] == ["coupon"]
    assert listed["diagnostics"][0]["code"] == "draft_json_invalid"
