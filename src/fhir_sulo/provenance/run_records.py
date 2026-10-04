"""Populating the frozen ``RunRecord``, and the ``TransformResult`` it describes.

``RunRecord`` has seventeen required fields and a validator that rejects an
empty one. This module is the single place that fills them, so that "which
digest goes in ``output_digest``" has one answer instead of one per caller.

Three rules it enforces
-----------------------
1. **No silent placeholder.** An input the pilot has not decided yet (the
   domain ontology, blocked on review item R1) must be recorded as an explicit
   token such as ``"unresolved:R1"``. ``store.graph_key`` refuses an empty
   string for the same reason: "undecided" and "decided" must not hash alike.
2. **The key is computed, never passed in.** ``output_graph_key`` is derived
   from the record's own fields, so ``graph_key_from_run_record(record) ==
   record.output_graph_key`` holds by construction and the store's integrity
   check cannot be satisfied by a caller that simply agrees with itself.
3. **Digests are of canonical forms.** ``output_digest`` is the digest of the
   *sorted* quad list, not of whatever order the engine happened to emit, so
   two runs that produced the same graph have the same digest.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from ..contracts import PILOT_SOURCE_SCOPE_ID,  CONTRACT_VERSION, QuadLineage, RunRecord, TransformResult, TransformStatus
from ..store.canonical import digest
from ..store.graph_key import GraphKeyInputs, graph_key
from .lineage import EngineLineagePayload, build_lineage, lineage_report

__all__ = [
    "NOT_VALIDATED",
    "RunInputs",
    "utc_now_iso",
    "deterministic_run_id",
    "build_run_record",
    "build_transform_result",
    "output_digest",
]

NOT_VALIDATED = "none:not-validated"
"""Explicit sentinel for ``validation_report_digest``.

An empty string would read as "validated, nothing to report". This reads as
what it is, and the operator guide's inspection command surfaces it."""


def utc_now_iso() -> str:
    """Current UTC time as an ``xsd:dateTime`` string, second precision.

    Second precision deliberately: sub-second noise in an activity timestamp
    is not information anyone uses, and it makes two otherwise identical runs
    gratuitously different in the audit log.
    """
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def deterministic_run_id(graph_key_iri: str, activity_time: str) -> str:
    """A run id that is a function of the run, not of a random number.

    Re-running the same inputs at the same second yields the same run id, and
    ``RunLedger.append`` then treats it as the same run instead of appending a
    duplicate. Any other second yields a different id.
    """
    return "run-%s" % digest([graph_key_iri, activity_time])[:24]


def output_digest(quads: Iterable[str]) -> str:
    """Digest of the emitted graph, order-independent."""
    return digest(sorted(quads))


@dataclass(frozen=True)
class RunInputs:
    """Everything needed to describe one run, before the run's outcome is known.

    Split out from ``RunRecord`` so that the graph key can be computed *before*
    materialization - which is the point of a deterministic key: it lets the
    caller ask "do I already have this graph?" without producing it first.
    """

    source_canonical_url: str
    source_version_id: str
    source_json_digest: str
    map_id: str
    map_semantic_version: str
    pairing_hash: str
    sulo_version: str
    domain_ontology_version: str
    terminology_snapshot: str
    policy_version: str
    engine_build: str
    renderer_id: str
    #: DR-016. ``"none"`` when no person-identifier index is in use; the
    #: index's digest otherwise. Two indexes give different entity IRIs for
    #: one source, so they must give different graph keys.
    person_index_digest: str = "none"
    #: DR-019. Which source the resource came from. Defaults to the
    #: single-source pilot value so a one-source run need not state it.
    source_scope_id: str = PILOT_SOURCE_SCOPE_ID
    contract_version: str = CONTRACT_VERSION

    def key_inputs(self) -> GraphKeyInputs:
        return GraphKeyInputs(
            source_scope_id=self.source_scope_id,
            source_canonical_url=self.source_canonical_url,
            source_version_id=self.source_version_id,
            source_json_digest=self.source_json_digest,
            map_id=self.map_id,
            map_semantic_version=self.map_semantic_version,
            pairing_hash=self.pairing_hash,
            sulo_version=self.sulo_version,
            domain_ontology_version=self.domain_ontology_version,
            terminology_snapshot=self.terminology_snapshot,
            policy_version=self.policy_version,
            engine_build=self.engine_build,
            renderer_id=self.renderer_id,
            person_index_digest=self.person_index_digest,
            contract_version=self.contract_version,
        )

    @property
    def graph_key(self) -> str:
        return graph_key(self.key_inputs())


