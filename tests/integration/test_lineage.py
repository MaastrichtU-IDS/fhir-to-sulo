"""Per-quad lineage. Acceptance matrix row "Lineage".

    Every quad traces to a source binding/constant plus source resource
    version, map hash, and run activity.

The per-quad half comes from the engine; the per-run half from the run record.
These tests check the join, and - more importantly - check that every way the
engine payload can be wrong is a hard failure rather than a gap.
"""

from __future__ import annotations

import unittest

from .support import EX, QUADS_V1, fake_engine_payload, mapped_pair, run_inputs  # noqa: F401

from fhir_sulo.contracts import TransformResult, TransformStatus
from fhir_sulo.provenance import (
    LineageError,
    UntracedQuadError,
    build_lineage,
    build_transform_result,
    from_engine_payload,
    lineage_report,
    result_lineage_report,
)

T1 = "2026-09-29T10:00:00Z"

# A deliberately tiny two-quad graph for the unit tests below.
#
# These exercise the lineage BUILDER - array lengths, ordering, missing
# sources - not map output, and each assertion names the quad at a specific
# index. ``support.QUADS_V1`` is the real 21-triple emitted eGFR graph, used
# by the correction tests; reusing it here would make "the entry at index 1"
# mean something different every time Agent 3 touches the map.
PAIR = (
    "<%segfr-result-egfr-456> <https://w3id.org/sulo/hasValue> "
    '"55.0"^^<http://www.w3.org/2001/XMLSchema#decimal> .' % EX,
    "<%segfr-result-egfr-456> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
    "<https://w3id.org/sulo/Quantity> ." % EX,
)


class EnginePayloadParsing(unittest.TestCase):
    def test_camel_and_snake_case_are_both_accepted(self):
        """The payload crosses a JS/Python boundary; the driver may do either."""
        camel = from_engine_payload(
            {
                "quads": ["<a> <b> <c> ."],
                "provenance": [
                    {"quad": "<a> <b> <c> .", "tc": "T", "src": "v:x", "frameIndex": 0}
                ],
                "frameOrigins": [{"frameIndex": 0, "scope": "s", "keyValues": ["k"]}],
            }
        )
        snake = from_engine_payload(
            {
                "quads": ["<a> <b> <c> ."],
                "provenance": [
                    {"quad": "<a> <b> <c> .", "triple_constraint": "T",
                     "source": "v:x", "frame_index": 0}
                ],
                "frame_origins": [{"frame_index": 0, "scope": "s", "key_values": ["k"]}],
            }
        )
        self.assertEqual(camel, snake)


class LineageConstruction(unittest.TestCase):
    def test_a_bound_variable_is_recorded_as_a_source_variable(self):
        payload = fake_engine_payload(PAIR, variables=["egfr:value", "egfr:unitCode"])
        lineage = build_lineage(payload, pivot_variables=["egfr:value", "egfr:unitCode"])
        self.assertEqual([item.source_variable for item in lineage],
                         ["egfr:value", "egfr:unitCode"])

    def test_a_constant_is_recorded_as_a_constraint_not_a_variable(self):
        """A constant written into the target schema is lineage, but it is not
        a value that came from the patient's record, and the two must not be
        confusable in an audit."""
        payload = fake_engine_payload(PAIR, variables=["egfr:value"])
        lineage = build_lineage(payload, pivot_variables=["egfr:value"])
        self.assertEqual(lineage[0].source_variable, "egfr:value")
        self.assertIsNone(lineage[1].source_variable)
        self.assertIsNotNone(lineage[1].source_constraint)

    def test_iteration_key_is_carried_through_from_the_frame_origin(self):
        payload = fake_engine_payload(PAIR, variables=["egfr:value"], key=("bp-1",))
        lineage = build_lineage(payload)
        for item in lineage:
            self.assertEqual(item.iteration_key, ("bp-1",))

    def test_every_quad_index_is_covered_exactly_once(self):
        payload = fake_engine_payload(PAIR, variables=["egfr:value"])
        lineage = build_lineage(payload)
        self.assertEqual(sorted(i.quad_index for i in lineage), list(range(len(PAIR))))


