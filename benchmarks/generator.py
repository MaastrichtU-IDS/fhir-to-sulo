"""Deterministic synthetic FHIR R4 resource generator.

Gate 4 asks for "a synthetic scale trial" over 10,000 resources. The generator
is deterministic from a seed so that two benchmark runs measure the same work,
and so that a throughput regression is a fact about the code rather than about
the dice.

Resource mix, chosen to exercise the shapes that actually cost something
rather than to flatter the number:

============ ===== ==========================================================
Family       Share Why
============ ===== ==========================================================
eGFR         40%   the simplest target: one quantity, one unit, one time
BP panel     35%   two components per resource - the repetition case, and the
                   one with the most triples per resource
Encounter    20%   the PRO case, and the only one the OWL reasoner has real
                   work to do on
error/absent  5%   entered-in-error and dataAbsentReason, so the measured run
                   includes the paths that produce no clinical assertions and
                   the failure categories are non-empty
============ ===== ==========================================================

This produces *target-shaped* output directly. It is **not** a FHIR-to-SULO
map and must not be mistaken for one: Agent 3 owns `maps/`, and the real
pipeline will produce these triples from a ShExMap pair. What is being
measured here is everything the host does around that - keying, lineage,
store, provenance, SHACL, OWL - plus, separately, the engine itself in
`engine_bench/`. `README.md` says exactly what that does and does not cover.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterator, List, Tuple

SULO = "https://w3id.org/sulo/"
EX = "https://example.org/fhir-sulo/"
XSD = "http://www.w3.org/2001/XMLSchema#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
PROV_DERIVED = "http://www.w3.org/ns/prov#wasDerivedFrom"

FAMILIES = ("egfr", "bp", "encounter", "ineligible")
WEIGHTS = (0.40, 0.35, 0.20, 0.05)


@dataclass(frozen=True)
class SyntheticResource:
    """One synthetic source resource and the target graph it should produce."""

    family: str
    resource_id: str
    canonical_url: str
    version_id: str
    json_digest: str
    source_status: str
    eligible: bool
    quads: Tuple[str, ...]
    pivot_variables: Tuple[str, ...]
    person_id: str
    reason: str = ""


def _iri(value: str) -> str:
    return "<%s>" % value


def _lit(value: str, datatype: str = None) -> str:
    text = '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')
    return "%s^^<%s>" % (text, datatype) if datatype else text


def _t(subject: str, predicate: str, obj: str) -> str:
    return "%s %s %s ." % (_iri(subject), _iri(predicate), obj)


def _egfr(index: int, person: str, rng: random.Random) -> Tuple[List[str], List[str]]:
    rid = "egfr-%d" % index
    result, unit, time, quality, record = (
        EX + "result-" + rid,
        EX + "unit-mL-min-1_73_m2",
        EX + "time-" + rid,
        EX + "renal-quality-" + rid,
        EX + "record-" + rid,
    )
    source = "https://fhir.example/Observation/%s/_history/1" % rid
    value = "%.1f" % (30.0 + rng.random() * 90.0)
    hour = 8 + (index % 10)
    quads = [
        _t(result, RDF_TYPE, _iri(SULO + "Quantity")),
        _t(result, RDF_TYPE, _iri(EX + "EGFRResult")),
        _t(result, SULO + "hasValue", _lit(value, XSD + "decimal")),
        _t(result, SULO + "hasPart", _iri(unit)),
        _t(result, SULO + "refersTo", _iri(quality)),
        _t(result, SULO + "atTime", _iri(time)),
        _t(result, PROV_DERIVED, _iri(source)),
        _t(unit, RDF_TYPE, _iri(SULO + "Unit")),
        _t(unit, SULO + "hasValue", _lit("mL/min/{1.73_m2}")),
        _t(time, RDF_TYPE, _iri(SULO + "TimeInstant")),
        _t(time, SULO + "hasValue",
           _lit("2026-09-02T%02d:00:00Z" % hour, XSD + "dateTimeStamp")),
        _t(quality, RDF_TYPE, _iri(SULO + "Feature")),
        _t(quality, RDF_TYPE, _iri(EX + "RenalFiltrationQuality")),
        _t(quality, SULO + "isFeatureOf", _iri(person)),
        _t(person, RDF_TYPE, _iri(SULO + "SpatialObject")),
        _t(person, SULO + "hasFeature", _iri(quality)),
        _t(record, RDF_TYPE, _iri(SULO + "InformationObject")),
        _t(record, SULO + "refersTo", _iri(result)),
        _t(record, PROV_DERIVED, _iri(source)),
    ]
    return quads, ["egfr:value", "egfr:unitCode", "egfr:effective", "egfr:person"]


def _bp(index: int, person: str, rng: random.Random) -> Tuple[List[str], List[str]]:
    rid = "bp-%d" % index
    panel, unit, time = EX + "record-" + rid, EX + "unit-mm-Hg", EX + "time-" + rid
    source = "https://fhir.example/Observation/%s/_history/1" % rid
    systolic = 100 + rng.randrange(0, 60)
    diastolic = 60 + rng.randrange(0, 35)
    hour = 8 + (index % 10)
    quads = [
        _t(panel, RDF_TYPE, _iri(SULO + "InformationObject")),
        _t(panel, RDF_TYPE, _iri(EX + "BloodPressurePanelRecord")),
        _t(panel, SULO + "atTime", _iri(time)),
        _t(panel, PROV_DERIVED, _iri(source)),
        _t(time, RDF_TYPE, _iri(SULO + "TimeInstant")),
        _t(time, SULO + "hasValue",
           _lit("2026-09-02T%02d:30:00Z" % hour, XSD + "dateTimeStamp")),
        _t(unit, RDF_TYPE, _iri(SULO + "Unit")),
        _t(unit, SULO + "hasValue", _lit("mm[Hg]")),
        _t(person, RDF_TYPE, _iri(SULO + "SpatialObject")),
    ]
    for component, value, quality_class in (
        ("systolic", systolic, "SystolicBloodPressureQuality"),
        ("diastolic", diastolic, "DiastolicBloodPressureQuality"),
    ):
        node = "%s%s-%s" % (EX, rid, component)
        quality = "%squality-%s-%s" % (EX, rid, component)
        quads.extend([
            _t(node, RDF_TYPE, _iri(SULO + "Quantity")),
            _t(node, SULO + "hasValue", _lit(str(value), XSD + "decimal")),
            _t(node, SULO + "hasPart", _iri(unit)),
            _t(node, SULO + "refersTo", _iri(quality)),
            _t(node, SULO + "atTime", _iri(time)),
            _t(panel, SULO + "refersTo", _iri(node)),
            _t(quality, RDF_TYPE, _iri(SULO + "Feature")),
            _t(quality, RDF_TYPE, _iri(EX + quality_class)),
            _t(quality, SULO + "isFeatureOf", _iri(person)),
            _t(person, SULO + "hasFeature", _iri(quality)),
        ])
    return quads, ["bp:systolic", "bp:diastolic", "bp:unitCode", "bp:effective"]


def _encounter(index: int, person: str, rng: random.Random) -> Tuple[List[str], List[str]]:
    rid = "enc-%d" % index
    encounter = EX + rid
    clinician = "%sclinician-c%d" % (EX, rng.randrange(1, 50))
    interval, start, end = (
        EX + "interval-" + rid, EX + "start-" + rid, EX + "end-" + rid
    )
    source = "https://fhir.example/Encounter/%s/_history/1" % rid
    hour = 8 + (index % 10)
    quads = [
        _t(encounter, RDF_TYPE, _iri(SULO + "Process")),
        _t(encounter, RDF_TYPE, _iri(EX + "ClinicalEncounter")),
        _t(encounter, SULO + "atTime", _iri(interval)),
        _t(encounter, PROV_DERIVED, _iri(source)),
        _t(interval, RDF_TYPE, _iri(SULO + "TimeInterval")),
        _t(interval, SULO + "hasPart", _iri(start)),
        _t(interval, SULO + "hasPart", _iri(end)),
        _t(start, RDF_TYPE, _iri(SULO + "StartTime")),
        _t(start, SULO + "hasValue",
           _lit("2026-09-02T%02d:00:00Z" % hour, XSD + "dateTimeStamp")),
        _t(end, RDF_TYPE, _iri(SULO + "EndTime")),
        _t(end, SULO + "hasValue",
           _lit("2026-09-02T%02d:30:00Z" % hour, XSD + "dateTimeStamp")),
        _t(person, RDF_TYPE, _iri(SULO + "SpatialObject")),
        _t(clinician, RDF_TYPE, _iri(SULO + "SpatialObject")),
    ]
    for role_local, holder, role_class in (
        ("patient-role-" + rid, person, "PatientRole"),
        ("clinician-role-" + rid, clinician, "ClinicianRole"),
    ):
        role = EX + role_local
        quads.extend([
            _t(encounter, SULO + "hasParticipant", _iri(role)),
            _t(role, RDF_TYPE, _iri(SULO + "Role")),
            _t(role, RDF_TYPE, _iri(EX + role_class)),
            _t(role, SULO + "isFeatureOf", _iri(holder)),
        ])
    return quads, ["enc:subject", "enc:performer", "enc:start", "enc:end"]


def generate(count: int, *, seed: int = 20260929, people: int = 500) -> Iterator[SyntheticResource]:
    """Yield ``count`` synthetic resources, deterministically."""
    rng = random.Random(seed)
    for index in range(count):
        family = rng.choices(FAMILIES, weights=WEIGHTS, k=1)[0]
        person = "%sperson-p%d" % (EX, rng.randrange(0, people))

        if family == "ineligible":
            reason, status = rng.choice(
                [
                    ("status entered-in-error: no clinical assertions", "entered-in-error"),
                    ("dataAbsentReason present: no numeric hasValue", "final"),
                ]
            )
            rid = "ineligible-%d" % index
            yield SyntheticResource(
                family="ineligible",
                resource_id=rid,
                canonical_url="https://fhir.example/Observation/%s" % rid,
                version_id="1",
                json_digest="sha256:synthetic-%d" % index,
                source_status=status,
                eligible=False,
                quads=(),
                pivot_variables=(),
                person_id=person,
                reason=reason,
            )
            continue

        builder = {"egfr": _egfr, "bp": _bp, "encounter": _encounter}[family]
        quads, variables = builder(index, person, rng)
        resource_type = "Encounter" if family == "encounter" else "Observation"
        rid = "%s-%d" % (family, index)
        yield SyntheticResource(
            family=family,
            resource_id=rid,
            canonical_url="https://fhir.example/%s/%s" % (resource_type, rid),
            version_id="1",
            json_digest="sha256:synthetic-%d" % index,
            source_status="finished" if family == "encounter" else "final",
            eligible=True,
            quads=tuple(quads),
            pivot_variables=tuple(variables),
            person_id=person,
        )
