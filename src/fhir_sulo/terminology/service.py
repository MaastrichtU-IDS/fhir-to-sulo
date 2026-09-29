"""Deterministic, offline terminology and UCUM resolution.

This is the "deterministic mock terminology service" Gate 1 asks Agent 5 for.
It reads the pinned snapshot in ``policies/`` and nothing else. There is no
network client in this package - see ``assert_offline()``.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from ..policy import DecisionRecord, PolicyBundle, normalise_text
from .types import (
    CodeInterpretation,
    CodeInterpreted,
    CodeOutcome,
    CodeRejected,
    CodeSourceOnly,
    Coding,
    UnitInterpretation,
    UnitOutcome,
    UnitRef,
    UnitRejected,
    UnitResolved,
    UnitSourceOnly,
)

__all__ = ["TerminologyService"]


class TerminologyService:
    """Resolves source codes and UCUM units against the pinned policy tables."""

    def __init__(self, policy: Optional[PolicyBundle] = None) -> None:
        self.policy = policy if policy is not None else PolicyBundle.load()
        self._codes = self.policy.code_interpretation
        self._units = self.policy.unit
        self.assert_offline()

        self._code_index: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        for entry in self._codes["entries"]:
            key = (normalise_text(entry["system"]), normalise_text(entry["code"]))
            self._code_index[key] = entry

        self._unit_index: Dict[Tuple[str, str], Mapping[str, Any]] = {}
        for unit in self._units["units"]:
            key = (normalise_text(unit["system"]), normalise_text(unit["code"]))
            self._unit_index[key] = unit

    def assert_offline(self) -> None:
        """Fail loudly if a policy table ever claims a runtime lookup."""
        if self._codes["terminology_snapshot"].get("live_lookup_at_runtime"):
            raise RuntimeError(
                "code-interpretation policy requests a live terminology lookup; "
                "Gate 1 requires a deterministic offline service"
            )
        if self._units["ucum_snapshot"].get("live_lookup_at_runtime"):
            raise RuntimeError(
                "unit policy requests a live UCUM lookup; Gate 1 requires a "
                "deterministic offline service"
            )

    @property
    def policy_versions(self) -> Dict[str, str]:
        return self.policy.versions

    # -- codes -------------------------------------------------------------

    def resolve_code(
        self, coding: Coding, *, expected_kind: Optional[str] = None
    ) -> CodeOutcome:
        """Resolve one source ``Coding``.

        Returns ``CodeInterpreted`` only when a reviewed table entry says so.
        Never invents a class, never passes an unknown code through.
        """
        system = normalise_text(coding.system)
        code = normalise_text(coding.code)
        inputs = dict(coding.as_dict(), expected_kind=expected_kind)

        if not system or not code:
            return self._code_reject(
                coding,
                "TC-R6-incomplete-coding",
                "incomplete-coding",
                "a Coding needs both a system and a code; got system=%r code=%r"
                % (coding.system, coding.code),
                inputs,
            )

        systems = self._codes.get("code_systems", {})
        entry = self._code_index.get((system, code))

        if entry is None:
            if system not in systems:
                return self._code_source_only(
                    coding,
                    "TC-R3-unknown-system",
                    "unknown-code-system",
                    "code system %r is not in the pinned snapshot %s. The code is "
                    "retained in the source layer and typed nowhere."
                    % (system, self._codes["terminology_snapshot"]["snapshot_id"]),
                    inputs,
                    configured=self._codes["defaults"]["unknown_system"],
                )
            return self._code_source_only(
                coding,
                "TC-R2-unknown-code",
                "unknown-code",
                "code %r of known system %r has no reviewed interpretation entry. "
                "A FHIR code literal alone is not an OWL class assertion "
                "(concept note section 2)." % (code, system),
                inputs,
                configured=self._codes["defaults"]["unknown_code_in_known_system"],
            )

        status = normalise_text(entry["review_status"])
        if status == "rejected":
            return self._code_reject(
                coding,
                "TC-R5-entry-rejected",
                "interpretation-rejected",
                "entry %s is marked review_status 'rejected': this code must not be "
                "interpreted." % entry["entry_id"],
                inputs,
            )
        if status not in self._codes["interpretable_statuses"]:
            return self._code_source_only(
                coding,
                "TC-R4-entry-not-approved",
                "interpretation-not-approved",
                "entry %s has review_status %r, which is not in interpretable_statuses "
                "%s. The code is retained in the source layer."
                % (entry["entry_id"], status, self._codes["interpretable_statuses"]),
                inputs,
                configured=self._codes["defaults"]["review_status_proposed"],
            )

        if expected_kind is not None and normalise_text(
            entry["observation_kind"]
        ) != normalise_text(expected_kind):
            return self._code_source_only(
                coding,
                "TC-R7-kind-mismatch",
                "observation-kind-mismatch",
                "entry %s is observation_kind %r but the caller expected %r"
                % (entry["entry_id"], entry["observation_kind"], expected_kind),
                inputs,
                configured="source-only",
            )

        interpretation = CodeInterpretation(
            entry_id=entry["entry_id"],
            result_class=entry.get("result_class"),
            quality_class=entry.get("quality_class"),
            observation_kind=entry["observation_kind"],
            expected_unit_dimension=entry.get("expected_unit_dimension"),
            review_status=status,
            clinical_signoff=status in self._codes["clinically_signed_off_statuses"],
        )
        record = DecisionRecord(
            service="terminology-code",
            rule_id="TC-R1-reviewed-entry",
            status="mapped",
            inputs=inputs,
            evidence=({"source_entry": dict(entry)},),
            outcome=dict(interpretation.as_dict(), source=coding.as_dict()),
            policy_versions=self.policy_versions,
        )
        return CodeInterpreted(source=coding, record=record, interpretation=interpretation)

    # -- units -------------------------------------------------------------

    def resolve_unit(
        self, unit_ref: UnitRef, *, expected_dimension: Optional[str] = None
    ) -> UnitOutcome:
        """Resolve one UCUM unit. Never converts, never normalises silently."""
        system = normalise_text(unit_ref.system)
        code = normalise_text(unit_ref.code)
        inputs = dict(unit_ref.as_dict(), expected_dimension=expected_dimension)
        defaults = self._units["defaults"]
        expected_system = normalise_text(self._units["ucum_snapshot"]["system"])

        if not code:
            return self._unit_outcome(
                defaults["missing_unit_code"],
                unit_ref,
                "TU-R6-missing-unit-code",
                "missing-unit-code",
                "no UCUM code supplied; a numeric quantity without a unit code would "
                "be the unqualified numeric assertion the contract forbids "
                "(concept note section 2).",
                inputs,
            )

        if system != expected_system:
            return self._unit_outcome(
                defaults["unknown_unit_system"],
                unit_ref,
                "TU-R3-unknown-unit-system",
                "unknown-unit-system",
                "unit system %r is not %r; this is not a UCUM code and is not "
                "reinterpreted as one." % (unit_ref.system, expected_system),
                inputs,
            )

        entry = self._unit_index.get((system, code))
        if entry is None:
            return self._unit_outcome(
                defaults["unknown_unit_code"],
                unit_ref,
                "TU-R2-unknown-unit-code",
                "unknown-unit-code",
                "UCUM code %r is not in the pinned snapshot %s. This resolver does not "
                "parse arbitrary UCUM expressions, so the unit is not guessed "
                "(concept note section 4: unrecognized UCUM units fail the numeric "
                "target shape)."
                % (code, self._units["ucum_snapshot"]["snapshot_id"]),
                inputs,
            )

        status = normalise_text(entry["review_status"])
        if status not in self._units["interpretable_statuses"]:
            return self._unit_outcome(
                "rejected" if status == "rejected" else "rejected",
                unit_ref,
                "TU-R5-unit-not-approved",
                "unit-not-approved",
                "unit %s has review_status %r, which is not in interpretable_statuses "
                "%s." % (entry["unit_id"], status, self._units["interpretable_statuses"]),
                inputs,
            )

        dimension = normalise_text(entry["dimension"])
        if expected_dimension is not None and dimension != normalise_text(
            expected_dimension
        ):
            conversion = normalise_text(str(defaults["conversion"]))
            return self._unit_outcome(
                defaults["dimension_mismatch"],
                unit_ref,
                "TU-R4-dimension-mismatch",
                "unit-dimension-mismatch",
                "unit %r has dimension %r but %r was expected; unit conversion is %s, "
                "so the value is not normalised."
                % (code, dimension, expected_dimension, conversion),
                inputs,
            )

        interpretation = UnitInterpretation(
            unit_id=entry["unit_id"],
            ucum_code=entry["code"],
            unit_iri=entry["unit_iri"],
            dimension=dimension,
            review_status=status,
            clinical_signoff=status in self._units["clinically_signed_off_statuses"],
            converted=False,
        )
        record = DecisionRecord(
            service="terminology-unit",
            rule_id="TU-R1-pinned-unit",
            status="mapped",
            inputs=inputs,
            evidence=({"source_entry": dict(entry)},),
            outcome=dict(interpretation.as_dict(), source=unit_ref.as_dict()),
            policy_versions=self.policy_versions,
        )
        return UnitResolved(source=unit_ref, record=record, unit=interpretation)

    # -- outcome helpers ---------------------------------------------------

    def _code_source_only(
        self,
        coding: Coding,
        rule_id: str,
        reason_code: str,
        reason: str,
        inputs: Mapping[str, Any],
        *,
        configured: str,
    ) -> CodeOutcome:
        if configured not in ("source-only", "rejected"):
            raise RuntimeError(
                "code-interpretation default %r must be 'source-only' or 'rejected'; "
                "a silent pass-through is not a permitted outcome" % configured
            )
        record = DecisionRecord(
            service="terminology-code",
            rule_id=rule_id,
            status=configured,
            inputs=inputs,
            outcome={
                "source": coding.as_dict(),
                "result_class": None,
                "quality_class": None,
                "source_retained": True,
            },
            policy_versions=self.policy_versions,
            reason_code=reason_code,
            reason=reason,
        )
        cls = CodeSourceOnly if configured == "source-only" else CodeRejected
        return cls(source=coding, record=record, reason_code=reason_code, reason=reason)

    def _code_reject(
        self,
        coding: Coding,
        rule_id: str,
        reason_code: str,
        reason: str,
        inputs: Mapping[str, Any],
    ) -> CodeRejected:
        record = DecisionRecord(
            service="terminology-code",
            rule_id=rule_id,
            status="rejected",
            inputs=inputs,
            outcome={
                "source": coding.as_dict(),
                "result_class": None,
                "quality_class": None,
                "source_retained": True,
            },
            policy_versions=self.policy_versions,
            reason_code=reason_code,
            reason=reason,
        )
        return CodeRejected(
            source=coding, record=record, reason_code=reason_code, reason=reason
        )

    def _unit_outcome(
        self,
        configured: str,
        unit_ref: UnitRef,
        rule_id: str,
        reason_code: str,
        reason: str,
        inputs: Mapping[str, Any],
    ) -> UnitOutcome:
        if configured not in ("source-only", "rejected"):
            raise RuntimeError(
                "unit policy default %r must be 'source-only' or 'rejected'; a silent "
                "pass-through is not a permitted outcome" % configured
            )
        record = DecisionRecord(
            service="terminology-unit",
            rule_id=rule_id,
            status=configured,
            inputs=inputs,
            outcome={
                "source": unit_ref.as_dict(),
                "unit_iri": None,
                "converted": False,
                "source_retained": True,
            },
            policy_versions=self.policy_versions,
            reason_code=reason_code,
            reason=reason,
        )
        cls = UnitSourceOnly if configured == "source-only" else UnitRejected
        return cls(
            source=unit_ref, record=record, reason_code=reason_code, reason=reason
        )
