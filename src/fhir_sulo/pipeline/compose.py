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

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from ..contracts import (
    EligibilityOutcome, RunRecord, SourceContext, TransformResult, TransformStatus,
)
from ..engine.docker import EngineImage, default_image
from ..engine.driver import Guards
from .families import Family, family_for
from .manifest import MapFiles, discover
from .runner import MapRun, MapRunner
from ..provenance.run_records import RunInputs, build_run_record, output_digest
from .services import ReferenceNotAPerson, policy_bundle, source_context


#: Honest placeholders. ``GraphKeyInputs`` refuses an empty string, on the
#: reasoning that "we had not decided yet" is itself a fact about the run and
#: must not hash to the same graph as a decision. These are the tokens for the
#: two things the pilot has not decided.
UNRESOLVED_DOMAIN = "unresolved:R1"


@dataclass(frozen=True)
class RunMetadata:
    """The run-level facts the graph key is a function of.

    Held on the Pipeline rather than passed per resource, because they are
    constant for a run and because the store's key refuses to be computed
    without them.
    """

    sulo_version: str = "0.2.12"
    domain_ontology_version: str = UNRESOLVED_DOMAIN
    policy_version: str = ""
    engine_build: str = ""


@dataclass(frozen=True)
class PipelineOutcome:
    """One resource, mapped or explicitly not."""

    source: SourceContext
    transform: TransformResult
    run: Optional[MapRun] = None
    family: str = ""
    notes: Tuple[str, ...] = ()
    #: the 13 graph-key inputs, so a run record can be built without
    #: recomputing them and without a second, weaker key
    inputs: Optional[RunInputs] = None

    @property
    def is_loadable(self) -> bool:
        return self.transform.is_loadable

    @property
    def ntriples(self) -> Tuple[str, ...]:
        return self.transform.target_quads

    def run_record(
        self,
        activity_time: Optional[str] = None,
        run_id: Optional[str] = None,
        validation_report_digest: str = "",
    ) -> RunRecord:
        """The immutable metadata for this run, ready for the store.

        Delegates to ``provenance.run_records.build_run_record``, which derives
        ``output_graph_key`` from the record's own fields. That is not a
        detail: the store recomputes the key from the record and **rejects**
        it if the two disagree, which is what makes an archived correction
        verifiable. An earlier version of this method filled the key from a
        different, four-field function, so its output could not be loaded --
        correct of the store, and unhelpful of this method. See DR-305.
        """
        if self.inputs is None:
            raise ValueError(
                "this outcome carries no RunInputs, so its graph key cannot be "
                "recomputed and the store would refuse the record")
        return build_run_record(
            self.inputs,
            status=self.transform.status,
            quads=self.transform.target_quads,
            validation_report_digest=validation_report_digest or "not-validated",
            activity_time=activity_time,
            run_id=run_id,
        )


