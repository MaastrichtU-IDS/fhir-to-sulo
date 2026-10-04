"""Gate 4 correction semantics and acceptance matrix row "Correction".

    Current graph has only eligible current assertions; earlier versions and
    run records remain auditable.

Three scenarios, plus the invariants that make them trustworthy.
"""

from __future__ import annotations

import unittest

from .support import (  # noqa: F401  (sets sys.path)
    QUADS_V1,
    QUADS_V2,
    mapped_pair,
    rejected_pair,
    run_inputs,
    source_only_pair,
)

from fhir_sulo.store import (
    GraphState,
    LoadAction,
    NamedGraphStore,
    StoreIntegrityError,
    subject_key_from_run_record,
)

T1 = "2026-09-29T10:00:00Z"
T2 = "2026-09-29T11:00:00Z"
T3 = "2026-09-29T12:00:00Z"


class UnchangedReprocessing(unittest.TestCase):
    """Gate 4: "unchanged reprocessing changes no triples"."""

    def test_reprocessing_identical_input_changes_nothing(self):
        inputs = run_inputs()
        result, record = mapped_pair(inputs, QUADS_V1, activity_time=T1)
        store = NamedGraphStore()
        store.load(result, record)

        before_triples = store.current_triples()
        before_digest = store.state_digest()
        before_graphs = dict(store.current)

        result2, record2 = mapped_pair(inputs, QUADS_V1, activity_time=T2)
        outcome = store.load(result2, record2)

        self.assertEqual(outcome.action, LoadAction.UNCHANGED)
        self.assertFalse(outcome.changed)
        self.assertEqual(outcome.triples_added, 0)
        self.assertEqual(outcome.triples_removed, 0)
        self.assertEqual(store.current_triples(), before_triples)
        self.assertEqual(store.state_digest(), before_digest)
        self.assertEqual(store.current, before_graphs)
        self.assertEqual(len(store.archive), 0)

    def test_the_second_run_is_still_recorded(self):
        """No-op for the graph, not for the audit log.

        Hiding a run because it changed nothing would make the ledger a record
        of changes rather than a record of runs, and "when was this last
        confirmed against the source?" would become unanswerable.
        """
        inputs = run_inputs()
        store = NamedGraphStore()
        store.load(*mapped_pair(inputs, QUADS_V1, activity_time=T1))
        store.load(*mapped_pair(inputs, QUADS_V1, activity_time=T2))
        self.assertEqual(len(store.runs), 2)

    def test_a_key_collision_with_different_triples_is_an_error_not_an_overwrite(self):
        """If this ever fires, the key is missing an input.

        The store must not resolve it by overwriting: that would silently
        accept a graph key that is not a function of the content-determining
        inputs, and every idempotence guarantee downstream would be void.
        """
        inputs = run_inputs()
        store = NamedGraphStore()
        store.load(*mapped_pair(inputs, QUADS_V1, activity_time=T1))
        result, record = mapped_pair(inputs, QUADS_V2, activity_time=T2)
        with self.assertRaises(StoreIntegrityError) as caught:
            store.load(result, record)
        self.assertIn("function of every input", str(caught.exception))


