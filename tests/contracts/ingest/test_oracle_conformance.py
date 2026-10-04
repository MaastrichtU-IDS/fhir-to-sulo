"""The renderer reproduces HL7's own published R4 Turtle.

This is the evidence behind DR-101's claim that a purpose-built renderer is
faithful to https://hl7.org/fhir/R4/rdf.html rather than merely self-consistent.
Three examples published by HL7 alongside the R4 specification are rendered
from their published JSON and compared graph-isomorphically with their
published Turtle:

* ``observation-example-bloodpressure`` - the example concept note section 5 cites
* ``observation-example-f205-egfr``     - the example concept note section 4 cites
* ``encounter-example``                 - concept note section 6's resource type

Two documented deviations are neutralised for the comparison and are the
renderer's *defaults*, not accidents (see profiles/fhir-r4-pilot.json,
``renderer.option_notes``):

* ``emit_code_system_class_assertions`` - HL7 emits ``a loinc:33914-3``. That is
  a terminology-derived OWL class assertion and concept note section 2 says a
  FHIR code literal alone is not one. Off by default; turned on here.
* ``emit_ontology_header`` - HL7 emits an ``owl:Ontology`` block pointing at
  build.fhir.org. Off by default; stripped from the official graph here.

Needs rdflib for isomorphism checking, so it skips when rdflib is absent. Every
test that could hide a fidelity loss runs without it.
"""

from __future__ import annotations

import os
import unittest

from . import _support
from ._support import ORACLE, read

from fhir_sulo.ingest import jsonio, render  # noqa: E402

try:
    import rdflib
    from rdflib.compare import graph_diff, to_isomorphic
    HAVE_RDFLIB = True
except ImportError:  # pragma: no cover
    HAVE_RDFLIB = False

OWL = "http://www.w3.org/2002/07/owl#"
EXAMPLES = ["observation-example-bloodpressure",
            "observation-example-f205-egfr",
            "encounter-example"]


class TestOracleFilesArePresent(unittest.TestCase):
    """Runs without rdflib: the oracle must at least be committed."""

    def test_all_oracle_pairs_are_committed(self):
        for name in EXAMPLES:
            for ext in (".json", ".ttl"):
                self.assertTrue(os.path.exists(os.path.join(ORACLE, name + ext)),
                                name + ext)

    def test_the_renderer_accepts_every_oracle_resource(self):
        """A refusal here means the pinned element table is missing an element
        that HL7's own example uses, i.e. our subset claim is wrong."""
        for name in EXAMPLES:
            with self.subTest(example=name):
                resource = jsonio.loads(read(os.path.join(ORACLE, name + ".json")))
                rendered = render(resource, base="http://hl7.org/fhir/",
                                  emit_code_system_class_assertions=True)
                self.assertGreater(len(rendered.triples), 20)


@unittest.skipUnless(HAVE_RDFLIB, "rdflib is not installed (see requirements-dev.txt)")
class TestIsomorphicToPublishedTurtle(unittest.TestCase):
    def _official(self, name):
        g = rdflib.Graph()
        g.parse(os.path.join(ORACLE, name + ".ttl"), format="turtle")
        for triple in [t for t in g if str(t[1]).startswith(OWL)
                       or str(t[2]) == OWL + "Ontology"]:
            g.remove(triple)
        return g

    def _mine(self, name):
        resource = jsonio.loads(read(os.path.join(ORACLE, name + ".json")))
        rendered = render(resource, base="http://hl7.org/fhir/",
                          emit_code_system_class_assertions=True,
                          emit_ontology_header=False)
        g = rdflib.Graph()
        g.parse(data=rendered.nt, format="nt")
        return g

    def test_examples_are_isomorphic(self):
        for name in EXAMPLES:
            with self.subTest(example=name):
                mine, official = self._mine(name), self._official(name)
                im, io = to_isomorphic(mine), to_isomorphic(official)
                if im != io:
                    _, only_mine, only_official = graph_diff(im, io)
                    detail = "\n".join(
                        ["  + " + " ".join(x.n3() for x in t)
                         for t in sorted(only_mine, key=str)[:10]]
                        + ["  - " + " ".join(x.n3() for x in t)
                           for t in sorted(only_official, key=str)[:10]])
                    self.fail(f"{name}: not isomorphic to HL7's published Turtle\n{detail}")
                self.assertEqual(len(mine), len(official))

    def test_the_comparison_can_fail(self):
        """Control: a deliberately wrong render must not read as isomorphic."""
        name = "encounter-example"
        resource = jsonio.loads(read(os.path.join(ORACLE, name + ".json")))
        resource["status"] = "finished"          # official says in-progress
        rendered = render(resource, base="http://hl7.org/fhir/",
                          emit_code_system_class_assertions=True)
        mine = rdflib.Graph()
        mine.parse(data=rendered.nt, format="nt")
        self.assertNotEqual(to_isomorphic(mine), to_isomorphic(self._official(name)))

    def test_our_turtle_writer_agrees_with_our_n_triples(self):
        from fhir_sulo.ingest import turtle
        for name in EXAMPLES:
            with self.subTest(example=name):
                resource = jsonio.loads(read(os.path.join(ORACLE, name + ".json")))
                r = render(resource, base="http://hl7.org/fhir/")
                a, b = rdflib.Graph(), rdflib.Graph()
                a.parse(data=r.nt, format="nt")
                b.parse(data=turtle.serialize(r.triples, root=r.root), format="turtle")
                self.assertEqual(to_isomorphic(a), to_isomorphic(b))

    def test_committed_fixture_turtle_matches_committed_fixture_ntriples(self):
        from ._support import cases
        for case_dir, case in cases():
            with self.subTest(fixture=case["fixture_id"]):
                a, b = rdflib.Graph(), rdflib.Graph()
                a.parse(os.path.join(case_dir, "canonical.nt"), format="nt")
                b.parse(os.path.join(case_dir, "readable.ttl"), format="turtle")
                self.assertEqual(to_isomorphic(a), to_isomorphic(b))


if __name__ == "__main__":
    unittest.main()
