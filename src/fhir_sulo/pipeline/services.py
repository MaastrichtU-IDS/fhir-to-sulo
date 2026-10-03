"""Host-side service calls the maps need: policy, ingest, identity, terminology.

Moved here from the test harness. Concept note section 3 gives the host map
selection, identity, terminology, batching and versioning; this is that work,
in production code, so the composed path does not have to import from
``tests/``.

Nothing here constructs a target triple. Each function answers one question a
map's run-binding manifest declares it needs answered -- who is this reference,
what is this quality's IRI, what is this unit's IRI -- and the answers travel
into the engine as ``staticVars``.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional


def policy_bundle(quality_mode: Optional[str] = "per-observation"):
    """The pinned policy tables, with the quality-identity mode set explicitly.

    The shipped default is ``None`` and rejects every request (review item R2).
    A test that wants a materialized graph must therefore name a mode, which is
    the point: no run can silently pick one.
    """
    from fhir_sulo.policy import PolicyBundle

    bundle = PolicyBundle.load()
    identity = copy.deepcopy(dict(bundle.identity))
    identity["quality_identity"]["mode"] = quality_mode
    return PolicyBundle(
        identity=identity,
        code_interpretation=bundle.code_interpretation,
        unit=bundle.unit,
        source_dir=bundle.source_dir,
    )


SCOPE_ID = "synthea-pilot-r4"
FHIR_BASE = "https://fhir.example/"


class ReferenceNotAPerson(RuntimeError):
    """The host declined to claim an entity for this FHIR reference.

    Concept note section 2 and the frozen ``ResolvedReference`` contract: a
    resolved FHIR reference carries no person-equivalence claim, and an
    ambiguous one must never silently merge.  Raised instead of inventing
    candidate evidence for the identity service to reject.
    """

    def __init__(self, reason_code: str, reason: str) -> None:
        super().__init__("%s: %s" % (reason_code, reason))
        self.reason_code = reason_code
        self.reason = reason


def source_context(json_path: Path):
    """Agent 2's ``SourceContext``: rendered RDF, resolved references, eligibility."""
    from fhir_sulo.ingest import ingest_file

    return ingest_file(str(json_path))


def entity_for_reference(svc, ctx, element_path: str, expected_type: str):
    """Agent 5's ``EntityIdentity`` for one of Agent 2's resolved references.

    The candidate evidence comes from Agent 2's reference resolver; nothing is
    fabricated.  An ambiguous or unresolvable reference therefore yields no
    entity, which is why ``egfr-reference-ambiguous`` and
    ``egfr-reference-unresolvable`` cannot produce a target graph even though
    their source shape is otherwise conformant.
    """
    from fhir_sulo.identity import IdentityRequest, ReferenceEvidence, SourceScope

    ref = ctx.resolved_references[element_path]
    ev = ref.evidence

    if ref.ambiguous or ev.kind == "ambiguous":
        raise ReferenceNotAPerson(
            "ambiguous-reference",
            "%s resolved ambiguously (%s); no reviewed merge rule exists, so no "
            "entity is claimed" % (ev.raw_reference, "; ".join(ev.notes)),
        )

    if ev.resolved_target is None or ev.kind in ("unresolvable", "identifier-only"):
        # Zero candidates: the identity service's own ID-R2 rejection.
        outcome = svc.resolve(IdentityRequest(ev.raw_reference, (expected_type,), ()))
        raise ReferenceNotAPerson(outcome.reason_code, outcome.reason)

    # IR-604: contained-reference scoping used to be applied here, by building
    # "<scope>|contained|<container url>" into SourceScope.scope_id and
    # stripping the '#' by hand. The identity service owns that rule now --
    # it is declared in policies/identity-policy.v1.json under
    # contained_reference_scoping -- so this caller states the facts and lets
    # the service derive the scope. The resulting IRIs are unchanged.
    if ev.kind == "contained":
        resource_id = ev.resolved_target
        canonical = None
        container_url = ctx.canonical_url
    else:
        resource_id = ev.resolved_target.rsplit("/", 1)[-1]
        canonical = ev.resolved_target
        container_url = None

    evidence = ReferenceEvidence(
        evidence_id=element_path,
        kind=ev.kind,
        source_scope=SourceScope(SCOPE_ID, FHIR_BASE),
        resource_type=expected_type,
        resource_id=resource_id,
        canonical_url=canonical,
        container_url=container_url,
    )
    kind = "person" if expected_type == "Patient" else "practitioner"
    outcome = svc.resolve(
        IdentityRequest(ev.raw_reference, (expected_type,), (evidence,), entity_kind=kind,
                        referring_resource_url=ctx.canonical_url)
    )
    if not outcome.is_resolved:
        raise ReferenceNotAPerson(outcome.reason_code, outcome.reason)
    return outcome.unwrap()


def quality_iri(svc, person, quality_class: str, system: str, code: str,
                canonical_url: str, version_id: str, effective: Optional[str]):
    from fhir_sulo.identity import QualityRequest

    return svc.resolve_quality(
        QualityRequest(
            person=person,
            quality_class_iri=quality_class,
            observable_system=system,
            observable_code=code,
            source_resource_canonical_url=canonical_url,
            source_resource_version_id=version_id,
            effective_time=effective,
        )
    )


def unit_iri(term_svc, system: str, code: str, dimension: str) -> str:
    from fhir_sulo.terminology import UnitRef

    return term_svc.resolve_unit(UnitRef(system, code), expected_dimension=dimension).unwrap().unit_iri
