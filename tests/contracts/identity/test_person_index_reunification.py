"""R8b in the shape the reviewer asked for: reunify, but only on a BSN-like id.

    "i do, if there bsn like attributes to uniquely identify"

So the rule is conditional. Two records of one human become one person when
both carry the same allowlisted person-level identifier, and stay two people
otherwise. Staying two is not a failure mode here -- it is R2b, and it is what
must happen when nothing says the records are about one human.

The index exists because a BSN-style number lives on ``Patient.identifier``,
on the Patient RESOURCE, which this pipeline never ingests. It is an input to
the identity service rather than a lookup the service performs, so resolve()
stays a pure function of (request, policy, index).
"""

import unittest

from fhir_sulo.identity import (
    IdentityRequest,
    IdentityService,
    ReferenceEvidence,
    SourceScope,
)
from fhir_sulo.identity.person_index import (
    PersonIdentifierConflict,
    PersonIdentifierIndex,
)

BSN = "https://w3id.org/ontostart/fhir2sulo/synthetic/person-number"
MRN = "http://hospital.example/mrn"

MUMC = ("maastricht-umc", "https://mumc.example/fhir/")
RAD = ("radboud-umc", "https://radboud.example/fhir/")


def patient(rid, system=BSN, value="900001"):
    return {"resourceType": "Patient", "id": rid,
            "identifier": [{"system": system, "value": value}]}


def index_for(*pairs, allowlist=(BSN,)):
    out = PersonIdentifierIndex.empty()
    for (scope, _base), resource in pairs:
        out = out.merged_with(
            PersonIdentifierIndex.build([resource], scope_id=scope, allowlist=allowlist))
    return out


def person(svc, site, rid, resource_type="Patient"):
    scope, base = site
    evidence = ReferenceEvidence(
        evidence_id="e", kind="literal-reference",
        source_scope=SourceScope(scope, base), resource_type=resource_type,
        resource_id=rid, canonical_url="%s%s/%s" % (base, resource_type, rid))
    outcome = svc.resolve(IdentityRequest(
        "%s/%s" % (resource_type, rid), (resource_type,), (evidence,), entity_kind="person"))
    assert outcome.is_resolved, getattr(outcome, "reason", None)
    return outcome.unwrap()


class OneHumanAcrossTwoSystems(unittest.TestCase):
    def test_two_systems_with_one_bsn_give_one_person(self):
        """Different scope AND different resource id -- only the BSN links them."""
        svc = IdentityService(person_index=index_for(
            (MUMC, patient("123")), (RAD, patient("987"))))
        a = person(svc, MUMC, "123")
        b = person(svc, RAD, "987")
        self.assertEqual(a.entity_iri, b.entity_iri)
        self.assertEqual(a.rule_id, "ID-R12-identifier-keyed-person")

    def test_different_bsns_stay_different_people(self):
        svc = IdentityService(person_index=index_for(
            (MUMC, patient("123", value="900001")),
            (RAD, patient("987", value="900002"))))
        self.assertNotEqual(person(svc, MUMC, "123").entity_iri,
                            person(svc, RAD, "987").entity_iri)

    def test_a_patient_and_a_practitioner_sharing_a_bsn_are_one_person(self):
        """The original R8b question, now reachable from real resources."""
        pract = {"resourceType": "Practitioner", "id": "c7",
                 "identifier": [{"system": BSN, "value": "900001"}]}
        svc = IdentityService(person_index=index_for(
            (MUMC, patient("123")), (MUMC, pract)))
        self.assertEqual(person(svc, MUMC, "123").entity_iri,
                         person(svc, MUMC, "c7", "Practitioner").entity_iri)


class WithoutABsnNothingReunifies(unittest.TestCase):
    """The conditional half of the ruling, and the default."""

    def test_an_empty_index_leaves_every_system_separate(self):
        svc = IdentityService()
        self.assertEqual(len(svc.person_index), 0)
        self.assertNotEqual(person(svc, MUMC, "123").entity_iri,
                            person(svc, RAD, "123").entity_iri)

    def test_a_local_mrn_is_not_indexed_so_cannot_reunify(self):
        """An MRN identifies a record at one site, not a human."""
        svc = IdentityService(person_index=index_for(
            (MUMC, patient("123", system=MRN, value="x")),
            (RAD, patient("987", system=MRN, value="x"))))
        self.assertEqual(len(svc.person_index), 0)
        self.assertNotEqual(person(svc, MUMC, "123").entity_iri,
                            person(svc, RAD, "987").entity_iri)

    def test_a_record_absent_from_the_index_keys_on_its_address(self):
        """Partial coverage must not break the records it does not cover."""
        svc = IdentityService(person_index=index_for((MUMC, patient("123"))))
        indexed = person(svc, MUMC, "123")
        plain = person(svc, MUMC, "456")
        self.assertEqual(indexed.rule_id, "ID-R12-identifier-keyed-person")
        self.assertEqual(plain.rule_id, "ID-R1-single-candidate")
        self.assertNotEqual(indexed.entity_iri, plain.entity_iri)


