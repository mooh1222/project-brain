"""대량 적재에서 재발한 계약을 고정한다.

1. 전체 ID를 logical key로 쓰지 않는다.
2. 대량 적재는 item ingest와 finalization을 분리한다.
3. workflow top-level `completed`만으로 완료 처리하지 않는다.
4. 코드 흐름 적대검증은 프로젝트별 코드 검증 계약을 읽고 하위 작업자에게도 전달한다.
5. raw 파일명은 versioned spec과 bulk archive를 구분한다.
"""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = ROOT / "src" / "project_brain" / "templates" / "ingest"
SKILL = TEMPLATE_ROOT / "SKILL.md"
REFERENCES = TEMPLATE_ROOT / "references"
REQUIRED_REFERENCES = (
    "scope.md",
    "object-model.md",
    "judgment.md",
    "ingest-tools.md",
    "system-domain-playbook.md",
    "completeness-checklist.md",
    "worked-example.md",
    "ingest-case-log.md",
)


class IngestSkillContractTest(unittest.TestCase):
    def test_skill_is_a_compact_router(self):
        text = SKILL.read_text(encoding="utf-8")
        for reference in REQUIRED_REFERENCES:
            self.assertTrue((REFERENCES / reference).is_file(), reference)
            self.assertIn(f"references/{reference}", text)
        self.assertLessEqual(len(text.splitlines()), 170)

    def test_generic_skill_routes_optional_project_code_verification(self):
        skill = SKILL.read_text(encoding="utf-8")
        playbook = (REFERENCES / "system-domain-playbook.md").read_text(encoding="utf-8")
        template_markdown = "\n".join(
            path.read_text(encoding="utf-8")
            for path in TEMPLATE_ROOT.rglob("*.md")
        )

        self.assertIn("validate_workflow_result.py", skill)
        self.assertIn("references/project-code-verification.md", skill)
        self.assertIn("프로젝트", playbook)
        self.assertIn("하위 작업자", playbook)
        self.assertNotIn("bb2-code-search-routing", template_markdown)
        self.assertNotIn("clangd callers", template_markdown)

    def test_raw_filename_policy_has_one_canonical_location(self):
        skill = SKILL.read_text(encoding="utf-8")
        ingest_tools = (REFERENCES / "ingest-tools.md").read_text(encoding="utf-8")

        self.assertIn("references/ingest-tools.md", skill)
        self.assertNotIn("raw/sources/", skill)
        for detail in ("spec-v<N>.md", "sanitized-original-basename", "analyze-spec-ppt"):
            self.assertNotIn(detail, skill)
            self.assertIn(detail, ingest_tools)


if __name__ == "__main__":
    unittest.main()
