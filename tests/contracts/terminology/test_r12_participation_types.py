"""R12: a reviewed participation type types the encounter-scoped role node.

Answered 2026-10-03 as **both**: the one role node carries
``ex:PractitionerRole`` and ``ex:PrimaryPerformerRole``. The two are not
disjoint and the node sits in their intersection -- the role held qua
practitioner, and the primary-performer role in this one encounter.

Concept note section 2 still governs: the FHIR code literal alone is not a
class assertion. An entry in
``policies/participation-type-interpretation.v1.json`` is what makes it one.
"""

import json
import pathlib
import unittest

from fhir_sulo.terminology.service import TerminologyService
from fhir_sulo.terminology.types import ParticipationTypeNotInterpretable

ROOT = pathlib.Path(__file__).resolve().parents[3]
TABLE = json.loads(
    (ROOT / "policies" / "participation-type-interpretation.v1.json").read_text())
V3 = "http://terminology.hl7.org/CodeSystem/v3-ParticipationType"
EX = "https://w3id.org/ontostart/fhir2sulo/"


class TheReviewedTableIsTheOnlySource(unittest.TestCase):
    def setUp(self):
        self.svc = TerminologyService()

    def test_pprf_resolves_to_the_reviewed_class(self):
        self.assertEqual(self.svc.participation_role_class(V3, "PPRF"),
                         EX + "PrimaryPerformerRole")

    def test_an_unreviewed_code_raises_rather_than_typing_nothing(self):
        """The role node is emitted either way.

        A caller handed ``None`` and carrying on would assert an
        under-specified role rather than decline to assert one, so this is an
        exception and not a falsy return.
        """
        with self.assertRaises(ParticipationTypeNotInterpretable) as caught:
            self.svc.participation_role_class(V3, "ENT")
        self.assertEqual(caught.exception.reason_code, "participation-type-unreviewed")

    def test_a_proposed_code_is_present_but_types_nothing(self):
        """SBJ and ATND are in the table so adding them is a reviewed edit
        rather than an invention -- but neither may reuse PPRF's class."""
        for code in ("SBJ", "ATND"):
            with self.subTest(code=code):
                with self.assertRaises(ParticipationTypeNotInterpretable) as caught:
                    self.svc.participation_role_class(V3, code)
                self.assertEqual(caught.exception.reason_code,
                                 "participation-type-not-interpretable")

    def test_an_unknown_system_raises(self):
        with self.assertRaises(ParticipationTypeNotInterpretable):
            self.svc.participation_role_class("http://example.org/made-up", "PPRF")


class TheTableKeepsItsOwnPromises(unittest.TestCase):
    def test_nothing_is_clinically_signed_off(self):
        """Same promise the code table makes: no entry claims clinical sign-off."""
        for entry in TABLE["entries"]:
            with self.subTest(entry=entry["entry_id"]):
                self.assertNotIn(entry["review_status"],
                                 TABLE["clinically_signed_off_statuses"])

    def test_an_unknown_code_is_rejected_not_passed_through(self):
        """Deliberately unlike the observation-code table, which says
        source-only. The rationale is recorded in the table itself."""
        self.assertEqual(TABLE["defaults"]["unknown_code_in_known_system"], "rejected")
        self.assertFalse(TABLE["defaults"]["silent_pass_through"])
        self.assertFalse(TABLE["defaults"]["invent_class_for_unknown_code"])

    def test_every_interpretable_entry_declares_a_class(self):
        for entry in TABLE["entries"]:
            if entry["review_status"] in TABLE["interpretable_statuses"]:
                with self.subTest(entry=entry["entry_id"]):
                    self.assertTrue(entry.get("role_class"), entry)

    def test_the_table_is_in_the_policy_version(self):
        """A new reviewed table must move policy_version, or a run record
        cannot say which rules produced it."""
        from fhir_sulo.policy import PolicyBundle

        bundle = PolicyBundle.load()
        self.assertIn("+part-", bundle.policy_version)
        self.assertEqual(bundle.versions["participation_type"], TABLE["version"])


class TheRoleClassFollowsTheResourceNotAConstant(unittest.TestCase):
    """The manifest carries a default; the host must overwrite it from the code.

    Otherwise "the participation type types the role" would be a constant that
    merely coincides with the right answer.
    """

    def test_changing_the_tables_class_changes_the_emitted_class(self):
        import copy
        import dataclasses

        from fhir_sulo.policy import PolicyBundle

        base = PolicyBundle.load()
        table = copy.deepcopy(dict(base.participation_type))
        for entry in table["entries"]:
            if entry["code"] == "PPRF":
                entry["role_class"] = EX + "SomeOtherRole"
        svc = TerminologyService(dataclasses.replace(base, participation_type=table))
        self.assertEqual(svc.participation_role_class(V3, "PPRF"), EX + "SomeOtherRole")


if __name__ == "__main__":
    unittest.main(verbosity=2)
