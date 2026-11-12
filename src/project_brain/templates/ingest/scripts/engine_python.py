"""적재 도구의 엔진 Python을 명시 override 또는 프로젝트 고정 release로 선택한다.

PROJECT_BRAIN_PYTHON은 명시 실행 환경을 유지한다. 미지정이면 이 스크립트가 속한
.project-brain.json의 checkout에서 .local/brain-tools/project-brain만 사용한다.
현재 Python의 import 가능 여부나 PATH 전역 launcher로 폴백하지 않는다.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType
from collections.abc import Callable, Mapping, MutableMapping

OVERRIDE = "PROJECT_BRAIN_PYTHON"
GUARD = "PROJECT_BRAIN_ENGINE_REEXEC"
_HINT = ("프로젝트 고정 Brain release 없음(준비 남음): 프로젝트 prepare/설치를 실행하거나 "
         f"{OVERRIDE}를 엔진이 깔린 Python의 절대 경로로 명시하세요.")


def load_source(path: Path, name: str) -> ModuleType:
    """Execute pinned runtime source, never a timestamp-based bytecode cache."""
    module = ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec", dont_inherit=True), module.__dict__)
    return module


def project_root() -> Path | None:
    # cwd 대신 스크립트 소속 config를 찾는다. skills 심링크도 실제 checkout으로 해석한다.
    for parent in Path(__file__).resolve().parents:
        if (parent / ".project-brain.json").is_file():
            return parent
    return None


def resolve(env: Mapping[str, str]) -> str | None:
    if env.get(OVERRIDE):
        return env[OVERRIDE]
    root = project_root()
    if root is None:
        return None
    python = root / ".local/brain-tools/project-brain/bin/python"
    launcher = python.with_name("project-brain")
    if not all(path.is_file() and os.access(path, os.X_OK) for path in (python, launcher)):
        return None
    return str(python)


def _engine_importable() -> bool:
    return importlib.util.find_spec("project_brain") is not None


def choose(
    env: Mapping[str, str],
    *,
    importable: Callable[[], bool] = _engine_importable,
    executable: str | None = None,
    resolve_interpreter: Callable[[Mapping[str, str]], str | None] = resolve,
) -> str | None:
    executable = sys.executable if executable is None else executable
    if env.get(OVERRIDE):
        return env[OVERRIDE]
    return resolve_interpreter(env)


def _same_interpreter(left: str, right: str) -> bool:
    # venv python은 base python의 symlink라 realpath로 비교하면 다른 환경도 같게 보인다.
    return os.path.abspath(left) == os.path.abspath(right)


def ensure(
    *,
    argv: list[str] | None = None,
    env: MutableMapping[str, str] | None = None,
    importable: Callable[[], bool] = _engine_importable,
    resolve_interpreter: Callable[[Mapping[str, str]], str | None] = resolve,
    executable: str | None = None,
    execve: Callable[[str, list[str], dict[str, str]], object] = os.execve,
) -> None:
    live_env = os.environ if env is None else env
    executable = sys.executable if executable is None else executable
    interpreter = choose(live_env, importable=importable, executable=executable,
                         resolve_interpreter=resolve_interpreter)
    explicit = bool(live_env.get(OVERRIDE))
    if interpreter is not None and _same_interpreter(interpreter, executable) and (
        explicit or sys.flags.isolated
    ):
        if not importable():
            raise SystemExit(
                f"project_brain을 import할 수 없습니다: 고른 Python {interpreter}에 엔진이 없습니다. "
                + _HINT
            )
        if not explicit:
            live_env.pop("PYTHONPATH", None)
            live_env.pop("PYTHONHOME", None)
            live_env["PATH"] = str(Path(interpreter).parent) + os.pathsep + live_env.get("PATH", os.defpath)
        # 자리를 잡았으면 표식을 지운다 — 자식 스크립트도 필요하면 스스로 넘어가야 한다.
        live_env.pop(GUARD, None)
        return
    if live_env.get(GUARD):
        raise SystemExit(
            f"project_brain을 import할 수 없습니다: 다시 실행한 {executable}에서도 엔진 Python을 "
            "확정하지 못했습니다. " + _HINT
        )
    if interpreter is None:
        raise SystemExit(
            f"project_brain을 import할 수 없습니다({executable}). " + _HINT
        )
    new_env = dict(live_env)
    flags = []
    if not explicit:
        new_env.pop("PYTHONPATH", None)
        new_env.pop("PYTHONHOME", None)
        new_env["PATH"] = str(Path(interpreter).parent) + os.pathsep + new_env.get("PATH", os.defpath)
        flags = ["-I", "-B"]
    new_env[GUARD] = "1"
    argv = list(sys.argv if argv is None else argv)
    try:
        execve(interpreter, [interpreter, *flags, *argv], new_env)
    except OSError as exc:
        raise SystemExit(
            f"엔진 Python {interpreter}을 실행할 수 없습니다: {exc}. " + _HINT
        ) from exc


def main() -> int:
    interpreter = choose(os.environ)
    if interpreter is None:
        print(_HINT, file=sys.stderr)
        return 1
    print(interpreter)
    return 0


if __name__ == "__main__":
    sys.exit(main())
