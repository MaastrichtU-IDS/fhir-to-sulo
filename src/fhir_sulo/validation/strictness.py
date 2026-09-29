"""The review item R5 switch: how closed-world the target shapes are.

R5 is **open**. Nothing in this module resolves it, and
``R5_RESOLVED`` stays ``False`` until the human clinical/ontology reviewer
answers. ``tests/integration/test_validation_shapes.py`` asserts that it is
still ``False``, so the flag cannot be flipped quietly as a side effect of
making something pass.

The question
------------
SULO 0.2.12 states existential restrictions that an OWL reasoner satisfies
with an anonymous witness but a closed-world shape check sees as a missing
triple (DR-002 axioms 4 and 5):

* ``Quantity ⊑ InformationObject ⊑ Feature ⊑ isFeatureOf some (Object ⊔ Process)``
  - the concept note's ``ex:egfr-result-456`` has no ``sulo:isFeatureOf``.
* ``TimeInstant ⊑ Time ⊑ Quantity ⊑ hasPart some Unit``, with
  ``Time disjointWith Unit`` - the note's ``ex:time-egfr-456`` has no unit
  part and cannot be its own unit.

R5 offers **A** materialize both explicitly, **B** relax both shapes, **C** a
per-axiom split.

What is built
-------------
Two independent booleans, not three named modes, because option C is a split
and a split needs two switches. The preset ``CONCEPT_NOTE_LITERAL`` - both off
- is the default, because the concept note's literal example graphs are the
only target the pilot has reviewer-independent warrant for. Option A is
``R5_OPTION_A``; a split is ``Strictness(...)`` with the two flags set
directly.

Flipping a flag adds SHACL constraints to the shapes graph. No map is
re-authored and no expected graph is rewritten, which is the property the
review request promised: "parameterised so that a reviewer answer flips
behaviour without re-authoring maps".
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "R5_RESOLVED",
    "Strictness",
    "CONCEPT_NOTE_LITERAL",
    "R5_OPTION_A",
    "R5_OPTION_B",
]

R5_RESOLVED = False
"""Set to True only by the reviewer's answer, recorded in a decision record.

Guarded by a test. If you are here because a shape check failed, the answer is
a decision record and a reviewer reply, not this constant."""


@dataclass(frozen=True)
class Strictness:
    """Which open-world existentials the target shapes require explicitly."""

    require_quantity_is_feature_of: bool = False
    """R5 row 2: does a materialized ``sulo:Quantity`` carry an explicit
    ``sulo:isFeatureOf``?"""

    require_time_unit: bool = False
    """R5 row 3: does a materialized ``sulo:TimeInstant`` carry an explicit
    time ``sulo:Unit`` as a ``sulo:hasPart``?"""

    @property
    def label(self) -> str:
        if not (self.require_quantity_is_feature_of or self.require_time_unit):
            return "concept-note-literal (R5 unanswered)"
        if self.require_quantity_is_feature_of and self.require_time_unit:
            return "R5-option-A (closed-world complete)"
        chosen = []
        if self.require_quantity_is_feature_of:
            chosen.append("quantity-isFeatureOf")
        if self.require_time_unit:
            chosen.append("time-unit")
        return "R5-option-C split: %s" % "+".join(chosen)

    def modules(self) -> tuple:
        """Which optional shape modules to merge into the shapes graph."""
        mods = ["base.ttl"]
        if self.require_quantity_is_feature_of:
            mods.append("strict-quantity-isfeatureof.ttl")
        if self.require_time_unit:
            mods.append("strict-time-unit.ttl")
        return tuple(mods)


CONCEPT_NOTE_LITERAL = Strictness()
"""The default. Validates exactly the graphs the concept note writes out."""

R5_OPTION_A = Strictness(require_quantity_is_feature_of=True, require_time_unit=True)
"""Everything the SULO existentials imply is materialized and checked."""

R5_OPTION_B = CONCEPT_NOTE_LITERAL
"""Option B and the literal graphs coincide; kept as a name so a reviewer
answer of "B" maps onto something rather than onto silence."""
