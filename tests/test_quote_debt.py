from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from project_brain.foundation import canonical_receipt_bytes
from project_brain.quote_debt import (
    QuoteDebtError,
    build_quote_debt_inventory,
    verify_quote_debt_inventory,
)
from project_brain.store import BrainStore


GENERATED_AT = "2026-08-06T12:00:00+09:00"
TARGET_SHA = "target-sha"


def _target_ids_sha256(target_ids: list[str]) -> str:
    payload = json.dumps(
        target_ids,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _measurement_value(target_ids: list[str]) -> dict[str, object]:
    return {
        "quote_backlog": {
            "target_count": len(target_ids),
            "target_ids": target_ids,
            "target_ids_sha256": _target_ids_sha256(target_ids),
        }
    }


def _fresh_stale_report() -> dict[str, object]:
    return {
        "target_head": TARGET_SHA,
        "candidates": [
            {
                "mapping_id": "mapping.ctx.stale",
                "mapping_key": "stale",
                "stale_locators": [
                    {
                        "locator_id": "code.ctx.stale",
                        "path": "src/Stale.cpp",
                        "change_type": "M",
                        "from_commit": "commit-stale",
                    }
                ],
            }
        ],
        "locator_group": [
            {
                "locator_id": "code.ctx.stale",
                "path": "src/Stale.cpp",
                "from_commit": "commit-stale",
                "target_head": TARGET_SHA,
                "change_type": "M",
                "blocking_affected_mapping_ids": ["mapping.ctx.stale"],
                "nonblocking_affected_mapping_ids": [],
            }
        ],
        "unmerged_anchors": [
            {
                "locator_id": "code.ctx.unmerged",
                "path": "src/Unmerged.cpp",
                "from_commit": "commit-unmerged",
                "reason": "not_ancestor",
                "blocking_affected_mapping_ids": [],
                "nonblocking_affected_mapping_ids": [],
            }
        ],
        "coverage": {
            "covered_mappings": ["mapping.ctx.stale"],
            "uncovered_mappings": [],
        },
    }


def _locator(
    locator_id: str,
    *,
    title: str,
    path: str,
    symbol: str,
    status: str = "reviewed",
    **extra: object,
) -> dict[str, object]:
    return {
        "id": locator_id,
        "kind": "CodeLocator",
        "title": title,
        "status": status,
        "repo": "demoapp",
        "path": path,
        "symbol": symbol,
        "commit_sha": f"commit-{locator_id.rsplit('.', 1)[-1]}",
        "locator_source": "rg",
        "verified_at": "2026-07-01T00:00:00Z",
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
        **extra,
    }


def _paired_ref(ref_id: str, locator_id: str, *, title: str) -> dict[str, object]:
    return {
        "id": ref_id,
        "kind": "EvidenceRef",
        "title": title,
        "status": "reviewed",
        "ref_type": "code_locator",
        "locator": {"code_locator_id": locator_id},
        "summary": "legacy evidence",
        "created_at": "2026-07-01T00:00:00Z",
        "updated_at": "2026-07-01T00:00:00Z",
    }


def _with_titles(store: BrainStore, titles: dict[str, str]) -> BrainStore:
    objects = []
    for obj in store.all():
        objects.append({**obj, "title": titles.get(obj["id"], obj.get("title"))})
    return BrainStore({obj["id"]: obj for obj in objects})


@pytest.fixture
def quote_fixture(tmp_path: Path) -> dict[str, object]:
    locators = [
        _locator(
            "code.ctx.stale",
            title="legacy stale",
            path="src/Stale.cpp",
            symbol="Ns::stale",
        ),
        _locator(
            "code.ctx.unmerged",
            title="legacy unmerged",
            path="src/Unmerged.cpp",
            symbol="Ns::unmerged",
        ),
        _locator(
            "code.ctx.lines",
            title="legacy lines",
            path="src/Lines.cpp",
            symbol="Ns::lines",
            line_start=7,
            line_end=9,
        ),
        _locator(
            "code.ctx.candidate",
            title="legacy candidate",
            path="src/Candidate.cpp",
            symbol="Ns::candidate",
            status="candidate",
        ),
        _locator(
            "code.ctx.bad-symbol",
            title="legacy bad symbol",
            path="src/Bad.cpp",
            symbol="Ns::run / descriptive",
        ),
    ]
    excluded_with_quote = _locator(
        "code.ctx.has-quote",
        title="already bound",
        path="src/Bound.cpp",
        symbol="Ns::bound",
        verified_quote="void Ns::bound() {}",
    )
    refs = [
        _paired_ref("evref.ctx.stale-a", "code.ctx.stale", title="legacy ref A"),
        _paired_ref("evref.ctx.stale-b", "code.ctx.stale", title="legacy ref B"),
        _paired_ref("evref.ctx.wrong", "code.ctx.has-quote", title="other ref"),
        {
            **_paired_ref(
                "evref.ctx.not-code", "code.ctx.stale", title="not a code ref"
            ),
            "ref_type": "spec_section",
        },
    ]
    objects = [*reversed(locators), excluded_with_quote, *reversed(refs)]
    existing = BrainStore({obj["id"]: obj for obj in objects})
    quote_debt_ids = sorted(locator["id"] for locator in locators)
    measurement_path = tmp_path / "measurement.json"
    measurement_bytes = canonical_receipt_bytes(_measurement_value(quote_debt_ids))
    measurement_path.write_bytes(measurement_bytes)
    expected_titles = {
        locator["id"]: locator["symbol"]
        for locator in locators
    }
    expected_titles.update({
        "evref.ctx.stale-a": "Ns::stale",
        "evref.ctx.stale-b": "Ns::stale",
    })
    return {
        "existing": existing,
        "measurement_path": measurement_path,
        "expected_measurement_sha256": hashlib.sha256(measurement_bytes).hexdigest(),
        "stale_report": _fresh_stale_report(),
        "engine_sha": "engine-sha",
        "repo_sha": "repo-sha",
        "target_revision_sha": TARGET_SHA,
        "brain_root": tmp_path / "brain",
        "index_db_path": tmp_path / "brain" / "index.sqlite3",
        "expected_titles": expected_titles,
    }


def _build(fixture: dict[str, object]) -> dict[str, object]:
    args = {key: value for key, value in fixture.items() if key != "expected_titles"}
    return build_quote_debt_inventory(**args, generated_at=GENERATED_AT)


def test_quote_inventory_is_canonical_and_deterministic(quote_fixture):
    first = _build(quote_fixture)
    second = _build(quote_fixture)

    assert canonical_receipt_bytes(first) == canonical_receipt_bytes(second)
    assert [row["locator_id"] for row in first["rows"]] == sorted(
        first["quote_debt_ids"]
    )
    assert first["quote_debt_ids"] == [
        "code.ctx.bad-symbol",
        "code.ctx.candidate",
        "code.ctx.lines",
        "code.ctx.stale",
        "code.ctx.unmerged",
    ]
    assert first["quote_debt_ids_sha256"] == _target_ids_sha256(
        first["quote_debt_ids"]
    )


def test_canonical_synthetic_measurement_uses_quote_backlog_schema(quote_fixture):
    measurement_bytes = quote_fixture["measurement_path"].read_bytes()
    measurement = json.loads(measurement_bytes)
    backlog = measurement["quote_backlog"]

    assert canonical_receipt_bytes(measurement) == measurement_bytes
    assert set(backlog) == {
        "target_count",
        "target_ids",
        "target_ids_sha256",
    }
    assert backlog["target_count"] == len(backlog["target_ids"]) == 5
    assert backlog["target_ids"] == sorted(set(backlog["target_ids"]))
    assert backlog["target_ids_sha256"] == _target_ids_sha256(
        backlog["target_ids"]
    )
    assert _build(quote_fixture)["quote_debt_ids_sha256"] == backlog[
        "target_ids_sha256"
    ]


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda backlog: backlog.update(target_count=999),
            "measurement_quote_debt_count_mismatch",
        ),
        (
            lambda backlog: backlog.update(target_ids_sha256="0" * 64),
            "measurement_quote_debt_ids_sha256_mismatch",
        ),
        (
            lambda backlog: backlog.update(
                target_ids=list(reversed(backlog["target_ids"]))
            ),
            "measurement_quote_debt_ids_not_canonical",
        ),
        (
            lambda backlog: backlog.update(
                target_ids=[*backlog["target_ids"], backlog["target_ids"][0]],
                target_count=backlog["target_count"] + 1,
            ),
            "measurement_quote_debt_ids_not_canonical",
        ),
    ],
    ids=["count", "id-hash", "order", "duplicate"],
)
def test_quote_inventory_rejects_invalid_measurement_backlog_metadata(
    quote_fixture,
    mutate,
    expected_code,
):
    measurement_path = quote_fixture["measurement_path"]
    measurement = json.loads(measurement_path.read_bytes())
    mutate(measurement["quote_backlog"])
    measurement_bytes = canonical_receipt_bytes(measurement)
    measurement_path.write_bytes(measurement_bytes)
    args = {
        key: value
        for key, value in quote_fixture.items()
        if key not in {"expected_titles", "expected_measurement_sha256"}
    }

    with pytest.raises(QuoteDebtError, match=expected_code):
        build_quote_debt_inventory(
            **args,
            expected_measurement_sha256=hashlib.sha256(
                measurement_bytes
            ).hexdigest(),
            generated_at=GENERATED_AT,
        )


