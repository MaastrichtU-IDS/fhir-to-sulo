"""Gate 3 acceptance conditions for the blood-pressure map.

From the brief:

    the BP tuple multiset is exactly {(bp-1,120,80),(bp-2,105,70)} and survives
    every permutation fixture; the graph contains **no** hasPatient; the
    inverse map recovers all shared bindings per scope.

The tuples are read out of the engine's own binding trees through
``BindingNode.tuples_for_scope``, the call the frozen interface demonstrates,
and compared against Agent 2's ``expected-bindings.json`` as **sorted lists,
not sets** -- ``bp-duplicate-values`` has two panels with identical values and
must stay two tuples.

``BPCrossJoinIsDetectable`` at the bottom is the fault injection: it feeds the
engine a deliberately cross-joined binding tree and asserts the checks above
fail.  A Gate 3 suite that passes on cross-joined bindings does not count.
"""

from __future__ import annotations

import copy
import json
import unittest

from . import bp_case
from ._engine import engine, graph
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


class BPTupleMultiset(engine.EngineTestCase):
    """The concept note section 5 requirement, on every fixture."""

    def test_the_concept_note_multiset_is_exactly_right(self):
        results = run_fixture("bp-two-panels")
        tree = bp_case.binding_tree("bp-two-panels", results)
        got = sorted(tree.tuples_for_scope("panel", TUPLE_VARS))
        self.assertEqual(got, [("bp-1", "120", "80"), ("bp-2", "105", "70")])

    def test_every_fixture_matches_agent_2s_declared_multiset(self):
        for fixture_id in FIXTURES:
            with self.subTest(fixture=fixture_id):
                results = run_fixture(fixture_id)
                tree = bp_case.binding_tree(fixture_id, results)
                for variables in (TUPLE_VARS, FULL_VARS):
                    want, forbidden = expected(fixture_id, variables)
                    got = sorted(tree.tuples_for_scope("panel", variables))
                    # sorted LISTS, not sets: bp-duplicate-values has two
                    # panels whose tuples coincide and must stay two tuples.
                    self.assertEqual(got, sorted(want), (fixture_id, variables))
                    for bad in forbidden:
                        self.assertNotIn(bad, got, (fixture_id, bad))

    def test_duplicate_values_stay_two_tuples(self):
        results = run_fixture("bp-duplicate-values")
        tree = bp_case.binding_tree("bp-duplicate-values", results)
        got = sorted(tree.tuples_for_scope("panel", ["sys", "dia"]))
        self.assertEqual(got, [("120", "80"), ("120", "80")])
        self.assertEqual(len(set(got)), 1,
                         "the two tuples are identical -- a set comparison would "
                         "silently accept one of them going missing")

    def test_the_multiset_survives_both_rdf_variants(self):
        """bp-reordered-serialisation: a different line order, and a genuinely
        different graph whose fhir:index values move.  Components are selected
        by LOINC code, so neither changes the answer."""
        base = sorted(bp_case.binding_tree(
            "bp-reordered-serialisation",
            run_fixture("bp-reordered-serialisation")).tuples_for_scope("panel", TUPLE_VARS))
        for variant in ("same_graph_different_serialisation",
                        "different_graph_same_clinical_content"):
            with self.subTest(variant=variant):
                results = run_fixture("bp-reordered-serialisation", variant)
                got = sorted(bp_case.binding_tree("bp-reordered-serialisation",
                                                  results).tuples_for_scope("panel", TUPLE_VARS))
                self.assertEqual(got, base)
                self.assertEqual(got, [("bp-1", "120", "80"), ("bp-2", "105", "70")])

    def test_the_components_reversed_variant_really_is_a_different_graph(self):
        """Otherwise the permutation test would be proving nothing."""
        d = bp_case.fixture_dir("bp-reordered-serialisation")
        a = set((d / "canonical.nt").read_text().splitlines())
        b = set((d / "canonical-components-reversed.nt").read_text().splitlines())
        self.assertNotEqual(a, b)
        c = set((d / "canonical-reordered.nt").read_text().splitlines())
        self.assertEqual(a, c, "canonical-reordered.nt should be the same triple set")

    def test_an_omitted_component_leaves_a_hole_not_a_borrowed_value(self):
        results = run_fixture("bp-component-omitted")
        tree = bp_case.binding_tree("bp-component-omitted", results)
        got = sorted(tree.tuples_for_scope("panel", TUPLE_VARS))
        self.assertEqual(got, [("bp-1", "120", ""), ("bp-2", "105", "70")])
        # and no diastolic node exists at all for bp-1
        triples = graph.parse(results["bp-1"]["nquads"])
        self.assertEqual(
            graph.subjects_of_type(triples, "https://example.org/fhir-sulo/DiastolicBloodPressureResult"),
            [])

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

    def test_each_panel_refers_to_exactly_its_own_two_quantities(self):
        for obs, r in self.results.items():
            with self.subTest(resource=obs):
                v = r["_hostValues"]
                triples = graph.parse(r["nquads"])
                refs = graph.objects_of(triples, "<%s>" % v["panelRecord"],
                                        "<%srefersTo>" % SULO)
                self.assertEqual(refs, sorted(["<%s>" % v["sysResult"],
                                               "<%s>" % v["diaResult"]]))

    def test_each_quantity_has_one_value_one_unit_and_one_quality(self):
        for obs, r in self.results.items():
            v = r["_hostValues"]
            triples = graph.parse(r["nquads"])
            for node in ("sysResult", "diaResult"):
                with self.subTest(resource=obs, node=node):
                    iri = "<%s>" % v[node]
                    self.assertEqual(len(graph.objects_of(triples, iri, "<%shasValue>" % SULO)), 1)
                    self.assertEqual(len(graph.objects_of(triples, iri, "<%shasPart>" % SULO)), 1)
                    self.assertEqual(len(graph.objects_of(triples, iri, "<%srefersTo>" % SULO)), 1)

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
                    "<https://example.org/fhir-sulo/ObservationRecord>"]))

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

    def test_a_cross_joined_binding_tree_fails_the_multiset_check(self):
        """Swap the two panels' diastolic values -- the exact cross-join the
        concept note names -- and the check must reject it."""
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

    def test_injecting_a_wrong_value_into_the_engine_changes_the_graph(self):
        """Not just the tuple check -- the materialized graph must move too.

        Feeds the materializer a mutated binding tree through the harness's
        override hook, which exists only for this test.
        """
        results = run_fixture("bp-two-panels")
        clean = results["bp-1"]
        mutated_bindings = copy.deepcopy(clean["bindings"])
        key = "https://w3id.org/fhir-sulo/map/bp/var#diaValue"
        mutated_bindings[key] = {"value": "70",
                                 "type": "http://www.w3.org/2001/XMLSchema#decimal"}
        dirty = bp_case.run("bp-two-panels", "bp-1", bindings_override=mutated_bindings)
        engine.require_clean(dirty)
        self.assertNotEqual(sorted(graph.parse(clean["nquads"])),
                            sorted(graph.parse(dirty["nquads"])))
        triples = graph.parse(dirty["nquads"])
        self.assertEqual(
            graph.objects_of(triples, "<%s>" % clean["_hostValues"]["diaResult"],
                             "<%shasValue>" % SULO),
            ['"70"^^<http://www.w3.org/2001/XMLSchema#decimal>'])


if __name__ == "__main__":
    unittest.main()
