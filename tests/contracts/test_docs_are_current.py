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

#: "OPEN" as a status word. Not "open-world", which is in R5's own title --
#: the first version of this guard flagged that heading, which is the same
#: too-crude-matching mistake as banning the bare string "synthea".
_OPEN_WORD = re.compile(r"\bOPEN\b(?!-)")


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

    def _answered_items(self):
        """Review items whose heading says answered AND does not also say open.

        Review finding: the first version matched `^## (R\d+) .*ANSWERED` and
        so read `## R8 — ... R8a ANSWERED / R8b OPEN` as fully answered. A
        heading that says both is itself the defect.
        """
        review = self._read("REVIEW-REQUEST.md")
        answered = set()
        for line in review.splitlines():
            m = re.match(r"^## (R\d+) .*", line)
            if not m:
                continue
            head = line.upper()
            if ("ANSWERED" in head or "SIGNED OFF" in head) and not _OPEN_WORD.search(head):
                answered.add(m.group(1))
        return answered

    def test_no_heading_claims_an_item_is_both_answered_and_open(self):
        review = self._read("REVIEW-REQUEST.md")
        both = [
            line for line in review.splitlines()
            if re.match(r"^## R\d+ ", line)
            and ("ANSWERED" in line.upper() or "SIGNED OFF" in line.upper())
            and _OPEN_WORD.search(line.upper())
        ]
        self.assertEqual(both, [], both)

    def test_no_document_lists_an_answered_item_as_open(self):
        """Matches any claim that items remain open, not one past phrasing.

        Review finding: the regex keyed on "review items remain open", a
        sentence that no longer appears, so the loop body never ran. A guard
        whose scenario cannot occur is not guarding.
        """
        answered = self._answered_items()
        self.assertTrue(answered, "could not find any answered items to check against")
        summary = self._read("GATE-0-4-SUMMARY.md")
        pattern = re.compile(
            r"[^.\n]*\b(?:remain|remains|are still|is still|still)\s+open[^.\n]*", re.I)
        for match in pattern.finditer(summary):
            claimed = set(re.findall(r"R\d+", match.group(0)))
            self.assertFalse(
                claimed & answered,
                "GATE-0-4-SUMMARY says %r but %s are answered"
                % (match.group(0).strip(), sorted(claimed & answered)))

    def test_the_old_scope_name_is_not_advertised_as_current(self):
        """It survives only in DR-014, which quotes it as the defect."""
        for name in ("GATE-0-4-SUMMARY.md", "OPERATOR-GUIDE.md", "REVIEW-REQUEST.md"):
            with self.subTest(doc=name):
                # Case-insensitive: review appended "generated with Synthea."
                # and the case-sensitive check let it through.
                self.assertNotIn("synthea", self._read(name).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
