"""R4, R6 and R11 as the maps implement them, and why R11 stops at Encounter.

Answered 2026-09-30 and applied here. Each is a run-binding or a relation in
a target schema, so the change was configuration plus, for R11, one relation
per record shape -- no map was re-authored.

The Encounter half of R11 is NOT a judgement call, and this module refuses to
state it as prose: `test_r11_does_not_extend_to_the_encounter_record` derives
the contradiction from the pinned ontology file, so if SULO ever changes the
argument fails rather than lingering as a comment someone believes.

No reasoner is used here and no rdflib: these run under the stdlib fallback
too. Agent 6 owns the HermiT evidence (`test_reasoning_pro.py`).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from . import egfr_case, encounter_case
from ._engine import engine, graph
from ._engine.graph import RDF_TYPE, SULO

REPO = engine.REPO
ONTOLOGY = REPO / "src/fhir_sulo/validation/ontology/sulo-0.2.12.ttl"
POLICY = REPO / "policies/code-interpretation.v1.json"
FAMILIES = ("egfr", "bp", "encounter")


def ontology_block(cls: str) -> str:
    """The pinned ontology's own text for one class."""
    text = ONTOLOGY.read_text()
    match = re.search(r"(?m)^sulo:%s\b.*?(?=\n\n|\Z)" % re.escape(cls), text, re.S)
    assert match, "sulo:%s is not in the pinned ontology" % cls
    return match.group(0)


def vocabulary(family: str):
    path = REPO / "maps/r4" / family / ("%s-bindings.v1.json" % family)
    return json.loads(path.read_text())["vocabulary"]


class R4TheQualityBranch(unittest.TestCase):
    """Ratified as `sulo:Quality`. Reviewer: "we should not use feature -> it
    should go to a more specific class eg. sulo:Quality."

    No emitted change -- this is what the maps already did -- but the
    divergence from the concept note's literal `a sulo:Feature` in section 4
    is now sanctioned rather than accidental, and nothing may assert the
    note's literal text as the expectation.
    """

    def test_the_quality_branch_run_binding_is_sulo_Quality(self):
        for family in ("egfr", "bp"):
            with self.subTest(family=family):
                self.assertEqual(vocabulary(family)["qualityBranch"]["iri"],
                                 "https://w3id.org/sulo/Quality")

    def test_no_map_emits_a_bare_feature(self):
        for family in FAMILIES:
            for spec in vocabulary(family).values():
                with self.subTest(family=family, iri=spec["iri"]):
                    self.assertNotEqual(spec["iri"], "https://w3id.org/sulo/Feature")

    def test_bare_feature_would_leave_the_individual_unpartitioned(self):
        """Why the reviewer's answer is the right one, from the ontology."""
        block = ontology_block("Feature")
        self.assertIn("owl:disjointUnionOf", block)
        for branch in ("Capability", "InformationObject", "Quality", "Role"):
            self.assertIn("sulo:" + branch, block)


