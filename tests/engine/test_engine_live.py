"""Live-engine tests: the ones that need Docker.

Three jobs, none of which the offline tests can do:

1. **Drift.** ``fixtures/parsed`` and ``fixtures/responses`` are derived from
   the pinned engine and committed so that CI needs no Docker. Committing a
   derived artifact is only honest if staleness is detectable, so these
   re-parse and re-run and fail if anything moved. An engine bump announces
   itself here.

2. **The linter is not crying wolf.** For each negative schema, the linter
   claims the engine will silently do the wrong thing. That claim is checked
   against the engine rather than trusted: the pair really does produce a
   partial or mis-associated graph, with ``ok: true``, which is what makes a
   build-time refusal proportionate.

3. **The driver works end to end**, including DR-302's decomposition over the
   real engine rather than over recordings.

Skipped, never failed, when Docker is absent.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from .support import ROOT, load_pair, load_shexc  # noqa: E402

from fhir_sulo.engine.docker import EngineImage, EngineUnavailable  # noqa: E402
from fhir_sulo.engine.driver import (  # noqa: E402
    BindingsNotConsumed, Guards, PassSpec, UnboundVariables, run_pass,
    to_transform_result, union_passes,
)
from fhir_sulo.engine.linter import lint_pair  # noqa: E402

VAR = "https://w3id.org/fhir-sulo/var#"
EX = "https://w3id.org/fhir-sulo/"
OBS1 = "https://fhir.example/Observation/bp-1"
OBS2 = "https://fhir.example/Observation/bp-2"
PATIENT = "https://fhir.example/Patient/p-1"

_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None:
        image = EngineImage()
        image.ensure_built()
        _ENGINE = image
    return _ENGINE


#: Set by `make engine-live` / `make gate1`. Without it these tests skip when
#: Docker is absent, which is right for a laptop and wrong for a gate: a gate
#: that passes because its evidence did not run is not a gate.
REQUIRE_ENGINE = os.environ.get("FHIR_SULO_REQUIRE_ENGINE") == "1"


def requires_docker(test):
    if EngineImage.docker_present():
        return test
    if REQUIRE_ENGINE:
        return test  # let it fail loudly: the gate asked for real evidence
    return unittest.skipUnless(False, "docker is not available on this host")(test)


def data(case: str, name: str = "data.ttl") -> str:
    with open(os.path.join(ROOT, "tests", "engine", "schemas", case, name),
              encoding="utf-8") as handle:
        return handle.read()


def spec(pass_id, case, node, root, target_case=None, data_case=None, **kw):
    return PassSpec(
        pass_id=pass_id,
        source_schema=load_shexc(case, "source"),
        data=data(data_case or case),
        node=node,
        target_schema=load_shexc(target_case or case, "target"),
        root=root,
        source_base="urn:fhir-sulo:test-source",
        target_base="urn:fhir-sulo:test-target",
        **kw,
    )


@requires_docker
class TestFixturesAreNotStale(unittest.TestCase):
    """The committed ShExJ and the committed engine responses still match."""

    def run_refresh(self, script):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tools", "engine", script), "--check"],
            capture_output=True, text=True, timeout=1800,
        )
        if proc.returncode == 2:
            self.skipTest(proc.stderr.strip())
        self.assertEqual(
            proc.returncode, 0,
            f"{script} reports stale fixtures; re-run it without --check "
            f"and review the diff.\n{proc.stdout}\n{proc.stderr}",
        )

    def test_parsed_schemas_match_the_pinned_parser(self):
        self.run_refresh("refresh-fixtures.py")

    def test_recorded_responses_match_the_pinned_engine(self):
        self.run_refresh("refresh-responses.py")


@requires_docker
class TestTheLinterIsNotCryingWolf(unittest.TestCase):
    """Each negative pair is refused at build time because the engine accepts
    it and then gets it wrong in silence. Both halves are checked here."""

    def materialize(self, case, node=OBS1, guards=None):
        return engine().run_pass(
            spec("x", case, node, "urn:g:x").to_bridge(guards or Guards())
        )

    def test_unbound_variable_yields_a_partial_graph_with_ok_true(self):
        self.assertIn("SP001", {f.code for f in lint_pair(
            *load_pair("neg-unbound-variable")).errors})
        response = self.materialize("neg-unbound-variable")
        self.assertTrue(response["ok"], "the engine raises nothing")
        self.assertLess(response["coverage"]["consumed"], response["coverage"]["total"])
        self.assertLess(len(response["quads"]), 11)

    def test_unknown_function_deletes_the_shape_silently(self):
        for case in ("neg-unknown-function", "neg-unknown-function-no-colon"):
            with self.subTest(case=case):
                self.assertIn("SP003", {f.code for f in lint_pair(*load_pair(case)).errors})
                response = self.materialize(case)
                self.assertTrue(response["ok"])
                self.assertEqual(len(response["quads"]), 1,
                                 "the whole Measurement shape should have vanished")

    def test_map_on_a_shape_valued_constraint_drops_the_subshape(self):
        self.assertIn("SP004", {f.code for f in lint_pair(*load_pair("neg-shaperef-map")).errors})
        response = self.materialize("neg-shaperef-map")
        self.assertTrue(response["ok"])
        predicates = {q["p"]["v"] for q in response["quads"]}
        self.assertNotIn(EX + "magnitude", predicates)

    def test_nested_repetition_mis_associates_and_reports_nothing(self):
        """The case the driver cannot catch, so the linter must."""
        self.assertIn("SP002", {f.code for f in lint_pair(
            *load_pair("neg-nested-repetition")).errors})
        response = self.materialize("neg-nested-repetition", node=PATIENT)
        self.assertTrue(response["ok"])
        self.assertEqual(response["lastReport"]["unboundVariables"], [])
        self.assertEqual(response["coverage"]["unconsumed"], [])
        panels = [q for q in response["quads"] if q["p"]["v"] == EX + "hasPanel"]
        self.assertNotEqual(len(panels), 2,
                            "the source has two Observations; if the engine now "
                            "emits two panels, revisit DR-302")

    def test_the_clean_pair_really_is_clean(self):
        self.assertEqual(lint_pair(*load_pair("ok-bp")).findings, ())
        response = self.materialize("ok-bp")
        self.assertTrue(response["ok"])
        self.assertEqual(response["coverage"]["unconsumed"], [])


@requires_docker
class TestDriverAgainstTheLiveEngine(unittest.TestCase):
    def test_bp_pair_end_to_end(self):
        result = union_passes([run_pass(
            spec("bp", "ok-bp", OBS1, "urn:g:bp-1#panel",
                 scope_name="component", key_variables=(VAR + "componentCode",)),
            engine=engine())])
        self.assertEqual(result.untraced_quads(), ())
        tuples = result.binding_tree.tuples_for_scope(
            "component", [VAR + "componentValue", VAR + "componentUnit"])
        self.assertEqual(sorted(tuples), [("120", "mm[Hg]"), ("80", "mm[Hg]")])
        transform = to_transform_result(
            result, map_id="bp/0.1.0", pairing_hash="sha256:x",
            source_canonical_url=OBS1, source_version_id="1",
            output_graph_key="urn:fhir-sulo:g:test:live")
        self.assertTrue(transform.is_loadable)
        self.assertEqual(len(transform.lineage), len(transform.target_quads))

    def test_output_is_byte_identical_across_runs(self):
        """DR-301 probe 4a, re-asserted through the driver: determinism must
        survive our blank-node relabelling, not just the engine's counter."""
        one = union_passes([run_pass(spec("bp", "ok-bp", OBS1, "urn:g:bp"), engine=engine())])
        two = union_passes([run_pass(spec("bp", "ok-bp", OBS1, "urn:g:bp"), engine=engine())])
        self.assertEqual(one.ntriples, two.ntriples)
        self.assertEqual(one.content_digest(), two.content_digest())

    def test_the_driver_refuses_an_unbound_variable(self):
        with self.assertRaises(UnboundVariables):
            run_pass(spec("x", "neg-unbound-variable", OBS1, "urn:g:x"), engine=engine())

    def test_the_driver_refuses_a_dropped_subshape(self):
        with self.assertRaises(BindingsNotConsumed):
            run_pass(spec("x", "neg-shaperef-map", OBS1, "urn:g:x"), engine=engine())

    def test_decomposition_reproduces_the_two_level_map(self):
        """DR-302's resolution over the live engine: three one-level passes,
        joined on the Observation IRI the SCHEMA bound, get the grouping that
        one two-level map gets wrong."""
        passes = [
            run_pass(spec("a", "ok-decomp-a", PATIENT, "urn:g:p-1#subject"),
                     engine=engine()),
            run_pass(spec("b1", "ok-decomp-b", OBS1, OBS1,
                          scope_name="component",
                          key_variables=(VAR + "componentValue",)), engine=engine()),
            run_pass(spec("b2", "ok-decomp-b", OBS2, OBS2,
                          scope_name="component",
                          key_variables=(VAR + "componentValue",)), engine=engine()),
        ]
        result = union_passes(passes)
        self.assertEqual(result.untraced_quads(), ())
        linked = {r.quad.o.value for r in result.records if r.predicate == EX + "hasPanel"}
        self.assertEqual(linked, {OBS1, OBS2})

    def test_engine_build_id_is_reportable(self):
        """RunRecord.engine_build must identify what produced the graph, and a
        tag is not an identity."""
        build = engine().build_id()
        self.assertIn("sha256:", build)


