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
from tempfile import TemporaryDirectory

from project_brain.installer import install


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
SOURCE_INTAKE_REPORT_TOKENS = (
    "사용자에게 보이는 첫 진행 보고",
    "Source Intake",
    "route=single|batch",
    "history_coverage=<값>",
    "보류해도 이 선언은 생략하지 않는다",
)
RAW_SANITIZATION_TOKENS = (
    "소문자 ASCII 영숫자와 하이픈",
    "`[^a-z0-9]+`",
    "fallback `document`",
    "`Legacy Plan 01.md` → `legacy-plan-01.md`",
    "`Collision Notes.md` → `collision-notes.md`",
    "Source Intake에서 선언한 source bundle root",
    "root 아래 상대경로",
    "절대경로와 `..` 탈출",
    "`.` component",
    "Unicode NFC",
    "경로 구분자는 `/`",
    "대소문자는 바꾸지 않고",
    "canonical relative path 문자열의 UTF-8 바이트",
    "파일 내용의 SHA-256이 아니다",
    "suffix를 늘리고 매번 유일성을 확인",
    "심볼릭 링크는 거부한다",
    "64 hex 글자까지",
    "비어 있지 않으면 fail-closed",
)


def _raw_policy_section(text: str) -> str:
    start = text.index("## 기획서 원문 보관")
    end = text.index("파일 기반 manifest", start)
    return text[start:end]


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

    def test_raw_filename_sanitization_contract_survives_install(self):
        canonical = (REFERENCES / "ingest-tools.md").read_text(encoding="utf-8")
        canonical_section = _raw_policy_section(canonical)
        for token in RAW_SANITIZATION_TOKENS:
            self.assertIn(token, canonical_section)

        with TemporaryDirectory() as td:
            target = Path(td)
            install(target, project="demo")
            rendered = (
                target
                / ".agents"
                / "skills"
                / "demo-brain-ingest"
                / "references"
                / "ingest-tools.md"
            ).read_text(encoding="utf-8")
        rendered_section = _raw_policy_section(rendered)
        for token in RAW_SANITIZATION_TOKENS:
            self.assertIn(token, rendered_section)

    def test_source_intake_report_contract_survives_install(self):
        canonical = SKILL.read_text(encoding="utf-8")
        for token in SOURCE_INTAKE_REPORT_TOKENS:
            self.assertIn(token, canonical)

        with TemporaryDirectory() as td:
            target = Path(td)
            install(target, project="demo")
            rendered = (
                target / ".agents" / "skills" / "demo-brain-ingest" / "SKILL.md"
            ).read_text(encoding="utf-8")
        for token in SOURCE_INTAKE_REPORT_TOKENS:
            self.assertIn(token, rendered)


if __name__ == "__main__":
    unittest.main()
