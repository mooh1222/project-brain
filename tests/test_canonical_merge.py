"""기존 canonical DomainMapping으로 collision source를 합치는 순수 projection 계약."""

from copy import deepcopy

import pytest

from project_brain import canonical_merge
from project_brain.canonical_merge import (
    CollisionMergeError,
    ReferenceCollapse,
    project_collision_merges,
)
from project_brain.store import BrainStore


def _mapping(object_id: str, *, title: str, meaning: str) -> dict:
    context_id, mapping_key = object_id.rsplit(".", 1)
    return {
        "id": object_id,
        "kind": "DomainMapping",
        "status": "reviewed",
        "truth_role": "domain",
        "title": title,
        "context_id": context_id.replace("mapping.", "context.", 1),
        "mapping_key": mapping_key,
        "canonical_summary": f"summary for {title}",
        "meaning": meaning,
        "boundary": f"boundary for {title}",
        "caveats": ["history_coverage=partial"],
        "glossary_term_ids": ["g.ctx.term"],
        "decision_record_ids": [],
        "code_locator_ids": ["code.ctx.locator"],
        "evidence_refs": ["ev.ctx.evidence"],
        "schema_version": "0.1",
        "poc_priority": "P2",
        "created_at": "2026-06-12T00:00:00+09:00",
        "updated_at": "2026-06-12T00:00:00+09:00",
        "tags": ["ctx"],
        "review_record_id": "review.bundle.ctx.domain-mapping",
        "review_state": {
            "meaning_reviewed": True,
            "evidence_reviewed": True,
            "projection_reviewed": True,
        },
    }


def merge_pair() -> tuple[dict, dict]:
    target = _mapping(
        "mapping.ctx.canonical",
        title="canonical target",
        meaning="canonical meaning",
    )
    source = deepcopy(target)
    source.update(
        {
            "id": "mapping.ctx.collision",
            "title": "collision source",
            "mapping_key": "canonical",
            "canonical_summary": "source summary",
            "meaning": "source meaning",
            "boundary": "source boundary",
        }
    )
    return source, target


@pytest.mark.parametrize(
    ("tamper", "code"),
    [
        ({"status": "candidate"}, "merge_exact_field_mismatch"),
        ({"context_id": "context.other"}, "merge_exact_field_mismatch"),
        ({"mapping_key": "other"}, "merge_exact_field_mismatch"),
        ({"unknown": "source-only"}, "merge_unknown_field_mismatch"),
        ({"evidence_refs": ["ev.a", "ev.a"]}, "merge_list_duplicate"),
        ({"evidence_refs": "ev.a"}, "merge_list_invalid"),
    ],
)
def test_project_collision_merges_rejects_payload_drift(tamper, code):
    source, target = merge_pair()
    source.update(tamper)
    with pytest.raises(CollisionMergeError) as caught:
        project_collision_merges(
            {source["id"]: source, target["id"]: target},
            {source["id"]: target["id"]},
        )
    assert caught.value.code == code


def _project(source: dict, target: dict, *others: dict):
    objects = [source, target, *others]
    return project_collision_merges(
        {obj["id"]: obj for obj in objects},
        {source["id"]: target["id"]},
    )


def test_project_collision_merges_rejects_unknown_value_drift():
    source, target = merge_pair()
    source["future_field"] = {"value": "source"}
    target["future_field"] = {"value": "target"}
    with pytest.raises(CollisionMergeError) as caught:
        _project(source, target)
    assert caught.value.code == "merge_unknown_field_mismatch"


def test_project_collision_merges_keeps_target_text_and_unions_evidence():
    source, target = merge_pair()
    source["decision_record_ids"] = ["decision.source"]
    target["decision_record_ids"] = ["decision.target"]
    source["caveats"] = ["history_coverage=partial"]
    target["caveats"] = ["history_coverage=unsearched"]

    projection = _project(source, target)

    survivor = projection.after_by_id[target["id"]]
    assert survivor["meaning"] == target["meaning"]
    assert survivor["decision_record_ids"] == ["decision.target", "decision.source"]
    assert survivor["caveats"] == ["history_coverage=unsearched"]
    assert source["id"] not in projection.after_by_id


