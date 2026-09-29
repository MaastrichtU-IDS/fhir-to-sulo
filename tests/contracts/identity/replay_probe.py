"""Standalone replay probe, executed as a **separate process** by the tests.

It resolves a fixed workload and prints the canonical JSON of everything that
must be reproducible: entity IRIs, quality IRIs, decision ids, and the policy
bundle digest.

Run it twice with different ``PYTHONHASHSEED`` values; the stdout must be byte
identical. That is what catches a dependence on ``hash()``, on dict ordering,
on a timestamp, or on any other per-process state - none of which an
in-process ``assert a == b`` would catch.
"""

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ.setdefault("FHIR_SULO_POLICY_DIR", str(REPO_ROOT / "policies"))

from fhir_sulo.identity import (  # noqa: E402
    IdentityRequest,
    IdentityService,
    QualityRequest,
    ReferenceEvidence,
    SourceScope,
)
from fhir_sulo.policy import PolicyBundle, canonical_json  # noqa: E402
from fhir_sulo.terminology import Coding, TerminologyService, UnitRef  # noqa: E402

SCOPE_A = SourceScope("synthea-pilot-r4", "https://fhir.example/")
SCOPE_B = SourceScope("other-site-r4", "https://other.example/")


def _evidence(evidence_id, scope, resource_type, resource_id, detail=None):
    return ReferenceEvidence(
        evidence_id=evidence_id,
        kind="literal-reference",
        source_scope=scope,
        resource_type=resource_type,
        resource_id=resource_id,
        canonical_url="%s%s/%s" % (scope.fhir_base_url, resource_type, resource_id),
        resource_version_id="1",
        # A multi-key mapping: if dict iteration order ever leaked into a key,
        # this is where it would show up across processes.
        detail=detail or {"zeta": "z", "alpha": "a", "mu": "m", "beta": "b"},
    )


def workload(policy_dir=None):
    bundle = PolicyBundle.load(policy_dir) if policy_dir else PolicyBundle.load()
    identity = IdentityService(bundle)
    terminology = TerminologyService(bundle)

    out = {"policy_versions": bundle.versions, "identity": [], "terminology": []}

    requests = [
        ("p123@A", IdentityRequest("Patient/p123", ("Patient",), (_evidence("e1", SCOPE_A, "Patient", "p123"),))),
        ("p123@A-again", IdentityRequest("Patient/p123", ("Patient",), (_evidence("e9", SCOPE_A, "Patient", "p123"),))),
        ("p999@A", IdentityRequest("Patient/p999", ("Patient",), (_evidence("e2", SCOPE_A, "Patient", "p999"),))),
        ("p123@B", IdentityRequest("Patient/p123", ("Patient",), (_evidence("e3", SCOPE_B, "Patient", "p123"),))),
        ("c7@A", IdentityRequest("Practitioner/c7", ("Practitioner",), (_evidence("e4", SCOPE_A, "Practitioner", "c7"),), entity_kind="person")),
        (
            "concordant-reordered",
            IdentityRequest(
                "Patient/p123",
                ("Patient",),
                (
                    _evidence("z-last", SCOPE_A, "Patient", "p123"),
                    _evidence("a-first", SCOPE_A, "Patient", "p123"),
                ),
            ),
        ),
        ("unresolved", IdentityRequest("Patient/ghost", ("Patient",), ())),
        (
            "ambiguous",
            IdentityRequest(
                "Patient/?identifier=x",
                ("Patient",),
                (
                    _evidence("m1", SCOPE_A, "Patient", "p123"),
                    _evidence("m2", SCOPE_A, "Patient", "p456"),
                ),
            ),
        ),
        (
            "wrong-type",
            IdentityRequest("Group/g1", ("Patient",), (_evidence("e5", SCOPE_A, "Group", "g1"),)),
        ),
    ]

    for label, request in requests:
        outcome = identity.resolve(request)
        row = {
            "label": label,
            "status": outcome.status,
            "decision_id": outcome.record.decision_id,
        }
        if outcome.is_resolved:
            row["entity_iri"] = outcome.identity.entity_iri
        else:
            row["reason_code"] = outcome.reason_code
        out["identity"].append(row)

    # Quality identity under each explicitly selected mode, plus the unset default.
    person = identity.resolve(requests[0][1]).unwrap()
    quality_request = QualityRequest(
        person=person,
        quality_class_iri="https://example.org/fhir-sulo/RenalFiltrationQuality",
        observable_system="http://loinc.org",
        observable_code="33914-3",
        source_resource_canonical_url="https://fhir.example/Observation/egfr-456",
        source_resource_version_id="1",
        effective_time="2026-09-02T14:00:00Z",
    )
    out["quality"] = []
    for mode in (None, "persistent-per-person-code", "per-observation"):
        variant = _bundle_with_quality_mode(bundle, mode)
        svc = IdentityService(variant)
        outcome = svc.resolve_quality(quality_request)
        row = {"mode": mode, "status": outcome.status, "decision_id": outcome.record.decision_id}
        if outcome.is_resolved:
            row["quality_iri"] = outcome.identity.quality_iri
        else:
            row["reason_code"] = outcome.reason_code
        out["quality"].append(row)

    codes = [
        Coding("http://loinc.org", "33914-3"),
        Coding("http://loinc.org", "8480-6"),
        Coding("http://loinc.org", "8462-4"),
        Coding("http://loinc.org", "85354-9"),
        Coding("http://loinc.org", "00000-0"),
        Coding("http://example.org/private-codes", "X1"),
    ]
    for coding in codes:
        outcome = terminology.resolve_code(coding)
        row = {
            "code": "%s|%s" % (coding.system, coding.code),
            "status": outcome.status,
            "decision_id": outcome.record.decision_id,
            "source_retained": outcome.source_retained(),
        }
        if outcome.is_interpreted:
            row["result_class"] = outcome.interpretation.result_class
        else:
            row["reason_code"] = outcome.reason_code
        out["terminology"].append(row)

    units = [
        (UnitRef("http://unitsofmeasure.org", "mL/min/{1.73_m2}"), "egfr-rate"),
        (UnitRef("http://unitsofmeasure.org", "mm[Hg]"), "pressure"),
        (UnitRef("http://unitsofmeasure.org", "kPa"), "pressure"),
        (UnitRef("http://unitsofmeasure.org", "mm[Hg]"), "egfr-rate"),
        (UnitRef("http://unitsofmeasure.org", "furlong/fortnight"), None),
        (UnitRef("http://example.org/units", "mmHg"), "pressure"),
    ]
    out["units"] = []
    for unit_ref, dimension in units:
        outcome = terminology.resolve_unit(unit_ref, expected_dimension=dimension)
        row = {
            "unit": "%s|%s" % (unit_ref.system, unit_ref.code),
            "expected_dimension": dimension,
            "status": outcome.status,
            "decision_id": outcome.record.decision_id,
            "source_retained": outcome.source_retained(),
        }
        if outcome.is_resolved:
            row["unit_iri"] = outcome.unit.unit_iri
        else:
            row["reason_code"] = outcome.reason_code
        out["units"].append(row)

    return out


def _bundle_with_quality_mode(bundle, mode):
    import copy

    identity_policy = copy.deepcopy(dict(bundle.identity))
    identity_policy["quality_identity"]["mode"] = mode
    return PolicyBundle(
        identity=identity_policy,
        code_interpretation=bundle.code_interpretation,
        unit=bundle.unit,
        source_dir=bundle.source_dir,
    )


if __name__ == "__main__":
    sys.stdout.write(canonical_json(workload()))
