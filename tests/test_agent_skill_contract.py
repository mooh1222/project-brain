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
            target
            / ".agents"
            / "skills"
            / f"demo-brain-{skill}"
            / relative
        ).read_text(encoding="utf-8")


def test_query_skill_verifies_current_code_and_keeps_default_use_read_only():
    query = _installed_skill("query")

    for required in (
        "기본 조회는 읽기 전용",
        "현재 checkout",
        "Brain에서 찾은 내용",
        "현재 코드에서 확인한 내용",
        "Brain에서 못 찾은 내용",
        "검색 표현 문제",
        "적재 누락",
        "명시적인 쓰기 요청",
        "객체 ID·채널별 건수",
        "확인한 path·symbol",
        "불일치·미확인 목록",
    ):
        assert required in query

    assert "Brain과 코드 모두에서 확인 못 함" not in query

    for automatic_write in (
        "project-brain promote --ids",
        "projection build-reuse",
        "project-brain index rebuild",
    ):
        assert automatic_write not in query


def test_audit_skill_reports_read_only_diagnostics_before_any_repair():
    audit = _installed_skill("audit")

    for required in (
        "project-brain audit --no-fetch --no-stale-cache-write",
        "먼저 보고",
        "명시적인 수정 요청",
        "checked",
        "skipped",
        "failures",
        "실제 사용 품질",
        "원격·캐시 갱신 audit",
    ):
        assert required in audit

    assert "즉시 연결" not in audit
    assert "## 언제" not in audit
    assert "기본 audit" not in audit


def test_ingest_skills_use_current_state_and_preserve_unrelated_user_work():
    ingest = _installed_skill("ingest")
    session = _installed_skill("session-ingest")

    for required in (
        "현재 코드와 ROADMAP.md",
        "실행 신호가 아니다",
        "git add -A",
        "git add .",
        "git commit -a",
        "승인된 경로",
        "자동 commit·stash",
    ):
        assert required in ingest + session

    assert "Use when BB2(LineBubble2)" not in session
    assert "사용자 명시 지시 = reviewed" not in session
    assert "코드로 확인 가능한 사실" in session
    assert "사용자 진술만으로 reviewed" in session


def test_backlog_recall_is_intent_routed_and_synthesized_notes_stay_unindexed():
    query = _installed_skill("query")
    session = _installed_skill("session-ingest")
    session_extract = _installed_reference(
        "session-ingest", "references/session-extract.md"
    )
    object_model = _installed_reference("ingest", "references/object-model.md")

    for trigger in (
        "우리 뭐 하기로 했지",
        "남은 일",
        "백로그",
        "나중에 고치기로 한 것",
    ):
        assert trigger in query
    for required in (
        "백로그 회상 질문에서만",
        "pending/insights.md",
        "backlog/development.md",
        "확정 여부",
        "진행 상태",
        "검증 상태",
        "출처",
        "Project Brain snapshot",
        ".project-brain.json",
        "백로그 파일 없음 — 조회 불가",
        "비어 있을 때만 `등록된 항목 없음`",
    ):
        assert required in query

    for trigger in ("나중에 고치자", "백로그에 남겨", "검증 대기로 보관"):
        assert trigger in session
    for required in (
        "미검증 합성 분석",
        "pending/insights.md",
        "개발 개선 제안",
        "backlog/development.md",
        "실제 원문",
        "비색인",
        "색인을 다시 만들 필요가 없다",
        "Git 추적 상태",
        "부모 디렉터리가 없으면 만든다",
    ):
        assert required in session

    installed_contract = session + session_extract + object_model
    assert "raw/sources/insights/backlog.md" not in installed_contract
    assert "guides/ops/knowledge" not in query + installed_contract


def test_installed_ingest_references_match_current_engine_contracts():
    with TemporaryDirectory() as td:
        target = Path(td)
        install(
            target,
            project="demo",
            brain_root="brain",
            default_branch="trunk",
            repo="demo-repo",
        )
        root = target / ".agents" / "skills" / "demo-brain-ingest"
        tools = (root / "references" / "ingest-tools.md").read_text(encoding="utf-8")
        object_model = (root / "references" / "object-model.md").read_text(encoding="utf-8")
        playbook = (
            root / "references" / "system-domain-playbook.md"
        ).read_text(encoding="utf-8")
        domain_spec = (root / "scripts" / "domain_spec.template.py").read_text(
            encoding="utf-8"
        )
        extract_template = (root / "scripts" / "extract_template.js").read_text(
            encoding="utf-8"
        )
        session = target / ".agents" / "skills" / "demo-brain-session-ingest"
        dev_ingest = (session / "references" / "dev-ingest.md").read_text(
            encoding="utf-8"
        )
        session_extract = (session / "references" / "session-extract.md").read_text(
            encoding="utf-8"
        )

    assert "Task 18 migration" not in tools
    assert "P0 foundation gate — 일반 적재 finalizer와 별개" not in tools
    assert "reviewed_at=\"<실제 검토 시각 ISO8601>\"" in tools
    assert "적재 당시 검토" in object_model
    assert "기계적으로 다시 대조" in object_model
    assert "--coverage-file coverage.json" in playbook
    assert "git rev-parse <trunk-ref>" in domain_spec
    assert "--short=10" not in domain_spec
    assert "verdict: \"pass\"" in extract_template
    assert "extract.atoms로 폴백" not in extract_template
    assert "라인=" not in dev_ingest
    assert "줄번호" not in dev_ingest
    assert "finalization.ok=true" in session_extract
    assert "실패가 0" in session_extract
    assert "실패하면 unprocessed" in session_extract
    assert "커밋 먼저" not in tools
    for safe_git_rule in (
        "git add -A",
        "git add .",
        "git commit -a",
        "승인된 경로",
        "자동 commit·stash",
    ):
        assert safe_git_rule in tools
