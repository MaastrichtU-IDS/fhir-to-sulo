"""Canonical serialisation primitives for deterministic keys.

Determinism rules, all of them load-bearing for Gate 4 ("unchanged
reprocessing changes no triples"):

* ``hashlib.sha256`` only. Python's builtin ``hash()`` is salted per process
  (``PYTHONHASHSEED``) and must never reach a key. ``tests/integration``
  enforces this by computing keys in two subprocesses with different seeds.
* Mapping keys are sorted, so dict insertion order cannot leak into a key.
* ``ensure_ascii=True``, so the hashed bytes are pure ASCII and independent of
  filesystem or locale encoding.
* Strings are Unicode NFC-normalised, so two byte-different but canonically
  equivalent source identifiers do not produce two graphs.
* No timestamps, no random values, no process or host state. Wall-clock time
  belongs in ``RunRecord.activity_time``, never in a key.

Duplication note
----------------
Agent 5 ships an equivalent module at ``src/fhir_sulo/policy/canonical.py`` on
their branch, with deliberately identical rules. The two must converge on one
module at integration; they are kept separate here only because the branches
are independent and importing across them would couple two gates. DR-601
records the convergence request.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Mapping

__all__ = ["normalise_text", "canonical_json", "sha256_hex", "digest"]


def normalise_text(value: str) -> str:
    """Unicode NFC-normalise and strip surrounding whitespace."""
    if not isinstance(value, str):
        raise TypeError("normalise_text expects str, got %s" % type(value).__name__)
    return unicodedata.normalize("NFC", value).strip()


def _normalise(value: Any) -> Any:
    if isinstance(value, str):
        return normalise_text(value)
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        # Float repr stability across platforms is not something a graph key
        # may depend on. Callers serialise decimals as strings.
        raise TypeError("float is not permitted in a canonical key input")
    if isinstance(value, Mapping):
        return {normalise_text(str(k)): _normalise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise(v) for v in value]
    raise TypeError("unsupported type in canonical input: %s" % type(value).__name__)


def canonical_json(value: Any) -> str:
    """Deterministic JSON text: sorted keys, no whitespace, ASCII-escaped."""
    return json.dumps(
        _normalise(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def digest(value: Any) -> str:
    """Full 64-character sha256 hex digest of the canonical form of ``value``."""
    return sha256_hex(canonical_json(value))
