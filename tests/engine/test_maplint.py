"""Manifest-driven linting: does the linter see every pass the runner runs?

The blood-pressure target declares ten root shapes and `start` names one of
them, because the engine has no `id()` and only a materialization's root node
has a controllable IRI. A `start`-only walk therefore left SP001, SP003 and
SP004 unchecked on nine of ten shapes -- and, worse, reported the other nine
passes' variables as unused, so its output was wrong rather than incomplete.

These tests are about that gap. The offline ones use synthetic ShExJ; the ones
that need the real schemas parsed are in `test_engine_live.py`.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fhir_sulo.engine.maplint import lint_map  # noqa: E402
from fhir_sulo.engine.shexj import Schema  # noqa: E402
from fhir_sulo.pipeline.manifest import (  # noqa: E402
    Manifest, ManifestError, MapFiles, discover, load_manifest_file,
)

REPO = Path(__file__).resolve().parents[2]
VAR = "https://ex.test/var#"
SHAPE = "https://ex.test/shape#"


def manifest(**overrides):
    raw = {
        "format": "fhir-sulo/map-run-bindings/0.1.0",
        "map_id": "test-map",
        "var_namespace": VAR,
        "shape_namespace": SHAPE,
        "domain_namespace": {"value": "https://ex.test/"},
        "vocabulary": {"klass": {"iri": "https://ex.test/Klass"}},
        "identity_provided": {"person": {}},
        "node_keys": {"recordNode": "{domain}rec-{obsId}"},
        "source_bound_vars": ["value", "obsId"],
        "passes": [
            {"name": "record", "shape": "RecordNode", "root": "recordNode",
             "vars": ["klass", "value"]},
            {"name": "person", "shape": "PersonNode", "root": "person",
             "vars": ["klass"]},
        ],
    }
    raw.update(overrides)
    return Manifest(family="test", path=Path("/tmp/test-bindings.json"), raw=raw)


def tc(predicate, code=None, value=None):
    node = {"type": "TripleConstraint", "predicate": predicate}
    if value:
        node["valueExpr"] = value
    if code:
        node["semActs"] = [{"type": "SemAct",
                            "name": "http://shex.io/extensions/Map/#", "code": code}]
    return node


def schema(shapes, start=None, label="t"):
    raw = {"type": "Schema", "shapes": [
        {"id": ident, "type": "ShapeDecl",
         "shapeExpr": {"type": "Shape", "expression": expr}}
        for ident, expr in shapes]}
    if start:
        raw["start"] = start
    return Schema(raw=raw, prefixes={"v": VAR, "sh": SHAPE}, label=label)


class TestManifest(unittest.TestCase):
    def test_static_variables_exclude_source_bound_ones(self):
        """A source-bound variable handed in as a static would be always
        available and never consumed -- a different thing entirely."""
        m = manifest()
        record = m.passes[0]
        self.assertEqual(m.static_variables_of(record), (VAR + "klass",))

    def test_conditional_passes_read_the_source_bindings(self):
        m = manifest(passes=[
            {"name": "dia", "shape": "D", "root": "recordNode", "vars": [],
             "requires_source_binding": "diaValue"},
            {"name": "nodia", "shape": "N", "root": "recordNode", "vars": [],
             "forbids_source_binding": "diaValue"},
        ])
        with_dia = {"diaValue": {"value": "80"}}
        without = {"diaValue": None}
        self.assertTrue(m.passes[0].runs_for(with_dia))
        self.assertFalse(m.passes[0].runs_for(without))
        self.assertFalse(m.passes[1].runs_for(with_dia))
        self.assertTrue(m.passes[1].runs_for(without))

    def test_node_keys_interpolate(self):
        self.assertEqual(manifest().node_keys(obsId="bp-1"),
                         {"recordNode": "https://ex.test/rec-bp-1"})

    def test_a_pass_variable_nothing_supplies_is_refused(self):
        with self.assertRaises(ManifestError):
            manifest(passes=[{"name": "p", "shape": "S", "root": "recordNode",
                              "vars": ["nobodySuppliesThis"]}]).validate()

    def test_a_pass_rooted_at_an_unknown_node_is_refused(self):
        with self.assertRaises(ManifestError):
            manifest(passes=[{"name": "p", "shape": "S", "root": "nowhere",
                              "vars": []}]).validate()

    def test_the_real_manifests_validate(self):
        for family in ("bp", "egfr", "encounter"):
            with self.subTest(family=family):
                path = REPO / "maps/r4" / family / f"{family}-bindings.v1.json"
                load_manifest_file(path, family).validate()


class TestDiscovery(unittest.TestCase):
    """The glob that shipped matched only `source.shex`, so `make
    lint-schemas` found nothing and exited 2 on every run it ever had."""

    def test_the_shipped_naming_is_found(self):
        families = {f.family: f for f in discover(REPO / "maps")}
        self.assertEqual(set(families), {"bp", "egfr", "encounter"})
        bp = families["bp"]
        self.assertEqual(bp.source.name, "bp-source.v1.shex")
        self.assertEqual(bp.target.name, "bp-target.v1.shex")
        self.assertEqual(bp.bindings.name, "bp-bindings.v1.json")
        self.assertEqual(bp.contract.name, "bp-map-contract.v1.json")

    def test_the_bare_layout_still_works(self):
        found = {f.family for f in discover(REPO / "tests/engine/schemas")}
        self.assertIn("ok-bp", found)

    def test_every_discovered_family_carries_a_manifest(self):
        for files in discover(REPO / "maps"):
            with self.subTest(family=files.family):
                self.assertIsNotNone(files.bindings, "would fall back to a start-only walk")


class TestEveryPassIsWalked(unittest.TestCase):
    def build(self):
        source = schema([("Src", {"type": "EachOf", "expressions": [
            tc("https://ex.test/value", " v:value "),
            tc("https://ex.test/obsId", " v:obsId "),
        ]})], start="Src", label="src")
        target = schema([
            (SHAPE + "RecordNode", {"type": "EachOf", "expressions": [
                tc("https://ex.test/type", " v:klass "),
                tc("https://ex.test/val", " v:value "),
            ]}),
            (SHAPE + "PersonNode", tc("https://ex.test/ptype", " v:klass ")),
        ], start=SHAPE + "RecordNode", label="tgt")
        return source, target

    def test_a_clean_map_is_clean(self):
        report = lint_map(manifest(), *self.build())
        self.assertTrue(report.ok, report.render())
        self.assertEqual(len(report.passes), 2)
        self.assertEqual(len(report.shapes_walked), 2)

    def test_a_fault_in_a_non_start_pass_is_caught(self):
        """The whole point. PersonNode is invisible to a start-only walk."""
        source, target = self.build()
        person = target.shape_exprs[SHAPE + "PersonNode"]
        person["expression"]["semActs"][0]["code"] = " v:neverBound "
        report = lint_map(manifest(), source, target)
        self.assertFalse(report.ok)
        codes = {f.code for f in report.errors}
        self.assertIn("SP001", codes)
        self.assertTrue(any("pass person" in f.where for f in report.errors))

    def test_an_unknown_map_function_in_a_non_start_pass_is_caught(self):
        source, target = self.build()
        person = target.shape_exprs[SHAPE + "PersonNode"]
        person["expression"]["semActs"][0]["code"] = " id(v:klass) "
        report = lint_map(manifest(), source, target)
        self.assertIn("SP003", {f.code for f in report.errors})

    def test_a_shape_no_pass_reaches_is_an_error(self):
        """An unreachable shape is an unlinted shape: nothing checks its Map
        codes, so CD-1's faults live there undetected."""
        source, target = self.build()
        target.shape_exprs[SHAPE + "Orphan"] = {
            "type": "Shape", "expression": tc("https://ex.test/x", " v:nope ")}
        report = lint_map(manifest(), source, target)
        self.assertIn("SP302", {f.code for f in report.errors})


