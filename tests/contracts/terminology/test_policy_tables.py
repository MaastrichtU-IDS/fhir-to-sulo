"""Properties of the policy tables themselves, and of their versioning."""

import json
from pathlib import Path

import pytest

from fhir_sulo.policy import PolicyBundle, PolicyError

POLICIES = Path(__file__).resolve().parents[3] / "policies"
TABLES = [
    "identity-policy.v1.json",
    "code-interpretation.v1.json",
    "unit-policy.v1.json",
]


@pytest.mark.parametrize("filename", TABLES)
def test_every_table_is_parseable_and_versioned(filename):
    data = json.loads((POLICIES / filename).read_text(encoding="utf-8"))
    assert data["policy_id"]
    assert data["version"]
    assert data["status"]


def test_the_bundle_exposes_versions_for_the_run_record():
    versions = PolicyBundle.load().versions
    for key in (
        "policy_version",
        "identity_policy",
        "code_interpretation",
        "unit_policy",
        "terminology_snapshot",
        "entity_key_revision",
        "quality_key_revision",
        "policy_bundle_digest",
    ):
        assert versions[key]
    assert len(versions["policy_bundle_digest"]) == 64


def test_the_bundle_digest_is_stable_across_loads():
    assert PolicyBundle.load().bundle_digest == PolicyBundle.load().bundle_digest


def test_a_missing_policy_directory_fails_loudly(tmp_path):
    with pytest.raises(PolicyError):
        PolicyBundle.load(tmp_path / "nowhere")


def test_a_missing_table_fails_loudly(tmp_path):
    for filename in TABLES[:-1]:
        (tmp_path / filename).write_text(
            (POLICIES / filename).read_text(encoding="utf-8"), encoding="utf-8"
        )
    with pytest.raises(PolicyError):
        PolicyBundle.load(tmp_path)


def test_the_services_never_do_a_runtime_lookup():
    bundle = PolicyBundle.load()
    assert bundle.code_interpretation["terminology_snapshot"]["live_lookup_at_runtime"] is False
    assert bundle.unit["ucum_snapshot"]["live_lookup_at_runtime"] is False


def test_no_networking_import_anywhere_in_the_services():
    root = Path(__file__).resolve().parents[3] / "src" / "fhir_sulo"
    banned = ("import requests", "import urllib", "import http.client", "import socket", "httpx")
    offenders = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for token in banned:
                if line.strip().startswith(token) or ("import %s" % token) in line:
                    offenders.append("%s:%d %s" % (path, lineno, line.strip()))
    assert not offenders, offenders


def test_defaults_are_explicit_outcomes_not_pass_through():
    bundle = PolicyBundle.load()
    code_defaults = bundle.code_interpretation["defaults"]
    for key in ("unknown_code_in_known_system", "unknown_system", "review_status_proposed"):
        assert code_defaults[key] in ("source-only", "rejected"), key
    assert code_defaults["silent_pass_through"] is False
    assert code_defaults["invent_class_for_unknown_code"] is False

    unit_defaults = bundle.unit["defaults"]
    for key in ("unknown_unit_code", "unknown_unit_system", "dimension_mismatch", "missing_unit_code"):
        assert unit_defaults[key] in ("source-only", "rejected"), key
    assert unit_defaults["conversion"] == "disabled"


def test_a_duplicate_table_entry_fails_validation():
    import copy

    bundle = PolicyBundle.load()
    codes = copy.deepcopy(dict(bundle.code_interpretation))
    codes["entries"].append(copy.deepcopy(codes["entries"][0]))
    variant = PolicyBundle(
        identity=bundle.identity,
        code_interpretation=codes,
        participation_type=bundle.participation_type,
        unit=bundle.unit,
        source_dir=bundle.source_dir,
    )
    with pytest.raises(PolicyError):
        variant.validate()


def test_an_unknown_review_status_fails_validation():
    import copy

    bundle = PolicyBundle.load()
    codes = copy.deepcopy(dict(bundle.code_interpretation))
    codes["entries"][0]["review_status"] = "looks-fine-to-me"
    variant = PolicyBundle(
        identity=bundle.identity,
        code_interpretation=codes,
        participation_type=bundle.participation_type,
        unit=bundle.unit,
        source_dir=bundle.source_dir,
    )
    with pytest.raises(PolicyError):
        variant.validate()


def test_the_pinned_scope_is_exactly_what_gate_0_approved():
    bundle = PolicyBundle.load()
    codes = {
        (e["system"], e["code"])
        for e in bundle.code_interpretation["entries"]
        if e["review_status"] in bundle.code_interpretation["interpretable_statuses"]
    }
    assert codes == {
        ("http://loinc.org", "33914-3"),
        ("http://loinc.org", "8480-6"),
        ("http://loinc.org", "8462-4"),
    }
    units = {
        u["code"]
        for u in bundle.unit["units"]
        if u["review_status"] in bundle.unit["interpretable_statuses"]
    }
    assert units == {"mL/min/{1.73_m2}", "mm[Hg]"}


def test_nothing_claims_clinical_signoff_yet():
    """Guard: if a reviewer approves an entry, this test must be updated with it."""
    bundle = PolicyBundle.load()
    approved = [
        e["entry_id"]
        for e in bundle.code_interpretation["entries"]
        if e["review_status"] == "approved"
    ] + [u["unit_id"] for u in bundle.unit["units"] if u["review_status"] == "approved"]
    assert approved == [], (
        "entries now claim clinical signoff: %s. Confirm the reviewer actually "
        "approved them and record it in DR-401." % approved
    )
