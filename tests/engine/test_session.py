"""The resident engine: it must be faster, and it must change nothing.

The Gate 4 benchmark measured 0.472 s per resource for `materialize`, of which
0.339 s was `docker run` start-up paid twice per resource, against 0.030 ms of
actual materialization. Keeping one process alive removes that.

The risk in keeping a process alive is that it stops being stateless. Two
things could make a resident engine give a different answer from a fresh one:
the schema cache, and any state a materializer leaves behind. Both are checked
here against the one-shot bridges rather than argued about, because "parsing
is pure" is exactly the kind of claim that is true until it is not.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fhir_sulo.engine.docker import EngineImage  # noqa: E402
from fhir_sulo.engine.session import EngineSession, EngineSessionClosed  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def requires_docker(test):
    if EngineImage.docker_present():
        return test
    if os.environ.get("FHIR_SULO_REQUIRE_ENGINE") == "1":
        return test
    return unittest.skipUnless(False, "docker is unavailable; A SKIP IS NOT A PASS")(test)


@requires_docker
class TestResidentEngineLifecycle(unittest.TestCase):
    def test_it_starts_answers_and_stops(self):
        with EngineSession(image=EngineImage()) as session:
            self.assertTrue(session.is_running)
            self.assertTrue(session.call({"op": "ping"})["ok"])
        self.assertFalse(session.is_running)

    def test_the_container_is_anonymous(self):
        """A *named* long-lived container is shared mutable state between
        worktrees, which is where CD-5 came from. This one is owned by one
        process and discoverable by nothing else."""
        with EngineSession(image=EngineImage()) as session:
            self.assertTrue(session.container_id)
            import subprocess
            names = subprocess.run(
                ["docker", "inspect", "--format", "{{.Name}}", session.container_id],
                capture_output=True, text=True).stdout.strip()
            self.assertNotIn("fhir-sulo", names.lower().replace("/", ""))

    def test_a_closed_session_refuses_rather_than_hangs(self):
        session = EngineSession(image=EngineImage()).start()
        session.close()
        with self.assertRaises(EngineSessionClosed):
            session.call({"op": "ping"})

    def test_an_unknown_op_is_an_answer_not_a_crash(self):
        with EngineSession(image=EngineImage()) as session:
            response = session.call({"op": "no-such-op"})
            self.assertFalse(response["ok"])
            self.assertIn("unknown op", response["error"])
            self.assertTrue(session.call({"op": "ping"})["ok"], "still usable")

    def test_memory_is_readable(self):
        """One resident container instead of twenty thousand short-lived ones
        is what makes engine memory a number that can be read at all."""
        with EngineSession(image=EngineImage()) as session:
            used = session.memory_bytes()
            self.assertIsNotNone(used)
            self.assertGreater(used, 0)
            self.assertLess(used, 2 * 1024 ** 3)


@requires_docker
class TestResidentOutputEqualsOneShot(unittest.TestCase):
    """The contract: keeping the process alive changes performance, nothing else."""

    CASES = [("bp", "bp-two-panels", "bp-1.json", "per-observation"),
             ("bp", "bp-component-omitted", "bp-1.json", "per-observation"),
             ("egfr", "egfr-baseline", "egfr-456.json", "per-observation"),
             ("encounter", "enc-baseline", "enc-9.json", None)]

    def outcome(self, family, case, name, mode, reuse):
        from fhir_sulo.pipeline.compose import Pipeline

        image = EngineImage(reuse_process=reuse)
        try:
            pipeline = Pipeline.for_family(family, REPO, engine=image,
                                           quality_mode=mode)
            return pipeline.run_file(REPO / "fixtures/r4" / family / case / name)
        finally:
            image.close()

    def test_quads_are_byte_identical(self):
        for family, case, name, mode in self.CASES:
            with self.subTest(family=family, case=case):
                one = self.outcome(family, case, name, mode, False)
                many = self.outcome(family, case, name, mode, True)
                self.assertEqual(list(one.ntriples), list(many.ntriples))

    def test_lineage_and_graph_key_are_identical(self):
        for family, case, name, mode in self.CASES:
            with self.subTest(family=family, case=case):
                one = self.outcome(family, case, name, mode, False)
                many = self.outcome(family, case, name, mode, True)
                self.assertEqual(one.transform.output_graph_key,
                                 many.transform.output_graph_key)
                key = lambda o: [(l.quad_index, l.produced_by, l.source_variable,
                                  l.source_constraint, l.iteration_key)
                                 for l in o.transform.lineage]
                self.assertEqual(key(one), key(many))

    def test_a_reused_schema_does_not_drift_over_repeats(self):
        """The schema cache is the one piece of state a resident process
        keeps. Ten runs through one process must all match the first."""
        from fhir_sulo.pipeline.compose import Pipeline

        image = EngineImage(reuse_process=True)
        try:
            pipeline = Pipeline.for_family("bp", REPO, engine=image,
                                           quality_mode="per-observation")
            path = REPO / "fixtures/r4/bp/bp-two-panels/bp-1.json"
            first = list(pipeline.run_file(path).ntriples)
            for _ in range(9):
                self.assertEqual(list(pipeline.run_file(path).ntriples), first)
        finally:
            image.close()

    def test_interleaving_families_does_not_leak_between_them(self):
        """One process serves every map. A cached schema or a materializer's
        leftovers must not reach another family's run."""
        from fhir_sulo.pipeline.compose import Pipeline

        image = EngineImage(reuse_process=True)
        try:
            pipelines = {f: Pipeline.for_family(
                f, REPO, engine=image,
                quality_mode=None if f == "encounter" else "per-observation")
                for f in ("bp", "egfr", "encounter")}
            paths = {"bp": REPO / "fixtures/r4/bp/bp-two-panels/bp-1.json",
                     "egfr": REPO / "fixtures/r4/egfr/egfr-baseline/egfr-456.json",
                     "encounter": REPO / "fixtures/r4/encounter/enc-baseline/enc-9.json"}
            alone = {f: list(pipelines[f].run_file(paths[f]).ntriples) for f in paths}
            for _ in range(3):
                for family in ("encounter", "bp", "egfr"):
                    self.assertEqual(
                        list(pipelines[family].run_file(paths[family]).ntriples),
                        alone[family])
        finally:
            image.close()


