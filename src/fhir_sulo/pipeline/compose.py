"""FHIR JSON in, a loadable ``TransformResult`` out: the whole path.

    FHIR JSON --[ingest]--> SourceContext
              --[identity + terminology]--> run bindings
              --[ShExMap driver over maps/r4/]--> TransformResult
              --[store]--> a named graph with provenance

Before this the three stages existed and nothing joined them. The maps were
run only by a test-only Node script; the store's loader was fed only by a
synthetic benchmark generator; the ``SourceContext`` ingest produced had no
consumer. Each stage was tested and the pipeline did not exist.

Two rules this file exists to keep:

* **Ineligibility stops the run before it starts.** ``TransformResult`` refuses
  target quads on ``source-only`` and ``rejected``, so an ineligible resource
  never reaches the engine rather than being mapped and then stripped. Concept
  note section 2: ``entered-in-error`` suppresses clinical assertions.
* **An unresolved or ambiguous reference is not a person.** The identity
  service declining is a normal outcome and yields ``source-only``, not a
  graph with a guessed subject.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from ..contracts import (
    EligibilityOutcome, RunRecord, SourceContext, TransformResult, TransformStatus,
)
from ..engine.docker import EngineImage, default_image
from ..engine.driver import Guards, graph_key
from .families import Family, family_for
from .manifest import MapFiles, discover
from .runner import MapRun, MapRunner
from .services import ReferenceNotAPerson, policy_bundle, source_context


@dataclass(frozen=True)
class PipelineOutcome:
    """One resource, mapped or explicitly not."""

    source: SourceContext
    transform: TransformResult
    run: Optional[MapRun] = None
    family: str = ""
    notes: Tuple[str, ...] = ()

    @property
    def is_loadable(self) -> bool:
        return self.transform.is_loadable

    @property
    def ntriples(self) -> Tuple[str, ...]:
        return self.transform.target_quads

    def run_record(
        self,
        run_id: str,
        activity_time: str,
        engine_build: str,
        sulo_version: str,
        domain_ontology_version: str,
        policy_version: str,
        contract_version: str,
        validation_report_digest: str = "",
    ) -> RunRecord:
        """The immutable metadata for this run.

        ``engine_build`` should be ``EngineImage.build_id()`` -- the image
        content id, not the tag, because a tag can be rebuilt.
        """
        from ..engine.driver import DriverResult

        digest = ""
        if self.run is not None:
            digest = self.run.result.driver_result.content_digest()
        return RunRecord(
            run_id=run_id,
            activity_time=activity_time,
            source_canonical_url=self.source.canonical_url,
            source_version_id=self.source.version_id,
            source_json_digest=self.source.source_json_digest,
            map_id=self.transform.map_id,
            map_semantic_version=self.transform.pairing_hash,
            pairing_hash=self.transform.pairing_hash,
            sulo_version=sulo_version,
            domain_ontology_version=domain_ontology_version,
            terminology_snapshot=self.source.terminology_snapshot,
            engine_build=engine_build,
            policy_version=policy_version,
            contract_version=contract_version,
            output_graph_key=self.transform.output_graph_key,
            output_digest=digest,
            validation_report_digest=validation_report_digest,
            transform_status=self.transform.status.value,
            renderer_id=self.source.renderer_id,
        )


@dataclass(frozen=True)
class Pipeline:
    """The composed path for one map family."""

    family: Family
    files: MapFiles
    engine: EngineImage = field(default_factory=default_image)
    guards: Guards = field(default_factory=Guards)
    quality_mode: Optional[str] = None

    @classmethod
    def for_family(
        cls,
        name: str,
        repo_root: Path,
        engine: Optional[EngineImage] = None,
        quality_mode: Optional[str] = None,
    ) -> "Pipeline":
        families = {f.family: f for f in discover(repo_root / "maps")}
        if name not in families:
            raise KeyError(
                f"no map family {name!r} under {repo_root / 'maps'}; found "
                f"{', '.join(sorted(families)) or 'none'}")
        resolver = family_for(name)
        return cls(
            family=resolver,
            files=families[name],
            engine=engine or default_image(),
            quality_mode=quality_mode if quality_mode is not None
            else resolver.quality_mode,
        )

    # -- the path -----------------------------------------------------------

    def run_file(self, fhir_json: Path, rdf: Optional[str] = None) -> PipelineOutcome:
        """Ingest one FHIR JSON resource and map it."""
        context = source_context(Path(fhir_json))
        return self.run_context(context, rdf=rdf)

    def run_context(
        self, context: SourceContext, rdf: Optional[str] = None
    ) -> PipelineOutcome:
        manifest = self.files.manifest
        if manifest is None:
            raise ValueError(f"{self.files.family}: no run-binding manifest")

        canonical_url = context.canonical_url
        identity_keys = dict(
            map_id=manifest.map_id,
            pairing_hash=manifest.semantic_version,
            source_canonical_url=canonical_url,
            source_version_id=context.version_id,
        )

        # 1. eligibility, before anything is materialized
        if context.eligibility is not EligibilityOutcome.ELIGIBLE:
            status = (TransformStatus.SOURCE_ONLY
                      if context.eligibility is EligibilityOutcome.SOURCE_ONLY
                      else TransformStatus.REJECTED)
            reason = context.eligibility_reason or "ineligible source resource"
            return PipelineOutcome(
                source=context, family=self.family.name,
                transform=_ineligible(status, reason, **identity_keys),
                notes=(reason,))

        # 2. bind the source graph
        runner = MapRunner(files=self.files, engine=self.engine, guards=self.guards)
        graph = rdf if rdf is not None else context.rdf_graph
        bindings = runner.bind(graph, canonical_url)

        # 3. identity and terminology
        from ..identity import IdentityService
        from ..terminology import TerminologyService

        policy = policy_bundle(self.quality_mode)
        try:
            resolved = self.family.resolve(
                manifest, bindings, context,
                IdentityService(policy), TerminologyService(policy), canonical_url)
        except ReferenceNotAPerson as exc:
            # Not an error: the identity service declining is a designed
            # outcome, and inventing a subject to get a graph would be the
            # person-equivalence claim concept note section 2 forbids.
            reason = f"{exc.reason_code}: {exc.reason}"
            return PipelineOutcome(
                source=context, family=self.family.name,
                transform=_ineligible(TransformStatus.SOURCE_ONLY, reason,
                                      **identity_keys),
                notes=(reason,))

        # 4. materialize every declared pass and union
        run = runner.run(graph, canonical_url, resolved.values,
                         source_bindings=bindings)
        transform = run.transform_result(
            source_canonical_url=canonical_url,
            source_version_id=context.version_id,
        )
        return PipelineOutcome(source=context, transform=transform, run=run,
                               family=self.family.name, notes=resolved.notes)


def _ineligible(status: TransformStatus, reason: str, **keys) -> TransformResult:
    return TransformResult(
        status=status,
        map_id=keys["map_id"],
        pairing_hash=keys["pairing_hash"],
        source_canonical_url=keys["source_canonical_url"],
        source_version_id=keys["source_version_id"],
        output_graph_key=graph_key(
            keys["map_id"], keys["pairing_hash"],
            keys["source_canonical_url"], keys["source_version_id"]),
        rejection_reason=reason if status is TransformStatus.REJECTED else None,
        diagnostics=(reason,),
    )