class R6PeopleAreSpatialObjects(engine.EngineTestCase):
    """Reviewer: "a person is a Spatial Object." Applied to practitioners too."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.egfr = egfr_case.run("egfr-baseline")
        cls.enc = encounter_case.run("enc-baseline")

    def test_the_run_bindings_say_spatial_object(self):
        for family in FAMILIES:
            for key in ("personSuloClass", "practitionerSuloClass"):
                if key in vocabulary(family):
                    with self.subTest(family=family, key=key):
                        self.assertEqual(vocabulary(family)[key]["iri"],
                                         "https://w3id.org/sulo/SpatialObject")

    def test_the_emitted_person_and_practitioner_are_spatial_objects(self):
        for label, result, keys in (("egfr", self.egfr, ("person",)),
                                    ("encounter", self.enc, ("person", "practitioner"))):
            triples = graph.parse(result["nquads"])
            for key in keys:
                with self.subTest(map=label, node=key):
                    types = graph.types_of(triples, "<%s>" % result["_hostValues"][key])
                    self.assertIn("<%sSpatialObject>" % SULO, types)
                    self.assertNotIn("<%sObject>" % SULO, types)

    def test_no_person_is_in_a_feature_branch(self):
        """The guard the answer restores: `Feature owl:disjointWith
        SpatialObject`, so this is now an inconsistency rather than a style
        rule. Bare `sulo:Object` could not give it, because
        `Quality subClassOf Feature subClassOf Object`."""
        for label, result, keys in (("egfr", self.egfr, ("person",)),
                                    ("encounter", self.enc, ("person", "practitioner"))):
            triples = graph.parse(result["nquads"])
            for key in keys:
                types = graph.types_of(triples, "<%s>" % result["_hostValues"][key])
                for branch in ("Feature", "Capability", "InformationObject", "Quality", "Role"):
                    with self.subTest(map=label, node=key, branch=branch):
                        self.assertNotIn("<%s%s>" % (SULO, branch), types)

    def test_the_disjointness_that_makes_it_a_guard_is_in_the_pinned_ontology(self):
        self.assertIn("owl:disjointWith sulo:SpatialObject", ontology_block("Feature"))

    def test_the_pro_chain_still_reaches_the_person(self):
        """`hasParticipant rdfs:range sulo:Object` and
        `SpatialObject subClassOf Object`, so the chain is unaffected."""
        self.assertIn("sulo:Object", ontology_block("SpatialObject"))
        triples = graph.parse(self.enc["nquads"])
        entailed = graph.entailed_participants(triples)
        process = "<%s>" % self.enc["_hostValues"]["process"]
        self.assertEqual(
            sorted(h for p, h in entailed if p == process),
            sorted(["<%s>" % self.enc["_hostValues"]["person"],
                    "<%s>" % self.enc["_hostValues"]["practitioner"]]))

    def test_nothing_asserts_a_part_of_a_person(self):
        """`SpatialObject subClassOf (hasPart only SpatialObject)`, so a
        `person hasPart X` with a non-spatial X would be inconsistent."""
        self.assertIn("owl:allValuesFrom sulo:SpatialObject", ontology_block("SpatialObject"))
        for result, keys in ((self.egfr, ("person",)), (self.enc, ("person", "practitioner"))):
            triples = graph.parse(result["nquads"])
            for key in keys:
                with self.subTest(node=key):
                    self.assertEqual(
                        graph.objects_of(triples, "<%s>" % result["_hostValues"][key],
                                         "<%shasPart>" % SULO), [])

    def test_hasFeature_is_not_a_subproperty_of_hasPart(self):
        """Checked before applying R6, because if it were, `person hasFeature
        quality` would entail `person hasPart quality` and trip
        SpatialObject's `hasPart only SpatialObject` restriction -- making
        every graph we emit inconsistent."""
        block = ontology_block("hasFeature")
        self.assertNotIn("rdfs:subPropertyOf", block)


class R11RecordsHaveTheirResultsAsParts(engine.EngineTestCase):
    """Reviewer: "compositionally, a record could indeed be comprised of
    statements, which could include the recording of results. This then
    captures where the results are located (e.g. the record). however, the
    results are information about the individual - they are features of the
    individual and they also refer to their qualities."
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.egfr = egfr_case.run("egfr-baseline")
        cls.enc = encounter_case.run("enc-baseline")

    def test_the_observation_record_has_the_result_as_a_part(self):
        v, triples = self.egfr["_hostValues"], graph.parse(self.egfr["nquads"])
        self.assertEqual(graph.objects_of(triples, "<%s>" % v["record"], "<%shasPart>" % SULO),
                         ["<%s>" % v["result"]])
        self.assertEqual(graph.objects_of(triples, "<%s>" % v["record"], "<%srefersTo>" % SULO),
                         [])

    def test_the_result_is_a_feature_of_the_individual(self):
        v, triples = self.egfr["_hostValues"], graph.parse(self.egfr["nquads"])
        self.assertEqual(
            graph.objects_of(triples, "<%s>" % v["result"], "<%sisFeatureOf>" % SULO),
            ["<%s>" % v["person"]])

    def test_the_result_still_refers_to_the_quality(self):
        v, triples = self.egfr["_hostValues"], graph.parse(self.egfr["nquads"])
        self.assertEqual(
            graph.objects_of(triples, "<%s>" % v["result"], "<%srefersTo>" % SULO),
            ["<%s>" % v["quality"]])

    def test_the_parthood_is_well_formed(self):
        """`InformationObject subClassOf (hasPart only InformationObject)`, and
        a result is a `Quantity subClassOf InformationObject`."""
        self.assertIn("owl:allValuesFrom sulo:InformationObject",
                      ontology_block("InformationObject"))
        self.assertIn("sulo:InformationObject", ontology_block("Quantity"))
        v, triples = self.egfr["_hostValues"], graph.parse(self.egfr["nquads"])
        self.assertIn("<%sInformationObject>" % SULO,
                      graph.types_of(triples, "<%s>" % v["record"]))
        self.assertIn("<%sQuantity>" % SULO, graph.types_of(triples, "<%s>" % v["result"]))

    def test_r11_does_not_extend_to_the_encounter_record(self):
        """Derived from the pinned ontology, not asserted as an opinion.

        `encounter-record sulo:hasPart encounter-process` would be
        inconsistent twice over:

          InformationObject subClassOf (hasPart only InformationObject)
            => the process would have to be an InformationObject, hence a
               Feature, hence an Object; but Object owl:disjointWith Process
               and the process is asserted `a sulo:Process`.
          Object subClassOf (not (hasPart some Process))
            => the record, being an Object, cannot have a Process part at all.

        So the Encounter record keeps `sulo:refersTo`. A result is information
        that sits inside a record; an encounter is an event in the world and
        is not located in its record.
        """
        info = ontology_block("InformationObject")
        self.assertIn("owl:allValuesFrom sulo:InformationObject", info)
        self.assertIn("sulo:Feature", info)

        obj = ontology_block("Object")
        self.assertIn("owl:disjointWith sulo:Process", obj)
        self.assertIn("owl:complementOf", obj)
        self.assertIn("owl:someValuesFrom sulo:Process", obj)

        self.assertIn("sulo:Object", ontology_block("Feature"))

        v, triples = self.enc["_hostValues"], graph.parse(self.enc["nquads"])
        self.assertIn("<%sProcess>" % SULO, graph.types_of(triples, "<%s>" % v["process"]))
        self.assertEqual(
            graph.objects_of(triples, "<%s>" % v["record"], "<%srefersTo>" % SULO),
            ["<%s>" % v["process"]])
        self.assertEqual(
            graph.objects_of(triples, "<%s>" % v["record"], "<%shasPart>" % SULO), [])


