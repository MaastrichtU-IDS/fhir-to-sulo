"""RunRecord - immutable metadata for one mapping run.

Plan section 3:

    Records source version/digest, map pairing/hash, SULO and domain ontology
    versions, terminology snapshot, engine build, policy version, activity
    time, graph key, validation report digest, and output digest. These are
    immutable metadata for the run, even when the current derived graph is
    replaced by a correction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


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
    policy_version: str
    contract_version: str
    output_graph_key: str
    output_digest: str
    validation_report_digest: str
    transform_status: str
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
        ):
            if not getattr(self, name):
                raise ValueError(f"RunRecord.{name} is required and must be non-empty")