@pytest.mark.parametrize(
    ("source_caveats", "target_caveats", "code"),
    [
        (["history_coverage=partial"], [], "merge_caveat_invalid"),
        (
            ["history_coverage=unknown"],
            ["history_coverage=partial"],
            "merge_caveat_invalid",
        ),
        (
            ["history_coverage=partial", "history_coverage=complete"],
            ["history_coverage=partial"],
            "merge_caveat_invalid",
        ),
        (
            ["history_coverage=partial", "platform=ios"],
            ["history_coverage=partial", "platform=android"],
            "merge_caveat_conflict",
        ),
    ],
)
def test_project_collision_merges_rejects_invalid_caveats(
    source_caveats, target_caveats, code
):
    source, target = merge_pair()
    source["caveats"] = source_caveats
    target["caveats"] = target_caveats
    with pytest.raises(CollisionMergeError) as caught:
        _project(source, target)
    assert caught.value.code == code


def test_project_collision_merges_preserves_target_first_caveat_order():
    source, target = merge_pair()
    source["caveats"] = [
        "source-note",
        "history_coverage=partial",
        "platform=ios",
    ]
    target["caveats"] = [
        "target-note",
        "history_coverage=complete",
        "platform=ios",
    ]

    survivor = _project(source, target).after_by_id[target["id"]]

    assert survivor["caveats"] == [
        "target-note",
        "history_coverage=partial",
        "platform=ios",
        "source-note",
    ]


def test_project_collision_merges_rejects_missing_source():
    _, target = merge_pair()
    with pytest.raises(CollisionMergeError) as caught:
        project_collision_merges(
            {target["id"]: target},
            {"mapping.ctx.missing": target["id"]},
        )
    assert caught.value.code == "merge_source_missing"


def test_project_collision_merges_rejects_missing_target():
    source, _ = merge_pair()
    with pytest.raises(CollisionMergeError) as caught:
        project_collision_merges(
            {source["id"]: source},
            {source["id"]: "mapping.ctx.missing"},
        )
    assert caught.value.code == "merge_target_missing"


def test_project_collision_merges_rejects_identical_endpoints():
    _, target = merge_pair()
    with pytest.raises(CollisionMergeError) as caught:
        project_collision_merges(
            {target["id"]: target},
            {target["id"]: target["id"]},
        )
    assert caught.value.code == "merge_endpoint_identity"


def test_project_collision_merges_rejects_duplicate_target():
    source, target = merge_pair()
    second_source = deepcopy(source)
    second_source["id"] = "mapping.ctx.collision-two"
    with pytest.raises(CollisionMergeError) as caught:
        project_collision_merges(
            {
                source["id"]: source,
                second_source["id"]: second_source,
                target["id"]: target,
            },
            {
                source["id"]: target["id"],
                second_source["id"]: target["id"],
            },
        )
    assert caught.value.code == "merge_target_duplicate"


def test_project_collision_merges_rejects_endpoint_overlap():
    source, target = merge_pair()
    middle = deepcopy(source)
    middle["id"] = "mapping.ctx.middle"
    with pytest.raises(CollisionMergeError) as caught:
        project_collision_merges(
            {source["id"]: source, middle["id"]: middle, target["id"]: target},
            {source["id"]: middle["id"], middle["id"]: target["id"]},
        )
    assert caught.value.code == "merge_endpoint_overlap"


def test_project_collision_merges_rejects_non_mapping_target():
    source, target = merge_pair()
    target["kind"] = "DecisionRecord"
    with pytest.raises(CollisionMergeError) as caught:
        _project(source, target)
    assert caught.value.code == "merge_target_kind_invalid"


def test_project_collision_merges_rejects_noncanonical_target_id():
    source, target = merge_pair()
    target["id"] = "mapping.ctx.not_canonical"
    with pytest.raises(CollisionMergeError) as caught:
        _project(source, target)
    assert caught.value.code == "merge_target_id_invalid"


