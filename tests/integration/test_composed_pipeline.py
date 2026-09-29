"""The composed path, end to end, on the real maps and the real fixtures.

Before this existed the pipeline was three islands: Agent 2's ingest produced
a `SourceContext` nothing consumed, Agent 3's maps ran only under a test-only
Node script, and Agent 6's store loader was fed only by a synthetic benchmark
generator. Each stage was tested; the pipeline was not.

The load-bearing test here is
:class:`TestTheHostEmitsNoTripleOfItsOwn`. DR-302 requires it, and the
coordinator asked that it now run over the **production maps** rather than the
driver's toy pairs -- that guard is what stands behind "target triple
construction lives in the schemas", so it has to run where it matters.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from fhir_sulo.contracts import TransformStatus  # noqa: E402
from fhir_sulo.engine.docker import EngineImage  # noqa: E402
from fhir_sulo.pipeline.cli import batch_entry  # noqa: E402
from fhir_sulo.pipeline.compose import Pipeline  # noqa: E402

SULO = "https://w3id.org/sulo/"


def requires_docker(test):
    if EngineImage.docker_present():
        return test
    if os.environ.get("FHIR_SULO_REQUIRE_ENGINE") == "1":
        return test          # the gate asked for real evidence; fail, don't skip
    return unittest.skipUnless(False, "docker is unavailable; A SKIP IS NOT A PASS")(test)


_PIPELINES = {}


def pipeline(family: str, quality_mode="per-observation") -> Pipeline:
    key = (family, quality_mode)
    if key not in _PIPELINES:
        image = EngineImage()
        image.ensure_built()
        _PIPELINES[key] = Pipeline.for_family(
            family, REPO, engine=image, quality_mode=quality_mode)
    return _PIPELINES[key]


def fixture(family: str, case: str, name: str) -> Path:
    return REPO / "fixtures/r4" / family / case / name


@requires_docker
class TestFhirJsonToTargetGraph(unittest.TestCase):
    """FHIR JSON in, a loadable TransformResult out."""

    def test_blood_pressure_maps(self):
        out = pipeline("bp").run_file(fixture("bp", "bp-two-panels", "bp-1.json"))
        self.assertIs(out.transform.status, TransformStatus.MAPPED)
        self.assertTrue(out.is_loadable)
        self.assertTrue(out.ntriples)
        self.assertEqual(len(out.transform.lineage), len(out.transform.target_quads))

    def test_egfr_maps(self):
        out = pipeline("egfr").run_file(
            fixture("egfr", "egfr-baseline", "egfr-456.json"))
        self.assertIs(out.transform.status, TransformStatus.MAPPED)
        self.assertTrue(out.ntriples)

    def test_encounter_maps(self):
        out = pipeline("encounter", quality_mode=None).run_file(
            fixture("encounter", "enc-baseline", "enc-9.json"))
        self.assertIs(out.transform.status, TransformStatus.MAPPED)
        self.assertTrue(out.ntriples)

    def test_the_pro_pattern_reaches_the_person(self):
        """Concept note section 2: no hasPatient, no resource shortcut. The
        person is reached only through quantity -> quality -> person."""
        out = pipeline("bp").run_file(fixture("bp", "bp-two-panels", "bp-1.json"))
        predicates = {line.split(" ")[1] for line in out.ntriples}
        self.assertFalse([p for p in predicates if "hasPatient" in p])
        self.assertIn("<%sisFeatureOf>" % SULO, predicates)
        self.assertIn("<%srefersTo>" % SULO, predicates)

    def test_an_omitted_component_leaves_a_hole(self):
        """The conditional passes really are conditional: no diastolic value
        means no diastolic quantity, not a borrowed one."""
        out = pipeline("bp").run_file(
            fixture("bp", "bp-component-omitted", "bp-1.json"))
        self.assertIs(out.transform.status, TransformStatus.MAPPED)
        self.assertTrue(out.run.skipped_passes)
        self.assertFalse([line for line in out.ntriples if "diastolic" in line])

    def test_the_same_input_twice_gives_the_same_graph(self):
        first = pipeline("bp").run_file(fixture("bp", "bp-two-panels", "bp-1.json"))
        second = pipeline("bp").run_file(fixture("bp", "bp-two-panels", "bp-1.json"))
        self.assertEqual(sorted(first.ntriples), sorted(second.ntriples))
        self.assertEqual(first.transform.output_graph_key,
                         second.transform.output_graph_key)


@requires_docker
class TestTheHostEmitsNoTripleOfItsOwn(unittest.TestCase):
    """DR-302's boundary, over the production maps.

    Every quad the composed path produces must name a TripleConstraint that
    the family's own target schema declares. A quad the host had built would
    carry no constraint id, or one the schema never declared. The driver
    checks this; these tests run the check where the real schemas are, because
    passing it on a toy pair proves nothing about the maps that ship.
    """

    CASES = [
        ("bp", "bp-two-panels", "bp-1.json", "per-observation"),
        ("bp", "bp-component-omitted", "bp-1.json", "per-observation"),
        ("egfr", "egfr-baseline", "egfr-456.json", "per-observation"),
        ("encounter", "enc-baseline", "enc-9.json", None),
    ]

    def test_every_quad_names_a_target_schema_constraint(self):
        for family, case, name, mode in self.CASES:
            with self.subTest(family=family, case=case):
                out = pipeline(family, mode).run_file(fixture(family, case, name))
                self.assertIsNotNone(out.run)
                self.assertEqual(out.run.untraced_quads(), ())

    def test_every_quad_is_covered_by_lineage(self):
        for family, case, name, mode in self.CASES:
            with self.subTest(family=family, case=case):
                out = pipeline(family, mode).run_file(fixture(family, case, name))
                covered = {l.quad_index for l in out.transform.lineage}
                self.assertEqual(covered, set(range(len(out.transform.target_quads))))

    def test_each_constraint_id_belongs_to_the_pass_that_used_it(self):
        out = pipeline("bp").run_file(fixture("bp", "bp-two-panels", "bp-1.json"))
        declared = {p.pass_id: p.constraint_ids
                    for p in out.run.result.driver_result.passes}
        for record in out.run.result.driver_result.records:
            self.assertIn(record.constraint_id, declared[record.pass_id])

    def test_the_guard_can_fail(self):
        """A guard that cannot fail is not a guard: forge a host-built quad."""
        from fhir_sulo.engine.driver import DriverResult, QuadRecord
        from fhir_sulo.engine.rdfterms import Quad, Term

        out = pipeline("bp").run_file(fixture("bp", "bp-two-panels", "bp-1.json"))
        genuine = out.run.result.driver_result
        forged = QuadRecord(
            quad=Quad(Term("iri", "urn:x:s"), Term("iri", "urn:x:invented"),
                      Term("literal", "by the host")),
            pass_id=genuine.passes[0].pass_id, constraint_id="tc:9999",
            predicate="urn:x:invented", kind="binding", variables=(), frame=None)
        tampered = DriverResult(records=genuine.records + (forged,),
                                passes=genuine.passes,
                                binding_tree=genuine.binding_tree, diagnostics=())
        self.assertEqual(tampered.untraced_quads(), (len(genuine.records),))


@requires_docker
class TestIneligibleSourcesNeverReachAGraph(unittest.TestCase):
    """`TransformResult` refuses target quads on source-only and rejected, so
    an ineligible resource must not be mapped and then stripped."""

    def test_entered_in_error_yields_source_only_with_no_quads(self):
        out = pipeline("egfr").run_file(
            fixture("egfr", "egfr-entered-in-error", "egfr-456-eie.json"))
        self.assertIsNot(out.transform.status, TransformStatus.MAPPED)
        self.assertEqual(out.transform.target_quads, ())
        self.assertFalse(out.is_loadable)

    def test_an_ambiguous_reference_is_not_a_person(self):
        """Concept note section 2: an ambiguous reference never silently
        merges, so there is no graph rather than a graph with a guess."""
        out = pipeline("egfr").run_file(
            fixture("egfr", "egfr-reference-ambiguous", "egfr-456-ambigref.json"))
        self.assertIsNot(out.transform.status, TransformStatus.MAPPED)
        self.assertEqual(out.transform.target_quads, ())
        self.assertTrue(out.notes)

    def test_an_unresolvable_reference_is_not_a_person(self):
        out = pipeline("egfr").run_file(
            fixture("egfr", "egfr-reference-unresolvable", "egfr-456-badref.json"))
        self.assertIsNot(out.transform.status, TransformStatus.MAPPED)
        self.assertEqual(out.transform.target_quads, ())


@requires_docker
class TestTheStoreSeam(unittest.TestCase):
    """The batch file is the seam Agent 6's loader reads. Until now its only
    producer was the synthetic benchmark generator."""

    def batch_for(self, family, case, name, mode="per-observation"):
        out = pipeline(family, mode).run_file(fixture(family, case, name))
        return out, batch_entry(out, engine_build="test", sulo_version="0.2.12",
                                domain_ontology_version="test",
                                policy_version="policies/v1")

    def test_a_mapped_entry_carries_quads_and_provenance(self):
        out, entry = self.batch_for("bp", "bp-two-panels", "bp-1.json")
        self.assertEqual(entry["status"], "mapped")
        self.assertEqual(len(entry["quads"]), len(out.ntriples))
        self.assertEqual(len(entry["engine_provenance"]), len(out.ntriples))
        self.assertTrue(entry["pivot_variables"])
        self.assertEqual(sorted(entry["inputs"]), sorted([
            "source_canonical_url", "source_version_id", "source_json_digest",
            "map_id", "map_semantic_version", "pairing_hash", "sulo_version",
            "domain_ontology_version", "terminology_snapshot", "policy_version",
            "engine_build", "renderer_id", "contract_version"]))

    def test_a_non_mapped_entry_carries_a_reason_and_no_quads(self):
        """It is written, not skipped: loading it retracts whatever graph the
        store holds, which is how entered-in-error takes effect."""
        _out, entry = self.batch_for(
            "egfr", "egfr-entered-in-error", "egfr-456-eie.json")
        self.assertNotEqual(entry["status"], "mapped")
        self.assertIn("reason", entry)
        self.assertNotIn("quads", entry)

    def test_the_cli_writes_a_batch_the_store_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch = Path(tmp) / "batch.jsonl"
            store = Path(tmp) / "store"
            proc = subprocess.run(
                [sys.executable, "-m", "fhir_sulo.pipeline.cli", "batch",
                 "--family", "bp", "--quality-mode", "per-observation",
                 "--repo", str(REPO), "--out", str(batch), "--load", str(store),
                 str(fixture("bp", "bp-two-panels", "bp-1.json")),
                 str(fixture("bp", "bp-two-panels", "bp-2.json"))],
                capture_output=True, text=True, timeout=1800,
                env=dict(os.environ, PYTHONPATH=str(REPO / "src")))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue((store / "graph.nt").exists())
            lines = [json.loads(l) for l in batch.read_text().splitlines() if l]
            self.assertEqual(len(lines), 2)
            self.assertTrue(all(e["status"] == "mapped" for e in lines))
            graph = (store / "graph.nt").read_text().splitlines()
            self.assertTrue(graph)


if __name__ == "__main__":
    unittest.main()
