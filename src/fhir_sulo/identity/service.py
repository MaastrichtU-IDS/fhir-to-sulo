"""The identity service: resolved FHIR reference + evidence -> project entity IRI.

Deterministic, offline, and stateless. The same request produces the same IRI in
any process, in any order, on any host, forever, for a given policy version.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..policy import DecisionRecord, PolicyBundle, key_fragment, normalise_text, slugify
from .types import (
    EntityIdentity,
    IdentityOutcome,
    IdentityRejected,
    IdentityRequest,
    IdentityResolved,
    QualityIdentity,
    QualityOutcome,
    QualityRejected,
    QualityRequest,
    QualityResolved,
    ReferenceEvidence,
)

__all__ = ["IdentityService"]

_KEY_SCHEME_VERSION = "fhir-sulo-entity-key/1"
_QUALITY_KEY_SCHEME_VERSION = "fhir-sulo-quality-key/1"


class PolicyInconsistent(ValueError):
    """The identity policy contradicts itself.

    Distinct from an undeclared entity kind, which is a caller error. This one
    is a defect in ``policies/identity-policy.v1.json`` and must not be
    recorded against the request's ``entity_kind``.
    """

class _UnscopedContained(ValueError):
    """Internal: a contained reference arrived with no container to scope it to.

    Never escapes ``resolve()`` -- it is turned into an ``IdentityRejected``
    before any key is built. It exists so the scoping helper cannot be called
    on an unscopable candidate and quietly return the dataset scope.
    """


class IdentityService:
    """Maps references to entity IRIs under a loaded, versioned policy."""

    def __init__(self, policy: Optional[PolicyBundle] = None) -> None:
        self.policy = policy if policy is not None else PolicyBundle.load()
        self._iri = self.policy.identity["entity_iri"]
        self._quality = self.policy.identity["quality_identity"]
        self._contained = self.policy.identity["contained_reference_scoping"]

    # -- contained-reference scoping (IR-604) -----------------------------
    #
    # A FHIR contained resource has no existence outside its container, so
    # '#p-inline' in two Observations is two people. That rule used to live in
    # every caller: the pipeline baked it into SourceScope.scope_id and the
    # ingest mock had a second, incompatible formula. It is identity policy,
    # so it is declared in policies/identity-policy.v1.json and applied here.

    def _effective_scope_id(self, evidence: ReferenceEvidence) -> str:
        """The scope this evidence keys in. Raises if a contained one is unscoped."""
        if not evidence.is_contained():
            return evidence.source_scope.scope_id
        if not evidence.container_url:
            raise _UnscopedContained(
                "contained reference %r has no container_url, so it cannot be "
                "scoped to its container; keying it on the dataset scope alone "
                "would merge every %r in %r into one entity"
                % (
                    evidence.resource_id,
                    evidence.resource_id,
                    evidence.source_scope.scope_id,
                )
            )
        return str(self._contained["scope_id_template"]).format(
            scope_id=evidence.source_scope.scope_id,
            container_url=evidence.container_url,
        )

    def _effective_resource_id(self, evidence: ReferenceEvidence) -> str:
        if evidence.is_contained() and self._contained.get(
            "strip_leading_hash_from_resource_id"
        ):
            return evidence.resource_id.lstrip("#")
        return evidence.resource_id

    def _key_triple(self, evidence: ReferenceEvidence) -> Tuple[str, str, str]:
        return (
            self._effective_scope_id(evidence),
            evidence.resource_type,
            self._effective_resource_id(evidence),
        )

    # -- versioning -------------------------------------------------------

    @property
    def policy_versions(self) -> Dict[str, str]:
        """Goes straight into ``RunRecord``."""
        return self.policy.versions

    # -- person / agent identity -----------------------------------------

    def resolve(self, request: IdentityRequest) -> IdentityOutcome:
        """Resolve one reference. Never returns ``None`` and never guesses."""
        inputs = request.as_dict()
        evidence = tuple(c.as_dict() for c in _sorted_candidates(request.candidates))

        if not request.candidates:
            return self._reject(
                "ID-R2-no-candidate",
                "unresolved-reference",
                "reference %r resolved to no candidate; reference resolution supplied no evidence"
                % request.reference_literal,
                inputs,
                evidence,
            )

        wrong_type = [
            c
            for c in request.candidates
            if normalise_text(c.resource_type) not in request.expected_resource_types
        ]
        if wrong_type:
            return self._reject(
                "ID-R5-unexpected-type",
                "unexpected-resource-type",
                "reference %r resolved to resource type(s) %s, expected one of %s"
                % (
                    request.reference_literal,
                    sorted({c.resource_type for c in wrong_type}),
                    list(request.expected_resource_types),
                ),
                inputs,
                evidence,
            )

        unscoped = [
            c for c in request.candidates if c.is_contained() and not c.container_url
        ]
        if unscoped:
            return self._reject(
                "ID-R9-contained-without-a-container",
                str(self._contained["missing_container_url_reason_code"]),
                "reference %r is contained but no container_url was supplied, so it "
                "cannot be scoped to its container. %s"
                % (
                    request.reference_literal,
                    self._contained["missing_container_url_note"],
                ),
                inputs,
                evidence,
            )

        triples = {self._key_triple(c) for c in request.candidates}
        if len(triples) > 1:
            return self._reject(
                "ID-R3-discordant-candidates",
                "ambiguous-reference",
                "reference %r resolved to %d distinct (source scope, resource type, "
                "resource id) triples: %s. No reviewed cross-source merge rule exists, "
                "so this is not merged."
                % (request.reference_literal, len(triples), sorted(triples)),
                inputs,
                evidence,
            )

        chosen = _sorted_candidates(request.candidates)[0]
        scope_id = self._effective_scope_id(chosen)
        resource_id = self._effective_resource_id(chosen)
        if chosen.is_contained():
            rule_id = "ID-R8-contained-scoped-to-its-container"
        elif len(request.candidates) == 1:
            rule_id = "ID-R1-single-candidate"
        else:
            rule_id = "ID-R4-concordant-candidates"

        style = self._iri["key_style"]
        if style == "legacy-concept-note":
            permitted = normalise_text(str(self._iri["single_source_scope"]))
            if normalise_text(scope_id) != permitted:
                return self._reject(
                    "ID-R7-cross-scope-under-legacy-key",
                    "cross-scope-under-unscoped-key",
                    "key_style 'legacy-concept-note' only keys scope %r, but this "
                    "reference resolved in scope %r. Keying it would risk merging two "
                    "people who share a resource id."
                    % (permitted, chosen.source_scope.scope_id),
                    inputs,
                    evidence,
                )

        key_inputs = {
            "key_scheme": _KEY_SCHEME_VERSION,
            # Deliberately the key revision, not the table's semantic version:
            # an entity IRI must not move when a policy edit did not change the
            # keying answer. See DR-401 section 2.
            "key_revision": str(self._iri["key_revision"]),
            "entity_kind": request.entity_kind,
            # Effective, not raw: for a contained reference these carry the
            # container scoping the service applied (IR-604). The raw values
            # stay visible in the recorded evidence.
            "source_scope_id": scope_id,
            "resource_type": chosen.resource_type,
            "resource_id": resource_id,
        }

        try:
            self._entity_kind_segment(str(request.entity_kind))
        except PolicyInconsistent as exc:
            # NOT the caller's fault. Reporting this as ID-R10 would blame the
            # request's entity_kind, in the audit trail, for a policy that
            # contradicts itself -- loud, but the wrong diagnosis.
            return self._reject(
                "ID-R11-policy-self-contradiction",
                "identity-policy-inconsistent",
                str(exc),
                inputs,
                evidence,
            )
        except ValueError as exc:
            return self._reject(
                "ID-R10-undeclared-entity-kind",
                "undeclared-entity-kind",
                str(exc),
                inputs,
                evidence,
            )

        try:
            local_name = self._entity_local_name(key_inputs, chosen)
        except (KeyError, ValueError) as exc:
            return self._reject(
                "ID-R6-incomplete-key-inputs",
                "incomplete-key-inputs",
                "cannot build a stable key for %r: %s" % (request.reference_literal, exc),
                inputs,
                evidence,
            )

        identity = EntityIdentity(
            entity_iri=self._iri["base"] + local_name,
            entity_kind=request.entity_kind,
            source_reference_literal=request.reference_literal,
            source_scope_id=scope_id,
            source_resource_type=chosen.resource_type,
            source_resource_id=resource_id,
            source_canonical_url=chosen.canonical_url,
            key_scheme=style,
            key_inputs=key_inputs,
            rule_id=rule_id,
        )
        record = DecisionRecord(
            service="identity",
            rule_id=rule_id,
            status="mapped",
            inputs=inputs,
            evidence=evidence,
            outcome=identity.as_dict(),
            policy_versions=self.policy_versions,
        )
        return IdentityResolved(identity=identity, record=record)

    def _entity_kind_segments(self) -> Mapping[str, str]:
        declared = dict(self._iri.get("entity_kind_segments") or {})
        alias = self._iri.get("person_segment")
        # The alias is kept for readers that predate the map; disagreement
        # between the two would silently re-key every person IRI.
        if alias is not None and declared.get("person") not in (None, alias):
            raise PolicyInconsistent(
                "identity policy disagrees with itself: person_segment is %r but "
                "entity_kind_segments['person'] is %r" % (alias, declared["person"])
            )
        if alias is not None:
            declared.setdefault("person", alias)
        return declared

    def _entity_kind_segment(self, kind: str) -> str:
        segments = self._entity_kind_segments()
        try:
            return segments[kind]
        except KeyError:
            raise ValueError(
                "entity kind %r is not declared in identity policy entity_kind_segments %s. "
                "An entity kind is an identity criterion, so it must name a rigid property; "
                "a role such as 'practitioner' or 'patient' belongs on a Role individual, not "
                "on the person's identity (DR-010)." % (kind, sorted(segments))
            ) from None

    def _entity_local_name(
        self, key_inputs: Mapping[str, Any], chosen: ReferenceEvidence
    ) -> str:
        style = self._iri["key_style"]
        # Declared segments only. This used to slugify ANY kind it was handed,
        # which is how entity_kind="practitioner" became practitioner-<hash>:
        # an anti-rigid property acting as an identity criterion (DR-010).
        # resolve() rejects an undeclared kind before reaching here; this raises
        # so no other caller can slip past the policy either.
        segment = self._entity_kind_segment(str(key_inputs["entity_kind"]))
        length = int(self._iri["key_length_hex_chars"])
        fields: Sequence[str] = tuple(self._iri["key_input_fields"])

        if style == "scoped-hash":
            return segment + key_fragment(fields, key_inputs, length=length)
        if style == "scoped-slug":
            return "%s%s-%s-%s" % (
                segment,
                slugify(chosen.source_scope.scope_id),
                slugify(chosen.resource_id),
                key_fragment(fields, key_inputs, length=8),
            )
        if style == "legacy-concept-note":
            # Scope is fixed by policy and checked above, so the resource id alone
            # is a complete key within the one permitted scope.
            return segment + slugify(chosen.resource_id)
        raise ValueError("unsupported key_style %r" % style)

    # -- quality identity --------------------------------------------------

    def resolve_quality(self, request: QualityRequest) -> QualityOutcome:
        """Resolve the quality IRI an observation's quantity ``refersTo``.

        Rejects while the policy mode is unset. That is the intended behaviour:
        the choice between a persisting quality and a per-observation quality is
        the clinical/ontology reviewer's, and no default is safe to guess.
        """
        inputs = request.as_dict()
        mode = self._quality.get("mode")

        if mode is None:
            return self._reject_quality(
                "QI-R0-policy-unset",
                "quality-identity-policy-unset",
                "quality_identity.mode is unset in %s. Concept note section 4 and plan "
                "Gate 0 reserve this decision for the clinical/ontology reviewer: does a "
                "quality IRI persist across observations for a patient, or is it keyed "
                "per observation, time and code? Both behaviours are implemented; set "
                "quality_identity.mode to 'persistent-per-person-code' or "
                "'per-observation' once decided." % self.policy.source_dir,
                inputs,
            )

        spec = self._quality["allowed_modes"][mode]
        fields: Sequence[str] = tuple(spec["key_input_fields"])
        key_inputs: Dict[str, Any] = {
            "key_scheme": _QUALITY_KEY_SCHEME_VERSION,
            "key_revision": str(self._quality["key_revision"]),
            "person_entity_iri": request.person.entity_iri,
            "quality_class_iri": request.quality_class_iri,
            "observable_system": request.observable_system,
            "observable_code": request.observable_code,
            "source_resource_canonical_url": request.source_resource_canonical_url,
            "source_resource_version_id": request.source_resource_version_id,
            "effective_time": request.effective_time,
        }

        try:
            fragment = key_fragment(
                fields, key_inputs, length=int(self._iri["key_length_hex_chars"])
            )
        except (KeyError, ValueError) as exc:
            return self._reject_quality(
                "QI-R2-incomplete-key-inputs",
                "incomplete-key-inputs",
                "mode %r requires %s, but %s" % (mode, list(fields), exc),
                inputs,
            )

        identity = QualityIdentity(
            quality_iri=self._iri["base"] + self._iri["quality_segment"] + fragment,
            quality_class_iri=request.quality_class_iri,
            person_entity_iri=request.person.entity_iri,
            mode=mode,
            key_inputs={k: key_inputs[k] for k in fields},
            rule_id="QI-R1-%s" % mode,
        )
        record = DecisionRecord(
            service="quality-identity",
            rule_id=identity.rule_id,
            status="mapped",
            inputs=inputs,
            outcome=identity.as_dict(),
            policy_versions=self.policy_versions,
        )
        return QualityResolved(identity=identity, record=record)

    # -- rejection helpers -------------------------------------------------

    def _reject(
        self,
        rule_id: str,
        reason_code: str,
        reason: str,
        inputs: Mapping[str, Any],
        evidence: Tuple[Mapping[str, Any], ...] = (),
    ) -> IdentityRejected:
        record = DecisionRecord(
            service="identity",
            rule_id=rule_id,
            status="rejected",
            inputs=inputs,
            evidence=evidence,
            outcome={"entity_iri": None, "rejected": True},
            policy_versions=self.policy_versions,
            reason_code=reason_code,
            reason=reason,
        )
        return IdentityRejected(reason_code=reason_code, reason=reason, record=record)

    def _reject_quality(
        self, rule_id: str, reason_code: str, reason: str, inputs: Mapping[str, Any]
    ) -> QualityRejected:
        record = DecisionRecord(
            service="quality-identity",
            rule_id=rule_id,
            status="rejected",
            inputs=inputs,
            outcome={"quality_iri": None, "rejected": True},
            policy_versions=self.policy_versions,
            reason_code=reason_code,
            reason=reason,
        )
        return QualityRejected(reason_code=reason_code, reason=reason, record=record)


def _sorted_candidates(
    candidates: Sequence[ReferenceEvidence],
) -> List[ReferenceEvidence]:
    """Total, content-based ordering so candidate order cannot affect output.

    Ordered on the raw fields, not the contained-scoped ones: this runs before
    scoping is applied (an unscoped contained candidate has no effective scope
    and would raise), and by the time a candidate is chosen the service has
    already established that every candidate shares one key triple, so any
    total order picks an equivalent one.
    """
    return sorted(
        candidates,
        key=lambda c: (
            normalise_text(c.source_scope.scope_id),
            normalise_text(c.resource_type),
            normalise_text(c.resource_id),
            normalise_text(c.kind),
            normalise_text(c.container_url or ""),
            normalise_text(c.evidence_id),
        ),
    )
