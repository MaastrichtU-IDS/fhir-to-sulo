"""PROV-O emission, run records and per-quad lineage.

Agent 6 scope. Stdlib-only: provenance is emitted as N-Quads text, so this
package imports no RDF library and runs under the system interpreter.
"""

from __future__ import annotations

from .lineage import (
    EngineLineagePayload,
    EngineQuadProvenance,
    FrameOrigin,
    LineageError,
    UntracedQuadError,
    build_lineage,
    canonical_lineage_json,
    from_engine_payload,
    lineage_digest,
    lineage_report,
)
from .prov import (
    FSP,
    PROV,
    ProvenanceEmitter,
    agent_iri,
    invalidation_quads,
    lineage_graph_iri,
    lineage_quads,
    plan_iri,
    registry_graph_iri,
    registry_quads,
    revision_quads,
    run_activity_iri,
    run_graph_iri,
    run_provenance_quads,
    source_entity_iri,
)
from .run_records import (
    NOT_VALIDATED,
    RunInputs,
    build_run_record,
    build_transform_result,
    deterministic_run_id,
    output_digest,
    result_lineage_report,
    utc_now_iso,
)

__all__ = [
    "EngineLineagePayload",
    "EngineQuadProvenance",
    "FrameOrigin",
    "LineageError",
    "UntracedQuadError",
    "build_lineage",
    "canonical_lineage_json",
    "from_engine_payload",
    "lineage_digest",
    "lineage_report",
    "FSP",
    "PROV",
    "ProvenanceEmitter",
    "agent_iri",
    "invalidation_quads",
    "lineage_graph_iri",
    "lineage_quads",
    "plan_iri",
    "registry_graph_iri",
    "registry_quads",
    "revision_quads",
    "run_activity_iri",
    "run_graph_iri",
    "run_provenance_quads",
    "source_entity_iri",
    "NOT_VALIDATED",
    "RunInputs",
    "build_run_record",
    "build_transform_result",
    "deterministic_run_id",
    "output_digest",
    "result_lineage_report",
    "utc_now_iso",
]
