"""Target shape validation, on real map output, with R5 unset rejecting.

Two review findings drove this file's shape:

**M4** — R5 was quietly decided as option B. A permissive default meant the
CLI, the benchmark and a test all ran under it while ``R5_RESOLVED = False``
claimed the question was open. ``R5UnsetRejects`` is the replacement: unset
now refuses, mirroring what Agent 5 did for R2.

**M2** — every check ran on hand-written graphs. ``RealMapOutputConforms``
validates the graphs Agent 3's maps actually emit. The hand-written negatives
stay, because a deliberately malformed graph has no real-map equivalent.

Needs the pinned environment (``requirements-runtime.txt``); skipped with a
message rather than failing when rdflib/pyshacl are absent, because the
contract tests must still run on the bare system interpreter.
"""

from __future__ import annotations

import importlib.util
import unittest

from . import mapoutput
from .support import graph_text

from fhir_sulo.validation import shapes_check, strictness

# Probed with find_spec, not with a bare `import`: shapes_check imports rdflib
# and pyshacl lazily, so importing it proves nothing about whether they are
# installed, and a linter that removes an "unused" import would silently turn
# these skips into failures on a bare interpreter. That is exactly what
# happened once.
HAVE_SHACL = all(
    importlib.util.find_spec(name) is not None for name in ("rdflib", "pyshacl")
)

SKIP = "needs the pinned environment: .venv/bin/pip install -r requirements-runtime.txt"

# Every suite below names its strictness. That is the point of M4: there is no
# default to inherit, so a test states the answer it is testing under.
LITERAL = strictness.CONCEPT_NOTE_LITERAL          # R5 option B
STRICT = strictness.CLOSED_WORLD_COMPLETE          # R5 option A


class R5UnsetRejects(unittest.TestCase):
    """R5 is open, and open now means *refused*, not *permissive*."""

    def test_the_recorded_answer_is_still_null(self):
        self.assertIsNone(
            strictness.recorded_mode(),
            "R5 is an open clinical/ontology review item. Recording an answer "
            "needs a reviewer reply and a decision record.",
        )

    def test_the_policy_declares_that_unset_rejects(self):
        policy = strictness.load_policy()
        self.assertEqual(policy["unset_behaviour"], "reject")
        self.assertIsNone(policy["reviewer_decision"])

    def test_resolving_without_a_mode_raises(self):
        with self.assertRaises(strictness.R5PolicyUnset) as caught:
            strictness.resolve()
        self.assertIn("unanswered", str(caught.exception))
        self.assertIn("concept-note-literal", str(caught.exception))

    def test_resolving_from_policy_raises_while_it_is_unset(self):
        """'from-policy' and no argument must behave identically.

        Otherwise there would be a spelling of the call that looks deliberate
        but still picks an answer.
        """
        with self.assertRaises(strictness.R5PolicyUnset):
            strictness.resolve("from-policy")

    def test_validate_graph_has_no_default_strictness(self):
        """The API-level half of the guarantee.

        A default argument is how option B came to be in force everywhere. If
        someone reinstates one, this fails.
        """
        import inspect

        signature = inspect.signature(shapes_check.validate_graph)
        parameter = signature.parameters["strictness"]
        self.assertIs(parameter.default, inspect.Parameter.empty)
        self.assertIs(
            signature.parameters["strictness"].kind,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )

    @unittest.skipUnless(HAVE_SHACL, SKIP)
    def test_validating_with_no_answer_refuses_rather_than_permits(self):
        with self.assertRaises(strictness.R5PolicyUnset):
            shapes_check.validate_graph(graph_text("egfr-target.ttl"), None)

    def test_the_cli_requires_an_explicit_strictness(self):
        from fhir_sulo.validation import cli

        parser = cli.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["shapes", "--graph", "x.nt"])
        args = parser.parse_args(
            ["shapes", "--graph", "x.nt", "--strictness", "concept-note-literal"]
        )
        self.assertEqual(args.strictness, "concept-note-literal")

    def test_the_benchmark_requires_an_explicit_strictness(self):
        """So a benchmark report always names what it ran under."""
        import os
        import sys

        benchmarks = os.path.join(mapoutput.REPO, "benchmarks")
        if benchmarks not in sys.path:
            sys.path.insert(0, benchmarks)
        import run_benchmark

        with self.assertRaises(SystemExit):
            run_benchmark.main(["-n", "1"])

    def test_both_options_are_implemented(self):
        """A, B and the R11-shaped split C. All selectable, none selected."""
        self.assertEqual(
            set(strictness.allowed_modes()),
            {"concept-note-literal", "closed-world-complete",
             "quantity-bearer-only"},
        )
        self.assertFalse(LITERAL.require_quantity_is_feature_of)
        self.assertFalse(LITERAL.require_time_unit)
        self.assertTrue(STRICT.require_quantity_is_feature_of)
        self.assertTrue(STRICT.require_time_unit)

    def test_a_split_needs_a_stated_rationale(self):
        """R5 option C is a reasoned position, not a half-set flag."""
        with self.assertRaises(strictness.R5PolicyUnset):
            strictness.Strictness(
                require_quantity_is_feature_of=True, require_time_unit=False
            )
        split = strictness.Strictness(
            require_quantity_is_feature_of=True,
            require_time_unit=False,
            rationale="reviewer answered A for DR-002 axiom 4 only",
        )
        self.assertIn("option-C", split.label)
        self.assertIn("strict-quantity-isfeatureof.ttl", split.modules())
        self.assertNotIn("strict-time-unit.ttl", split.modules())


