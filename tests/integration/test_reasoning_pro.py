"""The OWL reasoner, and the PRO property-chain entailment. DR-602.

The brief for this deliverable was explicit: *verify your chosen reasoner
actually does this with a tiny hand-written graph before building on it -
property chains with an inverse need OWL 2 DL (HermiT-class), and a weaker
profile reasoner may silently not entail it. That verification is itself a
deliverable: a test that fails if the reasoner is swapped for one that cannot
do it.*

``ReasonerIsCapable`` is that test. ``WeakerReasonerIsRejected`` is its
negative control: ELK is run through the same code path and must be found
**not** usable, so the verification is shown to be able to fail.
"""

from __future__ import annotations

import hashlib
import unittest

import support  # noqa: F401  (sets sys.path)
from support import graph_text

from fhir_sulo.validation import reasoning

try:
    import rdflib  # noqa: F401

    HAVE_RDFLIB = True
except ImportError:  # pragma: no cover
    HAVE_RDFLIB = False

HAVE_REASONER = reasoning.reasoner_available()
SKIP_ENV = "needs rdflib: .venv/bin/pip install -r requirements-runtime.txt"
SKIP_REASONER = (
    "needs an OWL reasoner: `robot` on PATH, or docker and the pinned image %s "
    "(there is no java on the pilot host)" % reasoning.ROBOT_IMAGE_TAG
)