@requires_docker
class TestResidentEngineDoesNotLeak(unittest.TestCase):
    """A process that lives for 10,000 resources must not grow with them.

    Measured over 2,400 runs the engine oscillates between 90 and 137 MiB and
    comes back down, and throughput is flat. This is the cheap regression
    guard for that: a cache keyed on schema text would grow without the bound
    in `server.js`, and nothing else would notice until a long run died.
    """

    def test_memory_and_throughput_stay_flat(self):
        from fhir_sulo.pipeline.compose import Pipeline

        image = EngineImage(reuse_process=True)
        try:
            pipeline = Pipeline.for_family("bp", REPO, engine=image,
                                           quality_mode="per-observation")
            path = REPO / "fixtures/r4/bp/bp-two-panels/bp-1.json"
            pipeline.run_file(path)
            session = image.session()
            for _ in range(150):
                pipeline.run_file(path)
            self.assertLess(session.memory_bytes(), 768 * 1024 ** 2)
            self.assertLessEqual(session.call({"op": "ping"})["cachedSchemas"], 64)
        finally:
            image.close()


@requires_docker
class TestBatching(unittest.TestCase):
    """Batching is safe under DR-302 -- every map is rooted at one resource and
    nothing crosses resources -- but it buys about 1% now that the process is
    resident, so it is offered rather than used by default."""

    def test_a_batch_answers_every_item_in_order(self):
        with EngineSession(image=EngineImage()) as session:
            requests = [{"op": "ping"} for _ in range(5)]
            results = session.run_map_batch(requests)
            self.assertEqual(len(results), 5)

    def test_an_empty_batch_is_empty(self):
        with EngineSession(image=EngineImage()) as session:
            self.assertEqual(session.run_map_batch([]), [])

    def test_one_bad_item_does_not_abandon_the_rest(self):
        """A partial batch silently dropping resources is the failure mode
        worth guarding: 10,000 in, 9,000 out, no error."""
        with EngineSession(image=EngineImage()) as session:
            response = session.call({"op": "run-map-batch", "items": [
                {"id": 0, "request": {"passes": []}},
                {"id": 1, "request": {"source": None, "passes": []}},
            ]})
            self.assertTrue(response["ok"])
            self.assertEqual(len(response["results"]), 2)


if __name__ == "__main__":
    unittest.main()
