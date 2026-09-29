"""Expected pivot bindings: declared, extracted from the RDF, and equal.

Two independent things are asserted for every fixture:

1. ``binding_tree`` deserialises to a :class:`fhir_sulo.contracts.BindingNode`
   whose ``tuples_for_scope`` gives exactly the declared ``expected_multiset``.
   This is the call Agent 3 and Agent 4 will make, so the artifact is proven to
   be usable in the form the acceptance test needs.
2. Running the fixture's ``extraction`` spec over the *committed canonical
   N-Triples* gives the same multiset. This is what stops the expected tuples
   from being an unchecked assertion about a graph nobody looked at.

The blood-pressure case is spelled out separately with its literal values,
because it is the concept note's headline requirement.
"""

from __future__ import annotations

import os
import unittest

from . import _support
from ._support import FIXTURES, cases, read

from fhir_sulo.ingest import bindings as B  # noqa: E402
from fhir_sulo.ingest.ntriples import parse  # noqa: E402

XSD = "http://www.w3.org/2001/XMLSchema#"


def _doc(family, case):
    return B.load(os.path.join(FIXTURES, family, case, "expected-bindings.json"))


def _graph(family, case, name="canonical.nt"):
    return parse(read(os.path.join(FIXTURES, family, case, name)))


class TestEveryFixture(unittest.TestCase):
    def test_declared_tuples_match_the_binding_tree(self):
        n = 0
        for case_dir, _ in cases():
            doc = B.load(os.path.join(case_dir, "expected-bindings.json"))
            tree = B.load_binding_tree(doc)
            for assertion in B.scope_assertions(doc):
                with self.subTest(fixture=doc["fixture_id"],
                                  variables=assertion["variables"]):
                    got = sorted(tree.tuples_for_scope(
                        assertion["scope"], assertion["variables"]))
                    self.assertEqual(got, B.expected_multiset(assertion))
                    n += 1
        self.assertGreater(n, 20)

    def test_declared_tuples_match_what_the_rdf_actually_contains(self):
        for case_dir, _ in cases():
            doc = B.load(os.path.join(case_dir, "expected-bindings.json"))
            triples = parse(read(os.path.join(case_dir, "canonical.nt")))
            got = B.extract(doc, triples)
            for assertion in B.scope_assertions(doc):
                with self.subTest(fixture=doc["fixture_id"],
                                  variables=assertion["variables"]):
                    rows = got[assertion["scope"]]
                    extracted = sorted(
                        tuple(r.get(v, "") for v in assertion["variables"]) for r in rows)
                    self.assertEqual(extracted, B.expected_multiset(assertion))

    def test_forbidden_tuples_are_absent(self):
        for case_dir, _ in cases():
            doc = B.load(os.path.join(case_dir, "expected-bindings.json"))
            tree = B.load_binding_tree(doc)
            for assertion in B.scope_assertions(doc):
                forbidden = B.forbidden_multiset(assertion)
                if not forbidden:
                    continue
                got = set(tree.tuples_for_scope(assertion["scope"], assertion["variables"]))
                with self.subTest(fixture=doc["fixture_id"]):
                    self.assertEqual(got & set(forbidden), set())

    def test_every_fixture_declares_at_least_one_scope_assertion(self):
        for case_dir, _ in cases():
            doc = B.load(os.path.join(case_dir, "expected-bindings.json"))
            with self.subTest(fixture=doc["fixture_id"]):
                self.assertTrue(B.scope_assertions(doc))
                for a in B.scope_assertions(doc):
                    self.assertTrue(a["expected_multiset"])


