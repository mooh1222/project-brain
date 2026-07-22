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
    "update-rules.md",
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

    def test_semantic_completeness_and_concept_domain_contracts(self):
        checklist = (REFERENCES / "completeness-checklist.md").read_text(encoding="utf-8")
        judgment = (REFERENCES / "judgment.md").read_text(encoding="utf-8")
        playbook = (REFERENCES / "system-domain-playbook.md").read_text(encoding="utf-8")

        self.assertLess(
            checklist.index("## 적재 전 의미 완전성"),
            checklist.index("## 실행 후 일곱 게이트"),
        )
        for token in ("1-pass", "2-pass", "기획서 기능 목차", "history_coverage=complete",
                      "DecisionRecord", "독립 재구성", "통째로 빠진 규칙"):
            self.assertIn(token, checklist)

        for token in ("spec_reflected=yes", "spec_reflected=no", "spec_reflected=unknown",
                      "spec_reflected=not_applicable"):
            self.assertIn(token, judgment)

        for token in (
            "기획서가 없으면",
            "개발 완료 코드",
            "데이터 소스",
            "구조/표시 패턴",
            "확장 지점",
            "규칙/함정",
            "과거 결정",
            "확장 지점 종합 매핑",
            "공통분모만",
            "기능별 차이",
        ):
            self.assertIn(token, playbook)
        for stale in (
            "SKILL.md §11.4",
            "SKILL.md 분기만으로 충분",
            "SKILL.md와 ingest-tools.md가 이미 다룬다",
        ):
            self.assertNotIn(stale, playbook)

    def test_update_rules_are_ingest_owned_and_cross_skill_routed(self):
        update_rules = REFERENCES / "update-rules.md"
        old_update_rules = TEMPLATE_ROOT.parent / "session-ingest" / "references" / "update-rules.md"
        ingest_skill = SKILL.read_text(encoding="utf-8")
        judgment = (REFERENCES / "judgment.md").read_text(encoding="utf-8")
        audit = (TEMPLATE_ROOT.parent / "audit" / "SKILL.md").read_text(encoding="utf-8")
        session_root = TEMPLATE_ROOT.parent / "session-ingest"
        session_text = "\n".join(
            path.read_text(encoding="utf-8") for path in session_root.rglob("*.md")
        )

        self.assertTrue(update_rules.is_file())
        self.assertFalse(old_update_rules.exists())
        for text in (ingest_skill, judgment, audit, session_text):
            self.assertIn("brain-ingest/references/update-rules.md", text)
        self.assertNotIn("docs/superpowers/", session_text)

        with TemporaryDirectory() as td:
            target = Path(td)
            install(target, project="demo")
            installed = target / ".agents" / "skills"
            self.assertTrue(
                (installed / "demo-brain-ingest" / "references" / "update-rules.md").is_file()
            )
            self.assertFalse(
                (installed / "demo-brain-session-ingest" / "references" / "update-rules.md").exists()
            )

    def test_update_rules_distinguish_engine_operator_and_known_gaps(self):
        text = (REFERENCES / "update-rules.md").read_text(encoding="utf-8")
        for heading in ("## 책임 경계", "## 엔진이 강제하는 것", "## 사람이 지키는 절차",
                        "## 현재 엔진 빈틈", "## kind별 갱신"):
            self.assertIn(heading, text)
        for contract in ("supersedes_mapping_ids", "valid_until", "derived_from_event_id",
                         "scope는 객체", "same-ID", "mark-checked", "reviewed→candidate",
                         "rollback transaction은 아니다"):
            self.assertIn(contract, text)
        self.assertNotIn("EventLedgerRecord 없이는 적재도", text)

    def test_object_model_restores_temporal_and_insight_contracts(self):
        text = (REFERENCES / "object-model.md").read_text(encoding="utf-8")
        self.assertIn("## TemporalFact 시간·연결 계약", text)
        self.assertIn("old status=superseded", text)
        self.assertIn("## Insight 적재 규칙", text)
        for token in ("candidate Insight", "reviewed", "cross-cutting-risk", "operational-lesson",
                      "source_object_ids", "evidence_refs", "session", "advisories"):
            self.assertIn(token, text)

    def test_query_audit_and_playbook_match_current_generic_runtime(self):
        query = (TEMPLATE_ROOT.parent / "query" / "SKILL.md").read_text(encoding="utf-8")
        audit = (TEMPLATE_ROOT.parent / "audit" / "SKILL.md").read_text(encoding="utf-8")
        playbook = (REFERENCES / "system-domain-playbook.md").read_text(encoding="utf-8")
        checklist = (REFERENCES / "completeness-checklist.md").read_text(encoding="utf-8")
        ingest_tools = (REFERENCES / "ingest-tools.md").read_text(encoding="utf-8")

        self.assertIn('project-brain search "<질문>"', query)
        self.assertIn('project-brain query "<시간·이력 질문>"', query)
        self.assertIn("project-brain show <object_id>", query)
        self.assertNotIn("search가 supersedes", query)
        self.assertIn("brain-ingest/references/update-rules.md", audit)
        for stale in ("model: 'opus'", "agentType: 'Explore'", "Haiku", "BrainStore", "term_ids ="):
            self.assertNotIn(stale, playbook)
        for artifact in ("심볼 인벤토리", "누락 판정", "확인한 이력 종류"):
            self.assertIn(artifact, checklist)
        self.assertNotIn("docs/superpowers/plans/", ingest_tools)

    def test_semantic_finalization_is_manifest_driven_and_evidence_bearing(self):
        ingest_tools = (REFERENCES / "ingest-tools.md").read_text(encoding="utf-8")
        checklist = (REFERENCES / "completeness-checklist.md").read_text(encoding="utf-8")
        scripts = "\n".join(
            path.read_text(encoding="utf-8") for path in (TEMPLATE_ROOT / "scripts").glob("*.py")
        )
        for token in ("recall_checks", "expected_object_ids", "require_code_locators",
                      "intentional_terminal_ids", "isolation_baseline", "manifest_fingerprint"):
            self.assertIn(token, ingest_tools)
        for token in ("finalization.ok", "unexpected_new_ids", "missing_object_ids",
                      "missing_code_locator_object_ids"):
            self.assertIn(token, checklist)
        self.assertNotIn("이 컨텍스트 핵심 동작", scripts)


if __name__ == "__main__":
    unittest.main()
