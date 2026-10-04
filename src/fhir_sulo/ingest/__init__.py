"""FHIR ingestion: validation, deterministic FHIR RDF rendering, references.

Owned by Agent 2. Produces :class:`fhir_sulo.contracts.SourceContext`.

Entry points
------------
``ingest_file`` / ``ingest_text``
    FHIR JSON -> ``SourceContext``.
``render`` / ``to_json``
    The two halves of the round trip.
``MockIdentityService``
    The deterministic stand-in for Agent 5's identity service; see
    ``identity_port`` for the interface being proposed to them.

No module in this package performs network I/O.
"""

from .bindings import extract, load as load_bindings, load_binding_tree
from .eligibility import EligibilityEvaluator, EligibilityVerdict
from .fhir_rdf import FhirRdfRenderer, RenderError, render
from .identity_port import (
    IdentityService,
    MockIdentityService,
    RefusingIdentityService,
    SubjectContext,
)
from .ingest import ingest_file, ingest_resource, ingest_text
from .manifest import Manifest, ManifestError, default_manifest
from .rdf_to_fhir import FhirRdfReader, InverseError, to_json
from .references import ReferenceResolver, resolve_resource

__all__ = [
    "EligibilityEvaluator", "EligibilityVerdict",
    "FhirRdfReader", "FhirRdfRenderer", "IdentityService", "Manifest",
    "ManifestError", "MockIdentityService", "RefusingIdentityService",
    "ReferenceResolver", "RenderError", "InverseError", "SubjectContext",
    "default_manifest", "extract", "ingest_file", "ingest_resource",
    "ingest_text", "load_bindings", "load_binding_tree", "render",
    "resolve_resource", "to_json",
]
