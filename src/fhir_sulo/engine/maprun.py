"""Run one whole map: bind once, materialize every declared pass, union.

:func:`~fhir_sulo.engine.driver.run_pass` validates and materializes in one
step, which is right for a single-pass map. The maps in ``maps/r4/`` are not
single-pass: the engine has no ``id()``, so every IRI-identified target node is
the root of its own materialization (DR-301 4b/4c, DR-302), and the
blood-pressure map has ten of them over one source binding.

So this module binds once and materializes N times. The fail-fast rules are
:mod:`~fhir_sulo.engine.driver`'s, unchanged and shared -- every silent engine
outcome DR-301 found still raises -- with one addition that only makes sense
across passes:

**Binding coverage is a property of the map, not of a pass.** A source binding
read by the diastolic pass is legitimately unconsumed by the systolic one, so
``BindingsNotConsumed`` per pass would fire on every correct run. It is checked
once, against the union of what every pass consumed, which is the question
worth asking: did the map as a whole drop a value?
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .docker import EngineImage, default_image
from .driver import (
    AcceptCeilingReached,
    BindingsNotConsumed,
    DriverResult,
    ExplorationTruncated,
    Guards,
    MaterializationFailure,
    PassResult,
    PassSpec,
    QuadRecord,
    SourceValidationFailure,
    UnboundVariables,
    UntracedQuad,
    union_passes,
)
from .rdfterms import Quad


@dataclass(frozen=True)
class MapPass:
    """One declared pass of a map: a target shape rooted at a chosen node."""

    name: str
    shape: Optional[str]
    root: str
    static_vars: Mapping[str, Any]
    scope_name: Optional[str] = None
    key_variables: Tuple[str, ...] = ()

    def to_bridge(self) -> Dict[str, Any]:
        return {"name": self.name, "shape": self.shape, "root": self.root,
                "staticVars": dict(self.static_vars)}


@dataclass(frozen=True)
class MapJob:
    """Everything one map run needs: a source graph, a target schema, passes."""

    source_schema: str
    target_schema: str
    data: str
    node: str
    passes: Sequence[MapPass]
    source_shape: Optional[str] = None
    source_base: str = "urn:fhir-sulo:source-schema"
    target_base: str = "urn:fhir-sulo:target-schema"
    data_base: str = "urn:fhir-sulo:data"
    #: Replaces validation. Replaying a stored binding tree, or the fault
    #: injection that proves an acceptance check can fail. Never on a real run.
    bindings_override: Optional[Any] = None

    def to_bridge(self, guards: Guards) -> Dict[str, Any]:
        request: Dict[str, Any] = {
            "target": {"schema": self.target_schema, "baseIRI": self.target_base},
            "passes": [p.to_bridge() for p in self.passes],
            "options": guards.to_bridge(),
        }
        if self.bindings_override is not None:
            request["bindings"] = self.bindings_override
        request["source"] = {
            "schema": self.source_schema, "baseIRI": self.source_base,
            "data": self.data, "dataBaseIRI": self.data_base,
            "node": self.node, "shapeLabel": self.source_shape,
        }
        return request


@dataclass(frozen=True)
class MapRunResult:
    """The union of every pass, plus the bindings they were made from."""

    bindings: Any
    driver_result: DriverResult

    @property
    def passes(self) -> Tuple[PassResult, ...]:
        return self.driver_result.passes

    @property
    def records(self) -> Tuple[QuadRecord, ...]:
        return self.driver_result.records

    @property
    def quads(self) -> Tuple[Quad, ...]:
        return self.driver_result.quads

    @property
    def ntriples(self) -> Tuple[str, ...]:
        return self.driver_result.ntriples


def bind(job: MapJob, engine: Optional[EngineImage] = None) -> Any:
    """Validate the source graph and return its binding tree, nothing else."""
    engine = engine or default_image()
    request = MapJob(
        source_schema=job.source_schema, target_schema=job.target_schema,
        data=job.data, node=job.node, passes=(), source_shape=job.source_shape,
        source_base=job.source_base, target_base=job.target_base,
        data_base=job.data_base,
    ).to_bridge(Guards())
    request["passes"] = []
    response = engine.call("run-map.js", request)
    if not response.get("ok"):
        _raise_for(response, "bind")
    return response["bindings"]


def run_map(
    job: MapJob,
    engine: Optional[EngineImage] = None,
    guards: Optional[Guards] = None,
    host_consumed: Sequence[str] = (),
) -> MapRunResult:
    """Bind once, materialize every pass, union, and refuse every silent failure.

    ``host_consumed`` names the source variables the HOST reads rather than the
    target schema: node-key inputs, identity and terminology service inputs,
    eligibility guards. Without it the coverage check condemns every correct
    run of these maps, because ``panel``, ``subjectRef`` and ``status`` reach
    no target constraint by design. It comes from
    ``pipeline.manifest.host_consumed_variables``, the same derivation the
    linter's SP101 uses -- if the two disagreed, a map could pass its own gate
    and then fail every run.
    """
    engine = engine or default_image()
    guards = guards or Guards()
    if not job.passes:
        raise ValueError("a map job needs at least one pass; use bind() to bind only")

    response = engine.call("run-map.js", job.to_bridge(guards))
    if not response.get("ok"):
        _raise_for(response, response.get("stage", "?"))

    results: List[PassResult] = []
    for entry in response["passes"]:
        spec = next(p for p in job.passes if p.name == entry["name"])
        results.append(_interpret(entry, spec, guards))

    _check_map_coverage(response["passes"], host_consumed)
    return MapRunResult(bindings=response.get("bindings"),
                        driver_result=union_passes(results))


def materialize_from_bindings(
    job: MapJob,
    bindings: Any,
    engine: Optional[EngineImage] = None,
    guards: Optional[Guards] = None,
    host_consumed: Sequence[str] = (),
) -> MapRunResult:
    """Materialize from a binding tree supplied by the caller.

    Two legitimate callers: a replay of a stored binding tree, and a test that
    injects a corrupted one to prove its acceptance checks can fail. Named
    explicitly rather than offered as a flag on the normal path, so a real run
    cannot reach it by accident.
    """
    replayed = MapJob(
        source_schema=job.source_schema, target_schema=job.target_schema,
        data=job.data, node=job.node, passes=job.passes,
        source_shape=job.source_shape, source_base=job.source_base,
        target_base=job.target_base, data_base=job.data_base,
        bindings_override=bindings,
    )
    return run_map(replayed, engine=engine, guards=guards,
                   host_consumed=host_consumed)


# ---------------------------------------------------------------------------
# fail-fast, shared with the single-pass driver
# ---------------------------------------------------------------------------


def _raise_for(response: Mapping[str, Any], stage: str) -> None:
    name = response.get("pass") or "map"
    if response.get("stage") == "validate" and "validation" in response:
        raise SourceValidationFailure(
            name, "source graph does not conform to the source schema",
            response["validation"])
    raise MaterializationFailure(
        name,
        f"engine failed at stage {response.get('stage', stage)}: "
        f"{response.get('error', 'no message')}",
        response.get("report"))


def _interpret(entry: Mapping[str, Any], spec: MapPass, guards: Guards) -> PassResult:
    """The driver's per-pass rules, minus the map-wide coverage check."""
    missing = [k for k in ("lastReport", "coverage", "constraints", "quads",
                           "provenance", "accepts")
               if entry.get(k) is None]
    if missing:
        raise MaterializationFailure(
            spec.name,
            f"the engine response is missing {missing}; the checks those fields "
            f"feed would not run, and a pass that skipped its checks is not a pass")

    report = entry["lastReport"]
    unbound = report.get("unboundVariables") or []
    if unbound:
        names = ", ".join(sorted({str(u.get("variable")) for u in unbound}))
        raise UnboundVariables(
            spec.name,
            f"target schema references unbound variable(s) {names}. The engine "
            f"prunes the branches that need them and returns a PARTIAL graph "
            f"with exit 0 (DR-301 probe 8c)", unbound)

    unused = report.get("unusedStatics") or []
    if unused:
        # staticVars are scoped per pass, so an unused one is a run binding --
        # an identity-resolved person, a terminology-resolved unit -- that the
        # host computed and the graph never received. Silent, and a mis-map.
        raise UnusedRunBindings(
            spec.name,
            f"run binding(s) {sorted(unused)} were supplied to this pass and never "
            f"reached the graph. An identity- or terminology-provided value that "
            f"does not appear in the output is a silent mis-map",
            unused)

    if report.get("explorationTruncated"):
        raise ExplorationTruncated(
            spec.name,
            "the engine stopped searching before it was done; the graph may be "
            "missing repetitions. Raise Guards.explore_steps", report)

    accepts = tuple(entry["accepts"])
    if len(accepts) >= guards.max_accepts:
        raise AcceptCeilingReached(
            spec.name,
            f"the accept ceiling ({guards.max_accepts}) was reached, so the chosen "
            f"materialization is the best of a truncated search (DR-301 B2)",
            {"accepts": len(accepts)})

    quads = entry["quads"]
    provenance = entry["provenance"]
    if len(quads) != len(provenance):
        raise UntracedQuad(
            spec.name,
            f"{len(quads)} quads but {len(provenance)} provenance entries; lineage "
            f"is not parallel to output and cannot be trusted")

    constraints = tuple(entry["constraints"])
    declared = {c["id"] for c in constraints}
    records: List[QuadRecord] = []
    for raw_quad, prov in zip(quads, provenance):
        constraint_id = prov.get("constraintId")
        if not constraint_id or constraint_id not in declared:
            raise UntracedQuad(
                spec.name,
                f"a quad names constraint {constraint_id!r}, which the target schema "
                f"does not declare; the graph is not fully attributable", prov)
        records.append(QuadRecord(
            quad=Quad.from_bridge(raw_quad),
            pass_id=spec.name,
            constraint_id=constraint_id,
            predicate=prov.get("predicate", ""),
            kind=prov.get("kind", "binding"),
            variables=tuple(prov.get("variables") or ()),
            frame=prov.get("frame"),
        ))

    return PassResult(
        pass_id=spec.name,
        records=tuple(records),
        binding_tree_raw=None,          # the map's tree is held once, on MapRunResult
        frames=tuple(entry.get("frames") or ()),
        frame_origins=tuple(entry.get("frameOrigins") or ()),
        constraints=constraints,
        last_report=report,
        accepts=accepts,
        coverage=entry["coverage"],
        root=spec.root,
        scope_name=spec.scope_name,
        key_variables=tuple(spec.key_variables),
    )


