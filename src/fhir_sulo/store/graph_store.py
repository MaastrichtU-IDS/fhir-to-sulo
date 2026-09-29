"""Named graph versioning, replacement and correction.

Implements plan Gate 4 and acceptance matrix row "Correction":

* version 1 -> version 2: stale version-1 derived assertions leave the
  *current* semantic graph; version-1 graph, lineage and run record stay
  retrievable;
* ``status = entered-in-error``: clinical assertions leave the current
  semantic graph, the *source record* is retained (concept note section 2);
* unchanged reprocessing: no triples change at all.

Deliberately stdlib-only. Quads are opaque N-Quads/N-Triples lines exactly as
``TransformResult.target_quads`` carries them, so this layer needs no RDF
library and runs under the system interpreter. Parsing happens only in
``fhir_sulo.validation``, which is the layer that has to reason about them.

Three structures, each with one job
-----------------------------------
``SourceRecordRegistry``
    Append-only. One entry per (resource, version) ever seen. Nothing removes
    an entry, which is how "an error status does not erase the source record"
    is made structural rather than a promise.

``RunLedger``
    Append-only, holding immutable ``RunRecord`` objects. Supersession is
    recorded by replacing the stored object with
    ``dataclasses.replace(old, superseded_by=...)``; the ledger refuses the
    replacement if any *other* field differs, so "immutable even when its
    output graph is replaced" is enforced rather than assumed.

``NamedGraphStore``
    Two disjoint areas, ``current`` and ``archive``. Retiring a graph *moves*
    it. "Removed from the current semantic graph" is then a property of the
    data structure, not of a query filter someone can forget to apply.
"""

from __future__ import annotations

import dataclasses
import enum
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

from .canonical import canonical_json, digest
from .graph_key import graph_key_from_run_record, subject_key_from_run_record, subject_of

__all__ = [
    "GraphState",
    "StoredGraph",
    "LoadAction",
    "LoadOutcome",
    "SourceRecord",
    "SourceRecordRegistry",
    "RunLedger",
    "NamedGraphStore",
    "StoreIntegrityError",
]


class StoreIntegrityError(RuntimeError):
    """The store was asked to do something that would corrupt the audit trail."""


class GraphState(enum.Enum):
    CURRENT = "current"
    SUPERSEDED = "superseded"     # a later source version replaced it
    INVALIDATED = "invalidated"   # entered-in-error, or otherwise retracted


class LoadAction(enum.Enum):
    CREATED = "created"           # first graph for this subject
    REPLACED = "replaced"         # a new version superseded the previous graph
    UNCHANGED = "unchanged"       # identical reprocessing; nothing touched
    INVALIDATED = "invalidated"   # a current graph was retracted
    HELD = "held"                 # non-mapped result, nothing was current


@dataclass(frozen=True)
class SourceRecord:
    canonical_url: str
    version_id: str
    json_digest: str
    source_status: str
    first_seen_run_id: str


@dataclass(frozen=True)
class StoredGraph:
    graph_key: str
    subject_key: str
    source_canonical_url: str
    source_version_id: str
    generated_by_run_id: str
    quads: Tuple[str, ...]
    state: GraphState
    state_reason: Optional[str] = None
    superseded_by_graph_key: Optional[str] = None
    invalidated_by_run_id: Optional[str] = None

    @property
    def content_digest(self) -> str:
        return digest(list(self.quads))


@dataclass(frozen=True)
class LoadOutcome:
    action: LoadAction
    graph_key: str
    subject_key: str
    run_id: str
    changed: bool
    triples_added: int = 0
    triples_removed: int = 0
    superseded_graph_key: Optional[str] = None
    note: Optional[str] = None


