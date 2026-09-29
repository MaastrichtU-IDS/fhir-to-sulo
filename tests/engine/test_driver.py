"""Materialization driver tests, against recorded responses from the real engine.

Two things are being tested and they are different:

* **The refusals.** CD-2 exists because the engine's CLI exits 0 on a fatal
  error, on a partial graph, and on a graph truncated to 19 items. Each of
  those is a recorded response in ``fixtures/responses``, taken from the pinned
  engine on a committed schema pair -- not invented -- and each must raise.
* **The boundary.** DR-302 requires the driver to emit no triple of its own and
  asks for that to be enforced rather than asserted in prose.
  :class:`TestDriverEmitsNoTripleOfItsOwn` is that enforcement, and it runs
  against the multi-pass union, where a host-built triple would be easiest to
  hide.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from support import load_response  # noqa: E402

from fhir_sulo.contracts import TransformStatus  # noqa: E402
from fhir_sulo.engine.driver import (  # noqa: E402
    AcceptCeilingReached,
    BindingsNotConsumed,
    Guards,
    MaterializationFailure,
    PassSpec,
    SourceValidationFailure,
    UnboundVariables,
    UntracedQuad,
    graph_key,
    ineligible_result,
    interpret_pass,
    to_transform_result,
    union_passes,
)
from fhir_sulo.engine.rdfterms import BNODE, Quad, Term, shape_signature  # noqa: E402

VAR = "https://w3id.org/fhir-sulo/var#"
EX = "https://w3id.org/fhir-sulo/"
OBS1 = "https://fhir.example/Observation/bp-1"
OBS2 = "https://fhir.example/Observation/bp-2"


def _spec(pass_id, root, scope=None, keys=()):
    """A PassSpec stub. Only the fields ``interpret_pass`` reads matter here;
    the schemas and data already went into the recorded response."""
    return PassSpec(
        pass_id=pass_id, source_schema="", data="", node="",
        target_schema="", root=root, scope_name=scope, key_variables=keys,
    )


def bp_pass(name="ok-bp", pass_id="bp", root="urn:g:bp-1#panel"):
    return interpret_pass(
        _spec(pass_id, root, scope="component", keys=(VAR + "componentCode",)),
        load_response(name),
    )


# --------------------------------------------------------------------------
# the happy path, and the acceptance tuple
# --------------------------------------------------------------------------


class TestSingleLevelMap(unittest.TestCase):
    def test_bp_pair_materializes(self):
        result = union_passes([bp_pass()])
        self.assertEqual(len(result.records), 11)
        self.assertEqual(result.untraced_quads(), ())

    def test_component_pairing_survives(self):
        """The acceptance requirement: 120 stays with systolic, 80 with
        diastolic. A cross-join would produce a tuple that was never in the
        source, which is exactly what tuples_for_scope surfaces."""
        tree = union_passes([bp_pass()]).binding_tree
        tuples = tree.tuples_for_scope("component", [VAR + "componentValue",
                                                     VAR + "componentUnit"])
        self.assertEqual(sorted(tuples), [("120", "mm[Hg]"), ("80", "mm[Hg]")])

    def test_pairing_is_independent_of_triple_order(self):
        """DR-301 probe 3 permuted the input; so does the recorded fixture."""
        a = union_passes([bp_pass("ok-bp")]).binding_tree
        b = union_passes([bp_pass("ok-bp-permuted")]).binding_tree
        keys = [VAR + "componentValue", VAR + "componentUnit"]
        self.assertEqual(sorted(a.tuples_for_scope("component", keys)),
                         sorted(b.tuples_for_scope("component", keys)))

    def test_iteration_keys_distinguish_the_components(self):
        tree = union_passes([bp_pass()]).binding_tree
        keys = {child.iteration_key for child in tree.children}
        self.assertEqual(len(keys), 2)

    def test_ambiguity_is_surfaced_not_swallowed(self):
        """The engine reports 3 accepting materializations even for this
        correct map. That must reach the caller rather than be assumed away."""
        result = union_passes([bp_pass()])
        self.assertTrue(any("accepting materializations" in d
                            for d in result.diagnostics))


# --------------------------------------------------------------------------
# the refusals: every silent engine failure in DR-301
# --------------------------------------------------------------------------


class TestFailFast(unittest.TestCase):
    def test_unbound_variable_raises(self):
        """DR-301 probe 8c: the CLI prints a partial graph and exits 0."""
        response = load_response("neg-unbound-variable")
        self.assertTrue(response["ok"])                       # the engine is happy
        self.assertEqual(len(response["quads"]), 1)           # ...with 1 of 11 quads
        with self.assertRaises(UnboundVariables):
            interpret_pass(_spec("x", "urn:g:x"), response)

    def test_unknown_function_without_a_colon_raises(self):
        """This one does NOT appear in lastReport.unboundVariables: the code
        dies inside extensions.lower instead. Binding coverage is what catches
        it, which is why coverage is checked as well as the report."""
        response = load_response("neg-unknown-function-no-colon")
        self.assertEqual(response["lastReport"]["unboundVariables"], [])
        with self.assertRaises(BindingsNotConsumed):
            interpret_pass(_spec("x", "urn:g:x"), response)

    def test_map_on_a_shape_valued_constraint_raises(self):
        response = load_response("neg-shaperef-map")
        self.assertTrue(response["ok"])
        with self.assertRaises(BindingsNotConsumed):
            interpret_pass(_spec("x", "urn:g:x"), response)

    def test_source_validation_failure_raises(self):
        with self.assertRaises(SourceValidationFailure):
            interpret_pass(_spec("x", "urn:g:x"), load_response("source-invalid"))

    def test_dangling_shape_reference_raises(self):
        with self.assertRaises(MaterializationFailure):
            interpret_pass(_spec("x", "urn:g:x"), load_response("neg-dangling"))

    def test_exploration_truncated_raises(self):
        response = dict(load_response("ok-bp"))
        response["lastReport"] = dict(response["lastReport"], explorationTruncated=True)
        with self.assertRaises(MaterializationFailure):
            interpret_pass(_spec("x", "urn:g:x"), response)


class TestTruncationIsLoud(unittest.TestCase):
    """DR-301 B2 is the finding that would have been shipped: 60 components in,
    19 out, exit 0, empty stderr. Both recordings are real engine output on the
    same 60-component graph; only the guards differ."""

    def test_engine_defaults_truncate(self):
        response = load_response("truncation-engine-defaults")
        self.assertTrue(response["ok"])
        self.assertLess(response["coverage"]["consumed"], response["coverage"]["total"])

    def test_the_driver_refuses_the_truncated_result(self):
        engine_defaults = Guards(max_accepts=20, max_repeat=50, max_steps=1_000_000,
                                 explore_steps=10_000, max_call_depth=50)
        with self.assertRaises((AcceptCeilingReached, BindingsNotConsumed)):
            interpret_pass(_spec("x", "urn:g:x"),
                           load_response("truncation-engine-defaults"),
                           guards=engine_defaults)

    def test_raised_guards_consume_everything(self):
        response = load_response("truncation-guards-raised")
        self.assertEqual(response["coverage"]["consumed"], response["coverage"]["total"])
        result = interpret_pass(_spec("x", "urn:g:x"), response)
        self.assertEqual(len(result.records), 243)

    def test_our_defaults_are_not_the_engine_defaults(self):
        """CD-2: nothing may inherit an engine default."""
        guards = Guards()
        self.assertGreater(guards.max_accepts, 20)
        self.assertGreater(guards.max_repeat, 50)
        self.assertEqual(
            set(guards.to_bridge()),
            {"maxAccepts", "maxRepeat", "maxSteps", "exploreSteps", "maxCallDepth"},
        )


class TestNestedRepetitionIsNotCaughtHere(unittest.TestCase):
    """The honest limit of the driver, recorded so nobody relies on it.

    Two levels of repetition consume every binding and truncate nothing, so
    none of the driver's runtime checks fire -- the values are all present and
    all attached to the wrong group. Only the linter can stop this, which is
    why DR-302 is a build-time constraint and not a runtime one.
    """

    def test_the_engine_reports_nothing_wrong(self):
        response = load_response("neg-nested-repetition")
        self.assertTrue(response["ok"])
        self.assertEqual(response["lastReport"]["unboundVariables"], [])
        self.assertFalse(response["lastReport"]["explorationTruncated"])
        self.assertEqual(response["coverage"]["unconsumed"], [])

    def test_and_so_the_driver_accepts_it(self):
        result = interpret_pass(_spec("x", "urn:g:x"), load_response("neg-nested-repetition"))
        self.assertTrue(result.records)

    def test_but_the_output_is_wrong(self):
        """Demonstrated, not asserted in prose: the source has two panels of two
        components; the engine emits a different number of panels."""
        result = interpret_pass(_spec("x", "urn:g:x"),
                                load_response("neg-nested-repetition"))
        panels = [r for r in result.records if r.predicate == EX + "hasPanel"]
        self.assertNotEqual(len(panels), 2,
                            "if this ever equals 2 the engine has been fixed and "
                            "DR-302 should be revisited")

    def test_the_linter_catches_what_the_driver_cannot(self):
        from support import load_pair

        from fhir_sulo.engine.linter import lint_pair

        report = lint_pair(*load_pair("neg-nested-repetition"))
        self.assertIn("SP002", {f.code for f in report.errors})


# --------------------------------------------------------------------------
# the boundary: a driver, not a transformer
# --------------------------------------------------------------------------


class TestDriverEmitsNoTripleOfItsOwn(unittest.TestCase):
    """DR-302: "its tests must assert that it emits no triple of its own".

    The mechanism: ``run-pass.js`` numbers every TripleConstraint in the target
    schema and tags each quad with the id of the one that emitted it. A quad
    the host had built would carry no id, or an id the schema never declared.
    """

    def three_passes(self):
        return [
            interpret_pass(_spec("a", "urn:g:p-1#subject", scope="panel",
                                 keys=(VAR + "panelIri",)),
                           load_response("decomp-pass-a")),
            interpret_pass(_spec("b1", OBS1, scope="component",
                                 keys=(VAR + "componentValue",)),
                           load_response("decomp-pass-b1")),
            interpret_pass(_spec("b2", OBS2, scope="component",
                                 keys=(VAR + "componentValue",)),
                           load_response("decomp-pass-b2")),
        ]

    def test_every_quad_in_the_union_names_a_target_schema_constraint(self):
        result = union_passes(self.three_passes())
        self.assertEqual(result.untraced_quads(), ())
        declared = {p.pass_id: p.constraint_ids for p in result.passes}
        for record in result.records:
            self.assertIn(record.constraint_id, declared[record.pass_id],
                          f"{record.quad.to_ntriples()} is not attributable")

    def test_the_union_adds_no_quad_to_the_passes(self):
        """Counting, so that an extra triple cannot hide behind attribution."""
        passes = self.three_passes()
        result = union_passes(passes)
        self.assertEqual(len(result.records), sum(len(p.records) for p in passes))

    def test_the_union_changes_nothing_but_blank_node_labels(self):
        """Relabelling is the one place the host touches a term. Compared under
        a signature that masks blank node labels, the multiset of quads before
        and after the union must be identical."""
        passes = self.three_passes()
        before = sorted(shape_signature(r.quad) for p in passes for r in p.records)
        after = sorted(shape_signature(r.quad) for r in union_passes(passes).records)
        self.assertEqual(before, after)

    def test_a_host_built_quad_would_be_rejected(self):
        """The guard is only a guard if it can fail. Forge one and check."""
        from fhir_sulo.engine.driver import DriverResult, QuadRecord

        passes = self.three_passes()
        genuine = union_passes(passes)
        forged = QuadRecord(
            quad=Quad(Term("iri", "urn:g:p-1#subject"),
                      Term("iri", EX + "invented"),
                      Term("literal", "by the host")),
            pass_id="a", constraint_id="tc:999", predicate=EX + "invented",
            kind="binding", variables=(), frame=0,
        )
        tampered = DriverResult(
            records=genuine.records + (forged,),
            passes=genuine.passes, binding_tree=genuine.binding_tree,
            diagnostics=(),
        )
        self.assertEqual(tampered.untraced_quads(), (len(genuine.records),))
        with self.assertRaises(UntracedQuad):
            to_transform_result(tampered, map_id="m", pairing_hash="h",
                                source_canonical_url="u", source_version_id="1")

    def test_a_quad_with_no_constraint_id_is_rejected_at_the_pass(self):
        response = dict(load_response("ok-bp"))
        provenance = [dict(p) for p in response["provenance"]]
        provenance[0]["constraintId"] = None
        response["provenance"] = provenance
        with self.assertRaises(UntracedQuad):
            interpret_pass(_spec("x", "urn:g:x"), response)

    def test_lineage_is_parallel_to_the_quads_or_the_pass_fails(self):
        response = dict(load_response("ok-bp"))
        response["provenance"] = response["provenance"][:-1]
        with self.assertRaises(UntracedQuad):
            interpret_pass(_spec("x", "urn:g:x"), response)


class TestBlankNodeSafeUnion(unittest.TestCase):
    """Every materialization restarts its counter at ``_:tm0``. DR-301 §4d saw
    this merge unrelated nodes in the first version of probe 10's union."""

    def test_passes_really_do_reuse_blank_node_labels(self):
        b1 = interpret_pass(_spec("b1", OBS1), load_response("decomp-pass-b1"))
        b2 = interpret_pass(_spec("b2", OBS2), load_response("decomp-pass-b2"))
        labels = lambda p: {t.value for r in p.records
                            for t in (r.quad.s, r.quad.o) if t.kind == BNODE}
        self.assertTrue(labels(b1) & labels(b2), "fixture no longer exercises the hazard")

    def test_the_union_keeps_them_apart(self):
        b1 = interpret_pass(_spec("b1", OBS1), load_response("decomp-pass-b1"))
        b2 = interpret_pass(_spec("b2", OBS2), load_response("decomp-pass-b2"))
        result = union_passes([b1, b2])
        by_pass = {}
        for record in result.records:
            for term in (record.quad.s, record.quad.o):
                if term.kind == BNODE:
                    by_pass.setdefault(record.pass_id, set()).add(term.value)
        self.assertEqual(set(by_pass["b1"]) & set(by_pass["b2"]), set())

    def test_duplicate_pass_ids_are_refused(self):
        b1 = interpret_pass(_spec("same", OBS1), load_response("decomp-pass-b1"))
        b2 = interpret_pass(_spec("same", OBS2), load_response("decomp-pass-b2"))
        with self.assertRaises(ValueError):
            union_passes([b1, b2])


