"""Brain 객체 ID의 parser/formatter/객체 필드 교차 검증 정본."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping


_SLUG_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_ANCHOR_KEY_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*(?:--[0-9]+)?")
_DECIMAL_RE = re.compile(r"0|[1-9][0-9]*")
_DIGEST_RE = re.compile(r"[0-9a-f]{16}")
_ENUM_RE = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")


class IdGrammarError(ValueError):
    """객체 ID가 정식 문법이나 연결 필드 불변조건을 어겼다."""


@dataclass(frozen=True)
class ParsedId:
    kind: str
    object_id: str
    variant: str
    fields: Mapping[str, str | int]

    def __getattr__(self, name: str) -> str | int:
        try:
            return self.fields[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


Parser = Callable[[str], ParsedId]
Formatter = Callable[[Mapping[str, str | int]], str]


@dataclass(frozen=True)
class IdGrammar:
    kind: str
    prefixes: tuple[str, ...]
    parser: Parser
    formatter: Formatter


def _parsed(
    kind: str,
    object_id: str,
    variant: str = "default",
    **fields: str | int,
) -> ParsedId:
    return ParsedId(kind, object_id, variant, MappingProxyType(dict(fields)))


def _require_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise IdGrammarError(f"{field} must be a string")
    return value


def _require_slug(value: object, field: str) -> str:
    text = _require_string(value, field)
    if not _SLUG_RE.fullmatch(text):
        raise IdGrammarError(f"{field} must match slug grammar")
    return text


def _require_anchor_key(value: object, field: str) -> str:
    text = _require_string(value, field)
    if not _ANCHOR_KEY_RE.fullmatch(text):
        raise IdGrammarError(f"{field} must match anchor-key grammar")
    return text


def _require_decimal(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise IdGrammarError(f"{field} must be a decimal")
    text = str(value)
    if not _DECIMAL_RE.fullmatch(text):
        raise IdGrammarError(f"{field} must be a decimal without leading zeroes")
    return int(text)


def _require_digest(value: object, field: str = "source_id_digest") -> str:
    text = _require_string(value, field)
    if not _DIGEST_RE.fullmatch(text):
        raise IdGrammarError(f"{field} must be 16 lowercase hexadecimal characters")
    return text


def _enum_to_piece(value: object, field: str) -> str:
    text = _require_string(value, field)
    if not _ENUM_RE.fullmatch(text):
        raise IdGrammarError(f"{field} must be a lowercase underscore enum")
    return text.replace("_", "-")


def _piece_to_enum(value: object, field: str) -> str:
    return _require_slug(value, field).replace("-", "_")


def _expect_fields(
    fields: Mapping[str, str | int],
    expected: frozenset[str],
) -> None:
    actual = frozenset(fields)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing fields {missing!r}")
        if extra:
            details.append(f"unexpected fields {extra!r}")
        raise IdGrammarError(", ".join(details))


def _split_exact(object_id: str, prefix: str, count: int) -> list[str]:
    parts = object_id.split(".")
    if len(parts) != count or parts[0] != prefix or any(part == "" for part in parts):
        raise IdGrammarError(
            f"expected {prefix!r} prefix and exactly {count - 1} non-empty ID fields"
        )
    return parts


def _simple_grammar(
    kind: str,
    prefix: str,
    field_specs: tuple[tuple[str, str], ...],
) -> IdGrammar:
    def parser(object_id: str) -> ParsedId:
        parts = _split_exact(object_id, prefix, len(field_specs) + 1)
        parsed_fields: dict[str, str | int] = {}
        for part, (field, atom) in zip(parts[1:], field_specs):
            if atom == "slug":
                parsed_fields[field] = _require_slug(part, field)
            elif atom == "anchor":
                parsed_fields[field] = _require_anchor_key(part, field)
            elif atom == "decimal":
                parsed_fields[field] = _require_decimal(part, field)
            elif atom == "enum":
                parsed_fields[field] = _piece_to_enum(part, field)
            elif atom == "digest":
                parsed_fields[field] = _require_digest(part, field)
            else:  # pragma: no cover - registry construction is static
                raise AssertionError(f"unknown atom {atom!r}")
        return _parsed(kind, object_id, **parsed_fields)

    def formatter(fields: Mapping[str, str | int]) -> str:
        expected = frozenset(field for field, _atom in field_specs)
        _expect_fields(fields, expected)
        parts = [prefix]
        for field, atom in field_specs:
            value = fields[field]
            if atom == "slug":
                parts.append(_require_slug(value, field))
            elif atom == "anchor":
                parts.append(_require_anchor_key(value, field))
            elif atom == "decimal":
                parts.append(str(_require_decimal(value, field)))
            elif atom == "enum":
                parts.append(_enum_to_piece(value, field))
            elif atom == "digest":
                parts.append(_require_digest(value, field))
        return ".".join(parts)

    return IdGrammar(kind, (prefix,), parser, formatter)


def _parse_bundle_key(bundle_key: object) -> tuple[str, str]:
    text = _require_string(bundle_key, "bundle_key")
    parts = _split_exact(text, "bundle", 3)
    return _require_slug(parts[1], "ctx"), _require_slug(parts[2], "key")


def _parse_bundle_review_record(object_id: str) -> ParsedId:
    parts = _split_exact(object_id, "review", 4)
    if parts[1] != "bundle":
        raise IdGrammarError("bundle ReviewRecord must use review.bundle prefix")
    ctx = _require_slug(parts[2], "ctx")
    key = _require_slug(parts[3], "key")
    return _parsed(
        "ReviewRecord",
        object_id,
        "bundle",
        ctx=ctx,
        key=key,
        bundle_key=f"bundle.{ctx}.{key}",
    )


def _require_review_target_id(value: object) -> str:
    target_object_id = _require_string(value, "target_object_id")
    if not target_object_id:
        raise IdGrammarError("single ReviewRecord target_object_id is empty")
    leaf_object_id = target_object_id
    while leaf_object_id.startswith("review.") and not leaf_object_id.startswith(
        "review.bundle."
    ):
        leaf_object_id = leaf_object_id.removeprefix("review.")
        if not leaf_object_id:
            raise IdGrammarError("single ReviewRecord target_object_id is empty")
    if leaf_object_id.startswith("review.bundle."):
        _parse_bundle_review_record(leaf_object_id)
    else:
        parse_id(leaf_object_id)
    return target_object_id


def _parse_review_record(object_id: str) -> ParsedId:
    if object_id.startswith("review.bundle."):
        return _parse_bundle_review_record(object_id)
    if not object_id.startswith("review."):
        raise IdGrammarError("expected 'review' prefix")
    target_object_id = object_id.removeprefix("review.")
    _require_review_target_id(target_object_id)
    return _parsed(
        "ReviewRecord",
        object_id,
        "single",
        target_object_id=target_object_id,
    )


def _format_review_record(fields: Mapping[str, str | int]) -> str:
    keys = frozenset(fields)
    if keys == {"target_object_id"}:
        target_object_id = _require_review_target_id(fields["target_object_id"])
        return f"review.{target_object_id}"
    if keys == {"bundle_key"}:
        ctx, key = _parse_bundle_key(fields["bundle_key"])
        return f"review.bundle.{ctx}.{key}"
    if keys == {"ctx", "key"}:
        ctx = _require_slug(fields["ctx"], "ctx")
        key = _require_slug(fields["key"], "key")
        return f"review.bundle.{ctx}.{key}"
    if keys == {"ctx", "key", "bundle_key"}:
        ctx = _require_slug(fields["ctx"], "ctx")
        key = _require_slug(fields["key"], "key")
        bundle_ctx, bundle_key = _parse_bundle_key(fields["bundle_key"])
        if (ctx, key) != (bundle_ctx, bundle_key):
            raise IdGrammarError("bundle_key does not match ctx/key")
        return f"review.bundle.{ctx}.{key}"
    raise IdGrammarError("ReviewRecord requires target_object_id or bundle fields")


def _parse_context_projection(object_id: str) -> ParsedId:
    parts = object_id.split(".")
    if len(parts) == 3 and parts[0] == "projection" and parts[2] == "context-md":
        ctx = _require_slug(parts[1], "ctx")
        return _parsed(
            "ContextProjection",
            object_id,
            "context_md",
            ctx=ctx,
            format="context_md",
        )
    if len(parts) == 4 and parts[0] == "projection" and parts[3] == "reuse":
        ctx = _require_slug(parts[1], "ctx")
        requirement_key = _require_slug(parts[2], "requirement_key")
        return _parsed(
            "ContextProjection",
            object_id,
            "reuse",
            ctx=ctx,
            requirement_key=requirement_key,
            format="prompt_payload",
        )
    raise IdGrammarError(
        "ContextProjection must be projection.<ctx>.context-md or "
        "projection.<ctx>.<requirement-key>.reuse"
    )


def _format_context_projection(fields: Mapping[str, str | int]) -> str:
    keys = frozenset(fields)
    if keys == {"ctx", "format"} and fields["format"] == "context_md":
        return f"projection.{_require_slug(fields['ctx'], 'ctx')}.context-md"
    if (
        keys == {"ctx", "requirement_key", "format"}
        and fields["format"] == "prompt_payload"
    ):
        ctx = _require_slug(fields["ctx"], "ctx")
        requirement_key = _require_slug(fields["requirement_key"], "requirement_key")
        return f"projection.{ctx}.{requirement_key}.reuse"
    raise IdGrammarError("ContextProjection fields do not match a canonical format variant")


_GRAMMARS = {
    grammar.kind: grammar
    for grammar in (
        _simple_grammar(
            "EvidenceManifest", "manifest", (("ctx", "slug"), ("key", "slug"))
        ),
        _simple_grammar(
            "EvidenceRef", "evref", (("ctx", "slug"), ("anchor_key", "anchor"))
        ),
        IdGrammar(
            "ReviewRecord",
            ("review",),
            _parse_review_record,
            _format_review_record,
        ),
        _simple_grammar(
            "EventLedgerRecord", "ledger", (("ctx", "slug"), ("key", "slug"))
        ),
        _simple_grammar("TemporalFact", "fact", (("ctx", "slug"), ("key", "slug"))),
        _simple_grammar(
            "CodeLocator", "code", (("ctx", "slug"), ("anchor_key", "anchor"))
        ),
        _simple_grammar("DomainContext", "context", (("ctx", "slug"),)),
        _simple_grammar("GlossaryTerm", "g", (("ctx", "slug"), ("key", "slug"))),
        IdGrammar(
            "ContextProjection",
            ("projection",),
            _parse_context_projection,
            _format_context_projection,
        ),
        _simple_grammar(
            "CurrentView", "view", (("view_type", "enum"), ("key", "slug"))
        ),
        _simple_grammar(
            "KnowledgePage", "page", (("category", "slug"), ("key", "slug"))
        ),
        _simple_grammar(
            "IndexRecord",
            "index",
            (("index_name", "enum"), ("source_id_digest", "digest")),
        ),
        _simple_grammar("SpecDocument", "spec", (("document_key", "slug"),)),
        _simple_grammar(
            "SpecRevision",
            "revision",
            (("document_key", "slug"), ("revision_key", "slug")),
        ),
        _simple_grammar(
            "SlideRef",
            "slide",
            (
                ("document_key", "slug"),
                ("revision_key", "slug"),
                ("slide_no", "decimal"),
            ),
        ),
        _simple_grammar("SlackThread", "slack", (("ctx", "slug"), ("key", "slug"))),
        _simple_grammar(
            "DecisionRecord", "decision", (("ctx", "slug"), ("key", "slug"))
        ),
        _simple_grammar(
            "DomainMapping", "mapping", (("ctx", "slug"), ("key", "slug"))
        ),
        _simple_grammar("Insight", "insight", (("ctx", "slug"), ("key", "slug"))),
    )
}

ID_GRAMMARS: Mapping[str, IdGrammar] = MappingProxyType(_GRAMMARS)

_KIND_BY_PREFIX = {
    prefix: kind
    for kind, grammar in ID_GRAMMARS.items()
    for prefix in grammar.prefixes
}


def parse_id(object_id: str, kind: str | None = None) -> ParsedId:
    """정식 객체 ID를 해석한다. kind 생략 시 첫 prefix로만 kind를 고른다."""
    if not isinstance(object_id, str) or not object_id:
        raise IdGrammarError("object_id must be a non-empty string")
    if kind is None:
        prefix = object_id.split(".", 1)[0]
        kind = _KIND_BY_PREFIX.get(prefix)
        if kind is None:
            raise IdGrammarError(f"unknown ID prefix {prefix!r}")
    grammar = ID_GRAMMARS.get(kind)
    if grammar is None:
        raise IdGrammarError(f"unknown kind {kind!r}")
    return grammar.parser(object_id)


def format_id(kind: str, **fields: str | int) -> str:
    """kind와 정식 문법 필드로 canonical 객체 ID를 만든다."""
    grammar = ID_GRAMMARS.get(kind)
    if grammar is None:
        raise IdGrammarError(f"unknown kind {kind!r}")
    return grammar.formatter(fields)


def _context_key_from_id(
    object_id: object,
    field: str,
    errors: list[str],
) -> str | None:
    if not isinstance(object_id, str):
        errors.append(f"{field} must be a canonical DomainContext ID")
        return None
    try:
        parsed = parse_id(object_id, "DomainContext")
    except IdGrammarError as exc:
        errors.append(f"{field} must be a canonical DomainContext ID: {exc}")
        return None
    return str(parsed.ctx)


def _validate_context_field(
    obj: Mapping[str, object],
    parsed: ParsedId,
    errors: list[str],
) -> None:
    if "context_id" not in obj:
        return
    context_key = _context_key_from_id(obj.get("context_id"), "context_id", errors)
    if context_key is not None and context_key != parsed.ctx:
        errors.append(
            f"context_id context key {context_key!r} does not match ID ctx {parsed.ctx!r}"
        )


def _validate_review_record(
    obj: Mapping[str, object],
    parsed: ParsedId,
    errors: list[str],
) -> None:
    if parsed.variant == "single":
        target = obj.get("target_object_id")
        if target is None:
            errors.append("target_object_id is required for single ReviewRecord")
        elif target != parsed.target_object_id:
            errors.append(
                f"target_object_id {target!r} does not match ID target "
                f"{parsed.target_object_id!r}"
            )
        if obj.get("review_scope") not in (None, "single_object"):
            errors.append("single ReviewRecord review_scope must be single_object")
        for field in (
            "target_object_ids",
            "bundle_key",
            "confirmation_key",
        ):
            if field in obj:
                errors.append(f"single ReviewRecord cannot use {field}")
        return

    if obj.get("review_scope") != "mapping_bundle":
        errors.append("bundle ReviewRecord must use mapping_bundle review_scope")
    if "target_object_id" in obj:
        errors.append("bundle ReviewRecord cannot use target_object_id")
    for field in ("bundle_key", "confirmation_key"):
        value = obj.get(field)
        if value is None:
            errors.append(f"bundle ReviewRecord requires {field}")
        elif value != parsed.bundle_key:
            errors.append(
                f"{field} {value!r} does not match ID bundle_key {parsed.bundle_key!r}"
            )
    targets = obj.get("target_object_ids")
    if not isinstance(targets, list) or not targets:
        errors.append("target_object_ids must be a non-empty list for bundle ReviewRecord")
        return
    for target in targets:
        try:
            target_id = parse_id(target, "DomainMapping")
        except (IdGrammarError, TypeError) as exc:
            errors.append(f"target_object_ids entry {target!r} is invalid: {exc}")
            continue
        if target_id.ctx != parsed.ctx:
            errors.append(
                f"target_object_ids entry {target!r} is outside bundle ctx {parsed.ctx!r}"
            )


def _validate_index_record(
    obj: Mapping[str, object],
    parsed: ParsedId,
    errors: list[str],
) -> None:
    index_name = obj.get("index_name")
    if index_name is not None and index_name != parsed.index_name:
        errors.append(
            f"index_name {index_name!r} does not match ID index_name {parsed.index_name!r}"
        )
    source_object_id = obj.get("source_object_id")
    if source_object_id is None:
        return
    if not isinstance(source_object_id, str):
        errors.append("source_object_id must be a canonical object ID")
        return
    try:
        parse_id(source_object_id)
    except IdGrammarError as exc:
        errors.append(f"source_object_id is not canonical: {exc}")
        return
    digest = hashlib.sha256(source_object_id.encode("utf-8")).hexdigest()[:16]
    if digest != parsed.source_id_digest:
        errors.append(
            f"source_object_id digest {digest!r} does not match ID digest "
            f"{parsed.source_id_digest!r}"
        )


def _validate_spec_revision(
    obj: Mapping[str, object],
    parsed: ParsedId,
    errors: list[str],
) -> None:
    spec_document_id = obj.get("spec_document_id")
    if spec_document_id is not None:
        try:
            document = parse_id(spec_document_id, "SpecDocument")
        except (IdGrammarError, TypeError) as exc:
            errors.append(f"spec_document_id is invalid: {exc}")
        else:
            if document.document_key != parsed.document_key:
                errors.append(
                    f"spec_document_id key {document.document_key!r} does not match "
                    f"ID document_key {parsed.document_key!r}"
                )
    revision_label = obj.get("revision_label")
    if revision_label is not None and revision_label != parsed.revision_key:
        errors.append(
            f"revision_label {revision_label!r} does not match ID revision_key "
            f"{parsed.revision_key!r}"
        )


def _validate_slide_ref(
    obj: Mapping[str, object],
    parsed: ParsedId,
    errors: list[str],
) -> None:
    spec_revision_id = obj.get("spec_revision_id")
    if spec_revision_id is not None:
        try:
            revision = parse_id(spec_revision_id, "SpecRevision")
        except (IdGrammarError, TypeError) as exc:
            errors.append(f"spec_revision_id is invalid: {exc}")
        else:
            expected = (parsed.document_key, parsed.revision_key)
            actual = (revision.document_key, revision.revision_key)
            if actual != expected:
                errors.append(
                    f"spec_revision_id keys {actual!r} do not match ID keys {expected!r}"
                )
    slide_no = obj.get("slide_no")
    if slide_no is not None:
        try:
            canonical_slide_no = _require_decimal(slide_no, "slide_no")
        except IdGrammarError as exc:
            errors.append(str(exc))
        else:
            if canonical_slide_no != parsed.slide_no:
                errors.append(
                    f"slide_no {slide_no!r} does not match ID slide_no {parsed.slide_no!r}"
                )


def validate_id_fields(obj: Mapping[str, object]) -> list[str]:
    """객체 ID 문법과 ID에 투영된 객체 필드가 일치하는지 검사한다."""
    object_id = obj.get("id")
    kind = obj.get("kind")
    display_id = object_id if isinstance(object_id, str) else "?"
    if not isinstance(kind, str) or kind not in ID_GRAMMARS:
        return [f"{display_id}: invalid id: unknown kind {kind!r}"]
    if not isinstance(object_id, str):
        return [f"{display_id}: invalid id for {kind}: object_id must be a string"]
    try:
        parsed = parse_id(object_id, kind)
    except IdGrammarError as exc:
        return [f"{display_id}: invalid id for {kind}: {exc}"]

    details: list[str] = []
    if kind == "ReviewRecord":
        _validate_review_record(obj, parsed, details)
    elif kind == "DomainContext":
        context_key = obj.get("context_key")
        if context_key is not None and context_key != parsed.ctx:
            details.append(
                f"context_key {context_key!r} does not match ID ctx {parsed.ctx!r}"
            )
    elif kind in {"GlossaryTerm", "ContextProjection", "DomainMapping"}:
        _validate_context_field(obj, parsed, details)
        if kind == "ContextProjection":
            fmt = obj.get("format")
            if fmt is not None and fmt != parsed.format:
                details.append(
                    f"format {fmt!r} does not match ID variant format {parsed.format!r}"
                )
        elif kind == "DomainMapping":
            mapping_key = obj.get("mapping_key")
            if mapping_key is not None and mapping_key != parsed.key:
                details.append(
                    f"mapping_key {mapping_key!r} does not match ID key {parsed.key!r}"
                )
    elif kind == "CurrentView":
        view_type = obj.get("view_type")
        if view_type is not None and view_type != parsed.view_type:
            details.append(
                f"view_type {view_type!r} does not match ID view_type {parsed.view_type!r}"
            )
    elif kind == "KnowledgePage":
        category = obj.get("category")
        if category is not None and category != parsed.category:
            details.append(
                f"category {category!r} does not match ID category {parsed.category!r}"
            )
    elif kind == "IndexRecord":
        _validate_index_record(obj, parsed, details)
    elif kind == "SpecRevision":
        _validate_spec_revision(obj, parsed, details)
    elif kind == "SlideRef":
        _validate_slide_ref(obj, parsed, details)

    return [f"{display_id}: invalid id fields: {detail}" for detail in details]
