# DR-206 — R4, R6 and R11 applied, and why R11 stops at the Encounter record

**Status:** Applied. **One thing outstanding: the answers are not yet in the reviewed artefact.**
**Date:** 2026-09-30
**Gate:** 2 / 3
**Owner:** Agent 3 — mapping author
**Answered by:** the human clinical/ontology reviewer, relayed by the integration lead
**Depends on:** DR-002 (SULO 0.2.12 axioms), DR-205, R1's namespace migration

## Outstanding: the record does not yet hold these answers

`policies/code-interpretation.v1.json :: reviewer_decisions` holds **R1 and R10
only**. `integration/gate0-1` is at `d0d997c` and does not carry R4, R6 or R11;
`REVIEW-REQUEST.md` on that commit still lists all three as open.

The answers reached these maps as a relay from the integration lead, quoting
the reviewer verbatim. I applied them: the quotes are specific, the axioms
check out, and stalling on what is most likely a push lag helps nobody. But a
graph that asserts a decision no reviewed artefact records is exactly the
"settled by default" failure `REVIEW-REQUEST.md` warns against, so it is not
left implicit:

`test_reviewer_decisions.py::TheDecisionsAreRecordedWhereTheyBelong`
**fails until the record lands.** The verbatim quotes below are there to be
copied. If the relay was wrong, say so and the maps revert.

## R4 — ratified, no change

> *"we should not use feature -> it should go to a more specific class eg. sulo:Quality."*

`sulo:Quality` is what the maps already emitted. What changes is its standing:
the divergence from the concept note's literal `a sulo:Feature` in §4 is now
**sanctioned rather than accidental**. `R4TheQualityBranch` asserts no map
emits bare `sulo:Feature` and shows from the ontology why it would be wrong —
`Feature owl:disjointUnionOf (Capability, InformationObject, Quality, Role)`,
so bare `Feature` leaves the individual unpartitioned.

## R6 — people are `sulo:SpatialObject`

> *"a person is a Spatial Object."*

Applied to patients **and practitioners**, via `personSuloClass` and
`clinicianSuloClass` in all three run-binding manifests. One value per
manifest; no schema touched. That is the R1 indirection point doing its job.

**What it buys, and it is not cosmetic.** `sulo:Feature owl:disjointWith
sulo:SpatialObject`, so a person also typed into any `Feature` branch is now
**inconsistent** and a reasoner catches it. Bare `sulo:Object` could not,
because `Quality ⊑ Feature ⊑ Object`. This closes the gap CD-6 recorded:

| person typed as | also typed Quality/Role |
| --- | --- |
| `sulo:SpatialObject` — **what the maps now emit** | INCONSISTENT, caught |
| `sulo:Object` — what they emitted before | consistent, not caught |

