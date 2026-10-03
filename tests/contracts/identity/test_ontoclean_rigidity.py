"""DR-010: an entity kind is an identity criterion, so it must be rigid.

OntoClean: identity criteria come from RIGID properties -- ones that hold
necessarily of their instances.  "practitioner" and "patient" are ANTI-RIGID:
a person can stop being either without ceasing to exist.  ``entity_kind`` is
one of ``key_input_fields``, so an anti-rigid value there would make a role an
identity criterion, and the person's IRI would change when the role lapsed.

These tests pin the three places that went wrong, so none can come back.
"""
import json
import re
import pathlib
import unittest

import pytest

from fhir_sulo.identity import (
    IdentityRequest,
    IdentityService,
    ReferenceEvidence,
    SourceScope,
)

ROOT = pathlib.Path(__file__).resolve().parents[3]
POLICY = json.loads((ROOT / "policies" / "identity-policy.v1.json").read_text())

# Anti-rigid terms that must never name an entity kind or appear in an entity IRI.
ANTI_RIGID = ("practitioner", "patient", "clinician", "subject", "performer", "author")


def test_policy_declares_only_rigid_entity_kinds():
    declared = POLICY["entity_iri"]["entity_kind_segments"]
    offenders = [k for k in declared if k.lower() in ANTI_RIGID]
    assert not offenders, (
        "identity policy declares anti-rigid entity kind(s) %s. An entity kind is an "
        "identity criterion and must be rigid; a role belongs on a Role individual (DR-010)."
        % offenders
    )


def test_person_segment_alias_agrees_with_the_map():
    iri = POLICY["entity_iri"]
    assert iri["entity_kind_segments"]["person"] == iri["person_segment"], (
        "person_segment and entity_kind_segments['person'] disagree; one of them re-keys "
        "every person IRI"
    )


def _request(kind):
    return IdentityRequest(
        "Practitioner/c7",
        ("Practitioner",),
        (
            ReferenceEvidence(
                evidence_id="Encounter.participant[0].individual",
                kind="literal-reference",
                source_scope=SourceScope("synthea-pilot-r4", "http://example.org/fhir/"),
                resource_type="Practitioner",
                resource_id="c7",
                canonical_url="http://example.org/fhir/Practitioner/c7",
            ),
        ),
        entity_kind=kind,
    )


@pytest.mark.parametrize("kind", ANTI_RIGID)
def test_an_anti_rigid_entity_kind_is_rejected_not_slugified(kind):
    """The original defect: the service slugified ANY kind into an IRI segment."""
    outcome = IdentityService().resolve(_request(kind))
    assert not outcome.is_resolved, (
        "entity_kind=%r resolved; it must be rejected, not turned into a %r- IRI segment" % (kind, kind)
    )
    assert outcome.reason_code == "undeclared-entity-kind"


def test_a_practitioner_reference_mints_a_person_iri():
    """End of the ruling: the practitioner is a person who holds a role."""
    outcome = IdentityService().resolve(_request("person"))
    assert outcome.is_resolved
    local = outcome.unwrap().entity_iri.rsplit("/", 1)[-1]
    assert local.startswith("person-"), local
    for term in ANTI_RIGID:
        assert term not in local.lower(), (
            "entity IRI %r carries the anti-rigid term %r" % (local, term)
        )


class NoPersonIsNamedAfterARole(unittest.TestCase):
    """DR-010 applies to hand-written graphs too, not only to minted IRIs.

    Found by review: applying the ruling, a blanket ClinicianRole ->
    PractitionerRole rename turned ``ex:clinician-c7`` into
    ``ex:practitioner-c7`` -- a node typed ``ex:Person``, now named after the
    very anti-rigid property the ruling exists to keep off people.  The patient
    counterpart was ``ex:person-p123`` throughout, the same asymmetry the
    ruling was about, reintroduced while fixing it.
    """

    GRAPHS = sorted(
        list((ROOT / "tests/integration/graphs").glob("*.ttl"))
        + list((ROOT / "fixtures/expected").glob("*/*/target.nt"))
    )

    PERSON_SUBJECT = re.compile(
        r"(?:ex:|<https://w3id\.org/ontostart/fhir2sulo/)([A-Za-z0-9-]+)>?\s+"
        r"(?:a|<http://www\.w3\.org/1999/02/22-rdf-syntax-ns#type>)\s+[^.]*?"
        r"(?:ex:Person|<https://w3id\.org/ontostart/fhir2sulo/Person>)"
    )

    def test_no_person_typed_node_carries_an_anti_rigid_term(self):
        self.assertTrue(self.GRAPHS, "no graphs found to check")
        checked = 0
        for path in self.GRAPHS:
            text = path.read_text(encoding="utf-8")
            for local in self.PERSON_SUBJECT.findall(text):
                checked += 1
                for term in ANTI_RIGID:
                    with self.subTest(graph=path.name, node=local, term=term):
                        self.assertNotIn(
                            term, local.lower(),
                            "%s types %r as ex:Person, but its local name carries the "
                            "anti-rigid term %r. A person is not named after a role "
                            "(DR-010); the role goes on a Role individual."
                            % (path.name, local, term),
                        )
        self.assertGreater(checked, 0, "no ex:Person nodes found to check")


