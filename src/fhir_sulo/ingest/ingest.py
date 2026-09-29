"""The ingestion entry point: FHIR JSON text -> :class:`SourceContext`.

This is the whole of Agent 2's runtime surface. It performs no network I/O, so
the "no hidden network calls at run time" criterion is a property of the code
rather than a configuration flag.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..contracts import EligibilityOutcome, ResolvedReference, SourceContext
from . import jsonio
from .eligibility import EligibilityEvaluator
from .fhir_rdf import FhirRdfRenderer
from .identity_port import IdentityService, RefusingIdentityService, SubjectContext
from .manifest import Manifest, default_manifest
from .ntriples import serialize
from .references import ReferenceResolver

#: Which resource type each reference-valued in-scope element is expected to
#: name. A mismatch is recorded as evidence, never silently accepted as a
#: person (concept note section 2).
EXPECTED_REFERENCE_TYPES = {
    "Observation.subject": "Patient",
    "Observation.encounter": "Encounter",
    "Observation.performer": "Practitioner",
    "Encounter.subject": "Patient",
    "Encounter.participant.individual": "Practitioner",
}


def _expected_for(path: str) -> Optional[str]:
    # Strip array indices so Encounter.participant[0].individual matches.
    import re
    return EXPECTED_REFERENCE_TYPES.get(re.sub(r"\[\d+\]", "", path))


def ingest_text(json_text: str, manifest: Optional[Manifest] = None,
                identity: Optional[IdentityService] = None,
                dataset_id: str = "synthetic/pilot") -> SourceContext:
    m = manifest or default_manifest()
    resource = jsonio.loads(json_text)
    return ingest_resource(resource, json_text=json_text, manifest=m,
                           identity=identity, dataset_id=dataset_id)


def ingest_file(path: str, **kwargs) -> SourceContext:
    with open(path, "r", encoding="utf-8") as fh:
        return ingest_text(fh.read(), **kwargs)


def ingest_resource(resource: Dict[str, Any], json_text: Optional[str] = None,
                    manifest: Optional[Manifest] = None,
                    identity: Optional[IdentityService] = None,
                    dataset_id: str = "synthetic/pilot") -> SourceContext:
    m = manifest or default_manifest()
    identity = identity or RefusingIdentityService()
    if json_text is None:
        json_text = jsonio.dumps(resource)

    rtype = resource.get("resourceType")
    if rtype not in m.supported_resource_types():
        raise ValueError(
            f"resourceType {rtype!r} is not in the pinned profile set "
            f"{m.supported_resource_types()}"
        )

    rendered = FhirRdfRenderer(m).render(resource)

    declared = tuple(str(p) for p in (resource.get("meta", {}).get("profile") or ()))
    known = set(m.known_profiles(rtype))
    validated = tuple(sorted(set(m.validated_profiles(rtype)) | (set(declared) & known)))

    resolver = ReferenceResolver(m)
    raw_refs = resolver.resolve_resource(
        resource,
        expected_types={
            path: t for path, t in (
                (p, _expected_for(p)) for p in _reference_paths(resolver, resource)
            ) if t
        },
    )

    version_id = str(resource.get("meta", {}).get("versionId") or "")
    canonical_url = m.server_base + rtype + "/" + str(resource["id"])
    subject_ctx = SubjectContext(
        source_server_base=m.server_base, dataset_id=dataset_id,
        source_resource_iri=canonical_url, source_version_id=version_id,
    )
    refs: Dict[str, ResolvedReference] = dict(identity.establish(raw_refs, subject_ctx))

    verdict = EligibilityEvaluator(m).evaluate(resource, refs)

    unknown_declared = tuple(sorted(set(declared) - known))
    notes = tuple(
        [f"renderer options: {sorted(FhirRdfRenderer(m).options.items())}"]
        + ([f"declared profiles not in the pinned set: {list(unknown_declared)}"]
           if unknown_declared else [])
    )

    return SourceContext(
        fhir_release=m.fhir_release,
        canonical_url=canonical_url,
        version_id=version_id,
        declared_profiles=declared,
        validated_profiles=validated,
        source_json_digest=jsonio.digest(json_text),
        rdf_graph=serialize(rendered.triples),
        rdf_content_type=m.data["renderer"]["canonical_media_type"],
        source_status=str(resource.get("status", "")),
        resolved_references=refs,
        terminology_snapshot=m.terminology_snapshot,
        eligibility=verdict.outcome,
        eligibility_reason=verdict.reason_text,
        unsupported_modifier_extensions=verdict.unsupported_modifier_extensions,
        renderer_id=m.renderer_id,
        notes=notes,
    )


def _reference_paths(resolver: ReferenceResolver, resource: Dict[str, Any]):
    rtype = resource["resourceType"]
    return [path for path, _ in resolver._find_references(resource, rtype, rtype)]
