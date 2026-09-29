"""Competency and negative queries. Plan section 5.

    Which eGFR result, value, unit, and time was reported for this person?
    Which systolic/diastolic pair belongs to each encounter time? Who
    participated in this encounter and in which role?
    Negative queries must find no cross-patient results, erroneous-status
    clinical assertion, or orphan result.
"""

from __future__ import annotations

import unittest

from .support import EX, QUADS_V1, graph_text, mapped_pair, run_inputs, source_only_pair

from fhir_sulo.provenance import ProvenanceEmitter
from fhir_sulo.store import NamedGraphStore
from fhir_sulo.validation import queries, reasoning

try:
    import rdflib

    HAVE_RDFLIB = True
except ImportError:  # pragma: no cover
    HAVE_RDFLIB = False

HAVE_REASONER = reasoning.reasoner_available()
SKIP_ENV = "needs rdflib: .venv/bin/pip install -r requirements-runtime.txt"
SKIP_REASONER = "needs an OWL reasoner: `robot` on PATH, or docker and the pinned ROBOT image"

BP_CLASSES = {
    "systolicClass": EX + "SystolicBloodPressureQuality",
    "diastolicClass": EX + "DiastolicBloodPressureQuality",
}
EXPECTED_BP = {
    ("2026-09-02T09:00:00Z", "120", "80"),
    ("2026-09-02T10:00:00Z", "105", "70"),
}


