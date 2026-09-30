"""R10 is answered: the pilot-provisional tier is ratified. Guard what it did NOT settle.

The reviewer accepted option A on 2026-09-29, so an entry at
``pilot-provisional`` may be interpreted and the eGFR and BP slices may
produce a materialized graph on synthetic data.

The risk in an accepted middle tier is drift: "good enough to execute" quietly
becoming "good enough to believe". These tests hold the line the answer
explicitly did not move.
"""

from __future__ import annotations

import json
import os
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TABLE = os.path.join(ROOT, "policies", "code-interpretation.v1.json")


def table():
    return json.load(open(TABLE, encoding="utf-8"))


class R10IsAnsweredAndRecorded(unittest.TestCase):
    def test_the_answer_is_recorded_in_the_policy_not_only_in_prose(self):
        d = table().get("reviewer_decisions", {}).get("R10")
        self.assertIsNotNone(d, "R10's answer must live where the machinery can see it")
        self.assertEqual(d["answer"], "A")
        self.assertTrue(d.get("answered_on"))

    def test_the_provisional_tier_is_interpretable_because_it_was_ratified(self):
        d = table()
        self.assertIn("pilot-provisional", d["interpretable_statuses"])


class WhatR10DidNotSettle(unittest.TestCase):
    def test_provisional_still_confers_no_clinical_signoff(self):
        d = table()
        self.assertEqual(
            d["clinically_signed_off_statuses"], ["approved"],
            "R10 ratified execution, not belief; only 'approved' is signed off")
        self.assertNotIn("pilot-provisional", d["clinically_signed_off_statuses"])

    def test_nothing_is_approved(self):
        offenders = [e.get("code") for e in table()["entries"]
                     if e.get("review_status") == "approved"]
        self.assertEqual(
            offenders, [],
            "R10 promoted nothing to approved; individual typings are R1b, still open: "
            + str(offenders))

    def test_the_domain_namespace_is_the_one_r1_confirmed(self):
        """Updated deliberately when R1 was answered, as its predecessor asked.

        This previously asserted the namespace was still a placeholder, and
        said to update it rather than delete it when R1 landed. R1 was
        answered A on 2026-09-30 with the namespace confirmed on 2026-09-30
        after a transposition check (``wi3d`` vs ``w3id``).

        What it guards now: the namespace is a *recorded* decision, not a
        value someone edited in. It is a graph-key input via
        ``quality_class_iri``, so a silent change re-keys every quality IRI.
        """
        ns = table()["domain_namespace"]
        self.assertEqual(ns, "https://w3id.org/ontostart/fhir2sulo/")
        self.assertNotIn("example.org", ns, "the placeholder must not return")

        decision = table()["reviewer_decisions"].get("R1")
        self.assertIsNotNone(decision, "a real namespace must carry the decision that set it")
        self.assertEqual(decision["namespace"], ns,
                         "the recorded decision and the live value must agree")

    def test_the_typings_are_still_not_approved(self):
        """R1's namespace is settled; R1b's three typings are not.

        Answering where the classes live says nothing about whether
        33914-3 means EGFRResult. Those entries stay pilot-provisional.
        """
        for e in table()["entries"]:
            if e.get("result_class"):
                with self.subTest(code=e["code"]):
                    self.assertNotEqual(e["review_status"], "approved")

    def test_the_table_still_awaits_the_reviewer_overall(self):
        self.assertEqual(table()["status"], "draft-awaiting-reviewer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