def test_quote_inventory_records_five_debt_axes_and_locator_fields(quote_fixture):
    value = _build(quote_fixture)
    by_id = {row["locator_id"]: row for row in value["rows"]}

    assert by_id["code.ctx.stale"]["axes"]["stale"] is True
    assert (
        by_id["code.ctx.unmerged"]["axes"]["unmerged_or_unverifiable"]
        is True
    )
    assert by_id["code.ctx.lines"]["axes"]["line_range"] is True
    assert by_id["code.ctx.candidate"]["axes"]["candidate"] is True
    assert by_id["code.ctx.bad-symbol"]["axes"]["noncanonical_symbol"] is True
    assert {
        "context": "ctx",
        "path": "src/Stale.cpp",
        "symbol": "Ns::stale",
        "commit": "commit-stale",
        "status": "reviewed",
        "source": "rg",
    }.items() <= by_id["code.ctx.stale"].items()


def test_quote_inventory_keeps_only_exact_paired_refs_in_sorted_one_to_many_list(
    quote_fixture,
):
    value = _build(quote_fixture)
    stale_row = next(
        row for row in value["rows"] if row["locator_id"] == "code.ctx.stale"
    )

    assert [ref["id"] for ref in stale_row["paired_refs"]] == [
        "evref.ctx.stale-a",
        "evref.ctx.stale-b",
    ]
    assert [ref["title"] for ref in stale_row["paired_refs"]] == [
        "legacy ref A",
        "legacy ref B",
    ]
    assert all(len(ref["non_title_sha256"]) == 64 for ref in stale_row["paired_refs"])
    assert len(stale_row["non_title_sha256"]) == 64


