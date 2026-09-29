"""Turn a manifest plus host-resolved values into a map run and a TransformResult.

This is the middle of the pipeline, and until now it did not exist in
production code: the maps were executed only by a test-only Node script, and
the store's loader was fed only by a synthetic benchmark generator. The two
ends never met.

What the host does here is exactly what concept note section 3 assigns it and
no more -- select a map, call identity and terminology, choose root nodes,
batch, union. It constructs no target triple. Every quad comes from a schema
in ``maps/r4/``, and :meth:`MapRun.untraced_quads` is empty only if every one
of them names a TripleConstraint the target schema declares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..contracts import (
    BindingNode, QuadLineage, TransformResult, TransformStatus,
)
from ..engine.docker import EngineImage, default_image
from ..engine.driver import Guards, to_transform_result
from ..engine.maprun import MapJob, MapPass, MapRunResult, bind, run_map
from .manifest import Manifest, MapFiles, PassSpec, host_consumed_variables


class MissingRunBinding(KeyError):
    """A pass needs a value the host did not resolve.

    Raised rather than defaulted: a pass silently handed a placeholder would
    materialize a graph full of plausible wrong IRIs.
    """


@dataclass(frozen=True)
class MapRun:
    """One map applied to one resource."""

    manifest: Manifest
    focus: str
    result: MapRunResult
    values: Mapping[str, Any]
    source_bindings: Mapping[str, Any]
    skipped_passes: Tuple[str, ...] = ()

    @property
    def ntriples(self) -> Tuple[str, ...]:
        return self.result.ntriples

    def untraced_quads(self) -> Tuple[int, ...]:
        return self.result.driver_result.untraced_quads()

    def lineage(self) -> Tuple[QuadLineage, ...]:
        return self.result.driver_result.lineage()

    def transform_result(
        self,
        source_canonical_url: str,
        source_version_id: str,
        output_graph_key: str,
        target_root: Optional[str] = None,
        diagnostics: Sequence[str] = (),
    ) -> TransformResult:
        """The frozen contract object.

        ``output_graph_key`` is supplied, never derived here: it is the store's
        13-input key (DR-601), and the driver does not know most of those
        inputs -- SULO version, engine build, renderer, policy version are run
        metadata the pipeline holds. Computing a weaker key here was the bug
        DR-305 removes.
        """
        extra = list(diagnostics)
        if self.skipped_passes:
            extra.append(
                "passes skipped because the source bound nothing for their "
                "declared variable: " + ", ".join(self.skipped_passes))
        return to_transform_result(
            self.result.driver_result,
            map_id=self.manifest.map_id,
            pairing_hash=self.manifest.semantic_version,
            source_canonical_url=source_canonical_url,
            source_version_id=source_version_id,
            target_root=target_root or self._primary_root(),
            output_graph_key=output_graph_key,
            extra_diagnostics=extra,
        )

    def _primary_root(self) -> Optional[str]:
        return self.result.passes[0].root if self.result.passes else None


def flat_bindings(bindings: Optional[Mapping[str, Any]], var_namespace: str) -> Dict[str, Any]:
    """``{shortName: {'value', 'type'}}`` from a flat ShExMap binding tree."""
    out: Dict[str, Any] = {}
    for key, value in (bindings or {}).items():
        if key.startswith(var_namespace):
            out[key[len(var_namespace):]] = value
    return out


def lexical(bindings: Mapping[str, Any], name: str) -> Optional[str]:
    value = bindings.get(name)
    if value is None:
        return None
    return value["value"] if isinstance(value, Mapping) else value


def build_passes(
    manifest: Manifest,
    values: Mapping[str, Any],
    source_bindings: Mapping[str, Any],
) -> Tuple[List[MapPass], List[str]]:
    """One engine pass per IRI-identified target node. Returns ``(passes, skipped)``.

    ``requires_source_binding`` / ``forbids_source_binding`` is the whole of
    the host's conditional logic, and the manifest declares it rather than this
    code deciding. A skipped pass emits nothing; nothing is reconstructed,
    guessed or re-associated host-side.
    """
    passes: List[MapPass] = []
    skipped: List[str] = []
    for spec in manifest.passes:
        if not spec.runs_for(source_bindings):
            skipped.append(spec.name)
            continue
        statics: Dict[str, Any] = {}
        for iri in manifest.static_variables_of(spec):
            local = iri[len(manifest.var_namespace):]
            if local not in values:
                raise MissingRunBinding(
                    f"pass {spec.name!r} of {manifest.map_id} needs run binding "
                    f"{local!r} and the host did not resolve it")
            statics[iri] = values[local]
        if spec.root not in values:
            raise MissingRunBinding(
                f"pass {spec.name!r} of {manifest.map_id} is rooted at {spec.root!r} "
                f"and the host did not resolve it")
        passes.append(MapPass(
            name=spec.name,
            shape=manifest.shape_iri(spec.shape),
            root=values[spec.root],
            static_vars=statics,
        ))
    return passes, skipped


@dataclass(frozen=True)
class MapRunner:
    """Runs one map family against one resource graph."""

    files: MapFiles
    engine: EngineImage = field(default_factory=default_image)
    guards: Guards = field(default_factory=Guards)

    @property
    def manifest(self) -> Manifest:
        manifest = self.files.manifest
        if manifest is None:
            raise ValueError(f"{self.files.family}: no run-binding manifest")
        return manifest

    def _job(self, data: str, focus: str, passes: Sequence[MapPass]) -> MapJob:
        return MapJob(
            source_schema=self.files.source.read_text(encoding="utf-8"),
            target_schema=self.files.target.read_text(encoding="utf-8"),
            data=data,
            node=focus,
            passes=passes,
            source_base=f"urn:fhir-sulo:{self.files.family}:source",
            target_base=f"urn:fhir-sulo:{self.files.family}:target",
        )

    def bind(self, data: str, focus: str) -> Dict[str, Any]:
        """Validate the resource graph and return its flat bindings."""
        tree = bind(self._job(data, focus, ()), engine=self.engine)
        return flat_bindings(tree, self.manifest.var_namespace)

    def run(
        self,
        data: str,
        focus: str,
        values: Mapping[str, Any],
        source_bindings: Optional[Mapping[str, Any]] = None,
        bindings_override: Optional[Any] = None,
    ) -> MapRun:
        manifest = self.manifest
        bound = dict(source_bindings) if source_bindings is not None \
            else self.bind(data, focus)
        passes, skipped = build_passes(manifest, values, bound)
        job = self._job(data, focus, passes)
        if bindings_override is not None:
            job = MapJob(
                source_schema=job.source_schema, target_schema=job.target_schema,
                data=job.data, node=job.node, passes=job.passes,
                source_shape=job.source_shape, source_base=job.source_base,
                target_base=job.target_base, data_base=job.data_base,
                bindings_override=bindings_override,
            )
        result = run_map(job, engine=self.engine, guards=self.guards,
                         host_consumed=sorted(
                             # the engine reports unconsumed variables by IRI
                             manifest.var_iri(local) for local in
                             host_consumed_variables(
                                 manifest, self.files.contract_document)))
        return MapRun(manifest=manifest, focus=focus, result=result,
                      values=values, source_bindings=bound,
                      skipped_passes=tuple(skipped))
