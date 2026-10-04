"""Source fidelity: JSON -> FHIR RDF -> JSON, and the committed RDF is what the
pinned renderer produces.

Plan section 2, Agent 2's local success condition:

    Each fixture retains release, canonical URL/version, profile, status,
    precise values, and resolvable reference context; source RDF round trips
    to its input content under the chosen renderer.

The round trip goes through the *serialised text*: render, write N-Triples,
re-parse with the dependency-free reader, rebuild JSON. It does not reuse the
renderer's in-memory tree, so agreement is evidence rather than tautology.
``test_roundtrip_mutations.py`` is the companion that proves this test can
fail.
"""

from __future__ import annotations

import os
import re
import unittest

from . import _support
from ._support import FIXTURES, ROOT, cases, read, source_files

from fhir_sulo.ingest import jsonio, render, to_json  # noqa: E402
from fhir_sulo.ingest.fhir_rdf import RenderError  # noqa: E402
from fhir_sulo.ingest.ntriples import parse, serialize  # noqa: E402


class TestRoundTrip(unittest.TestCase):
    def test_every_fixture_source_round_trips_exactly(self):
        checked = 0
        for label, path in source_files():
            with self.subTest(fixture=label):
                text = read(path)
                original = jsonio.loads(text)
                rendered = render(original)

                # Go out through text and back in through an independent reader.
                nt = serialize(rendered.triples)
                reparsed = parse(nt)
                self.assertEqual(
                    set(reparsed), set(rendered.triples),
                    "the N-Triples reader lost, invented or altered triples",
                )
                recovered = to_json(reparsed)

                differences = jsonio.diff(original, recovered)
                self.assertEqual(differences, [], f"{label}: {differences}")
                checked += 1
        self.assertGreaterEqual(checked, 20, "fixture discovery found suspiciously few sources")

    def test_rendering_is_deterministic(self):
        for label, path in source_files():
            with self.subTest(fixture=label):
                resource = jsonio.loads(read(path))
                first = render(resource).nt
                second = render(jsonio.loads(read(path))).nt
                self.assertEqual(first, second)

    def test_committed_canonical_rdf_matches_the_pinned_renderer(self):
        """A drift here means the renderer changed without the fixtures being
        regenerated, which would silently invalidate every downstream test."""
        import subprocess
        import sys

        proc = subprocess.run(
            [sys.executable, os.path.join(FIXTURES, "build.py"), "--check"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_canonical_form_is_sorted_and_stable(self):
        for case_dir, case in cases():
            nt_path = os.path.join(case_dir, "canonical.nt")
            with self.subTest(fixture=os.path.basename(case_dir)):
                lines = [l for l in read(nt_path).splitlines()
                         if l and not l.startswith("#")]
                self.assertEqual(lines, sorted(lines), "canonical.nt is not sorted")
                self.assertEqual(len(lines), len(set(lines)), "duplicate triples")


class TestPreservedFacets(unittest.TestCase):
    """Spot checks that name the facets the acceptance matrix names, so a
    regression reads as the thing that broke rather than as a diff."""

    def _nt(self, *parts):
        return read(os.path.join(FIXTURES, *parts))

    def test_decimal_precision_survives(self):
        nt = self._nt("egfr", "egfr-baseline", "canonical.nt")
        self.assertIn('"55.0"^^<http://www.w3.org/2001/XMLSchema#decimal>', nt)
        self.assertNotIn('"55"^^', nt)

    def test_temporal_precision_and_datatype_survive(self):
        nt = self._nt("egfr", "egfr-baseline", "canonical.nt")
        self.assertIn('"2026-09-02T14:00:00Z"^^<http://www.w3.org/2001/XMLSchema#dateTime>', nt)

    def test_unknown_period_end_is_absent_not_invented(self):
        nt = self._nt("encounter", "enc-open-period", "canonical.nt")
        self.assertIn("Period.start", nt)
        self.assertNotIn("Period.end", nt)

    def test_comparator_is_retained_in_the_source_layer(self):
        nt = self._nt("egfr", "egfr-comparator", "canonical.nt")
        self.assertIn("Quantity.comparator", nt)
        self.assertIn('"<"', nt)

    def test_code_system_and_code_are_retained_verbatim(self):
        nt = self._nt("egfr", "egfr-baseline", "canonical.nt")
        self.assertIn('"http://loinc.org"', nt)
        self.assertIn('"33914-3"', nt)

    def test_unit_display_text_and_ucum_code_are_both_retained(self):
        nt = self._nt("egfr", "egfr-baseline", "canonical.nt")
        self.assertIn('"mL/min/1.73 m2"', nt)          # Quantity.unit, source-only
        self.assertIn('"mL/min/{1.73_m2}"', nt)        # Quantity.code, the binding

    def test_no_owl_sameas_anywhere_in_the_source_layer(self):
        """Concept note section 2: never assert owl:sameAs between a FHIR
        resource and a person."""
        for case_dir, _ in cases():
            nt = read(os.path.join(case_dir, "canonical.nt"))
            self.assertNotIn("owl#sameAs", nt)

    def test_date_precision_effective_time_is_not_promoted_to_datetime(self):
        nt = self._nt("egfr", "egfr-effective-date-only", "canonical.nt")
        self.assertIn('"2026-09-02"^^<http://www.w3.org/2001/XMLSchema#date>', nt)
        self.assertNotIn("XMLSchema#dateTime", nt)

    def test_the_three_time_elements_are_distinguishable(self):
        """effective[x], issued and meta.lastUpdated must not collapse."""
        from fhir_sulo.ingest import jsonio as J
        resource = J.loads(read(os.path.join(
            FIXTURES, "egfr", "egfr-baseline", "egfr-456.json")))
        resource["issued"] = "2026-09-02T15:00:00Z"
        resource["meta"]["lastUpdated"] = "2026-09-02T16:00:00Z"
        nt = render(resource).nt
        self.assertIn("Observation.effectiveDateTime", nt)
        self.assertIn("Observation.issued", nt)
        self.assertIn("Meta.lastUpdated", nt)
        self.assertEqual(jsonio.diff(resource, to_json(parse(nt))), [])


class TestTemporalPrecisionLadder(unittest.TestCase):
    """Every R4 temporal precision, and the one form R4 does not allow.

    R5b asks whether the target should emit ``xsd:dateTimeStamp`` when an
    offset is present and ``xsd:dateTime`` when it is not. The premise only
    holds if an offsetless FHIR dateTime exists. It does not: R4's ``dateTime``
    regex puts the ``(Z|(+|-)hh:mm)`` group *inside* the ``T`` group and does
    not make it optional, so a value carrying a time always carries an offset.

    Checked here against the regex published in the R4 definitions bundle
    (``profiles-types.json``, ``StructureDefinition/dateTime``, the
    ``regex`` extension on ``dateTime.value``) rather than from memory, and
    restated as a literal so the suite documents it:

        ...(T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\\.[0-9]+)?
            (Z|(\\+|-)((0[0-9]|1[0-3]):[0-5][0-9]|14:00)))?...

    So the real discrimination is *precision*, and this is the ladder.
    """

    XSD = "http://www.w3.org/2001/XMLSchema#"

    LADDER = [
        ("2026", "gYear"),
        ("2026-09", "gYearMonth"),
        ("2026-09-02", "date"),
        ("2026-09-02T14:00:00Z", "dateTime"),
        ("2026-09-02T14:00:00+01:00", "dateTime"),
        ("2026-09-02T14:00:00.250Z", "dateTime"),
    ]

    # Valid R4 dateTime requires an offset once a time is present, so none of
    # these may be rendered. Guessing a datatype here would invent precision.
    REFUSED = [
        "2026-09-02T14:00:00",
        "2026-09-02T14:00",
        "2026-09-02 14:00:00Z",
        "02/09/2026",
        "",
    ]

    def _obs(self, effective):
        resource = jsonio.loads(read(os.path.join(
            FIXTURES, "egfr", "egfr-baseline", "egfr-456.json")))
        resource["effectiveDateTime"] = effective
        return resource

    def test_each_precision_gets_its_own_datatype(self):
        for value, expected in self.LADDER:
            with self.subTest(value=value):
                nt = render(self._obs(value)).nt
                self.assertIn('"%s"^^<%s%s>' % (value, self.XSD, expected), nt)

    def test_each_precision_round_trips_unchanged(self):
        for value, _ in self.LADDER:
            with self.subTest(value=value):
                original = self._obs(value)
                recovered = to_json(parse(render(original).nt))
                self.assertEqual(jsonio.diff(original, recovered), [])
                self.assertEqual(recovered["effectiveDateTime"], value)

    def test_the_precisions_are_all_distinguishable_from_one_another(self):
        rendered = {v: render(self._obs(v)).nt for v, _ in self.LADDER}
        self.assertEqual(len(set(rendered.values())), len(self.LADDER))

    def test_a_datetime_without_an_offset_is_refused_not_guessed(self):
        for value in self.REFUSED:
            with self.subTest(value=value):
                with self.assertRaises(RenderError):
                    render(self._obs(value))

    def test_an_offsetless_timestamp_is_not_valid_r4_in_the_first_place(self):
        """The premise behind R5b, checked rather than assumed."""
        r4_datetime = re.compile(
            r"([0-9]([0-9]([0-9][1-9]|[1-9]0)|[1-9]00)|[1-9]000)"
            r"(-(0[1-9]|1[0-2])(-(0[1-9]|[1-2][0-9]|3[0-1])"
            r"(T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?"
            r"(Z|(\+|-)((0[0-9]|1[0-3]):[0-5][0-9]|14:00)))?)?)?")
        self.assertIsNone(r4_datetime.fullmatch("2026-09-02T14:00:00"))
        # ... while every value the renderer accepts is conformant.
        for value, _ in self.LADDER:
            with self.subTest(value=value):
                self.assertIsNotNone(r4_datetime.fullmatch(value))

    def test_period_endpoints_follow_the_same_ladder(self):
        resource = jsonio.loads(read(os.path.join(
            FIXTURES, "encounter", "enc-baseline", "enc-9.json")))
        resource["period"] = {"start": "2026-09", "end": "2026-09-02T14:30:00Z"}
        nt = render(resource).nt
        self.assertIn('"2026-09"^^<%sgYearMonth>' % self.XSD, nt)
        self.assertIn('"2026-09-02T14:30:00Z"^^<%sdateTime>' % self.XSD, nt)
        self.assertEqual(jsonio.diff(resource, to_json(parse(nt))), [])


if __name__ == "__main__":
    unittest.main()
