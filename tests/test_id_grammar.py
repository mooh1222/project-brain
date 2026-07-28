import hashlib

import pytest

from project_brain.id_grammar import (
    ID_GRAMMARS,
    IdGrammarError,
    format_id,
    parse_id,
    validate_id_fields,
)
from project_brain.schema import VALID_KINDS


SOURCE_ID = "mapping.ctx.source"
SOURCE_DIGEST = hashlib.sha256(SOURCE_ID.encode("utf-8")).hexdigest()[:16]


ROUND_TRIP_CASES = (
    ("EvidenceManifest", {"ctx": "ctx", "key": "source"}, "manifest.ctx.source"),
    ("EvidenceRef", {"ctx": "ctx", "anchor_key": "jira-234--2"}, "evref.ctx.jira-234--2"),
    ("ReviewRecord", {"target_object_id": "g.ctx.key"}, "review.g.ctx.key"),
    ("EventLedgerRecord", {"ctx": "ctx", "key": "event"}, "ledger.ctx.event"),
    ("TemporalFact", {"ctx": "ctx", "key": "state"}, "fact.ctx.state"),
    ("CodeLocator", {"ctx": "ctx", "anchor_key": "shoot-action--6"}, "code.ctx.shoot-action--6"),
    ("DomainContext", {"ctx": "ctx"}, "context.ctx"),
    ("GlossaryTerm", {"ctx": "ctx", "key": "term"}, "g.ctx.term"),
    (
        "ContextProjection",
        {"ctx": "ctx", "format": "context_md"},
        "projection.ctx.context-md",
    ),
    (
        "ContextProjection",
        {"ctx": "ctx", "requirement_key": "result-popup", "format": "prompt_payload"},
        "projection.ctx.result-popup.reuse",
    ),
    ("CurrentView", {"view_type": "feature_status", "key": "main"}, "view.feature-status.main"),
    ("KnowledgePage", {"category": "guide", "key": "main"}, "page.guide.main"),
    (
        "IndexRecord",
        {"index_name": "code_locator", "source_id_digest": SOURCE_DIGEST},
        f"index.code-locator.{SOURCE_DIGEST}",
    ),
    ("SpecDocument", {"document_key": "game-spec"}, "spec.game-spec"),
    (
        "SpecRevision",
        {"document_key": "game-spec", "revision_key": "v2"},
        "revision.game-spec.v2",
    ),
    (
        "SlideRef",
        {"document_key": "game-spec", "revision_key": "v2", "slide_no": 3},
        "slide.game-spec.v2.3",
    ),
    ("SlackThread", {"ctx": "ctx", "key": "thread"}, "slack.ctx.thread"),
    ("DecisionRecord", {"ctx": "ctx", "key": "decision"}, "decision.ctx.decision"),
    ("DomainMapping", {"ctx": "ctx", "key": "mapping"}, "mapping.ctx.mapping"),
    ("Insight", {"ctx": "ctx", "key": "risk"}, "insight.ctx.risk"),
)


def test_registry_exactly_covers_schema_kinds():
    assert frozenset(ID_GRAMMARS) == VALID_KINDS


@pytest.mark.parametrize(("kind", "fields", "expected"), ROUND_TRIP_CASES)
def test_all_id_forms_format_and_parse_round_trip(kind, fields, expected):
    object_id = format_id(kind, **fields)

    assert object_id == expected
    parsed = parse_id(object_id, kind)
    assert parsed.kind == kind
    assert parsed.object_id == expected
    assert format_id(kind, **fields) == parsed.object_id


def test_review_record_variants_round_trip():
    single = parse_id("review.mapping.ctx.key", "ReviewRecord")
    bundle = parse_id("review.bundle.ctx.key", "ReviewRecord")
    nested_bundle = parse_id("review.review.bundle.ctx.key", "ReviewRecord")

    assert single.variant == "single"
    assert single.target_object_id == "mapping.ctx.key"
    assert bundle.variant == "bundle"
    assert bundle.ctx == "ctx"
    assert bundle.key == "key"
    assert bundle.bundle_key == "bundle.ctx.key"
    assert nested_bundle.variant == "single"
    assert nested_bundle.target_object_id == "review.bundle.ctx.key"
    assert (
        format_id(
            "ReviewRecord",
            target_object_id=nested_bundle.target_object_id,
        )
        == nested_bundle.object_id
    )