@unittest.skipUnless(HAVE_SHACL, SKIP)
@unittest.skipUnless(mapoutput.AVAILABLE, mapoutput.SKIP_NO_FIXTURES)
class RealMapOutputConforms(unittest.TestCase):
    """Every graph Agent 3's maps actually emit satisfies the shape contract.

    This is the check that has teeth: if a map starts emitting a quantity with
    two values, or a role with no holder, it fails here. The previous version
    of this suite validated hand-written graphs and would not have noticed.
    """

    def test_there_are_expected_graphs_to_check(self):
        self.assertGreaterEqual(
            len(mapoutput.MAPPED), 9,
            "expected at least the nine mapped fixtures Agent 3 ships",
        )

    def test_every_emitted_graph_conforms_under_r5_option_b(self):
        for item in mapoutput.MAPPED:
            with self.subTest(fixture=item.fixture_id, strictness=LITERAL.label):
                report = shapes_check.validate_graph(item.graph(), LITERAL)
                self.assertTrue(
                    report.conforms,
                    "%s/%s under %s:\n%s"
                    % (item.family, item.fixture_id, LITERAL.label, report.text),
                )

    def test_every_emitted_graph_records_the_r2_mode_it_was_built_under(self):
        """R2 is open too. A graph that does not say which answer produced it
        cannot be re-checked when the reviewer decides."""
        for item in mapoutput.MAPPED:
            with self.subTest(fixture=item.fixture_id):
                self.assertIn(
                    item.quality_identity_mode,
                    {"per-observation", "persistent-per-person-code"},
                    "outcome.json must record quality_identity_mode",
                )

    def test_only_R5s_second_row_still_fails_on_real_output(self):
        """R11 cleared R5 row 1; row 2 is what remains open.

        This test previously asserted that full strictness failed on **both**
        rows, because the maps emitted no ``sulo:isFeatureOf`` on quantities.
        Then the reviewer answered R11 -- "the results ... are features of the
        individual" -- and Agent 3 emitted it, which is R5 row 1 satisfied.

        Updated rather than repaired: the surviving violation set is the
        cleanest evidence that R11 answered one row and not the other. If
        ``isFeatureOf`` ever reappears here, R11 has been reverted; if
        ``hasPart`` disappears, R5 row 2 has been answered without anyone
        recording it.
        """
        item = mapoutput.by_id("egfr-baseline")
        report = shapes_check.validate_graph(item.graph(), STRICT)
        self.assertFalse(report.conforms, "R5 row 2 is open; full strictness must still fail")
        paths = {v.path for v in report.violations}
        self.assertEqual(
            paths, {"https://w3id.org/sulo/hasPart"},
            "expected only the time-unit row to fail; isFeatureOf is now emitted (R11)",
        )
        self.assertTrue(all("R5 option A" in v.message for v in report.violations))

    def test_a_whole_batch_of_current_graphs_conforms_together(self):
        """Per-fixture conformance does not imply the union conforms: the
        orphan and cross-patient constraints are graph-wide.

        The union is over CURRENT graphs, one per subject. `egfr-456` ships
        at v1, v2 and v3, and v1 and v2 emit the same result node IRI -- so
        merging both puts two `sulo:hasValue` literals on one quantity and
        violates DR-002 axiom 1. That is not a shape bug; it is the reason
        the store replaces a superseded version instead of accumulating it.
        Merging every version would assert a graph the pipeline never
        produces.
        """
        graph = mapoutput.merged_graph(
            *[m.fixture_id for m in mapoutput.CURRENT_MAPPED])
        report = shapes_check.validate_graph(graph, LITERAL)
        self.assertTrue(report.conforms, report.text)

    def test_merging_two_versions_of_one_resource_does_violate(self):
        """Control: the exclusion above is load-bearing, not cosmetic.

        If this ever conforms, either the correction scenario stopped
        sharing node IRIs or the functional-hasValue shape stopped being
        enforced -- both worth knowing.
        """
        ids = {m.fixture_id for m in mapoutput.MAPPED}
        if not {"egfr-baseline", "egfr-corrected"} <= ids:
            self.skipTest("needs both versions of egfr-456 as mapped fixtures")
        graph = mapoutput.merged_graph("egfr-baseline", "egfr-corrected")
        report = shapes_check.validate_graph(graph, LITERAL)
        self.assertFalse(
            report.conforms,
            "merging v1 and v2 of one resource should violate the functional "
            "hasValue constraint; it did not")


