"""PROV-O emission for derived graphs, runs and corrections.

Concept note section 7: "Link output to its source with PROV-O and retain the
ShEx.js per-quad lineage report. A correction computes a replacement graph and
removes stale derived assertions; source versions remain traceable."

Where the triples go
--------------------
Provenance never enters the semantic graph. Three separate named graphs:

``urn:fhir-sulo:prov:run:<run_id>``
    one graph per run, holding the activity, agent, plan and the entity
    description of the graph that run generated. Append-only.
``urn:fhir-sulo:prov:registry``
    the cross-run graph: source records, ``prov:specializationOf`` links from
    each version's graph to its replacement slot, and the revision and
    invalidation edges a correction adds.
``urn:fhir-sulo:prov:lineage:<run_id>``
    the optional RDF form of the per-quad lineage. Off by default; see
    ``lineage.lineage_report`` for why the default is data rather than RDF.

Keeping them apart is what makes Gate 4's "unchanged reprocessing changes no
triples" checkable at all: the semantic layer can be compared triple-for-triple
while the run ledger still grows, because the two are not mixed.

Vocabulary
----------
PROV-O for structure. The run metadata that PROV-O has no term for (digests,
build identifiers, ontology versions) uses ``urn:fhir-sulo:prov#`` - a URN for
the same reason ``store.graph_key.KEY_NAMESPACE`` is one: review item R1, which
would decide a project namespace, is open, and provenance emission must not
pre-empt it. The prefix is a module constant and changing it is a one-line
change plus a decision record.

Output format is N-Quads, one line per quad, no blank nodes, deterministic
order. No RDF library is needed to produce it, which keeps this package
importable under the system interpreter.
"""

from __future__ import annotations

import re
from typing import List, Mapping, Optional, Tuple

from ..store.graph_key import KEY_NAMESPACE, subject_key_from_run_record

__all__ = [
    "PROV",
    "FSP",
    "XSD",
    "RDF",
    "run_graph_iri",
    "registry_graph_iri",
    "lineage_graph_iri",
    "source_entity_iri",
    "run_activity_iri",
    "agent_iri",
    "plan_iri",
    "run_provenance_quads",
    "registry_quads",
    "revision_quads",
    "invalidation_quads",
    "lineage_quads",
    "ProvenanceEmitter",
]

PROV = "http://www.w3.org/ns/prov#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XSD = "http://www.w3.org/2001/XMLSchema#"
FSP = "urn:fhir-sulo:prov#"

_SAFE = re.compile(r"[^A-Za-z0-9._~:-]")


def _slug(value: str) -> str:
    return _SAFE.sub("-", value.strip()) or "unknown"


def _iri(value: str) -> str:
    return "<%s>" % value


