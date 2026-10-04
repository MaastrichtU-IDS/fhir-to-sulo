"""Reference-to-entity identity service (Agent 5).

Public interface - this is the boundary Agent 2 calls and mocks::

    from fhir_sulo.identity import (
        IdentityService, IdentityRequest, ReferenceEvidence, SourceScope,
    )

    svc = IdentityService()                      # loads policies/ and pins versions
    outcome = svc.resolve(IdentityRequest(...))  # IdentityResolved | IdentityRejected

    if outcome.is_resolved:
        person = outcome.identity               # EntityIdentity
    else:
        handle(outcome.reason_code, outcome.record)

There is no way to obtain an entity IRI from a rejected outcome: the rejected
type has no IRI attribute and ``unwrap()`` raises ``IdentityUnavailable``.
"""

from .service import IdentityService
from .types import (
    EntityIdentity,
    IdentityOutcome,
    IdentityRejected,
    IdentityRequest,
    IdentityResolved,
    IdentityUnavailable,
    QualityIdentity,
    QualityIdentityPolicyUnset,
    QualityOutcome,
    QualityRejected,
    QualityRequest,
    QualityResolved,
    ReferenceEvidence,
    SourceScope,
    require_identity,
    require_quality,
)

__all__ = [
    "IdentityService",
    "IdentityRequest",
    "IdentityOutcome",
    "IdentityResolved",
    "IdentityRejected",
    "IdentityUnavailable",
    "EntityIdentity",
    "ReferenceEvidence",
    "SourceScope",
    "QualityRequest",
    "QualityOutcome",
    "QualityResolved",
    "QualityRejected",
    "QualityIdentity",
    "QualityIdentityPolicyUnset",
    "require_identity",
    "require_quality",
]
