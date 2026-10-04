"""MapContract - the reviewed identity and shape of one ShExMap pairing.

Plan section 3:

    Contains pairing version/hash, source/target shape labels, variable names
    and types, repetition scopes, required values, allowed alternative shapes,
    static variables, node-key rules, inverse coverage, and expected nonmapped
    FHIR fields. shexmap-check or equivalent static analysis must pass before
    runtime.

Owned by Agent 3 (mapping author) to populate; the schema is fixed here.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Mapping, Optional, Tuple


class VariableType(enum.Enum):
    """The RDF term kind a pivot variable binds to."""

    IRI = "iri"
    DECIMAL = "decimal"
    STRING = "string"
    DATETIME = "datetime"
    CODE = "code"


@dataclass(frozen=True)
class RepetitionScope:
    """A named repetition group and the key that keeps its tuples together.

    This is the artifact that makes the blood-pressure requirement testable.
    Concept note section 5 requires the tuple multiset
    ``{(bp-1, 120, 80), (bp-2, 105, 70)}``; a graph producing
    ``(bp-1, 120, 70)`` fails even though every individual value appears.
    ``key_variables`` names the variables whose combination identifies one
    iteration, so a cross-join is detectable rather than merely unlikely.
    """

    name: str
    key_variables: Tuple[str, ...]
    member_variables: Tuple[str, ...]
    min_occurs: int = 0
    max_occurs: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.key_variables:
            raise ValueError(
                f"repetition scope {self.name!r} needs at least one key variable, "
                "otherwise its iterations cannot be told apart and a cross-join "
                "is undetectable"
            )
        overlap = set(self.key_variables) & set(self.member_variables)
        if overlap:
            raise ValueError(
                f"repetition scope {self.name!r}: {sorted(overlap)} are both key and member"
            )


@dataclass(frozen=True)
class PivotVariable:
    """One shared ``%Map:{ }`` variable, with its provenance-relevant metadata."""

    name: str
    var_type: VariableType
    required: bool
    source_element: str
    target_role: str
    scope: Optional[str] = None
    inverse_covered: bool = False
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MapContract:
    """The reviewed contract for one source/target ShExMap pairing."""

    map_id: str
    semantic_version: str
    pairing_hash: str
    source_release: str
    source_profiles: Tuple[str, ...]
    source_shape_label: str
    target_shape_label: str
    pivot_variables: Tuple[PivotVariable, ...]
    repetition_scopes: Tuple[RepetitionScope, ...]
    node_key_rules: Mapping[str, str]
    terminology_dependencies: Tuple[str, ...]
    status_eligibility: Tuple[str, ...]
    expected_failures: Tuple[str, ...]
    sulo_version: str
    fixture_references: Tuple[str, ...]
    expected_nonmapped_fields: Tuple[str, ...] = ()
    allowed_alternative_shapes: Tuple[str, ...] = ()
    static_variables: Mapping[str, str] = field(default_factory=dict)
    static_analysis_passed: bool = False

    def __post_init__(self) -> None:
        names = [v.name for v in self.pivot_variables]
        dupes = {n for n in names if names.count(n) > 1}
        if dupes:
            raise ValueError(f"{self.map_id}: duplicate pivot variables {sorted(dupes)}")

        known = set(names)
        scope_names = {s.name for s in self.repetition_scopes}
        for scope in self.repetition_scopes:
            unknown = (set(scope.key_variables) | set(scope.member_variables)) - known
            if unknown:
                raise ValueError(
                    f"{self.map_id}: repetition scope {scope.name!r} references "
                    f"undeclared variables {sorted(unknown)}"
                )
        for var in self.pivot_variables:
            if var.scope is not None and var.scope not in scope_names:
                raise ValueError(
                    f"{self.map_id}: variable {var.name!r} names undeclared scope {var.scope!r}"
                )

    @property
    def inverse_coverage(self) -> float:
        """Fraction of pivot variables the inverse map is declared to recover.

        Concept note section 7: the pairing promises recovery of shared pivot
        bindings, not reconstruction of every FHIR field. This makes the
        promised fraction explicit and reportable rather than assumed to be 1.
        """
        if not self.pivot_variables:
            return 0.0
        covered = sum(1 for v in self.pivot_variables if v.inverse_covered)
        return covered / len(self.pivot_variables)
