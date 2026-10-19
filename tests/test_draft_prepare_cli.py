import hashlib
import json
import subprocess

import pytest

from tests.test_draft_v2_cli import run_cli


def make_materials_fixture(tmp_path, monkeypatch):
    repo = tmp_path / "project"
    repo.mkdir()
    for args in (("init",), ("config", "user.email", "test@example.invalid"), ("config", "user.name", "Test")):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / ".project-brain.json").write_text(json.dumps({"repo": "demo", "brain_root": "brain"}))
    (repo / "Expiry.cpp").write_text("int expiry = 1;\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / "Expiry.cpp").write_text("int expiry = 2;\n")
    root = repo / "brain"
    raw = root / "raw/sources/coupon/spec.md"
    raw.parent.mkdir(parents=True)
    raw.write_bytes("# 기획\r\n\r\n## 만료\r\n서버 시각 기준이다.\r\n\r\n## 표시\r\n다른 절이다.\r\n".encode())
    monkeypatch.chdir(repo)
    rc, created = run_cli("draft", "create", "coupon", "--title", "쿠폰", "--scope", "만료")
    assert rc == 0
    patch = tmp_path / "patch.json"
    patch.write_text(json.dumps({
        "sources": [
            {"op": "add", "value": {"key": "code", "kind": "code", "locator": {"repo": "demo", "path": "Expiry.cpp"}, "quote": "expiry = 2", "observe": True}},
            {"op": "add", "value": {"key": "spec", "kind": "document", "locator": {"path": "raw/sources/coupon/spec.md", "section": "만료"}}},
        ],
        "items": [
            {"op": "add", "value": {"key": "expiry", "kind": "finding", "text": "서버 시각으로 만료 판정", "source_keys": ["code", "spec"], "limits": "표시 기준 미확인"}},
            {"op": "add", "value": {"key": "open", "kind": "question", "text": "표시는 어떤 기준인가?", "source_keys": []}},
        ],
    }))
    rc, changed = run_cli("draft", "update", "coupon", "--expected-sha", created["draft"]["sha256"], "--patch-file", patch)
    assert rc == 0
    return repo, root, head, changed["draft"]["sha256"]


def test_prepare_exports_selected_materials_and_byte_states_without_mutation(tmp_path, monkeypatch):
    repo, root, head, sha = make_materials_fixture(tmp_path, monkeypatch)
    before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    out = tmp_path / "packet"
    rc, response = run_cli("draft", "prepare", "coupon", "--item", "expiry", "--item", "open",
                           "--repo-root", repo, "--target-revision", head, "--out", out)
    assert rc == 0
    packet = json.loads((out / "materials.json").read_text())
    assert packet["draft"]["sha256"] == sha
    assert packet["target"]["revision"] == head
    assert packet["target"]["repo"] == "demo"
    assert [item["key"] for item in packet["items"]] == ["expiry"]
    assert [item["key"] for item in packet["unresolved_items"]] == ["open"]
    assert packet["items"][0]["limits"] == "표시 기준 미확인"
    code = next(source for source in packet["sources"] if source["key"] == "code")
    assert code["file_state"] == "available"
    assert code["file_hash_changed"] is True
    assert code["quote_status"] == "absent"
    assert code["excerpts"][0]["basis"] == "stored_quote"
    doc = next(source for source in packet["sources"] if source["key"] == "spec")
    excerpt = doc["excerpts"][0]
    assert excerpt["text"] == "## 만료\r\n서버 시각 기준이다.\r\n\r\n"
    assert excerpt["sha256"] == hashlib.sha256(excerpt["text"].encode()).hexdigest()
    assert "다른 절" not in excerpt["text"]
    assert "reviewed" not in json.dumps(packet)
    assert response["partial"] is True
    assert before == {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    second = tmp_path / "second-packet"
    rc, repeated = run_cli("draft", "prepare", "coupon", "--item", "expiry", "--item", "open",
                           "--repo-root", repo, "--target-revision", head, "--out", second)
    assert rc == 0
    assert repeated["sha256"] == response["sha256"]
    assert (second / "materials.json").read_bytes() == (out / "materials.json").read_bytes()


@pytest.mark.parametrize("invalid", ["unknown-key", "bad-revision", "bad-draft", "inside-brain", "nonempty", "symlink"])
def test_invalid_prepare_inputs_and_outputs_do_not_write(tmp_path, monkeypatch, invalid):
    repo, root, head, _ = make_materials_fixture(tmp_path, monkeypatch)
    out = tmp_path / "output"
    key = "missing" if invalid == "unknown-key" else "expiry"
    revision = "missing-commit" if invalid == "bad-revision" else head
    if invalid == "bad-draft":
        path = root / "drafts/coupon.json"
        document = json.loads(path.read_text())
        document["items"][0]["text"] = "\ud800"
        path.write_text(json.dumps(document))
    if invalid == "inside-brain":
        out = root / "packet"
    elif invalid == "nonempty":
        out.mkdir()
        (out / "materials.json").write_bytes(b"existing")
    elif invalid == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        out.symlink_to(target, target_is_directory=True)
    before = {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    rc, error = run_cli("draft", "prepare", "coupon", "--item", key,
                       "--repo-root", repo, "--target-revision", revision, "--out", out)

    assert rc == 1 and error["ok"] is False
    assert before == {str(p): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    if invalid == "nonempty":
        assert (out / "materials.json").read_bytes() == b"existing"
    elif invalid == "symlink":
        assert list(target.iterdir()) == []
    else:
        assert not out.exists()


@pytest.mark.parametrize("body,reason", [
    ("# 기획\n## 만료\n첫째\n## 만료\n둘째\n", "section_ambiguous"),
    ("# 기획\n## 다른 절\n없음\n", "section_missing"),
    ("## 만료\n" + "가" * 30000, "excerpt_too_large"),
    ("## 만료\n본문\n\n표시\n----\n다른 절\n", "section_unsupported"),
    ("## 만료\n첫째\n\n만료\n----\n둘째\n", "section_unsupported"),
])
def test_ambiguous_missing_or_large_section_is_diagnosed_without_fallback(tmp_path, monkeypatch, body, reason):
    repo, root, head, _ = make_materials_fixture(tmp_path, monkeypatch)
    (root / "raw/sources/coupon/spec.md").write_text(body)
    out = tmp_path / "packet"
    rc, _ = run_cli("draft", "prepare", "coupon", "--item", "expiry",
                    "--repo-root", repo, "--target-revision", head, "--out", out)
    assert rc == 0
    packet = json.loads((out / "materials.json").read_text())
    source = next(s for s in packet["sources"] if s["key"] == "spec")
    assert source["excerpts"] == []
    assert any(reason in d["detail"] for d in packet["diagnostics"])
    assert packet["partial"] is True


def test_case_alias_of_brain_cannot_be_used_as_output(tmp_path, monkeypatch):
    repo, root, head, _ = make_materials_fixture(tmp_path, monkeypatch)
    alias = root.with_name("BRAIN")
    if not alias.exists():
        pytest.skip("case-sensitive filesystem has no case alias")
    out = alias / "packet"
    rc, error = run_cli("draft", "prepare", "coupon", "--item", "expiry",
                       "--repo-root", repo, "--target-revision", head, "--out", out)
    assert rc == 1 and error["ok"] is False
    assert not (root / "packet").exists()


@pytest.mark.parametrize("quote,expected", [("서버", "present"), ("없는 원문", "absent"), ("##", "multiple")])
def test_document_saved_quote_state_is_checked_against_current_raw(tmp_path, monkeypatch, quote, expected):
    repo, root, head, sha = make_materials_fixture(tmp_path, monkeypatch)
    patch = tmp_path / "quote.json"
    patch.write_text(json.dumps({"sources": [{"op": "replace", "value": {
        "key": "spec", "kind": "document", "locator": {"path": "raw/sources/coupon/spec.md", "section": "만료"}, "quote": quote,
    }}]}))
    rc, _ = run_cli("draft", "update", "coupon", "--expected-sha", sha, "--patch-file", patch)
    assert rc == 0
    out = tmp_path / "packet"
    rc, _ = run_cli("draft", "prepare", "coupon", "--item", "expiry",
                    "--repo-root", repo, "--target-revision", head, "--out", out)
    assert rc == 0
    packet = json.loads((out / "materials.json").read_text())
    source = next(s for s in packet["sources"] if s["key"] == "spec")
    assert source["quote_status"] == expected
    if expected != "present":
        assert any(d.get("source_key") == "spec" and d["code"] == f"quote_{expected}" for d in packet["diagnostics"])


def test_item_without_evidence_is_explicitly_unresolved_material(tmp_path, monkeypatch):
    repo, root, head, sha = make_materials_fixture(tmp_path, monkeypatch)
    patch = tmp_path / "no-evidence.json"
    patch.write_text(json.dumps({"items": [{"op": "add", "value": {
        "key": "guess", "kind": "finding", "text": "근거 미확보", "source_keys": [],
    }}]}))
    rc, _ = run_cli("draft", "update", "coupon", "--expected-sha", sha, "--patch-file", patch)
    assert rc == 0
    out = tmp_path / "packet"
    rc, response = run_cli("draft", "prepare", "coupon", "--item", "guess",
                           "--repo-root", repo, "--target-revision", head, "--out", out)
    assert rc == 0 and response["partial"] is True
    assert response["diagnostics"][0]["code"] == "evidence_missing"


def test_overlapping_quote_occurrences_are_multiple_and_only_stored_quote_is_exported(tmp_path, monkeypatch):
    repo, root, _, sha = make_materials_fixture(tmp_path, monkeypatch)
    (repo / "Expiry.cpp").write_text("aaa")
    subprocess.run(["git", "add", "Expiry.cpp"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "overlapping quote"], cwd=repo, check=True, capture_output=True)
    patch = tmp_path / "overlap.json"
    patch.write_text(json.dumps({"sources": [{"op": "replace", "value": {
        "key": "code", "kind": "code", "locator": {"repo": "demo", "path": "Expiry.cpp"}, "quote": "aa", "observe": True,
    }}]}))
    rc, _ = run_cli("draft", "update", "coupon", "--expected-sha", sha, "--patch-file", patch)
    assert rc == 0
    out = tmp_path / "packet"
    rc, _ = run_cli("draft", "prepare", "coupon", "--item", "expiry",
                    "--repo-root", repo, "--target-revision", "HEAD", "--out", out)
    assert rc == 0
    packet = json.loads((out / "materials.json").read_text())
    source = next(s for s in packet["sources"] if s["key"] == "code")
    assert source["observation"]["quote_status"] == source["quote_status"] == "multiple"
    assert source["excerpts"][0]["text"] == "aa"
    assert len(source["excerpts"]) == 1


def test_raw_symlink_is_not_read_and_v1_prepare_is_rejected(tmp_path, monkeypatch):
    from project_brain.draft import create as create_legacy

    repo, root, head, _ = make_materials_fixture(tmp_path, monkeypatch)
    raw = root / "raw/sources/coupon/spec.md"
    raw.unlink()
    outside = tmp_path / "private.md"
    outside.write_text("## 만료\nOUTSIDE_SECRET\n")
    raw.symlink_to(outside)
    out = tmp_path / "packet"
    rc, _ = run_cli("draft", "prepare", "coupon", "--item", "expiry",
                    "--repo-root", repo, "--target-revision", head, "--out", out)
    assert rc == 0
    text = (out / "materials.json").read_text()
    assert "OUTSIDE_SECRET" not in text
    packet = json.loads(text)
    assert next(s for s in packet["sources"] if s["key"] == "spec")["file_state"] == "unavailable"
    create_legacy(root, topic_id="legacy", title="기존", scope="범위")
    out = tmp_path / "legacy-packet"
    rc, error = run_cli("draft", "prepare", "legacy", "--item", "x",
                       "--repo-root", repo, "--target-revision", head, "--out", out)
    assert rc == 1 and error["error_code"] == "draft_format_mismatch"
    assert not out.exists()


def test_materials_use_existing_coverage_mutation_and_receipt_for_changes_and_retry(tmp_path, monkeypatch):
    from project_brain.ingest import IngestError, ingest
    from project_brain.store import BrainStore
    from project_brain.transaction_receipt import receipt_from_result
    from tests.coverage_helpers import direct_coverage
    from tests.test_ingest import candidate_mapping, context

    repo, root, head, _ = make_materials_fixture(tmp_path, monkeypatch)
    out = tmp_path / "packet"
    rc, _ = run_cli("draft", "prepare", "coupon", "--item", "expiry",
                    "--repo-root", repo, "--target-revision", head, "--out", out)
    assert rc == 0
    packet = json.loads((out / "materials.json").read_text())
    # 의미 검토·객체 경계 선택은 호출자가 한다. prepare는 객체를 만들지 않는다.
    mapping = candidate_mapping("mapping.neutral.expiry", mapping_key="expiry", glossary_term_ids=[])
    mapping["meaning"] = packet["items"][0]["text"]
    objects = [context(), mapping]
    bad = {"id": "bad", "kind": "GlossaryTerm"}
    with pytest.raises(IngestError):
        ingest(root, [*objects, bad], engine_sha=head, coverage=direct_coverage(*objects, bad))
    assert BrainStore.load(root).all() == []
    committed = ingest(root, objects, engine_sha=head, coverage=direct_coverage(*objects))
    assert committed.outcome == "committed"
    receipt = receipt_from_result(committed, committed=True)
    assert {row["id"] for row in receipt.changed_objects} == {"context.neutral", "mapping.neutral.expiry"}
    retried = ingest(root, objects, engine_sha=head, coverage=direct_coverage(*objects))
    assert retried.outcome == "no_changes"
    changed = dict(mapping, meaning="같은 ID의 변경된 의미")
    updated = ingest(root, [changed], engine_sha=head, coverage=direct_coverage(changed))
    assert updated.outcome == "committed"
    assert BrainStore.load(root).get(mapping["id"])["meaning"] == "같은 ID의 변경된 의미"
    assert (out / "materials.json").read_text() == json.dumps(packet, ensure_ascii=False, indent=2) + "\n"
