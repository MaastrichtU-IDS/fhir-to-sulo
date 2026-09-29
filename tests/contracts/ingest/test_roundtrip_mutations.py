"""Proof that the round-trip test can fail.

A test that cannot fail is worthless. This module takes the committed canonical
N-Triples of a fixture, applies one targeted corruption, and requires the
round trip to notice - either by raising, or by producing a JSON that differs
from the source.

Each mutation names the acceptance-matrix facet it attacks:

    "All mapped fields, cardinalities, codes, comparators, statuses, and
     temporal precision survive."  - plan section 5, "Source fidelity"

Every case asserts the substitution actually applied, so a mutation that
silently became a no-op fails loudly instead of passing vacuously.
"""

from __future__ import annotations

import os
import unittest

from . import _support
from ._support import FIXTURES, read

from fhir_sulo.ingest import jsonio, to_json  # noqa: E402
from fhir_sulo.ingest.ntriples import parse  # noqa: E402
from fhir_sulo.ingest.rdf_to_fhir import InverseError  # noqa: E402

XSD = "http://www.w3.org/2001/XMLSchema#"

EGFR = ("egfr", "egfr-baseline")
CMP = ("egfr", "egfr-comparator")
BP = ("bp", "bp-two-panels")
ENC = ("encounter", "enc-baseline")


def _load(family, case):
    src_dir = os.path.join(FIXTURES, family, case)
    with open(os.path.join(src_dir, "case.json"), encoding="utf-8") as fh:
        import json
        meta = json.load(fh)
    original = jsonio.loads(read(os.path.join(src_dir, meta["sources"][0])))
    nt = read(os.path.join(src_dir, "canonical.nt"))
    return original, nt


class _MutationCase(unittest.TestCase):
    def assert_detected(self, family, case, facet, old, new, sources_index=0):
        """Apply ``old -> new`` to the fixture's canonical N-Triples and require
        the round trip to reject or to differ."""
        original, nt = _load(family, case)
        self.assertIn(old, nt, f"{facet}: the mutation target {old!r} is not in the fixture; "
                               "this test would otherwise pass vacuously")
        mutated = nt.replace(old, new, 1)
        self.assertNotEqual(mutated, nt, f"{facet}: mutation was a no-op")

        try:
            recovered = to_json(parse(mutated))
        except InverseError:
            return  # detected by the reader's own consistency checks
        differences = jsonio.diff(original, recovered)
        self.assertNotEqual(
            differences, [],
            f"{facet}: the round trip did NOT detect {old!r} -> {new!r}. "
            "The fidelity claim for this facet is unsupported.",
        )


class TestNumericPrecision(_MutationCase):
    def test_decimal_trailing_zero_loss_is_detected(self):
        self.assert_detected(
            *EGFR, facet="decimal precision",
            old=f'"55.0"^^<{XSD}decimal>', new=f'"55"^^<{XSD}decimal>')

    def test_decimal_value_change_is_detected(self):
        self.assert_detected(
            *EGFR, facet="decimal value",
            old=f'"55.0"^^<{XSD}decimal>', new=f'"55.1"^^<{XSD}decimal>')

    def test_decimal_demoted_to_plain_literal_is_detected(self):
        self.assert_detected(
            *EGFR, facet="decimal datatype",
            old=f'"55.0"^^<{XSD}decimal>', new='"55.0"')

    def test_decimal_promoted_to_integer_is_detected(self):
        self.assert_detected(
            *EGFR, facet="decimal datatype",
            old=f'"55.0"^^<{XSD}decimal>', new=f'"55.0"^^<{XSD}integer>')


class TestTemporalPrecision(_MutationCase):
    def test_datetime_downgraded_to_date_is_detected(self):
        self.assert_detected(
            *EGFR, facet="temporal precision",
            old=f'"2026-09-02T14:00:00Z"^^<{XSD}dateTime>',
            new=f'"2026-09-02"^^<{XSD}date>')

    def test_timezone_loss_is_detected(self):
        self.assert_detected(
            *EGFR, facet="temporal precision",
            old=f'"2026-09-02T14:00:00Z"^^<{XSD}dateTime>',
            new=f'"2026-09-02T14:00:00+01:00"^^<{XSD}dateTime>')

    def test_datatype_stripped_from_a_datetime_is_detected(self):
        self.assert_detected(
            *EGFR, facet="temporal datatype",
            old=f'"2026-09-02T14:00:00Z"^^<{XSD}dateTime>',
            new='"2026-09-02T14:00:00Z"')

    def test_datatype_inconsistent_with_the_lexical_form_is_detected(self):
        self.assert_detected(
            *EGFR, facet="temporal datatype",
            old=f'"2026-09-02T14:00:00Z"^^<{XSD}dateTime>',
            new=f'"2026-09-02T14:00:00Z"^^<{XSD}date>')

    def test_encounter_period_end_removal_is_detected(self):
        original, nt = _load(*ENC)
        lines = [l for l in nt.splitlines() if l and not l.startswith("#")]
        end_node = None
        for l in lines:
            if "Period.end" in l:
                end_node = l.split()[-2]
        self.assertIsNotNone(end_node, "fixture has no Period.end to remove")
        kept = [l for l in lines if "Period.end" not in l and end_node not in l]
        self.assertLess(len(kept), len(lines))
        recovered = to_json(parse("\n".join(kept)))
        self.assertNotEqual(jsonio.diff(original, recovered), [])


