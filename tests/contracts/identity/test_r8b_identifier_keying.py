"""R8b: a shared person-identifying business identifier keys one person.

The reviewer answered R8b on 2026-10-03: a Patient record and a Practitioner
record that carry the same person-identifying business identifier describe one
human and must get one entity IRI.

This is implemented as **keying**, not as a merge pass.  A business identifier
in an agreed namespace *is* an identity criterion for the person, so the person
is keyed on it directly: one IRI, deterministically, with no post-hoc graph
rewriting, no ``owl:sameAs`` between records, and no reasoning needed to
collapse two nodes.

The shipped policy allowlists a **synthetic** namespace only, so nothing a
real register issues can merge anyone.  These tests install a test-local
allowlist where they need a different one; the shipped state is covered by
``TheShippedPolicyMergesOnlySyntheticIdentifiers`` below.
"""

import copy
import unittest

from fhir_sulo.identity import (
    IdentityRequest,
    IdentityService,
    ReferenceEvidence,
    SourceScope,
)

NATIONAL = "http://example.org/national-person-number"
LOCAL_MRN = "http://hospital.example/mrn"

SITE_A = SourceScope("fhir-sulo-fixtures-r4", "https://fhir.example/")
SITE_B = SourceScope("other-site-r4", "https://other.example/")


def service_allowing(*systems):
    """A service whose policy allowlists these systems. PolicyBundle is frozen."""
    import dataclasses

    base = IdentityService()
    patched = copy.deepcopy(dict(base.policy.identity))
    patched["person_identifying_identifier_systems"] = [
        {"system": sysuri, "status": "pilot-provisional", "scope": "synthetic"}
        for sysuri in systems
    ]
    return IdentityService(policy=dataclasses.replace(base.policy, identity=patched))


def evidence(scope, resource_type, resource_id="", pairs=()):
    return ReferenceEvidence(
        evidence_id="e",
        kind="identifier-only" if not resource_id else "literal-reference",
        source_scope=scope,
        resource_type=resource_type,
        resource_id=resource_id,
        identifier_system=pairs[0] if pairs else None,
        identifier_value=pairs[1] if pairs else None,
    )


def resolve(svc, ev, resource_type):
    return svc.resolve(
        IdentityRequest("ref", (resource_type,), (ev,), entity_kind="person")
    )


class TheShippedPolicyMergesOnlySyntheticIdentifiers(unittest.TestCase):
    """The shipped allowlist is no longer empty, but it is still inert in the
    only sense that matters: nothing a real register issues can merge anyone.

    This class previously asserted the list was empty. That became the wrong
    assertion once a SYNTHETIC namespace was listed to make the mechanism
    reachable, so it now asserts the property that was actually being
    protected.
    """

    def test_only_synthetic_namespaces_are_interpretable(self):
        svc = IdentityService()
        for entry in svc.policy.identity["person_identifying_identifier_systems"]:
            if entry["status"] in ("approved", "pilot-provisional"):
                with self.subTest(system=entry["system"]):
                    self.assertEqual(entry["scope"], "synthetic")

    def test_the_real_world_candidates_are_present_but_type_nothing(self):
        """BSN and SSN are listed so enabling one is a reviewed edit rather
        than an invention. Listed is not enabled."""
        svc = IdentityService()
        proposed = {e["system"] for e in
                    svc.policy.identity["person_identifying_identifier_systems"]
                    if e["status"] == "proposed"}
        self.assertIn("http://fhir.nl/fhir/NamingSystem/bsn", proposed)
        self.assertFalse(proposed & svc._person_identifier_allowlist())

    def test_the_us_npi_is_explicitly_excluded_with_a_reason(self):
        """One system URI covers individual AND organisational NPIs."""
        svc = IdentityService()
        excluded = {e["system"]: e["reason"] for e in
                    svc.policy.identity["person_identifying_identifier_systems_excluded"]}
        self.assertIn("http://hl7.org/fhir/sid/us-npi", excluded)
        self.assertIn("Type 2", excluded["http://hl7.org/fhir/sid/us-npi"])

    def test_a_logical_reference_is_rejected_with_a_useful_reason(self):
        """Not ID-R6 'incomplete key inputs', which is true but unhelpful."""
        svc = IdentityService()
        outcome = resolve(svc, evidence(SITE_A, "Patient", pairs=(NATIONAL, "77")), "Patient")
        self.assertFalse(outcome.is_resolved)
        self.assertEqual(outcome.reason_code, "identifier-not-person-identifying")
        self.assertEqual(outcome.record.rule_id, "ID-R14-identifier-not-person-identifying")


