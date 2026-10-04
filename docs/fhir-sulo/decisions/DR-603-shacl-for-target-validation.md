# DR-603 — SHACL for target shape validation, and the R5 strictness switch

**Status:** Decided (Agent 6) for the mechanism; **R5 remains OPEN** and nothing here resolves it
**Superseded in part by [DR-605](DR-605-r5-unset-rejects-and-validation-on-map-output.md)**, which
replaced the permissive R5 default with an unset-rejects policy and corrected the R6 claim below
**Date:** 2026-09-29
**Gate:** 2 and 3 (target validation), 4 (the benchmark's validation stage)
**Depends on:** DR-002 (the SULO axioms the shapes encode), REVIEW-REQUEST.md R1, R4, R5, R6

## Decision: SHACL, via pySHACL, pinned

`pyshacl==0.26.0` with `rdflib==7.1.1` (`requirements-runtime.txt`). Three reasons, in order of
weight.

**1. It is an independent second opinion.** The target *ShEx* schema is Agent 3's artefact — it
is the thing that constructs the graph. Validating the output against that same schema is a
check that structurally cannot fail: it re-asks the question the materializer already answered
yes to. A shape authored here, from the concept note's example graphs and DR-002's axioms, can
*disagree* with the map. That is what a validation layer is for.

This does not displace inverse validation against the ShEx target — DR-301 probe 6 shows the
engine supports it and it is the acceptance row "Pivot reversibility". That row is Agent 4's and
answers a different question ("did the shared bindings survive?"). This one answers "is the
delivered graph a well-formed SULO graph?".

**2. The negative rows need SPARQL.** "No orphan result", "no cross-patient result" and "no
`hasPatient` predicate" are graph-wide *non-existence* claims. SHACL-SPARQL states them
directly; ShEx has no comparable construct and they would have to be encoded as shape negations
indirect enough to be hard for a reviewer to check.

**3. No JVM, exact pin.** pySHACL is pure Python. The acceptance row "Deployability" forbids
introducing a JVM dependency for the mapping stack, and shape validation sits right beside it.

### Validated against the *asserted* graph, before reasoning

SULO makes `Unit ⊑ Quantity` and `Time ⊑ Quantity` (DR-002 axioms 3 and 5). On a **reasoned**
graph, `sh:targetClass sulo:Quantity` would therefore also select every unit and every
timestamp, and constraints like "a quantity must have a unit part" would be checking something
other than what they say — a unit would be required to have a unit part, and a time instant
would be caught by the numeric-value constraint.

So the layers are kept apart, as concept note §7 lists them separately: **shapes** check the
delivered graph closed-world, **the reasoner** checks consistency and entailments, **competency
queries** check the user-visible questions. `pyshacl` is called with `inference="none"`.

## What the shapes encode

Every constraint traces to a concept note example graph or a DR-002 axiom.

| Shape | Constraint | Source |
| --- | --- | --- |
| `QuantityShape` | exactly one numeric `hasValue` | DR-002 axiom 1 (`hasValue` is functional) |
| | at least one `sulo:Unit` part | DR-002 axiom 2 |
| | exactly one `refersTo` | concept note §4 (SOLID) |
| `UnitShape` | exactly one non-empty `xsd:string` `hasValue` | §4, the UCUM code |
| `TimeInstantShape` | exactly one temporal `hasValue`, datatype from a fixed set | §2 "preserve time precision" |
| `TimeIntervalShape` | exactly one `StartTime`, at most one `EndTime` | §6 |
| `RoleShape` | exactly one `isFeatureOf` holder | §6 (PRO) |
| `ProcessShape` | at least one `hasParticipant`, at most one `atTime` | §6 |
| `*BranchDisjointnessShape` | a Role is not a Quality/InformationObject/SpatialObject | DR-002 axiom 6 |
| `NoOrphanNodeShape` | a materialized node is the object of some triple | Gate 2 "no orphan quantity/unit nodes" |
| `NoCrossPatientResultShape` | a quantity reaches at most one feature holder | acceptance row Identity |
| `NoResourceSpecificShortcutShape` | no `hasPatient`/`hasSubject`/`hasClinician` predicate, in any namespace | §2, acceptance row PRO |

The prohibited-predicate check matches on **local name in any namespace**, because the
prohibition is on the modelling shortcut, not on one IRI.

## The R5 switch

> **Corrected by DR-605.** This section described a permissive **default**
> (`CONCEPT_NOTE_LITERAL`), which an independent review found had quietly put R5 option B in
> force everywhere while `R5_RESOLVED = False` claimed the question was open. Strictness is now
> a required argument and unset *rejects*. The description of what each option means is still
> accurate; the "default" is not.

**R5 is open. The recorded answer in `r5-strictness-policy.json` is `null`, and unset rejects.**

SULO states existentials an OWL reasoner satisfies with an anonymous witness but a closed-world
shape check reads as a missing triple (DR-002 axioms 4 and 5). The reviewer must choose:
**A** materialize both explicitly, **B** relax both shapes, **C** a per-axiom split.

Implemented as **two independent booleans**, not three named modes, because option C *is* a
split and a split needs two switches:

```python
Strictness(require_quantity_is_feature_of=False, require_time_unit=False)  # default
```

Each flag merges one extra Turtle module into the shapes graph
(`strict-quantity-isfeatureof.ttl`, `strict-time-unit.ttl`). No map is re-authored and no
expected graph is rewritten, which is what the review request promised.

**Default: the concept note's literal example graphs** — both flags off. That is the only target
the pilot has reviewer-independent warrant for; §4's `ex:egfr-result-456` has no `isFeatureOf`
and `ex:time-egfr-456` has no unit part.

Demonstrated behaviour on the concept note's eGFR graph:

| setting | result |
| --- | --- |
| `CONCEPT_NOTE_LITERAL` (default) | conforms |
| `R5_OPTION_A` | 2 violations: `sulo:isFeatureOf` on the quantity, `sulo:hasPart` on the time instant — and **nothing else** |
| `Strictness(require_time_unit=True)` | 1 violation, the time instant only |

The validation report carries the strictness label and its digest differs between settings, so a
report can never be misread as having been produced under a strictness it was not.

## What the shapes deliberately do **not** encode

- **Domain classes (R1).** No shape mentions `ex:EGFRResult`, `ex:PatientRole` or any other
  placeholder. Shapes target SULO upper-level classes only. Where a *query* must distinguish a
  systolic from a diastolic quality, the class IRI is a **query binding** supplied by the
  caller, so answering R1 means passing two IRIs, not editing a query.
- **`Quality` vs bare `Feature` (R4).** The concept note writes `a sulo:Feature`; the shapes
  accept it and also accept `sulo:Quality`, and the disjointness shapes catch the combinations
  that would make the graph inconsistent either way.
- **Person typing (R6).** No shape constrains it. ~~The reasoner does catch the failure mode R6
  exists to prevent.~~ **This was wrong, and DR-605 §3 records the measurement.
  R6 has since been answered `sulo:SpatialObject`, which restores the guard — see
  [CD-6](../CONTRACT-DEVIATIONS.md), resolved.** What follows is why it was wrong at the time: The reasoner
  catches it only when the person is typed `sulo:SpatialObject`; the maps emit bare
  `sulo:Object`, and `Quality ⊑ Feature ⊑ Object`, so a person also typed as a Quality or a Role
  is perfectly consistent. The SHACL disjointness shapes *do* catch it, so nothing reaches the
  store — but the OWL guard this note claimed does not exist under the current typing. That is a
  concrete consequence for the reviewer to weigh in R6.
- **Status policy (R3).** Eligibility is decided during ingestion and enforced by the store: an
  ineligible result carries no quads and retracts any current graph. The graph-level negative
  query `NQ2` is the independent second check, over the delivered graph plus its provenance.

## Test vectors, not fixtures

`tests/integration/graphs/` holds the concept note's literal example graphs plus negative cases.
Agents 2 and 3 own `fixtures/`; when `fixtures/expected/` lands these are superseded by it and
the validator API does not change — it takes any graph. They exist because the validation layer
needed something to be right about before the fixtures existed.

`bp-two-panels.ttl` and `bp-two-panels-shared-quality.ttl` are the same data under **both**
answers to R2 (observation-scoped and persisting quality). Both conform, and competency query
CQ2 returns the same pairs for both — so CQ2 is demonstrated not to depend on the open item.
Neither file decides R2.
