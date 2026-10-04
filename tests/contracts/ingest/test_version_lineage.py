"""One resource across three versions: the ingestion side of Gate 4.

``egfr-456`` exists at three versions in the fixture set:

    v1  fixtures/r4/egfr/egfr-baseline    status=final              55.0
    v2  fixtures/r4/egfr/egfr-corrected   status=corrected          58.5
    v3  fixtures/r4/egfr/egfr-amended     status=amended            58.5 + a note
    v4  fixtures/r4/egfr/egfr-retracted   status=entered-in-error   58.5

Gate 4's correction row is "version 2 removes stale version-1 derived
assertions from the current semantic graph while preserving version-1
lineage". The store (Agent 6) implements the removal; what ingestion owes it
is a lineage with the right shape, and these tests assert exactly that:

* one canonical URL across all three, so the store sees one subject;
* three distinct ``source_json_digest`` values, so a reused ``versionId`` guard
  has something to catch and the replacement path is not short-circuited;
* a stable subject entity IRI, because correcting a result does not change who
  the patient is;
* ``effective[x]`` unchanged while ``meta.lastUpdated`` moves, which is the
  concept note section 2 distinction under the one condition that actually
  tests it.

``Observation.issued`` is deliberately absent from all three. Agent 3's
``maps/r4/egfr/egfr-source.v1.shex`` is CLOSED and does not list it, so a
fixture carrying ``issued`` fails source validation and Gate 4's correction
row could not run on it. That is a shape gap, not a fixture choice - HL7's own
``observation-example-f205-egfr`` carries ``issued`` - and it is reported
separately rather than worked around silently.

The graph-key assertions at the end use Agent 6's ``store.graph_key`` directly
rather than restating its rules, so they fail if the key definition drifts.
"""

from __future__ import annotations

import os
import unittest

from . import _support
from ._support import FIXTURES, read

from fhir_sulo.contracts import CONTRACT_VERSION, EligibilityOutcome  # noqa: E402
from fhir_sulo.ingest import (  # noqa: E402
    MockIdentityService,
    bindings as B,
    ingest_file,
    jsonio,
)
from fhir_sulo.ingest.ntriples import parse  # noqa: E402
from fhir_sulo.store.graph_key import (  # noqa: E402
    GraphKeyInputs,
    graph_key,
    subject_key,
    subject_of,
)

EGFR = os.path.join(FIXTURES, "egfr")
CANONICAL_URL = "https://fhir.example/Observation/egfr-456"
EFFECTIVE = "2026-09-02T14:00:00Z"
XSD = "http://www.w3.org/2001/XMLSchema#"

VERSIONS = [
    ("1", "egfr-baseline", "egfr-456.json"),
    ("2", "egfr-corrected", "egfr-456.json"),
    ("3", "egfr-amended", "egfr-456.json"),
    ("4", "egfr-retracted", "egfr-456.json"),
]


def _ingest(case, name):
    return ingest_file(os.path.join(EGFR, case, name), identity=MockIdentityService())


def _contexts():
    return {v: _ingest(case, name) for v, case, name in VERSIONS}


