"""IR-602: there must be exactly one canonicaliser, and it must behave.

History, because the shape of this test only makes sense with it:

`policy/canonical.py` (Agent 5, entity and quality keys) and
`store/canonical.py` (Agent 6, graph keys) were independent implementations of
the same normalisation rules, written on separate branches. They agreed. The
first version of this file proved they agreed over a corpus exercising NFC
folding, key ordering, nesting and float rejection, and the lead proved that
guard had teeth by injecting NFC->NFD into `store/canonical.py` (3 failures).

But "two implementations that agree today" is a condition to survive, not a
design. Both are now re-export shims over a single module, `fhir_sulo.canonical`.

So this file's job changed, and deleting it would have been wrong: the risk it
guards did not go away, it moved. Before, the risk was *drift between two known
modules*. Now it is *a third copy appearing anywhere* -- which the old test
could not have seen, because it only ever compared two named imports. The
`exactly one definition under src/` scan below is strictly stronger than what
it replaces, and the behavioural corpus is kept so the surviving implementation
is still asserted to do what both claimed.

Three tiers:
  1. the two historical import paths resolve to the *same function objects*
  2. no primitive is defined more than once anywhere under `src/`
  3. the one implementation still folds NFC, orders keys, and rejects floats
"""

from __future__ import annotations

import ast
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from fhir_sulo import canonical as the_canonicaliser  # noqa: E402
from fhir_sulo.policy import canonical as policy_canonical  # noqa: E402
from fhir_sulo.store import canonical as store_canonical  # noqa: E402

SRC = Path(__file__).resolve().parents[2] / "src" / "fhir_sulo"
IMPLEMENTATION = SRC / "canonical.py"

#: Every primitive that participates in a key. A second definition of any of
#: these is a second canonicaliser, whatever it is called or where it lives.
PRIMITIVES = (
    "normalise_text",
    "_normalise",
    "canonical_json",
    "sha256_hex",
    "digest",
    "slugify",
    "key_fragment",
)

SHARED = ("normalise_text", "canonical_json", "sha256_hex", "digest")

#: One module-level function legitimately shares a name with a primitive
#: without being a second canonicaliser. Allowlisted explicitly, with the
#: reason, so that a *new* collision still fails and this one is removed
#: deliberately rather than by a quietly loosened scan.
ALLOWED_SECOND_DEFINITIONS = {
    ("digest", "src/fhir_sulo/ingest/jsonio.py"): (
        "SourceContext.source_json_digest: sha256 of the EXACT source bytes. "
        "It must NOT canonicalise -- its whole job is to notice any byte change "
        "in the source JSON, which NFC folding and key sorting would hide. "
        "Same name, deliberately different function."
    ),
}

#: NFC control pair, written as escapes. If these are typed as literals an
#: editor or a formatter can normalise the file and silently make them equal,
#: which would turn the folding control into a tautology.
COMPOSED = "éclair"        # U+00E9 LATIN SMALL LETTER E WITH ACUTE
DECOMPOSED = "éclair"     # 'e' + U+0301 COMBINING ACUTE ACCENT

# Inputs chosen to exercise the rules the module claims: Unicode normalisation
# (NFC), ASCII escaping, key ordering, nesting, and the float rejection.
CORPUS = [
    "",
    "p123",
    "Patient/p123",
    "https://fhir.example/Observation/egfr-456",
    "mL/min/{1.73_m2}",
    "mm[Hg]",
    "éclair",     # combining acute -- NFC should fold this
    "éclair",      # precomposed -- must equal the line above
    "  leading and trailing  ",
    "tab\tand\nnewline",
    "emoji \U0001F600",
    "ß Straße ÅNGSTRÖM",
    {"b": 1, "a": 2},
    {"a": 2, "b": 1},        # different insertion order, same canonical form
    {"nested": {"z": [1, 2, {"k": "v"}], "a": None}},
    [1, "two", True, None],
    {"unicode key é": "value ́"},
    123,
    -7,
    True,
    None,
]


def _definitions_under_src():
    """Map primitive name -> list of (relative path, line) where it is *defined*.

    An AST walk over **module-level** defs, not a grep. Two consequences that
    matter:

    * a re-export (`from ..canonical import digest`) is an import, not a
      definition, so the shims do not count and a genuine re-implementation does;
    * a method is not a module-level def, so the delegating `digest` properties
      on `ValidationReport` and `ShapesReport` do not count -- they call the one
      implementation rather than reproducing it.
    """
    found = {name: [] for name in PRIMITIVES}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = str(path.relative_to(SRC.parent.parent))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in found:
                    found[node.name].append((rel, node.lineno))
    return found


def _unexplained_duplicates(found):
    out = {}
    for name, sites in found.items():
        extra = [
            site
            for site in sites
            if site[0] != "src/fhir_sulo/canonical.py"
            and (name, site[0]) not in ALLOWED_SECOND_DEFINITIONS
        ]
        if extra:
            out[name] = extra
    return out


