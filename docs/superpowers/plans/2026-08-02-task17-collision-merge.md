# Task 17 Collision Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 canonical `DomainMapping`을 survivor로 유지하면서 collision source 두 개의 근거와 참조를 손실 없이 합치고, 새 엔진 SHA에 다시 묶은 156행 결정 원장을 사용자 승인 게이트까지 완성한다.

**Architecture:** `canonical_merge.py`의 순수 projection이 payload 병합, 참조 치환, 배열 축약을 한 번만 계산한다. canonical ledger, planner, mutation validator, grandfather 비교, canonical artifact, intermediate receipt가 같은 projection을 소비하며, 실제 파일 변경은 기존 `CANONICAL_REPAIR` 원자적 transaction을 그대로 사용한다. 엔진 변경이 검증된 뒤에는 기존 Task 7 산출물을 보존형 archive하고 snapshot·Phase A·workbook을 새 엔진 SHA로 다시 생성한다.

**Tech Stack:** Python 3.11+, dataclasses, strict JSON, SHA-256 receipts, `BrainStore`, `MutationService`, pytest, unittest, Git worktree, Orca orchestration.

## Global Constraints

- 기존 target의 `title`, `canonical_summary`, `meaning`, `boundary`, `poc_priority`를 그대로 유지한다.
- source 전용 `code_locator_ids`, `decision_record_ids`, `evidence_refs`, `glossary_term_ids`, `tags`는 target-first stable union으로 보존한다.
- `caveats`의 `history_coverage`는 `unsearched < partial < complete` 중 더 보수적인 값을 하나만 남기며, 같은 key의 다른 충돌은 중단한다.
- source와 target의 unknown key set 또는 unknown value가 다르면 중단한다.
- `source_object_id` 또는 `source_object_ids`에서 merge source가 발견되면 중단한다.
- `ContextProjection.source_object_ids`가 merge source뿐 아니라 merge로 내용이 바뀌는 survivor 또는 referrer를 가리켜도 source-content hash가 낡으므로 중단한다.
- source delete, survivor update, referrer update는 기존 canonical repair transaction 하나에 들어간다.
- `request.renames`에는 기존 field-repair 5쌍만 들어가며 merge 2쌍은 들어가지 않는다.
- 배열 축약은 `reference_rewrites`에 가짜 index diff를 만들지 않고 canonical row의 `merge_receipt`에 기록한다.
- 기존 MutationManifest top-level schema와 journal schema를 바꾸지 않는다.
- 모든 production 변경은 실패하는 테스트를 먼저 확인한다.
- 합성 테스트에서는 실모델을 쓰지 않는다.
- BB2 object, eval, index, stale는 정확한 결정 원장을 사용자가 승인하기 전까지 바꾸지 않는다.
- Task 9는 정확한 ledger bytes에 대한 사용자 승인이 있기 전에는 시작하지 않는다.
- Terminal/Orca 권한이나 UI는 다시 검사하거나 변경하지 않는다.
- push, merge, BB2 staging은 하지 않는다.

---

## File Map

- Create `src/project_brain/canonical_merge.py`: collision merge의 payload·참조·배열 축약을 계산하는 순수 projection과 결과 dataclass.
- Create `tests/test_canonical_merge.py`: payload 정책, endpoint, 출처 참조, projection, 배열 축약의 집중 회귀.
- Modify `src/project_brain/canonical_repair.py`: 새 ledger action, merge map, planner, row receipt, artifact parser, intermediate receipt.
- Modify `tests/test_canonical_repair.py`: 156행 ledger 계약, planner/artifact/apply/intermediate 통합 회귀.
- Modify `tests/test_cli.py`: canonical repair CLI의 `row_count` 기대값을 merge row 2개를 포함한 7로 맞춘다.
- Modify `src/project_brain/mutation.py`: merge intent 검증, expected payload 재계산, grandfather comparison, 축약 field의 pointer diff 억제.
- Modify `tests/test_mutation.py`: 승인된 existing-target merge 허용과 승인 없는 merge/delete-only 거부.
- Modify `tests/test_corpus_io.py`: canonical merge transaction의 모든 장애 지점 rollback/recovery 회귀.
- Modify `docs/design-canonical.md`: canonical repair action과 merge receipt 계약.
- Modify `ROADMAP.md`: Task 17 collision merge engine 지원과 아직 닫히지 않은 사용자 승인 게이트 상태.
- Regenerate in BB2 `brain/recovery/2026-07-28/id-migration/phase-a-measurement.json`, `phase-a-classification.json`, `phase-a-feasibility.json`: 새 engine SHA binding만 반영한 Phase A 산출물.
- Create in BB2 `brain/recovery/2026-07-28/id-migration/canonicalization-decisions.json`: 검증된 156행 결정 원장.
- Regenerate outside Git `$TASK17_RECEIPTS/decision-review.json`: 새 engine SHA에 묶인 review workbook.

---

### Task 1: Pure Collision Merge Projection

**Files:**

- Create: `src/project_brain/canonical_merge.py`
- Create: `tests/test_canonical_merge.py`
- Read: `src/project_brain/reference_fields.py`
- Read: the four BB2 collision objects named in the design spec

**Interfaces:**

- Consumes: `existing_by_id: Mapping[str, Mapping[str, object]]`, `merge_pairs: Mapping[str, str]`.
- Produces:

```python
@dataclass(frozen=True)
class ReferenceCollapse:
    object_id: str
    pointer: str
    before_ids: tuple[str, ...]
    after_ids: tuple[str, ...]
    removed_index: int


@dataclass(frozen=True)
class CollisionMergeProjection:
    after_by_id: dict[str, dict]
    merge_pairs: tuple[tuple[str, str], ...]
    changed_object_ids: tuple[str, ...]
    reference_collapses: tuple[ReferenceCollapse, ...]


@dataclass(frozen=True)
class CollisionMergeError(ValueError):
    code: str
    detail: str


project_collision_merges(
    existing_by_id: Mapping[str, Mapping[str, object]],
    merge_pairs: Mapping[str, str],
) -> CollisionMergeProjection
```

- `after_by_id`는 source를 제거한 전체 logical store이며 입력 객체를 변경하지 않는다.
- `changed_object_ids`는 survivor와 실제로 바뀐 referrer만 정렬해 담는다.

- [ ] **Step 1: payload 정책의 실패 테스트를 작성한다**

`tests/test_canonical_merge.py`에 실제 DomainMapping key set을 가진 factory를 만들고 아래 표를 parameterize한다.

```python
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
```

- [ ] **Step 2: RED를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_canonical_merge.py -q`

Expected: collection FAIL because `project_brain.canonical_merge` does not exist.

- [ ] **Step 3: payload merge의 최소 구현을 작성한다**

`canonical_merge.py`에 field 집합을 상수로 두고 다음 순서로 survivor를 만든다.

```python
_TARGET_FIELDS = frozenset({
    "title", "canonical_summary", "meaning", "boundary", "poc_priority",
})
_EXACT_FIELDS = frozenset({
    "kind", "schema_version", "status", "truth_role", "context_id",
    "mapping_key", "review_record_id", "review_state", "created_at", "updated_at",
})
_UNION_FIELDS = frozenset({
    "code_locator_ids", "decision_record_ids", "evidence_refs",
    "glossary_term_ids", "tags",
})
_HISTORY_ORDER = {"unsearched": 0, "partial": 1, "complete": 2}


def _stable_union(target: list[str], source: list[str]) -> list[str]:
    seen = set(target)
    return [*target, *(item for item in source if item not in seen)]
```

`_merge_payload(source, target)`는 key set을 먼저 비교하고, exact field equality를 검사한 뒤 target 복사본의 union field와 caveats만 갱신한다. `id`는 target ID를 유지한다. `id`, target-authoritative, exact, union, caveat 집합을 제외하고 남은 residual key는 양쪽 값이 JSON-exact로 같아야 한다. 같은 residual key의 값이 다르면 `merge_unknown_field_mismatch`로 중단한다. `history_coverage`가 한쪽에만 있거나 허용값 밖이면 `merge_caveat_invalid`, 같은 다른 key가 서로 다른 값이면 `merge_caveat_conflict`로 중단한다.

다음 별도 회귀로 같은 unknown key의 값 차이를 잡는다.

```python
def test_project_collision_merges_rejects_unknown_value_drift():
    source, target = merge_pair()
    source["future_field"] = {"value": "source"}
    target["future_field"] = {"value": "target"}
    with pytest.raises(CollisionMergeError) as caught:
        project_collision_merges(
            {source["id"]: source, target["id"]: target},
            {source["id"]: target["id"]},
        )
    assert caught.value.code == "merge_unknown_field_mismatch"
