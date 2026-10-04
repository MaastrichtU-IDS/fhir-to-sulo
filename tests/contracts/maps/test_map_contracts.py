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
import os
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



def banned_shortcut_predicates():
    """The prohibition, read out of the SHACL constraint that enforces it.

    Hardcoded here as a tuple until 2026-10-03, when a blanket rename turned
    ("hasPatient", "hasSubject", "hasPractitioner", "hasClinician") into
    (..., "hasPractitioner", "hasPractitioner") -- a four-predicate prohibition
    silently became three, and no test noticed because a duplicate subTest
    still passes.  Deriving it means the schema test and the SHACL shape can
    never disagree about what is forbidden.
    """
    shapes = (REPO / "src/fhir_sulo/validation/shapes/base.ttl").read_text()
    found = tuple(dict.fromkeys(re.findall(r'STRENDS\(STR\(\?p\), "(has\w+)"\)', shapes)))
    if len(found) < 4:
        raise AssertionError(
            "expected at least 4 banned shortcut predicates in base.ttl, found %r. "
            "If one was deliberately removed, remove it from the SHACL shape and say "
            "why in a decision record." % (found,)
        )
    return found

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

    def test_every_repeating_constraint_is_a_tolerated_wildcard(self):
        """DR-302, on the schema text rather than the manifest.

        The rule that matters is DEPTH: two levels of repetition are silently
        mis-mapped by the engine.  A repeating constraint creates a second
        level only if something with a sub-shape, or a Map variable, sits
        under it.  So the check is not "there is exactly one `*`" -- that was
        the first version of this test and it was wrong, because it forced the
        CLOSED shapes to reject every `source_only_element`, including the
        `issued` that HL7's own eGFR example carries.

        The check is: every repeating constraint has the WILDCARD `.` value
        expression and no Map variable.  Nothing is bound under it, nothing is
        matched under it, so it cannot contribute a level.
        """
        for family in FAMILIES:
            body = schema_body((REPO / source_schema(family)).read_text())
            for line in body.splitlines():
                code = line.strip()
                if not code or not REPEAT.search(code):
                    continue
                with self.subTest(family=family, constraint=code):
                    self.assertRegex(
                        code, r"^fhir:[A-Za-z.]+\s+\.\s*\*\s*;?$",
                        "a repeating constraint must be a tolerated wildcard with no "
                        "sub-shape and no Map variable, or it can create the second "
                        "level of repetition the engine mis-maps (DR-302)")

    def test_repeating_constraints_are_the_declared_source_only_elements(self):
        """And each tolerated wildcard is one the pinned profile declares
        source-only, so the CLOSED shapes cannot be widened by accident."""
        profile = json.loads((REPO / "profiles/fhir-r4-pilot.json").read_text())
        declared = set()
        for spec in profile["resources"].values():
            for element in spec.get("source_only_elements", ()):
                declared.add("fhir:" + element)
        declared.add("fhir:DomainResource.text")        # Observation.text / Encounter.text
        declared.add("fhir:DomainResource.contained")   # Observation.contained / Encounter.contained

        for family in FAMILIES:
            body = schema_body((REPO / source_schema(family)).read_text())
            for line in body.splitlines():
                code = line.strip()
                if not code or not REPEAT.search(code):
                    continue
                predicate = code.split()[0]
                with self.subTest(family=family, predicate=predicate):
                    self.assertIn(predicate, declared)

    def test_method_is_not_tolerated(self):
        """Concept note section 2 names `method` among the things that must
        never be dropped while claiming an unqualified numeric result.

        The pinned profile lists it under `source_only_elements`, so the two
        documents conflict.  Held at REJECT -- the conservative side, producing
        no semantic output rather than an unqualified quantity -- and reported
        in DR-205 rather than resolved unilaterally.
        """
        for family in ("egfr", "bp"):
            with self.subTest(family=family):
                body = schema_body((REPO / source_schema(family)).read_text())
                self.assertNotIn("fhir:Observation.method", body)

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
        re-authoring. No schema may name a domain namespace; every domain class
        reaches the graph through the run-binding manifest.

        The namespace is read from the policy rather than written here. R1 was
        answered on 2026-09-30 and the placeholder became a real namespace; a
        test that checked only the retired literal would have gone quietly
        vacuous at exactly that moment. The retired one is still checked, so a
        stale hard-coded IRI cannot creep back either.
        """
        import json

        configured = json.loads(
            (REPO / "policies" / "code-interpretation.v1.json").read_text()
        )["domain_namespace"]
        self.assertTrue(configured, "policy declares no domain_namespace")
        banned = {configured.rstrip("/"), "https://example.org/fhir-sulo"}

        for family in FAMILIES:
            for rel in contractio.manifest(family)["pairing_files"]:
                if not rel.endswith(".shex"):
                    continue
                body = schema_body((REPO / rel).read_text())
                for ns in banned:
                    with self.subTest(file=rel, namespace=ns):
                        self.assertNotIn(ns, body, rel)

    def test_no_hasPatient_or_resource_specific_shortcut(self):
        """Concept note section 2, as a hard prohibition."""
        for family in FAMILIES:
            body = schema_body((REPO / target_schema(family)).read_text())
            for banned in banned_shortcut_predicates():
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

    def test_static_analysis_is_claimed_and_the_linter_agrees(self):
        """CD-1: the obligation moved from the absent id() to a host linter.

        This test was previously `test_static_analysis_is_not_claimed`, which
        asserted every map declared False because the linter had not landed.
        It has landed and covers every root shape of every pass -- 25 across
        the three maps, where it once saw three -- so the claim is now true
        and must stay backed by the linter actually passing.

        The two halves are asserted together on purpose. A contract claiming
        static analysis while the linter fails is a lie; a linter passing
        while the contract denies it is stale bookkeeping.
        """
        import shutil
        import subprocess
        import sys

        for family in FAMILIES:
            with self.subTest(family=family):
                self.assertIs(contractio.load(family).static_analysis_passed, True)

        lint = os.path.join(REPO, "tools", "shexmap-lint")
        proc = subprocess.run(
            [sys.executable, lint, "--dir", os.path.join(REPO, "maps"), "--require-pairs"],
            capture_output=True, text=True, cwd=REPO,
            env=dict(os.environ, PYTHONPATH=os.path.join(REPO, "src")),
        )
        self.assertEqual(
            proc.returncode, 0,
            "maps claim static_analysis_passed but the linter disagrees:\n"
            + proc.stdout + proc.stderr)

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
