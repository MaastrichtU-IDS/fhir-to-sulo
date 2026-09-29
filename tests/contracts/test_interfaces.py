"""Gate 0 contract tests.

These assert the *guards*, not the happy path: each test constructs input that
violates a rule from the contract documents and requires the interface to
refuse it. A guard that cannot fail is not a guard.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from fhir_sulo.contracts import (  # noqa: E402
    BindingNode,
    EligibilityOutcome,
    MapContract,
    PivotVariable,
    QuadLineage,
    ReferenceEvidence,
    RepetitionScope,
    ResolvedReference,
    SourceContext,
    TransformResult,
    TransformStatus,
    VariableType,
)
from fhir_sulo.contracts.source_context import (  # noqa: E402
    AmbiguousReferenceError,
    UnresolvedReferenceError,
)


def _evidence(raw="Patient/p123"):
    return ReferenceEvidence(
        kind="literal",
        raw_reference=raw,
        resolved_target="https://fhir.example/" + raw,
        source_element="Observation.subject",
    )


class TestNoImplicitPersonClaim(unittest.TestCase):
    """Concept note section 2: a resolved reference is not a person."""

    def test_unresolved_reference_cannot_be_used_as_a_person(self):
        ref = ResolvedReference(evidence=_evidence())
        with self.assertRaises(UnresolvedReferenceError):
            ref.require_entity_iri()

    def test_ambiguous_reference_cannot_be_used_as_a_person(self):
        ref = ResolvedReference(
            evidence=_evidence(), entity_iri="https://ex/person-1", ambiguous=True,
            ambiguity_reason="two candidate patients",
        )
        # Even with an IRI present, ambiguity must win.
        with self.assertRaises(AmbiguousReferenceError):
            ref.require_entity_iri()

    def test_resolved_reference_returns_iri(self):
        ref = ResolvedReference(
            evidence=_evidence(), entity_iri="https://ex/person-1",
            identity_policy_version="identity/0.1.0",
        )
        self.assertEqual(ref.require_entity_iri(), "https://ex/person-1")


class TestEligibilityGuards(unittest.TestCase):
    def test_unsupported_modifier_extension_blocks_materialization(self):
        with self.assertRaises(ValueError):
            SourceContext(
                fhir_release="4.0.1", canonical_url="u", version_id="1",
                declared_profiles=(), validated_profiles=(), source_json_digest="d",
                rdf_graph="", rdf_content_type="text/turtle", source_status="final",
                resolved_references={}, terminology_snapshot="t",
                eligibility=EligibilityOutcome.ELIGIBLE,
                unsupported_modifier_extensions=("https://ex/mod",),
            )


class TestRepetitionScope(unittest.TestCase):
    """Concept note section 5: within-panel association must be representable."""

    def test_scope_without_key_is_refused(self):
        with self.assertRaises(ValueError):
            RepetitionScope(name="panel", key_variables=(), member_variables=("sys",))

    def test_bp_tuple_multiset_is_recoverable_from_binding_tree(self):
        tree = BindingNode(
            shape="Patient", focus="p123", bindings={},
            children=(
                BindingNode(
                    shape="Panel", focus="bp-1", scope="panel", iteration_key=("bp-1",),
                    bindings={"panel": "bp-1", "sys": "120", "dia": "80"},
                ),
                BindingNode(
                    shape="Panel", focus="bp-2", scope="panel", iteration_key=("bp-2",),
                    bindings={"panel": "bp-2", "sys": "105", "dia": "70"},
                ),
            ),
        )
        got = tree.tuples_for_scope("panel", ["panel", "sys", "dia"])
        self.assertEqual(
            sorted(got),
            sorted((("bp-1", "120", "80"), ("bp-2", "105", "70"))),
        )

    def test_cross_join_is_detected_as_a_different_multiset(self):
        """The failure the concept note names explicitly: (bp-1, 120, 70)."""
        crossed = BindingNode(
            shape="Patient", focus="p123", bindings={},
            children=(
                BindingNode(
                    shape="Panel", focus="bp-1", scope="panel", iteration_key=("bp-1",),
                    bindings={"panel": "bp-1", "sys": "120", "dia": "70"},
                ),
                BindingNode(
                    shape="Panel", focus="bp-2", scope="panel", iteration_key=("bp-2",),
                    bindings={"panel": "bp-2", "sys": "105", "dia": "80"},
                ),
            ),
        )
        got = sorted(crossed.tuples_for_scope("panel", ["panel", "sys", "dia"]))
        expected = sorted((("bp-1", "120", "80"), ("bp-2", "105", "70")))
        self.assertNotEqual(got, expected)


class TestMapContractValidation(unittest.TestCase):
    def _contract(self, **over):
        base = dict(
            map_id="egfr", semantic_version="0.1.0", pairing_hash="h",
            source_release="4.0.1", source_profiles=(), source_shape_label="S",
            target_shape_label="T",
            pivot_variables=(
                PivotVariable("value", VariableType.DECIMAL, True, "Observation.valueQuantity.value", "quantity value"),
            ),
            repetition_scopes=(), node_key_rules={}, terminology_dependencies=(),
            status_eligibility=("final",), expected_failures=(), sulo_version="0.2.12",
            fixture_references=(),
        )
        base.update(over)
        return MapContract(**base)

    def test_duplicate_pivot_variables_refused(self):
        with self.assertRaises(ValueError):
            self._contract(pivot_variables=(
                PivotVariable("v", VariableType.DECIMAL, True, "a", "b"),
                PivotVariable("v", VariableType.STRING, True, "c", "d"),
            ))

    def test_scope_referencing_undeclared_variable_refused(self):
        with self.assertRaises(ValueError):
            self._contract(repetition_scopes=(
                RepetitionScope("panel", ("nosuchvar",), ("value",)),
            ))

    def test_inverse_coverage_is_reported_not_assumed(self):
        c = self._contract(pivot_variables=(
            PivotVariable("a", VariableType.DECIMAL, True, "x", "y", inverse_covered=True),
            PivotVariable("b", VariableType.STRING, True, "x", "y", inverse_covered=False),
        ))
        self.assertEqual(c.inverse_coverage, 0.5)


class TestTransformResultGuards(unittest.TestCase):
    """Plan section 3: only mapped output may reach a clinical graph."""

    def test_source_only_result_cannot_carry_quads(self):
        with self.assertRaises(ValueError):
            TransformResult(
                status=TransformStatus.SOURCE_ONLY, map_id="egfr", pairing_hash="h",
                source_canonical_url="u", source_version_id="1", output_graph_key="k",
                target_quads=("<a> <b> <c> .",),
            )

    def test_rejected_result_cannot_carry_quads(self):
        with self.assertRaises(ValueError):
            TransformResult(
                status=TransformStatus.REJECTED, map_id="egfr", pairing_hash="h",
                source_canonical_url="u", source_version_id="1", output_graph_key="k",
                target_quads=("<a> <b> <c> .",), rejection_reason="entered-in-error",
            )

    def test_rejected_result_requires_a_reason(self):
        with self.assertRaises(ValueError):
            TransformResult(
                status=TransformStatus.REJECTED, map_id="egfr", pairing_hash="h",
                source_canonical_url="u", source_version_id="1", output_graph_key="k",
            )

    def test_quad_without_lineage_is_refused(self):
        with self.assertRaises(ValueError):
            TransformResult(
                status=TransformStatus.MAPPED, map_id="egfr", pairing_hash="h",
                source_canonical_url="u", source_version_id="1", output_graph_key="k",
                target_quads=("<a> <b> <c> .", "<d> <e> <f> ."),
                lineage=(QuadLineage(0, "binding", "value", "TC1"),),
            )

    def test_fully_traced_mapped_result_is_loadable(self):
        r = TransformResult(
            status=TransformStatus.MAPPED, map_id="egfr", pairing_hash="h",
            source_canonical_url="u", source_version_id="1", output_graph_key="k",
            target_quads=("<a> <b> <c> .",),
            lineage=(QuadLineage(0, "binding", "value", "TC1"),),
        )
        self.assertTrue(r.is_loadable)


if __name__ == "__main__":
    unittest.main(verbosity=2)
