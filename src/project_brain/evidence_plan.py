"""Immutable parsing boundary for canonical evidence plans."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass


_ENTRY_KEYS = {
    "target_id",
    "source",
    "claimed_producer",
    "claimed_verifiers",
}
_ACTOR_KEYS = {"kind", "id", "version"}
_CHECK_KEYS = {"id", "outcome", "authority", "summary"}
_FORBIDDEN_CODES = (
    "evidence_plan_delete_target",
    "direct_reviewed_evidence_unavailable",
    "evidence_profile_unavailable",
    "evidence_adapter_unavailable",
)


class EvidencePlanError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class EvidencePlanActor:
    kind: str
    id: str
    version: str


@dataclass(frozen=True)
class EvidencePlanCheck:
    id: str
    outcome: str
    authority: str
    summary: str


@dataclass(frozen=True)
class CommonClaimsSource:
    checks: tuple[EvidencePlanCheck, ...]


@dataclass(frozen=True)
class RawSourceObservation:
    path: str


@dataclass(frozen=True)
class ExistingSources:
    pass


@dataclass(frozen=True)
class EvidencePlanEntry:
    target_id: str
    source: CommonClaimsSource | RawSourceObservation | ExistingSources
    claimed_producer: EvidencePlanActor
    claimed_verifiers: tuple[EvidencePlanActor, ...]


@dataclass(frozen=True)
class EvidencePlanRequirement:
    target_id: str
    requirement: str
    forbidden_code: str | None = None


@dataclass(frozen=True)
class EvidencePlanMatch:
    entries: tuple[EvidencePlanEntry, ...]
    omitted_optional_target_ids: tuple[str, ...]


@dataclass(frozen=True)
class EvidencePlanV1:
    entries: tuple[EvidencePlanEntry, ...]
    _canonical_payload: bytes

    def canonical_bytes(self) -> bytes:
        return self._canonical_payload

    def match(self, requirements: Iterable[EvidencePlanRequirement]) -> EvidencePlanMatch:
        try:
            parsed_requirements = tuple(requirements)
        except TypeError as exc:
            _fail(str(exc))
        target_ids: set[str] = set()
        for requirement in parsed_requirements:
            if (
                type(requirement) is not EvidencePlanRequirement
                or not _exact_nonempty_string(requirement.target_id)
                or type(requirement.requirement) is not str
                or requirement.requirement not in (
                    "optional_unverified",
                    "required",
                    "forbidden",
                )
            ):
                _fail("evidence plan requirement is invalid")
            if requirement.target_id in target_ids:
                _fail("evidence plan requirement target is duplicated")
            target_ids.add(requirement.target_id)
            if requirement.requirement == "forbidden":
                if (
                    not _exact_nonempty_string(requirement.forbidden_code)
                    or requirement.forbidden_code not in _FORBIDDEN_CODES
                ):
                    _fail("forbidden requirement code is invalid")
            elif requirement.forbidden_code is not None:
                _fail("only forbidden requirements may provide a code")

        parsed_requirements = tuple(sorted(
            parsed_requirements,
            key=lambda requirement: requirement.target_id,
        ))
        entries_by_target = {entry.target_id: entry for entry in self.entries}
        for requirement in parsed_requirements:
            if (
                requirement.requirement == "forbidden"
                and requirement.target_id in entries_by_target
            ):
                assert requirement.forbidden_code is not None
                raise EvidencePlanError(
                    requirement.forbidden_code,
                    f"entry is forbidden for {requirement.target_id}",
                )

        for requirement in parsed_requirements:
            if (
                requirement.requirement == "required"
                and requirement.target_id not in entries_by_target
            ):
                raise EvidencePlanError(
                    "evidence_plan_missing",
                    f"missing entry for {requirement.target_id}",
                )

        matched_target_ids: set[str] = set()
        omitted_optional_target_ids: list[str] = []
        for requirement in parsed_requirements:
            entry = entries_by_target.get(requirement.target_id)
            if requirement.requirement == "optional_unverified":
                if entry is None:
                    omitted_optional_target_ids.append(requirement.target_id)
                else:
                    matched_target_ids.add(requirement.target_id)
            elif requirement.requirement == "required":
                assert entry is not None
                matched_target_ids.add(requirement.target_id)

        unused = [
            entry.target_id
            for entry in self.entries
            if entry.target_id not in matched_target_ids
        ]
        if unused:
            raise EvidencePlanError(
                "evidence_plan_target_unused",
                f"unused entries: {', '.join(unused)}",
            )
        return EvidencePlanMatch(
            entries=tuple(
                entry
                for entry in self.entries
                if entry.target_id in matched_target_ids
            ),
            omitted_optional_target_ids=tuple(sorted(omitted_optional_target_ids)),
        )


class _DuplicateJsonKey(ValueError):
    pass


def _fail(detail: str) -> None:
    raise EvidencePlanError("evidence_plan_schema_invalid", detail)


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def _exact_nonempty_string(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and value == unicodedata.normalize("NFC", value)
    )


def _valid_raw_source_path(value: object) -> bool:
    if not _exact_nonempty_string(value) or "\\" in value or "\0" in value:
        return False
    assert isinstance(value, str)
    parts = value.split("/")
    return (
        len(parts) >= 3
        and parts[:2] == ["raw", "sources"]
        and all(part not in {"", ".", ".."} for part in parts)
    )


def _validate_entry_shapes(entries: list[object]) -> None:
    if not entries:
        _fail("plan entries must not be empty")
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
            _fail("entry shape is invalid")


def _validate_target_order(entries: list[object]) -> None:
    target_ids: list[str] = []
    for entry in entries:
        assert isinstance(entry, dict)
        target_id = entry["target_id"]
        if not _exact_nonempty_string(target_id):
            _fail("target ID is invalid")
        assert isinstance(target_id, str)
        target_ids.append(target_id)
    if target_ids != sorted(target_ids) or len(target_ids) != len(set(target_ids)):
        _fail("target IDs must be sorted and unique")


def _valid_claimed_actor(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == _ACTOR_KEYS
        and type(value["kind"]) is str
        and value["kind"] in ("human", "agent")
        and _exact_nonempty_string(value["id"])
        and _exact_nonempty_string(value["version"])
    )


def _validate_claimed_producers(entries: list[object]) -> None:
    for entry in entries:
        assert isinstance(entry, dict)
        if not _valid_claimed_actor(entry["claimed_producer"]):
            _fail("claimed producer is invalid")


def _validate_claimed_verifiers(entries: list[object]) -> None:
    for entry in entries:
        assert isinstance(entry, dict)
        verifiers = entry["claimed_verifiers"]
        if not isinstance(verifiers, list) or not all(
            _valid_claimed_actor(verifier) for verifier in verifiers
        ):
            _fail("claimed verifiers are invalid")
        identities = [
            (verifier["kind"], verifier["id"], verifier["version"])
            for verifier in verifiers
        ]
        if identities != sorted(identities) or len(identities) != len(set(identities)):
            _fail("claimed verifiers must be sorted and unique")


def _validate_sources(entries: list[object]) -> None:
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source")
        if not isinstance(source, dict):
            _fail("source shape is invalid")
        source_type = source.get("type")
        if type(source_type) is not str:
            _fail("source type is invalid")
        if source_type == "common_claims":
            if set(source) != {"type", "checks"} or not isinstance(source["checks"], list):
                _fail("common claims shape is invalid")
            if not all(
                isinstance(check, dict) and set(check) == _CHECK_KEYS
                for check in source["checks"]
            ):
                _fail("common check shape is invalid")
            if any(
                type(check["outcome"]) is not str
                or check["outcome"] not in ("pass", "fixed")
                for check in source["checks"]
            ):
                _fail("common check outcome is invalid")
            if any(
                type(check["authority"]) is not str
                or check["authority"] not in ("human", "agent")
                for check in source["checks"]
            ):
                _fail("common check authority is invalid")
            check_ids = [check["id"] for check in source["checks"]]
            if (
                not all(_exact_nonempty_string(check_id) for check_id in check_ids)
                or check_ids != sorted(check_ids)
                or len(check_ids) != len(set(check_ids))
            ):
                _fail("common check IDs must be sorted and unique")
            if not all(
                _exact_nonempty_string(check["summary"])
                for check in source["checks"]
            ):
                _fail("common check summary is invalid")
            verifier_kinds = {
                verifier["kind"] for verifier in entry["claimed_verifiers"]
            }
            if any(
                check["authority"] not in verifier_kinds
                for check in source["checks"]
            ):
                _fail("common check has no matching verifier")
        elif source_type == "raw_source_observation":
            if (
                set(source) != {"type", "path"}
                or not _valid_raw_source_path(source["path"])
            ):
                _fail("raw source path is invalid")
        elif source_type == "existing_sources":
            if set(source) != {"type"}:
                _fail("existing sources shape is invalid")
        else:
            _fail("source type is invalid")


def _decode_actor(value: object) -> EvidencePlanActor:
    assert isinstance(value, dict)
    return EvidencePlanActor(
        kind=value["kind"],
        id=value["id"],
        version=value["version"],
    )


def _decode_entry(value: object) -> EvidencePlanEntry:
    assert isinstance(value, dict)
    source_value = value["source"]
    assert isinstance(source_value, dict)
    source_type = source_value["type"]
    if source_type == "common_claims":
        checks = tuple(
            EvidencePlanCheck(
                id=check["id"],
                outcome=check["outcome"],
                authority=check["authority"],
                summary=check["summary"],
            )
            for check in source_value["checks"]
        )
        source = CommonClaimsSource(checks)
    elif source_type == "raw_source_observation":
        source = RawSourceObservation(source_value["path"])
    else:
        source = ExistingSources()
    return EvidencePlanEntry(
        target_id=value["target_id"],
        source=source,
        claimed_producer=_decode_actor(value["claimed_producer"]),
        claimed_verifiers=tuple(
            _decode_actor(verifier)
            for verifier in value["claimed_verifiers"]
        ),
    )


def parse_evidence_plan(data: bytes) -> EvidencePlanV1:
    if not isinstance(data, bytes) or not data.endswith(b"\n"):
        _fail("plan file must end with one newline")
    payload = data[:-1]
    try:
        value = json.loads(
            payload,
            object_pairs_hook=_json_object,
            parse_constant=_reject_nonfinite,
        )
        canonical_payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (UnicodeError, json.JSONDecodeError, _DuplicateJsonKey, TypeError, ValueError, RecursionError) as exc:
        _fail(str(exc))
    if payload != canonical_payload:
        _fail("plan file is not canonical JSON")
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "entries"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["entries"], list)
    ):
        _fail("plan shape is invalid")
    _validate_entry_shapes(value["entries"])
    _validate_target_order(value["entries"])
    _validate_claimed_producers(value["entries"])
    _validate_claimed_verifiers(value["entries"])
    _validate_sources(value["entries"])
    return EvidencePlanV1(
        entries=tuple(_decode_entry(entry) for entry in value["entries"]),
        _canonical_payload=canonical_payload,
    )
