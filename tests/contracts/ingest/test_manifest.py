"""The pinned profile manifest parses, is self-consistent, and is actually used.

Plan Gate 0 pass condition: "the manifest parses ... every required field has
an explicit source, target, or rejection rule."
"""

from __future__ import annotations

import json
import os
import re
import unittest

from . import _support
from ._support import FIXTURES, ROOT, cases, read

from fhir_sulo.ingest import default_manifest  # noqa: E402
from fhir_sulo.ingest.manifest import ELEMENT_TABLE_PATH, MANIFEST_PATH, Manifest  # noqa: E402

PROFILES = os.path.join(ROOT, "profiles")


class TestManifestParses(unittest.TestCase):
    def test_every_profiles_json_parses(self):
        found = 0
        for name in sorted(os.listdir(PROFILES)):
            if name.endswith(".json"):
                with self.subTest(file=name):
                    json.loads(read(os.path.join(PROFILES, name)))
                    found += 1
        self.assertGreaterEqual(found, 2)

    def test_manifest_loads_and_validates(self):
        m = Manifest.load(MANIFEST_PATH, ELEMENT_TABLE_PATH)
        self.assertEqual(m.fhir_release, "4.0.1")
        self.assertEqual(sorted(m.supported_resource_types()),
                         ["Encounter", "Observation"])


class TestPins(unittest.TestCase):
    def setUp(self):
        self.m = default_manifest()

    def test_the_three_loinc_codes_are_pinned(self):
        for code in ("33914-3", "8480-6", "8462-4"):
            self.assertTrue(self.m.is_pinned_code("http://loinc.org", code), code)

    def test_the_two_ucum_codes_are_pinned(self):
        for code in ("mL/min/{1.73_m2}", "mm[Hg]"):
            self.assertTrue(
                self.m.is_pinned_unit("http://unitsofmeasure.org", code), code)

    def test_an_unpinned_code_is_not_silently_accepted(self):
        self.assertFalse(self.m.is_pinned_code("http://loinc.org", "48642-3"))
        self.assertFalse(self.m.is_pinned_unit("http://unitsofmeasure.org", "mL/min"))
        self.assertFalse(self.m.is_pinned_unit(None, None))

    def test_profiles_are_pinned_with_a_role(self):
        for rtype in self.m.supported_resource_types():
            validated = self.m.validated_profiles(rtype)
            self.assertTrue(validated, f"{rtype} has no validated profile")
            for canonical in validated:
                self.assertTrue(canonical.startswith("http://hl7.org/fhir/"))

    def test_renderer_declares_determinism_and_no_network(self):
        r = self.m.data["renderer"]
        self.assertTrue(r["deterministic"])
        self.assertFalse(r["network_at_runtime"])
        self.assertTrue(re.match(r"^\S+/\d+\.\d+\.\d+$", r["renderer_id"]))
        self.assertTrue(os.path.exists(os.path.join(ROOT, r["decision_record"])))

    def test_terminology_class_assertions_are_off_by_default(self):
        """Concept note section 2: a FHIR code literal alone is not an OWL
        class assertion."""
        self.assertFalse(self.m.renderer_options["emit_code_system_class_assertions"])


class TestScopeIsComplete(unittest.TestCase):
    def setUp(self):
        self.m = default_manifest()

    def test_every_in_scope_element_exists_in_the_element_table(self):
        for rtype in self.m.supported_resource_types():
            for path in self.m.in_scope_elements(rtype):
                with self.subTest(element=path):
                    self._assert_path_known(path)

    def test_every_source_only_element_exists_in_the_element_table(self):
        for rtype in self.m.supported_resource_types():
            for path in self.m.source_only_elements(rtype):
                with self.subTest(element=path):
                    self._assert_path_known(path)

    def _assert_path_known(self, path):
        parts = path.split(".")
        type_name = parts[0]
        for i, name in enumerate(parts[1:]):
            ed = self.m.element_def(type_name, name)
            if i == len(parts) - 2:
                return
            type_name = ed["type"]
            if type_name == "#resource":
                return

    def test_every_status_in_the_policy_is_a_real_r4_status(self):
        r4 = {
            "Observation": {"registered", "preliminary", "final", "amended",
                            "corrected", "cancelled", "entered-in-error", "unknown"},
            "Encounter": {"planned", "arrived", "triaged", "in-progress", "onleave",
                          "finished", "cancelled", "entered-in-error", "unknown"},
        }
        for rtype, allowed in r4.items():
            declared = set(self.m.data["status_policy"][rtype])
            self.assertEqual(declared, allowed,
                             f"{rtype} status policy does not cover exactly the R4 value set")

    def test_ingest_package_imports_nothing_that_can_reach_a_network(self):
        """DR-101 claims 'no hidden network calls at run time'. Make it checkable."""
        src = os.path.join(ROOT, "src", "fhir_sulo", "ingest")
        banned = ("socket", "urllib", "requests", "http.client", "httpx",
                  "ftplib", "smtplib", "asyncio", "subprocess")
        offenders = []
        for name in sorted(os.listdir(src)):
            if not name.endswith(".py"):
                continue
            for line in read(os.path.join(src, name)).splitlines():
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                for mod in banned:
                    if re.match(rf"^(import|from)\s+{re.escape(mod)}\b", stripped):
                        offenders.append(f"{name}: {stripped}")
        self.assertEqual(offenders, [])

    def test_no_hardcoded_loinc_or_ucum_outside_the_manifest(self):
        """The manifest is meant to be the only place a code is pinned."""
        src = os.path.join(ROOT, "src", "fhir_sulo", "ingest")
        offenders = []
        for name in sorted(os.listdir(src)):
            if not name.endswith(".py"):
                continue
            text = read(os.path.join(src, name))
            # strip docstrings and comments before looking
            stripped = re.sub(r'""".*?"""', "", text, flags=re.S)
            stripped = re.sub(r"#.*", "", stripped)
            for needle in ("33914-3", "8480-6", "8462-4", "mm[Hg]", "loinc.org"):
                if needle in stripped:
                    offenders.append(f"{name}: {needle}")
        self.assertEqual(offenders, [])


class TestFixtureInventory(unittest.TestCase):
    def test_all_three_families_have_fixtures(self):
        families = {}
        for case_dir, case in cases():
            families.setdefault(case["family"], []).append(case["fixture_id"])
        self.assertEqual(sorted(families), ["bp", "egfr", "encounter"])
        self.assertGreaterEqual(len(families["egfr"]), 9)
        self.assertGreaterEqual(len(families["bp"]), 5)
        self.assertGreaterEqual(len(families["encounter"]), 3)

    def test_every_fixture_is_declared_synthetic(self):
        for _, case in cases():
            self.assertTrue(case["synthetic"], case["fixture_id"])

    def test_every_fixture_has_its_derived_artifacts(self):
        for case_dir, case in cases():
            for name in ("canonical.nt", "readable.ttl", "expected-bindings.json"):
                with self.subTest(fixture=case["fixture_id"], artifact=name):
                    self.assertTrue(os.path.exists(os.path.join(case_dir, name)))
            for variant in (case.get("variants") or {}).values():
                self.assertTrue(os.path.exists(os.path.join(case_dir, variant["rdf"])))


if __name__ == "__main__":
    unittest.main()
