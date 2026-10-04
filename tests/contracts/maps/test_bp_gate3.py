"""Gate 3 acceptance conditions for the blood-pressure map.

From the brief:

    the BP tuple multiset is exactly {(bp-1,120,80),(bp-2,105,70)} and survives
    every permutation fixture; the graph contains **no** hasPatient; the
    inverse map recovers all shared bindings per scope.

THE ACCEPTANCE CONDITION IS ON THE EMITTED TARGET GRAPH, not on the source
bindings.  `BPTargetGraphMultiset` recovers each tuple by walking the graph --
panel record -> sulo:refersTo -> quantity -> sulo:hasValue, with the slot
decided by the class of the quality the quantity refersTo -- and reads no
source binding and no host value at all.  That is what reaches a clinical
store, so that is what the gate is asserted on.

This is a repair.  The first version of this file asserted the multiset only
over `bp_case.binding_tree`, which is built from the *source* shape's
bindings, so a target schema that bound the right things and emitted the wrong
ones passed.  The integration lead's review caught it with a one-token
injection -- the diastolic node emitting `v:sysValue` -- which produced
`bp-diastolic-result-bp-1 sulo:hasValue "120"` and left every multiset test
green.  `BPTargetGraphMultiset.test_the_wrong_half_was_asserted_before`
documents the gap; the injection now fails five tests in this file.

`BPSourceBindingMultiset` keeps the source-side comparison against Agent 2's
`expected-bindings.json` through `BindingNode.tuples_for_scope`, the call the
frozen interface demonstrates.  It is corroboration, not the gate: it catches
faults on the extraction half, such as swapped LOINC component codes, which
the target-side check alone would attribute to the wrong schema.

Both compare **sorted lists, not sets** -- `bp-duplicate-values` has two panels
with identical values and must stay two tuples.

`BPCrossJoinIsDetectable` at the bottom is the fault injection.  A Gate 3 suite
that passes on cross-joined bindings, or on a cross-wired target schema, does
not count.
"""

from __future__ import annotations

import copy
import json
import unittest

from . import bp_case
from ._engine import engine, graph, mapjob
from ._engine.graph import RDF_TYPE, SULO

FIXTURES = ["bp-two-panels", "bp-component-omitted", "bp-reordered-serialisation",
            "bp-duplicate-values", "bp-other-patient"]
TUPLE_VARS = ["panel", "sys", "dia"]
FULL_VARS = ["panel", "subjectRef", "effective", "sys", "dia", "sysUnit", "diaUnit"]

_CACHE = {}


def run_fixture(fixture_id, variant=None):
    key = (fixture_id, variant)
    if key not in _CACHE:
        rdf, ids = bp_case.resources(fixture_id, variant)
        _CACHE[key] = {o: bp_case.run(fixture_id, o, rdf=rdf) for o in ids}
    return _CACHE[key]


def expected(fixture_id, variables):
    doc = json.loads((bp_case.fixture_dir(fixture_id) / "expected-bindings.json").read_text())
    for a in doc["assertions"]["scope_tuples"]:
        if a["scope"] == "panel" and a["variables"] == variables:
            return ([tuple(t) for t in a["expected_multiset"]],
                    [tuple(t) for t in a.get("must_not_contain", ())])
    raise AssertionError("no panel assertion for %s in %s" % (variables, fixture_id))


def vocabulary():
    return mapjob.vocabulary(mapjob.load_manifest("bp"))


def target_tuples(fixture_id, variant=None):
    """The (panel, sys, dia) multiset read out of the EMITTED target graph."""
    results = run_fixture(fixture_id, variant)
    nquads = "\n".join(r["nquads"] for r in results.values())
    return graph.bp_panel_tuples(nquads, vocabulary())


