"""Assemble and run the Encounter map for one fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ._engine import engine, mapjob

REPO = engine.REPO
FAMILY = "encounter"
VAR_NS = "https://w3id.org/fhir-sulo/map/encounter/var#"


def fixture_dir(fixture_id: str) -> Path:
    return REPO / "fixtures/r4/encounter" / fixture_id


def source_json(fixture_id: str) -> Path:
    case = json.loads((fixture_dir(fixture_id) / "case.json").read_text())
    return fixture_dir(fixture_id) / case["sources"][0]


def focus_iri(fixture_id: str) -> str:
    return "https://fhir.example/Encounter/%s" % source_json(fixture_id).stem


def bind(fixture_id: str) -> Dict[str, Any]:
    return mapjob.bind(FAMILY, fixture_dir(fixture_id) / "canonical.nt", focus_iri(fixture_id))


def run(fixture_id: str, *, bindings_override: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    manifest = mapjob.load_manifest(FAMILY)
    bound = bind(fixture_id)
    if not bound["validation"]["ok"]:
        return bound

    b = mapjob.flat_bindings(bound["bindings"], VAR_NS)

    from fhir_sulo.identity import IdentityService

    policy = mapjob.policy_bundle(None)  # no quality identity is needed by this map
    ident = IdentityService(policy)

    ctx = mapjob.source_context(source_json(fixture_id))
    try:
        person = mapjob.entity_for_reference(ident, ctx, "Encounter.subject", "Patient")
        clinician = mapjob.entity_for_reference(
            ident, ctx, "Encounter.participant[0].individual", "Practitioner")
    except mapjob.ReferenceNotAPerson as exc:
        return {
            "ok": False, "stage": "identity", "validation": bound["validation"],
            "bindings": bound["bindings"], "passes": [], "nquads": "",
            "identityRejection": {"reason_code": exc.reason_code, "reason": exc.reason},
            "_sourceBindings": b,
        }

    enc_id = mapjob.lexical(b, "encId")
    version_id = mapjob.lexical(b, "versionId")
    canonical_url = focus_iri(fixture_id)

    values = dict(mapjob.vocabulary(manifest))
    values.update(mapjob.node_keys(manifest, encId=enc_id, versionId=version_id,
                                   canonicalUrl=canonical_url))
    values["person"] = person.entity_iri
    values["clinician"] = clinician.entity_iri

    job = {
        "sourceSchema": engine.cpath("maps/r4/encounter/encounter-source.v1.shex"),
        "targetSchema": engine.cpath("maps/r4/encounter/encounter-target.v1.shex"),
        "data": engine.cpath(str((fixture_dir(fixture_id) / "canonical.nt").relative_to(REPO))),
        "focus": canonical_url,
        "startShape": None,
        "passes": mapjob.build_passes(manifest, values, b),
    }
    if bindings_override is not None:
        job["bindingsOverride"] = bindings_override
    result = engine.run_job(job)
    result["_hostValues"] = values
    result["_sourceBindings"] = b
    return result
