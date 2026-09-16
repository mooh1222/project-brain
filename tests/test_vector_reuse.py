"""#57/#58: rebuild 결과와 임베더 입력을 통한 자동 재사용 계약."""
from unittest.mock import patch

import pytest

from project_brain.embedder import StubEmbedder
from project_brain.search_index import rebuild
from project_brain import tokenize_ko
from tests.test_search_index import build_store_dir, glossary_term


class RecordingEmbedder(StubEmbedder):
    def __init__(self):
        super().__init__()
        self.batches = []

    def embed_many(self, texts):
        self.batches.append(list(texts))
        return super().embed_many(texts)


@pytest.fixture(autouse=True)
def regex_tokenizer():
    with patch('project_brain.search_index.tokenize',
               side_effect=lambda text: tokenize_ko.tokenize(text, backend='regex')):
        yield


def test_unchanged_objects_and_raw_reuse_all_vectors(tmp_path):
    brain = build_store_dir(tmp_path / 'brain', [glossary_term('g.a', term='보상')])
    raw = brain / 'raw/sources/neutral/spec.md'
    raw.parent.mkdir(parents=True)
    raw.write_text('레이스 우승 보상을 지급한다.', encoding='utf-8')
    db = tmp_path / 'index.db'
    embedder = RecordingEmbedder()
    cold = rebuild(brain, db, embedder)
    embedder.batches.clear()
    warm = rebuild(brain, db, embedder)
    assert embedder.batches == []
    assert cold['vectors_computed'] == cold['vectors_total'] == 2
    assert cold['vector_reuse_fallback'] == 'no_previous_index'
    assert warm['vectors_reused'] == warm['vectors_total'] == 2
    assert warm['vectors_computed'] == 0
    assert warm['vector_reuse_fallback'] is None
    assert warm['elapsed_seconds'] >= 0


def snapshot(db):
    from project_brain.search_index import _connect
    conn = _connect(db)
    try:
        return {
            table: conn.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
            for table in ('documents', 'documents_fts', 'documents_vec', 'meta')
        }
    finally:
        conn.close()


@pytest.mark.parametrize('change', ['object', 'raw', 'status', 'id', 'delete'])
def test_changed_surface_only_and_cold_equivalence(tmp_path, change):
    from project_brain.store import BrainStore
    from project_brain.search_index import search_bm25, search_vector
    obj = glossary_term('g.a', term='보상')
    brain = build_store_dir(tmp_path / 'brain', [obj, glossary_term('g.b', term='우승')])
    raw = brain / 'raw/sources/neutral/spec.md'
    raw.parent.mkdir(parents=True)
    raw.write_text('레이스 보상 지급', encoding='utf-8')
    db = tmp_path / 'index.db'
    e = RecordingEmbedder()
    rebuild(brain, db, e)
    if change == 'object':
        obj['definition'] = '새로운 지급 방식'
        BrainStore.save_object(brain, obj)
    elif change == 'raw':
        raw.write_text('달라진 원문 보상', encoding='utf-8')
    elif change == 'status':
        BrainStore.save_object(brain, glossary_term('g.a', term='보상', status='candidate'))
    else:
        next(brain.rglob(obj['id'] + '.json')).unlink()
        if change == 'id':
            BrainStore.save_object(brain, glossary_term('g.z', term='보상'))
    e.batches.clear()
    result = rebuild(brain, db, e)
    changed = change in ('object', 'raw')
    assert result['vectors_computed'] == int(changed)
    assert result['vectors_reused'] == result['vectors_total'] - int(changed)
    assert len(e.batches) == int(changed)
    if changed:
        assert len(e.batches[0]) == 1
        assert ('새로운 지급 방식' if change == 'object' else '달라진 원문') in e.batches[0][0]
    cold = tmp_path / 'cold.db'
    rebuild(brain, cold, StubEmbedder())
    assert snapshot(db) == snapshot(cold)
    for query in ('보상', '우승'):
        assert search_bm25(db, query) == search_bm25(cold, query)
        assert search_vector(db, query, embedder=e) == search_vector(cold, query, embedder=e)


@pytest.mark.parametrize(('damage', 'reason'), [
    ('legacy', 'legacy_index'),
    ('missing_fingerprint', 'unreadable_previous_index'),
    ('missing_content_hash', 'unreadable_previous_index'),
    ('null_fingerprint', 'invalid_previous_index'),
    ('schema', 'legacy_index'),
    ('identity', 'embedding_identity_mismatch'),
    ('fts_only', 'fts_only_index'),
    ('missing_vector', 'invalid_previous_index'),
    ('orphan_vector', 'invalid_previous_index'),
    ('missing_fts', 'invalid_previous_index'),
    ('extra_meta', 'invalid_previous_index'),
    ('conflict', 'conflicting_surface_vectors'),
    ('corrupt', 'unreadable_previous_index'),
])
def test_ineligible_previous_index_falls_back_as_a_whole(tmp_path, damage, reason):
    from project_brain.search_index import _connect
    brain = build_store_dir(tmp_path / 'brain', [
        glossary_term('g.a', term='보상'), glossary_term('g.b', term='보상'),
    ])
    db = tmp_path / 'index.db'
    e = RecordingEmbedder()
    rebuild(brain, db, e if damage != 'fts_only' else None)
    if damage == 'corrupt':
        db.write_bytes(b'broken sqlite')
    else:
        conn = _connect(db)
        sql = {
            'legacy': 'ALTER TABLE meta DROP COLUMN embedding_identity',
            'missing_fingerprint': 'ALTER TABLE meta DROP COLUMN corpus_fingerprint',
            'missing_content_hash': 'ALTER TABLE documents DROP COLUMN content_hash',
            'null_fingerprint': 'UPDATE meta SET corpus_fingerprint=NULL',
            'schema': 'UPDATE meta SET schema_version=1',
            'identity': "UPDATE meta SET embedding_identity='different'",
            'missing_vector': 'DELETE FROM documents_vec WHERE rowid=1',
            'orphan_vector': 'INSERT INTO documents_vec(rowid,embedding) SELECT 99,embedding FROM documents_vec WHERE rowid=1',
            'missing_fts': 'DELETE FROM documents_fts WHERE rowid=1',
            'extra_meta': 'INSERT INTO meta SELECT * FROM meta',
        }
        if damage in sql:
            conn.execute(sql[damage])
        elif damage == 'conflict':
            from project_brain.search_index import _serialize
            conn.execute('UPDATE documents_vec SET embedding=? WHERE rowid=1',
                         (_serialize(e.embed('다른 벡터')),))
        conn.commit()
        conn.close()
    e.batches.clear()
    result = rebuild(brain, db, e)
    assert result['vector_reuse_fallback'] == reason
    assert result['vectors_computed'] == 2
    assert result['vectors_reused'] == 0
    assert len(e.batches) == 1 and len(e.batches[0]) == 2
    cold = tmp_path / 'cold.db'
    rebuild(brain, cold, e)
    assert snapshot(db) == snapshot(cold)


