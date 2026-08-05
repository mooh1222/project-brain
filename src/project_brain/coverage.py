"""Coverage contract normalization and independent expected-object planning."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_brain.id_grammar import IdGrammarError, format_id, parse_id
from project_brain.store import BrainStore


_ASSEMBLED_FIELDS = frozenset(
    {"version", "mode", "verify_groups", "context", "sections", "expected_objects"}
)
_DIRECT_FIELDS = frozenset({"version", "mode", "objects"})
_SECTION_FIELDS = (
    "sources",
    "glossary",
    "code_anchors",
    "mappings",
    "decisions",
    "refs",
    "updates",
    "extra_objects",
)
_DECISION_EVIDENCE_TYPES = frozenset(
    {"commit", "jira", "pr", "slack", "spec", "wiki"}
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, order=True)
class ObjectIdentity:
    id: str
    kind: str


@dataclass(frozen=True)
class CoverageBinding:
    contract: dict[str, object]
    canonical_bytes: bytes
    sha256: str
    mode: str
    expected_objects: tuple[ObjectIdentity, ...]


@dataclass(frozen=True)
class BuildArtifactBinding:
    version: int
    coverage_sha256: str
    expected_objects: tuple[ObjectIdentity, ...]
    actual_objects: tuple[ObjectIdentity, ...]
    objects_sha256: str


class CoverageError(ValueError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        section: str | None = None,
        field: str | None = None,
        missing: tuple[str, ...] = (),
        unexpected: tuple[str, ...] = (),
        coverage_sha256: str | None = None,
    ) -> None:
        self.code = code
        self.section = section
        self.field = field
        self.missing = tuple(missing)
        self.unexpected = tuple(unexpected)
        self.coverage_sha256 = coverage_sha256
        self.detail = detail
        location = ".".join(part for part in (section, field) if part)
        message = f"{code}: {detail}"
        if location:
            message += f" ({location})"
        super().__init__(message)

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "detail": self.detail,
            "section": self.section,
            "field": self.field,
            "missing": list(self.missing),
            "unexpected": list(self.unexpected),
            "coverage_sha256": self.coverage_sha256,
        }


def _invalid(
    detail: str,
    *,
    section: str | None = None,
    field: str | None = None,
    missing: tuple[str, ...] = (),
    unexpected: tuple[str, ...] = (),
    coverage_sha256: str | None = None,
    code: str = "coverage_invalid",
) -> CoverageError:
    return CoverageError(
        code,
        detail,
        section=section,
        field=field,
        missing=missing,
        unexpected=unexpected,
        coverage_sha256=coverage_sha256,
    )


def _mapping(value: object, *, section: str | None, field: str | None) -> Mapping:
    if not isinstance(value, Mapping):
        raise _invalid("must be an object", section=section, field=field)
    return value


def _exact_mapping(
    value: object,
    expected: frozenset[str],
    *,
    section: str | None = None,
    field: str | None = None,
) -> Mapping:
    item = _mapping(value, section=section, field=field)
    actual = frozenset(key for key in item if isinstance(key, str))
    non_string = tuple(sorted(str(key) for key in item if not isinstance(key, str)))
    missing = tuple(sorted(expected - actual))
    unexpected = tuple(sorted(actual - expected)) + non_string
    if missing or unexpected:
        raise _invalid(
            "object fields do not match the contract",
            section=section,
            field=field,
            missing=missing,
            unexpected=unexpected,
        )
    return item


def _nonblank_string(
    value: object,
    *,
    section: str | None,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid("must be a non-empty string", section=section, field=field)
    return value


def _list(value: object, *, section: str | None, field: str) -> list:
    if not isinstance(value, list):
        raise _invalid("must be an array", section=section, field=field)
    return value


def _canonical_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise _invalid(f"must contain JSON values: {exc}") from exc
    return (text + "\n").encode("utf-8")


def _identity_text(identity: ObjectIdentity) -> str:
    return f"{identity.id}:{identity.kind}"


def _validate_identity(identity: ObjectIdentity, *, field: str) -> None:
    try:
        parse_id(identity.id, identity.kind)
    except IdGrammarError as exc:
        raise _invalid(str(exc), field=f"{field}.id") from exc


def _identity_items(
    values: object,
    *,
    field: str,
    exact_items: bool,
) -> tuple[ObjectIdentity, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        raise _invalid("must be an array", field=field)
    identities: list[ObjectIdentity] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(values):
        if exact_items:
            item = _exact_mapping(
                raw,
                frozenset({"id", "kind"}),
                field=f"{field}[{index}]",
            )
        else:
            item = _mapping(raw, section=None, field=f"{field}[{index}]")
            missing = tuple(name for name in ("id", "kind") if name not in item)
            if missing:
                raise _invalid(
                    "object identity fields are missing",
                    field=f"{field}[{index}]",
                    missing=missing,
                )
        object_id = _nonblank_string(item["id"], section=None, field=f"{field}.id")
        kind = _nonblank_string(item["kind"], section=None, field=f"{field}.kind")
        if object_id in seen_ids:
            raise _invalid("duplicate object id", field=f"{field}.id")
        seen_ids.add(object_id)
        identity = ObjectIdentity(object_id, kind)
        _validate_identity(identity, field=field)
        identities.append(identity)
    return tuple(sorted(identities))


def object_identities(
    objects: Sequence[Mapping[str, object]],
) -> tuple[ObjectIdentity, ...]:
    return _identity_items(objects, field="objects", exact_items=False)


def _unique_strings(
    values: object,
    *,
    section: str,
    field: str,
    preserve_order: bool = False,
    validate: Callable[[str], None] | None = None,
) -> list[str]:
    raw_values = _list(values, section=section, field=field)
    normalized: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        text = _nonblank_string(value, section=section, field=field)
        if text in seen:
            raise _invalid("duplicate value", section=section, field=field)
        seen.add(text)
        if validate is not None:
            try:
                validate(text)
            except IdGrammarError as exc:
                raise _invalid(str(exc), section=section, field=field) from exc
        normalized.append(text)
    if not preserve_order:
        normalized.sort()
    return normalized


def _normalize_list_section(
    raw: object,
    *,
    section_name: str,
    list_field: str,
    normalize_items: Callable[[object], list],
) -> dict[str, object]:
    item = _mapping(raw, section="sections", field=section_name)
    if list_field not in item:
        raise _invalid(
            "object fields do not match the contract",
            section="sections",
            field=section_name,
            missing=(list_field,),
        )
    values = normalize_items(item[list_field])
    if not values and "empty_reason" not in item:
        raise _invalid(
            "empty list requires empty_reason",
            section="sections",
            field=f"{section_name}.empty_reason",
            missing=("empty_reason",),
        )
    if values and "empty_reason" in item:
        raise _invalid(
            "non-empty list forbids empty_reason",
            section="sections",
            field=f"{section_name}.empty_reason",
            unexpected=("empty_reason",),
        )
    expected = frozenset({list_field}) if values else frozenset({list_field, "empty_reason"})
    item = _exact_mapping(
        item,
        expected,
        section="sections",
        field=section_name,
    )
    normalized: dict[str, object] = {list_field: values}
    if values:
        return normalized
    normalized["empty_reason"] = _nonblank_string(
        item["empty_reason"],
        section="sections",
        field=f"{section_name}.empty_reason",
    )
    return normalized


def _normalize_verify_groups(raw: object) -> dict[str, object]:
    item = _mapping(raw, section="verify_groups", field=None)
    if "names" not in item:
        raise _invalid(
            "object fields do not match the contract",
            section="verify_groups",
            missing=("names",),
        )
    names = _unique_strings(
        item["names"],
        section="verify_groups",
        field="verify_groups.names",
        preserve_order=True,
    )
    if not names and "empty_reason" not in item:
        raise _invalid(
            "empty names require empty_reason",
            section="verify_groups",
            field="verify_groups.empty_reason",
            missing=("empty_reason",),
        )
    if names and "empty_reason" in item:
        raise _invalid(
            "non-empty names forbid empty_reason",
            section="verify_groups",
            field="verify_groups.empty_reason",
            unexpected=("empty_reason",),
        )
    expected = frozenset({"names"}) if names else frozenset({"names", "empty_reason"})
    item = _exact_mapping(item, expected, section="verify_groups")
    normalized: dict[str, object] = {"names": names}
    if not names:
        normalized["empty_reason"] = _nonblank_string(
            item["empty_reason"],
            section="verify_groups",
            field="verify_groups.empty_reason",
        )
    return normalized


def _validate_derived(kind: str, ctx: str, key: str) -> None:
    field = "anchor_key" if kind in {"CodeLocator", "EvidenceRef"} else "key"
    format_id(kind, ctx=ctx, **{field: key})


def _normalize_decisions(raw: object, *, ctx: str) -> list[dict[str, object]]:
    items = _list(raw, section="sections", field="sections.decisions.items")
    normalized: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for index, raw_item in enumerate(items):
        item = _exact_mapping(
            raw_item,
            frozenset({"key", "evidence"}),
            section="sections",
            field=f"decisions.items[{index}]",
        )
        key = _nonblank_string(
            item["key"], section="sections", field="decisions.items.key"
        )
        if key in seen_keys:
            raise _invalid(
                "duplicate decision key",
                section="sections",
                field="sections.decisions.items.key",
            )
        seen_keys.add(key)
        try:
            _validate_derived("DecisionRecord", ctx, key)
        except IdGrammarError as exc:
            raise _invalid(
                str(exc), section="sections", field="decisions.items.key"
            ) from exc
        evidence_items = _list(
            item["evidence"],
            section="sections",
            field="decisions.items.evidence",
        )
        evidence: list[dict[str, str]] = []
        seen_evidence: set[tuple[str, str]] = set()
        for evidence_index, raw_evidence in enumerate(evidence_items):
            evidence_item = _exact_mapping(
                raw_evidence,
                frozenset({"type", "ref"}),
                section="sections",
                field=f"decisions.items[{index}].evidence[{evidence_index}]",
            )
            evidence_type = _nonblank_string(
                evidence_item["type"],
                section="sections",
                field="decisions.items.evidence.type",
            )
            evidence_ref = _nonblank_string(
                evidence_item["ref"],
                section="sections",
                field="decisions.items.evidence.ref",
            )
            if evidence_type not in _DECISION_EVIDENCE_TYPES:
                raise _invalid(
                    "unsupported decision evidence type",
                    section="sections",
                    field="decisions.items.evidence.type",
                )
            identity = (evidence_type, evidence_ref)
            if identity in seen_evidence:
                raise _invalid(
                    "duplicate decision evidence",
                    section="sections",
                    field="sections.decisions.items.evidence",
                )
            seen_evidence.add(identity)
            try:
                format_id(
                    "EvidenceRef",
                    ctx=ctx,
                    anchor_key=f"{evidence_type}-{evidence_ref}".lower(),
                )
            except IdGrammarError as exc:
                raise _invalid(
                    str(exc),
                    section="sections",
                    field="decisions.items.evidence",
                ) from exc
            evidence.append({"type": evidence_type, "ref": evidence_ref})
        evidence.sort(key=lambda value: (value["type"], value["ref"]))
        normalized.append({"key": key, "evidence": evidence})
    normalized.sort(key=lambda value: str(value["key"]))
    return normalized


def _normalize_refs(raw: object) -> list[dict[str, object]]:
    items = _list(raw, section="sections", field="sections.refs.items")
    normalized: list[dict[str, object]] = []
    aliases: set[str] = set()
    for index, raw_item in enumerate(items):
        item = _exact_mapping(
            raw_item,
            frozenset({"category", "alias", "id", "expect"}),
            section="sections",
            field=f"refs.items[{index}]",
        )
        category = _nonblank_string(
            item["category"], section="sections", field="refs.items.category"
        )
        alias = _nonblank_string(
            item["alias"], section="sections", field="refs.items.alias"
        )
        object_id = _nonblank_string(
            item["id"], section="sections", field="refs.items.id"
        )
        if alias in aliases:
            raise _invalid(
                "duplicate ref alias",
                section="sections",
                field="sections.refs.items.alias",
            )
        aliases.add(alias)
        try:
            parse_id(object_id)
        except IdGrammarError as exc:
            raise _invalid(str(exc), section="sections", field="refs.items.id") from exc
        expect = dict(
            _mapping(item["expect"], section="sections", field="refs.items.expect")
        )
        _canonical_json_bytes(expect)
        normalized.append(
            {
                "category": category,
                "alias": alias,
                "id": object_id,
                "expect": expect,
            }
        )
    normalized.sort(
        key=lambda value: (
            str(value["category"]),
            str(value["alias"]),
            str(value["id"]),
            _canonical_json_bytes(value["expect"]),
        )
    )
    return normalized


def _normalize_sections(raw: object, *, ctx: str) -> dict[str, object]:
    sections = _exact_mapping(raw, frozenset(_SECTION_FIELDS), section="sections")

    def strings(
        value: object,
        section_name: str,
        field: str,
        validator: Callable[[str], None],
    ) -> list[str]:
        return _unique_strings(
            value,
            section="sections",
            field=f"sections.{section_name}.{field}",
            validate=validator,
        )

    normalized: dict[str, object] = {}
    normalized["sources"] = _normalize_list_section(
        sections["sources"],
        section_name="sources",
        list_field="ids",
        normalize_items=lambda value: strings(
            value,
            "sources",
            "ids",
            lambda object_id: parse_id(object_id, "EvidenceManifest"),
        ),
    )
    normalized["glossary"] = _normalize_list_section(
        sections["glossary"],
        section_name="glossary",
        list_field="keys",
        normalize_items=lambda value: strings(
            value,
            "glossary",
            "keys",
            lambda key: _validate_derived("GlossaryTerm", ctx, key),
        ),
    )
    normalized["code_anchors"] = _normalize_list_section(
        sections["code_anchors"],
        section_name="code_anchors",
        list_field="keys",
        normalize_items=lambda value: strings(
            value,
            "code_anchors",
            "keys",
            lambda key: _validate_derived("CodeLocator", ctx, key),
        ),
    )
    normalized["mappings"] = _normalize_list_section(
        sections["mappings"],
        section_name="mappings",
        list_field="keys",
        normalize_items=lambda value: strings(
            value,
            "mappings",
            "keys",
            lambda key: _validate_derived("DomainMapping", ctx, key),
        ),
    )
    normalized["decisions"] = _normalize_list_section(
        sections["decisions"],
        section_name="decisions",
        list_field="items",
        normalize_items=lambda value: _normalize_decisions(value, ctx=ctx),
    )
    normalized["refs"] = _normalize_list_section(
        sections["refs"],
        section_name="refs",
        list_field="items",
        normalize_items=_normalize_refs,
    )
    normalized["updates"] = _normalize_list_section(
        sections["updates"],
        section_name="updates",
        list_field="ids",
        normalize_items=lambda value: strings(
            value,
            "updates",
            "ids",
            parse_id,
        ),
    )
    normalized["extra_objects"] = _normalize_list_section(
        sections["extra_objects"],
        section_name="extra_objects",
        list_field="objects",
        normalize_items=lambda value: [
            {"id": identity.id, "kind": identity.kind}
            for identity in _identity_items(
                value,
                field="sections.extra_objects.objects",
                exact_items=True,
            )
        ],
    )
    return normalized


def _normalize_context(raw: object) -> dict[str, str]:
    context = _exact_mapping(
        raw,
        frozenset({"key", "mode"}),
        section="context",
    )
    key = _nonblank_string(context["key"], section="context", field="key")
    mode = _nonblank_string(context["mode"], section="context", field="mode")
    if mode not in {"create", "reuse"}:
        raise _invalid("mode must be create or reuse", section="context", field="mode")
    try:
        format_id("DomainContext", ctx=key)
    except IdGrammarError as exc:
        raise _invalid(str(exc), section="context", field="key") from exc
    return {"key": key, "mode": mode}


def normalize_coverage(value: Mapping[str, object]) -> CoverageBinding:
    raw = _mapping(value, section=None, field=None)
    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise _invalid("version must be integer 1", field="version")
    mode = raw.get("mode")
    if mode not in {"direct", "assembled"}:
        raise _invalid("mode must be direct or assembled", field="mode")

    if mode == "direct":
        raw = _exact_mapping(raw, _DIRECT_FIELDS)
        expected_objects = _identity_items(
            raw["objects"], field="objects", exact_items=True
        )
        if not expected_objects:
            raise _invalid("LIVE object list must not be empty", field="objects")
        contract: dict[str, object] = {
            "version": 1,
            "mode": "direct",
            "objects": [
                {"id": identity.id, "kind": identity.kind}
                for identity in expected_objects
            ],
        }
    else:
        raw = _exact_mapping(raw, _ASSEMBLED_FIELDS)
        context = _normalize_context(raw["context"])
        expected_objects = _identity_items(
            raw["expected_objects"],
            field="expected_objects",
            exact_items=True,
        )
        if not expected_objects:
            raise _invalid(
                "LIVE object list must not be empty", field="expected_objects"
            )
        contract = {
            "version": 1,
            "mode": "assembled",
            "verify_groups": _normalize_verify_groups(raw["verify_groups"]),
            "context": context,
            "sections": _normalize_sections(raw["sections"], ctx=context["key"]),
            "expected_objects": [
                {"id": identity.id, "kind": identity.kind}
                for identity in expected_objects
            ],
        }

    canonical_bytes = _canonical_json_bytes(contract)
    return CoverageBinding(
        contract=contract,
        canonical_bytes=canonical_bytes,
        sha256=hashlib.sha256(canonical_bytes).hexdigest(),
        mode=mode,
        expected_objects=expected_objects,
    )


def read_coverage(path: Path) -> CoverageBinding:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _invalid(f"could not read coverage JSON: {exc}") from exc
    if not isinstance(raw, Mapping):
        raise _invalid("coverage JSON must contain an object")
    return normalize_coverage(raw)


def _planned_identity(
    kind: str,
    *,
    ctx: str,
    key: str | None = None,
) -> ObjectIdentity:
    if kind == "DomainContext":
        object_id = format_id(kind, ctx=ctx)
    else:
        key_field = "anchor_key" if kind in {"CodeLocator", "EvidenceRef"} else "key"
        object_id = format_id(kind, ctx=ctx, **{key_field: key})
    return ObjectIdentity(object_id, kind)


def _compare_expected(
    planned: tuple[ObjectIdentity, ...], binding: CoverageBinding
) -> None:
    if planned == binding.expected_objects:
        return
    planned_set = set(planned)
    authored_set = set(binding.expected_objects)
    raise _invalid(
        "independent planner does not match authored expected_objects",
        field="expected_objects",
        missing=tuple(_identity_text(item) for item in sorted(planned_set - authored_set)),
        unexpected=tuple(
            _identity_text(item) for item in sorted(authored_set - planned_set)
        ),
        coverage_sha256=binding.sha256,
        code="coverage_build_mismatch",
    )


def plan_expected_objects(
    binding: CoverageBinding,
    store: BrainStore,
) -> tuple[ObjectIdentity, ...]:
    if binding.mode == "direct":
        return binding.expected_objects

    contract = binding.contract
    context = contract["context"]
    sections = contract["sections"]
    assert isinstance(context, dict)
    assert isinstance(sections, dict)
    ctx = str(context["key"])
    context_id = format_id("DomainContext", ctx=ctx)
    planned: list[ObjectIdentity] = []

    if context["mode"] == "create":
        if store.has(context_id):
            raise _invalid(
                f"context {context_id} already exists",
                section="context",
                field="mode",
                coverage_sha256=binding.sha256,
                code="coverage_binding_mismatch",
            )
        planned.append(ObjectIdentity(context_id, "DomainContext"))
    else:
        if not store.has(context_id) or store.get(context_id).get("kind") != "DomainContext":
            raise _invalid(
                f"context.reuse requires existing DomainContext {context_id}",
                section="context",
                field="mode",
                coverage_sha256=binding.sha256,
                code="coverage_binding_mismatch",
            )

    for source_id in sections["sources"]["ids"]:
        planned.append(ObjectIdentity(source_id, "EvidenceManifest"))
    for key in sections["glossary"]["keys"]:
        planned.append(_planned_identity("GlossaryTerm", ctx=ctx, key=key))
    for key in sections["code_anchors"]["keys"]:
        planned.append(_planned_identity("CodeLocator", ctx=ctx, key=key))
        planned.append(_planned_identity("EvidenceRef", ctx=ctx, key=key))
    for key in sections["mappings"]["keys"]:
        planned.append(_planned_identity("DomainMapping", ctx=ctx, key=key))

    evidence: set[tuple[str, str]] = set()
    for decision in sections["decisions"]["items"]:
        planned.append(
            _planned_identity("DecisionRecord", ctx=ctx, key=decision["key"])
        )
        for item in decision["evidence"]:
            evidence.add((item["type"], item["ref"]))
    for evidence_type, evidence_ref in sorted(evidence):
        planned.append(
            _planned_identity(
                "EvidenceRef",
                ctx=ctx,
                key=f"{evidence_type}-{evidence_ref}".lower(),
            )
        )

    for object_id in sections["updates"]["ids"]:
        if not store.has(object_id):
            raise _invalid(
                f"update object {object_id} is not in the store",
                section="updates",
                field="ids",
                coverage_sha256=binding.sha256,
                code="coverage_binding_mismatch",
            )
        kind = store.get(object_id).get("kind")
        if not isinstance(kind, str) or not kind:
            raise _invalid(
                f"update object {object_id} has no kind",
                section="updates",
                field="ids",
                coverage_sha256=binding.sha256,
                code="coverage_binding_mismatch",
            )
        identity = ObjectIdentity(object_id, kind)
        _validate_identity(identity, field="sections.updates.ids")
        planned.append(identity)

    for item in sections["extra_objects"]["objects"]:
        planned.append(ObjectIdentity(item["id"], item["kind"]))

    planned.sort()
    seen_ids: set[str] = set()
    for identity in planned:
        if identity.id in seen_ids:
            raise _invalid(
                "planner produced duplicate object id",
                field="expected_objects.id",
                coverage_sha256=binding.sha256,
                code="coverage_build_mismatch",
            )
        seen_ids.add(identity.id)
    result = tuple(planned)
    _compare_expected(result, binding)
    return result


def _canonical_object_bundle(
    objects: Sequence[Mapping[str, object]],
) -> tuple[tuple[ObjectIdentity, ...], bytes]:
    identities = object_identities(objects)
    by_id: dict[str, Mapping[str, object]] = {}
    for obj in objects:
        by_id[str(obj["id"])] = obj
    ordered = [dict(by_id[identity.id]) for identity in identities]
    return identities, _canonical_json_bytes(ordered)


def _identity_diff(
    expected: tuple[ObjectIdentity, ...], actual: tuple[ObjectIdentity, ...]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    expected_set = set(expected)
    actual_set = set(actual)
    return (
        tuple(_identity_text(item) for item in sorted(expected_set - actual_set)),
        tuple(_identity_text(item) for item in sorted(actual_set - expected_set)),
    )


def build_artifact_binding(
    binding: CoverageBinding,
    objects: Sequence[Mapping[str, object]],
) -> BuildArtifactBinding:
    actual_objects, canonical_bytes = _canonical_object_bundle(objects)
    if actual_objects != binding.expected_objects:
        missing, unexpected = _identity_diff(binding.expected_objects, actual_objects)
        raise _invalid(
            "build objects do not match coverage expected_objects",
            field="actual_objects",
            missing=missing,
            unexpected=unexpected,
            coverage_sha256=binding.sha256,
            code="coverage_build_mismatch",
        )
    return BuildArtifactBinding(
        version=1,
        coverage_sha256=binding.sha256,
        expected_objects=binding.expected_objects,
        actual_objects=actual_objects,
        objects_sha256=hashlib.sha256(canonical_bytes).hexdigest(),
    )


def _sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise _invalid("must be a lowercase SHA-256 digest", field=field)
    return value


def normalize_build_artifact_binding(
    value: Mapping[str, object],
) -> BuildArtifactBinding:
    raw = _exact_mapping(
        value,
        frozenset(
            {
                "version",
                "coverage_sha256",
                "expected_objects",
                "actual_objects",
                "objects_sha256",
            }
        ),
    )
    version = raw["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise _invalid("version must be integer 1", field="version")
    expected = _identity_items(
        raw["expected_objects"], field="expected_objects", exact_items=True
    )
    actual = _identity_items(
        raw["actual_objects"], field="actual_objects", exact_items=True
    )
    if not expected:
        raise _invalid("LIVE object list must not be empty", field="expected_objects")
    if actual != expected:
        missing, unexpected = _identity_diff(expected, actual)
        raise _invalid(
            "actual_objects do not match expected_objects",
            field="actual_objects",
            missing=missing,
            unexpected=unexpected,
            code="coverage_binding_mismatch",
        )
    return BuildArtifactBinding(
        version=1,
        coverage_sha256=_sha256(raw["coverage_sha256"], field="coverage_sha256"),
        expected_objects=expected,
        actual_objects=actual,
        objects_sha256=_sha256(raw["objects_sha256"], field="objects_sha256"),
    )