class VersionOneToVersionTwo(unittest.TestCase):
    """Gate 4: version 2 removes stale version-1 assertions from the *current*
    graph while preserving version-1 lineage."""

    def setUp(self):
        self.v1 = run_inputs(version_id="1", json_digest="sha256:v1")
        self.v2 = run_inputs(version_id="2", json_digest="sha256:v2")
        self.store = NamedGraphStore()
        self.r1, self.rec1 = mapped_pair(self.v1, QUADS_V1, activity_time=T1)
        self.r2, self.rec2 = mapped_pair(self.v2, QUADS_V2, activity_time=T2)
        self.store.load(self.r1, self.rec1)
        self.outcome = self.store.load(self.r2, self.rec2)

    def test_version_two_replaces_version_one_in_the_current_graph(self):
        self.assertEqual(self.outcome.action, LoadAction.REPLACED)
        self.assertEqual(self.outcome.superseded_graph_key, self.rec1.output_graph_key)
        self.assertEqual(len(self.store.current), 1)
        self.assertEqual(self.store.current_triples(), tuple(sorted(QUADS_V2)))

    def test_no_version_one_triple_survives_in_the_current_graph(self):
        stale = set(QUADS_V1) - set(QUADS_V2)
        self.assertTrue(stale, "the fixture must actually differ between versions")
        self.assertEqual(stale & set(self.store.current_triples()), set())

    def test_version_one_remains_retrievable_and_marked_superseded(self):
        archived = self.store.graph(self.rec1.output_graph_key)
        self.assertIsNotNone(archived)
        self.assertEqual(archived.state, GraphState.SUPERSEDED)
        self.assertEqual(archived.quads, tuple(sorted(QUADS_V1)))
        self.assertEqual(archived.superseded_by_graph_key, self.rec2.output_graph_key)

    def test_version_one_run_record_is_preserved_and_marked_superseded(self):
        stored = self.store.runs.get(self.rec1.run_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.superseded_by, self.rec2.run_id)
        self.assertEqual(stored.output_graph_key, self.rec1.output_graph_key)
        self.assertEqual(stored.source_version_id, "1")

    def test_marking_superseded_changes_nothing_else_on_the_record(self):
        """"Immutable metadata for the run, even when the current derived
        graph is replaced by a correction" - plan section 3."""
        stored = self.store.runs.get(self.rec1.run_id)
        for field in self.rec1.__dataclass_fields__:
            if field == "superseded_by":
                continue
            with self.subTest(field=field):
                self.assertEqual(getattr(stored, field), getattr(self.rec1, field))

    def test_a_run_cannot_be_superseded_twice_by_different_runs(self):
        with self.assertRaises(StoreIntegrityError):
            self.store.runs.mark_superseded(self.rec1.run_id, "run-somebody-else")

    def test_both_source_versions_remain_registered(self):
        versions = self.store.sources.versions_of(
            "https://fhir.example/Observation/egfr-456"
        )
        self.assertEqual({v.version_id for v in versions}, {"1", "2"})

    def test_history_lists_both_graphs_in_order(self):
        subject = subject_key_from_run_record(self.rec1)
        history = self.store.history(subject)
        self.assertEqual(
            [g.graph_key for g in history],
            [self.rec1.output_graph_key, self.rec2.output_graph_key],
        )

    def test_a_version_id_reused_with_different_content_is_rejected(self):
        """A FHIR server that edits in place breaks version-based correction.

        Absorbing it silently would leave the store believing version 1 is
        still what it first saw.
        """
        conflicting = run_inputs(version_id="1", json_digest="sha256:different")
        result, record = mapped_pair(conflicting, QUADS_V2, activity_time=T3)
        with self.assertRaises(StoreIntegrityError) as caught:
            self.store.load(result, record)
        self.assertIn("reuses a versionId", str(caught.exception))


