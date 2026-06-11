import json
from collections import defaultdict
from pathlib import Path
from typing import Any


class BrainStore:
    def __init__(self, objects: dict[str, dict[str, Any]]):
        self._objects = objects
        self._by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for obj in objects.values():
            self._by_kind[obj.get("kind", "")].append(obj)

    @classmethod
    def load(cls, brain_root: Path) -> "BrainStore":
        objects: dict[str, dict[str, Any]] = {}
        for path in sorted(brain_root.rglob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            object_id = payload["id"]
            objects[object_id] = payload
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
    def save_object(cls, brain_root: Path, obj: dict) -> Path:
        """schema 검증 통과 후 kind별 디렉토리에 <id>.json으로 쓴다. id는 호출자 책임."""
        from project_brain.schema import validate_object, SchemaError
        errors = validate_object(obj)
        if errors:
            raise SchemaError("; ".join(errors))
        rel = cls._KIND_DIR[obj["kind"]]
        path = Path(brain_root) / rel / f"{obj['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
