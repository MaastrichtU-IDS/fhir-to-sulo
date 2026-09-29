"""Gate 4 scale trial: the REAL pipeline over N synthetic FHIR resources.

    The benchmark processes 10,000 synthetic resources on a documented
    4-vCPU/8-GB runner within 15 minutes, with peak memory below 6 GB and no
    unexpected mapping failures. -- plan Gate 4

Stages, default mode
--------------------
=========================== ==============================================
generate                    synthetic FHIR R4 JSON
render                      Agent 2: FHIR JSON -> SourceContext + FHIR RDF
materialize                 Agent 3's maps through Agent 4's pinned engine
keying + lineage + store     graph key, per-quad lineage, named graph load
provenance                  PROV-O emission for every run
shacl validation            SHACL over the accumulated semantic graph
owl reasoning               HermiT over the encounter graphs, in batches
=========================== ==============================================

``render`` and ``materialize`` are the two stages this benchmark lacked until
the composed pipeline existed. Without them the run contained no mapping, so
"no unexpected mapping failures" was unshowable and the number was a lower
bound on a path nobody runs.

``--synthetic-targets`` restores the old behaviour: the corpus generator emits
SULO target triples directly and both stages are skipped. That is not a Gate 4
result and the report says so -- it is for timing the host layers in isolation
and bisecting a regression to one stage.

Why reasoning is batched
------------------------
The PRO entailment is local to one encounter: the chain never crosses
resources. Reasoning over 10,000 resources as one ontology asks HermiT to do
global work that the semantics do not require, and it does not finish in any
useful time. ``--reason-batch`` sets the batch size, and ``--reason-sample``
measures a sample and extrapolates, with the report saying it extrapolated.
Both are honest instruments; neither softens the target.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict

from generator import SyntheticFhir, SyntheticResource, generate, generate_fhir
from harness import BenchmarkReport, Timer, describe_environment

from fhir_sulo.contracts import TransformStatus
from fhir_sulo.provenance import (
    ProvenanceEmitter,
    RunInputs,
    build_run_record,
    build_transform_result,
    from_engine_payload,
    result_lineage_report,
)
from fhir_sulo.store import NamedGraphStore

ACTIVITY_TIME = "2026-09-29T12:00:00Z"


def engine_payload_for(resource: SyntheticResource):
    """Stand in for Agent 4's driver output, in its documented shape.

    DR-301 probe 5: ``materializer.provenance[]`` is parallel to the emitted
    quads, each ``{quad, tc, predicate, src}``. Building it here means the
    benchmark measures the real cost of consuming it - a per-quad object, a
    length check, a text comparison and a classification - rather than
    pretending lineage is free.
    """
    variables = list(resource.pivot_variables)
    provenance = []
    for index, quad in enumerate(resource.quads):
        parts = quad.split(" ", 2)
        provenance.append(
            {
                "quad": quad,
                "tc": "%s/tc%d" % (resource.family, index),
                "predicate": parts[1] if len(parts) > 1 else "",
                "src": variables[index % len(variables)] if variables else "<const>",
                "frameIndex": 0,
            }
        )
    return from_engine_payload(
        {
            "quads": list(resource.quads),
            "provenance": provenance,
            "frameOrigins": [
                {"frameIndex": 0, "scope": resource.family,
                 "keyValues": [resource.resource_id]}
            ],
        }
    )


def run_inputs_for(resource: SyntheticResource) -> RunInputs:
    return RunInputs(
        source_canonical_url=resource.canonical_url,
        source_version_id=resource.version_id,
        source_json_digest=resource.json_digest,
        map_id="%s-r4" % resource.family,
        map_semantic_version="0.1.0",
        pairing_hash="sha256:pairing-%s" % resource.family,
        sulo_version="0.2.12",
        domain_ontology_version="unresolved:R1",
        terminology_snapshot="tx-2026-09-29",
        policy_version="unresolved:R2",
        engine_build="shex@1.0.0-alpha.33",
        renderer_id="fhir_sulo.ingest.fhir_rdf/0.1.0",
    )


def stage_pipeline(resources, report: BenchmarkReport):
    """Keying, lineage construction and named graph loading."""
    store = NamedGraphStore()
    records = []
    categories: Dict[str, int] = {}

    with Timer("keying+lineage+store", len(resources)) as timer:
        for resource in resources:
            inputs = run_inputs_for(resource)
            if resource.eligible:
                result = build_transform_result(
                    inputs,
                    status=TransformStatus.MAPPED,
                    engine_payload=engine_payload_for(resource),
                    pivot_variables=resource.pivot_variables,
                )
                record = build_run_record(
                    inputs,
                    status=TransformStatus.MAPPED,
                    quads=result.target_quads,
                    activity_time=ACTIVITY_TIME,
                )
            else:
                result = build_transform_result(
                    inputs,
                    status=TransformStatus.SOURCE_ONLY,
                    diagnostics=(resource.reason,),
                )
                record = build_run_record(
                    inputs, status=TransformStatus.SOURCE_ONLY,
                    activity_time=ACTIVITY_TIME,
                )
                categories[resource.reason] = categories.get(resource.reason, 0) + 1
            store.load(result, record)
            records.append((resource, result, record))
        timer.detail["current graphs"] = len(store.current)
        timer.detail["current triples"] = len(store.current_triples())
        timer.detail["state digest"] = store.state_digest()[:16]
    report.stages.append(timer.result)
    report.failure_categories.update(categories)
    return store, records


def stage_provenance(records, report: BenchmarkReport):
    with Timer("provenance", len(records)) as timer:
        emitter = ProvenanceEmitter()
        for resource, result, record in records:
            emitter.record_run(
                record,
                None,
                result_lineage_report(result, record) if result.target_quads else None,
                source_status=resource.source_status,
            )
        quads = emitter.quads()
        timer.detail["provenance quads"] = len(quads)
    report.stages.append(timer.result)


def stage_shacl(store, report: BenchmarkReport, *, strictness_name: str):
    from fhir_sulo.validation import shapes_check, strictness as strictness_mod

    strictness = strictness_mod.resolve(strictness_name)
    triples = store.current_triples()
    with Timer("shacl validation", len(triples)) as timer:
        graph_report = shapes_check.validate_graph("\n".join(triples), strictness)
        timer.detail["strictness"] = graph_report.strictness_label
        timer.detail["conforms"] = graph_report.conforms
        timer.detail["violations"] = len(graph_report.violations)
        timer.detail["report digest"] = graph_report.digest[:16]
        timer.detail["graph digest"] = graph_report.data_digest[:16]
        if not graph_report.conforms:
            for violation in graph_report.violations[:5]:
                print("  SHACL violation: %s" % violation, file=sys.stderr)
    report.stages.append(timer.result)
    if not graph_report.conforms:
        report.failure_categories["shacl violation"] = len(graph_report.violations)
    return graph_report


def stage_reasoning_over_store(store, report: BenchmarkReport, *, batch_size, sample):
    """HermiT over the encounter graphs, which are the ones with entailments.

    Reads the graphs out of the store rather than out of the corpus, so the
    same function serves both modes: in the real run these are the triples
    the maps emitted, in ``--synthetic-targets`` they are the generator's.
    Encounters are identified by their source URL, which the store records.
    """
    from fhir_sulo.validation import reasoning

    graphs = [
        g for g in store.current.values()
        if "/Encounter/" in g.source_canonical_url
    ]
    if not graphs:
        return
    measured = graphs[:sample] if sample and sample < len(graphs) else graphs
    extrapolated = len(measured) < len(graphs)

    with Timer("owl reasoning (HermiT)", len(graphs)) as timer:
        inferred_total = 0
        batches = 0
        with reasoning.RobotReasoner() as robot:
            timer.detail["reasoner backend"] = robot.backend
            timer.detail["reasoner"] = robot.reasoner
            timer.detail["exclude tautologies"] = robot.exclude_tautologies
            for start_index in range(0, len(measured), batch_size):
                chunk = measured[start_index:start_index + batch_size]
                quads = [q for graph in chunk for q in graph.quads]
                inferred = robot.materialize("\n".join(quads))
                inferred_total += len(inferred)
                batches += 1
        timer.detail["encounters in run"] = len(graphs)
        timer.detail["encounters measured"] = len(measured)
        timer.detail["batch size"] = batch_size
        timer.detail["batches"] = batches
        timer.detail["inferred triples"] = inferred_total
        if extrapolated:
            timer.detail["NOTE"] = (
                "measured %d of %d encounters; the stage time is the MEASURED "
                "time, not extrapolated" % (len(measured), len(graphs)))
    result = timer.result
    if extrapolated and result.seconds > 0:
        factor = len(graphs) / float(len(measured))
        result.detail["extrapolated full stage"] = "%.1f s (x%.1f)" % (
            result.seconds * factor, factor)
    report.stages.append(result)


def emit_batch(resources, path: str) -> None:
    """Write a batch manifest in the format fhir_sulo.store.cli documents.

    Lets an operator exercise the load/inspect/correct commands before Agents
    2, 3 and 4 have a pipeline that can produce one. The shape is the seam,
    not a convenience: if the real driver emits this, nothing downstream
    changes.
    """
    with open(path, "w", encoding="utf-8") as handle:
        for resource in resources:
            inputs = run_inputs_for(resource)
            entry = {
                "inputs": {
                    f.name: getattr(inputs, f.name)
                    for f in inputs.__dataclass_fields__.values()
                },
                "source_status": resource.source_status,
            }
            if resource.eligible:
                payload = engine_payload_for(resource)
                entry["status"] = "mapped"
                entry["quads"] = list(payload.quads)
                entry["pivot_variables"] = list(resource.pivot_variables)
                entry["engine_provenance"] = [
                    {"quad": p.quad, "tc": p.tc, "predicate": p.predicate,
                     "src": p.src, "frameIndex": p.frame_index}
                    for p in payload.provenance
                ]
                entry["frame_origins"] = [
                    {"frameIndex": o.frame_index, "scope": o.scope,
                     "keyValues": list(o.key_values)}
                    for o in payload.frame_origins
                ]
            else:
                entry["status"] = "source-only"
                entry["reason"] = resource.reason
            handle.write(json.dumps(entry, sort_keys=True) + "\n")



# ===========================================================================
# The real path: render, then materialize
# ===========================================================================


def stage_render(resources, report: BenchmarkReport, workdir):
    """Agent 2's ingest: FHIR JSON on disk -> SourceContext with FHIR RDF.

    Written to disk first because ``ingest_file`` takes a path, which is also
    what an operator's batch looks like. The write is inside the stage on
    purpose: serialising the corpus is work the real pipeline does too.
    """
    import json as _json
    from fhir_sulo.pipeline.services import source_context

    contexts = []
    failures: Dict[str, int] = {}
    with Timer("render", len(resources)) as timer:
        for item in resources:
            path = workdir / ("%s.json" % item.resource_id)
            path.write_text(_json.dumps(item.resource), encoding="utf-8")
            try:
                contexts.append((item, source_context(path)))
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                key = "render: %s" % type(exc).__name__
                failures[key] = failures.get(key, 0) + 1
                contexts.append((item, None))
        timer.detail["rendered"] = sum(1 for _i, c in contexts if c is not None)
        timer.detail["render failures"] = sum(failures.values())
        eligible = sum(
            1 for _i, c in contexts
            if c is not None and c.eligibility.value == "eligible"
        )
        timer.detail["eligible"] = eligible
        timer.detail["ineligible"] = len(resources) - eligible
    report.stages.append(timer.result)
    report.failure_categories.update(failures)
    return contexts


def stage_materialize(contexts, report: BenchmarkReport, *, quality_mode, repo_root):
    """Agent 3's maps through Agent 4's pinned engine, per resource."""
    from fhir_sulo.pipeline.compose import Pipeline

    pipelines = {}
    outcomes = []
    failures: Dict[str, int] = {}

    with Timer("materialize", len(contexts)) as timer:
        engine_build = None
        for item, context in contexts:
            if context is None:
                continue
            pipeline = pipelines.get(item.family)
            if pipeline is None:
                pipeline = Pipeline.for_family(
                    item.family, repo_root, quality_mode=quality_mode
                )
                pipelines[item.family] = pipeline
                if engine_build is None:
                    engine_build = pipeline.engine.build_id()
            try:
                outcome = pipeline.run_context(context)
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                key = "materialize: %s" % type(exc).__name__
                failures[key] = failures.get(key, 0) + 1
                continue
            outcomes.append(outcome)
            status = outcome.transform.status.value
            if status != "mapped":
                reason = (outcome.notes[0] if outcome.notes else status)
                failures[reason] = failures.get(reason, 0) + 1

        mapped = [o for o in outcomes if o.is_loadable]
        timer.detail["mapped"] = len(mapped)
        timer.detail["not mapped"] = len(outcomes) - len(mapped)
        timer.detail["target triples"] = sum(len(o.ntriples) for o in mapped)
        timer.detail["families"] = ", ".join(sorted(pipelines))
        timer.detail["engine build"] = engine_build or "n/a"
        timer.detail["quality mode"] = quality_mode
    report.stages.append(timer.result)
    report.failure_categories.update(failures)
    return outcomes


def stage_store_real(outcomes, report: BenchmarkReport, *, engine_build, policy_version):
    """Key, trace and load what the maps actually produced.

    Note on the two graph keys. ``PipelineOutcome.run_record()`` fills
    ``output_graph_key`` from ``engine.driver.graph_key``, which hashes four
    identity fields. The store's key (DR-601) hashes the twelve inputs that
    can change a triple, and the store refuses any record whose key does not
    recompute from its own fields - that check is what makes an archived
    correction verifiable. So the two are not interchangeable, and the record
    is rebuilt here from ``RunInputs`` exactly as ``store.cli load`` rebuilds
    it from the batch manifest. This is the supported path, not a workaround;
    it is flagged to Agents 1 and 4 because a caller reaching for
    ``run_record()`` and passing it straight to the store gets a
    ``StoreIntegrityError``, which is correct but unhelpful.
    """
    import dataclasses

    from fhir_sulo.contracts import CONTRACT_VERSION
    from fhir_sulo.provenance import RunInputs, build_run_record

    store = NamedGraphStore()
    records = []
    with Timer("keying+lineage+store", len(outcomes)) as timer:
        for outcome in outcomes:
            source = outcome.source
            transform = outcome.transform
            inputs = RunInputs(
                source_canonical_url=source.canonical_url,
                source_version_id=source.version_id,
                source_json_digest=source.source_json_digest,
                map_id=transform.map_id,
                map_semantic_version=transform.pairing_hash,
                pairing_hash=transform.pairing_hash,
                sulo_version="0.2.12",
                domain_ontology_version="unresolved:R1",
                terminology_snapshot=source.terminology_snapshot,
                policy_version=policy_version,
                engine_build=engine_build,
                renderer_id=source.renderer_id,
                contract_version=CONTRACT_VERSION,
            )
            record = build_run_record(
                inputs,
                status=transform.status,
                quads=transform.target_quads,
                activity_time=ACTIVITY_TIME,
            )
            # The pipeline's TransformResult carries the driver's key; the
            # store compares the two, so align it with the record's.
            aligned = dataclasses.replace(
                transform, output_graph_key=record.output_graph_key
            )
            store.load(aligned, record)
            records.append((outcome, aligned, record))
        timer.detail["current graphs"] = len(store.current)
        timer.detail["current triples"] = len(store.current_triples())
        timer.detail["state digest"] = store.state_digest()[:16]
    report.stages.append(timer.result)
    return store, records


def stage_provenance_real(records, report: BenchmarkReport):
    from fhir_sulo.provenance import lineage_report as _lineage_report

    with Timer("provenance", len(records)) as timer:
        emitter = ProvenanceEmitter()
        for outcome, transform, record in records:
            lineage = None
            if transform.target_quads:
                lineage = _lineage_report(
                    transform.lineage, transform.target_quads, record
                )
            emitter.record_run(
                record, None, lineage,
                source_status=outcome.source.source_status,
            )
        timer.detail["provenance quads"] = len(emitter.quads())
    report.stages.append(timer.result)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", "--resources", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260929)
    parser.add_argument(
        "--strictness", required=True,
        choices=["concept-note-literal", "closed-world-complete", "from-policy"],
        help=("REQUIRED. Review item R5 is open and has no default, so every "
              "benchmark report names the strictness it ran under. "
              "'from-policy' uses the reviewer's recorded answer and fails "
              "while it is unset."))
    parser.add_argument("--skip-shacl", action="store_true")
    parser.add_argument("--skip-reasoning", action="store_true")
    parser.add_argument("--reason-batch", type=int, default=50,
                        help="encounters per reasoner invocation")
    parser.add_argument("--reason-sample", type=int, default=0,
                        help="measure only this many encounters and extrapolate")
    parser.add_argument("--json", metavar="PATH", help="also write the report as JSON")
    parser.add_argument("--emit-batch", metavar="PATH",
                        help="write a batch manifest for fhir_sulo.store.cli and exit")
    parser.add_argument(
        "--synthetic-targets", action="store_true",
        help=("skip render and materialize; the corpus generator emits SULO "
              "target triples directly. NOT a Gate 4 result -- for timing the "
              "host layers in isolation and bisecting a regression."))
    parser.add_argument(
        "--quality-mode", default="per-observation",
        choices=["per-observation", "persistent-per-person-code"],
        help=("review item R2. Required by the pipeline because the shipped "
              "policy default rejects every quality request; recorded in the "
              "report so a run always says which answer produced it."))
    args = parser.parse_args(argv)

    report = BenchmarkReport(resources=args.resources)
    report.environment = describe_environment()
    report.environment["seed"] = args.seed
    report.environment["strictness"] = args.strictness
    report.environment["quality_mode"] = args.quality_mode
    report.environment["mode"] = (
        "synthetic-targets (no mapping)" if args.synthetic_targets
        else "real pipeline (render + materialize)")

    if args.synthetic_targets:
        with Timer("generate", args.resources) as timer:
            resources = list(generate(args.resources, seed=args.seed))
            timer.detail["target triples"] = sum(len(r.quads) for r in resources)
            for family in ("egfr", "bp", "encounter", "ineligible"):
                timer.detail[family] = sum(1 for r in resources if r.family == family)
        report.stages.append(timer.result)

        if args.emit_batch:
            emit_batch(resources, args.emit_batch)
            print("batch manifest for %d resources written to %s"
                  % (len(resources), args.emit_batch))
            return 0

        store, records = stage_pipeline(resources, report)
        stage_provenance(records, report)
    else:
        import shutil
        import tempfile
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[1]
        with Timer("generate", args.resources) as timer:
            resources = list(generate_fhir(args.resources, seed=args.seed))
            for family in ("egfr", "bp", "encounter"):
                timer.detail[family] = sum(
                    1 for r in resources if r.family == family and r.eligible)
            timer.detail["ineligible"] = sum(1 for r in resources if not r.eligible)
        report.stages.append(timer.result)

        workdir = Path(tempfile.mkdtemp(prefix="fhir-sulo-bench-"))
        try:
            contexts = stage_render(resources, report, workdir)
            outcomes = stage_materialize(
                contexts, report,
                quality_mode=args.quality_mode, repo_root=repo_root)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        from fhir_sulo.pipeline.compose import Pipeline
        from fhir_sulo.pipeline.services import policy_bundle

        engine_build = Pipeline.for_family(
            "egfr", repo_root, quality_mode=args.quality_mode).engine.build_id()
        policy = policy_bundle(args.quality_mode)
        store, records = stage_store_real(
            outcomes, report,
            engine_build=engine_build,
            policy_version=policy.policy_version)
        stage_provenance_real(records, report)

    if not args.skip_shacl:
        stage_shacl(store, report, strictness_name=args.strictness)
    if not args.skip_reasoning:
        stage_reasoning_over_store(store, report, batch_size=args.reason_batch,
                                   sample=args.reason_sample)

    print(report.text())
    if args.json:
        with open(args.json, "w") as handle:
            handle.write(report.json())
        print("\nJSON report written to %s" % args.json)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
