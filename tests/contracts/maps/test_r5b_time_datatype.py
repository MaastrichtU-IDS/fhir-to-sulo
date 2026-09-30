"""R5b: what datatype a materialized `sulo:TimeInstant` carries, and why.

R5 row 2 was answered **B, relax** -- no `sulo:Unit` on a time instant.
Reviewer: *"time instants are specified in the has value datatype."* That makes
the choice of datatype load-bearing, which is R5b: `xsd:dateTimeStamp` requires
an offset, `xsd:dateTime` permits its absence, so under that reasoning a plain
`dateTime` can express an under-specified instant.

The instruction was to emit `dateTimeStamp` where the source value carries an
offset and `dateTime` where it does not.

**That is not implementable in ShExMap, and this module is the measurement.**
Three findings, each pinned by a test here so the conclusion cannot rot into a
comment nobody rechecks:

1. The materializer **re-emits the bound source term verbatim**. A target
   constraint's declared datatype is ignored, so declaring `xsd:dateTimeStamp`
   changes nothing about what is emitted.
2. Declaring it anyway is actively harmful: the emitted graph then **fails its
   own target schema** on reverse validation, which is the pivot-recovery
   breakage of DR-201 section 5.2 all over again.
3. ShEx datatype matching is **exact, not subtype-aware**, so the source shape
   cannot read a `dateTime` literal as a `dateTimeStamp` either -- and the
   source RDF must not be re-typed, because Agent 2's renderer is validated
   graph-isomorphically against HL7's published Turtle, which types
   offset-bearing values as plain `xsd:dateTime`.

The only remaining routes are host-side literal construction, which rule 4
forbids ("target triple construction lives in the schemas"), or a
postprocessor, which is forbidden outright. So the map emits `xsd:dateTime`
for every instant, faithfully carrying whatever offset the source had, and
DR-207 raises **R5c** with the options.

What IS available, and is proved here, is **discrimination**: a source shape
can tell the two lexical forms apart with a ShEx regex facet. Whatever the
reviewer decides, the map can act on it -- it just cannot act by re-typing.
"""

from __future__ import annotations

import unittest

from . import egfr_case, encounter_case
from ._engine import engine, graph
from ._engine.graph import SULO

XSD = "http://www.w3.org/2001/XMLSchema#"
DATETIME = XSD + "dateTime"
DATETIMESTAMP = XSD + "dateTimeStamp"

FHIR = "http://hl7.org/fhir/"
PROBE_OBS = "https://probe.test/Observation/o1"
EGFR_SH = "https://w3id.org/fhir-sulo/map/egfr/shape#"


def probe_data(lexical: str, datatype: str = DATETIME) -> str:
    return "".join([
        '<%s> <%snodeRole> <%streeRoot> .\n' % (PROBE_OBS, FHIR, FHIR),
        '<%s> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <%sObservation> .\n'
        % (PROBE_OBS, FHIR),
        '<%s> <%sObservation.effectiveDateTime> _:t .\n' % (PROBE_OBS, FHIR),
        '_:t <%svalue> "%s"^^<%s> .\n' % (FHIR, lexical, datatype),
    ])


PROBE_SOURCE = """
PREFIX fhir: <http://hl7.org/fhir/>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX Map:  <http://shex.io/extensions/Map/#>
PREFIX v:    <https://probe.test/var#>
PREFIX sh:   <https://probe.test/shape#>
start = @sh:Obs
sh:Obs CLOSED {
  rdf:type [fhir:Observation] ; fhir:nodeRole [fhir:treeRoot] ;
  fhir:Observation.effectiveDateTime { fhir:value %s %%Map:{ v:effective %%} }
}
"""

PROBE_TARGET = """
PREFIX sulo: <https://w3id.org/sulo/>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX Map:  <http://shex.io/extensions/Map/#>
PREFIX v:    <https://probe.test/var#>
PREFIX sh:   <https://probe.test/shape#>
start = @sh:T
sh:T { rdf:type [sulo:TimeInstant] ; sulo:hasValue %s %%Map:{ v:effective %%} }
"""

# A source shape that tells the two lexical forms apart. Proof the capability
# exists, so whatever the reviewer answers the map can act on it.
DISCRIMINATING_SOURCE = """
PREFIX fhir: <http://hl7.org/fhir/>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX Map:  <http://shex.io/extensions/Map/#>
PREFIX v:    <https://probe.test/var#>
PREFIX sh:   <https://probe.test/shape#>
start = @sh:Obs
sh:Obs CLOSED {
  rdf:type [fhir:Observation] ; fhir:nodeRole [fhir:treeRoot] ;
  fhir:Observation.effectiveDateTime (@sh:Offset OR @sh:Offsetless)
}
sh:Offset     CLOSED { fhir:value xsd:dateTime /(Z|[+-][0-9]{2}:[0-9]{2})$/ %Map:{ v:withOffset %} }
sh:Offsetless CLOSED { fhir:value xsd:dateTime /[0-9]$/                     %Map:{ v:noOffset %} }
"""


