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
