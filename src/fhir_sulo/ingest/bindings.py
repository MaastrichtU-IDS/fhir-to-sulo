"""Expected pivot bindings: the format, the loader, and the extractor.

The artifact
------------
Every fixture directory carries ``expected-bindings.json``. It is the thing
Agent 3's maps and Agent 4's engine are tested against, so it is written to be
*checkable today*, against the rendered RDF, rather than merely declared.

It has three parts:

``binding_tree``
    A serialisation of :class:`fhir_sulo.contracts.BindingNode`. Load it with
    :func:`load_binding_tree` and the acceptance test is a direct
    ``tree.tuples_for_scope(scope, vars)`` multiset comparison - the same call
    ``tests/contracts/test_interfaces.py`` demonstrates.

``assertions.scope_tuples``
    Per repetition scope: the variable order, the ``expected_multiset``, and
    ``must_not_contain``. The BP entry carries the required answer
    ``{(bp-1,120,80),(bp-2,105,70)}`` in ``expected_multiset`` and the
    cross-join ``(bp-1,120,70)`` / ``(bp-2,105,80)`` in ``must_not_contain``,
    so a test that only checked "every value appears somewhere" fails.

``extraction``
    A declarative path spec that recovers the same tuples *from the rendered
    FHIR RDF*. This is what stops the expected tuples from being an unchecked
    assertion: :func:`extract` runs the spec over the committed canonical
    N-Triples and the test requires the two to agree.

Extraction language (deliberately tiny, no engine, no SPARQL dependency)
------------------------------------------------------------------------
``iterate``
    ``{"kind": "tree_roots", "type": "Observation"}`` - one iteration per
    resource whose node is a ``fhir:treeRoot`` of that type, ordered by the
    iteration key so the multiset is stable.
    ``{"kind": "self"}`` - exactly one iteration, the single tree root.
``vars``
    ``{"<name>": {"steps": [...], "optional": bool, "datatype": bool}}``.
    A step is either ``{"p": "<predicate local name>"}``, traversing
    ``fhir:<local name>``, or ``{"filter": {"steps": [...], "equals": "..."}}``,
    keeping only the current nodes whose sub-path yields that value.
    A variable must resolve to exactly one term unless ``optional`` is set, in
    which case zero terms bind the empty string - the same convention
    ``BindingNode.tuples_for_scope`` uses for a missing variable, so an omitted
    BP component shows up as a tuple with a hole rather than silently pairing
    with the neighbouring panel's value.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..contracts import BindingNode
from .manifest import Manifest, default_manifest
from .ntriples import BNode, Graph, IRI, Literal, Triple

FORMAT_ID = "fhir-sulo/expected-bindings/0.1.0"

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


class BindingSpecError(ValueError):
    pass


# ---------------------------------------------------------------------------
# The artifact
# ---------------------------------------------------------------------------

def load(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    fmt = doc.get("format")
    if fmt != FORMAT_ID:
        raise BindingSpecError(f"{path}: format {fmt!r} != {FORMAT_ID!r}")
    for key in ("fixture_id", "binding_tree", "assertions"):
        if key not in doc:
            raise BindingSpecError(f"{path}: missing {key!r}")
    return doc


def load_binding_tree(doc: Dict[str, Any]) -> BindingNode:
    return _node(doc["binding_tree"])


def _node(d: Dict[str, Any]) -> BindingNode:
    return BindingNode(
        shape=d["shape"],
        focus=d["focus"],
        bindings=dict(d.get("bindings", {})),
        children=tuple(_node(c) for c in d.get("children", ())),
        scope=d.get("scope"),
        iteration_key=tuple(d.get("iteration_key", ())),
    )


def scope_assertions(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(doc["assertions"].get("scope_tuples", ()))


def expected_multiset(assertion: Dict[str, Any]) -> List[Tuple[str, ...]]:
    return sorted(tuple(t) for t in assertion["expected_multiset"])


def forbidden_multiset(assertion: Dict[str, Any]) -> List[Tuple[str, ...]]:
    return sorted(tuple(t) for t in assertion.get("must_not_contain", ()))


# ---------------------------------------------------------------------------
# Extraction from rendered RDF
# ---------------------------------------------------------------------------

def extract(doc: Dict[str, Any], triples: Sequence[Triple],
            manifest: Optional[Manifest] = None) -> Dict[str, List[Dict[str, str]]]:
    """Run the fixture's ``extraction`` spec over a rendered graph.

    Returns ``{scope_name: [ {var: value}, ... ]}``, ordered by iteration key.
    """
    m = manifest or default_manifest()
    spec = doc.get("extraction")
    if not spec:
        raise BindingSpecError(f"{doc['fixture_id']}: no extraction spec")
    g = Graph(triples)
    fhir = m.fhir_base
    out: Dict[str, List[Dict[str, str]]] = {}
    for scope in spec["scopes"]:
        rows = []
        for focus in _iterate(g, fhir, scope["iterate"]):
            row = {}
            for name, vspec in scope["vars"].items():
                row[name] = _bind(g, fhir, focus, name, vspec)
            rows.append(row)
        key_vars = scope.get("key_variables") or list(scope["vars"])[:1]
        rows.sort(key=lambda r: tuple(r.get(k, "") for k in key_vars))
        out[scope["name"]] = rows
    return out


def _iterate(g: Graph, fhir: str, spec: Dict[str, Any]) -> List[Any]:
    kind = spec.get("kind")
    roots = [s for s in g.subjects_with(fhir + "nodeRole", IRI(fhir + "treeRoot"))]
    if kind == "self":
        if len(roots) != 1:
            raise BindingSpecError(f"iterate 'self' needs exactly one tree root, found {len(roots)}")
        return roots
    if kind == "tree_roots":
        want = spec.get("type")
        if want:
            roots = [r for r in roots
                     if IRI(fhir + want) in g.objects(r, RDF_TYPE)]
        return sorted(roots, key=lambda t: getattr(t, "value", getattr(t, "label", "")))
    raise BindingSpecError(f"unknown iterate kind {kind!r}")


def _bind(g: Graph, fhir: str, focus, name: str, vspec: Dict[str, Any]) -> str:
    terms = _walk(g, fhir, [focus], vspec["steps"], name)
    if not terms:
        if vspec.get("optional"):
            return ""
        raise BindingSpecError(f"variable {name!r} bound nothing and is not optional")
    if len(terms) > 1:
        raise BindingSpecError(
            f"variable {name!r} bound {len(terms)} terms; a pivot variable that binds "
            "more than once inside its scope would hide a cross-join"
        )
    return _render_term(terms[0], with_datatype=bool(vspec.get("datatype")))


def _walk(g: Graph, fhir: str, nodes: List[Any], steps: Sequence[Dict[str, Any]],
          name: str) -> List[Any]:
    current = list(nodes)
    for step in steps:
        if "p" in step:
            nxt = []
            for n in current:
                nxt.extend(g.objects(n, fhir + step["p"]))
            current = nxt
        elif "filter" in step:
            f = step["filter"]
            kept = []
            for n in current:
                got = _walk(g, fhir, [n], f["steps"], name)
                if any(_render_term(t, False) == f["equals"] for t in got):
                    kept.append(n)
            current = kept
        else:
            raise BindingSpecError(f"variable {name!r}: unknown step {step!r}")
    return current


def _render_term(term, with_datatype: bool) -> str:
    if isinstance(term, Literal):
        if with_datatype and term.datatype:
            return f"{term.lexical}^^{term.datatype}"
        return term.lexical
    if isinstance(term, IRI):
        return term.value
    if isinstance(term, BNode):
        return "_:" + term.label
    raise TypeError(type(term))  # pragma: no cover
