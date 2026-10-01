"""R3: which Observation statuses may reach the semantic layer, and why.

Answered 2026-10-01. FHIR's `status` conflates two independent axes:

* **verification** — `registered` → `preliminary` → `final`
* **revision** — `final` → `amended` / `corrected`

A position on the revision axis is post-final and has been revisited, so it
does not reduce reliability. Holding `amended` and `corrected` at
`source-only` applied the verification axis's caution to the revision axis,
and it had a concrete cost: **a correction never reached the semantic layer**.
v2 replaced v1's graph and then asserted nothing, so the erroneous value was
removed and the corrected one never arrived.

So the widening is not a loosening, and **the point of the answer is the
distinction, not the widening**. These tests assert both directions: the two
revision statuses map, and the three non-revision statuses still do not. A
suite that only asserted "final maps" would stay green while the new statuses
were silently broken, and one that only asserted the new statuses would stay
green if the guard were removed entirely.
"""

from __future__ import annotations

import json
import unittest

from . import egfr_case
from ._engine import contractio, engine, graph
from ._engine.graph import SULO

REPO = engine.REPO
PROFILE = REPO / "profiles/fhir-r4-pilot.json"
FIXTURE = "egfr-baseline"

REVISION_ELIGIBLE = ("final", "amended", "corrected")
NOT_ELIGIBLE = ("preliminary", "registered", "entered-in-error", "cancelled", "unknown")


def with_status(base: str, status: str) -> str:
    """`egfr-baseline`'s rendered RDF with a different Observation.status.

    A labelled perturbation, not a fixture. `fixtures/r4/` is Agent 2's, and
    `egfr-corrected` is being re-pointed from `final` to `corrected` so the
    evidence matches the policy; when it lands, `test_the_corrected_fixture_
    exercises_the_new_status` below stops skipping and this perturbation
    becomes corroboration rather than the only evidence.
    """
    old = '<http://hl7.org/fhir/value> "final" .'
    assert base.count(old) == 1, base.count(old)
    return base.replace(old, '<http://hl7.org/fhir/value> "%s" .' % status)


