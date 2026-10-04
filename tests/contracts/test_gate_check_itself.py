"""The gate checker is believed, so it gets checked.

An independent review found three defects in `tools/gate-check.py` that this
file now makes impossible to reintroduce silently:

* `check_bp_multiset_live` was defined and never wired into CONDITIONS -- dead
  code masquerading as coverage;
* `--report` forced exit 0, so the CI gate job could never fail;
* several conditions were satisfiable without the property holding (a filename
  regex that passed on empty files, a regex over a decision record's prose).

The first two are structural and are asserted here. The third is not fully
mechanisable, but the weakest remaining form -- a condition with no check at
all -- is counted and pinned, so adding one is a deliberate act.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
GATE_CHECK = os.path.join(ROOT, "tools", "gate-check.py")


def _load_gate_check():
    """Import tools/gate-check.py as a module.

    It must be registered in sys.modules before exec_module: the file uses
    `from __future__ import annotations`, so @dataclass resolves its field
    types through sys.modules[cls.__module__], which is None for an
    unregistered module.
    """
    import importlib.util
    if "gate_check" in sys.modules:
        return sys.modules["gate_check"]
    spec = importlib.util.spec_from_file_location("gate_check", GATE_CHECK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["gate_check"] = mod
    spec.loader.exec_module(mod)
    return mod


def _source():
    return open(GATE_CHECK, encoding="utf-8").read()


class GateCheckIsWellFormed(unittest.TestCase):
    def test_it_parses(self):
        ast.parse(_source())

    def test_every_condition_names_a_defined_function(self):
        src = _source()
        defined = {n.name for n in ast.walk(ast.parse(src))
                   if isinstance(n, ast.FunctionDef)}
        referenced = set(re.findall(r"Condition\([^)]*?,\s*(check_\w+)\)", src, re.S))
        missing = sorted(referenced - defined)
        self.assertEqual(missing, [], f"CONDITIONS references undefined checks: {missing}")

    def test_no_check_function_is_dead_code(self):
        """A check nobody runs is worse than no check: it reads as coverage."""
        src = _source()
        defined = [n.name for n in ast.walk(ast.parse(src))
                   if isinstance(n, ast.FunctionDef) and n.name.startswith("check_")]
        dead = sorted(n for n in defined if src.count(n) < 2)
        self.assertEqual(dead, [], f"defined but never wired into CONDITIONS: {dead}")

    def test_report_flag_does_not_force_success(self):
        """--report selects verbosity, not leniency.

        It previously returned 0 unconditionally, which meant the CI gate job
        reported status and could never fail on it.
        """
        src = _source()
        self.assertNotIn("return 0 if a.report", src,
                         "--report must not short-circuit the exit status")

    def test_an_unmechanised_condition_reports_manual_not_pass(self):
        mod = _load_gate_check()
        c = mod.Condition(0, "test", "a condition with no check", None)
        status, _ = c.evaluate()
        self.assertEqual(status, mod.MANUAL)

    def test_a_raising_check_reports_fail_not_pass(self):
        mod = _load_gate_check()

        def boom():
            raise RuntimeError("kaboom")

        c = mod.Condition(0, "test", "a check that raises", boom)
        status, detail = c.evaluate()
        self.assertEqual(status, mod.FAIL)
        self.assertIn("kaboom", detail)

    def test_no_condition_lacks_a_check(self):
        """Every gate condition must be backed by something executable.

        A condition with `check is None` reports MANUAL and blocks, which is
        safe, but it also means nobody is checking it. Zero is the target.
        """
        mod = _load_gate_check()
        unmechanised = [c.text for c in mod.CONDITIONS if c.check is None]
        self.assertEqual(unmechanised, [],
                         "conditions with no mechanical check: " + "; ".join(unmechanised))

    def test_the_signoff_passes_because_R7_is_signed(self):
        """R7 was signed off 2026-10-03.

        This previously asserted the condition reported MANUAL while the
        review was open, which was right until the sign-off arrived. Inverted
        rather than deleted, and the guarantee it protected -- that the gate
        cannot pass without R7 -- is asserted below against a synthetic
        document instead of the shipped one.
        """
        mod = _load_gate_check()
        status, detail = mod.check_review_request_open()
        self.assertEqual(status, mod.PASS, detail)
        self.assertIn("R7", detail)

    def test_the_gate_still_blocks_if_R7_is_not_signed(self):
        """The guarantee the sign-off must not have removed.

        Plan section 4 names the record/fact and PRO/SOLID sign-off as Gate
        0's condition. If that stopped being checked, Gate 0 would pass on
        engineering alone, which is the one thing this condition exists to
        prevent.
        """
        import tempfile

        mod = _load_gate_check()
        real = open(
            os.path.join(ROOT, "docs", "fhir-sulo", "REVIEW-REQUEST.md"),
            encoding="utf-8").read()
        # Un-sign R7 and nothing else.
        unsigned = real.replace(
            "## R7 — Record/fact distinction sign-off (explicit Gate 0 condition)"
            "  \u2705 SIGNED OFF",
            "## R7 — Record/fact distinction sign-off (explicit Gate 0 condition)")
        self.assertNotEqual(unsigned, real, "could not un-sign R7; heading changed?")

        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8")
        handle.write(unsigned)
        handle.close()

        status, detail = mod.check_review_request_open(handle.name)
        self.assertEqual(status, mod.MANUAL, detail)
        self.assertIn("R7", detail)

    def _review_doc(self, status_line, open_item):
        """A minimal review request, synthesised rather than borrowed.

        This used to mutate the REAL document and relied on it still having an
        unanswered item. Once every item was answered the mutation could no
        longer produce the situation under test, and the check quietly stopped
        checking anything -- the scenario was unconstructible, so the test went
        from "refuses a lie" to "observes a pass". Synthesising both halves
        keeps it meaningful no matter how the real review progresses.
        """
        import tempfile

        body = ["# Consolidated review request", "", status_line, "",
                "## R7 — Record/fact distinction sign-off  ✅ SIGNED OFF", ""]
        if open_item:
            body += ["## R99 — A deliberately unanswered item", ""]
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8")
        handle.write("\n".join(body))
        handle.close()
        return handle.name

    def test_it_refuses_a_request_that_claims_closed_with_items_open(self):
        mod = _load_gate_check()
        path = self._review_doc("**Status:** CLOSED", open_item=True)
        status, detail = mod.check_review_request_open(path)
        self.assertEqual(status, mod.FAIL, detail)

    def test_it_accepts_an_open_request_with_items_open(self):
        """The other half: being open about being open is not a failure."""
        mod = _load_gate_check()
        path = self._review_doc("**Status:** OPEN", open_item=True)
        status, detail = mod.check_review_request_open(path)
        self.assertEqual(status, mod.PASS, detail)
        self.assertIn("R99", detail)

    def test_the_live_request_is_consistent_about_its_own_status(self):
        """Guards the real document, which the synthesised cases no longer do.

        All 12 items are answered, so the claims-closed branch is now
        unreachable from the live file. What still matters is that it does not
        advertise itself as closed while anything is outstanding.
        """
        mod = _load_gate_check()
        real = open(
            os.path.join(ROOT, "docs", "fhir-sulo", "REVIEW-REQUEST.md"),
            encoding="utf-8").read()
        status, detail = mod.check_review_request_open()
        self.assertEqual(status, mod.PASS, detail)
        if "**Status:** OPEN" not in real:
            self.fail(
                "the review request no longer says Status: OPEN. Answered is not "
                "signed off -- every binding is still pilot-provisional and nothing "
                "is approved, so the request is not closed.")

    def test_every_pytest_node_id_it_cites_actually_resolves(self):
        """A renamed test class must not quietly hollow out a gate.

        `_pytest_node` reports FAIL on "no tests ran", so a stale id turns a
        gate red rather than green -- safe, but it costs a debugging cycle
        and hides the real state. Two agents renamed classes during
        integration and four conditions went red for this reason alone.
        Collect-only is cheap; check the ids resolve.
        """
        # The stdlib fallback (`make contracts-stdlib`) runs the system
        # interpreter, which deliberately has no pytest -- so every citation
        # would report "collected 0" and this test would fail for a reason
        # that says nothing about the node ids. Skip there; `make contracts`
        # is the authoritative runner and does check them.
        probe = subprocess.run([sys.executable, "-c", "import pytest"],
                               capture_output=True)
        if probe.returncode != 0:
            self.skipTest(
                "this interpreter has no pytest; node-id resolution is checked "
                "by `make contracts` (pytest), which is authoritative")

        src = _source()
        node_ids = sorted({
            m for m in re.findall(r'"(tests/[^"]*::[^"]*)"', src)
        })
        self.assertTrue(node_ids, "expected gate-check to cite pytest node ids")

        # Some ids are split across adjacent string literals in the source.
        joined = re.findall(r'"(tests/[^"]*)"\s*\n\s*"(::[^"]*)"', src)
        node_ids += [a + b for a, b in joined]

        unresolved = []
        for nid in sorted(set(node_ids)):
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", nid, "--collect-only", "-q"],
                cwd=ROOT, capture_output=True, text=True,
                env=dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src")),
            )
            out = proc.stdout or ""
            # Parse the collected count rather than scanning for words: a
            # successful collect-only prints "N tests collected", and an
            # unrelated "error" substring elsewhere in the output is not a
            # failure of this node id.
            m = re.search(r"(\d+)\s+tests?\s+collected", out)
            collected = int(m.group(1)) if m else 0
            if proc.returncode != 0 or collected < 1:
                tail = out.strip().splitlines()[-1] if out.strip() else "no output"
                unresolved.append(f"{nid}: collected {collected}, rc={proc.returncode} ({tail})")
        self.assertEqual(unresolved, [],
                         "gate-check cites node ids that do not resolve:\n  "
                         + "\n  ".join(unresolved))


if __name__ == "__main__":
    unittest.main(verbosity=2)
