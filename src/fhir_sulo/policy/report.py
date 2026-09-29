"""Render the policy tables as Markdown for human review.

The JSON files stay the single source of truth; this only presents them, so
there is no second copy to drift. Run::

    python -m fhir_sulo.policy.report
"""

from __future__ import annotations

import sys
from typing import Any, Iterable, List, Mapping, Optional, Sequence

from .bundle import PolicyBundle


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value).replace("|", "\\|")
    return text or "-"


def _table(headers: Sequence[str], rows: Iterable[Sequence[Any]]) -> List[str]:
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(_cell(c) for c in row) + " |")
    return out


def render(bundle: Optional[PolicyBundle] = None) -> str:
    bundle = bundle if bundle is not None else PolicyBundle.load()
    versions = bundle.versions
    lines: List[str] = [
        "# Policy tables for review",
        "",
        "Generated from `policies/` by `python -m fhir_sulo.policy.report`. "
        "Do not edit this output; edit the JSON tables.",
        "",
        "## Versions (these go into the RunRecord)",
        "",
    ]
    lines += _table(["Key", "Value"], sorted(versions.items()))

    lines += ["", "## Code interpretation table", ""]
    lines += _table(
        ["Entry", "System", "Code", "Display (source)", "Result class", "Quality class",
         "Unit dimension", "Review status", "Reviewer"],
        [
            (
                e["entry_id"], e["system"], e["code"], e.get("display_source"),
                e.get("result_class"), e.get("quality_class"),
                e.get("expected_unit_dimension"), e["review_status"], e.get("reviewer"),
            )
            for e in bundle.code_interpretation["entries"]
        ],
    )
    lines += [
        "",
        "Interpretable statuses: `%s`. Clinically signed off: `%s`."
        % (
            "`, `".join(bundle.code_interpretation["interpretable_statuses"]),
            "`, `".join(bundle.code_interpretation["clinically_signed_off_statuses"]),
        ),
        "",
        "Unknown-code defaults: %s."
        % ", ".join(
            "%s = `%s`" % (k, _cell(v))
            for k, v in sorted(bundle.code_interpretation["defaults"].items())
        ),
    ]

    lines += ["", "## Unit policy", ""]
    lines += _table(
        ["Unit", "UCUM code", "Dimension", "Unit IRI", "Review status", "Reviewer"],
        [
            (u["unit_id"], u["code"], u["dimension"], u["unit_iri"], u["review_status"],
             u.get("reviewer"))
            for u in bundle.unit["units"]
        ],
    )
    lines += [
        "",
        "Unit defaults: %s."
        % ", ".join("%s = `%s`" % (k, _cell(v)) for k, v in sorted(bundle.unit["defaults"].items())),
    ]

    identity = bundle.identity
    lines += ["", "## Identity policy", ""]
    lines += _table(
        ["Setting", "Value"],
        [
            ("key style", identity["entity_iri"]["key_style"]),
            ("key inputs", ", ".join(identity["entity_iri"]["key_input_fields"])),
            ("reference scope default", identity["reference_scope"]["default"]),
            ("cross-source merge", identity["reference_scope"]["cross_source_merge"]),
            ("approved merge evidence",
             ", ".join(identity["reference_scope"]["accepted_merge_evidence"]) or "none"),
            ("quality identity mode", identity["quality_identity"]["mode"]),
            ("quality identity status", identity["quality_identity"]["mode_status"]),
        ],
    )
    lines += ["", "### Resolution rules", ""]
    lines += _table(
        ["Rule", "When", "Outcome", "Reason code"],
        [
            (r["rule_id"], r["when"], r["then"], r.get("reason_code"))
            for r in identity["resolution_rules"]
        ],
    )

    lines += ["", "## Open questions for the clinical/ontology reviewer", ""]
    lines.append("1. **Quality identity.** %s" % identity["quality_identity"]["reviewer_question"])
    n = 2
    for entry in bundle.code_interpretation["entries"]:
        if entry.get("reviewer_note"):
            lines.append("%d. **%s.** %s" % (n, entry["entry_id"], entry["reviewer_note"]))
            n += 1
    for question in bundle.unit.get("reviewer_questions", []):
        lines.append("%d. %s" % (n, question))
        n += 1
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.stdout.write(render())
