"""설치되는 적재·세션 스킬이 엔진의 안전 경계를 그대로 안내하는지 검증한다."""
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


def test_confirmation_requires_an_explicit_promotion_target_and_operation():
    tools = _installed_reference("ingest", "references/ingest-tools.md")

    for required in (
        "단순 확인",
        "승격 대상",
        "승격 동작",
        "실행하지 않는다",
    ):
        assert required in tools


def test_installed_ingest_paths_share_one_conditional_glossary_criterion():
    with TemporaryDirectory() as td:
        target = Path(td)
        install(
            target,
            project="demo",
            brain_root="brain",
            default_branch="trunk",
            repo="demo-repo",
        )
        skills = target / ".agents" / "skills"
        ingest_root = skills / "demo-brain-ingest"
        criterion_path = ingest_root / "references" / "glossary-criteria.md"
        criterion = criterion_path.read_text(encoding="utf-8")
        installed_skills = {
            name: (skills / f"demo-brain-{name}" / "SKILL.md").read_text(
                encoding="utf-8"
            )
            for name in ("ingest", "session-ingest", "draft", "audit", "query")
        }

        assert criterion_path.is_file()
        for name in ("session-ingest", "draft", "audit", "query"):
            assert not (
                skills
                / f"demo-brain-{name}"
                / "references"
                / "glossary-criteria.md"
            ).exists()
        sibling_reference = "../demo-brain-ingest/references/glossary-criteria.md"
        for name in ("session-ingest", "draft", "audit"):
            resolved = (
                skills / f"demo-brain-{name}" / sibling_reference
            ).resolve(strict=True)
            assert resolved == criterion_path.resolve(strict=True)

    assert (
        "`GlossaryTerm`을 생성하거나 변경할 때 "
        "`references/glossary-criteria.md`를 먼저 읽는다."
        in installed_skills["ingest"]
    )
    assert (
        "현재 세션이나 과거 세션에서 어휘 후보를 추출할 때 "
        "`../demo-brain-ingest/references/glossary-criteria.md`를 먼저 읽는다."
        in installed_skills["session-ingest"]
    )
    assert (
        "기존 `GlossaryTerm`의 어휘 품질을 감사할 때 "
        "`../demo-brain-ingest/references/glossary-criteria.md`를 먼저 읽는다."
        in installed_skills["audit"]
    )
    assert "어휘 관찰을 잠정 분류할 때" in installed_skills["draft"]
    assert (
        "../demo-brain-ingest/references/glossary-criteria.md"
        in installed_skills["draft"]
    )
    for audit_trigger in ("어휘 감사", "코드 토큰 과잉 적재"):
        assert audit_trigger in installed_skills["audit"]
    assert "glossary-criteria.md" not in installed_skills["query"]

    for role_boundary in (
        "현재 세션과 과거 세션",
        "진행 중·미결 재료",
        "정식 적재 가능한 지식",
    ):
        assert role_boundary in installed_skills["session-ingest"]

    for required in (
        "실제 이름 사용",
        "독립 개념",
        "명명 근거",
        "enum·필드·변수명",
        "`DomainMapping`",
        "`CodeLocator`",
        "무객체",
        "대표어",
        "동의어",
        "별칭",
        "`candidate GlossaryTerm`",
        "사용자 판단",
    ):
        assert required in criterion

    example_rows = {
        expression: next(
            line for line in criterion.splitlines() if f"| `{expression}` |" in line
        )
        for expression in (
            "입장팝업",
            "OriginalPopup",
            "카누 레이스 상태",
            "IDLE",
            "RPMAP",
        )
    }
    assert "`GlossaryTerm`" in example_rows["입장팝업"]
    assert "`GlossaryTerm` 아님" in example_rows["OriginalPopup"]
    assert "`CodeLocator`" in example_rows["OriginalPopup"]
    assert "`GlossaryTerm`" in example_rows["카누 레이스 상태"]
    assert "`DomainMapping`" in example_rows["카누 레이스 상태"]
    assert "`GlossaryTerm` 아님" in example_rows["IDLE"]
    assert "`DomainMapping`" in example_rows["IDLE"]
    assert "무객체" in example_rows["RPMAP"]


def test_draft_skill_owns_lifecycle_and_session_ingest_only_routes_material():
    draft = _installed_skill("draft")
    session = _installed_skill("session-ingest")

    for command in (
        "project-brain draft list",
        "project-brain draft create",
        "project-brain draft show",
        "project-brain draft update",
        "project-brain draft lint",
    ):
        assert command in draft
    assert draft.index("project-brain draft list") < draft.index(
        "project-brain draft show"
    )
    for boundary in (
        "선택받기 전에는 본문 전체를 읽지 않는다",
        "draft_stale_sha",
        "한 초안에는 한 번에 한",
        "정식 Brain 객체나 raw 원문, 일반 query의 근거가 아니다",
        "소비 프로젝트 정책과 사용자가 준 권한",
    ):
        assert boundary in draft
    for source_rule in (
        "기획서나 현행 문서가 있으면 그 자료를 초기 source packet으로 삼는다",
        "없으면 사용자 대화와 현재 코드에서 시작한다",
    ):
        assert source_rule in draft

    assert "demo-brain-draft" in session
    assert "진행 중·미결 재료" in session
    assert "정식 적재 가능한 지식" in session
    assert "지식 초안의 생성·재개·갱신 수명주기" in session


def test_installed_ingest_skills_preserve_user_work_and_pending_boundaries():
    ingest = _installed_skill("ingest")
    session = _installed_skill("session-ingest")
    session_extract = _installed_reference("session-ingest", "references/session-extract.md")

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


def test_session_completion_uses_the_receipt_bound_cli_not_mark_processed():
    session_extract = _installed_reference("session-ingest", "references/session-extract.md")

    for required in (
        "project-brain session complete",
        "--transcript",
        "--manifest",
        "--report",
        "canonical receipt",
        "finalization.ok=true",
        "실패하면 unprocessed",
        "재개 정보",
    ):
        assert required in session_extract
    assert "session mark-processed" not in session_extract


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


def test_query_skill_separates_general_recall_from_deterministic_query_axes():
    query = _installed_skill("query")

    for required in (
        "일반 의미·코드 위치·개발 착수",
        "핵심 객체",
        "project-brain show <object_id>",
        "`project-brain query`는 변경 이유·현재 상태·과거 시점·근거 사슬만",
    ):
        assert required in query

    for removed_query_field in (
        "additional_candidates",
        "promotable_candidate_ids",
        "candidate_locators",
    ):
        assert removed_query_field not in query


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


def test_query_skill_documents_scope_and_display_limit_options():
    query = _installed_skill("query")

    for required in (
        "--context-id <id>",
        "--all-contexts",
        "--top-k",
        "기본 10",
        # scope 사실을 읽는 법과, scope가 거르지 않는 채널을 함께 안내한다.
        "origin",
        "advisories",
        # 필터 없음의 두 이유를 가르는 값이 문서에 다 나와야 한다.
        "`disabled`",
        "`none`",
        "`inferred`",
        "`explicit`",
    ):
        assert required in query

    # 다른 서브커맨드의 --scope(promote 승격 단위, draft 범위 서술)와 섞이지 않게
    # 조회 스킬은 그 이름을 쓰지 않는다.
    assert "search \"<질문>\" --scope" not in query
