"""CodeLocator와 짝 EvidenceRef의 표시 제목 계약."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import PurePosixPath

from project_brain.hash_utils import stable_json


def canonical_locator_title(locator: Mapping[str, object]) -> str:
    """locator의 결정론적인 표시 제목을 반환한다."""
    symbol = locator.get("symbol")
    if isinstance(symbol, str) and symbol:
        return symbol
    path = locator.get("path")
    basename = (
        PurePosixPath(path).name
        if isinstance(path, str) and path
        else "unknown"
    )
    object_id = locator.get("id")
    anchor_key = (
        object_id.rsplit(".", 1)[-1]
        if isinstance(object_id, str) and object_id
        else "unknown"
    )
    return f"{basename}:{anchor_key}"


def paired_code_locator_id(obj: Mapping[str, object]) -> str | None:
    """실제 code-locator EvidenceRef 모양이면 locator ID를 반환한다."""
    if (
        obj.get("kind") != "EvidenceRef"
        or obj.get("ref_type") != "code_locator"
    ):
        return None
    locator = obj.get("locator")
    if not isinstance(locator, Mapping):
        return None
    value = locator.get("code_locator_id")
    return value if isinstance(value, str) and value else None


def non_title_sha256(obj: Mapping[str, object]) -> str:
    """title을 제외한 JSON payload의 안정적인 SHA-256을 반환한다."""
    payload = {key: value for key, value in obj.items() if key != "title"}
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()
