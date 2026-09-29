"""Target shape validation, and the R5 strictness switch.

Needs the pinned environment (``requirements-runtime.txt``); skipped with a
message rather than failing when rdflib/pyshacl are absent, because the
contract tests must still run on the bare system interpreter.
"""

from __future__ import annotations

import importlib.util
import unittest

from .support import graph_text  # noqa: F401  (sets sys.path)

from fhir_sulo.validation import shapes_check, strictness

# Probed with find_spec, not with a bare `import`: shapes_check imports rdflib
# and pyshacl lazily, so importing it proves nothing about whether they are
# installed, and a linter that removes an "unused" import would silently turn
# these skips into failures on a bare interpreter. That is exactly what
# happened once.
HAVE_SHACL = all(
    importlib.util.find_spec(name) is not None for name in ("rdflib", "pyshacl")
)

SKIP = "needs the pinned environment: .venv/bin/pip install -r requirements-runtime.txt"


class R5StaysOpen(unittest.TestCase):
    """The guard that stops the open review item being closed by accident."""

    def test_r5_is_not_marked_resolved(self):
        self.assertFalse(
            strictness.R5_RESOLVED,
            "R5 is an open clinical/ontology review item. Resolving it needs a "
            "reviewer answer and a decision record, not a constant change.",
        )

    def test_the_default_is_the_concept_notes_literal_graphs(self):
        default = strictness.CONCEPT_NOTE_LITERAL
        self.assertFalse(default.require_quantity_is_feature_of)
        self.assertFalse(default.require_time_unit)
        self.assertIn("R5 unanswered", default.label)

    def test_option_c_is_expressible_as_a_split(self):
        split = strictness.Strictness(require_time_unit=True)
        self.assertIn("option-C", split.label)
        self.assertIn("strict-time-unit.ttl", split.modules())
        self.assertNotIn("strict-quantity-isfeatureof.ttl", split.modules())


@unittest.skipUnless(HAVE_SHACL, SKIP)
class ConceptNoteGraphsConform(unittest.TestCase):
    """The default strictness validates exactly what the concept note writes."""

    def _check(self, name):
        report = shapes_check.validate_graph(
            graph_text(name), strictness.CONCEPT_NOTE_LITERAL
        )
        self.assertTrue(report.conforms, "%s: %s" % (name, report.text))
        return report

    def test_egfr_target_graph(self):
        self._check("egfr-target.ttl")

    def test_two_blood_pressure_panels(self):
        self._check("bp-two-panels.ttl")

    def test_two_panels_with_a_shared_persisting_quality(self):
        """R2 option A must validate too; the shapes do not prejudge it."""
        self._check("bp-two-panels-shared-quality.ttl")

    def test_pro_encounter(self):
        self._check("encounter-pro.ttl")

    def test_report_digest_is_stable_across_runs(self):
        a = self._check("egfr-target.ttl").digest
        b = self._check("egfr-target.ttl").digest
        self.assertEqual(a, b)


@unittest.skipUnless(HAVE_SHACL, SKIP)
class NegativeCasesAreRejected(unittest.TestCase):
    """If a change makes any of these conform, the change is wrong."""

    @classmethod
    def setUpClass(cls):
        cls.report = shapes_check.validate_graph(
            graph_text("negatives.ttl"), strictness.CONCEPT_NOTE_LITERAL
        )

    def _messages_for(self, fragment):
        return [v.message for v in self.report.violations if fragment in v.focus_node]

    def test_the_graph_does_not_conform(self):
        self.assertFalse(self.report.conforms)

    def test_an_orphan_unit_is_caught(self):
        self.assertTrue(any("orphan" in m for m in self._messages_for("orphan-unit")))

    def test_an_orphan_result_is_caught(self):
        self.assertTrue(any("orphan" in m for m in self._messages_for("orphan-result")))

    def test_a_cross_patient_result_is_caught(self):
        self.assertTrue(
            any("cross-patient" in m for m in self._messages_for("cross-result"))
        )

    def test_a_hasPatient_shortcut_is_caught(self):
        self.assertTrue(
            any("shortcut" in m for m in self._messages_for("shortcut-encounter"))
        )

    def test_a_quantity_without_a_unit_is_caught(self):
        self.assertTrue(any("Unit part" in m for m in self._messages_for("unitless")))

    def test_a_quantity_with_two_values_is_caught(self):
        """DR-002 axiom 1: sulo:hasValue is owl:FunctionalProperty."""
        self.assertTrue(
            any("exactly one numeric" in m for m in self._messages_for("twovalue"))
        )

    def test_a_role_with_no_holder_is_caught(self):
        self.assertTrue(
            any("isFeatureOf exactly one" in m for m in self._messages_for("dangling-role"))
        )

    def test_a_time_instant_with_lost_precision_is_caught(self):
        self.assertTrue(any("precision" in m for m in self._messages_for("sloppy-time")))

    def test_a_node_in_two_disjoint_feature_branches_is_caught(self):
        self.assertTrue(any("disjoint" in m for m in self._messages_for("confused")))


@unittest.skipUnless(HAVE_SHACL, SKIP)
class R5SwitchFlipsExactlyTwoConstraints(unittest.TestCase):
    """A reviewer answer changes behaviour without re-authoring a map."""

    def test_option_a_flags_the_two_open_world_omissions(self):
        report = shapes_check.validate_graph(
            graph_text("egfr-target.ttl"), strictness.R5_OPTION_A
        )
        self.assertFalse(report.conforms)
        paths = {v.path for v in report.violations}
        self.assertEqual(
            paths,
            {"https://w3id.org/sulo/isFeatureOf", "https://w3id.org/sulo/hasPart"},
        )
        self.assertTrue(all("R5 option A" in v.message for v in report.violations))

    def test_option_b_is_the_default_and_the_graph_conforms(self):
        report = shapes_check.validate_graph(
            graph_text("egfr-target.ttl"), strictness.R5_OPTION_B
        )
        self.assertTrue(report.conforms)

    def test_the_split_flags_only_the_chosen_axiom(self):
        report = shapes_check.validate_graph(
            graph_text("egfr-target.ttl"),
            strictness.Strictness(require_time_unit=True),
        )
        self.assertFalse(report.conforms)
        self.assertEqual(len(report.violations), 1)
        self.assertIn("TimeInstant", report.violations[0].message)

    def test_the_strictness_label_is_recorded_in_the_report(self):
        report = shapes_check.validate_graph(
            graph_text("egfr-target.ttl"), strictness.R5_OPTION_A
        )
        self.assertIn("R5-option-A", report.strictness_label)

    def test_the_digest_differs_between_strictness_settings(self):
        """So a validation report can never be misread as having been
        produced under a strictness it was not."""
        literal = shapes_check.validate_graph(
            graph_text("egfr-target.ttl"), strictness.CONCEPT_NOTE_LITERAL
        )
        strict = shapes_check.validate_graph(
            graph_text("egfr-target.ttl"), strictness.R5_OPTION_A
        )
        self.assertNotEqual(literal.digest, strict.digest)


if __name__ == "__main__":
    unittest.main()
