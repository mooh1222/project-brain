import json
import re
from pathlib import Path

import pytest

from project_brain import cli
from project_brain.mutation import MutationOperation


ROOT = Path(__file__).parents[1]
ARCH = ROOT / "docs" / "architecture"
REQUIRED_DOCS = {
    "README.md",
    "runtime-map.md",
    "data-contracts.md",
    "change-map.md",
}

_SIMPLE_SUBCOMMAND_RUNNERS = {
    "index": cli._run_index,
    "session": cli._run_session,
    "projection": cli._run_projection,
    "graph": cli._run_graph,
    "snapshot": cli._run_snapshot,
    "context-replace": cli._run_context_replace,
}


def _read_architecture_doc(name: str) -> str:
    path = ARCH / name
    assert path.is_file(), f"missing architecture document: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def _runtime_contract() -> dict:
    text = _read_architecture_doc("runtime-map.md")
    match = re.search(
        r"<!-- architecture-contract:start -->\s*```json\s*(.*?)\s*```\s*"
        r"<!-- architecture-contract:end -->",
        text,
        re.DOTALL,
    )
    assert match is not None, "runtime-map.md has no architecture contract block"
    contract = json.loads(match.group(1))
    assert contract.get("schema_version") == 1
    return contract


def _contract_values(contract: dict, key: str) -> set[str]:
    values = contract.get(key)
    assert isinstance(values, list), f"architecture contract {key!r} must be a list"
    assert all(isinstance(value, str) and value for value in values)
    assert len(values) == len(set(values)), (
        f"architecture contract {key!r} has duplicates"
    )
    return set(values)


def _top_level_commands() -> set[str]:
    source = (ROOT / "src/project_brain/cli.py").read_text(encoding="utf-8")
    return set(
        re.findall(r"argv\[0\]\s*==\s*[\"']([^\"']+)[\"']", source)
    )


