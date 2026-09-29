"""Assemble and run the blood-pressure map for one fixture resource.

Concept note section 5's "two blood-pressure panels" are two separate
Observation resources, so this runs once per resource and the caller unions
the results.  DR-302: every map is rooted at exactly one FHIR resource.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ._engine import engine, mapjob

REPO = engine.REPO
FAMILY = "bp"
VAR_NS = "https://w3id.org/fhir-sulo/map/bp/var#"

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
SYSTOLIC_CODE = "8480-6"
DIASTOLIC_CODE = "8462-4"


def fixture_dir(fixture_id: str) -> Path:
    return REPO / "fixtures/r4/bp" / fixture_id


def case_doc(fixture_id: str) -> Dict[str, Any]:
    return json.loads((fixture_dir(fixture_id) / "case.json").read_text())


def resources(fixture_id: str, variant: Optional[str] = None) -> Tuple[str, List[str]]:
    """``(rdf file name, [observation id, ...])`` for a fixture or one variant."""
    case = case_doc(fixture_id)
    if variant is None:
        return "canonical.nt", [Path(s).stem for s in case["sources"]]
    spec = case["variants"][variant]
    sources = spec.get("sources", case["sources"])
    # the components-reversed sources keep their original resource ids
    ids = [Path(s).stem.replace("-components-reversed", "") for s in sources]
    return spec["rdf"], ids


def focus_iri(obs_id: str) -> str:
    return "https://fhir.example/Observation/%s" % obs_id


def source_json(fixture_id: str, obs_id: str, rdf: str) -> Path:
    """The FHIR JSON behind one resource of a fixture (or of an RDF variant)."""
    suffix = "-components-reversed" if "components-reversed" in rdf else ""
    return fixture_dir(fixture_id) / ("%s%s.json" % (obs_id, suffix))


def bind(fixture_id: str, obs_id: str, rdf: str = "canonical.nt") -> Dict[str, Any]:
    return mapjob.bind(FAMILY, fixture_dir(fixture_id) / rdf, focus_iri(obs_id))


def run(fixture_id: str, obs_id: str, *, rdf: str = "canonical.nt",
        quality_mode: str = "per-observation",
        bindings_override: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    manifest = mapjob.load_manifest(FAMILY)
    bound = bind(fixture_id, obs_id, rdf)
    if not bound["validation"]["ok"]:
        return bound

    b = mapjob.flat_bindings(bound["bindings"], VAR_NS)

    from fhir_sulo.identity import IdentityService
    from fhir_sulo.terminology import TerminologyService

    policy = mapjob.policy_bundle(quality_mode)
    ident = IdentityService(policy)
    term = TerminologyService(policy)

    vocab = dict(mapjob.vocabulary(manifest))

    ctx = mapjob.source_context(source_json(fixture_id, obs_id, rdf))
    try:
        person = mapjob.entity_for_reference(ident, ctx, "Observation.subject", "Patient")
    except mapjob.ReferenceNotAPerson as exc:
        return {
            "ok": False, "stage": "identity", "validation": bound["validation"],
            "bindings": bound["bindings"], "passes": [], "nquads": "",
            "identityRejection": {"reason_code": exc.reason_code, "reason": exc.reason},
            "_sourceBindings": b,
        }

    panel = mapjob.lexical(b, "panel")
    version_id = mapjob.lexical(b, "versionId")
    canonical_url = focus_iri(obs_id)
    effective = mapjob.lexical(b, "effective")

    values = dict(vocab)
    values.update(mapjob.node_keys(manifest, panel=panel, versionId=version_id,
                                   canonicalUrl=canonical_url))
    values["person"] = person.entity_iri
    values["sysQuality"] = mapjob.quality_iri(
        ident, person, vocab["sysQualityClass"], LOINC, SYSTOLIC_CODE,
        canonical_url, version_id, effective).unwrap().quality_iri
    values["unitIri"] = mapjob.unit_iri(term, UCUM, mapjob.lexical(b, "sysUnit"), "pressure")
    if mapjob.lexical(b, "diaValue"):
        values["diaQuality"] = mapjob.quality_iri(
            ident, person, vocab["diaQualityClass"], LOINC, DIASTOLIC_CODE,
            canonical_url, version_id, effective).unwrap().quality_iri

    job = {
        "sourceSchema": engine.cpath("maps/r4/bp/bp-source.v1.shex"),
        "targetSchema": engine.cpath("maps/r4/bp/bp-target.v1.shex"),
        "data": engine.cpath(str((fixture_dir(fixture_id) / rdf).relative_to(REPO))),
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


# ---------------------------------------------------------------------------
# the Gate 3 tuple multiset
# ---------------------------------------------------------------------------

def binding_tree(fixture_id: str, results: Mapping[str, Mapping[str, Any]]):
    """Rebuild a :class:`fhir_sulo.contracts.BindingNode` from engine output.

    One run per Observation, so one ``panel`` iteration per run.  The tuple
    multiset this yields is compared against Agent 2's
    ``expected-bindings.json`` with ``tuples_for_scope``, the same call the
    frozen interface demonstrates.
    """
    from fhir_sulo.contracts import BindingNode

    children = []
    for obs_id in sorted(results):
        b = results[obs_id]["_sourceBindings"]
        children.append(BindingNode(
            shape="BPPanel",
            focus=obs_id,
            scope="panel",
            iteration_key=(mapjob.lexical(b, "panel") or "",),
            bindings={
                "panel": mapjob.lexical(b, "panel") or "",
                "subjectRef": mapjob.lexical(b, "subjectRef") or "",
                "effective": mapjob.lexical(b, "effective") or "",
                "sys": mapjob.lexical(b, "sysValue") or "",
                "dia": mapjob.lexical(b, "diaValue") or "",
                "sysUnit": mapjob.lexical(b, "sysUnit") or "",
                "diaUnit": mapjob.lexical(b, "diaUnit") or "",
            },
        ))
    return BindingNode(shape="BPPanelSet", focus="bp-panels", bindings={},
                       children=tuple(children))
