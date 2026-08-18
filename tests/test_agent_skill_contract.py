from pathlib import Path
from tempfile import TemporaryDirectory

from project_brain.installer import install


def _installed_skill(skill: str) -> str:
    with TemporaryDirectory() as td:
        target = Path(td)
        install(
            target,
            project="demo",
            brain_root="brain",
            default_branch="trunk",
            repo="demo-repo",
        )
        return (
            target / ".agents" / "skills" / f"demo-brain-{skill}" / "SKILL.md"
        ).read_text(encoding="utf-8")


def test_query_skill_keeps_default_use_read_only():
    query = _installed_skill("query")

    for required in (
        "기본 조회는 읽기 전용",
        "명시적인 쓰기 요청",
        "demo-brain-ingest",
        "demo-brain-session-ingest",
    ):
        assert required in query

    for automatic_write in (
        "project-brain promote",
        "projection build-reuse",
        "project-brain index rebuild",
    ):
        assert automatic_write not in query


def test_audit_skill_reports_read_only_diagnostics_before_opt_in_updates():
    audit = _installed_skill("audit")

    for required in (
        "기본 실행은 읽기 전용",
        "project-brain audit",
        "--fetch --write-stale-cache",
        "checked",
        "skipped",
        "failures",
        "명시적인 수정 요청",
    ):
        assert required in audit