class TestCodesAndUnits(_MutationCase):
    def test_code_system_swap_is_detected(self):
        self.assert_detected(
            *EGFR, facet="code system",
            old='"http://loinc.org"', new='"http://snomed.info/sct"')

    def test_code_change_is_detected(self):
        self.assert_detected(
            *EGFR, facet="code", old='"33914-3"', new='"33914-4"')

    def test_ucum_code_change_is_detected(self):
        self.assert_detected(
            *EGFR, facet="unit code",
            old='"mL/min/{1.73_m2}"', new='"mL/min"')

    def test_unit_display_text_change_is_detected(self):
        """Quantity.unit is source-only, but source-only is not the same as
        droppable: the round trip must still see it change."""
        self.assert_detected(
            *EGFR, facet="unit display text",
            old='"mL/min/1.73 m2"', new='"mL/min/1.73m2"')


class TestStatusAndComparator(_MutationCase):
    def test_status_change_is_detected(self):
        self.assert_detected(
            *EGFR, facet="status", old='"final"', new='"amended"')

    def test_comparator_value_change_is_detected(self):
        self.assert_detected(
            *CMP, facet="comparator", old='"<"', new='">"')

    def test_comparator_removal_is_detected(self):
        original, nt = _load(*CMP)
        lines = [l for l in nt.splitlines() if l and not l.startswith("#")]
        node = None
        for l in lines:
            if "Quantity.comparator" in l:
                node = l.split()[-2]
        self.assertIsNotNone(node, "fixture has no comparator to remove")
        kept = [l for l in lines if "Quantity.comparator" not in l and node not in l]
        self.assertLess(len(kept), len(lines))
        recovered = to_json(parse("\n".join(kept)))
        differences = jsonio.diff(original, recovered)
        self.assertNotEqual(
            differences, [],
            "dropping a comparator while keeping the numeric value went undetected; "
            "concept note section 2 forbids exactly this",
        )


class TestReferenceContext(_MutationCase):
    def test_subject_reference_change_is_detected(self):
        self.assert_detected(
            *EGFR, facet="reference context",
            old='"Patient/p123"', new='"Patient/p999"')

    def test_version_id_change_is_detected(self):
        self.assert_detected(
            *EGFR, facet="resource version",
            old='<http://hl7.org/fhir/Meta.versionId>',
            new='<http://hl7.org/fhir/Meta.source>')


class TestCardinalityAndOrder(_MutationCase):
    def test_component_order_swap_is_detected(self):
        """fhir:index carries array order; swapping it must show up.

        Rendered from bp-1 alone so the two component nodes are unambiguous.
        """
        from fhir_sulo.ingest import render

        path = os.path.join(FIXTURES, "bp", "bp-two-panels", "bp-1.json")
        original = jsonio.loads(read(path))
        lines = [l for l in render(original).nt.splitlines() if l]
        comp_nodes = {l.split()[0] for l in lines
                      if "<http://hl7.org/fhir/Observation.component.code>" in l}
        self.assertEqual(len(comp_nodes), 2, "expected exactly two components in bp-1")
        swapped = []
        for l in lines:
            if l.split()[0] in comp_nodes and "/index>" in l:
                l = (l.replace('"0"^^', '"TMP"^^') if '"0"^^' in l
                     else l.replace('"1"^^', '"0"^^'))
            swapped.append(l)
        swapped = [l.replace('"TMP"^^', '"1"^^') for l in swapped]
        self.assertNotEqual(swapped, lines, "the index swap was a no-op")
        recovered = to_json(parse("\n".join(swapped)))
        self.assertNotEqual(jsonio.diff(original, recovered), [])

    def test_missing_index_on_a_repeating_element_is_rejected(self):
        _, nt = _load(*BP)
        lines = [l for l in nt.splitlines() if l and not l.startswith("#")]
        kept = [l for l in lines if "/index>" not in l]
        self.assertLess(len(kept), len(lines))
        with self.assertRaises(InverseError):
            to_json(parse("\n".join(kept)))

    def test_a_dropped_component_is_detected(self):
        original, nt = _load(*BP)
        lines = [l for l in nt.splitlines() if l and not l.startswith("#")]
        # Remove one Observation.component edge; the remaining index set is
        # then not 0..n-1, or the array is short. Either way it must not pass.
        victim = next(l for l in lines if "/Observation.component>" in l)
        kept = [l for l in lines if l != victim]
        try:
            recovered = to_json(parse("\n".join(kept)))
        except InverseError:
            return
        self.assertNotEqual(jsonio.diff(original, recovered), [])


class TestTheTestItself(_MutationCase):
    def runTest(self):  # pragma: no cover - required by the base-class ctor
        pass

    def test_an_unmutated_graph_round_trips_clean(self):
        """The control. If this failed, every 'detected' above would be noise."""
        original, nt = _load(*EGFR)
        self.assertEqual(jsonio.diff(original, to_json(parse(nt))), [])

    def test_a_missing_mutation_target_fails_loudly(self):
        """Guards against a mutation silently becoming a no-op after a fixture
        edit, which would turn a detection test into a pass-by-default."""
        probe = TestTheTestItself("runTest")
        with self.assertRaises(AssertionError):
            probe.assert_detected(*EGFR, facet="control",
                                  old='"not present in the fixture"', new='"x"')

    def test_an_identity_mutation_fails_loudly(self):
        """old == new must not count as a detection."""
        probe = TestTheTestItself("runTest")
        with self.assertRaises(AssertionError):
            probe.assert_detected(*EGFR, facet="control",
                                  old='"33914-3"', new='"33914-3"')


if __name__ == "__main__":
    unittest.main()
