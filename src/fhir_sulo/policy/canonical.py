"""Canonical serialisation and deterministic keying primitives.

Every entity key and every decision id in the identity and terminology services
goes through this module, so determinism is enforced in exactly one place.

Determinism rules enforced here
-------------------------------
* ``hashlib.sha256`` only. Python's builtin ``hash()`` is salted per process
  (``PYTHONHASHSEED``) and must never reach a key.
* Mapping keys are sorted, so Python dict insertion order cannot leak into a key.
* ``ensure_ascii=True``, so the hashed bytes are pure ASCII and independent of
  filesystem or locale encoding.
* Strings are Unicode NFC-normalised before hashing, so two byte-different but
  canonically equivalent source ids do not produce two entities.
* No timestamps, no random values, no process or host state. Run timestamps
  belong in Agent 6's ``RunRecord``, not in a key or a decision id.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Mapping, Sequence

__all__ = [
    "normalise_text",
    "canonical_json",
    "sha256_hex",
    "digest",
    "slugify",
]


def normalise_text(value: str) -> str:
    """Unicode NFC-normalise and strip surrounding whitespace."""
    if not isinstance(value, str):
        raise TypeError("normalise_text expects str, got %r" % type(value).__name__)
    return unicodedata.normalize("NFC", value).strip()


def _normalise(value: Any) -> Any:
    if isinstance(value, str):
        return normalise_text(value)
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        # Floats are not permitted in keys: repr stability across platforms is
        # not something this project should depend on.
        raise TypeError("float is not permitted in a canonical key or digest input")
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


_SLUG_SAFE = set("abcdefghijklmnopqrstuvwxyz0123456789")


def slugify(value: str, *, max_length: int = 48) -> str:
    """Lowercase, ASCII-only, hyphen-separated slug. Empty input raises.

    Used only for the human-readable part of a readable key style; the entropy
    always comes from the hash, never from the slug.
    """
    text = normalise_text(value).lower()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    out = []
    prev_dash = False
    for ch in text:
        if ch in _SLUG_SAFE:
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    slug = "".join(out).strip("-")[:max_length].strip("-")
    if not slug:
        raise ValueError("cannot slugify %r to a non-empty slug" % value)
    return slug


def key_fragment(fields: Sequence[str], values: Mapping[str, Any], *, length: int) -> str:
    """Hash exactly ``fields`` (in the given order) out of ``values``.

    Missing or empty fields raise: a key must never be computed from a partially
    populated input, because that silently collapses distinct entities.
    """
    payload = []
    for field in fields:
        if field not in values:
            raise KeyError("missing key input field: %s" % field)
        value = values[field]
        if value is None or (isinstance(value, str) and not normalise_text(value)):
            raise ValueError("empty key input field: %s" % field)
        payload.append([field, _normalise(value)])
    return digest(payload)[:length]
