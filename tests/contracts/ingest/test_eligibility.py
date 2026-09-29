"""Status and absence: exactly the declared mapped / source-only / rejected result.

Acceptance matrix row "Status/absence":

    Exactly the declared `mapped`, `source-only`, or `rejected` result.
    No unqualified numeric assertion.

Every negative fixture's outcome is declared in its ``case.json`` and asserted
here, so a policy change shows up as a fixture diff plus a test failure rather
than as a quiet behaviour change.
"""

from __future__ import annotations

import os
import unittest

from . import _support
from ._support import FIXTURES, cases, read

from fhir_sulo.contracts import EligibilityOutcome  # noqa: E402
from fhir_sulo.ingest import (  # noqa: E402
    MockIdentityService,
    default_manifest,
    ingest_file,
    ingest_text,
    jsonio,
)

OUTCOME = {
    "eligible": EligibilityOutcome.ELIGIBLE,
    "source-only": EligibilityOutcome.SOURCE_ONLY,
    "rejected": EligibilityOutcome.REJECTED,
}


def _ingest(case_dir, name):
    return ingest_file(os.path.join(case_dir, name), identity=MockIdentityService())


class TestDeclaredOutcomes(unittest.TestCase):
    def test_every_fixture_takes_its_declared_path(self):
        n = 0
        for case_dir, case in cases():
            want = OUTCOME[case["expected"]["eligibility"]]
            for name in case["sources"]:
                with self.subTest(fixture=case["fixture_id"], source=name):
                    ctx = _ingest(case_dir, name)
                    self.assertIs(ctx.eligibility, want, ctx.eligibility_reason)
                    for fragment in case["expected"]["eligibility_reason_contains"]:
                        self.assertIn(fragment, ctx.eligibility_reason or "")
                    n += 1
        self.assertGreaterEqual(n, 20)

    def test_negative_fixtures_exist_for_every_declared_value_policy(self):
        """Plan Gate 0: every required field has an explicit source, target or
        rejection rule. A policy with no fixture is an untested rule."""
        m = default_manifest()
        covered = set()
        for case_dir, case in cases():
            for fragment in case["expected"]["eligibility_reason_contains"]:
                covered.add(fragment)
        for expected_fragment in ("comparator", "dataAbsentReason present",
                                  "no pinned code", "not in the pinned unit set",
                                  "no UCUM system/code", "unresolvable reference",
                                  "ambiguous reference", "entered-in-error"):
            self.assertIn(expected_fragment, covered,
                          f"no fixture exercises the {expected_fragment!r} rule")


class TestSpecificRules(unittest.TestCase):
    def _obs(self):
        return jsonio.loads(read(os.path.join(
            FIXTURES, "egfr", "egfr-baseline", "egfr-456.json")))

    def _run(self, resource):
        return ingest_text(jsonio.dumps(resource), identity=MockIdentityService())

    def test_entered_in_error_is_source_only_not_rejected(self):
        """Concept note section 2: suppresses clinical assertions, does not
        erase the source record."""
        ctx = _ingest(os.path.join(FIXTURES, "egfr", "egfr-entered-in-error"),
                      "egfr-456-eie.json")
        self.assertIs(ctx.eligibility, EligibilityOutcome.SOURCE_ONLY)
        self.assertIn("Observation.status", ctx.rdf_graph)
        self.assertIn('"entered-in-error"', ctx.rdf_graph)

    def test_comparator_is_rejected_not_silently_accepted(self):
        r = self._obs()
        r["valueQuantity"]["comparator"] = ">="
        ctx = self._run(r)
        self.assertIs(ctx.eligibility, EligibilityOutcome.REJECTED)
        self.assertIn("comparator", ctx.eligibility_reason)

    def test_value_and_absent_reason_together_are_rejected(self):
        r = self._obs()
        r["dataAbsentReason"] = {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/data-absent-reason",
            "code": "unknown"}]}
        ctx = self._run(r)
        self.assertIs(ctx.eligibility, EligibilityOutcome.REJECTED)
        self.assertIn("obs-6", ctx.eligibility_reason)

    def test_unknown_status_is_rejected_rather_than_defaulted(self):
        r = self._obs()
        r["status"] = "not-a-real-status"
        ctx = self._run(r)
        self.assertIs(ctx.eligibility, EligibilityOutcome.REJECTED)
        self.assertIn("no entry in the pinned status policy", ctx.eligibility_reason)

    def test_the_most_severe_finding_wins(self):
        """entered-in-error (source-only) plus a comparator (rejected) must be
        rejected, not source-only."""
        r = self._obs()
        r["status"] = "entered-in-error"
        r["valueQuantity"]["comparator"] = "<"
        ctx = self._run(r)
        self.assertIs(ctx.eligibility, EligibilityOutcome.REJECTED)
        self.assertIn("entered-in-error", ctx.eligibility_reason)
        self.assertIn("comparator", ctx.eligibility_reason)

    def test_unsupported_modifier_extension_blocks_materialization(self):
        r = self._obs()
        r["modifierExtension"] = [{"url": "https://example.org/x/unknown-modifier",
                                   "valueBoolean": True}]
        ctx = self._run(r)
        self.assertIs(ctx.eligibility, EligibilityOutcome.REJECTED)
        self.assertEqual(ctx.unsupported_modifier_extensions,
                         ("https://example.org/x/unknown-modifier",))

    def test_a_modifier_extension_on_a_component_is_also_caught(self):
        r = jsonio.loads(read(os.path.join(
            FIXTURES, "bp", "bp-two-panels", "bp-1.json")))
        r["component"][0]["modifierExtension"] = [
            {"url": "https://example.org/x/component-modifier", "valueBoolean": True}]
        ctx = self._run(r)
        self.assertIs(ctx.eligibility, EligibilityOutcome.REJECTED)
        self.assertIn("https://example.org/x/component-modifier",
                      ctx.unsupported_modifier_extensions)