class TestBloodPressureMultiset(unittest.TestCase):
    """Concept note section 5 / plan Gate 3, spelled out.

    The required answer is {(bp-1, 120, 80), (bp-2, 105, 70)}. A graph that
    produces (bp-1, 120, 70) fails even though every individual value appears.
    """

    REQUIRED = sorted([("bp-1", "120", "80"), ("bp-2", "105", "70")])
    CROSS_JOIN = ("bp-1", "120", "70")

    def _tuples(self, case, rdf="canonical.nt"):
        doc = _doc("bp", case)
        rows = B.extract(doc, _graph("bp", case, rdf))["panel"]
        return sorted(tuple(r[v] for v in ("panel", "sys", "dia")) for r in rows)

    def test_baseline_multiset_is_exact(self):
        self.assertEqual(self._tuples("bp-two-panels"), self.REQUIRED)

    def test_cross_join_is_not_produced(self):
        self.assertNotIn(self.CROSS_JOIN, self._tuples("bp-two-panels"))

    def test_a_membership_check_would_not_have_caught_the_cross_join(self):
        """Why the assertion is a multiset comparison and not 'all values present'."""
        crossed = sorted([("bp-1", "120", "70"), ("bp-2", "105", "80")])
        all_values = {v for t in crossed for v in t}
        self.assertEqual(all_values, {v for t in self.REQUIRED for v in t})
        self.assertNotEqual(crossed, self.REQUIRED)

    def test_reordered_serialisation_is_the_same_graph_and_the_same_tuples(self):
        canonical = set(_graph("bp", "bp-reordered-serialisation", "canonical.nt"))
        reordered_text = read(os.path.join(
            FIXTURES, "bp", "bp-reordered-serialisation", "canonical-reordered.nt"))
        reordered = set(parse(reordered_text))
        self.assertEqual(canonical, reordered, "the reordered file is a different graph")
        self.assertNotEqual(
            [l for l in reordered_text.splitlines() if l and not l.startswith("#")],
            sorted(l for l in reordered_text.splitlines() if l and not l.startswith("#")),
            "the reordered file is in canonical order, so it tests nothing",
        )
        self.assertEqual(self._tuples("bp-reordered-serialisation"), self.REQUIRED)
        self.assertEqual(
            self._tuples("bp-reordered-serialisation", "canonical-reordered.nt"),
            self.REQUIRED)

    def test_reversed_component_arrays_change_the_graph_but_not_the_tuples(self):
        canonical = set(_graph("bp", "bp-reordered-serialisation", "canonical.nt"))
        reversed_g = set(_graph("bp", "bp-reordered-serialisation",
                                "canonical-components-reversed.nt"))
        self.assertNotEqual(canonical, reversed_g,
                            "reversing the component arrays must move fhir:index")
        self.assertEqual(
            self._tuples("bp-reordered-serialisation", "canonical-components-reversed.nt"),
            self.REQUIRED,
            "components must be selected by LOINC code, not by position",
        )

    def test_an_omitted_component_leaves_a_hole_rather_than_borrowing(self):
        got = self._tuples("bp-component-omitted")
        self.assertEqual(got, sorted([("bp-1", "120", ""), ("bp-2", "105", "70")]))
        self.assertNotIn(("bp-1", "120", "70"), got)
        self.assertNotIn(("bp-1", "120", "80"), got)

    def test_duplicate_values_across_panels_stay_two_tuples(self):
        got = self._tuples("bp-duplicate-values")
        self.assertEqual(got, sorted([("bp-3", "120", "80"), ("bp-4", "120", "80")]))
        self.assertEqual(len(got), 2, "identical-valued panels must not coalesce")

    def test_another_patients_panel_does_not_mix_in(self):
        doc = _doc("bp", "bp-other-patient")
        rows = B.extract(doc, _graph("bp", "bp-other-patient"))["panel"]
        by_subject = {r["subjectRef"]: (r["panel"], r["sys"], r["dia"]) for r in rows}
        self.assertEqual(by_subject["Patient/p123"], ("bp-1", "120", "80"))
        self.assertEqual(by_subject["Patient/p999"], ("bp-5", "200", "110"))


