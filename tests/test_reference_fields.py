"""Brain 객체 참조 필드 registry와 비파괴 rewrite 계약."""

import importlib

import pytest


SCALAR_FIELDS = frozenset({
    "context_id",
    "derived_from_event_id",
    "evidence_manifest_id",
    "review_record_id",
    "source_object_id",
    "spec_document_id",
    "spec_revision_id",
    "supersedes",
    "target_object_id",
})

LIST_FIELDS = frozenset({
    "affected_context_ids",
    "affected_glossary_term_ids",
    "affected_mapping_ids",
    "code_locator_ids",
    "decision_record_ids",
    "evidence_refs",
    "glossary_term_ids",
    "related_objects",
    "slack_thread_ids",
    "source_event_ids",
    "source_fact_ids",
    "source_object_ids",
    "spec_revision_ids",
    "supersedes_mapping_ids",
    "target_object_ids",
    "vouched_by_mapping_ids",
})


def _reference_fields():
    try:
        return importlib.import_module("project_brain.reference_fields")
    except ModuleNotFoundError:
        pytest.fail("project_brain.reference_fields public API is missing", pytrace=False)


def test_registry_is_the_exact_known_brain_reference_set():
    refs = _reference_fields()
    assert refs.SCALAR_REFERENCE_FIELDS == SCALAR_FIELDS
    assert refs.LIST_REFERENCE_FIELDS == LIST_FIELDS
    assert refs.NESTED_REFERENCE_POINTERS == ("/locator/code_locator_id",)


@pytest.mark.parametrize("field", sorted(SCALAR_FIELDS))
def test_scalar_reference_fields_are_discovered(field):
    refs = _reference_fields()
    obj = {field: "g.ctx.anchor"}

    assert list(refs.iter_object_refs(obj)) == [
        refs.ObjectRef(f"/{field}", "g.ctx.anchor")
    ]


@pytest.mark.parametrize("field", sorted(LIST_FIELDS))
def test_list_reference_fields_are_discovered(field):
    refs = _reference_fields()
    obj = {field: ["g.ctx.first", "g.ctx.second"]}

    assert list(refs.iter_object_refs(obj)) == [
        refs.ObjectRef(f"/{field}/0", "g.ctx.first"),
        refs.ObjectRef(f"/{field}/1", "g.ctx.second"),
    ]


def test_nested_code_locator_reference_is_discovered():
    refs = _reference_fields()
    obj = {
        "id": "evref.ctx.anchor",
        "kind": "EvidenceRef",
        "locator": {"code_locator_id": "code.ctx.anchor"},
    }

    assert list(refs.iter_object_refs(obj)) == [
        refs.ObjectRef("/locator/code_locator_id", "code.ctx.anchor")
    ]


def test_external_ids_are_not_brain_references():
    refs = _reference_fields()
    obj = {
        "jira_issue_ids": ["LGBBTWO-234"],
        "channel_id": "C123",
        "project_id": "bb2",
    }

    assert list(refs.iter_object_refs(obj)) == []


def test_malformed_reference_types_are_ignored_without_string_splitting():
    refs = _reference_fields()
    obj = {
        "context_id": ["context.ctx"],
        "source_object_ids": "mapping.ctx.anchor",
        "target_object_ids": {"mapping.ctx.anchor": True},
        "locator": {"code_locator_id": ["code.ctx.anchor"]},
    }

    assert list(refs.iter_object_refs(obj)) == []


def test_malformed_nested_reference_container_is_ignored():
    refs = _reference_fields()
    obj = {
        "locator": [
            {"code_locator_id": "code.ctx.not-at-the-registered-pointer"},
        ],
    }

    assert list(refs.iter_object_refs(obj)) == []


def test_invalid_nested_registry_escape_is_not_silently_ignored(monkeypatch):
    refs = _reference_fields()
    monkeypatch.setattr(
        refs,
        "NESTED_REFERENCE_POINTERS",
        ("/locator/bad~2field",),
    )

    with pytest.raises(ValueError, match="invalid JSON pointer escape"):
        list(refs.iter_object_refs({"locator": {"bad~2field": "code.ctx.anchor"}}))


def test_malformed_list_elements_are_ignored_individually():
    refs = _reference_fields()
    obj = {
        "source_object_ids": [
            "mapping.ctx.first",
            None,
            {"id": "mapping.ctx.not-a-ref"},
            "mapping.ctx.second",
        ],
    }

    assert list(refs.iter_object_refs(obj)) == [
        refs.ObjectRef("/source_object_ids/0", "mapping.ctx.first"),
        refs.ObjectRef("/source_object_ids/3", "mapping.ctx.second"),
    ]


