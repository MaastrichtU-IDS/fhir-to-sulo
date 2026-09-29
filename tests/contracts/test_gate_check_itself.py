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

    def test_the_reviewer_signoff_blocks_while_the_review_is_open(self):
        """The one condition that must never mechanically PASS.

        It is mechanised -- it parses REVIEW-REQUEST.md -- but while that
        document is OPEN it must report MANUAL, so no amount of engineering
        can advance Gate 0 without a human.
        """
        mod = _load_gate_check()
        signoff = [c for c in mod.CONDITIONS if "Reviewer signs off" in c.text]
        self.assertEqual(len(signoff), 1, "expected exactly one reviewer sign-off condition")
        status, detail = signoff[0].evaluate()
        self.assertEqual(status, mod.MANUAL, f"sign-off reported {status}: {detail}")
        self.assertIn("not signed off", detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
