"""The key triple comes from the reference's TARGET, not from string surgery.

Three false merges found by adversarial review on 2026-10-04, all reachable
through the shipped pipeline and all silent -- status ``mapped``, no note:

1. ``resource_id = ev.resolved_target.rsplit("/", 1)[-1]`` turned
   ``Patient/123/_history/2`` into the id ``"2"``, so a versioned reference
   to patient 123 was attributed to **patient 2**. Not merely a merge: a
   misattribution.
2. An absolute reference to ANOTHER server was keyed in the ingesting
   source's scope, so ``https://radboud.example/fhir/Patient/987`` and the
   local ``Patient/987`` became one person.
3. ``Pipeline.run_file`` ingested for itself with no scope, so DR-014's fix
   reached ``run_context`` and stopped short of the path operators use.

``references.py`` had parsed type, id, version and server base all along and
discarded them into prose. Re-deriving identity by parsing a display string is
the mistake DR-011 already named once.

These are BEHAVIOURAL guards. The source-level one they replace
(``test_no_module_constant_is_used_for_scoping_any_more``) checks for a
substring, and review demonstrated a regression that keeps the substring,
reintroduces the bug, and passes 630 tests.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from fhir_sulo.identity import IdentityService
from fhir_sulo.ingest import ingest_file
from fhir_sulo.pipeline.services import ReferenceNotAPerson, entity_for_reference

REPO = Path(__file__).resolve().parents[3]
BASE = json.loads((REPO / "fixtures/r4/egfr/egfr-baseline/egfr-456.json").read_text())


def person_iri(reference, scope_id="mumc-r4"):
    doc = dict(BASE)
    doc["subject"] = {"reference": reference}
    path = os.path.join(tempfile.mkdtemp(), "o.json")
    Path(path).write_text(json.dumps(doc), encoding="utf-8")
    context = ingest_file(path, source_scope_id=scope_id)
    return entity_for_reference(
        IdentityService(), context, "Observation.subject", "Patient").entity_iri


class AVersionedReferenceNamesThePersonNotTheVersion(unittest.TestCase):
    def test_it_is_the_same_person_as_the_unversioned_reference(self):
        """A record version does not make a new person."""
        self.assertEqual(person_iri("Patient/123/_history/2"), person_iri("Patient/123"))

    def test_it_is_not_the_patient_whose_id_equals_the_version(self):
        """The defect: Patient/123/_history/2 resolved to patient "2"."""
        self.assertNotEqual(person_iri("Patient/123/_history/2"), person_iri("Patient/2"))

    def test_two_versions_of_one_patient_are_one_person(self):
        self.assertEqual(person_iri("Patient/123/_history/1"),
                         person_iri("Patient/123/_history/7"))

    def test_the_version_is_kept_as_lineage(self):
        doc = dict(BASE)
        doc["subject"] = {"reference": "Patient/123/_history/2"}
        path = os.path.join(tempfile.mkdtemp(), "o.json")
        Path(path).write_text(json.dumps(doc), encoding="utf-8")
        context = ingest_file(path, source_scope_id="mumc-r4")
        evidence = context.resolved_references["Observation.subject"].evidence
        self.assertEqual(evidence.target_version_id, "2")
        self.assertEqual(evidence.target_resource_id, "123")


class AReferenceIntoAnotherServerIsRefused(unittest.TestCase):
    def test_it_does_not_key_in_the_ingesting_sources_scope(self):
        """Keying it locally asserts their Patient/987 and ours are one
        person -- the unrecorded cross-source merge the policy refuses."""
        with self.assertRaises(ReferenceNotAPerson) as caught:
            person_iri("https://radboud.example/fhir/Patient/987")
        self.assertEqual(caught.exception.reason_code, "cross-server-reference-unscoped")

    def test_a_reference_to_the_pinned_server_still_resolves(self):
        """The guard must not refuse ordinary absolute references."""
        self.assertEqual(person_iri("https://fhir.example/Patient/987"),
                         person_iri("Patient/987"))


class RunFileHonoursThePipelinesScope(unittest.TestCase):
    """Behavioural, through the entry point operators actually use."""

    def _scope(self, path, scope_id):
        from fhir_sulo.pipeline.services import source_context

        return source_context(Path(path), source_scope_id=scope_id).source_scope_id

    def test_two_sources_do_not_collapse_through_the_run_file_path(self):
        a = self._scope("fixtures/multi-source/mumc-r4/Observation-egfr-a.json", "mumc-r4")
        b = self._scope("fixtures/multi-source/radboud-r4/Observation-egfr-b.json",
                        "radboud-r4")
        self.assertNotEqual(a, b)

    def test_the_pipeline_carries_the_scope_to_run_file(self):
        import inspect

        from fhir_sulo.pipeline.compose import Pipeline

        self.assertIn("source_scope_id", inspect.signature(Pipeline.for_family).parameters)
        body = inspect.getsource(Pipeline.run_file)
        self.assertIn("source_scope_id=self.source_scope_id", body)

    def test_the_operator_cli_can_set_the_scope_and_the_index(self):
        """Without these the only cross-system rule can never fire from the
        operator path, and two hospitals' Patient/123 stay one person."""
        import argparse
        import contextlib
        import io

        from fhir_sulo.pipeline.cli import main

        for sub in ("map", "batch"):
            with self.subTest(subcommand=sub):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
                    main([sub, "--help"])
                printed = buf.getvalue()
                self.assertIn("--source-scope", printed)
                self.assertIn("--person-index", printed)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ContainedResourcesAreNotLookedUpInTheIndex(unittest.TestCase):
    """DR-020. A contained resource has no existence outside its container.

    The index lookup used the raw scope and raw resource id, not the
    effective container-scoped key the service uses everywhere else, so a
    contained ``#p-inline`` matched a TOP-LEVEL ``Patient/p-inline`` and the
    two fused -- on a coincidence of ids, not on evidence.
    """

    SYN = "https://w3id.org/ontostart/fhir2sulo/synthetic/person-number"

    def _service(self):
        from fhir_sulo.identity.person_index import PersonIdentifierIndex

        index = PersonIdentifierIndex.build(
            [{"resourceType": "Patient", "id": "p-inline",
              "identifier": [{"system": self.SYN, "value": "900001"}]}],
            scope_id="mumc", allowlist=[self.SYN])
        return IdentityService(person_index=index)

    def _resolve(self, kind, container=None):
        from fhir_sulo.identity import IdentityRequest, ReferenceEvidence, SourceScope

        evidence = ReferenceEvidence(
            evidence_id="e", kind=kind,
            source_scope=SourceScope("mumc", "https://mumc.example/fhir/"),
            resource_type="Patient", resource_id="p-inline", container_url=container)
        outcome = self._service().resolve(
            IdentityRequest("ref", ("Patient",), (evidence,), entity_kind="person"))
        self.assertTrue(outcome.is_resolved, getattr(outcome, "reason", None))
        return outcome.unwrap()

    def test_a_contained_resource_does_not_fuse_with_a_top_level_record(self):
        top = self._resolve("literal-reference")
        contained = self._resolve("contained", "https://mumc.example/fhir/Observation/o1")
        self.assertNotEqual(top.entity_iri, contained.entity_iri)

    def test_the_contained_one_keys_under_its_container(self):
        contained = self._resolve("contained", "https://mumc.example/fhir/Observation/o1")
        self.assertEqual(contained.rule_id, "ID-R8-contained-scoped-to-its-container")

    def test_the_top_level_one_still_keys_on_the_identifier(self):
        """The fix must not switch the index off for records it does cover."""
        self.assertEqual(self._resolve("literal-reference").rule_id,
                         "ID-R12-identifier-keyed-person")