def test_rewrite_is_non_mutating_scoped_and_preserves_list_order_and_duplicates():
    refs = _reference_fields()
    obj = {
        "target_object_id": "g.ctx.old",
        "supersedes": "g.ctx.old",
        "source_object_ids": [
            "g.ctx.old",
            "mapping.ctx.untouched",
            "g.ctx.old",
        ],
        "locator": {"code_locator_id": "g.ctx.old"},
        "jira_issue_ids": ["g.ctx.old"],
        "free_text": "g.ctx.old",
    }

    rewritten, changed = refs.rewrite_object_refs(
        obj,
        {"g.ctx.old": "g.ctx.new"},
    )

    assert rewritten == {
        "target_object_id": "g.ctx.new",
        "supersedes": "g.ctx.new",
        "source_object_ids": [
            "g.ctx.new",
            "mapping.ctx.untouched",
            "g.ctx.new",
        ],
        "locator": {"code_locator_id": "g.ctx.new"},
        "jira_issue_ids": ["g.ctx.old"],
        "free_text": "g.ctx.old",
    }
    assert changed == (
        refs.ObjectRef("/locator/code_locator_id", "g.ctx.old"),
        refs.ObjectRef("/source_object_ids/0", "g.ctx.old"),
        refs.ObjectRef("/source_object_ids/2", "g.ctx.old"),
        refs.ObjectRef("/supersedes", "g.ctx.old"),
        refs.ObjectRef("/target_object_id", "g.ctx.old"),
    )
    assert obj["target_object_id"] == "g.ctx.old"
    assert obj["supersedes"] == "g.ctx.old"
    assert obj["source_object_ids"] == [
        "g.ctx.old",
        "mapping.ctx.untouched",
        "g.ctx.old",
    ]
    assert obj["locator"] == {"code_locator_id": "g.ctx.old"}


def test_rewrite_returns_an_independent_copy_when_nothing_changes():
    refs = _reference_fields()
    obj = {
        "source_object_ids": ["mapping.ctx.anchor"],
        "locator": {"code_locator_id": "code.ctx.anchor"},
    }

    rewritten, changed = refs.rewrite_object_refs(obj, {})
    rewritten["source_object_ids"].append("mapping.ctx.new")
    rewritten["locator"]["code_locator_id"] = "code.ctx.new"

    assert changed == ()
    assert obj == {
        "source_object_ids": ["mapping.ctx.anchor"],
        "locator": {"code_locator_id": "code.ctx.anchor"},
    }


def test_json_pointer_tokens_use_rfc_6901_escaping(monkeypatch):
    refs = _reference_fields()
    monkeypatch.setattr(
        refs,
        "SCALAR_REFERENCE_FIELDS",
        frozenset({"field/with/slash", "field~with~tilde"}),
    )
    monkeypatch.setattr(refs, "LIST_REFERENCE_FIELDS", frozenset())
    monkeypatch.setattr(refs, "NESTED_REFERENCE_POINTERS", ())
    obj = {
        "field/with/slash": "g.ctx.slash",
        "field~with~tilde": "g.ctx.tilde",
    }

    assert list(refs.iter_object_refs(obj)) == [
        refs.ObjectRef("/field~1with~1slash", "g.ctx.slash"),
        refs.ObjectRef("/field~0with~0tilde", "g.ctx.tilde"),
    ]
    rewritten, changed = refs.rewrite_object_refs(
        obj,
        {
            "g.ctx.slash": "g.ctx.new-slash",
            "g.ctx.tilde": "g.ctx.new-tilde",
        },
    )
    assert rewritten == {
        "field/with/slash": "g.ctx.new-slash",
        "field~with~tilde": "g.ctx.new-tilde",
    }
    assert changed == (
        refs.ObjectRef("/field~0with~0tilde", "g.ctx.tilde"),
        refs.ObjectRef("/field~1with~1slash", "g.ctx.slash"),
    )


@pytest.mark.parametrize("pointer", ["/bad~2escape", "/dangling~"])
def test_json_pointer_rejects_invalid_escape_sequences(pointer):
    refs = _reference_fields()

    with pytest.raises(ValueError, match="invalid JSON pointer escape"):
        refs._pointer_tokens(pointer)


@pytest.mark.parametrize("token", ["01", "+1", "-0"])
def test_json_pointer_rejects_noncanonical_array_indices(token):
    refs = _reference_fields()

    with pytest.raises(ValueError, match="canonical decimal"):
        refs._value_at_pointer({"items": ["zero", "one"]}, f"/items/{token}")


def test_json_pointer_accepts_valid_escapes_and_canonical_array_indices():
    refs = _reference_fields()
    items = [str(index) for index in range(11)]

    assert refs._pointer_tokens("/a~0b/c~1d") == ("a~b", "c/d")
    assert refs._value_at_pointer({"items": items}, "/items/0") == "0"
    assert refs._value_at_pointer({"items": items}, "/items/1") == "1"
    assert refs._value_at_pointer({"items": items}, "/items/10") == "10"


def test_rewrite_rejects_non_string_replacement_keys():
    refs = _reference_fields()
    obj = {"target_object_id": "g.ctx.old"}

    with pytest.raises(TypeError, match="replacement keys must be strings"):
        refs.rewrite_object_refs(
            obj,
            {
                "g.ctx.old": "g.ctx.new",
                123: "g.ctx.other",
            },
        )

    assert obj == {"target_object_id": "g.ctx.old"}


def test_rewrite_rejects_non_string_replacement_values():
    refs = _reference_fields()
    obj = {"target_object_id": "g.ctx.old"}

    with pytest.raises(TypeError, match="replacement values must be strings"):
        refs.rewrite_object_refs(obj, {"g.ctx.old": 123})

    assert obj == {"target_object_id": "g.ctx.old"}
