"""C/C++ quote와 symbol AST 관계 검증 테스트."""

from __future__ import annotations

import unittest

from project_brain.symbol_verify import (
    SymbolStatus,
    is_canonical_symbol_shape,
    verify_symbol_relation,
)


class CanonicalSymbolShapeTest(unittest.TestCase):
    def test_accepts_only_canonical_c_cpp_identifier_segments(self):
        for symbol in ("run", "Ns::Widget::run", "Widget::~Widget"):
            with self.subTest(symbol=symbol):
                self.assertTrue(is_canonical_symbol_shape(symbol))

        for symbol in (
            "",
            None,
            "Ns::",
            "Ns::run / descriptive",
            "Ns::operator==",
            "함수 설명",
        ):
            with self.subTest(symbol=symbol):
                self.assertFalse(is_canonical_symbol_shape(symbol))


class VerifySymbolRelationTest(unittest.TestCase):
    def _verify(self, *, source: str, quote: str, symbol: str, path: str = "src/example.cpp"):
        blob = source.encode("utf-8")
        quote_bytes = quote.encode("utf-8")
        start = blob.index(quote_bytes)
        return verify_symbol_relation(
            path=path,
            blob=blob,
            quote_start=start,
            quote_end=start + len(quote_bytes),
            symbol=symbol,
        )

    def test_qualified_method_requires_scope_and_leaf(self):
        result = self._verify(
            source="void Foo::bar() { return; }\n",
            quote="void Foo::bar() { return; }",
            symbol="Foo::bar",
        )

        self.assertEqual(result.status, SymbolStatus.VERIFIED)
        self.assertEqual(result.canonical_symbol, "Foo::bar")

    def test_qualified_method_rejects_wrong_scope(self):
        result = self._verify(
            source="void Other::bar() { return; }\n",
            quote="void Other::bar() { return; }",
            symbol="Foo::bar",
        )

        self.assertEqual(result.status, SymbolStatus.MISMATCH)

    def test_template_arguments_are_not_counted_as_scope_segments(self):
        result = self._verify(
            source="void Foo<T>::bar() { return; }\n",
            quote="void Foo<T>::bar() { return; }",
            symbol="Foo::bar",
        )

        self.assertEqual(result.status, SymbolStatus.VERIFIED)

    def test_template_argument_name_cannot_forge_a_scope_segment(self):
        result = self._verify(
            source="void Foo<T>::bar() { return; }\n",
            quote="void Foo<T>::bar() { return; }",
            symbol="Foo::T::bar",
        )

        self.assertEqual(result.status, SymbolStatus.MISMATCH)

    def test_unknown_qualified_structure_requires_manual_verification(self):
        result = self._verify(
            source="void A::template B<T>::bar() { return; }\n",
            quote="void A::template B<T>::bar() { return; }",
            symbol="A::B::bar",
        )

        self.assertEqual(result.status, SymbolStatus.UNSUPPORTED)

    def test_class_scope_and_leaf_are_verified_for_member_declaration(self):
        result = self._verify(
            source="class Foo { void bar(); };\n",
            quote="void bar();",
            symbol="Foo::bar",
        )

        self.assertEqual(result.status, SymbolStatus.VERIFIED)

    def test_cpp17_nested_namespace_segments_verify_function_scope(self):
        result = self._verify(
            source="namespace A::B { void run() {} }\n",
            quote="void run() {}",
            symbol="A::B::run",
        )

        self.assertEqual(result.status, SymbolStatus.VERIFIED)

    def test_cpp17_nested_namespace_segments_verify_class_member_scope(self):
        result = self._verify(
            source="namespace A::B { class Foo { void bar(); }; }\n",
            quote="void bar();",
            symbol="A::B::Foo::bar",
        )

        self.assertEqual(result.status, SymbolStatus.VERIFIED)

    def test_enum_or_constant_requires_identifier_boundary(self):
        verified = self._verify(
            source="enum class State { READY, READING };\n",
            quote="READY",
            symbol="READY",
        )
        substring = self._verify(
            source="enum class State { READY, READING };\n",
            quote="READY",
            symbol="READ",
        )

        self.assertEqual(verified.status, SymbolStatus.VERIFIED)
        self.assertEqual(substring.status, SymbolStatus.MISMATCH)

    def test_unqualified_function_identifier_is_verified(self):
        result = self._verify(
            source="int compute_value(int input) { return input + 1; }\n",
            quote="int compute_value(int input) { return input + 1; }",
            symbol="compute_value",
        )

        self.assertEqual(result.status, SymbolStatus.VERIFIED)

    def test_quote_must_contain_qualified_leaf_identifier_boundary(self):
        result = self._verify(
            source="void Foo::bar() { return; }\n",
            quote=":",
            symbol="Foo::bar",
        )

        self.assertEqual(result.status, SymbolStatus.MISMATCH)

    def test_quote_must_contain_unqualified_identifier_boundary(self):
        result = self._verify(
            source="int compute_value() { return 1; }\n",
            quote="c",
            symbol="compute_value",
        )

        self.assertEqual(result.status, SymbolStatus.MISMATCH)

    def test_overlapping_parse_error_or_missing_node_is_unsupported(self):
        cases = (
            ("void compute_value( {}", "void compute_value( {}"),
            (
                "int compute_value() { return ;",
                "int compute_value() { return ;",
            ),
        )
        for source, quote in cases:
            with self.subTest(source=source):
                result = self._verify(
                    source=source,
                    quote=quote,
                    symbol="compute_value",
                )
                self.assertEqual(result.status, SymbolStatus.UNSUPPORTED)

    def test_old_descriptive_symbol_does_not_auto_pass(self):
        for symbol in ("Foo::bar / legacy", "Foo::bar (예전 이름)", "함수 설명"):
            with self.subTest(symbol=symbol):
                result = self._verify(
                    source="void Foo::bar() { return; }\n",
                    quote="void Foo::bar() { return; }",
                    symbol=symbol,
                )
                self.assertEqual(result.status, SymbolStatus.MISMATCH)

    def test_operator_symbol_requires_structured_manual_verification(self):
        result = self._verify(
            source="class Foo { bool operator==(const Foo&) const; };\n",
            quote="bool operator==(const Foo&) const;",
            symbol="Foo::operator==",
        )

        self.assertEqual(result.status, SymbolStatus.UNSUPPORTED)

    def test_unsupported_extension_is_explicit(self):
        result = verify_symbol_relation(
            path="tools/example.py",
            blob=b"def run(): pass\n",
            quote_start=0,
            quote_end=len(b"def run(): pass"),
            symbol="run",
        )

        self.assertEqual(result.status, SymbolStatus.UNSUPPORTED)
        self.assertEqual(result.evidence, "unsupported extension")


