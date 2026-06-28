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
from project_brain.installer import MANIFEST_FILENAME, install, render_template


class RenderTemplateTest(unittest.TestCase):
    def test_substitutes_project_and_brain_root(self):
        text = render_template("query", project="demo", brain_root="brain")
        self.assertIn("name: demo-brain-query", text)
        self.assertIn("demo-brain-ingest", text)  # 상대 스킬 참조도 치환
        self.assertNotIn("{{PROJECT}}", text)
        self.assertNotIn("{{BRAIN_ROOT}}", text)
        # session-ingest 템플릿도 치환 검증
        si = render_template("session-ingest", project="demo", brain_root="brain")
        self.assertIn("name: demo-brain-session-ingest", si)
        self.assertNotIn("{{PROJECT}}", si)
        self.assertNotIn("{{BRAIN_ROOT}}", si)
        # audit 템플릿도 치환 검증
        cu = render_template("audit", project="demo", brain_root="brain")
        self.assertIn("name: demo-brain-audit", cu)
        self.assertIn("demo-brain-session-ingest", cu)  # 상대 스킬 참조도 치환
        self.assertNotIn("{{PROJECT}}", cu)

    def test_unknown_template_raises(self):
        with self.assertRaises(KeyError):
            render_template("nope", project="x", brain_root="brain")


class InstallTest(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.target = Path(self._td.name).resolve()

    def tearDown(self):
        self._td.cleanup()

    def _skill(self, name):
        return self.target / ".claude" / "skills" / name / "SKILL.md"

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
        # manifest에 심은 파일 기록 — 키는 target 기준 상대 경로(머신 이식성:
        # 절대 경로를 박으면 다른 머신 checkout에서 도구 소유 파일을 못 알아본다)
        manifest = json.loads(
            (self.target / MANIFEST_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(len(manifest["files"]), 4)
        for key in manifest["files"]:
            self.assertFalse(Path(key).is_absolute(), key)
            self.assertTrue((self.target / key).exists(), key)
        self.assertEqual(report["config"], "created")
        self.assertEqual(len(report["created"]), 4)

    def test_reinstall_is_idempotent(self):
        install(self.target, project="demo")
        report = install(self.target, project="demo")
        self.assertEqual(report["config"], "kept")
        # 동일 내용 재설치 — created가 아니라 updated(도구 소유 갱신)로 보고
        self.assertEqual(report["created"], [])
        self.assertEqual(len(report["updated"]), 4)

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