@unittest.skipUnless(HAVE_SHACL, SKIP)
@unittest.skipUnless(mapoutput.AVAILABLE, mapoutput.SKIP_NO_FIXTURES)
class ValidationDigestIdentifiesTheGraph(unittest.TestCase):
    """MINOR finding: the digest was the same for all nine graphs.

    It hashed only the findings, and a conforming report has none - so
    ``RunRecord.validation_report_digest`` said "something conformed" and
    nothing about what. A validation digest that cannot tell you what was
    validated is not evidence.
    """

    def test_digests_collide_exactly_when_the_graphs_are_equal(self):
        """The right invariant, and it is not "all digests differ".

        ``bp-reordered-serialisation`` is supposed to produce a graph
        byte-identical to ``bp-two-panels`` - that is what the fixture tests.
        So those two *must* share a digest, and a test demanding all-distinct
        would be asserting a bug. What must hold is that two fixtures share a
        digest if and only if they emitted the same triples.
        """
        digests, graphs = {}, {}
        for item in mapoutput.MAPPED:
            report = shapes_check.validate_graph(item.graph(), LITERAL)
            digests.setdefault(report.digest, set()).add(item.fixture_id)
            graphs.setdefault(
                frozenset(item.triples().splitlines()), set()
            ).add(item.fixture_id)

        self.assertEqual(
            sorted(sorted(g) for g in digests.values()),
            sorted(sorted(g) for g in graphs.values()),
            "digest grouping does not match graph-content grouping",
        )
        # And the grouping is not degenerate: before data_digest existed,
        # every conforming report hashed the same and this was one group.
        self.assertGreaterEqual(len(digests), 8)

    def test_the_same_graph_produces_the_same_digest(self):
        item = mapoutput.by_id("egfr-baseline")
        first = shapes_check.validate_graph(item.graph(), LITERAL)
        second = shapes_check.validate_graph(item.graph(), LITERAL)
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.data_digest, second.data_digest)

    def test_the_digest_distinguishes_strictness(self):
        item = mapoutput.by_id("egfr-baseline")
        self.assertNotEqual(
            shapes_check.validate_graph(item.graph(), LITERAL).digest,
            shapes_check.validate_graph(item.graph(), STRICT).digest,
        )

    def test_the_report_states_what_it_validated(self):
        item = mapoutput.by_id("egfr-baseline")
        report = shapes_check.validate_graph(item.graph(), LITERAL)
        self.assertEqual(report.triples_validated, len(item.graph()))
        self.assertGreater(report.focus_nodes, 0)
        self.assertTrue(report.data_digest)