_BODY_SOURCE = """\
float Settings::getValue(std::string key) {
\tstd::string raw = lookup(key);
\tif (raw.empty()) {
\t\treturn 0;
\t}
\treturn parse(raw);
}
"""


class EnclosingBodyRelationTest(unittest.TestCase):
    """인용문이 심볼 이름을 담지 않아도 그 심볼의 몸통 안이면 관계가 성립한다."""

    def _verify(self, *, source: str, quote: str, symbol: str, path: str = "src/example.cpp"):
        blob = source.encode("utf-8")
        quote_bytes = quote.encode("utf-8")
        start = blob.index(quote_bytes)
        return verify_symbol_relation(
            path=path,
            blob=blob,
            quote_start=start,
            quote_end=start + len(quote_bytes),
            symbol=symbol,
        )

    def test_quote_inside_function_body_verifies_by_enclosing_definition(self):
        result = self._verify(
            source=_BODY_SOURCE,
            quote="if (raw.empty()) {",
            symbol="Settings::getValue",
        )

        self.assertEqual(result.status, SymbolStatus.VERIFIED)
        self.assertEqual(result.canonical_symbol, "Settings::getValue")

    def test_enclosing_body_rule_rejects_wrong_symbol(self):
        result = self._verify(
            source=_BODY_SOURCE,
            quote="if (raw.empty()) {",
            symbol="Settings::otherValue",
        )

        self.assertEqual(result.status, SymbolStatus.MISMATCH)

    def test_enclosing_body_rule_ignores_signature_overlap(self):
        """시그니처를 스치는 조각은 몸통 밖이라 규칙이 걸리지 않는다."""
        qualified = self._verify(
            source="void Foo::bar() { return; }\n",
            quote=":",
            symbol="Foo::bar",
        )
        unqualified = self._verify(
            source="int compute_value() { return 1; }\n",
            quote="c",
            symbol="compute_value",
        )

        self.assertEqual(qualified.status, SymbolStatus.MISMATCH)
        self.assertEqual(unqualified.status, SymbolStatus.MISMATCH)

    def test_enclosing_body_rule_handles_in_class_method_definition(self):
        result = self._verify(
            source=(
                "class Widget {\n"
                "\tvoid draw() {\n"
                "\t\tint count = 0;\n"
                "\t\tpaint(count);\n"
                "\t}\n"
                "};\n"
            ),
            quote="int count = 0;",
            symbol="Widget::draw",
        )

        self.assertEqual(result.status, SymbolStatus.VERIFIED)

    def test_enclosing_body_rule_handles_anonymous_namespace_free_function(self):
        result = self._verify(
            source=(
                "namespace {\n"
                "\tint compute(int a) {\n"
                "\t\tint doubled = a * 2;\n"
                "\t\treturn doubled;\n"
                "\t}\n"
                "}\n"
            ),
            quote="int doubled = a * 2;",
            symbol="compute",
        )

        self.assertEqual(result.status, SymbolStatus.VERIFIED)

    def test_enclosing_body_rule_prefers_innermost_definition(self):
        source = (
            "void outer() {\n"
            "\tstruct Helper {\n"
            "\t\tvoid run() {\n"
            "\t\t\tint v = 1;\n"
            "\t\t}\n"
            "\t};\n"
            "}\n"
        )

        innermost = self._verify(source=source, quote="int v = 1;", symbol="Helper::run")
        outermost = self._verify(source=source, quote="int v = 1;", symbol="outer")

        self.assertEqual(innermost.status, SymbolStatus.VERIFIED)
        self.assertEqual(outermost.status, SymbolStatus.MISMATCH)


if __name__ == "__main__":
    unittest.main()