def emitted_time_value(nquads: str, node: str):
    return graph.objects_of(graph.parse(nquads), "<%s>" % node, "<%shasValue>" % SULO)


class WhatTheMapsEmitToday(engine.EngineTestCase):
    """The side-by-side the integration lead asked for.

    The offsetless input is a **labelled perturbation** of
    `egfr-baseline`'s rendered RDF, not a fixture: every fixture in
    `fixtures/r4/` carries `Z`. A real offsetless fixture is Agent 2's to add
    and is requested -- see DR-207.
    """

    OFFSET = "2026-09-02T14:00:00Z"
    OFFSETLESS = "2026-09-02T14:00:00"
    OTHER_OFFSET = "2026-09-02T14:00:00+05:30"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base = (egfr_case.fixture_dir("egfr-baseline") / "canonical.nt").read_text()

    def emit(self, lexical):
        data = self.base.replace(self.OFFSET, lexical)
        self.assertTrue(lexical == self.OFFSET or data != self.base,
                        "the perturbation did nothing")
        result = egfr_case.run("egfr-baseline", data_override=data)
        engine.require_clean(result)
        return result

    def test_an_offset_bearing_instant(self):
        result = self.emit(self.OFFSET)
        self.assertEqual(
            emitted_time_value(result["nquads"], result["_hostValues"]["timeInstant"]),
            ['"%s"^^<%s>' % (self.OFFSET, DATETIME)])

    def test_an_offsetless_instant(self):
        """Accepted, and emitted offsetless. No offset is invented -- section 2
        requires preserving precision, and asserting an offset the source did
        not carry would be a fabrication."""
        result = self.emit(self.OFFSETLESS)
        self.assertEqual(
            emitted_time_value(result["nquads"], result["_hostValues"]["timeInstant"]),
            ['"%s"^^<%s>' % (self.OFFSETLESS, DATETIME)])

    def test_the_lexical_form_is_carried_through_verbatim(self):
        """The injection that shows nothing is hard-coded.

        A map that pinned `Z`, or normalised every instant to UTC, would pass
        the two tests above and fail this one.
        """
        result = self.emit(self.OTHER_OFFSET)
        self.assertEqual(
            emitted_time_value(result["nquads"], result["_hostValues"]["timeInstant"]),
            ['"%s"^^<%s>' % (self.OTHER_OFFSET, DATETIME)])

    def test_every_emitted_time_instant_is_xsd_dateTime(self):
        """Across all three maps, including the Encounter endpoints."""
        results = [egfr_case.run("egfr-baseline"), encounter_case.run("enc-baseline")]
        for result in results:
            triples = graph.parse(result["nquads"])
            for cls in ("TimeInstant", "StartTime", "EndTime"):
                for node in graph.subjects_of_type(triples, SULO + cls):
                    for value in graph.objects_of(triples, node, "<%shasValue>" % SULO):
                        with self.subTest(cls=cls, node=node):
                            self.assertIn("^^<%s>" % DATETIME, value)
                            self.assertNotIn(DATETIMESTAMP, value)


