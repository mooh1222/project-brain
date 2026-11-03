"""#93: CLI에서 관찰하는 checkout 간 exact surface 벡터 재사용."""
import io
import json
import subprocess
import sys
from types import SimpleNamespace
from contextlib import redirect_stdout
from unittest.mock import patch

import pytest

from project_brain import cli, tokenize_ko
from project_brain.store import BrainStore
from tests.test_search_index import build_store_dir, glossary_term


@pytest.fixture(autouse=True)
def regex_tokenizer():
    with patch('project_brain.search_index.tokenize',
               side_effect=lambda text: tokenize_ko.tokenize(text, backend='regex')):
        yield


def run_cli(*args):
    out = io.StringIO()
    with patch('sys.argv', ['project-brain', *map(str, args)]), redirect_stdout(out):
        rc = cli.main()
    payload = json.loads(out.getvalue())
    assert rc == 0, payload
    assert payload['ok'], payload
    return payload


def rebuild(brain, db, *args):
    return run_cli('index', 'rebuild', '--brain-root', brain, '--db', db,
                   '--stub-embedder', *args)


def corpus(path):
    brain = build_store_dir(path, [
        glossary_term('g.a', term='보상'), glossary_term('g.b', term='우승'),
    ])
    raw = brain / 'raw/sources/neutral/spec.md'
    raw.parent.mkdir(parents=True)
    raw.write_text('레이스 우승 보상을 지급한다.', encoding='utf-8')
    return brain


def test_seed_reuses_all_objects_and_raw_and_preserves_search(tmp_path):
    brain = corpus(tmp_path / 'brain')
    seed = tmp_path / 'seed #1.db'
    cold = rebuild(brain, seed)
    before = seed.read_bytes()
    target = tmp_path / 'new.db'
    result = rebuild(brain, target, '--seed', seed)
    assert result['vectors_total'] == result['vectors_seeded'] == 3
    assert result['vectors_computed'] == result['vectors_reused'] == 0
    assert result['seed_paths'] == [str(seed)]
    assert result['seed_fallbacks'] == []
    assert seed.read_bytes() == before
    assert cold['vectors_computed'] == 3
    args = ['search', '우승 보상', '--brain-root', brain, '--stub-embedder']
    assert run_cli(*args, '--db', seed) == run_cli(*args, '--db', target)


def test_changed_object_computes_only_one_vector(tmp_path):
    brain = corpus(tmp_path / 'brain')
    seed = tmp_path / 'seed.db'
    rebuild(brain, seed)
    BrainStore.save_object(brain, glossary_term('g.a', term='새 지급 보상'))
    result = rebuild(brain, tmp_path / 'new.db', '--seed', seed)
    assert result['vectors_seeded'] == 2
    assert result['vectors_computed'] == 1
    assert result['vectors_reused'] == 0


@pytest.mark.parametrize(('field', 'value', 'reason'), [
    ('embedding_identity', 'different', 'embedding_identity_mismatch'),
    ('tokenizer', 'other@1', 'tokenizer_mismatch'),
    ('extractor_version', -1, 'extractor_version_mismatch'),
    ('schema_version', -1, 'legacy_index'),
])
def test_incompatible_seed_falls_back(tmp_path, field, value, reason):
    import sqlite3
    brain = corpus(tmp_path / 'brain')
    seed = tmp_path / 'seed.db'
    rebuild(brain, seed)
    with sqlite3.connect(seed) as conn:
        conn.execute(f'UPDATE meta SET {field}=?', (value,))
    result = rebuild(brain, tmp_path / 'new.db', '--seed', seed)
    assert result['vectors_seeded'] == 0
    assert result['vectors_computed'] == 3
    assert result['seed_fallbacks'] == [{'path': str(seed), 'reason': reason}]


def test_bad_seed_is_skipped_and_next_seed_can_supply_vectors(tmp_path):
    brain = corpus(tmp_path / 'brain')
    broken = tmp_path / 'broken.db'
    broken.write_bytes(b'broken sqlite')
    good = tmp_path / 'good.db'
    rebuild(brain, good)
    result = rebuild(brain, tmp_path / 'new.db', '--seed', broken,
                     '--seed', good, '--seed', good)
    assert result['vectors_seeded'] == 3
    assert result['vectors_computed'] == 0
    assert result['seed_paths'] == [str(good)]
    assert result['seed_fallbacks'] == [
        {'path': str(broken), 'reason': 'unreadable_previous_index'},
    ]