```

- [ ] **Step 4: target-authoritative, stable union, 보수적 caveat 테스트를 추가하고 통과시킨다**

```python
def test_project_collision_merges_keeps_target_text_and_unions_evidence():
    source, target = merge_pair()
    source["decision_record_ids"] = ["decision.source"]
    target["decision_record_ids"] = ["decision.target"]
    source["caveats"] = ["history_coverage=partial"]
    target["caveats"] = ["history_coverage=unsearched"]

    projection = project_collision_merges(
        {source["id"]: source, target["id"]: target},
        {source["id"]: target["id"]},
    )

    survivor = projection.after_by_id[target["id"]]
    assert survivor["meaning"] == target["meaning"]
    assert survivor["decision_record_ids"] == ["decision.target", "decision.source"]
    assert survivor["caveats"] == ["history_coverage=unsearched"]
    assert source["id"] not in projection.after_by_id
```

Run: `.venv/bin/python -m pytest tests/test_canonical_merge.py -q`

Expected: PASS.

- [ ] **Step 5: endpoint와 참조 축약 실패 테스트를 작성한다**

다음 경우를 exact error code로 검사한다.

```text
merge_source_missing
merge_target_missing
merge_endpoint_identity
merge_target_duplicate
merge_endpoint_overlap
merge_target_kind_invalid
merge_target_id_invalid
merge_provenance_reference
merge_context_projection_reference
merge_reference_duplicate
merge_reference_list_invalid
```

그리고 source-only 배열은 같은 자리 target 치환, source+target 배열은 source 한 항목 제거, unrelated 항목의 상대 순서는 유지하는지 검사한다.

- [ ] **Step 6: 참조 projection과 `ReferenceCollapse`를 구현한다**

등록된 scalar/list/nested reference만 처리한다. list field에 source와 target이 각각 한 번 있으면 `pointer`를 배열 field 자체(`/target_object_ids`)로 기록하고 source index를 `removed_index`에 넣는다. source 또는 target count가 2 이상이면 중단한다. `source_object_id(s)`의 merge-source 참조는 치환하지 않고 실패한다. merge payload와 모든 referrer projection을 계산해 `changed_object_ids`를 확정한 뒤, 모든 `ContextProjection.source_object_ids`가 merge source 집합 또는 `changed_object_ids`와 겹치지 않는지 검사한다. merge source 의존, survivor 의존, 변경 referrer 의존을 각각 실패 테스트로 고정한다.

```python
ReferenceCollapse(
    object_id=str(obj["id"]),
    pointer=f"/{field_name}",
    before_ids=tuple(value),
    after_ids=tuple(rewritten_value),
    removed_index=source_index,
)
```

Run: `.venv/bin/python -m pytest tests/test_canonical_merge.py tests/test_reference_fields.py -q`

Expected: PASS; existing duplicate-preserving `rewrite_object_refs()` tests remain unchanged.

- [ ] **Step 7: 실제 네 payload를 읽는 read-only regression을 추가한다**

테스트에 BB2 절대경로를 넣지 않는다. 네 실제 payload에서 필요한 fixture를 `tests/test_canonical_merge.py`에 복사해 두 pair의 결과를 고정한다.

```python
assert drone_survivor["decision_record_ids"] == [
    "decision.disturb-drone.drone-pop-sound",
    "decision.disturb-drone.factory-break-fix",
]
assert hedgehog_survivor["caveats"] == ["history_coverage=unsearched"]
```

Run: `.venv/bin/python -m pytest tests/test_canonical_merge.py -q`

Expected: PASS.

- [ ] **Step 8: 커밋한다**

```bash
git add src/project_brain/canonical_merge.py tests/test_canonical_merge.py
git diff --cached --check
git commit -m "feat(brain): add canonical collision merge projection"
```

---

### Task 2: Ledger Action and Endpoint Validation

**Files:**

- Modify: `src/project_brain/canonical_repair.py`
- Modify: `tests/test_canonical_repair.py`
- Modify: `tests/test_cli.py`

**Interfaces:**

- Consumes: Task 1 `project_collision_merges()`.
- Produces:

```python
CanonicalAction.COLLISION_MERGE_INTO_EXISTING = "collision_merge_into_existing"


collision_merges_from_ledger(
    ledger: CanonicalizationLedger,
) -> dict[str, str]
```

- `canonical_repair_renames_from_ledger()`는 기존 5쌍만 반환한다.
- `id_renames_from_ledger()`는 merge source를 반환하지 않는다.

- [ ] **Step 1: decoder와 action count RED 테스트를 작성한다**

기존 156행 fixture의 collision 두 행을 새 action으로 바꿔 다음을 검사한다.

```python
assert collision_merges_from_ledger(ledger) == {
    "mapping.disturb-drone.cloud-reskin-identity":
        "mapping.disturb-drone.drone-cloud-reskin-identity",
    "mapping.disturb-hedgehog.angry-shoot-block":
        "mapping.disturb-hedgehog.angry-shoot-bubble-removal",
}
assert not (
    set(collision_merges_from_ledger(ledger))
    & set(id_renames_from_ledger(ledger))
)
```

merge row는 existing target, `field_changes=[]`, `source_kind="DomainMapping"`만 허용하며 merge count가 1 또는 3이면 `canonical_repair_action_count_invalid`를 기대한다.

- [ ] **Step 2: RED를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_canonical_repair.py -k 'merge and ledger' -q`

Expected: FAIL because the action enum and map do not exist or existing target is rejected.

- [ ] **Step 3: decoder와 ledger validator를 최소 변경한다**

`_decode_decision()`에서 merge는 non-null `new_id`, 빈 `field_changes`를 요구한다. `validate_canonicalization_ledger()`의 target loop는 merge와 rename을 분기한다.

```python
if decision.action is CanonicalAction.COLLISION_MERGE_INTO_EXISTING:
    if decision.source_kind != "DomainMapping" or not existing.has(decision.new_id):
        _fail("decision_merge_target_invalid", decision.source_id)
    try:
        parse_id(decision.new_id, "DomainMapping")
    except IdGrammarError as exc:
        _fail("decision_merge_target_invalid", str(exc))
else:
    if existing.has(decision.new_id):
        _fail("decision_target_exists", decision.new_id)
```

모든 target은 여전히 unique해야 한다. merge target은 다른 decision `source_id`, 다른 merge target, rename target과 겹치면 `decision_merge_endpoint_overlap`로 중단한다. 전체 ledger가 먼저 구성된 뒤 `project_collision_merges()`를 호출해 kind/context/key/review/provenance/projection gate를 재사용한다.

- [ ] **Step 4: endpoint drift matrix를 추가한다**

target missing, existing but non-canonical target ID, target이 다른 decision source, kind/context/key/review_record mismatch, duplicate target, source SHA drift, provenance, ContextProjection source/survivor/referrer dependency를 각각 독립 테스트한다. error code는 `decision_merge_target_invalid`, `decision_merge_endpoint_overlap`, 또는 Task 1의 `CollisionMergeError.code`를 `CanonicalRepairError`로 옮긴 값 중 하나로 고정한다.

Run: `.venv/bin/python -m pytest tests/test_canonical_repair.py -k 'merge and ledger' -q`

Expected: PASS.

- [ ] **Step 5: 기존 ledger 회귀를 실행한다**

Run: `.venv/bin/python -m pytest tests/test_canonical_repair.py -k 'ledger or decision' -q`

Expected: PASS; non-merge existing target rejection and `collision_distinct_rename` behavior remain unchanged.

- [ ] **Step 6: 커밋한다**

```bash
git add src/project_brain/canonical_repair.py tests/test_canonical_repair.py
git diff --cached --check
git commit -m "feat(brain): validate canonical collision merge decisions"
```

---

### Task 3: Planner and Mutation Intent Validation

**Files:**

- Modify: `src/project_brain/canonical_repair.py`
- Modify: `src/project_brain/mutation.py`
- Modify: `tests/test_canonical_repair.py`
- Modify: `tests/test_mutation.py`

**Interfaces:**

- Consumes: `collision_merges_from_ledger()`, `project_collision_merges()`.
- Produces one `MutationRequest` with:

