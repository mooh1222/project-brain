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
from project_brain.coverage import BuildArtifactBinding
from project_brain.repo_context import RepoContext
from project_brain.transaction_receipt import BatchBinding


class IngestError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        error_details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.detail = detail
        self.error_details = dict(error_details or {})
        super().__init__(f"{code}: {detail}" if code else detail)

    def as_dict(self) -> dict[str, object]:
        return {
            "error_code": self.code,
            "error": self.detail,
            "error_details": dict(self.error_details),
        }


def ingest(
    brain_root: Path,
    objects: Sequence[dict],
    preconditions: Mapping[str, str] | None = None,
    *,
    engine_sha: str,
    coverage: Mapping[str, object] | None = None,
    build_binding: BuildArtifactBinding | Mapping[str, object] | None = None,
    repo_context: RepoContext | None = None,
    operation: MutationOperation = MutationOperation.INGEST,
    expected_corpus_fingerprint: str | None = None,
    batch_binding: BatchBinding | None = None,
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
        expected_corpus_fingerprint=expected_corpus_fingerprint,
        batch_binding=batch_binding,
        coverage=coverage,
        build_binding=build_binding,
    )
    result = MutationService().apply(inputs, request=request)
    if not result.ok:
        raise IngestError(
            result.error_code or "mutation_failed",
            result.detail or "mutation failed",
            result.error_details,
        )
    return result
