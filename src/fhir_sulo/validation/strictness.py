"""Review item R5: how closed-world the target shapes are. **Unset rejects.**

R5 is **open**, and nothing in this module resolves it. The recorded answer
lives in ``r5-strictness-policy.json`` with ``"mode": null``, and while it is
null every resolution that does not name a mode explicitly raises
``R5PolicyUnset``.

Why it is built this way
------------------------
An earlier version of this module had a permissive default::

    R5_RESOLVED = False
    CONCEPT_NOTE_LITERAL = Strictness()    # both flags off
    R5_OPTION_B = CONCEPT_NOTE_LITERAL     # the same object

``R5_RESOLVED = False`` was decorative. The CLI defaulted to it, the benchmark
ran under it, and a test pinned it, so **option B was in force everywhere**
while the flag said the question was open. A graph with every
``sulo:isFeatureOf`` deleted conformed. That is not an open question; it is a
quietly answered one.

This module now follows the model Agent 5 used for review item R2 (quality
identity) in ``policies/identity-policy.v1.json``: ``mode: null``,
``unset_behaviour: reject``, both options implemented and tested, and no
caller able to inherit an answer. Concretely:

* ``resolve()`` with no mode raises ``R5PolicyUnset``.
* ``shapes_check.validate_graph`` and ``load_shapes_graph`` take strictness as
  a **required positional argument**. There is no default to inherit.
* the CLI's ``--strictness`` is **required**.
* the benchmark's ``--strictness`` is **required**, so a benchmark report
  always names the strictness it ran under.

Choosing ``concept-note-literal`` is still possible and still passes - it is a
legitimate answer, R5 option B. The change is that a run must *say so*, and
saying so is recorded in the report digest.

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

**A** materialize both explicitly; **B** relax both shapes; **C** split.

R5 does not change what is emitted, only how it is checked, so it is
deliberately **not** one of ``graph_key.CONTENT_FIELDS``: answering it must not
re-key every graph. It does change ``validation_report_digest``, which is
correct - a report must say which strictness produced it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Mapping, Optional, Union

__all__ = [
    "R5PolicyUnset",
    "Strictness",
    "POLICY_PATH",
    "load_policy",
    "recorded_mode",
    "allowed_modes",
    "resolve",
    "CONCEPT_NOTE_LITERAL",
    "CLOSED_WORLD_COMPLETE",
    "QUANTITY_BEARER_ONLY",
    "R5_OPTION_A",
    "R5_OPTION_B",
]

POLICY_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "r5-strictness-policy.json"
)


class R5PolicyUnset(RuntimeError):
    """Strictness was needed and review item R5 has not been answered.

    Deliberately an exception and not a warning-plus-fallback. A fallback is
    how R5 came to be answered by accident the first time.
    """


@dataclass(frozen=True)
class Strictness:
    """Which open-world existentials the target shapes require explicitly.

    Two independent booleans rather than three named modes, because R5 option
    C *is* a split and a split needs two switches. A split must carry a
    ``rationale``: an unlabelled half-strict setting is indistinguishable from
    a mistake, and R5 option C is supposed to be a reasoned position.
    """

    require_quantity_is_feature_of: bool
    require_time_unit: bool
    mode: Optional[str] = None
    rationale: str = ""

    def __post_init__(self) -> None:
        symmetric = self.require_quantity_is_feature_of == self.require_time_unit
        if not symmetric and not (self.rationale or self.mode):
            raise R5PolicyUnset(
                "a per-axiom split is R5 option C and needs a stated reason: "
                "either name a mode from r5-strictness-policy.json (which carries "
                "the description) or pass Strictness(..., rationale='why this "
                "split'). Half-strict with no reason recorded cannot be told "
                "apart from an oversight."
            )

    @property
    def label(self) -> str:
        if self.mode:
            return self.mode
        if self.require_quantity_is_feature_of and self.require_time_unit:
            return "closed-world-complete"
        if not (self.require_quantity_is_feature_of or self.require_time_unit):
            return "concept-note-literal"
        chosen = []
        if self.require_quantity_is_feature_of:
            chosen.append("quantity-isFeatureOf")
        if self.require_time_unit:
            chosen.append("time-unit")
        return "R5-option-C-split:%s" % "+".join(chosen)

    def modules(self) -> tuple:
        """Which optional shape modules to merge into the shapes graph."""
        mods = ["base.ttl"]
        if self.require_quantity_is_feature_of:
            mods.append("strict-quantity-isfeatureof.ttl")
        if self.require_time_unit:
            mods.append("strict-time-unit.ttl")
        return tuple(mods)


def load_policy(path: str = POLICY_PATH) -> Mapping[str, object]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def recorded_mode(path: str = POLICY_PATH) -> Optional[str]:
    """The reviewer's recorded answer, or None while R5 is open."""
    return load_policy(path).get("mode")


