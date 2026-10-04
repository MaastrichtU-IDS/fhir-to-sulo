"""What turning an identifier system on would do to existing entity IRIs.

Enabling a person-identifying identifier system, or supplying an index for
the first time, **moves** every entity IRI it covers: an identifier-keyed
person is keyed on `(system, value)` instead of on the record address, so the
hash changes. Graphs already written still carry the old IRIs.

That is a graph migration, not a configuration change, and this reports it
before it happens rather than after. It answers two questions a migration
needs: which records move, and which previously-separate people become one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .person_index import PersonIdentifierIndex
from .service import IdentityService
from .types import IdentityRequest, ReferenceEvidence, SourceScope

__all__ = ["RekeyReport", "RekeyRow", "plan_rekey"]


@dataclass(frozen=True)
class RekeyRow:
    source_scope_id: str
    resource_type: str
    resource_id: str
    before: str
    after: str

    @property
    def moved(self) -> bool:
        return self.before != self.after


@dataclass(frozen=True)
class RekeyReport:
    rows: Sequence[RekeyRow]

    @property
    def moved(self) -> List[RekeyRow]:
        return [r for r in self.rows if r.moved]

    @property
    def merges(self) -> Dict[str, List[RekeyRow]]:
        """New IRIs that more than one source record now shares.

        The point of the exercise: these are the people who were several
        entities and become one. Anything here is a claim that two records
        describe one human, so it is the part a reviewer should read.
        """
        by_after: Dict[str, List[RekeyRow]] = {}
        for row in self.rows:
            by_after.setdefault(row.after, []).append(row)
        return {iri: rows for iri, rows in by_after.items() if len(rows) > 1}

    def summary(self) -> str:
        merges = self.merges
        people = sum(len(rows) for rows in merges.values())
        return (
            "%d record(s) examined; %d entity IRI(s) move; %d record(s) collapse into "
            "%d person(s)." % (len(self.rows), len(self.moved), people, len(merges))
        )


def plan_rekey(
    records: Sequence[Tuple[str, str, str, str]],
    index: PersonIdentifierIndex,
    *,
    policy=None,
    entity_kind: str = "person",
) -> RekeyReport:
    """Resolve each record with and without the index and diff the IRIs.

    ``records`` are ``(scope_id, fhir_base_url, resource_type, resource_id)``.
    Both resolutions use the same policy, so the only variable is the index --
    which is what makes the diff attributable to it.
    """
    before_svc = IdentityService(policy, person_index=PersonIdentifierIndex.empty())
    after_svc = IdentityService(policy, person_index=index)

    rows: List[RekeyRow] = []
    for scope_id, base, resource_type, resource_id in records:
        evidence = ReferenceEvidence(
            evidence_id="rekey-plan",
            kind="literal-reference",
            source_scope=SourceScope(scope_id, base),
            resource_type=resource_type,
            resource_id=resource_id,
            canonical_url="%s%s/%s" % (base, resource_type, resource_id),
        )
        request = IdentityRequest(
            "%s/%s" % (resource_type, resource_id), (resource_type,), (evidence,),
            entity_kind=entity_kind)
        before = before_svc.resolve(request)
        after = after_svc.resolve(request)
        if not (before.is_resolved and after.is_resolved):
            # A record that cannot be keyed either way is not a migration
            # question; it is a rejection, and it is reported where rejections
            # are reported rather than silently dropped into a plan.
            continue
        rows.append(RekeyRow(
            source_scope_id=scope_id,
            resource_type=resource_type,
            resource_id=resource_id,
            before=before.unwrap().entity_iri,
            after=after.unwrap().entity_iri,
        ))
    return RekeyReport(rows=tuple(rows))
