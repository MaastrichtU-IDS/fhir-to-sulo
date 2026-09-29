"""The deterministic output graph key. DR-601.

The property that matters is not "the function returns a string": it is that
the *same inputs* give the *same key in a different process*, and that the key
can be recomputed from an archived run record years later. Both are asserted
here, the first by actually starting subprocesses with different hash seeds.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest

from . import support  # noqa: F401  (sets sys.path)

from fhir_sulo.store import (
    CONTENT_FIELDS,
    EXCLUDED_RUN_RECORD_FIELDS,
    SUBJECT_FIELDS,
    GraphKeyError,
    GraphKeyInputs,
    graph_key,
    graph_key_from_run_record,
    subject_key,
    subject_key_from_run_record,
    subject_of,
)
from fhir_sulo.contracts import RunRecord


def _inputs(**overrides) -> GraphKeyInputs:
    base = dict(
        source_canonical_url="https://fhir.example/Observation/egfr-456",
        source_version_id="1",
        source_json_digest="sha256:v1",
        map_id="egfr-r4",
        map_semantic_version="0.1.0",
        pairing_hash="sha256:pairing-aaaa",
        sulo_version="0.2.12",
        domain_ontology_version="unresolved:R1",
        terminology_snapshot="tx-2026-09-29",
        policy_version="unresolved:R2",
        engine_build="shex@1.0.0-alpha.33",
        renderer_id="fhir_sulo.ingest.fhir_rdf/0.1.0",
        contract_version="0.1.0",
    )
    base.update(overrides)
    return GraphKeyInputs(**base)


class GraphKeyDeterminism(unittest.TestCase):
    def test_same_inputs_same_key(self):
        self.assertEqual(graph_key(_inputs()), graph_key(_inputs()))

    def test_key_is_stable_across_processes_with_different_hash_seeds(self):
        """The one that actually catches ``hash()``.

        ``PYTHONHASHSEED`` changes the value of the builtin ``hash`` between
        processes. If any part of the key derivation ever reached for it - via
        a set iteration order, say - these two subprocesses would disagree.
        Calling the function twice in one process would not notice.
        """
        script = (
            "import sys; sys.path.insert(0, %r);"
            "from fhir_sulo.store import graph_key, GraphKeyInputs;"
            "print(graph_key(GraphKeyInputs(%s)))"
            % (
                support.SRC,
                ", ".join(
                    "%s=%r" % (name, getattr(_inputs(), name)) for name in CONTENT_FIELDS
                ),
            )
        )
        keys = []
        for seed in ("0", "1", "12345"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            proc = subprocess.run(
                [sys.executable, "-c", script], capture_output=True, text=True, env=env
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            keys.append(proc.stdout.strip())
        self.assertEqual(len(set(keys)), 1, "key varied with PYTHONHASHSEED: %s" % keys)
        self.assertEqual(keys[0], graph_key(_inputs()))

    def test_no_module_in_the_store_or_provenance_calls_builtin_hash(self):
        """Parsed, not grepped: a docstring saying "hash()" is not a call."""
        offenders = []
        for package in ("store", "provenance"):
            directory = os.path.join(support.SRC, "fhir_sulo", package)
            for name in sorted(os.listdir(directory)):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(directory, name)
                with open(path, encoding="utf-8") as handle:
                    tree = ast.parse(handle.read(), filename=path)
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "hash"
                    ):
                        offenders.append("%s/%s:%d" % (package, name, node.lineno))
        self.assertEqual(
            offenders, [], "builtin hash() is salted per process and must not reach a key"
        )

    def test_key_does_not_depend_on_wall_clock_or_field_order(self):
        forward = _inputs()
        shuffled = GraphKeyInputs(
            **{name: getattr(forward, name) for name in reversed(CONTENT_FIELDS)}
        )
        self.assertEqual(graph_key(forward), graph_key(shuffled))


class GraphKeyCoverage(unittest.TestCase):
    def test_every_content_field_changes_the_key(self):
        """If a field is in the key spec it must actually be in the key.

        A field listed in ``CONTENT_FIELDS`` but silently dropped from the
        hash would mean two different graphs sharing one key, which the store
        detects only later and only by accident.
        """
        base = graph_key(_inputs())
        for field in CONTENT_FIELDS:
            with self.subTest(field=field):
                changed = graph_key(_inputs(**{field: "CHANGED"}))
                self.assertNotEqual(base, changed, "%s does not affect the key" % field)

    def test_version_change_changes_the_graph_key_but_not_the_subject_key(self):
        """The reason there are two keys at all.

        Version 2 must be a *different graph* - otherwise version 1's lineage
        is overwritten - while occupying the *same replacement slot* -
        otherwise nothing tells the store that it supersedes version 1.
        """
        v1, v2 = _inputs(source_version_id="1"), _inputs(source_version_id="2",
                                                  source_json_digest="sha256:v2")
        self.assertNotEqual(graph_key(v1), graph_key(v2))
        self.assertEqual(subject_key(v1), subject_key(v2))

    def test_subject_key_separates_resources_and_maps(self):
        base = subject_key(_inputs())
        self.assertNotEqual(
            base, subject_key(_inputs(source_canonical_url="https://fhir.example/Observation/x"))
        )
        self.assertNotEqual(base, subject_key(_inputs(map_id="bp-r4")))

    def test_subject_is_recoverable_from_the_graph_key_without_rehashing(self):
        inputs = _inputs()
        self.assertEqual(subject_of(graph_key(inputs)), subject_key(inputs))

    def test_subject_fields_are_a_subset_of_content_fields(self):
        self.assertTrue(set(SUBJECT_FIELDS) <= set(CONTENT_FIELDS))

    def test_run_outcome_fields_are_excluded_from_the_key(self):
        """A key computed from an outcome cannot be computed before the run.

        The whole value of a deterministic key is being able to ask "do I
        already have this graph?" *before* producing it.
        """
        overlap = set(EXCLUDED_RUN_RECORD_FIELDS) & set(CONTENT_FIELDS)
        self.assertEqual(overlap, set())
        for excluded in ("run_id", "activity_time", "output_digest",
                         "validation_report_digest"):
            self.assertIn(excluded, EXCLUDED_RUN_RECORD_FIELDS)


class GraphKeyInputValidation(unittest.TestCase):
    def test_empty_field_is_refused_rather_than_hashed(self):
        for field in CONTENT_FIELDS:
            with self.subTest(field=field):
                with self.assertRaises(GraphKeyError):
                    _inputs(**{field: ""})

    def test_undecided_policy_must_be_an_explicit_token(self):
        """An open review item is recorded, not blanked.

        ``"unresolved:R1"`` and a real ontology version hash differently, so a
        graph produced while R1 was open can never be mistaken for one
        produced after it was answered.
        """
        open_item = graph_key(_inputs(domain_ontology_version="unresolved:R1"))
        answered = graph_key(_inputs(domain_ontology_version="fhir-sulo-domain/1.0.0"))
        self.assertNotEqual(open_item, answered)

    def test_whitespace_only_field_is_refused(self):
        with self.assertRaises(GraphKeyError):
            _inputs(policy_version="   ")


class RecomputableFromTheRunRecord(unittest.TestCase):
    """The invariant the correction audit trail rests on."""

    def _record(self, **overrides):
        inputs = _inputs(**overrides)
        return RunRecord(
            run_id="run-1",
            activity_time="2026-09-29T10:00:00Z",
            output_graph_key=graph_key(inputs),
            output_digest="sha256:out",
            validation_report_digest="sha256:val",
            transform_status="mapped",
            **{name: getattr(inputs, name) for name in CONTENT_FIELDS},
        )

    def test_key_recomputes_from_an_archived_record(self):
        record = self._record()
        self.assertEqual(graph_key_from_run_record(record), record.output_graph_key)

    def test_subject_recomputes_from_an_archived_record(self):
        record = self._record()
        self.assertEqual(
            subject_key_from_run_record(record), subject_of(record.output_graph_key)
        )

    def test_a_record_whose_key_does_not_match_its_fields_is_detectable(self):
        record = self._record()
        tampered = RunRecord(
            **{
                **{f.name: getattr(record, f.name) for f in record.__dataclass_fields__.values()},
                "source_version_id": "99",
            }
        )
        self.assertNotEqual(graph_key_from_run_record(tampered), tampered.output_graph_key)


if __name__ == "__main__":
    unittest.main()
