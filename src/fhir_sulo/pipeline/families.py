"""Per-family host work: which services a map needs, and what to root it at.

A map's run-binding manifest declares *that* a variable comes from the
identity or terminology service (``identity_provided``), in prose. It cannot
declare *which call* -- that a systolic quality is resolved for LOINC 8480-6
against the person from ``Observation.subject`` is family knowledge, and this
is where it lives.

Everything else is manifest-driven: the passes, their shapes, their statics,
the node keys and the conditional entry shapes all come from the manifest, so
a change there needs no change here. What each resolver contributes is the
handful of values the manifest says a service must supply.

None of this constructs a target triple. It answers questions and hands the
answers to the engine as ``staticVars``.
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from .manifest import Manifest
from .runner import lexical
from .services import ReferenceNotAPerson, entity_for_reference, quality_iri, unit_iri

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
SYSTOLIC_CODE = "8480-6"
DIASTOLIC_CODE = "8462-4"


@dataclass(frozen=True)
class ResolvedValues:
    """Everything the passes need, plus what identity actually decided."""

    values: Dict[str, Any]
    person_iri: Optional[str] = None
    notes: Tuple[str, ...] = ()


class Family:
    """One FHIR resource family's host work."""

    name: str = ""
    resource_type: str = ""
    #: the policy's quality-identity mode this map requires; None = not needed
    quality_mode: Optional[str] = "per-observation"

    def focus_iri(self, resource_id: str) -> str:
        return "https://fhir.example/%s/%s" % (self.resource_type, resource_id)

    def resolve(
        self,
        manifest: Manifest,
        bindings: Mapping[str, Any],
        context,
        identity,
        terminology,
        canonical_url: str,
    ) -> ResolvedValues:
        raise NotImplementedError


class BloodPressure(Family):
    """Blood pressure: one person, one unit, one quality per component.

    Two panels in the concept note's section 5 case are two Observation
    resources, so this runs once per resource (DR-302). ``bp-other-patient``
    has panels belonging to two different people, which is why the person is
    resolved per resource and never hoisted across panels.
    """

    name = "bp"
    resource_type = "Observation"

    def resolve(self, manifest, bindings, context, identity, terminology,
                canonical_url) -> ResolvedValues:
        person = entity_for_reference(identity, context, "Observation.subject", "Patient")
        vocab = manifest.vocabulary
        panel = lexical(bindings, "panel")
        version_id = lexical(bindings, "versionId")
        effective = lexical(bindings, "effective")

        values: Dict[str, Any] = dict(vocab)
        values.update(manifest.node_keys(panel=panel, versionId=version_id,
                                         canonicalUrl=canonical_url))
        values["person"] = person.entity_iri
        values["sysQuality"] = quality_iri(
            identity, person, vocab["sysQualityClass"], LOINC, SYSTOLIC_CODE,
            canonical_url, version_id, effective).unwrap().quality_iri
        values["unitIri"] = unit_iri(
            terminology, UCUM, lexical(bindings, "sysUnit"), "pressure")
        if lexical(bindings, "diaValue"):
            values["diaQuality"] = quality_iri(
                identity, person, vocab["diaQualityClass"], LOINC, DIASTOLIC_CODE,
                canonical_url, version_id, effective).unwrap().quality_iri
        return ResolvedValues(values=values, person_iri=person.entity_iri)


class Egfr(Family):
    """eGFR: one person, one quality keyed on the observation's own code."""

    name = "egfr"
    resource_type = "Observation"

    def resolve(self, manifest, bindings, context, identity, terminology,
                canonical_url) -> ResolvedValues:
        person = entity_for_reference(identity, context, "Observation.subject", "Patient")
        vocab = manifest.vocabulary
        values: Dict[str, Any] = dict(vocab)
        values.update(manifest.node_keys(
            obsId=lexical(bindings, "obsId"),
            versionId=lexical(bindings, "versionId"),
            canonicalUrl=canonical_url))
        values["person"] = person.entity_iri
        values["quality"] = quality_iri(
            identity, person, vocab["qualityClass"], LOINC, lexical(bindings, "code"),
            canonical_url, lexical(bindings, "versionId"),
            lexical(bindings, "effective")).unwrap().quality_iri
        values["unitIri"] = unit_iri(
            terminology, UCUM, lexical(bindings, "unitCode"), "egfr-rate")
        return ResolvedValues(values=values, person_iri=person.entity_iri)


_PARTICIPANT_RE = re.compile(r"^Encounter\.participant\[(\d+)\]\.individual$")


def _refuse_unconsulted_participants(context) -> None:
    """Fail loudly if the source carries a participant this family will not read.

    Only ``participant[0]`` is consulted. Any other index present in the
    resolved references would be dropped without trace, so refuse instead.
    """
    extra = sorted(
        path for path in context.resolved_references
        if (m := _PARTICIPANT_RE.match(path)) and m.group(1) != "0"
    )
    if extra:
        raise ReferenceNotAPerson(
            "encounter-multiple-participants",
            "this Encounter carries %d participant(s) beyond the first (%s). "
            "Only Encounter.participant[0].individual is mapped (DR-201 "
            "section 5.1: each participant needs its own role and holder IRI, "
            "and staticVars are global to a materialization). Mapping the "
            "first and discarding the rest would silently lose a participant, "
            "so the resource is refused instead."
            % (len(extra), ", ".join(extra))
        )


class Encounter(Family):
    """Encounter: two people and no quality, so no quality-identity mode."""


    name = "encounter"
    resource_type = "Encounter"
    quality_mode = None

    def resolve(self, manifest, bindings, context, identity, terminology,
                canonical_url) -> ResolvedValues:
        person = entity_for_reference(identity, context, "Encounter.subject", "Patient")

        # DR-201 section 5.1 caps Encounter.participant at cardinality 1, and
        # the ShEx source shape enforces it -- a second participant fails
        # validation loudly before reaching here. This is the SECOND guard,
        # and it is the one that matters: the ShEx cap is expected to be
        # lifted at Gate 5 for MedicationAdministration-style repeated groups,
        # and if it were lifted without touching this line, participant[1]
        # would be resolved by Agent 2 and then never consulted -- silently
        # dropped, which is exactly what the contract promises cannot happen.
        _refuse_unconsulted_participants(context)
        practitioner = entity_for_reference(
            identity, context, "Encounter.participant[0].individual", "Practitioner")
        values: Dict[str, Any] = dict(manifest.vocabulary)
        values.update(manifest.node_keys(
            encId=lexical(bindings, "encId"),
            versionId=lexical(bindings, "versionId"),
            canonicalUrl=canonical_url))
        values["person"] = person.entity_iri
        values["practitioner"] = practitioner.entity_iri
        return ResolvedValues(values=values, person_iri=person.entity_iri)


FAMILIES: Dict[str, Family] = {
    f.name: f for f in (BloodPressure(), Egfr(), Encounter())
}


def family_for(name: str) -> Family:
    try:
        return FAMILIES[name]
    except KeyError:
        raise KeyError(
            f"no host resolver for map family {name!r}; known: "
            f"{', '.join(sorted(FAMILIES))}. A new family needs one: the manifest "
            f"says a value comes from a service, not which call makes it"
        ) from None
