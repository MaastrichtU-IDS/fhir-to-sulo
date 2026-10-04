"""Acceptance matrix "Identity": ambiguous identity never silently merges.

These tests check the *API shape*, not just the behaviour: the point of the
contract is that a caller cannot get a person IRI out of an ambiguous
reference even by accident.
"""

import dataclasses

import pytest

from fhir_sulo.identity import (
    EntityIdentity,
    IdentityRejected,
    IdentityRequest,
    IdentityService,
    IdentityUnavailable,
    ReferenceEvidence,
    SourceScope,
    require_identity,
)

SCOPE = SourceScope("fhir-sulo-fixtures-r4", "https://fhir.example/")


def _ev(evidence_id, resource_id, resource_type="Patient", scope=SCOPE):
    return ReferenceEvidence(evidence_id, "literal-reference", scope, resource_type, resource_id)


def _svc():
    return IdentityService()


@pytest.mark.parametrize(
    "request_obj,expected_reason",
    [
        (IdentityRequest("Patient/ghost", ("Patient",), ()), "unresolved-reference"),
        (
            IdentityRequest(
                "Patient/?identifier=x",
                ("Patient",),
                (_ev("m1", "p123"), _ev("m2", "p456")),
            ),
            "ambiguous-reference",
        ),
        (
            IdentityRequest(
                "Patient/p123",
                ("Patient",),
                (_ev("m1", "p123"), _ev("m2", "p123", scope=SourceScope("other-site-r4"))),
            ),
            "ambiguous-reference",
        ),
        (
            IdentityRequest("Group/g1", ("Patient",), (_ev("g", "g1", "Group"),)),
            "unexpected-resource-type",
        ),
        (
            IdentityRequest("Patient/", ("Patient",), (_ev("e", "   "),)),
            "incomplete-key-inputs",
        ),
    ],
)
def test_ambiguous_or_unresolved_is_rejected(request_obj, expected_reason):
    outcome = _svc().resolve(request_obj)
    assert not outcome.is_resolved
    assert isinstance(outcome, IdentityRejected)
    assert outcome.reason_code == expected_reason
    assert outcome.status == "rejected"


def test_rejection_has_no_iri_attribute_of_any_kind():
    outcome = _svc().resolve(
        IdentityRequest("Patient/?identifier=x", ("Patient",), (_ev("a", "p1"), _ev("b", "p2")))
    )
    field_names = {f.name for f in dataclasses.fields(outcome)}
    assert field_names == {"reason_code", "reason", "record"}
    for leaky in ("identity", "entity_iri", "iri", "person", "person_iri", "value"):
        with pytest.raises(IdentityUnavailable):
            getattr(outcome, leaky)


def test_unwrap_on_a_rejection_raises():
    outcome = _svc().resolve(IdentityRequest("Patient/ghost", ("Patient",), ()))
    with pytest.raises(IdentityUnavailable) as excinfo:
        outcome.unwrap()
    assert excinfo.value.reason_code == "unresolved-reference"
    assert excinfo.value.record.status == "rejected"
    with pytest.raises(IdentityUnavailable):
        require_identity(outcome)


def test_no_public_api_returns_an_optional_iri():
    """A caller can never write ``if iri is None`` and forget the else branch."""
    import inspect
    import typing

    import fhir_sulo.identity as pkg

    hints_bad = []
    for name in ("resolve", "resolve_quality"):
        sig = inspect.signature(getattr(IdentityService, name))
        annotation = sig.return_annotation
        rendered = str(annotation)
        if "Optional" in rendered or "None" in rendered:
            hints_bad.append("%s -> %s" % (name, rendered))
    assert not hints_bad, hints_bad

    # And no helper hands out a bare string IRI from an outcome union.
    for name in dir(pkg):
        obj = getattr(pkg, name)
        if inspect.isfunction(obj):
            rendered = str(inspect.signature(obj).return_annotation)
            assert "Optional" not in rendered, "%s returns %s" % (name, rendered)


def test_str_of_a_rejection_does_not_look_like_an_iri():
    outcome = _svc().resolve(IdentityRequest("Patient/ghost", ("Patient",), ()))
    text = str(outcome)
    assert "http" not in text
    assert text.startswith("IdentityRejected(")


def test_concordant_duplicate_evidence_is_not_a_merge():
    """Several pieces of evidence naming the same resource is not ambiguity."""
    outcome = _svc().resolve(
        IdentityRequest("Patient/p123", ("Patient",), (_ev("a", "p123"), _ev("b", "p123")))
    )
    assert outcome.is_resolved
    assert outcome.identity.rule_id == "ID-R4-concordant-candidates"
    single = _svc().resolve(IdentityRequest("Patient/p123", ("Patient",), (_ev("a", "p123"),)))
    assert outcome.identity.entity_iri == single.identity.entity_iri


def test_rejection_still_carries_a_full_audit_record():
    outcome = _svc().resolve(
        IdentityRequest("Patient/?identifier=x", ("Patient",), (_ev("a", "p1"), _ev("b", "p2")))
    )
    record = outcome.record.to_dict()
    assert record["service"] == "identity"
    assert record["rule_id"] == "ID-R3-discordant-candidates"
    assert record["status"] == "rejected"
    assert record["outcome"]["entity_iri"] is None
    assert len(record["evidence"]) == 2
    assert record["policy_versions"]["policy_bundle_digest"]
    assert record["decision_id"]