class TestDecompositionReproducesTheTwoLevelMap(unittest.TestCase):
    """DR-302's resolution, run through the driver on real engine output.

    The single two-level map gets this wrong (see
    ``TestNestedRepetitionIsNotCaughtHere``). Three one-level passes joined on
    the Observation IRI get it right.
    """

    def result(self):
        return union_passes([
            interpret_pass(_spec("a", "urn:g:p-1#subject"), load_response("decomp-pass-a")),
            interpret_pass(_spec("b1", OBS1, scope="component",
                                 keys=(VAR + "componentValue",)),
                           load_response("decomp-pass-b1")),
            interpret_pass(_spec("b2", OBS2, scope="component",
                                 keys=(VAR + "componentValue",)),
                           load_response("decomp-pass-b2")),
        ])

    def panels(self, result):
        """time -> sorted magnitudes, read out of the union's N-Triples."""
        quads = result.records
        by_subject = {}
        for record in quads:
            key = record.quad.s.to_ntriples()
            by_subject.setdefault(key, []).append(record)
        times, magnitudes = {}, {}
        for subject, records in by_subject.items():
            for record in records:
                if record.predicate == EX + "atTime":
                    times[subject] = record.quad.o.value
                if record.predicate == EX + "hasMeasurement":
                    magnitudes.setdefault(subject, []).append(record.quad.o.to_ntriples())
        out = {}
        for subject, when in times.items():
            values = []
            for measurement in magnitudes.get(subject, []):
                for record in by_subject.get(measurement, []):
                    if record.predicate == EX + "magnitude":
                        values.append(record.quad.o.value)
            out[when] = sorted(values)
        return out

    def test_each_observation_keeps_its_own_components(self):
        self.assertEqual(
            self.panels(self.result()),
            {"2026-03-04T09:15:00Z": ["120", "80"],
             "2026-03-04T11:40:00Z": ["105", "70"]},
        )

    def test_the_skeleton_links_to_the_same_iris_the_passes_are_rooted_at(self):
        """The join key is bound by the schema, not inferred by the host."""
        result = self.result()
        linked = {r.quad.o.value for r in result.records
                  if r.predicate == EX + "hasPanel"}
        rooted = {p.root for p in result.passes if p.pass_id.startswith("b")}
        self.assertEqual(linked, rooted)

    def test_the_whole_union_is_still_attributable(self):
        self.assertEqual(self.result().untraced_quads(), ())


