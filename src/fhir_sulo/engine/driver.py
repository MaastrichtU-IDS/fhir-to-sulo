"""The materialization driver: a driver, and provably not a transformer.

CD-2 bans ``shexmap-materialize``. This is the supported entry point. It does
four things and refuses to do a fifth:

1. **Sets every engine guard explicitly.** DR-301 B2: ``maxAccepts`` defaults to
   20, which silently truncates any repeated constraint to 19 items -- 60 in,
   19 out, exit 0, empty stderr. Nothing here inherits an engine default, so a
   change to one cannot quietly change our output.
2. **Fails fast.** DR-301 B3: the engine's CLI exits 0 on a fatal error *and* on
   a partial graph. Every silent failure mode found in the spike is turned into
   an exception here: see :class:`MaterializationFailure` and the checks in
   :func:`run_pass`.
3. **Unions passes without merging their blank nodes.** DR-302's decomposition
   runs one pass per level of repetition. Each pass restarts its blank node
   counter at ``_:tm0``, so the union relabels per pass -- and then checks that
   relabelling changed nothing but labels.
4. **Carries lineage from the first moment.** ``provenance[]`` and
   ``frameOrigins`` are threaded into :class:`~fhir_sulo.contracts.QuadLineage`
   as the quads are collected, not reconstructed later.

The fifth thing -- emitting or amending a triple -- is what separates a driver
from the postprocessor DR-302 forbids. It is enforced, not promised:
``run-pass.js`` numbers every TripleConstraint in the target schema and tags
each emitted quad with the id of the one that produced it, and
:meth:`DriverResult.untraced_quads` is empty only if every quad in the union
names a constraint from the target schema that produced it. The host has no
code path that constructs a quad; ``tests/engine/test_driver.py`` asserts this
against the union, not against a single pass.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..contracts import BindingNode, QuadLineage, TransformResult, TransformStatus
from .docker import EngineImage, default_image
from .rdfterms import Quad, shape_signature

#: A pass id prefixes blank node labels, so it has to be a legal label itself.
_VALID_PASS_ID = re.compile(r"\A[A-Za-z0-9_][A-Za-z0-9_-]*\Z")

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Guards:
    """Engine search guards. Ours, not the engine's.

    ``max_accepts`` must exceed the largest number of repetitions any single
    constraint will produce, because the engine records one accepting
    materialization per repetition count and stops collecting at this limit,
    keeping the best it has found so far (DR-301 §11). The default is set well
    above any plausible per-resource cardinality rather than being tuned, and
    the driver fails loudly if the ceiling is ever reached, so a wrong value
    cannot pass as a small graph.

    The cost is that the search never short-circuits, making it quadratic in
    the repetition count: measured 100/100 in 25 ms, 1000/1000 in 2.1 s,
    2000/2000 in 12.4 s. Per FHIR resource this is comfortable; a
    Bundle-rooted map would not be, which is one more reason DR-302 exists.
    """

    max_accepts: int = 100_000
    max_repeat: int = 100_000
    max_steps: int = 100_000_000
    explore_steps: int = 100_000_000
    max_call_depth: int = 50

    def to_bridge(self) -> Dict[str, int]:
        return {
            "maxAccepts": self.max_accepts,
            "maxRepeat": self.max_repeat,
            "maxSteps": self.max_steps,
            "exploreSteps": self.explore_steps,
            "maxCallDepth": self.max_call_depth,
        }


@dataclass(frozen=True)
class PassSpec:
    """One validate-and-materialize pass.

    A single-level map is one pass. DR-302's decomposition is pass A (the
    skeleton, whose target emits each group's own IRI as a leaf) followed by
    one pass per group, each rooted at that IRI -- which is how the union joins
    without the host inventing a link.
    """

    pass_id: str
    source_schema: str
    data: str
    node: str
    target_schema: str
    root: str
    source_base: str = "urn:fhir-sulo:source-schema"
    target_base: str = "urn:fhir-sulo:target-schema"
    data_base: str = "urn:fhir-sulo:data"
    source_shape: Optional[str] = None
    target_shape: Optional[str] = None
    static_vars: Mapping[str, str] = field(default_factory=dict)
    #: names the repetition scope this pass's repeated group belongs to, so the
    #: binding tree can answer ``tuples_for_scope`` (MapContract.RepetitionScope)
    scope_name: Optional[str] = None
    key_variables: Tuple[str, ...] = ()

    def to_bridge(self, guards: Guards) -> Dict[str, Any]:
        return {
            "source": {
                "schema": self.source_schema, "baseIRI": self.source_base,
                "data": self.data, "dataBaseIRI": self.data_base,
                "node": self.node, "shapeLabel": self.source_shape,
            },
            "target": {
                "schema": self.target_schema, "baseIRI": self.target_base,
                "shapeLabel": self.target_shape,
            },
            "root": self.root,
            "staticVars": dict(self.static_vars),
            "options": guards.to_bridge(),
        }


# --------------------------------------------------------------------------
# failures
# --------------------------------------------------------------------------


class MaterializationFailure(RuntimeError):
    """A pass failed, or succeeded in one of the engine's silent ways.

    Every subclass corresponds to a DR-301 finding where the engine's own CLI
    would have exited 0.
    """

    def __init__(self, pass_id: str, message: str, detail: Any = None):
        self.pass_id = pass_id
        self.detail = detail
        super().__init__(f"pass {pass_id!r}: {message}")


class SourceValidationFailure(MaterializationFailure):
    """The source graph does not conform to the source schema."""


class UnboundVariables(MaterializationFailure):
    """DR-301 probe 8c: a partial graph with exit 0 and an empty stderr."""


class ExplorationTruncated(MaterializationFailure):
    """The engine gave up searching; the graph may be incomplete."""


class BindingsNotConsumed(MaterializationFailure):
    """Source bindings the target schema never asked for. Data would be lost."""


class UntracedQuad(MaterializationFailure):
    """A quad with no target-schema constraint behind it. Should be impossible."""


class AcceptCeilingReached(MaterializationFailure):
    """DR-301 B2: the 19-item truncation, made loud."""


# --------------------------------------------------------------------------
# results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class QuadRecord:
    """One emitted quad with the lineage the engine gave for it."""

    quad: Quad
    pass_id: str
    constraint_id: str
    predicate: str
    kind: str                      # binding | constant | structural | static
    variables: Tuple[str, ...]
    frame: Optional[int]

    @property
    def qualified_constraint(self) -> str:
        return f"{self.pass_id}#{self.constraint_id}"


@dataclass(frozen=True)
class PassResult:
    """Everything one pass produced, before the union."""

    pass_id: str
    records: Tuple[QuadRecord, ...]
    binding_tree_raw: Any
    frames: Tuple[Any, ...]
    frame_origins: Tuple[Any, ...]
    constraints: Tuple[Mapping[str, Any], ...]
    last_report: Mapping[str, Any]
    accepts: Tuple[Mapping[str, Any], ...]
    coverage: Mapping[str, Any]
    root: str
    scope_name: Optional[str]
    key_variables: Tuple[str, ...]

    @property
    def constraint_ids(self) -> frozenset:
        return frozenset(c["id"] for c in self.constraints)


@dataclass(frozen=True)
class DriverResult:
    """The union of every pass, plus the evidence Agent 6 needs.

    ``TransformResult`` is the contract hand-off; this is the engine-level
    detail behind it. Keeping them separate means the contract object never has
    to carry a field invented to hold a diagnostic.
    """

    records: Tuple[QuadRecord, ...]
    passes: Tuple[PassResult, ...]
    binding_tree: Optional[BindingNode]
    diagnostics: Tuple[str, ...]

    @property
    def quads(self) -> Tuple[Quad, ...]:
        return tuple(r.quad for r in self.records)

    @property
    def ntriples(self) -> Tuple[str, ...]:
        return tuple(r.quad.to_ntriples() for r in self.records)

    def untraced_quads(self) -> Tuple[int, ...]:
        """Indices of quads not attributable to a target-schema constraint.

        This is the mechanical form of "the driver emits no triple of its own".
        A quad the host had constructed would have no constraint id, or an id
        the pass's target schema never declared.
        """
        declared = {p.pass_id: p.constraint_ids for p in self.passes}
        bad = []
        for i, rec in enumerate(self.records):
            if not rec.constraint_id or rec.constraint_id not in declared.get(
                rec.pass_id, frozenset()
            ):
                bad.append(i)
        return tuple(bad)

    def lineage(self) -> Tuple[QuadLineage, ...]:
        out = []
        for i, rec in enumerate(self.records):
            out.append(QuadLineage(
                quad_index=i,
                produced_by=f"{rec.pass_id}/{rec.kind}",
                source_variable=rec.variables[0] if rec.variables else None,
                source_constraint=rec.qualified_constraint,
                iteration_key=(rec.pass_id, f"frame:{rec.frame}")
                if rec.frame is not None else (),
            ))
        return tuple(out)

    def content_digest(self) -> str:
        """A digest of the graph, for ``RunRecord.output_digest``.

        Sorted N-Triples over the union. This is deterministic because the
        driver's blank node labels are: the engine's counter is deterministic
        (DR-301 probe 4a: byte-identical across runs, labels included) and the
        union's prefix is the pass id. It is deliberately *not* claimed to be
        isomorphism-invariant -- two structurally identical graphs built by
        different pass decompositions would digest differently, and pretending
        otherwise would misinform Gate 4.
        """
        joined = "\n".join(sorted(self.ntriples))
        return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# the driver
# --------------------------------------------------------------------------


def run_pass(
    spec: PassSpec,
    engine: Optional[EngineImage] = None,
    guards: Optional[Guards] = None,
) -> PassResult:
    """Run one pass and refuse every silent failure the spike found."""
    engine = engine or default_image()
    guards = guards or Guards()
    response = engine.run_pass(spec.to_bridge(guards))
    return interpret_pass(spec, response, guards)


def interpret_pass(
    spec: PassSpec, response: Mapping[str, Any], guards: Optional[Guards] = None
) -> PassResult:
    """Turn a bridge response into a :class:`PassResult`, or raise.

    Split out from :func:`run_pass` so the fail-fast rules can be tested
    against recorded engine responses without Docker -- the rules are the part
    that must not regress.
    """
    guards = guards or Guards()

    if not response.get("ok"):
        stage = response.get("stage", "?")
        if stage == "validate" and "validation" in response:
            raise SourceValidationFailure(
                spec.pass_id,
                "source graph does not conform to the source schema",
                response["validation"],
            )
        raise MaterializationFailure(
            spec.pass_id,
            f"engine failed at stage {stage}: {response.get('error', 'no message')}",
            response.get("report"),
        )

    # Absence of evidence is not evidence of absence. Every check below reads a
    # field of the response; if a field is missing, the check it guards would
    # silently not run and an empty response would read as a clean pass. For a
    # driver whose whole purpose is that the engine fails quietly, that is the
    # one defect worth being pedantic about.
    missing = [k for k in ("lastReport", "coverage", "constraints", "quads",
                           "provenance", "accepts")
               if response.get(k) is None]
    if missing:
        raise MaterializationFailure(
            spec.pass_id,
            f"the engine response is missing {missing}; the checks those fields "
            f"feed would not run, and a pass that skipped its checks is not a pass",
            {"keys": sorted(response)},
        )

    report = response["lastReport"]

    unbound = report.get("unboundVariables") or []
    if unbound:
        names = ", ".join(sorted({str(u.get("variable")) for u in unbound}))
        raise UnboundVariables(
            spec.pass_id,
            f"target schema references unbound variable(s) {names}. The engine "
            f"prunes the branches that need them and returns a PARTIAL graph "
            f"with exit 0 (DR-301 probe 8c)",
            unbound,
        )

    if report.get("explorationTruncated"):
        raise ExplorationTruncated(
            spec.pass_id,
            "the engine stopped searching before it was done; the graph may be "
            "missing repetitions. Raise Guards.explore_steps",
            report,
        )

    accepts = tuple(response["accepts"])
    if len(accepts) >= guards.max_accepts:
        raise AcceptCeilingReached(
            spec.pass_id,
            f"the accept ceiling ({guards.max_accepts}) was reached, so the "
            f"chosen materialization is the best of a truncated search. This is "
            f"DR-301 B2 -- the failure that silently emits 19 of 60 items. Raise "
            f"Guards.max_accepts above the repetition count",
            {"accepts": len(accepts)},
        )

    coverage = response["coverage"]
    if not coverage.get("chosenAvailable"):
        raise MaterializationFailure(
            spec.pass_id,
            "the engine reported no chosen materialization, so which bindings "
            "were consumed is unknown and coverage cannot be checked",
            coverage,
        )
    unconsumed = coverage.get("unconsumed") or []
    if unconsumed:
        raise BindingsNotConsumed(
            spec.pass_id,
            f"{len(unconsumed)} of {coverage.get('total')} source bindings were "
            f"never used by the target schema, so the mapping dropped data: "
            f"{unconsumed[:8]}",
            coverage,
        )

    quads = response["quads"]
    provenance = response["provenance"]
    if len(quads) != len(provenance):
        raise UntracedQuad(
            spec.pass_id,
            f"{len(quads)} quads but {len(provenance)} provenance entries; "
            f"lineage is not parallel to output and cannot be trusted",
        )

    constraints = tuple(response["constraints"])
    declared = {c["id"] for c in constraints}
    records: List[QuadRecord] = []
    for raw_quad, prov in zip(quads, provenance):
        constraint_id = prov.get("constraintId")
        if not constraint_id or constraint_id not in declared:
            raise UntracedQuad(
                spec.pass_id,
                f"a quad names constraint {constraint_id!r}, which the target "
                f"schema does not declare; the graph is not fully attributable",
                prov,
            )
        records.append(QuadRecord(
            quad=Quad.from_bridge(raw_quad),
            pass_id=spec.pass_id,
            constraint_id=constraint_id,
            predicate=prov.get("predicate", ""),
            kind=prov.get("kind", "binding"),
            variables=tuple(prov.get("variables") or ()),
            frame=prov.get("frame"),
        ))

    return PassResult(
        pass_id=spec.pass_id,
        records=tuple(records),
        binding_tree_raw=response.get("bindings"),
        frames=tuple(response.get("frames") or ()),
        frame_origins=tuple(response.get("frameOrigins") or ()),
        constraints=constraints,
        last_report=report,
        accepts=accepts,
        coverage=coverage,
        root=spec.root,
        scope_name=spec.scope_name,
        key_variables=tuple(spec.key_variables),
    )


def union_passes(passes: Sequence[PassResult]) -> DriverResult:
    """Union the passes, relabelling blank nodes, and check nothing else moved.

    Each pass restarts the engine's blank node counter at ``_:tm0``, so a naive
    concatenation merges unrelated nodes -- observed in DR-301 probe 10 before
    it was fixed. Relabelling is semantically a no-op (blank node labels are
    document-scoped) but it is the one place the host touches a term, so it is
    also the one place worth proving inert: the signature of every quad, with
    blank node labels masked out, must be unchanged by it.
    """
    if not passes:
        return DriverResult(records=(), passes=(), binding_tree=None, diagnostics=())

    pass_ids = [p.pass_id for p in passes]
    if len(set(pass_ids)) != len(pass_ids):
        raise ValueError(
            "pass ids must be unique; they namespace blank nodes in the union"
        )
    # The pass id becomes part of every blank node label, so an id with a space
    # in it produces `_:pass 1_tm0` -- unparseable N-Triples. Caught here, where
    # the message can name the pass id, rather than later per term.
    bad = [p for p in pass_ids if not _VALID_PASS_ID.match(p)]
    if bad:
        raise ValueError(
            f"pass id(s) {bad} cannot be used: they prefix blank node labels, so "
            f"they must be letters, digits, '_' or '-' only"
        )

    records: List[QuadRecord] = []
    for result in passes:
        for rec in result.records:
            moved = rec.quad.relabel_blank_nodes(result.pass_id)
            if shape_signature(moved) != shape_signature(rec.quad):
                raise UntracedQuad(
                    result.pass_id,
                    "blank node relabelling altered a quad beyond its labels; "
                    "refusing to emit a graph the driver may have changed",
                )
            records.append(QuadRecord(
                quad=moved,
                pass_id=rec.pass_id,
                constraint_id=rec.constraint_id,
                predicate=rec.predicate,
                kind=rec.kind,
                variables=rec.variables,
                frame=rec.frame,
            ))

    diagnostics: List[str] = []
    for result in passes:
        alternatives = (result.last_report or {}).get("alternatives", 0)
        if alternatives and alternatives > 1:
            diagnostics.append(
                f"pass {result.pass_id}: the engine found {alternatives} accepting "
                f"materializations and chose the one consuming the most bindings. "
                f"Inspect PassResult.accepts before trusting an ambiguous map"
            )
        unused = (result.last_report or {}).get("unusedStatics") or []
        if unused:
            diagnostics.append(
                f"pass {result.pass_id}: static variables never referenced: "
                f"{', '.join(sorted(unused))}"
            )

    return DriverResult(
        records=tuple(records),
        passes=tuple(passes),
        binding_tree=combined_binding_tree(passes),
        diagnostics=tuple(diagnostics),
    )


def combined_binding_tree(passes: Sequence[PassResult]) -> Optional[BindingNode]:
    """One binding tree spanning every pass.

    The acceptance tuples are read off ``TransformResult.binding_tree`` via
    ``tuples_for_scope``. Returning only the first pass's tree would hide every
    later pass's iterations from that check -- for a DR-302 decomposition, the
    skeleton's bindings would be all anyone could see, and the component tuples
    the acceptance matrix is written about would be unreachable.

    Later passes attach as children of the first pass's root. They are not
    nested under a particular iteration of it, because deciding which iteration
    a pass "belongs" to would be the host inferring structure; the pass's own
    subtree already carries its scope and iteration keys, which is what
    ``tuples_for_scope`` reads.
    """
    if not passes:
        return None
    trees = [binding_tree_of(p) for p in passes]
    root = trees[0]
    if root is None:
        return next((t for t in trees if t is not None), None)
    extra = tuple(t for t in trees[1:] if t is not None)
    return replace(root, children=root.children + extra) if extra else root


def materialize(
    specs: Sequence[PassSpec],
    engine: Optional[EngineImage] = None,
    guards: Optional[Guards] = None,
) -> DriverResult:
    """Run every pass in order and union the results."""
    return union_passes([run_pass(s, engine=engine, guards=guards) for s in specs])


# --------------------------------------------------------------------------
# binding tree
# --------------------------------------------------------------------------


def binding_tree_of(result: PassResult) -> Optional[BindingNode]:
    """Convert the engine's binding tree into the frozen contract shape.

    The engine's tree is untyped nested arrays and objects: an object is one
    frame of bindings, an array is a repetition. It carries no shape label and
    no iteration key, so those come from the :class:`PassSpec`. Under DR-302
    there is at most one repetition level, which is what makes the iteration
    key well defined -- the child's position *is* its iteration.
    """
    if result.binding_tree_raw is None:
        return None
    own, children = _split(result.binding_tree_raw)
    kids = []
    for index, child in enumerate(children):
        child_bindings, grandchildren = _split(child)
        kids.append(BindingNode(
            shape=result.scope_name or result.pass_id,
            focus=f"{result.root}#iteration-{index}",
            bindings=child_bindings,
            children=tuple(_nested(g, result, index) for g in grandchildren),
            scope=result.scope_name or result.pass_id,
            iteration_key=_iteration_key(child_bindings, result.key_variables, index),
        ))
    return BindingNode(
        shape=result.pass_id,
        focus=result.root,
        bindings=own,
        children=tuple(kids),
    )


def _nested(node, result: PassResult, parent_index: int) -> BindingNode:
    """A deeper repetition level. DR-302 forbids reaching this in a linted
    pair; it is handled rather than dropped so that an unlinted pair produces a
    visibly odd tree instead of a quietly truncated one."""
    bindings, children = _split(node)
    return BindingNode(
        shape=f"{result.pass_id}/nested",
        focus=f"{result.root}#iteration-{parent_index}-nested",
        bindings=bindings,
        children=tuple(_nested(c, result, parent_index) for c in children),
        scope=f"{result.scope_name or result.pass_id}/nested",
    )


def _split(node) -> Tuple[Dict[str, str], List[Any]]:
    """Separate a binding-tree node's own bindings from its repetitions.

    Sibling frames at one level are expected to bind disjoint variables. If two
    bind the same one, merging them would silently drop a value from the
    binding tree the acceptance tuples are read out of -- so it raises instead.
    """
    bindings: Dict[str, str] = {}
    children: List[Any] = []
    frames = [node] if isinstance(node, dict) else (
        [n for n in node if isinstance(n, dict)] if isinstance(node, list) else [])
    for frame in frames:
        for name, value in _values(frame).items():
            if name in bindings and bindings[name] != value:
                raise MaterializationFailure(
                    "binding-tree",
                    f"two sibling frames bind {name!r} differently "
                    f"({bindings[name]!r} and {value!r}); merging them would "
                    f"drop one, so the binding tree cannot be built",
                )
            bindings[name] = value
    if isinstance(node, list):
        lists = [item for item in node if isinstance(item, list)]
        if len(lists) > 1:
            # Two sibling repetition lists are two different scopes. Merging
            # them would present their iterations as iterations of one scope,
            # and tuples_for_scope would then report tuples that were never in
            # the source -- a manufactured cross-join, from the very code that
            # exists to make cross-joins detectable.
            raise MaterializationFailure(
                "binding-tree",
                f"{len(lists)} sibling repetition groups at one level; they are "
                f"separate scopes and merging them would invent tuples. Give "
                f"each its own pass (DR-302)",
            )
        for item in lists:
            children.extend(item)
    return bindings, children


def _values(frame: Mapping[str, Any]) -> Dict[str, str]:
    """Lexical values, which is what the acceptance tuples compare."""
    out: Dict[str, str] = {}
    for name, value in frame.items():
        if isinstance(value, dict):
            out[name] = str(value.get("value", ""))
        else:
            out[name] = str(value)
    return out


def _iteration_key(
    bindings: Mapping[str, str], key_variables: Sequence[str], index: int
) -> Tuple[str, ...]:
    """Identify one iteration of a repetition scope.

    ``RepetitionScope`` requires key variables so that "a cross-join is
    detectable rather than merely unlikely". A key variable the iteration does
    not bind would give every iteration the same empty key and quietly undo
    that, so it is an error: it means the PassSpec names variables this schema
    pair does not produce.
    """
    if not key_variables:
        return (str(index),)
    missing = [v for v in key_variables if v not in bindings]
    if missing:
        raise MaterializationFailure(
            "binding-tree",
            f"iteration {index} binds none of the declared key variable(s) "
            f"{missing}; without them iterations cannot be told apart and a "
            f"cross-join would be undetectable",
        )
    return tuple(bindings[v] for v in key_variables)


# --------------------------------------------------------------------------
# contract hand-off
# --------------------------------------------------------------------------


def to_transform_result(
    result: DriverResult,
    map_id: str,
    pairing_hash: str,
    source_canonical_url: str,
    source_version_id: str,
    output_graph_key: str,
    target_root: Optional[str] = None,
    extra_diagnostics: Sequence[str] = (),
) -> TransformResult:
    """Populate the frozen :class:`TransformResult`.

    ``TransformResult`` refuses a ``MAPPED`` result whose quads are not all
    covered by lineage, so the lineage built here is not decoration -- the
    constructor will not accept the object without it. That is the intended
    coupling: an untraceable quad cannot reach a clinical graph.

    ``binding_alternatives`` is left empty on purpose. The engine reports
    alternative *materializations*, not alternative binding trees; synthesising
    BindingNodes for them would invent structure the engine never produced. The
    count and the per-accept statistics are surfaced in ``diagnostics`` and on
    :class:`PassResult` instead.
    """
    untraced = result.untraced_quads()
    if untraced:
        raise UntracedQuad(
            "union",
            f"quads at {untraced} have no target-schema constraint behind them",
        )
    return TransformResult(
        status=TransformStatus.MAPPED,
        map_id=map_id,
        pairing_hash=pairing_hash,
        source_canonical_url=source_canonical_url,
        source_version_id=source_version_id,
        output_graph_key=output_graph_key,
        target_quads=result.ntriples,
        target_root=target_root or (result.passes[0].root if result.passes else None),
        binding_tree=result.binding_tree,
        lineage=result.lineage(),
        binding_alternatives=(),
        diagnostics=tuple(result.diagnostics) + tuple(extra_diagnostics),
    )


def graph_key(*args, **kwargs) -> str:
    """Removed. There is one graph key, and it is the store's.

    This used to hash four identity fields. The store's key
    (``fhir_sulo.store.graph_key``, DR-601) hashes thirteen, and the store
    **refuses** a run record whose key does not recompute from the record's own
    fields -- which is what makes an archived correction verifiable. Two
    functions with the same name and different semantics is how someone ships a
    graph whose key does not mean what the store thinks it means, so the weaker
    one is gone rather than deprecated.

    Build ``fhir_sulo.provenance.run_records.RunInputs`` and read
    ``.graph_key``; the pipeline does this for you.
    """
    raise NotImplementedError(
        "engine.driver.graph_key has been removed: use "
        "fhir_sulo.provenance.run_records.RunInputs(...).graph_key, which is "
        "the 13-input key the store verifies (DR-601). See DR-305."
    )


def ineligible_result(
    status: TransformStatus,
    map_id: str,
    pairing_hash: str,
    source_canonical_url: str,
    source_version_id: str,
    reason: str,
    output_graph_key: str,
) -> TransformResult:
    """A result for a source the mapping must not be run against at all.

    ``TransformResult`` refuses target quads on ``source-only`` and
    ``rejected``, so this exists to make the right thing the easy thing: the
    driver is never invoked, rather than invoked and then stripped.
    """
    if status is TransformStatus.MAPPED:
        raise ValueError("ineligible_result is for source-only or rejected outcomes")
    return TransformResult(
        status=status,
        map_id=map_id,
        pairing_hash=pairing_hash,
        source_canonical_url=source_canonical_url,
        source_version_id=source_version_id,
        output_graph_key=output_graph_key,
        rejection_reason=reason if status is TransformStatus.REJECTED else None,
        diagnostics=(reason,),
    )
