"""IR-604: contained-reference scoping belongs to the service, not its callers.

A FHIR contained resource has no existence outside the resource that contains
it, so two Observations that each carry a contained Patient `#p-inline`
describe two different people. That rule was previously applied by every
caller -- `pipeline/services.py` baked `"<scope>|contained|<url>"` into
`SourceScope.scope_id` and stripped the `#` by hand, and `ingest/identity_port.py`'s
`MockIdentityService` had a second formula that disagreed on the scope-key
shape, the digest length and the local-name prefix.

These tests assert the *service* enforces it, from the declared policy, so a
caller cannot get it wrong by omission. The behaviour visible to existing
callers is unchanged: `tests/contracts/maps/test_encounter_gate3.py` and the
`egfr-contained-subject` / `enc-contained-practitioner` expected graphs still
match byte for byte.
"""

import pytest

from fhir_sulo.identity import (
    IdentityRequest,
    IdentityService,
    IdentityUnavailable,
    ReferenceEvidence,
    SourceScope,
)
from fhir_sulo.policy import PolicyBundle, PolicyError

SCOPE = SourceScope("synthea-pilot-r4", "https://fhir.example/")
OBS_1 = "https://fhir.example/Observation/egfr-456"
OBS_2 = "https://fhir.example/Observation/egfr-789"


def _contained(container_url, resource_id="#p-inline", evidence_id="e"):
    return ReferenceEvidence(
        evidence_id=evidence_id,
        kind="contained",
        source_scope=SCOPE,
        resource_type="Patient",
        resource_id=resource_id,
        canonical_url=None,
        container_url=container_url,
    )


def _request(container_url, resource_id="#p-inline", evidence_id="e"):
    return IdentityRequest(
        reference_literal=resource_id,
        expected_resource_types=("Patient",),
        candidates=(_contained(container_url, resource_id, evidence_id),),
        referring_resource_url=container_url,
    )


def _iri(svc, container_url, resource_id="#p-inline"):
    outcome = svc.resolve(_request(container_url, resource_id))
    assert outcome.is_resolved, getattr(outcome, "reason", None)
    return outcome.identity.entity_iri


@pytest.fixture()
def svc():
    return IdentityService()


# -- the rule itself ---------------------------------------------------------


def test_the_same_inline_id_in_two_containers_is_two_people(svc):
    """The headline invariant. This passed before IR-604 and must still pass."""
    assert _iri(svc, OBS_1) != _iri(svc, OBS_2)


def test_the_same_inline_id_in_the_same_container_is_one_person(svc):
    """Scoping must not over-separate: one container, one entity, every time."""
    assert _iri(svc, OBS_1) == _iri(svc, OBS_1)


def test_the_caller_no_longer_has_to_pre_scope_anything(svc):
    """The whole point: callers pass the plain dataset scope and the facts."""
    outcome = svc.resolve(_request(OBS_1))
    assert outcome.is_resolved
    assert outcome.identity.rule_id == "ID-R8-contained-scoped-to-its-container"
    # The service, not the caller, put the container into the scope.
    assert outcome.identity.source_scope_id == "synthea-pilot-r4|contained|" + OBS_1
    assert outcome.identity.key_inputs["source_scope_id"].endswith(OBS_1)


def test_the_leading_hash_is_normalised_away(svc):
    """'#p-inline' and 'p-inline' name the same contained resource."""
    assert _iri(svc, OBS_1, "#p-inline") == _iri(svc, OBS_1, "p-inline")


def test_a_contained_person_differs_from_a_top_level_one_with_the_same_id(svc):
    contained = _iri(svc, OBS_1, "#p123")
    top_level = svc.resolve(
        IdentityRequest(
            "Patient/p123",
            ("Patient",),
            (
                ReferenceEvidence(
                    "e", "literal-reference", SCOPE, "Patient", "p123",
                    canonical_url="https://fhir.example/Patient/p123",
                ),
            ),
        )
    )
    assert top_level.is_resolved
    assert contained != top_level.identity.entity_iri


def test_two_inline_ids_in_one_container_stay_distinct(svc):
    assert _iri(svc, OBS_1, "#p-inline") != _iri(svc, OBS_1, "#p-other")


# -- the unscopable case is rejected, not guessed ----------------------------


