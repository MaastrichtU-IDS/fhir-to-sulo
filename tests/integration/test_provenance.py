"""PROV-O linkage from the derived graph to its source. Concept note section 7.

    Link output to its source with PROV-O and retain the ShEx.js per-quad
    lineage report. A correction computes a replacement graph and removes
    stale derived assertions; source versions remain traceable.
"""

from __future__ import annotations

import unittest

from fhir_sulo.contracts import CONTRACT_VERSION

from .support import (  # noqa: F401  (sets sys.path)
    QUADS_V1,
    QUADS_V2,
    mapped_pair,
    run_inputs,
    source_only_pair,
)

from fhir_sulo.provenance import (
    FSP,
    PROV,
    ProvenanceEmitter,
    invalidation_quads,
    registry_graph_iri,
    result_lineage_report,
    revision_quads,
    run_graph_iri,
    run_provenance_quads,
    source_entity_iri,
)
from fhir_sulo.store import NamedGraphStore  # noqa: E402

T1 = "2026-09-29T10:00:00Z"
T2 = "2026-09-29T11:00:00Z"


def has(quads, subject_fragment, predicate, object_fragment=None):
    for quad in quads:
        if subject_fragment in quad and predicate in quad:
            if object_fragment is None or object_fragment in quad:
                return True
    return False


class DerivedGraphLinksToItsSource(unittest.TestCase):
    def setUp(self):
        self.inputs = run_inputs()
        self.result, self.record = mapped_pair(self.inputs, QUADS_V1, activity_time=T1)
        self.quads = run_provenance_quads(self.record, source_status="final")

    def test_the_source_entity_is_the_version_specific_fhir_iri(self):
        """Concept note section 4 writes it with the _history segment."""
        self.assertEqual(
            source_entity_iri("https://fhir.example/Observation/egfr-456", "1"),
            "https://fhir.example/Observation/egfr-456/_history/1",
        )

    def test_an_already_version_specific_url_is_not_double_suffixed(self):
        url = "https://fhir.example/Observation/egfr-456/_history/3"
        self.assertEqual(source_entity_iri(url, "3"), url)

    def test_the_graph_was_derived_from_the_source_version(self):
        self.assertTrue(
            has(self.quads, self.record.output_graph_key, PROV + "wasDerivedFrom",
                "/_history/1")
        )

    def test_the_graph_was_generated_by_the_run_activity(self):
        self.assertTrue(
            has(self.quads, self.record.output_graph_key, PROV + "wasGeneratedBy",
                self.record.run_id)
        )

    def test_the_activity_used_the_source_and_the_map_plan(self):
        self.assertTrue(has(self.quads, self.record.run_id, PROV + "used", "/_history/1"))
        self.assertTrue(has(self.quads, self.record.run_id, PROV + "used", "urn:fhir-sulo:map:"))

    def test_the_map_pairing_is_a_prov_plan_carrying_its_hash(self):
        self.assertTrue(has(self.quads, "urn:fhir-sulo:map:", "type", PROV + "Plan"))
        self.assertTrue(
            has(self.quads, "urn:fhir-sulo:map:", FSP + "pairingHash", "sha256:pairing-aaaa")
        )

    def test_the_engine_build_is_attributed_to_a_software_agent(self):
        self.assertTrue(has(self.quads, "urn:fhir-sulo:agent:", "type", PROV + "SoftwareAgent"))
        self.assertTrue(
            has(self.quads, self.record.output_graph_key, PROV + "wasAttributedTo",
                "urn:fhir-sulo:agent:")
        )

    def test_every_run_record_field_that_pins_a_version_is_emitted(self):
        for term, value in (
            (FSP + "suloVersion", "0.2.12"),
            (FSP + "terminologySnapshot", "tx-2026-09-29"),
            (FSP + "policyVersion", "unresolved:R2"),
            (FSP + "domainOntologyVersion", "unresolved:R1"),
            (FSP + "engineBuild", "shex@1.0.0-alpha.33"),
            (FSP + "contractVersion", CONTRACT_VERSION),
        ):
            with self.subTest(term=term):
                self.assertTrue(has(self.quads, "", term, value), term)

    def test_provenance_lands_in_its_own_named_graph(self):
        """It must never be mixed into the semantic layer, or Gate 4's
        "unchanged reprocessing changes no triples" becomes uncheckable."""
        expected = run_graph_iri(self.record.run_id)
        for quad in self.quads:
            self.assertTrue(quad.rstrip().endswith("<%s> ." % expected), quad)

    def test_output_is_deterministic(self):
        self.assertEqual(
            self.quads, run_provenance_quads(self.record, source_status="final")
        )


