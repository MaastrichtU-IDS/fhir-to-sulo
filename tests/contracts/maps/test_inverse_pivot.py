"""Target-to-source pivot recovery (acceptance row "Pivot reversibility").

Concept note section 5 calls this "the first test of target-to-source pivot
recovery: validating the materialized graph against the target map must recover
the same two associated tuples", and section 7 says the pairing promises
recovery of shared pivot bindings, not every FHIR field.

Method: take the materialized graph, validate each node against the *target*
schema that produced it, and read the Map bindings back out.  That is the same
`shex-validate --extension` path the forward direction uses, so nothing here is
a bespoke reader.
"""

from __future__ import annotations

import unittest

from . import bp_case, egfr_case, encounter_case
from ._engine import engine, graph

EGFR_SH = "https://w3id.org/fhir-sulo/map/egfr/shape#"
EGFR_V = "https://w3id.org/fhir-sulo/map/egfr/var#"
BP_SH = "https://w3id.org/fhir-sulo/map/bp/shape#"
BP_V = "https://w3id.org/fhir-sulo/map/bp/var#"
ENC_SH = "https://w3id.org/fhir-sulo/map/encounter/shape#"
ENC_V = "https://w3id.org/fhir-sulo/map/encounter/var#"


def reverse(target_schema_rel: str, nquads: str, focus: str, shape: str, var_ns: str):
    """Validate one node of a FRESHLY MATERIALIZED graph against the target
    schema and read the Map bindings back out.

    `nquads` is the graph text, not a committed path, deliberately: reverse
    validation against `fixtures/expected/.../target.nt` would read a golden
    that a broken map has not yet been allowed to update, which makes the test
    blind to the drift it exists to catch.
    """
    result = engine.run_job({
        "sourceSchema": engine.cpath(target_schema_rel),
        "data": None,
        "dataInline": nquads,
        "focus": focus,
        "startShape": shape,
        "passes": [],
    })
    if not result["validation"]["ok"]:
        raise AssertionError("reverse validation failed for %s @ %s: %s"
                             % (focus, shape, result["validation"]))
    return {k[len(var_ns):]: (v["value"] if isinstance(v, dict) else v)
            for k, v in result["bindings"].items() if k.startswith(var_ns)}


class EGFRInverse(engine.EngineTestCase):
    SCHEMA = "maps/r4/egfr/egfr-target.v1.shex"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.forward = egfr_case.run("egfr-baseline")
        cls.v = cls.forward["_hostValues"]
        cls.GRAPH = cls.forward["nquads"]

    def rev(self, shape, root):
        return reverse(self.SCHEMA, self.GRAPH, root, EGFR_SH + shape, EGFR_V)

    def test_the_materialized_graph_revalidates_against_its_own_target_schema(self):
        for shape, key in (("EGFRResultNode", "result"), ("EGFRQualityNode", "quality"),
                           ("EGFRPersonNode", "person"), ("EGFRUnitNode", "unitIri"),
                           ("EGFRTimeNode", "timeInstant"), ("EGFRRecordNode", "record")):
            with self.subTest(shape=shape):
                self.rev(shape, self.v[key])   # raises if it does not validate

    def test_the_shared_pivot_variables_come_back_unchanged(self):
        """The source-bound pivots -- value, unitCode, effective -- are the
        bindings the pairing actually promises (concept note section 7)."""
        src = self.forward["_sourceBindings"]
        self.assertEqual(self.rev("EGFRResultNode", self.v["result"])["value"],
                         src["value"]["value"])
        self.assertEqual(self.rev("EGFRUnitNode", self.v["unitIri"])["unitCode"],
                         src["unitCode"]["value"])
        self.assertEqual(self.rev("EGFRTimeNode", self.v["timeInstant"])["effective"],
                         src["effective"]["value"])

    def test_the_run_bindings_that_name_nodes_come_back(self):
        back = self.rev("EGFRResultNode", self.v["result"])
        for key in ("unitIri", "quality", "timeInstant", "sourceVersionIri", "resultClass"):
            self.assertEqual(back[key], self.v[key], key)
        self.assertEqual(self.rev("EGFRRecordNode", self.v["record"])["result"],
                         self.v["result"])
        self.assertEqual(self.rev("EGFRQualityNode", self.v["quality"])["person"],
                         self.v["person"])

    def test_two_variable_bound_rdf_types_recover_as_a_set_not_a_mapping(self):
        """MEASURED LIMITATION, recorded rather than smoothed over.

        A node carrying two variable-bound ``rdf:type`` constraints recovers
        the right SET of classes but an arbitrary assignment of classes to
        variables: the inverse cannot tell two same-predicate IRI constraints
        apart.  sh:EGFRResultNode is unaffected because its other rdf:type is
        the constant [sulo:Quantity], which is why the test above can assert
        `resultClass` exactly.

        Consequence: `qualityBranch`/`qualityClass` and
        `personSuloClass`/`personClass` are declared inverse_covered=false in
        the MapContract.  If a future engine or schema change fixes this, this
        test fails and the contract gets updated -- which is the point.
        """
        back = self.rev("EGFRQualityNode", self.v["quality"])
        self.assertEqual({back["qualityBranch"], back["qualityClass"]},
                         {self.v["qualityBranch"], self.v["qualityClass"]})
        self.assertNotEqual((back["qualityBranch"], back["qualityClass"]),
                            (self.v["qualityBranch"], self.v["qualityClass"]),
                            "the assignment is now correct; update the MapContract's "
                            "inverse_coverage_note and inverse_covered flags")


