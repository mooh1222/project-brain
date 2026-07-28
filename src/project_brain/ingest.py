"""범용 적재 진입점.

제품 쓰기는 모두 :class:`MutationService`의 검증·transaction 경계를 통과한다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from project_brain.mutation import (
    MutationOperation,
    MutationRequest,
    MutationService,
)
from project_brain.repo_context import RepoContext


class IngestError(RuntimeError):
    pass


def ingest(
    brain_root: Path,
    objects: Sequence[dict],
    preconditions: Mapping[str, str] | None = None,
    *,
    engine_sha: str,
    repo_context: RepoContext | None = None,
    operation: MutationOperation = MutationOperation.INGEST,
):
    """한 bundle을 공통 mutation service로 원자 적용한다."""
    inputs = tuple(objects)
    request = MutationRequest(
        operation=operation,
        brain_root=Path(brain_root),
        repo_context=repo_context,
        engine_sha=engine_sha,
        objects=inputs,
        preconditions=preconditions or {},
    )
    result = MutationService().apply(inputs, request=request)
    if not result.ok:
        detail = result.detail or "mutation failed"
        code = f"{result.error_code}: " if result.error_code else ""
        raise IngestError(f"{code}{detail}")
    return result