def test_deep_nested_review_validation_fails_closed_without_recursion_error():
    object_id = "review." * 500 + "g.ctx.key"

    errors = validate_id_fields(
        {
            "id": object_id,
            "kind": "ReviewRecord",
        }
    )

    assert any("target_object_id is required" in error for error in errors)


def test_deep_nested_review_formatter_does_not_recurse():
    target_object_id = "review." * 500 + "g.ctx.key"

    assert format_id(
        "ReviewRecord",
        target_object_id=target_object_id,
    ) == f"review.{target_object_id}"


def test_context_projection_variants_round_trip():
    context_md = parse_id("projection.ctx.context-md", "ContextProjection")
    reuse = parse_id("projection.ctx.requirement.reuse", "ContextProjection")

    assert context_md.variant == "context_md"
    assert context_md.format == "context_md"
    assert reuse.variant == "reuse"
    assert reuse.format == "prompt_payload"
    assert reuse.requirement_key == "requirement"


def test_anchor_suffix_is_not_pollution():
    assert parse_id("code.ctx.shoot-action--6", "CodeLocator").anchor_key == "shoot-action--6"


def test_parser_can_infer_kind_without_prefix_fallback():
    assert parse_id("g.ctx.term").kind == "GlossaryTerm"
    assert parse_id("review.bundle.ctx.key").kind == "ReviewRecord"


def test_unknown_kind_is_rejected():
    with pytest.raises(IdGrammarError, match="unknown kind"):
        parse_id("g.ctx.term", "NoSuchKind")


def test_unknown_prefix_is_rejected():
    with pytest.raises(IdGrammarError, match="unknown ID prefix"):
        parse_id("unknown.ctx.term")


def test_wrong_prefix_for_known_kind_is_rejected():
    with pytest.raises(IdGrammarError):
        parse_id("mapping.ctx.term", "GlossaryTerm")


def test_underscore_is_rejected():
    with pytest.raises(IdGrammarError):
        parse_id("g.ctx.bad_key", "GlossaryTerm")


def test_empty_piece_is_rejected():
    with pytest.raises(IdGrammarError):
        parse_id("mapping.ctx..key", "DomainMapping")


def test_leading_zero_decimal_is_rejected():
    with pytest.raises(IdGrammarError):
        parse_id("slide.game-spec.v2.03", "SlideRef")


def test_uppercase_jira_internal_key_is_rejected():
    assert validate_id_fields(
        {"id": "evref.ctx.jira-LGBBTWO-234", "kind": "EvidenceRef"}
    )


def test_index_record_digest_must_be_lowercase_hex():
    with pytest.raises(IdGrammarError):
        parse_id("index.fts.0123456789abcdeG", "IndexRecord")


def test_index_record_digest_must_match_source_object_id():
    errors = validate_id_fields(
        {
            "id": "index.fts.0123456789abcdef",
            "kind": "IndexRecord",
            "index_name": "fts",
            "source_object_id": SOURCE_ID,
        }
    )

    assert any("source_object_id digest" in error for error in errors)


def test_index_record_name_must_match_object_field():
    errors = validate_id_fields(
        {
            "id": f"index.code-locator.{SOURCE_DIGEST}",
            "kind": "IndexRecord",
            "index_name": "fts",
            "source_object_id": SOURCE_ID,
        }
    )

    assert any("index_name" in error for error in errors)


def test_single_review_record_target_must_match_id():
    errors = validate_id_fields(
        {
            "id": "review.g.ctx.term",
            "kind": "ReviewRecord",
            "target_object_id": "g.ctx.other",
        }
    )

    assert any("target_object_id" in error for error in errors)


def test_bundle_review_record_bundle_key_must_match_id():
    errors = validate_id_fields(
        {
            "id": "review.bundle.ctx.mapping",
            "kind": "ReviewRecord",
            "review_scope": "mapping_bundle",
            "bundle_key": "bundle.ctx.other",
        }
    )

    assert any("bundle_key" in error for error in errors)


