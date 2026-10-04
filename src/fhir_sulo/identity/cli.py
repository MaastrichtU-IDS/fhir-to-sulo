"""Build a person-identifier index, and plan the migration it would cause.

    # one source
    python -m fhir_sulo.identity.cli build \
        --source maastricht-umc=/data/mumc/patients --out index.json

    # several, merged; scope keys the entries so they cannot collide
    python -m fhir_sulo.identity.cli build \
        --source maastricht-umc=/data/mumc \
        --source radboud-umc=/data/radboud --out index.json

    # what would enabling it do?
    python -m fhir_sulo.identity.cli plan --index index.json

``build`` refuses to write an index that would merge nobody unless asked, on
the grounds that an empty result usually means the allowlist is wrong rather
than that the data has no identifiers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..policy import PolicyBundle
from .person_index import PersonIdentifierIndex
from .rekey_report import plan_rekey


def allowlist_from_policy(policy=None):
    """Every accepted spelling -> its canonical one, from the reviewed policy.

    A mapping rather than a list, so a record carrying an alias is indexed
    under the canonical spelling and matches a record that arrived spelled
    the other way (DR-017).
    """
    from .service import IdentityService

    return dict(IdentityService(policy)._person_identifier_canonical_map())


def _parse_source(spec: str):
    if "=" not in spec:
        raise argparse.ArgumentTypeError(
            "--source wants SCOPE_ID=PATH, got %r. The scope id is not cosmetic: it keys "
            "the entries, and two systems sharing one would merge their patients." % spec)
    scope_id, path = spec.split("=", 1)
    if not scope_id.strip():
        raise argparse.ArgumentTypeError("--source has an empty scope id: %r" % spec)
    return scope_id.strip(), Path(path)


def cmd_build(args) -> int:
    allowlist = allowlist_from_policy()
    if not allowlist:
        print("no identifier system is allowlisted, so nothing can be indexed.\n"
              "Add one to person_identifying_identifier_systems with an interpretable "
              "status -- that is a reviewed decision (R8b).", file=sys.stderr)
        return 2

    index = PersonIdentifierIndex.empty()
    for scope_id, path in args.source:
        part = PersonIdentifierIndex.from_directory(
            path, scope_id=scope_id, allowlist=allowlist)
        print("  %-24s %4d person record(s)  <- %s" % (scope_id, len(part), path))
        index = index.merged_with(part)

    if not len(index) and not args.allow_empty:
        print("\nindexed nothing. Allowlisted systems were:\n  %s\n"
              "An empty index merges nobody, which is usually a wrong allowlist rather "
              "than data without identifiers. Pass --allow-empty to write it anyway."
              % "\n  ".join(allowlist), file=sys.stderr)
        return 1

    written = index.save(args.out)
    print("\nwrote %s\n  entries: %d\n  digest:  %s" % (args.out, len(index), written))
    print("\nRecord that digest with the run: two indexes give different entity IRIs for "
          "the same input.")
    return 0


def cmd_plan(args) -> int:
    index = PersonIdentifierIndex.load(args.index)
    records = [
        (scope_id, args.fhir_base, rtype, rid)
        for (scope_id, rtype, rid) in index.entries
    ]
    report = plan_rekey(records, index)
    print(report.summary())
    merges = report.merges
    if not merges:
        print("\nNothing collapses: every record keeps its own person.")
        return 0
    print("\nRecords that would become ONE person -- each line below is a claim that two "
          "records describe one human, and is the part to review:")
    for iri, rows in sorted(merges.items()):
        print("\n  %s" % iri)
        for row in sorted(rows, key=lambda r: (r.source_scope_id, r.resource_id)):
            print("    %-24s %s/%s" % (row.source_scope_id, row.resource_type, row.resource_id))
    print("\nEnabling this MOVES %d entity IRI(s). Graphs already written keep the old ones, "
          "so this is a graph migration, not a configuration change." % len(report.moved))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="fhir_sulo.identity.cli", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="index person identifiers from source resources")
    build.add_argument("--source", action="append", required=True, type=_parse_source,
                       metavar="SCOPE_ID=PATH",
                       help="one healthcare system: its scope id and a directory of "
                            "FHIR JSON resources or Bundles. Repeatable.")
    build.add_argument("--out", required=True, type=Path)
    build.add_argument("--allow-empty", action="store_true")
    build.set_defaults(func=cmd_build)

    plan = sub.add_parser("plan", help="report the re-keying an index would cause")
    plan.add_argument("--index", required=True, type=Path)
    plan.add_argument("--fhir-base", default="https://fhir.example/",
                      help="only used to build canonical URLs for the report")
    plan.set_defaults(func=cmd_plan)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
