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


def _installed_reference(skill: str, relative: str) -> str:
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
            target / ".agents" / "skills" / f"demo-brain-{skill}" / relative
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


def test_ingest_confirmation_requires_an_explicit_target_and_operation():
    tools = _installed_reference("ingest", "references/ingest-tools.md")

    for required in (
        "단순 확인",
        "승격 대상",
        "승격 동작",
        "실행하지 않는다",
    ):
        assert required in tools


def test_ingest_skills_preserve_unrelated_user_work_and_pending_boundaries():
    ingest = _installed_skill("ingest")
    session = _installed_skill("session-ingest")
    session_extract = _installed_reference(
        "session-ingest", "references/session-extract.md"
    )

    for safe_git_rule in (
        "git add -A",
        "git add .",
        "git commit -a",
        "승인된 경로",
        "자동 commit·stash",
    ):
        assert safe_git_rule in ingest + session

    for boundary in (
        "pending/insights.md",
        "backlog/development.md",
        "비색인",
        "Project Brain snapshot",
        "실제 원문",
    ):
        assert boundary in session + session_extract
    assert "raw/sources/insights/backlog.md" not in session + session_extract


def test_session_is_marked_processed_only_after_exact_success_receipts():
    session_extract = _installed_reference(
        "session-ingest", "references/session-extract.md"
    )

    for required in (
        "canonical receipt",
        "exact",
        "실패가 0",
        "finalization.ok=true",
        "실패하면 unprocessed",
        "재개 정보",
    ):
        assert required in session_extract
