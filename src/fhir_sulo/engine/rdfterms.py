"""RDF terms and quads as the driver moves them between engine passes.

Quads travel as structured terms, not as Turtle text. Re-parsing Turtle between
passes would be the easy route and it is the wrong one: blank node labels are
document-scoped, every materialization restarts its counter at ``_:tm0``, and a
Turtle round trip through a shared parser silently merges ``_:tm0`` from pass A
with ``_:tm0`` from pass B into one node (DR-301 §4d -- observed, not feared;
it corrupted the first version of probe 10's union).

Keeping terms structured makes relabelling a total, checkable function rather
than a hope about parser behaviour.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Optional


class InvalidTerm(ValueError):
    """A term that cannot be written as N-Triples.

    Raised rather than escaped: an IRI with a space in it is a bug upstream,
    and silently rewriting it would change what the graph says about the
    world. The driver's contract is that it does not alter the engine's terms.
    """


#: N-Triples IRIREF forbids these between the angle brackets, plus controls.
_ILLEGAL_IN_IRI = re.compile('[\\x00-\\x20<>"{}|^`\\\\]')

#: A conservative BLANK_NODE_LABEL: enough for engine counters and pass ids.
_VALID_BNODE_LABEL = re.compile(r"\A[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")

IRI = "iri"
BNODE = "bnode"
LITERAL = "literal"

XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"

# N-Triples ECHAR, plus \uXXXX for every other control character. Clinical
# free text really does carry stray control characters, and emitting one raw
# produces a file no parser will accept -- a corrupt graph rather than a
# rejected one. Applied per character, so a backslash cannot be double-escaped.
_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


def _escape(text: str) -> str:
    out = []
    for char in text:
        if char in _ESCAPES:
            out.append(_ESCAPES[char])
        elif char < " " or char == "\x7f":
            out.append("\\u%04X" % ord(char))
        else:
            out.append(char)
    return "".join(out)


@dataclass(frozen=True)
class Term:
    kind: str
    value: str
    datatype: Optional[str] = None
    language: Optional[str] = None

    @classmethod
    def from_bridge(cls, raw) -> "Term":
        return cls(
            kind=raw["t"],
            value=raw["v"],
            datatype=raw.get("dt"),
            language=raw.get("lang"),
        )

    def to_ntriples(self) -> str:
        if self.kind == IRI:
            bad = _ILLEGAL_IN_IRI.search(self.value)
            if bad:
                raise InvalidTerm(
                    f"IRI {self.value!r} contains {bad.group()!r}, which N-Triples "
                    f"forbids between < and >. Emitting it would produce a file no "
                    f"parser accepts"
                )
            return "<" + self.value + ">"
        if self.kind == BNODE:
            if not _VALID_BNODE_LABEL.match(self.value):
                raise InvalidTerm(
                    f"blank node label {self.value!r} is not a valid N-Triples "
                    f"label; if it was built from a pass id, that id needs to be "
                    f"restricted to letters, digits, '_' and '-'"
                )
            return "_:" + self.value
        body = '"' + _escape(self.value) + '"'
        if self.language:
            return body + "@" + self.language
        if self.datatype and self.datatype != XSD_STRING:
            return body + "^^<" + self.datatype + ">"
        return body


@dataclass(frozen=True)
class Quad:
    s: Term
    p: Term
    o: Term

    @classmethod
    def from_bridge(cls, raw) -> "Quad":
        return cls(
            s=Term.from_bridge(raw["s"]),
            p=Term.from_bridge(raw["p"]),
            o=Term.from_bridge(raw["o"]),
        )

    def to_ntriples(self) -> str:
        return f"{self.s.to_ntriples()} {self.p.to_ntriples()} {self.o.to_ntriples()} ."

    def relabel_blank_nodes(self, prefix: str) -> "Quad":
        """Return this quad with every blank node label prefixed.

        Only the label changes, and only for blank nodes: IRIs, literals and
        predicates are returned identically. That is what makes the union safe
        without making it a rewrite -- see ``driver.union_passes``.
        """
        return Quad(
            s=_relabel(self.s, prefix),
            p=_relabel(self.p, prefix),
            o=_relabel(self.o, prefix),
        )


def _relabel(term: Term, prefix: str) -> Term:
    if term.kind != BNODE:
        return term
    return replace(term, value=f"{prefix}_{term.value}")


def shape_signature(quad: Quad) -> tuple:
    """The part of a quad that relabelling must NOT change.

    Blank node labels collapse to the constant ``"_"`` so that two quads are
    equal under this signature exactly when they differ only in blank node
    naming. The driver's self-check compares signatures before and after the
    union; a driver that invented or altered a triple would change one.
    """

    def sig(term: Term):
        if term.kind == BNODE:
            return (BNODE, "_")
        return (term.kind, term.value, term.datatype, term.language)

    return (sig(quad.s), sig(quad.p), sig(quad.o))