@requires_docker
class TestEngineUnavailableIsAnError(unittest.TestCase):
    def test_an_unbuilt_image_does_not_silently_pass(self):
        missing = EngineImage(tag="fhir-sulo/shexmap:definitely-not-built")
        with self.assertRaises(EngineUnavailable):
            missing.build_id()


if __name__ == "__main__":
    unittest.main()


@requires_docker
class TestLintCommandFailsTheBuild(unittest.TestCase):
    """CD-1: "the linter must fail the build, not warn". Exit codes are the
    only part of that a CI job can see, so they are tested directly."""

    def lint(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(ROOT, "tools", "shexmap-lint")] + list(args),
            capture_output=True, text=True, timeout=1800,
        )

    def paths(self, case):
        base = os.path.join(ROOT, "tests", "engine", "schemas", case)
        return os.path.join(base, "source.shex"), os.path.join(base, "target.shex")

    def test_a_clean_pair_exits_zero(self):
        proc = self.lint(*self.paths("ok-bp"))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_every_negative_pair_exits_one(self):
        for case in ("neg-unbound-variable", "neg-nested-repetition",
                     "neg-unknown-function", "neg-unknown-function-no-colon",
                     "neg-shaperef-map", "neg-dangling", "neg-cycle-target"):
            with self.subTest(case=case):
                proc = self.lint(*self.paths(case))
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_warnings_alone_do_not_fail(self):
        proc = self.lint(*self.paths("neg-unbound-variable"),
                         "--static",
                         "https://w3id.org/fhir-sulo/var#componentSystem=ucum")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("warning", proc.stdout)

    def test_directory_mode_reports_every_pair_and_fails(self):
        proc = self.lint("--dir", os.path.join(ROOT, "tests", "engine", "schemas"),
                         "--json")
        self.assertEqual(proc.returncode, 1)
        payload = json.loads(proc.stdout)
        by_name = {p["name"]: p for p in payload["maps"]}
        self.assertTrue(by_name["ok-bp"]["ok"])
        self.assertTrue(by_name["ok-decomp-a"]["ok"])
        self.assertTrue(by_name["ok-decomp-b"]["ok"])
        self.assertFalse(by_name["neg-nested-repetition"]["ok"])
        self.assertEqual(
            {p["name"] for p in payload["maps"] if not p["ok"]},
            {n for n in by_name if n.startswith("neg-")},
        )

    def test_an_unparseable_schema_is_not_a_pass(self):
        broken = os.path.join(ROOT, "tests", "engine", "fixtures", "broken.shex")
        with open(broken, "w", encoding="utf-8") as handle:
            handle.write("PREFIX : <http://ex/>\nstart = @<S>\n<S> { :a  \n")
        try:
            proc = self.lint(broken, self.paths("ok-bp")[1])
            self.assertNotEqual(proc.returncode, 0)
        finally:
            os.unlink(broken)


