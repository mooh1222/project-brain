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


def test_p0_ingest_integrity_flow_and_deferred_migration_are_explicit():
    runtime = _read_architecture_doc("runtime-map.md")
    for token in (
        "CoverageContract",
        "expected planner",
        "MutationService",
        "단일 clock",
        "no-op receipt",
        "foundation gate",
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

    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    for token in (
        "P0 ingest integrity 완료 기준",
        "Task 18",
        "blocked handoff",
        "실코퍼스 migration은 미완료",
    ):
        assert token in roadmap
