"""Agent 5's headline invariants, written for plain ``unittest``.

Why this file exists, and why it sits beside the other agents' contract tests
rather than in ``tests/contracts/identity/``:

``make contracts`` and the CI job run ``python -m unittest discover -s
tests/contracts``. unittest discovery does not descend into
``tests/contracts/identity/`` or ``tests/contracts/terminology/`` (they are not
importable packages), and the full suite there uses pytest fixtures and
``parametrize``. So without this module, none of Agent 5's 104 checks would run
in CI, and Gate 1's "deterministic mock terminology/identity service" would be
satisfied by the existence of two directories alone.

This module therefore restates the load-bearing invariants with stdlib only.
It is a floor, not a replacement: the full suite is

    .venv/bin/python -m pytest tests/contracts -q

and Agent 1 should wire that into CI (pytest is pinned in requirements-dev.txt).
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from fhir_sulo.identity import (  # noqa: E402
    IdentityRequest,
    IdentityService,
    IdentityUnavailable,
    QualityIdentityPolicyUnset,
    QualityRequest,
    ReferenceEvidence,
    SourceScope,
)
from fhir_sulo.policy import PolicyBundle, parse_policy_version  # noqa: E402
from fhir_sulo.terminology import Coding, TerminologyService, UnitRef  # noqa: E402

SITE_A = SourceScope("synthea-pilot-r4", "https://fhir.example/")
SITE_B = SourceScope("other-site-r4", "https://other.example/")
PROBE = REPO_ROOT / "tests" / "contracts" / "identity" / "replay_probe.py"


def _request(scope, resource_id, resource_type="Patient", evidence_id="e"):
    evidence = ReferenceEvidence(
        evidence_id, "literal-reference", scope, resource_type, resource_id
    )
    return IdentityRequest(
        "%s/%s" % (resource_type, resource_id), (resource_type,), (evidence,)
    )


class IdentityContract(unittest.TestCase):
    """Acceptance matrix row "Identity"."""

    def setUp(self):
        self.svc = IdentityService()

    def test_repeated_references_resolve_to_one_person(self):
        iris = {
            self.svc.resolve(_request(SITE_A, "p123", evidence_id="e%d" % i))
            .identity.entity_iri
            for i in range(10)
        }
        self.assertEqual(len(iris), 1)

    def test_distinct_people_remain_distinct(self):
        a = self.svc.resolve(_request(SITE_A, "p123")).identity.entity_iri
        b = self.svc.resolve(_request(SITE_A, "p999")).identity.entity_iri
        self.assertNotEqual(a, b)

    def test_same_id_at_two_sources_stays_two_people(self):
        a = self.svc.resolve(_request(SITE_A, "p123")).identity.entity_iri
        b = self.svc.resolve(_request(SITE_B, "p123")).identity.entity_iri
        self.assertNotEqual(a, b)

    def test_unresolved_reference_is_rejected(self):
        outcome = self.svc.resolve(IdentityRequest("Patient/ghost", ("Patient",), ()))
        self.assertFalse(outcome.is_resolved)
        self.assertEqual(outcome.reason_code, "unresolved-reference")

    def test_ambiguous_reference_is_rejected_and_unignorable(self):
        candidates = (
            ReferenceEvidence("m1", "literal-reference", SITE_A, "Patient", "p123"),
            ReferenceEvidence("m2", "literal-reference", SITE_A, "Patient", "p456"),
        )
        outcome = self.svc.resolve(
            IdentityRequest("Patient/?identifier=x", ("Patient",), candidates)
        )
        self.assertFalse(outcome.is_resolved)
        self.assertEqual(outcome.reason_code, "ambiguous-reference")
        with self.assertRaises(IdentityUnavailable):
            outcome.unwrap()
        for leaky in ("identity", "entity_iri", "iri", "person"):
            with self.assertRaises(IdentityUnavailable):
                getattr(outcome, leaky)

    def test_a_resolved_reference_is_not_an_equivalence_claim(self):
        lineage = self.svc.resolve(_request(SITE_A, "p123")).identity.lineage()
        self.assertFalse(lineage["equivalence_asserted"])
        self.assertEqual(
            lineage["lineage_predicate"], "http://www.w3.org/ns/prov#wasDerivedFrom"
        )
        self.assertEqual(lineage["source_reference_literal"], "Patient/p123")

    def test_quality_identity_policy_is_unset_and_rejects(self):
        person = self.svc.resolve(_request(SITE_A, "p123")).unwrap()
        outcome = self.svc.resolve_quality(
            QualityRequest(
                person=person,
                quality_class_iri="https://example.org/fhir-sulo/RenalFiltrationQuality",
                observable_system="http://loinc.org",
                observable_code="33914-3",
            )
        )
        self.assertFalse(outcome.is_resolved)
        self.assertEqual(outcome.reason_code, "quality-identity-policy-unset")
        with self.assertRaises(QualityIdentityPolicyUnset):
            outcome.unwrap()


class DeterminismContract(unittest.TestCase):
    """Gate 4 depends on this: node identity comes from here, not the engine."""

    def test_replay_across_separate_processes_is_byte_identical(self):
        outputs = []
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            env["FHIR_SULO_POLICY_DIR"] = str(REPO_ROOT / "policies")
            result = subprocess.run(
                [sys.executable, str(PROBE)],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            outputs.append(result.stdout.decode("ascii"))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[1], outputs[2])
        self.assertGreaterEqual(len(json.loads(outputs[0])["identity"]), 9)

    # Two tiers, matching tests/contracts/identity/test_determinism_replay.py.
    # The original single rglob widened its own scope at integration and began
    # flagging RunRecord.activity_time (which must be wall-clock, and is
    # excluded from the graph key by DR-601) and the reasoner's temp-file
    # uuids. Scope is declared, and its completeness is tested.
    KEY_PATH_MODULES = (
        "policy/canonical.py", "policy/record.py",
        "store/canonical.py", "store/graph_key.py",
        "identity/service.py", "terminology/service.py",
    )

    @staticmethod
    def _hits(path, tokens, skip_hashlib=False):
        out = []
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.split("#", 1)[0]
            for tok in tokens:
                if tok == "hash(" and skip_hashlib and "hashlib" in stripped:
                    continue
                if tok in stripped:
                    out.append("%s:%d %s" % (path.name, lineno, tok))
                    break
        return out

    def test_the_declared_key_path_exists(self):
        root = REPO_ROOT / "src" / "fhir_sulo"
        missing = [m for m in self.KEY_PATH_MODULES if not (root / m).is_file()]
        self.assertEqual(missing, [], "declared keying path names missing files")

    def test_no_nondeterminism_in_the_keying_path(self):
        root = REPO_ROOT / "src" / "fhir_sulo"
        offenders = []
        for module in self.KEY_PATH_MODULES:
            path = root / module
            offenders += self._hits(
                path, ("time.time(", "datetime.now(", "utcnow(", "uuid", "random."))
            offenders += self._hits(path, ("hash(",), skip_hashlib=True)
        self.assertEqual(offenders, [])

    def test_no_builtin_hash_anywhere_in_src(self):
        offenders = []
        for path in sorted((REPO_ROOT / "src" / "fhir_sulo").rglob("*.py")):
            offenders += self._hits(path, ("hash(",), skip_hashlib=True)
        self.assertEqual(offenders, [])

    def test_entity_iris_survive_a_policy_version_bump(self):
        import copy

        bundle = PolicyBundle.load()
        baseline = IdentityService(bundle).resolve(_request(SITE_A, "p123")).identity.entity_iri
        identity_policy = copy.deepcopy(dict(bundle.identity))
        identity_policy["version"] = "9.9.9"
        variant = PolicyBundle(
            identity=identity_policy,
            code_interpretation=bundle.code_interpretation,
            unit=bundle.unit,
            source_dir=bundle.source_dir,
        )
        self.assertNotEqual(variant.policy_version, bundle.policy_version)
        self.assertEqual(
            IdentityService(variant).resolve(_request(SITE_A, "p123")).identity.entity_iri,
            baseline,
        )


class TerminologyContract(unittest.TestCase):
    """Plan section 2: explicit outcomes, source codes retained."""

    def setUp(self):
        self.term = TerminologyService()

    def test_pinned_codes_are_interpreted(self):
        for code, expected in (
            ("33914-3", "https://example.org/fhir-sulo/EGFRResult"),
            ("8480-6", "https://example.org/fhir-sulo/SystolicBloodPressureResult"),
            ("8462-4", "https://example.org/fhir-sulo/DiastolicBloodPressureResult"),
        ):
            outcome = self.term.resolve_code(Coding("http://loinc.org", code))
            self.assertEqual(outcome.status, "mapped")
            self.assertEqual(outcome.interpretation.result_class, expected)
            self.assertFalse(outcome.interpretation.clinical_signoff)

    def test_unknown_code_and_system_have_explicit_outcomes(self):
        self.assertEqual(
            self.term.resolve_code(Coding("http://loinc.org", "00000-0")).status, "source-only"
        )
        self.assertEqual(
            self.term.resolve_code(Coding("http://example.org/x", "X1")).status, "source-only"
        )
        self.assertEqual(self.term.resolve_code(Coding("http://loinc.org", "")).status, "rejected")

    def test_source_codes_are_retained_on_every_outcome(self):
        for coding in (
            Coding("http://loinc.org", "33914-3", "eGFR"),
            Coding("http://loinc.org", "00000-0", "mystery"),
            Coding("http://loinc.org", "", None),
        ):
            self.assertEqual(self.term.resolve_code(coding).source_retained(), coding.as_dict())

    def test_pinned_units_resolve_and_bad_units_are_rejected(self):
        ucum = "http://unitsofmeasure.org"
        ok = self.term.resolve_unit(
            UnitRef(ucum, "mL/min/{1.73_m2}"), expected_dimension="egfr-rate"
        )
        self.assertEqual(ok.status, "mapped")
        self.assertEqual(ok.unit.unit_iri, "https://example.org/fhir-sulo/ucum-mL-min-1_73_m2")
        self.assertFalse(ok.unit.converted)

        for unit_ref, dimension, reason in (
            (UnitRef(ucum, "furlong/fortnight"), None, "unknown-unit-code"),
            (UnitRef(ucum, ""), "pressure", "missing-unit-code"),
            (UnitRef("http://example.org/units", "mmHg"), "pressure", "unknown-unit-system"),
            (UnitRef(ucum, "mm[Hg]"), "egfr-rate", "unit-dimension-mismatch"),
            (UnitRef(ucum, "kPa"), "pressure", "unit-not-approved"),
        ):
            outcome = self.term.resolve_unit(unit_ref, expected_dimension=dimension)
            self.assertEqual(outcome.status, "rejected", unit_ref.code)
            self.assertEqual(outcome.reason_code, reason)

    def test_the_service_is_offline(self):
        bundle = PolicyBundle.load()
        self.assertFalse(
            bundle.code_interpretation["terminology_snapshot"]["live_lookup_at_runtime"]
        )
        self.assertFalse(bundle.unit["ucum_snapshot"]["live_lookup_at_runtime"])


class PolicyVersionContract(unittest.TestCase):
    """What Agent 6 puts in RunRecord."""

    def test_policy_version_is_one_resolvable_string(self):
        bundle = PolicyBundle.load()
        parts = parse_policy_version(bundle.policy_version)
        self.assertEqual(parts["bundle"], "fhir-sulo-policies")
        self.assertEqual(parts["identity"], bundle.identity["version"])
        self.assertTrue(bundle.bundle_digest.startswith(parts["digest_prefix"]))
        self.assertTrue(bundle.matches_policy_version(bundle.policy_version))

    def test_terminology_snapshot_is_one_string(self):
        self.assertIsInstance(PolicyBundle.load().terminology_snapshot, str)

    def test_every_decision_record_carries_the_policy_version(self):
        svc = IdentityService()
        for outcome in (
            svc.resolve(_request(SITE_A, "p123")),
            svc.resolve(IdentityRequest("Patient/ghost", ("Patient",), ())),
        ):
            versions = outcome.record.to_dict()["policy_versions"]
            self.assertTrue(parse_policy_version(versions["policy_version"]))


if __name__ == "__main__":
    unittest.main()
