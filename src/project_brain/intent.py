from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedQuery:
    original_query: str
    canonical_query: str
    avoided_terms: list[str]


@dataclass(frozen=True)
class ClassifiedQuery:
    normalized: NormalizedQuery
    intents: list[str]


def normalize_terms(query: str, avoid_map: dict[str, str] | None = None) -> NormalizedQuery:
    avoid_map = avoid_map or {}
    canonical = query
    avoided: list[str] = []
    for avoided_term, canonical_term in avoid_map.items():
        if avoided_term in canonical:
            avoided.append(avoided_term)
            canonical = canonical.replace(avoided_term, canonical_term)
    return NormalizedQuery(original_query=query, canonical_query=canonical, avoided_terms=avoided)


def classify_query(query: str, avoid_map: dict[str, str] | None = None) -> ClassifiedQuery:
    normalized = normalize_terms(query, avoid_map)
    text = normalized.canonical_query
    intents: list[str] = []

    if "왜" in text or "이유" in text or "바뀌" in text:
        intents.append("why_changed")
    if "현재" in text or "지금" in text or "QA 기준" in text:
        intents.append("current_status")
    if "그때" in text or "당시" in text or "as-of" in text:
        intents.append("as_of_history")
    if (
        "어디 구현" in text
        or "어디서 구현" in text
        or "어디에 구현" in text
        or "어느 함수" in text
        or "drawEventCluster" in text
    ):
        intents.append("implementation_location")
    if "무슨 뜻" in text or "용어" in text:
        intents.append("glossary_meaning")
    if "근거" in text or "누가 확정" in text or "출처" in text:
        intents.append("evidence_provenance")

    if "why_changed" in intents and "current_status" in intents:
        intents = ["why_changed", "current_status"] + [
            intent for intent in intents if intent not in {"why_changed", "current_status"}
        ]

    if not intents:
        intents.append("unknown")

    return ClassifiedQuery(normalized=normalized, intents=intents)