# --------------------------------------------------------------------------
# contract hand-off
# --------------------------------------------------------------------------


class TestTransformResultHandoff(unittest.TestCase):
    def test_mapped_result_carries_lineage_for_every_quad(self):
        result = union_passes([bp_pass()])
        transform = to_transform_result(
            result, map_id="bp/0.1.0", pairing_hash="sha256:x",
            source_canonical_url=OBS1, source_version_id="1")
        self.assertIs(transform.status, TransformStatus.MAPPED)
        self.assertTrue(transform.is_loadable)
        self.assertEqual(len(transform.lineage), len(transform.target_quads))
        self.assertEqual({l.quad_index for l in transform.lineage},
                         set(range(len(transform.target_quads))))

    def test_lineage_names_a_variable_for_binding_derived_quads(self):
        transform = to_transform_result(
            union_passes([bp_pass()]), map_id="m", pairing_hash="h",
            source_canonical_url=OBS1, source_version_id="1")
        bindings = [l for l in transform.lineage if l.produced_by.endswith("/binding")]
        self.assertTrue(bindings)
        self.assertTrue(all(l.source_variable for l in bindings))
        self.assertTrue(all(l.source_constraint for l in transform.lineage))

    def test_structural_quads_are_labelled_as_such(self):
        """A blank-node link is emitted by a constraint but carries no binding;
        calling it a binding would be a lineage claim we cannot support."""
        transform = to_transform_result(
            union_passes([bp_pass()]), map_id="m", pairing_hash="h",
            source_canonical_url=OBS1, source_version_id="1")
        structural = [l for l in transform.lineage
                      if l.produced_by.endswith("/structural")]
        self.assertTrue(structural)
        self.assertTrue(all(l.source_variable is None for l in structural))

    def test_graph_key_is_deterministic_and_identity_derived(self):
        first = graph_key("m", "h", OBS1, "1")
        self.assertEqual(first, graph_key("m", "h", OBS1, "1"))
        self.assertNotEqual(first, graph_key("m", "h", OBS1, "2"))

    def test_content_digest_is_stable(self):
        a = union_passes([bp_pass()]).content_digest()
        b = union_passes([bp_pass()]).content_digest()
        self.assertEqual(a, b)

    def test_ineligible_sources_carry_no_quads(self):
        for status in (TransformStatus.SOURCE_ONLY, TransformStatus.REJECTED):
            with self.subTest(status=status):
                result = ineligible_result(
                    status, map_id="m", pairing_hash="h",
                    source_canonical_url=OBS1, source_version_id="1",
                    reason="status entered-in-error")
                self.assertEqual(result.target_quads, ())
                self.assertFalse(result.is_loadable)

    def test_mapped_is_not_an_ineligible_outcome(self):
        with self.assertRaises(ValueError):
            ineligible_result(TransformStatus.MAPPED, map_id="m", pairing_hash="h",
                              source_canonical_url=OBS1, source_version_id="1",
                              reason="no")

    def test_binding_alternatives_are_not_fabricated(self):
        """The engine reports alternative materializations, not alternative
        binding trees. Synthesising BindingNodes for them would invent
        structure, so the count goes to diagnostics instead."""
        transform = to_transform_result(
            union_passes([bp_pass()]), map_id="m", pairing_hash="h",
            source_canonical_url=OBS1, source_version_id="1")
        self.assertEqual(transform.binding_alternatives, ())
        self.assertTrue(any("accepting materializations" in d
                            for d in transform.diagnostics))


