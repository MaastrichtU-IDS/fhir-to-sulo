"""IR-602: the two canonicalisers must not drift.

`policy/canonical.py` (Agent 5, entity and quality keys) and
`store/canonical.py` (Agent 6, graph keys) implement the same normalisation
rules, written independently on separate branches. Merging them into one
module is the right end state, but both are heavily depended on and each is
separately tested, so the immediate risk is not duplication itself -- it is
*silent divergence*. If they ever normalise differently, entity keys and graph
keys disagree about what "the same input" means, which is precisely the bug
both modules exist to prevent, and nothing else in the suite would notice.

This test makes divergence fail CI. It is the guard, not the fix; convergence
is tracked as debt in DR-007.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from fhir_sulo.policy import canonical as policy_canonical  # noqa: E402
from fhir_sulo.store import canonical as store_canonical  # noqa: E402

# Inputs chosen to exercise the rules both modules claim: Unicode normalisation
# (NFC), ASCII escaping, key ordering, nesting, and the float rejection.
CORPUS = [
    "",
    "p123",
    "Patient/p123",
    "https://fhir.example/Observation/egfr-456",
    "mL/min/{1.73_m2}",
    "mm[Hg]",
    "éclair",          # combining acute -- NFC should fold this
    "éclair",           # precomposed -- must equal the line above
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


class CanonicalisersAgree(unittest.TestCase):
    def test_normalise_text_agrees(self):
        for value in [c for c in CORPUS if isinstance(c, str)]:
            with self.subTest(value=value):
                self.assertEqual(
                    policy_canonical.normalise_text(value),
                    store_canonical.normalise_text(value),
                    "normalise_text diverged between policy/ and store/",
                )

    def test_canonical_json_agrees(self):
        for value in CORPUS:
            with self.subTest(value=repr(value)[:40]):
                self.assertEqual(
                    policy_canonical.canonical_json(value),
                    store_canonical.canonical_json(value),
                    "canonical_json diverged between policy/ and store/",
                )

    def test_digest_agrees(self):
        for value in CORPUS:
            with self.subTest(value=repr(value)[:40]):
                self.assertEqual(
                    policy_canonical.digest(value),
                    store_canonical.digest(value),
                    "digest diverged between policy/ and store/",
                )

    def test_sha256_hex_agrees_on_its_intended_input(self):
        """sha256_hex takes already-escaped canonical JSON, so feed it that.

        Calling it on raw Unicode raises in both modules by design (they
        encode as ASCII); that agreement is asserted separately below.
        """
        for value in CORPUS:
            canon = policy_canonical.canonical_json(value)
            with self.subTest(value=repr(value)[:40]):
                self.assertEqual(
                    policy_canonical.sha256_hex(canon),
                    store_canonical.sha256_hex(canon),
                )

    def test_both_refuse_unescaped_non_ascii_identically(self):
        """Neither may quietly accept what the other rejects."""
        raw = "e\u0301clair"
        with self.assertRaises(UnicodeEncodeError):
            policy_canonical.sha256_hex(raw)
        with self.assertRaises(UnicodeEncodeError):
            store_canonical.sha256_hex(raw)

    def test_both_reject_floats(self):
        """A float's repr is platform-dependent, so neither may hash one."""
        for mod in (policy_canonical, store_canonical):
            with self.subTest(module=mod.__name__):
                with self.assertRaises(Exception):
                    mod.canonical_json({"value": 55.0})

    def test_nfc_folding_is_actually_happening(self):
        """Control: the corpus really does contain a case that folds.

        Without this, the agreement tests above could pass vacuously on a
        corpus where no input exercises normalisation.
        """
        composed = "éclair"
        decomposed = "éclair"
        self.assertNotEqual(composed, decomposed)
        self.assertEqual(
            policy_canonical.normalise_text(composed),
            policy_canonical.normalise_text(decomposed),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
