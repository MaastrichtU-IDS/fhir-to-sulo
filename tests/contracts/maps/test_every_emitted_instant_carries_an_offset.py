"""The property that makes R5 row 2's reasoning sound.

The reviewer answered R5 row 2 -- do not materialize a ``sulo:Unit`` on a time
instant -- on the grounds that *"time instants are specified in the has value
datatype"*.

I initially recorded that reasoning as overstated (CD-7, since corrected),
on the belief that FHIR ``dateTime`` permits a clock time with no offset, so
``xsd:dateTime`` could not distinguish a specified instant from an
under-specified one. **That belief was wrong.** FHIR R4's published regex for
``dateTime`` places the timezone group inside the ``T`` group and does not
make it optional, so a clock time without an offset is not conformant R4 and
cannot occur:

    2026-09-02             valid   -> renders xsd:date, not an instant (DR-009)
    2026-09-02T14:00:00    INVALID
    2026-09-02T14:00:00Z   valid
    2026-09-02T14:00:00+01:00  valid

So every conformant value that renders ``xsd:dateTime`` carries an offset, and
the reviewer's reasoning holds: the emitted literal does specify the instant.

That guarantee is currently a property of FHIR plus our renderer plus the
source shape, none of which states it in one place. This file states it, on
the graphs we actually emit, so it cannot quietly stop being true.
"""

from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from tests.integration import mapoutput  # noqa: E402

XSD_DATETIME = "http://www.w3.org/2001/XMLSchema#dateTime"
OFFSET = re.compile(r"(Z|[+-](?:0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00)$")

# The published R4 dateTime regex, reproduced so the claim above is checkable
# here and not only in Agent 2's ingestion suite.
R4_DATETIME = re.compile(
    r"^(?:([0-9]([0-9]([0-9][1-9]|[1-9]0)|[1-9]00)|[1-9]000)"
    r"(-(0[1-9]|1[0-2])(-(0[1-9]|[1-2][0-9]|3[0-1])"
    r"(T([01][0-9]|2[0-3]):[0-5][0-9]:([0-5][0-9]|60)(\.[0-9]+)?"
    r"(Z|(\+|-)((0[0-9]|1[0-3]):[0-5][0-9]|14:00)))?)?)?)$"
)


@unittest.skipUnless(mapoutput.AVAILABLE, mapoutput.SKIP_NO_FIXTURES)
class EveryEmittedInstantCarriesAnOffset(unittest.TestCase):
    def _datetime_literals(self):
        found = []
        for item in mapoutput.MAPPED:
            for line in item.triples().splitlines():
                if XSD_DATETIME in line and "hasValue" in line:
                    m = re.search(r'"([^"]+)"\^\^<%s>' % re.escape(XSD_DATETIME), line)
                    if m:
                        found.append((item.fixture_id, m.group(1)))
        return found

    def test_there_are_some_to_check(self):
        self.assertTrue(self._datetime_literals(), "no xsd:dateTime instants emitted")

    def test_every_one_carries_an_offset(self):
        for fixture, lexical in self._datetime_literals():
            with self.subTest(fixture=fixture, value=lexical):
                self.assertRegex(
                    lexical, OFFSET,
                    "an emitted instant with no offset would be an under-specified "
                    "instant, which R5 row 2's reasoning assumes cannot occur")

    def test_the_r4_regex_is_why_and_still_says_so(self):
        """If FHIR ever relaxed this, the reasoning above would need revisiting."""
        self.assertIsNone(
            R4_DATETIME.match("2026-09-02T14:00:00"),
            "R4 now permits a clock time with no offset; R5 row 2's reasoning, "
            "CD-7 and DR-009 all need revisiting")
        for ok in ("2026-09-02", "2026-09-02T14:00:00Z", "2026-09-02T14:00:00+01:00"):
            self.assertIsNotNone(R4_DATETIME.match(ok), ok)

    def test_a_date_only_value_never_becomes_an_instant(self):
        """DR-009, checked on output rather than asserted in prose."""
        for item in mapoutput.MAPPED:
            for line in item.triples().splitlines():
                if "XMLSchema#date>" in line:
                    self.fail("%s emitted an xsd:date into the semantic layer; "
                              "a date is not an instant (DR-009)" % item.fixture_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