```text
delete_ids = field-repair sources union merge sources
renames = field-repair source -> new target only
objects = field-repair creates, merge survivor updates, changed referrer updates
canonical_repair_intents = five rename intents plus two merge intents
canonical_repair_reference_collapses = exact Task 1 ReferenceCollapse rows
```

- The merge intent uses the existing `CanonicalRepairIntent` fields with `reason_code="collision_merge_into_existing"` and empty `field_changes`.
- Add `MutationRequest.canonical_repair_reference_collapses: tuple[ReferenceCollapse, ...] = ()`. This request-only field is not added to `MutationManifest` or the journal. The planner supplies it, the mutation validator recomputes it from `project_collision_merges()`, and any mismatch is rejected before manifest construction.
- `_validate_canonical_repair_request()` returns one internal result instead of only an error:

```python
@dataclass(frozen=True)
class _CanonicalRepairValidation:
    error: MutationPlanResult | None
    comparison_by_id: dict[str, dict]
    suppressed_reference_fields: frozenset[tuple[str, str]]
```

For non-canonical operations the caller uses empty comparison/suppression values. For canonical repair, `comparison_by_id` is the final expected payload map after merge projection, field-repair reference rewrites, and approved field changes—not the merge-only intermediate map.

- [ ] **Step 1: planner shape RED 테스트를 작성한다**

Task 2 fixture에서 plan을 만들고 operation별 exact 집합을 검사한다.

```python
merge_sources = set(collision_merges_from_ledger(fixture.ledger))
merge_targets = set(collision_merges_from_ledger(fixture.ledger).values())
request = plan_canonical_repair(**fixture.plan_args).request

assert merge_sources <= set(request.delete_ids)
assert merge_sources.isdisjoint(request.renames)
assert merge_targets.isdisjoint(request.renames.values())
assert merge_targets <= {obj["id"] for obj in request.objects}
assert all(source not in {obj["id"] for obj in request.objects}
           for source in merge_sources)
```

두 bundle review의 source+target 배열은 source가 제거되고, drone DecisionRecord 두 개는 source-only 참조가 target으로 바뀌는지도 검사한다.

- [ ] **Step 2: RED를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_canonical_repair.py -k 'merge and plan' -q`

Expected: FAIL because planner still treats every repair pair as source-delete/new-create rename.

- [ ] **Step 3: planner를 rename과 merge로 나눈다**

`plan_canonical_repair()`에서 먼저 complete `existing_by_id`와 merge projection을 만든다. 그 logical store에 기존 field-repair replacement와 approved field change를 적용한다. request object는 최종 payload가 기존과 다른 survivor/referrer와 새 field-repair target만 담는다.

```python
repair_pairs = canonical_repair_renames_from_ledger(ledger)
merge_pairs = collision_merges_from_ledger(ledger)
merge_projection = project_collision_merges(existing_by_id, merge_pairs)
logical_by_id = merge_projection.after_by_id
```

precondition은 merge source, merge target, field-repair source, 바뀌는 기존 referrer를 모두 `_object_hash(existing_by_id[id])`로 묶는다. `id_renames` artifact field에는 `id_renames_from_ledger()` 결과만 유지한다.

- [ ] **Step 4: 승인된 merge와 승인 없는 merge를 분리하는 mutation RED 테스트를 쓴다**

`tests/test_mutation.py:932`의 기존 parameterized test를 둘로 나눈다.

```python
def test_canonical_repair_allows_explicit_existing_target_merge(tmp_path):
    request = _collision_merge_request(tmp_path)
    result = MutationService().plan(request.objects, request=request)
    assert result.ok is True


@pytest.mark.parametrize("case", ["unapproved_existing_target", "delete_only"])
def test_canonical_repair_rejects_unapproved_merge_or_delete_only(tmp_path, case):
    request = _unapproved_request(tmp_path, case)
    result = MutationService().plan(request.objects, request=request)
    assert result.ok is False
    assert result.manifest is None
```

`_collision_merge_request()`는 실제 request shape처럼 source와 target을 store에 쓰고, source는 `delete_ids`, survivor는 `objects`, merge pair는 intent에만 넣는다.

- [ ] **Step 5: RED를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_mutation.py -k 'canonical_repair and merge' -q`

Expected: FAIL because `_validate_canonical_repair_request()` requires every intent to equal an explicit rename.

- [ ] **Step 6: mutation validator를 reason별로 분리한다**

`_validate_canonical_repair_request()`가 intents를 다음처럼 나눈다.

```python
merge_intents = tuple(
    intent for intent in intents
    if intent.reason_code == "collision_merge_into_existing"
)
rename_intents = tuple(intent for intent in intents if intent not in merge_intents)
merge_pairs = {intent.source_id: intent.new_id for intent in merge_intents}
```

검사 계약:

- explicit `rename_pairs`는 rename intent와 exact equality.
- `delete_ids`는 rename source와 merge source의 exact 합집합.
- created IDs는 rename target의 exact 집합.
- merge source는 `input_by_id`에 없고 merge target은 `existing_by_id`와 `input_by_id` 양쪽에 있음.
- `project_collision_merges(existing_by_id, merge_pairs)`의 survivor/referrer payload와 request payload가 exact.
- request의 `canonical_repair_reference_collapses`가 recomputed projection과 dataclass-exact.
- merge와 rename이 같은 referrer를 바꿀 때 merge projection 뒤 field-repair replacements를 적용한 최종 payload를 비교.
- 그 밖의 기존 object update나 create는 `canonical_repair_payload_changed`.
- `collision_merge_into_existing` 외 unknown reason은 계속 `canonical_repair_reason_invalid`.

- [ ] **Step 7: tamper와 overlap 테스트를 통과시킨다**

survivor union 하나 제거, target-authoritative field 변경, referrer collapse 누락, merge source input 재등장, target create 위장, merge pair를 `renames`에도 추가, delete 하나 누락을 각각 거부한다.

Run: `.venv/bin/python -m pytest tests/test_mutation.py -k 'canonical_repair' -q`

Expected: PASS.

- [ ] **Step 8: grandfather 비교를 merge-aware로 바꾼다**

현재 `_canonical_repair_comparison_shape()`의 단순 `rewrite_object_refs()` 대신, canonical repair에서 merge pair가 있으면 Task 1 projection의 해당 logical object를 비교 shape로 사용한다. 배열 축약 뒤의 referrer가 기존 structured-ID 문제를 새 문제로 오인하지 않도록 다음 회귀를 추가한다.

```python
def test_canonical_merge_grandfather_shape_collapses_duplicate_logical_ref(tmp_path):
    request = _collision_merge_request(tmp_path, invalid_referrer=True)
    result = MutationService().plan(request.objects, request=request)
    assert result.ok is True
    assert {
        row["problem"] for row in result.manifest.grandfathered_problems_after
    } <= {
        row["problem"] for row in result.manifest.grandfathered_problems_before
    }
```

`_grandfathered_problems()`에 optional `comparison_by_id`를 전달해 before hash 계산을 logical merge 결과로 정규화하고, 같은 comparison map을 schema 직후 structured-ID early validation의 `_canonical_repair_objects_equivalent()`에도 전달한다. early validation과 grandfather hash가 서로 다른 normalization을 쓰면 안 된다.

```python
def _canonical_repair_objects_equivalent(
    before: Mapping[str, object],
    after: Mapping[str, object],
    replacements: Mapping[str, str],
    *,
    comparison_by_id: Mapping[str, Mapping[str, object]] | None = None,
) -> bool:
    object_id = before.get("id")
    if comparison_by_id is not None and isinstance(object_id, str):
        projected = comparison_by_id.get(object_id)
        if projected is not None:
            return dict(projected) == dict(after)
    return _canonical_repair_comparison_shape(before, replacements) == dict(after)
```

`_validate_canonical_repair_request()`가 `_CanonicalRepairValidation.comparison_by_id`로 final expected payload map을 caller에 돌려준다. 이 map은 Step 8 early ID validation과 grandfather calculation 양쪽에 exact하게 전달한다. invalid structured-ID referrer가 merge collapse와 field-repair reference rewrite를 함께 받아도 early validation을 통과하는 테스트를 추가한다.

- [ ] **Step 9: merge receipt가 지정한 list field만 가짜 pointer diff에서 제외한다**

