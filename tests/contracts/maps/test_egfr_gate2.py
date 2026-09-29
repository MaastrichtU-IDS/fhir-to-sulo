"""Gate 2 acceptance conditions for the eGFR map.

From the brief:

    the normal eGFR fixture yields *exactly one* value/unit/quality/patient
    association; no orphan quantity or unit nodes; inverse validation recovers
    the shared pivot variables.

These run the pinned engine in Docker.  They do not read
``fixtures/expected/``: a wrong graph regenerated there still fails here.
"""

from __future__ import annotations

import json
import unittest

from . import egfr_case
from ._engine import engine, graph
from ._engine.graph import RDF_TYPE, SULO

EX = "https://example.org/fhir-sulo/"
FIXTURE = "egfr-baseline"


class EGFRGate2(engine.EngineTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.result = egfr_case.run(FIXTURE)
        cls.triples = graph.parse(cls.result["nquads"])
        cls.values = cls.result["_hostValues"]

    # -- the run itself was clean ------------------------------------------

    def test_the_map_ran_with_no_silent_failure_mode(self):
        """Every mode DR-301 documents as failing silently is checked explicitly."""
        engine.require_clean(self.result)
        for p in self.result["passes"]:
            self.assertEqual(p["report"]["alternatives"], 1,
                             "pass %r had %s materializations; more than one means the "
                             "schema does not determine the graph"
                             % (p["name"], p["report"]["alternatives"]))

    # -- exactly one value / unit / quality / patient association ----------

    def test_exactly_one_value(self):
        result = "<%s>" % self.values["result"]
        self.assertEqual(
            graph.objects_of(self.triples, result, "<%shasValue>" % SULO),
            ['"55.0"^^<http://www.w3.org/2001/XMLSchema#decimal>'],
        )

    def test_the_decimal_precision_survives(self):
        """DR-102: '55' is a different tuple from '55.0'."""
        result = "<%s>" % self.values["result"]
        [value] = graph.objects_of(self.triples, result, "<%shasValue>" % SULO)
        self.assertIn('"55.0"', value)
        self.assertNotIn('"55"', value)

    def test_exactly_one_unit(self):
        result = "<%s>" % self.values["result"]
        parts = graph.objects_of(self.triples, result, "<%shasPart>" % SULO)
        self.assertEqual(len(parts), 1, parts)
        [unit] = parts
        self.assertEqual(graph.types_of(self.triples, unit), ["<%sUnit>" % SULO])
        self.assertEqual(
            graph.objects_of(self.triples, unit, "<%shasValue>" % SULO),
            ['"mL/min/{1.73_m2}"'],
        )

    def test_exactly_one_quality(self):
        result = "<%s>" % self.values["result"]
        refs = graph.objects_of(self.triples, result, "<%srefersTo>" % SULO)
        self.assertEqual(len(refs), 1, refs)
        self.assertEqual(refs, ["<%s>" % self.values["quality"]])

    def test_exactly_one_patient_association_and_it_goes_through_the_quality(self):
        """Concept note section 2: no hasPatient, no resource-specific shortcut.

        The only path from the result to the person is
        ``result refersTo quality isFeatureOf person``.
        """
        person = "<%s>" % self.values["person"]
        result = "<%s>" % self.values["result"]
        quality = "<%s>" % self.values["quality"]

        # the person is reached exactly once, and only from the quality
        incoming = sorted((s, p) for s, p, o in self.triples if o == person)
        self.assertEqual(incoming, [(quality, "<%sisFeatureOf>" % SULO)], incoming)

        # nothing on the result node points at the person
        self.assertNotIn(person, [o for p, o in graph.po(self.triples, result)])

        # and the inverse is stated exactly once, as the concept note's graph does
        self.assertEqual(
            graph.objects_of(self.triples, person, "<%shasFeature>" % SULO), [quality])

    def test_the_quality_is_a_sulo_quality_not_a_bare_feature(self):
        """R4 default (option A).  Bare sulo:Feature would leave the individual
        unpartitioned across a four-way disjoint union (DR-002 axiom 6)."""
        quality = "<%s>" % self.values["quality"]
        self.assertIn("<%sQuality>" % SULO, graph.types_of(self.triples, quality))
        self.assertNotIn("<%sFeature>" % SULO, graph.types_of(self.triples, quality))

    # -- no orphan nodes ----------------------------------------------------

    def test_no_orphan_quantity_or_unit_nodes(self):
        """Exactly one node has no incoming edge, and it is the record node.

        Every other node -- the quantity, the unit, the quality, the person,
        the time instant -- is reachable, so none of them dangles.
        """
        self.assertEqual(graph.sources(self.triples), ["<%s>" % self.values["record"]])

    def test_no_blank_nodes(self):
        """Every target node is an IRI whose key rule is declared in the
        MapContract, so a correction can replace it (concept note section 7)."""
        self.assertEqual(graph.blank_nodes(self.triples), set())

    def test_every_typed_node_is_reachable_from_the_record(self):
        record = "<%s>" % self.values["record"]
        seen, frontier = {record}, [record]
        while frontier:
            node = frontier.pop()
            for _, o in graph.po(self.triples, node):
                if o.startswith("<") and o not in seen:
                    seen.add(o)
                    frontier.append(o)
        unreachable = graph.subjects(self.triples) - seen
        self.assertEqual(unreachable, set(), unreachable)

    # -- the SULO 0.2.12 axioms --------------------------------------------

    def test_hasValue_is_functional_so_no_node_carries_two(self):
        """DR-002 axiom 1: sulo:hasValue is an owl:FunctionalProperty."""
        for subject in graph.subjects(self.triples):
            vals = graph.objects_of(self.triples, subject, "<%shasValue>" % SULO)
            self.assertLessEqual(len(vals), 1, (subject, vals))

    def test_every_quantity_has_a_unit_part(self):
        """DR-002 axiom 2: sulo:Quantity subClassOf (sulo:hasPart some sulo:Unit)."""
        for q in graph.subjects_of_type(self.triples, SULO + "Quantity"):
            parts = graph.objects_of(self.triples, q, "<%shasPart>" % SULO)
            self.assertTrue(parts, q)
            self.assertTrue(
                any("<%sUnit>" % SULO in graph.types_of(self.triples, part) for part in parts),
                (q, parts))

    def test_the_record_and_the_quantity_are_distinct_individuals(self):
        """Concept note section 1 and 2: two layers, never identified."""
        self.assertNotEqual(self.values["record"], self.values["result"])
        self.assertNotIn("sameAs", self.result["nquads"])

    def test_the_source_lineage_is_versioned(self):
        prov = "<http://www.w3.org/ns/prov#wasDerivedFrom>"
        for node in ("result", "record"):
            self.assertEqual(
                graph.objects_of(self.triples, "<%s>" % self.values[node], prov),
                ["<https://fhir.example/Observation/egfr-456/_history/1>"])

    def test_the_time_is_effective_not_issued_and_keeps_its_datatype(self):
        t = "<%s>" % self.values["timeInstant"]
        self.assertEqual(graph.types_of(self.triples, t), ["<%sTimeInstant>" % SULO])
        self.assertEqual(
            graph.objects_of(self.triples, t, "<%shasValue>" % SULO),
            ['"2026-09-02T14:00:00Z"^^<http://www.w3.org/2001/XMLSchema#dateTime>'])

    # -- the vocabulary indirection ----------------------------------------

    def test_the_domain_vocabulary_can_be_swapped_without_touching_a_schema(self):
        """Review item R1.  Same fixture, a different vocabulary, no schema edit.

        Only the domain typing changes shape.  Every SULO term, every literal
        and every non-quality node IRI is byte-identical, so the vocabulary is
        genuinely behind one indirection point.

        One IRI *does* move, and the test states it rather than hiding it:
        the quality IRI, because ``quality_class_iri`` is one of the quality
        key inputs in ``policies/identity-policy.v1.json``.  Consequence for
        sequencing: answering R1 re-keys every quality node, exactly as
        answering R2 does.
        """
        other = egfr_case.run(FIXTURE, vocabulary_override={
            "resultClass": "https://other.example/vocab/EGFRResult",
            "qualityClass": "https://other.example/vocab/RenalFiltrationQuality",
        })
        engine.require_clean(other)
        swapped = graph.parse(other["nquads"])

        result = "<%s>" % self.values["result"]
        self.assertIn("<https://other.example/vocab/EGFRResult>",
                      graph.types_of(swapped, result))
        self.assertIn("<%sQuantity>" % SULO, graph.types_of(swapped, result))

        # the quality IRI moves; nothing else does
        self.assertNotEqual(self.values["quality"], other["_hostValues"]["quality"])
        for key in ("person", "result", "record", "timeInstant", "unitIri"):
            self.assertEqual(self.values[key], other["_hostValues"][key], key)

        def normalise(ts, quality):
            out = []
            for s, p, o in ts:
                if p == RDF_TYPE and ("EGFRResult" in o or "RenalFiltrationQuality" in o):
                    o = "<DOMAIN-CLASS>"
                s = "<QUALITY>" if s == "<%s>" % quality else s
                o = "<QUALITY>" if o == "<%s>" % quality else o
                out.append((s, p, o))
            return sorted(out)

        self.assertEqual(normalise(self.triples, self.values["quality"]),
                         normalise(swapped, other["_hostValues"]["quality"]))


class EGFRQualityIdentityIsBlocked(engine.EngineTestCase):
    """Review item R2 is unanswered, and the shipped default must stop the run."""

    def test_the_map_cannot_run_under_the_shipped_quality_policy(self):
        from fhir_sulo.identity import QualityIdentityPolicyUnset

        with self.assertRaises(QualityIdentityPolicyUnset):
            egfr_case.run(FIXTURE, quality_mode=None)

    def test_the_two_quality_modes_give_different_quality_iris(self):
        """DR-401: answering R2 moves every quality IRI. Stated as a test so the
        migration cannot be mistaken for a configuration change."""
        a = egfr_case.run(FIXTURE, quality_mode="per-observation")
        b = egfr_case.run(FIXTURE, quality_mode="persistent-per-person-code")
        self.assertNotEqual(a["_hostValues"]["quality"], b["_hostValues"]["quality"])
        # and nothing else moves
        self.assertEqual(a["_hostValues"]["person"], b["_hostValues"]["person"])
        self.assertEqual(a["_hostValues"]["result"], b["_hostValues"]["result"])
        self.assertEqual(a["_hostValues"]["unitIri"], b["_hostValues"]["unitIri"])


if __name__ == "__main__":
    unittest.main()