def test_quote_inventory_rejects_measurement_sha_mismatch(quote_fixture):
    args = {
        key: value
        for key, value in quote_fixture.items()
        if key not in {"expected_titles", "expected_measurement_sha256"}
    }
    with pytest.raises(QuoteDebtError, match="measurement"):
        build_quote_debt_inventory(
            **args,
            expected_measurement_sha256="0" * 64,
            generated_at=GENERATED_AT,
        )


def test_quote_inventory_rejects_measurement_id_set_mismatch(quote_fixture):
    measurement_path = quote_fixture["measurement_path"]
    measurement_bytes = canonical_receipt_bytes(
        _measurement_value(["code.ctx.not-current-debt"])
    )
    measurement_path.write_bytes(measurement_bytes)
    args = {
        key: value
        for key, value in quote_fixture.items()
        if key not in {"expected_titles", "expected_measurement_sha256"}
    }

    with pytest.raises(QuoteDebtError, match="measurement"):
        build_quote_debt_inventory(
            **args,
            expected_measurement_sha256=hashlib.sha256(measurement_bytes).hexdigest(),
            generated_at=GENERATED_AT,
        )


def test_quote_inventory_requires_stale_report_for_exact_target_revision(quote_fixture):
    quote_fixture["stale_report"] = {
        **quote_fixture["stale_report"],
        "target_head": "other-target",
    }

    with pytest.raises(QuoteDebtError, match="target"):
        _build(quote_fixture)


def test_quote_inventory_rejects_stale_set_cache_like_input(quote_fixture):
    quote_fixture["stale_report"] = {
        "target_head": TARGET_SHA,
        "computed_at": "2026-08-06T12:00:00+09:00",
        "stale_by_mapping": {},
    }

    with pytest.raises(QuoteDebtError, match="stale_report"):
        _build(quote_fixture)


def test_quote_inventory_rejects_incomplete_fresh_stale_report_row(quote_fixture):
    stale_report = deepcopy(quote_fixture["stale_report"])
    stale_report["locator_group"] = [{"locator_id": "code.ctx.stale"}]
    quote_fixture["stale_report"] = stale_report

    with pytest.raises(QuoteDebtError, match="stale_report"):
        _build(quote_fixture)


def test_pre_migration_verifier_requires_exact_unchanged_projection(quote_fixture):
    value = _build(quote_fixture)
    receipt = verify_quote_debt_inventory(
        value,
        existing=quote_fixture["existing"],
        stale_report=quote_fixture["stale_report"],
        phase="pre_migration",
    )

    assert receipt["ok"] is True
    assert receipt["phase"] == "pre_migration"
    with pytest.raises(QuoteDebtError, match="pre_migration"):
        verify_quote_debt_inventory(
            value,
            existing=quote_fixture["existing"],
            stale_report=quote_fixture["stale_report"],
            phase="pre_migration",
            authorized_titles=quote_fixture["expected_titles"],
        )