class TestNTriplesSerialization(unittest.TestCase):
    def test_literals_are_escaped(self):
        quad = Quad(Term("iri", "urn:s"), Term("iri", "urn:p"),
                    Term("literal", 'a "quoted"\nline\\here'))
        self.assertEqual(
            quad.to_ntriples(),
            '<urn:s> <urn:p> "a \\"quoted\\"\\nline\\\\here" .',
        )

    def test_plain_string_literals_omit_the_xsd_string_datatype(self):
        quad = Quad(Term("iri", "urn:s"), Term("iri", "urn:p"),
                    Term("literal", "x", datatype="http://www.w3.org/2001/XMLSchema#string"))
        self.assertTrue(quad.to_ntriples().endswith('"x" .'))

    def test_language_tags_survive(self):
        quad = Quad(Term("iri", "urn:s"), Term("iri", "urn:p"),
                    Term("literal", "bonjour", language="fr"))
        self.assertTrue(quad.to_ntriples().endswith('"bonjour"@fr .'))


if __name__ == "__main__":
    unittest.main()


class TestNTriplesControlCharacters(unittest.TestCase):
    """Clinical free text carries stray control characters. Emitting one raw
    makes a file no parser accepts -- a corrupt graph rather than a rejected
    one, which is the failure mode this whole package exists to avoid."""

    def literal(self, value):
        return Quad(Term("iri", "urn:s"), Term("iri", "urn:p"),
                    Term("literal", value)).to_ntriples()

    def test_ntriples_echar_escapes(self):
        self.assertIn("\\b", self.literal("\b"))
        self.assertIn("\\f", self.literal("\f"))
        self.assertIn("\\t", self.literal("\t"))

    def test_other_control_characters_become_unicode_escapes(self):
        self.assertIn("\\u0007", self.literal("\x07"))
        self.assertIn("\\u0000", self.literal("\x00"))
        self.assertIn("\\u007F", self.literal("\x7f"))

    def test_no_raw_control_character_survives(self):
        rendered = self.literal("".join(chr(i) for i in range(0x20)) + "\x7f")
        self.assertFalse([c for c in rendered if c < " " or c == "\x7f"])

    def test_a_backslash_is_not_double_escaped(self):
        self.assertTrue(self.literal("a\\b").endswith('"a\\\\b" .'))


