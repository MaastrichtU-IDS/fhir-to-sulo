"""Reference resolution produces evidence, never a person claim.

Concept note section 2: a `Patient` resource is not identical to a person, and
plan section 3: "No person-equivalence claim is implicit in a resolved FHIR
reference." These tests assert the *refusals* as hard as the resolutions.
"""

from __future__ import annotations

import os
import unittest

from . import _support
from ._support import FIXTURES, cases, read

from fhir_sulo.contracts import ResolvedReference  # noqa: E402
from fhir_sulo.contracts.source_context import (  # noqa: E402
    AmbiguousReferenceError,
    UnresolvedReferenceError,
)
from fhir_sulo.ingest import (  # noqa: E402
    MockIdentityService,
    RefusingIdentityService,
    SubjectContext,
    ingest_file,
    jsonio,
    resolve_resource,
)

CTX = SubjectContext(
    source_server_base="https://fhir.example/", dataset_id="synthetic/pilot",
    source_resource_iri="https://fhir.example/Observation/egfr-456",
    source_version_id="1",
)


def _resource(family, case, name):
    return jsonio.loads(read(os.path.join(FIXTURES, family, case, name)))


class TestEvidenceKinds(unittest.TestCase):
    def test_relative_reference(self):
        r = resolve_resource(_resource("egfr", "egfr-baseline", "egfr-456.json"))
        ref = r["Observation.subject"]
        self.assertEqual(ref.evidence.kind, "literal-relative")
        self.assertEqual(ref.evidence.raw_reference, "Patient/p123")
        self.assertEqual(ref.evidence.resolved_target, "https://fhir.example/Patient/p123")
        self.assertIsNone(ref.entity_iri, "resolution must not produce an entity IRI")

    def test_contained_reference(self):
        r = resolve_resource(_resource("egfr", "egfr-contained-subject",
                                       "egfr-456-contained.json"))
        ref = r["Observation.subject"]
        self.assertEqual(ref.evidence.kind, "contained")
        self.assertEqual(ref.evidence.resolved_target, "#p-inline")
        self.assertTrue(any("no existence outside" in n for n in ref.evidence.notes))

    def test_dangling_contained_reference_is_unresolvable(self):
        r = resolve_resource(_resource("egfr", "egfr-reference-unresolvable",
                                       "egfr-456-badref.json"))
        ref = r["Observation.subject"]
        self.assertEqual(ref.evidence.kind, "unresolvable")
        self.assertIsNone(ref.evidence.resolved_target)

    def test_duplicate_contained_ids_are_ambiguous(self):
        r = resolve_resource(_resource("egfr", "egfr-reference-ambiguous",
                                       "egfr-456-ambigref.json"))
        ref = r["Observation.subject"]
        self.assertEqual(ref.evidence.kind, "ambiguous")
        self.assertTrue(ref.ambiguous)

    def test_encounter_participant_is_resolved(self):
        r = resolve_resource(_resource("encounter", "enc-baseline", "enc-9.json"))
        ref = r["Encounter.participant[0].individual"]
        self.assertEqual(ref.evidence.kind, "literal-relative")
        self.assertEqual(ref.evidence.resolved_target,
                         "https://fhir.example/Practitioner/c7")

    def test_contained_participant_is_resolved(self):
        r = resolve_resource(_resource("encounter", "enc-contained-practitioner",
                                       "enc-12.json"))
        ref = r["Encounter.participant[0].individual"]
        self.assertEqual(ref.evidence.kind, "contained")
        self.assertEqual(ref.evidence.resolved_target, "#pr-inline")

    def test_absolute_cross_server_reference_is_flagged(self):
        res = _resource("egfr", "egfr-baseline", "egfr-456.json")
        res["subject"] = {"reference": "https://other.example/Patient/p123"}
        ref = resolve_resource(res)["Observation.subject"]
        self.assertEqual(ref.evidence.kind, "literal-absolute")
        self.assertTrue(any("different server base" in n for n in ref.evidence.notes))

    def test_versioned_reference_keeps_its_version(self):
        res = _resource("egfr", "egfr-baseline", "egfr-456.json")
        res["subject"] = {"reference": "Patient/p123/_history/2"}
        ref = resolve_resource(res)["Observation.subject"]
        self.assertEqual(ref.evidence.kind, "literal-versioned")
        self.assertIn("https://fhir.example/Patient/p123/_history/2",
                      ref.evidence.resolved_target)

    def test_identifier_only_reference_is_not_resolvable(self):
        res = _resource("egfr", "egfr-baseline", "egfr-456.json")
        res["subject"] = {"identifier": {"system": "https://ex/mrn", "value": "42"}}
        ref = resolve_resource(res)["Observation.subject"]
        self.assertEqual(ref.evidence.kind, "identifier-only")
        self.assertIsNone(ref.evidence.resolved_target)

    def test_wrong_target_type_is_recorded_not_silently_accepted(self):
        res = _resource("egfr", "egfr-baseline", "egfr-456.json")
        res["subject"] = {"reference": "Device/d1"}
        from fhir_sulo.ingest.references import ReferenceResolver
        ref = ReferenceResolver().resolve(res["subject"],
                                          source_element="Observation.subject",
                                          expected_type="Patient")
        self.assertTrue(any("expects a Patient" in n for n in ref.evidence.notes))


