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

EX = "https://w3id.org/ontostart/fhir2sulo/"
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

    def test_the_emitted_value_and_unit_are_the_ones_the_source_bound(self):
        """Target-side content, cross-checked against the source bindings.

        The two are separate artifacts: a map can bind the right things and
        emit the wrong ones.  Asserting only the source bindings is what let a
        cross-wired blood-pressure target schema through review, so the eGFR
        map states the correspondence explicitly.
        """
        src = self.result["_sourceBindings"]
        result = "<%s>" % self.values["result"]
        [emitted] = graph.objects_of(self.triples, result, "<%shasValue>" % SULO)
        self.assertEqual(emitted,
                         '"%s"^^<%s>' % (src["value"]["value"], src["value"]["type"]))
        [unit] = graph.objects_of(self.triples, result, "<%shasPart>" % SULO)
        self.assertEqual(graph.objects_of(self.triples, unit, "<%shasValue>" % SULO),
                         ['"%s"' % src["unitCode"]["value"]])
        [time] = graph.objects_of(self.triples, result, "<%satTime>" % SULO)
        self.assertEqual(graph.objects_of(self.triples, time, "<%shasValue>" % SULO),
                         ['"%s"^^<%s>' % (src["effective"]["value"], src["effective"]["type"])])

    def test_the_result_is_typed_by_the_reviewed_class_for_the_source_code(self):
        """The domain type is the code table's entry for the code the source
        bound -- not a class the schema happens to name."""
        import json
        codes = json.loads((engine.REPO / "policies/code-interpretation.v1.json").read_text())
        entry = next(e for e in codes["entries"]
                     if e["code"] == self.result["_sourceBindings"]["code"]["value"])
        self.assertIn("<%s>" % entry["result_class"],
                      graph.types_of(self.triples, "<%s>" % self.values["result"]))
        [quality] = graph.objects_of(self.triples, "<%s>" % self.values["result"],
                                     "<%srefersTo>" % SULO)
        self.assertIn("<%s>" % entry["quality_class"], graph.types_of(self.triples, quality))

    def test_exactly_one_quality(self):
        result = "<%s>" % self.values["result"]
        refs = graph.objects_of(self.triples, result, "<%srefersTo>" % SULO)
        self.assertEqual(len(refs), 1, refs)
        self.assertEqual(refs, ["<%s>" % self.values["quality"]])

    def test_the_person_is_reached_only_by_sulo_feature_relations(self):
        """Concept note section 2: no hasPatient, no resource-specific shortcut.

        R11 (2026-09-30) added a second, direct arc: the result is itself a
        feature of the individual. So the person now has TWO incoming arcs --
        from the quality and from the result -- and the test says so rather
        than asserting a single path that is no longer the contract. What
        section 2 forbids is a shortcut PREDICATE, and both of these are
        sulo:isFeatureOf.
        """
        person = "<%s>" % self.values["person"]
        quality = "<%s>" % self.values["quality"]
        result = "<%s>" % self.values["result"]
        is_feature_of = "<%sisFeatureOf>" % SULO

        incoming = sorted((s, p) for s, p, o in self.triples if o == person)
        self.assertEqual(incoming, sorted([(quality, is_feature_of),
                                           (result, is_feature_of)]), incoming)

        # and the inverse is stated exactly once, as concept note section 4 does
        self.assertEqual(
            graph.objects_of(self.triples, person, "<%shasFeature>" % SULO), [quality])

    def test_no_shortcut_predicate_reaches_the_person(self):
        allowed = {RDF_TYPE, "<http://www.w3.org/ns/prov#wasDerivedFrom>"} | {
            "<%s%s>" % (SULO, p) for p in
            ("hasValue", "hasPart", "refersTo", "atTime", "isFeatureOf", "hasFeature")}
        used = graph.predicates(self.triples)
        self.assertEqual(used - allowed, set(), sorted(used - allowed))
        for p in used:
            self.assertNotIn("hasPatient", p)
            self.assertNotIn("hasSubject", p)

    def test_the_quality_is_a_sulo_quality_not_a_bare_feature(self):
        """R4 default (option A).  Bare sulo:Feature would leave the individual
        unpartitioned across a four-way disjoint union (DR-002 axiom 6)."""
        quality = "<%s>" % self.values["quality"]
        self.assertIn("<%sQuality>" % SULO, graph.types_of(self.triples, quality))
        self.assertNotIn("<%sFeature>" % SULO, graph.types_of(self.triples, quality))

    # -- no orphan nodes ----------------------------------------------------

    def test_the_record_has_the_result_as_a_part(self):
        """R11, answered 2026-09-30. The record HAS the result -- "this then
        captures where the results are located (e.g. the record)" -- rather
        than referring to it."""
        record = "<%s>" % self.values["record"]
        self.assertEqual(graph.objects_of(self.triples, record, "<%shasPart>" % SULO),
                         ["<%s>" % self.values["result"]])
        self.assertEqual(graph.objects_of(self.triples, record, "<%srefersTo>" % SULO), [],
                         "R11 replaced record->result refersTo with hasPart")

    def test_the_result_is_a_feature_of_the_person(self):
        """R11: "the results are information about the individual - they are
        features of the individual". This is also R5's FIRST row answered as
        option A; R5's second row (a time unit) stays unset and unemitted."""
        self.assertEqual(
            graph.objects_of(self.triples, "<%s>" % self.values["result"],
                             "<%sisFeatureOf>" % SULO),
            ["<%s>" % self.values["person"]])

    def test_no_time_instant_carries_a_unit(self):
        """R5's SECOND row is still open and must stay unset."""
        for node in graph.subjects_of_type(self.triples, SULO + "TimeInstant"):
            with self.subTest(node=node):
                self.assertEqual(
                    graph.objects_of(self.triples, node, "<%shasPart>" % SULO), [])

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