class TheCanonicalUrlNamesTheSourceItCameFrom(unittest.TestCase):
    """DR-020. It was built from the PINNED manifest's base, so every source
    produced the same URL for one resource id -- and that URL is a graph key
    input and the replacement slot."""

    def _url(self, path, **kw):
        return ingest_file(path, **kw).canonical_url

    def test_two_sources_give_two_canonical_urls(self):
        a = self._url("fixtures/multi-source/mumc-r4/Observation-egfr-a.json",
                      source_scope_id="mumc-r4", fhir_base_url="https://mumc.example/fhir/")
        b = self._url("fixtures/multi-source/radboud-r4/Observation-egfr-b.json",
                      source_scope_id="radboud-r4",
                      fhir_base_url="https://radboud.example/fhir/")
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith("https://mumc.example/fhir/"), a)

    def test_the_default_is_the_pinned_base_so_nothing_re_keys(self):
        self.assertTrue(
            self._url("fixtures/multi-source/mumc-r4/Observation-egfr-a.json")
            .startswith("https://fhir.example/"))

    def test_the_operator_cli_can_set_it(self):
        import contextlib
        import io

        from fhir_sulo.pipeline.cli import main

        for sub in ("map", "batch"):
            with self.subTest(subcommand=sub):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
                    main([sub, "--help"])
                self.assertIn("--fhir-base", buf.getvalue())
