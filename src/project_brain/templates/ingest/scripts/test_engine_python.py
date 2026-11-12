"""engine_python — 시스템 python3로 실행된 스크립트가 엔진이 깔린 Python으로 넘어가는 계약."""

import os
import json
import shutil
import venv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import engine_python  # noqa: E402


class SourceLoadingTest(unittest.TestCase):
    def test_runtime_loader_ignores_stale_bytecode(self):
        import py_compile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "helper.py"
            path.write_text("VALUE = 'OLD'\n")
            py_compile.compile(str(path), doraise=True)
            stamp = path.stat()
            path.write_text("VALUE = 'NEW'\n")
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            self.assertEqual(engine_python.load_source(path, "helper_under_test").VALUE, "NEW")

HERE = Path(__file__).resolve().parent


class ResolveTest(unittest.TestCase):
    def test_explicit_override_wins(self):
        self.assertEqual(engine_python.resolve({"PROJECT_BRAIN_PYTHON": "/x/python"}), "/x/python")

    def test_no_global_or_current_interpreter_fallback(self):
        from unittest.mock import patch
        with patch.object(engine_python, "project_root", return_value=None):
            self.assertIsNone(engine_python.resolve({}))


class ChooseTest(unittest.TestCase):
    def _choose(self, env, importable, resolved="/tools/python"):
        return engine_python.choose(env, importable=lambda: importable,
                                    executable="/usr/bin/python3",
                                    resolve_interpreter=lambda _env: resolved)

    def test_override_wins_even_when_current_imports_engine(self):
        self.assertEqual(self._choose({"PROJECT_BRAIN_PYTHON": "/x/python"}, True), "/x/python")

    def test_project_release_wins_when_current_imports_engine(self):
        self.assertEqual(self._choose({}, True), "/tools/python")

    def test_missing_release_never_uses_current_engine(self):
        self.assertEqual(self._choose({}, False), "/tools/python")
        self.assertIsNone(self._choose({}, True, resolved=None))

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

    def test_project_release_reexecs_when_current_engine_is_importable(self):
        calls = self._ensure(importable=True, env={}, resolved="/tools/python")
        self.assertEqual([call[0] for call in calls], ["/tools/python"])

    def test_success_clears_guard_so_child_scripts_can_reexec(self):
        env = {engine_python.GUARD: "1", engine_python.OVERRIDE: "/p", "KEEP": "1"}
        engine_python.ensure(argv=["x.py"], env=env, importable=lambda: True,
                             resolve_interpreter=lambda _env: None, executable="/p",
                             execve=lambda *args: None)
        self.assertEqual(env, {engine_python.OVERRIDE: "/p", "KEEP": "1"})

    def test_reexecs_with_engine_python_and_guard(self):
        calls = self._ensure(importable=False, env={"KEEP": "1"}, resolved="/tools/python")
        self.assertEqual(len(calls), 1)
        path, args, new_env = calls[0]
        self.assertEqual(path, "/tools/python")
        self.assertEqual(args, ["/tools/python", "-I", "-B", "/skill/scripts/x.py", "--flag"])
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

    def test_same_implicit_interpreter_reexecs_in_isolation(self):
        calls = self._ensure(importable=False, env={}, resolved="/usr/bin/python3")
        self.assertEqual(calls[0][1][1:3], ["-I", "-B"])


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
                bootstrap = text.find('["ensure"]()')
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


SCRIPTS = HERE


class CheckoutReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "checkout with spaces"
        self.scripts = self.root / ".agents/bundles/brain/bb2-brain-ingest/scripts"
        self.scripts.mkdir(parents=True)
        for source in SCRIPTS.iterdir():
            if source.name != Path(__file__).name and source.suffix in {".py", ".sh"}:
                shutil.copy2(source, self.scripts / source.name)
        pin = self.root / ".project-brain.json"
        pin.write_text('{"version": "test"}\n')
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.env = {key: value for key, value in os.environ.items()
                    if key not in {"PROJECT_BRAIN_PYTHON", "PROJECT_BRAIN_ENGINE_REEXEC",
                                   "PYTHONPATH", "PYTHONHOME"}}
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.tools = self.base / "tools"
        self.tools.mkdir()
        (self.tools / "python3").symlink_to(sys.executable)
        # 시스템 도구만 노출하며 사용자의 전역 project-brain은 제외한다.
        self.env["PATH"] = str(self.tools) + os.pathsep + os.defpath
        self.probe = self.scripts / "probe.py"
        self.probe.write_text(
            "import json, os, runpy, subprocess, sys\n"
            "from pathlib import Path\n"
            "runpy.run_path(str(Path(__file__).with_name('engine_python.py')))['ensure']()\n"
            "import project_brain\n"
            "print(json.dumps({'engine': project_brain.VERSION, 'python': sys.executable,\n"
            " 'cli': subprocess.check_output(['project-brain', '--version'], text=True).strip(),\n"
            " 'override': os.environ.get('PROJECT_BRAIN_PYTHON'),\n"
            " 'pythonpath': os.environ.get('PYTHONPATH'),\n"
            " 'pythonhome': os.environ.get('PYTHONHOME')}))\n"
        )

    def install_engine(self, directory: Path, label: str) -> Path:
        venv.EnvBuilder(with_pip=False, symlinks=True).create(directory)
        python = directory / "bin/python"
        result = subprocess.run(
            [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            text=True, capture_output=True, check=True,
        )
        package = Path(result.stdout.strip()) / "project_brain"
        package.mkdir()
        (package / "__init__.py").write_text(f"VERSION = {label!r}\n")
        return python

    def install_release(self) -> Path:
        python = self.install_engine(self.root / ".local/brain-tools/project-brain", "checkout")
        launcher = self.root / ".local/brain-bin/project-brain"
        launcher.parent.mkdir(parents=True)
        cli = python.with_name("project-brain")
        cli.write_text("#!/bin/sh\nprintf '%s\\n' checkout-cli\n")
        cli.chmod(0o755)
        launcher.symlink_to(cli)
        return python

    def install_global(self) -> Path:
        python = self.install_engine(self.base / "global-tools", "global")
        launcher = self.tools / "project-brain"
        launcher.write_text(f"#!{python}\nprint('global-cli')\n")
        launcher.chmod(0o755)
        return python

    def run_script(self, script: Path, *args: str, python: Path | str = sys.executable):
        return subprocess.run([str(python), "-B", str(script), *args],
                              cwd=self.base, env=self.env, text=True, capture_output=True)

    def assert_checkout(self, result, python):
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload, {
            "engine": "checkout", "python": str(python), "cli": "checkout-cli",
            "override": None, "pythonpath": None, "pythonhome": None,
        })

    def test_direct_python_without_global_engine(self):
        python = self.install_release()
        self.assert_checkout(self.run_script(self.probe), python)

    def test_checkout_wins_over_global_interpreter_and_pythonpath(self):
        python = self.install_release()
        global_python = self.install_global()
        poison = self.base / "injected"
        poison.mkdir()
        (poison / "project_brain.py").write_text("VERSION = 'injected'\n")
        self.env["PYTHONPATH"] = str(poison)
        self.assert_checkout(self.run_script(self.probe, python=global_python), python)

    def test_same_release_python_restarts_without_injected_module(self):
        python = self.install_release()
        poison = self.base / "injected"
        poison.mkdir()
        (poison / "project_brain.py").write_text("VERSION = 'injected'\n")
        self.env["PYTHONPATH"] = str(poison)
        self.assert_checkout(self.run_script(self.probe, python=python), python)

    def test_resolver_uses_own_checkout_when_cwd_is_another_checkout(self):
        python = self.install_release()
        other = self.base / "other-checkout"
        (other / "scripts/agents").mkdir(parents=True)
        (other / ".project-brain.json").write_text('{}\n')
        self.assert_checkout(subprocess.run(
            [sys.executable, "-B", str(self.probe)], cwd=other, env=self.env,
            text=True, capture_output=True,
        ), python)

    def test_missing_release_exits_with_prepare_for_python_entrypoints(self):
        for global_engine in (False, True):
            if global_engine:
                self.install_global()
            for name in ("engine_python.py", "run_ingest_batch.py", "assemble_notes.py",
                         "validate_foundation.py", "finalize_ingest.py"):
                with self.subTest(global_engine=global_engine, script=name):
                    result = self.run_script(self.scripts / name, "--help")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("prepare/설치", result.stderr)
                    self.assertNotIn("global-cli", result.stdout)

    def test_partial_release_is_not_accepted(self):
        python = self.install_release()
        for missing in (python.with_name("project-brain"), python):
            with self.subTest(missing=missing):
                saved = missing.with_name(missing.name + ".saved")
                missing.rename(saved)
                try:
                    result = self.run_script(self.probe)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("prepare/설치", result.stderr)
                finally:
                    saved.rename(missing)

    def test_shell_wrappers_without_release_never_fall_back(self):
        for global_engine in (False, True):
            if global_engine:
                self.install_global()
            for name, args in (("run_ingest.sh", ["--dry", "verify.json", "spec.py"]),
                               ("finalize_ingest.sh", ["--help"])):
                with self.subTest(global_engine=global_engine, script=name):
                    result = subprocess.run(
                        ["/bin/bash", str(self.scripts / name), *args], cwd=self.base,
                        env=self.env, text=True, capture_output=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("prepare/설치", result.stderr)
                    self.assertNotIn("global-cli", result.stdout)

    def test_shell_wrapper_passes_checkout_engine_and_sanitized_environment(self):
        python = self.install_release()
        global_python = self.install_global()
        self.env["PYTHONPATH"] = "/unused/injected"
        # 래퍼 경계만 확인하며 실제 ingest/finalize는 실행하지 않는다.
        shutil.copy2(self.probe, self.scripts / "finalize_ingest.py")
        result = subprocess.run(
            ["/bin/bash", str(self.scripts / "finalize_ingest.sh")], cwd=self.base,
            env=self.env, text=True, capture_output=True,
        )
        self.assert_checkout(result, python)


    def test_explicit_override_remains_supported(self):
        self.install_release()
        global_python = self.install_global()
        self.env["PROJECT_BRAIN_PYTHON"] = str(global_python)
        result = self.run_script(self.probe)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["engine"], "global")
        self.assertEqual(payload["python"], str(global_python))
        self.assertEqual(payload["override"], str(global_python))


if __name__ == "__main__":
    unittest.main()
