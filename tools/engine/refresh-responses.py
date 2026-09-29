#!/usr/bin/env python3
"""Record real engine responses so the driver's rules can be tested without Docker.

The driver's value is entirely in what it refuses. Those refusals must be
tested, and testing them against invented JSON would be testing the test. So
every fixture here is a *recorded* response from the pinned engine on a
committed schema pair and a committed graph -- including the responses where
the engine quietly does the wrong thing, which are the ones that matter.

`tests/engine/test_driver_docker.py` re-runs the same cases against the live
engine and fails if a recording has gone stale.

Usage:  python3 tools/engine/refresh-responses.py [--check]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fhir_sulo.engine.docker import EngineImage, EngineUnavailable  # noqa: E402
from fhir_sulo.engine.driver import Guards, PassSpec  # noqa: E402

SCHEMAS = os.path.join(ROOT, "tests", "engine", "schemas")
OUT = os.path.join(ROOT, "tests", "engine", "fixtures", "responses")

OBS1 = "https://fhir.example/Observation/bp-1"
OBS2 = "https://fhir.example/Observation/bp-2"
PATIENT = "https://fhir.example/Patient/p-1"
VAR = "https://w3id.org/fhir-sulo/var#"


def read(case: str, name: str) -> str:
    with open(os.path.join(SCHEMAS, case, name), encoding="utf-8") as handle:
        return handle.read()


def spec(
    name: str, case: str, node: str, root: str,
    data_file: str = "data.ttl", source_case=None, target_case=None, **kw
) -> PassSpec:
    return PassSpec(
        pass_id=name,
        source_schema=read(source_case or case, "source.shex"),
        data=read(case, data_file),
        node=node,
        target_schema=read(target_case or case, "target.shex"),
        root=root,
        source_base="urn:fhir-sulo:test-source",
        target_base="urn:fhir-sulo:test-target",
        **kw,
    )


def big_component_graph(n: int) -> str:
    """One Observation with ``n`` components, for the DR-301 B2 truncation."""
    head = [
        "PREFIX fhir: <http://hl7.org/fhir/>",
        "PREFIX sct:  <http://snomed.info/id/>",
        "PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>",
        f"<{OBS1}> fhir:status \"final\" ; fhir:subject <{PATIENT}> ;",
        '  fhir:effective "2026-03-04T09:15:00Z"^^xsd:dateTime ;',
        "  fhir:component " + ", ".join(f"<{OBS1}#c{i}>" for i in range(n)) + " .",
    ]
    for i in range(n):
        head.append(
            f"<{OBS1}#c{i}> fhir:code sct:{100000 + i} ; "
            f'fhir:value "{100 + i}"^^xsd:decimal ; fhir:unit "mm[Hg]" .'
        )
    return "\n".join(head) + "\n"


def cases():
    """(fixture name, PassSpec, Guards). Recorded exactly as the driver sends them."""
    default = Guards()
    scope = dict(scope_name="component", key_variables=(VAR + "componentCode",))

    yield "ok-bp", spec("bp", "ok-bp", OBS1, "urn:g:bp-1#panel", **scope), default
    yield ("ok-bp-permuted",
           spec("bp", "ok-bp", OBS1, "urn:g:bp-1#panel",
                data_file="data-permuted.ttl", **scope), default)

    # the DR-302 decomposition, end to end
    yield ("decomp-pass-a",
           spec("a", "ok-decomp-a", PATIENT, "urn:g:p-1#subject",
                scope_name="panel", key_variables=(VAR + "panelIri",)), default)
    inner = dict(scope_name="component",
                 key_variables=(VAR + "componentValue",))
    yield "decomp-pass-b1", spec("b1", "ok-decomp-b", OBS1, OBS1, **inner), default
    yield "decomp-pass-b2", spec("b2", "ok-decomp-b", OBS2, OBS2, **inner), default

    # every silent failure the linter exists to prevent
    yield ("neg-unbound-variable",
           spec("x", "neg-unbound-variable", OBS1, "urn:g:x"), default)
    yield ("neg-unknown-function",
           spec("x", "neg-unknown-function", OBS1, "urn:g:x"), default)
    yield ("neg-unknown-function-no-colon",
           spec("x", "neg-unknown-function-no-colon", OBS1, "urn:g:x"), default)
    yield ("neg-shaperef-map",
           spec("x", "neg-shaperef-map", OBS1, "urn:g:x"), default)
    yield ("neg-nested-repetition",
           spec("x", "neg-nested-repetition", PATIENT, "urn:g:x"), default)
    yield ("neg-dangling", spec("x", "neg-dangling", OBS1, "urn:g:x"), default)

    # a source graph that does not conform at all
    bad = spec("x", "ok-bp", OBS1, "urn:g:x")
    yield ("source-invalid",
           PassSpec(**{**bad.__dict__,
                       "data": read("ok-bp", "data.ttl").replace(
                           '"120"^^xsd:decimal', '"one hundred twenty"')}),
           default)

    # DR-301 B2: 60 components under the ENGINE's own default ceiling of 20
    truncating = PassSpec(**{**spec("x", "ok-bp", OBS1, "urn:g:x", **scope).__dict__,
                             "data": big_component_graph(60)})
    yield "truncation-engine-defaults", truncating, Guards(
        max_accepts=20, max_repeat=50, max_steps=1_000_000,
        explore_steps=10_000, max_call_depth=50)
    yield "truncation-guards-raised", truncating, default


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    engine = EngineImage()
    try:
        engine.ensure_built()
    except EngineUnavailable as exc:
        print(f"engine unavailable: {exc}", file=sys.stderr)
        return 2

    os.makedirs(OUT, exist_ok=True)
    stale, written = [], []
    for name, pass_spec, guards in cases():
        response = engine.run_pass(pass_spec.to_bridge(guards))
        payload = json.dumps(response, indent=1, sort_keys=True) + "\n"
        path = os.path.join(OUT, f"{name}.json")
        existing = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                existing = handle.read()
        if existing == payload:
            continue
        if args.check:
            stale.append(name)
            continue
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(payload)
        written.append(name)

    if args.check:
        if stale:
            print("stale responses: " + ", ".join(stale), file=sys.stderr)
            return 1
        print("all recorded engine responses match the pinned engine")
        return 0
    print(f"refreshed {len(written)} response(s)" + (": " + ", ".join(written) if written else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
