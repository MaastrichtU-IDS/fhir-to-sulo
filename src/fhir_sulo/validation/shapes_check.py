"""Target shape validation with SHACL.

Choice: SHACL, via pySHACL, pinned
=================================
ShEx and SHACL were both candidates. SHACL was chosen for three reasons, in
order of weight:

1. **It is an independent second opinion.** The target *ShEx* schema is Agent
   3's artefact - it is the thing that constructs the graph. Validating the
   output against that same schema would be a check that structurally cannot
   fail: it re-asks the question the materializer already answered yes to.
   (Bidirectional pivot recovery against the ShEx target *is* worth doing, and
   DR-301 probe 6 shows the engine supports it; that is Agent 4's "Pivot
   reversibility" row, not this one.) A shape written here, from the concept
   note's example graphs and DR-002's axioms, can disagree with the map - which
   is the entire point of a validation layer.
2. **The negative rows need SPARQL.** "No orphan result", "no cross-patient
   result" and "no ``hasPatient`` predicate" are graph-wide non-existence
   claims. SHACL-SPARQL states them directly; ShEx has no comparable
   construct, and expressing them as shape-negations would be indirect enough
   to be hard to review.
3. **No JVM, and the pin is exact.** pySHACL is pure Python. The acceptance
   row "Deployability" forbids introducing a JVM dependency *for the mapping
   stack*, and shape validation sits right beside it.

Pinned: ``pyshacl==0.26.0`` with ``rdflib==7.1.1`` (``requirements-runtime.txt``).

Validated against the **asserted** graph, before reasoning. On a reasoned
graph ``sh:targetClass sulo:Quantity`` would also select every ``sulo:Unit``
and every ``sulo:TimeInstant``, because SULO makes both subclasses of
``Quantity`` - so the constraints would be checking something other than what
they say. Entailments are the reasoner's job; see ``reasoning.py``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..store.canonical import digest
from .strictness import CONCEPT_NOTE_LITERAL, Strictness

__all__ = [
    "SHAPES_DIR",
    "ShapeViolation",
    "ShapeReport",
    "MissingDependencyError",
    "load_shapes_graph",
    "validate_graph",
]

SHAPES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shapes")


class MissingDependencyError(RuntimeError):
    """pySHACL or rdflib is not installed in this interpreter."""


@dataclass(frozen=True)
class ShapeViolation:
    focus_node: str
    source_shape: str
    path: Optional[str]
    message: str
    severity: str
    value: Optional[str] = None

    def __str__(self) -> str:
        where = " %s" % self.path if self.path else ""
        return "%s <%s>%s: %s" % (self.severity, self.focus_node, where, self.message)


@dataclass(frozen=True)
class ShapeReport:
    conforms: bool
    strictness_label: str
    violations: Tuple[ShapeViolation, ...] = ()
    shape_modules: Tuple[str, ...] = ()
    text: str = ""

    @property
    def digest(self) -> str:
        """Stable digest, for ``RunRecord.validation_report_digest``.

        Hashes the findings, not the prose: pySHACL's text output includes
        blank-node labels that vary between runs, and a validation digest that
        changed for that reason would make "identical graph hashes from a clean
        deployment" impossible to demonstrate.
        """
        return digest(
            {
                "conforms": self.conforms,
                "strictness": self.strictness_label,
                "modules": list(self.shape_modules),
                "violations": sorted(
                    [v.source_shape, v.focus_node, v.path or "", v.message, v.severity]
                    for v in self.violations
                ),
            }
        )

    def summary(self) -> str:
        if self.conforms:
            return "conforms (%s, %d shape modules)" % (
                self.strictness_label, len(self.shape_modules)
            )
        return "%d violation(s) under %s" % (len(self.violations), self.strictness_label)


def _require_rdflib():
    try:
        import rdflib  # noqa: F401
    except ImportError as exc:  # pragma: no cover - environment guard
        raise MissingDependencyError(
            "rdflib is not installed. Create the pinned environment:\n"
            "    python3 -m venv .venv\n"
            "    .venv/bin/pip install -r requirements-runtime.txt"
        ) from exc
    return rdflib


def load_shapes_graph(strictness: Strictness = CONCEPT_NOTE_LITERAL):
    """Merge the base shapes with whichever R5 modules the switch enables."""
    rdflib = _require_rdflib()
    graph = rdflib.Graph()
    for module in strictness.modules():
        path = os.path.join(SHAPES_DIR, module)
        if not os.path.exists(path):
            raise FileNotFoundError("shape module not found: %s" % path)
        graph.parse(path, format="turtle")
    return graph


def _as_graph(data):
    """Accept an rdflib Graph, a Turtle/N-Triples string, or a sequence of quads."""
    rdflib = _require_rdflib()
    if isinstance(data, rdflib.Graph):
        return data
    graph = rdflib.Graph()
    if isinstance(data, str):
        text = data
        fmt = "turtle" if ("@prefix" in text or "PREFIX" in text) else "nt"
        graph.parse(data=text, format=fmt)
        return graph
    if isinstance(data, (list, tuple)):
        graph.parse(data="\n".join(str(line) for line in data), format="nt")
        return graph
    raise TypeError("cannot read a graph from %s" % type(data).__name__)


def validate_graph(
    data,
    strictness: Strictness = CONCEPT_NOTE_LITERAL,
    *,
    shapes_graph=None,
) -> ShapeReport:
    """Validate a materialized target graph against the SULO shape contract."""
    try:
        from pyshacl import validate as pyshacl_validate
    except ImportError as exc:  # pragma: no cover - environment guard
        raise MissingDependencyError(
            "pyshacl is not installed. Create the pinned environment:\n"
            "    python3 -m venv .venv\n"
            "    .venv/bin/pip install -r requirements-runtime.txt"
        ) from exc

    rdflib = _require_rdflib()
    data_graph = _as_graph(data)
    shapes = shapes_graph if shapes_graph is not None else load_shapes_graph(strictness)

    conforms, results_graph, text = pyshacl_validate(
        data_graph,
        shacl_graph=shapes,
        # No inference here on purpose: see the module docstring. Reasoning is
        # a separate, separately reported layer.
        inference="none",
        advanced=True,       # SHACL-SPARQL, needed by the negative constraints
        abort_on_first=False,
        meta_shacl=False,
        debug=False,
    )

    SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
    violations: List[ShapeViolation] = []
    for result in results_graph.subjects(rdflib.RDF.type, SH.ValidationResult):
        def one(predicate):
            value = results_graph.value(result, predicate)
            return None if value is None else str(value)

        violations.append(
            ShapeViolation(
                focus_node=one(SH.focusNode) or "?",
                source_shape=one(SH.sourceShape) or "?",
                path=one(SH.resultPath),
                message=one(SH.resultMessage) or "(no message)",
                severity=(one(SH.resultSeverity) or "").rsplit("#", 1)[-1] or "Violation",
                value=one(SH.value),
            )
        )

    return ShapeReport(
        conforms=bool(conforms),
        strictness_label=strictness.label,
        violations=tuple(sorted(violations, key=lambda v: (v.focus_node, v.message))),
        shape_modules=strictness.modules(),
        text=text,
    )