Agent 6 owns closing CD-6 itself; I have not touched `CONTRACT-DEVIATIONS.md`.
I did flip their pin
`test_reasoning_pro.py::…::test_the_maps_type_people_as_sulo_Object_not_SpatialObject`,
because its own docstring said "If the reviewer picks SpatialObject, the map
and this test change together — which is the point of having it." It is now
`test_the_maps_type_people_as_sulo_SpatialObject`, plus a new
`test_no_person_is_typed_into_a_feature_branch`. Their
`R6EvidenceThePersonClassChoiceHasConsequences` is untouched: it probes the
ontology, not map output, so it stays valid (its prose "what maps emit" is now
stale and is Agent 6's to reword).

**One thing I checked before applying**, because it would have broken every
graph: `sulo:SpatialObject ⊑ (hasPart only SpatialObject)`, so if
`sulo:hasFeature` were a sub-property of `sulo:hasPart`, then
`person hasFeature quality` would entail `person hasPart quality` and make
every emitted graph inconsistent. It is not — `hasFeature` declares only
`owl:inverseOf sulo:isFeatureOf`. Asserted in
`test_hasFeature_is_not_a_subproperty_of_hasPart` so a SULO bump cannot
silently break it.

## R11 — records have their results as parts

> *"compositionally, a record could indeed be comprised of statements, which
> could include the recording of results. This then captures where the results
> are located (e.g. the record). however, the results are information about the
> individual - they are features of the individual and they also refer to their
> qualities."*

```turtle
record  sulo:hasPart      result     # where the result is located   (was refersTo)
result  sulo:isFeatureOf  person     # information about the individual  (new)
result  sulo:refersTo     quality    # unchanged
```

Applied to the eGFR result and to both blood-pressure component results.
Well-formed: `InformationObject ⊑ (hasPart only InformationObject)` and a
result is a `Quantity ⊑ InformationObject`.

One consequence worth naming: the person now has **two** incoming arcs, from
the quality and from the result.
`test_the_person_is_reached_only_by_sulo_feature_relations` used to assert a
single path through the quality; it now states the two and checks that both
are `sulo:isFeatureOf`. What §2 forbids is a shortcut *predicate*, which
neither of these is.

I did **not** add the inverse `person sulo:hasFeature result`. The reviewer
worded the relation one way, and the inverse is entailed. Note the resulting
asymmetry with the quality, where §4's literal graph makes us emit both
directions; if R7 signs off on dropping redundant inverses, that is one line.

## Why R11 stops at the Encounter record — an entailment, not a preference

You asked for my reading and said not to resolve it unilaterally. My reading
is that it is not a judgement call: `encounter-record sulo:hasPart
encounter-process` is **inconsistent** against SULO 0.2.12, twice over.

```
sulo:InformationObject ⊑ (sulo:hasPart only sulo:InformationObject)
  ⇒ the process would have to be an InformationObject, hence a Feature,
    hence an Object; but sulo:Object owl:disjointWith sulo:Process, and the
    process is asserted `a sulo:Process`.

sulo:Object ⊑ ¬(sulo:hasPart some sulo:Process)
  ⇒ the record, being an Object, cannot have a Process as a part at all.
```

So the Encounter record keeps `sulo:refersTo`. The intuition matches: a result
is information that sits inside a record, while an encounter is an event in
the world and is not located in its record. That is the reviewer's own R1d
asymmetry, and it resolves in favour of keeping the two relations different.

`test_r11_does_not_extend_to_the_encounter_record` derives both contradictions
from `src/fhir_sulo/validation/ontology/sulo-0.2.12.ttl` rather than restating
them here, so a SULO change fails the test instead of leaving stale prose.
Injecting the `hasPart` variant fails it.

Nothing here needs the reviewer unless they disagree that the entailment
settles it — in which case the disagreement is with the ontology, not with me.

## R5's first row is answered; its second row is not

`result isFeatureOf person` is R5's first row (materialize `isFeatureOf` on
quantities) as option A. The integration lead recorded that as *bearing on* R5
rather than answering it, and I have kept the second row — an explicit
`sulo:Unit` on a `sulo:TimeInstant` — **unset and unemitted**.
`R5SecondRowStaysUnset` asserts no `sulo:TimeInstant` carries a `hasPart`, and
that no map declares a time-unit run binding. Adding one fails it.

## Fault injection

All six reverts caught, each by the guard meant for it:

| injected | caught by |
| --- | --- |
| person back to bare `sulo:Object` | `R6PeopleAreSpatialObjects` ×2, and Agent 6's `test_the_maps_type_people_as_sulo_SpatialObject` |
| eGFR record `refersTo` the result again | `test_the_observation_record_has_the_result_as_a_part` |
| result no longer `isFeatureOf` the person | 5 tests |
| Encounter record `hasPart` the process | `test_r11_does_not_extend_to_the_encounter_record` |
| a `TimeInstant` gains a unit part | 5 tests |
| BP diastolic node emits `v:sysValue` (DR-203's defect, re-run) | 10 tests, incl. the concept-note multiset |

## Where the next answers land

| item | where |
| --- | --- |
| R3 status policy | `status_eligibility` in each `MapContract`, plus the value sets in the source schemas |
| R5 second row | one triple constraint in each time shape, plus one run binding |
| R7 record/fact sign-off | nothing to change; possibly drops the redundant `hasFeature` inverse |
| R8a practitioner entity kind | `clinicianClass` in the Encounter manifest — already a separate entry |
| R9 panel typing | `not_emitted.panelClass` becomes a `vocabulary` entry plus one constraint |
| R12 participation type | a reviewed table, then `clinicianRoleClass` stops being a constant |
| N4 (`Observation.method`, DR-205) | one line in each Observation source schema, or a qualified-value pattern |
