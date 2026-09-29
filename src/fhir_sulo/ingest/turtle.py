"""A deterministic nested-Turtle writer, for the human-readable fixture copy.

The *canonical* artifact is sorted N-Triples (``ntriples.serialize``); this
writer exists so a reviewer can read a fixture without a tool. It reproduces
HL7's published layout closely enough to diff against it by eye, and it is
deterministic: nesting follows the triple emission order, which follows FHIR
element order.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .ntriples import BNode, IRI, Literal, Triple

XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

DEFAULT_PREFIXES = {
    "fhir": "http://hl7.org/fhir/",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}


def serialize(triples: Sequence[Triple], prefixes: Optional[Dict[str, str]] = None,
              root: Optional[IRI] = None) -> str:
    prefixes = dict(prefixes or DEFAULT_PREFIXES)
    by_subject: Dict[object, List[Triple]] = {}
    order: List[object] = []
    ref_count: Dict[object, int] = {}
    for t in triples:
        if t.s not in by_subject:
            by_subject[t.s] = []
            order.append(t.s)
        by_subject[t.s].append(t)
        if isinstance(t.o, BNode):
            ref_count[t.o] = ref_count.get(t.o, 0) + 1

    # A blank node referenced exactly once is inlined; anything else is a
    # top-level subject. FHIR RDF never shares a blank node, so in practice
    # every one inlines and the output is a single nested block per resource.
    inlinable = {n for n, c in ref_count.items() if c == 1}

    out: List[str] = []
    for prefix in sorted(prefixes):
        out.append(f"@prefix {prefix}: <{prefixes[prefix]}> .")
    out.append("")

    tops = [s for s in order if not (isinstance(s, BNode) and s in inlinable)]
    if root is not None and root in tops:
        tops = [root] + [s for s in tops if s != root]

    for i, subject in enumerate(tops):
        out.append(_term(subject, prefixes) + " " +
                   _predicate_block(by_subject, subject, inlinable, prefixes, 1) + " .")
        if i < len(tops) - 1:
            out.append("")
    return "\n".join(out) + "\n"


def _predicate_block(by_subject, subject, inlinable, prefixes, depth: int) -> str:
    pad = "  " * depth
    parts: List[str] = []
    for t in by_subject.get(subject, ()):
        pred = "a" if t.p.value == RDF_TYPE else _term(t.p, prefixes)
        if isinstance(t.o, BNode) and t.o in inlinable:
            inner = _predicate_block(by_subject, t.o, inlinable, prefixes, depth + 1)
            obj = "[\n" + "  " * (depth + 1) + inner + "\n" + pad + "]"
        else:
            obj = _term(t.o, prefixes)
        parts.append(f"{pred} {obj}")
    return (";\n" + pad).join(parts)


def _term(term, prefixes: Dict[str, str]) -> str:
    if isinstance(term, BNode):
        return "_:" + term.label
    if isinstance(term, IRI):
        for prefix, base in prefixes.items():
            if term.value.startswith(base):
                local = term.value[len(base):]
                if local and _is_pname_local(local):
                    return f"{prefix}:{local}"
        return term.n3()
    if isinstance(term, Literal):
        if term.datatype and term.datatype.startswith(XSD):
            return f'"{_esc(term.lexical)}"^^xsd:{term.datatype[len(XSD):]}'
        return term.n3()
    raise TypeError(type(term))  # pragma: no cover


def _is_pname_local(local: str) -> bool:
    if not local or local[0] in "-.":
        return False
    return all(c.isalnum() or c in "_-." for c in local)


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace('"', '\\"')
                .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
