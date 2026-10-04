"""The person index belongs in the graph key, because it changes the graph.

Enabling an index re-keys entity IRIs. Before DR-016 the index was not one of
the graph key's inputs, so the **same key** named two graphs with different
content. For a content-addressed store that is the one intolerable failure:
it would believe it already held the graph and never supersede it, or
overwrite one with the other and keep no lineage between them.

With the digest in the key, enabling an index gives every affected graph a new
key, and the v1-to-v2 supersession machinery that already exists carries out
the migration. No bespoke migrator is needed, which is the point.
"""

import unittest

from fhir_sulo.provenance.run_records import RunInputs
from fhir_sulo.store.graph_key import CONTENT_FIELDS, KEY_SPEC_VERSION, subject_key

BASE = dict(
    source_canonical_url="https://mumc.example/fhir/Observation/o1",
    source_version_id="1",
    source_json_digest="sha256:v1",
    map_id="egfr-r4",
    map_semantic_version="0.1.0",
    pairing_hash="sha256:pairing-aaaa",
    sulo_version="0.2.12",
    domain_ontology_version="unresolved:R1",
    terminology_snapshot="tx-2026-09-29",
    policy_version="pv",
    engine_build="shex@1.0.0-alpha.33",
    renderer_id="fhir_sulo.ingest.fhir_rdf/0.1.0",
)


class TheIndexIsAKeyInput(unittest.TestCase):
    def test_it_is_declared_among_the_content_fields(self):
        self.assertIn("person_index_digest", CONTENT_FIELDS)

    def test_two_indexes_give_two_graph_keys(self):
        """The collision this closes."""
        a = RunInputs(**BASE, person_index_digest="sha256:aaa").graph_key
        b = RunInputs(**BASE, person_index_digest="sha256:bbb").graph_key
        self.assertNotEqual(a, b)

    def test_no_index_is_an_explicit_token_not_an_empty_string(self):
        """So "no index" and "some index" cannot hash alike -- the rule the
        graph key already applies to every other field."""
        self.assertEqual(RunInputs(**BASE).person_index_digest, "none")
        self.assertNotEqual(
            RunInputs(**BASE).graph_key,
            RunInputs(**BASE, person_index_digest="sha256:aaa").graph_key)

    def test_an_empty_digest_is_refused(self):
        from fhir_sulo.store.graph_key import GraphKeyError

        with self.assertRaises(GraphKeyError):
            RunInputs(**BASE, person_index_digest="").graph_key

    def test_the_key_spec_was_bumped(self):
        """Adding a content field re-keys every graph in the store, which is a
        decision record, not an implementation detail."""
        self.assertEqual(KEY_SPEC_VERSION, "graph-key/2")


class TheMigrationUsesSupersessionNotABespokeTool(unittest.TestCase):
    def test_the_subject_key_is_unchanged_by_the_index(self):
        """The replacement slot is (source resource, map). Both graphs land in
        the SAME slot, which is exactly what makes the new one supersede the
        old rather than sit beside it."""
        before = RunInputs(**BASE)
        after = RunInputs(**BASE, person_index_digest="sha256:aaa")
        self.assertEqual(subject_key(before.key_inputs()),
                         subject_key(after.key_inputs()))
        self.assertNotEqual(before.graph_key, after.graph_key)

    def test_the_key_recomputes_from_the_run_record_alone(self):
        """An archived correction has to stay verifiable."""
        from fhir_sulo.contracts import TransformStatus
        from fhir_sulo.provenance.run_records import build_run_record
        from fhir_sulo.store.graph_key import graph_key_from_run_record

        inputs = RunInputs(**BASE, person_index_digest="sha256:aaa")
        record = build_run_record(inputs, status=TransformStatus.MAPPED,
                                  quads=("<a> <b> <c> .",))
        self.assertEqual(graph_key_from_run_record(record), inputs.graph_key)
        self.assertEqual(record.person_index_digest, "sha256:aaa")


if __name__ == "__main__":
    unittest.main(verbosity=2)
