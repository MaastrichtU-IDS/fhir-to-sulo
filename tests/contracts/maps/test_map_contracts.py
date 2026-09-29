"""The three MapContract manifests are real, loadable and consistent.

No Docker and no pytest: these are the contract-level checks, and they must run
in CI and under the stdlib fallback (`make contracts-stdlib`).

Between them these are the CD-1 substitute for the static checker the pinned
engine does not ship: unbound target variables, incompatible repetition scopes
(DR-302), and -- replacing "invalid `id()` uses" -- any Map code that is not a
bare variable, because the engine's response to an unknown Map function is to
silently delete the entire shape that used it.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

from ._engine import contractio, engine

REPO = engine.REPO
FAMILIES = ("egfr", "bp", "encounter")


def schema_body(text: str) -> str:
    """Strip ShExC comments, leaving `#` inside <IRIs> and "literals" alone.

    Needed because these schemas carry long rationale comments that mention the
    very strings the checks below forbid in code.
    """
    out = []
    for line in text.splitlines():
        kept, in_iri, in_str = [], False, False
        for ch in line:
            if in_iri:
                in_iri = ch != ">"
            elif in_str:
                in_str = ch != '"'
            elif ch == "<":
                in_iri = True
            elif ch == '"':
                in_str = True
            elif ch == "#":
                break
            kept.append(ch)
        out.append("".join(kept))
    return "\n".join(out)


REPEAT = re.compile(r"[*+]\s*(?:;|\}|$)|\{\s*\d+\s*,\s*(?:\d{2,}|\*)\s*\}")
MAP_CODE = re.compile(r"%Map:\{(.*?)%\}")
ALLOWED_MAP_FUNCTIONS = ("hashmap", "regex", "test")


def source_schema(family):
    return next(p for p in contractio.manifest(family)["pairing_files"]
                if p.endswith("source.v1.shex"))


def target_schema(family):
    return next(p for p in contractio.manifest(family)["pairing_files"]
                if p.endswith("target.v1.shex"))


class MapContracts(unittest.TestCase):
    def test_manifest_deserialises_to_the_frozen_map_contract(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                contract = contractio.load(family)
                self.assertTrue(contract.map_id)
                self.assertEqual(contract.sulo_version, "0.2.12")
                self.assertEqual(contract.source_release, "R4")
                self.assertTrue(contract.pivot_variables)
                self.assertTrue(contract.repetition_scopes)

    def test_pairing_hash_matches_the_schemas(self):
        """A schema edit that leaves the hash alone must fail the build."""
        proc = subprocess.run([sys.executable, str(REPO / "maps/r4/rehash.py"), "--check"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_every_pairing_file_exists(self):
        for family in FAMILIES:
            for rel in contractio.manifest(family)["pairing_files"]:
                with self.subTest(file=rel):
                    self.assertTrue((REPO / rel).is_file(), rel)

    def test_no_scope_declares_more_than_one_iteration_per_run(self):
        """DR-302, asserted on the declared contract.

        Every map is rooted at one FHIR resource, so every scope is one
        iteration per run.  A scope with max_occurs other than 1 would mean a
        repeating group inside a single run, which is where the engine's
        two-level failure starts.
        """
        for family in FAMILIES:
            for scope in contractio.load(family).repetition_scopes:
                with self.subTest(family=family, scope=scope.name):
                    self.assertEqual(
                        scope.max_occurs, 1,
                        "%s: scope %r declares max_occurs=%s" % (family, scope.name,
                                                                 scope.max_occurs))

    def test_the_source_schema_has_at_most_one_repeating_constraint(self):
        """DR-302 again, on the schema text rather than the manifest.

        A repeating constraint is `*`, `+` or an upper bound above 1.  The only
        one any source schema may carry is the tolerated, unmapped
        fhir:DomainResource.contained.
        """
        for family in FAMILIES:
            with self.subTest(family=family):
                body = schema_body((REPO / source_schema(family)).read_text())
                repeating = [line.strip() for line in body.splitlines()
                             if line.strip() and REPEAT.search(line.strip())]
                self.assertEqual(repeating, ["fhir:DomainResource.contained . * ;"], repeating)

    def test_every_map_code_is_a_bare_variable(self):
        """CD-1's substitute for 'invalid id() uses fail before data processing'.

        The pinned engine has no id(), and an unknown Map function does not
        error -- it silently deletes the entire shape that used it (DR-301 4b).
        A typo in a Map function is therefore catastrophic and invisible, so the
        only safe rule is that every Map code is a bare variable.
        """
        for family in FAMILIES:
            for rel in contractio.manifest(family)["pairing_files"]:
                if not rel.endswith(".shex"):
                    continue
                for code in MAP_CODE.findall(schema_body((REPO / rel).read_text())):
                    code = code.strip()
                    with self.subTest(file=rel, code=code):
                        self.assertNotIn(
                            "(", code,
                            "%s: Map code %r calls a function; the engine has only %s and "
                            "silently deletes the shape for anything else"
                            % (rel, code, list(ALLOWED_MAP_FUNCTIONS)))
                        self.assertRegex(code, r"^v:[A-Za-z][A-Za-z0-9]*$")

    def test_target_variables_are_a_subset_of_source_variables_plus_statics(self):
        """The linter's first obligation: no target variable can be unbindable.

        DR-301 blocker 8c: the engine's response to one of these is a partial
        graph, exit 0 and a clean stderr.
        """
        for family in FAMILIES:
            with self.subTest(family=family):
                doc = contractio.manifest(family)
                src = MAP_CODE.findall(schema_body((REPO / source_schema(family)).read_text()))
                tgt = MAP_CODE.findall(schema_body((REPO / target_schema(family)).read_text()))
                source_vars = {c.strip()[2:] for c in src}
                target_vars = {c.strip()[2:] for c in tgt}
                unbindable = target_vars - source_vars - set(doc["static_variables"])
                self.assertEqual(unbindable, set(), sorted(unbindable))

    def test_every_declared_static_variable_is_actually_used(self):
        """The other direction: a run binding no shape reads is a dead entry,
        and the engine reports it in unusedStatics, which the Gate 2/3 tests
        treat as an error."""
        for family in FAMILIES:
            with self.subTest(family=family):
                doc = contractio.manifest(family)
                tgt = MAP_CODE.findall(schema_body((REPO / target_schema(family)).read_text()))
                used = {c.strip()[2:] for c in tgt}
                bindings = json.loads(
                    (REPO / "maps/r4" / family
                     / ("%s-bindings.v1.json" % family)).read_text())
                # a root node key is supplied to materialize() as the root, not
                # as a Map variable, so it need not appear in the schema text
                roots = {p["root"] for p in bindings["passes"]}
                declared = set(doc["static_variables"]) - roots
                self.assertEqual(declared - used, set(), sorted(declared - used))

    def test_no_domain_vocabulary_iri_appears_in_any_schema(self):
        """Review item R1: the domain vocabulary must be swappable without
        re-authoring.  The placeholder namespace has no owner, so no schema may
        name it; every domain class reaches the graph through the run-binding
        manifest."""
        for family in FAMILIES:
            for rel in contractio.manifest(family)["pairing_files"]:
                if not rel.endswith(".shex"):
                    continue
                with self.subTest(file=rel):
                    self.assertNotIn("example.org/fhir-sulo",
                                     schema_body((REPO / rel).read_text()), rel)

    def test_no_hasPatient_or_resource_specific_shortcut(self):
        """Concept note section 2, as a hard prohibition."""
        for family in FAMILIES:
            body = schema_body((REPO / target_schema(family)).read_text())
            for banned in ("hasPatient", "hasSubject", "hasPractitioner", "hasClinician"):
                with self.subTest(family=family, predicate=banned):
                    self.assertNotIn(banned, body)

    def test_no_owl_sameAs_anywhere(self):
        """Concept note section 2: never between a FHIR resource and a person,
        process or quality.  The maps use none at all."""
        for family in FAMILIES:
            for rel in contractio.manifest(family)["pairing_files"]:
                body = (schema_body((REPO / rel).read_text()) if rel.endswith(".shex")
                        else (REPO / rel).read_text())
                with self.subTest(file=rel):
                    self.assertNotIn("sameAs", body)

    def test_static_analysis_is_not_claimed(self):
        """CD-1: the engine ships no static checker and Agent 4's linter has not
        landed, so no map may claim static analysis passed."""
        for family in FAMILIES:
            with self.subTest(family=family):
                self.assertIs(contractio.load(family).static_analysis_passed, False)

    def test_inverse_coverage_is_reported_not_assumed(self):
        """Concept note section 7: the promised fraction is explicit, not 1."""
        for family in FAMILIES:
            with self.subTest(family=family):
                coverage = contractio.load(family).inverse_coverage
                self.assertGreater(coverage, 0.0)
                self.assertLess(coverage, 1.0)


class IndirectionPointMirrorsThePolicyTables(unittest.TestCase):
    """The run-binding manifests mirror the reviewed tables; they are not a
    second opinion."""

    def setUp(self):
        self.codes = json.loads((REPO / "policies/code-interpretation.v1.json").read_text())
        self.units = json.loads((REPO / "policies/unit-policy.v1.json").read_text())
        self.by_code = {e["code"]: e for e in self.codes["entries"]}

    def test_egfr_vocabulary_matches_the_code_table(self):
        egfr = json.loads((REPO / "maps/r4/egfr/egfr-bindings.v1.json").read_text())
        self.assertEqual(egfr["domain_namespace"]["value"], self.codes["domain_namespace"])
        self.assertEqual(egfr["vocabulary"]["resultClass"]["iri"],
                         self.by_code["33914-3"]["result_class"])
        self.assertEqual(egfr["vocabulary"]["qualityClass"]["iri"],
                         self.by_code["33914-3"]["quality_class"])

    def test_bp_vocabulary_matches_the_code_table(self):
        bp = json.loads((REPO / "maps/r4/bp/bp-bindings.v1.json").read_text())
        self.assertEqual(bp["vocabulary"]["sysResultClass"]["iri"],
                         self.by_code["8480-6"]["result_class"])
        self.assertEqual(bp["vocabulary"]["diaResultClass"]["iri"],
                         self.by_code["8462-4"]["result_class"])
        self.assertEqual(bp["vocabulary"]["sysQualityClass"]["iri"],
                         self.by_code["8480-6"]["quality_class"])
        self.assertEqual(bp["vocabulary"]["diaQualityClass"]["iri"],
                         self.by_code["8462-4"]["quality_class"])

    def test_the_bp_panel_code_types_nothing_while_r9_is_open(self):
        bp = json.loads((REPO / "maps/r4/bp/bp-bindings.v1.json").read_text())
        self.assertEqual(self.by_code["85354-9"]["review_status"], "proposed")
        self.assertNotIn("panelClass", bp["vocabulary"])
        self.assertEqual(bp["not_emitted"]["panelClass"]["review_item"], "R9")

    def test_the_pinned_units_exist(self):
        self.assertTrue({u["code"] for u in self.units["units"]}
                        >= {"mL/min/{1.73_m2}", "mm[Hg]"})

    def test_nothing_in_the_maps_claims_clinical_sign_off(self):
        """R10: every code this pilot interprets is pilot-provisional."""
        for entry in self.codes["entries"]:
            if entry["code"] in {"33914-3", "8480-6", "8462-4"}:
                with self.subTest(code=entry["code"]):
                    self.assertNotEqual(entry["review_status"], "approved")

    def test_every_vocabulary_entry_names_its_source_and_is_not_approved(self):
        """So a reviewer answer can be applied without guessing what it touches,
        and so nothing here can quietly claim to be settled."""
        for family in FAMILIES:
            manifest = json.loads(
                (REPO / "maps/r4" / family / ("%s-bindings.v1.json" % family)).read_text())
            for name, spec in manifest["vocabulary"].items():
                with self.subTest(family=family, entry=name):
                    self.assertIn("source", spec)
                    self.assertIn("status", spec)
                    self.assertNotEqual(spec["status"], "approved")


if __name__ == "__main__":
    unittest.main()
