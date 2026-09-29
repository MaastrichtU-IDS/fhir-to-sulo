"""Code resolution contract.

Concept note section 2: "A code-to-class interpretation needs a reviewed
terminology rule; a FHIR code literal alone is not an OWL class assertion."
Plan section 2: "unknown or incompatible codes/units have explicit outcomes;
source codes are retained."
"""

import dataclasses

import pytest

from fhir_sulo.terminology import (
    CodeInterpreted,
    CodeRejected,
    CodeSourceOnly,
    Coding,
    TerminologyService,
    TerminologyUnavailable,
)

PINNED = {
    "33914-3": "https://example.org/fhir-sulo/EGFRResult",
    "8480-6": "https://example.org/fhir-sulo/SystolicBloodPressureResult",
    "8462-4": "https://example.org/fhir-sulo/DiastolicBloodPressureResult",
}


@pytest.fixture(scope="module")
def term():
    return TerminologyService()


@pytest.mark.parametrize("code,expected_class", sorted(PINNED.items()))
def test_pinned_codes_resolve_to_their_reviewed_class(term, code, expected_class):
    outcome = term.resolve_code(Coding("http://loinc.org", code))
    assert isinstance(outcome, CodeInterpreted)
    assert outcome.status == "mapped"
    assert outcome.interpretation.result_class == expected_class
    assert outcome.interpretation.quality_class
    assert outcome.interpretation.expected_unit_dimension


def test_an_interpretation_without_clinical_signoff_says_so(term):
    """Nothing is clinically approved yet; the outcome must not pretend it is."""
    outcome = term.resolve_code(Coding("http://loinc.org", "33914-3"))
    assert outcome.interpretation.review_status == "pilot-provisional"
    assert outcome.interpretation.clinical_signoff is False


def test_unknown_code_in_a_known_system_is_source_only(term):
    outcome = term.resolve_code(Coding("http://loinc.org", "00000-0"))
    assert isinstance(outcome, CodeSourceOnly)
    assert outcome.status == "source-only"
    assert outcome.reason_code == "unknown-code"


def test_unknown_code_system_is_source_only(term):
    outcome = term.resolve_code(Coding("http://example.org/private-codes", "X1"))
    assert isinstance(outcome, CodeSourceOnly)
    assert outcome.reason_code == "unknown-code-system"


def test_a_recognised_system_with_no_entries_is_still_source_only(term):
    outcome = term.resolve_code(Coding("http://snomed.info/sct", "44054006"))
    assert outcome.status == "source-only"
    assert outcome.reason_code == "unknown-code"


def test_a_proposed_entry_is_not_interpreted(term):
    """The BP panel code is drafted but not reviewed, so it types nothing."""
    outcome = term.resolve_code(Coding("http://loinc.org", "85354-9"))
    assert outcome.status == "source-only"
    assert outcome.reason_code == "interpretation-not-approved"


def test_an_incomplete_coding_is_rejected(term):
    assert term.resolve_code(Coding("http://loinc.org", "")).status == "rejected"
    assert term.resolve_code(Coding("", "33914-3")).status == "rejected"


def test_an_observation_kind_mismatch_is_explicit(term):
    outcome = term.resolve_code(Coding("http://loinc.org", "33914-3"), expected_kind="panel")
    assert outcome.status == "source-only"
    assert outcome.reason_code == "observation-kind-mismatch"


@pytest.mark.parametrize(
    "coding",
    [
        Coding("http://loinc.org", "33914-3", "eGFR"),
        Coding("http://loinc.org", "00000-0", "mystery"),
        Coding("http://example.org/private-codes", "X1", "local"),
        Coding("http://loinc.org", "85354-9", "BP panel"),
    ],
)
def test_the_source_code_and_system_are_retained_on_every_outcome(term, coding):
    outcome = term.resolve_code(coding)
    retained = outcome.source_retained()
    assert retained["system"] == coding.system
    assert retained["code"] == coding.code
    assert retained["display"] == coding.display
    assert outcome.record.to_dict()["outcome"]["source"] == coding.as_dict()


def test_a_non_interpreted_outcome_has_no_class_attribute(term):
    """No caller can read a domain class off an unmapped code."""
    outcome = term.resolve_code(Coding("http://loinc.org", "00000-0"))
    field_names = {f.name for f in dataclasses.fields(outcome)}
    assert "result_class" not in field_names
    assert "interpretation" not in field_names
    for leaky in ("result_class", "quality_class", "domain_class", "interpretation"):
        with pytest.raises(TerminologyUnavailable):
            getattr(outcome, leaky)
    with pytest.raises(TerminologyUnavailable):
        outcome.unwrap()


def test_no_class_is_invented_for_an_unknown_code(term):
    outcome = term.resolve_code(Coding("http://loinc.org", "00000-0"))
    record = outcome.record.to_dict()
    assert record["outcome"]["result_class"] is None
    assert record["outcome"]["quality_class"] is None
    assert record["outcome"]["source_retained"] is True


def test_every_outcome_carries_an_auditable_record(term):
    for coding in (
        Coding("http://loinc.org", "33914-3"),
        Coding("http://loinc.org", "00000-0"),
        Coding("http://loinc.org", ""),
    ):
        record = term.resolve_code(coding).record.to_dict()
        assert record["service"] == "terminology-code"
        assert record["rule_id"].startswith("TC-R")
        assert record["status"] in ("mapped", "source-only", "rejected")
        assert record["policy_versions"]["code_interpretation"] == "1.0.0"
        assert len(record["decision_id"]) == 64


def test_statuses_use_the_transform_result_vocabulary(term):
    seen = set()
    for coding in (
        Coding("http://loinc.org", "33914-3"),
        Coding("http://loinc.org", "00000-0"),
        Coding("http://loinc.org", ""),
    ):
        seen.add(term.resolve_code(coding).status)
    assert seen == {"mapped", "source-only", "rejected"}
