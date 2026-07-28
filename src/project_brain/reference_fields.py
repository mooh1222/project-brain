"""Brain 객체 사이 참조 필드의 단일 registry와 비파괴 rewrite."""

from collections.abc import Iterator, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectRef:
    pointer: str
    object_id: str


SCALAR_REFERENCE_FIELDS: frozenset[str] = frozenset({
    "context_id",
    "derived_from_event_id",
    "evidence_manifest_id",
    "review_record_id",
    "source_object_id",
    "spec_document_id",
    "spec_revision_id",
    "supersedes",
    "target_object_id",
})

LIST_REFERENCE_FIELDS: frozenset[str] = frozenset({
    "affected_context_ids",
    "affected_glossary_term_ids",
    "affected_mapping_ids",
    "code_locator_ids",
    "decision_record_ids",
    "evidence_refs",
    "glossary_term_ids",
    "related_objects",
    "slack_thread_ids",
    "source_event_ids",
    "source_fact_ids",
    "source_object_ids",
    "spec_revision_ids",
    "supersedes_mapping_ids",
    "target_object_ids",
    "vouched_by_mapping_ids",
})

NESTED_REFERENCE_POINTERS: tuple[str, ...] = (
    "/locator/code_locator_id",
)


class _NonCanonicalArrayIndexError(ValueError):
    """등록 경로가 malformed 객체의 list를 만났을 때만 구분해 건너뛰기 위한 내부 오류."""


def _escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _unescape_pointer_token(token: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(token):
        char = token[index]
        if char != "~":
            decoded.append(char)
            index += 1
            continue
        if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
            raise ValueError(f"invalid JSON pointer escape in token {token!r}")
        decoded.append("~" if token[index + 1] == "0" else "/")
        index += 2
    return "".join(decoded)


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/"):
        raise ValueError(f"JSON pointer must start with '/': {pointer!r}")
    return tuple(_unescape_pointer_token(token) for token in pointer[1:].split("/"))


def _canonical_array_index(token: str) -> int:
    if token == "0":
        return 0
    if (
        not token
        or token[0] not in "123456789"
        or any(char not in "0123456789" for char in token[1:])
    ):
        raise _NonCanonicalArrayIndexError(
            f"JSON pointer array index must be canonical decimal, got {token!r}"
        )
    return int(token)


def _resolve_pointer(
    obj: Mapping[str, object],
    pointer: str,
) -> tuple[bool, object | None]:
    current: object = obj
    for token in _pointer_tokens(pointer):
        if isinstance(current, Mapping):
            if token not in current:
                return False, None
            current = current[token]
        elif isinstance(current, list):
            index = _canonical_array_index(token)
            if index < 0 or index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _value_at_pointer(obj: Mapping[str, object], pointer: str) -> object | None:
    found, value = _resolve_pointer(obj, pointer)
    return value if found else None


def _set_value_at_pointer(obj: dict, pointer: str, value: str) -> None:
    tokens = _pointer_tokens(pointer)
    current: object = obj
    for token in tokens[:-1]:
        if isinstance(current, MutableMapping):
            current = current[token]
        elif isinstance(current, list):
            current = current[_canonical_array_index(token)]
        else:  # pragma: no cover - iter_object_refs가 만든 pointer라 도달 불가
            raise TypeError(f"cannot traverse JSON pointer {pointer!r}")

    final = tokens[-1]
    if isinstance(current, MutableMapping):
        current[final] = value
    elif isinstance(current, list):
        current[_canonical_array_index(final)] = value
    else:  # pragma: no cover - iter_object_refs가 만든 pointer라 도달 불가
        raise TypeError(f"cannot set JSON pointer {pointer!r}")


def iter_object_refs(obj: Mapping[str, object]) -> Iterator[ObjectRef]:
    """실제 Brain 객체 참조만 RFC 6901 JSON pointer와 함께 순회한다."""
    for field in sorted(SCALAR_REFERENCE_FIELDS):
        value = obj.get(field)
        if isinstance(value, str):
            yield ObjectRef(f"/{_escape_pointer_token(field)}", value)

    for field in sorted(LIST_REFERENCE_FIELDS):
        value = obj.get(field)
        if not isinstance(value, list):
            continue
        escaped_field = _escape_pointer_token(field)
        for index, item in enumerate(value):
            if isinstance(item, str):
                yield ObjectRef(f"/{escaped_field}/{index}", item)

    for pointer in NESTED_REFERENCE_POINTERS:
        try:
            value = _value_at_pointer(obj, pointer)
        except _NonCanonicalArrayIndexError:
            continue
        if isinstance(value, str):
            yield ObjectRef(pointer, value)


def rewrite_object_refs(
    obj: Mapping[str, object],
    replacements: Mapping[str, str],
) -> tuple[dict, tuple[ObjectRef, ...]]:
    """registry 참조만 바꾼 독립 복사본과 실제 변경 위치·이전 ID를 반환한다."""
    for key, value in replacements.items():
        if not isinstance(key, str):
            raise TypeError("replacement keys must be strings")
        if not isinstance(value, str):
            raise TypeError("replacement values must be strings")

    rewritten = deepcopy(dict(obj))
    changed: list[ObjectRef] = []
    for ref in iter_object_refs(obj):
        replacement = replacements.get(ref.object_id)
        if replacement is None or replacement == ref.object_id:
            continue
        _set_value_at_pointer(rewritten, ref.pointer, replacement)
        changed.append(ref)

    return rewritten, tuple(sorted(changed, key=lambda ref: ref.pointer))