class TestNoImplicitPersonClaim(unittest.TestCase):
    def test_resolution_alone_never_yields_an_entity_iri(self):
        for case_dir, case in cases():
            for name in case["sources"]:
                res = jsonio.loads(read(os.path.join(case_dir, name)))
                for path, ref in resolve_resource(res).items():
                    with self.subTest(fixture=case["fixture_id"], path=path):
                        self.assertIsNone(ref.entity_iri)
                        self.assertIsNone(ref.identity_policy_version)

    def test_the_default_ingest_establishes_no_identity(self):
        """Without a reviewed identity policy, no person exists."""
        ctx = ingest_file(os.path.join(FIXTURES, "egfr", "egfr-baseline", "egfr-456.json"))
        ref = ctx.resolved_references["Observation.subject"]
        self.assertEqual(ref.identity_policy_version, RefusingIdentityService.policy_version)
        with self.assertRaises(UnresolvedReferenceError):
            ref.require_entity_iri()

    def test_no_owl_sameas_is_emitted_anywhere(self):
        for case_dir, _ in cases():
            self.assertNotIn("sameAs", read(os.path.join(case_dir, "canonical.nt")))


class TestMockIdentityService(unittest.TestCase):
    def setUp(self):
        self.svc = MockIdentityService()

    def _one(self, family, case, name, path="Observation.subject"):
        refs = resolve_resource(_resource(family, case, name))
        return self.svc.establish(refs, CTX)[path]

    def test_resolved_reference_gets_a_stable_iri(self):
        a = self._one("egfr", "egfr-baseline", "egfr-456.json")
        b = self._one("egfr", "egfr-baseline", "egfr-456.json")
        self.assertEqual(a.require_entity_iri(), b.require_entity_iri())
        self.assertEqual(a.identity_policy_version, "mock-identity/0.1.0")

    def test_the_same_patient_from_two_resources_is_one_entity(self):
        obs = resolve_resource(_resource("egfr", "egfr-baseline", "egfr-456.json"))
        enc = resolve_resource(_resource("encounter", "enc-baseline", "enc-9.json"))
        a = self.svc.establish(obs, CTX)["Observation.subject"]
        b = self.svc.establish(enc, CTX)["Encounter.subject"]
        self.assertEqual(a.require_entity_iri(), b.require_entity_iri())

    def test_different_patients_stay_different(self):
        p123 = resolve_resource(_resource("bp", "bp-other-patient", "bp-1.json"))
        p999 = resolve_resource(_resource("bp", "bp-other-patient", "bp-5.json"))
        a = self.svc.establish(p123, CTX)["Observation.subject"]
        b = self.svc.establish(p999, CTX)["Observation.subject"]
        self.assertNotEqual(a.require_entity_iri(), b.require_entity_iri())

    def test_a_version_suffix_does_not_split_an_entity(self):
        res = _resource("egfr", "egfr-baseline", "egfr-456.json")
        plain = self.svc.establish(resolve_resource(res), CTX)["Observation.subject"]
        res["subject"] = {"reference": "Patient/p123/_history/2"}
        versioned = self.svc.establish(resolve_resource(res), CTX)["Observation.subject"]
        self.assertEqual(plain.require_entity_iri(), versioned.require_entity_iri())

    def test_contained_entities_are_scoped_to_their_container(self):
        refs = resolve_resource(_resource("egfr", "egfr-contained-subject",
                                          "egfr-456-contained.json"))
        a = self.svc.establish(refs, CTX)["Observation.subject"].require_entity_iri()
        other = SubjectContext(
            source_server_base=CTX.source_server_base, dataset_id=CTX.dataset_id,
            source_resource_iri="https://fhir.example/Observation/somewhere-else",
            source_version_id="1")
        b = self.svc.establish(refs, other)["Observation.subject"].require_entity_iri()
        self.assertNotEqual(a, b, "two contained #p-inline patients must not merge")

    def test_ambiguity_is_returned_not_resolved(self):
        ref = self._one("egfr", "egfr-reference-ambiguous", "egfr-456-ambigref.json")
        self.assertTrue(ref.ambiguous)
        with self.assertRaises(AmbiguousReferenceError):
            ref.require_entity_iri()

    def test_unresolvable_gets_no_iri(self):
        ref = self._one("egfr", "egfr-reference-unresolvable", "egfr-456-badref.json")
        with self.assertRaises(UnresolvedReferenceError):
            ref.require_entity_iri()

    def test_entity_iri_is_opaque(self):
        """A downstream consumer must not be able to read a FHIR id back out and
        re-introduce the record/fact confusion."""
        iri = self._one("egfr", "egfr-baseline", "egfr-456.json").require_entity_iri()
        self.assertNotIn("p123", iri)
        self.assertNotIn("Patient", iri)


class TestCaseDeclarations(unittest.TestCase):
    """Every case.json reference expectation must hold."""

    def test_declared_reference_outcomes(self):
        svc = MockIdentityService()
        for case_dir, case in cases():
            expectations = case["expected"].get("references") or {}
            if not expectations:
                continue
            res = jsonio.loads(read(os.path.join(case_dir, case["sources"][0])))
            refs = svc.establish(resolve_resource(res), CTX)
            for path, want in expectations.items():
                with self.subTest(fixture=case["fixture_id"], path=path):
                    got = refs[path]
                    self.assertEqual(got.evidence.kind, want["kind"])
                    self.assertEqual(got.evidence.resolved_target, want["resolved_target"])
                    if want.get("entity_iri_established"):
                        self.assertIsNotNone(got.require_entity_iri())
                    else:
                        with self.assertRaises((AmbiguousReferenceError,
                                                UnresolvedReferenceError)):
                            got.require_entity_iri()


if __name__ == "__main__":
    unittest.main()