@pytest.mark.parametrize("field", ["source_object_id", "source_object_ids"])
def test_project_collision_merges_rejects_provenance_reference(field):
    source, target = merge_pair()
    value = source["id"] if field.endswith("_id") else [source["id"]]
    referrer = {
        "id": "insight.ctx.referrer",
        "kind": "Insight",
        field: value,
    }
    with pytest.raises(CollisionMergeError) as caught:
        _project(source, target, referrer)
    assert caught.value.code == "merge_provenance_reference"


def test_project_collision_merges_rejects_context_projection_scalar_provenance():
    source, target = merge_pair()
    projection = {
        "id": "projection.ctx.requirement.reuse",
        "kind": "ContextProjection",
        "source_object_id": source["id"],
        "source_object_ids": [],
    }

    with pytest.raises(CollisionMergeError) as caught:
        _project(source, target, projection)

    assert caught.value.code == "merge_context_projection_reference"


def _projection(*source_object_ids: str) -> dict:
    return {
        "id": "projection.ctx.requirement.reuse",
        "kind": "ContextProjection",
        "source_object_ids": list(source_object_ids),
    }


@pytest.mark.parametrize("dependency", ["source", "survivor", "referrer"])
def test_project_collision_merges_rejects_context_projection_dependency(dependency):
    source, target = merge_pair()
    if dependency == "survivor":
        source["decision_record_ids"] = ["decision.ctx.source"]
    referrer = {
        "id": "decision.ctx.referrer",
        "kind": "DecisionRecord",
        "target_object_id": source["id"],
    }
    dependency_id = {
        "source": source["id"],
        "survivor": target["id"],
        "referrer": referrer["id"],
    }[dependency]
    with pytest.raises(CollisionMergeError) as caught:
        _project(source, target, referrer, _projection(dependency_id))
    assert caught.value.code == "merge_context_projection_reference"


@pytest.mark.parametrize(
    "registered_reference",
    [
        {"evidence_refs": ["mapping.ctx.collision"]},
        {"related_objects": ["mapping.ctx.collision"]},
        {"context_id": "mapping.ctx.collision"},
        {"locator": {"code_locator_id": "mapping.ctx.collision"}},
    ],
    ids=["evidence_refs", "related_objects", "context_id", "nested_pointer"],
)
def test_project_collision_merges_prescans_every_context_projection_reference(
    registered_reference,
):
    source, target = merge_pair()
    context_projection = _projection()
    context_projection.update(deepcopy(registered_reference))
    original_bytes = BrainStore.object_bytes(context_projection)

    with pytest.raises(CollisionMergeError) as caught:
        _project(source, target, context_projection)

    assert caught.value.code == "merge_context_projection_reference"
    assert BrainStore.object_bytes(context_projection) == original_bytes


def test_registered_reference_rewrite_never_mutates_context_projection():
    source, target = merge_pair()
    context_projection = _projection()
    context_projection["evidence_refs"] = [source["id"]]
    after_by_id = {context_projection["id"]: deepcopy(context_projection)}

    changed_ids, collapses = canonical_merge._rewrite_registered_references(
        after_by_id,
        ((source["id"], target["id"]),),
    )

    assert BrainStore.object_bytes(after_by_id[context_projection["id"]]) == (
        BrainStore.object_bytes(context_projection)
    )
    assert changed_ids == set()
    assert collapses == []


def test_same_bytes_matches_brain_store_object_serialization():
    left = {"id": "g.ctx.term", "nested": {"enabled": True, "count": 1}}
    reordered = {
        "nested": {"enabled": True, "count": 1},
        "id": "g.ctx.term",
    }
    comparisons = (
        deepcopy(left),
        reordered,
        {"id": "g.ctx.term", "nested": {"enabled": 1, "count": 1}},
    )
    same_bytes = getattr(canonical_merge, "_same_bytes", None)

    assert callable(same_bytes)
    assert canonical_merge._json_exact(left, reordered)
    assert not same_bytes(left, reordered)
    for right in comparisons:
        assert same_bytes(left, right) is (
            BrainStore.object_bytes(left) == BrainStore.object_bytes(right)
        )


