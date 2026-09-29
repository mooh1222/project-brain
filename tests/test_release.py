"""tools/release.py — release artifact 검사의 결정론 부분(합성 wheel·git 저장소)."""

import hashlib
import importlib.util
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "release.py"
_spec = importlib.util.spec_from_file_location("release_tool", _TOOL)
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _write_wheel(path: Path, members: dict[str, int], *, version: str = "0.1.0",
                 entry_points: str | None = None) -> Path:
    """members: wheel 안 경로 → unix mode. METADATA·entry_points는 자동 추가."""
    dist_info = f"project_brain-{version}.dist-info"
    if entry_points is None:
        entry_points = "[console_scripts]\nproject-brain = project_brain.cli:main\n"
    with zipfile.ZipFile(path, "w") as archive:
        for name, mode in members.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, b"x")
        archive.writestr(
            f"{dist_info}/METADATA",
            f"Metadata-Version: 2.4\nName: project-brain\nVersion: {version}\n",
        )
        archive.writestr(f"{dist_info}/entry_points.txt", entry_points)
    return path


def _template_repo(root: Path) -> Path:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    templates = root / "src" / "project_brain" / "templates" / "ingest"
    (templates / "scripts").mkdir(parents=True)
    (templates / "SKILL.md").write_text("skill")
    runner = templates / "scripts" / "run.sh"
    runner.write_text("#!/bin/sh\n")
    runner.chmod(0o755)
    (templates / "scripts" / "__pycache__").mkdir()
    (templates / "scripts" / "__pycache__" / "x.pyc").write_bytes(b"")
    (root / "pyproject.toml").write_text('[project]\nname = "project-brain"\nversion = "0.1.0"\n')
    _git(root, "add", "pyproject.toml", "src/project_brain/templates/ingest/SKILL.md",
         "src/project_brain/templates/ingest/scripts/run.sh")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "tag", "v0.1.0")
    return root


class TestTrackedTemplateModes(unittest.TestCase):
    EXPECTED = {
        "project_brain/templates/ingest/SKILL.md": False,
        "project_brain/templates/ingest/scripts/run.sh": True,
    }

    def test_reads_committed_paths_and_executable_bits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _template_repo(Path(tmp))
            self.assertEqual(release.tracked_template_modes(root, "HEAD"), self.EXPECTED)

    def test_reads_the_requested_revision_not_later_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _template_repo(Path(tmp))
            extra = root / "src/project_brain/templates/ingest/scripts/new.sh"
            extra.write_text("#!/bin/sh\n")
            extra.chmod(0o755)
            _git(root, "add", str(extra.relative_to(root)))
            _git(root, "commit", "-q", "-m", "later")

            self.assertEqual(release.tracked_template_modes(root, "v0.1.0"), self.EXPECTED)
            self.assertIn("project_brain/templates/ingest/scripts/new.sh",
                          release.tracked_template_modes(root, "HEAD"))


class TestBuildFailureLeavesNoArtifacts(unittest.TestCase):
    def test_failed_artifact_check_does_not_create_output_directory(self):
        def fake_produce(repo_root, staging, version):
            _write_wheel(staging / release.wheel_name(version), {})  # 템플릿 없는 wheel
            (staging / release.constraints_name(version)).write_text("numpy==2.3.2\n")

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "repo").mkdir()
            root = _template_repo(Path(tmp) / "repo")
            out = Path(tmp) / "out"
            original = release._produce_artifacts
            release._produce_artifacts = fake_produce
            try:
                with self.assertRaises(release.ReleaseError):
                    release.build("v0.1.0", out, repo_root=root)
            finally:
                release._produce_artifacts = original
            self.assertFalse((out / "v0.1.0").exists())

    def test_successful_build_moves_checked_artifacts_with_checksums(self):
        def fake_produce(repo_root, staging, version):
            _write_wheel(staging / release.wheel_name(version), {
                "project_brain/cli.py": 0o644,
                "project_brain/templates/ingest/SKILL.md": 0o644,
                "project_brain/templates/ingest/scripts/run.sh": 0o755,
            })
            (staging / release.constraints_name(version)).write_text("numpy==2.3.2\n")

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "repo").mkdir()
            root = _template_repo(Path(tmp) / "repo")
            out = Path(tmp) / "out"
            original = release._produce_artifacts
            release._produce_artifacts = fake_produce
            try:
                report = release.build("v0.1.0", out, repo_root=root)
            finally:
                release._produce_artifacts = original
            release_dir = out / "v0.1.0"
            self.assertTrue(report["ok"])
            self.assertEqual(sorted(p.name for p in release_dir.iterdir()), [
                release.CHECKSUMS_NAME,
                release.constraints_name("0.1.0"),
                release.wheel_name("0.1.0"),
            ])
            self.assertEqual(release.checksum_problems(release_dir / release.CHECKSUMS_NAME), [])


