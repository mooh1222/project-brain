from project_brain.display_contract import (
    canonical_locator_title,
    non_title_sha256,
    paired_code_locator_id,
)


def test_canonical_locator_title_prefers_symbol_and_has_stable_path_fallback():
    assert canonical_locator_title({
        "id": "code.ctx.anchor",
        "path": "Source/Foo.cpp",
        "symbol": "Ns::run",
    }) == "Ns::run"
    assert canonical_locator_title({
        "id": "code.ctx.anchor",
        "path": "Source/Foo.cpp",
    }) == "Foo.cpp:anchor"
    assert canonical_locator_title({}) == "unknown:unknown"


def test_paired_code_locator_id_accepts_only_code_locator_evidence_refs():
    assert paired_code_locator_id({
        "kind": "EvidenceRef",
        "ref_type": "code_locator",
        "locator": {"code_locator_id": "code.ctx.anchor"},
    }) == "code.ctx.anchor"
    assert paired_code_locator_id({
        "kind": "EvidenceRef",
        "ref_type": "spec_section",
        "locator": {"code_locator_id": "code.ctx.anchor"},
    }) is None
    assert paired_code_locator_id({
        "kind": "EvidenceRef",
        "ref_type": "code_locator",
        "locator": {"section": "1"},
    }) is None


def test_non_title_sha256_ignores_only_title():
    before = {"id": "code.ctx.anchor", "title": "old", "summary": "same"}
    title_only = {**before, "title": "new"}
    non_title_change = {**title_only, "summary": "changed"}

    assert non_title_sha256(before) == non_title_sha256(title_only)
    assert non_title_sha256(before) != non_title_sha256(non_title_change)
