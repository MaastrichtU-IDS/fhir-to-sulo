"""Entity IRIs must survive policy edits that did not change the answer.

Agent 1's engine spike found the pinned ShEx.js build ships no ``id()``
function (CD-1), so node identity comes from source IRIs plus this service.
That makes Gate 4's "unchanged reprocessing changes no triples" depend on
these keys not moving for incidental reasons.

The key is therefore built from ``entity_iri.key_revision``, a separate,
deliberately sticky field - never from the policy table's semantic version.
"""

import copy

import pytest

from fhir_sulo.identity import (
    IdentityRequest,
    IdentityService,
    QualityRequest,
    ReferenceEvidence,
    SourceScope,
)
from fhir_sulo.policy import PolicyBundle, PolicyError, parse_policy_version

SCOPE = SourceScope("synthea-pilot-r4", "https://fhir.example/")
REQUEST = IdentityRequest(
    "Patient/p123",
    ("Patient",),
    (ReferenceEvidence("e", "literal-reference", SCOPE, "Patient", "p123"),),
)


def _variant(mutate):
    bundle = PolicyBundle.load()
    identity_policy = copy.deepcopy(dict(bundle.identity))
    code = copy.deepcopy(dict(bundle.code_interpretation))
    unit = copy.deepcopy(dict(bundle.unit))
    mutate(identity_policy, code, unit)
    return PolicyBundle(
        identity=identity_policy,
        code_interpretation=code,
        participation_type=bundle.participation_type,
        unit=unit,
        source_dir=bundle.source_dir,
    )


def _iri(bundle):
    return IdentityService(bundle).resolve(REQUEST).identity.entity_iri


def _quality_iri(bundle):
    svc = IdentityService(bundle)
    person = svc.resolve(REQUEST).unwrap()
    return svc.resolve_quality(
        QualityRequest(
            person=person,
            quality_class_iri="https://w3id.org/ontostart/fhir2sulo/RenalFiltrationQuality",
            observable_system="http://loinc.org",
            observable_code="33914-3",
            source_resource_canonical_url="https://fhir.example/Observation/egfr-456",
            source_resource_version_id="1",
            effective_time="2026-09-02T14:00:00Z",
        )
    ).identity.quality_iri


BASELINE = _iri(PolicyBundle.load())


@pytest.mark.parametrize(
    "label,mutate",
    [
        (
            "identity table version bump",
            lambda i, c, u: i.__setitem__("version", "1.4.2"),
        ),
        (
            "all three table versions bumped",
            lambda i, c, u: (
                i.__setitem__("version", "2.0.0"),
                c.__setitem__("version", "2.0.0"),
                u.__setitem__("version", "2.0.0"),
            ),
        ),
        (
            "reviewer answers the quality question",
            lambda i, c, u: i["quality_identity"].__setitem__(
                "mode", "persistent-per-person-code"
            ),
        ),
        (
            "a new code interpretation entry is added",
            lambda i, c, u: c["entries"].append(
                dict(c["entries"][0], entry_id="CODE-NEW", code="99999-9")
            ),
        ),
        (
            "a unit is approved by the reviewer",
            lambda i, c, u: u["units"][0].__setitem__("review_status", "approved"),
        ),
        (
            "prose in the identity policy is reworded",
            lambda i, c, u: i["quality_identity"].__setitem__(
                "reviewer_question", "reworded for the reviewer"
            ),
        ),
        (
            "a resolution rule note is clarified",
            lambda i, c, u: i["resolution_rules"][0].__setitem__("when", "clarified"),
        ),
    ],
)
def test_entity_iris_do_not_move_on_an_unrelated_policy_edit(label, mutate):
    variant = _variant(mutate)
    assert variant.policy_version != PolicyBundle.load().policy_version, (
        "%s should change the policy version" % label
    )
    assert _iri(variant) == BASELINE, "%s moved the entity IRI" % label


def test_bumping_the_key_revision_is_the_one_thing_that_re_keys():
    variant = _variant(lambda i, c, u: i["entity_iri"].__setitem__("key_revision", "2"))
    assert _iri(variant) != BASELINE


def test_quality_iris_are_stable_under_an_unrelated_edit():
    persistent = _variant(
        lambda i, c, u: i["quality_identity"].__setitem__("mode", "persistent-per-person-code")
    )
    baseline = _quality_iri(persistent)

    bumped = _variant(
        lambda i, c, u: (
            i["quality_identity"].__setitem__("mode", "persistent-per-person-code"),
            i.__setitem__("version", "3.1.4"),
            u["units"][0].__setitem__("review_status", "approved"),
        )
    )
    assert _quality_iri(bumped) == baseline


def test_changing_the_quality_mode_does_move_quality_iris():
    """Unavoidable and intended: the two modes key on different inputs."""
    persistent = _variant(
        lambda i, c, u: i["quality_identity"].__setitem__("mode", "persistent-per-person-code")
    )
    per_observation = _variant(
        lambda i, c, u: i["quality_identity"].__setitem__("mode", "per-observation")
    )
    assert _quality_iri(persistent) != _quality_iri(per_observation)


def test_a_policy_that_keys_on_its_own_version_is_rejected():
    variant = _variant(
        lambda i, c, u: i["entity_iri"].__setitem__(
            "key_input_fields",
            ["key_scheme", "policy_version", "entity_kind", "source_scope_id",
             "resource_type", "resource_id"],
        )
    )
    with pytest.raises(PolicyError):
        variant.validate()


# -- the single policy version string for RunRecord ---------------------------


def test_policy_version_is_a_single_resolvable_string():
    bundle = PolicyBundle.load()
    value = bundle.policy_version
    assert isinstance(value, str) and "\n" not in value
    parts = parse_policy_version(value)
    assert parts["bundle"] == "fhir-sulo-policies"
    assert parts["identity"] == bundle.identity["version"]
    assert parts["code_interpretation"] == bundle.code_interpretation["version"]
    assert parts["unit"] == bundle.unit["version"]
    assert bundle.bundle_digest.startswith(parts["digest_prefix"])
    assert bundle.matches_policy_version(value)


def test_terminology_snapshot_is_a_single_string():
    bundle = PolicyBundle.load()
    assert bundle.terminology_snapshot == "pilot-pinned-subset-2026-09-29"


def test_the_policy_version_changes_when_any_table_changes():
    before = PolicyBundle.load().policy_version
    variant = _variant(lambda i, c, u: u["units"][0].__setitem__("review_status", "approved"))
    assert variant.policy_version != before
    assert not PolicyBundle.load().matches_policy_version(variant.policy_version)


def test_a_foreign_policy_version_string_is_rejected():
    for bad in ("", "1.0.0", "someone-elses/identity-1+code-1+unit-1", "fhir-sulo-policies/x"):
        with pytest.raises(PolicyError):
            parse_policy_version(bad)


def test_every_audit_record_carries_the_run_record_fields():
    record = IdentityService().resolve(REQUEST).record.to_dict()
    versions = record["policy_versions"]
    assert parse_policy_version(versions["policy_version"])
    assert versions["terminology_snapshot"]
    assert versions["entity_key_revision"] == "1"
    assert versions["quality_key_revision"] == "1"