class TestRecordMatch(unittest.TestCase):
    WHEEL_RECORD = (
        "project_brain/cli.py,sha256=AAA,10\n"
        "project_brain/templates/ingest/SKILL.md,sha256=BBB,5\n"
        "project_brain-0.1.0.dist-info/RECORD,,\n"
    )

    def test_installed_package_files_match_verified_wheel(self):
        installed = self.WHEEL_RECORD + "../../../bin/project-brain,sha256=ZZZ,1\n"
        self.assertEqual(release.record_problems(self.WHEEL_RECORD, installed), [])

    def test_reports_file_with_different_hash(self):
        installed = self.WHEEL_RECORD.replace("sha256=AAA", "sha256=XXX")
        self.assertEqual(release.record_problems(self.WHEEL_RECORD, installed),
                         ["installed file differs from verified wheel: project_brain/cli.py"])

    def test_reports_file_missing_from_install(self):
        installed = "project_brain/cli.py,sha256=AAA,10\n"
        self.assertEqual(release.record_problems(self.WHEEL_RECORD, installed), [
            "installed file differs from verified wheel: "
            "project_brain/templates/ingest/SKILL.md",
        ])


class TestInstalledModes(unittest.TestCase):
    def test_reports_destination_whose_executable_bit_differs_from_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            skill = project / ".agents/skills/smoke-brain-ingest/scripts"
            skill.mkdir(parents=True)
            (skill / "run.sh").write_text("")
            (skill / "run.sh").chmod(0o644)
            (skill / "lib.py").write_text("")
            (skill / "lib.py").chmod(0o644)
            desired = {
                ".agents/skills/smoke-brain-ingest/scripts/run.sh": True,
                ".agents/skills/smoke-brain-ingest/scripts/lib.py": False,
                ".agents/skills/smoke-brain-ingest/scripts/gone.sh": True,
            }
            self.assertEqual(release.installed_mode_problems(desired, project), [
                "installed file missing: .agents/skills/smoke-brain-ingest/scripts/gone.sh",
                "installed executable bit differs from template: "
                ".agents/skills/smoke-brain-ingest/scripts/run.sh",
            ])


class TestMainErrorReport(unittest.TestCase):
    def test_bytes_stderr_from_git_is_reported_as_json(self):
        import io
        import json
        from contextlib import redirect_stderr

        def fail(*args, **kwargs):
            raise subprocess.CalledProcessError(128, ["git"], stderr=b"fatal: no HEAD")

        original = release.build
        release.build = fail
        err = io.StringIO()
        try:
            with redirect_stderr(err):
                code = release.main(["build", "--tag", "v0.1.0"])
        finally:
            release.build = original
        self.assertEqual(code, 1)
        payload = json.loads(err.getvalue())
        self.assertIn("fatal: no HEAD", payload["error"])