@pytest.mark.parametrize(
    "right",
    [
        {
            "id": "g.ctx.term",
            "nested": {
                "count": 1,
                "enabled": True,
                "items": [{"first": "a", "second": "b"}],
            },
        },
        {
            "id": "g.ctx.term",
            "nested": {
                "enabled": True,
                "count": 1,
                "items": [{"second": "b", "first": "a"}],
            },
        },
    ],
    ids=["nested-dict-order", "list-nested-dict-order"],
)
def test_same_bytes_matches_nested_brain_store_object_serialization(right):
    left = {
        "id": "g.ctx.term",
        "nested": {
            "enabled": True,
            "count": 1,
            "items": [{"first": "a", "second": "b"}],
        },
    }
    serialized_equal = (
        BrainStore.object_bytes(left) == BrainStore.object_bytes(right)
    )

    assert canonical_merge._json_exact(left, right)
    assert not serialized_equal
    assert canonical_merge._same_bytes(left, right) is serialized_equal


@pytest.mark.parametrize("survivor_changes", [False, True])
def test_changed_object_ids_are_exactly_the_byte_changed_live_objects(
    survivor_changes,
):
    source, target = merge_pair()
    if survivor_changes:
        source["decision_record_ids"] = ["decision.ctx.source"]
    existing_by_id = {source["id"]: source, target["id"]: target}

    projection = project_collision_merges(
        existing_by_id,
        {source["id"]: target["id"]},
    )

    expected_changed_ids = tuple(sorted(
        object_id
        for object_id, obj in projection.after_by_id.items()
        if (
            object_id in existing_by_id
            and BrainStore.object_bytes(existing_by_id[object_id])
            != BrainStore.object_bytes(obj)
        )
    ))
    assert projection.changed_object_ids == expected_changed_ids
    assert (target["id"] in projection.changed_object_ids) is survivor_changes


def test_project_collision_merges_rejects_registered_list_with_multiple_pairs():
    (drone_source, drone_target), (hedgehog_source, hedgehog_target) = (
        _real_collision_pairs()
    )
    referrer = {
        "id": "decision.ctx.multi-pair",
        "kind": "DecisionRecord",
        "related_objects": [drone_source["id"], hedgehog_target["id"]],
    }

    with pytest.raises(CollisionMergeError) as caught:
        project_collision_merges(
            {
                obj["id"]: obj
                for obj in (
                    drone_source,
                    drone_target,
                    hedgehog_source,
                    hedgehog_target,
                    referrer,
                )
            },
            {
                drone_source["id"]: drone_target["id"],
                hedgehog_source["id"]: hedgehog_target["id"],
            },
        )

    assert caught.value.code == "merge_reference_multi_pair"


def test_project_collision_merges_rejects_merge_source_collapse_referrer():
    (drone_source, drone_target), (hedgehog_source, hedgehog_target) = (
        _real_collision_pairs()
    )
    other_pair = [hedgehog_source["id"], hedgehog_target["id"]]
    drone_source["related_objects"] = list(other_pair)
    drone_target["related_objects"] = list(other_pair)

    with pytest.raises(CollisionMergeError) as caught:
        project_collision_merges(
            {
                obj["id"]: obj
                for obj in (
                    drone_source,
                    drone_target,
                    hedgehog_source,
                    hedgehog_target,
                )
            },
            {
                drone_source["id"]: drone_target["id"],
                hedgehog_source["id"]: hedgehog_target["id"],
            },
        )

    assert caught.value.code == "merge_reference_source_referrer"