`_reference_rewrites()`에 validated `suppressed_fields: frozenset[tuple[str, str]]`를 넘긴다. 값은 `request.canonical_repair_reference_collapses`에서 `(collapse.object_id, collapse.pointer)`만 뽑는다. 이 exact field 아래 pointer만 건너뛰고, 길이 차이 자체로 추측하지 않는다. scalar와 길이가 같은 list의 source→target은 계속 기록하며, 기존 mixed-review repair의 6→5 `target_object_ids` rewrite도 계속 남아야 한다.

```python
suppressed_fields = frozenset(
    (collapse.object_id, collapse.pointer)
    for collapse in request.canonical_repair_reference_collapses
)
```

이 값은 `_CanonicalRepairValidation.suppressed_reference_fields`로 manifest builder까지 전달하고 `_reference_rewrites(..., suppressed_fields=...)`에 사용한다. validator가 recomputed collapse와 request field의 exact equality를 확인했으므로 caller가 신뢰하는 suppression은 임의 입력이 아니다.

merge bundle 축약은 `reference_rewrites`에 없고 drone DecisionRecord 두 개의 source-only replacement는 exact pointer와 함께 남는 테스트를 추가한다. 별도 회귀에서 기존 mixed-review repair의 길이 감소 field가 억제되지 않고 기존 rewrite rows를 유지하는지 검사한다.

Run: `.venv/bin/python -m pytest tests/test_mutation.py tests/test_canonical_repair.py -q`

Expected: PASS.

- [ ] **Step 9b: trusted intermediate receipt가 merge source delete를 최소 범위로 인식하게 한다**

Task 3이 merge source를 `delete_ids`로 실제 삭제하므로, Task 5 전까지 기존 trusted
intermediate 성공 회귀를 깨뜨리지 않는 최소 연결부를 함께 넣는다. 이 단계는 Task 4의
`merge_receipt`를 소비하지 않는다.

- `_artifact_transition_receipts()`가 artifact `deletes`를 별도 exact map
  `{object_id: before_sha256}`으로 읽는다. 기존 update/rename 해석은 바꾸지 않는다.
- `id_renames_from_trusted_repair_receipt()`가
  `collision_merge_into_existing` decision이면 intermediate source가 없고 delete receipt의
  `before_sha256`이 ledger `source_sha256`과 같은지 검사한다. non-merge decision은 기존
  update/rename 검증을 유지한다.
- 기존 `test_trusted_intermediate_receipt_returns_only_pure_id_renames`를 RED로 사용하고,
  반환 rename에서 merge source가 빠지는지와 intermediate에 merge source가 남지 않는지를
  함께 단언한다.
- 이 최소 연결부가 직접 책임지는 변조 축 세 개만 Task 3에 둔다: delete row 누락,
  delete before SHA 변경, intermediate에 merge source 잔존.

Run: `.venv/bin/python -m pytest tests/test_canonical_repair.py -k 'intermediate' -q`

Expected: PASS. Task 5의 merge receipt 교차검증과 transaction recovery는 아직 구현하지 않는다.

- [ ] **Step 10: 커밋한다**

```bash
git add src/project_brain/canonical_repair.py src/project_brain/mutation.py \
  tests/test_canonical_repair.py tests/test_mutation.py
git diff --cached --check
git commit -m "feat(brain): plan canonical merges atomically"
```

---

### Task 4: Canonical Artifact Merge Receipt

**Files:**

- Modify: `src/project_brain/canonical_repair.py`
- Modify: `tests/test_canonical_repair.py`

**Interfaces:**

- Consumes: Task 1 `ReferenceCollapse`, Task 3 planner projection.
- Produces every `CanonicalRepairRow` with `merge_receipt`:

```python
@dataclass(frozen=True)
class CanonicalMergeReceipt:
    source_delete_before_sha256: str
    target_id: str
    target_before_sha256: str
    target_after_sha256: str
    reference_collapses: tuple[ReferenceCollapse, ...]


@dataclass(frozen=True)
class CanonicalRepairRow:
    # existing fields unchanged
    merge_receipt: CanonicalMergeReceipt | None
```

- Non-merge rows serialize `"merge_receipt": null`.
- Artifact version remains `canonical_repair_version: 1`; strict row shape and live replan bind the added row field before any real artifact exists.

- [ ] **Step 1: exact receipt RED 테스트를 작성한다**

```python
merge_rows = [row for row in plan.rows if row.merge_receipt is not None]
assert len(merge_rows) == 2
for row in merge_rows:
    receipt = row.merge_receipt
    assert receipt.target_id == row.new_id
    assert receipt.target_after_sha256 == row.canonical_payload_hash
    assert receipt.source_delete_before_sha256 == fixture.existing.source_sha256(row.source_id)
    assert receipt.target_before_sha256 == fixture.existing.source_sha256(row.new_id)
```

두 bundle collapse의 `before_ids`, `after_ids`, `removed_index`를 exact fixture 값으로 검사한다.

- [ ] **Step 2: RED를 확인한다**

Run: `.venv/bin/python -m pytest tests/test_canonical_repair.py -k 'merge and artifact' -q`

Expected: FAIL because `CanonicalRepairRow` has no `merge_receipt`.

- [ ] **Step 3: row receipt를 생성한다**

`plan_canonical_repair()`가 merge decision별로 source/target raw SHA와 projection collapse를 모아 `CanonicalMergeReceipt`를 만든다. 한 collapse는 그 referrer가 실제로 해당 merge source를 제거한 경우에만 해당 row에 들어간다. non-merge row에는 `None`을 명시한다.

- [ ] **Step 4: artifact parser의 strict row decoder를 추가한다**

`_parse_canonical_artifact()`에서 `rows`를 단순 list 여부만 보지 말고 exact row keys, SHA, field change, rewrite, merge receipt를 검증한다. merge receipt exact keys는 다음뿐이다.

```python
{
    "source_delete_before_sha256",
    "target_id",
    "target_before_sha256",
    "target_after_sha256",
    "reference_collapses",
}
```

collapse는 exact keys `object_id`, `pointer`, `before_ids`, `after_ids`, `removed_index`를 요구하고 다음 식을 검사한다.

```python
before_ids[removed_index] == row["source_id"]
after_ids == before_ids[:removed_index] + before_ids[removed_index + 1:]
before_ids.count(row["source_id"]) == 1
before_ids.count(row["new_id"]) == 1
after_ids.count(row["new_id"]) == 1
```

Task 4가 merge decision 두 개를 `rows`에 처음 추가하므로 trusted intermediate validator의
row source coverage도 이 단계에서 `set(repair_renames) | set(collision_merges_from_ledger(ledger))`
로 넓힌다. merge row가 생긴 뒤에도 trusted intermediate 성공 회귀가 green인지 확인하는
테스트를 함께 둔다. Task 3 시점에는 merge row가 아직 없으므로 이 확장은 앞당기지 않는다.

- [ ] **Step 5: tamper matrix를 추가한다**

source delete SHA, target ID, target before SHA, target after SHA, row canonical hash, collapse object/pointer/index/before/after, non-merge non-null receipt, merge null receipt를 한 축씩 바꿔 `manifest_invalid` 또는 `manifest_revalidation_failed`를 기대한다.

Run: `.venv/bin/python -m pytest tests/test_canonical_repair.py -k 'artifact or manifest' -q`

Expected: PASS.

- [ ] **Step 6: live replan과 apply 통합을 확인한다**

artifact raw bytes가 계획과 exact일 때만 apply되고, merge survivor와 referrer를 하나라도 바꾼 뒤 같은 artifact를 적용하면 `manifest_revalidation_failed` 또는 snapshot drift로 중단하는 테스트를 실행한다.

Run: `.venv/bin/python -m pytest tests/test_canonical_repair.py -k 'apply or revalidation' -q`

Expected: PASS.

Task 4가 canonical artifact row 수를 5에서 7로 바꾸므로 CLI plan/apply 출력의
`row_count` 기대값 두 곳도 7로 갱신한다. `tests/test_cli.py` 전체를 실행해 앞선 plan 단언이
가리고 있던 apply 경로까지 확인하고, 커밋 전 전체 엔진 회귀를 한 번 실행한다.

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py -q
.venv/bin/python -m pytest -q
```

Expected: PASS.

- [ ] **Step 7: 커밋한다**

```bash
git add src/project_brain/canonical_repair.py tests/test_canonical_repair.py \
  tests/test_cli.py
