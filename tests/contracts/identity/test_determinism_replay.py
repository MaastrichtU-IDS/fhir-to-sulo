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


# ---------------------------------------------------------------------------
# Static determinism guard.
#
# This was originally a single rglob over src/fhir_sulo. At integration that
# scope silently widened to cover provenance/ and validation/ and started
# flagging two legitimate constructs: RunRecord.activity_time is *supposed* to
# be wall-clock (and is deliberately excluded from the graph key's content
# fields, DR-601), and the reasoner uses uuid4 for temporary container and file
# names. A guard whose scope changes when someone adds a package is a guard
# that will be relaxed the first time it is inconvenient, so the scope is now
# declared explicitly and its completeness is itself tested.
#
# Tier 1 - modules that compute a key. Nothing time-, uuid- or random-derived
#          may appear, because anything here can reach a persisted identifier.
# Tier 2 - all of src. Only the builtin hash() is banned; it is salted per
#          process and must never key anything, anywhere.
# ---------------------------------------------------------------------------

KEY_PATH_MODULES = (
    "canonical.py",             # IR-602: the ONE canonicaliser; every key goes through it
    "policy/canonical.py",      # re-export shim, kept so a re-fork here is still scanned
    "policy/record.py",
    "store/canonical.py",       # re-export shim, same reason
    "store/graph_key.py",       # graph_key / subject_key
    "identity/service.py",
    "terminology/service.py",
)

_NONDETERMINISTIC = ("time.time(", "datetime.now(", "utcnow(", "uuid", "random.")


def _offending_lines(path, needles, skip_hashlib=False):
    out = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.split("#", 1)[0]
        for needle in needles:
            if needle == "hash(" and skip_hashlib and "hashlib" in stripped:
                continue
            if needle in stripped:
                out.append("%s:%d: %s" % (path, lineno, line.strip()))
                break
    return out


def test_the_declared_key_path_actually_exists():
    """The scope is only meaningful if it names real files and is not empty.

    Without this, deleting or renaming a module would quietly shrink the
    guard to nothing while the suite stayed green.
    """
    root = REPO_ROOT / "src" / "fhir_sulo"
    missing = [m for m in KEY_PATH_MODULES if not (root / m).is_file()]
    assert not missing, (
        "KEY_PATH_MODULES names files that do not exist: %s. Update the list "
        "deliberately; do not let the guard silently cover nothing." % missing
    )
    assert len(KEY_PATH_MODULES) >= 4
    # IR-602 converged the two canonicalisers into one module. That module is
    # now the whole project's keying path, so scanning it is mandatory;
    # scanning the two shims is cheap insurance against someone re-forking one
    # of them. test_canonicalisers_agree.py is what fails if they do.
    assert "canonical.py" in KEY_PATH_MODULES, (
        "the single canonicaliser must be in the declared keying path"
    )
    assert any(m.endswith("policy/canonical.py") for m in KEY_PATH_MODULES)
    assert any(m.endswith("store/canonical.py") for m in KEY_PATH_MODULES)


def test_no_nondeterministic_constructs_in_the_keying_path():
    """Tier 1: clocks, uuids and randomness cannot reach a key."""
    root = REPO_ROOT / "src" / "fhir_sulo"
    offenders = []
    for module in KEY_PATH_MODULES:
        path = root / module
        offenders += _offending_lines(path, _NONDETERMINISTIC)
        offenders += _offending_lines(path, ("hash(",), skip_hashlib=True)
    assert not offenders, (
        "nondeterministic constructs in the declared keying path:\n"
        + "\n".join(offenders)
    )


def test_no_builtin_hash_anywhere_in_src():
    """Tier 2: hash() is salted per process and must never key anything."""
    offenders = []
    for path in sorted((REPO_ROOT / "src" / "fhir_sulo").rglob("*.py")):
        offenders += _offending_lines(path, ("hash(",), skip_hashlib=True)
    assert not offenders, "builtin hash() found in src:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# Restored 2026-09-29. These three were dropped when the integration lead
# rewrote the static determinism guard above and replaced everything from that
# function to end-of-file. Nothing replaced them and no decision record
# mentioned it, so coverage silently fell. They are unchanged from
# f947f27^ and they still pass.
# ---------------------------------------------------------------------------

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