def _lit(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return '"%s"' % escaped


def _typed(value: str, datatype: str) -> str:
    return "%s^^<%s>" % (_lit(value), datatype)


def _quad(subject: str, predicate: str, obj: str, graph: str) -> str:
    return "%s <%s> %s %s ." % (_iri(subject), predicate, obj, _iri(graph))


# ------------------------------------------------------------------ IRI minting


def run_graph_iri(run_id: str) -> str:
    return "%s:prov:run:%s" % (KEY_NAMESPACE, _slug(run_id))


def registry_graph_iri() -> str:
    return "%s:prov:registry" % KEY_NAMESPACE


def lineage_graph_iri(run_id: str) -> str:
    return "%s:prov:lineage:%s" % (KEY_NAMESPACE, _slug(run_id))


def run_activity_iri(run_id: str) -> str:
    return "%s:run:%s" % (KEY_NAMESPACE, _slug(run_id))


def agent_iri(engine_build: str) -> str:
    return "%s:agent:%s" % (KEY_NAMESPACE, _slug(engine_build))


def plan_iri(map_id: str, pairing_hash: str) -> str:
    return "%s:map:%s:%s" % (KEY_NAMESPACE, _slug(map_id), _slug(pairing_hash))


def source_entity_iri(canonical_url: str, version_id: str) -> str:
    """The FHIR version-specific read IRI, as concept note section 4 writes it.

    ``https://fhir.example/Observation/egfr-456/_history/1`` - the resource, its
    ``_history`` segment and its ``meta.versionId``. If the canonical URL
    already carries a ``_history`` segment it is used unchanged, so a caller
    that already has a version-specific URL is not double-suffixed.
    """
    url = canonical_url.rstrip("/")
    if "/_history/" in url:
        return url
    return "%s/_history/%s" % (url, version_id)


# ------------------------------------------------------------------- emission

_METADATA_FIELDS: Tuple[Tuple[str, str], ...] = (
    ("sourceJsonDigest", "source_json_digest"),
    ("mapId", "map_id"),
    ("mapSemanticVersion", "map_semantic_version"),
    ("pairingHash", "pairing_hash"),
    ("suloVersion", "sulo_version"),
    ("domainOntologyVersion", "domain_ontology_version"),
    ("terminologySnapshot", "terminology_snapshot"),
    ("engineBuild", "engine_build"),
    ("policyVersion", "policy_version"),
    ("contractVersion", "contract_version"),
    ("outputDigest", "output_digest"),
    ("validationReportDigest", "validation_report_digest"),
    ("transformStatus", "transform_status"),
)


def run_provenance_quads(
    record, *, graph_key: Optional[str] = None, source_status: Optional[str] = None
) -> Tuple[str, ...]:
    """The activity, agent, plan and generated-entity description for one run.

    ``source_status`` is the FHIR ``Observation.status`` / ``Encounter.status``
    from ``SourceContext``. ``RunRecord`` has no field for it (it carries
    ``transform_status``, which is the pipeline's verdict, not the record's
    status), so the store supplies it from its ``SourceRecordRegistry``. It is
    emitted because the negative query "no erroneous-status clinical
    assertion" has to be answerable from the graph, not only from the store's
    internal state.
    """
    graph = run_graph_iri(record.run_id)
    activity = run_activity_iri(record.run_id)
    agent = agent_iri(record.engine_build)
    plan = plan_iri(record.map_id, record.pairing_hash)
    source = source_entity_iri(record.source_canonical_url, record.source_version_id)
    derived = graph_key or record.output_graph_key

    q: List[str] = []
    add = q.append

    # --- the activity
    add(_quad(activity, RDF + "type", _iri(PROV + "Activity"), graph))
    add(_quad(activity, PROV + "startedAtTime",
              _typed(record.activity_time, XSD + "dateTime"), graph))
    add(_quad(activity, PROV + "endedAtTime",
              _typed(record.activity_time, XSD + "dateTime"), graph))
    add(_quad(activity, PROV + "used", _iri(source), graph))
    add(_quad(activity, PROV + "used", _iri(plan), graph))
    add(_quad(activity, PROV + "wasAssociatedWith", _iri(agent), graph))

    # --- the agent and its plan, qualified so the plan is not merely "used"
    add(_quad(agent, RDF + "type", _iri(PROV + "SoftwareAgent"), graph))
    add(_quad(agent, FSP + "engineBuild", _lit(record.engine_build), graph))
    add(_quad(plan, RDF + "type", _iri(PROV + "Plan"), graph))
    add(_quad(plan, RDF + "type", _iri(PROV + "Entity"), graph))
    add(_quad(plan, FSP + "mapId", _lit(record.map_id), graph))
    add(_quad(plan, FSP + "mapSemanticVersion", _lit(record.map_semantic_version), graph))
    add(_quad(plan, FSP + "pairingHash", _lit(record.pairing_hash), graph))

    # --- the source, which is an entity in its own right and never deleted
    add(_quad(source, RDF + "type", _iri(PROV + "Entity"), graph))
    add(_quad(source, FSP + "sourceCanonicalUrl", _lit(record.source_canonical_url), graph))
    add(_quad(source, FSP + "sourceVersionId", _lit(record.source_version_id), graph))
    add(_quad(source, FSP + "sourceJsonDigest", _lit(record.source_json_digest), graph))
    if source_status:
        add(_quad(source, FSP + "sourceStatus", _lit(source_status), graph))

    # --- the derived graph
    add(_quad(derived, RDF + "type", _iri(PROV + "Entity"), graph))
    add(_quad(derived, PROV + "wasGeneratedBy", _iri(activity), graph))
    add(_quad(derived, PROV + "wasDerivedFrom", _iri(source), graph))
    add(_quad(derived, PROV + "wasAttributedTo", _iri(agent), graph))
    add(_quad(derived, PROV + "generatedAtTime",
              _typed(record.activity_time, XSD + "dateTime"), graph))
    add(_quad(derived, FSP + "graphKeySpec", _lit("graph-key/1"), graph))
    for term, field in _METADATA_FIELDS:
        value = getattr(record, field, "")
        if value:
            add(_quad(derived, FSP + term, _lit(str(value)), graph))
    if record.superseded_by:
        add(_quad(activity, FSP + "supersededBy",
                  _iri(run_activity_iri(record.superseded_by)), graph))

    return tuple(sorted(q))


def registry_quads(record, *, source_status: Optional[str] = None) -> Tuple[str, ...]:
    """Cross-run edges: which replacement slot this version's graph specialises.

    ``prov:specializationOf`` is the PROV-O term for "this entity is a more
    specific version of that one", which is exactly the relation between one
    version's derived graph and the subject key that all its versions share.
    """
    graph = registry_graph_iri()
    subject = subject_key_from_run_record(record)
    source = source_entity_iri(record.source_canonical_url, record.source_version_id)
    derived = record.output_graph_key

    q = [
        _quad(subject, RDF + "type", _iri(PROV + "Entity"), graph),
        _quad(subject, FSP + "sourceCanonicalUrl", _lit(record.source_canonical_url), graph),
        _quad(subject, FSP + "mapId", _lit(record.map_id), graph),
        _quad(derived, PROV + "specializationOf", _iri(subject), graph),
        _quad(derived, PROV + "wasDerivedFrom", _iri(source), graph),
        _quad(derived, FSP + "sourceVersionId", _lit(record.source_version_id), graph),
        _quad(source, RDF + "type", _iri(PROV + "Entity"), graph),
        _quad(source, FSP + "sourceJsonDigest", _lit(record.source_json_digest), graph),
    ]
    if source_status:
        q.append(_quad(source, FSP + "sourceStatus", _lit(source_status), graph))
    return tuple(sorted(q))


def revision_quads(new_graph_key: str, old_graph_key: str, record) -> Tuple[str, ...]:
    """A version-2 graph revises the version-1 graph it replaced."""
    graph = registry_graph_iri()
    q = [
        _quad(new_graph_key, PROV + "wasRevisionOf", _iri(old_graph_key), graph),
        _quad(old_graph_key, FSP + "supersededByGraph", _iri(new_graph_key), graph),
        _quad(old_graph_key, FSP + "retiredFromCurrent",
              _typed("true", XSD + "boolean"), graph),
        _quad(old_graph_key, PROV + "invalidatedAtTime",
              _typed(record.activity_time, XSD + "dateTime"), graph),
        _quad(old_graph_key, PROV + "wasInvalidatedBy",
              _iri(run_activity_iri(record.run_id)), graph),
    ]
    return tuple(sorted(q))


def invalidation_quads(old_graph_key: str, record, reason: str) -> Tuple[str, ...]:
    """A status change to ``entered-in-error`` retracts the clinical assertions.

    The source entity is untouched on purpose. Concept note section 2: the
    error status "suppresses clinical assertions from that resource; it does
    not erase the source record".
    """
    graph = registry_graph_iri()
    q = [
        _quad(old_graph_key, PROV + "wasInvalidatedBy",
              _iri(run_activity_iri(record.run_id)), graph),
        _quad(old_graph_key, PROV + "invalidatedAtTime",
              _typed(record.activity_time, XSD + "dateTime"), graph),
        _quad(old_graph_key, FSP + "retiredFromCurrent",
              _typed("true", XSD + "boolean"), graph),
        _quad(old_graph_key, FSP + "retractionReason", _lit(reason), graph),
        _quad(old_graph_key, FSP + "sourceRecordRetained",
              _typed("true", XSD + "boolean"), graph),
    ]
    return tuple(sorted(q))


def lineage_quads(report: Mapping[str, object], run_id: str) -> Tuple[str, ...]:
    """The RDF form of a per-quad lineage report, using RDF reification.

    Off the default path. At the Gate 4 scale this is roughly five triples per
    produced triple, so it is produced on request for the graphs an
    investigator is actually looking at, and the data form in
    ``lineage.lineage_report`` carries the same facts for everything else.
    """
    graph = lineage_graph_iri(run_id)
    activity = run_activity_iri(run_id)
    q: List[str] = []
    for item in report.get("quads", ()):  # type: ignore[union-attr]
        index = item["index"]
        node = "%s:lineage:%s:%d" % (KEY_NAMESPACE, _slug(run_id), index)
        q.append(_quad(node, RDF + "type", _iri(PROV + "Entity"), graph))
        q.append(_quad(node, FSP + "quadIndex",
                       _typed(str(index), XSD + "integer"), graph))
        q.append(_quad(node, FSP + "quadText", _lit(str(item["quad"])), graph))
        q.append(_quad(node, PROV + "wasGeneratedBy", _iri(activity), graph))
        q.append(_quad(node, FSP + "producedBy", _lit(str(item["produced_by"])), graph))
        if item.get("source_variable"):
            q.append(_quad(node, FSP + "sourceVariable",
                           _lit(str(item["source_variable"])), graph))
        if item.get("source_constraint"):
            q.append(_quad(node, FSP + "sourceConstraint",
                           _lit(str(item["source_constraint"])), graph))
        for position, value in enumerate(item.get("iteration_key", ())):
            q.append(_quad(node, FSP + "iterationKey%d" % position, _lit(str(value)), graph))
    return tuple(sorted(q))


class ProvenanceEmitter:
    """Accumulates provenance quads across a batch, deterministically."""

    def __init__(self, *, emit_lineage_rdf: bool = False) -> None:
        self.emit_lineage_rdf = emit_lineage_rdf
        self._run: List[str] = []
        self._registry: List[str] = []
        self._lineage: List[str] = []

    def record_run(
        self, record, outcome=None, lineage_report=None, source_status=None
    ) -> None:
        self._run.extend(run_provenance_quads(record, source_status=source_status))
        self._registry.extend(registry_quads(record, source_status=source_status))
        if outcome is not None and getattr(outcome, "superseded_graph_key", None):
            action = getattr(outcome.action, "value", str(outcome.action))
            if action == "invalidated":
                self._registry.extend(
                    invalidation_quads(
                        outcome.superseded_graph_key, record,
                        outcome.note or "retracted",
                    )
                )
            else:
                self._registry.extend(
                    revision_quads(outcome.graph_key, outcome.superseded_graph_key, record)
                )
        if self.emit_lineage_rdf and lineage_report is not None:
            self._lineage.extend(lineage_quads(lineage_report, record.run_id))

    def quads(self) -> Tuple[str, ...]:
        return tuple(sorted(set(self._run) | set(self._registry) | set(self._lineage)))

    def nquads(self) -> str:
        return "\n".join(self.quads()) + ("\n" if self._run or self._registry else "")