def load(name):
    graph = rdflib.Graph()
    graph.parse(data=graph_text(name), format="turtle")
    return graph


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
class EgfrCompetencyQuery(unittest.TestCase):
    def test_returns_the_value_unit_and_time_for_the_person(self):
        result = queries.run_query(
            load("egfr-target.ttl"), queries.Q_EGFR,
            bindings={"person": EX + "person-p123"},
        )
        self.assertTrue(result.passed, result.note)
        self.assertEqual(result.row_count, 1)
        row = dict(zip(result.variables, result.rows[0]))
        self.assertEqual(row["value"], "55.0")
        self.assertEqual(row["unitCode"], "mL/min/{1.73_m2}")
        self.assertEqual(row["time"], "2026-09-02T14:00:00Z")
        self.assertEqual(row["person"], EX + "person-p123")

    def test_asking_about_a_different_person_returns_nothing(self):
        """"Distinct people remain distinct" - acceptance row Identity."""
        result = queries.run_query(
            load("egfr-target.ttl"), queries.Q_EGFR,
            bindings={"person": EX + "person-someone-else"},
        )
        self.assertEqual(result.row_count, 0)
        self.assertFalse(result.passed)


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
class BloodPressurePairing(unittest.TestCase):
    """Concept note section 5: the multiset is the assertion, not the count."""

    def _pairs(self, name):
        result = queries.run_query(load(name), queries.Q_BP_PAIRS, bindings=BP_CLASSES)
        return {(row[1], row[2], row[3]) for row in result.rows}

    def test_the_two_panels_keep_their_own_components(self):
        self.assertEqual(self._pairs("bp-two-panels.ttl"), EXPECTED_BP)

    def test_a_persisting_shared_quality_gives_the_same_pairs(self):
        """Review item R2 option A. The pairing comes from the panel record,
        not from the quality node, so either answer to R2 gives the same
        result. Neither this test nor the fixture decides R2."""
        self.assertEqual(self._pairs("bp-two-panels-shared-quality.ttl"), EXPECTED_BP)

    def test_a_cross_joined_graph_is_detected(self):
        """Every individual value is present and the row count is right; only
        the multiset differs. A test that counted rows would pass this."""
        pairs = self._pairs("bp-cross-join.ttl")
        self.assertEqual(len(pairs), 2)
        self.assertNotEqual(pairs, EXPECTED_BP)
        self.assertIn(("2026-09-02T09:00:00Z", "120", "70"), pairs)


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(HAVE_REASONER, SKIP_REASONER)
class EncounterParticipants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.asserted = load("encounter-pro.ttl")
        with reasoning.RobotReasoner() as robot:
            cls.reasoned = robot.reason_and_merge(cls.asserted)

    def test_the_reasoned_graph_answers_who_participated_and_in_which_role(self):
        result = queries.run_query(self.reasoned, queries.Q_PARTICIPANTS)
        self.assertTrue(result.passed, result.note)
        found = {(row[1], row[2]) for row in result.rows}
        self.assertEqual(
            found,
            {
                (EX + "person-p123", EX + "patient-role-enc-9"),
                (EX + "clinician-c7", EX + "clinician-role-enc-9"),
            },
        )

    def test_the_unreasoned_graph_cannot_answer_it(self):
        """Not a defect: PRO puts the person one entailment away. Recorded so
        that the reasoning step is visibly load-bearing."""
        result = queries.run_query(self.asserted, queries.Q_PARTICIPANTS)
        self.assertEqual(result.row_count, 0)

    def test_the_suite_reports_a_failure_rather_than_an_empty_pass(self):
        """An unreasoned run must not look like a passing run."""
        report = queries.run_suite(
            self.asserted, reasoned=False, queries=[queries.Q_PARTICIPANTS]
        )
        self.assertFalse(report.passed)
        self.assertIn("carries no OWL entailments", report.results[0].note)


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
class NegativeQueries(unittest.TestCase):
    def test_the_concept_note_graphs_trip_none_of_them(self):
        for name in ("egfr-target.ttl", "bp-two-panels.ttl", "encounter-pro.ttl"):
            with self.subTest(graph=name):
                report = queries.run_suite(
                    load(name), reasoned=True, queries=queries.NEGATIVE_QUERIES
                )
                self.assertTrue(report.passed, report.summary())

    def test_a_cross_patient_result_is_found(self):
        report = queries.run_query(load("negatives.ttl"), queries.N_CROSS_PATIENT)
        self.assertFalse(report.passed)
        self.assertGreaterEqual(report.row_count, 1)

    def test_an_orphan_result_is_found(self):
        report = queries.run_query(load("negatives.ttl"), queries.N_ORPHAN)
        self.assertFalse(report.passed)
        found = {row[0] for row in report.rows}
        self.assertIn("https://example.org/neg/orphan-unit", found)
        self.assertIn("https://example.org/neg/orphan-result", found)

    def test_a_hasPatient_predicate_is_found_in_any_namespace(self):
        report = queries.run_query(load("negatives.ttl"), queries.N_HAS_PATIENT)
        self.assertFalse(report.passed)
        self.assertTrue(any("hasPatient" in row[1] for row in report.rows))


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
class ErroneousStatusIsUnassertable(unittest.TestCase):
    """Checked twice, because one check would not be enough.

    The store is what actually prevents it: an ineligible result carries no
    quads and retracts any current graph. The query is the independent
    second opinion over the delivered graph plus its provenance, which is
    what an auditor would have.
    """

    def setUp(self):
        self.store = NamedGraphStore()
        v1 = run_inputs(version_id="1", json_digest="sha256:v1")
        self.store.load(*mapped_pair(v1, QUADS_V1, activity_time="2026-09-29T10:00:00Z"))
        v2 = run_inputs(version_id="2", json_digest="sha256:v2-error")
        self.result, self.record = source_only_pair(
            v2,
            activity_time="2026-09-29T11:00:00Z",
            reason="status entered-in-error: no clinical assertions",
        )
        self.outcome = self.store.load(self.result, self.record)

    def test_the_store_leaves_no_clinical_assertion(self):
        self.assertEqual(self.store.current_triples(), ())

    def test_the_query_finds_no_assertion_derived_from_the_erroneous_version(self):
        emitter = ProvenanceEmitter()
        emitter.record_run(self.record, self.outcome, source_status="entered-in-error")
        graph = rdflib.Graph()
        graph.parse(
            data="\n".join(self.store.current_triples()) or "", format="nt"
        )
        prov_graph = rdflib.Graph()
        prov_graph.parse(data=emitter.nquads(), format="nquads")
        for triple in prov_graph:
            graph.add(triple)

        result = queries.run_query(graph, queries.N_ERRONEOUS_STATUS)
        self.assertTrue(result.passed, result.rows)

    def test_the_query_would_catch_it_if_an_assertion_had_survived(self):
        """The negative query has to be able to fail, or it proves nothing."""
        graph = rdflib.Graph()
        graph.parse(
            data="""
            @prefix prov: <http://www.w3.org/ns/prov#> .
            @prefix ex:   <https://example.org/fhir-sulo/> .
            ex:leaked prov:wasDerivedFrom <https://fhir.example/Observation/x/_history/2> .
            <https://fhir.example/Observation/x/_history/2>
                <urn:fhir-sulo:prov#sourceStatus> "entered-in-error" .
            """,
            format="turtle",
        )
        result = queries.run_query(graph, queries.N_ERRONEOUS_STATUS)
        self.assertFalse(result.passed)
        self.assertEqual(result.row_count, 1)


if __name__ == "__main__":
    unittest.main()
