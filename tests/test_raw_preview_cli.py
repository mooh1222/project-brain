"""공개 raw preview CLI: regex 주입 합성 원문만 사용한다."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).parents[1]


def run_preview(*args, cwd=None, forbid_side_effects=False, tokenizer_failure=False):
    return run_cli("raw", "chunk-preview", *args, cwd=cwd,
                   forbid_side_effects=forbid_side_effects,
                   tokenizer_failure=tokenizer_failure)


def run_cli(*args, cwd=None, forbid_side_effects=False, tokenizer_failure=False):
    script = """
import sys
from project_brain import tokenize_ko
tokenize_ko._BACKEND_NAME = 'regex'
tokenize_ko._KOREAN_SPLITTER = tokenize_ko._regex_splitter
"""
    if tokenizer_failure:
        script += """
def unavailable(text):
    raise RuntimeError('tokenizer unavailable')
tokenize_ko._KOREAN_SPLITTER = unavailable
"""
    if forbid_side_effects:
        script += """
import importlib.abc
class ForbiddenImport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'sentence_transformers'} or fullname == 'project_brain.embedder':
            raise AssertionError('preview imported embedder: ' + fullname)
sys.meta_path.insert(0, ForbiddenImport())
def read_only(event, args):
    if event == 'sqlite3.connect':
        raise AssertionError('preview opened a database')
    if event == 'open':
        path, mode, flags = args
        if (isinstance(mode, str) and any(c in mode for c in 'wa+')) or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError('preview opened for writing: ' + str(path))
    if event in {'os.mkdir', 'os.remove', 'os.rename', 'os.rmdir'}:
        raise AssertionError('preview mutated filesystem: ' + event)
import os
sys.addaudithook(read_only)
"""
    script += """
