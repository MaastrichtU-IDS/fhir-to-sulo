"""Gate 4 correction, driven end to end by the composed pipeline.

    Test a source resource corrected from version 1 to version 2, a status
    changed to ``entered-in-error``, and unchanged reprocessing. -- plan Gate 4

``test_correction.py`` exercises the store's semantics directly and quickly.
This does the same three scenarios through **real FHIR JSON, real ingest, the
reviewed maps and the pinned engine**, so the Gate 4 row rests on what the
pipeline produces rather than on graphs a test author wrote.

Why the version-2 resources are built here
------------------------------------------
The fixture set has no pair of fixtures that are two *versions of the same
resource*: ``egfr-entered-in-error`` is a different resource id
(``egfr-456-eie``), not version 2 of ``egfr-456``. So each scenario starts
from Agent 2's committed ``egfr-456.json`` and applies the edit an EHR would
itself make - a corrected value, or a status change - bumping
``meta.versionId``. Every triple compared is still map output; only the input
edit is synthetic, and it is the edit the scenario is *about*.

Agent 2 has been asked for an ``egfr-corrected`` fixture. When it lands,
``_version_two`` is replaced by loading it and nothing else changes.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from . import mapoutput
from fhir_sulo.store import GraphState, LoadAction, NamedGraphStore

from fhir_sulo.engine.docker import EngineImage
from fhir_sulo.pipeline.compose import Pipeline
from fhir_sulo.pipeline.services import policy_bundle, source_context


def requires_docker(test):
    """Agent 4's convention, reused so the whole suite gates the same way."""
    if EngineImage.docker_present():
        return test
    if os.environ.get("FHIR_SULO_REQUIRE_ENGINE") == "1":
        return test          # the gate asked for real evidence; fail, don't skip
    return unittest.skipUnless(False, "docker is unavailable; A SKIP IS NOT A PASS")(test)

REPO = Path(mapoutput.REPO)
BASELINE = REPO / "fixtures/r4/egfr/egfr-baseline/egfr-456.json"
QUALITY_MODE = "per-observation"   # review item R2; named, never defaulted
T1 = "2026-09-29T10:00:00Z"
T2 = "2026-09-29T11:00:00Z"