class SourceRecordRegistry:
    """Append-only inventory of every source resource version ever ingested."""

    def __init__(self) -> None:
        self._records: Dict[Tuple[str, str], SourceRecord] = {}

    def register(
        self,
        canonical_url: str,
        version_id: str,
        json_digest: str,
        source_status: str,
        run_id: str,
    ) -> SourceRecord:
        key = (canonical_url, version_id)
        existing = self._records.get(key)
        if existing is not None:
            if existing.json_digest != json_digest:
                raise StoreIntegrityError(
                    "%s version %s was already registered with a different JSON "
                    "digest (%s vs %s): a FHIR server that reuses a versionId after "
                    "an edit breaks version-based correction and must be reported, "
                    "not absorbed"
                    % (canonical_url, version_id, existing.json_digest, json_digest)
                )
            return existing
        record = SourceRecord(canonical_url, version_id, json_digest, source_status, run_id)
        self._records[key] = record
        return record

    def get(self, canonical_url: str, version_id: str) -> Optional[SourceRecord]:
        return self._records.get((canonical_url, version_id))

    def versions_of(self, canonical_url: str) -> Tuple[SourceRecord, ...]:
        return tuple(
            r for (url, _v), r in sorted(self._records.items()) if url == canonical_url
        )

    def all(self) -> Tuple[SourceRecord, ...]:
        return tuple(self._records[k] for k in sorted(self._records))

    def __len__(self) -> int:
        return len(self._records)


class RunLedger:
    """Append-only store of immutable ``RunRecord`` objects."""

    def __init__(self) -> None:
        self._records: Dict[str, object] = {}
        self._order: List[str] = []

    def append(self, record) -> None:
        run_id = record.run_id
        if run_id in self._records:
            if self._records[run_id] != record:
                raise StoreIntegrityError(
                    "run %s is already in the ledger with different content; run "
                    "records are immutable" % run_id
                )
            return
        self._records[run_id] = record
        self._order.append(run_id)

    def get(self, run_id: str):
        return self._records.get(run_id)

    def mark_superseded(self, run_id: str, superseded_by_run_id: str) -> None:
        """Record that a later run replaced this run's output graph.

        The record itself is not mutated: a new frozen record is stored that
        differs in ``superseded_by`` and in nothing else, and the "nothing
        else" is checked here rather than trusted.
        """
        old = self._records.get(run_id)
        if old is None:
            raise StoreIntegrityError("cannot supersede unknown run %s" % run_id)
        if old.superseded_by == superseded_by_run_id:
            return
        if old.superseded_by is not None:
            raise StoreIntegrityError(
                "run %s is already superseded by %s; it cannot also be superseded "
                "by %s" % (run_id, old.superseded_by, superseded_by_run_id)
            )
        new = dataclasses.replace(old, superseded_by=superseded_by_run_id)
        changed = [
            f.name
            for f in dataclasses.fields(old)
            if f.name != "superseded_by" and getattr(old, f.name) != getattr(new, f.name)
        ]
        if changed:
            raise StoreIntegrityError(
                "marking run %s superseded would change %s; run records are immutable"
                % (run_id, sorted(changed))
            )
        self._records[run_id] = new

    def all(self) -> Tuple[object, ...]:
        return tuple(self._records[r] for r in self._order)

    def for_graph(self, graph_key: str) -> Tuple[object, ...]:
        return tuple(r for r in self.all() if r.output_graph_key == graph_key)

    def __len__(self) -> int:
        return len(self._records)


