"""Acceptance matrix "Identity": deterministic entity keys on replay.

The load-bearing test here is ``test_replay_across_separate_processes``: an
in-process ``assert a == b`` cannot detect a dependence on ``hash()``, which is
salted once per interpreter. These runs use different ``PYTHONHASHSEED`` values
in genuinely separate processes.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PROBE = Path(__file__).resolve().parent / "replay_probe.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_probe import workload  # noqa: E402

from fhir_sulo.policy import canonical_json  # noqa: E402


def _run_probe(hashseed):
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = str(hashseed)
    env["FHIR_SULO_POLICY_DIR"] = str(REPO_ROOT / "policies")
    env.pop("PYTHONDONTWRITEBYTECODE", None)
    result = subprocess.run(
        [sys.executable, str(PROBE)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("ascii")


def test_replay_across_separate_processes():
    """Same workload, three processes, three different hash seeds, byte-identical."""
    outputs = [_run_probe(seed) for seed in (0, 1, 12345)]
    assert outputs[0] == outputs[1] == outputs[2], (
        "identity/terminology output differs across processes; something in the "
        "keying depends on per-process state"
    )
    # And the run actually did something.
    parsed = json.loads(outputs[0])
    assert len(parsed["identity"]) >= 9
    assert any(row.get("entity_iri") for row in parsed["identity"])


def test_replay_in_process_is_also_stable():
    assert canonical_json(workload()) == canonical_json(workload())


def test_no_builtin_hash_in_the_keying_path():
    """Static guard: hashlib only. ``hash()`` is salted and must never key."""
    offenders = []
    for path in sorted((REPO_ROOT / "src" / "fhir_sulo").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.split("#", 1)[0]
            if "hash(" in stripped and "hashlib" not in stripped:
                offenders.append("%s:%d: %s" % (path, lineno, line.strip()))
            for forbidden in ("time.time(", "datetime.now(", "utcnow(", "uuid", "random."):
                if forbidden in stripped:
                    offenders.append("%s:%d: %s" % (path, lineno, line.strip()))
    assert not offenders, "nondeterministic constructs in the keying path:\n" + "\n".join(
        offenders
    )


def test_candidate_order_does_not_affect_the_key():
    from fhir_sulo.identity import IdentityRequest, IdentityService, ReferenceEvidence, SourceScope

    scope = SourceScope("synthea-pilot-r4", "https://fhir.example/")
    a = ReferenceEvidence("a", "literal-reference", scope, "Patient", "p123")
    b = ReferenceEvidence("b", "bundle-entry", scope, "Patient", "p123")
    svc = IdentityService()

    forward = svc.resolve(IdentityRequest("Patient/p123", ("Patient",), (a, b)))
    reverse = svc.resolve(IdentityRequest("Patient/p123", ("Patient",), (b, a)))

    assert forward.is_resolved and reverse.is_resolved
    assert forward.identity.entity_iri == reverse.identity.entity_iri
    assert forward.record.decision_id == reverse.record.decision_id


def test_repeated_reference_resolves_to_one_person():
    """Plan section 2: 'repeated references resolve to one intended person'."""
    from fhir_sulo.identity import IdentityRequest, IdentityService, ReferenceEvidence, SourceScope

    scope = SourceScope("synthea-pilot-r4", "https://fhir.example/")
    svc = IdentityService()
    iris = set()
    for i in range(25):
        evidence = ReferenceEvidence(
            evidence_id="ev-%d" % i,
            kind="literal-reference" if i % 2 else "bundle-entry",
            source_scope=scope,
            resource_type="Patient",
            resource_id="p123",
            canonical_url="https://fhir.example/Patient/p123",
            resource_version_id=str(i),
            detail={"observed_in": "Observation/obs-%d" % i},
        )
        outcome = svc.resolve(IdentityRequest("Patient/p123", ("Patient",), (evidence,)))
        assert outcome.is_resolved
        iris.add(outcome.identity.entity_iri)
    assert len(iris) == 1, iris


def test_unicode_equivalent_ids_do_not_split_one_person():
    """NFC normalisation: two byte-different but equivalent ids are one entity."""
    from fhir_sulo.identity import IdentityRequest, IdentityService, ReferenceEvidence, SourceScope

    svc = IdentityService()
    composed = "pat-é"  # e-acute as a single code point
    decomposed = "pat-é"  # e + combining acute
    assert composed != decomposed

    iris = set()
    for resource_id in (composed, decomposed):
        scope = SourceScope("synthea-pilot-r4", "https://fhir.example/")
        evidence = ReferenceEvidence("e", "literal-reference", scope, "Patient", resource_id)
        outcome = svc.resolve(IdentityRequest("Patient/x", ("Patient",), (evidence,)))
        assert outcome.is_resolved
        iris.add(outcome.identity.entity_iri)
    assert len(iris) == 1
