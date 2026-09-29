"""engine_python — 시스템 python3로 실행된 스크립트가 엔진이 깔린 Python으로 넘어가는 계약."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import engine_python  # noqa: E402

HERE = Path(__file__).resolve().parent


class InterpreterFromShebangTest(unittest.TestCase):
    def test_direct_interpreter_path(self):
        self.assertEqual(
            engine_python.interpreter_from_shebang("#!/tools/pb/bin/python3\n", lambda _: None),
            "/tools/pb/bin/python3",
        )

    def test_env_shebang_resolves_through_path(self):
        self.assertEqual(
            engine_python.interpreter_from_shebang(
                "#!/usr/bin/env python3.12\n", {"python3.12": "/opt/py/python3.12"}.get),
            "/opt/py/python3.12",
        )

    def test_uv_sh_trampoline_for_paths_with_spaces(self):
        text = "#!/bin/sh\n'''exec' '/Users/a b/tools/pb/bin/python' \"$0\" \"$@\"\n' '''\n"
        self.assertEqual(engine_python.interpreter_from_shebang(text, lambda _: None),
                         "/Users/a b/tools/pb/bin/python")

    def test_kernel_splitting_keeps_quotes_in_paths(self):
        self.assertEqual(
            engine_python.interpreter_from_shebang("#!/Users/o'brien/pb/bin/python\n",
                                                   lambda _: None),
            "/Users/o'brien/pb/bin/python",
        )

    def test_env_split_string_option(self):
        self.assertEqual(
            engine_python.interpreter_from_shebang(
                "#!/usr/bin/env -S python3 -X utf8\n", {"python3": "/opt/py/python3"}.get),
            "/opt/py/python3",
        )

    def test_unrecognized_launcher_yields_none(self):
        self.assertIsNone(engine_python.interpreter_from_shebang("\x7fELF", lambda _: None))
        self.assertIsNone(engine_python.interpreter_from_shebang("#!/bin/sh\necho\n",
                                                                 lambda _: None))


class ResolveTest(unittest.TestCase):
    def test_explicit_override_wins(self):
        self.assertEqual(
            engine_python.resolve({"PROJECT_BRAIN_PYTHON": "/x/python"}, lambda _: "/bin/pb",
                                  lambda _: "#!/other/python\n"),
            "/x/python",
        )

    def test_falls_back_to_project_brain_launcher(self):
        self.assertEqual(
            engine_python.resolve({}, {"project-brain": "/bin/pb"}.get,
                                  {"/bin/pb": "#!/tools/pb/bin/python3\n"}.__getitem__),
            "/tools/pb/bin/python3",
        )

    def test_none_without_override_or_launcher(self):
        self.assertIsNone(engine_python.resolve({}, lambda _: None, lambda _: ""))


class ChooseTest(unittest.TestCase):
    def _choose(self, env, importable, resolved="/tools/python"):
        return engine_python.choose(env, importable=lambda: importable,
                                    executable="/usr/bin/python3",
                                    resolve_interpreter=lambda _env: resolved)

    def test_override_wins_even_when_current_imports_engine(self):
        self.assertEqual(self._choose({"PROJECT_BRAIN_PYTHON": "/x/python"}, True), "/x/python")

    def test_current_interpreter_when_it_imports_engine(self):
        self.assertEqual(self._choose({}, True), "/usr/bin/python3")

    def test_resolved_launcher_otherwise(self):
        self.assertEqual(self._choose({}, False), "/tools/python")
        self.assertIsNone(self._choose({}, False, resolved=None))

    def test_cli_prints_chosen_interpreter(self):
        env = {key: value for key, value in os.environ.items() if key != engine_python.OVERRIDE}
        env[engine_python.OVERRIDE] = "/x/python"
        result = subprocess.run([sys.executable, str(HERE / "engine_python.py")], env=env,
                                capture_output=True, text=True, check=False)
        self.assertEqual((result.returncode, result.stdout), (0, "/x/python\n"), result.stderr)


class EnsureTest(unittest.TestCase):
    def _ensure(self, *, importable, env, resolved, executable="/usr/bin/python3"):
        calls = []
        engine_python.ensure(
            argv=["/skill/scripts/x.py", "--flag"],
            env=env,
            importable=lambda: importable,
            resolve_interpreter=lambda _env: resolved,
            executable=executable,
            execve=lambda path, args, new_env: calls.append((path, args, new_env)),
        )
        return calls

    def test_no_op_when_engine_is_importable(self):
        self.assertEqual(self._ensure(importable=True, env={}, resolved="/tools/python"), [])

    def test_success_clears_guard_so_child_scripts_can_reexec(self):
        env = {engine_python.GUARD: "1", "KEEP": "1"}
        engine_python.ensure(argv=["x.py"], env=env, importable=lambda: True,
                             resolve_interpreter=lambda _env: None, executable="/p",
                             execve=lambda *args: None)
        self.assertEqual(env, {"KEEP": "1"})

    def test_reexecs_with_engine_python_and_guard(self):
        calls = self._ensure(importable=False, env={"KEEP": "1"}, resolved="/tools/python")
        self.assertEqual(len(calls), 1)
        path, args, new_env = calls[0]
        self.assertEqual(path, "/tools/python")
        self.assertEqual(args, ["/tools/python", "/skill/scripts/x.py", "--flag"])
        self.assertEqual(new_env["KEEP"], "1")
        self.assertEqual(new_env[engine_python.GUARD], "1")

    def test_fails_clearly_when_nothing_resolves(self):
        with self.assertRaises(SystemExit) as raised:
            self._ensure(importable=False, env={}, resolved=None)
        self.assertIn("PROJECT_BRAIN_PYTHON", str(raised.exception.code))

    def test_explicit_override_reexecs_even_when_engine_imports(self):
        calls = self._ensure(importable=True, env={engine_python.OVERRIDE: "/x/python"},
                             resolved="/x/python")
        self.assertEqual([call[0] for call in calls], ["/x/python"])

    def test_override_matching_current_interpreter_is_a_no_op(self):
        self.assertEqual(self._ensure(importable=True,
                                      env={engine_python.OVERRIDE: "/usr/bin/python3"},
                                      resolved="/usr/bin/python3"), [])

    def test_exec_failure_stops_with_reason(self):
        def missing(*_args):
            raise FileNotFoundError("no such file")

        with self.assertRaises(SystemExit) as raised:
            engine_python.ensure(argv=["x.py"], env={}, importable=lambda: False,
                                 resolve_interpreter=lambda _env: "/gone/python",
                                 executable="/usr/bin/python3", execve=missing)
        self.assertIn("/gone/python", str(raised.exception.code))
        self.assertIn("PROJECT_BRAIN_PYTHON", str(raised.exception.code))

    def test_does_not_loop_after_a_reexec(self):
        with self.assertRaises(SystemExit) as raised:
            self._ensure(importable=False, env={engine_python.GUARD: "1"},
                         resolved="/tools/python")
        self.assertIn("/usr/bin/python3", str(raised.exception.code))

    def test_does_not_reexec_into_the_same_interpreter(self):
        with self.assertRaises(SystemExit):
            self._ensure(importable=False, env={}, resolved="/usr/bin/python3")


class ScriptEntryTest(unittest.TestCase):
    """엔진을 import하는 설치 스크립트는 import 전에 engine_python.ensure()를 거친다."""

    ENGINE_SCRIPTS = (
        "assemble_notes.py",
        "finalize_ingest.py",
        "run_ingest_batch.py",
        "validate_foundation.py",
    )

    def test_engine_scripts_bootstrap_before_engine_import(self):
        for name in self.ENGINE_SCRIPTS:
            with self.subTest(script=name):
                text = (HERE / name).read_text(encoding="utf-8")
                bootstrap = text.find("engine_python.ensure()")
                self.assertNotEqual(bootstrap, -1)
                first_import = min(
                    (index for index in (text.find("from project_brain"),
                                         text.find("import project_brain"))
                     if index != -1),
                    default=len(text),
                )
                self.assertLess(bootstrap, first_import)

    def test_engine_scripts_start_under_safe_path_mode(self):
        """-P(PYTHONSAFEPATH)면 스크립트 디렉토리가 sys.path에 없어도 부트스트랩이 동작한다."""
        with tempfile.TemporaryDirectory() as cwd:
            for name in self.ENGINE_SCRIPTS:
                with self.subTest(script=name):
                    result = subprocess.run(
                        [sys.executable, "-P", str(HERE / name), "--help"],
                        cwd=cwd, capture_output=True, text=True, check=False,
                    )
                    # validate_foundation은 --help에도 rc 1 JSON을 내므로 rc가 아니라
                    # 부트스트랩(import) 실패가 없는지로 본다.
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertNotIn("ModuleNotFoundError", result.stderr + result.stdout)

    def test_wrappers_resolve_engine_python_once(self):
        for name in ("run_ingest.sh", "finalize_ingest.sh"):
            with self.subTest(wrapper=name):
                text = (HERE / name).read_text(encoding="utf-8")
                self.assertIn('engine_python.py', text)
                calls = [line for line in text.splitlines()
                         if "python3 " in line and "engine_python.py" not in line]
                self.assertEqual(calls, [])

    def test_script_without_engine_reexecs_into_python_named_by_override(self):
        """engine 없는 인터프리터로 실행해도 PROJECT_BRAIN_PYTHON의 Python에서 끝난다."""
        with tempfile.TemporaryDirectory() as tmp:
            bare_env = {key: value for key, value in os.environ.items()
                        if key not in {"PYTHONPATH", engine_python.GUARD}}
            bare_env["PYTHONNOUSERSITE"] = "1"
            # -I: 격리 모드 — 현재 venv의 site-packages·PYTHONPATH 없이 시작한다.
            probe = Path(tmp) / "probe.py"
            probe.write_text(
                "import sys\n"
                f"sys.path.insert(0, {str(HERE)!r})\n"
                "import engine_python\n"
                "engine_python.ensure()\n"
                "import project_brain\n"
                "print(sys.executable)\n",
                encoding="utf-8",
            )
            bare_env["PROJECT_BRAIN_PYTHON"] = sys.executable
            bare_python = sys._base_executable if hasattr(sys, "_base_executable") \
                else sys.executable
            result = subprocess.run(
                [bare_python, "-I", str(probe)],
                env=bare_env, capture_output=True, text=True, check=False,
            )
        importable_in_bare = subprocess.run(
            [bare_python, "-I", "-c", "import project_brain"],
            capture_output=True, check=False,
        ).returncode == 0
        if importable_in_bare:
            self.skipTest("base interpreter already imports project_brain")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), sys.executable)


if __name__ == "__main__":
    unittest.main()