class NamedGraphStore:
    """Current and archived derived graphs, keyed by subject and graph key."""

    def __init__(self) -> None:
        self.current: Dict[str, StoredGraph] = {}
        self.archive: Dict[str, StoredGraph] = {}
        self._current_of_subject: Dict[str, str] = {}
        self._history: Dict[str, List[str]] = {}
        self.sources = SourceRecordRegistry()
        self.runs = RunLedger()

    # ---------------------------------------------------------------- loading

    def load(self, result, record) -> LoadOutcome:
        """Apply one ``TransformResult`` plus its ``RunRecord`` to the store."""
        self._check_consistency(result, record)

        graph_key = record.output_graph_key
        subject = subject_key_from_run_record(record)

        self.sources.register(
            canonical_url=record.source_canonical_url,
            version_id=record.source_version_id,
            json_digest=record.source_json_digest,
            source_status=getattr(result, "source_status", "") or record.transform_status,
            run_id=record.run_id,
        )
        self.runs.append(record)

        if not getattr(result, "is_loadable", False):
            return self._apply_non_mapped(result, record, subject)

        quads = tuple(sorted(result.target_quads))
        existing_key = self._current_of_subject.get(subject)

        if existing_key == graph_key:
            stored = self.current[graph_key]
            if stored.quads != quads:
                raise StoreIntegrityError(
                    "graph %s already holds different triples for the same key. The "
                    "graph key is supposed to be a function of every input that can "
                    "change a triple, so this means an input is missing from the key "
                    "(see graph_key.CONTENT_FIELDS), not that the store should "
                    "overwrite." % graph_key
                )
            return LoadOutcome(
                action=LoadAction.UNCHANGED,
                graph_key=graph_key,
                subject_key=subject,
                run_id=record.run_id,
                changed=False,
                note="identical reprocessing; the current semantic graph was not touched",
            )

        superseded_key = None
        removed = 0
        if existing_key is not None:
            superseded_key = existing_key
            removed = self._retire(
                existing_key,
                GraphState.SUPERSEDED,
                reason="superseded by source version %s" % record.source_version_id,
                superseded_by_graph_key=graph_key,
            )
            previous = self.archive[existing_key]
            self.runs.mark_superseded(previous.generated_by_run_id, record.run_id)

        self.current[graph_key] = StoredGraph(
            graph_key=graph_key,
            subject_key=subject,
            source_canonical_url=record.source_canonical_url,
            source_version_id=record.source_version_id,
            generated_by_run_id=record.run_id,
            quads=quads,
            state=GraphState.CURRENT,
        )
        self._current_of_subject[subject] = graph_key
        self._history.setdefault(subject, []).append(graph_key)

        return LoadOutcome(
            action=LoadAction.REPLACED if superseded_key else LoadAction.CREATED,
            graph_key=graph_key,
            subject_key=subject,
            run_id=record.run_id,
            changed=True,
            triples_added=len(quads),
            triples_removed=removed,
            superseded_graph_key=superseded_key,
        )

    def _apply_non_mapped(self, result, record, subject: str) -> LoadOutcome:
        """A ``source-only`` or ``rejected`` result retracts any current graph.

        Concept note section 2: "A status of ``entered-in-error`` suppresses
        clinical assertions from that resource; it does not erase the source
        record." The source record was registered above and is never removed.
        """
        # A rejected result carries ``rejection_reason``; a source-only one
        # carries its explanation in ``diagnostics``, because the contract
        # requires a reason only for the former. Both are recorded verbatim,
        # so the archived graph says *why* it was retracted rather than only
        # that it was.
        reason = getattr(result, "rejection_reason", None) or "; ".join(
            getattr(result, "diagnostics", ()) or ()
        )
        if not reason:
            reason = (
                "transform status %s: not eligible for clinical assertions"
                % record.transform_status
            )
        existing_key = self._current_of_subject.get(subject)
        if existing_key is None:
            return LoadOutcome(
                action=LoadAction.HELD,
                graph_key=record.output_graph_key,
                subject_key=subject,
                run_id=record.run_id,
                changed=False,
                note=reason,
            )
        removed = self._retire(
            existing_key,
            GraphState.INVALIDATED,
            reason=reason,
            invalidated_by_run_id=record.run_id,
        )
        self.runs.mark_superseded(
            self.archive[existing_key].generated_by_run_id, record.run_id
        )
        self._history.setdefault(subject, []).append(record.output_graph_key)
        return LoadOutcome(
            action=LoadAction.INVALIDATED,
            graph_key=record.output_graph_key,
            subject_key=subject,
            run_id=record.run_id,
            changed=True,
            triples_removed=removed,
            superseded_graph_key=existing_key,
            note=reason,
        )

    def _retire(
        self,
        graph_key: str,
        state: GraphState,
        reason: str,
        superseded_by_graph_key: Optional[str] = None,
        invalidated_by_run_id: Optional[str] = None,
    ) -> int:
        stored = self.current.pop(graph_key)
        self._current_of_subject.pop(stored.subject_key, None)
        self.archive[graph_key] = dataclasses.replace(
            stored,
            state=state,
            state_reason=reason,
            superseded_by_graph_key=superseded_by_graph_key,
            invalidated_by_run_id=invalidated_by_run_id,
        )
        return len(stored.quads)

    @staticmethod
    def _check_consistency(result, record) -> None:
        if result.output_graph_key != record.output_graph_key:
            raise StoreIntegrityError(
                "TransformResult graph key %s does not match RunRecord graph key %s"
                % (result.output_graph_key, record.output_graph_key)
            )
        recomputed = graph_key_from_run_record(record)
        if recomputed != record.output_graph_key:
            raise StoreIntegrityError(
                "run %s carries graph key %s but its own fields hash to %s. The key "
                "must be recomputable from the audit record, otherwise the correction "
                "history cannot be verified after the fact."
                % (record.run_id, record.output_graph_key, recomputed)
            )
        if subject_of(record.output_graph_key) != subject_key_from_run_record(record):
            raise StoreIntegrityError(
                "graph key %s does not embed the subject key its run record implies"
                % record.output_graph_key
            )
        if result.source_version_id != record.source_version_id:
            raise StoreIntegrityError(
                "TransformResult is for version %s but the run record says %s"
                % (result.source_version_id, record.source_version_id)
            )

    # -------------------------------------------------------------- inspection

    def current_graph_key(self, subject_key: str) -> Optional[str]:
        return self._current_of_subject.get(subject_key)

    def current_triples(self) -> Tuple[str, ...]:
        """Every triple in the current semantic graph, deterministically ordered."""
        out: List[str] = []
        for key in sorted(self.current):
            out.extend(self.current[key].quads)
        return tuple(sorted(out))

    def archived_triples(self) -> Tuple[str, ...]:
        out: List[str] = []
        for key in sorted(self.archive):
            out.extend(self.archive[key].quads)
        return tuple(sorted(out))

    def graph(self, graph_key: str) -> Optional[StoredGraph]:
        return self.current.get(graph_key) or self.archive.get(graph_key)

    def history(self, subject_key: str) -> Tuple[StoredGraph, ...]:
        keys = self._history.get(subject_key, [])
        return tuple(g for g in (self.graph(k) for k in keys) if g is not None)

    def subjects(self) -> Tuple[str, ...]:
        return tuple(sorted(set(self._history)))

    def state_digest(self) -> str:
        """A single digest of the current semantic layer.

        Gate 4: "a clean deployment produces identical graph hashes for the
        fixture suite". This is that hash.
        """
        return digest(
            {"current": {k: list(self.current[k].quads) for k in sorted(self.current)}}
        )

    def summary(self) -> Mapping[str, object]:
        return {
            "current_graphs": len(self.current),
            "archived_graphs": len(self.archive),
            "current_triples": len(self.current_triples()),
            "archived_triples": len(self.archived_triples()),
            "source_versions": len(self.sources),
            "runs": len(self.runs),
            "state_digest": self.state_digest(),
        }

    # ------------------------------------------------------------ persistence

    STATE_VERSION = 1

    def to_state(self) -> Mapping[str, object]:
        """The whole store as plain data, deterministically ordered.

        Includes the run ledger and the source registry, not only the graphs:
        an operator who reloads a store and cannot see the earlier runs cannot
        audit a correction, and the store would happily re-create a graph it
        had already superseded.
        """

        def graph_state(g: StoredGraph) -> Mapping[str, object]:
            return {
                "subject_key": g.subject_key,
                "source_canonical_url": g.source_canonical_url,
                "source_version_id": g.source_version_id,
                "generated_by_run_id": g.generated_by_run_id,
                "state": g.state.value,
                "state_reason": g.state_reason,
                "superseded_by_graph_key": g.superseded_by_graph_key,
                "invalidated_by_run_id": g.invalidated_by_run_id,
                "quads": list(g.quads),
            }

        return {
            "state_version": self.STATE_VERSION,
            "current": {k: graph_state(self.current[k]) for k in sorted(self.current)},
            "archive": {k: graph_state(self.archive[k]) for k in sorted(self.archive)},
            "history": {k: list(v) for k, v in sorted(self._history.items())},
            "sources": [
                {
                    "canonical_url": s.canonical_url,
                    "version_id": s.version_id,
                    "json_digest": s.json_digest,
                    "source_status": s.source_status,
                    "first_seen_run_id": s.first_seen_run_id,
                }
                for s in self.sources.all()
            ],
            "runs": [
                {f.name: getattr(r, f.name) for f in dataclasses.fields(r)}
                for r in self.runs.all()
            ],
        }

    @classmethod
    def from_state(cls, state: Mapping[str, object]) -> "NamedGraphStore":
        from ..contracts import RunRecord

        version = state.get("state_version")
        if version != cls.STATE_VERSION:
            raise StoreIntegrityError(
                "store state version %r cannot be read by this build (expected %d)"
                % (version, cls.STATE_VERSION)
            )

        store = cls()
        for area, target in (("current", store.current), ("archive", store.archive)):
            for key, blob in (state.get(area) or {}).items():
                target[key] = StoredGraph(
                    graph_key=key,
                    subject_key=blob["subject_key"],
                    source_canonical_url=blob["source_canonical_url"],
                    source_version_id=blob["source_version_id"],
                    generated_by_run_id=blob["generated_by_run_id"],
                    quads=tuple(blob["quads"]),
                    state=GraphState(blob["state"]),
                    state_reason=blob.get("state_reason"),
                    superseded_by_graph_key=blob.get("superseded_by_graph_key"),
                    invalidated_by_run_id=blob.get("invalidated_by_run_id"),
                )
        for key, graph in store.current.items():
            store._current_of_subject[graph.subject_key] = key
        store._history = {k: list(v) for k, v in (state.get("history") or {}).items()}

        for blob in state.get("sources") or ():
            store.sources._records[(blob["canonical_url"], blob["version_id"])] = (
                SourceRecord(
                    canonical_url=blob["canonical_url"],
                    version_id=blob["version_id"],
                    json_digest=blob["json_digest"],
                    source_status=blob["source_status"],
                    first_seen_run_id=blob["first_seen_run_id"],
                )
            )
        for blob in state.get("runs") or ():
            payload = dict(blob)
            payload["notes"] = tuple(payload.get("notes") or ())
            store.runs.append(RunRecord(**payload))
        return store

    def to_json(self) -> str:
        return canonical_json(
            {
                "current": {
                    k: {
                        "subject_key": g.subject_key,
                        "source_canonical_url": g.source_canonical_url,
                        "source_version_id": g.source_version_id,
                        "generated_by_run_id": g.generated_by_run_id,
                        "quads": list(g.quads),
                    }
                    for k, g in self.current.items()
                },
                "archive": {
                    k: {
                        "subject_key": g.subject_key,
                        "source_canonical_url": g.source_canonical_url,
                        "source_version_id": g.source_version_id,
                        "generated_by_run_id": g.generated_by_run_id,
                        "state": g.state.value,
                        "state_reason": g.state_reason,
                        "superseded_by_graph_key": g.superseded_by_graph_key,
                        "invalidated_by_run_id": g.invalidated_by_run_id,
                        "quads": list(g.quads),
                    }
                    for k, g in self.archive.items()
                },
            }
        )