class TheIndexIsAnAuditableInput(unittest.TestCase):
    def test_only_person_typed_resources_are_indexed(self):
        """An Observation's identifier describes the observation, not a person."""
        obs = {"resourceType": "Observation", "id": "o1",
               "identifier": [{"system": BSN, "value": "900001"}]}
        built = PersonIdentifierIndex.build([obs, patient("123")],
                                            scope_id="maastricht-umc", allowlist=[BSN])
        self.assertEqual(len(built), 1)
        self.assertIsNone(built.lookup("maastricht-umc", "Observation", "o1"))

    def test_the_digest_changes_with_the_contents(self):
        """Two indexes give two graphs; a run record must be able to say which."""
        a = index_for((MUMC, patient("123")))
        b = index_for((MUMC, patient("123", value="900002")))
        self.assertNotEqual(a.digest, b.digest)
        self.assertEqual(a.digest, index_for((MUMC, patient("123"))).digest)

    def test_two_scopes_do_not_overwrite_each_other_on_merge(self):
        merged = index_for((MUMC, patient("123")), (RAD, patient("123", value="900002")))
        self.assertEqual(len(merged), 2)

    def test_discordant_identifiers_on_one_record_are_a_conflict(self):
        """Choosing would make identity depend on element order."""
        confused = {"resourceType": "Patient", "id": "123", "identifier": [
            {"system": BSN, "value": "900001"}, {"system": BSN, "value": "900002"}]}
        with self.assertRaises(PersonIdentifierConflict):
            PersonIdentifierIndex.build([confused], scope_id="maastricht-umc",
                                        allowlist=[BSN])

    def test_building_is_deterministic(self):
        rows = [patient("123"), patient("456", value="900002")]
        first = PersonIdentifierIndex.build(rows, scope_id="s", allowlist=[BSN])
        second = PersonIdentifierIndex.build(reversed(rows), scope_id="s", allowlist=[BSN])
        self.assertEqual(first.digest, second.digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)


BSN_URI = "http://fhir.nl/fhir/NamingSystem/bsn"
BSN_OID = "urn:oid:2.16.840.1.113883.2.4.6.3"


def service_allowing_bsn():
    """A service with BSN promoted, aliases and all.

    The shipped policy keeps BSN at `proposed`, because enabling it is a
    governance decision. Promoting it here is the only honest way to exercise
    an aliased system.
    """
    import copy
    import dataclasses

    from fhir_sulo.policy import PolicyBundle

    base = PolicyBundle.load()
    identity = copy.deepcopy(dict(base.identity))
    for entry in identity["person_identifying_identifier_systems"]:
        if entry["system"] == BSN_URI:
            entry["status"] = "pilot-provisional"
    return IdentityService(dataclasses.replace(base, identity=identity))


class OneSystemHasMoreThanOneSpelling(unittest.TestCase):
    """BSN is a fhir.nl URI in FHIR-native systems and urn:oid:... in anything
    derived from HL7 v2 or CDA. Across several healthcare systems both arrive.

    Exact-string matching would index one spelling and miss the other, and an
    unindexed record does not fail -- it quietly keys on its address. So the
    two systems would never be reunified and nothing would say so.
    """

    def _iri(self, svc, scope, base, rid, system):
        evidence = ReferenceEvidence(
            evidence_id="e", kind="literal-reference",
            source_scope=SourceScope(scope, base), resource_type="Patient",
            resource_id=rid, canonical_url="%sPatient/%s" % (base, rid),
            identifier_system=system, identifier_value="900001")
        outcome = svc.resolve(IdentityRequest(
            "Patient/%s" % rid, ("Patient",), (evidence,), entity_kind="person"))
        self.assertTrue(outcome.is_resolved, getattr(outcome, "reason", None))
        return outcome.unwrap().entity_iri

    def test_the_uri_and_the_oid_form_are_one_person(self):
        svc = service_allowing_bsn()
        fhir_native = self._iri(svc, *MUMC, "123", BSN_URI)
        v2_derived = self._iri(svc, *RAD, "987", BSN_OID)
        self.assertEqual(fhir_native, v2_derived)

    def test_the_key_uses_the_canonical_spelling(self):
        """Not whichever spelling happened to arrive first."""
        svc = service_allowing_bsn()
        canonical = svc._person_identifier_canonical_map()
        self.assertEqual(canonical[BSN_OID], BSN_URI)
        self.assertEqual(canonical[BSN_URI], BSN_URI)

    def test_an_alias_of_a_proposed_system_still_types_nothing(self):
        """Promoting is a decision; an alias must not smuggle one in."""
        svc = IdentityService()
        self.assertNotIn(BSN_OID, svc._person_identifier_canonical_map())
        self.assertNotIn(BSN_URI, svc._person_identifier_canonical_map())


class AliasShadowingIsRefusedByPolicyValidation(unittest.TestCase):
    """DR-020. Aliasing resolves by walking entries in order, so if entry B
    listed entry A's primary system among its ``equivalent_systems`` then
    A's canonical form depended on which entry came first -- deterministic
    for a given file, silently wrong, and it merges two namespaces into one
    person."""

    def test_the_shipped_policy_has_no_shadowing(self):
        from fhir_sulo.policy import PolicyBundle

        PolicyBundle.load().validate()

    def test_one_entry_claiming_anothers_system_is_refused(self):
        import copy
        import dataclasses

        from fhir_sulo.policy import PolicyBundle, PolicyError

        base = PolicyBundle.load()
        identity = copy.deepcopy(dict(base.identity))
        systems = identity["person_identifying_identifier_systems"]
        systems[-1]["equivalent_systems"] = [systems[0]["system"]]
        with self.assertRaises(PolicyError) as caught:
            dataclasses.replace(base, identity=identity).validate()
        self.assertIn("claimed by two entries", str(caught.exception))

    def test_an_entry_may_still_repeat_its_own_primary(self):
        """Harmless redundancy must not be mistaken for a conflict."""
        import copy
        import dataclasses

        from fhir_sulo.policy import PolicyBundle

        base = PolicyBundle.load()
        identity = copy.deepcopy(dict(base.identity))
        entry = identity["person_identifying_identifier_systems"][0]
        entry["equivalent_systems"] = [entry["system"]]
        dataclasses.replace(base, identity=identity).validate()
