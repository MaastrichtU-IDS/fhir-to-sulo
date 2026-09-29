"""Shared loading for the engine tests.

Schemas are read from committed ShExJ produced by the pinned engine's own
parser, so these tests need no Docker and run in CI. ``test_linter_docker.py``
is the one that re-parses and fails on drift.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))

PARSED = os.path.join(HERE, "fixtures", "parsed")
ENGINE_RESPONSES = os.path.join(HERE, "fixtures", "responses")
SCHEMAS = os.path.join(HERE, "schemas")

from fhir_sulo.engine.shexj import Schema  # noqa: E402


def load_parsed(case: str, role: str) -> Schema:
    with open(os.path.join(PARSED, f"{case}.{role}.json"), encoding="utf-8") as handle:
        payload = json.load(handle)
    return Schema(raw=payload["schema"], prefixes=payload["prefixes"],
                  label=f"{case}/{role}")


def load_pair(case: str):
    return load_parsed(case, "source"), load_parsed(case, "target")


def load_shexc(case: str, role: str) -> str:
    with open(os.path.join(SCHEMAS, case, f"{role}.shex"), encoding="utf-8") as handle:
        return handle.read()


def load_response(name: str):
    with open(os.path.join(ENGINE_RESPONSES, f"{name}.json"), encoding="utf-8") as handle:
        return json.load(handle)


def codes(report) -> set:
    return {f.code for f in report.findings}


def error_codes(report) -> set:
    return {f.code for f in report.errors}
