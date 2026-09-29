"""Code system and UCUM resolution against a pinned offline snapshot (Agent 5).

Public interface::

    from fhir_sulo.terminology import TerminologyService, Coding, UnitRef

    term = TerminologyService()
    code = term.resolve_code(Coding("http://loinc.org", "33914-3"))
    unit = term.resolve_unit(
        UnitRef("http://unitsofmeasure.org", "mL/min/{1.73_m2}"),
        expected_dimension="egfr-rate",
    )

Every outcome carries ``.status`` in the ``TransformResult`` vocabulary
(``mapped`` / ``source-only`` / ``rejected``) and ``.source`` with the original
system and code, whatever the outcome.
"""

from .service import TerminologyService
from .types import (
    CodeInterpretation,
    CodeInterpreted,
    CodeOutcome,
    CodeRejected,
    CodeSourceOnly,
    Coding,
    TerminologyUnavailable,
    UnitInterpretation,
    UnitOutcome,
    UnitRef,
    UnitRejected,
    UnitResolved,
    UnitSourceOnly,
)

__all__ = [
    "TerminologyService",
    "Coding",
    "UnitRef",
    "CodeOutcome",
    "CodeInterpreted",
    "CodeSourceOnly",
    "CodeRejected",
    "CodeInterpretation",
    "UnitOutcome",
    "UnitResolved",
    "UnitSourceOnly",
    "UnitRejected",
    "UnitInterpretation",
    "TerminologyUnavailable",
]