def test_post_migration_verify_allows_only_bound_title_changes(quote_fixture):
    value = _build(quote_fixture)
    migrated = _with_titles(
        quote_fixture["existing"], quote_fixture["expected_titles"]
    )

    receipt = verify_quote_debt_inventory(
        value,
        existing=migrated,
        stale_report=quote_fixture["stale_report"],
        phase="post_migration",
        authorized_titles=quote_fixture["expected_titles"],
    )

    assert receipt["ok"] is True
    assert receipt["phase"] == "post_migration"


def test_post_migration_accepts_verified_binding_style_authorization_superset(
    quote_fixture,
):
    value = _build(quote_fixture)
    binding_titles = {
        **quote_fixture["expected_titles"],
        "code.ctx.has-quote": "Ns::bound",
        "evref.ctx.wrong": "Ns::bound",
    }
    migrated = _with_titles(quote_fixture["existing"], binding_titles)

    receipt = verify_quote_debt_inventory(
        value,
        existing=migrated,
        stale_report=quote_fixture["stale_report"],
        phase="post_migration",
        authorized_titles=binding_titles,
    )

    assert receipt["ok"] is True
    assert receipt["phase"] == "post_migration"


def test_post_migration_rejects_empty_authorization_on_pre_state(quote_fixture):
    value = _build(quote_fixture)

    with pytest.raises(QuoteDebtError, match="post_migration_authorized_titles"):
        verify_quote_debt_inventory(
            value,
            existing=quote_fixture["existing"],
            stale_report=quote_fixture["stale_report"],
            phase="post_migration",
            authorized_titles={},
        )


def test_post_migration_rejects_partial_authorization_and_partial_store(
    quote_fixture,
):
    value = _build(quote_fixture)
    partial_titles = {"code.ctx.stale": "Ns::stale"}
    partially_migrated = _with_titles(quote_fixture["existing"], partial_titles)

    with pytest.raises(QuoteDebtError, match="post_migration_authorized_titles"):
        verify_quote_debt_inventory(
            value,
            existing=partially_migrated,
            stale_report=quote_fixture["stale_report"],
            phase="post_migration",
            authorized_titles=partial_titles,
        )


def test_post_migration_rejects_noncanonical_expected_title(quote_fixture):
    value = _build(quote_fixture)
    wrong_titles = {
        **quote_fixture["expected_titles"],
        "code.ctx.stale": "Wrong::title",
    }
    wrongly_migrated = _with_titles(quote_fixture["existing"], wrong_titles)

    with pytest.raises(QuoteDebtError, match="post_migration_authorized_titles"):
        verify_quote_debt_inventory(
            value,
            existing=wrongly_migrated,
            stale_report=quote_fixture["stale_report"],
            phase="post_migration",
            authorized_titles=wrong_titles,
        )


def test_post_migration_requires_authorization_and_rejects_payload_drift(quote_fixture):
    value = _build(quote_fixture)
    with pytest.raises(QuoteDebtError, match="post_migration"):
        verify_quote_debt_inventory(
            value,
            existing=quote_fixture["existing"],
            stale_report=quote_fixture["stale_report"],
            phase="post_migration",
        )

    migrated = _with_titles(
        quote_fixture["existing"], quote_fixture["expected_titles"]
    )
    objects = {obj["id"]: dict(obj) for obj in migrated.all()}
    objects["code.ctx.stale"]["path"] = "src/Unauthorized.cpp"
    with pytest.raises(QuoteDebtError, match="non-title|projection"):
        verify_quote_debt_inventory(
            value,
            existing=BrainStore(objects),
            stale_report=quote_fixture["stale_report"],
            phase="post_migration",
            authorized_titles=quote_fixture["expected_titles"],
        )


def test_inventory_json_has_no_non_json_values(quote_fixture):
    value = _build(quote_fixture)
    assert json.loads(canonical_receipt_bytes(value)) == value


def test_canonical_json_round_trip_remains_verifiable(quote_fixture):
    value = _build(quote_fixture)
    loaded = json.loads(canonical_receipt_bytes(value))

    assert verify_quote_debt_inventory(
        loaded,
        existing=quote_fixture["existing"],
        stale_report=quote_fixture["stale_report"],
        phase="pre_migration",
    )["ok"] is True


def test_inventory_verifier_rejects_quote_debt_id_hash_mismatch(quote_fixture):
    value = {**_build(quote_fixture), "quote_debt_ids_sha256": "0" * 64}

    with pytest.raises(QuoteDebtError, match="inventory_quote_debt_ids_sha256"):
        verify_quote_debt_inventory(
            value,
            existing=quote_fixture["existing"],
            stale_report=quote_fixture["stale_report"],
            phase="pre_migration",
        )