def _help_choices(runner, argv: list[str], capsys) -> set[str]:
    with pytest.raises(SystemExit) as exc:
        runner([*argv, "--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    match = re.search(r"\{([^{}]+)\}", output)
    assert match is not None, output
    return set(match.group(1).split(","))


def _subcommand_paths(capsys) -> set[str]:
    paths: set[str] = set()
    for command, runner in _SIMPLE_SUBCOMMAND_RUNNERS.items():
        paths.update(
            f"{command} {choice}"
            for choice in _help_choices(runner, [], capsys)
        )

    migration_modes = _help_choices(cli._run_migration, [], capsys)
    for mode in migration_modes:
        paths.update(
            f"migration {mode} {action}"
            for action in _help_choices(cli._run_migration, [mode], capsys)
        )
    return paths


def test_required_architecture_documents_exist():
    missing = sorted(name for name in REQUIRED_DOCS if not (ARCH / name).is_file())
    assert missing == []


def test_runtime_contract_matches_all_top_level_cli_commands():
    contract = _runtime_contract()
    assert _contract_values(contract, "top_level_commands") == _top_level_commands()


def test_runtime_contract_matches_all_subcommand_paths(capsys):
    contract = _runtime_contract()
    assert _contract_values(contract, "subcommand_paths") == _subcommand_paths(capsys)


def test_runtime_contract_matches_mutation_operations():
    contract = _runtime_contract()
    assert _contract_values(contract, "mutation_operations") == {
        operation.value for operation in MutationOperation
    }


def test_architecture_contract_paths_exist():
    contract = _runtime_contract()
    repo_root = ROOT.resolve()
    for key in ("source_paths", "test_paths", "doc_paths"):
        paths = _contract_values(contract, key)
        assert paths, f"architecture contract {key!r} must not be empty"
        for relative in sorted(paths):
            path = Path(relative)
            assert not path.is_absolute(), relative
            resolved = (ROOT / path).resolve()
            assert resolved.is_relative_to(repo_root), relative
            assert resolved.is_file(), relative


def test_living_architecture_docs_do_not_pin_test_counts():
    forbidden = {
        "pytest result": re.compile(r"\b\d[\d,]*\s+passed\b", re.IGNORECASE),
        "unittest result": re.compile(r"\bRan\s+\d[\d,]*\s+tests?\b", re.IGNORECASE),
        "Korean test count": re.compile(r"테스트\s+\d[\d,]*\s*(?:개|건)"),
    }
    for name in sorted(REQUIRED_DOCS):
        text = _read_architecture_doc(name)
        matched = [
            label for label, pattern in forbidden.items() if pattern.search(text)
        ]
        assert matched == [], f"{name} pins mutable test counts: {matched}"


def test_runtime_map_states_non_corpus_write_boundaries():
    text = _read_architecture_doc("runtime-map.md")
    required_phrases = (
        "build는 저장하지 않는다",
        "코퍼스 객체 변경만 MutationService",
        "query는 fresh index가 없어도",
        "search는 fresh index가 필요",
        "redaction_status 기반 restricted 라벨",
        "일부 query 경로",
        "EventLedgerRecord·TemporalFact",
        "search의 다섯 채널",
        "principal별 ACL을 집행하지 않는다",
        "session mark-processed",
        "audit은 stale-set cache를 쓴다",
    )
    missing = [phrase for phrase in required_phrases if phrase not in text]
    assert missing == []


def test_architecture_entry_states_authority_and_two_repo_boundary():
    text = _read_architecture_doc("README.md")
    required_phrases = (
        "명시 인자 > config > ConfigError",
        "엔진 레포",
        "데이터 레포",
        "현재 동작은 코드·테스트·CLI",
    )
    missing = [phrase for phrase in required_phrases if phrase not in text]
    assert missing == []


def test_primary_entrypoints_link_to_architecture_map():
    missing = []
    for relative in ("AGENTS.md", "README.md", "ROADMAP.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        if "docs/architecture/README.md" not in text:
            missing.append(relative)
    assert missing == []


def test_p0_ingest_integrity_flow_is_explicit():
    runtime = _read_architecture_doc("runtime-map.md")
    for token in (
        "CoverageContract",
        "expected planner",
        "MutationService",
        "단일 clock",
        "no-op receipt",
        "같은 좌표 재검증",
    ):
        assert token in runtime

    contracts = _read_architecture_doc("data-contracts.md")
    for token in (
        "timestamp owner map",
        "created_at",
        "updated_at",
        "verified_at",
        "generated_at",
        "reviewed_at",
        "object-templates",
        "다음 audit",
    ):
        assert token in contracts

    changes = _read_architecture_doc("change-map.md")
    for token in (
        "coverage",
        "timestamp",
        "receipt",
        "focused",
        "full",
        "brain/checks",
        "rebuild 불필요",
    ):
        assert token in changes

def test_runtime_map_separates_active_finalization_from_planned_p0_gate():
    runtime = _read_architecture_doc("runtime-map.md")
    match = re.search(
        r"## 전체 실행 흐름\s*```mermaid\s*(.*?)\s*```",
        runtime,
        re.DOTALL,
    )
    assert match is not None
    active_graph = match.group(1)
    for edge in (
        "Receipt -. installed batch .-> ReceiptRecovery[durable receipt recovery]",
        "ReceiptRecovery --> SemanticFinalizer[installed semantic finalization]",
        "SemanticFinalizer --> TailVerify[post-finalizer object-tail verification]",
    ):
        assert edge in active_graph
    assert "Receipt --> Foundation" not in active_graph

    for statement in (
        "Task 12–15에서 추가할 별도 P0 최종 gate",
        "현재 활성 경로가 아니다",
        "일반 ingest finalizer가 아니다",
        "finalizer를 호출하지 않는다",
        "index rebuild를 호출하지 않는다",
    ):
        assert statement in runtime


def test_task18_migration_boundaries_are_explicit():
    runtime = _read_architecture_doc("runtime-map.md")
    for token in (
        "quote inventory",
        "pre-snapshot",
        "binding",
        "verify-plan",
        "post-verify",
        "closure",
    ):
        assert token in runtime
    for option in (
        "--target-revision",
        "--binding",
        "--corpus-snapshot",
        "--snapshot-verify",
        "--closure",
        "--expected-engine-head",
        "--expected-bb2-head",
    ):
        assert option in runtime

    changes = _read_architecture_doc("change-map.md")
    for token in (
        "task18_verify.py",
        "task18_binding.py",
        "quote_debt.py",
        "display migration",
    ):
        assert token in changes

    contracts = _read_architecture_doc("data-contracts.md")
    for token in (
        "paired locator/ref title",
        "reviewed at ingest, not mechanically re-checkable now",
        "title만",
    ):
        assert token in contracts


def test_task18_plan_pins_eval_scenarios_and_post_audit_cache_policy():
    plan = (
        ROOT
        / "docs/superpowers/plans/2026-08-06-task18-display-labels-and-quote-debt.md"
    ).read_text(encoding="utf-8")

    def task_section(number: int) -> str:
        match = re.search(
            rf"^### Task {number}:.*?(?=^### Task \d+:|\Z)",
            plan,
            re.MULTILINE | re.DOTALL,
        )
        assert match is not None
        return match.group(0)

    task11 = task_section(11)
    task13 = task_section(13)
    eval_invocation = (
        '(\n'
        '  cd "$BB2"\n'
        '  PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" '
        '-m project_brain.cli eval \\\n'
        '    --brain-root "$BB2/brain" \\\n'
        '    --scenarios "$BB2/brain/eval_scenarios.json"\n'
        ')'
    )
    assert eval_invocation in task11
    assert eval_invocation in task13
    audit_invocation = (
        '--brain-root "$BB2/brain" --repo-root "$BB2" --no-fetch '
        "--no-stale-cache-write\n"
    )
    assert audit_invocation in task11
    assert (
        audit_invocation in task13
    )
    assert "--golden-set" not in task11
    assert "--golden-set" not in task13


@pytest.mark.parametrize("name", ("change-map.md", "runtime-map.md"))
def test_display_migration_preserve_exception_forbids_rebuild(name: str):
    text = _read_architecture_doc(name)
    paragraphs = re.split(r"\n\s*\n", text)
    matching = [
        paragraph
        for paragraph in paragraphs
        if "DISPLAY_MIGRATION" in paragraph and "PRESERVE" in paragraph
    ]
    assert len(matching) == 1
    paragraph = matching[0]
    assert "index rebuild를 하지 않는다" in paragraph
    assert "index DB bytes를 보존" in paragraph
