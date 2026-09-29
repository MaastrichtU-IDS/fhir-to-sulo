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

    def test_the_domain_namespace_is_still_the_r1_placeholder(self):
        """A ratified tier running on placeholder vocabulary is the current state.

        If R1 is answered this test should be updated deliberately, not
        deleted -- it is what stops 'the pipeline runs' being mistaken for
        'the vocabulary is real'.
        """
        ns = table()["domain_namespace"]
        self.assertIn(
            "example.org", ns,
            "domain_namespace is no longer a placeholder; R1 may have been "
            "answered, in which case update this test and R1b's entries together")

    def test_the_table_still_awaits_the_reviewer_overall(self):
        self.assertEqual(table()["status"], "draft-awaiting-reviewer")


if __name__ == "__main__":
    unittest.main(verbosity=2)
