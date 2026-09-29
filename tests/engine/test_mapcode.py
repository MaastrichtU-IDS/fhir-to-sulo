"""Map-code classification: does the linter read a code exactly as the engine does?

Every divergence between these two readings is a silent wrong graph, so the
cases here are the ones where the engine is surprising rather than the ones
where it is obvious.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "src"))

from fhir_sulo.engine.mapcode import CodeKind, parse_map_code  # noqa: E402

PREFIXES = {"v": "https://w3id.org/fhir-sulo/var#", "bp": "http://bp.example/"}


def code(raw, prefixes=None):
    return parse_map_code(raw, PREFIXES if prefixes is None else prefixes)


class TestPlainVariables(unittest.TestCase):
    def test_prefixed_name(self):
        result = code(" v:status ")
        self.assertEqual(result.kind, CodeKind.VARIABLE)
        self.assertEqual(result.variables, ("https://w3id.org/fhir-sulo/var#status",))
        self.assertTrue(result.is_valid)

    def test_absolute_iri(self):
        self.assertEqual(code("<http://x/y>").variables, ("http://x/y",))

    def test_undeclared_prefix_is_rejected(self):
        self.assertFalse(code(" nope:status ").is_valid)

    def test_empty_iri_is_rejected(self):
        """`<>` parses and then binds nothing, so the engine deletes the shape."""
        result = code(" <> ")
        self.assertFalse(result.is_valid)
        self.assertEqual(result.variables, ())


class TestPythonJavaScriptDivergence(unittest.TestCase):
    r"""Python's ``$`` matches before a trailing newline; JavaScript's does not.

    With ``$`` the linter would call ``" v:name \n"`` a valid variable while
    the engine calls it an unrecognised code and prunes the branch. The
    patterns use ``\Z`` so that the two agree.
    """

    def test_a_trailing_newline_makes_it_unparseable_as_the_engine_sees_it(self):
        result = code(" v:status \n")
        self.assertEqual(result.kind, CodeKind.UNPARSEABLE)
        self.assertFalse(result.is_valid)


class TestKnownFunctions(unittest.TestCase):
    def test_hashmap_reports_its_variable(self):
        result = code(' hashmap(v:status, {"F": "final"}) ')
        self.assertEqual(result.function, "hashmap")
        self.assertEqual(result.variables, ("https://w3id.org/fhir-sulo/var#status",))
        self.assertTrue(result.is_valid)

    def test_regex_reports_every_capture_group(self):
        """The form the shipped BPdam fixture uses. It survives the variable
        pattern only because of the space after the comma."""
        result = code(" regex(/(?<bp:family>[a-zA-Z]+), (?<bp:given>[a-zA-Z]+)/) ")
        self.assertTrue(result.is_valid, result.problem)
        self.assertEqual(sorted(result.variables),
                         ["http://bp.example/family", "http://bp.example/given"])

    def test_regex_with_no_capture_group_binds_nothing(self):
        self.assertFalse(code(" regex(/[a-z]+/) ").is_valid)

    def test_test_is_accepted_and_binds_nothing(self):
        result = code(" test() ")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.variables, ())


class TestUnknownFunctions(unittest.TestCase):
    """CD-1, both routes."""

    def test_no_colon_reaches_the_function_dispatcher(self):
        result = code(" skolemize(x) ")
        self.assertEqual(result.kind, CodeKind.FUNCTION)
        self.assertFalse(result.is_valid)
        self.assertIn("skolemize", result.problem)

    def test_a_colon_makes_it_a_variable_before_it_is_ever_a_function(self):
        """`id(v:x)` never reaches the dispatcher. The message has to explain
        that, or the author is left wondering what prefix `id(v` is."""
        result = code(" id(v:x) ")
        self.assertEqual(result.kind, CodeKind.VARIABLE)
        self.assertFalse(result.is_valid)
        self.assertIn("variable pattern first", result.problem)
        self.assertIn("'id'", result.problem)

    def test_even_a_known_function_is_rejected_when_it_hits_that_trap(self):
        """`regex(/(?<v:a>x)/)` with no internal space matches the variable
        pattern, so the engine mishandles it too. Flagging it is agreement
        with the engine, not over-strictness."""
        result = code("regex(/(?<v:a>x)/)")
        self.assertFalse(result.is_valid)
        self.assertIn("variable pattern first", result.problem)


class TestUnparseable(unittest.TestCase):
    def test_empty_code(self):
        self.assertFalse(code("   ").is_valid)

    def test_garbage(self):
        self.assertFalse(code(" not a code at all ").is_valid)


if __name__ == "__main__":
    unittest.main()
