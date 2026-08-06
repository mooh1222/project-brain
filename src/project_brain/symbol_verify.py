"""CodeLocator quote와 C/C++ symbol 관계 검증."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from tree_sitter import Language, Node, Parser
import tree_sitter_cpp

_SUPPORTED_EXTENSIONS = frozenset({".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp"})
_IDENTIFIER_TYPES = frozenset({
    "identifier",
    "field_identifier",
    "namespace_identifier",
    "type_identifier",
    "destructor_name",
})
_QUALIFIED_TYPES = frozenset({
    "qualified_identifier",
    "scoped_identifier",
})
_LEXICAL_SCOPE_TYPES = frozenset({
    "namespace_definition",
    "class_specifier",
    "struct_specifier",
    "union_specifier",
    "enum_specifier",
})
_DECLARATOR_WRAPPERS = frozenset({
    "function_declarator",
    "pointer_declarator",
    "reference_declarator",
    "parenthesized_declarator",
})
_SIMPLE_IDENTIFIER = re.compile(r"~?[A-Za-z_][A-Za-z0-9_]*\Z")


def is_canonical_symbol_shape(symbol: object) -> bool:
    """symbol이 정규 C/C++ 식별자 segment만으로 이뤄졌는지 반환한다."""
    if not isinstance(symbol, str) or not symbol:
        return False
    return all(
        _SIMPLE_IDENTIFIER.fullmatch(segment)
        for segment in symbol.split("::")
    )


class SymbolStatus(StrEnum):
    VERIFIED = "verified"
    MANUAL_VERIFIED = "manual_verified"
    MISMATCH = "mismatch"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class SymbolVerification:
    status: SymbolStatus
    canonical_symbol: str
    evidence: str


def verify_symbol_relation(
    *,
    path: str,
    blob: bytes,
    quote_start: int,
    quote_end: int,
    symbol: str,
) -> SymbolVerification:
    extension = PurePosixPath(path).suffix.lower()
    if extension not in _SUPPORTED_EXTENSIONS:
        return SymbolVerification(SymbolStatus.UNSUPPORTED, symbol, "unsupported extension")

    if (
        not isinstance(blob, bytes)
        or not isinstance(quote_start, int)
        or not isinstance(quote_end, int)
        or quote_start < 0
        or quote_start >= quote_end
        or quote_end > len(blob)
    ):
        return SymbolVerification(
            SymbolStatus.MISMATCH,
            symbol,
            "invalid quote byte range",
        )
    if not isinstance(symbol, str) or not symbol:
        return SymbolVerification(SymbolStatus.MISMATCH, str(symbol), "empty symbol")

    segments = tuple(symbol.split("::"))
    if not is_canonical_symbol_shape(symbol):
        if (
            any(segment.startswith("operator") for segment in segments)
            and all(
                _SIMPLE_IDENTIFIER.fullmatch(segment)
                or (
                    segment.startswith("operator")
                    and segment.isascii()
                    and not any(character.isspace() for character in segment)
                    and "/" not in segment
                )
                for segment in segments
            )
        ):
            return SymbolVerification(
                SymbolStatus.UNSUPPORTED,
                symbol,
                "operator symbol requires manual verification",
            )
        return SymbolVerification(
            SymbolStatus.MISMATCH,
            symbol,
            "symbol is not a canonical C/C++ identifier",
        )

    parser = Parser(Language(tree_sitter_cpp.language()))
    root = parser.parse(blob).root_node
    nodes = tuple(_iter_nodes(root))
    if any(
        _syntax_problem_overlaps(node, quote_start, quote_end)
        for node in nodes
    ):
        return SymbolVerification(
            SymbolStatus.UNSUPPORTED,
            symbol,
            "C/C++ parse ERROR or MISSING node overlaps quote byte range",
        )
    unsupported_qualified_structure = False

    for node in nodes:
        if not _overlaps(node, quote_start, quote_end):
            continue
        if len(segments) > 1 and node.type in _QUALIFIED_TYPES:
            qualified_segments = _qualified_identifier_segments(node, blob)
            if qualified_segments is None:
                unsupported_qualified_structure = True
            elif (
                qualified_segments == segments
                and _quote_contains_node(
                    _qualified_leaf(node),
                    quote_start,
                    quote_end,
                )
            ):
                return SymbolVerification(
                    SymbolStatus.VERIFIED,
                    symbol,
                    f"{node.type} spans quote byte range",
                )
        if node.type not in _IDENTIFIER_TYPES:
            continue
        if _node_text(node, blob) != segments[-1]:
            continue
        if not _quote_contains_node(node, quote_start, quote_end):
            continue
        if len(segments) == 1:
            return SymbolVerification(
                SymbolStatus.VERIFIED,
                symbol,
                f"{node.type} boundary spans quote byte range",
            )
        lexical_scope = _lexical_scope_segments(node, blob)
        if lexical_scope is None:
            unsupported_qualified_structure = True
        elif lexical_scope == segments[:-1]:
            return SymbolVerification(
                SymbolStatus.VERIFIED,
                symbol,
                "lexical scope and identifier boundary span quote byte range",
            )

    if _enclosing_body_segments(root, blob, quote_start, quote_end) == segments:
        return SymbolVerification(
            SymbolStatus.VERIFIED,
            symbol,
            "enclosing function definition body spans quote byte range",
        )

    if unsupported_qualified_structure:
        return SymbolVerification(
            SymbolStatus.UNSUPPORTED,
            symbol,
            "C/C++ AST structure could not establish a canonical scope",
        )
    return SymbolVerification(
        SymbolStatus.MISMATCH,
        symbol,
        "no matching C/C++ identifier relation overlaps quote byte range",
    )


def _enclosing_body_segments(
    root: Node,
    blob: bytes,
    start: int,
    end: int,
) -> tuple[str, ...] | None:
    """quote를 **몸통 안에** 통째로 담는 가장 안쪽 함수 정의의 canonical segments.

    시그니처에 걸친 quote는 몸통 밖이므로 이 규칙이 걸리지 않는다 — 식별자 조각
    하나로 symbol 라벨을 참이라 주장하는 것을 계속 막는다.
    """
    innermost: Node | None = None
    innermost_body_start = -1
    for node in _iter_nodes(root):
        if node.type != "function_definition":
            continue
        body = node.child_by_field_name("body")
        if body is None:
            continue
        if body.start_byte <= start and end <= body.end_byte:
            if body.start_byte > innermost_body_start:
                innermost = node
                innermost_body_start = body.start_byte
    if innermost is None:
        return None
    return _function_definition_segments(innermost, blob)


def _function_definition_segments(
    node: Node,
    blob: bytes,
) -> tuple[str, ...] | None:
    declarator = node.child_by_field_name("declarator")
    while declarator is not None and declarator.type in _DECLARATOR_WRAPPERS:
        declarator = declarator.child_by_field_name("declarator")
    if declarator is None:
        return None
    if declarator.type in _QUALIFIED_TYPES:
        return _qualified_identifier_segments(declarator, blob)
    if declarator.type not in _IDENTIFIER_TYPES:
        return None
    lexical_scope = _lexical_scope_segments(declarator, blob)
    if lexical_scope is None:
        return None
    return (*lexical_scope, _node_text(declarator, blob))


def _iter_nodes(root: Node):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _overlaps(node: Node, start: int, end: int) -> bool:
    return node.start_byte < end and start < node.end_byte


def _syntax_problem_overlaps(node: Node, start: int, end: int) -> bool:
    if node.type == "ERROR":
        return _overlaps(node, start, end)
    return node.is_missing and start <= node.start_byte <= end


def _quote_contains_node(node: Node | None, start: int, end: int) -> bool:
    return node is not None and start <= node.start_byte and node.end_byte <= end


def _node_text(node: Node, blob: bytes) -> str:
    return blob[node.start_byte:node.end_byte].decode("utf-8", errors="strict")


def _qualified_identifier_segments(
    node: Node,
    blob: bytes,
) -> tuple[str, ...] | None:
    if node.type not in _QUALIFIED_TYPES:
        return None
    scope = node.child_by_field_name("scope")
    name = node.child_by_field_name("name")
    if scope is None or name is None:
        return None
    scope_segments = _scope_segments(scope, blob)
    name_segments = _name_segments(name, blob)
    if scope_segments is None or name_segments is None:
        return None
    return (*scope_segments, *name_segments)


def _scope_segments(node: Node, blob: bytes) -> tuple[str, ...] | None:
    if node.type in _IDENTIFIER_TYPES:
        return (_node_text(node, blob),)
    if node.type in _QUALIFIED_TYPES:
        return _qualified_identifier_segments(node, blob)
    if node.type == "template_type":
        name = node.child_by_field_name("name")
        if name is None:
            return None
        return _name_segments(name, blob)
    return None


def _name_segments(node: Node, blob: bytes) -> tuple[str, ...] | None:
    if node.type in _IDENTIFIER_TYPES:
        return (_node_text(node, blob),)
    if node.type in _QUALIFIED_TYPES:
        return _qualified_identifier_segments(node, blob)
    return None


def _qualified_leaf(node: Node) -> Node | None:
    name = node.child_by_field_name("name")
    while name is not None and name.type in _QUALIFIED_TYPES:
        name = name.child_by_field_name("name")
    if name is None or name.type not in _IDENTIFIER_TYPES:
        return None
    return name


def _lexical_scope_segments(
    node: Node,
    blob: bytes,
) -> tuple[str, ...] | None:
    scopes: list[str] = []
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type in _LEXICAL_SCOPE_TYPES:
            name = ancestor.child_by_field_name("name")
            if name is not None:
                name_segments = _lexical_scope_name_segments(name, blob)
                if name_segments is None:
                    return None
                scopes.extend(reversed(name_segments))
        ancestor = ancestor.parent
    scopes.reverse()
    return tuple(scopes)


def _lexical_scope_name_segments(
    name: Node,
    blob: bytes,
) -> tuple[str, ...] | None:
    if name.type in _IDENTIFIER_TYPES:
        return (_node_text(name, blob),)
    if name.type == "nested_namespace_specifier":
        children = tuple(
            _node_text(child, blob)
            for child in name.named_children
            if child.type == "namespace_identifier"
        )
        if len(children) == len(name.named_children):
            return children
    return None
