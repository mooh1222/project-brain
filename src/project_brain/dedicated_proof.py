"""종류별 전용 증거를 mutation 요청과 현재 source에 결속한다."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from project_brain.hash_utils import (
    source_content_hash,
    stable_json,
    verification_content_hash,
)
from project_brain.store import BrainStore
from project_brain.write_semantics import ObjectActionKind


ProofStatus = Literal["ready", "unverified", "stale", "blocked"]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ACTOR_KEYS = frozenset({"kind", "id", "version"})
_RECEIPT_KEYS = frozenset({"kind", "id"})
_SUPPORTED_ACTIONS = frozenset({
    ObjectActionKind.CREATE,
    ObjectActionKind.UPDATE,
    ObjectActionKind.NO_CHANGE,
})
_REASON_ORDER = (
    "proof_missing",
    "proof_shape_invalid",
    "profile_mismatch",
    "target_mismatch",
    "action_mismatch",
    "subject_changed",
    "sources_changed",
    "inputs_changed",
    "execution_invalid",
)


@dataclass(frozen=True)
class DedicatedProofMaterial:
    sources: tuple[Mapping[str, str], ...]
    inputs: Mapping[str, object]


@dataclass(frozen=True)
class DedicatedProofContext:
    brain_root: Path | None
    store: BrainStore
    before: Mapping[str, object] | None
    after: Mapping[str, object]
    action: ObjectActionKind
    receipt: Mapping[str, object]


@dataclass(frozen=True)
class DedicatedProof:
    version: int
    target_id: str
    profile_id: str
    profile_version: int
    action: str
    subject_sha256: str
    sources: tuple[Mapping[str, str], ...]
    inputs: Mapping[str, object]
    producer: Mapping[str, str]
    verifiers: tuple[Mapping[str, str], ...]
    receipt: Mapping[str, object]
    proof_sha256: str


@dataclass(frozen=True)
class DedicatedProofProfile:
    id: str
    version: int
    subject_kind: str
    selector: Callable[[Mapping[str, object]], bool]
    materialize: Callable[[DedicatedProofContext], DedicatedProofMaterial]
    receipt_kinds: frozenset[str]
    minimum_verifiers: int = 0
    execution_problems: Callable[
        [DedicatedProofContext, DedicatedProof],
        tuple[str, ...],
    ] = lambda _context, _proof: ()


@dataclass(frozen=True)
class DedicatedProofEvaluation:
    proof_status: ProofStatus
    reason_codes: tuple[str, ...]


def _actor_key(actor: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        str(actor.get("kind", "")),
        str(actor.get("id", "")),
        str(actor.get("version", "")),
    )


def _actor_valid(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and frozenset(value) == _ACTOR_KEYS
        and all(
            isinstance(value.get(key), str) and bool(value.get(key))
            for key in _ACTOR_KEYS
        )
    )


def dedicated_proof_dict(proof: DedicatedProof) -> dict[str, object]:
    """manifest와 unstamped intent가 공유하는 exact JSON 표현."""
    return {
        "version": proof.version,
        "target_id": proof.target_id,
        "profile": {
            "id": proof.profile_id,
            "version": proof.profile_version,
        },
        "action": proof.action,
        "subject_sha256": proof.subject_sha256,
        "sources": [dict(row) for row in proof.sources],
        "inputs": deepcopy(dict(proof.inputs)),
        "execution": {
            "producer": dict(proof.producer),
            "verifiers": [dict(verifier) for verifier in proof.verifiers],
            "receipt": deepcopy(dict(proof.receipt)),
        },
        "proof_sha256": proof.proof_sha256,
    }


def _proof_identity(proof: DedicatedProof) -> str:
    payload = dedicated_proof_dict(proof)
    payload.pop("proof_sha256")
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


def _subject_sha256(subject: Mapping[str, object]) -> str:
    return verification_content_hash(subject, direct_evidence_fields=())


def semantic_source_bindings(
    subject: Mapping[str, object],
    store: BrainStore,
    *,
    fields: Sequence[str],
) -> tuple[Mapping[str, str], ...]:
    """등록된 source ID 필드를 현재 의미 hash 행으로 바꾼다."""
    rows: list[dict[str, str]] = []
    for field in fields:
        raw_ids = subject.get(field)
        if not isinstance(raw_ids, list):
            raise ValueError(f"{field} must be an array")
        for index, source_id in enumerate(raw_ids):
            if not isinstance(source_id, str) or not source_id:
                raise ValueError(f"{field}[{index}] must be a non-empty string")
            if not store.has(source_id):
                raise ValueError(f"source object is missing: {source_id}")
            rows.append({
                "pointer": f"/{field}/{index}",
                "source_id": source_id,
                "content_sha256": source_content_hash([store.get(source_id)]),
            })
    return tuple(sorted(rows, key=lambda row: (row["pointer"], row["source_id"])))


def builtin_dedicated_proof_profiles() -> tuple[DedicatedProofProfile, ...]:
    """서로 다른 task 소유 profile 모듈을 충돌 없이 합친다."""
    from project_brain.dedicated_proof_capture import CAPTURE_PROFILES
    from project_brain.dedicated_proof_derived import DERIVED_PROFILES

    profiles = tuple(CAPTURE_PROFILES) + tuple(DERIVED_PROFILES)
    ids = [profile.id for profile in profiles]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate dedicated proof profile id")
    return tuple(sorted(profiles, key=lambda profile: profile.id))


def dedicated_proof_profile(
    subject: Mapping[str, object],
    *,
    profiles: Sequence[DedicatedProofProfile] | None = None,
) -> DedicatedProofProfile | None:
    selected_profiles = (
        tuple(profiles)
        if profiles is not None
        else builtin_dedicated_proof_profiles()
    )
    matches = tuple(
        profile
        for profile in selected_profiles
        if subject.get("kind") == profile.subject_kind
        and profile.selector(subject)
    )
    if len(matches) > 1:
        raise RuntimeError("multiple dedicated proof profiles match subject")
    return matches[0] if matches else None


def _shape_problems(
    proof: DedicatedProof,
    *,
    profile: DedicatedProofProfile,
) -> tuple[str, ...]:
    problems: list[str] = []
    if proof.version != 1:
        problems.append("dedicated proof version must be 1")
    if not isinstance(proof.target_id, str) or not proof.target_id:
        problems.append("dedicated proof target_id is invalid")
    if proof.profile_id != profile.id or proof.profile_version != profile.version:
        problems.append("dedicated proof profile does not match subject")
    if proof.action not in {action.value for action in _SUPPORTED_ACTIONS}:
        problems.append("dedicated proof action is invalid")
    if _SHA256.fullmatch(proof.subject_sha256) is None:
        problems.append("dedicated proof subject_sha256 is invalid")
    normalized_sources: list[tuple[str, str, str]] = []
    for index, row in enumerate(proof.sources):
        if not isinstance(row, Mapping) or frozenset(row) != frozenset({
            "pointer", "source_id", "content_sha256",
        }):
            problems.append(f"dedicated proof sources[{index}] keys must be exact")
            continue
        values = tuple(row.get(key) for key in (
            "pointer", "source_id", "content_sha256",
        ))
        if (
            not all(isinstance(value, str) and value for value in values)
            or _SHA256.fullmatch(str(values[2])) is None
        ):
            problems.append(f"dedicated proof sources[{index}] is invalid")
            continue
        normalized_sources.append((str(values[0]), str(values[1]), str(values[2])))
    if (
        normalized_sources != sorted(normalized_sources)
        or len(normalized_sources) != len(set(normalized_sources))
    ):
        problems.append("dedicated proof sources must be sorted and unique")
    if not isinstance(proof.inputs, Mapping):
        problems.append("dedicated proof inputs must be an object")
    if not _actor_valid(proof.producer):
        problems.append("dedicated proof producer is invalid")
    if not all(_actor_valid(verifier) for verifier in proof.verifiers):
        problems.append("dedicated proof verifiers are invalid")
    elif (
        [_actor_key(verifier) for verifier in proof.verifiers]
        != sorted(_actor_key(verifier) for verifier in proof.verifiers)
        or len({_actor_key(verifier) for verifier in proof.verifiers})
        != len(proof.verifiers)
    ):
        problems.append("dedicated proof verifiers must be sorted and unique")
    if (
        not isinstance(proof.receipt, Mapping)
        or not _RECEIPT_KEYS.issubset(proof.receipt)
        or proof.receipt.get("kind") not in profile.receipt_kinds
        or not isinstance(proof.receipt.get("id"), str)
        or _SHA256.fullmatch(str(proof.receipt.get("id"))) is None
    ):
        problems.append("dedicated proof receipt is invalid")
    if (
        not isinstance(proof.proof_sha256, str)
        or _SHA256.fullmatch(proof.proof_sha256) is None
        or proof.proof_sha256 != _proof_identity(proof)
    ):
        problems.append("dedicated proof proof_sha256 is invalid")
    return tuple(problems)


def _execution_problems(
    context: DedicatedProofContext,
    profile: DedicatedProofProfile,
    proof: DedicatedProof,
) -> tuple[str, ...]:
    problems: list[str] = []
    if len(proof.verifiers) < profile.minimum_verifiers:
        problems.append(
            f"dedicated proof requires at least {profile.minimum_verifiers} verifier(s)"
        )
    problems.extend(profile.execution_problems(context, proof))
    return tuple(problems)


def prepare_dedicated_proof(
    after: Mapping[str, object],
    store: BrainStore,
    *,
    brain_root: Path | None = None,
    before: Mapping[str, object] | None,
    action: ObjectActionKind,
    producer: Mapping[str, str],
    verifiers: Sequence[Mapping[str, str]],
    receipt: Mapping[str, object],
    profile: DedicatedProofProfile | None = None,
    profiles: Sequence[DedicatedProofProfile] | None = None,
) -> DedicatedProof:
    selected = profile or dedicated_proof_profile(after, profiles=profiles)
    if selected is None:
        raise ValueError("subject has no dedicated proof profile")
    if after.get("status") != "reviewed":
        raise ValueError("dedicated proof requires reviewed subject")
    if action not in _SUPPORTED_ACTIONS:
        raise ValueError("dedicated proof action is invalid")
    context = DedicatedProofContext(
        brain_root=brain_root,
        store=store,
        before=before,
        after=after,
        action=action,
        receipt=receipt,
    )
    material = selected.materialize(context)
    sorted_verifiers = tuple(sorted(
        (dict(verifier) for verifier in verifiers),
        key=_actor_key,
    ))
    proof = DedicatedProof(
        version=1,
        target_id=str(after.get("id", "")),
        profile_id=selected.id,
        profile_version=selected.version,
        action=action.value,
        subject_sha256=_subject_sha256(after),
        sources=tuple(dict(row) for row in material.sources),
        inputs=deepcopy(dict(material.inputs)),
        producer=dict(producer),
        verifiers=sorted_verifiers,
        receipt=deepcopy(dict(receipt)),
        proof_sha256="0" * 64,
    )
    proof = DedicatedProof(
        **{
            **proof.__dict__,
            "proof_sha256": _proof_identity(proof),
        }
    )
    evaluation = evaluate_dedicated_proof(
        proof,
        brain_root=brain_root,
        store=store,
        before=before,
        after=after,
        action=action,
        profile=selected,
    )
    if evaluation.proof_status != "ready":
        raise ValueError("; ".join(evaluation.reason_codes))
    return proof


def evaluate_dedicated_proof(
    proof: DedicatedProof | None,
    *,
    store: BrainStore,
    before: Mapping[str, object] | None,
    after: Mapping[str, object],
    action: ObjectActionKind,
    brain_root: Path | None = None,
    profile: DedicatedProofProfile | None = None,
    profiles: Sequence[DedicatedProofProfile] | None = None,
) -> DedicatedProofEvaluation:
    selected = profile or dedicated_proof_profile(after, profiles=profiles)
    if selected is None:
        raise ValueError("subject has no dedicated proof profile")
    reasons: set[str] = set()
    if proof is None:
        reasons.add("proof_missing")
    elif not isinstance(proof, DedicatedProof):
        reasons.add("proof_shape_invalid")
    else:
        if _shape_problems(proof, profile=selected):
            reasons.add("proof_shape_invalid")
        if (proof.profile_id, proof.profile_version) != (
            selected.id,
            selected.version,
        ):
            reasons.add("profile_mismatch")
        if proof.target_id != after.get("id"):
            reasons.add("target_mismatch")
        if proof.action != action.value:
            reasons.add("action_mismatch")
        if proof.subject_sha256 != _subject_sha256(after):
            reasons.add("subject_changed")
        context = DedicatedProofContext(
            brain_root=brain_root,
            store=store,
            before=before,
            after=after,
            action=action,
            receipt=proof.receipt,
        )
        try:
            material = selected.materialize(context)
        except (KeyError, TypeError, ValueError):
            reasons.add("sources_changed")
        else:
            if proof.sources != tuple(dict(row) for row in material.sources):
                reasons.add("sources_changed")
            if dict(proof.inputs) != dict(material.inputs):
                reasons.add("inputs_changed")
        if _execution_problems(context, selected, proof):
            reasons.add("execution_invalid")
    ordered = tuple(reason for reason in _REASON_ORDER if reason in reasons)
    if not ordered:
        status: ProofStatus = "ready"
    elif set(ordered) == {"proof_missing"}:
        status = "unverified"
    elif any(
        reason in {
            "proof_shape_invalid",
            "profile_mismatch",
            "target_mismatch",
            "action_mismatch",
            "execution_invalid",
        }
        for reason in ordered
    ):
        status = "blocked"
    else:
        status = "stale"
    return DedicatedProofEvaluation(status, ordered)