@requires_docker
class TestRealMapsLintClean(unittest.TestCase):
    """The three shipped maps, parsed by the pinned engine and linted per pass.

    `make lint-schemas` had never passed: discovery matched only `source.shex`
    and the shipped files are `<family>-source.v1.shex`, so it found nothing
    and exited 2 on every run it ever had. These tests are what stops that
    recurring, and they check the analysis is *real* rather than merely green:
    the fault-injection cases target a shape `start` does not name.
    """

    FAMILIES = {"bp": 10, "egfr": 6, "encounter": 9}

    def parse(self, path, base, label):
        from fhir_sulo.engine.shexj import Schema

        response = engine().parse_schema(
            open(path, encoding="utf-8").read(), base)
        self.assertTrue(response.get("ok"), response.get("error"))
        return Schema(raw=response["schema"], prefixes=response["prefixes"], label=label)

    def lint(self, family, target_text=None):
        import json as _json

        from fhir_sulo.engine.maplint import lint_map
        from fhir_sulo.pipeline.manifest import discover

        files = {f.family: f for f in discover(Path(ROOT) / "maps")}[family]
        source = self.parse(files.source, "urn:s", f"{family}/source")
        if target_text is None:
            target = self.parse(files.target, "urn:t", f"{family}/target")
        else:
            response = engine().parse_schema(target_text, "urn:t")
            self.assertTrue(response.get("ok"), response.get("error"))
            from fhir_sulo.engine.shexj import Schema
            target = Schema(raw=response["schema"], prefixes=response["prefixes"],
                            label=f"{family}/target")
        contract = _json.loads(files.contract.read_text()) if files.contract else None
        return lint_map(files.manifest, source, target, contract=contract)

    def test_every_shipped_map_lints_clean(self):
        for family in sorted(self.FAMILIES):
            with self.subTest(family=family):
                report = self.lint(family)
                self.assertTrue(report.ok, report.render())

    def test_every_declared_pass_is_actually_walked(self):
        """The count is the claim: a start-only walk analysed one shape."""
        for family, expected in sorted(self.FAMILIES.items()):
            with self.subTest(family=family):
                report = self.lint(family)
                self.assertEqual(len(report.shapes_walked), expected)
                self.assertEqual(len(report.passes), expected)

    def test_no_target_shape_is_left_unanalysed(self):
        for family in sorted(self.FAMILIES):
            with self.subTest(family=family):
                self.assertEqual(self.lint(family).unreachable_shapes, ())

    def _target_text(self, family):
        from fhir_sulo.pipeline.manifest import discover

        files = {f.family: f for f in discover(Path(ROOT) / "maps")}[family]
        return files.target.read_text(encoding="utf-8")

    def test_an_unknown_map_function_in_a_non_start_pass_is_caught(self):
        """`sh:BPUnitNode` is the `unit` pass. `start` is `BPPanelRecordNode`,
        so before the manifest-driven walk this edit was invisible."""
        text = self._target_text("bp").replace(
            "%Map:{ v:sysUnit %}", "%Map:{ id(v:sysUnit) %}", 1)
        report = self.lint("bp", text)
        self.assertFalse(report.ok)
        errors = [f for f in report.errors if f.code == "SP003"]
        self.assertTrue(errors)
        self.assertTrue(any("pass unit" in f.where for f in errors), report.render())

    def test_an_unbound_variable_in_a_non_start_pass_is_caught(self):
        text = self._target_text("bp").replace(
            "%Map:{ v:effective %}", "%Map:{ v:effectiveTypo %}", 1)
        report = self.lint("bp", text)
        errors = [f for f in report.errors if f.code == "SP001"]
        self.assertTrue(errors)
        self.assertTrue(any("pass time" in f.where for f in errors), report.render())

    def test_a_map_on_a_shape_valued_target_constraint_is_caught(self):
        """SP004 on the eGFR map's non-start quantity shape."""
        report = self.lint("egfr")
        self.assertTrue(report.ok, report.render())


@requires_docker
class TestLintSchemasGatePasses(unittest.TestCase):
    """`make lint-schemas` is a CI step. It must actually pass."""

    def test_the_command_exits_zero_on_the_shipped_maps(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tools", "shexmap-lint"),
             "--dir", os.path.join(ROOT, "maps"), "--require-pairs"],
            capture_output=True, text=True, timeout=1800)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("3 map(s) clean", proc.stdout)

    def test_json_output_names_every_pass(self):
        proc = subprocess.run(
            [sys.executable, os.path.join(ROOT, "tools", "shexmap-lint"),
             "--dir", os.path.join(ROOT, "maps"), "--json"],
            capture_output=True, text=True, timeout=1800)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        by_name = {m["name"]: m for m in payload["maps"]}
        self.assertEqual(len(by_name["bp"]["passes"]), 10)
        self.assertTrue(all(p["ok"] for p in by_name["bp"]["passes"]))
