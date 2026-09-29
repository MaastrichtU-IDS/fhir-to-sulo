"""Host-side engine tools: the static checks and the driver the engine lacks.

Two tools, both mandated by DR-301 decision 3 and both consequences of the
spike finding that this engine's failures are silent:

* :mod:`~fhir_sulo.engine.linter` -- the schema-pair linter. CD-1: no
  ``shexmap-check`` ships, so unbound variables, nested repetition (DR-302) and
  unknown Map functions are caught here, before data processing, as build
  failures rather than warnings.
* :mod:`~fhir_sulo.engine.driver` -- the materialization driver. CD-2: the
  engine's CLI truncates output at 19 repetitions and exits 0 on failure, so
  the programmatic API is driven from here with every guard set explicitly and
  every silent failure turned into an exception.

The engine itself always runs in the pinned Docker image
(:mod:`~fhir_sulo.engine.docker`); nothing is bind-mounted, because on this
host a bind mount of an unshared path yields an empty directory rather than an
error.
"""

from __future__ import annotations

from .docker import (
    DEFAULT_TAG,
    EngineImage,
    EngineInvocationError,
    EngineUnavailable,
    default_image,
)
from .driver import (
    AcceptCeilingReached,
    BindingsNotConsumed,
    DriverResult,
    ExplorationTruncated,
    Guards,
    MaterializationFailure,
    PassResult,
    PassSpec,
    QuadRecord,
    SourceValidationFailure,
    UnboundVariables,
    UntracedQuad,
    binding_tree_of,
    graph_key,
    ineligible_result,
    interpret_pass,
    materialize,
    run_pass,
    to_transform_result,
    union_passes,
)
from .linter import (
    ContractCheck,
    Finding,
    LintReport,
    SchemaPairLintError,
    Severity,
    check_contract,
    lint_pair,
)
from .mapcode import CodeKind, MapCode, parse_map_code
from .rdfterms import Quad, Term
from .shexj import Schema, load as load_schema, walk_paths

__all__ = [
    # docker
    "DEFAULT_TAG", "EngineImage", "EngineInvocationError", "EngineUnavailable",
    "default_image",
    # linter
    "ContractCheck", "Finding", "LintReport", "SchemaPairLintError", "Severity",
    "check_contract", "lint_pair",
    # map codes and schemas
    "CodeKind", "MapCode", "parse_map_code", "Schema", "load_schema", "walk_paths",
    # driver
    "AcceptCeilingReached", "BindingsNotConsumed", "DriverResult",
    "ExplorationTruncated", "Guards", "MaterializationFailure", "PassResult",
    "PassSpec", "Quad", "QuadRecord", "SourceValidationFailure", "Term",
    "UnboundVariables", "UntracedQuad", "binding_tree_of", "graph_key",
    "ineligible_result", "interpret_pass", "materialize", "run_pass",
    "to_transform_result", "union_passes",
]
