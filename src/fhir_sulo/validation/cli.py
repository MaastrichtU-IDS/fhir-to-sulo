"""Operator commands for target validation, reasoning and competency queries.

The "check" half of the operator interface; ``fhir_sulo.store.cli`` is the
"inspect and correct" half.

    python -m fhir_sulo.validation.cli reasoner-check
    python -m fhir_sulo.validation.cli shapes   --graph current.nt
    python -m fhir_sulo.validation.cli reason   --graph current.nt -o reasoned.ttl
    python -m fhir_sulo.validation.cli queries  --graph reasoned.ttl --reasoned

``reasoner-check`` runs first in the operator guide, and deliberately so: it
is the only command that tells you whether the OWL reasoner configured on
this machine can perform the entailment the pilot depends on. Everything
downstream is meaningless if it cannot, and it fails quietly if you do not
ask.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import queries as queries_mod
from . import reasoning, shapes_check, strictness

STRICTNESS = {
    "literal": strictness.CONCEPT_NOTE_LITERAL,
    "r5-a": strictness.R5_OPTION_A,
    "r5-b": strictness.R5_OPTION_B,
}


def _load(path: str):
    import rdflib

    graph = rdflib.Graph()
    fmt = {
        ".ttl": "turtle", ".nt": "nt", ".nq": "nquads",
        ".n3": "n3", ".jsonld": "json-ld", ".rdf": "xml",
    }.get(path[path.rfind("."):].lower(), "turtle")
    graph.parse(path, format=fmt)
    return graph


def cmd_reasoner_check(args) -> int:
    """Does the configured reasoner perform the SULO PRO chain entailment?"""
    try:
        verification = reasoning.verify_property_chain_support(args.reasoner)
    except reasoning.ReasonerUnavailable as exc:
        print("REASONER UNAVAILABLE: %s" % exc, file=sys.stderr)
        return 2
    print(verification.report())
    if not verification.usable:
        print(
            "\nThis reasoner CANNOT perform "
            "`hasParticipant o inverseOf(hasFeature) -> hasParticipant`.\n"
            "A property chain containing an inverse needs OWL 2 DL. ELK is EL and\n"
            "silently entails nothing here. Use HermiT (the default).",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_shapes(args) -> int:
    report = shapes_check.validate_graph(_load(args.graph), STRICTNESS[args.strictness])
    print("strictness   %s" % report.strictness_label)
    print("modules      %s" % ", ".join(report.shape_modules))
    print("result       %s" % report.summary())
    print("digest       %s" % report.digest)
    if not report.conforms:
        print("")
        for violation in report.violations:
            print("  %s" % violation)
        return 1
    return 0


def cmd_reason(args) -> int:
    try:
        with reasoning.RobotReasoner(reasoner=args.reasoner) as robot:
            print("backend      %s" % robot.backend, file=sys.stderr)
            asserted = _load(args.graph)
            consistency = robot.check_consistency(asserted)
            print("consistency  %s%s"
                  % ("consistent" if consistency.consistent else "INCONSISTENT",
                     "" if consistency.consistent else " -- " + consistency.detail),
                  file=sys.stderr)
            if not consistency.consistent:
                return 1
            merged = robot.reason_and_merge(asserted)
    except reasoning.ReasonerUnavailable as exc:
        print("REASONER UNAVAILABLE: %s" % exc, file=sys.stderr)
        return 2
    print("asserted     %d triples" % len(asserted), file=sys.stderr)
    print("with entailments %d triples" % len(merged), file=sys.stderr)
    merged.serialize(args.output, format="turtle")
    print("written to   %s" % args.output, file=sys.stderr)
    return 0


def cmd_queries(args) -> int:
    graph = _load(args.graph)
    bindings = {}
    if args.person:
        bindings["CQ1-egfr-for-person"] = {"person": args.person}
    if args.systolic_class and args.diastolic_class:
        bindings["CQ2-bp-pair-per-time"] = {
            "systolicClass": args.systolic_class,
            "diastolicClass": args.diastolic_class,
        }
    report = queries_mod.run_suite(graph, reasoned=args.reasoned, bindings=bindings)
    for result in report.results:
        mark = "PASS" if result.passed else "FAIL"
        print("%-4s %-34s %d row(s)" % (mark, result.query_id, result.row_count))
        if result.note:
            print("       %s" % result.note)
        if args.rows and result.rows:
            print("       %s" % " | ".join(result.variables))
            for row in result.rows[: args.limit]:
                print("       %s" % " | ".join(row))
    print("")
    print(report.summary())
    print("digest %s" % report.digest)
    return 0 if report.passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m fhir_sulo.validation.cli",
        description="Validate, reason over and query a materialized SULO graph.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "reasoner-check",
        help="verify the OWL reasoner can do the SULO PRO chain (run this first)",
    )
    check.add_argument("--reasoner", default=reasoning.DEFAULT_REASONER)
    check.set_defaults(func=cmd_reasoner_check)

    shapes = subparsers.add_parser("shapes", help="SHACL target shape validation")
    shapes.add_argument("--graph", required=True)
    shapes.add_argument("--strictness", default="literal", choices=sorted(STRICTNESS),
                        help="R5 switch; 'literal' is the default and R5 is OPEN")
    shapes.set_defaults(func=cmd_shapes)

    reason = subparsers.add_parser(
        "reason", help="check consistency and write the graph plus its entailments"
    )
    reason.add_argument("--graph", required=True)
    reason.add_argument("-o", "--output", default="reasoned.ttl")
    reason.add_argument("--reasoner", default=reasoning.DEFAULT_REASONER)
    reason.set_defaults(func=cmd_reason)

    query = subparsers.add_parser("queries", help="competency and negative queries")
    query.add_argument("--graph", required=True)
    query.add_argument("--reasoned", action="store_true",
                       help="the graph already carries OWL entailments")
    query.add_argument("--person", help="bind CQ1 to one person IRI")
    query.add_argument("--systolic-class", help="CQ2: the systolic quality class (R1)")
    query.add_argument("--diastolic-class", help="CQ2: the diastolic quality class (R1)")
    query.add_argument("--rows", action="store_true", help="print result rows")
    query.add_argument("--limit", type=int, default=20)
    query.set_defaults(func=cmd_queries)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
