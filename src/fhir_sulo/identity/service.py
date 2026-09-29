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


class IdentityService:
    """Maps references to entity IRIs under a loaded, versioned policy."""

    def __init__(self, policy: Optional[PolicyBundle] = None) -> None:
        self.policy = policy if policy is not None else PolicyBundle.load()
        self._iri = self.policy.identity["entity_iri"]
        self._quality = self.policy.identity["quality_identity"]

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

        triples = {c.key_triple() for c in request.candidates}
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
        rule_id = (
            "ID-R1-single-candidate"
            if len(request.candidates) == 1
            else "ID-R4-concordant-candidates"
        )

        style = self._iri["key_style"]
        if style == "legacy-concept-note":
            permitted = normalise_text(str(self._iri["single_source_scope"]))
            if normalise_text(chosen.source_scope.scope_id) != permitted:
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
            "source_scope_id": chosen.source_scope.scope_id,
            "resource_type": chosen.resource_type,
            "resource_id": chosen.resource_id,
        }

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
            source_scope_id=chosen.source_scope.scope_id,
            source_resource_type=chosen.resource_type,
            source_resource_id=chosen.resource_id,
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

    def _entity_local_name(
        self, key_inputs: Mapping[str, Any], chosen: ReferenceEvidence
    ) -> str:
        style = self._iri["key_style"]
        segment = self._iri["person_segment"] if key_inputs["entity_kind"] == "person" else (
            slugify(str(key_inputs["entity_kind"])) + "-"
        )
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
    """Total, content-based ordering so candidate order cannot affect output."""
    return sorted(
        candidates,
        key=lambda c: (
            normalise_text(c.source_scope.scope_id),
            normalise_text(c.resource_type),
            normalise_text(c.resource_id),
            normalise_text(c.kind),
            normalise_text(c.evidence_id),
        ),
    )