class CorrectionEdges(unittest.TestCase):
    def setUp(self):
        self.v1 = run_inputs(version_id="1", json_digest="sha256:v1")
        self.v2 = run_inputs(version_id="2", json_digest="sha256:v2")
        self.store = NamedGraphStore()
        self.r1, self.rec1 = mapped_pair(self.v1, QUADS_V1, activity_time=T1)
        self.r2, self.rec2 = mapped_pair(self.v2, QUADS_V2, activity_time=T2)
        self.store.load(self.r1, self.rec1)
        self.outcome = self.store.load(self.r2, self.rec2)

    def test_version_two_is_a_prov_revision_of_version_one(self):
        quads = revision_quads(
            self.rec2.output_graph_key, self.rec1.output_graph_key, self.rec2
        )
        self.assertTrue(
            has(quads, self.rec2.output_graph_key, PROV + "wasRevisionOf",
                self.rec1.output_graph_key)
        )
        self.assertTrue(
            has(quads, self.rec1.output_graph_key, PROV + "wasInvalidatedBy",
                self.rec2.run_id)
        )

    def test_correction_edges_land_in_the_registry_graph(self):
        quads = revision_quads(
            self.rec2.output_graph_key, self.rec1.output_graph_key, self.rec2
        )
        for quad in quads:
            self.assertTrue(quad.rstrip().endswith("<%s> ." % registry_graph_iri()))

    def test_an_error_retraction_records_that_the_source_is_retained(self):
        quads = invalidation_quads(
            self.rec1.output_graph_key, self.rec2, "status entered-in-error"
        )
        self.assertTrue(
            has(quads, self.rec1.output_graph_key, FSP + "sourceRecordRetained", "true")
        )
        self.assertTrue(
            has(quads, self.rec1.output_graph_key, FSP + "retractionReason",
                "entered-in-error")
        )
        self.assertFalse(
            any("wasInvalidatedBy" in q and "/_history/" in q for q in quads),
            "the SOURCE entity must never be invalidated; only the derived graph is",
        )

    def test_the_emitter_chooses_revision_for_a_replacement(self):
        emitter = ProvenanceEmitter()
        emitter.record_run(self.rec2, self.outcome)
        self.assertTrue(
            has(emitter.quads(), self.rec2.output_graph_key, PROV + "wasRevisionOf",
                self.rec1.output_graph_key)
        )

    def test_the_emitter_chooses_invalidation_for_an_error_status(self):
        store = NamedGraphStore()
        store.load(*mapped_pair(self.v1, QUADS_V1, activity_time=T1))
        result, record = source_only_pair(
            run_inputs(version_id="2", json_digest="sha256:err"),
            activity_time=T2,
            reason="status entered-in-error: no clinical assertions",
        )
        outcome = store.load(result, record)
        emitter = ProvenanceEmitter()
        emitter.record_run(record, outcome, source_status="entered-in-error")
        quads = emitter.quads()
        self.assertTrue(
            has(quads, outcome.superseded_graph_key, FSP + "sourceRecordRetained", "true")
        )
        self.assertFalse(
            any(PROV + "wasRevisionOf" in q for q in quads),
            "an error retraction is not a revision; nothing replaced the graph",
        )

    def test_the_erroneous_status_is_queryable_from_the_graph(self):
        """Negative query NQ2 has to be answerable without the store."""
        result, record = source_only_pair(
            run_inputs(version_id="2", json_digest="sha256:err"),
            activity_time=T2,
            reason="status entered-in-error",
        )
        quads = run_provenance_quads(record, source_status="entered-in-error")
        self.assertTrue(has(quads, "/_history/2", FSP + "sourceStatus", "entered-in-error"))


class UnchangedReprocessingLeavesProvenanceAlone(unittest.TestCase):
    def test_the_derived_graph_keeps_its_original_generating_run(self):
        """A confirming run appends to the ledger; it does not re-attribute
        the graph to itself. Otherwise "who produced this triple" would change
        every time someone re-ran the batch."""
        inputs = run_inputs()
        store = NamedGraphStore()
        r1, rec1 = mapped_pair(inputs, QUADS_V1, activity_time=T1)
        out1 = store.load(r1, rec1)

        emitter = ProvenanceEmitter()
        emitter.record_run(rec1, out1, result_lineage_report(r1, rec1))
        before = emitter.quads()

        r2, rec2 = mapped_pair(inputs, QUADS_V1, activity_time=T2)
        out2 = store.load(r2, rec2)
        self.assertFalse(out2.changed)

        graph = store.graph(rec1.output_graph_key)
        self.assertEqual(graph.generated_by_run_id, rec1.run_id)
        self.assertEqual(before, emitter.quads())

    def test_semantic_and_provenance_graphs_never_share_a_named_graph(self):
        inputs = run_inputs()
        store = NamedGraphStore()
        result, record = mapped_pair(inputs, QUADS_V1, activity_time=T1)
        outcome = store.load(result, record)
        emitter = ProvenanceEmitter()
        emitter.record_run(record, outcome)
        for quad in emitter.quads():
            graph_component = quad.rsplit("<", 1)[-1].rstrip("> .")
            self.assertTrue(
                graph_component.startswith("urn:fhir-sulo:prov:"),
                "provenance quad landed in %r, not a provenance graph" % graph_component,
            )
            self.assertNotEqual(graph_component, record.output_graph_key)


class LineageRdfIsOptional(unittest.TestCase):
    def test_lineage_rdf_is_off_by_default(self):
        inputs = run_inputs()
        result, record = mapped_pair(inputs, QUADS_V1, activity_time=T1)
        emitter = ProvenanceEmitter()
        emitter.record_run(record, None, result_lineage_report(result, record))
        self.assertFalse(any("urn:fhir-sulo:lineage:" in q for q in emitter.quads()))

    def test_lineage_rdf_can_be_turned_on_and_covers_every_quad(self):
        inputs = run_inputs()
        result, record = mapped_pair(inputs, QUADS_V1, activity_time=T1)
        emitter = ProvenanceEmitter(emit_lineage_rdf=True)
        emitter.record_run(record, None, result_lineage_report(result, record))
        nodes = {
            q.split(">", 1)[0] + ">"
            for q in emitter.quads()
            if "urn:fhir-sulo:lineage:" in q.split(">", 1)[0]
        }
        self.assertEqual(len(nodes), len(result.target_quads))


if __name__ == "__main__":
    unittest.main()
