"""The operator path: build an index, see the migration, without writing Python."""

import json
import tempfile
import unittest
from pathlib import Path

from fhir_sulo.identity.cli import allowlist_from_policy, main

BSN = "https://w3id.org/ontostart/fhir2sulo/synthetic/person-number"


def write(root, name, doc):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def patient(rid, value):
    return {"resourceType": "Patient", "id": rid,
            "identifier": [{"system": BSN, "value": value}]}


class TheAllowlistComesFromPolicy(unittest.TestCase):
    def test_it_is_the_interpretable_entries_only(self):
        allowed = allowlist_from_policy()
        self.assertIn(BSN, allowed)
        self.assertNotIn("http://fhir.nl/fhir/NamingSystem/bsn", allowed,
                         "a `proposed` system must not reach the index builder")


class BuildingFromTheCommandLine(unittest.TestCase):
    def test_two_sources_merge_into_one_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "mumc/p.json", patient("123", "900001"))
            write(tmp, "rad/p.json", patient("987", "900001"))
            out = Path(tmp) / "index.json"
            code = main(["build",
                         "--source", "maastricht-umc=%s/mumc" % tmp,
                         "--source", "radboud-umc=%s/rad" % tmp,
                         "--out", str(out)])
            self.assertEqual(code, 0)
            doc = json.loads(out.read_text())
        self.assertEqual(len(doc["entries"]), 2)
        self.assertIn("digest", doc)

    def test_an_index_that_merges_nobody_is_refused_by_default(self):
        """Usually a wrong allowlist, not data without identifiers."""
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "src/o.json", {"resourceType": "Observation", "id": "o1"})
            out = Path(tmp) / "index.json"
            self.assertEqual(
                main(["build", "--source", "s=%s/src" % tmp, "--out", str(out)]), 1)
            self.assertFalse(out.exists())

    def test_it_can_be_written_anyway_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "src/o.json", {"resourceType": "Observation", "id": "o1"})
            out = Path(tmp) / "index.json"
            self.assertEqual(
                main(["build", "--source", "s=%s/src" % tmp, "--out", str(out),
                      "--allow-empty"]), 0)
            self.assertTrue(out.exists())

    def test_a_source_without_a_scope_id_is_rejected(self):
        """The scope id keys the entries; two systems sharing one would merge
        their patients."""
        with self.assertRaises(SystemExit):
            main(["build", "--source", "/just/a/path", "--out", "/tmp/x.json"])


class PlanningTheMigration(unittest.TestCase):
    def test_it_names_the_records_that_collapse(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "mumc/p.json", patient("123", "900001"))
            write(tmp, "rad/p.json", patient("987", "900001"))
            write(tmp, "rad/q.json", patient("555", "900009"))   # different person
            out = Path(tmp) / "index.json"
            main(["build", "--source", "maastricht-umc=%s/mumc" % tmp,
                  "--source", "radboud-umc=%s/rad" % tmp, "--out", str(out)])

            import contextlib
            import io

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(main(["plan", "--index", str(out)]), 0)
            printed = buf.getvalue()

        self.assertIn("collapse into 1 person", printed)
        self.assertIn("Patient/123", printed)
        self.assertIn("Patient/987", printed)
        # 555 is indexed under its own number: it re-keys but merges with nobody.
        self.assertIn("3 entity IRI(s) move", printed)
        self.assertNotIn("Patient/555", printed.split("become ONE person")[-1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
