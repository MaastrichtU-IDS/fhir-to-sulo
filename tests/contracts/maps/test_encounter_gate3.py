"""Gate 3 acceptance conditions for the Encounter map (concept note section 6).

The headline is the PRO entailment: the map asserts
``process hasParticipant role`` and ``role isFeatureOf holder``, and SULO's
property chain gives ``process hasParticipant holder`` *without* the map
asserting it and without any ``hasPatient`` shortcut.
"""

from __future__ import annotations

import unittest

from . import encounter_case
from ._engine import engine, graph
from ._engine.graph import RDF_TYPE, SULO

EX = "https://w3id.org/ontostart/fhir2sulo/"
HAS_PARTICIPANT = "<%shasParticipant>" % SULO
IS_FEATURE_OF = "<%sisFeatureOf>" % SULO


class EncounterBaseline(engine.EngineTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result = encounter_case.run("enc-baseline")
        cls.triples = graph.parse(cls.result["nquads"])
        cls.values = cls.result["_hostValues"]

    def test_the_run_was_clean(self):
        engine.require_clean(self.result)
        for p in self.result["passes"]:
            self.assertEqual(p["report"]["alternatives"], 1, p["name"])

    def test_the_graph_matches_the_concept_note_section_6_shape(self):
        process = "<%s>" % self.values["process"]
        self.assertEqual(sorted(graph.types_of(self.triples, process)),
                         sorted(["<%sProcess>" % SULO, "<%sClinicalEncounter>" % EX]))
        self.assertEqual(
            graph.objects_of(self.triples, process, HAS_PARTICIPANT),
            sorted(["<%s>" % self.values["patientRole"],
                    "<%s>" % self.values["clinicianRole"]]))
        self.assertEqual(graph.objects_of(self.triples, process, "<%satTime>" % SULO),
                         ["<%s>" % self.values["interval"]])

    def test_the_emitted_endpoints_are_the_ones_the_source_bound(self):
        """Target-side content, cross-checked against the source bindings, and
        asserted per endpoint so a start/end swap cannot pass."""
        src = self.result["_sourceBindings"]
        for node, var in (("startTime", "start"), ("endTime", "end")):
            with self.subTest(node=node):
                self.assertEqual(
                    graph.objects_of(self.triples, "<%s>" % self.values[node],
                                     "<%shasValue>" % SULO),
                    ['"%s"^^<%s>' % (src[var]["value"], src[var]["type"])])
        self.assertNotEqual(src["start"]["value"], src["end"]["value"],
                            "the fixture must have distinct endpoints or the swap "
                            "check above proves nothing")

    def test_the_patient_role_is_held_by_the_subject_and_not_the_practitioner(self):
        """A cross-wired target schema -- patientRole isFeatureOf the clinician --
        must fail.  The two holders come from two different FHIR references, so
        comparing the emitted arcs to the resolved entities catches a swap."""
        self.assertNotEqual(self.values["person"], self.values["clinician"])
        self.assertEqual(
            graph.objects_of(self.triples, "<%s>" % self.values["patientRole"], IS_FEATURE_OF),
            ["<%s>" % self.values["person"]])
        self.assertEqual(
            graph.objects_of(self.triples, "<%s>" % self.values["clinicianRole"], IS_FEATURE_OF),
            ["<%s>" % self.values["clinician"]])
        entailed = graph.entailed_participants(self.triples)
        process = "<%s>" % self.values["process"]
        self.assertEqual(
            sorted(h for p, h in entailed if p == process),
            sorted(["<%s>" % self.values["person"], "<%s>" % self.values["clinician"]]))

    def test_the_two_roles_are_typed_and_held(self):
        for role, cls, holder in (("patientRole", "PatientRole", "person"),
                                  ("clinicianRole", "ClinicianRole", "clinician")):
            with self.subTest(role=role):
                iri = "<%s>" % self.values[role]
                self.assertEqual(sorted(graph.types_of(self.triples, iri)),
                                 sorted(["<%sRole>" % SULO, "<%s%s>" % (EX, cls)]))
                self.assertEqual(graph.objects_of(self.triples, iri, IS_FEATURE_OF),
                                 ["<%s>" % self.values[holder]])

    def test_the_interval_has_a_start_and_an_end_with_their_datatypes(self):
        interval = "<%s>" % self.values["interval"]
        self.assertEqual(graph.types_of(self.triples, interval), ["<%sTimeInterval>" % SULO])
        self.assertEqual(graph.objects_of(self.triples, interval, "<%shasPart>" % SULO),
                         sorted(["<%s>" % self.values["startTime"],
                                 "<%s>" % self.values["endTime"]]))
        self.assertEqual(
            graph.objects_of(self.triples, "<%s>" % self.values["startTime"],
                             "<%shasValue>" % SULO),
            ['"2026-09-02T14:00:00Z"^^<http://www.w3.org/2001/XMLSchema#dateTime>'])
        self.assertEqual(
            graph.objects_of(self.triples, "<%s>" % self.values["endTime"],
                             "<%shasValue>" % SULO),
            ['"2026-09-02T14:30:00Z"^^<http://www.w3.org/2001/XMLSchema#dateTime>'])

    # -- the PRO entailment -------------------------------------------------

    def test_the_pro_chain_entails_the_people_as_participants(self):
        """DR-002 confirmed the chain is asserted in SULO 0.2.12; this computes
        it from the emitted triples."""
        entailed = graph.entailed_participants(self.triples)
        process = "<%s>" % self.values["process"]
        self.assertIn((process, "<%s>" % self.values["person"]), entailed)
        self.assertIn((process, "<%s>" % self.values["clinician"]), entailed)

    def test_the_map_does_not_assert_the_entailment_directly(self):
        """If it did, the PRO pattern would be decoration rather than the
        mechanism.  The only hasParticipant objects are the two roles."""
        process = "<%s>" % self.values["process"]
        asserted = graph.objects_of(self.triples, process, HAS_PARTICIPANT)
        self.assertNotIn("<%s>" % self.values["person"], asserted)
        self.assertNotIn("<%s>" % self.values["clinician"], asserted)

    def test_no_hasPatient_and_no_shortcut_predicate(self):
        allowed = {RDF_TYPE, "<http://www.w3.org/ns/prov#wasDerivedFrom>"} | {
            "<%s%s>" % (SULO, p) for p in
            ("hasParticipant", "isFeatureOf", "hasFeature", "atTime", "hasPart",
             "hasValue", "refersTo")}
        used = graph.predicates(self.triples)
        self.assertEqual(used - allowed, set(), sorted(used - allowed))
        for p in used:
            self.assertNotIn("hasPatient", p)

    def test_the_role_holders_are_not_typed_as_features(self):
        """DR-002: sulo:Feature owl:disjointWith sulo:SpatialObject, and Feature
        is a disjoint union of four branches.  A person must not be any of
        them, or the graph is inconsistent."""
        for holder in ("person", "clinician"):
            with self.subTest(holder=holder):
                types = graph.types_of(self.triples, "<%s>" % self.values[holder])
                for branch in ("Feature", "Capability", "InformationObject", "Quality", "Role"):
                    self.assertNotIn("<%s%s>" % (SULO, branch), types)

    def test_no_orphan_nodes_and_no_blank_nodes(self):
        self.assertEqual(graph.sources(self.triples), ["<%s>" % self.values["record"]])
        self.assertEqual(graph.blank_nodes(self.triples), set())

    def test_the_record_and_the_process_are_distinct_individuals(self):
        self.assertNotEqual(self.values["record"], self.values["process"])
        self.assertEqual(
            graph.objects_of(self.triples, "<%s>" % self.values["record"],
                             "<%srefersTo>" % SULO),
            ["<%s>" % self.values["process"]])
        self.assertNotIn("sameAs", self.result["nquads"])

    def test_the_encounter_class_code_does_not_type_the_process(self):
        """Concept note section 2: a FHIR code literal alone is not an OWL class
        assertion, and v3-ActCode has no reviewed entry."""
        self.assertIn("classCode", self.result["_sourceBindings"])
        self.assertEqual(self.result["_sourceBindings"]["classCode"]["value"], "AMB")
        self.assertNotIn("AMB", self.result["nquads"])


class EncounterVariants(engine.EngineTestCase):
    def test_a_contained_practitioner_resolves_to_a_different_entity(self):
        """A contained resource has no existence outside its container, so
        enc-12's '#pr-inline' must not merge with enc-9's Practitioner/c7."""
        base = encounter_case.run("enc-baseline")
        contained = encounter_case.run("enc-contained-practitioner")
        engine.require_clean(contained)
        self.assertNotEqual(base["_hostValues"]["clinician"],
                            contained["_hostValues"]["clinician"])
        # but the patient, referenced identically, is the same entity
        self.assertEqual(base["_hostValues"]["person"], contained["_hostValues"]["person"])

    def test_in_progress_is_not_materialized(self):
        """Concept note section 6: 'it is not treated as a finished interval'.
        R3 / Q-A2-2 is unanswered, so no policy exists and nothing is emitted."""
        r = encounter_case.run("enc-in-progress")
        self.assertFalse(r["validation"]["ok"])
        self.assertEqual(r["nquads"], "")

    def test_an_open_ended_period_is_not_materialized(self):
        """Concept note section 2 requires unknown endpoints to be preserved,
        and the pilot has no reviewed representation for one (R3 / Q-A2-3), so
        the map must not invent an end."""
        r = encounter_case.run("enc-open-period")
        self.assertFalse(r["validation"]["ok"])
        self.assertEqual(r["nquads"], "")

    def test_roles_are_keyed_by_the_encounter_not_by_the_person(self):
        """Two encounters for the same patient give two distinct patient roles.
        Merging them would assert one role participating in two processes."""
        a = encounter_case.run("enc-baseline")
        b = encounter_case.run("enc-contained-practitioner")
        self.assertEqual(a["_hostValues"]["person"], b["_hostValues"]["person"])
        self.assertNotEqual(a["_hostValues"]["patientRole"], b["_hostValues"]["patientRole"])


if __name__ == "__main__":
    unittest.main()