@pytest.mark.parametrize(
    "bad_value",
    ["mapping.ctx.collision", ["mapping.ctx.collision", None]],
)
def test_project_collision_merges_rejects_malformed_reference_list(bad_value):
    source, target = merge_pair()
    referrer = {
        "id": "review.bundle.ctx.domain-mapping",
        "kind": "ReviewRecord",
        "target_object_ids": bad_value,
    }
    with pytest.raises(CollisionMergeError) as caught:
        _project(source, target, referrer)
    assert caught.value.code == "merge_reference_list_invalid"


@pytest.mark.parametrize("duplicate_endpoint", ["source", "target"])
def test_project_collision_merges_rejects_duplicate_merge_reference(duplicate_endpoint):
    source, target = merge_pair()
    duplicated_id = source["id"] if duplicate_endpoint == "source" else target["id"]
    referrer = {
        "id": "review.bundle.ctx.domain-mapping",
        "kind": "ReviewRecord",
        "target_object_ids": [duplicated_id, "mapping.ctx.other", duplicated_id],
    }
    with pytest.raises(CollisionMergeError) as caught:
        _project(source, target, referrer)
    assert caught.value.code == "merge_reference_duplicate"


def test_project_collision_merges_rewrites_registered_references_and_collapses_list():
    source, target = merge_pair()
    source["decision_record_ids"] = ["decision.ctx.source"]
    scalar_referrer = {
        "id": "decision.ctx.scalar",
        "kind": "DecisionRecord",
        "target_object_id": source["id"],
        "related_objects": ["g.ctx.before", source["id"], "g.ctx.after"],
        "locator": {"code_locator_id": source["id"]},
    }
    collapse_referrer = {
        "id": "review.bundle.ctx.domain-mapping",
        "kind": "ReviewRecord",
        "target_object_ids": [
            "mapping.ctx.before",
            source["id"],
            "mapping.ctx.middle",
            target["id"],
            "mapping.ctx.after",
        ],
    }
    untouched = {
        "id": "decision.ctx.untouched",
        "kind": "DecisionRecord",
        "target_object_ids": ["mapping.ctx.other", "mapping.ctx.other"],
    }
    before = deepcopy([source, target, scalar_referrer, collapse_referrer, untouched])

    projection = _project(
        source, target, scalar_referrer, collapse_referrer, untouched
    )

    rewritten_scalar = projection.after_by_id[scalar_referrer["id"]]
    assert rewritten_scalar["target_object_id"] == target["id"]
    assert rewritten_scalar["related_objects"] == [
        "g.ctx.before",
        target["id"],
        "g.ctx.after",
    ]
    assert rewritten_scalar["locator"]["code_locator_id"] == target["id"]
    assert projection.after_by_id[collapse_referrer["id"]]["target_object_ids"] == [
        "mapping.ctx.before",
        "mapping.ctx.middle",
        target["id"],
        "mapping.ctx.after",
    ]
    assert projection.after_by_id[untouched["id"]] == untouched
    assert projection.changed_object_ids == tuple(
        sorted((target["id"], scalar_referrer["id"], collapse_referrer["id"]))
    )
    assert projection.reference_collapses == (
        ReferenceCollapse(
            object_id=collapse_referrer["id"],
            pointer="/target_object_ids",
            before_ids=tuple(collapse_referrer["target_object_ids"]),
            after_ids=(
                "mapping.ctx.before",
                "mapping.ctx.middle",
                target["id"],
                "mapping.ctx.after",
            ),
            removed_index=1,
        ),
    )
    assert [source, target, scalar_referrer, collapse_referrer, untouched] == before

    projection.after_by_id[untouched["id"]]["target_object_ids"].append("changed")
    assert untouched["target_object_ids"] == ["mapping.ctx.other", "mapping.ctx.other"]


