"""Host side of the map test harness: a thin adapter onto the production driver.

This used to be a test-only Node script plus a container of its own. Both are
gone. `run_job` now builds a `fhir_sulo.engine.maprun.MapJob` and runs it
through the pinned image the driver owns, so Agent 3's acceptance tests
exercise the code that ships:

* the production multi-pass bridge (`tools/engine/bridge/run-map.js`), which
  validates once and materializes every declared pass;
* the driver's `Guards`, set explicitly, never inherited (CD-2);
* the driver's per-quad provenance, which is what makes
  `test_host_emits_no_triples.py` checkable rather than assertable.

The legacy result-document shape is preserved on purpose: `require_clean`,
`quads`, `triples` and `objects_of` are used across six test modules, and
repointing the engine is not a reason to rewrite Agent 3's assertions.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from fhir_sulo.engine.docker import EngineImage, EngineUnavailable
from fhir_sulo.engine.driver import Guards, MaterializationFailure, union_passes
from fhir_sulo.engine.maprun import MapJob, MapPass, _interpret
from fhir_sulo.engine.rdfterms import Quad
from fhir_sulo.pipeline.manifest import discover, host_consumed_variables

REPO = Path(__file__).resolve().parents[4]

_IMAGE: Optional[EngineImage] = None


def docker_available() -> bool:
    return EngineImage.docker_present()


def image() -> EngineImage:
    global _IMAGE
    if _IMAGE is None:
        img = EngineImage()
        img.ensure_built()
        _IMAGE = img
    return _IMAGE


def cpath(rel: str) -> str:
    """A repository-relative path.

    Kept as a function because the case modules call it eleven times. Nothing
    is copied into a container any more -- the bridge takes schema text and
    graph text on stdin, which is also why no bind mount is involved (DR-301:
    on this host an unshared bind mount yields an empty directory, silently).
    """
    return rel


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _nt(term) -> str:
    return term.to_ntriples()


def run_job(job: Mapping[str, Any]) -> Dict[str, Any]:
    """Run one map job and return the harness result document."""
    passes = [
        MapPass(name=p["name"], shape=p.get("shape"), root=p["root"],
                static_vars=p.get("staticVars", {}))
        for p in job.get("passes", [])
    ]
    # `dataInline` carries graph text directly instead of a repository path.
    # Agent 3's inverse-pivot tests use it to validate a FRESHLY materialized
    # graph: reverse-validating the committed golden would read a file a
    # broken map has not been allowed to update, making the test blind to the
    # drift it exists to catch. Introduced on their branch at the same time
    # this adapter replaced run-map.js, so neither side saw the other.
    inline = job.get("dataInline")
    if inline is None and job.get("data") is None:
        raise ValueError(
            "run_job needs either 'data' (a repository-relative path) or "
            "'dataInline' (graph text); both were None"
        )
    map_job = MapJob(
        source_schema=_read(job["sourceSchema"]),
        target_schema=_read(job["targetSchema"]) if job.get("targetSchema") else "",
        data=inline if inline is not None else _read(job["data"]),
        node=job["focus"],
        passes=passes,
        source_shape=job.get("startShape"),
        bindings_override=job.get("bindingsOverride"),
    )
    guards = Guards()
    request = map_job.to_bridge(guards)
    if not passes:
        request["passes"] = []
    response = image().call("run-map.js", request)

    out: Dict[str, Any] = {
        "ok": False, "stage": response.get("stage", "validate"),
        "validation": None, "bindings": response.get("bindings"),
        "passes": [], "nquads": "",
        "engine": {"image": image().tag, "guards": guards.to_bridge()},
    }

    if not response.get("ok") and response.get("stage") == "validate":
        out["validation"] = {"ok": False, "failure": response.get("validation"),
                             "exitCode": 1}
        return out
    out["validation"] = {"ok": True, "failure": None, "exitCode": 0}

    if not response.get("ok"):
        # a materialization failure: report it on the pass that raised, the
        # way the old harness did, so require_clean stays the thing that fails
        out["stage"] = response.get("stage", "materialize")
        out["passes"] = [{"name": response.get("pass"), "root": None, "shape": None,
                          "quads": [], "report": response.get("report"),
                          "error": {"message": response.get("error"),
                                    "report": response.get("report")}}]
        return out

    entries = response.get("passes", [])
    results, lines = [], []
    for entry in entries:
        spec = next(p for p in passes if p.name == entry["name"])
        record = {"name": entry["name"], "root": entry["root"],
                  "shape": entry.get("shape"), "quads": [], "report": entry["lastReport"],
                  "error": None}
        try:
            interpreted = _interpret(entry, spec, guards)
        except MaterializationFailure as exc:
            record["error"] = {"message": str(exc), "report": entry["lastReport"]}
            out["passes"].append(record)
            out["stage"] = "materialize"
            return out
        results.append(interpreted)
        for quad_record in interpreted.records:
            quad = quad_record.quad.relabel_blank_nodes(entry["name"])
            triple = [_nt(quad.s), _nt(quad.p), _nt(quad.o)]
            record["quads"].append(triple)
            lines.append(" ".join(triple) + " .")
        out["passes"].append(record)

    out["nquads"] = "\n".join(sorted(set(lines)))
    out["stage"] = "done"
    out["ok"] = True
    if results:
        # the driver's own union, so the host-emits-no-triples guard runs on
        # exactly the graph the tests inspect
        out["_driverResult"] = union_passes(results)
    return out


def quads(result: Mapping[str, Any]) -> List[str]:
    return [line for line in result.get("nquads", "").splitlines() if line]


def triples(result: Mapping[str, Any]) -> List[tuple]:
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
    driver = result.get("_driverResult")
    if driver is not None and driver.untraced_quads():
        raise AssertionError(
            "quads at %s name no TripleConstraint in the target schema; the host "
            "would be emitting them (DR-302)" % (driver.untraced_quads(),))


SKIP_NOTE = (
    "The pinned ShExMap engine did not run, so the Gate 2/3 acceptance tests did "
    "not execute. A SKIP HERE IS NOT A PASS."
)


class EngineTestCase(unittest.TestCase):
    """Base class for tests that need the pinned engine in Docker.

    Skips, loudly, where Docker is unavailable -- unless
    ``FHIR_SULO_REQUIRE_ENGINE=1``, which the gate sets: a gate that passes
    because its evidence did not run is not a gate.
    """

    @classmethod
    def setUpClass(cls) -> None:
        required = os.environ.get("FHIR_SULO_REQUIRE_ENGINE") == "1"
        if os.environ.get("CI") and os.environ.get("FHIR_SULO_ENGINE_TESTS") != "1" \
                and not required:
            raise unittest.SkipTest(
                SKIP_NOTE + " Reason: running under CI without FHIR_SULO_ENGINE_TESTS=1."
            )
        if not docker_available():
            if required:
                raise AssertionError(
                    SKIP_NOTE + " FHIR_SULO_REQUIRE_ENGINE=1 was set, so this is a "
                    "failure rather than a skip.")
            raise unittest.SkipTest(SKIP_NOTE + " Reason: Docker is unavailable.")
        image()
