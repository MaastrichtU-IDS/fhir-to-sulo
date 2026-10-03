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
