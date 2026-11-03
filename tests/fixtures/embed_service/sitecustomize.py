"""외부 ML/OS 경계 fake. 하위 프로세스에도 적용하며 가중치를 절대 읽지 않는다."""
import os
import sys
import time
import types
from pathlib import Path

if os.environ.get('PB_TEST_DIR'):
    import numpy as np

    def event(kind):
        with open(Path(os.environ['PB_TEST_DIR']) / 'events', 'a') as stream:
            stream.write(f'{kind} {os.getpid()} {time.monotonic()}\n')

    class Model:
        device = 'cpu'
        dtype = 'torch.float32'

        def __init__(self, *args, **kwargs):
            event('load')
            import atexit
            atexit.register(lambda: event('unload'))

        def encode(self, texts, **kwargs):
            from project_brain.embedder import StubEmbedder
            event('begin')
            time.sleep(float(os.environ.get('PB_TEST_DELAY', '0')))
            result = np.asarray(StubEmbedder().embed_many(texts))
            event('end')
            return result

    sys.modules['torch'] = types.SimpleNamespace(set_num_threads=lambda n: None)
    sys.modules['sentence_transformers'] = types.SimpleNamespace(
        SentenceTransformer=Model, util=types.SimpleNamespace(get_device_name=lambda: 'cpu'))
    import project_brain.embedding_service as service
    service.runtime_dir = lambda: Path(os.environ['PB_TEST_DIR'])
    if os.environ.get('PB_TEST_SOCKET_BLOCK'):
        import socket
        original_socket = socket.socket

        def blocked(family=socket.AF_INET, *args, **kwargs):
            if family == socket.AF_UNIX:
                raise PermissionError('test sandbox socket denied')
            return original_socket(family, *args, **kwargs)
        socket.socket = blocked
    if os.environ.get('PB_TEST_START_FAIL'):
        import subprocess
        original_popen = subprocess.Popen

        def start_failure(args, *positional, **kwargs):
            if any('from project_brain.embedding_service import serve' in str(arg) for arg in args):
                raise OSError('fake spawn failure')
            return original_popen(args, *positional, **kwargs)
        subprocess.Popen = start_failure