class EnteredInError(unittest.TestCase):
    """Concept note section 2: an error status suppresses clinical assertions
    from that resource; it does not erase the source record."""

    def setUp(self):
        self.v1 = run_inputs(version_id="1", json_digest="sha256:v1")
        self.v2 = run_inputs(version_id="2", json_digest="sha256:v2-error")
        self.store = NamedGraphStore()
        self.store.load(*mapped_pair(self.v1, QUADS_V1, activity_time=T1))
        self.result, self.record = source_only_pair(
            self.v2,
            activity_time=T2,
            reason="status entered-in-error: no clinical assertions",
        )
        self.outcome = self.store.load(self.result, self.record)

    def test_clinical_assertions_are_removed_from_the_current_graph(self):
        self.assertEqual(self.outcome.action, LoadAction.INVALIDATED)
        self.assertEqual(self.store.current_triples(), ())
        self.assertEqual(len(self.store.current), 0)

    def test_the_source_record_is_retained_for_both_versions(self):
        versions = self.store.sources.versions_of(
            "https://fhir.example/Observation/egfr-456"
        )
        self.assertEqual({v.version_id for v in versions}, {"1", "2"})

    def test_the_retracted_graph_stays_auditable_with_a_reason(self):
        archived = self.store.graph(self.outcome.superseded_graph_key)
        self.assertEqual(archived.state, GraphState.INVALIDATED)
        self.assertEqual(archived.quads, tuple(sorted(QUADS_V1)))
        self.assertIn("entered-in-error", archived.state_reason)
        self.assertEqual(archived.invalidated_by_run_id, self.record.run_id)

    def test_a_rejected_result_may_not_carry_quads(self):
        """Enforced by the frozen contract, asserted here so a regression in
        the store cannot route quads around it."""
        from fhir_sulo.contracts import TransformResult, TransformStatus

        with self.assertRaises(ValueError):
            TransformResult(
                status=TransformStatus.REJECTED,
                map_id="egfr-r4",
                pairing_hash="x",
                source_canonical_url="u",
                source_version_id="1",
                output_graph_key="k",
                target_quads=QUADS_V1,
                rejection_reason="nope",
            )

    def test_an_error_on_a_resource_with_no_current_graph_is_a_no_op(self):
        store = NamedGraphStore()
        result, record = rejected_pair(
            run_inputs(version_id="7", json_digest="sha256:v7"),
            activity_time=T3,
            reason="status entered-in-error",
        )
        outcome = store.load(result, record)
        self.assertEqual(outcome.action, LoadAction.HELD)
        self.assertFalse(outcome.changed)
        self.assertEqual(store.current_triples(), ())
        self.assertEqual(len(store.sources), 1)


class StoreIntegrity(unittest.TestCase):
    def test_a_result_and_record_that_disagree_are_refused(self):
        inputs = run_inputs()
        other = run_inputs(version_id="2", json_digest="sha256:v2")
        result, _ = mapped_pair(inputs, QUADS_V1, activity_time=T1)
        _, record = mapped_pair(other, QUADS_V2, activity_time=T1)
        with self.assertRaises(StoreIntegrityError):
            NamedGraphStore().load(result, record)

    def test_a_record_whose_key_does_not_match_its_fields_is_refused(self):
        import dataclasses

        inputs = run_inputs()
        result, record = mapped_pair(inputs, QUADS_V1, activity_time=T1)
        tampered = dataclasses.replace(record, terminology_snapshot="tx-tampered")
        with self.assertRaises(StoreIntegrityError) as caught:
            NamedGraphStore().load(result, tampered)
        self.assertIn("recomputable from the audit record", str(caught.exception))

    def test_state_digest_is_reproducible_from_a_clean_store(self):
        """Gate 4: "a clean deployment produces identical graph hashes"."""
        inputs = run_inputs()
        digests = []
        for _ in range(2):
            store = NamedGraphStore()
            store.load(*mapped_pair(inputs, QUADS_V1, activity_time=T1))
            store.load(
                *mapped_pair(
                    run_inputs(version_id="2", json_digest="sha256:v2"),
                    QUADS_V2,
                    activity_time=T2,
                )
            )
            digests.append(store.state_digest())
        self.assertEqual(digests[0], digests[1])

    def test_load_order_does_not_affect_the_current_triple_set(self):
        a = run_inputs(url="https://fhir.example/Observation/a", json_digest="sha256:a")
        b = run_inputs(url="https://fhir.example/Observation/b", json_digest="sha256:b")
        forward, backward = NamedGraphStore(), NamedGraphStore()
        forward.load(*mapped_pair(a, QUADS_V1, activity_time=T1))
        forward.load(*mapped_pair(b, QUADS_V2, activity_time=T2))
        backward.load(*mapped_pair(b, QUADS_V2, activity_time=T2))
        backward.load(*mapped_pair(a, QUADS_V1, activity_time=T1))
        self.assertEqual(forward.current_triples(), backward.current_triples())
        self.assertEqual(forward.state_digest(), backward.state_digest())


if __name__ == "__main__":
    unittest.main()
