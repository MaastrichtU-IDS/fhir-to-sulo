"""Schema-pair linter tests.

Written the way ``tests/contracts`` is: these assert the *refusals*. Each
negative schema in ``tests/engine/schemas`` is a pair the pinned engine accepts
and then mishandles in silence, so a linter that stopped catching one would
hand the pilot a quietly wrong graph. The cases are named for the acceptance
matrix row they carry (CD-1): unbound variables, incompatible repetition
scopes, unknown Map functions.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import error_codes, load_pair  # noqa: E402

from fhir_sulo.contracts import (  # noqa: E402
    MapContract, PivotVariable, RepetitionScope, VariableType,
)
from fhir_sulo.engine.linter import (  # noqa: E402
    SchemaPairLintError, Severity, check_contract, lint_pair,
)


class TestCleanPairs(unittest.TestCase):
    """A correct pair must produce nothing at all, or the noise hides the signal."""

    def test_bp_pair_is_clean(self):
        report = lint_pair(*load_pair("ok-bp"))
        self.assertEqual(report.findings, (), report.render())
        self.assertTrue(report.ok)
        self.assertEqual(report.max_repetition_depth, 1)

    def test_decomposition_passes_are_clean(self):
        """DR-302's decomposition is only a resolution if it lints."""
        for case in ("ok-decomp-a", "ok-decomp-b"):
            with self.subTest(case=case):
                report = lint_pair(*load_pair(case))
                self.assertEqual(report.findings, (), report.render())
                self.assertLessEqual(report.max_repetition_depth, 1)

    def test_clean_pair_does_not_raise(self):
        lint_pair(*load_pair("ok-bp")).raise_for_status()


class TestUnboundVariables(unittest.TestCase):
    """Acceptance row obligation 1."""

    def test_unbound_target_variable_is_an_error(self):
        report = lint_pair(*load_pair("neg-unbound-variable"))
        self.assertIn("SP001", error_codes(report))
        self.assertFalse(report.ok)

    def test_the_message_names_the_variable_and_the_path(self):
        report = lint_pair(*load_pair("neg-unbound-variable"))
        finding = next(f for f in report.errors if f.code == "SP001")
        self.assertIn("componentSystem", finding.message)
        self.assertIn("hasMeasurement", finding.where)

    def test_a_static_variable_counts_as_bound(self):
        """staticVars are always readable and never consumed, so they bind."""
        source, target = load_pair("neg-unbound-variable")
        report = lint_pair(
            source, target,
            static_variables={"https://w3id.org/fhir-sulo/var#componentSystem": "ucum"},
        )
        self.assertNotIn("SP001", error_codes(report))
        self.assertTrue(report.ok, report.render())

    def test_it_fails_the_build(self):
        with self.assertRaises(SchemaPairLintError):
            lint_pair(*load_pair("neg-unbound-variable")).raise_for_status()


class TestRepetitionScopes(unittest.TestCase):
    """Acceptance row obligation 2, which is DR-302."""

    def test_two_levels_of_repetition_are_an_error(self):
        report = lint_pair(*load_pair("neg-nested-repetition"))
        self.assertIn("SP002", error_codes(report))
        self.assertEqual(report.max_repetition_depth, 2)

    def test_both_schemas_are_checked_not_just_the_target(self):
        """The source decides the binding tree; the target decides emission.
        A pair is only safe if neither side nests."""
        report = lint_pair(*load_pair("neg-nested-repetition"))
        schemas = {f.schema for f in report.errors if f.code == "SP002"}
        self.assertEqual(
            schemas,
            {"neg-nested-repetition/source", "neg-nested-repetition/target"},
        )

    def test_one_finding_per_offending_chain(self):
        """Every constraint below a nested repetition inherits the fault; the
        author has one thing to fix and should be told once per schema."""
        report = lint_pair(*load_pair("neg-nested-repetition"))
        self.assertEqual(len([f for f in report.errors if f.code == "SP002"]), 2)

    def test_optional_is_not_repetition(self):
        """`?` and `{0,1}` are optional, not repeating; DR-302 limits repetition."""
        from fhir_sulo.engine.shexj import is_repeating

        self.assertFalse(is_repeating({"min": 0, "max": 1}))
        self.assertFalse(is_repeating({}))
        self.assertTrue(is_repeating({"min": 0, "max": -1}))
        self.assertTrue(is_repeating({"min": 1, "max": 3}))


