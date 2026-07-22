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

from project_brain.config import CONFIG_FILENAME
from project_brain.installer import MANIFEST_FILENAME, install, render_text


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
            install(adopted_target, project="demo")
            self.assertFalse(adopted.stat().st_mode & stat.S_IXUSR)  # matching untracked adopt

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
        self.assertEqual(report["removed"], [str(retired)])
        self.assertNotIn(rel_key, self._manifest()["files"])

    def test_reinstall_prunes_missing_retired_manifest_key_without_reporting_removal(self):
        install(self.target, project="demo")
        rel_key = ".agents/skills/demo-brain-query/references/missing.md"
        self._record_retired(rel_key, create=False)

        report = install(self.target, project="demo")

        self.assertEqual(report["removed"], [])
        self.assertNotIn(rel_key, self._manifest()["files"])

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

            self.assertEqual(migrated["removed"], [str(old_installed)])
            self.assertIn(str(new_installed), migrated["created"])
            self.assertFalse(old_installed.exists())
            self.assertTrue(new_installed.is_file())
            for field in ("created", "updated", "removed", "adopted", "skipped"):
                self.assertEqual(second[field], [], field)
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
        self.assertIn(str(skill), report["skipped"])

    def test_preexisting_user_skill_not_touched(self):
        # install 밖에서 만들어진(=manifest에 없는) 스킬은 사용자 소유 — 건드리지 않는다.
        skill = self._skill("demo-brain-query")
        skill.parent.mkdir(parents=True)
        skill.write_text("기존 사용자 스킬", encoding="utf-8")
        report = install(self.target, project="demo")
        self.assertEqual(skill.read_text(encoding="utf-8"), "기존 사용자 스킬")
        self.assertIn(str(skill), report["skipped"])

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
        self.assertIn(str(skill), report["updated"])

    def test_force_preserves_manifest_outside_file(self):
        # manifest 밖(사용자 소유) 파일은 force여도 보존.
        skill = self._skill("demo-brain-query")
        skill.parent.mkdir(parents=True)
        skill.write_text("기존 사용자 스킬", encoding="utf-8")
        report = install(self.target, project="demo", force=True)
        self.assertEqual(skill.read_text(encoding="utf-8"), "기존 사용자 스킬")
        self.assertIn(str(skill), report["skipped"])

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
                     "validate_workflow_result.py"):
            with self.subTest(name=name):
                script = scripts / name
                self.assertTrue(script.is_file())
                if name.endswith(".sh") and script.is_file():
                    self.assertTrue(script.stat().st_mode & stat.S_IXUSR)
        self.assertFalse((scripts / "test_batch_tools.py").exists())
        self.assertEqual(overlay.read_text(encoding="utf-8"),
                         "프로젝트가 소유하는 코드 검증 규칙\n")
        self.assertNotIn(str(overlay.relative_to(self.target)),
                         json.loads((self.target / MANIFEST_FILENAME).read_text(encoding="utf-8"))["files"])
        self.assertEqual(second["skipped"], [])


if __name__ == "__main__":
    unittest.main()
