"""install — 프로젝트에 config + 스킬 4종을 멱등 설치하고 manifest로 추적한다.

파일 단위 보존 모델: manifest에 기록된 해시와 디스크가 일치할 때만 갱신(도구 소유),
불일치(사용자 수정)·manifest 밖(사용자 소유)은 건드리지 않고 보고한다 —
hwi_PKM manifest 멱등 패턴의 파일 단위 적용.
"""
from __future__ import annotations

import json
import hashlib
import stat
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from project_brain.config import CONFIG_FILENAME
from project_brain.installer import (
    InstallConflictError,
    MANIFEST_FILENAME,
    install,
    normalize_installer_report_path,
    render_text,
)


ROOT = Path(__file__).resolve().parents[1]


class RenderTextTest(unittest.TestCase):
    def test_substitutes_project_and_brain_root(self):
        out = render_text("name: {{PROJECT}}-brain-query → {{BRAIN_ROOT}}/x",
                          project="demo", brain_root="knowledge")
        self.assertEqual(out, "name: demo-brain-query → knowledge/x")
        self.assertNotIn("{{PROJECT}}", out)
        self.assertNotIn("{{BRAIN_ROOT}}", out)

    def test_render_text_substitutes_branch_and_repo(self):
        out = render_text("{{REPO}}@{{DEFAULT_BRANCH}} for {{PROJECT}}",
                          project="demo", brain_root="brain",
                          default_branch="main", repo="myrepo")
        self.assertEqual(out, "myrepo@main for demo")


