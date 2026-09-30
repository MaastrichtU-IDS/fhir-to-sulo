"""Competency and negative queries, on real map output. Plan section 5.

    Which eGFR result, value, unit, and time was reported for this person?
    Which systolic/diastolic pair belongs to each encounter time? Who
    participated in this encounter and in which role?
    Negative queries must find no cross-patient results, erroneous-status
    clinical assertion, or orphan result.

Review finding M2: these ran on hand-written graphs using ``ex:person-p123``,
``sulo:SpatialObject`` and ``xsd:dateTimeStamp``, none of which the maps emit.
They now run on ``fixtures/expected/*/*/target.nt``. The hand-written
``bp-cross-join.ttl`` is kept, because it is the failure the pairing test has
to be able to detect and no correct map emits it.
"""

from __future__ import annotations

import unittest

from . import mapoutput
from .support import EX, graph_text, mapped_pair, run_inputs, source_only_pair

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
SKIP_FIXTURES = mapoutput.SKIP_NO_FIXTURES

BP_CLASSES = {
    "systolicClass": mapoutput.SYSTOLIC_QUALITY,
    "diastolicClass": mapoutput.DIASTOLIC_QUALITY,
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
@unittest.skipUnless(mapoutput.AVAILABLE, SKIP_FIXTURES)
class EgfrCompetencyQueryOnMapOutput(unittest.TestCase):
    """CQ1 against the graph the eGFR map emits."""

    @classmethod
    def setUpClass(cls):
        cls.item = mapoutput.by_id("egfr-baseline")
        cls.graph = cls.item.graph()

    def _the_person(self):
        """Discovered, not hard-coded: real person IRIs are content hashes."""
        people = set(
            self.graph.subjects(
                rdflib.RDF.type, rdflib.URIRef(mapoutput.EX + "Person")
            )
        )
        self.assertEqual(len(people), 1, people)
        return str(next(iter(people)))

    def test_returns_the_value_unit_and_time_for_the_person(self):
        person = self._the_person()
        result = queries.run_query(
            self.graph, queries.Q_EGFR, bindings={"person": person}
        )
        self.assertTrue(result.passed, result.note)
        self.assertEqual(result.row_count, 1)
        row = dict(zip(result.variables, result.rows[0]))
        self.assertEqual(row["value"], "55.0")
        self.assertEqual(row["unitCode"], "mL/min/{1.73_m2}")
        self.assertEqual(mapoutput.iso_z(row["time"]), "2026-09-02T14:00:00Z")
        self.assertEqual(row["person"], person)

    def test_the_person_iri_is_the_keyed_one_not_the_concept_note_placeholder(self):
        """Guards against this suite drifting back to hand-written graphs."""
        person = self._the_person()
        self.assertNotEqual(person, EX + "person-p123")
        self.assertRegex(person, r"/person-[0-9a-f]{32}$")

    def test_asking_about_a_different_person_returns_nothing(self):
        """"Distinct people remain distinct" - acceptance row Identity."""
        result = queries.run_query(
            self.graph, queries.Q_EGFR,
            bindings={"person": EX + "person-00000000000000000000000000000000"},
        )
        self.assertEqual(result.row_count, 0)
        self.assertFalse(result.passed)

    def test_two_real_patients_results_never_answer_each_others_question(self):
        """``bp-other-patient`` is a genuinely two-patient fixture.

        It holds results for the eGFR patient AND a second person, which is
        the point: it exists so a map that merged them would be caught. So
        the assertion is not "one row" - the eGFR patient legitimately has an
        eGFR result and two BP components here - but that **every row
        returned for a person is about that person**, and that the two
        people's answers are disjoint.
        """
        other = mapoutput.by_id("bp-other-patient")
        combined = rdflib.Graph()
        for triple in self.graph:
            combined.add(triple)
        for triple in other.graph():
            combined.add(triple)

        people = sorted(
            str(p) for p in set(
                combined.subjects(rdflib.RDF.type,
                                  rdflib.URIRef(mapoutput.EX + "Person"))
            )
        )
        self.assertEqual(len(people), 2, people)

        answers = {}
        for person in people:
            result = queries.run_query(
                combined, queries.Q_EGFR, bindings={"person": person}
            )
            rows = [dict(zip(result.variables, row)) for row in result.rows]
            self.assertTrue(rows, "no results for %s" % person)
            for row in rows:
                self.assertEqual(row["person"], person)
            answers[person] = {r["result"] for r in rows}

        first, second = answers[people[0]], answers[people[1]]
        self.assertEqual(
            first & second, set(),
            "a result is being attributed to both patients",
        )


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(mapoutput.AVAILABLE, SKIP_FIXTURES)
class BloodPressurePairingOnMapOutput(unittest.TestCase):
    """CQ2. Concept note section 5: the multiset is the assertion."""

    def _pairs(self, graph):
        result = queries.run_query(graph, queries.Q_BP_PAIRS, bindings=BP_CLASSES)
        return {
            (mapoutput.iso_z(row[1]), row[2], row[3]) for row in result.rows
        }

    def test_the_emitted_two_panel_graph_keeps_its_pairs(self):
        self.assertEqual(
            self._pairs(mapoutput.by_id("bp-two-panels").graph()), EXPECTED_BP
        )

    def test_a_reordered_source_serialisation_gives_the_same_pairs(self):
        self.assertEqual(
            self._pairs(mapoutput.by_id("bp-reordered-serialisation").graph()),
            EXPECTED_BP,
        )

    def test_duplicate_values_across_panels_stay_in_their_own_panels(self):
        """The case where value identity cannot disambiguate the panels."""
        pairs = self._pairs(mapoutput.by_id("bp-duplicate-values").graph())
        self.assertTrue(pairs)
        for _time, systolic, diastolic in pairs:
            self.assertTrue(systolic and diastolic)
        self.assertEqual(len(pairs), len({p[0] for p in pairs}),
                         "each panel time must yield exactly one pair")

    def test_a_cross_joined_graph_is_detected(self):
        """Hand-written on purpose: no correct map emits this.

        Every individual value is present and the row count is right; only
        the pairing differs. A test that counted rows would pass it.
        """
        pairs = self._pairs(load("bp-cross-join.ttl"))
        self.assertEqual(len(pairs), 2)
        self.assertNotEqual(pairs, EXPECTED_BP)
        self.assertIn(("2026-09-02T09:00:00Z", "120", "70"), pairs)

    def test_a_component_omission_does_not_fabricate_a_pair(self):
        """An incomplete panel must yield no pair, not a half-invented one."""
        item = mapoutput.by_id("bp-component-omitted")
        pairs = self._pairs(item.graph())
        for _time, systolic, diastolic in pairs:
            self.assertTrue(systolic and diastolic)


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(HAVE_REASONER, SKIP_REASONER)
@unittest.skipUnless(mapoutput.AVAILABLE, SKIP_FIXTURES)
class EncounterParticipantsOnMapOutput(unittest.TestCase):
    """CQ3, which needs the SULO property chain."""

    @classmethod
    def setUpClass(cls):
        cls.asserted = mapoutput.by_id("enc-baseline").graph()
        with reasoning.RobotReasoner() as robot:
            cls.reasoned = robot.reason_and_merge(cls.asserted)

    def test_the_reasoned_graph_answers_who_participated_and_in_which_role(self):
        result = queries.run_query(self.reasoned, queries.Q_PARTICIPANTS)
        self.assertTrue(result.passed, result.note)
        holders = {row[1] for row in result.rows}
        roles = {row[2] for row in result.rows}
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(len(holders), 2, "patient and clinician must be distinct")
        self.assertEqual(
            roles,
            {mapoutput.EX + "patient-role-enc-9", mapoutput.EX + "clinician-role-enc-9"},
        )

    def test_the_unreasoned_graph_cannot_answer_it(self):
        """Not a defect: PRO puts the person one entailment away. Recorded so
        the reasoning step is visibly load-bearing."""
        result = queries.run_query(self.asserted, queries.Q_PARTICIPANTS)
        self.assertEqual(result.row_count, 0)

    def test_the_suite_reports_a_failure_rather_than_an_empty_pass(self):
        report = queries.run_suite(
            self.asserted, reasoned=False, queries=[queries.Q_PARTICIPANTS]
        )
        self.assertFalse(report.passed)
        self.assertIn("carries no OWL entailments", report.results[0].note)


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(mapoutput.AVAILABLE, SKIP_FIXTURES)
class NegativeQueriesOnMapOutput(unittest.TestCase):
    def test_no_emitted_graph_trips_any_negative_query(self):
        for item in mapoutput.MAPPED:
            with self.subTest(fixture=item.fixture_id):
                report = queries.run_suite(
                    item.graph(), reasoned=True, queries=queries.NEGATIVE_QUERIES
                )
                self.assertTrue(report.passed, report.summary())

    def test_the_whole_batch_together_trips_none_either(self):
        """Cross-patient and orphan are graph-wide: per-fixture is not enough."""
        graph = mapoutput.merged_graph(*[m.fixture_id for m in mapoutput.MAPPED])
        report = queries.run_suite(
            graph, reasoned=True, queries=queries.NEGATIVE_QUERIES
        )
        self.assertTrue(report.passed, report.summary())

    def test_the_negative_queries_can_still_fail(self):
        """Without this, "all pass" would be indistinguishable from "all
        broken"."""
        negatives = load("negatives.ttl")
        for query, expected_rows in (
            (queries.N_CROSS_PATIENT, 2),
            (queries.N_ORPHAN, 2),
            (queries.N_HAS_PATIENT, 1),
        ):
            with self.subTest(query=query.query_id):
                result = queries.run_query(negatives, query)
                self.assertFalse(result.passed)
                self.assertGreaterEqual(result.row_count, expected_rows)


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(mapoutput.AVAILABLE, SKIP_FIXTURES)
class ErroneousStatusIsUnassertable(unittest.TestCase):
    """Driven by the real ``egfr-entered-in-error`` fixture.

    Checked twice, because one check would not be enough. The store is what
    actually prevents it: an ineligible result carries no quads and retracts
    any current graph. The query is the independent second opinion over the
    delivered graph plus its provenance, which is what an auditor would have.
    """

    @classmethod
    def setUpClass(cls):
        cls.baseline = mapoutput.by_id("egfr-baseline")
        cls.erroneous = mapoutput.by_id("egfr-entered-in-error")

    def test_the_fixture_really_is_an_error_status_that_produced_no_graph(self):
        self.assertIsNone(self.erroneous.target_path)
        self.assertEqual(self.erroneous.outcome["declared_by_agent2"], "source-only")
        self.assertTrue(self.erroneous.outcome["agrees_with_agent2"])

    def _store_after_retraction(self):
        store = NamedGraphStore()
        v1 = run_inputs(version_id="1", json_digest="sha256:v1")
        result, record = mapped_pair(
            v1,
            tuple(self.baseline.triples().splitlines()),
            activity_time="2026-09-29T10:00:00Z",
        )
        store.load(result, record)

        v2 = run_inputs(version_id="2", json_digest="sha256:v2-eie")
        bad_result, bad_record = source_only_pair(
            v2,
            activity_time="2026-09-29T11:00:00Z",
            reason="map outcome %s: %s"
            % (
                self.erroneous.map_outcome,
                ", ".join(self.erroneous.outcome["diagnostic"]["elements"]),
            ),
        )
        outcome = store.load(bad_result, bad_record)
        return store, bad_record, outcome

    def test_the_store_leaves_no_clinical_assertion(self):
        store, _record, _outcome = self._store_after_retraction()
        self.assertEqual(store.current_triples(), ())

    def test_the_retraction_reason_comes_from_the_real_map_outcome(self):
        """Not a string a test author invented."""
        _store, record, outcome = self._store_after_retraction()
        self.assertIn("source-shape-nonconformant", outcome.note)
        self.assertIn("Observation.status", outcome.note)

    def test_the_source_record_survives(self):
        store, _record, _outcome = self._store_after_retraction()
        self.assertEqual(
            {s.version_id for s in store.sources.versions_of(
                "https://fhir.example/Observation/egfr-456")},
            {"1", "2"},
        )

    def test_the_query_finds_no_assertion_derived_from_the_erroneous_version(self):
        store, record, outcome = self._store_after_retraction()
        emitter = ProvenanceEmitter()
        emitter.record_run(record, outcome, source_status="entered-in-error")
        graph = rdflib.Graph()
        current = store.current_triples()
        if current:
            graph.parse(data="\n".join(current), format="nt")
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
            @prefix ex:   <https://w3id.org/ontostart/fhir2sulo/> .
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