class TestOneResourceThreeVersions(unittest.TestCase):
    def setUp(self):
        self.ctx = _contexts()

    def test_all_three_share_one_canonical_url(self):
        for version, ctx in self.ctx.items():
            with self.subTest(version=version):
                self.assertEqual(ctx.canonical_url, CANONICAL_URL)

    def test_the_version_ids_are_distinct_and_ordered(self):
        self.assertEqual([c.version_id for c in self.ctx.values()], ["1", "2", "3", "4"])

    def test_the_source_digests_are_all_different(self):
        """A v2 whose bytes matched v1 would not exercise replacement at all,
        and the store's reused-versionId guard would have nothing to catch."""
        digests = [c.source_json_digest for c in self.ctx.values()]
        self.assertEqual(len(set(digests)), len(VERSIONS), digests)
        for d in digests:
            self.assertTrue(d.startswith("sha256:"))

    def test_the_declared_lineage_chain_is_consistent(self):
        import json
        for version, case, _ in VERSIONS[1:]:
            with open(os.path.join(EGFR, case, "case.json"), encoding="utf-8") as fh:
                lineage = json.load(fh)["lineage"]
            with self.subTest(fixture=case):
                self.assertEqual(lineage["resource_id"], "egfr-456")
                self.assertEqual(lineage["canonical_url"], CANONICAL_URL)
                self.assertEqual(lineage["version_id"], version)
                self.assertEqual(lineage["supersedes"], str(int(version) - 1))

    def test_eligibility_follows_the_pinned_status_policy(self):
        self.assertIs(self.ctx["1"].eligibility, EligibilityOutcome.ELIGIBLE)
        self.assertIs(self.ctx["2"].eligibility, EligibilityOutcome.ELIGIBLE)
        self.assertIs(self.ctx["3"].eligibility, EligibilityOutcome.ELIGIBLE)
        self.assertIs(self.ctx["4"].eligibility, EligibilityOutcome.SOURCE_ONLY)
        self.assertIn("entered-in-error", self.ctx["4"].eligibility_reason)

    def test_the_sources_are_distinct_files_with_one_resource_id(self):
        """Same basename in three directories: the file is named after the
        resource it holds, which is also what Agent 3's harness assumes when
        it derives the focus IRI from the filename stem."""
        paths = [os.path.join(EGFR, case, name) for _, case, name in VERSIONS]
        self.assertEqual(len(set(paths)), len(VERSIONS))
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(os.path.isfile(path))
                self.assertEqual(os.path.basename(path), "egfr-456.json")
                self.assertEqual(jsonio.loads(read(path))["id"], "egfr-456")

    def test_no_version_carries_observation_issued(self):
        """Agent 3's egfr source shape is CLOSED and rejects it. Asserted so
        that re-adding issued fails here, next to the explanation, rather than
        as an opaque validation failure three layers away."""
        for version, case, name in VERSIONS:
            with self.subTest(version=version):
                self.assertNotIn("issued", jsonio.loads(read(os.path.join(EGFR, case, name))))

    def test_the_retracted_version_keeps_its_source_record(self):
        """Concept note section 2: entered-in-error suppresses clinical
        assertions; it does not erase the record."""
        nt = self.ctx["4"].rdf_graph
        self.assertIn('"entered-in-error"', nt)
        self.assertIn('"58.5"^^<%sdecimal>' % XSD, nt)
        self.assertIn('"33914-3"', nt)

    def test_the_corrected_value_actually_changed(self):
        self.assertIn('"55.0"^^<%sdecimal>' % XSD, self.ctx["1"].rdf_graph)
        self.assertIn('"58.5"^^<%sdecimal>' % XSD, self.ctx["2"].rdf_graph)
        self.assertNotIn('"55.0"^^', self.ctx["2"].rdf_graph)

    def test_the_three_rendered_graphs_are_all_different(self):
        graphs = [c.rdf_graph for c in self.ctx.values()]
        self.assertEqual(len(set(graphs)), len(VERSIONS))

    def test_the_subject_entity_is_stable_across_the_lineage(self):
        """Correcting a result does not change who the patient is."""
        iris = {c.resolved_references["Observation.subject"].require_entity_iri()
                for c in self.ctx.values()}
        self.assertEqual(len(iris), 1, iris)


class TestTheTimesStayDistinct(unittest.TestCase):
    """Concept note section 2, under the condition that actually tests it.

    A single resource cannot show that effective[x] and meta.lastUpdated are
    held apart, because nothing moves. A correction can.
    """

    def _row(self, case):
        doc = B.load(os.path.join(EGFR, case, "expected-bindings.json"))
        triples = parse(read(os.path.join(EGFR, case, "canonical.nt")))
        return B.extract(doc, triples)["observation"][0]

    def test_effective_is_unchanged_by_the_correction_and_the_retraction(self):
        want = EFFECTIVE + "^^" + XSD + "dateTime"
        for case in ("egfr-corrected", "egfr-amended", "egfr-retracted"):
            self.assertEqual(self._row(case)["effective"], want, case)
        v1 = jsonio.loads(read(os.path.join(EGFR, "egfr-baseline", "egfr-456.json")))
        self.assertEqual(v1["effectiveDateTime"], EFFECTIVE)

    def test_last_updated_moves_and_is_never_the_effective_time(self):
        for case, when in (("egfr-corrected", "2026-09-03T08:15:00Z"),
                           ("egfr-amended", "2026-09-03T16:40:00Z"),
                           ("egfr-retracted", "2026-09-04T11:00:00Z")):
            row = self._row(case)
            with self.subTest(fixture=case):
                self.assertNotEqual(row["lastUpdated"], row["effective"])
                self.assertTrue(row["lastUpdated"].startswith(when))

    def test_a_retraction_moves_last_updated_but_not_the_effective_time(self):
        """An administrative change to the record, not a new observation."""
        v3, v4 = self._row("egfr-amended"), self._row("egfr-retracted")
        self.assertEqual(v3["effective"], v4["effective"])
        self.assertNotEqual(v3["lastUpdated"], v4["lastUpdated"])

    def test_a_retraction_does_not_restate_the_value(self):
        self.assertEqual(self._row("egfr-amended")["value"],
                         self._row("egfr-retracted")["value"])

    def test_the_lineage_tuples_differ_between_versions(self):
        rows = [self._row(c) for c in
                ("egfr-corrected", "egfr-amended", "egfr-retracted")]
        order = ["obsId", "versionId", "status", "effective", "lastUpdated", "value"]
        tuples = {tuple(r[v] for v in order) for r in rows}
        self.assertEqual(len(tuples), 3)