class LineageFailsLoudly(unittest.TestCase):
    """Every one of these would otherwise reach TransformResult as a mystery."""

    def test_a_short_provenance_array_is_an_error(self):
        payload = from_engine_payload(
            {
                "quads": list(PAIR),
                "provenance": [{"quad": PAIR[0], "tc": "T", "src": "v:x"}],
            }
        )
        with self.assertRaises(LineageError) as caught:
            build_lineage(payload)
        self.assertIn("parallel to the emitted quads", str(caught.exception))

    def test_a_reordered_provenance_array_is_an_error(self):
        payload = from_engine_payload(
            {
                "quads": list(PAIR),
                "provenance": [
                    {"quad": PAIR[1], "tc": "T1", "src": "v:x"},
                    {"quad": PAIR[0], "tc": "T0", "src": "v:y"},
                ],
            }
        )
        with self.assertRaises(LineageError) as caught:
            build_lineage(payload)
        self.assertIn("parallel ordering", str(caught.exception))

    def test_a_quad_with_neither_binding_nor_constraint_is_an_error(self):
        payload = from_engine_payload(
            {
                "quads": [PAIR[0]],
                "provenance": [{"quad": PAIR[0], "predicate": "p"}],
            }
        )
        with self.assertRaises(UntracedQuadError) as caught:
            build_lineage(payload)
        self.assertIn("may not enter a clinical semantic graph", str(caught.exception))


class TransformResultRefusesUntracedOutput(unittest.TestCase):
    """The frozen contract's own guard, exercised from this side."""

    def test_a_mapped_result_with_partial_lineage_cannot_be_constructed(self):
        payload = fake_engine_payload(PAIR, variables=["egfr:value"])
        full = build_lineage(payload)
        with self.assertRaises(ValueError) as caught:
            TransformResult(
                status=TransformStatus.MAPPED,
                map_id="egfr-r4",
                pairing_hash="h",
                source_canonical_url="u",
                source_version_id="1",
                output_graph_key="k",
                target_quads=PAIR,
                lineage=full[:1],
            )
        self.assertIn("no lineage", str(caught.exception))

    def test_build_transform_result_refuses_a_mapped_result_with_no_payload(self):
        with self.assertRaises(ValueError) as caught:
            build_transform_result(run_inputs(), status=TransformStatus.MAPPED)
        self.assertIn("engine lineage payload", str(caught.exception))

    def test_build_transform_result_refuses_quads_on_a_non_mapped_status(self):
        payload = fake_engine_payload(PAIR, variables=["egfr:value"])
        with self.assertRaises(ValueError) as caught:
            build_transform_result(
                run_inputs(), status=TransformStatus.SOURCE_ONLY, engine_payload=payload
            )
        self.assertIn("only mapped output", str(caught.exception))


class LineageReportJoinsPerQuadToPerRun(unittest.TestCase):
    def setUp(self):
        self.inputs = run_inputs()
        self.result, self.record = mapped_pair(self.inputs, QUADS_V1, activity_time=T1)
        self.report = result_lineage_report(self.result, self.record)

    def test_the_report_carries_the_per_run_half(self):
        """"plus source resource version, map hash, and run activity"."""
        self.assertEqual(self.report["source_version_id"], "1")
        self.assertEqual(self.report["pairing_hash"], "sha256:pairing-aaaa")
        self.assertEqual(self.report["run_id"], self.record.run_id)
        self.assertEqual(self.report["output_graph_key"], self.record.output_graph_key)

    def test_the_report_carries_every_quad_with_its_producer(self):
        self.assertEqual(len(self.report["quads"]), len(self.result.target_quads))
        for entry in self.report["quads"]:
            self.assertTrue(entry["produced_by"])
            self.assertTrue(entry["source_variable"] or entry["source_constraint"])

    def test_the_report_is_deterministic(self):
        again = result_lineage_report(self.result, self.record)
        self.assertEqual(self.report, again)

    def test_a_report_whose_length_disagrees_with_the_quads_is_an_error(self):
        with self.assertRaises(LineageError):
            lineage_report(self.result.lineage[:1], self.result.target_quads, self.record)


if __name__ == "__main__":
    unittest.main()
