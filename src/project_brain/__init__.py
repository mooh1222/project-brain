"""Project Brain; content-bound releases record the code actually executed."""

import sys as _sys
from pathlib import Path as _Path

_package = _Path(__file__).resolve().parent
if (_package / "_release_identity.json").is_file():
    # Register before importing engine_identity, so neither bootstrap module is
    # inferred from a disk cache. Checkout imports retain their existing behavior.
    _executed = {str(_Path(__file__).resolve()): {_sys._getframe().f_code}}

    def _record_execution(event, args):
        if event == "exec":
            code = args[0]
            if code.co_name == "<module>" and code.co_filename.endswith(".py"):
                path = _Path(code.co_filename).resolve()
                if path.is_relative_to(_package):
                    _executed.setdefault(str(path), set()).add(code)

    _sys.addaudithook(_record_execution)
    from .engine_identity import _bootstrap_release

    _bootstrap_release(_executed)
