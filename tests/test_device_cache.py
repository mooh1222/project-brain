"""#96: 프로세스 경계에서 신원 바이트와 ML import 없는 캐시 재사용을 검증한다."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_embedding_service import EMBED, cli, env, events, run


IDENTITY = """
from project_brain.embedder import get_embedder
import json, sys
identity = get_embedder(False).embedding_identity
print(json.dumps({'identity': identity, 'ml_loaded': any(
    name.split('.')[0] in ('torch', 'sentence_transformers') for name in sys.modules)}))
"""


def test_cache_hit_preserves_identity_without_importing_ml(env):
    original = run(env, IDENTITY)['identity']
    hit = run({**env, 'PB_TEST_NO_ML': '1'}, IDENTITY)
    assert hit == {'identity': original, 'ml_loaded': False}
    assert json.loads(original)['device'] == 'cpu'


def cache_file(env):
    return next(Path(env['PB_TEST_DIR']).glob('device-*.json'))


@pytest.mark.parametrize('damage', ['json', 'format', 'device', 'permissions', 'symlink'])
def test_invalid_cache_is_a_miss_and_preserves_identity(env, damage):
    original = run(env, IDENTITY)['identity']
    path = cache_file(env)
    if damage == 'json':
        path.write_text('{broken')
    elif damage == 'format':
        path.write_text('{"format": 2, "device": "cuda:0"}')
    elif damage == 'device':
        path.write_text('{"format": 1, "device": []}')
    elif damage == 'permissions':
        path.chmod(0o644)
    else:
        target = path.with_suffix('.target')
        path.rename(target)
        path.symlink_to(target)
    assert run(env, IDENTITY)['identity'] == original
    assert not path.is_symlink() and path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('name', ['CUDA_VISIBLE_DEVICES', 'LOCAL_RANK',
                                  'PYTORCH_ENABLE_MPS_FALLBACK', 'ZE_AFFINITY_MASK'])
def test_device_environment_change_is_a_cache_miss(env, name):
    original = run(env, IDENTITY)['identity']
    changed = {**env, name: '96-test'}
    assert run(changed, IDENTITY)['identity'] == original
    assert len(list(Path(env['PB_TEST_DIR']).glob('device-*.json'))) == 2


def test_concurrent_writers_leave_a_readable_identity_without_ml(env):
    children = [subprocess.Popen([sys.executable, '-c', IDENTITY], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for _ in range(5)]
    identities = []
    for child in children:
        out, err = child.communicate(timeout=25)
        assert child.returncode == 0, err
        identities.append(json.loads(out)['identity'])
    assert len(set(identities)) == 1
    assert run({**env, 'PB_TEST_NO_ML': '1'}, IDENTITY) == {
        'identity': identities[0], 'ml_loaded': False}
    assert not list(Path(env['PB_TEST_DIR']).glob('.device-*'))


@pytest.mark.parametrize('service', ['1', '0'])
def test_wrong_device_recovers_and_returns_exact_vectors(env, service):
    original = run(env, IDENTITY)['identity']
    path = cache_file(env)
    path.write_text('{"format": 1, "device": "cuda:99"}')
    result = run({**env, 'PROJECT_BRAIN_EMBED_SERVICE': service})
    assert result == run({**env, 'PROJECT_BRAIN_EMBED_SERVICE': '0'})
    assert run(env, IDENTITY)['identity'] == original
    loads = [e for e in events(env) if e[0] == 'load']
    # service: 2 service models (old one stopped first), fallback: same loaded model.
    assert len(loads) == (3 if service == '1' else 2)


@pytest.mark.parametrize('service', ['1', '0'])
def test_second_identity_change_is_an_error_without_unbounded_retry(env, service):
    result = subprocess.run([sys.executable, '-c', EMBED],
                            env={**env, 'PROJECT_BRAIN_EMBED_SERVICE': service,
                                 'PB_TEST_DTYPE': 'torch.float16'},
                            capture_output=True, text=True, timeout=25)
    assert result.returncode != 0
    assert 'embedding_identity_changed:' in result.stderr
    assert len([e for e in events(env) if e[0] == 'begin']) == 2


def test_resident_service_client_does_not_import_ml(env):
    expected = run(env)
    assert cli(env, 'embedder', 'status')['model_loaded']
    assert run({**env, 'PB_TEST_NO_ML': '1'}) == expected


@pytest.mark.parametrize(('detected', 'device'), [('cpu', 'cpu'), ('mps', 'mps:0'),
                                               ('cuda:3', 'cuda:3')])
def test_identity_matches_existing_v2_bytes(env, detected, device):
    from importlib.metadata import version
    packages = ', '.join(f'"{name}": "{version(name)}"' for name in
                         ('numpy', 'sentence-transformers', 'torch', 'transformers'))
    # #95 v2의 고정 필드·직렬화. 캐시 구현으로부터 기대값을 만들지 않는다.
    expected = ('{"device": "' + device + '", "dimension": 1024, "implementation": 2, '
                '"max_seq_length": 2048, "model": "BAAI/bge-m3", '
                '"model_dtype": "torch.float32", "normalize_embeddings": true, '
                '"output_dtype": "float32", "packages": {' + packages + '}, '
                '"revision": "5617a9f61b028005a4858fdac845db406aefb181"}')
    assert run({**env, 'PB_TEST_DEVICE': detected}, IDENTITY)['identity'].encode() == expected.encode()
    assert run({**env, 'PB_TEST_NO_ML': '1'}, IDENTITY)['identity'].encode() == expected.encode()


@pytest.mark.parametrize('change', [
    'sys.executable = "/different/python"',
    'sys.prefix = "/different/venv"',
    'platform.machine = lambda: "different-machine"',
    'platform.release = lambda: "different-os"',
    'importlib.metadata.version = lambda name: "different-version"',
])
def test_execution_environment_change_does_not_reuse_cache(env, change):
    run(env, IDENTITY)
    code = 'import sys, platform, importlib.metadata\n' + change + '\n' + IDENTITY
    run(env, code)
    assert len(list(Path(env['PB_TEST_DIR']).glob('device-*.json'))) == 2
