"""범용 조립 코어 — 구조화 노트 → brain 객체 묶음.

판정은 에이전트(노트 작성), 변환은 기계적(이 모듈). supersede/강등/충돌 해소/이력
판정은 하지 않는다. objbase.base 위에 kind별 변환 + refs + updates + 2층 검증을 얹는다.
저장은 절대 안 한다 — build()는 객체 묶음 + diff만 반환하고 ingest가 저장한다.
"""
from project_brain.objbase import base

# id 파생 규칙 (kind → prefix). 컨벤션: g.<ctx>.<key> / mapping.<ctx>.<key> 등.
_ID_PREFIX = {
    "GlossaryTerm": "g",
    "DomainMapping": "mapping",
    "CodeLocator": "code",
    "EvidenceRef": "evref",
    "DecisionRecord": "decision",
    "DomainContext": "context",
}


def derive_id(kind, ctx, key):
    """kind+컨텍스트+key로 객체 id를 만든다. 규칙은 _ID_PREFIX 고정."""
    return f"{_ID_PREFIX[kind]}.{ctx}.{key}"


def build_glossary_terms(notes, now):
    """노트의 glossary[] 항목을 reviewed GlossaryTerm 객체로 변환한다."""
    ctx = notes["context"]["key"]
    out = []
    for g in notes.get("glossary", []):
        obj = {
            "id": derive_id("GlossaryTerm", ctx, g["key"]),
            "kind": "GlossaryTerm",
            "status": "reviewed",
            "truth_role": "domain",
            "title": g["key"],
            "context_id": f"context.{ctx}",
            "term": g["term"],
            "definition": g["definition"],
            "evidence_refs": g.get("evidence_refs", []),
        }
        out.append(base(obj, tags=[ctx], created_at=now, updated_at=now, poc_priority="P2"))
    return out