def _real_collision_pairs() -> tuple[tuple[dict, dict], tuple[dict, dict]]:
    drone_source = _mapping(
        "mapping.disturb-drone.cloud-reskin-identity",
        title="드론은 먹구름/뭉게구름 리스킨",
        meaning="드론 방해버블은 기존 구름과 기능이 같고 디자인만 다르다.",
    )
    drone_target = _mapping(
        "mapping.disturb-drone.drone-cloud-reskin-identity",
        title="Candidate mapping: drone-cloud-reskin-identity",
        meaning="베타드론과 알파드론은 구름 계층을 상속한 리스킨이다.",
    )
    for obj in (drone_source, drone_target):
        obj["mapping_key"] = "drone-cloud-reskin-identity"
        obj["review_record_id"] = "review.bundle.disturb-drone.domain-mapping"
        obj["tags"] = ["disturb-drone"]
    drone_source.update(
        {
            "decision_record_ids": [
                "decision.disturb-drone.drone-pop-sound",
                "decision.disturb-drone.factory-break-fix",
            ],
            "glossary_term_ids": [
                "g.disturb-drone.betadrone",
                "g.disturb-drone.alphadrone",
                "g.disturb-drone.cloud-reskin",
            ],
            "code_locator_ids": [
                "code.disturb-drone.bubble-object",
                "code.disturb-drone.sprite",
                "code.disturb-drone.factory",
                "code.disturb-drone.type-enum",
            ],
            "evidence_refs": [
                "evref.disturb-drone.spec-concept",
                "evref.disturb-drone.code-drone-class",
                "evref.disturb-drone.code-sprite",
                "evref.disturb-drone.code-factory",
            ],
        }
    )
    drone_target.update(
        {
            "decision_record_ids": [],
            "glossary_term_ids": ["g.disturb-drone.cloud-reskin"],
            "code_locator_ids": [
                "code.disturb-drone.bubble-object",
                "code.disturb-drone.support-init",
                "code.disturb-drone.sprite",
            ],
            "evidence_refs": [
                "evref.disturb-drone.spec-concept",
                "evref.disturb-drone.pr-7052",
            ],
        }
    )

    hedgehog_source = _mapping(
        "mapping.disturb-hedgehog.angry-shoot-block",
        title="화난 상태 슈팅버블 HIT 제거",
        meaning="화난 상태에서는 충돌한 슈팅버블이 제거된다.",
    )
    hedgehog_target = _mapping(
        "mapping.disturb-hedgehog.angry-shoot-bubble-removal",
        title="Candidate mapping: 화난 고슴도치 HIT",
        meaning="화난 고슴도치는 충돌한 슈팅버블을 제거한다.",
    )
    for obj in (hedgehog_source, hedgehog_target):
        obj["mapping_key"] = "angry-shoot-bubble-removal"
        obj["review_record_id"] = "review.bundle.disturb-hedgehog.domain-mapping"
        obj["tags"] = ["disturb-hedgehog"]
    hedgehog_source["caveats"] = ["history_coverage=partial"]
    hedgehog_target["caveats"] = ["history_coverage=unsearched"]
    hedgehog_source["evidence_refs"] = [
        "evref.disturb-hedgehog.spec-concept",
        "evref.disturb-hedgehog.code-angry-block-shoot",
    ]
    hedgehog_target["evidence_refs"] = [
        "evref.disturb-hedgehog.code-shootable-remover-classify"
    ]
    return (drone_source, drone_target), (hedgehog_source, hedgehog_target)


def test_project_collision_merges_matches_the_two_real_collision_payloads():
    (drone_source, drone_target), (hedgehog_source, hedgehog_target) = (
        _real_collision_pairs()
    )

    projection = project_collision_merges(
        {
            obj["id"]: obj
            for obj in (
                drone_source,
                drone_target,
                hedgehog_source,
                hedgehog_target,
            )
        },
        {
            drone_source["id"]: drone_target["id"],
            hedgehog_source["id"]: hedgehog_target["id"],
        },
    )

    drone_survivor = projection.after_by_id[drone_target["id"]]
    hedgehog_survivor = projection.after_by_id[hedgehog_target["id"]]
    assert drone_survivor["decision_record_ids"] == [
        "decision.disturb-drone.drone-pop-sound",
        "decision.disturb-drone.factory-break-fix",
    ]
    assert hedgehog_survivor["caveats"] == ["history_coverage=unsearched"]
