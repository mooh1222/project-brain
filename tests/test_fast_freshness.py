"""#95: public search freshness agrees with the independent full-fingerprint oracle."""
from unittest import mock

import pytest

from project_brain import search_index, tokenize_ko
from project_brain.search import _guard_index_freshness
from project_brain.store import BrainStore
from tests.test_search_index import build_store_dir, glossary_term


@pytest.fixture(autouse=True)
def regex_tokenizer(monkeypatch):
    monkeypatch.setattr(tokenize_ko, "_BACKEND_NAME", "regex")
    monkeypatch.setattr(tokenize_ko, "_KOREAN_SPLITTER", tokenize_ko._regex_splitter)


def test_unchanged_freshness_never_tokenizes_even_excluded_surfaces(tmp_path):
    brain, db = tmp_path / "brain", tmp_path / "index.db"
    empty = glossary_term("g.empty", term="!!!", definition="!!!")
    build_store_dir(brain, [glossary_term("g.one", term="알림"), empty])
    raw = brain / "raw/sources/neutral/empty.md"
    raw.parent.mkdir(parents=True)
    raw.write_text("!!!", encoding="utf-8")
    search_index.rebuild(brain, db, seeds=[])
    store = BrainStore.load(brain)
    with mock.patch.object(search_index, "tokenize", wraps=tokenize_ko.tokenize) as calls:
        _guard_index_freshness(db, store, brain)
    assert calls.call_count == 0


@pytest.mark.parametrize("legacy", [False, True], ids=["cached", "legacy"])
@pytest.mark.parametrize("change,stale,max_calls", [
    ("unchanged", False, 0), ("surface", True, 1), ("status", True, 0),
    ("add", True, 1), ("delete", True, 0), ("to_empty", True, 1),
    ("from_empty", True, 1), ("empty_to_empty", False, 1),
    ("empty_add", False, 1), ("empty_delete", False, 0),
    ("no_surface", False, 0), ("unindexed_field", False, 0),
    ("raw_add", True, 1), ("raw_edit", True, 1), ("raw_delete", True, 0),
    ("raw_to_empty", True, 1), ("raw_from_empty", True, 1),
    ("raw_empty_edit", False, 1), ("projection_stale", True, 0),
    ("projection_fresh", True, 1),
])
def test_freshness_equivalence(tmp_path, legacy, change, stale, max_calls):
    from tests.test_search_index import projection, review_record
    brain, db = tmp_path / "brain", tmp_path / "index.db"
    one = glossary_term("g.one", term="알림")
    empty = glossary_term("g.empty", term="!!!", definition="!!!")
    proj = projection("projection.one", context_id="context.neutral", title="브리핑",
                      reuse_payload="알림 재사용", source_object_ids=["g.one"],
                      source_objects=[one])
    if change == "projection_fresh":
        proj["source_content_hash"] = "old"
    build_store_dir(brain, [one, empty, proj, review_record()])
    raw = brain / "raw/sources/neutral/source.md"
    raw.parent.mkdir(parents=True)
    raw.write_text("원문 알림", encoding="utf-8")
    raw_empty = raw.with_name("empty.md")
    raw_empty.write_text("!!!", encoding="utf-8")
    search_index.rebuild(brain, db, seeds=[])
    if legacy:
        import sqlite3
        with sqlite3.connect(db) as conn:
            conn.execute("DROP TABLE freshness_meta")
            conn.execute("DROP TABLE freshness_surfaces")
    if change == "surface":
        one["definition"] = "새로운 정의"
    elif change == "status":
        one["status"] = "superseded"
    elif change == "add":
        BrainStore.save_object(brain, glossary_term("g.added", term="추가"))
    elif change == "delete":
        BrainStore.object_path(brain, one).unlink()
    elif change == "to_empty":
        one["term"] = one["definition"] = "???"
    elif change == "from_empty":
        empty["term"] = "새로운 표면"
    elif change == "empty_to_empty":
        empty["term"] = "???"
    elif change == "empty_add":
        BrainStore.save_object(brain, glossary_term("g.added", term="?", definition="?"))
    elif change == "empty_delete":
        BrainStore.object_path(brain, empty).unlink()
    elif change == "no_surface":
        obj = review_record()
        obj["title"] = "검수 변경"
        BrainStore.save_object(brain, obj)
    elif change == "unindexed_field":
        one["updated_at"] = "2026-07-01T00:00:00Z"
    elif change == "raw_add":
        raw.with_name("added.md").write_text("새 원문", encoding="utf-8")
    elif change == "raw_edit":
        raw.write_text("수정한 원문", encoding="utf-8")
    elif change == "raw_delete":
        raw.unlink()
    elif change == "raw_to_empty":
        raw.write_text("???", encoding="utf-8")
    elif change == "raw_from_empty":
        raw_empty.write_text("원문 생성", encoding="utf-8")
    elif change == "raw_empty_edit":
        raw_empty.write_text("???", encoding="utf-8")
    elif change == "projection_stale":
        proj["source_content_hash"] = "old"
    elif change == "projection_fresh":
        from project_brain.hash_utils import source_content_hash
        proj["source_content_hash"] = source_content_hash([one])
    # Persist only objects not deliberately removed. Projection is affected by
    # source-object edits as well as its own hash, as in the real store.
    if change != "delete":
        BrainStore.save_object(brain, one)
    if change != "empty_delete":
        BrainStore.save_object(brain, empty)
    BrainStore.save_object(brain, proj)
    store = BrainStore.load(brain)
    full_stale = (search_index.compute_corpus_fingerprint(store, brain)
                  != search_index.read_meta_fingerprint(db))
    assert full_stale == stale
    with mock.patch.object(search_index, "tokenize", wraps=tokenize_ko.tokenize) as calls:
        if stale:
            with pytest.raises(search_index.StaleIndexError, match="index rebuild"):
                _guard_index_freshness(db, store, brain)
        else:
            _guard_index_freshness(db, store, brain)
    if not legacy:
        assert calls.call_count <= max_calls