class BPTargetGraphMultiset(engine.EngineTestCase):
    """Concept note section 5, asserted on the graph the map actually emits."""

    def test_the_concept_note_multiset_is_exactly_right(self):
        self.assertEqual(target_tuples("bp-two-panels"),
                         [("bp-1", "120", "80"), ("bp-2", "105", "70")])

    def test_every_fixture_matches_agent_2s_declared_multiset(self):
        for fixture_id in FIXTURES:
            with self.subTest(fixture=fixture_id):
                want, forbidden = expected(fixture_id, TUPLE_VARS)
                got = target_tuples(fixture_id)
                # sorted LISTS, not sets: bp-duplicate-values has two panels
                # whose tuples coincide and must stay two tuples.
                self.assertEqual(got, sorted(want), fixture_id)
                for bad in forbidden:
                    self.assertNotIn(bad, got, (fixture_id, bad))

    def test_duplicate_values_stay_two_tuples(self):
        got = [t[1:] for t in target_tuples("bp-duplicate-values")]
        self.assertEqual(sorted(got), [("120", "80"), ("120", "80")])
        self.assertEqual(len(set(got)), 1,
                         "the two tuples are identical -- a set comparison would "
                         "silently accept one of them going missing")

    def test_the_multiset_survives_both_rdf_variants(self):
        """A different line order, and a genuinely different graph whose
        fhir:index values move.  Components are selected by LOINC code, so
        neither changes the emitted graph."""
        base = target_tuples("bp-reordered-serialisation")
        for variant in ("same_graph_different_serialisation",
                        "different_graph_same_clinical_content"):
            with self.subTest(variant=variant):
                got = target_tuples("bp-reordered-serialisation", variant)
                self.assertEqual(got, base)
                self.assertEqual(got, [("bp-1", "120", "80"), ("bp-2", "105", "70")])

    def test_an_omitted_component_leaves_a_hole_not_a_borrowed_value(self):
        self.assertEqual(target_tuples("bp-component-omitted"),
                         [("bp-1", "120", ""), ("bp-2", "105", "70")])
        # and no diastolic node exists at all for bp-1
        triples = graph.parse(run_fixture("bp-component-omitted")["bp-1"]["nquads"])
        self.assertEqual(
            graph.subjects_of_type(triples, vocabulary()["diaResultClass"]), [])

    def test_the_other_patients_panel_keeps_its_own_values(self):
        self.assertEqual(target_tuples("bp-other-patient"),
                         [("bp-1", "120", "80"), ("bp-5", "200", "110")])

    def test_the_wrong_half_was_asserted_before(self):
        """A regression guard on the repair itself.

        The source bindings and the emitted graph are two different artifacts,
        and a test that reads only the first cannot see a cross-wired target
        schema.  This asserts they are compared independently: the extractor
        used here touches no source binding, so if someone reintroduces the
        shortcut this test's imports stop making sense.
        """
        results = run_fixture("bp-two-panels")
        nquads = "\n".join(r["nquads"] for r in results.values())
        from_graph = graph.bp_panel_tuples(nquads, vocabulary())
        from_source = sorted(bp_case.binding_tree("bp-two-panels", results)
                             .tuples_for_scope("panel", TUPLE_VARS))
        self.assertEqual(from_graph, from_source,
                         "the emitted graph and the source bindings disagree; the map "
                         "bound one thing and emitted another")


class BPSourceBindingMultiset(engine.EngineTestCase):
    """Corroboration on the extraction half -- NOT the acceptance condition.

    Catches faults the target-side check would blame on the wrong schema, such
    as the two component LOINC codes being swapped in the source shape.
    """

    def test_every_fixture_matches_agent_2s_declared_bindings(self):
        for fixture_id in FIXTURES:
            with self.subTest(fixture=fixture_id):
                tree = bp_case.binding_tree(fixture_id, run_fixture(fixture_id))
                for variables in (TUPLE_VARS, FULL_VARS):
                    want, forbidden = expected(fixture_id, variables)
                    got = sorted(tree.tuples_for_scope("panel", variables))
                    self.assertEqual(got, sorted(want), (fixture_id, variables))
                    for bad in forbidden:
                        self.assertNotIn(bad, got, (fixture_id, bad))

    def test_the_components_reversed_variant_really_is_a_different_graph(self):
        """Otherwise the permutation test would be proving nothing."""
        d = bp_case.fixture_dir("bp-reordered-serialisation")
        a = set((d / "canonical.nt").read_text().splitlines())
        b = set((d / "canonical-components-reversed.nt").read_text().splitlines())
        self.assertNotEqual(a, b)
        c = set((d / "canonical-reordered.nt").read_text().splitlines())
        self.assertEqual(a, c, "canonical-reordered.nt should be the same triple set")

    def test_two_panels_for_two_people_do_not_share_a_person(self):
        results = run_fixture("bp-other-patient")
        people = {o: r["_hostValues"]["person"] for o, r in results.items()}
        self.assertEqual(len(set(people.values())), 2, people)