from project_brain.cli import main
raise SystemExit(main())
"""
    return subprocess.run(
        [sys.executable, "-c", script, *map(str, args)],
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"),
             "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True,
    )


def write_source(brain, name, text):
    path = brain / "raw" / "sources" / "demo" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_preview_reports_known_counts_including_zero_sources(tmp_path):
    brain = tmp_path / "brain"
    write_source(brain, "normal.md", "# One\nalpha\n## Two\nbeta\n")
    write_source(brain, "empty.md", "\n  \n")
    write_source(brain, "symbols.md", "!!!")
    write_source(brain, "long.md", "가" * 1100)

    result = run_preview("--brain-root", brain, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "ok": True,
        "brain_root": str(brain),
        "tokenizer": "regex@4",
        "raw_chunks": 5,
        "sources": [
            {"path": "raw/sources/demo/empty.md", "context_id": "context.demo", "raw_chunks": 0},
            {"path": "raw/sources/demo/long.md", "context_id": "context.demo", "raw_chunks": 3},
            {"path": "raw/sources/demo/normal.md", "context_id": "context.demo", "raw_chunks": 2},
            {"path": "raw/sources/demo/symbols.md", "context_id": "context.demo", "raw_chunks": 0},
        ],
    }


def test_preview_explicit_files_are_a_deduplicated_subset_and_config_is_resolved(tmp_path):
    brain = tmp_path / "configured-brain"
    write_source(brain, "a.md", "alpha")
    second = write_source(brain, "b.md", "# One\nalpha\n# Two\nbeta")
    write_source(brain, "ignored.txt", "gamma")
    write_source(brain, "nested/deeper.md", "delta")
    (brain / "raw" / "sources" / "root.md").write_text("outside context")
    (tmp_path / ".project-brain.json").write_text(json.dumps({"brain_root": "configured-brain"}))
    cwd = tmp_path / "subdir"
    cwd.mkdir()

    result = run_preview("--json", second, "../configured-brain/raw/sources/demo/b.md", cwd=cwd)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["raw_chunks"] == 2
    assert payload["sources"] == [
        {"path": "raw/sources/demo/b.md", "context_id": "context.demo", "raw_chunks": 2},
    ]
    default = run_preview("--json", cwd=cwd)
    assert default.returncode == 0, default.stderr
    assert [s["path"] for s in json.loads(default.stdout)["sources"]] == [
        "raw/sources/demo/a.md", "raw/sources/demo/b.md",
    ]
    override = tmp_path / "override"
    write_source(override, "only.md", "gamma")
    explicit = run_preview("--json", "--brain-root", override, cwd=cwd)
    assert explicit.returncode == 0, explicit.stderr
    assert json.loads(explicit.stdout)["raw_chunks"] == 1


@pytest.mark.parametrize("name", ["missing.md", "outside.md", "note.txt", "nested/deeper.md", "."])
def test_preview_rejects_paths_that_rebuild_would_not_discover(tmp_path, name):
    brain = tmp_path / "brain"
    write_source(brain, "normal.md", "alpha")
    write_source(brain, "note.txt", "beta")
    write_source(brain, "nested/deeper.md", "gamma")
    (tmp_path / "outside.md").write_text("outside")
    supplied = tmp_path / "outside.md" if name == "outside.md" else brain / "raw/sources/demo" / name

    result = run_preview("--brain-root", brain, "--json", supplied)

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "error" in payload
    assert "sources" not in payload  # 부분 성공 보고 없음


@pytest.mark.parametrize("existing_db", [False, True])
def test_public_preview_never_imports_embedder_or_writes_or_opens_db(tmp_path, existing_db):
    brain = tmp_path / "brain"
    write_source(brain, "normal.md", "alpha")
    if existing_db:
        db = brain / ".brain-local" / "index.db"
        db.parent.mkdir()
        db.write_bytes(b"not even a valid sqlite database")

    def snapshot():
        return {
            p.relative_to(brain).as_posix():
                (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in [brain, *brain.rglob("*")]
        }

    before = snapshot()
    result = run_preview("--json", "--brain-root", brain, forbid_side_effects=True)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["raw_chunks"] == 1
    assert snapshot() == before


@pytest.mark.parametrize("texts, expected", [
    (["# One\nalpha\n## Two\nbeta"], 2),
    (["\n  \n"], 0),
    (["!!!"], 0),
    (["가" * 1100], 3),
    (["# One\nalpha\n## Two\nbeta", "", "!!!", "가" * 1100], 5),
])
def test_preview_matches_actual_stub_rebuild_raw_rows(tmp_path, texts, expected):
    brain = tmp_path / "brain"
    for number, text in enumerate(texts):
        write_source(brain, f"source{number}.md", text)
    preview = run_preview("--json", "--brain-root", brain)
    assert preview.returncode == 0, preview.stderr
    rebuilt = run_cli("index", "rebuild", "--brain-root", brain,
                      "--db", tmp_path / "index.db", "--stub-embedder")
    assert rebuilt.returncode == 0, rebuilt.stdout + rebuilt.stderr
    assert json.loads(preview.stdout)["raw_chunks"] == expected
    assert json.loads(rebuilt.stdout)["raw_chunks"] == expected


def test_preview_missing_sources_is_empty_but_missing_brain_fails(tmp_path):
    brain = tmp_path / "brain"
    brain.mkdir()
    result = run_preview("--json", "--brain-root", brain)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["sources"] == []
    assert json.loads(result.stdout)["raw_chunks"] == 0

    missing = run_preview("--json", "--brain-root", tmp_path / "absent")
    assert missing.returncode == 1
    assert json.loads(missing.stdout)["ok"] is False


def test_preview_read_failure_is_json_without_partial_counts(tmp_path):
    brain = tmp_path / "brain"
    write_source(brain, "a-normal.md", "alpha")
    bad = write_source(brain, "z-invalid.md", "")
    bad.write_bytes(b"\xff")
    result = run_preview("--json", "--brain-root", brain)
    assert result.returncode == 1
    assert json.loads(result.stdout)["ok"] is False
    assert "sources" not in json.loads(result.stdout)
    assert "Traceback" not in result.stderr


def test_preview_config_and_argument_errors_keep_cli_exit_two(tmp_path):
    missing = run_preview("--json", cwd=tmp_path)
    assert missing.returncode == 2
    assert json.loads(missing.stderr)["ok"] is False
    malformed = run_cli("raw", "not-a-command")
    assert malformed.returncode == 2


def test_preview_text_output_reports_zero_sources_and_total(tmp_path):
    brain = tmp_path / "brain"
    write_source(brain, "empty.md", "")
    result = run_preview("--brain-root", brain)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "0\traw/sources/demo/empty.md\nraw_chunks: 0 (regex@4)\n"


def test_preview_tokenizer_failure_is_json_without_partial_counts(tmp_path):
    brain = tmp_path / "brain"
    write_source(brain, "normal.md", "한글")
    result = run_preview("--json", "--brain-root", brain, tokenizer_failure=True)
    assert result.returncode == 1
    assert json.loads(result.stdout) == {"ok": False, "error": "tokenizer unavailable"}
    assert "Traceback" not in result.stderr