@dataclass(frozen=True)
class Pipeline:
    """The composed path for one map family."""

    family: Family
    files: MapFiles
    engine: EngineImage = field(default_factory=default_image)
    guards: Guards = field(default_factory=Guards)
    quality_mode: Optional[str] = None
    #: R8b. The person-identifier index this run resolves identity under, or
    #: None for the conservative default where nothing reunifies.
    person_index: Optional[Any] = None
    #: DR-018. Which source this run's resources come from. ``None`` means
    #: the ingest default, which is correct ONLY for a single-source run.
    #: Carried here because ``run_file`` ingests for itself, so DR-014's fix
    #: reached ``run_context`` and stopped short of the path operators use.
    source_scope_id: Optional[str] = None
    metadata: RunMetadata = field(default_factory=RunMetadata)

    @property
    def person_index_digest(self) -> str:
        """DR-016. DERIVED, never set beside the index.

        It belongs in the graph key because the index decides which source
        records are one person, so it changes the entity IRIs in the emitted
        graph. Holding it as its own field would let the digest disagree with
        the index actually in use -- a graph key that lies about its graph,
        which is worse than having no key at all.
        """
        if self.person_index is None or not len(self.person_index):
            return "none"
        return self.person_index.digest

    @classmethod
    def for_family(
        cls,
        name: str,
        repo_root: Path,
        engine: Optional[EngineImage] = None,
        quality_mode: Optional[str] = None,
        metadata: Optional["RunMetadata"] = None,
        person_index: Optional[Any] = None,
        source_scope_id: Optional[str] = None,
    ) -> "Pipeline":
        families = {f.family: f for f in discover(repo_root / "maps")}
        if name not in families:
            raise KeyError(
                f"no map family {name!r} under {repo_root / 'maps'}; found "
                f"{', '.join(sorted(families)) or 'none'}")
        resolver = family_for(name)
        image = engine or default_image()
        mode = quality_mode if quality_mode is not None else resolver.quality_mode
        meta = metadata or RunMetadata()
        if not meta.policy_version:
            meta = replace(meta, policy_version=policy_bundle(mode).policy_version)
        if not meta.engine_build:
            meta = replace(meta, engine_build=image.build_id())
        return cls(
            family=resolver,
            files=families[name],
            engine=image,
            quality_mode=mode,
            metadata=meta,
            person_index=person_index,
            source_scope_id=source_scope_id,
        )

    # -- the path -----------------------------------------------------------

    def run_inputs(self, context: SourceContext) -> RunInputs:
        """The 13 fields the store's graph key is a function of (DR-601)."""
        manifest = self.files.manifest
        return RunInputs(
            source_canonical_url=context.canonical_url,
            source_version_id=context.version_id,
            source_json_digest=context.source_json_digest,
            map_id=manifest.map_id,
            map_semantic_version=manifest.semantic_version,
            pairing_hash=manifest.semantic_version,
            sulo_version=self.metadata.sulo_version,
            domain_ontology_version=self.metadata.domain_ontology_version,
            terminology_snapshot=context.terminology_snapshot,
            policy_version=self.metadata.policy_version,
            engine_build=self.metadata.engine_build,
            renderer_id=context.renderer_id,
            person_index_digest=self.person_index_digest,
        )

    def run_file(self, fhir_json: Path, rdf: Optional[str] = None) -> PipelineOutcome:
        """Ingest one FHIR JSON resource and map it."""
        context = source_context(Path(fhir_json), source_scope_id=self.source_scope_id)
        return self.run_context(context, rdf=rdf)

    def run_context(
        self, context: SourceContext, rdf: Optional[str] = None
    ) -> PipelineOutcome:
        manifest = self.files.manifest
        if manifest is None:
            raise ValueError(f"{self.files.family}: no run-binding manifest")

        canonical_url = context.canonical_url
        inputs = self.run_inputs(context)
        identity_keys = dict(
            map_id=manifest.map_id,
            pairing_hash=manifest.semantic_version,
            source_canonical_url=canonical_url,
            source_version_id=context.version_id,
            output_graph_key=inputs.graph_key,
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
                notes=(reason,), inputs=inputs)

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
                IdentityService(policy, person_index=self.person_index),
                TerminologyService(policy), canonical_url)
        except ReferenceNotAPerson as exc:
            # Not an error: the identity service declining is a designed
            # outcome, and inventing a subject to get a graph would be the
            # person-equivalence claim concept note section 2 forbids.
            reason = f"{exc.reason_code}: {exc.reason}"
            return PipelineOutcome(
                source=context, family=self.family.name,
                transform=_ineligible(TransformStatus.SOURCE_ONLY, reason,
                                      **identity_keys),
                notes=(reason,), inputs=inputs)

        # 4. materialize every declared pass and union
        run = runner.run(graph, canonical_url, resolved.values,
                         source_bindings=bindings)
        transform = run.transform_result(
            source_canonical_url=canonical_url,
            source_version_id=context.version_id,
            output_graph_key=inputs.graph_key,
        )
        return PipelineOutcome(source=context, transform=transform, run=run,
                               family=self.family.name, notes=resolved.notes,
                               inputs=inputs)


def _ineligible(status: TransformStatus, reason: str, **keys) -> TransformResult:
    return TransformResult(
        status=status,
        map_id=keys["map_id"],
        pairing_hash=keys["pairing_hash"],
        source_canonical_url=keys["source_canonical_url"],
        source_version_id=keys["source_version_id"],
        output_graph_key=keys["output_graph_key"],
        rejection_reason=reason if status is TransformStatus.REJECTED else None,
        diagnostics=(reason,),
    )