def test_a_contained_reference_with_no_container_is_rejected(svc):
    """Falling back to the dataset scope is the merge this rule prevents."""
    outcome = svc.resolve(
        IdentityRequest("#p-inline", ("Patient",), (_contained(None),))
    )
    assert not outcome.is_resolved
    assert outcome.reason_code == "contained-reference-unscoped"
    assert outcome.record.rule_id == "ID-R9-contained-without-a-container"
    with pytest.raises(IdentityUnavailable):
        outcome.unwrap()
    with pytest.raises(IdentityUnavailable):
        outcome.entity_iri


def test_an_unscopable_contained_reference_never_reaches_the_keying_path(svc):
    """Even mixed in with a scopable one, nothing is keyed."""
    outcome = svc.resolve(
        IdentityRequest(
            "#p-inline",
            ("Patient",),
            (_contained(OBS_1, evidence_id="a"), _contained(None, evidence_id="b")),
        )
    )
    assert not outcome.is_resolved
    assert outcome.reason_code == "contained-reference-unscoped"


def test_two_containers_are_ambiguous_not_silently_merged(svc):
    """Two candidates that disagree on container are discordant, as they should be."""
    outcome = svc.resolve(
        IdentityRequest(
            "#p-inline",
            ("Patient",),
            (_contained(OBS_1, evidence_id="a"), _contained(OBS_2, evidence_id="b")),
        )
    )
    assert not outcome.is_resolved
    assert outcome.reason_code == "ambiguous-reference"


def test_candidate_order_does_not_change_the_contained_result(svc):
    a = _contained(OBS_1, evidence_id="a")
    b = _contained(OBS_1, "p-inline", evidence_id="b")
    forward = svc.resolve(IdentityRequest("#p-inline", ("Patient",), (a, b)))
    reverse = svc.resolve(IdentityRequest("#p-inline", ("Patient",), (b, a)))
    assert forward.is_resolved and reverse.is_resolved
    assert forward.identity.entity_iri == reverse.identity.entity_iri


# -- lineage and audit -------------------------------------------------------


def test_the_record_shows_both_the_raw_and_the_derived_scope(svc):
    record = svc.resolve(_request(OBS_1)).record.to_dict()
    evidence = record["evidence"][0]
    assert evidence["source_scope"]["scope_id"] == "synthea-pilot-r4"   # raw
    assert evidence["container_url"] == OBS_1
    assert record["outcome"]["source_scope_id"].endswith(OBS_1)         # derived
    assert record["rule_id"] == "ID-R8-contained-scoped-to-its-container"


def test_non_contained_evidence_is_untouched(svc):
    """A literal reference must not acquire a container_url key by accident."""
    evidence = ReferenceEvidence(
        "e", "literal-reference", SCOPE, "Patient", "p123",
        canonical_url="https://fhir.example/Patient/p123",
    )
    outcome = svc.resolve(IdentityRequest("Patient/p123", ("Patient",), (evidence,)))
    assert outcome.is_resolved
    assert outcome.identity.source_scope_id == "synthea-pilot-r4"
    assert "container_url" not in evidence.as_dict()
    assert outcome.identity.rule_id == "ID-R1-single-candidate"


# -- the rule is policy, and the policy is enforced --------------------------


def test_the_rule_is_declared_in_the_policy_table():
    block = PolicyBundle.load().identity["contained_reference_scoping"]
    assert block["applies_to_evidence_kind"] == "contained"
    assert "{container_url}" in block["scope_id_template"]
    assert block["missing_container_url"] == "rejected"
    assert block["rationale"]


@pytest.mark.parametrize(
    "mutate,why",
    [
        (
            lambda b: b.pop("contained_reference_scoping"),
            "no block at all",
        ),
        (
            lambda b: b["contained_reference_scoping"].__setitem__(
                "scope_id_template", "{scope_id}|contained"
            ),
            "template drops the container, so every container shares a scope",
        ),
        (
            lambda b: b["contained_reference_scoping"].__setitem__(
                "missing_container_url", "source-only"
            ),
            "an unscopable contained reference would no longer be rejected",
        ),
    ],
)
def test_a_policy_that_weakens_the_rule_fails_to_load(mutate, why):
    import copy

    bundle = PolicyBundle.load()
    identity_policy = copy.deepcopy(dict(bundle.identity))
    mutate(identity_policy)
    variant = PolicyBundle(
        identity=identity_policy,
        code_interpretation=bundle.code_interpretation,
        unit=bundle.unit,
        source_dir=bundle.source_dir,
    )
    with pytest.raises(PolicyError):
        variant.validate()