class OntologyIsPinned(unittest.TestCase):
    """The reasoner is only as trustworthy as the axioms it is given."""

    def test_the_vendored_sulo_matches_the_recorded_digest(self):
        with open(reasoning.SULO_PATH, "rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(
            actual,
            reasoning.SULO_SHA256,
            "the vendored SULO copy does not match DR-002's pin; the PRO "
            "entailment was verified against that exact file",
        )

    def test_the_property_chain_axiom_is_present_in_the_vendored_copy(self):
        with open(reasoning.SULO_PATH, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("owl:propertyChainAxiom", text)
        self.assertIn("owl:inverseOf sulo:hasFeature", text)

    def test_the_image_is_pinned_by_digest_not_by_tag(self):
        """A tag can be repointed at a different build; a digest cannot."""
        self.assertIn("@sha256:", reasoning.ROBOT_IMAGE)


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(HAVE_REASONER, SKIP_REASONER)
class ReasonerIsCapable(unittest.TestCase):
    """This test must fail if the reasoner is swapped for a weaker one."""

    @classmethod
    def setUpClass(cls):
        cls.verification = reasoning.verify_property_chain_support(
            reasoning.DEFAULT_REASONER
        )

    def test_the_chosen_reasoner_is_usable(self):
        self.assertTrue(
            self.verification.usable,
            "the configured reasoner cannot perform the SULO PRO entailment:\n%s"
            % self.verification.report(),
        )

    def test_the_entailment_is_materialized(self):
        self.assertTrue(self.verification.entailment_materialized)

    def test_denying_the_entailment_makes_the_ontology_inconsistent(self):
        """Asks the reasoner, not the serialiser.

        Materialization alone could in principle be produced by an axiom
        generator that was wrong in our favour. A refutation cannot.
        """
        self.assertTrue(self.verification.refutation_detected)

    def test_the_verification_names_the_triple_it_checked(self):
        self.assertIn("hasParticipant", self.verification.inferred_triple)
        self.assertIn("person-p123", self.verification.inferred_triple)


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(HAVE_REASONER, SKIP_REASONER)
class WeakerReasonerIsRejected(unittest.TestCase):
    """The negative control, without which the test above proves nothing.

    ELK is an OWL 2 EL reasoner. EL has no inverse properties, so it cannot
    apply ``hasParticipant o inverseOf(hasFeature)``. It does not say so: it
    returns fewer entailments and exits 0. That is the exact failure mode the
    verification exists to catch, so it is exercised.
    """

    def test_elk_silently_fails_the_same_verification(self):
        verification = reasoning.verify_property_chain_support("ELK")
        self.assertFalse(
            verification.usable,
            "ELK was expected to be unable to do this chain. If it now can, "
            "re-read the verification - it may have stopped testing anything.",
        )
        self.assertFalse(verification.entailment_materialized)
        self.assertFalse(verification.refutation_detected)


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(HAVE_REASONER, SKIP_REASONER)
class SeparateParseUnitsLoseTheEntailment(unittest.TestCase):
    """Pins the reason ``materialize`` merges before calling ROBOT.

    Handing ROBOT ``-i sulo.ttl -i data.ttl`` makes OWLAPI parse each file
    alone. The data file declares no object properties, so the participation
    triples are read as ``AnnotationAssertion``, the chain never fires, and
    the run exits 0 with a plausible-looking output. If someone replaces the
    merge with a two-file invocation, this test notices.
    """

    def test_the_trap_still_bites_and_is_therefore_still_worth_avoiding(self):
        self.assertTrue(
            reasoning.probe_separate_parse_units(),
            "two separate -i inputs now preserve the entailment. If ROBOT or "
            "OWLAPI fixed this, the merge in _merged_input can be simplified - "
            "but check before removing it.",
        )


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(HAVE_REASONER, SKIP_REASONER)
class EncounterEntailmentAndConsistency(unittest.TestCase):
    """Gate 3: "a PRO-aware reasoner infers the correct patient and clinician
    as participants in the encounter; the graph contains no hasPatient"."""

    @classmethod
    def setUpClass(cls):
        cls.robot = reasoning.RobotReasoner()
        cls.robot.start()
        cls.asserted = cls.robot._graph_of(graph_text("encounter-pro.ttl"))
        cls.inferred = cls.robot.materialize(cls.asserted)

    @classmethod
    def tearDownClass(cls):
        cls.robot.close()

    def _iri(self, local):
        return rdflib.URIRef("https://example.org/fhir-sulo/" + local)

    def test_the_patient_is_inferred_as_a_participant(self):
        self.assertIn(
            (self._iri("encounter-9"),
             rdflib.URIRef("https://w3id.org/sulo/hasParticipant"),
             self._iri("person-p123")),
            self.inferred,
        )

    def test_the_clinician_is_inferred_as_a_participant(self):
        self.assertIn(
            (self._iri("encounter-9"),
             rdflib.URIRef("https://w3id.org/sulo/hasParticipant"),
             self._iri("clinician-c7")),
            self.inferred,
        )

    def test_neither_person_was_asserted_as_a_participant(self):
        """Otherwise the test above would pass without any reasoning at all."""
        for local in ("person-p123", "clinician-c7"):
            self.assertNotIn(
                (self._iri("encounter-9"),
                 rdflib.URIRef("https://w3id.org/sulo/hasParticipant"),
                 self._iri(local)),
                self.asserted,
            )

    def test_the_graph_is_consistent_with_sulo(self):
        report = self.robot.check_consistency(self.asserted)
        self.assertTrue(report.consistent, report.detail)

    def test_the_graph_contains_no_hasPatient_predicate(self):
        """Acceptance matrix row PRO. Checked on the ASSERTED and the REASONED
        graph: a reasoner cannot introduce one, but checking only the asserted
        graph would leave that unstated."""
        for label, graph in (("asserted", self.asserted), ("inferred", self.inferred)):
            with self.subTest(graph=label):
                offenders = [
                    str(p) for _s, p, _o in graph if str(p).endswith("hasPatient")
                ]
                self.assertEqual(offenders, [])

    def test_a_person_typed_into_a_feature_branch_is_caught_as_inconsistent(self):
        """SULO makes Feature disjoint with SpatialObject (DR-002). This is
        the mistake review item R6 exists to prevent, and the reasoner does
        catch it - so R6 has a safety net while it is open."""
        broken = graph_text("encounter-pro.ttl") + (
            "\n<https://example.org/fhir-sulo/person-p123> a "
            "<https://w3id.org/sulo/Quality> .\n"
        )
        report = self.robot.check_consistency(broken)
        self.assertFalse(report.consistent)


if __name__ == "__main__":
    unittest.main()
