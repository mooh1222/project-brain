import json
from pathlib import Path

import pytest

from project_brain.evidence_plan import (
    EvidencePlanError,
    EvidencePlanMatch,
    EvidencePlanRequirement,
    EvidencePlanV1,
    parse_evidence_plan,
)


_CANONICAL_COMMON_CLAIMS_PAYLOAD = (
    '{"entries":[{"claimed_producer":{"id":"codex","kind":"agent","version":"1"},'
    '"claimed_verifiers":[{"id":"reviewer","kind":"human","version":"1"}],'
    '"source":{"checks":[{"authority":"human","id":"reviewed-brief",'
    '"outcome":"pass","summary":"확인"}],"type":"common_claims"},'
    '"target_id":"candidate.alpha"}],"version":1}'
).encode("utf-8")


def test_accepts_canonical_plan():
    plan = parse_evidence_plan(_CANONICAL_COMMON_CLAIMS_PAYLOAD + b"\n")

    assert isinstance(plan, EvidencePlanV1)
    assert plan.canonical_bytes() == _CANONICAL_COMMON_CLAIMS_PAYLOAD


def _canonical_file(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _entry(*, target_id: str, source: dict[str, object]) -> dict[str, object]:
    return {
        "target_id": target_id,
        "source": source,
        "claimed_producer": {"kind": "agent", "id": "codex", "version": "1"},
        "claimed_verifiers": [
            {"kind": "human", "id": "reviewer", "version": "1"},
        ],
    }


def _plan(*entries: dict[str, object]) -> dict[str, object]:
    return {"version": 1, "entries": list(entries)}


def test_rejects_exact_shape():
    valid = _plan(_entry(
        target_id="raw.alpha",
        source={"type": "raw_source_observation", "path": "raw/sources/alpha.txt"},
    ))
    assert parse_evidence_plan(_canonical_file(valid)).canonical_bytes() == (
        _canonical_file(valid)[:-1]
    )

    for path in ("/raw/sources/alpha.txt", "raw/sources//alpha.txt", "raw/sources/../alpha.txt", "raw\\sources\\alpha.txt"):
        invalid = _plan(_entry(
            target_id="raw.alpha",
            source={"type": "raw_source_observation", "path": path},
        ))
        with pytest.raises(EvidencePlanError) as exc:
            parse_evidence_plan(_canonical_file(invalid))
        assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_nul_raw_source_path():
    invalid = _plan(_entry(
        target_id="raw.alpha",
        source={
            "type": "raw_source_observation",
            "path": "raw/sources/alpha\x00.txt",
        },
    ))

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(invalid))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_existing_sources():
    valid = _plan(_entry(
        target_id="derived.alpha",
        source={"type": "existing_sources"},
    ))
    assert parse_evidence_plan(_canonical_file(valid)).canonical_bytes() == (
        _canonical_file(valid)[:-1]
    )

    invalid = _plan(_entry(
        target_id="derived.alpha",
        source={"type": "existing_sources", "source_object_ids": []},
    ))
    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(invalid))
    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_entry():
    invalid = _entry(
        target_id="derived.alpha",
        source={"type": "existing_sources"},
    )
    invalid["unexpected"] = True

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_common_claims():
    valid_source = {
        "type": "common_claims",
        "checks": [
            {
                "id": "reviewed-brief",
                "outcome": "pass",
                "authority": "human",
                "summary": "확인",
            },
        ],
    }
    assert parse_evidence_plan(_canonical_file(_plan(_entry(
        target_id="common.alpha",
        source=valid_source,
    ))))

    invalid_source = {**valid_source, "unexpected": True}
    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(_entry(
            target_id="common.alpha",
            source=invalid_source,
        ))))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_claimed_producer():
    invalid = _entry(
        target_id="derived.alpha",
        source={"type": "existing_sources"},
    )
    invalid["claimed_producer"] = {
        "kind": "engine",
        "id": "engine",
        "version": "1",
    }

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_claimed_verifier():
    invalid = _entry(
        target_id="derived.alpha",
        source={"type": "existing_sources"},
    )
    invalid["claimed_verifiers"] = [
        {"kind": "adapter", "id": "adapter", "version": "1"},
    ]

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    (
        ("actor_kind", []),
        ("actor_kind", {}),
        ("check_outcome", []),
        ("check_outcome", {}),
        ("check_authority", []),
        ("check_authority", {}),
        ("source_type", []),
        ("source_type", {}),
    ),
)
def test_rejects_unhashable_nested_schema_values(
    field: str,
    invalid_value: object,
):
    if field == "actor_kind":
        entry = _entry(
            target_id="derived.alpha",
            source={"type": "existing_sources"},
        )
        entry["claimed_producer"] = {
            "kind": invalid_value,
            "id": "codex",
            "version": "1",
        }
    elif field == "check_outcome":
        entry = _entry(
            target_id="common.alpha",
            source={
                "type": "common_claims",
                "checks": [{
                    "id": "reviewed-brief",
                    "outcome": invalid_value,
                    "authority": "human",
                    "summary": "확인",
                }],
            },
        )
    elif field == "check_authority":
        entry = _entry(
            target_id="common.alpha",
            source={
                "type": "common_claims",
                "checks": [{
                    "id": "reviewed-brief",
                    "outcome": "pass",
                    "authority": invalid_value,
                    "summary": "확인",
                }],
            },
        )
    else:
        entry = _entry(
            target_id="derived.alpha",
            source={"type": invalid_value},
        )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(entry)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_target_order():
    plan = _plan(
        _entry(
            target_id="target.z",
            source={"type": "existing_sources"},
        ),
        _entry(
            target_id="target.a",
            source={"type": "existing_sources"},
        ),
    )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(plan))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_duplicate_target():
    plan = _plan(
        _entry(
            target_id="target.alpha",
            source={"type": "existing_sources"},
        ),
        _entry(
            target_id="target.alpha",
            source={"type": "existing_sources"},
        ),
    )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(plan))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_verifier_order():
    invalid = _entry(
        target_id="derived.alpha",
        source={"type": "existing_sources"},
    )
    invalid["claimed_verifiers"] = [
        {"kind": "human", "id": "reviewer", "version": "1"},
        {"kind": "agent", "id": "codex", "version": "1"},
    ]

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_duplicate_verifier():
    invalid = _entry(
        target_id="derived.alpha",
        source={"type": "existing_sources"},
    )
    verifier = {"kind": "human", "id": "reviewer", "version": "1"}
    invalid["claimed_verifiers"] = [verifier, verifier]

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_common_check():
    invalid = _entry(
        target_id="common.alpha",
        source={
            "type": "common_claims",
            "checks": [
                {
                    "id": "reviewed-brief",
                    "outcome": "pass",
                    "authority": "human",
                    "summary": "확인",
                    "unexpected": True,
                },
            ],
        },
    )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_common_check_outcome():
    invalid = _entry(
        target_id="common.alpha",
        source={
            "type": "common_claims",
            "checks": [
                {
                    "id": "reviewed-brief",
                    "outcome": "skipped",
                    "authority": "human",
                    "summary": "확인",
                },
            ],
        },
    )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_common_check_authority():
    invalid = _entry(
        target_id="common.alpha",
        source={
            "type": "common_claims",
            "checks": [
                {
                    "id": "reviewed-brief",
                    "outcome": "pass",
                    "authority": "engine",
                    "summary": "확인",
                },
            ],
        },
    )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_common_check_order():
    invalid = _entry(
        target_id="common.alpha",
        source={
            "type": "common_claims",
            "checks": [
                {
                    "id": "z-check",
                    "outcome": "pass",
                    "authority": "human",
                    "summary": "확인",
                },
                {
                    "id": "a-check",
                    "outcome": "fixed",
                    "authority": "human",
                    "summary": "수정 확인",
                },
            ],
        },
    )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_duplicate_common_check():
    check = {
        "id": "reviewed-brief",
        "outcome": "pass",
        "authority": "human",
        "summary": "확인",
    }
    invalid = _entry(
        target_id="common.alpha",
        source={"type": "common_claims", "checks": [check, check]},
    )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_common_check_summary():
    invalid = _entry(
        target_id="common.alpha",
        source={
            "type": "common_claims",
            "checks": [
                {
                    "id": "reviewed-brief",
                    "outcome": "pass",
                    "authority": "human",
                    "summary": "",
                },
            ],
        },
    )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_when_check_has_no_matching_verifier():
    invalid = _entry(
        target_id="common.alpha",
        source={
            "type": "common_claims",
            "checks": [
                {
                    "id": "agent-check",
                    "outcome": "pass",
                    "authority": "agent",
                    "summary": "확인",
                },
            ],
        },
    )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_exact_shape_for_unknown_source_type():
    invalid = _entry(
        target_id="unknown.alpha",
        source={"type": "caller_supplied_sources"},
    )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(_canonical_file(_plan(invalid)))

    assert exc.value.code == "evidence_plan_schema_invalid"