class TestBindingTreeRefusesCorruption(unittest.TestCase):
    """The binding tree is what the acceptance tuples are read out of, so a
    silently-wrong one is as bad as a silently-wrong graph."""

    def test_sibling_frames_binding_the_same_variable_are_refused(self):
        from fhir_sulo.engine.driver import _split

        with self.assertRaises(MaterializationFailure):
            _split([{"v:a": {"value": "1"}}, {"v:a": {"value": "2"}}])

    def test_identical_duplicates_are_fine(self):
        from fhir_sulo.engine.driver import _split

        bindings, _ = _split([{"v:a": {"value": "1"}}, {"v:a": {"value": "1"}}])
        self.assertEqual(bindings, {"v:a": "1"})

    def test_a_key_variable_the_iteration_does_not_bind_is_refused(self):
        """Otherwise every iteration keys as ('',) and RepetitionScope's whole
        reason for existing -- making a cross-join detectable -- is undone."""
        from fhir_sulo.engine.driver import _iteration_key

        with self.assertRaises(MaterializationFailure):
            _iteration_key({"v:a": "1"}, ("v:missing",), 0)

    def test_index_is_the_key_when_none_is_declared(self):
        from fhir_sulo.engine.driver import _iteration_key

        self.assertEqual(_iteration_key({"v:a": "1"}, (), 3), ("3",))

    def test_declared_key_variables_are_used(self):
        result = union_passes([bp_pass()])
        self.assertEqual(
            sorted(child.iteration_key for child in result.binding_tree.children),
            [("http://snomed.info/id/271649006",),
             ("http://snomed.info/id/271650006",)],
        )


