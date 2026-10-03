"""DR-010: an entity kind is an identity criterion, so it must be rigid.

OntoClean: identity criteria come from RIGID properties -- ones that hold
necessarily of their instances.  "practitioner" and "patient" are ANTI-RIGID:
a person can stop being either without ceasing to exist.  ``entity_kind`` is
one of ``key_input_fields``, so an anti-rigid value there would make a role an
identity criterion, and the person's IRI would change when the role lapsed.

These tests pin the three places that went wrong, so none can come back.
"""
import json
import pathlib

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
