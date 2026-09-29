"""UCUM resolution contract.

Concept note section 4 failure variants: "missing or unrecognized UCUM units
fail this numeric target shape". Concept note section 2: never drop a unit
code/system while claiming an unqualified numeric result.
"""

import dataclasses

import pytest

from fhir_sulo.terminology import (
    TerminologyService,
    TerminologyUnavailable,
    UnitRef,
    UnitRejected,
    UnitResolved,
)

UCUM = "http://unitsofmeasure.org"


@pytest.fixture(scope="module")
def term():
    return TerminologyService()


def test_pinned_egfr_unit_resolves(term):
    outcome = term.resolve_unit(
        UnitRef(UCUM, "mL/min/{1.73_m2}", "mL/min/1.73 m2"), expected_dimension="egfr-rate"
    )
    assert isinstance(outcome, UnitResolved)
    assert outcome.status == "mapped"
    assert outcome.unit.unit_iri == "https://example.org/fhir-sulo/ucum-mL-min-1_73_m2"
    assert outcome.unit.dimension == "egfr-rate"
    assert outcome.unit.converted is False
    assert outcome.unit.clinical_signoff is False


def test_pinned_pressure_unit_resolves(term):
    outcome = term.resolve_unit(UnitRef(UCUM, "mm[Hg]", "mmHg"), expected_dimension="pressure")
    assert outcome.status == "mapped"
    assert outcome.unit.unit_iri == "https://example.org/fhir-sulo/ucum-mm_Hg"


def test_unknown_ucum_code_is_rejected_not_guessed(term):
    outcome = term.resolve_unit(UnitRef(UCUM, "furlong/fortnight"))
    assert isinstance(outcome, UnitRejected)
    assert outcome.reason_code == "unknown-unit-code"


def test_an_unparsed_ucum_expression_is_not_silently_accepted(term):
    """The resolver matches pinned literals; it does not parse UCUM grammar."""
    outcome = term.resolve_unit(UnitRef(UCUM, "mL/min/(1.73.m2)"), expected_dimension="egfr-rate")
    assert outcome.status == "rejected"
    assert outcome.reason_code == "unknown-unit-code"


def test_missing_unit_code_is_rejected(term):
    outcome = term.resolve_unit(UnitRef(UCUM, ""), expected_dimension="pressure")
    assert outcome.status == "rejected"
    assert outcome.reason_code == "missing-unit-code"


def test_a_non_ucum_unit_system_is_rejected(term):
    outcome = term.resolve_unit(UnitRef("http://example.org/units", "mmHg"), expected_dimension="pressure")
    assert outcome.status == "rejected"
    assert outcome.reason_code == "unknown-unit-system"


def test_incompatible_dimension_is_rejected(term):
    outcome = term.resolve_unit(UnitRef(UCUM, "mm[Hg]"), expected_dimension="egfr-rate")
    assert outcome.status == "rejected"
    assert outcome.reason_code == "unit-dimension-mismatch"
    assert "conversion is disabled" in outcome.reason


def test_a_convertible_unit_is_not_silently_normalised(term):
    """kPa is dimensionally pressure, but conversion is disabled by policy."""
    outcome = term.resolve_unit(UnitRef(UCUM, "kPa"), expected_dimension="pressure")
    assert outcome.status == "rejected"
    assert outcome.reason_code == "unit-not-approved"
    assert term.policy.unit["defaults"]["conversion"] == "disabled"
    assert term.policy.unit["defaults"]["silent_normalisation"] is False


def test_no_outcome_ever_reports_a_conversion(term):
    resolved = term.resolve_unit(UnitRef(UCUM, "mm[Hg]"), expected_dimension="pressure")
    assert resolved.unit.converted is False
    rejected = term.resolve_unit(UnitRef(UCUM, "kPa"), expected_dimension="pressure")
    assert rejected.record.to_dict()["outcome"]["converted"] is False


@pytest.mark.parametrize(
    "unit_ref,dimension",
    [
        (UnitRef(UCUM, "mL/min/{1.73_m2}", "mL/min/1.73 m2"), "egfr-rate"),
        (UnitRef(UCUM, "furlong/fortnight", "nonsense"), None),
        (UnitRef("http://example.org/units", "mmHg", "mmHg"), "pressure"),
        (UnitRef(UCUM, "kPa", "kPa"), "pressure"),
    ],
)
def test_the_source_unit_is_retained_on_every_outcome(term, unit_ref, dimension):
    outcome = term.resolve_unit(unit_ref, expected_dimension=dimension)
    retained = outcome.source_retained()
    assert retained == unit_ref.as_dict()
    assert outcome.record.to_dict()["outcome"]["source"] == unit_ref.as_dict()


def test_a_rejected_unit_has_no_iri_attribute(term):
    outcome = term.resolve_unit(UnitRef(UCUM, "furlong/fortnight"))
    field_names = {f.name for f in dataclasses.fields(outcome)}
    assert "unit" not in field_names
    assert "unit_iri" not in field_names
    for leaky in ("unit", "unit_iri", "ucum_code", "dimension"):
        with pytest.raises(TerminologyUnavailable):
            getattr(outcome, leaky)
    with pytest.raises(TerminologyUnavailable):
        outcome.unwrap()


def test_the_display_text_is_not_treated_as_the_unit(term):
    """The concept note keeps the display text in the source layer only."""
    outcome = term.resolve_unit(
        UnitRef(UCUM, "mL/min/{1.73_m2}", "mL/min/1.73 m2"), expected_dimension="egfr-rate"
    )
    assert outcome.unit.ucum_code == "mL/min/{1.73_m2}"
    assert outcome.source.display == "mL/min/1.73 m2"
    assert outcome.unit.ucum_code != outcome.source.display


def test_the_code_table_and_the_unit_table_agree_on_dimensions(term):
    dimensions = set(term.policy.unit["dimensions"])
    for entry in term.policy.code_interpretation["entries"]:
        expected = entry["expected_unit_dimension"]
        if expected is not None:
            assert expected in dimensions, entry["entry_id"]


def test_the_egfr_code_and_its_unit_line_up_end_to_end(term):
    """Worked example A: code and unit must be mutually consistent."""
    from fhir_sulo.terminology import Coding

    code = term.resolve_code(Coding("http://loinc.org", "33914-3"))
    unit = term.resolve_unit(
        UnitRef(UCUM, "mL/min/{1.73_m2}", "mL/min/1.73 m2"),
        expected_dimension=code.interpretation.expected_unit_dimension,
    )
    assert unit.status == "mapped"
    assert unit.unit.dimension == code.interpretation.expected_unit_dimension