class BPInverse(engine.EngineTestCase):
    """Gate 3: the inverse map recovers all shared bindings per scope."""

    SCHEMA = "maps/r4/bp/bp-target.v1.shex"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.results = {o: bp_case.run("bp-two-panels", o) for o in ("bp-1", "bp-2")}
        cls.GRAPH = "\n".join(r["nquads"] for r in cls.results.values())

    def test_each_panel_recovers_its_own_tuple_and_no_other(self):
        """The whole point: the reverse direction must not cross-join either.

        Both panels live in one graph file, so if the inverse mixed them up it
        would show here.
        """
        recovered = []
        for obs in ("bp-1", "bp-2"):
            v = self.results[obs]["_hostValues"]
            sys_back = reverse(self.SCHEMA, self.GRAPH, v["sysResult"],
                               BP_SH + "BPSystolicQuantityNode", BP_V)
            dia_back = reverse(self.SCHEMA, self.GRAPH, v["diaResult"],
                               BP_SH + "BPDiastolicQuantityNode", BP_V)
            recovered.append((obs, sys_back["sysValue"], dia_back["diaValue"]))
            # the two quantities of one panel must point at that panel's qualities
            self.assertEqual(sys_back["sysQuality"], v["sysQuality"])
            self.assertEqual(dia_back["diaQuality"], v["diaQuality"])
            self.assertEqual(sys_back["timeInstant"], v["timeInstant"])
            self.assertEqual(dia_back["timeInstant"], v["timeInstant"])

        self.assertEqual(sorted(recovered),
                         [("bp-1", "120", "80"), ("bp-2", "105", "70")])

    def test_the_panel_record_revalidates_against_its_own_entry_shape(self):
        """Both panels have a diastolic component, so the entry shape that
        produced them is the WithDiastolic alternative.  Validating against the
        other one must fail -- that is the whole reason the pair exists."""
        for obs in ("bp-1", "bp-2"):
            with self.subTest(resource=obs):
                v = self.results[obs]["_hostValues"]
                back = reverse(self.SCHEMA, self.GRAPH, v["panelRecord"],
                               BP_SH + "BPPanelRecordNodeWithDiastolic", BP_V)
                self.assertEqual(back["timeInstant"], v["timeInstant"])
                self.assertEqual(back["sourceVersionIri"], v["sourceVersionIri"])
                self.assertEqual(back["recordClass"],
                                 "https://w3id.org/ontostart/fhir2sulo/ObservationRecord")
                # both members come back; the assignment to sysResult/diaResult is
                # not recoverable, because the inverse cannot tell two arcs of the
                # same predicate apart.  Recorded in the MapContract.
                self.assertEqual({back["sysResult"], back["diaResult"]},
                                 {v["sysResult"], v["diaResult"]})

    def test_the_wrong_alternative_entry_shape_does_not_validate(self):
        v = self.results["bp-1"]["_hostValues"]
        with self.assertRaises(AssertionError):
            reverse(self.SCHEMA, self.GRAPH, v["panelRecord"],
                    BP_SH + "BPPanelRecordNode", BP_V)

    def test_a_panel_without_a_diastolic_component_uses_the_other_alternative(self):
        omitted = bp_case.run("bp-component-omitted", "bp-1")
        v = omitted["_hostValues"]
        back = reverse(self.SCHEMA, omitted["nquads"],
                       v["panelRecord"], BP_SH + "BPPanelRecordNode", BP_V)
        self.assertEqual(back["sysResult"], v["sysResult"])

    def test_the_shared_unit_and_times_come_back(self):
        v = self.results["bp-1"]["_hostValues"]
        self.assertEqual(
            reverse(self.SCHEMA, self.GRAPH, v["unitIri"], BP_SH + "BPUnitNode", BP_V)["sysUnit"],
            "mm[Hg]")
        self.assertEqual(
            reverse(self.SCHEMA, self.GRAPH, v["timeInstant"], BP_SH + "BPTimeNode",
                    BP_V)["effective"],
            "2026-09-02T09:00:00Z")


class EncounterInverse(engine.EngineTestCase):
    SCHEMA = "maps/r4/encounter/encounter-target.v1.shex"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        forward = encounter_case.run("enc-baseline")
        cls.v = forward["_hostValues"]
        cls.GRAPH = forward["nquads"]

    def test_the_endpoints_and_the_roles_come_back(self):
        start = reverse(self.SCHEMA, self.GRAPH, self.v["startTime"],
                        ENC_SH + "StartTimeNode", ENC_V)
        end = reverse(self.SCHEMA, self.GRAPH, self.v["endTime"],
                      ENC_SH + "EndTimeNode", ENC_V)
        self.assertEqual(start["start"], "2026-09-02T14:00:00Z")
        self.assertEqual(end["end"], "2026-09-02T14:30:00Z")

        patient = reverse(self.SCHEMA, self.GRAPH, self.v["patientRole"],
                          ENC_SH + "PatientRoleNode", ENC_V)
        self.assertEqual(patient["person"], self.v["person"])
        practitioner = reverse(self.SCHEMA, self.GRAPH, self.v["practitionerRole"],
                            ENC_SH + "PractitionerRoleNode", ENC_V)
        self.assertEqual(practitioner["practitioner"], self.v["practitioner"])

    def test_the_interval_recovers_both_endpoints(self):
        back = reverse(self.SCHEMA, self.GRAPH, self.v["interval"],
                       ENC_SH + "TimeIntervalNode", ENC_V)
        self.assertEqual({back["startTime"], back["endTime"]},
                         {self.v["startTime"], self.v["endTime"]})


if __name__ == "__main__":
    unittest.main()
