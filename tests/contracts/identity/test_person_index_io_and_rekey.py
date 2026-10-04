"""Getting the index from real sources, and seeing the migration first.

Two things DR-015 left open and this closes: where the index comes from in a
real run, and how anyone finds out what enabling it would do before they do it.
"""

import json
import tempfile
import unittest
from pathlib import Path

from fhir_sulo.identity.person_index import (
    PersonIdentifierConflict,
    PersonIdentifierIndex,
)
from fhir_sulo.identity.rekey_report import plan_rekey

BSN = "https://w3id.org/ontostart/fhir2sulo/synthetic/person-number"
MUMC = ("maastricht-umc", "https://mumc.example/fhir/")
RAD = ("radboud-umc", "https://radboud.example/fhir/")


def patient(rid, value="900001"):
    return {"resourceType": "Patient", "id": rid,
            "identifier": [{"system": BSN, "value": value}]}


def bundle(*resources):
    return {"resourceType": "Bundle", "type": "collection",
            "entry": [{"resource": r} for r in resources]}


class LoadingFromRealSources(unittest.TestCase):
    def test_a_bundle_is_indexed(self):
        idx = PersonIdentifierIndex.from_bundle(
            bundle(patient("123"), {"resourceType": "Observation", "id": "o1"}),
            scope_id="maastricht-umc", allowlist=[BSN])
        self.assertEqual(len(idx), 1)

    def test_a_bundle_of_no_person_resources_is_empty_not_an_error(self):
        idx = PersonIdentifierIndex.from_bundle(
            bundle({"resourceType": "Observation", "id": "o1"}),
            scope_id="s", allowlist=[BSN])
        self.assertEqual(len(idx), 0)

    def test_something_that_is_not_a_bundle_is_refused(self):
        with self.assertRaises(ValueError):
            PersonIdentifierIndex.from_bundle(patient("123"), scope_id="s", allowlist=[BSN])

    def test_a_directory_of_resources_and_bundles_is_indexed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "p1.json").write_text(json.dumps(patient("123")))
            (root / "nested").mkdir()
            (root / "nested" / "b.json").write_text(
                json.dumps(bundle(patient("456", "900002"))))
            idx = PersonIdentifierIndex.from_directory(
                root, scope_id="maastricht-umc", allowlist=[BSN])
        self.assertEqual(len(idx), 2)

    def test_an_unreadable_file_raises_rather_than_being_skipped(self):
        """An under-populated index does not fail -- it stops reunifying
        people, invisibly. So a file we cannot read is an error."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "p1.json").write_text(json.dumps(patient("123")))
            (root / "broken.json").write_text("{not json")
            with self.assertRaises(ValueError):
                PersonIdentifierIndex.from_directory(root, scope_id="s", allowlist=[BSN])

    def test_directory_order_does_not_change_the_digest(self):
        digests = set()
        for names in (("a.json", "b.json"), ("b.json", "a.json")):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name, rid in zip(names, ("123", "456")):
                    (root / name).write_text(json.dumps(patient(rid, rid)))
                digests.add(PersonIdentifierIndex.from_directory(
                    root, scope_id="s", allowlist=[BSN]).digest)
        self.assertEqual(len(digests), 1)


class TheIndexRoundTrips(unittest.TestCase):
    def test_save_then_load_preserves_the_entries_and_digest(self):
        idx = PersonIdentifierIndex.build([patient("123")], scope_id="s", allowlist=[BSN])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            written = idx.save(path)
            back = PersonIdentifierIndex.load(path)
        self.assertEqual(written, idx.digest)
        self.assertEqual(back.digest, idx.digest)
        self.assertEqual(back.lookup("s", "Patient", "123"), (BSN, "900001"))

    def test_an_edited_index_is_refused_on_load(self):
        """An index decides which records are one person. An untracked edit
        silently re-keys entities, so the digest is checked, not trusted."""
        idx = PersonIdentifierIndex.build([patient("123")], scope_id="s", allowlist=[BSN])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            idx.save(path)
            doc = json.loads(path.read_text())
            doc["entries"][0]["identifier_value"] = "tampered"
            path.write_text(json.dumps(doc))
            with self.assertRaises(ValueError) as caught:
                PersonIdentifierIndex.load(path)
        self.assertIn("edited", str(caught.exception))


class TheMigrationIsVisibleBeforeItHappens(unittest.TestCase):
    def _index(self):
        return PersonIdentifierIndex.build(
            [patient("123")], scope_id="maastricht-umc", allowlist=[BSN]).merged_with(
            PersonIdentifierIndex.build(
                [patient("987")], scope_id="radboud-umc", allowlist=[BSN]))

    def _records(self):
        return [
            (MUMC[0], MUMC[1], "Patient", "123"),
            (RAD[0], RAD[1], "Patient", "987"),
            (RAD[0], RAD[1], "Patient", "555"),   # not indexed
        ]

    def test_it_reports_which_iris_move(self):
        report = plan_rekey(self._records(), self._index())
        self.assertEqual(len(report.rows), 3)
        self.assertEqual(len(report.moved), 2)

    def test_it_names_the_records_that_become_one_person(self):
        """The part a reviewer reads: every entry here is a claim that two
        records describe one human."""
        merges = plan_rekey(self._records(), self._index()).merges
        self.assertEqual(len(merges), 1)
        (rows,) = merges.values()
        self.assertEqual(
            sorted((r.source_scope_id, r.resource_id) for r in rows),
            [("maastricht-umc", "123"), ("radboud-umc", "987")])

    def test_an_unindexed_record_does_not_move(self):
        report = plan_rekey(self._records(), self._index())
        untouched = [r for r in report.rows if r.resource_id == "555"]
        self.assertEqual(len(untouched), 1)
        self.assertFalse(untouched[0].moved)

    def test_an_empty_index_moves_nothing(self):
        report = plan_rekey(self._records(), PersonIdentifierIndex.empty())
        self.assertEqual(report.moved, [])
        self.assertEqual(report.merges, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)


class AliasedSystemsIndexUnderOneSpelling(unittest.TestCase):
    """DR-017. The index builder must canonicalise too.

    If it indexed a record under whichever spelling arrived, a hospital
    sending the urn:oid: form and one sending the fhir.nl URI would land under
    different keys and never match -- the exact silent miss the aliasing
    exists to stop, just moved one layer down.
    """

    URI = "http://fhir.nl/fhir/NamingSystem/bsn"
    OID = "urn:oid:2.16.840.1.113883.2.4.6.3"

    def _canonical_map(self):
        return {self.URI: self.URI, self.OID: self.URI}

    def test_both_spellings_index_under_the_canonical_one(self):
        fhir_native = {"resourceType": "Patient", "id": "123",
                       "identifier": [{"system": self.URI, "value": "900001"}]}
        v2_derived = {"resourceType": "Patient", "id": "987",
                      "identifier": [{"system": self.OID, "value": "900001"}]}
        a = PersonIdentifierIndex.build([fhir_native], scope_id="mumc",
                                        allowlist=self._canonical_map())
        b = PersonIdentifierIndex.build([v2_derived], scope_id="rad",
                                        allowlist=self._canonical_map())
        self.assertEqual(a.lookup("mumc", "Patient", "123"),
                         b.lookup("rad", "Patient", "987"))
        self.assertEqual(a.lookup("mumc", "Patient", "123")[0], self.URI)

    def test_a_plain_list_allowlist_still_works(self):
        """The simple form stays valid; aliasing is opt-in per entry."""
        built = PersonIdentifierIndex.build(
            [{"resourceType": "Patient", "id": "1",
              "identifier": [{"system": BSN, "value": "9"}]}],
            scope_id="s", allowlist=[BSN])
        self.assertEqual(len(built), 1)

    def test_the_cli_hands_the_builder_a_canonical_map(self):
        from fhir_sulo.identity.cli import allowlist_from_policy

        self.assertIsInstance(allowlist_from_policy(), dict)


class ConflictsRaiseWhereverTheyOccur(unittest.TestCase):
    """DR-015 says a disagreement about one record raises. Review found that
    was true ACROSS files and untested, and false WITHIN one file: ``build``
    did ``out[key] = ...`` so the last entry silently won.
    """

    def _patient(self, value):
        return {"resourceType": "Patient", "id": "123",
                "identifier": [{"system": BSN, "value": value}]}

    def test_two_entries_for_one_record_in_one_bundle_raise(self):
        doc = {"resourceType": "Bundle",
               "entry": [{"resource": self._patient("900001")},
                         {"resource": self._patient("900002")}]}
        with self.assertRaises(PersonIdentifierConflict):
            PersonIdentifierIndex.from_bundle(doc, scope_id="s", allowlist=[BSN])

    def test_an_agreeing_duplicate_is_not_a_conflict(self):
        """Two copies saying the same thing are not a disagreement."""
        doc = {"resourceType": "Bundle",
               "entry": [{"resource": self._patient("900001")},
                         {"resource": self._patient("900001")}]}
        built = PersonIdentifierIndex.from_bundle(doc, scope_id="s", allowlist=[BSN])
        self.assertEqual(len(built), 1)

    def test_two_indexes_disagreeing_on_merge_raise(self):
        """Stated by DR-015 and, until now, pinned by nothing: review deleted
        the raise entirely and 637 tests still passed."""
        a = PersonIdentifierIndex.build([self._patient("900001")],
                                        scope_id="s", allowlist=[BSN])
        b = PersonIdentifierIndex.build([self._patient("900002")],
                                        scope_id="s", allowlist=[BSN])
        with self.assertRaises(PersonIdentifierConflict):
            a.merged_with(b)

    def test_merging_agreeing_indexes_is_fine(self):
        a = PersonIdentifierIndex.build([self._patient("900001")],
                                        scope_id="s", allowlist=[BSN])
        self.assertEqual(len(a.merged_with(a)), 1)

    def test_an_index_with_no_digest_is_refused(self):
        """`if recorded and ...` skipped verification when the field was
        absent, so a hand-written index bypassed the check DR-015 promises."""
        import json

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "i.json"
            path.write_text(json.dumps({"format": "x", "entries": []}))
            with self.assertRaises(ValueError) as caught:
                PersonIdentifierIndex.load(path)
        self.assertIn("no `digest`", str(caught.exception))
