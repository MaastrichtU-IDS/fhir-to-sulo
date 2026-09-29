"""Lint a whole map: every pass, not just the one the ``start`` shape names.

:func:`~fhir_sulo.engine.linter.lint_pair` walks a target schema from its
``start``. For the schema style this pilot adopted that analyses almost
nothing. The engine has no ``id()``, so only a materialization's root node has
a controllable IRI, so **every IRI-identified target node is the root of its
own pass** (DR-301 4b/4c, DR-302's decomposition). The blood-pressure target
therefore declares ten root shapes and ``start`` names one of them.

Walking from ``start`` alone left SP001, SP003 and SP004 unchecked on nine of
ten blood-pressure shapes and five of six eGFR shapes -- and produced a
*wrong* answer rather than a partial one, reporting the other passes'
variables as bound-but-never-read and their statics as unused. CD-1's three
obligations were structurally uncovered for the exact style the maps use.

This module lints once per declared pass, with that pass's ``staticVars`` in
scope, exactly as the runner will execute it. Two findings are deliberately
global rather than per pass:

* **SP101** (source variable never read) is computed against the union of
  every pass's target variables. Per pass it would fire for almost every
  variable, since no single pass reads them all.
* **SP002** is reported per schema rather than per pass, because a nested
  repetition is a property of the schema, not of the entry point.

**SP103** (unused static) stays per pass, and is the most valuable finding
here: the engine scopes ``staticVars`` per materialization and reports
``lastReport.unusedStatics``, which the maps' own tests require to be empty.
A static declared for a pass that never reads it is an identity-provided
binding that will not reach the graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from ..pipeline.manifest import Manifest, PassSpec, host_consumed_variables
from .linter import Finding, LintReport, Severity, lint_pair
from .mapcode import parse_map_code
from .shexj import Schema, SchemaTooLarge, map_codes_of, walk_paths

#: Stand-in for a run binding's value. The linter checks variable *names*, so
#: it never needs identity or terminology to have run.
PLACEHOLDER = "urn:fhir-sulo:lint-placeholder"


@dataclass(frozen=True)
class PassReport:
    """What linting one declared pass found."""

    pass_name: str
    shape: str
    report: LintReport

    @property
    def ok(self) -> bool:
        return self.report.ok


@dataclass(frozen=True)
class MapLintReport:
    """The whole map: every pass, plus the findings that span them."""

    family: str
    map_id: str
    passes: Tuple[PassReport, ...] = ()
    global_findings: Tuple[Finding, ...] = ()
    shapes_walked: Tuple[str, ...] = ()
    unreachable_shapes: Tuple[str, ...] = ()

    @property
    def findings(self) -> Tuple[Finding, ...]:
        out: List[Finding] = list(self.global_findings)
        for entry in self.passes:
            out.extend(entry.report.findings)
        return tuple(out)

    @property
    def errors(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.ERROR)

    @property
    def warnings(self) -> Tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = [f"{self.family} ({self.map_id}): {len(self.passes)} pass(es), "
                 f"{len(self.shapes_walked)} root shape(s) analysed"]
        for finding in self.global_findings:
            lines.append("  " + finding.render())
        for entry in self.passes:
            if entry.report.findings:
                lines.append(f"  pass {entry.pass_name} -> {entry.shape}")
                for finding in entry.report.findings:
                    lines.append("    " + finding.render())
        return "\n".join(lines)


def lint_map(
    manifest: Manifest,
    source: Schema,
    target: Schema,
    source_start: Optional[str] = None,
    contract: Optional[Mapping[str, object]] = None,
) -> MapLintReport:
    """Lint every pass the manifest declares, plus what spans them.

    ``contract`` is the family's ``<family>-map-contract.v1.json``. It matters
    for SP101: in this architecture a source variable is legitimately consumed
    by the *host* -- as a node-key input, an identity or terminology service
    input, or an eligibility guard -- and never reaches a target constraint.
    ``pivot_variables[].target_role`` says which, so with the contract in hand
    SP101 fires only for a variable that is read by nothing at all, which is
    the half-applied rename it was meant to catch. Without it, SP101 would
    report most of a well-formed map as dead.
    """
    global_findings: List[Finding] = []
    pass_reports: List[PassReport] = []
    walked: List[str] = []

    source_start = source_start or None
    source_vars = _source_variables(source, source_start, global_findings)
    all_target_vars: Set[str] = set()

    for spec in manifest.passes:
        shape = manifest.shape_iri(spec.shape)
        statics = {name: PLACEHOLDER for name in manifest.static_variables_of(spec)}
        report = lint_pair(
            source, target,
            static_variables=statics,
            source_start=source_start,
            target_start=shape,
        )
        # SP101 is meaningless per pass -- no single pass reads every source
        # variable -- so it is dropped here and recomputed once, globally.
        kept = tuple(f for f in report.findings if f.code != "SP101")
        kept = tuple(_tag(f, spec) for f in kept)
        all_target_vars.update(report.target_variables)
        pass_reports.append(PassReport(
            pass_name=spec.name,
            shape=shape,
            report=LintReport(
                findings=kept,
                source_variables=report.source_variables,
                target_variables=report.target_variables,
                static_variables=report.static_variables,
                max_repetition_depth=report.max_repetition_depth,
            ),
        ))
        walked.append(shape)

    if not manifest.passes:
        global_findings.append(Finding(
            code="SP301", severity=Severity.ERROR, schema=manifest.family,
            message="the run-binding manifest declares no passes, so there is "
                    "nothing to analyse and nothing the runner could execute",
        ))

    declared_roles = host_consumed_variables(manifest, contract)
    for name in sorted(source_vars - all_target_vars):
        local = name[len(manifest.var_namespace):] \
            if name.startswith(manifest.var_namespace) else name
        if local in declared_roles:
            continue  # the host consumes it, and the contract says so
        global_findings.append(Finding(
            code="SP101", severity=Severity.WARNING, schema=source.label, where=name,
            message="bound by the source schema, read by no pass of this map, and "
                    "given no target_role in the MapContract. Either a target "
                    "constraint should read it, or the contract should declare what "
                    "the host does with it; as it stands nothing does either",
        ))
    if contract is not None:
        pivots = {v.get("name") for v in contract.get("pivot_variables", ())}
        used = {n[len(manifest.var_namespace):] if n.startswith(manifest.var_namespace)
                else n for n in source_vars | all_target_vars}
        for name in sorted(pivots - used - set(manifest.vocabulary)
                           - set(manifest.identity_provided)
                           - set(manifest.node_key_templates)):
            global_findings.append(Finding(
                code="SP303", severity=Severity.ERROR, schema=manifest.family, where=name,
                message="MapContract declares this pivot variable but neither schema "
                        "binds or reads it and the manifest does not supply it; the "
                        "contract describes a pairing that is not there",
            ))

    unreachable = _unreachable_shapes(target, walked)
    for shape in unreachable:
        global_findings.append(Finding(
            code="SP302", severity=Severity.ERROR, schema=target.label, where=shape,
            message="declared in the target schema but named by no pass and reachable "
                    "from none, so nothing will ever materialize it. Either declare a "
                    "pass for it or delete it -- an unreachable shape is unlinted, and "
                    "SP001/SP003/SP004 are not checked on it",
        ))

    return MapLintReport(
        family=manifest.family,
        map_id=manifest.map_id,
        passes=tuple(pass_reports),
        global_findings=tuple(global_findings),
        shapes_walked=tuple(walked),
        unreachable_shapes=tuple(unreachable),
    )


def _tag(finding: Finding, spec: PassSpec) -> Finding:
    """Name the pass on a finding, so a fix has an address."""
    return Finding(
        code=finding.code,
        severity=finding.severity,
        schema=finding.schema,
        message=finding.message,
        where=f"pass {spec.name}: {finding.where}" if finding.where else f"pass {spec.name}",
    )


def _source_variables(
    source: Schema, source_start: Optional[str], findings: List[Finding]
) -> Set[str]:
    """Variables the source schema binds, from its own start shape."""
    try:
        paths, _, _ = walk_paths(source, source_start)
    except SchemaTooLarge as exc:
        findings.append(Finding(
            code="SP008", severity=Severity.ERROR, schema=source.label, message=str(exc)))
        return set()
    found: Set[str] = set()
    for path in paths:
        for raw in map_codes_of(path.constraint):
            code = parse_map_code(raw, source.prefixes)
            if code.is_valid:
                found.update(code.variables)
    return found


def _unreachable_shapes(target: Schema, walked: Sequence[str]) -> Tuple[str, ...]:
    """Declared target shapes that no pass names and no walked pass reaches.

    An unreachable shape is not merely dead weight: it is unlinted. Nothing
    checks its Map codes, so the silent-deletion faults CD-1 exists to catch
    live there undetected until someone wires it up.
    """
    reachable: Set[str] = set(walked)
    for entry in walked:
        try:
            paths, cycles, _ = walk_paths(target, entry)
        except SchemaTooLarge:
            return ()
        for path in paths:
            for step in path.steps:
                if step.shape:
                    reachable.add(step.shape)
        for cycle in cycles:
            reachable.update(cycle.shapes)
    declared = set(target.shape_exprs)
    if target.start is not None and isinstance(target.start, str):
        reachable.add(target.start)
    return tuple(sorted(declared - reachable))


# ---------------------------------------------------------------------------
# static values for the CLI
# ---------------------------------------------------------------------------


def declared_statics(manifest: Manifest) -> Dict[str, str]:
    """Every variable the host supplies, as a placeholder-valued static map.

    The CLI used to require one ``--static`` flag per variable -- sixteen of
    them for the blood-pressure map, typed by hand, with no check that the
    list matched the manifest. The manifest already declares them.
    """
    statics: Dict[str, str] = {}
    for spec in manifest.passes:
        for iri in manifest.static_variables_of(spec):
            statics[iri] = PLACEHOLDER
    return statics
