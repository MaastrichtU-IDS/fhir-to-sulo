"""Shared interfaces fixed at Gate 0.

Implementation plan section 3 fixes four interfaces before parallel work starts:
SourceContext, MapContract, TransformResult and RunRecord. Every agent codes
against these; changes require a reviewed contract change by the integration
lead (plan section 6 rule 1).

Design rules enforced here, traceable to the contract documents:

* A resolved FHIR reference carries no person-equivalence claim
  (concept note section 2). ``ResolvedReference`` therefore holds evidence and
  an optional entity IRI that is only populated by the identity service, and
  ``TransformStatus`` gates what may reach a clinical graph.
* Only ``TransformStatus.MAPPED`` output may be loaded into a clinical semantic
  graph (plan section 3).
* Output graph keys are deterministic so that unchanged reprocessing changes no
  triples (plan Gate 4).
"""

from __future__ import annotations

from .source_context import (
    EligibilityOutcome,
    ReferenceEvidence,
    ResolvedReference,
    SourceContext,
)
from .map_contract import (
    MapContract,
    PivotVariable,
    RepetitionScope,
    VariableType,
)
from .transform_result import (
    BindingNode,
    QuadLineage,
    TransformResult,
    TransformStatus,
)
from .run_record import RunRecord

__all__ = [
    "EligibilityOutcome",
    "ReferenceEvidence",
    "ResolvedReference",
    "SourceContext",
    "MapContract",
    "PivotVariable",
    "RepetitionScope",
    "VariableType",
    "BindingNode",
    "QuadLineage",
    "TransformResult",
    "TransformStatus",
    "RunRecord",
]

CONTRACT_VERSION = "0.1.0"
"""Bumped by the integration lead on any breaking interface change.

Recorded in every RunRecord so a run can be tied to the interface generation it
was produced under.
"""
