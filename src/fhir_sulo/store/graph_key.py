"""Deterministic output graph key.

Concept note section 7: "the generated graph for one source resource/version
has a deterministic graph key". Plan Gate 4: "unchanged reprocessing changes no
triples" and "version 2 removes stale version-1 derived assertions from the
current semantic graph while preserving version-1 lineage".

Those two sentences need *two* identifiers, not one, and conflating them is the
main way this gets built wrong:

``graph_key``
    Names one immutable derived graph. It is a function of every input that can
    change an emitted triple, including the source ``versionId``. Version 1 and
    version 2 of a resource therefore have **different** graph keys - which is
    exactly right, because both must remain retrievable and auditable.

``subject_key``
    Names the *replacement slot*: the thing in the world the graph is about,
    under one map. Every version of one source resource under one map shares a
    subject key. The store keeps at most one *current* graph per subject key,
    so loading version 2 retires version 1 from the current semantic graph
    without deleting it.

If only ``graph_key`` existed, nothing would tell the store that G2 supersedes
G1 rather than sitting beside it. If only ``subject_key`` existed, version 1
would be overwritten and its lineage lost. See DR-601.

What the content key covers, and why
------------------------------------
The rule is: **the key covers exactly the inputs that can change the emitted
triples, and nothing else.** Anything time-, run- or outcome-dependent is
excluded, otherwise reprocessing an unchanged resource would mint a new graph
and Gate 4 could never pass.

============================= ==============================================
Field                         Why a change to it changes the triples
============================= ==============================================
source_canonical_url          different resource
source_version_id             different version (concept note section 7)
source_json_digest            guards a server that reuses a versionId after an
                              edit; also lets "unchanged" be decided from the
                              key alone rather than by diffing graphs
map_id                        different mapping family
map_semantic_version          different reviewed revision of that family
pairing_hash                  immutable hash of the actual schema pair
sulo_version                  target upper-level vocabulary
domain_ontology_version       domain classes emitted (blocked on R1)
terminology_snapshot          code-to-class interpretation changes types
policy_version                identity/quality-identity policy changes node
                              IRIs (R2 decides this one outright)
engine_build                  DR-301 B2/B3: two engine builds can silently
                              emit different graphs, so an engine upgrade must
                              mint a new key rather than overwrite in place
contract_version              interface generation the run was produced under
============================= ==============================================

Deliberately excluded: ``run_id``, ``activity_time``, ``output_digest``,
``validation_report_digest``, ``transform_status``, ``superseded_by``,
``notes``. The first two are wall-clock/nondeterministic; the rest are
*outcomes* of the run, and keying on an outcome makes the key uncomputable
before the run and therefore useless for deciding whether to run at all.

Known gap
---------
The FHIR RDF renderer identity (``SourceContext.renderer_id``, Agent 2) can
change the source graph and hence the target triples, but ``RunRecord`` has no
field for it. Rather than key on something a ``RunRecord`` cannot reproduce -
which would break the invariant below - it is left out and raised as an
interface request to Agent 1. See DR-601 "Open interface request".

Invariant enforced by ``tests/integration/test_graph_key.py``::

    graph_key_from_run_record(rr) == rr.output_graph_key

i.e. the key of any archived run is recomputable from its own audit record. A
key that could not be recomputed from the record would make the correction
history unverifiable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .canonical import digest

__all__ = [
    "KEY_SPEC_VERSION",
    "KEY_NAMESPACE",
    "CONTENT_FIELDS",
    "SUBJECT_FIELDS",
    "EXCLUDED_RUN_RECORD_FIELDS",
    "GraphKeyInputs",
    "graph_key",
    "subject_key",
    "graph_key_from_run_record",
    "subject_key_from_run_record",
]

KEY_SPEC_VERSION = "graph-key/2"
"""Bumped only by a decision record. A bump re-keys every graph in the store,
so it is folded into the hash input explicitly rather than left implicit.

