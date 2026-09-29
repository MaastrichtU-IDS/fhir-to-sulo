# DR-002 — SULO version pin and axiom findings

**Status:** Decided (pin) + **Review requested** (interpretations)
**Date:** 2026-09-29
**Gate:** 0

## Pin

| Item | Value |
| --- | --- |
| Ontology | SULO — Simplified Upper Level Ontology |
| Version | **0.2.12** (`owl:versionInfo "0.2.12"`, `owl:versionIRI sulo:sulo-0.2.12.ttl`) |
| Source file | `versions/sulo-0.2.12.ttl` in `AIDAVA-DEV/sulo` |
| Commit | `1a4abc1699471187e94fbc59591101b2b635d6ea` (main, 2026-09-07) |
| Namespace | `https://w3id.org/sulo/` |
| Size | 381 lines; 17 classes, 18 object properties, 1 datatype property |

The repository publishes no git tags, so the commit SHA is the immutable pin.

## Vocabulary verification

Every SULO term used in the concept note's worked examples **exists in 0.2.12**:

- Classes: `Quantity`, `Unit`, `Feature`, `Quality`, `Role`, `Process`, `Object`,
  `InformationObject`, `TimeInstant`, `TimeInterval`, `StartTime`, `EndTime`
- Properties: `hasValue`, `refersTo`, `isFeatureOf`, `hasFeature`, `hasParticipant`,
  `atTime`, `hasPart`

No term in the concept note is missing or misspelled.

## Confirmed: the PRO chain the plan depends on is real

```turtle
sulo:hasParticipant owl:propertyChainAxiom
    ( sulo:hasParticipant [ owl:inverseOf sulo:hasFeature ] ) .
```

Since `sulo:isFeatureOf owl:inverseOf sulo:hasFeature`, this is exactly
`hasParticipant ∘ isFeatureOf → hasParticipant`. So from

```turtle
ex:encounter-9 sulo:hasParticipant ex:patient-role-enc-9 .
ex:patient-role-enc-9 sulo:isFeatureOf ex:person-p123 .
```

a reasoner entails `ex:encounter-9 sulo:hasParticipant ex:person-p123`.
**Gate 3's entailment test is well-founded.** This was verified against the axiom, not assumed.

### Range check (a non-issue, checked because it looked like one)

`sulo:hasParticipant rdfs:range sulo:Object`, and roles are features — which looks like a
type clash. It is not: **`sulo:Feature rdfs:subClassOf sulo:Object`** in SULO, so
`Role ⊑ Feature ⊑ Object` and the range is satisfied. No inconsistency.
Note the related constraint: `sulo:Feature owl:disjointWith sulo:SpatialObject`, so a person
modelled as a `sulo:SpatialObject` must never also be typed as a `Feature`.

## Axioms that constrain the target shapes

These are properties of SULO 0.2.12 that the target ShEx/SHACL shapes must respect.

1. **`sulo:hasValue` is `owl:FunctionalProperty`**, domain `sulo:InformationObject`.
   At most one value per node. This makes the acceptance criterion "one `sulo:Quantity`
   has one numeric `hasValue`" machine-enforceable rather than aspirational.
2. **`sulo:Quantity ⊑ sulo:InformationObject`** and
   **`sulo:Quantity ⊑ (sulo:hasPart some sulo:Unit)`**. A quantity must have a unit part.
3. **`sulo:Unit ⊑ sulo:Quantity`**, and `sulo:hasPart` is reflexive and transitive, so a
   unit may satisfy its own unit-part requirement.
4. **`sulo:InformationObject ⊑ sulo:Feature ⊑ (sulo:isFeatureOf some (Object ⊔ Process))`.**
   Every quantity is therefore a feature of something. See open question Q3.
5. **`sulo:Time ⊑ sulo:Quantity`**, `sulo:Time owl:disjointWith sulo:Unit`,
   `Time owl:disjointUnionOf (Duration, TimeInstant, TimeInterval)`. A `TimeInstant`
   is a quantity and so inherits the unit-part requirement, but cannot be its own unit.
   See open question Q2.
6. **`sulo:Feature owl:disjointUnionOf (Capability, InformationObject, Quality, Role)`**,
   with a matching `owl:AllDisjointClasses`. A feature must fall in exactly one branch.
   See open question Q1.
7. `sulo:refersTo` domain `sulo:InformationObject`, range `owl:Thing`. The concept note's
   uses (`Quantity refersTo Quality`, `InformationObject refersTo Quantity`) are in domain.

## Open questions for the clinical/ontology reviewer

Consolidated with all other review items in
[`docs/fhir-sulo/REVIEW-REQUEST.md`](../REVIEW-REQUEST.md). Summarised here:

- **Q1** — Concept note §4 types the eGFR referent `a sulo:Feature, ex:RenalFiltrationQuality`.
  `sulo:Feature` is a disjoint union of four branches, so bare `Feature` leaves the individual
  unpartitioned. `sulo:Quality` ("a feature intrinsically associated with its bearer") appears
  to be the intended branch. Confirm `sulo:Quality`.
- **Q2** — Should a materialized `sulo:TimeInstant` carry an explicit time `sulo:Unit`?
  OWL leaves the existential implicit and stays satisfiable, but a closed-world ShEx/SHACL
  target shape will flag its absence. Decide: emit an explicit unit, or relax the shape.
- **Q3** — Should a materialized `sulo:Quantity` carry an explicit `sulo:isFeatureOf`?
  Same open-world/closed-world tension as Q2. The concept note's example graph omits it.

None of these are being treated as approved. Engineering continues against the concept
note's literal graphs, with the shape checks parameterised so a reviewer answer flips
them without re-authoring the maps.
