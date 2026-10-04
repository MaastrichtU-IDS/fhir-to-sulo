"""Which person-level identifier a source record carries (R8b).

The problem this solves. A BSN-style number lives on ``Patient.identifier``,
on the **Patient resource**. The pipeline ingests one ``Observation`` or
``Encounter`` at a time and never sees that resource, so the identifier it
would need in order to recognise one human across several healthcare systems
is not in front of it.

The index is the missing input, and it is deliberately an INPUT rather than a
lookup the identity service performs for itself:

* the service stays a pure function of (request, policy, index), so a replay
  with the same three reproduces the same IRIs, which DR-401 requires;
* the index carries a digest, so a run record can say WHICH index produced a
  graph -- two runs under different indexes give different entity IRIs, and
  that must be auditable rather than mysterious;
* building it is a separate pass that can read Patient resources from a
  Bundle, a directory, or an export, without any of that reaching the
  identity service.

Only **allowlisted** systems are indexed. An identifier that is not
person-identifying is not a near miss here, it is noise, and keeping it would
invite someone to key on it later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from ..policy import digest, normalise_text

__all__ = ["PersonIdentifierIndex", "PersonIdentifierConflict"]

#: Resource types whose own ``identifier`` array describes a PERSON.
#: An Observation's identifier describes the observation, not its subject.
PERSON_RESOURCE_TYPES = ("Patient", "Practitioner", "RelatedPerson")


class PersonIdentifierConflict(ValueError):
    """One source record carries two different person identifiers in one system.

    Not resolvable by choosing: picking either would make identity depend on
    element order, and the two values disagree about who this is.
    """


@dataclass(frozen=True)
class PersonIdentifierIndex:
    """``(scope_id, resource_type, resource_id) -> (system, value)``."""

    entries: Mapping[Tuple[str, str, str], Tuple[str, str]] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "PersonIdentifierIndex":
        """The default. Nothing merges, which is the conservative outcome."""
        return cls(entries={})

    @classmethod
    def build(
        cls,
        resources: Iterable[Mapping[str, Any]],
        *,
        scope_id: str,
        allowlist: Iterable[str],
    ) -> "PersonIdentifierIndex":
        """Index the allowlisted person identifiers on person-typed resources."""
        allowed = {normalise_text(s) for s in allowlist if s}
        out: Dict[Tuple[str, str, str], Tuple[str, str]] = {}
        if not allowed:
            return cls(entries=out)

        for resource in resources:
            rtype = str(resource.get("resourceType") or "")
            if rtype not in PERSON_RESOURCE_TYPES:
                continue
            rid = str(resource.get("id") or "")
            if not rid:
                continue
            found = set()
            for ident in resource.get("identifier") or ():
                if not isinstance(ident, Mapping):
                    continue
                system = normalise_text(str(ident.get("system") or ""))
                value = normalise_text(str(ident.get("value") or ""))
                if system and value and system in allowed:
                    found.add((system, value))
            if not found:
                continue
            if len(found) > 1:
                raise PersonIdentifierConflict(
                    "%s/%s in scope %r carries %d discordant person identifiers (%s). "
                    "Choosing one would make identity depend on element order."
                    % (rtype, rid, scope_id, len(found),
                       ", ".join("%s|%s" % p for p in sorted(found)))
                )
            out[(normalise_text(scope_id), rtype, rid)] = found.pop()
        return cls(entries=out)

    def merged_with(self, other: "PersonIdentifierIndex") -> "PersonIdentifierIndex":
        """Combine per-source indexes into one run-wide index.

        Keys include the scope, so two systems cannot overwrite each other.
        A genuine disagreement about one record is still a conflict.
        """
        combined = dict(self.entries)
        for key, pair in other.entries.items():
            if key in combined and combined[key] != pair:
                raise PersonIdentifierConflict(
                    "two indexes disagree about %s: %r vs %r" % (key, combined[key], pair)
                )
            combined[key] = pair
        return PersonIdentifierIndex(entries=combined)

    def lookup(self, scope_id: str, resource_type: str,
               resource_id: str) -> Optional[Tuple[str, str]]:
        return self.entries.get((normalise_text(scope_id), resource_type, resource_id))

    def as_dict(self) -> Dict[str, Any]:
        rows = [
            {
                "source_scope_id": scope,
                "resource_type": rtype,
                "resource_id": rid,
                "identifier_system": system,
                "identifier_value": value,
            }
            for (scope, rtype, rid), (system, value) in self.entries.items()
        ]
        rows.sort(key=lambda r: (r["source_scope_id"], r["resource_type"], r["resource_id"]))
        return {"format": "fhir-sulo/person-identifier-index/1", "entries": rows}

    @property
    def digest(self) -> str:
        """Identifies this index in a run record. Two indexes, two graphs."""
        return digest(self.as_dict())

    def __len__(self) -> int:
        return len(self.entries)
