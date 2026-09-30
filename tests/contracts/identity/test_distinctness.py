"""Acceptance matrix "Identity": distinct people remain distinct."""

import pytest

from fhir_sulo.identity import (
    IdentityRequest,
    IdentityService,
    ReferenceEvidence,
    SourceScope,
)

SITE_A = SourceScope("synthea-pilot-r4", "https://fhir.example/")
SITE_B = SourceScope("other-site-r4", "https://other.example/")


def _resolve(svc, scope, resource_id, resource_type="Patient"):
    evidence = ReferenceEvidence(
        evidence_id="e",
        kind="literal-reference",
        source_scope=scope,
        resource_type=resource_type,
        resource_id=resource_id,
        canonical_url="%s%s/%s" % (scope.fhir_base_url, resource_type, resource_id),
    )
    return svc.resolve(
        IdentityRequest("%s/%s" % (resource_type, resource_id), (resource_type,), (evidence,))
    )


def test_two_patients_never_collapse_to_one_iri():
    svc = IdentityService()
    a = _resolve(svc, SITE_A, "p123")
    b = _resolve(svc, SITE_A, "p999")
    assert a.is_resolved and b.is_resolved
    assert a.identity.entity_iri != b.identity.entity_iri


def test_same_resource_id_at_two_sources_stays_two_people():
    """The conservative, source-scoped default (plan section 7 risk row)."""
    svc = IdentityService()
    a = _resolve(svc, SITE_A, "p123")
    b = _resolve(svc, SITE_B, "p123")
    assert a.is_resolved and b.is_resolved
    assert a.identity.entity_iri != b.identity.entity_iri
    assert a.identity.source_scope_id != b.identity.source_scope_id


def test_no_cross_source_merge_rule_is_approved():
    svc = IdentityService()
    scope_policy = svc.policy.identity["reference_scope"]
    assert scope_policy["default"] == "source-scoped"
    assert scope_policy["cross_source_merge"] == "requires-recorded-evidence"
    assert scope_policy["accepted_merge_evidence"] == [], (
        "a cross-source merge rule has been added to the policy table; that is a "
        "reviewed decision and needs a decision record"
    )


def test_patient_and_practitioner_with_the_same_id_stay_distinct():
    svc = IdentityService()
    patient = _resolve(svc, SITE_A, "x1", "Patient")
    practitioner = _resolve(svc, SITE_A, "x1", "Practitioner")
    assert patient.is_resolved and practitioner.is_resolved
    assert patient.identity.entity_iri != practitioner.identity.entity_iri


def test_many_patients_produce_as_many_distinct_iris():
    svc = IdentityService()
    iris = set()
    for i in range(500):
        outcome = _resolve(svc, SITE_A, "p%04d" % i)
        assert outcome.is_resolved
        iris.add(outcome.identity.entity_iri)
    assert len(iris) == 500


def test_readable_key_style_still_scopes(tmp_path):
    """``scoped-slug`` is readable but must not merge two sources' p123."""
    from fhir_sulo.policy import PolicyBundle

    bundle = PolicyBundle.load()
    import copy

    identity_policy = copy.deepcopy(dict(bundle.identity))
    identity_policy["entity_iri"]["key_style"] = "scoped-slug"
    variant = PolicyBundle(
        identity=identity_policy,
        code_interpretation=bundle.code_interpretation,
        unit=bundle.unit,
        source_dir=bundle.source_dir,
    )
    svc = IdentityService(variant)
    a = _resolve(svc, SITE_A, "p123")
    b = _resolve(svc, SITE_B, "p123")
    assert a.identity.entity_iri != b.identity.entity_iri
    assert "p123" in a.identity.entity_iri  # readable
    assert "synthea-pilot-r4" in a.identity.entity_iri


def test_legacy_key_style_rejects_a_second_source_scope():
    """The readable concept-note style is guarded against the merge it invites."""
    import copy

    from fhir_sulo.policy import PolicyBundle

    bundle = PolicyBundle.load()
    identity_policy = copy.deepcopy(dict(bundle.identity))
    identity_policy["entity_iri"]["key_style"] = "legacy-concept-note"
    identity_policy["entity_iri"]["single_source_scope"] = "synthea-pilot-r4"
    variant = PolicyBundle(
        identity=identity_policy,
        code_interpretation=bundle.code_interpretation,
        unit=bundle.unit,
        source_dir=bundle.source_dir,
    )
    svc = IdentityService(variant)

    permitted = _resolve(svc, SITE_A, "p123")
    assert permitted.is_resolved
    assert permitted.identity.entity_iri == "https://w3id.org/ontostart/fhir2sulo/person-p123"

    other = _resolve(svc, SITE_B, "p123")
    assert not other.is_resolved
    assert other.reason_code == "cross-scope-under-unscoped-key"


def test_legacy_key_style_without_a_declared_scope_fails_to_load():
    import copy

    from fhir_sulo.policy import PolicyBundle, PolicyError

    bundle = PolicyBundle.load()
    identity_policy = copy.deepcopy(dict(bundle.identity))
    identity_policy["entity_iri"]["key_style"] = "legacy-concept-note"
    identity_policy["entity_iri"]["single_source_scope"] = None
    variant = PolicyBundle(
        identity=identity_policy,
        code_interpretation=bundle.code_interpretation,
        unit=bundle.unit,
        source_dir=bundle.source_dir,
    )
    with pytest.raises(PolicyError):
        variant.validate()