@unittest.skipUnless(HAVE_SHACL, SKIP)
@unittest.skipUnless(mapoutput.AVAILABLE, mapoutput.SKIP_NO_FIXTURES)
class R5RowsAreIndependent(unittest.TestCase):
    """R5 has two rows and neither implies the other.

    Review item **R11** makes the maps emit ``result sulo:isFeatureOf
    person``, which satisfies R5's first row in practice. Agent 1 recorded
    that as *bearing on* R5, not answering it, and **row 2 - an explicit
    ``sulo:Unit`` on a ``TimeInstant`` - remains open**.

    The risk that creates is a coupling bug: row 1 arriving flips the whole
    switch and row 2 gets answered by accident. These tests are the proof it
    cannot happen. The strictness flags are two independent booleans, the
    policy's recorded ``mode`` is still ``null``, and a graph that satisfies
    row 1 still fails row 2.
    """

    def test_the_policy_is_still_unset_after_r11(self):
        self.assertIsNone(strictness.recorded_mode())
        self.assertEqual(strictness.load_policy()["unset_behaviour"], "reject")
        with self.assertRaises(strictness.R5PolicyUnset):
            strictness.resolve()

    def test_the_two_flags_are_separately_settable(self):
        modes = strictness.allowed_modes()
        self.assertIn("quantity-bearer-only", modes)
        split = strictness.resolve("quantity-bearer-only")
        self.assertTrue(split.require_quantity_is_feature_of)
        self.assertFalse(split.require_time_unit)
        self.assertIn("strict-quantity-isfeatureof.ttl", split.modules())
        self.assertNotIn("strict-time-unit.ttl", split.modules())

    def _r11_shaped(self):
        """The egfr graph as R11 will emit it: result isFeatureOf person."""
        item = mapoutput.by_id("egfr-baseline")
        lines = item.triples().splitlines()
        type_nt = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
        person = next(
            l.split(" ", 1)[0] for l in lines
            if type_nt in l and (mapoutput.EX + "Person") in l
        )
        result = "<%segfr-result-egfr-456>" % mapoutput.EX
        return "\n".join(lines) + (
            "\n%s <https://w3id.org/sulo/isFeatureOf> %s .\n" % (result, person)
        )

    def test_satisfying_row_one_does_not_satisfy_row_two(self):
        """The coupling test.

        Under full strictness an R11-shaped graph has exactly ONE violation
        left, and it is the time-unit one. If the flags were coupled, either
        both would clear or neither would.
        """
        report = shapes_check.validate_graph(self._r11_shaped(), STRICT)
        self.assertFalse(report.conforms)
        self.assertEqual(
            {v.path for v in report.violations},
            {"https://w3id.org/sulo/hasPart"},
            "the only remaining strict violation must be R5 row 2 (time unit)",
        )
        self.assertTrue(any("TimeInstant" in v.message for v in report.violations))

    def test_row_one_alone_passes_on_an_r11_shaped_graph(self):
        report = shapes_check.validate_graph(
            self._r11_shaped(), strictness.QUANTITY_BEARER_ONLY
        )
        self.assertTrue(report.conforms, report.text)

    def test_row_one_now_passes_on_real_output_because_R11_landed(self):
        """The row-1-only mode is satisfied by the graphs the maps emit.

        Renamed from ``..._still_fails_on_a_pre_r11_graph``: the real
        ``egfr-baseline`` graph is no longer pre-R11. The mode is still
        checking something -- the companion test below shows it rejecting a
        graph with the bearer arc stripped out.
        """
        report = shapes_check.validate_graph(
            mapoutput.by_id("egfr-baseline").graph(),
            strictness.QUANTITY_BEARER_ONLY,
        )
        self.assertTrue(report.conforms, report.text)

    def test_row_one_is_not_vacuous_it_rejects_a_graph_without_the_bearer(self):
        """Strip R11's isFeatureOf back out and the mode must object.

        Without this, the test above could pass because the mode checks
        nothing at all.
        """
        import rdflib

        graph = mapoutput.by_id("egfr-baseline").graph()
        stripped = rdflib.Graph()
        bearer = rdflib.URIRef("https://w3id.org/sulo/isFeatureOf")
        quantity = rdflib.URIRef("https://w3id.org/sulo/Quantity")
        quantities = set(graph.subjects(rdflib.RDF.type, quantity))
        removed = 0
        for s_, p_, o_ in graph:
            if p_ == bearer and s_ in quantities:
                removed += 1
                continue
            stripped.add((s_, p_, o_))
        self.assertGreater(removed, 0, "fixture no longer has a quantity bearer arc to strip")

        report = shapes_check.validate_graph(stripped, strictness.QUANTITY_BEARER_ONLY)
        self.assertFalse(report.conforms)
        self.assertEqual(
            {v.path for v in report.violations},
            {"https://w3id.org/sulo/isFeatureOf"},
        )

    def test_the_default_still_accepts_both_shapes_of_graph(self):
        """R5 is open, so neither row may be enforced by default."""
        for label, graph in (("pre-R11", mapoutput.by_id("egfr-baseline").graph()),
                             ("R11", self._r11_shaped())):
            with self.subTest(graph=label):
                self.assertTrue(
                    shapes_check.validate_graph(graph, LITERAL).conforms)


