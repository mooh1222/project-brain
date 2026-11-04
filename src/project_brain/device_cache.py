"""실행 장치 판정만 보관하는 머신 로컬 힌트 (#96). 모델 로더는 항상 재판정한다."""
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import re
import stat
import sys
import tempfile


def _cache_path() -> Path:
    from project_brain.embedding_service import runtime_dir

    # sentence-transformers 5.6 get_device_name: CUDA(+LOCAL_RANK/distributed),
    # MPS, torch-npu, XPU, Habana 순. backend 가시성/driver 설정도 보수적으로 포함한다.
    packages = {}
    for name in ('torch', 'sentence-transformers', 'transformers', 'torch-npu',
                 'habana-torch', 'intel-extension-for-pytorch'):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    inputs = {
        'format': 1, 'executable': os.path.realpath(sys.executable),
        'prefix': sys.prefix, 'python': platform.python_version(),
        'machine': platform.machine(), 'system': platform.system(),
        'release': platform.release(), 'os_version': platform.version(),
        'packages': packages,
        'environment': {k: v for k, v in os.environ.items() if k.startswith((
            'CUDA_', 'NVIDIA_', 'PYTORCH_', 'TORCH_', 'HIP_', 'ROCR_', 'HSA_',
            'ASCEND_', 'NPU_', 'XPU_', 'ONEAPI_', 'ZE_', 'SYCL_', 'HPU_', 'HABANA_',
        )) or k in ('LOCAL_RANK', 'RANK', 'WORLD_SIZE', 'LD_LIBRARY_PATH',
                    'DYLD_LIBRARY_PATH')},
    }
    key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    return runtime_dir() / f'device-{key}.json'


def _distributed_initialized() -> bool:
    # 이미 분산 runtime을 초기화한 직접 호출자는 환경에 없는 rank 상태도 사용한다.
    torch = sys.modules.get('torch')
    distributed = getattr(torch, 'distributed', None)
    return (distributed is not None and distributed.is_available()
            and distributed.is_initialized())


def read_device() -> str | None:
    if _distributed_initialized():
        return None
    try:
        fd = os.open(_cache_path(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd) as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > 16384):
                return None
            value = json.load(stream)
        if (isinstance(value, dict) and value.get('format') == 1
                and isinstance(value.get('device'), str)
                and re.fullmatch(r'cpu|(?:cuda|mps|npu|xpu|hpu):[0-9]+', value['device'])):
            return value['device']
    except (OSError, ValueError):
        pass
    return None


def write_device(device: str) -> None:
    if _distributed_initialized():
        return  # 프로세스 내부 rank를 일반 클라이언트의 머신 캐시에 기록하지 않는다.
    path = _cache_path()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.device-',
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'format': 1, 'device': device}, stream)
        os.replace(temporary, path)
    except OSError:
        pass  # 선택 캐시 쓰기 실패는 실제 장치 판정을 무효화하지 않는다.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def invalidate_device() -> None:
    _cache_path().unlink(missing_ok=True)
