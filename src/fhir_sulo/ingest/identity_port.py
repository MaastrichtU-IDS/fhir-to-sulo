"""The narrow interface ingestion needs from Agent 5's identity service.

Agent 5 owns the real implementation and its policy tables. This module owns
only the *shape of the call* and a deterministic mock, so ingestion can be
tested and Gate 1 can run before Agent 5 lands. Nothing here imports Agent 5's
code, and Agent 5 is not expected to import this module: the shared vocabulary
is ``fhir_sulo.contracts.ResolvedReference``, which is already frozen.

Interface, proposed in DR-103 and to be confirmed by Agent 5
------------------------------------------------------------
::

    establish(refs: Mapping[str, ResolvedReference],
              subject_context: SubjectContext) -> Mapping[str, ResolvedReference]

* Input: exactly what :mod:`fhir_sulo.ingest.references` produced - the raw
  reference plus its ``ReferenceEvidence``. Ingestion never proposes an entity
  IRI and never guesses a person.
* Output: the *same* keys, with ``entity_iri``, ``identity_policy_version``
  and, where applicable, ``ambiguous``/``ambiguity_reason`` filled in.
* The service must not invent an IRI for evidence of kind ``unresolvable`` or
  ``identifier-only`` without saying which policy rule allowed it; that is what
  ``identity_policy_version`` is for.
* Ambiguity is returned, never resolved by picking one. Setting
  ``ambiguous=True`` makes ``require_entity_iri()`` raise, which is the
  acceptance-matrix behaviour "ambiguous identity never silently merges".
* The call is pure with respect to ingestion: same input, same output, so that
  "running the same map twice yields the same graph identity" (Gate 1) is not
  defeated at the identity boundary.

Open point for Agent 5 (recorded in DR-103): whether ``establish`` also returns
an *entity class* (person vs practitioner vs contained-record-only). Ingestion
does not need it; Agent 3's target shapes might.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

from ..contracts import ReferenceEvidence, ResolvedReference


@dataclass(frozen=True)
class SubjectContext:
    """The scope within which an identity claim is being made.

    Concept note section 4 warns against silently merging independent records.
    The dataset/server scope is therefore part of the request, not an ambient
    assumption.
    """

    source_server_base: str
    dataset_id: str
    source_resource_iri: str
    source_version_id: str


class IdentityService:
    """The protocol. ``typing.Protocol`` is 3.8+, but this stays a plain ABC-ish
    base so the module imports cleanly on the pinned Python 3.9 CI runner."""

    policy_version: str = "unset"

    def establish(self, refs: Mapping[str, ResolvedReference],
                  subject_context: SubjectContext) -> Mapping[str, ResolvedReference]:
        raise NotImplementedError


class MockIdentityService(IdentityService):
    """Deterministic stand-in. Gate 1 asks Agent 5 for exactly this behaviour.

    Rules, in order:

    1. ``ambiguous`` evidence stays ambiguous. Never picked.
    2. ``unresolvable`` and ``identifier-only`` evidence get no ``entity_iri``.
    3. ``contained`` evidence gets an IRI scoped to the containing resource,
       because a contained resource has no independent existence. Two different
       Observations with a contained Patient ``#p`` therefore do NOT merge.
    4. Everything else gets a stable IRI derived from the resolved target, so
       ``Patient/p123`` from two resources is the same entity - the "repeated
       references resolve to one intended person" condition.

    The IRI is ``{namespace}{kind-prefix}-{sha256(scope-key)[:16]}``: opaque, so
    no downstream code can parse a FHIR id back out of it and re-introduce the
    record/fact confusion.
    """

    policy_version = "mock-identity/0.1.0"

    def __init__(self, namespace: str = "https://example.org/fhir-sulo/entity/"):
        self.namespace = namespace

    def establish(self, refs: Mapping[str, ResolvedReference],
                  subject_context: SubjectContext) -> Dict[str, ResolvedReference]:
        out: Dict[str, ResolvedReference] = {}
        for path, ref in refs.items():
            out[path] = self._establish_one(ref, subject_context)
        return out

    def _establish_one(self, ref: ResolvedReference,
                       ctx: SubjectContext) -> ResolvedReference:
        ev: ReferenceEvidence = ref.evidence
        if ref.ambiguous or ev.kind == "ambiguous":
            return ResolvedReference(
                evidence=ev, entity_iri=None,
                identity_policy_version=self.policy_version,
                ambiguous=True,
                ambiguity_reason=ref.ambiguity_reason or "ambiguous reference",
            )
        if ev.kind in ("unresolvable", "identifier-only") or ev.resolved_target is None:
            return ResolvedReference(
                evidence=ev, entity_iri=None,
                identity_policy_version=self.policy_version,
            )
        if ev.kind == "contained":
            scope_key = f"contained|{ctx.source_resource_iri}|{ev.resolved_target}"
            prefix = "contained"
        else:
            # Version-independent: Patient/p123 and Patient/p123/_history/2 are
            # the same entity. Stripping _history is the policy, stated here so
            # Agent 5 can agree or override it.
            target = ev.resolved_target.split("/_history/")[0]
            scope_key = f"resource|{ctx.source_server_base}|{ctx.dataset_id}|{target}"
            prefix = "entity"
        digest = hashlib.sha256(scope_key.encode("utf-8")).hexdigest()[:16]
        return ResolvedReference(
            evidence=ev,
            entity_iri=f"{self.namespace}{prefix}-{digest}",
            identity_policy_version=self.policy_version,
        )


class RefusingIdentityService(IdentityService):
    """Establishes nothing. The default for a run that has no identity policy.

    Using this makes every ``require_entity_iri()`` raise, which is the correct
    behaviour when no reviewed policy is in force: no person is claimed.
    """

    policy_version = "refusing/0.1.0"

    def establish(self, refs, subject_context):
        return {
            path: ResolvedReference(evidence=r.evidence, entity_iri=None,
                                    identity_policy_version=self.policy_version,
                                    ambiguous=r.ambiguous,
                                    ambiguity_reason=r.ambiguity_reason)
            for path, r in refs.items()
        }
