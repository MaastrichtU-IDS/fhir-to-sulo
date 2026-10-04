"""SourceContext - the validated, rendered, reference-resolved FHIR input.

Plan section 3:

    Contains fhir_release, canonical resource URL, version ID, declared and
    validated profiles, source JSON digest, RDF graph, resolved references with
    evidence, source status, terminology snapshot, and eligibility outcome. No
    person-equivalence claim is implicit in a resolved FHIR reference.

Owned by Agent 2 (ingestion) to produce; consumed by Agents 3, 4, 5 and 6.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence, Tuple


class EligibilityOutcome(enum.Enum):
    """Whether this source resource may produce clinical assertions at all.

    Decided during ingestion from status and modifier extensions, before any
    mapping runs. Concept note section 2: a status of ``entered-in-error``
    suppresses clinical assertions but does not erase the source record, and an
    unsupported modifier extension blocks semantic materialization.
    """

    ELIGIBLE = "eligible"
    SOURCE_ONLY = "source-only"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ReferenceEvidence:
    """Why a FHIR reference was resolved the way it was.

    This is audit material, not an identity claim. ``kind`` records how the
    reference was resolved (literal, relative, contained, bundle-local) so that
    the identity service can apply a different rule per kind rather than
    treating every resolution as equally trustworthy.
    """

    kind: str
    raw_reference: str
    resolved_target: Optional[str]
    source_element: str
    notes: Tuple[str, ...] = ()
    #: R8b. Set for ``kind == "identifier-only"``: a FHIR logical reference
    #: carries ``Identifier.system`` + ``Identifier.value`` and no address.
    #: Still not an identity claim -- the identity service keys on it only
    #: when the system is on the policy's reviewed allowlist.
    identifier_system: Optional[str] = None
    identifier_value: Optional[str] = None


@dataclass(frozen=True)
class ResolvedReference:
    """A FHIR reference plus its evidence, and *optionally* an entity IRI.

    ``entity_iri`` is None until the identity service (Agent 5) supplies one
    under a recorded policy. A consumer that wants a person MUST check this
    field rather than deriving an IRI from ``evidence.resolved_target``:
    deriving one would silently turn a FHIR record reference into a
    person-equivalence claim, which concept note section 2 forbids.
    """

    evidence: ReferenceEvidence
    entity_iri: Optional[str] = None
    identity_policy_version: Optional[str] = None
    ambiguous: bool = False
    ambiguity_reason: Optional[str] = None

    def require_entity_iri(self) -> str:
        """Return the entity IRI, or raise if identity was never established.

        Deliberately the only ergonomic way to get an IRI out, so that an
        unresolved or ambiguous reference cannot be used as a person by
        accident. Acceptance matrix row "Identity": ambiguous identity never
        silently merges.
        """
        if self.ambiguous:
            raise AmbiguousReferenceError(
                f"{self.evidence.raw_reference}: {self.ambiguity_reason or 'ambiguous'}"
            )
        if self.entity_iri is None:
            raise UnresolvedReferenceError(
                f"{self.evidence.raw_reference}: no entity IRI was established"
            )
        return self.entity_iri


class AmbiguousReferenceError(RuntimeError):
    """Raised when an ambiguous reference is used as though it were resolved."""


class UnresolvedReferenceError(RuntimeError):
    """Raised when an unresolved reference is used as though it were resolved."""


#: The single source this repo's hand-written fixtures come from. A DEFAULT,
#: not a constant: a deployment reading from several healthcare systems must
#: pass its own per-source value, and ``identity-policy.v1.json`` records that
#: under ``reference_scope.deployment_mode``.
#:
#: Named for what it is. It was ``synthea-pilot-r4`` until 2026-10-04, which
#: named a generator this project does not use -- there is no Synthea data
#: here and never was. Harmless while the scope was a constant nobody could
#: set; not harmless once scope ids key identity, because a plausible name
#: invites someone to point a real Synthea export at the same scope and fuse
#: two unrelated corpora that share resource ids.
PILOT_SOURCE_SCOPE_ID = "fhir-sulo-fixtures-r4"
PILOT_FHIR_BASE_URL = "https://fhir.example/"


@dataclass(frozen=True)
class SourceContext:
    """Everything downstream needs about one validated FHIR source resource."""

    fhir_release: str
    canonical_url: str
    version_id: str
    declared_profiles: Tuple[str, ...]
    validated_profiles: Tuple[str, ...]
    source_json_digest: str
    rdf_graph: str
    rdf_content_type: str
    source_status: str
    resolved_references: Mapping[str, ResolvedReference]
    terminology_snapshot: str
    eligibility: EligibilityOutcome
    #: WHERE this resource came from. An entity IRI is keyed on it, so two
    #: healthcare systems that each hold ``Patient/123`` must give two
    #: different people. Carried per resource rather than configured globally,
    #: because in a multi-source run it varies from one resource to the next.
    #: It was a module constant in ``pipeline/services.py`` until 2026-10-04,
    #: which meant every source keyed as one and records from different
    #: systems sharing a resource id silently became ONE person.
    source_scope_id: str = PILOT_SOURCE_SCOPE_ID
    fhir_base_url: str = PILOT_FHIR_BASE_URL
    eligibility_reason: Optional[str] = None
    unsupported_modifier_extensions: Tuple[str, ...] = ()
    renderer_id: str = ""
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.unsupported_modifier_extensions and self.eligibility is EligibilityOutcome.ELIGIBLE:
            raise ValueError(
                "unsupported modifier extensions must block semantic materialization "
                "(concept note section 2); eligibility cannot be ELIGIBLE"
            )
