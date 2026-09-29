"""Lexical-form-preserving JSON I/O for FHIR resources.

Why this module exists
----------------------
``json.load`` turns ``55.0`` into the Python float ``55.0`` and ``120`` into the
int ``120``. Both lose information the pilot must not lose:

* ``55.0`` and ``55`` become indistinguishable once you round-trip through
  ``float``/``repr`` in the general case, and FHIR's ``decimal`` type is
  explicitly defined to preserve the precision of the submitted value
  (https://hl7.org/fhir/R4/datatypes.html#decimal).
* Concept note section 2 forbids dropping precision while claiming an
  unqualified numeric result.

So numbers are parsed into :class:`FhirNumber`, a ``str`` subclass carrying the
*exact source lexical form*. The renderer writes that form into the RDF literal
and the inverse renderer reads it back, which is what makes the round-trip test
able to detect a precision loss at all.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class FhirNumber(str):
    """A JSON number, kept as its exact source lexical form.

    Subclasses ``str`` so that comparisons against the original parse are
    string comparisons on the lexical form: ``FhirNumber("55.0") !=
    FhirNumber("55")``, which is the discrimination the round-trip test needs.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"FhirNumber({str.__repr__(self)})"


def loads(text: str) -> Any:
    """Parse FHIR JSON, preserving the lexical form of every number."""
    return json.loads(text, parse_float=FhirNumber, parse_int=FhirNumber)


def load_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return loads(fh.read())


def dumps(value: Any, indent: int = 2) -> str:
    """Serialise back to JSON with numbers written as their stored lexical form.

    ``json.dumps`` would quote a ``FhirNumber`` because it is a ``str``, so this
    is a small hand-written serialiser. Object key order is source order, which
    ``dict`` preserves in Python 3.7+.
    """
    out: list = []
    _dump(value, out, indent, 0)
    return "".join(out)


def _dump(value: Any, out: list, indent: int, level: int) -> None:
    pad = " " * (indent * level)
    inner = " " * (indent * (level + 1))
    if isinstance(value, FhirNumber):
        out.append(str(value))
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif value is None:
        out.append("null")
    elif isinstance(value, str):
        out.append(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, dict):
        if not value:
            out.append("{}")
            return
        out.append("{\n")
        items = list(value.items())
        for i, (k, v) in enumerate(items):
            out.append(inner)
            out.append(json.dumps(k, ensure_ascii=False))
            out.append(": ")
            _dump(v, out, indent, level + 1)
            out.append(",\n" if i < len(items) - 1 else "\n")
        out.append(pad + "}")
    elif isinstance(value, list):
        if not value:
            out.append("[]")
            return
        out.append("[\n")
        for i, v in enumerate(value):
            out.append(inner)
            _dump(v, out, indent, level + 1)
            out.append(",\n" if i < len(value) - 1 else "\n")
        out.append(pad + "]")
    else:  # pragma: no cover - guard
        raise TypeError(f"cannot serialise {type(value).__name__}")


def digest(text: str) -> str:
    """The SourceContext ``source_json_digest``: sha256 of the exact bytes."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Strict structural comparison
# --------------------------------------------------------------------------

_KIND_BOOL = "bool"
_KIND_NUM = "number"
_KIND_STR = "string"


def _kind(v: Any) -> str:
    if isinstance(v, bool):
        return _KIND_BOOL
    if isinstance(v, FhirNumber):
        return _KIND_NUM
    if isinstance(v, str):
        return _KIND_STR
    if isinstance(v, dict):
        return "object"
    if isinstance(v, list):
        return "array"
    if v is None:
        return "null"
    return type(v).__name__


def diff(a: Any, b: Any, path: str = "$") -> list:
    """Return a list of human-readable differences between two parsed resources.

    Type-aware: a JSON *string* ``"55.0"`` and a JSON *number* ``55.0`` are
    reported as different even though ``FhirNumber`` compares equal to ``str``.
    Object key order is NOT compared (JSON objects are unordered); array order
    IS compared (FHIR arrays are ordered and the RDF carries ``fhir:index``).
    """
    out: list = []
    ka, kb = _kind(a), _kind(b)
    if ka != kb:
        out.append(f"{path}: kind {ka} != {kb} ({a!r} vs {b!r})")
        return out
    if ka == "object":
        for k in a:
            if k not in b:
                out.append(f"{path}.{k}: missing on the right")
            else:
                out.extend(diff(a[k], b[k], f"{path}.{k}"))
        for k in b:
            if k not in a:
                out.append(f"{path}.{k}: unexpected on the right")
    elif ka == "array":
        if len(a) != len(b):
            out.append(f"{path}: length {len(a)} != {len(b)}")
        for i, (x, y) in enumerate(zip(a, b)):
            out.extend(diff(x, y, f"{path}[{i}]"))
    elif a != b:
        out.append(f"{path}: {a!r} != {b!r}")
    return out
