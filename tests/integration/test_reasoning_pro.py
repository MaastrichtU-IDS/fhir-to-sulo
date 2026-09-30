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

from . import mapoutput

from fhir_sulo.validation import reasoning

try:
    import rdflib  # noqa: F401

    HAVE_RDFLIB = True
except ImportError:  # pragma: no cover
    HAVE_RDFLIB = False

HAVE_REASONER = reasoning.reasoner_available()
SKIP_ENV = "needs rdflib: .venv/bin/pip install -r requirements-runtime.txt"

try:  # pyshacl is a runtime dependency; one test below needs it
    import pyshacl as _pyshacl  # noqa: F401
    HAVE_SHACL = True
except Exception:  # pragma: no cover - depends on the environment
    HAVE_SHACL = False
SKIP_SHACL = (
    "needs pyshacl: .venv/bin/pip install -r requirements-runtime.txt. "
    "Every other test in this module skips without it; this one used to "
    "raise MissingDependencyError instead, which reads as a defect rather "
    "than a missing dependency."
)
R6_ANSWER = "https://w3id.org/sulo/SpatialObject"
"""Review item R6, answered 2026-09-30: "a person is a Spatial Object."

Recorded as a constant so the answer appears once and every test that
depends on it moves together."""

SULO_OBJECT = "https://w3id.org/sulo/Object"

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
@unittest.skipUnless(mapoutput.AVAILABLE, mapoutput.SKIP_NO_FIXTURES)
class EncounterEntailmentOnRealMapOutput(unittest.TestCase):
    """Gate 3, on the graphs the maps actually emit.

        a PRO-aware reasoner infers the correct patient and clinician as
        participants in the encounter; the graph contains no hasPatient

    Review finding M2: this ran on ``tests/integration/graphs/encounter-pro.ttl``,
    a hand-written graph using ``ex:person-p123`` and ``sulo:SpatialObject``.
    The real map emits ``person-<32 hex>`` and ``sulo:Object``. The properties
    held on both, so nothing was wrong - but a Gate 3 condition backed by a
    graph no pipeline produces establishes nothing, and would not notice the
    map drifting. It now runs on ``fixtures/expected/encounter/*/target.nt``.
    """

    FIXTURES = ("enc-baseline", "enc-contained-practitioner")

    @classmethod
    def setUpClass(cls):
        cls.robot = reasoning.RobotReasoner()
        cls.robot.start()
        cls.cases = {}
        for fixture_id in cls.FIXTURES:
            asserted = mapoutput.by_id(fixture_id).graph()
            cls.cases[fixture_id] = (asserted, cls.robot.materialize(asserted))

    @classmethod
    def tearDownClass(cls):
        cls.robot.close()

    HAS_PARTICIPANT = "https://w3id.org/sulo/hasParticipant"
    IS_FEATURE_OF = "https://w3id.org/sulo/isFeatureOf"
    RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    ROLE = "https://w3id.org/sulo/Role"

    def _role_holders(self, graph):
        """(encounter, role, holder) triples, read out of the graph itself.

        Nothing is hard-coded: the IRIs in real map output are content
        hashes, so the test discovers them rather than asserting a literal
        that would have to be updated whenever the identity policy moves.
        """
        p = rdflib.URIRef
        out = set()
        for encounter, _p, role in graph.triples((None, p(self.HAS_PARTICIPANT), None)):
            if (role, p(self.RDF_TYPE), p(self.ROLE)) not in graph:
                continue
            for _r, _p2, holder in graph.triples((role, p(self.IS_FEATURE_OF), None)):
                out.add((encounter, role, holder))
        return out

    def test_the_maps_emit_two_typed_roles_per_encounter(self):
        for fixture_id, (asserted, _inferred) in self.cases.items():
            with self.subTest(fixture=fixture_id):
                holders = self._role_holders(asserted)
                self.assertEqual(len(holders), 2, holders)

    def test_both_holders_are_inferred_as_participants(self):
        p = rdflib.URIRef
        for fixture_id, (asserted, inferred) in self.cases.items():
            for encounter, role, holder in self._role_holders(asserted):
                with self.subTest(fixture=fixture_id, role=str(role)):
                    self.assertIn(
                        (encounter, p(self.HAS_PARTICIPANT), holder),
                        inferred,
                        "the SULO property chain did not put %s in %s"
                        % (holder, encounter),
                    )

    def test_neither_holder_was_asserted_as_a_participant(self):
        """Otherwise the test above would pass with no reasoning at all."""
        p = rdflib.URIRef
        for fixture_id, (asserted, _inferred) in self.cases.items():
            for encounter, _role, holder in self._role_holders(asserted):
                with self.subTest(fixture=fixture_id):
                    self.assertNotIn(
                        (encounter, p(self.HAS_PARTICIPANT), holder), asserted
                    )

    def test_the_patient_and_the_clinician_are_distinct_people(self):
        """A chain that collapsed both roles onto one holder would satisfy
        "both inferred" while being badly wrong."""
        for fixture_id, (asserted, _inferred) in self.cases.items():
            with self.subTest(fixture=fixture_id):
                holders = {h for _e, _r, h in self._role_holders(asserted)}
                self.assertEqual(len(holders), 2, holders)

    def test_every_emitted_graph_is_consistent_with_sulo(self):
        for item in mapoutput.MAPPED:
            with self.subTest(fixture=item.fixture_id):
                report = self.robot.check_consistency(item.graph())
                self.assertTrue(report.consistent, report.detail)

    def test_no_emitted_graph_contains_a_hasPatient_predicate(self):
        """Acceptance matrix row PRO, over real output, asserted and inferred.

        A reasoner cannot introduce one, but checking only the asserted graph
        would leave that unstated.
        """
        for fixture_id, (asserted, inferred) in self.cases.items():
            for label, graph in (("asserted", asserted), ("inferred", inferred)):
                with self.subTest(fixture=fixture_id, graph=label):
                    offenders = [
                        str(pred) for _s, pred, _o in graph
                        if str(pred).endswith(("hasPatient", "hasSubject"))
                    ]
                    self.assertEqual(offenders, [])
        for item in mapoutput.MAPPED:
            with self.subTest(fixture=item.fixture_id, graph="asserted"):
                offenders = [
                    str(pred) for _s, pred, _o in item.graph()
                    if str(pred).endswith(("hasPatient", "hasSubject"))
                ]
                self.assertEqual(offenders, [])

    @unittest.expectedFailure
    def test_the_maps_emit_the_r6_answer(self):
        """Review item R6 is ANSWERED: a person is a ``sulo:SpatialObject``.

        **This is an expected failure on purpose, and it is self-clearing.**
        The reviewer has answered; Agent 3's map change had not landed when
        this was written, so the maps still emit bare ``sulo:Object``.

        ``expectedFailure`` is the right marker rather than a skip or a
        softened assertion, because the moment the maps start emitting
        ``SpatialObject`` this reports an **unexpected success**, which is a
        failure, and whoever lands that change is told to delete this
        decorator. A skip would go quiet; an assertion of the *current*
        behaviour would silently start passing for the wrong reason once both
        sides moved - which is exactly how the original placeholder/map
        disagreement went unnoticed.
        """
        graph = mapoutput.by_id("enc-baseline").graph()
        p = rdflib.URIRef
        people = set(graph.subjects(p(self.RDF_TYPE), p(mapoutput.EX + "Person")))
        self.assertTrue(people)
        for person in people:
            self.assertIn(
                (person, p(self.RDF_TYPE), p(R6_ANSWER)), graph,
                "R6 was answered %s; this person is not typed that way" % R6_ANSWER,
            )

    def test_the_maps_type_people_consistently_one_way_or_the_other(self):
        """Whatever the maps emit today, they must be uniform about it.

        Holds before and after Agent 3's change, so it is the part of the old
        pinning test that keeps working while R6 is being implemented.
        """
        p = rdflib.URIRef
        seen = set()
        for item in mapoutput.MAPPED:
            graph = item.graph()
            for person in graph.subjects(p(self.RDF_TYPE), p(mapoutput.EX + "Person")):
                types = {str(o) for o in graph.objects(person, p(self.RDF_TYPE))}
                seen.add(frozenset(types & {R6_ANSWER, SULO_OBJECT}))
        self.assertEqual(
            len(seen), 1,
            "the maps type people inconsistently across fixtures: %s" % seen,
        )


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(HAVE_REASONER, SKIP_REASONER)
class R6EvidenceThePersonClassChoiceHasConsequences(unittest.TestCase):
    """The evidence that decided review item R6 - kept live after the answer.

    **R6 is now answered: "a person is a Spatial Object."** These tests are
    what made the question answerable, and they stay because the guard they
    describe has to keep working. In particular
    ``test_bare_object_does_not`` is NOT deleted now that ``SpatialObject``
    is the answer: it is the control that proves the guard does real work
    rather than being decorative. If SULO's class hierarchy ever changed so
    that bare ``Object`` also caught this, that test would fail and the stated
    reason for the R6 answer would need revisiting.

    The history. A claim in DR-603 turned out to be false: it said the
    reasoner catches a person wrongly typed into a ``Feature`` branch, "so R6
    has a safety net while it is open". That is true only for
    ``sulo:SpatialObject``.

    SULO 0.2.12 has ``Feature ⊑ Object`` and ``Feature owl:disjointWith
    SpatialObject``. So:

    ========================================= ==============
    person typed as                           + Quality/Role
    ========================================= ==============
    ``sulo:SpatialObject`` (the old hand graph) INCONSISTENT
    ``sulo:Object``        (what maps emit)     consistent
    ========================================= ==============

    At the time of measuring, the maps emitted ``sulo:Object``, so there was
    no safety net: a map bug that typed a patient as a Role would pass the
    reasoner. The reviewer weighed that and chose ``SpatialObject``, which
    buys the guard back. See CD-6 and DR-605 s3.
    """

    PROBE = """
    @prefix sulo: <https://w3id.org/sulo/> .
    @prefix ex:   <https://w3id.org/ontostart/fhir2sulo/> .
    ex:enc a sulo:Process ; sulo:hasParticipant ex:role .
    ex:role a sulo:Role ; sulo:isFeatureOf ex:p .
    """

    @classmethod
    def setUpClass(cls):
        cls.robot = reasoning.RobotReasoner()
        cls.robot.start()

    @classmethod
    def tearDownClass(cls):
        cls.robot.close()

    def _consistent(self, person_types: str) -> bool:
        return self.robot.check_consistency(
            self.PROBE + "ex:p a %s .\n" % person_types
        ).consistent

    def test_both_candidate_typings_are_fine_on_their_own(self):
        self.assertTrue(self._consistent("sulo:Object"))
        self.assertTrue(self._consistent("sulo:SpatialObject"))

    def test_spatialobject_makes_a_misclassified_person_inconsistent(self):
        self.assertFalse(self._consistent("sulo:SpatialObject , sulo:Quality"))
        self.assertFalse(self._consistent("sulo:SpatialObject , sulo:Role"))

    def test_bare_object_does_not(self):
        """The control. ``Quality ⊑ Feature ⊑ Object``, so there is no clash.

        Deliberately kept after R6 was answered. Without it, the test above
        would show only that *something* is inconsistent, not that the choice
        of ``SpatialObject`` is what makes it so.
        """
        self.assertTrue(self._consistent("sulo:Object , sulo:Quality"))
        self.assertTrue(self._consistent("sulo:Object , sulo:Role"))

    @unittest.skipUnless(HAVE_SHACL, SKIP_SHACL)
    def test_the_shapes_catch_it_even_though_the_reasoner_does_not(self):
        """Not a disaster, but the guard is in SHACL, not in OWL.

        Worth stating precisely: the disjointness shapes reject a node in two
        Feature branches, so a misclassified person is caught before it
        reaches the store. What is *not* available under bare ``sulo:Object``
        is the OWL consistency check, which is the one the acceptance matrix
        row "reasoner checks consistency" leans on.
        """
        from fhir_sulo.validation import shapes_check, strictness

        broken = (
            "<https://w3id.org/ontostart/fhir2sulo/p> "
            "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
            "<https://w3id.org/sulo/Role> .\n"
            "<https://w3id.org/ontostart/fhir2sulo/p> "
            "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
            "<https://w3id.org/sulo/Quality> .\n"
            "<https://w3id.org/ontostart/fhir2sulo/p> "
            "<https://w3id.org/sulo/isFeatureOf> "
            "<https://w3id.org/ontostart/fhir2sulo/q> .\n"
        )
        report = shapes_check.validate_graph(
            broken, strictness.CONCEPT_NOTE_LITERAL
        )
        self.assertFalse(report.conforms)
        self.assertTrue(any("disjoint" in v.message for v in report.violations))


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(HAVE_REASONER, SKIP_REASONER)
@unittest.skipUnless(mapoutput.AVAILABLE, mapoutput.SKIP_NO_FIXTURES)
class R6AppliedToRealMapOutput(unittest.TestCase):
    """Does the R6 answer hold on the graphs the maps actually emit?

    Run ahead of Agent 3's change by retyping people in the real expected
    graphs, so the answer is checked against real output before the maps move
    rather than after. When the maps emit ``SpatialObject`` themselves,
    ``_retyped`` becomes the identity function and these tests keep passing
    unchanged - they assert a property of the graphs, not of the rewrite.

    The axiom to watch, flagged by Agent 1:
    ``SpatialObject ⊑ (hasPart only SpatialObject)``. Nothing may assert
    ``person sulo:hasPart X`` for a non-SpatialObject X.
    """

    @classmethod
    def setUpClass(cls):
        cls.robot = reasoning.RobotReasoner()
        cls.robot.start()

    @classmethod
    def tearDownClass(cls):
        cls.robot.close()

    HAS_PART = "<https://w3id.org/sulo/hasPart>"
    TYPE_NT = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"

    @classmethod
    def _people(cls, triples):
        return {
            line.split(" ", 1)[0]
            for line in triples.splitlines()
            if cls.TYPE_NT in line and (mapoutput.EX + "Person") in line
        }

    @classmethod
    def _retyped(cls, triples):
        """Apply the R6 answer to a graph that may not carry it yet."""
        people = cls._people(triples)
        out = []
        for line in triples.splitlines():
            if (line.split(" ", 1)[0] in people and cls.TYPE_NT in line
                    and "<%s>" % SULO_OBJECT in line):
                line = line.replace("<%s>" % SULO_OBJECT, "<%s>" % R6_ANSWER)
            out.append(line)
        return "\n".join(out), people

    def test_every_emitted_graph_stays_consistent_under_the_r6_answer(self):
        for item in mapoutput.MAPPED:
            with self.subTest(fixture=item.fixture_id):
                triples, people = self._retyped(item.triples())
                self.assertTrue(people, "no person nodes to retype")
                self.assertIn(R6_ANSWER, triples)
                report = self.robot.check_consistency(triples)
                self.assertTrue(report.consistent, report.detail)

    def test_the_guard_is_back_on_real_output(self):
        """A person also typed as a Role is now caught by the reasoner."""
        item = mapoutput.by_id("enc-baseline")
        triples, people = self._retyped(item.triples())
        person = sorted(people)[0]
        broken = triples + "\n%s %s <https://w3id.org/sulo/Role> .\n" % (
            person, self.TYPE_NT)
        self.assertFalse(self.robot.check_consistency(broken).consistent)

    def test_no_emitted_graph_asserts_hasPart_on_a_person(self):
        """``SpatialObject ⊑ (hasPart only SpatialObject)`` - the axiom that
        could bite. It does not: no map asserts parthood on a person."""
        for item in mapoutput.MAPPED:
            with self.subTest(fixture=item.fixture_id):
                triples = item.triples()
                people = self._people(triples)
                offenders = [
                    line for line in triples.splitlines()
                    if line.split(" ", 1)[0] in people and self.HAS_PART in line
                ]
                self.assertEqual(offenders, [], offenders)


