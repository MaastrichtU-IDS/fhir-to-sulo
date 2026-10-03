"""The live entity-IRI style must equal the recorded decision.

DR-005 recorded `scoped-slug` on 2026-09-29. The policy shipped
`scoped-hash`. Nobody noticed for four days, because **no test compared the
two** -- the decision lived in a markdown file and the behaviour lived in a
JSON file and nothing joined them.

That is the drift this file exists to prevent. It does not care *which*
style is chosen; it cares that the running system and the written decision
say the same thing.

(The discrepancy, when finally investigated, resolved in favour of
`scoped-hash`: `scoped-slug` embeds the FHIR resource id in the semantic
individual's IRI -- `person-synthea-pilot-r4-p123-144658ab` -- which names
the person after the record and invites the conflation concept note §2
exists to prevent. The reasoning is in the policy's `key_style_decision`.)
"""

from __future__ import annotations

import json
import os
import re
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
POLICY = os.path.join(ROOT, "policies", "identity-policy.v1.json")
DR005 = os.path.join(ROOT, "docs", "fhir-sulo", "decisions",
                     "DR-005-entity-iri-style-and-agent5-scope.md")


def entity_iri():
    return json.load(open(POLICY, encoding="utf-8"))["entity_iri"]


class TheLiveStyleMatchesTheRecord(unittest.TestCase):
    def test_the_policy_carries_the_decision_that_set_it(self):
        decision = entity_iri().get("key_style_decision")
        self.assertIsNotNone(
            decision,
            "the live key_style must carry the decision that set it, or the "
            "two can drift again")
        self.assertEqual(decision["style"], entity_iri()["key_style"])
        self.assertTrue(decision.get("record"), "name the decision record")

    def test_the_decision_record_exists_and_names_this_style(self):
        self.assertTrue(os.path.exists(DR005), DR005)
        text = open(DR005, encoding="utf-8").read()
        style = entity_iri()["key_style"]
        self.assertIn(
            style, text,
            "DR-005 does not mention the style that is actually in force; "
            "update the record or the policy, but they must agree")

    def test_the_style_is_one_the_policy_documents(self):
        e = entity_iri()
        self.assertIn(e["key_style"], e["key_style_options"])


class WhatTheChosenStyleGuarantees(unittest.TestCase):
    """scoped-hash is opaque. If that changes, these say what is lost."""

    def test_the_local_name_carries_no_source_identifier(self):
        e = entity_iri()
        if e["key_style"] != "scoped-hash":
            self.skipTest("only scoped-hash claims opacity; style is %s"
                          % e["key_style"])
        import glob

        pattern = re.compile(
            re.escape(e["base"]) + r"(?:person|practitioner|quality)-([^>\s]+)")
        seen = 0
        for path in glob.glob(os.path.join(ROOT, "fixtures", "expected",
                                           "*", "*", "target.nt")):
            for m in pattern.finditer(open(path, encoding="utf-8").read()):
                seen += 1
                local = m.group(1)
                self.assertRegex(
                    local, r"^[0-9a-f]{32}$",
                    "an entity IRI whose local name is not an opaque hash names "
                    "the semantic individual after something -- check it is not "
                    "the FHIR resource id")
        self.assertGreater(seen, 0, "no entity IRIs found to check")


if __name__ == "__main__":
    unittest.main(verbosity=2)