class InstallTest(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.target = Path(self._td.name).resolve()

    def tearDown(self):
        self._td.cleanup()

    def _skill_dir(self, name):
        return self.target / ".agents" / "skills" / name

    def _skill(self, name):
        return self._skill_dir(name) / "SKILL.md"

    def _expected_count(self):
        import project_brain.installer as inst
        n = 0
        for skill in inst._SKILLS:
            root = inst._TEMPLATES_DIR / skill
            if not root.is_dir():
                continue
            for src in root.rglob("*"):
                if src.is_file() and not inst._excluded(src.relative_to(root)):
                    n += 1
        return n

    def _manifest(self):
        return json.loads(
            (self.target / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )

    def _write_manifest(self, manifest):
        (self.target / MANIFEST_FILENAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _record_retired(self, rel_key, managed_content=b"managed\n", *, create=True):
        manifest = self._manifest()
        manifest["files"][rel_key] = hashlib.sha256(managed_content).hexdigest()
        self._write_manifest(manifest)
        path = self.target / rel_key
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(managed_content)
        return path

    def _assert_no_retirement_artifacts(self):
        self.assertEqual(list(self.target.rglob(".*.tmp")), [])
        self.assertEqual(list(self.target.rglob(".*.retired-*.bak")), [])

    def test_walk_injects_references_and_scripts(self):
        # 합성 템플릿: query 스킬에 references/scripts와 제외 대상까지 둔다.
        import project_brain.installer as inst
        tdir = Path(self._td.name) / "fake_templates"
        q = tdir / "query"
        (q / "references").mkdir(parents=True)
        (q / "scripts" / "fixtures").mkdir(parents=True)
        (q / "scripts" / "__pycache__").mkdir(parents=True)
        (q / "SKILL.md").write_text("name: {{PROJECT}}-brain-query\n", encoding="utf-8")
        (q / "references" / "guide.md").write_text("see {{PROJECT}}\n", encoding="utf-8")
        (q / "scripts" / "run.sh").write_text("echo {{PROJECT}}\n", encoding="utf-8")
        (q / "scripts" / "test_run.py").write_text("# dev test\n", encoding="utf-8")
        (q / "scripts" / "fixtures" / "data.py").write_text("X = 1\n", encoding="utf-8")
        (q / "scripts" / "__pycache__" / "x.pyc").write_text("junk\n", encoding="utf-8")
        orig_dir, orig_skills = inst._TEMPLATES_DIR, inst._SKILLS
        inst._TEMPLATES_DIR, inst._SKILLS = tdir, {"query": "brain-query"}
        try:
            install(self.target, project="demo")
        finally:
            inst._TEMPLATES_DIR, inst._SKILLS = orig_dir, orig_skills
        base = self._skill_dir("demo-brain-query")
        self.assertEqual((base / "SKILL.md").read_text(encoding="utf-8"),
                         "name: demo-brain-query\n")
        self.assertEqual((base / "references" / "guide.md").read_text(encoding="utf-8"),
                         "see demo\n")
        self.assertEqual((base / "scripts" / "run.sh").read_text(encoding="utf-8"),
                         "echo demo\n")
        # 제외: test_*.py · fixtures/ · __pycache__
        self.assertFalse((base / "scripts" / "test_run.py").exists())
        self.assertFalse((base / "scripts" / "fixtures").exists())
        self.assertFalse((base / "scripts" / "__pycache__").exists())

    def test_tool_owned_update_preserves_executable_template_mode(self):
        import project_brain.installer as inst
        tdir = Path(self._td.name) / "fake_executable_templates"
        script = tdir / "query" / "scripts" / "run.sh"
        script.parent.mkdir(parents=True)
        script.write_text("echo first\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        orig_dir, orig_skills = inst._TEMPLATES_DIR, inst._SKILLS
        inst._TEMPLATES_DIR, inst._SKILLS = tdir, {"query": "brain-query"}
        try:
            install(self.target, project="demo")
            installed = self._skill_dir("demo-brain-query") / "scripts" / "run.sh"
            self.assertTrue(installed.stat().st_mode & stat.S_IXUSR)

            script.write_text("echo updated\n", encoding="utf-8")
            install(self.target, project="demo")
            self.assertEqual(installed.read_text(encoding="utf-8"), "echo updated\n")
            self.assertTrue(installed.stat().st_mode & stat.S_IXUSR)
        finally:
            inst._TEMPLATES_DIR, inst._SKILLS = orig_dir, orig_skills

    def test_executable_mode_changes_only_for_tool_owned_template_writes(self):
        import project_brain.installer as inst
        tdir = Path(self._td.name) / "fake_mode_templates"
        script = tdir / "query" / "scripts" / "run.sh"
        script.parent.mkdir(parents=True)
        script.write_text("echo v1\n", encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        orig_dir, orig_skills = inst._TEMPLATES_DIR, inst._SKILLS
        inst._TEMPLATES_DIR, inst._SKILLS = tdir, {"query": "brain-query"}
        try:
            tracked_target = self.target / "tracked"
            tracked_target.mkdir()
            install(tracked_target, project="demo")
            tracked = tracked_target / ".agents" / "skills" / "demo-brain-query" / "scripts" / "run.sh"
            self.assertTrue(tracked.stat().st_mode & stat.S_IXUSR)  # fresh

            script.write_text("echo v2\n", encoding="utf-8")
            tracked.chmod(tracked.stat().st_mode & ~stat.S_IXUSR)
            install(tracked_target, project="demo")
            self.assertTrue(tracked.stat().st_mode & stat.S_IXUSR)  # tracked update

            tracked.write_text("user edit\n", encoding="utf-8")
            tracked.chmod(tracked.stat().st_mode & ~stat.S_IXUSR)
            install(tracked_target, project="demo", force=True)
            self.assertTrue(tracked.stat().st_mode & stat.S_IXUSR)  # force update

            adopted_target = self.target / "adopted"
            adopted_target.mkdir()
            adopted = adopted_target / ".agents" / "skills" / "demo-brain-query" / "scripts" / "run.sh"
            adopted.parent.mkdir(parents=True)
            adopted.write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
            adopted.chmod(adopted.stat().st_mode & ~stat.S_IXUSR)
            adopted_report = install(adopted_target, project="demo")
            self.assertTrue(adopted.stat().st_mode & stat.S_IXUSR)  # matching untracked adopt
            self.assertIn(
                adopted.relative_to(adopted_target).as_posix(),
                adopted_report["adopted"],
            )
            second_adopt = install(adopted_target, project="demo")
            for field in ("created", "updated", "removed", "adopted", "skipped"):
                self.assertEqual(second_adopt[field], [])

            skipped_target = self.target / "skipped"
            skipped_target.mkdir()
            skipped = skipped_target / ".agents" / "skills" / "demo-brain-query" / "scripts" / "run.sh"
            skipped.parent.mkdir(parents=True)
            skipped.write_text("user edit\n", encoding="utf-8")
            skipped.chmod(skipped.stat().st_mode & ~stat.S_IXUSR)
            install(skipped_target, project="demo")
            self.assertFalse(skipped.stat().st_mode & stat.S_IXUSR)  # user-owned skipped
        finally:
            inst._TEMPLATES_DIR, inst._SKILLS = orig_dir, orig_skills

    def test_fresh_install_creates_config_skills_manifest(self):
        report = install(self.target, project="demo")
        # config 생성 + project 기록
        cfg = json.loads((self.target / CONFIG_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(cfg["project"], "demo")
        self.assertEqual(cfg["brain_root"], "brain")
        # 스킬 4종 렌더 주입
        query = self._skill("demo-brain-query").read_text(encoding="utf-8")
        self.assertIn("name: demo-brain-query", query)
        self.assertTrue(self._skill("demo-brain-ingest").exists())
        self.assertTrue(self._skill("demo-brain-session-ingest").exists())
        self.assertTrue(self._skill("demo-brain-audit").exists())
        # manifest에 심은 파일 기록 — 키는 target 기준 상대 경로(머신 이식성)
        manifest = json.loads(
            (self.target / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(len(manifest["files"]), self._expected_count())
        for key in manifest["files"]:
            self.assertFalse(Path(key).is_absolute(), key)
            self.assertTrue((self.target / key).exists(), key)
        self.assertEqual(report["config"], "created")
        self.assertEqual(len(report["created"]), self._expected_count())

    def test_report_paths_are_target_relative_and_control_paths_track_writes(self):
        first = install(
            self.target,
            project="demo",
            brain_root="brain",
            default_branch="develop",
            repo="demo_client",
        )
        self.assertEqual(first["target_root"], str(self.target))
        self.assertEqual(
            first["installer_control_paths"],
            [MANIFEST_FILENAME, CONFIG_FILENAME],
        )
        for field in ("created", "updated", "removed", "adopted", "skipped"):
            for value in first[field]:
                self.assertFalse(Path(value).is_absolute(), (field, value))
                self.assertEqual(value, Path(value).as_posix())

        second = install(
            self.target,
            project="demo",
            brain_root="brain",
            default_branch="develop",
            repo="demo_client",
        )
        self.assertEqual(second["installer_control_paths"], [MANIFEST_FILENAME])
        for field in ("created", "updated", "removed", "adopted", "skipped"):
            self.assertEqual(second[field], [], field)

    def test_normalize_installer_report_path_accepts_legacy_internal_absolute(self):
        relative = ".agents/skills/demo-brain-ingest/SKILL.md"
        self.assertEqual(
            normalize_installer_report_path(self.target, relative),
            relative,
        )
        self.assertEqual(
            normalize_installer_report_path(self.target, str(self.target / relative)),
            relative,
        )

    def test_normalize_installer_report_path_rejects_escape_empty_and_parent_symlink(self):
        outside = self.target.parent / "outside"
        outside.mkdir(exist_ok=True)
        linked = self.target / ".agents"
        linked.symlink_to(outside, target_is_directory=True)
        for value in ("", "../outside", str(outside / "file"), ".agents/file"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    InstallConflictError,
                    "installer report path",
                ):
                    normalize_installer_report_path(self.target, value)

    def test_real_skill_install_is_idempotent_and_uses_engine_templates(self):
        first = install(self.target, project="demo", default_branch="trunk")
        second = install(self.target, project="demo", default_branch="trunk")
        audit = self._skill("demo-brain-audit").read_text(encoding="utf-8")
        ingest_tools = (
            self._skill_dir("demo-brain-ingest") / "references" / "ingest-tools.md"
        ).read_text(encoding="utf-8")

        self.assertTrue(first["created"])
        for field in ("created", "updated", "removed", "adopted", "skipped"):
            self.assertEqual(second[field], [], field)
        self.assertIn("stale.target_head", audit)
        self.assertIn("trunk", audit)
        self.assertNotIn("{{DEFAULT_BRANCH}}", audit)
        self.assertIn("session-snapshot filtering은 Project Brain install 범위 밖", ingest_tools)

    def test_glossary_criterion_installs_once_is_idempotent_and_preserves_user_edit(self):
        install(self.target, project="demo")
        criterion = (
            self._skill_dir("demo-brain-ingest")
            / "references"
            / "glossary-criteria.md"
        )
        second = install(self.target, project="demo")

        self.assertTrue(criterion.is_file())
        self.assertEqual(
            list((self.target / ".agents" / "skills").rglob("glossary-criteria.md")),
            [criterion],
        )
        for field in ("created", "updated", "removed", "adopted", "skipped"):
            self.assertEqual(second[field], [], field)

        user_content = criterion.read_text(encoding="utf-8") + "\n사용자 보충 기준\n"
        criterion.write_text(user_content, encoding="utf-8")
        third = install(self.target, project="demo")

        relative = criterion.relative_to(self.target).as_posix()
        self.assertIn(relative, third["skipped"])
        self.assertEqual(criterion.read_text(encoding="utf-8"), user_content)

    def test_p0_bb2_install_reports_exact_controls_and_installs_only_runtime_script(self):
        config = {
            "project": "bb2",
            "brain_root": "brain",
            "default_branch": "develop",
            "repo": "bb2_client",
        }
        (self.target / CONFIG_FILENAME).write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        first = install(
            self.target,
            project="bb2",
            brain_root="brain",
            default_branch="develop",
            repo="bb2_client",
        )
        second = install(
            self.target,
            project="bb2",
            brain_root="brain",
            default_branch="develop",
            repo="bb2_client",
        )
        scripts = self._skill_dir("bb2-brain-ingest") / "scripts"
        runtime = scripts / "validate_foundation.py"
        self.assertTrue(runtime.is_file())
        self.assertTrue(runtime.stat().st_mode & stat.S_IXUSR)
        self.assertFalse((scripts / "test_validate_foundation.py").exists())
        manifest = self._manifest()["files"]
        runtime_relative = runtime.relative_to(self.target).as_posix()
        self.assertEqual(
            manifest[runtime_relative],
            hashlib.sha256(runtime.read_bytes()).hexdigest(),
        )
        self.assertEqual(first["target_root"], str(self.target))
        self.assertEqual(first["config"], "kept")
        self.assertEqual(first["installer_control_paths"], [MANIFEST_FILENAME])
        self.assertEqual(first["skipped"], [])
        self.assertEqual(first["adopted"], [])
        self.assertEqual(second["installer_control_paths"], [MANIFEST_FILENAME])
        for field in ("created", "updated", "removed", "adopted", "skipped"):
            self.assertEqual(second[field], [], field)
        self.assertEqual(
            json.loads((self.target / CONFIG_FILENAME).read_text(encoding="utf-8")),
            config,
        )

    def test_installs_complete_object_contract_reference_and_second_install_is_noop(self):
        first = install(self.target, project="demo")
        second = install(self.target, project="demo")
        root = self._skill_dir("demo-brain-ingest") / "references/object-templates"
        expected_non_kind = {
            "README.md",
            "build-coverage.complete.template.json",
            "build-notes.complete.template.json",
            "direct-coverage.template.json",
            "object-graph.complete.template.json",
            "invalid/manifest.json",
            "invalid/notes-missing-context-commit.json",
            "invalid/missing-base-required.json",
            "invalid/missing-kind-required.json",
            "invalid/candidate-without-metadata.json",
            "invalid/reviewed-without-evidence.json",
            "invalid/invalid-redaction-status.json",
            "invalid/dangling-reference.json",
            "invalid/code-locator-without-quote.json",
            "invalid/code-locator-coordinate-change-without-quote.json",
            "invalid/reviewed-to-candidate.json",
        }
        self.assertTrue(first["created"])
        self.assertTrue(
            all((root / relative).is_file() for relative in expected_non_kind)
        )

        kind_files = {
            path.name.removesuffix(".template.json")
            for path in (root / "kinds").glob("*.template.json")
        }
        from project_brain.schema import VALID_KINDS

        self.assertEqual(kind_files, VALID_KINDS)
        invalid_manifest = json.loads(
            (root / "invalid/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {case["file"] for case in invalid_manifest["cases"]},
            {
                Path(relative).name
                for relative in expected_non_kind
                if relative.startswith("invalid/")
                and relative != "invalid/manifest.json"
            },
        )
        for path in root.rglob("*.json"):
            json.loads(path.read_text(encoding="utf-8"))
        canonical_root = (
            ROOT / "src/project_brain/templates/ingest/references/object-templates"
        )
        for name in (
            "build-coverage.complete.template.json",
            "direct-coverage.template.json",
        ):
            self.assertEqual((root / name).read_bytes(), (canonical_root / name).read_bytes())
        for field in ("created", "updated", "removed", "adopted", "skipped"):
            self.assertEqual(second[field], [], field)

    def test_config_symlink_fails_closed_before_any_read_or_write(self):
        with TemporaryDirectory() as outside_dir:
            external = Path(outside_dir) / "external-config.json"
            external.write_text(
                json.dumps({"project": "outside", "brain_root": "brain"}),
                encoding="utf-8",
            )
            external_before = external.read_bytes()
            config_path = self.target / CONFIG_FILENAME
            config_path.symlink_to(external)

            with self.assertRaisesRegex(
                    InstallConflictError, r"\.project-brain\.json.*심링크"):
                install(self.target, project="demo", repo="would-have-been-backfilled")

            self.assertTrue(config_path.is_symlink())
            self.assertEqual(external.read_bytes(), external_before)
            self.assertFalse((self.target / MANIFEST_FILENAME).exists())
            self.assertFalse((self.target / ".agents").exists())

    def test_manifest_symlink_fails_closed_before_config_backfill_or_other_writes(self):
        config_path = self.target / CONFIG_FILENAME
        config_path.write_text(
            json.dumps({"project": "demo", "brain_root": "brain"}),
            encoding="utf-8",
        )
        config_before = config_path.read_bytes()
        with TemporaryDirectory() as outside_dir:
            external = Path(outside_dir) / "external-manifest.json"
            external.write_text('{"files": {}}\n', encoding="utf-8")
            external_before = external.read_bytes()
            manifest_path = self.target / MANIFEST_FILENAME
            manifest_path.symlink_to(external)

            with self.assertRaisesRegex(
                    InstallConflictError, r"\.project-brain-manifest\.json.*심링크"):
                install(self.target, project="demo", repo="would-have-been-backfilled")

            self.assertTrue(manifest_path.is_symlink())
            self.assertEqual(external.read_bytes(), external_before)
            self.assertEqual(config_path.read_bytes(), config_before)
            self.assertFalse((self.target / ".agents").exists())

    def test_control_file_directories_fail_closed_before_other_writes(self):
        for control_name in (CONFIG_FILENAME, MANIFEST_FILENAME):
            with self.subTest(control_name=control_name):
                target = self.target / control_name.removeprefix(".").removesuffix(".json")
                target.mkdir()
                if control_name == MANIFEST_FILENAME:
                    (target / CONFIG_FILENAME).write_text(
                        json.dumps({"project": "demo", "brain_root": "brain"}),
                        encoding="utf-8",
                    )
                control_path = target / control_name
                control_path.mkdir()
                config_before = (
                    (target / CONFIG_FILENAME).read_bytes()
                    if control_name == MANIFEST_FILENAME else None
                )

                with self.assertRaisesRegex(
                        InstallConflictError, rf"{control_name}.*일반 파일이 아님"):
                    install(target, project="demo", repo="would-have-been-backfilled")

                self.assertTrue(control_path.is_dir())
                if config_before is not None:
                    self.assertEqual((target / CONFIG_FILENAME).read_bytes(), config_before)
                self.assertFalse((target / ".agents").exists())

    def test_desired_directory_fails_closed_before_config_or_managed_writes(self):
        install(self.target, project="demo")
        destination = self._skill("demo-brain-query")
        destination.unlink()
        destination.mkdir()
        sentinel = destination / "user-data.txt"
        sentinel.write_text("user-owned directory\n", encoding="utf-8")
        other_managed = self._skill("demo-brain-ingest")
        config_path = self.target / CONFIG_FILENAME
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config.pop("repo")
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        manifest_path = self.target / MANIFEST_FILENAME
        before = {
            "config": config_path.read_bytes(),
            "manifest": manifest_path.read_bytes(),
            "sentinel": sentinel.read_bytes(),
            "other": other_managed.read_bytes(),
        }

        with self.assertRaises(Exception) as raised:
            install(self.target, project="demo", repo="would-have-been-backfilled")

        self.assertEqual(config_path.read_bytes(), before["config"])
        self.assertEqual(manifest_path.read_bytes(), before["manifest"])
        self.assertTrue(destination.is_dir())
        self.assertEqual(sentinel.read_bytes(), before["sentinel"])
        self.assertEqual(other_managed.read_bytes(), before["other"])
        self.assertIsInstance(raised.exception, InstallConflictError)
        self.assertRegex(
            str(raised.exception), r"brain-query/SKILL\.md.*관리 경로가 일반 파일이 아님",
        )

    def test_desired_fifo_preflight_rejects_without_reading_it(self):
        import os
        import project_brain.installer as inst

        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO를 지원하지 않는 플랫폼")
        install(self.target, project="demo")
        destination = self._skill("demo-brain-query")
        destination.unlink()
        os.mkfifo(destination)
        rel_key = str(destination.relative_to(self.target))

        with self.assertRaisesRegex(
                InstallConflictError, r"brain-query/SKILL\.md.*관리 경로가 일반 파일이 아님"):
            inst._safe_managed_path(
                self.target, rel_key, inst._managed_roots("demo"),
                require_regular_leaf=True,
            )

    def test_reinstall_is_idempotent(self):
        install(self.target, project="demo")
        report = install(self.target, project="demo")
        self.assertEqual(report["config"], "kept")
        # 동일 내용 재설치 — 내용 동일·이미 도구 소유 → 무변경
        self.assertEqual(report["created"], [])
        self.assertEqual(report["updated"], [])
        self.assertEqual(report["adopted"], [])
        self.assertEqual(report["skipped"], [])
        self.assertEqual(report["removed"], [])

    def test_reinstall_removes_unchanged_retired_file_and_prunes_manifest(self):
        install(self.target, project="demo")
        rel_key = ".agents/skills/demo-brain-query/references/retired.md"
        retired = self._record_retired(rel_key)

        report = install(self.target, project="demo")

        self.assertFalse(retired.exists())
        self.assertEqual(report["removed"], [retired.relative_to(self.target).as_posix()])
        self.assertNotIn(rel_key, self._manifest()["files"])

    def test_reinstall_prunes_missing_retired_manifest_key_without_reporting_removal(self):
        install(self.target, project="demo")
        rel_key = ".agents/skills/demo-brain-query/references/missing.md"
        self._record_retired(rel_key, create=False)

        report = install(self.target, project="demo")

        self.assertEqual(report["removed"], [])
        self.assertNotIn(rel_key, self._manifest()["files"])

    def test_manifest_prepare_failure_keeps_retired_file_and_old_manifest(self):
        import project_brain.installer as inst
        install(self.target, project="demo")
        retired = self._record_retired(
            ".agents/skills/demo-brain-query/references/retired.md", b"retired bytes\n")
        manifest_path = self.target / MANIFEST_FILENAME
        manifest_before = manifest_path.read_bytes()
        retired_before = retired.read_bytes()
        original_write_bytes = Path.write_bytes

        def fail_manifest_temporary_write(path, data):
            if path.name.startswith(f".{MANIFEST_FILENAME}."):
                raise OSError("injected manifest preparation failure")
            return original_write_bytes(path, data)

        with mock.patch.object(Path, "write_bytes", new=fail_manifest_temporary_write):
            with self.assertRaisesRegex(OSError, "manifest preparation failure"):
                install(self.target, project="demo")

        self.assertEqual(retired.read_bytes(), retired_before)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self._assert_no_retirement_artifacts()
        install(self.target, project="demo")
        self.assertFalse(retired.exists())
        second = install(self.target, project="demo")
        for field in ("created", "updated", "removed", "adopted", "skipped"):
            self.assertEqual(second[field], [])

    def test_manifest_replace_failure_restores_all_retired_files(self):
        import project_brain.installer as inst
        install(self.target, project="demo")
        retired = [
            self._record_retired(
                ".agents/skills/demo-brain-query/references/retired-one.md", b"first retired\n"),
            self._record_retired(
                ".agents/skills/demo-brain-query/references/retired-two.md", b"second retired\n"),
        ]
        manifest_path = self.target / MANIFEST_FILENAME
        manifest_before = manifest_path.read_bytes()
        retired_before = [path.read_bytes() for path in retired]
        original_replace = inst.os.replace

        def fail_manifest_replace(source, destination):
            if Path(destination) == manifest_path:
                raise OSError("injected manifest replace failure")
            return original_replace(source, destination)

        with mock.patch.object(inst.os, "replace", new=fail_manifest_replace):
            with self.assertRaisesRegex(OSError, "manifest replace failure"):
                install(self.target, project="demo")

        self.assertEqual([path.read_bytes() for path in retired], retired_before)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self._assert_no_retirement_artifacts()
        install(self.target, project="demo")
        self.assertTrue(all(not path.exists() for path in retired))
        second = install(self.target, project="demo")
        for field in ("created", "updated", "removed", "adopted", "skipped"):
            self.assertEqual(second[field], [])

    def test_second_retirement_move_failure_restores_first_file(self):
        import project_brain.installer as inst
        install(self.target, project="demo")
        retired = [
            self._record_retired(
                ".agents/skills/demo-brain-query/references/retired-one.md", b"first retired\n"),
            self._record_retired(
                ".agents/skills/demo-brain-query/references/retired-two.md", b"second retired\n"),
        ]
        manifest_path = self.target / MANIFEST_FILENAME
        manifest_before = manifest_path.read_bytes()
        retired_before = [path.read_bytes() for path in retired]
        original_replace = inst.os.replace

        def fail_second_retirement_move(source, destination):
            if Path(source) == retired[1]:
                raise OSError("injected second retirement move failure")
            return original_replace(source, destination)

        with mock.patch.object(inst.os, "replace", new=fail_second_retirement_move):
            with self.assertRaisesRegex(OSError, "second retirement move failure"):
                install(self.target, project="demo")

        self.assertEqual([path.read_bytes() for path in retired], retired_before)
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        self._assert_no_retirement_artifacts()
        install(self.target, project="demo")
        self.assertTrue(all(not path.exists() for path in retired))
        second = install(self.target, project="demo")
        for field in ("created", "updated", "removed", "adopted", "skipped"):
            self.assertEqual(second[field], [])

    def test_desired_write_failure_preserves_retired_config_and_manifest(self):
        import project_brain.installer as inst
        templates = self.target / "write_failure_templates"
        old_source = templates / "query" / "references" / "old.md"
        old_source.parent.mkdir(parents=True)
        old_source.write_bytes(b"retired managed bytes\n")
        (self.target / CONFIG_FILENAME).write_text(
            json.dumps({"project": "demo", "brain_root": "brain"}), encoding="utf-8")
        original_dir, original_skills = inst._TEMPLATES_DIR, inst._SKILLS
        inst._TEMPLATES_DIR, inst._SKILLS = templates, {"query": "brain-query"}
        try:
            install(self.target, project="demo")
            retired = self._skill_dir("demo-brain-query") / "references" / "old.md"
            new_installed = self._skill_dir("demo-brain-query") / "references" / "new.md"
            old_source.unlink()
            (old_source.parent / "new.md").write_bytes(b"new desired bytes\n")
            config_before = (self.target / CONFIG_FILENAME).read_bytes()
            manifest_before = (self.target / MANIFEST_FILENAME).read_bytes()
            retired_before = retired.read_bytes()
            original_write_bytes = Path.write_bytes

            def fail_new_desired_write(path, data):
                if data == b"new desired bytes\n":
                    raise OSError("injected desired write failure")
                return original_write_bytes(path, data)

            with mock.patch.object(Path, "write_bytes", new=fail_new_desired_write):
                with self.assertRaisesRegex(OSError, "injected desired write failure"):
                    install(self.target, project="demo", repo="backfill-repo")

            self.assertEqual(retired.read_bytes(), retired_before)
            self.assertFalse(new_installed.exists())
            self.assertEqual((self.target / CONFIG_FILENAME).read_bytes(), config_before)
            self.assertEqual((self.target / MANIFEST_FILENAME).read_bytes(), manifest_before)
        finally:
            inst._TEMPLATES_DIR, inst._SKILLS = original_dir, original_skills

    def test_modified_retired_file_fails_before_any_write_even_with_force(self):
        install(self.target, project="demo")
        rel_key = ".agents/skills/demo-brain-query/references/retired.md"
        retired = self._record_retired(rel_key)
        retired.write_text("사용자 수정\n", encoding="utf-8")
        desired = self._skill("demo-brain-query")
        desired.unlink()
        manifest_before = (self.target / MANIFEST_FILENAME).read_bytes()
        config_before = (self.target / CONFIG_FILENAME).read_bytes()

        with self.assertRaisesRegex(RuntimeError, "retired.md.*사용자 수정"):
            install(self.target, project="demo", force=True)

        self.assertEqual(retired.read_text(encoding="utf-8"), "사용자 수정\n")
        self.assertFalse(desired.exists())
        self.assertEqual((self.target / MANIFEST_FILENAME).read_bytes(), manifest_before)
        self.assertEqual((self.target / CONFIG_FILENAME).read_bytes(), config_before)

    def test_retired_symlink_and_parent_symlink_fail_closed(self):
        install(self.target, project="demo")
        with TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir)
            outside_file = outside / "outside.md"
            outside_file.write_text("outside\n", encoding="utf-8")

            symlink_key = ".agents/skills/demo-brain-query/references/retired-link.md"
            symlink = self._record_retired(symlink_key, create=False)
            symlink.parent.mkdir(parents=True, exist_ok=True)
            symlink.symlink_to(outside_file)
            with self.assertRaisesRegex(RuntimeError, "retired-link.md.*심링크"):
                install(self.target, project="demo")
            symlink.unlink()

            manifest = self._manifest()
            manifest["files"].pop(symlink_key)
            parent_key = ".agents/skills/demo-brain-query/references/linked/retired.md"
            manifest["files"][parent_key] = hashlib.sha256(b"outside\n").hexdigest()
            self._write_manifest(manifest)
            linked_parent = self.target / ".agents/skills/demo-brain-query/references/linked"
            linked_parent.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "linked/retired.md.*대상 루트 밖"):
                install(self.target, project="demo")
            self.assertEqual(outside_file.read_text(encoding="utf-8"), "outside\n")

    def test_unsafe_retired_manifest_paths_fail_closed(self):
        with TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir) / "outside.md"
            outside.write_text("outside\n", encoding="utf-8")
            unsafe_keys = (
                str(outside),
                "../outside.md",
                ".agents/skills/not-a-managed-root/retired.md",
            )
            for index, unsafe_key in enumerate(unsafe_keys):
                with self.subTest(unsafe_key=unsafe_key):
                    target = self.target / f"unsafe-{index}"
                    target.mkdir()
                    install(target, project="demo")
                    manifest_path = target / MANIFEST_FILENAME
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    manifest["files"][unsafe_key] = hashlib.sha256(b"outside\n").hexdigest()
                    manifest_path.write_text(
                        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
                    before = manifest_path.read_bytes()
                    with self.assertRaisesRegex(RuntimeError, "안전하지 않은 관리 경로"):
                        install(target, project="demo")
                    self.assertEqual(manifest_path.read_bytes(), before)
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")

    def test_template_move_creates_new_file_removes_old_and_second_run_is_idempotent(self):
        import project_brain.installer as inst
        templates = self.target / "move_templates"
        old_source = templates / "query" / "references" / "old.md"
        old_source.parent.mkdir(parents=True)
        old_source.write_text("managed\n", encoding="utf-8")
        original_dir, original_skills = inst._TEMPLATES_DIR, inst._SKILLS
        inst._TEMPLATES_DIR, inst._SKILLS = templates, {"query": "brain-query"}
        try:
            install(self.target, project="demo")
            old_installed = self._skill_dir("demo-brain-query") / "references" / "old.md"
            new_installed = self._skill_dir("demo-brain-query") / "references" / "new.md"
            old_source.unlink()
            (old_source.parent / "new.md").write_text("managed\n", encoding="utf-8")

            migrated = install(self.target, project="demo")
            second = install(self.target, project="demo")

            self.assertEqual(
                migrated["removed"],
                [old_installed.relative_to(self.target).as_posix()],
            )
            self.assertIn(
                new_installed.relative_to(self.target).as_posix(),
                migrated["created"],
            )
            self.assertFalse(old_installed.exists())
            self.assertTrue(new_installed.is_file())
            for field in ("created", "updated", "removed", "adopted", "skipped"):
                self.assertEqual(second[field], [], field)
        finally:
            inst._TEMPLATES_DIR, inst._SKILLS = original_dir, original_skills

    def test_template_move_user_owned_destination_conflict_fails_before_any_write(self):
        import project_brain.installer as inst
        templates = self.target / "move_conflict_templates"
        old_source = templates / "query" / "references" / "old.md"
        old_source.parent.mkdir(parents=True)
        old_source.write_text("managed old\n", encoding="utf-8")
        original_dir, original_skills = inst._TEMPLATES_DIR, inst._SKILLS
        inst._TEMPLATES_DIR, inst._SKILLS = templates, {"query": "brain-query"}
        try:
            install(self.target, project="demo")
            old_installed = self._skill_dir("demo-brain-query") / "references" / "old.md"
            new_installed = self._skill_dir("demo-brain-query") / "references" / "new.md"
            old_source.unlink()
            (old_source.parent / "new.md").write_text("managed new\n", encoding="utf-8")
            new_installed.write_text("user destination\n", encoding="utf-8")
            config_path = self.target / CONFIG_FILENAME
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config.pop("repo")
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            manifest_path = self.target / MANIFEST_FILENAME
            before = {
                "old": old_installed.read_bytes(),
                "new": new_installed.read_bytes(),
                "config": config_path.read_bytes(),
                "manifest": manifest_path.read_bytes(),
            }

            with self.assertRaisesRegex(
                    InstallConflictError, r"new\.md.*manifest 밖.*사용자"):
                install(self.target, project="demo", repo="would-have-been-backfilled")

            self.assertEqual(old_installed.read_bytes(), before["old"])
            self.assertEqual(new_installed.read_bytes(), before["new"])
            self.assertEqual(config_path.read_bytes(), before["config"])
            self.assertEqual(manifest_path.read_bytes(), before["manifest"])
        finally:
            inst._TEMPLATES_DIR, inst._SKILLS = original_dir, original_skills

    def test_template_move_file_parent_conflict_fails_before_any_write(self):
        import project_brain.installer as inst
        templates = self.target / "move_parent_conflict_templates"
        refs = templates / "query" / "references"
        refs.mkdir(parents=True)
        old_source = refs / "old.md"
        old_source.write_text("managed old\n", encoding="utf-8")
        original_dir, original_skills = inst._TEMPLATES_DIR, inst._SKILLS
        inst._TEMPLATES_DIR, inst._SKILLS = templates, {"query": "brain-query"}
        try:
            install(self.target, project="demo")
            old_installed = self._skill_dir("demo-brain-query") / "references" / "old.md"
            new_installed = self._skill_dir("demo-brain-query") / "references" / "new" / "leaf.md"
            old_source.unlink()
            new_source = refs / "new" / "leaf.md"
            new_source.parent.mkdir()
            new_source.write_text("managed new\n", encoding="utf-8")
            blocker = new_installed.parent
            blocker.write_text("user-owned blocker\n", encoding="utf-8")
            config_path = self.target / CONFIG_FILENAME
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config.pop("repo")
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            manifest_path = self.target / MANIFEST_FILENAME
            before = {
                "old": old_installed.read_bytes(),
                "blocker": blocker.read_bytes(),
                "config": config_path.read_bytes(),
                "manifest": manifest_path.read_bytes(),
            }

            with self.assertRaisesRegex(
                    InstallConflictError, r"new/leaf\.md.*부모 경로.*디렉터리가 아님"):
                install(self.target, project="demo", repo="would-have-been-backfilled")

            self.assertEqual(old_installed.read_bytes(), before["old"])
            self.assertEqual(blocker.read_bytes(), before["blocker"])
            self.assertEqual(config_path.read_bytes(), before["config"])
            self.assertEqual(manifest_path.read_bytes(), before["manifest"])
            self.assertFalse(new_installed.exists())
        finally:
            inst._TEMPLATES_DIR, inst._SKILLS = original_dir, original_skills

    def test_retired_file_plus_modified_tracked_destination_fails_before_any_write(self):
        import project_brain.installer as inst
        templates = self.target / "tracked_conflict_templates"
        refs = templates / "query" / "references"
        refs.mkdir(parents=True)
        (refs / "old.md").write_text("managed old\n", encoding="utf-8")
        (refs / "kept.md").write_text("managed kept\n", encoding="utf-8")
        original_dir, original_skills = inst._TEMPLATES_DIR, inst._SKILLS
        inst._TEMPLATES_DIR, inst._SKILLS = templates, {"query": "brain-query"}
        try:
            install(self.target, project="demo")
            old_installed = self._skill_dir("demo-brain-query") / "references" / "old.md"
            kept_installed = self._skill_dir("demo-brain-query") / "references" / "kept.md"
            (refs / "old.md").unlink()
            kept_installed.write_text("user modified tracked\n", encoding="utf-8")
            config_path = self.target / CONFIG_FILENAME
            manifest_path = self.target / MANIFEST_FILENAME
            before = {
                "old": old_installed.read_bytes(),
                "kept": kept_installed.read_bytes(),
                "config": config_path.read_bytes(),
                "manifest": manifest_path.read_bytes(),
            }

            with self.assertRaisesRegex(
                    InstallConflictError, r"kept\.md.*manifest 추적.*사용자 수정"):
                install(self.target, project="demo")

            self.assertEqual(old_installed.read_bytes(), before["old"])
            self.assertEqual(kept_installed.read_bytes(), before["kept"])
            self.assertEqual(config_path.read_bytes(), before["config"])
            self.assertEqual(manifest_path.read_bytes(), before["manifest"])
        finally:
            inst._TEMPLATES_DIR, inst._SKILLS = original_dir, original_skills

    def test_template_move_matching_user_destination_is_adopted(self):
        import project_brain.installer as inst
        templates = self.target / "move_adopt_templates"
        old_source = templates / "query" / "references" / "old.md"
        old_source.parent.mkdir(parents=True)
        old_source.write_text("managed\n", encoding="utf-8")
        original_dir, original_skills = inst._TEMPLATES_DIR, inst._SKILLS
        inst._TEMPLATES_DIR, inst._SKILLS = templates, {"query": "brain-query"}
        try:
            install(self.target, project="demo")
            old_installed = self._skill_dir("demo-brain-query") / "references" / "old.md"
            new_installed = self._skill_dir("demo-brain-query") / "references" / "new.md"
            old_source.unlink()
            (old_source.parent / "new.md").write_text("managed\n", encoding="utf-8")
            new_installed.write_text("managed\n", encoding="utf-8")

            report = install(self.target, project="demo")

            self.assertEqual(
                report["removed"],
                [old_installed.relative_to(self.target).as_posix()],
            )
            self.assertEqual(
                report["adopted"],
                [new_installed.relative_to(self.target).as_posix()],
            )
            self.assertEqual(report["skipped"], [])
            self.assertFalse(old_installed.exists())
            self.assertEqual(new_installed.read_text(encoding="utf-8"), "managed\n")
        finally:
            inst._TEMPLATES_DIR, inst._SKILLS = original_dir, original_skills

    def test_force_updates_modified_tracked_destination_during_migration(self):
        import project_brain.installer as inst
        templates = self.target / "force_move_templates"
        refs = templates / "query" / "references"
        refs.mkdir(parents=True)
        (refs / "old.md").write_text("managed old\n", encoding="utf-8")
        (refs / "kept.md").write_text("managed v1\n", encoding="utf-8")
        original_dir, original_skills = inst._TEMPLATES_DIR, inst._SKILLS
        inst._TEMPLATES_DIR, inst._SKILLS = templates, {"query": "brain-query"}
        try:
            install(self.target, project="demo")
            old_installed = self._skill_dir("demo-brain-query") / "references" / "old.md"
            kept_installed = self._skill_dir("demo-brain-query") / "references" / "kept.md"
            (refs / "old.md").unlink()
            (refs / "kept.md").write_text("managed v2\n", encoding="utf-8")
            kept_installed.write_text("user modified tracked\n", encoding="utf-8")

            report = install(self.target, project="demo", force=True)

            self.assertEqual(
                report["removed"],
                [old_installed.relative_to(self.target).as_posix()],
            )
            self.assertEqual(
                report["updated"],
                [kept_installed.relative_to(self.target).as_posix()],
            )
            self.assertFalse(old_installed.exists())
            self.assertEqual(kept_installed.read_text(encoding="utf-8"), "managed v2\n")
        finally:
            inst._TEMPLATES_DIR, inst._SKILLS = original_dir, original_skills

    def test_existing_config_is_preserved(self):
        (self.target / CONFIG_FILENAME).write_text(
            json.dumps({"project": "custom", "brain_root": "knowledge"}),
            encoding="utf-8",
        )
        report = install(self.target, project="demo")
        cfg = json.loads((self.target / CONFIG_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(cfg["project"], "custom")  # 기존 config 보존
        self.assertEqual(report["config"], "kept")
        # 스킬 렌더는 기존 config의 project/brain_root를 따른다
        self.assertTrue(self._skill("custom-brain-query").exists())
        recall = self._skill("custom-brain-query").read_text(encoding="utf-8")
        self.assertIn("knowledge", recall)

    def test_user_modified_skill_not_overwritten(self):
        install(self.target, project="demo")
        skill = self._skill("demo-brain-query")
        skill.write_text("사용자 수정본", encoding="utf-8")
        report = install(self.target, project="demo")
        self.assertEqual(skill.read_text(encoding="utf-8"), "사용자 수정본")
        self.assertIn(skill.relative_to(self.target).as_posix(), report["skipped"])

    def test_preexisting_user_skill_not_touched(self):
        # install 밖에서 만들어진(=manifest에 없는) 스킬은 사용자 소유 — 건드리지 않는다.
        skill = self._skill("demo-brain-query")
        skill.parent.mkdir(parents=True)
        skill.write_text("기존 사용자 스킬", encoding="utf-8")
        report = install(self.target, project="demo")
        self.assertEqual(skill.read_text(encoding="utf-8"), "기존 사용자 스킬")
        self.assertIn(skill.relative_to(self.target).as_posix(), report["skipped"])

    def test_install_writes_new_config_keys(self):
        install(self.target, project="demo", default_branch="main", repo="myrepo")
        cfg = json.loads((self.target / CONFIG_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(cfg["default_branch"], "main")
        self.assertEqual(cfg["repo"], "myrepo")

    def test_install_backfills_missing_config_keys_from_flags(self):
        # footgun 방지: 기존 config에 repo/default_branch 칸이 없는데 옵션으로 값을 주면
        # 그 값을 config에 채워(backfill) 다음 install이 같은 값으로 결정적이게 한다.
        # 기존 키는 안 건드리고(보존), 옵션이 빈 값이면 안 적는다.
        (self.target / CONFIG_FILENAME).write_text(
            json.dumps({"project": "demo", "brain_root": "brain"}), encoding="utf-8")
        report = install(self.target, project="demo", repo="myrepo", default_branch="main")
        cfg = json.loads((self.target / CONFIG_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(cfg["repo"], "myrepo")          # 누락 키 보충
        self.assertEqual(cfg["default_branch"], "main")  # 누락 키 보충
        self.assertEqual(cfg["project"], "demo")         # 기존 키 보존
        self.assertEqual(report["config"], "updated")
        # backfill 덕에 옵션 없이 재실행해도 같은 값으로 렌더(다음번에 빈 값으로 안 깨짐)
        report2 = install(self.target, project="demo")
        self.assertEqual(report2["config"], "kept")
        skill = self._skill("demo-brain-query").read_text(encoding="utf-8")
        self.assertNotIn("{{REPO}}", skill)

    def test_adopts_matching_disk_file_into_manifest(self):
        # manifest 밖 파일이 렌더 결과와 내용이 같으면 채택(도구 소유 등록).
        install(self.target, project="demo")  # 1회 설치로 파일·manifest 생성
        # manifest를 비워 "사용자 소유"로 되돌린 뒤 재설치 → 내용 같으니 채택
        (self.target / MANIFEST_FILENAME).write_text('{"files": {}}', encoding="utf-8")
        report = install(self.target, project="demo")
        self.assertTrue(report["adopted"])
        self.assertEqual(report["skipped"], [])
        manifest = json.loads((self.target / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        self.assertTrue(len(manifest["files"]) >= 4)

    def test_force_overwrites_manifest_tracked_user_edit(self):
        install(self.target, project="demo")
        skill = self._skill("demo-brain-query")
        skill.write_text("사용자 수정본", encoding="utf-8")  # manifest 기록 있음 + 수정
        report = install(self.target, project="demo", force=True)
        self.assertIn("name: demo-brain-query", skill.read_text(encoding="utf-8"))
        self.assertIn(skill.relative_to(self.target).as_posix(), report["updated"])

    def test_force_preserves_manifest_outside_file(self):
        # manifest 밖(사용자 소유) 파일은 force여도 보존.
        skill = self._skill("demo-brain-query")
        skill.parent.mkdir(parents=True)
        skill.write_text("기존 사용자 스킬", encoding="utf-8")
        report = install(self.target, project="demo", force=True)
        self.assertEqual(skill.read_text(encoding="utf-8"), "기존 사용자 스킬")
        self.assertIn(skill.relative_to(self.target).as_posix(), report["skipped"])

    def test_real_templates_render_with_synthetic_values(self):
        # 역수입된 실제 templates를 합성값으로 렌더 → (a) 미치환 토큰 0(현재 brain 스킬엔
        # 정당한 {{ 리터럴이 없음 — 확인됨), (b) 도구명 오염(project-{{BRAIN_ROOT}}) 부재.
        import project_brain.installer as inst
        for skill in inst._SKILLS:
            root = inst._TEMPLATES_DIR / skill
            for src in root.rglob("*"):
                if not src.is_file() or inst._excluded(src.relative_to(root)):
                    continue
                if src.suffix not in inst._TEXT_SUFFIXES:
                    continue
                raw = src.read_text(encoding="utf-8")
                out = inst.render_text(raw, project="zzz", brain_root="kkk",
                                       default_branch="ttt", repo="qqq")
                self.assertNotIn("{{", out, f"미치환 토큰: {src}")
                # F1 오염 백스톱: project-brain이 project-{{BRAIN_ROOT}}로 깨졌으면
                # 합성 렌더에서 project-kkk가 나타난다(정상 리터럴에선 부재).
                self.assertNotIn("project-kkk", out,
                                 f"도구명 오염(project-brain→project-<root>): {src}")

    def test_ingest_runtime_scripts_install_without_claiming_project_overlay(self):
        overlay = (self._skill_dir("demo-brain-ingest") / "references" /
                   "project-code-verification.md")
        overlay.parent.mkdir(parents=True)
        overlay.write_text("프로젝트가 소유하는 코드 검증 규칙\n", encoding="utf-8")

        install(self.target, project="demo")
        second = install(self.target, project="demo")

        scripts = self._skill_dir("demo-brain-ingest") / "scripts"
        for name in ("run_ingest.sh", "finalize_ingest.sh", "finalize_ingest.py", "run_ingest_batch.py",
                     "validate_workflow_result.py", "validate_foundation.py"):
            with self.subTest(name=name):
                script = scripts / name
                self.assertTrue(script.is_file())
                if name.endswith(".sh") or name == "validate_foundation.py":
                    self.assertTrue(script.stat().st_mode & stat.S_IXUSR)
        run_ingest = (scripts / "run_ingest.sh").read_text(encoding="utf-8")
        for flag in ("--repo-root", "--brain-root", "--expected-repo-id", "--expected-revision-ref",
                     "--engine-sha", "--batch-binding-file", "--validate-transaction"):
            self.assertIn(flag, run_ingest)
        installed_batch = (scripts / "run_ingest_batch.py").read_text(encoding="utf-8")
        installed_finalizer = (scripts / "finalize_ingest.py").read_text(encoding="utf-8")
        for token in (
            "item_records",
            "target_revision_sha",
            "batch-binding.json",
            "recover_batch_receipts",
            "brain_root_inode",
            "post-finalizer verification",
            "post_gate_object_tail",
            "strict_commit",
        ):
            self.assertIn(token, installed_batch + installed_finalizer)
        installed_query = self._skill("demo-brain-query").read_text(encoding="utf-8")
        installed_audit = self._skill("demo-brain-audit").read_text(encoding="utf-8")
        self.assertIn("display_only", installed_query)
        self.assertIn("quote_access=allow", installed_query)
        self.assertIn("code_quote=missing", installed_audit)
        self.assertFalse((scripts / "test_batch_tools.py").exists())
        self.assertFalse((scripts / "test_validate_foundation.py").exists())
        self.assertEqual(overlay.read_text(encoding="utf-8"),
                         "프로젝트가 소유하는 코드 검증 규칙\n")
        self.assertNotIn(str(overlay.relative_to(self.target)),
                         json.loads((self.target / MANIFEST_FILENAME).read_text(encoding="utf-8"))["files"])
        for field in ("created", "updated", "removed", "adopted", "skipped"):
            self.assertEqual(second[field], [], field)


if __name__ == "__main__":
    unittest.main()
