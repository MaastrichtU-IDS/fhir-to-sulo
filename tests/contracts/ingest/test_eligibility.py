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


class TestEveryObservationStatus(unittest.TestCase):
    """All eight R4 Observation statuses, driven through ingestion.

    R3's answer widened the eligible set from {final} to
    {final, amended, corrected}. FHIR's status conflates two axes, and the
    answer turns on the distinction: ``amended``/``corrected`` are points on
    the *revision* axis - complete and verified, then revised - while
    ``preliminary``/``registered`` are points on the *verification* axis.
    Widening along the wrong axis is the failure this guards, and a suite that
    only showed ``final`` mapping would not notice it.

    Driven from the manifest rather than a second hardcoded list, so the table
    and the behaviour cannot drift apart; ``test_manifest`` separately asserts
    the manifest covers exactly the R4 value set.
    """

    REVISION_AXIS = {"final", "amended", "corrected"}
    VERIFICATION_AXIS = {"registered", "preliminary"}

    def _with_status(self, status):
        r = jsonio.loads(read(os.path.join(
            FIXTURES, "egfr", "egfr-baseline", "egfr-456.json")))
        r["status"] = status
        return ingest_text(jsonio.dumps(r), identity=MockIdentityService())

    def test_each_status_takes_the_outcome_the_manifest_declares(self):
        m = default_manifest()
        for status in m.data["status_policy"]["Observation"]:
            with self.subTest(status=status):
                self.assertIs(self._with_status(status).eligibility,
                              OUTCOME[m.status_outcome("Observation", status)])

    def test_exactly_the_revision_axis_is_eligible(self):
        m = default_manifest()
        eligible = {s for s in m.data["status_policy"]["Observation"]
                    if m.status_outcome("Observation", s) == "eligible"}
        self.assertEqual(eligible, self.REVISION_AXIS)

    def test_no_verification_axis_status_is_eligible(self):
        for status in self.VERIFICATION_AXIS:
            with self.subTest(status=status):
                self.assertIs(self._with_status(status).eligibility,
                              EligibilityOutcome.SOURCE_ONLY)

    def test_retraction_is_source_only_not_eligible(self):
        """entered-in-error is retraction, not revision: R3 kept it out."""
        self.assertIs(self._with_status("entered-in-error").eligibility,
                      EligibilityOutcome.SOURCE_ONLY)

    def test_every_source_only_status_still_keeps_its_record(self):
        for status in ("preliminary", "registered", "cancelled", "unknown",
                       "entered-in-error"):
            with self.subTest(status=status):
                ctx = self._with_status(status)
                self.assertIn('"%s"' % status, ctx.rdf_graph)
                self.assertIn('"55.0"', ctx.rdf_graph)


