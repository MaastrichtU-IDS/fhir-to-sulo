"""Repository hygiene checks for mistakes that have already happened here.

Every check below corresponds to a real defect that reached the branch.
"""

from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _py_files(*rel_dirs):
    for rel in rel_dirs:
        base = os.path.join(ROOT, rel)
        for dirpath, dirnames, names in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in
                           ("__pycache__", ".venv", "node_modules")]
            for n in names:
                if n.endswith(".py"):
                    yield os.path.relpath(os.path.join(dirpath, n), ROOT)


class NoAmbiguousSiblingImports(unittest.TestCase):
    """`tests/engine/support.py` and `tests/integration/support.py` both exist.

    A bare `import support` binds whichever suite pytest happened to put on
    sys.path first, so a test silently reads another suite's helpers. This
    broke collection once, then broke a single test twice more -- including
    once from a *function-local* import that a module-level-only sweep missed.
    Relative imports are unambiguous; require them.
    """

    def test_no_bare_support_import_anywhere_in_tests(self):
        pattern = re.compile(r"^\s*(?:from\s+support\s+import|import\s+support\b)", re.M)
        offenders = []
        for rel in _py_files("tests"):
            text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
            for m in pattern.finditer(text):
                line = text[:m.start()].count("\n") + 1
                offenders.append(f"{rel}:{line}")
        self.assertEqual(
            offenders, [],
            "bare `support` imports bind the wrong suite's module; use "
            "`from .support import ...`:\n  " + "\n  ".join(offenders))

    def test_the_collision_that_motivates_this_still_exists(self):
        """If there is only one support.py, this guard is over-engineering.

        Asserted so the guard is removed deliberately rather than left as
        cargo cult if the duplication is ever resolved.
        """
        supports = [rel for rel in _py_files("tests")
                    if os.path.basename(rel) == "support.py"]
        self.assertGreater(
            len(supports), 1,
            "only one support.py remains; this guard can be deleted: " + str(supports))


class TestDirectoriesArePackages(unittest.TestCase):
    """Non-package test directories are what made the collision possible."""

    def test_suites_with_helper_modules_are_packages(self):
        for rel in ("tests", "tests/engine", "tests/integration"):
            with self.subTest(package=rel):
                self.assertTrue(
                    os.path.exists(os.path.join(ROOT, rel, "__init__.py")),
                    f"{rel} must be a package so its modules get qualified names")


if __name__ == "__main__":
    unittest.main(verbosity=2)
