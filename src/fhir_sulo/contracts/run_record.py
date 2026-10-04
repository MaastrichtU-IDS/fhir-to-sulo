"""RunRecord - immutable metadata for one mapping run.

Plan section 3:

    Records source version/digest, map pairing/hash, SULO and domain ontology
    versions, terminology snapshot, engine build, policy version, activity
    time, graph key, validation report digest, and output digest. These are
    immutable metadata for the run, even when the current derived graph is
    replaced by a correction.

``renderer_id`` is not in the plan's list but was added at contract 0.3.0
(IR-601, raised by Agent 6). The FHIR-JSON-to-RDF renderer can change the
emitted target triples, so leaving it out meant a renderer change was
invisible to the graph key: reprocessing after one would report ``unchanged``
while the triples differed. Anything that can change an emitted triple belongs
in the key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .source_context import PILOT_SOURCE_SCOPE_ID


@dataclass(frozen=True)
class RunRecord:
    """One immutable run activity record. Survives correction of its output."""

    run_id: str
    activity_time: str
    source_canonical_url: str
    source_version_id: str
    source_json_digest: str
    map_id: str
    map_semantic_version: str
    pairing_hash: str
    sulo_version: str
    domain_ontology_version: str
    terminology_snapshot: str
    engine_build: str
    renderer_id: str
    policy_version: str
    contract_version: str
    output_graph_key: str
    output_digest: str
    validation_report_digest: str
    transform_status: str
    #: DR-016, contract 0.6.0. The person-identifier index decides which source
    #: records are one person, so it changes the entity IRIs in the emitted
    #: graph and belongs in the graph key. ``"none"`` when no index is in use:
    #: an explicit token, so "no index" and "some index" cannot hash alike.
    person_index_digest: str = "none"
    #: DR-019. Which source the resource came from; part of the graph key and
    #: of the replacement slot, so the key recomputes from the record alone.
    source_scope_id: str = PILOT_SOURCE_SCOPE_ID
    superseded_by: Optional[str] = None
    notes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "activity_time",
            "source_version_id",
            "pairing_hash",
            "output_graph_key",
            "engine_build",
            "renderer_id",
            "person_index_digest",
        ):
            if not getattr(self, name):
                raise ValueError(f"RunRecord.{name} is required and must be non-empty")
