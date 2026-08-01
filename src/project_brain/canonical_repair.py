"""검토된 canonicalization decision ledger의 strict decoder와 validator."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from enum import StrEnum
from pathlib import Path

from project_brain.canonical_merge import (
    CollisionMergeError,
    ReferenceCollapse,
    project_collision_merges,
)
from project_brain.id_grammar import IdGrammarError, parse_id
from project_brain.migration import (
    MigrationError,
    trusted_migration_context,
    validate_live_snapshot_corpus,
    validate_snapshot_binding,
)
from project_brain.mutation import (
    CanonicalFieldChange,
    CanonicalRepairIntent,
    MutationManifest,
    MutationOperation,
    MutationPlanResult,
    MutationRequest,
    MutationService,
    corpus_fingerprint,
)
from project_brain.reference_fields import rewrite_object_refs
from project_brain.snapshot import (
    GitWorktreeReceipt,
    SnapshotError,
    SnapshotVerification,
    verify_git_root_clean,
    verify_snapshot,
)
from project_brain.store import BrainStore


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_LEDGER_KEYS = {
    "version",
    "phase_a_classification_sha256",
    "engine_sha",
    "repo_head",
    "corpus_fingerprint",
    "decisions",
}
_DECISION_KEYS = {
    "source_id",
    "source_kind",
    "source_sha256",
    "action",
    "new_id",
    "field_changes",
    "decision_reason",
    "decision_evidence",
}
_FIELD_CHANGE_KEYS = {"pointer", "before", "after"}
_CLASSIFICATION_BINDING_KEYS = {
    "schema_version",
    "engine_sha",
    "repo_head",
    "corpus_fingerprint",
    "eval_sha256",
    "stale_sha256",
}


@dataclass(frozen=True)
class CanonicalRepairError(RuntimeError):
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


class CanonicalAction(StrEnum):
    ID_ONLY_RENAME = "id_only_rename"
    TARGET_DERIVED_REVIEW_RENAME = "target_derived_review_rename"
    REFERENCE_ONLY = "reference_only"
    PROJECTED_FIELD_REPAIR = "projected_field_repair"
    REVIEW_SHAPE_REPAIR = "review_shape_repair"
    COLLISION_DISTINCT_RENAME = "collision_distinct_rename"
    COLLISION_MERGE_INTO_EXISTING = "collision_merge_into_existing"


@dataclass(frozen=True)
class CanonicalizationDecision:
    source_id: str
    source_kind: str
    source_sha256: str
    action: CanonicalAction
    new_id: str | None
    field_changes: tuple[CanonicalFieldChange, ...]
    decision_reason: str
    decision_evidence: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalizationLedger:
    version: int
    phase_a_classification_sha256: str
    engine_sha: str
    repo_head: str
    corpus_fingerprint: str
    decisions: tuple[CanonicalizationDecision, ...]
    sha256: str


@dataclass(frozen=True)
class CanonicalMergeReceipt:
    source_delete_before_sha256: str
    target_id: str
    target_before_sha256: str
    target_after_sha256: str
    reference_collapses: tuple[ReferenceCollapse, ...]


@dataclass(frozen=True)
class CanonicalRepairRow:
    source_id: str
    new_id: str
    kind: str
    reason_code: str
    field_changes: tuple[CanonicalFieldChange, ...]
    canonical_payload_hash: str
    reference_rewrites: tuple[dict, ...]
    snapshot_id: str
    merge_receipt: CanonicalMergeReceipt | None


@dataclass(frozen=True)
class CanonicalRepairPlan:
    request: MutationRequest
    mutation_plan: MutationPlanResult
    rows: tuple[CanonicalRepairRow, ...]
    decision_ledger_sha256: str
    phase_a_classification_sha256: str
    id_renames: tuple[tuple[str, str], ...]
    snapshot_id: str
    snapshot_manifest_sha256: str
    engine_receipt: GitWorktreeReceipt


@dataclass(frozen=True)
class CanonicalRepairArtifact:
    manifest: dict
    manifest_bytes: bytes
    manifest_sha256: str


@dataclass(frozen=True)
class CanonicalRepairApplyResult:
    transaction_id: str
    action_count: int
    snapshot_id: str
    decision_ledger_sha256: str


@dataclass(frozen=True)
class _ArtifactTransitions:
    updates: dict[str, tuple[str, str]]
    renames: dict[str, tuple[str, str, str]]
    deletes: dict[str, str]


class _DuplicateKey(ValueError):
    pass


def _fail(code: str, detail: str) -> None:
    raise CanonicalRepairError(code, detail)


def _duplicate_key_rejector(pairs: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_json(payload: bytes, *, code: str) -> object:
    if not isinstance(payload, bytes):
        _fail(code, "payload must be bytes")
    try:
        return json.loads(payload, object_pairs_hook=_duplicate_key_rejector)
    except (UnicodeError, json.JSONDecodeError, _DuplicateKey) as exc:
        _fail(code, str(exc))


def _exact_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _decode_field_changes(value: object) -> tuple[CanonicalFieldChange, ...]:
    if not isinstance(value, list):
        _fail("decision_ledger_invalid", "field_changes must be a list")
    changes: list[CanonicalFieldChange] = []
    seen_pointers: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != _FIELD_CHANGE_KEYS:
            _fail("decision_ledger_invalid", "field change keys are invalid")
        pointer = raw["pointer"]
        if (
            not isinstance(pointer, str)
            or not pointer.startswith("/")
            or pointer == "/"
            or pointer in seen_pointers
            or raw["before"] == raw["after"]
        ):
            _fail("decision_ledger_invalid", "field change is invalid")
        seen_pointers.add(pointer)
        changes.append(CanonicalFieldChange(
            pointer=pointer,
            before=raw["before"],
            after=raw["after"],
        ))
    return tuple(changes)


def _decode_decision(raw: object) -> CanonicalizationDecision:
    if not isinstance(raw, dict) or set(raw) != _DECISION_KEYS:
        _fail("decision_ledger_invalid", "decision row keys are invalid")
    if (
        not _exact_nonempty_string(raw["source_id"])
        or not _exact_nonempty_string(raw["source_kind"])
        or not isinstance(raw["source_sha256"], str)
        or _SHA256.fullmatch(raw["source_sha256"]) is None
        or not _exact_nonempty_string(raw["decision_reason"])
        or not isinstance(raw["decision_evidence"], list)
        or not raw["decision_evidence"]
        or not all(
            _exact_nonempty_string(item)
            for item in raw["decision_evidence"]
        )
        or len(set(raw["decision_evidence"]))
        != len(raw["decision_evidence"])
    ):
        _fail("decision_ledger_invalid", "decision row values are invalid")
    try:
        action = CanonicalAction(raw["action"])
    except (TypeError, ValueError):
        _fail("decision_ledger_invalid", "decision action is invalid")
    new_id = raw["new_id"]
    if action is CanonicalAction.REFERENCE_ONLY:
        if new_id is not None:
            _fail(
                "decision_ledger_invalid",
                "reference_only must not change the source ID",
            )
    elif not _exact_nonempty_string(new_id):
        _fail("decision_ledger_invalid", "rename decision requires new_id")
    changes = _decode_field_changes(raw["field_changes"])
    expected_pointer = {
        CanonicalAction.PROJECTED_FIELD_REPAIR: "/mapping_key",
        CanonicalAction.REVIEW_SHAPE_REPAIR: "/target_object_ids",
    }.get(action)
    if expected_pointer is None:
        if changes:
            _fail(
                "decision_ledger_invalid",
                f"{action.value} does not allow field changes",
            )
    elif len(changes) != 1 or changes[0].pointer != expected_pointer:
        _fail(
            "decision_ledger_invalid",
            f"{action.value} requires an exact {expected_pointer} change",
        )
    return CanonicalizationDecision(
        source_id=raw["source_id"],
        source_kind=raw["source_kind"],
        source_sha256=raw["source_sha256"],
        action=action,
        new_id=new_id,
        field_changes=changes,
        decision_reason=raw["decision_reason"],
        decision_evidence=tuple(raw["decision_evidence"]),
    )


def decode_canonicalization_ledger(payload: bytes) -> CanonicalizationLedger:
    raw = _load_json(payload, code="decision_ledger_invalid")
    if not isinstance(raw, dict) or set(raw) != _LEDGER_KEYS:
        _fail("decision_ledger_invalid", "decision ledger keys are invalid")
    if (
        type(raw["version"]) is not int
        or raw["version"] != 1
        or not isinstance(raw["phase_a_classification_sha256"], str)
        or _SHA256.fullmatch(raw["phase_a_classification_sha256"]) is None
        or not isinstance(raw["engine_sha"], str)
        or _GIT_SHA.fullmatch(raw["engine_sha"]) is None
        or not isinstance(raw["repo_head"], str)
        or _GIT_SHA.fullmatch(raw["repo_head"]) is None
        or not isinstance(raw["corpus_fingerprint"], str)
        or _SHA256.fullmatch(raw["corpus_fingerprint"]) is None
        or not isinstance(raw["decisions"], list)
    ):
        _fail("decision_ledger_invalid", "decision ledger values are invalid")
    decisions = tuple(_decode_decision(item) for item in raw["decisions"])
    source_ids = [decision.source_id for decision in decisions]
    if len(set(source_ids)) != len(source_ids):
        _fail("decision_ledger_invalid", "decision sources must be unique")
    return CanonicalizationLedger(
        version=raw["version"],
        phase_a_classification_sha256=raw[
            "phase_a_classification_sha256"
        ],
        engine_sha=raw["engine_sha"],
        repo_head=raw["repo_head"],
        corpus_fingerprint=raw["corpus_fingerprint"],
        decisions=decisions,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _classification_rows(
    classification_bytes: bytes,
) -> tuple[dict[str, tuple[str, str]], dict]:
    raw = _load_json(
        classification_bytes,
        code="classification_invalid",
    )
    if not isinstance(raw, dict):
        _fail("classification_invalid", "classification must be an object")
    binding = raw.get("binding")
    rows = raw.get("rows")
    if (
        not isinstance(binding, dict)
        or set(binding) != _CLASSIFICATION_BINDING_KEYS
        or binding["schema_version"] != 1
        or not isinstance(rows, list)
    ):
        _fail("classification_invalid", "classification binding is invalid")
    for field in ("eval_sha256", "corpus_fingerprint"):
        if (
            not isinstance(binding[field], str)
            or _SHA256.fullmatch(binding[field]) is None
        ):
            _fail("classification_invalid", f"classification {field} is invalid")
    if binding["stale_sha256"] is not None and (
        not isinstance(binding["stale_sha256"], str)
        or _SHA256.fullmatch(binding["stale_sha256"]) is None
    ):
        _fail("classification_invalid", "classification stale_sha256 is invalid")
    for field in ("engine_sha", "repo_head"):
        if (
            not isinstance(binding[field], str)
            or _GIT_SHA.fullmatch(binding[field]) is None
        ):
            _fail("classification_invalid", f"classification {field} is invalid")
    by_source: dict[str, tuple[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            _fail("classification_invalid", "classification row is invalid")
        source_id = row.get("old_id")
        source_kind = row.get("kind")
        source_sha256 = row.get("source_sha256")
        if (
            not _exact_nonempty_string(source_id)
            or not _exact_nonempty_string(source_kind)
            or not isinstance(source_sha256, str)
            or _SHA256.fullmatch(source_sha256) is None
            or source_id in by_source
        ):
            _fail("classification_invalid", "classification row binding is invalid")
        by_source[source_id] = (source_kind, source_sha256)
    return by_source, binding


def validate_canonicalization_ledger(
    ledger: CanonicalizationLedger,
    *,
    classification_bytes: bytes,
    expected_classification_sha256: str,
    existing: BrainStore,
    engine_sha: str,
    repo_head: str,
) -> CanonicalizationLedger:
    if not isinstance(ledger, CanonicalizationLedger):
        _fail("decision_ledger_invalid", "ledger has the wrong type")
    if (
        not isinstance(expected_classification_sha256, str)
        or _SHA256.fullmatch(expected_classification_sha256) is None
        or hashlib.sha256(classification_bytes).hexdigest()
        != expected_classification_sha256
        or ledger.phase_a_classification_sha256
        != expected_classification_sha256
    ):
        _fail(
            "classification_sha256_mismatch",
            "classification bytes do not match the trusted receipt and ledger",
        )
    if ledger.engine_sha != engine_sha:
        _fail(
            "decision_engine_sha_mismatch",
            "decision ledger engine SHA differs from the current engine",
        )
    if ledger.repo_head != repo_head:
        _fail(
            "decision_repo_head_mismatch",
            "decision ledger repo HEAD differs from the current repository",
        )
    if not isinstance(existing, BrainStore):
        _fail("request_invalid", "existing must be BrainStore")
    if ledger.corpus_fingerprint != corpus_fingerprint(existing):
        _fail(
            "decision_corpus_fingerprint_mismatch",
            "decision ledger corpus fingerprint differs from the current store",
        )
    classification, binding = _classification_rows(classification_bytes)
    if (
        binding["engine_sha"] != ledger.engine_sha
        or binding["repo_head"] != ledger.repo_head
        or binding["corpus_fingerprint"] != ledger.corpus_fingerprint
    ):
        _fail(
            "classification_binding_mismatch",
            "classification binding differs from the decision ledger",
        )
    decision_by_source = {
        decision.source_id: decision
        for decision in ledger.decisions
    }
    if len(decision_by_source) != 156 or len(classification) != 156:
        _fail(
            "classification_coverage_invalid",
            "decision ledger must exactly cover all 156 classification rows",
        )
    if set(decision_by_source) != set(classification):
        _fail(
            "classification_source_mismatch",
            "classification and decision source IDs differ",
        )
    merge_decisions = tuple(
        decision
        for decision in ledger.decisions
        if decision.action is CanonicalAction.COLLISION_MERGE_INTO_EXISTING
    )
    if len(merge_decisions) != 2:
        _fail(
            "canonical_repair_action_count_invalid",
            "canonical repair ledger requires exactly 2 collision merge rows",
        )

    targets: dict[str, CanonicalAction] = {}
    merge_targets: set[str] = set()
    rename_targets: set[str] = set()
    for decision in ledger.decisions:
        if decision.action is CanonicalAction.REFERENCE_ONLY:
            continue
        assert decision.new_id is not None
        previous_action = targets.get(decision.new_id)
        if previous_action is not None:
            if (
                decision.action
                is CanonicalAction.COLLISION_MERGE_INTO_EXISTING
                or previous_action
                is CanonicalAction.COLLISION_MERGE_INTO_EXISTING
            ):
                _fail(
                    "decision_merge_endpoint_overlap",
                    f"merge target overlaps another target: {decision.new_id}",
                )
            _fail(
                "decision_target_duplicate",
                f"duplicate decision target: {decision.new_id}",
            )
        targets[decision.new_id] = decision.action
        if (
            decision.action
            is CanonicalAction.COLLISION_MERGE_INTO_EXISTING
        ):
            merge_targets.add(decision.new_id)
        else:
            rename_targets.add(decision.new_id)
    overlap = merge_targets & (set(decision_by_source) | rename_targets)
    if overlap:
        _fail(
            "decision_merge_endpoint_overlap",
            f"merge endpoints overlap ledger sources or targets: {sorted(overlap)!r}",
        )

    for source_id, decision in decision_by_source.items():
        if classification[source_id] != (
            decision.source_kind,
            decision.source_sha256,
        ):
            _fail(
                "classification_source_mismatch",
                f"{source_id}: decision differs from classification source binding",
            )
        if not existing.has(source_id):
            _fail(
                "decision_source_missing",
                f"decision source is absent from the current store: {source_id}",
            )
        if existing.get(source_id).get("kind") != decision.source_kind:
            _fail(
                "classification_source_mismatch",
                f"{source_id}: current kind differs from the decision ledger",
            )
        if existing.source_sha256(source_id) != decision.source_sha256:
            _fail(
                "decision_source_sha256_mismatch",
                f"{source_id}: current source bytes differ from the decision ledger",
            )
        if decision.action is CanonicalAction.REFERENCE_ONLY:
            continue
        assert decision.new_id is not None
        if (
            decision.action
            is CanonicalAction.COLLISION_MERGE_INTO_EXISTING
        ):
            if (
                decision.source_kind != "DomainMapping"
                or not existing.has(decision.new_id)
            ):
                _fail("decision_merge_target_invalid", decision.source_id)
            try:
                parse_id(decision.new_id, "DomainMapping")
            except IdGrammarError as exc:
                _fail("decision_merge_target_invalid", str(exc))
        else:
            if existing.has(decision.new_id):
                _fail(
                    "decision_target_exists",
                    f"decision target already exists: {decision.new_id}",
                )
            try:
                parse_id(decision.new_id, decision.source_kind)
            except IdGrammarError as exc:
                _fail(
                    "decision_target_invalid",
                    f"{decision.source_id}: new ID is not canonical: {exc}",
                )
        if decision.action is CanonicalAction.PROJECTED_FIELD_REPAIR:
            change = decision.field_changes[0]
            try:
                parsed = parse_id(decision.new_id, "DomainMapping")
            except IdGrammarError as exc:
                _fail("decision_target_invalid", str(exc))
            if (
                decision.source_kind != "DomainMapping"
                or not isinstance(change.before, str)
                or not isinstance(change.after, str)
                or change.after != parsed.key
            ):
                _fail(
                    "decision_field_change_invalid",
                    f"{source_id}: projected field repair is invalid",
                )
        elif (
            decision.action is CanonicalAction.REVIEW_SHAPE_REPAIR
            and decision.source_kind != "ReviewRecord"
        ):
            _fail(
                "decision_field_change_invalid",
                f"{source_id}: review shape repair kind is invalid",
            )
    merge_pairs = collision_merges_from_ledger(ledger)
    if merge_pairs:
        try:
            project_collision_merges(
                {str(obj["id"]): obj for obj in existing.all()},
                merge_pairs,
            )
        except CollisionMergeError as exc:
            _fail(exc.code, exc.detail)
    return ledger


def parse_canonicalization_ledger(
    payload: bytes,
    *,
    classification_bytes: bytes,
    expected_classification_sha256: str,
    existing: BrainStore,
    engine_sha: str,
    repo_head: str,
) -> CanonicalizationLedger:
    return validate_canonicalization_ledger(
        decode_canonicalization_ledger(payload),
        classification_bytes=classification_bytes,
        expected_classification_sha256=expected_classification_sha256,
        existing=existing,
        engine_sha=engine_sha,
        repo_head=repo_head,
    )


def canonical_repair_renames_from_ledger(
    ledger: CanonicalizationLedger,
) -> dict[str, str]:
    actions = {
        CanonicalAction.PROJECTED_FIELD_REPAIR,
        CanonicalAction.REVIEW_SHAPE_REPAIR,
    }
    return {
        decision.source_id: decision.new_id
        for decision in ledger.decisions
        if decision.action in actions and decision.new_id is not None
    }


def collision_merges_from_ledger(
    ledger: CanonicalizationLedger,
) -> dict[str, str]:
    return {
        decision.source_id: decision.new_id
        for decision in ledger.decisions
        if (
            decision.action
            is CanonicalAction.COLLISION_MERGE_INTO_EXISTING
            and decision.new_id is not None
        )
    }


def id_renames_from_ledger(
    ledger: CanonicalizationLedger,
) -> dict[str, str]:
    actions = {
        CanonicalAction.ID_ONLY_RENAME,
        CanonicalAction.TARGET_DERIVED_REVIEW_RENAME,
        CanonicalAction.COLLISION_DISTINCT_RENAME,
    }
    return {
        decision.source_id: decision.new_id
        for decision in ledger.decisions
        if decision.action in actions and decision.new_id is not None
    }


def _object_hash(obj: Mapping[str, object]) -> str:
    return hashlib.sha256(BrainStore.object_bytes(obj)).hexdigest()


def _canonical_json_bytes(payload: object) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _migration_failure(exc: MigrationError) -> None:
    _fail(exc.code, exc.detail)


def _snapshot_failure(exc: SnapshotError) -> None:
    _fail(exc.code, exc.detail)


def _validate_plan_ledger_binding(
    ledger: CanonicalizationLedger,
    *,
    existing: BrainStore,
    engine_sha: str,
    snapshot: SnapshotVerification,
) -> None:
    if not isinstance(ledger, CanonicalizationLedger):
        _fail("decision_ledger_invalid", "ledger has the wrong type")
    if _SHA256.fullmatch(ledger.sha256) is None:
        _fail("decision_ledger_invalid", "ledger SHA is invalid")
    if ledger.engine_sha != engine_sha:
        _fail(
            "decision_engine_sha_mismatch",
            "decision ledger engine SHA differs from the current engine",
        )
    if ledger.repo_head != snapshot.repo_head:
        _fail(
            "decision_repo_head_mismatch",
            "decision ledger repo HEAD differs from the trusted snapshot",
        )
    if ledger.corpus_fingerprint != corpus_fingerprint(existing):
        _fail(
            "decision_corpus_fingerprint_mismatch",
            "decision ledger corpus fingerprint differs from the current store",
        )
    for decision in ledger.decisions:
        if (
            not existing.has(decision.source_id)
            or existing.get(decision.source_id).get("kind")
            != decision.source_kind
            or existing.source_sha256(decision.source_id)
            != decision.source_sha256
        ):
            _fail(
                "decision_source_sha256_mismatch",
                f"{decision.source_id}: current source differs from the ledger",
            )


def _replace_approved_field(obj: dict, change: CanonicalFieldChange) -> None:
    key = change.pointer.removeprefix("/")
    if obj.get(key) != change.before:
        _fail(
            "decision_field_change_mismatch",
            f"approved before value differs at {change.pointer}",
        )
    obj[key] = deepcopy(change.after)


def _validate_repair_action_counts(ledger: CanonicalizationLedger) -> None:
    actual = {
        action: sum(
            decision.action is action
            for decision in ledger.decisions
        )
        for action in (
            CanonicalAction.PROJECTED_FIELD_REPAIR,
            CanonicalAction.REVIEW_SHAPE_REPAIR,
            CanonicalAction.COLLISION_MERGE_INTO_EXISTING,
        )
    }
    expected = {
        CanonicalAction.PROJECTED_FIELD_REPAIR: 4,
        CanonicalAction.REVIEW_SHAPE_REPAIR: 1,
        CanonicalAction.COLLISION_MERGE_INTO_EXISTING: 2,
    }
    if actual != expected:
        _fail(
            "canonical_repair_action_count_invalid",
            (
                "canonical repair ledger requires exactly "
                "4 projected_field_repair, 1 review_shape_repair, and "
                "2 collision_merge_into_existing rows"
            ),
        )


def plan_canonical_repair(
    *,
    existing: BrainStore,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
    engine_sha: str,
    ledger: CanonicalizationLedger,
    snapshot: SnapshotVerification,
) -> CanonicalRepairPlan:
    if not isinstance(existing, BrainStore):
        _fail("request_invalid", "existing must be BrainStore")
    try:
        repo_context = trusted_migration_context(
            brain_root=brain_root,
            repo_root=repo_root,
            engine_root=engine_root,
            engine_sha=engine_sha,
            snapshot=snapshot,
        )
        validate_live_snapshot_corpus(existing, snapshot)
    except MigrationError as exc:
        _migration_failure(exc)
    _validate_plan_ledger_binding(
        ledger,
        existing=existing,
        engine_sha=engine_sha,
        snapshot=snapshot,
    )
    _validate_repair_action_counts(ledger)
    try:
        engine_receipt = verify_git_root_clean(
            engine_root,
            label="engine_root",
        )
    except SnapshotError as exc:
        _snapshot_failure(exc)
    if engine_receipt.head != engine_sha or engine_receipt.status_bytes != b"":
        _fail(
            "engine_receipt_mismatch",
            "clean engine receipt differs from the requested engine",
        )

    repair_pairs = canonical_repair_renames_from_ledger(ledger)
    merge_pairs = collision_merges_from_ledger(ledger)
    if not repair_pairs:
        _fail("canonical_repair_empty", "ledger has no canonical repair rows")
    repair_decisions = tuple(
        decision
        for decision in ledger.decisions
        if decision.source_id in repair_pairs
    )
    merge_decisions = tuple(
        decision
        for decision in ledger.decisions
        if decision.source_id in merge_pairs
    )
    existing_by_id = {str(obj["id"]): obj for obj in existing.all()}
    try:
        merge_projection = project_collision_merges(
            existing_by_id,
            merge_pairs,
        )
    except CollisionMergeError as exc:
        _fail(exc.code, exc.detail)

    logical_by_id: dict[str, dict] = {}
    for object_id in sorted(merge_projection.after_by_id):
        rewritten, _ = rewrite_object_refs(
            merge_projection.after_by_id[object_id],
            repair_pairs,
        )
        new_id = repair_pairs.get(object_id)
        decision = next(
            (
                item
                for item in repair_decisions
                if item.source_id == object_id
            ),
            None,
        )
        if new_id is not None:
            rewritten["id"] = new_id
            assert decision is not None
            for change in decision.field_changes:
                _replace_approved_field(rewritten, change)
        logical_by_id[new_id or object_id] = rewritten

    request_objects = [
        logical_by_id[object_id]
        for object_id in sorted(logical_by_id)
        if (
            object_id in set(merge_pairs.values())
            or object_id not in existing_by_id
            or logical_by_id[object_id] != existing_by_id[object_id]
        )
    ]

    request_by_id = {str(obj["id"]): obj for obj in request_objects}
    intents = tuple(
        CanonicalRepairIntent(
            source_id=decision.source_id,
            new_id=repair_pairs[decision.source_id],
            reason_code=decision.action.value,
            field_changes=decision.field_changes,
        )
        for decision in repair_decisions
    ) + tuple(
        CanonicalRepairIntent(
            source_id=decision.source_id,
            new_id=merge_pairs[decision.source_id],
            reason_code=decision.action.value,
            field_changes=decision.field_changes,
        )
        for decision in merge_decisions
    )
    delete_ids = set(repair_pairs) | set(merge_pairs)
    precondition_ids = set(delete_ids)
    precondition_ids.update(
        object_id
        for object_id in request_by_id
        if object_id in existing_by_id
    )
    request = MutationRequest(
        operation=MutationOperation.CANONICAL_REPAIR,
        brain_root=brain_root,
        repo_context=repo_context,
        engine_sha=engine_sha,
        objects=tuple(request_objects),
        delete_ids=tuple(sorted(delete_ids)),
        renames=dict(repair_pairs),
        preconditions={
            object_id: _object_hash(existing_by_id[object_id])
            for object_id in sorted(precondition_ids)
        },
        expected_corpus_fingerprint=corpus_fingerprint(existing),
        canonical_repair_intents=intents,
        canonical_repair_reference_collapses=(
            merge_projection.reference_collapses
        ),
        canonical_repair_binding={
            "decision_ledger_sha256": ledger.sha256,
            "phase_a_classification_sha256": (
                ledger.phase_a_classification_sha256
            ),
        },
    )
    mutation_plan = MutationService().plan(request.objects, request=request)
    if not mutation_plan.ok or mutation_plan.manifest is None:
        _fail(
            mutation_plan.error_code or "mutation_plan_failed",
            mutation_plan.detail or "canonical repair preflight failed",
        )
    after_by_id = {
        str(obj["id"]): obj
        for obj in mutation_plan.after_objects
    }
    rows: list[CanonicalRepairRow] = []
    for decision in repair_decisions:
        new_id = repair_pairs[decision.source_id]
        after = after_by_id[new_id]
        row_rewrites = tuple(
            dict(rewrite)
            for rewrite in mutation_plan.manifest.reference_rewrites
            if (
                rewrite["before_id"] == decision.source_id
                and rewrite["after_id"] == new_id
            )
        )
        rows.append(CanonicalRepairRow(
            source_id=decision.source_id,
            new_id=new_id,
            kind=decision.source_kind,
            reason_code=decision.action.value,
            field_changes=decision.field_changes,
            canonical_payload_hash=_object_hash(after),
            reference_rewrites=row_rewrites,
            snapshot_id=snapshot.snapshot_id,
            merge_receipt=None,
        ))
    for decision in merge_decisions:
        target_id = merge_pairs[decision.source_id]
        after = after_by_id[target_id]
        row_rewrites = tuple(
            dict(rewrite)
            for rewrite in mutation_plan.manifest.reference_rewrites
            if (
                rewrite["before_id"] == decision.source_id
                and rewrite["after_id"] == target_id
            )
        )
        target_after_sha256 = _object_hash(after)
        rows.append(CanonicalRepairRow(
            source_id=decision.source_id,
            new_id=target_id,
            kind=decision.source_kind,
            reason_code=decision.action.value,
            field_changes=decision.field_changes,
            canonical_payload_hash=target_after_sha256,
            reference_rewrites=row_rewrites,
            snapshot_id=snapshot.snapshot_id,
            merge_receipt=CanonicalMergeReceipt(
                source_delete_before_sha256=existing.source_sha256(
                    decision.source_id
                ),
                target_id=target_id,
                target_before_sha256=existing.source_sha256(target_id),
                target_after_sha256=target_after_sha256,
                reference_collapses=tuple(
                    collapse
                    for collapse in merge_projection.reference_collapses
                    if collapse.before_ids[collapse.removed_index]
                    == decision.source_id
                ),
            ),
        ))
    return CanonicalRepairPlan(
        request=request,
        mutation_plan=mutation_plan,
        rows=tuple(rows),
        decision_ledger_sha256=ledger.sha256,
        phase_a_classification_sha256=(
            ledger.phase_a_classification_sha256
        ),
        id_renames=tuple(sorted(id_renames_from_ledger(ledger).items())),
        snapshot_id=snapshot.snapshot_id,
        snapshot_manifest_sha256=snapshot.manifest_sha256,
        engine_receipt=engine_receipt,
    )


def create_canonical_repair_artifact(
    plan: CanonicalRepairPlan,
) -> CanonicalRepairArtifact:
    if plan.mutation_plan.manifest is None:
        _fail("mutation_plan_missing", "canonical repair plan has no manifest")
    artifact = {
        **asdict(plan.mutation_plan.manifest),
        "canonical_repair_version": 1,
        "migration_kind": "canonical_repair",
        "rows": [asdict(row) for row in plan.rows],
        "objects": list(plan.mutation_plan.after_objects),
        "decision_ledger_sha256": plan.decision_ledger_sha256,
        "phase_a_classification_sha256": (
            plan.phase_a_classification_sha256
        ),
        "id_renames": dict(plan.id_renames),
        "snapshot_id": plan.snapshot_id,
        "snapshot_manifest_sha256": plan.snapshot_manifest_sha256,
        "engine_receipt": {
            "root": plan.engine_receipt.root,
            "head": plan.engine_receipt.head,
            "status_sha256": plan.engine_receipt.status_sha256,
        },
    }
    payload = _canonical_json_bytes(artifact)
    return CanonicalRepairArtifact(
        manifest=artifact,
        manifest_bytes=payload,
        manifest_sha256=hashlib.sha256(payload).hexdigest(),
    )


_CANONICAL_ARTIFACT_EXTRA_KEYS = {
    "canonical_repair_version",
    "migration_kind",
    "rows",
    "objects",
    "decision_ledger_sha256",
    "phase_a_classification_sha256",
    "id_renames",
    "snapshot_id",
    "snapshot_manifest_sha256",
    "engine_receipt",
}
_CANONICAL_ROW_KEYS = {
    "source_id",
    "new_id",
    "kind",
    "reason_code",
    "field_changes",
    "canonical_payload_hash",
    "reference_rewrites",
    "snapshot_id",
    "merge_receipt",
}
_REFERENCE_REWRITE_KEYS = {
    "object_id",
    "pointer",
    "before_id",
    "after_id",
}
_MERGE_RECEIPT_KEYS = {
    "source_delete_before_sha256",
    "target_id",
    "target_before_sha256",
    "target_after_sha256",
    "reference_collapses",
}
_REFERENCE_COLLAPSE_KEYS = {
    "object_id",
    "pointer",
    "before_ids",
    "after_ids",
    "removed_index",
}


def _validate_sha_receipt(
    payload: bytes,
    expected_sha256: str,
    *,
    code: str,
    label: str,
) -> None:
    if (
        not isinstance(expected_sha256, str)
        or _SHA256.fullmatch(expected_sha256) is None
        or not isinstance(payload, bytes)
        or hashlib.sha256(payload).hexdigest() != expected_sha256
    ):
        _fail(code, f"{label} bytes do not match the trusted receipt")


def _json_exact(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        assert isinstance(right, dict)
        return left.keys() == right.keys() and all(
            _json_exact(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        assert isinstance(right, list)
        return len(left) == len(right) and all(
            _json_exact(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _valid_artifact_pointer(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("/")
        and value != "/"
    )


def _validate_artifact_field_changes(
    value: object,
    *,
    reason_code: str,
) -> None:
    if not isinstance(value, list):
        _fail("manifest_invalid", "artifact row field_changes are invalid")
    expected_pointers = {
        CanonicalAction.PROJECTED_FIELD_REPAIR.value: ("/mapping_key",),
        CanonicalAction.REVIEW_SHAPE_REPAIR.value: (
            "/target_object_ids",
        ),
        CanonicalAction.COLLISION_MERGE_INTO_EXISTING.value: (),
    }.get(reason_code)
    if expected_pointers is None:
        _fail("manifest_invalid", "artifact row reason_code is invalid")
    pointers: list[str] = []
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != _FIELD_CHANGE_KEYS:
            _fail("manifest_invalid", "artifact field change keys are invalid")
        pointer = raw["pointer"]
        if (
            not _valid_artifact_pointer(pointer)
            or _json_exact(raw["before"], raw["after"])
        ):
            _fail("manifest_invalid", "artifact field change is invalid")
        assert isinstance(pointer, str)
        pointers.append(pointer)
    if tuple(pointers) != expected_pointers:
        _fail("manifest_invalid", "artifact row field changes do not match action")


def _validate_artifact_reference_rewrites(
    value: object,
    *,
    source_id: str,
    new_id: str,
) -> None:
    if not isinstance(value, list):
        _fail("manifest_invalid", "artifact row reference_rewrites are invalid")
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != _REFERENCE_REWRITE_KEYS:
            _fail("manifest_invalid", "artifact reference rewrite keys are invalid")
        if (
            not _exact_nonempty_string(raw["object_id"])
            or not _valid_artifact_pointer(raw["pointer"])
            or raw["before_id"] != source_id
            or raw["after_id"] != new_id
        ):
            _fail("manifest_invalid", "artifact reference rewrite is invalid")


def _validate_artifact_merge_receipt(
    value: object,
    *,
    source_id: str,
    new_id: str,
    canonical_payload_hash: str,
) -> None:
    if not isinstance(value, dict) or set(value) != _MERGE_RECEIPT_KEYS:
        _fail("manifest_invalid", "artifact merge receipt keys are invalid")
    if (
        not isinstance(value["source_delete_before_sha256"], str)
        or _SHA256.fullmatch(value["source_delete_before_sha256"]) is None
        or value["target_id"] != new_id
        or not isinstance(value["target_before_sha256"], str)
        or _SHA256.fullmatch(value["target_before_sha256"]) is None
        or value["target_after_sha256"] != canonical_payload_hash
        or not isinstance(value["target_after_sha256"], str)
        or _SHA256.fullmatch(value["target_after_sha256"]) is None
        or not isinstance(value["reference_collapses"], list)
    ):
        _fail("manifest_invalid", "artifact merge receipt is invalid")
    for raw in value["reference_collapses"]:
        if not isinstance(raw, dict) or set(raw) != _REFERENCE_COLLAPSE_KEYS:
            _fail("manifest_invalid", "artifact reference collapse keys are invalid")
        before_ids = raw["before_ids"]
        after_ids = raw["after_ids"]
        removed_index = raw["removed_index"]
        if (
            not _exact_nonempty_string(raw["object_id"])
            or not _valid_artifact_pointer(raw["pointer"])
            or not isinstance(before_ids, list)
            or not all(_exact_nonempty_string(item) for item in before_ids)
            or not isinstance(after_ids, list)
            or not all(_exact_nonempty_string(item) for item in after_ids)
            or type(removed_index) is not int
            or not 0 <= removed_index < len(before_ids)
        ):
            _fail("manifest_invalid", "artifact reference collapse is invalid")
        if (
            before_ids[removed_index] != source_id
            or after_ids
            != before_ids[:removed_index] + before_ids[removed_index + 1:]
            or before_ids.count(source_id) != 1
            or before_ids.count(new_id) != 1
            or after_ids.count(new_id) != 1
        ):
            _fail(
                "manifest_invalid",
                "artifact reference collapse does not match its merge row",
            )


def _validate_artifact_rows(value: object, *, snapshot_id: str) -> None:
    if not isinstance(value, list):
        _fail("manifest_invalid", "artifact rows are invalid")
    seen_sources: set[str] = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != _CANONICAL_ROW_KEYS:
            _fail("manifest_invalid", "artifact row keys are invalid")
        source_id = row["source_id"]
        new_id = row["new_id"]
        reason_code = row["reason_code"]
        canonical_payload_hash = row["canonical_payload_hash"]
        if (
            not _exact_nonempty_string(source_id)
            or not _exact_nonempty_string(new_id)
            or source_id == new_id
            or not _exact_nonempty_string(row["kind"])
            or not _exact_nonempty_string(reason_code)
            or not isinstance(canonical_payload_hash, str)
            or _SHA256.fullmatch(canonical_payload_hash) is None
            or row["snapshot_id"] != snapshot_id
            or source_id in seen_sources
        ):
            _fail("manifest_invalid", "artifact row values are invalid")
        assert isinstance(source_id, str)
        assert isinstance(new_id, str)
        assert isinstance(reason_code, str)
        assert isinstance(canonical_payload_hash, str)
        seen_sources.add(source_id)
        _validate_artifact_field_changes(
            row["field_changes"],
            reason_code=reason_code,
        )
        _validate_artifact_reference_rewrites(
            row["reference_rewrites"],
            source_id=source_id,
            new_id=new_id,
        )
        if reason_code == CanonicalAction.COLLISION_MERGE_INTO_EXISTING.value:
            _validate_artifact_merge_receipt(
                row["merge_receipt"],
                source_id=source_id,
                new_id=new_id,
                canonical_payload_hash=canonical_payload_hash,
            )
        elif row["merge_receipt"] is not None:
            _fail(
                "manifest_invalid",
                "non-merge artifact row must have a null merge receipt",
            )


def _parse_canonical_artifact(
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
) -> dict:
    _validate_sha_receipt(
        manifest_bytes,
        expected_manifest_sha256,
        code="manifest_sha256_mismatch",
        label="canonical repair manifest",
    )
    artifact = _load_json(manifest_bytes, code="manifest_invalid")
    expected_keys = {
        *(field.name for field in fields(MutationManifest)),
        *_CANONICAL_ARTIFACT_EXTRA_KEYS,
    }
    if not isinstance(artifact, dict) or set(artifact) != expected_keys:
        _fail("manifest_invalid", "canonical repair artifact keys are invalid")
    engine_receipt = artifact["engine_receipt"]
    if (
        type(artifact["canonical_repair_version"]) is not int
        or artifact["canonical_repair_version"] != 1
        or artifact["migration_kind"] != "canonical_repair"
        or not isinstance(artifact["rows"], list)
        or not isinstance(artifact["objects"], list)
        or not isinstance(artifact["id_renames"], dict)
        or not isinstance(engine_receipt, dict)
        or set(engine_receipt) != {"root", "head", "status_sha256"}
        or not _exact_nonempty_string(engine_receipt["root"])
        or not isinstance(engine_receipt["head"], str)
        or _GIT_SHA.fullmatch(engine_receipt["head"]) is None
        or engine_receipt["status_sha256"] != hashlib.sha256(b"").hexdigest()
        or not isinstance(artifact["decision_ledger_sha256"], str)
        or _SHA256.fullmatch(artifact["decision_ledger_sha256"]) is None
        or not isinstance(artifact["phase_a_classification_sha256"], str)
        or _SHA256.fullmatch(artifact["phase_a_classification_sha256"]) is None
        or not isinstance(artifact["snapshot_manifest_sha256"], str)
        or _SHA256.fullmatch(artifact["snapshot_manifest_sha256"]) is None
        or not _exact_nonempty_string(artifact["snapshot_id"])
    ):
        _fail("manifest_invalid", "canonical repair artifact values are invalid")
    if not all(
        _exact_nonempty_string(old_id)
        and _exact_nonempty_string(new_id)
        for old_id, new_id in artifact["id_renames"].items()
    ):
        _fail("manifest_invalid", "artifact id_renames are invalid")
    _validate_artifact_rows(
        artifact["rows"],
        snapshot_id=artifact["snapshot_id"],
    )
    return artifact


def _validate_artifact_trust_bindings(
    artifact: Mapping[str, object],
    *,
    decisions_sha256: str,
    classification_sha256: str,
    engine_sha: str,
    snapshot: SnapshotVerification,
) -> None:
    if (
        artifact["decision_ledger_sha256"] != decisions_sha256
        or artifact["phase_a_classification_sha256"]
        != classification_sha256
    ):
        _fail(
            "manifest_binding_mismatch",
            "canonical artifact decision bindings differ from trusted inputs",
        )
    if artifact["engine_sha"] != engine_sha:
        _fail("engine_sha_mismatch", "artifact engine SHA differs from apply input")
    receipt = artifact["engine_receipt"]
    assert isinstance(receipt, dict)
    if receipt["head"] != engine_sha:
        _fail(
            "engine_receipt_mismatch",
            "artifact clean engine receipt differs from apply input",
        )
    if (
        artifact["snapshot_id"] != snapshot.snapshot_id
        or artifact["snapshot_manifest_sha256"]
        != snapshot.manifest_sha256
    ):
        _fail(
            "snapshot_binding_mismatch",
            "apply snapshot differs from the planned trusted snapshot",
        )


def apply_canonical_repair_artifact(
    *,
    manifest_bytes: bytes,
    expected_manifest_sha256: str,
    decisions_bytes: bytes,
    expected_decisions_sha256: str,
    classification_bytes: bytes,
    expected_classification_sha256: str,
    brain_root: Path,
    repo_root: Path,
    engine_root: Path,
    engine_sha: str,
    snapshot_root: Path,
    expected_snapshot_manifest_sha256: str,
    failure_injector: Callable[[str], None] | None = None,
) -> CanonicalRepairApplyResult:
    artifact = _parse_canonical_artifact(
        manifest_bytes,
        expected_manifest_sha256,
    )
    _validate_sha_receipt(
        decisions_bytes,
        expected_decisions_sha256,
        code="decision_ledger_sha256_mismatch",
        label="decision ledger",
    )
    _validate_sha_receipt(
        classification_bytes,
        expected_classification_sha256,
        code="classification_sha256_mismatch",
        label="classification",
    )
    ledger = decode_canonicalization_ledger(decisions_bytes)
    try:
        snapshot = verify_snapshot(
            snapshot_root,
            expected_manifest_sha256=expected_snapshot_manifest_sha256,
        )
    except SnapshotError as exc:
        _snapshot_failure(exc)
    _validate_artifact_trust_bindings(
        artifact,
        decisions_sha256=expected_decisions_sha256,
        classification_sha256=expected_classification_sha256,
        engine_sha=engine_sha,
        snapshot=snapshot,
    )
    existing = BrainStore.load(brain_root)
    ledger = validate_canonicalization_ledger(
        ledger,
        classification_bytes=classification_bytes,
        expected_classification_sha256=expected_classification_sha256,
        existing=existing,
        engine_sha=engine_sha,
        repo_head=snapshot.repo_head,
    )
    replanned = plan_canonical_repair(
        existing=existing,
        brain_root=brain_root,
        repo_root=repo_root,
        engine_root=engine_root,
        engine_sha=engine_sha,
        ledger=ledger,
        snapshot=snapshot,
    )
    fresh = create_canonical_repair_artifact(replanned)
    if fresh.manifest_bytes != manifest_bytes:
        _fail(
            "manifest_revalidation_failed",
            "live replan differs from the supplied canonical repair artifact",
        )
    result = MutationService().apply(
        replanned.request.objects,
        request=replanned.request,
        failure_injector=failure_injector,
    )
    if not result.ok or result.manifest is None:
        _fail(
            result.error_code or "mutation_apply_failed",
            result.detail or "canonical repair mutation failed",
        )
    return CanonicalRepairApplyResult(
        transaction_id=result.manifest.transaction_id,
        action_count=(
            len(result.manifest.creates)
            + len(result.manifest.updates)
            + len(result.manifest.deletes)
            + len(result.manifest.renames)
            + len(result.manifest.auxiliary_updates)
        ),
        snapshot_id=snapshot.snapshot_id,
        decision_ledger_sha256=ledger.sha256,
    )


def _validate_classification_receipt_for_ledger(
    ledger: CanonicalizationLedger,
    *,
    classification_bytes: bytes,
    expected_classification_sha256: str,
) -> None:
    _validate_sha_receipt(
        classification_bytes,
        expected_classification_sha256,
        code="classification_sha256_mismatch",
        label="classification",
    )
    if ledger.phase_a_classification_sha256 != expected_classification_sha256:
        _fail(
            "classification_sha256_mismatch",
            "ledger classification receipt differs from trusted input",
        )
    rows, binding = _classification_rows(classification_bytes)
    decision_by_source = {
        decision.source_id: decision
        for decision in ledger.decisions
    }
    if (
        len(rows) != 156
        or len(decision_by_source) != 156
        or set(rows) != set(decision_by_source)
    ):
        _fail(
            "classification_coverage_invalid",
            "decision ledger must exactly cover all 156 classification rows",
        )
    for source_id, decision in decision_by_source.items():
        if rows[source_id] != (decision.source_kind, decision.source_sha256):
            _fail(
                "classification_source_mismatch",
                f"{source_id}: decision differs from classification",
            )
    if (
        binding["engine_sha"] != ledger.engine_sha
        or binding["repo_head"] != ledger.repo_head
        or binding["corpus_fingerprint"] != ledger.corpus_fingerprint
    ):
        _fail(
            "classification_binding_mismatch",
            "classification binding differs from the decision ledger",
        )


def _artifact_transition_receipts(
    artifact: Mapping[str, object],
) -> _ArtifactTransitions:
    updates: dict[str, tuple[str, str]] = {}
    update_actions = artifact["updates"]
    if not isinstance(update_actions, list):
        _fail("manifest_invalid", "artifact updates must be a list")
    for action in update_actions:
        if not isinstance(action, dict) or set(action) != {
            "object_id",
            "path",
            "before_sha256",
            "after_sha256",
        }:
            _fail("manifest_invalid", "artifact updates row is invalid")
        object_id = action["object_id"]
        before_sha256 = action["before_sha256"]
        after_sha256 = action["after_sha256"]
        if (
            not _exact_nonempty_string(object_id)
            or not _exact_nonempty_string(action["path"])
            or not isinstance(before_sha256, str)
            or _SHA256.fullmatch(before_sha256) is None
            or not isinstance(after_sha256, str)
            or _SHA256.fullmatch(after_sha256) is None
            or object_id in updates
        ):
            _fail("manifest_invalid", "artifact updates receipt is invalid")
        assert isinstance(object_id, str)
        updates[object_id] = (before_sha256, after_sha256)

    renames: dict[str, tuple[str, str, str]] = {}
    rename_actions = artifact["renames"]
    if not isinstance(rename_actions, list):
        _fail("manifest_invalid", "artifact renames must be a list")
    for action in rename_actions:
        if not isinstance(action, dict) or set(action) != {
            "old_id",
            "new_id",
            "old_path",
            "new_path",
            "before_sha256",
            "after_sha256",
        }:
            _fail("manifest_invalid", "artifact renames row is invalid")
        source_id = action["old_id"]
        target_id = action["new_id"]
        before_sha256 = action["before_sha256"]
        after_sha256 = action["after_sha256"]
        if (
            not _exact_nonempty_string(source_id)
            or not _exact_nonempty_string(target_id)
            or source_id == target_id
            or not _exact_nonempty_string(action["old_path"])
            or not _exact_nonempty_string(action["new_path"])
            or not isinstance(before_sha256, str)
            or _SHA256.fullmatch(before_sha256) is None
            or not isinstance(after_sha256, str)
            or _SHA256.fullmatch(after_sha256) is None
            or source_id in renames
        ):
            _fail("manifest_invalid", "artifact renames receipt is invalid")
        assert isinstance(source_id, str)
        assert isinstance(target_id, str)
        renames[source_id] = (target_id, before_sha256, after_sha256)

    deletes: dict[str, str] = {}
    delete_actions = artifact["deletes"]
    if not isinstance(delete_actions, list):
        _fail("manifest_invalid", "artifact deletes must be a list")
    for action in delete_actions:
        if not isinstance(action, dict) or set(action) != {
            "object_id",
            "path",
            "before_sha256",
            "after_sha256",
        }:
            _fail("manifest_invalid", "artifact deletes row is invalid")
        source_id = action["object_id"]
        before_sha256 = action["before_sha256"]
        if (
            not _exact_nonempty_string(source_id)
            or not _exact_nonempty_string(action["path"])
            or not isinstance(before_sha256, str)
            or _SHA256.fullmatch(before_sha256) is None
            or action["after_sha256"] is not None
            or source_id in deletes
        ):
            _fail("manifest_invalid", "artifact deletes receipt is invalid")
        assert isinstance(source_id, str)
        deletes[source_id] = before_sha256
    if (
        set(updates) & set(renames)
        or set(updates) & set(deletes)
        or set(renames) & set(deletes)
    ):
        _fail("manifest_invalid", "artifact transition IDs overlap")
    return _ArtifactTransitions(
        updates=updates,
        renames=renames,
        deletes=deletes,
    )


def _artifact_pointer_value(obj: Mapping[str, object], pointer: str) -> object:
    current: object = obj
    for raw_token in pointer[1:].split("/"):
        token_parts: list[str] = []
        index = 0
        while index < len(raw_token):
            char = raw_token[index]
            if char != "~":
                token_parts.append(char)
                index += 1
                continue
            if (
                index + 1 >= len(raw_token)
                or raw_token[index + 1] not in {"0", "1"}
            ):
                raise ValueError("invalid artifact JSON pointer escape")
            token_parts.append("~" if raw_token[index + 1] == "0" else "/")
            index += 2
        token = "".join(token_parts)
        if isinstance(current, Mapping):
            if token not in current:
                raise KeyError(token)
            current = current[token]
        elif isinstance(current, list):
            if (
                not token.isdigit()
                or (len(token) > 1 and token.startswith("0"))
                or int(token) >= len(current)
            ):
                raise KeyError(token)
            current = current[int(token)]
        else:
            raise KeyError(token)
    return current


def id_renames_from_trusted_repair_receipt(
    *,
    decisions_bytes: bytes,
    expected_decisions_sha256: str,
    classification_bytes: bytes,
    expected_classification_sha256: str,
    canonical_manifest_bytes: bytes,
    expected_canonical_manifest_sha256: str,
    existing: BrainStore,
    intermediate_snapshot: SnapshotVerification,
) -> dict[str, str]:
    _validate_sha_receipt(
        decisions_bytes,
        expected_decisions_sha256,
        code="decision_ledger_sha256_mismatch",
        label="decision ledger",
    )
    ledger = decode_canonicalization_ledger(decisions_bytes)
    _validate_classification_receipt_for_ledger(
        ledger,
        classification_bytes=classification_bytes,
        expected_classification_sha256=expected_classification_sha256,
    )
    artifact = _parse_canonical_artifact(
        canonical_manifest_bytes,
        expected_canonical_manifest_sha256,
    )
    try:
        validate_snapshot_binding(intermediate_snapshot)
        validate_live_snapshot_corpus(existing, intermediate_snapshot)
    except MigrationError as exc:
        _migration_failure(exc)
    if (
        artifact["decision_ledger_sha256"] != expected_decisions_sha256
        or artifact["phase_a_classification_sha256"]
        != expected_classification_sha256
        or artifact["before_fingerprint"] != ledger.corpus_fingerprint
        or artifact["expected_after_fingerprint"]
        != intermediate_snapshot.corpus_fingerprint
        or artifact["engine_sha"] != ledger.engine_sha
        or ledger.engine_sha != intermediate_snapshot.engine_head
        or ledger.repo_head != intermediate_snapshot.repo_head
    ):
        _fail(
            "intermediate_receipt_mismatch",
            "canonical artifact and intermediate snapshot bindings differ",
        )
    expected_id_renames = id_renames_from_ledger(ledger)
    if artifact["id_renames"] != expected_id_renames:
        _fail(
            "intermediate_receipt_mismatch",
            "artifact pure ID rename map differs from the decision ledger",
        )
    repair_renames = canonical_repair_renames_from_ledger(ledger)
    merge_pairs = collision_merges_from_ledger(ledger)
    rows = artifact["rows"]
    if not isinstance(rows, list) or {
        row.get("source_id")
        for row in rows
        if isinstance(row, dict)
    } != set(repair_renames) | set(merge_pairs):
        _fail(
            "intermediate_receipt_mismatch",
            "artifact rows do not exactly cover canonical repairs",
        )
    transitions = _artifact_transition_receipts(artifact)
    rows_by_source = {
        row["source_id"]: row
        for row in rows
        if isinstance(row, dict)
    }
    for decision in ledger.decisions:
        if decision.source_id in merge_pairs:
            target_id = merge_pairs[decision.source_id]
            row = rows_by_source[decision.source_id]
            merge_receipt = row["merge_receipt"]
            assert isinstance(merge_receipt, dict)
            if (
                row["new_id"] != target_id
                or row["kind"] != decision.source_kind
                or row["reason_code"] != decision.action.value
                or merge_receipt["target_id"] != target_id
            ):
                _fail(
                    "intermediate_source_receipt_mismatch",
                    f"{decision.source_id}: merge row differs from ledger",
                )
            if existing.has(decision.source_id):
                _fail(
                    "intermediate_source_receipt_mismatch",
                    (
                        f"{decision.source_id}: merge source remains in "
                        "intermediate store"
                    ),
                )
            delete_sha256 = transitions.deletes.get(decision.source_id)
            if delete_sha256 is None:
                _fail(
                    "intermediate_source_receipt_mismatch",
                    f"{decision.source_id}: merge delete receipt is missing",
                )
            if (
                delete_sha256 != decision.source_sha256
                or delete_sha256
                != merge_receipt["source_delete_before_sha256"]
            ):
                _fail(
                    "intermediate_source_receipt_mismatch",
                    f"{decision.source_id}: merge delete receipt is invalid",
                )
            target_before_sha256 = merge_receipt["target_before_sha256"]
            target_after_sha256 = merge_receipt["target_after_sha256"]
            survivor_update = transitions.updates.get(target_id)
            if target_before_sha256 != target_after_sha256:
                if survivor_update is None:
                    _fail(
                        "intermediate_source_receipt_mismatch",
                        (
                            f"{decision.source_id}: merge survivor update "
                            "is missing"
                        ),
                    )
                target_before_sha256, target_after_sha256 = survivor_update
            elif survivor_update is not None:
                _fail(
                    "intermediate_source_receipt_mismatch",
                    (
                        f"{decision.source_id}: no-op merge survivor has "
                        "an update"
                    ),
                )
            live_target_sha256 = existing.source_sha256(target_id)
            if (
                target_before_sha256
                != merge_receipt["target_before_sha256"]
                or target_after_sha256
                != merge_receipt["target_after_sha256"]
                or live_target_sha256 != target_after_sha256
                or row["canonical_payload_hash"] != target_after_sha256
            ):
                _fail(
                    "intermediate_source_receipt_mismatch",
                    f"{decision.source_id}: merge survivor receipt is invalid",
                )
            reference_collapses = merge_receipt["reference_collapses"]
            assert isinstance(reference_collapses, list)
            for collapse in reference_collapses:
                assert isinstance(collapse, dict)
                referrer_id = collapse["object_id"]
                pointer = collapse["pointer"]
                try:
                    live_referrer = existing.get(referrer_id)
                    live_ids = _artifact_pointer_value(live_referrer, pointer)
                except (KeyError, ValueError):
                    live_ids = None
                if (
                    not isinstance(live_ids, list)
                    or live_ids != collapse["after_ids"]
                    or decision.source_id in live_ids
                ):
                    _fail(
                        "intermediate_source_receipt_mismatch",
                        (
                            f"{decision.source_id}: merge collapse live "
                            "receipt is invalid"
                        ),
                    )
            continue
        renamed = transitions.renames.get(decision.source_id)
        updated = transitions.updates.get(decision.source_id)
        transition = (
            renamed
            if renamed is not None
            else (
                (decision.source_id, *updated)
                if updated is not None
                else None
            )
        )
        if transition is None:
            if existing.source_sha256(decision.source_id) != decision.source_sha256:
                _fail(
                    "intermediate_source_receipt_mismatch",
                    f"{decision.source_id}: intermediate source receipt changed",
                )
            continue
        target_id, before_sha256, after_sha256 = transition
        if (
            before_sha256 != decision.source_sha256
            or existing.source_sha256(target_id) != after_sha256
        ):
            _fail(
                "intermediate_source_receipt_mismatch",
                f"{decision.source_id}: transition receipt is invalid",
            )
    return expected_id_renames