def test_locked_seed_falls_back_without_touching_source(tmp_path):
    import sqlite3
    brain = corpus(tmp_path / 'brain')
    seed = tmp_path / 'seed.db'
    rebuild(brain, seed)
    before = seed.read_bytes()
    conn = sqlite3.connect(seed)
    try:
        conn.execute('BEGIN EXCLUSIVE')
        result = rebuild(brain, tmp_path / 'new.db', '--seed', seed)
    finally:
        conn.rollback()
        conn.close()
    assert result['vectors_computed'] == 3
    assert result['vectors_seeded'] == 0
    assert result['seed_fallbacks'] == [
        {'path': str(seed), 'reason': 'unreadable_previous_index'},
    ]
    assert seed.read_bytes() == before


def test_corrupt_seed_alone_does_not_fail_rebuild(tmp_path):
    brain = corpus(tmp_path / 'brain')
    seed = tmp_path / 'broken.db'
    seed.write_bytes(b'broken sqlite')
    result = rebuild(brain, tmp_path / 'new.db', '--seed', seed)
    assert result['vectors_computed'] == 3
    assert result['vectors_seeded'] == 0
    assert result['seed_fallbacks'] == [
        {'path': str(seed), 'reason': 'unreadable_previous_index'},
    ]


def test_unresolvable_seed_path_does_not_fail_rebuild(tmp_path):
    brain = corpus(tmp_path / 'brain')
    seed = tmp_path / 'loop.db'
    seed.symlink_to(seed)
    result = rebuild(brain, tmp_path / 'new.db', '--seed', seed)
    assert result['vectors_computed'] == 3
    assert len(result['seed_fallbacks']) == 1
    assert result['seed_fallbacks'][0]['path'] == str(seed)
    assert result['seed_fallbacks'][0]['reason'] in (
        'no_previous_index', 'unreadable_previous_index',
    )


def test_previous_index_takes_priority_and_seed_supplies_only_missing_surface(tmp_path):
    brain = corpus(tmp_path / 'brain')
    target = tmp_path / 'index.db'
    rebuild(brain, target)
    BrainStore.save_object(brain, glossary_term('g.a', term='새 지급 보상'))
    seed = tmp_path / 'seed.db'
    rebuild(brain, seed)
    result = rebuild(brain, target, '--seed', seed)
    assert result['vectors_reused'] == 2
    assert result['vectors_seeded'] == 1
    assert result['vectors_computed'] == 0
    warm = rebuild(brain, target, '--seed', seed)
    assert warm['vectors_reused'] == 3
    assert warm['vectors_seeded'] == 0
    assert warm['seed_paths'] == []


def test_config_seeds_are_relative_and_explicit_cli_replaces_them(tmp_path, monkeypatch):
    brain = corpus(tmp_path / 'brain')
    seed = tmp_path / 'configured.db'
    rebuild(brain, seed)
    (tmp_path / '.project-brain.json').write_text(json.dumps({
        'index_seeds': ['configured.db'],
    }))
    monkeypatch.chdir(tmp_path)
    configured = rebuild(brain, tmp_path / 'configured-target.db')
    assert configured['vectors_seeded'] == 3
    assert configured['seed_paths'] == [str(seed)]
    missing = tmp_path / 'missing.db'
    explicit = rebuild(brain, tmp_path / 'explicit-target.db', '--seed', missing)
    assert explicit['vectors_seeded'] == 0
    assert explicit['vectors_computed'] == 3
    assert explicit['seed_paths'] == []
    assert explicit['seed_fallbacks'] == [
        {'path': str(missing), 'reason': 'no_previous_index'},
    ]


