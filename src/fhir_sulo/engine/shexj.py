"""Read a ShExJ schema: indexes, shape-reference resolution, path walking.

The linter analyses ShExJ, never ShExC. Parsing is delegated to the pinned
engine's own parser (``tools/engine/bridge/parse.js``) so that the linter and
the engine cannot disagree about what a schema says -- a disagreement would be
the worst possible bug in a tool whose job is to predict engine behaviour.

Everything here is pure: given a ShExJ dict it needs no Docker, which is what
lets the linter's own tests run in CI without one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

SHAPE_EXPR_TYPES = frozenset({"Shape", "ShapeAnd", "ShapeOr", "ShapeNot", "NodeConstraint"})
TRIPLE_EXPR_TYPES = frozenset({"EachOf", "OneOf", "TripleConstraint"})

#: ShExJ spells "unbounded" as -1.
UNBOUNDED = -1


def cardinality(node: Mapping[str, Any]) -> Tuple[int, int]:
    """``(min, max)`` with ShExJ's defaults applied. ``max`` may be ``UNBOUNDED``."""
    return int(node.get("min", 1)), int(node.get("max", 1))


def is_repeating(node: Mapping[str, Any]) -> bool:
    """Whether this constraint or group can match more than once.

    ``min`` is irrelevant: ``?`` and ``{0,1}`` are optional, not repeating, and
    it is repetition -- not optionality -- that DR-302 limits.
    """
    _, mx = cardinality(node)
    return mx == UNBOUNDED or mx > 1


@dataclass
class Schema:
    """An indexed ShExJ schema plus the prefix table its Map codes need."""

    raw: Mapping[str, Any]
    prefixes: Mapping[str, str] = field(default_factory=dict)
    label: str = "schema"

    shape_exprs: Dict[str, Any] = field(init=False, default_factory=dict)
    triple_exprs: Dict[str, Any] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        for decl in self.raw.get("shapes", []) or []:
            ident = decl.get("id")
            if ident:
                self.shape_exprs[ident] = decl.get("shapeExpr", decl) if decl.get(
                    "type") == "ShapeDecl" else decl
        for node in _walk_dicts(self.raw):
            if node.get("type") in TRIPLE_EXPR_TYPES and node.get("id"):
                self.triple_exprs[node["id"]] = node

    # -- resolution ---------------------------------------------------------

    @property
    def start(self) -> Optional[Any]:
        return self.raw.get("start")

    def resolve_shape(self, expr: Any, _hops: int = 0) -> Optional[Mapping[str, Any]]:
        """Follow shape-label references to the shape expression itself.

        Returns ``None`` for a dangling reference; the caller reports it. The
        hop limit mirrors the engine's own loop guard rather than trusting the
        schema to be acyclic at the *declaration* level.
        """
        while isinstance(expr, str):
            if _hops > 100:
                return None
            expr = self.shape_exprs.get(expr)
            if expr is None:
                return None
            if isinstance(expr, dict) and expr.get("type") == "ShapeDecl":
                expr = expr.get("shapeExpr")
            _hops += 1
        return expr if isinstance(expr, dict) else None

    def resolve_triple_expr(self, expr: Any) -> Optional[Mapping[str, Any]]:
        if isinstance(expr, str):
            return self.triple_exprs.get(expr)
        return expr if isinstance(expr, dict) else None

    def shape_label_of(self, expr: Any) -> Optional[str]:
        return expr if isinstance(expr, str) else (expr or {}).get("id")

    # -- traversal ----------------------------------------------------------

    def triple_constraints(self) -> Iterator[Mapping[str, Any]]:
        """Every TripleConstraint in the document, regardless of reachability."""
        for node in _walk_dicts(self.raw):
            if node.get("type") == "TripleConstraint":
                yield node

    def sub_shapes(self, shape_expr: Any) -> List[Any]:
        """The Shape components of a shape expression.

        ``ShapeAnd``/``ShapeOr`` are unwrapped because the materializer
        composes them at the NFA level; ``NodeConstraint`` conjuncts restrict
        the focus node rather than its arcs and contribute no triples, so they
        are skipped here as they are there.
        """
        expr = self.resolve_shape(shape_expr)
        if expr is None:
            return []
        kind = expr.get("type")
        if kind == "Shape":
            return [expr]
        if kind in ("ShapeAnd", "ShapeOr"):
            out: List[Any] = []
            for part in expr.get("shapeExprs", []):
                out.extend(self.sub_shapes(part))
            return out
        return []  # NodeConstraint, ShapeNot: no arcs of their own


