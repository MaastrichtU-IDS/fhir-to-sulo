"""Target validation: SHACL shapes, OWL reasoning, competency queries.

Agent 6 scope. Unlike ``fhir_sulo.store`` and ``fhir_sulo.provenance``, this
package needs ``rdflib`` and ``pyshacl`` (``requirements-runtime.txt``), and
the reasoning layer needs Docker. Imports are lazy so that importing the
package on a bare interpreter does not fail; the missing piece is reported
when it is actually used.
"""

from __future__ import annotations

from .strictness import (
    CLOSED_WORLD_COMPLETE,
    CONCEPT_NOTE_LITERAL,
    R5_OPTION_A,
    R5_OPTION_B,
    R5PolicyUnset,
    Strictness,
    allowed_modes,
    recorded_mode,
    resolve,
)

__all__ = [
    "CLOSED_WORLD_COMPLETE",
    "CONCEPT_NOTE_LITERAL",
    "R5_OPTION_A",
    "R5_OPTION_B",
    "R5PolicyUnset",
    "Strictness",
    "allowed_modes",
    "recorded_mode",
    "resolve",
    "validate_graph",
    "load_shapes_graph",
    "ShapeReport",
    "ShapeViolation",
    "RobotReasoner",
    "verify_property_chain_support",
    "ChainVerification",
    "COMPETENCY_QUERIES",
    "NEGATIVE_QUERIES",
    "run_suite",
    "run_query",
]


def __getattr__(name):
    if name in ("validate_graph", "load_shapes_graph", "ShapeReport", "ShapeViolation",
                "MissingDependencyError"):
        from . import shapes_check
        return getattr(shapes_check, name)
    if name in ("RobotReasoner", "verify_property_chain_support", "ChainVerification",
                "ReasonerUnavailable", "ReasoningError", "InconsistentOntology",
                "ROBOT_IMAGE", "DEFAULT_REASONER", "SULO_PATH", "SULO_SHA256"):
        from . import reasoning
        return getattr(reasoning, name)
    if name in ("COMPETENCY_QUERIES", "NEGATIVE_QUERIES", "run_suite", "run_query",
                "QuerySuiteReport", "QueryResult", "CompetencyQuery", "NegativeQuery"):
        from . import queries
        return getattr(queries, name)
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
