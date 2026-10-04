"""Operator commands for the output graph store.

    Definition of done: ... an operator can run and inspect a batch without
    editing code. -- plan section 8

This is the "inspect and correct" half; ``fhir_sulo.validation.cli`` is the
"check" half. Neither asks the operator to write Python.

The batch manifest
------------------
A batch is a JSON Lines file, one transform per line. It is the seam between
the pipeline (Agents 2, 3, 4) and this store, chosen so the two can be built
and tested independently, and so an operator can inspect, diff and replay a
batch as a file::

    {"inputs": {... the 12 graph-key fields ...},
     "status": "mapped",
     "source_status": "final",
     "quads": ["<s> <p> <o> .", ...],
     "engine_provenance": [{"quad": "...", "tc": "...", "src": "..."}],
     "frame_origins": [{"frameIndex": 0, "scope": "...", "keyValues": ["..."]}],
     "pivot_variables": ["egfr:value"]}

``status`` is ``mapped``, ``source-only`` or ``rejected``. A non-mapped line
carries ``reason`` instead of quads; loading it retracts any current graph for
that resource, which is how a correction to ``entered-in-error`` is applied.

``benchmarks/run_benchmark.py --emit-batch`` writes a synthetic one, so the
commands below can be exercised before the real pipeline exists.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from ..contracts import TransformStatus
from ..provenance import (
    ProvenanceEmitter,
    RunInputs,
    build_run_record,
    build_transform_result,
    from_engine_payload,
    result_lineage_report,
)
from .canonical import canonical_json
from .graph_key import CONTENT_FIELDS, GraphKeyInputs, graph_key, subject_key
from .graph_store import NamedGraphStore

STATUSES = {
    "mapped": TransformStatus.MAPPED,
    "source-only": TransformStatus.SOURCE_ONLY,
    "rejected": TransformStatus.REJECTED,
}


def _read_state(path: str) -> NamedGraphStore:
    if not path or not os.path.exists(path):
        return NamedGraphStore()
    with open(path, encoding="utf-8") as handle:
        return NamedGraphStore.from_state(json.load(handle))


def _write_state(store: NamedGraphStore, path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(canonical_json(store.to_state()))


def _lines(path: str):
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            line = line.strip()
            if line:
                yield number, json.loads(line)


def _apply(entry, store, emitter, activity_time):
    inputs = RunInputs(**entry["inputs"])
    status = STATUSES[entry.get("status", "mapped")]

    if status is TransformStatus.MAPPED:
        payload = from_engine_payload(
            {
                "quads": entry["quads"],
                "provenance": entry.get("engine_provenance") or [],
                "frameOrigins": entry.get("frame_origins") or [],
            }
        )
        result = build_transform_result(
            inputs, status=status, engine_payload=payload,
            pivot_variables=entry.get("pivot_variables"),
        )
    else:
        result = build_transform_result(
            inputs,
            status=status,
            diagnostics=(entry.get("reason", ""),) if entry.get("reason") else (),
            rejection_reason=(
                entry.get("reason") or "not eligible"
                if status is TransformStatus.REJECTED else None
            ),
        )

    record = build_run_record(
        inputs, status=status, quads=result.target_quads,
        activity_time=activity_time or None,
    )
    outcome = store.load(result, record)
    if emitter is not None:
        emitter.record_run(
            record,
            outcome,
            result_lineage_report(result, record) if result.target_quads else None,
            source_status=entry.get("source_status"),
        )
    return outcome


def cmd_load(args) -> int:
    store = _read_state(args.state)
    emitter = ProvenanceEmitter(emit_lineage_rdf=args.lineage_rdf)
    counts = {}
    failures: List[str] = []

    for number, entry in _lines(args.batch):
        try:
            outcome = _apply(entry, store, emitter, args.activity_time)
        except Exception as exc:  # noqa: BLE001 - see below
            # Deliberately broad. This is a per-line batch processor run by an
            # operator, and every failure mode it has - a malformed manifest, a
            # lineage array that does not match the quads, a store integrity
            # violation - is a fact about *that line* that the operator needs
            # reported with a line number. A traceback from line 4,000 of a
            # batch is not a usable report. The type name is kept so nothing is
            # disguised, and without --keep-going the batch still stops here.
            failures.append("line %d: %s: %s" % (number, type(exc).__name__, exc))
            if not args.keep_going:
                break
            continue
        name = outcome.action.value
        counts[name] = counts.get(name, 0) + 1

    for name in sorted(counts):
        print("%-14s %d" % (name, counts[name]))
    print("")
    for key, value in sorted(store.summary().items()):
        print("%-18s %s" % (key, value))

    if args.state:
        _write_state(store, args.state)
        print("\nstore state written to %s" % args.state)
    if args.provenance:
        with open(args.provenance, "w", encoding="utf-8") as handle:
            handle.write(emitter.nquads())
        print("provenance (N-Quads) written to %s" % args.provenance)
    if args.graph:
        with open(args.graph, "w", encoding="utf-8") as handle:
            handle.write("\n".join(store.current_triples()) + "\n")
        print("current semantic graph written to %s" % args.graph)

    if failures:
        print("\n%d FAILED line(s):" % len(failures), file=sys.stderr)
        for failure in failures:
            print("  " + failure, file=sys.stderr)
        return 1
    return 0


def cmd_inspect(args) -> int:
    store = _read_state(args.state)
    if args.subject:
        history = store.history(args.subject)
        if not history:
            print("no graphs for subject %s" % args.subject, file=sys.stderr)
            return 1
        print("history of %s" % args.subject)
        for graph in history:
            print("  %-10s v%-4s %s" % (graph.state.value, graph.source_version_id,
                                        graph.graph_key))
            print("             run   %s" % graph.generated_by_run_id)
            print("             quads %d" % len(graph.quads))
            if graph.state_reason:
                print("             why   %s" % graph.state_reason)
        return 0
    if args.graph_key:
        graph = store.graph(args.graph_key)
        if graph is None:
            print("no such graph: %s" % args.graph_key, file=sys.stderr)
            return 1
        print("graph        %s" % graph.graph_key)
        print("subject      %s" % graph.subject_key)
        print("source       %s version %s"
              % (graph.source_canonical_url, graph.source_version_id))
        print("state        %s%s"
              % (graph.state.value, " (%s)" % graph.state_reason if graph.state_reason else ""))
        print("generated by %s" % graph.generated_by_run_id)
        print("digest       %s" % graph.content_digest)
        if args.quads:
            print("")
            for quad in graph.quads:
                print(quad)
        return 0

    for key, value in sorted(store.summary().items()):
        print("%-18s %s" % (key, value))
    print("")
    print("subjects (%d)" % len(store.subjects()))
    for subject in store.subjects()[: args.limit]:
        current = store.current_graph_key(subject)
        versions = len(store.history(subject))
        print("  %s  versions=%d  current=%s"
              % (subject, versions, current or "RETRACTED"))
    return 0


def cmd_run(args) -> int:
    store = _read_state(args.state)
    record = store.runs.get(args.run_id)
    if record is None:
        print("no such run: %s" % args.run_id, file=sys.stderr)
        return 1
    for field in sorted(record.__dataclass_fields__):
        print("%-26s %s" % (field, getattr(record, field)))
    print("")
    print("--- PROV-O ---")
    from ..provenance import run_provenance_quads

    for quad in run_provenance_quads(record):
        print(quad)
    return 0


def cmd_verify(args) -> int:
    """Recompute every stored graph key from its own run record."""
    store = _read_state(args.state)
    from .graph_key import graph_key_from_run_record

    bad = []
    for record in store.runs.all():
        recomputed = graph_key_from_run_record(record)
        if recomputed != record.output_graph_key:
            bad.append((record.run_id, record.output_graph_key, recomputed))
    print("checked %d run records" % len(store.runs))
    if bad:
        print("\n%d run record(s) whose key does not match their own fields:" % len(bad))
        for run_id, stored, recomputed in bad:
            print("  %s\n    stored     %s\n    recomputed %s" % (run_id, stored, recomputed))
        return 1
    print("every graph key recomputes from its run record")
    print("state digest: %s" % store.state_digest())
    return 0


def cmd_key(args) -> int:
    if args.inputs:
        with open(args.inputs, encoding="utf-8") as handle:
            values = json.load(handle)
    else:
        values = {}
        for pair in args.set or ():
            name, _, value = pair.partition("=")
            values[name] = value
    missing = [f for f in CONTENT_FIELDS if f not in values]
    if missing:
        print("missing graph key inputs: %s" % ", ".join(missing), file=sys.stderr)
        print("\nthe key is a function of exactly these fields:", file=sys.stderr)
        for field in CONTENT_FIELDS:
            print("  " + field, file=sys.stderr)
        return 2
    inputs = GraphKeyInputs(**{f: values[f] for f in CONTENT_FIELDS})
    print("graph key   %s" % graph_key(inputs))
    print("subject key %s" % subject_key(inputs))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fhir_sulo.store.cli",
        description="Inspect and correct the FHIR-to-SULO output graph store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    load = subparsers.add_parser("load", help="apply a batch manifest to the store")
    load.add_argument("--batch", required=True, help="JSON Lines batch manifest")
    load.add_argument("--state", default="store-state.json")
    load.add_argument("--provenance", help="write PROV-O N-Quads here")
    load.add_argument("--graph", help="write the current semantic graph here (N-Triples)")
    load.add_argument("--activity-time", default=None,
                      help="fix the run timestamp, for reproducible runs")
    load.add_argument("--lineage-rdf", action="store_true",
                      help="also emit per-quad lineage as RDF (large)")
    load.add_argument("--keep-going", action="store_true",
                      help="continue past a failing line and report at the end")
    load.set_defaults(func=cmd_load)

    inspect = subparsers.add_parser("inspect", help="summarise the store")
    inspect.add_argument("--state", default="store-state.json")
    inspect.add_argument("--subject", help="show the version history of one subject key")
    inspect.add_argument("--graph-key", help="show one graph")
    inspect.add_argument("--quads", action="store_true", help="print the graph's triples")
    inspect.add_argument("--limit", type=int, default=20)
    inspect.set_defaults(func=cmd_inspect)

    run = subparsers.add_parser("run", help="show a run record and its PROV-O")
    run.add_argument("run_id")
    run.add_argument("--state", default="store-state.json")
    run.set_defaults(func=cmd_run)

    verify = subparsers.add_parser(
        "verify", help="recompute every graph key from its run record"
    )
    verify.add_argument("--state", default="store-state.json")
    verify.set_defaults(func=cmd_verify)

    key = subparsers.add_parser("key", help="compute a graph key from its inputs")
    key.add_argument("--inputs", help="JSON file with the 12 key fields")
    key.add_argument("--set", action="append", metavar="FIELD=VALUE")
    key.set_defaults(func=cmd_key)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
