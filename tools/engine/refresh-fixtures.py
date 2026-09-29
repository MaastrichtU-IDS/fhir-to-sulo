#!/usr/bin/env python3
"""Re-parse every test schema with the pinned engine and commit the ShExJ.

The linter analyses ShExJ. Parsing is the engine's job (`bridge/parse.js`), but
requiring Docker to run the linter's own unit tests would keep them out of CI,
so the parsed form is committed and the tests read that.

Committing a derived artifact is only safe if drift is detectable:
`tests/engine/test_linter_docker.py` re-parses and fails when a fixture no
longer matches, which is also how an engine bump announces itself.

Usage:  python3 tools/engine/refresh-fixtures.py [--check]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fhir_sulo.engine.docker import EngineImage, EngineUnavailable  # noqa: E402

SCHEMA_DIR = os.path.join(ROOT, "tests", "engine", "schemas")
FIXTURE_DIR = os.path.join(ROOT, "tests", "engine", "fixtures", "parsed")

#: Base IRIs are fixed here rather than derived from a path, so that a fixture
#: parsed on one machine is byte-identical to the same fixture parsed on
#: another. A file:// base would embed the checkout location in every label.
BASES = {"source": "urn:fhir-sulo:test-source", "target": "urn:fhir-sulo:test-target"}


def pairs():
    for name in sorted(os.listdir(SCHEMA_DIR)):
        directory = os.path.join(SCHEMA_DIR, name)
        if not os.path.isdir(directory):
            continue
        for role in ("source", "target"):
            path = os.path.join(directory, f"{role}.shex")
            if os.path.exists(path):
                yield name, role, path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="fail if any committed fixture is stale")
    args = ap.parse_args()

    engine = EngineImage()
    try:
        engine.ensure_built()
    except EngineUnavailable as exc:
        print(f"engine unavailable: {exc}", file=sys.stderr)
        return 2

    os.makedirs(FIXTURE_DIR, exist_ok=True)
    stale, written = [], []
    for name, role, path in pairs():
        with open(path, encoding="utf-8") as handle:
            shexc = handle.read()
        response = engine.parse_schema(shexc, BASES[role])
        if not response.get("ok"):
            print(f"FAIL {name}/{role}: {response.get('error')}", file=sys.stderr)
            return 1
        payload = json.dumps(
            {"schema": response["schema"], "prefixes": response["prefixes"]},
            indent=1, sort_keys=True,
        ) + "\n"
        out = os.path.join(FIXTURE_DIR, f"{name}.{role}.json")
        existing = None
        if os.path.exists(out):
            with open(out, encoding="utf-8") as handle:
                existing = handle.read()
        if existing == payload:
            continue
        if args.check:
            stale.append(f"{name}.{role}.json")
            continue
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(payload)
        written.append(f"{name}.{role}.json")

    if args.check:
        if stale:
            print("stale fixtures: " + ", ".join(stale), file=sys.stderr)
            return 1
        print("all parsed fixtures match the pinned engine")
        return 0
    print(f"refreshed {len(written)} fixture(s)" + (": " + ", ".join(written) if written else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