class CorrectionReplacesTheSameNodes(engine.EngineTestCase):
    """The map-side half of Gate 4's correction row, on Agent 2's v1/v2/v3.

    Concept note section 7: "A correction computes a replacement graph and
    removes stale derived assertions; source versions remain traceable."
    That only works if a new version keys the SAME node IRIs -- otherwise the
    stale triples have nothing to be replaced on, and a store ends up holding
    both values. `MapContract.node_key_rules` keys by resource id and not by
    version precisely for this, and until the version-lineage fixtures landed
    it was a claim in a manifest with nothing exercising it.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.v1 = egfr_case.run("egfr-baseline")       # egfr-456 @ v1, 55.0
        cls.v2 = egfr_case.run("egfr-corrected")      # egfr-456 @ v2, 58.5

    def test_both_versions_are_the_same_resource(self):
        self.assertEqual(egfr_case.focus_iri("egfr-baseline"),
                         egfr_case.focus_iri("egfr-corrected"))

    def test_the_result_and_record_nodes_keep_their_iris(self):
        for node in ("result", "record", "timeInstant"):
            with self.subTest(node=node):
                self.assertEqual(self.v1["_hostValues"][node],
                                 self.v2["_hostValues"][node])

    def test_the_person_and_the_unit_are_unchanged(self):
        for node in ("person", "unitIri"):
            with self.subTest(node=node):
                self.assertEqual(self.v1["_hostValues"][node],
                                 self.v2["_hostValues"][node])

    def test_the_value_moves_and_the_old_one_is_gone(self):
        result = "<%s>" % self.v1["_hostValues"]["result"]
        decimal = "^^<http://www.w3.org/2001/XMLSchema#decimal>"
        self.assertEqual(
            graph.objects_of(graph.parse(self.v1["nquads"]), result, "<%shasValue>" % SULO),
            ['"55.0"' + decimal])
        self.assertEqual(
            graph.objects_of(graph.parse(self.v2["nquads"]), result, "<%shasValue>" % SULO),
            ['"58.5"' + decimal])

    def test_the_lineage_names_the_version_that_produced_each_graph(self):
        prov = "<http://www.w3.org/ns/prov#wasDerivedFrom>"
        base = "<https://fhir.example/Observation/egfr-456/_history/%s>"
        for version, result in (("1", self.v1), ("2", self.v2)):
            with self.subTest(version=version):
                triples = graph.parse(result["nquads"])
                self.assertEqual(
                    graph.objects_of(triples, "<%s>" % result["_hostValues"]["result"], prov),
                    [base % version])

    def test_a_retraction_produces_no_clinical_assertion(self):
        """Concept note section 2: `entered-in-error` suppresses clinical
        assertions from that resource; it does not erase the source record."""
        v3 = egfr_case.run("egfr-retracted")
        self.assertFalse(v3["validation"]["ok"])
        self.assertEqual(v3["nquads"], "")

    def test_the_quality_iri_moves_with_the_version_under_the_current_policy(self):
        """Recorded, not asserted as desirable: R2 is unanswered, and under
        `per-observation` the quality is keyed by version, so a correction
        mints a new quality node while the quantity keeps its IRI. Under
        `persistent-per-person-code` it would not. Whoever answers R2 should
        see this consequence rather than discover it."""
        self.assertNotEqual(self.v1["_hostValues"]["quality"],
                            self.v2["_hostValues"]["quality"])
        persistent_v1 = egfr_case.run("egfr-baseline",
                                      quality_mode="persistent-per-person-code")
        persistent_v2 = egfr_case.run("egfr-corrected",
                                      quality_mode="persistent-per-person-code")
        self.assertEqual(persistent_v1["_hostValues"]["quality"],
                         persistent_v2["_hostValues"]["quality"])