class TestTheAmendmentChangesOnlyTheRecord(unittest.TestCase):
    """v3 amends v2 by adding an Observation.note and nothing else.

    R3's answer accepted a specific consequence: an amendment touching only a
    ``source_only`` element still produces a new graph version, because
    ``source_json_digest`` is a graph-key content field, so the store reports a
    replacement rather than 'unchanged'. These tests pin the *ingestion* half
    of that - that nothing the map binds moved - so if an 'amendment' ever
    quietly carried a clinical change it fails here rather than at the store.
    """

    BOUND_AND_CLINICAL = ("code", "codeSystem", "subjectRef", "effective",
                          "value", "unitSystem", "unitCode", "comparator",
                          "absentReason")

    def _row(self, case):
        doc = B.load(os.path.join(EGFR, case, "expected-bindings.json"))
        triples = parse(read(os.path.join(EGFR, case, "canonical.nt")))
        return B.extract(doc, triples)["observation"][0]

    def test_every_clinical_binding_is_byte_equal_to_its_predecessor(self):
        v2, v3 = self._row("egfr-corrected"), self._row("egfr-amended")
        for var in self.BOUND_AND_CLINICAL:
            with self.subTest(variable=var):
                self.assertEqual(v2[var], v3[var])

    def test_only_the_record_level_bindings_moved(self):
        v2, v3 = self._row("egfr-corrected"), self._row("egfr-amended")
        moved = {k for k in v2 if v2[k] != v3.get(k)}
        self.assertEqual(moved, {"versionId", "status", "lastUpdated", "noteText"})

    def test_the_amendment_is_really_present_in_the_source_rdf(self):
        """Otherwise the test above would pass on an unchanged resource."""
        self.assertEqual(self._row("egfr-corrected")["noteText"], "")
        self.assertTrue(self._row("egfr-amended")["noteText"])

    def test_the_source_digest_differs_even_though_nothing_clinical_did(self):
        v2 = _ingest("egfr-corrected", "egfr-456.json")
        v3 = _ingest("egfr-amended", "egfr-456.json")
        self.assertNotEqual(v2.source_json_digest, v3.source_json_digest)
        self.assertEqual(v2.canonical_url, v3.canonical_url)

    def test_the_amendment_is_eligible(self):
        """R3, answered 2026-10-01. Before that this fixture could not exist."""
        self.assertIs(_ingest("egfr-amended", "egfr-456.json").eligibility,
                      EligibilityOutcome.ELIGIBLE)


class TestGraphKeyShape(unittest.TestCase):
    """The two properties the store depends on, asserted against its own code."""

    def _inputs(self, ctx):
        return GraphKeyInputs(
            source_canonical_url=ctx.canonical_url,
            source_version_id=ctx.version_id,
            source_json_digest=ctx.source_json_digest,
            map_id="egfr-r4",
            map_semantic_version="0.1.0",
            pairing_hash="sha256:pairing-aaaa",
            sulo_version="0.2.12",
            domain_ontology_version="unresolved:R1",
            terminology_snapshot=ctx.terminology_snapshot,
            policy_version="unresolved:R2",
            engine_build="shex@1.0.0-alpha.33",
            renderer_id=ctx.renderer_id,
            person_index_digest="none",
            contract_version=CONTRACT_VERSION,
        )

    def setUp(self):
        self.keys = {v: self._inputs(c) for v, c in _contexts().items()}

    def test_all_three_versions_share_one_subject_key(self):
        subjects = {subject_key(i) for i in self.keys.values()}
        self.assertEqual(len(subjects), 1, subjects)

    def test_each_version_gets_its_own_graph_key(self):
        graphs = {graph_key(i) for i in self.keys.values()}
        self.assertEqual(len(graphs), len(VERSIONS), graphs)

    def test_every_graph_key_resolves_back_to_the_shared_subject(self):
        subject = subject_key(self.keys["1"])
        for version, inputs in self.keys.items():
            with self.subTest(version=version):
                self.assertEqual(subject_of(graph_key(inputs)), subject)

    def test_the_renderer_id_is_in_the_content_key(self):
        """IR-601: a renderer change must re-key rather than read as unchanged."""
        import dataclasses
        before = graph_key(self.keys["2"])
        after = graph_key(dataclasses.replace(
            self.keys["2"], renderer_id="fhir_sulo.ingest.fhir_rdf/9.9.9"))
        self.assertNotEqual(before, after)
        self.assertEqual(subject_of(before), subject_of(after),
                         "a renderer change must not move the replacement slot")


if __name__ == "__main__":
    unittest.main()