def test_read_error_falls_back_but_new_build_error_preserves_live(tmp_path):
    from project_brain import search_index
    brain = build_store_dir(tmp_path / 'brain', [glossary_term('g.a', term='보상')])
    db = tmp_path / 'index.db'
    e = RecordingEmbedder()
    rebuild(brain, db, e)
    connect = search_index._vec_connect

    def read_denied(path, **kwargs):
        if kwargs.get('uri'):
            raise PermissionError('read denied')
        return connect(path, **kwargs)

    with patch.object(search_index, '_vec_connect', side_effect=read_denied):
        result = rebuild(brain, db, e)
    assert result['vector_reuse_fallback'] == 'unreadable_previous_index'
    assert result['vectors_computed'] == 1
    before = db.read_bytes()
    for boundary in ('_validate_rebuilt_index', '_fsync_file', 'os.replace'):
        with patch('project_brain.search_index.' + boundary, side_effect=OSError('failure')):
            with pytest.raises(OSError):
                rebuild(brain, db, e)
        assert db.read_bytes() == before
        assert list(tmp_path.glob('.index.db.rebuild-*')) == []


def test_current_eligibility_and_interrupted_temp_are_not_reused(tmp_path):
    from tests.test_search_index import projection, review_record
    brain = build_store_dir(tmp_path / 'brain', [
        glossary_term('g.a', term='보상'),
        glossary_term('g.blank', term='', definition=''),
        review_record(),
        projection('p.stale', context_id='context.neutral', title='낡은 projection',
                   reuse_payload='낡은 본문'),
    ])
    db = tmp_path / 'index.db'
    e = RecordingEmbedder()
    cold = rebuild(brain, db, e)
    assert cold['indexed'] == 1
    assert cold['skipped'] == 3
    interrupted = tmp_path / '.index.db.rebuild-interrupted.tmp'
    interrupted.write_bytes(b'unfinished result')
    before = db.read_bytes()
    with patch('project_brain.search_index._fsync_file', side_effect=KeyboardInterrupt):
        with pytest.raises(KeyboardInterrupt):
            rebuild(brain, db, e)
    assert db.read_bytes() == before
    e.batches.clear()
    warm = rebuild(brain, db, e)
    assert warm['vectors_reused'] == 1
    assert warm['vectors_computed'] == 0
    assert e.batches == []
    assert interrupted.read_bytes() == b'unfinished result'


def test_fts_only_and_empty_corpus_report_zero_vectors(tmp_path):
    brain = build_store_dir(tmp_path / 'brain', [glossary_term('g.a', term='보상')])
    result = rebuild(brain, tmp_path / 'index.db')
    assert result['vector_reuse_fallback'] == 'embedding_disabled'
    assert result['vectors_total'] == result['vectors_computed'] == result['vectors_reused'] == 0
    empty = tmp_path / 'empty'
    empty.mkdir()
    e = RecordingEmbedder()
    db = tmp_path / 'empty.db'
    rebuild(empty, db, e)
    result = rebuild(empty, db, e)
    assert result['vector_reuse_fallback'] is None
    assert result['vectors_total'] == result['vectors_computed'] == result['vectors_reused'] == 0
    assert e.batches == []


@pytest.mark.parametrize('failure', ['error', 'short_result', 'extra_result'])
def test_miss_calculation_failure_preserves_previous_live_index(tmp_path, failure):
    from project_brain.store import BrainStore
    brain = build_store_dir(tmp_path / 'brain', [glossary_term('g.a', term='보상')])
    db = tmp_path / 'index.db'
    rebuild(brain, db, StubEmbedder())
    before = db.read_bytes()
    BrainStore.save_object(brain, glossary_term('g.a', term='변경된 보상'))

    class FailingEmbedder(StubEmbedder):
        def embed_many(self, texts):
            if failure == 'error':
                raise RuntimeError('model failure')
            return super().embed_many(texts[:0] if failure == 'short_result' else texts * 2)

    with pytest.raises(RuntimeError):
        rebuild(brain, db, FailingEmbedder())
    assert db.read_bytes() == before
    assert list(tmp_path.glob('.index.db.rebuild-*')) == []
