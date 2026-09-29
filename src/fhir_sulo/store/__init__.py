"""Output graph store: deterministic graph keys, named graph versioning, correction.

Agent 6 scope. Nothing here parses RDF - quads are opaque lines exactly as
``TransformResult.target_quads`` carries them - so this package is stdlib-only
and runs under the system interpreter with no dependencies.
"""

from __future__ import annotations

from .canonical import canonical_json, digest, normalise_text, sha256_hex
from .graph_key import (
    CONTENT_FIELDS,
    EXCLUDED_RUN_RECORD_FIELDS,
    KEY_NAMESPACE,
    KEY_SPEC_VERSION,
    SUBJECT_FIELDS,
    GraphKeyError,
    GraphKeyInputs,
    graph_key,
    graph_key_from_run_record,
    subject_key,
    subject_key_from_run_record,
    subject_of,
)
from .graph_store import (
    GraphState,
    LoadAction,
    LoadOutcome,
    NamedGraphStore,
    RunLedger,
    SourceRecord,
    SourceRecordRegistry,
    StoreIntegrityError,
    StoredGraph,
)

__all__ = [
    "canonical_json",
    "digest",
    "normalise_text",
    "sha256_hex",
    "CONTENT_FIELDS",
    "EXCLUDED_RUN_RECORD_FIELDS",
    "KEY_NAMESPACE",
    "KEY_SPEC_VERSION",
    "SUBJECT_FIELDS",
    "GraphKeyError",
    "GraphKeyInputs",
    "graph_key",
    "graph_key_from_run_record",
    "subject_key",
    "subject_key_from_run_record",
    "subject_of",
    "GraphState",
    "LoadAction",
    "LoadOutcome",
    "NamedGraphStore",
    "RunLedger",
    "SourceRecord",
    "SourceRecordRegistry",
    "StoreIntegrityError",
    "StoredGraph",
]
