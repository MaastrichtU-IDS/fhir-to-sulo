"""Profile conformance checking for profiles the pilot CLAIMS (R9a).

Before R9a, ``SourceContext.validated_profiles`` meant "declared in
``meta.profile`` and recognised by the manifest" -- a resource could claim
``vitalsigns`` and be reported as validated with nothing checking it. That is
the failure this module exists to remove: a profile is reported as validated
only if it was checked and passed.

Scope is **what the resource declares**, not its type. ``vitalsigns`` applies
to an Observation that declares it; eGFR is not a vital sign and forcing
``category = vital-signs`` on it would be wrong. That is also what
``meta.profile`` means in FHIR.

The constraints are **data**, declared per profile in
``profiles/fhir-r4-pilot.json``, so what is enforced stays reviewable next to
what is claimed. The set is a deliberate subset and the manifest says which
parts of ``vitalsigns`` are NOT enforced.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple


class ProfileConformanceError(ValueError):
    """A resource declared a profile the pilot enforces, and does not satisfy it.

    Rejection, not a note: claiming conformance means refusing input that
    does not conform, otherwise the claim is decoration.
    """

    def __init__(self, profile: str, violations: Sequence[Tuple[str, str]]):
        self.profile = profile
        self.violations = tuple(violations)
        detail = "; ".join("%s: %s" % (cid, msg) for cid, msg in violations)
        super().__init__(
            "resource declares %s but does not conform -- %s" % (profile, detail)
        )


def _codings(resource: Mapping[str, Any], path: str) -> List[Mapping[str, Any]]:
    """Codings under a CodeableConcept element, which may be a list or not."""
    node = resource.get(path)
    if node is None:
        return []
    items = node if isinstance(node, list) else [node]
    out: List[Mapping[str, Any]] = []
    for item in items:
        if isinstance(item, Mapping):
            for coding in item.get("coding") or ():
                if isinstance(coding, Mapping):
                    out.append(coding)
    return out


def _present(resource: Mapping[str, Any], path: str) -> bool:
    value = resource.get(path)
    if value is None:
        return False
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return False
    return True


def _check(resource: Mapping[str, Any], rule: Mapping[str, Any]):
    kind = rule.get("kind")
    message = rule.get("message") or rule.get("id", "constraint")

    if kind == "coding-present":
        ok = any(
            c.get("system") == rule["system"] and c.get("code") == rule["code"]
            for c in _codings(resource, rule["path"])
        )
    elif kind == "coding-system-present":
        ok = any(c.get("system") == rule["system"]
                 for c in _codings(resource, rule["path"]))
    elif kind == "element-present":
        ok = _present(resource, rule["path"])
    elif kind == "one-of-present":
        ok = any(_present(resource, p) for p in rule["paths"])
    elif kind == "value-or-component":
        # vs-2. Only bites when the observation carries neither structure.
        has_children = _present(resource, "component") or _present(resource, "hasMember")
        has_value = any(k.startswith("value") for k in resource) or _present(
            resource, "dataAbsentReason")
        ok = has_children or has_value
    else:
        # An unknown constraint kind must NOT silently pass: that would be a
        # claim nothing checks, which is the thing this module removes.
        raise ProfileConformanceError(
            rule.get("profile", "<unknown>"),
            [(rule.get("id", "?"),
              "constraint kind %r is declared in the manifest but not implemented" % (kind,))],
        )
    return ok, message


def enforceable_profiles(manifest, resource_type: str) -> Dict[str, Sequence[Mapping[str, Any]]]:
    """Declared profiles that carry constraints this pilot can actually check."""
    entry = manifest.data["resources"].get(resource_type) or {}
    out: Dict[str, Sequence[Mapping[str, Any]]] = {}
    for prof in entry.get("pinned_profiles", ()):
        if prof.get("role") == "validated" and prof.get("constraints"):
            out[prof["canonical"]] = prof["constraints"]
    return out


def check_declared_profiles(manifest, resource: Mapping[str, Any]) -> Tuple[str, ...]:
    """Check every declared profile the pilot enforces. Returns those that passed.

    Raises ``ProfileConformanceError`` on the first non-conformant profile.
    A declared profile with no enforceable constraints is simply not returned:
    it was not checked, so it is not reported as validated.
    """
    rtype = resource.get("resourceType")
    declared = tuple(str(p) for p in (resource.get("meta", {}).get("profile") or ()))
    if not declared:
        return ()

    enforceable = enforceable_profiles(manifest, rtype)
    passed: List[str] = []
    for profile in declared:
        rules = enforceable.get(profile)
        if not rules:
            continue
        violations = [
            (rule.get("id", "?"), message)
            for rule, (ok, message) in ((r, _check(resource, r)) for r in rules)
            if not ok
        ]
        if violations:
            raise ProfileConformanceError(profile, violations)
        passed.append(profile)
    return tuple(passed)
