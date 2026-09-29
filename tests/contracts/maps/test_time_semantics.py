"""The three FHIR times are distinguishable, and only one reaches the graph.

Concept note section 2:

    Distinguish observation `effective[x]` (clinically relevant time) from
    `issued` (availability of the result) and `meta.lastUpdated` (resource
    version update). Preserve time precision and unknown endpoints.

Until now this was untested on the map side, and worse than untested: the
CLOSED source shape did not list `fhir:Observation.issued`, so a resource
carrying `issued` at all failed source validation. HL7's own
`observation-example-f205-egfr` -- the example concept note section 4 is
modelled on -- carries it. Agent 2 found the gap while adding the version
lineage fixtures; the shape now tolerates `issued` without mapping it, and
these tests hold that.

The inputs here are `egfr-baseline`'s rendered RDF with the extra time triples
appended by the test. That is a deliberate, labelled perturbation to probe the
map, not a fixture: `fixtures/r4/` is Agent 2's, and a real fixture carrying
all three times would be better evidence. Raised with the integration lead.
"""

from __future__ import annotations

import unittest

from . import egfr_case
from ._engine import engine, graph, mapjob
from ._engine.graph import SULO

FIXTURE = "egfr-baseline"
FHIR = "http://hl7.org/fhir/"
XSD_DATETIME = "http://www.w3.org/2001/XMLSchema#dateTime"

OBSERVATION = "https://fhir.example/Observation/egfr-456"
EFFECTIVE = "2026-09-02T14:00:00Z"      # clinically relevant: what the map uses
ISSUED = "2026-09-03T08:15:00Z"         # availability of the result
LAST_UPDATED = "2026-09-04T11:45:00Z"   # resource version update


def with_extra_times(nquads: str) -> str:
    """`egfr-baseline`'s graph, plus an `issued` and a `meta.lastUpdated`.

    Written the way the renderer writes a primitive: a blank node carrying
    `fhir:value`.
    """
    meta = "_:egfr-456-b1"   # the Resource.meta node the renderer emits
    extra = [
        '<%s> <%sObservation.issued> _:test-issued .' % (OBSERVATION, FHIR),
        '_:test-issued <%svalue> "%s"^^<%s> .' % (FHIR, ISSUED, XSD_DATETIME),
        '%s <%sMeta.lastUpdated> _:test-lastupdated .' % (meta, FHIR),
        '_:test-lastupdated <%svalue> "%s"^^<%s> .' % (FHIR, LAST_UPDATED, XSD_DATETIME),
    ]
    return nquads.rstrip("\n") + "\n" + "\n".join(extra) + "\n"


