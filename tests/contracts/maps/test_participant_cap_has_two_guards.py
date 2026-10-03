"""`Encounter.participant` is capped at one, and two separate things enforce it.

DR-201 §5.1 caps it because each participant needs its own role and holder
IRI and `staticVars` are global to a materialization. The contract promises a
second participant **fails loudly** rather than being silently dropped.

That promise was asserted nowhere, and it rests on two guards with very
different lifetimes:

1. the ShEx source shape's cardinality, which fires first today;
2. `families.py`, which consults only `participant[0]` by exact FHIRPath.

Guard 1 is **expected to be lifted at Gate 5**, when repeated groups like
`MedicationAdministration.dosage` need to map. If it were lifted without
touching guard 2, `participant[1]` would be resolved by ingestion and then
never consulted -- dropped without trace, which is precisely what the
contract says cannot happen.

So both are tested, and guard 2 is tested *directly* rather than through
guard 1, because guard 1 currently masks it.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

from fhir_sulo.pipeline import families  # noqa: E402
from fhir_sulo.pipeline.services import ReferenceNotAPerson  # noqa: E402


class _Ctx:
    def __init__(self, paths):
        self.resolved_references = {p: object() for p in paths}


class GuardTwoRefusesAnUnconsultedParticipant(unittest.TestCase):
    """Tested directly: the ShEx cap masks it in an end-to-end run."""

    def test_one_participant_is_fine(self):
        families._refuse_unconsulted_participants(
            _Ctx(["Encounter.subject", "Encounter.participant[0].individual"]))

    def test_a_second_participant_is_refused_not_dropped(self):
        with self.assertRaises(ReferenceNotAPerson) as caught:
            families._refuse_unconsulted_participants(_Ctx([
                "Encounter.subject",
                "Encounter.participant[0].individual",
                "Encounter.participant[1].individual",
            ]))
        self.assertEqual(caught.exception.reason_code,
                         "encounter-multiple-participants")
        self.assertIn("participant[1]", caught.exception.reason)

    def test_it_counts_every_extra_not_just_the_first(self):
        with self.assertRaises(ReferenceNotAPerson) as caught:
            families._refuse_unconsulted_participants(_Ctx([
                "Encounter.participant[%d].individual" % i for i in range(4)
            ]))
        self.assertIn("3 participant(s) beyond the first",
                      caught.exception.reason)

    def test_it_does_not_fire_on_unrelated_references(self):
        families._refuse_unconsulted_participants(
            _Ctx(["Observation.subject", "Observation.performer[1]"]))


class GuardOneFailsLoudlyEndToEnd(unittest.TestCase):
    """The promise as it holds today, through the whole pipeline."""

    def test_a_two_participant_encounter_is_refused_with_a_nonzero_exit(self):
        src = json.load(open(os.path.join(
            ROOT, "fixtures/r4/encounter/enc-baseline/enc-9.json"), encoding="utf-8"))
        second = copy.deepcopy(src["participant"][0])
        second["individual"] = {"reference": "Practitioner/c8"}
        src["participant"] = [src["participant"][0], second]
        src["id"] = "enc-two-participants"

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "enc-two.json")
            json.dump(src, open(path, "w", encoding="utf-8"))
            proc = subprocess.run(
                [sys.executable, "-m", "fhir_sulo.pipeline.cli", "batch",
                 "--family", "encounter", "--out", os.path.join(tmp, "b.jsonl"), path],
                cwd=ROOT, capture_output=True, text=True,
                env=dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src")),
            )
        self.assertNotEqual(proc.returncode, 0,
                            "a second participant must not be silently accepted")
        combined = proc.stdout + proc.stderr
        self.assertTrue(
            "SourceValidationFailure" in combined
            or "encounter-multiple-participants" in combined,
            "refused, but not by either named guard:\n" + combined[-800:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
