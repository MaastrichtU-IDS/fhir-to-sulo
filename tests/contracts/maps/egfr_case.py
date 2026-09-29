"""Assemble and run the eGFR map for one fixture.

Shared by the Gate 2 acceptance tests and the expected-graph tests, so both
exercise exactly the same host path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ._engine import engine, mapjob

REPO = engine.REPO
FAMILY = "egfr"
VAR_NS = "https://w3id.org/fhir-sulo/map/egfr/var#"

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"


def fixture_dir(fixture_id: str) -> Path:
    return REPO / "fixtures/r4/egfr" / fixture_id


def source_json(fixture_id: str) -> Path:
    case = json.loads((fixture_dir(fixture_id) / "case.json").read_text())
    return fixture_dir(fixture_id) / case["sources"][0]


def focus_iri(fixture_id: str) -> str:
    """The single FHIR resource this map is rooted at (DR-302)."""
    return "https://fhir.example/Observation/%s" % source_json(fixture_id).stem


def bind(fixture_id: str, data_override: Optional[str] = None) -> Dict[str, Any]:
    return mapjob.bind(FAMILY, fixture_dir(fixture_id) / "canonical.nt",
                       focus_iri(fixture_id), data_override=data_override)


def run(fixture_id: str, *, quality_mode: str = "per-observation",
        bindings_override: Optional[Mapping[str, Any]] = None,
        vocabulary_override: Optional[Mapping[str, str]] = None,
        data_override: Optional[str] = None) -> Dict[str, Any]:
    """Bind, resolve identity and terminology, then materialize every pass."""
    manifest = mapjob.load_manifest(FAMILY)
    bound = bind(fixture_id, data_override)
    if not bound["validation"]["ok"]:
        return bound

    b = mapjob.flat_bindings(bound["bindings"], VAR_NS)

    from fhir_sulo.identity import IdentityService
    from fhir_sulo.terminology import TerminologyService

    policy = mapjob.policy_bundle(quality_mode)
    ident = IdentityService(policy)
    term = TerminologyService(policy)

    vocab = dict(mapjob.vocabulary(manifest))
    if vocabulary_override:
        vocab.update(vocabulary_override)

    # Identity comes from Agent 2's resolved reference plus Agent 5's service.
    # An ambiguous or unresolvable subject therefore yields no person and the
    # run stops here, with no target graph.
    ctx = mapjob.source_context(source_json(fixture_id))
    try:
        person = mapjob.entity_for_reference(ident, ctx, "Observation.subject", "Patient")
    except mapjob.ReferenceNotAPerson as exc:
        return {
            "ok": False, "stage": "identity", "validation": bound["validation"],
            "bindings": bound["bindings"], "passes": [], "nquads": "",
            "identityRejection": {"reason_code": exc.reason_code, "reason": exc.reason},
            "_sourceBindings": b,
        }

    obs_id = mapjob.lexical(b, "obsId")
    version_id = mapjob.lexical(b, "versionId")
    canonical_url = focus_iri(fixture_id)

    quality = mapjob.quality_iri(
        ident, person, vocab["qualityClass"], LOINC, mapjob.lexical(b, "code"),
        canonical_url, version_id, mapjob.lexical(b, "effective"),
    ).unwrap()

    unit = mapjob.unit_iri(term, UCUM, mapjob.lexical(b, "unitCode"), "egfr-rate")

    keys = mapjob.node_keys(manifest, obsId=obs_id, versionId=version_id,
                            canonicalUrl=canonical_url)

    values = dict(vocab)
    values.update(keys)
    values["person"] = person.entity_iri
    values["quality"] = quality.quality_iri
    values["unitIri"] = unit

    job = {
        "sourceSchema": engine.cpath("maps/r4/egfr/egfr-source.v1.shex"),
        "targetSchema": engine.cpath("maps/r4/egfr/egfr-target.v1.shex"),
        "data": None if data_override is not None else engine.cpath(
            str((fixture_dir(fixture_id) / "canonical.nt").relative_to(REPO))),
        "dataInline": data_override,
        "focus": canonical_url,
        "startShape": None,
        "passes": mapjob.build_passes(manifest, values),
    }
    if bindings_override is not None:
        job["bindingsOverride"] = bindings_override
    result = engine.run_job(job)
    result["_hostValues"] = values
    result["_sourceBindings"] = b
    return result