class R5SecondRowStaysUnset(engine.EngineTestCase):
    """R11 answered R5's FIRST row (materialize `isFeatureOf` on quantities)
    as option A. The SECOND row -- an explicit `sulo:Unit` on a
    `sulo:TimeInstant` -- is still open and must stay unset.
    """

    def test_no_time_instant_carries_a_unit_part(self):
        for fixture in ("egfr-baseline", "egfr-corrected"):
            triples = graph.parse(egfr_case.run(fixture)["nquads"])
            for node in graph.subjects_of_type(triples, SULO + "TimeInstant"):
                with self.subTest(fixture=fixture, node=node):
                    self.assertEqual(
                        graph.objects_of(triples, node, "<%shasPart>" % SULO), [])

    def test_the_maps_declare_no_time_unit_run_binding(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                self.assertNotIn("timeUnit", vocabulary(family))
                self.assertNotIn("timeUnitIri", vocabulary(family))


class TheDecisionsAreRecordedWhereTheyBelong(unittest.TestCase):
    """The graph asserts R4, R6 and R11; the reviewed artefact must say so.

    `policies/code-interpretation.v1.json :: reviewer_decisions` is the record
    of what the reviewer answered. At the time this was written it held only
    R1 and R10, and the R4/R6/R11 answers reached these maps as a relay from
    the integration lead rather than through that file. The maps are changed
    -- the relay quoted the reviewer verbatim and the axioms check out -- but
    a graph that asserts a decision no reviewed artefact records is exactly
    the "settled by default" failure REVIEW-REQUEST.md warns about.

    So this fails until the record lands. It is a one-line fix for whoever
    owns the file, and clearing it is how the two stop disagreeing. DR-206
    has the verbatim quotes to copy.
    """

    def test_reviewer_decisions_records_R4_R6_and_R11(self):
        decisions = json.loads(POLICY.read_text()).get("reviewer_decisions", {})
        missing = [item for item in ("R4", "R6", "R11") if item not in decisions]
        self.assertEqual(
            missing, [],
            "the maps emit these answers but %s records only %s. Land the record, or "
            "tell Agent 3 the relay was wrong and the maps get reverted."
            % (POLICY.relative_to(REPO), sorted(decisions)))


if __name__ == "__main__":
    unittest.main()