@pytest.mark.parametrize(
    "data",
    (
        b'{"entries":[],"entries":[],"version":1}\n',
        b'{"entries":[],"version":NaN}\n',
        b'{"entries":[],"version":1} \n',
        b'{"entries":[],"version":1}',
        _canonical_file({"version": 1, "entries": []}),
        _canonical_file(_plan(_entry(
            target_id="candidate.cafe\u0301",
            source={"type": "existing_sources"},
        ))),
        _canonical_file(_plan(_entry(
            target_id="candidate.alpha ",
            source={"type": "existing_sources"},
        ))),
    ),
)
def test_rejects_noncanonical_json(data: bytes):
    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(data)

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_rejects_deeply_nested_canonical_json():
    nesting = 10_000
    data = (
        b'{"entries":'
        + b"[" * nesting
        + b"0"
        + b"]" * nesting
        + b',"version":1}\n'
    )

    with pytest.raises(EvidencePlanError) as exc:
        parse_evidence_plan(data)

    assert exc.value.code == "evidence_plan_schema_invalid"


class _RequirementSubclass(EvidencePlanRequirement):
    pass


class _StringSubclass(str):
    pass


@pytest.mark.parametrize(
    "requirements",
    (
        None,
        "not-a-requirement",
        {"target_id": "optional.alpha"},
        (("optional.alpha", "optional_unverified"),),
        (_RequirementSubclass("optional.alpha", "optional_unverified"),),
        (EvidencePlanRequirement(
            _StringSubclass("optional.alpha"),
            "optional_unverified",
        ),),
        (EvidencePlanRequirement(
            "optional.alpha",
            _StringSubclass("optional_unverified"),
        ),),
        (EvidencePlanRequirement("optional.alpha", []),),
        (EvidencePlanRequirement("optional.alpha", {}),),
    ),
)
def test_match_rejects_nonexact_requirement_inputs(requirements: object):
    plan = parse_evidence_plan(_canonical_file(_plan(_entry(
        target_id="optional.alpha",
        source={"type": "existing_sources"},
    ))))

    with pytest.raises(EvidencePlanError) as exc:
        plan.match(requirements)

    assert exc.value.code == "evidence_plan_schema_invalid"