class TestSourceContextContents(unittest.TestCase):
    def test_source_context_carries_the_pinned_provenance_fields(self):
        ctx = _ingest(os.path.join(FIXTURES, "egfr", "egfr-baseline"), "egfr-456.json")
        m = default_manifest()
        self.assertEqual(ctx.fhir_release, "4.0.1")
        self.assertEqual(ctx.canonical_url, "https://fhir.example/Observation/egfr-456")
        self.assertEqual(ctx.version_id, "1")
        self.assertEqual(ctx.source_status, "final")
        self.assertEqual(ctx.renderer_id, m.renderer_id)
        self.assertEqual(ctx.rdf_content_type, "application/n-triples")
        self.assertEqual(ctx.terminology_snapshot, m.terminology_snapshot)
        self.assertTrue(ctx.source_json_digest.startswith("sha256:"))
        self.assertIn("http://hl7.org/fhir/StructureDefinition/Observation",
                      ctx.validated_profiles)

    def test_digest_changes_when_the_source_changes(self):
        base = os.path.join(FIXTURES, "egfr", "egfr-baseline", "egfr-456.json")
        a = ingest_file(base).source_json_digest
        b = ingest_text(read(base).replace("55.0", "55.1")).source_json_digest
        self.assertNotEqual(a, b)

    def test_declared_profile_is_validated_when_it_is_pinned(self):
        r = jsonio.loads(read(os.path.join(
            FIXTURES, "egfr", "egfr-baseline", "egfr-456.json")))
        r["meta"]["profile"] = ["http://hl7.org/fhir/StructureDefinition/vitalsigns"]
        ctx = ingest_text(jsonio.dumps(r))
        self.assertIn("http://hl7.org/fhir/StructureDefinition/vitalsigns",
                      ctx.declared_profiles)
        self.assertIn("http://hl7.org/fhir/StructureDefinition/vitalsigns",
                      ctx.validated_profiles)

    def test_an_unpinned_declared_profile_is_reported_not_silently_validated(self):
        r = jsonio.loads(read(os.path.join(
            FIXTURES, "egfr", "egfr-baseline", "egfr-456.json")))
        r["meta"]["profile"] = ["https://example.org/StructureDefinition/made-up"]
        ctx = ingest_text(jsonio.dumps(r))
        self.assertIn("https://example.org/StructureDefinition/made-up",
                      ctx.declared_profiles)
        self.assertNotIn("https://example.org/StructureDefinition/made-up",
                         ctx.validated_profiles)
        self.assertTrue(any("not in the pinned set" in n for n in ctx.notes))

    def test_ingestion_is_reproducible(self):
        path = os.path.join(FIXTURES, "egfr", "egfr-baseline", "egfr-456.json")
        a = ingest_file(path, identity=MockIdentityService())
        b = ingest_file(path, identity=MockIdentityService())
        self.assertEqual(a.rdf_graph, b.rdf_graph)
        self.assertEqual(a.source_json_digest, b.source_json_digest)
        self.assertEqual(
            {k: v.entity_iri for k, v in a.resolved_references.items()},
            {k: v.entity_iri for k, v in b.resolved_references.items()})


if __name__ == "__main__":
    unittest.main()
