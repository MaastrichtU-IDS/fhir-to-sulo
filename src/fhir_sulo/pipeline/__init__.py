"""The composed path: FHIR JSON in, a loadable target graph out.

Until this package existed the pipeline was three islands. Agent 2's ingest
produced a ``SourceContext`` nothing consumed; Agent 3's maps were executed
only by a test-only Node script; Agent 6's store loader was fed only by a
synthetic benchmark generator. The driver this package drives is the middle.

* :mod:`~fhir_sulo.pipeline.manifest` -- read a map's run-binding manifest,
  shared with the linter so the two cannot disagree about what is on disk.
* :mod:`~fhir_sulo.pipeline.runner` -- manifest plus host-resolved values to a
  map run and a frozen ``TransformResult``.
* :mod:`~fhir_sulo.pipeline.families` -- the per-family host work: which
  identity and terminology calls a map needs, and what to root its passes at.
* :mod:`~fhir_sulo.pipeline.compose` -- the whole path, end to end.
"""

from __future__ import annotations

from .manifest import Manifest, MapFiles, discover, load_manifest, load_manifest_file
from .runner import MapRun, MapRunner, MissingRunBinding, build_passes, flat_bindings, lexical

__all__ = [
    "Manifest", "MapFiles", "discover", "load_manifest", "load_manifest_file",
    "MapRun", "MapRunner", "MissingRunBinding", "build_passes", "flat_bindings",
    "lexical",
]