class TestSourceVariableAccounting(unittest.TestCase):
    """SP101 must not call a host-consumed variable dead.

    `panel`, `versionId`, `subjectRef` and `status` feed node keys, the
    identity service and the eligibility guard. Reporting them as unread was
    the analysis being wrong, not merely incomplete.
    """

    def build_with_host_var(self):
        source = schema([("Src", {"type": "EachOf", "expressions": [
            tc("https://ex.test/value", " v:value "),
            tc("https://ex.test/obsId", " v:obsId "),
            tc("https://ex.test/subjectRef", " v:subjectRef "),
        ]})], start="Src", label="src")
        target = schema([
            (SHAPE + "RecordNode", {"type": "EachOf", "expressions": [
                tc("https://ex.test/type", " v:klass "),
                tc("https://ex.test/val", " v:value "),
            ]}),
            (SHAPE + "PersonNode", tc("https://ex.test/ptype", " v:klass ")),
        ], start=SHAPE + "RecordNode", label="tgt")
        return source, target

    def test_a_node_key_input_is_not_reported_as_dead(self):
        """`obsId` appears only in a node-key template, which the manifest
        declares, so the manifest alone is enough to account for it."""
        report = lint_map(manifest(), *self.build_with_host_var())
        dead = {f.where for f in report.warnings if f.code == "SP101"}
        self.assertNotIn(VAR + "obsId", dead)

    def test_a_declared_target_role_accounts_for_a_variable(self):
        contract = {"pivot_variables": [
            {"name": "subjectRef", "target_role": "identity service input"}]}
        report = lint_map(manifest(), *self.build_with_host_var(), contract=contract)
        self.assertEqual([f for f in report.warnings if f.code == "SP101"], [])

    def test_a_variable_nothing_accounts_for_is_still_reported(self):
        report = lint_map(manifest(), *self.build_with_host_var(), contract={})
        dead = {f.where for f in report.warnings if f.code == "SP101"}
        self.assertEqual(dead, {VAR + "subjectRef"})

    def test_a_contract_pivot_no_schema_uses_is_an_error(self):
        contract = {"pivot_variables": [{"name": "ghost", "target_role": "x"}]}
        report = lint_map(manifest(), *self.build_with_host_var(), contract=contract)
        self.assertIn("SP303", {f.code for f in report.errors})


if __name__ == "__main__":
    unittest.main()
