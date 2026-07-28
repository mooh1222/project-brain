import json
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class StoreLoadError(RuntimeError):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        paths: tuple[Path, ...] = (),
    ):
        self.code = code
        self.detail = detail
        self.paths = paths
        super().__init__(f"{code}: {detail}")


class BrainStore:
    def __init__(self, objects: dict[str, dict[str, Any]]):
        self._objects = objects
        self._by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for obj in objects.values():
            self._by_kind[obj.get("kind", "")].append(obj)

    @classmethod
    def load(cls, brain_root: Path) -> "BrainStore":
        from project_brain.corpus_io import (
            assert_corpus_readable,
            corpus_lock,
        )

        with corpus_lock(brain_root, exclusive=False):
            assert_corpus_readable(brain_root)
            return cls.load_unlocked(brain_root)

    @classmethod
    def load_unlocked(cls, brain_root: Path) -> "BrainStore":
        """Load while the caller already owns the appropriate corpus lock."""
        from project_brain.corpus_io import (
            CorpusIOError,
            read_tracked_json_files,
        )

        # 객체 디렉토리(_KIND_DIR)만 스캔한다 — brain root에는 비객체 JSON
        # (eval_scenarios.json, raw/sources/ 자료 등)이 같이 살 수 있고, 객체는
        # 항상 save_object가 _KIND_DIR 아래에 쓰므로 스캔도 같은 경계를 따른다.
        try:
            files = read_tracked_json_files(
                brain_root,
                set(cls._KIND_DIR.values()),
            )
        except (CorpusIOError, OSError) as exc:
            root = Path(brain_root)
            raise StoreLoadError(
                "object_scan_failed",
                f"could not scan tracked object directories: {exc}",
                paths=getattr(exc, "paths", ()) or (root,),
            ) from exc
        objects: dict[str, dict[str, Any]] = {}
        object_paths: dict[str, Path] = {}
        for path, data in files:
            try:
                text = data.decode("utf-8")
            except UnicodeError as exc:
                raise StoreLoadError(
                    "object_read_failed",
                    f"could not read tracked object JSON {path}: {exc}",
                    paths=(path,),
                ) from exc
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise StoreLoadError(
                    "object_json_invalid",
                    f"tracked object JSON is invalid at {path}: {exc}",
                    paths=(path,),
                ) from exc
            if not isinstance(payload, dict):
                raise StoreLoadError(
                    "object_payload_invalid",
                    f"tracked object JSON must contain an object: {path}",
                    paths=(path,),
                )
            object_id = payload.get("id")
            if not isinstance(object_id, str) or not object_id:
                raise StoreLoadError(
                    "object_id_invalid",
                    f"tracked object requires a non-empty string id: {path}",
                    paths=(path,),
                )
            kind = payload.get("kind")
            if not isinstance(kind, str) or not kind:
                raise StoreLoadError(
                    "object_kind_invalid",
                    f"tracked object requires a non-empty string kind: {path}",
                    paths=(path,),
                )
            previous_path = object_paths.get(object_id)
            if previous_path is not None:
                raise StoreLoadError(
                    "duplicate_existing_object_id",
                    (
                        f"duplicate payload id {object_id!r} in "
                        f"{previous_path} and {path}"
                    ),
                    paths=(previous_path, path),
                )
            objects[object_id] = payload
            object_paths[object_id] = path
        return cls(objects)

    def get(self, object_id: str) -> dict[str, Any]:
        return self._objects[object_id]

    def has(self, object_id: str) -> bool:
        return object_id in self._objects

    def by_kind(self, kind: str) -> list[dict[str, Any]]:
        return list(self._by_kind.get(kind, []))

    def all(self) -> list[dict[str, Any]]:
        return list(self._objects.values())

    # kind → brain root 기준 상대 디렉토리 (storage §4 layout)
    _KIND_DIR = {
        "EvidenceManifest": "raw/manifests",
        "EvidenceRef": "objects/evidence_refs",
        "ReviewRecord": "objects/reviews",
        "EventLedgerRecord": "objects/ledger",
        "TemporalFact": "objects/facts",
        "CodeLocator": "objects/code",
        "DomainContext": "objects/domain",
        "GlossaryTerm": "objects/domain",
        "DomainMapping": "objects/mappings",
        "Insight": "objects/insights",
        "DecisionRecord": "objects/decisions",
        "ContextProjection": "indexes/context_projections",
        "KnowledgePage": "views/knowledge",
        "IndexRecord": "indexes/records",
        "CurrentView": "views/current",
        "SpecDocument": "objects/specs",
        "SpecRevision": "objects/specs",
        "SlideRef": "objects/specs",
        "SlackThread": "objects/comms",
    }

    @classmethod
    def object_path(cls, brain_root: Path, obj: Mapping[str, object]) -> Path:
        return (
            Path(brain_root)
            / cls._KIND_DIR[str(obj["kind"])]
            / f"{obj['id']}.json"
        )

    @staticmethod
    def object_bytes(obj: Mapping[str, object]) -> bytes:
        return (
            json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8")

    @classmethod
    def save_object(cls, brain_root: Path, obj: dict) -> Path:
        """schema 검증 통과 후 kind별 디렉토리에 <id>.json으로 쓴다. id는 호출자 책임."""
        from project_brain.schema import validate_object, SchemaError
        errors = validate_object(obj)
        if errors:
            raise SchemaError("; ".join(errors))
        path = cls.object_path(brain_root, obj)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(cls.object_bytes(obj))
        return path
