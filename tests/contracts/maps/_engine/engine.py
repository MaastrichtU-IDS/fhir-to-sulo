"""Host side of the test-only ShExMap engine harness.

There is no node/npm on this host, so the pinned engine runs in Docker.  Colima
shares only the VM owner's home directory, so a bind mount into a scratchpad
silently yields an empty directory (DR-301 operational note): the repository
tree is shipped in with ``docker cp`` instead.

TEMPORARY, TEST-ONLY.  Agent 4 owns the production materialization driver
(DR-301 decision 3, CD-2); this exists so the Gate 2/3 acceptance tests can run
before that driver lands.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

REPO = Path(__file__).resolve().parents[4]
CONTAINER = os.environ.get("FHIR_SULO_ENGINE_CONTAINER", "shexmaps")
IMAGE = "node:20-bookworm-slim"
# Each PROCESS gets its own tree inside the container.  A shared /w/repo was
# a real defect: `fixtures/expected/build.py` runs as a subprocess from one of
# the tests and re-syncs the same path, so a parent that had already synced
# could go on believing its cached copy was current while another process had
# replaced it.  That produced ENOENT-on-a-fixture failures and, worse, ran
# schemas the host had already edited. Per-process paths make it impossible.
CONTAINER_REPO = "/w/repo-%d" % os.getpid()

_PREPARED = False


def docker_available() -> bool:
    exe = shutil.which("docker")
    if not exe:
        return False
    return subprocess.run([exe, "info"], capture_output=True).returncode == 0


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(
            "docker %s failed (%s)\n%s\n%s" % (args[0], proc.returncode, proc.stdout, proc.stderr)
        )
    return proc


def ensure_container() -> None:
    """Create the container and ``npm ci`` the pinned lockfile, once per session."""
    global _PREPARED
    if _PREPARED:
        return
    alive = subprocess.run(
        ["docker", "exec", CONTAINER, "test", "-d", "/w/node_modules/shex"],
        capture_output=True,
    ).returncode == 0
    if not alive:
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
        _run("run", "-d", "--name", CONTAINER, "-w", "/w", IMAGE, "sleep", "infinity")
        _run("cp", str(REPO / "tools/engine/package.json"), "%s:/w/package.json" % CONTAINER)
        _run("cp", str(REPO / "tools/engine/package-lock.json"), "%s:/w/package-lock.json" % CONTAINER)
        _run("exec", CONTAINER, "npm", "ci", "--no-audit", "--no-fund", "--prefix", "/w")
    _PREPARED = True


SYNCED_TREES = ("maps", "fixtures", "tests/contracts/maps/_engine")
_SYNCED = False


def sync_tree(force: bool = False) -> None:
    """Ship the schemas, fixtures and harness into the container, ONCE.

    Colima shares only the VM owner's home, so a bind mount into the scratchpad
    silently yields an empty directory (DR-301 operational note); the tree goes
    in with ``docker cp`` instead.

    Once per process, not once per job.  Doing it per job meant every
    materialization first ``rm -rf``'d and re-copied the whole tree, which was
    slow and left a window in which a run could see a missing fixture and
    report a source-validation failure that had nothing to do with the map.
    Call ``sync_tree(force=True)`` after editing a schema mid-process; the
    fault-injection scripts do.
    """
    global _SYNCED
    ensure_container()
    if _SYNCED and not force:
        return
    _run("exec", CONTAINER, "mkdir", "-p", CONTAINER_REPO)
    for rel in SYNCED_TREES:
        _run("exec", CONTAINER, "mkdir", "-p", "%s/%s" % (CONTAINER_REPO, Path(rel).parent))
        _run("exec", CONTAINER, "rm", "-rf", "%s/%s" % (CONTAINER_REPO, rel))
        _run("cp", str(REPO / rel), "%s:%s/%s" % (CONTAINER, CONTAINER_REPO, rel))
        # docker cp reports success even where nothing landed; verify.
        probe = _run("exec", CONTAINER, "test", "-e", "%s/%s" % (CONTAINER_REPO, rel),
                     check=False)
        if probe.returncode != 0:
            raise RuntimeError("docker cp did not land %s in the container" % rel)
    _SYNCED = True


def cpath(rel: str) -> str:
    """Repository-relative path as seen inside the container."""
    return "%s/%s" % (CONTAINER_REPO, rel)


def run_job(job: Mapping[str, Any]) -> Dict[str, Any]:
    """Run one map job through the pinned engine and return its result document."""
    sync_tree()
    proc = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "node",
         cpath("tests/contracts/maps/_engine/run-map.js"), "-"],
        input=json.dumps(job), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("run-map.js failed (%s)\n%s\n%s"
                           % (proc.returncode, proc.stdout[-4000:], proc.stderr[-4000:]))
    return json.loads(proc.stdout)


def quads(result: Mapping[str, Any]) -> List[str]:
    """The union graph as a sorted list of N-Triples lines."""
    return [line for line in result.get("nquads", "").splitlines() if line]


def triples(result: Mapping[str, Any]) -> List[tuple]:
    """The union graph as (subject, predicate, object) N-Triples term triples."""
    out = []
    for p in result.get("passes", []):
        for s, pr, o in p["quads"]:
            out.append((s, pr, o))
    return out


def objects_of(result: Mapping[str, Any], subject: str, predicate: str) -> List[str]:
    return sorted(o for (s, p, o) in triples(result) if s == subject and p == predicate)


def require_clean(result: Mapping[str, Any]) -> None:
    """Fail loudly on every silent-failure mode DR-301 documents."""
    if not result["validation"]["ok"]:
        raise AssertionError("source validation failed: %s"
                             % json.dumps(result["validation"])[:2000])
    for p in result["passes"]:
        if p["error"]:
            raise AssertionError("pass %r raised: %s" % (p["name"], p["error"]))
        r = p["report"] or {}
        if r.get("unboundVariables"):
            raise AssertionError("pass %r left variables unbound (DR-301 8c: this is a "
                                 "silent partial graph): %s" % (p["name"], r["unboundVariables"]))
        if r.get("explorationTruncated"):
            raise AssertionError("pass %r truncated exploration (DR-301 B2)" % p["name"])
        if r.get("unusedStatics"):
            raise AssertionError("pass %r ignored run bindings %s -- an identity-provided "
                                 "binding that never reaches the graph is a silent "
                                 "mis-map" % (p["name"], r["unusedStatics"]))


SKIP_NOTE = (
    "The pinned ShExMap engine did not run, so the Gate 2/3 acceptance tests did "
    "not execute. A SKIP HERE IS NOT A PASS."
)


class EngineTestCase(unittest.TestCase):
    """Base class for tests that need the pinned engine in Docker.

    Skips, loudly, where Docker is unavailable.  Also skips on a CI runner
    unless ``FHIR_SULO_ENGINE_TESTS=1`` is set: the CI job as configured runs
    ``make contracts`` with no Docker step, and silently adding a container
    pull plus ``npm ci`` to it is the integration lead's call, not this
    package's.  Reported to Agent 1: CI needs a job that sets that variable, or
    these tests never run there.
    """

    @classmethod
    def setUpClass(cls) -> None:
        if os.environ.get("CI") and os.environ.get("FHIR_SULO_ENGINE_TESTS") != "1":
            raise unittest.SkipTest(
                SKIP_NOTE + " Reason: running under CI without FHIR_SULO_ENGINE_TESTS=1."
            )
        if not docker_available():
            raise unittest.SkipTest(SKIP_NOTE + " Reason: Docker is unavailable.")
        ensure_container()
