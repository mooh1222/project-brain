"""#94: get_embedder/CLI와 외부 가짜 모델로 관찰하는 프로세스 간 계약."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
EMBED = """
from project_brain.embedder import get_embedder
import json
emb = get_embedder(stub=False)
print(json.dumps([v.tobytes().hex() for v in emb.embed_many(['보상', '우승'])]))
"""


@pytest.fixture
def env(tmp_path):
    import tempfile
    import shutil
    runtime = tempfile.mkdtemp(prefix='pb94-', dir='/tmp')
    result = {**os.environ, 'PB_TEST_DIR': runtime,
              'PYTHONPATH': os.pathsep.join([str(ROOT / 'tests/fixtures/embed_service'),
                                           str(ROOT / 'src')]),
              'PROJECT_BRAIN_EMBED_IDLE_SECONDS': '30',
              'PROJECT_BRAIN_EMBED_WAIT_SECONDS': '8'}
    result.pop('PROJECT_BRAIN_EMBEDDER', None)
    yield result
    subprocess.run([sys.executable, '-m', 'project_brain.cli', 'embedder', 'stop'],
                   env=result, capture_output=True, timeout=15)
    shutil.rmtree(runtime)


def run(env, code=EMBED):
    result = subprocess.run([sys.executable, '-c', code], env=env,
                            capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def cli(env, *args):
    result = subprocess.run([sys.executable, '-m', 'project_brain.cli', *map(str, args)],
                            env=env, capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def events(env):
    path = Path(env['PB_TEST_DIR']) / 'events'
    return [line.split() for line in path.read_text().splitlines()] if path.exists() else []


def test_concurrent_first_requests_share_one_model_and_exact_vectors(env):
    children = [subprocess.Popen([sys.executable, '-c', EMBED], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for _ in range(5)]
    results = []
    for child in children:
        out, err = child.communicate(timeout=25)
        assert child.returncode == 0, err
        results.append(json.loads(out))
    assert all(result == results[0] for result in results)
    assert len([e for e in events(env) if e[0] == 'load']) == 1
    state = cli(env, 'embedder', 'status')
    assert state['running'] and state['identity'] and state['rss_bytes'] > 0
    assert run({**env, 'PROJECT_BRAIN_EMBED_SERVICE': '0'}) == results[0]


@pytest.mark.parametrize('slots', [1, 2])
def test_blocked_socket_fallback_limits_live_models(env, slots):
    env = {**env, 'PB_TEST_SOCKET_BLOCK': '1', 'PB_TEST_DELAY': '0.25',
           'PROJECT_BRAIN_EMBED_SLOTS': str(slots)}
    children = [subprocess.Popen([sys.executable, '-c', EMBED], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for _ in range(5)]
    for child in children:
        out, err = child.communicate(timeout=25)
        assert child.returncode == 0, err
        assert json.loads(out)
    live = peak = 0
    for kind, pid, stamp in sorted(events(env), key=lambda e: float(e[2])):
        if kind == 'load':
            live += 1
        elif kind == 'unload':
            live -= 1
        peak = max(peak, live)
    assert peak == slots
    assert live == 0
    assert not cli(env, 'embedder', 'status')['running']


def test_slot_timeout_is_explicit_busy_error(env):
    import time
    busy = {**env, 'PB_TEST_SOCKET_BLOCK': '1', 'PB_TEST_DELAY': '2',
            'PROJECT_BRAIN_EMBED_WAIT_SECONDS': '0.15'}
    child = subprocess.Popen([sys.executable, '-c', EMBED], env=busy,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not events(env) and time.monotonic() < deadline:
            time.sleep(0.05)
        result = subprocess.run([sys.executable, '-c', EMBED], env=busy,
                                capture_output=True, text=True, timeout=15)
        assert result.returncode != 0
        assert 'embedder_busy' in result.stderr
        assert 'PROJECT_BRAIN_EMBED_WAIT_SECONDS' in result.stderr
    finally:
        out, err = child.communicate(timeout=15)
        assert child.returncode == 0, err


def test_idle_exit_kill_and_stale_artifacts_recover(env):
    import signal
    import socket
    import time
    env = {**env, 'PROJECT_BRAIN_EMBED_IDLE_SECONDS': '0.7'}
    state = cli(env, 'embedder', 'status')
    assert not state['running']
    stale = Path(state['socket'])
    with socket.socket(socket.AF_UNIX) as sock:
        sock.bind(str(stale))
    stale.with_suffix('.owner').write_text('99999999')
    stale.with_suffix('.start').write_text('99999999')
    expected = run(env)
    state = cli(env, 'embedder', 'status')
    os.kill(state['pid'], signal.SIGKILL)
    assert run(env) == expected
    time.sleep(1)
    assert not cli(env, 'embedder', 'status')['running']
    assert run(env) == expected
    assert len([e for e in events(env) if e[0] == 'load']) == 3


@pytest.mark.parametrize('wrong', ['identity', 'version'])
def test_incompatible_service_is_rejected_before_text_is_sent(env, wrong):
    import socket
    import struct
    import threading
    state = cli(env, 'embedder', 'status')
    identity = run(env, "from project_brain.embedder import get_embedder; import json; "
                   "print(json.dumps(get_embedder(False).embedding_identity))")
    received = []
    with socket.socket(socket.AF_UNIX) as server:
        server.bind(state['socket'])
        server.listen(8)
        server.settimeout(3)
        def peer():
            while True:
                try:
                    conn, _ = server.accept()
                except (OSError, TimeoutError):
                    return
                with conn:
                    hello = {'identity': identity, 'version': 1}
                    hello[wrong] = 'incompatible'
                    payload = json.dumps(hello).encode()
                    conn.sendall(struct.pack('!I', len(payload)) + payload)
                    received.append(conn.recv(100))
        thread = threading.Thread(target=peer)
        thread.start()
        try:
            assert run(env) == run({**env, 'PROJECT_BRAIN_EMBED_SERVICE': '0'})
        finally:
            thread.join(timeout=5)
    assert received and all(data == b'' for data in received)


def test_rebuild_and_search_use_service_with_identical_index_results(env, tmp_path):
    from tests.test_index_seeds import corpus
    brain = corpus(tmp_path / 'brain')
    direct = tmp_path / 'direct.db'
    shared = tmp_path / 'shared.db'
    a = cli({**env, 'PROJECT_BRAIN_EMBED_SERVICE': '0'}, 'index', 'rebuild',
            '--brain-root', brain, '--db', direct, '--seed', tmp_path / 'absent')
    b = cli(env, 'index', 'rebuild', '--brain-root', brain, '--db', shared,
            '--seed', tmp_path / 'absent')
    assert a['vectors_computed'] == b['vectors_computed'] == 3
    assert cli(env, 'embedder', 'status')['model_loaded']
    args = ['search', '우승 보상', '--brain-root', brain]
    assert cli(env, *args, '--db', direct) == cli(env, *args, '--db', shared)
    # 색인 저장 벡터의 동치는 동일 DB를 seed로 전량 재사용하는 경계와 함께 확인한다.
    import sqlite3
    def vectors(path):
        with sqlite3.connect(path) as conn:
            import sqlite_vec
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            return conn.execute('SELECT rowid, embedding FROM documents_vec ORDER BY rowid').fetchall()
    assert vectors(direct) == vectors(shared)


def test_fallback_holds_slot_while_cached_model_is_idle(env):
    import time
    code = EMBED + "\nimport time; time.sleep(1.5)"
    direct = {**env, 'PROJECT_BRAIN_EMBED_SERVICE': '0',
              'PROJECT_BRAIN_EMBED_WAIT_SECONDS': '0.15'}
    child = subprocess.Popen([sys.executable, '-c', code], env=direct,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 10
        while not any(e[0] == 'end' for e in events(env)) and time.monotonic() < deadline:
            time.sleep(0.02)
        result = subprocess.run([sys.executable, '-c', EMBED], env=direct,
                                capture_output=True, text=True, timeout=15)
        assert result.returncode != 0 and 'embedder_busy' in result.stderr
    finally:
        child.communicate(timeout=15)
    assert run(direct)


def test_large_rebuild_batch_and_service_failure_fallback(env):
    code = """
from project_brain.embedder import get_embedder
import json
emb = get_embedder(False)
print(json.dumps([v.tobytes().hex() for v in emb.embed_many([str(n) for n in range(70)])]))
"""
    expected = run({**env, 'PROJECT_BRAIN_EMBED_SERVICE': '0'}, code)
    assert run(env, code) == expected
    cli(env, 'embedder', 'stop')
    assert run({**env, 'PB_TEST_START_FAIL': '1'}, code) == expected


def test_doctor_reports_service_without_starting_model(env):
    before = cli(env, 'doctor')
    check = next(c for c in before['checks'] if c['name'] == 'embed-service')
    assert not json.loads(check['detail'])['running']
    assert not events(env)
    run(env)
    after = cli(env, 'doctor')
    state = json.loads(next(c for c in after['checks'] if c['name'] == 'embed-service')['detail'])
    assert state['running'] and state['rss_bytes'] > 0 and state['identity']
