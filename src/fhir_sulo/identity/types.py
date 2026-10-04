"""Types on the identity boundary between Agent 2 (FHIR ingestion) and Agent 5.

Design constraint from the contract
-----------------------------------
"An unresolved or ambiguous reference must produce an explicit rejection that
the caller has to handle - it must be impossible to silently get a person IRI
out of an ambiguous reference. Make that a type/API property, not a convention."

How that is enforced here:

* ``resolve()`` returns ``IdentityOutcome = Union[IdentityResolved, IdentityRejected]``.
* ``IdentityRejected`` has **no** ``identity``, ``entity_iri`` or ``iri`` attribute.
  Reaching for one is an ``AttributeError`` at runtime and a type error under
  mypy, and ``__getattr__`` upgrades the common misspellings to a loud
  ``IdentityUnavailable`` so the failure names the problem.
* There is **no** API anywhere in this package that returns ``Optional[str]``
  or ``Optional[EntityIdentity]``. A caller cannot write ``if iri is None``
  and forget the else branch, because they never get a ``None``.
* ``unwrap()`` exists on both arms; on the rejected arm it raises.
* ``QualityRequest.person`` is typed ``EntityIdentity``, so a quality IRI cannot
  be requested before a person identity has actually been resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Mapping, NoReturn, Optional, Tuple, Union

try:  # pragma: no cover - 3.8+ has Literal in typing
    from typing import Literal
except ImportError:  # pragma: no cover
    from typing_extensions import Literal  # type: ignore

from ..policy import DecisionRecord

__all__ = [
    "IdentityUnavailable",
    "QualityIdentityPolicyUnset",
    "SourceScope",
    "ReferenceEvidence",
    "IdentityRequest",
    "EntityIdentity",
    "IdentityResolved",
    "IdentityRejected",
    "IdentityOutcome",
    "QualityRequest",
    "QualityIdentity",
    "QualityResolved",
    "QualityRejected",
    "QualityOutcome",
    "require_identity",
    "require_quality",
]


class IdentityUnavailable(Exception):
    """Raised when a caller tries to read an entity IRI that was never granted.

    Carries the rejection's reason code and its audit record so the failure is
    self-describing in a log or a traceback.
    """

    def __init__(self, reason_code: str, reason: str, record: DecisionRecord) -> None:
        super().__init__("%s: %s" % (reason_code, reason))
        self.reason_code = reason_code
        self.reason = reason
        self.record = record


class QualityIdentityPolicyUnset(IdentityUnavailable):
    """The quality identity policy is deliberately unset, awaiting the reviewer."""


# ---------------------------------------------------------------------------
# Inputs (produced by Agent 2's reference resolution)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceScope:
    """The dataset or server the reference was resolved within.

    ``scope_id`` is the identity scope. Two references are only ever candidates
    for the same entity if they share it, unless a reviewed cross-source merge
    rule says otherwise - and no such rule is currently approved.
    """

    scope_id: str
    fhir_base_url: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"scope_id": self.scope_id, "fhir_base_url": self.fhir_base_url}


@dataclass(frozen=True)
class ReferenceEvidence:
    """One candidate resolution of a FHIR reference, with how it was obtained.

    ``kind`` is Agent 2's resolution mechanism, e.g. ``"literal-reference"``,
    ``"bundle-entry"``, ``"contained"``, ``"logical-identifier"``.

    IR-604: for ``kind == "contained"`` the caller supplies ``container_url``
    -- the canonical URL of the resource the ``#local`` reference lives inside
    -- and the *service* derives the scope from it. Callers used to pre-bake
    that into ``source_scope.scope_id`` themselves, in two places, with two
    incompatible formulas. ``source_scope`` is now the plain dataset scope in
    every case, and a contained reference without a ``container_url`` is
    rejected rather than keyed, because an unscoped ``#p-inline`` is exactly
    the merge this rule exists to prevent.
    """

    evidence_id: str
    kind: str
    source_scope: SourceScope
    resource_type: str
    resource_id: str
    canonical_url: Optional[str] = None
    resource_version_id: Optional[str] = None
    container_url: Optional[str] = None
    #: R8b. A FHIR business identifier carried by the reference or the
    #: contained resource. Only keys the person when ``identifier_system`` is
    #: on the policy's reviewed allowlist; otherwise it is audit detail and
    #: the record address keys as before.
    identifier_system: Optional[str] = None
    identifier_value: Optional[str] = None
    detail: Mapping[str, str] = field(default_factory=dict)

    def is_contained(self) -> bool:
        """Whether this is a ``#local`` reference into the containing resource.

        The scope it keys in is derived by ``IdentityService`` from the policy
        table, not here: the rule is identity policy, and a dataclass with no
        policy in hand is exactly where it stopped being reviewable.
        """
        return self.kind == "contained"

    def as_dict(self) -> Dict[str, Any]:
        out = {
            "evidence_id": self.evidence_id,
            "kind": self.kind,
            "source_scope": self.source_scope.as_dict(),
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "canonical_url": self.canonical_url,
            "resource_version_id": self.resource_version_id,
            "identifier_system": self.identifier_system,
            "identifier_value": self.identifier_value,
            "detail": dict(self.detail),
        }
        if self.is_contained():
            out["container_url"] = self.container_url
        return out


@dataclass(frozen=True)
class IdentityRequest:
    """A reference to turn into a project entity IRI.

    ``candidates`` may be empty (unresolved), hold one entry, or hold several
    (ambiguous unless they all agree). Order is irrelevant to the outcome.
    """

    reference_literal: str
    expected_resource_types: Tuple[str, ...]
    candidates: Tuple[ReferenceEvidence, ...] = ()
    entity_kind: str = "person"
    referring_resource_url: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "reference_literal": self.reference_literal,
            "expected_resource_types": list(self.expected_resource_types),
            "entity_kind": self.entity_kind,
            "referring_resource_url": self.referring_resource_url,
            "candidate_count": len(self.candidates),
        }


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntityIdentity:
    """A project entity IRI plus the lineage that justifies it.

    The FHIR reference is retained alongside the IRI. It is lineage, not an
    equivalence claim: nothing here licenses ``owl:sameAs`` between the FHIR
    resource and the entity (concept note section 2).
    """

    entity_iri: str
    entity_kind: str
    source_reference_literal: str
    source_scope_id: str
    source_resource_type: str
    source_resource_id: str
    source_canonical_url: Optional[str]
    key_scheme: str
    key_inputs: Mapping[str, Any]
    rule_id: str

    def lineage(self) -> Dict[str, Any]:
        """Everything Agent 3/6 need to attach ``prov:wasDerivedFrom``."""
        return {
            "entity_iri": self.entity_iri,
            "source_reference_literal": self.source_reference_literal,
            "source_scope_id": self.source_scope_id,
            "source_resource_type": self.source_resource_type,
            "source_resource_id": self.source_resource_id,
            "source_canonical_url": self.source_canonical_url,
            "lineage_predicate": "http://www.w3.org/ns/prov#wasDerivedFrom",
            "equivalence_asserted": False,
        }

    def as_dict(self) -> Dict[str, Any]:
        out = self.lineage()
        out.update(
            {
                "entity_kind": self.entity_kind,
                "key_scheme": self.key_scheme,
                "key_inputs": dict(self.key_inputs),
                "rule_id": self.rule_id,
            }
        )
        return out


_LEAKY_NAMES = frozenset(
    {"identity", "entity_iri", "iri", "person", "person_iri", "value", "quality_iri"}
)


@dataclass(frozen=True)
class IdentityResolved:
    """A reference resolved to exactly one entity."""

    identity: EntityIdentity
    record: DecisionRecord
    is_resolved: ClassVar[Literal[True]] = True
    status: ClassVar[Literal["mapped"]] = "mapped"

    def unwrap(self) -> EntityIdentity:
        return self.identity


@dataclass(frozen=True)
class IdentityRejected:
    """A reference that must not become an entity IRI.

    Deliberately has no attribute holding an IRI. ``unwrap()`` raises.
    """

    reason_code: str
    reason: str
    record: DecisionRecord
    is_resolved: ClassVar[Literal[False]] = False
    status: ClassVar[Literal["rejected"]] = "rejected"

    def unwrap(self) -> NoReturn:
        raise IdentityUnavailable(self.reason_code, self.reason, self.record)

    def __getattr__(self, name: str) -> NoReturn:
        # Only reached for attributes that do not exist on the dataclass.
        if name in _LEAKY_NAMES:
            raise IdentityUnavailable(self.reason_code, self.reason, self.record)
        raise AttributeError(name)

    def __str__(self) -> str:
        return "IdentityRejected(%s: %s)" % (self.reason_code, self.reason)


IdentityOutcome = Union[IdentityResolved, IdentityRejected]


def require_identity(outcome: IdentityOutcome) -> EntityIdentity:
    """Narrow an outcome or raise. For callers that genuinely cannot continue."""
    return outcome.unwrap()


# ---------------------------------------------------------------------------
# Quality identity (the reviewer's open decision)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QualityRequest:
    """A request for the IRI of the quality an observation refers to.

    ``person`` is an ``EntityIdentity``, not a string, so this request cannot be
    constructed from a rejected reference.
    """

    person: EntityIdentity
    quality_class_iri: str
    observable_system: str
    observable_code: str
    source_resource_canonical_url: Optional[str] = None
    source_resource_version_id: Optional[str] = None
    effective_time: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "person_entity_iri": self.person.entity_iri,
            "quality_class_iri": self.quality_class_iri,
            "observable_system": self.observable_system,
            "observable_code": self.observable_code,
            "source_resource_canonical_url": self.source_resource_canonical_url,
            "source_resource_version_id": self.source_resource_version_id,
            "effective_time": self.effective_time,
        }


@dataclass(frozen=True)
class QualityIdentity:
    quality_iri: str
    quality_class_iri: str
    person_entity_iri: str
    mode: str
    key_inputs: Mapping[str, Any]
    rule_id: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "quality_iri": self.quality_iri,
            "quality_class_iri": self.quality_class_iri,
            "person_entity_iri": self.person_entity_iri,
            "mode": self.mode,
            "key_inputs": dict(self.key_inputs),
            "rule_id": self.rule_id,
        }


@dataclass(frozen=True)
class QualityResolved:
    identity: QualityIdentity
    record: DecisionRecord
    is_resolved: ClassVar[Literal[True]] = True
    status: ClassVar[Literal["mapped"]] = "mapped"

    def unwrap(self) -> QualityIdentity:
        return self.identity


@dataclass(frozen=True)
class QualityRejected:
    reason_code: str
    reason: str
    record: DecisionRecord
    is_resolved: ClassVar[Literal[False]] = False
    status: ClassVar[Literal["rejected"]] = "rejected"

    def unwrap(self) -> NoReturn:
        if self.reason_code == "quality-identity-policy-unset":
            raise QualityIdentityPolicyUnset(self.reason_code, self.reason, self.record)
        raise IdentityUnavailable(self.reason_code, self.reason, self.record)

    def __getattr__(self, name: str) -> NoReturn:
        if name in _LEAKY_NAMES:
            self.unwrap()
        raise AttributeError(name)

    def __str__(self) -> str:
        return "QualityRejected(%s: %s)" % (self.reason_code, self.reason)


QualityOutcome = Union[QualityResolved, QualityRejected]


def require_quality(outcome: QualityOutcome) -> QualityIdentity:
    return outcome.unwrap()