def build_run_record(
    inputs: RunInputs,
    *,
    status: TransformStatus,
    quads: Sequence[str] = (),
    validation_report_digest: str = NOT_VALIDATED,
    activity_time: Optional[str] = None,
    run_id: Optional[str] = None,
    notes: Tuple[str, ...] = (),
) -> RunRecord:
    """Fill every field of the frozen ``RunRecord``."""
    key = inputs.graph_key
    when = activity_time or utc_now_iso()
    return RunRecord(
        run_id=run_id or deterministic_run_id(key, when),
        activity_time=when,
        source_canonical_url=inputs.source_canonical_url,
        source_version_id=inputs.source_version_id,
        source_json_digest=inputs.source_json_digest,
        map_id=inputs.map_id,
        map_semantic_version=inputs.map_semantic_version,
        pairing_hash=inputs.pairing_hash,
        sulo_version=inputs.sulo_version,
        domain_ontology_version=inputs.domain_ontology_version,
        terminology_snapshot=inputs.terminology_snapshot,
        engine_build=inputs.engine_build,
        renderer_id=inputs.renderer_id,
        source_scope_id=inputs.source_scope_id,
        person_index_digest=inputs.person_index_digest,
        policy_version=inputs.policy_version,
        contract_version=inputs.contract_version,
        output_graph_key=key,
        output_digest=output_digest(quads),
        validation_report_digest=validation_report_digest or NOT_VALIDATED,
        transform_status=status.value,
        notes=notes,
    )


def build_transform_result(
    inputs: RunInputs,
    *,
    status: TransformStatus,
    engine_payload: Optional[EngineLineagePayload] = None,
    pivot_variables: Optional[Iterable[str]] = None,
    target_root: Optional[str] = None,
    binding_tree=None,
    binding_alternatives: Tuple = (),
    diagnostics: Tuple[str, ...] = (),
    rejection_reason: Optional[str] = None,
) -> TransformResult:
    """Assemble a ``TransformResult`` with per-quad lineage already attached.

    ``TransformResult`` refuses a ``mapped`` result whose quads are not all
    traced, so lineage is not optional for a loadable result: it is built here,
    from the engine payload, or the construction fails. That is the intended
    behaviour - a mapped graph with missing lineage should never exist as an
    object, let alone reach a store.
    """
    quads: Tuple[str, ...] = ()
    lineage: Tuple[QuadLineage, ...] = ()

    if status is TransformStatus.MAPPED:
        if engine_payload is None:
            raise ValueError(
                "a mapped result needs the engine lineage payload; without it the "
                "quads cannot be traced and the result would be rejected by its "
                "own constructor"
            )
        quads = tuple(engine_payload.quads)
        lineage = build_lineage(engine_payload, pivot_variables=pivot_variables)
    elif engine_payload is not None and engine_payload.quads:
        raise ValueError(
            "status %s carries %d quads; only mapped output may reach a clinical "
            "semantic graph (plan section 3)" % (status.value, len(engine_payload.quads))
        )

    return TransformResult(
        status=status,
        map_id=inputs.map_id,
        pairing_hash=inputs.pairing_hash,
        source_canonical_url=inputs.source_canonical_url,
        source_version_id=inputs.source_version_id,
        output_graph_key=inputs.graph_key,
        target_quads=quads,
        target_root=target_root,
        binding_tree=binding_tree,
        lineage=lineage,
        binding_alternatives=binding_alternatives,
        diagnostics=diagnostics,
        rejection_reason=rejection_reason,
    )


def result_lineage_report(result: TransformResult, record: RunRecord) -> Mapping[str, Any]:
    """The joined per-quad and per-run lineage for one result."""
    return lineage_report(result.lineage, result.target_quads, record)