@requires_docker
class CorrectionThroughTheRealPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="fhir-sulo-correct-"))
        cls.pipeline = Pipeline.for_family("egfr", REPO, quality_mode=QUALITY_MODE)
        cls.policy_version = policy_bundle(QUALITY_MODE).policy_version
        cls.engine_build = cls.pipeline.engine.build_id()
        cls.v1_json = json.loads(BASELINE.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- helpers ------------------------------------------------------------

    def _run(self, resource: dict, name: str):
        """Real FHIR JSON -> real pipeline outcome."""
        path = self.tmp / ("%s.json" % name)
        path.write_text(json.dumps(resource), encoding="utf-8")
        return self.pipeline.run_context(source_context(path))

    def _load(self, store: NamedGraphStore, outcome, activity_time: str):
        """Key and load, exactly as ``store.cli load`` does from a manifest."""
        import dataclasses

        from fhir_sulo.contracts import CONTRACT_VERSION
        from fhir_sulo.provenance import RunInputs, build_run_record

        source, transform = outcome.source, outcome.transform
        inputs = RunInputs(
            source_canonical_url=source.canonical_url,
            source_version_id=source.version_id,
            source_json_digest=source.source_json_digest,
            map_id=transform.map_id,
            map_semantic_version=transform.pairing_hash,
            pairing_hash=transform.pairing_hash,
            sulo_version="0.2.12",
            domain_ontology_version="unresolved:R1",
            terminology_snapshot=source.terminology_snapshot,
            policy_version=self.policy_version,
            engine_build=self.engine_build,
            renderer_id=source.renderer_id,
            contract_version=CONTRACT_VERSION,
        )
        record = build_run_record(
            inputs,
            status=transform.status,
            quads=transform.target_quads,
            activity_time=activity_time,
        )
        aligned = dataclasses.replace(
            transform, output_graph_key=record.output_graph_key
        )
        return store.load(aligned, record), record

    def _version_two(self, **edits) -> dict:
        resource = copy.deepcopy(self.v1_json)
        resource["meta"] = dict(resource.get("meta", {}), versionId="2")
        for key, value in edits.items():
            if value is None:
                resource.pop(key, None)
            else:
                resource[key] = value
        return resource

    # -- the scenarios ------------------------------------------------------

    def test_version_one_maps_and_loads(self):
        outcome = self._run(self.v1_json, "v1")
        self.assertTrue(outcome.is_loadable, outcome.notes)
        store = NamedGraphStore()
        result, _record = self._load(store, outcome, T1)
        self.assertEqual(result.action, LoadAction.CREATED)
        self.assertGreater(len(store.current_triples()), 10)

    def test_unchanged_reprocessing_changes_no_triples(self):
        """Gate 4, through the engine. Also proves the engine is deterministic
        across two separate invocations, not merely within one."""
        store = NamedGraphStore()
        self._load(store, self._run(self.v1_json, "v1"), T1)
        before, digest = store.current_triples(), store.state_digest()

        outcome, = (self._run(self.v1_json, "v1-again"),)
        result, _record = self._load(store, outcome, T2)

        self.assertEqual(result.action, LoadAction.UNCHANGED)
        self.assertFalse(result.changed)
        self.assertEqual(store.current_triples(), before)
        self.assertEqual(store.state_digest(), digest)
        self.assertEqual(len(store.archive), 0)

    def test_a_corrected_value_replaces_the_stale_assertion(self):
        store = NamedGraphStore()
        v1 = self._run(self.v1_json, "v1")
        self._load(store, v1, T1)

        corrected = self._version_two(
            valueQuantity=dict(self.v1_json["valueQuantity"], value=61.0)
        )
        v2 = self._run(corrected, "v2")
        self.assertTrue(v2.is_loadable, v2.notes)
        result, record2 = self._load(store, v2, T2)

        self.assertEqual(result.action, LoadAction.REPLACED)
        current = set(store.current_triples())

        # The corrected value is present and the stale one is gone, judged on
        # the actual emitted triples rather than on a string a test wrote.
        self.assertTrue(any('"61.0"' in q for q in current))
        self.assertFalse(any('"55.0"' in q for q in current))

        stale = set(v1.transform.target_quads) - set(v2.transform.target_quads)
        self.assertTrue(stale, "the two versions must actually differ")
        self.assertEqual(stale & current, set())

        archived = store.graph(result.superseded_graph_key)
        self.assertEqual(archived.state, GraphState.SUPERSEDED)
        self.assertEqual(set(archived.quads), set(v1.transform.target_quads))
        self.assertEqual(
            store.runs.get(archived.generated_by_run_id).superseded_by, record2.run_id
        )

    def test_entered_in_error_retracts_the_clinical_assertions(self):
        """Concept note section 2, end to end.

        The pipeline never reaches the engine for an ineligible resource, so
        the retraction is the only signal the store gets - which is why the
        non-mapped manifest line must not be filtered out.
        """
        store = NamedGraphStore()
        self._load(store, self._run(self.v1_json, "v1"), T1)
        self.assertGreater(len(store.current_triples()), 10)

        erroneous = self._version_two(status="entered-in-error")
        v2 = self._run(erroneous, "v2-eie")

        self.assertFalse(v2.is_loadable)
        self.assertEqual(v2.transform.target_quads, ())
        self.assertTrue(v2.notes)

        result, _record = self._load(store, v2, T2)
        self.assertEqual(result.action, LoadAction.INVALIDATED)
        self.assertEqual(store.current_triples(), ())

        archived = store.graph(result.superseded_graph_key)
        self.assertEqual(archived.state, GraphState.INVALIDATED)

        versions = {
            s.version_id
            for s in store.sources.versions_of(v2.source.canonical_url)
        }
        self.assertEqual(
            versions, {"1", "2"},
            "the source record must survive the retraction (concept note s2)",
        )

    def test_the_retraction_reason_comes_from_the_status_policy(self):
        """Not a string this test invented."""
        erroneous = self._version_two(status="entered-in-error")
        v2 = self._run(erroneous, "v2-eie-reason")
        reason = " ".join(v2.notes) + " " + " ".join(v2.transform.diagnostics)
        self.assertIn("entered-in-error", reason)

    def test_the_emitted_graph_still_validates_after_the_correction(self):
        """A correction must leave a conforming graph, not merely a smaller one."""
        import importlib.util

        if importlib.util.find_spec("pyshacl") is None:
            self.skipTest("needs pyshacl")
        from fhir_sulo.validation import shapes_check, strictness

        store = NamedGraphStore()
        self._load(store, self._run(self.v1_json, "v1"), T1)
        corrected = self._version_two(
            valueQuantity=dict(self.v1_json["valueQuantity"], value=61.0)
        )
        self._load(store, self._run(corrected, "v2"), T2)

        report = shapes_check.validate_graph(
            "\n".join(store.current_triples()), strictness.CONCEPT_NOTE_LITERAL
        )
        self.assertTrue(report.conforms, report.text)


if __name__ == "__main__":
    unittest.main()