class TestCoarseEffectiveTime(unittest.TestCase):
    """R3's new row: a date is not an instant, so no time node is emitted.

    Proposed, pending R3. Asserted here so the rule is visible and so its
    *scope* is pinned: it must fire on Observation.effective[x] and must not
    quietly spread to Encounter.period, whose open-endedness question is R5.
    """

    def _obs(self, effective=None, period=None):
        r = jsonio.loads(read(os.path.join(
            FIXTURES, "egfr", "egfr-baseline", "egfr-456.json")))
        r.pop("effectiveDateTime", None)
        if effective is not None:
            r["effectiveDateTime"] = effective
        if period is not None:
            r["effectivePeriod"] = period
        return ingest_text(jsonio.dumps(r), identity=MockIdentityService())

    def test_a_full_timestamp_stays_eligible(self):
        self.assertIs(self._obs("2026-09-02T14:00:00Z").eligibility,
                      EligibilityOutcome.ELIGIBLE)
        self.assertIs(self._obs("2026-09-02T14:00:00+01:00").eligibility,
                      EligibilityOutcome.ELIGIBLE)

    def test_every_coarser_precision_is_source_only(self):
        for value in ("2026-09-02", "2026-09", "2026"):
            with self.subTest(value=value):
                ctx = self._obs(value)
                self.assertIs(ctx.eligibility, EligibilityOutcome.SOURCE_ONLY)
                self.assertIn("carries no clock time", ctx.eligibility_reason)
                self.assertIn("R3", ctx.eligibility_reason)

    def test_the_value_is_still_retained_in_the_source_layer(self):
        """source-only retains the record; it does not erase it."""
        ctx = self._obs("2026-09-02")
        self.assertIn('"2026-09-02"^^<http://www.w3.org/2001/XMLSchema#date>',
                      ctx.rdf_graph)

    def test_a_coarse_effective_period_endpoint_also_fires(self):
        ctx = self._obs(period={"start": "2026-09-02", "end": "2026-09-03T10:00:00Z"})
        self.assertIs(ctx.eligibility, EligibilityOutcome.SOURCE_ONLY)
        self.assertIn("effectivePeriod.start", ctx.eligibility_reason)
        self.assertNotIn("effectivePeriod.end", ctx.eligibility_reason)

    def test_the_rule_does_not_reach_encounter_period(self):
        """Deliberately out of scope: Encounter.period is R5 / Q-A2-3."""
        enc = jsonio.loads(read(os.path.join(
            FIXTURES, "encounter", "enc-baseline", "enc-9.json")))
        enc["period"] = {"start": "2026-09-02"}
        ctx = ingest_text(jsonio.dumps(enc), identity=MockIdentityService())
        self.assertIs(ctx.eligibility, EligibilityOutcome.ELIGIBLE)

    def test_the_scope_is_manifest_driven_not_hardcoded(self):
        policy = default_manifest().value_policy("effective_time_coarser_than_seconds")
        self.assertEqual(policy["outcome"], "source-only")
        self.assertEqual(sorted(policy["applies_to"]),
                         ["Observation.effectiveDateTime", "Observation.effectivePeriod"])
        self.assertIn("R3", policy["reason"])

    def test_an_offsetless_timestamp_is_refused_by_the_renderer_not_ruled_on_here(self):
        """'2026-09-02T14:00:00' is not conformant R4, so it never reaches a
        policy decision; the renderer refuses it first."""
        from fhir_sulo.ingest.fhir_rdf import RenderError
        with self.assertRaises(RenderError):
            self._obs("2026-09-02T14:00:00")


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

    def test_a_falsely_declared_profile_is_rejected_not_rubber_stamped(self):
        """R9a. This test previously asserted the OPPOSITE, and was right to fail.

        It took an eGFR resource, wrote ``vitalsigns`` into ``meta.profile``,
        and asserted the result appeared in ``validated_profiles``.  Nothing
        checked it: ``validated`` meant "declared and recognised".  An eGFR is
        not a vital sign and carries no ``category = vital-signs``, so it does
        not conform, and claiming it did was the rubber stamp R9a removed.
        """
        from fhir_sulo.ingest.profile_conformance import ProfileConformanceError

        r = jsonio.loads(read(os.path.join(
            FIXTURES, "egfr", "egfr-baseline", "egfr-456.json")))
        r["meta"]["profile"] = ["http://hl7.org/fhir/StructureDefinition/vitalsigns"]
        with self.assertRaises(ProfileConformanceError) as caught:
            ingest_text(jsonio.dumps(r))
        self.assertIn("vs-cat", str(caught.exception))

    def test_a_conformant_declared_profile_is_validated(self):
        """And the claim is only made after the constraints actually pass."""
        r = jsonio.loads(read(os.path.join(
            FIXTURES, "bp", "bp-two-panels", "bp-1.json")))
        ctx = ingest_text(jsonio.dumps(r))
        self.assertIn("http://hl7.org/fhir/StructureDefinition/vitalsigns",
                      ctx.declared_profiles)
        self.assertIn("http://hl7.org/fhir/StructureDefinition/vitalsigns",
                      ctx.validated_profiles)

    def test_each_enforced_constraint_can_actually_fail(self):
        """A constraint nobody can break is a constraint nobody is checking."""
        from fhir_sulo.ingest.profile_conformance import ProfileConformanceError

        base = jsonio.loads(read(os.path.join(
            FIXTURES, "bp", "bp-two-panels", "bp-1.json")))
        breakages = {
            "vs-cat": lambda r: r.pop("category"),
            "vs-subject": lambda r: r.pop("subject"),
            "vs-effective": lambda r: r.pop("effectiveDateTime"),
            "vs-code-loinc": lambda r: r["code"]["coding"][0].update(
                {"system": "http://example.org/not-loinc"}),
            # vs-2: no component, no hasMember, no value[x], no dataAbsentReason.
            "vs-2": lambda r: r.pop("component"),
        }
        for constraint_id, break_it in breakages.items():
            with self.subTest(constraint=constraint_id):
                r = jsonio.loads(jsonio.dumps(base))
                break_it(r)
                with self.assertRaises(ProfileConformanceError) as caught:
                    ingest_text(jsonio.dumps(r))
                self.assertIn(constraint_id, str(caught.exception))

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