def test_scope_inference_reuses_exact_surfaces_from_index(tmp_path):
    from project_brain.search import eval_recall, infer_scope
    from project_brain.embedder import StubEmbedder
    from tests.test_ingest import context
    brain, db = tmp_path / "brain", tmp_path / "index.db"
    ctx = context()
    ctx.update(id="context.trap-spike", display_name="가시 함정", title="가시 함정 도메인", context_key="trap-spike")
    BrainStore.save_object(brain, ctx)
    search_index.rebuild(brain, db, embedder=StubEmbedder(), seeds=[])
    store = BrainStore.load(brain)
    expected = infer_scope("가시 함정 상태", store)
    with mock.patch("project_brain.search.tokenize", wraps=tokenize_ko.tokenize) as calls:
        result = eval_recall("가시 함정 상태", db_path=db, brain_root=brain,
                             store=store, embedder=StubEmbedder())
    assert result["scope"] == {"context_id": expected, "origin": "inferred"}
    assert all(call.args[0] not in {"가시 함정", "trap spike"} for call in calls.call_args_list)


def test_cli_eval_validates_one_snapshot_once(tmp_path, monkeypatch, capsys):
    import json
    from project_brain import cli
    brain, db = tmp_path / "brain", tmp_path / "index.db"
    one = glossary_term("g.one", term="알림")
    BrainStore.save_object(brain, one)
    search_index.rebuild(brain, db, seeds=[])
    config = {"brain_root": "brain", "db": "index.db", "scenarios": "eval.json"}
    (tmp_path / ".project-brain.json").write_text(json.dumps(config))
    scenarios = [{"id": f"s{i}", "query": "알림", "expect": {"top5_any": [one["id"]]}}
                 for i in range(3)]
    (tmp_path / "eval.json").write_text(json.dumps({"scenarios": scenarios}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROJECT_BRAIN_EMBEDDER", "stub")
    monkeypatch.setattr("sys.argv", ["project-brain", "eval"])
    with mock.patch.object(search_index, "compute_corpus_fingerprint",
                           wraps=search_index.compute_corpus_fingerprint) as fingerprints:
        assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)["summary"]["passed"] == 3
    assert fingerprints.call_count == 1


@pytest.mark.parametrize("damage", ["missing_table", "missing_row", "version", "fingerprint", "invalid_flag"])
def test_optional_cache_damage_falls_back_to_full_guard(tmp_path, damage):
    import sqlite3
    brain, db = tmp_path / "brain", tmp_path / "index.db"
    one = glossary_term("g.one", term="알림")
    BrainStore.save_object(brain, one)
    search_index.rebuild(brain, db, seeds=[])
    statements = {
        "missing_table": "DROP TABLE freshness_surfaces",
        "missing_row": "DELETE FROM freshness_surfaces",
        "version": "UPDATE freshness_meta SET version=0",
        "fingerprint": "UPDATE freshness_meta SET corpus_fingerprint='old'",
        "invalid_flag": "UPDATE freshness_surfaces SET has_tokens=2",
    }
    with sqlite3.connect(db) as conn:
        conn.execute(statements[damage])
    _guard_index_freshness(db, BrainStore.load(brain), brain)
    one["definition"] = "다른 내용"
    BrainStore.save_object(brain, one)
    with pytest.raises(search_index.StaleIndexError, match="index rebuild"):
        _guard_index_freshness(db, BrainStore.load(brain), brain)


def test_new_batch_and_ordinary_search_reject_changes(tmp_path):
    from project_brain.search import SearchSession, eval_recall
    from project_brain.embedder import StubEmbedder
    brain, db = tmp_path / "brain", tmp_path / "index.db"
    one = glossary_term("g.one", term="알림")
    BrainStore.save_object(brain, one)
    search_index.rebuild(brain, db, seeds=[])
    batch = SearchSession(brain_root=brain, db_path=db, embedder=StubEmbedder())
    assert batch("알림")["results"][0]["object_id"] == one["id"]
    raw = brain / "raw/sources/neutral/new.md"
    raw.parent.mkdir(parents=True)
    raw.write_text("새로운 원문", encoding="utf-8")
    # Reusing the same store must not cache raw freshness for ordinary search.
    with pytest.raises(search_index.StaleIndexError, match="index rebuild"):
        eval_recall("알림", brain_root=brain, db_path=db, store=batch.store,
                    embedder=StubEmbedder())
    fresh_batch = SearchSession(brain_root=brain, db_path=db, embedder=StubEmbedder())
    with pytest.raises(search_index.StaleIndexError, match="index rebuild"):
        fresh_batch("알림")


@pytest.mark.parametrize("query", ["가시 함정", "함정", "가시 폭탄 함정", "없는 기능", "!"])
@pytest.mark.parametrize("change", [False, True], ids=["same", "title_changed"])
def test_cached_scope_matches_original_inference(tmp_path, query, change):
    from project_brain.search import infer_scope
    from tests.test_ingest import context
    brain, db = tmp_path / "brain", tmp_path / "index.db"
    contexts = []
    for key, name in [("trap", "함정"), ("trap-spike", "가시 함정"), ("trap-bomb", "폭탄 함정")]:
        ctx = context()
        ctx.update(id=f"context.{key}", context_key=key, title=f"{name} 도메인", display_name=name)
        contexts.append(ctx)
    build_store_dir(brain, contexts)
    search_index.rebuild(brain, db, seeds=[])
    if change:
        contexts[1]["title"] = "가시 폭탄 도메인"
        BrainStore.save_object(brain, contexts[1])
    store = BrainStore.load(brain)
    assert infer_scope(query, store, scope_cache=search_index.read_scope_cache(db)) == infer_scope(query, store)


def test_cli_search_stale_reports_rebuild(tmp_path, monkeypatch, capsys):
    from project_brain import cli
    brain, db = tmp_path / "brain", tmp_path / "index.db"
    one = glossary_term("g.one", term="알림")
    BrainStore.save_object(brain, one)
    search_index.rebuild(brain, db, seeds=[])
    one["definition"] = "변경"
    BrainStore.save_object(brain, one)
    monkeypatch.setenv("PROJECT_BRAIN_EMBEDDER", "stub")
    monkeypatch.setattr("sys.argv", ["project-brain", "search", "알림", "--brain-root", str(brain), "--db", str(db)])
    assert cli.main() == 1
    output = capsys.readouterr()
    assert "index rebuild" in output.out + output.err