class OneImplementation(unittest.TestCase):
    """Tier 1 and 2: there is exactly one canonicaliser."""

    def test_the_historical_import_paths_are_the_same_objects(self):
        """A re-fork of either shim fails here immediately."""
        for name in SHARED:
            with self.subTest(primitive=name):
                self.assertIs(
                    getattr(policy_canonical, name),
                    getattr(store_canonical, name),
                    "policy/ and store/ no longer share one %s" % name,
                )
                self.assertIs(
                    getattr(policy_canonical, name),
                    getattr(the_canonicaliser, name),
                    "policy/%s is not fhir_sulo.canonical's" % name,
                )

    def test_no_primitive_is_defined_outside_the_one_implementation(self):
        """Catches a *third* copy, which the old two-module drift test could not."""
        unexplained = _unexplained_duplicates(_definitions_under_src())
        self.assertEqual(
            unexplained,
            {},
            "a second canonicaliser has appeared; these primitives are defined "
            "outside src/fhir_sulo/canonical.py:\n%s\nMove them into the single "
            "implementation, or allowlist them in ALLOWED_SECOND_DEFINITIONS with "
            "a reason."
            % "\n".join(
                "  %s: %s" % (k, ", ".join("%s:%d" % s for s in v))
                for k, v in sorted(unexplained.items())
            ),
        )

    def test_the_scan_is_not_vacuous(self):
        """Control: the scan must actually locate the one real definition.

        Without this, renaming `canonical.py` would make the duplicate check
        pass on zero definitions -- green, and covering nothing.
        """
        found = _definitions_under_src()
        for name in PRIMITIVES:
            with self.subTest(primitive=name):
                sites = [s for s in found[name] if s[0] == "src/fhir_sulo/canonical.py"]
                self.assertEqual(
                    len(sites),
                    1,
                    "%s is not defined exactly once in the single implementation; "
                    "found %s" % (name, found[name]),
                )

    def test_every_allowlisted_collision_still_exists(self):
        """An allowlist that names something gone is cargo cult; fail instead."""
        found = _definitions_under_src()
        for (name, path), reason in sorted(ALLOWED_SECOND_DEFINITIONS.items()):
            with self.subTest(allowlisted="%s @ %s" % (name, path)):
                self.assertTrue(
                    any(site[0] == path for site in found.get(name, [])),
                    "ALLOWED_SECOND_DEFINITIONS still allows %s in %s, but nothing "
                    "is defined there any more. Remove the entry.\nReason given: %s"
                    % (name, path, reason),
                )

    def test_the_shims_define_nothing(self):
        for shim in (SRC / "policy" / "canonical.py", SRC / "store" / "canonical.py"):
            tree = ast.parse(shim.read_text(encoding="utf-8"), filename=str(shim))
            defs = [
                n.name
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ]
            with self.subTest(shim=shim.name):
                self.assertEqual(defs, [], "%s defines %s; it must only re-export" % (shim, defs))


class CanonicaliserBehaviour(unittest.TestCase):
    """Tier 3: the surviving implementation still does what both claimed."""

    def test_nfc_folding_is_actually_happening(self):
        """Control: there really is a case that folds, so the corpus is not inert."""
        self.assertNotEqual(COMPOSED, DECOMPOSED)
        self.assertEqual(
            the_canonicaliser.normalise_text(COMPOSED),
            the_canonicaliser.normalise_text(DECOMPOSED),
        )
        self.assertEqual(
            the_canonicaliser.digest(DECOMPOSED), the_canonicaliser.digest(COMPOSED)
        )

    def test_canonical_json_is_order_independent(self):
        self.assertEqual(
            the_canonicaliser.canonical_json({"b": 1, "a": 2}),
            the_canonicaliser.canonical_json({"a": 2, "b": 1}),
        )

    def test_canonical_json_is_pure_ascii_over_the_whole_corpus(self):
        for value in CORPUS:
            with self.subTest(value=repr(value)[:40]):
                the_canonicaliser.canonical_json(value).encode("ascii")

    def test_digest_is_stable_over_the_whole_corpus(self):
        for value in CORPUS:
            with self.subTest(value=repr(value)[:40]):
                self.assertEqual(
                    the_canonicaliser.digest(value), the_canonicaliser.digest(value)
                )
                self.assertEqual(len(the_canonicaliser.digest(value)), 64)

    def test_floats_are_rejected(self):
        """A float's repr is platform-dependent, so it may never be hashed."""
        with self.assertRaises(TypeError):
            the_canonicaliser.canonical_json({"value": 55.0})

    def test_sha256_hex_refuses_unescaped_non_ascii(self):
        with self.assertRaises(UnicodeEncodeError):
            the_canonicaliser.sha256_hex("éclair")

    def test_reachable_through_both_historical_paths(self):
        """The shims are not decorative: existing importers must still work."""
        for value in CORPUS:
            with self.subTest(value=repr(value)[:40]):
                self.assertEqual(
                    policy_canonical.digest(value), store_canonical.digest(value)
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
