"""The maps suite must pass in any order, and from a clean tree.

Bought by a defect. In review the suite was order-dependent: a full-suite run
from clean gave 22 failures, a second run 2, a third 0, while the maps suite
alone passed from clean. **CI always runs from clean**, so a Gate 2/3 suite
that is only green on a warm tree is not a gate.

Both causes were in the harness and are gone:

* the job document was ``docker cp``'d to a fixed ``/w/job.json`` before a
  ``docker exec`` that read it; ``docker cp`` returns once the daemon has
  accepted the archive, so a run could read the *previous* call's job and
  materialize the wrong fixture;
* the repository was copied into one long-lived container under a shared
  path, which ``fixtures/expected/build.py`` re-synced from a subprocess, so
  a parent that had already synced could go on trusting a tree another
  process had just torn down and rebuilt.

The harness is now the production driver (Agent 4), which passes schema and
graph text on stdin to ``docker run``, so neither can recur. This test is the
regression guard: it re-runs the whole maps suite in a different order, in a
fresh process, and fails if the outcome differs.

Default order is REVERSED -- deterministic, so a failure is reproducible. Set
``FHIR_SULO_MAPS_ORDER_SEED`` to shuffle with that seed instead; CI can vary
it per build to fuzz. The order used is always named in the failure message.
"""

from __future__ import annotations

import os
import random
import subprocess
import sys
import unittest

from ._engine import engine

REPO = engine.REPO
CHILD_MARKER = "FHIR_SULO_MAPS_ORDER_CHILD"
SEED_VAR = "FHIR_SULO_MAPS_ORDER_SEED"
MAPS = "tests/contracts/maps"


class MapsSuiteIsOrderIndependent(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get(CHILD_MARKER):
            raise unittest.SkipTest("this is the re-ordered child run")
        required = os.environ.get("FHIR_SULO_REQUIRE_ENGINE") == "1"
        if os.environ.get("CI") and os.environ.get("FHIR_SULO_ENGINE_TESTS") != "1" \
                and not required:
            raise unittest.SkipTest(engine.SKIP_NOTE + " Reason: CI without engine tests.")
        if not engine.docker_available():
            if required:
                raise AssertionError(engine.SKIP_NOTE + " FHIR_SULO_REQUIRE_ENGINE=1 "
                                     "was set, so this is a failure rather than a skip.")
            raise unittest.SkipTest(engine.SKIP_NOTE + " Reason: Docker is unavailable.")
        # `make contracts-stdlib` runs the system python3, which deliberately has
        # no pytest: it is the stdlib-only fallback. Re-ordering the suite needs
        # pytest to collect node ids, so skip there -- `make contracts` is the
        # authoritative runner and does run this.
        if subprocess.run([sys.executable, "-c", "import pytest"],
                          capture_output=True).returncode != 0:
            raise unittest.SkipTest(
                "%s has no pytest, so the suite cannot be re-ordered here; "
                "`make contracts` is the authoritative runner and runs this test."
                % sys.executable)

    def test_the_suite_passes_in_a_different_order(self):
        env = dict(os.environ, PYTHONPATH="src", **{CHILD_MARKER: "1"})

        collect = subprocess.run(
            [sys.executable, "-m", "pytest", MAPS, "--collect-only", "-q",
             "--no-header", "-p", "no:cacheprovider"],
            cwd=str(REPO), capture_output=True, text=True, env=env)
        self.assertEqual(collect.returncode, 0,
                         collect.stdout[-3000:] + collect.stderr[-2000:])
        ids = [line.strip() for line in collect.stdout.splitlines()
               if line.strip().startswith(MAPS) and "::" in line]
        self.assertGreater(len(ids), 50, "collection looks wrong: %d ids" % len(ids))

        seed = os.environ.get(SEED_VAR)
        if seed:
            random.Random(seed).shuffle(ids)
            how = "shuffled with %s=%s" % (SEED_VAR, seed)
        else:
            ids.reverse()
            how = "reversed (set %s to shuffle instead)" % SEED_VAR

        run = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header",
             "-p", "no:cacheprovider", *ids],
            cwd=str(REPO), capture_output=True, text=True, env=env)
        failures = [l for l in run.stdout.splitlines() if l.startswith(("FAILED", "ERROR"))]
        self.assertEqual(
            run.returncode, 0,
            "the maps suite does not pass in a different order (%s).\n"
            "CI always runs from clean, so an order-dependent suite is not a gate.\n%s"
            % (how, "\n".join(failures[:20]) or run.stdout[-3000:]))


class HarnessCarriesNoStateBetweenRuns(engine.EngineTestCase):
    """The evidence must be reproducible from nothing.

    The old harness kept one ``shexmaps`` container alive for hours across
    many runs, so a green suite could depend on something a previous run left
    in it. The driver runs ``docker run --rm`` per call, so there is nothing
    to carry; these assert that rather than assume it.
    """

    def test_the_engine_image_is_the_pinned_content_addressed_one(self):
        """Not `node:20-bookworm-slim` with an `npm ci` at test time, which is
        what produced the first round of Gate 2/3 evidence, and not a bare
        version tag either -- several worktrees share one Docker daemon, so a
        version-only tag is shared mutable state."""
        from fhir_sulo.engine.docker import DEFAULT_TAG, default_tag

        self.assertEqual(engine.image().tag, default_tag())
        self.assertTrue(engine.image().tag.startswith(DEFAULT_TAG + "-"))
        self.assertTrue(engine.image().exists())

    def test_the_gate_evidence_records_which_image_produced_it(self):
        """A tag can be rebuilt; the content id is what produced the graph."""
        build_id = engine.image().build_id()
        self.assertIn(":", build_id)
        self.assertIn("sha256:", build_id)

    def test_every_engine_call_is_docker_run_rm(self):
        """No container outlives the call that made it.

        Asserted on how the driver invokes docker, NOT by listing the daemon's
        containers: several agent worktrees share one Docker daemon and other
        suites run engine calls concurrently, so a global listing is itself
        order-dependent. An earlier version of this test did exactly that and
        failed in a full-suite run while passing alone -- the same class of
        mistake it exists to catch.
        """
        import inspect
        from fhir_sulo.engine import docker as docker_mod

        source = inspect.getsource(docker_mod.EngineImage.call)
        self.assertIn('"--rm"', source)
        self.assertNotIn('"--name"', source)
        self.assertNotIn("docker cp", source)

    def test_the_harness_creates_no_container_of_its_own(self):
        """The old harness kept one `shexmaps` container alive for hours
        across many runs, so a green suite could depend on what a previous run
        left in it."""
        import inspect

        source = inspect.getsource(engine)
        for banned in ("docker\", \"run", "sleep infinity", "shexmaps"):
            self.assertNotIn(banned, source.replace("``shexmaps``", ""))

    def test_no_repository_tree_is_copied_into_a_container(self):
        """Schema and graph text travel on stdin.

        A copied-in tree went stale between processes, and its non-atomic
        refresh left a window in which a run saw a missing fixture and
        reported a source-validation failure that had nothing to do with the
        map.
        """
        self.assertFalse(hasattr(engine, "sync_tree"))
        source = (REPO / "src/fhir_sulo/engine/docker.py").read_text()
        self.assertNotIn("docker cp", source)
        self.assertIn("--rm", source)


if __name__ == "__main__":
    unittest.main()
