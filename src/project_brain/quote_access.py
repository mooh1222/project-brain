"""CodeLocator 원문 인용구의 공개 가능 상태를 판정한다."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from project_brain.store import BrainStore


class AccessState(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class QuoteAccess:
    redaction: AccessState
    principal_acl: AccessState
    final: AccessState


def _reverse_evidence_refs(
    locator_id: str,
    store: BrainStore,
) -> tuple[Mapping[str, object], ...]:
    refs = []
    for ref in store.by_kind("EvidenceRef"):
        locator = ref.get("locator")
        if (
            isinstance(locator, Mapping)
            and locator.get("code_locator_id") == locator_id
        ):
            refs.append(ref)
    return tuple(sorted(refs, key=lambda ref: str(ref.get("id", ""))))


def _combine(states: list[AccessState]) -> AccessState:
    if not states:
        return AccessState.INDETERMINATE
    if AccessState.DENY in states:
        return AccessState.DENY
    if all(state is AccessState.ALLOW for state in states):
        return AccessState.ALLOW
    return AccessState.INDETERMINATE


def evaluate_quote_access(
    locator_id: str,
    store: BrainStore,
    *,
    principal: object | None,
    acl_evaluator: Callable[
        [object, Mapping[str, object]],
        AccessState,
    ] | None,
) -> QuoteAccess:
    refs = _reverse_evidence_refs(locator_id, store)
    if not refs:
        return QuoteAccess(
            AccessState.INDETERMINATE,
            AccessState.INDETERMINATE,
            AccessState.INDETERMINATE,
        )

    manifests: list[Mapping[str, object] | None] = []
    redaction_states: list[AccessState] = []
    for ref in refs:
        manifest_id = ref.get("evidence_manifest_id")
        manifest = (
            store.get(manifest_id)
            if isinstance(manifest_id, str) and store.has(manifest_id)
            else None
        )
        if manifest is None or manifest.get("kind") != "EvidenceManifest":
            manifests.append(None)
            redaction_states.append(AccessState.INDETERMINATE)
            continue
        manifests.append(manifest)
        redaction_states.append(
            AccessState.ALLOW
            if manifest.get("redaction_status") == "approved"
            else AccessState.DENY
        )

    redaction = _combine(redaction_states)
    acl_states: list[AccessState] = []
    for manifest in manifests:
        if (
            manifest is None
            or principal is None
            or acl_evaluator is None
        ):
            acl_states.append(AccessState.INDETERMINATE)
            continue
        try:
            evaluated = acl_evaluator(principal, manifest)
            acl_states.append(AccessState(evaluated))
        except (Exception, ValueError):
            acl_states.append(AccessState.INDETERMINATE)
    principal_acl = _combine(acl_states)

    if AccessState.DENY in {redaction, principal_acl}:
        final = AccessState.DENY
    elif (
        redaction is AccessState.ALLOW
        and principal_acl is AccessState.ALLOW
    ):
        final = AccessState.ALLOW
    else:
        final = AccessState.INDETERMINATE
    return QuoteAccess(redaction, principal_acl, final)