def test_bundle_review_record_requires_bundle_variant_fields():
    errors = validate_id_fields(
        {
            "id": "review.bundle.ctx.mapping",
            "kind": "ReviewRecord",
            "target_object_id": "mapping.ctx.mapping",
        }
    )

    assert any("review_scope" in error for error in errors)
    assert any("bundle_key" in error for error in errors)
    assert any("confirmation_key" in error for error in errors)
    assert any("target_object_ids" in error for error in errors)
    assert any("target_object_id" in error for error in errors)


def test_bundle_review_record_requires_nonempty_target_list():
    errors = validate_id_fields(
        {
            "id": "review.bundle.ctx.mapping",
            "kind": "ReviewRecord",
            "review_scope": "mapping_bundle",
            "bundle_key": "bundle.ctx.mapping",
            "confirmation_key": "bundle.ctx.mapping",
            "target_object_ids": "mapping.ctx.mapping",
        }
    )

    assert any("target_object_ids must be a non-empty list" in error for error in errors)


def test_bundle_review_record_targets_must_be_mappings_in_same_context():
    errors = validate_id_fields(
        {
            "id": "review.bundle.ctx.mapping",
            "kind": "ReviewRecord",
            "review_scope": "mapping_bundle",
            "bundle_key": "bundle.ctx.mapping",
            "confirmation_key": "bundle.ctx.mapping",
            "target_object_ids": [
                "g.ctx.term",
                "mapping.other.mapping",
            ],
        }
    )

    assert any("g.ctx.term" in error and "invalid" in error for error in errors)
    assert any("mapping.other.mapping" in error and "outside bundle ctx" in error
               for error in errors)


def test_bundle_review_record_confirmation_key_must_match_id():
    errors = validate_id_fields(
        {
            "id": "review.bundle.ctx.mapping",
            "kind": "ReviewRecord",
            "review_scope": "mapping_bundle",
            "bundle_key": "bundle.ctx.mapping",
            "confirmation_key": "bundle.ctx.other",
            "target_object_ids": ["mapping.ctx.mapping"],
        }
    )

    assert any("confirmation_key" in error for error in errors)


def test_single_review_record_requires_only_single_variant_fields():
    errors = validate_id_fields(
        {
            "id": "review.g.ctx.term",
            "kind": "ReviewRecord",
            "review_scope": "single_object",
            "target_object_ids": ["mapping.ctx.mapping"],
            "bundle_key": "bundle.ctx.mapping",
        }
    )

    assert any("target_object_id is required" in error for error in errors)
    assert any("target_object_ids" in error for error in errors)
    assert any("bundle_key" in error for error in errors)


def test_context_projection_format_must_match_variant():
    errors = validate_id_fields(
        {
            "id": "projection.ctx.context-md",
            "kind": "ContextProjection",
            "format": "prompt_payload",
        }
    )

    assert any("format" in error for error in errors)


def test_spec_revision_document_reference_key_must_match_id():
    errors = validate_id_fields(
        {
            "id": "revision.game-spec.v2",
            "kind": "SpecRevision",
            "spec_document_id": "spec.other",
            "revision_label": "v2",
        }
    )

    assert any("spec_document_id" in error for error in errors)


def test_spec_revision_label_must_match_id():
    errors = validate_id_fields(
        {
            "id": "revision.game-spec.v2",
            "kind": "SpecRevision",
            "spec_document_id": "spec.game-spec",
            "revision_label": "v3",
        }
    )

    assert any("revision_label" in error for error in errors)


def test_slide_ref_revision_reference_keys_must_match_id():
    errors = validate_id_fields(
        {
            "id": "slide.game-spec.v2.3",
            "kind": "SlideRef",
            "spec_revision_id": "revision.game-spec.v3",
            "slide_no": 3,
        }
    )

    assert any("spec_revision_id" in error for error in errors)


def test_slide_number_must_match_id():
    errors = validate_id_fields(
        {
            "id": "slide.game-spec.v2.3",
            "kind": "SlideRef",
            "spec_revision_id": "revision.game-spec.v2",
            "slide_no": 4,
        }
    )

    assert any("slide_no" in error for error in errors)


def test_format_rejects_unknown_fields_instead_of_falling_back():
    with pytest.raises(IdGrammarError):
        format_id("GlossaryTerm", ctx="ctx", key="term", ignored="value")


def test_missing_parsed_field_attribute_raises_attribute_error():
    parsed = parse_id("g.ctx.term", "GlossaryTerm")

    with pytest.raises(AttributeError):
        _ = parsed.anchor_key
