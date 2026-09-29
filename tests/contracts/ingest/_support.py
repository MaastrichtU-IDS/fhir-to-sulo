"""Shared fixture discovery for the ingestion contract tests."""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
FIXTURES = os.path.join(ROOT, "fixtures", "r4")
ORACLE = os.path.join(FIXTURES, "_oracle")

if os.path.join(ROOT, "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))


def cases():
    """Yield ``(case_dir, case_dict)`` for every fixture with a ``case.json``."""
    out = []
    for family in sorted(os.listdir(FIXTURES)):
        fdir = os.path.join(FIXTURES, family)
        if not os.path.isdir(fdir) or family.startswith("_"):
            continue
        for name in sorted(os.listdir(fdir)):
            cpath = os.path.join(fdir, name, "case.json")
            if os.path.isfile(cpath):
                with open(cpath, encoding="utf-8") as fh:
                    out.append((os.path.join(fdir, name), json.load(fh)))
    return out


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def source_files():
    """Yield ``(label, absolute_path)`` for every source JSON in every fixture."""
    seen = []
    for case_dir, case in cases():
        names = list(case["sources"])
        for variant in (case.get("variants") or {}).values():
            names.extend(variant.get("sources", ()))
        for name in names:
            seen.append((f"{os.path.basename(case_dir)}/{name}",
                         os.path.join(case_dir, name)))
    return seen