class AnAllowlistedIdentifierKeysThePerson(unittest.TestCase):
    def test_a_patient_and_a_practitioner_sharing_one_become_one_person(self):
        """The answer to R8b, demonstrated end to end."""
        svc = service_allowing(NATIONAL)
        patient = resolve(svc, evidence(SITE_A, "Patient", pairs=(NATIONAL, "77")), "Patient")
        practitioner = resolve(
            svc, evidence(SITE_A, "Practitioner", pairs=(NATIONAL, "77")), "Practitioner")
        self.assertTrue(patient.is_resolved and practitioner.is_resolved)
        self.assertEqual(patient.unwrap().entity_iri, practitioner.unwrap().entity_iri)
        self.assertEqual(patient.unwrap().rule_id, "ID-R12-identifier-keyed-person")

    def test_it_merges_across_source_scopes(self):
        """This IS the recorded evidence cross_source_merge requires.

        A national identifier is global by construction; scoping it per source
        would defeat the only thing it is for.
        """
        svc = service_allowing(NATIONAL)
        a = resolve(svc, evidence(SITE_A, "Patient", pairs=(NATIONAL, "77")), "Patient")
        b = resolve(svc, evidence(SITE_B, "Patient", pairs=(NATIONAL, "77")), "Patient")
        self.assertEqual(a.unwrap().entity_iri, b.unwrap().entity_iri)

    def test_different_values_stay_different_people(self):
        svc = service_allowing(NATIONAL)
        a = resolve(svc, evidence(SITE_A, "Patient", pairs=(NATIONAL, "77")), "Patient")
        b = resolve(svc, evidence(SITE_A, "Patient", pairs=(NATIONAL, "78")), "Patient")
        self.assertNotEqual(a.unwrap().entity_iri, b.unwrap().entity_iri)

    def test_the_same_value_in_a_different_system_is_a_different_person(self):
        """Identifier.value alone means nothing; the namespace is the point."""
        svc = service_allowing(NATIONAL, LOCAL_MRN)
        a = resolve(svc, evidence(SITE_A, "Patient", pairs=(NATIONAL, "77")), "Patient")
        b = resolve(svc, evidence(SITE_A, "Patient", pairs=(LOCAL_MRN, "77")), "Patient")
        self.assertNotEqual(a.unwrap().entity_iri, b.unwrap().entity_iri)

    def test_a_non_allowlisted_identifier_does_not_key(self):
        """An MRN identifies a patient record at one site, not a human."""
        svc = service_allowing(NATIONAL)
        outcome = resolve(svc, evidence(SITE_A, "Patient", pairs=(LOCAL_MRN, "77")), "Patient")
        self.assertFalse(outcome.is_resolved)
        self.assertEqual(outcome.reason_code, "identifier-not-person-identifying")

    def test_the_identifier_key_is_not_the_record_address_key(self):
        """Documents the cost: switching a record onto an identifier moves its IRI."""
        svc = service_allowing(NATIONAL)
        by_identifier = resolve(
            svc, evidence(SITE_A, "Patient", pairs=(NATIONAL, "77")), "Patient")
        by_address = resolve(svc, evidence(SITE_A, "Patient", resource_id="77"), "Patient")
        self.assertNotEqual(by_identifier.unwrap().entity_iri, by_address.unwrap().entity_iri)

    def test_discordant_person_identifiers_are_rejected_not_guessed(self):
        """Picking one would make identity depend on element order."""
        svc = service_allowing(NATIONAL, LOCAL_MRN)
        candidates = (
            evidence(SITE_A, "Patient", pairs=(NATIONAL, "77")),
            evidence(SITE_A, "Patient", pairs=(LOCAL_MRN, "99")),
        )
        outcome = svc.resolve(
            IdentityRequest("ref", ("Patient",), candidates, entity_kind="person"))
        self.assertFalse(outcome.is_resolved)
        self.assertEqual(outcome.reason_code, "ambiguous-person-identifier")
        self.assertEqual(outcome.record.rule_id, "ID-R13-multiple-person-identifiers")

    def test_the_key_is_deterministic(self):
        svc = service_allowing(NATIONAL)
        seen = {
            resolve(svc, evidence(SITE_A, "Patient", pairs=(NATIONAL, "77")),
                    "Patient").unwrap().entity_iri
            for _ in range(20)
        }
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
