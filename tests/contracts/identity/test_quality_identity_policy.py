"""The quality identity question is the reviewer's, and the code says so.

Concept note section 4 and plan Gate 0: "Decide whether a quality IRI persists
across observations or is observation-specific." Agent 5 must implement both
behaviours behind a switch with a clearly marked unset default, not decide it.
"""

import copy

import pytest

from fhir_sulo.identity import (
    IdentityRequest,
    IdentityService,
    QualityIdentityPolicyUnset,
    QualityRejected,
    QualityRequest,
    ReferenceEvidence,
    SourceScope,
)
from fhir_sulo.policy import PolicyBundle

SCOPE = SourceScope("synthea-pilot-r4", "https://fhir.example/")
QUALITY_CLASS = "https://example.org/fhir-sulo/RenalFiltrationQuality"


def _bundle(mode):
    bundle = PolicyBundle.load()
    identity_policy = copy.deepcopy(dict(bundle.identity))
    identity_policy["quality_identity"]["mode"] = mode
    return PolicyBundle(
        identity=identity_policy,
        code_interpretation=bundle.code_interpretation,
        unit=bundle.unit,
        source_dir=bundle.source_dir,
    )


def _person(svc, resource_id="p123"):
    evidence = ReferenceEvidence("e", "literal-reference", SCOPE, "Patient", resource_id)
    return svc.resolve(
        IdentityRequest("Patient/%s" % resource_id, ("Patient",), (evidence,))
    ).unwrap()


def _request(person, observation_id="egfr-456", version="1", when="2026-09-02T14:00:00Z"):
    return QualityRequest(
        person=person,
        quality_class_iri=QUALITY_CLASS,
        observable_system="http://loinc.org",
        observable_code="33914-3",
        source_resource_canonical_url="https://fhir.example/Observation/%s" % observation_id,
        source_resource_version_id=version,
        effective_time=when,
    )


def test_the_shipped_default_is_unset():
    policy = PolicyBundle.load().identity["quality_identity"]
    assert policy["mode"] is None
    assert "UNSET" in policy["mode_status"]
    assert policy["reviewer_decision"] is None
    assert policy["unset_behaviour"] == "reject"
    assert set(policy["allowed_modes"]) == {
        "persistent-per-person-code",
        "per-observation",
    }
    assert policy["reviewer_question"]


def test_unset_policy_rejects_rather_than_guessing():
    svc = IdentityService()
    outcome = svc.resolve_quality(_request(_person(svc)))
    assert isinstance(outcome, QualityRejected)
    assert outcome.reason_code == "quality-identity-policy-unset"
    assert "reviewer" in outcome.reason
    with pytest.raises(QualityIdentityPolicyUnset):
        outcome.unwrap()
    with pytest.raises(QualityIdentityPolicyUnset):
        outcome.quality_iri


def test_persistent_mode_reuses_one_quality_across_observations():
    svc = IdentityService(_bundle("persistent-per-person-code"))
    person = _person(svc)
    first = svc.resolve_quality(_request(person, "egfr-456", "1", "2026-09-02T14:00:00Z"))
    second = svc.resolve_quality(_request(person, "egfr-789", "3", "2027-01-05T09:30:00Z"))
    assert first.is_resolved and second.is_resolved
    assert first.identity.quality_iri == second.identity.quality_iri
    assert first.identity.mode == "persistent-per-person-code"


def test_per_observation_mode_keeps_independent_records_apart():
    svc = IdentityService(_bundle("per-observation"))
    person = _person(svc)
    first = svc.resolve_quality(_request(person, "egfr-456", "1", "2026-09-02T14:00:00Z"))
    second = svc.resolve_quality(_request(person, "egfr-789", "3", "2027-01-05T09:30:00Z"))
    assert first.is_resolved and second.is_resolved
    assert first.identity.quality_iri != second.identity.quality_iri

    replay = svc.resolve_quality(_request(person, "egfr-456", "1", "2026-09-02T14:00:00Z"))
    assert replay.identity.quality_iri == first.identity.quality_iri


def test_the_two_modes_do_not_produce_the_same_iri():
    person = _person(IdentityService())
    persistent = IdentityService(_bundle("persistent-per-person-code")).resolve_quality(
        _request(person)
    )
    per_obs = IdentityService(_bundle("per-observation")).resolve_quality(_request(person))
    assert persistent.identity.quality_iri != per_obs.identity.quality_iri


def test_per_observation_mode_rejects_a_request_missing_its_keys():
    svc = IdentityService(_bundle("per-observation"))
    person = _person(svc)
    incomplete = QualityRequest(
        person=person,
        quality_class_iri=QUALITY_CLASS,
        observable_system="http://loinc.org",
        observable_code="33914-3",
    )
    outcome = svc.resolve_quality(incomplete)
    assert not outcome.is_resolved
    assert outcome.reason_code == "incomplete-key-inputs"


def test_two_people_never_share_a_quality_iri_in_either_mode():
    for mode in ("persistent-per-person-code", "per-observation"):
        svc = IdentityService(_bundle(mode))
        a = svc.resolve_quality(_request(_person(svc, "p123")))
        b = svc.resolve_quality(_request(_person(svc, "p999")))
        assert a.identity.quality_iri != b.identity.quality_iri, mode


def test_an_unknown_mode_fails_policy_validation():
    from fhir_sulo.policy import PolicyError

    with pytest.raises(PolicyError):
        _bundle("whatever-feels-right").validate()