git diff --cached --check
git commit -m "feat(brain): receipt canonical merge collapses"
```

---

### Task 5: Intermediate Receipt and Transaction Recovery

**Files:**

- Modify: `src/project_brain/canonical_repair.py`
- Modify: `tests/test_canonical_repair.py`
- Modify: `tests/test_corpus_io.py`

**Interfaces:**

- Consumes: canonical artifact `deletes`, `updates`, `rows[].merge_receipt`.
- Produces: `id_renames_from_trusted_repair_receipt()` returns only remaining pure-ID map; merge sources are never returned.

- [ ] **Step 1: Task 3의 delete-aware 최소 연결부가 green인지 확인한다**

Task 3에서 이미 추가한 trusted intermediate 성공 회귀를 다시 실행해 pure-ID rename만
반환되고 merge source는 intermediate에 없음을 확인한다.

```python
renames = id_renames_from_trusted_repair_receipt(**args)
assert renames == id_renames_from_ledger(fixture.ledger)
assert not set(collision_merges_from_ledger(fixture.ledger)) & set(renames)
assert all(not intermediate.has(source)
           for source in collision_merges_from_ledger(fixture.ledger))
```

- [ ] **Step 2: merge receipt 교차검증 RED를 작성하고 확인한다**

실제로 바뀌는 survivor의 update receipt 누락 또는 before/after SHA 변경처럼 Task 3의 최소
연결부가 책임지지 않는 한 축을 먼저 테스트로 추가한다.

Run: `.venv/bin/python -m pytest tests/test_canonical_repair.py -k 'intermediate and merge_survivor' -q`

Expected: FAIL because the trusted intermediate validator does not yet bind survivor update receipt,
row payload hash, and Task 4 `merge_receipt` together.

- [ ] **Step 3: transition receipt parser와 merge receipt 검증을 완전한 형태로 만든다**

Task 3의 deletes 최소 map을 유지하면서 `_artifact_transition_receipts()`가 `updates`,
`renames`, `deletes`를 서로 분리한 strict result로 반환하게 한다.

```python
@dataclass(frozen=True)
class _ArtifactTransitions:
    updates: dict[str, tuple[str, str]]
    renames: dict[str, tuple[str, str, str]]
    deletes: dict[str, str]
```

merge decision은 아래를 모두 검증한다.

- intermediate source absent.
- delete receipt before SHA equals ledger source SHA and merge receipt source SHA.
- merge receipt target before/after SHA가 다르면 survivor update가 정확히 하나 있어야 하고,
  update before/after SHA가 merge receipt와 같아야 한다.
- merge receipt target before/after SHA가 같으면 survivor update는 없어야 한다.
- live survivor SHA는 모든 경우 row payload hash, target after SHA와 같아야 하며, update가
  있는 경우 update after SHA와도 같아야 한다.
- collapse referrer live list equals `after_ids` and source is absent.
- row의 source/new ID/reason과 ledger decision exact.

non-merge decision은 기존 rename/update 검증을 유지한다.

- [ ] **Step 4: trusted receipt tamper matrix를 추가한다**

다음 축을 하나씩 바꿔 모두 fail-closed인지 검사한다.

```text
survivor update missing while target before != after
survivor update present while target before == after
survivor before SHA
survivor after SHA
row canonical payload hash
merge receipt target ID
collapse before IDs
collapse after IDs
collapse removed index
live survivor bytes
live referrer list
```

no-op survivor의 정상 artifact에 update 행이 없고 trusted intermediate 검증이 통과하는
양성 회귀를 둔다. before==after인 위조 update 행을 추가하면
`intermediate_source_receipt_mismatch`로 중단해야 한다.

delete row 누락, delete before SHA 변경, intermediate source 잔존 세 축은 Task 3 소유다.
여기서는 Task 4 `merge_receipt`와 live survivor/referrer를 함께 묶는 나머지 축만 다룬다.

Run: `.venv/bin/python -m pytest tests/test_canonical_repair.py -k 'intermediate' -q`

Expected: PASS with exact `manifest_invalid`, `intermediate_receipt_mismatch`, or `intermediate_source_receipt_mismatch` codes asserted per axis.

- [ ] **Step 5: transaction fault fixture를 만든다**

`tests/test_corpus_io.py`에 `test_canonical_merge_rolls_back_every_transaction_failure_point`라는 exact node ID로 새 parameterized test를 만든다. source delete, survivor update, collapse referrer update가 모두 있는 merge request를 쓰고, 매 failure point마다 apply 직후와 recovery 직후 파일 SHA 집합을 기록한다.

```python
assert observed_state in {before_state, after_state}
assert not (
    source_missing
    and survivor_before
    and referrer_before
)
```

- [ ] **Step 6: 모든 rollback/recovery 회귀를 실행한다**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_corpus_io.py::test_canonical_merge_rolls_back_every_transaction_failure_point -q
```

Expected: PASS at every published journal/replacement failure point; recovery ends in whole-before or whole-after only.

- [ ] **Step 7: canonical repair 통합 회귀를 실행한다**

Run: `.venv/bin/python -m pytest tests/test_canonical_merge.py tests/test_canonical_repair.py tests/test_mutation.py tests/test_corpus_io.py -q`

Expected: PASS.

- [ ] **Step 8: 커밋한다**

```bash
git add src/project_brain/canonical_repair.py tests/test_canonical_repair.py \
  tests/test_corpus_io.py
git diff --cached --check
git commit -m "fix(brain): verify merge delete receipts and recovery"
```

---

### Task 6: Engine Documentation, Full Regression, and Integration Review

**Files:**

- Modify: `docs/design-canonical.md`
- Modify: `ROADMAP.md`
- Test: all `tests/`
- Test: `src/project_brain/templates/ingest/scripts/test_*.py`

**Interfaces:**

- Consumes: Tasks 1–5 reviewed commits.
- Produces: clean engine worktree at one reviewed `ENGINE_SHA`, with complete test receipts and no BB2 mutation. `ENGINE_BASE_SHA` is the commit recorded immediately before Task 1 and is used for every whole-implementation diff.

- [ ] **Step 1: canonical design 문서를 갱신한다**

`docs/design-canonical.md`의 canonical repair section에 다음 계약을 실제 symbol 이름과 함께 적는다.

```text
collision_merge_into_existing
project_collision_merges()
source delete + existing target update
target-authoritative semantic fields
target-first stable evidence union
conservative history_coverage
provenance and ContextProjection fail-closed gates
CanonicalRepairRow.merge_receipt
```

`reference_rewrites`와 `reference_collapses`의 역할 차이, intermediate receipt가 delete/update/row hash를 함께 검증한다는 점을 명시한다.

- [ ] **Step 2: ROADMAP 상태를 정확히 갱신한다**

엔진 기능 지원은 완료로 기록하되, 실코퍼스 원장 승인과 Task 9 apply는 아직 미완료라고 분리한다. “검색 품질 회귀 완료”나 “실코퍼스 migration 완료”라고 쓰지 않는다.

- [ ] **Step 3: 문서와 symbol을 대조한다**

Run:

```bash
rg -n 'collision_merge_into_existing|project_collision_merges|merge_receipt' \
  src/project_brain tests docs/design-canonical.md ROADMAP.md
```

Expected: production symbols, tests, docs가 모두 연결되고 미완성 표식이 없다.

- [ ] **Step 4: 전체 엔진 합성 회귀를 실행한다**

Run: `.venv/bin/python -m pytest -q`

Expected: all tests PASS. 테스트 수와 elapsed를 task report에 기록한다.

- [ ] **Step 5: 설치되는 ingest runtime unittest를 실행한다**

Run:

```bash
.venv/bin/python -m unittest discover \
  -s src/project_brain/templates/ingest/scripts -p 'test_*.py'
```

Expected: `OK`. 테스트 수를 task report에 기록한다.

- [ ] **Step 6: engine diff와 작업트리를 점검한다**

Run:

```bash
git diff --check
git status --short
git diff --stat "$ENGINE_BASE_SHA"..HEAD
```

Expected: docs 두 파일만 아직 uncommitted이며, BB2/source checkout의 기존 dirt는 건드리지 않았다.

- [ ] **Step 7: 문서 커밋을 만든다**

```bash
git add docs/design-canonical.md ROADMAP.md
git diff --cached --check
git commit -m "docs(brain): document canonical collision merge"
```

- [ ] **Step 8: 독립 통합 리뷰를 받는다**