def _walk_dicts(node: Any) -> Iterator[Mapping[str, Any]]:
    """Every dict in a ShExJ tree, skipping parser-private ``_`` keys."""
    if isinstance(node, dict):
        yield node
        for key, value in node.items():
            if not key.startswith("_"):
                yield from _walk_dicts(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_dicts(item)


@dataclass(frozen=True)
class PathStep:
    """One arc on a path from the start shape to a constraint.

    ``repeat_depth`` is how many *nested* repetitions this one arc introduces,
    not a flag. A triple constraint contributes one if its own cardinality
    repeats, plus one for each enclosing ``EachOf``/``OneOf`` group that
    repeats. ``(:x .*)*`` is two levels of repetition on a single arc -- the
    group iterates and the constraint iterates within each iteration -- and
    counting it as one would let exactly the schema DR-302 forbids through the
    gate.
    """

    shape: Optional[str]
    predicate: str
    repeat_depth: int = 0
    #: repetition from the constraint's own cardinality, for rendering
    self_repeating: bool = False

    @property
    def repeating(self) -> bool:
        return self.repeat_depth > 0

    def __str__(self) -> str:
        if self.repeat_depth == 0:
            return self.predicate
        if self.self_repeating and self.repeat_depth == 1:
            return self.predicate + "*"
        groups = self.repeat_depth - (1 if self.self_repeating else 0)
        mark = "*" if self.self_repeating else ""
        return f"{self.predicate}{mark}(in {groups} repeating group(s))"


@dataclass(frozen=True)
class ConstraintPath:
    """A reachable TripleConstraint and how the walk arrived at it."""

    constraint: Mapping[str, Any]
    steps: Tuple[PathStep, ...]

    @property
    def repetition_count(self) -> int:
        return sum(s.repeat_depth for s in self.steps)

    @property
    def repeating_steps(self) -> Tuple[PathStep, ...]:
        return tuple(s for s in self.steps if s.repeat_depth)

    def render(self) -> str:
        return " / ".join(str(s) for s in self.steps) or "(start)"


@dataclass(frozen=True)
class Cycle:
    """A shape-reference cycle found while walking."""

    shapes: Tuple[str, ...]

    def render(self) -> str:
        return " -> ".join(self.shapes)


class SchemaTooLarge(RuntimeError):
    """The path walk exceeded its budget.

    Shape references form a DAG, so a schema where many shapes reference the
    same few sub-shapes has exponentially many *paths* through a linear number
    of shapes. A build gate must not hang on one, and must not quietly analyse
    a prefix either, so the walk raises and the linter turns it into an error.
    """


#: Shape references form a DAG, so paths can be exponential in the shape count.
#: Any pilot schema is orders of magnitude below this.
MAX_PATHS = 20000


def walk_paths(
    schema: Schema,
    start: Optional[Any] = None,
    max_depth: int = 64,
    max_paths: int = MAX_PATHS,
) -> Tuple[List[ConstraintPath], List[Cycle], List[str]]:
    """Enumerate every path from ``start`` to a reachable TripleConstraint.

    Returns ``(paths, cycles, dangling_references)``. A cycle terminates the
    branch that closed it and is reported rather than unrolled, so this always
    terminates; ``max_paths`` bounds breadth as ``max_depth`` bounds depth, and
    exceeding it raises :class:`SchemaTooLarge` rather than returning a partial
    answer a build gate would read as a pass. ``dangling_references`` names
    shape labels the schema uses but does not declare -- which the engine turns
    into a runtime ``shape ... not found`` rather than a parse error.
    """
    paths: List[ConstraintPath] = []
    cycles: List[Cycle] = []
    dangling: List[str] = []
    start = schema.start if start is None else start
    if start is None:
        return paths, cycles, dangling

    def descend(shape_expr: Any, steps: Tuple[PathStep, ...], stack: Tuple[str, ...]) -> None:
        label = schema.shape_label_of(shape_expr)
        if label is not None and label in stack:
            # the cycle is the suffix of the stack from where the label first
            # appeared, closed back onto it
            cycles.append(Cycle(shapes=stack[stack.index(label):] + (label,)))
            return
        if len(steps) >= max_depth:
            return
        resolved = schema.resolve_shape(shape_expr)
        if resolved is None:
            if isinstance(shape_expr, str):
                dangling.append(shape_expr)
            return
        next_stack = stack + (label,) if label is not None else stack
        for shape in schema.sub_shapes(shape_expr):
            expression = shape.get("expression")
            if expression is not None:
                visit_expr(expression, label, steps, next_stack, group_repeats=0)

    def visit_expr(
        expr: Any,
        shape_label: Optional[str],
        steps: Tuple[PathStep, ...],
        stack: Tuple[str, ...],
        group_repeats: int,
    ) -> None:
        node = schema.resolve_triple_expr(expr)
        if node is None:
            return
        kind = node.get("type")
        if kind in ("EachOf", "OneOf"):
            # each enclosing repeating group is its own level of nesting
            inner = group_repeats + (1 if is_repeating(node) else 0)
            for sub in node.get("expressions", []):
                visit_expr(sub, shape_label, steps, stack, inner)
            return
        if kind != "TripleConstraint":
            return
        self_repeating = is_repeating(node)
        step = PathStep(
            shape=shape_label,
            predicate=node.get("predicate", "?"),
            repeat_depth=group_repeats + (1 if self_repeating else 0),
            self_repeating=self_repeating,
        )
        here = steps + (step,)
        if len(paths) >= max_paths:
            raise SchemaTooLarge(
                f"more than {max_paths} paths from the start shape; refusing to "
                f"report a partial analysis of {schema.label}"
            )
        paths.append(ConstraintPath(constraint=node, steps=here))
        value_expr = node.get("valueExpr")
        if value_expr is not None and _is_shape_valued(schema, value_expr):
            descend(value_expr, here, stack)

    descend(start, (), ())
    return paths, cycles, dangling


def _is_shape_valued(schema: Schema, value_expr: Any) -> bool:
    """Whether a constraint's value is a shape (so the walk descends into it)."""
    resolved = schema.resolve_shape(value_expr)
    if resolved is None:
        # A dangling label is still shape-valued in intent; descend so the
        # reference gets reported rather than silently ignored.
        return isinstance(value_expr, str)
    return resolved.get("type") in ("Shape", "ShapeAnd", "ShapeOr")


def map_codes_of(constraint: Mapping[str, Any]) -> Tuple[str, ...]:
    """The raw bodies of this constraint's ``%Map:{ ... %}`` annotations."""
    from .mapcode import MAP_EXTENSION_IRI

    return tuple(
        act.get("code", "")
        for act in constraint.get("semActs", []) or []
        if act.get("name") == MAP_EXTENSION_IRI
    )


def prefix_table(parse_response: Mapping[str, Any]) -> Dict[str, str]:
    """Prefixes from a ``parse.js`` response, tolerating an absent table."""
    return dict(parse_response.get("prefixes") or {})


def load(parse_response: Mapping[str, Any], label: str) -> Schema:
    """Build a :class:`Schema` from a ``parse.js`` response."""
    return Schema(
        raw=parse_response["schema"],
        prefixes=prefix_table(parse_response),
        label=label,
    )


def shape_expr_labels(schema: Schema) -> Sequence[str]:
    return sorted(schema.shape_exprs)