class BPGraphShape(engine.EngineTestCase):
    def setUp(self):
        self.results = run_fixture("bp-two-panels")
        self.triples = graph.parse("\n".join(r["nquads"] for r in self.results.values()))

    def test_the_runs_were_clean(self):
        for obs, r in self.results.items():
            with self.subTest(resource=obs):
                engine.require_clean(r)
                for p in r["passes"]:
                    self.assertEqual(p["report"]["alternatives"], 1, (obs, p["name"]))

    def test_the_graph_contains_no_hasPatient_and_no_shortcut_predicate(self):
        """Concept note section 2, asserted on the emitted graph, not the schema."""
        allowed = {
            RDF_TYPE,
            "<http://www.w3.org/ns/prov#wasDerivedFrom>",
        } | {"<%s%s>" % (SULO, p) for p in
             ("hasValue", "hasPart", "refersTo", "atTime", "isFeatureOf", "hasFeature")}
        used = graph.predicates(self.triples)
        self.assertEqual(used - allowed, set(), sorted(used - allowed))
        for p in used:
            self.assertNotIn("hasPatient", p)
            self.assertNotIn("hasSubject", p)

    def test_each_panel_has_exactly_its_own_two_quantities_as_parts(self):
        """R11: the record HAS the results as PARTS -- where they are located
        -- rather than referring to them."""
        for obs, r in self.results.items():
            with self.subTest(resource=obs):
                v = r["_hostValues"]
                triples = graph.parse(r["nquads"])
                panel = "<%s>" % v["panelRecord"]
                self.assertEqual(
                    graph.objects_of(triples, panel, "<%shasPart>" % SULO),
                    sorted(["<%s>" % v["sysResult"], "<%s>" % v["diaResult"]]))
                self.assertEqual(
                    graph.objects_of(triples, panel, "<%srefersTo>" % SULO), [],
                    "R11 replaced record->result refersTo with hasPart")

    def test_each_quantity_is_a_feature_of_the_person(self):
        """R11: \"the results are information about the individual - they are
        features of the individual\". Also R5's first row, answered as A."""
        for obs, r in self.results.items():
            v = r["_hostValues"]
            triples = graph.parse(r["nquads"])
            for node in ("sysResult", "diaResult"):
                with self.subTest(resource=obs, node=node):
                    self.assertEqual(
                        graph.objects_of(triples, "<%s>" % v[node],
                                         "<%sisFeatureOf>" % SULO),
                        ["<%s>" % v["person"]])

    def test_each_quantity_has_one_value_one_unit_and_one_quality(self):
        """Arity AND content.  Counting arcs alone would accept a diastolic
        node carrying the systolic value, which is the defect this suite was
        repaired for."""
        want = {"bp-1": {"sysResult": "120", "diaResult": "80"},
                "bp-2": {"sysResult": "105", "diaResult": "70"}}
        for obs, r in self.results.items():
            v = r["_hostValues"]
            triples = graph.parse(r["nquads"])
            for node in ("sysResult", "diaResult"):
                with self.subTest(resource=obs, node=node):
                    iri = "<%s>" % v[node]
                    values = graph.objects_of(triples, iri, "<%shasValue>" % SULO)
                    self.assertEqual(values, ['"%s"^^<http://www.w3.org/2001/XMLSchema#decimal>'
                                              % want[obs][node]])
                    self.assertEqual(graph.objects_of(triples, iri, "<%shasPart>" % SULO),
                                     ["<%s>" % v["unitIri"]])
                    quality = {"sysResult": "sysQuality", "diaResult": "diaQuality"}[node]
                    self.assertEqual(graph.objects_of(triples, iri, "<%srefersTo>" % SULO),
                                     ["<%s>" % v[quality]])
                    self.assertEqual(graph.objects_of(triples, iri,
                                                      "<%sisFeatureOf>" % SULO),
                                     ["<%s>" % v["person"]])

    def test_systolic_and_diastolic_qualities_are_distinct(self):
        for obs, r in self.results.items():
            with self.subTest(resource=obs):
                v = r["_hostValues"]
                self.assertNotEqual(v["sysQuality"], v["diaQuality"])

    def test_no_orphan_nodes(self):
        for obs, r in self.results.items():
            with self.subTest(resource=obs):
                triples = graph.parse(r["nquads"])
                self.assertEqual(graph.sources(triples),
                                 ["<%s>" % r["_hostValues"]["panelRecord"]])

    def test_no_blank_nodes(self):
        self.assertEqual(graph.blank_nodes(self.triples), set())

    def test_the_two_panels_share_the_person_and_the_unit_but_nothing_else(self):
        a, b = (graph.parse(self.results[o]["nquads"]) for o in ("bp-1", "bp-2"))
        shared = graph.subjects(a) & graph.subjects(b)
        person = "<%s>" % self.results["bp-1"]["_hostValues"]["person"]
        unit = "<%s>" % self.results["bp-1"]["_hostValues"]["unitIri"]
        self.assertEqual(shared, {person, unit},
                         "under the per-observation quality policy (R2) nothing else "
                         "may be shared between two panels")

    def test_the_panel_code_does_not_type_the_panel_record(self):
        """Review item R9 is unanswered; option B is in force."""
        for obs, r in self.results.items():
            with self.subTest(resource=obs):
                triples = graph.parse(r["nquads"])
                types = graph.types_of(triples, "<%s>" % r["_hostValues"]["panelRecord"])
                self.assertEqual(sorted(types), sorted([
                    "<%sInformationObject>" % SULO,
                    "<https://w3id.org/ontostart/fhir2sulo/ObservationRecord>"]))

    def test_hasValue_is_functional_everywhere(self):
        for subject in graph.subjects(self.triples):
            self.assertLessEqual(
                len(graph.objects_of(self.triples, subject, "<%shasValue>" % SULO)), 1, subject)