def _check_map_coverage(
    entries: Sequence[Mapping[str, Any]], host_consumed: Sequence[str] = ()
) -> None:
    """Did the map as a whole consume every source binding?

    Per pass this question has no useful answer -- the systolic pass does not
    read the diastolic value and should not -- so it is asked once, over the
    union. A binding no pass consumed is a value the source offered and the
    target graph does not contain.
    """
    if not entries:
        return
    # A binding is unconsumed BY THE MAP only if every pass left it unconsumed,
    # hence the intersection: one pass reading it is enough.
    unconsumed: Optional[set] = None
    for entry in entries:
        coverage = entry.get("coverage") or {}
        if not coverage.get("chosenAvailable"):
            raise MaterializationFailure(
                entry.get("name", "?"),
                "the engine reported no chosen materialization, so which bindings "
                "were consumed is unknown and coverage cannot be checked", coverage)
        keys = set(coverage.get("unconsumedVariables") or [])
        unconsumed = keys if unconsumed is None else (unconsumed & keys)
    left = (unconsumed or set()) - set(host_consumed)
    if left:
        raise BindingsNotConsumed(
            "map",
            f"{len(left)} source variable(s) were read by no pass of this map and "
            f"are not declared as host-consumed, so the mapping dropped data: "
            f"{sorted(left)[:8]}",
            {"unconsumed": sorted(left), "hostConsumed": sorted(host_consumed)})


class UnusedRunBindings(MaterializationFailure):
    """A staticVar handed to a pass that never read it.

    CD-1's runtime half. The engine reports it in ``lastReport.unusedStatics``
    and otherwise carries on, so an identity-resolved person IRI can be
    computed, handed over, and silently left out of the graph.
    """
