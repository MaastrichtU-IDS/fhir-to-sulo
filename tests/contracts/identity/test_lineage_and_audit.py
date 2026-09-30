"""Lineage and audit properties of the identity service.

Concept note section 2: never assert ``owl:sameAs`` between a FHIR resource and
a person. Concept note section 4: the identity step must be auditable.
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
from fhir_sulo.policy import PolicyBundle

SCOPE = SourceScope("synthea-pilot-r4", "https://fhir.example/")
EVIDENCE = ReferenceEvidence(
    evidence_id="e1",
    kind="literal-reference",
    source_scope=SCOPE,
    resource_type="Patient",
    resource_id="p123",
    canonical_url="https://fhir.example/Patient/p123",
    resource_version_id="1",
    detail={"element": "Observation.subject"},
)
REQUEST = IdentityRequest(
    reference_literal="Patient/p123",
    expected_resource_types=("Patient",),
    candidates=(EVIDENCE,),
    referring_resource_url="https://fhir.example/Observation/egfr-456/_history/1",
)


def test_fhir_reference_is_retained_as_lineage():
    outcome = IdentityService().resolve(REQUEST)
    lineage = outcome.identity.lineage()
    assert lineage["source_reference_literal"] == "Patient/p123"
    assert lineage["source_canonical_url"] == "https://fhir.example/Patient/p123"
    assert lineage["source_scope_id"] == "synthea-pilot-r4"
    assert lineage["entity_iri"].startswith("https://w3id.org/ontostart/fhir2sulo/person-")
    assert lineage["entity_iri"] != lineage["source_canonical_url"]


def test_no_equivalence_is_claimed_between_the_resource_and_the_person():
    outcome = IdentityService().resolve(REQUEST)
    lineage = outcome.identity.lineage()
    assert lineage["equivalence_asserted"] is False
    assert lineage["lineage_predicate"] == "http://www.w3.org/ns/prov#wasDerivedFrom"

    forbidden = IdentityService().policy.identity["lineage"][
        "forbidden_predicates_between_fhir_resource_and_entity"
    ]
    assert "http://www.w3.org/2002/07/owl#sameAs" in forbidden

    blob = repr(outcome.record.to_dict()) + repr(lineage)
    assert "sameAs" not in blob
    assert "owl#" not in blob


def test_the_audit_record_has_every_required_part():
    outcome = IdentityService().resolve(REQUEST)
    record = outcome.record.to_dict()
    assert record["service"] == "identity"
    assert record["rule_id"] == "ID-R1-single-candidate"
    assert record["status"] == "mapped"
    assert record["inputs"]["reference_literal"] == "Patient/p123"
    assert record["inputs"]["referring_resource_url"].endswith("_history/1")
    assert record["evidence"][0]["evidence_id"] == "e1"
    assert record["evidence"][0]["kind"] == "literal-reference"
    assert record["outcome"]["entity_iri"] == outcome.identity.entity_iri
    assert record["outcome"]["key_inputs"]["resource_id"] == "p123"
    versions = record["policy_versions"]
    assert versions["identity_policy"] == "1.0.0"
    assert len(versions["policy_bundle_digest"]) == 64
    assert len(record["decision_id"]) == 64


def test_the_audit_record_carries_no_timestamp():
    """Timestamps belong in the RunRecord, not in a reproducible decision."""
    record = IdentityService().resolve(REQUEST).record.to_dict()
    blob = repr(record).lower()
    for token in ("timestamp", "generated_at", "run_id", "2026-09-29t"):
        assert token not in blob, token


def test_a_policy_change_changes_the_bundle_digest():
    bundle = PolicyBundle.load()
    before = bundle.bundle_digest
    tweaked = copy.deepcopy(dict(bundle.identity))
    tweaked["entity_iri"]["key_length_hex_chars"] = 24
    variant = PolicyBundle(
        identity=tweaked,
        code_interpretation=bundle.code_interpretation,
        unit=bundle.unit,
        source_dir=bundle.source_dir,
    )
    assert variant.bundle_digest != before


def test_key_inputs_are_recorded_so_a_reviewer_can_recompute_the_iri():
    from fhir_sulo.policy import key_fragment

    svc = IdentityService()
    outcome = svc.resolve(REQUEST)
    key_inputs = outcome.identity.key_inputs
    fields = svc.policy.identity["entity_iri"]["key_input_fields"]
    length = svc.policy.identity["entity_iri"]["key_length_hex_chars"]
    recomputed = "https://w3id.org/ontostart/fhir2sulo/person-" + key_fragment(
        fields, key_inputs, length=length
    )
    assert recomputed == outcome.identity.entity_iri
