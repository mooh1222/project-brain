"""install — 프로젝트에 config + 스킬 4종을 멱등 설치하고 manifest로 추적한다.

파일 단위 보존 모델: manifest에 기록된 해시와 디스크가 일치할 때만 갱신(도구 소유),
불일치(사용자 수정)·manifest 밖(사용자 소유)은 건드리지 않고 보고한다 —
hwi_PKM manifest 멱등 패턴의 파일 단위 적용.
"""
from __future__ import annotations

import json
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
        # 동일 내용 재설치 — created가 아니라 updated(도구 소유 갱신)로 보고
        self.assertEqual(report["created"], [])
        self.assertEqual(len(report["updated"]), self._expected_count())

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


if __name__ == "__main__":
    unittest.main()