def allowed_modes(path: str = POLICY_PATH) -> Mapping[str, Mapping[str, object]]:
    return load_policy(path)["allowed_modes"]  # type: ignore[index]


def _from_spec(mode: str, spec: Mapping[str, object]) -> Strictness:
    return Strictness(
        require_quantity_is_feature_of=bool(spec["require_quantity_is_feature_of"]),
        require_time_unit=bool(spec["require_time_unit"]),
        mode=mode,
    )


def resolve(
    mode: Union[str, Strictness, None] = None, *, path: str = POLICY_PATH
) -> Strictness:
    """Turn a named mode into a ``Strictness``, or refuse.

    ``mode`` may be:

    * a mode name from the policy's ``allowed_modes``;
    * a ``Strictness`` already built by the caller (R5 option C);
    * ``"from-policy"``, which uses the reviewer's recorded answer and raises
      if it is still null;
    * ``None``, which also consults the policy and therefore also raises while
      R5 is open.

    The last two are the same thing on purpose. There is no spelling of this
    call that quietly picks an answer.
    """
    if isinstance(mode, Strictness):
        return mode

    policy = load_policy(path)
    options = policy["allowed_modes"]

    if mode is None or mode == "from-policy":
        recorded = policy.get("mode")
        if recorded is None:
            raise R5PolicyUnset(
                "review item R5 is unanswered: %s has \"mode\": null and "
                "\"unset_behaviour\": \"reject\".\n\n%s\n\n"
                "Name a strictness explicitly at the call site - one of %s - or "
                "record the reviewer's answer in that file. Nothing validates "
                "under a guessed answer."
                % (
                    os.path.relpath(path),
                    policy["reviewer_question"],
                    ", ".join(sorted(options)),
                )
            )
        mode = recorded

    if mode not in options:
        raise ValueError(
            "unknown R5 strictness mode %r; allowed: %s"
            % (mode, ", ".join(sorted(options)))
        )
    return _from_spec(mode, options[mode])


# Named options, for callers that have decided and want to say so in code.
# Building them from the policy file means the file is the single description
# of what each option means, and a code/policy disagreement is impossible.
CONCEPT_NOTE_LITERAL = _from_spec(
    "concept-note-literal", allowed_modes()["concept-note-literal"]
)
"""R5 option B. Legitimate, and no longer a default: using it is answering."""

CLOSED_WORLD_COMPLETE = _from_spec(
    "closed-world-complete", allowed_modes()["closed-world-complete"]
)
"""R5 option A."""

QUANTITY_BEARER_ONLY = _from_spec(
    "quantity-bearer-only", allowed_modes()["quantity-bearer-only"]
)
"""R5 option C: row 1 strict, row 2 relaxed.

Added when review item R11 made the maps emit ``result sulo:isFeatureOf
person``, which satisfies R5 row 1 in practice. Agent 1 recorded R11 as
*bearing on* R5, not answering it, and row 2 - an explicit ``sulo:Unit`` on a
``TimeInstant`` - is still open. This mode exists so that position is
nameable; selecting it is still a choice a caller must make, and the policy's
recorded ``mode`` stays ``null``."""

R5_OPTION_A = CLOSED_WORLD_COMPLETE
R5_OPTION_B = CONCEPT_NOTE_LITERAL
