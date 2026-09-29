"""Status, value and modifier-extension eligibility, entirely manifest-driven.

Every outcome here traces to a rule in ``profiles/fhir-r4-pilot.json``. The
point of putting the rules in the manifest rather than in code is plan section
6: "No agent may resolve a failed semantic test by weakening its expected graph
without a recorded decision." A policy change is a manifest diff a reviewer can
read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..contracts import EligibilityOutcome, ResolvedReference
from .manifest import Manifest, default_manifest

_OUTCOME = {
    "eligible": EligibilityOutcome.ELIGIBLE,
    "source-only": EligibilityOutcome.SOURCE_ONLY,
    "rejected": EligibilityOutcome.REJECTED,
}
_SEVERITY = {
    EligibilityOutcome.ELIGIBLE: 0,
    EligibilityOutcome.SOURCE_ONLY: 1,
    EligibilityOutcome.REJECTED: 2,
}


@dataclass(frozen=True)
class EligibilityVerdict:
    outcome: EligibilityOutcome
    reasons: Tuple[str, ...]
    unsupported_modifier_extensions: Tuple[str, ...]

    @property
    def reason_text(self) -> Optional[str]:
        return "; ".join(self.reasons) if self.reasons else None


class EligibilityEvaluator:
    def __init__(self, manifest: Optional[Manifest] = None):
        self.m = manifest or default_manifest()

    def evaluate(self, resource: Dict[str, Any],
                 references: Optional[Dict[str, ResolvedReference]] = None
                 ) -> EligibilityVerdict:
        rtype = resource["resourceType"]
        findings: List[Tuple[EligibilityOutcome, str]] = []

        findings.extend(self._status(rtype, resource))
        unsupported = self._modifier_extensions(resource)
        for url in unsupported:
            findings.append((EligibilityOutcome.REJECTED,
                             f"unsupported modifier extension <{url}>: "
                             + self.m.value_policy("unsupported_modifier_extension")["reason"]))
        if rtype == "Observation":
            findings.extend(self._observation_values(resource))
        findings.extend(self._references(references or {}))

        outcome = EligibilityOutcome.ELIGIBLE
        for candidate, _ in findings:
            if _SEVERITY[candidate] > _SEVERITY[outcome]:
                outcome = candidate
        reasons = tuple(text for o, text in findings if o is not EligibilityOutcome.ELIGIBLE)
        return EligibilityVerdict(outcome, reasons, tuple(unsupported))

    # -- rules --------------------------------------------------------------

    def _status(self, rtype: str, resource: Dict[str, Any]):
        status = resource.get("status")
        if status is None:
            yield (EligibilityOutcome.REJECTED, f"{rtype}.status is absent but required")
            return
        mapped = self.m.status_outcome(rtype, str(status))
        if mapped is None:
            yield (EligibilityOutcome.REJECTED,
                   f"{rtype}.status {status!r} has no entry in the pinned status policy")
            return
        outcome = _OUTCOME[mapped]
        if outcome is not EligibilityOutcome.ELIGIBLE:
            yield (outcome, f"{rtype}.status {status!r} is {mapped} under the pinned status policy")

    def _modifier_extensions(self, node: Any, acc: Optional[List[str]] = None) -> List[str]:
        acc = acc if acc is not None else []
        supported = set(self.m.supported_modifier_extensions)
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "modifierExtension":
                    for ext in value or ():
                        url = str(ext.get("url", ""))
                        if url not in supported:
                            acc.append(url)
                else:
                    self._modifier_extensions(value, acc)
        elif isinstance(node, list):
            for item in node:
                self._modifier_extensions(item, acc)
        return acc

    def _observation_values(self, resource: Dict[str, Any]):
        yield from self._value_slot(resource, "Observation")
        for index, comp in enumerate(resource.get("component", ()) or ()):
            yield from self._value_slot(comp, f"Observation.component[{index}]")
        # Code eligibility is checked on the parent code and each component code.
        yield from self._code(resource.get("code"), "Observation.code")
        for index, comp in enumerate(resource.get("component", ()) or ()):
            yield from self._code(comp.get("code"), f"Observation.component[{index}].code")

    def _value_slot(self, node: Dict[str, Any], path: str):
        quantity = node.get("valueQuantity")
        absent = node.get("dataAbsentReason")
        if quantity is not None and absent is not None:
            p = self.m.value_policy("value_and_dataAbsentReason_both_present")
            yield (_OUTCOME[p["outcome"]], f"{path}: both a value and a dataAbsentReason: " + p["reason"])
            return
        if absent is not None:
            p = self.m.value_policy("dataAbsentReason_present")
            yield (_OUTCOME[p["outcome"]], f"{path}.dataAbsentReason present: " + p["reason"])
            return
        if quantity is None:
            return
        if "comparator" in quantity:
            p = self.m.value_policy("valueQuantity.comparator_present")
            yield (_OUTCOME[p["outcome"]],
                   f"{path}.valueQuantity.comparator {quantity['comparator']!r}: " + p["reason"])
        system, code = quantity.get("system"), quantity.get("code")
        if system is None or code is None:
            yield (EligibilityOutcome.REJECTED,
                   f"{path}.valueQuantity has no UCUM system/code; "
                   "concept note section 4: missing units fail the numeric target shape")
        elif not self.m.is_pinned_unit(str(system), str(code)):
            yield (EligibilityOutcome.REJECTED,
                   f"{path}.valueQuantity unit {code!r} in {system!r} is not in the pinned "
                   "unit set; concept note section 4: unrecognised units fail the numeric "
                   "target shape")

    def _code(self, concept: Optional[Dict[str, Any]], path: str):
        if concept is None:
            yield (EligibilityOutcome.REJECTED, f"{path} is absent but required")
            return
        codings = concept.get("coding") or ()
        if not codings:
            yield (EligibilityOutcome.REJECTED, f"{path} has no coding")
            return
        if not any(self.m.is_pinned_code(str(c.get("system")), str(c.get("code")))
                   for c in codings):
            p = self.m.value_policy("code_not_in_pinned_set")
            shown = ", ".join(f"{c.get('system')}|{c.get('code')}" for c in codings)
            yield (_OUTCOME[p["outcome"]], f"{path}: no pinned code among [{shown}]: " + p["reason"])

    def _references(self, references: Dict[str, ResolvedReference]):
        for path, ref in references.items():
            if ref.ambiguous or ref.evidence.kind == "ambiguous":
                p = self.m.value_policy("ambiguous_reference")
                yield (_OUTCOME[p["outcome"]],
                       f"{path}: ambiguous reference {ref.evidence.raw_reference!r}: " + p["reason"])
            elif ref.evidence.kind == "unresolvable":
                p = self.m.value_policy("unresolvable_reference")
                yield (_OUTCOME[p["outcome"]],
                       f"{path}: unresolvable reference {ref.evidence.raw_reference!r}: " + p["reason"])