class TestInspectWheel(unittest.TestCase):
    EXPECTED = {
        "project_brain/templates/ingest/SKILL.md": False,
        "project_brain/templates/ingest/scripts/run.sh": True,
    }

    def _members(self, **overrides):
        members = {
            "project_brain/__init__.py": 0o644,
            "project_brain/cli.py": 0o644,
            "project_brain/templates/ingest/SKILL.md": 0o644,
            "project_brain/templates/ingest/scripts/run.sh": 0o755,
        }
        members.update(overrides)
        return {name: mode for name, mode in members.items() if mode is not None}

    def _inspect(self, members, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            wheel = _write_wheel(Path(tmp) / "w.whl", members, **kwargs)
            return release.inspect_wheel(wheel, self.EXPECTED, "0.1.0")

    def test_complete_wheel_has_no_problems(self):
        self.assertEqual(self._inspect(self._members()), [])

    def test_reports_missing_template(self):
        problems = self._inspect(self._members(**{
            "project_brain/templates/ingest/SKILL.md": None,
        }))
        self.assertEqual(problems, [
            "missing template: project_brain/templates/ingest/SKILL.md",
        ])

    def test_reports_untracked_template_payload(self):
        problems = self._inspect(self._members(**{
            "project_brain/templates/ingest/scripts/__pycache__/run.cpython-312.pyc": 0o644,
        }))
        self.assertEqual(problems, [
            "untracked template: "
            "project_brain/templates/ingest/scripts/__pycache__/run.cpython-312.pyc",
        ])

    def test_reports_lost_executable_bit(self):
        problems = self._inspect(self._members(**{
            "project_brain/templates/ingest/scripts/run.sh": 0o644,
        }))
        self.assertEqual(problems, [
            "executable bit mismatch: project_brain/templates/ingest/scripts/run.sh "
            "(expected executable)",
        ])

    def test_reports_unexpected_executable_bit(self):
        problems = self._inspect(self._members(**{
            "project_brain/templates/ingest/SKILL.md": 0o755,
        }))
        self.assertEqual(problems, [
            "executable bit mismatch: project_brain/templates/ingest/SKILL.md "
            "(expected non-executable)",
        ])

    def test_reports_version_mismatch(self):
        problems = self._inspect(self._members(), version="0.2.0")
        self.assertIn("metadata version 0.2.0 != release version 0.1.0", problems)

    def test_reports_missing_cli_entrypoint(self):
        problems = self._inspect(self._members(), entry_points="[console_scripts]\n")
        self.assertEqual(problems, [
            "missing console script: project-brain = project_brain.cli:main",
        ])

    def test_reports_missing_cli_module(self):
        problems = self._inspect(self._members(**{"project_brain/cli.py": None}))
        self.assertEqual(problems, ["missing module: project_brain/cli.py"])


class TestConstraints(unittest.TestCase):
    def test_pinned_constraints_pass(self):
        text = (
            "# header\n"
            "numpy==2.3.2\n"
            "    # via project-brain\n"
            "torch==2.8.0 ; sys_platform == 'darwin'\n"
        )
        self.assertEqual(release.constraint_problems(text), [])

    def test_reports_unpinned_and_self_reference(self):
        text = "numpy>=2\n-e .\nproject-brain==0.1.0\n"
        self.assertEqual(release.constraint_problems(text), [
            "unpinned constraint: numpy>=2",
            "unpinned constraint: -e .",
            "constraints must not pin project-brain itself",
        ])

    def test_empty_constraints_are_rejected(self):
        self.assertEqual(release.constraint_problems("# only comments\n"),
                         ["constraints file has no pins"])


class TestInstalledVersions(unittest.TestCase):
    CONSTRAINTS = (
        "numpy==2.4.6 ; python_full_version < '3.12'\n"
        "    # via project-brain\n"
        "numpy==2.5.1 ; python_full_version >= '3.12'\n"
        "kiwipiepy==0.23.2\n"
        "colorama==0.4.6 ; sys_platform == 'win32'\n"
    )

    @staticmethod
    def _py312(marker: str) -> bool:
        return {
            "python_full_version < '3.12'": False,
            "python_full_version >= '3.12'": True,
            "sys_platform == 'win32'": False,
        }[marker]

    def _problems(self, installed):
        return release.installed_version_problems(self.CONSTRAINTS, installed, self._py312)

    def test_installed_pins_match_applicable_markers(self):
        installed = {"numpy": "2.5.1", "kiwipiepy": "0.23.2", "project-brain": "0.1.0"}
        self.assertEqual(self._problems(installed), [])

    def test_reports_version_drift(self):
        installed = {"numpy": "2.4.6", "Kiwipiepy": "0.23.2"}
        self.assertEqual(self._problems(installed),
                         ["installed numpy 2.4.6 != constrained 2.5.1"])

    def test_reports_applicable_pin_that_is_not_installed(self):
        self.assertEqual(self._problems({"numpy": "2.5.1"}),
                         ["constrained kiwipiepy 0.23.2 is not installed"])

    def test_marker_evaluator_receives_marker_text_only(self):
        seen = []
        release.installed_version_problems(
            "a==1 ; os_name == 'nt'\n", {}, lambda marker: seen.append(marker) or False)
        self.assertEqual(seen, ["os_name == 'nt'"])


class TestChecksums(unittest.TestCase):
    def test_write_then_verify_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wheel = root / "a.whl"
            wheel.write_bytes(b"wheel")
            constraints = root / "c.txt"
            constraints.write_bytes(b"pins")

            sums = release.write_checksums([wheel, constraints], root / "SHA256SUMS")

            self.assertEqual(sums.read_text(), (
                f"{hashlib.sha256(b'wheel').hexdigest()}  a.whl\n"
                f"{hashlib.sha256(b'pins').hexdigest()}  c.txt\n"
            ))
            self.assertEqual(release.checksum_problems(sums), [])

    def test_reports_mismatch_and_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.whl").write_bytes(b"wheel")
            (root / "c.txt").write_bytes(b"pins")
            sums = release.write_checksums([root / "a.whl", root / "c.txt"],
                                           root / "SHA256SUMS")
            (root / "a.whl").write_bytes(b"tampered")
            (root / "c.txt").unlink()

            self.assertEqual(release.checksum_problems(sums), [
                "checksum mismatch: a.whl",
                "missing file: c.txt",
            ])

    def test_empty_checksum_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            sums = Path(tmp) / "SHA256SUMS"
            sums.write_text("")
            self.assertEqual(release.checksum_problems(sums),
                             ["checksum file lists no artifacts"])


class TestInstallReport(unittest.TestCase):
    def test_second_install_must_not_change_anything(self):
        clean = {"ok": True, "created": [], "updated": [], "removed": [],
                 "adopted": [], "skipped": []}
        self.assertEqual(release.idempotent_install_problems(clean), [])

        dirty = {**clean, "updated": ["a"], "created": ["b"]}
        self.assertEqual(release.idempotent_install_problems(dirty), [
            "second install created: ['b']",
            "second install updated: ['a']",
        ])

    def test_missing_report_key_is_a_problem(self):
        self.assertEqual(
            release.idempotent_install_problems({"ok": True, "created": []}),
            [
                "second install report lacks updated",
                "second install report lacks removed",
                "second install report lacks adopted",
                "second install report lacks skipped",
            ],
        )


class TestReleaseNames(unittest.TestCase):
    def test_artifact_names_follow_version(self):
        self.assertEqual(release.wheel_name("0.1.0"), "project_brain-0.1.0-py3-none-any.whl")
        self.assertEqual(release.constraints_name("0.1.0"),
                         "project-brain-0.1.0-constraints.txt")

    def test_tag_must_be_v_prefixed_version(self):
        self.assertEqual(release.version_from_tag("v0.1.0"), "0.1.0")
        with self.assertRaises(ValueError):
            release.version_from_tag("0.1.0")


if __name__ == "__main__":
    unittest.main()