class TestUnknownMapFunctions(unittest.TestCase):
    """Acceptance row obligation 3, as CD-1 restates it.

    Both routes matter. Which one an author hits depends only on whether the
    argument they typed happens to contain a colon, and the engine is silent
    either way.
    """

    def test_id_with_a_colon_is_caught(self):
        report = lint_pair(*load_pair("neg-unknown-function"))
        self.assertIn("SP003", error_codes(report))

    def test_unknown_function_without_a_colon_is_caught(self):
        report = lint_pair(*load_pair("neg-unknown-function-no-colon"))
        self.assertIn("SP003", error_codes(report))
        finding = next(f for f in report.errors if f.code == "SP003")
        self.assertIn("skolemize", finding.message)

    def test_a_rejected_code_is_not_also_reported_as_unbound(self):
        """One fault, one finding: the garbage variable name is a symptom."""
        report = lint_pair(*load_pair("neg-unknown-function"))
        self.assertNotIn("SP001", error_codes(report))


class TestOtherSilentEngineBehaviours(unittest.TestCase):
    def test_map_on_a_shape_valued_target_constraint(self):
        report = lint_pair(*load_pair("neg-shaperef-map"))
        self.assertIn("SP004", error_codes(report))

    def test_the_same_annotation_in_the_source_is_fine(self):
        """It is how DR-302's decomposition binds its join key, so SP004 is
        target-only. ok-decomp-a proves the idiom lints clean."""
        report = lint_pair(*load_pair("ok-decomp-a"))
        self.assertNotIn("SP004", error_codes(report))

    def test_dangling_shape_reference(self):
        report = lint_pair(*load_pair("neg-dangling"))
        self.assertIn("SP007", error_codes(report))

    def test_cycle_in_the_target_schema(self):
        report = lint_pair(*load_pair("neg-cycle-target"))
        self.assertIn("SP005", error_codes(report))

    def test_linting_a_cyclic_schema_terminates(self):
        """A cycle is reported, not unrolled; this test exists because the
        walk would otherwise be the obvious place to hang."""
        report = lint_pair(*load_pair("neg-cycle-target"))
        self.assertTrue(report.findings)


class TestWarningsDoNotFailTheBuild(unittest.TestCase):
    def test_unused_source_variable_is_a_warning(self):
        source, target = load_pair("ok-bp")
        # drop one variable from the target's view by linting the target of a
        # pair that reads fewer variables than the source binds
        report = lint_pair(source, load_pair("ok-decomp-b")[1])
        self.assertTrue(any(f.code == "SP101" for f in report.warnings))
        self.assertTrue(
            all(f.severity is Severity.WARNING for f in report.findings
                if f.code == "SP101")
        )


def _contract(**overrides):
    base = dict(
        map_id="bp/0.1.0",
        semantic_version="0.1.0",
        pairing_hash="sha256:test",
        source_release="R4",
        source_profiles=("http://hl7.org/fhir/StructureDefinition/bp",),
        source_shape_label="BPObservation",
        target_shape_label="Panel",
        pivot_variables=tuple(
            PivotVariable(
                name="https://w3id.org/fhir-sulo/var#" + short,
                var_type=VariableType.STRING, required=True,
                source_element="Observation." + short, target_role=short,
            )
            for short in ("status", "subject", "effective",
                          "componentCode", "componentValue", "componentUnit")
        ),
        repetition_scopes=(
            RepetitionScope(
                name="component",
                key_variables=("https://w3id.org/fhir-sulo/var#componentCode",),
                member_variables=("https://w3id.org/fhir-sulo/var#componentValue",
                                  "https://w3id.org/fhir-sulo/var#componentUnit"),
            ),
        ),
        node_key_rules={"Panel": "source Observation IRI"},
        terminology_dependencies=("snomed",),
        status_eligibility=("final",),
        expected_failures=(),
        sulo_version="2024-01-01",
        fixture_references=("tests/engine/schemas/ok-bp",),
    )
    base.update(overrides)
    return MapContract(**base)