class TestFrozenContractGap(unittest.TestCase):
    """A hole in the Gate 0 contract, recorded here rather than patched.

    ``TransformResult.__post_init__`` checks lineage coverage only when
    ``lineage`` is already non-empty::

        if self.status is TransformStatus.MAPPED and self.lineage:

    so a MAPPED result carrying quads and *no* lineage at all is accepted and
    reports ``is_loadable`` -- the one case the check exists to stop. The
    one-word fix is to drop ``and self.lineage``, but the four interfaces are
    frozen and changing one needs the integration lead (plan section 6 rule 1),
    so this test pins the current behaviour, proves the driver never relies on
    it, and will fail loudly if the contract is fixed -- which is the signal to
    delete this class.
    """

    def test_the_contract_currently_admits_a_mapped_result_with_no_lineage(self):
        from fhir_sulo.contracts import TransformResult

        result = TransformResult(
            status=TransformStatus.MAPPED, map_id="m", pairing_hash="h",
            source_canonical_url="u", source_version_id="1",
            output_graph_key="k", target_quads=("<a> <b> <c> .",))
        self.assertEqual(result.lineage, ())
        self.assertTrue(result.is_loadable)

    def test_the_driver_never_produces_one(self):
        """Belt and braces: the driver's own gate does not depend on the
        contract's, so closing the contract hole changes nothing here."""
        transform = to_transform_result(
            union_passes([bp_pass()]), map_id="m", pairing_hash="h",
            source_canonical_url=OBS1, source_version_id="1")
        self.assertEqual(len(transform.lineage), len(transform.target_quads))
        self.assertTrue(transform.target_quads)