reviewer에게 design spec, 이 plan, exact `$ENGINE_BASE_SHA..HEAD` review package, 전체 테스트 영수증을 제공한다. 판정은 `PASS` 또는 `CHANGES_REQUIRED`와 Blocker/Major/Minor 수를 요구한다. 다음 항목을 별도로 확인하게 한다.

```text
No source evidence loss
No fabricated pointer rewrite
No unapproved existing-target merge
No delete-only bypass
No provenance or ContextProjection rewrite
Whole-before/whole-after recovery
Merge source excluded from later pure ID map
No MutationManifest or journal top-level schema drift
```

CHANGES_REQUIRED이면 같은 Task의 fresh implementer가 RED→GREEN으로 수정하고 새 diff를 같은 reviewer에게 재제출한다. 최대 다섯 번 뒤에도 Major가 남으면 구현을 멈추고 Orca의 Claude Opus 5 high와 blocker를 협의한다.

- [ ] **Step 9: 최종 engine SHA와 clean receipt를 고정한다**

Run:

```bash
git status --porcelain=v1
git rev-parse HEAD
git diff --check HEAD~1..HEAD
```

Expected: status empty. 이 SHA를 `ENGINE_SHA`로 이후 모든 snapshot/Phase A/workbook/ledger에 사용한다.

---

### Task 7: Rebind Task 7, Build the 156-row Ledger, and Stop at Approval Gate 1

**Files:**

- Archive without deletion: prior pre-snapshot, Phase A JSON 3개, workbook, Task 7/8 receipts.
- Regenerate in BB2: `brain/recovery/2026-07-28/id-migration/phase-a-classification.json`
- Regenerate in BB2: the other two exact Phase A JSON outputs produced by `scan_task17.py`.
- Regenerate outside Git: `/private/tmp/project-brain-task17-receipts-ba05PLlb/decision-review.json`
- Create in BB2: `brain/recovery/2026-07-28/id-migration/canonicalization-decisions.json`
- Update ignored report: `.superpowers/sdd/2026-07-31-task17-canonical-id-recovery/task-7-report.md`
- Update ignored report: `.superpowers/sdd/2026-07-31-task17-canonical-id-recovery/task-8-report.md`
- Does not modify: BB2 objects, eval, index, stale, journals, `.git/info/exclude`.

**Interfaces:**

- Consumes: reviewed clean `ENGINE_SHA`, reviewed scanner/test bytes, exact pre-Task17 receipts, prior Task 8 semantic decisions for 154 rows, the two user-approved merge decisions.
- Produces: one strict 156-row ledger with exact action counts:

```text
id_only_rename = 137
target_derived_review_rename = 11
reference_only = 1
projected_field_repair = 4
review_shape_repair = 1
collision_merge_into_existing = 2
collision_distinct_rename = 0
total = 156
```

- [ ] **Step 1: preflight와 baseline을 read-only로 다시 고정한다**

다음을 exact 비교한다.

```text
Engine status empty and HEAD == ENGINE_SHA
BB2 HEAD == 53671bce5e94edf38a7afa11706963581065fb0f
BB2 dirt 32 records / 2209 bytes / staged 0
Source checkout dirt 17 records / 751 bytes / staged 0
Corpus fingerprint 437a32931da4a830a4ca45c6f24efe9ad534536a4c74fe2df794bbb50016ff90
eval SHA cb45132eab11ea6f615f9108e3cbb3b54474a14cf6e1d39dc5ffd56741858d39
index SHA 51047f2843b885f21dd328579494cb67932728f2ef58377a24286b398a1abd60
stale SHA 8061ed9ba99d2f574bfc6e90bf8c042b300510d258dff78f23c8018646ead594
```

하나라도 다르면 regeneration을 시작하지 않고 변경된 축을 보고한다. Terminal 권한은 검사 대상에서 제외한다.

- [ ] **Step 2: 이전 산출물을 보존형 archive한다**

archive root는 receipts 아래 새 `task8a-rebind-<ENGINE_SHA 앞 12자>` 디렉터리다. `mkdir`은 destination이 이미 있으면 실패해야 하며 `-p`를 쓰지 않는다. broad glob이나 overwrite를 쓰지 않고, exact path마다 source path, mode, size, SHA-256을 manifest에 먼저 기록한 뒤 rename으로 옮긴다. archive manifest 자체도 `O_CREAT|O_EXCL|O_NOFOLLOW`로 새로 쓴다.

```text
/Users/al03040455/Desktop/bb2_client/.snapshots/2026-07-31/task17-pre-canonical/task17-pre-canonical
/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-07-28/id-migration/phase-a-classification.json
/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-07-28/id-migration/phase-a-measurement.json
/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-07-28/id-migration/phase-a-feasibility.json
/private/tmp/project-brain-task17-receipts-ba05PLlb/decision-review.json
/private/tmp/project-brain-task17-receipts-ba05PLlb/phase-a-run.json
/private/tmp/project-brain-task17-receipts-ba05PLlb/pre-task17-create.json
/private/tmp/project-brain-task17-receipts-ba05PLlb/task7-recovery-files.json
/private/tmp/project-brain-task17-receipts-ba05PLlb/task8-blocked-files.json
```

위 목록이 현재 stale engine/workbook binding allowlist다. 하나라도 예상과 다르면 임의로 넓혀 찾지 말고 현재 receipt manifest와 Task 7/8 report를 대조해 중단한다. archive 뒤 각 destination의 SHA와 manifest가 다시 맞아야 하며, 원본 path가 다시 생성되기 전까지 모두 absent인지 확인한다.

아래 command의 인자 목록을 그대로 사용한다. embedded script는 regular file/directory만 허용하고 symlink·special file을 거부한다. 모든 file bytes SHA를 담은 manifest를 archive root에 exclusive-create한 뒤 exact source를 하나씩 rename하고 source/destination parent를 fsync한다. `os.rename()`이 `EXDEV`로 실패하면 copy/delete로 우회하지 않고 중단한다.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2=/Users/al03040455/Desktop/bb2_client
PHASE_A_ROOT="$BB2/brain/recovery/2026-07-28/id-migration"
TASK17_RECEIPTS=/private/tmp/project-brain-task17-receipts-ba05PLlb
ENGINE_SHA=$(git -C "$ENGINE" rev-parse HEAD)
ARCHIVE_ROOT="$TASK17_RECEIPTS/task8a-rebind-${ENGINE_SHA:0:12}"
test ! -e "$ARCHIVE_ROOT"
mkdir "$ARCHIVE_ROOT"
"$ENGINE/.venv/bin/python" - "$ARCHIVE_ROOT" \
  "$BB2/.snapshots/2026-07-31/task17-pre-canonical/task17-pre-canonical" \
  "$PHASE_A_ROOT/phase-a-classification.json" \
  "$PHASE_A_ROOT/phase-a-measurement.json" \
  "$PHASE_A_ROOT/phase-a-feasibility.json" \
  "$TASK17_RECEIPTS/decision-review.json" \
  "$TASK17_RECEIPTS/phase-a-run.json" \
  "$TASK17_RECEIPTS/pre-task17-create.json" \
  "$TASK17_RECEIPTS/task7-recovery-files.json" \
  "$TASK17_RECEIPTS/task8-blocked-files.json" <<'PY'
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

archive = Path(sys.argv[1])
sources = tuple(Path(value) for value in sys.argv[2:])

def file_row(path: Path, relative: str) -> dict[str, object]:
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise RuntimeError(f"not a regular file: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        digest = hashlib.sha256()
        size = 0
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(fd)
        binding = (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_size)
        if binding != (after.st_dev, after.st_ino, after.st_mode, after.st_size):
            raise RuntimeError(f"file changed while hashing: {path}")
        return {"path": relative, "mode": stat.S_IMODE(opened.st_mode),
                "size": size, "sha256": digest.hexdigest()}
    finally:
        os.close(fd)

rows = []
for source in sources:
    current = source.lstat()
    if stat.S_ISREG(current.st_mode):
        files = [source]
    elif stat.S_ISDIR(current.st_mode):
        files = []
        for child in sorted(source.rglob("*")):
            mode = child.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise RuntimeError(f"unsafe archive entry: {child}")
            if stat.S_ISREG(mode):
                files.append(child)
    else:
        raise RuntimeError(f"unsafe archive source: {source}")
    rows.append({
        "source": str(source),
        "files": [file_row(path, path.relative_to(source).as_posix()) for path in files],
    })

payload = (json.dumps({"version": 1, "sources": rows}, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":")) + "\n").encode()
manifest_fd = os.open(archive / "archive-manifest.json",
                      os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
try:
    view = memoryview(payload)
    while view:
        written = os.write(manifest_fd, view)
        if written <= 0:
            raise OSError("archive manifest write made no progress")
        view = view[written:]
    os.fsync(manifest_fd)
finally:
    os.close(manifest_fd)

for source in sources:
    destination = archive / source.name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    os.rename(source, destination)
    for parent in (source.parent, archive):
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)

