"""One human at two hospitals becomes one person, through the real pipeline.

This is R8b demonstrated rather than unit-tested. Everything up to now proved
the identity service would key on an identifier if handed one; nothing proved
the pipeline could get there from FHIR JSON on disk, because the corpus had no
Patient resources and only one source.

The scenario, from ``fixtures/multi-source/``:

    mumc-r4     Patient/123  person number 900001   eGFR 61.5
    radboud-r4  Patient/987  person number 900001   eGFR 55.0
    radboud-r4  Patient/555  person number 900009   eGFR 72.0

``Patient/123`` and ``Patient/987`` share nothing but the person number. The
two eGFR results must attach to ONE person; ``Patient/555`` must stay someone
else.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from fhir_sulo.contracts import TransformStatus  # noqa: E402
from fhir_sulo.engine.docker import EngineImage  # noqa: E402
from fhir_sulo.identity.cli import allowlist_from_policy  # noqa: E402
from fhir_sulo.identity.person_index import PersonIdentifierIndex  # noqa: E402
from fhir_sulo.ingest import ingest_file  # noqa: E402
from fhir_sulo.pipeline.compose import Pipeline  # noqa: E402

CORPUS = REPO / "fixtures/multi-source"
SOURCES = {"mumc-r4": CORPUS / "mumc-r4", "radboud-r4": CORPUS / "radboud-r4"}
PERSON = re.compile(r"<(https://w3id\.org/ontostart/fhir2sulo/person-[0-9a-f]{32})>")

_IMAGE = None


def image():
    global _IMAGE
    if _IMAGE is None:
        _IMAGE = EngineImage()
        _IMAGE.ensure_built()
    return _IMAGE


def build_index() -> PersonIdentifierIndex:
    allow = allowlist_from_policy()
    index = PersonIdentifierIndex.empty()
    for scope_id, path in SOURCES.items():
        index = index.merged_with(
            PersonIdentifierIndex.from_directory(path, scope_id=scope_id, allowlist=allow))
    return index


def run(scope_id: str, observation: Path, index) -> str:
    """Map one Observation under its own source scope. Returns the person IRI."""
    pipe = Pipeline.for_family("egfr", REPO, engine=image(),
                               quality_mode="per-observation", person_index=index)
    context = ingest_file(str(observation), source_scope_id=scope_id)
    out = pipe.run_context(context)
    assert out.transform.status is TransformStatus.MAPPED, out.transform.status
    people = set(PERSON.findall("\n".join(out.transform.target_quads)))
    assert len(people) == 1, people
    return people.pop()


class OneHumanTwoHospitals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = build_index()
        cls.a = run("mumc-r4", SOURCES["mumc-r4"] / "Observation-egfr-a.json", cls.index)
        cls.b = run("radboud-r4", SOURCES["radboud-r4"] / "Observation-egfr-b.json", cls.index)
        cls.c = run("radboud-r4", SOURCES["radboud-r4"] / "Observation-egfr-c.json", cls.index)

    def test_the_index_was_built_from_the_patient_files(self):
        """Three Patients indexed; the local MRNs on them are not allowlisted."""
        self.assertEqual(len(self.index), 3)

    def test_the_two_hospitals_results_attach_to_one_person(self):
        """The whole point. Two scopes, two resource ids, one human."""
        self.assertEqual(self.a, self.b)

    def test_a_different_person_number_stays_a_different_person(self):
        """So a pass means the right people merged, not that everyone did."""
        self.assertNotEqual(self.a, self.c)

    def test_without_the_index_the_same_two_are_two_people(self):
        """The control. Nothing but the index links these records."""
        empty = PersonIdentifierIndex.empty()
        a = run("mumc-r4", SOURCES["mumc-r4"] / "Observation-egfr-a.json", empty)
        b = run("radboud-r4", SOURCES["radboud-r4"] / "Observation-egfr-b.json", empty)
        self.assertNotEqual(a, b)

    def test_the_index_digest_reaches_the_graph_key(self):
        """DR-016: two indexes must not name one graph."""
        obs = SOURCES["mumc-r4"] / "Observation-egfr-a.json"
        context = ingest_file(str(obs), source_scope_id="mumc-r4")
        with_index = Pipeline.for_family("egfr", REPO, engine=image(),
                                         quality_mode="per-observation",
                                         person_index=self.index)
        without = Pipeline.for_family("egfr", REPO, engine=image(),
                                      quality_mode="per-observation")
        self.assertEqual(without.person_index_digest, "none")
        self.assertEqual(with_index.person_index_digest, self.index.digest)
        self.assertNotEqual(with_index.run_inputs(context).graph_key,
                            without.run_inputs(context).graph_key)

    def test_the_digest_cannot_disagree_with_the_index(self):
        """It is derived, not a field someone can set beside the index."""
        pipe = Pipeline.for_family("egfr", REPO, engine=image(),
                                   quality_mode="per-observation", person_index=self.index)
        with self.assertRaises(AttributeError):
            pipe.person_index_digest = "a lie"


if __name__ == "__main__":
    unittest.main(verbosity=2)
