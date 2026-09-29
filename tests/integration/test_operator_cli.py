"""The operator interface, exercised the way the operator guide documents it.

    Definition of done: ... an operator can run and inspect a batch without
    editing code. -- plan section 8

That sentence is only true if the documented commands actually work, so the
guide's worked example is a test rather than a transcript someone pasted in
once. Every command in ``docs/fhir-sulo/OPERATOR-GUIDE.md`` appears here.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

import support  # noqa: F401  (sets sys.path)

from fhir_sulo.store import NamedGraphStore, cli as store_cli
from fhir_sulo.store.canonical import canonical_json

ACTIVITY_1 = "2026-09-29T12:00:00Z"
ACTIVITY_2 = "2026-09-29T13:00:00Z"

BASE_INPUTS = {
    "source_canonical_url": "https://fhir.example/Observation/egfr-1",
    "source_version_id": "1",
    "source_json_digest": "sha256:v1",
    "map_id": "egfr-r4",
    "map_semantic_version": "0.1.0",
    "pairing_hash": "sha256:pairing-aaaa",
    "sulo_version": "0.2.12",
    "domain_ontology_version": "unresolved:R1",
    "terminology_snapshot": "tx-2026-09-29",
    "policy_version": "unresolved:R2",
    "engine_build": "shex@1.0.0-alpha.33",
    "contract_version": "0.1.0",
}

QUAD_V1 = (
    "<https://example.org/fhir-sulo/result-1> <https://w3id.org/sulo/hasValue> "
    '"55.0"^^<http://www.w3.org/2001/XMLSchema#decimal> .'
)
QUAD_V2 = QUAD_V1.replace("55.0", "61.0")


def entry(*, version="1", digest="sha256:v1", quad=QUAD_V1, status="mapped", reason=None):
    inputs = dict(BASE_INPUTS, source_version_id=version, source_json_digest=digest)
    blob = {"inputs": inputs, "status": status, "source_status": "final"}
    if status == "mapped":
        blob["quads"] = [quad]
        blob["pivot_variables"] = ["egfr:value"]
        blob["engine_provenance"] = [
            {"quad": quad, "tc": "SULOResult/hasValue",
             "predicate": "https://w3id.org/sulo/hasValue",
             "src": "egfr:value", "frameIndex": 0}
        ]
        blob["frame_origins"] = [
            {"frameIndex": 0, "scope": "result", "keyValues": ["egfr-1"]}
        ]
    else:
        blob["source_status"] = "entered-in-error"
        blob["reason"] = reason or "status entered-in-error: no clinical assertions"
    return blob


def write_batch(path, entries):
    with open(path, "w", encoding="utf-8") as handle:
        for item in entries:
            handle.write(json.dumps(item, sort_keys=True) + "\n")


def run_cli(argv):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        status = store_cli.main(argv)
    return status, buffer.getvalue()


class OperatorWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fhir-sulo-op-")
        self.batch = os.path.join(self.tmp, "batch.jsonl")
        self.state = os.path.join(self.tmp, "store-state.json")
        self.graph = os.path.join(self.tmp, "current.nt")
        self.prov = os.path.join(self.tmp, "prov.nq")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _store(self) -> NamedGraphStore:
        with open(self.state, encoding="utf-8") as handle:
            return NamedGraphStore.from_state(json.load(handle))

    def _load(self, entries, *, activity=ACTIVITY_1):
        write_batch(self.batch, entries)
        return run_cli([
            "load", "--batch", self.batch, "--state", self.state,
            "--graph", self.graph, "--provenance", self.prov,
            "--activity-time", activity,
        ])

    def test_load_reports_what_it_did_and_writes_every_artefact(self):
        status, out = self._load([entry()])
        self.assertEqual(status, 0, out)
        self.assertIn("created", out)
        for path in (self.state, self.graph, self.prov):
            self.assertTrue(os.path.exists(path), path)
        with open(self.graph, encoding="utf-8") as handle:
            self.assertIn("55.0", handle.read())

    def test_reloading_the_same_batch_changes_nothing(self):
        """Gate 4's idempotence, through the interface an operator uses."""
        self._load([entry()])
        with open(self.state, encoding="utf-8") as handle:
            before = json.load(handle)
        before_digest = NamedGraphStore.from_state(before).state_digest()

        status, out = self._load([entry()], activity=ACTIVITY_2)
        self.assertEqual(status, 0, out)
        self.assertIn("unchanged", out)

        with open(self.state, encoding="utf-8") as handle:
            after = json.load(handle)
        self.assertEqual(
            NamedGraphStore.from_state(after).state_digest(), before_digest
        )
        self.assertEqual(before["current"], after["current"])

    def test_a_correction_replaces_the_current_graph_and_keeps_the_old_one(self):
        self._load([entry()])
        status, out = self._load(
            [entry(version="2", digest="sha256:v2", quad=QUAD_V2)], activity=ACTIVITY_2
        )
        self.assertEqual(status, 0, out)
        self.assertIn("replaced", out)

        with open(self.graph, encoding="utf-8") as handle:
            current = handle.read()
        self.assertIn("61.0", current)
        self.assertNotIn("55.0", current)

        store = self._store()
        self.assertEqual(len(store.current), 1)
        self.assertEqual(len(store.archive), 1)
        archived = list(store.archive.values())[0]
        self.assertEqual(archived.source_version_id, "1")
        self.assertIn(QUAD_V1, archived.quads)

    def test_an_entered_in_error_correction_empties_the_current_graph(self):
        self._load([entry()])
        status, out = self._load(
            [entry(version="2", digest="sha256:err", status="source-only")],
            activity=ACTIVITY_2,
        )
        self.assertEqual(status, 0, out)
        self.assertIn("invalidated", out)
        with open(self.graph, encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), "")

        store = self._store()
        self.assertEqual(
            {s.version_id for s in store.sources.versions_of(
                "https://fhir.example/Observation/egfr-1")},
            {"1", "2"},
            "the source record must survive the retraction (concept note section 2)",
        )

    def test_inspect_shows_the_version_history(self):
        self._load([entry()])
        self._load([entry(version="2", digest="sha256:v2", quad=QUAD_V2)],
                   activity=ACTIVITY_2)
        store = self._store()
        subject = store.subjects()[0]

        status, out = run_cli(["inspect", "--state", self.state, "--subject", subject])
        self.assertEqual(status, 0)
        self.assertIn("superseded", out)
        self.assertIn("current", out)
        self.assertIn("v1", out)
        self.assertIn("v2", out)

    def test_run_shows_the_record_and_its_prov_o(self):
        self._load([entry()])
        store = self._store()
        run_id = store.runs.all()[0].run_id
        status, out = run_cli(["run", run_id, "--state", self.state])
        self.assertEqual(status, 0)
        self.assertIn("output_graph_key", out)
        self.assertIn("prov#wasDerivedFrom", out)
        self.assertIn("/_history/1", out)

    def test_verify_recomputes_every_key(self):
        self._load([entry()])
        status, out = run_cli(["verify", "--state", self.state])
        self.assertEqual(status, 0, out)
        self.assertIn("recomputes from its run record", out)

    def test_verify_fails_on_a_tampered_state_file(self):
        """The command has to be able to fail, or it is decoration."""
        self._load([entry()])
        with open(self.state, encoding="utf-8") as handle:
            state = json.load(handle)
        state["runs"][0]["terminology_snapshot"] = "tx-tampered"
        with open(self.state, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(state))
        status, out = run_cli(["verify", "--state", self.state])
        self.assertEqual(status, 1)
        self.assertIn("does not match", out)

    def test_key_computes_a_graph_key_from_a_json_file(self):
        path = os.path.join(self.tmp, "inputs.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(BASE_INPUTS, handle)
        status, out = run_cli(["key", "--inputs", path])
        self.assertEqual(status, 0)
        self.assertIn("urn:fhir-sulo:g:", out)
        self.assertIn("urn:fhir-sulo:s:", out)

    def test_key_names_the_missing_fields_rather_than_guessing(self):
        path = os.path.join(self.tmp, "partial.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"map_id": "egfr-r4"}, handle)
        status, _ = run_cli(["key", "--inputs", path])
        self.assertEqual(status, 2)

    def test_a_bad_line_fails_the_batch_and_names_the_line(self):
        broken = dict(entry())
        broken["engine_provenance"] = []          # lineage that covers nothing
        write_batch(self.batch, [entry(), broken])
        status, _ = run_cli([
            "load", "--batch", self.batch, "--state", self.state,
            "--activity-time", ACTIVITY_1, "--keep-going",
        ])
        self.assertEqual(status, 1)


class StateRoundTrip(unittest.TestCase):
    def test_a_reloaded_store_is_indistinguishable_from_the_original(self):
        from support import QUADS_V1, QUADS_V2, mapped_pair, run_inputs

        store = NamedGraphStore()
        store.load(*mapped_pair(run_inputs(), QUADS_V1, activity_time=ACTIVITY_1))
        store.load(*mapped_pair(
            run_inputs(version_id="2", json_digest="sha256:v2"),
            QUADS_V2, activity_time=ACTIVITY_2,
        ))
        restored = NamedGraphStore.from_state(json.loads(canonical_json(store.to_state())))

        self.assertEqual(restored.state_digest(), store.state_digest())
        self.assertEqual(restored.current_triples(), store.current_triples())
        self.assertEqual(restored.archived_triples(), store.archived_triples())
        self.assertEqual(len(restored.runs), len(store.runs))
        self.assertEqual(restored.subjects(), store.subjects())
        for record in store.runs.all():
            self.assertEqual(restored.runs.get(record.run_id), record)

    def test_supersession_survives_a_round_trip(self):
        """Otherwise a reloaded store would forget that version 1 was replaced."""
        from support import QUADS_V1, QUADS_V2, mapped_pair, run_inputs

        store = NamedGraphStore()
        _r1, rec1 = mapped_pair(run_inputs(), QUADS_V1, activity_time=ACTIVITY_1)
        store.load(_r1, rec1)
        r2, rec2 = mapped_pair(
            run_inputs(version_id="2", json_digest="sha256:v2"),
            QUADS_V2, activity_time=ACTIVITY_2,
        )
        store.load(r2, rec2)

        restored = NamedGraphStore.from_state(json.loads(canonical_json(store.to_state())))
        self.assertEqual(restored.runs.get(rec1.run_id).superseded_by, rec2.run_id)

    def test_an_unknown_state_version_is_refused(self):
        with self.assertRaises(Exception):
            NamedGraphStore.from_state({"state_version": 999})


if __name__ == "__main__":
    unittest.main()
