"""설치 스크립트를 엔진(project_brain)이 깔린 Python으로 실행되게 한다.

스크립트는 shebang `#!/usr/bin/env python3`나 `python3 x.py`로 시작하는데, release 설치본의
엔진은 uv tool 환경에만 있어 시스템 python3로는 import되지 않는다. 엔진 import 전에
`ensure()`를 부르면 다음 순서로 고른 Python이 지금 인터프리터와 다를 때 같은 인자로 자신을
다시 실행한다.

1. `PROJECT_BRAIN_PYTHON` 환경 변수 — 지정하면 항상 이 Python을 쓴다
2. 지금 인터프리터 — 엔진을 import할 수 있으면 그대로
3. PATH의 `project-brain` 실행 파일이 가리키는 인터프리터(shebang)

찾지 못하거나 다시 실행한 뒤에도 import가 안 되면 추측하지 않고 이유를 남기고 멈춘다.
wrapper는 `python3 engine_python.py`로 고른 경로를 한 번 받아 쓴다(표준 출력 한 줄).
"""

from __future__ import annotations

import importlib.util
import os
import shlex
import shutil
import sys
from collections.abc import Callable, Mapping, MutableMapping

OVERRIDE = "PROJECT_BRAIN_PYTHON"
GUARD = "PROJECT_BRAIN_ENGINE_REEXEC"
_HINT = f"{OVERRIDE}를 엔진이 깔린 Python의 절대 경로로 지정하세요."


def _env_program(args: list[str], which: Callable[[str], str | None]) -> str | None:
    """`env [-S] [-옵션] [NAME=값] program …`에서 program을 PATH로 찾는다."""
    words = list(args)
    while words:
        word = words.pop(0)
        if word.startswith("-S"):
            words = word[2:].split() + words
        elif word.startswith("-") or "=" in word:
            continue
        else:
            return which(word)
    return None


def interpreter_from_shebang(text: str, which: Callable[[str], str | None]) -> str | None:
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#!"):
        return None
    # 커널은 shebang을 셸 인용 없이 공백으로만 나눈다(인터프리터 + 인자).
    words = lines[0][2:].split()
    if not words:
        return None
    program = os.path.basename(words[0])
    if program == "env":
        return _env_program(words[1:], which)
    if program == "sh" and len(lines) > 1 and lines[1].startswith("'''exec'"):
        # uv/pip가 공백 있는 경로에 쓰는 sh trampoline: '''exec' '<python>' "$0" "$@"
        try:
            exec_words = shlex.split(lines[1][len("'''exec'"):])
        except ValueError:
            return None
        return exec_words[0] if exec_words else None
    if program in {"sh", "bash"}:
        return None
    return words[0]


def _read_head(path: str) -> str:
    with open(path, "rb") as handle:
        return handle.read(4096).decode("utf-8", errors="replace")


def resolve(
    env: Mapping[str, str],
    which: Callable[[str], str | None] = shutil.which,
    read_head: Callable[[str], str] = _read_head,
) -> str | None:
    if env.get(OVERRIDE):
        return env[OVERRIDE]
    launcher = which("project-brain")
    if launcher is None:
        return None
    try:
        return interpreter_from_shebang(read_head(launcher), which)
    except OSError:
        return None


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
    if importable():
        return executable
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
    if interpreter is not None and _same_interpreter(interpreter, executable):
        if not importable():
            raise SystemExit(
                f"project_brain을 import할 수 없습니다: 고른 Python {interpreter}에 엔진이 없습니다. "
                + _HINT
            )
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
            f"project_brain을 import할 수 없습니다({executable}). PATH에 project-brain을 두거나 "
            + _HINT
        )
    new_env = dict(live_env)
    new_env[GUARD] = "1"
    argv = list(sys.argv if argv is None else argv)
    try:
        execve(interpreter, [interpreter, *argv], new_env)
    except OSError as exc:
        raise SystemExit(
            f"엔진 Python {interpreter}을 실행할 수 없습니다: {exc}. " + _HINT
        ) from exc


def main() -> int:
    interpreter = choose(os.environ)
    if interpreter is None:
        print("project_brain을 import할 Python을 찾지 못했습니다. PATH에 project-brain을 두거나 "
              + _HINT, file=sys.stderr)
        return 1
    print(interpreter)
    return 0


if __name__ == "__main__":
    sys.exit(main())
