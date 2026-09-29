"""TransformResult - the output of one mapping run over one source resource.

Plan section 3:

    Contains target RDF quads, binding tree, target root, per-quad source
    binding/constraint lineage, diagnostics, status (mapped, source-only, or
    rejected), and deterministic output graph key. Only mapped output can be
    loaded into a clinical semantic graph. The caller must be able to inspect
    all binding alternatives rather than accepting an ambiguous map silently.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence, Tuple


class TransformStatus(enum.Enum):
    MAPPED = "mapped"
    SOURCE_ONLY = "source-only"
    REJECTED = "rejected"


@dataclass(frozen=True)
class BindingNode:
    """One node of the binding tree, preserving repetition structure.

    ``scope`` names the RepetitionScope this node is an iteration of, and
    ``iteration_key`` is the tuple of key-variable values identifying it. A
    flat ``{variable: value}`` map cannot express two blood-pressure panels;
    this shape can, and ``tuples_for_scope`` below turns it back into the
    multiset the acceptance test compares.
    """

    shape: str
    focus: str
    bindings: Mapping[str, str]
    children: Tuple["BindingNode", ...] = ()
    scope: Optional[str] = None
    iteration_key: Tuple[str, ...] = ()

    def tuples_for_scope(self, scope: str, variables: Sequence[str]) -> Tuple[Tuple[str, ...], ...]:
        """Collect one tuple of ``variables`` per iteration of ``scope``.

        Returned as a tuple of tuples so a test can compare it as a multiset.
        This is the operation the "Repetition" acceptance row is written
        against: a cross-join shows up as a tuple that was never in the source.
        """
        found = []
        if self.scope == scope:
            found.append(tuple(self.bindings.get(v, "") for v in variables))
        for child in self.children:
            found.extend(child.tuples_for_scope(scope, variables))
        return tuple(found)

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass(frozen=True)
class QuadLineage:
    """Which binding or constant, and which constraint, produced one quad.

    Acceptance matrix row "Lineage": every quad traces to a source binding or
    constant plus source resource version, map hash, and run activity. The
    per-run parts live on RunRecord; the per-quad parts live here.
    """

    quad_index: int
    produced_by: str
    source_variable: Optional[str]
    source_constraint: Optional[str]
    iteration_key: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TransformResult:
    """The result of applying one MapContract to one SourceContext."""

    status: TransformStatus
    map_id: str
    pairing_hash: str
    source_canonical_url: str
    source_version_id: str
    output_graph_key: str
    target_quads: Tuple[str, ...] = ()
    target_root: Optional[str] = None
    binding_tree: Optional[BindingNode] = None
    lineage: Tuple[QuadLineage, ...] = ()
    binding_alternatives: Tuple[BindingNode, ...] = ()
    diagnostics: Tuple[str, ...] = field(default_factory=tuple)
    rejection_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status is not TransformStatus.MAPPED and self.target_quads:
            raise ValueError(
                f"{self.map_id}: status {self.status.value} must not carry target quads; "
                "only mapped output may reach a clinical semantic graph (plan section 3)"
            )
        if self.status is TransformStatus.MAPPED and self.lineage:
            covered = {l.quad_index for l in self.lineage}
            expected = set(range(len(self.target_quads)))
            if covered != expected:
                missing = sorted(expected - covered)
                raise ValueError(
                    f"{self.map_id}: quads without lineage at indices {missing}; "
                    "every produced quad must be traceable"
                )
        if self.status is TransformStatus.REJECTED and not self.rejection_reason:
            raise ValueError(f"{self.map_id}: a rejected result must carry a rejection reason")

    @property
    def is_loadable(self) -> bool:
        """Whether this output may be loaded into a clinical semantic graph."""
        return self.status is TransformStatus.MAPPED