for expected in rows:
    source = Path(expected["source"])
    destination = archive / source.name
    if source.exists() or source.is_symlink():
        raise RuntimeError(f"archive source still exists: {source}")
    if destination.is_file():
        actual = [file_row(destination, ".")]
    else:
        actual = [
            file_row(path, path.relative_to(destination).as_posix())
            for path in sorted(destination.rglob("*"))
            if path.is_file() and not path.is_symlink()
        ]
    if actual != expected["files"]:
        raise RuntimeError(f"archive receipt mismatch: {destination}")
PY
```

- [ ] **Step 3: scanner 회귀와 exact-path pre-snapshot을 새 ENGINE_SHA로 만든다**

Run scanner tests:

```bash
PYTHONDONTWRITEBYTECODE=1 \
  /Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery/.venv/bin/python \
  -m pytest \
  /Users/al03040455/Desktop/bb2_client/brain/recovery/2026-07-28/id-migration/test_scan_task17.py -q
```

Expected: 31/31 PASS and no `__pycache__` under live recovery.

Create and verify the same logical pre-snapshot with the exact commands below.

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2=/Users/al03040455/Desktop/bb2_client
TASK17_RECEIPTS=/private/tmp/project-brain-task17-receipts-ba05PLlb
PRE_TASK17_OUT="$BB2/.snapshots/2026-07-31/task17-pre-canonical"
PRE_TASK17_ID=task17-pre-canonical
PRE_CREATE_RECEIPT="$TASK17_RECEIPTS/pre-task17-create.json"
test ! -e "$PRE_CREATE_RECEIPT"
set -o noclobber
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot create \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --output-root "$PRE_TASK17_OUT" \
  --snapshot-id "$PRE_TASK17_ID" \
  > "$PRE_CREATE_RECEIPT"
PRE_TASK17_SHA=$(
  "$ENGINE/.venv/bin/python" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["manifest_sha256"])' \
  "$PRE_CREATE_RECEIPT"
)
PRE_TASK17_ROOT="$PRE_TASK17_OUT/$PRE_TASK17_ID"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" -m project_brain.cli snapshot verify \
  --snapshot-root "$PRE_TASK17_ROOT" \
  --expected-manifest-sha256 "$PRE_TASK17_SHA"
```

Expected: 11,134 files, repo HEAD and new engine HEAD exact, object/eval/index/stale inventory missing/extra/changed 0. Record the new manifest SHA; do not assume it equals the old `5e27e8cbaf27bf33f4ad19ad7e6a0f54e1f891cb63180b3353f8167d57dc9216` because engine binding changed.

- [ ] **Step 4: Phase A 세 파일을 새 ENGINE_SHA로 재생성한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2=/Users/al03040455/Desktop/bb2_client
PHASE_A_ROOT="$BB2/brain/recovery/2026-07-28/id-migration"
TASK17_RECEIPTS=/private/tmp/project-brain-task17-receipts-ba05PLlb
ENGINE_SHA=$(git -C "$ENGINE" rev-parse HEAD)

PHASE_A_RECEIPT="$TASK17_RECEIPTS/phase-a-run.json"
test ! -e "$PHASE_A_RECEIPT"
set -o noclobber
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" "$PHASE_A_ROOT/scan_task17.py" \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --engine-sha "$ENGINE_SHA" \
  --output-root "$PHASE_A_ROOT" \
  > "$PHASE_A_RECEIPT"
```

Expected semantic projection:

```text
store objects 10,943
invalid objects/problems 155/158
classification rows 156
safe ID-only self renames 31
safe closure invalid/problems 125/128
human-ID decisions 109
mapping repairs 4
collisions 2
mixed review 1
```

각 새 파일은 new engine SHA, same BB2 HEAD, same corpus/eval/stale binding을 가져야 한다.

- [ ] **Step 5: review workbook을 새 binding으로 재생성한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2=/Users/al03040455/Desktop/bb2_client
PHASE_A_ROOT="$BB2/brain/recovery/2026-07-28/id-migration"
TASK17_RECEIPTS=/private/tmp/project-brain-task17-receipts-ba05PLlb
ENGINE_SHA=$(git -C "$ENGINE" rev-parse HEAD)
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" "$PHASE_A_ROOT/scan_task17.py" \
  --brain-root "$BB2/brain" \
  --repo-root "$BB2" \
  --engine-root "$ENGINE" \
  --engine-sha "$ENGINE_SHA" \
  --review-workbook "$TASK17_RECEIPTS/decision-review.json"
```

Expected: regular file, 156 rows, Phase A raw bytes exact, collision target evidence 2/2, EvidenceRef raw manifest 16/16, no candidate ID synthesis by scanner.

새 snapshot manifest, scanner/test bytes, Phase A 세 파일, workbook의 exact path/mode/size/SHA와 engine/repo/corpus binding을 새 `$TASK17_RECEIPTS/task7-recovery-files.json`에 `O_EXCL|O_NOFOLLOW`로 기록한다. archive된 stale receipt는 재사용하지 않는다.

- [ ] **Step 6: 154개 기존 의미 결정을 새 workbook pointer로 다시 묶는다**

Task 8 report의 old→new와 field diff를 source ID로 join한다. 행 번호를 그대로 복사하지 말고 새 workbook에서 source ID를 찾아 pointer를 재계산한다. 각 source SHA/new target/field diff를 current source와 다시 비교한다.

```python
assert set(decision_by_source) == set(classification_by_source)
assert len(decision_by_source) == 156
assert all(
    decision["source_sha256"] == classification_by_source[source]["source_sha256"]
    for source, decision in decision_by_source.items()
)
```

- [ ] **Step 7: collision 두 행을 exact merge action으로 기록한다**

Drone:

```json
{
  "source_id": "mapping.disturb-drone.cloud-reskin-identity",
  "source_kind": "DomainMapping",
  "action": "collision_merge_into_existing",
  "new_id": "mapping.disturb-drone.drone-cloud-reskin-identity",
  "field_changes": []
}
```

Hedgehog:

```json
{
  "source_id": "mapping.disturb-hedgehog.angry-shoot-block",
  "source_kind": "DomainMapping",
  "action": "collision_merge_into_existing",
  "new_id": "mapping.disturb-hedgehog.angry-shoot-bubble-removal",
  "field_changes": []
}
```

각 row의 `source_sha256`는 새 classification에서 exact 복사하고, `decision_reason`에는 existing target survivor, target semantic text 유지, source-only evidence union, 보수적 caveat 결과를 적는다. `decision_evidence`에는 새 workbook source pointer와 `collision_target` pointer를 모두 넣는다.

- [ ] **Step 8: canonical JSON ledger를 anchored exclusive writer로 쓴다**

top-level exact keys와 row exact keys는 기존 contract를 유지한다. `scan_task17._canonical_json_bytes(ledger)`로 한 번만 직렬화하고, 같은 모듈의 `_open_output_parent(..., require_git_outside=False)`와 `_exclusive_write_at(..., require_git_outside=False)`를 호출한다. 이렇게 `sort_keys=True`, `ensure_ascii=False`, compact separators, trailing newline, parent FD binding, `O_EXCL|O_NOFOLLOW`, exact-inode cleanup을 기존 reviewed writer와 공유한다. destination이 이미 있으면 덮어쓰지 않고 중단한다.

```python
parent_fd, parent_binding = scan_task17._open_output_parent(
    decisions_path.parent,
    require_git_outside=False,
)
try:
    decisions_sha, _ = scan_task17._exclusive_write_at(
        parent_fd,
        decisions_path.parent,
        decisions_path.name,
        scan_task17._canonical_json_bytes(ledger_payload),
        parent_binding,
        require_git_outside=False,
    )
finally:
    os.close(parent_fd)
```

Destination:

```text
/Users/al03040455/Desktop/bb2_client/brain/recovery/2026-07-28/id-migration/canonicalization-decisions.json
```

