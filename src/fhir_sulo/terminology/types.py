"""Types on the terminology/UCUM boundary.

Contract constraints encoded here
---------------------------------
* "A FHIR code literal is not an OWL class assertion." Only ``CodeInterpreted``
  carries a ``result_class``; the other two outcome types have no class
  attribute at all, so no caller can read one off an unmapped code.
* "Source codes and their systems are always retained regardless of
  interpretation outcome." ``source`` is on the shared base of every outcome.
* "An external lookup must supply a value or fail explicitly." No outcome type
  is ``Optional`` and no resolver returns ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, Mapping, NoReturn, Optional, Union

try:  # pragma: no cover
    from typing import Literal
except ImportError:  # pragma: no cover
    from typing_extensions import Literal  # type: ignore

from ..policy import DecisionRecord

__all__ = [
    "TerminologyUnavailable",
    "Coding",
    "UnitRef",
    "CodeInterpretation",
    "CodeInterpreted",
    "CodeSourceOnly",
    "CodeRejected",
    "CodeOutcome",
    "UnitInterpretation",
    "UnitResolved",
    "UnitSourceOnly",
    "UnitRejected",
    "UnitOutcome",
]


class TerminologyUnavailable(Exception):
    """Raised when a caller reads an interpretation that was never granted."""

    def __init__(self, reason_code: str, reason: str, record: DecisionRecord) -> None:
        super().__init__("%s: %s" % (reason_code, reason))
        self.reason_code = reason_code
        self.reason = reason
        self.record = record


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Coding:
    """A FHIR ``Coding``: system + code, with the source display kept verbatim."""

    system: str
    code: str
    display: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"system": self.system, "code": self.code, "display": self.display}


@dataclass(frozen=True)
class UnitRef:
    """A FHIR ``Quantity``'s unit: system + code, plus the human ``unit`` text."""

    system: str
    code: str
    display: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {"system": self.system, "code": self.code, "display": self.display}


# ---------------------------------------------------------------------------
# Code outcomes
# ---------------------------------------------------------------------------

_LEAKY_CODE_NAMES = frozenset(
    {"result_class", "quality_class", "domain_class", "interpretation"}
)


@dataclass(frozen=True)
class _CodeOutcomeBase:
    source: Coding
    record: DecisionRecord

    def source_retained(self) -> Dict[str, Any]:
        """The source system and code, always available on every outcome."""
        return self.source.as_dict()


@dataclass(frozen=True)
class CodeInterpretation:
    """The reviewed interpretation of one code."""

    entry_id: str
    result_class: Optional[str]
    quality_class: Optional[str]
    observation_kind: str
    expected_unit_dimension: Optional[str]
    review_status: str
    clinical_signoff: bool

    def as_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "result_class": self.result_class,
            "quality_class": self.quality_class,
            "observation_kind": self.observation_kind,
            "expected_unit_dimension": self.expected_unit_dimension,
            "review_status": self.review_status,
            "clinical_signoff": self.clinical_signoff,
        }


@dataclass(frozen=True)
class CodeInterpreted(_CodeOutcomeBase):
    interpretation: CodeInterpretation
    is_interpreted: ClassVar[Literal[True]] = True
    status: ClassVar[Literal["mapped"]] = "mapped"

    def unwrap(self) -> CodeInterpretation:
        return self.interpretation


@dataclass(frozen=True)
class CodeSourceOnly(_CodeOutcomeBase):
    """The code is retained in the source/record layer and typed nowhere."""

    reason_code: str
    reason: str
    is_interpreted: ClassVar[Literal[False]] = False
    status: ClassVar[Literal["source-only"]] = "source-only"

    def unwrap(self) -> NoReturn:
        raise TerminologyUnavailable(self.reason_code, self.reason, self.record)

    def __getattr__(self, name: str) -> NoReturn:
        if name in _LEAKY_CODE_NAMES:
            raise TerminologyUnavailable(
                object.__getattribute__(self, "reason_code"),
                object.__getattribute__(self, "reason"),
                object.__getattribute__(self, "record"),
            )
        raise AttributeError(name)


