"""Turn a map's run-binding manifest plus one fixture into an engine job.

This is the *host* side of concept note section 3: it selects a map, calls the
identity and terminology services, chooses root nodes, and unions the passes.
It constructs no target triple -- every triple in the output comes from a
schema in ``maps/r4/``.  Asserted by
``test_expected_graphs.py::ExpectedGraphContents::test_every_emitted_predicate_is_written_in_a_target_schema``,
which checks every predicate of every expected graph against the target
schema that produced it.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import engine

REPO = engine.REPO


def load_manifest(family: str, version: str = "v1") -> Dict[str, Any]:
    path = REPO / "maps/r4" / family / ("%s-bindings.%s.json" % (family, version))
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# services
# ---------------------------------------------------------------------------

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

    if ev.kind == "contained":
        # A contained resource has no existence outside its container, so the
        # identity scope is the containing resource.  Same rule as Agent 2's
        # proposed MockIdentityService; flagged to Agent 5 as something their
        # service, not its callers, should own.
        scope = SourceScope("%s|contained|%s" % (SCOPE_ID, ctx.canonical_url), FHIR_BASE)
        resource_id = ev.resolved_target.lstrip("#")
        canonical = None
    else:
        scope = SourceScope(SCOPE_ID, FHIR_BASE)
        resource_id = ev.resolved_target.rsplit("/", 1)[-1]
        canonical = ev.resolved_target

    evidence = ReferenceEvidence(
        evidence_id=element_path,
        kind=ev.kind,
        source_scope=scope,
        resource_type=expected_type,
        resource_id=resource_id,
        canonical_url=canonical,
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


# ---------------------------------------------------------------------------
# bindings
# ---------------------------------------------------------------------------

def bind(family: str, fixture: Path, focus: str, version: str = "v1") -> Dict[str, Any]:
    """Stage 1 only: validate the source shape and return the engine result."""
    return engine.run_job({
        "sourceSchema": engine.cpath("maps/r4/%s/%s-source.%s.shex" % (family, family, version)),
        "data": engine.cpath(str(fixture.relative_to(REPO))),
        "focus": focus,
        "startShape": None,
        "passes": [],
    })


def flat_bindings(bindings: Mapping[str, Any], var_ns: str) -> Dict[str, Any]:
    """``{shortName: {'value':..., 'type':...}}`` from a flat ShExMap binding tree."""
    out: Dict[str, Any] = {}
    for k, val in (bindings or {}).items():
        if k.startswith(var_ns):
            out[k[len(var_ns):]] = val
    return out


def lexical(b: Mapping[str, Any], name: str) -> Optional[str]:
    v = b.get(name)
    if v is None:
        return None
    return v["value"] if isinstance(v, dict) else v


def tagged(b: Mapping[str, Any], name: str) -> str:
    """``lexical^^datatype`` -- Agent 2's tuple convention (DR-102)."""
    v = b.get(name)
    if v is None:
        return ""
    if isinstance(v, dict):
        return v["value"] + ("^^" + v["type"] if v.get("type") else "")
    return str(v)


# ---------------------------------------------------------------------------
# job assembly
# ---------------------------------------------------------------------------

def build_passes(manifest: Mapping[str, Any], values: Mapping[str, str],
                 source_bindings: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """One engine pass per IRI-identified target node.

    ``values`` maps every manifest variable name that is not source-bound to
    the term the engine wants: a bare IRI string, or a ``{'value', 'type'}``
    dict for a literal.

    A pass carrying ``requires_source_binding`` runs only when the source
    schema actually bound that variable.  This is the whole of the host's
    conditional logic, and it is declared in the map's own manifest, not here.
    """
    var_ns = manifest["var_namespace"]
    shape_ns = manifest["shape_namespace"]
    source_bound = set(manifest.get("source_bound_vars", ()))
    passes = []
    for spec in manifest["passes"]:
        needs = spec.get("requires_source_binding")
        forbids = spec.get("forbids_source_binding")
        if needs is not None or forbids is not None:
            if source_bindings is None:
                raise ValueError("pass %r is conditional but no source bindings were given"
                                 % spec["name"])
            if needs is not None and not lexical(source_bindings, needs):
                continue
            if forbids is not None and lexical(source_bindings, forbids):
                continue
        statics = {}
        for name in spec["vars"]:
            if name in source_bound:
                continue
            if name not in values:
                raise KeyError(
                    "pass %r needs run binding %r and the host did not supply it"
                    % (spec["name"], name)
                )
            statics[var_ns + name] = values[name]
        passes.append({
            "name": spec["name"],
            "shape": shape_ns + spec["shape"],
            "root": values[spec["root"]],
            "staticVars": statics,
        })
    return passes


def node_keys(manifest: Mapping[str, Any], **fmt: str) -> Dict[str, str]:
    domain = manifest["domain_namespace"]["value"]
    return {
        name: template.format(domain=domain, **fmt)
        for name, template in manifest["node_keys"].items()
    }


def vocabulary(manifest: Mapping[str, Any]) -> Dict[str, str]:
    return {name: spec["iri"] for name, spec in manifest["vocabulary"].items()}