- [ ] **Step 9: strict parser와 read-only canonical plan을 실행한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2=/Users/al03040455/Desktop/bb2_client
PHASE_A_ROOT="$BB2/brain/recovery/2026-07-28/id-migration"
TASK17_RECEIPTS=/private/tmp/project-brain-task17-receipts-ba05PLlb
ENGINE_SHA=$(git -C "$ENGINE" rev-parse HEAD)
PRE_TASK17_ROOT="$BB2/.snapshots/2026-07-31/task17-pre-canonical/task17-pre-canonical"
PRE_CREATE_RECEIPT="$TASK17_RECEIPTS/pre-task17-create.json"
PRE_TASK17_SHA=$(
  "$ENGINE/.venv/bin/python" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["manifest_sha256"])' \
  "$PRE_CREATE_RECEIPT"
)
DECISIONS="$PHASE_A_ROOT/canonicalization-decisions.json"
CLASSIFICATION="$PHASE_A_ROOT/phase-a-classification.json"
DECISIONS_SHA=$(env LC_ALL=C LANG=C openssl dgst -sha256 "$DECISIONS" | awk '{print $2}')
CLASSIFICATION_SHA=$(env LC_ALL=C LANG=C openssl dgst -sha256 "$CLASSIFICATION" | awk '{print $2}')

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$ENGINE/src" \
  "$ENGINE/.venv/bin/python" - "$DECISIONS" "$CLASSIFICATION" \
  "$CLASSIFICATION_SHA" "$BB2/brain" "$ENGINE_SHA" \
  53671bce5e94edf38a7afa11706963581065fb0f \
  "$PRE_TASK17_ROOT" "$PRE_TASK17_SHA" "$ENGINE" "$BB2" <<'PY'
from pathlib import Path
from project_brain.canonical_repair import (
    collision_merges_from_ledger,
    id_renames_from_ledger,
    parse_canonicalization_ledger,
    plan_canonical_repair,
)
from project_brain.snapshot import verify_snapshot
from project_brain.store import BrainStore
import sys

(
    decisions,
    classification,
    classification_sha,
    brain,
    engine_sha,
    repo_head,
    snapshot_root,
    snapshot_sha,
    engine_root,
    repo_root,
) = sys.argv[1:]
store = BrainStore.load(Path(brain))
ledger = parse_canonicalization_ledger(
    Path(decisions).read_bytes(),
    classification_bytes=Path(classification).read_bytes(),
    expected_classification_sha256=classification_sha,
    existing=store,
    engine_sha=engine_sha,
    repo_head=repo_head,
)
snapshot = verify_snapshot(
    Path(snapshot_root),
    expected_manifest_sha256=snapshot_sha,
)
plan = plan_canonical_repair(
    existing=store,
    brain_root=Path(brain),
    repo_root=Path(repo_root),
    engine_root=Path(engine_root),
    engine_sha=engine_sha,
    ledger=ledger,
    snapshot=snapshot,
)
assert len(ledger.decisions) == 156
assert len(collision_merges_from_ledger(ledger)) == 2
assert not set(collision_merges_from_ledger(ledger)) & set(id_renames_from_ledger(ledger))
assert len(id_renames_from_ledger(ledger)) == 148
assert len(plan.request.renames) == 5
assert plan.mutation_plan.ok and plan.mutation_plan.manifest is not None
print(ledger.sha256, snapshot.manifest_sha256, plan.mutation_plan.manifest.transaction_id)
PY
```

이 command는 `verify_snapshot()`과 `plan_canonical_repair()`까지만 호출하고 apply는 호출하지 않는다. Expected: repair rename 5, merge 2, later pure ID map 148, unresolved 0, dangling 0, target collision 0, object/eval/index/stale byte changes 0.

- [ ] **Step 10: BB2 실코퍼스 회귀를 read-only로 실행한다**

```bash
ENGINE=/Users/al03040455/Downloads/codes/project-brain/.worktrees/brain-ingest-recovery
BB2=/Users/al03040455/Desktop/bb2_client
PYTHONPATH="$ENGINE/src" "$ENGINE/.venv/bin/python" \
  -m unittest discover -s "$BB2/brain/checks" -p 'test_*.py'
```

Expected: PASS. 이 단계는 색인 입력이나 embedding 계약을 바꾸지 않으므로 `index rebuild`는 실행하지 않는다. 기존 DB로 eval을 실행할 수 있으면 exact 15/15를 확인하되, 이 plan에서 실모델 rebuild는 하지 않는다.

- [ ] **Step 11: 독립 ledger review를 받는다**

reviewer에게 exact ledger/workbook/classification bytes의 SHA, 두 merge source/target raw bytes, read-only plan report, preflight receipts를 제공한다. reviewer는 다음을 독립 계산한다.

```text
156 source coverage and source SHA exact
action counts 137/11/1/4/1/2
109 human IDs and 31 safe closure targets canonical and collision-free
four mapping field changes exact
mixed review diff exact
two merge endpoint and payload policy exact
11 dependent reviews and three eval pointers closed
no object/eval/index/stale/journal mutation
BB2/source dirt and staged 0 unchanged
```

판정이 `CHANGES_REQUIRED`이면 ledger를 보존형 archive한 뒤 새 bytes를 만들고 Step 9부터 다시 검증한다. 이전 사용자 승인은 없으므로 재승인 문제는 아직 없다.

PASS 뒤 exact ledger, classification, workbook, snapshot, engine/BB2 SHA와 invariance receipt를 `$TASK17_RECEIPTS/task8-ledger-files.json`에 exclusive-create한다. 이 receipt SHA도 Task 8 report와 사용자 승인 자료에 넣는다.

- [ ] **Step 12: 사용자 승인 게이트 1 자료를 제시하고 멈춘다**

최종 답변에 다음을 제시한다.

```text
exact ledger path, byte size, SHA-256
classification SHA-256
engine SHA and BB2 HEAD
action/kind/context counts
109 human old -> new mapping report path
four mapping field diffs
two merge survivor payload diffs and collapse receipts expected by plan
mixed review diff
11 dependent ReviewRecord changes and three eval pointer closure
snapshot manifest SHA and file count
full engine/runtime/BB2 check results
BB2/source dirt and object/eval/index/stale invariance receipts
```

사용자에게 exact ledger bytes 승인을 명시적으로 요청한다. 이 답변에서 Task 9를 시작하거나 artifact를 적용하지 않는다. ledger bytes가 이후 한 바이트라도 바뀌면 새 SHA로 다시 승인받는다.

---

## Controller Execution Rules

- Task 1 implementer dispatch 전에 `ENGINE_BASE_SHA=$(git rev-parse HEAD)`를 이 plan의 progress ledger에 기록하고, task/final review package는 항상 이 base 또는 각 task에서 기록한 exact base를 사용한다.
- Task마다 fresh implementer 한 명과 fresh reviewer 한 명을 쓴다.
- implementer는 task brief만 받고, production code 전에 RED output을 report에 남긴다.
- reviewer는 design spec, task brief, implementer report, base..head diff를 독립 검토한다.
- controller는 구현 코드를 직접 수정하지 않고 task dispatch, receipts, review, progress ledger만 관리한다.
- 한 task의 review가 PASS되기 전에는 다음 task를 시작하지 않는다.
- 같은 blocker가 두 번 반복되거나 architecture 선택이 다시 필요하면 Orca orchestration으로 Claude Opus 5 high task를 만들고 `worker_done`까지 기다린 뒤 결과를 반영한다.
- 사용자 승인 게이트 1은 Task 7 Step 12에서만 열고, 명시적 승인 전에는 계획 실행을 종료한다.

## Plan Self-Review Checklist

- [ ] Design spec의 목표, 비목표, ledger, payload, caveat, unknown-field, reference collapse, receipt, planner, mutation, grandfather, intermediate, recovery, rebind, approval gate가 각각 Task 1–7에 대응한다.
- [ ] `collision_merges_from_ledger()`와 `project_collision_merges()` 이름이 모든 task에서 같다.
- [ ] Merge count는 2, field-repair rename count는 5, later pure ID count는 148, ledger total은 156으로 서로 맞는다.
- [ ] `request.renames`에 merge가 없고 `id_renames_from_ledger()`에도 merge가 없다.
- [ ] BB2 object/eval/index/stale write는 사용자 승인 전 어디에도 없다.
- [ ] 미완성 표식과 정의되지 않은 interface가 없다.