class TestEgfrAndEncounterBindings(unittest.TestCase):
    def test_egfr_baseline_tuple(self):
        doc = _doc("egfr", "egfr-baseline")
        rows = B.extract(doc, _graph("egfr", "egfr-baseline"))["observation"]
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["obsId"], "egfr-456")
        self.assertEqual(r["status"], "final")
        self.assertEqual(r["code"], "33914-3")
        self.assertEqual(r["codeSystem"], "http://loinc.org")
        self.assertEqual(r["subjectRef"], "Patient/p123")
        self.assertEqual(r["value"], "55.0^^" + XSD + "decimal")
        self.assertEqual(r["unitCode"], "mL/min/{1.73_m2}")
        self.assertEqual(r["effective"], "2026-09-02T14:00:00Z^^" + XSD + "dateTime")
        self.assertEqual(r["comparator"], "")

    def test_egfr_comparator_is_bound_not_dropped(self):
        doc = _doc("egfr", "egfr-comparator")
        r = B.extract(doc, _graph("egfr", "egfr-comparator"))["observation"][0]
        self.assertEqual(r["comparator"], "<")
        self.assertEqual(r["value"], "55.0^^" + XSD + "decimal")

    def test_egfr_absent_value_binds_nothing_rather_than_zero(self):
        doc = _doc("egfr", "egfr-data-absent-reason")
        r = B.extract(doc, _graph("egfr", "egfr-data-absent-reason"))["observation"][0]
        self.assertEqual(r["value"], "")
        self.assertEqual(r["absentReason"], "not-performed")

    def test_encounter_baseline_tuple(self):
        doc = _doc("encounter", "enc-baseline")
        r = B.extract(doc, _graph("encounter", "enc-baseline"))["encounter"][0]
        self.assertEqual(r["encId"], "enc-9")
        self.assertEqual(r["status"], "finished")
        self.assertEqual(r["subjectRef"], "Patient/p123")
        self.assertEqual(r["participantRef"], "Practitioner/c7")
        self.assertEqual(r["start"], "2026-09-02T14:00:00Z^^" + XSD + "dateTime")
        self.assertEqual(r["end"], "2026-09-02T14:30:00Z^^" + XSD + "dateTime")

    def test_open_period_binds_no_end(self):
        doc = _doc("encounter", "enc-open-period")
        r = B.extract(doc, _graph("encounter", "enc-open-period"))["encounter"][0]
        self.assertEqual(r["start"], "2026-09-02T14:00:00Z^^" + XSD + "dateTime")
        self.assertEqual(r["end"], "", "an unknown endpoint must not be invented")


class TestExtractionCanFail(unittest.TestCase):
    """The extractor must be able to report a wrong graph, not just agree."""

    def test_a_corrupted_value_changes_the_extracted_tuple(self):
        doc = _doc("bp", "bp-two-panels")
        text = read(os.path.join(FIXTURES, "bp", "bp-two-panels", "canonical.nt"))
        mutated = text.replace('"80"^^', '"70"^^', 1)
        self.assertNotEqual(mutated, text)
        rows = B.extract(doc, parse(mutated))["panel"]
        got = sorted(tuple(r[v] for v in ("panel", "sys", "dia")) for r in rows)
        self.assertNotEqual(got, TestBloodPressureMultiset.REQUIRED)
        self.assertIn(("bp-1", "120", "70"), got)

    def test_a_variable_binding_twice_is_refused(self):
        """Two systolic components in one panel would hide a cross-join."""
        doc = _doc("bp", "bp-two-panels")
        text = read(os.path.join(FIXTURES, "bp", "bp-two-panels", "canonical.nt"))
        # Duplicate bp-1's systolic component under a second blank node.
        lines = [l for l in text.splitlines() if l and not l.startswith("#")]
        clone = [l.replace("bp-1-b", "bp-1-z") for l in lines if "bp-1-b" in l]
        merged = lines + [l for l in clone if l not in lines]
        self.assertGreater(len(merged), len(lines))
        with self.assertRaises(B.BindingSpecError):
            B.extract(doc, parse("\n".join(merged)))


if __name__ == "__main__":
    unittest.main()