graph-key/2 (DR-016) adds ``person_index_digest``. Without it, the same source
under two different person-identifier indexes produced the SAME key for two
graphs whose entity IRIs differ -- so the store believed it already held the
graph and never superseded it. A key that does not change when the content
does is the one failure a content-addressed store cannot tolerate."""

KEY_NAMESPACE = "urn:fhir-sulo"
"""A URN, deliberately. An ``http(s)`` graph IRI would need a project namespace,
and that is review item R1, which is open. A URN is a valid IRI for a named
graph and commits us to nothing. Changing it is a KEY_SPEC_VERSION bump."""

SUBJECT_LENGTH = 24   # 96 bits
CONTENT_LENGTH = 40   # 160 bits

CONTENT_FIELDS = (
    "source_canonical_url",
    "source_version_id",
    "source_json_digest",
    "map_id",
    "map_semantic_version",
    "pairing_hash",
    "sulo_version",
    "domain_ontology_version",
    "terminology_snapshot",
    "policy_version",
    "engine_build",
    "renderer_id",     # IR-601: the renderer can change the emitted triples
    # R8b/DR-016: the person-identifier index decides which source records are
    # one person, so it changes the entity IRIs in the emitted graph. "none"
    # when no index is in use -- an explicit token, like every other field
    # here, so "no index" and "some index" cannot hash alike.
    "person_index_digest",
    "contract_version",
)

SUBJECT_FIELDS = (
    "source_canonical_url",
    "map_id",
)

EXCLUDED_RUN_RECORD_FIELDS = (
    "run_id",
    "activity_time",
    "output_graph_key",
    "output_digest",
    "validation_report_digest",
    "transform_status",
    "superseded_by",
    "notes",
)


class GraphKeyError(ValueError):
    """A graph key could not be computed from the inputs given."""


@dataclass(frozen=True)
class GraphKeyInputs:
    """Exactly the inputs the graph key is a function of.

    Every field is required and must be non-empty. An unresolved policy must be
    recorded as an explicit token (``"unresolved:R1"``, ``"none"``, ...) rather
    than an empty string: an empty string and a real value must not be able to
    hash to the same graph, and "we had not decided yet" is itself a fact about
    the run that belongs in the key.
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
    person_index_digest: str
    contract_version: str

    def __post_init__(self) -> None:
        for name in CONTENT_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str):
                raise GraphKeyError(
                    "graph key input %s must be a string, got %s"
                    % (name, type(value).__name__)
                )
            if not value.strip():
                raise GraphKeyError(
                    "graph key input %s is empty; record an explicit token such as "
                    "'unresolved:R1' instead, so that 'undecided' and 'decided' "
                    "cannot hash to the same graph" % name
                )

    def as_dict(self) -> Mapping[str, str]:
        return {name: getattr(self, name) for name in CONTENT_FIELDS}

    @classmethod
    def from_run_record(cls, record) -> "GraphKeyInputs":
        """Rebuild the key inputs from an immutable ``RunRecord``."""
        missing = [f for f in CONTENT_FIELDS if not hasattr(record, f)]
        if missing:
            raise GraphKeyError(
                "run record is missing graph key fields %s; the key must be "
                "recomputable from the audit record alone" % sorted(missing)
            )
        return cls(**{f: getattr(record, f) for f in CONTENT_FIELDS})


def _fragment(fields, values: Mapping[str, str], length: int, label: str) -> str:
    payload = [["spec", KEY_SPEC_VERSION], ["kind", label]]
    for field in fields:
        if field not in values:
            raise GraphKeyError("missing graph key input field: %s" % field)
        value = values[field]
        if not isinstance(value, str) or not value.strip():
            raise GraphKeyError("empty graph key input field: %s" % field)
        payload.append([field, value])
    return digest(payload)[:length]


def subject_key(inputs) -> str:
    """The replacement slot IRI: one per (source resource, map), all versions."""
    values = inputs.as_dict() if isinstance(inputs, GraphKeyInputs) else inputs
    return "%s:s:%s" % (KEY_NAMESPACE, _fragment(SUBJECT_FIELDS, values, SUBJECT_LENGTH, "subject"))


def graph_key(inputs) -> str:
    """The named graph IRI for one derived graph, deterministic across processes."""
    values = inputs.as_dict() if isinstance(inputs, GraphKeyInputs) else inputs
    subject = _fragment(SUBJECT_FIELDS, values, SUBJECT_LENGTH, "subject")
    content = _fragment(CONTENT_FIELDS, values, CONTENT_LENGTH, "content")
    return "%s:g:%s:%s" % (KEY_NAMESPACE, subject, content)


def graph_key_from_run_record(record) -> str:
    return graph_key(GraphKeyInputs.from_run_record(record))


def subject_key_from_run_record(record) -> str:
    return subject_key(GraphKeyInputs.from_run_record(record))


def subject_of(graph_key_iri: str) -> str:
    """Recover the subject key from a graph key IRI, without rehashing."""
    prefix = "%s:g:" % KEY_NAMESPACE
    if not graph_key_iri.startswith(prefix):
        raise GraphKeyError("not a graph key IRI: %r" % graph_key_iri)
    rest = graph_key_iri[len(prefix):]
    subject, sep, _content = rest.partition(":")
    if not sep or len(subject) != SUBJECT_LENGTH:
        raise GraphKeyError("malformed graph key IRI: %r" % graph_key_iri)
    return "%s:s:%s" % (KEY_NAMESPACE, subject)