@pytest.mark.parametrize(
    "forbidden_code",
    (
        "forbidden_by_policy",
        "evidence_plan_missing",
    ),
)
def test_match_rejects_nonclassifier_forbidden_codes(forbidden_code: str):
    plan = parse_evidence_plan(_canonical_file(_plan(_entry(
        target_id="forbidden.alpha",
        source={"type": "existing_sources"},
    ))))

    with pytest.raises(EvidencePlanError) as exc:
        plan.match((EvidencePlanRequirement(
            "forbidden.alpha",
            "forbidden",
            forbidden_code,
        ),))

    assert exc.value.code == "evidence_plan_schema_invalid"


def test_matches_mixed_target_requirements():
    plan = parse_evidence_plan(_canonical_file(_plan(
        _entry(
            target_id="optional.present",
            source={"type": "existing_sources"},
        ),
        _entry(
            target_id="required.alpha",
            source={"type": "existing_sources"},
        ),
    )))

    match = plan.match((
        EvidencePlanRequirement("required.alpha", "required"),
        EvidencePlanRequirement("optional.present", "optional_unverified"),
        EvidencePlanRequirement("optional.absent", "optional_unverified"),
        EvidencePlanRequirement(
            "forbidden.alpha",
            "forbidden",
            "evidence_plan_delete_target",
        ),
    ))

    assert isinstance(match, EvidencePlanMatch)
    assert tuple(entry.target_id for entry in match.entries) == (
        "optional.present",
        "required.alpha",
    )
    assert match.omitted_optional_target_ids == ("optional.absent",)