class BPCrossJoinIsDetectable(engine.EngineTestCase):
    """Fault injection: the Gate 3 check must fail on cross-joined bindings.

    The integration lead fault-injects every headline claim before merging.
    These tests inject the faults themselves, so the suite's ability to catch
    them is evidence rather than an assumption.
    """

    def test_a_cross_joined_binding_tree_fails_the_source_side_check(self):
        """Swap the two panels' diastolic values -- the exact cross-join the
        concept note names -- and the source-side check must reject it too."""
        from fhir_sulo.contracts import BindingNode

        results = copy.deepcopy(run_fixture("bp-two-panels"))
        a = results["bp-1"]["_sourceBindings"]["diaValue"]
        b = results["bp-2"]["_sourceBindings"]["diaValue"]
        results["bp-1"]["_sourceBindings"]["diaValue"] = b
        results["bp-2"]["_sourceBindings"]["diaValue"] = a

        tree = bp_case.binding_tree("bp-two-panels", results)
        got = sorted(tree.tuples_for_scope("panel", TUPLE_VARS))
        want, forbidden = expected("bp-two-panels", TUPLE_VARS)

        self.assertNotEqual(got, sorted(want),
                            "the multiset comparison did not notice a cross-join")
        self.assertIn(("bp-1", "120", "70"), got)
        self.assertIn(("bp-1", "120", "70"), forbidden)

    def test_a_membership_check_would_not_have_caught_it(self):
        """Why the comparison is a multiset and not 'every value appears'."""
        correct = [("bp-1", "120", "80"), ("bp-2", "105", "70")]
        crossed = [("bp-1", "120", "70"), ("bp-2", "105", "80")]
        values = lambda ts: sorted(v for t in ts for v in t)
        self.assertEqual(values(correct), values(crossed))
        self.assertNotEqual(sorted(correct), sorted(crossed))

    def test_a_set_comparison_would_not_have_caught_a_lost_duplicate(self):
        """Why sorted lists and not sets: bp-duplicate-values."""
        two = [("bp-3", "120", "80"), ("bp-4", "120", "80")]
        one = [("bp-3", "120", "80")]
        self.assertEqual(set(t[1:] for t in two), set(t[1:] for t in one))
        self.assertNotEqual(sorted(t[1:] for t in two), sorted(t[1:] for t in one))

    def test_a_wrong_value_reaching_the_engine_fails_the_TARGET_graph_check(self):
        """The repaired check, exercised end to end.

        Feeds the materializer a mutated binding tree through the harness's
        override hook -- which exists only for this test -- and asserts the
        target-graph extractor reports the wrong tuple and stops matching
        Agent 2's declared multiset.  Before the repair this only asserted the
        graph had *changed*, which a source-side multiset test could not see.
        """
        results = run_fixture("bp-two-panels")
        clean = results["bp-1"]
        mutated = copy.deepcopy(clean["bindings"])
        mutated["https://w3id.org/fhir-sulo/map/bp/var#diaValue"] = {
            "value": "70", "type": "http://www.w3.org/2001/XMLSchema#decimal"}
        dirty = bp_case.run("bp-two-panels", "bp-1", bindings_override=mutated)
        engine.require_clean(dirty)

        triples = graph.parse(dirty["nquads"])
        self.assertEqual(
            graph.objects_of(triples, "<%s>" % clean["_hostValues"]["diaResult"],
                             "<%shasValue>" % SULO),
            ['"70"^^<http://www.w3.org/2001/XMLSchema#decimal>'])

        got = graph.bp_panel_tuples(dirty["nquads"], vocabulary())
        self.assertEqual(got, [("bp-1", "120", "70")])
        want, forbidden = expected("bp-two-panels", TUPLE_VARS)
        self.assertNotEqual(got, [t for t in sorted(want) if t[0] == "bp-1"])
        self.assertIn(("bp-1", "120", "70"), forbidden)

    def test_a_cross_wired_target_node_is_caught_by_the_graph_extractor(self):
        """The exact defect the integration lead's review found.

        A target schema whose diastolic node emits `v:sysValue` produces
        `bp-diastolic-result-bp-1 sulo:hasValue "120"`.  Simulated here by
        rewriting the emitted graph, so the assertion is exercised without
        editing a committed schema; the real schema injection is in
        DR-201 and was re-run by hand.
        """
        results = run_fixture("bp-two-panels")
        v = results["bp-1"]["_hostValues"]
        cross_wired = results["bp-1"]["nquads"].replace(
            '<%s> <%shasValue> "80"^^' % (v["diaResult"], SULO),
            '<%s> <%shasValue> "120"^^' % (v["diaResult"], SULO))
        self.assertNotEqual(cross_wired, results["bp-1"]["nquads"], "the rewrite did nothing")
        self.assertEqual(graph.bp_panel_tuples(cross_wired, vocabulary()),
                         [("bp-1", "120", "120")])

    def test_a_quantity_pointing_at_the_wrong_quality_raises(self):
        """Not merely a wrong tuple: the extractor refuses to assign a slot
        when a quantity's own domain type and its quality disagree."""
        results = run_fixture("bp-two-panels")
        v = results["bp-1"]["_hostValues"]
        swapped = results["bp-1"]["nquads"].replace(
            "<%s> <%srefersTo> <%s>" % (v["diaResult"], SULO, v["diaQuality"]),
            "<%s> <%srefersTo> <%s>" % (v["diaResult"], SULO, v["sysQuality"]))
        self.assertNotEqual(swapped, results["bp-1"]["nquads"])
        with self.assertRaises(AssertionError):
            graph.bp_panel_tuples(swapped, vocabulary())


if __name__ == "__main__":
    unittest.main()
