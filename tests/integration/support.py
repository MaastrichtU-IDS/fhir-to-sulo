"""Shared helpers and narrow test doubles for the Agent 6 integration tests.

Agents 2, 3, 4 and 5 are building in parallel. Nothing here imports their
code; each dependency is replaced by the *narrowest* thing that satisfies the
frozen interface, so that when their work lands the tests change in one place
or not at all:

* the engine's lineage output -> ``fake_engine_payload`` builds the documented
  ``{quad, tc, predicate, src}`` shape (DR-301 probe 5) by hand;
* the identity service -> entity IRIs are passed in as strings;
* the terminology service -> the snapshot is an opaque token in a key.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

GRAPHS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graphs")

from fhir_sulo.contracts import TransformStatus  # noqa: E402
from fhir_sulo.provenance import (  # noqa: E402
    RunInputs,
    build_run_record,
    build_transform_result,
    from_engine_payload,
)

EX = "https://example.org/fhir-sulo/"

BASE_INPUTS = dict(
    map_id="egfr-r4",
    map_semantic_version="0.1.0",
    pairing_hash="sha256:pairing-aaaa",
    sulo_version="0.2.12",
    domain_ontology_version="unresolved:R1",
    terminology_snapshot="tx-2026-09-29",
    policy_version="unresolved:R2",
    engine_build="shex@1.0.0-alpha.33",
    renderer_id="fhir_sulo.ingest.fhir_rdf/0.1.0",
)


def graph_text(name: str) -> str:
    with open(os.path.join(GRAPHS, name), encoding="utf-8") as handle:
        return handle.read()


def run_inputs(*, version_id="1", json_digest="sha256:v1", url=None, **overrides) -> RunInputs:
    kwargs = dict(BASE_INPUTS)
    kwargs.update(overrides)
    return RunInputs(
        source_canonical_url=url or "https://fhir.example/Observation/egfr-456",
        source_version_id=version_id,
        source_json_digest=json_digest,
        **kwargs,
    )


def fake_engine_payload(quads, *, variables=None, scope="result", key=("egfr-456",)):
    """Build the engine lineage payload Agent 4's driver is documented to emit.

    Every quad gets a triple constraint and a source, because that is what the
    real engine reports for a quad it produced; the tests that need a *broken*
    payload build it explicitly rather than getting one by accident here.
    """
    variables = list(variables or [])
    provenance = []
    for index, quad in enumerate(quads):
        src = variables[index] if index < len(variables) else "<constant>"
        provenance.append(
            {
                "quad": quad,
                "tc": "TargetShape/tc%d" % index,
                "predicate": quad.split(" ", 2)[1],
                "src": src,
                "frameIndex": 0,
            }
        )
    return from_engine_payload(
        {
            "quads": list(quads),
            "provenance": provenance,
            "frameOrigins": [
                {"frameIndex": 0, "scope": scope, "keyValues": list(key)}
            ],
        }
    )


# --------------------------------------------------------------------------
# The graphs the correction tests are driven by.
#
# Review finding (MINOR): Gate 4's correction evidence rested on two
# hand-built two-triple graphs, so "version 2 removes stale version-1
# assertions" was demonstrated on something no map produces. These are now
# the REAL emitted graph from ``fixtures/expected/egfr/egfr-baseline``, read
# as text so this module stays importable without rdflib.
#
# ONE thing is still synthetic, and it is called out rather than hidden: the
# fixture set contains no pair of fixtures that are two *versions of the same
# resource*. ``egfr-entered-in-error`` is a different resource id
# (``egfr-456-eie``), not version 2 of ``egfr-456``. So version 2 here is the
# real version-1 graph with the reported value corrected, which is exactly
# what a real correction looks like. Everything else - all 21 triples, the
# hashed person and quality IRIs, the datatypes - is map output.
#
# Gate 4's correction row no longer rests on that edit. Since the composed
# pipeline landed, ``test_correction_on_pipeline_output.py`` runs all three
# correction scenarios through real FHIR JSON, real ingest, the reviewed maps
# and the pinned engine, comparing only emitted triples. These constants stay
# because the store-level tests in ``test_correction.py`` are the fast,
# engine-free ones and still want a realistic graph to move around.
#
# Still requested from Agent 2, now as a simplification rather than a gap: a
# genuine ``egfr-corrected`` fixture at ``meta.versionId = 2``, which would
# let the pipeline test load version 2 instead of editing version 1 in
# memory.
# --------------------------------------------------------------------------

_EXPECTED = os.path.join(ROOT, "fixtures", "expected")
_BASELINE = os.path.join(_EXPECTED, "egfr", "egfr-baseline", "target.nt")


def _real_triples(path):
    with open(path, encoding="utf-8") as handle:
        return tuple(
            line.strip()
            for line in handle
            if line.strip() and not line.startswith("#")
        )


_FALLBACK_V1 = (
    "<%segfr-result-egfr-456> <https://w3id.org/sulo/hasValue> "
    '"55.0"^^<http://www.w3.org/2001/XMLSchema#decimal> .' % EX,
    "<%segfr-result-egfr-456> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
    "<https://w3id.org/sulo/Quantity> ." % EX,
)

USING_REAL_MAP_OUTPUT = os.path.exists(_BASELINE)

QUADS_V1 = _real_triples(_BASELINE) if USING_REAL_MAP_OUTPUT else _FALLBACK_V1

QUADS_V2 = tuple(
    line.replace('"55.0"', '"61.0"') for line in QUADS_V1
)

assert QUADS_V1 != QUADS_V2, (
    "version 2 must differ from version 1, or the correction tests would be "
    "asserting nothing"
)


def mapped_pair(inputs, quads, *, activity_time, variables=("egfr:value", None)):
    """A (TransformResult, RunRecord) pair for a successful mapping."""
    payload = fake_engine_payload(quads, variables=[v for v in variables if v])
    result = build_transform_result(
        inputs,
        status=TransformStatus.MAPPED,
        engine_payload=payload,
        pivot_variables=["egfr:value", "egfr:unitCode"],
        target_root="%segfr-result-456" % EX,
    )
    record = build_run_record(
        inputs,
        status=TransformStatus.MAPPED,
        quads=result.target_quads,
        activity_time=activity_time,
    )
    return result, record


def rejected_pair(inputs, *, activity_time, reason):
    result = build_transform_result(
        inputs, status=TransformStatus.REJECTED, rejection_reason=reason
    )
    record = build_run_record(
        inputs, status=TransformStatus.REJECTED, activity_time=activity_time
    )
    return result, record


def source_only_pair(inputs, *, activity_time, reason):
    result = build_transform_result(
        inputs, status=TransformStatus.SOURCE_ONLY, diagnostics=(reason,)
    )
    record = build_run_record(
        inputs, status=TransformStatus.SOURCE_ONLY, activity_time=activity_time
    )
    return result, record