@dataclass(frozen=True)
class CodeRejected(_CodeOutcomeBase):
    """The code must not produce semantic output at all."""

    reason_code: str
    reason: str
    is_interpreted: ClassVar[Literal[False]] = False
    status: ClassVar[Literal["rejected"]] = "rejected"

    def unwrap(self) -> NoReturn:
        raise TerminologyUnavailable(self.reason_code, self.reason, self.record)

    def __getattr__(self, name: str) -> NoReturn:
        if name in _LEAKY_CODE_NAMES:
            raise TerminologyUnavailable(
                object.__getattribute__(self, "reason_code"),
                object.__getattribute__(self, "reason"),
                object.__getattribute__(self, "record"),
            )
        raise AttributeError(name)


CodeOutcome = Union[CodeInterpreted, CodeSourceOnly, CodeRejected]


# ---------------------------------------------------------------------------
# Unit outcomes
# ---------------------------------------------------------------------------

_LEAKY_UNIT_NAMES = frozenset({"unit", "unit_iri", "ucum_code", "dimension"})


@dataclass(frozen=True)
class _UnitOutcomeBase:
    source: UnitRef
    record: DecisionRecord

    def source_retained(self) -> Dict[str, Any]:
        return self.source.as_dict()


@dataclass(frozen=True)
class UnitInterpretation:
    unit_id: str
    ucum_code: str
    unit_iri: str
    dimension: str
    review_status: str
    clinical_signoff: bool
    converted: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "ucum_code": self.ucum_code,
            "unit_iri": self.unit_iri,
            "dimension": self.dimension,
            "review_status": self.review_status,
            "clinical_signoff": self.clinical_signoff,
            "converted": self.converted,
        }


@dataclass(frozen=True)
class UnitResolved(_UnitOutcomeBase):
    unit: UnitInterpretation
    is_resolved: ClassVar[Literal[True]] = True
    status: ClassVar[Literal["mapped"]] = "mapped"

    def unwrap(self) -> UnitInterpretation:
        return self.unit


@dataclass(frozen=True)
class UnitSourceOnly(_UnitOutcomeBase):
    reason_code: str
    reason: str
    is_resolved: ClassVar[Literal[False]] = False
    status: ClassVar[Literal["source-only"]] = "source-only"

    def unwrap(self) -> NoReturn:
        raise TerminologyUnavailable(self.reason_code, self.reason, self.record)

    def __getattr__(self, name: str) -> NoReturn:
        if name in _LEAKY_UNIT_NAMES:
            raise TerminologyUnavailable(
                object.__getattribute__(self, "reason_code"),
                object.__getattribute__(self, "reason"),
                object.__getattribute__(self, "record"),
            )
        raise AttributeError(name)


@dataclass(frozen=True)
class UnitRejected(_UnitOutcomeBase):
    reason_code: str
    reason: str
    is_resolved: ClassVar[Literal[False]] = False
    status: ClassVar[Literal["rejected"]] = "rejected"

    def unwrap(self) -> NoReturn:
        raise TerminologyUnavailable(self.reason_code, self.reason, self.record)

    def __getattr__(self, name: str) -> NoReturn:
        if name in _LEAKY_UNIT_NAMES:
            raise TerminologyUnavailable(
                object.__getattribute__(self, "reason_code"),
                object.__getattribute__(self, "reason"),
                object.__getattribute__(self, "record"),
            )
        raise AttributeError(name)


UnitOutcome = Union[UnitResolved, UnitSourceOnly, UnitRejected]


class ParticipationTypeNotInterpretable(Exception):
    """A participation type has no reviewed role-class binding (R12).

    Deliberately an exception rather than a ``None`` return: the role node is
    emitted either way, so a caller that silently carried on would assert an
    under-specified role instead of declining to assert one.
    """

    def __init__(self, reason_code: str, reason: str):
        self.reason_code = reason_code
        self.reason = reason
        super().__init__(reason)
