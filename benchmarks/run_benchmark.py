"""Gate 4 scale trial: the host pipeline over N synthetic resources.

    The benchmark processes 10,000 synthetic resources on a documented
    4-vCPU/8-GB runner within 15 minutes, with peak memory below 6 GB and no
    unexpected mapping failures. -- plan Gate 4

Run it through ``benchmarks/run.sh``, which enforces the constraints. Running
it bare on the host measures the host, which is not the documented runner and
is not a Gate 4 result; the report says which of the two it was.

Stages
------
=========================== ==============================================
keying + lineage + store    graph key, per-quad lineage, named graph load
provenance                  PROV-O emission for every run
shape validation            SHACL over the accumulated semantic graph
owl reasoning               HermiT over the encounter graphs, in batches
=========================== ==============================================

The ShExMap engine is **not** in this run; it is measured separately by
``engine_bench/``, because it needs Node and because the maps it would run are
Agent 3's, which do not exist yet. ``README.md`` states the consequence
plainly: this is a lower bound on the end-to-end time, not the end-to-end
time.

Why reasoning is batched
------------------------
The PRO entailment is local to one encounter: the chain never crosses
resources. Reasoning over 10,000 resources as one ontology asks HermiT to do
global work that the semantics do not require, and it does not finish in any
useful time. ``--reason-batch`` sets the batch size, and
``--reason-sample`` measures a sample and extrapolates, with the report saying
it extrapolated. Both are honest instruments; neither softens the target.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict

from generator import SyntheticResource, generate
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

    strictness = getattr(strictness_mod, strictness_name)
    triples = store.current_triples()
    with Timer("shacl validation", len(triples)) as timer:
        graph_report = shapes_check.validate_graph("\n".join(triples), strictness)
        timer.detail["strictness"] = graph_report.strictness_label
        timer.detail["conforms"] = graph_report.conforms
        timer.detail["violations"] = len(graph_report.violations)
        timer.detail["report digest"] = graph_report.digest[:16]
        if not graph_report.conforms:
            for violation in graph_report.violations[:5]:
                print("  SHACL violation: %s" % violation, file=sys.stderr)
    report.stages.append(timer.result)
    if not graph_report.conforms:
        report.failure_categories["shacl violation"] = len(graph_report.violations)
    return graph_report


def stage_reasoning(resources, report: BenchmarkReport, *, batch_size: int, sample: int):
    """HermiT over the encounter graphs, which are the ones with entailments."""
    from fhir_sulo.validation import reasoning

    encounters = [r for r in resources if r.family == "encounter"]
    if not encounters:
        return
    measured = encounters[:sample] if sample and sample < len(encounters) else encounters
    extrapolated = len(measured) < len(encounters)

    with Timer("owl reasoning (HermiT)", len(encounters)) as timer:
        inferred_total = 0
        batches = 0
        with reasoning.RobotReasoner() as robot:
            timer.detail["reasoner backend"] = robot.backend
            timer.detail["reasoner"] = robot.reasoner
            timer.detail["exclude tautologies"] = robot.exclude_tautologies
            for start in range(0, len(measured), batch_size):
                chunk = measured[start:start + batch_size]
                quads = [q for resource in chunk for q in resource.quads]
                inferred = robot.materialize("\n".join(quads))
                inferred_total += len(inferred)
                batches += 1
        timer.detail["encounters in run"] = len(encounters)
        timer.detail["encounters measured"] = len(measured)
        timer.detail["batch size"] = batch_size
        timer.detail["batches"] = batches
        timer.detail["inferred triples"] = inferred_total
        if extrapolated:
            timer.detail["NOTE"] = (
                "measured %d of %d encounters; the stage time below is the MEASURED "
                "time, not extrapolated - see 'extrapolated full stage' for the "
                "projection" % (len(measured), len(encounters))
            )
    result = timer.result
    if extrapolated and result.seconds > 0:
        factor = len(encounters) / float(len(measured))
        result.detail["extrapolated full stage"] = "%.1f s (x%.1f)" % (
            result.seconds * factor, factor
        )
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", "--resources", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260929)
    parser.add_argument("--strictness", default="CONCEPT_NOTE_LITERAL",
                        choices=["CONCEPT_NOTE_LITERAL", "R5_OPTION_A", "R5_OPTION_B"])
    parser.add_argument("--skip-shacl", action="store_true")
    parser.add_argument("--skip-reasoning", action="store_true")
    parser.add_argument("--reason-batch", type=int, default=50,
                        help="encounters per reasoner invocation")
    parser.add_argument("--reason-sample", type=int, default=0,
                        help="measure only this many encounters and extrapolate")
    parser.add_argument("--json", metavar="PATH", help="also write the report as JSON")
    parser.add_argument("--emit-batch", metavar="PATH",
                        help="write a batch manifest for fhir_sulo.store.cli and exit")
    args = parser.parse_args(argv)

    report = BenchmarkReport(resources=args.resources)
    report.environment = describe_environment()
    report.environment["seed"] = args.seed
    report.environment["strictness"] = args.strictness

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
    if not args.skip_shacl:
        stage_shacl(store, report, strictness_name=args.strictness)
    if not args.skip_reasoning:
        stage_reasoning(resources, report,
                        batch_size=args.reason_batch, sample=args.reason_sample)

    print(report.text())
    if args.json:
        with open(args.json, "w") as handle:
            handle.write(report.json())
        print("\nJSON report written to %s" % args.json)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
