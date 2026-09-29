#!/usr/bin/env python3
"""Check a gate's stated pass conditions against what is actually in the tree.

The implementation plan states pass conditions per gate in prose. This encodes
them as checks so advancing a gate is a verifiable event rather than an
assertion in a status report. Every condition names its source in the plan.

A condition that cannot currently be checked mechanically is reported as
MANUAL, never as PASS. Reviewer sign-off is always MANUAL and always blocks.

Usage:
    python3 tools/gate-check.py 0
    python3 tools/gate-check.py --all --report
Exit status: 0 if the requested gate passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS, FAIL, MANUAL = "PASS", "FAIL", "MANUAL"


@dataclass
class Condition:
    gate: int
    source: str
    text: str
    check: Optional[Callable[[], "tuple[str, str]"]] = None

    def evaluate(self):
        if self.check is None:
            return MANUAL, "no mechanical check; requires human confirmation"
        try:
            return self.check()
        except Exception as exc:  # a broken check must not read as a pass
            return FAIL, f"check raised {type(exc).__name__}: {exc}"


def _exists(*parts):
    return os.path.exists(os.path.join(ROOT, *parts))


def _glob_any(pattern_dir, regex):
    d = os.path.join(ROOT, pattern_dir)
    if not os.path.isdir(d):
        return []
    rx = re.compile(regex)
    out = []
    for dirpath, _, names in os.walk(d):
        for n in names:
            if rx.search(n):
                out.append(os.path.relpath(os.path.join(dirpath, n), ROOT))
    return sorted(out)


def check_contract_tests():
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    venv_py = os.path.join(ROOT, ".venv", "bin", "python")
    cmd = ([venv_py, "-m", "pytest", "tests", "-q"] if os.path.exists(venv_py)
           else [sys.executable, "-m", "unittest", "discover",
                 "-s", "tests/contracts", "-p", "test_*.py"])
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    tail = (p.stderr or p.stdout).strip().splitlines()
    summary = tail[-1] if tail else "no output"
    ran = next((l for l in tail if l.startswith("Ran ")), "")
    return (PASS, f"{ran} {summary}".strip()) if p.returncode == 0 else (FAIL, summary)


def check_interfaces_frozen():
    need = ["source_context.py", "map_contract.py", "transform_result.py", "run_record.py"]
    missing = [n for n in need if not _exists("src", "fhir_sulo", "contracts", n)]
    if missing:
        return FAIL, f"missing interface modules: {', '.join(missing)}"
    return PASS, "SourceContext, MapContract, TransformResult, RunRecord present"


def check_repository_decision():
    return (PASS, "DR-001 recorded") if _exists(
        "docs", "fhir-sulo", "decisions", "DR-001-implementation-repository.md"
    ) else (FAIL, "DR-001 missing")


def check_sulo_pinned():
    p = os.path.join(ROOT, "docs", "fhir-sulo", "decisions", "DR-002-sulo-pin-and-axioms.md")
    if not os.path.exists(p):
        return FAIL, "DR-002 missing"
    text = open(p, encoding="utf-8").read()
    sha = re.search(r"\b([0-9a-f]{40})\b", text)
    ver = re.search(r"0\.2\.\d+", text)
    if not (sha and ver):
        return FAIL, "DR-002 present but lacks an immutable commit pin or version"
    return PASS, f"SULO {ver.group(0)} @ {sha.group(1)[:8]}"


def check_review_request_open():
    p = os.path.join(ROOT, "docs", "fhir-sulo", "REVIEW-REQUEST.md")
    if not os.path.exists(p):
        return FAIL, "no consolidated review request"
    text = open(p, encoding="utf-8").read()
    items = re.findall(r"^## (R\d+) ", text, re.M)
    if "**Status:** OPEN" in text:
        return MANUAL, f"{len(items)} items open ({', '.join(items)}); reviewer has not signed off"
    return PASS, f"{len(items)} items, review closed"


def check_fixtures_present():
    js = _glob_any("fixtures/r4", r"\.json$")
    if not js:
        return FAIL, "no fixtures under fixtures/r4/"
    families = {"egfr": 0, "bp": 0, "enc": 0}
    for f in js:
        low = f.lower()
        for k in families:
            if k in low:
                families[k] += 1
    missing = [k for k, v in families.items() if v == 0]
    if missing:
        return FAIL, f"{len(js)} fixtures but none for: {', '.join(missing)}"
    return PASS, f"{len(js)} fixtures (egfr {families['egfr']}, bp {families['bp']}, enc {families['enc']})"


def check_expected_bindings():
    b = _glob_any("fixtures", r"expected.*(binding|tuple)")
    if not b:
        return FAIL, "no expected binding/tuple artifacts committed"
    return PASS, f"{len(b)} expected-binding artifacts"


def check_profile_manifest():
    m = _glob_any("profiles", r"\.(json|ya?ml)$")
    if not m:
        return FAIL, "no machine-readable profile manifest under profiles/"
    bad = []
    for rel in m:
        path = os.path.join(ROOT, rel)
        if rel.endswith(".json"):
            import json
            try:
                json.load(open(path, encoding="utf-8"))
            except Exception as exc:
                bad.append(f"{rel}: {exc}")
    if bad:
        return FAIL, "manifest does not parse: " + "; ".join(bad)
    return PASS, f"{len(m)} manifest file(s) parse"


def check_engine_pinned():
    lock = _glob_any("tools/engine", r"package-lock\.json$")
    findings = _glob_any("docs/fhir-sulo", r"DR-3\d\d.*\.md$")
    if not lock:
        return FAIL, "no pinned engine lockfile under tools/engine/"
    if not findings:
        return FAIL, "engine pinned but no DR-3xx recording the capability verdict"
    return PASS, f"engine lockfile + {len(findings)} engine decision record(s)"


def _dr301_verdicts():
    """Parse the recorded probe verdict block out of DR-301."""
    p = os.path.join(ROOT, "docs", "fhir-sulo", "decisions",
                     "DR-301-engine-pin-and-capability-verdict.md")
    if not os.path.exists(p):
        return {}
    out = {}
    for m in re.finditer(r"^(PASS|FAIL)\s+(\S+)\s+(.*)$", open(p, encoding="utf-8").read(), re.M):
        out[m.group(2)] = (m.group(1), m.group(3).strip())
    return out


def check_bp_tuple_test():
    """Gate 1/3: the ENGINE must preserve within-panel pairing.

    A passing assertion in our own dataclass tests is not evidence about the
    engine, so require both: a committed, runnable engine probe and a recorded
    PASS verdict for it.
    """
    probe = _exists("tools", "engine", "probes", "p03-iteration")
    verdicts = _dr301_verdicts()
    v = verdicts.get("3")
    unit = []
    for rel in _glob_any("tests", r"\.py$"):
        t = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        if "105" in t and "120" in t and "80" in t and "70" in t:
            unit.append(rel)
    if not probe:
        return FAIL, "no committed engine probe tools/engine/probes/p03-iteration"
    if not v:
        return FAIL, "engine probe present but DR-301 records no verdict for probe 3"
    if v[0] != PASS:
        return FAIL, f"engine probe 3 recorded as {v[0]}: {v[1]}"
    if not unit:
        return FAIL, "engine passes but no unit test asserts the multiset"
    return PASS, f"engine probe 3 PASS + asserted in {', '.join(unit)}"


def check_determinism_recorded():
    v = _dr301_verdicts().get("4a")
    if not v:
        return FAIL, "DR-301 records no determinism verdict (probe 4a)"
    if v[0] != PASS:
        return FAIL, f"probe 4a recorded as {v[0]}: {v[1]}"
    return PASS, "probe 4a PASS - byte-identical across runs incl. blank-node labels"


def check_engine_gaps_documented():
    """Gate 1: unsupported behaviour documented as blocking, not hidden."""
    dev = os.path.join(ROOT, "docs", "fhir-sulo", "CONTRACT-DEVIATIONS.md")
    if not os.path.exists(dev):
        return FAIL, "no CONTRACT-DEVIATIONS.md"
    verdicts = _dr301_verdicts()
    fails = [k for k, (st, _) in verdicts.items() if st == FAIL]
    if not verdicts:
        return FAIL, "DR-301 records no probe verdicts at all"
    if not fails:
        return MANUAL, "no FAIL verdicts recorded; confirm the probe set was adversarial"
    text = open(dev, encoding="utf-8").read()
    cds = re.findall(r"^## (CD-\d+)", text, re.M)
    if not cds:
        return FAIL, f"{len(fails)} engine FAILs but no CD- entries documenting them"
    return PASS, f"{len(fails)} engine FAILs recorded; deviations {', '.join(cds)} documented"


def check_mock_services():
    """Gate 1: a deterministic mock terminology/identity service exists.

    Checking that two directories exist would pass vacuously, so run their
    suites and require a real replay test to be present and passing. The
    determinism claim is the whole point of the condition.
    """
    ident = _exists("src", "fhir_sulo", "identity")
    term = _exists("src", "fhir_sulo", "terminology")
    missing = [n for n, ok in (("identity", ident), ("terminology", term)) if not ok]
    if missing:
        return FAIL, f"missing service package(s): {', '.join(missing)}"

    replay = [r for r in _glob_any("tests", r"\.py$")
              if "replay" in r or "determinism" in r]
    if not replay:
        return FAIL, "service packages exist but no determinism/replay test guards them"

    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
    venv_py = os.path.join(ROOT, ".venv", "bin", "python")
    if os.path.exists(venv_py):
        cmd = [venv_py, "-m", "pytest", "tests", "-q"]
        runner = "pytest"
    else:
        cmd = [sys.executable, "-m", "unittest", "discover",
               "-s", "tests/contracts", "-p", "test_*.py"]
        runner = "unittest (stdlib fallback; run 'make venv' for full coverage)"
    p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    out = (p.stdout or p.stderr).strip().splitlines()
    summary = out[-1] if out else "no output"
    if p.returncode != 0:
        return FAIL, f"{runner}: {summary}"
    return PASS, f"{runner}: {summary}; replay guard in {os.path.basename(replay[0])}"


def check_explicit_field_rules():
    """Gate 0: every required field has an explicit source, target, or rejection rule.

    Mechanised in three parts rather than asserted:
      source     - the renderer must REFUSE an element absent from the pinned
                   element table, not drop it. Executed, not inspected.
      rejection  - every fixture case must declare an eligibility outcome.
      target     - every fixture case must have an expected target graph or a
                   declared negative outcome (Agent 3).
    """
    import json

    table = os.path.join(ROOT, "profiles", "fhir-r4-element-table.json")
    if not os.path.exists(table):
        return FAIL, "no pinned element table at profiles/fhir-r4-element-table.json"
    try:
        json.load(open(table, encoding="utf-8"))
    except Exception as exc:
        return FAIL, f"element table does not parse: {exc}"

    # -- source half: prove the renderer is fail-closed ----------------------
    probe = (
        "import sys, glob;"
        "sys.path.insert(0,'src');"
        "from fhir_sulo.ingest import fhir_rdf, jsonio;"
        "f=sorted(glob.glob('fixtures/r4/*/*/[!ce]*.json'))[0];"
        "d=jsonio.loads(open(f).read());"
        "d['totallyNotAFhirElement']='surprise';"
        "\ntry:\n fhir_rdf.render(d); print('FAILOPEN')\nexcept Exception: print('FAILCLOSED')"
    )
    r = subprocess.run([sys.executable, "-c", probe], cwd=ROOT,
                       capture_output=True, text=True)
    if "FAILCLOSED" not in (r.stdout or ""):
        return FAIL, ("renderer does not refuse an unpinned element "
                      f"(fail-open): {(r.stdout or r.stderr).strip()[:120]}")

    # -- rejection half: every case declares an outcome ----------------------
    cases = _glob_any("fixtures/r4", r"^case\.json$")
    if not cases:
        return FAIL, "no fixture case.json files"
    missing = []
    for rel in cases:
        try:
            d = json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))
            if not d.get("expected", {}).get("eligibility"):
                missing.append(rel)
        except Exception as exc:
            return FAIL, f"{rel} does not parse: {exc}"
    if missing:
        return FAIL, f"{len(missing)} case(s) declare no eligibility outcome"

    # -- target half: Agent 3's expected graphs ------------------------------
    expected = _glob_any("fixtures/expected", r"\.(nt|ttl|json)$")
    if not expected:
        return FAIL, (f"source and rejection rules explicit for {len(cases)} cases, "
                      "but no target rules yet: fixtures/expected/ is empty (Agent 3)")
    return PASS, (f"renderer fail-closed; {len(cases)} cases declare an outcome; "
                  f"{len(expected)} expected target artifacts")


def check_fhir_rdf_proven():
    """Gate 1: FHIR JSON to RDF proven for the fixtures, references resolved.

    Three executed parts, not a claim:
      drift      - the committed canonical RDF must match the pinned renderer
      oracle     - our render of HL7's own examples must be graph-isomorphic
                   to HL7's published Turtle (external validation)
      references - every fixture case must declare resolved references with
                   an evidence kind
    """
    import json

    build = os.path.join(ROOT, "fixtures", "r4", "build.py")
    if not os.path.exists(build):
        return FAIL, "no fixtures/r4/build.py to re-derive the canonical RDF"
    r = subprocess.run([sys.executable, build, "--check"], cwd=ROOT,
                       capture_output=True, text=True)
    if r.returncode != 0:
        return FAIL, f"committed RDF drifted from the renderer: {(r.stdout or r.stderr).strip()[:140]}"
    drift = (r.stdout or "").strip().splitlines()
    drift_msg = drift[-1] if drift else "check passed"

    venv_py = os.path.join(ROOT, ".venv", "bin", "python")
    oracle_rel = os.path.join("tests", "contracts", "ingest", "test_oracle_conformance.py")
    if not _exists(oracle_rel):
        return FAIL, "no oracle conformance test; the renderer would be self-certified"
    if os.path.exists(venv_py):
        env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
        r2 = subprocess.run([venv_py, "-m", "pytest", oracle_rel, "-q"],
                            cwd=ROOT, env=env, capture_output=True, text=True)
        out = (r2.stdout or "").strip().splitlines()
        last = out[-1] if out else ""
        if r2.returncode != 0:
            return FAIL, f"oracle conformance failed: {last}"
        if "skipped" in last and "passed" not in last:
            return FAIL, f"oracle conformance skipped entirely (rdflib missing?): {last}"
        oracle_msg = last
    else:
        oracle_msg = "oracle not executed (no .venv; run 'make venv')"
        return MANUAL, f"{drift_msg}; {oracle_msg}"

    cases = _glob_any("fixtures/r4", r"^case\.json$")
    without = []
    for rel in cases:
        d = json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))
        refs = d.get("expected", {}).get("references", {})
        if refs and not all(v.get("kind") for v in refs.values()):
            without.append(rel)
    if without:
        return FAIL, f"{len(without)} case(s) declare a reference with no evidence kind"

    return PASS, f"{drift_msg}; oracle {oracle_msg}; {len(cases)} cases declare reference evidence"


_PYTEST_CACHE = {}


def _pytest_node(nodeid, label=None):
    """Run one pytest node id and report PASS/FAIL from its exit status.

    Cached per node id so a gate with several conditions backed by the same
    class does not re-run it. If pytest is unavailable the condition reports
    MANUAL rather than PASS -- an unrunnable check must never read as a pass.
    """
    label = label or nodeid.split("::")[-1]
    if nodeid in _PYTEST_CACHE:
        return _PYTEST_CACHE[nodeid]
    venv_py = os.path.join(ROOT, ".venv", "bin", "python")
    if not os.path.exists(venv_py):
        out = (MANUAL, f"cannot run {label}: no .venv (run 'make venv')")
    else:
        target = nodeid.split("::")[0]
        if not os.path.exists(os.path.join(ROOT, target)):
            out = (FAIL, f"{target} does not exist")
        else:
            env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src"))
            r = subprocess.run([venv_py, "-m", "pytest", nodeid, "-q", "--tb=no"],
                               cwd=ROOT, env=env, capture_output=True, text=True)
            lines = [l for l in (r.stdout or "").strip().splitlines() if l.strip()]
            summary = lines[-1] if lines else "no output"
            if r.returncode == 0 and "passed" in summary:
                out = (PASS, f"{label}: {summary}")
            elif r.returncode == 0:
                out = (FAIL, f"{label} selected no tests ({summary})")
            else:
                out = (FAIL, f"{label}: {summary}")
    _PYTEST_CACHE[nodeid] = out
    return out


def check_pro_entailment():
    return _pytest_node(
        "tests/integration/test_reasoning_pro.py::EncounterEntailmentAndConsistency",
        "PRO entailment (HermiT, with ELK negative control)")


def check_no_has_patient():
    a = _pytest_node("tests/integration/test_competency_queries.py", "competency queries")
    if a[0] != PASS:
        return a
    hits = []
    for d in ("maps", "fixtures/expected", "src"):
        for rel in _glob_any(d, r"\.(shex|ttl|nt|py)$"):
            if "hasPatient" in open(os.path.join(ROOT, rel), encoding="utf-8",
                                    errors="ignore").read():
                hits.append(rel)
    hits = [h for h in hits if "test" not in h.lower()]
    if hits:
        return FAIL, f"hasPatient appears in {', '.join(hits[:4])}"
    return PASS, f"{a[1]}; no hasPatient in maps, expected graphs or src"


def check_unchanged_reprocessing():
    return _pytest_node("tests/integration/test_correction.py::UnchangedReprocessing",
                        "unchanged reprocessing")


def check_v1_to_v2():
    return _pytest_node("tests/integration/test_correction.py::VersionOneToVersionTwo",
                        "v1 to v2 supersession")


def check_entered_in_error():
    return _pytest_node("tests/integration/test_correction.py::EnteredInError",
                        "entered-in-error retraction")


def check_clean_deployment_hashes():
    return _pytest_node(
        "tests/integration/test_correction.py::StoreIntegrity"
        "::test_state_digest_is_reproducible_from_a_clean_store",
        "clean-store digest reproducibility")


def check_benchmark():
    import json
    p = os.path.join(ROOT, "benchmarks", "last-report.json")
    if not os.path.exists(p):
        return FAIL, "no benchmarks/last-report.json"
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as exc:
        return FAIL, f"benchmark report does not parse: {exc}"
    if not d.get("passed"):
        return FAIL, f"benchmark did not pass: {d.get('total_seconds')}s"
    secs = d.get("total_seconds")
    n = d.get("resources")
    return PASS, f"{n} resources in {secs}s (targets: 15 min, 6 GB)"


CONDITIONS: List[Condition] = [
    # ---- Gate 0 -----------------------------------------------------------
    Condition(0, "DR-001 / plan §1", "Implementation repository chosen and recorded", check_repository_decision),
    Condition(0, "plan Gate 0", "SULO ontology pinned to an immutable identifier", check_sulo_pinned),
    Condition(0, "plan §3", "The four shared interfaces are fixed", check_interfaces_frozen),
    Condition(0, "plan §3", "Interface guard tests pass", check_contract_tests),
    Condition(0, "plan Gate 0", "The manifest parses", check_profile_manifest),
    Condition(0, "plan Gate 0", "Fixtures are committed", check_fixtures_present),
    Condition(0, "plan Gate 0", "Expected pivot tuples are committed", check_expected_bindings),
    Condition(0, "plan Gate 0", "Every required field has an explicit source, target, or rejection rule", check_explicit_field_rules),
    Condition(0, "plan Gate 0", "Reviewer signs off on record/fact distinction and PRO/SOLID patterns", check_review_request_open),
    # ---- Gate 1 -----------------------------------------------------------
    Condition(1, "plan Gate 1", "Engine build pinned with a recorded capability verdict", check_engine_pinned),
    Condition(1, "plan Gate 1", "FHIR JSON to RDF proven for the fixtures, references resolved", check_fhir_rdf_proven),
    Condition(1, "plan Gate 1", "Two BP panels preserve their component pairing", check_bp_tuple_test),
    Condition(1, "plan Gate 1", "Running the same map twice yields the same graph identity", check_determinism_recorded),
    Condition(1, "plan Gate 1", "Unsupported engine behaviour documented as a blocking issue, not hidden in a postprocessor", check_engine_gaps_documented),
    Condition(1, "plan Gate 1", "Deterministic mock terminology/identity service available", check_mock_services),
    # ---- Gate 2 -----------------------------------------------------------
    Condition(2, "plan Gate 2", "Normal eGFR fixture yields exactly one value/unit/quality/patient association"),
    Condition(2, "plan Gate 2", "Every negative fixture takes its specified source-only or rejected path"),
    Condition(2, "plan Gate 2", "No source modification is lost"),
    Condition(2, "plan Gate 2", "Inverse validation recovers the shared pivot variables"),
    Condition(2, "plan Gate 2", "No orphan quantity/unit nodes"),
    # ---- Gate 3 -----------------------------------------------------------
    Condition(3, "plan Gate 3", "BP tuple multiset exact in baseline and all permutations", check_bp_tuple_test),
    Condition(3, "plan Gate 3", "PRO-aware reasoner infers patient and clinician as participants", check_pro_entailment),
    Condition(3, "plan Gate 3", "Graph contains no hasPatient", check_no_has_patient),
    Condition(3, "plan Gate 3", "Inverse map recovers all shared bindings per scope"),
    # ---- Gate 4 -----------------------------------------------------------
    Condition(4, "plan Gate 4", "Unchanged reprocessing changes no triples", check_unchanged_reprocessing),
    Condition(4, "plan Gate 4", "Version 2 removes stale version-1 derived assertions, preserving v1 lineage", check_v1_to_v2),
    Condition(4, "plan Gate 4", "entered-in-error removes clinical assertions", check_entered_in_error),
    Condition(4, "plan Gate 4", "Clean deployment produces identical graph hashes for the fixture suite", check_clean_deployment_hashes),
    Condition(4, "plan Gate 4", "Benchmark: 10,000 resources, 4 vCPU / 8 GB, under 15 min, peak memory under 6 GB", check_benchmark),
]


def _own_conditions_pass(gate: int):
    results = [(c, *c.evaluate()) for c in CONDITIONS if c.gate == gate]
    nfail = sum(1 for _, s, _ in results if s == FAIL)
    nman = sum(1 for _, s, _ in results if s == MANUAL)
    return results, nfail == 0 and nman == 0


def run_gate(gate: int, verbose=True, _cache={}):
    """Evaluate one gate. A gate is only PASSED if every prior gate is too.

    Plan section 6 rule 5: "no new FHIR resource family starts until the
    current vertical slice and its negative cases pass". Without the ordering
    check a later gate could report PASSED while an earlier one is blocked,
    which is exactly the overclaim this tool exists to prevent.
    """
    results, own_ok = _own_conditions_pass(gate)
    npass = sum(1 for _, s, _ in results if s == PASS)
    nfail = sum(1 for _, s, _ in results if s == FAIL)
    nman = sum(1 for _, s, _ in results if s == MANUAL)

    blocked_by = []
    for earlier in sorted({c.gate for c in CONDITIONS if c.gate < gate}):
        if earlier not in _cache:
            _cache[earlier] = _own_conditions_pass(earlier)[1]
        if not _cache[earlier]:
            blocked_by.append(earlier)

    if verbose:
        print(f"\n=== Gate {gate} ===")
        for c, status, detail in results:
            mark = {PASS: "PASS", FAIL: "FAIL", MANUAL: "MANL"}[status]
            print(f"  [{mark}] {c.text}")
            print(f"         {c.source} - {detail}")
        if own_ok and blocked_by:
            print(f"  [HELD] all own conditions pass, but Gate(s) "
                  f"{', '.join(map(str, blocked_by))} are not passed")
            print(f"         plan section 6 rule 5 - gates advance in order")
        own = "own conditions PASS" if own_ok else "own conditions BLOCKED"
        verdict = "PASSED" if (own_ok and not blocked_by) else (
            "HELD" if own_ok else "BLOCKED")
        print(f"  -> Gate {gate} {verdict}  ({npass} pass, {nfail} fail, "
              f"{nman} manual; {own})")
    return own_ok and not blocked_by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gate", nargs="?", type=int)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.all:
        oks = [run_gate(g) for g in sorted({c.gate for c in CONDITIONS})]
        print("\nGates passing:", sum(oks), "of", len(oks))
        return 0 if a.report else (0 if all(oks) else 1)
    if a.gate is None:
        ap.error("give a gate number or --all")
    return 0 if run_gate(a.gate) else 1


if __name__ == "__main__":
    sys.exit(main())