class ResourceTypeStillPartitionsPeople(unittest.TestCase):
    """The remainder of the OntoClean finding, pinned rather than papered over.

    DR-010 removed ``practitioner`` as an entity kind.  It did NOT change the
    partition: ``entity_kind`` was a deterministic function of
    ``resource_type`` (four call sites, each with one literal expected type,
    and ID-R5 rejects any mismatch), and ``resource_type`` is itself a key
    input.  So the same anti-rigid pair {Patient, Practitioner} still splits
    one human into two entities, under a provenance-sounding name.

    Review finding: nothing exercised this.  ``test_distinctness`` varies
    ``resource_id`` with the type defaulted to Patient, and the encounter
    fixtures use ``p123`` and ``c7``, which differ by id anyway -- so dropping
    ``resource_type`` from ``key_input_fields`` would have failed no test.

    These tests pin the behaviour AND say it is unresolved, so answering R8b
    changes a test that explains itself rather than silently re-keying graphs.
    """

    def _iri(self, resource_type):
        evidence = ReferenceEvidence(
            evidence_id="e",
            kind="literal-reference",
            source_scope=SourceScope("synthea-pilot-r4", "https://fhir.example/"),
            resource_type=resource_type,
            resource_id="c7",
            canonical_url="https://fhir.example/%s/c7" % resource_type,
        )
        outcome = IdentityService().resolve(
            IdentityRequest("%s/c7" % resource_type, (resource_type,), (evidence,),
                            entity_kind="person")
        )
        self.assertTrue(outcome.is_resolved, getattr(outcome, "reason", None))
        return outcome.unwrap().entity_iri

    def test_resource_type_is_still_an_identity_criterion(self):
        """R8b, unanswered. If a reviewer rules that these merge, this fails."""
        self.assertNotEqual(
            self._iri("Patient"), self._iri("Practitioner"),
            "Patient/c7 and Practitioner/c7 collapsed to one entity. No cross-record "
            "merge rule has been reviewed (R2b, accepted_merge_evidence is empty), so "
            "this is not a merge the pipeline may make on its own."
        )

    def test_neither_iri_advertises_which_role_the_record_described(self):
        """What DR-010 DID fix: the distinction is in the key, not on the label."""
        for resource_type in ("Patient", "Practitioner"):
            local = self._iri(resource_type).rsplit("/", 1)[-1]
            self.assertTrue(local.startswith("person-"), local)
            for term in ANTI_RIGID:
                self.assertNotIn(term, local.lower())

    def _key_inputs(self, resource_type):
        evidence = ReferenceEvidence(
            evidence_id="e",
            kind="literal-reference",
            source_scope=SourceScope("synthea-pilot-r4", "https://fhir.example/"),
            resource_type=resource_type,
            resource_id="c7",
            canonical_url="https://fhir.example/%s/c7" % resource_type,
        )
        outcome = IdentityService().resolve(
            IdentityRequest("%s/c7" % resource_type, (resource_type,), (evidence,),
                            entity_kind="person")
        )
        return dict(outcome.unwrap().key_inputs)

    def test_resource_type_is_the_only_thing_keeping_them_apart(self):
        """Behavioural, not a restatement of the policy.

        Review finding: the first version of this asserted
        ``"resource_type" in key_input_fields``, which checks the policy
        against itself.  This compares the key inputs the service actually
        built for the two requests and requires the difference to be exactly
        one field -- so a second discriminator appearing, or entity_kind
        diverging again, fails here rather than passing quietly.
        """
        patient = self._key_inputs("Patient")
        practitioner = self._key_inputs("Practitioner")
        differing = {k for k in set(patient) | set(practitioner)
                     if patient.get(k) != practitioner.get(k)}
        self.assertEqual(
            differing, {"resource_type"},
            "the key inputs for Patient/c7 and Practitioner/c7 differ in %s. R8b is about "
            "resource_type alone; another differing field means something else is also "
            "partitioning people and DR-010's analysis no longer describes the code."
            % sorted(differing),
        )

    def test_entity_kind_no_longer_discriminates(self):
        """DR-010 left entity_kind in key_input_fields as a constant."""
        self.assertEqual(
            self._key_inputs("Patient")["entity_kind"],
            self._key_inputs("Practitioner")["entity_kind"],
            "entity_kind differs between a Patient and a Practitioner reference again",
        )
