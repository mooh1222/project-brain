"""사용자별 임베딩 서비스와 프로세스 내 로드의 전역 메모리 경계 (#94).

flock 파일은 지우지 않는다: inode를 바꾸면 실행 중인 소유자의 잠금이 우회된다.
모델이 살아 있는 동안 service/slot FD를 보유하며 OS가 사망 시 자동 회수한다.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import math
import os
import queue
import signal
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
import threading
import time

import numpy as np

PROTOCOL_VERSION = 1
MAX_FRAME = 16 * 1024 * 1024
BATCH_SIZE = 32


class EmbedderError(RuntimeError):
    pass


class ServiceUnavailable(Exception):
    pass


class ServiceMismatch(ServiceUnavailable):
    pass


def setting(name: str, default: float) -> float:
    value = float(os.environ.get(f'PROJECT_BRAIN_EMBED_{name}', default))
    if not math.isfinite(value) or value <= 0:
        raise EmbedderError(f'잘못된 PROJECT_BRAIN_EMBED_{name}: 양수여야 합니다')
    return value


def runtime_dir() -> Path:
    # TMPDIR은 터미널/샌드박스마다 달라질 수 있다. 같은 사용자의 모든 checkout이
    # 같은 잠금을 써야 하므로 OS 공용 임시 위치에 uid로 고정한다.
    path = Path('/tmp') / f'project-brain-embed-{os.getuid()}'
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise EmbedderError(f'안전하지 않은 임베딩 runtime 디렉터리: {path}')
    return path


def _paths(identity: str) -> tuple[Path, Path, Path, Path]:
    key = hashlib.sha256(f'{PROTOCOL_VERSION}\0{identity}'.encode()).hexdigest()[:32]
    base = runtime_dir() / key
    return tuple(Path(f'{base}.{suffix}') for suffix in ('sock', 'start', 'owner', 'log'))


def _try_lock(path: Path) -> int | None:
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    return fd


def _wait_lock(path: Path, deadline: float) -> int:
    while True:
        fd = _try_lock(path)
        if fd is not None:
            return fd
        if time.monotonic() >= deadline:
            raise ServiceUnavailable('서비스 기동 잠금 대기 초과')
        time.sleep(0.05)


def acquire_slot() -> int:
    count = setting('SLOTS', 1)
    if not count.is_integer():
        raise EmbedderError('PROJECT_BRAIN_EMBED_SLOTS는 양의 정수여야 합니다')
    deadline = time.monotonic() + setting('WAIT_SECONDS', 300)
    try:
        while True:
            for number in range(int(count)):
                fd = _try_lock(runtime_dir() / f'fallback-{number}.lock')
                if fd is not None:
                    return fd
            if time.monotonic() >= deadline:
                raise EmbedderError(
                    'embedder_busy: 다른 프로세스가 임베딩 모델 슬롯을 사용 중입니다. '
                    '진행 중인 검색 종료 후 재시도하거나 PROJECT_BRAIN_EMBED_WAIT_SECONDS를 늘리세요.')
            time.sleep(0.05)
    except OSError as exc:
        # 잠금이 불가능하면 로드를 허용하지 않는다.
        raise EmbedderError(f'embedder_lock_unavailable: {exc}; 임베딩을 실행하지 않았습니다') from exc


def _read_exact(conn: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        part = conn.recv(size - len(chunks))
        if not part:
            raise ServiceUnavailable('임베딩 서비스 연결 종료')
        chunks.extend(part)
    return bytes(chunks)


def _receive(conn: socket.socket) -> dict:
    size, = struct.unpack('!I', _read_exact(conn, 4))
    if size > MAX_FRAME:
        raise ServiceUnavailable('임베딩 서비스 프레임 크기 초과')
    value = json.loads(_read_exact(conn, size))
    if not isinstance(value, dict):
        raise ServiceUnavailable('임베딩 서비스 응답 형식 오류')
    return value


def _send(conn: socket.socket, payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode()
    if len(data) > MAX_FRAME:
        raise EmbedderError('임베딩 요청 크기 초과 (16MiB)')
    conn.sendall(struct.pack('!I', len(data)) + data)


def _connect(identity: str, timeout: float) -> socket.socket:
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        conn.settimeout(timeout)
        conn.connect(str(_paths(identity)[0]))
        hello = _receive(conn)
        if hello.get('version') != PROTOCOL_VERSION or hello.get('identity') != identity:
            raise ServiceMismatch('임베딩 서비스 신원/프로토콜 불일치')
        return conn
    except BaseException:
        conn.close()
        raise


def _exchange(identity: str, payload: dict, timeout: float) -> dict:
    with _connect(identity, timeout) as conn:
        _send(conn, payload)
        reply = _receive(conn)
    if reply.get('error'):
        raise EmbedderError(f"embedder_service_error: {reply['error']}")
    return reply


def _ensure_service(identity: str) -> None:
    try:
        with _connect(identity, 0.5):
            return
    except (OSError, ValueError, ServiceUnavailable) as exc:
        if isinstance(exc, (PermissionError, ServiceMismatch)):
            raise ServiceUnavailable(str(exc)) from exc
    sock, start, owner, log = _paths(identity)
    deadline = time.monotonic() + setting('WAIT_SECONDS', 300)
    lock = _wait_lock(start, deadline)
    process = None
    try:
        while True:
            try:
                with _connect(identity, 0.5):
                    return
            except ServiceMismatch:
                raise
            except (OSError, ValueError, ServiceUnavailable):
                pass
            # 서비스 수명 잠금이 있으면 바쁘거나 기동 중이다. 중복 spawn하지 않는다.
            owner_fd = _try_lock(owner)
            if owner_fd is not None:
                os.close(owner_fd)
                environment = dict(os.environ)
                environment['PYTHONPATH'] = os.pathsep.join(filter(None, [
                    str(Path(__file__).resolve().parents[1]), environment.get('PYTHONPATH')]))
                if process is None:
                    with log.open('ab') as stream:
                        process = subprocess.Popen(
                            [sys.executable, '-c',
                             'from project_brain.embedding_service import serve; serve()'],
                            env=environment, stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                            start_new_session=True,
                        )
                # child가 owner lock을 얻을 시간을 준다.
                time.sleep(0.1)
            if process is not None and process.poll() is not None:
                raise ServiceUnavailable(f'임베딩 서비스 기동 실패: {log}')
            if time.monotonic() >= deadline:
                raise ServiceUnavailable(f'임베딩 서비스 기동 대기 초과: {sock}')
            time.sleep(0.05)
    finally:
        os.close(lock)


class ServiceClient:
    def __init__(self, identity: str):
        self.identity = identity

    def embed_many(self, texts: list[str]) -> list[np.ndarray]:
        vectors = []
        for offset in range(0, len(texts), BATCH_SIZE):
            batch = texts[offset:offset + BATCH_SIZE]
            for attempt in range(2):
                try:
                    _ensure_service(self.identity)
                    reply = _exchange(self.identity, {'op': 'embed', 'texts': batch},
                                      setting('WAIT_SECONDS', 300))
                    data = base64.b64decode(reply['vectors'], validate=True)
                    from project_brain.embedder import EMBED_DIM
                    if len(data) != len(batch) * EMBED_DIM * 4:
                        raise ServiceUnavailable('임베딩 서비스 벡터 크기 불일치')
                    rows = np.frombuffer(data, dtype='<f4').reshape(len(batch), EMBED_DIM)
                    vectors.extend(row.copy() for row in rows)
                    break
                except (OSError, ValueError, KeyError, ServiceUnavailable) as exc:
                    if attempt:
                        raise ServiceUnavailable(str(exc)) from exc
        return vectors


class LockedLocal:
    def __init__(self, model):
        self.model = model
        self.identity = model.embedding_identity
        self.slot = None

    def embed_many(self, texts: list[str]) -> list[np.ndarray]:
        if self.slot is None:
            self.slot = acquire_slot()
        # 실패해도 모델이 일부 적재됐을 수 있다. FD를 모델과 함께 프로세스 종료까지 유지한다.
        vectors = self.model.embed_many(texts)
        if self.model.embedding_identity != self.identity:
            raise EmbedderError('embedding_identity_changed: 실제 임베딩 신원이 사전 신원과 다릅니다')
        return vectors


def _rss_bytes() -> int | None:
    try:
        result = subprocess.run(['ps', '-o', 'rss=', '-p', str(os.getpid())],
                                capture_output=True, text=True, timeout=2, check=True)
        return int(result.stdout.strip()) * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def service_status(identity: str) -> dict:
    sock, _, _, log = _paths(identity)
    base = {'socket': str(sock), 'log': str(log)}
    try:
        reply = _exchange(identity, {'op': 'status'}, 2)
        return {'running': True, **base, **reply}
    except (OSError, ValueError, ServiceUnavailable):
        return {'running': False, **base}


def service_stop(identity: str) -> dict:
    _, _, owner, _ = _paths(identity)
    try:
        _exchange(identity, {'op': 'stop'}, 2)
    except (OSError, ValueError, ServiceUnavailable):
        pass
    deadline = time.monotonic() + 10
    while True:
        fd = _try_lock(owner)
        if fd is not None:
            os.close(fd)
            return {'stopped': True}
        if time.monotonic() >= deadline:
            return {'stopped': False, 'error': 'embedder_stop_timeout'}
        time.sleep(0.05)


def serve() -> None:
    from project_brain.embedder import RealEmbedder
    model = RealEmbedder()
    identity = model.embedding_identity
    sock, _, owner, _ = _paths(identity)
    lock = _try_lock(owner)
    if lock is None:
        return

    # 모델 계산은 단일 worker에서 직렬화한다. listener는 계산 중에도 status/stop을 받는다.
    work = queue.Queue()
    state_lock = threading.Lock()
    pending = 0
    last_request = time.monotonic()

    def embed_worker():
        nonlocal pending, last_request
        while True:
            conn, texts = work.get()
            with conn:
                try:
                    rows = model.embed_many(texts)
                    if model.embedding_identity != identity:
                        raise EmbedderError('embedding_identity_changed: 모델 실행 신원 변경')
                    _send(conn, {'vectors': base64.b64encode(
                        b''.join(row.astype('<f4', copy=False).tobytes() for row in rows)
                    ).decode('ascii')})
                except Exception as exc:
                    try:
                        _send(conn, {'error': f'{type(exc).__name__}: {exc}'})
                    except OSError:
                        pass
                finally:
                    with state_lock:
                        pending -= 1
                        last_request = time.monotonic()

    threading.Thread(target=embed_worker, daemon=True).start()
    try:
        sock.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(sock))
            os.chmod(sock, 0o600)
            server.listen(64)
            idle = setting('IDLE_SECONDS', 600)
            while True:
                with state_lock:
                    if pending == 0 and time.monotonic() - last_request >= idle:
                        break
                server.settimeout(min(0.2, idle))
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                transferred = False
                try:
                    conn.settimeout(setting('WAIT_SECONDS', 300))
                    _send(conn, {'version': PROTOCOL_VERSION, 'identity': identity})
                    request = _receive(conn)
                    op = request.get('op')
                    if op == 'embed':
                        texts = request.get('texts')
                        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
                            raise ValueError('texts는 문자열 배열이어야 합니다')
                        with state_lock:
                            pending += 1
                        work.put((conn, texts))
                        transferred = True
                    elif op == 'status':
                        with state_lock:
                            busy = pending > 0
                        _send(conn, {'pid': os.getpid(), 'identity': identity,
                                     'version': PROTOCOL_VERSION, 'rss_bytes': _rss_bytes(),
                                     'idle_seconds': idle, 'busy': busy,
                                     'model_loaded': model._model is not None})
                    elif op == 'stop':
                        _send(conn, {'stopped': True})
                        # native encode 도중에도 메모리를 반환한다. OS가 모델과 수명 FD를
                        # 함께 회수한다. 남은 소켓은 다음 owner가 안전하게 정리한다.
                        os.kill(os.getpid(), signal.SIGTERM)
                    else:
                        _send(conn, {'error': '알 수 없는 임베딩 서비스 명령'})
                except (OSError, ValueError, ServiceUnavailable):
                    pass  # handshake probe/클라이언트 이탈은 서비스 종료 이유가 아니다.
                finally:
                    if not transferred:
                        conn.close()
    finally:
        sock.unlink(missing_ok=True)
        # native 메모리 회수 전에 owner FD를 풀지 않는다. 프로세스 종료가 회수한다.


if __name__ == '__main__':
    serve()
