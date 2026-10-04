"""The schema-pair linter: static analysis the pinned engine does not ship.

DR-301 probe 7 found no ``shexmap-check`` and no equivalent anywhere in
``shex@1.0.0-alpha.33``; ``shex-validate --diagnose`` crashes non-TTY with exit
99. CD-1 therefore moves the acceptance matrix's "Mapping analysis" row onto
this tool, with three obligations:

======  =========================================================  ============
Code    Obligation                                                 Source
======  =========================================================  ============
SP001   unbound variables fail before data processing              matrix row
SP002   incompatible repetition scopes fail before data            DR-302
        processing
SP003   unknown Map functions fail before data processing          CD-1, which
        (replacing "invalid ``id()`` uses", because ``id()``       replaces the
        does not exist and an unknown function is deleted in       matrix's
        silence)                                                   ``id()``
======  =========================================================  ============

Every one of those three is an *error*: this tool fails the build. It does not
warn, because each corresponds to an engine behaviour that is silent at runtime
-- a warning would be advice about a bug nobody is going to see otherwise.

The remaining error codes cover the other silent-deletion paths DR-301 found;
the ``SP1xx`` warnings are real but recoverable and do not fail.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .mapcode import MapCode, parse_map_code
from .shexj import (
    ConstraintPath, Schema, SchemaTooLarge, map_codes_of, walk_paths,
)


class Severity(enum.Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    """One linter result, with enough context to fix it without guessing."""

    code: str
    severity: Severity
    schema: str
    message: str
    where: str = ""

    def render(self) -> str:
        at = f" [{self.where}]" if self.where else ""
        return f"{self.severity.value.upper()} {self.code} ({self.schema}){at}: {self.message}"


@dataclass(frozen=True)
class LintReport:
    """The outcome of linting one source/target pair."""

    findings: Tuple[Finding, ...]
    source_variables: Tuple[str, ...] = ()
    target_variables: Tuple[str, ...] = ()
    static_variables: Tuple[str, ...] = ()
    max_repetition_depth: int = 0

    @property
    def errors(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        """True only when nothing would fail the build."""
        return not self.errors

    def render(self) -> str:
        if not self.findings:
            return "schema pair clean: 0 findings"
        return "\n".join(f.render() for f in self.findings)

    def raise_for_status(self) -> None:
        """Fail the build. CD-1: the linter must fail, not warn."""
        if self.errors:
            raise SchemaPairLintError(self)


class SchemaPairLintError(RuntimeError):
    """Raised when a schema pair carries at least one error finding."""

    def __init__(self, report: LintReport):
        self.report = report
        super().__init__(
            f"{len(report.errors)} schema-pair error(s):\n" + report.render()
        )


# --------------------------------------------------------------------------
# the linter
# --------------------------------------------------------------------------


def lint_pair(
    source: Schema,
    target: Schema,
    static_variables: Optional[Mapping[str, str]] = None,
    source_start: Optional[object] = None,
    target_start: Optional[object] = None,
) -> LintReport:
    """Lint one source/target ShExMap pair.

    ``static_variables`` are the ``staticVars`` the driver will pass; they are
    always readable and never consumed, so they count as bound for SP001.
    """
    statics = dict(static_variables or {})
    findings: List[Finding] = []

    try:
        src_paths, src_cycles, src_dangling = walk_paths(source, source_start)
        tgt_paths, tgt_cycles, tgt_dangling = walk_paths(target, target_start)
    except SchemaTooLarge as exc:
        # A partial analysis would read as a pass, which for a build gate is
        # the one outcome that must never happen by accident.
        return LintReport(findings=(Finding(
            code="SP008", severity=Severity.ERROR, schema=f"{source.label}+{target.label}",
            message=(f"{exc}. Split the pair, or raise walk_paths(max_paths=...) "
                     f"only after checking the schema is not accidentally recursive"),
        ),))

    # -- SP003 first: an unreadable code makes every later answer unreliable
    src_codes = _collect_codes(source, src_paths, findings)
    tgt_codes = _collect_codes(target, tgt_paths, findings)

    source_vars = _variables(src_codes)
    target_vars = _variables(tgt_codes)

    # -- SP001 unbound target variables ------------------------------------
    # Only codes that parsed: a code SP003 already rejected has a garbage
    # variable name, and reporting it as "unbound" as well would bury the
    # finding that actually tells the author what to fix.
    bound = source_vars | set(statics)
    for path, code in tgt_codes:
        if not code.is_valid:
            continue
        for var in code.variables:
            if var in bound:
                continue
            findings.append(Finding(
                code="SP001",
                severity=Severity.ERROR,
                schema=target.label,
                where=path.render(),
                message=(
                    f"target variable {var!r} is never bound: the source schema does "
                    f"not declare it and it is not a static variable. At runtime the "
                    f"engine prunes every branch that needs it and emits a PARTIAL "
                    f"graph with exit 0 and an empty stderr (DR-301 probe 8c)"
                ),
            ))

    # -- SP002 repetition depth (DR-302) -----------------------------------
    # Every constraint *below* a nested repetition inherits the violation, so
    # report one finding per offending chain of repeats rather than one per
    # leaf. The author has a single thing to fix; six copies of it would read
    # as six problems.
    depth = 0
    reported_chains: Set[Tuple[str, ...]] = set()
    for label, paths in ((source.label, src_paths), (target.label, tgt_paths)):
        for path in sorted(paths, key=lambda p: len(p.steps)):
            depth = max(depth, path.repetition_count)
            if path.repetition_count >= 2:
                chain = (label,) + tuple(s.predicate for s in path.repeating_steps)
                if chain in reported_chains:
                    continue
                reported_chains.add(chain)
                repeats = ", ".join(str(s) for s in path.repeating_steps)
                findings.append(Finding(
                    code="SP002",
                    severity=Severity.ERROR,
                    schema=label,
                    where=path.render(),
                    message=(
                        f"{path.repetition_count} repeating constraints on one path "
                        f"from the root ({repeats}). DR-302 allows at most one: at two "
                        f"levels the engine mis-associates groups and drops members "
                        f"silently, and no flag changes that (DR-301 B1). Decompose "
                        f"into one pass per level, joined on the group's own IRI"
                    ),
                ))

    # -- SP004 Map annotation on a shape-valued TARGET constraint ----------
    for path, code in tgt_codes:
        if _is_shape_valued(target, path.constraint):
            findings.append(Finding(
                code="SP004",
                severity=Severity.ERROR,
                schema=target.label,
                where=path.render(),
                message=(
                    f"constraint carries {code.raw.strip()!r} and is shape-valued. The "
                    f"materializer takes the Map branch and returns before it can "
                    f"descend, so the bound term is emitted as a leaf and the whole "
                    f"sub-shape is dropped (DR-301 probe 4b). Either drop the Map "
                    f"annotation, or make the value a node constraint (e.g. IRI) and "
                    f"materialize the sub-shape in its own pass"
                ),
            ))

    # -- SP005/SP102 shape-reference cycles --------------------------------
    for cycle in tgt_cycles:
        findings.append(Finding(
            code="SP005", severity=Severity.ERROR, schema=target.label,
            where=cycle.render(),
            message=(
                "cycle in the target schema's shape references. Materialization "
                "unrolls it to maxCallDepth and then kills the thread, so output "
                "depth would depend on a guard rather than on the data"
            ),
        ))
    for cycle in src_cycles:
        findings.append(Finding(
            code="SP102", severity=Severity.WARNING, schema=source.label,
            where=cycle.render(),
            message=(
                "cycle in the source schema's shape references. Validation copes, "
                "but the binding tree's depth becomes data-dependent, so DR-302's "
                "one-repetition rule can no longer be checked statically for data "
                "that recurses through this cycle"
            ),
        ))

    # -- SP007 dangling shape references -----------------------------------
    for label, dangling in ((source.label, src_dangling), (target.label, tgt_dangling)):
        for ref in sorted(set(dangling)):
            findings.append(Finding(
                code="SP007", severity=Severity.ERROR, schema=label, where=ref,
                message=(
                    f"shape {ref!r} is referenced but not declared; the engine raises "
                    f"'shape not found' at runtime rather than at parse time"
                ),
            ))

    # -- SP006 no start shape ----------------------------------------------
    if target.start is None and target_start is None:
        findings.append(Finding(
            code="SP006", severity=Severity.ERROR, schema=target.label, where="",
            message=(
                "target schema declares no start shape and none was supplied; "
                "materialization fails with 'no shape given and no start in schema'"
            ),
        ))
    if source.start is None and source_start is None:
        findings.append(Finding(
            code="SP006", severity=Severity.ERROR, schema=source.label, where="",
            message="source schema declares no start shape and none was supplied",
        ))

    # -- SP101/SP103 warnings ----------------------------------------------
    for var in sorted(source_vars - target_vars):
        findings.append(Finding(
            code="SP101", severity=Severity.WARNING, schema=source.label, where=var,
            message=(
                "bound by the source schema but never read by the target. Harmless "
                "at runtime, but it lowers MapContract.inverse_coverage and is "
                "usually a rename that was only half applied"
            ),
        ))
    for var in sorted(set(statics) - target_vars):
        findings.append(Finding(
            code="SP103", severity=Severity.WARNING, schema=target.label, where=var,
            message="static variable is declared but never referenced by the target",
        ))

    return LintReport(
        findings=tuple(findings),
        source_variables=tuple(sorted(source_vars)),
        target_variables=tuple(sorted(target_vars)),
        static_variables=tuple(sorted(statics)),
        max_repetition_depth=depth,
    )


def _collect_codes(
    schema: Schema, paths: Sequence[ConstraintPath], findings: List[Finding]
) -> List[Tuple[ConstraintPath, MapCode]]:
    """Parse every reachable Map code, recording SP003 for the bad ones."""
    out: List[Tuple[ConstraintPath, MapCode]] = []
    for path in paths:
        for raw in map_codes_of(path.constraint):
            code = parse_map_code(raw, schema.prefixes)
            out.append((path, code))
            if not code.is_valid:
                findings.append(Finding(
                    code="SP003",
                    severity=Severity.ERROR,
                    schema=schema.label,
                    where=path.render(),
                    message=code.problem or "unusable Map code",
                ))
    return out


def _variables(codes: Iterable[Tuple[ConstraintPath, MapCode]]) -> Set[str]:
    found: Set[str] = set()
    for _, code in codes:
        if code.is_valid:
            found.update(code.variables)
    return found


def _is_shape_valued(schema: Schema, constraint: Mapping[str, object]) -> bool:
    value_expr = constraint.get("valueExpr")
    if value_expr is None:
        return False
    resolved = schema.resolve_shape(value_expr)
    if resolved is None:
        return isinstance(value_expr, str)
    return resolved.get("type") in ("Shape", "ShapeAnd", "ShapeOr")


# --------------------------------------------------------------------------
# cross-check against the reviewed MapContract
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ContractCheck:
    """Whether a reviewed MapContract still describes the schemas it names.

    ``MapContract.static_analysis_passed`` is a boolean an author could simply
    set. This is what makes setting it honest.
    """

    report: LintReport
    findings: Tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.report.ok and not [f for f in self.findings
                                       if f.severity is Severity.ERROR]

    def render(self) -> str:
        parts = [self.report.render()]
        parts.extend(f.render() for f in self.findings)
        return "\n".join(p for p in parts if p)


def check_contract(contract, source: Schema, target: Schema) -> ContractCheck:
    """Lint the pair, then confirm the MapContract matches what is there."""
    report = lint_pair(
        source, target,
        static_variables=dict(getattr(contract, "static_variables", {}) or {}),
    )
    findings: List[Finding] = []
    declared = {v.name for v in contract.pivot_variables}
    actual = set(report.source_variables) | set(report.target_variables)

    for name in sorted(declared - actual):
        findings.append(Finding(
            code="SP201", severity=Severity.ERROR, schema=contract.map_id, where=name,
            message=(
                "MapContract declares this pivot variable but neither schema uses it; "
                "the contract describes a pairing that no longer exists"
            ),
        ))
    for name in sorted(actual - declared):
        findings.append(Finding(
            code="SP202", severity=Severity.ERROR, schema=contract.map_id, where=name,
            message=(
                "used by the schemas but absent from MapContract.pivot_variables, so "
                "it carries no reviewed type, required flag or inverse-coverage claim"
            ),
        ))
    if report.max_repetition_depth > 1:
        findings.append(Finding(
            code="SP203", severity=Severity.ERROR, schema=contract.map_id, where="",
            message=f"schemas nest repetition {report.max_repetition_depth} deep (DR-302)",
        ))
    declared_scopes = len(contract.repetition_scopes)
    if declared_scopes > 1:
        findings.append(Finding(
            code="SP204", severity=Severity.ERROR, schema=contract.map_id, where="",
            message=(
                f"{declared_scopes} repetition scopes declared. DR-302 permits one per "
                f"pair; additional scopes belong to additional passes"
            ),
        ))
    if declared_scopes == 1 and report.max_repetition_depth == 0:
        findings.append(Finding(
            code="SP205", severity=Severity.WARNING, schema=contract.map_id, where="",
            message=(
                "a repetition scope is declared but neither schema repeats anything; "
                "the scope's tuple assertions would pass vacuously"
            ),
        ))
    return ContractCheck(report=report, findings=tuple(findings))