class TestContractCrossCheck(unittest.TestCase):
    """``MapContract.static_analysis_passed`` is a boolean someone could just
    set. This is what makes setting it honest."""

    def test_a_matching_contract_passes(self):
        check = check_contract(_contract(), *load_pair("ok-bp"))
        self.assertTrue(check.ok, check.render())

    def test_a_variable_the_schemas_do_not_use_is_caught(self):
        contract = _contract(pivot_variables=_contract().pivot_variables + (
            PivotVariable(name="https://w3id.org/fhir-sulo/var#ghost",
                          var_type=VariableType.STRING, required=False,
                          source_element="nowhere", target_role="nowhere"),
        ))
        check = check_contract(contract, *load_pair("ok-bp"))
        self.assertIn("SP201", {f.code for f in check.findings})
        self.assertFalse(check.ok)

    def test_a_variable_missing_from_the_contract_is_caught(self):
        # drop `status`, which no repetition scope references, so MapContract's
        # own guard does not reject the contract before the linter sees it
        contract = _contract(pivot_variables=_contract().pivot_variables[1:])
        check = check_contract(contract, *load_pair("ok-bp"))
        self.assertIn("SP202", {f.code for f in check.findings})
        self.assertFalse(check.ok)

    def test_more_than_one_declared_scope_is_refused(self):
        contract = _contract(repetition_scopes=(
            RepetitionScope(name="a", key_variables=("https://w3id.org/fhir-sulo/var#status",),
                            member_variables=()),
            RepetitionScope(name="b", key_variables=("https://w3id.org/fhir-sulo/var#subject",),
                            member_variables=()),
        ))
        check = check_contract(contract, *load_pair("ok-bp"))
        self.assertIn("SP204", {f.code for f in check.findings})


if __name__ == "__main__":
    unittest.main()


class TestRepetitionDepthCounting(unittest.TestCase):
    """Repetition nests through groups as well as through shape references.

    Written after the first implementation counted ``(:x .*)*`` as one level:
    a group that repeats and a constraint that repeats within it are two
    levels, and DR-302 forbids the pair. Counting it as one would have let the
    exact schema the gate exists for through.
    """

    @staticmethod
    def schema_with(expression, label="t"):
        from fhir_sulo.engine.shexj import Schema

        return Schema(
            raw={"type": "Schema", "start": "R", "shapes": [
                {"id": "R", "type": "ShapeDecl",
                 "shapeExpr": {"type": "Shape", "expression": expression}}]},
            prefixes={"p": "http://p/"}, label=label)

    @staticmethod
    def tc(predicate, **kw):
        return dict({"type": "TripleConstraint", "predicate": predicate}, **kw)

    def depth(self, expression):
        from fhir_sulo.engine.shexj import walk_paths

        paths, _, _ = walk_paths(self.schema_with(expression))
        return max(p.repetition_count for p in paths)

    def test_plain_constraint_is_zero(self):
        self.assertEqual(self.depth(self.tc("p:v")), 0)

    def test_starred_constraint_is_one(self):
        self.assertEqual(self.depth(self.tc("p:v", min=0, max=-1)), 1)

    def test_bounded_repetition_counts(self):
        self.assertEqual(self.depth(self.tc("p:v", min=2, max=5)), 1)

    def test_repeating_group_around_plain_constraint_is_one(self):
        self.assertEqual(self.depth(
            {"type": "EachOf", "min": 0, "max": -1,
             "expressions": [self.tc("p:v")]}), 1)

    def test_repeating_group_around_repeating_constraint_is_two(self):
        self.assertEqual(self.depth(
            {"type": "EachOf", "min": 0, "max": -1,
             "expressions": [self.tc("p:v", min=0, max=-1)]}), 2)

    def test_two_nested_repeating_groups_is_two(self):
        self.assertEqual(self.depth(
            {"type": "EachOf", "min": 0, "max": -1, "expressions": [
                {"type": "EachOf", "min": 0, "max": -1,
                 "expressions": [self.tc("p:v")]}]}), 2)

    def test_the_linter_rejects_a_repeating_group_of_repeating_constraints(self):
        schema = self.schema_with(
            {"type": "EachOf", "min": 0, "max": -1,
             "expressions": [self.tc("p:v", min=0, max=-1)]})
        report = lint_pair(schema, schema)
        self.assertIn("SP002", error_codes(report))