def test_auto_does_not_search_other_clones(tmp_path, monkeypatch):
    original = tmp_path / 'original'
    original.mkdir()
    git(original, 'init', '-q')
    git(original, 'config', 'user.email', 'seed@test.invalid')
    git(original, 'config', 'user.name', 'Seed Test')
    (original / '.project-brain.json').write_text('{}')
    git(original, 'add', '.project-brain.json')
    git(original, 'commit', '-qm', 'fixture')
    other = tmp_path / 'other-clone'
    git(tmp_path, 'clone', '-q', str(original), str(other))
    other_brain = corpus(other / 'brain')
    rebuild(other_brain, other_brain / '.brain-local/index.db')
    target = tmp_path / 'target'
    git(original, 'worktree', 'add', '-qb', 'target', str(target))
    corpus(target / 'brain')
    # 같은 clone의 config가 별도 clone DB를 가리켜도 자동 seed로 채택하지 않는다.
    (original / '.project-brain.json').write_text(json.dumps({
        'db': str(other_brain / '.brain-local/index.db'),
    }))
    monkeypatch.chdir(target)
    result = run_cli('index', 'rebuild', '--stub-embedder')
    assert result['vectors_seeded'] == 0
    assert result['vectors_computed'] == 3
    assert result['seed_paths'] == []
    assert result['seed_fallbacks'] == [{
        'path': str(other_brain / '.brain-local/index.db'), 'reason': 'seed_clone_mismatch',
    }]


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_auto_discovers_same_clone_original_first_and_config_can_disable(tmp_path, monkeypatch):
    original = tmp_path / 'original'
    original.mkdir()
    git(original, 'init', '-q')
    git(original, 'config', 'user.email', 'seed@test.invalid')
    git(original, 'config', 'user.name', 'Seed Test')
    config = {'brain_root': 'data/knowledge', 'db': 'cache/custom.db'}
    (original / '.project-brain.json').write_text(json.dumps(config))
    git(original, 'add', '.project-brain.json')
    git(original, 'commit', '-qm', 'fixture')
    sibling = tmp_path / 'sibling'
    target = tmp_path / 'target'
    git(original, 'worktree', 'add', '-qb', 'sibling', str(sibling))
    git(original, 'worktree', 'add', '-qb', 'target', str(target))
    for root in (original, sibling, target):
        corpus(root / 'data/knowledge')
    original_db = original / 'cache/custom.db'
    sibling_db = sibling / 'cache/custom.db'
    # 명시 seed를 주어 fixture 생성 시 자동 탐색을 억제한다.
    for root, db in ((original, original_db), (sibling, sibling_db)):
        rebuild(root / 'data/knowledge', db, '--seed', tmp_path / 'absent.db')
    monkeypatch.chdir(target)
    result = run_cli('index', 'rebuild', '--stub-embedder')
    assert result['vectors_seeded'] == 3
    assert result['seed_paths'] == [str(original_db)]
    # 원본이 손상되면 같은 clone의 다음 checkout으로 진행한다.
    original_db.write_bytes(b'broken sqlite')
    result = rebuild(target / 'data/knowledge', target / 'fallback.db')
    assert result['vectors_seeded'] == 3
    assert result['seed_paths'] == [str(sibling_db)]
    assert result['seed_fallbacks'] == [
        {'path': str(original_db), 'reason': 'unreadable_previous_index'},
    ]
    (original / '.project-brain.json').write_text('[]')
    invalid_config = rebuild(target / 'data/knowledge', target / 'invalid-config.db')
    assert invalid_config['vectors_seeded'] == 3
    assert invalid_config['seed_paths'] == [str(sibling_db)]
    assert invalid_config['seed_fallbacks'] == [
        {'path': str(original / '.project-brain.json'), 'reason': 'invalid_seed_config'},
    ]
    config['index_seeds'] = []
    (target / '.project-brain.json').write_text(json.dumps(config))
    disabled = rebuild(target / 'data/knowledge', target / 'disabled.db')
    assert disabled['vectors_computed'] == 3
    assert disabled['vectors_seeded'] == 0


@pytest.mark.parametrize('use_seed', [True, False])
def test_full_reuse_does_not_construct_real_model(tmp_path, use_seed):
    from project_brain.embedder import RealEmbedder, StubEmbedder

    class FakeModel:
        device = 'cpu'
        dtype = 'torch.float32'
        max_seq_length = 2048

        def __init__(self, *args, **kwargs):
            pass

        def encode(self, texts, **kwargs):
            return StubEmbedder().embed_many(texts)

    external = SimpleNamespace(SentenceTransformer=FakeModel,
                               util=SimpleNamespace(get_device_name=lambda: 'cpu'))
    brain = corpus(tmp_path / 'brain')
    source = tmp_path / 'source.db'
    with patch.dict(sys.modules, {
        'sentence_transformers': external,
        'torch': SimpleNamespace(set_num_threads=lambda n: None),
    }), \
         patch.object(cli, 'get_embedder', side_effect=RealEmbedder):
        run_cli('index', 'rebuild', '--brain-root', brain, '--db', source)
        external.SentenceTransformer = lambda *a, **kw: pytest.fail('모델 가중치 로드 금지')
        args = ['--seed', source] if use_seed else []
        result = run_cli('index', 'rebuild', '--brain-root', brain,
                         '--db', tmp_path / 'new.db' if use_seed else source, *args)
    assert result['vectors_computed'] == 0
    assert result['vectors_seeded' if use_seed else 'vectors_reused'] == 3
