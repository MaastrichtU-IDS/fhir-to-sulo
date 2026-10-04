"""Two healthcare systems holding the same resource id are two people.

The identity policy has always promised this:

    scoped-hash -- "Source-scoped by construction; two sources that both hold
    Patient/p123 get different IRIs. Safe default."

The policy delivered it. **The pipeline did not call it correctly.**
``pipeline/services.py`` held

    SCOPE_ID = "fhir-sulo-fixtures-r4"
    FHIR_BASE = "https://fhir.example/"

as module constants and passed them for every resource, so every source keyed
as one. ``Patient/123`` at two different hospitals became ONE person -- a
silent false merge, and strictly worse than failing to merge, because nothing
anywhere reported it.

Found on 2026-10-04 when the reviewer said the data would come from "a variety
of different healthcare systems". Until then every fixture came from one, so
no test could have caught it: the bug was invisible to a single-source corpus.
"""

import unittest

from fhir_sulo.contracts import PILOT_FHIR_BASE_URL, PILOT_SOURCE_SCOPE_ID
from fhir_sulo.identity import (
    IdentityRequest,
    IdentityService,
    ReferenceEvidence,
    SourceScope,
)
from fhir_sulo.ingest import ingest_file

FIXTURE = "fixtures/r4/encounter/enc-baseline/enc-9.json"


class TheScopeTravelsWithTheResource(unittest.TestCase):
    def test_ingest_records_where_the_resource_came_from(self):
        ctx = ingest_file(FIXTURE, source_scope_id="radboud-umc")
        self.assertEqual(ctx.source_scope_id, "radboud-umc")

    def test_the_pilot_default_is_what_the_constant_used_to_be(self):
        """So adopting the fix re-keys nothing in this repo."""
        ctx = ingest_file(FIXTURE)
        self.assertEqual(ctx.source_scope_id, PILOT_SOURCE_SCOPE_ID)
        self.assertEqual(ctx.fhir_base_url, PILOT_FHIR_BASE_URL)

    def test_a_context_without_a_scope_cannot_key_a_person(self):
        """Keying it under a default would merge it with every other source."""
        from dataclasses import replace

        from fhir_sulo.pipeline.services import ReferenceNotAPerson, _scope_of

        ctx = replace(ingest_file(FIXTURE), source_scope_id="")
        with self.assertRaises(ReferenceNotAPerson) as caught:
            _scope_of(ctx)
        self.assertEqual(caught.exception.reason_code, "source-scope-unknown")


class TwoSystemsAreTwoPeople(unittest.TestCase):
    def _iri(self, scope_id, base):
        svc = IdentityService()
        evidence = ReferenceEvidence(
            evidence_id="e",
            kind="literal-reference",
            source_scope=SourceScope(scope_id, base),
            resource_type="Patient",
            resource_id="123",
            canonical_url=base + "Patient/123",
        )
        return svc.resolve(
            IdentityRequest("Patient/123", ("Patient",), (evidence,), entity_kind="person")
        ).unwrap().entity_iri

    def test_the_same_resource_id_at_two_systems_is_two_people(self):
        a = self._iri("maastricht-umc", "https://mumc.example/fhir/")
        b = self._iri("radboud-umc", "https://radboud.example/fhir/")
        self.assertNotEqual(a, b, "two hospitals' Patient/123 collapsed into one person")

    def test_the_scope_id_alone_is_enough_to_separate_them(self):
        """Even two systems behind one FHIR base stay separate."""
        base = "https://shared-gateway.example/fhir/"
        self.assertNotEqual(self._iri("site-a", base), self._iri("site-b", base))

    def test_the_same_system_twice_is_one_person(self):
        """The other direction: scoping must not make keying unstable."""
        self.assertEqual(
            self._iri("maastricht-umc", "https://mumc.example/fhir/"),
            self._iri("maastricht-umc", "https://mumc.example/fhir/"),
        )


class ThePipelineHonoursItEndToEnd(unittest.TestCase):
    """The unit above passed even while the bug was live, because it called the
    service directly. This one goes through the ingest path that was broken."""

    def test_two_ingests_under_two_scopes_disagree_about_the_person(self):
        from fhir_sulo.pipeline.services import _scope_of

        a = _scope_of(ingest_file(FIXTURE, source_scope_id="maastricht-umc"))
        b = _scope_of(ingest_file(FIXTURE, source_scope_id="radboud-umc"))
        self.assertNotEqual(a.scope_id, b.scope_id)

    def test_no_module_constant_is_used_for_scoping_any_more(self):
        """Regression guard on the shape of the bug, not just its symptom."""
        import inspect

        from fhir_sulo.pipeline import services

        body = inspect.getsource(services.entity_for_reference)
        self.assertNotIn("SourceScope(SCOPE_ID", body)
        self.assertIn("_scope_of(ctx)", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheScopeIdIsDefinedInOnePlace(unittest.TestCase):
    """Renamed 2026-10-04 from ``synthea-pilot-r4``.

    That name described a generator this project does not use -- there is no
    Synthea data here and never was. Harmless while the scope was a constant
    nobody could set. Not harmless once scope ids key identity: a plausible
    name invites someone to point a real Synthea export at the same scope id
    and fuse two unrelated corpora that happen to share resource ids.
    """

    #: Files allowed to mention the old name, and why. An EXPLICIT list, not a
    #: pattern: the first version of this guard banned the string outright and
    #: then flagged a sibling guard whose whole job is to assert the string is
    #: absent. A rule that cannot tell "uses the old name" from "guards
    #: against the old name" is the wrong rule, and loosening it to a
    #: substring match would have let a real use back in.
    MAY_MENTION_THE_OLD_NAME = {
        "src/fhir_sulo/contracts/source_context.py":
            "one comment explaining the rename, next to the constant it renamed",
        "tests/contracts/identity/test_multi_source_scoping.py":
            "this guard",
        "tests/contracts/test_docs_are_current.py":
            "asserts the docs do not advertise the old name",
    }

    def test_the_old_name_is_gone_from_code_policy_and_tests(self):
        """Decision records keep it: DR-014 quotes it as the defect."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        offenders = []
        for path in list(root.glob("src/**/*.py")) + list(root.glob("tests/**/*.py")) \
                + list(root.glob("policies/*.json")) + list(root.glob("maps/**/*.json")):
            rel = str(path.relative_to(root))
            if rel in self.MAY_MENTION_THE_OLD_NAME:
                continue
            if "synthea" in path.read_text(encoding="utf-8"):
                offenders.append(rel)
        self.assertEqual(offenders, [], offenders)

    def test_every_exemption_is_still_needed(self):
        """An exemption nobody needs is a hole nobody is watching."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        stale = [
            rel for rel in self.MAY_MENTION_THE_OLD_NAME
            if not (root / rel).is_file()
            or "synthea" not in (root / rel).read_text(encoding="utf-8")
        ]
        self.assertEqual(stale, [], "remove these exemptions: %s" % stale)

    def test_nothing_hardcodes_a_scope_id_beside_the_constant(self):
        """src/ must read PILOT_SOURCE_SCOPE_ID, never repeat its value.

        A second literal is how the constant and the thing callers actually
        use drift apart, which is the shape of DR-014 all over again.
        """
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[3]
        literal = '"%s"' % PILOT_SOURCE_SCOPE_ID
        offenders = [
            str(path.relative_to(root))
            for path in root.glob("src/**/*.py")
            if literal in path.read_text(encoding="utf-8")
            and path.name != "source_context.py"
        ]
        self.assertEqual(offenders, [], offenders)