@unittest.skipUnless(HAVE_RDFLIB, SKIP_ENV)
@unittest.skipUnless(HAVE_REASONER, SKIP_REASONER)
@unittest.skipUnless(mapoutput.AVAILABLE, mapoutput.SKIP_NO_FIXTURES)
class R11WithR6IsConsistent(unittest.TestCase):
    """Review item R11 changes the graphs, so check it before it lands.

    R11: ``record sulo:refersTo result`` becomes ``record sulo:hasPart
    result``, and each result gains ``sulo:isFeatureOf person``. Two axioms
    could have bitten and neither does:

    * ``InformationObject ⊑ (hasPart only InformationObject)`` - a result is a
      ``Quantity ⊑ InformationObject``, so the new parthood is well-formed;
    * ``Feature owl:disjointWith SpatialObject`` - the result is a Feature and
      the person is a SpatialObject, which are different individuals.
    """

    def test_r11_and_r6_together_are_consistent_on_real_output(self):
        item = mapoutput.by_id("egfr-baseline")
        lines = item.triples().splitlines()
        type_nt = R6AppliedToRealMapOutput.TYPE_NT
        person = next(
            l.split(" ", 1)[0] for l in lines
            if type_nt in l and (mapoutput.EX + "Person") in l
        )
        record = "<%segfr-record-egfr-456>" % mapoutput.EX
        result = "<%segfr-result-egfr-456>" % mapoutput.EX

        out = []
        for line in lines:
            if line.split(" ", 1)[0] == person and type_nt in line \
                    and "<%s>" % SULO_OBJECT in line:
                line = line.replace("<%s>" % SULO_OBJECT, "<%s>" % R6_ANSWER)
            if line.startswith(record) and "<https://w3id.org/sulo/refersTo>" in line \
                    and result in line:
                line = line.replace("<https://w3id.org/sulo/refersTo>",
                                    "<https://w3id.org/sulo/hasPart>")
            out.append(line)
        out.append("%s <https://w3id.org/sulo/isFeatureOf> %s ." % (result, person))
        graph = "\n".join(out)

        self.assertIn("sulo/hasPart> <%segfr-result" % mapoutput.EX, graph)
        self.assertIn("isFeatureOf", graph)

        with reasoning.RobotReasoner() as robot:
            report = robot.check_consistency(graph)
        self.assertTrue(report.consistent, report.detail)


if __name__ == "__main__":
    unittest.main()
