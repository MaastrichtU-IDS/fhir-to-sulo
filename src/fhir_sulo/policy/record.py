"""The auditable decision record emitted by every identity/terminology call.

One record per decision: input, evidence, rule applied, outcome, policy version.

Deliberately **no timestamp and no run id**. Those are run metadata and belong
in Agent 6's ``RunRecord``. Putting them here would make the record - and
therefore any digest over a batch of records - non-reproducible, which would
defeat Gate 4's "unchanged reprocessing changes no triples".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple

from .canonical import digest

__all__ = ["DecisionRecord"]


@dataclass(frozen=True)
class DecisionRecord:
    """An immutable, reproducible audit record for one policy decision."""

    service: str
    """"identity", "quality-identity", "terminology-code" or "terminology-unit"."""

    rule_id: str
    """The identifier of the policy rule that produced this outcome."""

    status: str
    """"mapped", "source-only" or "rejected" - the TransformResult vocabulary."""

    inputs: Mapping[str, Any]
    outcome: Mapping[str, Any]
    policy_versions: Mapping[str, str]
    evidence: Tuple[Mapping[str, Any], ...] = ()
    reason_code: str = ""
    reason: str = ""

    @property
    def decision_id(self) -> str:
        """sha256 over the whole record. Same decision, same id, every run."""
        return digest(self._body())

    def _body(self) -> Dict[str, Any]:
        return {
            "service": self.service,
            "rule_id": self.rule_id,
            "status": self.status,
            "inputs": dict(self.inputs),
            "evidence": [dict(e) for e in self.evidence],
            "outcome": dict(self.outcome),
            "policy_versions": dict(self.policy_versions),
            "reason_code": self.reason_code,
            "reason": self.reason,
        }

    def to_dict(self) -> Dict[str, Any]:
        body = self._body()
        body["decision_id"] = self.decision_id
        return body