class TestCombinedBindingTree(unittest.TestCase):
    """A decomposed map's acceptance tuples must be reachable from the one
    binding tree the contract carries, or the check silently inspects only the
    skeleton."""

    def three_passes(self):
        return [
            interpret_pass(_spec("a", "urn:g:p-1#subject"), load_response("decomp-pass-a")),
            interpret_pass(_spec("b1", OBS1, scope="component",
                                 keys=(VAR + "componentValue",)),
                           load_response("decomp-pass-b1")),
            interpret_pass(_spec("b2", OBS2, scope="component",
                                 keys=(VAR + "componentValue",)),
                           load_response("decomp-pass-b2")),
        ]

    def test_every_pass_contributes_its_iterations(self):
        tree = union_passes(self.three_passes()).binding_tree
        tuples = tree.tuples_for_scope("component", [VAR + "componentValue"])
        # bp-1 is {120, 80} and bp-2 is {105, 70}: all four, from both passes
        self.assertEqual(sorted(t[0] for t in tuples), ["105", "120", "70", "80"])

    def test_a_single_pass_tree_is_unchanged(self):
        tree = union_passes([bp_pass()]).binding_tree
        self.assertEqual(len(tree.children), 2)

    def test_the_first_pass_root_is_still_the_root(self):
        tree = union_passes(self.three_passes()).binding_tree
        self.assertEqual(tree.focus, "urn:g:p-1#subject")