class TheTwoAxesAreDistinguished(engine.EngineTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.base = (egfr_case.fixture_dir(FIXTURE) / "canonical.nt").read_text()

    def run_with(self, status):
        data = self.base if status == "final" else with_status(self.base, status)
        return egfr_case.run(FIXTURE, data_override=data)

    def test_the_revision_statuses_map(self):
        """`amended` and `corrected` reach the semantic layer."""
        for status in REVISION_ELIGIBLE:
            with self.subTest(status=status):
                result = self.run_with(status)
                self.assertTrue(result["validation"]["ok"],
                                "%s must be eligible after R3: %s"
                                % (status, str(result["validation"])[:400]))
                engine.require_clean(result)
                self.assertTrue(result["nquads"].strip(), "%s produced no graph" % status)

    def test_a_revision_status_produces_the_same_clinical_assertion_as_final(self):
        """The revision axis does not change what is asserted, only that it
        has been revisited. If `amended` emitted a different graph shape, the
        widening would be doing more than the answer licensed."""
        final = self.run_with("final")
        for status in ("amended", "corrected"):
            with self.subTest(status=status):
                self.assertEqual(sorted(graph.parse(self.run_with(status)["nquads"])),
                                 sorted(graph.parse(final["nquads"])))

    def test_the_verification_and_retraction_statuses_still_do_not_map(self):
        """The distinction is the answer. `preliminary` and `registered` are
        verification states; `entered-in-error` is a retraction, not a
        revision."""
        for status in NOT_ELIGIBLE:
            with self.subTest(status=status):
                result = self.run_with(status)
                self.assertFalse(result["validation"]["ok"],
                                 "%s must NOT reach the semantic layer" % status)
                self.assertEqual(result["nquads"], "")

    def test_the_status_is_bound_but_never_emitted(self):
        """Concept note section 2: the record's status belongs to the source
        layer. It is bound so it cannot be dropped silently, and asserting it
        in the semantic layer would be the record/fact confusion."""
        for status in REVISION_ELIGIBLE:
            with self.subTest(status=status):
                result = self.run_with(status)
                self.assertEqual(result["_sourceBindings"]["status"]["value"], status)
                self.assertNotIn('"%s"' % status, result["nquads"])


class TheGuardAndTheContractAgree(unittest.TestCase):
    """No Docker: these compare declared artefacts."""

    def test_the_observation_contracts_declare_the_three_statuses(self):
        for family in ("egfr", "bp"):
            with self.subTest(family=family):
                self.assertEqual(tuple(contractio.load(family).status_eligibility),
                                 REVISION_ELIGIBLE)

    def test_the_encounter_contract_is_unchanged(self):
        """R3's answer is about Observation revision statuses. Encounter has
        no revision axis in its value set, and a finished Encounter with an
        open-ended period still awaits a ruling."""
        self.assertEqual(tuple(contractio.load("encounter").status_eligibility),
                         ("finished",))

    def test_the_source_schemas_guard_exactly_those_statuses(self):
        for family in ("egfr", "bp"):
            with self.subTest(family=family):
                path = next(p for p in contractio.manifest(family)["pairing_files"]
                            if p.endswith("source.v1.shex"))
                body = (REPO / path).read_text()
                self.assertIn('["final" "amended" "corrected"]', body)
                for status in NOT_ELIGIBLE:
                    self.assertNotIn('"%s"' % status, body.split("Observation.status")[1][:400])


class TheProfileAndTheMapsAgreeAboutEligibility(unittest.TestCase):
    """Two artefacts, one question: which statuses may be interpreted?

    `profiles/fhir-r4-pilot.json :: status_policy.Observation` is the pinned
    declaration; each `MapContract.status_eligibility` is what the maps
    actually enforce. If they disagree, one of them is wrong and the graph is
    being produced under a rule nobody reviewed.

    As of this change the profile still says `amended: source-only`, because
    Agent 2's update has not landed. The maps are widened because the reviewer
    answered; this fails until the two agree. Clearing it is a three-line edit
    to `status_policy.Observation`.
    """

    def test_the_profile_and_the_contracts_agree(self):
        policy = json.loads(PROFILE.read_text())["status_policy"]["Observation"]
        eligible = tuple(sorted(s for s, outcome in policy.items() if outcome == "eligible"))
        for family in ("egfr", "bp"):
            with self.subTest(family=family):
                self.assertEqual(
                    eligible, tuple(sorted(contractio.load(family).status_eligibility)),
                    "profiles/fhir-r4-pilot.json says %s is eligible, the %s map enforces "
                    "%s. R3 was answered 2026-10-01: amended and corrected are eligible. "
                    "Update status_policy.Observation, or tell Agent 3 the relay was wrong "
                    "and the guards revert."
                    % (list(eligible), family,
                       list(contractio.load(family).status_eligibility)))


class TheCorrectedFixtureExercisesTheNewStatus(engine.EngineTestCase):
    """Agent 2 is re-pointing `egfr-corrected` from `final` to `corrected`.

    Until it lands, `TheTwoAxesAreDistinguished` carries the evidence via a
    labelled perturbation. Once it lands this becomes the real evidence and
    the perturbation is corroboration. Skips rather than fails, because the
    fixture is Agent 2's to change and the behaviour is already covered.
    """

    def test_the_corrected_fixture_uses_the_corrected_status(self):
        source = json.loads(
            (egfr_case.fixture_dir("egfr-corrected") / "egfr-456.json").read_text())
        if source["status"] != "corrected":
            self.skipTest(
                "egfr-corrected still carries status %r; Agent 2 is re-pointing it to "
                "'corrected' so Gate 4's correction row runs on the FHIR-precise status. "
                "The behaviour is covered meanwhile by TheTwoAxesAreDistinguished."
                % source["status"])
        result = egfr_case.run("egfr-corrected")
        engine.require_clean(result)
        self.assertEqual(result["_sourceBindings"]["status"]["value"], "corrected")
        self.assertEqual(
            graph.objects_of(graph.parse(result["nquads"]),
                             "<%s>" % result["_hostValues"]["result"],
                             "<%shasValue>" % SULO),
            ['"58.5"^^<http://www.w3.org/2001/XMLSchema#decimal>'])


class AnAmendmentToASourceOnlyElementStillReplaces(engine.EngineTestCase):
    """A consequence the reviewer accepted explicitly, asserted rather than
    described.

    Amend only a `source_only` element -- say `Observation.issued` -- and the
    new version's semantic triples are **identical** to its predecessor's.
    The graph key still changes, because `source_json_digest` is a content
    field, so the store reports a REPLACEMENT rather than "unchanged". That is
    visible rather than silent, and it is the same shape as DR-601's
    engine-upgrade case.

    The failure worth catching is the other one: if such an amendment ever
    reported *unchanged*, the amendment would have gone unrecorded.
    """

    FHIR = "http://hl7.org/fhir/"
    XSD = "http://www.w3.org/2001/XMLSchema#"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = (egfr_case.fixture_dir(FIXTURE) / "canonical.nt").read_text()
        cls.v1 = egfr_case.run(FIXTURE, data_override=base)
        amended = with_status(base, "amended").rstrip("\n") + "\n" + "".join([
            '<https://fhir.example/Observation/egfr-456> <%sObservation.issued> _:iss .\n'
            % cls.FHIR,
            '_:iss <%svalue> "2026-09-05T09:00:00Z"^^<%sdateTime> .\n' % (cls.FHIR, cls.XSD),
        ])
        cls.v2 = egfr_case.run(FIXTURE, data_override=amended)

    def test_both_versions_materialize(self):
        engine.require_clean(self.v1)
        engine.require_clean(self.v2)

    def test_the_amendment_really_changed_the_source(self):
        """Otherwise the test below proves nothing."""
        self.assertEqual(self.v1["_sourceBindings"]["status"]["value"], "final")
        self.assertEqual(self.v2["_sourceBindings"]["status"]["value"], "amended")

    def test_the_semantic_triples_are_identical(self):
        """`issued` and `status` are both source-only, so nothing the
        amendment touched reaches the semantic layer."""
        self.assertEqual(sorted(graph.parse(self.v1["nquads"])),
                         sorted(graph.parse(self.v2["nquads"])))

    def test_the_identity_is_identical_too(self):
        """Not merely isomorphic: the same node IRIs, so a store replacing v1
        with v2 writes the same subjects."""
        for key in ("result", "record", "timeInstant", "person", "quality", "unitIri"):
            with self.subTest(node=key):
                self.assertEqual(self.v1["_hostValues"][key], self.v2["_hostValues"][key])

    def test_the_source_digest_distinguishes_them_so_the_store_sees_a_replacement(self):
        """The graph key must still move, or the amendment goes unrecorded.

        `source_json_digest` is a graph-key content field, and the two
        versions' source JSON differs, so the key differs even though the
        triples do not.
        """
        from fhir_sulo.ingest import jsonio

        v1_json = (egfr_case.fixture_dir(FIXTURE) / "egfr-456.json").read_text()
        # edited as text, not round-tripped: re-serialising would renormalise
        # the decimal and change the digest for a reason that has nothing to
        # do with the amendment.
        amended_json = v1_json.replace('"status": "final"', '"status": "amended"')
        self.assertNotEqual(amended_json, v1_json, "the edit did nothing")
        amended_json = amended_json.replace(
            '"status": "amended",',
            '"status": "amended",\n  "issued": "2026-09-05T09:00:00Z",')
        self.assertNotEqual(jsonio.digest(v1_json),
                            jsonio.digest(amended_json),
                            "the source digest must distinguish an amendment that changed "
                            "only source-only elements, or the store reports 'unchanged' "
                            "and the amendment goes unrecorded")


if __name__ == "__main__":
    unittest.main()
