"""A dependency-free N-Triples reader/writer.

The canonical rendered RDF committed under ``fixtures/r4/`` is sorted
N-Triples. That choice is deliberate:

* It is byte-stable, so a fixture diff is a real content diff.
* It parses with the standard library alone, so CI (which installs nothing
  beyond Python) can run the round-trip test. A round-trip test that is
  skipped in CI is worthless.
* Parsing the *serialised text* rather than reusing the renderer's in-memory
  tree is what stops the round-trip test from being circular.

Grammar: https://www.w3.org/TR/n-triples/ (the subset FHIR RDF needs: IRIs,
blank nodes, plain literals, typed literals, language-tagged literals).
"""

from __future__ import annotations

import re
from typing import Iterable, List, NamedTuple, Optional, Tuple

XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


class IRI(NamedTuple):
    value: str

    def n3(self) -> str:
        return "<" + _escape_iri(self.value) + ">"


class BNode(NamedTuple):
    label: str

    def n3(self) -> str:
        return "_:" + self.label


class Literal(NamedTuple):
    lexical: str
    datatype: Optional[str] = None
    language: Optional[str] = None

    def n3(self) -> str:
        s = '"' + _escape_literal(self.lexical) + '"'
        if self.language:
            return s + "@" + self.language
        if self.datatype:
            return s + "^^<" + _escape_iri(self.datatype) + ">"
        return s


Term = object  # IRI | BNode | Literal


class Triple(NamedTuple):
    s: Term
    p: IRI
    o: Term

    def n3(self) -> str:
        return f"{self.s.n3()} {self.p.n3()} {self.o.n3()} ."


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

_IRI_ESCAPES = {
    "\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t",
}


def _escape_iri(iri: str) -> str:
    out = []
    for ch in iri:
        if ch in '<>"{}|^`\\' or ord(ch) <= 0x20:
            out.append("\\u%04X" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def _escape_literal(text: str) -> str:
    out = []
    for ch in text:
        if ch in _IRI_ESCAPES:
            out.append(_IRI_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append("\\u%04X" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def serialize(triples: Iterable[Triple]) -> str:
    """Canonical form: one triple per line, bytewise-sorted, no duplicates.

    Duplicates are dropped because an RDF graph is a set. They arise legitimately
    when several resources in one fixture reference the same Patient and each
    contributes the same ``<...Patient/p123> a fhir:Patient .`` stub.
    """
    lines = sorted({t.n3() for t in triples})
    return "\n".join(lines) + ("\n" if lines else "")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_WS = re.compile(r"[ \t]+")
_IRI_RE = re.compile(r"<((?:[^\x00-\x20<>\"{}|^`\\]|\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8})*)>")
_BNODE_RE = re.compile(r"_:([A-Za-z0-9_][A-Za-z0-9_.\-]*)")
_LIT_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_LANG_RE = re.compile(r"@([a-zA-Z]+(?:-[a-zA-Z0-9]+)*)")

_UNESCAPE = {"t": "\t", "b": "\b", "n": "\n", "r": "\r", "f": "\f", '"': '"', "'": "'", "\\": "\\"}


class NTriplesSyntaxError(ValueError):
    pass


def _unescape(text: str) -> str:
    out: List[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= len(text):
            raise NTriplesSyntaxError("trailing backslash")
        esc = text[i]
        if esc in _UNESCAPE:
            out.append(_UNESCAPE[esc])
            i += 1
        elif esc == "u":
            out.append(chr(int(text[i + 1:i + 5], 16)))
            i += 5
        elif esc == "U":
            out.append(chr(int(text[i + 1:i + 9], 16)))
            i += 9
        else:
            raise NTriplesSyntaxError(f"unknown escape \\{esc}")
    return "".join(out)


def _parse_term(line: str, pos: int, allow_literal: bool):
    while pos < len(line) and line[pos] in " \t":
        pos += 1
    m = _IRI_RE.match(line, pos)
    if m:
        return IRI(_unescape(m.group(1))), m.end()
    m = _BNODE_RE.match(line, pos)
    if m:
        return BNode(m.group(1)), m.end()
    if allow_literal:
        m = _LIT_RE.match(line, pos)
        if m:
            lex = _unescape(m.group(1))
            pos = m.end()
            m2 = _LANG_RE.match(line, pos)
            if m2:
                return Literal(lex, None, m2.group(1)), m2.end()
            if line.startswith("^^", pos):
                m3 = _IRI_RE.match(line, pos + 2)
                if not m3:
                    raise NTriplesSyntaxError(f"bad datatype IRI in {line!r}")
                return Literal(lex, _unescape(m3.group(1)), None), m3.end()
            return Literal(lex, None, None), pos
    raise NTriplesSyntaxError(f"cannot parse term at offset {pos} in {line!r}")


def parse(text: str) -> List[Triple]:
    """Parse N-Triples text into a list of :class:`Triple`."""
    triples: List[Triple] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        s, pos = _parse_term(line, 0, allow_literal=False)
        p, pos = _parse_term(line, pos, allow_literal=False)
        o, pos = _parse_term(line, pos, allow_literal=True)
        rest = line[pos:].strip()
        if rest != ".":
            raise NTriplesSyntaxError(f"expected '.' at end of {line!r}, got {rest!r}")
        triples.append(Triple(s, p, o))
    return triples


def parse_file(path: str) -> List[Triple]:
    with open(path, "r", encoding="utf-8") as fh:
        return parse(fh.read())


# ---------------------------------------------------------------------------
# Small graph helper used by the inverse renderer and the binding extractor
# ---------------------------------------------------------------------------

class Graph:
    """Index over a triple list. Deliberately tiny; no reasoning, no I/O."""

    def __init__(self, triples: Iterable[Triple]):
        self.triples: Tuple[Triple, ...] = tuple(triples)
        self._by_subject = {}
        for t in self.triples:
            self._by_subject.setdefault(t.s, []).append(t)

    def po(self, subject) -> List[Tuple[IRI, Term]]:
        """Predicate/object pairs for a subject, in file order."""
        return [(t.p, t.o) for t in self._by_subject.get(subject, ())]

    def objects(self, subject, predicate: str) -> List[Term]:
        return [t.o for t in self._by_subject.get(subject, ()) if t.p.value == predicate]

    def one(self, subject, predicate: str):
        vals = self.objects(subject, predicate)
        if len(vals) > 1:
            raise ValueError(f"{subject} {predicate}: expected at most one, got {len(vals)}")
        return vals[0] if vals else None

    def subjects_with(self, predicate: str, obj=None) -> List[Term]:
        out = []
        for t in self.triples:
            if t.p.value == predicate and (obj is None or t.o == obj):
                out.append(t.s)
        return out
