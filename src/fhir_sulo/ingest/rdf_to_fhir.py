"""FHIR RDF -> FHIR JSON. The inverse half of the round-trip test.

This module deliberately does NOT share a code path with the renderer beyond
the pinned element table. It walks a *parsed* graph (from committed N-Triples
text, via the dependency-free reader in ``ntriples.py``) and rebuilds the JSON
object. If the two agreed by construction the round-trip test could not fail,
which plan section 2 explicitly requires it to be able to do.

What the round trip is claimed to preserve, exactly:

* every element in the pinned subset, with its JSON structure and array order;
* the *lexical form* of every number (``55.0`` stays ``55.0``);
* the temporal precision of every date/dateTime/instant, because the xsd
  datatype is derived from and checked against the lexical form;
* codes, code systems, comparators, units and statuses, because they are
  ordinary string-valued elements and are compared verbatim.

What it does not claim: reconstruction of ``fhir:index``, ``fhir:link``,
``fhir:nodeRole`` or the reference stub types. Those are derived, not source;
they are re-derived on the next render and checked separately.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .jsonio import FhirNumber
from .manifest import Manifest, ManifestError, default_manifest
from .ntriples import BNode, Graph, IRI, Literal, Triple

XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


class InverseError(ValueError):
    pass


class FhirRdfReader:
    def __init__(self, manifest: Optional[Manifest] = None):
        self.m = manifest or default_manifest()
        self.fhir = self.m.fhir_base
        # predicate IRI -> (type_name, element_name, element_def), built once.
        self._index: Dict[str, List[Tuple[str, str, Dict[str, Any]]]] = {}
        for type_name, tdef in self.m.elements["types"].items():
            for elem_name, ed in tdef["elements"].items():
                self._index.setdefault(self.fhir + ed["predicate"], []).append(
                    (type_name, elem_name, ed)
                )

    # -- public -------------------------------------------------------------

    def to_json(self, triples, root=None) -> Dict[str, Any]:
        g = Graph(triples)
        if root is None:
            roots = g.subjects_with(self.fhir + "nodeRole", IRI(self.fhir + "treeRoot"))
            if len(roots) != 1:
                raise InverseError(
                    f"expected exactly one fhir:treeRoot, found {len(roots)}; "
                    "pass root= explicitly"
                )
            root = roots[0]
        rtype = self._resource_type(g, root)
        out: Dict[str, Any] = {"resourceType": rtype}
        out.update(self._read_object(g, root, rtype, rtype))
        return out

    # -- internals ----------------------------------------------------------

    def _resource_type(self, g: Graph, node) -> str:
        for obj in g.objects(node, RDF_TYPE):
            if isinstance(obj, IRI) and obj.value.startswith(self.fhir):
                name = obj.value[len(self.fhir):]
                if self.m.has_type(name) and self.m.type_kind(name) == "resource":
                    return name
        raise InverseError(f"{node}: no fhir: resource type found")

    def _read_object(self, g: Graph, node, type_name: str, path: str) -> Dict[str, Any]:
        elements = self.m.elements["types"][type_name]["elements"]
        by_predicate = {self.fhir + ed["predicate"]: (name, ed)
                        for name, ed in elements.items()}

        # Group objects by element, preserving the order fhir:index records.
        grouped: Dict[str, List[Any]] = {}
        for pred, obj in g.po(node):
            p = pred.value
            if p == RDF_TYPE or p in (self.fhir + "nodeRole", self.fhir + "index",
                                      self.fhir + "link", self.fhir + "value"):
                continue
            if p not in by_predicate:
                raise InverseError(
                    f"{path}: predicate <{p}> is not an element of {type_name} in the "
                    "pinned element table"
                )
            grouped.setdefault(p, []).append(obj)

        out: Dict[str, Any] = {}
        # Emit in element-table order so the result is deterministic; the
        # comparison in jsonio.diff ignores object key order anyway.
        for pred, (elem_name, ed) in by_predicate.items():
            if pred not in grouped:
                continue
            objs = grouped[pred]
            child_path = f"{path}.{elem_name}"
            if ed.get("repeats"):
                ordered = self._order_by_index(g, objs, child_path)
                out[elem_name] = [
                    self._read_value(g, o, ed, f"{child_path}[{i}]")
                    for i, o in enumerate(ordered)
                ]
            else:
                if len(objs) != 1:
                    raise InverseError(f"{child_path}: {len(objs)} values for a 0..1 element")
                out[elem_name] = self._read_value(g, objs[0], ed, child_path)
        return out

    def _order_by_index(self, g: Graph, objs: List[Any], path: str) -> List[Any]:
        keyed = []
        for o in objs:
            if isinstance(o, Literal):
                raise InverseError(f"{path}: repeating element with a bare literal object")
            idx = g.one(o, self.fhir + "index")
            if idx is None:
                raise InverseError(f"{path}: repeating element node has no fhir:index")
            keyed.append((int(idx.lexical), o))
        positions = sorted(k for k, _ in keyed)
        if positions != list(range(len(positions))):
            raise InverseError(f"{path}: fhir:index values {positions} are not 0..n-1")
        keyed.sort(key=lambda kv: kv[0])
        return [o for _, o in keyed]

    def _read_value(self, g: Graph, obj, ed: Dict[str, Any], path: str) -> Any:
        ftype = ed["type"]

        if ed.get("raw_literal"):
            if not isinstance(obj, Literal):
                raise InverseError(f"{path}: expected a direct literal")
            return obj.lexical

        if ftype == "#resource":
            ctype = self._resource_type(g, obj)
            out: Dict[str, Any] = {"resourceType": ctype}
            out.update(self._read_object(g, obj, ctype, path))
            return out

        if self.m.is_primitive(ftype):
            value_lit = g.one(obj, self.fhir + "value")
            if value_lit is None:
                raise InverseError(f"{path}: primitive node has no fhir:value")
            if not isinstance(value_lit, Literal):
                raise InverseError(f"{path}: fhir:value is not a literal")
            return self._decode_primitive(value_lit, ftype, path)

        return self._read_object(g, obj, ftype, path)

    def _decode_primitive(self, lit: Literal, ftype: str, path: str) -> Any:
        expected = self.m.primitive_xsd(ftype)
        if expected is None:
            if lit.datatype is not None:
                raise InverseError(
                    f"{path}: FHIR {ftype} must be a plain literal, got ^^<{lit.datatype}>"
                )
            return lit.lexical
        if expected == "#temporal":
            if lit.datatype is None:
                raise InverseError(f"{path}: FHIR {ftype} literal carries no datatype, so its "
                                   "precision is not recoverable")
            # Re-derive the datatype from the lexical form and require agreement.
            # This is what makes a silent precision change detectable.
            from .fhir_rdf import temporal_datatype
            derived = temporal_datatype(lit.lexical, ftype)
            if derived != lit.datatype:
                raise InverseError(
                    f"{path}: literal {lit.lexical!r} implies <{derived}> but is typed "
                    f"<{lit.datatype}>; temporal precision does not match its datatype"
                )
            return lit.lexical
        if expected.endswith("#boolean"):
            if lit.datatype != expected:
                raise InverseError(f"{path}: expected ^^<{expected}>, got ^^<{lit.datatype}>")
            if lit.lexical not in ("true", "false"):
                raise InverseError(f"{path}: {lit.lexical!r} is not an xsd:boolean")
            return lit.lexical == "true"
        if lit.datatype != expected:
            raise InverseError(
                f"{path}: FHIR {ftype} expects ^^<{expected}>, got ^^<{lit.datatype}>"
            )
        return FhirNumber(lit.lexical)


def to_json(triples, manifest: Optional[Manifest] = None, root=None) -> Dict[str, Any]:
    return FhirRdfReader(manifest).to_json(triples, root=root)
