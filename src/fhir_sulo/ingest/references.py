"""Reference resolution: literal, relative, absolute, contained and by-identifier.

What this module produces is **evidence**, never a person claim. Concept note
section 2: a FHIR ``Patient`` resource is not identical to a person, and a
resolved reference is not an identity assertion. So the output is
``ResolvedReference(evidence=..., entity_iri=None)`` and the only way to get an
IRI out is ``require_entity_iri()``, which raises until Agent 5's identity
service has supplied one under a recorded policy.

``ReferenceEvidence.kind`` is the discriminator the identity service is meant
to branch on, because the kinds are not equally trustworthy:

``literal-relative``
    ``"Patient/p123"`` against a known server base. Resolvable, and the target
    type is asserted by the reference itself.
``literal-absolute``
    ``"https://other.example/Patient/p9"``. Resolvable, but it names a
    different server; cross-server identity is Agent 5's policy call.
``literal-versioned``
    ``"Patient/p123/_history/2"``. Resolves to a specific version.
``contained``
    ``"#p-inline"``. Resolves only inside this resource. Concept note section 2's
    record/fact distinction bites hardest here: a contained Patient has no
    independent existence, so merging it with anything is a policy decision.
``identifier-only``
    No ``reference``, only ``Reference.identifier``. Not resolvable to a
    resource; carries a business identifier the identity service may use.
``unresolvable``
    Anything else, including a dangling contained reference.
``ambiguous``
    More than one candidate target (e.g. two contained resources sharing an id).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..contracts import ReferenceEvidence, ResolvedReference
from .manifest import Manifest, default_manifest

_RELATIVE = re.compile(r"^(?P<type>[A-Z][A-Za-z]+)/(?P<id>[A-Za-z0-9\-.]{1,64})"
                       r"(?:/_history/(?P<version>[A-Za-z0-9\-.]{1,64}))?$")
_ABSOLUTE = re.compile(r"^(?P<base>https?://\S+?/)(?P<type>[A-Z][A-Za-z]+)/(?P<id>[A-Za-z0-9\-.]{1,64})"
                       r"(?:/_history/(?P<version>[A-Za-z0-9\-.]{1,64}))?$")


def _note(*parts: str) -> Tuple[str, ...]:
    return tuple(p for p in parts if p)


class ReferenceResolver:
    """Resolves the reference-valued elements of one resource.

    ``expected_types`` lets the caller state what a given element is supposed
    to point at (``Observation.subject`` -> ``Patient``). A mismatch does not
    fail resolution; it is recorded as a note, because rejecting is the
    manifest's job and merging is Agent 5's.
    """

    def __init__(self, manifest: Optional[Manifest] = None,
                 effective_base: Optional[str] = None):
        self.m = manifest or default_manifest()
        #: DR-021. The base of the source these resources came from. "Same
        #: server" must be judged against THIS, not the pinned manifest:
        #: with a per-source base set, comparing against the pinned one
        #: refused the source's own absolute references and accepted
        #: references to the placeholder, which is exactly backwards.
        self.effective_base = effective_base

    def _base(self) -> str:
        return self.effective_base or self.m.server_base

    def resolve_resource(self, resource: Dict[str, Any],
                         expected_types: Optional[Dict[str, str]] = None
                         ) -> Dict[str, ResolvedReference]:
        """Return ``{fhirpath: ResolvedReference}`` for every reference found."""
        expected_types = expected_types or {}
        contained = self._index_contained(resource)
        out: Dict[str, ResolvedReference] = {}
        rtype = resource["resourceType"]
        for path, ref in self._find_references(resource, rtype, rtype):
            out[path] = self.resolve(
                ref, source_element=path, contained=contained,
                expected_type=expected_types.get(path),
            )
        return out

    # -- discovery ----------------------------------------------------------

    def _index_contained(self, resource: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        index: Dict[str, List[Dict[str, Any]]] = {}
        for entry in resource.get("contained", ()) or ():
            cid = entry.get("id")
            if cid is not None:
                index.setdefault(str(cid), []).append(entry)
        return index

    def _find_references(self, obj: Any, type_name: str, path: str):
        """Walk the pinned element table, yielding (fhirpath, Reference dict)."""
        if not isinstance(obj, dict):
            return
        for key, value in obj.items():
            if key == "resourceType":
                continue
            ed = self.m.element_def(type_name, key)
            ftype = ed["type"]
            items = value if ed.get("repeats") else [value]
            for index, item in enumerate(items):
                child = f"{path}.{key}" + (f"[{index}]" if ed.get("repeats") else "")
                if ftype == "Reference":
                    yield child, item
                    # A Reference may itself carry Reference.identifier.assigner.
                    assigner = (item or {}).get("identifier", {}).get("assigner")
                    if assigner:
                        yield f"{child}.identifier.assigner", assigner
                elif ftype == "#resource":
                    ctype = item.get("resourceType")
                    if ctype and self.m.has_type(ctype):
                        yield from self._find_references(item, ctype, child)
                elif not self.m.is_primitive(ftype):
                    yield from self._find_references(item, ftype, child)

    # -- resolution ---------------------------------------------------------

    def resolve(self, ref: Optional[Dict[str, Any]], source_element: str,
                contained: Optional[Dict[str, List[Dict[str, Any]]]] = None,
                expected_type: Optional[str] = None) -> ResolvedReference:
        contained = contained or {}
        ref = ref or {}
        literal = ref.get("reference")
        declared_type = ref.get("type")

        if literal is None:
            if ref.get("identifier"):
                ident = ref["identifier"]
                raw = f"identifier:{ident.get('system')}|{ident.get('value')}"
                return ResolvedReference(evidence=ReferenceEvidence(
                    kind="identifier-only", raw_reference=raw, resolved_target=None,
                    source_element=source_element,
                    # Structured, not only packed into raw_reference: the
                    # identity service must not have to parse a display string
                    # to decide identity (R8b).
                    identifier_system=ident.get("system"),
                    identifier_value=ident.get("value"),
                    notes=_note("no Reference.reference; only a business identifier",
                                "the identity service may match on this, the renderer may not"),
                ))
            return ResolvedReference(evidence=ReferenceEvidence(
                kind="unresolvable", raw_reference="", resolved_target=None,
                source_element=source_element,
                notes=("Reference has neither reference nor identifier",),
            ))

        text = str(literal)

        # ---- contained ----
        if text.startswith("#"):
            cid = text[1:]
            candidates = contained.get(cid, [])
            if len(candidates) == 1:
                target = candidates[0]
                ttype = target.get("resourceType")
                return ResolvedReference(evidence=ReferenceEvidence(
                    kind="contained", raw_reference=text,
                    resolved_target=f"#{cid}", source_element=source_element,
                    notes=_note(
                        f"contained {ttype} with id {cid!r}",
                        "a contained resource has no existence outside this resource; "
                        "cross-resource merging is an identity-policy decision",
                        _type_note(expected_type, ttype),
                    ),
                ))
            if len(candidates) > 1:
                return ResolvedReference(
                    evidence=ReferenceEvidence(
                        kind="ambiguous", raw_reference=text, resolved_target=None,
                        source_element=source_element,
                        notes=(f"{len(candidates)} contained resources share id {cid!r}",),
                    ),
                    ambiguous=True,
                    ambiguity_reason=f"{len(candidates)} contained resources share id {cid!r}",
                )
            return ResolvedReference(evidence=ReferenceEvidence(
                kind="unresolvable", raw_reference=text, resolved_target=None,
                source_element=source_element,
                notes=(f"no contained resource with id {cid!r}",),
            ))

        # ---- absolute ----
        m = _ABSOLUTE.match(text)
        if m:
            same_server = m.group("base") == self._base()
            return ResolvedReference(evidence=ReferenceEvidence(
                kind="literal-versioned" if m.group("version") else "literal-absolute",
                raw_reference=text, resolved_target=text, source_element=source_element,
                target_resource_type=m.group("type"),
                target_resource_id=m.group("id"),
                target_version_id=m.group("version"),
                target_server_base=None if same_server else m.group("base"),
                notes=_note(
                    f"absolute reference to {m.group('type')}/{m.group('id')}",
                    "" if same_server else
                    f"names a different server base {m.group('base')!r} than this "
                    f"source's {self._base()!r}; cross-server identity is an "
                    f"identity-policy decision",
                    f"version {m.group('version')}" if m.group("version") else "",
                    _type_note(expected_type, m.group("type")),
                    _declared_type_note(declared_type, m.group("type")),
                ),
            ))

        # ---- relative ----
        m = _RELATIVE.match(text)
        if m:
            return ResolvedReference(evidence=ReferenceEvidence(
                kind="literal-versioned" if m.group("version") else "literal-relative",
                raw_reference=text,
                resolved_target=self._base() + text,
                source_element=source_element,
                target_resource_type=m.group("type"),
                target_resource_id=m.group("id"),
                target_version_id=m.group("version"),
                notes=_note(
                    f"relative reference resolved against the source's server base "
                    f"{self._base()!r}",
                    f"version {m.group('version')}" if m.group("version") else "",
                    _type_note(expected_type, m.group("type")),
                    _declared_type_note(declared_type, m.group("type")),
                ),
            ))

        if text.startswith("urn:"):
            return ResolvedReference(evidence=ReferenceEvidence(
                kind="unresolvable", raw_reference=text, resolved_target=None,
                source_element=source_element,
                notes=("urn: references resolve only inside a Bundle; this pilot ingests "
                       "single resources, so there is no fullUrl to match",),
            ))

        return ResolvedReference(evidence=ReferenceEvidence(
            kind="unresolvable", raw_reference=text, resolved_target=None,
            source_element=source_element,
            notes=("does not match any FHIR reference form this pilot resolves",),
        ))


def _type_note(expected: Optional[str], actual: Optional[str]) -> str:
    if expected and actual and expected != actual:
        return (f"element expects a {expected} but the reference names a {actual}; "
                "recorded, not rejected - see the manifest value_policy")
    return ""


def _declared_type_note(declared: Optional[str], actual: Optional[str]) -> str:
    if declared and actual and str(declared) != actual:
        return f"Reference.type is {declared!r} but the literal names a {actual}"
    return ""


def resolve_resource(resource: Dict[str, Any], manifest: Optional[Manifest] = None,
                     expected_types: Optional[Dict[str, str]] = None):
    return ReferenceResolver(manifest).resolve_resource(resource, expected_types)
