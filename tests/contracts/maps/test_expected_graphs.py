"""The expected target graphs and negative outcomes in ``fixtures/expected/``.

Two jobs:

1. **cross-check** -- for all 19 fixtures, the map's own outcome must agree with
   Agent 2's independently declared eligibility.  Two layers authored by two
   agents from the same contract; a disagreement is a finding, not a test to
   relax.  This half needs no Docker and runs in CI.
2. **regression** -- ``fixtures/expected/build.py --check`` re-runs every map on
   every fixture and fails on drift.  This half needs the pinned engine.

No pytest, so the stdlib fallback (`make contracts-stdlib`) covers part 1 too.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

from ._engine import engine, graph

REPO = engine.REPO
EXPECTED = REPO / "fixtures/expected"
FIXTURE_DIRS = sorted(p for p in EXPECTED.glob("*/*") if (p / "outcome.json").is_file())

TARGET_SCHEMAS = {
    "egfr": REPO / "maps/r4/egfr/egfr-target.v1.shex",
    "bp": REPO / "maps/r4/bp/bp-target.v1.shex",
    "encounter": REPO / "maps/r4/encounter/encounter-target.v1.shex",
}

# No "practitioner-": an entity kind is an identity criterion, so it must be
# rigid, and a practitioner IS a person holding a PractitionerRole (DR-010).
ENTITY_PREFIXES = ("<https://w3id.org/ontostart/fhir2sulo/person-",
                   "<https://w3id.org/ontostart/fhir2sulo/quality-")


def outcome(path: Path):
    return json.loads((path / "outcome.json").read_text())


class ExpectedOutcomes(unittest.TestCase):
    def test_there_is_one_expected_outcome_per_agent_2_fixture(self):
        declared = sorted(p.name for p in (REPO / "fixtures/r4").glob("*/*")
                          if p.is_dir() and (p / "case.json").is_file())
        mine = sorted(p.name for p in FIXTURE_DIRS)
        self.assertEqual(mine, declared)
        # derived, not hardcoded: adding a fixture should fail the tests that
        # are actually about that fixture, not an unrelated count.
        self.assertGreaterEqual(len(mine), 19, mine)

    def test_the_map_outcome_agrees_with_agent_2s_declaration(self):
        for path in FIXTURE_DIRS:
            doc = outcome(path)
            with self.subTest(fixture=doc["fixture_id"]):
                case = json.loads((REPO / "fixtures/r4" / doc["family"] / doc["fixture_id"]
                                   / "case.json").read_text())
                self.assertEqual(doc["declared_by_agent2"], case["expected"]["eligibility"])
                self.assertTrue(
                    doc["agrees_with_agent2"],
                    "%s: Agent 2 declares %r but the map outcome is %r. Do not weaken "
                    "either side; this is a finding for the integration lead."
                    % (doc["fixture_id"], doc["declared_by_agent2"], doc["map_outcome"]))

    def test_only_eligible_fixtures_have_a_target_graph(self):
        for path in FIXTURE_DIRS:
            doc = outcome(path)
            with self.subTest(fixture=doc["fixture_id"]):
                has_graph = (path / "target.nt").is_file()
                self.assertEqual(has_graph, doc["declared_by_agent2"] == "eligible")
                self.assertEqual(has_graph, doc["target_graph"] is not None)

    def test_every_negative_outcome_carries_a_diagnostic(self):
        for path in FIXTURE_DIRS:
            doc = outcome(path)
            if doc["map_outcome"] == "mapped":
                continue
            with self.subTest(fixture=doc["fixture_id"]):
                self.assertTrue(
                    doc["diagnostic"],
                    "%s produced no target graph and no reason. A silent rejection is "
                    "the failure mode DR-301 warns about." % doc["fixture_id"])

    def test_the_run_parameters_record_the_unanswered_review_items(self):
        """The graphs are not valid without them, so they are not implicit."""
        for path in FIXTURE_DIRS:
            doc = outcome(path)
            with self.subTest(fixture=doc["fixture_id"]):
                params = doc["run_parameters"]
                self.assertIn(params["quality_identity_mode"],
                              ("per-observation", "persistent-per-person-code"))
                self.assertIn("R2", params["quality_identity_mode_note"])
                self.assertEqual(params["sulo_version"], "0.2.12")

    def test_exactly_the_expected_fixtures_materialize(self):
        """The named list IS the contract; the counts are derived from it.

        Which fixtures produce a semantic graph is a reviewed decision, so it
        is spelled out. How many there are is not, so adding a fixture must
        not fail a test about arithmetic.
        """
        mapped = sorted(outcome(p)["fixture_id"] for p in FIXTURE_DIRS
                        if outcome(p)["map_outcome"] == "mapped")
        self.assertEqual(mapped, [
            "bp-component-omitted", "bp-duplicate-values", "bp-other-patient",
            "bp-reordered-serialisation", "bp-two-panels",
            "egfr-amended", "egfr-baseline",
            "egfr-contained-subject", "egfr-corrected",
            "enc-baseline", "enc-contained-practitioner"])
        not_mapped = sorted(outcome(p)["fixture_id"] for p in FIXTURE_DIRS
                            if outcome(p)["map_outcome"] != "mapped")
        self.assertEqual(len(mapped) + len(not_mapped), len(FIXTURE_DIRS))
        self.assertIn("egfr-retracted", not_mapped)


class ExpectedGraphContents(unittest.TestCase):
    def graphs(self):
        for path in FIXTURE_DIRS:
            if (path / "target.nt").is_file():
                yield outcome(path), graph.parse((path / "target.nt").read_text())

    def test_no_placeholder_person_iri_leaks_into_a_graph(self):
        """Concept note section 2: a FHIR reference is not a person.

        A person IRI derived from `Patient/p123` would contain the FHIR id.
        Every entity and quality IRI must be the identity service's opaque
        32-hex hash instead.
        """
        for doc, triples in self.graphs():
            for s, p, o in triples:
                for term in (s, o):
                    if term.startswith(ENTITY_PREFIXES):
                        with self.subTest(fixture=doc["fixture_id"], term=term):
                            self.assertRegex(term.rsplit("-", 1)[-1][:-1], r"^[0-9a-f]{32}$")

    def test_no_blank_nodes_in_any_expected_graph(self):
        for doc, triples in self.graphs():
            with self.subTest(fixture=doc["fixture_id"]):
                self.assertEqual(graph.blank_nodes(triples), set())

    def test_no_owl_sameAs_in_any_expected_graph(self):
        for doc, triples in self.graphs():
            with self.subTest(fixture=doc["fixture_id"]):
                self.assertNotIn("<http://www.w3.org/2002/07/owl#sameAs>",
                                 graph.predicates(triples))

    def test_no_hasPatient_in_any_expected_graph(self):
        for doc, triples in self.graphs():
            for p in graph.predicates(triples):
                with self.subTest(fixture=doc["fixture_id"], predicate=p):
                    self.assertNotIn("hasPatient", p)

    def test_every_emitted_predicate_is_written_in_a_target_schema(self):
        """Plan section 1: the host must not hold a second library of triple
        rules.  Every predicate in every expected graph appears literally in
        the target schema that produced it; the host chooses roots and unions
        passes, and constructs nothing."""
        shorthand = {"https://w3id.org/sulo/": "sulo:",
                     "http://www.w3.org/ns/prov#": "prov:"}
        for doc, triples in self.graphs():
            schema = TARGET_SCHEMAS[doc["family"]].read_text()
            for predicate in graph.predicates(triples):
                iri = predicate[1:-1]
                with self.subTest(fixture=doc["fixture_id"], predicate=iri):
                    if iri == "http://www.w3.org/1999/02/22-rdf-syntax-ns#type":
                        self.assertIn("rdf:type", schema)
                        continue
                    matched = any(iri.startswith(ns) and (short + iri[len(ns):]) in schema
                                  for ns, short in shorthand.items())
                    self.assertTrue(matched, "%s not found in %s"
                                    % (iri, TARGET_SCHEMAS[doc["family"]].name))

    def test_every_expected_graph_has_exactly_one_entry_point(self):
        """No orphan nodes: the only node with no incoming edge is the record.

        For a BP fixture the graph is the union of two resources, so there are
        two record nodes.
        """
        for doc, triples in self.graphs():
            with self.subTest(fixture=doc["fixture_id"]):
                entry = graph.sources(triples)
                expected = 2 if doc["family"] == "bp" else 1
                self.assertEqual(len(entry), expected, entry)
                for node in entry:
                    self.assertIn("record", node.lower().replace("bp-panel", "record"))


class ExpectedGraphsAreCurrent(engine.EngineTestCase):
    def test_build_check_reports_no_drift(self):
        """Re-runs all 19 maps and diffs against the committed graphs."""
        proc = subprocess.run([sys.executable, str(REPO / "fixtures/expected/build.py"),
                               "--check"], capture_output=True, text=True, cwd=str(REPO))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_the_maps_are_deterministic(self):
        """Gate 4's precondition: unchanged input reprocesses to the same graph.

        DR-301 4d says the engine is byte-deterministic including blank-node
        labels; this asserts it end to end, through the host path too.
        """
        from . import egfr_case
        a = egfr_case.run("egfr-baseline")
        b = egfr_case.run("egfr-baseline")
        self.assertEqual(a["nquads"], b["nquads"])
        committed = "\n".join(
            l for l in (EXPECTED / "egfr/egfr-baseline/target.nt").read_text().splitlines()
            if not l.startswith("#"))
        self.assertEqual(a["nquads"], committed)


if __name__ == "__main__":
    unittest.main()
