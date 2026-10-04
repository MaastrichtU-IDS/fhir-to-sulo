"""The documents a reviewer is told to trust must still be true.

This session rewrote enough that several top-level claims went stale while
every test still passed -- REVIEW-REQUEST.md said R8b's rule "cannot fire"
after it had been built and demonstrated, and GATE-0-4-SUMMARY.md listed three
review items as open after all three were answered. Prose does not fail a
suite, so these are the checks that make it able to.
"""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs" / "fhir-sulo"
DECISIONS = DOCS / "decisions"


class EveryDecisionRecordIsIndexed(unittest.TestCase):
    """41 records with no map undercuts the "reviewable PR" the plan asks for."""

    def setUp(self):
        self.index = (DECISIONS / "README.md").read_text(encoding="utf-8")
        self.linked = set(re.findall(r"\]\((DR-[^)]+\.md)\)", self.index))
        self.on_disk = {p.name for p in DECISIONS.glob("DR-*.md")}

    def test_no_record_is_missing_from_the_index(self):
        self.assertEqual(sorted(self.on_disk - self.linked), [])

    def test_the_index_links_nothing_that_does_not_exist(self):
        self.assertEqual(sorted(self.linked - self.on_disk), [])

    def test_every_record_states_a_status(self):
        missing = [
            p.name for p in sorted(DECISIONS.glob("DR-*.md"))
            if not re.search(r"^\*\*Status:\*\*", p.read_text(encoding="utf-8"), re.M)
        ]
        self.assertEqual(missing, [])


class TheTopLevelDocumentsAreNotStale(unittest.TestCase):
    """Specific claims that were true when written and later became false."""

    def _read(self, name):
        return (DOCS / name).read_text(encoding="utf-8")

    def test_the_review_request_does_not_say_r8b_cannot_fire(self):
        text = self._read("REVIEW-REQUEST.md")
        self.assertNotIn("its rule cannot", text)
        self.assertNotIn("No merge rule is implemented", text)

    def test_the_review_request_does_not_call_the_merge_evidence_empty(self):
        """It has one reviewed entry; a test elsewhere requires exactly one."""
        import json

        policy = json.loads(
            (ROOT / "policies" / "identity-policy.v1.json").read_text(encoding="utf-8"))
        accepted = policy["reference_scope"]["accepted_merge_evidence"]
        text = self._read("REVIEW-REQUEST.md")
        if accepted:
            self.assertNotIn("`accepted_merge_evidence` is empty by design", text)

    def test_no_document_lists_an_answered_item_as_open(self):
        review = self._read("REVIEW-REQUEST.md")
        answered = set(re.findall(r"^## (R\d+) .*(?:ANSWERED|SIGNED OFF)", review, re.M))
        self.assertTrue(answered, "could not find any answered items to check against")
        summary = self._read("GATE-0-4-SUMMARY.md")
        for match in re.finditer(r"review items? remain open[^.\n]*", summary):
            claimed = set(re.findall(r"R\d+", match.group(0)))
            self.assertFalse(
                claimed & answered,
                "GATE-0-4-SUMMARY lists %s as open; they are answered"
                % sorted(claimed & answered))

    def test_the_old_scope_name_is_not_advertised_as_current(self):
        """It survives only in DR-014, which quotes it as the defect."""
        for name in ("GATE-0-4-SUMMARY.md", "OPERATOR-GUIDE.md", "REVIEW-REQUEST.md"):
            with self.subTest(doc=name):
                self.assertNotIn("synthea", self._read(name))


if __name__ == "__main__":
    unittest.main(verbosity=2)
