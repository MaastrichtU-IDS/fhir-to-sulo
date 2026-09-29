"""Thin re-exports: the host-side map logic now lives in `fhir_sulo.pipeline`.

Everything here used to be implemented in the test tree, which is why the
pipeline did not exist in production code: the only thing that could run a map
was a test. It moved to `src/fhir_sulo/pipeline/` and this module is what keeps
Agent 3's case modules working unchanged across that move.

The one thing still defined here is `build_passes`'s legacy dict shape, which
the case modules assemble into a job document; it delegates to the production
implementation so there is one set of rules about conditional passes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from fhir_sulo.pipeline import runner as _runner
from fhir_sulo.pipeline.manifest import load_manifest as _load_manifest
from fhir_sulo.pipeline.services import (  # noqa: F401  (re-exported)
    ReferenceNotAPerson, entity_for_reference, policy_bundle, quality_iri,
    source_context, unit_iri,
)

from . import engine

REPO = engine.REPO

flat_bindings = _runner.flat_bindings
lexical = _runner.lexical


def load_manifest(family: str, version: str = "v1") -> Dict[str, Any]:
    """The manifest as a plain dict, which the case modules index directly."""
    return dict(_load_manifest(family, REPO, version).raw)


def tagged(b: Mapping[str, Any], name: str) -> str:
    """``lexical^^datatype`` -- Agent 2's tuple convention (DR-102)."""
    v = b.get(name)
    if v is None:
        return ""
    if isinstance(v, Mapping):
        return v["value"] + ("^^" + v["type"] if v.get("type") else "")
    return str(v)


def _manifest_of(raw: Mapping[str, Any]):
    from fhir_sulo.pipeline.manifest import Manifest

    return Manifest(family=raw.get("map_id", "?"), path=Path("<in-memory>"), raw=raw)


def bind(family: str, fixture: Path, focus: str, version: str = "v1",
         data_override: Optional[str] = None) -> Dict[str, Any]:
    """Stage 1 only: validate the source shape and return the engine result."""
    return engine.run_job({
        "sourceSchema": "maps/r4/%s/%s-source.%s.shex" % (family, family, version),
        "data": None if data_override is not None else str(fixture.relative_to(REPO)),
        "dataInline": data_override,
        "focus": focus,
        "startShape": None,
        "passes": [],
    })


def build_passes(manifest: Mapping[str, Any], values: Mapping[str, str],
                 source_bindings: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """One engine pass per IRI-identified target node, as job-document dicts."""
    passes, _skipped = _runner.build_passes(
        _manifest_of(manifest), values, source_bindings or {})
    return [{"name": p.name, "shape": p.shape, "root": p.root,
             "staticVars": dict(p.static_vars)} for p in passes]


def node_keys(manifest: Mapping[str, Any], **fmt: str) -> Dict[str, str]:
    return _manifest_of(manifest).node_keys(**fmt)


def vocabulary(manifest: Mapping[str, Any]) -> Dict[str, str]:
    return _manifest_of(manifest).vocabulary
