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


def test_the_shipped_mode_is_the_reviewers_answer_to_R2():
    """R2 was answered B (per-observation) on 2026-09-30.

    This test previously asserted the mode was unset, which was correct until
    the reviewer answered. It is inverted rather than deleted, because the
    thing worth guarding is that the shipped mode is a *recorded decision* and
    not a default someone slipped in: the record must name the item, the
    answer and the date, and must still carry the reviewer's own caveat that
    the underlying question is unresolved.
    """
    policy = PolicyBundle.load().identity["quality_identity"]
    assert policy["mode"] == "per-observation"
    assert set(policy["allowed_modes"]) == {
        "persistent-per-person-code",
        "per-observation",
    }

    decision = policy["reviewer_decision"]
    assert decision is not None, "a set mode must carry the decision that set it"
    assert decision["item"] == "R2"
    assert decision["answer"].startswith("B")
    assert "provisional" in decision["status"]

    # The reviewer said this is safest, not settled. If that caveat is ever
    # dropped, the mode has been promoted to a conclusion nobody reached.
    assert "not yet resolved" in decision["reviewer_words"]
    assert decision["revisit"]

    # Switching remains possible and remains a migration.
    assert policy["unset_behaviour"] == "reject"


def test_an_unset_policy_still_rejects():
    """The guard R2's answer did not remove.

    The shipped bundle now names a mode, so the rejection path has to be
    exercised against a deliberately unset bundle. Without this, answering
    R2 would silently delete the protection that stopped a run guessing.
    """
    svc = IdentityService(_bundle(None))
    outcome = svc.resolve_quality(_request(_person(svc)))
    assert isinstance(outcome, QualityRejected)
    assert outcome.reason_code == "quality-identity-policy-unset"
    assert "reviewer" in outcome.reason
    with pytest.raises(QualityIdentityPolicyUnset):
        outcome.unwrap()
    with pytest.raises(QualityIdentityPolicyUnset):
        outcome.quality_iri


def test_the_shipped_bundle_resolves_a_quality_now_that_R2_is_answered():
    """Consequence of the answer: quality requests succeed on the shipped policy."""
    svc = IdentityService()
    outcome = svc.resolve_quality(_request(_person(svc)))
    assert outcome.is_resolved, getattr(outcome, "reason", outcome)


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
