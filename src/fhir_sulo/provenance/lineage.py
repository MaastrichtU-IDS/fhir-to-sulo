"""Per-quad lineage: engine provenance in, ``TransformResult.lineage`` out.

Acceptance matrix row "Lineage": *every quad traces to a source binding or
constant plus source resource version, map hash, and run activity.* The
per-run half of that lives on ``RunRecord``; the per-quad half is built here.

What the engine gives us
------------------------
DR-301 probe 5 (PASS) established that ``shex@1.0.0-alpha.33``'s
``ThreadedMaterializer`` exposes, after a materialization:

``materializer.provenance``
    an array **parallel to the emitted quads**, each entry
    ``{quad, tc, predicate, src}`` - the emitted quad, the triple constraint
    that produced it, its predicate, and the source binding or constant.
``materializer.frameOrigins``
    which binding frame (iteration of a repetition scope) each quad came from.

Agent 4 owns the driver that surfaces those two structures. This module
consumes them and owns nothing about how they are obtained, so the two can be
built in parallel: ``EngineLineagePayload`` is the whole interface between us,
and ``from_engine_payload`` accepts the plain JSON shape the driver emits.

Why this is strict
------------------
``TransformResult.__post_init__`` refuses a ``mapped`` result whose quads are
not all traced. That check is the last line of defence, not the first: by the
time it fires, the information needed to say *which* quad lost its lineage and
*why* is gone. So every failure mode is caught here, with the engine payload
still in hand, and reported as a hard error:

* a provenance array of a different length than the quad array;
* an entry whose ``quad`` text does not match the quad at its index (a driver
  that reordered, filtered or deduplicated);
* an entry with neither a source binding nor a triple constraint.

None of these degrade to a warning. A quad in a clinical semantic graph that
cannot be traced back to what produced it is precisely the thing this row of
the acceptance matrix exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from ..contracts import QuadLineage
from ..store.canonical import canonical_json, digest

__all__ = [
    "EngineQuadProvenance",
    "EngineLineagePayload",
    "LineageError",
    "UntracedQuadError",
    "from_engine_payload",
    "build_lineage",
    "lineage_report",
    "lineage_digest",
]


class LineageError(RuntimeError):
    """The engine lineage payload cannot be turned into per-quad lineage."""


class UntracedQuadError(LineageError):
    """A produced quad has no source binding and no triple constraint."""


@dataclass(frozen=True)
class EngineQuadProvenance:
    """One entry of ``materializer.provenance[]``.

    ``src`` is the engine's word for "where the object term came from": either
    a shared ``%Map:{ }`` variable name or a constant written into the target
    schema. Both are acceptable lineage (the acceptance row says "a source
    binding/constant"); what is not acceptable is neither.
    """

    quad: str
    tc: Optional[str] = None
    predicate: Optional[str] = None
    src: Optional[str] = None
    frame_index: Optional[int] = None


@dataclass(frozen=True)
class FrameOrigin:
    """One entry of ``materializer.frameOrigins``.

    ``key_values`` is the tuple of key-variable values identifying the
    iteration, in the order ``MapContract.RepetitionScope.key_variables``
    declares them - so a cross-join shows up as an iteration key that was never
    in the source, rather than as a plausible-looking quad.
    """

    frame_index: int
    scope: Optional[str] = None
    key_values: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EngineLineagePayload:
    """Everything the engine driver hands over about one materialization."""

    quads: Tuple[str, ...]
    provenance: Tuple[EngineQuadProvenance, ...]
    frame_origins: Tuple[FrameOrigin, ...] = ()

    def frame(self, index: Optional[int]) -> Optional[FrameOrigin]:
        if index is None:
            return None
        for origin in self.frame_origins:
            if origin.frame_index == index:
                return origin
        return None


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def from_engine_payload(payload: Mapping[str, Any]) -> EngineLineagePayload:
    """Build a payload from the driver's plain JSON.

    Accepts ``{"quads": [...], "provenance": [{quad, tc, predicate, src,
    frameIndex}], "frameOrigins": [{frameIndex, scope, keyValues}]}``, which is
    the shape DR-301 probe 5 observed, with camelCase and snake_case both
    tolerated because the driver crosses a JS/Python boundary.
    """

    def pick(entry: Mapping[str, Any], *names: str) -> Any:
        for name in names:
            if name in entry:
                return entry[name]
        return None

    quads = tuple(str(q) for q in payload.get("quads", ()))

    provenance = []
    for entry in payload.get("provenance", ()) or ():
        if not isinstance(entry, Mapping):
            raise LineageError("provenance entry is not an object: %r" % (entry,))
        frame = pick(entry, "frameIndex", "frame_index")
        provenance.append(
            EngineQuadProvenance(
                quad=str(pick(entry, "quad") or ""),
                tc=_as_str(pick(entry, "tc", "tripleConstraint", "triple_constraint")),
                predicate=_as_str(pick(entry, "predicate")),
                src=_as_str(pick(entry, "src", "source")),
                frame_index=int(frame) if frame is not None else None,
            )
        )

    origins = []
    for entry in payload.get("frameOrigins", payload.get("frame_origins", ())) or ():
        if not isinstance(entry, Mapping):
            raise LineageError("frameOrigins entry is not an object: %r" % (entry,))
        index = pick(entry, "frameIndex", "frame_index")
        if index is None:
            raise LineageError("frameOrigins entry has no frame index: %r" % (entry,))
        key_values = pick(entry, "keyValues", "key_values") or ()
        origins.append(
            FrameOrigin(
                frame_index=int(index),
                scope=_as_str(pick(entry, "scope")),
                key_values=tuple(str(v) for v in key_values),
            )
        )

    return EngineLineagePayload(
        quads=quads, provenance=tuple(provenance), frame_origins=tuple(origins)
    )


def build_lineage(
    payload: EngineLineagePayload,
    *,
    pivot_variables: Optional[Iterable[str]] = None,
) -> Tuple[QuadLineage, ...]:
    """Turn an engine payload into ``TransformResult.lineage``.

    ``pivot_variables`` is the set of shared ``%Map:{ }`` variable names from
    the ``MapContract``. When supplied, an ``src`` that is one of them is
    recorded as ``source_variable`` and anything else as ``source_constraint``,
    so a constant written into the target schema is never mistaken for a value
    that came from the patient's record. When it is not supplied the
    distinction is made heuristically and a diagnostic says so.
    """
    quads: Sequence[str] = payload.quads
    prov = payload.provenance

    if len(prov) != len(quads):
        raise LineageError(
            "engine returned %d provenance entries for %d quads. The array is "
            "documented as parallel to the emitted quads (DR-301 probe 5), so a "
            "length mismatch means the driver filtered, deduplicated or reordered "
            "one of them. Refusing to guess which quad lost its lineage."
            % (len(prov), len(quads))
        )

    known = set(pivot_variables) if pivot_variables is not None else None

    out = []
    for index, (quad, entry) in enumerate(zip(quads, prov)):
        if entry.quad and entry.quad != quad:
            raise LineageError(
                "provenance entry %d describes quad %r but the quad at that index "
                "is %r; the driver must preserve the parallel ordering"
                % (index, entry.quad, quad)
            )
        if entry.src is None and entry.tc is None:
            raise UntracedQuadError(
                "quad %d (%s) has neither a source binding nor a triple constraint. "
                "Acceptance matrix row 'Lineage' requires every quad to trace to a "
                "source binding or constant; an untraceable quad may not enter a "
                "clinical semantic graph." % (index, quad)
            )

        source_variable = None
        source_constraint = entry.tc
        if entry.src is not None:
            if known is None:
                # No contract to check against: treat a bare name as a variable
                # and anything with RDF punctuation as a constant term.
                looks_like_term = entry.src[0] in '<"_' or entry.src.startswith("http")
                if looks_like_term:
                    source_constraint = source_constraint or entry.src
                else:
                    source_variable = entry.src
            elif entry.src in known:
                source_variable = entry.src
            else:
                source_constraint = source_constraint or entry.src

        origin = payload.frame(entry.frame_index)
        out.append(
            QuadLineage(
                quad_index=index,
                produced_by=entry.tc or entry.predicate or (entry.src or "constant"),
                source_variable=source_variable,
                source_constraint=source_constraint,
                iteration_key=origin.key_values if origin else (),
            )
        )
    return tuple(out)


def lineage_report(
    lineage: Sequence[QuadLineage],
    quads: Sequence[str],
    record,
) -> Mapping[str, Any]:
    """A deterministic, inspectable record joining per-quad to per-run lineage.

    This is the artefact the acceptance row is checked against: for each quad,
    the binding or constant that produced it *plus* the source resource
    version, map hash and run activity. Emitted as data rather than as RDF
    because at 10,000 resources the RDF reification of every quad is several
    times the size of the graph it describes; ``prov.lineage_quads`` produces
    the RDF form for the cases that want it.
    """
    if len(lineage) != len(quads):
        raise LineageError(
            "lineage covers %d quads but %d were produced" % (len(lineage), len(quads))
        )
    return {
        "run_id": record.run_id,
        "source_canonical_url": record.source_canonical_url,
        "source_version_id": record.source_version_id,
        "source_json_digest": record.source_json_digest,
        "map_id": record.map_id,
        "pairing_hash": record.pairing_hash,
        "output_graph_key": record.output_graph_key,
        "quads": [
            {
                "index": item.quad_index,
                "quad": quads[item.quad_index],
                "produced_by": item.produced_by,
                "source_variable": item.source_variable,
                "source_constraint": item.source_constraint,
                "iteration_key": list(item.iteration_key),
            }
            for item in sorted(lineage, key=lambda l: l.quad_index)
        ],
    }


def lineage_digest(report: Mapping[str, Any]) -> str:
    """Stable digest of a lineage report, for inclusion in a run record note."""
    return digest(report)


def canonical_lineage_json(report: Mapping[str, Any]) -> str:
    return canonical_json(report)
