"""Operator commands for the composed path: FHIR JSON in, a store batch out.

    python -m fhir_sulo.pipeline.cli map --family bp fixtures/r4/bp/bp-two-panels/bp-1.json
    python -m fhir_sulo.pipeline.cli batch --family bp --out batch.jsonl <files...>
    python -m fhir_sulo.pipeline.cli batch --family bp --out batch.jsonl --load store/

The batch file is the seam Agent 6's store already reads -- one JSON Lines
entry per transform. Until now its only producer was the synthetic benchmark
generator, which is why the operator guide told operators to practise on
synthetic output: nothing could turn a real FHIR resource into a batch. This
can.

A non-mapped resource is written too, with its reason and no quads. That is
not an omission: loading a ``source-only`` line retracts whatever graph the
store currently holds for that resource, which is how ``entered-in-error``
takes effect (concept note section 2). Skipping the line would leave the old
clinical assertions standing.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..contracts import CONTRACT_VERSION, TransformStatus
from ..engine.docker import EngineImage, EngineUnavailable, default_image
from .compose import Pipeline, PipelineOutcome
from .families import FAMILIES
from .manifest import discover

REPO_DEFAULT = Path(__file__).resolve().parents[3]


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def batch_entry(
    outcome: PipelineOutcome,
    engine_build: str,
    sulo_version: str,
    domain_ontology_version: str,
    policy_version: str,
) -> Dict[str, Any]:
    """One JSON Lines entry, in the shape ``fhir_sulo.store.cli load`` reads."""
    transform = outcome.transform
    source = outcome.source
    entry: Dict[str, Any] = {
        "inputs": {
            "source_canonical_url": source.canonical_url,
            "source_version_id": source.version_id,
            "source_json_digest": source.source_json_digest,
            "map_id": transform.map_id,
            "map_semantic_version": transform.pairing_hash,
            "pairing_hash": transform.pairing_hash,
            "sulo_version": sulo_version,
            "domain_ontology_version": domain_ontology_version,
            "terminology_snapshot": source.terminology_snapshot,
            "policy_version": policy_version,
            "engine_build": engine_build,
            "renderer_id": source.renderer_id,
            "contract_version": CONTRACT_VERSION,
        },
        "source_status": source.source_status,
        "status": transform.status.value,
    }
    if transform.status is not TransformStatus.MAPPED:
        entry["reason"] = (transform.rejection_reason
                           or (transform.diagnostics[0] if transform.diagnostics
                               else "not eligible"))
        return entry

    entry["quads"] = list(transform.target_quads)
    entry["pivot_variables"] = sorted({
        lineage.source_variable for lineage in transform.lineage
        if lineage.source_variable
    })
    entry["engine_provenance"] = [
        {"quad": transform.target_quads[lineage.quad_index],
         "tc": lineage.source_constraint,
         "predicate": _predicate_of(transform.target_quads[lineage.quad_index]),
         "src": lineage.produced_by,
         "frameIndex": _frame_of(lineage)}
        for lineage in transform.lineage
    ]
    entry["frame_origins"] = _frame_origins(outcome)
    return entry


def _predicate_of(ntriple: str) -> str:
    parts = ntriple.split(" ", 2)
    return parts[1] if len(parts) > 1 else ""


def _frame_of(lineage) -> Optional[int]:
    for part in lineage.iteration_key:
        if isinstance(part, str) and part.startswith("frame:"):
            tail = part.split(":", 1)[1]
            return int(tail) if tail.isdigit() else None
    return None


def _frame_origins(outcome: PipelineOutcome) -> List[Dict[str, Any]]:
    """One entry per iteration of the map's repetition scope.

    Taken from the binding tree the engine produced, not reconstructed: the
    scope name and key values are the ones `tuples_for_scope` reads, which is
    what makes the store's lineage answer the same question the acceptance
    matrix asks.
    """
    if outcome.run is None or outcome.run.result.driver_result.binding_tree is None:
        return []
    origins = []
    for index, child in enumerate(outcome.run.result.driver_result.binding_tree.children):
        origins.append({"frameIndex": index,
                        "scope": child.scope or "",
                        "keyValues": list(child.iteration_key)})
    return origins


def _resolve_engine(tag: Optional[str]) -> EngineImage:
    image = default_image(tag)
    image.ensure_built()
    return image


def _run_files(
    family: str, files: Sequence[Path], repo: Path, image: EngineImage,
    quality_mode: Optional[str],
) -> List[PipelineOutcome]:
    pipeline = Pipeline.for_family(family, repo, engine=image, quality_mode=quality_mode)
    return [pipeline.run_file(path) for path in files]


def cmd_map(args) -> int:
    image = _resolve_engine(args.image)
    outcomes = _run_files(args.family, [Path(p) for p in args.files],
                          Path(args.repo), image, args.quality_mode)
    for outcome in outcomes:
        print(f"{outcome.source.canonical_url}  {outcome.transform.status.value}"
              f"  {len(outcome.ntriples)} quad(s)"
              f"  graph={outcome.transform.output_graph_key}")
        for note in outcome.notes:
            print(f"    note: {note}")
        if args.show_quads:
            for line in sorted(outcome.ntriples):
                print("    " + line)
    return 0 if all(o.transform.status is not TransformStatus.REJECTED
                    for o in outcomes) else 1


def cmd_batch(args) -> int:
    image = _resolve_engine(args.image)
    build = image.build_id()
    outcomes = _run_files(args.family, [Path(p) for p in args.files],
                          Path(args.repo), image, args.quality_mode)
    out = Path(args.out)
    with out.open("w", encoding="utf-8") as handle:
        for outcome in outcomes:
            entry = batch_entry(
                outcome, engine_build=build, sulo_version=args.sulo_version,
                domain_ontology_version=args.domain_ontology_version,
                policy_version=args.policy_version)
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    mapped = sum(1 for o in outcomes if o.transform.status is TransformStatus.MAPPED)
    print(f"wrote {len(outcomes)} entry(ies) to {out} ({mapped} mapped)")

    if args.load:
        from ..store.cli import main as store_main

        load_dir = Path(args.load)
        load_dir.mkdir(parents=True, exist_ok=True)
        code = store_main([
            "load", "--batch", str(out),
            "--state", str(load_dir / "state.json"),
            "--provenance", str(load_dir / "provenance.nq"),
            "--graph", str(load_dir / "graph.nt"),
        ])
        if code != 0:
            return code
        print(f"loaded into {load_dir}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fhir_sulo.pipeline.cli",
        description=__doc__.splitlines()[0],
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--family", required=True, choices=sorted(FAMILIES),
                       help="which map family to apply")
        p.add_argument("--repo", default=str(REPO_DEFAULT),
                       help="repository root holding maps/")
        p.add_argument("--image", help="override the pinned engine image tag")
        p.add_argument("--quality-mode", default=None,
                       help="policy quality-identity mode; the shipped default "
                            "rejects every request, so a map that needs one "
                            "must name it (review item R2)")
        p.add_argument("files", nargs="+", help="FHIR JSON resource file(s)")

    run = sub.add_parser("map", help="map resources and print what came out")
    common(run)
    run.add_argument("--show-quads", action="store_true")
    run.set_defaults(func=cmd_map)

    batch = sub.add_parser("batch", help="write a store batch manifest")
    common(batch)
    batch.add_argument("--out", required=True, help="batch JSON Lines file to write")
    batch.add_argument("--load", metavar="DIR",
                       help="also load the batch into this store directory, "
                            "writing state.json, provenance.nq and graph.nt")
    batch.add_argument("--sulo-version", default="0.2.12")
    batch.add_argument("--domain-ontology-version", default="pilot-placeholder")
    batch.add_argument("--policy-version", default="policies/v1")
    batch.set_defaults(func=cmd_batch)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except EngineUnavailable as exc:
        print(f"engine unavailable: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