class ThreeTimesAreDistinguishable(engine.EngineTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        source = (egfr_case.fixture_dir(FIXTURE) / "canonical.nt").read_text()
        cls.perturbed = with_extra_times(source)
        cls.baseline = egfr_case.run(FIXTURE)

    def bind(self, data: str):
        return engine.run_job({
            "sourceSchema": engine.cpath("maps/r4/egfr/egfr-source.v1.shex"),
            "dataInline": data,
            "focus": OBSERVATION,
            "startShape": None,
            "passes": [],
        })

    def test_the_perturbation_really_adds_the_two_other_times(self):
        """Otherwise everything below would be proving nothing."""
        source = (egfr_case.fixture_dir(FIXTURE) / "canonical.nt").read_text()
        self.assertNotIn("Observation.issued", source)
        self.assertNotIn("Meta.lastUpdated", source)
        self.assertIn("Observation.issued", self.perturbed)
        self.assertIn("Meta.lastUpdated", self.perturbed)
        self.assertIn(ISSUED, self.perturbed)
        self.assertIn(LAST_UPDATED, self.perturbed)

    def test_a_resource_carrying_issued_still_validates(self):
        """The gap Agent 2 found: the CLOSED shape used to reject it.

        `issued` does not qualify the numeric claim, so retaining it in the
        source layer while asserting the quantity is what section 2 permits.
        """
        result = self.bind(self.perturbed)
        self.assertTrue(result["validation"]["ok"],
                        "an Observation carrying `issued` must not fail source "
                        "validation: HL7's own eGFR example carries it. %s"
                        % str(result["validation"])[:600])

    def test_neither_issued_nor_lastUpdated_is_bound(self):
        """They are tolerated, not mapped. A bound variable could reach the
        graph; an unbound one cannot."""
        bound = mapjob.flat_bindings(self.bind(self.perturbed)["bindings"],
                                     egfr_case.VAR_NS)
        self.assertEqual(mapjob.lexical(bound, "effective"), EFFECTIVE)
        for name, value in bound.items():
            text = value["value"] if isinstance(value, dict) else str(value)
            with self.subTest(variable=name):
                self.assertNotEqual(text, ISSUED)
                self.assertNotEqual(text, LAST_UPDATED)

    def test_only_effective_reaches_the_semantic_layer(self):
        """The whole point of section 2's distinction, on the emitted graph."""
        result = egfr_case.run(FIXTURE, data_override=self.perturbed)
        engine.require_clean(result)
        nquads = result["nquads"]

        self.assertIn(EFFECTIVE, nquads)
        self.assertNotIn(ISSUED, nquads)
        self.assertNotIn(LAST_UPDATED, nquads)

        triples = graph.parse(nquads)
        time_node = "<%s>" % result["_hostValues"]["timeInstant"]
        self.assertEqual(
            graph.objects_of(triples, time_node, "<%shasValue>" % SULO),
            ['"%s"^^<%s>' % (EFFECTIVE, XSD_DATETIME)])

    def test_the_extra_times_change_nothing_else_in_the_graph(self):
        """A tolerated element must be inert: same graph, with or without it."""
        result = egfr_case.run(FIXTURE, data_override=self.perturbed)
        engine.require_clean(result)
        self.assertEqual(sorted(graph.parse(result["nquads"])),
                         sorted(graph.parse(self.baseline["nquads"])))

    def test_the_version_is_taken_from_meta_versionId_not_from_a_time(self):
        """`meta.lastUpdated` is a version-update timestamp, not the version.

        The lineage IRI must name the versionId, so two versions of one
        resource are distinguishable even if they share a lastUpdated.
        """
        result = egfr_case.run(FIXTURE, data_override=self.perturbed)
        prov = "<http://www.w3.org/ns/prov#wasDerivedFrom>"
        triples = graph.parse(result["nquads"])
        derived = graph.objects_of(triples, "<%s>" % result["_hostValues"]["result"], prov)
        self.assertEqual(derived, ["<%s/_history/1>" % OBSERVATION])


class MethodIsNotSilentlyDropped(engine.EngineTestCase):
    """Concept note section 2 names `method` among the elements that must not
    be dropped while claiming an unqualified numeric result.

    `profiles/fhir-r4-pilot.json` lists it under `source_only_elements`, so
    the two documents conflict. Held at REJECT, which produces no semantic
    output rather than an unqualified quantity, and reported in DR-205.
    """

    def test_an_observation_carrying_a_method_is_rejected(self):
        source = (egfr_case.fixture_dir(FIXTURE) / "canonical.nt").read_text()
        with_method = source.rstrip("\n") + "\n" + "\n".join([
            '<%s> <%sObservation.method> _:test-method .' % (OBSERVATION, FHIR),
            '_:test-method <%sCodeableConcept.text> _:test-method-text .' % FHIR,
            '_:test-method-text <%svalue> "creatinine-based" .' % FHIR,
        ]) + "\n"
        result = engine.run_job({
            "sourceSchema": engine.cpath("maps/r4/egfr/egfr-source.v1.shex"),
            "dataInline": with_method,
            "focus": OBSERVATION,
            "startShape": None,
            "passes": [],
        })
        self.assertFalse(
            result["validation"]["ok"],
            "an Observation carrying a method must not silently yield an "
            "unqualified quantity (concept note section 2)")


if __name__ == "__main__":
    unittest.main()