class WhyDateTimeStampCannotBeEmitted(engine.EngineTestCase):
    """The measurement behind DR-207. Each of these is a reason, not an excuse."""

    def probe(self, source_datatype, target_datatype, lexical, data_datatype=DATETIME):
        return engine.run_job({
            "sourceSchemaInline": PROBE_SOURCE % source_datatype,
            "targetSchemaInline": PROBE_TARGET % target_datatype,
            "dataInline": probe_data(lexical, data_datatype),
            "data": None, "focus": PROBE_OBS, "startShape": None,
            "passes": [{"name": "t", "shape": "https://probe.test/shape#T",
                        "root": "https://probe.test/time", "staticVars": {}}],
        })

    def test_the_targets_declared_datatype_is_ignored(self):
        """FINDING 1. The materializer re-emits the bound source term verbatim.

        So `sulo:hasValue xsd:dateTimeStamp` in a target schema does not make
        the emitted literal a dateTimeStamp. This is the whole reason R5b
        cannot be implemented as specified.
        """
        for lexical in ("2026-09-02T14:00:00Z", "2026-09-02T14:00:00+01:00",
                        "2026-09-02T14:00:00"):
            with self.subTest(lexical=lexical):
                result = self.probe("xsd:dateTime", "xsd:dateTimeStamp", lexical)
                self.assertTrue(result["validation"]["ok"])
                emitted = [q[2] for p in result["passes"] for q in p["quads"]
                           if "hasValue" in q[1]]
                self.assertEqual(emitted, ['"%s"^^<%s>' % (lexical, DATETIME)],
                                 "the target declared dateTimeStamp and the engine "
                                 "emitted dateTime anyway")

    def test_declaring_it_makes_the_graph_fail_its_own_schema(self):
        """FINDING 2. Worse than a no-op.

        Reverse-validating a materialized graph against the target schema that
        produced it is the pivot-recovery check (concept note section 5). A
        target that declares a datatype the engine will not emit breaks it.
        """
        forward = egfr_case.run("egfr-baseline")
        engine.require_clean(forward)
        honest = (engine.REPO / "maps/r4/egfr/egfr-target.v1.shex").read_text()
        lying = honest.replace("sulo:hasValue xsd:dateTime %Map:{ v:effective %}",
                               "sulo:hasValue xsd:dateTimeStamp %Map:{ v:effective %}")
        self.assertNotEqual(honest, lying, "the rewrite did nothing")

        for schema, expected_ok in ((honest, True), (lying, False)):
            with self.subTest(declares="dateTime" if expected_ok else "dateTimeStamp"):
                rev = engine.run_job({
                    "sourceSchemaInline": schema, "targetSchema": None,
                    "dataInline": forward["nquads"], "data": None,
                    "focus": forward["_hostValues"]["timeInstant"],
                    "startShape": EGFR_SH + "EGFRTimeNode", "passes": []})
                self.assertEqual(rev["validation"]["ok"], expected_ok)

    def test_shex_datatype_matching_is_exact_not_subtype_aware(self):
        """FINDING 3. So the source cannot read a dateTime as a dateTimeStamp.

        `xsd:dateTimeStamp` is a subtype of `xsd:dateTime` in XSD, but ShEx
        matches the literal's datatype IRI, not the type hierarchy.
        """
        ok = self.probe("xsd:dateTimeStamp", "xsd:dateTime",
                        "2026-09-02T14:00:00Z", DATETIME)["validation"]["ok"]
        self.assertFalse(ok, "a dateTime literal must not match a dateTimeStamp constraint")
        ok = self.probe("xsd:dateTime", "xsd:dateTime",
                        "2026-09-02T14:00:00Z", DATETIMESTAMP)["validation"]["ok"]
        self.assertFalse(ok, "a dateTimeStamp literal must not match a dateTime constraint")

    def test_the_source_can_still_tell_the_two_forms_apart(self):
        """What IS available. Whatever the reviewer answers, the map can act
        on the distinction -- it just cannot act by re-typing the literal."""
        cases = {"2026-09-02T14:00:00Z": "withOffset",
                 "2026-09-02T14:00:00+01:00": "withOffset",
                 "2026-09-02T14:00:00-05:00": "withOffset",
                 "2026-09-02T14:00:00": "noOffset"}
        for lexical, expected in cases.items():
            with self.subTest(lexical=lexical):
                result = engine.run_job({
                    "sourceSchemaInline": DISCRIMINATING_SOURCE, "targetSchema": None,
                    "dataInline": probe_data(lexical), "data": None,
                    "focus": PROBE_OBS, "startShape": None, "passes": []})
                self.assertTrue(result["validation"]["ok"], str(result["validation"])[:300])
                bound = {k.rsplit("#", 1)[-1] for k in (result["bindings"] or {})}
                self.assertEqual(bound, {expected})


class RdflibCanonicalisesTheTwoDatatypesDifferently(unittest.TestCase):
    """The asymmetry the integration lead asked about, measured.

    rdflib rewrites `Z` to `+00:00` for `xsd:dateTime` but leaves it alone for
    `xsd:dateTimeStamp`. Graph comparison and the SHACL digest both go through
    rdflib, so if the pilot ever did emit both datatypes, the same instant
    would have different lexical forms depending on its datatype. Recorded now
    rather than discovered later.
    """

    def setUp(self):
        try:
            import rdflib  # noqa: F401
        except ImportError:
            self.skipTest("rdflib is not in the stdlib fallback environment")

    def serialise(self, lexical, datatype):
        import rdflib
        g = rdflib.Graph()
        g.add((rdflib.URIRef("urn:s"), rdflib.URIRef("urn:p"),
               rdflib.Literal(lexical, datatype=rdflib.URIRef(datatype))))
        return g.serialize(format="nt").strip().split(" ", 2)[2]

    def test_Z_is_rewritten_for_dateTime(self):
        self.assertIn("+00:00", self.serialise("2026-09-02T14:00:00Z", DATETIME))

    def test_Z_survives_for_dateTimeStamp(self):
        self.assertIn("2026-09-02T14:00:00Z", self.serialise("2026-09-02T14:00:00Z",
                                                             DATETIMESTAMP))

    def test_an_explicit_offset_is_untouched_either_way(self):
        for datatype in (DATETIME, DATETIMESTAMP):
            with self.subTest(datatype=datatype):
                self.assertIn("+01:00", self.serialise("2026-09-02T14:00:00+01:00", datatype))


class R5Row2StaysRelaxed(engine.EngineTestCase):
    """R5 row 2 = B. No `sulo:Unit` on a time instant; unchanged by R5b."""

    def test_no_time_node_carries_a_unit_part(self):
        for result in (egfr_case.run("egfr-baseline"), encounter_case.run("enc-baseline")):
            triples = graph.parse(result["nquads"])
            for cls in ("TimeInstant", "StartTime", "EndTime"):
                for node in graph.subjects_of_type(triples, SULO + cls):
                    with self.subTest(cls=cls, node=node):
                        self.assertEqual(
                            graph.objects_of(triples, node, "<%shasPart>" % SULO), [])


if __name__ == "__main__":
    unittest.main()