@unittest.skipUnless(HAVE_SHACL, SKIP)
class NegativeCasesAreRejected(unittest.TestCase):
    """Hand-written on purpose: no correct map emits these.

    Kept as minimal units. If a change makes any of them conform, the change
    is wrong.
    """

    @classmethod
    def setUpClass(cls):
        cls.report = shapes_check.validate_graph(graph_text("negatives.ttl"), LITERAL)

    def _messages_for(self, fragment):
        return [v.message for v in self.report.violations if fragment in v.focus_node]

    def test_the_graph_does_not_conform(self):
        self.assertFalse(self.report.conforms)

    def test_an_orphan_unit_is_caught(self):
        self.assertTrue(any("orphan" in m for m in self._messages_for("orphan-unit")))

    def test_an_orphan_result_is_caught(self):
        self.assertTrue(any("orphan" in m for m in self._messages_for("orphan-result")))

    def test_a_cross_patient_result_is_caught(self):
        self.assertTrue(
            any("cross-patient" in m for m in self._messages_for("cross-result"))
        )

    def test_a_hasPatient_shortcut_is_caught(self):
        self.assertTrue(
            any("shortcut" in m for m in self._messages_for("shortcut-encounter"))
        )

    def test_a_quantity_without_a_unit_is_caught(self):
        self.assertTrue(any("Unit part" in m for m in self._messages_for("unitless")))

    def test_a_quantity_with_two_values_is_caught(self):
        """DR-002 axiom 1: sulo:hasValue is owl:FunctionalProperty."""
        self.assertTrue(
            any("exactly one numeric" in m for m in self._messages_for("twovalue"))
        )

    def test_a_role_with_no_holder_is_caught(self):
        self.assertTrue(
            any("isFeatureOf exactly one" in m for m in self._messages_for("dangling-role"))
        )

    def test_a_time_instant_with_lost_precision_is_caught(self):
        self.assertTrue(any("precision" in m for m in self._messages_for("sloppy-time")))

    def test_a_node_in_two_disjoint_feature_branches_is_caught(self):
        self.assertTrue(any("disjoint" in m for m in self._messages_for("confused")))


if __name__ == "__main__":
    unittest.main()