class TestWalkTermination(unittest.TestCase):
    def test_a_diamond_is_not_a_cycle(self):
        """Two paths to one shape is sharing, not recursion. Reporting SP005
        here would make every realistic schema unlintable."""
        from fhir_sulo.engine.shexj import Schema, walk_paths

        schema = Schema(raw={"type": "Schema", "start": "R", "shapes": [
            {"id": "R", "type": "ShapeDecl", "shapeExpr": {"type": "Shape", "expression": {
                "type": "EachOf", "expressions": [
                    {"type": "TripleConstraint", "predicate": "p:a", "valueExpr": "L"},
                    {"type": "TripleConstraint", "predicate": "p:b", "valueExpr": "L"}]}}},
            {"id": "L", "type": "ShapeDecl", "shapeExpr": {"type": "Shape", "expression":
                {"type": "TripleConstraint", "predicate": "p:v"}}},
        ]}, prefixes={}, label="diamond")
        paths, cycles, dangling = walk_paths(schema)
        self.assertEqual(cycles, [])
        self.assertEqual(dangling, [])
        self.assertEqual(len(paths), 4)

    def test_self_reference_is_a_cycle_and_terminates(self):
        from fhir_sulo.engine.shexj import Schema, walk_paths

        schema = Schema(raw={"type": "Schema", "start": "A", "shapes": [
            {"id": "A", "type": "ShapeDecl", "shapeExpr": {"type": "Shape", "expression":
                {"type": "TripleConstraint", "predicate": "p:self", "valueExpr": "A"}}}]},
            prefixes={}, label="self")
        _, cycles, _ = walk_paths(schema)
        self.assertEqual([c.render() for c in cycles], ["A -> A"])

    def test_path_explosion_is_an_error_not_a_pass(self):
        """A partial analysis would read as a clean pair, which is the one
        outcome a build gate must never produce by accident."""
        from fhir_sulo.engine.shexj import Schema, SchemaTooLarge, walk_paths

        shapes, depth = [], 14
        for i in range(depth):
            nxt = f"S{i + 1}"
            shapes.append({"id": f"S{i}", "type": "ShapeDecl", "shapeExpr": {
                "type": "Shape", "expression": {"type": "EachOf", "expressions": [
                    {"type": "TripleConstraint", "predicate": "p:a", "valueExpr": nxt},
                    {"type": "TripleConstraint", "predicate": "p:b", "valueExpr": nxt}]}}})
        shapes.append({"id": f"S{depth}", "type": "ShapeDecl", "shapeExpr": {
            "type": "Shape", "expression":
                {"type": "TripleConstraint", "predicate": "p:leaf"}}})
        schema = Schema(raw={"type": "Schema", "start": "S0", "shapes": shapes},
                        prefixes={}, label="wide")
        with self.assertRaises(SchemaTooLarge):
            walk_paths(schema)
        report = lint_pair(schema, schema)
        self.assertIn("SP008", error_codes(report))
        self.assertFalse(report.ok)