def test_match_sorts_requirements_and_prioritizes_forbidden_error():
    plan = parse_evidence_plan(_canonical_file(_plan(
        _entry(
            target_id="forbidden.alpha",
            source={"type": "existing_sources"},
        ),
        _entry(
            target_id="forbidden.zeta",
            source={"type": "existing_sources"},
        ),
        _entry(
            target_id="unused.alpha",
            source={"type": "existing_sources"},
        ),
    )))

    with pytest.raises(EvidencePlanError) as exc:
        plan.match((
            EvidencePlanRequirement("required.alpha", "required"),
            EvidencePlanRequirement(
                "forbidden.zeta",
                "forbidden",
                "evidence_plan_delete_target",
            ),
            EvidencePlanRequirement(
                "forbidden.alpha",
                "forbidden",
                "direct_reviewed_evidence_unavailable",
            ),
        ))

    assert exc.value.code == "direct_reviewed_evidence_unavailable"


def test_match_prioritizes_required_error_before_unused_entry():
    plan = parse_evidence_plan(_canonical_file(_plan(_entry(
        target_id="unused.alpha",
        source={"type": "existing_sources"},
    ))))

    with pytest.raises(EvidencePlanError) as exc:
        plan.match((EvidencePlanRequirement("required.alpha", "required"),))

    assert exc.value.code == "evidence_plan_missing"


@pytest.mark.parametrize(
    ("plan", "requirements", "code"),
    (
        (
            _plan(_entry(
                target_id="optional.alpha",
                source={"type": "existing_sources"},
            )),
            (
                EvidencePlanRequirement("optional.alpha", "optional_unverified"),
                EvidencePlanRequirement("required.alpha", "required"),
            ),
            "evidence_plan_missing",
        ),
        (
            _plan(_entry(
                target_id="optional.present",
                source={"type": "existing_sources"},
            )),
            (EvidencePlanRequirement("optional.absent", "optional_unverified"),),
            "evidence_plan_target_unused",
        ),
        (
            _plan(_entry(
                target_id="forbidden.alpha",
                source={"type": "existing_sources"},
            )),
            (EvidencePlanRequirement(
                "forbidden.alpha",
                "forbidden",
                "evidence_plan_delete_target",
            ),),
            "evidence_plan_delete_target",
        ),
    ),
)
def test_matches_mixed_target_requirements_rejects_exact_codes(
    plan: dict[str, object],
    requirements: tuple[EvidencePlanRequirement, ...],
    code: str,
):
    parsed = parse_evidence_plan(_canonical_file(plan))

    with pytest.raises(EvidencePlanError) as exc:
        parsed.match(requirements)

    assert exc.value.code == code


def _read_only_effect_probe(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def test_parse_failure_has_no_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "effect-probe.txt").write_bytes(b"unchanged")
    plan = parse_evidence_plan(_canonical_file(_plan(_entry(
        target_id="optional.alpha",
        source={"type": "existing_sources"},
    ))))
    failures = (
        (
            lambda: parse_evidence_plan(b'{"entries":[],"version":1}'),
            "evidence_plan_schema_invalid",
        ),
        (
            lambda: plan.match((EvidencePlanRequirement("required.alpha", "required"),)),
            "evidence_plan_missing",
        ),
        (
            lambda: plan.match((EvidencePlanRequirement("optional.absent", "optional_unverified"),)),
            "evidence_plan_target_unused",
        ),
        (
            lambda: plan.match((EvidencePlanRequirement(
                "optional.alpha",
                "forbidden",
                "evidence_plan_delete_target",
            ),)),
            "evidence_plan_delete_target",
        ),
    )

    for operation, code in failures:
        before = _read_only_effect_probe(tmp_path)
        with pytest.raises(EvidencePlanError) as exc:
            operation()
        assert exc.value.code == code
        assert _read_only_effect_probe(tmp_path) == before
